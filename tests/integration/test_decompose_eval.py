"""Decomposition right-sizing EVAL (over-decomposition fix, builder brief Problem 1).

Feeds goals of KNOWN size — each paired with the over-decomposed task list a free-
associating 14B would emit — through the REAL ``decompose_request`` and asserts the
output is RIGHT-SIZED:

  * the brief's named acceptance cases directly (is_leap_year -> exactly 1; a CLI todo
    app -> a single-digit count of coherent tasks; the four adversarial "must survive"
    goals keep their feature), and
  * a 32-case ADVERSARIAL CORPUS from a four-lens red-team (``decompose_eval_corpus.json``,
    workflow wf_5bc7e0bd): 16 explosions that must collapse with NO structural/atomic-split
    task surviving, and 16 test/validate/check/scan-looking goals that are real FEATURES
    and must NOT collapse.

MUTATION-RESISTANCE (the load-bearing discipline). The over-split oracle
(``_oversplit_findings``) is defined HERE and NEVER imports or calls the collapse code, so
disabling the ruler does not disable the detector (point 3 of the LA review). The
``test_mutation_*`` cases monkeypatch ``_collapse`` to the identity — the ruler disabled —
and show the SAME goals make the oracle FAIL (the explosion's structural slugs reappear). A
green run never shown failing when reverted proves nothing.

The model is injected (a fake ``generate_fn`` returning the explosion), so the eval runs
without a GPU.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from shared.fleet import decompose as dc

_CORPUS = json.loads(
    (Path(__file__).parent / "decompose_eval_corpus.json").read_text(encoding="utf-8")
)
MUST_COLLAPSE = _CORPUS["must_collapse"]
MUST_SURVIVE = _CORPUS["must_survive"]

#: A right-sized decomposition is still "single-digit" (the brief's medium-goal bound).
_SINGLE_DIGIT = 8


# ---------------------------------------------------------------------------
# The INDEPENDENT over-split oracle — self-contained, never imports the collapse
# code, so the mutation proof (disable the ruler -> oracle fails) is non-circular.
# ---------------------------------------------------------------------------

#: Slug shapes a right-sized decomposition must NEVER emit — atomic / structural /
#: per-test-case / scaffold splits. These are the fingerprints of over-decomposition.
_BAD_SLUG_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p) for p in (
        r"^define-", r"^declare-", r"^scaffold-", r"^stub-", r"^setup-",
        r"^(create|add|make)-file", r"^test-", r"^verif", r"^acceptance-tests?$",
        r"(^|-)tests?$", r"-\d{2,4}$",
    )
)


def _structural_survivors(slugs: list[str]) -> list[str]:
    """The slugs that look like an atomic/structural split (the oracle's positive set).

    A one-directional detector applied ONLY to must_collapse survivors: it flags a leading
    ``test-``/``verif`` broadly (to catch ``verify-edge-cases`` / ``test-x-200`` in a
    disabled-ruler explosion). A NAMED verification deliverable like ``verify-signature``
    would also match — but it never appears as a must_collapse survivor; the must_survive
    cases validate such deliverables by FEATURE-PRESENCE, not through this oracle.
    """
    return [s for s in slugs if any(p.search(s) for p in _BAD_SLUG_PATTERNS)]


def _oversplit_findings(tasks: list[dict], *, max_tasks: int) -> list[str]:
    """Reasons the task set is over-decomposed; empty list == right-sized.

    Two INDEPENDENT signals (the brief's "count threshold AND known-bad slug patterns"):
    a count over the goal's known coherent size, and any structural/atomic-split slug.
    """
    slugs = [t["task"] for t in tasks]
    findings: list[str] = []
    if len(tasks) > max_tasks:
        findings.append(f"count {len(tasks)} > {max_tasks}")
    bad = _structural_survivors(slugs)
    if bad:
        findings.append(f"structural/atomic-split slugs survived: {bad}")
    return findings


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


def _projects(tmp_path):
    proj = tmp_path / "projects"
    (proj / "myapp" / ".git").mkdir(parents=True)
    return proj


def _model_returning(slugs: list[str]):
    """A fake generate_fn that emits the given over-decomposed task list as JSON."""
    payload = json.dumps([{"task": s, "prompt": f"do the work for {s}"} for s in slugs])
    return lambda _prompt: payload


def _run(goal: str, slugs: list[str], proj):
    return dc.decompose_request(
        goal, "myapp", generate_fn=_model_returning(slugs), projects_dir=proj,
    )


# ---------------------------------------------------------------------------
# The brief's NAMED acceptance criteria (asserted directly)
# ---------------------------------------------------------------------------

# The exact ~9-task explosion the brief reported for the one-liner goal.
_LEAP_YEAR_EXPLOSION = [
    "define-is-leap-year-function", "implement-leap-year-logic",
    "test-is-leap-year-2024", "test-is-leap-year-1900", "test-is-leap-year-2000",
    "verify-edge-cases", "acceptance-tests", "create-file",
]


def test_is_leap_year_collapses_to_exactly_one_task(tmp_path):
    proj = _projects(tmp_path)
    res = _run("write an is_leap_year function", _LEAP_YEAR_EXPLOSION, proj)
    assert res.ok
    assert len(res.tasks) == 1, [t["task"] for t in res.tasks]   # brief: EXACTLY 1
    assert "leap-year" in res.tasks[0]["task"]
    assert res.collapsed_test_intent is True
    assert not _oversplit_findings(res.tasks, max_tasks=1)


def test_is_palindrome_collapses_to_exactly_one_task(tmp_path):
    # The live #670 Problem-3 shakedown goal: is_palindrome over-split into
    # implement-is-palindrome + acceptance-tests. The decomposer must right-size to ONE
    # feature task carrying the test INTENT (the test work is folded downstream, never a
    # sibling fleet task that spins its own worktree).
    proj = _projects(tmp_path)
    explosion = [
        "define-is-palindrome", "implement-is-palindrome",
        "test-is-palindrome-racecar", "test-is-palindrome-hello",
        "verify-edge-cases", "acceptance-tests", "create-file",
    ]
    res = _run("write an is_palindrome function", explosion, proj)
    assert res.ok
    assert len(res.tasks) == 1, [t["task"] for t in res.tasks]   # brief: EXACTLY 1
    assert "palindrome" in res.tasks[0]["task"]
    assert res.collapsed_test_intent is True
    assert not _oversplit_findings(res.tasks, max_tasks=1)


def test_slugify_collapses_to_exactly_one_task(tmp_path):
    proj = _projects(tmp_path)
    explosion = [
        "define-slugify", "implement-slugify",
        "test-slugify-spaces", "test-slugify-unicode",
        "verify-edge-cases", "acceptance-tests",
    ]
    res = _run("write a slugify function", explosion, proj)
    assert res.ok
    assert len(res.tasks) == 1, [t["task"] for t in res.tasks]   # brief: EXACTLY 1
    assert "slugify" in res.tasks[0]["task"]
    assert res.collapsed_test_intent is True
    assert not _oversplit_findings(res.tasks, max_tasks=1)


def test_cli_todo_app_is_single_digit_distinct_features(tmp_path):
    # The brief's medium goal: a single-digit count of COHERENT tasks, one per VERB
    # (add/list/done are distinct features), NOT one per test-case / file / step.
    proj = _projects(tmp_path)
    explosion = [
        "implement-add-todo", "implement-list-todos", "implement-mark-done",
        "define-todo-model", "test-add", "test-list", "test-done", "acceptance-tests",
    ]
    res = _run("a CLI todo app: add, list, and done", explosion, proj)
    assert res.ok
    slugs = [t["task"] for t in res.tasks]
    assert not _oversplit_findings(res.tasks, max_tasks=_SINGLE_DIGIT), slugs
    assert 3 <= len(slugs) <= 6, slugs                       # the 3 verbs, not 8 micro-tasks
    for verb in ("add", "list", "done"):
        assert any(verb in s for s in slugs), (verb, slugs)


@pytest.mark.parametrize("goal,slugs,survives", [
    ("build a unit-test generator",
     ["build-unit-test-generator", "implement-signature-parser", "write-tests"], "generator"),
    ("add input validation to the signup form",
     ["implement-input-validation", "test-validation", "verify-form"], "validation"),
    ("implement a /health-check endpoint",
     ["implement-health-check-endpoint", "test-health-check", "verify-edge-cases"], "health-check"),
    ("write a linter rule",
     ["implement-linter-rule", "write-tests", "add-test-fixtures"], "linter"),
])
def test_brief_adversarial_goals_survive(goal, slugs, survives, tmp_path):
    # The four goals the LA named: their feature must NOT be collapsed as if it were a test.
    proj = _projects(tmp_path)
    res = _run(goal, slugs, proj)
    assert res.ok and res.tasks
    assert any(survives in t["task"] for t in res.tasks), [t["task"] for t in res.tasks]


# ---------------------------------------------------------------------------
# The red-team CORPUS — GREEN (the ruler right-sizes every explosion)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", MUST_COLLAPSE, ids=[c["goal"][:48] for c in MUST_COLLAPSE])
def test_corpus_must_collapse_is_right_sized(case, tmp_path):
    proj = _projects(tmp_path)
    res = _run(case["goal"], case["slugs"], proj)
    assert res.ok and res.tasks
    slugs = [t["task"] for t in res.tasks]
    # No structural / atomic-split task survives — EXCEPT a small, explicitly-marked
    # `overkeep` budget for the handful of standalone per-case tests that are shape-
    # identical to a verify-<feature> deliverable (kept on purpose; never a dropped
    # feature — see case['note']). 13/16 cases have overkeep==0.
    overkeep = case.get("overkeep", 0)
    structural = _structural_survivors(slugs)
    assert len(structural) <= overkeep, (
        f"{case['goal']!r}: structural survivors {structural} exceed overkeep budget {overkeep}"
    )
    # Reduced from the proposal AND single-digit.
    assert len(slugs) < len(case["slugs"]), f"{case['goal']!r}: no reduction {slugs}"
    bound = case.get("exact", case.get("max", _SINGLE_DIGIT)) + overkeep
    assert len(slugs) <= bound, f"{case['goal']!r}: {len(slugs)} > {bound} {slugs} ({case.get('note','')})"
    if "exact" in case and not overkeep:
        assert len(slugs) == case["exact"], f"{case['goal']!r}: expected {case['exact']}, got {slugs}"


@pytest.mark.parametrize("case", MUST_SURVIVE, ids=[c["goal"][:48] for c in MUST_SURVIVE])
def test_corpus_must_survive_keeps_features(case, tmp_path):
    proj = _projects(tmp_path)
    res = _run(case["goal"], case["slugs"], proj)
    assert res.ok and res.tasks
    slugs = [t["task"] for t in res.tasks]
    assert len(slugs) >= case["min"], f"{case['goal']!r}: collapsed to {slugs}, expected >= {case['min']}"
    for sub in case["survives"]:
        assert any(sub in s for s in slugs), f"{case['goal']!r}: feature {sub!r} lost; survivors={slugs}"


def test_corpus_no_goal_ends_with_zero_tasks(tmp_path):
    proj = _projects(tmp_path)
    for case in MUST_COLLAPSE + MUST_SURVIVE:
        res = _run(case["goal"], case["slugs"], proj)
        assert res.ok and len(res.tasks) >= 1, case["goal"]


# ---------------------------------------------------------------------------
# MUTATION — disable the ruler; the INDEPENDENT oracle must catch the explosion
# (proves teeth + non-circularity: the oracle never calls _collapse)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", MUST_COLLAPSE, ids=[c["goal"][:48] for c in MUST_COLLAPSE])
def test_mutation_disabled_ruler_fails_the_oracle(case, tmp_path, monkeypatch):
    # Disable ONLY the right-sizing ruler (identity collapse). The oracle is unchanged —
    # it does not import _collapse — so it still runs and now FAILS on the explosion.
    monkeypatch.setattr(dc, "_collapse", lambda candidates: (list(candidates), False))
    proj = _projects(tmp_path)
    res = _run(case["goal"], case["slugs"], proj)
    bound = case.get("exact", case.get("max", _SINGLE_DIGIT)) + case.get("overkeep", 0)
    findings = _oversplit_findings(res.tasks, max_tasks=bound)
    assert findings, (
        f"MUTATION ESCAPED: with the ruler disabled, {case['goal']!r} still looked "
        f"right-sized ({[t['task'] for t in res.tasks]}) — the oracle has no teeth"
    )


def test_mutation_leap_year_explodes_without_the_ruler(tmp_path, monkeypatch):
    # The brief's headline case, explicit: disable the ruler -> the ~9-task explosion
    # reappears and the oracle (count + structural slugs) fails hard.
    monkeypatch.setattr(dc, "_collapse", lambda candidates: (list(candidates), False))
    proj = _projects(tmp_path)
    res = _run("write an is_leap_year function", _LEAP_YEAR_EXPLOSION, proj)
    findings = _oversplit_findings(res.tasks, max_tasks=1)
    assert findings and len(res.tasks) > 1, [t["task"] for t in res.tasks]


def test_oracle_self_check():
    # The oracle is honest independent of any production code: it flags known structural
    # slugs and clears clean feature slugs.
    assert _structural_survivors(
        ["define-x", "test-y-2024", "acceptance-tests", "add-tests", "setup-route",
         "verify-edge-cases", "create-file-foo"]
    ) == ["define-x", "test-y-2024", "acceptance-tests", "add-tests", "setup-route",
          "verify-edge-cases", "create-file-foo"]
    assert _structural_survivors(
        ["implement-leap-year-logic", "implement-health-check-endpoint",
         "build-unit-test-generator", "write-a-linter-rule", "validate-email-format",
         "add-input-validation"]
    ) == []


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
