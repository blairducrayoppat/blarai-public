"""Isolated tests for the C2 redispatch-staging limb (#844, coord_redispatch).

The limb is DORMANT (no live caller); these tests drive it in isolation over an
in-memory born-encrypted proposal store and tmp-path SG topologies, exactly as the
sibling C2 limbs are tested. The verdict-contract lock (TestVerdictContract) is
the load-bearing regression guard: the limb keys on the fleet's SUMMARY result
words across a module boundary, and a DORMANT limb whose trigger word drifted
would detect nothing — silently — until go-live.
"""

from __future__ import annotations

import inspect
import re
from datetime import datetime, timezone

import pytest

import shared.coordinator.config as sgconfig
import shared.fleet.coord_redispatch as cr
import shared.fleet.dispatch as dispatch
from shared.coordinator.proposal_store import (
    ProposalLane,
    ProposalStatus,
    build_proposal_store,
)

T0 = datetime(2026, 7, 13, 12, 0, 0, tzinfo=timezone.utc)


def _outcome(
    task: str = "build-widget",
    result: str = "PARKED",
    detail: str = "RESULT: not merged (parked for review)",
) -> dispatch.TaskOutcome:
    return dispatch.TaskOutcome(
        task=task, outcome="processed", result=result, detail=detail
    )


@pytest.fixture()
def store():
    """An in-memory born-encrypted store (SoftwareSealer dev path)."""
    s = build_proposal_store(":memory:")
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def topology(tmp_path):
    """A minimal SG topology: a governed repo root + a separate projects dir with
    one workspace repo (mirrors the evaluate_dor test fixture)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    projects = tmp_path / "projects"
    projects.mkdir()
    (projects / "myapp").mkdir()
    roots = sgconfig.GovernedCoreRoots(repo_root=repo)
    return repo, projects, roots


def _cycle(store, topology, outcomes, run_id="RID-1", repo_id="myapp", **kwargs):
    _repo, projects, roots = topology
    return cr.stage_redispatch_proposals(
        outcomes,
        run_id=run_id,
        repo_id=repo_id,
        projects_dir=projects,
        roots=roots,
        store=store,
        now=T0,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# The verdict contract — the cross-module string-literal regression lock
# ---------------------------------------------------------------------------


class TestVerdictContract:
    def test_classify_result_vocabulary_is_fully_classified(self) -> None:
        """Every result literal ``dispatch._classify_result`` can return MUST be
        explicitly eligible or excluded here. Extracting the literals from SOURCE
        means a future rename ("PARKED" -> anything) or a brand-new result word
        fails THIS test instead of silently making the dormant limb detect
        nothing (the failure mode only go-live would have surfaced)."""
        src = inspect.getsource(dispatch._classify_result)
        # ANY string-literal return counts ([^"]+, not [A-Z-]+): a future
        # lowercase/underscore/digit result word must fail this lock too, and a
        # refactor away from literal returns collapses the set to empty != the
        # declaration, which also fails loud (review NIT-1).
        literals = set(re.findall(r'return "([^"]+)"', src))
        assert literals == set(cr.RECOGNIZED_RESULTS)

    def test_eligible_is_exactly_the_honest_shortfall_class(self) -> None:
        assert cr.REDISPATCH_ELIGIBLE_RESULTS == frozenset({"PARKED"})

    def test_excluded_pins_every_non_candidate(self) -> None:
        assert cr.REDISPATCH_EXCLUDED_RESULTS == frozenset(
            {"MERGED", "BLOCKED", "NOTHING", "TIMEOUT", "UNKNOWN"}
        )

    def test_eligible_and_excluded_are_disjoint(self) -> None:
        assert not (cr.REDISPATCH_ELIGIBLE_RESULTS & cr.REDISPATCH_EXCLUDED_RESULTS)

    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            ("merged to main", "MERGED"),
            ("not merged (parked for review)", "PARKED"),
            ("blocked - possible secret", "BLOCKED"),
            ("nothing to merge", "NOTHING"),
            ("timed out after budget", "TIMEOUT"),
            ("who knows", "UNKNOWN"),
        ],
    )
    def test_classification_probes(self, line: str, expected: str) -> None:
        """Behavioral pins for the semantic each word carries — including that
        'not merged' wins over its 'merged' substring (the PARKED trigger)."""
        assert dispatch._classify_result(line) == expected

    def test_proposal_class_literal_is_release_stable(self) -> None:
        """The class literal is part of every fingerprint; renaming it would
        orphan the dedup history, so the literal itself is pinned."""
        assert cr.REDISPATCH_PROPOSAL_CLASS == "redispatch-parked"


# ---------------------------------------------------------------------------
# Eligibility — only PARKED stages
# ---------------------------------------------------------------------------


class TestEligibility:
    def test_parked_stages_one_draft(self, store, topology) -> None:
        result = _cycle(store, topology, [_outcome()])
        assert len(result.staged) == 1
        assert result.deduped == () and result.refused == () and result.errors == ()
        active = store.list_active()
        assert len(active) == 1
        p = active[0]
        assert p.status is ProposalStatus.DRAFT
        assert p.lane is ProposalLane.WORKSPACE
        assert p.proposal_class == cr.REDISPATCH_PROPOSAL_CLASS
        assert result.staged[0].proposal_id == p.id

    @pytest.mark.parametrize(
        ("result_word", "detail"),
        [
            ("MERGED", "merged to main"),
            ("BLOCKED", "blocked - possible secret"),
            ("NOTHING", "nothing to merge"),
            ("TIMEOUT", "timed out after budget"),
            ("UNKNOWN", "???"),
        ],
    )
    def test_excluded_results_stage_nothing(
        self, store, topology, result_word: str, detail: str
    ) -> None:
        result = _cycle(
            store, topology, [_outcome(result=result_word, detail=detail)]
        )
        assert result.staged == () and result.deduped == ()
        assert len(result.ineligible) == 1
        assert result_word in result.ineligible[0].reason
        assert store.list_active() == []

    def test_mixed_run_stages_only_the_parked_tasks(self, store, topology) -> None:
        outcomes = [
            _outcome(task="t-merged", result="MERGED", detail="merged"),
            _outcome(task="t-parked-1"),
            _outcome(task="t-timeout", result="TIMEOUT", detail="timed out"),
            _outcome(task="t-parked-2"),
        ]
        result = _cycle(store, topology, outcomes)
        assert {s.task for s in result.staged} == {"t-parked-1", "t-parked-2"}
        assert {s.task for s in result.ineligible} == {"t-merged", "t-timeout"}
        assert len(store.list_active()) == 2


# ---------------------------------------------------------------------------
# The SG ruler — fail-closed target severance (the CaMeL property)
# ---------------------------------------------------------------------------


class TestSGRuler:
    @pytest.mark.parametrize(
        "bad_repo_id",
        ["../evil", "a/b", "a\\b", ".hidden", "~home", "C:evil", "", "  ", ".."],
    )
    def test_non_plain_repo_id_refused_fail_closed(
        self, store, topology, bad_repo_id: str
    ) -> None:
        result = _cycle(store, topology, [_outcome()], repo_id=bad_repo_id)
        assert result.staged == ()
        assert len(result.refused) == 1
        assert "plain workspace component" in result.refused[0].reason
        assert store.list_active() == []

    def test_governed_core_target_refused(self, store, topology) -> None:
        """projects_dir aimed AT the governed repo: a plain component derives INTO
        the governed core and the staging-time ruler refuses (same artificial
        topology the evaluate_dor lock uses)."""
        repo, _projects, roots = topology
        result = cr.stage_redispatch_proposals(
            [_outcome()],
            run_id="RID-1",
            repo_id="shared",
            projects_dir=repo,
            roots=roots,
            store=store,
            now=T0,
        )
        assert result.staged == ()
        assert len(result.refused) == 1
        assert "SG ruler at staging" in result.refused[0].reason
        assert "governed core" in result.refused[0].reason
        assert store.list_active() == []

    def test_renamed_clone_sentinel_refused(self, store, topology) -> None:
        """A workspace dir carrying the governed-core sentinel is refused by
        content identity (layer 3) even though its PATH is innocent."""
        _repo, projects, _roots = topology
        evil = projects / "evil"
        evil.mkdir()
        (evil / sgconfig.GOVERNED_CORE_SENTINEL_FILE).touch()
        result = _cycle(store, topology, [_outcome()], repo_id="evil")
        assert result.staged == ()
        assert len(result.refused) == 1
        assert "governed core" in result.refused[0].reason
        assert store.list_active() == []

    def test_refusal_happens_before_the_store(
        self, store, topology, monkeypatch
    ) -> None:
        """A refused cycle never calls the store at all — the fence sits in front
        of the sanctioned API, not behind it."""

        def _must_not_be_called(**_kwargs):
            raise AssertionError("add_draft must not be reached on a refused cycle")

        monkeypatch.setattr(store, "add_draft", _must_not_be_called)
        result = _cycle(store, topology, [_outcome()], repo_id="../evil")
        assert len(result.refused) == 1

    def test_blank_run_id_refused_fail_closed(self, store, topology) -> None:
        result = _cycle(store, topology, [_outcome()], run_id="   ")
        assert result.staged == ()
        assert len(result.refused) == 1
        assert "malformed cycle input" in result.refused[0].reason
        assert store.list_active() == []

    def test_refusal_still_reports_ineligible(self, store, topology) -> None:
        outcomes = [_outcome(task="t-parked"), _outcome(task="t-done", result="MERGED")]
        result = _cycle(store, topology, outcomes, repo_id="../evil")
        assert {s.task for s in result.refused} == {"t-parked"}
        assert {s.task for s in result.ineligible} == {"t-done"}


# ---------------------------------------------------------------------------
# Dedup semantics — the deliberate evidence-hash grain
# ---------------------------------------------------------------------------


class TestDedupSemantics:
    def test_same_run_re_read_stages_once(self, store, topology) -> None:
        """The same parked run seen every cycle asks ONCE (§2.12.5)."""
        first = _cycle(store, topology, [_outcome()])
        second = _cycle(store, topology, [_outcome()])
        assert len(first.staged) == 1
        assert second.staged == ()
        assert len(second.deduped) == 1
        assert second.deduped[0].proposal_id == first.staged[0].proposal_id
        assert len(store.list_active()) == 1

    def test_new_run_is_new_evidence_and_stages_fresh(self, store, topology) -> None:
        first = _cycle(store, topology, [_outcome()], run_id="RID-1")
        second = _cycle(store, topology, [_outcome()], run_id="RID-2")
        assert len(first.staged) == 1 and len(second.staged) == 1
        assert first.staged[0].fingerprint != second.staged[0].fingerprint
        assert len(store.list_active()) == 2

    @pytest.mark.parametrize("decision", ["approved", "rejected"])
    def test_decided_evidence_is_never_reasked(
        self, store, topology, decision: str
    ) -> None:
        """The post-terminal nag-loop lock: after the operator decides on THIS
        evidence, re-reading the same parked run stages nothing — the store's
        terminal-doesn't-suppress is reserved for NEW evidence (a new run)."""
        first = _cycle(store, topology, [_outcome()])
        pid = first.staged[0].proposal_id
        store.mark_staged(pid, now=T0)
        if decision == "approved":
            store.mark_approved(pid, now=T0)
        else:
            store.mark_rejected(pid, now=T0)

        again = _cycle(store, topology, [_outcome()])
        assert again.staged == () and again.deduped == ()
        assert len(again.already_decided) == 1
        assert decision in again.already_decided[0].reason
        assert store.list_active() == []

    def test_duplicate_task_lines_in_one_run_stage_once(self, store, topology) -> None:
        result = _cycle(store, topology, [_outcome(task="t"), _outcome(task="t")])
        assert len(result.staged) == 1
        assert len(result.deduped) == 1
        assert len(store.list_active()) == 1

    def test_active_dedup_survives_staging_transition(self, store, topology) -> None:
        """A proposal surfaced to the operator (STAGED) still dedups — active
        means DRAFT or STAGED."""
        first = _cycle(store, topology, [_outcome()])
        store.mark_staged(first.staged[0].proposal_id, now=T0)
        again = _cycle(store, topology, [_outcome()])
        assert again.staged == ()
        assert len(again.deduped) == 1


# ---------------------------------------------------------------------------
# Payload — deterministic composition, born-encrypted at rest
# ---------------------------------------------------------------------------


class TestPayload:
    def test_payload_fields_round_trip(self, store, topology) -> None:
        outcome = _outcome(task="fix-the-parser", detail="not merged (review pending)")
        result = _cycle(store, topology, [outcome])
        p = store.get(result.staged[0].proposal_id)
        assert p is not None
        payload = p.payload
        assert payload["run_id"] == "RID-1"
        assert payload["repo_id"] == "myapp"
        assert payload["target"].endswith("myapp")
        assert payload["task"] == "fix-the-parser"
        assert payload["result"] == "PARKED"
        assert payload["detail"] == "not merged (review pending)"
        assert "fix-the-parser" in payload["goal"]
        assert payload["evidence"] == ["run:RID-1"]

    def test_evidence_pointer_uses_runs_dir_when_given(
        self, store, topology, tmp_path
    ) -> None:
        runs = tmp_path / "runs"
        result = _cycle(store, topology, [_outcome()], runs_dir=runs)
        p = store.get(result.staged[0].proposal_id)
        assert p is not None
        (pointer,) = p.payload["evidence"]
        assert pointer.endswith("SUMMARY.txt")
        assert "RID-1" in pointer

    def test_payload_is_encrypted_at_rest(self, store, topology) -> None:
        """Content-bearing → born-encrypted (§2.13 item 2): the task text must
        not appear in the at-rest payload blob."""
        result = _cycle(store, topology, [_outcome(task="SECRET-TASK-MARKER")])
        pid = result.staged[0].proposal_id
        raw = store._conn.execute(  # noqa: SLF001 - inspecting at-rest bytes
            "SELECT payload FROM coordinator_proposals WHERE id = ?", (pid,)
        ).fetchone()[0]
        assert b"SECRET-TASK-MARKER" not in bytes(raw)


# ---------------------------------------------------------------------------
# Fail-soft — a store fault never crashes the cycle, and naturally retries
# ---------------------------------------------------------------------------


class TestFailSoft:
    def test_store_fault_is_recorded_and_cycle_continues(
        self, store, topology, monkeypatch
    ) -> None:
        original = store.add_draft
        calls = {"n": 0}

        def flaky(**kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("simulated store fault")
            return original(**kwargs)

        monkeypatch.setattr(store, "add_draft", flaky)
        outcomes = [_outcome(task="t-a"), _outcome(task="t-b")]
        result = _cycle(store, topology, outcomes)
        assert len(result.errors) == 1 and result.errors[0].task == "t-a"
        assert len(result.staged) == 1 and result.staged[0].task == "t-b"

        # No proposal was written for the faulted task, so the next cycle
        # naturally retries it (and dedups the one that landed).
        monkeypatch.undo()
        retry = _cycle(store, topology, outcomes)
        assert {s.task for s in retry.staged} == {"t-a"}
        assert {s.task for s in retry.deduped} == {"t-b"}


# ---------------------------------------------------------------------------
# The execution-time re-validation seam (§2.12 item 4 — TOCTOU)
# ---------------------------------------------------------------------------


class TestExecutionSeam:
    def test_revalidate_allows_an_intact_world(self, store, topology) -> None:
        _repo, projects, roots = topology
        result = _cycle(store, topology, [_outcome()])
        p = store.get(result.staged[0].proposal_id)
        assert p is not None
        verdict = cr.revalidate_for_execution(p, roots=roots, projects_dir=projects)
        assert verdict.allowed
        assert verdict.phase == "EXECUTION"

    def test_revalidate_denies_a_world_that_changed(self, store, topology) -> None:
        """The literal TOCTOU: valid at staging, the target becomes a
        governed-core clone before execution — the execution-time run refuses."""
        _repo, projects, roots = topology
        result = _cycle(store, topology, [_outcome()])
        p = store.get(result.staged[0].proposal_id)
        assert p is not None
        (projects / "myapp" / sgconfig.GOVERNED_CORE_SENTINEL_FILE).touch()
        verdict = cr.revalidate_for_execution(p, roots=roots, projects_dir=projects)
        assert verdict.denied
        assert verdict.phase == "EXECUTION"
        assert "governed core" in verdict.reason

    def test_revalidate_denies_payload_without_repo_id(self, store, topology) -> None:
        _repo, projects, roots = topology
        p = store.add_draft(
            lane=ProposalLane.WORKSPACE,
            proposal_class=cr.REDISPATCH_PROPOSAL_CLASS,
            fingerprint="fp-no-repo-id",
            payload={"goal": "hand-crafted payload missing the structured field"},
            now=T0,
        )
        verdict = cr.revalidate_for_execution(p, roots=roots, projects_dir=projects)
        assert verdict.denied
        assert "no structured repo_id" in verdict.reason
        assert verdict.phase == "EXECUTION"

    def test_revalidate_denies_malformed_repo_id(self, store, topology) -> None:
        _repo, projects, roots = topology
        p = store.add_draft(
            lane=ProposalLane.WORKSPACE,
            proposal_class=cr.REDISPATCH_PROPOSAL_CLASS,
            fingerprint="fp-bad-repo-id",
            payload={"repo_id": "../evil"},
            now=T0,
        )
        verdict = cr.revalidate_for_execution(p, roots=roots, projects_dir=projects)
        assert verdict.denied
        assert "plain workspace component" in verdict.reason
        assert verdict.phase == "EXECUTION"


# ---------------------------------------------------------------------------
# Evidence-hash primitive
# ---------------------------------------------------------------------------


class TestEvidenceHash:
    def test_deterministic_and_distinct_by_field(self) -> None:
        a = cr.redispatch_evidence_hash(run_id="r1", task="t", result="PARKED")
        b = cr.redispatch_evidence_hash(run_id="r1", task="t", result="PARKED")
        c = cr.redispatch_evidence_hash(run_id="r2", task="t", result="PARKED")
        d = cr.redispatch_evidence_hash(run_id="r1", task="u", result="PARKED")
        assert a == b
        assert len({a, c, d}) == 3
        assert len(a) == 64 and all(ch in "0123456789abcdef" for ch in a)

    def test_field_boundaries_unambiguous(self) -> None:
        left = cr.redispatch_evidence_hash(run_id="a", task="bc", result="x")
        right = cr.redispatch_evidence_hash(run_id="ab", task="c", result="x")
        assert left != right
