"""
Tests for services.ui_gateway.src.session_store (P1.11).

Covers:
  - SessionStore schema creation (WAL, foreign keys, tables, indices)
  - create_session (UUID, title truncation, timestamps)
  - list_sessions (ordering, turn counts, active flag)
  - get_session_turns (chronological, deserialized pgov_reasons)
  - add_turn (role validation, FK to session, updated_at bump)
  - delete_session (CASCADE turns, return value)
  - clear_session_turns (preserves session)
  - set_active_session (deactivates others)
  - SessionSummary / Turn dataclass construction
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from services.ui_gateway.src.session_store import (
    SessionStore,
    SessionSummary,
    Turn,
    derive_session_title,
)
from services.ui_gateway.src.constants import (
    SESSION_TITLE_MAX_CHARS,
    SESSION_TITLE_PROMPT_CHARS,
)


# ─────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def store() -> SessionStore:
    """In-memory session store for testing."""
    s = SessionStore(db_path=":memory:")
    yield s  # type: ignore[misc]
    s.close()


# ─────────────────────────────────────────────────────────────────
# Schema
# ─────────────────────────────────────────────────────────────────


class TestSchema:
    """Verify SQLite schema configuration."""

    def test_wal_mode_requested(self, store: SessionStore) -> None:
        """In-memory DBs report 'memory' but WAL was requested.
        Verify WAL is set for file-based DBs via a temp file."""
        import tempfile, os
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "test.db")
            file_store = SessionStore(db_path=db_path)
            try:
                row = file_store._conn.execute("PRAGMA journal_mode").fetchone()
                assert row is not None
                assert row[0] == "wal"
            finally:
                file_store.close()

    def test_foreign_keys_enabled(self, store: SessionStore) -> None:
        row = store._conn.execute("PRAGMA foreign_keys").fetchone()
        assert row is not None
        assert row[0] == 1

    def test_sessions_table_exists(self, store: SessionStore) -> None:
        row = store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'"
        ).fetchone()
        assert row is not None

    def test_turns_table_exists(self, store: SessionStore) -> None:
        row = store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='turns'"
        ).fetchone()
        assert row is not None

    def test_turns_session_index(self, store: SessionStore) -> None:
        row = store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_turns_session'"
        ).fetchone()
        assert row is not None


# ─────────────────────────────────────────────────────────────────
# create_session
# ─────────────────────────────────────────────────────────────────


class TestCreateSession:
    """Session creation, IDs, and title handling."""

    def test_returns_uuid_string(self, store: SessionStore) -> None:
        sid = store.create_session(title="Test")
        assert isinstance(sid, str)
        assert len(sid) == 36  # UUID format

    def test_empty_title_defaults(self, store: SessionStore) -> None:
        sid = store.create_session()
        sessions = store.list_sessions()
        assert any(s.id == sid and s.title == "" for s in sessions)

    def test_title_truncation(self, store: SessionStore) -> None:
        long_title = "A" * (SESSION_TITLE_MAX_CHARS + 50)
        sid = store.create_session(title=long_title)
        sessions = store.list_sessions()
        match = [s for s in sessions if s.id == sid]
        assert len(match) == 1
        assert len(match[0].title) == SESSION_TITLE_MAX_CHARS

    def test_new_session_is_active(self, store: SessionStore) -> None:
        sid = store.create_session(title="Active")
        sessions = store.list_sessions()
        match = [s for s in sessions if s.id == sid]
        assert match[0].is_active is True

    def test_multiple_sessions(self, store: SessionStore) -> None:
        store.create_session()
        store.create_session()
        store.create_session()
        assert len(store.list_sessions()) == 3


# ─────────────────────────────────────────────────────────────────
# list_sessions
# ─────────────────────────────────────────────────────────────────


class TestListSessions:
    """Session listing and ordering."""

    def test_empty_store(self, store: SessionStore) -> None:
        assert store.list_sessions() == []

    def test_ordered_by_updated_desc(self, store: SessionStore) -> None:
        s1 = store.create_session(title="First")
        time.sleep(0.01)  # ensure distinct timestamps
        s2 = store.create_session(title="Second")
        sessions = store.list_sessions()
        assert sessions[0].id == s2
        assert sessions[1].id == s1

    def test_turn_count(self, store: SessionStore) -> None:
        sid = store.create_session()
        store.add_turn(sid, "user", "hi", "N/A", [])
        store.add_turn(sid, "assistant", "hello", "approved", [])
        sessions = store.list_sessions()
        match = [s for s in sessions if s.id == sid]
        assert match[0].turn_count == 2

    def test_returns_session_summary_type(self, store: SessionStore) -> None:
        store.create_session()
        sessions = store.list_sessions()
        assert isinstance(sessions[0], SessionSummary)


# ─────────────────────────────────────────────────────────────────
# add_turn / get_session_turns
# ─────────────────────────────────────────────────────────────────


class TestTurns:
    """Turn creation, retrieval, and validation."""

    def test_add_and_retrieve_turns(self, store: SessionStore) -> None:
        sid = store.create_session()
        store.add_turn(sid, "user", "Hello", "N/A", [])
        store.add_turn(sid, "assistant", "Hi", "approved", [])
        turns = store.get_session_turns(sid)
        assert len(turns) == 2
        assert turns[0].role == "user"
        assert turns[1].role == "assistant"

    def test_turn_has_uuid_id(self, store: SessionStore) -> None:
        sid = store.create_session()
        tid = store.add_turn(sid, "user", "test", "N/A", [])
        assert len(tid) == 36

    def test_turn_pgov_reasons_deserialized(self, store: SessionStore) -> None:
        sid = store.create_session()
        store.add_turn(
            sid, "assistant", "redacted", "denied",
            ["PII_DETECTED", "LEAKAGE_DETECTED"],
        )
        turns = store.get_session_turns(sid)
        assert turns[0].pgov_reasons == ["PII_DETECTED", "LEAKAGE_DETECTED"]

    def test_invalid_role_raises(self, store: SessionStore) -> None:
        sid = store.create_session()
        with pytest.raises(ValueError, match="Invalid role"):
            store.add_turn(sid, "system", "forbidden", "N/A", [])

    def test_turns_chronological_order(self, store: SessionStore) -> None:
        sid = store.create_session()
        store.add_turn(sid, "user", "first", "N/A", [])
        time.sleep(0.01)
        store.add_turn(sid, "assistant", "second", "approved", [])
        turns = store.get_session_turns(sid)
        assert turns[0].content == "first"
        assert turns[1].content == "second"

    def test_add_turn_updates_session_timestamp(self, store: SessionStore) -> None:
        sid = store.create_session()
        sessions_before = store.list_sessions()
        ts_before = sessions_before[0].updated_at
        time.sleep(0.01)
        store.add_turn(sid, "user", "bump", "N/A", [])
        sessions_after = store.list_sessions()
        ts_after = sessions_after[0].updated_at
        assert ts_after > ts_before

    def test_empty_session_has_no_turns(self, store: SessionStore) -> None:
        sid = store.create_session()
        assert store.get_session_turns(sid) == []

    def test_turn_type(self, store: SessionStore) -> None:
        sid = store.create_session()
        store.add_turn(sid, "user", "test", "N/A", [])
        turns = store.get_session_turns(sid)
        assert isinstance(turns[0], Turn)


# ─────────────────────────────────────────────────────────────────
# delete_session
# ─────────────────────────────────────────────────────────────────


class TestDeleteSession:
    """Session deletion with CASCADE."""

    def test_delete_returns_true(self, store: SessionStore) -> None:
        sid = store.create_session()
        assert store.delete_session(sid) is True

    def test_delete_nonexistent_returns_false(self, store: SessionStore) -> None:
        assert store.delete_session("no-such-id") is False

    def test_cascade_deletes_turns(self, store: SessionStore) -> None:
        sid = store.create_session()
        store.add_turn(sid, "user", "hi", "N/A", [])
        store.add_turn(sid, "assistant", "hello", "approved", [])
        store.delete_session(sid)
        # Session gone
        assert len(store.list_sessions()) == 0
        # Turns also gone (verify via raw query)
        row = store._conn.execute(
            "SELECT COUNT(*) FROM turns WHERE session_id = ?", (sid,)
        ).fetchone()
        assert row[0] == 0

    def test_delete_only_target_session(self, store: SessionStore) -> None:
        s1 = store.create_session()
        s2 = store.create_session()
        store.delete_session(s1)
        sessions = store.list_sessions()
        assert len(sessions) == 1
        assert sessions[0].id == s2


# ─────────────────────────────────────────────────────────────────
# clear_session_turns
# ─────────────────────────────────────────────────────────────────


class TestClearSessionTurns:
    """Clearing turns while preserving the session."""

    def test_clear_returns_count(self, store: SessionStore) -> None:
        sid = store.create_session()
        store.add_turn(sid, "user", "a", "N/A", [])
        store.add_turn(sid, "user", "b", "N/A", [])
        count = store.clear_session_turns(sid)
        assert count == 2

    def test_session_preserved_after_clear(self, store: SessionStore) -> None:
        sid = store.create_session()
        store.add_turn(sid, "user", "a", "N/A", [])
        store.clear_session_turns(sid)
        sessions = store.list_sessions()
        assert len(sessions) == 1
        assert sessions[0].id == sid
        assert store.get_session_turns(sid) == []

    def test_clear_empty_session(self, store: SessionStore) -> None:
        sid = store.create_session()
        count = store.clear_session_turns(sid)
        assert count == 0


# ─────────────────────────────────────────────────────────────────
# set_active_session
# ─────────────────────────────────────────────────────────────────


class TestSetActiveSession:
    """Session activation logic."""

    def test_deactivates_others(self, store: SessionStore) -> None:
        s1 = store.create_session(title="A")
        s2 = store.create_session(title="B")
        store.set_active_session(s1)
        sessions = store.list_sessions()
        by_id = {s.id: s for s in sessions}
        assert by_id[s1].is_active is True
        assert by_id[s2].is_active is False

    def test_switch_active(self, store: SessionStore) -> None:
        s1 = store.create_session()
        s2 = store.create_session()
        store.set_active_session(s1)
        store.set_active_session(s2)
        sessions = store.list_sessions()
        by_id = {s.id: s for s in sessions}
        assert by_id[s1].is_active is False
        assert by_id[s2].is_active is True


# ---------------------------------------------------------------------------
# Relocated from tests/integration/test_p114_ui_end_to_end.py per P5_TASK8_EA5 WI-4.
# `slow` marker stripped (3F.3): these are unit-scope service tests.
# ---------------------------------------------------------------------------


class TestP114Relocated:
    """Relocated non-cross-service P114 tests (formerly under tests/integration/)."""

    def test_create_session_returns_uuid_string(self, tmp_path: Path) -> None:
        store = SessionStore(str(tmp_path / "sessions.db"))
        try:
            session_id = store.create_session("Session A")
            uuid.UUID(session_id)
            assert len(session_id) == 36
        finally:
            store.close()


    def test_list_sessions_returns_created_sessions(self, tmp_path: Path) -> None:
        store = SessionStore(str(tmp_path / "sessions.db"))
        try:
            sid = store.create_session("Session B")
            sessions = store.list_sessions()
            assert any(s.id == sid for s in sessions)
        finally:
            store.close()


    def test_add_turn_persists_turn(self, tmp_path: Path) -> None:
        store = SessionStore(str(tmp_path / "sessions.db"))
        try:
            sid = store.create_session("Session C")
            turn_id = store.add_turn(sid, "user", "hello", "N/A", [])
            turns = store.get_turns(sid)
            assert any(t.id == turn_id for t in turns)
        finally:
            store.close()


    def test_get_turns_returns_persisted_turns_in_order(self, tmp_path: Path) -> None:
        store = SessionStore(str(tmp_path / "sessions.db"))
        try:
            sid = store.create_session("Session D")
            store.add_turn(sid, "user", "first", "N/A", [])
            store.add_turn(sid, "assistant", "second", "approved", [])
            turns = store.get_turns(sid)
            assert [t.content for t in turns] == ["first", "second"]
        finally:
            store.close()


    def test_create_session_title_truncated_to_limit(self, tmp_path: Path) -> None:
        store = SessionStore(str(tmp_path / "sessions.db"))
        try:
            long_title = "x" * 200
            sid = store.create_session(long_title)
            sessions = [s for s in store.list_sessions() if s.id == sid]
            assert sessions
            assert len(sessions[0].title) == 80
        finally:
            store.close()


# ─────────────────────────────────────────────────────────────────
# derive_session_title — auto-title derivation
# ─────────────────────────────────────────────────────────────────


_WHEN = datetime(2026, 5, 22, 14, 30, tzinfo=timezone.utc)


class TestDeriveSessionTitle:
    """derive_session_title builds '<prompt fragment>… · <date>' titles."""

    def test_short_prompt_has_no_ellipsis(self) -> None:
        """A prompt shorter than the char cap appears in full, no ellipsis."""
        title = derive_session_title("Hi there", _WHEN)
        assert title == "Hi there · May 22, 2026"

    def test_long_prompt_truncated_with_ellipsis(self) -> None:
        """A prompt longer than the cap is truncated and gets an ellipsis."""
        title = derive_session_title("What is the capital of France?", _WHEN)
        fragment = "What is the capital of France?"[:SESSION_TITLE_PROMPT_CHARS]
        assert title.startswith(fragment + "…")
        assert " · May 22, 2026" in title

    def test_fragment_length_matches_constant(self) -> None:
        """The prompt fragment is exactly SESSION_TITLE_PROMPT_CHARS long."""
        title = derive_session_title("A" * 50, _WHEN)
        assert title.startswith("A" * SESSION_TITLE_PROMPT_CHARS + "…")

    def test_includes_date(self) -> None:
        """The title carries a human-readable date."""
        title = derive_session_title("anything", _WHEN)
        assert "May 22, 2026" in title

    def test_collapses_whitespace(self) -> None:
        """Newlines and runs of spaces in the prompt are collapsed."""
        title = derive_session_title("  line one\n\n   line two  ", _WHEN)
        assert title == "line one line t… · May 22, 2026"

    def test_empty_prompt_falls_back(self) -> None:
        """An empty / whitespace-only prompt still yields a dated title."""
        assert derive_session_title("", _WHEN) == "Session · May 22, 2026"
        assert derive_session_title("   \n  ", _WHEN) == "Session · May 22, 2026"

    def test_never_exceeds_max_chars(self) -> None:
        """The derived title is always within SESSION_TITLE_MAX_CHARS."""
        title = derive_session_title("z" * 5000, _WHEN)
        assert len(title) <= SESSION_TITLE_MAX_CHARS


# ─────────────────────────────────────────────────────────────────
# set_title_if_empty — auto-title on first prompt
# ─────────────────────────────────────────────────────────────────


class TestSetTitleIfEmpty:
    """set_title_if_empty applies a title only when none is set yet."""

    def test_sets_title_when_empty(self, store: SessionStore) -> None:
        sid = store.create_session()  # empty title
        assert store.set_title_if_empty(sid, "Derived Title") is True
        match = [s for s in store.list_sessions() if s.id == sid]
        assert match[0].title == "Derived Title"

    def test_does_not_clobber_existing_title(self, store: SessionStore) -> None:
        """A session that already has a title is left untouched."""
        sid = store.create_session(title="User Chose This")
        assert store.set_title_if_empty(sid, "Auto Title") is False
        match = [s for s in store.list_sessions() if s.id == sid]
        assert match[0].title == "User Chose This"

    def test_truncates_to_max_chars(self, store: SessionStore) -> None:
        sid = store.create_session()
        store.set_title_if_empty(sid, "y" * 200)
        match = [s for s in store.list_sessions() if s.id == sid]
        assert len(match[0].title) == SESSION_TITLE_MAX_CHARS

    def test_unknown_session_returns_false(self, store: SessionStore) -> None:
        assert store.set_title_if_empty("no-such-session", "Title") is False

    def test_only_fires_once(self, store: SessionStore) -> None:
        """The first call sets the title; a second call is a no-op."""
        sid = store.create_session()
        assert store.set_title_if_empty(sid, "First") is True
        assert store.set_title_if_empty(sid, "Second") is False
        match = [s for s in store.list_sessions() if s.id == sid]
        assert match[0].title == "First"


# ─────────────────────────────────────────────────────────────────
# update_session_title — the /rename command
# ─────────────────────────────────────────────────────────────────


class TestUpdateSessionTitle:
    """update_session_title unconditionally overwrites the title (rename)."""

    def test_overwrites_existing_title(self, store: SessionStore) -> None:
        sid = store.create_session(title="Old Name")
        assert store.update_session_title(sid, "New Name") is True
        match = [s for s in store.list_sessions() if s.id == sid]
        assert match[0].title == "New Name"

    def test_sets_title_when_empty(self, store: SessionStore) -> None:
        sid = store.create_session()
        assert store.update_session_title(sid, "Renamed") is True
        match = [s for s in store.list_sessions() if s.id == sid]
        assert match[0].title == "Renamed"

    def test_truncates_to_max_chars(self, store: SessionStore) -> None:
        sid = store.create_session()
        store.update_session_title(sid, "w" * 200)
        match = [s for s in store.list_sessions() if s.id == sid]
        assert len(match[0].title) == SESSION_TITLE_MAX_CHARS

    def test_unknown_session_returns_false(self, store: SessionStore) -> None:
        assert store.update_session_title("no-such-session", "Title") is False


# ─────────────────────────────────────────────────────────────────
# _backfill_empty_titles — one-time historical data repair
# ─────────────────────────────────────────────────────────────────


class TestBackfillEmptyTitles:
    """_backfill_empty_titles repairs sessions stored with empty titles."""

    def test_backfills_from_first_user_turn(self, store: SessionStore) -> None:
        """An empty-title session gets a title derived from its first prompt."""
        sid = store.create_session()  # empty title (the historical bug)
        store.add_turn(sid, "user", "How do I bake sourdough bread", "N/A", [])

        count = store._backfill_empty_titles()

        assert count == 1
        match = [s for s in store.list_sessions() if s.id == sid]
        assert match[0].title.startswith("How do I bake s…")

    def test_skips_session_with_no_turns(self, store: SessionStore) -> None:
        """A never-used session has no content to name it after — left empty."""
        sid = store.create_session()
        count = store._backfill_empty_titles()
        assert count == 0
        match = [s for s in store.list_sessions() if s.id == sid]
        assert match[0].title == ""

    def test_skips_session_with_only_assistant_turn(self, store: SessionStore) -> None:
        """Defensive: no user turn means nothing to derive a title from."""
        sid = store.create_session()
        store.add_turn(sid, "assistant", "orphan reply", "approved", [])
        count = store._backfill_empty_titles()
        assert count == 0

    def test_does_not_touch_nonempty_titles(self, store: SessionStore) -> None:
        """Sessions that already have a title are never modified."""
        sid = store.create_session(title="Keep This Title")
        store.add_turn(sid, "user", "some prompt text here", "N/A", [])
        count = store._backfill_empty_titles()
        assert count == 0
        match = [s for s in store.list_sessions() if s.id == sid]
        assert match[0].title == "Keep This Title"

    def test_is_idempotent(self, store: SessionStore) -> None:
        """A second backfill pass finds nothing left to repair."""
        sid = store.create_session()
        store.add_turn(sid, "user", "first prompt", "N/A", [])
        assert store._backfill_empty_titles() == 1
        assert store._backfill_empty_titles() == 0

    def test_runs_automatically_on_init(self, tmp_path: Path) -> None:
        """Reopening a DB with empty-title sessions backfills them at init."""
        db_path = str(tmp_path / "sessions.db")
        store1 = SessionStore(db_path)
        try:
            sid = store1.create_session()  # empty title
            store1.add_turn(sid, "user", "What does this file say", "N/A", [])
        finally:
            store1.close()

        # Reopen — __init__ runs the backfill.
        store2 = SessionStore(db_path)
        try:
            match = [s for s in store2.list_sessions() if s.id == sid]
            assert match[0].title.startswith("What does this …")
        finally:
            store2.close()


