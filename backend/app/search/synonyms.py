"""Small curated synonym table for free-text questions: the same concept is written many ways ('salt' / 'sodium', 'SBP' / 'blood pressure',
'hospitalization' / 'hospitalisation'). Each group lists single words; words are matched after the same stemming the indexes use.
Deliberately tiny and hand-made for this corpus; a real system would use MeSH/UMLS."""
from .bm25 import stem

GROUPS = [
    ("salt", "sodium", "nacl"),
    ("pressure", "bp", "sbp", "dbp", "systolic", "diastolic", "hypertension", "hypertensive"),
    ("weight", "bmi", "adiposity", "bodyweight"),
    ("mortality", "death", "deaths", "survival", "died"),
    ("fracture", "fractures", "break", "breaks"),
    ("hospitalization", "hospitalisation", "hospitalizations", "hospitalisations", "admission", "readmission"),
    ("failure", "hf", "hfref", "hfpef"),
    ("cardiovascular", "cvd", "mace", "cardiac", "coronary", "cardio", "heart"),
    ("carb", "carbohydrate", "carbohydrates", "low-carb", "keto", "ketogenic"),
    ("sweetener", "sweeteners", "aspartame", "sucralose", "nonnutritive", "non-nutritive", "saccharin", "stevia"),
    ("glycemic", "glycaemic", "glycemia", "glycaemia", "hba1c", "glucose", "glycated"),
    ("kidney", "renal", "egfr", "ckd", "nephropathy"),
    ("fasting", "time-restricted", "tre", "intermittent", "alternate-day", "isf"),
    ("ultra-processed", "ultraprocessed", "upf"),
    ("vitd", "cholecalciferol", "ergocalciferol", "25-hydroxyvitamin", "25ohd", "vitd", "calcifediol"),
    ("omega-3", "omega", "n-3", "epa", "dha", "fish"),
    ("statin", "statins", "atorvastatin", "simvastatin", "rosuvastatin", "pravastatin"),
    ("coffee", "caffeine"),
    ("exercise", "training", "physical-activity"),
    ("sglt2", "gliflozin", "dapagliflozin", "empagliflozin", "canagliflozin", "sotagliflozin", "sglt"),
    ("osteoporosis", "osteoporotic", "osteopenia", "osteopenic"),
    ("density", "bmd"),
    ("depression", "depressive", "depressed"),
    ("obesity", "overweight", "obese"),
]
_MAP: dict[str, frozenset[str]] = {}
for g in GROUPS:
    stems = frozenset(stem(w) for w in g)
    for w in g:
        _MAP[stem(w)] = _MAP.get(stem(w), frozenset()) | stems


def expand(stemmed_token: str) -> frozenset[str]:
    """The token plus its synonyms (all stemmed)."""
    return _MAP.get(stemmed_token, frozenset()) | {stemmed_token}
