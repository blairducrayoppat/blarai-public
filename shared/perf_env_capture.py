"""Perf-harness environment self-capture (#816 Part 2).

Every performance-evidence JSON records the box state it was measured under,
stamped AT RUN START — so a resident VM or model can never silently vanish
from an evidence record again.  The 2026-07-10 unnoticed-VM incident is the
incident this module exists for: the sealed BlarAI-Orchestrator guest ran
through an evening of #769 measurements unrecorded, and the addendum had to
be human-reconstructed after the fact because no harness stamped what was
resident when its numbers were taken.

The capture is FAIL-SOFT BY CONTRACT: a probe failure must NEVER break a
bench run — but it is stamped honestly as the string ``"unknown"``, never
omitted.  ``"unknown"`` in the evidence is itself a signal (the probe could
not answer); an absent key silently reads as "the box was clean", which is
exactly how the original incident slipped through.

Consumers: ``scripts/benchmark_vlm_text_inference.py`` and
``scripts/benchmark_spec_decode_ab.py`` embed :func:`capture_box_state`
under the ``"environment"`` key of their result JSONs (start + end stamps;
shape-locked by ``tests/integration/test_perf_harness_env_capture.py``).
The interactive twin is agentic-setup ``scripts/box-state.ps1`` (#816
Part 1) — the same consumer classes as a human-facing report; this module
is the machine-facing stamp that rides the evidence record itself.

Probe surfaces (all local — loopback sockets + a local subprocess; no
external network, consistent with the shared/ posture):

* ``vm_states``       — ALL Hyper-V VMs via a PowerShell ``Get-VM``
  subprocess, never a known-name filter: enumerating everything is the
  point (the incident VM was the one nobody thought to ask about).  The
  shell-out mirrors ``launcher/vm_manager.py::_run_ps`` (``-NoProfile
  -NonInteractive``) rather than importing the launcher — the harnesses
  must not grow a launcher dependency for one read-only enumeration.
* ``ao_listening``    — loopback :5001 connect probe.  Liveness, not
  health (cf. the #750 lesson on ``create_connection`` probes): for a
  box-state stamp, "something holds the AO port" IS the fact to record.
* ``ovms_listening``  — loopback :8000 connect probe (the OVMS HTTP port).
* ``ovms_process``    — any process whose name contains ``ovms`` (psutil
  scan; the port can lag the process on startup/teardown, so both are
  stamped).
* ``ram_available_gib`` — ``psutil.virtual_memory().available`` in GiB.
* ``captured_utc``    — the stamp instant, ISO-8601 Zulu.

Every probe takes an injectable seam (callable/iterable) so the unit tests
exercise all paths with no real Hyper-V, sockets, or process table.
"""

from __future__ import annotations

import socket
import subprocess
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

try:
    import psutil  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover — psutil is a declared runtime dep, normally present
    psutil = None  # type: ignore[assignment]

#: The honest sentinel for "this probe could not answer" — stamped, never omitted.
UNKNOWN: str = "unknown"

#: AO loopback port (= launcher.__main__.ORCHESTRATOR_HOST_LOOPBACK_PORT).
AO_LOOPBACK_PORT: int = 5001

#: OVMS HTTP port (the fleet model server the dispatch battery runs).
OVMS_HTTP_PORT: int = 8000

#: PowerShell probe budget (registered in shared/timeout_registry.py).  A warm
#: ``Get-VM`` answers in ~1-3 s; 25 s covers a cold PowerShell + Hyper-V module
#: load and matches the harnesses' existing gpu_driver_version probe budget.
PS_PROBE_TIMEOUT_S: float = 25.0

#: Loopback connect probe budget (registered in shared/timeout_registry.py).
#: Loopback answers in milliseconds; 1 s bounds a capture on a wedged stack.
PORT_PROBE_TIMEOUT_S: float = 1.0

#: The canonical capture shape — :func:`capture_box_state` returns exactly
#: these keys, always all present.  Downstream evidence scrapers key on this.
BOX_STATE_KEYS: frozenset[str] = frozenset(
    {
        "vm_states",
        "ao_listening",
        "ovms_listening",
        "ovms_process",
        "ram_available_gib",
        "captured_utc",
    }
)

#: One line per VM, tab-separated ``Name<TAB>State``.  ``"$($_.State)"``
#: stringifies the enum ("Off"/"Running"/...) — ``ConvertTo-Json`` would emit
#: the raw enum INTEGER, and its bare-object-for-one-item shape is a second
#: trap; plain lines avoid both.  ``-ErrorAction Stop`` turns a permission /
#: module failure into a non-zero exit → ``"unknown"`` (fail-soft, honest).
_GET_VM_COMMAND: str = (
    'Get-VM -ErrorAction Stop | ForEach-Object { "$($_.Name)`t$($_.State)" }'
)

#: Seam types.  ``PsRunner`` matches ``_run_ps``; ``Connector`` matches
#: ``socket.create_connection`` (returns anything close()-able); ``MemProber``
#: returns AVAILABLE BYTES.
PsRunner = Callable[[str], "tuple[int, str, str]"]
Connector = Callable[..., Any]
MemProber = Callable[[], float]


def _run_ps(command: str, timeout: float = PS_PROBE_TIMEOUT_S) -> tuple[int, str, str]:
    """Execute a PowerShell command and return ``(exit_code, stdout, stderr)``.

    Mirrors ``launcher/vm_manager.py::_run_ps`` (``-NoProfile
    -NonInteractive`` for deterministic execution).  Never raises: timeout,
    missing binary, and spawn errors all return exit code ``-1`` so the
    caller degrades to ``"unknown"``.
    """
    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                command,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except (FileNotFoundError, OSError) as exc:
        return -1, "", f"{type(exc).__name__}: {exc}"


def capture_vm_states(
    ps_runner: PsRunner | None = None,
) -> list[dict[str, str]] | str:
    """ALL Hyper-V VMs as ``[{"name": ..., "state": ...}, ...]``.

    ``[]`` is an honest answer (the enumeration SUCCEEDED and found zero
    VMs); the string ``"unknown"`` means the enumeration itself failed
    (non-elevated shell, Hyper-V module absent, timeout, runner raised).
    A malformed output line degrades per-line to ``state="unknown"`` rather
    than discarding the whole enumeration.  Never raises.
    """
    run: PsRunner = ps_runner if ps_runner is not None else _run_ps
    try:
        code, stdout, _stderr = run(_GET_VM_COMMAND)
    except Exception:  # noqa: BLE001 — a capture failure must never break a bench run
        return UNKNOWN
    if code != 0:
        return UNKNOWN
    vms: list[dict[str, str]] = []
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        name, sep, state = line.rpartition("\t")
        if not sep:
            vms.append({"name": line, "state": UNKNOWN})
        else:
            vms.append({"name": name.strip(), "state": state.strip() or UNKNOWN})
    return vms


def probe_port_listening(
    port: int,
    host: str = "127.0.0.1",
    *,
    connector: Connector | None = None,
    timeout_s: float = PORT_PROBE_TIMEOUT_S,
) -> bool | str:
    """True when a loopback connect to ``host:port`` succeeds (liveness).

    ``False`` on refusal/timeout (nothing listening); ``"unknown"`` only on
    a non-socket failure (the probe itself broke).  Never raises.
    """
    connect: Connector = (
        connector if connector is not None else socket.create_connection
    )
    try:
        sock = connect((host, port), timeout=timeout_s)
    except OSError:
        return False
    except Exception:  # noqa: BLE001 — probe machinery failure, not a port answer
        return UNKNOWN
    try:
        sock.close()
    except Exception:  # noqa: BLE001 — the connect already answered the question
        pass
    return True


def probe_ovms_process(
    process_names: Iterable[str] | None = None,
) -> bool | str:
    """True when any process name contains ``ovms`` (case-insensitive).

    ``"unknown"`` when the process table cannot be read (psutil absent or
    the scan raised) — NOT ``False``: "cannot check" must never stamp as
    "no model server" (the incident class this module closes).  Never raises.
    """
    if process_names is None:
        if psutil is None:
            return UNKNOWN
        try:
            names: list[str] = []
            for proc in psutil.process_iter(["name"]):
                try:
                    names.append(proc.info.get("name") or "")
                except Exception:  # noqa: BLE001 — races with exiting processes are normal
                    continue
            process_names = names
        except Exception:  # noqa: BLE001 — the scan itself failed
            return UNKNOWN
    try:
        return any("ovms" in (name or "").lower() for name in process_names)
    except Exception:  # noqa: BLE001 — a broken injected iterable
        return UNKNOWN


def probe_ram_available_gib(mem_prober: MemProber | None = None) -> float | str:
    """System available memory in GiB, rounded to 2 places.

    ``"unknown"`` when psutil is absent or the probe raised.  Never raises.
    """
    try:
        if mem_prober is not None:
            available_bytes = float(mem_prober())
        elif psutil is not None:
            available_bytes = float(psutil.virtual_memory().available)
        else:
            return UNKNOWN
        return round(available_bytes / (1024.0**3), 2)
    except Exception:  # noqa: BLE001 — a capture failure must never break a bench run
        return UNKNOWN


def capture_box_state(
    *,
    ao_port: int = AO_LOOPBACK_PORT,
    ovms_port: int = OVMS_HTTP_PORT,
    ps_runner: PsRunner | None = None,
    connector: Connector | None = None,
    process_names: Iterable[str] | None = None,
    mem_prober: MemProber | None = None,
) -> dict[str, Any]:
    """One box-state stamp for a perf-evidence record.  NEVER raises.

    Returns exactly :data:`BOX_STATE_KEYS` — every key always present, each
    probe independently degrading to ``"unknown"`` on failure.  Call once at
    run START (before any guard or model load shifts the box) and embed the
    dict under the result JSON's ``"environment"`` key; a second stamp at
    completion records what changed under the run (battery jobs start and
    stop the AO/OVMS around measurement windows on this box).
    """

    def _soft(probe: Callable[[], Any]) -> Any:
        try:
            return probe()
        except Exception:  # noqa: BLE001 — the never-break-a-bench-run contract
            return UNKNOWN

    return {
        "vm_states": _soft(lambda: capture_vm_states(ps_runner)),
        "ao_listening": _soft(
            lambda: probe_port_listening(ao_port, connector=connector)
        ),
        "ovms_listening": _soft(
            lambda: probe_port_listening(ovms_port, connector=connector)
        ),
        "ovms_process": _soft(lambda: probe_ovms_process(process_names)),
        "ram_available_gib": _soft(lambda: probe_ram_available_gib(mem_prober)),
        "captured_utc": _soft(
            lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        ),
    }
