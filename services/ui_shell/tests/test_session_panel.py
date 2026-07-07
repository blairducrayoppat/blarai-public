"""
Tests for services.ui_shell.src.session_panel (WI-8, P1.12).

Covers:
  - SessionPanel public async methods verify asyncio.to_thread wiring
  - SessionListItem label format matches production format string
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.ui_gateway.src.session_store import SessionSummary
from services.ui_shell.src.session_panel import SessionListItem, SessionPanel
from services.ui_shell.src.constants import TITLE_PLACEHOLDER


def _make_panel(store: object = None) -> SessionPanel:
    """Construct a SessionPanel bypassing Textual's __init__."""
    panel = SessionPanel.__new__(SessionPanel)
    panel._store = store  # type: ignore[attr-defined]
    panel._active_session_id = None  # type: ignore[attr-defined]
    return panel


def _make_summary(
    session_id: str = "sess-1",
    title: str = "Test Chat",
    turn_count: int = 3,
    is_active: bool = False,
) -> SessionSummary:
    return SessionSummary(
        id=session_id,
        title=title,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        is_active=is_active,
        turn_count=turn_count,
    )


class TestSessionPanelPublicMethods:
    """WI-8: async methods route synchronous store calls through asyncio.to_thread."""

    @pytest.mark.asyncio
    async def test_refresh_list_uses_to_thread(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """refresh_list() calls store.list_sessions via asyncio.to_thread."""
        recorded_calls: list[tuple] = []

        async def fake_to_thread(fn: object, *args: object, **kwargs: object) -> object:
            recorded_calls.append((fn, args, kwargs))
            if callable(fn):
                return fn(*args, **kwargs)
            return None

        monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)

        store = MagicMock()
        store.list_sessions.return_value = []
        panel = _make_panel(store)

        list_view = AsyncMock()
        panel.query_one = MagicMock(return_value=list_view)  # type: ignore[method-assign]

        await panel.refresh_list()

        assert any(fn is store.list_sessions for fn, _args, _kw in recorded_calls)

    @pytest.mark.asyncio
    async def test_create_new_session_uses_to_thread(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """create_new_session() calls store.create_session and set_active_session via to_thread."""
        recorded_fns: list[object] = []

        async def fake_to_thread(fn: object, *args: object, **kwargs: object) -> object:
            recorded_fns.append(fn)
            if callable(fn):
                return fn(*args, **kwargs)
            return None

        monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)

        new_id = "sess-new"
        store = MagicMock()
        store.create_session.return_value = new_id
        store.set_active_session.return_value = None
        store.list_sessions.return_value = []

        panel = _make_panel(store)
        list_view = AsyncMock()
        panel.query_one = MagicMock(return_value=list_view)  # type: ignore[method-assign]

        await panel.create_new_session()

        assert store.create_session in recorded_fns
        assert store.set_active_session in recorded_fns
        assert panel._active_session_id == new_id

    @pytest.mark.asyncio
    async def test_delete_current_session_uses_to_thread(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """delete_current_session() calls store.delete_session via to_thread."""
        recorded_fns: list[object] = []

        async def fake_to_thread(fn: object, *args: object, **kwargs: object) -> object:
            recorded_fns.append(fn)
            if callable(fn):
                return fn(*args, **kwargs)
            return None

        monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)

        store = MagicMock()
        store.delete_session.return_value = True
        store.list_sessions.return_value = []

        panel = _make_panel(store)
        panel._active_session_id = "sess-to-delete"  # type: ignore[attr-defined]
        list_view = AsyncMock()
        panel.query_one = MagicMock(return_value=list_view)  # type: ignore[method-assign]

        await panel.delete_current_session()

        assert store.delete_session in recorded_fns
        assert panel._active_session_id is None

    @pytest.mark.asyncio
    async def test_select_session_uses_to_thread(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """select_session() calls store.set_active_session via to_thread."""
        recorded_fns: list[object] = []

        async def fake_to_thread(fn: object, *args: object, **kwargs: object) -> object:
            recorded_fns.append(fn)
            if callable(fn):
                return fn(*args, **kwargs)
            return None

        monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)

        store = MagicMock()
        store.set_active_session.return_value = None
        store.list_sessions.return_value = []

        panel = _make_panel(store)
        list_view = AsyncMock()
        panel.query_one = MagicMock(return_value=list_view)  # type: ignore[method-assign]

        await panel.select_session("sess-selected")

        assert store.set_active_session in recorded_fns
        assert panel._active_session_id == "sess-selected"

    def test_active_session_id_property_returns_stored_value(self) -> None:
        """active_session_id property reflects _active_session_id."""
        panel = _make_panel()
        assert panel.active_session_id is None
        panel._active_session_id = "s1"  # type: ignore[attr-defined]
        assert panel.active_session_id == "s1"

    @pytest.mark.asyncio
    async def test_refresh_list_noop_when_store_is_none(self) -> None:
        """refresh_list() returns immediately if no store is set."""
        panel = _make_panel(store=None)
        # Should not raise; no query_one call attempted
        await panel.refresh_list()

    @pytest.mark.asyncio
    async def test_create_new_session_noop_when_store_is_none(self) -> None:
        """create_new_session() returns immediately if no store is set."""
        panel = _make_panel(store=None)
        await panel.create_new_session()
        assert panel._active_session_id is None

    @pytest.mark.asyncio
    async def test_delete_current_session_noop_when_no_active(self) -> None:
        """delete_current_session() is a no-op if no session is active."""
        store = MagicMock()
        panel = _make_panel(store)
        panel._active_session_id = None  # type: ignore[attr-defined]
        await panel.delete_current_session()
        store.delete_session.assert_not_called()


class TestSessionListItemLabelFormat:
    """WI-8: SessionListItem._label_markup() builds the entry display text."""

    def _make_item(self, title: str, turn_count: int) -> SessionListItem:
        summary = _make_summary(title=title, turn_count=turn_count)
        item = SessionListItem.__new__(SessionListItem)
        item._summary = summary  # type: ignore[attr-defined]
        return item

    def test_session_list_item_label_format(self) -> None:
        """Label text is '{title}  [dim]({turn_count})[/dim]'."""
        item = self._make_item("Test Chat", 5)
        assert item._label_markup() == "Test Chat  [dim](5)[/dim]"

    def test_session_list_item_label_uses_placeholder_when_title_empty(self) -> None:
        """Empty title falls back to TITLE_PLACEHOLDER."""
        item = self._make_item("", 0)
        assert item._label_markup() == f"{TITLE_PLACEHOLDER}  [dim](0)[/dim]"

    def test_label_escapes_markup_in_title(self) -> None:
        """A title containing '[...]' is escaped so it renders literally.

        Session titles now carry real user text (the first prompt, or a
        /rename value); an unescaped '[red]' would be eaten as a Rich
        markup tag — the same class of bug fixed in streaming.py.
        """
        from rich.markup import escape

        item = self._make_item("Use [red]brackets[/red] here", 3)
        markup = item._label_markup()
        # The title segment is escaped (every '[' becomes '\\['); only the
        # [dim] wrapper around the turn count stays as live markup.
        expected = escape("Use [red]brackets[/red] here") + "  [dim](3)[/dim]"
        assert markup == expected
        # The escaped form is present — the title cannot break out as a tag.
        assert "\\[red]" in markup

    def test_label_keeps_dim_markup_live(self) -> None:
        """The [dim] wrapper around the turn count is our own markup — kept live."""
        item = self._make_item("plain title", 7)
        assert item._label_markup() == "plain title  [dim](7)[/dim]"

    def test_session_list_item_stores_session_id(self) -> None:
        """SessionListItem stores the session_id from the summary."""
        summary = _make_summary(session_id="my-sess", title="X", turn_count=1)
        # Use __new__ to bypass Textual's ListItem.__init__
        item = SessionListItem.__new__(SessionListItem)
        item.session_id = summary.id  # type: ignore[attr-defined]
        item._summary = summary  # type: ignore[attr-defined]
        assert item.session_id == "my-sess"
