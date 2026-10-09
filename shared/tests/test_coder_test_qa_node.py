"""#1416 — the node half of the coder-exam grader.

Why this file exists, and why its fixtures come from an archive rather than imagination.

`coder_test_qa` was built on :mod:`ast` from top to bottom and its tree walk was
``if not name.endswith(".py"): continue``. So a website delivery was not graded leniently,
it was not graded at all: **55 of 55 banked website records returned ``no-tests``**, and
the harness rendered that absence as a sentence about the coder — *"this task changed 19
file(s) and NONE of them was a python test -- it wrote no exam for its own work"* — against
an archived delivery holding nine ``.test.js`` files and zero python files. ``measured:
true`` and ``files_scanned: 0`` sat in the same record.

That is the sharpest form of the defect the module exists to catch, aimed at itself: not a
silent zero but a confident, wrong, human-readable accusation produced by a check that
never looked.

**The load-bearing half of this file is the negative half.** A test-integrity gate that
cries wolf gets switched off, and a switched-off gate protects nothing — so every defect
shape below is paired with the nearest LEGITIMATE construct: the assertion-free test
against the bare smoke test that calls a first-party symbol; the exam-with-no-test against
the fixture module sitting beside the exams; the empty body against a real transcribed
website test.

Fixtures are taken from the real 08-14 pottery delivery
(``battery-b9-pottery-site-20260814night.git``), so an edit that stops catching the
original defect fails here. The scanner reuses :mod:`shared.fleet.oracle_qa`'s tokeniser
rather than growing a second one; these locks are on what ``coder_test_qa`` decides with
it, not on the tokeniser itself, which has its own.
"""

from __future__ import annotations

import os

from shared.fleet import coder_test_qa as ctq

# ---------------------------------------------------------------------------
# Fixtures — the defect shapes, and their honest near-twins
# ---------------------------------------------------------------------------

#: Verbatim in shape from the delivery's ``tests/data.test.mjs``: a file NAMED as an exam
#: that declares no test, asserts nothing, and prints "All tests passed!" whenever the code
#: does not throw. Per-test scanners iterate zero bodies over it, so before the file-level
#: rule it produced a confident clean.
NODE_FILE_WITH_NO_TEST = """
import { getPieces, getPieceById } from '../src/pieces/data.js'

// Test that the functions exist and are callable
console.log('Testing getPieces function...');
try {
  const pieces = await getPieces();
  console.log('Successfully retrieved pieces');
  console.log('All tests passed!');
} catch (error) {
  console.error('Test failed:', error);
  process.exit(1);
}
"""

NODE_EMPTY_BODY = """
import { test } from 'node:test';
test('the studio page renders', () => {});
"""

NODE_NO_ASSERTION = """
import { test } from 'node:test';
test('contact form works', () => {
  const x = 1 + 1;
  console.log('looks fine', x);
});
"""

#: The honest twin of :data:`NODE_NO_ASSERTION`: no assertion, but it CALLS a first-party
#: symbol, so it throws on a missing implementation and genuinely discriminates.
#: :mod:`oracle_qa`'s own floor rule spares this shape and so must this one.
NODE_SMOKE_FIRST_PARTY = """
import { test } from 'node:test';
import { getPieces } from '../src/pieces/data.js';
test('listing pieces does not throw', async () => {
  await getPieces();
});
"""

#: Transcribed from the delivery's ``test/header.test.js`` — a real exam that must stay
#: silent under every fingerprint here.
NODE_HONEST_EXAM = """
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

test('Header HTML file exists and contains expected structure', () => {
  const headerHtml = readFileSync('public/header.html', 'utf8');
  assert.ok(headerHtml.includes('assets/logo.png'));
  assert.ok(headerHtml.includes('<header>'));
});
"""


def _classes(findings) -> list[str]:
    return sorted(f.cls for f in findings)


# ---------------------------------------------------------------------------
# The defect shapes — each must FIRE
# ---------------------------------------------------------------------------


def test_a_node_test_with_an_empty_body_cannot_fail_and_is_convicted():
    findings = ctq.scan_node_source(NODE_EMPTY_BODY, path="home.test.js")
    assert _classes(findings) == [ctq.CLASS_VACUOUS_TEST]
    assert "EMPTY body" in findings[0].message


def test_a_node_test_with_no_assertion_and_no_first_party_call_is_convicted():
    findings = ctq.scan_node_source(NODE_NO_ASSERTION, path="contact.test.js")
    assert _classes(findings) == [ctq.CLASS_VACUOUS_TEST]
    assert "no assertion" in findings[0].message


def test_a_named_exam_that_declares_no_test_at_all_is_convicted_at_file_level():
    """THE lock for the shape a per-test scanner structurally cannot see.

    Pytest's ``def test_*`` collection contract makes the python equivalent visibly empty.
    Node has no such contract, so without a file-level rule a bare script named
    ``.test.mjs`` yields zero findings and reads as a clean exam. This one shipped."""
    findings = ctq.scan_node_source(NODE_FILE_WITH_NO_TEST, path="data.test.mjs")
    assert _classes(findings) == [ctq.CLASS_VACUOUS_TEST]
    assert "declares no test" in findings[0].message
    assert findings[0].subject == "data.test.mjs"


# ---------------------------------------------------------------------------
# The honest twins — each must stay SILENT
# ---------------------------------------------------------------------------


def test_the_bare_smoke_test_that_calls_a_first_party_symbol_is_NOT_convicted():
    """oracle_qa's ``_exercises_first_party`` docstring exists precisely so a legitimate
    smoke oracle "passes the floor and is not false-flagged". Convicting it here would
    contradict, in this instrument, a rule written to prevent this exact false flag in
    the sibling one."""
    assert ctq.scan_node_source(NODE_SMOKE_FIRST_PARTY, path="pieces.test.js") == []


def test_a_real_website_exam_is_not_false_flagged():
    assert ctq.scan_node_source(NODE_HONEST_EXAM, path="header.test.js") == []


def test_a_fixture_beside_the_tests_is_never_accused_of_being_an_empty_exam():
    """The delivery ships ``test-data.mjs`` next to its exams. A helper module holding no
    test is not an exam containing no test, and calling it one would be the same
    confident-wrong-sentence failure #1416 removed, aimed at a different innocent party.
    File-level conviction is gated on the NAME declaring an exam, which is why."""
    fixture = "export const SAMPLE = { name: 'bowl' };\n"
    assert ctq.scan_node_source(fixture, path="test-data.mjs") == []
    assert ctq.scan_node_source(fixture, path="helpers.js") == []
    assert ctq.node_exam_by_name("test-data.mjs") is False
    assert ctq.node_exam_by_name("data.test.mjs") is True


def test_a_bare_script_with_a_top_level_assertion_is_a_real_if_unusual_exam():
    """It CAN fail under ``node --test`` — a top-level throw fails the file. The
    file-level rule is deliberately narrower than "declares no test()" for this reason."""
    code = "import assert from 'node:assert/strict';\nassert.ok(1 + 1 === 2);\n"
    assert ctq.scan_node_source(code, path="math.test.mjs") == []


# ---------------------------------------------------------------------------
# Taxonomy, honesty and reach
# ---------------------------------------------------------------------------


def test_node_findings_carry_the_same_taxonomy_as_python_not_a_parallel_one():
    """"On par" has to mean the SAME class, so a count the operator reads means one thing
    in both languages. A node-only taxonomy would leave the two ecosystems incomparable —
    which is the trap #1385's retirement path already walked into once, by expecting
    website nights to close rows that no website night can reach."""
    findings = ctq.scan_node_source(NODE_EMPTY_BODY, path="a.test.js")
    assert findings[0].cls in ctq.ALL_CODER_TEST_CLASSES
    assert findings[0].hard is True, "a provably unfailable test is HARD in either language"


def test_a_missing_tokeniser_is_an_unparsed_file_never_a_clean_one(tmp_path, monkeypatch):
    """FAIL-SOFT IS NOT FAIL-SILENT.

    If :mod:`oracle_qa` cannot be imported, the file was NOT examined. Returning ``[]``
    would publish a clean exam over a file nobody read — this module's own defect, in this
    module. An unparseable file is fail-soft; an unavailable scanner is not the same fact."""
    exam = tmp_path / "a.test.js"
    exam.write_text(NODE_EMPTY_BODY, encoding="utf-8")

    def _boom():
        raise ctq._TokeniserUnavailable("planted")

    monkeypatch.setattr(ctq, "_node_tokeniser", _boom)
    result = ctq.scan_paths([str(exam)])
    assert result.findings == []
    assert result.measured is False, "nobody looked; that must not read as a pass"
    assert str(exam) in result.unparsed
    assert result.languages.get(ctq.LANG_NODE, 0) == 0


def test_node_exams_are_discovered_by_name_and_by_directory(tmp_path):
    """Real deliveries use both conventions: the 08-14 site shipped
    ``test/header.test.js`` and ``tests/data.test.mjs``."""
    (tmp_path / "test").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "test" / "header.test.js").write_text(NODE_HONEST_EXAM, encoding="utf-8")
    (tmp_path / "test" / "helpers.js").write_text("export const A = 1;\n", encoding="utf-8")
    (tmp_path / "src" / "widget.spec.mjs").write_text(NODE_HONEST_EXAM, encoding="utf-8")
    (tmp_path / "src" / "widget.js").write_text("export const B = 2;\n", encoding="utf-8")

    names = sorted(os.path.basename(p) for p in ctq.discover_node_test_files(str(tmp_path)))
    assert names == ["header.test.js", "helpers.js", "widget.spec.mjs"], (
        "admitted by NAME (*.test.js / *.spec.mjs) or by LOCATION (test/); plain source "
        f"outside both is not an exam. Got {names}"
    )


def test_the_sealed_node_oracle_is_the_control_not_the_subject(tmp_path):
    """The node dual of the ``test_job_acceptance.py`` exclusion. It is authored away from
    the coder and restored from a clean copy, so a finding against it would park a run
    whose real defect is somewhere else entirely."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "acceptance.job.test.mjs").write_text(
        NODE_EMPTY_BODY, encoding="utf-8")
    assert ctq.discover_node_test_files(str(tmp_path)) == []


def test_node_build_output_is_not_this_coders_exam(tmp_path):
    """The node analogue of the ``.venv``/``site-packages`` exclusions: a vendored
    package's suite is not this coder's exam in either language."""
    for junk in ("node_modules", ".next", "coverage", "dist"):
        d = tmp_path / junk / "test"
        d.mkdir(parents=True)
        (d / "vendored.test.js").write_text(NODE_EMPTY_BODY, encoding="utf-8")
    assert ctq.discover_node_test_files(str(tmp_path)) == []


def test_an_exam_in_a_language_with_no_scanner_is_NAMED_never_counted_as_absent(tmp_path):
    """#1416 generalised to the NEXT ecosystem, so this is fixed once rather than per
    language. A grader that cannot read a language must say so; ``uncovered`` is how "we
    did not read this" stays distinguishable from "there was nothing to read"."""
    (tmp_path / "spec").mkdir()
    (tmp_path / "spec" / "widget_spec.rb").write_text("describe 'x' do\nend\n", encoding="utf-8")
    (tmp_path / "spec" / "fixtures.json").write_text("{}", encoding="utf-8")

    found = ctq.discover_all_test_files(str(tmp_path))
    assert found.python == [] and found.node == []
    assert [os.path.basename(p) for p in found.uncovered] == ["widget_spec.rb"], (
        "a ruby exam is an UNGRADED EXAM and must be named; the json fixture beside it is "
        "data, and naming it would be noise that trains the operator to skim the field"
    )

    result = ctq.scan_paths(found.scannable, uncovered=found.uncovered)
    assert result.measured is False
    assert result.clean is False, "an unexamined project is never clean"
    assert result.to_evidence()["uncovered"] == found.uncovered


def test_the_evidence_names_which_language_was_actually_read(tmp_path):
    """``files_scanned: 9`` alone cannot answer "was the website half graded". A single
    total is what hid an entire ecosystem going ungraded for 55 consecutive records."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "a.test.js").write_text(NODE_HONEST_EXAM, encoding="utf-8")
    (tmp_path / "tests" / "test_b.py").write_text(
        "def test_b():\n    assert 1 == 1\n", encoding="utf-8")

    found = ctq.discover_all_test_files(str(tmp_path))
    evidence = ctq.scan_paths(found.scannable, uncovered=found.uncovered).to_evidence()
    assert evidence["languages"] == {ctq.LANG_PYTHON: 1, ctq.LANG_NODE: 1}
    assert evidence["files_scanned"] == 2


def test_a_website_delivery_is_no_longer_reported_as_having_written_no_exam(tmp_path):
    """THE regression lock for #1416, in the shape the operator actually met it.

    Before: a node delivery yielded ``files_scanned: 0``, which the harness rendered as
    *"this task changed N file(s) and NONE of them was a python test -- it wrote no exam
    for its own work"* over a tree holding nine real test files. The harness's sentence is
    downstream of THIS number, so pinning the number is what retires the accusation."""
    (tmp_path / "test").mkdir()
    for name in ("home-page.test.js", "header.test.js", "contact.test.js"):
        (tmp_path / "test" / name).write_text(NODE_HONEST_EXAM, encoding="utf-8")

    found = ctq.discover_all_test_files(str(tmp_path))
    result = ctq.scan_paths(found.scannable, uncovered=found.uncovered)
    assert result.files_scanned == 3, "the exam files exist; a zero here IS the defect"
    assert result.measured is True
    assert result.languages[ctq.LANG_NODE] == 3
    assert result.clean is True, "these are real exams with real assertions"


def test_the_full_tree_reason_does_not_claim_a_language_it_no_longer_means():
    """It read "every python test file under the tree was examined" while examining node.
    A scope sentence naming the wrong language is the same class of defect as the
    accusation this ticket removed: a confident description of a scan that did otherwise."""
    assert "python test file" not in ctq.full_tree_scope().reason


# ---------------------------------------------------------------------------
# Found in independent review, 2026-08-16 (#1416). Every one of these was a HARD
# false positive or a clean-looking absence in the FIX FOR #1416 -- that is, this
# module committing the defect it exists to catch, one seam inside its own repair.
# They are grouped so a future reader sees the class rather than six unrelated cases.
# ---------------------------------------------------------------------------


def test_an_assertion_inside_a_SAME_FILE_helper_is_not_a_vacuous_test():
    """FP-A. The file contains `assert.ok` and was told it "makes no assertion".

    `oracle_qa.node_first_party_names` reads only ESM `import ... from './x'`, which is the
    right question for a SEALED oracle authored to a template. A coder's own exam routinely
    defines its helpers in the file it is testing from."""
    code = """
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
function checkContains(html, needle) { assert.ok(html.includes(needle)); }
test('the nav bar is present on every page', () => {
  const html = readFileSync('public/index.html', 'utf8');
  checkContains(html, '<nav>');
});
"""
    assert ctq.scan_node_source(code, path="nav.test.js") == []


def test_commonjs_require_binds_first_party_symbols_just_as_esm_import_does():
    """FP-B. The IDENTICAL test was convicted or spared by import syntax alone.

    scan_node_source's docstring promises the bare no-raise smoke test is "deliberately NOT
    flagged" -- oracle_qa's own floor rule. That promise was unreachable for every file
    using `require()`, which is most of the CommonJS world."""
    cjs = """
const test = require('node:test');
const { computeTotal } = require('../src/cart.js');
test('adding a piece to the cart does not blow up', () => { computeTotal([{price: 2}]); });
"""
    esm = """
import { test } from 'node:test';
import { computeTotal } from '../src/cart.js';
test('adding a piece to the cart does not blow up', () => { computeTotal([{price: 2}]); });
"""
    assert ctq.scan_node_source(cjs, path="cart.test.js") == [], (
        "the CommonJS twin of a spared ESM test must also be spared -- import syntax is not "
        "evidence about whether a test can fail"
    )
    assert ctq.scan_node_source(esm, path="cart.test.js") == []


def test_a_regex_dot_test_call_is_not_a_test_declaration():
    r"""FP-C, and the worst-looking output of the three.

    `_NODE_TEST_HEAD_RE` was `(?:it|test)\s*...\(` -- and in `SLUG_RE.test(` the word
    boundary sits between the dot and the `t`. So a plain helper module holding NO test was
    convicted as vacuous and rendered to the operator as `helpers.js::-`, the `-` recovered
    from a `join('-')` argument. Admitted for scanning only because it sits in `test/`."""
    code = """
const SLUG_RE = /^[a-z-]+$/;
export function allSlugsValid(pieces) { return SLUG_RE.test(pieces.map(p => p.slug).join('-')); }
"""
    assert ctq.scan_node_source(code, path="helpers.js") == []


def test_the_member_call_fix_does_not_break_it_only_and_test_concurrent():
    """The converse of the above: `it.only(` / `test.concurrent(` have their dot AFTER the
    keyword and must still be recognised, or the exclusion silently stops grading them."""
    code = """
import { test, it } from 'node:test';
it.only('focused and empty', () => {});
test.concurrent('parallel and empty', () => {});
"""
    findings = ctq.scan_node_source(code, path="a.test.js")
    assert len(findings) == 2, f"both declaration forms must still be read; got {findings}"


def test_an_unreadable_node_file_is_unparsed_never_examined_and_clean(tmp_path, monkeypatch):
    """The #1416 defect class, inside the fix for #1416.

    `scan_node_source` is fail-soft and returns [] for a source the tokeniser REFUSED --
    indistinguishable at the call site from a clean exam. scan_paths incremented `parsed`
    and the node count unconditionally, so an unreadable file banked as
    `files_scanned: 1, measured: true, unparsed: [], clean` -- with a genuinely empty-bodied
    test inside it still reported as clean. The python branch has always routed its parse
    failure to `unparsed`; this is the node branch reaching parity."""
    exam = tmp_path / "broken.test.js"
    exam.write_text(NODE_EMPTY_BODY, encoding="utf-8")
    monkeypatch.setattr(ctq, "node_source_is_readable", lambda code: False)

    result = ctq.scan_paths([str(exam)])
    assert result.findings == []
    assert str(exam) in result.unparsed, "a file the tokeniser refused was NOT examined"
    assert result.measured is False, "nobody read it; that must not bank as a measurement"
    assert result.languages.get(ctq.LANG_NODE, 0) == 0
    assert result.clean is False, "an unexamined file is never a clean exam"


def test_a_shell_test_RUNNER_does_not_falsely_exonerate_a_coder_who_wrote_no_exam():
    """The ticket's own defect, INVERTED -- and the inversion is the harder one to notice.

    `.sh`/`.ps1` were in UNCOVERED_CODE_SUFFIXES, so a delivery shipping `run-tests.sh` and
    no actual exam populated `uncovered`. The harness tests `FilesScanned == 0 and
    Uncovered > 0` BEFORE the no-tests branch, so the operator was told *"this is a gap in
    the GRADER, not a fault of the coder"* about a coder who had written nothing at all.
    Absolving falsely is the same failure as accusing falsely; the kinder sentence is not
    the safer one."""
    assert ".sh" not in ctq.UNCOVERED_CODE_SUFFIXES
    assert ".ps1" not in ctq.UNCOVERED_CODE_SUFFIXES


def test_a_shell_runner_beside_no_exam_leaves_uncovered_empty(tmp_path):
    (tmp_path / "run-tests.sh").write_text("#!/bin/sh\nnpm test\n", encoding="utf-8")
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    found = ctq.discover_all_test_files(str(tmp_path))
    assert found.uncovered == [], (
        "a test RUNNER is not an ungraded exam; naming it flips the grader into falsely "
        f"exonerating a coder that wrote none. Got {found.uncovered}"
    )
    assert found.python == [] and found.node == []


def test_a_genuine_ruby_exam_is_still_named(tmp_path):
    """The converse of the above -- the narrowing must not silence the real case."""
    (tmp_path / "spec").mkdir()
    (tmp_path / "spec" / "cart_spec.rb").write_text("describe 'x' do\nend\n", encoding="utf-8")
    found = ctq.discover_all_test_files(str(tmp_path))
    assert [os.path.basename(p) for p in found.uncovered] == ["cart_spec.rb"]


def test_a_same_file_helper_spares_only_if_ITS_OWN_BODY_can_fail():
    """The rule got this wrong TWICE, in opposite directions, and the second is the one
    worth remembering.

    v1 counted every local declaration, so `function noop() {}` called from a test body
    spared the test — a call that cannot fail for any implementation.

    v2 asked "does the FILE assert anywhere", which is a FILE-level answer to a PER-TEST
    question. One real assertion anywhere in a multi-test exam re-opened the hole for every
    other test in it — and a multi-test file where one test is weak is the NORMAL shape this
    instrument exists to catch. Its docstring claimed it "drops the shape it must not spare"
    and its lock certified that sentence while testing only the no-assertion-anywhere case.

    v3 asks the question the rule actually wants: can THIS call fail? A local symbol earns
    its exemption only if its own body asserts, or calls something this file does not own."""
    no_op = """
import { test } from 'node:test';
function noop() {}
test('the studio page renders', () => { noop(); });
"""
    assert _classes(ctq.scan_node_source(no_op, path="noop.test.js")) == [
        ctq.CLASS_VACUOUS_TEST], "a same-file no-op cannot throw on a missing implementation"

    # v2's blind spot: a REAL assertion in test 1 must not exonerate test 2.
    mixed = """
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
function samplePiece() { return { name: 'bowl', price: 20 }; }
test('the header markup is present', () => {
  assert.ok(readFileSync('public/header.html', 'utf8').includes('<header>'));
});
test('the studio page renders', () => {
  const p = samplePiece();
  console.log('looks fine', p);
});
"""
    findings = ctq.scan_node_source(mixed, path="mixed.test.js")
    assert [f.subject for f in findings] == ["mixed.test.js::the studio page renders"], (
        "one honest assertion elsewhere in the file must not exonerate a test that calls a "
        f"local factory and asserts nothing. Got {[f.subject for f in findings]}"
    )

    # And the closure can be declared INSIDE the vacuous body itself.
    closure = """
import { test } from 'node:test';
import assert from 'node:assert/strict';
test('the cart totals correctly', () => { assert.equal(2 + 2, 4); });
test('the checkout page renders', () => {
  const build = () => ({ ok: true });
  build();
});
"""
    findings = ctq.scan_node_source(closure, path="closure.test.js")
    assert [f.subject for f in findings] == ["closure.test.js::the checkout page renders"]

    # The shape the exemption EXISTS for: the helper's own body asserts.
    asserting_helper = """
import { test } from 'node:test';
import assert from 'node:assert/strict';
function checkContains(h, n) { assert.ok(h.includes(n)); }
test('the nav bar renders', () => { checkContains('<nav>', '<nav>'); });
"""
    assert ctq.scan_node_source(asserting_helper, path="nav.test.js") == []

    # And the other way a local helper earns it: it calls something the file does not own.
    delegating_helper = """
import { test } from 'node:test';
import { getPieces } from '../src/pieces/data.js';
function loadAll() { return getPieces(); }
test('listing pieces does not throw', () => { loadAll(); });
"""
    assert ctq.scan_node_source(delegating_helper, path="pieces.test.js") == []


def test_a_dynamically_imported_symbol_binds_like_a_static_one():
    """The residue of FP-B: the same test was convicted or spared by whether its import was
    static. `await import('./x')` names code this file does not own exactly as `import ...
    from './x'` does."""
    code = """
import { test } from 'node:test';
test('the pieces module loads', async () => {
  const { getPieces } = await import('../src/pieces/data.js');
  getPieces();
});
"""
    assert ctq.scan_node_source(code, path="dyn.test.js") == []


def test_a_required_symbol_spares_even_in_a_file_with_no_assertion_anywhere():
    """The asymmetry stated explicitly: the assertion condition applies to SAME-FILE
    declarations only. A relative `require`/`import` names code this file does not own, so
    the bare no-raise smoke test stays exempt exactly as oracle_qa's floor rule intends —
    and that file legitimately contains no assertion at all."""
    code = """
const test = require('node:test');
const { computeTotal } = require('../src/cart.js');
test('adding to the cart does not blow up', () => { computeTotal([{price: 2}]); });
"""
    assert ctq.scan_node_source(code, path="cart.test.js") == []


#: A source the tokeniser genuinely REFUSES — an apostrophe inside JSX text, which
#: `node_mask` reads as an unterminated string literal and returns None for. Used instead of
#: monkeypatching, so the lock proves the WIRING from a real refusal and not just the branch.
NODE_UNMASKABLE = """
import { test } from 'node:test';
export function Panel() { return <p>the studio's pieces</p>; }
test('the panel renders', () => {});
"""


def test_a_REAL_unmaskable_source_is_unparsed_not_examined_and_clean(tmp_path):
    """The wiring, not the branch.

    The sibling lock monkeypatches `node_source_is_readable`, which proves the routing but
    not that a real refusal reaches it — and an independent reviewer verified this path by
    hand precisely because the lock could not. Note the planted EMPTY-bodied test inside:
    before the fix this file banked as examined-and-clean with that test in it."""
    exam = tmp_path / "panel.test.jsx"
    exam.write_text(NODE_UNMASKABLE, encoding="utf-8")
    assert ctq.node_source_is_readable(NODE_UNMASKABLE) is False, (
        "fixture no longer unmaskable — the tokeniser changed and this lock is now vacuous, "
        "which is the defect it exists to catch"
    )

    result = ctq.scan_paths([str(exam)])
    assert result.findings == []
    assert str(exam) in result.unparsed
    assert result.measured is False
    assert result.languages.get(ctq.LANG_NODE, 0) == 0
    assert result.clean is False


def test_the_declaration_body_reader_survives_ordinary_javascript():
    """`_declaration_body` is a hand-rolled brace matcher, so it gets attacked rather than
    read. Each case below is a helper that PLAINLY asserts; if its body is misread the
    symbol fails to earn its exemption and the test calling it is convicted HARD.

    The default-parameter case is not hypothetical — it shipped. Without skipping the
    parameter list, the first `{` found belongs to `opts = {strict: true}`, so THAT became
    the body, it asserts nothing, and a helper whose next line is `assert.ok(...)` was
    treated as unable to fail."""
    default_param = """
import { test } from 'node:test';
import assert from 'node:assert/strict';
function checkPiece(piece, opts = { strict: true }) {
  assert.ok(piece.name, 'piece must have a name');
}
test('a piece has a name', () => { checkPiece({ name: 'bowl' }); });
"""
    assert ctq.scan_node_source(default_param, path="defaults.test.js") == [], (
        "a default parameter holding an object literal must not be mistaken for the body"
    )

    class_extends = """
import { test } from 'node:test';
import assert from 'node:assert/strict';
class PieceChecker extends Object {
  verify(p) { assert.ok(p.name); }
}
test('the checker verifies', () => { new PieceChecker().verify({ name: 'x' }); });
"""
    assert ctq.scan_node_source(class_extends, path="klass.test.js") == []

    template_literal = """
import { test } from 'node:test';
import assert from 'node:assert/strict';
function label(p) {
  const s = `piece ${p.name} costs ${p.price}`;
  assert.ok(s.length > 0);
  return s;
}
test('labels render', () => { label({ name: 'bowl', price: 2 }); });
"""
    assert ctq.scan_node_source(template_literal, path="tmpl.test.js") == [], (
        "a template literal's ${...} braces are blanked by the mask; reading the RAW source "
        "here would unbalance the match"
    )

    object_return = """
import { test } from 'node:test';
import assert from 'node:assert/strict';
function build() { return { ok: true, nested: { deep: 1 } }; }
test('build returns nothing checkable', () => { build(); });
"""
    findings = ctq.scan_node_source(object_return, path="obj.test.js")
    assert _classes(findings) == [ctq.CLASS_VACUOUS_TEST], (
        "the converse: a helper returning a nested object literal asserts nothing and calls "
        "nothing external, so it must NOT earn the exemption"
    )


def test_delegation_through_a_second_local_helper_is_still_a_test_that_can_fail():
    """Helper-of-a-helper is ordinary, and a one-level rule convicted it.

    `outer()` calls `inner()` which asserts. The exemption resolves to a FIXED POINT for
    that reason: a scanner that punishes one more layer of indirection is teaching people to
    inline their helpers, which is a worse exam, not a better one."""
    code = """
import { test } from 'node:test';
import assert from 'node:assert/strict';
function inner(p) { assert.ok(p.name); }
function outer(p) { inner(p); }
test('the piece is valid', () => { outer({ name: 'bowl' }); });
"""
    assert ctq.scan_node_source(code, path="twolevel.test.js") == []


def test_the_word_assert_in_a_COMMENT_earns_a_helper_nothing():
    """The mask blanks comments before any of this runs, so prose cannot buy an exemption.
    Worth locking explicitly: `NODE_ASSERTION_RE` is deliberately generous, and "generous
    over masked source" and "generous over raw source" differ by exactly this case."""
    code = """
import { test } from 'node:test';
function render(p) {
  // we should assert the name here but do not
  return String(p);
}
test('renders a piece', () => { render({ name: 'bowl' }); });
"""
    findings = ctq.scan_node_source(code, path="comment.test.js")
    assert _classes(findings) == [ctq.CLASS_VACUOUS_TEST]


def test_a_delegation_cycle_terminates():
    """The fixed point iterates over a map the source controls. Two helpers calling each
    other, neither asserting, must converge and convict rather than loop."""
    code = """
import { test } from 'node:test';
function a(p) { return b(p); }
function b(p) { return a(p); }
test('mutual recursion asserts nothing', () => { a(1); });
"""
    findings = ctq.scan_node_source(code, path="cycle.test.js")
    assert _classes(findings) == [ctq.CLASS_VACUOUS_TEST]


def test_the_declaration_head_is_skipped_in_all_of_its_shapes():
    """The same root cause, three times: THE FIRST `{` AFTER THE HEAD IS NOT THE BODY.

    Each of these broke the version that handled the one before it, and each is a HARD false
    positive — a helper whose body plainly asserts, failing to earn its exemption, so the
    test calling it is convicted and the review skip withdrawn.

    The second one is the instructive one. The parameter-list skip fired only when a `(` came
    next, which is true of an ANONYMOUS function expression and false of a NAMED one — so the
    fix for case 1 looked complete, passed a four-case lock, and left the identical defect
    reachable through a different spelling."""
    named_fn_expr = """
import { test } from 'node:test';
import assert from 'node:assert/strict';
const checkPage = function helper(html, opts = { strict: true }) { assert.ok(html.length, opts); };
test('the studio page renders', () => { checkPage('<main>'); });
"""
    assert ctq.scan_node_source(named_fn_expr, path="named.test.js") == [], (
        "a NAMED function expression's own name sits where the parameter list was expected"
    )

    extends_call = """
import { test } from 'node:test';
import assert from 'node:assert/strict';
function mixin(o) { return Object; }
class Checker extends mixin({ strict: true }) { run(h) { assert.ok(h); } }
test('renders', () => { new Checker().run('<main>'); });
"""
    assert ctq.scan_node_source(extends_call, path="mixin.test.js") == [], (
        "the argument to an `extends` call is not the class body"
    )

    # The converse: an arrow's head is already consumed by the matching regex, so skipping
    # identifiers there would eat the first token of an expression body.
    expression_arrow = """
import { test } from 'node:test';
import assert from 'node:assert/strict';
const check = (h) => assert.ok(h.length);
test('the page renders', () => { check('<main>'); });
"""
    assert ctq.scan_node_source(expression_arrow, path="arrow.test.js") == []


def test_a_NESTED_helpers_assertion_does_not_exonerate_the_function_containing_it():
    """The lenient direction, which is the one this rule exists to guard.

    `outer()` cannot fail for any implementation. Its textual body contains `inner`'s
    assertion, and `inner` is a symbol the test never calls. Nested NAMED declarations are
    stripped before the body is read; `inner` is still admitted in its own right."""
    code = """
import { test } from 'node:test';
import assert from 'node:assert/strict';
function outer() { function inner(h) { assert.ok(h); } return 1; }
test('the studio page renders', () => { outer(); });
"""
    findings = ctq.scan_node_source(code, path="nested.test.js")
    assert _classes(findings) == [ctq.CLASS_VACUOUS_TEST]

    # But an inline CALLBACK is part of what the function does when called, and must count.
    callback = """
import { test } from 'node:test';
import assert from 'node:assert/strict';
function checkAll(items) { items.forEach(i => assert.ok(i)); }
test('all pieces are valid', () => { checkAll([1, 2]); });
"""
    assert ctq.scan_node_source(callback, path="cb.test.js") == []


def test_reading_a_property_off_an_imported_object_is_not_calling_it():
    r"""`\(|\.` also matched `cart.title`. A property read does not throw on a missing or
    wrong implementation the way a call does, so it must not buy an exemption. The predicate
    is now identical to the one `scan_node_source` applies to a test body — the two were
    answering the same question with different strictness."""
    code = """
import { test } from 'node:test';
import { cart } from '../src/cart.js';
function label() { return cart.title; }
test('the checkout page renders', () => { label(); });
"""
    findings = ctq.scan_node_source(code, path="propread.test.js")
    assert _classes(findings) == [ctq.CLASS_VACUOUS_TEST]

    called = """
import { test } from 'node:test';
import { cart } from '../src/cart.js';
function label() { return cart.title(); }
test('the checkout page renders', () => { label(); });
"""
    assert ctq.scan_node_source(called, path="called.test.js") == [], (
        "the converse: CALLING a method on an imported object can throw, and still spares"
    )


def test_a_GENERATOR_helper_is_a_declaration_too():
    r"""`async function* gen(h) { assert.ok(h); }` matched no alternative of the declaration
    regex, because `function\s+NAME` cannot cross the `*`. So the helper was never admitted
    and the test calling it was convicted HARD over a body containing `assert.ok`.

    Same family as the three head shapes, and found the same way — by running ordinary
    javascript through the scanner rather than by reading the pattern. A regex that is wrong
    about what a declaration LOOKS like fails silently in the accusing direction."""
    code = """
import { test } from 'node:test';
import assert from 'node:assert/strict';
async function* gen(h) { assert.ok(h); yield h; }
test('generates', () => { gen('<main>'); });
"""
    assert ctq.scan_node_source(code, path="star.test.js") == []


def test_stripping_a_nested_declaration_uses_its_OFFSET_not_a_text_search():
    """The first version of this lock could not reach the bug it named.

    It used two SIBLING nested helpers with identical bodies — but `find` searched from each
    match's own end, so a duplicate sibling is always BEHIND the search start and the true
    body is always the first hit. The reachable shape is a body whose text repeats inside its
    own HEAD, which makes the search land in the head and strip the wrong span:

        `function inner(o = { assert: 1 }) { assert: 1 }`
                          ^^^^^^^^^^^^^ found first, so the strip ends here

    leaving `) { assert: 1 }` behind and the enclosing function holding a token it did not
    earn. The fix removed the class rather than the case: the span was known when the body
    was extracted, so nothing is re-derived."""
    assert ctq._strip_nested_declarations(
        "{ function inner(o = { assert: 1 }) { assert: 1 } return 1; }"
    ) == "{  return 1; }"

    # And the sibling shape the first fixture used, kept because it is cheap and real.
    code = """
import { test } from 'node:test';
import assert from 'node:assert/strict';
function outer(h) {
  function a(x) { return x; }
  function b(x) { return x; }
  return h;
}
test('renders', () => { outer('<main>'); });
"""
    assert _classes(ctq.scan_node_source(code, path="repeat.test.js")) == [
        ctq.CLASS_VACUOUS_TEST]


def test_an_assertion_hidden_in_an_UNREACHABLE_nested_function_buys_nothing():
    """Gaming resistance, and the claim is deliberately narrow.

    Stripping nested declarations could have opened a way to LOSE an assertion; instead it
    closes one way to fake one — a helper cannot borrow the assertion of a NESTED function
    the test never reaches.

    It does NOT close forgery in general, and the broader sentence this docstring used to
    carry ("a coder cannot satisfy the scanner by declaring an asserting function it never
    calls") is false: an unreachable assertion in the helper's OWN body still earns the
    exemption. See `test_the_forgeable_shapes_are_a_STATED_limit_not_a_claim` for why that is
    a documented boundary rather than a defect."""
    code = """
import { test } from 'node:test';
import assert from 'node:assert/strict';
function looksLegit(h) {
  function hidden() { assert.ok(false); }
  return h;
}
test('the page renders', () => { looksLegit('<main>'); });
"""
    findings = ctq.scan_node_source(code, path="gaming.test.js")
    assert _classes(findings) == [ctq.CLASS_VACUOUS_TEST]


def test_a_multiline_parameter_list_with_nested_braces_is_still_skipped():
    code = """
import { test } from 'node:test';
import assert from 'node:assert/strict';
function check(
  html,
  opts = { strict: true, deep: { more: 1 } },
  extra = () => ({ x: 1 })
) {
  assert.ok(html.length, opts, extra);
}
test('the page renders', () => { check('<main>'); });
"""
    assert ctq.scan_node_source(code, path="longparams.test.js") == []


def test_a_class_member_before_the_asserting_one_does_not_hide_it():
    code = """
import { test } from 'node:test';
import assert from 'node:assert/strict';
class Checker { get strict() { return true; } run(h) { assert.ok(h); } }
test('renders', () => { new Checker().run('<main>'); });
"""
    assert ctq.scan_node_source(code, path="getter.test.js") == []


def test_a_TYPESCRIPT_return_type_or_generic_constraint_is_not_the_body():
    """Root causes four and five of one sentence: THE FIRST `{` AFTER THE HEAD IS NOT THE BODY.

    `.ts`/`.tsx` are admitted deliberately, and NODE_TEST_SUFFIXES' own comment says
    TypeScript's additions are "syntax the masker steps over". These two are the syntax it
    does not step over — an object-literal RETURN TYPE and an object-literal GENERIC
    CONSTRAINT both put braces in front of the body. Both convicted a helper whose body
    plainly asserts, which withdraws the review skip and costs a night."""
    return_type = """
import { test } from 'node:test';
import assert from 'node:assert/strict';
function parsePage(s: string): { ok: boolean } { assert.ok(s.length); return { ok: true }; }
test('renders', () => { parsePage('<main>'); });
"""
    assert ctq.scan_node_source(return_type, path="rettype.test.ts") == []

    generic_constraint = """
import { test } from 'node:test';
import assert from 'node:assert/strict';
function check<T extends { a: number }>(x: T) { assert.ok(x.a); }
test('renders', () => { check({ a: 1 }); });
"""
    assert ctq.scan_node_source(generic_constraint, path="generic.test.ts") == []

    # A non-object return type must not swallow the body either.
    plain_type = """
import { test } from 'node:test';
import assert from 'node:assert/strict';
function count(s: string): Promise<number> { assert.ok(s.length); return Promise.resolve(1); }
test('renders', () => { count('<main>'); });
"""
    assert ctq.scan_node_source(plain_type, path="plain.test.ts") == []


def test_a_nested_ARROW_helper_is_stripped_like_a_nested_function():
    """Identical semantics must not get opposite verdicts based on declaration form.

    `function outer() { const inner = (h) => assert.ok(h); return 1; }` spared `outer` while
    the `function inner` spelling convicted it — structurally the same asymmetry as the
    CommonJS-versus-ESM one this module already fixed once, so it is fixed the same way."""
    arrow_form = """
import { test } from 'node:test';
import assert from 'node:assert/strict';
function outer() { const inner = (h) => assert.ok(h); return 1; }
test('renders', () => { outer(); });
"""
    fn_form = """
import { test } from 'node:test';
import assert from 'node:assert/strict';
function outer() { function inner(h) { assert.ok(h); } return 1; }
test('renders', () => { outer(); });
"""
    assert _classes(ctq.scan_node_source(arrow_form, path="a.test.js")) == [
        ctq.CLASS_VACUOUS_TEST]
    assert _classes(ctq.scan_node_source(fn_form, path="b.test.js")) == [
        ctq.CLASS_VACUOUS_TEST], "both spellings must reach the same verdict"


def test_the_forgeable_shapes_are_a_STATED_limit_not_a_claim():
    """This instrument measures CARELESSNESS, not DECEPTION — and that boundary is asserted
    here rather than left for a reader to discover.

    The exemption is earned by a token match over masked source, so it is forgeable in one
    word. Each shape below SPARES the calling test, and each is a deliberate consequence of
    oracle_qa's stated asymmetry: *"a missed vacuous test costs one weak exam, while a false
    positive REFUSES a whole job. The asymmetry is the design."*

    The honest caveat, which is why this is a lock and not a comment: that asymmetry was
    chosen for a SEALED oracle authored away from the coder. Here the subject is the coder's
    own exam and the author is the party with the incentive — the same rule against a
    different threat model. Beating a coder that WANTS to forge a token is not reachable by
    static scanning, and attempting it would re-import the false-positive risk that took four
    review rounds to remove. Deliberate grader-gaming is `green_audit`'s question.

    If a future change makes any of these convict, that is a real improvement and this lock
    should be updated deliberately — not a regression to be silenced."""
    forgeable = [
        ("a bare identifier statement",
         "function helper() { assert; }"),
        ("an assertion in dead code",
         "function helper() { if (false) { assert.ok(1); } return 1; }"),
        ("a local variable NAMED assert",
         "function helper() { let assert = 1; return assert; }"),
    ]
    for label, decl in forgeable:
        code = (
            "import { test } from 'node:test';\n"
            + decl + "\n"
            + "test('the page renders', () => { helper(); });\n"
        )
        assert ctq.scan_node_source(code, path="f.test.js") == [], (
            f"{label}: this is a KNOWN forgeable shape and is expected to be spared. If it "
            "now convicts, update this lock deliberately rather than deleting the case."
        )

    # And an external binding earns its exemption STRUCTURALLY, so the path need not resolve.
    unresolved = """
import { test } from 'node:test';
const { anything } = require('./nope.js');
test('the page renders', () => { anything(); });
"""
    assert ctq.scan_node_source(unresolved, path="g.test.js") == []


def test_the_head_walk_reaches_the_END_of_the_head_not_its_first_brace():
    """SIX shapes have now put a `{` in front of the body, and every fix that special-cased
    one left the next reachable:

      1. a default parameter          `function f(a, o = {x: 1}) { … }`
      2. a named function expression  `const f = function g(a, o = {x: 1}) { … }`
      3. an `extends` call argument   `class C extends mix({x: 1}) { … }`
      4. a TS object return type      `function f(s: string): { ok: boolean } { … }`
      5. a TS generic constraint      `function f<T extends {a: number}>(x: T) { … }`
      6. a TS type predicate          `function f(x: unknown): x is { name: string } { … }`

    Number 6 is the one that retired the case-by-case approach: the `:` handler consumed a
    brace only when it came IMMEDIATELY after the colon, and `x is` sits between. The rule
    now walks the head to its end — a brace group is the BODY unless a return-type annotation
    is still open, in which case it is the type and the body is the next group.

    Every case below is a helper that plainly asserts; a misread body means it fails to earn
    its exemption and the test calling it is convicted HARD."""
    cases = {
        "predicate.test.ts":
            "function isPiece(x: unknown): x is { name: string } { assert.ok(x); return true; }",
        "nestedgen.test.ts":
            "function load(s: string): Promise<{ ok: boolean }> "
            "{ assert.ok(s.length); return Promise.resolve({ ok: true }); }",
        "implements.test.ts":
            "class Checker implements Runner { run(h: string) { assert.ok(h); } }",
        "tuple.test.ts":
            "function pair(s: string): [string, { ok: boolean }] "
            "{ assert.ok(s); return [s, { ok: true }]; }",
    }
    for path, decl in cases.items():
        call = "isPiece({ name: 'b' })" if "isPiece" in decl else (
            "load('<main>')" if "load" in decl else (
                "new Checker().run('<main>')" if "Checker" in decl else "pair('x')"))
        code = (
            "import { test } from 'node:test';\n"
            "import assert from 'node:assert/strict';\n"
            + decl + "\n"
            + f"test('renders', () => {{ {call}; }});\n"
        )
        assert ctq.scan_node_source(code, path=path) == [], (
            f"{path}: the head walk stopped early and read a TYPE as the body"
        )


def test_a_less_than_COMPARISON_is_not_a_generic_parameter_list():
    """The `<` skip is balanced-angle counting, which is only correct where a `<` opens a
    generic. In an arrow BODY it is a comparison — and that body is reached with
    `skip_head=False`, so the walk never sees it. Locked because the two are indistinguishable
    by shape and the wrong answer would swallow the rest of the file."""
    code = """
import { test } from 'node:test';
import assert from 'node:assert/strict';
const under = (a) => a < 10;
function check(a) { assert.ok(under(a)); }
test('renders', () => { check(1); });
"""
    assert ctq.scan_node_source(code, path="cmp.test.js") == []


def _ts_case(decl: str, call: str) -> str:
    return (
        "import { test } from 'node:test';\n"
        "import assert from 'node:assert/strict';\n"
        + decl + "\n"
        + f"test('renders', () => {{ {call}; }});\n"
    )


def test_the_head_walk_against_the_rest_of_typescript():
    """Root causes EIGHT and NINE, plus the shapes that held.

    Eight: `abstract class C { … }` matched no alternative of the declaration regex, which
    allowed only an optional `export` before `class`. Nine: a UNION return type
    `: { a: 1 } | { b: 2 } { body }` — after the first group was taken as the type the
    annotation was treated as CLOSED, so the second type group became the "body" and the real
    body sat one group further on. `|` and `&` reopen it.

    The four that held are locked too, because "we tried it and it was fine" is worth exactly
    as much as the fixes when the next person edits this walk."""
    fine = {
        "abstract": ("abstract class C { run(h: string) { assert.ok(h); } }",
                     "new C().run('h')"),
        "union-return": (
            "function check(h: string): { a: 1 } | { b: 2 } { assert.ok(h); return { a: 1 }; }",
            "check('h')"),
        "intersection-return": (
            "function check(h: string): { a: 1 } & { b: 2 } "
            "{ assert.ok(h); return { a: 1, b: 2 }; }", "check('h')"),
        "decorator": ("class C { @log run(h: string) { assert.ok(h); } }", "new C().run('x')"),
        "satisfies": (
            "const check = ((h: string) => { assert.ok(h); }) satisfies (s: string) => void;",
            "check('x')"),
        "param-property": (
            "class C { constructor(private readonly o: { x: number }) { assert.ok(o); } "
            "run(h) { assert.ok(h); } }", "new C({x:1}).run('h')"),
        "default-arrow-param": (
            "function check(h, cb = (x) => { return x; }) { assert.ok(h); }", "check('h')"),
        "optional-param": ("function check(h?: string): void { assert.ok(h); }", "check('h')"),
    }
    for label, (decl, call) in fine.items():
        assert ctq.scan_node_source(_ts_case(decl, call), path=f"{label}.test.ts") == [], (
            f"{label}: the head walk misread a type as the body, so a helper that plainly "
            "asserts failed to earn its exemption"
        )


def test_the_head_walk_still_convicts_when_the_typescript_helper_asserts_NOTHING():
    """The converse for the whole TypeScript family. Every case above is spared because the
    helper asserts; none of them may be spared merely for being TypeScript. Without this,
    a walk that silently swallowed the body would pass the entire block above."""
    silent = {
        "abstract": ("abstract class C { run(h: string) { return h; } }", "new C().run('h')"),
        "union-return": (
            "function check(h: string): { a: 1 } | { b: 2 } { return { a: 1 }; }",
            "check('h')"),
        "optional-param": ("function check(h?: string): void { return; }", "check('h')"),
    }
    for label, (decl, call) in silent.items():
        findings = ctq.scan_node_source(_ts_case(decl, call), path=f"{label}-silent.test.ts")
        assert _classes(findings) == [ctq.CLASS_VACUOUS_TEST], (
            f"{label}: this helper asserts nothing and calls nothing external, so the test "
            "calling it carries no information and must be convicted"
        )


#: Every way JavaScript and TypeScript name a callable thing, with the modifier combinations
#: that actually occur. THIS IS THE STRUCTURAL CONTROL for a class of defect that recurred
#: SIX times: a declaration form the reader does not recognise, whose body is therefore never
#: read, so a helper that plainly asserts fails to earn its exemption and the test calling it
#: is convicted HARD. Every instance was found by running ordinary javascript through the
#: scanner; not one was found by reading the pattern, and none announced itself.
#:
#: The four that shipped, in the order they were found: a generator; `abstract class`;
#: `export default class`; `export default function` (which is the single most common way a
#: module exports one helper) and its `async` twin. Two of those four were introduced by a
#: fix for the previous one landing on only one of three parallel alternatives.
#:
#: Add a row here BEFORE adding a form to the pattern. That ordering is the point: the
#: pattern getting longer is not a control, and it has now been lengthened five times without
#: becoming right.
DECLARATION_FORMS = [
    ("plain function", "function check(h) { assert.ok(h); }", "check"),
    ("async function", "async function check(h) { assert.ok(h); }", "check"),
    ("generator", "function* check(h) { assert.ok(h); }", "check"),
    ("async generator", "async function* check(h) { assert.ok(h); }", "check"),
    ("export function", "export function check(h) { assert.ok(h); }", "check"),
    ("export async function", "export async function check(h) { assert.ok(h); }", "check"),
    ("export default function", "export default function check(h) { assert.ok(h); }", "check"),
    ("export default async function",
     "export default async function check(h) { assert.ok(h); }", "check"),
    ("class", "class Check { run(h) { assert.ok(h); } }", "Check"),
    ("export class", "export class Check { run(h) { assert.ok(h); } }", "Check"),
    ("export default class", "export default class Check { run(h) { assert.ok(h); } }", "Check"),
    ("abstract class", "abstract class Check { run(h) { assert.ok(h); } }", "Check"),
    ("export abstract class",
     "export abstract class Check { run(h) { assert.ok(h); } }", "Check"),
    ("const arrow", "const check = (h) => { assert.ok(h); };", "check"),
    ("export const arrow", "export const check = (h) => { assert.ok(h); };", "check"),
    ("const arrow, single param", "const check = h => { assert.ok(h); };", "check"),
    ("const function expression", "const check = function (h) { assert.ok(h); };", "check"),
    ("const NAMED function expression",
     "const check = function inner(h) { assert.ok(h); };", "check"),
    ("const async arrow", "const check = async (h) => { assert.ok(h); };", "check"),
    ("let arrow", "let check = (h) => { assert.ok(h); };", "check"),
]


def test_every_declaration_FORM_admits_its_symbol():
    """The enumeration. A form the reader cannot see is a HARD false positive waiting."""
    oq = ctq._node_tokeniser()
    missed = []
    for label, decl, name in DECLARATION_FORMS:
        symbols = ctq._node_callable_symbols(
            "import assert from 'node:assert/strict';\n" + decl + "\n", oq)
        if name not in symbols:
            missed.append(f"{label}: {decl!r} -> {sorted(symbols)}")
    assert not missed, (
        "declaration forms whose symbol was not admitted — each is a HARD false positive "
        "against any test that calls the helper:\n  " + "\n  ".join(missed)
    )


def test_every_declaration_FORM_spares_the_test_that_calls_it():
    """The same matrix driven end to end, because admitting a symbol and sparing the test are
    different steps and only the second one is what the operator sees."""
    convicted = []
    for label, decl, name in DECLARATION_FORMS:
        call = f"new {name}().run('h')" if name[0].isupper() else f"{name}('h')"
        code = (
            "import { test } from 'node:test';\n"
            "import assert from 'node:assert/strict';\n"
            + decl + "\n"
            + f"test('renders', () => {{ {call}; }});\n"
        )
        if ctq.scan_node_source(code, path="t.test.ts"):
            convicted.append(label)
    assert not convicted, (
        "these helpers plainly assert, and the tests calling them were convicted: "
        + ", ".join(convicted)
    )


def test_the_two_declaration_READERS_agree_on_every_form():
    """`_NODE_LOCAL_DECL_RE` admits symbols; `_NODE_NESTED_DECL_RE` strips nested ones. They
    were maintained in parallel and drifted: `abstract class` landed on the top-level class
    alternative only, so a NESTED abstract class was stripped from its enclosing body while a
    top-level one was never admitted — two readers of the same construct inside one module,
    disagreeing about what a declaration is.

    Both are now built from `_DECL_MODIFIERS` and `_FN_KEYWORD`. This asserts the agreement
    rather than the shared definition, so a future edit that re-splits them fails here even
    if it keeps the constants."""
    disagreed = []
    for label, decl, _name in DECLARATION_FORMS:
        top = bool(ctq._NODE_LOCAL_DECL_RE.search("\n" + decl))
        nested = bool(ctq._NODE_NESTED_DECL_RE.search(decl))
        if top != nested:
            disagreed.append(f"{label}: top-level={top} nested={nested}")
    assert not disagreed, (
        "the two declaration readers disagree; a form stripped when nested but not admitted "
        "when top-level is the drift that already happened once:\n  " + "\n  ".join(disagreed)
    )
