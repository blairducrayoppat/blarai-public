"""Gateway-side locks for #1069 S3-F — the coverage gate at the approve door.

The plan-time half (the pin, the bounded re-authoring, the marker) is locked in
``shared/tests/test_coverage_gate.py``. THIS file locks what the gateway does with the
marker, driven through the REAL DispatchCoordinator with injected fakes:

* a blocked plan renders blocked and ``/dispatch approve`` is REFUSED — nothing fires, no
  acceptance record is written, and the plan stays parked (deny-by-default at the last door);
* a revision is a real unblock path: the SAME deterministic #989 measurement re-runs over the
  revised plan, so a revision that drops/repairs the uncovered work clears the block and one
  that does not keeps it (a block that could never clear would be a dead end wearing an open
  door);
* the marker survives the #1116 parked-state round-trip (a blocked plan is still blocked
  after a restart) and rides the Inc-4 clarifying hold.

The revise flow runs the real ``shared.fleet.revise`` op machinery — never a hand-mutated
task list — so these locks break if the seam does.
"""

from __future__ import annotations

import pytest

from services.ui_gateway.src.dispatch_coordinator import (
    DispatchCommand,
    DispatchCoordinator,
    PendingClarification,
    PendingDispatch,
    _clarifying_from_payload,
    _clarifying_to_payload,
    _pending_from_payload,
    _pending_to_payload,
)
from shared.fleet import dispatch as fleet
from shared.fleet.acceptance import (
    ACCEPTANCE_TASK_SLUG,
    JOB_ORACLE_CODE_KEY,
    JOB_ORACLE_PATH_KEY,
    AcceptanceCriterion,
    AcceptanceSpec,
    PlanResult,
    _coverage_blocked_message,
)
from shared.fleet.revise import REVISE_SENTINEL

# ---------------------------------------------------------------------------
# Harness — the test_dispatch_coordinator idiom, with a multi-task blocked plan
# ---------------------------------------------------------------------------


def _cfg(tmp_path):
    return fleet.FleetDispatchConfig(
        scripts_dir=tmp_path / "scripts",
        queue_path=tmp_path / "q.json",
        runs_dir=tmp_path / "runs",
        projects_dir=tmp_path / "projects",
    )


def _spec():
    return AcceptanceSpec("a flashcards quiz", (
        AcceptanceCriterion("c1", "it scores a correct answer", "behavior", "run it"),
    ))


#: Imports ONLY app.quiz_engine — with tasks engine+cli below, task "cli" is uncovered.
_GAPPED_ORACLE_CODE = (
    "from app.quiz_engine import run_quiz\n"
    "\n"
    "def test_scores():\n"
    "    assert run_quiz([{'question': 'q', 'answer': 'a'}], lambda q: 'a')"
    " == {'asked': 1, 'correct': 1}\n"
)

_BLOCKED_MARKER = _coverage_blocked_message(
    "CONTRACT-COVERAGE WARNING: build task(s) cli own NO module the job-acceptance "
    "oracle imports — 2 build task(s) against 1 oracle import target(s)."
)


def _blocked_tasks(repo_path: str) -> list[dict]:
    return [
        {"repo": repo_path, "task": "engine", "prompt": "build the quiz engine",
         "depends_on": [],
         "contract": {"creates": ["app/quiz_engine.py"],
                      "exports": ["run_quiz(cards, answer_fn)"], "notes": ""}},
        {"repo": repo_path, "task": "cli", "prompt": "build the cli",
         "depends_on": ["engine"],
         "contract": {"creates": ["app/cli.py"], "exports": ["main()"], "notes": ""}},
        {"repo": repo_path, "task": ACCEPTANCE_TASK_SLUG, "prompt": "run the exam",
         JOB_ORACLE_CODE_KEY: _GAPPED_ORACLE_CODE,
         JOB_ORACLE_PATH_KEY: "tests/test_job_acceptance.py"},
    ]


def _plan_fn_factory(tmp_path, *, revision_ops):
    """First (normal) call → the BLOCKED multi-task plan. A revise-sentinel call → the
    scripted edit ops, exactly as the AO would return them."""

    async def plan_fn(repo, goal):
        if REVISE_SENTINEL in goal:
            return PlanResult(ok=True, revision=list(revision_ops), message="ops")
        repo_path = str(tmp_path / "projects" / repo)
        return PlanResult(
            ok=True,
            tasks=_blocked_tasks(repo_path),
            spec=_spec(),
            message="planned (blocked)",
            coverage_blocked=_BLOCKED_MARKER,
        )

    return plan_fn


def _fake_execute(*, calls):
    async def execute_fn(session_id, run_id, repo, tasks, spec):
        calls.append({"session": session_id, "run_id": run_id, "tasks": tasks})
        return fleet.DispatchResult(ok=True, run_id=run_id, message="dispatching")

    return execute_fn


def _coord(tmp_path, *, plan_fn, execute_fn=None):
    return DispatchCoordinator(
        config=_cfg(tmp_path), enabled=True,
        plan_fn=plan_fn, execute_fn=execute_fn, mint_run_id=lambda: "RID-DET",
    )


async def _plan_blocked(coord):
    return await coord.handle_command(
        "s", DispatchCommand(kind="run", repo="flashcards", goal="a flashcards quiz"))


# ---------------------------------------------------------------------------
# The approve door
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blocked_plan_renders_blocked_and_stores_the_marker(tmp_path):
    coord = _coord(tmp_path, plan_fn=_plan_fn_factory(tmp_path, revision_ops=[]))
    reply = await _plan_blocked(coord)
    assert "APPROVAL IS BLOCKED FOR NOW" in reply
    assert "Reply `/dispatch approve`" not in reply, \
        "a blocked card must not offer the verb the coordinator will refuse"
    pending = coord.pending_for("s")
    assert pending is not None and pending.coverage_blocked == _BLOCKED_MARKER


@pytest.mark.asyncio
async def test_approve_is_refused_while_blocked_and_nothing_fires(tmp_path):
    exec_calls: list = []
    coord = _coord(tmp_path, plan_fn=_plan_fn_factory(tmp_path, revision_ops=[]),
                   execute_fn=_fake_execute(calls=exec_calls))
    await _plan_blocked(coord)
    reply = await coord.handle_command("s", DispatchCommand(kind="approve"))
    assert "cli" in reply, "the refusal must NAME the gap, not just say no"
    assert exec_calls == [], "a blocked approve fired work"
    # The acceptance record write sits AFTER the refusal — nothing may persist either.
    runs_dir = tmp_path / "runs"
    assert (not runs_dir.exists()) or not any(runs_dir.iterdir()), \
        "a blocked approve wrote an acceptance record"
    # The plan is KEPT (refused, not discarded): the operator revises or rejects it.
    assert coord.pending_for("s") is not None


@pytest.mark.asyncio
async def test_reject_still_clears_a_blocked_plan(tmp_path):
    """Blocked never means stuck: reject stays open and fully clears the slot."""
    coord = _coord(tmp_path, plan_fn=_plan_fn_factory(tmp_path, revision_ops=[]))
    await _plan_blocked(coord)
    reply = await coord.handle_command("s", DispatchCommand(kind="reject"))
    assert "Cancelled" in reply
    assert coord.pending_for("s") is None


# ---------------------------------------------------------------------------
# Revise as the unblock path — the marker is RE-EVALUATED, both directions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_revision_that_drops_the_uncovered_task_unblocks(tmp_path):
    """Dropping 'cli' (a keep-only-engine revision) leaves an exam that covers every
    remaining task — the re-evaluation must CLEAR the marker, say so, and re-open approve."""
    exec_calls: list = []
    coord = _coord(
        tmp_path,
        plan_fn=_plan_fn_factory(tmp_path, revision_ops=[{"op": "keep", "ref": 1}]),
        execute_fn=_fake_execute(calls=exec_calls),
    )
    await _plan_blocked(coord)
    reply = await coord.handle_command(
        "s", DispatchCommand(kind="revise", feedback="drop the cli, engine only"))
    assert "closed the coverage gap" in reply
    assert "APPROVAL IS BLOCKED" not in reply
    assert "Reply `/dispatch approve`" in reply, "an unblocked card must offer approve again"
    pending = coord.pending_for("s")
    assert pending is not None and pending.coverage_blocked == ""
    # ...and approve now actually fires.
    await coord.handle_command("s", DispatchCommand(kind="approve"))
    assert len(exec_calls) == 1


@pytest.mark.asyncio
async def test_a_revision_that_keeps_the_gap_stays_blocked(tmp_path):
    """A changed-but-still-gapped revision (cli re-scoped into a contract-less task) must
    KEEP the block, with the marker recomputed over the plan as revised."""
    exec_calls: list = []
    coord = _coord(
        tmp_path,
        plan_fn=_plan_fn_factory(
            tmp_path,
            revision_ops=[{"op": "keep", "ref": 1},
                          {"op": "revise", "ref": 2, "task": "cli-v2",
                           "prompt": "a better cli"}],
        ),
        execute_fn=_fake_execute(calls=exec_calls),
    )
    await _plan_blocked(coord)
    reply = await coord.handle_command(
        "s", DispatchCommand(kind="revise", feedback="make the cli better"))
    assert "APPROVAL IS BLOCKED FOR NOW" in reply
    pending = coord.pending_for("s")
    assert pending is not None and pending.coverage_blocked != ""
    assert "cli-v2" in pending.coverage_blocked, \
        "the marker must be RECOMPUTED over the revised plan, not carried stale"
    refusal = await coord.handle_command("s", DispatchCommand(kind="approve"))
    assert "cli-v2" in refusal and exec_calls == []


@pytest.mark.asyncio
async def test_an_unblocked_plan_never_pays_the_re_evaluation(tmp_path):
    """Quick-path invariance: a plan that arrived WITHOUT a marker revises exactly as
    before — no recompute, no marker appearing after the fact."""
    async def plan_fn(repo, goal):
        if REVISE_SENTINEL in goal:
            return PlanResult(ok=True, revision=[{"op": "keep", "ref": 1}], message="ops")
        repo_path = str(tmp_path / "projects" / repo)
        return PlanResult(ok=True, tasks=_blocked_tasks(repo_path), spec=_spec(),
                          message="planned")  # same gapped tasks, NO marker (gate off)

    coord = _coord(tmp_path, plan_fn=plan_fn)
    await _plan_blocked(coord)
    reply = await coord.handle_command(
        "s", DispatchCommand(kind="revise", feedback="drop the cli"))
    assert "APPROVAL IS BLOCKED" not in reply
    pending = coord.pending_for("s")
    assert pending is not None and pending.coverage_blocked == ""


# ---------------------------------------------------------------------------
# Durability + the clarifying hold — the marker is state, not a banner
# ---------------------------------------------------------------------------


def test_marker_survives_the_pending_payload_roundtrip():
    p = PendingDispatch(run_id="R", repo="r", goal="g", tasks=[], spec=_spec(),
                        coverage_blocked=_BLOCKED_MARKER)
    assert _pending_from_payload(_pending_to_payload(p)).coverage_blocked == _BLOCKED_MARKER


def test_marker_survives_the_clarifying_payload_roundtrip():
    p = PendingClarification(run_id="R", repo="r", goal="g", tasks=[], spec=_spec(),
                             question={"question": "q", "options": []},
                             coverage_blocked=_BLOCKED_MARKER)
    restored = _clarifying_from_payload(_clarifying_to_payload(p))
    assert restored.coverage_blocked == _BLOCKED_MARKER


def test_pre_s3f_payloads_restore_unblocked():
    """A row parked before this slice has no key — it must restore approvable, never raise."""
    p = _pending_to_payload(PendingDispatch(run_id="R", repo="r", goal="g", tasks=[],
                                            spec=_spec()))
    p.pop("coverage_blocked")
    assert _pending_from_payload(p).coverage_blocked == ""
    c = _clarifying_to_payload(PendingClarification(
        run_id="R", repo="r", goal="g", tasks=[], spec=_spec(),
        question={"question": "q", "options": []}))
    c.pop("coverage_blocked")
    assert _clarifying_from_payload(c).coverage_blocked == ""


@pytest.mark.asyncio
async def test_F2_unmeasurable_re_evaluation_keeps_the_original_marker(tmp_path):
    """Review F1/F2, gateway side: a revision whose surviving exam measures
    NOT-COMPUTABLE (no first-party imports) must keep the ORIGINAL marker — never clear
    it, never print the closed-the-gap affirmative."""
    def importless_tasks(repo_path):
        tasks = _blocked_tasks(repo_path)
        tasks[-1][JOB_ORACLE_CODE_KEY] = "def test_scores():\n    assert True\n"
        return tasks

    async def plan_fn(repo, goal):
        from shared.fleet.revise import REVISE_SENTINEL as _RS
        if _RS in goal:
            return PlanResult(ok=True, revision=[{"op": "keep", "ref": 1}],
                              message="ops")
        repo_path = str(tmp_path / "projects" / repo)
        return PlanResult(ok=True, tasks=importless_tasks(repo_path), spec=_spec(),
                          message="planned (blocked)",
                          coverage_blocked=_BLOCKED_MARKER)

    coord = _coord(tmp_path, plan_fn=plan_fn)
    await _plan_blocked(coord)
    reply = await coord.handle_command(
        "s", DispatchCommand(kind="revise", feedback="drop the cli"))
    assert "closed the coverage gap" not in reply
    assert "APPROVAL IS BLOCKED FOR NOW" in reply
    assert coord.pending_for("s").coverage_blocked == _BLOCKED_MARKER, \
        "an unmeasurable re-evaluation must keep the ORIGINAL marker verbatim"


@pytest.mark.asyncio
async def test_F2_re_evaluation_crash_keeps_the_block(tmp_path, monkeypatch):
    """A crash inside the gateway-side measurement is NOT an unblock — fail-closed."""
    from shared.fleet import acceptance as acc_mod

    coord = _coord(
        tmp_path,
        plan_fn=_plan_fn_factory(tmp_path, revision_ops=[{"op": "keep", "ref": 1}]))
    await _plan_blocked(coord)

    def boom(*a, **k):
        raise RuntimeError("measurement down")

    monkeypatch.setattr(acc_mod, "contract_coverage", boom)
    reply = await coord.handle_command(
        "s", DispatchCommand(kind="revise", feedback="drop the cli"))
    assert "closed the coverage gap" not in reply
    assert coord.pending_for("s").coverage_blocked == _BLOCKED_MARKER


@pytest.mark.asyncio
async def test_F3_blocked_at_the_cap_every_surface_is_honest(tmp_path):
    """Review F3: three gap-preserving revisions reach the cap — the card supersedes the
    baked revise offer, and the cap refusal routes to reject, never to approve."""
    coord = _coord(
        tmp_path,
        plan_fn=_plan_fn_factory(
            tmp_path,
            revision_ops=[{"op": "keep", "ref": 1},
                          {"op": "revise", "ref": 2, "task": "cli-v2",
                           "prompt": "a better cli"}]),
    )
    await _plan_blocked(coord)
    last_card = ""
    for _ in range(3):
        last_card = await coord.handle_command(
            "s", DispatchCommand(kind="revise", feedback="make the cli better"))
    assert coord.pending_for("s").revision_count == 3
    assert "Refinements are used up" in last_card, \
        "the at-cap blocked card must supersede the baked revise offer"
    refusal = await coord.handle_command(
        "s", DispatchCommand(kind="revise", feedback="try again"))
    assert "reject" in refusal
    assert "approve" not in refusal, \
        "a blocked plan at the cap must never be told to approve"


@pytest.mark.asyncio
async def test_F7_blocked_marker_survives_a_restart_through_the_real_store(tmp_path):
    """Review F7: park a BLOCKED plan through the real born-encrypted store, boot a NEW
    coordinator over the same store, and approve must still be refused."""
    from services.ui_gateway.src.dispatch_state_store import (
        build_dispatch_state_store,
    )

    store = build_dispatch_state_store(str(tmp_path / "dispatch_state.db"),
                                       dev_mode=True)
    coord = DispatchCoordinator(
        config=_cfg(tmp_path), enabled=True,
        plan_fn=_plan_fn_factory(tmp_path, revision_ops=[]), execute_fn=None,
        mint_run_id=lambda: "RID-DET", state_store=store,
    )
    await _plan_blocked(coord)

    exec_calls: list = []
    reopened = build_dispatch_state_store(str(tmp_path / "dispatch_state.db"),
                                          dev_mode=True)
    coord2 = DispatchCoordinator(
        config=_cfg(tmp_path), enabled=True,
        plan_fn=_plan_fn_factory(tmp_path, revision_ops=[]),
        execute_fn=_fake_execute(calls=exec_calls),
        mint_run_id=lambda: "RID-DET", state_store=reopened,
    )
    coord2.restore_at_boot()
    restored = coord2.pending_for("s")
    assert restored is not None and restored.coverage_blocked == _BLOCKED_MARKER, \
        "the marker must survive the encrypted park + boot restore"
    reply = await coord2.handle_command("s", DispatchCommand(kind="approve"))
    assert "cli" in reply and exec_calls == [], \
        "a restored blocked plan must still refuse approve"


@pytest.mark.asyncio
async def test_marker_rides_the_clarifying_hold_to_the_final_card(tmp_path):
    """When the Inc-4 platform question interposes, the marker must survive the hold and
    land on the eventual pending plan — a block must not evaporate because a question was
    asked in between."""
    ambiguous_spec = AcceptanceSpec(
        "a flashcards quiz",
        (AcceptanceCriterion("c1", "it scores", "behavior", "run it"),),
        build_plan={"surface": "ambiguous", "language_hint": None,
                    "complexity": "moderate", "components": [],
                    "candidates": ["desktop-gui", "web", "mobile"]},
    )

    async def plan_fn(repo, goal):
        repo_path = str(tmp_path / "projects" / repo)
        return PlanResult(ok=True, tasks=_blocked_tasks(repo_path), spec=ambiguous_spec,
                          message="planned", coverage_blocked=_BLOCKED_MARKER)

    coord = _coord(tmp_path, plan_fn=plan_fn)
    reply = await _plan_blocked(coord)
    assert "one quick question" in reply, "harness self-check: the Inc-4 question must fire"
    assert coord.pending_clarification_for("s").coverage_blocked == _BLOCKED_MARKER
    final = await coord.handle_command("s", DispatchCommand(kind="choose", choice="2"))
    assert "APPROVAL IS BLOCKED FOR NOW" in final
    pending = coord.pending_for("s")
    assert pending is not None and pending.coverage_blocked == _BLOCKED_MARKER
