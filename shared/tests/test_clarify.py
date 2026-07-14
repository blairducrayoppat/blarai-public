"""Tests for the requirements-clarification stage (#819) — ``shared.fleet.clarify``.

The model PROPOSES clarifying questions; a deterministic ruler DISPOSES. These tests pin:
the sufficiency check (an empty emission asks nothing), the ruler (dedupe by axis, cap,
vacuous floor, unknown-axis coercion), grammar-first with fail-soft to free-text, the
"just decide for me" escape + its recorded defaults, the free-text answer record, and the
goal-sentinel compose/split round-trip that carries the enriched block across the plan seam.
"""

from __future__ import annotations

import json

from shared.fleet import clarify


# ---- question generation + sufficiency -----------------------------------


def _gen(payload: str):
    return lambda _prompt: payload


def test_generate_questions_parses_and_tags_axes():
    payload = json.dumps([
        {"axis": "surface", "question": "Where will you use this — computer, browser, or phone?"},
        {"axis": "persistence", "question": "Should your information be saved between uses?"},
    ])
    qs = clarify.generate_clarifying_questions("an app", generate_fn=_gen(payload))
    assert [q.axis for q in qs] == ["surface", "persistence"]
    assert all(isinstance(q, clarify.ClarifyQuestion) for q in qs)


def test_sufficient_goal_asks_nothing():
    # The model returns [] for a goal that already carries the axes — the sufficiency check.
    assert clarify.generate_clarifying_questions("x", generate_fn=_gen("[]")) == ()


def test_blank_goal_asks_nothing():
    assert clarify.generate_clarifying_questions("   ", generate_fn=_gen("[irrelevant]")) == ()


def test_generate_is_fail_soft_on_model_error():
    def boom(_prompt):
        raise RuntimeError("model down")

    assert clarify.generate_clarifying_questions("an app", generate_fn=boom) == ()


def test_generate_fail_soft_on_garbage():
    assert clarify.generate_clarifying_questions("an app", generate_fn=_gen("not json at all")) == ()


# ---- the ruler ------------------------------------------------------------


def test_ruler_dedupes_by_axis():
    payload = json.dumps([
        {"axis": "surface", "question": "Where will you use this app mainly?"},
        {"axis": "surface", "question": "A second surface question that must be dropped."},
        {"axis": "scope", "question": "How big a first version do you want?"},
    ])
    qs = clarify._parse_questions(payload, max_questions=5)
    assert [q.axis for q in qs] == ["surface", "scope"]  # one per axis, order preserved


def test_ruler_caps_question_count():
    items = [{"axis": a, "question": f"A clear question about {a} here?"}
             for a in ["surface", "persistence", "feature", "visual", "scope"]]
    qs = clarify._parse_questions(json.dumps(items), max_questions=2)
    assert len(qs) == 2


def test_ruler_drops_vacuous_and_coerces_unknown_axis():
    payload = json.dumps([
        {"axis": "surface", "question": "hi"},                       # too short -> dropped
        {"axis": "bogus", "question": "A perfectly clear question?"},  # unknown axis -> feature
    ])
    qs = clarify._parse_questions(payload, max_questions=5)
    assert len(qs) == 1 and qs[0].axis == clarify.AXIS_FEATURE


def test_ruler_non_list_and_non_dict_items():
    assert clarify._parse_questions('{"axis":"surface"}', max_questions=5) == ()
    assert clarify._parse_questions('[1, "x", null]', max_questions=5) == ()


# ---- grammar-first, fail-soft to free-text --------------------------------


def test_grammar_first_used_when_hook_present():
    grammar_payload = json.dumps([{"axis": "scope", "question": "How big a first version?"}])
    calls = {"free": 0}

    def free(_prompt):
        calls["free"] += 1
        return "[]"

    def structured(_prompt, _schema):
        return grammar_payload

    qs = clarify.generate_clarifying_questions("an app", generate_fn=free, structured_generate_fn=structured)
    assert [q.axis for q in qs] == ["scope"]
    assert calls["free"] == 0  # the free-text path was NOT taken


def test_grammar_error_falls_back_to_free_text():
    def structured(_prompt, _schema):
        raise RuntimeError("xgrammar crashed")

    payload = json.dumps([{"axis": "surface", "question": "Where will you use this?"}])
    qs = clarify.generate_clarifying_questions("an app", generate_fn=_gen(payload), structured_generate_fn=structured)
    assert [q.axis for q in qs] == ["surface"]  # free-text path recovered it


def test_grammar_empty_array_is_accepted_as_sufficient():
    # A grammar-constrained [] is a valid "ask nothing" answer, NOT a fallback trigger.
    calls = {"free": 0}

    def free(_prompt):
        calls["free"] += 1
        return json.dumps([{"axis": "surface", "question": "should not be reached"}])

    qs = clarify.generate_clarifying_questions("an app", generate_fn=free,
                                               structured_generate_fn=lambda _p, _s: "[]")
    assert qs == () and calls["free"] == 0


def test_schema_enum_pins_axes():
    schema = clarify.clarify_questions_emission_json_schema(max_questions=3)
    assert schema["maxItems"] == 3
    assert set(schema["items"]["properties"]["axis"]["enum"]) == set(clarify.CLARIFY_AXES)
    assert "minItems" not in schema  # [] must be a valid emission


# ---- "just decide for me" + recorded defaults -----------------------------


def test_is_decide_for_me_recognises_variants():
    for s in ["just decide for me", "Just decide", "you decide", "decide", "up to you", "whatever you think"]:
        assert clarify.is_decide_for_me(s), s
    for s in ["on my computer", "save my todos", "a blue theme"]:
        assert not clarify.is_decide_for_me(s), s


def test_decide_defaults_records_per_axis_assumptions():
    qs = (clarify.ClarifyQuestion("surface", "where?"), clarify.ClarifyQuestion("visual", "look?"))
    out = clarify.decide_defaults(qs)
    assert [c["assumed"] for c in out] == [True, True]
    assert out[0]["answer"] == clarify.DEFAULT_AXIS_ANSWERS["surface"]
    assert out[1]["answer"] == clarify.DEFAULT_AXIS_ANSWERS["visual"]


def test_answered_from_free_text_records_one_entry():
    qs = (clarify.ClarifyQuestion("surface", "where?"),)
    out = clarify.answered_from_free_text(qs, "on my laptop, and save my data")
    assert len(out) == 1 and out[0]["assumed"] is False
    assert out[0]["answer"] == "on my laptop, and save my data"


def test_answered_from_free_text_blank_is_empty():
    assert clarify.answered_from_free_text((), "   ") == []


def test_questions_from_dicts_roundtrip_and_fail_closed():
    raw = [{"axis": "surface", "question": "q1"}, {"axis": "bad", "question": "q2"}, "junk", {"question": ""}]
    qs = clarify.questions_from_dicts(raw)
    assert [(q.axis, q.question) for q in qs] == [("surface", "q1"), (clarify.AXIS_FEATURE, "q2")]
    assert clarify.questions_from_dicts("not a list") == ()


# ---- compose / split the enriched block across the plan seam --------------


def test_compose_requirements_block_tags_assumptions():
    block = clarify.compose_requirements_block([
        {"question": "q", "answer": "on my computer", "assumed": False},
        {"question": "q2", "answer": "a clean look", "assumed": True},
        {"question": "q3", "answer": "  ", "assumed": False},  # blank -> skipped
    ])
    assert "- on my computer" in block
    assert "- (assumed) a clean look" in block
    assert "  " not in block.splitlines()[1:]  # no blank-answer line


def test_compose_requirements_block_empty():
    assert clarify.compose_requirements_block([]) == ""
    assert clarify.compose_requirements_block([{"answer": ""}]) == ""


def test_compose_split_planning_goal_roundtrip():
    block = clarify.compose_requirements_block([{"question": "q", "answer": "on my computer", "assumed": False}])
    enriched = clarify.compose_planning_goal("a todo app", block)
    assert clarify.REQUIREMENTS_SENTINEL in enriched
    clean, req = clarify.split_planning_goal(enriched)
    assert clean == "a todo app" and "on my computer" in req


def test_compose_planning_goal_empty_block_is_plain_goal():
    assert clarify.compose_planning_goal("a todo app", "") == "a todo app"


def test_split_plain_goal_is_byte_identical():
    # A goal without the sentinel -> (goal, "") — the today's-flow guarantee.
    assert clarify.split_planning_goal("just a normal goal") == ("just a normal goal", "")


# ---- token-cost estimate (reported, not gated) ----------------------------


def test_estimate_tokens_is_monotonic_and_zero_for_empty():
    assert clarify.estimate_tokens("") == 0
    assert clarify.estimate_tokens("   ") == 0
    short = clarify.estimate_tokens("on my computer")
    longer = clarify.estimate_tokens("on my computer and please save all of my data between uses")
    assert 0 < short < longer
