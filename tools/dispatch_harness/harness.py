"""The headless gateway driver — :class:`DispatchHarness`.

Drives the SAME ``/dispatch`` flow the WinUI drives, but with no GUI:

    /dispatch <repo> | <goal>   -> PLAN preview (or an Inc-4 clarifying question first)
    /dispatch <n>               -> answer the clarifying question (if asked)
    /dispatch approve           -> EXECUTE (the only path that fires work)
    [monitor the run]           -> stop-doomed-fast, else read the SUMMARY outcome

It reuses the real :class:`DispatchCoordinator` (via the real
:class:`~services.ui_gateway.src.transport.TransportGateway` in LIVE mode, or an injected
coordinator + fake fleet dir in DRY-RUN/tests). It is a headless WinUI, NOT a second
implementation: it sends the same command strings and reads the same replies.

Two modes:

* **LIVE** — build the real ``TransportGateway`` over **production mutual-TLS by default**
  (``dev_mode=False``, ``host_mode=True``, the per-boot mTLS chain the launcher wrote to
  ``<repo>/certs`` per ADR-026; port from the AO config, ``fleet_dispatch_enabled``, the
  agentic-setup/projects roots). ``dev_mode=True`` keeps the old plaintext loopback for a dev-mode
  AO. The coordinator's PLAN/EXECUTE seams open their own connections to the running AO at
  ``:5001``. The harness fails clearly if the certs are absent, if it cannot reach the AO, or if
  dispatch is disabled. The model swap happens AO-side; the harness then monitors the run via
  :class:`RunMonitor` and stops a doomed run with ``/dispatch stop``.
* **DRY-RUN** — drive a real ``DispatchCoordinator`` wired to injected ``plan_fn``/``execute_fn``
  + a fake fleet-run ``FleetDispatchConfig``; ``execute_fn`` writes a fake ``SUMMARY.txt`` so the
  monitor returns COMPLETE without the GPU. Proves the whole flow off-live.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from services.ui_gateway.src.dispatch_coordinator import (
    DispatchCommand,
    DispatchCoordinator,
)
from services.ui_gateway.src.transport import TransportGateway
from shared.fleet.dispatch import FleetDispatchConfig, latest_run_id

from tools.dispatch_harness.clarify import pick_clarify_answer
from tools.dispatch_harness.jobs import JobSpec
from tools.dispatch_harness.monitor import DoomVerdict, MonitorResult, RunMonitor
from tools.dispatch_harness.report import JobReport, SweepReport

# A reply that contains this marker is a clarifying question awaiting an option number.
_CLARIFY_MARKER = "Reply with the number"
# A successful PLAN preview always offers approve/reject.
_APPROVE_MARKER = "/dispatch approve"
# The EXECUTE reply leads with "Dispatching <run_id> — N task(s)".
_RUN_ID_RE = re.compile(r"Dispatching\s+(\S+)\s+—\s+\d+\s+task", re.UNICODE)


@dataclass
class DispatchHarness:
    """Drives the ``/dispatch`` pipeline for one or many jobs.

    Construct via :meth:`for_live` (the real gateway) or :meth:`for_dry_run` (injected fakes);
    the body is mode-agnostic — it only ever calls :meth:`_send` (a ``handle_dispatch_command``)
    and builds a :class:`RunMonitor`.
    """

    # ``send_fn(session_id, text) -> reply`` — the real gateway.handle_dispatch_command, or a
    # thin wrapper over an injected coordinator (dry-run/tests).
    send_fn: Callable[[str, str], Awaitable[str | None]]
    config: FleetDispatchConfig
    coordinator: DispatchCoordinator | None = None  # for direct run_id introspection (optional)
    session_id: str = "harness"
    default_clarify_answer: str = "1"
    dry_run: bool = False
    # #749: when True (and config.vikunja_bridge is on), run_job posts the driver's
    # per-job outcome to the durable Vikunja ticket after adopting the scorecard.
    # Default False. The battery keeps this OFF and owns the AUTHORITATIVE post
    # itself (after its FALSE-DONE cross-check), so a battery job posts exactly one
    # outcome comment — never two. A standalone/real-dispatch caller opts in.
    report_outcomes_to_vikunja: bool = False
    # Monitoring knobs (defaults match the production swap_run_budget_s ceiling; 10800 per #757).
    poll_interval_s: float = 5.0
    # 90 -> 240 (2026-07-09 night B4 false-doom; family with RunMonitor.stall_grace_s —
    # the [3/5] verify gate's 600 s budget contains legitimately CPU-quiet, log-quiet gaps).
    stall_grace_s: float = 240.0
    overall_timeout_s: float = 10800.0
    # Monitor injectables (tests override clock/sleep/cpu probe; dry-run uses a fast monitor).
    monitor_factory: Callable[..., RunMonitor] | None = None
    log: Callable[[str], None] = print

    # ── construction ──────────────────────────────────────────────────────

    @classmethod
    def for_live(
        cls,
        *,
        port: int,
        agentic_setup_dir: str,
        projects_dir: str,
        fleet_dispatch_enabled: bool = True,
        dev_mode: bool = False,
        certs_dir: str | None = None,
        session_id: str = "harness",
        default_clarify_answer: str = "1",
        poll_interval_s: float = 5.0,
        stall_grace_s: float = 240.0,
        overall_timeout_s: float = 10800.0,
        log: Callable[[str], None] = print,
    ) -> "DispatchHarness":
        """Build a harness over the REAL ``TransportGateway`` (LIVE mode).

        LIVE defaults to **production mutual-TLS** (``dev_mode=False``): the gateway connects to
        the running AO over loopback + the per-boot mTLS chain the launcher provisioned into
        ``<repo_root>/certs/`` (ADR-026), exactly as the real WinUI does. The three cert paths
        (gateway client cert + key + CA) are resolved from the canonical
        :mod:`shared.security.cert_provisioning` filenames and **asserted present** — if any is
        missing the harness fails closed (production always requires mTLS; the certs only exist
        when BlarAI is running in production mode so the launcher has minted them).

        ``dev_mode=True`` preserves the original DRY-RUN/test wiring: loopback, NO mTLS (plaintext
        dev path) — used only when driving a dev-mode AO.

        The fleet-dispatch settings are threaded exactly as the launcher threads them. No session
        store (the harness does not persist conversation; the informational-turn persist in
        ``handle_dispatch_command`` no-ops without a store).

        Args:
            port: The AO's loopback port (read from the AO ``default.toml`` ``[ipc].vsock_port``).
            agentic_setup_dir / projects_dir: Fleet-dispatch roots (launcher-equivalent threading).
            fleet_dispatch_enabled: Whether dispatch is enabled (the running AO is the SSOT).
            dev_mode: ``False`` (default) = production loopback + mTLS; ``True`` = plaintext dev
                      loopback (the prior behavior — no cert paths).
            certs_dir: Override for the per-boot certs directory. ``None`` (default) resolves to
                       ``<repo_root>/certs``. Ignored in ``dev_mode``.
        """
        from shared.fleet.dispatch import build_default_config

        if dev_mode:
            # Plaintext dev/test loopback — the original behavior, byte-for-byte.
            gateway = TransportGateway(
                session_store=None,
                dev_mode=True,
                host="127.0.0.1",
                port=port,
                fleet_dispatch_enabled=fleet_dispatch_enabled,
                fleet_dispatch_agentic_setup_dir=agentic_setup_dir,
                fleet_dispatch_projects_dir=projects_dir,
            )
        else:
            # Production: loopback + per-boot mTLS (ADR-026). Resolve the launcher-written certs
            # and fail closed if they are absent — production never connects without mTLS.
            from shared.security.cert_provisioning import (
                CA_CERT_NAME,
                DEFAULT_CERTS_DIR,
                GATEWAY_CLIENT_CERT_NAME,
                GATEWAY_CLIENT_KEY_NAME,
            )

            if certs_dir is not None:
                certs_root = Path(certs_dir)
            else:
                repo_root = Path(__file__).resolve().parents[2]
                certs_root = repo_root / DEFAULT_CERTS_DIR

            client_cert = certs_root / GATEWAY_CLIENT_CERT_NAME
            client_key = certs_root / GATEWAY_CLIENT_KEY_NAME
            ca_cert = certs_root / CA_CERT_NAME

            missing = [
                str(p)
                for p in (client_cert, client_key, ca_cert)
                if not p.is_file()
            ]
            if missing:
                raise FileNotFoundError(
                    "LIVE dispatch needs the per-boot mTLS certs the launcher provisions, but "
                    f"these are missing under {certs_root}: {', '.join(missing)}. "
                    "Start BlarAI in PRODUCTION mode (not dev_mode) so the launcher mints the "
                    "per-boot certs (ADR-026) at this path, or pass --dev-mode to use the "
                    "plaintext dev loopback against a dev-mode AO."
                )

            gateway = TransportGateway(
                session_store=None,
                dev_mode=False,
                host="127.0.0.1",
                port=port,
                host_mode=True,
                mtls_cert_path=str(client_cert),
                mtls_key_path=str(client_key),
                ca_cert_path=str(ca_cert),
                fleet_dispatch_enabled=fleet_dispatch_enabled,
                fleet_dispatch_agentic_setup_dir=agentic_setup_dir,
                fleet_dispatch_projects_dir=projects_dir,
            )

        config = build_default_config(
            agentic_setup_dir or None, projects_dir or None
        )
        coordinator = getattr(gateway, "_dispatch_coordinator", None)
        return cls(
            send_fn=gateway.handle_dispatch_command,
            config=config,
            coordinator=coordinator,
            session_id=session_id,
            default_clarify_answer=default_clarify_answer,
            dry_run=False,
            poll_interval_s=poll_interval_s,
            stall_grace_s=stall_grace_s,
            overall_timeout_s=overall_timeout_s,
            log=log,
        )

    @classmethod
    def for_dry_run(
        cls,
        *,
        config: FleetDispatchConfig,
        plan_fn: Callable[[str, str], Awaitable],
        execute_fn: Callable[..., Awaitable],
        mint_run_id: Callable[[], str] | None = None,
        session_id: str = "harness",
        default_clarify_answer: str = "1",
        monitor_factory: Callable[..., RunMonitor] | None = None,
        log: Callable[[str], None] = print,
    ) -> "DispatchHarness":
        """Build a harness over a real :class:`DispatchCoordinator` wired to injected fakes.

        ``plan_fn`` / ``execute_fn`` are the fake AO; ``config`` points at a fake fleet-run dir.
        ``execute_fn`` is expected to write a ``SUMMARY.txt`` into ``config.runs_dir/<run_id>/`` so
        the monitor returns COMPLETE. ``monitor_factory`` lets a test pass a fast (no-sleep)
        monitor; the default uses a short poll/grace so a dry-run finishes immediately."""
        coordinator = DispatchCoordinator(
            config=config,
            enabled=True,
            plan_fn=plan_fn,
            execute_fn=execute_fn,
            mint_run_id=(mint_run_id or (lambda: "DRYRUN-RID")),
        )

        async def _send(session: str, text: str) -> str:
            cmd = __import__(
                "services.ui_gateway.src.dispatch_coordinator",
                fromlist=["parse_dispatch_command"],
            ).parse_dispatch_command(text)
            if cmd is None:
                return ""
            return await coordinator.handle_command(session, cmd)

        return cls(
            send_fn=_send,
            config=config,
            coordinator=coordinator,
            session_id=session_id,
            default_clarify_answer=default_clarify_answer,
            dry_run=True,
            poll_interval_s=0.0,
            stall_grace_s=1.0,
            overall_timeout_s=30.0,
            monitor_factory=monitor_factory,
            log=log,
        )

    # ── driving one job ───────────────────────────────────────────────────

    async def _send(self, text: str) -> str:
        reply = await self.send_fn(self.session_id, text)
        return reply or ""

    def _stop_fn(self) -> Callable[[], None]:
        """A ``/dispatch stop`` callable for the monitor (clean abort of an executing run)."""

        def _stop() -> None:
            try:
                asyncio.run(self._send("/dispatch stop"))
            except RuntimeError:
                # Already inside an event loop (shouldn't happen — the monitor runs in a worker
                # thread) — schedule on a fresh loop.
                loop = asyncio.new_event_loop()
                try:
                    loop.run_until_complete(self._send("/dispatch stop"))
                finally:
                    loop.close()

        return _stop

    def _make_monitor(self, run_id: str) -> RunMonitor:
        if self.monitor_factory is not None:
            return self.monitor_factory(
                config=self.config, run_id=run_id, stop_fn=self._stop_fn(), log=self.log
            )
        kwargs: dict = dict(
            config=self.config,
            run_id=run_id,
            poll_interval_s=self.poll_interval_s,
            stall_grace_s=self.stall_grace_s,
            overall_timeout_s=self.overall_timeout_s,
            stop_fn=self._stop_fn(),
            log=self.log,
        )
        if self.dry_run:
            # No real coder process — short-circuit the CPU probe to "idle" so a fake run that
            # never writes more progress is judged purely on the SUMMARY/stall, and don't sleep.
            kwargs["proc_cpu_probe"] = lambda: False
            kwargs["cpu_sample_s"] = 0.0
        return RunMonitor(**kwargs)

    def _resolve_run_id(self, approve_reply: str) -> str:
        """Get the run id: prefer the coordinator's just-cleared pending slot's id captured before
        approve; else parse the EXECUTE reply; else the latest run under the runs dir."""
        m = _RUN_ID_RE.search(approve_reply or "")
        if m:
            return m.group(1)
        try:
            rid = latest_run_id(config=self.config)
        except Exception:  # noqa: BLE001
            rid = None
        return rid or ""

    async def run_job(self, job: JobSpec) -> JobReport:
        """Drive ONE job end-to-end and return its :class:`JobReport`."""
        report = JobReport(repo=job.repo, goal=job.goal, expected=job.expected)
        started = time.monotonic()

        # 1) PLAN.
        plan_reply = await self._send(job.command)
        report.plan_preview = _first_lines(plan_reply, 3)

        # 2) Inc-4 clarifying question (only if asked).
        if _is_clarifying_question(plan_reply):
            report.asked_clarifying = True
            answer = pick_clarify_answer(
                plan_reply, job.clarify_answer, default=self.default_clarify_answer
            )
            report.answered = answer
            self.log(f"[{job.repo}] clarifying question asked -> answering /dispatch {answer}")
            plan_reply = await self._send(f"/dispatch {answer}")
            report.plan_preview = _first_lines(plan_reply, 3)

        # Did PLAN actually produce an approvable preview?
        if _APPROVE_MARKER not in plan_reply:
            report.error = _plan_failure_summary(plan_reply)
            report.wall_clock_s = time.monotonic() - started
            self.log(f"[{job.repo}] PLAN did not yield an approvable preview: {report.error}")
            return report
        report.plan_ok = True

        # Capture the minted run id from the coordinator's pending slot BEFORE approve clears it
        # (the most reliable source; the EXECUTE reply is the fallback).
        pre_run_id = ""
        if self.coordinator is not None:
            pending = self.coordinator.pending_for(self.session_id)
            if pending is not None:
                pre_run_id = pending.run_id

        # 3) APPROVE → EXECUTE.
        approve_reply = await self._send("/dispatch approve")
        run_id = pre_run_id or self._resolve_run_id(approve_reply)
        report.run_id = run_id
        if not _approve_succeeded(approve_reply):
            report.error = f"approve did not fire EXECUTE: {_first_lines(approve_reply, 2)}"
            report.wall_clock_s = time.monotonic() - started
            self.log(f"[{job.repo}] approve failed: {report.error}")
            return report
        report.approved = True
        self.log(f"[{job.repo}] approved — run_id={run_id or '(unknown)'}; monitoring…")

        # 4) MONITOR (stop-doomed-fast).
        if not run_id:
            report.error = "approved but could not determine the run id to monitor"
            report.wall_clock_s = time.monotonic() - started
            return report
        monitor = self._make_monitor(run_id)
        result: MonitorResult = await asyncio.to_thread(monitor.run)
        report.verdict = result.verdict.value
        report.outcome = result.outcome
        report.stop_reason = result.stop_reason
        report.progress_tail = result.progress_tail
        # #748: adopt the DRIVER's job-level verdict from the run's scorecard.json
        # when the plan-graph driver emitted one — the report must carry the JOB
        # truth (PARKED-HONEST/GREEN/…) first-class, not just run-health. Fail-soft:
        # legacy runs have no scorecard and the fields stay "".
        driver_sc: dict | None = None
        try:
            sc_path = self.config.runs_dir / run_id / "scorecard.json"
            if sc_path.is_file():
                sc = json.loads(sc_path.read_text(encoding="utf-8"))
                if isinstance(sc, dict):
                    driver_sc = sc
                    report.job_verdict = str(sc.get("verdict", "") or "")
                    report.job_attribution = str(sc.get("attribution", "") or "")
        except Exception:  # noqa: BLE001 — a bad scorecard must not sink the report
            pass
        report.wall_clock_s = time.monotonic() - started
        # #749 post-adoption: publish this job's outcome to its durable Vikunja
        # ticket (opt-in + knob-gated; the battery leaves report_outcomes_to_vikunja
        # OFF and posts its own cross-checked verdict instead). Wholly fail-soft.
        self._maybe_report_to_vikunja(report, driver_sc)
        self.log(
            f"[{job.repo}] done — verdict={report.verdict} outcome={report.outcome or '—'} "
            + (f"job={report.job_verdict} " if report.job_verdict else "")
            + f"({report.wall_clock_s:.0f}s)"
        )
        return report

    def _maybe_report_to_vikunja(self, report: JobReport, driver_sc: dict | None) -> None:
        """#749: ensure-and-update this job's durable Vikunja ticket from the driver
        scorecard. Opt-in (``report_outcomes_to_vikunja``) AND knob-gated
        (``config.vikunja_bridge``); a no-op without a driver scorecard (no verdict
        to report). Wholly fail-soft — the bridge swallows its own errors, and this
        wrapper never raises into the run."""
        if not self.report_outcomes_to_vikunja:
            return
        if not getattr(self.config, "vikunja_bridge", False):
            return
        if not driver_sc or not report.run_id:
            return
        try:
            from shared.fleet import vikunja_bridge as vb

            ticket_id = vb.ensure_job_ticket(
                self.config, report.run_id, report.goal, report.repo
            )
            if ticket_id is not None:
                vb.post_outcome(self.config, ticket_id, driver_sc)
        except Exception as exc:  # noqa: BLE001 — ticket I/O never affects a run
            self.log(f"[{report.repo}] vikunja ticket update skipped (fail-soft): {exc}")

    async def run_sweep(self, jobs: list[JobSpec]) -> SweepReport:
        """Drive every job in order, accumulating a :class:`SweepReport`."""
        sweep = SweepReport(dry_run=self.dry_run)
        for job in jobs:
            try:
                sweep.add(await self.run_job(job))
            except Exception as exc:  # noqa: BLE001 — one job's crash must not sink the sweep
                self.log(f"[{job.repo}] job crashed: {exc}")
                sweep.add(
                    JobReport(repo=job.repo, goal=job.goal, expected=job.expected,
                              error=f"harness exception: {exc}")
                )
        return sweep


# ---------------------------------------------------------------------------
# Small pure reply helpers (unit-tested directly)
# ---------------------------------------------------------------------------


def _is_clarifying_question(reply: str) -> bool:
    """True when a PLAN reply is an Inc-4 clarifying question (awaiting an option number)."""
    r = reply or ""
    return _CLARIFY_MARKER in r and _APPROVE_MARKER not in r


def _approve_succeeded(reply: str) -> bool:
    """True when an approve reply indicates EXECUTE fired (vs a refusal/wiring/disabled notice)."""
    r = (reply or "").lower()
    if "dispatching" in r:
        return True
    # Known failure shells the coordinator returns on a non-firing approve.
    return False


def _plan_failure_summary(reply: str) -> str:
    """A short reason a PLAN did not yield an approvable preview (disabled / wiring / refusal)."""
    r = reply or ""
    low = r.lower()
    if "off" in low and "dormant" in low:
        return "dispatch is disabled (the AO's [fleet_dispatch].enabled is false)"
    if "wiring" in low and "go-live" in low:
        return "dispatch enabled but plan/execute wiring is not connected (go-live pending)"
    if "could not connect" in low:
        return "could not connect to the Assistant Orchestrator (is it running on :5001?)"
    return _first_lines(r, 2) or "PLAN returned no approvable preview"


def _first_lines(text: str, n: int) -> str:
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    return " / ".join(lines[:n])
