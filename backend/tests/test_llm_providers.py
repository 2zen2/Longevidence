import json

import httpx
import pytest

from app.extraction import llm
from app.extraction.llm import LLMConfigError, OpenAICompatLLM, build_provider
from app.extraction.schema import tool_schema

SCHEMA = tool_schema()
OUT = {"study": {"design": {"status": "not_reported"}}}


def make(provider, httpx_mock_unused=None):
    from app.ingestion.http import ApiClient
    base = llm.BASE_URLS[provider]
    api = ApiClient(base, per_second=1000, max_attempts=3, backoff_initial=0.001,
                    client=httpx.Client(base_url=base, headers={"Authorization": "Bearer k"}))
    return OpenAICompatLLM(provider, "m-1", "k", api=api)


def tool_reply(args=OUT, **extra):
    return {"model": "m-1-served", "usage": {"prompt_tokens": 11, "completion_tokens": 7},
            "choices": [{"message": {"tool_calls": [{"function": {"name": llm.TOOL_NAME, "arguments": json.dumps(args)}}]}}], **extra}


def test_openrouter_request_shape_and_parse(httpx_mock):
    httpx_mock.add_response(url="https://openrouter.ai/api/v1/chat/completions", json=tool_reply())
    r = make("openrouter").complete("k", "sys", "usr", SCHEMA)
    body = json.loads(httpx_mock.get_requests()[0].content)
    assert body["tool_choice"]["function"]["name"] == llm.TOOL_NAME and body["temperature"] == 0
    assert body["max_tokens"] == 16000 and "max_completion_tokens" not in body
    assert body["tools"][0]["function"]["parameters"] == SCHEMA
    assert r.output == OUT and r.usage == {"input_tokens": 11, "output_tokens": 7} and r.model == "m-1-served"


def test_openai_uses_max_completion_tokens_and_drops_temperature_when_rejected(httpx_mock):
    httpx_mock.add_response(status_code=400, json={"error": {"message": "Unsupported value: 'temperature' does not support 0"}})
    httpx_mock.add_response(json=tool_reply())
    r = make("openai").complete("k", "s", "u", SCHEMA)
    first, second = (json.loads(x.content) for x in httpx_mock.get_requests())
    assert "temperature" in first and "temperature" not in second
    assert first["max_completion_tokens"] == 16000 and "max_tokens" not in first
    assert r.output == OUT


def test_falls_back_to_json_in_content_when_no_tool_call(httpx_mock):
    reply = {"choices": [{"message": {"content": "Here you go:\n```json\n" + json.dumps(OUT) + "\n```"}}]}
    httpx_mock.add_response(json=reply)
    assert make("openrouter").complete("k", "s", "u", SCHEMA).output == OUT


def test_openrouter_error_inside_200_is_raised(httpx_mock):
    httpx_mock.add_response(json={"error": {"message": "provider overloaded", "code": 502}})
    with pytest.raises(RuntimeError, match="provider overloaded"):
        make("openrouter").complete("k", "s", "u", SCHEMA)


def test_auth_error_is_not_retried(httpx_mock):
    httpx_mock.add_response(status_code=401, text="bad key")
    with pytest.raises(RuntimeError, match="HTTP 401"):
        make("openai").complete("k", "s", "u", SCHEMA)
    assert len(httpx_mock.get_requests()) == 1


def test_transient_429_is_retried(httpx_mock):
    httpx_mock.add_response(status_code=429, headers={"Retry-After": "0"})
    httpx_mock.add_response(json=tool_reply())
    assert make("openrouter").complete("k", "s", "u", SCHEMA).output == OUT


def test_build_provider_validation_and_dispatch():
    assert build_provider("openrouter", "deepseek/deepseek-chat", "k").provider == "openrouter"
    assert build_provider("openai", "gpt-5-nano-2025-08-07", "k").provider == "openai"
    assert build_provider("anthropic", "claude-sonnet-5-5", "k").provider == "anthropic"
    for bad in (("nope", "m", "k"), ("openai", "m", ""), ("openai", "", "k")):
        with pytest.raises(LLMConfigError):
            build_provider(*bad)


def test_default_client_resolution(monkeypatch, tmp_path):
    from app.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "llm_model", "")
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(settings, "llm_mode", "replay")
    c = llm.default_client()                       # replay needs no key; model falls back to provider default
    assert (c.provider, c.model, c.inner) == ("openai", "gpt-5-nano-2025-08-07", None)
    monkeypatch.setattr(settings, "llm_mode", "record")
    with pytest.raises(LLMConfigError, match="LLM_API_KEY"):
        llm.default_client()
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    monkeypatch.setattr(settings, "llm_api_key", "k")
    assert llm.default_client().inner.provider == "anthropic"
    monkeypatch.setattr(settings, "llm_provider", "google")
    monkeypatch.setattr(settings, "llm_model", "")
    assert llm.default_client().model == "gemini-2.5-flash"


def test_billing_error_is_fatal_and_aborts_extraction(httpx_mock):
    from app.extraction.llm import LLMFatalError
    from app.extraction.runner import extract_text
    httpx_mock.add_response(status_code=402, text="insufficient credits")
    with pytest.raises(LLMFatalError, match="402"):
        extract_text("T", "RESULTS: x", [], make("openrouter"))
    assert len(httpx_mock.get_requests()) == 1


def test_exhausted_rate_limit_is_fatal_not_a_per_paper_error(httpx_mock):
    from app.extraction.llm import LLMFatalError
    for _ in range(3):
        httpx_mock.add_response(status_code=429, headers={"Retry-After": "0"})
    with pytest.raises(LLMFatalError, match="rate/quota"):
        make("openrouter").complete("k", "s", "u", SCHEMA)


def test_truncated_response_is_a_clear_error(httpx_mock):
    httpx_mock.add_response(json={"choices": [{"finish_reason": "length", "message": {"content": '{"study": {"des'}}]})
    with pytest.raises(RuntimeError, match="truncated"):
        make("openrouter").complete("k", "s", "u", SCHEMA)


def test_google_uses_gemini_openai_endpoint_and_flattened_schema(httpx_mock):
    httpx_mock.add_response(url="https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", json=tool_reply())
    assert make("google").complete("k", "s", "u", SCHEMA).output == OUT
    params = json.loads(httpx_mock.get_requests()[0].content)["tools"][0]["function"]["parameters"]
    text = json.dumps(params)
    for banned in ("$ref", "$defs", "anyOf", '"default"', '"title"'):
        assert banned not in text
    assert "nullable" in text and params["type"] == "object"


def test_gemini_schema_inlines_refs_and_nullable():
    from app.extraction.llm import gemini_schema
    src = {"$defs": {"A": {"type": "object", "title": "A", "properties": {"x": {"anyOf": [{"type": "integer"}, {"type": "null"}], "default": None}}}},
           "type": "object", "properties": {"a": {"$ref": "#/$defs/A"}, "b": {"anyOf": [{"$ref": "#/$defs/A"}, {"type": "null"}]}}}
    out = gemini_schema(src)
    assert out["properties"]["a"] == {"type": "object", "properties": {"x": {"type": "integer", "nullable": True}}}
    assert out["properties"]["b"]["nullable"] is True and "x" in out["properties"]["b"]["properties"]


def test_removed_providers_are_rejected(monkeypatch):
    from app.config import settings
    assert llm.PROVIDERS == ("anthropic", "openai", "openrouter", "google")
    assert not hasattr(settings, "cloudflare_account_id") and not hasattr(settings, "anthropic_api_key")
    with pytest.raises(LLMConfigError, match="unknown LLM_PROVIDER"):
        build_provider("cloudflare", "m", "k")
