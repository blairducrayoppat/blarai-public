"""Locks for the coordinator stall-comment seen-set state (#844 C2, ADR-039 §2.8/§2.13).

Proves the plaintext-metadata storage posture the LA affirmed 2026-07-13: atomic
write, owner-DACL hardening WIRED (fail-safe), fail-soft read (missing/corrupt ->
empty set), round-trip, and the non-string-fingerprint filter. The EPISODE-pruning
behavior lives in the cycle (``test_coord_stall_monitor.py``); this file proves the
STATE primitive underneath it.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from shared.fleet import coord_stall_state as css
from shared.fleet.dispatch import FleetDispatchConfig

_NOW = datetime(2026, 7, 13, 12, 0, 0, tzinfo=timezone.utc)


def _config(tmp_path: Path) -> FleetDispatchConfig:
    return FleetDispatchConfig(
        scripts_dir=tmp_path / "scripts",
        queue_path=tmp_path / "state" / "fleet-queue.json",
        runs_dir=tmp_path / "state" / "fleet-runs",
        projects_dir=tmp_path / "projects",
    )


# ---------------------------------------------------------------------------
# path derivation (sibling of fleet-swap under the same state root)
# ---------------------------------------------------------------------------


def test_default_path_is_under_coordinator_state_dir(tmp_path):
    cfg = _config(tmp_path)
    path = css.default_stall_seen_path(cfg)
    assert path.name == "stall_seen.json"
    assert path.parent == css.coordinator_state_dir(cfg)
    assert path.parent.name == "coordinator"


# ---------------------------------------------------------------------------
# read — fail-soft to the EMPTY set on ANY trouble (the "<=1 dup comment" cost)
# ---------------------------------------------------------------------------


def test_read_missing_file_is_empty_state(tmp_path):
    state = css.read_seen_state(tmp_path / "nope.json")
    assert state.fingerprints == frozenset()
    assert state.updated_at == ""


def test_read_malformed_json_is_empty_state(tmp_path):
    p = tmp_path / "s.json"
    p.write_text("{not json", encoding="utf-8")
    assert css.read_seen_state(p).fingerprints == frozenset()


def test_read_non_dict_payload_is_empty_state(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps(["a", "b"]), encoding="utf-8")
    assert css.read_seen_state(p).fingerprints == frozenset()


def test_read_non_list_fingerprints_is_empty_state(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"fingerprints": "Standard:1"}), encoding="utf-8")
    assert css.read_seen_state(p).fingerprints == frozenset()


def test_read_filters_non_string_and_empty_fingerprints(tmp_path):
    """A partially-corrupt file can never inject a non-string fingerprint."""
    p = tmp_path / "s.json"
    p.write_text(
        json.dumps({"fingerprints": ["Standard:1", "", 42, None, "Expedite:2"]}),
        encoding="utf-8",
    )
    assert css.read_seen_state(p).fingerprints == frozenset(
        {"Standard:1", "Expedite:2"}
    )


def test_read_non_string_updated_at_coerces_to_blank(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"fingerprints": [], "updated_at": 123}), encoding="utf-8")
    assert css.read_seen_state(p).updated_at == ""


# ---------------------------------------------------------------------------
# write — atomic, plaintext, owner-DACL wired, round-trip
# ---------------------------------------------------------------------------


def test_write_then_read_round_trip(tmp_path):
    p = tmp_path / "coord" / "stall_seen.json"
    state = css.StallSeenState(
        fingerprints=frozenset({"Standard:4", "Expedite:9"}),
        updated_at=_NOW.isoformat(),
    )
    css.write_seen_state(state, path=p)
    back = css.read_seen_state(p)
    assert back.fingerprints == state.fingerprints
    assert back.updated_at == _NOW.isoformat()


def test_write_creates_parent_dirs(tmp_path):
    p = tmp_path / "a" / "b" / "c" / "stall_seen.json"
    css.write_seen_state(
        css.StallSeenState(frozenset({"Standard:1"}), _NOW.isoformat()), path=p
    )
    assert p.is_file()


def test_write_is_atomic_no_temp_left(tmp_path):
    p = tmp_path / "stall_seen.json"
    css.write_seen_state(css.StallSeenState(frozenset({"Standard:1"}), ""), path=p)
    assert not (tmp_path / "stall_seen.json.tmp").exists()


def test_write_payload_is_sorted_plaintext(tmp_path):
    """The payload is PLAINTEXT (not born-encrypted) and deterministically sorted
    — the affirmed non-content-bearing posture, verifiable on disk."""
    p = tmp_path / "stall_seen.json"
    css.write_seen_state(
        css.StallSeenState(frozenset({"Expedite:9", "Standard:4"}), _NOW.isoformat()),
        path=p,
    )
    raw = json.loads(p.read_text(encoding="utf-8"))
    assert raw["fingerprints"] == ["Expedite:9", "Standard:4"]
    assert raw["updated_at"] == _NOW.isoformat()


def test_write_wires_owner_only_dacl(tmp_path, monkeypatch):
    """The owner-DACL hardening is applied to the written path (defense-in-depth).
    ``ensure_owner_only_dacl`` is itself fail-safe; here we prove it is WIRED."""
    calls: list[Path] = []
    monkeypatch.setattr(css, "ensure_owner_only_dacl", lambda p: calls.append(p))
    p = tmp_path / "stall_seen.json"
    css.write_seen_state(css.StallSeenState(frozenset({"Standard:1"}), ""), path=p)
    assert calls == [p]


def test_empty_state_round_trips(tmp_path):
    p = tmp_path / "stall_seen.json"
    css.write_seen_state(css.StallSeenState(), path=p)
    assert css.read_seen_state(p).fingerprints == frozenset()
