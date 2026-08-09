"""#1342 item 2 — the oracle QA record may not report a pass it never measured.

The escaped artifact this file exists for, verbatim from
``state/fleet-runs/20260808-160538-bd/oracle-qa.json``::

    { "validated": true,  "findings_total": 0,
      "findings": { "f2p_vacuous": 0, "adequacy_floor": 0, ... },
      "f2p_baseline": "not-run",
      "collectability": "skipped",
      "oracle_coverage": "unknown", "covered": [], "uncovered": [] }

``f2p_vacuous`` IS the check for vacuous tests. It reported 0 against an oracle that was
three-fifths vacuous — two empty test bodies, an assertion-free call, a tautology — because
the stage that produces that finding never ran. Every reader takes ``0 findings`` to mean
*we looked and found nothing*. It meant *we did not look*, and the honest field
(``f2p_baseline: "not-run"``) sat directly beside the confident one, lending it credibility.

That record was consumed downstream: the ``already_satisfied`` optimisation trusted the
passing oracle and deleted two tasks from the plan, one of them a page the operator had
explicitly asked for. The count being un-interpretable was not cosmetic.
"""

from __future__ import annotations

import pytest

from shared.fleet import oracle_qa as q


def _result(**kwargs) -> q.OracleQAResult:
    """An OracleQAResult with the given stamps; everything else at its default."""
    verdict = kwargs.pop("verdict", "seed")
    result = q.OracleQAResult(oracle_code="", verdict=verdict)
    for key, value in kwargs.items():
        setattr(result, key, value)
    return result


#: The escaped shape: a node oracle whose execution stages were both skipped.
def _the_escaped_record() -> q.OracleQAResult:
    return _result(
        language="node", f2p_baseline="not-run", collectability="skipped",
        coverage_denominator=0,
    )


#: A run where every stage genuinely produced a result.
def _a_measured_record() -> q.OracleQAResult:
    return _result(
        language="python", f2p_baseline="all-fail", collectability="confirmed",
        coverage_denominator=5, covered=["c1", "c2", "c3", "c4", "c5"],
    )


# ---------------------------------------------------------------------------
# The record that escaped
# ---------------------------------------------------------------------------


def test_the_real_escaped_record_is_no_longer_conclusive() -> None:
    """The exact #1342 stamps must produce a record that cannot be read as clean."""
    evidence = _the_escaped_record().to_evidence()

    assert evidence["findings_total"] == 0
    assert evidence["findings_conclusive"] is False, (
        "zero findings from unrun checks must NOT be marked conclusive — this is the "
        "whole defect"
    )
    assert evidence["measurement"]["status"] == "partial"
    assert evidence["not_measured"], "the checks that did not run must be named"


def test_the_vacuity_check_reports_itself_as_unmeasured() -> None:
    """``f2p_vacuous: 0`` beside ``f2p_baseline: not-run`` must be labelled unmeasured.

    This is the single most load-bearing assertion in the file: it is the exact pair of
    fields that certified a three-fifths-vacuous oracle.
    """
    evidence = _the_escaped_record().to_evidence()

    assert evidence["findings"]["f2p_vacuous"] == 0
    assert evidence["findings_measured"]["f2p_vacuous"] is False
    assert evidence["findings_measured"]["collectability"] is False


def test_the_unmeasured_reasons_are_readable_by_a_person() -> None:
    """A reader deciding whether to trust a delivery gets sentences, not stage names."""
    reasons = " ".join(_the_escaped_record().to_evidence()["not_measured"])

    assert "shown capable of failing" in reasons
    assert "f2p_seed_gate" not in reasons, "internals must not leak into the disclosure"


# ---------------------------------------------------------------------------
# The distinction the record must carry
# ---------------------------------------------------------------------------


def test_measured_clean_and_unmeasured_are_DIFFERENT_records() -> None:
    """Ran-and-found-nothing must be distinguishable from did-not-run.

    Both have ``findings_total == 0``. If that were the only readable field, the two would
    be indistinguishable — which is precisely how the defect survived four gates.
    """
    unmeasured = _the_escaped_record().to_evidence()
    measured = _a_measured_record().to_evidence()

    assert unmeasured["findings_total"] == measured["findings_total"] == 0
    assert unmeasured["findings_conclusive"] is False
    assert measured["findings_conclusive"] is True
    assert measured["not_measured"] == []
    assert measured["measurement"]["status"] == "measured"


def test_a_real_finding_is_still_reported_when_stages_ran() -> None:
    """The honesty block must not swallow genuine findings."""
    result = _a_measured_record()
    result.counts[q.CLASS_F2P_VACUOUS] = 2
    evidence = result.to_evidence()

    assert evidence["findings_total"] == 2
    assert evidence["findings_conclusive"] is True


@pytest.mark.parametrize("stamp", ["", "not-run", "skipped", "unknown", "NOT-RUN", " skipped "])
def test_every_not_measured_stamp_is_recognised(stamp: str) -> None:
    """Case and whitespace must not smuggle an unrun stage past the check."""
    result = _a_measured_record()
    result.f2p_baseline = stamp
    assert result.stage_measured()[q.STAGE_F2P] is False
    assert result.to_evidence()["findings_conclusive"] is False


@pytest.mark.parametrize("stamp", ["all-fail", "confirmed", "refused"])
def test_a_real_stamp_counts_as_evidence(stamp: str) -> None:
    result = _a_measured_record()
    result.f2p_baseline = stamp
    assert result.stage_measured()[q.STAGE_F2P] is True


def test_nothing_measured_at_all_is_its_own_status() -> None:
    result = _result(
        validated=False, f2p_baseline="not-run", collectability="not-run",
        coverage_denominator=0,
    )
    assert result.to_evidence()["measurement"]["status"] == "unmeasured"


def test_every_finding_class_names_the_stage_that_produces_it() -> None:
    """A class with no stage would default to 'static' and could be silently misreported."""
    missing = [c for c in q.ALL_CLASSES if c not in q.CLASS_STAGE]
    assert missing == [], f"finding classes with no stage mapping: {missing}"


# ---------------------------------------------------------------------------
# Back-compatibility — the block is additive
# ---------------------------------------------------------------------------


def test_every_pre_existing_key_survives_unchanged() -> None:
    """Consumers of this shape (#827 classifier, #832 green-audit) must not break."""
    evidence = _a_measured_record().to_evidence()
    for key in (
        "validated", "language", "verdict", "findings", "findings_total",
        "regeneration", "oracle_coverage", "covered", "uncovered",
        "f2p_baseline", "collectability",
    ):
        assert key in evidence, f"pre-existing evidence key '{key}' was dropped"


def test_the_stamp_vocabulary_has_ONE_owner() -> None:
    """`swap_driver` must import the vocabulary, not keep a second copy of it.

    Two copies drift, and the drift is silent in the direction that hurts: a stamp the
    consumer failed to recognise as "not measured" would be treated as evidence and let an
    unvalidated oracle delete work from the plan again.
    """
    from shared.fleet import swap_driver

    assert swap_driver._QA_STAMPS_NOT_MEASURED is q.STAMPS_NOT_MEASURED


# ---------------------------------------------------------------------------
# Toggle proof — security_by_design principle 12
# ---------------------------------------------------------------------------


def test_toggle_proof_the_probe_fails_when_stage_mapping_is_disengaged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Claim every stage ran, and the escaped record grades conclusive again.

    Without this, a green suite cannot be told apart from a probe that never reached the
    code under test.
    """
    evidence = _the_escaped_record().to_evidence()
    assert evidence["findings_conclusive"] is False

    monkeypatch.setattr(
        q.OracleQAResult,
        "stage_measured",
        lambda self: {s: True for s in (
            q.STAGE_STATIC, q.STAGE_COLLECTABILITY, q.STAGE_F2P, q.STAGE_COVERAGE, q.STAGE_ALWAYS
        )},
    )
    disengaged = _the_escaped_record().to_evidence()
    assert disengaged["findings_conclusive"] is True, (
        "disengaging the stage map must restore the defect — if it does not, the engaged "
        "result was not produced by the control under test"
    )
    assert disengaged["not_measured"] == []
