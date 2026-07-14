"""#827 QUALITY-9 — the standing failure-taxonomy classifier.

The load-bearing test is the POSITIVE CONTROL (lesson 222): the 9 hand-classified
job-instances from ``docs/handoffs/failure-taxonomy-20260711.md`` are reconstructed as
fixtures, and the deterministic classifier MUST reproduce the human's class on every one.
A verdict-issuing instrument's classes are not believed until it can produce the known
answer on a known subject.

The other suites lock the invariants: ADVISORY (never mutates a verdict/attribution), the
GREEN-side coverage classification (c.1735), the structured-sidecar (#821/#822/#824)
consumption path, the priority ordering, the honest UNCLASSIFIED residue, and the
battery-close summary integration (the KPI trend line + the per-job re-stamp).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.dispatch_harness import battery as bat
from tools.dispatch_harness import failure_taxonomy as ftax
from tools.dispatch_harness.scorecard import Scorecard, validate


# ---------------------------------------------------------------------------
# Fixture helpers — reconstruct a run dir + scorecard from an evidence signature
# ---------------------------------------------------------------------------


def _make_run_dir(tmp_path: Path, run_id: str, files: "dict[str, str]") -> Path:
    """Write ``files`` (name -> text) into ``<tmp_path>/<run_id>/`` and return tmp_path
    (the runs_dir the classifier is handed)."""
    run_dir = tmp_path / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (run_dir / name).write_text(text, encoding="utf-8")
    return tmp_path


def _sc(job_id: str, verdict: str, attribution: str, evidence: dict, run_id: str) -> Scorecard:
    return Scorecard(
        job_id=job_id, verdict=verdict, attribution=attribution,
        evidence=dict(evidence), run_id=run_id, repo=f"sandbox/{job_id.lower()}",
    )


# ---------------------------------------------------------------------------
# THE 9 GOLDENS — the classifier must reproduce the hand-analysis (positive control)
# ---------------------------------------------------------------------------

# Each golden: (id, verdict, attribution, evidence, {run-dir files}, expected class).
# The evidence + files reproduce the exact signature the analyst read (raw logs — the
# historical runs predate the #821/#822/#824 structured sidecars, so the classifier's
# log-regex fallback is exercised here exactly as it will be for any flat run).
_GOLDENS = [
    pytest.param(
        "B1", "PARKED-HONEST", "BUILD",
        {"oracle_status": "not-run", "mode": "flat"},
        {"run-fleet-retrieve-expense-list.log":
            "    @given(st.text(min_length=1), st.floats(allow_nan=False))\n"
            "E   TypeError: text() got an unexpected keyword argument 'min_length'\n"},
        ftax.CLASS_ORACLE_DEFECT, id="B1-n1 oracle kwargs bug (flat)",
    ),
    pytest.param(
        "B1", "PARKED-HONEST", "BUILD",
        {"oracle_status": "not-run", "mode": "flat"},
        {"run-fleet-retrieve-expense-list.log":
            "    | ValueError: Amount must be a positive number\n"
            "    | Falsifying example: test_list_expenses_returns_sorted_list_by_date(\n"
            "    |     expenses=[(0.0, '0', '0')],\n"},
        ftax.CLASS_ORACLE_DEFECT, id="B1-n2 ill-posed strategy (flat)",
    ),
    pytest.param(
        "B4", "PARKED-HONEST", "BUILD",
        {"oracle_status": "failed", "mode": "plan-graph"},
        {"JOB_SUMMARY.txt":
            "from cli import main\nE   ModuleNotFoundError: No module named 'cli'\n"
            "Interrupted: 1 error during collection\n"},
        ftax.CLASS_INTEGRATION_SEAM, id="B4-n1 import seam (cli)",
    ),
    pytest.param(
        "B4", "PARKED-HONEST", "BUILD",
        {"oracle_status": "failed", "mode": "plan-graph"},
        {"swap-progress.log":
            "JOB acceptance oracle FAILED ... test_graceful_exit - "
            "OSError: pytest: reading from stdin while output is captured\n"
            "6 failed, 1 passed\n"},
        ftax.CLASS_ORACLE_DEFECT, id="B4-n2 interactive-io oracle defect",
    ),
    pytest.param(
        "B5", "PARKED-HONEST", "BUILD",
        {"oracle_status": "not-run", "mode": "flat"},
        {"JOB_SUMMARY.txt": "Nothing to merge\n"},
        ftax.CLASS_DECOMPOSE_DOWNGRADE, id="B5-n1 nothing-to-merge (flat)",
    ),
    pytest.param(
        "B5", "STALLED", "VERIFY",
        {"oracle_status": "not-run", "mode": "flat", "design_review": "cap-reached"},
        {"design-critique.log":
            "The 'OK (sum = undefined)' text appears misaligned and unprofessional.\n"
            "The chart area is a large white rectangle with no visible chart.\n"},
        ftax.CLASS_BLIND_FIX_LOOP, id="B5-n2 blind-fix-loop (design cap)",
    ),
    pytest.param(
        "B6", "PARKED-HONEST", "BUILD",
        {"oracle_status": "failed", "mode": "plan-graph"},
        {"JOB_SUMMARY.txt":
            "from inventory_manager import InventoryManager\n"
            "E   ModuleNotFoundError: No module named 'inventory_manager'\n"},
        ftax.CLASS_INTEGRATION_SEAM, id="B6-n1 import seam (inventory_manager)",
    ),
    pytest.param(
        "B6", "PARKED-HONEST", "BUILD",
        {"oracle_status": "failed", "mode": "plan-graph"},
        {"run-fleet-create-command-line-interface.log":
            ">       from cli_interface import run_cli\n"
            "E       ModuleNotFoundError: No module named 'cli_interface'\n"},
        ftax.CLASS_INTEGRATION_SEAM, id="B6-n2 layout drift (cli_interface)",
    ),
    pytest.param(
        "B7", "PARKED-HONEST", "BUILD",
        {"oracle_status": "failed", "mode": "plan-graph"},
        {"JOB_SUMMARY.txt":
            "Error [ERR_MODULE_NOT_FOUND]: Cannot find module '.../src/slugify-phrase.js'\n"},
        ftax.CLASS_INTEGRATION_SEAM, id="B7-n1 import seam (node)",
    ),
]


@pytest.mark.parametrize("job,verdict,attr,evidence,files,expected", _GOLDENS)
def test_nine_goldens_reproduce_the_hand_taxonomy(
    tmp_path, job, verdict, attr, evidence, files, expected
):
    """The positive control: every hand-classified job-instance is reproduced."""
    run_id = f"{job}-run"
    runs_dir = _make_run_dir(tmp_path, run_id, files)
    sc = _sc(job, verdict, attr, evidence, run_id)
    klass, fingerprint = ftax.classify_scorecard(sc, runs_dir=runs_dir)
    assert klass == expected, f"{job}: got {klass} ({fingerprint}), expected {expected}"
    assert fingerprint  # every classification names its evidence


def test_all_nine_goldens_classify_zero_unclassified(tmp_path):
    """The whole golden set has UNCLASSIFIED == 0 — the instrument is healthy on the
    known subjects (a golden falling to residue would mean a regressed fingerprint)."""
    pairs = []
    for i, p in enumerate(_GOLDENS):
        job, verdict, attr, evidence, files, expected = p.values
        run_id = f"{job}-{i}"
        runs_dir = _make_run_dir(tmp_path, run_id, files)
        sc = _sc(job, verdict, attr, evidence, run_id)
        klass, fp = ftax.classify_scorecard(sc, runs_dir=runs_dir)
        pairs.append((sc, klass, fp))
    agg = ftax.aggregate(pairs)
    assert agg["unclassified"] == 0
    assert agg["failure_classes"][ftax.CLASS_ORACLE_DEFECT] == 3   # B1n1,B1n2,B4n2
    assert agg["failure_classes"][ftax.CLASS_INTEGRATION_SEAM] == 4  # B4n1,B6n1,B6n2,B7n1
    assert agg["failure_classes"][ftax.CLASS_BLIND_FIX_LOOP] == 1    # B5n2
    assert agg["failure_classes"][ftax.CLASS_DECOMPOSE_DOWNGRADE] == 1  # B5n1


# ---------------------------------------------------------------------------
# ADVISORY invariant — the classifier NEVER changes a verdict or attribution
# ---------------------------------------------------------------------------


def test_classify_and_stamp_never_mutates_verdict_or_attribution():
    cards = [
        Scorecard(job_id="B1", verdict="GREEN", evidence={"oracle_status": "passed"}),
        Scorecard(job_id="B4", verdict="PARKED-HONEST", attribution="BUILD",
                  evidence={"oracle_status": "failed", "mode": "plan-graph"}),
        Scorecard(job_id="B8", verdict="FALSE-DONE", attribution="VERIFY",
                  evidence={"oracle_status": "passed"}),
        Scorecard(job_id="B6", verdict="STALLED", attribution="HARNESS",
                  evidence={"oracle_status": "unknown"}),
    ]
    before = [(c.verdict, c.attribution) for c in cards]
    ftax.classify_and_stamp(cards, runs_dir=None, out_dir=None)
    after = [(c.verdict, c.attribution) for c in cards]
    assert before == after
    # …and every card gained exactly one advisory stamp (failure OR green class).
    for c in cards:
        ev = c.evidence
        has_failure = ftax.EV_FAILURE_CLASS in ev
        has_green = ftax.EV_GREEN_CLASS in ev
        assert has_failure ^ has_green, f"{c.job_id}: exactly one class stamp expected"


def test_block_declares_itself_advisory():
    block = ftax.classify_and_stamp(
        [Scorecard(job_id="B4", verdict="PARKED-HONEST", attribution="BUILD",
                   evidence={"mode": "flat"})],
        runs_dir=None, out_dir=None,
    )
    assert block["classifier_advisory"] is True
    assert block["schema"] == ftax.TAXONOMY_SCHEMA


def test_stamped_evidence_still_validates_as_a_scorecard():
    """The stamp is a string pointer — a stamped scorecard is still writer-valid (S6)."""
    sc = Scorecard(job_id="B4", verdict="PARKED-HONEST", attribution="BUILD",
                   evidence={"oracle_status": "failed", "mode": "flat"})
    ftax.classify_and_stamp([sc], runs_dir=None, out_dir=None)
    assert validate(sc) == []
    assert "\n" not in sc.evidence[ftax.EV_FAILURE_FINGERPRINT]


# ---------------------------------------------------------------------------
# Structured-sidecar (#821 / #822 / #824) consumption — the forward path
# ---------------------------------------------------------------------------


def _oracle_qa_run(tmp_path, run_id, qa: dict):
    return _make_run_dir(tmp_path, run_id, {"oracle-qa.json": json.dumps(qa)})


def test_oracle_qa_findings_route_to_oracle_defect(tmp_path):
    runs_dir = _oracle_qa_run(tmp_path, "r", {
        "oracle_coverage": "2/3",
        "findings": {c: 0 for c in ftax._ORACLE_DEFECT_FINDINGS} | {"strategy_illposed": 1},
    })
    sc = _sc("B1", "PARKED-HONEST", "BUILD", {"oracle_status": "failed", "mode": "plan-graph"}, "r")
    klass, fp = ftax.classify_scorecard(sc, runs_dir=runs_dir)
    assert klass == ftax.CLASS_ORACLE_DEFECT
    assert "strategy_illposed" in fp


def test_oracle_qa_refuse_routes_to_oracle_defect(tmp_path):
    runs_dir = _oracle_qa_run(tmp_path, "r", {"verdict": "refuse", "findings": {}, "f2p_baseline": "vacuous:test_x"})
    sc = _sc("B4", "PARKED-HONEST", "VERIFY", {"oracle_status": "not-run", "mode": "plan-graph"}, "r")
    klass, _ = ftax.classify_scorecard(sc, runs_dir=runs_dir)
    assert klass == ftax.CLASS_ORACLE_DEFECT


def test_import_probe_verdict_routes_to_integration_seam(tmp_path):
    runs_dir = _make_run_dir(tmp_path, "r", {"import-probe-verdict.json": json.dumps(
        {"ok": False, "unresolved": [{"module": "cli_interface", "raw": "from cli_interface import run_cli"}]}
    )})
    sc = _sc("B6", "PARKED-HONEST", "BUILD", {"oracle_status": "failed", "mode": "plan-graph"}, "r")
    klass, fp = ftax.classify_scorecard(sc, runs_dir=runs_dir)
    assert klass == ftax.CLASS_INTEGRATION_SEAM
    assert "cli_interface" in fp


def test_import_contract_finding_routes_to_seam_not_oracle(tmp_path):
    runs_dir = _oracle_qa_run(tmp_path, "r", {
        "oracle_coverage": "unknown",
        "findings": {c: 0 for c in ftax._ORACLE_DEFECT_FINDINGS} | {"import_contract": 1},
    })
    sc = _sc("B6", "PARKED-HONEST", "BUILD", {"oracle_status": "failed", "mode": "plan-graph"}, "r")
    klass, _ = ftax.classify_scorecard(sc, runs_dir=runs_dir)
    assert klass == ftax.CLASS_INTEGRATION_SEAM


def test_decompose_diagnostics_flat_routes_to_downgrade(tmp_path):
    runs_dir = _make_run_dir(tmp_path, "r", {"decompose-diagnostics.json": json.dumps(
        {"mode": "flat", "flat_reason": "malformed-collapse", "cleaned_task_count": 1}
    )})
    # No mode in the scorecard evidence — the sidecar carries the flat signal.
    sc = _sc("B1", "PARKED-HONEST", "BUILD", {"oracle_status": "not-run"}, "r")
    klass, fp = ftax.classify_scorecard(sc, runs_dir=runs_dir)
    assert klass == ftax.CLASS_DECOMPOSE_DOWNGRADE
    assert "malformed-collapse" in fp


# ---------------------------------------------------------------------------
# Priority ordering — the crux the goldens depend on
# ---------------------------------------------------------------------------


def test_oracle_defect_outranks_decompose_downgrade(tmp_path):
    """A FLAT run with a broken oracle attributes to ORACLE-DEFECT, not merely mode=flat
    (the B1 ranking: primary ORACLE-DEFECT, secondary DECOMPOSE-DOWNGRADE)."""
    runs_dir = _make_run_dir(tmp_path, "r", {"run-fleet-x.log":
        "E   TypeError: text() got an unexpected keyword argument 'min_size'\n"})
    sc = _sc("B1", "PARKED-HONEST", "BUILD", {"oracle_status": "not-run", "mode": "flat"}, "r")
    assert ftax.classify_scorecard(sc, runs_dir=runs_dir)[0] == ftax.CLASS_ORACLE_DEFECT


def test_blind_fix_outranks_decompose_downgrade():
    """A flat run whose design loop capped is BLIND-FIX-LOOP, not DECOMPOSE (B5-n2)."""
    sc = Scorecard(job_id="B5", verdict="STALLED", attribution="VERIFY",
                   evidence={"mode": "flat", "design_review": "cap-reached"})
    assert ftax.classify_scorecard(sc, runs_dir=None)[0] == ftax.CLASS_BLIND_FIX_LOOP


def test_harness_attribution_routes_to_harness_budget():
    sc = Scorecard(job_id="B2", verdict="STALLED", attribution="HARNESS",
                   evidence={"oracle_status": "unknown"})
    assert ftax.classify_scorecard(sc, runs_dir=None)[0] == ftax.CLASS_HARNESS_BUDGET


def test_coder_idle_is_not_harness_it_is_residue(tmp_path):
    """An idle circuit-breaker is a BUILD/capability event, NOT a harness fault — with no
    oracle/seam/design signal it must fall to the honest UNCLASSIFIED residue, never be
    mislabeled HARNESS (the hand-analysis is explicit idle was not a terminal cause)."""
    runs_dir = _make_run_dir(tmp_path, "r", {"run-fleet-x.log":
        "CIRCUIT BREAKER: agent went idle for 240s\n1 failed, 23 passed\n"})
    sc = _sc("B6", "PARKED-HONEST", "BUILD", {"oracle_status": "failed", "mode": "plan-graph"}, "r")
    assert ftax.classify_scorecard(sc, runs_dir=runs_dir)[0] == ftax.CLASS_UNCLASSIFIED


def test_unclassified_names_itself_a_candidate_new_class():
    sc = Scorecard(job_id="B9", verdict="PARKED-HONEST", attribution="BUILD",
                   evidence={"oracle_status": "failed", "mode": "plan-graph"})
    klass, fp = ftax.classify_scorecard(sc, runs_dir=None)
    assert klass == ftax.CLASS_UNCLASSIFIED
    assert "new leak class" in fp


# ---------------------------------------------------------------------------
# GREEN-side classification (c.1735) — measure what a GREEN actually PROVED
# ---------------------------------------------------------------------------


def test_green_full_coverage_is_verified(tmp_path):
    runs_dir = _oracle_qa_run(tmp_path, "r", {"oracle_coverage": "5/5", "covered": ["c1"], "uncovered": []})
    sc = _sc("B2", "GREEN", "", {"oracle_status": "passed", "mode": "plan-graph"}, "r")
    klass, fp = ftax.classify_scorecard(sc, runs_dir=runs_dir)
    assert klass == ftax.CLASS_GREEN_VERIFIED
    assert "5/5" in fp


def test_green_partial_coverage_is_the_leniency_drift_class(tmp_path):
    runs_dir = _oracle_qa_run(tmp_path, "r", {"oracle_coverage": "3/5", "uncovered": ["c2", "c4"]})
    sc = _sc("B2", "GREEN", "", {"oracle_status": "passed", "mode": "plan-graph"}, "r")
    klass, fp = ftax.classify_scorecard(sc, runs_dir=runs_dir)
    assert klass == ftax.CLASS_GREEN_PARTIAL
    assert "c2" in fp and "c4" in fp


def test_green_unknown_coverage_is_unverified(tmp_path):
    runs_dir = _oracle_qa_run(tmp_path, "r", {"oracle_coverage": "unknown"})
    sc = _sc("B2", "GREEN", "", {"oracle_status": "passed"}, "r")
    assert ftax.classify_scorecard(sc, runs_dir=runs_dir)[0] == ftax.CLASS_GREEN_UNVERIFIED


def test_green_with_no_coverage_stamp_is_unverified():
    """The B2 shape: a GREEN with no #821 sidecar — we cannot say what it proved."""
    sc = Scorecard(job_id="B2", verdict="GREEN", evidence={"oracle_status": "passed"})
    assert ftax.classify_scorecard(sc, runs_dir=None)[0] == ftax.CLASS_GREEN_UNVERIFIED


def test_green_gaming_fingerprint_routes_to_gamed(tmp_path):
    """The OPTIONAL #832/#837 hook: a green-audit sidecar flag surfaces GREEN-GAMED."""
    runs_dir = _make_run_dir(tmp_path, "r", {
        "oracle-qa.json": json.dumps({"oracle_coverage": "5/5"}),
        "green-audit.json": json.dumps({"gamed": True, "reason": "asserts a constant"}),
    })
    sc = _sc("B2", "GREEN", "", {"oracle_status": "passed"}, "r")
    assert ftax.classify_scorecard(sc, runs_dir=runs_dir)[0] == ftax.CLASS_GREEN_GAMED


# ---------------------------------------------------------------------------
# Trend + history (the KPI line)
# ---------------------------------------------------------------------------


def test_trend_first_night_has_no_previous():
    trend = ftax.compute_trend({ftax.CLASS_ORACLE_DEFECT: 3}, history=[])
    assert trend["nights"] == 1
    assert trend["by_class"][ftax.CLASS_ORACLE_DEFECT] == {"current": 3, "previous": None, "delta": None}


def test_trend_computes_night_over_night_delta():
    history = [{"label": "n2", "failure_classes": {ftax.CLASS_ORACLE_DEFECT: 3, ftax.CLASS_INTEGRATION_SEAM: 4}}]
    trend = ftax.compute_trend(
        {ftax.CLASS_ORACLE_DEFECT: 2, ftax.CLASS_INTEGRATION_SEAM: 1}, history=history)
    assert trend["nights"] == 2
    assert trend["previous_label"] == "n2"
    assert trend["by_class"][ftax.CLASS_ORACLE_DEFECT] == {"current": 2, "previous": 3, "delta": -1}
    assert trend["by_class"][ftax.CLASS_INTEGRATION_SEAM] == {"current": 1, "previous": 4, "delta": -3}


def test_load_history_reads_prior_sibling_summaries(tmp_path):
    root = tmp_path / "battery"
    prior = root / "20260709-000000"
    prior.mkdir(parents=True)
    (prior / "battery-summary.json").write_text(json.dumps(
        {"failure_taxonomy": {"failure_classes": {ftax.CLASS_ORACLE_DEFECT: 5}}}
    ), encoding="utf-8")
    current = root / "20260711-000000"
    current.mkdir(parents=True)
    history = ftax.load_history(current)
    assert len(history) == 1
    assert history[0]["label"] == "20260709-000000"
    assert history[0]["failure_classes"][ftax.CLASS_ORACLE_DEFECT] == 5


def test_load_history_excludes_the_current_night(tmp_path):
    root = tmp_path / "battery"
    current = root / "20260711-000000"
    current.mkdir(parents=True)
    (current / "battery-summary.json").write_text(json.dumps(
        {"failure_taxonomy": {"failure_classes": {ftax.CLASS_ORACLE_DEFECT: 9}}}
    ), encoding="utf-8")
    assert ftax.load_history(current) == []


# ---------------------------------------------------------------------------
# Battery-close integration — the summary carries + persists the taxonomy
# ---------------------------------------------------------------------------


def test_summary_classify_populates_block_and_restamps_files(tmp_path):
    cards = [
        Scorecard(job_id="B1", verdict="PARKED-HONEST", attribution="BUILD",
                  evidence={"oracle_status": "not-run", "mode": "flat"}, run_id="r1"),
        Scorecard(job_id="B2", verdict="GREEN", evidence={"oracle_status": "passed"}, run_id="r2"),
    ]
    # Seed the per-job scorecard files as run_battery would have (pre-stamp).
    for c in cards:
        bat.write_scorecard(c, tmp_path / f"{c.job_id}.scorecard.json")

    summary = bat.BatterySummary(scorecards=cards, out_dir=str(tmp_path))
    block = summary.classify(runs_dir=None, out_dir=tmp_path, log=lambda *_: None)

    assert block["schema"] == ftax.TAXONOMY_SCHEMA
    assert block["classifier_advisory"] is True
    d = summary.to_dict()
    assert d["failure_taxonomy"]["failure_classes"][ftax.CLASS_DECOMPOSE_DOWNGRADE] == 1
    assert d["failure_taxonomy"]["green_classes"][ftax.CLASS_GREEN_UNVERIFIED] == 1
    # the per-job files were re-stamped in place (durable artifact carries the advisory class)
    b1 = json.loads((tmp_path / "B1.scorecard.json").read_text(encoding="utf-8"))
    assert b1["evidence"][ftax.EV_FAILURE_CLASS] == ftax.CLASS_DECOMPOSE_DOWNGRADE
    b2 = json.loads((tmp_path / "B2.scorecard.json").read_text(encoding="utf-8"))
    assert b2["evidence"][ftax.EV_GREEN_CLASS] == ftax.CLASS_GREEN_UNVERIFIED


def test_summary_render_carries_the_kpi_line(tmp_path):
    cards = [Scorecard(job_id="B4", verdict="PARKED-HONEST", attribution="BUILD",
                       evidence={"mode": "flat"}, run_id="r")]
    summary = bat.BatterySummary(scorecards=cards, out_dir=str(tmp_path))
    summary.classify(runs_dir=None, out_dir=tmp_path, log=lambda *_: None)
    rendered = summary.render()
    assert "failure-taxonomy:" in rendered
    assert "unclassified:" in rendered


def test_summary_without_classify_omits_the_block_gracefully():
    """A summary that never classified renders + serializes without error (fail-soft)."""
    summary = bat.BatterySummary(scorecards=[
        Scorecard(job_id="B2", verdict="GREEN", evidence={"oracle_status": "passed"})])
    assert summary.to_dict()["failure_taxonomy"] == {}
    assert "failure-taxonomy:" not in summary.render()


@pytest.mark.asyncio
async def test_dry_run_battery_stamps_and_persists_taxonomy(tmp_path):
    """End-to-end through run_battery: the written battery-summary.json carries the
    taxonomy block and the GREEN card is stamped with a green_class."""
    cards = list(bat.load_cards().values())
    b1 = next(c for c in cards if c["id"] == "B1")
    harness = bat.build_dry_run_harness([b1])
    summary = await bat.run_battery(harness, [b1], out_dir=tmp_path, dry_run=True,
                                    log=lambda *_: None)
    written = json.loads((tmp_path / "battery-summary.json").read_text(encoding="utf-8"))
    assert written["failure_taxonomy"]["schema"] == ftax.TAXONOMY_SCHEMA
    assert "classifier_advisory" in written["failure_taxonomy"]
    # the dry-run B1 greens; it carries a green_class stamp (advisory), verdict untouched
    job = written["jobs"][0]
    assert job["verdict"] == "GREEN"
    assert job["evidence"].get(ftax.EV_GREEN_CLASS) in ftax.GREEN_CLASSES
