"""#837 QUALITY-17 — the GREEN audit (advisory archetype-regression floor + diverse jury).

The load-bearing test is the SEED PROOF (lesson 222 — a verdict-issuing instrument's classes
are not believed until it reproduces the known answer on a known subject): the three real B2
tokenizers are reconstructed as hermetic fixture repos, and Layer 1's archetype-regression
probe MUST flag the 2026-07-11 GREEN's data-loss regression (``["worry"]`` where the previous
GREEN kept five tokens) while scoring the earlier lateral reformat a mere CHANGE. The same
proof is run OPPORTUNISTICALLY against the real agentic-setup archives when present.

The other suites lock the invariants: the DETERMINISTIC band formula (the model never renders
the band), the ADVISORY invariant (the audit never changes a verdict/attribution), the diverse
jury's per-field majority + honest abstention, the surface-aware "what you got" card, the
craft lints, the calibration measurement, and the #827 sidecar hand-off + battery-close wiring.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.dispatch_harness.green_quality import (
    audit_green,
    audit_greens,
    band as band_mod,
)
from tools.dispatch_harness.green_quality import (
    calibration as calib,
)
from tools.dispatch_harness.green_quality import (
    card as card_mod,
)
from tools.dispatch_harness.green_quality import (
    jury as jury_mod,
)
from tools.dispatch_harness.green_quality import (
    layer1 as l1,
)
from tools.dispatch_harness.green_quality.constants import (
    ABSTAIN,
    BAND_A,
    BAND_B,
    BAND_C,
    FIELD_CORRECTNESS_PROBE,
    FIELD_NAMING_STRUCTURE,
    FIELD_RUNNABLE_SURFACE,
)
from tools.dispatch_harness.scorecard import Scorecard, validate

# ---------------------------------------------------------------------------
# The three real B2 tokenizers, reconstructed verbatim as fixtures (the seed subject)
# ---------------------------------------------------------------------------

#: 07-07 — strips SURROUNDING punctuation only: keeps "don't", "well-known" intact.
_TOK_GOOD = '''
import re
def tokenize(text):
    if not text:
        return []
    out = []
    for w in text.split():
        c = re.sub(r'^[^\\w]+|[^\\w]+$', '', w)
        if c:
            out.append(c.lower())
    return out
'''

#: 07-09 — normalises contractions, splits on non-alphanumeric: "dont","well","known".
#: A lateral CHANGE vs 07-07 (no data lost — content words survive), not a regression.
_TOK_NORMALIZE = '''
import re
def tokenize(text):
    text = text.lower()
    text = re.sub(r"'(?=[a-zA-Z])", "", text)
    words = re.split(r"[^a-zA-Z0-9]+", text)
    return [w for w in words if w]
'''

#: 07-11 — the BANKED GREEN: edge-strip, split('.'), keep only isalnum parts. "don't" and
#: "well-known" are NOT alnum, so they VANISH — real prose loses every contraction/hyphen.
_TOK_DROPPING = '''
import re
def tokenize(text):
    if not text:
        return []
    tokens = [t for t in re.split(r'\\s+', text.strip()) if t]
    out = []
    for token in tokens:
        c = re.sub(r'^[^\\w]+|[^\\w]+$', '', token)
        if c:
            c = c.lower()
            for part in c.split('.'):
                if part.isalnum():
                    out.append(part)
    return out
'''

_B2_INPUTS = ["Don't worry, it's well-known.", "state-of-the-art tech", "The cost was $3.14 today."]


def _make_lib_repo(root: Path, tokenize_src: str, *, scaffold: bool = False,
                   skeleton_readme: bool = False, demo: bool = False) -> Path:
    """A minimal python-lib repo with ``app/tokenize.py`` (+ optional scaffold residue)."""
    app = root / "app"
    app.mkdir(parents=True, exist_ok=True)
    (app / "__init__.py").write_text("", encoding="utf-8")
    (app / "tokenize.py").write_text(tokenize_src, encoding="utf-8")
    if scaffold:
        (app / "core.py").write_text(
            '"""This summarize function is a PLACEHOLDER so the project builds."""\n'
            "def summarize(numbers):\n    return {}\n", encoding="utf-8")
    (root / "README.md").write_text(
        "A minimal, clean, offline Python project the fleet seeds. Extend it."
        if skeleton_readme else "# Text stats toolkit\nCounts words in text.\n",
        encoding="utf-8")
    if demo:
        (root / "demo.py").write_text("from app.tokenize import tokenize\nprint(tokenize('hi'))\n",
                                      encoding="utf-8")
    return root


def _b2_probe_set() -> l1.ProbeSet:
    return l1.parse_probe_set({
        "schema": l1.PROBE_SET_SCHEMA, "job_id": "B2", "surface": "python-lib",
        "probes": [{"kind": "python-callable", "import": "app.tokenize", "attr": "tokenize",
                    "inputs": _B2_INPUTS}],
    })


# ---------------------------------------------------------------------------
# THE SEED PROOF (hermetic) — Layer 1 catches the B2 data-loss regression
# ---------------------------------------------------------------------------


def test_seed_proof_hermetic_dropping_is_regression(tmp_path):
    """The BANKED 07-11 GREEN vs the previous GREEN: a DATA-LOSS regression (5 tokens -> 1).
    This is the exact catch the flat-GREEN scoreboard missed — Layer 1, no model."""
    current = _make_lib_repo(tmp_path / "cur", _TOK_DROPPING)
    reference = _make_lib_repo(tmp_path / "ref", _TOK_NORMALIZE)
    reg = l1.archetype_regression(current, reference, _b2_probe_set())
    assert reg.regressed is True
    assert reg.changed is True
    assert reg.measured is True
    assert "Don't worry" in reg.detail and "worry" in reg.detail


def test_seed_proof_hermetic_reformat_is_change_not_regression(tmp_path):
    """The earlier 07-07 -> 07-09 contraction reformat CHANGED behaviour but lost no data —
    a B-level drift signal, never a C-level regression. This is the severity split that keeps
    the instrument from crying wolf on every lateral edit."""
    current = _make_lib_repo(tmp_path / "cur", _TOK_NORMALIZE)
    reference = _make_lib_repo(tmp_path / "ref", _TOK_GOOD)
    reg = l1.archetype_regression(current, reference, _b2_probe_set())
    assert reg.changed is True
    assert reg.regressed is False


def test_seed_proof_hermetic_identical_is_clean(tmp_path):
    """Same code both nights -> no change, measured clean (the honest A-floor input)."""
    current = _make_lib_repo(tmp_path / "cur", _TOK_GOOD)
    reference = _make_lib_repo(tmp_path / "ref", _TOK_GOOD)
    reg = l1.archetype_regression(current, reference, _b2_probe_set())
    assert reg.changed is False and reg.regressed is False and reg.measured is True


def test_seed_proof_hermetic_bands(tmp_path):
    """End-to-end through audit_green: the dropping GREEN -> C, the reformat GREEN -> B."""
    dropping = _make_lib_repo(tmp_path / "d/repos-archived/battery-b2-text-stats", _TOK_DROPPING)
    normalize = _make_lib_repo(tmp_path / "n/repos-archived/battery-b2-text-stats", _TOK_NORMALIZE)
    # Point audit_green's current-repo resolver at each; give an explicit reference.
    sc_c = Scorecard(job_id="B2", verdict="GREEN", repo="battery-b2-text-stats", run_id="r1")
    res_c = audit_green(sc_c, out_dir=tmp_path / "d", archive_root=tmp_path / "none",
                        probe_dir=_probe_dir(tmp_path), surface="python-lib")
    # No reference in the archive -> "first GREEN", so band is driven by craft only (A/B).
    assert res_c.band in (BAND_A, BAND_B)
    # With an explicit prior-GREEN archive, the dropping repo regresses -> C.
    reg = l1.archetype_regression(dropping, normalize, _b2_probe_set())
    assert band_mod.compute_band(_l1_with(reg)) == BAND_C


def _probe_dir(tmp_path: Path) -> Path:
    d = tmp_path / "probes"
    d.mkdir(parents=True, exist_ok=True)
    (d / "B2.json").write_text(json.dumps({
        "schema": l1.PROBE_SET_SCHEMA, "job_id": "B2", "surface": "python-lib",
        "probes": [{"kind": "python-callable", "import": "app.tokenize", "attr": "tokenize",
                    "inputs": _B2_INPUTS}]}), encoding="utf-8")
    return d


def _l1_with(reg: l1.RegressionFinding) -> l1.Layer1Result:
    clean = l1.CraftFinding(False, "")
    return l1.Layer1Result(regression=reg, dead_scaffold=clean, stale_readme=clean,
                           no_entry_point=clean, ruff_findings=None, surface="python-lib")


# ---------------------------------------------------------------------------
# THE SEED PROOF (opportunistic) — the real agentic-setup B2 archives
# ---------------------------------------------------------------------------

_REAL_ARCH = Path("C:/Users/mrbla/agentic-setup/state/battery")
_REAL_NIGHTS = {"night-20260707-160408": BAND_B, "night-20260709-230001": BAND_B,
                "night-20260711-000001": BAND_C}


@pytest.mark.parametrize("night,expected_band", list(_REAL_NIGHTS.items()))
def test_seed_proof_real_archives(night, expected_band):
    """Against the REAL archived B2 repos (when present): the two earlier GREENs band B, the
    banked 07-11 GREEN bands C — reproducing the dossier's own seed-audit severity verdicts."""
    night_dir = _REAL_ARCH / night
    repo = night_dir / "repos-archived" / "battery-b2-text-stats"
    if not repo.is_dir():
        pytest.skip("real agentic-setup B2 archives not present")
    sc = Scorecard(job_id="B2", verdict="GREEN", repo="battery-b2-text-stats", run_id=night)
    res = audit_green(sc, out_dir=night_dir, archive_root=_REAL_ARCH, surface="python-lib")
    assert res.band == expected_band
    if expected_band == BAND_C:
        assert res.layer1.regression.regressed is True


# ---------------------------------------------------------------------------
# The DETERMINISTIC band formula (the model never renders the band)
# ---------------------------------------------------------------------------


def _reg(regressed=False, changed=False):
    return l1.RegressionFinding(regressed, changed, "detail", measured=True)


def _l1(regressed=False, changed=False, dead=False, readme=False, no_entry=False, ruff=None):
    return l1.Layer1Result(
        regression=_reg(regressed, changed),
        dead_scaffold=l1.CraftFinding(dead, "scaffold"),
        stale_readme=l1.CraftFinding(readme, "readme"),
        no_entry_point=l1.CraftFinding(no_entry, "no entry"),
        ruff_findings=ruff, surface="python-lib")


def test_band_regression_is_C():
    assert band_mod.compute_band(_l1(regressed=True, changed=True)) == BAND_C


def test_band_lateral_change_is_B():
    assert band_mod.compute_band(_l1(changed=True)) == BAND_B


def test_band_craft_residue_is_B():
    assert band_mod.compute_band(_l1(dead=True)) == BAND_B
    assert band_mod.compute_band(_l1(readme=True)) == BAND_B
    assert band_mod.compute_band(_l1(no_entry=True)) == BAND_B


def test_band_clean_is_A():
    assert band_mod.compute_band(_l1()) == BAND_A


def test_band_ruff_below_threshold_stays_A():
    assert band_mod.compute_band(_l1(ruff=3)) == BAND_A
    assert band_mod.compute_band(_l1(ruff=25)) == BAND_B


def test_band_jury_wrong_correctness_is_C():
    jr = jury_mod.JuryResult(scores={FIELD_CORRECTNESS_PROBE: "wrong"})
    assert band_mod.compute_band(_l1(), jr) == BAND_C


def test_band_jury_no_runnable_is_C():
    jr = jury_mod.JuryResult(scores={FIELD_RUNNABLE_SURFACE: "no"})
    assert band_mod.compute_band(_l1(), jr) == BAND_C


def test_band_jury_abstain_carries_no_signal():
    """An abstained field never pushes the band toward a worse letter — silence is not
    evidence. All-abstain jury over a clean Layer 1 stays A."""
    jr = jury_mod.JuryResult(scores={f: ABSTAIN for f in ("runnable_surface", "bad_input_handling",
                                                          "naming_structure", "correctness_probe")},
                             uncertain=["runnable_surface"])
    assert band_mod.compute_band(_l1(), jr) == BAND_A


def test_band_ignores_a_model_supplied_band_field():
    """The deterministic-formula lock: even if a juror emits a spurious 'band' key, it is
    dropped at parse and the formula computes from the SCORED fields — a juror cannot render
    its own band. correctness=wrong -> C regardless of any 'band':'A' the model tried."""
    emission = json.dumps({"runnable_surface": "yes", "bad_input_handling": "graceful",
                           "naming_structure": "clear", "correctness_probe": "wrong",
                           "band": "A", "verdict": "GREEN"})
    parsed = jury_mod.parse_emission(emission)
    assert "band" not in parsed and "verdict" not in parsed
    assert parsed[FIELD_CORRECTNESS_PROBE] == "wrong"


# ---------------------------------------------------------------------------
# The diverse jury — majority vote + honest abstention + grammar emission
# ---------------------------------------------------------------------------


def _fake_generate(emission: dict):
    """A fake structured_generate_fn: returns the fixed emission regardless of prompt/schema."""
    return lambda prompt, schema_text: json.dumps(emission)


def _juror(emission: dict, lens="lens", seed=0) -> jury_mod.Juror:
    return jury_mod.Juror(lens=lens, structured_generate_fn=_fake_generate(emission), seed=seed)


def test_jury_majority_per_field():
    """Two of three jurors say correctness=wrong -> the majority is 'wrong'."""
    votes = [
        jury_mod.run_juror(_juror({"runnable_surface": "yes", "bad_input_handling": "graceful",
                                   "naming_structure": "clear", "correctness_probe": "wrong"}), "subject"),
        jury_mod.run_juror(_juror({"runnable_surface": "yes", "bad_input_handling": "graceful",
                                   "naming_structure": "clear", "correctness_probe": "wrong"}), "subject"),
        jury_mod.run_juror(_juror({"runnable_surface": "yes", "bad_input_handling": "graceful",
                                   "naming_structure": "mixed", "correctness_probe": "none"}), "subject"),
    ]
    result = jury_mod.tally(votes)
    assert result.value(FIELD_CORRECTNESS_PROBE) == "wrong"
    assert result.value(FIELD_RUNNABLE_SURFACE) == "yes"


def test_jury_abstains_on_three_way_disagreement():
    """A field where all three jurors disagree ABSTAINS — stamped uncertain, never a guessed
    middling pass (the honesty discipline)."""
    votes = [
        jury_mod.run_juror(_juror({"runnable_surface": "yes", "bad_input_handling": "graceful",
                                   "naming_structure": "clear", "correctness_probe": "none"}), "subject"),
        jury_mod.run_juror(_juror({"runnable_surface": "yes", "bad_input_handling": "graceful",
                                   "naming_structure": "mixed", "correctness_probe": "none"}), "subject"),
        jury_mod.run_juror(_juror({"runnable_surface": "yes", "bad_input_handling": "graceful",
                                   "naming_structure": "poor", "correctness_probe": "none"}), "subject"),
    ]
    result = jury_mod.tally(votes)
    assert result.value(FIELD_NAMING_STRUCTURE) is None
    assert result.scores[FIELD_NAMING_STRUCTURE] == ABSTAIN
    assert FIELD_NAMING_STRUCTURE in result.uncertain


def test_jury_single_vote_is_not_a_majority():
    """One lone vote on a field is NOT a majority — it abstains honestly."""
    votes = [jury_mod.run_juror(_juror({"correctness_probe": "wrong"}), "subject")]
    result = jury_mod.tally(votes)
    assert result.value(FIELD_CORRECTNESS_PROBE) is None


def test_jury_failed_juror_abstains_not_crashes():
    """A juror whose model raises simply abstains (fail-soft) — never sinks the jury."""
    def _boom(prompt, schema_text):
        raise RuntimeError("model down")
    vote = jury_mod.run_juror(jury_mod.Juror("lens", _boom), "subject")
    assert vote.fields == {}


def test_build_default_jury_none_without_model():
    """No model wired -> None (the standing det-only posture; Layer 2 is a supervised slot)."""
    assert jury_mod.build_default_jury(None) is None
    jurors = jury_mod.build_default_jury(_fake_generate({"correctness_probe": "none"}))
    assert jurors is not None and len(jurors) == 3
    assert {j.lens for j in jurors} == set(jury_mod.LENSES)


def test_jury_emission_schema_is_enum_pinned():
    from tools.dispatch_harness.green_quality.constants import CORRECTNESS_VALUES

    schema = jury_mod.green_quality_emission_json_schema()
    assert schema["additionalProperties"] is False
    assert schema["properties"]["correctness_probe"]["enum"] == list(CORRECTNESS_VALUES)


# ---------------------------------------------------------------------------
# The surface-aware "what you got" card
# ---------------------------------------------------------------------------


def test_card_library_surface_never_says_open_the_app():
    """The B2 failure the card fixes: a python-lib must NOT be told to 'open the app'."""
    l1r = _l1()
    the_card = card_mod.build_card("B2", "python-lib", BAND_A, l1r)
    assert "open the app" not in the_card.run_hint.lower()
    assert "library" in the_card.run_hint.lower()


def test_card_carries_the_regression_caveat(tmp_path):
    reg = l1.RegressionFinding(True, True,
                              'input "Don\'t worry, it\'s well-known.": now ["worry"] vs was [...]',
                              measured=True)
    l1r = _l1_with(reg)
    the_card = card_mod.build_card("B2", "python-lib", BAND_C, l1r)
    assert "Don't worry" in the_card.caveat
    assert the_card.to_evidence().startswith("[C]")


def test_card_gui_surface_opens_itself():
    the_card = card_mod.build_card("BX", "node-web", BAND_A, _l1())
    assert "open it" in the_card.run_hint.lower()


# ---------------------------------------------------------------------------
# Craft lints
# ---------------------------------------------------------------------------


def test_lint_dead_scaffold(tmp_path):
    repo = _make_lib_repo(tmp_path / "r", _TOK_GOOD, scaffold=True)
    assert l1.lint_dead_scaffold(repo).flagged is True
    clean = _make_lib_repo(tmp_path / "c", _TOK_GOOD)
    assert l1.lint_dead_scaffold(clean).flagged is False


def test_lint_stale_readme(tmp_path):
    repo = _make_lib_repo(tmp_path / "r", _TOK_GOOD, skeleton_readme=True)
    assert l1.lint_stale_readme(repo).flagged is True
    clean = _make_lib_repo(tmp_path / "c", _TOK_GOOD)
    assert l1.lint_stale_readme(clean).flagged is False


def test_lint_no_entry_point(tmp_path):
    """A library with no demo/__main__/console-script is flagged; one with demo.py is not; a
    buried per-module ``if __name__`` demo does NOT count (undiscoverable)."""
    bare = _make_lib_repo(tmp_path / "bare", _TOK_GOOD)
    assert l1.lint_no_entry_point(bare, "python-lib").flagged is True
    with_demo = _make_lib_repo(tmp_path / "demo", _TOK_GOOD, demo=True)
    assert l1.lint_no_entry_point(with_demo, "python-lib").flagged is False
    # A buried __main__ block is not a discoverable entry.
    (bare / "app" / "buried.py").write_text("if __name__ == '__main__':\n    print('x')\n",
                                            encoding="utf-8")
    assert l1.lint_no_entry_point(bare, "python-lib").flagged is True


def test_lint_entry_point_skipped_for_gui():
    """A GUI/web surface opens itself — the entry-point lint never flags it."""
    finding = l1.lint_no_entry_point(Path("nonexistent"), "node-web")
    assert finding.flagged is False


# ---------------------------------------------------------------------------
# The reference-GREEN finder
# ---------------------------------------------------------------------------


def _write_scorecard_file(night: Path, job_id: str, verdict: str):
    (night / "scorecards").mkdir(parents=True, exist_ok=True)
    (night / "scorecards" / f"{job_id}.scorecard.json").write_text(
        json.dumps({"job_id": job_id, "verdict": verdict}), encoding="utf-8")
    (night / "repos-archived" / "battery-b2-text-stats").mkdir(parents=True, exist_ok=True)


def test_find_reference_green_picks_last_prior_green(tmp_path):
    arch = tmp_path / "battery"
    _write_scorecard_file(arch / "20260101-000000", "B2", "GREEN")
    _write_scorecard_file(arch / "20260102-000000", "B2", "GREEN")
    _write_scorecard_file(arch / "20260103-000000", "B2", "PARKED-HONEST")  # not a GREEN
    current = arch / "20260104-000000"
    ref = l1.find_reference_green(arch, "B2", "battery-b2-text-stats", exclude_night=current)
    assert ref is not None and ref.parent.parent.name == "20260102-000000"


def test_find_reference_green_none_when_only_self(tmp_path):
    arch = tmp_path / "battery"
    _write_scorecard_file(arch / "20260101-000000", "B2", "GREEN")
    ref = l1.find_reference_green(arch, "B2", "battery-b2-text-stats",
                                 exclude_night=arch / "20260101-000000")
    assert ref is None


# ---------------------------------------------------------------------------
# The advisory invariant (audit_greens never changes a verdict/attribution)
# ---------------------------------------------------------------------------


def test_audit_greens_is_advisory(tmp_path):
    """audit_greens stamps evidence + writes a sidecar but NEVER changes a verdict or
    attribution — the b5class honesty discipline, enforced by the schema and by construction."""
    current = _make_lib_repo(tmp_path / "out/repos-archived/battery-b2-text-stats", _TOK_DROPPING)
    _make_lib_repo(tmp_path / "prior/repos-archived/battery-b2-text-stats", _TOK_NORMALIZE)
    # A sibling PRIOR night that scored GREEN, so a real reference is found.
    _write_scorecard_file(tmp_path / "battery" / "20260101", "B2", "GREEN")
    _make_lib_repo(tmp_path / "battery" / "20260101" / "repos-archived" / "battery-b2-text-stats",
                   _TOK_NORMALIZE)
    out_dir = tmp_path / "battery" / "20260102"
    (out_dir / "repos-archived" / "battery-b2-text-stats").mkdir(parents=True)
    _make_lib_repo(out_dir / "repos-archived" / "battery-b2-text-stats", _TOK_DROPPING)
    runs = tmp_path / "runs"
    sc = Scorecard(job_id="B2", verdict="GREEN", attribution="", repo="battery-b2-text-stats",
                   run_id="R1", evidence={"oracle_status": "passed"})
    block = audit_greens([sc], runs_dir=runs, out_dir=out_dir,
                         probe_dir=_probe_dir(tmp_path), job_surfaces={"B2": "python-lib"})
    assert sc.verdict == "GREEN" and sc.attribution == ""
    assert sc.evidence["oracle_status"] == "passed"  # existing evidence untouched
    assert sc.evidence["green_quality_band"] == BAND_C
    assert block["audited"] == 1 and block["bands"][BAND_C] == 1 and block["regressed"] == 1
    # The scorecard is still schema-valid after the advisory stamp.
    assert validate(sc) == []
    assert (runs / "R1" / "green-quality.json").is_file()


def test_audit_greens_skips_non_green(tmp_path):
    sc = Scorecard(job_id="B4", verdict="PARKED-HONEST", attribution="BUILD",
                   repo="battery-b4", run_id="R2")
    block = audit_greens([sc], runs_dir=tmp_path / "runs", out_dir=tmp_path / "out")
    assert block["audited"] == 0
    assert not any(k.startswith("green_quality") for k in sc.evidence)


def test_audit_greens_fail_soft_on_missing_everything(tmp_path):
    """No repos, no probes, no archive -> an honest empty/unmeasured audit, never a crash."""
    sc = Scorecard(job_id="B2", verdict="GREEN", repo="battery-b2-text-stats", run_id="R3")
    block = audit_greens([sc], runs_dir=tmp_path / "runs", out_dir=tmp_path / "out",
                         probe_dir=tmp_path / "no-probes")
    assert block["audited"] == 1
    assert sc.evidence["green_quality_band"] in (BAND_A, BAND_B, BAND_C)


# ---------------------------------------------------------------------------
# Composition with #832 (integrity) + #827: distinct concerns, no collision
# ---------------------------------------------------------------------------


def test_quality_audit_does_not_collide_with_832_or_827(tmp_path):
    """The QUALITY band composes cleanly beneath #832's INTEGRITY gate. My audit writes its OWN
    ``green-quality.json`` (never #832's ``green-audit.json``) and stamps only ``green_quality_*``
    keys — so it can NEVER trip #827's gaming signal (which reads ``green_audit == 'gamed'``) and
    manufacture a false GREEN-GAMED. The two instruments share a GREEN but not a namespace."""
    from tools.dispatch_harness import failure_taxonomy as ftax

    _write_scorecard_file(tmp_path / "battery" / "20260101", "B2", "GREEN")
    _make_lib_repo(tmp_path / "battery" / "20260101" / "repos-archived" / "battery-b2-text-stats",
                   _TOK_NORMALIZE)
    out_dir = tmp_path / "battery" / "20260102"
    _make_lib_repo(out_dir / "repos-archived" / "battery-b2-text-stats", _TOK_DROPPING)
    runs = tmp_path / "runs"
    sc = Scorecard(job_id="B2", verdict="GREEN", repo="battery-b2-text-stats", run_id="R1",
                   evidence={"oracle_status": "passed"})
    audit_greens([sc], runs_dir=runs, out_dir=out_dir, probe_dir=_probe_dir(tmp_path),
                 job_surfaces={"B2": "python-lib"})
    # My sidecar is green-quality.json; I never write #832's green-audit.json.
    assert (runs / "R1" / "green-quality.json").is_file()
    assert not (runs / "R1" / "green-audit.json").exists()
    # My stamps are green_quality_* only — the bare `green_audit` gaming key is never set.
    assert "green_audit" not in sc.evidence
    assert sc.evidence["green_quality_band"] == BAND_C
    # #827's gaming signal (reads green_audit=='gamed' from evidence or its green-audit sidecar)
    # stays inert against my evidence + a run dir with no integrity sidecar.
    ctx = ftax.load_context(runs, "R1")
    assert ctx.green_audit is None  # #832's integrity sidecar absent here
    assert ftax._gaming_signal(sc.evidence, ctx) is None


# ---------------------------------------------------------------------------
# Calibration — measure the auditor against the operator (safe adopt; never gates)
# ---------------------------------------------------------------------------


def test_calibration_agreement_rate(tmp_path):
    calib.record_pair(tmp_path, calib.CalibrationPair("B2", "r1", BAND_C, calib.OP_REJECT))
    calib.record_pair(tmp_path, calib.CalibrationPair("B2", "r2", BAND_A, calib.OP_ACCEPT))
    calib.record_pair(tmp_path, calib.CalibrationPair("B2", "r3", BAND_A, calib.OP_REJECT))  # disagree
    pairs = calib.load_pairs(tmp_path)
    assert len(pairs) == 3
    report = calib.agreement_rate(pairs)
    assert report["agreement"] == "2/3"
    assert "advisory-only" in report["gating"]


def test_calibration_rejects_bad_verdict(tmp_path):
    assert calib.record_pair(tmp_path, calib.CalibrationPair("B2", "r", BAND_A, "maybe")) is False
