"""Gateway-side locks for #1069 S3-G — criteria revision through the real coordinator.

The shared ruler is locked in ``shared/tests/test_criteria_revise.py``. THIS file drives
the REAL DispatchCoordinator revise flow with injected fakes and locks the seams:

* criteria/scope feedback that task-revision cannot serve runs the criteria path and the
  card actually changes — delta leads, judged criteria edited, revision budget consumed;
* what CANNOT change, by construction: the compiled task prompts and the riding exam are
  byte-identical through a criteria revision, the deterministic floors survive (delivery
  floor auto-kept by the machine wall AND re-injected — two independent locks), and the
  coverage marker carries verbatim;
* the dormant default's operator-visible reply is byte-identical to pre-G: with the stage
  off the AO refuses Fail-Closed and the coordinator renders the honest #1055 message.
"""

from __future__ import annotations

import json

import pytest

from services.ui_gateway.src.dispatch_coordinator import (
    DispatchCommand,
    DispatchCoordinator,
)
from shared.fleet import dispatch as fleet
from shared.fleet.acceptance import (
    DELIVERY_FLOOR_ID,
    OPERATOR_ASSETS_FLOOR_ID,
    OPERATOR_ASSETS_VISUAL_ID,
    AcceptanceCriterion,
    AcceptanceSpec,
    PlanResult,
    TIER_HUMAN,
    _ensure_operator_assets_floor,
    _ensure_operator_assets_visual,
)
from shared.fleet.revise import CRITERIA_REVISE_SENTINEL, REVISE_SENTINEL

# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


def _cfg(tmp_path):
    return fleet.FleetDispatchConfig(
        scripts_dir=tmp_path / "scripts",
        queue_path=tmp_path / "q.json",
        runs_dir=tmp_path / "runs",
        projects_dir=tmp_path / "projects",
    )


def _web_spec():
    """A web spec whose criteria span the wall: one machine row (the delivery floor
    itself), one visual row, one human row."""
    return AcceptanceSpec(
        "a habit page", (
            AcceptanceCriterion(DELIVERY_FLOOR_ID,
                                "the served page loads and shows the habit list",
                                "smoke", "serve and assert"),
            AcceptanceCriterion("c2", "big friendly buttons", "visual", ""),
            AcceptanceCriterion("c3", "feels quick", "human", ""),
        ),
        build_plan={"surface": "web", "candidates": [], "language_hint": None,
                    "complexity": "simple", "components": []},
    )


def _tasks(repo_path: str) -> list[dict]:
    # Carries the plan-time VLM stamp (review F1): the design loop critiques against
    # visual_criteria_json, so the fixture must carry it or the re-thread pin is vacuous.
    return [{"repo": repo_path, "task": "build-page", "prompt": "build the page",
             "visual_criteria_json": json.dumps(["big friendly buttons"])}]


class _PlanFn:
    """Scripted AO: a normal goal plans; a task-revise sentinel returns NO ops (the #1055
    shape); a criteria-revise sentinel returns the scripted response."""

    def __init__(self, tmp_path, criteria_response):
        self.tmp_path = tmp_path
        self.criteria_response = criteria_response
        self.criteria_calls: list[str] = []

    async def __call__(self, repo, goal):
        if CRITERIA_REVISE_SENTINEL in goal:
            self.criteria_calls.append(goal)
            return self.criteria_response
        if REVISE_SENTINEL in goal:
            return PlanResult(ok=True, revision=[], message="no ops")
        repo_path = str(self.tmp_path / "projects" / repo)
        return PlanResult(ok=True, tasks=_tasks(repo_path), spec=_web_spec(),
                          message="planned")


class _EagerTaskPlanFn(_PlanFn):
    """The live 2026-07-29 ceremony shape: the task-revise model INVENTS usable task
    ops for criteria-flavoured feedback (witnessed deleting a real build task at the
    S3 go-live demo). Criteria-first routing exists so these ops never run for
    criteria feedback; this fake makes the task path a live wire instead of a no-op."""

    def __init__(self, tmp_path, criteria_response):
        super().__init__(tmp_path, criteria_response)
        self.task_revise_calls: list[str] = []

    async def __call__(self, repo, goal):
        if CRITERIA_REVISE_SENTINEL in goal:
            self.criteria_calls.append(goal)
            return self.criteria_response
        if REVISE_SENTINEL in goal:
            self.task_revise_calls.append(goal)
            return PlanResult(ok=True, revision=[
                {"op": "revise", "ref": 1, "task": "build-page-bigger",
                 "prompt": "build the page with bigger tiles"},
            ], message="ops")
        repo_path = str(self.tmp_path / "projects" / repo)
        return PlanResult(ok=True, tasks=_tasks(repo_path), spec=_web_spec(),
                          message="planned")


def _coord(tmp_path, plan_fn):
    return DispatchCoordinator(
        config=_cfg(tmp_path), enabled=True,
        plan_fn=plan_fn, execute_fn=None, mint_run_id=lambda: "RID-DET",
    )


async def _plan(coord):
    return await coord.handle_command(
        "s", DispatchCommand(kind="run", repo="habits", goal="a habit page"))


_CRITERIA_FEEDBACK = "change the acceptance criteria: drop the feels-quick one and add checking it looks tidy on a phone"

_OPS_RESPONSE = PlanResult(ok=True, criteria_revision=[
    {"op": "keep", "ref": 1},
    {"op": "rescope", "ref": 2, "text": "buttons usable one-handed"},
    {"op": "add", "text": "looks tidy on a phone"},
], message="ops")

_OFF_RESPONSE = PlanResult(ok=False, message="Criteria revision is turned off (Fail-Closed).")


# ---------------------------------------------------------------------------
# The capability — judged layer edits land, budget consumed, exam untouched
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_criteria_feedback_revises_the_judged_layer(tmp_path):
    plan_fn = _PlanFn(tmp_path, _OPS_RESPONSE)
    coord = _coord(tmp_path, plan_fn)
    await _plan(coord)
    before = coord.pending_for("s")
    reply = await coord.handle_command(
        "s", DispatchCommand(kind="revise", feedback=_CRITERIA_FEEDBACK))
    assert "I updated what the build will be judged on" in reply
    assert "looks tidy on a phone" in reply
    assert "feels quick" in reply and "Removed:" in reply
    pending = coord.pending_for("s")
    assert pending is not None
    texts = [c.text for c in pending.spec.criteria]
    assert "looks tidy on a phone" in texts
    assert "buttons usable one-handed" in texts
    assert "feels quick" not in texts
    added = next(c for c in pending.spec.criteria if c.text == "looks tidy on a phone")
    assert added.tier == TIER_HUMAN
    # The budget is SHARED with task revisions and was consumed.
    assert pending.revision_count == before.revision_count + 1
    # Review F1: the VLM stamp is RE-THREADED from the revised spec — the design loop
    # must critique against the criteria the operator now holds...
    assert json.loads(pending.tasks[0]["visual_criteria_json"]) == [
        "buttons usable one-handed"
    ], "a rescoped visual criterion must reach the build loop's stamp"
    # ...while everything the CODER consumes stays frozen: prompt, slug, repo untouched.
    for key in ("repo", "task", "prompt"):
        assert pending.tasks[0][key] == before.tasks[0][key]
    # The feedback is recorded on the spec like any revision's (card + record).
    assert any(c.get("answer") == _CRITERIA_FEEDBACK
               for c in pending.spec.clarifications)


@pytest.mark.asyncio
async def test_the_delivery_floor_survives_and_the_wall_reports_protected(tmp_path):
    """An emission that tries to rescope the floor and drop everything else: the floor
    (machine tier) must survive verbatim — the wall discards the rescope and the omission
    sweep auto-keeps it — and the card says so."""
    plan_fn = _PlanFn(tmp_path, PlanResult(ok=True, criteria_revision=[
        {"op": "rescope", "ref": 1, "text": "loads eventually"},
        {"op": "keep", "ref": 2},
    ], message="ops"))
    coord = _coord(tmp_path, plan_fn)
    await _plan(coord)
    reply = await coord.handle_command(
        "s", DispatchCommand(kind="revise", feedback=_CRITERIA_FEEDBACK))
    assert "Protected" in reply
    pending = coord.pending_for("s")
    floor = next(c for c in pending.spec.criteria if c.id == DELIVERY_FLOOR_ID)
    assert floor.text == "the served page loads and shows the habit list"
    assert floor.check == "serve and assert", "the floor's check must survive the wall"


@pytest.mark.asyncio
async def test_asset_floor_survives_revision_and_the_visual_stays_droppable(tmp_path):
    """#1165 M5 through the REAL coordinator revise flow: an emission omitting both
    asset checks keeps the MACHINE wiring floor (wall + re-injection — the fourth
    re-injection line in _try_criteria_revision is what this locks) while the
    operator-tier VISUAL criterion drops (the S3-G posture); the manifest itself
    survives the revision, so the re-rendered card still acknowledges the files."""
    manifest = {"files": [{"name": "logo.svg", "class": "image", "size": 10}],
                "skipped_names": 0, "skipped_other": 0}

    def _asset_spec():
        base = AcceptanceSpec(
            "a page",
            (AcceptanceCriterion("c1", "the served page loads and shows the habit list",
                                 "smoke", "serve and assert"),
             AcceptanceCriterion("c2", "feels quick", "human", "")),
            build_plan={"surface": "web", "candidates": [], "language_hint": None,
                        "complexity": "simple", "components": []},
            operator_assets=manifest,
        )
        return _ensure_operator_assets_visual(_ensure_operator_assets_floor(base))

    class _AssetPlanFn(_PlanFn):
        async def __call__(self, repo, goal):
            if CRITERIA_REVISE_SENTINEL in goal:
                self.criteria_calls.append(goal)
                return self.criteria_response
            if REVISE_SENTINEL in goal:
                return PlanResult(ok=True, revision=[], message="no ops")
            repo_path = str(self.tmp_path / "projects" / repo)
            return PlanResult(ok=True, tasks=_tasks(repo_path), spec=_asset_spec(),
                              message="planned")

    plan_fn = _AssetPlanFn(tmp_path, PlanResult(ok=True, criteria_revision=[
        {"op": "keep", "ref": 1},   # omits c2, the asset floor AND the visual row
    ], message="ops"))
    coord = _coord(tmp_path, plan_fn)
    await _plan(coord)
    reply = await coord.handle_command(
        "s", DispatchCommand(kind="revise", feedback=_CRITERIA_FEEDBACK))
    pending = coord.pending_for("s")
    ids = {c.id for c in pending.spec.criteria}
    assert OPERATOR_ASSETS_FLOOR_ID in ids, (
        "the asset wiring floor must survive a revision (wall + re-injection)")
    assert OPERATOR_ASSETS_VISUAL_ID not in ids, (
        "the operator-tier visual criterion must stay droppable")
    assert pending.spec.operator_assets == manifest
    assert 'Working from your assets folder: "logo.svg"' in reply


@pytest.mark.asyncio
async def test_stage_off_renders_the_pre_G_honest_message(tmp_path):
    """The dormant-default bar: with the AO refusing Fail-Closed, the operator-visible
    reply is the slice-A honest message — criteria unchanged, budget NOT consumed."""
    plan_fn = _PlanFn(tmp_path, _OFF_RESPONSE)
    coord = _coord(tmp_path, plan_fn)
    await _plan(coord)
    before = coord.pending_for("s")
    reply = await coord.handle_command(
        "s", DispatchCommand(kind="revise", feedback=_CRITERIA_FEEDBACK))
    assert "couldn't change that through revise" in reply
    assert "reject and start a new dispatch" in reply
    pending = coord.pending_for("s")
    assert [c.to_dict() for c in pending.spec.criteria] == \
           [c.to_dict() for c in before.spec.criteria]
    assert pending.revision_count == before.revision_count
    assert plan_fn.criteria_calls, "harness self-check: the AO refusal path was exercised"


@pytest.mark.asyncio
async def test_non_criteria_feedback_never_runs_the_criteria_path(tmp_path):
    """Ordinary task feedback that no-ops falls to the generic honest message without a
    criteria round-trip — the detector gates the new path, so the quick shape is
    byte-identical to pre-G."""
    plan_fn = _PlanFn(tmp_path, _OPS_RESPONSE)
    coord = _coord(tmp_path, plan_fn)
    await _plan(coord)
    reply = await coord.handle_command(
        "s", DispatchCommand(kind="revise", feedback="make it faster somehow please"))
    assert "couldn't turn that into a change to the plan" in reply
    assert plan_fn.criteria_calls == []


@pytest.mark.asyncio
async def test_F2_wall_only_feedback_gets_the_protected_report(tmp_path):
    """Review F2: keeps plus a machine-tier rescope only — changed is False but the wall
    fired. The reply must be the PROTECTED report (the stage is provably on), never the
    pre-G "criteria can't be edited" message, and the budget stays unconsumed."""
    plan_fn = _PlanFn(tmp_path, PlanResult(ok=True, criteria_revision=[
        {"op": "rescope", "ref": 1, "text": "loads eventually"},
        {"op": "keep", "ref": 2},
        {"op": "keep", "ref": 3},
    ], message="ops"))
    coord = _coord(tmp_path, plan_fn)
    await _plan(coord)
    before = coord.pending_for("s")
    reply = await coord.handle_command(
        "s", DispatchCommand(kind="revise", feedback=_CRITERIA_FEEDBACK))
    assert "Protected" in reply
    assert "couldn't change that through revise" not in reply, \
        "the pre-G message is FALSE once the stage is live"
    pending = coord.pending_for("s")
    assert pending.revision_count == before.revision_count, \
        "a wall-only no-op must not consume the budget"
    assert [c.to_dict() for c in pending.spec.criteria] == \
           [c.to_dict() for c in before.spec.criteria]


@pytest.mark.asyncio
async def test_criteria_feedback_beats_an_eager_task_reviser(tmp_path):
    """The live-caught routing defect's lock: criteria feedback must run the criteria
    path FIRST even when the task model would happily return usable task ops — the
    task model is never consulted, and the task list survives byte-identically."""
    plan_fn = _EagerTaskPlanFn(tmp_path, _OPS_RESPONSE)
    coord = _coord(tmp_path, plan_fn)
    await _plan(coord)
    before = coord.pending_for("s")
    reply = await coord.handle_command(
        "s", DispatchCommand(kind="revise", feedback=_CRITERIA_FEEDBACK))
    assert "I updated what the build will be judged on" in reply
    assert plan_fn.task_revise_calls == [], \
        "criteria feedback reached the task-revise model — the live defect regressed"
    assert plan_fn.criteria_calls, "the criteria path never ran"
    pending = coord.pending_for("s")
    texts = [c.text for c in pending.spec.criteria]
    assert "looks tidy on a phone" in texts
    assert [t["task"] for t in pending.tasks] == [t["task"] for t in before.tasks], \
        "a criteria revision must never add/drop/rename tasks"
    for key in ("repo", "task", "prompt"):
        assert pending.tasks[0][key] == before.tasks[0][key]


@pytest.mark.asyncio
async def test_eager_task_ops_still_land_for_task_feedback(tmp_path):
    """The other half of the routing: detector-negative feedback keeps the task path,
    ops and all — criteria-first must not have stolen ordinary task revision."""
    plan_fn = _EagerTaskPlanFn(tmp_path, _OPS_RESPONSE)
    coord = _coord(tmp_path, plan_fn)
    await _plan(coord)
    reply = await coord.handle_command(
        "s", DispatchCommand(kind="revise",
                             feedback="build the page differently with bigger tiles"))
    assert plan_fn.criteria_calls == [], \
        "task feedback must not pay a criteria round-trip"
    assert plan_fn.task_revise_calls, "the task path never ran"
    assert "I revised the plan from your feedback" in reply
    pending = coord.pending_for("s")
    assert any(t.get("task") == "build-page-bigger" for t in pending.tasks), \
        "the task op the model returned must actually land"


@pytest.mark.asyncio
async def test_budget_cap_refuses_before_any_criteria_call(tmp_path):
    plan_fn = _PlanFn(tmp_path, _OPS_RESPONSE)
    coord = _coord(tmp_path, plan_fn)
    await _plan(coord)
    for _ in range(3):
        await coord.handle_command(
            "s", DispatchCommand(kind="revise", feedback=_CRITERIA_FEEDBACK))
    reply = await coord.handle_command(
        "s", DispatchCommand(kind="revise", feedback=_CRITERIA_FEEDBACK))
    assert "refined this plan 3 times" in reply
    assert len(plan_fn.criteria_calls) == 3, "the cap must hold across criteria revisions"
