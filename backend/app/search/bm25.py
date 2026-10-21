"""Minimal BM25 (Okapi) keyword index. Tokens keep hyphenated and alphanumeric terms intact ('SGLT2', 'time-restricted', '25-hydroxyvitamin'),
so exact-term queries match exactly; a light stemmer lets 'fractures' find 'fracture'."""
import math
import re
from collections import Counter

_TOKEN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
STOP = set("a an the of in on for to and or with without does do is are was were be been by at as from vs versus what how can could would should will "
           "it its their there than then that this these those into among between whether if any".split())


def stem(w: str) -> str:
    if len(w) <= 4 or any(c.isdigit() for c in w):
        return w
    for suf in ("ations", "ation", "ings", "ing", "ies", "ied", "es", "ed", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            w = w[: -len(suf)] + ("y" if suf in ("ies", "ied") else "")
            break
    return w[:-1] if w.endswith("e") and len(w) > 4 else w      # fracture / fractures / fractured -> fractur


_SGLT = re.compile(r"sodium[- ]glucose")
_VITD = re.compile(r"\bvitamin[ -]?d[23]?\b")                         # "vitamin D" must not match vitamin B12 / E / K


def tokenize(text: str) -> list[str]:
    out = []
    for t in _TOKEN.findall(_VITD.sub("vitd", _SGLT.sub("sglt2", text.lower()))):      # 'sodium-glucose cotransporter' is a drug class, not salt
        if t in STOP:
            continue
        out.append(stem(t))
        if "-" in t:                                  # 'time-restricted' also matches 'time' and 'restricted'
            out += [stem(p) for p in t.split("-") if p not in STOP and len(p) > 2]
    return out


class BM25:
    def __init__(self, docs: dict[int, str], k1: float = 1.4, b: float = 0.75, field_boost: dict[int, str] | None = None, boost: int = 2):
        """docs: id -> text. field_boost: id -> extra text (e.g. the title) counted `boost` extra times."""
        self.k1, self.b = k1, b
        self.tf: dict[int, Counter] = {}
        self.len: dict[int, int] = {}
        df: Counter = Counter()
        for i, text in docs.items():
            toks = tokenize(text) + (tokenize(field_boost[i]) * boost if field_boost and i in field_boost else [])
            c = Counter(toks)
            self.tf[i], self.len[i] = c, len(toks)
            df.update(c.keys())
        self.n = len(docs)
        self.avg = (sum(self.len.values()) / self.n) if self.n else 0.0
        self.idf = {t: math.log(1 + (self.n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    def search(self, query: str, limit: int = 200, rel_min: float = 0.3) -> list[tuple[int, float]]:
        """Hits scoring below rel_min x the best score are dropped: one stray shared word is not a match."""
        q = tokenize(query)
        if not q:
            return []
        from .synonyms import expand
        scores: dict[int, float] = {}
        terms = set(q)
        alts = {t: expand(t) for t in terms}
        need = max(1, -(-len(terms) // 2))                 # a hit must contain at least half of the distinct query terms
        for i, c in self.tf.items():
            s, matched = 0.0, 0
            for t in terms:
                best = 0.0
                for a in alts[t]:                          # a query term is satisfied by itself or any synonym; count the best one once
                    f = c.get(a)
                    if f:
                        w = (1.0 if a == t else 0.8) * self.idf.get(a, 0) * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.len[i] / (self.avg or 1)))
                        best = max(best, w)
                if best:
                    matched += 1
                    s += best
            if s > 0 and matched >= need:
                scores[i] = s
        ranked = sorted(scores.items(), key=lambda x: -x[1])[:limit]
        return [x for x in ranked if ranked and x[1] >= rel_min * ranked[0][1]]
