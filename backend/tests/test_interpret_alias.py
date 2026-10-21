"""Everyday phrasing is routed to a preset topic only when the topic measures what is being asked."""
import json

import pytest

from app.config import settings
from app.synthesis.interpret import alias_topic, interpret


@pytest.mark.parametrize("q, slug, polarity", [
    ("Is bacon bad for you?", "red-meat", "harm"),
    ("Does the keto diet work for diabetes?", "low-carb", "benefit"),
    ("Is an ice bath bad for building muscle?", "cold-lifting", "harm"),
    ("Do fish oil pills prevent heart attacks?", "omega3", "benefit"),
    ("Does eating nuts help you live longer?", "nuts", "benefit"),
    ("Is diet soda bad for you?", "sweeteners", "harm"),          # 'diet soda' beats the shorter 'soda'
    ("Should I take NMN?", "nmn", "benefit"),
])
def test_everyday_question_is_routed_to_its_topic(q, slug, polarity):
    i = alias_topic(q, None)
    assert (i.source, i.slug, i.polarity) == ("preset", slug, polarity)
    assert i.notes and "Read as the" in i.notes[0]


@pytest.mark.parametrize("q", [
    "Does coffee cause insomnia?",            # outcome the coffee topic does not measure
    "Is coffee or red meat worse for you?",   # two topics
    "Is keto safe?",                          # safety is not measured by the low-carb topic
    "Does creatine improve memory?",          # no topic
])
def test_unrelated_or_ambiguous_questions_are_not_routed(q):
    assert alias_topic(q, None) is None


def test_exact_preset_question_is_unchanged_and_polarity_can_be_overridden():
    p = next(x for x in json.loads((settings.data_dir / "questions.json").read_text()) if x["slug"] == "red-meat")
    i = interpret(p["question"])
    assert (i.slug, i.notes) == ("red-meat", [])
    assert alias_topic("Is bacon bad for you?", "benefit").polarity_source == "override"


def test_every_preset_has_tags_and_aliases():
    for p in json.loads((settings.data_dir / "questions.json").read_text()):
        assert p["tags"] and p["aliases"], p["slug"]


def test_model_reading_keeps_only_allowed_tags():
    from app.synthesis.interpret import from_model_reading, tag_vocabulary
    m = {"exposure": "creatine", "outcomes": ["memory"], "polarity": "benefit", "tags": ["Supplement", "Made Up", "Supplement", "Mortality"]}
    assert from_model_reading("does creatine help memory", m).tags == ["Supplement", "Mortality"]
    assert "Made Up" not in tag_vocabulary()


def test_preset_and_alias_readings_carry_the_presets_tags():
    from app.synthesis.interpret import alias_topic, interpret, presets
    p = next(x for x in presets() if x["slug"] == "red-meat")
    assert interpret(p["question"]).tags == p["tags"] == alias_topic("is bacon bad", None).tags
