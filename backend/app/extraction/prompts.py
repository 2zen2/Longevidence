"""Prompt versions. v1 is frozen (results and cassettes depend on it); changes go in a new version.

v2 adds, in response to failures seen in the v1 evaluations:
  * an exact JSON skeleton to copy (a model on a Workers AI endpoint ignored the tool schema and invented its own structure)
  * "no quote, no value" (22% of DeepSeek's reported values came with no quote at all)
  * direction 'unclear' for outcomes with no good/bad direction (hormone levels, biomarkers)
Select with PROMPT_VERSION=v2.
"""
from ..config import settings

SYSTEM_V1 = """You extract structured evidence from the title and abstract of one biomedical paper.

Rules (these matter more than completeness):
1. Use ONLY the text provided. No outside knowledge, no inference from the drug or trial name.
2. Every reported value needs a `quote`: copy it VERBATIM from the text (same characters, no paraphrase,
   no ellipsis). Keep quotes short, one sentence or clause. `section` is the label it appears under
   (e.g. METHODS); use "ABSTRACT" if unlabeled.
3. If the text does not state a field, set status="not_reported" and leave value and quote null.
   An honest not_reported is correct; a guessed value is an error.
4. Numbers (sample size, effect size, CI, p) must appear in your quote exactly as written.
5. design: "rct" = primary report of a randomized trial; "rct_secondary_analysis" = post-hoc,
   pre-specified, subgroup, biomarker, pooled or other secondary analysis of randomized trial data.
6. sample_size = participants randomized/enrolled in the analysis described, not those screened.
7. primary_findings: the main efficacy results that have a stated effect estimate (max 5). direction is
   relative to the intervention vs comparator, judged from the estimate and CI as written: CI crossing
   the null => "no_difference". Leave out results that do not report an effect estimate.
8. limitations_stated: only limitations the authors explicitly state. Usually empty for abstracts.
9. confidence: how sure you are that the value is stated exactly as extracted."""

SYSTEM_V2 = SYSTEM_V1 + """

Additional rules (version 2):
10. Output format. Return ONE JSON object shaped exactly like this example (values are illustrative). Every one of the six
    `study` fields is an OBJECT with at least "status"; never a bare string or number. Do not add other keys.
{"study": {
   "design":       {"status": "reported", "value": "rct", "quote": "<verbatim text>", "section": "METHODS", "confidence": "high"},
   "sample_size":  {"status": "reported", "value": 191, "quote": "<verbatim text containing 191>", "section": "RESULTS", "confidence": "high"},
   "population":   {"status": "reported", "value": "adults with type 2 diabetes", "quote": "<verbatim text>", "section": "METHODS", "confidence": "medium"},
   "intervention": {"status": "reported", "value": "empagliflozin 10 mg", "quote": "<verbatim text>", "section": "METHODS", "confidence": "high"},
   "comparator":   {"status": "not_reported"},
   "follow_up":    {"status": "not_reported"}},
 "primary_findings": [{"outcome": "HbA1c change at 4 months", "direction": "no_difference", "effect_measure": "MD",
   "effect_value": -0.22, "ci_low": -0.72, "ci_high": 0.30, "p_value": 0.40, "quote": "<verbatim sentence with the numbers>",
   "section": "RESULTS", "confidence": "high"}],
 "limitations_stated": []}
    design must be one of: rct, rct_secondary_analysis, cohort, case_control, cross_sectional, meta_analysis, other.
    effect_measure must be one of HR, RR, OR, MD, other. direction must be one of favors_intervention, no_difference,
    favors_comparator, unclear. Numbers are JSON numbers (0.74, not "0.74"; CI bounds are separate fields).
11. No quote, no value: if you cannot copy a verbatim quote that supports a field, set status="not_reported" instead.
12. direction "unclear" is for an outcome with no good/bad direction (for example a hormone level or biomarker). For an
    exposure study (for example higher intake vs lower), the "intervention" is the higher or exposed group, so a harmful
    association is "favors_comparator"."""

SYSTEMS = {"v1": SYSTEM_V1, "v2": SYSTEM_V2}
PROMPT_VERSION = settings.prompt_version if settings.prompt_version in SYSTEMS else "v1"
SYSTEM = SYSTEMS[PROMPT_VERSION]


def get_prompt(version: str) -> str:
    return SYSTEMS[version]


def user_prompt(title: str, text: str) -> str:
    return f"Title: {title}\n\nAbstract (the only source text):\n<abstract>\n{text}\n</abstract>"
