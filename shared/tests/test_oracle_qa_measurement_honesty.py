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

from pathlib import Path

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


# ---------------------------------------------------------------------------
# #1350 — a `not-run` that says WHY
# ---------------------------------------------------------------------------
#
# All 81 banked oracle-qa.json records carry `f2p_baseline: "not-run"`, across both
# ecosystems since 2026-07-12, and none of them says whether the runner was missing, timed
# out, or died on its way up. The single most load-bearing check in the QA system reported
# the same word for a month and nobody could act on it.


def test_the_stamp_is_EXACTLY_not_run_so_the_gates_still_bite() -> None:
    """The load-bearing constraint. Decorating the stamp would re-open the amputation.

    `swap_driver._oracle_execution_validated` decides whether an oracle may DELETE work by
    membership test against `STAMPS_NOT_MEASURED`. A stamp like `not-run:timeout` fails that
    test, which would turn an unvalidated oracle back into evidence — #1342, reintroduced by
    a diagnostic. The cause must ride in a separate dict, never in the stamp.
    """
    diag: dict = {}
    stamp, _ = q.fail_to_pass_baseline("x", "C:/no/such/skeleton", diagnostics=diag)

    assert stamp == "not-run"
    assert stamp in q.STAMPS_NOT_MEASURED
    assert diag["cause"] == "skeleton-absent"


def test_a_runner_that_dies_before_pytest_speaks_names_itself(tmp_path: Path) -> None:
    """The production symptom: 81 records' worth of silence, now with a cause attached."""
    skeleton = tmp_path / "skeleton"
    skeleton.mkdir()
    (skeleton / "README.md").write_text("x", encoding="utf-8")

    def dead_runner(cmd, cwd, timeout, env=None):  # noqa: ANN001, ARG001
        return (False, "", "")

    diag: dict = {}
    stamp, _ = q.fail_to_pass_baseline(
        "def test_x(): assert False", str(skeleton), run=dead_runner, diagnostics=diag
    )

    assert stamp == "not-run"
    assert diag["cause"] == "runner-produced-nothing"
    assert diag["elapsed_s"] is not None, "a reader needs to know if it timed out or died fast"
    assert diag["cmd"], "the exact invocation is the first thing anyone would ask for"


def test_the_diagnostic_is_readable_on_a_windows_console(tmp_path: Path) -> None:
    """It is read in a console whose code page mangles non-ASCII punctuation."""
    diag: dict = {}
    q.fail_to_pass_baseline("x", "C:/no/such/skeleton", diagnostics=diag)
    assert diag["detail"].isascii()


def test_the_detail_reaches_the_banked_record() -> None:
    """A cause nothing publishes is the defect wearing the fix's uniform."""
    result = _result(f2p_baseline="not-run")
    result.f2p_diagnostics = {"cause": "runner-produced-nothing", "detail": "d"}
    evidence = result.to_evidence()

    assert evidence["not_measured_detail"]["cause"] == "runner-produced-nothing"
    assert evidence["findings_conclusive"] is False


def test_a_probe_that_RAN_publishes_no_cause() -> None:
    """An empty detail is how a reader tells `it ran` from `it did not`."""
    assert _a_measured_record().to_evidence()["not_measured_detail"] == {}


def test_toggle_proof_removing_the_capture_restores_the_silence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Disengage the capture and `not-run` goes back to saying nothing."""
    diag: dict = {}
    q.fail_to_pass_baseline("x", "C:/no/such/skeleton", diagnostics=diag)
    assert diag.get("cause"), "engaged: the cause must be captured"

    monkeypatch.setattr(
        q, "_not_run", lambda *a, **k: ("not-run", [])  # noqa: ARG005
    )
    blind: dict = {}
    stamp, _ = q.fail_to_pass_baseline("x", "C:/no/such/skeleton", diagnostics=blind)
    assert stamp == "not-run"
    assert blind == {}, "disengaged: the silence must return, or the capture proved nothing"


# ---------------------------------------------------------------------------
# #1351 — the generation collapsed instead of finishing
# ---------------------------------------------------------------------------

_TRUNCATED_ORACLE = Path(
    "C:/Users/mrbla/agentic-setup/state/fleet-runs/20260806-094526-bd/"
    "job-oracle-acceptance.job.test.mjs"
)


@pytest.mark.skipif(not _TRUNCATED_ORACLE.is_file(), reason="run archive not in this checkout")
def test_the_real_collapsed_oracle_is_caught() -> None:
    """The artifact: `habits2`..`habits55`, ending mid-token at `const habits55 = await get`.

    Two runs produced it BYTE-IDENTICALLY, because generation here is deterministic — so a
    retry reproduces the same corrupt exam forever. That is worse than a flaky truncation:
    re-running is not a remedy.
    """
    code = _TRUNCATED_ORACLE.read_text(encoding="utf-8", errors="replace")
    finding = q.generation_degeneracy(code)

    assert finding is not None, "the real collapsed oracle must be caught"
    assert finding.cls == q.CLASS_ADEQUACY_FLOOR
    assert "habits" in finding.message
    assert "retry" in finding.message.lower(), (
        "the message must say a retry cannot cure it — that is the actionable half"
    )


def test_it_runs_WITHOUT_parsing_because_the_artifact_does_not_parse() -> None:
    """The detector must work on raw text, and must fire before the syntax short-circuit.

    A collapsed generation typically stops mid-token, so it is unparseable — exactly when
    this finding is most useful. Placed after the syntax return it would never fire on the
    case it exists for.
    """
    # A two-character stem at minimum: single letters (`x1`, `y2`) read as coordinates and are
    # deliberately excluded — which this test tripped over on its own first run, using `a1`.
    collapsed = (
        "".join(f"const habit{i} = await get();\n" for i in range(1, 10))
        + "const habit10 = await get"
    )
    assert q.generation_degeneracy(collapsed) is not None


def test_a_healthy_oracle_is_not_convicted() -> None:
    """Precision: a handful of numbered fixtures is ordinary test-writing, not a collapse."""
    ordinary = (
        "const item1 = mk(); const item2 = mk(); const item3 = mk();\n"
        "assert.equal(total([item1, item2, item3]), 3);\n"
    )
    assert q.generation_degeneracy(ordinary) is None


def test_a_scattered_set_of_numbers_is_not_a_run() -> None:
    """Error codes and years are numbered identifiers too, and they are not a loop."""
    scattered = "code200 code301 code404 code418 code500 code502 code503 code504 code511"
    assert q.generation_degeneracy(scattered) is None


def test_toggle_proof_raising_the_threshold_blinds_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """The threshold is load-bearing, not a number that happens to sit in the file."""
    collapsed = " ".join(f"habits{i}" for i in range(1, 20))
    assert q.generation_degeneracy(collapsed) is not None

    monkeypatch.setattr(q, "_DEGENERACY_RUN_THRESHOLD", 99)
    assert q.generation_degeneracy(collapsed) is None
