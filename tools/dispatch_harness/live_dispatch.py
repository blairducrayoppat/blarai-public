"""Is a coding dispatch still driving right now? — the INTERVAL witness (#1341).

The Python twin of ``Get-LiveDispatch`` in
``agentic-setup/scripts/run-battery-night.ps1``. That function exists because the
nightly battery must not archive a sandbox out from under a run that is still
building; this one exists because the battery **scorecard writer** must not assert
a terminal verdict over an interval it stopped watching.

WHY A PROCESS AND NOT A FILE
============================
"Is this dispatch still running?" is an INTERVAL question, and every file marker
the fleet emits answers a SHORTER one. Measured, on the run this module was built
for (``20260808-160538-bd``): the harness stopped waiting at 294.97 s and banked
``verdict: STALLED, notes: "job could not run"``; the same run then merged three
tasks and started a fourth, and the ``SUMMARY.txt`` the scorecard cited as proof of
the stall was rewritten to ``RESULT: MERGED``. ``pwsh`` pid 5364 was alive the whole
time. A process is an interval by construction — it spans the between-wave gaps
that defeat port probes and journal-marker arithmetic alike (see the PowerShell
twin's header for why :8000 and TASK-START/TASK-END counting both fail).

THE THREE-STATE ANSWER IS THE POINT
===================================
:data:`LIVE`, :data:`ABSENT`, :data:`UNKNOWN` — never a bool. "I could not look" is
not "nothing is there", and a caller that cannot tell the two apart will record an
unobserved interval as an observed absence, which is the exact defect class this
module was written to retire. Every failure path here returns :data:`UNKNOWN` with
the reason; nothing returns :data:`ABSENT` on a probe that did not complete.

THE DIVERGENCE FROM THE POWERSHELL TWIN, AND WHY
================================================
The twin matches ``-m tools.dispatch_harness.`` as a bare prefix and avoids matching
its own children only by ORDERING (its probe is synchronous and its archive loop runs
before the runner launches). This module is called FROM one of those children:
``python -m tools.dispatch_harness.battery`` is the battery runner itself, so the
twin's prefix would make every card self-match and report a live dispatch on an idle
box — the permanent-false-positive mirror of the twin's S3 trap. :data:`_SELF_MODULES`
is therefore excluded by name, and the exclusion is a NAMED CONSTANT rather than a
``!= os.getpid()`` test because a peer battery runner is not this job's dispatch
driver either, and pid-exclusion alone would not catch it.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

#: A dispatch driver is running (an interval that has not ended).
LIVE = "live"
#: The process table was read in full and holds no dispatch driver.
ABSENT = "absent"
#: The question could not be answered. NEVER conflate with :data:`ABSENT`.
UNKNOWN = "unknown"

#: ``-m <module>`` values under ``tools.dispatch_harness.`` that are the BATTERY
#: RUNNER rather than a dispatch leg. Excluded by name: this module runs inside
#: the first one, and a second battery process is a peer measuring instrument,
#: not a driver of the job being scored.
_SELF_MODULES: frozenset[str] = frozenset({"battery"})

#: Images that could plausibly host a dispatch driver. Used ONLY for the blind-spot
#: test below — never to conclude that something IS a driver.
_DRIVER_CAPABLE_IMAGE = re.compile(
    r"^(python|pythonw|pwsh|powershell|node|opencode)\.exe$", re.IGNORECASE
)

# THE IMAGE AND THE FORM TOGETHER, never the form alone (the twin's S3 lesson).
# `-m shared.fleet.swap_ops` appears verbatim inside any shell whose -Command
# MENTIONS it, so matching argument text alone lets a diagnostic one-liner, a grep,
# or this module's own test suite masquerade as a live dispatch. Binding each
# pattern to the executable that can actually host it makes the match a real
# invocation FORM: a .ps1 is run by a shell, a `-m <module>` by an interpreter.
_SHELL_IMAGE = re.compile(r"^(pwsh|powershell)\.exe$", re.IGNORECASE)
_PY_IMAGE = re.compile(r"^(python|pythonw)\.exe$", re.IGNORECASE)

_RUN_FLEET = re.compile(r"-File\s+\S*run-fleet\.ps1", re.IGNORECASE)
_SWAP_OPS = re.compile(r"-m\s+shared\.fleet\.swap_ops(\s|$)")
#: Any dispatch_harness leg EXCEPT the runner itself — see :data:`_SELF_MODULES`.
_HARNESS_LEG = re.compile(r"-m\s+tools\.dispatch_harness\.([A-Za-z_][A-Za-z0-9_]*)")


@dataclass(frozen=True)
class LiveDispatch:
    """One process-table read, and what it is honestly worth.

    ``state`` is the contract. ``detail`` is a single-line, evidence-safe account of
    what was seen (a live driver's image/pid, or why the answer is UNKNOWN) and is
    empty only for :data:`ABSENT`, where there is nothing to say. ``pids`` is
    populated for :data:`LIVE` (who to go and look at) and for the blind-spot
    :data:`UNKNOWN` (who could not be read)."""

    state: str
    detail: str = ""
    pids: tuple[int, ...] = ()

    @property
    def is_live(self) -> bool:
        """True ONLY for a positive observation. An UNKNOWN is not a live reading,
        and callers must not treat it as one — but they must not treat it as an
        absence either; check ``state`` when the difference matters."""
        return self.state == LIVE


def _driver_label(name: str, cmdline: str) -> str:
    """The driver FORM *cmdline* matches when run as *name*, or "" for none.

    Pure and total — the whole matcher, isolated from process enumeration so the
    form rules can be driven directly by a test with no processes involved."""
    if _SHELL_IMAGE.match(name) and _RUN_FLEET.search(cmdline):
        return "run-fleet.ps1 (outer dispatch driver)"
    if _PY_IMAGE.match(name):
        if _SWAP_OPS.search(cmdline):
            return "shared.fleet.swap_ops (swap driver)"
        leg = _HARNESS_LEG.search(cmdline)
        if leg and leg.group(1) not in _SELF_MODULES:
            return f"tools.dispatch_harness.{leg.group(1)} (dispatch leg)"
    return ""


def _iter_processes():
    """Yield ``(pid, image_name, cmdline_or_None)`` for every DRIVER-CAPABLE process.

    ``cmdline`` is ``None`` when this process may not read it — the blind spot a
    non-elevated caller has over elevated processes, which :func:`probe_live_dispatch`
    converts into :data:`UNKNOWN` rather than silence. Raises on a process table that
    cannot be enumerated at all; the caller turns that into :data:`UNKNOWN` too.

    THE NAME FILTER COMES FIRST, AND IT COSTS NOTHING SEMANTICALLY. Asking psutil for
    ``cmdline`` during enumeration opens EVERY process on the box: measured 6.28 s on
    this machine under a live dispatch, against ~0.1 s for a name-only sweep plus a
    command-line read of the handful of candidates. Nothing is lost, because every
    image :func:`_driver_label` can match is in :data:`_DRIVER_CAPABLE_IMAGE` by
    construction and that same set defines the blind-spot test — a process this filter
    drops could neither have matched nor have been a blind spot."""
    import psutil  # noqa: PLC0415 — lazy by design (import-cost hygiene, house idiom)

    for proc in psutil.process_iter(["pid", "name"]):
        try:
            info = proc.info
            name = info.get("name") or ""
            if not _DRIVER_CAPABLE_IMAGE.match(name):
                continue
            pid = int(info.get("pid") or -1)
            try:
                raw = proc.cmdline()
            except Exception:  # noqa: BLE001 — unreadable is the BLIND SPOT, not an absence
                raw = None
        except Exception:  # noqa: BLE001 — one vanished process never sinks the sweep
            continue
        # psutil reports an unreadable command line as None and a genuinely
        # argument-less one as []. Those mean opposite things here, so the empty
        # list becomes "" (readable, nothing to match) and None stays None.
        yield pid, name, (None if raw is None else " ".join(raw))


def probe_live_dispatch(processes=None, *, self_pid: int | None = None) -> LiveDispatch:
    """Read the process table once and report whether a dispatch driver is running.

    *processes* is the injection seam: an iterable of ``(pid, image_name,
    cmdline_or_None)``. Defaulting to :func:`_iter_processes` keeps the live path
    honest while letting the control be proved to FIRE — and, with an empty table,
    proved to go quiet — without spawning a real dispatch (security_by_design
    principle 12: a lock ships with the test that shows it blocking AND the toggle
    that shows the probe failing when the lock is off).

    FAIL-SOFT, NEVER FAIL-QUIET. An unreadable process table, and a table in which
    any driver-capable image hides its command line, both return :data:`UNKNOWN`
    with the reason. :data:`ABSENT` is returned only after a complete read that saw
    every candidate's command line — because "I saw nothing" is evidence of absence
    only if seeing was possible."""
    pid_self = os.getpid() if self_pid is None else self_pid
    try:
        rows = list(_iter_processes() if processes is None else processes)
    except Exception as exc:  # noqa: BLE001 — an unreadable table is UNKNOWN, never ABSENT
        return LiveDispatch(
            UNKNOWN,
            detail=f"could not read the process table ({type(exc).__name__}: {exc})",
        )

    hits: list[tuple[int, str, str]] = []
    blind: list[tuple[int, str]] = []
    for pid, name, cmdline in rows:
        if pid == pid_self:
            continue
        if cmdline is None:
            if _DRIVER_CAPABLE_IMAGE.match(name or ""):
                blind.append((pid, name or "?"))
            continue
        label = _driver_label(name or "", cmdline)
        if label:
            hits.append((pid, name or "?", label))

    if hits:
        first = hits[0]
        return LiveDispatch(
            LIVE,
            detail=(f"pid {first[0]} ({first[1]}) is {first[2]}; "
                    f"{len(hits)} driving process(es) total"),
            pids=tuple(pid for pid, _, _ in hits),
        )
    if blind:
        # Measured on a healthy elevated box (the twin's note): 21 of 253 processes
        # carry a null command line and NONE is a driver-capable image — those are
        # System/Registry/Memory-Compression, which have no command line rather than
        # a hidden one. A driver-capable image with an unreadable command line is
        # therefore anomalous, and the honest answer is "I cannot tell".
        names = ", ".join(f"{name}:{pid}" for pid, name in blind[:5])
        return LiveDispatch(
            UNKNOWN,
            detail=(f"{len(blind)} driver-capable process(es) hide their command line "
                    f"({names}) — this process cannot see whether they drive a dispatch "
                    "(elevation blind spot); reporting UNKNOWN rather than an idle box"),
            pids=tuple(pid for pid, _ in blind),
        )
    return LiveDispatch(ABSENT)
