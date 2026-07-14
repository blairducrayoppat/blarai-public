"""The production ACP coder driver (Vikunja #775 / ACP-01, carries #779).

WHAT THIS IS
============
The parallel driver the PowerShell fleet can switch to per run — it drives a
persistent ``opencode acp`` session over the Agent Client Protocol (JSON-RPC 2.0
over stdio, typed event stream) instead of the production ``opencode run`` +
transcript-regex path (``fleet-lib.ps1`` ``Invoke-AgentRun``). It returns the
EXACT same result contract ``Invoke-CandidateBuild`` already consumes, so the
best-of-N selection / deterministic gate / merge are byte-unchanged — ACP
replaces only *how the coder is driven and watched*, never *how the winner is
chosen* (ACP-01 design §2).

WHY IT LIVES HERE, IN TWO HALVES
================================
The #759 spike proved the ACP client belongs on the Python side, beside
``monitor.py`` where monitoring already lives — the JSON-RPC event loop, the
SDK, and the tree-kill all want to be Python. But the SDK
(``agent-client-protocol`` 0.11.0) needs **Python 3.14**, while the BlarAI
runtime ``.venv`` (and this whole test suite) is **3.11**. The resolution — and
the load-bearing design rule of this module:

    * The PURE logic (event→field mapping, step-cap, idle detection, own-cancel
      tracking, the result contract) is at module top level and imports NO
      ``acp`` — so it is unit-testable under the 3.11 gate with a FAKE event
      stream, and the timeout registry can import the module to read
      ``ACP_IDLE_TIMEOUT_S``.
    * The LIVE run path (``_run_acp_session``) imports ``acp`` LAZILY, inside the
      function. An import/handshake failure is reported as a *fall-back-to-stdin*
      envelope (ACP-01 §2 config-fallback: the driver choice is a dev-tooling
      reliability call, not a security boundary — the security floor is the §3
      restricted account, independent of which driver drove).

So this file is importable and testable everywhere; it only *runs* under a 3.14
interpreter with ``acp`` present, invoked by the PowerShell shim
(``Invoke-CoderDriver`` in ``fleet-lib.ps1``) only when
``configs/fleet-driver.json`` says ``driver=acp``. With the default ``stdin`` it
is never imported at all — flag-dormant by construction.

INTEGRATION REQUIREMENTS FROM THE SPIKE (RESULTS.md), ALL BUILT HERE
====================================================================
* **Tree-kill teardown.** The SDK connection-close orphans opencode's node tree
  (9 children reaped after the spike's timeout run). We reuse the blessed
  ``shared.procspawn.terminate_process_tree`` after the session context exits.
* **Rebuild the step/spin cap on the event stream.** ACP has no native
  ``MaxSteps``; the typed events make it EASIER — :class:`AcpEventTracker`
  counts distinct tool-calls (steps) and edit tool-calls, with the same
  hard-cap + spin semantics as ``Invoke-AgentRun -JsonStepCap``.
* **Track own cancels.** opencode 1.17.8 returns ``StopReason=end_turn`` even on
  a cancel — a real fidelity gap. We NEVER trust StopReason; the tracker records
  "did I send cancel, and why" itself.
* **Semantic stall signal (#779 / recalibrated #790).** idle = "no
  ``session/update`` for ``ACP_IDLE_TIMEOUT_S``". This retired the #779
  mtime/new-file blind spot, but the 2026-07-12 battery proved the signal is
  NOT the incremental heartbeat the design assumed: opencode-acp emits NO
  ``session/update`` (and writes NO stderr line) for the whole of a long
  model-generation window, so a healthy 30B generating its first/next response
  looks IDENTICAL to a wedged one on every channel we can see. The bound is
  therefore a coarse "it's never coming back" catch, and must be sized to clear
  a full generation burst — 600 s, not the spike's 120 s (which false-killed
  18/24 candidates). See ``ACP_IDLE_TIMEOUT_S`` for the full calibration note.

THE RESULT CONTRACT (drop-in for ``Invoke-CandidateBuild``)
===========================================================
:meth:`AcpRunResult.to_contract` emits the exact hashtable ``Invoke-AgentRun``
returns today::

    @{ TimedOut; TimeoutReason; Capped; CappedReason; ExitCode; LogPath; Seconds; Error }

so the PowerShell shim surfaces it byte-compatibly.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from shared.fleet import acp_progress

# ---------------------------------------------------------------------------
# Registered timeouts / caps (see shared/timeout_registry.py — the ACP idle
# window is registered there; the gate cross-checks this live constant).
# ---------------------------------------------------------------------------

#: idle = "no session/update for this long" -> a WEDGED coder (TimedOut, 'idle').
#:
#: CALIBRATION — the 2026-07-12 battery (#790). The #759 spike's 83 s "max
#: healthy inter-event gap" was UNREPRESENTATIVE: it undersampled the long
#: single-generation tail. On the first real coder battery under driver=acp, a
#: 120 s bound FALSE-KILLED 18 of 24 candidates (75%). Two shapes, one cause:
#:   * first-token starvation — the 30B spends >120 s generating its FIRST
#:     response (plan + reasoning + first edit) before emitting any tool_call,
#:     so the ONLY session/updates the client sees are the startup
#:     available_commands_update + a used=0 usage_update, then silence -> kill;
#:   * mid-run generation gap — a candidate that DID edit/run tests then enters
#:     one long generation burst (e.g. writing the implementation) and is killed
#:     mid-stream (opencode logs `error=Aborted`) even though it was producing.
#: The load-bearing fact the spike missed: during a model-generation window
#: opencode-acp emits NO session/update AND writes NO line to its own stderr
#: (both channels verified dark across the full 120 s in the battery
#: transcripts), and — before the first edit — nothing is on disk either. So
#: there is NO real-time signal that distinguishes "generating a long response"
#: from "wedged"; the ONLY lever is how long we wait. The cost is asymmetric —
#: false-killing a working candidate is catastrophic (and collapses best-of-N,
#: since all N die the same generation-time death), while waiting longer on a
#: genuinely hung coder is cheap: the ceiling backstop still fires, and at 600 s
#: a true hang is caught at 1/6 of the 3600 s ceiling. So the bound must clear a
#: full multi-minute generation burst with margin, not just the cold-prefill
#: wait. 600 s does; 120 s did not. This is a calibration the LA/coordinator can
#: retighten with real (non-censored) gap data — see the timeout_registry entry.
#: NOTE: the live per-run value is `acp.idle_sec` in agentic-setup
#: configs/fleet-driver.json (it overrides this default via --idle-sec); bumping
#: it there is the operator go-live step that makes this fix take effect on the
#: battery. Registered: shared/timeout_registry.py.
ACP_IDLE_TIMEOUT_S: float = 600.0

#: Hard turn cap — bounds even a coder that keeps making edits. Mirrors
#: Invoke-AgentRun's MaxSteps=45 (fleet-lib.ps1); a cap is NOT a timeout (the
#: work is on disk) -> Capped, ExitCode=0, the gate still decides the merge.
ACP_MAX_STEPS: int = 45

#: Spin detector — this many consecutive tool-calls making NO edit AFTER work
#: began is the compulsive "re-verify done work" loop (the spike's F2 loop:
#: ~15 diagnostic `python -c` probes, no edits, never converged). Mirrors
#: Invoke-AgentRun's SpinSteps=10.
ACP_SPIN_STEPS: int = 10


# ---------------------------------------------------------------------------
# The result contract — the exact shape Invoke-CandidateBuild consumes.
# ---------------------------------------------------------------------------


@dataclass
class AcpRunResult:
    """The outcome of one ACP-driven coder run, in the fleet's result shape.

    The field names deliberately map 1:1 to the PowerShell hashtable
    ``Invoke-AgentRun`` returns (``fleet-lib.ps1:489``) so
    :meth:`to_contract` is a byte-compatible drop-in.
    """

    timed_out: bool = False
    timeout_reason: str = ""       # 'idle' | 'ceiling' | '' (mirrors Invoke-AgentRun)
    capped: bool = False
    capped_reason: str = ""
    exit_code: Optional[int] = None
    log_path: str = ""
    seconds: float = 0.0
    error: str = ""

    def to_contract(self) -> dict[str, Any]:
        """The PascalCase hashtable the PowerShell shim surfaces verbatim."""
        return {
            "TimedOut": self.timed_out,
            "TimeoutReason": self.timeout_reason,
            "Capped": self.capped,
            "CappedReason": self.capped_reason,
            # PowerShell's ConvertFrom-Json maps JSON null -> $null, matching
            # Invoke-AgentRun's ExitCode=$null on a timeout.
            "ExitCode": self.exit_code,
            "LogPath": self.log_path,
            "Seconds": round(self.seconds, 1),
            "Error": self.error,
        }


# ---------------------------------------------------------------------------
# The step-cap decision — pure, mirrors Invoke-AgentRun's -JsonStepCap logic.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StepCapDecision:
    """Whether a run should be CAPPED, and why (a pure function of the counts)."""

    capped: bool
    reason: str = ""


def evaluate_step_cap(
    *, steps: int, edits: int, steps_at_last_edit: int,
    max_steps: int = ACP_MAX_STEPS, spin_steps: int = ACP_SPIN_STEPS,
) -> StepCapDecision:
    """Decide the cap from the running counts — the byte-for-byte analogue of
    ``Invoke-AgentRun``'s ``$spinning``/``$capped`` block (``fleet-lib.ps1:440-443``).

    Two independent bounds, both gate-ELIGIBLE (a cap is not a failure):
      * hard cap: ``steps >= max_steps`` — bounds even a loop that keeps editing.
      * spin: ``edits >= 1`` AND ``steps - steps_at_last_edit >= spin_steps`` —
        the "kept probing, stopped editing" loop, caught EARLY without strangling
        a legit long task (whose edit count keeps rising).
    """
    spinning = (edits >= 1) and ((steps - steps_at_last_edit) >= spin_steps)
    if steps >= max_steps:
        return StepCapDecision(True, f"hard cap: {max_steps} turns")
    if spinning:
        return StepCapDecision(True, f"spin: {spin_steps} turns with no edit after work began")
    return StepCapDecision(False, "")


def idle_exceeded(now: float, last_event: float, idle_timeout: float = ACP_IDLE_TIMEOUT_S) -> bool:
    """True iff no event has arrived for >= ``idle_timeout`` (the wedged-coder
    signal). Pure so the watchdog is trivially testable; ``now``/``last_event``
    are monotonic seconds."""
    return (now - last_event) >= idle_timeout


# ---------------------------------------------------------------------------
# The event tracker — consumes normalized session/update payloads, maintains
# the step/edit counts + token usage + failure visibility + the transcript.
# ---------------------------------------------------------------------------

# opencode's ACP tool-call `kind` for a file-mutating write. The stdin path
# counts `"tool":"(write|edit|patch|multiedit)"` markers; ACP types the call
# directly as kind='edit', so the equivalent signal is one field, not a regex.
_EDIT_KIND = "edit"


@dataclass
class AcpEventTracker:
    """Accumulates the fleet-relevant signals from the ACP event stream.

    Fed one NORMALIZED payload per ``session/update`` — a plain dict shaped like
    ``update.model_dump(mode="json", by_alias=True, exclude_none=True)`` (the
    camelCase form the SDK emits, exactly as the #759 spike captured). Kept free
    of any ``acp`` dependency so it is driven by hand-built fakes in the gate.

    Mapping (ACP-01 §7.2):
      * ``tool_call`` (first-seen ``toolCallId``)  -> a STEP; ``kind==edit`` -> an EDIT.
      * ``tool_call_update``                       -> a status transition on an
        existing call (failure visibility; never a new step).
      * ``agent_message_chunk`` / thought / plan   -> liveness only (idle reset).
      * ``usage_update`` / any ``usage`` payload    -> token accounting.
    """

    log_path: Optional[Path] = None
    clock: Callable[[], float] = time.monotonic
    max_steps: int = ACP_MAX_STEPS
    spin_steps: int = ACP_SPIN_STEPS
    #: #844 C2 — durable progress for the coordinator (a separate process that
    #: cannot see the monotonic ``clock``). Both default off, so existing
    #: construction is unchanged; wired in ``_run_acp_session``. ``wall_clock`` is
    #: SEPARATE from ``clock`` on purpose: monotonic for idle timing, wall-clock for
    #: the cross-process durable timestamp.
    run_id: str = ""
    progress_path: Optional[Path] = None
    wall_clock: Callable[[], float] = time.time

    steps: int = 0
    edits: int = 0
    steps_at_last_edit: int = 0
    failed_tool_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    event_count: int = 0
    last_event_monotonic: float = field(default=0.0)
    _seen_tool_calls: set[str] = field(default_factory=set)
    _tool_kind: dict[str, str] = field(default_factory=dict)
    _failed_ids: set[str] = field(default_factory=set)
    _fh: Any = None

    def __post_init__(self) -> None:
        self.last_event_monotonic = self.clock()
        if self.log_path is not None:
            self.log_path = Path(self.log_path)
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = self.log_path.open("a", encoding="utf-8", errors="replace")

    # -- ingestion ---------------------------------------------------------
    def on_session_update(self, payload: dict[str, Any]) -> None:
        """Fold one normalized ``session/update`` payload into the counts.

        Every payload — of any kind (tool_call, tool_call_update,
        agent_message_chunk, thought, plan, usage) — advances the liveness
        clock. Token/message activity WITHOUT a new discrete step keeps a
        candidate alive: emitting is working. The caveat the #790 battery
        surfaced is upstream of this method, not in it — opencode-acp does not
        reliably EMIT those heartbeats during a long generation window, so the
        idle bound (``ACP_IDLE_TIMEOUT_S``) must be generous enough to span one;
        this method resets on whatever DOES arrive."""
        self.event_count += 1
        self.last_event_monotonic = self.clock()
        self._write_transcript(payload)

        kind_of_update = payload.get("sessionUpdate")
        if kind_of_update == "tool_call":
            self._on_tool_call(payload)
        elif kind_of_update == "tool_call_update":
            self._on_tool_call_update(payload)
        # usage can arrive as its own event or ride a tool/message payload.
        if "usage" in payload or kind_of_update == "usage_update":
            self._on_usage(payload)

        # #844 C2 — refresh the durable coordinator-facing progress snapshot after
        # folding this event (additive + fail-soft; never affects the run).
        self._write_progress()

    def _on_tool_call(self, payload: dict[str, Any]) -> None:
        tcid = payload.get("toolCallId") or payload.get("id") or ""
        kind = (payload.get("kind") or "").lower()
        if tcid:
            self._tool_kind[tcid] = kind
        # Count a STEP once per distinct tool-call id (first sighting).
        if tcid and tcid in self._seen_tool_calls:
            self._maybe_mark_failed(tcid, payload.get("status"))
            return
        if tcid:
            self._seen_tool_calls.add(tcid)
        self.steps += 1
        if kind == _EDIT_KIND:
            self.edits += 1
            self.steps_at_last_edit = self.steps
        self._maybe_mark_failed(tcid, payload.get("status"))

    def _on_tool_call_update(self, payload: dict[str, Any]) -> None:
        tcid = payload.get("toolCallId") or payload.get("id") or ""
        # A late-arriving kind (opencode sometimes types the call on the update).
        kind = (payload.get("kind") or "").lower()
        if tcid and kind:
            # Reclassify a call that only NOW reveals it is an edit (and was
            # already counted as a step) -> credit the edit exactly once.
            if kind == _EDIT_KIND and self._tool_kind.get(tcid) != _EDIT_KIND \
                    and tcid in self._seen_tool_calls:
                self._tool_kind[tcid] = kind
                self.edits += 1
                self.steps_at_last_edit = self.steps
        self._maybe_mark_failed(tcid, payload.get("status"))

    def _maybe_mark_failed(self, tcid: str, status: Optional[str]) -> None:
        if status == "failed" and tcid and tcid not in self._failed_ids:
            self._failed_ids.add(tcid)
            self.failed_tool_calls += 1

    def _on_usage(self, payload: dict[str, Any]) -> None:
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else payload
        for key in ("inputTokens", "input_tokens", "promptTokens", "prompt_tokens"):
            val = usage.get(key)
            if isinstance(val, (int, float)):
                self.tokens_in = max(self.tokens_in, int(val))
                break
        for key in ("outputTokens", "output_tokens", "completionTokens", "completion_tokens"):
            val = usage.get(key)
            if isinstance(val, (int, float)):
                self.tokens_out = max(self.tokens_out, int(val))
                break

    # -- verdicts ----------------------------------------------------------
    def step_cap(self) -> StepCapDecision:
        return evaluate_step_cap(
            steps=self.steps, edits=self.edits,
            steps_at_last_edit=self.steps_at_last_edit,
            max_steps=self.max_steps, spin_steps=self.spin_steps,
        )

    def seconds_idle(self, now: Optional[float] = None) -> float:
        return (self.clock() if now is None else now) - self.last_event_monotonic

    def is_idle(self, now: Optional[float] = None, idle_timeout: float = ACP_IDLE_TIMEOUT_S) -> bool:
        return idle_exceeded(self.clock() if now is None else now, self.last_event_monotonic, idle_timeout)

    # -- durable coordinator-facing progress (#844 C2) ---------------------
    def _write_progress(self) -> None:
        """Durable, WALL-CLOCK progress snapshot for the COORDINATOR — a separate
        process that cannot see this tracker's monotonic clock. Additive +
        FAIL-SOFT: a write failure never affects the run (mirrors
        :meth:`_write_transcript`); the in-run idle/kill logic is untouched. The
        coordinator READS this to compose its cross-run operational view; the
        wall-clock stamp is what makes the age computable across processes."""
        if self.progress_path is None:
            return
        now_iso = datetime.fromtimestamp(self.wall_clock(), tz=timezone.utc).isoformat()
        acp_progress.write_acp_progress(
            acp_progress.AcpProgressSnapshot(
                run_id=self.run_id,
                last_event_at=now_iso,
                updated_at=now_iso,
                event_count=self.event_count,
                steps=self.steps,
                edits=self.edits,
                failed_tool_calls=self.failed_tool_calls,
                tokens_in=self.tokens_in,
                tokens_out=self.tokens_out,
            ),
            path=self.progress_path,
        )

    # -- transcript --------------------------------------------------------
    def _write_transcript(self, payload: dict[str, Any]) -> None:
        if self._fh is None:
            return
        try:
            rec = {"t_rel_s": round(self.clock() - 0.0, 4) if False else None,
                   "event": payload.get("sessionUpdate", "?"), "payload": payload}
            # Keep the transcript compact + one-line-per-event (grep-friendly,
            # like the stdin JSON transcript downstream tools already read).
            self._fh.write(json.dumps({"event": rec["event"], "payload": payload}, ensure_ascii=False) + "\n")
            self._fh.flush()
        except Exception:  # noqa: BLE001 — a transcript write must never break a run
            pass

    def write_line(self, line: str) -> None:
        """Append a raw provenance/diagnostic line to the transcript."""
        if self._fh is None:
            return
        try:
            self._fh.write(line.rstrip("\n") + "\n")
            self._fh.flush()
        except Exception:  # noqa: BLE001
            pass

    def close(self) -> None:
        if self._fh is not None:
            try:
                self._fh.close()
            except Exception:  # noqa: BLE001
                pass
            self._fh = None


# ---------------------------------------------------------------------------
# Own-cancel tracking — never trust StopReason (the opencode 1.17.8 fidelity gap).
# ---------------------------------------------------------------------------


@dataclass
class CancelState:
    """Tracks whether WE sent session/cancel and why — because opencode returns
    ``StopReason=end_turn`` on a cancel, not ``cancelled`` (#759 measurement).
    The result classification reads THIS, never the wire StopReason."""

    sent: bool = False
    reason: str = ""   # 'idle' | 'ceiling' | 'cap'

    def mark(self, reason: str) -> None:
        # First cause wins — a cap that then goes idle is still a cap.
        if not self.sent:
            self.sent = True
            self.reason = reason


def classify_result(
    *, tracker: AcpEventTracker, cancel: CancelState, elapsed_s: float,
    log_path: str, run_error: str = "",
) -> AcpRunResult:
    """Map the tracked state to the fleet result contract — PURE (no wire access).

    Precedence:
      1. a run-phase error (SDK raised AFTER handshake) -> Error set, ExitCode
         None, no timeout flags (the gate parks; we do NOT silently re-drive
         under stdin — that is only for pre-run import/handshake failure).
      2. we sent a cancel -> classify by OUR reason (never StopReason):
         'idle'/'ceiling' -> TimedOut; 'cap' -> Capped (work is on disk).
      3. the step cap tripped without a cancel (defensive) -> Capped.
      4. natural finish -> clean, ExitCode 0.
    """
    base = AcpRunResult(log_path=log_path, seconds=elapsed_s)
    if run_error:
        base.error = run_error
        base.exit_code = None
        return base
    if cancel.sent:
        if cancel.reason == "idle":
            base.timed_out = True
            base.timeout_reason = "idle"
            base.exit_code = None
        elif cancel.reason == "ceiling":
            base.timed_out = True
            base.timeout_reason = "ceiling"
            base.exit_code = None
        elif cancel.reason == "cap":
            base.capped = True
            base.capped_reason = tracker.step_cap().reason or "step cap"
            base.exit_code = 0
        return base
    cap = tracker.step_cap()
    if cap.capped:
        base.capped = True
        base.capped_reason = cap.reason
        base.exit_code = 0
        return base
    base.exit_code = 0
    return base


# ---------------------------------------------------------------------------
# The CLI envelope — how the PowerShell shim consumes a run.
# ---------------------------------------------------------------------------


def make_envelope(*, ok: bool, phase: str, fallback_to_stdin: bool,
                  result: Optional[AcpRunResult] = None, error: str = "") -> dict[str, Any]:
    """The JSON the shim reads. ``fallback_to_stdin`` is True ONLY for a
    pre-run import/handshake/spawn failure (ACP-01 §2 config-fallback); once the
    prompt has started we never silently re-drive the coder under stdin."""
    env: dict[str, Any] = {
        "ok": ok,
        "phase": phase,               # 'import' | 'spawn' | 'handshake' | 'run'
        "fallback_to_stdin": fallback_to_stdin,
        "error": error,
    }
    if result is not None:
        env["result"] = result.to_contract()
    return env


def _write_envelope(env: dict[str, Any], result_json: Optional[str]) -> None:
    payload = json.dumps(env, ensure_ascii=False)
    if result_json:
        try:
            Path(result_json).parent.mkdir(parents=True, exist_ok=True)
            Path(result_json).write_text(payload, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            print(f"acp_coder: could not write result-json: {exc}", file=sys.stderr, flush=True)
    # Also emit on stdout (last line) as a belt-and-suspenders channel.
    print(payload, flush=True)


def build_env(workdir: str) -> dict[str, str]:
    """The env opencode needs, mirroring Invoke-AgentRun (fleet-lib.ps1:344-384)
    and the #759 spike's build_env: pin git-bash (NOT WSL) and give the agent's
    own pytest the worktree root on PYTHONPATH."""
    env: dict[str, str] = {}
    git_bash = r"C:\Program Files\Git\bin\bash.exe"
    env["OPENCODE_GIT_BASH_PATH"] = git_bash
    env["SHELL"] = git_bash
    env["PYTHONPATH"] = workdir
    for k in ("USERPROFILE", "APPDATA", "LOCALAPPDATA", "PATH", "PATHEXT",
              "SYSTEMROOT", "SYSTEMDRIVE", "TEMP", "TMP", "HOMEDRIVE", "HOMEPATH",
              "USERNAME", "PROCESSOR_ARCHITECTURE"):
        v = os.environ.get(k)
        if v is not None:
            env[k] = v
    return env


def resolve_opencode_exe(explicit: Optional[str] = None) -> str:
    """The REAL compiled opencode.exe (not the .cmd/.ps1 npm shim). asyncio's
    subprocess spawn does not go through a shell, so it cannot resolve the shim —
    Invoke-AgentRun resolves this exact exe for the same reason
    (fleet-lib.ps1:355). Mirrors the #759 spike resolver."""
    if explicit and Path(explicit).exists():
        return explicit
    import subprocess  # local: keep module import cheap
    try:
        out = subprocess.run(["where.exe", "opencode"], capture_output=True, text=True, timeout=10)
        for line in out.stdout.splitlines():
            line = line.strip()
            if line.lower().endswith((".ps1", ".cmd")) or line.lower().endswith("opencode"):
                exe = Path(line).parent / "node_modules" / "opencode-ai" / "bin" / "opencode.exe"
                if exe.exists():
                    return str(exe)
    except Exception:  # noqa: BLE001
        pass
    cand = Path(os.environ.get("APPDATA", "")) / "npm" / "node_modules" / "opencode-ai" / "bin" / "opencode.exe"
    return str(cand) if cand.exists() else "opencode"


def normalize_model(model: str) -> str:
    """opencode wants provider/model; a bare OVMS id gets the local provider —
    exactly Invoke-AgentRun's ``if ($Model -notmatch '/') { "local/$Model" }``
    (fleet-lib.ps1:340)."""
    return model if (not model or "/" in model) else f"local/{model}"


# ---------------------------------------------------------------------------
# The LIVE run path — the only place ``acp`` is imported. Lazy by design.
# ---------------------------------------------------------------------------


def run_acp_coder(args: argparse.Namespace) -> dict[str, Any]:
    """Drive one opencode-acp coder session and return the CLI envelope.

    This is the ONLY entry that touches ``acp``. The import is lazy so the rest
    of the module (and the whole 3.11 gate) never needs the SDK; an ImportError
    is reported as a fall-back-to-stdin envelope, not a crash.
    """
    try:
        import acp  # noqa: F401 — lazy: 3.14-only SDK, absent on the 3.11 gate
    except Exception as exc:  # noqa: BLE001
        return make_envelope(
            ok=False, phase="import", fallback_to_stdin=True,
            error=f"acp SDK import failed ({type(exc).__name__}: {exc}); "
                  f"falling back to the stdin driver for this run",
        )
    import asyncio

    try:
        return asyncio.run(_run_acp_session(args))
    except Exception as exc:  # noqa: BLE001 — an unexpected crash is a run-phase error
        result = AcpRunResult(
            log_path=args.log_path, error=f"acp run crashed: {type(exc).__name__}: {exc}",
            exit_code=None,
        )
        return make_envelope(ok=True, phase="run", fallback_to_stdin=False, result=result)


async def _run_acp_session(args: argparse.Namespace) -> dict[str, Any]:
    """The async ACP conversation. Imports ``acp`` names locally (3.14 path)."""
    import asyncio
    import acp
    from acp import spawn_agent_process, text_block

    workdir = args.workdir
    model = normalize_model(args.model)
    log_path = args.log_path
    idle_timeout = float(args.idle_sec)
    overall_deadline = time.monotonic() + float(args.timeout_sec)
    prompt_text = Path(args.prompt_file).read_text(encoding="utf-8") if args.prompt_file else (args.prompt or "")

    exe = resolve_opencode_exe(args.opencode_exe)
    _log = Path(log_path)
    tracker = AcpEventTracker(
        log_path=_log, max_steps=int(args.max_steps), spin_steps=int(args.spin_steps),
        # #844 C2 — the coordinator reads runs_dir/<run_id>/acp-progress.json; the
        # per-run logs live in that same run dir, so derive both from the log path.
        run_id=_log.parent.name,
        progress_path=_log.with_name(acp_progress.ACP_PROGRESS_FILENAME),
    )
    cancel = CancelState()
    tracker.write_line(f"[acp-driver] opencode={exe} model={model} cwd={workdir} "
                       f"idle={idle_timeout}s ceiling={args.timeout_sec}s "
                       f"max_steps={args.max_steps} spin_steps={args.spin_steps}")

    # The live ACP client — defined HERE so every acp reference is inside the
    # 3.14 path. Duck-typed exactly like the #759 spike's RecordingClient: fs +
    # terminal capabilities OFF so opencode uses its OWN tools (matching
    # `opencode run`); permission requests auto-approved within the worktree.
    class _CoderClient:
        def __init__(self) -> None:
            self.start = time.monotonic()

        async def session_update(self, session_id: str, update: Any, **_: Any) -> None:
            try:
                payload = update.model_dump(mode="json", by_alias=True, exclude_none=True)
            except Exception:  # noqa: BLE001
                payload = {"sessionUpdate": "unknown", "_repr": repr(update)}
            tracker.on_session_update(payload)

        async def request_permission(self, session_id: str, tool_call: Any,
                                     options: list, **_: Any):
            from acp.schema import AllowedOutcome, RequestPermissionResponse
            chosen = None
            for pref in ("allow_once", "allow_always"):
                for opt in options:
                    if getattr(opt, "kind", None) == pref:
                        chosen = opt
                        break
                if chosen:
                    break
            if chosen is None and options:
                chosen = options[0]
            return RequestPermissionResponse(
                outcome=AllowedOutcome(outcome="selected", option_id=chosen.option_id)
            )

        # fs + terminal are declared OFF -> opencode must never call these.
        async def write_text_file(self, *a: Any, **k: Any):
            raise acp.RequestError.method_not_found("fs/write_text_file (capability OFF)")

        async def read_text_file(self, *a: Any, **k: Any):
            raise acp.RequestError.method_not_found("fs/read_text_file (capability OFF)")

        async def create_terminal(self, *a: Any, **k: Any):
            raise acp.RequestError.method_not_found("terminal (capability OFF)")

        async def terminal_output(self, *a: Any, **k: Any):
            raise acp.RequestError.method_not_found("terminal (capability OFF)")

        async def release_terminal(self, *a: Any, **k: Any):
            raise acp.RequestError.method_not_found("terminal (capability OFF)")

        async def wait_for_terminal_exit(self, *a: Any, **k: Any):
            raise acp.RequestError.method_not_found("terminal (capability OFF)")

        async def kill_terminal(self, *a: Any, **k: Any):
            raise acp.RequestError.method_not_found("terminal (capability OFF)")

        async def create_elicitation(self, *a: Any, **k: Any):
            raise acp.RequestError.method_not_found("elicitation unsupported")

        async def complete_elicitation(self, *a: Any, **k: Any) -> None:
            return None

        async def ext_method(self, method: str, params: dict) -> dict:
            return {}

        async def ext_notification(self, method: str, params: dict) -> None:
            return None

        def on_connect(self, conn: Any) -> None:
            self._conn = conn

    def _client_capabilities():
        from acp.schema import ClientCapabilities, FileSystemCapabilities, PlanCapabilities
        return ClientCapabilities(
            fs=FileSystemCapabilities(read_text_file=False, write_text_file=False),
            terminal=False, plan=PlanCapabilities(),
        )

    async def _watchdog(conn: Any, session_id: str) -> None:
        """Enforce the step-cap, the semantic idle bound, and the ceiling —
        cooperative cancel first (the spike's ~2.1 s clean stop), tree-kill last
        (on context exit). Never trusts StopReason; records the cause itself."""
        while True:
            await asyncio.sleep(1.0)
            if cancel.sent:
                return
            cap = tracker.step_cap()
            if cap.capped:
                cancel.mark("cap")
                tracker.write_line(f"[acp-driver] STEP CAP -> cancel ({cap.reason})")
            elif tracker.is_idle(idle_timeout=idle_timeout):
                cancel.mark("idle")
                tracker.write_line(f"[acp-driver] IDLE {tracker.seconds_idle():.0f}s "
                                   f">= {idle_timeout}s -> cancel")
            elif time.monotonic() >= overall_deadline:
                cancel.mark("ceiling")
                tracker.write_line("[acp-driver] CEILING reached -> cancel")
            if cancel.sent:
                try:
                    await conn.cancel(session_id=session_id)
                except Exception as exc:  # noqa: BLE001 — cancel is best-effort; tree-kill backstops
                    tracker.write_line(f"[acp-driver] session/cancel raised (tree-kill backstops): {exc}")
                return

    err_path = f"{log_path}.err"
    run_error = ""
    opencode_pid: Optional[int] = None
    started = time.monotonic()
    stderr_fh = open(err_path, "wb")  # noqa: SIM115 — handed to the transport
    try:
        try:
            async with spawn_agent_process(
                _CoderClient(), exe, "acp", "--print-logs", "--log-level", "INFO",
                env=build_env(workdir), cwd=workdir,
                transport_kwargs={"stderr": stderr_fh},
            ) as (conn, proc):
                opencode_pid = proc.pid
                try:
                    await asyncio.wait_for(
                        conn.initialize(protocol_version=acp.PROTOCOL_VERSION,
                                        client_capabilities=_client_capabilities()),
                        timeout=60.0)
                    sess = await conn.new_session(cwd=workdir)
                    session_id = sess.session_id
                except Exception as exc:  # noqa: BLE001 — pre-prompt failure -> fall back to stdin
                    return make_envelope(
                        ok=False, phase="handshake", fallback_to_stdin=True,
                        error=f"acp handshake/new_session failed ({type(exc).__name__}: {exc})")

                if model:
                    try:
                        await conn.set_config_option(config_id="model", session_id=session_id, value=model)
                    except Exception as exc:  # noqa: BLE001 — worktree opencode.json override still governs
                        tracker.write_line(f"[acp-driver] set_config_option(model) failed "
                                           f"(worktree override governs): {exc}")

                watch = asyncio.create_task(_watchdog(conn, session_id))
                try:
                    await conn.prompt(session_id=session_id, prompt=[text_block(prompt_text)])
                except Exception as exc:  # noqa: BLE001 — a mid-run SDK error is a run-phase error
                    run_error = f"acp prompt raised: {type(exc).__name__}: {exc}"
                finally:
                    watch.cancel()
        except Exception as exc:  # noqa: BLE001 — spawn/context failure before the prompt
            return make_envelope(
                ok=False, phase="spawn", fallback_to_stdin=True,
                error=f"acp spawn failed ({type(exc).__name__}: {exc})")
    finally:
        # Tree-kill teardown — the SDK close orphans opencode's node children
        # (the spike reaped 9). Reuse the blessed helper; import lazily so the
        # pure module carries no shared dependency at top level.
        if opencode_pid is not None:
            try:
                from shared.procspawn import terminate_process_tree
                killed = terminate_process_tree(opencode_pid)
                tracker.write_line(f"[acp-driver] tree-kill reaped {len(killed)} pid(s)")
            except Exception as exc:  # noqa: BLE001
                tracker.write_line(f"[acp-driver] tree-kill error: {exc}")
        try:
            stderr_fh.close()
        except Exception:  # noqa: BLE001
            pass
        # Fold opencode's stderr into the transcript (carries the plugin
        # load-lines the #762 canary reads), then drop the temp file — mirrors
        # Invoke-AgentRun's stderr fold (fleet-lib.ps1:466-468).
        try:
            if Path(err_path).exists():
                tracker.write_line("[acp-driver] --- opencode stderr ---")
                tracker.write_line(Path(err_path).read_text(encoding="utf-8", errors="replace"))
                Path(err_path).unlink()
        except Exception:  # noqa: BLE001
            pass
        tracker.close()

    elapsed = time.monotonic() - started
    result = classify_result(tracker=tracker, cancel=cancel, elapsed_s=elapsed,
                             log_path=log_path, run_error=run_error)
    return make_envelope(ok=True, phase="run", fallback_to_stdin=False, result=result)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m tools.dispatch_harness.acp_coder",
        description="ACP coder driver (#775) — drives one opencode-acp session, "
                    "returns the Invoke-CandidateBuild result contract.")
    p.add_argument("--workdir", required=True, help="the coder worktree (cwd for opencode)")
    p.add_argument("--model", default="local/coder-30b")
    p.add_argument("--log-path", required=True, help="transcript sink (LogPath in the contract)")
    grp = p.add_mutually_exclusive_group(required=True)
    grp.add_argument("--prompt")
    grp.add_argument("--prompt-file")
    p.add_argument("--timeout-sec", type=float, default=3600.0, help="the ceiling (MaxRunMinutes*60)")
    p.add_argument("--idle-sec", type=float, default=ACP_IDLE_TIMEOUT_S)
    p.add_argument("--max-steps", type=int, default=ACP_MAX_STEPS)
    p.add_argument("--spin-steps", type=int, default=ACP_SPIN_STEPS)
    p.add_argument("--opencode-exe", default=None, help="explicit opencode.exe (else auto-resolve)")
    p.add_argument("--result-json", default=None, help="where to write the envelope (the shim reads this)")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    env = run_acp_coder(args)
    _write_envelope(env, args.result_json)
    # Exit 0 regardless: the envelope carries the outcome; a non-zero exit would
    # just make the shim fall back to stdin, which is only correct for the
    # explicit fallback_to_stdin cases (already signalled in the envelope).
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
