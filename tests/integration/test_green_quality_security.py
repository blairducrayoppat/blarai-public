"""#1182 — the deterministic SECURITY floor over a banked GREEN's delivered tree.

The gap this suite locks: the coder fleet had no security bar anywhere. The builder brief
never asked for secure code, no grader looked for it, and no exam card mentioned it — so a
``node-web`` deliverable carrying a hardcoded credential, a string-built SQL query, or
unescaped markup written straight into the page passed every gate and was reported to a
non-technical operator as GREEN band A, "Looks clean".

Two proofs carry this file, per the standing rule that a control ships with evidence it
BLOCKS and evidence the probe FAILS when the lock is off:

* **The planted defect.** A fixture repo modelled on the B3/B5 budget-tracker shape ships a
  deliberate vulnerability. Driven through the REAL battery-close entry point
  (``BatterySummary.green_quality`` -> ``audit_greens``), it must reach the scorecard
  evidence, the band, the sidecar on disk, and the operator's plain-language card.
* **The toggle.** The SAME fixture, with the security scanner injected as a disabled stub,
  must NOT band C and must carry no security finding — proving the C is attributable to this
  control rather than to some other check that happened to fire on the same repo. Without
  this half, "secure" and "the test cannot reach it" look identical.

A third property is tested in its own right because it is the one that decides whether the
instrument can be trusted at all: a scan that could not run reports "could not determine" and
bands B. It never reports clean. Fail-soft is not fail-open.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.dispatch_harness.battery import BatterySummary
from tools.dispatch_harness.green_quality import (
    audit_green,
    audit_greens,
    band as band_mod,
    card as card_mod,
    render_kpi,
    security as sec,
)
from tools.dispatch_harness.green_quality.constants import (
    BAND_A,
    BAND_B,
    BAND_C,
    EV_SECURITY,
    RESERVED_EVIDENCE_KEYS,
    SEVERITY_HIGH,
    SEVERITY_INFO,
    SEVERITY_MEDIUM,
)
from tools.dispatch_harness.green_quality.layer1 import CraftFinding, Layer1Result, RegressionFinding
from tools.dispatch_harness.scorecard import Scorecard, validate

# ---------------------------------------------------------------------------
# Fixture trees — a B3/B5-shaped budget web app, once vulnerable and once not.
#
# The two differ ONLY in the planted defects, so any band difference between them is
# attributable to the security scan and to nothing else in the audit.
# ---------------------------------------------------------------------------

#: The planted defects, one per house rule the brief now states:
#: rule 4 (a real-shaped Stripe key in source), rule 5 (an f-string SQL query), rule 6
#: (a template literal interpolated into innerHTML).
_VULNERABLE_SERVER = '''
import sqlite3

STRIPE_KEY = "sk_live_51H8xQ2eZvKYlo2CabcdEfGh"

def entries_for(category):
    conn = sqlite3.connect("budget.db")
    return conn.execute(f"SELECT amount FROM entries WHERE category = '{category}'").fetchall()
'''

#: The same server written to the house rules: the key comes from the environment, the query
#: is parameterised. Byte-for-byte the same shape otherwise.
_SAFE_SERVER = '''
import os
import sqlite3

STRIPE_KEY = os.environ["STRIPE_KEY"]

def entries_for(category):
    conn = sqlite3.connect("budget.db")
    return conn.execute("SELECT amount FROM entries WHERE category = ?", (category,)).fetchall()
'''

_VULNERABLE_CLIENT = '''
function renderEntries(entries) {
  list.innerHTML = entries.map(e => `<li>${e.category}: ${e.amount}</li>`).join("");
}
'''

#: The safe client builds nodes and sets TEXT, which is the encoding house rule 6 asks for.
_SAFE_CLIENT = '''
function renderEntries(entries) {
  list.replaceChildren();
  for (const e of entries) {
    const li = document.createElement("li");
    li.textContent = `${e.category}: ${e.amount}`;
    list.appendChild(li);
  }
}
'''


def _make_web_repo(root: Path, *, vulnerable: bool) -> Path:
    """A budget-tracker web deliverable of the B3/B5 shape."""
    (root / "app").mkdir(parents=True, exist_ok=True)
    (root / "public").mkdir(parents=True, exist_ok=True)
    (root / "app" / "server.py").write_text(
        _VULNERABLE_SERVER if vulnerable else _SAFE_SERVER, encoding="utf-8")
    (root / "public" / "app.js").write_text(
        _VULNERABLE_CLIENT if vulnerable else _SAFE_CLIENT, encoding="utf-8")
    (root / "public" / "index.html").write_text(
        "<h1>Budget</h1><ul id='list'></ul>", encoding="utf-8")
    (root / "README.md").write_text("# Budget tracker\nAdd expenses and see totals.\n",
                                    encoding="utf-8")
    return root


def _disabled_scanner(repo, surface=""):
    """The lock turned OFF: a scanner that reports a measured, empty result.

    Deliberately claims ``measured=True`` — a stub returning "could not determine" would band
    B on its own and the toggle test could not tell a disabled lock apart from a working one.
    This stub is the only place in the tree allowed to assert a clean result it did not earn."""
    return sec.SecurityResult(measured=True, status="scanner disabled for this test",
                              files_scanned=0)


def _l1_clean() -> Layer1Result:
    """A Layer-1 result with nothing flagged, so a band is decided by the security scan alone.

    MEASURED-clean: a ``CraftFinding`` is born unmeasured (#1223), so a fixture that leaves
    the flag off asserts against "never looked" while its name claims "found nothing"."""
    clean = CraftFinding(False, "", measured=True)
    return Layer1Result(
        regression=RegressionFinding(False, False, "no behaviour change", measured=True),
        dead_scaffold=clean, stale_readme=clean, no_entry_point=clean,
        ruff_findings=None, surface="node-web")


# ---------------------------------------------------------------------------
# Each scan catches its planted defect — and stays quiet on the safe equivalent
# ---------------------------------------------------------------------------


def test_secret_scan_catches_a_provider_credential(tmp_path):
    repo = _make_web_repo(tmp_path / "vuln", vulnerable=True)
    result = sec.scan_repo(repo, "node-web")
    hits = [f for f in result.findings if f.rule == sec.RULE_PROVIDER_CREDENTIAL]
    assert hits, "a live-shaped Stripe key in source was not caught"
    assert hits[0].severity == SEVERITY_HIGH
    assert hits[0].path == "app/server.py"


def test_secret_scan_never_stores_the_secret_it_found(tmp_path):
    """Flagging a leaked credential must not copy it into the audit's own artifacts. The
    finding names the file and line; the value itself is masked."""
    repo = _make_web_repo(tmp_path / "vuln", vulnerable=True)
    result = sec.scan_repo(repo, "node-web")
    blob = json.dumps([f.__dict__ for f in result.findings]) + result.summary()
    assert "sk_live_51H8xQ2eZvKYlo2CabcdEfGh" not in blob
    assert "***" in blob


def test_sql_scan_catches_an_interpolated_query_but_not_a_parameterised_one(tmp_path):
    vuln = sec.scan_repo(_make_web_repo(tmp_path / "vuln", vulnerable=True))
    safe = sec.scan_repo(_make_web_repo(tmp_path / "safe", vulnerable=False))
    assert any(f.rule == sec.RULE_SQL_FROM_STRING for f in vuln.findings)
    assert not any(f.rule == sec.RULE_SQL_FROM_STRING for f in safe.findings)


def test_web_scan_catches_innerhtml_interpolation_but_not_textcontent(tmp_path):
    vuln = sec.scan_repo(_make_web_repo(tmp_path / "vuln", vulnerable=True), "node-web")
    safe = sec.scan_repo(_make_web_repo(tmp_path / "safe", vulnerable=False), "node-web")
    assert any(f.rule == sec.RULE_HTML_INJECTION for f in vuln.findings)
    assert not any(f.rule == sec.RULE_HTML_INJECTION for f in safe.findings)


def test_the_safe_repo_is_measured_clean(tmp_path):
    """The other half of every catch: the house-rule-compliant tree scores clean, so a
    finding means something. A scanner that flags everything grades nothing."""
    result = sec.scan_repo(_make_web_repo(tmp_path / "safe", vulnerable=False), "node-web")
    assert result.measured is True
    assert result.is_clean() is True
    assert result.findings == ()


def test_dangerous_sinks_are_graded_by_argument_shape(tmp_path):
    """``eval`` on a variable is a hole; ``eval`` on a literal is a smell. The severity split
    is what keeps the band from crying wolf on every occurrence of a scary identifier."""
    repo = tmp_path / "sinks"
    repo.mkdir()
    (repo / "m.py").write_text(
        "def run(expr):\n    return eval(expr)\n\ndef fixed():\n    return eval('2+2')\n",
        encoding="utf-8")
    findings = sec.scan_repo(repo).findings
    severities = {f.line: f.severity for f in findings if f.rule == sec.RULE_CODE_FROM_STRING}
    assert severities[2] == SEVERITY_HIGH
    assert severities[5] == SEVERITY_INFO


def test_placeholder_credentials_are_info_not_findings(tmp_path):
    """``api_key = "your-key-here"`` is a coder deferring a value, not a leak. It is recorded
    for transparency but never moves the band."""
    repo = tmp_path / "ph"
    repo.mkdir()
    (repo / "c.py").write_text('api_key = "your-key-here"\npassword = "CHANGEME"\n',
                               encoding="utf-8")
    result = sec.scan_repo(repo)
    assert result.worst_severity == SEVERITY_INFO
    assert result.at_or_above(SEVERITY_MEDIUM) == ()


def test_findings_in_the_test_suite_are_demoted_not_dropped(tmp_path):
    """A dummy credential in a fixture is expected; a real one pasted into a test is still in
    the shipped tree. One level down, never silence."""
    repo = tmp_path / "t"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "test_api.py").write_text(
        'password = "8f3b9c2e1a7d4f6b0c5e8a2d9f1b3c7e"\n', encoding="utf-8")
    result = sec.scan_repo(repo)
    assert result.findings, "a demoted finding must still be reported"
    assert result.worst_severity == SEVERITY_MEDIUM


# ---------------------------------------------------------------------------
# FAIL-SOFT, NEVER FAIL-OPEN — the property the whole control rests on
# ---------------------------------------------------------------------------


def test_a_scan_that_cannot_run_is_never_clean(tmp_path):
    """Three ways the scan can fail to happen. None of them may report clean."""
    for result in (sec.scan_repo(None),
                   sec.scan_repo(tmp_path / "does-not-exist"),
                   sec.scan_repo(tmp_path / "empty-tree")):
        assert result.measured is False
        assert result.is_clean() is False
        assert "could-not-determine" in result.summary()


def test_an_empty_findings_list_alone_does_not_mean_clean():
    """The type-level guard: an unmeasured result has no findings AND is not clean. Any
    caller reading ``not result.findings`` as 'safe' is reading it wrong, so the question is
    only answerable through :meth:`is_clean`."""
    unmeasured = sec.SecurityResult()
    assert unmeasured.findings == ()
    assert unmeasured.is_clean() is False


def test_the_findings_cap_never_truncates_away_a_high_severity_finding(tmp_path):
    """A cap that drops findings in scan order can drop the one HIGH sitting behind fifty
    INFO lines, and the band silently improves. Past the cap the scan keeps every HIGH and
    says the list is partial — a truncation must never be able to decide the band."""
    repo = tmp_path / "noisy"
    repo.mkdir()
    # 60 files of placeholder-grade noise (info), then one real injection sink.
    for i in range(60):
        (repo / f"noise{i:02d}.py").write_text('api_key = "your-key-here"\n', encoding="utf-8")
    (repo / "zz_last.py").write_text(
        'def q(conn, uid):\n    return conn.execute(f"SELECT * FROM t WHERE id = {uid}")\n',
        encoding="utf-8")
    result = sec.scan_repo(repo)
    assert result.measured is True
    assert result.worst_severity == SEVERITY_HIGH, "the HIGH behind the cap was truncated away"
    assert any(f.rule == sec.RULE_SQL_FROM_STRING for f in result.findings)
    assert "capped" in result.status
    assert band_mod.compute_band(_l1_clean(), None, result) == BAND_C


def test_a_scanner_that_raises_degrades_to_could_not_determine(tmp_path):
    """A scanner fault must not sink battery close, and must not vanish either."""
    def _boom(repo, surface=""):
        raise RuntimeError("scanner exploded")

    repo = _make_web_repo(tmp_path / "out" / "repos-archived" / "battery-b3-budget-web",
                          vulnerable=False)
    assert repo.is_dir()
    sc = Scorecard(job_id="B3", verdict="GREEN", repo="battery-b3-budget-web", run_id="R1")
    result = audit_green(sc, out_dir=tmp_path / "out", surface="node-web", security_scan=_boom)
    assert result.security.measured is False
    assert "RuntimeError" in result.security.status
    assert result.band == BAND_B


# ---------------------------------------------------------------------------
# EDITED INTO SILENCE — #1183's lesson, turned into regression locks
#
# #1183's `lint_stale_readme` keyed on marker STRINGS; an edit elsewhere removed the marker
# and the lint went blind to the file it existed to catch, silently, for a week. Every case
# below is a way this scanner was ACTUALLY silenced when first written — each verified by
# running it, not imagined — and each must now stay caught. A security lint that finds
# nothing is indistinguishable from a secure deliverable, so `is_clean()` is the assertion
# that matters: the finding may be graded down, it may never be erased.
# ---------------------------------------------------------------------------


def _scan_tree(tmp_path: Path, name: str, files: dict) -> sec.SecurityResult:
    root = tmp_path / name
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return sec.scan_repo(root, "node-web")


#: A real-shaped 32-character key, reused so each evasion differs ONLY in its dodge.
_KEY = "8f3b9c2e1a7d4f6b0c5e8a2d9f1b3c7e"


def test_silencing_a_placeholder_word_hidden_inside_a_real_key(tmp_path):
    """The sharpest vector found: the placeholder vocabulary DOWNGRADES a finding, so a real
    key containing the substring 'example' graded INFO and banded A — the word list silencing
    the finding from inside the secret's own value. Entropy now outranks the word list."""
    result = _scan_tree(tmp_path, "ex", {"a.py": 'API_KEY = "8f3b9c2example7d4f6b0c5e8a2d9f1b"\n'})
    assert result.worst_severity == SEVERITY_HIGH
    assert result.is_clean() is False


def test_silencing_by_renaming_the_identifier(tmp_path):
    """A word list of secret NAMES is silenced by a rename. Before the shape-based scan,
    `SVC_CRED = "<32 hex>"` returned is_clean() TRUE on a tree with a hardcoded credential.
    The finding is graded MEDIUM without a name to corroborate it — but it exists."""
    result = _scan_tree(tmp_path, "rn", {"a.py": f'SVC_CRED = "{_KEY}"\n'})
    assert result.is_clean() is False
    assert any(f.rule == sec.RULE_HIGH_ENTROPY_LITERAL for f in result.findings)


def test_silencing_by_hiding_the_secret_in_a_build_directory(tmp_path):
    """`dist/` was skipped as build output, so a deliverable whose only credential sat in the
    shipped bundle scored band A and reported CLEAN. A secret in a bundle is a shipped
    secret."""
    result = _scan_tree(tmp_path, "dst", {
        "app/ok.py": "x = 1\n",
        "dist/bundle.js": 'const k = "AKIAIOSFODNN7EXAMPLE";\n'})
    assert result.worst_severity == SEVERITY_HIGH
    assert result.is_clean() is False


def test_a_skipped_directory_that_exists_is_named_in_the_status(tmp_path):
    """Dependency trees are still skipped, and that blind spot is stated rather than left for
    the reader to infer that 'clean' meant 'everywhere'."""
    result = _scan_tree(tmp_path, "nm", {
        "app/ok.py": "x = 1\n",
        "node_modules/lib/i.js": 'var k = "AKIAIOSFODNN7EXAMPLE";\n'})
    assert "NOT scanned" in result.status and "node_modules" in result.status


def test_the_ast_path_catches_what_reformatting_hides(tmp_path):
    """A regex on `eval(` is a string match on source text. A call node is a structural fact,
    so splitting the call across lines cannot hide it."""
    result = _scan_tree(tmp_path, "ast", {"a.py": "def f(e):\n    return eval(\n        e\n    )\n"})
    assert result.worst_severity == SEVERITY_HIGH


def test_the_ast_path_catches_sql_with_no_sql_vocabulary(tmp_path):
    """The regex path needs a SQL verb AND a clause keyword — itself a word list, and one an
    unusual dialect out-runs. An f-string reaching `.execute()` is caught structurally with no
    vocabulary consulted at all."""
    result = _scan_tree(tmp_path, "sql", {"a.py": "def q(c, u):\n    return c.execute(f'grab rows for {u}')\n"})
    assert any(f.rule == sec.RULE_SQL_FROM_STRING for f in result.findings)


def test_both_detectors_run_because_neither_subsumes_the_other(tmp_path):
    """Switching Python to AST-only measurably LOST this case: the f-string is bound to a
    variable and executed a line later, which the AST sees only as a Name. The regex path
    still reads it. Union, not replacement — and deduped, so one sink is one finding."""
    result = _scan_tree(tmp_path, "both", {"a.py":
        'def q(c, u):\n    s = f"SELECT * FROM t WHERE id = {u}"\n    return c.execute(s)\n'})
    assert any(f.rule == sec.RULE_SQL_FROM_STRING for f in result.findings)
    single = _scan_tree(tmp_path, "dedup", {"a.py": "def f(e):\n    return eval(e)\n"})
    sinks = [f for f in single.findings if f.rule == sec.RULE_CODE_FROM_STRING]
    assert len(sinks) == 1, "the AST and regex paths double-reported the same sink"


def test_unparseable_python_still_gets_the_regex_path(tmp_path):
    """A syntactically broken deliverable must never be a silently unscanned one, and the
    fallback says so in the status."""
    result = _scan_tree(tmp_path, "bad", {"a.py": "def broken(:\n    eval(user_input)\n"})
    assert result.worst_severity == SEVERITY_HIGH
    assert "did not parse" in result.status


def test_long_camelcase_identifiers_are_not_credential_material(tmp_path):
    """The false positive the real archive caught: `runtimeIdentifierGraphPath` is 26
    alphanumeric characters over two character classes, so a class count alone flagged every
    camelCase name in a JSON file. Real tokens interleave digits; identifiers do not."""
    result = _scan_tree(tmp_path, "camel", {
        "a.json": '{"runtimeIdentifierGraphPath": "x", "originalTargetFrameworks": []}\n',
        "b.js": "const originalTargetFrameworks = 1;\n"})
    assert result.is_clean() is True


def test_a_uuid_constant_is_not_credential_material(tmp_path):
    result = _scan_tree(tmp_path, "uuid", {"a.py": 'ID = "3f2504e0-4f89-11d3-9a0c-0305e82c3301"\n'})
    assert result.is_clean() is True


# ---------------------------------------------------------------------------
# SEED PROOF (opportunistic) — the scan fires on REAL fleet output, not just fixtures
#
# A lint proven only against a defect its own author planted proves the regex, not the
# instrument. The battery archive holds the fleet's actual web deliverables, and B5's
# ``public/app.js`` interpolates habit names and error text straight into ``innerHTML`` —
# the exact construct house rule 6 now forbids, written by the coder unprompted.
#
# Honest scope, because it bounds what this evidence supports: the archived nights carrying
# these findings banked PARKED-HONEST and STALLED, not GREEN. No archived GREEN carries a
# high-severity finding today. This proves the construct is real fleet output that the audit
# would have surfaced had the night banked, NOT that a vulnerable deliverable was ever
# reported clean to the operator.
# ---------------------------------------------------------------------------

_REAL_ARCH = Path("C:/Users/mrbla/agentic-setup/state/battery")


def test_seed_proof_real_b5_archive_has_an_html_injection():
    """The real 2026-07-14 B5 habit tracker interpolates a user-supplied habit name into
    markup: ``namePara.innerHTML = `<strong>${habit.name}</strong>` ``. The scan must catch
    it at HIGH, and must not need a fixture to do so."""
    repo = _REAL_ARCH / "night-20260714-020002" / "repos-archived" / "battery-b5-habit-web"
    if not repo.is_dir():
        pytest.skip("real agentic-setup B5 archives not present")
    result = sec.scan_repo(repo, "node-web")
    assert result.measured is True
    high = [f for f in result.at_or_above(SEVERITY_HIGH)
            if f.rule == sec.RULE_HTML_INJECTION and f.path == "public/app.js"]
    assert high, "the real B5 deliverable's innerHTML interpolation was not caught"
    assert any("${habit.name}" in f.detail for f in high)


def test_seed_proof_the_web_seed_itself_is_clean():
    """The seed every web job extends uses ``textContent``. If the SEED ever ships an
    ``innerHTML`` interpolation, every web deliverable inherits the flaw from line one —
    so the starting point is asserted clean, not assumed."""
    seed = Path("C:/Users/mrbla/agentic-setup/build-infra/web/reference")
    if not seed.is_dir():
        pytest.skip("agentic-setup web seed not present")
    result = sec.scan_repo(seed, "node-web")
    assert result.measured is True
    assert result.at_or_above(SEVERITY_MEDIUM) == ()


# ---------------------------------------------------------------------------
# The band formula — where a finding becomes a consequence
# ---------------------------------------------------------------------------


def _sec_with(*severities: str) -> sec.SecurityResult:
    findings = tuple(
        sec.SecurityFinding(sec.RULE_SQL_FROM_STRING, s, "app/server.py", 7, "detail")
        for s in severities)
    return sec.SecurityResult(findings, measured=True, status="scanned 2 file(s)", files_scanned=2)


def test_band_high_severity_finding_is_C():
    assert band_mod.compute_band(_l1_clean(), None, _sec_with(SEVERITY_HIGH)) == BAND_C


def test_band_medium_severity_finding_is_B():
    assert band_mod.compute_band(_l1_clean(), None, _sec_with(SEVERITY_MEDIUM)) == BAND_B


def test_band_info_severity_never_moves_the_band():
    assert band_mod.compute_band(_l1_clean(), None, _sec_with(SEVERITY_INFO)) == BAND_A


def test_band_measured_clean_scan_is_A():
    clean = sec.SecurityResult(measured=True, status="scanned 4 file(s)", files_scanned=4)
    assert band_mod.compute_band(_l1_clean(), None, clean) == BAND_A


def test_band_unmeasured_scan_is_B_not_A():
    """The whole fail-closed argument in one assertion: 'we could not look' must not render as
    'we looked and it was fine'."""
    assert band_mod.compute_band(_l1_clean(), None, sec.SecurityResult()) == BAND_B
    _, _, b_reasons = band_mod.band_reasons(_l1_clean(), None, sec.SecurityResult())
    assert any("NOT a clean result" in r for r in b_reasons)


def test_band_names_the_security_trigger_in_plain_language():
    """A C the operator cannot act on is an opaque letter. The reason names the rule, the
    file and the line, and says what it means to someone who cannot read code."""
    _, c_reasons, _ = band_mod.band_reasons(_l1_clean(), None, _sec_with(SEVERITY_HIGH))
    assert c_reasons and "app/server.py:7" in c_reasons[0]
    assert "database queries by pasting text together" in c_reasons[0]


def test_band_without_a_supplied_scan_is_unchanged():
    """``security=None`` is 'this caller composed no scan', not 'the scan failed'. The
    existing Layer-1-only callers must keep their previous bands."""
    assert band_mod.compute_band(_l1_clean(), None) == BAND_A
    assert band_mod.compute_band(_l1_clean(), None, None) == BAND_A


# ---------------------------------------------------------------------------
# REACHABILITY — the planted defect through the REAL battery-close entry point
# ---------------------------------------------------------------------------


def _green_run(tmp_path: Path, *, vulnerable: bool):
    """Drive a GREEN B3 through ``BatterySummary.green_quality`` — the method
    ``battery.py`` itself calls at close — and return ``(scorecard, summary)``."""
    out_dir = tmp_path / "battery" / "20260730-000001"
    _make_web_repo(out_dir / "repos-archived" / "battery-b3-budget-web", vulnerable=vulnerable)
    sc = Scorecard(job_id="B3", verdict="GREEN", attribution="", repo="battery-b3-budget-web",
                   run_id="R1", evidence={"oracle_status": "passed"})
    summary = BatterySummary(scorecards=[sc], out_dir=str(out_dir))
    summary.green_quality(runs_dir=tmp_path / "runs", out_dir=out_dir,
                          job_surfaces={"B3": "node-web"})
    return sc, summary


def test_planted_defect_reaches_the_scorecard_the_band_and_the_card(tmp_path):
    """THE REACHABILITY PROOF. A control nothing calls is not a control, so this drives the
    real object through the real entry point and checks every surface the finding must
    arrive on: the band, the reserved evidence key, the sidecar on disk, the summary block,
    and the plain-language card the operator actually reads."""
    sc, summary = _green_run(tmp_path, vulnerable=True)

    # The verdict is untouched — this audit is advisory, and a security finding does not
    # change that. It changes what the operator is TOLD about the GREEN.
    assert sc.verdict == "GREEN" and sc.attribution == ""

    assert sc.evidence["green_quality_band"] == BAND_C
    assert "sql-built-from-string" in sc.evidence[EV_SECURITY]
    assert "provider-credential" in sc.evidence[EV_SECURITY]

    sidecar = json.loads((tmp_path / "runs" / "R1" / "green-quality.json").read_text(encoding="utf-8"))
    assert sidecar["security"]["measured"] is True
    assert sidecar["security"]["clean"] is False
    assert sidecar["security"]["worst_severity"] == SEVERITY_HIGH
    rules = {f["rule"] for f in sidecar["security"]["findings"]}
    assert {"provider-credential", "sql-built-from-string", "unescaped-html-sink"} <= rules

    assert summary.green_quality_block["security_high"] == 1
    assert summary.green_quality_block["security_unmeasured"] == 0
    assert summary.green_quality_block["bands"][BAND_C] == 1

    # The operator's card leads with the security caveat, in language he can act on.
    assert "worth removing" in sc.evidence["green_quality_card"] or \
           "pasting text together" in sc.evidence["green_quality_card"]

    # The night's KPI line carries the security counts.
    assert any("security: high=1" in line for line in render_kpi(summary.green_quality_block))


def test_the_safe_deliverable_bands_A_through_the_same_path(tmp_path):
    """The discrimination half: the same fixture written to the house rules banks band A with
    a measured-clean scan. Without this, band C proves only that the scan fires."""
    sc, summary = _green_run(tmp_path, vulnerable=False)
    assert sc.evidence["green_quality_band"] == BAND_A
    assert sc.evidence[EV_SECURITY].startswith("clean (")
    assert summary.green_quality_block["security_high"] == 0
    assert summary.green_quality_block["security_unmeasured"] == 0


def test_toggle_off_the_probe_fails_to_catch_the_same_defect(tmp_path):
    """THE TOGGLE PROOF. The identical vulnerable tree, with the scanner injected as a
    disabled stub, must NOT band C and must carry no security finding.

    This is what distinguishes 'the deliverable was insecure and we caught it' from 'some
    other check happened to fire'. If this test ever passes with band C, the C above was
    never attributable to the security scan and the control is decoration."""
    out_dir = tmp_path / "battery" / "20260730-000001"
    _make_web_repo(out_dir / "repos-archived" / "battery-b3-budget-web", vulnerable=True)
    sc = Scorecard(job_id="B3", verdict="GREEN", attribution="", repo="battery-b3-budget-web",
                   run_id="R1", evidence={"oracle_status": "passed"})
    block = audit_greens([sc], runs_dir=tmp_path / "runs", out_dir=out_dir,
                         job_surfaces={"B3": "node-web"}, security_scan=_disabled_scanner)

    assert sc.evidence["green_quality_band"] != BAND_C
    assert block["security_high"] == 0
    sidecar = json.loads((tmp_path / "runs" / "R1" / "green-quality.json").read_text(encoding="utf-8"))
    assert sidecar["security"]["findings"] == []


# ---------------------------------------------------------------------------
# The advisory contract still holds with the new stamp
# ---------------------------------------------------------------------------


def test_the_security_stamp_stays_inside_the_reserved_keys(tmp_path):
    """The audit is the SOLE writer of ``green_quality_*`` and writes nothing else. Adding a
    security key must not widen that surface — asserted here rather than merely documented,
    because an evidence key nobody constrains is how an advisory instrument grows a verdict."""
    sc, _ = _green_run(tmp_path, vulnerable=True)
    written = {k for k in sc.evidence if k.startswith("green_quality")}
    assert written <= RESERVED_EVIDENCE_KEYS
    assert EV_SECURITY in written
    assert sc.evidence["oracle_status"] == "passed"  # pre-existing evidence untouched


def test_the_scorecard_stays_schema_valid_after_the_security_stamp(tmp_path):
    """Evidence values are single-line and capped; a multi-line finding detail would make the
    durable scorecard artifact unwritable."""
    sc, _ = _green_run(tmp_path, vulnerable=True)
    assert validate(sc) == []
    assert "\n" not in sc.evidence[EV_SECURITY]


def test_a_security_finding_never_changes_a_verdict(tmp_path):
    """The load-bearing invariant of the whole package, re-asserted for the sharpest new
    signal: band C on a security hole is a caveat the operator reads, never a downgrade. A
    band that fed banking would be a new FALSE-DONE vector."""
    sc, _ = _green_run(tmp_path, vulnerable=True)
    assert sc.verdict == "GREEN"
    assert sc.attribution == ""
    assert sc.evidence["green_quality_band"] == BAND_C


# ---------------------------------------------------------------------------
# ADVERSARIAL-REVIEW REGRESSIONS (#1182). Two independent reviews drove real deliverables and
# real archives through this scan and found five ways it lied. Each is locked below with BOTH
# halves, because a noise fix that quietly narrows detection is the worse defect: the false
# positive must be gone AND the genuine construct it was confused with must still be caught.
# A scan the operator learns to ignore is a scan that is off.
# ---------------------------------------------------------------------------

#: The house-rule prose that ships in every coder worktree's ``AGENTS.md``. Verbatim in shape:
#: a rulebook cannot state an anti-pattern without containing it.
_HOUSE_RULE_MARKDOWN = """# Coder house rules

## Rule 5 - never build code or queries out of strings

Never `f"SELECT ... WHERE id = {user_id}"`, never `"SELECT ... " + user_id`. And never
`eval()`, `exec()`, `os.system()`, or `subprocess(..., shell=True)` on anything a user typed.
To run another program, pass an argument LIST (`subprocess.run(["git", "status"])`).
"""


def test_documentation_about_an_unsafe_construct_is_not_the_unsafe_construct(tmp_path):
    """A rulebook is not a vulnerability.

    ``AGENTS.md`` is copied into every coder worktree as its committed baseline, so it is in
    the delivered tree this scan walks. Once it spelled out the anti-patterns the fleet was
    being taught to avoid, the scan read its worked examples as three HIGH findings - a
    string-built SQL query, a code sink and a shell invocation - and EVERY Python deliverable
    banded C. The operator's card then told him his project "builds database queries by
    pasting text together", pointing at his own instructions.

    Markdown was already excluded from the entropy and web-injection scans; the sink scan is
    now consistent with its siblings."""
    repo = tmp_path / "documented"
    repo.mkdir()
    (repo / "AGENTS.md").write_text(_HOUSE_RULE_MARKDOWN, encoding="utf-8")
    (repo / "README.md").write_text(
        "Run it with `os.system('...')`? No - use `subprocess.run([...])`.\n", encoding="utf-8")
    (repo / "app.py").write_text("def total(rows):\n    return sum(rows)\n", encoding="utf-8")
    result = sec.scan_repo(repo, "python-lib")
    assert result.measured is True
    assert result.is_clean(), f"documentation graded as source: {result.findings_lines()}"


def test_the_same_constructs_in_executable_source_are_still_caught(tmp_path):
    """The other half. Excluding markdown must narrow the scan by FILE TYPE and by nothing
    else - the identical constructs in a ``.py`` file are code and still band C."""
    repo = tmp_path / "executable"
    repo.mkdir()
    (repo / "db.py").write_text(
        "import os\n"
        "def get(conn, user_id):\n"
        '    return conn.execute(f"SELECT * FROM users WHERE id = {user_id}")\n'
        "def run(cmd):\n"
        "    return os.system(cmd)\n",
        encoding="utf-8")
    result = sec.scan_repo(repo, "python-lib")
    rules = {f.rule for f in result.at_or_above(SEVERITY_HIGH)}
    assert sec.RULE_SQL_FROM_STRING in rules
    assert sec.RULE_SHELL_INVOCATION in rules
    assert band_mod.compute_band(_l1_clean(), None, result) == BAND_C


def test_a_credential_pasted_into_documentation_is_still_a_shipped_credential(tmp_path):
    """The deliberate asymmetry, and the reason this is not a blanket markdown exemption.
    "Does this file execute?" and "does this file carry a live key?" are different questions.
    A real key in a README ships exactly as a key in a config file does, so the SECRET scan
    still reads markdown even though the sink scan no longer does."""
    repo = tmp_path / "leaky-readme"
    repo.mkdir()
    (repo / "README.md").write_text(
        "## Setup\n\nExport your key:\n\n    AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE\n",
        encoding="utf-8")
    result = sec.scan_repo(repo, "python-lib")
    assert result.measured is True
    assert any(f.rule == sec.RULE_PROVIDER_CREDENTIAL for f in result.at_or_above(SEVERITY_HIGH))
    assert result.is_clean() is False


# ---------------------------------------------------------------------------
# `.exec()` is a method name in ordinary code
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("source", [
    "const m = /^(\\d+)-(\\d+)$/.exec(userInput);",          # the JavaScript RegExp API
    "while ((match = re.exec(text)) !== null) { out.push(match[1]); }",
    "db.exec(schemaSql);",                                   # better-sqlite3
    "cursor.exec(statement)",                                # a Python database handle
    "  .exec(sql)",                                          # chained; the dot leads its line
])
def test_a_dotted_exec_is_a_method_call_not_a_text_to_code_sink(source):
    """The finding the reviewer judged most likely to get the whole scan ignored.

    ``\\b(eval|exec|new Function)\\s*\\(`` matched after a dot, so the JavaScript regular-
    expression API, better-sqlite3's ``db.exec`` and any ``cursor.exec`` graded HIGH and
    forced band C on clean code. Only the BARE builtin executes text."""
    assert sec.scan_dangerous_sinks("app.js", source) == []


@pytest.mark.parametrize("source", [
    "value = eval(user_input)",
    "exec(downloaded_source)",
    "const fn = new Function(bodyText);",
    "  eval(payload)",                                       # indented, still bare
])
def test_the_bare_builtin_sink_is_still_high(source):
    """The other half: suppressing the dot must not suppress the sink itself."""
    findings = sec.scan_dangerous_sinks("app.js", source)
    assert [f.severity for f in findings] == [SEVERITY_HIGH], source
    assert findings[0].rule == sec.RULE_CODE_FROM_STRING


def test_the_javascript_regex_api_no_longer_bands_a_clean_web_app_C(tmp_path):
    """Reachability, not only the regex: a clean deliverable that uses ``.exec()`` to parse
    input must reach band A through the same path a vulnerable one reaches C."""
    repo = tmp_path / "clean-web"
    (repo / "public").mkdir(parents=True)
    (repo / "public" / "app.js").write_text(
        "const RANGE = /^(\\d+)-(\\d+)$/;\n"
        "function parse(value) {\n"
        "  const m = RANGE.exec(value);\n"
        "  return m ? [Number(m[1]), Number(m[2])] : null;\n"
        "}\n", encoding="utf-8")
    result = sec.scan_repo(repo, "node-web")
    assert result.is_clean(), result.findings_lines()
    assert band_mod.compute_band(_l1_clean(), None, result) == BAND_A


# ---------------------------------------------------------------------------
# An innerHTML COMPARISON is a read, not a write
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("source", [
    "if (el.innerHTML === previousMarkup) { return; }",
    "if (el.innerHTML == previousMarkup) { return; }",
    'if (node.innerHTML !== "") { node.remove(); }',
    "if (node.innerHTML != cached) { redraw(); }",
])
def test_an_innerhtml_comparison_is_not_an_injection_sink(source):
    """The pattern matched the first ``=`` of ``===``, leaving an ``rhs`` of ``"== previous..."``
    that is not a static literal - so a read-only comparison graded HIGH. ``!==`` never matched
    (``!`` is not ``=``), and that asymmetry was the tell that it was unintended."""
    assert sec.scan_web_injection("app.js", source) == []


@pytest.mark.parametrize("source", [
    "el.innerHTML = `<li>${item.name}</li>`;",
    "el.innerHTML += userSuppliedMarkup;",
    "container.outerHTML = buildMarkup(row);",
])
def test_a_real_innerhtml_assignment_is_still_high(source):
    """The other half: ``=`` and ``+=`` are still assignments and still sinks."""
    findings = sec.scan_web_injection("app.js", source)
    assert [f.rule for f in findings] == [sec.RULE_HTML_INJECTION], source
    assert findings[0].severity == SEVERITY_HIGH


# ---------------------------------------------------------------------------
# Where a tree LIVES says nothing about what is IN it
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ancestor", ["obj", "venv", "node_modules", ".vscode", "site-packages"])
def test_a_skipped_name_among_the_repos_ancestors_does_not_blind_the_scan(tmp_path, ancestor):
    """The skip check tested ``path.parts`` - every ancestor of the repo, not only the
    components inside it. A deliverable checked out under any directory carrying a skipped
    name was skipped ENTIRELY: ``files_scanned=0``, ``measured=False``. Fail-soft rather than
    fail-open, but the credential went unreported all the same."""
    repo = tmp_path / ancestor / "delivered-app"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "config.py").write_text('AWS = "AKIAIOSFODNN7EXAMPLE"\n', encoding="utf-8")
    result = sec.scan_repo(repo, "python-lib")
    assert result.measured is True, f"ancestor {ancestor!r} blinded the whole scan"
    assert result.files_scanned == 1
    assert result.worst_severity == SEVERITY_HIGH


def test_a_skipped_directory_inside_the_repo_is_still_skipped(tmp_path):
    """The other half: comparing relative to the root must not stop skipping the dependency
    trees the exclusion exists for. ``node_modules`` INSIDE the deliverable stays unread, and
    that blind spot stays named in the status."""
    repo = tmp_path / "with-deps"
    (repo / "node_modules" / "lib").mkdir(parents=True)
    (repo / "app").mkdir()
    (repo / "app" / "ok.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "node_modules" / "lib" / "i.js").write_text(
        'var k = "AKIAIOSFODNN7EXAMPLE";\n', encoding="utf-8")
    result = sec.scan_repo(repo, "python-lib")
    assert result.files_scanned == 1
    assert result.is_clean() is True
    assert "NOT scanned" in result.status and "node_modules" in result.status


def test_the_status_never_names_a_directory_outside_the_deliverable(tmp_path):
    """``_present_skipped_dirs`` had the same ancestor bug, so the blind-spot line could name
    a tree that is not part of what was delivered - a status the operator cannot act on, and
    one that misdescribes the scan's own coverage."""
    repo = tmp_path / "obj" / "delivered-app"
    repo.mkdir(parents=True)
    (repo / "main.py").write_text("x = 1\n", encoding="utf-8")
    result = sec.scan_repo(repo, "python-lib")
    assert "NOT scanned" not in result.status, result.status


# ---------------------------------------------------------------------------
# An interrupted scan must keep what it already found
# ---------------------------------------------------------------------------


def _interrupted_scan(tmp_path: Path, monkeypatch) -> sec.SecurityResult:
    """Drive the REAL ``scan_repo`` through a walk that dies after one file - the same
    ``OSError`` path a vanishing tree takes, not a hand-built result."""
    repo = tmp_path / "interrupted"
    repo.mkdir()
    (repo / "config.py").write_text('AWS = "AKIAIOSFODNN7EXAMPLE"\n', encoding="utf-8")
    (repo / "later.py").write_text("x = 1\n", encoding="utf-8")
    real_iter = sec._iter_source_files

    def dying_walk(root):
        for index, path in enumerate(real_iter(root)):
            if index >= 1:
                raise OSError("the tree went away mid-walk")
            yield path

    monkeypatch.setattr(sec, "_iter_source_files", dying_walk)
    return sec.scan_repo(repo, "python-lib")


def test_an_interrupted_scan_keeps_the_findings_it_already_made(tmp_path, monkeypatch):
    """``scan_repo`` deliberately returns findings AND ``measured=False`` when the walk dies.
    Both facts have to survive downstream: *we found this* and *we did not finish looking*."""
    result = _interrupted_scan(tmp_path, monkeypatch)
    assert result.measured is False
    assert result.is_clean() is False
    assert result.worst_severity == SEVERITY_HIGH
    assert "PARTIAL SCAN" in result.summary()
    assert sec.RULE_PROVIDER_CREDENTIAL in result.summary()


def test_an_interrupted_scan_that_found_a_credential_still_bands_C(tmp_path, monkeypatch):
    """``_security_reasons`` early-returned on ``not measured`` and discarded the findings, so
    a tree with a live AWS key banded B - while the KPI line counted the same finding as a
    HIGH. The instrument contradicted itself about one run, and the softer half is the one the
    operator reads."""
    result = _interrupted_scan(tmp_path, monkeypatch)
    band, c_reasons, b_reasons = band_mod.band_reasons(_l1_clean(), None, result)
    assert band == BAND_C
    assert any(sec.RULE_PROVIDER_CREDENTIAL in r for r in c_reasons)
    assert any("NOT a clean result" in r for r in b_reasons)


def test_an_interrupted_scan_tells_the_operator_about_the_credential(tmp_path, monkeypatch):
    """The card checked ``measured`` above the ``high`` branch, so the one deliverable that HAD
    something got a card saying only that a check had not run - which reads as "nothing to
    see". The finding leads now, because it is the half he can act on; the unfinished walk
    follows, because it is the half that stops "no problems found" reading as clean."""
    result = _interrupted_scan(tmp_path, monkeypatch)
    caveat = card_mod._caveat_from_security(result)
    assert "real account key written directly into the code" in caveat
    assert "did not finish" in caveat


def test_an_interrupted_scan_that_found_nothing_is_still_only_unknown(tmp_path, monkeypatch):
    """The regression that would be easy to introduce while fixing the one above: with no
    findings to report, an unmeasured scan must still refuse to read as clean."""
    repo = tmp_path / "quiet"
    repo.mkdir()
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")

    def dying_walk(root):
        raise OSError("unreadable from the first entry")
        yield  # pragma: no cover - marks this a generator

    monkeypatch.setattr(sec, "_iter_source_files", dying_walk)
    result = sec.scan_repo(repo, "python-lib")
    assert result.measured is False and result.findings == ()
    assert "could-not-determine" in result.summary()
    assert band_mod.compute_band(_l1_clean(), None, result) == BAND_B
    assert "could not run" in card_mod._caveat_from_security(result)


# ---------------------------------------------------------------------------
# BUILD OUTPUT IS NOT THE CODER'S CODE (#1182, second review round)
#
# The same failure shape as the AGENTS.md defect above, one directory over: grading something
# the coder did not author, and forcing C on every deliverable of a surface. The WinUI SDK
# bundles its own `map.html`, whose `innerHTML = p.join("")` sits under `bin/`. Every winui
# deliverable inherited band C from it before a coder wrote a line, and the operator's card
# told him his project "puts text straight into the page as page-code" while pointing at a
# Microsoft file he cannot fix.
#
# The fix is NOT to skip build output again -- that was the fail-open removed in 7c19aca0,
# where a deliverable whose only credential sat in `dist/` scored band A and reported CLEAN.
# It is the `.md` asymmetry carried through: *does this file carry a live key* (scan it,
# wherever it lives) versus *did the coder write this construct* (their own source only).
# Both halves are locked below.
# ---------------------------------------------------------------------------

#: Every seed surface the fleet can build. Enumerated STATICALLY rather than globbed, so a
#: seed that disappears fails loudly instead of silently dropping out of the sweep; the
#: companion test below fails if the directory ever grows a surface this list does not name.
_SEED_SURFACES = (
    "android", "cpp", "dotnet-console", "node-cli", "powershell",
    "python", "web", "web-static", "winui",
)
_SEED_ROOT = Path("C:/Users/mrbla/agentic-setup/build-infra")


@pytest.mark.parametrize("surface", _SEED_SURFACES)
def test_seed_proof_every_build_surface_seed_is_clean(surface):
    """THE PROBE CLASS THAT CATCHES THIS DEFECT FAMILY, extended to all nine surfaces.

    A seed is the tree every deliverable of its surface starts from, so a finding IN the seed
    is inherited by every deliverable and attributed to a coder who never touched it. There
    were seed-proofs for `web` and `python` but none for `winui`, and winui was the one that
    banded C -- the gap and the defect were the same shape.

    The 144-repo archive cannot catch this class: those nights predate the house rules and
    contain no winui job. Only driving the seeds themselves does."""
    seed = _SEED_ROOT / surface / "reference"
    if not seed.is_dir():
        pytest.skip(f"agentic-setup {surface} seed not present")
    result = sec.scan_repo(seed, "")
    assert result.measured is True
    assert result.at_or_above(SEVERITY_MEDIUM) == (), (
        f"the {surface} seed every deliverable inherits is not clean: {result.findings_lines()}")


def test_the_seed_sweep_covers_every_surface_on_disk():
    """The list above is a word list, and a word list goes stale silently -- a NEW build
    surface would ship with no seed-proof at all, which is exactly how winui got here. This
    fails the day a tenth surface appears, naming it."""
    if not _SEED_ROOT.is_dir():
        pytest.skip("agentic-setup build-infra not present")
    on_disk = {p.parent.name for p in _SEED_ROOT.glob("*/reference") if p.is_dir()}
    assert on_disk <= set(_SEED_SURFACES), (
        f"build surfaces with no seed-proof: {sorted(on_disk - set(_SEED_SURFACES))}")


def test_a_vendored_sdk_asset_in_build_output_does_not_band_the_deliverable_C(tmp_path):
    """The measured defect, as a fixture: third-party markup under `bin/` carrying the exact
    construct the web rule hunts. It is the toolchain's file, so it is not graded."""
    repo = tmp_path / "winui-app"
    (repo / "bin" / "x64" / "Debug" / "Microsoft.UI.Xaml" / "Assets").mkdir(parents=True)
    (repo / "MainWindow.xaml.cs").write_text(
        "public sealed partial class MainWindow : Window { }\n", encoding="utf-8")
    (repo / "bin" / "x64" / "Debug" / "Microsoft.UI.Xaml" / "Assets" / "map.html").write_text(
        'b.prototype.getOptions.call(this).htmlContent.innerHTML = p.join("")\n', encoding="utf-8")
    result = sec.scan_repo(repo, "desktop-gui")
    assert result.measured is True
    assert result.is_clean(), result.findings_lines()
    assert band_mod.compute_band(_l1_clean(), None, result) == BAND_A


def test_a_credential_in_build_output_is_still_found(tmp_path):
    """THE HALF THAT MUST NOT REGRESS. Build output came off the skip list because a
    deliverable whose only credential sat in a shipped bundle scored band A and reported
    CLEAN. Narrowing which RULES apply there must not re-close the tree to the secret scan --
    a key in a bundle ships exactly as a key in a config file does."""
    repo = tmp_path / "bundled-secret"
    (repo / "dist").mkdir(parents=True)
    (repo / "src").mkdir()
    (repo / "src" / "index.js").write_text("export const ok = 1;\n", encoding="utf-8")
    (repo / "dist" / "bundle.js").write_text(
        'const k = "AKIAIOSFODNN7EXAMPLE";\n', encoding="utf-8")
    result = sec.scan_repo(repo, "node-web")
    assert result.worst_severity == SEVERITY_HIGH
    assert any(f.rule == sec.RULE_PROVIDER_CREDENTIAL and f.path.startswith("dist/")
               for f in result.findings)
    assert band_mod.compute_band(_l1_clean(), None, result) == BAND_C


def test_the_coders_own_source_is_still_graded_for_the_same_construct(tmp_path):
    """The discrimination half: the identical markup sink in authored source still bands C.
    The exemption is by LOCATION -- who wrote the file -- and by nothing else."""
    repo = tmp_path / "authored"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "render.js").write_text(
        "list.innerHTML = entries.map(e => `<li>${e.name}</li>`).join('');\n", encoding="utf-8")
    result = sec.scan_repo(repo, "node-web")
    assert any(f.rule == sec.RULE_HTML_INJECTION for f in result.at_or_above(SEVERITY_HIGH))
    assert band_mod.compute_band(_l1_clean(), None, result) == BAND_C


@pytest.mark.parametrize("build_dir", [
    "obj", "dist", "build", "out", "target",
    # `bin` qualifies only BENEATH a configuration/architecture/target-framework segment --
    # see test_an_authored_bin_entry_point_is_still_graded for the other half.
    "bin/Debug", "bin/x64", "bin/Release/net8.0-windows10.0.19041.0",
])
def test_every_build_output_directory_is_treated_the_same(tmp_path, build_dir):
    """`obj/` was skipped outright while `bin/` was read as source -- incoherent for .NET,
    where both are build output, and it hid only ONE of the two copies of the SDK asset that
    caused this. Every build-output tree now gets the same treatment: read for credentials,
    not graded as authored code."""
    repo = tmp_path / f"proj-{build_dir.replace('/', '-')}"
    (repo / build_dir).mkdir(parents=True)
    (repo / "app.js").write_text("export const ok = 1;\n", encoding="utf-8")
    (repo / build_dir / "out.js").write_text(
        'el.innerHTML = payload;\nconst k = "AKIAIOSFODNN7EXAMPLE";\n', encoding="utf-8")
    result = sec.scan_repo(repo, "node-web")
    rules = {f.rule for f in result.findings}
    assert sec.RULE_PROVIDER_CREDENTIAL in rules, f"{build_dir}: the credential was not read"
    assert sec.RULE_HTML_INJECTION not in rules, f"{build_dir}: graded as authored code"


# ---------------------------------------------------------------------------
# `bin/` MEANS OPPOSITE THINGS IN DIFFERENT ECOSYSTEMS
#
# Classifying it by NAME was a fail-open on authored code, and the exact mirror of the one
# 7c19aca0 removed: secrets invisible in `dist/` then, sinks invisible in `bin/` now. The
# node-cli seed's package.json declares `"bin": {"app": "bin/cli.mjs"}`, so that file is the
# authored entry point of every node-cli deliverable -- and the file in a command-line tool
# most likely to carry argv handling, a shell invocation or an `eval`.
#
# The seed sweep CANNOT catch this: the real seed's entry point is clean. It needs a planted
# sink, which is what these locks are.
# ---------------------------------------------------------------------------


def test_an_authored_bin_entry_point_is_still_graded(tmp_path):
    """THE REGRESSION LOCK. A node-cli deliverable whose declared entry point carries an
    `eval` on argv and a concatenated SQL query scanned CLEAN at band A once `bin` was
    classified by name. It must band C."""
    repo = tmp_path / "node-cli-app"
    (repo / "bin").mkdir(parents=True)
    (repo / "src").mkdir()
    (repo / "package.json").write_text('{"bin": {"app": "bin/cli.js"}}\n', encoding="utf-8")
    (repo / "src" / "lib.js").write_text("export const ok = 1;\n", encoding="utf-8")
    (repo / "bin" / "cli.js").write_text(
        "#!/usr/bin/env node\n"
        "eval(process.argv[2]);\n"
        'db.query("SELECT * FROM t WHERE id = " + q);\n', encoding="utf-8")
    result = sec.scan_repo(repo, "node-cli")
    assert result.is_clean() is False, "the authored CLI entry point was not graded"
    rules = {f.rule for f in result.at_or_above(SEVERITY_HIGH)}
    assert sec.RULE_CODE_FROM_STRING in rules
    assert sec.RULE_SQL_FROM_STRING in rules
    assert band_mod.compute_band(_l1_clean(), None, result) == BAND_C


@pytest.mark.parametrize("rel", [
    "bin/cli.mjs",                 # the node-cli seed's declared entry point
    "bin/cli.js",
    "bin/tools/helper.mjs",        # an authored subdirectory is not a config segment
    "src/bin/run.py",              # a python console script
])
def test_a_bin_path_without_a_config_segment_is_authored(rel):
    assert sec._is_build_output(rel) is False, rel


@pytest.mark.parametrize("rel", [
    "bin/Debug/app.dll",
    "bin/Release/app.dll",
    "bin/x64/Debug/net8.0-windows10.0.19041.0/win-x64/Microsoft.UI.Xaml/Assets/map.html",
    "bin/AnyCPU/Release/net48/app.exe",
    "bin/net8.0/app.dll",
    "src/bin/arm64/Release/app.dll",
])
def test_a_bin_path_under_a_config_segment_is_build_output(rel):
    assert sec._is_build_output(rel) is True, rel


def test_the_node_cli_seeds_real_entry_point_is_read_as_authored_source():
    """Driven against the REAL seed rather than a fixture of the path shape: whatever the
    seed's layout becomes, its declared entry point must stay in the graded set."""
    seed = _SEED_ROOT / "node-cli" / "reference"
    if not seed.is_dir():
        pytest.skip("agentic-setup node-cli seed not present")
    entry = seed / "bin" / "cli.mjs"
    if not entry.is_file():
        pytest.skip("node-cli seed has no bin/ entry point")
    assert sec._is_build_output("bin/cli.mjs") is False
    result = sec.scan_repo(seed, "node-cli")
    assert result.measured is True
    assert "build-output file(s)" not in result.status, (
        f"the node-cli seed reported build output it does not have: {result.status}")


def test_vendored_dependencies_are_skipped_like_node_modules(tmp_path):
    """`vendor/` is third-party DEPENDENCIES (Go, PHP), the same category as `node_modules`,
    and the two are now treated identically rather than sitting in different tiers. Volume is
    the reason dependency trees are skipped outright instead of read for credentials: a
    vendored tree can exhaust the per-repo file budget and starve the coder's own source."""
    repo = tmp_path / "go-app"
    (repo / "vendor" / "github.com" / "x" / "y").mkdir(parents=True)
    (repo / "main.go").write_text("package main\n", encoding="utf-8")
    (repo / "vendor" / "github.com" / "x" / "y" / "lib.go").write_text(
        'const k = "AKIAIOSFODNN7EXAMPLE"\n', encoding="utf-8")
    result = sec.scan_repo(repo, "")
    assert result.files_scanned == 1
    assert "NOT scanned" in result.status and "vendor" in result.status


def test_the_build_output_bound_is_named_in_the_status(tmp_path):
    """A bound the reader cannot see is a bound that becomes a false clean -- the same rule
    that makes skipped trees name themselves. These files WERE read, but under a narrower rule
    set, and the status says so rather than letting 'clean' imply everything was graded."""
    repo = tmp_path / "with-build"
    (repo / "dist").mkdir(parents=True)
    (repo / "app.js").write_text("export const ok = 1;\n", encoding="utf-8")
    (repo / "dist" / "bundle.js").write_text("var x = 1;\n", encoding="utf-8")
    result = sec.scan_repo(repo, "node-web")
    assert "build-output file(s) read for credentials only" in result.status
    assert result.is_clean() is True
