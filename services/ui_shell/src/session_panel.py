"""
Session Panel Widget (P1.12, ADR-009)
=====================================
Left-docked sidebar listing conversation sessions. Each entry
shows title, timestamp, and turn count. Sessions are persisted
via the SessionStore (P1.11 ui_gateway).

SessionStore methods are synchronous (SQLite). All calls are wrapped
with ``asyncio.to_thread()`` to avoid blocking the Textual event loop.

Layout:
  ┌─────────────┐
  │ Sessions     │  ← header label
  │─────────────│
  │ ▸ Session 1 │  ← active session highlighted
  │   Session 2 │
  │   Session 3 │
  │─────────────│
  │ [+ New]      │  ← Ctrl+N
  └─────────────┘
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from rich.markup import escape
from textual.containers import Vertical
from textual.widgets import Label, ListItem, ListView, Static

from .constants import TITLE_PLACEHOLDER

if TYPE_CHECKING:
    from services.ui_gateway.src.session_store import SessionStore, SessionSummary


class SessionListItem(ListItem):
    """Single session entry in the sidebar."""

    def __init__(self, summary: SessionSummary, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.session_id: str = summary.id
        self._summary = summary

    def _label_markup(self) -> str:
        """Build the entry's display markup.

        The session title now carries real user text (the first prompt, or
        a /rename value), so it is escaped before interpolation — a title
        containing ``[...]`` must render literally, not as a Rich markup
        tag. The ``[dim]`` around the turn count is our own markup and is
        intentionally left live.
        """
        title = escape(self._summary.title or TITLE_PLACEHOLDER)
        turns = self._summary.turn_count
        return f"{title}  [dim]({turns})[/dim]"

    def compose(self):  # type: ignore[override]
        yield Label(self._label_markup())


class SessionPanel(Vertical):
    """Session management sidebar widget.

    Parameters
    ----------
    store : SessionStore | None
        Injected session store. If None, the panel is non-functional
        (Fail-Closed: no sessions available).
    """

    DEFAULT_CSS = """
    SessionPanel {
        width: 25%;
        dock: left;
        border-right: solid $primary;
        padding: 0 1;
    }
    """

    def __init__(
        self,
        store: SessionStore | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._store = store
        self._active_session_id: str | None = None

    def compose(self):  # type: ignore[override]
        yield Static("Sessions", classes="panel-header")
        yield ListView(id="session-list")

    async def on_mount(self) -> None:
        """Load sessions on mount."""
        await self.refresh_list()

    # ── Public API ────────────────────────────────────────────────

    async def refresh_list(self) -> None:
        """Reload session list from store.

        SessionStore.list_sessions() is synchronous (SQLite) —
        wrapped with asyncio.to_thread() to avoid blocking.
        """
        if self._store is None:
            return
        sessions: list[SessionSummary] = await asyncio.to_thread(
            self._store.list_sessions
        )
        list_view = self.query_one("#session-list", ListView)
        await list_view.clear()
        for summary in sessions:
            item = SessionListItem(summary)
            if summary.is_active:
                self._active_session_id = summary.id
                item.highlighted = True
            await list_view.append(item)

    async def create_new_session(self) -> None:
        """Create a new session and refresh the list.

        SessionStore.create_session() returns a UUID string (sync).
        """
        if self._store is None:
            return
        session_id: str = await asyncio.to_thread(self._store.create_session)
        await asyncio.to_thread(self._store.set_active_session, session_id)
        self._active_session_id = session_id
        await self.refresh_list()

    async def delete_current_session(self) -> None:
        """Delete the active session and refresh the list."""
        if self._store is None or self._active_session_id is None:
            return
        await asyncio.to_thread(
            self._store.delete_session, self._active_session_id
        )
        self._active_session_id = None
        await self.refresh_list()

    async def select_session(self, session_id: str) -> None:
        """Switch the active session to the given ID."""
        if self._store is None:
            return
        await asyncio.to_thread(self._store.set_active_session, session_id)
        self._active_session_id = session_id
        await self.refresh_list()

    @property
    def active_session_id(self) -> str | None:
        """The currently selected session ID."""
        return self._active_session_id
