"""Driver-integrated stop-doomed-fast checks (#844 C2, ADR-039 §2.10 C2 / §2.13 item 6).

The PROMOTION of the dispatch harness's doom-detection patterns
(``tools/dispatch_harness/monitor.py``) into the swap driver itself: an out-of-band
watchdog — a structural sibling of :class:`shared.fleet.swap_driver.BudgetWatchdog`,
same thread pattern, same ``request_stop``/``abort`` machinery, same
teardown-entry inertness — that samples the fleet's own PROGRESS artifacts while a
run-fleet child is live and stops a DETERMINED-doomed coder in minutes instead of
letting it burn the whole per-task ceiling. This is ADR-039 §2.13 item 6's *in-run
tactical* monitoring layer gaining the harness's proven doom logic natively; the
coordinator's *cross-run operational* layer (stalls, `/coord status`) stays
observe-only and is built elsewhere.

**Doom is never elapsed time.** A healthy coding run can legitimately be long (a
live ~1 h rocket-calc run PARKED honestly); the doom signal is the harness's
measured predicate: between two samples ``stall_grace_s`` apart, NO watched
progress artifact advanced AND no coder/fleet process burned CPU AND a run-fleet
child is actually REGISTERED (in flight). The watched-artifact vocabulary and the
process-name/CPU heuristics are lifted from the harness byte-identically (this
module is their SSOT now — ``monitor.py`` imports them back), including every
false-doom scar: the #687 review/design/swap logs, the night-20260709 B4
verify-gate workers (uv/ruff/git), and the 240 s grace those incidents set
(registered in ``shared/timeout_registry.py``).

**Child-registered is the arming condition.** Only the live run-task path
registers a child with the ``_CurrentChild`` holder — the driver's own phases
(load, wave gates, critic/design, teardown) never do — so a quiet log during a
driver-side step can never doom anything (the B4 false-doom class, closed
structurally rather than by grace-window tuning alone). Teardown-entry
(``begin_teardown``) makes the shared ``abort`` structurally inert, so a doom that
fires late can never act during the 14B restore — the same proof obligation the
budget watchdog already carries.

**Honest labeling (#757 lineage).** A doom stop rides the SAME stop event the
budget watchdog uses, so without discrimination it would be reported as a
budget-timeout. The watchdog therefore records ``fired``; the driver's stop
labeling and the unexplained-kill relabel (``swap_ops.relabel_unexplained_kill``)
read it and say *doom-stop*, never "the budget elapsed" for a kill the budget did
not issue.

DORMANT (#844): ``[coordinator].swap_doom_checks_enabled`` ships ``false`` and the
dispatch spec does not carry the key, so ``build_doom_watchdog`` returns ``None``
and the driver runs NO doom thread — swap behavior is byte-identical to pre-#844.
Going live is an LA ceremony: thread the flag into the dispatch spec and flip the
TOML key. Importing this module arms nothing.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from shared.fleet.dispatch import FleetDispatchConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# The promoted signal vocabulary — SSOT (monitor.py imports these back)
# ---------------------------------------------------------------------------

#: Coder/fleet child-process names whose CPU activity means "the run is doing
#: work". Lowercased, matched prefix-or-equal against psutil process names
#: (which include ``.exe`` on Windows). Promoted verbatim from
#: ``tools/dispatch_harness/monitor.py`` — including the night-20260709 B4
#: false-doom additions (the [3/5] verify gate's uv/ruff/git native workers,
#: which burn CPU while every watched log stays quiet by design).
CODER_PROC_NAMES: tuple[str, ...] = (
    "opencode",        # the coder agent runtime
    "dotnet",          # .NET build/test
    "node",            # JS/TS toolchains the coder may spawn
    "msbuild",
    "playwright",      # browser-driven verify
    "msedge",
    "ovms",            # the 30B server itself (generation)
    "python",          # the detached swap driver + run-fleet pwsh children
    "pwsh",
    "powershell",
    "uv",              # ephemeral test/lint installs + runners (uv run --with pytest/mutmut)
    "ruff",            # native lint binary
    "git",             # worktree/diff operations between steps
)

#: CPU-percent above which a process counts as "actively working" for a sample.
CPU_ACTIVE_THRESHOLD: float = 5.0

#: The no-progress window that defines determined-doom, in seconds. The SAME
#: measured quantity as the harness monitor's ``RunMonitor.stall_grace_s`` (both
#: registered in ``shared/timeout_registry.py``; change them together): it must
#: comfortably exceed the longest legitimately log-quiet, CPU-quiet gap INSIDE a
#: healthy step (the B4 verify gate hands off between native workers), while
#: still dooming a truly dead run in minutes — the overall budget backstops.
DOOM_STALL_GRACE_S: float = 240.0

#: Watchdog poll cadence (poll grain, below-registry-value — inventoried in the
#: timeout registry's grain list alongside the harness monitor's identical 5 s).
DOOM_POLL_INTERVAL_S: float = 5.0

#: CPU sample window per poll (grain; matches the harness monitor's 1.5 s).
DOOM_CPU_SAMPLE_S: float = 1.5


# ---------------------------------------------------------------------------
# Sampling — the fleet's own progress artifacts, from the driver's vantage
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DoomSample:
    """One instant's doom-relevant signals — the pure predicate's whole input.

    ``newest_progress_mtime`` is the max mtime across EVERY watched progress
    artifact (``None`` when none exist yet); ``child_active`` is whether a
    run-fleet child is currently REGISTERED with the ``_CurrentChild`` holder
    (the arming condition); ``coder_cpu_active`` is the psutil CPU probe."""

    wall_now: float
    newest_progress_mtime: float | None
    coder_cpu_active: bool
    child_active: bool


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _newest_glob_mtime(directory: Path, patterns: tuple[str, ...]) -> float | None:
    mtimes: list[float] = []
    for pattern in patterns:
        try:
            entries = list(directory.glob(pattern))
        except OSError:
            continue
        mtimes.extend(m for m in (_mtime(p) for p in entries) if m is not None)
    return max(mtimes) if mtimes else None


def newest_progress_mtime(config: FleetDispatchConfig, run_id: str) -> float | None:
    """The freshest mtime across the run's watched progress artifacts.

    The SAME artifact set the harness monitor watches (its #686/#687 scars
    included): the run dir's ``journal.log`` + ``run-fleet-*.log`` +
    ``design-critique.log`` + ``swap-progress.log``, the shared
    ``state/logs/ovms-*.out.log`` (generation), and the shared
    ``state/reports/*.review.log`` / ``*.agent.log`` (the per-task review /
    coder output a long GPU-bound [4/5] review advances while every other log
    is quiet). Fail-soft: unreadable pieces contribute nothing; no artifacts at
    all yields ``None`` (never doom — the run simply hasn't produced output)."""
    run_dir = config.runs_dir / run_id
    state_dir = config.queue_path.parent
    candidates = [
        _mtime(run_dir / "journal.log"),
        _newest_glob_mtime(run_dir, ("run-fleet-*.log",)),
        _mtime(run_dir / "design-critique.log"),
        _mtime(run_dir / "swap-progress.log"),
        _newest_glob_mtime(state_dir / "logs", ("ovms-*.out.log",)),
        _newest_glob_mtime(state_dir / "reports", ("*.review.log", "*.agent.log")),
    ]
    mtimes = [m for m in candidates if m is not None]
    return max(mtimes) if mtimes else None


def coder_cpu_active(
    *,
    sample_s: float = DOOM_CPU_SAMPLE_S,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """psutil-based "is a coder/fleet child burning CPU?" over a short sample.

    Promoted verbatim from the harness monitor's probe, fail-soft in the SAME
    direction: any error (psutil missing, a process vanishing mid-sample) reads
    as ``True`` — assume active, never doom a run on an unreadable probe; the
    mtime-stall condition still has to hold too, and the budget backstops."""
    try:
        import psutil
    except Exception:  # noqa: BLE001
        return True  # can't measure -> assume active (don't kill on a missing probe)
    try:
        procs = []
        for p in psutil.process_iter(["name"]):
            name = (p.info.get("name") or "").lower()
            if any(name == n or name.startswith(n) for n in CODER_PROC_NAMES):
                try:
                    p.cpu_percent(None)  # prime the per-process counter
                    procs.append(p)
                except Exception:  # noqa: BLE001
                    pass
        if not procs:
            return False  # no coder/fleet process at all -> definitely idle
        sleep(sample_s)
        for p in procs:
            try:
                if p.cpu_percent(None) >= CPU_ACTIVE_THRESHOLD:
                    return True
            except Exception:  # noqa: BLE001
                continue
        return False
    except Exception:  # noqa: BLE001
        return True  # unreadable -> assume active (fail-soft)


def build_doom_sampler(
    config: FleetDispatchConfig,
    run_id: str,
    *,
    child_active: Callable[[], bool],
    cpu_probe: "Callable[[], bool] | None" = None,
    wall_clock: Callable[[], float] = time.time,
) -> Callable[[], DoomSample]:
    """Compose the live :class:`DoomSample` reader for one run.

    ``child_active`` is the ``_CurrentChild.is_child_registered`` bound method
    (the arming condition); ``cpu_probe`` defaults to :func:`coder_cpu_active`.
    The CPU probe is only paid when a child is actually registered — a
    driver-phase sample is a cheap three-field read."""
    probe = cpu_probe or coder_cpu_active

    def _sample() -> DoomSample:
        active = bool(child_active())
        return DoomSample(
            wall_now=wall_clock(),
            newest_progress_mtime=newest_progress_mtime(config, run_id),
            coder_cpu_active=(probe() if active else False),
            child_active=active,
        )

    return _sample


# ---------------------------------------------------------------------------
# The pure doom predicate (the promoted classify_run_health rules 5-7, at the
# driver's vantage — rules 1-4 are unnecessary here: the driver IS the phase
# owner and knows natively when a task child is in flight and when it returned)
# ---------------------------------------------------------------------------


def classify_doom(
    prev: "DoomSample | None",
    cur: DoomSample,
    *,
    stall_grace_s: float = DOOM_STALL_GRACE_S,
) -> bool:
    """True iff *cur* is DETERMINED-doomed relative to *prev*.

    Doom requires ALL of, mirroring the harness predicate's semantics:

    1. a run-fleet child is REGISTERED (``cur.child_active`` — the arming
       condition; the driver's own phases can never doom),
    2. no coder/fleet CPU this sample,
    3. a prior sample exists (a single snapshot is never doom — confirmation),
    4. progress artifacts exist and did NOT advance since *prev* (a first
       appearance counts as an advance), and
    5. the freshest artifact is at least ``stall_grace_s`` old at *cur*'s wall
       clock.

    ``stall_grace_s <= 0`` disables (never doomed) — the same disable idiom as
    the budget watchdog's ``budget_s <= 0``."""
    if stall_grace_s <= 0:
        return False
    if not cur.child_active:
        return False
    if cur.coder_cpu_active:
        return False
    if prev is None:
        return False
    if cur.newest_progress_mtime is None:
        return False  # nothing written yet — not-started, the budget backstops
    if prev.newest_progress_mtime is None:
        return False  # artifacts first appeared this cycle — that IS progress
    if cur.newest_progress_mtime > prev.newest_progress_mtime:
        return False  # progress advanced
    return (cur.wall_now - cur.newest_progress_mtime) >= stall_grace_s


# ---------------------------------------------------------------------------
# The out-of-band watchdog (structural sibling of run_budget_watchdog)
# ---------------------------------------------------------------------------


def run_doom_watchdog(
    *,
    stall_grace_s: float,
    finished: Callable[[], bool],
    sample: Callable[[], DoomSample],
    mark_fired: Callable[[], None],
    request_stop: Callable[[], None],
    abort: Callable[[], None],
    on_doom: "Callable[[str], None] | None" = None,
    poll_s: float = DOOM_POLL_INTERVAL_S,
    sleep: "Callable[[float], None] | None" = None,
) -> None:
    """Daemon poll loop for the stop-doomed-fast check.

    ``finished()`` is checked FIRST every iteration so ``DoomWatchdog.stop()``
    self-exits the loop. On a doom verdict it records the fire
    (``mark_fired`` — read by the driver's honest stop labeling BEFORE the kill
    lands), narrates it (``on_doom``, best-effort), asks the CODE loop to stop
    (``request_stop`` — the same per-run stop event the budget watchdog sets),
    tree-kills the registered child (``abort`` — the ``_CurrentChild`` holder,
    structurally inert once teardown begins), then returns. A sampling error
    resets the baseline and is treated as ALIVE (fail-soft: an unreadable box
    never kills a run). Clock/sleep injected for tests."""
    sleep = sleep or time.sleep
    prev: "DoomSample | None" = None
    while True:
        if finished():
            return
        try:
            cur = sample()
        except Exception:  # noqa: BLE001 — an unreadable sample must never doom
            prev = None
            sleep(poll_s)
            continue
        if classify_doom(prev, cur, stall_grace_s=stall_grace_s):
            age = (
                cur.wall_now - cur.newest_progress_mtime
                if cur.newest_progress_mtime is not None
                else 0.0
            )
            reason = (
                f"DOOM-STOP: no fleet progress for {age:.0f}s (>= {stall_grace_s:.0f}s "
                "grace) and no coder process active while a run-fleet child is live — "
                "stopping the doomed task fast (the budget would have waited)."
            )
            try:
                mark_fired()
            except Exception:  # noqa: BLE001
                pass
            if on_doom is not None:
                try:
                    on_doom(reason)
                except Exception:  # noqa: BLE001
                    pass
            try:
                request_stop()
            except Exception:  # noqa: BLE001
                pass
            try:
                abort()
            except Exception:  # noqa: BLE001
                pass
            return
        prev = cur
        sleep(poll_s)


class DoomWatchdog:
    """Owns the out-of-band doom daemon thread for ONE swap run.

    The structural sibling of :class:`shared.fleet.swap_driver.BudgetWatchdog`:
    ``start()`` spawns the daemon — a NO-OP unless ``enabled`` and
    ``stall_grace_s > 0``, so the dormant default (#844: the dispatch spec does
    not carry the flag) spawns no thread and changes nothing. ``stop()`` is
    idempotent and exception-proof: it sets the finished event then joins
    UNBOUNDED (a bounded join is not proof of death — the ``step_aside.py``
    precedent — and a surviving daemon must never fire during the 14B restore;
    with finished set, each iteration is a cheap poll, so the join returns
    within one poll interval). ``fired`` is True iff the doom verdict fired
    this run — the driver's honest stop labeling reads it (#757 lineage: a doom
    kill must never be reported as a budget-timeout)."""

    def __init__(
        self,
        *,
        enabled: bool,
        sample: Callable[[], DoomSample],
        abort: Callable[[], None],
        request_stop: Callable[[], None],
        on_doom: "Callable[[str], None] | None" = None,
        stall_grace_s: float = DOOM_STALL_GRACE_S,
        poll_s: float = DOOM_POLL_INTERVAL_S,
        sleep: "Callable[[float], None] | None" = None,
    ) -> None:
        self._enabled = bool(enabled)
        try:
            self._stall_grace_s = float(stall_grace_s or 0.0)
        except (TypeError, ValueError):
            self._stall_grace_s = 0.0
        self._sample = sample
        self._abort = abort
        self._request_stop = request_stop
        self._on_doom = on_doom
        self._poll_s = poll_s
        self._sleep = sleep
        self._finished = threading.Event()
        self._fired = threading.Event()
        self._thread: "threading.Thread | None" = None

    @property
    def fired(self) -> bool:
        """True iff the doom verdict fired this run (read by stop labeling)."""
        return self._fired.is_set()

    def start(self) -> None:
        if not self._enabled or self._stall_grace_s <= 0:
            return
        try:
            t = threading.Thread(
                target=run_doom_watchdog,
                kwargs=dict(
                    stall_grace_s=self._stall_grace_s,
                    finished=self._finished.is_set,
                    sample=self._sample,
                    mark_fired=self._fired.set,
                    request_stop=self._request_stop,
                    abort=self._abort,
                    on_doom=self._on_doom,
                    poll_s=self._poll_s,
                    sleep=self._sleep,
                ),
                name="blarai-swap-doom-check",
                daemon=True,
            )
            t.start()
            self._thread = t
        except Exception:  # noqa: BLE001 — degrade to no-watchdog; NEVER raise into run()
            self._thread = None

    def stop(self) -> None:
        # Idempotent + exception-proof: the disabled / no-thread path must be a
        # clean no-op — never an AttributeError that masks `raised` in _teardown.
        self._finished.set()
        t = self._thread
        if t is None:
            return
        try:
            t.join()   # UNBOUNDED — finished is set, so the loop exits within one poll
        except Exception:  # noqa: BLE001
            pass
        self._thread = None
