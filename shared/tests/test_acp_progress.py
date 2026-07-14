"""Locks for the durable ACP progress contract + the coordinator's operational ruler
(#844 C2, ADR-039 §2.13 item 6).

The write side is FAIL-SOFT (a coder run must never be affected by a progress-write
failure); the read side is fail-soft (a dead/absent/corrupt artifact never crashes
the coordinator); the ruler's SOFT ``quiet`` signal requires an ACTIVE run (a
finished run's stale last-event age is never a stall).
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from shared.fleet import acp_progress as ap

_NOW = datetime(2026, 7, 13, 12, 0, 0, tzinfo=timezone.utc)

_BASE = ap.AcpProgressSnapshot(
    run_id="R1", last_event_at=_NOW.isoformat(), updated_at=_NOW.isoformat(),
    event_count=5, steps=3, edits=1, failed_tool_calls=0, tokens_in=10, tokens_out=20,
)


def _snap(**kw) -> ap.AcpProgressSnapshot:
    return replace(_BASE, **kw)


# ---------------------------------------------------------------------------
# snapshot JSON round-trip + defensive parse
# ---------------------------------------------------------------------------


def test_snapshot_json_round_trip():
    s = _snap()
    assert ap.snapshot_from_json(s.to_json()) == s


def test_snapshot_from_malformed_json_is_none():
    assert ap.snapshot_from_json("{not json") is None


def test_snapshot_from_non_dict_is_none():
    assert ap.snapshot_from_json(json.dumps([1, 2])) is None


def test_snapshot_coerces_wrong_typed_fields():
    raw = json.dumps({"run_id": 5, "steps": "nan", "edits": None, "event_count": 7})
    s = ap.snapshot_from_json(raw)
    assert s is not None
    assert s.run_id == ""       # non-str -> ""
    assert s.steps == 0         # unparseable int -> 0
    assert s.edits == 0
    assert s.event_count == 7   # valid int preserved


# ---------------------------------------------------------------------------
# write/read — plaintext, atomic, fail-soft
# ---------------------------------------------------------------------------


def test_write_then_read_round_trip(tmp_path):
    s = _snap()
    p = tmp_path / "run1" / "acp-progress.json"
    assert ap.write_acp_progress(s, path=p) is True
    assert ap.read_acp_progress(p) == s


def test_write_is_plaintext_and_atomic(tmp_path):
    p = tmp_path / "acp-progress.json"
    ap.write_acp_progress(_snap(run_id="RX"), path=p)
    raw = json.loads(p.read_text(encoding="utf-8"))
    assert raw["run_id"] == "RX"                              # plaintext, not encrypted
    assert not (tmp_path / "acp-progress.json.tmp").exists()  # temp consumed by os.replace


def test_write_fail_soft_returns_false_never_raises(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")               # a FILE where a dir is needed
    p = blocker / "sub" / "acp-progress.json"
    assert ap.write_acp_progress(_snap(), path=p) is False  # no raise, just False


def test_read_missing_is_none(tmp_path):
    assert ap.read_acp_progress(tmp_path / "nope.json") is None


def test_read_corrupt_is_none(tmp_path):
    p = tmp_path / "acp-progress.json"
    p.write_text("{garbage", encoding="utf-8")
    assert ap.read_acp_progress(p) is None


# ---------------------------------------------------------------------------
# the operational ruler
# ---------------------------------------------------------------------------


def test_assess_active_recent_is_not_quiet():
    s = _snap(last_event_at=(_NOW - timedelta(seconds=30)).isoformat())
    a = ap.assess_acp_progress(s, now=_NOW, run_active=True)
    assert a.last_event_age_s == 30
    assert a.quiet is False
    assert "active" in a.summary


def test_assess_active_stale_is_quiet():
    s = _snap(last_event_at=(_NOW - timedelta(seconds=400)).isoformat())
    a = ap.assess_acp_progress(s, now=_NOW, run_active=True)  # 400 >= 300 default
    assert a.quiet is True
    assert "QUIET" in a.summary


def test_assess_finished_run_is_never_quiet():
    """A finished run (SUMMARY present -> run_active False) with a stale last event is
    NOT a stall — the quiet signal requires an ACTIVE run."""
    s = _snap(last_event_at=(_NOW - timedelta(seconds=9999)).isoformat())
    a = ap.assess_acp_progress(s, now=_NOW, run_active=False)
    assert a.quiet is False
    assert "finished" in a.summary


def test_assess_unparseable_timestamp_age_none_not_quiet():
    s = _snap(last_event_at="not-a-date")
    a = ap.assess_acp_progress(s, now=_NOW, run_active=True)
    assert a.last_event_age_s is None
    assert a.quiet is False


def test_assess_custom_threshold():
    s = _snap(last_event_at=(_NOW - timedelta(seconds=100)).isoformat())
    a = ap.assess_acp_progress(s, now=_NOW, run_active=True, quiet_threshold_s=60.0)
    assert a.quiet is True  # 100 >= 60


def test_default_soft_threshold_is_half_the_hard_kill_window():
    """Documents the relationship the doctrine relies on: SOFT surfacing at 300 s, the
    fleet's HARD idle-kill at 600 s — the operator sees 'quiet' before the kill."""
    assert ap.DEFAULT_ACP_QUIET_THRESHOLD_S == 300.0
