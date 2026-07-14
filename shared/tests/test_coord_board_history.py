"""Locks for the bucket-transition record + observed age basis (#845 C3, ADR-039 §2.14.2).

The C3 design (`docs/research/c3-heartbeat-design-2026-07.md` §4) settled age =
entered-Ready, first-observed-in-bucket. These locks pin: episode semantics
(keep / re-stamp / prune / fresh-return), the MISSING-vs-CORRUPT read split,
the created fallback for unobserved cards, the composer's observed-basis
switch, the corrupt-record surfaced fallback (never silent — §2.14.4), and the
dormancy contract (no ``board_history`` supplied → byte-identical pre-C3
behavior)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from shared.fleet import coord_board_history as bh
from shared.fleet import vikunja_bridge as vb
from shared.fleet import work_state as ws
from shared.fleet.dispatch import FleetDispatchConfig
from shared.tests.test_vikunja_bridge import FakeVikunja

_NOW = datetime(2026, 7, 14, 12, 0, 0, tzinfo=timezone.utc)
_EARLIER = datetime(2026, 7, 13, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _loopback_env(monkeypatch):
    monkeypatch.setenv("VIKUNJA_URL", "http://localhost:3456")
    monkeypatch.setenv("VIKUNJA_USER", "blarai")
    monkeypatch.setenv("VIKUNJA_PASS", "test-pass")


def _config(tmp_path: Path) -> FleetDispatchConfig:
    return FleetDispatchConfig(
        scripts_dir=tmp_path / "scripts",
        queue_path=tmp_path / "state" / "fleet-queue.json",
        runs_dir=tmp_path / "state" / "fleet-runs",
        projects_dir=tmp_path / "projects",
    )


# ---------------------------------------------------------------------------
# read_board_history — MISSING vs CORRUPT (the §2.14.4 split)
# ---------------------------------------------------------------------------


def test_read_missing_file_is_empty_not_corrupt(tmp_path):
    result = bh.read_board_history(tmp_path / "absent.json")
    assert result.corrupt is False
    assert result.state.entries == {}


def test_read_unparseable_json_is_corrupt(tmp_path):
    p = tmp_path / "board_history.json"
    p.write_text("{not json", encoding="utf-8")
    result = bh.read_board_history(p)
    assert result.corrupt is True
    assert result.error
    assert result.state.entries == {}


def test_read_wrong_shape_is_corrupt(tmp_path):
    p = tmp_path / "board_history.json"
    p.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert bh.read_board_history(p).corrupt is True
    p.write_text(json.dumps({"entries": "nope"}), encoding="utf-8")
    assert bh.read_board_history(p).corrupt is True


def test_read_validates_entries_element_wise(tmp_path):
    p = tmp_path / "board_history.json"
    p.write_text(
        json.dumps(
            {
                "entries": {
                    "7:1001": {"bucket": "Ready", "first_seen": "2026-07-13T12:00:00+00:00"},
                    "7:1002": {"bucket": "", "first_seen": "2026-07-13T12:00:00+00:00"},
                    "7:1003": {"bucket": "Ready"},
                    "7:1004": "not-a-dict",
                    "": {"bucket": "Ready", "first_seen": "x"},
                },
                "updated_at": "2026-07-13T12:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    result = bh.read_board_history(p)
    assert result.corrupt is False
    assert set(result.state.entries) == {"7:1001"}
    assert result.state.entries["7:1001"].bucket == "Ready"
    assert result.state.updated_at == "2026-07-13T12:00:00+00:00"


def test_write_read_round_trip(tmp_path):
    p = tmp_path / "nested" / "board_history.json"
    state = bh.BoardHistoryState(
        entries={
            "7:1001": bh.ObservedBucketEntry(bucket="Ready", first_seen=_EARLIER.isoformat()),
            "9:2001": bh.ObservedBucketEntry(bucket="In Progress", first_seen=_NOW.isoformat()),
        },
        updated_at=_NOW.isoformat(),
    )
    bh.write_board_history(state, path=p)
    result = bh.read_board_history(p)
    assert result.corrupt is False
    assert result.state == state
    assert not p.with_suffix(p.suffix + ".tmp").exists()  # atomic replace, no residue


# ---------------------------------------------------------------------------
# observe_board — episode semantics
# ---------------------------------------------------------------------------


def test_first_observation_stamps_now():
    state = bh.observe_board(
        bh.BoardHistoryState(), project_id=7, membership={1001: "Ready"}, now=_NOW
    )
    assert state.entries["7:1001"] == bh.ObservedBucketEntry(
        bucket="Ready", first_seen=_NOW.isoformat()
    )
    assert state.updated_at == _NOW.isoformat()


def test_same_bucket_keeps_first_seen():
    prior = bh.observe_board(
        bh.BoardHistoryState(), project_id=7, membership={1001: "Ready"}, now=_EARLIER
    )
    later = bh.observe_board(prior, project_id=7, membership={1001: "Ready"}, now=_NOW)
    assert later.entries["7:1001"].first_seen == _EARLIER.isoformat()


def test_bucket_move_restamps():
    prior = bh.observe_board(
        bh.BoardHistoryState(), project_id=7, membership={1001: "Ready"}, now=_EARLIER
    )
    moved = bh.observe_board(
        prior, project_id=7, membership={1001: "In Progress"}, now=_NOW
    )
    assert moved.entries["7:1001"] == bh.ObservedBucketEntry(
        bucket="In Progress", first_seen=_NOW.isoformat()
    )


def test_departed_card_pruned_and_return_is_fresh_episode():
    prior = bh.observe_board(
        bh.BoardHistoryState(), project_id=7, membership={1001: "Ready"}, now=_EARLIER
    )
    gone = bh.observe_board(prior, project_id=7, membership={}, now=_EARLIER)
    assert "7:1001" not in gone.entries
    returned = bh.observe_board(gone, project_id=7, membership={1001: "Ready"}, now=_NOW)
    assert returned.entries["7:1001"].first_seen == _NOW.isoformat()  # fresh, not credited


def test_other_projects_untouched():
    prior = bh.observe_board(
        bh.BoardHistoryState(), project_id=9, membership={2001: "Ready"}, now=_EARLIER
    )
    after = bh.observe_board(prior, project_id=7, membership={1001: "Ready"}, now=_NOW)
    assert after.entries["9:2001"].first_seen == _EARLIER.isoformat()
    assert after.entries["7:1001"].first_seen == _NOW.isoformat()


def test_observe_is_deterministic():
    a = bh.observe_board(
        bh.BoardHistoryState(), project_id=7, membership={1: "A", 2: "B"}, now=_NOW
    )
    b = bh.observe_board(
        bh.BoardHistoryState(), project_id=7, membership={2: "B", 1: "A"}, now=_NOW
    )
    assert a == b


# ---------------------------------------------------------------------------
# extract_bucket_membership — over board_state's enriched buckets
# ---------------------------------------------------------------------------


def test_extract_membership_skips_malformed_and_keeps_first():
    buckets = [
        {"title": "Ready", "tasks": [{"id": 1}, {"id": "bad"}, "junk", {"id": 2}]},
        {"title": "", "tasks": [{"id": 3}]},          # empty title -> skipped
        {"title": "In Progress", "tasks": [{"id": 1}]},  # duplicate -> first wins
        "not-a-bucket",
        {"title": "No tasks key"},
    ]
    assert bh.extract_bucket_membership(buckets) == {1: "Ready", 2: "Ready"}


# ---------------------------------------------------------------------------
# inject_observed_basis — observed where recorded, created fallback otherwise
# ---------------------------------------------------------------------------


def test_inject_uses_observed_else_created_and_never_mutates():
    state = bh.observe_board(
        bh.BoardHistoryState(), project_id=7, membership={1001: "Ready"}, now=_EARLIER
    )
    tasks = [
        {"id": 1001, "created": "2026-07-01T00:00:00Z"},   # observed -> first_seen
        {"id": 1002, "created": "2026-07-02T00:00:00Z"},   # unobserved -> created
        {"id": "bad", "created": "2026-07-03T00:00:00Z"},  # malformed id -> created
    ]
    injected = bh.inject_observed_basis(tasks, state=state, project_id=7)
    assert injected[0][bh.OBSERVED_AGE_FIELD] == _EARLIER.isoformat()
    assert injected[1][bh.OBSERVED_AGE_FIELD] == "2026-07-02T00:00:00Z"
    assert injected[2][bh.OBSERVED_AGE_FIELD] == "2026-07-03T00:00:00Z"
    assert all(bh.OBSERVED_AGE_FIELD not in t for t in tasks)  # copies, not mutation


# ---------------------------------------------------------------------------
# work_state integration — the observed-basis switch + the dormancy locks
# ---------------------------------------------------------------------------


def _seed_project(fake: FakeVikunja) -> int:
    fake.seed_view(7, 2, title="Board", kind="kanban")
    fake.seed_bucket(7, 2, 10, title="Ready")
    return fake.seed_task(
        7, title="old-card", done=False, bucket_id=10, created="2026-06-01T00:00:00Z"
    )


def test_project_ages_compute_on_observed_basis_when_history_supplied():
    """A card created six weeks ago but first OBSERVED in Ready yesterday must
    age from the observation, not from creation (the settled §2.14.2 meaning)."""
    fake = FakeVikunja()
    tid = _seed_project(fake)
    history = bh.observe_board(
        bh.BoardHistoryState(), project_id=7, membership={tid: "Ready"}, now=_EARLIER
    )
    pw = ws.read_project_work_state(
        "Coder Jobs", 7, now=_NOW, board_history=history, transport=fake
    )
    assert pw.flow is not None
    assert pw.flow.age_basis_field == bh.OBSERVED_AGE_FIELD
    assert pw.flow.ages[0].age_seconds == pytest.approx(
        (_NOW - _EARLIER).total_seconds()
    )


def test_project_unobserved_card_falls_back_to_created_age():
    fake = FakeVikunja()
    _seed_project(fake)
    pw = ws.read_project_work_state(
        "Coder Jobs", 7, now=_NOW, board_history=bh.BoardHistoryState(), transport=fake
    )
    assert pw.flow is not None
    assert pw.flow.age_basis_field == bh.OBSERVED_AGE_FIELD
    created = datetime(2026, 6, 1, tzinfo=timezone.utc)
    assert pw.flow.ages[0].age_seconds == pytest.approx(
        (_NOW - created).total_seconds()
    )


def test_project_without_history_is_unchanged_created_basis():
    """The dormancy lock: no ``board_history`` -> the pre-C3 read, byte-identical
    — same basis label AND the same computed age values."""
    fake = FakeVikunja()
    _seed_project(fake)
    pw = ws.read_project_work_state("Coder Jobs", 7, now=_NOW, transport=fake)
    assert pw.flow is not None
    assert pw.flow.age_basis_field == "created"
    created = datetime(2026, 6, 1, tzinfo=timezone.utc)
    assert pw.flow.ages[0].age_seconds == pytest.approx(
        (_NOW - created).total_seconds()
    )


def test_read_drops_tampered_key_shapes(tmp_path):
    """Anchored key validation (review finding 3): only ``{int}:{int}`` keys
    survive a read — a tampered/drifted shape is dropped, never carried."""
    p = tmp_path / "board_history.json"
    p.write_text(
        json.dumps(
            {
                "entries": {
                    "7:1001": {"bucket": "Ready", "first_seen": "2026-07-13T12:00:00+00:00"},
                    "abc:def": {"bucket": "Ready", "first_seen": "2026-07-13T12:00:00+00:00"},
                    "7:1001:extra": {"bucket": "Ready", "first_seen": "2026-07-13T12:00:00+00:00"},
                    "71001": {"bucket": "Ready", "first_seen": "2026-07-13T12:00:00+00:00"},
                },
                "updated_at": "",
            }
        ),
        encoding="utf-8",
    )
    result = bh.read_board_history(p)
    assert result.corrupt is False
    assert set(result.state.entries) == {"7:1001"}


def test_compose_with_healthy_record_switches_basis_and_surfaces_liveness(tmp_path):
    fake = FakeVikunja()
    tid = _seed_project(fake)
    history = bh.observe_board(
        bh.BoardHistoryState(), project_id=7, membership={tid: "Ready"}, now=_EARLIER
    )
    p = tmp_path / "board_history.json"
    bh.write_board_history(history, path=p)

    snap = ws.compose_work_state(
        fleet_config=_config(tmp_path),
        coordinator_projects={"Coder Jobs": 7},
        now=_NOW,
        board_history_path=p,
        vikunja_transport=fake,
    )
    assert snap.age_basis_field == bh.OBSERVED_AGE_FIELD
    liveness = {s.name: s.status for s in snap.substrate}
    assert liveness["board_history"] == vb.ReadStatus.OK
    assert snap.projects[0].flow is not None
    assert snap.projects[0].flow.age_basis_field == bh.OBSERVED_AGE_FIELD


def test_compose_with_corrupt_record_falls_back_surfaced_never_silent(tmp_path):
    """The §2.14.4 lock: a corrupt record -> created basis + an UNREACHABLE
    board_history substrate entry. Neither silent trust nor silent fallback."""
    fake = FakeVikunja()
    _seed_project(fake)
    p = tmp_path / "board_history.json"
    p.write_text("{torn", encoding="utf-8")

    snap = ws.compose_work_state(
        fleet_config=_config(tmp_path),
        coordinator_projects={"Coder Jobs": 7},
        now=_NOW,
        board_history_path=p,
        vikunja_transport=fake,
    )
    assert snap.age_basis_field == "created"
    liveness = {s.name: s.status for s in snap.substrate}
    assert liveness["board_history"] == vb.ReadStatus.UNREACHABLE
    assert snap.projects[0].flow is not None
    assert snap.projects[0].flow.age_basis_field == "created"


def test_compose_missing_record_is_cold_start_observed_basis(tmp_path):
    """MISSING is not CORRUPT: the observed basis engages over an empty record
    (every card on its created fallback) and liveness reads EMPTY."""
    fake = FakeVikunja()
    _seed_project(fake)
    snap = ws.compose_work_state(
        fleet_config=_config(tmp_path),
        coordinator_projects={"Coder Jobs": 7},
        now=_NOW,
        board_history_path=tmp_path / "absent.json",
        vikunja_transport=fake,
    )
    assert snap.age_basis_field == bh.OBSERVED_AGE_FIELD
    liveness = {s.name: s.status for s in snap.substrate}
    assert liveness["board_history"] == vb.ReadStatus.EMPTY
    # The design's ordering lock (§2 steps 3-4): compose READS the record and
    # never writes it — the diff-and-write is the cycle's job, after compose.
    assert not (tmp_path / "absent.json").exists()


def test_compose_without_path_has_no_board_history_substrate(tmp_path):
    """The dormancy lock at the compose seam: no path -> no liveness entry, the
    created default on the snapshot — byte-identical to the pre-C3 compose."""
    snap = ws.compose_work_state(
        fleet_config=_config(tmp_path),
        coordinator_projects={},
        now=_NOW,
        vikunja_transport=FakeVikunja(),
    )
    assert snap.age_basis_field == "created"
    assert all(s.name != "board_history" for s in snap.substrate)


def test_default_path_lives_in_coordinator_state_dir(tmp_path):
    cfg = _config(tmp_path)
    p = bh.default_board_history_path(cfg)
    assert p.name == "board_history.json"
    assert p.parent.name == "coordinator"
