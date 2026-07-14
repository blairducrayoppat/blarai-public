"""Tests for #819 — the requirements-clarification stage inside ``generate_plan``.

The CLARIFY stage sits BETWEEN the dispatch request and decompose: when the stage is on and
the goal is underspecified, ``generate_plan`` asks a few questions and RETURNS EARLY with them
(no tasks/spec); after the operator answers, the re-plan threads the compact requirements block
into decompose + criteria + assumptions + build-signal + both oracles + every task prompt while
``spec.goal`` stays clean. A battery/headless card dispatch NEVER clarifies. ``clarify=False``
(the default) is byte-identical to the pre-#819 plan.

Model calls are faked throughout (offline — the live 14B proof rides the next live dispatch).
"""

from __future__ import annotations

import json

from shared.fleet import acceptance as acc
from shared.fleet import clarify as clr
from shared.fleet.acceptance import (
    AcceptanceSpec,
    DecompositionOverride,
    generate_plan,
)

# The clarify prompt's unique routing marker — pinned to the real template so a rewrite that
# breaks the fakes' routing fails loudly here, not silently.
_MARKER_CLARIFY = "ask ONLY the few questions"
_MARKER_DECOMPOSE = "decomposing a software change request"
_MARKER_CRITERIA = "ACCEPTANCE CRITERIA"
_MARKER_BUILD_PLAN = "Classify what KIND of software"

_QUESTIONS_JSON = json.dumps([
    {"axis": "surface", "question": "Where will you use this — computer, browser, or phone?"},
    {"axis": "persistence", "question": "Should your information be saved between uses?"},
])
_ONE_TASK_JSON = json.dumps([{"task": "build-it", "prompt": "Build the thing."}])
_CRITERIA_JSON = json.dumps([{"text": "the project builds", "tier": "build", "check": ""}])


def _repo(tmp_path):
    proj = tmp_path / "projects"
    (proj / "myapp" / ".git").mkdir(parents=True, exist_ok=True)
    return proj, "myapp"


def _gen(calls: list, *, questions: str = _QUESTIONS_JSON):
    """A recording free-text generate_fn routing each PLAN prompt to a canned emission."""

    def gen(prompt: str) -> str:
        calls.append(prompt)
        if _MARKER_CLARIFY in prompt:
            return questions
        if _MARKER_CRITERIA in prompt:
            return _CRITERIA_JSON
        if _MARKER_BUILD_PLAN in prompt:
            return json.dumps({"surface": "desktop-gui", "candidates": [],
                               "language_hint": None, "complexity": "simple", "components": []})
        if _MARKER_DECOMPOSE in prompt:
            return _ONE_TASK_JSON
        return "[]"  # assumptions / assets

    return gen


def test_marker_matches_template():
    assert _MARKER_CLARIFY in clr._CLARIFY_TEMPLATE


# ---- the CLARIFY early-return --------------------------------------------


def test_clarify_on_underspecified_returns_questions_and_no_plan(tmp_path):
    proj, repo = _repo(tmp_path)
    calls: list = []
    plan = generate_plan("a todo app", repo, generate_fn=_gen(calls),
                         projects_dir=proj, clarify=True)
    assert plan.ok
    assert [q["axis"] for q in plan.questions] == ["surface", "persistence"]
    assert plan.tasks == [] and plan.spec.criteria == ()   # no decompose/criteria ran
    # ONLY the clarify prompt was issued (the expensive sequence never fired).
    assert all(_MARKER_CLARIFY in p for p in calls)


def test_clarify_off_is_byte_identical_no_questions(tmp_path):
    proj, repo = _repo(tmp_path)
    calls: list = []
    plan = generate_plan("a todo app", repo, generate_fn=_gen(calls),
                         projects_dir=proj, clarify=False)
    assert plan.questions == [] and len(plan.tasks) >= 1
    assert not any(_MARKER_CLARIFY in p for p in calls)  # clarify prompt never issued


def test_sufficient_goal_proceeds_to_plan(tmp_path):
    proj, repo = _repo(tmp_path)
    calls: list = []
    # Model judges the goal sufficient (returns []) -> planning proceeds, no early return.
    plan = generate_plan("a todo app", repo, generate_fn=_gen(calls, questions="[]"),
                         projects_dir=proj, clarify=True)
    assert plan.questions == [] and len(plan.tasks) >= 1
    assert any(_MARKER_CLARIFY in p for p in calls)  # the sufficiency check DID run


def test_clarify_fail_soft_proceeds_to_plan(tmp_path):
    proj, repo = _repo(tmp_path)

    def gen(prompt: str) -> str:
        if _MARKER_CLARIFY in prompt:
            raise RuntimeError("clarify model crashed")
        if _MARKER_CRITERIA in prompt:
            return _CRITERIA_JSON
        if _MARKER_DECOMPOSE in prompt:
            return _ONE_TASK_JSON
        return "[]"

    plan = generate_plan("a todo app", repo, generate_fn=gen, projects_dir=proj, clarify=True)
    assert plan.questions == [] and len(plan.tasks) >= 1  # degraded to direct decompose


# ---- requirements threading (the re-plan) --------------------------------


def test_requirements_thread_into_prompts_and_tasks_and_spec_goal_stays_clean(tmp_path):
    proj, repo = _repo(tmp_path)
    calls: list = []
    req = clr.compose_requirements_block([
        {"question": "q", "answer": "on my computer", "assumed": False},
        {"question": "q2", "answer": "save my todos", "assumed": True},
    ])
    plan = generate_plan("a todo app", repo, generate_fn=_gen(calls),
                         projects_dir=proj, clarify=True, requirements=req)
    # clarify is SUPPRESSED on a re-plan (requirements present).
    assert plan.questions == [] and not any(_MARKER_CLARIFY in p for p in calls)
    # the requirements seeded the sub-generation prompts...
    assert any("on my computer" in p for p in calls)
    # ...and ride EVERY compiled task context, verbatim + delimited...
    assert plan.tasks and all(
        "Clarified requirements" in t["prompt"] and "on my computer" in t["prompt"]
        for t in plan.tasks
    )
    # ...while spec.goal stays the CLEAN original (no block in the preview header).
    assert plan.spec.goal == "a todo app"


def test_battery_override_skips_clarify(tmp_path):
    proj, repo = _repo(tmp_path)
    calls: list = []
    override = DecompositionOverride(tasks=[{"repo": repo, "task": "t1", "prompt": "do"}])
    plan = generate_plan("a todo app", repo, generate_fn=_gen(calls), projects_dir=proj,
                         clarify=True, decomposition_override=override)
    # A carded (battery/headless) dispatch is never clarified — the card IS the spec.
    assert plan.questions == [] and len(plan.tasks) >= 1
    assert not any(_MARKER_CLARIFY in p for p in calls)


# ---- grammar-first for the clarify emission -------------------------------


def test_clarify_grammar_first(tmp_path):
    proj, repo = _repo(tmp_path)
    free_calls: list = []

    def structured(prompt: str, schema_text: str) -> str:
        if _MARKER_CLARIFY in prompt:
            schema = json.loads(schema_text)
            assert set(schema["items"]["properties"]["axis"]["enum"]) == set(clr.CLARIFY_AXES)
            return _QUESTIONS_JSON
        return ""  # force free-text for the rest (irrelevant — we early-return)

    plan = generate_plan("a todo app", repo, generate_fn=_gen(free_calls),
                         projects_dir=proj, clarify=True, structured_generate_fn=structured)
    assert [q["axis"] for q in plan.questions] == ["surface", "persistence"]
    # the grammar served the clarify emission — the free-text clarify prompt never fired.
    assert not any(_MARKER_CLARIFY in p for p in free_calls)


# ---- the spec.clarifications record (additive key) ------------------------


def test_spec_clarifications_roundtrip_and_render():
    spec = AcceptanceSpec(
        goal="a todo app",
        clarifications=(
            {"question": "where?", "answer": "on my computer", "assumed": False},
            {"question": "look?", "answer": "a clean simple look", "assumed": True},
        ),
    )
    back = AcceptanceSpec.from_dict(spec.to_dict())
    assert back.clarifications == spec.clarifications
    preview = acc.render_criteria_preview(back, ecosystem="python")
    assert "what you told me" in preview.lower()          # the answered one
    assert "on my computer" in preview
    assert "asked me to decide" in preview.lower()        # the assumed one
    assert "a clean simple look" in preview


def test_spec_clarifications_absent_key_is_empty():
    # An older payload with no key reconstructs unchanged (backward-compatible).
    assert AcceptanceSpec.from_dict({"goal": "g"}).clarifications == ()


def test_coerce_clarifications_fail_closed():
    assert acc._coerce_clarifications("not a list") == ()
    # blank / vacuous answers dropped; a real one survives with assumed coerced to bool.
    out = acc._coerce_clarifications([
        {"question": "q", "answer": "", "assumed": True},
        "junk",
        {"question": "q2", "answer": "on my computer", "assumed": 1},
    ])
    assert out == ({"question": "q2", "answer": "on my computer", "assumed": True},)
