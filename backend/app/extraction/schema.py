"""Extraction schema. Every extracted claim carries its own provenance (quote, section, offsets) and a
verification state. The LLM fills quote/section/status; offsets and verification are set by our verifier,
so the model can never vouch for its own citations."""
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

SCHEMA_VERSION = "1"

# Fields written only by the verifier (stripped from the schema shown to the LLM).
VERIFIER_FIELDS = {"char_start", "char_end", "verification", "notes"}
Verification = Literal["exact", "fuzzy", "failed", "n/a", "unchecked"]


class Design(str, Enum):
    rct = "rct"                                    # primary report of a randomized trial
    rct_secondary_analysis = "rct_secondary_analysis"  # post-hoc / pre-specified / pooled analysis of RCT(s)
    cohort = "cohort"
    case_control = "case_control"
    cross_sectional = "cross_sectional"
    meta_analysis = "meta_analysis"
    other = "other"


class Located(BaseModel):
    quote: str | None = Field(None, description="Verbatim text copied from the source supporting this claim.")
    section: str | None = Field(None, description="Label of the abstract section the quote comes from.")
    confidence: Literal["high", "medium", "low"] | None = None
    # --- set by verifier, never trusted from the model ---
    char_start: int | None = None
    char_end: int | None = None
    verification: Verification = "unchecked"
    notes: list[str] = Field(default_factory=list)


class Provenance(Located):
    status: Literal["reported", "not_reported"] = Field(
        description="'not_reported' if the text does not state this; never guess.")

    @model_validator(mode="after")
    def _abstain_means_empty(self):
        if self.status == "not_reported":
            object.__setattr__(self, "value", None)
        return self


class StrField(Provenance):
    value: str | None = None


class IntField(Provenance):
    value: int | None = None


class DesignField(Provenance):
    value: Design | None = None


class Finding(Located):
    outcome: str = Field(description="The outcome this result is about, e.g. 'HF hospitalization or CV death'.")
    direction: Literal["favors_intervention", "favors_comparator", "no_difference", "unclear"]
    effect_measure: Literal["HR", "RR", "OR", "MD", "other"] | None = None
    effect_value: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    p_value: float | None = Field(None, description="Number as written; for 'P<0.001' give 0.001.")
    quote: str = Field(description="Verbatim sentence(s) stating this result, including the numbers.")


class StudyCharacteristics(BaseModel):
    design: DesignField
    population: StrField
    sample_size: IntField = Field(description="Number randomized/enrolled analyzed, not screened.")
    intervention: StrField
    comparator: StrField
    follow_up: StrField


class PaperExtraction(BaseModel):
    study: StudyCharacteristics
    primary_findings: list[Finding] = Field(
        default_factory=list, description="Main efficacy results with numbers, max 5. Empty if none reported.")
    limitations_stated: list[StrField] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)   # set by pipeline (e.g. design_disagrees_with_pubmed)


def tool_schema(require_quotes: bool = False) -> dict:
    """JSON schema for the forced tool call, minus verifier-owned fields.

    require_quotes (prompt v2): `status`, `value` and `quote` become required keys on every provenance field, so a model cannot
    treat the quote as optional. `null` stays valid for fields that are not reported."""
    def strip(node):
        if isinstance(node, dict):
            if "properties" in node:
                node["properties"] = {k: strip(v) for k, v in node["properties"].items()
                                      if k not in VERIFIER_FIELDS and k != "flags"}
            return {k: (strip(v) if k != "properties" else v) for k, v in node.items()}
        if isinstance(node, list):
            return [strip(x) for x in node]
        return node
    s = strip(PaperExtraction.model_json_schema())
    s["required"] = [r for r in s.get("required", []) if r != "flags"]
    if require_quotes:
        for name in ("StrField", "IntField", "DesignField"):
            d = s.get("$defs", {}).get(name)
            if d:
                d["required"] = sorted(set(d.get("required", [])) | {"status", "value", "quote"})
    return s
