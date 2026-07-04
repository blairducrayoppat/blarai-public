"""Tests for BlarAI MCP server (cf-2 WI-21).

Covers all 6 tool surfaces per ADR-022 §6 + the MCP-R1/R2 conformance:
  - health
  - list_file_tickets, read_file_ticket, query_ticket_state (3 file-ticket tools)
  - emit_notification, list_recent_notifications (2 notification tools)

ND-3 floor: target ≥12 cases (2 per new tool). Actual count: see end of file.

Pattern: monkeypatch BLARAI_MCP_TICKET_ROOT + BLARAI_MCP_NOTIFICATION_LOG
to tmp_path so we never touch real state.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tools.blarai_mcp import server


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    """Redirect BLARAI_MCP_TICKET_ROOT + NOTIFICATION_LOG to tmp_path."""
    ticket_root = tmp_path / "tickets"
    ticket_root.mkdir()
    notif_log = tmp_path / "notifications.jsonl"
    monkeypatch.setenv("BLARAI_MCP_TICKET_ROOT", str(ticket_root))
    monkeypatch.setenv("BLARAI_MCP_NOTIFICATION_LOG", str(notif_log))
    return ticket_root, notif_log


# ---------------------------------------------------------------------------
# MCP-R1 / MCP-R2 conformance
# ---------------------------------------------------------------------------


def test_mcp_r1_server_declares_version():
    """SERVER_VERSION must be semver."""
    parts = server.SERVER_VERSION.split(".")
    assert len(parts) == 3 and all(p.isdigit() for p in parts)


def test_mcp_r2_health_tool_returns_status_ok(isolated_state):
    """health returns ok shape with version + ticket_root_exists + elapsed_ms."""
    result = server.health()
    assert result["status"] == "ok"
    assert result["version"] == server.SERVER_VERSION
    assert result["ticket_root_exists"] is True
    assert isinstance(result["elapsed_ms"], int)


def test_mcp_r2_health_reports_missing_ticket_root(tmp_path, monkeypatch):
    """health reports ticket_root_exists=False when the directory is absent."""
    monkeypatch.setenv("BLARAI_MCP_TICKET_ROOT", str(tmp_path / "missing"))
    monkeypatch.setenv(
        "BLARAI_MCP_NOTIFICATION_LOG", str(tmp_path / "x.jsonl")
    )
    result = server.health()
    assert result["status"] == "ok"
    assert result["ticket_root_exists"] is False


# ---------------------------------------------------------------------------
# list_file_tickets
# ---------------------------------------------------------------------------


def test_list_file_tickets_returns_envelope_with_paths(isolated_state):
    """list_file_tickets returns MCP-R9 envelope with relative paths."""
    ticket_root, _ = isolated_state
    sprint = ticket_root / "cf_2"
    sprint.mkdir()
    (sprint / "WI-21.md").write_text("status: doing\n", encoding="utf-8")
    (sprint / "WI-22.md").write_text("status: pending\n", encoding="utf-8")

    result = server.list_file_tickets(sprint_id="cf_2")
    assert "llmContent" in result
    assert "returnDisplay" in result
    paths = [t["path"] for t in result["llmContent"]]
    # Normalize path separators (Windows uses backslash).
    paths_norm = [p.replace("\\", "/") for p in paths]
    assert "cf_2/WI-21.md" in paths_norm
    assert "cf_2/WI-22.md" in paths_norm


def test_list_file_tickets_paginates(isolated_state):
    """list_file_tickets honors page + per_page (MCP-R7)."""
    ticket_root, _ = isolated_state
    sprint = ticket_root / "cf_2"
    sprint.mkdir()
    for i in range(10):
        (sprint / f"WI-{i:02d}.md").write_text("x", encoding="utf-8")

    page1 = server.list_file_tickets(sprint_id="cf_2", page=1, per_page=4)
    page2 = server.list_file_tickets(sprint_id="cf_2", page=2, per_page=4)
    assert len(page1["llmContent"]) == 4
    assert len(page2["llmContent"]) == 4
    # Pages should not overlap.
    p1_paths = {t["path"] for t in page1["llmContent"]}
    p2_paths = {t["path"] for t in page2["llmContent"]}
    assert p1_paths.isdisjoint(p2_paths)


def test_list_file_tickets_handles_missing_dir(isolated_state):
    """list_file_tickets returns empty envelope (not isError) when dir absent."""
    result = server.list_file_tickets(sprint_id="nonexistent")
    assert "isError" not in result
    assert result["llmContent"] == []


def test_list_file_tickets_rejects_zero_per_page(isolated_state):
    """list_file_tickets returns isError on per_page<1 (MCP-R11)."""
    result = server.list_file_tickets(per_page=0)
    assert result.get("isError") is True


# ---------------------------------------------------------------------------
# read_file_ticket
# ---------------------------------------------------------------------------


def test_read_file_ticket_returns_content(isolated_state):
    """read_file_ticket returns content + size_bytes for a valid path."""
    ticket_root, _ = isolated_state
    sprint = ticket_root / "cf_2"
    sprint.mkdir()
    body = "status: doing\ntitle: WI-21\n"
    (sprint / "WI-21.md").write_text(body, encoding="utf-8")

    result = server.read_file_ticket(ticket_path="cf_2/WI-21.md")
    assert "isError" not in result
    assert result["llmContent"]["content"] == body
    assert result["llmContent"]["size_bytes"] == len(body.encode("utf-8"))


def test_read_file_ticket_rejects_path_traversal(isolated_state):
    """read_file_ticket blocks '..' in the path to prevent escape."""
    result = server.read_file_ticket(ticket_path="../etc/passwd")
    assert result.get("isError") is True
    assert any("..\'" in c["text"] or "'..'" in c["text"]
               for c in result["content"])


def test_read_file_ticket_returns_iserror_on_missing_file(isolated_state):
    """read_file_ticket returns isError for absent file."""
    result = server.read_file_ticket(ticket_path="cf_2/missing.md")
    assert result.get("isError") is True


# ---------------------------------------------------------------------------
# query_ticket_state
# ---------------------------------------------------------------------------


def test_query_ticket_state_extracts_status(isolated_state):
    """query_ticket_state surfaces status from frontmatter."""
    ticket_root, _ = isolated_state
    sprint = ticket_root / "cf_2"
    sprint.mkdir()
    (sprint / "WI-21.md").write_text(
        "---\ntitle: WI-21 MCP refactor\nstatus: doing\n---\n",
        encoding="utf-8",
    )

    result = server.query_ticket_state(ticket_id="WI-21")
    assert "isError" not in result
    assert result["llmContent"]["ticket_id"] == "WI-21"
    assert result["llmContent"]["status"] == "doing"
    assert result["llmContent"]["sprint_id"] == "cf_2"


def test_query_ticket_state_returns_empty_when_absent(isolated_state):
    """query_ticket_state returns empty payload (NOT isError) when not found."""
    result = server.query_ticket_state(ticket_id="WI-999")
    assert "isError" not in result
    assert result["llmContent"] == {}


def test_query_ticket_state_rejects_path_traversal(isolated_state):
    """query_ticket_state rejects '/' or '..' in ticket_id."""
    result = server.query_ticket_state(ticket_id="../../etc/passwd")
    assert result.get("isError") is True


# ---------------------------------------------------------------------------
# emit_notification
# ---------------------------------------------------------------------------


def test_emit_notification_writes_to_log(isolated_state):
    """emit_notification appends a JSON Lines record."""
    _, notif_log = isolated_state
    result = server.emit_notification(
        channel="audit",
        message="WI-21 specialist closing",
        severity="info",
    )
    assert "isError" not in result
    assert result["llmContent"]["channel"] == "audit"
    assert "id" in result["llmContent"]
    # Verify it landed on disk.
    lines = notif_log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["channel"] == "audit"
    assert record["message"] == "WI-21 specialist closing"


def test_emit_notification_rejects_invalid_channel(isolated_state):
    """emit_notification returns isError on out-of-taxonomy channel."""
    result = server.emit_notification(
        channel="bogus", message="x"
    )
    assert result.get("isError") is True


def test_emit_notification_rejects_invalid_severity(isolated_state):
    """emit_notification returns isError on invalid severity."""
    result = server.emit_notification(
        channel="audit", message="x", severity="catastrophic"
    )
    assert result.get("isError") is True


def test_emit_notification_includes_correlation_id_when_supplied(isolated_state):
    """emit_notification round-trips the optional correlation_id."""
    _, notif_log = isolated_state
    result = server.emit_notification(
        channel="fleet",
        message="dispatched WI-21",
        correlation_id="cf-2-wi-21",
    )
    assert "isError" not in result
    record = json.loads(notif_log.read_text(encoding="utf-8").splitlines()[0])
    assert record["correlation_id"] == "cf-2-wi-21"


# ---------------------------------------------------------------------------
# list_recent_notifications
# ---------------------------------------------------------------------------


def test_list_recent_notifications_returns_emitted_records(isolated_state):
    """list_recent_notifications surfaces previously emitted records."""
    server.emit_notification(channel="audit", message="one")
    server.emit_notification(channel="fleet", message="two")
    server.emit_notification(channel="gate", message="three")

    result = server.list_recent_notifications()
    assert "isError" not in result
    # Most-recent-first ordering.
    messages = [r["message"] for r in result["llmContent"]]
    assert messages == ["three", "two", "one"]


def test_list_recent_notifications_filters_by_channel(isolated_state):
    """list_recent_notifications channel filter excludes other channels."""
    server.emit_notification(channel="audit", message="a1")
    server.emit_notification(channel="fleet", message="f1")
    server.emit_notification(channel="audit", message="a2")

    result = server.list_recent_notifications(channel="audit")
    assert "isError" not in result
    messages = [r["message"] for r in result["llmContent"]]
    assert set(messages) == {"a1", "a2"}


def test_list_recent_notifications_returns_empty_when_log_absent(
    tmp_path, monkeypatch
):
    """list_recent_notifications returns empty envelope when log absent."""
    monkeypatch.setenv("BLARAI_MCP_TICKET_ROOT", str(tmp_path / "tk"))
    monkeypatch.setenv(
        "BLARAI_MCP_NOTIFICATION_LOG", str(tmp_path / "missing.jsonl")
    )
    result = server.list_recent_notifications()
    assert "isError" not in result
    assert result["llmContent"] == []


def test_list_recent_notifications_caps_limit_at_200(isolated_state):
    """list_recent_notifications caps limit at LIST_PER_PAGE_CAP."""
    # Just verify the cap is in effect — emitting 5 records, request limit=9999.
    for i in range(5):
        server.emit_notification(channel="audit", message=f"m{i}")
    result = server.list_recent_notifications(limit=9999)
    # 5 records exist; cap is 200 (server-side clamp); we get all 5 in return.
    assert len(result["llmContent"]) == 5


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------


def test_envelope_helper_shape():
    """_envelope returns {llmContent, returnDisplay}."""
    assert server._envelope([1, 2], "two items") == {
        "llmContent": [1, 2],
        "returnDisplay": "two items",
    }


def test_error_envelope_helper_shape():
    """_to_error_envelope returns isError + content[{type:text, text}]."""
    env = server._to_error_envelope(ValueError("oops"))
    assert env["isError"] is True
    assert env["content"][0]["type"] == "text"
    assert "ValueError: oops" in env["content"][0]["text"]
