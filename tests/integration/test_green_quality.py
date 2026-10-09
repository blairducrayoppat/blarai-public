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
import subprocess
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
    #: MEASURED-clean, because that is the only clean a real lint can produce. A
    #: ``CraftFinding`` is born unmeasured (#1223), so omitting the flag here would build a
    #: "looked and found nothing" fixture out of a "never looked" value.
    clean = l1.CraftFinding(False, "", measured=True)
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


def _l1(regressed=False, changed=False, dead=False, readme=False, no_entry=False, ruff=None,
        seed=None, craft_measured=True):
    """``seed=None`` leaves the seed-divergence finding at its dataclass default, which is
    UNKNOWN — deliberately not clean (see :class:`layer1.SeedDivergenceFinding`).

    Craft lints are built MEASURED by default, because that is the only shape the real lints
    emit for a decided answer: since #1223 a ``CraftFinding`` is born unmeasured, and a
    ``flagged=True, measured=False`` finding is a shape no code path in ``layer1`` can
    produce. Building one anyway is instance 8's defect in miniature — a fixture asserting
    against a value production forbids — and it is what these helpers were doing until the
    born-unmeasured default made them fail loudly. ``craft_measured=False`` is available for
    the tests that deliberately exercise a lint that could not run."""
    kwargs = {} if seed is None else {"seed_divergence": seed}
    return l1.Layer1Result(
        regression=_reg(regressed, changed),
        dead_scaffold=l1.CraftFinding(dead, "scaffold", measured=craft_measured),
        stale_readme=l1.CraftFinding(readme, "readme", measured=craft_measured),
        no_entry_point=l1.CraftFinding(no_entry, "no entry", measured=craft_measured),
        ruff_findings=ruff, surface="python-lib", **kwargs)


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
# The seed-divergence check (#1183) — the relational replacement for marker matching
# ---------------------------------------------------------------------------

#: The seed README exactly as #1142 neutralised it. It contains NONE of
#: ``_README_SKELETON_MARKERS``, which is the whole point: the marker lint cannot see it, in
#: the seed or in the untouched copy that ships. Held here as a literal so these tests keep
#: reproducing the real defect even if the live seed is edited again.
_SEED_README = "# Project\n\nBuilt with BlarAI.\n\nRun the tests with `pytest -q`.\n"

#: The seed pyproject, trimmed to the parts that matter here: a build config the coder is told
#: to KEEP, plus the one operator-facing field it is expected to rewrite.
_SEED_PYPROJECT = (
    '[build-system]\nrequires = ["setuptools>=68"]\n\n'
    '[project]\nname = "app"\nversion = "0.1.0"\n'
    'description = "A starting skeleton for a Python project (extend this)."\n'
    'dependencies = []\n\n'
    '[tool.pytest.ini_options]\ntestpaths = ["tests"]\npythonpath = ["."]\n'
)

#: AGENTS.md is instructions to the coder, not part of the product — an identical copy is
#: CORRECT. Only the sentence that makes that true is needed here.
_SEED_AGENTS = ("**This file is instructions to YOU, the coder. It is not part of the "
                "delivered product.**\n")


def _seed_dir(tmp_path: Path, name: str = "seed") -> Path:
    """A stand-in for ``agentic-setup/build-infra/python/reference`` — the fleet's Python seed."""
    root = tmp_path / name
    (root / "tests").mkdir(parents=True, exist_ok=True)
    (root / "README.md").write_text(_SEED_README, encoding="utf-8")
    (root / "pyproject.toml").write_text(_SEED_PYPROJECT, encoding="utf-8")
    (root / "AGENTS.md").write_text(_SEED_AGENTS, encoding="utf-8")
    (root / "tests" / "test_smoke.py").write_text("def test_smoke():\n    assert True\n",
                                                  encoding="utf-8")
    return root


def _delivery(tmp_path: Path, seed: Path, name: str = "delivered", *,
              readme: str | None = None, description: str | None = None) -> Path:
    """A delivered project: a COPY of the seed, with whatever the coder actually rewrote.
    ``None`` means "the coder left it exactly as seeded" — the case under test."""
    root = tmp_path / name
    (root / "tests").mkdir(parents=True, exist_ok=True)
    (root / "README.md").write_text(
        _SEED_README if readme is None else readme, encoding="utf-8")
    (root / "pyproject.toml").write_text(
        _SEED_PYPROJECT if description is None
        else _SEED_PYPROJECT.replace(
            "A starting skeleton for a Python project (extend this).", description),
        encoding="utf-8")
    # Always copied verbatim — both are files the coder is told NOT to change.
    (root / "AGENTS.md").write_text((seed / "AGENTS.md").read_text(encoding="utf-8"),
                                    encoding="utf-8")
    (root / "tests" / "test_smoke.py").write_text(
        (seed / "tests" / "test_smoke.py").read_text(encoding="utf-8"), encoding="utf-8")
    return root


def test_seed_divergence_flags_an_untouched_delivery(tmp_path):
    """THE REGRESSION LOCK: a delivery that shipped the seed's README and description unchanged
    is flagged, naming both files. This is the 2026-07-29 B2/B4 shape exactly."""
    seed = _seed_dir(tmp_path)
    delivered = _delivery(tmp_path, seed)
    finding = l1.lint_seed_divergence(delivered, seed_root=seed)
    assert finding.flagged is True
    assert finding.status == l1.SEED_STATUS_IDENTICAL
    assert set(finding.identical) == {"README.md", "pyproject.toml"}
    assert finding.measured is True


def test_seed_divergence_is_the_lock_the_marker_lint_is_not(tmp_path):
    """THE TOGGLE (security principle 12): with the lock OFF the probe FAILS.

    Same subject, two checks. ``lint_stale_readme`` — the marker-matching lint — reads the
    untouched seed README as CLEAN, because #1142's neutralised text contains none of its
    markers. The seed-divergence check flags it. This test is the difference between the two,
    and it is the reason the fix was not "extend the marker list": a control keyed on a string
    can be edited into silence, and this one was."""
    seed = _seed_dir(tmp_path)
    delivered = _delivery(tmp_path, seed)
    # Lock OFF — the existing marker lint cannot see the defect at all.
    assert l1.lint_stale_readme(delivered).flagged is False
    # Lock ON — the relational check does.
    assert l1.lint_seed_divergence(delivered, seed_root=seed).flagged is True


def test_seed_divergence_cannot_be_satisfied_by_editing_the_seed(tmp_path):
    """Editing the seed cannot clear the finding, because the delivered file IS a copy of the
    seed — an edit moves BOTH sides of the comparison at once. Rewrite the seed README to
    something entirely different, re-seed the delivery from it, and the flag stands."""
    seed = _seed_dir(tmp_path)
    assert l1.lint_seed_divergence(_delivery(tmp_path, seed), seed_root=seed).flagged is True

    # The "fix" that would silence a marker lint: change the template's own words.
    new_text = "# Your new project\n\nCompletely different template prose.\n"
    (seed / "README.md").write_text(new_text, encoding="utf-8")
    reseeded = _delivery(tmp_path, seed, "delivered2", readme=new_text)
    finding = l1.lint_seed_divergence(reseeded, seed_root=seed)
    assert finding.flagged is True
    assert "README.md" in finding.identical


def test_seed_divergence_clean_when_the_coder_actually_wrote_something(tmp_path):
    """The only way to clear it: write a real README and a real description."""
    seed = _seed_dir(tmp_path)
    delivered = _delivery(tmp_path, seed, readme="# Flashcards CLI\n\nDrills you on cards.\n",
                          description="A command-line flashcard drill.")
    finding = l1.lint_seed_divergence(delivered, seed_root=seed)
    assert finding.flagged is False
    assert finding.status == l1.SEED_STATUS_DIVERGED
    assert set(finding.diverged) == {"README.md", "pyproject.toml"}


def test_seed_divergence_never_punishes_a_file_the_coder_must_not_change(tmp_path):
    """``AGENTS.md`` and ``tests/test_smoke.py`` are byte-identical to the seed in EVERY correct
    delivery — AGENTS.md is instructions to the coder ("not part of the delivered product") and
    test_smoke.py is the toolchain proof AGENTS.md says to keep. Neither may ever be flagged."""
    seed = _seed_dir(tmp_path)
    delivered = _delivery(tmp_path, seed, readme="# Real thing\n", description="A real thing.")
    finding = l1.lint_seed_divergence(delivered, seed_root=seed)
    assert finding.flagged is False
    # Identical on disk, and deliberately outside the comparison set.
    assert (delivered / "AGENTS.md").read_bytes() == (seed / "AGENTS.md").read_bytes()
    assert "AGENTS.md" not in finding.identical + finding.diverged + finding.unknown
    assert "tests/test_smoke.py" not in finding.identical + finding.diverged + finding.unknown


def test_seed_divergence_keeps_pyproject_build_config_out_of_scope(tmp_path):
    """AGENTS.md says "keep ``pyproject.toml``", so its build-system/packaging/pytest blocks are
    LEGITIMATELY byte-identical. Only ``project.description`` is compared: a delivery that
    rewrote the description but kept every other line is clean, even though the file as a whole
    is nearly identical to the seed."""
    seed = _seed_dir(tmp_path)
    delivered = _delivery(tmp_path, seed, readme="# Real\n", description="A word counter.")
    # The file really is otherwise unchanged — this is not a case of the coder rewriting it.
    assert '[build-system]\nrequires = ["setuptools>=68"]' in (
        delivered / "pyproject.toml").read_text(encoding="utf-8")
    finding = l1.lint_seed_divergence(delivered, seed_root=seed)
    assert finding.flagged is False
    assert "pyproject.toml" in finding.diverged


def test_seed_divergence_normalised_newlines_are_not_an_escape(tmp_path):
    """Re-saving the seed README with CRLF line endings does not clear the finding — the
    comparison normalises, so a trivial byte-level edit is not divergence."""
    seed = _seed_dir(tmp_path)
    delivered = _delivery(tmp_path, seed)
    # write_text() on Windows already emits CRLF, so force the delivered copy to bare LF plus
    # a stray trailing blank line — different bytes, identical text.
    (delivered / "README.md").write_bytes((_SEED_README + "\n").encode("utf-8"))
    assert (delivered / "README.md").read_bytes() != (seed / "README.md").read_bytes()
    assert l1.lint_seed_divergence(delivered, seed_root=seed).flagged is True


def test_seed_divergence_missing_seed_is_unknown_never_clean(tmp_path):
    """THE FAIL-SOFT CONTRACT, and the sharp edge of it: an unlocatable seed degrades to
    UNKNOWN — never a crash, never a false flag, and never a PASS. An unknown that reads as
    clean is precisely the bug this check exists to end."""
    delivered = _delivery(tmp_path, _seed_dir(tmp_path))
    finding = l1.lint_seed_divergence(delivered, seed_root=tmp_path / "no-such-seed")
    assert finding.flagged is False          # no false flag
    assert finding.status == l1.SEED_STATUS_UNKNOWN
    assert finding.measured is False         # and NOT readable as clean
    assert set(finding.unknown) == {"README.md", "pyproject.toml"}


def test_seed_divergence_unknown_is_reported_out_loud(tmp_path):
    """FAIL-LOUD: a check that could not run says so in the findings. A silent unmeasured
    control is indistinguishable from a passing one."""
    unknown = l1.lint_seed_divergence(tmp_path / "repo", seed_root=tmp_path / "gone")
    result = _l1()
    assert result.seed_divergence.measured is False  # the dataclass DEFAULT is unknown, not clean
    # Craft lints MEASURED-clean, so the only UNKNOWN in the report is the seed one under test.
    _clean = l1.CraftFinding(False, "", measured=True)
    assert any("seed divergence UNKNOWN" in f for f in l1.Layer1Result(
        regression=_reg(), dead_scaffold=_clean,
        stale_readme=_clean, no_entry_point=_clean,
        seed_divergence=unknown).findings())


def test_seed_divergence_unreadable_delivery_is_unknown_not_flagged(tmp_path):
    """A delivery with no README/pyproject at all cannot be compared — unknown, not flagged
    (the absent file is some other lint's business, never a false seed-identity claim)."""
    seed = _seed_dir(tmp_path)
    empty = tmp_path / "empty"
    empty.mkdir()
    finding = l1.lint_seed_divergence(empty, seed_root=seed)
    assert finding.flagged is False
    assert finding.status == l1.SEED_STATUS_UNKNOWN


def test_seed_divergence_malformed_toml_is_unknown_not_flagged(tmp_path):
    """An unparseable delivered pyproject degrades that file to unknown while the README
    comparison still stands — partial knowledge is reported, never inflated to a verdict."""
    seed = _seed_dir(tmp_path)
    delivered = _delivery(tmp_path, seed, readme="# Real\n")
    (delivered / "pyproject.toml").write_text("[project\nname = broken", encoding="utf-8")
    finding = l1.lint_seed_divergence(delivered, seed_root=seed)
    assert finding.flagged is False
    assert finding.diverged == ("README.md",)
    assert finding.unknown == ("pyproject.toml",)
    assert "not compared: pyproject.toml" in finding.detail


def test_seed_divergence_default_root_resolves_without_a_hardcoded_path():
    """The seed root comes from the harness config's ``agentic_setup_dir`` (env → TOML →
    documented fallback), the same resolver every other external fleet path uses — never a
    literal absolute path in the lint. ``None`` when it does not exist on this box."""
    root = l1.default_seed_root()
    assert root is None or root.name == "reference"
    # A config object that names a root is honoured verbatim.
    class _Cfg:
        agentic_setup_dir = "C:/nowhere-at-all"
    assert l1.default_seed_root(_Cfg()) is None


def test_seed_divergence_moves_the_band_and_the_card(tmp_path):
    """Wired, not merely built: a flagged seed-divergence is a B trigger and the operator card
    says so in plain language. An UNMEASURED check moves nothing — the band states something
    about the DELIVERABLE, and a seed the auditor could not read says nothing about it."""
    seed = _seed_dir(tmp_path)
    flagged = l1.lint_seed_divergence(_delivery(tmp_path, seed), seed_root=seed)
    unknown = l1.lint_seed_divergence(tmp_path / "x", seed_root=tmp_path / "gone")

    banded = _l1()
    assert band_mod.compute_band(banded) == BAND_A          # unknown by default -> no signal
    assert band_mod.compute_band(_l1(seed=flagged)) == BAND_B
    assert band_mod.compute_band(_l1(seed=unknown)) == BAND_A

    the_card = card_mod.build_card("B2", "python-lib", BAND_B, _l1(seed=flagged))
    assert "word-for-word" in the_card.caveat
    assert "starter template" in the_card.caveat


def test_seed_divergence_reaches_the_audit_and_the_sidecar(tmp_path):
    """REACHABILITY: driven through the real ``audit_greens`` entry point the battery calls, a
    seed-copy delivery lands a named evidence key and a sidecar that records a STATUS STRING —
    never a bare bool, so 'unknown' can never be read as 'clean' by a later reader."""
    seed = _seed_dir(tmp_path)
    out_dir = tmp_path / "battery" / "20260102"
    repo = out_dir / "repos-archived" / "battery-b4-flashcards-cli"
    _delivery(out_dir / "repos-archived", seed, "battery-b4-flashcards-cli")
    (repo / "app").mkdir(parents=True, exist_ok=True)
    runs = tmp_path / "runs"
    sc = Scorecard(job_id="B4", verdict="GREEN", repo="battery-b4-flashcards-cli", run_id="R9")

    audit_greens([sc], runs_dir=runs, out_dir=out_dir, seed_root=seed,
                 probe_dir=tmp_path / "no-probes", job_surfaces={"B4": "python-cli"})

    assert sc.evidence["green_quality_seed_identical"] == "README.md,pyproject.toml"
    assert sc.evidence["green_quality_band"] == BAND_B
    assert validate(sc) == []
    sidecar = json.loads((runs / "R9" / "green-quality.json").read_text(encoding="utf-8"))
    assert sidecar["craft"]["seed_divergence"] == l1.SEED_STATUS_IDENTICAL
    assert sidecar["craft"]["seed_identical_files"] == ["README.md", "pyproject.toml"]
    assert sidecar["craft"]["seed_root"] == str(seed)


# --- The real deliveries (opportunistic — the live sandbox, not an immutable archive) -------

_REAL_PROJECTS = ("battery-b2-text-stats", "battery-b4-flashcards-cli")


def _seed_file_set(seed: Path | None) -> set[str]:
    """Every file the fleet seed declares, repo-relative. Empty when the seed is absent."""
    if seed is None:
        return set()
    return {p.relative_to(seed).as_posix() for p in seed.rglob("*") if p.is_file()}


def _archive_holds_a_delivery(repo: Path, seed_files: set[str]) -> bool:
    """Does this archived sandbox hold coder work, or only the seed?

    Asserts the PRECONDITION the seed-divergence measurement needs — every file the seed
    declares is present to be compared against. A sandbox that parked before the coder
    committed is missing most of them, and the lint correctly reports those `unknown`.

    Deliberately NOT a commit count. The previous form asked `> 1 commit`, reasoning that a
    seeded sandbox carries only "init battery sandbox". #740 then added a second seed commit
    and the discriminator silently stopped discriminating — see the caller for the incident.
    A property of the tree cannot be invalidated by a change to the harness's commit habits.
    """
    if not seed_files:
        return False
    ls = subprocess.run(["git", "-C", str(repo), "ls-files"], capture_output=True, text=True)
    if ls.returncode != 0:
        return False
    tracked = {line for line in ls.stdout.split() if line}
    return not (seed_files - tracked)


def _git_sandbox(root: Path, commits: list[dict[str, str]]) -> Path:
    """A real git repo with one commit per element — no mock; the discriminator shells out.

    Takes a LIST of commits rather than a flat file map because commit COUNT is the thing the
    old discriminator keyed on: a fixture that always makes one commit would be rejected by
    the old rule for the wrong reason and the regression lock would pass without proving
    anything. Caught by mutating the discriminator back and watching the lock stay green.
    """
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(root), "init", "-q"], capture_output=True, text=True)
    for i, files in enumerate(commits):
        for rel, body in files.items():
            f = root / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(body, encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "-A"], capture_output=True, text=True)
        subprocess.run(["git", "-C", str(root), "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-qm", f"c{i}"], capture_output=True, text=True)
    return root


def test_a_seed_only_sandbox_is_NOT_mistaken_for_a_delivery(tmp_path):
    """REGRESSION LOCK for the 2026-08-07 red gate.

    A B4 run parked before the coder committed anything. Its archive held exactly two
    commits — `init battery sandbox` and #740's `seed protected job-level acceptance oracle`
    — and the old `> 1 commit` discriminator read that as a delivery. It went to the top of
    the newest-first list, the seed-divergence lint honestly reported `unknown` for a
    `pyproject.toml` that was never there to compare, and `main` went red on a lint that was
    working correctly.

    The sandbox here makes TWO commits, mirroring the real pair, precisely so that the old
    `> 1` rule WOULD accept it. That is what makes this a lock rather than a coincidence:
    revert the discriminator and this test goes red.
    """
    seed_files = {"pyproject.toml", "README.md", "app/main.py", "tests/test_app.py"}
    seed_only = _git_sandbox(tmp_path / "parked", [
        {"README.md": "x"},                                  # init battery sandbox
        {"tests/test_job_acceptance.py": "seeded oracle"},   # #740's oracle seed
    ])
    assert _archive_holds_a_delivery(seed_only, seed_files) is False, (
        "a sandbox that parked before the coder committed was accepted as a delivery — "
        "this is the 2026-08-07 red gate returning")


def test_a_real_delivery_IS_recognised(tmp_path):
    """CONTROL for the lock above: the discriminator must not simply reject everything."""
    seed_files = {"pyproject.toml", "README.md", "app/main.py", "tests/test_app.py"}
    delivered = _git_sandbox(tmp_path / "delivered", [
        {"README.md": "x", "pyproject.toml": "[project]"},
        {"app/main.py": "print(1)", "tests/test_app.py": "def test_x(): pass"},
        {"app/extra.py": "coder work"},
    ])
    assert _archive_holds_a_delivery(delivered, seed_files) is True


def test_an_absent_seed_affirms_nothing(tmp_path):
    """[kill] Fail-closed: with no seed to compare against, nothing may be called a delivery."""
    delivered = _git_sandbox(tmp_path / "d", [
        {"README.md": "x"}, {"app/main.py": "y"}])
    assert _archive_holds_a_delivery(delivered, set()) is False
    assert _seed_file_set(None) == set()


@pytest.mark.parametrize("project", _REAL_PROJECTS)
def test_seed_divergence_returns_a_determinate_answer_on_the_real_deliveries(project):
    """Against a REAL COMPLETED delivery and the REAL seed: the check must reach a DETERMINATE
    answer (never crash, never 'unknown') on the projects the fleet actually produces.

    Reads the most recent ARCHIVED delivery, never the live ``projects/`` tree. That is the
    whole point: the wrapper archives the previous delivery by rename and ``git init``s a
    fresh sandbox at the START of every run, so between 23:00 and the coder's first commit —
    and for the entire duration of any run — the live tree holds only seed files and several
    seed files do not exist there to be compared. The lint correctly reports those `unknown`,
    and a gate asserting determinacy against them fails for a reason that has nothing to do
    with the code under test. That is the "gate must not be killed by the live system" rule,
    and it went RED on 2026-07-30 for exactly this. An archived delivery is immutable and
    complete, so the assertion below means what it says.

    Deliberately does NOT assert *flagged* — pinning the expected answer would turn a coder
    finally writing a README into a gate failure. That both projects were flagged on
    2026-07-30 is recorded in the shipping commit and on #1183."""
    seed = l1.default_seed_root()
    archived = sorted(
        Path("C:/Users/mrbla/agentic-setup/state/battery").glob(f"night-*/repos-archived/{project}"),
        reverse=True,
    )
    # Newest archive that actually holds a DELIVERY. An archived tree is not automatically a
    # delivery: a run cancelled (or still in flight) before the coder's first commit archives
    # a tree carrying only the seed, and 2026-07-30 put exactly such a tree at the top of the
    # list.
    #
    # THE DISCRIMINATOR COUNTED COMMITS AND THE SEED GREW A SECOND ONE (2026-08-07). The
    # original form asserted `> 1 commit`, on the reasoning that "a seeded sandbox carries the
    # single 'init battery sandbox' commit and nothing else". #740 then added a second seed
    # commit — `chore(m2): seed protected job-level acceptance oracle` — so a sandbox that
    # parked before the coder ever committed carried TWO commits and read as a delivery. The
    # 2026-08-06 23:00 B4 run did exactly that (PARKED-HONEST at 141 s, attribution BUILD),
    # went to the top of this list, and turned `main` red on a lint that was working perfectly:
    # a seed-only tree has no `pyproject.toml` to compare, so `unknown` is the HONEST answer
    # and the assertion below is right to reject it. The test picked the wrong tree.
    #
    # So this no longer counts anything. It asserts the PRECONDITION the measurement needs:
    # every file the seed declares is present to be compared against. A seed-only sandbox is
    # missing four of the five; a real delivery has all of them plus its own work. That is a
    # property of the tree rather than a fact about the harness's commit habits, so the next
    # change to seeding cannot silently re-break it — which is exactly how this broke.
    seed_files = _seed_file_set(seed)
    repo = next((p for p in archived
                 if p.is_dir() and _archive_holds_a_delivery(p, seed_files)), None)
    if seed is None or repo is None:
        pytest.skip("real fleet seed / a completed archived delivery not present on this box")
    finding = l1.lint_seed_divergence(repo)
    assert finding.measured is True
    assert finding.status in (l1.SEED_STATUS_IDENTICAL, l1.SEED_STATUS_DIVERGED)
    assert not finding.unknown


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


# ---------------------------------------------------------------------------
# #1189 — the advisory ruff lint: a skipped lint must not read as a clean one
# ---------------------------------------------------------------------------


def test_ruff_not_run_is_stated_never_implied_by_silence():
    """`None` (could not run) and `0` (ran, found nothing) are different answers.

    The old render was `if self.ruff_findings:`, which suppressed BOTH — so a lint that had
    never executed was indistinguishable from a clean one. It had never executed on any
    night: `run_ruff_advisory` invoked a bare ``ruff``, and the harness runs the venv's
    python.exe directly rather than through an activated venv, so the name could not resolve.
    """
    unmeasured = _l1(ruff=None).findings()
    measured_clean = _l1(ruff=0).findings()
    measured_dirty = _l1(ruff=7).findings()

    assert any("NOT RUN" in s for s in unmeasured), unmeasured
    assert any("absent measurement" in s for s in unmeasured), unmeasured
    # the toggle: a real zero must NOT borrow the unmeasured wording, and vice versa
    assert not any("NOT RUN" in s for s in measured_clean), measured_clean
    assert any("0 advisory findings (measured)" in s for s in measured_clean), measured_clean
    assert any("7 advisory finding(s)" in s for s in measured_dirty), measured_dirty


# ---------------------------------------------------------------------------
# #1244 — the producer must not mint a zero the run did not earn.
#
# What stood here was `test_ruff_is_invoked_by_module_not_by_a_bare_command_name`, which did
# `inspect.getsource(l1.run_ruff_advisory)` and asserted `'["ruff", "check"' in src`. Its
# subject was the SOURCE TEXT, so it passed on the textual presence of code — it would have
# passed if the entire function body were deleted and replaced by that string in a comment.
# It also certified a fallback that was UNREACHABLE at the time it was written. Deleted, not
# repaired: a control whose subject is the source text is satisfiable by editing the source
# text, and the three tests below take the RETURN VALUE as their subject instead.
# ---------------------------------------------------------------------------


def test_ruff_that_could_not_lint_reports_NOT_RUN_not_a_clean_zero(tmp_path):
    """Real ruff, real failure, no mock — the deliverable's own config is the trigger.

    An unknown rule selector makes ruff exit 2 with EMPTY stdout. The old
    `json.loads(cp.stdout or "[]")` turned that into `0`, which `findings()` prints as
    "ruff: 0 advisory findings (measured)" — the operator reading his card could not tell
    it from a lint that ran and found nothing. The coder fleet writes these config files,
    so this is reachable on a real deliverable and not a contrived shape.
    """
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[tool.ruff.lint]\nselect = ["ZZZ999"]\n', encoding="utf-8")

    assert l1.run_ruff_advisory(tmp_path) is None

    # and the render the operator actually reads must say so out loud
    rendered = _l1(ruff=l1.run_ruff_advisory(tmp_path)).findings()
    assert any("NOT RUN" in s for s in rendered), rendered
    assert not any("(measured)" in s for s in rendered), rendered


def test_ruff_that_DID_lint_still_reports_its_count(tmp_path):
    """The control case. Without it, a function that returned ``None`` unconditionally would
    pass the test above — "secure" would be indistinguishable from "the probe never reached
    the control" (security_by_design principle 12).

    MEASURED (ruff 0.16.1): a genuine run always writes at least the two-character document
    ``[]``, so a clean tree is a MEASURED zero and must keep saying so.
    """
    (tmp_path / "a.py").write_text(
        "def mean(xs):\n    return sum(xs) / len(xs)\n", encoding="utf-8")
    assert l1.run_ruff_advisory(tmp_path) == 0

    (tmp_path / "b.py").write_text("import os\nimport sys\n", encoding="utf-8")
    dirty = l1.run_ruff_advisory(tmp_path)
    assert isinstance(dirty, int) and dirty > 0, dirty


def test_an_EMPTY_tree_is_a_measured_zero_and_not_an_absent_measurement(tmp_path):
    """The boundary the guard must NOT cross, kept as its own test because it is the one way
    this fix could be wrong in the expensive direction.

    "Blank stdout means not-run" would be a defect if any genuine run printed nothing. Eleven
    cases were measured looking for one — empty directory, only non-Python files,
    ``exclude = ["*"]``, ``extend-exclude = ["*.py"]``, ``select = []``, a file-level
    ``# ruff: noqa`` — and every one emitted ``[]`` with exit 0. This locks the two that are
    cheap to express, so a future ruff that starts printing nothing on a real run breaks a
    test here rather than silently converting clean trees into "NOT RUN".
    """
    assert l1.run_ruff_advisory(tmp_path) == 0, "an empty tree is a measured zero"

    (tmp_path / "notes.txt").write_text("no python here\n", encoding="utf-8")
    assert l1.run_ruff_advisory(tmp_path) == 0, "a tree with no .py files is a measured zero"


def test_a_smart_quote_in_the_deliverable_does_not_make_the_lint_RAISE(tmp_path):
    """The #1244 guard's own regression, found post-merge and fixed in the same night.

    LLM-written code contains smart quotes routinely. ruff echoes the offending source into the
    diagnostic's ``fix.content``, so its JSON carries U+201D (bytes E2 80 9D). ``text=True``
    decodes with the LOCALE encoding -- cp1252 here -- where byte 0x9D is UNDEFINED. The decode
    raises inside subprocess's reader THREAD, which cannot propagate, so ``subprocess.run``
    returns normally with ``cp.stdout is None``.

    The first #1244 guard did ``cp.stdout.strip()`` on that and raised ``AttributeError`` --
    from a function whose docstring promises it never raises, into `battery.py`'s blanket
    ``except Exception``, which would have blanked the ENTIRE green-quality stage for the night
    rather than one lint. Pinning ``encoding="utf-8"`` is what actually fixes it: the lint now
    RUNS on such a tree rather than merely failing to crash on it.
    """
    src = 'x = f"he said ”hi”"\n'
    (tmp_path / "m.py").write_bytes(src.encode("utf-8"))

    result = l1.run_ruff_advisory(tmp_path)          # must not raise

    assert isinstance(result, int), (
        f"a smart-quoted tree must yield a MEASURED count, got {result!r}"
    )


def test_a_None_stdout_is_NOT_RUN_and_never_an_exception(monkeypatch, tmp_path):
    """Belt-and-braces control for the shape above, driven at the seam.

    Even with the encoding pinned, ``cp.stdout`` being None must read as an absent measurement
    rather than crash -- because the alternative failure is invisible (swallowed one frame up)
    and costs a whole night. Asserts the guard tolerates None AND still answers NOT RUN.
    """
    class _CP:
        returncode = 0
        stdout = None
        stderr = ""

    monkeypatch.setattr(l1.subprocess, "run", lambda *a, **k: _CP())
    assert l1.run_ruff_advisory(tmp_path) is None


def test_the_NOT_RUN_answer_FAILS_when_the_guard_is_removed(tmp_path):
    """The toggle-proof: prove the guard is what changes the answer, not something else.

    Replays the exact shape captured from real ruff through the PRE-FIX expression and asserts
    it produces the false zero. Without this, a green test above cannot distinguish "the guard
    works" from "this input never reached the guard". The subprocess call is in the test rather
    than mocked into the module so the shape is the real one, and the raw-spawn gate excludes
    test paths (`test_no_new_raw_spawn_sites.py:212`).
    """
    import sys

    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[tool.ruff.lint]\nselect = ["ZZZ999"]\n', encoding="utf-8")

    cp = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--output-format", "json", "."],
        capture_output=True, text=True, cwd=str(tmp_path), timeout=60,
    )
    # the shape this fix was written against, asserted rather than assumed
    assert cp.returncode == 2, cp.returncode
    assert cp.stdout.strip() == "", repr(cp.stdout)

    # PRE-FIX: `or "[]"` swallows the empty stdout and mints a zero
    assert len(json.loads(cp.stdout or "[]")) == 0

    # POST-FIX: the same run, through the real function, is an absent measurement
    assert l1.run_ruff_advisory(tmp_path) is None


# ---------------------------------------------------------------------------
# #1223 F2 — the scorecard evidence stamp and the corpus rollup were FLAG-SHAPED
#
# An instrument that could not look emitted no key at all, and an absent key is exactly what
# a measured-and-clean instrument emits. The security stamp had been given the three-way
# treatment for that reason and said so in a comment four lines above; the other three keys,
# and the two corpus counters the operator's KPI line is built from, were left flag-shaped.
# ---------------------------------------------------------------------------


def _audit_result(layer1):
    """A GreenAuditResult carrying *layer1*, everything else measured-clean.

    Hand-built on purpose: the RENDERER is what is under test here, and the stamp must be
    provably three-way across status combinations a fixture tree cannot conveniently produce.
    The SEAM — that the real entrypoints return unmeasured when they cannot measure — is
    proved separately in tests/security/test_instrument_toggles.py."""
    from tools.dispatch_harness.green_quality import GreenAuditResult
    from tools.dispatch_harness.green_quality.security import SecurityResult

    return GreenAuditResult(
        job_id="B2", run_id="R1", repo="r", surface="python-lib", band=BAND_A,
        mode="det-only", layer1=layer1, jury=None,
        card=card_mod.build_card("B2", "python-lib", BAND_A, layer1),
        reference_green=None,
        security=SecurityResult(measured=True, files_scanned=3),
    )


def test_a_measured_clean_audit_stamps_no_layer1_disclosure():
    """THE QUIET CASE, first, because noise is the failure mode of this fix.

    Every layer-1 key stays absent when all four instruments looked and found nothing. If this
    ever inverts, the stamp starts disclosing on healthy nights, the operator learns to skim
    the green_quality_* block, and the loud keys below go unread along with it."""
    clean_seed = l1.SeedDivergenceFinding(False, "all diverged", status=l1.SEED_STATUS_DIVERGED)
    stamp = _audit_result(_l1(seed=clean_seed)).evidence_stamp("sidecar")

    for key in ("green_quality_regressed", "green_quality_dead_scaffold",
                "green_quality_seed_identical"):
        assert key not in stamp, f"{key} was stamped on a measured-clean audit: {stamp.get(key)!r}"
    # ...while the unconditional security key is still there, unchanged.
    assert stamp["green_quality_security"].startswith("clean (")


def test_an_unmeasured_layer1_instrument_stamps_a_disclosure_not_silence():
    """THE LOUD CASE: a probe or lint that could not look says so ON THE SCORECARD.

    Before this, ``if self.layer1.regression.regressed:`` wrote the key only on a finding, so a
    probe that never ran produced the same stamp as one that ran clean — the #1223 collapse on
    the surface a non-technical reader treats as the record of the night. The disclosure
    carries the marker registered in shared/instrument_registry.py, so a reader (and any
    downstream consumer) tells a disclosure from a finding by its VALUE, never by presence."""
    unmeasured = l1.Layer1Result(
        regression=l1.RegressionFinding(False, False, "probe could not run", measured=False),
        dead_scaffold=l1.CraftFinding(False, "tree unreadable", measured=False),
        stale_readme=l1.CraftFinding(False, "tree unreadable", measured=False),
        no_entry_point=l1.CraftFinding(False, "tree unreadable", measured=False),
        ruff_findings=None, surface="python-lib",
    )
    stamp = _audit_result(unmeasured).evidence_stamp("sidecar")

    assert "regression probe NOT RUN" in stamp["green_quality_regressed"]
    assert "dead scaffold lint NOT RUN" in stamp["green_quality_dead_scaffold"]
    # the seed finding is left at its dataclass default, which is UNKNOWN
    assert "seed divergence UNKNOWN" in stamp["green_quality_seed_identical"]


def test_a_measured_finding_still_stamps_the_finding_not_the_disclosure():
    """The third way, pinned so the fix cannot be 'completed' by disclosing unconditionally.

    A key that always carries a caveat is as unreadable as one that never does."""
    flagged_seed = l1.SeedDivergenceFinding(
        True, "still the seed", status=l1.SEED_STATUS_IDENTICAL, identical=("README.md",))
    stamp = _audit_result(_l1(regressed=True, dead=True, seed=flagged_seed)).evidence_stamp("s")

    assert "NOT RUN" not in stamp["green_quality_regressed"]
    assert stamp["green_quality_dead_scaffold"] == "residue"
    assert stamp["green_quality_seed_identical"] == "README.md"


def test_any_craft_residue_is_false_for_a_lint_that_could_not_look():
    """``flagged=False`` out of a blind lint is not a clean answer, and the property no longer
    reports it as one — the unmeasured lints are NAMED by its companion instead.

    This property is what the corpus counter and the operator's KPI line are both derived
    from, so the collapse rode all the way out to the night's headline number."""
    blind = _l1(craft_measured=False)
    assert blind.any_craft_residue is False
    assert blind.craft_lints_unmeasured == ("dead scaffold", "stale README", "entry point",
                                            "seed divergence")

    clean_seed = l1.SeedDivergenceFinding(False, "diverged", status=l1.SEED_STATUS_DIVERGED)
    looked = _l1(seed=clean_seed)
    assert looked.any_craft_residue is False
    assert looked.craft_lints_unmeasured == ()

    # the toggle: a MEASURED residue is still reported, so the guard did not silence the
    # finding it was added to qualify.
    assert _l1(dead=True, seed=clean_seed).any_craft_residue is True
    assert _l1(dead=True, craft_measured=False).any_craft_residue is False


def test_the_corpus_rollup_pairs_every_count_with_its_unmeasured_partner():
    """The night's summary block, which ``render_kpi`` prints straight to the operator.

    ``regressed`` and ``craft_residue`` counted findings and said nothing about how many jobs
    were never examined, while ``security_unmeasured`` sat two lines below doing it correctly.
    A reader comparing ``regressed=0`` across nights could not tell a quiet night from a blind
    one."""
    from tools.dispatch_harness.green_quality import corpus_block, render_kpi

    blind_l1 = _l1(craft_measured=False, seed=None)
    blind_l1.regression = l1.RegressionFinding(False, False, "no reference GREEN", measured=False)
    blind = _audit_result(blind_l1)
    clean_seed = l1.SeedDivergenceFinding(False, "diverged", status=l1.SEED_STATUS_DIVERGED)
    looked = _audit_result(_l1(seed=clean_seed))

    block = corpus_block([blind, looked], "det-only")
    assert block["audited"] == 2
    assert block["regressed"] == 0 and block["regression_unmeasured"] == 1
    assert block["craft_residue"] == 0 and block["craft_unmeasured"] == 1

    kpi = "\n".join(render_kpi(block))
    assert "regressed=0 (not-measured=1)" in kpi, kpi
    assert "craft-residue=0 (not-measured=1)" in kpi, kpi


def test_the_corpus_rollup_still_counts_a_measured_regression():
    """The toggle on the guard added to the rollup: qualifying ``regressed`` with ``measured``
    must not stop a REAL regression being counted. A guard that silences the finding it was
    added to qualify is this defect class mirrored."""
    from tools.dispatch_harness.green_quality import corpus_block

    clean_seed = l1.SeedDivergenceFinding(False, "diverged", status=l1.SEED_STATUS_DIVERGED)
    block = corpus_block([_audit_result(_l1(regressed=True, seed=clean_seed))], "det-only")
    assert block["regressed"] == 1 and block["regression_unmeasured"] == 0


# ---- #1269: silence is not a measurement -----------------------------------
#
# The defect these lock: run_probe returned [] when the child produced no output, and
# _diff_probe then found [] and [] "comparable" -- any() over an empty sequence is False
# and 0 != 0 is False, so NEITHER guard fired. archetype_regression stamped
# measured=True with "no behaviour change vs the last archived GREEN", and the operator
# KPI read "regressed=0 (not-measured=0)" about code no probe had run.
#
# These drive the REAL run_probe against REAL child processes -- no stubbed runner --
# because a mocked runner is what let the original ship: every existing regression test
# used a probe that returned output.

from tools.dispatch_harness.green_quality import layer1 as _gq_layer1


def _probe_repo(root: Path, body: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "app.py").write_text(body, encoding="utf-8")
    return root


_SILENT_AT_IMPORT = (
    # SystemExit derives from BaseException, so _PYCALL_HARNESS's `except Exception`
    # cannot catch it. The child dies before its print(). argparse writes to stderr, so
    # stdout is empty. This is a very common LLM deliverable shape.
    "import sys\n"
    "def convert(x):\n"
    "    return x * 2\n"
    "sys.exit(0)\n"
)
_HEALTHY = "def convert(x):\n    return x * 2\n"


def _pycall_probe() -> "_gq_layer1.Probe":
    return _gq_layer1.Probe(
        kind=_gq_layer1.PROBE_KIND_PYTHON_CALLABLE, module="app", attr="convert",
        inputs=("1", "2"), argv=(),
    )


class _OneProbeSet:
    def __init__(self, probe: "_gq_layer1.Probe") -> None:
        self.probes = (probe,)


def test_a_probe_that_produced_no_output_returns_the_could_not_run_sentinel(
    tmp_path: Path,
) -> None:
    """run_probe's own docstring promises the sentinel 'on any failure'. Empty stdout was
    the failure it did not honour."""
    repo = _probe_repo(tmp_path / "cur", _SILENT_AT_IMPORT)
    out = _gq_layer1.run_probe(repo, _pycall_probe())
    assert len(out) == 1 and out[0].startswith("could-not-run"), out


def test_two_silent_probes_are_not_comparable(tmp_path: Path) -> None:
    """The exact vacuous-guard case: both sides silent, so both guards are satisfied by
    emptiness rather than by agreement."""
    cur = _probe_repo(tmp_path / "cur", _SILENT_AT_IMPORT)
    ref = _probe_repo(tmp_path / "ref", _SILENT_AT_IMPORT)
    comparable, diffs = _gq_layer1._diff_probe(cur, ref, _pycall_probe(), _gq_layer1.run_probe)
    assert comparable is False and diffs == []


def test_a_silent_probe_yields_measured_False_not_no_behaviour_change(
    tmp_path: Path,
) -> None:
    """THE REGRESSION LOCK. Before the fix this returned
    measured=True, 'no behaviour change vs the last archived GREEN'."""
    cur = _probe_repo(tmp_path / "cur", _SILENT_AT_IMPORT)
    ref = _probe_repo(tmp_path / "ref", _SILENT_AT_IMPORT)
    probe = _pycall_probe()
    finding = _gq_layer1.archetype_regression(
        cur, ref, probe_set=_OneProbeSet(probe), run=_gq_layer1.run_probe,
    )
    assert finding.measured is False, "a probe that never ran must not read as measured"
    assert "could not run" in finding.detail
    assert finding.regressed is False and finding.changed is False


def test_a_healthy_probe_still_measures(tmp_path: Path) -> None:
    """THE CONVERSE. A control that refuses everything is not a control -- without this,
    the lock above is satisfied by breaking the instrument entirely."""
    cur = _probe_repo(tmp_path / "cur", _HEALTHY)
    ref = _probe_repo(tmp_path / "ref", _HEALTHY)
    probe = _pycall_probe()
    finding = _gq_layer1.archetype_regression(
        cur, ref, probe_set=_OneProbeSet(probe), run=_gq_layer1.run_probe,
    )
    assert finding.measured is True
    assert finding.regressed is False and finding.changed is False


def test_a_real_regression_is_still_caught_after_the_fix(tmp_path: Path) -> None:
    """The seed proof's shape, in miniature: the fix must not blind the instrument to the
    data-loss case it exists to catch."""
    cur = _probe_repo(tmp_path / "cur", "def convert(x):\n    return ''\n")
    ref = _probe_repo(tmp_path / "ref", _HEALTHY)
    probe = _pycall_probe()
    finding = _gq_layer1.archetype_regression(
        cur, ref, probe_set=_OneProbeSet(probe), run=_gq_layer1.run_probe,
    )
    assert finding.measured is True and finding.regressed is True


def test_a_short_result_list_is_not_compared_as_a_prefix(tmp_path: Path) -> None:
    """The harness emits one result per input. Fewer means it died partway, and comparing
    a prefix against a full run is a measurement of different things."""
    repo = _probe_repo(tmp_path / "cur", _HEALTHY)
    probe = _gq_layer1.Probe(
        kind=_gq_layer1.PROBE_KIND_PYTHON_CALLABLE, module="app", attr="convert",
        inputs=("1", "2", "3"), argv=(),
    )
    out = _gq_layer1.run_probe(repo, probe)
    assert len(out) == 3, "sanity: a healthy probe returns one output per input"

    def _truncating_runner(r: Path, p: "_gq_layer1.Probe") -> list[str]:
        return _gq_layer1.run_probe(r, p)[:1]

    comparable, _ = _gq_layer1._diff_probe(repo, repo, probe, _truncating_runner)
    assert comparable is True, "equal-length truncation is still comparable"

    def _empty_runner(r: Path, p: "_gq_layer1.Probe") -> list[str]:
        return []

    comparable2, _ = _gq_layer1._diff_probe(repo, repo, probe, _empty_runner)
    assert comparable2 is False, (
        "the second independent lock: a runner returning [] must never mint a measurement, "
        "even though run_probe no longer does"
    )


# ---- #1270: a dropped card is counted, and a total failure is never silent ----
#
# audit_greens' per-card handler is correctly fail-soft, but the dropped card was counted
# NOWHERE -- not audited, not unmeasured, not at all -- so `audited: len(results)`
# described a partial night as a whole one. And render_kpi returned [] on audited==0, so a
# night whose EVERY audit raised rendered byte-identically to a night with no GREENs: the
# most reassuring output the function can emit, produced by its worst input.

from tools.dispatch_harness import green_quality as _gq


def test_corpus_block_counts_the_cards_that_raised() -> None:
    block = _gq.corpus_block([], _gq.MODE_DET_ONLY, audit_failed=("B2", "B4", "B7"))
    assert block["audited"] == 0
    assert block["audit_failed"] == 3
    assert block["audit_failed_jobs"] == ["B2", "B4", "B7"]


def test_a_night_where_every_audit_raised_is_not_rendered_as_silence() -> None:
    """THE REGRESSION LOCK. Before the fix this returned [] -- identical to a quiet night."""
    block = _gq.corpus_block([], _gq.MODE_DET_ONLY, audit_failed=("B2", "B4"))
    out = _gq.render_kpi(block)
    assert out, "a total audit failure must not render as nothing"
    joined = " ".join(out)
    assert "NOT MEASURED" in joined and "B2" in joined and "B4" in joined


def test_a_genuinely_quiet_night_still_renders_nothing() -> None:
    """THE CONVERSE. Without this, the lock above is satisfied by making the KPI shout on
    every night with no GREENs -- which would train the operator to ignore it."""
    assert _gq.render_kpi(_gq.corpus_block([], _gq.MODE_DET_ONLY)) == []
    assert _gq.render_kpi({}) == []


def test_a_partial_failure_is_rendered_beside_the_counts_not_instead_of_them(
    tmp_path: Path,
) -> None:
    """audited=N on a night where cards also raised is not wrong about the N -- it is silent
    about the rest. Both must appear."""
    block = dict(_gq.corpus_block([], _gq.MODE_DET_ONLY, audit_failed=("B7",)))
    block["audited"] = 2  # pretend two cards did audit
    out = _gq.render_kpi(block)
    joined = " ".join(out)
    assert "audit-failed=1" in joined, joined
    assert "bands" in joined, "the ordinary counts must still render"


def test_audit_failed_defaults_to_zero_so_existing_callers_are_unchanged() -> None:
    """corpus_block's new parameter is keyword-only with a default: a caller that does not
    pass it gets today's behaviour exactly, and the KPI stays quiet."""
    block = _gq.corpus_block([], _gq.MODE_DET_ONLY)
    assert block["audit_failed"] == 0 and block["audit_failed_jobs"] == []


# ---------------------------------------------------------------------------
# RECONCILIATION — the night's rollup checked by something that is not the rollup
# ---------------------------------------------------------------------------
# DoD capability 13. `corpus_block` is the shared aggregator behind several registered
# instruments (the three craft lints, the archetype regression probe), so locking it once holds
# more than one of them. #1270 already fixed the loss it had — a card that RAISED vanished from
# `results` and was counted nowhere, so `audited` described a smaller night as a complete one.
#
# These lock the arithmetic that fix depends on, which nothing asserted:
#   * the bands PARTITION the audited population (they sum to `audited`);
#   * `audited` is the POPULATION, not a sum of the bands — the #1231 property, which is what
#     stops coverage looking clean while classification degrades;
#   * the night's true size stays recoverable as `audited + audit_failed`.


def _clean_result():
    clean_seed = l1.SeedDivergenceFinding(False, "diverged", status=l1.SEED_STATUS_DIVERGED)
    return _audit_result(_l1(seed=clean_seed))


def test_the_bands_partition_the_audited_population() -> None:
    from dataclasses import replace

    base = _clean_result()
    results = [replace(base, band=b) for b in (BAND_A, BAND_B, BAND_C)]
    block = _gq.corpus_block(results, _gq.MODE_DET_ONLY)

    assert block["audited"] == 3
    assert sum(block["bands"].values()) == block["audited"], (
        f"bands do not partition the audited population: "
        f"{block['bands']} sums to {sum(block['bands'].values())}, audited={block['audited']}"
    )


def test_audited_is_the_POPULATION_not_a_sum_of_the_bands() -> None:
    """#1231's exact shape, and the reason this rollup can be trusted.

    A card carrying a band no bucket recognises must STILL count in `audited`. If `audited`
    were derived from the band counters — as `link_lint`'s `references` is (#1389) — that card
    would leave numerator and denominator together, the arithmetic would stay perfectly
    self-consistent, and a night that classified less would look identical to a smaller one.
    """
    from dataclasses import replace

    base = _clean_result()
    rogue = replace(base, band="Z-INVENTED-LATER")
    block = _gq.corpus_block([base, rogue], _gq.MODE_DET_ONLY)

    assert block["audited"] == 2, "an unclassifiable card must not vanish from the population"
    assert sum(block["bands"].values()) == 1, "sanity: the rogue band is in no bucket"
    # And the divergence must be VISIBLE — audited does not shrink to match the buckets.
    assert sum(block["bands"].values()) != block["audited"]


def test_the_partition_lock_is_not_vacuous() -> None:
    """The toggle. A partition assertion that cannot fail proves nothing (principle 12)."""
    from dataclasses import replace

    base = _clean_result()
    good = _gq.corpus_block([replace(base, band=BAND_A)], _gq.MODE_DET_ONLY)
    assert sum(good["bands"].values()) == good["audited"]

    bad = _gq.corpus_block([replace(base, band="NOT-A-BAND")], _gq.MODE_DET_ONLY)
    assert sum(bad["bands"].values()) != bad["audited"]


def test_the_nights_true_size_survives_a_card_that_raised() -> None:
    """#1270's property stated as arithmetic: nothing observed leaves every counter.

    A card whose audit RAISED never reaches `results`, so `audited` alone under-describes the
    night. The pair must reconstitute it — otherwise the rollup reports a partial night as a
    whole one, which is this row's entire subject.
    """
    block = _gq.corpus_block([_clean_result()], _gq.MODE_DET_ONLY, audit_failed=("B4", "B7"))
    assert block["audited"] == 1
    assert block["audit_failed"] == 2
    assert block["audited"] + block["audit_failed"] == 3
    assert list(block["audit_failed_jobs"]) == ["B4", "B7"], "the lost cards are NAMED, not counted"


# ---------------------------------------------------------------------------
# #1397 — the craft walks are BOUNDED, and the bound was neither counted nor
# disclosed. `lint_dead_scaffold` had been computing its shortfall since it was
# built and writing it into `detail`; `Layer1Result.findings()` printed a craft
# detail only when `measured and flagged` or `not measured`, so a bounded-clean
# lint was neither and the sentence reached nobody.
# ---------------------------------------------------------------------------


def _many_py(root: Path, n: int, *, marker: bool = False) -> Path:
    (root / "app").mkdir(parents=True, exist_ok=True)
    for i in range(n):
        (root / "app" / f"m{i}.py").write_text("VALUE = 1\n", encoding="utf-8")
    if marker:
        # Must be a string from `_SCAFFOLD_MARKERS`, not a plausible-looking invention.
        (root / "app" / "zzz_scaffold.py").write_text("X = 'PLACEHOLDER'\n", encoding="utf-8")
    return root


def test_a_bounded_scaffold_walk_says_its_coverage_was_partial(tmp_path):
    """A tree past the 400-file bound reported an unqualified "no seed scaffold placeholder
    found" having examined an arbitrary prefix of it."""
    repo = _many_py(tmp_path / "big", 450)
    finding = l1.lint_dead_scaffold(repo)

    assert finding.measured, "the lint ran"
    assert finding.flagged is False, "precondition: nothing found in the part it read"
    assert finding.coverage_partial, "a bounded walk claimed complete coverage"
    assert "bound" in finding.detail, f"the reader must be told which bound was hit: {finding.detail!r}"


def test_a_small_tree_is_walked_WHOLE_and_says_so(tmp_path):
    """The toggle. A `coverage_partial` that is always true carries no information."""
    repo = _many_py(tmp_path / "small", 5)
    finding = l1.lint_dead_scaffold(repo)

    assert finding.measured and finding.flagged is False
    assert not finding.coverage_partial, "a complete walk claimed partial coverage"
    assert "partial" not in finding.detail


def test_vendored_trees_do_not_consume_the_bound(tmp_path):
    """The skip-list. Before it, a delivery shipping a `.venv` could spend all 400 slots
    inside site-packages and never reach the coder's own code — reporting a clean result
    about a tree it had not looked at.
    """
    repo = tmp_path / "vendored"
    (repo / ".venv" / "lib" / "site-packages" / "dep").mkdir(parents=True)
    for i in range(500):
        (repo / ".venv" / "lib" / "site-packages" / "dep" / f"v{i}.py").write_text(
            "VALUE = 1\n", encoding="utf-8")
    (repo / "app").mkdir(parents=True)
    # The real marker, read off `_SCAFFOLD_MARKERS`. My first draft invented one
    # ("TODO: replace this scaffold") and the test failed for that reason rather than the
    # one it names — a fixture asserting against a string the lint has never looked for.
    (repo / "app" / "real.py").write_text("X = 'PLACEHOLDER'\n", encoding="utf-8")

    finding = l1.lint_dead_scaffold(repo)
    assert finding.flagged is True, (
        "the coder's own scaffold marker was hidden behind a vendored tree — the walk never "
        "reached it"
    )
    assert not finding.coverage_partial, "the real tree is tiny once the vendored one is skipped"


def test_a_truncated_entry_point_walk_does_NOT_accuse(tmp_path):
    """`no_entry_point.flagged` is a band-B trigger, so a false flag costs the operator a
    worse verdict on a build that may be fine.

    The module already refuses to accuse when a packaging manifest could not be read — "the
    flag would be an accusation the evidence does not carry". A walk that stopped at the
    bound is the same shape: the entry point may simply be past it.
    """
    repo = _many_py(tmp_path / "huge", 850)   # no demo.py / __main__.py / bin / console-script
    finding = l1.lint_no_entry_point(repo, "python-lib")

    assert finding.measured
    assert finding.flagged is False, (
        "a truncated walk produced an ACCUSATION the evidence does not carry, and that "
        "accusation bands B"
    )
    assert finding.coverage_partial
    assert "bound" in finding.detail


def test_the_partial_coverage_sentence_REACHES_the_shipping_surface(tmp_path):
    """The whole point of #1397's second half, and the reason a lock on `detail` alone would
    have been worthless: the sentence existed and `findings()` dropped it.
    """
    repo = _many_py(tmp_path / "big2", 450)
    result = l1.Layer1Result(
        regression=l1.RegressionFinding(False, False, "no behaviour change", measured=True),
        dead_scaffold=l1.lint_dead_scaffold(repo),
        stale_readme=l1.CraftFinding(False, "", measured=True),
        no_entry_point=l1.CraftFinding(False, "", measured=True),
        ruff_findings=None, surface="python-lib")

    lines = " ".join(result.findings())
    assert "PARTIAL" in lines, (
        f"the shipped report dropped the partial-coverage caveat the object was carrying: {lines!r}"
    )
    assert "lower bound" in lines


def test_a_clean_complete_lint_adds_NOTHING_to_the_report(tmp_path):
    """The toggle for the shipping surface. Without it, a `findings()` hard-wired to always
    append would pass the test above and fill every clean report with noise.
    """
    repo = _many_py(tmp_path / "small2", 5)
    result = l1.Layer1Result(
        regression=l1.RegressionFinding(False, False, "no behaviour change", measured=True),
        dead_scaffold=l1.lint_dead_scaffold(repo),
        stale_readme=l1.CraftFinding(False, "", measured=True),
        no_entry_point=l1.CraftFinding(False, "", measured=True),
        ruff_findings=None, surface="python-lib")

    lines = " ".join(result.findings())
    assert "PARTIAL" not in lines, f"a complete lint claimed partial coverage: {lines!r}"


# ---------------------------------------------------------------------------
# #1231 / DoD row 13 — seed divergence's reconciliation lock.
#
# Row 13's audit verdicted this grader SOUND but it carried no external check of
# its own arithmetic, which is the row's first clause verbatim: "a grader's own
# arithmetic is verified by something that is not that grader". Its three
# buckets — identical / diverged / unknown — are drawn over SEED_FILES, and the
# docstring already promises the third is "always NAMED, never folded silently
# into clean". Nothing asserted that promise from outside.
# ---------------------------------------------------------------------------


def _seed_and_delivery(tmp_path: Path, *, changed: set[str] | None = None):
    """A real seed tree and a delivery copied from it, honouring each spec's COMPARE MODE.

    Written against `SeedFileSpec` as it actually is — `rel_path`, and a `mode` that is either
    whole-file or toml-fields. My first draft guessed `spec.path` and fell back to `str(spec)`,
    which produced a filename out of the dataclass repr and failed with an OSError that said
    nothing about the real mistake. Read the surface, then write the fixture.
    """
    changed = changed or set()
    seed = tmp_path / "seed"
    repo = tmp_path / "delivery"
    for spec in l1.SEED_FILES:
        rel = spec.rel_path
        rewritten = rel in changed
        if spec.mode == l1.SEED_COMPARE_TOML_FIELDS:
            desc = "a real description of the pottery site" if rewritten else "PLACEHOLDER"
            seed_body = '[project]\ndescription = "PLACEHOLDER"\n'
            repo_body = f'[project]\ndescription = "{desc}"\n'
        else:
            seed_body = f"SEED CONTENT for {rel}\n"
            repo_body = (f"the coder rewrote {rel}\n" if rewritten else seed_body)
        for root, body in ((seed, seed_body), (repo, repo_body)):
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(body, encoding="utf-8")
    return seed, repo


def test_the_seed_buckets_account_for_every_file_examined(tmp_path):
    """The #1231 property stated for this instrument: every seed file the check looked at
    lands in EXACTLY ONE of identical / diverged / unknown.

    A file in none of them is a comparison that happened and was reported nowhere — the
    numerator and the denominator lost together, which is the shape row 13 exists to forbid.
    """
    seed, repo = _seed_and_delivery(tmp_path)
    finding = l1.lint_seed_divergence(repo, seed_root=seed)

    buckets = list(finding.identical) + list(finding.diverged) + list(finding.unknown)
    assert buckets, "precondition: the check examined something"
    assert len(buckets) == len(set(buckets)), (
        f"a file appears in more than one bucket, so the three do not partition: {buckets}"
    )
    assert finding.measured, "a comparison succeeded, so this is a measured result"


def test_a_file_that_could_not_be_compared_is_NAMED_not_dropped(tmp_path):
    """The docstring's own promise, asserted from outside it.

    An unreadable seed file must appear in `unknown`. Folding it into silence would let the
    check report a clean divergence result about a file it never read — the fail-open this
    instrument's tri-state exists to prevent.
    """
    seed, repo = _seed_and_delivery(tmp_path)
    real_read = Path.read_text
    victim = sorted(p.name for p in seed.rglob("*") if p.is_file())[0]

    def _blind(self, *a, **k):
        if self.name == victim and "seed" in str(self):
            raise OSError("permission denied")
        return real_read(self, *a, **k)

    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(Path, "read_text", _blind)
        finding = l1.lint_seed_divergence(repo, seed_root=seed)
    finally:
        monkeypatch.undo()

    named = list(finding.identical) + list(finding.diverged) + list(finding.unknown)
    assert any(victim in n for n in named), (
        f"a file that could not be compared vanished from every bucket: {named}"
    )


def test_the_partition_lock_is_not_vacuous(tmp_path):
    """The toggle. If the buckets were always empty the assertion above would pass on a
    grader that examined nothing, which is the vacuous shape row 13 is about.
    """
    seed, repo = _seed_and_delivery(tmp_path,
                                    changed={s.rel_path for s in l1.SEED_FILES})
    finding = l1.lint_seed_divergence(repo, seed_root=seed)
    total = len(finding.identical) + len(finding.diverged) + len(finding.unknown)
    assert total > 0, "the check reported no files at all — the partition proves nothing"
    assert finding.diverged, "a rewritten file must land in `diverged`, or the buckets are inert"


# ---------------------------------------------------------------------------
# #1385 item 1 — the craft seed sweep must not be Python-only
# ---------------------------------------------------------------------------


def _seed_copy(tmp_path, seed_name: str, *, rewrite_readme: bool):
    """A delivery that is a COPY of one seed tree, optionally with a written README."""
    src = Path("C:/Users/mrbla/agentic-setup/build-infra") / seed_name / "reference"
    if not src.is_dir():
        pytest.skip(f"seed tree {seed_name} not present on this box")
    repo = tmp_path / f"delivery-{seed_name}"
    repo.mkdir()
    readme = src / "README.md"
    if not readme.is_file():
        pytest.skip(f"seed {seed_name} has no README.md to copy")
    (repo / "README.md").write_text(
        "# Pottery studio\n\nA site for a small pottery studio.\n" if rewrite_readme
        else readme.read_text(encoding="utf-8", errors="replace"),
        encoding="utf-8",
    )
    return repo


def test_a_delivery_shipping_the_WEB_seed_readme_is_flagged(tmp_path):
    """#1385 item 1, measured on the 2026-08-14 B9 run before it was fixed.

    `build-infra/` holds a reference tree per surface, and this lint compared every delivery
    against `python` alone. The web seed README is 1,461 normalised characters; the Python
    one is 68. So a web delivery shipping its seed README untouched differed from the text it
    was compared against and was reported CLEAN — the exact false-clean this lint exists to
    retire, on the operator's stated priority surface.

    Last night's delivery normalised character-for-character identical to
    `web/reference/README.md`, still titled "Web project skeleton (BlarAI dispatch fleet)",
    mentioning the pottery studio zero times. Nothing flagged it."""
    repo = _seed_copy(tmp_path, "web", rewrite_readme=False)
    finding = l1.lint_seed_divergence(repo)
    assert finding.flagged, (
        f"a delivery shipping the untouched WEB seed README was not flagged: {finding.detail}"
    )
    assert "README.md" in finding.detail
    assert Path(finding.seed_root).parent.name == "web", (
        f"the finding should name the seed it actually matched, got {finding.seed_root}"
    )


def test_the_PYTHON_ONLY_root_still_misses_it_which_is_why_the_sweep_exists(tmp_path):
    """The toggle, and the proof this is not a vacuous test. Pinning the comparison back to the
    single Python tree reproduces the false clean exactly."""
    repo = _seed_copy(tmp_path, "web", rewrite_readme=False)
    finding = l1.lint_seed_divergence(repo, seed_root=l1.default_seed_root())
    assert not finding.flagged, (
        "the python-only comparison should MISS a web seed README — if this now catches it, "
        "the sweep is not what fixed the defect and the claim above is wrong"
    )


def test_a_delivery_whose_readme_was_actually_written_is_NOT_flagged(tmp_path):
    """Precision. Sweeping nine seed trees must not turn every delivery into a finding — a
    README the coder wrote byte-matches no reference tree."""
    repo = _seed_copy(tmp_path, "web", rewrite_readme=True)
    finding = l1.lint_seed_divergence(repo)
    assert not finding.flagged, (
        f"a written README was flagged as unchanged from a seed: {finding.detail}"
    )


def test_the_python_seed_is_still_caught_by_the_sweep(tmp_path):
    """The behaviour that already worked must keep working — widening the search must not
    trade one surface's coverage for another's."""
    repo = _seed_copy(tmp_path, "python", rewrite_readme=False)
    finding = l1.lint_seed_divergence(repo)
    assert finding.flagged, f"the python seed README stopped being caught: {finding.detail}"


def test_all_seed_roots_finds_every_surface_not_just_python():
    """The sweep's input. If this ever returns one tree again, the fix has silently reverted."""
    roots = l1.all_seed_roots()
    if not roots:
        pytest.skip("build-infra/ not present on this box")
    names = {r.parent.name for r in roots}
    assert "python" in names and "web" in names, f"expected python AND web seeds, got {names}"
    assert len(roots) > 1, "the sweep found a single tree — that is the defect, restored"
    assert all(r.name == "reference" for r in roots)
