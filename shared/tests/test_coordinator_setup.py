"""Locks for the OPERATOR-RUN Coordinator Kanban substrate setup migration
(#843, ADR-039 §2.12.11 / §2.9's paired tenet).

Proves: idempotent discover-or-create (a re-run creates nothing new),
fail-soft per-step reporting, and the orphan-flagging half never removes
anything — only reports. Offline: FakeVikunja stands in for the transport.
"""

from __future__ import annotations

import pytest

from shared.fleet import vikunja_bridge as vb
from shared.tests.test_vikunja_bridge import FakeVikunja
from tools.dispatch_harness import coordinator_setup as cs


@pytest.fixture(autouse=True)
def _loopback_env(monkeypatch):
    monkeypatch.setenv("VIKUNJA_URL", "http://localhost:3456")
    monkeypatch.setenv("VIKUNJA_USER", "blarai")
    monkeypatch.setenv("VIKUNJA_PASS", "test-pass")


# ---------------------------------------------------------------------------
# run_setup — idempotent discover-or-create
# ---------------------------------------------------------------------------


def test_run_setup_creates_every_bucket_and_label_on_a_fresh_project():
    fake = FakeVikunja()
    results = cs.run_setup(7, 2, transport=fake)

    for title in cs.KANBAN_BUCKETS:
        assert results[f"bucket:{title}"] is not None
    for title, _color in cs.SETUP_LABELS:
        assert results[f"label:{title}"] is not None
    # #887: the provenance label (Battery/Test) is provisioned alongside the
    # class-of-service labels — the runtime resolves it by name.
    assert results["label:Battery/Test"] is not None

    assert len(fake._buckets[(7, 2)]) == len(cs.KANBAN_BUCKETS)
    assert len(fake._labels) == len(cs.SETUP_LABELS)


def test_run_setup_is_idempotent_across_two_runs():
    fake = FakeVikunja()
    first = cs.run_setup(7, 2, transport=fake)
    second = cs.run_setup(7, 2, transport=fake)

    assert first == second  # SAME ids both times — nothing re-created
    assert len(fake._buckets[(7, 2)]) == len(cs.KANBAN_BUCKETS)  # not doubled
    assert len(fake._labels) == len(cs.SETUP_LABELS)  # not doubled


def test_run_setup_only_creates_the_missing_items():
    """A PARTIALLY-migrated project (some buckets/labels already exist from
    a prior manual setup) must have ONLY the missing items created — the
    existing ones are found and reused, not duplicated."""
    fake = FakeVikunja()
    fake.seed_bucket(7, 2, 999, title="Backlog")  # pre-existing
    fake.seed_label(888, title="Expedite", hex_color="e91e63")  # pre-existing

    results = cs.run_setup(7, 2, transport=fake)

    assert results["bucket:Backlog"] == 999  # found, not re-created
    assert results["label:Expedite"] == 888  # found, not re-created
    assert len(fake._buckets[(7, 2)]) == len(cs.KANBAN_BUCKETS)  # still exactly 5
    assert len(fake._labels) == len(cs.SETUP_LABELS)  # no dup of the pre-existing


def test_run_setup_reports_failure_per_step_without_crashing():
    fake = FakeVikunja(fail=True)
    results = cs.run_setup(7, 2, transport=fake)
    assert all(v is None for v in results.values())
    assert set(results.keys()) == {
        *(f"bucket:{t}" for t in cs.KANBAN_BUCKETS),
        *(f"label:{t}" for t, _ in cs.SETUP_LABELS),
    }


# ---------------------------------------------------------------------------
# find_orphans — the paired tenet's flag-only, never-remove half
# ---------------------------------------------------------------------------


def test_find_orphans_flags_unrecognized_bucket_and_label():
    fake = FakeVikunja()
    cs.run_setup(7, 2, transport=fake)  # the known 5 buckets + 4 labels
    fake.seed_bucket(7, 2, 777, title="Someday/Maybe")  # NOT in KANBAN_BUCKETS
    fake.seed_label(666, title="Wontfix", hex_color="000000")  # NOT in CLASSES_OF_SERVICE

    orphans = cs.find_orphans(7, 2, transport=fake)
    assert orphans["buckets"] == ["Someday/Maybe"]
    assert orphans["labels"] == ["Wontfix"]
    # #887: Battery/Test is a KNOWN provenance label — never flagged as an orphan.
    assert cs.PROVENANCE_LABELS[0][0] not in orphans["labels"]

    # Never removed — orphan-flagging is report-only.
    assert len(fake._buckets[(7, 2)]) == len(cs.KANBAN_BUCKETS) + 1
    assert len(fake._labels) == len(cs.SETUP_LABELS) + 1


def test_find_orphans_empty_on_a_clean_migrated_project():
    fake = FakeVikunja()
    cs.run_setup(7, 2, transport=fake)
    orphans = cs.find_orphans(7, 2, transport=fake)
    assert orphans == {"buckets": [], "labels": []}


def test_find_orphans_degrades_to_empty_on_unreachable_never_crashes():
    fake = FakeVikunja(fail=True)
    orphans = cs.find_orphans(7, 2, transport=fake)
    assert orphans == {"buckets": [], "labels": []}


# ---------------------------------------------------------------------------
# CLI entrypoint — exit code reflects step failures
# ---------------------------------------------------------------------------


def test_main_returns_zero_on_full_success(monkeypatch, capsys):
    fake = FakeVikunja()
    monkeypatch.setattr(vb, "_default_transport", lambda: fake)
    rc = cs._main(["--project-id", "7", "--view-id", "2"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "FAILED" not in out


def test_main_returns_nonzero_when_a_step_fails(monkeypatch, capsys):
    fake = FakeVikunja(fail=True)
    monkeypatch.setattr(vb, "_default_transport", lambda: fake)
    rc = cs._main(["--project-id", "7", "--view-id", "2"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "FAILED" in out
