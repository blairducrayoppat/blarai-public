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
import platform
import re
import socket
import ssl
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

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

CARD_SCHEMA = "battery-card/v1"
JOBPLAN_SCHEMA = "jobplan/v1"

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

_CARD_ID_RE = re.compile(r"^B[1-9][0-9]?$")
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


def boot_launcher_detached(repo_root: Path, log_path: Path) -> None:
    """Boot the AO headless the SAME way run-battery-night.ps1 does — ``python -m
    launcher`` (PRODUCTION mode; no --dev-mode) from the blarai repo root, DETACHED
    so it outlives this runner, stdout+stderr -> *log_path*. Production is mandatory:
    the harness connects over the per-boot mTLS certs the launcher mints (ADR-026),
    so a dev-mode boot would leave the harness unable to reach it.

    #761: spawned via the interpreter's ``pythonw.exe`` sibling when one exists —
    ``sys.executable`` through the venv ``python.exe`` shim re-spawns a
    console-subsystem child that is allocated a fresh VISIBLE console despite
    DETACHED_PROCESS (the accidentally-closable swap-back window class); pythonw
    (GUI subsystem) never allocates one, and Textual takes its proven
    headless-driver fallback. NEVER ``CREATE_NO_WINDOW`` on a launcher spawn — a
    HIDDEN console crashed Textual on 2026-07-06 ("Driver must be in application
    mode"). Fallback: no sibling -> ``sys.executable`` unchanged."""
    from shared.fleet.swap_ops import pythonw_sibling

    exe = pythonw_sibling(sys.executable)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(log_path, "a", encoding="utf-8", errors="replace")  # noqa: SIM115 — handed to the child
    try:
        try:
            subprocess.Popen(  # noqa: S603 — constant argv, no shell
                [exe, "-m", "launcher"],
                cwd=str(repo_root), stdin=subprocess.DEVNULL,
                stdout=fh, stderr=subprocess.STDOUT,
                creationflags=_DETACHED | _NEW_GROUP | _BREAKAWAY, close_fds=True,
            )
        except OSError:
            # Not inside a Windows job object -> BREAKAWAY is invalid; retry without it.
            subprocess.Popen(  # noqa: S603
                [exe, "-m", "launcher"],
                cwd=str(repo_root), stdin=subprocess.DEVNULL,
                stdout=fh, stderr=subprocess.STDOUT,
                creationflags=_DETACHED | _NEW_GROUP, close_fds=True,
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
            boot=lambda: boot_launcher_detached(repo_root, Path(reboot_log_dir) / "ao-reboot.log"),
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


def validate_card(card: dict) -> list[str]:
    """Every structural problem with a battery card ([] == valid)."""
    if not isinstance(card, dict):
        return [f"card must be an object, got {type(card).__name__}"]
    errors: list[str] = []
    if card.get("schema") != CARD_SCHEMA:
        errors.append(f"schema must be '{CARD_SCHEMA}', got {card.get('schema')!r}")
    cid = str(card.get("id", ""))
    if not _CARD_ID_RE.match(cid):
        errors.append(f"id '{cid}' must match B<n>")
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
        cards[str(card["id"])] = card
    if problems:
        raise ValueError("battery spec is invalid — " + " | ".join(problems))
    if not cards:
        raise ValueError(f"no battery cards found under {root}")
    return cards


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

    @property
    def false_done(self) -> int:
        return sum(1 for s in self.scorecards if s.verdict == VERDICT_FALSE_DONE)

    @property
    def stalled(self) -> int:
        return sum(1 for s in self.scorecards if s.verdict == VERDICT_STALLED)

    @property
    def interventions_total(self) -> int:
        return sum(s.interventions for s in self.scorecards)

    def exit_code(self) -> int:
        """2 = FALSE-DONE present (program-failing); 1 = STALLED present (harness
        needs attention); 0 = every job honest (GREEN/PARKED-HONEST/RECOVERED)."""
        if self.false_done:
            return 2
        if self.stalled:
            return 1
        return 0

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
        lines.append(
            f"hard gates: FALSE-DONE={self.false_done} "
            f"[{'OK' if not self.false_done else 'PROGRAM-FAILING'}]  "
            f"interventions={self.interventions_total} "
            f"[{'OK' if not self.interventions_total else 'VIOLATED'}]  "
            f"stalled={self.stalled}"
        )
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
        (out_dir / "battery-summary.json").write_text(
            json.dumps(summary.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    print("\n" + summary.render() + "\n")
    print(f"(scorecards + battery-summary.json written to {out_dir})")
    return summary.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())
