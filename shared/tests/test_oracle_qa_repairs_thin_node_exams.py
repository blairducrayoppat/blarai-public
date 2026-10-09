"""A thin node exam must be REPAIRED, not merely refused (#1410).

WHAT THIS CLOSES. `validate_authored_oracle` has a bounded regeneration loop: it finds one
named defect, hands the model single-focus feedback, and re-authors — up to
`MAX_REGEN_ROUNDS`. It is the only mechanism in the system that turns a bad exam into a good
one.

The per-test node vacuity checks — `node_static_vacuity`, which convicts a `.mjs` test with
an empty body or no assertion — were called from exactly ONE place: `_node_seed_gate`, which
runs AFTER validation is over. So for node exams the loop never saw the defect it most needed
to see. The evidence is on disk in the 2026-08-14 B9 run:

    findings.adequacy_floor : 2
    regeneration.rounds     : 0
    verdict                 : refuse

Two adequacy findings, zero repair attempts. Nine consecutive runs recorded `verdict: refuse`
and the multi-page website card has therefore never been gradeable — a second, independent
reason on top of the dependency gate in #1381.

The refusal itself was working correctly and is not what this file changes: a refused exam is
never seeded, and the 2026-08-14 run was honestly labelled `ORACLE-DEFECT` with the
fingerprint `oracle-qa verdict=refuse (adequacy_floor)`. What was missing is the feedback path
from the instrument back to the author.

WHAT THIS DOES NOT CLAIM. Regeneration is bounded and the model may fail to improve the exam;
`regenerate_exhausted` remains a legitimate outcome and still refuses. This asserts that the
loop is REACHED and ATTEMPTS a repair — not that a repair always succeeds. An exam nobody
tried to fix and an exam that could not be fixed are different results, and only the second is
honest.
"""

from __future__ import annotations

from shared.fleet import oracle_qa
from shared.fleet.acceptance import AcceptanceCriterion, AcceptanceSpec

#: The escaped B9 exam's defining shape: a test that asserts nothing and calls nothing.
#: Kept close to the real one (`state/fleet-runs/*/job-oracle-acceptance.job.test.mjs`)
#: rather than minimised, so the fixture stays recognisable as the thing that shipped.
THIN_EXAM = """\
import test from 'node:test'; import assert from 'node:assert';
import { getPieces } from '../src/pieces/data.js';

test('Verify all pages are accessible', async () => {
  // This test would be implemented with a server and HTTP requests.
  // For the purpose of this test file, we assume the pages are accessible.
});

test('Verify pieces load', async () => {
  const pieces = await getPieces();
  assert.ok(pieces.length > 0);
});
"""

REPAIRED_EXAM = """\
import test from 'node:test'; import assert from 'node:assert';
import { getPieces, getPieceById } from '../src/pieces/data.js';

test('Verify a piece can be fetched by id', async () => {
  const pieces = await getPieces();
  const fetched = await getPieceById(pieces[0].id);
  assert.equal(fetched.id, pieces[0].id);
});

test('Verify pieces load', async () => {
  const pieces = await getPieces();
  assert.ok(pieces.length > 0);
});
"""


def _spec() -> AcceptanceSpec:
    return AcceptanceSpec(
        "a website for a pottery studio",
        (AcceptanceCriterion("c1", "each piece has its own page", "test", ""),),
    )


def _tasks() -> "list[dict]":
    return [{"repo": "pottery", "task": "create-piece-detail-page", "prompt": "build it"}]


# ── the defect, asserted before the fix is exercised ────────────────────────


def test_the_thin_exam_really_is_convicted_by_the_per_test_checks():
    """The premise. If this ever goes green the fixture stopped being thin and every
    assertion below is measuring nothing."""
    findings = oracle_qa.node_static_vacuity(THIN_EXAM)
    assert findings, "the fixture must be convictable"
    assert any(f.cls == oracle_qa.CLASS_ADEQUACY_FLOOR for f in findings)
    assert all(f.hard for f in findings), "these are HARD shapes — they cannot fail on any tree"


def test_the_repaired_exam_is_NOT_convicted():
    """Precision: the checks must accept a real exam, or the loop below could never
    terminate on success and 'repair' would be unreachable by construction."""
    assert not oracle_qa.node_static_vacuity(REPAIRED_EXAM)


# ── the lock ────────────────────────────────────────────────────────────────


def test_a_thin_node_exam_REACHES_the_regeneration_loop():
    """THE LOCK. The loop must be given a chance to fix what the seed gate would only refuse.

    Asserted on `regen_rounds`, which is the observable that was 0 on the shipped run —
    not on the verdict, because a verdict of `seed` would also be produced by a model that
    happened to author well the first time, and that is not what broke."""
    calls: list[str] = []

    def generate_fn(prompt: str) -> str:
        calls.append(prompt)
        return REPAIRED_EXAM

    result = oracle_qa.validate_authored_oracle(
        THIN_EXAM, "node", _spec(), _tasks(), generate_fn=generate_fn,
    )

    assert result.regen_rounds >= 1, (
        "the thin exam was never handed to the regeneration loop — this is the shipped "
        "defect: adequacy findings recorded with regeneration.rounds = 0, so the model was "
        "never asked to try again, nine runs in a row"
    )
    assert calls, "the loop reported a round without asking the model for anything"


def test_the_repair_is_offered_the_defect_by_name():
    """Single-focus feedback is what makes the loop work at all — a re-author prompt that
    does not name the defect is a re-roll, not a repair."""
    seen: list[str] = []

    def generate_fn(prompt: str) -> str:
        seen.append(prompt)
        return REPAIRED_EXAM

    oracle_qa.validate_authored_oracle(
        THIN_EXAM, "node", _spec(), _tasks(), generate_fn=generate_fn,
    )

    joined = "\n".join(seen).lower()
    assert "empty body" in joined or "asserts nothing" in joined or "assertion" in joined, (
        "the re-author prompt did not name the vacuity defect, so the model has no more "
        "information than it had the first time"
    )


def test_WITHOUT_the_routing_the_loop_is_never_reached___the_toggle():
    """THE TOGGLE, and it reproduces the shipped defect exactly.

    Plan-time QA returned early for ANY non-python ecosystem — *"we cannot AST-scan JS"*,
    true when written, false since `node_static_vacuity` was built for the seed gate. Node
    was one of those early returns, so the repair loop was never entered at all.

    Any other non-python ecosystem still takes that branch, so it stands in for the pre-fix
    node behaviour: same thin exam, same model, and the result is `rounds = 0` with nothing
    asked — the exact pair the 2026-08-14 evidence recorded.

    Without this, the lock above would pass on any build that happened to call the model once
    and nobody would learn that the ROUTING is what changed."""
    def generate_fn(prompt: str) -> str:  # pragma: no cover — must never be called
        raise AssertionError("the pre-fix path must not reach the model")

    pre_fix = oracle_qa.validate_authored_oracle(
        THIN_EXAM, "go", _spec(), _tasks(), generate_fn=generate_fn,
    )
    assert pre_fix.regen_rounds == 0, (
        "the early-return branch attempted a repair — then it is no longer the pre-fix "
        "behaviour and this toggle proves nothing"
    )
    assert not pre_fix.findings, "the early return records no findings, by construction"

    post_fix = oracle_qa.validate_authored_oracle(
        THIN_EXAM, "node", _spec(), _tasks(), generate_fn=lambda p: REPAIRED_EXAM,
    )
    assert post_fix.regen_rounds >= 1, "node is still taking the early return"


def test_a_python_oracle_still_takes_the_python_path():
    """Precision: the routing is on `ecosystem == "node"` only, so a python oracle is
    untouched. A fix that quietly moved python onto the node stages would drop every
    contract, strategy and traceability check it currently has."""
    py_code = "def test_thing():\n    assert 1 == 1\n"
    result = oracle_qa.validate_authored_oracle(
        py_code, "python", _spec(), _tasks(), generate_fn=lambda p: py_code,
    )
    assert result.language == "python"
    # The python path measures collectability; the node path explicitly does not.
    assert result.collectability != "skipped"


def test_an_unknown_ecosystem_is_unchanged():
    """The other half of the routing: anything that is neither python nor node keeps the
    honest validated-but-unscanned stamp it had before."""
    result = oracle_qa.validate_authored_oracle(
        THIN_EXAM, "rust", _spec(), _tasks(), generate_fn=lambda p: THIN_EXAM,
    )
    assert result.collectability == "skipped"
    assert result.regen_rounds == 0
