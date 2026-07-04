"""BlarAI MCP server (cf-2 WI-21).

Per ADR-022 §6 BlarAI MCP gaps disposition:
  - file-ticket-read tools (3) — ADOPT-CF-2 alignment with ADR-021 sync surface
  - notification-channel tools (2) — BUILD-CF-2 per ADR-024 surface
  - conditional placeholder (1) — defer/build per Anthropic primitive shifts

Design conformance with ADR-022 14-rule ruleset:
  - MCP-R1: SERVER_VERSION semver pin.
  - MCP-R2: ``health`` tool exposed.
  - MCP-R3: no plaintext secrets in env vars (this server has no auth surface).
  - MCP-R4: ``instructions`` block ≤200 tokens, three-element discipline.
  - MCP-R5: ``<verb>_<object>`` snake_case naming on all tools.
  - MCP-R6: typed parameters; no stringified-JSON inputs.
  - MCP-R7: pagination on list tools.
  - MCP-R8: tool docstrings ≤100 tokens; rationale in source comments.
  - MCP-R9: ``llmContent`` / ``returnDisplay`` envelope.
  - MCP-R10: parsed JSON in ``llmContent``, not stringified.
  - MCP-R11: ``isError: true`` envelope on expected errors.

Configuration (env-var indirection per MCP-R3):
  - BLARAI_MCP_TICKET_ROOT: directory hosting file-ticket substrate
        (defaults to .tickets/ at the cwd). Maps to ADR-021 §6 substrate.
  - BLARAI_MCP_NOTIFICATION_LOG: JSON Lines log file path
        (defaults to .blarai-notifications.jsonl). Maps to ADR-024 surface.

Run via: ``python -m tools.blarai_mcp.server`` (stdio transport).
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

# Pydantic-on-py311 needs typing_extensions.TypedDict (see devplatform
# tools/vikunja_mcp/server.py WI-21 note).
from typing_extensions import TypedDict


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SERVER_VERSION = "0.1.0"  # MCP-R1 semver pin.
LIST_PER_PAGE_CAP = 200  # MCP-R7 max page size.
NOTIFICATION_LIST_DEFAULT = 50

DEFAULT_TICKET_ROOT = ".tickets"
DEFAULT_NOTIFICATION_LOG = ".blarai-notifications.jsonl"

logger = logging.getLogger("blarai_mcp")


def _ticket_root() -> Path:
    """Resolve the active ticket-root directory.

    Lazy-resolved so tests can monkeypatch BLARAI_MCP_TICKET_ROOT after import.
    """
    return Path(os.environ.get("BLARAI_MCP_TICKET_ROOT", DEFAULT_TICKET_ROOT))


def _notification_log() -> Path:
    """Resolve the active notification-log path (lazy for the same reason)."""
    return Path(
        os.environ.get("BLARAI_MCP_NOTIFICATION_LOG", DEFAULT_NOTIFICATION_LOG)
    )


# ---------------------------------------------------------------------------
# Envelope helpers (MCP-R9 / MCP-R10 / MCP-R11)
# ---------------------------------------------------------------------------


def _envelope(structured: Any, summary: str) -> dict:
    """Wrap a parsed-JSON payload + human summary per MCP-R9 / MCP-R10."""
    return {"llmContent": structured, "returnDisplay": summary}


def _to_error_envelope(e: Exception) -> dict:
    """Convert an expected exception to the MCP-R11 isError envelope."""
    return {
        "isError": True,
        "content": [
            {"type": "text", "text": f"{type(e).__name__}: {e}"}
        ],
    }


# ---------------------------------------------------------------------------
# Typed parameter specs (MCP-R6)
# ---------------------------------------------------------------------------


class NotificationSpec(TypedDict, total=False):
    """Typed spec for emit_notification per ADR-024 surface.

    Required: ``channel`` (one of audit|fleet|gate per ADR-024 §4 taxonomy)
    + ``message``. Optional: ``severity`` (info|warn|critical), ``correlation_id``.
    """

    channel: str
    message: str
    severity: str
    correlation_id: str


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "BlarAI MCP",
    instructions=(
        "BlarAI-side MCP tools for cf-program ticket-state queries + "
        "notification-channel emission. State: file-ticket substrate (read) "
        "+ notification log (append). "
        "Use these to inspect cf-program tickets without git checkout + emit "
        "audit/fleet/gate events. "
        "Do NOT use these tools for code commits, Vikunja CRUD, or runtime "
        "configuration — those belong to git Bash, Vikunja MCP, and the "
        "settings-specialist surfaces respectively."
    ),
)
# MCP-R1 semver pin on the underlying low-level Server.
mcp._mcp_server.version = SERVER_VERSION


# ── Health (MCP-R2) ───────────────────────────────────────────────────────


@mcp.tool()
def health() -> dict:
    """Return server health: status, version, ticket_root existence.

    Returns:
        ``{status, version, ticket_root_exists, notification_log_path}``.
    """
    start = time.monotonic()
    ticket_root = _ticket_root()
    elapsed_ms = int((time.monotonic() - start) * 1000)
    return {
        "status": "ok",
        "version": SERVER_VERSION,
        "ticket_root_exists": ticket_root.exists(),
        "notification_log_path": str(_notification_log()),
        "elapsed_ms": elapsed_ms,
    }


# ── File-ticket read tools (3 — ADR-021 sync surface) ─────────────────────


@mcp.tool()
def list_file_tickets(
    sprint_id: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> dict:
    """List file-tickets under the ticket-root.

    Args:
        sprint_id: Optional sprint subdir filter (e.g., 'cf_2').
        page: 1-based page number.
        per_page: Items per page (default 50, cap 200).

    Returns:
        ``{"llmContent": [<ticket-stub>...], "returnDisplay": "<summary>"}``.
    """
    try:
        if per_page > LIST_PER_PAGE_CAP:
            per_page = LIST_PER_PAGE_CAP
        if per_page < 1 or page < 1:
            raise ValueError("page and per_page must be >= 1")

        root = _ticket_root()
        if sprint_id is not None:
            scan_root = root / sprint_id
        else:
            scan_root = root

        if not scan_root.exists():
            return _envelope(
                [],
                f"No ticket directory at {scan_root}.",
            )

        # Discover .md tickets (the file-ticket extension per ADR-021).
        all_files = sorted(scan_root.rglob("*.md"))
        start = (page - 1) * per_page
        page_slice = all_files[start : start + per_page]

        result = [
            {
                "path": str(p.relative_to(root)),
                "name": p.name,
                "size_bytes": p.stat().st_size,
            }
            for p in page_slice
        ]
        return _envelope(
            result,
            f"Listed {len(result)} file-ticket(s) "
            f"(page {page}, total {len(all_files)}).",
        )
    except (ValueError, OSError) as e:
        return _to_error_envelope(e)


@mcp.tool()
def read_file_ticket(ticket_path: str) -> dict:
    """Read a single file-ticket by relative path.

    Args:
        ticket_path: Path relative to the ticket-root (e.g., 'cf_2/WI-21.md').

    Returns:
        ``{"llmContent": {"path", "content", "size_bytes"}, "returnDisplay": "<summary>"}``.
    """
    try:
        if not ticket_path or ".." in Path(ticket_path).parts:
            raise ValueError(
                f"Invalid ticket_path {ticket_path!r}: empty or contains '..'."
            )

        root = _ticket_root()
        target = (root / ticket_path).resolve()
        # Path-traversal guard: the resolved path must remain under root.
        root_resolved = root.resolve()
        try:
            target.relative_to(root_resolved)
        except ValueError as exc:
            raise ValueError(
                f"ticket_path {ticket_path!r} escapes ticket-root."
            ) from exc

        if not target.exists():
            raise FileNotFoundError(f"No ticket at {ticket_path!r}")

        content = target.read_text(encoding="utf-8")
        payload = {
            "path": ticket_path,
            "content": content,
            "size_bytes": len(content.encode("utf-8")),
        }
        return _envelope(
            payload,
            f"Read file-ticket {ticket_path} ({payload['size_bytes']} bytes).",
        )
    except (ValueError, FileNotFoundError, OSError) as e:
        return _to_error_envelope(e)


@mcp.tool()
def query_ticket_state(ticket_id: str) -> dict:
    """Query the state of a ticket by ticket_id.

    Scans the ticket-root for a file matching ``<ticket_id>.md`` (case-sensitive)
    and returns its frontmatter-derived state if present. The state shape is
    intentionally minimal (status + sprint_id + path) — Vikunja MCP is the
    canonical source for rich ticket state per ADR-021 §5.

    Args:
        ticket_id: The ticket identifier (e.g., 'WI-21', 'EA-3').

    Returns:
        ``{"llmContent": {"ticket_id", "status", "sprint_id", "path"} or {},
           "returnDisplay": "<summary>"}``.
    """
    try:
        if not ticket_id or "/" in ticket_id or ".." in ticket_id:
            raise ValueError(
                f"Invalid ticket_id {ticket_id!r}: empty, contains '/' or '..'."
            )

        root = _ticket_root()
        if not root.exists():
            return _envelope({}, f"No ticket-root at {root}.")

        candidates = list(root.rglob(f"{ticket_id}.md"))
        if not candidates:
            return _envelope({}, f"No file-ticket for ticket_id={ticket_id!r}.")

        target = candidates[0]
        # Minimal frontmatter scan: read first ~50 lines looking for
        # `status:` and parent dir as sprint_id.
        text = target.read_text(encoding="utf-8")
        head = text.splitlines()[:50]
        status = "unknown"
        for line in head:
            stripped = line.strip()
            if stripped.lower().startswith("status:"):
                status = stripped.split(":", 1)[1].strip().strip("\"'")
                break

        sprint_id = target.parent.name if target.parent != root else None
        payload = {
            "ticket_id": ticket_id,
            "status": status,
            "sprint_id": sprint_id,
            "path": str(target.relative_to(root)),
        }
        return _envelope(
            payload,
            f"Ticket {ticket_id}: status={status}, sprint={sprint_id}.",
        )
    except (ValueError, OSError) as e:
        return _to_error_envelope(e)


# ── Notification-channel tools (2 — ADR-024 surface) ──────────────────────


def _append_notification(record: dict[str, Any]) -> None:
    """Append a notification record to the JSON Lines log atomically.

    Best-effort atomicity via append-only IO. Concurrent writers across
    processes are out of scope for cf-2; cf-3 may add fcntl-based locking.
    """
    log_path = _notification_log()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


@mcp.tool()
def emit_notification(
    channel: str,
    message: str,
    severity: str = "info",
    correlation_id: str | None = None,
) -> dict:
    """Emit a structured notification to the BlarAI notification log.

    Args:
        channel: One of 'audit', 'fleet', 'gate' per ADR-024 §4 taxonomy.
        message: Human-readable event description.
        severity: 'info' | 'warn' | 'critical' (default 'info').
        correlation_id: Optional cross-event correlation key.

    Returns:
        ``{"llmContent": {"id", "channel", "severity", "timestamp"},
           "returnDisplay": "<summary>"}``.
    """
    try:
        valid_channels = {"audit", "fleet", "gate"}
        valid_severities = {"info", "warn", "critical"}
        if channel not in valid_channels:
            raise ValueError(
                f"channel must be one of {sorted(valid_channels)}, got {channel!r}."
            )
        if severity not in valid_severities:
            raise ValueError(
                f"severity must be one of {sorted(valid_severities)}, got {severity!r}."
            )
        if not message:
            raise ValueError("message must be non-empty.")

        event_id = str(uuid.uuid4())
        timestamp = time.time()
        record = {
            "id": event_id,
            "channel": channel,
            "severity": severity,
            "message": message,
            "timestamp": timestamp,
        }
        if correlation_id is not None:
            record["correlation_id"] = correlation_id

        _append_notification(record)

        payload = {
            "id": event_id,
            "channel": channel,
            "severity": severity,
            "timestamp": timestamp,
        }
        return _envelope(
            payload,
            f"Emitted {severity} notification to {channel} channel.",
        )
    except (ValueError, OSError) as e:
        return _to_error_envelope(e)


@mcp.tool()
def list_recent_notifications(
    channel: str | None = None,
    limit: int = NOTIFICATION_LIST_DEFAULT,
) -> dict:
    """List the most recent notifications from the log.

    Args:
        channel: Optional channel filter ('audit', 'fleet', 'gate').
        limit: Max records to return (default 50, cap 200).

    Returns:
        ``{"llmContent": [<record>...], "returnDisplay": "<summary>"}``.
    """
    try:
        if limit > LIST_PER_PAGE_CAP:
            limit = LIST_PER_PAGE_CAP
        if limit < 1:
            raise ValueError("limit must be >= 1")

        log_path = _notification_log()
        if not log_path.exists():
            return _envelope([], f"No notification log at {log_path}.")

        # Read whole file then tail — adequate for cf-2 expected volume.
        # cf-3 may move to a backed tailing implementation for large logs.
        with log_path.open("r", encoding="utf-8") as f:
            lines = f.readlines()

        records: list[dict] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue  # skip malformed lines (defensive)
            if channel is not None and record.get("channel") != channel:
                continue
            records.append(record)

        # Most-recent-first ordering.
        recent = records[-limit:][::-1]
        return _envelope(
            recent,
            f"Found {len(recent)} notification(s)"
            + (f" on channel={channel}" if channel else "")
            + ".",
        )
    except (ValueError, OSError) as e:
        return _to_error_envelope(e)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")
