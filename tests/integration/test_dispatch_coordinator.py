"""Tests for the gateway /dispatch coordinator (DispatchCoordinator) — increment 3b.

ONE flow, always confirmed: /dispatch <repo> | <goal> -> criteria preview -> WAIT;
/dispatch approve fires EXECUTE; /dispatch reject discards. The load-bearing tests are
that NO path fires work without an explicit approve, and that /dispatch status renders
the honest per-criterion report (an unrun check is never a pass). plan_fn/execute_fn are
injected fakes — the real AO-IPC wiring is the deferred go-live step.
"""

from __future__ import annotations

import pytest

from services.ui_gateway.src.dispatch_coordinator import (
    DispatchCommand,
    DispatchCoordinator,
    parse_dispatch_command,
)
from shared.fleet import dispatch as fleet
from shared.fleet.acceptance import AcceptanceCriterion, AcceptanceSpec, PlanResult


def _cfg(tmp_path):
    return fleet.FleetDispatchConfig(
        scripts_dir=tmp_path / "scripts",
        queue_path=tmp_path / "q.json",
        runs_dir=tmp_path / "runs",
        projects_dir=tmp_path / "projects",
    )


def _spec():
    return AcceptanceSpec("a calculator", (
        AcceptanceCriterion("c1", "the project builds", "build", ""),
        AcceptanceCriterion("c2", "2 + 3 shows 5", "behavior", "assert add(2,3)==5"),
        AcceptanceCriterion("c3", "big friendly buttons", "visual", ""),
    ))


def _fake_plan(spec=None, *, calls=None):
    spec = spec or _spec()

    async def plan_fn(repo, goal):
        if calls is not None:
            calls.append((repo, goal))
        return PlanResult(
            ok=True,
            tasks=[{"repo": repo, "task": "add-calc", "prompt": "build a calc"}],
            spec=spec,
            message="planned",
        )

    return plan_fn


def _fake_execute(*, calls, ok=True, message="Dispatching RID-DET — be back when it's done."):
    async def execute_fn(session_id, run_id, repo, tasks, spec):
        calls.append({"session": session_id, "run_id": run_id, "repo": repo,
                      "tasks": tasks, "spec": spec})
        return fleet.DispatchResult(ok=ok, run_id=run_id, message=message)

    return execute_fn


def _coord(tmp_path, *, enabled=True, plan_fn=None, execute_fn=None):
    return DispatchCoordinator(
        config=_cfg(tmp_path), enabled=enabled,
        plan_fn=plan_fn, execute_fn=execute_fn, mint_run_id=lambda: "RID-DET",
    )


# ---- parse ----------------------------------------------------------------


def test_parse_run_goal():
    c = parse_dispatch_command("/dispatch calc | a calculator for a kid")
    assert c and c.kind == "run" and c.repo == "calc" and c.goal == "a calculator for a kid"


def test_parse_approve_and_reject():
    assert parse_dispatch_command("/dispatch approve").kind == "approve"
    assert parse_dispatch_command("/dispatch reject").kind == "reject"


def test_parse_stop():
    assert parse_dispatch_command("/dispatch stop").kind == "stop"
    assert parse_dispatch_command("/dispatch STOP").kind == "stop"  # case-insensitive verb
    assert parse_dispatch_command("/dispatch stop now").kind == "stop"  # trailing words ignored


def test_parse_status():
    assert parse_dispatch_command("/dispatch status RID1").run_id == "RID1"
    assert parse_dispatch_command("/dispatch status").run_id == ""


def test_parse_non_dispatch_returns_none():
    assert parse_dispatch_command("hello there") is None
    assert parse_dispatch_command("/dispatchx foo") is None
    assert parse_dispatch_command("/imagine a cat") is None


# ---- dormant: disabled ----------------------------------------------------


@pytest.mark.asyncio
async def test_disabled_returns_notice_and_calls_nothing(tmp_path):
    plan_calls, exec_calls = [], []
    coord = _coord(tmp_path, enabled=False,
                   plan_fn=_fake_plan(calls=plan_calls),
                   execute_fn=_fake_execute(calls=exec_calls))
    for cmd in (DispatchCommand(kind="run", repo="r", goal="g"),
                DispatchCommand(kind="approve"),
                DispatchCommand(kind="reject"),
                DispatchCommand(kind="status")):
        reply = await coord.handle_command("s", cmd)
        assert "off" in reply.lower() or "dormant" in reply.lower()
    assert plan_calls == [] and exec_calls == []


# ---- enabled but unwired (the shipped go-live-pending posture) -------------


@pytest.mark.asyncio
async def test_enabled_but_unwired_plan_reports_wiring_notice(tmp_path):
    coord = _coord(tmp_path, plan_fn=None, execute_fn=None)
    reply = await coord.handle_command("s", DispatchCommand(kind="run", repo="r", goal="g"))
    assert "wiring" in reply.lower() and "go-live" in reply.lower()


# ---- PLAN -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_returns_criteria_and_stores_slot(tmp_path):
    calls = []
    coord = _coord(tmp_path, plan_fn=_fake_plan(calls=calls))
    reply = await coord.handle_command("s", DispatchCommand(kind="run", repo="calc", goal="a calc"))
    assert "2 + 3 shows 5" in reply and "big friendly buttons" in reply
    assert "/dispatch approve" in reply and "/dispatch reject" in reply
    assert calls == [("calc", "a calc")]
    pending = coord.pending_for("s")
    assert pending is not None and pending.run_id == "RID-DET" and pending.goal == "a calc"


@pytest.mark.asyncio
async def test_plan_preview_surfaces_task_shape(tmp_path):
    # The confirm preview must show HOW the goal will be built (the decomposition), so the
    # operator approves seeing the plan shape — not only the acceptance criteria. The fake
    # PlanResult carries a single task slug 'add-calc'; it must surface humanized.
    coord = _coord(tmp_path, plan_fn=_fake_plan())
    reply = await coord.handle_command("s", DispatchCommand(kind="run", repo="calc", goal="a calc"))
    assert "Here's how I'll build it (1 task(s)):" in reply
    assert "Add calc" in reply  # humanized slug of the PlanResult task (hyphen -> space)


@pytest.mark.asyncio
async def test_plan_fell_back_prepends_degradation_notice(tmp_path):
    # Honesty: when the 14B fell back to a minimal plan, the operator must see it —
    # not a thin build-only plan with no sign anything degraded.
    async def _fell_back_plan(repo, goal):
        return PlanResult(ok=True, tasks=[], spec=_spec(), fell_back=True, message="fell back")

    coord = _coord(tmp_path, plan_fn=_fell_back_plan)
    reply = await coord.handle_command("s", DispatchCommand(kind="run", repo="calc", goal="vague"))
    assert "couldn't fully parse" in reply.lower() and "minimal plan" in reply.lower()
    assert "2 + 3 shows 5" in reply  # the (thin) criteria still render after the notice


@pytest.mark.asyncio
async def test_plan_not_fell_back_has_no_notice(tmp_path):
    coord = _coord(tmp_path, plan_fn=_fake_plan())  # fell_back defaults False
    reply = await coord.handle_command("s", DispatchCommand(kind="run", repo="calc", goal="a calc"))
    assert "couldn't fully parse" not in reply.lower()


@pytest.mark.asyncio
async def test_plan_usage_when_missing(tmp_path):
    coord = _coord(tmp_path, plan_fn=_fake_plan())
    reply = await coord.handle_command("s", DispatchCommand(kind="run", repo="", goal=""))
    assert "Usage" in reply
    assert coord.pending_for("s") is None


@pytest.mark.asyncio
async def test_plan_already_pending_refuses(tmp_path):
    calls = []
    coord = _coord(tmp_path, plan_fn=_fake_plan(calls=calls))
    await coord.handle_command("s", DispatchCommand(kind="run", repo="calc", goal="first goal"))
    reply = await coord.handle_command("s", DispatchCommand(kind="run", repo="calc", goal="second goal"))
    assert "already waiting" in reply.lower() and "first goal" in reply
    assert len(calls) == 1  # the 14B is not re-run while one is pending


@pytest.mark.asyncio
async def test_plan_failure_message_no_slot(tmp_path):
    async def failing_plan(repo, goal):
        return PlanResult(ok=False, message="Could not dispatch — refusing: under BlarAI.")

    coord = _coord(tmp_path, plan_fn=failing_plan)
    reply = await coord.handle_command("s", DispatchCommand(kind="run", repo="BlarAI", goal="x"))
    assert "Could not dispatch" in reply
    assert coord.pending_for("s") is None


@pytest.mark.asyncio
async def test_plan_dotnet_ecosystem_caveat_up_front(tmp_path):
    cfg = _cfg(tmp_path)
    (cfg.projects_dir / "calc").mkdir(parents=True)
    (cfg.projects_dir / "calc" / "App.csproj").write_text("<Project/>", encoding="utf-8")
    coord = DispatchCoordinator(config=cfg, enabled=True, plan_fn=_fake_plan(),
                                execute_fn=None, mint_run_id=lambda: "RID-DET")
    reply = await coord.handle_command("s", DispatchCommand(kind="run", repo="calc", goal="a calc"))
    assert "C#/.NET" in reply and "does not run .NET tests" in reply


# ---- the mandatory-confirm guarantee --------------------------------------


@pytest.mark.asyncio
async def test_no_path_fires_execute_without_approve(tmp_path):
    exec_calls = []
    coord = _coord(tmp_path, plan_fn=_fake_plan(), execute_fn=_fake_execute(calls=exec_calls))
    # plan, reject, status — none may call execute_fn
    await coord.handle_command("s", DispatchCommand(kind="run", repo="calc", goal="g"))
    await coord.handle_command("s", DispatchCommand(kind="reject"))
    await coord.handle_command("s", DispatchCommand(kind="status"))
    assert exec_calls == []  # work fires ONLY via /dispatch approve


# ---- APPROVE / EXECUTE ----------------------------------------------------


@pytest.mark.asyncio
async def test_approve_fires_execute_writes_record_clears_slot(tmp_path):
    exec_calls = []
    cfg = _cfg(tmp_path)
    coord = DispatchCoordinator(config=cfg, enabled=True, plan_fn=_fake_plan(),
                                execute_fn=_fake_execute(calls=exec_calls), mint_run_id=lambda: "RID-DET")
    await coord.handle_command("s", DispatchCommand(kind="run", repo="calc", goal="a calc"))
    reply = await coord.handle_command("s", DispatchCommand(kind="approve"))
    assert "Dispatching" in reply
    assert len(exec_calls) == 1 and exec_calls[0]["run_id"] == "RID-DET"
    assert coord.pending_for("s") is None  # launched -> slot cleared
    # the acceptance record was persisted (run-id-keyed) for the later report
    rec = fleet.read_acceptance_record(cfg, "RID-DET")
    assert rec is not None and rec["spec"]["goal"] == "a calculator"


@pytest.mark.asyncio
async def test_approve_no_pending(tmp_path):
    coord = _coord(tmp_path, plan_fn=_fake_plan(), execute_fn=_fake_execute(calls=[]))
    reply = await coord.handle_command("s", DispatchCommand(kind="approve"))
    assert "Nothing to approve" in reply


@pytest.mark.asyncio
async def test_approve_execute_failure_keeps_slot(tmp_path):
    coord = _coord(tmp_path, plan_fn=_fake_plan(),
                   execute_fn=_fake_execute(calls=[], ok=False, message="Could not enqueue — refused."))
    await coord.handle_command("s", DispatchCommand(kind="run", repo="calc", goal="g"))
    reply = await coord.handle_command("s", DispatchCommand(kind="approve"))
    assert "Could not enqueue" in reply
    assert coord.pending_for("s") is not None  # kept for retry


@pytest.mark.asyncio
async def test_approve_unwired_reports_notice(tmp_path):
    coord = _coord(tmp_path, plan_fn=_fake_plan(), execute_fn=None)
    await coord.handle_command("s", DispatchCommand(kind="run", repo="calc", goal="g"))
    reply = await coord.handle_command("s", DispatchCommand(kind="approve"))
    assert "wiring" in reply.lower()


# ---- REJECT ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_reject_clears_slot(tmp_path):
    coord = _coord(tmp_path, plan_fn=_fake_plan())
    await coord.handle_command("s", DispatchCommand(kind="run", repo="calc", goal="drop me"))
    reply = await coord.handle_command("s", DispatchCommand(kind="reject"))
    assert "Cancelled" in reply and "drop me" in reply
    assert coord.pending_for("s") is None


@pytest.mark.asyncio
async def test_reject_no_pending(tmp_path):
    coord = _coord(tmp_path, plan_fn=_fake_plan())
    reply = await coord.handle_command("s", DispatchCommand(kind="reject"))
    assert "Nothing to reject" in reply


# ---- STOP (abort an APPROVED, EXECUTING run) ------------------------------


@pytest.mark.asyncio
async def test_stop_active_run_writes_cancel_sentinel(tmp_path):
    # /dispatch stop on an ACTIVE run (a non-terminal swap-state record on disk) trips the
    # driver's cancel sentinel — the SAME file build_swap_ops' cancel_requested lambda reads,
    # so writing it cleanly halts the detached driver (14B restored, partial work parked).
    from shared.fleet import swap_ops, swap_state as ss

    cfg = _cfg(tmp_path)
    # An in-flight run: the AO/driver persisted swap-state mid-CODE (non-terminal phase).
    ss.write_swap_state(
        ss.SwapState(run_id="RID-DET", session_id="s", phase=ss.PHASE_CODE,
                     tasks=[{"repo": "calc", "task": "add-calc", "prompt": "p"}]),
        path=swap_ops.swap_state_path(cfg),
    )
    sentinel = swap_ops.cancel_path(cfg)
    assert not sentinel.exists()  # baseline: no cancel before stop (mutation-resistance anchor)

    coord = DispatchCoordinator(config=cfg, enabled=True)
    reply = await coord.handle_command("s", DispatchCommand(kind="stop"))

    assert "Stopping the run" in reply and "parked" in reply
    # The load-bearing assertion: the sentinel the driver polls now EXISTS. Reverting the
    # handler's path.write_text(...) makes this fail (it stays absent) — the test binds the write.
    assert sentinel.exists()


@pytest.mark.asyncio
async def test_stop_no_active_run_reports_nothing_and_writes_no_sentinel(tmp_path):
    # No swap-state on disk -> nothing is executing. Stop must say so AND write no sentinel,
    # so a stale cancel can never leak into the NEXT dispatch's CODE loop.
    from shared.fleet import swap_ops

    cfg = _cfg(tmp_path)
    coord = DispatchCoordinator(config=cfg, enabled=True)
    reply = await coord.handle_command("s", DispatchCommand(kind="stop"))

    assert "Nothing is running to stop." == reply
    assert not swap_ops.cancel_path(cfg).exists()  # no run -> no sentinel written


@pytest.mark.asyncio
async def test_stop_terminal_phase_is_not_active(tmp_path):
    # A RECOVERED/IDLE swap-state is TERMINAL — the run already ended. Stop treats it as
    # not-running (is_in_flight gate), the same terminal set the boot reconciler uses, so a
    # leftover terminal record never causes a spurious cancel write.
    from shared.fleet import swap_ops, swap_state as ss

    cfg = _cfg(tmp_path)
    ss.write_swap_state(
        ss.SwapState(run_id="RID-DET", session_id="s", phase=ss.PHASE_RECOVERED, tasks=[]),
        path=swap_ops.swap_state_path(cfg),
    )
    coord = DispatchCoordinator(config=cfg, enabled=True)
    reply = await coord.handle_command("s", DispatchCommand(kind="stop"))
    assert "Nothing is running to stop." == reply
    assert not swap_ops.cancel_path(cfg).exists()


@pytest.mark.asyncio
async def test_stop_does_not_touch_pending_slot(tmp_path):
    # stop is for an APPROVED, EXECUTING run — NOT a pending-not-approved plan (that's reject).
    # A pending plan with no live run must NOT be silently dropped by stop, and no sentinel
    # is written (nothing is executing).
    from shared.fleet import swap_ops

    cfg = _cfg(tmp_path)
    coord = DispatchCoordinator(config=cfg, enabled=True, plan_fn=_fake_plan(),
                                execute_fn=_fake_execute(calls=[]))
    await coord.handle_command("s", DispatchCommand(kind="run", repo="calc", goal="keep me"))
    assert coord.pending_for("s") is not None

    reply = await coord.handle_command("s", DispatchCommand(kind="stop"))
    assert "Nothing is running to stop." == reply
    assert coord.pending_for("s") is not None  # the pending plan survives a stop (reject ≠ stop)
    assert not swap_ops.cancel_path(cfg).exists()


@pytest.mark.asyncio
async def test_stop_disabled_writes_no_sentinel(tmp_path):
    # Dormancy is the flag alone: with dispatch disabled, stop returns the disabled notice
    # and writes nothing (no sentinel even though a stale in-flight record exists on disk).
    from shared.fleet import swap_ops, swap_state as ss

    cfg = _cfg(tmp_path)
    ss.write_swap_state(
        ss.SwapState(run_id="RID-DET", session_id="s", phase=ss.PHASE_CODE, tasks=[]),
        path=swap_ops.swap_state_path(cfg),
    )
    coord = DispatchCoordinator(config=cfg, enabled=False)
    reply = await coord.handle_command("s", DispatchCommand(kind="stop"))
    assert "off" in reply.lower() or "dormant" in reply.lower()
    assert not swap_ops.cancel_path(cfg).exists()  # disabled -> no sentinel


# ---- STATUS (the honest report) -------------------------------------------


@pytest.mark.asyncio
async def test_status_renders_honest_acceptance_report(tmp_path):
    cfg = _cfg(tmp_path)
    # a .NET-style result: build verified, behavior test never ran (TESTS: none)
    report_file = tmp_path / "report.txt"
    report_file.write_text("VERIFY: pass\nTESTS: none\nRESULT: MERGED\n", encoding="utf-8")
    run_dir = cfg.runs_dir / "RID-DET"
    run_dir.mkdir(parents=True)
    (run_dir / "SUMMARY.txt").write_text(
        f"- add-calc: processed\n    RESULT: MERGED\n    full report: {report_file}\n",
        encoding="utf-8",
    )
    fleet.write_acceptance_record(cfg, "RID-DET", spec_dict=_spec().to_dict(),
                                  repo=str(cfg.projects_dir / "calc"))
    coord = DispatchCoordinator(config=cfg, enabled=True)
    reply = await coord.handle_command("s", DispatchCommand(kind="status", run_id="RID-DET"))
    assert "[PASS]  the project builds" in reply
    assert "NOT AUTO-CHECKED" in reply
    # the behavior criterion (test never ran) is NOT marked PASS
    behavior_line = next(ln for ln in reply.splitlines() if "2 + 3 shows 5" in ln)
    assert "PASS" not in behavior_line
    assert "big friendly buttons" in reply  # eyeball checklist


@pytest.mark.asyncio
async def test_status_falls_back_to_summary_without_record(tmp_path, monkeypatch):
    monkeypatch.setattr(
        fleet, "read_summary",
        lambda *a, **k: fleet.DispatchResult(ok=True, run_id="RID1", message="Fleet run RID1 — 1 task(s)"),
    )
    coord = _coord(tmp_path)
    reply = await coord.handle_command("s", DispatchCommand(kind="status", run_id="RID1"))
    assert "Fleet run RID1" in reply


@pytest.mark.asyncio
async def test_status_uses_latest_when_no_id(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "latest_run_id", lambda *a, **k: "LATEST")
    seen = {}

    def fake_read(*a, **k):
        seen.update(k)
        return fleet.DispatchResult(ok=True, run_id=k.get("run_id", ""), message="ok")

    monkeypatch.setattr(fleet, "read_summary", fake_read)
    coord = _coord(tmp_path)
    await coord.handle_command("s", DispatchCommand(kind="status", run_id=""))
    assert seen.get("run_id") == "LATEST"


@pytest.mark.asyncio
async def test_status_no_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "latest_run_id", lambda *a, **k: None)
    coord = _coord(tmp_path)
    reply = await coord.handle_command("s", DispatchCommand(kind="status", run_id=""))
    assert "No dispatches yet" in reply


@pytest.mark.asyncio
async def test_status_surfaces_swap_progress_trail(tmp_path):
    # Finding 1: the operator is blind during the swap (WinUI closes), so /dispatch status
    # must surface the restart-surviving progress trail written during the swap.
    from shared.fleet import swap_ops
    cfg = _cfg(tmp_path)
    swap_ops.write_swap_progress(cfg, "RID-DET", "stepping aside for the 30B")
    swap_ops.write_swap_progress(cfg, "RID-DET", "30B loading")
    fleet.write_acceptance_record(cfg, "RID-DET", spec_dict=_spec().to_dict(),
                                  repo=str(cfg.projects_dir / "calc"))
    coord = DispatchCoordinator(config=cfg, enabled=True)
    reply = await coord.handle_command("s", DispatchCommand(kind="status", run_id="RID-DET"))
    assert "What happened during the swap" in reply
    assert "stepping aside for the 30B" in reply and "30B loading" in reply


# ===========================================================================
# Confidence-gated clarifying question (ask-when-ambiguous) — increment 4, #677
# ===========================================================================
#
# ONE bounded interactive sub-state extending the existing pending-approval flow. When the
# 14B flagged a genuinely ambiguous platform fork (surface=ambiguous + candidates), the
# coordinator asks ONE curated question BEFORE the normal preview; the operator answers with
# the option number; the chosen surface is threaded into the plan; then the SAME approval
# preview. The KILL-TEST: a clear surface drives NO extra turn (today's flow).

_AMBIGUOUS_BUILD_PLAN = {
    "surface": "ambiguous", "language_hint": None, "complexity": "moderate",
    "components": [], "candidates": ["desktop-gui", "web", "mobile"],
}


def _ambiguous_spec():
    return AcceptanceSpec(
        "an app with buttons",
        (
            AcceptanceCriterion("c1", "the project builds", "build", ""),
            AcceptanceCriterion("c2", "the buttons work", "behavior", ""),
        ),
        build_plan=dict(_AMBIGUOUS_BUILD_PLAN),
    )


def _ambiguous_plan(*, calls=None):
    """A plan_fn whose spec carries an AMBIGUOUS build_plan (the clarifying trigger). Its task
    starts threaded surface=ambiguous (as compile_prompts would leave it pre-answer) so the
    re-threading after the answer is observable."""
    spec = _ambiguous_spec()

    async def plan_fn(repo, goal):
        if calls is not None:
            calls.append((repo, goal))
        return PlanResult(
            ok=True,
            tasks=[{"repo": repo, "task": "build-app", "prompt": "build it",
                    "surface": "ambiguous", "complexity": "moderate", "language_hint": None}],
            spec=spec,
            message="planned",
        )

    return plan_fn


# ---- parse the clarifying-answer forms ------------------------------------


def test_parse_choose_bare_number():
    c = parse_dispatch_command("/dispatch 2")
    assert c and c.kind == "choose" and c.choice == "2"


def test_parse_choose_use_and_choose_verbs():
    assert parse_dispatch_command("/dispatch use 3").kind == "choose"
    assert parse_dispatch_command("/dispatch use 3").choice == "3"
    assert parse_dispatch_command("/dispatch choose 1").choice == "1"


def test_parse_goal_with_pipe_is_still_run_not_choose():
    # A real repo|goal is unaffected; only a BARE number / use-N is a choose.
    c = parse_dispatch_command("/dispatch calc | a calculator")
    assert c.kind == "run" and c.repo == "calc"


# ---- the clarifying sub-state ---------------------------------------------


@pytest.mark.asyncio
async def test_ambiguous_plan_asks_the_curated_question_not_the_preview(tmp_path):
    # The 14B flagged ambiguity -> the coordinator asks the SYSTEM's curated question and does
    # NOT yet show the approval preview (no approval-pending slot; a clarification slot instead).
    coord = _coord(tmp_path, plan_fn=_ambiguous_plan())
    reply = await coord.handle_command("s", DispatchCommand(kind="run", repo="app", goal="an app with buttons"))
    assert "Where will you mainly use this?" in reply
    assert "1. On this computer" in reply and "2. In a web browser" in reply and "3. On a phone" in reply
    # the curated options are shown, NOT the acceptance criteria preview yet
    assert "Automatic checks" not in reply
    assert "/dispatch approve" not in reply
    # state: a clarification is pending; NO approval-pending dispatch yet
    assert coord.pending_clarification_for("s") is not None
    assert coord.pending_for("s") is None


@pytest.mark.asyncio
async def test_answering_threads_surface_and_shows_preview(tmp_path):
    # The operator answers "2" (web) -> the chosen surface is threaded into the plan and the
    # NORMAL approval preview is shown; the clarification slot clears, approval-pending is set.
    coord = _coord(tmp_path, plan_fn=_ambiguous_plan())
    await coord.handle_command("s", DispatchCommand(kind="run", repo="app", goal="an app with buttons"))
    reply = await coord.handle_command("s", DispatchCommand(kind="choose", choice="2"))
    assert "Got it — building it for: In a web browser." in reply
    assert "the buttons work" in reply              # the normal criteria preview is now shown
    assert "/dispatch approve" in reply
    # the chosen surface threaded onto the pending dispatch's tasks (the load-bearing wiring)
    pending = coord.pending_for("s")
    assert pending is not None
    assert pending.spec.build_plan["surface"] == "web"
    assert pending.spec.build_plan["candidates"] == []      # fork resolved
    assert pending.tasks[0]["surface"] == "web"             # re-threaded onto the task
    # the clarification slot is cleared (bounded to one turn)
    assert coord.pending_clarification_for("s") is None


@pytest.mark.asyncio
async def test_answering_then_approve_executes_with_resolved_surface(tmp_path):
    # End-to-end through EXECUTE: answer the question, then approve — the surface that reaches
    # execute_fn (and the persisted record) is the operator's chosen one, not "ambiguous".
    exec_calls = []
    cfg = _cfg(tmp_path)
    coord = DispatchCoordinator(config=cfg, enabled=True, plan_fn=_ambiguous_plan(),
                                execute_fn=_fake_execute(calls=exec_calls), mint_run_id=lambda: "RID-DET")
    await coord.handle_command("s", DispatchCommand(kind="run", repo="app", goal="an app with buttons"))
    await coord.handle_command("s", DispatchCommand(kind="choose", choice="1"))  # desktop-gui
    await coord.handle_command("s", DispatchCommand(kind="approve"))
    assert len(exec_calls) == 1
    assert exec_calls[0]["tasks"][0]["surface"] == "desktop-gui"
    assert exec_calls[0]["spec"].build_plan["surface"] == "desktop-gui"
    rec = fleet.read_acceptance_record(cfg, "RID-DET")
    assert rec is not None and rec["spec"]["build_plan"]["surface"] == "desktop-gui"


@pytest.mark.asyncio
async def test_clear_surface_drives_no_extra_turn_kill_test(tmp_path):
    # THE KILL-TEST: a CLEAR-surface plan asks NOTHING — the approval preview is shown directly
    # (today's flow, byte-identical), no clarification slot. Reverting the resolve hook in _plan
    # would make an ambiguous plan ALSO skip the question; this binds the clear-surface side.
    clear_spec = AcceptanceSpec(
        "a desktop calc",
        (AcceptanceCriterion("c1", "the project builds", "build", ""),
         AcceptanceCriterion("c2", "2 + 3 shows 5", "behavior", "")),
        build_plan={"surface": "desktop-gui", "language_hint": None, "complexity": "moderate", "components": []},
    )
    coord = _coord(tmp_path, plan_fn=_fake_plan(clear_spec))
    reply = await coord.handle_command("s", DispatchCommand(kind="run", repo="calc", goal="a desktop calc"))
    assert "Where will you mainly use this?" not in reply  # no question
    assert "/dispatch approve" in reply                    # straight to the approval preview
    assert coord.pending_clarification_for("s") is None
    assert coord.pending_for("s") is not None


@pytest.mark.asyncio
async def test_no_build_plan_drives_no_question(tmp_path):
    # The default (the existing _fake_plan spec has NO build_plan) -> resolve returns None ->
    # no extra turn. This is exactly the existing 32 tests' posture; asserted explicitly here.
    coord = _coord(tmp_path, plan_fn=_fake_plan())
    reply = await coord.handle_command("s", DispatchCommand(kind="run", repo="calc", goal="a calc"))
    assert "Where will you mainly use this?" not in reply
    assert coord.pending_clarification_for("s") is None
    assert coord.pending_for("s") is not None


@pytest.mark.asyncio
async def test_unmapped_ambiguous_fork_falls_through_to_preview(tmp_path):
    # An ambiguous fork the curated map has no entry for ({command-line, library}) yields NO
    # question -> today's guess+confirm preview directly. Keeps the map SMALL without blocking.
    spec = AcceptanceSpec(
        "a tool",
        (AcceptanceCriterion("c1", "the project builds", "build", ""),),
        build_plan={"surface": "ambiguous", "language_hint": None, "complexity": "moderate",
                    "components": [], "candidates": ["command-line", "library"]},
    )
    coord = _coord(tmp_path, plan_fn=_fake_plan(spec))
    reply = await coord.handle_command("s", DispatchCommand(kind="run", repo="t", goal="a tool"))
    assert "Where will you mainly use this?" not in reply
    assert "/dispatch approve" in reply
    assert coord.pending_clarification_for("s") is None


@pytest.mark.asyncio
async def test_out_of_range_answer_falls_back_no_hang(tmp_path):
    # A malformed / out-of-range answer (e.g. "9") FALLS BACK to the un-refined plan (never a
    # hang/loop): the preview is shown, surface threads as unknown (the fleet's no-seed path),
    # and the operator can still approve/reject. The clarification slot clears.
    coord = _coord(tmp_path, plan_fn=_ambiguous_plan())
    await coord.handle_command("s", DispatchCommand(kind="run", repo="app", goal="an app with buttons"))
    reply = await coord.handle_command("s", DispatchCommand(kind="choose", choice="9"))
    assert "didn't catch which option" in reply.lower()
    assert "/dispatch approve" in reply                 # still proceeds to the preview
    pending = coord.pending_for("s")
    assert pending is not None
    assert pending.tasks[0]["surface"] == "unknown"     # unresolved ambiguous -> unknown to the fleet
    assert coord.pending_clarification_for("s") is None  # bounded — slot cleared even on fallback


@pytest.mark.asyncio
async def test_non_numeric_answer_also_falls_back(tmp_path):
    coord = _coord(tmp_path, plan_fn=_ambiguous_plan())
    await coord.handle_command("s", DispatchCommand(kind="run", repo="app", goal="g"))
    reply = await coord.handle_command("s", DispatchCommand(kind="choose", choice="banana"))
    assert "didn't catch which option" in reply.lower()
    assert coord.pending_for("s") is not None
    assert coord.pending_clarification_for("s") is None


@pytest.mark.asyncio
async def test_choose_with_nothing_pending_reports_clearly(tmp_path):
    coord = _coord(tmp_path, plan_fn=_fake_plan())
    reply = await coord.handle_command("s", DispatchCommand(kind="choose", choice="2"))
    assert "no question waiting" in reply.lower()


@pytest.mark.asyncio
async def test_new_dispatch_while_question_pending_is_refused(tmp_path):
    # The one-pending-slot discipline: a new /dispatch while a question is pending is refused
    # (the 14B is not re-run), pointing the operator at the question.
    calls = []
    coord = _coord(tmp_path, plan_fn=_ambiguous_plan(calls=calls))
    await coord.handle_command("s", DispatchCommand(kind="run", repo="app", goal="first"))
    reply = await coord.handle_command("s", DispatchCommand(kind="run", repo="app", goal="second"))
    assert "waiting on one question" in reply.lower()
    assert len(calls) == 1  # the 14B was not re-run while the question is pending


@pytest.mark.asyncio
async def test_reject_clears_pending_question(tmp_path):
    # reject cancels at the QUESTION phase too (not only the approval phase).
    coord = _coord(tmp_path, plan_fn=_ambiguous_plan())
    await coord.handle_command("s", DispatchCommand(kind="run", repo="app", goal="drop me"))
    assert coord.pending_clarification_for("s") is not None
    reply = await coord.handle_command("s", DispatchCommand(kind="reject"))
    assert "Cancelled" in reply and "drop me" in reply
    assert coord.pending_clarification_for("s") is None
    assert coord.pending_for("s") is None


@pytest.mark.asyncio
async def test_question_phase_fires_no_execute(tmp_path):
    # The mandatory-confirm guarantee extends across the new sub-state: planning into a
    # question, then answering, fires NO execute until an explicit approve.
    exec_calls = []
    coord = _coord(tmp_path, plan_fn=_ambiguous_plan(), execute_fn=_fake_execute(calls=exec_calls))
    await coord.handle_command("s", DispatchCommand(kind="run", repo="app", goal="g"))
    await coord.handle_command("s", DispatchCommand(kind="choose", choice="2"))
    assert exec_calls == []  # answering resolves the surface but does NOT fire work


# ---- /dispatch new: create-a-project (#712) -------------------------------


def test_parse_new_create_verb():
    c = parse_dispatch_command("/dispatch new kid-calc | a calc for a kid")
    assert c and c.kind == "create"
    assert c.repo == "kid-calc" and c.goal == "a calc for a kid"


def test_parse_new_without_pipe_is_create_with_empty_goal():
    c = parse_dispatch_command("/dispatch new kid-calc")
    assert c and c.kind == "create" and c.repo == "kid-calc" and c.goal == ""


def test_parse_new_no_space_before_pipe():
    c = parse_dispatch_command("/dispatch new calc|x")
    assert c and c.kind == "create" and c.repo == "calc" and c.goal == "x"


def test_parse_newsapp_is_run_not_create():
    # A repo whose name merely STARTS with "new" is a normal run target.
    c = parse_dispatch_command("/dispatch newsapp | x")
    assert c and c.kind == "run" and c.repo == "newsapp"


@pytest.mark.asyncio
async def test_create_and_plan_creates_repo_then_plans(tmp_path):
    calls = []
    coord = _coord(tmp_path, plan_fn=_fake_plan(calls=calls))
    reply = await coord.handle_command(
        "s", DispatchCommand(kind="create", repo="Kid Calc", goal="a calc for a kid")
    )
    # The repo was REALLY created (git) under the projects dir...
    repo = _cfg(tmp_path).projects_dir / "kid-calc"
    assert (repo / ".git").is_dir()
    # ...and the PLAN ran on the created slug, landing in approval-pending state.
    assert calls == [("kid-calc", "a calc for a kid")]
    assert coord.pending_for("s") is not None
    assert "Created a new project 'kid-calc'" in reply
    # The plan preview signals Approve/Reject buttons (one-shot, then cleared).
    assert coord.pop_action_kind("s") == "dispatch_plan"
    assert coord.pop_action_kind("s") == ""


@pytest.mark.asyncio
async def test_create_refuses_empty_goal(tmp_path):
    coord = _coord(tmp_path, plan_fn=_fake_plan())
    reply = await coord.handle_command(
        "s", DispatchCommand(kind="create", repo="x", goal="")
    )
    assert "Usage: /dispatch new" in reply
    assert coord.pending_for("s") is None


@pytest.mark.asyncio
async def test_create_blocked_while_a_dispatch_is_pending(tmp_path):
    coord = _coord(tmp_path, plan_fn=_fake_plan())
    # First create lands a pending plan.
    await coord.handle_command("s", DispatchCommand(kind="create", repo="one", goal="g"))
    assert coord.pending_for("s") is not None
    # A second new-project attempt is refused until the first is resolved.
    reply = await coord.handle_command(
        "s", DispatchCommand(kind="create", repo="two", goal="g2")
    )
    assert "Finish the dispatch that's already waiting" in reply
    assert not (_cfg(tmp_path).projects_dir / "two").exists()
