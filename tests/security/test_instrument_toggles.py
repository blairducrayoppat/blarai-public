# enforces-rule: security_by_design.principles.every-control-is-tested-off -- instrument controls only
r"""The #1223 principle-12 pair, one per registered instrument: it BLOCKS, and it can't fake it.

``CLAUDE.md`` security_by_design #12 — *every control ships with a test proving it BLOCKS
when engaged and a toggle-test proving the probe FAILS when the lock is off, otherwise you
cannot distinguish "secure" from "test can't reach it"* — is what instances 1 through 6 of
the 2026-07-30 defect class shipped without. :mod:`shared.instrument_registry` makes the pair
a REQUIRED, RESOLVED field, and this module is where those named tests live. Every function
here is cited by name from a registry entry;
``test_instrument_registry.test_every_entry_names_a_live_toggle_and_seam_test`` fails if one
is renamed or deleted.

TWO KINDS, and the split is the point:

* a **TOGGLE** test drives a RENDERER over an unmeasured result and proves the output cannot
  be read as clean. Building that result by hand is correct — the renderer is the subject.
* a **SEAM** test drives the REAL entrypoint into a REAL failure and proves it RETURNS
  unmeasured. It may not substitute the producer, because that is precisely where the mocks
  lie: on 2026-07-30 one test injected a stand-in runner and proved the logic while never
  crossing the boundary (0.9 s substituted vs 5.67 s real), and another built fixtures in a
  shape the production parser forbids and ran 1416 green over a live defect.
  ``test_instrument_registry.test_every_seam_test_drives_the_real_entrypoint`` enforces the
  call; the discipline of failing for a REAL reason is enforced here, by construction — every
  seam test below fails on a missing tree, an absent seed, an unresolvable binary or an empty
  input, never on an injected error.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.fleet import image_placement, link_lint, swap_ops
from shared.fleet.coder_test_qa import CoderTestQAResult, scan_paths
from shared.fleet.oracle_mutation import is_measured, not_measured_evidence
from shared.fleet.swap_driver import SwapDriver
from tools.dispatch_harness.green_audit import GreenAuditResult, scan_tree
from tools.dispatch_harness.green_quality.band import band_reasons
from tools.dispatch_harness.green_quality import placeholder_prose as prose_mod
from tools.dispatch_harness.green_quality.card import (
    _caveat_from_prose,
    _caveat_from_security,
    build_card,
)
from tools.dispatch_harness.green_quality.constants import BAND_A, BAND_B
from tools.dispatch_harness.green_quality.layer1 import (
    PROBE_KIND_PYTHON_CALLABLE,
    CraftFinding,
    Layer1Result,
    Probe,
    ProbeSet,
    RegressionFinding,
    SeedDivergenceFinding,
    archetype_regression,
    lint_dead_scaffold,
    lint_no_entry_point,
    lint_seed_divergence,
    lint_stale_readme,
    run_ruff_advisory,
)
from tools.dispatch_harness.green_quality.mutation import evidence_stamp
from tools.dispatch_harness.green_quality.security import SecurityResult, scan_repo
from tools.dispatch_harness.green_quality.traceability import (
    FirstPartyIndex,
    TraceabilityResult,
    assess,
)

# A Layer-1 result whose every check RAN and found nothing — the control condition. Each
# toggle below flips exactly ONE check to unmeasured, so any difference in the rendered
# output is attributable to that check and not to the fixture.
_MEASURED_CLEAN = dict(
    regression=RegressionFinding(False, False, "no behaviour change", measured=True),
    dead_scaffold=CraftFinding(False, "no seed scaffold placeholder found", measured=True),
    stale_readme=CraftFinding(False, "README is not the skeleton default", measured=True),
    no_entry_point=CraftFinding(False, "a runnable entry point is present", measured=True),
    seed_divergence=SeedDivergenceFinding(False, "all files diverge", status="diverged"),
    ruff_findings=0,
    surface="python-lib",
)


def _layer1(**overrides: object) -> Layer1Result:
    """A measured-clean Layer-1 result with named checks flipped to unmeasured."""
    return Layer1Result(**{**_MEASURED_CLEAN, **overrides})  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# security scan
# ---------------------------------------------------------------------------


def test_security_scan_unmeasured_never_renders_clean() -> None:
    """TOGGLE: an unmeasured SecurityResult cannot reach band A, an is_clean() yes, a
    'clean' summary, or a card that stays silent about its own blind spot."""
    unmeasured = SecurityResult(measured=False, status="delivered tree not found")
    measured = SecurityResult(measured=True, status="scanned 12 file(s)", files_scanned=12)

    assert not unmeasured.is_clean()
    assert measured.is_clean()
    assert "could-not-determine" in unmeasured.summary()
    assert "clean" in measured.summary()

    band, _c, b_reasons = band_reasons(_layer1(), None, unmeasured)
    assert band == BAND_B, "an unmeasured security scan reached band A"
    assert any("NOT a clean result" in r for r in b_reasons)
    assert band_reasons(_layer1(), None, measured)[0] == BAND_A, (
        "the control condition did not reach band A, so the toggle proves nothing"
    )

    assert "could not run" in _caveat_from_security(unmeasured)
    assert _caveat_from_security(measured) == ""


def test_security_scan_seam_returns_unmeasured_on_a_missing_tree(tmp_path: Path) -> None:
    """SEAM: the real scanner over a tree that is not there returns measured=False."""
    result = scan_repo(tmp_path / "no-such-deliverable")
    assert result.measured is False
    assert not result.is_clean()
    assert "not found" in result.status

    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    assert scan_repo(tmp_path).measured is True, (
        "the real scanner reported unmeasured on a readable tree - the seam test would pass "
        "for the wrong reason"
    )


# ---------------------------------------------------------------------------
# placeholder-prose scan
# ---------------------------------------------------------------------------


def test_prose_scan_unmeasured_never_renders_clean() -> None:
    """TOGGLE: an unmeasured ProseResult cannot report clean, and — the state this instrument
    has and its sibling does not — neither can a tree that simply had no pages in it.

    THREE renderings are pinned rather than two, because this instrument's characteristic
    failure is not the two-way collapse but the FOUR-way one: a Python library and a
    well-written site are both 'no findings', and reporting them identically would let a night
    of libraries read as a night of finished websites."""
    unmeasured = prose_mod.ProseResult(measured=False, status="delivered tree not found")
    no_pages = prose_mod.ProseResult(measured=True, applicable=False,
                                     status="no delivered web page or template found in lib")
    written = prose_mod.ProseResult(measured=True, applicable=True, pages_scanned=4,
                                    status="read 4 page(s) and 0 template(s)")

    assert unmeasured.disposition() == prose_mod.DISPOSITION_UNMEASURED
    assert no_pages.disposition() == prose_mod.DISPOSITION_NOT_APPLICABLE
    assert written.disposition() == prose_mod.DISPOSITION_CLEAN

    assert not unmeasured.is_clean()
    assert not no_pages.is_clean(), (
        "a tree with no pages reported CLEAN - this scan approves what it read, and it read "
        "nothing here"
    )
    assert written.is_clean()

    assert "could-not-determine" in unmeasured.summary()
    assert "not-applicable" in no_pages.summary()
    assert "could-not-determine" not in written.summary()
    assert "no placeholder prose" in written.summary()

    # The three renderings must differ from one another, not merely each say something.
    rendered = {unmeasured.summary(), no_pages.summary(), written.summary()}
    assert len(rendered) == 3, f"two of the three states render identically: {rendered}"


def test_prose_scan_seam_returns_unmeasured_on_a_missing_tree(tmp_path: Path) -> None:
    """SEAM: the real scanner over a tree that is not there returns measured=False.

    The control half drives the SAME producer over a real page, because 'unmeasured on a
    missing tree' proves nothing if the scanner reports unmeasured on everything."""
    result = prose_mod.scan_repo(tmp_path / "no-such-deliverable")
    assert result.measured is False
    assert not result.is_clean()
    assert result.disposition() == prose_mod.DISPOSITION_UNMEASURED
    assert "not found" in result.status

    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text(
        "<html><head><title>Ridge Pottery Studio</title></head>"
        "<body><h1>Ridge Pottery Studio</h1>"
        "<p>We throw stoneware on the wheel in a converted barn outside Hexham.</p>"
        "</body></html>",
        encoding="utf-8")
    assert prose_mod.scan_repo(site).measured is True, (
        "the real scanner reported unmeasured on a readable tree - the seam test would pass "
        "for the wrong reason"
    )


def test_prose_scan_stays_quiet_on_a_written_site(tmp_path: Path) -> None:
    """QUIET: a real page with real (if plain) words scans measured-clean, bands A, and puts
    no caveat on the operator's card.

    The copy here is deliberately ORDINARY — short, unremarkable, the sort of thing a coder
    writes when nobody gave it much to go on. That is the case this scan must not convict:
    the line it grades is placeholder-versus-written, never good-versus-bad."""
    site = tmp_path / "site"
    (site / "about").mkdir(parents=True)
    (site / "index.html").write_text(
        "<!doctype html><html><head><title>Ridge Pottery Studio</title></head><body>"
        "<h1>Hand-thrown stoneware</h1>"
        "<p>Small-batch pots, fired in a gas kiln, sold from the studio door.</p>"
        "<img src='bowl.jpg' alt='A grey stoneware bowl on a workbench'>"
        "<form><input placeholder='you@example.com'><button>Join the list</button></form>"
        "</body></html>", encoding="utf-8")
    (site / "about" / "index.html").write_text(
        "<html><head><title>About the studio</title></head><body>"
        "<h2>About</h2><p>The studio opened in 2019 and runs two classes a week.</p>"
        "</body></html>", encoding="utf-8")

    result = prose_mod.scan_repo(site, "web")
    assert result.measured is True
    assert result.disposition() == prose_mod.DISPOSITION_CLEAN
    assert result.is_clean(), f"a written site produced findings: {result.findings_lines()}"
    assert result.pages_scanned == 2
    assert "could-not-determine" not in result.summary()
    assert _caveat_from_prose(result) == ""
    assert band_reasons(_layer1(), None, None, result)[0] == BAND_A


# ---------------------------------------------------------------------------
# traceability
# ---------------------------------------------------------------------------

_ORACLE = "from app import word_frequencies\n\ndef test_wf():\n    assert word_frequencies(['a']) == {'a': 1}\n"
_CRITERIA = [{"id": "c1", "tier": "behavior", "text": "the word frequency count is right",
              "check": "call word_frequencies"}]


def test_traceability_unmeasured_never_renders_a_ratio() -> None:
    """TOGGLE: an unavailable TraceabilityResult renders 'unavailable', never a coverage
    ratio, and can never be stamped GREEN-VERIFIED."""
    unavailable = TraceabilityResult(available=False, reason="first-party surface unresolved")
    assert "unavailable" in unavailable.fingerprint()
    assert "/" not in unavailable.fingerprint().split("(")[0], (
        "an unavailable result rendered something ratio-shaped"
    )
    assert unavailable.verified_class is False
    block = unavailable.to_block()
    assert block["available"] is False and block["verified_class"] is False
    assert block["reason"]


def test_traceability_seam_returns_unavailable_without_a_first_party_index() -> None:
    """SEAM: the real assessor, given a real oracle and real criteria but no resolved
    first-party surface, refuses to emit a number."""
    result = assess(_ORACLE, _CRITERIA)
    assert result.available is False
    assert "first-party" in result.reason
    assert "unavailable" in result.fingerprint()


# ---------------------------------------------------------------------------
# archetype regression probe
# ---------------------------------------------------------------------------


def test_regression_unmeasured_is_reported_not_silent() -> None:
    """TOGGLE: a RegressionFinding that could not run is STATED in the findings report and
    still cannot move the band."""
    unmeasured = RegressionFinding(False, False, "probe could not run on this archetype")
    findings = _layer1(regression=unmeasured).findings()
    assert any("regression probe NOT RUN" in f for f in findings), findings
    assert any("absent measurement" in f for f in findings)

    assert not any("NOT RUN" in f and "regression" in f
                   for f in _layer1().findings()), (
        "the control condition also reported NOT RUN, so the toggle proves nothing"
    )
    assert band_reasons(_layer1(regression=unmeasured), None, None)[0] == BAND_A, (
        "an unmeasured probe moved the band - it says nothing about the deliverable"
    )


def test_regression_seam_returns_unmeasured_without_a_reference_green(tmp_path: Path) -> None:
    """SEAM: the real probe with no reference GREEN to diff against returns measured=False."""
    repo = tmp_path / "repo"
    repo.mkdir()
    result = archetype_regression(repo, None, None)
    assert result.measured is False
    assert result.regressed is False and result.changed is False


# ---------------------------------------------------------------------------
# seed divergence
# ---------------------------------------------------------------------------


def test_seed_divergence_unknown_is_reported_not_silent() -> None:
    """TOGGLE: an unknown SeedDivergenceFinding is reported out loud, never as clean."""
    unknown = SeedDivergenceFinding(False, "no seed root resolved")
    assert unknown.measured is False
    findings = _layer1(seed_divergence=unknown).findings()
    assert any("seed divergence UNKNOWN" in f for f in findings), findings
    assert not any("UNKNOWN" in f for f in _layer1().findings()), (
        "the control condition also reported UNKNOWN, so the toggle proves nothing"
    )


def test_seed_divergence_seam_returns_unknown_without_a_seed_root(tmp_path: Path) -> None:
    """SEAM: the real lint with no resolvable seed directory returns status='unknown'."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# A real project\n", encoding="utf-8")
    result = lint_seed_divergence(repo, seed_root=tmp_path / "no-such-seed")
    assert result.status == "unknown"
    assert result.measured is False
    assert result.flagged is False


# ---------------------------------------------------------------------------
# advisory ruff
# ---------------------------------------------------------------------------


def test_ruff_not_run_renders_as_not_run() -> None:
    """TOGGLE: ruff_findings=None renders as NOT RUN, and 0 renders as measured-clean.

    The two must not render the same. They did until #1189, which is how an advisory lint
    that had never once executed read clean on every night the project had run.

    Both results are built as explicit :class:`Layer1Result` values rather than through this
    module's helper: the sentinel lives on the aggregate rather than on a result type of its
    own, and routing the one instrument whose status IS its count through a factory would
    hide the field this test exists to pin."""
    not_run = Layer1Result(**{**_MEASURED_CLEAN, "ruff_findings": None}).findings()
    measured_zero = Layer1Result(**{**_MEASURED_CLEAN, "ruff_findings": 0}).findings()

    assert any("ruff: NOT RUN" in f for f in not_run), not_run
    assert any("absent measurement, not a clean one" in f for f in not_run)
    assert any("ruff: 0 advisory findings (measured)" in f for f in measured_zero)
    assert not any("NOT RUN" in f for f in measured_zero)
    # And the band treats neither as a trigger — `None >= 10` must never be evaluated.
    assert band_reasons(_layer1(ruff_findings=None), None, None)[0] == BAND_A


def test_ruff_seam_returns_none_when_the_binary_cannot_be_resolved(tmp_path: Path) -> None:
    """SEAM: the real advisory lint, run against a working directory that does not exist,
    crosses the real subprocess boundary and returns None rather than 0.

    No injected runner: the failure is a genuine OSError from the real ``subprocess.run``,
    which is the same path #1189's unresolvable bare ``ruff`` command took."""
    result = run_ruff_advisory(tmp_path / "no-such-directory")
    assert result is None, (
        f"an unrunnable lint returned {result!r} - a count, however small, is a claim that "
        f"the lint ran"
    )


# ---------------------------------------------------------------------------
# craft lints (shared by all three entries — one CraftFinding contract)
# ---------------------------------------------------------------------------


def test_craft_lint_unreadable_repo_is_reported_not_silent() -> None:
    """TOGGLE: an unmeasured CraftFinding is stated in the report and cannot move the band.

    All THREE craft lints are exercised, not one as a stand-in for the family. They share a
    result type but each renders its own disclosure line, and a toggle that pinned only the
    README wording would let the other two drift silently - which is how a reader who learned
    to look for a marker stops finding it."""
    blind = CraftFinding(False, "repo not found at ghost (lint could not run)")
    assert blind.measured is False

    for kwarg, marker in (("dead_scaffold", "dead scaffold lint NOT RUN"),
                          ("stale_readme", "stale README lint NOT RUN"),
                          ("no_entry_point", "entry point lint NOT RUN")):
        layer1 = _layer1(**{kwarg: blind})
        findings = layer1.findings()
        assert any(marker in f for f in findings), (marker, findings)
        assert any("absent measurement" in f for f in findings), findings
        # An unmeasured lint states its absence but never accuses the coder.
        assert band_reasons(layer1, None, None)[0] == BAND_A, kwarg
        card = build_card("j1", "python-lib", BAND_A, layer1)
        assert card.caveat == "", "an unmeasured tidiness lint spent the card's single caveat"

    assert not any("NOT RUN" in f for f in _layer1().findings()), (
        "the control condition also reported NOT RUN, so the toggle proves nothing"
    )


def test_craft_lint_seam_returns_unmeasured_on_a_missing_tree(tmp_path: Path) -> None:
    """SEAM: all three real lints, over a tree that is not there, return measured=False.

    And over a REAL tree they return measured=True — without which this test would pass
    against a lint that had simply stopped working."""
    missing = tmp_path / "no-such-repo"
    for finding in (lint_dead_scaffold(missing),
                    lint_stale_readme(missing),
                    lint_no_entry_point(missing, "python-lib")):
        assert finding.measured is False, finding
        assert finding.flagged is False, finding

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("def go():\n    return 1\n", encoding="utf-8")
    (repo / "README.md").write_text("# Real project\n", encoding="utf-8")
    assert lint_dead_scaffold(repo).measured is True
    assert lint_stale_readme(repo).measured is True
    assert lint_no_entry_point(repo, "python-lib").measured is True


# ---------------------------------------------------------------------------
# coder-test QA
# ---------------------------------------------------------------------------


def test_coder_test_qa_unmeasured_is_not_clean() -> None:
    """TOGGLE: an unmeasured CoderTestQAResult is not clean, and says so in its evidence.

    This aligns the Python result with ``Invoke-CoderTestQa``'s ``.Measured``, whose callers
    already gate on it and never on ``.Findings.Count``."""
    unmeasured = CoderTestQAResult()
    measured = CoderTestQAResult(measured=True, files_scanned=3)

    assert unmeasured.clean is False, "an unexamined project reported clean"
    assert measured.clean is True, "the control condition was not clean, so nothing is proven"
    assert unmeasured.to_evidence()["measured"] is False
    assert measured.to_evidence()["measured"] is True


def test_coder_test_qa_seam_returns_unmeasured_on_no_test_files(tmp_path: Path) -> None:
    """SEAM: the real scanner over an empty path list, and over a file it cannot parse,
    returns measured=False — both are unexamined projects."""
    assert scan_paths([]).measured is False

    unparseable = tmp_path / "test_broken.py"
    unparseable.write_text("def test_(:\n", encoding="utf-8")
    result = scan_paths([str(unparseable)])
    assert result.measured is False, "a suite that would not parse reported as examined"
    assert result.clean is False
    assert result.unparsed == [str(unparseable)]

    good = tmp_path / "test_ok.py"
    good.write_text("def test_x():\n    assert 1 == 1\n", encoding="utf-8")
    assert scan_paths([str(good)]).measured is True


# ---------------------------------------------------------------------------
# green audit
# ---------------------------------------------------------------------------


def test_green_audit_unaudited_is_not_clean() -> None:
    """TOGGLE: an unaudited tree renders 'not-audited', never 'clean'.

    ``gamed`` deliberately stays False (an unaudited tree must not accuse the coder); the
    honesty lives in the rendered status, which is three-way."""
    unaudited = GreenAuditResult(audited=False)
    audited = GreenAuditResult(audited=True, files_scanned=9)

    assert unaudited.to_sidecar_dict()["green_audit"] == "not-audited"
    assert audited.to_sidecar_dict()["green_audit"] == "clean"
    # The downgrade signal is unchanged by the fix — the consumers read only "gamed".
    assert unaudited.gamed is False and audited.gamed is False


def test_green_audit_seam_returns_unaudited_on_a_missing_tree(tmp_path: Path) -> None:
    """SEAM: the real scanner over a tree that is not there returns audited=False."""
    result = scan_tree(tmp_path / "no-such-tree")
    assert result.audited is False
    assert result.to_sidecar_dict()["green_audit"] == "not-audited"

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("def go():\n    return 1\n", encoding="utf-8")
    assert scan_tree(repo).audited is True


# ---------------------------------------------------------------------------
# oracle mutation (dict-shaped evidence + a predicate)
# ---------------------------------------------------------------------------


def test_oracle_mutation_unmeasured_stamps_not_measured() -> None:
    """TOGGLE: the stamp renders 'not-measured (<reason>)' rather than a 0/0 score.

    ``0/0`` is not a clean sheet, and the predicate ``is_measured`` is the single place that
    distinction is made."""
    unmeasured = not_measured_evidence("tests/test_job_acceptance.py", "skipped-no-run-dir")
    assert is_measured(unmeasured) is False
    stamp = evidence_stamp(unmeasured, "run/oracle-mutation.json")
    rendered = json.dumps(stamp)
    assert "not-measured" in rendered, rendered
    assert "skipped-no-run-dir" in rendered


def test_oracle_mutation_seam_builds_unmeasured_evidence() -> None:
    """SEAM: the real evidence builder produces a blob the real predicate calls unmeasured,
    and a hand-built 'completed with mutants' blob is measured — so the predicate is
    discriminating rather than always answering no."""
    evidence = not_measured_evidence("tests/test_job_acceptance.py", "skipped-no-banked-oracle")
    assert is_measured(evidence) is False
    assert evidence["mutation_audit"] == "skipped-no-banked-oracle"

    measured = dict(evidence)
    measured.update({"mutation_audit": "run", "ran": 4, "killed": 3})
    assert is_measured(measured) is True, (
        "the predicate answers 'unmeasured' for everything, so the toggle proves nothing"
    )


def test_smoke_contract_unmeasured_never_renders_exercised() -> None:
    """TOGGLE: a capture that could not report renders the could-not-determine disposition,
    never the exercised one — and the operator-facing note claims nothing.

    This is the #1289 collapse aimed at #1289's own instrument. The whole point of the
    behaviour contract is that a GRADED declared check must not read like a heuristic guess;
    if the honesty channel itself could not tell 'the capture went blind' from 'the check ran
    and passed', the fix would carry the defect it was built to remove."""
    blind = dict(swap_ops._DESIGN_LOOP_FALLBACK)
    assert swap_ops.smoke_contract_is_measured(blind) is False
    assert swap_ops.smoke_contract_disposition(blind) == "could-not-determine"
    assert SwapDriver._smoke_contract_note(blind) == "", (
        "a contract-blind capture volunteered a claim about a contract it never saw"
    )

    # A producer that sets the bool while reporting a status that does not mean 'exercised'
    # is drifting; a predicate trusting the bool alone would launder that drift into a pass.
    lying = dict(blind, smoke_declared=True, smoke_measured=True,
                 smoke_status=swap_ops.SMOKE_ACTION_HOOK_MISSING)
    assert swap_ops.smoke_contract_is_measured(lying) is False
    assert swap_ops.smoke_contract_disposition(lying) == "declared-not-exercised"
    assert "did NOT run" in SwapDriver._smoke_contract_note(lying)


def test_smoke_contract_seam_returns_unavailable_on_a_blind_capture() -> None:
    """SEAM: the REAL coercion — the function every design-loop result passes through —
    builds an unmeasured blob from a producer that said nothing, while a real honoured
    payload is measured, so the predicate discriminates rather than always answering no.

    Driven with the producer's own PascalCase keys, because that is the shape the PowerShell
    half actually emits; a seam test over this side's snake_case would prove the two repos
    agree by assuming it."""
    silent = swap_ops._coerce_design_loop_result({})
    assert silent["smoke_status"] == ""
    assert swap_ops.smoke_contract_is_measured(silent) is False
    assert swap_ops.smoke_contract_disposition(silent) == "could-not-determine", (
        "an empty status fell through to a claim about the plan"
    )

    honoured = swap_ops._coerce_design_loop_result(
        {"SmokeDeclared": True, "SmokeMeasured": True, "SmokeStatus": "honoured"}
    )
    assert swap_ops.smoke_contract_is_measured(honoured) is True, (
        "the predicate answers 'unmeasured' for everything, so the toggle proves nothing"
    )
    assert swap_ops.smoke_contract_disposition(honoured) == "exercised"

    # Cross-repo drift, DECLARED half: a status this side does not know can never mint the
    # positive claim -- but it must not delete the DISCLOSURE either. "A contract existed and
    # this review did not grade it" is true however the JS side spells the status, so a rename
    # there degrades the DETAIL (the status rides verbatim in the note) and nothing else.
    # Resolving this to could-not-determine dropped a failed declared contract in silence,
    # because `_smoke_contract_note` is deliberately mute on that disposition.
    drifted_declared = swap_ops._coerce_design_loop_result(
        {"SmokeDeclared": True, "SmokeMeasured": True, "SmokeStatus": "some-future-status"}
    )
    assert swap_ops.smoke_contract_is_measured(drifted_declared) is False, (
        "an unrecognised status was laundered into 'exercised' by trusting the bool"
    )
    assert swap_ops.smoke_contract_disposition(drifted_declared) == "declared-not-exercised"
    note = SwapDriver._smoke_contract_note(drifted_declared)
    assert "did NOT run" in note and "some-future-status" in note, (
        "a declared contract that failed was dropped without a word because this side did "
        "not recognise the status string"
    )

    # Cross-repo drift, UNDECLARED half: with no evidence a contract existed, an unrecognised
    # status IS could-not-determine. Refusing to make a CLAIM on unparseable evidence is right;
    # refusing to make a DISCLOSURE is not, and only this pair distinguishes the two.
    drifted_blind = swap_ops._coerce_design_loop_result(
        {"SmokeDeclared": False, "SmokeMeasured": False, "SmokeStatus": "some-future-status"}
    )
    assert swap_ops.smoke_contract_disposition(drifted_blind) == "could-not-determine"
    assert swap_ops.smoke_contract_is_measured(drifted_blind) is False
    assert SwapDriver._smoke_contract_note(drifted_blind) == ""

    # A CAPTURE CRASH on a declared contract is the same disclosure, and this is the case the
    # reordering also moved -- stated here rather than left as a silent side effect of it.
    # capture-web-cdp.mjs emits `unavailable` when the evaluate block threw AFTER reading a valid
    # spec: declared=true, and behaviour that never reached a verdict. The reader knows a contract
    # existed and was not graded, so it is not contract-BLIND and could-not-determine under-reports
    # it. The note stays blame-free (it names the status and says this review did not grade it), so
    # disclosing costs nothing. Every legitimately blind path -- WinUI, the msedge fallback, a
    # fail-soft critique, a legacy producer -- carries declared=False and is untouched, which is
    # what `blind` and `drifted_blind` above pin.
    crashed = swap_ops._coerce_design_loop_result(
        {"SmokeDeclared": True, "SmokeMeasured": False, "SmokeStatus": "unavailable"}
    )
    assert swap_ops.smoke_contract_disposition(crashed) == "declared-not-exercised"
    assert "did NOT run" in SwapDriver._smoke_contract_note(crashed)


# ---------------------------------------------------------------------------
# delivered-site link resolution (dict-shaped report + a predicate)
# ---------------------------------------------------------------------------


def test_link_lint_unmeasured_never_renders_clean() -> None:
    """TOGGLE: a scan that never followed a link cannot render as a site whose links work.

    Hand-built on purpose — the RENDERERS are the subject. BOTH of them, because they speak
    to different readers and a disclosure that reached only one would leave the other
    reporting a clean delivery: ``format_operator_summary`` is what the Lead Architect reads,
    and ``_with_link_report`` writes the line that lands in ``exec-smoke.log`` and in the
    coder's feedback.

    Three states are pinned rather than two. A DISCLOSURE ("nobody followed these links") and
    a FINDING ("this link leads nowhere") are different facts with different urgencies, and
    the third — a measured scan with nothing to say — has to be SILENT, or an instrument that
    speaks on every healthy run teaches the reader to skim the whole caveat block."""
    unmeasured = {
        "schema": "link-lint/v1", "checked": False,
        "reason": "site directory does not exist: /nowhere",
        "findings": [], "hard": False, "files_scanned": 0, "references": 0, "counts": {},
        "not_measured": ["nothing was scanned: the site directory does not exist"],
    }
    clean = {
        "schema": "link-lint/v1", "checked": True, "reason": "",
        "findings": [], "hard": False, "files_scanned": 2, "references": 9,
        "counts": {"resolved": 9, "broken": 0, "undecidable": 0, "external": 0, "in_page": 0},
        "not_measured": [],
    }
    broken = {
        **clean, "hard": True,
        "counts": {**clean["counts"], "resolved": 8, "broken": 1},
        "findings": [{"rule": "broken-link", "severity": link_lint.SEVERITY_HIGH,
                      "message": "'piece-detail.html' points at a page that is not in the "
                                 "delivered site.",
                      "reference": "piece-detail.html?id=${piece.id}",
                      "file": "pieces.html", "line": 41}],
    }

    assert link_lint.is_measured(unmeasured) is False
    assert link_lint.is_measured(clean) is True, (
        "the predicate answers 'unmeasured' for everything, so the toggle proves nothing"
    )

    assert "did not run" in link_lint.format_operator_summary(unmeasured)
    assert "leads somewhere real" not in link_lint.format_operator_summary(unmeasured), (
        "a scan that opened no page reported that every link it could follow works"
    )
    assert "leads somewhere real" in link_lint.format_operator_summary(clean), (
        "the control condition did not render clean, so the toggle proves nothing"
    )

    # The evidence line: DISCLOSURE, FINDING and SILENCE, and the declared marker is what
    # keeps the first two apart for a reader who learned to look for it.
    assert "links NOT checked" in swap_ops._with_link_report(
        {"evidence": "served + loaded"}, unmeasured)["evidence"]
    assert "1 broken link(s)" in swap_ops._with_link_report(
        {"evidence": "served + loaded"}, broken)["evidence"]
    assert swap_ops._with_link_report(
        {"evidence": "served + loaded"}, clean)["evidence"] == "served + loaded", (
        "a measured, clean link report spent an evidence line saying nothing"
    )


def test_link_lint_seam_returns_unmeasured_on_a_site_with_no_pages(tmp_path: Path) -> None:
    """SEAM: the real resolver, over two REAL degraded trees, returns an unmeasured report.

    Two trees, because they are different failures and the module reaches them by different
    paths: a site directory that is not there, and a directory that IS there and holds no
    page or script for a link to live in. The second is the one that matters — four empty
    scaffolds returned ``checked: true, hard: false`` on this module's first sweep, which is
    a clean bill of health issued over nothing.

    Both failures come from the filesystem, never from an injected error. The control half
    drives the SAME producer over a real page, because 'unmeasured on an empty tree' proves
    nothing if the resolver reports unmeasured on everything."""
    absent = link_lint.lint_site(tmp_path / "no-such-delivery")
    assert link_lint.is_measured(absent) is False
    assert absent["counts"] == {}, "counts were published for a tree nothing ever opened"
    assert "does not exist" in absent["reason"]

    site = tmp_path / "site"
    site.mkdir()
    (site / "README.md").write_text("# nothing built here yet\n", encoding="utf-8")
    hollow = link_lint.lint_site(site)
    assert link_lint.is_measured(hollow) is False, (
        "a served root holding no page reported a measured scan - that is a clean result "
        "issued over nothing, which is the exact shape this instrument exists to refuse"
    )
    assert hollow["files_scanned"] == 0
    assert hollow["counts"] == {}
    assert "NOTHING was checked" in " ".join(hollow["not_measured"])

    (site / "index.html").write_text(
        "<!doctype html><html><body><a href='README.md'>the readme</a></body></html>",
        encoding="utf-8")
    assert link_lint.is_measured(link_lint.lint_site(site)) is True, (
        "the real resolver reported unmeasured on a readable page - the seam test would pass "
        "for the wrong reason"
    )


# ---------------------------------------------------------------------------
# delivered-site media placement (dict-shaped report + a predicate)
# ---------------------------------------------------------------------------


def test_image_placement_ungraded_never_renders_clean() -> None:
    """TOGGLE: THREE states, because two of them would collapse the one that costs the most.

    A grading pass that COULD NOT run, a delivery that genuinely HAS no media, and a graded
    gallery with nothing wrong are three different facts. Folding the middle into either
    neighbour is #1342 in miniature: read as 'graded and fine' it is a false clean over a
    site with no pictures at all, and read as 'could not grade' it is a false alarm on a
    delivery that is simply a text site. Hand-built results throughout — the renderers are
    the subject, and both are pinned because they reach different readers."""
    ungraded = {
        "schema": "image-placement/v1", "checked": False, "nothing_to_grade": False,
        "reason": "site directory does not exist: /nowhere",
        "findings": [], "hard": False, "checks": {}, "counts": {},
        "not_measured": ["nothing was graded: the site directory does not exist"],
    }
    no_media = {
        **ungraded, "nothing_to_grade": True,
        "reason": "this site declares no media: no image files under the served root and no "
                  "data file listing items with pictures",
        "not_measured": ["NOTHING was graded: the delivery contains no images and no item data"],
    }
    graded = {
        "schema": "image-placement/v1", "checked": True, "nothing_to_grade": False, "reason": "",
        "findings": [], "hard": False,
        "checks": {"item_placement": {"checked": True, "reason": ""},
                   "asset_usage": {"checked": True, "reason": ""}},
        "counts": {"items": 4, "items_with_image": 4, "items_without_image": 0,
                   "distinct_item_images": 4, "max_items_per_image": 1,
                   "items_with_missing_image": 0, "image_assets": 6,
                   "unreferenced_assets": 0, "referenced_assets": 6, "exempt_assets": 0},
        "not_measured": ["no image is ever opened"],
    }
    repeated = {
        **graded, "hard": True,
        "counts": {**graded["counts"], "distinct_item_images": 2, "max_items_per_image": 3},
        "findings": [{"rule": "repeated-item-image", "severity": image_placement.SEVERITY_HIGH,
                      "message": "'assets/mug.png' is the declared picture of 3 different "
                                 "products.",
                      "reference": "assets/mug.png", "item": "Classic Mug",
                      "file": "data/pieces.json"}],
    }

    assert image_placement.is_graded(ungraded) is False
    assert image_placement.is_graded(no_media) is False, (
        "a delivery with nothing to grade read as a graded pass - it publishes no counts, so "
        "reading it as measured puts a clean bill of health on an absent result"
    )
    assert image_placement.is_graded(graded) is True, (
        "the predicate answers 'ungraded' for everything, so the toggle proves nothing"
    )

    assert "did not run" in image_placement.format_operator_summary(ungraded)
    assert "nothing to grade" in image_placement.format_operator_summary(no_media)
    assert "did not run" not in image_placement.format_operator_summary(no_media), (
        "a text site with no pictures was reported as a grader that failed"
    )
    rendered = {image_placement.format_operator_summary(r)
                for r in (ungraded, no_media, graded)}
    assert len(rendered) == 3, f"two of the three states render identically: {rendered}"

    def evidence(report: dict) -> str:
        """The exec-smoke evidence line this report produces, from a fixed starting state."""
        return swap_ops._with_media_report({"evidence": "served + loaded"}, report)["evidence"]

    assert "media placement NOT graded" in evidence(ungraded)
    assert "no media to grade" in evidence(no_media)
    assert "1 media placement finding(s)" in evidence(repeated)
    assert evidence(graded) == "served + loaded", (
        "a graded gallery with nothing wrong spent an evidence line saying nothing"
    )


def test_image_placement_seam_returns_ungraded_on_a_site_with_no_media(tmp_path: Path) -> None:
    """SEAM: the real grader, over two REAL trees it cannot grade, returns an ungraded report.

    Two trees, and the pair is the point: a missing directory is a FAILURE to grade, while a
    real, well-formed, entirely textual site is an ABSENCE of anything to grade. Both are
    unmeasured and neither publishes a count, but they are not the same fact and the report
    keeps them apart. Both conditions come from the filesystem, never from an injected error.

    The control half drives the SAME producer over a delivery that does carry media, because
    'ungraded on an empty tree' proves nothing if the grader reports ungraded on everything."""
    absent = image_placement.grade_site(tmp_path / "no-such-delivery")
    assert image_placement.is_graded(absent) is False
    assert absent["nothing_to_grade"] is False, (
        "a missing tree was reported as a delivery that simply had no pictures"
    )
    assert absent["counts"] == {}

    site = tmp_path / "site"
    (site / "public").mkdir(parents=True)
    (site / "public" / "index.html").write_text(
        "<!doctype html><html><head><title>Ridge Pottery Studio</title></head><body>"
        "<h1>Ridge Pottery Studio</h1>"
        "<p>We throw stoneware on the wheel in a converted barn outside Hexham.</p>"
        "</body></html>", encoding="utf-8")
    textual = image_placement.grade_site(site)
    assert image_placement.is_graded(textual) is False, (
        "a delivery with no picture and no product list reported a graded pass"
    )
    assert textual["nothing_to_grade"] is True
    assert textual["counts"] == {}, "counts were published for a delivery that graded nothing"
    assert "NOTHING was graded" in " ".join(textual["not_measured"])

    (site / "public" / "assets").mkdir()
    (site / "public" / "assets" / "bowl.png").write_text("x", encoding="utf-8")
    (site / "public" / "index.html").write_text(
        "<!doctype html><html><body><h1>Ridge Pottery Studio</h1>"
        "<img src='assets/bowl.png' alt='A grey stoneware bowl'></body></html>",
        encoding="utf-8")
    assert image_placement.is_graded(image_placement.grade_site(site)) is True, (
        "the real grader reported ungraded on a delivery carrying media - the seam test "
        "would pass for the wrong reason"
    )


def test_several_unmeasured_instruments_each_keep_their_own_disclosure() -> None:
    """AGGREGATE: N instruments merging into ONE report do not collapse into one caveat.

    Three craft lints share a result type AND a renderer, which is the aggregate shape - and
    the reason disclosures are a LIST rather than a flag. Two instruments can each be
    unmeasured for a DIFFERENT reason, and folding them into a single "something did not run"
    loses which one, which is the same information loss as folding "did not run" into "found
    nothing", one level up.

    Pinned here because the registry models the aggregate implicitly - several entries share
    one renderer and are charged separately by their receivers - and an implicit property is
    one nobody notices breaking."""
    scaffold_blind = CraftFinding(False, "repo could not be walked (PermissionError)")
    readme_blind = CraftFinding(False, "README present but unreadable (README.md)")

    lines = _layer1(dead_scaffold=scaffold_blind, stale_readme=readme_blind).findings()
    disclosures = [line for line in lines if "NOT RUN" in line]
    assert len(disclosures) == 2, f"two blind lints collapsed into {disclosures}"
    assert any("could not be walked" in line for line in disclosures), disclosures
    assert any("unreadable" in line for line in disclosures), (
        "both lints reported, but the DISTINCT reasons were lost - a caveat list that does "
        "not carry why each instrument went blind is a flag wearing a list's shape"
    )


# ---------------------------------------------------------------------------
# THE QUIET CASE - an instrument that convicts a healthy run gets muted
# ---------------------------------------------------------------------------
#
# Three agents on 2026-07-30, working unrelated branches, independently arrived at the same
# warning about this registry: make eleven instruments loud, let ONE of them speak on healthy
# runs, and the operator learns to skim the caveat block -- at which point all eleven are
# silent, including the honest ones. A fail-loud control that convicts healthy configurations
# gets muted, and a muted control is worse than the silence it replaced.
#
# So each instrument owes a THIRD named case beyond principle 12's pair: driven over a real,
# healthy input it must report MEASURED and emit no disclosure. Every test below builds a real
# tree (or a real evidence blob) and calls the real producer -- "it stays quiet in production"
# is a claim about production, and a hand-built result cannot support it.


def test_security_scan_stays_quiet_on_a_healthy_tree(tmp_path: Path) -> None:
    """QUIET: a readable tree with no credential and no sink scans measured-clean, bands A,
    and puts no caveat on the operator's card."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (repo / "README.md").write_text("# Adder\n\nAdds two numbers.\n", encoding="utf-8")

    result = scan_repo(repo)
    assert result.measured is True
    assert result.is_clean(), f"a clean tree produced findings: {result.findings_lines()}"
    assert "could-not-determine" not in result.summary()
    assert _caveat_from_security(result) == ""
    assert band_reasons(_layer1(), None, result)[0] == BAND_A


def test_traceability_stays_quiet_on_a_resolvable_oracle() -> None:
    """QUIET: given a first-party index it CAN resolve, the assessor emits a real ratio
    rather than an unavailable disclosure.

    The index is built through the module's own public constructor from a root name - the
    same call `resolve_first_party` makes in production - rather than by hand-setting
    `resolved=True`, which would be the author agreeing with the author."""
    index = FirstPartyIndex.from_roots({"app"}, source="a delivered tree providing app.py")
    result = assess(_ORACLE, _CRITERIA, first_party=index)
    assert result.available is True, result.reason
    assert "unavailable" not in result.fingerprint()
    assert result.denominator == 1


def test_regression_stays_quiet_on_a_measured_clean_probe(tmp_path: Path) -> None:
    """QUIET: with a reference tree and a runnable probe, the real prober reports MEASURED
    and the report carries no NOT RUN line."""
    current, reference = tmp_path / "cur", tmp_path / "ref"
    for root in (current, reference):
        root.mkdir()
        (root / "app.py").write_text("def shout(s):\n    return s.upper()\n", encoding="utf-8")
    # The kind comes from the module's OWN constant, not a literal. A hand-typed "call" is
    # a shape `run_probe` rejects outright ("could-not-run: unknown probe kind"), and it made
    # this very test assert the unmeasured path while claiming to prove the measured one -
    # the fixture agreeing with its author about a vocabulary production defines.
    probe_set = ProbeSet(job_id="Q1", surface="python-lib", probes=(
        Probe(kind=PROBE_KIND_PYTHON_CALLABLE, inputs=("hi",), module="app", attr="shout"),
    ))

    result = archetype_regression(current, reference, probe_set)
    assert result.measured is True, result.detail
    assert result.regressed is False and result.changed is False
    findings = _layer1(regression=result).findings()
    assert not any("regression probe NOT RUN" in f for f in findings), findings


def test_seed_divergence_stays_quiet_on_a_diverged_delivery(tmp_path: Path) -> None:
    """QUIET: a delivery whose README differs from the seed's is measured-diverged, and the
    report carries no UNKNOWN line. The seed is a real directory the real lint diffs against."""
    seed, repo = tmp_path / "seed", tmp_path / "repo"
    seed.mkdir()
    repo.mkdir()
    (seed / "README.md").write_text("# project skeleton\n\nthe fleet seeds this.\n",
                                    encoding="utf-8")
    (repo / "README.md").write_text("# Expense Tracker\n\nTracks expenses.\n", encoding="utf-8")

    result = lint_seed_divergence(repo, seed_root=seed)
    assert result.measured is True, result.detail
    assert result.status == "diverged"
    assert result.flagged is False
    assert not any("seed divergence UNKNOWN" in f
                   for f in _layer1(seed_divergence=result).findings())


def test_ruff_stays_quiet_when_it_measured_zero(tmp_path: Path) -> None:
    """QUIET: the real advisory lint over a clean tree returns a COUNT, never None, so the
    report says 'measured' rather than NOT RUN.

    If ruff cannot be resolved in this environment the lint honestly returns None - the
    unmeasured case its seam test already owns - so this skips rather than asserting a number
    the box cannot produce."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

    count = run_ruff_advisory(repo)
    if count is None:
        pytest.skip("ruff is not resolvable here - the unmeasured path is the seam test's")
    assert isinstance(count, int)
    findings = Layer1Result(**{**_MEASURED_CLEAN, "ruff_findings": count}).findings()
    assert not any("ruff: NOT RUN" in f for f in findings), findings


def test_craft_lints_stay_quiet_on_a_real_tree(tmp_path: Path) -> None:
    """QUIET: all three real lints over a real, well-formed deliverable report MEASURED, flag
    nothing, and leave no NOT RUN line in the report or trigger in the band."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (repo / "demo.py").write_text("from app import add\n\nprint(add(2, 3))\n", encoding="utf-8")
    (repo / "README.md").write_text("# Adder\n\nAdds two numbers.\n", encoding="utf-8")

    dead = lint_dead_scaffold(repo)
    readme = lint_stale_readme(repo)
    entry = lint_no_entry_point(repo, "python-lib")
    for finding in (dead, readme, entry):
        assert finding.measured is True, finding
        assert finding.flagged is False, finding

    healthy = _layer1(dead_scaffold=dead, stale_readme=readme, no_entry_point=entry)
    for marker in ("dead scaffold lint NOT RUN", "stale README lint NOT RUN",
                   "entry point lint NOT RUN"):
        assert not any(marker in f for f in healthy.findings()), (marker, healthy.findings())
    assert band_reasons(healthy, None, None)[0] == BAND_A


def test_coder_test_qa_stays_quiet_on_a_real_suite(tmp_path: Path) -> None:
    """QUIET: a real, parseable test file carrying a genuine assertion scans measured AND
    clean - the scanner must not convict an exam that is fine."""
    good = tmp_path / "test_adder.py"
    good.write_text(
        "from app import add\n\n\n"
        "def test_add_sums_two_numbers():\n"
        "    assert add(2, 3) == 5\n",
        encoding="utf-8")

    result = scan_paths([str(good)])
    assert result.measured is True
    assert result.clean is True, f"a sound exam was convicted: {result.to_evidence()}"
    assert result.to_evidence()["measured"] is True


def test_green_audit_stays_quiet_on_a_scanned_tree(tmp_path: Path) -> None:
    """QUIET: a real tree with no grader-tampering fingerprint audits clean, and the sidecar
    says 'clean' rather than 'not-audited'."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

    result = scan_tree(repo)
    assert result.audited is True
    assert result.gamed is False, f"a clean tree was accused: {result.summary_line()}"
    assert result.to_sidecar_dict()["green_audit"] == "clean"


def test_oracle_mutation_stays_quiet_on_a_measured_audit() -> None:
    """QUIET: evidence the real builder produced and a real run then COMPLETED stamps a
    score, not a not-measured disclosure.

    The base blob comes from `not_measured_evidence` - the real producer of the shape - and
    only the fields a completed run writes are then set, so the stamp is exercised over
    production's own keys rather than a dict this test invented."""
    evidence = not_measured_evidence("tests/test_job_acceptance.py", "skipped-no-run-dir")
    evidence.update({"mutation_audit": "run", "ran": 4, "killed": 3,
                     "oracle_mutation_score": "3/4"})
    assert is_measured(evidence) is True

    stamp = json.dumps(evidence_stamp(evidence, "run/oracle-mutation.json"))
    assert "not-measured" not in stamp, stamp
    assert "3/4" in stamp


def test_smoke_contract_stays_quiet_where_no_contract_applies() -> None:
    """QUIET: the two dispositions that are NOT defects say nothing at all.

    This instrument's healthy population is dominated by runs that legitimately have no
    contract — every non-web dispatch reports ``not-declared``, and every contract-blind
    surface (WinUI, the msedge fallback, a legacy producer) reports ``unavailable``. An
    instrument that announced itself on those would speak on nearly every run in the fleet,
    and the registry's own warning is that one such instrument mutes the other eleven.

    So the silence here is deliberate and it is NOT the security scan's rule. An unmeasured
    security scan hides a live credential and must shout; an unmeasured behaviour contract on
    a surface that has no contracts costs a reader nothing. #823 settled the same trade for
    this channel's sibling: a console-blind run keeps today's behaviour rather than announcing
    its blindness."""
    no_contract = swap_ops._coerce_design_loop_result(
        {"SmokeDeclared": False, "SmokeMeasured": False, "SmokeStatus": "not-declared"}
    )
    assert swap_ops.smoke_contract_disposition(no_contract) == "no-contract-declared"
    assert SwapDriver._smoke_contract_note(no_contract) == "", (
        "a python-lib dispatch was told about a web behaviour contract it never had"
    )

    # And the clean-path sentence stays clean: no caveat, no disclosure, no hedge.
    note = SwapDriver._design_note(
        SwapDriver.__new__(SwapDriver),
        dict(no_contract, ok=True, should_iterate=False),
    )
    assert "behaviour check" not in note, note
    assert note.startswith("The design reviewer found nothing obvious to change"), note

    # The exercised case is the ONE positive it volunteers, and only because the sentence it
    # joins reads identically whether or not anything was graded.
    honoured = swap_ops._coerce_design_loop_result(
        {"SmokeDeclared": True, "SmokeMeasured": True, "SmokeStatus": "honoured"}
    )
    graded = SwapDriver._design_note(SwapDriver.__new__(SwapDriver), honoured)
    assert "the behaviour check the plan declared was exercised" in graded, graded


def test_link_lint_stays_quiet_on_a_site_whose_links_resolve(tmp_path: Path) -> None:
    """QUIET: an ordinary, correct little site scans measured and produces NO finding.

    Every reference here is a shape a coder writes without being told to: a relative page
    link, a site-absolute stylesheet, an image beside the page, an in-page anchor and an
    outbound link. None of them is a defect, and this instrument fires HARD - a finding here
    forces a FIX iteration - so a false accusation would send a coder to "fix" correct markup
    and teach the reader to stop believing the report.

    The exact counts are asserted, not just the absence of findings: an instrument that
    stayed quiet by resolving nothing would be quiet for the wrong reason."""
    site = tmp_path / "site"
    (site / "public" / "styles").mkdir(parents=True)
    (site / "public" / "images").mkdir(parents=True)
    (site / "public" / "index.html").write_text(
        "<!doctype html><html><head><title>Ridge Pottery Studio</title>"
        "<link rel='stylesheet' href='/styles/site.css'></head><body>"
        "<h1 id='top'>Hand-thrown stoneware</h1>"
        "<img src='images/bowl.png' alt='A grey stoneware bowl on a workbench'>"
        "<a href='about.html'>About the studio</a>"
        "<a href='#top'>Back to top</a>"
        "<a href='https://example.org/stockists'>Our stockist</a>"
        "</body></html>", encoding="utf-8")
    (site / "public" / "about.html").write_text(
        "<!doctype html><html><body><p>The studio opened in 2019.</p>"
        "<a href='index.html'>Home</a></body></html>", encoding="utf-8")
    (site / "public" / "styles" / "site.css").write_text("body { margin: 0; }\n", encoding="utf-8")
    (site / "public" / "images" / "bowl.png").write_text("x", encoding="utf-8")

    report = link_lint.lint_site(site)

    assert link_lint.is_measured(report) is True
    assert report["findings"] == [], f"a correct site was convicted: {report['findings']}"
    assert report["hard"] is False
    assert report["files_scanned"] == 2
    assert report["counts"] == {"resolved": 4, "broken": 0, "undecidable": 0,
                                "external": 1, "in_page": 1}

    summary = link_lint.format_operator_summary(report)
    assert "leads somewhere real" in summary
    assert "NOT confirmed working" not in summary, (
        "a site with nothing built at runtime was told some of its links were unchecked"
    )
    assert swap_ops._with_link_report(
        {"evidence": "served + loaded"}, report)["evidence"] == "served + loaded", (
        "a measured, clean link report spoke on a healthy run"
    )


def test_image_placement_stays_quiet_on_a_correctly_placed_gallery(tmp_path: Path) -> None:
    """QUIET: four products, four photographs, one logo and one hero banner. Silence.

    This is the population this instrument has to live in without nagging. The logo appears
    on every page and the hero on the home page, which is CORRECT and is the shape a repeat
    rule tuned by threshold would convict - the guard here is structural instead (only an
    asset an ITEM declares can reach the counter), and this test is what proves the structure
    holds on a real tree rather than in the docstring that claims it."""
    site = tmp_path / "site"
    (site / "public" / "assets").mkdir(parents=True)
    (site / "data").mkdir(parents=True)
    for page in ("index", "shop", "about"):
        (site / "public" / f"{page}.html").write_text(
            "<!doctype html><html><body>"
            "<img src='assets/logo.png' alt='Ridge Pottery Studio'>"
            "<img src='assets/hero.png' alt='The potter at the wheel'>"
            f"<p>{page}</p></body></html>", encoding="utf-8")
    for asset in ("logo", "hero", "mug", "bowl", "vase", "plate"):
        (site / "public" / "assets" / f"{asset}.png").write_text("x", encoding="utf-8")
    (site / "data" / "pieces.json").write_text(json.dumps([
        {"name": "Classic Mug", "category": "mugs", "image": "assets/mug.png"},
        {"name": "Deep Bowl", "category": "bowls", "image": "assets/bowl.png"},
        {"name": "Tall Vase", "category": "vases", "image": "assets/vase.png"},
        {"name": "Side Plate", "category": "plates", "image": "assets/plate.png"},
    ]), encoding="utf-8")

    report = image_placement.grade_site(site)

    assert image_placement.is_graded(report) is True
    assert report["findings"] == [], f"a correct gallery was convicted: {report['findings']}"
    assert report["hard"] is False
    assert report["checks"]["item_placement"]["checked"] is True
    assert report["checks"]["asset_usage"]["checked"] is True
    assert report["counts"]["items"] == 4
    assert report["counts"]["distinct_item_images"] == 4
    assert report["counts"]["max_items_per_image"] == 1
    assert report["counts"]["unreferenced_assets"] == 0, (
        "a logo and a hero used as page furniture were reported as pictures nobody uses"
    )

    summary = image_placement.format_operator_summary(report)
    assert "NOT CHECKED" not in summary
    assert "did not run" not in summary
    assert swap_ops._with_media_report(
        {"evidence": "served + loaded"}, report)["evidence"] == "served + loaded", (
        "a graded gallery with nothing wrong spoke on a healthy run"
    )
