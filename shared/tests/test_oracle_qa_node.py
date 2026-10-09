"""Node job-oracle QA — static vacuity + the FAIL-TO-PASS baseline (#1342).

The regression lock for the defect that let B9's `20260807-195617-bd` bank GREEN while
missing an operator-required page: `f2p_seed_gate` returned an unconditional `seed` for
every non-python oracle, so the ONE exam with authority over a whole job was the one exam
never proven able to fail.

The centrepiece is :data:`_REAL_B9_ORACLE` — the escaped artifact VERBATIM, copied from
`state/fleet-runs/20260807-195617-bd/job-oracle-acceptance.job.test.mjs`. A lock built
only on defects invented here would be weaker than one built on the file that actually got
through, so both are present: the real oracle and synthetic single-shape cases.

Live `node` tests are marked with :data:`_needs_node`. Node is a production requirement of
the node dispatch path (the driver grades with `npm test` → `node --test`), so on any host
that can run a node job these execute; the guard exists so a node-less checkout reports an
honest, NAMED environmental skip rather than a red gate.
"""

from __future__ import annotations

import shutil

import pytest

from shared.fleet import oracle_qa as oq
from shared.fleet import swap_ops as so
from shared.fleet.acceptance import JOB_ORACLE_PATH_NODE
from shared.fleet.dispatch import FleetDispatchConfig

_needs_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="requires the real `node` runtime (the ecosystem this gate grades)",
)


# ---------------------------------------------------------------------------
# The artifact that escaped — verbatim, 33 lines
# ---------------------------------------------------------------------------

_REAL_B9_ORACLE = """import test from 'node:test'; import assert from 'node:assert';
import { storeEnquiry } from '../src/contact/enquiries.js';
import { getPieces, getPieceById } from '../src/pieces/data.js';

test('Verify all pages are accessible', async () => {
  // This test would be implemented with a server and HTTP requests, which are not supported in this context.
  // For the purpose of this test file, we assume the pages are correctly created and accessible.
});

test('Verify shared data source updates are reflected in both list and detail pages', async () => {
  const pieces = await getPieces();
  const piece = pieces[0];
  piece.price = 15.99;
  await getPieceById(piece.id);
  assert.equal(piece.price, 15.99);
});

test('Verify filtering by category works', async () => {
  const pieces = await getPieces();
  const filteredPieces = pieces.filter(p => p.category === 'mugs');
  assert.ok(filteredPieces.length > 0);
});

test('Verify contact form stores enquiry', async () => {
  const enquiry = { name: 'Test Name', email: 'test@example.com', message: 'Test message' };
  await storeEnquiry(enquiry);
  // This test would verify the storage, but the actual storage mechanism is not provided.
});

test('Verify contact form provides feedback for missing fields', async () => {
  // This test would be implemented with a form submission and validation check.
  // For the purpose of this test file, we assume the validation is correctly implemented.
});
"""

#: A LEGITIMATE node oracle — the false-positive guard. Every test asserts real product
#: behaviour through the first-party surface. If any change to the detector ever REFUSES
#: this, the detector has become worse than the defect it replaced: a false refuse blocks
#: real work, where a missed vacuous test costs one weak exam.
_LEGIT_ORACLE = """import test from 'node:test';
import assert from 'node:assert';
import { getPieces, getPieceById } from '../src/pieces/data.js';
import { storeEnquiry, listEnquiries } from '../src/contact/enquiries.js';

test('piece list exposes every seeded piece', async () => {
  const pieces = await getPieces();
  assert.ok(Array.isArray(pieces));
  assert.ok(pieces.length >= 1);
});

test('detail lookup returns the requested piece', async () => {
  const pieces = await getPieces();
  const found = await getPieceById(pieces[0].id);
  assert.equal(found.id, pieces[0].id);
});

test('an enquiry is persisted and retrievable', async () => {
  await storeEnquiry({ name: 'A', email: 'a@b.c', message: 'hi' });
  const all = await listEnquiries();
  assert.equal(all.length, 1);
});

test('a bare smoke call is allowed to assert nothing', async () => {
  await getPieces();
});
"""


def _fake_run(out: str = "", err: str = "", ok: bool = False):
    def run(cmd, cwd, timeout_s, env):
        return (ok, out, err)
    return run


def _fake_node_run(tap: str = "", *, check_ok: bool = True, err: str = ""):
    """A faked runner that answers the TWO node subprocesses SEPARATELY — `node --check`
    (a parse) and `node --test` (the baseline). One canned reply for both is what a first
    draft of this file did, and it made a sound oracle REFUSE: `--check` read the TAP body
    as a parse error. The gate really does spawn two different processes, so the double
    must too."""
    def run(cmd, cwd, timeout_s, env):
        if "--check" in cmd:
            return (check_ok, "", "" if check_ok else (err or "SyntaxError"))
        return (False, tap, "")
    return run


def _config(tmp_path) -> FleetDispatchConfig:
    setup = tmp_path / "setup"
    (setup / "scripts").mkdir(parents=True, exist_ok=True)
    return FleetDispatchConfig(
        scripts_dir=setup / "scripts",
        queue_path=setup / "state" / "fleet-queue.json",
        runs_dir=setup / "state" / "fleet-runs",
        projects_dir=tmp_path,
    )


def _tap(*names: str) -> str:
    body = "TAP version 13\n"
    for i, n in enumerate(names, start=1):
        body += f"# Subtest: {n}\nok {i} - {n}\n  ---\n  duration_ms: 0.1\n  ...\n"
    return body + f"1..{len(names)}\n# tests {len(names)}\n# pass {len(names)}\n# fail 0\n"


# ---------------------------------------------------------------------------
# Static vacuity — the shapes that convict without executing anything
# ---------------------------------------------------------------------------


def test_static_vacuity_fires_on_the_real_escaped_oracle():
    """THE lock. Both empty-bodied tests are caught, and every finding is HARD."""
    findings = oq.node_static_vacuity(_REAL_B9_ORACLE)
    subjects = {f.subject for f in findings}
    assert "Verify all pages are accessible" in subjects
    assert "Verify contact form provides feedback for missing fields" in subjects
    assert all(f.cls == oq.CLASS_ADEQUACY_FLOOR and f.hard for f in findings)


def test_static_vacuity_does_not_fire_on_a_legitimate_oracle():
    """The false-positive guard: a real oracle — INCLUDING its bare no-raise smoke test —
    survives untouched. A false REFUSE blocks real work and is the worse failure."""
    assert oq.node_static_vacuity(_LEGIT_ORACLE) == []


def test_empty_body_is_hard():
    code = "import test from 'node:test';\ntest('nothing', () => {});\n"
    findings = oq.node_static_vacuity(code)
    assert len(findings) == 1
    assert findings[0].hard and findings[0].subject == "nothing"


def test_comment_only_body_is_hard():
    code = "import test from 'node:test';\ntest('c', () => {\n  // assume it works\n});\n"
    assert len(oq.node_static_vacuity(code)) == 1


def test_assertion_free_with_no_first_party_call_is_hard():
    code = (
        "import test from 'node:test';\n"
        "import { thing } from '../src/thing.js';\n"
        "test('local only', () => {\n  const xs = [1,2].filter(x => x > 1);\n});\n"
    )
    findings = oq.node_static_vacuity(code)
    assert len(findings) == 1 and findings[0].hard


def test_assertion_free_smoke_call_is_deliberately_not_flagged():
    """The module's OWN floor rule (`_exercises_first_party`): a bare no-raise call on a
    first-party symbol COUNTS. Such a test still fails on a skeleton — where the imports
    resolve, the F2P baseline convicts it by MEASUREMENT rather than by guess."""
    code = (
        "import test from 'node:test';\n"
        "import { runIt } from '../src/app.js';\n"
        "test('smoke', async () => {\n  await runIt();\n});\n"
    )
    assert oq.node_static_vacuity(code) == []


def test_skip_and_todo_tests_are_not_flagged():
    """An explicitly skipped/todo test is an honest non-assertion, and a `todo` body is
    empty BY CONTRACT — convicting it would refuse a correctly-marked placeholder."""
    code = (
        "import test from 'node:test';\n"
        "test.skip('later', () => {});\n"
        "test.todo('unwritten');\n"
    )
    assert oq.node_static_vacuity(code) == []


def test_concise_arrow_body_with_assertion_is_not_flagged():
    code = (
        "import test from 'node:test';\nimport assert from 'node:assert';\n"
        "import { v } from '../src/v.js';\n"
        "test('concise', () => assert.ok(v()));\n"
    )
    assert oq.node_static_vacuity(code) == []


def test_it_alias_and_nested_describe_are_scanned():
    code = (
        "import { describe, it } from 'node:test';\n"
        "describe('group', () => {\n  it('empty', () => {});\n});\n"
    )
    findings = oq.node_static_vacuity(code)
    assert len(findings) == 1 and findings[0].subject == "empty"


# ---------------------------------------------------------------------------
# The masker — braces inside literals must not be mistaken for code
# ---------------------------------------------------------------------------


def test_braces_inside_strings_and_templates_do_not_confuse_the_scan():
    code = (
        "import test from 'node:test';\nimport assert from 'node:assert';\n"
        "import { render } from '../src/render.js';\n"
        "test('literals', () => {\n"
        "  const s = '} not a brace {';\n"
        "  const t = `a ${ render({ x: 1 }) } b`;\n"
        "  const re = /[{}]/g;\n"
        "  assert.ok(t.length > 0);\n"
        "});\n"
    )
    assert oq.node_static_vacuity(code) == []


def test_unmaskable_source_is_fail_soft():
    """An unterminated literal yields NO findings — this scan would rather see nothing than
    mis-tokenise a legitimate oracle into a REFUSE. `node --check` owns validity soundly."""
    assert oq.node_static_vacuity("test('x', () => { const s = 'unterminated\n});") == []
    assert oq.node_static_vacuity("test('x', () => { /* never closed \n") == []


def test_apostrophe_in_a_double_quoted_name_does_not_break_the_scan():
    code = (
        'import test from \'node:test\';\n'
        'test("the operator\'s page renders", () => {});\n'
    )
    assert len(oq.node_static_vacuity(code)) == 1


# ---------------------------------------------------------------------------
# FAIL-TO-PASS baseline — faked runner (the stamp contract)
# ---------------------------------------------------------------------------


def test_node_f2p_flags_vacuous_pass(tmp_path):
    run = _fake_run(out=_tap("Verify all pages are accessible"))
    stamp, findings = oq.node_fail_to_pass_baseline(
        _REAL_B9_ORACLE, str(tmp_path), run=run)
    assert stamp == "vacuous:Verify all pages are accessible"
    assert [f.cls for f in findings] == [oq.CLASS_F2P_VACUOUS]
    assert findings[0].hard


def test_node_f2p_all_fail_is_clean(tmp_path):
    run = _fake_run(out="TAP version 13\nnot ok 1 - t\n1..1\n# tests 1\n# pass 0\n# fail 1\n")
    stamp, findings = oq.node_fail_to_pass_baseline(_LEGIT_ORACLE, str(tmp_path), run=run)
    assert stamp == "all-fail" and findings == []


def test_node_f2p_machinery_miss_is_not_run(tmp_path):
    """Empty output (node died before TAP said anything) → honest not-run, NEVER a false
    clean. The fail-soft half of the asymmetry the brief pins."""
    stamp, findings = oq.node_fail_to_pass_baseline(
        _LEGIT_ORACLE, str(tmp_path), run=_fake_run(out="", err=""))
    assert stamp == "not-run" and findings == []


def test_node_f2p_timeout_is_not_run(tmp_path):
    stamp, _ = oq.node_fail_to_pass_baseline(
        _LEGIT_ORACLE, str(tmp_path), run=_fake_run(out="", err="TIMEOUT"))
    assert stamp == "not-run"


def test_node_f2p_missing_dir_is_not_run():
    stamp, _ = oq.node_fail_to_pass_baseline(_LEGIT_ORACLE, "/no/such/dir", run=_fake_run())
    assert stamp == "not-run"


def test_node_f2p_skipped_tap_entry_is_not_a_pass(tmp_path):
    """A `# SKIP` directive is not evidence of vacuity — counting it would invent a finding
    against a test that never ran."""
    run = _fake_run(out="TAP version 13\nok 1 - dormant # SKIP\n1..1\n# tests 1\n# pass 0\n")
    stamp, findings = oq.node_fail_to_pass_baseline(_LEGIT_ORACLE, str(tmp_path), run=run)
    assert stamp == "all-fail" and findings == []


def test_node_f2p_probe_lands_beside_the_pinned_oracle(tmp_path):
    """The probe must sit where the real oracle sits, or its `../src/...` specifiers
    resolve outside the tree and every run becomes a meaningless import error."""
    seen: dict = {}

    def run(cmd, cwd, timeout_s, env):
        seen["rel"] = cmd[-1]
        seen["cwd"] = cwd
        return (False, "1..0\n# tests 0\n", "")

    oq.node_fail_to_pass_baseline(_LEGIT_ORACLE, str(tmp_path), run=run)
    expected_parent = JOB_ORACLE_PATH_NODE.rsplit("/", 1)[0]
    assert seen["rel"].startswith(expected_parent + "/")
    assert seen["cwd"] == str(tmp_path)


def test_node_f2p_cleans_up_its_probe(tmp_path):
    oq.node_fail_to_pass_baseline(
        _LEGIT_ORACLE, str(tmp_path), run=_fake_run(out="1..0\n# tests 0\n"))
    assert list(tmp_path.rglob("_qa_f2p_probe*")) == []


# ---------------------------------------------------------------------------
# node --check collectability
# ---------------------------------------------------------------------------


def test_node_collectability_confirmed():
    stamp, finding = oq.node_confirm_collectable(
        _LEGIT_ORACLE, run=_fake_run(ok=True))
    assert stamp == "confirmed" and finding is None


def test_node_collectability_parse_failure_is_hard():
    stamp, finding = oq.node_confirm_collectable(
        "test('x', () => {", run=_fake_run(err="SyntaxError: Unexpected end of input"))
    assert stamp == "unconfirmed"
    assert finding is not None and finding.cls == oq.CLASS_COLLECTABILITY and finding.hard


def test_node_collectability_silent_failure_is_not_run():
    """A runner that failed while saying nothing measured nothing about the oracle."""
    stamp, finding = oq.node_confirm_collectable(_LEGIT_ORACLE, run=_fake_run(ok=False))
    assert stamp == "not-run" and finding is None


# ---------------------------------------------------------------------------
# The gate — reachability, and the verdict that used to be an unconditional `seed`
# ---------------------------------------------------------------------------


def test_gate_refuses_the_real_escaped_oracle(tmp_path):
    """End to end through the REAL entry point: the artifact that banked GREEN is now
    REFUSED. This is the assertion the whole change exists to make true."""
    result = oq.f2p_seed_gate(
        _REAL_B9_ORACLE, JOB_ORACLE_PATH_NODE, str(tmp_path),
        run=_fake_node_run("1..1\n# tests 1\n# pass 0\n# fail 1\n"))
    assert result.verdict == "refuse"
    assert result.language == "node"
    assert not result.seedable
    assert result.counts[oq.CLASS_ADEQUACY_FLOOR] >= 2


def test_gate_does_not_refuse_a_legitimate_node_oracle(tmp_path):
    """The toggle's other half: a sound oracle still seeds. A gate that refuses everything
    is indistinguishable from a gate that works, until it blocks real work."""
    result = oq.f2p_seed_gate(
        _LEGIT_ORACLE, JOB_ORACLE_PATH_NODE, str(tmp_path),
        run=_fake_node_run("1..4\n# tests 4\n# pass 0\n# fail 4\n"))
    assert result.verdict == "seed"
    assert result.seedable and result.language == "node"


def test_gate_no_longer_stamps_a_flat_skipped_collectability(tmp_path):
    """The instrument-honesty half (#1342 capability 7): the node path used to stamp
    `collectability: skipped` / `f2p_baseline: not-run` on EVERY run regardless of what
    happened, which read as a measurement while measuring nothing."""
    result = oq.f2p_seed_gate(
        _LEGIT_ORACLE, JOB_ORACLE_PATH_NODE, str(tmp_path),
        run=_fake_node_run("1..1\n# tests 1\n# pass 0\n# fail 1\n"))
    ev = result.to_evidence()
    assert ev["collectability"] == "confirmed"
    assert ev["f2p_baseline"] == "all-fail"


def test_gate_machinery_miss_still_seeds(tmp_path):
    """Fail-soft is PRESERVED: a machinery miss must never block a dispatch. Only a
    CONFIRMED defect refuses."""
    result = oq.f2p_seed_gate(
        _LEGIT_ORACLE, JOB_ORACLE_PATH_NODE, str(tmp_path), run=_fake_run(out="", err=""))
    assert result.verdict == "seed" and result.seedable
    assert result.f2p_baseline == "not-run"


def test_gate_unknown_ecosystem_still_seeds_unstamped(tmp_path):
    """The untouched branch: no runner exists for it, and the stamps say so."""
    result = oq.f2p_seed_gate("whatever", "tests/oracle.rb", str(tmp_path), run=_fake_run())
    assert result.verdict == "seed"
    assert result.collectability == "skipped" and result.f2p_baseline == "not-run"


# ---------------------------------------------------------------------------
# Reachability + the disengaged-lock proof (security_by_design 12)
# ---------------------------------------------------------------------------


def test_seed_gate_is_reached_for_a_node_oracle(tmp_path, monkeypatch):
    """`built-but-wired-into-nothing` is the recurring failure this pins: drive the REAL
    driver-side entry point and prove the node oracle actually reaches the gate."""
    monkeypatch.setenv("BLARAI_ORACLE_QA", "1")
    refusal = so._oracle_qa_seed_gate(
        _config(tmp_path), "R1", str(tmp_path), JOB_ORACLE_PATH_NODE, _REAL_B9_ORACLE, "",
        _fake_node_run("1..1\n# tests 1\n# pass 0\n# fail 1\n"))
    assert refusal is not None and refusal["ok"] is False


def test_disengaged_kill_switch_lets_the_vacuous_oracle_through(tmp_path, monkeypatch):
    """The toggle proof: with the QA kill-switch OFF the SAME oracle is NOT refused. Without
    this we could not distinguish 'the gate blocked it' from 'the probe never ran'."""
    monkeypatch.setenv("BLARAI_ORACLE_QA", "0")
    refusal = so._oracle_qa_seed_gate(
        _config(tmp_path), "R1", str(tmp_path), JOB_ORACLE_PATH_NODE, _REAL_B9_ORACLE, "",
        _fake_node_run("1..1\n# tests 1\n# pass 0\n# fail 1\n"))
    assert refusal is None


# ---------------------------------------------------------------------------
# LIVE — the real `node` binary against a real skeleton (mocks lie)
# ---------------------------------------------------------------------------


@_needs_node
def test_live_f2p_all_fail_on_a_greenfield_skeleton(tmp_path):
    """MEASURED, and the reason the static pass is not optional: on a tree where the
    product does not exist the oracle's imports do not resolve, node reports ONE failing
    aggregate, and F2P legitimately returns `all-fail`. The escaped oracle is INVISIBLE to
    the execution stage here — it is the static pass that convicts it."""
    stamp, findings = oq.node_fail_to_pass_baseline(_REAL_B9_ORACLE, str(tmp_path))
    assert stamp == "all-fail" and findings == []


@_needs_node
def test_live_f2p_convicts_when_the_imports_resolve(tmp_path):
    """The other half, measured: where the skeleton DOES satisfy the imports, every one of
    the escaped oracle's five tests passes with no product behind them, and the execution
    stage convicts all five."""
    (tmp_path / "src" / "contact").mkdir(parents=True)
    (tmp_path / "src" / "pieces").mkdir(parents=True)
    (tmp_path / "src" / "contact" / "enquiries.js").write_text(
        "export async function storeEnquiry(e) { return null; }\n", encoding="utf-8")
    (tmp_path / "src" / "pieces" / "data.js").write_text(
        "export async function getPieces() { return [{ id: 1, category: 'mugs' }]; }\n"
        "export async function getPieceById(id) { return null; }\n", encoding="utf-8")
    stamp, findings = oq.node_fail_to_pass_baseline(_REAL_B9_ORACLE, str(tmp_path))
    assert stamp.startswith("vacuous:")
    assert len(findings) == 5
    assert all(f.cls == oq.CLASS_F2P_VACUOUS and f.hard for f in findings)


#: A TRUNCATED oracle, the shape of `20260806-094526-bd` and `20260806-171303-bd` — both
#: real job oracles, both cut off mid-statement at exactly 6306 bytes (5 `{`, 4 `}`), and
#: both seeded as-is by the old node path because it ran no stage that could look. Kept
#: short here; the property under test is the truncation, not the length.
_TRUNCATED_ORACLE = """import test from 'node:test';
import assert from 'node:assert';
import { addHabit, getHabits } from '../src/routes/habits.js';

test('Add, edit, and delete habits', async () => {
  await addHabit('Exercise');
  const habits = await getHabits();
  assert.strictEqual(habits.length, 1);

  await addHabit('Cook');
  const habits55 = await get"""


def test_truncated_oracle_static_pass_is_fail_soft():
    """The masker cannot balance a truncated file, so it reports NOTHING rather than
    inventing findings from a half-parse. Convicting it is the collectability stage's job,
    and that stage is sound where this scan is heuristic."""
    assert oq.node_static_vacuity(_TRUNCATED_ORACLE) == []


@_needs_node
def test_live_truncated_oracle_is_refused_by_collectability(tmp_path):
    """The layering, measured on the real shape: the static pass abstains, `node --check`
    convicts, and the gate REFUSES. Two historical oracles carried this defect and seeded
    anyway — nothing on the node path ran a stage that could see it."""
    result = oq.f2p_seed_gate(_TRUNCATED_ORACLE, JOB_ORACLE_PATH_NODE, str(tmp_path))
    assert result.verdict == "refuse" and not result.seedable
    assert result.collectability == "unconfirmed"
    assert result.counts[oq.CLASS_COLLECTABILITY] == 1


@_needs_node
def test_live_node_check_confirms_a_valid_oracle():
    stamp, finding = oq.node_confirm_collectable(_REAL_B9_ORACLE)
    assert stamp == "confirmed" and finding is None


@_needs_node
def test_live_node_check_convicts_a_broken_oracle():
    stamp, finding = oq.node_confirm_collectable("test('x', () => {\n")
    assert stamp == "unconfirmed"
    assert finding is not None and finding.hard


@_needs_node
def test_live_gate_refuses_the_real_oracle_end_to_end(tmp_path):
    """The whole arc on real machinery: real node, real skeleton, real entry point. The
    run that banked GREEN on 2026-08-07 does not seed."""
    result = oq.f2p_seed_gate(_REAL_B9_ORACLE, JOB_ORACLE_PATH_NODE, str(tmp_path))
    assert result.verdict == "refuse" and not result.seedable
    assert result.collectability == "confirmed"
    assert result.f2p_baseline == "all-fail"


@_needs_node
def test_live_gate_seeds_a_legitimate_oracle(tmp_path):
    """The false-positive guard on real machinery — the assertion that keeps this gate
    usable. A sound oracle passes every stage against a real greenfield skeleton."""
    result = oq.f2p_seed_gate(_LEGIT_ORACLE, JOB_ORACLE_PATH_NODE, str(tmp_path))
    assert result.verdict == "seed" and result.seedable
    assert result.collectability == "confirmed"
    assert result.f2p_baseline == "all-fail"


# ---------------------------------------------------------------------------
# #1350 — the node not-run stamp must say WHY
#
# The python path has used `_not_run(diagnostics, cause, detail)` since that helper landed —
# a helper written FOR this ticket. Its node sibling returned a bare `("not-run", [])` at all
# five exits, so the ecosystem the operator actually cares about (websites are node jobs) had
# the undiagnosable stamp. Lesson 342's predicate: the honest treatment was applied at one
# site and not run over its sibling.
# ---------------------------------------------------------------------------


def _trivial_oracle() -> str:
    return "import {test} from 'node:test';\ntest('x', () => {});\n"


def test_node_f2p_names_an_absent_skeleton(tmp_path):
    diag: dict = {}
    stamp, findings = oq.node_fail_to_pass_baseline(
        _trivial_oracle(), str(tmp_path / "does-not-exist"), diagnostics=diag)
    assert stamp == "not-run"
    assert findings == []          # a machinery miss is fail-soft, never a finding
    assert diag["cause"] == "skeleton-absent"
    assert "not a directory" in diag["detail"]


def test_node_f2p_banks_the_runners_last_words_when_tap_says_nothing(tmp_path):
    """The exit that fired on every pre-2026-08-09 node record. On a node oracle this is
    almost always ESM resolution against the pre-implementation skeleton, and that is
    unreadable from the stamp alone — so the command and both streams are banked."""
    diag: dict = {}
    stamp, _ = oq.node_fail_to_pass_baseline(
        _trivial_oracle(), str(tmp_path),
        run=lambda *a, **k: (False, "", "ERR_MODULE_NOT_FOUND: '../src/pieces/data.js'"),
        diagnostics=diag)
    assert stamp == "not-run"
    assert diag["cause"] == "runner-produced-nothing"
    assert "ERR_MODULE_NOT_FOUND" in diag["stderr_tail"]
    assert "--test" in diag["cmd"]
    assert diag["elapsed_s"] is not None


def test_node_f2p_names_the_exception_instead_of_swallowing_it(tmp_path):
    """`except Exception: return ("not-run", [])` collapsed every machinery failure into one
    silent word. Fail-soft is correct here; fail-SILENT never was."""
    def boom(*a, **k):
        raise RuntimeError("subprocess exploded")

    diag: dict = {}
    stamp, _ = oq.node_fail_to_pass_baseline(
        _trivial_oracle(), str(tmp_path), run=boom, diagnostics=diag)
    assert stamp == "not-run"
    assert diag["cause"] == "raised"
    assert "RuntimeError" in diag["detail"]
    assert "subprocess exploded" in diag["detail"]


def test_the_node_stamp_is_never_decorated(tmp_path):
    """[kill] Several gates decide whether an oracle may DELETE work by membership test
    against STAMPS_NOT_MEASURED. A decorated stamp like `not-run:timeout` would fail that
    test and turn an unvalidated oracle back into evidence — the #1342 amputation. The cause
    goes in the diagnostics dict; the stamp string stays exactly `not-run`."""
    for runner in (None, (lambda *a, **k: (False, "", "x"))):
        diag: dict = {}
        kw = {"diagnostics": diag}
        if runner is not None:
            kw["run"] = runner
        stamp, _ = oq.node_fail_to_pass_baseline(
            _trivial_oracle(), str(tmp_path / "nope"), **kw)
        assert stamp == "not-run"
        assert stamp in oq.STAMPS_NOT_MEASURED


def test_node_diagnostics_reach_the_banked_evidence(tmp_path):
    """[kill] Wiring: without _node_seed_gate threading the dict through, the diagnostics are
    collected and dropped — the built-but-wired-into-nothing shape this repo keeps paying for."""
    result = oq.f2p_seed_gate(
        _trivial_oracle(), JOB_ORACLE_PATH_NODE, str(tmp_path / "absent"))
    evidence = result.to_evidence()
    assert evidence["language"] == "node"
    assert evidence["f2p_baseline"] == "not-run"
    assert evidence["not_measured_detail"]["cause"] == "skeleton-absent"


def test_a_measured_node_run_carries_no_not_run_diagnostics(tmp_path):
    """[quiet] The other direction: a baseline that RAN must not leave a cause behind. A
    diagnostics dict that is populated on success would make every record look like a failure."""
    diag: dict = {}
    stamp, _ = oq.node_fail_to_pass_baseline(
        _trivial_oracle(), str(tmp_path),
        run=lambda *a, **k: (False, "TAP version 13\n1..1\nnot ok 1 - x\n# fail 1\n", ""),
        diagnostics=diag)
    assert stamp == "all-fail"
    assert diag == {}
