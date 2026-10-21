"""LLM access behind one small interface; the provider is configuration (LLM_PROVIDER / LLM_MODEL / LLM_API_KEY).

* AnthropicLLM       - Anthropic Messages API, forced tool call.
* OpenAICompatLLM    - OpenAI and OpenRouter (same chat-completions protocol), forced function call.
* CassetteLLM        - wraps any client; `record` saves responses to disk, `replay` serves them. This is what makes
                       evaluation and CI reproducible without network or API key. Cassettes are keyed by
                       sha256(text + model + prompt + schema version), so switching model never reuses another's output.
Every provider is asked for the same thing (the Pydantic schema as one forced tool call), so downstream validation,
verification and evaluation are provider-independent.
"""
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import httpx

from ..config import settings
from ..ingestion.http import ApiClient, RetryableHTTPError

TOOL_NAME = "record_evidence"
PROVIDERS = ("anthropic", "openai", "openrouter", "google")
DEFAULT_MODELS = {"anthropic": "claude-sonnet-5-5", "openai": "gpt-5-nano-2025-08-07",
                  "openrouter": "deepseek/deepseek-chat", "google": "gemini-2.5-flash"}
# OpenAI, OpenRouter and Google (Gemini's OpenAI-compatible endpoint) share one chat-completions client; Anthropic has its own.
BASE_URLS = {"openai": "https://api.openai.com/v1", "openrouter": "https://openrouter.ai/api/v1",
             "google": "https://generativelanguage.googleapis.com/v1beta/openai"}


def gemini_schema(schema: dict) -> dict:
    """Gemini accepts only a subset of JSON Schema: no $ref/$defs, no anyOf, no default/title. Inline the references and turn
    `anyOf: [X, null]` into X with nullable=true. Pydantic validation after the call is still the real contract."""
    defs = schema.get("$defs", {})

    def walk(node):
        if isinstance(node, list):
            return [walk(x) for x in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            return walk(defs[node["$ref"].rsplit("/", 1)[-1]])
        if "anyOf" in node:
            options = [o for o in node["anyOf"] if o.get("type") != "null"]
            out = walk(options[0]) if len(options) == 1 else {}
            return {**out, "nullable": True} if len(options) < len(node["anyOf"]) else out
        out = {}
        for k, v in node.items():
            if k in ("$defs", "default", "title", "additionalProperties", "examples", "$schema"):
                continue
            out[k] = {pk: walk(pv) for pk, pv in v.items()} if k == "properties" else walk(v)
        return out

    return walk({k: v for k, v in schema.items() if k != "$defs"})


@dataclass
class LLMResponse:
    output: dict
    usage: dict = field(default_factory=dict)
    model: str = ""


class LLMClient(Protocol):
    model: str
    provider: str

    def complete(self, key: str, system: str, user: str, tool_schema: dict) -> LLMResponse: ...


class CassetteMiss(RuntimeError):
    pass


class LLMConfigError(RuntimeError):
    pass


class LLMFatalError(RuntimeError):
    """Auth/billing failure (401/402/403): retrying or continuing the batch is pointless, so it aborts the run."""


class AnthropicLLM:
    provider = "anthropic"

    def __init__(self, model: str, api_key: str):
        import anthropic
        self.model = model
        self._anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=api_key)

    def complete(self, key, system, user, tool_schema):
        kwargs = dict(
            model=self.model, max_tokens=4096, system=system,
            messages=[{"role": "user", "content": user}],
            tools=[{"name": TOOL_NAME, "description": "Record the extracted evidence.", "input_schema": tool_schema}],
            tool_choice={"type": "tool", "name": TOOL_NAME},
        )
        try:
            resp = self.client.messages.create(temperature=0, **kwargs)
        except self._anthropic.BadRequestError as e:
            if "temperature" not in str(e).lower():
                raise
            resp = self.client.messages.create(**kwargs)   # model does not accept temperature
        block = next((b for b in resp.content if b.type == "tool_use"), None)
        if block is None:
            raise RuntimeError("model returned no tool call")
        return LLMResponse(dict(block.input),
                           {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens},
                           self.model)


def _json_from_text(text: str) -> dict:
    """Fallback for models that answer in prose/JSON instead of honoring the forced tool call."""
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S) or re.search(r"(\{.*\})", text, re.S)
    if not m:
        raise RuntimeError("model returned neither a tool call nor JSON")
    return json.loads(m.group(1))


class OpenAICompatLLM:
    """OpenAI, OpenRouter and Google. Non-strict function calling: our schema (nested optionals, $defs) is not
    OpenAI strict-mode compatible, and Pydantic validation after the call is the real contract anyway."""

    def __init__(self, provider: str, model: str, api_key: str, api: ApiClient | None = None):
        self.provider, self.model = provider, model
        headers = {"Authorization": f"Bearer {api_key}"}
        if provider == "openrouter":
            headers["X-Title"] = "Longevidence"
        base = BASE_URLS[provider] if api is None else BASE_URLS.get(provider, "")
        # free OpenRouter models allow ~20 requests/minute: pace ourselves instead of burning retries on 429s
        rate = 0.3 if model.endswith(":free") else 5
        self.api = api or ApiClient(base, per_second=rate, max_attempts=4, backoff_initial=2.0,
                                    client=httpx.Client(base_url=base, timeout=180, headers=headers))

    def _body(self, system: str, user: str, schema: dict, *, temperature: bool) -> dict:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "tools": [{"type": "function", "function": {"name": TOOL_NAME, "description": "Record the extracted evidence.",
                                                        "parameters": gemini_schema(schema) if self.provider == "google" else schema}}],
            "tool_choice": {"type": "function", "function": {"name": TOOL_NAME}},
        }
        # OpenAI's reasoning models need max_completion_tokens and spend part of it on hidden reasoning
        # Reasoning models spend part of the budget on hidden thinking; a small cap truncates the answer mid-JSON.
        if self.provider == "openai":
            body["max_completion_tokens"] = 16000
        else:
            body["max_tokens"] = 16000
        if temperature:
            body["temperature"] = 0
        return body

    def _post(self, body: dict):
        try:
            return self.api.post("/chat/completions", body)
        except RetryableHTTPError as e:
            if "429" in str(e):    # still rate-limited after backoff: quota (e.g. free-model daily cap). Stop; the cache lets you resume.
                raise LLMFatalError(f"{self.provider} rate/quota limit reached ({e}); completed responses are cached, re-run later to resume") from e
            raise

    def complete(self, key, system, user, tool_schema):
        r = self._post(self._body(system, user, tool_schema, temperature=True))
        if r.status_code == 400 and "temperature" in r.text.lower():      # e.g. gpt-5 family: default only
            r = self._post(self._body(system, user, tool_schema, temperature=False))
        if r.status_code in (401, 402, 403):              # auth/billing: stop, keep the cache
            raise LLMFatalError(f"{self.provider} HTTP {r.status_code}: {r.text[:300]}")
        if r.status_code >= 400:
            raise RuntimeError(f"{self.provider} HTTP {r.status_code}: {r.text[:300]}")
        data = r.json()
        if data.get("error"):                                              # OpenRouter reports upstream errors in a 200
            raise RuntimeError(f"{self.provider} error: {str(data['error'])[:300]}")
        choice = data["choices"][0]
        if choice.get("finish_reason") == "length":
            raise RuntimeError(f"{self.provider} response truncated at the output-token limit (reasoning model?)")
        msg = choice["message"]
        calls = msg.get("tool_calls")
        output = json.loads(calls[0]["function"]["arguments"]) if calls else _json_from_text(msg.get("content") or "")
        u = data.get("usage") or {}
        return LLMResponse(output, {"input_tokens": u.get("prompt_tokens", 0), "output_tokens": u.get("completion_tokens", 0)},
                           data.get("model") or self.model)


class CassetteLLM:
    def __init__(self, directory: Path, mode: str, inner: LLMClient | None = None, model: str | None = None,
                 provider: str | None = None):
        assert mode in ("replay", "record", "live")
        self.dir, self.mode, self.inner = Path(directory), mode, inner
        self.model = model or (inner.model if inner else resolved_model())
        self.provider = provider or (inner.provider if inner else settings.llm_provider)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key):
        return self.dir / f"{key}.json"

    def complete(self, key, system, user, tool_schema):
        p = self._path(key)
        if self.mode == "replay" or (self.mode == "record" and p.exists()):
            if not p.exists():
                raise CassetteMiss(f"no recorded response for {key[:12]}; run with LLM_MODE=record and an API key")
            d = json.loads(p.read_text())
            return LLMResponse(d["output"], d.get("usage", {}), d.get("model", self.model))
        if self.inner is None:
            raise CassetteMiss("live/record mode needs an LLM client (set LLM_API_KEY)")
        resp = self.inner.complete(key, system, user, tool_schema)
        if self.mode == "record":
            p.write_text(json.dumps({"provider": self.provider, "model": resp.model, "usage": resp.usage,
                                     "output": resp.output}, indent=1))
        return resp


def resolved_model() -> str:
    return settings.llm_model or DEFAULT_MODELS.get(settings.llm_provider, "")


def resolved_api_key() -> str:
    return settings.llm_api_key


def build_provider(provider: str, model: str, api_key: str) -> LLMClient:
    if provider not in PROVIDERS:
        raise LLMConfigError(f"unknown LLM_PROVIDER {provider!r}; use one of {', '.join(PROVIDERS)}")
    if not api_key:
        raise LLMConfigError(f"LLM_API_KEY is not set for provider {provider!r}")
    if not model:
        raise LLMConfigError("LLM_MODEL is not set")
    return AnthropicLLM(model, api_key) if provider == "anthropic" else OpenAICompatLLM(provider, model, api_key)


def default_client() -> CassetteLLM:
    """Client from env config. In replay mode no key is needed (and none is used)."""
    provider, model = settings.llm_provider, resolved_model()
    inner = None
    if settings.llm_mode != "replay":
        inner = build_provider(provider, model, resolved_api_key())
    return CassetteLLM(settings.data_dir / "cassettes", settings.llm_mode, inner, model, provider)


def llm_status() -> dict:
    """Is a real model configured? Never exposes the key. Used to decide whether topic ingestion is offered at all."""
    provider, model = settings.llm_provider, resolved_model()
    if provider not in PROVIDERS:
        return {"ready": False, "provider": provider, "model": model, "reason": f"unknown LLM_PROVIDER {provider!r}"}
    if not resolved_api_key():
        return {"ready": False, "provider": provider, "model": model, "reason": "no LLM_API_KEY configured"}
    if not model:
        return {"ready": False, "provider": provider, "model": model, "reason": "LLM_MODEL is not set"}
    return {"ready": True, "provider": provider, "model": model, "reason": None}


def ingest_client() -> CassetteLLM:
    """Live client for topic ingestion. Always calls the provider (and records responses, so a retried job reuses them),
    regardless of LLM_MODE, which governs the offline evaluation harness."""
    st = llm_status()
    if not st["ready"]:
        raise LLMConfigError(st["reason"])
    inner = build_provider(st["provider"], st["model"], resolved_api_key())
    return CassetteLLM(settings.data_dir / "cassettes", "record", inner, st["model"], st["provider"])
