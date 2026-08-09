"""Tests for #1069 S3 slice G — criteria revision (#1055 part 2).

The dead-end being retired is the operator's, hit live on 2026-07-22: revise edits the
plan's TASKS, never the criteria, and the old failure message invited rephrasing — a loop
that could never succeed. Slice A shipped the honest message; this slice is the real
capability behind it.

The load-bearing property in this file is THE MACHINE WALL: machine-gated criteria
(build / behavior / smoke) are KEEP-ONLY through this path. The folded test block in the
compiled prompts and the riding exam consume ONLY machine tiers, and both are frozen at
plan time by the #820/#877 safety asymmetry — if a criteria revision could edit a machine
criterion, the card would show one assertion while the exam tested another. So the wall is
tested from both sides: a rescope aimed at a machine row is discarded AND reported
protected; an OMITTED machine row is auto-kept (deny-by-default); and the judged tiers
(visual / human) are fully editable, with an added criterion FORCED to human.

Both knobs required (``criteria_revise`` AND ``advanced_intake``); off on a criteria-revise
goal is a clean Fail-Closed refusal. Model calls are faked throughout (offline, GPU-free).
"""

from __future__ import annotations

import json

from shared.fleet.acceptance import (
    TEST_TIERS,
    TIER_BUILD,
    TIER_HUMAN,
    TIER_VISUAL,
    generate_plan,
)
from shared.fleet.revise import (
    CRITERIA_REVISE_SENTINEL,
    JUDGED_TIERS,
    MACHINE_TIERS,
    CriteriaReviseOp,
    apply_criteria_revision_ops,
    compose_criteria_revision_goal,
    criteria_ops_from_dicts,
    generate_criteria_revision_ops,
    render_criteria_revision_delta,
    split_criteria_revision_goal,
)

# ---------------------------------------------------------------------------
# The tier mirror — revise.py stays acceptance-free, so the sets are replicated
# and PINNED equal here (the sandbox-prefix mirror pattern).
# ---------------------------------------------------------------------------


def test_machine_tiers_mirror_acceptances_tier_vocabulary():
    assert MACHINE_TIERS == set(TEST_TIERS) | {TIER_BUILD}
    assert JUDGED_TIERS == {TIER_VISUAL, TIER_HUMAN}
    assert not (MACHINE_TIERS & JUDGED_TIERS)


# ---------------------------------------------------------------------------
# Sentinel round-trip
# ---------------------------------------------------------------------------

_ROWS = [
    {"id": "c1", "text": "it scores a correct answer", "tier": "behavior",
     "check": "run the quiz"},
    {"id": "c2", "text": "big friendly buttons", "tier": "visual", "check": ""},
    {"id": "c3", "text": "feels quick", "tier": "human", "check": ""},
]


def test_sentinel_roundtrip():
    goal = compose_criteria_revision_goal("a quiz", "drop the buttons one", _ROWS)
    assert CRITERIA_REVISE_SENTINEL in goal
    clean, feedback, rows = split_criteria_revision_goal(goal)
    assert clean == "a quiz"
    assert feedback == "drop the buttons one"
    assert [r["id"] for r in rows] == ["c1", "c2", "c3"]


def test_split_without_sentinel_is_a_plain_goal():
    assert split_criteria_revision_goal("a quiz") == ("a quiz", "", [])


def test_split_malformed_payload_fails_soft():
    goal = "a quiz" + CRITERIA_REVISE_SENTINEL + "{not json"
    assert split_criteria_revision_goal(goal) == ("a quiz", "", [])


# ---------------------------------------------------------------------------
# The apply ruler — THE WALL, from both sides
# ---------------------------------------------------------------------------


def test_keep_is_byte_stable_and_rescope_edits_a_judged_row():
    ops = (
        CriteriaReviseOp(op="keep", ref=1),
        CriteriaReviseOp(op="rescope", ref=2, text="buttons usable one-handed"),
        CriteriaReviseOp(op="keep", ref=3),
    )
    out = apply_criteria_revision_ops(_ROWS, ops)
    assert out is not None and out.changed
    assert out.criteria[0] == _ROWS[0]                       # kept machine row, byte-stable
    assert out.criteria[1]["text"] == "buttons usable one-handed"
    assert out.criteria[1]["tier"] == "visual"               # tier survives a rescope
    assert out.criteria[1]["id"] == "c2"                     # identity survives too
    assert out.criteria[1]["check"] == ""                    # the old check never carries over
    assert out.rescoped_titles == ["buttons usable one-handed"]


def test_rescope_aimed_at_a_machine_row_is_discarded_and_reported_protected():
    ops = (
        CriteriaReviseOp(op="rescope", ref=1, text="it scores whatever I say"),
        CriteriaReviseOp(op="keep", ref=2),
        CriteriaReviseOp(op="keep", ref=3),
    )
    out = apply_criteria_revision_ops(_ROWS, ops)
    assert out is not None
    texts = [r["text"] for r in out.criteria]
    assert "it scores a correct answer" in texts, "the machine row must survive unchanged"
    assert "it scores whatever I say" not in texts
    assert out.protected_titles == ["it scores a correct answer"]


def test_an_omitted_machine_row_is_auto_kept_never_dropped():
    """Deny-by-default: leaving a machine criterion out of the ops is NOT a way to delete
    it — dropping an automatic check remains reject + re-dispatch."""
    ops = (CriteriaReviseOp(op="keep", ref=2),)  # omits c1 (behavior) and c3 (human)
    out = apply_criteria_revision_ops(_ROWS, ops)
    assert out is not None
    texts = [r["text"] for r in out.criteria]
    assert "it scores a correct answer" in texts, "omitted machine row must be auto-kept"
    assert "feels quick" not in texts, "an omitted judged row is a deliberate removal"
    assert out.removed_titles == ["feels quick"]
    assert "it scores a correct answer" in out.protected_titles


def test_added_criterion_is_forced_to_human_with_a_fresh_id():
    ops = (
        CriteriaReviseOp(op="keep", ref=1),
        CriteriaReviseOp(op="keep", ref=2),
        CriteriaReviseOp(op="keep", ref=3),
        CriteriaReviseOp(op="add", text="looks tidy on a phone"),
    )
    out = apply_criteria_revision_ops(_ROWS, ops)
    assert out is not None and out.changed
    added = out.criteria[3]
    assert added["tier"] == "human", "a post-plan addition must never mint a machine check"
    assert added["check"] == ""
    assert added["id"] not in {"c1", "c2", "c3"}
    assert out.added_titles == ["looks tidy on a phone"]


def test_all_keep_reproduction_is_not_a_change():
    ops = tuple(CriteriaReviseOp(op="keep", ref=i) for i in (1, 2, 3))
    out = apply_criteria_revision_ops(_ROWS, ops)
    assert out is not None and out.changed is False


def test_no_ops_or_empty_rows_fail_soft():
    assert apply_criteria_revision_ops(_ROWS, ()) is None
    assert apply_criteria_revision_ops([], (CriteriaReviseOp(op="keep", ref=1),)) is None


def test_wire_dicts_roundtrip_through_ops_from_dicts():
    ops = criteria_ops_from_dicts([
        {"op": "keep", "ref": 1},
        {"op": "rescope", "ref": "2", "text": "buttons usable one-handed"},
        {"op": "add", "text": "looks tidy on a phone"},
        {"op": "explode", "ref": 1},          # unknown op — dropped
        "garbage",                             # non-dict — dropped
    ])
    assert [o.op for o in ops] == ["keep", "rescope", "add"]
    assert ops[1].ref == 2                     # "2" coerced fail-soft


def test_wire_parity_dedupes_refs_and_drops_blank_adds():
    """Review F4: the wire seam applies the AO parser's shape rules — a hand-crafted
    payload cannot double-reference a ref (which would double-report a protected title)
    or mint a blank human row."""
    ops = criteria_ops_from_dicts([
        {"op": "rescope", "ref": 1, "text": "scores anything at all"},
        {"op": "rescope", "ref": 1, "text": "scores anything again"},   # dup — dropped
        {"op": "keep", "ref": 1},                                        # dup — dropped
        {"op": "add", "text": "ok"},                                     # blank-ish — dropped
        {"op": "rescope", "ref": 2, "text": "x"},                        # below floor — dropped
    ])
    assert [(o.op, o.ref) for o in ops] == [("rescope", 1)]
    # And the double-rescope of a machine row therefore reports protected ONCE.
    out = apply_criteria_revision_ops(_ROWS, ops + (CriteriaReviseOp(op="keep", ref=2),
                                                    CriteriaReviseOp(op="keep", ref=3)))
    assert out is not None
    assert out.protected_titles == ["it scores a correct answer"]


def test_all_adds_emission_is_legal_loud_and_wall_respecting():
    """An all-adds emission removes every judged row (loudly — the delta lists them) and
    auto-keeps every machine row; the additions land as human-tier."""
    ops = (CriteriaReviseOp(op="add", text="looks tidy on a phone"),)
    out = apply_criteria_revision_ops(_ROWS, ops)
    assert out is not None and out.changed
    texts = [r["text"] for r in out.criteria]
    assert "it scores a correct answer" in texts          # machine row auto-kept
    assert "big friendly buttons" not in texts            # judged rows removed...
    assert set(out.removed_titles) == {"big friendly buttons", "feels quick"}  # ...loudly
    assert out.criteria[0]["tier"] == "human" and out.criteria[0]["text"] == \
        "looks tidy on a phone"


# ---------------------------------------------------------------------------
# The proposer — prompt content + ruler behind it
# ---------------------------------------------------------------------------


def test_proposer_marks_machine_rows_protected_in_the_prompt():
    prompts: list[str] = []

    def gen(prompt: str) -> str:
        prompts.append(prompt)
        return json.dumps([{"op": "keep", "ref": 1}, {"op": "keep", "ref": 2},
                           {"op": "keep", "ref": 3}])

    generate_criteria_revision_ops("a quiz", _ROWS, "some feedback", generate_fn=gen)
    assert len(prompts) == 1
    assert "[protected] [behavior] it scores a correct answer" in prompts[0]
    assert "[protected] [visual]" not in prompts[0]


def test_proposer_fails_soft_on_model_error_and_blank_feedback():
    def boom(prompt: str) -> str:
        raise RuntimeError("model down")

    assert generate_criteria_revision_ops("g", _ROWS, "feedback", generate_fn=boom) == ()
    assert generate_criteria_revision_ops("g", _ROWS, "  ", generate_fn=lambda p: "[]") == ()


# ---------------------------------------------------------------------------
# Through generate_plan — the two-knob gate and the Fail-Closed refusal
# ---------------------------------------------------------------------------


def _sentinel_goal() -> str:
    return compose_criteria_revision_goal("a quiz", "drop the buttons one", _ROWS)


def _ops_gen(prompt: str) -> str:
    if "The current criteria:" in prompt:
        return json.dumps([{"op": "keep", "ref": 1}, {"op": "keep", "ref": 3}])
    return "[]"


def test_generate_plan_returns_ops_with_both_knobs_on(tmp_path):
    proj = tmp_path / "projects"
    (proj / "quiz" / ".git").mkdir(parents=True)
    plan = generate_plan(_sentinel_goal(), "quiz", generate_fn=_ops_gen,
                         projects_dir=proj, advanced_intake=True, criteria_revise=True)
    assert plan.ok
    assert plan.criteria_revision and plan.criteria_revision[0]["op"] == "keep"
    assert plan.tasks == [] and not plan.spec.criteria, "an early-return carries no plan"


def test_generate_plan_refuses_fail_closed_when_the_stage_is_off(tmp_path):
    proj = tmp_path / "projects"
    (proj / "quiz" / ".git").mkdir(parents=True)
    for knobs in ({}, {"advanced_intake": True}, {"criteria_revise": True}):
        plan = generate_plan(_sentinel_goal(), "quiz", generate_fn=_ops_gen,
                             projects_dir=proj, **knobs)
        assert not plan.ok, f"knobs {knobs} must refuse"
        assert "turned off" in plan.message
        assert plan.criteria_revision == []


def test_a_criteria_sentinel_goal_never_falls_through_to_a_fresh_plan(tmp_path):
    """The refusal shape matters: a sentinel-laden goal must NEVER be planned as if the
    sentinel text were the operator's idea (the #820 lesson, applied here)."""
    proj = tmp_path / "projects"
    (proj / "quiz" / ".git").mkdir(parents=True)
    calls: list[str] = []

    def spy(prompt: str) -> str:
        calls.append(prompt)
        return "[]"

    plan = generate_plan(_sentinel_goal(), "quiz", generate_fn=spy, projects_dir=proj)
    assert not plan.ok
    assert calls == [], "the refusal must return before ANY model call"


# ---------------------------------------------------------------------------
# The delta card
# ---------------------------------------------------------------------------


def test_delta_names_all_four_sections():
    ops = (
        CriteriaReviseOp(op="rescope", ref=2, text="buttons usable one-handed"),
        CriteriaReviseOp(op="rescope", ref=1, text="scores anything"),  # protected
        CriteriaReviseOp(op="add", text="looks tidy on a phone"),
    )
    out = apply_criteria_revision_ops(_ROWS, ops)
    assert out is not None
    delta = render_criteria_revision_delta(out, "make it friendlier")
    assert "Reworded:" in delta and "buttons usable one-handed" in delta
    assert "Added (you check these yourself):" in delta
    assert "Removed:" in delta and "feels quick" in delta
    assert "Protected" in delta and "it scores a correct answer" in delta
    assert "reject" in delta, "the protected section must route to the real alternative"
