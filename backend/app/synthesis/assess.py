"""Study-level quality screening and finding-level statistical uncertainty.

This is a transparent, rule-based *screen*, not a formal risk-of-bias tool (Cochrane RoB 2, ROBINS-I) or full GRADE:
  * design tier and sample size come from verified claims (or PubMed's publication type as a fallback)
  * bias signals are text patterns (randomization, concealment, blinding, ITT, registration, funding/COI) located in stored
    passages; each signal keeps the passage it was found in. With only an abstract, a missing signal is "not assessable",
    never "absent".
  * statistical uncertainty is computed from the reported interval/p-value; inconsistent numbers are flagged.
"""
import math
import re
from dataclasses import dataclass, field

DESIGN_WEIGHT = {"rct": 1.0, "meta_analysis": 0.9, "rct_secondary_analysis": 0.6, "cohort": 0.5,
                 "case_control": 0.35, "cross_sectional": 0.3, "other": 0.2, "unknown": 0.2}
DESIGN_RANK = {"rct": 0, "meta_analysis": 0, "rct_secondary_analysis": 1, "cohort": 2, "case_control": 3, "cross_sectional": 3, "other": 4, "unknown": 4}
RATIO = {"HR", "RR", "OR"}
EXPERIMENTAL = {"rct", "rct_secondary_analysis"}

# (key, label, regex, kind): kind 'good' = presence lowers concern, 'risk' = presence raises concern
SIGNALS_RCT = [
    ("randomization", "Randomization described", re.compile(r"\brandomi[sz]", re.I), "good"),
    ("concealment", "Allocation concealment / central randomization", re.compile(
        r"allocation concealment|concealed allocation|sealed[, ]+opaque|central(?:ly|ized|ised)? randomi[sz]|interactive (?:web|voice)[- ]response|\bIWRS\b|\bIVRS\b|\bIRT\b", re.I), "good"),
    ("blinding", "Blinding (double/triple-blind, masked)", re.compile(r"double[- ]blind|triple[- ]blind|single[- ]blind|\bmasked\b|participants? (?:and|or) investigators? (?:were )?blind", re.I), "good"),
    ("open_label", "Open-label / unblinded", re.compile(r"open[- ]label|unblinded|not blinded|without blinding|no blinding", re.I), "risk"),
    ("placebo", "Placebo or sham control", re.compile(r"placebo|sham[- ]", re.I), "good"),
    ("itt", "Intention-to-treat analysis", re.compile(r"intention[- ]to[- ]treat|\bITT\b|modified intention", re.I), "good"),
    ("registration", "Trial registered", re.compile(r"\bNCT\s?\d{8}|ISRCTN\s?\d+|ChiCTR[-\w]*|ACTRN\d+|EudraCT|UMIN\d+|ClinicalTrials\.gov|trial regist|PROSPERO", re.I), "good"),
    ("attrition", "Attrition / loss to follow-up reported", re.compile(r"lost to follow[- ]up|loss to follow[- ]up|withdr[ae]w|drop[- ]?outs?|discontinued (?:the )?(?:study|treatment|intervention)", re.I), "good"),
]
SIGNALS_OBS = [
    ("confounding", "Adjustment for confounders", re.compile(r"adjusted for|multivariable|multivariate|propensity|confound|covariates?", re.I), "good"),
    ("prospective", "Prospective cohort", re.compile(r"prospective", re.I), "good"),
    ("self_report", "Self-reported exposure (FFQ, questionnaire, recall)", re.compile(r"self[- ]report|food frequency|\bFFQ\b|questionnaire|24[- ]?h(?:our)? recall|dietary recall", re.I), "risk"),
]
SIGNAL_FUNDING = ("industry_funding", "Industry funding / ties", re.compile(
    r"Boehringer|AstraZeneca|Novartis|Merck|Pfizer|Eli Lilly|\bLilly\b|Bayer|Novo Nordisk|Janssen|Sanofi|Abbott|Amgen|GlaxoSmithKline|\bGSK\b|Roche|Takeda|Daiichi|Vifor|Boston Scientific|Medtronic|sponsored by|funded by .{0,40}(?:company|pharma|industry)", re.I), "risk")
NO_COI = re.compile(r"no (?:competing|conflicts?|potential conflicts?)|declare[sd]? no|nothing to disclose|no financial", re.I)


@dataclass
class Signal:
    key: str
    label: str
    kind: str                      # good | risk | context
    status: str                    # present | absent | not_assessable
    passage_uid: str | None = None
    snippet: str | None = None
    basis: str | None = None       # fulltext | abstract


def _snip(text: str, m: re.Match, width: int = 110) -> str:
    a, b = max(0, m.start() - width // 2), min(len(text), m.end() + width // 2)
    return ("…" if a else "") + text[a:b].strip() + ("…" if b < len(text) else "")


def screen_signals(design: str, passages: list[dict], has_fulltext: bool) -> list[Signal]:
    """passages: dicts with uid, text, section, doc_kind. Missing signals are 'absent' only if full text was searched."""
    specs = (SIGNALS_RCT if design in EXPERIMENTAL or design == "meta_analysis" else SIGNALS_OBS)
    if design == "meta_analysis":
        specs = [s for s in SIGNALS_RCT if s[0] in ("registration",)]
    out: list[Signal] = []
    body = [p for p in passages if p["section"] != "funding_coi"] if has_fulltext else passages
    for key, label, rx, kind in specs:
        hit = None
        for p in body:
            m = rx.search(p["text"])
            if m:
                hit = (p, m)
                if p["doc_kind"] == "pmc_jats":
                    break
        if hit:
            out.append(Signal(key, label, kind, "present", hit[0]["uid"], _snip(hit[0]["text"], hit[1]), "fulltext" if hit[0]["doc_kind"] == "pmc_jats" else "abstract"))
        else:
            out.append(Signal(key, label, kind, "absent" if has_fulltext else "not_assessable", basis="fulltext" if has_fulltext else "abstract"))
    # funding / conflicts: only in full text (abstracts do not carry them)
    key, label, rx, kind = SIGNAL_FUNDING
    fund = [p for p in passages if p["section"] == "funding_coi"]
    if has_fulltext and fund:
        hit = next(((p, m) for p in fund if (m := rx.search(p["text"]))), None)
        if hit:
            out.append(Signal(key, label, kind, "present", hit[0]["uid"], _snip(hit[0]["text"], hit[1]), "fulltext"))
        else:
            out.append(Signal(key, label, kind, "absent", fund[0]["uid"], None, "fulltext"))
    else:
        out.append(Signal(key, label, kind, "not_assessable", basis="abstract" if not has_fulltext else "fulltext"))
    return out


def rob_level(design: str, signals: list[Signal]) -> tuple[str, list[str]]:
    """Coarse screen. Returns (level, reasons). level: lower | some | higher | not_assessable"""
    sig = {s.key: s for s in signals}
    reasons: list[str] = []
    if design in EXPERIMENTAL:
        core = [sig[k] for k in ("randomization", "concealment", "blinding", "itt", "registration") if k in sig]
        assessable = [s for s in core if s.status != "not_assessable"]
        absent = [s.label for s in core if s.status == "absent"]
        present = [s for s in core if s.status == "present"]
        if sig.get("open_label") and sig["open_label"].status == "present":
            reasons.append("open-label design")
        if not assessable:
            return "not_assessable", ["only the abstract was available"]
        if sig["randomization"].status != "present":
            return "higher", ["randomization not described"]
        reasons += [f"not found in full text: {a.lower()}" for a in absent]
        if sig["open_label"].status == "present" or len(absent) >= 3:
            return "higher", reasons
        if absent or any(s.status == "not_assessable" for s in core):
            if len(present) >= 3 and not absent:
                return "lower", ["abstract reports " + ", ".join(s.label.lower() for s in present)] + reasons
            return "some", reasons or ["only part of the design is assessable from the abstract"]
        return "lower", [f"{len(present)} of {len(core)} core safeguards found"]
    if design in ("cohort", "case_control", "cross_sectional"):
        s = sig.get("confounding")
        if s and s.status == "present":
            reasons.append("adjusts for confounders (residual confounding still possible)")
            if sig.get("self_report") and sig["self_report"].status == "present":
                reasons.append("self-reported exposure")
            return "some", reasons
        if s and s.status == "absent":
            return "higher", ["no confounder adjustment found in full text"]
        return "not_assessable", ["observational study; abstract does not describe adjustment"] if (s and s.status == "not_assessable") else ["unknown"]
    if design == "meta_analysis":
        return "not_assessable", ["pooled analysis: quality of the included studies was not assessed here"]
    return "not_assessable", ["design not classified"]


def size_weight(n: int | None) -> tuple[float, str]:
    if n is None:
        return 0.6, "unknown"
    for cut, w, label in ((50, 0.4, "very small"), (100, 0.55, "small"), (300, 0.7, "modest"), (1000, 0.85, "moderate"), (10**12, 1.0, "large")):
        if n < cut:
            return w, label
    return 1.0, "large"


ROB_WEIGHT = {"lower": 1.0, "some": 0.85, "higher": 0.65, "not_assessable": 0.9}


@dataclass
class FindingStats:
    significant: bool | None          # None: no interval or p-value reported
    basis: str                        # ci | p | none
    precision: str                    # precise | moderate | imprecise | unclassified
    se: float | None
    flags: list[str] = field(default_factory=list)


def _null(m: str | None, lo: float) -> float:
    if m in RATIO:
        return 1.0
    if m == "MD":
        return 0.0
    return 0.0 if lo <= 0 else 1.0           # scale unknown: an interval reaching <= 0 can only be a difference


def finding_stats(f: dict) -> FindingStats:
    m, lo, hi, p = f.get("effect_measure"), f.get("ci_low"), f.get("ci_high"), f.get("p_value")
    flags: list[str] = []
    has_ci = lo is not None and hi is not None
    ci_sig = (not (lo <= _null(m, lo) <= hi)) if has_ci else None
    if m in RATIO | {"MD"} and ci_sig is not None:
        sig, basis = ci_sig, "ci"                # a stated interval on a known scale is authoritative
    elif p is not None:
        sig, basis = p < 0.05, "p"
    elif ci_sig is not None:
        sig, basis = ci_sig, "ci"
    else:
        sig, basis = None, "none"
    if p is not None and ci_sig is not None and (p < 0.05) != ci_sig:
        flags.append("p_value_and_ci_disagree")
    se, prec = None, "unclassified"
    if has_ci and lo > 0 and hi > 0 and m in RATIO:
        width = math.log(hi / lo)
        se = width / (2 * 1.96)
        prec = "precise" if width < 0.35 else "moderate" if width < 0.8 else "imprecise"
    elif has_ci and m == "MD":
        se = (hi - lo) / (2 * 1.96)
    if sig is None:
        flags.append("no_uncertainty_reported")
    return FindingStats(sig, basis, prec, se, flags)
