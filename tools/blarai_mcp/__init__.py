"""BlarAI-side MCP server scaffolding (cf-2 WI-21 BUILD-CF-2).

Per ADR-022 §6.2 + cf-2 EDD §B.7 BlarAI MCP gaps closure. Exposes a small
surface area distinct from the devplatform-side Vikunja MCP:

  - 3 file-ticket-read tools (ADOPT-CF-2 alignment with ADR-021 sync surface):
      list_file_tickets, read_file_ticket, query_ticket_state
  - 2 notification-channel tools (BUILD-CF-2 per ADR-024 surface):
      emit_notification, list_recent_notifications
  - 1 conditional placeholder (Anthropic-primitive-shift guard):
      health (always returns a stub; conditional tools materialize when
      the LA activates the corresponding workstream).

The package is scaffolding — concrete persistence wiring lives behind
``BLARAI_MCP_TICKET_ROOT`` / ``BLARAI_MCP_NOTIFICATION_LOG`` env vars so the
tests can exercise the surface against a tmp_path without touching real
state. cf-3 wires the production paths.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
