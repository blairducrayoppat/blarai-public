"""Tests for #1044 (S3 slice D) — the bad-input coverage floor on the acceptance exam.

The gap being closed is measured, not hypothetical: a flashcards build passed every automated
grading layer — the per-task oracles, the job-level exam, the sandbox's own eight test files,
and the ``green_quality`` juror, which scored it ``bad_input_handling=graceful`` — while the
shipped ``run_quiz`` raised ``KeyError`` on a card dict without a ``question`` key and
``AttributeError`` on an answer that was not a string. Both were confirmed by execution.

So the load-bearing test in this file is not "the floor is injected". It is
:func:`test_the_floor_goes_RED_on_the_measured_B4_defect`, which reconstructs that defect,
shows the ORIGINAL happy-path exam passing against it (the #1044 finding, reproduced), and
shows the FLOORED exam failing against it and passing against the fixed build. A lock that has
only ever been watched passing cannot distinguish "the property holds" from "the probe cannot
reach the property".

The toggle-off bar is the standing one for every advanced-intake slice: with the flag off the
plan is byte-identical, and — because this floor is a sub-gate — with ``advanced_intake`` ON
but ``bad_input_floor`` off it is *also* byte-identical, which is what stops an already-live
flag from changing what a build is graded on as a side effect.

Model calls are faked throughout (offline, GPU-free).
"""

from __future__ import annotations

import ast
import json
import pathlib
import sys
import textwrap

import pytest

#: The repo root, for the out-of-process dormancy probe below.
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

from shared.fleet.acceptance import (
    JOB_ORACLE_CODE_KEY,
    AcceptanceCriterion,
    AcceptanceSpec,
    DecompositionOverride,
    _ensure_bad_input_floor,
    generate_plan,
)
from shared.fleet.bad_input_floor import (
    BAD_INPUT_FLOOR_MARKER,
    FLOOR_TEST_PREFIX,
    bad_input_floor_targets,
    inject_bad_input_floor,
)

# ---------------------------------------------------------------------------
# The measured #1044 evidence, reconstructed.
#
# `run_quiz` subscripts `card['question']` / `card['answer']` directly and calls `.strip()` on
# whatever `answer_fn` returns; `load_cards` validates only the OUTER container. Both defects
# were confirmed by executing the real shipped file (ticket #1044, CLAIM 1 / CLAIM 2).
# ---------------------------------------------------------------------------

_DEFECTIVE_QUIZ_ENGINE = '''
import json


def load_cards(path):
    """Validates the outer container ONLY - a list of anything loads cleanly."""
    with open(path, encoding="utf-8") as fh:
        cards = json.load(fh)
    return cards if isinstance(cards, list) else []


def run_quiz(cards, answer_fn):
    asked = 0
    correct = 0
    for card in cards:
        asked += 1
        user_answer = answer_fn(card["question"])
        if user_answer.strip().lower() == card["answer"].strip().lower():
            correct += 1
    return {"asked": asked, "correct": correct}
'''

_FIXED_QUIZ_ENGINE = '''
import json


def load_cards(path):
    if not isinstance(path, str) or not path:
        raise ValueError("path must be a non-empty string")
    with open(path, encoding="utf-8") as fh:
        cards = json.load(fh)
    if not isinstance(cards, list):
        return []
    return [c for c in cards if isinstance(c, dict) and "question" in c and "answer" in c]


def run_quiz(cards, answer_fn):
    if not isinstance(cards, list):
        raise ValueError("cards must be a list of card dicts")
    if not callable(answer_fn):
        raise ValueError("answer_fn must be callable")
    asked = 0
    correct = 0
    for card in cards:
        if not isinstance(card, dict) or "question" not in card or "answer" not in card:
            continue
        asked += 1
        user_answer = answer_fn(card["question"])
        if not isinstance(user_answer, str):
            continue
        if user_answer.strip().lower() == str(card["answer"]).strip().lower():
            correct += 1
    return {"asked": asked, "correct": correct}
'''

#: The happy-path-only exam: exactly the shape that certified the defective build GREEN.
_HAPPY_PATH_EXAM = '''
from app.quiz_engine import run_quiz


def test_scores_a_correct_answer():
    cards = [{"question": "capital of France", "answer": "Paris"}]
    assert run_quiz(cards, lambda q: "Paris") == {"asked": 1, "correct": 1}
'''


# ---------------------------------------------------------------------------
# Running an exam against a build, in-process.
# ---------------------------------------------------------------------------


def _install_build(tmp_path, source: str, module: str = "quiz_engine") -> None:
    """Write ``app/<module>.py`` with *source* and make it importable from ``tmp_path``."""
    pkg = tmp_path / "app"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / f"{module}.py").write_text(textwrap.dedent(source), encoding="utf-8")


def _run_exam(tmp_path, exam_code: str, build: str, test_prefix: str,
              module: str = "quiz_engine") -> list[str]:
    """Execute *exam_code* against *build* and return the names of the tests that FAILED.

    Drives the REAL emitted source through a real import of a real module, rather than
    asserting on the generated text: the text looking right is what every layer in #1044
    already had. Only test functions whose name starts with *test_prefix* are run, so one
    call can ask "what did the happy-path tests do" and another "what did the floor do".
    """
    _install_build(tmp_path, build, module)
    sys.path.insert(0, str(tmp_path))
    stale = [m for m in sys.modules if m == "app" or m.startswith("app.")]
    saved = {m: sys.modules.pop(m) for m in stale}
    try:
        namespace: dict = {"__name__": "_bif_exam_under_test"}
        exec(compile(exam_code, "<exam>", "exec"), namespace)  # noqa: S102 — the unit under test
        failed: list[str] = []
        for name, fn in sorted(namespace.items()):
            if not name.startswith(test_prefix) or not callable(fn):
                continue
            try:
                fn()
            except Exception:  # noqa: BLE001 — any raise is a failing test, whatever the class
                failed.append(name)
        return failed
    finally:
        for m in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
            sys.modules.pop(m, None)
        sys.modules.update(saved)
        sys.path.remove(str(tmp_path))


# ---------------------------------------------------------------------------
# THE load-bearing test: the floor goes RED on the defect, and only on the defect.
# ---------------------------------------------------------------------------


def test_the_floor_goes_RED_on_the_measured_B4_defect(tmp_path):
    """#1044 end to end, on the real evidence.

    Three assertions in one, because separately none of them means anything:

    1. the happy-path exam PASSES against the defective build — the finding itself, and the
       control that proves this file is not testing a build that was already failing;
    2. the FLOORED exam FAILS it, naming the entry point;
    3. the floored exam PASSES against a build that validates its input.

    Without (1) the RED in (2) could be any old broken build; without (3) the floor could be
    a probe that fails against everything, which is the same as no signal at all.
    """
    floored = inject_bad_input_floor(_HAPPY_PATH_EXAM)
    assert floored != _HAPPY_PATH_EXAM, "the floor did not inject — the rest proves nothing"

    # 1. The happy path is green on the broken build. This IS the #1044 finding.
    assert _run_exam(tmp_path, _HAPPY_PATH_EXAM, _DEFECTIVE_QUIZ_ENGINE, "test_scores") == []

    # 2. The floor is RED on it.
    red = _run_exam(tmp_path, floored, _DEFECTIVE_QUIZ_ENGINE, "test_bad_input_floor__")
    assert red == ["test_bad_input_floor__app_quiz_engine__run_quiz"], (
        "the bad-input floor did not catch the two measured crashes "
        f"(KeyError on a missing card key, AttributeError on a non-string answer); failed={red}"
    )

    # 3. ... and GREEN on a build that validates.
    assert _run_exam(tmp_path, floored, _FIXED_QUIZ_ENGINE, "test_bad_input_floor__") == [], (
        "the floor failed a build that rejects bad input properly — it is convicting valid work"
    )
    # and the original test still passes on the fixed build (the floor changed no behaviour)
    assert _run_exam(tmp_path, floored, _FIXED_QUIZ_ENGINE, "test_scores") == []


def test_each_measured_crash_class_is_caught_on_its_own(tmp_path):
    """The two #1044 claims, isolated — so a future narrowing of the value ladder that drops
    one of them fails HERE, naming which, instead of silently halving the floor's reach."""
    missing_key_only = '''
def run_quiz(cards, answer_fn):
    if not callable(answer_fn):
        raise ValueError("answer_fn must be callable")
    for card in cards:
        answer_fn(card["question"])          # CLAIM 1: KeyError on a card without the key
    return {"asked": 0, "correct": 0}
'''
    non_string_only = '''
def run_quiz(cards, answer_fn):
    if not isinstance(cards, list) or not callable(answer_fn):
        raise ValueError("bad arguments")
    for card in cards:
        if not isinstance(card, dict):
            continue
        answer_fn(card.get("question")).strip()   # CLAIM 2: AttributeError on a non-string
    return {"asked": 0, "correct": 0}
'''
    floored = inject_bad_input_floor(_HAPPY_PATH_EXAM)
    for label, build in (("CLAIM 1 (missing key)", missing_key_only),
                         ("CLAIM 2 (non-string answer)", non_string_only)):
        failed = _run_exam(tmp_path, floored, build, "test_bad_input_floor__")
        assert failed == ["test_bad_input_floor__app_quiz_engine__run_quiz"], (
            f"the floor missed {label} — it only catches the two claims together, which means "
            "the ladder is narrower than the evidence it was built from"
        )


def test_rejecting_bad_input_LOUDLY_is_a_pass_not_a_failure(tmp_path):
    """Raising on bad input is CORRECT handling. A floor that punished it would push builds
    toward swallowing errors — the opposite of the property #1044 wants."""
    strict = '''
def run_quiz(cards, answer_fn):
    if not isinstance(cards, list):
        raise TypeError("cards must be a list")
    if not callable(answer_fn):
        raise ValueError("answer_fn must be callable")
    raise RuntimeError("deliberate domain failure")
'''
    floored = inject_bad_input_floor(_HAPPY_PATH_EXAM)
    assert _run_exam(tmp_path, floored, strict, "test_bad_input_floor__") == []


def test_a_cli_that_exits_on_bad_input_is_a_pass(tmp_path):
    """``argparse`` raises ``SystemExit`` on a bad argument; that is a handled outcome, and a
    ``SystemExit`` escaping the probe would otherwise abort the whole test session."""
    exiting = '''
import sys


def run_quiz(cards, answer_fn):
    sys.exit(2)
'''
    floored = inject_bad_input_floor(_HAPPY_PATH_EXAM)
    assert _run_exam(tmp_path, floored, exiting, "test_bad_input_floor__") == []


# ---------------------------------------------------------------------------
# The quantifier: which entry points the floor covers
# ---------------------------------------------------------------------------


def test_targets_are_the_first_party_callables_the_exam_invokes():
    exam = (
        "import json\n"
        "import pytest\n"
        "from app.stats import summarize\n"
        "import report\n"
        "def test_a():\n"
        "    assert summarize([1, 2]) == 1.5\n"
        "    assert report.render('x', mode='terse')\n"
        "    assert json.dumps({}) == '{}'\n"
    )
    targets = {(t.module, t.name, t.shapes) for t in bad_input_floor_targets(exam)}
    assert targets == {
        ("app.stats", "summarize", ((1, ()),)),
        ("report", "render", ((1, ("mode",)),)),
    }


def test_a_deep_import_chain_is_NOT_a_target_inherited_limitation():
    """``import app.report`` then ``app.report.render(...)`` binds only the name ``app``, and
    the interface-contract derivation records the two unambiguous shapes on purpose — a
    resolution it is not sure of would put a call it invented into the exam, and a spurious
    failure convicts valid work. The floor inherits that precision-first boundary rather than
    widening it locally, so this exam is UNFLOORED. Named here because an unfloored exam looks
    exactly like a floored one from the outside, and the honest limit belongs in a test rather
    than in prose nobody re-reads."""
    exam = (
        "import app.report\n"
        "def test_a():\n"
        "    assert app.report.render('x')\n"
    )
    assert bad_input_floor_targets(exam) == ()


def test_stdlib_and_test_framework_calls_are_never_targets():
    """A false first-party classification would have the floor import the standard library and
    call it with junk, which can only ever produce a RED against a build that did nothing
    wrong. Both filters are applied, so a module either survives the interpreter's own stdlib
    set AND the curated oracle list, or it is not driven."""
    exam = (
        "import json, sqlite3, hashlib, subprocess\n"
        "import pytest\n"
        "def test_a():\n"
        "    json.loads('{}')\n"
        "    sqlite3.connect(':memory:')\n"
        "    hashlib.sha256(b'x')\n"
        "    subprocess.run(['echo'])\n"
        "    pytest.approx(1.0)\n"
    )
    assert bad_input_floor_targets(exam) == ()


def test_a_zero_argument_entry_point_is_not_a_target():
    """There is no input to malform, and asserting "it runs" duplicates the exam's own smoke
    test. B6's ``run_cli()`` is the real shape this protects."""
    exam = (
        "from app.cli import run_cli\n"
        "def test_a():\n"
        "    assert run_cli() == 0\n"
    )
    assert bad_input_floor_targets(exam) == ()


def test_every_observed_arity_is_driven_not_the_widest():
    """Two call sites, two arities — BOTH are driven. Taking only the widest would leave the
    narrow site's own bad-input behaviour unmeasured whenever the callee has defaults."""
    exam = (
        "from app.core import fetch\n"
        "def test_a():\n"
        "    fetch('a')\n"
        "def test_b():\n"
        "    fetch('a', 2)\n"
    )
    assert [t.shapes for t in bad_input_floor_targets(exam)] == [((1, ()), (2, ()))]


def test_call_sites_are_NEVER_merged_across_positional_and_keyword(tmp_path):
    """F1, the blocker this fix exists for, locked at both layers.

    An exam calling ``check_answer(a, b)`` at one site and ``check_answer(a, expected=b)`` at
    another merges — under the ``probe_signatures`` view the first version used — into
    ``(2 positional, keyword expected)``. No site ever performed that call; the callee raises
    ``TypeError: got multiple values for argument 'expected'`` at ARGUMENT BINDING, which the
    ladder cannot distinguish from "the callee rejected the input", so every row was swallowed
    and the emitted test passed green having never entered the function. A defective build was
    certified by the floor built to catch defective builds.

    Asserted at the derivation (shapes stay per-site) AND through execution (the floor is RED
    on a build that crashes), because the first is the fix and the second is the consequence.
    """
    exam = (
        "from app.grader import check_answer\n"
        "def test_positional():\n"
        "    assert check_answer('paris', 'paris')\n"
        "def test_keyword():\n"
        "    assert check_answer('paris', expected='paris')\n"
    )
    shapes = bad_input_floor_targets(exam)[0].shapes
    assert shapes == ((2, ()), (1, ("expected",))), \
        "call sites were merged — the floor is synthesising a shape the exam never performed"
    assert not any(positional == 2 and kws for positional, kws in shapes), \
        "a merged positional+keyword shape survived; it can never bind"

    crashes_on_bad_input = '''
def check_answer(given, expected):
    return given.strip().lower() == expected.strip().lower()
'''
    floored = inject_bad_input_floor(exam)
    failed = _run_exam(tmp_path, floored, crashes_on_bad_input,
                       "test_bad_input_floor__", module="grader")
    assert failed == ["test_bad_input_floor__app_grader__check_answer"], \
        "the floor passed a build that crashes on bad input — F1 has regressed"


def test_a_target_whose_shapes_can_NEVER_bind_fails_LOUDLY(tmp_path):
    """The second half of F1's fix, and the one that stops a repeat being silent.

    Whatever the derivation does, a row that cannot bind never enters the callee, and a probe
    that measured nothing must not report the same green as one that measured and survived.
    This module's own stated contract is that an absent measurement is never a clean bill; the
    emitted test now honours it.
    """
    exam = (
        "from app.grader import check_answer\n"
        "def test_a():\n"
        "    assert check_answer('a', 'b')\n"
    )
    wrong_signature = '''
def check_answer(only_one):
    return bool(only_one)
'''
    floored = inject_bad_input_floor(exam)
    failed = _run_exam(tmp_path, floored, wrong_signature, "test_bad_input_floor__",
                       module="grader")
    assert failed == ["test_bad_input_floor__app_grader__check_answer"], \
        "a floor test that never entered the callee reported green"


def test_an_under_determined_call_site_is_not_driven():
    """``f('a', *rest)`` records a LOWER BOUND on the argument count, not the count. Building a
    call from a lower bound is a guess dressed as an observation — the F1 class again — so the
    site is skipped, and a target with no other site gets no floor test at all.

    The concrete leading argument is load-bearing in this fixture: a bare ``f(*rest)`` records
    zero positional arguments and would be dropped by the no-arguments rule regardless, so the
    test would pass with the under-determined skip deleted. (It did; the mutation caught it.)
    """
    exam = (
        "from app.core import fetch\n"
        "def test_a():\n"
        "    rest = ('b', 'c')\n"
        "    fetch('a', *rest)\n"
    )
    assert bad_input_floor_targets(exam) == ()


def test_a_call_site_wider_than_the_cap_is_SKIPPED_not_truncated():
    """N2. ``_MAX_POSITIONAL`` is a defensive cap, and the direction it fails in is the whole
    point: a call TRUNCATED to the cap is a shape the exam never performed, which is the F1
    class arriving through the back door — the callee cannot bind it, every row is swallowed as
    "rejected the input", and the floor reports green having entered nothing. Skipping loses
    coverage on one very wide entry point; truncating manufactures a false verdict on it.

    The cap itself is not the contract and may be retuned; skip-rather-than-truncate is.
    """
    from shared.fleet.bad_input_floor import _MAX_POSITIONAL

    args = ", ".join(f"'a{i}'" for i in range(_MAX_POSITIONAL + 1))
    exam = (
        "from app.core import wide\n"
        "def test_a():\n"
        f"    wide({args})\n"
    )
    assert bad_input_floor_targets(exam) == (), \
        "an over-wide call site was truncated to the cap instead of skipped"

    # ... and a site AT the cap is still driven, so the skip is a boundary, not a blanket
    at_cap = ", ".join(f"'a{i}'" for i in range(_MAX_POSITIONAL))
    exam_at_cap = (
        "from app.core import wide\n"
        "def test_a():\n"
        f"    wide({at_cap})\n"
    )
    assert [t.shapes for t in bad_input_floor_targets(exam_at_cap)] == [((_MAX_POSITIONAL, ()),)]


def test_unparseable_exam_yields_no_targets_and_no_injection():
    junk = "def test_a(:\n  pass\n"
    assert bad_input_floor_targets(junk) == ()
    assert inject_bad_input_floor(junk) == junk


def test_an_aliased_import_targets_the_EXPORT_the_coder_must_provide():
    """``from app.core import fetch as grab`` binds ``grab`` locally but the coder provides
    ``fetch``. Emitting the local alias would produce an ImportError the build could never
    fix, so the target must be the export."""
    exam = (
        "from app.core import fetch as grab\n"
        "def test_a():\n"
        "    grab('x')\n"
    )
    targets = bad_input_floor_targets(exam)
    assert [(t.module, t.name) for t in targets] == [("app.core", "fetch")]
    assert "from app.core import fetch\n" in inject_bad_input_floor(exam)


# ---------------------------------------------------------------------------
# Injection mechanics
# ---------------------------------------------------------------------------


def test_injected_exam_parses_and_defines_one_reserved_test_per_target():
    floored = inject_bad_input_floor(_HAPPY_PATH_EXAM)
    tree = ast.parse(floored)  # would raise if the emitted block were malformed
    names = [n.name for n in ast.walk(tree)
             if isinstance(n, ast.FunctionDef) and n.name.startswith("test_bad_input_floor__")]
    assert names == ["test_bad_input_floor__app_quiz_engine__run_quiz"]
    assert BAD_INPUT_FLOOR_MARKER in floored
    # the original exam is preserved verbatim, not rewritten
    assert floored.startswith(_HAPPY_PATH_EXAM.rstrip("\n"))


def test_injection_is_idempotent_BY_MARKER_not_by_inspection():
    """Idempotence is keyed on the reserved marker, the same identity discipline the delivery
    floor adopted (#1041) after a wording-based predicate was measured wrong in both
    directions. Re-running is a no-op because the MARKER is there, never because some test
    looked bad-input-ish."""
    once = inject_bad_input_floor(_HAPPY_PATH_EXAM)
    assert inject_bad_input_floor(once) == once
    assert once.count(BAD_INPUT_FLOOR_MARKER) == 1


def test_a_model_authored_bad_input_test_does_NOT_suppress_the_floor():
    """The floor never reads what the exam asserts. An exam that already tests bad input gets a
    redundant test; a false suppression would silently cost the guarantee for the whole exam,
    and that asymmetry is the whole reason detection was rejected."""
    exam = _HAPPY_PATH_EXAM + (
        "\n\ndef test_handles_empty_input():\n"
        "    assert run_quiz([], lambda q: '') == {'asked': 0, 'correct': 0}\n"
    )
    floored = inject_bad_input_floor(exam)
    assert "test_bad_input_floor__app_quiz_engine__run_quiz" in floored


def _emitted_block() -> str:
    """Just the injected block, with the original exam stripped off the front."""
    return inject_bad_input_floor(_HAPPY_PATH_EXAM)[len(_HAPPY_PATH_EXAM.rstrip("\n")):]


def test_the_malformed_VALUE_answers_every_duck_typed_access_it_claims_to():
    """Each of these is the probe's REACH, not a convenience.

    In round 1 they carry the probe past a callee's early accesses to where it assumes a type.
    In round 2 this object is the FILLER for every argument not being varied — so a method that
    raises instead of answering is an argument that rejects the call before the varied one is
    reached, collapsing round 2 back into round 1 and silently undoing the fix for the very
    defect this floor exists to catch. Asserted one behaviour at a time so a regression names
    which one went.
    """
    namespace: dict = {"__name__": "_bif_emitted_under_test"}
    exec(compile(_emitted_block(), "<emitted>", "exec"), namespace)  # noqa: S102
    bad = namespace["_bif_BadValue"]()

    assert bad("anything") == 0, "not callable — a callback argument would be rejected"
    assert list(bad) == [bad], "not iterable, or does not yield itself — a loop cannot proceed"
    assert len(bad) == 1, "not sized"
    assert bad["missing"] == 0, "subscripting RAISES — a lookup stops the probe at the door"
    assert bool(bad) is True, "falsy — an `if not x: raise` guard would reject it"
    assert repr(bad) == "<malformed>", "repr is not address-free; failure messages would differ"


def test_the_duck_typed_value_is_what_REACHES_a_crash_behind_a_lookup(tmp_path):
    """The behavioural half of the test above: a build whose only defect sits behind a subscript
    that it validates.

    Every plain ladder value is rejected cleanly here — ``None``/``""``/``0``/``[]``/``[{}]``
    raise ``TypeError`` on the lookup and ``{}`` raises ``KeyError``, both of which this build
    converts into a deliberate ``ValueError``. Only the duck-typed value ANSWERS the lookup, so
    only it reaches the line assuming the callback returned a string. Make ``__getitem__`` raise
    and this build reads as fully handled — which is precisely what a suite that never exercised
    the duck-typing could not tell you.
    """
    build = '''
def score(entry, grader):
    if not callable(grader):
        raise ValueError("grader must be callable")
    try:
        label = entry["label"]
    except (KeyError, TypeError):
        raise ValueError("entry needs a 'label'")
    return grader(label).strip()
'''
    exam = (
        "from app.scoring import score\n"
        "def test_a():\n"
        "    assert score({'label': 'x'}, lambda v: 'x') == 'x'\n"
    )
    failed = _run_exam(tmp_path, inject_bad_input_floor(exam), build,
                       "test_bad_input_floor__", module="scoring")
    assert failed == ["test_bad_input_floor__app_scoring__score"], \
        "the duck-typed value no longer reaches past a validated lookup"


def test_the_emitted_block_defines_NO_unreserved_module_level_name():
    """The other half of the naming contract. The reserved TEST-name infix is locked; the helper
    prefix was not — and the block is appended LAST, so an unprefixed ``survives`` or
    ``BadValue`` or ``VALUES`` would SHADOW a same-named module-level symbol in a model-authored
    exam and silently change what that exam's own tests do. Corrupting the measuring instrument
    is strictly worse than a collision that crashes.

    The reserved prefixes are written as LITERALS here rather than imported. The first version
    imported ``_EMIT_PREFIX`` and compared against it — which is vacuous, because setting that
    constant to ``""`` makes every name start with it and the check passes against exactly the
    defect it exists to catch. Mutation caught it. A test that reads the constant under test
    cannot judge the constant under test.
    """
    from shared.fleet.bad_input_floor import _EMIT_PREFIX

    reserved = ("_bif_", "test_bad_input_floor__")
    assert _EMIT_PREFIX == reserved[0], (
        "the helper prefix changed; that is a deliberate act, so update this literal "
        "deliberately too rather than letting the check follow it"
    )
    assert FLOOR_TEST_PREFIX == reserved[1]

    def _module_level_names(source: str) -> set:
        names: set = set()
        for node in ast.parse(source).body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.Assign):
                names.update(t.id for t in node.targets if isinstance(t, ast.Name))
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                names.update((a.asname or a.name).split(".")[0] for a in node.names)
        return names

    introduced = (_module_level_names(inject_bad_input_floor(_HAPPY_PATH_EXAM))
                  - _module_level_names(_HAPPY_PATH_EXAM))
    assert introduced, "the block introduced nothing — the fixture stopped exercising injection"
    unreserved = {n for n in introduced if not n.startswith(reserved)}
    assert not unreserved, (
        f"the emitted block defines unreserved module-level name(s) {sorted(unreserved)} — "
        "each would shadow a model-authored exam's own symbol of that name"
    )


def test_the_emitted_block_is_pure_ascii():
    """It is written into a sandbox tree this process does not own and re-read by the fleet's
    grader; one non-ASCII byte is a decode error on the first host whose default encoding is
    not UTF-8, and an unreadable exam is worse than an unfloored one."""
    assert _emitted_block().isascii(), \
        "the machine-injected block carries a non-ASCII character"


def test_an_empty_exam_is_returned_unchanged():
    assert inject_bad_input_floor("") == ""


def test_an_emitted_block_that_would_not_PARSE_is_discarded(monkeypatch):
    """The self-check: the floor may never turn a collectable exam into an uncollectable one.

    Reached by breaking the emitter deliberately, because on the shipped emitter it cannot be
    reached at all — the block is fixed text that begins at column zero, so appending it to any
    source that already parses still parses. That makes this guard insurance against a future
    change to the emitter rather than a live path, and the only honest way to show it BLOCKS is
    to hand it something broken. Untested, it would be indistinguishable from a guard that
    silently does nothing (it survived mutation testing until this test existed).
    """
    import shared.fleet.bad_input_floor as ruler

    monkeypatch.setattr(ruler, "_render_target", lambda _t: "\n\ndef broken(:\n    pass\n")
    assert ruler.inject_bad_input_floor(_HAPPY_PATH_EXAM) == _HAPPY_PATH_EXAM


# ---------------------------------------------------------------------------
# The acceptance.py gate: ecosystem + fail-soft
# ---------------------------------------------------------------------------


def _spec(language_hint="python", surface="command-line"):
    return AcceptanceSpec(
        goal="a flashcards quiz",
        criteria=(AcceptanceCriterion(id="c1", text="it quizzes", tier="behavior",
                                      check="run the quiz"),),
        build_plan={"surface": surface, "candidates": [], "language_hint": language_hint,
                    "complexity": "simple", "components": []},
    )


def test_gate_floors_a_python_exam():
    out = _ensure_bad_input_floor(_HAPPY_PATH_EXAM, _spec())
    assert BAD_INPUT_FLOOR_MARKER in out


def test_gate_refuses_on_ECOSYSTEM_not_merely_on_unparseable_source():
    """A node exam is out of contract by design: JavaScript has no equivalent crash family (a
    missing key yields ``undefined`` rather than raising), so the same ladder would assert a
    much weaker property, and a weak assertion made loudly is worse than an absent one.

    Driven with PYTHON source under a NODE spec on purpose. Real ``.mjs`` source never parses
    as Python, so an exam-shaped node probe would pass whether or not the ecosystem check
    existed — a lock that is green against the bug it guards. Holding the source constant and
    moving only the ecosystem is what makes this measure the gate.
    """
    node_spec = _spec(language_hint=None, surface="web")
    assert _ensure_bad_input_floor(_HAPPY_PATH_EXAM, node_spec) == _HAPPY_PATH_EXAM
    # the SAME source under a python spec IS floored — so the refusal above is the ecosystem
    assert BAD_INPUT_FLOOR_MARKER in _ensure_bad_input_floor(_HAPPY_PATH_EXAM, _spec())


def test_a_real_node_exam_is_left_alone():
    node_exam = (
        "import test from 'node:test';\n"
        "import assert from 'node:assert';\n"
        "import { runQuiz } from '../src/quiz.mjs';\n"
        "test('scores', () => { assert.ok(runQuiz([], () => '')); });\n"
    )
    spec = _spec(language_hint=None, surface="web")
    assert _ensure_bad_input_floor(node_exam, spec) == node_exam


def test_gate_leaves_an_unclassified_ecosystem_unchanged():
    assert _ensure_bad_input_floor(_HAPPY_PATH_EXAM, _spec(language_hint="dotnet",
                                                           surface="desktop")) \
        == _HAPPY_PATH_EXAM


def test_gate_is_fail_soft_AND_LOUD_when_the_ruler_crashes(monkeypatch, caplog):
    """A ruler bug must not sink a plan request — but an absent floor is an absent
    measurement, never a clean bill, so it is never silent."""
    import shared.fleet.bad_input_floor as ruler

    def boom(_code):
        raise RuntimeError("derivation exploded")

    monkeypatch.setattr(ruler, "inject_bad_input_floor", boom)
    with caplog.at_level("WARNING"):
        out = _ensure_bad_input_floor(_HAPPY_PATH_EXAM, _spec())
    assert out == _HAPPY_PATH_EXAM
    assert any("bad-input floor crashed" in r.getMessage() for r in caplog.records), \
        "the floor failed silently — a swallowed control failure is worse than no control"


# ---------------------------------------------------------------------------
# Through generate_plan — the seam, with the two-knob gate and the toggle-off bar
# ---------------------------------------------------------------------------


_PY_JOB_ORACLE = (
    "```python\n"
    "from app.quiz_engine import run_quiz\n"
    "\n"
    "def test_scores_a_correct_answer():\n"
    "    cards = [{'question': 'q', 'answer': 'a'}]\n"
    "    assert run_quiz(cards, lambda q: 'a') == {'asked': 1, 'correct': 1}\n"
    "```\n"
)


def _repo(tmp_path, name="flashcards"):
    proj = tmp_path / "projects"
    (proj / name / ".git").mkdir(parents=True, exist_ok=True)
    return proj, name


def _gen(prompt: str) -> str:
    if "decomposing a software change request" in prompt:
        return json.dumps([
            {"task": "engine", "prompt": "build the quiz engine", "depends_on": [],
             "contract": {"creates": ["app/quiz_engine.py"],
                          "exports": ["run_quiz(cards, answer_fn)"], "notes": ""}},
            {"task": "cli", "prompt": "build the cli", "depends_on": ["engine"],
             "contract": {"creates": ["app/cli.py"], "exports": ["main()"], "notes": ""}},
        ])
    if "ACCEPTANCE CRITERIA" in prompt:
        return json.dumps([{"text": "It scores a correct answer", "tier": "behavior",
                            "check": "run the quiz and check the tally"}])
    if "Classify what KIND of software" in prompt:
        return json.dumps({"surface": "command-line", "candidates": [],
                           "language_hint": "python", "complexity": "simple",
                           "components": []})
    if "JOB-LEVEL ACCEPTANCE" in prompt:
        return _PY_JOB_ORACLE
    return "[]"


def _job_exam(plan) -> str:
    return str(plan.tasks[-1].get(JOB_ORACLE_CODE_KEY, ""))


def test_both_knobs_ON_floors_the_job_exam(tmp_path):
    proj, repo = _repo(tmp_path)
    plan = generate_plan("a flashcards quiz", repo, generate_fn=_gen, projects_dir=proj,
                         advanced_intake=True, bad_input_floor=True)
    exam = _job_exam(plan)
    assert BAD_INPUT_FLOOR_MARKER in exam
    assert "test_bad_input_floor__app_quiz_engine__run_quiz" in exam


def test_advanced_intake_ALONE_does_not_floor_the_exam(tmp_path):
    """The sub-gate that matters: ``advanced_intake`` is already live, so if the floor rode it
    this change would go live at merge — a capability change with no ceremony. BOTH knobs are
    required, and this is the test that would catch a future refactor collapsing them."""
    proj, repo = _repo(tmp_path)
    plan = generate_plan("a flashcards quiz", repo, generate_fn=_gen, projects_dir=proj,
                         advanced_intake=True)
    assert BAD_INPUT_FLOOR_MARKER not in _job_exam(plan)


def test_bad_input_floor_ALONE_does_not_floor_the_exam(tmp_path):
    proj, repo = _repo(tmp_path)
    plan = generate_plan("a flashcards quiz", repo, generate_fn=_gen, projects_dir=proj,
                         bad_input_floor=True)
    assert BAD_INPUT_FLOOR_MARKER not in _job_exam(plan)


def test_floor_off_is_BYTE_IDENTICAL_through_generate_plan(tmp_path):
    """The standing toggle-off bar. Compared across the WHOLE compiled plan, not just the exam:
    the exam's bytes feed the coder's import + signature contract and the plan-time coverage
    warning, so a floor that leaked into any of them would change the dispatch while the flag
    read as off."""
    proj, repo = _repo(tmp_path)
    default = generate_plan("a flashcards quiz", repo, generate_fn=_gen, projects_dir=proj,
                            advanced_intake=True)
    explicit_off = generate_plan("a flashcards quiz", repo, generate_fn=_gen, projects_dir=proj,
                                 advanced_intake=True, bad_input_floor=False)
    on = generate_plan("a flashcards quiz", repo, generate_fn=_gen, projects_dir=proj,
                       advanced_intake=True, bad_input_floor=True)

    assert explicit_off.tasks == default.tasks
    assert explicit_off.message == default.message
    assert [c.to_dict() for c in explicit_off.spec.criteria] == \
           [c.to_dict() for c in default.spec.criteria]
    # ... and the ON run really is different, so the equality above is measuring the flag and
    # not a harness that cannot reach the behaviour at all.
    assert on.tasks != default.tasks
    # the floor touches ONLY the exam bytes — criteria and every non-final task are untouched
    assert [c.to_dict() for c in on.spec.criteria] == [c.to_dict() for c in default.spec.criteria]
    assert on.tasks[:-1] == default.tasks[:-1]


# ---------------------------------------------------------------------------
# The SINGLE-TASK shape (step 2e). Covered here because it was not covered at all: every
# generate_plan test above uses a >=2-task decomposition, where 2e never runs and
# ``oracle_code`` stays "". Two independent mutants survived the first review because of it —
# deleting the single-task floor call entirely, and feeding compile_prompts the PRE-floor exam.
#
# Not a corner case. Step 2e's own comment calls it "the MVP — the case best-of-N + self-written
# tests collide worst", and #1044's evidence, the B4 flashcards build, is a single-feature build.
# ---------------------------------------------------------------------------


_PY_TASK_ORACLE = (
    "```python\n"
    "from app.quiz_engine import run_quiz\n"
    "\n"
    "def test_scores_a_correct_answer():\n"
    "    assert run_quiz([{'question': 'q', 'answer': 'a'}], lambda q: 'a')\n"
    "```\n"
)


def _single_task_gen(prompt: str) -> str:
    if "decomposing a software change request" in prompt:
        return json.dumps([{"task": "engine", "prompt": "build the quiz engine",
                            "contract": {"creates": ["app/quiz_engine.py"],
                                         "exports": ["run_quiz(cards, answer_fn)"],
                                         "notes": ""}}])
    if "ACCEPTANCE CRITERIA" in prompt:
        return json.dumps([{"text": "It scores a correct answer", "tier": "behavior",
                            "check": "run the quiz and check the tally"}])
    if "Classify what KIND of software" in prompt:
        return json.dumps({"surface": "command-line", "candidates": [],
                           "language_hint": "python", "complexity": "simple",
                           "components": []})
    if "Write a COMPLETE Python pytest test file" in prompt:
        return _PY_TASK_ORACLE
    return "[]"


def _task_exam(plan) -> str:
    return str(plan.tasks[-1].get("acceptance_test_code", ""))


def test_the_SINGLE_TASK_exam_is_floored_too(tmp_path):
    """Step 2e's exam is the one a single-feature build is graded by, and it reaches the fleet
    through a different key (``acceptance_test_code``) than the job exam. Floored, or the whole
    single-task shape ships the gap #1044 is about."""
    proj, repo = _repo(tmp_path)
    plan = generate_plan("a flashcards quiz", repo, generate_fn=_single_task_gen,
                         projects_dir=proj, advanced_intake=True, bad_input_floor=True)
    assert len(plan.tasks) == 1, "the harness stopped producing the single-task shape"
    exam = _task_exam(plan)
    assert BAD_INPUT_FLOOR_MARKER in exam
    assert "test_bad_input_floor__app_quiz_engine__run_quiz" in exam


def test_the_single_task_floor_is_gated_and_byte_identical_when_off(tmp_path):
    proj, repo = _repo(tmp_path)
    default = generate_plan("a flashcards quiz", repo, generate_fn=_single_task_gen,
                            projects_dir=proj, advanced_intake=True)
    on = generate_plan("a flashcards quiz", repo, generate_fn=_single_task_gen,
                       projects_dir=proj, advanced_intake=True, bad_input_floor=True)
    assert BAD_INPUT_FLOOR_MARKER not in _task_exam(default)
    assert _task_exam(on) != _task_exam(default)


def test_the_floor_does_not_disturb_the_coder_facing_prompt(tmp_path):
    """Driven on the SINGLE-TASK shape, where ``compile_prompts`` actually derives the coder's
    import + signature contract FROM the exam — on the multi-task shape the oracle never
    reaches the prompt, so the same assertion there is vacuous and passes even when
    compile_prompts is fed the wrong exam.

    The injected imports are function-local and name modules the exam already imported, so the
    derived contract must be unchanged. If this fails, the floor is quietly rewriting what the
    coder was told to build."""
    proj, repo = _repo(tmp_path)
    default = generate_plan("a flashcards quiz", repo, generate_fn=_single_task_gen,
                            projects_dir=proj, advanced_intake=True)
    on = generate_plan("a flashcards quiz", repo, generate_fn=_single_task_gen,
                       projects_dir=proj, advanced_intake=True, bad_input_floor=True)
    # non-vacuity: the floor DID reach this shape's exam ...
    assert _task_exam(on) != _task_exam(default)
    # ... and still left the coder's instructions untouched.
    assert [t.get("prompt") for t in on.tasks] == [t.get("prompt") for t in default.tasks]


def test_a_battery_card_never_receives_the_bad_input_floor(tmp_path):
    """A card IS the exam, frozen for cross-night comparability — and #1044's own evidence came
    from a card's exam, so silently re-flooring one would make the finding un-observable in the
    very place it was found. Also covers the caller-authorised oracle branch (#752 F2), whose
    exam the caller owns and this ruler may not rewrite."""
    proj, repo = _repo(tmp_path, "battery-b4-flashcards-cli")
    override = DecompositionOverride(
        tasks=[{"task": "engine", "prompt": "build it",
                "contract": {"creates": ["app/quiz_engine.py"], "exports": []}}],
        job_oracle_code="from app.quiz_engine import run_quiz\n\n"
                        "def test_it():\n    assert run_quiz([], lambda q: '')\n",
        job_oracle_path="tests/test_job_acceptance.py",
    )
    plan = generate_plan("a flashcards quiz", repo, generate_fn=_gen, projects_dir=proj,
                         advanced_intake=True, bad_input_floor=True,
                         decomposition_override=override)
    assert BAD_INPUT_FLOOR_MARKER not in _job_exam(plan), \
        "the bad-input floor rewrote a frozen battery card's exam"


def test_a_card_sandbox_repo_is_suppressed_even_WITHOUT_an_override(tmp_path):
    """The #1041 blocker shape: an override is built only for cards with a registered arm
    builder, so most cards arrive with ``override=None`` and only the repo prefix marks them."""
    proj, repo = _repo(tmp_path, "battery-b5-habit-web")
    plan = generate_plan("a flashcards quiz", repo, generate_fn=_gen, projects_dir=proj,
                         advanced_intake=True, bad_input_floor=True)
    assert BAD_INPUT_FLOOR_MARKER not in _job_exam(plan)


def test_with_the_floor_OFF_the_ruler_is_not_imported_on_the_PLAN_path(tmp_path):
    """Structural absence on the planning path, checked rather than asserted.

    RENAMED (#1044 review N1). It used to be called ``..._is_never_even_IMPORTED``, which
    claimed more than it proves: it drives ``generate_plan`` only, and the seed-time
    fail-to-pass gate imports the ruler for a string constant regardless of the flags. The old
    name would have kept reading as a global guarantee long after it stopped being one — a
    test name is a claim surface like any other, and this one was making a claim its body never
    checked. See ``test_the_F2P_path_imports_the_ruler_but_runs_NO_floor_behaviour`` for the
    other half.

    Run in a SUBPROCESS because this test module imports the ruler at the top, so an in-process
    ``sys.modules`` check would be measuring the test file rather than the seam. The import
    lives inside :func:`_ensure_bad_input_floor`, which is only reachable through the two-knob
    gate, so with the floor off nothing of the ruler is loaded, let alone executed.
    """
    import inspect
    import subprocess

    proj, repo = _repo(tmp_path)
    probe = tmp_path / "probe.py"
    # The generator is COPIED IN as source rather than imported from this module: importing
    # this test file would drag in its own top-level import of the ruler, and the probe would
    # then be measuring the test harness instead of the seam. (First version did exactly that
    # and reported LOADED.)
    probe.write_text(
        "import json, pathlib, sys\n"
        f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
        "from shared.fleet.acceptance import generate_plan\n\n"
        + inspect.getsource(_gen)
        + "\n"
        f"generate_plan('a flashcards quiz', {repo!r}, generate_fn=_gen,\n"
        f"              projects_dir=pathlib.Path({str(proj)!r}),\n"
        "              advanced_intake=True)\n"
        "print('LOADED' if 'shared.fleet.bad_input_floor' in sys.modules else 'ABSENT')\n",
        encoding="utf-8",
    )
    out = subprocess.run([sys.executable, str(probe)], capture_output=True, text=True,
                         cwd=str(REPO_ROOT), timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.strip().endswith("ABSENT"), (
        "the bad-input ruler was imported with the floor OFF — the dormancy is a disabled "
        f"boolean, not structural absence. stdout={out.stdout!r}"
    )


# ---------------------------------------------------------------------------
# F2P interaction — the floor must not be able to DELETE grading (#1044 review F3a)
# ---------------------------------------------------------------------------


def test_floor_tests_are_excluded_from_the_F2P_VACUITY_set():
    """The fail-to-pass baseline treats a test that passes pre-implementation as vacuous, and a
    confirmed-vacuous test is a HARD finding that REFUSES the whole job exam.

    A floor test legitimately passes there: on a brownfield tree whose entry point already
    exists and already validates its input, it is doing exactly its job. Left in the set, a
    floor added to strengthen grading would instead leave the dispatch with NO job acceptance
    at all — and the better the pre-existing code, the more certainly it would happen.

    The exclusion is a prefix allowlist over machine-owned names only: a model-authored test
    that passes pre-implementation is still vacuous, and is still convicted.
    """
    from shared.fleet.oracle_qa import _discriminating_tests

    passed = [
        "test_bad_input_floor__app_quiz_engine__run_quiz",
        "test_scores_a_correct_answer",
        "test_bad_input_floor__app_cli__main",
    ]
    assert _discriminating_tests(passed) == ["test_scores_a_correct_answer"]


def test_a_PASSING_floor_test_does_not_make_the_whole_job_exam_vacuous(tmp_path):
    """Driven through the real :func:`fail_to_pass_baseline`, not just the filter helper.

    The unit test above passes even when the baseline never CALLS the filter, so on its own it
    is green against the bug it guards — the mutation proved exactly that. This drives the real
    function with an injected runner whose output shows a floor test PASSING on the skeleton,
    and requires a clean ``all-fail`` stamp with no finding: no refusal, grading intact.
    """
    from shared.fleet.oracle_qa import fail_to_pass_baseline

    blob = (
        "_qa_f2p_probe.py::test_bad_input_floor__app_quiz_engine__run_quiz PASSED   [ 50%]\n"
        "_qa_f2p_probe.py::test_scores_a_correct_answer FAILED                      [100%]\n"
        "1 failed, 1 passed in 0.10s\n"
    )
    stamp, findings = fail_to_pass_baseline(
        "def test_x():\n    pass\n", str(tmp_path),
        run=lambda *a, **k: (False, blob, ""),
    )
    assert stamp == "all-fail", (
        f"a passing bad-input floor test was classed {stamp!r} — a CONFIRMED-vacuous verdict "
        "REFUSES the job oracle, so the floor would delete grading for the whole dispatch"
    )
    assert findings == []


def test_a_model_authored_test_that_passes_pre_implementation_is_STILL_vacuous(tmp_path):
    """The exclusion must not become a hole. Only machine-owned reserved names are exempt; the
    vacuity check this rides on is still doing its original job."""
    from shared.fleet.oracle_qa import fail_to_pass_baseline

    blob = (
        "_qa_f2p_probe.py::test_scores_a_correct_answer PASSED                      [100%]\n"
        "1 passed in 0.10s\n"
    )
    stamp, findings = fail_to_pass_baseline(
        "def test_x():\n    pass\n", str(tmp_path),
        run=lambda *a, **k: (True, blob, ""),
    )
    assert stamp == "vacuous:test_scores_a_correct_answer"
    assert len(findings) == 1


def test_the_F2P_path_imports_the_ruler_but_runs_NO_floor_behaviour(tmp_path):
    """The narrowed N1 claim, locked where it was broken.

    The seed-time gate imports the ruler for its reserved prefix on every run, whichever way
    either flag is set — that is why the plan-path dormancy probe passed honestly and still
    missed this. So the honest claim is not "never imported", it is "nothing of the FLOOR
    runs", and this pins exactly that: the import happens, and it is INERT. No exam is read, no
    target is derived, no block is emitted, and a run with no floor tests in it produces the
    byte-identical verdict it produced before the exclusion existed.

    Written this way deliberately rather than as the absence assertion the round was scoped
    with: an absence assertion here cannot pass, because the import is real and was measured
    real. A test written to match a sentence rather than the substrate is how the sentence
    survives being wrong.
    """
    import subprocess

    from shared.fleet.oracle_qa import fail_to_pass_baseline

    # 1. The import really does happen here. Measured OUT OF PROCESS: this test module imports
    #    the ruler at the top, so an in-process `in sys.modules` assertion is true no matter
    #    what the seam does — vacuous, and it was written that way first.
    probe = tmp_path / "f2p_probe.py"
    probe.write_text(
        "import sys, tempfile\n"
        f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
        "from shared.fleet.oracle_qa import fail_to_pass_baseline\n"
        "with tempfile.TemporaryDirectory() as td:\n"
        "    fail_to_pass_baseline('def test_x():\\n    pass\\n', td,\n"
        "                          run=lambda *a, **k: (False, '1 failed in 0.1s\\n', ''))\n"
        "print('LOADED' if 'shared.fleet.bad_input_floor' in sys.modules else 'ABSENT')\n",
        encoding="utf-8",
    )
    out = subprocess.run([sys.executable, str(probe)], capture_output=True, text=True,
                         cwd=str(REPO_ROOT), timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.strip().endswith("LOADED"), (
        "the ruler is no longer imported on the F2P path — good, but the retracted docstrings "
        "at acceptance.py::_ensure_bad_input_floor and the entrypoint config field now UNDERclaim. "
        "Widen them deliberately rather than leaving the record wrong in the other direction."
    )

    # 2. And that import is INERT: no floor test in the run, so the verdict is what it always
    #    was, from exactly one runner invocation.
    calls: list = []

    def recording_run(*args, **kwargs):
        calls.append(args)
        return (False, "_qa_f2p_probe.py::test_a FAILED  [100%]\n1 failed in 0.10s\n", "")

    stamp, findings = fail_to_pass_baseline(
        "def test_x():\n    pass\n", str(tmp_path), run=recording_run)
    assert (stamp, findings) == ("all-fail", [])
    assert len(calls) == 1, "the exclusion added a second run or suppressed the only one"


def test_the_reserved_prefix_is_pinned_to_the_names_actually_EMITTED():
    """Two modules must agree on one literal: the emitter builds the names, ``oracle_qa``
    excludes them. A drift in either direction is silent — a widened emitter name would be
    convicted as vacuous, a narrowed exclusion would stop protecting. So the exclusion is
    checked against a REAL emitted name, not against the constant it came from."""
    from shared.fleet.bad_input_floor import FLOOR_TEST_PREFIX
    from shared.fleet.oracle_qa import _discriminating_tests

    emitted = [t.test_name for t in bad_input_floor_targets(_HAPPY_PATH_EXAM)]
    assert emitted, "the harness stopped producing a target"
    assert all(name.startswith(FLOOR_TEST_PREFIX) for name in emitted)
    assert _discriminating_tests(emitted) == []


@pytest.mark.parametrize("code", ["", "not python at all ((("])
def test_generate_plan_survives_an_unusable_exam(code, tmp_path):
    """Fail-soft at the seam: an exam the ruler cannot floor leaves the plan runnable."""
    proj, repo = _repo(tmp_path)

    def gen(prompt: str) -> str:
        if "JOB-LEVEL ACCEPTANCE" in prompt:
            return code
        return _gen(prompt)

    plan = generate_plan("a flashcards quiz", repo, generate_fn=gen, projects_dir=proj,
                         advanced_intake=True, bad_input_floor=True)
    assert plan.ok
