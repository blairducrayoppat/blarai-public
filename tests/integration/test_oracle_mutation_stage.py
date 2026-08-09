"""#1195 item 2 — the battery-close seam that RUNS #828's oracle mutation audit.

The audit itself is covered by ``shared/tests/test_oracle_mutation.py``. What was missing —
and what these suites lock — is that anything CALLS it. Before #1195 the module had no
production caller and no run dir on this machine carried an ``oracle-mutation.json``, so the
battery could report an exam PASSED without ever establishing the exam COULD fail.

The suites, and what each would catch:

* **Reachability** — battery close actually invokes the stage, and invokes it BEFORE
  ``classify()``. This is the built-but-wired-into-nothing lock: it fails the moment someone
  removes the call, and it is the only test here that would notice the whole feature going
  dark. The ordering half is load-bearing too — the traceability stage runs inside
  ``classify()``, so a stage that ran after it could never supply the ``L4-KILLS`` evidence.
* **Discrimination, through the real entry point** — a sharp exam kills mutants and a vacuous
  one does not, driven through ``audit_green_oracles`` with the REAL audit and REAL pytest
  subprocesses (``@pytest.mark.slow``). The toggle half of security principle 12: the same
  stage over a deliberately vacuous oracle must score 0 and band ``weak``, or a "strong" band
  is not attributable to this instrument.
* **Fail-soft is never fail-open** — each precondition miss produces a sidecar and a stamp
  that reads ``not-measured (<reason>)``. The ``0/0`` the evidence dict carries is a NUMBER,
  and a number invites a reader to treat it as a clean sheet; these assert it never reaches
  the scorecard as one.
* **The advisory invariant** — the stage writes only the reserved keys and cannot move a
  verdict, including when the audit itself misbehaves and tries to.
* **It cannot sink the night** — an audit that raises leaves the stage returning a block and
  the scorecard still stamped.
* **Boundedness** — the stage budget truncates deterministically and stamps the GREENs it
  never reached, and a second pass re-uses banked measured evidence instead of paying twice.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from shared.fleet.acceptance import JOB_ORACLE_PATH_NODE, JOB_ORACLE_PATH_PYTHON
from shared.fleet.oracle_mutation import ORACLE_MUTATION_SIDECAR_NAME, is_measured
from tools.dispatch_harness import battery as bat
from tools.dispatch_harness.green_quality import mutation as mut
from tools.dispatch_harness.scorecard import Scorecard

# ---------------------------------------------------------------------------
# Fixtures — the shapes a real run banks
# ---------------------------------------------------------------------------

#: An exam with teeth: every assertion pins an exact value, so any operator mutation of the
#: feature code flips it RED.
SHARP_ORACLE = '''
from app.calc import add, in_range

def test_add_exact():
    assert add(2, 3) == 5
    assert add(-1, 1) == 0

def test_in_range_boundary():
    assert in_range(5) is True
    assert in_range(10) is False
'''

#: An exam that checks nothing about the code: it calls the functions and asserts a tautology.
#: A vacuous oracle is exactly what this instrument exists to expose.
VACUOUS_ORACLE = '''
from app.calc import add, in_range

def test_it_runs():
    add(2, 3)
    in_range(5)
    assert True
'''

FEATURE_CODE = '''
def add(a, b):
    return a + b


def in_range(n):
    if n < 10:
        return True
    return False
'''


def _delivered_tree(root: Path) -> Path:
    """A minimal python deliverable: an ``app`` package the oracle imports from."""
    app = root / "app"
    app.mkdir(parents=True, exist_ok=True)
    (app / "__init__.py").write_text("", encoding="utf-8")
    (app / "calc.py").write_text(FEATURE_CODE, encoding="utf-8")
    (root / "tests").mkdir(exist_ok=True)
    return root


def _bank_run(runs_dir: Path, run_id: str, oracle: str,
              oracle_path: str = JOB_ORACLE_PATH_PYTHON) -> Path:
    """Bank the seeded oracle the way a dispatch names it in the run dir."""
    d = runs_dir / run_id
    d.mkdir(parents=True, exist_ok=True)
    (d / f"job-oracle-{Path(oracle_path).name}").write_text(oracle, encoding="utf-8")
    return d


def _green(job_id: str = "B1", run_id: str = "RUN1", repo: str = "proj") -> Scorecard:
    return Scorecard(job_id=job_id, verdict="GREEN", attribution="", wall_clock_s=1.0,
                     run_id=run_id, repo=repo)


def _archived(out_dir: Path, slug: str) -> Path:
    """The night's archived deliverable copy — the tree the stage resolves first."""
    tree = out_dir / "repos-archived" / slug
    tree.mkdir(parents=True, exist_ok=True)
    return _delivered_tree(tree)


def _fake_audit(score: str = "8/10", band: str = "adequate", status: str = "run",
                killed: int = 8, ran: int = 10, survivors=None):
    """An audit stand-in with the module's real evidence shape, for the cases that are about
    THIS stage's logic (resolution, budget, stamping) rather than about mutation itself."""
    def _run(config, run_id, repo, rel_path, oracle_code, *, budget_s=0.0, **_):
        ev = {
            "audit": "oracle_mutation", "language": "python", "mutation_audit": status,
            "oracle_mutation_score": score, "oracle_mutation_coverage": band,
            "killed": killed, "survived": ran - killed, "ran": ran, "planned": ran,
            "total_sites": ran, "by_operator": {}, "survivors": survivors or [],
            "targets": ["app/calc.py"], "seed": "abc", "budget_s": budget_s,
        }
        out = Path(config.runs_dir) / run_id / ORACLE_MUTATION_SIDECAR_NAME
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(ev, indent=2), encoding="utf-8")
        return ev
    return _run


# ---------------------------------------------------------------------------
# A. Reachability — the built-but-wired-into-nothing lock
# ---------------------------------------------------------------------------


def test_battery_close_invokes_the_stage():
    """The whole point of #1195 item 2. This fails if the call is ever removed."""
    src = inspect.getsource(bat.run_battery)
    assert "summary.oracle_mutation(" in src, (
        "battery close no longer calls the oracle-mutation stage — the audit is built and "
        "wired into nothing again, which is the exact defect #1195 item 2 closed."
    )


def test_stage_runs_before_classify_so_l4_stays_reachable():
    """``classify()`` runs the traceability stage, whose L4-KILLS rung is the consumer of this
    sidecar. A stage ordered after it could never supply that evidence."""
    src = inspect.getsource(bat.run_battery)
    assert src.index("summary.oracle_mutation(") < src.index("summary.classify("), (
        "the mutation stage must run BEFORE classify() — traceability reads the sidecar there."
    )


def test_combined_pass_also_invokes_the_stage():
    """The ``main`` re-run over the combined scorecard set must not silently skip the audit."""
    assert "summary.oracle_mutation(" in inspect.getsource(bat.main)


def test_summary_carries_the_block_and_the_kpi_line():
    summary = bat.BatterySummary(scorecards=[_green()])
    summary.oracle_mutation_block = mut._block(
        [{"mutation_audit": "run", "ran": 10, "killed": 8, "survived": 2,
          "oracle_mutation_coverage": "adequate"}],
        greens=1, budget_s=900.0, exhausted=False)
    assert summary.to_dict()["oracle_mutation"]["audited"] == 1
    assert "oracle-mutation:" in summary.render()


def test_block_absent_until_the_stage_runs():
    """No silent default: the block is empty, not a zeroed score, before the stage runs."""
    assert bat.BatterySummary(scorecards=[_green()]).to_dict()["oracle_mutation"] == {}


# ---------------------------------------------------------------------------
# B. Discrimination through the REAL entry point (principle 12: engaged + toggled off)
# ---------------------------------------------------------------------------


def _uv_available() -> bool:
    import shutil
    return shutil.which("uv") is not None


@pytest.mark.slow
@pytest.mark.skipif(not _uv_available(), reason="no uv runner for grade-parity subprocesses")
@pytest.mark.parametrize(
    "oracle,expect_kills,expect_band",
    [(SHARP_ORACLE, True, ("strong", "adequate")), (VACUOUS_ORACLE, False, ("weak",))],
)
def test_real_stage_discriminates_sharp_from_vacuous(tmp_path, oracle, expect_kills, expect_band):
    """The REAL audit, REAL mutants, REAL pytest subprocesses, driven through the REAL stage.

    The vacuous half is the toggle: if the sharp exam bands strong but the vacuous one does
    too, the score is not attributable to this instrument at all."""
    runs, out = tmp_path / "runs", tmp_path / "out"
    _bank_run(runs, "RUN1", oracle)
    _archived(out, "proj")
    sc = _green()

    block = mut.audit_green_oracles([sc], runs_dir=runs, out_dir=out, battery_budget_s=600.0)

    banked = json.loads((runs / "RUN1" / ORACLE_MUTATION_SIDECAR_NAME).read_text())
    assert is_measured(banked), f"the audit never counted a mutant: {banked['mutation_audit']}"
    assert (banked["killed"] > 0) is expect_kills
    assert banked["oracle_mutation_coverage"] in expect_band
    assert block["audited"] == 1 and block["not_measured"] == 0
    assert sc.evidence[mut.EV_SCORE] == banked["oracle_mutation_score"]


@pytest.mark.slow
@pytest.mark.skipif(not _uv_available(), reason="no uv runner for grade-parity subprocesses")
def test_real_runner_attribution_reaches_the_l4_rung(tmp_path):
    """#1195 item 3, across BOTH seams with nothing stubbed: the REAL pinned runner
    (``uv run --no-project --with pytest==…``) produces the failure summary, the REAL audit
    parses it into per-mutant attribution, and the REAL traceability stage folds that into
    ``L4-KILLS`` for the criterion whose own test did the killing.

    This exists because the cheaper proofs cannot reach the thing most likely to break. The
    attribution is parsed out of pytest's own stdout, so it depends on what the PINNED runner
    prints — and a sibling test on this module once injected ``sys.executable -m pytest`` in
    place of that command and proved the mutation logic without ever crossing the seam the
    live path crosses. Substituting the runner here would test a different program."""
    from tools.dispatch_harness.green_quality import traceability as trace

    runs, out = tmp_path / "runs", tmp_path / "out"
    run_dir = _bank_run(runs, "RUN1", SHARP_ORACLE)
    _archived(out, "proj")
    # The criteria the exam is graded against: c1's wording names ``add``, whose own test
    # pins exact values, so a mutated ``add`` must take ``test_add_exact`` down with it.
    (run_dir / "acceptance.json").write_text(json.dumps({"spec": {"goal": "g", "criteria": [
        {"id": "c1", "text": "The add function must add two numbers.",
         "tier": "behavior", "check": ""},
    ]}}), encoding="utf-8")
    (run_dir / "import-probe-targets.json").write_text(json.dumps(
        [{"kind": "py", "module": "app.calc", "level": 0, "names": ["add"], "raw": ""}]),
        encoding="utf-8")
    (run_dir / "import-probe-verdict.json").write_text(
        json.dumps({"ok": True, "unresolved": []}), encoding="utf-8")

    mut.audit_green_oracles([_green()], runs_dir=runs, out_dir=out, battery_budget_s=900.0)
    result = trace.assess_run(run_dir)

    banked = json.loads((run_dir / ORACLE_MUTATION_SIDECAR_NAME).read_text())
    assert is_measured(banked), f"the audit never counted a mutant: {banked['mutation_audit']}"
    assert any(m["killed_by"] for m in banked["mutants"]), (
        "the REAL runner's output named no failing test — attribution is parsed from it, so "
        "this is the seam, not a detail")
    assert result.attribution.available, result.attribution.reason
    c1 = next(c for c in result.criteria if c.criterion_id == "c1")
    assert c1.level == trace.LEVEL_KILLS and c1.l4 == trace.L4_KILLED
    assert "test_add_exact" in c1.l4_evidence
    assert "L4 killed:1" in result.fingerprint()


@pytest.mark.slow
@pytest.mark.skipif(not _uv_available(), reason="no uv runner for grade-parity subprocesses")
def test_real_stage_never_writes_to_the_delivered_tree(tmp_path):
    """The audit mutates what it is pointed at; it must be pointed at a COPY. A kill between a
    mutant's write and its restore would otherwise corrupt the night's archived evidence."""
    runs, out = tmp_path / "runs", tmp_path / "out"
    _bank_run(runs, "RUN1", SHARP_ORACLE)
    tree = _archived(out, "proj")
    before = {p.name: p.read_bytes() for p in (tree / "app").iterdir()}

    mut.audit_green_oracles([_green()], runs_dir=runs, out_dir=out, battery_budget_s=600.0)

    assert {p.name: p.read_bytes() for p in (tree / "app").iterdir()} == before
    assert not (tree / JOB_ORACLE_PATH_PYTHON).exists(), (
        "the audit seeded its oracle into the operator's archived tree")


# ---------------------------------------------------------------------------
# C. Fail-soft is never fail-open — an unmeasured audit never renders as a pass
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("setup,reason", [
    (lambda runs, out: None, "skipped-no-run-dir"),
    (lambda runs, out: (runs / "RUN1").mkdir(parents=True), "skipped-no-banked-oracle"),
])
def test_missing_inputs_are_stamped_not_silent(tmp_path, setup, reason):
    runs, out = tmp_path / "runs", tmp_path / "out"
    runs.mkdir(parents=True, exist_ok=True)
    setup(runs, out)
    sc = _green()

    block = mut.audit_green_oracles([sc], runs_dir=runs, out_dir=out)

    assert sc.evidence[mut.EV_STATUS] == reason
    assert sc.evidence[mut.EV_SCORE] == f"not-measured ({reason})"
    assert block["audited"] == 0 and block["not_measured"] == 1


def test_no_delivered_tree_is_not_measured(tmp_path):
    runs, out = tmp_path / "runs", tmp_path / "out"
    _bank_run(runs, "RUN1", SHARP_ORACLE)
    sc = _green()
    mut.audit_green_oracles([sc], runs_dir=runs, out_dir=out)
    assert sc.evidence[mut.EV_STATUS] == "skipped-no-delivered-tree"
    assert "not-measured" in sc.evidence[mut.EV_SCORE]


def test_node_oracle_declines_through_the_real_audit(tmp_path):
    """Exercises the REAL ``run_oracle_mutation_audit`` through the real stage (no subprocess):
    a node exam has no host mutation runner and must decline honestly."""
    runs, out = tmp_path / "runs", tmp_path / "out"
    _bank_run(runs, "RUN1", "// js", oracle_path=JOB_ORACLE_PATH_NODE)
    _archived(out, "proj")
    sc = _green()

    mut.audit_green_oracles([sc], runs_dir=runs, out_dir=out)

    assert sc.evidence[mut.EV_STATUS] == "skipped-no-python-runner"
    assert sc.evidence[mut.EV_SCORE] == "not-measured (skipped-no-python-runner)"
    assert (runs / "RUN1" / ORACLE_MUTATION_SIDECAR_NAME).is_file(), (
        "a run with no sidecar is indistinguishable from one whose audit found nothing")


def test_a_zero_of_zero_never_reaches_the_card_as_a_number(tmp_path):
    """``0/0`` is the shape an audit that ran nothing returns. It must never be stamped as a
    score — the single most repeated fail-open in this codebase."""
    runs, out = tmp_path / "runs", tmp_path / "out"
    _bank_run(runs, "RUN1", SHARP_ORACLE)
    _archived(out, "proj")
    sc = _green()

    mut.audit_green_oracles([sc], runs_dir=runs, out_dir=out,
                            audit=_fake_audit(score="0/0", band="unknown",
                                              status="skipped-no-targets", killed=0, ran=0))

    assert sc.evidence[mut.EV_SCORE] == "not-measured (skipped-no-targets)"
    assert sc.evidence[mut.EV_SCORE] != "0/0"


def test_measured_zero_is_reported_as_a_real_score(tmp_path):
    """The toggle of the case above: an audit that RAN and killed nothing is a genuine finding
    (a blind exam), and must read as ``0/12``, not as not-measured."""
    runs, out = tmp_path / "runs", tmp_path / "out"
    _bank_run(runs, "RUN1", VACUOUS_ORACLE)
    _archived(out, "proj")
    sc = _green()

    block = mut.audit_green_oracles(
        [sc], runs_dir=runs, out_dir=out,
        audit=_fake_audit(score="0/12", band="weak", killed=0, ran=12))

    assert sc.evidence[mut.EV_SCORE] == "0/12"
    assert sc.evidence[mut.EV_COVERAGE] == "weak"
    assert block["audited"] == 1 and block["not_measured"] == 0


def test_kpi_renders_an_entirely_unaudited_night(tmp_path):
    """A night where nothing could be audited must still print a line. Silence there is the
    state that reads as 'nothing to report'."""
    block = mut._block([], greens=3, budget_s=900.0, exhausted=False)
    rendered = "\n".join(mut.render_kpi(block))
    assert "audited 0/3" in rendered and "not-measured=3" in rendered


def test_no_runs_dir_block_names_its_reason():
    block = mut.audit_green_oracles([_green()], runs_dir=None)
    assert block["audited"] == 0 and block["not_measured"] == 1
    assert "runs_dir" in block["reason"]


# ---------------------------------------------------------------------------
# D. Advisory — the stage cannot move a verdict
# ---------------------------------------------------------------------------


def test_only_reserved_keys_are_written(tmp_path):
    runs, out = tmp_path / "runs", tmp_path / "out"
    _bank_run(runs, "RUN1", SHARP_ORACLE)
    _archived(out, "proj")
    sc = _green()
    sc.evidence = {"mode": "plan-graph"}

    mut.audit_green_oracles([sc], runs_dir=runs, out_dir=out,
                            audit=_fake_audit(survivors=[{"operator": "boundary",
                                                          "file": "app/calc.py", "line": 6}]))

    assert sc.evidence["mode"] == "plan-graph"  # pre-existing evidence untouched
    assert set(sc.evidence) - {"mode"} <= mut.RESERVED_EVIDENCE_KEYS
    assert sc.evidence[mut.EV_SURVIVORS] == ["boundary app/calc.py:6"]


def test_a_misbehaving_audit_cannot_move_the_verdict(tmp_path):
    """The advisory lock, driven: an audit that reaches back and rewrites the card is undone."""
    runs, out = tmp_path / "runs", tmp_path / "out"
    _bank_run(runs, "RUN1", SHARP_ORACLE)
    _archived(out, "proj")
    sc = _green()

    def _rogue(config, run_id, repo, rel_path, oracle_code, *, budget_s=0.0, **_):
        sc.verdict, sc.attribution = "FALSE-DONE", "VERIFY"
        return _fake_audit()(config, run_id, repo, rel_path, oracle_code, budget_s=budget_s)

    mut.audit_green_oracles([sc], runs_dir=runs, out_dir=out, audit=_rogue)

    assert (sc.verdict, sc.attribution) == ("GREEN", "")


def test_non_green_cards_are_never_audited(tmp_path):
    runs, out = tmp_path / "runs", tmp_path / "out"
    parked = Scorecard(job_id="B2", verdict="PARKED-HONEST", attribution="BUILD",
                       wall_clock_s=1.0, run_id="RUN2", repo="proj")
    called: list[str] = []

    def _spy(config, run_id, *a, **k):
        called.append(run_id)
        return _fake_audit()(config, run_id, *a, **k)

    block = mut.audit_green_oracles([parked], runs_dir=runs, out_dir=out, audit=_spy)

    assert called == [] and block["greens"] == 0
    assert mut.EV_SCORE not in (parked.evidence or {})


# ---------------------------------------------------------------------------
# E. It cannot sink the night
# ---------------------------------------------------------------------------


def test_a_raising_audit_leaves_the_card_stamped_and_the_stage_returning(tmp_path):
    runs, out = tmp_path / "runs", tmp_path / "out"
    _bank_run(runs, "RUN1", SHARP_ORACLE)
    _archived(out, "proj")
    sc = _green()

    def _boom(*a, **k):
        raise RuntimeError("mutation exploded")

    block = mut.audit_green_oracles([sc], runs_dir=runs, out_dir=out, audit=_boom)

    assert block["not_measured"] == 1
    assert "skipped-stage-error-RuntimeError" in sc.evidence[mut.EV_STATUS]
    assert "not-measured" in sc.evidence[mut.EV_SCORE]


def test_battery_method_survives_an_unimportable_stage(monkeypatch):
    """The import lives inside the guard: a syntax error in this stage must not take down the
    battery-summary write. Matches the guard ``classify()`` grew for the same reason."""
    import builtins
    real_import = builtins.__import__

    def _fail(name, *a, **k):
        if name.endswith("green_quality.mutation") or name.endswith("green_quality"):
            raise ImportError("stage unavailable")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _fail)
    summary = bat.BatterySummary(scorecards=[_green()])
    assert summary.oracle_mutation(runs_dir=None, log=lambda _m: None) == {}


def test_battery_method_runs_the_stage_for_real(tmp_path):
    """The ``BatterySummary`` method is the seam battery close uses; drive IT, not the helper.

    Uses a node exam so the REAL audit is reached and declines without spawning a pytest
    subprocess per mutant — the whole real path, at fast-tier cost. The mutants themselves are
    proven in the ``@pytest.mark.slow`` discrimination suite above."""
    runs, out = tmp_path / "runs", tmp_path / "out"
    _bank_run(runs, "RUN1", "// js", oracle_path=JOB_ORACLE_PATH_NODE)
    _archived(out, "proj")
    sc = _green()
    summary = bat.BatterySummary(scorecards=[sc], out_dir=str(out))

    block = summary.oracle_mutation(runs_dir=runs, out_dir=out)

    assert block["greens"] == 1
    assert sc.evidence[mut.EV_STATUS] == "skipped-no-python-runner"
    assert summary.to_dict()["oracle_mutation"] is block


# ---------------------------------------------------------------------------
# F. Bounded — the stage cannot extend the night without a ceiling
# ---------------------------------------------------------------------------


def test_battery_budget_truncates_and_stamps_the_greens_it_never_reached(tmp_path):
    runs, out = tmp_path / "runs", tmp_path / "out"
    cards = []
    for i in (1, 2, 3):
        _bank_run(runs, f"RUN{i}", SHARP_ORACLE)
        cards.append(_green(job_id=f"B{i}", run_id=f"RUN{i}"))
    _archived(out, "proj")

    ticks = iter([0.0, 0.0, 0.0, 999.0, 999.0, 999.0, 999.0])

    block = mut.audit_green_oracles(
        cards, runs_dir=runs, out_dir=out, battery_budget_s=10.0,
        clock=lambda: next(ticks), audit=_fake_audit())

    assert block["budget_exhausted"] is True
    assert block["audited"] == 1 and block["not_measured"] == 2
    skipped = [c for c in cards if c.evidence[mut.EV_STATUS] == mut.STATUS_BATTERY_BUDGET]
    assert len(skipped) == 2
    assert all("not-measured" in c.evidence[mut.EV_SCORE] for c in skipped)


def test_second_pass_reuses_a_measured_sidecar_instead_of_re_auditing(tmp_path):
    """The combined-set re-run must not pay for the whole night twice."""
    runs, out = tmp_path / "runs", tmp_path / "out"
    _bank_run(runs, "RUN1", SHARP_ORACLE)
    _archived(out, "proj")
    calls: list[str] = []

    def _counting(config, run_id, *a, **k):
        calls.append(run_id)
        return _fake_audit()(config, run_id, *a, **k)

    first, second = _green(), _green()
    mut.audit_green_oracles([first], runs_dir=runs, out_dir=out, audit=_counting)
    mut.audit_green_oracles([second], runs_dir=runs, out_dir=out, audit=_counting)

    assert calls == ["RUN1"], "the second pass re-ran the audit instead of reusing the sidecar"
    assert second.evidence[mut.EV_SCORE] == first.evidence[mut.EV_SCORE]


def test_an_unmeasured_sidecar_is_retried_not_frozen(tmp_path):
    """A miss caused by a tree that was not archived yet must not freeze into a permanent
    not-measured stamp — only a MEASURED sidecar is reusable."""
    runs, out = tmp_path / "runs", tmp_path / "out"
    run_dir = _bank_run(runs, "RUN1", SHARP_ORACLE)
    _archived(out, "proj")
    (run_dir / ORACLE_MUTATION_SIDECAR_NAME).write_text(
        json.dumps({"mutation_audit": "skipped-no-delivered-tree", "ran": 0}), encoding="utf-8")
    sc = _green()

    mut.audit_green_oracles([sc], runs_dir=runs, out_dir=out, audit=_fake_audit())

    assert sc.evidence[mut.EV_SCORE] == "8/10"


def test_a_fresh_attempt_overwrites_a_stale_unmeasured_sidecar(tmp_path):
    """The banked sidecar must record THIS attempt, not an earlier miss. A stale
    not-measured file surviving a successful re-audit would misreport the night."""
    runs, out = tmp_path / "runs", tmp_path / "out"
    run_dir = _bank_run(runs, "RUN1", SHARP_ORACLE)
    _archived(out, "proj")
    (run_dir / ORACLE_MUTATION_SIDECAR_NAME).write_text(
        json.dumps({"mutation_audit": "skipped-no-delivered-tree", "ran": 0}), encoding="utf-8")

    mut.audit_green_oracles([_green()], runs_dir=runs, out_dir=out, audit=_fake_audit())

    banked = json.loads((run_dir / ORACLE_MUTATION_SIDECAR_NAME).read_text())
    assert banked["mutation_audit"] == "run" and banked["oracle_mutation_score"] == "8/10"


def test_stage_budget_constant_is_registered():
    from shared.timeout_registry import registry_names
    assert ("tools.dispatch_harness.green_quality.mutation:"
            "ORACLE_MUTATION_BATTERY_BUDGET_S") in registry_names()


def test_oversized_tree_is_declined_rather_than_copied(tmp_path, monkeypatch):
    runs, out = tmp_path / "runs", tmp_path / "out"
    _bank_run(runs, "RUN1", SHARP_ORACLE)
    _archived(out, "proj")
    monkeypatch.setattr(mut, "_MAX_COPY_FILES", 1)
    sc = _green()

    mut.audit_green_oracles([sc], runs_dir=runs, out_dir=out)

    assert sc.evidence[mut.EV_STATUS] == "skipped-tree-too-large"


# ---------------------------------------------------------------------------
# G. Resolution details the seam depends on
# ---------------------------------------------------------------------------


def test_oracle_rel_path_resolves_against_the_owning_constant():
    assert mut._oracle_rel_path("job-oracle-test_job_acceptance.py") == JOB_ORACLE_PATH_PYTHON
    assert mut._oracle_rel_path("job-oracle-acceptance.job.test.mjs") == JOB_ORACLE_PATH_NODE
    assert mut._oracle_rel_path("job-oracle-something_else.py") is None


def test_live_sandbox_is_the_fallback_when_nothing_was_archived(tmp_path):
    runs, projects = tmp_path / "runs", tmp_path / "projects"
    _bank_run(runs, "RUN1", SHARP_ORACLE)
    _delivered_tree(projects / "proj")
    sc = _green()

    mut.audit_green_oracles([sc], runs_dir=runs, out_dir=tmp_path / "out",
                            projects_dir=projects, audit=_fake_audit())

    assert sc.evidence[mut.EV_SCORE] == "8/10"
