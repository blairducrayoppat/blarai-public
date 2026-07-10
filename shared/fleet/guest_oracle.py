"""Guest-certified oracle runs (#744, plan §10.3) — DORMANT S4 hardening.

After a dispatch job's tasks merge and the HOST job-level acceptance oracle has
graded the integrated tree (``SwapOps.run_job_oracle`` — the *fidelity* gate),
this module re-runs the SAME spec-blind oracle inside the NIC-less Alpine guest
(``BlarAI-Orchestrator``) as an *isolation certificate* layered on top: no
TCP/IP stack exists in the guest, so exfiltration by model-written test code is
structurally impossible and the host filesystem is unreachable.  The guest run
is ADVISORY EVIDENCE ONLY — it never changes verdict or attribution semantics
(the LA has not ratified more); a host-pass/guest-fail divergence is FLAGGED in
the evidence block for the operator.

Pipeline (host side, one run per JOB in the swap machine's RAM-free window):

  1. **Snapshot** — collect the integrated repo's pure-Python source
     (``*.py`` only, hygiene dirs excluded, hard file/size caps);
  2. **Overlay** — the PLAN-CARRIED oracle bytes replace whatever is on disk
     at the pinned oracle path (mirror of the host gate's
     restore-before-grade: a merged edit to the oracle can never help);
  3. **Dependency scan** — ``ast``-parse every file; any top-level import
     outside stdlib + pytest + the snapshot's own modules ⇒ ``not-run``
     with reason ``deps-unavailable`` (the guest is OFFLINE — no installs,
     fail-closed, decided host-side before anything ships);
  4. **Ship** — a deterministic ZIP over the UC-003 vsock staging corridor
     pattern (``shared/ipc/oracle_channel.py`` — chunked, size-capped,
     fail-closed); the result comes back over the same channel.

STRUCTURAL DORMANCY: no production code registers a transport — the
``transport`` parameter defaults to ``None`` and the pipeline then reports an
honest ``not-run`` (``guest-transport-unregistered``).  Wiring the real
AF_HYPERV transport + provisioning pytest in the guest is the LA's supervised
go-live ceremony (the guest-parser precedent, #655).  On top of that sits the
``[fleet_dispatch].guest_oracle_enabled = false`` knob: the swap driver never
calls this pipeline at all while it is off.

``execute_snapshot`` is the GUEST-side half — pure stdlib + pytest, so the
exact function the guest service will run is offline-testable on the host
today (zip-slip/zip-bomb guarded extraction into a temp dir, then
``python -m pytest -q <oracle>``).

Security frame: fail-closed everywhere (every machinery failure is an honest
``not-run``, never an implied pass and never a raise into the swap teardown);
source-only transport (no binaries, no git metadata, no env); no network — the
corridor is host↔guest vsock only.
"""

from __future__ import annotations

import ast
import io
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Callable

# GUEST-PORTABILITY (#744 ceremony, 2026-07-08): this module SHIPS TO the
# NIC-less Alpine guest on the provisioning CD, so its module-level imports
# must stay stdlib + shared.ipc only.  ``shared.fleet.acceptance`` drags the
# whole decompose machinery — poison in the guest — so the pinned oracle
# paths are REDECLARED here (the parser-service DEFAULT_PARSER_PORT
# precedent) and a host-side lock pins them equal to acceptance's
# JOB_ORACLE_ALLOWED_PATHS (test_guest_oracle_service.py).
JOB_ORACLE_ALLOWED_PATHS: frozenset[str] = frozenset(
    {"tests/test_job_acceptance.py", "tests/acceptance.job.test.mjs"}
)

#: Snapshot collection caps (raw source, pre-zip).  A fleet-built project's
#: pure-Python source measures in the tens of KB; these caps bound a runaway
#: or hostile tree long before the corridor's 2 MiB wire cap.
SNAPSHOT_MAX_FILES: int = 512
SNAPSHOT_MAX_FILE_BYTES: int = 512_000
SNAPSHOT_MAX_TOTAL_BYTES: int = 2 * 1024 * 1024

#: Directory names never collected (and refused on extraction): hygiene dirs
#: plus anything hidden.  Matches the fleet's own worktree hygiene posture.
SNAPSHOT_EXCLUDED_DIRS: frozenset[str] = frozenset(
    {"__pycache__", "node_modules", ".git", ".venv", "venv", ".worktrees",
     ".pytest_cache", ".mypy_cache", ".ruff_cache", "dist", "build", ".eggs"}
)

#: Import roots available in the provisioned guest beyond the stdlib.  The
#: go-live ceremony provisioned exactly pytest 9.1.1 + hypothesis 6.155.7
#: (pure wheels, `provision_oracle.sh` step (d), verified import at step (e) —
#: docs/security/guest_oracle_provisioning_record.md).  hypothesis joined
#: 2026-07-09: the oracle GENERATOR promises it ("the test runner has
#: hypothesis available", acceptance.py) and the guest has it, but this scan
#: refused it host-side, so every property-testing oracle read
#: deps-unavailable and never shipped (#744 c.1526).  This set mirrors the
#: provisioned guest venv — extend it only alongside a guest provisioning
#: ceremony, never ahead of one.
GUEST_AVAILABLE_IMPORT_ROOTS: frozenset[str] = frozenset(
    {"pytest", "_pytest", "hypothesis"}
)

#: Stable machine reasons for a not-run (the closed reason vocabulary the
#: evidence block carries — greppable across runs).
REASON_NO_ORACLE = "no-job-oracle"
REASON_REFUSED_PATH = "refused-oracle-path"
REASON_NON_PYTHON = "non-python-oracle"
REASON_SNAPSHOT_FAILED = "snapshot-failed"
REASON_SNAPSHOT_TOO_LARGE = "snapshot-too-large"
REASON_SOURCE_UNPARSEABLE = "source-unparseable"
REASON_DEPS_UNAVAILABLE = "deps-unavailable"
REASON_TRANSPORT_UNREGISTERED = "guest-transport-unregistered"
REASON_GUEST_ERROR = "guest-error"

#: Bound on the human evidence label (never file contents — §10 S6).
_EVIDENCE_MAX_CHARS: int = 2_000

#: Deterministic ZIP member timestamp (zipfile's minimum valid date) — the
#: snapshot bytes are a pure function of the source, so tests can lock them.
_ZIP_EPOCH: tuple[int, int, int, int, int, int] = (1980, 1, 1, 0, 0, 0)


class GuestOracleError(Exception):
    """Deterministic guest-oracle machinery failure (mapped to not-run)."""


def _not_run(reason: str, evidence: str) -> dict:
    return {"status": "not-run", "reason": reason,
            "evidence": evidence[:_EVIDENCE_MAX_CHARS]}


# ---------------------------------------------------------------------------
# Host side: snapshot -> overlay -> dep scan -> zip -> transport
# ---------------------------------------------------------------------------


def build_source_snapshot(repo: str | Path) -> list[tuple[str, bytes]]:
    """Collect the repo's pure-Python source as ``(posix_rel_path, bytes)``.

    ``*.py`` files only (the guest scope is pure-Python pytest — #744
    constraint 5), hygiene/hidden dirs excluded, sorted for determinism.

    Raises:
        GuestOracleError: unreadable repo, or any collection cap exceeded
            (file count / per-file bytes / total bytes) — fail-closed, the
            caller maps it to an honest ``not-run``.
    """
    root = Path(repo)
    if not root.is_dir():
        raise GuestOracleError(f"repo is not a directory: {root}")
    files: list[tuple[str, bytes]] = []
    total = 0
    # rglob + explicit part-filter (not os.walk pruning) keeps the traversal
    # order OS-independent after the final sort; the part-filter still
    # excludes every hygiene dir at ANY depth.
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root)
        parts = rel.parts
        if any(p in SNAPSHOT_EXCLUDED_DIRS or p.startswith(".") for p in parts[:-1]):
            continue
        if parts[-1].startswith("."):
            continue
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise GuestOracleError(f"unreadable source file {rel.as_posix()}: {exc}") from exc
        if len(data) > SNAPSHOT_MAX_FILE_BYTES:
            raise GuestOracleError(
                f"{rel.as_posix()} is {len(data)} bytes (> {SNAPSHOT_MAX_FILE_BYTES} "
                "per-file cap)"
            )
        total += len(data)
        if total > SNAPSHOT_MAX_TOTAL_BYTES:
            raise GuestOracleError(
                f"snapshot exceeds {SNAPSHOT_MAX_TOTAL_BYTES} total bytes at "
                f"{rel.as_posix()}"
            )
        files.append((rel.as_posix(), data))
        if len(files) > SNAPSHOT_MAX_FILES:
            raise GuestOracleError(
                f"snapshot exceeds {SNAPSHOT_MAX_FILES} files"
            )
    return files


def overlay_oracle(
    files: list[tuple[str, bytes]], oracle_rel_path: str, oracle_code: str
) -> list[tuple[str, bytes]]:
    """Return *files* with the PLAN-CARRIED oracle bytes at *oracle_rel_path*.

    The plan bytes ALWAYS win (replace-or-append) — the guest grades the
    spec-blind oracle as planned, mirroring the host gate's
    restore-before-grade posture (#690): a merged edit to the oracle file can
    never help the job pass."""
    oracle_bytes = oracle_code.encode("utf-8")
    out = [(p, b) for (p, b) in files if p != oracle_rel_path]
    out.append((oracle_rel_path, oracle_bytes))
    out.sort(key=lambda item: item[0])
    return out


def scan_snapshot_deps(files: list[tuple[str, bytes]]) -> list[str]:
    """Top-level import roots the OFFLINE guest cannot satisfy (sorted).

    Allowed roots: the stdlib (``sys.stdlib_module_names``), pytest
    (:data:`GUEST_AVAILABLE_IMPORT_ROOTS`), and the snapshot's OWN modules /
    packages.  Relative imports resolve within the snapshot by construction.

    Raises:
        GuestOracleError: a source file that does not parse — the scan cannot
            certify what it cannot read (fail-closed; the host gate will have
            reported the syntax failure on its own run)."""
    local_roots: set[str] = set()
    for rel, _data in files:
        parts = PurePosixPath(rel).parts
        if len(parts) == 1:
            local_roots.add(PurePosixPath(rel).stem)
        else:
            local_roots.add(parts[0])
    allowed = set(sys.stdlib_module_names) | GUEST_AVAILABLE_IMPORT_ROOTS | local_roots
    missing: set[str] = set()
    for rel, data in files:
        try:
            tree = ast.parse(data.decode("utf-8"), filename=rel)
        except (SyntaxError, UnicodeDecodeError, ValueError) as exc:
            raise GuestOracleError(f"{REASON_SOURCE_UNPARSEABLE}: {rel}: {exc}") from exc
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root not in allowed:
                        missing.add(root)
            elif isinstance(node, ast.ImportFrom):
                if node.level:  # relative import — inside the snapshot
                    continue
                if node.module:
                    root = node.module.split(".")[0]
                    if root not in allowed:
                        missing.add(root)
    return sorted(missing)


def zip_snapshot(files: list[tuple[str, bytes]]) -> bytes:
    """Deterministic ZIP of the snapshot (fixed timestamps, sorted members)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel, data in sorted(files, key=lambda item: item[0]):
            info = zipfile.ZipInfo(rel, date_time=_ZIP_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, data)
    return buf.getvalue()


def run_guest_oracle(
    repo: str,
    oracle_rel_path: str,
    oracle_code: str,
    *,
    transport: "Callable[[bytes, str], dict] | None" = None,
) -> dict:
    """The host-side guest-oracle pipeline — ONE run per job (#744).

    Returns ``{"status": "passed"|"failed"|"not-run", "reason": str,
    "evidence": str}`` — the same closed status vocabulary as the host job
    oracle so the two are directly comparable.  EVERY failure path is an
    honest ``not-run`` with a stable machine reason; nothing raises to the
    caller (the swap teardown guards it again regardless — belt and braces).

    ``transport`` sends ``(snapshot_zip, oracle_rel_path)`` to the guest and
    returns the decoded response dict (``oracle_channel`` shapes).  The
    default ``None`` is the STRUCTURAL DORMANCY LOCK: no production code
    registers one until the supervised go-live ceremony."""
    try:
        if not oracle_code:
            return _not_run(REASON_NO_ORACLE, "no job oracle was generated at plan time")
        if oracle_rel_path not in JOB_ORACLE_ALLOWED_PATHS:
            return _not_run(
                REASON_REFUSED_PATH,
                f"refused oracle path {oracle_rel_path!r} (not a pinned oracle path)",
            )
        if not oracle_rel_path.endswith(".py"):
            return _not_run(
                REASON_NON_PYTHON,
                "the guest runs pure-Python pytest only — a node oracle is "
                "host-gate-only (fidelity stays host-side)",
            )
        try:
            files = build_source_snapshot(repo)
        except GuestOracleError as exc:
            reason = (REASON_SNAPSHOT_TOO_LARGE
                      if "cap" in str(exc) or "exceeds" in str(exc)
                      else REASON_SNAPSHOT_FAILED)
            return _not_run(reason, str(exc))
        files = overlay_oracle(files, oracle_rel_path, oracle_code)
        try:
            missing = scan_snapshot_deps(files)
        except GuestOracleError as exc:
            return _not_run(REASON_SOURCE_UNPARSEABLE, str(exc))
        if missing:
            return _not_run(
                REASON_DEPS_UNAVAILABLE,
                "the offline guest cannot import: " + ", ".join(missing),
            )
        snapshot_zip = zip_snapshot(files)
        # The corridor's wire cap backstops the raw-source cap above.
        from shared.ipc.oracle_channel import ORACLE_BODY_MAX_BYTES

        if len(snapshot_zip) > ORACLE_BODY_MAX_BYTES:
            return _not_run(
                REASON_SNAPSHOT_TOO_LARGE,
                f"snapshot zip of {len(snapshot_zip)} bytes exceeds the "
                f"{ORACLE_BODY_MAX_BYTES} corridor cap",
            )
        if transport is None:
            return _not_run(
                REASON_TRANSPORT_UNREGISTERED,
                "no guest transport is registered in this build — wiring the "
                "AF_HYPERV corridor is the supervised go-live ceremony (#744)",
            )
        response = transport(snapshot_zip, oracle_rel_path)
        return _normalize_guest_response(response)
    except BaseException as exc:  # noqa: BLE001 — never raise into the swap teardown
        return _not_run(REASON_GUEST_ERROR, f"guest oracle pipeline error: {type(exc).__name__}")


def _normalize_guest_response(response: object) -> dict:
    """Coerce a transport response to the closed result shape (fail-closed)."""
    if not isinstance(response, dict):
        return _not_run(REASON_GUEST_ERROR, "guest transport returned a non-dict")
    status = response.get("status")
    if status not in ("passed", "failed", "not-run"):
        return _not_run(REASON_GUEST_ERROR, f"guest returned unknown status {status!r}")
    reason = str(response.get("reason", "") or "")
    evidence = str(response.get("evidence", "") or "")
    if status == "not-run" and not reason:
        reason = REASON_GUEST_ERROR
    if status != "not-run":
        reason = ""
    return {"status": status, "reason": reason,
            "evidence": evidence[:_EVIDENCE_MAX_CHARS]}


def certificate_block(guest_result: dict, *, host_status: str) -> dict:
    """The advisory ``guest_oracle`` evidence block attached to the job record.

    ADVISORY ONLY (#744 constraint 3): verdict/attribution semantics are
    untouched — the block records the guest outcome BESIDE the host outcome
    and flags a host-pass/guest-fail divergence for the operator; the
    scorecard-attribution question stays with the harness until the LA
    ratifies more."""
    guest_status = str(guest_result.get("status", "not-run"))
    if guest_status not in ("passed", "failed", "not-run"):
        guest_status = "not-run"
    divergence = host_status == "passed" and guest_status == "failed"
    block = {
        "schema": "guest-oracle/v1",
        "advisory": True,
        "status": guest_status,
        "reason": str(guest_result.get("reason", "") or ""),
        "evidence": str(guest_result.get("evidence", "") or "")[:_EVIDENCE_MAX_CHARS],
        "host_status": str(host_status),
        "divergence": divergence,
    }
    if divergence:
        block["evidence"] = (
            "DIVERGENCE: the host oracle passed but the guest run failed — "
            "flagged for operator review (isolation certificate withheld). "
            + block["evidence"]
        )[:_EVIDENCE_MAX_CHARS]
    return block


# ---------------------------------------------------------------------------
# Guest side: safe extraction + pytest execution (pure stdlib + pytest)
# ---------------------------------------------------------------------------


def _validate_member_name(name: str) -> None:
    """Refuse a hostile snapshot member name (zip-slip containment).

    Split out of :func:`safe_extract_snapshot` so the full hostile-name matrix is
    unit-testable OS-independently: on Windows the stdlib READER normalizes
    ``\\`` to ``/`` at ``ZipInfo`` construction, but on the Alpine guest
    (``os.sep == '/'``) a crafted backslashed name survives to this check.

    Raises:
        GuestOracleError: absolute/drive/backslash, traversal-shaped,
            hidden/hygiene segment, or non-Python member names."""
    if "\\" in name or name.startswith("/") or ":" in name:
        raise GuestOracleError(f"refused member name {name!r} (absolute/drive/backslash)")
    parts = name.split("/")
    if any(p in ("", "..") for p in parts):
        raise GuestOracleError(f"refused member name {name!r} (traversal-shaped)")
    if any(p.startswith(".") or p in SNAPSHOT_EXCLUDED_DIRS for p in parts):
        raise GuestOracleError(f"refused member name {name!r} (hidden/hygiene segment)")
    if not name.endswith(".py"):
        raise GuestOracleError(f"refused member name {name!r} (non-Python)")


def safe_extract_snapshot(snapshot_zip: bytes, dest: str | Path) -> list[str]:
    """Extract a snapshot ZIP into *dest* with zip-slip/zip-bomb guards.

    Every member name must be a relative forward-slash ``*.py`` path with no
    ``..``/empty/hidden/hygiene segments; declared decompressed sizes are
    validated against the collection caps BEFORE any byte is extracted.

    Returns the sorted extracted relative paths.

    Raises:
        GuestOracleError: any malformed/hostile member (fail-closed — nothing
            is extracted on refusal)."""
    root = Path(dest)
    try:
        zf = zipfile.ZipFile(io.BytesIO(snapshot_zip))
    except zipfile.BadZipFile as exc:
        raise GuestOracleError(f"snapshot is not a valid zip: {exc}") from exc
    with zf:
        infos = zf.infolist()
        if len(infos) > SNAPSHOT_MAX_FILES:
            raise GuestOracleError(f"snapshot declares {len(infos)} members (> cap)")
        total = 0
        for info in infos:
            name = info.filename
            _validate_member_name(name)
            if info.file_size > SNAPSHOT_MAX_FILE_BYTES:
                raise GuestOracleError(
                    f"member {name!r} declares {info.file_size} bytes (> per-file cap)"
                )
            total += info.file_size
            if total > SNAPSHOT_MAX_TOTAL_BYTES:
                raise GuestOracleError("snapshot declares more than the total-byte cap")
        extracted: list[str] = []
        for info in infos:
            target = root / PurePosixPath(info.filename)
            # Resolved-containment backstop under the name validation above.
            if not target.resolve().is_relative_to(root.resolve()):
                raise GuestOracleError(f"member {info.filename!r} escapes the extract root")
            target.parent.mkdir(parents=True, exist_ok=True)
            data = zf.read(info)
            if len(data) > SNAPSHOT_MAX_FILE_BYTES:
                # A lying header (declared small, inflates big) dies here.
                raise GuestOracleError(f"member {info.filename!r} inflated past the per-file cap")
            target.write_bytes(data)
            extracted.append(info.filename)
    return sorted(extracted)


def _default_pytest_run(cmd: list[str], timeout_s: float, cwd: str) -> tuple[bool, str, str]:
    """Bounded, no-shell pytest subprocess (argv-only — §10 S1)."""
    try:
        cp = subprocess.run(  # noqa: S603 — vector argv, no shell
            cmd, capture_output=True, text=True, timeout=timeout_s, cwd=cwd,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return (False, "", f"pytest run failed to complete: {type(exc).__name__}")
    return (cp.returncode == 0, cp.stdout or "", cp.stderr or "")


def execute_snapshot(
    snapshot_zip: bytes,
    oracle_rel_path: str,
    *,
    run: "Callable[[list[str], float, str], tuple[bool, str, str]] | None" = None,
    timeout_s: float = 600.0,
) -> dict:
    """The GUEST-side half: extract the snapshot and pytest the job oracle.

    Pure stdlib + pytest, so the exact code the guest service will run is
    offline-testable on the host today.  ``python -m pytest`` (never the bare
    CLI) so the snapshot root lands on ``sys.path`` — the host gate's own
    #748 lesson, inherited rather than relearned.

    Returns the closed ``{"status", "reason", "evidence"}`` result shape;
    every machinery failure is an honest ``not-run``."""
    runner = run or _default_pytest_run
    try:
        if oracle_rel_path not in JOB_ORACLE_ALLOWED_PATHS:
            return _not_run(
                REASON_REFUSED_PATH,
                f"refused oracle path {oracle_rel_path!r} (not a pinned oracle path)",
            )
        with tempfile.TemporaryDirectory(prefix="blarai-guest-oracle-") as tmp:
            try:
                extracted = safe_extract_snapshot(snapshot_zip, tmp)
            except GuestOracleError as exc:
                return _not_run(REASON_SNAPSHOT_FAILED, str(exc))
            if oracle_rel_path not in extracted:
                return _not_run(
                    REASON_NO_ORACLE,
                    f"snapshot does not contain the oracle at {oracle_rel_path!r}",
                )
            ok, out, err = runner(
                [sys.executable, "-m", "pytest", "-q", oracle_rel_path],
                timeout_s,
                tmp,
            )
            tail = (out + "\n" + err).strip()[-500:]
            return {
                "status": "passed" if ok else "failed",
                "reason": "",
                "evidence": (f"{'exit 0' if ok else 'nonzero exit'}; {tail}")[:_EVIDENCE_MAX_CHARS],
            }
    except BaseException as exc:  # noqa: BLE001 — the guest service must answer, never crash
        return _not_run(REASON_GUEST_ERROR, f"guest execution error: {type(exc).__name__}")


def build_result_json(result: dict) -> str:
    """Serialize a result dict to the response-body JSON the channel ships."""
    return json.dumps(
        {
            "status": str(result.get("status", "not-run")),
            "reason": str(result.get("reason", "") or ""),
            "evidence": str(result.get("evidence", "") or "")[:_EVIDENCE_MAX_CHARS],
        },
        separators=(",", ":"),
        ensure_ascii=False,
    )
