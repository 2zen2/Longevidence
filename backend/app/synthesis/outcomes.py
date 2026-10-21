"""Which outcome a finding is about, and what kind of evidence that outcome is.

Extracted findings carry an outcome string like "All-cause mortality, highest vs lowest quintile saturated fat" or "IBD onset, high cholesterol
intake". Only the part before the first comma / "per" / "(" / "vs" ... (the OUTCOME HEAD) names the outcome; the rest describes the contrast
or the exposure. Matching the question's outcome terms against the whole string let exposure words ("cholesterol intake", "without diabetes")
count as outcomes, so matching is done on the head only.

Outcomes are also tiered, because a verdict that mixes LDL cholesterol with myocardial infarction is not a verdict about either:
  tier 1  clinical events and primary outcomes (death, MI, stroke, cancer, incident diabetes, fractures, falls, function ...)
  tier 2  validated surrogates and anthropometrics (LDL/total cholesterol, triglycerides, blood pressure, HbA1c, body weight/BMI/waist)
  tier 3  other biomarkers (glucose, insulin, inflammatory markers, NAD+, microbiota ...)
The classification is a small hand-written lexicon (below); it is deliberately visible and testable, not learned.
"""
import re

TIER_LABEL = {1: "clinical events and primary outcomes", 2: "validated surrogate markers (lipids, blood pressure, HbA1c, body weight)",
              3: "other biomarkers"}

# ---- outcome head
_CUT = re.compile(r",|;|:|\(|\[| - | – | vs\.? | versus | per | with | during | among | in | at | after | by | between | from | over | across | compared | comparing ", re.I)
_RELATED = re.compile(r"[\w-]*-related\b", re.I)          # 'non-obesity-related cancer' is a cancer outcome, not an obesity one


_LEAD = re.compile(r"^(?:the\s+)?(?:(?:mean|median|between-group|within-group|absolute|relative|percent(?:age)?|net|overall|adjusted)\s+)*"
                   r"(?:differences?|changes?|reductions?|decreases?|increases?|improvements?|incidence|risk|rates?|number|reduction|time)\s+(?:in|of|for|to)\s+(?:first\s+)?", re.I)
_CORR = re.compile(r"^(?:correlations?|associations?|relationships?|links?)\s+(?:of|between)\s+.+?\s+(?:with|and)\s+(?P<o>.+)$", re.I)


def outcome_head(outcome: str) -> str:
    """The outcome noun phrase: text before the first comma / 'per' / '(' / 'vs' / 'with' / 'in' ... Falls back to the whole string.
    Leading wrappers ('Change in', 'Between-group difference in', 'Correlation of X with') are removed first."""
    o = " ".join((outcome or "").split())
    m = _CORR.match(o)
    if m:
        o = m.group("o")
    for _ in range(3):
        o2 = _LEAD.sub("", o, count=1)
        if o2 == o:
            break
        o = o2
    head = _CUT.split(o, maxsplit=1)[0].strip(" -–/") if o else ""
    head = _RELATED.sub(" ", head).strip()
    return head or o


# ---- outcome classes (what the question's terms and the finding's head can share)
CLASSES: dict[str, re.Pattern] = {k: re.compile(v, re.I) for k, v in {
    "mortality": r"mortalit|death|died|survival|fatal",
    "cardiovascular": r"cardiovascular|\bcvd\b|cardiac|heart (?:disease|attack|failure)|coronary|\bchd\b|\bcad\b|myocardial|\bmi\b|stroke|cerebrovascular|"
                      r"\bcbd\b|isch[a]?emic|atheroscler|\bmace\b|angina|revasculari|cardiomyopath|\bhf\b|\bhhf\b|\bhfref\b|\bhfpef\b",
    "heart_failure": r"heart failure|\bhf\b|\bhhf\b|hfref|hfpef",
    "cancer": r"cancer|carcinoma|tumou?r|neoplas|malignan|leuk[a]?emia|lymphoma|melanoma|oncolog",
    "diabetes": r"diabet|\bt2dm?\b|\bgdm\b",
    "lipids": r"cholesterol|\bldl|\bhdl|lipoprotein|lipid|triglycerid|apolipo|\bapob\b",
    "blood_pressure": r"blood pressure|\bsbp\b|\bdbp\b|systolic|diastolic|hypertens|\bbp\b",
    "weight": r"weight|\bbmi\b|body mass|adipos|obes|overweight|waist|fat mass|body fat|fat accumulation|girth|\bfat loss",
    "glycemic": r"hba1c|glycat|glyc[a]?emi|glucose|\bhoma|insulin|prediabet",
    "kidney": r"kidney|renal|\bckd\b|egfr|nephro|albuminuria|dialysis",
    "fracture": r"fractur",
    "falls": r"\bfalls?\b|\bfall-",
    "bone": r"bone (?:mineral )?density|\bbmd\b|osteopor",
}.items()}

# ---- tiers (checked from the most "surrogate" end, so 'fasting glucose' is tier 3 and 'LDL cholesterol' tier 2 even though both hit a class)
_TIER3 = re.compile(r"\binsulin\b|homa|glucose|\bcrp\b|c-reactive|interleukin|\bil-\d|\btnf|leptin|ghrelin|adiponectin|microbio|\bnad\b|nad\+|hormone|"
                    r"biomarker|\bmarkers?\b|oxidative|inflamm|lipidome|metabolite|plasma|serum|urinary|cortisol|testosterone|endothelial|"
                    r"flow[- ]mediated|arterial stiffness|\bcimt\b|intima|ejection fraction|\blvef\b|cardiac function|left ventricular|\bnt-?pro-?bnp\b|\bbnp\b|troponin|echocardiograph", re.I)
_TIER2 = re.compile(r"\bapo ?b\b|\bldl|\bhdl|cholesterol|triglycerid|lipid|lipoprotein|apolipo|blood pressure|\bsbp\b|\bdbp\b|systolic|diastolic|\bbp\b|hba1c|glycated|"
                    r"glyc[a]?emic control|body weight|\bweight\b|\bbmi\b|body mass|waist|fat mass|body fat|adipos|bone (?:mineral )?density|\bbmd\b|"
                    r"hypertension|overweight|obesity", re.I)
# 'incident'/'risk' wording promotes a nominally surrogate class to a clinical event: incident hypertension/obesity/diabetes are diagnoses, but
# the lexicon above keeps hypertension and obesity at tier 2 because the studies here report them as continuous measures far more often.


def tier_of(head: str) -> int:
    h = (head or "").lower()
    if _TIER3.search(h) and not re.search(r"mortalit|death|diabet(?:es)?\b(?! control)", h):
        return 3
    if _TIER2.search(h) and not re.search(r"mortalit|death|\bcardiovascular (?:disease|event)|incident", h):
        return 2
    return 1


# ---- mortality qualifiers
_ALLCAUSE = re.compile(r"\b(?:all[- ]?cause|any[- ]cause|total|overall|premature|early|late|long[- ]term|short[- ]term|follow[- ]up|time to|risk of|"
                       r"adjusted|unadjusted|crude|\d+[- ]?(?:days?|months?|years?|yrs?)|incidence of|rate of|the|of|and|or|in|survival|"
                       r"mortality|deaths?|died|fatal|risk|rate|rates)\b", re.I)


def mortality_qualifier(head: str) -> str:
    """'' for plain all-cause mortality, else the words that make it cause- or setting-specific ('lung cancer-specific', 'ICU', 'neonatal')."""
    rest = _ALLCAUSE.sub(" ", re.sub(r"[-/]", " ", head.lower()))
    return " ".join(w for w in re.findall(r"[a-z0-9+]+", rest) if len(w) > 1 or w.isdigit()).strip()


def classes_of(text: str) -> set[str]:
    return {c for c, rx in CLASSES.items() if rx.search(text or "")}


def topic_classes(terms: list[str]) -> set[str]:
    out: set[str] = set()
    for t in terms:
        out |= classes_of(t)
    return out


def topic_best_tier(terms: list[str]) -> int:
    """The tier the question itself is about: the best (lowest) tier among its outcome terms. 'weight loss' -> 2, 'cardiovascular events' -> 1."""
    return min((tier_of(t) for t in terms), default=1)


def match_outcome(outcome: str, terms: list[str], free: bool = False) -> tuple[bool, int, str]:
    """-> (does the finding's outcome answer one of the question's outcome terms, tier, head).

    Preset topics: a term matches the head when its phrase occurs, every one of its words (stemmed) occurs, or the head and the term share an
    outcome class (so 'myocardial infarction' answers a question about 'cardiovascular' outcomes). Mortality is special: plain all-cause mortality
    answers a question about mortality; cause-specific or setting-specific mortality ('lung cancer-specific', 'ICU', '28-day sepsis') answers it only
    when the question asks about that cause.
    Free text: terms are outcome phrases; the head noun of the phrase (or a synonym) must occur in the finding's head."""
    head = outcome_head(outcome)
    tier = tier_of(head)
    low = head.lower()
    if free:
        return _match_free(low, terms), tier, head
    classes = classes_of(low)
    tcls = topic_classes(terms)
    if "mortality" in classes and CLASSES["mortality"].search(re.sub(r"[^a-z ]", " ", low)):
        q = mortality_qualifier(low)
        if not q:
            return ("mortality" in tcls or any(CLASSES["mortality"].search(t) for t in terms)), tier, head
        qcls = classes_of(q) - {"mortality"}
        if qcls:
            return bool(qcls & tcls), tier, head
        lit = any(t.lower() in low for t in terms if len(t) > 3 and not CLASSES["mortality"].search(t))
        return lit, tier, head                                   # unrecognised qualifier ('ICU', 'neonatal', 'sepsis'): only if the question names it
    ow = set(re.findall(r"[a-z0-9]+", low))
    ow_stem = {_stem(w) for w in ow}
    for t in terms:
        tl = t.lower()
        if tl in low:
            return True, tier, head
        words = re.findall(r"[a-z0-9]+", tl)
        if words and all(w in ow or _stem(w) in ow_stem for w in words):
            return True, tier, head
    # same outcome class ('myocardial infarction' answers 'cardiovascular'), but a head that is a lesser kind of outcome than anything the question names
    # ('cardiac function' for a question about heart-failure hospitalisation and death) does not
    return bool(classes & tcls) and tier <= max((tier_of(t) for t in terms), default=1), tier, head


_SUF = re.compile(r"(ations?|ation|ings?|ing|ies|ied|es|ed|s)$")


def _stem(w: str) -> str:
    w = w.lower()
    return _SUF.sub("", w) if len(w) > 4 else w


def _match_free(low: str, terms: list[str]) -> bool:
    from ..search.bm25 import tokenize
    from ..search.synonyms import expand
    from .interpret import MORTALITY_QUALIFIERS
    ot = set(tokenize(low))
    for t in terms:
        toks = tokenize(t.lower())
        if not toks:
            continue
        head = toks[-1]
        if not (expand(head) & ot):
            continue
        if expand(head) & expand("mortality"):
            qual = [q for q in MORTALITY_QUALIFIERS if q in low]
            asked = [q for q in MORTALITY_QUALIFIERS if q in t.lower()]
            if qual and not asked:
                continue                                  # asked about mortality in general; this is a cause-specific one
            if asked and not any(q in low for q in asked):
                continue                                  # asked about cardiovascular (etc.) mortality; this is not
        return True
    return False
