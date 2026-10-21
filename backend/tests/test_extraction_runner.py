import json

import pytest

from app.extraction.llm import CassetteLLM, CassetteMiss, LLMResponse
from app.extraction.runner import extract_text

TITLE = "T"
TEXT = "RESULTS: We randomized 100 patients to drug or placebo."
SECTIONS = [{"label": "RESULTS", "start": 0, "end": len(TEXT)}]
NR = {"status": "not_reported"}
GOOD = {"study": {"design": NR, "population": NR, "intervention": NR, "comparator": NR, "follow_up": NR,
                  "sample_size": {"status": "reported", "value": 100, "quote": "We randomized 100 patients"}},
        "primary_findings": []}


class Scripted:
    model = "scripted"
    provider = "test"

    def __init__(self, *outs):
        self.outs, self.calls = list(outs), []

    def complete(self, key, system, user, schema):
        self.calls.append((key, user))
        return LLMResponse(self.outs.pop(0), {"input_tokens": 10, "output_tokens": 5}, self.model)


def test_valid_output_is_verified():
    r = extract_text(TITLE, TEXT, SECTIONS, Scripted(GOOD))
    assert r.status == "ok" and r.extraction.study.sample_size.verification == "exact"
    assert r.usage == {"input_tokens": 10, "output_tokens": 5}


def test_invalid_then_repaired_once():
    bad = {"study": {"design": {"status": "reported", "value": "not-a-design", "quote": "x"}}}
    llm = Scripted(bad, GOOD)
    r = extract_text(TITLE, TEXT, SECTIONS, llm)
    assert r.status == "ok" and r.attempts == 2
    assert "failed validation" in llm.calls[1][1] and llm.calls[1][0].endswith(".repair")


def test_gives_up_after_one_repair():
    bad = {"nope": 1}
    r = extract_text(TITLE, TEXT, SECTIONS, Scripted(bad, bad))
    assert r.status == "invalid" and r.extraction is None and r.attempts == 2


def test_tool_schema_hides_verifier_fields():
    from app.extraction.schema import tool_schema
    s = json.dumps(tool_schema())
    for hidden in ("char_start", "char_end", '"verification"', '"notes"', '"flags"'):
        assert hidden not in s


def test_cassette_record_then_replay(tmp_path):
    rec = CassetteLLM(tmp_path, "record", Scripted(GOOD), model="scripted")
    r1 = extract_text(TITLE, TEXT, SECTIONS, rec)
    replay = CassetteLLM(tmp_path, "replay", None, model="scripted")
    r2 = extract_text(TITLE, TEXT, SECTIONS, replay)
    assert r1.extraction.model_dump() == r2.extraction.model_dump()
    with pytest.raises(CassetteMiss):
        CassetteLLM(tmp_path, "replay", None, model="scripted").complete("unknown", "", "", {})
    # a miss inside the runner is reported as an error status, not a crash
    r3 = extract_text(TITLE, "different text", SECTIONS, replay)
    assert r3.status == "error" and "no recorded response" in r3.error


def test_double_encoded_nested_values_are_decoded_then_validated():
    enc = {"study": json.dumps(GOOD["study"]), "primary_findings": json.dumps([])}
    r = extract_text(TITLE, TEXT, SECTIONS, Scripted(enc))
    assert r.status == "ok" and r.extraction.study.sample_size.verification == "exact"
    still_bad = extract_text(TITLE, TEXT, SECTIONS, Scripted({"study": "not json"}, {"study": "not json"}))
    assert still_bad.status == "invalid"          # decoding never bypasses validation


def test_prompt_versions_are_selectable_and_v1_is_frozen():
    from app.extraction.prompts import SYSTEM_V1, SYSTEM_V2, get_prompt
    assert get_prompt("v1") == SYSTEM_V1 and get_prompt("v2") == SYSTEM_V2
    assert SYSTEM_V2.startswith(SYSTEM_V1) and "No quote, no value" in SYSTEM_V2 and '"status": "reported"' in SYSTEM_V2
    assert "No quote, no value" not in SYSTEM_V1       # v1 results/cassettes must stay reproducible


def test_prompt_version_is_part_of_the_cache_key():
    from app.extraction.runner import input_hash
    assert input_hash("t", "x", "m", "v1") != input_hash("t", "x", "m", "v2")


def _unquoted():
    d = json.loads(json.dumps(GOOD))
    d["study"]["design"] = {"status": "reported", "value": "rct"}          # reported, no quote
    return d


def _quoted():
    d = json.loads(json.dumps(GOOD))
    d["study"]["design"] = {"status": "reported", "value": "rct", "quote": "We randomized 100 patients"}
    return d


def test_v2_sends_back_reported_values_without_quotes_once():
    llm = Scripted(_unquoted(), _quoted())
    r = extract_text(TITLE, TEXT, SECTIONS, llm, prompt_version="v2")
    assert r.status == "ok" and r.attempts == 2 and r.extraction.study.design.quote
    assert "study.design" in llm.calls[1][1] and llm.calls[1][0].endswith(".repair")


def test_v2_keeps_first_answer_if_repair_is_worse_or_fails():
    r = extract_text(TITLE, TEXT, SECTIONS, Scripted(_unquoted(), {"nonsense": 1}), prompt_version="v2")
    assert r.status == "ok" and r.extraction.study.design.quote is None
    assert r.extraction.study.design.verification == "failed" and "missing_quote" in r.extraction.study.design.notes   # still measured

    class Boom(Scripted):
        def complete(self, key, *a):
            if key.endswith(".repair"):
                raise RuntimeError("upstream 500")
            return super().complete(key, *a)
    r2 = extract_text(TITLE, TEXT, SECTIONS, Boom(_unquoted()), prompt_version="v2")
    assert r2.status == "ok" and r2.extraction is not None


def test_v1_does_not_enforce_quotes():
    llm = Scripted(_unquoted())
    r = extract_text(TITLE, TEXT, SECTIONS, llm, prompt_version="v1")
    assert r.status == "ok" and r.attempts == 1 and len(llm.calls) == 1


def test_v2_tool_schema_requires_quote_keys_but_v1_does_not():
    from app.extraction.schema import tool_schema
    v1, v2 = tool_schema(), tool_schema(require_quotes=True)
    assert "quote" not in v1["$defs"]["StrField"]["required"]
    assert {"status", "value", "quote"} <= set(v2["$defs"]["StrField"]["required"])
    assert {"status", "value", "quote"} <= set(v2["$defs"]["DesignField"]["required"])
