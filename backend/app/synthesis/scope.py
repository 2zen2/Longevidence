"""Which arm is the exposure, and is this study in scope at all.

Two judgements the stance logic depends on, made once and explicitly:

1. ORIENTATION. A finding's direction ("favors_intervention") is only meaningful relative to the arm that has MORE or LESS of the exposure the
   question is about. The intervention arm may be the exposure ("high butter"), a reduction of it ("replacing saturated fat with unsaturated"),
   a composition change ("higher P:S ratio" = less saturated fat), or merely the alternative to the exposure ("olive oil vs butter": the exposure
   is the COMPARATOR arm). `exposure_less()` says whether the intervention arm has less of the exposure; `stance_of` then flips accordingly.

2. SCOPE. Some studies mention the exposure and an outcome the question lists but answer a different question: infants and pregnancy outcomes
   in a question about adults, ICU/sepsis/COVID mortality, mortality among cancer survivors, tax-policy and global-burden analyses, pooled
   exposures that include the opposite of the exposure ("unsweetened and sugar-sweetened tea"). `scope_exclusion()` returns a reason code and the
   matched text so the exclusion is logged and shown, never silent.
"""
import re

from .outcomes import classes_of

# ------------------------------------------------------------------------------------------------ exposure terms in text
_SUFFIX = r"(?:s|es|i|d|ed|ing|ation|ated|ic|\d)?"
_NEG_BEFORE = r"(?<!non-)(?<!non )(?<!non)(?<!un)(?<!anti-)"


def term_rx(term: str) -> re.Pattern:
    """Whole-word match for a term ('nut' must not hit 'nutrition', 'saturated fat' must not hit 'unsaturated fat' or 'non-saturated fat'); hyphen,
    space or nothing between the words of the term ('ultra-processed' = 'ultraprocessed'); a few inflections allowed."""
    toks = [re.escape(t) for t in re.findall(r"[a-z0-9]+", (term or "").lower())]
    if not toks:
        return re.compile(r"(?!x)x")
    return re.compile(r"(?<![a-z0-9])" + _NEG_BEFORE + r"[\s_\-]*".join(toks) + _SUFFIX + r"(?![a-z0-9])", re.I)


_RX_CACHE: dict[str, re.Pattern] = {}


def has_term(text: str, term: str) -> bool:
    rx = _RX_CACHE.get(term)
    if rx is None:
        rx = _RX_CACHE[term] = term_rx(term)
    return bool(rx.search(text or ""))


def has_any(text: str, terms: list[str]) -> bool:
    return any(has_term(text, t) for t in terms)


def strip_terms(text: str, terms: list[str]) -> str:
    """Remove phrases that look like the exposure but are not it ('plant-based oils' in a question about plant-based diets)."""
    out = text or ""
    for t in terms or []:
        out = term_rx(t).sub(" ", out)
    return out


# ------------------------------------------------------------------------------------------------ orientation
_FILL = r"(?:(?:the|in|of|dietary|total|your|intake of|consumption of|quintile of|quartile of|tertile of|intake|consumption|levels? of)[\s-]+){0,3}"
_PREFIX = (r"(?:reduc\w*|lower\w*|decreas\w*|limit\w*|restrict\w*|cut(?:ting)?(?: back on| down on)?|avoid\w*|minimi[sz]\w*|less|fewer|low|"
           r"eliminat\w*|exclud\w*|no|without|free of|zero)")
_SUFFIXES = r"(?:reduction|reduced|substitutes?|alternatives?|restriction|restricted|avoidance|lowering|limitation|minimi[sz]ation|exclusion|elimination|cut|cutting)"
_CALORIE = re.compile(r"(?:very[- ])?(?:low|reduced)[- ](?:calorie|energy|kcal|caloric)\w*|(?:caloric|calorie|energy)[- ]restrict\w*|time[- ]restrict\w*", re.I)

_REPL_VERB = re.compile(r"replac\w*\s+(?:the\s+|a\s+|\d[\w%./ ]*?\s+(?:of|from)\s+)?(?P<a>[^,;()]{3,80}?)\s+(?:with|by|for)\s+(?P<b>[^,;()]{3,80})", re.I)
_REPL_SUBST = re.compile(r"substitut\w*\s+(?:of\s+)?(?:\d[\w%./ ]*?\s+(?:of|from)\s+)?(?P<b>[^,;()]{3,80}?)\s+for\s+(?P<a>[^,;()]{3,80})", re.I)
_REPL_SUBST2 = re.compile(r"substitut\w*\s+(?P<a>[^,;()]{3,80}?)\s+(?:with|by)\s+(?P<b>[^,;()]{3,80})", re.I)
_REPL_INSTEAD = re.compile(r"(?P<b>[^,;()]{3,80}?)\s+(?:instead of|in place of|rather than)\s+(?P<a>[^,;()]{3,80})", re.I)
_REPL_NOUN = re.compile(r"(?P<x>[\w][\w-]*(?: [\w-]+){0,3}?)\s+(?:staple\s+)?(?:replacement|substitution)\b", re.I)
_RATIO = re.compile(r"(?P<dir>higher|greater|increased|high|lower|reduced|low)?\s*\b(?P<n>[A-Za-z]{1,16})\s*(?::|/|\bto\b)\s*(?P<d>[A-Za-z]{1,16})\s+(?:fatty acid\s+)?ratio\b", re.I)
RATIO_ALIASES = {"s": "saturated fat", "sfa": "saturated fat", "sfas": "saturated fat", "saturated": "saturated fat", "p": "polyunsaturated fat",
                 "pufa": "polyunsaturated fat", "polyunsaturated": "polyunsaturated fat", "unsaturated": "unsaturated fat", "m": "monounsaturated fat",
                 "mufa": "monounsaturated fat", "monounsaturated": "monounsaturated fat", "ps": "polyunsaturated fat"}


_LIST = re.compile(r"\b((?:[a-z][\w-]*(?:,\s*(?:and\s+)?|\s+and\s+))+[a-z][\w-]*)\s+(meats?|beverages?|drinks?|fats?|oils?|proteins?|vegetables?|fruits?|grains?|diets?)\b", re.I)


def distribute_lists(text: str) -> str:
    """'higher red, processed, and white meat intake' -> 'higher red meat, processed meat, white meat intake', so each member of the list can be judged."""
    def fix(m):
        items = re.split(r",\s*(?:and\s+)?|\s+and\s+", m.group(1))
        return ", ".join(f"{i} {m.group(2)}" for i in items)
    return _LIST.sub(fix, text or "")


class Exposure:
    """What counts as 'the exposure' in text, for a preset (curated phrases) or a free-text reading (stemmed tokens)."""

    def __init__(self, interp):
        self.preset = interp.source == "preset"
        self.terms = (list(interp.concepts[0]) + list(getattr(interp, "exposure_extra", []) or [])) if (self.preset and interp.concepts) else []
        self.free_stems = [] if self.preset else [t for t in (interp.exposure_terms or []) if len(t) > 2]
        self.not_terms = list(getattr(interp, "exposure_not", []) or [])

    def hit(self, text: str) -> bool:
        text = strip_terms(distribute_lists(text), self.not_terms)
        if self.preset:
            return has_any(text, self.terms)
        from ..search.bm25 import tokenize
        from ..search.synonyms import expand
        hay = set(tokenize(text or ""))
        return any(expand(s) & hay for s in self.free_stems)

    def term_alt(self) -> str:
        if self.preset:
            parts = [r"[\s_\-]*".join(re.escape(t) for t in re.findall(r"[a-z0-9]+", term.lower())) for term in self.terms]
        else:
            parts = [re.escape(s) + r"\w*" for s in self.free_stems]
        for term in (self.terms if self.preset else []):       # 'low-sodium' / 'sodium reduction' name a nutrient whose reduction is the exposure: 'low sodium diet' must hit
            m = re.match(r"(?:low|reduced|restricted)[ -](sodium|salt|sugar|fat|saturated fat|cholesterol|purine|fructose)\b", term.lower()) or \
                re.match(r"(sodium|salt|sugar|fat|saturated fat|cholesterol)\b.* (?:reduction|restriction)$", term.lower())
            if m:
                parts.append(re.escape(m.group(1)))
        parts = [p for p in parts if p]
        return "(?:" + "|".join(parts) + ")" if parts else r"(?!x)x"


def _less_cue(expo: Exposure, text: str) -> bool:
    """A reduction word attached directly to the exposure: 'low sodium', 'reducing salt', 'sodium reduction', 'lowest quintile of saturated fat'.
    'Low-fat vegan diet' and 'very-low-calorie ketogenic diet' do not count: the reduced thing is not the exposure."""
    t = _CALORIE.sub(" ", text or "")
    alt = expo.term_alt()
    if re.search(r"(?<![a-z])" + _PREFIX + r"[\s-]+" + _FILL + alt, t, re.I):
        return True
    return bool(re.search(alt + r"(?:[\s-]+(?:intake|consumption|levels?|content))?[\s-]+" + _SUFFIXES, t, re.I))


_CONTRAST_MORE = re.compile(r"\b(?:highest|higher|high|top|upper|greater|more|Q[2-5]|T3|T2)\b[^,;]{0,40}?\b(?:vs\.?|versus|compared (?:to|with)|than)\b[^,;]{0,25}?"
                            r"\b(?:lowest|lower|low|bottom|least|fewer|none|never|non-?consumers?|Q1|T1|0 ?(?:g|mg|ml|servings?))\b|"
                            r"\bper (?:additional |extra |each )?\d[\d.,]*\s*(?:g|mg|ml|mL|kcal|servings?|cups?)|\bper (?:serving|increment|SD)\b|"
                            r"\beach (?:additional|extra|increment)", re.I)


def _contrast(expo: Exposure, text: str) -> tuple[bool | None, str]:
    """'highest vs lowest quintile of red meat', 'per 100 mg/d dietary cholesterol': the finding itself contrasts MORE with LESS of the exposure."""
    if text and _CONTRAST_MORE.search(text) and expo.hit(text):
        return False, "finding contrasts higher with lower intake of the exposure"
    return None, ""


def _replacement(expo: Exposure, text: str) -> tuple[bool | None, str]:
    """-> (exposure is the REPLACED thing -> True / the thing introduced -> False / undecided -> None, basis)"""
    for rx in (_REPL_VERB, _REPL_SUBST, _REPL_SUBST2, _REPL_INSTEAD):
        m = rx.search(text or "")
        if not m:
            continue
        a, b = expo.hit(m.group("a")), expo.hit(m.group("b"))
        if a and not b:
            return True, "replacement: the exposure is what is replaced"
        if b and not a:
            return False, "replacement: the exposure is what is introduced"
    m = _REPL_NOUN.search(text or "")
    if m and expo.hit(m.group("x")):
        return False, "replacement: the exposure is what is introduced"
    return None, ""


def _ratio(expo: Exposure, text: str) -> tuple[bool | None, str]:
    """Composition ratios: 'higher P:S ratio' has LESS saturated fat (the exposure is in the denominator)."""
    for m in _RATIO.finditer(text or ""):
        n, d = RATIO_ALIASES.get(m.group("n").lower(), m.group("n")), RATIO_ALIASES.get(m.group("d").lower(), m.group("d"))
        direction = (m.group("dir") or "").lower()
        if not direction:
            continue
        higher = direction in ("higher", "greater", "increased", "high")
        if re.search(r"(?:\bvs\.?|\bversus|\bthan|compared (?:to|with))\s*$", text[:m.start()], re.I):
            higher = not higher                                  # 'higher vs lower P:S ratio': 'lower' describes the comparator arm
        hn, hd = expo.hit(n), expo.hit(d)
        if hd and not hn:
            return higher, "composition ratio: the exposure is the denominator"          # higher ratio -> less exposure
        if hn and not hd:
            return (not higher), "composition ratio: the exposure is the numerator"
    return None, ""


NEGATED_ARM = re.compile(r"\b(?:no|non|without|absence|abstain\w*|abstinence|free of|zero|placebo|usual|control|none)\b", re.I)


def exposure_less(expo: Exposure, finding_text: str, interv: str, comp: str) -> tuple[bool, str]:
    """-> (does the INTERVENTION arm / the finding's contrast have LESS of the exposure than the comparison?, basis).
    Finding-level wording (its own outcome string) outranks the paper-level PICO."""
    for src in (finding_text, interv):
        for fn in (_replacement, _ratio):
            r, why = fn(expo, src)
            if r is not None:
                return r, why
    r, why = _contrast(expo, finding_text)
    if r is not None:
        return r, why
    hi, hc = expo.hit(interv), expo.hit(comp)
    if hc and not hi and (interv or "").strip():
        if _less_cue(expo, comp) or NEGATED_ARM.search(comp):
            return False, "comparator is a reduced/absent exposure"
        return True, "exposure is the comparator arm (the intervention is the alternative)"
    if hi and hc:
        li, lc = _less_cue(expo, interv), _less_cue(expo, comp)
        if li != lc:
            return li, "both arms name the exposure; the reduced arm is the " + ("intervention" if li else "comparator")
    if _less_cue(expo, interv):
        return True, "intervention reduces the exposure"
    return False, ""


# ------------------------------------------------------------------------------------------------ scope
SCOPE_TEXT = {
    "population_out_of_scope": "the study population is outside what the question asks about",
    "study_type_out_of_scope": "policy, tax or global-burden analysis rather than a study of the exposure's effect",
}
_PERINATAL_ANY = re.compile(r"\b(?:neonat\w*|preterm|pre-term|premature (?:infants?|babies)|infants?|newborns?|pregnan\w*|gestation\w*|perinatal|prenatal|"
                            r"antenatal|lactati\w*|breastfe\w*|postpartum|periconception\w*|preeclampsia)\b", re.I)
_CHILD_POP = re.compile(r"\b(?:children|child|toddlers?|paediatric|pediatric|adolescen\w*|schoolchildren|boys|girls)\b", re.I)
_PERINATAL_OUTCOME = re.compile(r"\b(?:gestational|neonatal|birth ?weight|offspring|preeclampsia|preterm|childhood|infant)\b", re.I)
_ACUTE = re.compile(r"\b(?:ICU|intensive care|critically ill|critical illness|sepsis|septic|mechanically ventilated|ventilat\w+|COVID-19|COVID|SARS-CoV-2|"
                    r"coronavirus|perioperative|peri-operative|cardiac arrest|trauma\w*|burns?)\b", re.I)
_PROGNOSIS_POP = re.compile(r"\b(?:survivors?|post-?diagnos\w+|after (?:a |the |their )?(?:\w+ )?diagnosis|(?:newly )?diagnosed with (?:\w+ )?(?:cancer|carcinoma)|"
                            r"(?:cancer|carcinoma|tumou?r|oncolog\w*) (?:patients?|survival|progression|recurrence)|patients with (?:\w+ ){0,2}(?:cancer|carcinoma)|"
                            r"nonmetastatic|non-metastatic|metastatic)\b", re.I)
_PROGNOSIS_HEAD = re.compile(r"mortalit|death|survival|recurrence|progression|prognos|relapse", re.I)
_POLICY_TITLE = re.compile(r"\b(?:tax(?:es|ation)?|excise|policy|policies|legislation|regulation|age-period-cohort|disability[- ]adjusted|DALYs?|"
                           r"global burden|burden of .{0,60}attributable|attributable (?:to|burden)|temporal trends?|secular trends?)\b", re.I)


def _q(interp, rx: re.Pattern, found: str) -> bool:
    """The question itself asks about this population/setting -> the rule does not apply."""
    q = (interp.question or "") + " " + " ".join(interp.outcome_terms or [])
    return bool(rx.search(q)) or bool(re.search(re.escape(found.split()[0].lower()), q.lower()))


def scope_exclusion(interp, title: str, pico: dict, head: str) -> tuple[str, str] | None:
    """-> (reason code, human-readable detail) when the study answers a different question than asked, else None."""
    pop, interv, comp = str(pico.get("population") or ""), str(pico.get("intervention") or ""), str(pico.get("comparator") or "")
    title = title or ""
    low_head = (head or "").lower()

    for src, label in ((pop, "population"), (title, "title"), (low_head, "outcome")):
        m = _PERINATAL_ANY.search(src) if label != "outcome" else _PERINATAL_OUTCOME.search(src)
        if m and not _q(interp, _PERINATAL_ANY, m.group(0)):
            return "population_out_of_scope", f"pregnancy, infant or perinatal setting (“{m.group(0)}” in the {label}); the question is about the general adult population"
    m = _CHILD_POP.search(pop)
    if m and re.search(r"\badults?\b", interp.question or "", re.I) and not _q(interp, _CHILD_POP, m.group(0)):      # only when the question says it is about adults
        return "population_out_of_scope", f"children or adolescents (“{m.group(0)}” in the population); the question is about adults"
    m = _ACUTE.search(pop) or _ACUTE.search(title) or _ACUTE.search(interv)
    if m and not _q(interp, _ACUTE, m.group(0)):
        return "population_out_of_scope", f"acute or critical illness setting (“{m.group(0)}”); the question is about habitual exposure or outpatient treatment"
    if _PROGNOSIS_HEAD.search(low_head):
        m = _PROGNOSIS_POP.search(pop) or _PROGNOSIS_POP.search(title) or _PROGNOSIS_POP.search(interv)
        if m and not _PROGNOSIS_POP.search(interp.question or ""):     # (a question that merely lists 'cancer' as an outcome does not ask about cancer patients)
            return "population_out_of_scope", f"prognosis among people already diagnosed (“{m.group(0)}”); the question is about the exposure in people without that disease"
    m = _POLICY_TITLE.search(title)
    if m and not _q(interp, _POLICY_TITLE, m.group(0)) and not (interv and has_any(interv, interp.concepts[0] if interp.concepts and interp.source == "preset" else []) and not _POLICY_TITLE.search(interv)):
        return "study_type_out_of_scope", f"policy, tax or global-burden analysis (“{m.group(0)}” in the title), not an effect of the exposure itself"
    return None


# ------------------------------------------------------------------------------------------------ finding-level: not the overall effect
PROGNOSTIC_RX = re.compile(r"\b(?:in the )?placebo[- ](?:group|arm)|\bcontrol[- ]group only|\bindirect effect|\bmediat\w+ (?:by|through|via)|\bvia (?:fat|body|bmi|weight)", re.I)


def finding_outcome_classes(head: str) -> set[str]:
    return classes_of(head)
