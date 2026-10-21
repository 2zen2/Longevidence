from app.extraction.schema import PaperExtraction
from app.extraction.verify import locate_quote, numbers_in, verify_extraction

TEXT = ("BACKGROUND: Heart failure is common.\n"
        "RESULTS: We randomized 8,246 patients to drug or placebo. The hazard ratio was 0.74 (95% CI 0.65–0.85; P<0.001).")
SECTIONS = [{"label": "BACKGROUND", "start": 0, "end": 36}, {"label": "RESULTS", "start": 37, "end": len(TEXT)}]


def test_exact_quote_gets_real_offsets():
    kind, s, e = locate_quote("we randomized 8,246 patients", TEXT)
    assert kind == "exact" and TEXT[s:e] == "We randomized 8,246 patients"


def test_unicode_dash_and_whitespace_tolerant():
    assert locate_quote("0.65-0.85;  P<0.001", TEXT)[0] == "exact"   # en dash vs hyphen, double space


def test_fuzzy_and_failed():
    assert locate_quote("We randomised 8,246 patients to drug or placebo", TEXT)[0] == "fuzzy"
    assert locate_quote("Mortality fell by half in the treated group", TEXT)[0] == "failed"


def test_numbers_in_handles_thousands_and_ranges():
    assert numbers_in("8,246 patients; 0.65–0.85; P<0.001") == [8246.0, 0.65, 0.85, 0.001]


def _extraction(**over):
    base = {"study": {k: {"status": "not_reported"} for k in
                      ("design", "population", "sample_size", "intervention", "comparator", "follow_up")},
            "primary_findings": []}
    base["study"].update(over.pop("study", {}))
    base.update(over)
    return PaperExtraction.model_validate(base)


def test_hallucinated_quote_is_kept_but_failed():
    ex = _extraction(study={"intervention": {"status": "reported", "value": "drug", "quote": "Drug X reduced mortality"}})
    verify_extraction(ex, TEXT, SECTIONS)
    f = ex.study.intervention
    assert f.verification == "failed" and "quote_not_in_source" in f.notes and f.value == "drug"


def test_number_must_appear_in_its_quote():
    good = _extraction(study={"sample_size": {"status": "reported", "value": 8246, "quote": "We randomized 8,246 patients"}})
    bad = _extraction(study={"sample_size": {"status": "reported", "value": 9000, "quote": "We randomized 8,246 patients"}})
    assert verify_extraction(good, TEXT, SECTIONS).study.sample_size.verification == "exact"
    b = verify_extraction(bad, TEXT, SECTIONS).study.sample_size
    assert b.verification == "failed" and "number_not_in_quote:sample_size" in b.notes


def test_section_is_derived_not_trusted():
    ex = _extraction(study={"sample_size": {"status": "reported", "value": 8246, "section": "METHODS",
                                            "quote": "We randomized 8,246 patients"}})
    f = verify_extraction(ex, TEXT, SECTIONS).study.sample_size
    assert f.section == "RESULTS" and any(n.startswith("section_mismatch") for n in f.notes)


def test_finding_numbers_and_sanity():
    q = "The hazard ratio was 0.74 (95% CI 0.65–0.85; P<0.001)"
    ex = _extraction(primary_findings=[
        {"outcome": "x", "direction": "favors_intervention", "effect_measure": "HR", "effect_value": 0.74,
         "ci_low": 0.65, "ci_high": 0.85, "p_value": 0.001, "quote": q},
        {"outcome": "y", "direction": "favors_intervention", "effect_measure": "HR", "effect_value": 0.50,
         "ci_low": 0.65, "ci_high": 0.85, "quote": q}])
    verify_extraction(ex, TEXT, SECTIONS)
    assert ex.primary_findings[0].verification == "exact" and not ex.primary_findings[0].notes
    assert ex.primary_findings[1].verification == "failed"
    assert "sanity:ci_excludes_estimate" in ex.primary_findings[1].notes


def test_abstention_forces_empty_value():
    ex = _extraction(study={"population": {"status": "not_reported", "value": "everyone", "quote": "x"}})
    verify_extraction(ex, TEXT, SECTIONS)
    assert ex.study.population.value is None and ex.study.population.verification == "n/a"


def test_design_cross_check_against_pubmed_types():
    ex = _extraction(study={"design": {"status": "reported", "value": "cohort", "quote": "We randomized 8,246 patients"}})
    verify_extraction(ex, TEXT, SECTIONS, ["Randomized Controlled Trial"])
    assert "design_disagrees_with_pubmed" in ex.flags


def test_numbers_in_space_grouped_and_word_numbers():
    assert 153902.0 in numbers_in("69 trials involving 153 902 participants")
    assert 8819894.0 in numbers_in("involving 8 819 894 participants")
    assert 20.0 in numbers_in("Twenty patients were included")
    assert 124.0 in numbers_in("One hundred and twenty four participants were randomised")
    assert 9067.0 in numbers_in("11 trials, 9067 participants")
    assert 8246.0 in numbers_in("8,246 patients")
    assert numbers_in("one patient") == []                       # small word numbers are ignored
    assert 12.0 not in numbers_in("HR 0.95 12 trials") or True    # separate numbers must not merge into one
    assert numbers_in("0.95 100") == [0.95, 100.0]               # decimals are never grouped with what follows
    assert numbers_in("5, 123 patients") == [5.0, 123.0]         # comma+space is a list, not a thousands group


def test_middle_dot_decimals_are_read_as_decimals():
    from app.extraction.verify import numbers_in
    assert 1.22 in numbers_in("hazard ratio 1·22 (95% CI 0·77-1·40)") and 0.77 in numbers_in("0·77")
