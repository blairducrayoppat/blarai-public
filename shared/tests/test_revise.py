"""Tests for the plan-feedback REVISION engine (:mod:`shared.fleet.revise`, #820).

The engine is PURE + GPU-free (the model call is injected). Coverage: the goal-seam
compose/split round-trip, the grammar-first emission + free-text fallback, the deterministic
ruler (ref-range validation, dedupe, per-op field requirements, cap), the byte-stable APPLY
(a kept task is copied verbatim, an add/revise is new, removed/reordered detected), the
plain-language delta, and the absolute fail-soft (garbage/empty -> () / None). The coordinator
lifecycle (cap, tombstone, fail-soft re-render) is covered in
tests/integration/test_dispatch_coordinator.py.
"""

from __future__ import annotations

import pytest

from shared.fleet import revise as r


# ── goal-seam compose / split ────────────────────────────────────────────


def test_compose_split_roundtrip():
    goal = "a todo app"
    fb = "skip the login and add CSV export first"
    titles = ["Build login", "Build tracker", "Add persistence"]
    embedded = r.compose_revision_goal(goal, fb, titles)
    assert r.REVISE_SENTINEL in embedded
    clean, out_fb, out_titles = r.split_revision_goal(embedded)
    assert clean == goal and out_fb == fb and out_titles == titles


def test_split_plain_goal_is_noop():
    # A goal WITHOUT the sentinel is a normal plan request — byte-identical to today.
    assert r.split_revision_goal("just a normal goal") == ("just a normal goal", "", [])


def test_split_malformed_payload_fails_soft():
    # A corrupt payload after the sentinel degrades to the clean head + empty feedback/titles.
    bad = "a goal" + r.REVISE_SENTINEL + "{not json"
    assert r.split_revision_goal(bad) == ("a goal", "", [])


def test_compose_strips_and_coerces():
    embedded = r.compose_revision_goal("  g  ", "  fb  ", ["a", "b"])
    clean, fb, titles = r.split_revision_goal(embedded)
    assert clean == "g" and fb == "fb" and titles == ["a", "b"]


# ── the ruler: _parse_revision_ops ───────────────────────────────────────


def test_parse_keep_add_revise():
    text = (
        '[{"op":"keep","ref":1},'
        '{"op":"add","task":"CSV Export","prompt":"add a CSV export button"},'
        '{"op":"revise","ref":2,"task":"tracker-v2","prompt":"a richer tracker view"}]'
    )
    ops = r._parse_revision_ops(text, n_tasks=3)
    assert [o.op for o in ops] == ["keep", "add", "revise"]
    assert ops[0].ref == 1
    assert ops[1].task == "csv-export" and ops[1].prompt == "add a CSV export button"
    assert ops[2].ref == 2 and ops[2].task == "tracker-v2"


def test_parse_drops_out_of_range_ref():
    # ref 9 does not exist (only 2 tasks) -> dropped; ref 0 invalid -> dropped.
    ops = r._parse_revision_ops('[{"op":"keep","ref":9},{"op":"keep","ref":0},{"op":"keep","ref":2}]', n_tasks=2)
    assert [o.ref for o in ops] == [2]


def test_parse_dedupes_refs():
    # A task referenced twice (keep then keep, or keep then revise) is taken once.
    ops = r._parse_revision_ops(
        '[{"op":"keep","ref":1},{"op":"keep","ref":1},'
        '{"op":"revise","ref":1,"task":"x","prompt":"changed scope"}]',
        n_tasks=3,
    )
    assert len(ops) == 1 and ops[0].op == "keep" and ops[0].ref == 1


def test_parse_drops_vacuous_add():
    # add with no slug or a too-short prompt is dropped.
    ops = r._parse_revision_ops('[{"op":"add","task":"","prompt":"long enough"},{"op":"add","task":"ok","prompt":"x"}]', n_tasks=1)
    assert ops == ()


def test_parse_string_and_float_refs_coerced():
    ops = r._parse_revision_ops('[{"op":"keep","ref":"2"},{"op":"keep","ref":1.0}]', n_tasks=2)
    assert sorted(o.ref for o in ops) == [1, 2]


def test_parse_bool_ref_rejected():
    # bool is an int subclass — a True/False ref must NOT be read as ref 1/0.
    assert r._parse_revision_ops('[{"op":"keep","ref":true}]', n_tasks=3) == ()


def test_parse_garbage_and_empty():
    assert r._parse_revision_ops("not json at all", n_tasks=3) == ()
    assert r._parse_revision_ops("[]", n_tasks=3) == ()
    assert r._parse_revision_ops('{"op":"keep"}', n_tasks=3) == ()  # object, not array
    assert r._parse_revision_ops("", n_tasks=3) == ()


def test_parse_unknown_op_skipped():
    ops = r._parse_revision_ops('[{"op":"delete","ref":1},{"op":"keep","ref":1}]', n_tasks=2)
    assert [o.op for o in ops] == ["keep"]


def test_parse_caps_step_count():
    # More than the step cap collapses to the cap (a small model can loop).
    items = ",".join('{"op":"add","task":"t%d","prompt":"a valid prompt"}' % i for i in range(50))
    ops = r._parse_revision_ops("[" + items + "]", n_tasks=0)
    assert len(ops) == r._MAX_REVISION_STEPS


def test_parse_slug_sanitizes():
    ops = r._parse_revision_ops('[{"op":"add","task":"My Cool Feature!!","prompt":"do the thing"}]', n_tasks=1)
    assert ops[0].task == "my-cool-feature"


# ── generate_revision_ops: grammar-first + fail-soft ─────────────────────


def test_generate_free_text_path():
    def gen(_prompt):
        return '[{"op":"keep","ref":1},{"op":"add","task":"export","prompt":"add export"}]'

    ops = r.generate_revision_ops("g", ["Task one"], "add export", generate_fn=gen)
    assert [o.op for o in ops] == ["keep", "add"]


def test_generate_grammar_first_used_when_present():
    calls = {"grammar": 0, "free": 0}

    def structured(_p, _schema):
        calls["grammar"] += 1
        return '[{"op":"keep","ref":1}]'

    def gen(_p):
        calls["free"] += 1
        return "[]"

    ops = r.generate_revision_ops(
        "g", ["Task one"], "keep it", generate_fn=gen, structured_generate_fn=structured
    )
    assert len(ops) == 1 and calls["grammar"] == 1 and calls["free"] == 0  # grammar won, no fallback


def test_generate_grammar_raises_falls_back_to_free_text():
    def structured(_p, _schema):
        raise RuntimeError("grammar hook down")

    def gen(_p):
        return '[{"op":"keep","ref":1}]'

    ops = r.generate_revision_ops(
        "g", ["Task one"], "keep it", generate_fn=gen, structured_generate_fn=structured
    )
    assert len(ops) == 1  # the hook raising must NOT add a failure mode


def test_generate_model_raises_is_failsoft():
    def gen(_p):
        raise RuntimeError("model down")

    assert r.generate_revision_ops("g", ["Task one"], "change it", generate_fn=gen) == ()


def test_generate_blank_feedback_or_no_tasks_is_empty():
    assert r.generate_revision_ops("g", ["Task"], "   ", generate_fn=lambda p: "x") == ()
    assert r.generate_revision_ops("g", [], "change it", generate_fn=lambda p: "x") == ()


def test_generate_prompt_carries_feedback_and_numbered_tasks():
    seen = {}

    def gen(prompt):
        seen["prompt"] = prompt
        return "[]"

    r.generate_revision_ops("a todo app", ["Build login", "Build tracker"], "skip login", generate_fn=gen)
    p = seen["prompt"]
    assert "skip login" in p and "1. Build login" in p and "2. Build tracker" in p and "a todo app" in p


# ── apply_revision_ops: byte-stable keeps, adds, removals, reorder ───────


def _features():
    return [
        {"repo": "todo", "task": "build-login", "prompt": "P1", "surface": "web"},
        {"repo": "todo", "task": "build-tracker", "prompt": "P2", "surface": "web"},
        {"repo": "todo", "task": "add-persistence", "prompt": "P3", "surface": "web"},
    ]


def test_apply_keep_is_byte_identical():
    feats = _features()
    ops = (r.ReviseOp("keep", ref=2), r.ReviseOp("keep", ref=3))
    out = r.apply_revision_ops(feats, ops, repo="todo")
    assert out is not None
    # The kept task dicts are byte-identical to the originals (never a fresh decompose).
    assert out.tasks[0] == feats[1] and out.tasks[1] == feats[2]
    assert out.removed_titles == ["Build login"]
    assert out.kept_titles == ["Build tracker", "Add persistence"]
    assert out.changed is True  # a task was removed


def test_apply_add_and_keep():
    feats = _features()
    ops = (
        r.ReviseOp("add", task="csv-export", prompt="export to CSV file"),
        r.ReviseOp("keep", ref=1),
        r.ReviseOp("keep", ref=2),
        r.ReviseOp("keep", ref=3),
    )
    out = r.apply_revision_ops(feats, ops, repo="todo")
    assert [t["task"] for t in out.tasks] == ["csv-export", "build-login", "build-tracker", "add-persistence"]
    assert out.added_titles == ["Csv export"] and out.removed_titles == []
    assert out.tasks[0] == {"repo": "todo", "task": "csv-export", "prompt": "export to CSV file"}


def test_apply_revise_replaces():
    feats = _features()
    ops = (
        r.ReviseOp("keep", ref=1),
        r.ReviseOp("revise", ref=2, task="tracker-v2", prompt="a richer tracker with charts"),
        r.ReviseOp("keep", ref=3),
    )
    out = r.apply_revision_ops(feats, ops, repo="todo")
    assert out.revised_titles == ["Tracker v2"] and out.removed_titles == []
    assert out.tasks[1] == {"repo": "todo", "task": "tracker-v2", "prompt": "a richer tracker with charts"}
    assert out.changed is True


def test_apply_reorder_detected():
    feats = _features()
    ops = (r.ReviseOp("keep", ref=3), r.ReviseOp("keep", ref=1), r.ReviseOp("keep", ref=2))
    out = r.apply_revision_ops(feats, ops, repo="todo")
    assert out.reordered is True and out.changed is True
    assert out.removed_titles == []  # all kept, just reordered


def test_apply_all_keep_same_order_is_unchanged():
    feats = _features()
    ops = (r.ReviseOp("keep", ref=1), r.ReviseOp("keep", ref=2), r.ReviseOp("keep", ref=3))
    out = r.apply_revision_ops(feats, ops, repo="todo")
    assert out is not None and out.changed is False  # a no-op revision -> coordinator fails soft


def test_apply_empty_ops_is_none():
    assert r.apply_revision_ops(_features(), (), repo="todo") is None


def test_apply_all_garbage_ops_yields_none():
    # Ops that all reference nothing real -> no tasks survive -> None (fail-soft).
    ops = (r.ReviseOp("keep", ref=99), r.ReviseOp("revise", ref=99, task="x", prompt="changed"))
    assert r.apply_revision_ops(_features(), ops, repo="todo") is None


def test_apply_does_not_mutate_originals():
    feats = _features()
    before = [dict(t) for t in feats]
    r.apply_revision_ops(feats, (r.ReviseOp("keep", ref=1),), repo="todo")
    assert feats == before  # the originals are untouched (kept tasks are COPIES)


# ── ops_from_dicts (wire reconstruction) ─────────────────────────────────


def test_ops_from_dicts_roundtrip():
    wire = [
        {"op": "keep", "ref": 1, "task": "", "prompt": ""},
        {"op": "add", "ref": 0, "task": "Export", "prompt": "export it"},
    ]
    ops = r.ops_from_dicts(wire)
    assert ops[0] == r.ReviseOp("keep", ref=1)
    assert ops[1].op == "add" and ops[1].task == "export"


def test_ops_from_dicts_failclosed():
    assert r.ops_from_dicts("not a list") == ()
    assert r.ops_from_dicts([{"op": "nonsense"}, "junk", 42]) == ()


# ── delta rendering ──────────────────────────────────────────────────────


def test_render_delta_shows_all_change_classes():
    out = r.RevisionOutcome(
        tasks=[], kept_titles=["Kept one"], added_titles=["New feature"],
        revised_titles=["Reworked"], removed_titles=["Old one"], reordered=True, changed=True,
    )
    delta = r.render_revision_delta(out, "do the things")
    assert "do the things" in delta
    assert "Added:" in delta and "New feature" in delta
    assert "Changed:" in delta and "Reworked" in delta
    assert "Removed:" in delta and "Old one" in delta
    assert "Reordered" in delta


def test_render_delta_no_change_note():
    out = r.RevisionOutcome(changed=False)
    assert "No changes" in r.render_revision_delta(out, "fb")
