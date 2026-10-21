"""Verification: the model's output is a *claim*; this module checks it against the source text.

Checks (all deterministic):
  * quote presence: exact (after unicode/whitespace/case normalization) -> real char offsets,
    else fuzzy (>= 90 partial ratio) -> offsets of best alignment, else FAILED
  * section: derived from where the quote actually is; model's claim is overridden and mismatches noted
  * numbers: every numeric value must appear as a number inside its own quote
  * sanity: CI contains the estimate, p in [0, 1]
Failed fields are kept (so the hallucination rate is measurable) but never counted as verified.
"""
import re
import unicodedata

from rapidfuzz import fuzz

from .schema import Located, PaperExtraction, Provenance

FUZZY_THRESHOLD = 90.0
MIN_FUZZY_LEN = 15
_TRANS = str.maketrans({"‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-",
                        "‘": "'", "’": "'", "“": '"', "”": '"', " ": " "})


def normalize_with_map(text: str) -> tuple[str, list[int]]:
    """Normalize for matching; idx[i] is the original index of normalized char i."""
    out, idx, prev_space = [], [], True
    for i, ch in enumerate(text):
        for c in unicodedata.normalize("NFKC", ch).translate(_TRANS).lower():
            if c.isspace():
                if prev_space:
                    continue
                c, prev_space = " ", True
            else:
                prev_space = False
            out.append(c)
            idx.append(i)
    while out and out[-1] == " ":
        out.pop(); idx.pop()
    return "".join(out), idx


def locate_quote(quote: str, source: str, _cache: dict | None = None) -> tuple[str, int | None, int | None]:
    nq, _ = normalize_with_map(quote)
    nq = nq.strip()
    if not nq:
        return "failed", None, None
    ns, idx = normalize_with_map(source)
    pos = ns.find(nq)
    if pos >= 0:
        return "exact", idx[pos], idx[pos + len(nq) - 1] + 1
    if len(nq) >= MIN_FUZZY_LEN:
        al = fuzz.partial_ratio_alignment(nq, ns)
        if al and al.score >= FUZZY_THRESHOLD and al.dest_end > al.dest_start:
            return "fuzzy", idx[al.dest_start], idx[al.dest_end - 1] + 1
    return "failed", None, None


_NUM = re.compile(r"(?<![\w.])-?(?:\d+\.\d+|\d+|\.\d+)")


_GROUPED = re.compile(r"(?<![\d.])(\d{1,3})((?:[ ,\u00a0\u202f]\d{3})+)(?!\d)")
_WORD_VALUES = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen "
    "eighteen nineteen".split())}
_WORD_VALUES.update({w: 20 + 10 * i for i, w in enumerate("twenty thirty forty fifty sixty seventy eighty ninety".split())})
_WORD_RUN = re.compile(r"\b(?:(?:" + "|".join(sorted(list(_WORD_VALUES) + ["hundred", "thousand", "million"], key=len, reverse=True))
                       + r")(?:[\s-]+and)?(?:[\s-]+|\b))+", re.I)


def _word_numbers(text: str) -> list[float]:
    """'Twenty patients' -> 20; 'One hundred and twenty four' -> 124. Values < 10 are ignored ('one' is mostly a pronoun)."""
    out = []
    for m in _WORD_RUN.finditer(text):
        total = cur = 0
        seen = False
        for w in re.split(r"[\s-]+", m.group().lower().strip()):
            if w == "and" or not w:
                continue
            seen = True
            if w in _WORD_VALUES:
                cur += _WORD_VALUES[w]
            elif w == "hundred":
                cur = max(cur, 1) * 100
            elif w in ("thousand", "million"):
                total += max(cur, 1) * (1000 if w == "thousand" else 1_000_000)
                cur = 0
        v = total + cur
        if seen and v >= 10:
            out.append(float(v))
    return out


def numbers_in(text: str) -> list[float]:
    """Numbers as written: '1,336', '153 902' (thin/regular space groups), '0.65', and number words ('Twenty')."""
    text = re.sub(r"(?<=\d)[·∙⋅](?=\d)", ".", text)          # Lancet-style decimals: 1·22 -> 1.22
    t = _GROUPED.sub(lambda m: m.group(1) + re.sub(r"\D", "", m.group(2)), text)
    return [float(m.group()) for m in _NUM.finditer(t)] + _word_numbers(text)


def _has_number(value: float, nums: list[float]) -> bool:
    return any(abs(abs(value) - abs(n)) < 1e-9 for n in nums)   # abs: "-" in ranges parses as sign


def section_at(sections: list[dict], pos: int) -> str | None:
    for s in sections:
        if s["start"] <= pos < s["end"]:
            return s["label"]
    return None


def _check_location(f: Located, source: str, sections: list[dict]) -> None:
    f.char_start = f.char_end = None
    f.notes = []
    if not f.quote or not f.quote.strip():
        f.verification = "failed"
        f.notes.append("missing_quote")
        return
    f.verification, f.char_start, f.char_end = locate_quote(f.quote, source)
    if f.verification == "failed":
        f.notes.append("quote_not_in_source")
        return
    true_section = section_at(sections, f.char_start)
    if true_section and f.section and f.section.strip().lower() != true_section.lower():
        f.notes.append(f"section_mismatch(claimed={f.section})")
    if true_section:
        f.section = true_section


def _fail_on_numbers(f: Located, pairs: dict[str, float | int | None]) -> None:
    if f.verification == "failed":
        return
    nums = numbers_in(f.quote or "")
    bad = [k for k, v in pairs.items() if v is not None and not _has_number(float(v), nums)]
    if bad:
        f.verification = "failed"
        f.notes += [f"number_not_in_quote:{k}" for k in bad]


def verify_extraction(ex: PaperExtraction, source: str, sections: list[dict],
                      publication_types: list[str] | None = None) -> PaperExtraction:
    s = ex.study
    for name in ("design", "population", "sample_size", "intervention", "comparator", "follow_up"):
        f: Provenance = getattr(s, name)
        if f.status == "not_reported" or (f.value is None):
            f.status, f.verification, f.notes, f.char_start, f.char_end = "not_reported", "n/a", [], None, None
            f.quote = None
            continue
        _check_location(f, source, sections)
        if name == "sample_size":
            _fail_on_numbers(f, {"sample_size": f.value})
    for f in ex.limitations_stated:
        if f.status == "reported" and f.value:
            _check_location(f, source, sections)
        else:
            f.verification = "n/a"
    for fd in ex.primary_findings:
        _check_location(fd, source, sections)
        _fail_on_numbers(fd, {"effect_value": fd.effect_value, "ci_low": fd.ci_low,
                              "ci_high": fd.ci_high, "p_value": fd.p_value})
        if fd.ci_low is not None and fd.ci_high is not None and fd.effect_value is not None \
                and not (fd.ci_low <= fd.effect_value <= fd.ci_high):
            fd.notes.append("sanity:ci_excludes_estimate")
        if fd.p_value is not None and not (0 <= fd.p_value <= 1):
            fd.notes.append("sanity:p_out_of_range")
    ex.flags = design_flags(ex, publication_types or [])
    return ex


def design_flags(ex: PaperExtraction, pubtypes: list[str]) -> list[str]:
    """Cross-check the model's design against PubMed's independent publication-type metadata."""
    d = ex.study.design.value
    if d is None or not pubtypes:
        return []
    d = d.value
    is_rct_type = "Randomized Controlled Trial" in pubtypes
    is_ma_type = "Meta-Analysis" in pubtypes
    flags = []
    if is_rct_type and d not in ("rct", "rct_secondary_analysis"):
        flags.append("design_disagrees_with_pubmed")
    if d == "meta_analysis" and not is_ma_type:
        flags.append("design_disagrees_with_pubmed")
    if d in ("rct",) and not is_rct_type:
        flags.append("design_disagrees_with_pubmed")
    return flags


def verification_summary(ex: PaperExtraction) -> dict:
    items = []
    for name in ("design", "population", "sample_size", "intervention", "comparator", "follow_up"):
        f = getattr(ex.study, name)
        if f.status == "reported":
            items.append(f.verification)
    items += [f.verification for f in ex.primary_findings]
    c = {k: items.count(k) for k in ("exact", "fuzzy", "failed")}
    n = len(items)
    return {**c, "claims": n, "verified_fraction": ((c["exact"] + c["fuzzy"]) / n) if n else None}


def missing_quotes(ex: PaperExtraction) -> list[str]:
    """Reported claims that carry no quote at all (the 'no quote, no value' rule of prompt v2)."""
    out = []
    for name in ("design", "population", "sample_size", "intervention", "comparator", "follow_up"):
        f = getattr(ex.study, name)
        if f.status == "reported" and f.value is not None and not (f.quote or "").strip():
            out.append(f"study.{name}")
    for i, fd in enumerate(ex.primary_findings):
        if not (fd.quote or "").strip():
            out.append(f"primary_findings[{i}]")
    for i, f in enumerate(ex.limitations_stated):
        if f.status == "reported" and f.value and not (f.quote or "").strip():
            out.append(f"limitations_stated[{i}]")
    return out
