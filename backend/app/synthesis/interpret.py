"""Question -> Interpretation: which papers are on topic, which findings answer the question, and which direction
counts as 'the claim is right' (polarity).

Preset questions (data/questions.json) carry hand-written concept groups. Free-text questions are parsed by simple rules and
the interpretation is returned to the user so a wrong parse is visible and can be corrected (`polarity` can be overridden)."""
import json
import re
from dataclasses import asdict, dataclass, field

from ..config import settings

STOP = set("""a an the of in on for to and or with without does do did is are was were be been by at as from vs versus what how can
could would should will it its their there than then that this these those into among between whether if any more less
adults adult people patients patient participants individuals persons effect effects association associated link linked
evidence study studies research""".split())
HARM_VERBS = ("increas", "rais", "caus", "worsen", "elevat", "promot", "aggravat")
BENEFIT_VERBS = ("reduc", "lower", "decreas", "improv", "prevent", "help", "protect", "boost", "slow", "delay", "enhanc", "ameliorat")
NEUTRAL_VERBS = ("lead", "affect", "influenc", "associated", "linked", "relat", "impact")
VERB_RX = re.compile(r"\b(" + "|".join(HARM_VERBS + BENEFIT_VERBS + NEUTRAL_VERBS) + r")\w*\b")
HARM_WORDS = ("higher", "more risk", "greater risk", "increased risk", "worse", "harm", "elevated")
BENEFIT_WORDS = ("lower", "fewer", "less", "reduced risk", "decreased", "better", "improved", "protective")
GOOD_OUTCOMES = ("weight loss", "remission", "survival", "longevity", "improvement", "recovery", "adherence",
                 "nad", "hdl", "muscle mass", "muscle growth", "muscle strength", "lean mass", "bone density", "bone mass", "testosterone",
                 "telomere length", "endurance", "vo2", "hypertroph")   # outcomes it is good to raise: 'raise/increase X' is then a benefit claim
HARM_ADJ = ("dangerous", "harmful", "unsafe", "risky", "toxic", "safe", "safety")
AUX = re.compile(r"^\s*(do|does|did|is|are|can|could|will|would|should)\s+")
SEPARATORS = (" and ", " on ", " for ", " in ", " with ", " vs ", " versus ")
GENERIC = set("supplement supplements supplementation intake consumption cutting cut back reducing using eating diet level levels therapy treatment "
              "intervention interventions program programs risk older people patients adults adult individuals low high more less higher lower "
              "reduced increased disease progression event events outcome outcomes rate rates incidence prevalence change loss gain use usage "
              "control management bad good healthy unhealthy harmful beneficial health you your diets".split())
# Vague health claims ("processed foods are unhealthy", "are nuts good for you?"): a polarity word and no named outcome.
HEALTH_HARM_ADJ = ("unhealthier", "unhealthy", "worse", "harmful", "bad", "damaging", "detrimental", "unwholesome", "fattening")
HEALTH_GOOD_ADJ = ("healthier", "healthy", "better", "good", "beneficial", "nutritious", "protective", "helpful", "wholesome")
_ADJ = "|".join(HEALTH_HARM_ADJ + HEALTH_GOOD_ADJ)
HEALTH_CLAIM = re.compile(r"^(?P<x>.+?)\s+(?:(?:is|are)\s+)?(?:really\s+|actually\s+|generally\s+|very\s+|so\s+)?(?P<adj>" + _ADJ + r")\b(?:\s+(?:for|to|on)\s+(?:the\s+|your\s+)?(?P<tail>you|health|heart|humans|people|adults|us|eat|body|brain|bones?|kids|children|liver|kidneys?))?$")
HEALTH_OUTCOMES = ["mortality", "cardiovascular", "cancer", "diabetes", "obesity", "hypertension", "weight", "cholesterol", "inflammation"]
BONE_OUTCOMES = ["fractures", "bone mineral density", "osteoporosis"]
OUTCOME_ALIASES = [(re.compile(r"\b(?:bone|bones|skeletal|skeleton|osteo\w*)\b"), BONE_OUTCOMES)]       # vague outcome phrase -> measurable outcomes the papers report
ALIASES = {"processed food": ["ultra-processed"], "junk food": ["ultra-processed"], "fast food": ["ultra-processed"], "processed foods": ["ultra-processed"]}
MORTALITY_QUALIFIERS = ("cardiovascular", "cardiac", "cancer", "stroke", "cause-specific", "neonatal", "infant", "maternal", "28-day", "covid", "sepsis",
                        "suicide", "kidney", "renal", "cvd", "coronary", "disease-specific")


# Everyday phrasing -> a preset topic, used by report.build_report as a fallback when the rules count fewer than 3 studies. Each preset in
# data/questions.json lists `aliases` ("bacon", "keto", "ice bath"). The topic applies only when every other content word in the question is vague ("bad", "worth it") or an outcome that topic already measures; otherwise the rules run as before.
VAGUE = set("bad good worth worthwhile work works really actually take taking pill pills capsule capsules supplement help helps healthy unhealthy "
            "dangerous harmful risky need should better best".split())
EVERYDAY_OUTCOMES = {"heart": "cardiovascular", "attack": "cardiovascular", "attacks": "cardiovascular", "live": "mortality", "longer": "mortality",
                     "life": "mortality", "lifespan": "mortality", "die": "mortality", "dying": "mortality", "osteoporosis": "fracture", "bone": "fracture",
                     "bones": "fracture", "lose": "weight", "fat": "weight", "glucose": "glycemic", "sugar": "glycemic",
                     "build": "muscle", "building": "muscle", "gain": "muscle", "gains": "muscle", "bulk": "muscle"}
ALIAS_HARM = ("bad", "harm", "cause", "causes", "increase", "risk", "dangerous", "unhealthy", "unsafe", "risky", "worse")
ALIAS_BENEFIT = ("good", "help", "helps", "lower", "lowers", "reduce", "reduces", "improve", "improves", "prevent", "prevents", "worth", "work", "works", "protect", "healthy", "better")


def _stems(text: str) -> set[str]:
    from ..search.bm25 import tokenize
    from ..search.synonyms import expand
    return {e for t in tokenize(text) for e in expand(t)}


def alias_topic(q: str, polarity: str | None) -> "Interpretation | None":
    from ..search.bm25 import tokenize
    low = _norm(AUX.sub("", q.lower().strip().rstrip("?. ")))
    hits: list[tuple[int, int, int, dict, str]] = []       # (start, end, length, preset, alias)
    for p in presets():
        for a in p.get("aliases", []):
            na = _norm(a)
            for m in re.finditer(r"(?<![a-z0-9])" + re.escape(na) + r"(?![a-z0-9])", low):
                hits.append((m.start(), m.end(), len(na), p, a))
    if not hits:
        return None
    hits.sort(key=lambda h: -h[2])                          # longest phrase wins where phrases overlap ('diet soda' beats 'soda')
    kept: list = []
    for h in hits:
        if not any(h[0] < k[1] and k[0] < h[1] for k in kept):
            kept.append(h)
    if len({k[3]["slug"] for k in kept}) != 1:
        return None                                         # the question names more than one topic
    p, alias = kept[0][3], kept[0][4]
    covered = " ".join(" ".join(g) for g in p["concepts"]) + " " + " ".join(p.get("outcome_terms", [])) + " " + " ".join(p.get("aliases", []))
    known = _stems(covered)
    rest = low
    for k in sorted(kept, key=lambda k: -k[0]):
        rest = rest[:k[0]] + " " + rest[k[1]:]
    for w in re.findall(r"[a-z0-9][a-z0-9-]*", rest):
        if w in STOP or w in GENERIC or w in VAGUE or len(w) <= 2 or VERB_RX.match(w):
            continue
        if not (_stems(EVERYDAY_OUTCOMES.get(w, w)) & known):
            return None                                     # asks about something this topic does not measure
    words = set(re.findall(r"[a-z]+", low))
    if polarity:
        pol, src = polarity, "override"
    elif words & set(ALIAS_HARM):
        pol, src = "harm", "parsed"
    elif words & set(ALIAS_BENEFIT):
        pol, src = "benefit", "parsed"
    else:
        pol, src = p.get("polarity", "benefit"), "preset"
    note = (f"Read as the “{p['label']}” topic because the question mentions “{alias}”, and counted against: {', '.join(p.get('outcome_terms', [])[:6])}. "
            f"The full question for this topic is: {p['question']}")
    return Interpretation(q, pol, src, p["concepts"], p.get("outcome_terms", []), "preset", slug=p["slug"],
                          exposure_less=bool(p.get("exposure_less", False)), notes=[note], tags=list(p.get("tags", [])),
                          exposure_not=list(p.get("exposure_not_terms", [])), exposure_extra=list(p.get("exposure_extra_terms", [])))


@dataclass
class Interpretation:
    question: str
    polarity: str                       # benefit | harm  (what counts as supporting the claim)
    polarity_source: str                # preset | parsed | assumed | override
    concepts: list[list[str]]           # AND across groups, OR within a group
    outcome_terms: list[str]
    source: str                         # preset | parsed
    slug: str | None = None
    exposure_words: list[list[str]] = field(default_factory=list)   # free text: tokens of each exposure WORD; a paper must match most words
    exposure_alias: list[str] = field(default_factory=list)         # tokens that satisfy the whole exposure on their own ('processed food' ~ 'ultra-processed')
    exposure_less: bool = False                                     # the claim is about LESS of the exposure ('reducing salt', 'low-carb')
    exposure_terms: list[str] = field(default_factory=list)   # free text only: tokens naming the exposure/intervention (left of the verb)
    notes: list[str] = field(default_factory=list)
    search_text: str = ""                                       # retrieval text when the claim was re-read (exposure + outcomes); else the question itself
    tags: list[str] = field(default_factory=list)               # topic keywords: a preset's own, or the model's pick from tag_vocabulary(); empty for a rules-only reading
    model_read: bool = False                                    # the reading came from the language model, not the rules
    exposure_extra: list[str] = field(default_factory=list)     # preset only: abbreviations/synonyms the exposure is written as in text ('SSBs', 'NNS'); used to read arms, not to retrieve
    exposure_not: list[str] = field(default_factory=list)       # preset only: phrases that look like the exposure but are not ('plant-based oils', 'unsweetened', 'poultry')

    def dict(self) -> dict:
        return asdict(self)


def tag_vocabulary() -> list[str]:
    """The fixed set of topic tags (the union of the presets' tags). The model may only choose from these."""
    return sorted({t for p in presets() for t in p.get("tags", [])})


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s.lower())).strip()


def presets() -> list[dict]:
    try:
        return json.loads((settings.data_dir / "questions.json").read_text())
    except FileNotFoundError:
        return []


LESS_RX = re.compile(r"\b(?:reduc\w*|lower\w*|decreas\w*|limit\w*|restrict\w*|cut\w*|avoid\w*|less|fewer|minimi\w*|low[- ](?:sodium|salt|sugar|fat|saturated|cholesterol|calorie|energy|purine)\w*|replac\w*|substitut\w*)\b")


def exposure_is_less(text: str) -> bool:
    t = re.sub(r"time[- ]restrict\w*|energy[- ]restrict\w*|calorie[- ]restrict\w*|caloric[- ]restrict\w*", " ", (text or "").lower())   # named regimens, not 'restrict X'
    return bool(LESS_RX.search(t))


def _exposure_words(text: str) -> list[list[str]]:
    from ..search.bm25 import tokenize
    return [toks for w in re.findall(r"[a-z0-9][a-z0-9-]*", text) if w not in STOP and w not in GENERIC and len(w) > 2 and (toks := [t for t in tokenize(w) if len(t) > 2])]


def polarity_is_safety(body: str) -> bool:
    return any(re.search(r"\b" + a + r"\b", body) for a in HARM_ADJ)


def interpret(question: str, polarity: str | None = None) -> Interpretation:
    q = question.strip()
    for p in presets():
        if p.get("concepts") and _norm(p["question"]) == _norm(q):
            return Interpretation(q, polarity or p.get("polarity", "benefit"), "override" if polarity else "preset",
                                  p["concepts"], p.get("outcome_terms", []), "preset", slug=p["slug"], exposure_less=bool(p.get("exposure_less", False)),
                                  tags=list(p.get("tags", [])), exposure_not=list(p.get("exposure_not_terms", [])), exposure_extra=list(p.get("exposure_extra_terms", [])))
    low = q.lower().strip().rstrip("?. ")
    notes: list[str] = []
    from ..search.bm25 import tokenize
    body = re.sub(r"\bvitamin[ -]?d[23]?\b", "vitd", AUX.sub("", low))      # one token, so 'vitamin D' is not any vitamin
    words = lambda t: [w for w in re.findall(r"[a-z0-9][a-z0-9-]*", t) if w not in STOP and w not in GENERIC and len(w) > 2]

    hc = HEALTH_CLAIM.match(body)
    if hc and not VERB_RX.search(hc.group("x")):
        x, adj = hc.group("x"), hc.group("adj")
        pol, src = (polarity, "override") if polarity else (("harm" if adj in HEALTH_HARM_ADJ else "benefit"), "parsed")
        exposure = list(dict.fromkeys(t for w in words(x) for t in tokenize(w) if len(t) > 2))
        for key, extra in ALIASES.items():
            if key in x:
                exposure += [t for e in extra for t in tokenize(e)]
        tail = hc.group("tail") or ""
        outs = ["cardiovascular", "cholesterol", "heart"] if tail == "heart" else list(BONE_OUTCOMES) if tail.startswith("bone") else list(HEALTH_OUTCOMES)
        notes = [f"Read as a general health claim about “{x.strip()}”: counted against " + ("heart and cardiovascular outcomes" if tail == "heart" else "any major health outcome (mortality, cardiovascular disease, cancer, diabetes, obesity, blood pressure)") + ". "
                 "A paper counts only if the exposure (or a synonym) appears in its title or intervention.",
                 "Free-text question: candidate papers come from hybrid keyword + semantic retrieval; treat the verdict as a rough guide."]
        return Interpretation(q, pol, src, [[t] for t in outs], outs, "parsed", exposure_terms=list(dict.fromkeys(exposure)), notes=notes, exposure_less=exposure_is_less(x),
                              exposure_words=_exposure_words(x), exposure_alias=[t for key, extra in ALIASES.items() if key in x for e in extra for t in tokenize(e)])

    # split the question into exposure | outcome at the main verb: the first verb that has an exposure phrase before it
    # ('reducing salt lower blood pressure': 'reducing' has nothing before it, so 'lower' is the main verb)
    verb = next((m for m in VERB_RX.finditer(body) if words(body[:m.start()])), None)
    hint = None
    if verb:
        left, right = body[:verb.start()], body[verb.end():]
        v = verb.group(1)
        hint = "harm" if v in HARM_VERBS else "benefit" if v in BENEFIT_VERBS else None
        if hint == "harm" and any(g in right for g in GOOD_OUTCOMES):
            hint = "benefit"                                          # 'cause more weight loss' is a benefit claim
    else:
        adj = next((a for a in HARM_ADJ if re.search(r"\b" + a + r"\b", body)), None)
        sep = next((sp for sp in SEPARATORS if sp in " " + body + " "), None)
        if adj:
            left, right, hint = body.split(adj)[0], "", "harm"
            notes.append("Read as a safety question: looking for adverse outcomes.")
        elif sep:
            left, right = (" " + body + " ").split(sep, 1)
        else:
            left, right = "", body
    if polarity:
        pol, src = polarity, "override"
    elif hint:
        pol, src = hint, "parsed"
    else:
        pol, src = None, None
    if pol is None:                                                    # neutral verb ('linked to', 'associated with'): the direction word decides
        if any(w in right for w in HARM_WORDS):
            pol, src = "harm", "parsed"
        elif any(w in right for w in BENEFIT_WORDS):
            pol, src = "benefit", "parsed"
        else:
            pol, src = "benefit", "assumed"
            notes.append("Could not tell from the wording whether a benefit or a harm is being asked about; assuming benefit.")

    exposure = list(dict.fromkeys(t for w in words(left) for t in tokenize(w) if len(t) > 2))
    if exposure:
        notes.append(f"Exposure read as: {left.strip()}. A paper counts only if this (or a synonym) appears in its title or its intervention.")
    else:
        notes.append("Could not separate the exposure from the outcome in this question, so no exposure check was applied.")

    # outcome phrases: drop the population tail ('in older adults'), split on and/or/commas, drop generic words
    tail = re.split(r"\b(?:in|among|than|compared|versus|vs)\b", right)[0]
    chunks = [" ".join(words(c)) for c in re.split(r",|\band\b|\bor\b", tail)]
    terms = [c for c in dict.fromkeys(chunks) if c]
    if not terms and not right.strip() and polarity_is_safety(body):
        terms = ["adverse", "harm", "safety", "serious"]
    if not terms:                                                      # 'improve outcomes in heart failure': the population is the only specific thing
        terms = [c for c in dict.fromkeys(" ".join(words(c)) for c in re.split(r",|\band\b|\bor\b", right)) if c]
    for rx, extra in OUTCOME_ALIASES:
        if any(rx.search(t) and not re.search(r"fractur|density|osteopor", t) for t in terms):
            terms = list(dict.fromkeys(terms + extra))
            notes.append("“" + right.strip() + "” is not something papers measure directly, so it is counted as: " + ", ".join(extra) + ".")
    concepts = [[t] for t in terms]
    notes.append("Free-text question: candidate papers come from hybrid keyword + semantic retrieval, and findings are matched to the question by shared words and a small synonym table, so treat the verdict as a rough guide.")
    return Interpretation(q, pol, src, concepts, terms, "parsed", exposure_terms=exposure, notes=notes, exposure_words=_exposure_words(left), exposure_less=exposure_is_less(left))


def from_model_reading(question: str, m: dict, polarity: str | None = None) -> Interpretation:
    """Build an Interpretation from the model's reading (llm_assist.read_claim). Same downstream checks as a rules-based free-text reading."""
    from ..search.bm25 import tokenize
    vd = lambda t: re.sub(r"\bvitamin[ -]?d[23]?\b", "vitd", t.lower())
    exposure = re.split(r"\s+(?:after|following|during|before|post)\s+", vd(m["exposure"]), maxsplit=1)[0] or vd(m["exposure"])   # timing/context is not the exposure
    syn = [vd(x) for x in m.get("exposure_synonyms", [])]
    alias = [t for x in syn if len(re.findall(r"[a-z0-9][a-z0-9-]*", x)) == 1 for t in tokenize(x) if len(t) > 2]
    outs = list(dict.fromkeys(re.sub(r"\s+", " ", re.sub(r"\([^)]*\)", " ", o)).strip() for o in m["outcomes"]))
    outs = [o for o in dict.fromkeys(re.sub(r"\b(?:incidence|risk|events?|levels?|rates?|outcomes?)\s*$", "", o).strip() for o in outs) if o]
    pol, src = (polarity, "override") if polarity else (m["polarity"], "model")
    notes = [f"The rules could not match this claim to enough studies, so a language model re-read it as: exposure “{m['exposure']}”"
             + (f" (also: {', '.join(m.get('exposure_synonyms', []))})" if m.get("exposure_synonyms") else "") + f"; outcomes counted: {', '.join(outs)}. "
             "It only chose search terms; every study, number and quote still comes from the verified stored claims."]
    return Interpretation(question, pol, src, [[o] for o in outs], outs, "parsed", exposure_terms=list(dict.fromkeys(t for w in re.findall(r"[a-z0-9][a-z0-9-]*", exposure) if w not in STOP and w not in GENERIC for t in tokenize(w) if len(t) > 2)),
                          notes=notes, exposure_words=_exposure_words(exposure), exposure_alias=list(dict.fromkeys(alias)),
                          exposure_less=bool(m.get("exposure_less")), search_text=f"{exposure} {' '.join(outs[:3])}", model_read=True,
                          tags=[t for t in dict.fromkeys(m.get("tags") or []) if t in tag_vocabulary()][:5])
