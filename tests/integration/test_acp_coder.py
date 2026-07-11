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
from pathlib import Path

import pytest

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
    NEW-file events fire during it. The ACP model retires that: tool_call_update
    and agent_message_chunk heartbeats on the ONE in-flight write keep the
    liveness clock fresh, so a long healthy single-artifact write is never
    false-doomed. Closes #779 by construction."""
    clk = FakeClock()
    t = AcpEventTracker(clock=clk)
    # One long edit begins.
    t.on_session_update(tool_call("render-1", kind="edit", status="in_progress"))
    # Over the next 5 minutes, only heartbeats on that SAME call arrive — no new
    # file, no new tool_call — every 30 s (well inside the 120 s idle window).
    for _ in range(10):
        clk.advance(30.0)
        t.on_session_update(agent_chunk("...still rendering the frame..."))
        assert not t.is_idle(idle_timeout=ACP_IDLE_TIMEOUT_S), "heartbeats must keep it live"
    # And it never spuriously capped (one long edit, no spin).
    assert not t.step_cap().capped
    # The old mtime/new-file heuristic would have doomed this after 240 s of "no
    # new file"; the semantic stream did not.


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
    assert ACP_IDLE_TIMEOUT_S == 120.0
    assert ACP_MAX_STEPS == 45 and ACP_SPIN_STEPS == 10
