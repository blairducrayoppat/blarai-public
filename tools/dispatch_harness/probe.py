"""Probe-not-predict swap admission (#784).

The battery night launcher (``agentic-setup/scripts/run-battery-night.ps1``, the
"LEAN PREFLIGHT" section) used to admit the night by ARITHMETIC: project the
post-unload headroom (current Available + the 14B's ~8.7 GiB that returns when the
AO steps aside) and proceed only if that projection clears a 20.5 GiB gate (the
swap driver's own 20.0 GiB gate + margin). Below the gate it waited on 30-minute
retries to 04:00.

The #777 measurement proved a clean 30B load from **19.85 GiB** available. So the
arithmetic gate has a DEAD BAND — roughly 19.85 to 20.5 GiB — where the launcher
waits all night on a load that would actually work. Raising or lowering the
predicted threshold only moves the argument (20 vs 18 vs 17.5); it never ends it,
because the prediction is a proxy for a thing we can just MEASURE.

This module measures it. In the marginal band the launcher calls the probe, which
attempts the REAL 30B load ONCE, **outside any job** — so no verdict can ever be
stamped on the attempt — bounded by the same 04:00 deadline and a graceful,
always-restore abort. Probe succeeds -> run the night for real. Probe fails ->
restore the AO, clean up, and rejoin the retry loop. A failed load INSIDE a job is
what makes a night unbankable (a STALLED scorecard); a failed load in the probe
costs only one warm ~13 s attempt and a re-boot.

Side-effect discipline (lesson 224): every side-effecting step REUSES an audited
leg from ``shared/fleet/swap_ops.py`` / ``tools/dispatch_harness/battery.py`` —
the probe adds no new subprocess op. Critically, the probe **stamps NOTHING**: it
never writes swap-state, a scorecard, a phase, or the fleet sentinel. The only
files it touches are diagnostic logs (start-llm's own log, an AO re-boot log). It
is a measurement, not a run.

    python -m tools.dispatch_harness.probe --min-free-gb 15.0 --json

Exit codes (the launcher branches on these):
  0  READY        — the 30B loaded and served within the deadline (AO restored)
  1  LOAD_FAILED  — the load failed or was aborted (AO restored)
  2  ERROR        — an unexpected error (AO restored best-effort)
  3  BELOW_FLOOR  — Available < --min-free-gb; nothing was attempted, no side effects
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

#: ``tools/dispatch_harness/probe.py`` -> the blarai checkout root (parents[2]),
#: the cwd for a re-booted ``python -m launcher`` (mirrors battery._BLARAI_REPO_ROOT).
_BLARAI_REPO_ROOT = Path(__file__).resolve().parents[2]

#: The coder-30B serves here (OVMS local socket); the production AO serves here.
_OVMS_PORT = 8000
_AO_PORT = 5001

PROBE_SCHEMA = "probe/v1"

# Exit codes / outcome labels (stable — the --json line and the PS caller read them).
EXIT_READY = 0
EXIT_LOAD_FAILED = 1
EXIT_ERROR = 2
EXIT_BELOW_FLOOR = 3


@dataclass(frozen=True)
class ProbeResult:
    """The probe's machine-readable outcome (community-grade perf capture + the PS caller)."""

    exit_code: int
    outcome: str
    available_gb: float
    min_free_gb: float
    load_seconds: float = 0.0
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "schema": PROBE_SCHEMA,
            "outcome": self.outcome,
            "exit_code": self.exit_code,
            "available_gb": round(self.available_gb, 2),
            "min_free_gb": round(self.min_free_gb, 2),
            "load_seconds": round(self.load_seconds, 1),
            "detail": self.detail,
        }

    def json_line(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


@dataclass
class ProbeOps:
    """The injected side-effecting seams — every effect is a callable, so ``run_probe``
    is unit-testable with no socket, no process, no GPU (the AoReensurer / SwapOps
    pattern). ``build_real_probe_ops`` wires the live legs; tests pass fakes."""

    available_gb: Callable[[], float]
    stop_ao: Callable[[], dict]
    load_30b: Callable[[], bool]
    wait_ready: Callable[[], bool]
    restore: Callable[[], None]
    log: Callable[[str], None] = lambda _m: None
    clock: Callable[[], float] = time.monotonic


def run_probe(ops: ProbeOps, *, min_free_gb: float, timeout_s: float) -> ProbeResult:
    """Attempt one real 30B load OUTSIDE any job, always restoring the AO.

    Sequence (pure over ``ops`` — no real imports here):

      1. measure Available (the same source the driver's gate reads);
      2. below ``min_free_gb`` -> exit 3, NOTHING attempted (no stop, no load, no
         restore — the below-floor path must have ZERO side effects);
      3. otherwise: stop the AO (frees the resident 14B), load the 30B, wait for it
         to serve; READY iff both succeed within the budget;
      4. ALWAYS restore the AO (finally, even on abort/exception). A restore that
         RAISES is LOUD but the exit code is preserved (never masked by the finally).

    ``timeout_s`` bounds the readiness proof after the load. The underlying start-llm
    block has its own ceiling (``START_LLM_TIMEOUT_S``); the launcher defaults
    ``timeout_s`` to that same constant so the two agree."""
    available = float(ops.available_gb())
    if available < min_free_gb:
        ops.log(
            f"probe: Available {available:.1f} GiB < floor {min_free_gb:.1f} GiB — "
            "below the sanity bound; NOT attempting a load (nothing touched)."
        )
        return ProbeResult(
            exit_code=EXIT_BELOW_FLOOR,
            outcome="BELOW_FLOOR",
            available_gb=available,
            min_free_gb=min_free_gb,
            detail=f"Available {available:.1f} GiB below the {min_free_gb:.1f} GiB floor",
        )

    # Past the floor: we are committing to the attempt, so the AO WILL be stopped and
    # therefore MUST be restored — set this before stop_ao so a stop that partially
    # fired is still followed by a restore (restore is safe/idempotent).
    must_restore = True
    load_seconds = 0.0
    try:
        ops.log(
            f"probe: Available {available:.1f} GiB >= floor {min_free_gb:.1f} GiB — "
            "probing a real 30B load (outside any job; no verdict can be stamped)."
        )
        stop_info = ops.stop_ao()
        ops.log(f"probe: AO stop -> {stop_info}")
        t0 = ops.clock()
        loaded = bool(ops.load_30b())
        ready = bool(ops.wait_ready()) if loaded else False
        load_seconds = ops.clock() - t0
        if loaded and ready:
            ops.log(f"probe: 30B READY in {load_seconds:.1f}s — the night can run.")
            return ProbeResult(
                exit_code=EXIT_READY,
                outcome="READY",
                available_gb=available,
                min_free_gb=min_free_gb,
                load_seconds=load_seconds,
                detail=f"30B loaded and served in {load_seconds:.1f}s",
            )
        reason = "load returned failure" if not loaded else "loaded but never served within the budget"
        ops.log(f"probe: 30B load FAILED ({reason}) after {load_seconds:.1f}s — will rejoin the retry loop.")
        return ProbeResult(
            exit_code=EXIT_LOAD_FAILED,
            outcome="LOAD_FAILED",
            available_gb=available,
            min_free_gb=min_free_gb,
            load_seconds=load_seconds,
            detail=reason,
        )
    except KeyboardInterrupt:
        # Graceful abort (deadline reaper / operator Ctrl-C): treated as a load abort,
        # NOT an unexpected error. The restore still runs in finally.
        ops.log("probe: ABORTED (interrupt) — restoring the AO and rejoining the retry loop.")
        return ProbeResult(
            exit_code=EXIT_LOAD_FAILED,
            outcome="ABORTED",
            available_gb=available,
            min_free_gb=min_free_gb,
            load_seconds=load_seconds,
            detail="aborted before the load proved ready",
        )
    except Exception as exc:  # noqa: BLE001 — unexpected: report exit 2, still restore
        ops.log(f"probe: unexpected error ({type(exc).__name__}: {exc}) — restoring the AO.")
        return ProbeResult(
            exit_code=EXIT_ERROR,
            outcome="ERROR",
            available_gb=available,
            min_free_gb=min_free_gb,
            load_seconds=load_seconds,
            detail=f"{type(exc).__name__}: {exc}",
        )
    finally:
        if must_restore:
            try:
                ops.restore()
            except Exception as exc:  # noqa: BLE001 — LOUD, but never mask the exit code
                ops.log(
                    "probe: RESTORE RAISED — the AO may be down; the battery's per-job "
                    f"AoReensurer is the backstop (exit code preserved): {exc}"
                )


# ---------------------------------------------------------------------------
# The live wiring — every side-effecting step is an EXISTING audited leg.
# ---------------------------------------------------------------------------


def _real_stop_ao(repo_root: Path, log: Callable[[str], None]) -> dict:
    """Stop the production AO so its resident 14B frees the RAM the 30B needs.

    The driver never kills the AO — in a real swap the AO STEPS ASIDE (exits itself)
    and the driver waits on its PID. The probe cannot trigger that in-process
    step-aside on a separate live AO, so it finds the launcher by its single-instance
    lock (``certs/launcher.lock`` — the authoritative pid the launcher records at
    boot), CONFIRMS it is genuinely a ``-m launcher`` process (never a recycled pid),
    and tree-kills it via the audited ``shared.procspawn.terminate_process_tree``
    (psutil-first; a bare ``taskkill`` only as the psutil-absent fallback — never a
    blind pid kill). A forceful stop skips the launcher's graceful cleanup and leaves
    a stale lock, exactly like the driver's ``os._exit`` step-aside path — the next
    ``boot_launcher_detached`` reclaims the stale lock. Stamps nothing."""
    from launcher.instance_lock import (
        _is_live_launcher,
        _read_holder_pid,
        lock_path_for_repo,
    )
    from shared.procspawn import terminate_process_tree

    lock = lock_path_for_repo(repo_root)
    pid = _read_holder_pid(lock)
    if not pid or pid <= 0:
        log("probe: no launcher instance-lock pid — the AO looks already-down; nothing to stop.")
        return {"stopped": False, "pid": 0, "reason": "no-lock-pid"}
    if not _is_live_launcher(pid):
        log(f"probe: instance-lock pid {pid} is not a live '-m launcher' (stale) — nothing to stop.")
        return {"stopped": False, "pid": int(pid), "reason": "stale-pid"}
    targeted = terminate_process_tree(int(pid))
    return {"stopped": True, "pid": int(pid), "targeted": list(targeted)}


def _real_restore(
    config,
    repo_root: Path,
    *,
    ao_port: int,
    reboot_log: Path,
    log: Callable[[str], None],
) -> None:
    """ALWAYS-RESTORE: stop the 30B's OVMS, re-boot the AO the SAME detached way the
    battery preflight does, then NON-FATALLY wait for :5001. Every step is wrapped so
    a restore failure is loud but never raises out of the caller's finally."""
    from shared.fleet.swap_ops import real_backend_ready, real_stop_ovms
    from tools.dispatch_harness.battery import boot_launcher_detached

    try:
        log("probe restore: stopping OVMS (the 30B) ...")
        real_stop_ovms()
    except Exception as exc:  # noqa: BLE001 — loud, continue to the AO re-boot
        log(f"probe restore: real_stop_ovms error (continuing): {exc}")
    try:
        log("probe restore: re-booting the AO (python -m launcher, production, detached) ...")
        boot_launcher_detached(repo_root, reboot_log, port=ao_port, log=log)
    except Exception as exc:  # noqa: BLE001 — loud, still try the readiness wait
        log(f"probe restore: AO re-boot spawn error: {exc}")
    try:
        up = real_backend_ready(port=ao_port)
        if up:
            log(f"probe restore: AO up on :{ao_port}.")
        else:
            log(
                f"probe restore: AO NOT up on :{ao_port} within the readiness wait — "
                "NON-FATAL; the battery's per-job AoReensurer re-boots as the backstop."
            )
    except Exception as exc:  # noqa: BLE001 — non-fatal
        log(f"probe restore: AO readiness wait error (non-fatal): {exc}")


def build_real_probe_ops(
    *,
    timeout_s: float,
    log: Callable[[str], None],
    repo_root: Path | None = None,
) -> ProbeOps:
    """Wire the live legs into a :class:`ProbeOps`. Resolves the fleet config the SAME
    way the battery runner does (``load_harness_config`` -> ``build_default_config``),
    so ``start-llm.ps1`` and the runs dir point at the operator's real agentic-setup
    root — never a guess."""
    from shared.fleet.swap_ops import (
        real_available_gb,
        real_load_30b,
        real_wait_ready,
    )
    from tools.dispatch_harness.config import load_harness_config
    from shared.fleet.dispatch import build_default_config

    root = repo_root or _BLARAI_REPO_ROOT
    hc = load_harness_config()
    config = build_default_config(hc.agentic_setup_dir or None, hc.projects_dir or None)
    reboot_log = config.runs_dir / "probe-ao-reboot.log"

    return ProbeOps(
        available_gb=real_available_gb,
        stop_ao=lambda: _real_stop_ao(root, log),
        # run_id="" -> start-llm's log lands at runs_dir/start-llm.log (a file, so it
        # never creates a run dir that latest_run_id() could mistake for a real run).
        load_30b=lambda: real_load_30b(config, run_id=""),
        wait_ready=lambda: real_wait_ready(port=_OVMS_PORT, timeout_s=timeout_s),
        restore=lambda: _real_restore(
            config, root, ao_port=_AO_PORT, reboot_log=reboot_log, log=log
        ),
        log=log,
    )


def main(argv: "list[str] | None" = None) -> int:
    from shared.fleet.swap_ops import START_LLM_TIMEOUT_S

    parser = argparse.ArgumentParser(
        prog="python -m tools.dispatch_harness.probe",
        description="Probe-not-predict swap admission (#784): attempt one real 30B "
        "load outside any job; success admits the battery night.",
    )
    parser.add_argument(
        "--min-free-gb",
        type=float,
        required=True,
        help="Sanity floor: if Available RAM (GiB) is below this, exit 3 without "
        "attempting a load (nothing is touched).",
    )
    parser.add_argument(
        "--timeout-s",
        type=float,
        default=START_LLM_TIMEOUT_S,
        help="Readiness-proof budget after the load (seconds). Default: the registered "
        "start-llm load ceiling (START_LLM_TIMEOUT_S), so the probe's wait agrees with "
        "start-llm's own block.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a single machine-readable outcome line on stdout (for the PS caller "
        "and community-grade perf capture). Logs always go to stderr.",
    )
    args = parser.parse_args(argv)

    # UTF-8-safe output regardless of the console codepage / a captured transcript —
    # the probe's messages carry non-ASCII punctuation and the PS caller redirects
    # every stream to a file (the #761 cp1252 banner-crash class: a wrapper that
    # can't encode its own output kills the process). errors="replace" fails soft.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001 — a non-reconfigurable stream (a pipe/StringIO) is fine
            pass

    # Logs -> stderr so a --json consumer can capture the one outcome line on stdout.
    def _log(msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)

    ops = build_real_probe_ops(timeout_s=args.timeout_s, log=_log)
    result = run_probe(ops, min_free_gb=args.min_free_gb, timeout_s=args.timeout_s)

    if args.json:
        print(result.json_line(), flush=True)
    else:
        _log(
            f"probe result: {result.outcome} (exit {result.exit_code}); "
            f"available {result.available_gb:.1f} GiB, load {result.load_seconds:.1f}s"
        )
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
