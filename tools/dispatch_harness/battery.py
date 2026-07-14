"""M2 capability-battery runner (plan §9.5 Layer 4 — built by W9, executed by W8).

One command queues any subset of the versioned job battery (``evals/battery/B*.json``)
through the REAL dispatch pipeline and emits validated, machine-readable scorecards
plus a summary table::

    python -m tools.dispatch_harness.battery --jobs B1,B3 [--dry-run] [--out DIR]
    python -m tools.dispatch_harness.battery --all

It drives the EXISTING :class:`~tools.dispatch_harness.harness.DispatchHarness`
(``for_live`` / ``for_dry_run`` / ``run_job`` — a headless WinUI, not a second
implementation) and NEVER forks it. ``--dry-run`` runs the harness's fake-AO mode
end-to-end (no GPU, no model, no live AO) — the standing smoke that a battery run
produces valid scorecards.

Verdict sourcing (honest by construction):

* **Adopt** — when the run dir carries a driver-emitted ``scorecard.json``
  (``state/fleet-runs/<RunId>/scorecard.json`` — the W6 REPORT-phase seam, plan
  §4.3), the runner validates it, stamps the battery context (job id, card,
  repo, versions), and **cross-checks** it: a claimed GREEN whose
  ``evidence.oracle_status`` is not ``"passed"``, or a GREEN on a rig-carrying
  job (B8), is rewritten to **FALSE-DONE** (attribution VERIFY) — the §9
  zero-tolerance invariant with teeth in the runner itself.
* **Synthesize** — with no driver scorecard (pre-W6 pipeline, or a crashed run)
  the runner emits a conservative card: a job that cannot run **or cannot be
  scored** is ``STALLED`` + ``HARNESS``, never silence and never an unearned
  GREEN.

Security posture (plan §10 S5): battery targets are pinned to SANDBOX repos —
a card whose ``repo`` does not match ``battery-<slug>`` is refused at load
(the operator's real repos are never eligible); the fleet's own
``validate_repo`` containment still applies underneath, unchanged.

This module also owns the battery-spec plumbing shared by the gate tests:
card loading/validation, JobPlan-v1 structural validation (the pinned #740
contract), wave computation, and the **reference plan-hash canonicalization**
(see :func:`reference_plan_hash` — flagged to Lane A/W1 as the documented
proposal until PlanStore lands its own).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import re
import socket
import ssl
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from tools.dispatch_harness import green_audit
from tools.dispatch_harness.config import load_harness_config
from tools.dispatch_harness.harness import DispatchHarness
from tools.dispatch_harness.jobs import JobSpec
from tools.dispatch_harness.report import JobReport
from tools.dispatch_harness.scorecard import (
    ATTRIBUTION_HARNESS,
    ATTRIBUTION_VERIFY,
    SCORECARD_SCHEMA,
    Scorecard,
    VERDICT_FALSE_DONE,
    VERDICT_GREEN,
    VERDICT_PARKED_HONEST,
    VERDICT_STALLED,
    VERDICTS,
    validate as validate_scorecard,
    write_scorecard,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SPEC_DIR = _REPO_ROOT / "evals" / "battery"
#: Dev/tuning cards live in a SEPARATE namespace so the frozen battery's B*.json
#: glob (and the production plan-override resolver) never see them (#838 D4).
DEV_SPEC_DIR = DEFAULT_SPEC_DIR / "dev"

CARD_SCHEMA = "battery-card/v1"
JOBPLAN_SCHEMA = "jobplan/v1"

#: ADR-038 D4 — the born-frozen-XOR-born-dev marker. A FROZEN card is model-neutral
#: and MEASUREMENT-ONLY (the battery judges against it; it is never tuned against); a
#: DEV card is the tuning surface model-specific refinement iterates on. A card is one
#: class or the other and NEVER crosses — enforced structurally by the id/class
#: biconditional in :func:`validate_card`. Absent ⇒ frozen (fail-safe: an unstamped
#: card can never be accidentally usable for tuning).
CARD_CLASS_FROZEN = "frozen"
CARD_CLASS_DEV = "dev"
CARD_CLASSES: frozenset[str] = frozenset({CARD_CLASS_FROZEN, CARD_CLASS_DEV})
DEFAULT_CARD_CLASS = CARD_CLASS_FROZEN

#: The pinned JobPlan v1 status vocabularies (#740 contract — Lane A implements the
#: same text; a mismatch here is a contract defect, not a local choice).
TASK_STATUSES: frozenset[str] = frozenset(
    {"pending", "ready", "building", "merged", "parked", "blocked", "skipped"}
)
INTEGRATION_STATUSES: frozenset[str] = frozenset({"pending", "passed", "failed"})
JOB_ACCEPTANCE_STATUSES: frozenset[str] = frozenset({"pending", "passed", "failed", "not-run"})

#: S5 sandbox pin: every battery target repo must look like this — never an
#: operator repo. (validate_repo's projects-dir containment still applies below.)
_SANDBOX_REPO_RE = re.compile(r"^battery-[a-z0-9][a-z0-9-]{0,40}$")

_CARD_ID_RE = re.compile(r"^B[1-9][0-9]?$")       # frozen battery ids (B1..B99)
_DEV_CARD_ID_RE = re.compile(r"^D[1-9][0-9]?$")   # dev/tuning ids (D1..D99) — #838 D4
_KEBAB_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

#: Where the driver's REPORT phase emits its per-run scorecard (the W6 seam).
DRIVER_SCORECARD_NAME = "scorecard.json"

#: The blarai checkout root — the cwd for a re-booted `python -m launcher` (mirrors
#: run-battery-night.ps1's ``$BlarRoot``). ``battery.py`` -> ``parents[2]``.
_BLARAI_REPO_ROOT = _REPO_ROOT

# Windows detached-process flags so a re-booted launcher OUTLIVES this runner
# (mirrors shared.fleet.swap_ops._spawn_detached_driver).
_DETACHED = 0x00000008           # DETACHED_PROCESS
_NEW_GROUP = 0x00000200          # CREATE_NEW_PROCESS_GROUP
_BREAKAWAY = 0x01000000          # CREATE_BREAKAWAY_FROM_JOB


# ---------------------------------------------------------------------------
# #750 fix 2 — re-ensure the live AO before each battery job (defense-in-depth)
# ---------------------------------------------------------------------------
#
# Night-1's cascade: B2's swap-back false-readied (declared "14B is back" on a
# bare-socket check, see #750 fix 1), :5001 died, and every SUBSEQUENT job
# (B4, B6) STALLED [HARNESS] because nothing re-ensured the AO. This layer makes
# ONE flaky swap-back non-cascading — it health-checks :5001 before each job and
# re-boots the launcher if it is down — WITHOUT waiting on the swap-driver
# readiness fix. The two compose: fix 1 makes the swap-back honest about
# readiness; fix 2 recovers if a swap-back nonetheless leaves the AO down.


def ao_socket_ready(port: int, *, timeout_s: float = 2.0) -> bool:
    """True iff something accepts a loopback TCP connection on *port*. A single
    accepted connection is *liveness*, not health — that is why the re-ensure below
    is DEFENSE-IN-DEPTH: a dying listener that passes here only STALLS this job, and
    the next job's ensure re-checks (a genuinely dead :5001 then refuses -> re-boot).
    The authoritative readiness proof is the swap driver's hardened backend_ready
    (#750 fix 1). Bare socket by design — the air-gap import control forbids a
    runtime HTTP client."""
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout_s):
            return True
    except OSError:
        return False


def ao_mtls_healthy(
    port: int,
    cert_path: Path,
    key_path: Path,
    ca_cert_path: Path,
    *,
    timeout_s: float = 5.0,
) -> bool:
    """True iff a client can COMPLETE the loopback mTLS handshake with the AO on *port*
    using the launcher-provisioned gateway certs — i.e. the AO's server leaf verifies
    against the CURRENT on-disk CA. This is the health that the bare-socket
    ``ao_socket_ready`` cannot see.

    THE FAILURE THIS CATCHES (found live 2026-07-06). The launcher mints a FRESH per-boot
    CA into ``certs/`` on every boot (``provision_per_boot_certs``), and an AO holds its
    minted certs in memory for its whole life. If ``certs/`` is re-minted UNDER a running
    AO — a standing-gate run booting a second production stack, a manual cert regen — the
    live AO keeps ACCEPTING the socket but now presents a leaf the current on-disk CA no
    longer signs. ``ao_socket_ready`` still says "up", the job dispatches, and the real
    mTLS turn fails ``CERTIFICATE_VERIFY_FAILED`` -> STALL [HARNESS]. Making the re-ensure
    mTLS-aware turns that orphan into a re-boot (the launcher re-mints + reloads ONE
    consistent set) instead of a cascade of harness stalls.

    Reuses the SAME client context the real transport builds
    (:func:`shared.ipc.vsock.create_client_ssl_context` — CERT_REQUIRED, check_hostname
    False, TLS>=1.2) and the SAME gateway client cert the dispatch presents, so a PASS here
    proves the dispatch's mTLS will verify too. NO application bytes are sent — the completed
    handshake alone is the proof, then the socket is closed. Fail-closed: certs absent,
    connection refused, or verify failure all -> not healthy (unprobeable == not healthy)."""
    for p in (cert_path, key_path, ca_cert_path):
        if not Path(p).is_file():
            return False
    try:
        from shared.ipc.vsock import create_client_ssl_context
    except Exception:  # noqa: BLE001 — cannot build the blessed context -> unprobeable
        return False
    ctx = create_client_ssl_context(str(cert_path), str(key_path), str(ca_cert_path))
    if ctx is None:
        return False
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout_s) as raw:
            with ctx.wrap_socket(raw, server_side=False):
                return True
    except (ssl.SSLError, OSError):
        return False


# ---------------------------------------------------------------------------
# #863 Option A — the teardown barrier (DRAFT_cert_remint_race_durable_fix.md §2):
# PROVE any prior AO is dead before boot_launcher_detached mints/boots a replacement.
# ---------------------------------------------------------------------------
#
# The #863 reuse-window (BLARAI_REUSE_CERTS below) fixed CERT agreement between
# successive battery boots but left the OTHER failure shape the same AO-lifecycle
# overlap produces open: a still-live prior AO still holds :port when the new
# launcher tries to bind it — a port-bind collision (or an instance-lock refusal)
# instead of a cert error. Evidence this is not hypothetical: #863's own run log
# recorded its third launcher boot (PID 3128, 23:06:32) "LEAKED on :5001 post-run"
# — a launcher process still bound to the AO's port when the run gave up.
#
# This barrier composes ONLY already-audited primitives — no new trust boundary,
# no new cross-process shutdown signal: the instance lock's OWN liveness check
# (launcher.instance_lock._is_live_launcher — the exact test the lock itself
# already trusts for a reclaim decision), the tree-kill escalation probe.py's
# _real_stop_ao already uses (shared.procspawn.terminate_process_tree —
# terminate() leaves-first then root, a bounded ~3s grace, then kill() on
# anything still alive), and this module's own ao_socket_ready.

#: Bounded wait for a tree-killed prior AO's port to actually go quiet (a SEPARATE
#: check from "the pid is gone" — process death and socket closure are not the same
#: instant). terminate_process_tree's own escalation already bounds the KILL at
#: ~3s; this covers the REMAINING OS-level socket-teardown lag. Registered in
#: shared/timeout_registry.py.
TEARDOWN_BARRIER_PORT_FREE_TIMEOUT_S: float = 15.0
#: Poll cadence while waiting for the port to go quiet (grain, not separately
#: registered — mirrors the AoReensurer.poll_s BACKLOG convention).
TEARDOWN_BARRIER_POLL_S: float = 0.5

#: The production AO's fixed port (mirrors tools.dispatch_harness.probe._AO_PORT;
#: duplicated rather than imported so this module's own default stays self-contained).
_AO_PORT: int = 5001


class TeardownBarrierError(RuntimeError):
    """Option A fail-closed (#863): a prior AO was tree-killed but its port never went
    quiet within the bounded wait. Raised INSTEAD of proceeding to boot a replacement
    onto a port a live process may still hold — every current caller already wraps
    ``boot_launcher_detached`` in a broad ``except Exception`` (``AoReensurer.ensure``,
    ``probe._real_restore``), so this surfaces as an honest failure and the job/probe
    STALLs rather than racing a cert/port collision."""


@dataclass
class TeardownBarrierOps:
    """Injected seams for :func:`run_teardown_barrier` — mirrors the AoReensurer /
    ProbeOps DI pattern already used in this module/package, so the prove-dead policy
    is unit-testable with no real process, socket, or GPU."""

    read_holder_pid: Callable[[], "int | None"]
    is_live_launcher: Callable[[int], bool]
    terminate: Callable[[int], "list[int]"]
    port_occupied: Callable[[], bool]  # True iff something still accepts on the port
    sleep: Callable[[float], None] = time.sleep
    log: Callable[[str], None] = print


def run_teardown_barrier(
    ops: TeardownBarrierOps,
    *,
    port: int,
    port_free_timeout_s: float = TEARDOWN_BARRIER_PORT_FREE_TIMEOUT_S,
    poll_s: float = TEARDOWN_BARRIER_POLL_S,
) -> None:
    """PROVE any prior AO holding this checkout's instance lock is dead before the
    caller mints/boots a replacement (#863 Option A).

    1. Identify the current lock holder and confirm it is a LIVE launcher (not a
       stale or recycled pid) — the SAME two checks the instance lock itself already
       trusts for its own reclaim decision (no new trust boundary; see
       ``launcher.instance_lock``).
    2. If live: tree-kill it (``ops.terminate`` — ``terminate_process_tree`` in the
       real wiring: leaves-first ``terminate()``, a bounded ~3s grace, then
       ``kill()`` on anything still alive).
    3. Poll until the port is ACTUALLY quiet, bounded by *port_free_timeout_s*.
       FAIL-CLOSED: raises :class:`TeardownBarrierError` naming the pid and port if
       it never frees.

    No lock holder, or the holder is not a live launcher (absent/corrupt lock, a
    dead pid, or a recycled pid now owned by an unrelated process) -> nothing to
    tear down; returns immediately WITHOUT EVER calling ``ops.port_occupied()``.
    This short-circuit matters beyond tidiness: it means a caller whose lock file is
    provably absent (a fresh ``certs/`` dir, or an isolated repo_root that shares no
    lock file with anything real — this module's own OFFLINE tests) can never be
    made to wait on, or misidentify, an unrelated process that happens to hold the
    same port number elsewhere on the box.
    """
    pid = ops.read_holder_pid()
    if not pid or pid <= 0 or not ops.is_live_launcher(pid):
        return

    ops.log(f"[teardown-barrier] lock holder pid {pid} is a LIVE launcher — tearing "
            f"it down before minting a replacement on :{port} (#863 Option A).")
    targeted = ops.terminate(pid)
    ops.log(f"[teardown-barrier] tree-kill targeted {targeted} — waiting up to "
            f"{port_free_timeout_s:.0f}s for :{port} to go quiet.")

    waited = 0.0
    while waited < port_free_timeout_s:
        if not ops.port_occupied():
            ops.log(f"[teardown-barrier] :{port} is quiet — safe to boot the replacement.")
            return
        ops.sleep(poll_s)
        waited += poll_s
    if not ops.port_occupied():
        ops.log(f"[teardown-barrier] :{port} is quiet — safe to boot the replacement.")
        return
    raise TeardownBarrierError(
        f"prior AO (pid {pid}) was tree-killed but :{port} is STILL accepting connections "
        f"after {port_free_timeout_s:.0f}s — refusing to boot a replacement onto a port a "
        "prior instance may still hold (fail-closed; the #863 port-collision this barrier "
        "exists to prevent)."
    )


def build_real_teardown_ops(
    repo_root: Path, port: int, log: Callable[[str], None] = print,
) -> TeardownBarrierOps:
    """Wire the REAL legs for :func:`run_teardown_barrier`: the SAME instance-lock
    liveness check the launcher's own single-instance guard trusts, the SAME
    tree-kill escalation ``probe.py``'s ``_real_stop_ao`` uses, and this module's own
    :func:`ao_socket_ready`. Composition only — no new primitive."""
    from launcher.instance_lock import _is_live_launcher, _read_holder_pid, lock_path_for_repo
    from shared.procspawn import terminate_process_tree

    lock = lock_path_for_repo(repo_root)
    my_pid = os.getpid()

    def _holder() -> "int | None":
        pid = _read_holder_pid(lock)
        # Defense-in-depth (mirrors acquire_instance_lock's own holder != me guard):
        # boot_launcher_detached never runs INSIDE a launcher process, so this is
        # unreachable in practice — but never treat our OWN pid as a peer to kill.
        return None if pid == my_pid else pid

    return TeardownBarrierOps(
        read_holder_pid=_holder,
        is_live_launcher=_is_live_launcher,
        terminate=terminate_process_tree,
        port_occupied=lambda: ao_socket_ready(port),
        log=log,
    )


def boot_launcher_detached(
    repo_root: Path, log_path: Path, *,
    port: int = _AO_PORT, log: Callable[[str], None] = print,
) -> None:
    """Boot the AO headless the SAME way run-battery-night.ps1 does — ``python -m
    launcher`` (PRODUCTION mode; no --dev-mode) from the blarai repo root, DETACHED
    so it outlives this runner, stdout+stderr -> *log_path*. Production is mandatory:
    the harness connects over the per-boot mTLS certs the launcher mints (ADR-026),
    so a dev-mode boot would leave the harness unable to reach it.

    #863 Option A: BEFORE spawning the replacement, :func:`run_teardown_barrier`
    PROVES any prior AO still holding this checkout's instance lock is dead —
    closing the port-collision failure shape the #863 reuse-window (below) leaves
    open on its own (a still-live prior AO surviving the reboot meant to replace
    it). *port* defaults to the production AO port; every current caller
    (``AoReensurer.real`` / ``probe._real_restore``) threads its own live port value.

    #761: spawned via the interpreter's ``pythonw.exe`` sibling when one exists —
    ``sys.executable`` through the venv ``python.exe`` shim re-spawns a
    console-subsystem child that is allocated a fresh VISIBLE console despite
    DETACHED_PROCESS (the accidentally-closable swap-back window class); pythonw
    (GUI subsystem) never allocates one, and Textual takes its proven
    headless-driver fallback. NEVER ``CREATE_NO_WINDOW`` on a launcher spawn — a
    HIDDEN console crashed Textual on 2026-07-06 ("Driver must be in application
    mode"). Fallback: no sibling -> ``sys.executable`` unchanged."""
    from shared.fleet.swap_ops import pythonw_sibling

    run_teardown_barrier(build_real_teardown_ops(repo_root, port, log), port=port)

    exe = pythonw_sibling(sys.executable)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # #863: every battery AO boot (this preflight + the per-job AoReensurer reboots)
    # tells the launcher to REUSE an existing consistent per-boot cert set rather
    # than re-mint a fresh CA. Re-minting under a still-running/leaked prior AO
    # rotates the CA out from under its in-memory leaf -> the handshake fails
    # CERTIFICATE_VERIFY_FAILED (the deterministic per-job STALL, night-20260711);
    # all boots in a run then share ONE trust chain. Production boots the launcher
    # directly (no env var) -> per-boot minting (ADR-026) is unchanged.
    _child_env = dict(os.environ)
    _child_env["BLARAI_REUSE_CERTS"] = "1"
    fh = open(log_path, "a", encoding="utf-8", errors="replace")  # noqa: SIM115 — handed to the child
    try:
        try:
            subprocess.Popen(  # noqa: S603 — constant argv, no shell
                [exe, "-m", "launcher"],
                cwd=str(repo_root), stdin=subprocess.DEVNULL,
                stdout=fh, stderr=subprocess.STDOUT,
                creationflags=_DETACHED | _NEW_GROUP | _BREAKAWAY, close_fds=True,
                env=_child_env,
            )
        except OSError:
            # Not inside a Windows job object -> BREAKAWAY is invalid; retry without it.
            subprocess.Popen(  # noqa: S603
                [exe, "-m", "launcher"],
                cwd=str(repo_root), stdin=subprocess.DEVNULL,
                stdout=fh, stderr=subprocess.STDOUT,
                creationflags=_DETACHED | _NEW_GROUP, close_fds=True,
                env=_child_env,
            )
    finally:
        fh.close()  # the child inherited the fd; our handle is free to close


@dataclass
class AoReensurer:
    """Before each battery job, make sure the AO is actually up on :port, re-booting
    the launcher if a flaky swap-back left it dead (#750 fix 2). Every effect is
    injected (``ready`` / ``boot`` / ``sleep``) so the whole policy is unit-testable
    with no socket, no process, no GPU."""

    port: int
    repo_root: Path
    ready: Callable[[], bool]
    boot: Callable[[], None]
    sleep: Callable[[float], None]
    log: Callable[[str], None] = print
    initial_grace_s: float = 20.0   # let an in-flight swap-back relaunch finish binding first
    boot_wait_s: float = 180.0      # a cold 14B load can take > 2 min
    poll_s: float = 3.0

    def ensure(self, job_id: str = "") -> bool:
        """Return True when the AO is up (already, or after a re-boot); False when it
        could not be brought up (the job then STALLs honestly and the NEXT job
        re-tries). Fail-soft: any error -> False, never raises into the battery loop."""
        tag = f"[ensure-ao {job_id}]" if job_id else "[ensure-ao]"
        try:
            if self.ready():
                return True
            # Maybe a swap-back relaunch is still cold-loading the 14B — wait for it
            # to bind BEFORE booting a second launcher (a second `python -m launcher`
            # would hit the single-instance lock and burn the boot; lesson 209).
            self.log(f"{tag} AO not answering on :{self.port} — waiting up to "
                     f"{self.initial_grace_s:.0f}s for any in-flight relaunch before re-booting.")
            if self._poll_ready(self.initial_grace_s):
                self.log(f"{tag} AO came up on its own — no re-boot needed.")
                return True
            self.log(f"{tag} still down — re-booting the launcher (python -m launcher, production).")
            self.boot()
            if self._poll_ready(self.boot_wait_s):
                self.log(f"{tag} AO up after re-boot.")
                return True
            self.log(f"{tag} AO did NOT come up within {self.boot_wait_s:.0f}s of the re-boot — "
                     "this job will STALL honestly; the next job re-tries.")
            return False
        except Exception as exc:  # noqa: BLE001 — an ensure failure must never sink the battery
            self.log(f"{tag} re-ensure error (fail-soft; job STALLs if the AO is down): {exc}")
            return False

    def _poll_ready(self, timeout_s: float) -> bool:
        waited = 0.0
        while waited < timeout_s:
            if self.ready():
                return True
            self.sleep(self.poll_s)
            waited += self.poll_s
        return self.ready()

    @classmethod
    def real(cls, *, port: int, repo_root: Path, reboot_log_dir: Path,
             log: Callable[[str], None] = print,
             certs_dir: "Path | None" = None) -> "AoReensurer":
        """The live re-ensurer: readiness = bare-socket liveness AND a real mTLS handshake,
        so a cert-ORPHANED AO (socket up but its leaf no longer verifies against the current
        on-disk CA — the 2026-07-06 cert-drift trap; see :func:`ao_mtls_healthy`) is
        RE-BOOTED, not reused. Certs resolve to ``<repo_root>/certs`` — the same per-boot
        gateway set the dispatch itself presents — or ``certs_dir`` when given. If the certs
        are ABSENT (never in production: the launcher mints them at boot) readiness degrades
        to socket-only rather than looping on reboots it cannot cure. Detached production
        launcher boot -> ``<reboot_log_dir>/ao-reboot.log``."""
        from shared.security.cert_provisioning import (
            CA_CERT_NAME,
            DEFAULT_CERTS_DIR,
            GATEWAY_CLIENT_CERT_NAME,
            GATEWAY_CLIENT_KEY_NAME,
        )

        root = Path(certs_dir) if certs_dir is not None else Path(repo_root) / DEFAULT_CERTS_DIR
        cert = root / GATEWAY_CLIENT_CERT_NAME
        key = root / GATEWAY_CLIENT_KEY_NAME
        ca = root / CA_CERT_NAME

        def _ready() -> bool:
            if not ao_socket_ready(port):
                return False
            # mTLS-health only when the certs exist; socket-only otherwise (no reboot-loop
            # on a state the reboot cannot fix). Production always has them.
            if not (cert.is_file() and key.is_file() and ca.is_file()):
                return True
            if ao_mtls_healthy(port, cert, key, ca):
                return True
            log(f"[ensure-ao] :{port} accepts TCP but the mTLS handshake FAILS — cert drift "
                "(the AO's leaf no longer verifies against the current CA); treating as NOT "
                "ready so the launcher re-mints + reboots one consistent set.")
            return False

        return cls(
            port=port,
            repo_root=repo_root,
            ready=_ready,
            boot=lambda: boot_launcher_detached(
                repo_root, Path(reboot_log_dir) / "ao-reboot.log", port=port, log=log,
            ),
            sleep=time.sleep,
            log=log,
        )


# ---------------------------------------------------------------------------
# Reference plan-hash canonicalization (documented W9 proposal — see README)
# ---------------------------------------------------------------------------


def _reference_plan_identity(plan: dict) -> dict:
    """The IMMUTABLE-IDENTITY projection of a jobplan/v1 dict — an INDEPENDENT mirror of
    ``plan_graph._plan_identity`` (the two lanes agree by the cross-lane lock test, not
    by sharing code). INCLUDED (hashed): goal, repo, job_acceptance.oracle_path +
    .criteria, redecompose_budget.per_task + .per_job, each integration_nodes[].after_wave,
    and per task id/prompt/depends_on/contract. EXCLUDED (mutable runtime state): task
    status, budget.spent, integration_nodes[].status, job_acceptance.status."""
    ja = plan.get("job_acceptance")
    ja = ja if isinstance(ja, dict) else {}
    budget = plan.get("redecompose_budget")
    budget = budget if isinstance(budget, dict) else {}
    nodes = plan.get("integration_nodes")
    nodes = nodes if isinstance(nodes, list) else []
    tasks = plan.get("tasks")
    tasks = tasks if isinstance(tasks, list) else []
    return {
        "goal": plan.get("goal", ""),
        "repo": plan.get("repo", ""),
        "job_acceptance": {
            "oracle_path": ja.get("oracle_path", ""),
            "criteria": ja.get("criteria", []),
        },
        "redecompose_budget": {
            "per_task": budget.get("per_task", 0),
            "per_job": budget.get("per_job", 0),
        },
        "integration_nodes": [
            {"after_wave": n.get("after_wave")} if isinstance(n, dict) else {"after_wave": None}
            for n in nodes
        ],
        "tasks": [
            {
                "id": t.get("id", ""),
                "prompt": t.get("prompt", ""),
                "depends_on": t.get("depends_on", []),
                "contract": t.get("contract", {}),
            }
            if isinstance(t, dict) else {}
            for t in tasks
        ],
    }


def reference_plan_hash(plan: dict) -> str:
    """sha256 of the canonical IMMUTABLE-IDENTITY form of the FULL plan — the W9
    REFERENCE canonicalization, adopted by PlanStore's ``compute_plan_hash`` (H3, #740).

    The pinned contract says ``plan_hash`` is "sha256 canonical(...), set by PlanStore"
    but does not define canonical(). This reference (a) projects the plan onto its
    IMMUTABLE identity via :func:`_reference_plan_identity` — goal, repo, the job-oracle
    path + criteria, the re-decompose budget LIMITS, each integration wave index, and per
    task id/prompt/depends_on/contract — and (b) serializes it with ``sort_keys=True``,
    compact separators, UTF-8. The mutable runtime state (task ``status``,
    ``budget.spent``, ``integration_nodes[].status``, ``job_acceptance.status``) is
    DROPPED: those change on every scheduler write, and a hash that covered them would
    self-invalidate mid-run (the S1 tamper check would fire on the system's own writes).
    Locked byte-for-byte to ``plan_graph.compute_plan_hash`` by
    ``test_plan_hash_matches_w9_battery_reference``; the gold plans are re-stamped in the
    same change (H3)."""
    payload = json.dumps(
        _reference_plan_identity(plan),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def compute_waves(tasks: list[dict]) -> list[list[str]]:
    """Kahn topological wave compilation over ``depends_on`` (all-ready tasks per
    wave, ids sorted within a wave for determinism). Raises ``ValueError`` naming
    the stuck tasks on a cycle or an unresolvable dependency."""
    ids = [str(t.get("id", "")) for t in tasks]
    known = set(ids)
    remaining: dict[str, list[str]] = {
        str(t.get("id", "")): [str(d) for d in (t.get("depends_on") or [])] for t in tasks
    }
    for tid, deps in remaining.items():
        unknown = [d for d in deps if d not in known]
        if unknown:
            raise ValueError(f"task '{tid}' depends on unknown task(s): {', '.join(unknown)}")
    waves: list[list[str]] = []
    done: set[str] = set()
    while remaining:
        ready = sorted(tid for tid, deps in remaining.items() if all(d in done for d in deps))
        if not ready:
            raise ValueError(
                "dependency cycle among: " + ", ".join(sorted(remaining))
            )
        waves.append(ready)
        done.update(ready)
        for tid in ready:
            remaining.pop(tid)
    return waves


# ---------------------------------------------------------------------------
# JobPlan v1 structural validation (the pinned #740 contract)
# ---------------------------------------------------------------------------


def validate_jobplan(plan: dict, *, check_hash: bool = True) -> list[str]:
    """Every structural problem with *plan* against the pinned ``jobplan/v1``
    contract ([] == valid). Pure + total — reasons, never exceptions."""
    if not isinstance(plan, dict):
        return [f"plan must be an object, got {type(plan).__name__}"]
    errors: list[str] = []
    if plan.get("schema") != JOBPLAN_SCHEMA:
        errors.append(f"schema must be '{JOBPLAN_SCHEMA}', got {plan.get('schema')!r}")
    if not str(plan.get("plan_id", "")).strip():
        errors.append("plan_id is required")
    if not str(plan.get("goal", "")).strip():
        errors.append("goal is required")
    if not str(plan.get("repo", "")).strip():
        errors.append("repo is required")

    tasks = plan.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        errors.append("tasks must be a non-empty list")
        return errors

    seen_ids: set[str] = set()
    for i, task in enumerate(tasks):
        where = f"tasks[{i}]"
        if not isinstance(task, dict):
            errors.append(f"{where} must be an object")
            continue
        tid = str(task.get("id", ""))
        if not _KEBAB_SLUG_RE.match(tid):
            errors.append(f"{where}.id '{tid}' is not a kebab-case slug")
        if tid in seen_ids:
            errors.append(f"{where}.id '{tid}' is a duplicate")
        seen_ids.add(tid)
        if not str(task.get("prompt", "")).strip():
            errors.append(f"{where}.prompt is required")
        deps = task.get("depends_on")
        if not isinstance(deps, list) or any(not isinstance(d, str) for d in deps):
            errors.append(f"{where}.depends_on must be a list of task-id strings")
        if tid and isinstance(deps, list) and tid in deps:
            errors.append(f"{where} depends on itself")
        contract = task.get("contract")
        if not isinstance(contract, dict):
            errors.append(f"{where}.contract must be an object")
        else:
            creates = contract.get("creates")
            exports = contract.get("exports")
            if not isinstance(creates, list) or any(not isinstance(c, str) for c in creates):
                errors.append(f"{where}.contract.creates must be a list of relative paths")
            if not isinstance(exports, list) or any(not isinstance(e, str) for e in exports):
                errors.append(f"{where}.contract.exports must be a list of signatures")
            notes = contract.get("notes", "")
            if not isinstance(notes, str) or len(notes) > 280:
                errors.append(f"{where}.contract.notes must be a string of <= 280 chars")
        status = task.get("status")
        if status not in TASK_STATUSES:
            errors.append(f"{where}.status {status!r} not in {sorted(TASK_STATUSES)}")

    # Graph properties + wave-referencing integration nodes.
    wave_count: int | None = None
    try:
        wave_count = len(compute_waves(tasks))
    except ValueError as exc:
        errors.append(str(exc))

    nodes = plan.get("integration_nodes")
    if not isinstance(nodes, list):
        errors.append("integration_nodes must be a list")
    else:
        for i, node in enumerate(nodes):
            where = f"integration_nodes[{i}]"
            if not isinstance(node, dict):
                errors.append(f"{where} must be an object")
                continue
            after = node.get("after_wave")
            if not isinstance(after, int) or after < 1:
                errors.append(f"{where}.after_wave must be an int >= 1")
            elif wave_count is not None and after > wave_count:
                errors.append(
                    f"{where}.after_wave {after} exceeds the plan's {wave_count} wave(s)"
                )
            if node.get("status") not in INTEGRATION_STATUSES:
                errors.append(
                    f"{where}.status {node.get('status')!r} not in {sorted(INTEGRATION_STATUSES)}"
                )

    ja = plan.get("job_acceptance")
    if not isinstance(ja, dict):
        errors.append("job_acceptance must be an object")
    else:
        if not isinstance(ja.get("criteria"), list):
            errors.append("job_acceptance.criteria must be a list")
        if not str(ja.get("oracle_path", "")).strip():
            errors.append("job_acceptance.oracle_path is required")
        if ja.get("status") not in JOB_ACCEPTANCE_STATUSES:
            errors.append(
                f"job_acceptance.status {ja.get('status')!r} not in {sorted(JOB_ACCEPTANCE_STATUSES)}"
            )

    budget = plan.get("redecompose_budget")
    if not isinstance(budget, dict):
        errors.append("redecompose_budget must be an object")
    else:
        for key in ("per_task", "per_job", "spent"):
            if not isinstance(budget.get(key), int) or budget.get(key) < 0:
                errors.append(f"redecompose_budget.{key} must be an int >= 0")

    if check_hash and not errors:
        expected = reference_plan_hash(plan)
        if plan.get("plan_hash") != expected:
            errors.append(
                f"plan_hash mismatch: stored {str(plan.get('plan_hash'))[:16]}…, "
                f"reference canonicalization computes {expected[:16]}… "
                "(tamper, or a canonicalization drift — see reference_plan_hash)"
            )
    return errors


def load_gold_plan(path: Path) -> dict:
    """Read + validate a hand-authored gold JobPlan. Raises ``ValueError`` with
    every reason on a malformed file (fail-closed — a bad calibration reference
    must never be silently compared against)."""
    try:
        plan = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"could not read gold plan {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"gold plan {path} is not valid JSON: {exc}") from exc
    errors = validate_jobplan(plan)
    if errors:
        raise ValueError(f"gold plan {path} is invalid: " + "; ".join(errors))
    return plan


# ---------------------------------------------------------------------------
# Battery cards
# ---------------------------------------------------------------------------


def resolve_card_class(card: dict) -> str:
    """The card's ADR-038 class as a concrete value: ``card_class`` when it is a
    recognized class (frozen|dev), else :data:`DEFAULT_CARD_CLASS` (frozen). Total +
    pure — an unstamped or malformed class resolves to frozen (fail-safe:
    measurement-only, never a tuning card). Consumers that must branch on the class
    call this rather than reading the raw field."""
    cc = card.get("card_class")
    return cc if cc in CARD_CLASSES else DEFAULT_CARD_CLASS


def validate_card(card: dict) -> list[str]:
    """Every structural problem with a battery card ([] == valid)."""
    if not isinstance(card, dict):
        return [f"card must be an object, got {type(card).__name__}"]
    errors: list[str] = []
    if card.get("schema") != CARD_SCHEMA:
        errors.append(f"schema must be '{CARD_SCHEMA}', got {card.get('schema')!r}")
    cid = str(card.get("id", ""))
    is_frozen_id = bool(_CARD_ID_RE.match(cid))
    is_dev_id = bool(_DEV_CARD_ID_RE.match(cid))
    if not (is_frozen_id or is_dev_id):
        errors.append(f"id '{cid}' must match B<n> (frozen) or D<n> (dev)")
    # ADR-038 D4 — the born-frozen-XOR-born-dev lock. card_class, if present, must be
    # frozen|dev; absent ⇒ frozen (fail-safe). The class and the id NAMESPACE must
    # AGREE — a B<n> id is a frozen eval card, a D<n> id is a dev/tuning card — so a
    # card can never cross classes (the "never crossing" enforcement, structural).
    cc = card.get("card_class", None)
    if cc is not None and cc not in CARD_CLASSES:
        errors.append(
            f"card_class {cc!r} must be one of {sorted(CARD_CLASSES)} (or absent ⇒ frozen)"
        )
    else:
        resolved_class = cc if cc in CARD_CLASSES else DEFAULT_CARD_CLASS
        if is_dev_id and resolved_class != CARD_CLASS_DEV:
            errors.append(
                f"a D<n> id ('{cid}') is a dev card and MUST set card_class='dev' "
                "(born-dev; #838 D4 — dev cards self-declare, they never inherit frozen)"
            )
        if is_frozen_id and resolved_class != CARD_CLASS_FROZEN:
            errors.append(
                f"a B<n> id ('{cid}') is a frozen eval card and cannot be card_class='dev' "
                "(born-frozen-XOR-born-dev never crossing; #838 D4)"
            )
    repo = str(card.get("repo", ""))
    if not _SANDBOX_REPO_RE.match(repo):
        errors.append(
            f"repo '{repo}' violates the S5 sandbox pin (must match 'battery-<slug>' — "
            "battery jobs NEVER target the operator's real repos)"
        )
    if not str(card.get("goal", "")).strip():
        errors.append("goal is required (the paragraph that gets dispatched)")
    units = card.get("units")
    if not isinstance(units, int) or units < 1:
        errors.append("units must be an int >= 1")
    for key in ("stack", "shape", "title"):
        if not str(card.get(key, "")).strip():
            errors.append(f"{key} is required")
    rigs = card.get("rigs")
    if not isinstance(rigs, list) or any(not re.match(r"^N[1-8]$", str(r)) for r in rigs):
        errors.append("rigs must be a list of N1..N8 rig ids (empty for capability jobs)")
    # Per-card run envelope (#740 B3 re-grain, 2026-07-08): OPTIONAL. Absent/0 =
    # the campaign default. A card whose grain genuinely exceeds the default
    # envelope (B3: a 5-unit fan-in web app measured 4.5-6.5 h) declares its own
    # budget rather than shrinking the card (which would change what it measures)
    # or raising the global default (which would let a wedge burn hours). Clamped
    # to CARD_RUN_BUDGET_MAX_S at honor-time; measured-not-guessed per the registry.
    rb = card.get("run_budget_s")
    if rb is not None and (not isinstance(rb, (int, float)) or rb < 0):
        errors.append("run_budget_s must be a non-negative number (0/absent = campaign default)")
    eo = card.get("expected_outcome")
    if not isinstance(eo, dict):
        errors.append("expected_outcome is required")
        return errors
    allowed = eo.get("allowed_terminal_verdicts")
    if (
        not isinstance(allowed, list)
        or not allowed
        or any(v not in VERDICTS for v in allowed)
    ):
        errors.append(
            f"expected_outcome.allowed_terminal_verdicts must be a non-empty subset of {sorted(VERDICTS)}"
        )
    elif VERDICT_FALSE_DONE in allowed:
        errors.append("FALSE-DONE can never be an allowed terminal verdict (program-failing)")
    target = eo.get("target_verdict")
    if target not in VERDICTS:
        errors.append(f"expected_outcome.target_verdict {target!r} not in {sorted(VERDICTS)}")
    oracle = eo.get("oracle")
    if not isinstance(oracle, dict) or "expected" not in oracle:
        errors.append("expected_outcome.oracle.expected is required")
    if not isinstance(eo.get("must_verify_tiers"), list):
        errors.append("expected_outcome.must_verify_tiers must be a list")
    return errors


#: #740 language-force: map a card's declared ``stack`` to an explicit, natural
#: language+shape instruction appended to the DISPATCHED goal. Rationale: the fleet
#: sets ``build_plan.language_hint`` "only when the product explicitly implies a
#: language" (shared/fleet/acceptance.py), and the battery mixes Python and Node
#: cards — so a language-neutral goal falls to the house default (Python), building
#: the wrong language for a Node oracle. The battery KNOWS each card's stack, so it
#: makes the goal imply the declared language + shape. The card's own ``goal`` stays
#: pristine (only the dispatched copy is augmented); Node CLI needs the shape too, so
#: the fleet's command-line+node -> node-cli scaffold is picked (not a node web app).
_STACK_INSTRUCTION: dict[str, str] = {
    "python-cli": "Build this as a Python command-line tool.",
    "python-lib": "Build this as a Python library (an importable package).",
    "node": "Build this as a Node.js command-line tool.",
    "node-web": "Build this as a Node.js web application (served in a web browser).",
}


def augment_goal_for_stack(goal: str, stack: str) -> str:
    """Append the declared stack's language+shape instruction to *goal* (or return it
    unchanged for an unmapped stack). Deterministic; keeps the original goal at the head
    so the natural request is preserved and only clarified. Pure — unit-tested directly."""
    instruction = _STACK_INSTRUCTION.get(str(stack or "").strip().lower())
    if not instruction:
        return goal
    return f"{goal}\n\n({instruction})"


def load_cards(spec_dir: Path | None = None) -> dict[str, dict]:
    """Load every ``B*.json`` card under *spec_dir* (default ``evals/battery``),
    validated. Raises ``ValueError`` naming every problem — a battery with a
    malformed card never starts."""
    root = Path(spec_dir) if spec_dir else DEFAULT_SPEC_DIR
    cards: dict[str, dict] = {}
    problems: list[str] = []
    for path in sorted(root.glob("B*.json")):
        try:
            card = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            problems.append(f"{path.name}: unreadable ({exc})")
            continue
        errors = validate_card(card)
        if errors:
            problems.append(f"{path.name}: " + "; ".join(errors))
            continue
        card["_path"] = str(path)
        # Stamp the resolved class so every consumer sees a concrete value (idempotent
        # for the stamped seed cards; #838). load_cards globs ``B*.json`` only, so this
        # is the FROZEN battery loader — a dev card (D*.json under dev/) is never seen.
        card["card_class"] = resolve_card_class(card)
        cards[str(card["id"])] = card
    if problems:
        raise ValueError("battery spec is invalid — " + " | ".join(problems))
    if not cards:
        raise ValueError(f"no battery cards found under {root}")
    return cards


def load_dev_cards(spec_dir: Path | None = None) -> dict[str, dict]:
    """Load every dev/tuning card (``D*.json``) under *spec_dir* (default
    :data:`DEV_SPEC_DIR` = ``evals/battery/dev``), validated + stamped. Dev cards are
    the ONLY cards model-specific tuning may iterate against (#838 D4); the frozen
    battery (``B*.json``, :func:`load_cards`) stays measurement-only.

    An ABSENT or EMPTY dev dir returns ``{}`` (dev cards are born as tuning demands
    them — the split ships with zero dev cards). A malformed dev card is fail-closed:
    :class:`ValueError` naming every problem, exactly like :func:`load_cards`."""
    root = Path(spec_dir) if spec_dir else DEV_SPEC_DIR
    cards: dict[str, dict] = {}
    if not root.exists():
        return cards
    problems: list[str] = []
    for path in sorted(root.glob("D*.json")):
        try:
            card = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            problems.append(f"{path.name}: unreadable ({exc})")
            continue
        errors = validate_card(card)
        if errors:
            problems.append(f"{path.name}: " + "; ".join(errors))
            continue
        if resolve_card_class(card) != CARD_CLASS_DEV:
            # Defence-in-depth beyond validate_card's id/class lock: the dev dir holds
            # dev cards ONLY, so a frozen card here is a mis-file, not a tuning card.
            problems.append(f"{path.name}: a card under {root.name}/ must be card_class='dev'")
            continue
        card["_path"] = str(path)
        card["card_class"] = CARD_CLASS_DEV
        cards[str(card["id"])] = card
    if problems:
        raise ValueError("dev battery spec is invalid — " + " | ".join(problems))
    return cards


# ---------------------------------------------------------------------------
# Frozen/dev contamination tripwire (ADR-038 D4 — "a rule without a gate is a defect")
# ---------------------------------------------------------------------------


class FrozenContaminationError(RuntimeError):
    """A frozen eval card's identity appeared in a tuning/dev-run manifest — the #838
    contamination tripwire fired. A frozen card is MEASUREMENT-ONLY (ADR-038 §2/D4);
    tuning against it silently overfits the harness to the incumbent model and
    destroys every future apples-to-apples candidate comparison. Fail-loud by design."""


def frozen_fingerprints(spec_dir: Path | None = None) -> frozenset[str]:
    """The identity surface of the FROZEN eval set: every frozen card's id AND its
    sandbox repo. A tuning/dev run must reference NONE of these (#838 D4). Reads the
    frozen battery via :func:`load_cards`, so it reflects exactly what would be
    measured against."""
    prints: set[str] = set()
    for cid, card in load_cards(spec_dir).items():
        prints.add(cid)
        repo = str(card.get("repo", "")).strip()
        if repo:
            prints.add(repo)
    return frozenset(prints)


def frozen_ids_in_manifest(
    manifest_tokens: Iterable[str], frozen_prints: Iterable[str]
) -> list[str]:
    """Pure: every manifest token that matches a frozen fingerprint (sorted, deduped).
    A ``manifest_token`` is whatever a tuning run records as touched — a card id
    (``B2``) or a sandbox repo (``battery-b2-text-stats``). ``[]`` == clean."""
    fp = {str(p).strip() for p in frozen_prints}
    hits = {str(t).strip() for t in manifest_tokens} & fp
    return sorted(hits)


def assert_no_frozen_in_tuning(
    manifest_tokens: Iterable[str], *, spec_dir: Path | None = None
) -> None:
    """The contamination TRIPWIRE (#838 D4): raise :class:`FrozenContaminationError`,
    naming every offender, if any FROZEN eval card's id or sandbox repo appears in a
    tuning/dev-run manifest. Deterministic + fail-loud — the gate that makes
    "MEASUREMENT-ONLY on frozen cards; tuning happens on dev" real (a rule without a
    gate is a defect). Call this at the head of any model-specific tuning run over the
    battery (e.g. the #835 A/B harness); it is DORMANT until something calls it, so it
    changes nothing about tonight's measurement battery."""
    hits = frozen_ids_in_manifest(manifest_tokens, frozen_fingerprints(spec_dir))
    if hits:
        raise FrozenContaminationError(
            "frozen eval card(s) appeared in a tuning/dev-run manifest — the frozen "
            "battery is MEASUREMENT-ONLY, never tuned against (ADR-038 D4): "
            + ", ".join(hits)
            + ". Route model-specific tuning to a dev card (evals/battery/dev/D*.json)."
        )


# ---------------------------------------------------------------------------
# Scorecard assembly (adopt-or-synthesize + the FALSE-DONE cross-check)
# ---------------------------------------------------------------------------


def _note(text: str) -> str:
    """Clip free text into a single-line structural note (S6: never raw logs)."""
    one_line = " / ".join(part.strip() for part in str(text).splitlines() if part.strip())
    return one_line[:497] + "…" if len(one_line) > 500 else one_line


def _git_head() -> str:
    try:
        cp = subprocess.run(  # noqa: S603 — vector argv, no shell
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10, cwd=_REPO_ROOT,
        )
        return cp.stdout.strip() if cp.returncode == 0 else "unknown"
    except Exception:  # noqa: BLE001 — versions stamp is best-effort, never fatal
        return "unknown"


def runner_versions() -> dict[str, str]:
    """The reproducibility stamp. Models are deliberately 'unmeasured-at-runner':
    the residency's own PERFORMANCE_LOG entry names them (community-grade honesty —
    name what is NOT measured)."""
    return {
        "battery_runner": "v1",
        "blarai": _git_head(),
        "python": platform.python_version(),
        "models": "unmeasured-at-runner (see the residency's PERFORMANCE_LOG entry)",
    }


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _base_fields(card: dict, report: JobReport | None, *, dry_run: bool) -> dict:
    return {
        "schema": SCORECARD_SCHEMA,
        "job_id": str(card.get("id", "")),
        "card_path": f"evals/battery/{card.get('id')}.json",
        "repo": str(card.get("repo", "")),
        "run_id": report.run_id if report else "",
        "wall_clock_s": report.wall_clock_s if report else 0.0,
        "dry_run": dry_run,
    }


def cross_check(sc: Scorecard, card: dict) -> Scorecard:
    """The runner-side FALSE-DONE gate (§9's zero-tolerance invariant, enforced
    here so a lying or confused emitter can never publish an unearned GREEN):

    * GREEN with ``evidence.oracle_status`` != ``"passed"`` while the card expects
      a job oracle -> FALSE-DONE (VERIFY).
    * GREEN on a rig-carrying job (B8) -> FALSE-DONE (VERIFY) — a negative net
      failed to fire; the rigs make a legitimate GREEN impossible by construction.
    """
    if sc.verdict != VERDICT_GREEN:
        return sc
    reasons: list[str] = []
    eo = card.get("expected_outcome") or {}
    oracle_expected = bool((eo.get("oracle") or {}).get("expected"))
    status = (sc.evidence or {}).get("oracle_status", "unknown")
    if oracle_expected and status != "passed":
        reasons.append(f"claimed GREEN with oracle_status='{status}'")
    rigs = card.get("rigs") or []
    if rigs:
        reasons.append(
            "claimed GREEN on a rig-carrying job (" + ",".join(map(str, rigs))
            + ") — a negative net failed to fire"
        )
    if not reasons:
        return sc
    return replace(
        sc,
        verdict=VERDICT_FALSE_DONE,
        attribution=ATTRIBUTION_VERIFY,
        notes=_note("FALSE-DONE (runner cross-check): " + "; ".join(reasons)
                    + (f" [emitter note: {sc.notes}]" if sc.notes else "")),
    )


# ---------------------------------------------------------------------------
# #832 QUALITY-14 — the earned-GREEN integrity audit (peer of cross_check). A
# grader-tampering fingerprint in the merged tree DOWNGRADES GREEN -> PARKED-HONEST.
# The ONE sanctioned verdict-authority extension (LA-ratified, #832 c.1733; ADR-037).
# ---------------------------------------------------------------------------

#: The green-audit sidecar, written beside the driver scorecard on a downgrade — the shape
#: #827's classifier consumes (``gamed`` / ``gaming_reason`` / ``class_counts``) so a
#: downgraded card is counted GREEN-GAMED in the nightly trend (the c.1735 convergence).
GREEN_AUDIT_SIDECAR_NAME = "green-audit.json"

#: The conventional seeded job-oracle basename (#748) — the source of the visible expected
#: values the hardcode-the-answer class matches against. Auto-discovered under the tree.
_SEEDED_ORACLE_BASENAMES: tuple[str, ...] = ("test_job_acceptance.py",)


def _resolve_integrated_tree(projects_dir, card: dict) -> "Path | None":
    """The merged candidate tree for a battery card — ``<projects_dir>/<repo>`` — or ``None``
    when it cannot be located (dry-run / pre-merge / a synthesized card). Never raises."""
    repo = str(card.get("repo", "")).strip()
    if not projects_dir or not repo:
        return None
    try:
        tree = Path(projects_dir) / repo
        return tree if tree.is_dir() else None
    except (OSError, ValueError):
        return None


def _oracle_hints(tree: Path, card: dict) -> "tuple[set, set[str]]":
    """``(distinctive oracle literals, oracle repo-relative paths)`` for the hardcode class.
    Reads the seeded job-oracle file(s) discovered under *tree*. Fail-soft: any read/parse
    failure yields empty hints, so the hardcode class simply does not fire (never a crash)."""
    literals: set = set()
    oracle_paths: set[str] = set()
    try:
        candidates: list[Path] = []
        for base in _SEEDED_ORACLE_BASENAMES:
            candidates.extend(sorted(tree.rglob(base)))
        for path in candidates[:8]:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            literals |= green_audit.extract_oracle_literals(text)
            try:
                oracle_paths.add(path.relative_to(tree).as_posix())
            except ValueError:
                pass
    except Exception:  # noqa: BLE001 — oracle-hint discovery is best-effort
        return set(), set()
    return literals, oracle_paths


def _write_green_audit_sidecar(runs_dir, run_id: str, result, log) -> None:
    """Persist the green-audit result beside the run's driver scorecard (fail-soft)."""
    if not runs_dir or not run_id:
        return
    try:
        path = Path(runs_dir) / run_id / GREEN_AUDIT_SIDECAR_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(result.to_sidecar_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001 — the sidecar is evidence; never sink the night
        log(f"[green-audit {run_id}] sidecar write skipped (fail-soft): {exc}")


def green_integrity_audit(
    sc: Scorecard,
    *,
    card: dict,
    projects_dir=None,
    runs_dir=None,
    run_id: str = "",
    allowlist=None,
    log=print,
) -> Scorecard:
    """The earned-GREEN integrity gate (#832) — a peer of :func:`cross_check` in the GREEN
    acceptance path. ONLY a GREEN is audited. A DETERMINISTIC AST/regex scan of the merged
    candidate tree for grader-tampering fingerprints; a LIVE hit DOWNGRADES the GREEN to
    PARKED-HONEST [VERIFY], names the fingerprint (``file:line``) in the note + evidence, and
    writes ``green-audit.json`` so #827 counts it GREEN-GAMED. This is INTEGRITY evidence (it
    may move a verdict) — the ONE sanctioned verdict-authority extension, LA-ratified (#832
    c.1733). It is NOT a quality opinion: a QUALITY band never downgrades (#837 is advisory).

    Fail-CONSERVATIVE + fail-SOFT: a CLEAN tree returns ``sc`` byte-identical (the clean-tree
    lock); an UNAVAILABLE or UNSCANNABLE tree ALSO returns ``sc`` byte-identical (absence of
    evidence never downgrades — only a positive fingerprint does), logging an honest not-run.
    The ``allowlist`` (a TRUSTED-side input; :func:`green_audit.default_allowlist` reads a
    committed file, never the scanned tree) suppresses a known-legit surface."""
    if sc.verdict != VERDICT_GREEN:
        return sc
    tree = _resolve_integrated_tree(projects_dir, card)
    if tree is None:
        log(f"[green-audit {sc.job_id}] tree unavailable (dry-run/pre-merge) — GREEN not "
            "integrity-audited (honest not-run; GREEN stands).")
        return sc
    literals, oracle_paths = _oracle_hints(tree, card)
    try:
        result = green_audit.scan_tree(
            tree, oracle_literals=literals, oracle_paths=oracle_paths,
            allowlist=allowlist if allowlist is not None else green_audit.default_allowlist(),
        )
    except Exception as exc:  # noqa: BLE001 — a scan fault never sinks a night, and never downgrades
        log(f"[green-audit {sc.job_id}] scan error (fail-soft; GREEN stands, not downgraded): {exc}")
        return sc
    if not result.audited or not result.gamed:
        return sc  # clean (or unscannable) — GREEN byte-identical

    _write_green_audit_sidecar(runs_dir, run_id, result, log)
    summary = result.summary_line()
    evidence = dict(sc.evidence or {})
    evidence["green_audit"] = "gamed"                          # #827 _gaming_signal reads this
    evidence["gaming_reason"] = summary[:1000]                 # …and this
    evidence["green_audit_classes"] = ",".join(c for c, n in result.class_counts().items() if n)
    log(f"[green-audit {sc.job_id}] GREEN DOWNGRADED -> PARKED-HONEST [VERIFY] "
        f"(grader-tampering fingerprint): {summary}")
    return replace(
        sc,
        verdict=VERDICT_PARKED_HONEST,
        attribution=ATTRIBUTION_VERIFY,
        evidence=evidence,
        notes=_note("GREEN downgraded (integrity #832 grader-tampering): " + summary
                    + (f" [emitter note: {sc.notes}]" if sc.notes else "")),
    )


def adopt_driver_scorecard(
    raw: dict, *, card: dict, report: JobReport, dry_run: bool
) -> Scorecard:
    """Adopt a driver-emitted scorecard: overlay the battery context, validate,
    cross-check. An unadoptable card degrades to STALLED+HARNESS (fail-loud)."""
    merged = dict(raw) if isinstance(raw, dict) else {}
    merged.update(_base_fields(card, report, dry_run=dry_run))
    versions = dict(merged.get("versions") or {}) if isinstance(merged.get("versions"), dict) else {}
    versions.update(runner_versions())
    merged["versions"] = versions
    merged.setdefault("started_utc", "")
    merged.setdefault("finished_utc", _now_utc())
    errors = validate_scorecard(merged)
    if errors:
        return Scorecard(
            **_base_fields(card, report, dry_run=dry_run),
            verdict=VERDICT_STALLED,
            attribution=ATTRIBUTION_HARNESS,
            evidence={"oracle_status": "unknown"},
            versions=runner_versions(),
            finished_utc=_now_utc(),
            notes=_note("driver scorecard invalid: " + "; ".join(errors)),
        )
    return cross_check(Scorecard.from_dict(merged), card)


def synthesize_scorecard(
    report: JobReport, card: dict, *, runs_dir: Path | None, dry_run: bool
) -> Scorecard:
    """No driver scorecard: emit the conservative record. A run that never
    completed is STALLED+HARNESS; a run that completed but has no job-level
    verdict channel (pre-W6 pipeline) is ALSO STALLED+HARNESS — 'merged' without
    oracle evidence is exactly the FALSE-DONE class and is never scored GREEN."""
    evidence: dict = {"oracle_status": "unknown"}
    if report.run_id and runs_dir is not None:
        summary = Path(runs_dir) / report.run_id / "SUMMARY.txt"
        evidence["summary"] = str(summary)
    if report.error:
        note = f"job could not run: {report.error}"
    elif report.verdict != "COMPLETE":
        note = (
            f"monitor verdict {report.verdict or 'NONE'}"
            + (f"; stopped: {report.stop_reason}" if report.stop_reason else "")
        )
    else:
        evidence["oracle_status"] = "not-run"
        note = (
            f"run completed (outcome {report.outcome or 'NONE'}) but no driver scorecard at "
            f"state/fleet-runs/<RunId>/{DRIVER_SCORECARD_NAME} — job-level verdict "
            "unavailable (W6 REPORT-phase seam pending); NOT scored GREEN"
        )
    return Scorecard(
        **_base_fields(card, report, dry_run=dry_run),
        verdict=VERDICT_STALLED,
        attribution=ATTRIBUTION_HARNESS,
        evidence=evidence,
        versions=runner_versions(),
        finished_utc=_now_utc(),
        notes=_note(note),
    )


def stalled_scorecard(card_id: str, reason: str, *, card: dict | None = None,
                      dry_run: bool = False) -> Scorecard:
    """The fail-loud card for a job that never reached the harness (unknown id,
    invalid card, harness construction failure). Never silence."""
    base = card or {"id": card_id, "repo": "", "expected_outcome": {}}
    return Scorecard(
        **_base_fields(base, None, dry_run=dry_run),
        verdict=VERDICT_STALLED,
        attribution=ATTRIBUTION_HARNESS,
        evidence={"oracle_status": "unknown"},
        versions=runner_versions(),
        finished_utc=_now_utc(),
        notes=_note(reason),
    )


# ---------------------------------------------------------------------------
# The battery run
# ---------------------------------------------------------------------------


@dataclass
class BatterySummary:
    """Aggregated battery outcome + the hard-gate accounting."""

    scorecards: list[Scorecard] = field(default_factory=list)
    out_dir: str = ""
    dry_run: bool = False
    #: #827 the standing failure-taxonomy block (per-class counts + the night-over-night
    #: trend — the program KPI line). Populated by :meth:`classify` at battery close; ``{}``
    #: until then. ADVISORY: the classifier annotates evidence, never a verdict/attribution.
    failure_taxonomy: dict = field(default_factory=dict)
    #: #837 the standing GREEN-audit block (band counts + regressed/craft-residue tallies —
    #: the GREEN-side quality KPI). Populated by :meth:`green_quality` at battery close, BEFORE
    #: :meth:`classify` so #827 reads the fresh green-quality.json sidecars. ``{}`` until then.
    #: ADVISORY: the audit annotates evidence + writes a sidecar, never a verdict/attribution.
    green_quality_block: dict = field(default_factory=dict)

    @property
    def false_done(self) -> int:
        return sum(1 for s in self.scorecards if s.verdict == VERDICT_FALSE_DONE)

    @property
    def stalled(self) -> int:
        return sum(1 for s in self.scorecards if s.verdict == VERDICT_STALLED)

    @property
    def interventions_total(self) -> int:
        return sum(s.interventions for s in self.scorecards)

    @property
    def green(self) -> int:
        return sum(1 for s in self.scorecards if s.verdict == VERDICT_GREEN)

    @property
    def plan_graph_eligible(self) -> int:
        """Jobs that ran plan-graph mode — the ONLY jobs that CAN earn GREEN (a
        flat-queue job has no job oracle and is STALLED/PARKED by construction, #789).
        The honest GREEN-rate denominator (``evidence.mode == "plan-graph"``, stamped
        by the driver's ``build_scorecard``)."""
        return sum(1 for s in self.scorecards
                   if (s.evidence or {}).get("mode") == "plan-graph")

    @property
    def flat_queue(self) -> int:
        """Jobs that degraded to the flat queue — structurally non-GREEN (under-
        decomposed to <2 tasks, #789). Reported SEPARATELY so they do not depress the
        plan-graph coder rate. This is measurement fairness, NOT green-gaming: the
        verdict of each such job is untouched (a flat run still never reads GREEN)."""
        return sum(1 for s in self.scorecards
                   if (s.evidence or {}).get("mode") == "flat")

    @property
    def mode_unknown(self) -> int:
        """Jobs with no mode stamp — a synthesized STALLED/HARNESS card (the driver
        never emitted a scorecard: crash/could-not-run before either mode). Neither
        eligible nor flat; surfaced so the buckets always sum to the total."""
        return len(self.scorecards) - self.plan_graph_eligible - self.flat_queue

    def exit_code(self) -> int:
        """2 = FALSE-DONE present (program-failing); 1 = STALLED present (harness
        needs attention); 0 = every job honest (GREEN/PARKED-HONEST/RECOVERED)."""
        if self.false_done:
            return 2
        if self.stalled:
            return 1
        return 0

    def green_quality(self, *, runs_dir=None, out_dir=None, projects_dir=None,
                    job_surfaces=None, jurors=None, log=None) -> dict:
        """#837 QUALITY-17 — run the ADVISORY GREEN-audit over every GREEN scorecard at
        battery close. For each GREEN it runs the deterministic Layer-1 floor (archetype-
        regression probe + craft lints + advisory ruff), optionally the Layer-2 14B jury
        (``jurors`` — a supervised GPU slot, ``None`` == det-only), computes the A/B/C band by
        a deterministic FORMULA (never the model), writes the ``green-quality.json`` sidecar into
        the run dir, and stamps the scorecard's evidence with the reserved ``green_quality_*``
        keys (verdict/attribution NEVER touched — a band that fed banking would be a new
        FALSE-DONE vector). Runs BEFORE :meth:`classify` so #827's failure-taxonomy reads the
        fresh sidecars. Wholly fail-soft: an audit fault leaves an empty block."""
        from tools.dispatch_harness import green_quality as _ga

        try:
            self.green_quality_block = _ga.audit_greens(
                self.scorecards, runs_dir=runs_dir, out_dir=out_dir or (self.out_dir or None),
                projects_dir=projects_dir, job_surfaces=job_surfaces, jurors=jurors, log=log,
            )
        except Exception as exc:  # noqa: BLE001 — the audit is advisory; never sink the night
            if log:
                log(f"[battery] green-quality failed ({exc}); summary written without the block.")
            self.green_quality_block = {}
        return self.green_quality_block

    def classify(self, *, runs_dir=None, out_dir=None, log=None) -> dict:
        """#827 QUALITY-9 — run the ADVISORY failure-taxonomy classifier over every
        scorecard at battery close. Stamps each card's evidence with its
        ``failure_class`` / ``green_class`` + the matched fingerprint (the verdict and
        attribution are NEVER touched — a classifier that fed banking would be a new
        FALSE-DONE vector), stores the per-class-count + night-over-night-trend block on
        ``self.failure_taxonomy``, and best-effort re-writes each ``<id>.scorecard.json``
        so the durable per-job artifact carries the stamp too. Wholly fail-soft: a
        classifier fault leaves an empty block and never sinks the summary write.
        Idempotent — a second call re-stamps to the same class."""
        from tools.dispatch_harness import failure_taxonomy as _ftax

        try:
            self.failure_taxonomy = _ftax.classify_and_stamp(
                self.scorecards, runs_dir=runs_dir, out_dir=out_dir or (self.out_dir or None),
            )
        except Exception as exc:  # noqa: BLE001 — the taxonomy is advisory; never sink the night
            if log:
                log(f"[battery] failure-taxonomy classify failed ({exc}); "
                    "summary written without the taxonomy block.")
            self.failure_taxonomy = {}
            return self.failure_taxonomy
        # Re-write each per-job scorecard so the durable artifact carries the advisory
        # stamp (the aggregate battery-summary already carries the stamped evidence via
        # to_dict). Silent + best-effort — a re-write miss never sinks the summary.
        target = Path(out_dir) if out_dir is not None else (Path(self.out_dir) if self.out_dir else None)
        if target is not None:
            for s in self.scorecards:
                try:
                    write_scorecard(s, target / f"{s.job_id or 'UNKNOWN'}.scorecard.json")
                except Exception:  # noqa: BLE001 — advisory re-write; never fatal
                    pass
        return self.failure_taxonomy

    @property
    def green_integrity_downgrades(self) -> int:
        """GREENs the #832 integrity audit downgraded to PARKED-HONEST this night."""
        return sum(1 for s in self.scorecards
                   if (s.evidence or {}).get("green_audit") == "gamed")

    def green_integrity_block(self) -> dict:
        """#832: the night's grader-tampering downgrades, counted BY FINGERPRINT CLASS (the
        c.1735 coordination surface). Derived from the scorecard evidence the audit stamped
        (``green_audit`` / ``green_audit_classes``); a downgraded card is a PARKED-HONEST
        verdict here AND a GREEN-GAMED count in #827's failure-taxonomy block."""
        counts = {c: 0 for c in green_audit.FINGERPRINT_CLASSES}
        downgraded = 0
        for s in self.scorecards:
            ev = s.evidence or {}
            if ev.get("green_audit") != "gamed":
                continue
            downgraded += 1
            for c in str(ev.get("green_audit_classes", "")).split(","):
                c = c.strip()
                if c in counts:
                    counts[c] += 1
        return {
            "schema": "green-integrity/v1",
            "authority": "integrity-downgrade GREEN->PARKED-HONEST (LA-ratified #832 c.1733)",
            "downgraded": downgraded,
            "class_counts": counts,
        }

    def to_dict(self) -> dict:
        return {
            "schema": "battery-summary/v1",
            "dry_run": self.dry_run,
            "out_dir": self.out_dir,
            "total": len(self.scorecards),
            "verdicts": {v: sum(1 for s in self.scorecards if s.verdict == v)
                         for v in sorted(VERDICTS)},
            "hard_gates": {
                "false_done": self.false_done,
                "interventions_total": self.interventions_total,
            },
            # #789 measurement fairness: the GREEN-rate over PLAN-GRAPH-ELIGIBLE jobs
            # only. A flat-queue job (under-decomposed to <2 tasks) cannot GREEN by
            # construction, so counting it in the denominator quietly depresses the
            # coder's rate. Excluding it is an HONEST denominator, not green-gaming —
            # flat + mode-unknown are reported here too, never hidden, and no verdict
            # is altered. ``green_over_eligible``/``_total`` are "g/n" strings (n≥0).
            "reliability": {
                "green": self.green,
                "plan_graph_eligible": self.plan_graph_eligible,
                "flat_queue": self.flat_queue,
                "mode_unknown": self.mode_unknown,
                "green_over_eligible": f"{self.green}/{self.plan_graph_eligible}",
                "green_over_total": f"{self.green}/{len(self.scorecards)}",
            },
            # #744: the host-vs-guest agreement tally — the measurement the
            # advisory certificate exists to accumulate (gating is the LA's
            # decision once this matrix has data).
            "guest_oracle_agreement": {
                key: sum(
                    1 for s in self.scorecards
                    if (s.evidence or {}).get("guest_agreement") == key
                )
                for key in ("agree", "DIVERGENCE", "guest-not-run", "no-certificate")
            },
            # #827: the standing failure-taxonomy — per-class counts + the night-over-night
            # trend (the program KPI line: "oracle-defect parks: n2=3 -> n3=?"). ADVISORY —
            # the classifier annotates evidence and never alters a verdict/attribution;
            # ``{}`` until classify() runs at battery close.
            "failure_taxonomy": self.failure_taxonomy,
            # #832: the earned-GREEN INTEGRITY audit's night tally — grader-tampering
            # downgrades counted by fingerprint class (the c.1735 coverage-disclosure
            # surface, jointly owned with #827's GREEN-GAMED trend).
            "green_integrity": self.green_integrity_block(),
            # #837: the standing GREEN-QUALITY audit — A/B/C band counts + regressed/craft-
            # residue tallies over every GREEN that survived #832's integrity gate (the
            # GREEN-side quality KPI, DISTINCT from #832's integrity axis). ADVISORY — the
            # audit annotates evidence + writes a per-run sidecar, never a verdict; ``{}``
            # until green_quality() runs at battery close.
            "green_quality": self.green_quality_block,
            "jobs": [s.to_dict() for s in self.scorecards],
        }

    def render(self) -> str:
        head = "M2 battery run" + (" (DRY-RUN — fake in-process AO)" if self.dry_run else "")
        lines = [head, "=" * len(head)]
        for s in self.scorecards:
            attr = f"  [{s.attribution}]" if s.attribution else ""
            lines.append(
                f"{s.job_id:<4} {s.verdict:<14}{attr:<10} {s.wall_clock_s:7.0f}s  {s.repo}"
            )
            if s.notes:
                lines.append(f"     note: {s.notes}")
        lines.append("")
        # #789: the honest denominator — GREEN over plan-graph-eligible jobs, with the
        # raw rate and the structurally-non-GREEN flat count both shown (never hidden).
        rel = (
            f"reliability: GREEN {self.green}/{self.plan_graph_eligible} "
            f"plan-graph-eligible (raw {self.green}/{len(self.scorecards)}); "
            f"flat-queue={self.flat_queue} (structurally non-GREEN, #789)"
        )
        if self.mode_unknown:
            rel += f"; mode-unknown={self.mode_unknown}"
        lines.append(rel)
        lines.append(
            f"hard gates: FALSE-DONE={self.false_done} "
            f"[{'OK' if not self.false_done else 'PROGRAM-FAILING'}]  "
            f"interventions={self.interventions_total} "
            f"[{'OK' if not self.interventions_total else 'VIOLATED'}]  "
            f"stalled={self.stalled}"
        )
        # #827: the advisory failure-taxonomy KPI line(s) — per-class trend + the
        # unclassified rate (the instrument's own health metric). Present only after
        # classify() has run; a fail-soft empty block renders nothing.
        if self.failure_taxonomy:
            from tools.dispatch_harness import failure_taxonomy as _ftax

            lines.extend(_ftax.render_kpi(self.failure_taxonomy))
        # #837: the advisory GREEN-audit KPI line (band counts + regressed/craft-residue).
        # Present only after green_quality() has run; a fail-soft empty block renders nothing.
        if self.green_quality_block:
            from tools.dispatch_harness import green_quality as _ga

            lines.extend(_ga.render_kpi(self.green_quality_block))
        return "\n".join(lines)


def read_guest_oracle_certificate(runs_dir: Path | None, run_id: str) -> dict | None:
    """#744 consumption half: read the advisory guest-oracle.json beside the
    driver scorecard, or None when absent (node jobs / transport failure /
    pre-744 runs). Fail-soft: an unreadable certificate reads as None — the
    certificate is evidence, never a gate."""
    if not runs_dir or not run_id:
        return None
    path = Path(runs_dir) / run_id / "guest-oracle.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def guest_oracle_evidence(guest: dict | None) -> str:
    """#744: flatten the advisory certificate to the scorecard evidence contract —
    strings only, single line, capped (pointers + short statuses, never raw logs).
    A dict here fails the fail-closed writer and costs the whole night (2026-07-08)."""
    if guest is None:
        return "no-certificate"
    status = str(guest.get("status") or "unknown")
    reason = str(guest.get("reason") or "")
    return _note(f"{status}: {reason}" if reason else status)[:300]


def _stage_card_run_budget(harness, card_budget_s: float, base_monitor_s: float,
                           log, cid: str) -> None:
    """Set BOTH per-job budgets from a card's optional run_budget_s (#740 B3).

    Driver watchdog: stage the consume-once pending-budget file the AO reads at
    _fire_swap. Harness monitor: mutate ``harness.overall_timeout_s`` (restored to
    ``base_monitor_s`` for a default card). A card with no budget clears the
    pending file AND restores the base monitor — byte-identical to today. Fail-soft:
    a staging error just leaves the campaign default in force."""
    from shared.fleet.swap_ops import write_pending_run_budget

    try:
        cfg = getattr(harness, "config", None)
        if cfg is not None:
            write_pending_run_budget(cfg, card_budget_s)  # >0 stages; 0 clears
        if card_budget_s and card_budget_s > 0:
            harness.overall_timeout_s = card_budget_s
            log(f"[battery {cid}] per-card run envelope: {card_budget_s:.0f}s "
                f"(driver + monitor) — over the campaign default {base_monitor_s:.0f}s.")
        else:
            harness.overall_timeout_s = base_monitor_s
    except Exception as exc:  # noqa: BLE001 — never sink the battery over a budget
        log(f"[battery {cid}] per-card budget staging failed ({exc}); using the default.")


def guest_agreement(host_oracle_status: str, guest: dict | None) -> str:
    """Classify one job's host-vs-guest oracle agreement for the tally.

    Closed vocabulary (the morning report + battery-summary carry it):
      * ``no-certificate``  — no guest run (node job, transport down, pre-744)
      * ``guest-not-run``   — certificate present but the guest could not run
      * ``agree``           — both passed or both failed
      * ``DIVERGENCE``      — one passed where the other failed (THE datum)
    """
    if guest is None:
        return "no-certificate"
    g = str(guest.get("status", "not-run"))
    if g == "not-run":
        return "guest-not-run"
    h = str(host_oracle_status or "").strip().lower()
    if h in ("passed", "failed"):
        return "agree" if g == h else "DIVERGENCE"
    return "guest-not-run" if g not in ("passed", "failed") else f"guest-{g}-host-{h or 'unknown'}"


def _read_driver_scorecard(runs_dir: Path | None, run_id: str) -> dict | None:
    if not runs_dir or not run_id:
        return None
    path = Path(runs_dir) / run_id / DRIVER_SCORECARD_NAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}  # present-but-unreadable — adoption will fail loudly
    return data if isinstance(data, dict) else {}


async def run_battery(
    harness: DispatchHarness,
    cards: list[dict],
    *,
    out_dir: Path,
    dry_run: bool,
    log=print,
    ensure_ao: "Callable[[str], bool] | None" = None,
) -> BatterySummary:
    """Drive every card through ``harness.run_job`` (serially — one residency per
    job by design), adopt-or-synthesize + cross-check its scorecard, write each
    ``<id>.scorecard.json`` and the ``battery-summary.json``.

    ``ensure_ao`` (#750 fix 2): a ``job_id -> up?`` re-ensurer called before each job
    so a flaky swap-back that left the AO down is recovered (a re-boot) instead of
    cascading into every later job STALLING. ``None`` (dry-run / tests) skips it —
    the fake in-process AO needs no socket. It never raises (fail-soft); a False
    result just means the job will STALL honestly (and the next job re-tries)."""
    summary = BatterySummary(out_dir=str(out_dir), dry_run=dry_run)
    out_dir.mkdir(parents=True, exist_ok=True)
    runs_dir = getattr(harness.config, "runs_dir", None)
    # #832: the merged-tree root for the earned-GREEN integrity audit + its trusted-side
    # allowlist (loaded ONCE from the committed file, never from a scanned candidate tree).
    projects_dir = getattr(harness.config, "projects_dir", None)
    green_allowlist = green_audit.default_allowlist()
    # The base (campaign-default) monitor budget — restored for every card that
    # does not declare its own envelope (#740 B3 re-grain).
    _base_monitor_budget_s = getattr(harness, "overall_timeout_s", 0.0)
    for card in cards:
        cid = str(card.get("id"))
        started = _now_utc()
        if ensure_ao is not None:
            # Blocking (socket + bounded boot wait); run off the event loop.
            await asyncio.to_thread(ensure_ao, cid)
        # #740 B3 re-grain (2026-07-08): a card may declare its own run envelope.
        # Set BOTH bounds per-job: the AO driver watchdog (via the consume-once
        # pending-budget file, staged moments before the dispatch) AND the
        # harness MONITOR (mutated per-job — otherwise the monitor would /dispatch
        # stop a legit long job at the campaign default). Absent → clears the
        # pending file + restores the base monitor budget → byte-identical.
        card_budget = float(card.get("run_budget_s") or 0.0)
        _stage_card_run_budget(harness, card_budget, _base_monitor_budget_s, log, cid)
        log(f"[battery {cid}] dispatching {card.get('repo')} …")
        try:
            job = JobSpec(
                repo=str(card["repo"]),
                # #740: make the card's declared stack explicit so the coder builds the
                # language the oracle grades (Python vs Node), not the house default.
                goal=augment_goal_for_stack(str(card["goal"]), str(card.get("stack", ""))),
                clarify_answer=str(card.get("clarify_answer", "") or "1"),
            )
            report = await harness.run_job(job)
        except Exception as exc:  # noqa: BLE001 — one job's crash must not sink the battery
            sc = stalled_scorecard(cid, f"harness exception: {exc}", card=card, dry_run=dry_run)
            sc = replace(sc, started_utc=started)
            summary.scorecards.append(sc)
            _write(sc, out_dir, log)
            continue
        raw = _read_driver_scorecard(runs_dir, report.run_id)
        if raw is not None:
            sc = adopt_driver_scorecard(raw, card=card, report=report, dry_run=dry_run)
            # #744: fold the guest certificate into the scorecard EVIDENCE (the
            # consumption half — an instrument nobody reads does not exist,
            # lesson 46). Advisory only: verdict/attribution untouched.
            guest = read_guest_oracle_certificate(runs_dir, report.run_id)
            evidence = dict(sc.evidence or {})
            evidence["guest_oracle"] = guest_oracle_evidence(guest)
            evidence["guest_agreement"] = guest_agreement(
                str(evidence.get("oracle_status", "")), guest
            )
            sc = replace(sc, evidence=evidence)
        else:
            sc = synthesize_scorecard(report, card, runs_dir=runs_dir, dry_run=dry_run)
        # #832: earned-GREEN integrity audit — a grader-tampering fingerprint in the merged
        # tree downgrades the GREEN to PARKED-HONEST [VERIFY] BEFORE it banks (the one
        # verdict-authority extension, LA-ratified). No-op for non-GREEN; byte-identical on a
        # clean tree; fail-soft (never downgrades on a scan fault or an unavailable tree).
        sc = green_integrity_audit(
            sc, card=card, projects_dir=projects_dir, runs_dir=runs_dir,
            run_id=report.run_id, allowlist=green_allowlist, log=log,
        )
        sc = replace(sc, started_utc=started)
        try:
            _write(sc, out_dir, log)
        except ValueError as exc:
            # The fail-closed writer refused the composed card. The refusal is
            # correct (an invalid record must never land); the runner dying with
            # it is not — one job's record must not sink the night (the same
            # contract as the run_job try above; cost of the miss: 2026-07-08,
            # runner dead 4 min in, zero scorecards). Degrade THIS job to the
            # fail-loud STALLED card and keep going.
            log(f"[battery {cid}] composed scorecard INVALID — degrading to "
                f"STALLED [HARNESS]: {exc}")
            sc = stalled_scorecard(
                cid, f"invalid composed scorecard: {exc}", card=card, dry_run=dry_run
            )
            sc = replace(sc, started_utc=started)
            _write(sc, out_dir, log)
        summary.scorecards.append(sc)
        # #749: fail-soft, knob-gated durable-ticket post — the single per-job
        # outcome comment (after the FALSE-DONE cross-check above; never a heartbeat).
        _post_job_ticket(getattr(harness, "config", None), card, report, sc, log)
    # #837: at battery close (AFTER #832's per-job integrity gate above), run the advisory
    # GREEN-QUALITY audit over every job that REMAINS GREEN (a #832 downgrade is now PARKED, so
    # it is skipped — integrity first, quality second). Layer-1 deterministic floor now; the 14B
    # jury is a supervised GPU slot (jurors=None). Writes each GREEN's green-quality.json sidecar
    # + stamps green_quality_* evidence BEFORE #827's classify below. Surfaces come from the
    # cards; projects_dir is the same one #832's per-job audit used (defined above).
    job_surfaces = {str(c.get("id")): str(c.get("stack", "")) for c in cards}
    summary.green_quality(runs_dir=runs_dir, out_dir=out_dir, projects_dir=projects_dir,
                        job_surfaces=job_surfaces, log=log)
    # #827: stamp every scorecard with its advisory failure/green class + the taxonomy block,
    # BEFORE the summary write so battery-summary.json carries it.
    summary.classify(runs_dir=runs_dir, out_dir=out_dir, log=log)
    (out_dir / "battery-summary.json").write_text(
        json.dumps(summary.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return summary


def _write(sc: Scorecard, out_dir: Path, log) -> None:
    path = out_dir / f"{sc.job_id or 'UNKNOWN'}.scorecard.json"
    write_scorecard(sc, path)
    log(f"[battery {sc.job_id}] {sc.verdict}"
        + (f" [{sc.attribution}]" if sc.attribution else "")
        + f" -> {path}")


def _post_job_ticket(cfg, card: dict, report: JobReport, sc: Scorecard, log) -> None:
    """#749: publish this battery job's AUTHORITATIVE (post-cross-check) outcome to
    its durable Vikunja ticket — one comment per job, the ticket closed only on a
    GREEN + oracle-passed scorecard. Knob-gated (``config.vikunja_bridge``) and
    wholly FAIL-SOFT (a Vikunja outage never affects the battery).

    The battery owns this post (not the harness) so it is the FALSE-DONE
    cross-check RESULT — never the raw driver claim — that reaches the ticket: a
    rigged B8 GREEN rewritten to FALSE-DONE lands as an OPEN ticket, never a
    wrongly-closed one. The harness's own post-adoption seam stays OFF during a
    battery run (``report_outcomes_to_vikunja`` defaults False), so a completed job
    posts exactly ONE outcome comment — never two."""
    if cfg is None or not getattr(cfg, "vikunja_bridge", False):
        return
    run_id = sc.run_id or report.run_id
    if not run_id:
        return
    try:
        from shared.fleet import vikunja_bridge as vb

        ticket_id = vb.ensure_job_ticket(
            cfg, run_id, str(card.get("goal", "")), str(card.get("repo", ""))
        )
        if ticket_id is not None:
            vb.post_outcome(cfg, ticket_id, sc.to_dict())
    except Exception as exc:  # noqa: BLE001 — ticket I/O never affects a battery night
        log(f"[battery {sc.job_id}] vikunja ticket update skipped (fail-soft): {exc}")


# ---------------------------------------------------------------------------
# Dry-run wiring (the harness's existing fake-AO mode, card-aware)
# ---------------------------------------------------------------------------


def build_dry_run_harness(cards: list[dict], *, session_id: str = "battery") -> DispatchHarness:
    """A card-aware fake AO over :meth:`DispatchHarness.for_dry_run` (the same
    pattern as ``__main__._build_dry_run_harness`` — the REAL coordinator with
    injected plan/execute fns + a fake fleet dir; no GPU, no model, no live AO).

    The fake ``execute_fn`` writes the ``SUMMARY.txt`` the monitor completes on
    AND a driver ``scorecard.json`` into the run dir — exercising the full W6
    adoption seam end-to-end. Rig-carrying cards (B8) emit an HONEST fake:
    PARKED-HONEST with the rigs reported caught and ``oracle_status: failed`` —
    a dry-run battery must model the system WORKING, and a fake GREEN on B8
    would (correctly) be rewritten FALSE-DONE by the cross-check."""
    from shared.fleet.acceptance import AcceptanceCriterion, AcceptanceSpec, PlanResult
    from shared.fleet.dispatch import DispatchResult, FleetDispatchConfig

    tmp = Path(tempfile.mkdtemp(prefix="battery-dryrun-"))
    fake_config = FleetDispatchConfig(
        scripts_dir=tmp / "scripts",
        queue_path=tmp / "state" / "fleet-queue.json",
        runs_dir=tmp / "state" / "fleet-runs",
        projects_dir=tmp / "projects",
    )
    by_repo = {str(c["repo"]): c for c in cards}
    counter = {"n": 0}

    def _mint() -> str:
        counter["n"] += 1
        return f"BATTERY-DRYRUN-{counter['n']}"

    async def plan_fn(repo: str, goal: str) -> PlanResult:
        spec = AcceptanceSpec(
            goal,
            (
                AcceptanceCriterion("c1", "the project builds", "build", ""),
                AcceptanceCriterion("c2", "the headline feature works", "behavior", ""),
            ),
            build_plan={"surface": "desktop-gui", "language_hint": None,
                        "complexity": "moderate", "components": []},
        )
        return PlanResult(
            ok=True,
            tasks=[{"repo": repo, "task": "build-it", "prompt": goal,
                    "surface": "desktop-gui"}],
            spec=spec,
            message="planned (battery dry-run)",
        )

    async def execute_fn(session_id, run_id, repo, tasks, spec):
        card = by_repo.get(str(repo), {})
        rigs = card.get("rigs") or []
        run_dir = fake_config.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        if rigs:
            result_line = ("RESULT: Task parked - not merged (rigged negatives "
                           + ",".join(map(str, rigs)) + " caught by the gates; branch kept).")
            driver = {
                "schema": SCORECARD_SCHEMA,
                "job_id": "(driver)",
                "verdict": VERDICT_PARKED_HONEST,
                "attribution": ATTRIBUTION_VERIFY,
                "wall_clock_s": 0.0,
                "samples_consumed": 1,
                "packs_consumed": 1,
                "interventions": 0,
                "evidence": {"summary": str(run_dir / "SUMMARY.txt"),
                             "oracle_status": "failed"},
                "versions": {"emitter": "battery-dry-run-fake-ao"},
                "notes": "dry-run fake: rigs simulated CAUGHT (" + ",".join(map(str, rigs)) + ")",
            }
        else:
            result_line = "RESULT: MERGED into your project - just open the app and try it."
            driver = {
                "schema": SCORECARD_SCHEMA,
                "job_id": "(driver)",
                "verdict": VERDICT_GREEN,
                "attribution": "",
                "wall_clock_s": 0.0,
                "samples_consumed": 1,
                "packs_consumed": 0,
                "interventions": 0,
                "evidence": {"summary": str(run_dir / "SUMMARY.txt"),
                             "oracle_status": "passed"},
                "versions": {"emitter": "battery-dry-run-fake-ao"},
                "notes": "dry-run fake: oracle simulated green",
            }
        (run_dir / "SUMMARY.txt").write_text(
            f"Fleet run {run_id} — 1 task(s):\n- build-it: processed\n    {result_line}\n",
            encoding="utf-8",
        )
        (run_dir / DRIVER_SCORECARD_NAME).write_text(
            json.dumps(driver, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        return DispatchResult(
            ok=True, run_id=run_id,
            message=f"Dispatching {run_id} — 1 task(s) to the coder fleet (battery dry-run).",
        )

    return DispatchHarness.for_dry_run(
        config=fake_config,
        plan_fn=plan_fn,
        execute_fn=execute_fn,
        mint_run_id=_mint,
        session_id=session_id,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m tools.dispatch_harness.battery",
        description="Run the M2 capability battery (evals/battery) through the dispatch pipeline.",
    )
    sel = p.add_argument_group("job selection")
    sel.add_argument("--jobs", metavar="IDS",
                     help="Comma-separated battery ids to run (e.g. B1,B3,B8).")
    sel.add_argument("--all", action="store_true", help="Run every card in the spec.")
    p.add_argument("--spec-dir", metavar="DIR",
                   help="Battery spec directory (default: evals/battery).")
    p.add_argument("--out", metavar="DIR",
                   help="Scorecard output dir (default: <agentic-setup>/state/battery/<stamp> "
                        "for live runs; a fresh temp dir for --dry-run).")
    p.add_argument("--dry-run", action="store_true",
                   help="Drive the harness's fake in-process AO end-to-end (no GPU/model/AO).")
    p.add_argument("--config", metavar="TOML",
                   help="Override the AO default.toml path (port + fleet roots).")
    p.add_argument("--dev-mode", action="store_true",
                   help="LIVE over plaintext dev loopback instead of production mTLS.")
    p.add_argument("--session-id", default="battery")
    mon = p.add_argument_group("monitoring (live)")
    mon.add_argument("--poll-interval-s", type=float, default=5.0)
    mon.add_argument("--stall-grace-s", type=float, default=240.0)
    mon.add_argument("--overall-timeout-s", type=float, default=0.0,
                     help="Hard per-run cap (0 = the AO's swap_run_budget_s).")
    return p


def _select_cards(cards: dict[str, dict], args) -> tuple[list[dict], list[str]]:
    """(runnable cards, unknown ids). Unknown ids are NOT dropped — each becomes a
    fail-loud STALLED scorecard downstream."""
    if args.all:
        return list(cards.values()), []
    if not args.jobs:
        raise SystemExit("error: provide --jobs B1[,B3,…] or --all (see --help).")
    wanted = [w.strip().upper() for w in str(args.jobs).split(",") if w.strip()]
    selected = [cards[w] for w in wanted if w in cards]
    unknown = [w for w in wanted if w not in cards]
    return selected, unknown


def _force_utf8_output() -> None:
    """Force UTF-8 on stdout/stderr. The runner + harness log job content — PLAN previews,
    monitor progress tails, oracle/criteria text — that can carry non-cp1252 characters
    (``>=`` U+2265, ``->`` arrows, ...). On Windows the default console/redirect codec is
    cp1252, so an un-reconfigured ``print`` of a ``≥`` raises UnicodeEncodeError and
    crashes the WHOLE runner — aborting the job as STALLED [HARNESS] even though its build
    succeeded (found live re-running B7, 2026-07-06: a node oracle carried ``>=``).
    ``errors='replace'`` is a final backstop on top of UTF-8. Fail-soft."""
    import sys as _sys

    for _stream in (_sys.stdout, _sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8_output()
    args = _build_parser().parse_args(argv)
    try:
        cards = load_cards(Path(args.spec_dir) if args.spec_dir else None)
    except ValueError as exc:
        print(f"battery: {exc}", file=sys.stderr)
        return 1
    selected, unknown = _select_cards(cards, args)

    if args.out:
        out_dir = Path(args.out)
    elif args.dry_run:
        out_dir = Path(tempfile.mkdtemp(prefix="battery-scorecards-"))
    else:
        cfg = load_harness_config(args.config)
        base = Path(cfg.agentic_setup_dir) if cfg.agentic_setup_dir else Path(
            "C:/Users/mrbla/agentic-setup"
        )
        out_dir = base / "state" / "battery" / time.strftime("%Y%m%d-%H%M%S")

    summary = BatterySummary(out_dir=str(out_dir), dry_run=args.dry_run)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Fail-loud for ids that never reach the harness.
    for bad in unknown:
        sc = stalled_scorecard(bad, f"unknown battery id '{bad}' — not in the spec "
                                    f"({', '.join(sorted(cards))})", dry_run=args.dry_run)
        summary.scorecards.append(sc)
        _write(sc, out_dir, print)

    ensure_ao: "Callable[[str], bool] | None" = None
    if selected:
        try:
            if args.dry_run:
                harness = build_dry_run_harness(selected, session_id=args.session_id)
                print("DRY-RUN: driving the battery against the harness's fake in-process AO.\n")
            else:
                cfg = load_harness_config(args.config)
                harness = DispatchHarness.for_live(
                    port=cfg.port,
                    agentic_setup_dir=cfg.agentic_setup_dir,
                    projects_dir=cfg.projects_dir,
                    fleet_dispatch_enabled=cfg.fleet_dispatch_enabled,
                    dev_mode=args.dev_mode,
                    session_id=args.session_id,
                    poll_interval_s=args.poll_interval_s,
                    stall_grace_s=args.stall_grace_s,
                    overall_timeout_s=args.overall_timeout_s or cfg.swap_run_budget_s,
                )
                # #750 fix 2: re-ensure the AO before each job so one flaky swap-back
                # can't cascade every later job into a STALL. Production only — the
                # auto-reboot boots `python -m launcher` in production mode (mTLS);
                # a --dev-mode run is operator-driven, so we don't auto-reboot it.
                if not args.dev_mode:
                    ensure_ao = AoReensurer.real(
                        port=cfg.port, repo_root=_BLARAI_REPO_ROOT,
                        reboot_log_dir=out_dir, log=print,
                    ).ensure
        except Exception as exc:  # noqa: BLE001 — construction failure = every job STALLED, loudly
            for card in selected:
                sc = stalled_scorecard(str(card["id"]),
                                       f"harness could not be built: {exc}",
                                       card=card, dry_run=args.dry_run)
                summary.scorecards.append(sc)
                _write(sc, out_dir, print)
            # #827: classify the STALLED/HARNESS cards (no run dirs → attribution-only).
            summary.classify(runs_dir=None, out_dir=out_dir, log=print)
            (out_dir / "battery-summary.json").write_text(
                json.dumps(summary.to_dict(), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            print("\n" + summary.render())
            return summary.exit_code()

        run_summary = asyncio.run(
            run_battery(harness, selected, out_dir=out_dir, dry_run=args.dry_run,
                        ensure_ao=ensure_ao)
        )
        summary.scorecards.extend(run_summary.scorecards)
        # re-write the combined summary (includes any unknown-id STALLED cards)
        # #837: re-run the GREEN-audit over the COMBINED set (idempotent — run_battery already
        # wrote each GREEN's sidecar; the appended unknown-id cards are STALLED, so this is a
        # no-op for them) BEFORE the combined classify, so #827 reads the band.
        _runs_dir = getattr(getattr(harness, "config", None), "runs_dir", None)
        _projects_dir = getattr(getattr(harness, "config", None), "projects_dir", None)
        _job_surfaces = {str(c.get("id")): str(c.get("stack", "")) for c in selected}
        summary.green_quality(runs_dir=_runs_dir, out_dir=out_dir, projects_dir=_projects_dir,
                            job_surfaces=_job_surfaces, log=print)
        # #827: re-classify over the COMBINED set (run_battery's stamped cards re-read
        # their sidecars idempotently; the appended unknown-id STALLED cards get stamped).
        summary.classify(runs_dir=_runs_dir, out_dir=out_dir, log=print)
        (out_dir / "battery-summary.json").write_text(
            json.dumps(summary.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    print("\n" + summary.render() + "\n")
    print(f"(scorecards + battery-summary.json written to {out_dir})")
    return summary.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())
