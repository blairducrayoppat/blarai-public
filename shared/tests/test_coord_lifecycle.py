"""Tests for the C2 deterministic lifecycle decision core (#844).

Fixture-only, fully offline — no Vikunja, no network, no live clock (every
``now`` is supplied). Mirrors the C1/#848 test style: adversarial where a
control must hold (a forged "done" must not reach Done; a governed-core target
must be refused through the DoR gate), exhaustive on the fail-soft paths.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import shared.coordinator.config as sgconfig
from shared.fleet import coord_lifecycle as cl

# ---------------------------------------------------------------------------
# helpers / fixtures
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 7, 12, 18, 0, 0, tzinfo=timezone.utc)


def _task(
    task_id: int,
    *,
    labels: "list[str] | None" = None,
    description: str = "acceptance: it works",
    created: "datetime | None" = None,
    title: str = "t",
) -> dict:
    """A minimal Vikunja-shaped task dict for the decision functions."""
    out: dict = {"id": task_id, "title": title, "description": description}
    if labels is not None:
        out["labels"] = [{"id": i, "title": t} for i, t in enumerate(labels)]
    if created is not None:
        out["created"] = created.astimezone(timezone.utc).isoformat()
    return out


def _make_governed_repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "CLAUDE.md").write_text("governed", encoding="utf-8")
    (root / "docs").mkdir(exist_ok=True)
    (root / "docs" / "DECISION_REGISTER.md").write_text("g", encoding="utf-8")
    (root / "shared" / "fleet").mkdir(parents=True, exist_ok=True)
    (root / "shared" / "fleet" / "dispatch.py").write_text("g", encoding="utf-8")
    return root


@pytest.fixture()
def topology(tmp_path: Path):
    """(repo governed-core, projects workspace, roots) — mirrors the #848 tests."""
    repo = _make_governed_repo(tmp_path / "blarai")
    projects = tmp_path / "projects"
    projects.mkdir()
    (projects / "myapp").mkdir()
    roots = sgconfig.GovernedCoreRoots(repo_root=repo)
    return repo, projects, roots


# ---------------------------------------------------------------------------
# class-of-service classification
# ---------------------------------------------------------------------------


class TestClassifyServiceClass:
    def test_each_class_recognized(self) -> None:
        for sc in cl.ServiceClass:
            assert cl.classify_service_class(_task(1, labels=[sc.value])) is sc

    def test_no_label_defaults_to_standard(self) -> None:
        assert cl.classify_service_class(_task(1)) is cl.ServiceClass.STANDARD
        assert cl.DEFAULT_SERVICE_CLASS is cl.ServiceClass.STANDARD

    def test_null_labels_field_is_fail_soft(self) -> None:
        # Vikunja renders an unlabeled task's labels as null.
        assert (
            cl.classify_service_class({"id": 1, "labels": None})
            is cl.ServiceClass.STANDARD
        )

    def test_highest_priority_label_wins(self) -> None:
        # Expedite + Standard together -> Expedite (declaration-order priority).
        t = _task(1, labels=["Standard", "Expedite"])
        assert cl.classify_service_class(t) is cl.ServiceClass.EXPEDITE
        # Fixed-date beats Standard/Intangible.
        t2 = _task(2, labels=["Intangible", "Fixed-date", "Standard"])
        assert cl.classify_service_class(t2) is cl.ServiceClass.FIXED_DATE

    def test_unrelated_labels_ignored(self) -> None:
        assert (
            cl.classify_service_class(_task(1, labels=["Security", "Testing"]))
            is cl.ServiceClass.STANDARD
        )

    def test_pull_rank_matches_declaration_order(self) -> None:
        assert cl.ServiceClass.EXPEDITE.pull_rank == 0
        assert cl.ServiceClass.INTANGIBLE.pull_rank == 3
        ranks = [sc.pull_rank for sc in cl.ServiceClass]
        assert ranks == sorted(ranks)


# ---------------------------------------------------------------------------
# board movement — the "forged done" lock
# ---------------------------------------------------------------------------


class TestResolveBoardTransition:
    def test_dispatch_started_to_in_progress(self) -> None:
        tr = cl.resolve_board_transition(dispatch_started=True)
        assert tr is not None and tr.to_bucket == cl.BUCKET_IN_PROGRESS

    def test_green_and_merged_to_done(self) -> None:
        tr = cl.resolve_board_transition(oracle_passed=True, merged=True)
        assert tr is not None and tr.to_bucket == cl.BUCKET_DONE

    def test_parked_to_ready(self) -> None:
        tr = cl.resolve_board_transition(parked=True)
        assert tr is not None and tr.to_bucket == cl.BUCKET_READY

    def test_nothing_is_no_transition(self) -> None:
        assert cl.resolve_board_transition() is None

    def test_merged_without_oracle_never_done(self) -> None:
        # The forged/premature-done lock: merged but no oracle pass -> NOT Done.
        tr = cl.resolve_board_transition(
            dispatch_started=True, oracle_passed=False, merged=True
        )
        assert tr is not None and tr.to_bucket == cl.BUCKET_IN_PROGRESS
        assert tr.to_bucket != cl.BUCKET_DONE

    def test_oracle_without_merge_never_done(self) -> None:
        tr = cl.resolve_board_transition(
            dispatch_started=True, oracle_passed=True, merged=False
        )
        assert tr is not None and tr.to_bucket == cl.BUCKET_IN_PROGRESS

    def test_done_precedence_over_parked_and_started(self) -> None:
        tr = cl.resolve_board_transition(
            dispatch_started=True, oracle_passed=True, merged=True, parked=True
        )
        assert tr is not None and tr.to_bucket == cl.BUCKET_DONE

    def test_parked_precedence_over_started(self) -> None:
        tr = cl.resolve_board_transition(dispatch_started=True, parked=True)
        assert tr is not None and tr.to_bucket == cl.BUCKET_READY


# ---------------------------------------------------------------------------
# Definition of Ready
# ---------------------------------------------------------------------------


class TestHasAcceptanceCriteria:
    def test_present(self) -> None:
        assert cl.has_acceptance_criteria(_task(1, description="acceptance: X works"))

    def test_empty_or_near_empty_fails(self) -> None:
        assert not cl.has_acceptance_criteria(_task(1, description=""))
        assert not cl.has_acceptance_criteria(_task(1, description="   "))
        assert not cl.has_acceptance_criteria(_task(1, description="tiny"))

    def test_non_string_fails(self) -> None:
        assert not cl.has_acceptance_criteria({"id": 1, "description": None})
        assert not cl.has_acceptance_criteria({"id": 1})


class TestEvaluateDoR:
    def test_ready_dispatch_ticket(self, topology) -> None:
        repo, projects, roots = topology
        r = cl.evaluate_dor(
            _task(1, description="acceptance: builds + tests green"),
            target_repo_id="myapp",
            projects_dir=projects,
            roots=roots,
            has_open_blocker=False,
        )
        assert r.ready and r.reasons == ()

    def test_ready_non_dispatch_ticket_skips_target(self) -> None:
        # No target_repo_id -> a docs/advisory item, target check skipped.
        r = cl.evaluate_dor(_task(1, description="acceptance: doc updated"))
        assert r.ready

    def test_missing_criteria_not_ready(self) -> None:
        r = cl.evaluate_dor(_task(1, description=""))
        assert not r.ready
        assert any("acceptance criteria" in reason for reason in r.reasons)

    def test_invalid_target_id_not_ready(self, topology) -> None:
        repo, projects, roots = topology
        r = cl.evaluate_dor(
            _task(1),
            target_repo_id="../evil",
            projects_dir=projects,
            roots=roots,
        )
        assert not r.ready
        assert any("plain workspace component" in reason for reason in r.reasons)

    def test_governed_core_target_refused_through_dor(self, topology) -> None:
        # Artificial topology: projects_dir == the governed repo, so a plain
        # component ("shared") derives INTO the governed core -> SG ruler DENY,
        # surfaced by the DoR gate (proves DoR propagates #848's refusal).
        repo, _projects, roots = topology
        r = cl.evaluate_dor(
            _task(1),
            target_repo_id="shared",
            projects_dir=repo,
            roots=roots,
        )
        assert not r.ready
        assert any("SG ruler" in reason for reason in r.reasons)

    def test_target_given_but_no_roots_is_fail_closed(self, topology) -> None:
        repo, projects, _roots = topology
        r = cl.evaluate_dor(
            _task(1), target_repo_id="myapp", projects_dir=projects, roots=None
        )
        assert not r.ready
        assert any("cannot validate target" in reason for reason in r.reasons)

    def test_open_blocker_not_ready(self) -> None:
        r = cl.evaluate_dor(
            _task(1, description="acceptance: fine"), has_open_blocker=True
        )
        assert not r.ready
        assert any("blocking relation" in reason for reason in r.reasons)

    def test_multiple_failures_all_reported(self, topology) -> None:
        repo, projects, roots = topology
        r = cl.evaluate_dor(
            _task(1, description=""),
            target_repo_id="../evil",
            projects_dir=projects,
            roots=roots,
            has_open_blocker=True,
        )
        assert not r.ready
        assert len(r.reasons) == 3


# ---------------------------------------------------------------------------
# stall detection
# ---------------------------------------------------------------------------


class TestDetectStalls:
    def test_per_class_outlier_detected(self) -> None:
        # Standard class: three ~1h items + one 100h item -> the 100h is an outlier.
        tasks = [
            _task(1, created=_NOW - timedelta(hours=1)),
            _task(2, created=_NOW - timedelta(hours=1)),
            _task(3, created=_NOW - timedelta(hours=1)),
            _task(4, created=_NOW - timedelta(hours=100), title="stuck"),
        ]
        signals = cl.detect_stalls(tasks, now=_NOW)
        assert len(signals) == 1
        assert signals[0].task_id == 4
        assert signals[0].service_class is cl.ServiceClass.STANDARD
        assert signals[0].fingerprint == "Standard:4"

    def test_small_class_no_false_alarm(self) -> None:
        # A single-item class cannot produce a meaningful stddev -> no signal.
        signals = cl.detect_stalls(
            [_task(1, labels=["Expedite"], created=_NOW - timedelta(hours=500))],
            now=_NOW,
        )
        assert signals == []

    def test_classes_isolated(self) -> None:
        # A long-lived Standard baseline must not make an Expedite item "stall",
        # and vice versa — each class judged against its own baseline.
        tasks = [
            _task(1, labels=["Standard"], created=_NOW - timedelta(hours=200)),
            _task(2, labels=["Standard"], created=_NOW - timedelta(hours=200)),
            _task(3, labels=["Expedite"], created=_NOW - timedelta(hours=1)),
            _task(4, labels=["Expedite"], created=_NOW - timedelta(hours=1)),
            _task(5, labels=["Expedite"], created=_NOW - timedelta(hours=1)),
            _task(6, labels=["Expedite"], created=_NOW - timedelta(hours=40), title="x"),
        ]
        signals = cl.detect_stalls(tasks, now=_NOW)
        # The 40h Expedite item is the outlier within Expedite; the 200h Standard
        # pair is uniform (no variance) -> no Standard signal.
        assert [s.task_id for s in signals] == [6]
        assert signals[0].service_class is cl.ServiceClass.EXPEDITE

    def test_fail_soft_unparseable_timestamp(self) -> None:
        tasks = [
            _task(1, created=_NOW - timedelta(hours=1)),
            _task(2, created=_NOW - timedelta(hours=1)),
            _task(5, created=_NOW - timedelta(hours=1)),
            {"id": 3, "title": "bad", "created": "not-a-date"},
            _task(4, created=_NOW - timedelta(hours=100)),
        ]
        # The bad record drops out; no crash, outlier still found among the rest
        # (three ~1h baseline items + the 100h straggler clear the 1.5-sigma bar).
        signals = cl.detect_stalls(tasks, now=_NOW)
        assert [s.task_id for s in signals] == [4]

    def test_sorted_by_class_then_age(self) -> None:
        tasks = [
            _task(1, labels=["Standard"], created=_NOW - timedelta(hours=1)),
            _task(2, labels=["Standard"], created=_NOW - timedelta(hours=1)),
            _task(7, labels=["Standard"], created=_NOW - timedelta(hours=1)),
            _task(3, labels=["Standard"], created=_NOW - timedelta(hours=100)),
            _task(4, labels=["Expedite"], created=_NOW - timedelta(hours=1)),
            _task(5, labels=["Expedite"], created=_NOW - timedelta(hours=1)),
            _task(8, labels=["Expedite"], created=_NOW - timedelta(hours=1)),
            _task(6, labels=["Expedite"], created=_NOW - timedelta(hours=100)),
        ]
        signals = cl.detect_stalls(tasks, now=_NOW)
        # Expedite (pull_rank 0) before Standard (pull_rank 2).
        assert [s.task_id for s in signals] == [6, 3]


class TestAntiFirehoseDedup:
    def test_new_stall_signals_filters_seen(self) -> None:
        tasks = [
            _task(1, created=_NOW - timedelta(hours=1)),
            _task(2, created=_NOW - timedelta(hours=1)),
            _task(4, created=_NOW - timedelta(hours=1)),
            _task(3, created=_NOW - timedelta(hours=100)),
        ]
        signals = cl.detect_stalls(tasks, now=_NOW)
        fp = signals[0].fingerprint
        # First cycle: unseen -> surfaced.
        assert cl.new_stall_signals(signals, set()) == signals
        # Second cycle: same fingerprint already seen -> suppressed (one comment).
        assert cl.new_stall_signals(signals, {fp}) == []


# ---------------------------------------------------------------------------
# SSOT wiring — the operator-run migration and the runtime core share ONE list
# ---------------------------------------------------------------------------


class TestKanbanVocabularySSOT:
    def test_setup_migration_imports_the_same_vocabulary(self) -> None:
        from tools.dispatch_harness import coordinator_setup as setup

        assert setup.KANBAN_BUCKETS is cl.KANBAN_BUCKETS
        assert setup.CLASSES_OF_SERVICE is cl.CLASSES_OF_SERVICE

    def test_class_labels_match_service_class_enum(self) -> None:
        label_names = [name for name, _color in cl.CLASSES_OF_SERVICE]
        assert label_names == [sc.value for sc in cl.ServiceClass]

    def test_buckets_are_the_five_stages(self) -> None:
        assert cl.KANBAN_BUCKETS == (
            "Backlog",
            "Ready",
            "In Progress",
            "In Review/Verify",
            "Done",
        )
