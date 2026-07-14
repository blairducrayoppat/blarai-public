"""Unit tests for the ACP coder driver (tools/dispatch_harness/acp_coder.py, #775).

No model, no GPU, and critically **no ``acp`` SDK** — the driver's pure logic
(event→field mapping, step-cap, semantic idle detection, own-cancel tracking,
the result contract) is exercised with a HAND-BUILT fake event stream. This is
the design guarantee that makes the module testable under the 3.11 standing gate
even though the live ACP path needs Python 3.14 + the SDK (the import is lazy).

These run in the standing gate (tests/integration is in scope).

Covers, per ACP-01 §7.2 + the spike RESULTS.md integration requirements:
  * the §7.2 result contract shape (the exact 8 PascalCase keys),
  * the step/spin cap rebuilt on typed events (Invoke-AgentRun MaxSteps/SpinSteps parity),
  * the semantic idle bound — and the **#779 regression case**: a long
    single-artifact write survives the idle-breaker because tool_call_update /
    agent_message_chunk heartbeats keep the liveness clock fresh,
  * own-cancel tracking that never trusts StopReason,
  * event→field mapping (steps, edits, failed tool calls, token usage).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from shared.fleet import acp_progress as ap
from tools.dispatch_harness.acp_coder import (
    ACP_IDLE_TIMEOUT_S,
    ACP_MAX_STEPS,
    ACP_SPIN_STEPS,
    AcpEventTracker,
    AcpRunResult,
    CancelState,
    classify_result,
    evaluate_step_cap,
    idle_exceeded,
    make_envelope,
    normalize_model,
)


# ---------------------------------------------------------------------------
# fake event stream helpers — the normalized (camelCase) session/update payload
# shape the SDK emits (update.model_dump(by_alias=True)), exactly as the #759
# spike captured to NDJSON.
# ---------------------------------------------------------------------------


def tool_call(tcid: str, kind: str = "execute", status: str = "pending") -> dict:
    return {"sessionUpdate": "tool_call", "toolCallId": tcid, "kind": kind, "status": status,
            "title": f"{kind} {tcid}"}


def tool_call_update(tcid: str, status: str, kind: str | None = None) -> dict:
    p = {"sessionUpdate": "tool_call_update", "toolCallId": tcid, "status": status}
    if kind is not None:
        p["kind"] = kind
    return p


def agent_chunk(text: str = "thinking...") -> dict:
    return {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": text}}


def usage(inp: int, out: int) -> dict:
    return {"sessionUpdate": "usage_update", "usage": {"inputTokens": inp, "outputTokens": out}}


class FakeClock:
    """A hand-advanced monotonic clock so idle/step timing is deterministic."""

    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


# ---------------------------------------------------------------------------
# result contract
# ---------------------------------------------------------------------------


def test_result_contract_has_exact_eight_keys():
    contract = AcpRunResult(log_path="x.log", seconds=1.234).to_contract()
    assert set(contract) == {
        "TimedOut", "TimeoutReason", "Capped", "CappedReason",
        "ExitCode", "LogPath", "Seconds", "Error",
    }


def test_result_contract_null_exit_code_on_timeout():
    r = AcpRunResult(timed_out=True, timeout_reason="idle", exit_code=None, log_path="l")
    c = r.to_contract()
    assert c["ExitCode"] is None  # -> $null through ConvertFrom-Json, like Invoke-AgentRun
    assert c["TimedOut"] is True and c["TimeoutReason"] == "idle"


def test_result_contract_rounds_seconds():
    assert AcpRunResult(seconds=12.3456).to_contract()["Seconds"] == 12.3


# ---------------------------------------------------------------------------
# step / spin cap — parity with Invoke-AgentRun's -JsonStepCap block
# ---------------------------------------------------------------------------


def test_step_cap_hard_ceiling_at_max_steps():
    dec = evaluate_step_cap(steps=ACP_MAX_STEPS, edits=5, steps_at_last_edit=40)
    assert dec.capped and "hard cap" in dec.reason


def test_step_cap_not_tripped_below_ceiling_while_editing():
    # steps climbing but each near an edit -> a legit long task, not capped.
    dec = evaluate_step_cap(steps=44, edits=20, steps_at_last_edit=44)
    assert not dec.capped


def test_spin_detector_trips_after_edits_stop():
    # 1 edit happened at step 5, then 10 non-edit steps (the F2 probe loop).
    dec = evaluate_step_cap(steps=15, edits=1, steps_at_last_edit=5)
    assert dec.capped and "spin" in dec.reason


def test_spin_detector_silent_before_any_edit():
    # No edit yet -> the spin rule does not apply (only the hard cap can fire).
    dec = evaluate_step_cap(steps=12, edits=0, steps_at_last_edit=0)
    assert not dec.capped


# ---------------------------------------------------------------------------
# idle detection (pure) + the #779 regression
# ---------------------------------------------------------------------------


def test_idle_exceeded_boundary():
    assert idle_exceeded(now=1000 + ACP_IDLE_TIMEOUT_S, last_event=1000.0)
    assert not idle_exceeded(now=1000 + ACP_IDLE_TIMEOUT_S - 0.5, last_event=1000.0)


def test_tracker_idle_after_silence():
    clk = FakeClock()
    t = AcpEventTracker(clock=clk)
    t.on_session_update(tool_call("a", kind="execute", status="in_progress"))
    clk.advance(ACP_IDLE_TIMEOUT_S + 1)
    assert t.is_idle(idle_timeout=ACP_IDLE_TIMEOUT_S)


def test_779_long_single_artifact_write_is_not_idle():
    """#779 regression: a slow SINGLE-file render used to read as idle because no
    NEW-file events fire during it. IF tool_call_update / agent_message_chunk
    heartbeats DO arrive on the one in-flight write, they keep the liveness clock
    fresh, so a long healthy single-artifact write is never false-doomed. This
    locks the reset-on-any-event contract.

    NOTE (#790): the field caveat this test cannot see is that opencode-acp does
    not reliably EMIT those heartbeats during a real generation window — the
    2026-07-12 battery showed 120 s of total silence on every channel. That is an
    upstream emission gap, addressed by the generous ACP_IDLE_TIMEOUT_S bound
    (see test_790_* below), not by this reset logic, which is correct as-is."""
    clk = FakeClock()
    t = AcpEventTracker(clock=clk)
    # One long edit begins.
    t.on_session_update(tool_call("render-1", kind="edit", status="in_progress"))
    # Over the next 5 minutes, only heartbeats on that SAME call arrive — no new
    # file, no new tool_call — every 30 s (well inside the idle window).
    for _ in range(10):
        clk.advance(30.0)
        t.on_session_update(agent_chunk("...still rendering the frame..."))
        assert not t.is_idle(idle_timeout=ACP_IDLE_TIMEOUT_S), "heartbeats must keep it live"
    # And it never spuriously capped (one long edit, no spin).
    assert not t.step_cap().capped


def test_790_token_activity_without_discrete_step_keeps_candidate_alive():
    """#790 core lock: a candidate emitting TOKENS (agent_message_chunk) but
    making NO new discrete step/edit is WORKING and must not be idle-cancelled.
    This is the property the fix protects — 'emitting is working' — and it holds
    at any bound as long as the chunks land within it."""
    clk = FakeClock()
    t = AcpEventTracker(clock=clk)
    t.on_session_update(tool_call("read-1", kind="read", status="completed"))
    steps_before = t.steps
    # 8 minutes of pure message-chunk streaming, one chunk/minute — no new
    # tool_call, no edit — comfortably inside the 600 s bound.
    for _ in range(8):
        clk.advance(60.0)
        t.on_session_update(agent_chunk("...still generating the implementation..."))
        assert not t.is_idle(idle_timeout=ACP_IDLE_TIMEOUT_S), "token activity must keep it live"
    assert t.steps == steps_before  # chunks are liveness only — never counted as steps
    assert not t.step_cap().capped


def test_790_silent_generation_window_survives_new_bound_but_would_die_at_120s():
    """#790 regression: the exact failure the battery hit. A candidate goes fully
    silent (no session/update at all — opencode emits none during a long
    generation) for 240 s, a window that is well within a healthy 30B's
    first/next-response generation. At the OLD 120 s bound it was false-killed
    (the 18/24 battery deaths); at the recalibrated 600 s bound it survives."""
    clk = FakeClock()
    t = AcpEventTracker(clock=clk)
    t.on_session_update(tool_call("plan-1", kind="read", status="completed"))
    clk.advance(240.0)  # 4 min of pure generation silence — the observed shape
    assert t.is_idle(idle_timeout=120.0), "documents the OLD 120 s false-kill"
    assert not t.is_idle(idle_timeout=ACP_IDLE_TIMEOUT_S), "the 600 s bound must NOT kill it"


def test_790_truly_hung_candidate_still_idle_cancels_at_new_bound():
    """The true-hang catch survives the recalibration: a candidate with NO event
    of any kind for longer than the bound is still declared idle (TimedOut)."""
    clk = FakeClock()
    t = AcpEventTracker(clock=clk)
    t.on_session_update(tool_call("a", kind="execute", status="in_progress"))
    clk.advance(ACP_IDLE_TIMEOUT_S + 1)
    assert t.is_idle(idle_timeout=ACP_IDLE_TIMEOUT_S)
    # And it classifies as a TimedOut/'idle' cancel (never trusts StopReason).
    c = CancelState()
    c.mark("idle")
    r = classify_result(tracker=t, cancel=c, elapsed_s=ACP_IDLE_TIMEOUT_S + 1, log_path="l")
    assert r.timed_out and r.timeout_reason == "idle" and r.exit_code is None


# ---------------------------------------------------------------------------
# event -> field mapping
# ---------------------------------------------------------------------------


def test_distinct_tool_calls_count_steps_once():
    t = AcpEventTracker()
    t.on_session_update(tool_call("a", status="pending"))
    t.on_session_update(tool_call_update("a", status="in_progress"))
    t.on_session_update(tool_call_update("a", status="completed"))
    t.on_session_update(tool_call("b", status="pending"))
    assert t.steps == 2  # two distinct ids, not five events


def test_edit_kind_counts_edits_and_resets_spin_anchor():
    t = AcpEventTracker()
    t.on_session_update(tool_call("e1", kind="edit"))
    t.on_session_update(tool_call("x1", kind="execute"))
    t.on_session_update(tool_call("e2", kind="edit"))
    assert t.edits == 2
    assert t.steps_at_last_edit == 3  # the 3rd distinct call was the 2nd edit


def test_late_typed_edit_on_update_credited_once():
    t = AcpEventTracker()
    t.on_session_update(tool_call("z", kind="", status="pending"))  # kind unknown at start
    assert t.edits == 0
    t.on_session_update(tool_call_update("z", status="in_progress", kind="edit"))
    assert t.edits == 1
    # A second update naming edit again must NOT double-count.
    t.on_session_update(tool_call_update("z", status="completed", kind="edit"))
    assert t.edits == 1


def test_failed_tool_calls_surface():
    t = AcpEventTracker()
    t.on_session_update(tool_call("a", status="pending"))
    t.on_session_update(tool_call_update("a", status="failed"))
    t.on_session_update(tool_call("b", status="pending"))
    t.on_session_update(tool_call_update("b", status="failed"))
    t.on_session_update(tool_call_update("b", status="failed"))  # idempotent
    assert t.failed_tool_calls == 2


def test_usage_tracked():
    t = AcpEventTracker()
    t.on_session_update(usage(1200, 340))
    t.on_session_update(usage(1500, 900))  # cumulative high-water
    assert t.tokens_in == 1500 and t.tokens_out == 900


def test_transcript_written(tmp_path: Path):
    log = tmp_path / "sub" / "run.log"
    t = AcpEventTracker(log_path=log)
    t.on_session_update(tool_call("a", kind="edit"))
    t.write_line("[acp-driver] provenance")
    t.close()
    body = log.read_text(encoding="utf-8")
    assert '"event": "tool_call"' in body
    assert "[acp-driver] provenance" in body
    # one JSON object per event line (grep-friendly, like the stdin transcript)
    first = json.loads(body.splitlines()[0])
    assert first["payload"]["toolCallId"] == "a"


# ---------------------------------------------------------------------------
# own-cancel tracking + result classification
# ---------------------------------------------------------------------------


def test_cancel_state_first_cause_wins():
    c = CancelState()
    c.mark("cap")
    c.mark("idle")
    assert c.sent and c.reason == "cap"


def test_classify_natural_finish_is_clean_exit_zero():
    t = AcpEventTracker()
    t.on_session_update(tool_call("a", kind="edit", status="completed"))
    r = classify_result(tracker=t, cancel=CancelState(), elapsed_s=42.0, log_path="l.log")
    assert not r.timed_out and not r.capped and r.exit_code == 0


def test_classify_idle_cancel_is_timeout_idle():
    c = CancelState()
    c.mark("idle")
    r = classify_result(tracker=AcpEventTracker(), cancel=c, elapsed_s=130.0, log_path="l")
    assert r.timed_out and r.timeout_reason == "idle" and r.exit_code is None


def test_classify_ceiling_cancel_is_timeout_ceiling():
    c = CancelState()
    c.mark("ceiling")
    r = classify_result(tracker=AcpEventTracker(), cancel=c, elapsed_s=3600.0, log_path="l")
    assert r.timed_out and r.timeout_reason == "ceiling" and r.exit_code is None


def test_classify_cap_cancel_is_capped_exit_zero():
    # A cap sends a cancel (cooperative-first), but a cap is NOT a timeout — the
    # work is on disk, so ExitCode=0 and the gate still decides the merge.
    t = AcpEventTracker()
    for i in range(ACP_MAX_STEPS):
        t.on_session_update(tool_call(f"c{i}", kind="execute"))
    c = CancelState()
    c.mark("cap")
    r = classify_result(tracker=t, cancel=c, elapsed_s=500.0, log_path="l")
    assert r.capped and not r.timed_out and r.exit_code == 0
    assert "hard cap" in r.capped_reason


def test_classify_run_error_parks_not_falls_back():
    r = classify_result(tracker=AcpEventTracker(), cancel=CancelState(), elapsed_s=5.0,
                        log_path="l", run_error="acp prompt raised: RuntimeError: boom")
    assert r.error and r.exit_code is None
    assert not r.timed_out and not r.capped


def test_classify_step_cap_without_cancel_still_capped():
    # Defensive: if the cap tripped but no cancel was recorded, still report Capped.
    t = AcpEventTracker()
    for i in range(ACP_MAX_STEPS):
        t.on_session_update(tool_call(f"c{i}", kind="execute"))
    r = classify_result(tracker=t, cancel=CancelState(), elapsed_s=500.0, log_path="l")
    assert r.capped and r.exit_code == 0


# ---------------------------------------------------------------------------
# CLI envelope + helpers
# ---------------------------------------------------------------------------


def test_envelope_import_failure_signals_fallback():
    env = make_envelope(ok=False, phase="import", fallback_to_stdin=True, error="no acp")
    assert env["fallback_to_stdin"] is True and env["phase"] == "import"
    assert "result" not in env


def test_envelope_run_carries_contract():
    env = make_envelope(ok=True, phase="run", fallback_to_stdin=False,
                        result=AcpRunResult(exit_code=0, log_path="l"))
    assert env["fallback_to_stdin"] is False
    assert set(env["result"]) == {
        "TimedOut", "TimeoutReason", "Capped", "CappedReason",
        "ExitCode", "LogPath", "Seconds", "Error"}


@pytest.mark.parametrize("raw,expected", [
    ("coder-30b", "local/coder-30b"),
    ("local/coder-30b", "local/coder-30b"),
    ("some/other", "some/other"),
    ("", ""),
])
def test_normalize_model(raw, expected):
    assert normalize_model(raw) == expected


def test_idle_constant_matches_registered_value():
    # The timeout registry cross-checks this same constant; keep them in lockstep.
    # 600 s per the #790 recalibration (was 120 s — false-killed 18/24 candidates).
    assert ACP_IDLE_TIMEOUT_S == 600.0
    assert ACP_MAX_STEPS == 45 and ACP_SPIN_STEPS == 10


# ---------------------------------------------------------------------------
# durable coordinator-facing progress artifact (#844 C2) — additive + fail-soft
# ---------------------------------------------------------------------------


def test_progress_artifact_written_per_event(tmp_path: Path):
    prog = tmp_path / "acp-progress.json"
    fixed_wall = 1_700_000_000.0  # a fixed wall-clock so the timestamp is deterministic
    t = AcpEventTracker(run_id="R7", progress_path=prog, wall_clock=lambda: fixed_wall)
    t.on_session_update(tool_call("c1", kind="edit", status="completed"))
    snap = ap.read_acp_progress(prog)
    assert snap is not None
    assert snap.run_id == "R7"
    assert snap.steps == 1 and snap.edits == 1 and snap.event_count == 1
    # the durable stamp is WALL-CLOCK (not the monotonic idle clock)
    assert snap.last_event_at == datetime.fromtimestamp(fixed_wall, tz=timezone.utc).isoformat()


def test_progress_refreshed_each_event(tmp_path: Path):
    prog = tmp_path / "acp-progress.json"
    t = AcpEventTracker(run_id="R", progress_path=prog)
    t.on_session_update(tool_call("a", kind="execute"))
    t.on_session_update(tool_call("b", kind="edit"))
    snap = ap.read_acp_progress(prog)
    assert snap is not None
    assert snap.event_count == 2 and snap.steps == 2 and snap.edits == 1


def test_no_progress_path_writes_nothing(tmp_path: Path):
    prog = tmp_path / "acp-progress.json"
    t = AcpEventTracker()  # progress_path defaults None -> the write is a no-op
    t.on_session_update(agent_chunk())
    assert not prog.exists()


def test_progress_write_is_fail_soft(tmp_path: Path):
    # progress_path's parent is a FILE -> the write cannot mkdir -> fail-soft.
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    t = AcpEventTracker(run_id="R", progress_path=blocker / "sub" / "acp-progress.json")
    t.on_session_update(agent_chunk())  # must NOT raise despite the write failing
    assert t.event_count == 1           # the event still folded
