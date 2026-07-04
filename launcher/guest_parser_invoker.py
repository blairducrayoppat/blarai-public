"""
Guest-Parser Bridge Invoker — the 3.11-side half of the AF_HYPERV version bridge
================================================================================
The BlarAI runtime venv is Python 3.11.9, which lacks ``socket.AF_HYPERV`` (added
in 3.12).  This module is what the 3.11 launcher calls to reach the guest parser:
it discovers a 3.12+ interpreter, spawns :mod:`launcher.guest_parser_bridge` as a
short-lived subprocess (one process per op — health checks + rare operator parses
are low-frequency; a long-lived daemon would be over-engineering), pipes the
request frames in, reads the result, and maps it to the bool / response frames the
:class:`launcher.guest_parser.GuestParserManager` and the parser-channel seam
expect.

FAST PATH (future-proofing): if the *running* interpreter already has
``socket.AF_HYPERV`` (a future 3.12+ runtime venv), the bridge is unnecessary —
:func:`bridge_required` is False and the launcher uses the in-process transport
directly (``shared.ipc.vsock``), skipping the subprocess entirely.

INTERPRETER DISCOVERY ORDER (fail-closed if none qualifies):
  1. an explicit ``[guest_parser].bridge_python`` config value (when non-empty);
  2. ``py -3.14`` (the Windows launcher selecting 3.14);
  3. the known absolute path the dev box ships 3.14 at.
A candidate qualifies ONLY if it reports ``socket.AF_HYPERV`` present (probed by a
tiny ``-c`` one-liner).  The 3.11 ``sys.executable`` is NEVER silently used as the
bridge — that is the whole bug this module routes around.  If no candidate
qualifies, the invoker raises :class:`BridgeUnavailableError` with code
``GP_BRIDGE_UNAVAILABLE`` and the caller fails closed LOUD (URL ingest refuses;
there is never a host-side parse fallback — ADR-030 §3).

Security:
  - No external network calls.  The subprocess opens AF_HYPERV vsock to the guest
    ONLY; this module imports no network client (the air-gap import-scan covers
    ``launcher/``).
  - Fail-closed everywhere: a crashed / timed-out / garbled bridge → False /
    None; never a fabricated success, never a fallback.
  - Logs carry structural labels only — never page content / fetched paths.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import struct
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from launcher.parser_channel_seam import ParserEndpoint

logger = logging.getLogger(__name__)

# The known absolute path the dev box ships Python 3.14 at (discovery step 3).
# A list so a future box can add a path without changing the discovery logic.
_KNOWN_BRIDGE_PATHS: tuple[str, ...] = (
    r"C:\Users\mrbla\AppData\Local\Python\pythoncore-3.14-64\python.exe",
)

# The `py -3.14` launcher form (discovery step 2) — Windows only.
_PY_LAUNCHER_ARGS: tuple[str, ...] = ("py", "-3.14")

# Frame length-prefix (matches launcher.guest_parser_bridge — 4-byte big-endian,
# 0 length terminates the list).
_LEN_FORMAT = "!I"
_LEN_SIZE = struct.calcsize(_LEN_FORMAT)

# A tiny probe program: exit 0 iff this interpreter has socket.AF_HYPERV.
_AF_HYPERV_PROBE = "import socket,sys;sys.exit(0 if hasattr(socket,'AF_HYPERV') else 7)"

# Bounded wait for the interpreter-capability probe (fast, local).
_PROBE_TIMEOUT_S: float = 10.0


class BridgeUnavailableError(RuntimeError):
    """No 3.12+ interpreter with ``socket.AF_HYPERV`` could be discovered.

    Carries the structural code ``GP_BRIDGE_UNAVAILABLE`` so the manager maps it
    to a deterministic fail-closed fingerprint (never a pretended success).
    """

    code: str = "GP_BRIDGE_UNAVAILABLE"

    def __init__(self, message: str) -> None:
        super().__init__(f"{self.code}: {message}")
        self.message = message


def bridge_required() -> bool:
    """True when the running interpreter lacks ``socket.AF_HYPERV`` (needs the
    subprocess bridge); False when it can open AF_HYPERV in-process (3.12+)."""
    return not hasattr(socket, "AF_HYPERV")


def _candidate_commands(bridge_python: str = "") -> list[list[str]]:
    """The interpreter-command candidates, in discovery order."""
    candidates: list[list[str]] = []
    if bridge_python.strip():
        candidates.append([bridge_python.strip()])
    if sys.platform == "win32":
        candidates.append(list(_PY_LAUNCHER_ARGS))
    for path in _KNOWN_BRIDGE_PATHS:
        if Path(path).is_file():
            candidates.append([path])
    return candidates


def _interp_has_af_hyperv(command: list[str]) -> bool:
    """True iff *command* launches an interpreter reporting ``socket.AF_HYPERV``."""
    try:
        result = subprocess.run(
            [*command, "-c", _AF_HYPERV_PROBE],
            capture_output=True,
            timeout=_PROBE_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("bridge interpreter probe failed for %r: %s", command, exc)
        return False
    return result.returncode == 0


def discover_bridge_command(bridge_python: str = "") -> list[str]:
    """Return the bridge interpreter command, or raise BridgeUnavailableError.

    Tries each candidate in discovery order and returns the FIRST that reports
    ``socket.AF_HYPERV``.  The running 3.11 ``sys.executable`` is never a
    candidate — see the module docstring.

    Raises:
        BridgeUnavailableError: no candidate qualifies (fail-closed, loud).
    """
    tried: list[str] = []
    for command in _candidate_commands(bridge_python):
        tried.append(" ".join(command))
        if _interp_has_af_hyperv(command):
            logger.info(
                "guest-parser bridge interpreter resolved: %s", " ".join(command)
            )
            return command
    raise BridgeUnavailableError(
        "no Python 3.12+ interpreter with socket.AF_HYPERV found (tried: "
        f"{tried or ['<none>']}); set [guest_parser].bridge_python or install "
        "py -3.14 — refusing fail-closed (NEVER the 3.11 runtime, which cannot "
        "address AF_HYPERV)."
    )


def _frame_list_bytes(frames: list[bytes]) -> bytes:
    """Encode frames as length-prefixed bytes + a 0-length terminator."""
    parts: list[bytes] = []
    for frame in frames:
        parts.append(struct.pack(_LEN_FORMAT, len(frame)))
        parts.append(frame)
    parts.append(struct.pack(_LEN_FORMAT, 0))
    return b"".join(parts)


def _split_status_and_frames(stdout: bytes) -> tuple[dict, list[bytes]]:
    """Split the bridge's stdout into the JSON status line + trailing frames.

    The first line (up to and including the first ``\\n``) is the UTF-8 JSON
    status; any bytes after it are the length-prefixed response frame list.
    """
    newline = stdout.find(b"\n")
    if newline < 0:
        raise ValueError("bridge stdout has no status line")
    status = json.loads(stdout[:newline].decode("utf-8"))
    if not isinstance(status, dict):
        raise ValueError("bridge status is not a JSON object")
    remainder = stdout[newline + 1 :]
    frames = _decode_frame_list(remainder)
    return status, frames


def _decode_frame_list(blob: bytes) -> list[bytes]:
    """Decode length-prefixed frames (terminated by a 0 length) from *blob*."""
    frames: list[bytes] = []
    offset = 0
    while offset + _LEN_SIZE <= len(blob):
        (length,) = struct.unpack_from(_LEN_FORMAT, blob, offset)
        offset += _LEN_SIZE
        if length == 0:
            break
        if offset + length > len(blob):
            raise ValueError("truncated response frame from bridge")
        frames.append(blob[offset : offset + length])
        offset += length
    return frames


class GuestParserBridge:
    """Spawns the 3.14 helper per op; maps results to the manager's expectations.

    One instance is built by the launcher when the running interpreter needs the
    bridge.  Each call spawns a fresh subprocess (low-frequency workload — no
    daemon).  Construction resolves the interpreter ONCE (fail-closed if none
    qualifies) so a missing bridge is caught at wiring time, not at first probe.
    """

    def __init__(
        self,
        *,
        bridge_python: str = "",
        mtls_cert: str = "",
        mtls_key: str = "",
        mtls_ca: str = "",
        bridge_module: str = "launcher.guest_parser_bridge",
        repo_root: Path | None = None,
        _command: list[str] | None = None,
    ) -> None:
        # ``_command`` is a test seam (a fake bridge executable); production
        # resolves via discovery.
        self._command = (
            list(_command)
            if _command is not None
            else discover_bridge_command(bridge_python)
        )
        self._bridge_module = bridge_module
        self._mtls_cert = mtls_cert
        self._mtls_key = mtls_key
        self._mtls_ca = mtls_ca
        self._repo_root = (
            repo_root if repo_root is not None else Path(__file__).resolve().parents[1]
        )

    @property
    def command(self) -> list[str]:
        """The resolved bridge interpreter command (read-only)."""
        return list(self._command)

    def _job(self, op: str, endpoint: "ParserEndpoint") -> dict:  # noqa: F821
        return {
            "op": op,
            "vm_id": endpoint.vm_id,
            "service_guid": endpoint.service_guid,
            "vsock_port": endpoint.vsock_port,
            "timeout_s": endpoint.timeout_s,
            "mtls_cert": self._mtls_cert,
            "mtls_key": self._mtls_key,
            "mtls_ca": self._mtls_ca,
        }

    def _run(
        self, op: str, endpoint: "ParserEndpoint", request_frames: list[bytes]  # noqa: F821
    ) -> tuple[dict, list[bytes]] | None:
        """Spawn the bridge for one op; return (status, frames) or None on failure.

        Timeout-bounded by ``endpoint.timeout_s`` plus a small spawn margin.  A
        crash, timeout, non-JSON status, or non-zero exit with no parseable
        status all map to None (fail-closed at the call site).
        """
        job_line = (json.dumps(self._job(op, endpoint)) + "\n").encode("utf-8")
        stdin_payload = job_line
        if op in ("health", "parse"):
            stdin_payload += _frame_list_bytes(request_frames)

        # The bridge runs as `-m launcher.guest_parser_bridge`, so it needs the
        # repo root on its import path (PYTHONPATH) — it imports shared.ipc.*.
        env = dict(os.environ)
        existing = env.get("PYTHONPATH", "")
        repo = str(self._repo_root)
        env["PYTHONPATH"] = repo + (os.pathsep + existing if existing else "")

        # Spawn margin over the op's own budget: connect + interpreter start.
        timeout_s = float(endpoint.timeout_s) + 15.0
        try:
            proc = subprocess.run(
                [*self._command, "-m", self._bridge_module],
                input=stdin_payload,
                capture_output=True,
                timeout=timeout_s,
                check=False,
                env=env,
                cwd=repo,
            )
        except subprocess.TimeoutExpired:
            logger.error("guest-parser bridge timed out (op=%s) — fail-closed", op)
            return None
        except (OSError, subprocess.SubprocessError) as exc:
            logger.error(
                "guest-parser bridge spawn failed (op=%s): %s — fail-closed",
                op,
                type(exc).__name__,
            )
            return None

        if proc.stderr:
            # Structural labels only (the bridge never logs content); surface at
            # debug so a failing bridge is diagnosable without leaking.
            logger.debug(
                "guest-parser bridge stderr (op=%s): %s",
                op,
                proc.stderr.decode("utf-8", errors="replace").strip()[:500],
            )
        try:
            status, frames = _split_status_and_frames(proc.stdout)
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.error(
                "guest-parser bridge produced unparseable output (op=%s): %s "
                "(exit=%s) — fail-closed",
                op,
                type(exc).__name__,
                proc.returncode,
            )
            return None
        return status, frames

    # ── ops ───────────────────────────────────────────────────────────────

    def reachable(self, endpoint: "ParserEndpoint") -> bool:  # noqa: F821
        """Transport reachability via the bridge (open + close AF_HYPERV)."""
        result = self._run("reachable", endpoint, [])
        if result is None:
            return False
        status, _frames = result
        return bool(status.get("ok"))

    def health(
        self, endpoint: "ParserEndpoint", request_frames: list[bytes]
    ) -> bool:  # noqa: F821
        """Frame-level health: send a minimal parse request, require a well-formed
        response.  Never raises (fail-closed False on any failure)."""
        result = self._run("health", endpoint, request_frames)
        if result is None:
            return False
        status, _frames = result
        return bool(status.get("ok"))

    def parse(
        self, endpoint: "ParserEndpoint", request_frames: list[bytes]
    ) -> list[bytes] | None:  # noqa: F821
        """Full parse round-trip: returns the response frames, or None on failure."""
        result = self._run("parse", endpoint, request_frames)
        if result is None:
            return None
        status, frames = result
        if not status.get("ok"):
            return None
        return frames
