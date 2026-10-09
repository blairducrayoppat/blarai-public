"""#821 (QUALITY-3) — oracle-QA locks.

Every taxonomy defect class is a fixture (the ill-posed strategy B1n2, the invented
contract + interactive-IO B4, the ``sys.listdir`` no-raise smoke B6), plus the
FAIL-TO-PASS vacuous case, the traceability unmapped-criterion case, the no-raise
adequacy-floor case, the regeneration accounting, and the evidence-stamp shape. The
model calls are faked throughout, so the taxonomy locks run model-free.

SUBPROCESSES ARE NOT ALL FAKED, and the ``#1200`` section at the foot of this file is why.
Faking the runner everywhere left ``_qa_env`` and ``_pytest_cmd`` — the seam the live path
crosses — completely unexercised, and BOTH were broken on this host for at least two banked
nights while every test here stayed green: uv could not see its managed interpreter through
the app-data redirect, and the execution command's ``-q``/``-v`` cancelled to dot output
that the per-test parser reads as "nothing passed". The fast locks there assert the seam's
shape; the ``@pytest.mark.slow`` ones drive the REAL ``uv run``, because a probe that
finishes in under a second is not running the runner production uses.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import time
from pathlib import Path

import pytest

from shared.fleet import acceptance as acc
from shared.fleet import clarify as clr
from shared.fleet import grade_env
from shared.fleet import oracle_mutation as mutation
from shared.fleet import oracle_qa as oq
from shared.fleet import swap_ops as so
from shared.fleet.acceptance import (
    JOB_ORACLE_PATH_PYTHON,
    AcceptanceCriterion,
    AcceptanceSpec,
)
from shared.fleet.dispatch import FleetDispatchConfig

# ---------------------------------------------------------------------------
# Oracle fixtures — the taxonomy, one shape per defect class
# ---------------------------------------------------------------------------

#: A CLEAN python job oracle: bounded strategy, first-party assertion, no invented API.
_CLEAN = (
    "from expense import add_expense, total\n\n"
    "def test_total_sums_expenses():\n"
    "    add_expense(3)\n"
    "    add_expense(4)\n"
    "    assert total() == 7\n"
)

#: B1n2 — an ILL-POSED strategy: unbounded st.floats() feeds spec-invalid inputs (0.0).
_ILLPOSED_STRATEGY = (
    "from hypothesis import given, strategies as st\n"
    "from expense import add_expense, total\n\n"
    "@given(st.floats())\n"
    "def test_total(amount):\n"
    "    add_expense(amount)\n"
    "    assert total() == amount\n"
)

#: A WELL-POSED property test: bounded floats (min/max present) — must NOT be flagged.
_BOUNDED_STRATEGY = (
    "from hypothesis import given, strategies as st\n"
    "from expense import add_expense, total\n\n"
    "@given(st.floats(min_value=0.01, max_value=1000.0))\n"
    "def test_total(amount):\n"
    "    add_expense(amount)\n"
    "    assert total() >= amount\n"
)

#: B4 — an INVENTED contract: check_answer is asserted but the plan never declared it.
_INVENTED_CONTRACT = (
    "from flashcards import check_answer\n\n"
    "def test_quiz_correct_answer():\n"
    "    assert check_answer('cat', 'cat') == 'correct'\n"
)

#: Direct interactive I/O in the oracle — input() raises under pytest (the B4 class).
_INTERACTIVE_IO = (
    "from flashcards import quiz\n\n"
    "def test_quiz_prompt():\n"
    "    answer = input('your answer: ')\n"
    "    assert quiz(answer) is not None\n"
)

#: B6 — a valid smoke oracle: run_cli() is a NO-RAISE call on a first-party symbol; the
#: adequacy floor MUST accept it (the mid-build amendment — not assertion-only).
_NORAISE_SMOKE = (
    "from inventory import run_cli, add_item\n\n"
    "def test_launches():\n"
    "    run_cli()\n"
    "def test_add():\n"
    "    add_item('widget', 5)\n"
)

#: Vacuous: imports first-party but no test exercises it (asserts only a constant).
_VACUOUS_ASSERT = (
    "from expense import add_expense\n\n"
    "def test_math():\n"
    "    assert 2 + 2 == 4\n"
)

#: Vacuous: imports NOTHING first-party.
_NO_FIRST_PARTY = "def test_always():\n    assert True\n"

#: Imports a module no plan task declares (import-contract miss).
_UNDECLARED_MODULE = (
    "from totally_unplanned import widget\n\n"
    "def test_widget():\n"
    "    assert widget() == 1\n"
)


def _crit(cid: str, text: str, tier: str = "behavior") -> AcceptanceCriterion:
    return AcceptanceCriterion(id=cid, text=text, tier=tier)


def _spec(*criteria: AcceptanceCriterion, language_hint: str = "python") -> AcceptanceSpec:
    return AcceptanceSpec(
        goal="an expense tracker",
        criteria=tuple(criteria),
        build_plan={"surface": "command-line", "language_hint": language_hint,
                    "complexity": "simple", "components": []},
    )


def _tasks(*, exports=("add_expense(x)", "total()"), creates=("expense.py",)) -> list[dict]:
    return [
        {"repo": "X", "task": "core", "prompt": "build core",
         "contract": {"creates": list(creates), "exports": list(exports), "notes": ""}},
        {"repo": "X", "task": "report", "prompt": "build report"},
    ]


# ---------------------------------------------------------------------------
# Static stages — each taxonomy class flagged (and each conservative negative)
# ---------------------------------------------------------------------------


def test_scan_strategies_flags_unbounded_b1n2():
    findings = oq.scan_strategies(_ILLPOSED_STRATEGY)
    assert [f.cls for f in findings] == [oq.CLASS_STRATEGY]
    assert findings[0].subject == "floats"
    assert findings[0].hard  # ill-posed strategy convicts valid work → HARD


def test_scan_strategies_passes_bounded():
    assert oq.scan_strategies(_BOUNDED_STRATEGY) == []
    # A non-property oracle is never scanned.
    assert oq.scan_strategies(_CLEAN) == []


def test_scan_interactive_io_flags_input():
    findings = oq.scan_interactive_io(_INTERACTIVE_IO)
    assert [f.cls for f in findings] == [oq.CLASS_INTERACTIVE_IO]
    assert findings[0].hard
    assert oq.scan_interactive_io(_CLEAN) == []


def test_scan_interactive_io_flags_stdin_read():
    code = "import sys\nfrom app import go\n\ndef test_x():\n    data = sys.stdin.read()\n    assert go(data)\n"
    findings = oq.scan_interactive_io(code)
    assert any(f.cls == oq.CLASS_INTERACTIVE_IO for f in findings)


def test_scan_invented_contracts_flags_undeclared_b4():
    findings = oq.scan_invented_contracts(_INVENTED_CONTRACT, {"add_card", "quiz"})
    assert [f.cls for f in findings] == [oq.CLASS_INVENTED_CONTRACT]
    assert findings[0].subject == "check_answer"


def test_scan_invented_contracts_conservative():
    # Declared export → not flagged. Empty contract → check disabled (no false invention).
    assert oq.scan_invented_contracts(_INVENTED_CONTRACT, {"check_answer"}) == []
    assert oq.scan_invented_contracts(_INVENTED_CONTRACT, set()) == []
    # A local helper / stdlib name is never flagged (only `from <first-party> import`).
    assert oq.scan_invented_contracts(_CLEAN, {"add_expense", "total"}) == []


# ---------------------------------------------------------------------------
# #967 D1 — a DECLARED SUBMODULE import is not an invented contract
# ---------------------------------------------------------------------------

#: The live shape from dispatch run 20260719-002208-bd: the seeded oracle imports the
#: plan's declared SUBMODULES (flashcard_app/card_manager.py &c), not functions. Judged
#: against the function-export set alone, every one of them read as an invented contract
#: — and because invented_contract outranks a coverage gap, both regeneration rounds went
#: to phantoms while oracle_coverage sat at 0/6. The run's own import probe resolved all
#: four names against the built package ("unresolved": []), proving them legitimate.
_SUBMODULE_IMPORT = (
    "from flashcard_app import card_manager, quiz_engine, score_tracker, main\n\n"
    "def test_add_card():\n"
    "    card_manager.add_card('cat', 'feline')\n"
    "    assert card_manager is not None\n"
)

#: That run's plan: five created modules, none of which is an exported NAME.
_SUBMODULE_CREATES = (
    "flashcard_app/card_manager.py", "flashcard_app/quiz_engine.py",
    "flashcard_app/score_tracker.py", "flashcard_app/main.py",
    "flashcard_app/data_storage.py",
)
_SUBMODULE_EXPORTS = ("add_card(front, back)", "quiz_user(f)", "track_score(n)", "run_app()")


def _submodule_symbols() -> tuple[set[str], set[str]]:
    return oq._declared_symbols(
        _tasks(exports=_SUBMODULE_EXPORTS, creates=_SUBMODULE_CREATES)
    )


def test_scan_invented_contracts_accepts_declared_submodules_967():
    exports, modules = _submodule_symbols()
    assert "card_manager" not in exports and "card_manager" in modules
    # The measured defect: judged against exports alone, every submodule import convicts.
    without = oq.scan_invented_contracts(_SUBMODULE_IMPORT, exports)
    assert {f.subject for f in without} == {
        "card_manager", "quiz_engine", "score_tracker", "main"}
    # Threading the plan's declared submodules through resolves all four as legitimate.
    assert oq.scan_invented_contracts(_SUBMODULE_IMPORT, exports, modules) == []


def test_scan_invented_contracts_still_flags_invention_when_submodules_declared():
    # The toggle-off half (CLAUDE.md principle 12): with the WIDENED input the check must
    # still BLOCK a genuine invention, else "the fix works" is indistinguishable from
    # "the check now accepts everything".
    exports, modules = _submodule_symbols()
    code = (
        "from flashcard_app import card_manager, check_answer\n\n"
        "def test_quiz():\n"
        "    assert check_answer('cat', 'cat') == 'correct'\n"
    )
    findings = oq.scan_invented_contracts(code, exports, modules)
    # The declared submodule passes in the SAME import statement the invention rides in.
    assert [f.subject for f in findings] == ["check_answer"]
    assert findings[0].cls == oq.CLASS_INVENTED_CONTRACT
    # B4's original invention is untouched by the widening.
    assert [f.subject for f in oq.scan_invented_contracts(
        _INVENTED_CONTRACT, {"add_card", "quiz"}, modules)] == ["check_answer"]
    # Only the two DECLARED sets license a name — an unknown one is still an invention
    # even when a module set is supplied.
    assert oq.scan_invented_contracts(
        _INVENTED_CONTRACT, {"add_card"}, {"flashcards"}) != []
    # The fail-soft floor is unmoved: no declared exports → no judgement, modules or not.
    assert oq.scan_invented_contracts(_INVENTED_CONTRACT, set(), modules) == []


def test_static_findings_submodule_fix_touches_only_the_invented_contract_class():
    # The accounting pin: threading `modules` through changes the invented-contract class
    # and NOTHING else — the other static classes are class-for-class identical.
    exports, modules = _submodule_symbols()
    before = oq._static_findings(_SUBMODULE_IMPORT, exports, set())
    after = oq._static_findings(_SUBMODULE_IMPORT, exports, modules)
    assert sorted(f.cls for f in before if f.cls != oq.CLASS_INVENTED_CONTRACT) == \
        sorted(f.cls for f in after if f.cls != oq.CLASS_INVENTED_CONTRACT)
    assert [f.cls for f in after] == []  # the live shape is now statically clean
    # The module surface itself was always declared — this was never an import-contract miss.
    assert oq.check_import_contract(_SUBMODULE_IMPORT, modules) == []


# ---------------------------------------------------------------------------
# #826 — the INVENTED-RETURN contract (B4n2's deep half): a magic return STRING
# the spec never names, over the import-name invention above
# ---------------------------------------------------------------------------

#: B4n2 return-half: check_answer IS a declared export (no import invention), but the
#: oracle demands it return the magic string 'correct' the requirements never state.
_INVENTED_RETURN_ONLY = (
    "from flashcards import check_answer\n\n"
    "def test_quiz():\n"
    "    assert check_answer('cat') == 'correct'\n"
)


def test_scan_invented_return_flags_magic_string_b4n2():
    findings = oq.scan_invented_return_contracts(_INVENTED_RETURN_ONLY, "a flashcards quiz app")
    assert [f.cls for f in findings] == [oq.CLASS_INVENTED_RETURN]
    assert findings[0].subject == "check_answer"
    assert not findings[0].hard  # SOFT — a heuristic string match never REFUSES an oracle


def test_scan_invented_return_conservative():
    # Grounded: the spec names the value → a legitimate assertion, not flagged.
    assert oq.scan_invented_return_contracts(
        _INVENTED_RETURN_ONLY, "shows correct or wrong for each card") == []
    # Empty corpus disables the check (no spec to judge against → never a false invention).
    assert oq.scan_invented_return_contracts(_INVENTED_RETURN_ONLY, "") == []
    # A numeric return is never flagged (spec-derivable — no "5" needed in prose).
    num = "from calc import add\n\ndef test_x():\n    assert add(2, 3) == 5\n"
    assert oq.scan_invented_return_contracts(num, "a calculator") == []
    # A trivial (single-char) string is skipped.
    triv = "from m import f\n\ndef test_x():\n    assert f() == 'x'\n"
    assert oq.scan_invented_return_contracts(triv, "a thing") == []
    # The clean oracle asserts a NUMBER (total() == 7) → never flagged.
    assert oq.scan_invented_return_contracts(_CLEAN, "an expense tracker") == []


# ---------------------------------------------------------------------------
# #1043 — the corpus/author alignment. The oracle is authored from the PLANNING SEED
# (goal + the operator's clarified requirements, #819/#1032) while ``spec.goal`` stays
# the CLEAN goal by design. Judging the oracle against the narrower spec text convicted
# it for asserting exactly the value the operator supplied.
# ---------------------------------------------------------------------------

#: The operator's own words, and the oracle that legitimately encodes them. Nothing here
#: is invented — "Saved" reaches the oracle only because the operator asked for it.
_OPERATOR_ANSWER = "show the word Saved after each entry"
_OPERATOR_GROUNDED_ORACLE = (
    "from store import add_item\n\n"
    "def test_adding_an_entry_confirms():\n"
    "    assert add_item('milk') == 'Saved'\n"
)


def _real_operator_answers(*clarifications: dict) -> tuple[str, ...]:
    """Build the grounding input the way PRODUCTION does — through the REAL composer and
    its REAL extractor, never a hand-written approximation.

    Load-bearing (#1043 review F3): the first draft of these locks hand-wrote the
    authored-from string and even hand-approximated the house header, so the boilerplate-
    poisoning defect sailed through a suite written to catch exactly that class. A fixture
    that merely RESEMBLES the real string is how such a defect survives its own test.
    """
    return clr.operator_answers_from_block(clr.compose_requirements_block(list(clarifications)))


def test_spec_corpus_grounds_on_the_operator_answers():
    """The corpus spans every channel the operator's words arrive through."""
    spec = _spec(_crit("c2", "adding an entry shows it in the list"))
    # The spec alone does NOT contain the operator's word — this is the trap.
    assert "saved" not in oq._spec_corpus(spec)
    # The operator's answer, routed through the real composer, carries it in.
    corpus = oq._spec_corpus(spec, _real_operator_answers(
        {"question": "confirm?", "answer": _OPERATOR_ANSWER, "assumed": False}))
    assert "saved" in corpus
    assert "an expense tracker" in corpus       # the goal is still there
    assert "adding an entry" in corpus          # so are the criteria


def test_house_boilerplate_never_enters_the_grounding_corpus():
    """#1043 review F1 — the reachable blocker the first build shipped.

    ``authored_from`` used to be the RENDERED requirements block, whose fixed header
    ("The person clarified these requirements — build to them:") entered the corpus on
    EVERY clarified dispatch. That granted authority to words no operator uttered, so an
    oracle asserting ``classify(...) == 'person'`` was excused — a genuinely-bad oracle
    silently forgiven, violating this slice's own "zero effect on a bad oracle" bar.

    Grounding is authority; only the operator may confer it. Built through the real
    composer so a header reword cannot quietly re-open the hole.
    """
    answers = _real_operator_answers(
        {"question": "store phone?", "answer": "yes, store a phone number with each contact",
         "assumed": False})
    spec = _spec(_crit("c2", "shows saved contacts"))
    corpus = oq._spec_corpus(spec, answers)

    for word in ("person", "build", "clarified", "requirements", "them", "these"):
        assert word not in corpus, (
            f"house boilerplate {word!r} reached the grounding corpus — the judge now "
            "excuses an oracle asserting our own prose back at us"
        )

    # The concrete conviction the poisoning excused. 'person' is an ordinary return value.
    invented = ("from classify import classify\n\n"
                "def test_x():\n    assert classify('Bob Smith') == 'person'\n")
    assert [f.cls for f in oq.scan_invented_return_contracts(invented, corpus)] == [
        oq.CLASS_INVENTED_RETURN
    ]
    # POSITIVE CONTROL: the operator's OWN word still grounds, so the exclusion above is
    # about provenance and not about the corpus being empty.
    grounded = ("from store import add_item\n\n"
                "def test_y():\n    assert add_item('x') == 'phone'\n")
    assert oq.scan_invented_return_contracts(grounded, corpus) == []


def test_model_written_criteria_ground_because_the_coder_is_given_them():
    """The admission rule is "requirement content the CODER was also given", NOT "the
    operator wrote it" — and this lock exists because the docstring once claimed the latter.

    Criteria are written by the 14B and they DO ground the scanner. That is correct rather
    than a hole: :func:`compile_prompts` puts each criterion's text/check verbatim into the
    coder's task prompt, so a criterion naming a value genuinely instructed the coder to
    produce it and an oracle asserting it blindsides nobody. The clarify question fails
    exactly this test — it never reaches the coder — which is why excluding it is right
    while excluding criteria would be wrong.

    If a future change stops compiling criteria into the coder's prompt, the justification
    for admitting them evaporates. This asserts that premise instead of trusting the prose.
    """
    crit = _crit("c2", "each saved row is marked Ledgered in the list")
    spec = _spec(crit)
    assert "ledgered" in oq._spec_corpus(spec)

    oracle = ("from ledger import save_row\n\n"
              "def test_marks():\n    assert save_row({}) == 'Ledgered'\n")
    assert oq.scan_invented_return_contracts(oracle, oq._spec_corpus(spec)) == []

    # The premise, asserted against the REAL compiler: the coder IS given that text.
    compiled = acc.compile_prompts(
        [{"repo": "X", "task": "core", "prompt": "build core"},
         {"repo": "X", "task": "report", "prompt": "build report"}],
        spec,
    )
    assert any("Ledgered" in str(t.get("prompt", "")) for t in compiled), (
        "criteria no longer reach the coder's prompts — the reason model-written criteria "
        "may ground the invented-return scanner has gone away, so the admission rule in "
        "_spec_corpus's docstring is now false and the exclusion must be revisited."
    )


def test_assumed_answer_grounds_but_its_tag_does_not():
    """The "just decide for me" path renders an ``(assumed)`` marker. The ANSWER is a
    deterministic in-repo default (legitimate grounding); the MARKER is house prose."""
    answers = _real_operator_answers(
        {"question": "where?", "answer": "save to a local file", "assumed": True})
    corpus = oq._spec_corpus(_spec(_crit("c2", "keeps data")), answers)
    assert "local file" in corpus
    assert "assumed" not in corpus


def test_spec_corpus_unions_recorded_clarification_ANSWERS():
    """A spec carrying the #819 record grounds on the ANSWER — and the record rides
    ``to_dict``/``from_dict``, so a RECONSTRUCTED spec keeps that grounding. The model's
    QUESTION text is excluded (see the laundering lock below)."""
    spec = AcceptanceSpec(
        goal="a todo app",
        criteria=(_crit("c2", "adding an entry shows it in the list"),),
        clarifications=({"question": "confirm each entry?", "answer": _OPERATOR_ANSWER,
                         "assumed": False},),
    )
    corpus = oq._spec_corpus(AcceptanceSpec.from_dict(spec.to_dict()))
    assert "saved" in corpus                  # the operator's ANSWER grounds
    assert "confirm each entry" not in corpus  # the model's QUESTION does not


def test_model_authored_question_cannot_launder_an_invention():
    """Grounding IS authority, so only human/deterministic text may confer it.

    The clarify model writes the QUESTION, and its questions routinely name a candidate
    value. If the question entered the corpus, the model could excuse its own invented
    return contract — here excusing an assertion the operator's answer explicitly REFUSED.
    (Found in independent review of the first #1043 build, which admitted the question.)
    """
    spec = AcceptanceSpec(
        goal="a todo app",
        criteria=(_crit("c2", "adding an entry shows it in the list"),),
        clarifications=({"question": "Should add_item return the string Saved?",
                         "answer": "no, return None", "assumed": False},),
    )
    corpus = oq._spec_corpus(spec)
    assert "saved" not in corpus, "the model's question text leaked into the grounding corpus"
    findings = oq.scan_invented_return_contracts(_OPERATOR_GROUNDED_ORACLE, corpus)
    assert [f.cls for f in findings] == [oq.CLASS_INVENTED_RETURN], (
        "an assertion the operator REFUSED was excused — the model laundered its own "
        "invention through its own question text"
    )

    # POSITIVE CONTROL: the same oracle IS excused when the OPERATOR's answer names the
    # value. Without this arm the assertion above could pass on a scanner that always fires.
    said_yes = AcceptanceSpec(
        goal="a todo app",
        criteria=(_crit("c2", "adding an entry shows it in the list"),),
        clarifications=({"question": "Should add_item return the string Saved?",
                         "answer": "yes, return Saved", "assumed": False},),
    )
    assert oq.scan_invented_return_contracts(
        _OPERATOR_GROUNDED_ORACLE, oq._spec_corpus(said_yes)) == []


def test_spec_corpus_fail_soft_unchanged():
    """No operator answers and no clarifications → the goal alone, exactly as before;
    nothing at all → '' (which DISABLES the scanner rather than inventing a finding)."""
    assert oq._spec_corpus(AcceptanceSpec(goal="a todo app")) == "a todo app"
    assert oq._spec_corpus(AcceptanceSpec(goal="")) == ""
    assert oq._spec_corpus(AcceptanceSpec(goal=""), ()) == ""
    assert oq._spec_corpus(AcceptanceSpec(goal="a todo app"), None) == "a todo app"


def test_validate_does_not_convict_an_operator_supplied_return_value():
    """#1043, with its toggle-off: the SAME oracle + spec is RED without the alignment
    and GREEN with it, so the lock demonstrably sees the real defect."""
    crits = [_crit("c2", "adding an entry shows it in the list")]
    spec = _spec(*crits)
    tasks = _tasks(exports=("add_item(text)",), creates=("store.py",))
    answers = _real_operator_answers(
        {"question": "confirm?", "answer": _OPERATOR_ANSWER, "assumed": False})
    common = dict(
        generate_fn=lambda p: "",  # any regeneration attempt yields nothing usable
        structured_generate_fn=_full_cover_structured(
            {"c2": ["test_adding_an_entry_confirms"]}),
    )

    # TOGGLE OFF (the pre-#1043 behaviour — judge against the spec alone): RED.
    off = oq.validate_authored_oracle(
        _OPERATOR_GROUNDED_ORACLE, "python", spec, tasks, **common)
    assert off.counts[oq.CLASS_INVENTED_RETURN] == 1, (
        "the toggle-off arm must reproduce the defect — a lock whose negative arm is "
        "already clean proves nothing"
    )

    # ALIGNED: the oracle is judged against what the operator said → clean.
    on = oq.validate_authored_oracle(
        _OPERATOR_GROUNDED_ORACLE, "python", spec, tasks, operator_answers=answers, **common)
    assert on.counts[oq.CLASS_INVENTED_RETURN] == 0
    assert on.verdict == "seed"
    assert on.regen_rounds == 0          # nothing to regenerate → no wasted GPU round
    assert "Saved" in on.oracle_code     # the operator's value SURVIVES into the exam


def test_alignment_does_not_blind_the_scanner_to_a_real_invention():
    """The alignment widens grounding to the operator's words — and NOT one word more.
    A value neither the spec NOR the operator's answers name is still convicted.

    Built through the real composer: an earlier draft hand-wrote this fixture, including a
    hand-approximated "the person clarified" phrase, and that near-miss is precisely why it
    failed to notice the real header was poisoning the corpus (#1043 review F3).
    """
    crits = [_crit("c2", "quizzes the user on flashcards")]
    result = oq.validate_authored_oracle(
        _INVENTED_RETURN_ONLY, "python", _spec(*crits),
        _tasks(exports=("check_answer(word)",), creates=("flashcards.py",)),
        generate_fn=lambda p: "",
        structured_generate_fn=_full_cover_structured({"c2": ["test_quiz"]}),
        operator_answers=_real_operator_answers(
            {"question": "where?", "answer": "use it on my phone", "assumed": False}),
    )
    assert result.counts[oq.CLASS_INVENTED_RETURN] == 1


def test_check_import_contract_flags_undeclared_module():
    findings = oq.check_import_contract(_UNDECLARED_MODULE, {"expense"})
    assert [f.cls for f in findings] == [oq.CLASS_IMPORT_CONTRACT]
    assert findings[0].subject == "totally_unplanned"
    # A declared module (by top package) passes; empty contract disables the check.
    assert oq.check_import_contract(_CLEAN, {"expense"}) == []
    assert oq.check_import_contract(_UNDECLARED_MODULE, set()) == []


def test_check_syntax_flags_hypothesis_kwarg_and_syntaxerror():
    bad_kwarg = (
        "from hypothesis import given, strategies as st\n"
        "from app import f\n\n"
        "@given(st.text(min_length=1))\n"
        "def test_f(s):\n    assert f(s) is not None\n"
    )
    finding = oq.check_syntax(bad_kwarg)
    assert finding is not None and finding.cls == oq.CLASS_COLLECTABILITY
    syn = oq.check_syntax("def broken(:\n")
    assert syn is not None and syn.cls == oq.CLASS_COLLECTABILITY
    assert oq.check_syntax(_CLEAN) is None


# ---------------------------------------------------------------------------
# Adequacy floor — the no-raise rule (the mid-build correctness amendment)
# ---------------------------------------------------------------------------


def test_adequacy_floor_passes_noraise_call_b6():
    # B6's run_cli() smoke test is a no-raise call on a first-party symbol → floor PASSES.
    assert oq.adequacy_floor(_NORAISE_SMOKE) is None


def test_adequacy_floor_passes_assertion():
    assert oq.adequacy_floor(_CLEAN) is None


def test_adequacy_floor_flags_vacuous_assert():
    finding = oq.adequacy_floor(_VACUOUS_ASSERT)
    assert finding is not None and finding.cls == oq.CLASS_ADEQUACY_FLOOR
    assert finding.hard


def test_adequacy_floor_flags_no_first_party_import():
    finding = oq.adequacy_floor(_NO_FIRST_PARTY)
    assert finding is not None and finding.cls == oq.CLASS_ADEQUACY_FLOOR


# ---------------------------------------------------------------------------
# FAIL-TO-PASS baseline — the vacuous-pass gate (faked subprocess)
# ---------------------------------------------------------------------------


def _fake_run(out: str = "", err: str = "", ok: bool = False):
    def run(cmd, cwd, timeout_s, env):
        return (ok, out, err)
    return run


def test_f2p_flags_vacuous_pass(tmp_path):
    run = _fake_run(out="_qa_f2p_probe.py::test_always PASSED\n1 passed in 0.01s")
    stamp, findings = oq.fail_to_pass_baseline(_NO_FIRST_PARTY, str(tmp_path), run=run)
    assert stamp == "vacuous:test_always"
    assert [f.cls for f in findings] == [oq.CLASS_F2P_VACUOUS]
    assert findings[0].hard


def test_f2p_all_fail_is_clean(tmp_path):
    run = _fake_run(out="_qa_f2p_probe.py::test_total FAILED\n1 failed in 0.02s")
    stamp, findings = oq.fail_to_pass_baseline(_CLEAN, str(tmp_path), run=run)
    assert stamp == "all-fail" and findings == []


def test_f2p_collection_error_is_clean(tmp_path):
    # Imports miss on the unimplemented skeleton → collection error → nothing passed.
    run = _fake_run(out="ERROR _qa_f2p_probe.py\nerrors during collection\n1 error in 0.03s")
    stamp, findings = oq.fail_to_pass_baseline(_CLEAN, str(tmp_path), run=run)
    assert stamp == "all-fail" and findings == []


def test_f2p_machinery_miss_is_not_run(tmp_path):
    # Empty output (uv missing / crash) → honest not-run, NEVER a false clean.
    run = _fake_run(out="", err="")
    stamp, findings = oq.fail_to_pass_baseline(_CLEAN, str(tmp_path), run=run)
    assert stamp == "not-run" and findings == []


def test_f2p_timeout_is_not_run(tmp_path):
    run = _fake_run(out="", err="TIMEOUT")
    stamp, findings = oq.fail_to_pass_baseline(_CLEAN, str(tmp_path), run=run)
    assert stamp == "not-run"


def test_f2p_missing_dir_is_not_run():
    stamp, findings = oq.fail_to_pass_baseline(_CLEAN, "/no/such/dir", run=_fake_run())
    assert stamp == "not-run"


def test_passed_tests_parser():
    out = "t/x.py::test_a PASSED\nt/x.py::test_b FAILED\ntest_c PASSED\nother line\n"
    assert oq._passed_tests(out) == ["test_a", "test_c"]


# ---------------------------------------------------------------------------
# Collectability confirmation — advisory, never a false park
# ---------------------------------------------------------------------------


def test_confirm_collectable_confirmed():
    run = _fake_run(out="collected 2 items", ok=True)
    stamp, finding = oq.confirm_collectable(_CLEAN, run=run)
    assert stamp == "confirmed" and finding is None


# Both fixtures below carry the summary line REAL pytest emits on a collection failure
# ("no tests collected, 1 error in 1.34s", measured 2026-07-30). Without it these asserted
# against output pytest cannot produce, and #1200's not-run detection — which asks whether
# the runner completed at all — correctly declines to read a bare `E ...` line as a verdict.


def test_confirm_collectable_structural_defect_flags():
    run = _fake_run(out="E   hypothesis.errors.InvalidArgument: min_value > max_value\n"
                        "no tests collected, 1 error in 1.34s")
    stamp, finding = oq.confirm_collectable(_ILLPOSED_STRATEGY, run=run)
    assert stamp == "unconfirmed" and finding is not None
    assert finding.cls == oq.CLASS_COLLECTABILITY


def test_confirm_collectable_import_miss_is_no_finding():
    # A stub-synthesis miss must NEVER false-park a valid oracle.
    run = _fake_run(out="E   ModuleNotFoundError: No module named 'expense'\n"
                        "no tests collected, 1 error in 0.42s")
    stamp, finding = oq.confirm_collectable(_CLEAN, run=run)
    assert stamp == "unconfirmed" and finding is None


# ---------------------------------------------------------------------------
# Traceability matrix — grammar schema + AST verification
# ---------------------------------------------------------------------------


def test_coverage_map_schema_prefills_keys():
    schema = oq.coverage_map_emission_json_schema(["c2", "c3", "c2"])
    assert schema["required"] == ["c2", "c3"]  # de-duped, order-preserving
    assert set(schema["properties"]) == {"c2", "c3"}
    assert schema["additionalProperties"] is False


def test_verify_traceability_covered_and_uncovered():
    crits = [_crit("c2", "sums expenses"), _crit("c3", "reports total", "smoke")]
    cov_map = {"c2": ["test_total_sums_expenses"], "c3": ["test_total_sums_expenses"]}
    covered, uncovered, findings = oq.verify_traceability(_CLEAN, cov_map, crits)
    assert set(covered) == {"c2", "c3"} and uncovered == []
    assert findings == []


def test_verify_traceability_unmapped_criterion():
    # c7 is ENTIRELY absent from the map (the r2adequacy measured hole) → uncovered.
    crits = [_crit("c2", "sums expenses"), _crit("c7", "no crash on empty", "smoke")]
    cov_map = {"c2": ["test_total_sums_expenses"]}
    covered, uncovered, findings = oq.verify_traceability(_CLEAN, cov_map, crits)
    assert covered == ["c2"] and uncovered == ["c7"]
    assert [f.cls for f in findings] == [oq.CLASS_TRACEABILITY]
    assert findings[0].subject == "c7"


def test_verify_traceability_false_declaration_is_uncovered():
    # c2 maps to a test that does NOT exist / does not exercise a first-party symbol.
    crits = [_crit("c2", "sums expenses")]
    covered, uncovered, _ = oq.verify_traceability(
        _CLEAN, {"c2": ["test_nonexistent"]}, crits)
    assert covered == [] and uncovered == ["c2"]
    # A test that touches nothing first-party is a false declaration too.
    vac = "from expense import add_expense\n\ndef test_v():\n    assert 1 == 1\n"
    covered2, uncovered2, _ = oq.verify_traceability(vac, {"c2": ["test_v"]}, crits)
    assert uncovered2 == ["c2"]


def test_verify_traceability_subject_binding_when_provided():
    # With #826's subject map, the named test must reference the criterion's OWN subject.
    crits = [_crit("c2", "sums expenses")]
    code = ("from expense import add_expense, total\n\n"
            "def test_only_add():\n    add_expense(1)\n    assert add_expense is not None\n")
    # test_only_add references add_expense but NOT `total` — c2's subject is {total}.
    covered, uncovered, _ = oq.verify_traceability(
        code, {"c2": ["test_only_add"]}, crits, criterion_subjects={"c2": {"total"}})
    assert uncovered == ["c2"]


def test_request_coverage_map_grammar_first_then_freetext():
    crits = [_crit("c2", "sums expenses")]

    def structured(prompt, schema):
        assert "c2" in schema  # the schema pre-fills the key
        return json.dumps({"c2": ["test_total_sums_expenses"]})

    m = oq.request_coverage_map(_CLEAN, crits, generate_fn=lambda p: "", structured_generate_fn=structured)
    assert m == {"c2": ["test_total_sums_expenses"]}

    # No grammar hook → free-text fallback parsed.
    m2 = oq.request_coverage_map(
        _CLEAN, crits, generate_fn=lambda p: 'here: {"c2": ["test_total_sums_expenses"]} done')
    assert m2 == {"c2": ["test_total_sums_expenses"]}

    # Unusable emission → None (caller stamps coverage unknown, never invents a verdict).
    m3 = oq.request_coverage_map(_CLEAN, crits, generate_fn=lambda p: "no json here")
    assert m3 is None


# ---------------------------------------------------------------------------
# #1003 order-independence probe — the coverage map is the one place two
# candidate lists are co-presented for a matching judgement (criteria in spec
# insertion order, test names in AST source order), with no order control on
# either. These probes run the SAME deterministic pipeline twice — source
# order, then BOTH lists reversed — and assert an identical covered-id set,
# converting "we assume order doesn't matter" into a gate-enforced claim.
# ---------------------------------------------------------------------------

#: Three order-probe tests whose SOURCE ORDER (which derives the prompt's
#: test-name list) can be reversed wholesale; each body is order-free and
#: exercises a first-party symbol, so coverage never depends on position.
_ORDER_PROBE_TESTS = (
    "def test_add_expense_records():\n"
    "    add_expense(3)\n"
    "    assert total() == 3\n",
    "def test_total_sums_expenses():\n"
    "    add_expense(3)\n"
    "    add_expense(4)\n"
    "    assert total() == 7\n",
    "def test_report_lists_totals():\n"
    "    add_expense(2)\n"
    "    assert '2' in report()\n",
)


def _order_probe_oracle(blocks: tuple[str, ...]) -> str:
    return "from expense import add_expense, total, report\n\n" + "\n\n".join(blocks)


def _order_probe_criteria() -> list[AcceptanceCriterion]:
    return [_crit("c1", "records an expense"),
            _crit("c2", "sums expenses"),
            _crit("c3", "reports the total", "smoke")]


def _prompt_lists(prompt: str) -> tuple[list[str], list[str]]:
    """Read the two co-presented lists back EXACTLY as the prompt orders them
    (criteria lines are ``- {id} [{tier}] {text}``; test names one CSV line)."""
    criteria_part = prompt.split("Criteria:\n", 1)[1].split("\n\n", 1)[0]
    ids = [line.split()[1] for line in criteria_part.splitlines()]
    names_part = prompt.split("Test functions present in the file: ", 1)[1].split("\n\n", 1)[0]
    return ids, [n.strip() for n in names_part.split(",")]


def test_coverage_map_order_probe_identical_covered_set_under_swap():
    # The free-text half of the oracle_qa.request_coverage_map injection seam.
    # The judge is scripted and purely POSITION-driven — it pairs the i-th
    # criterion with the i-th test name exactly as the prompt presents them —
    # so reversing both lists together must yield the same pairing, and any
    # asymmetry the probe surfaces belongs to the deterministic path (prompt
    # build, emission parse, AST verify), not to a model. NOTE (#1003 honest
    # scope): this establishes the surrounding pipeline is order-blind; only a
    # swapped-order run against the live 14B would measure model position bias.
    crits = _order_probe_criteria()
    seen: list[list[str]] = []

    def judge(prompt: str) -> str:
        ids, names = _prompt_lists(prompt)
        seen.append(ids)
        return json.dumps({cid: [name] for cid, name in zip(ids, names, strict=True)})

    code_fwd = _order_probe_oracle(_ORDER_PROBE_TESTS)
    map_fwd = oq.request_coverage_map(code_fwd, crits, generate_fn=judge)
    assert map_fwd, "scripted judge produced no usable forward emission"
    covered_fwd, uncovered_fwd, _ = oq.verify_traceability(code_fwd, map_fwd, crits)

    crits_rev = list(reversed(crits))
    code_rev = _order_probe_oracle(tuple(reversed(_ORDER_PROBE_TESTS)))
    map_rev = oq.request_coverage_map(code_rev, crits_rev, generate_fn=judge)
    assert map_rev, "scripted judge produced no usable reversed emission"
    covered_rev, uncovered_rev, _ = oq.verify_traceability(code_rev, map_rev, crits_rev)

    # The swap must actually REACH the judge — otherwise the probe is vacuous.
    assert seen == [["c1", "c2", "c3"], ["c3", "c2", "c1"]]
    assert set(covered_fwd) == set(covered_rev) == {"c1", "c2", "c3"}
    assert uncovered_fwd == [] and uncovered_rev == []


def test_coverage_map_order_probe_structured_path_identical():
    # The grammar-first half of the same seam: the schema pre-fills
    # ``required`` in criteria order, so a reversed input reverses the schema
    # the judge answers from. The covered set must be order-blind here exactly
    # as on the free-text path.
    seen: list[list[str]] = []

    def structured(prompt: str, schema: str) -> str:
        ids = list(json.loads(schema)["required"])
        seen.append(ids)
        _, names = _prompt_lists(prompt)
        return json.dumps({cid: [name] for cid, name in zip(ids, names, strict=True)})

    def covered_set(code: str, criteria: list[AcceptanceCriterion]) -> set[str]:
        cov = oq.request_coverage_map(
            code, criteria, generate_fn=lambda p: "", structured_generate_fn=structured)
        assert cov, "scripted judge produced no usable grammar emission"
        covered, _, _ = oq.verify_traceability(code, cov, criteria)
        return set(covered)

    crits = _order_probe_criteria()
    fwd = covered_set(_order_probe_oracle(_ORDER_PROBE_TESTS), crits)
    rev = covered_set(_order_probe_oracle(tuple(reversed(_ORDER_PROBE_TESTS))),
                      list(reversed(crits)))
    assert seen == [["c1", "c2", "c3"], ["c3", "c2", "c1"]]
    assert fwd == rev == {"c1", "c2", "c3"}


# ---------------------------------------------------------------------------
# Orchestrator — verdicts + regeneration accounting
# ---------------------------------------------------------------------------


def _full_cover_structured(map_dict):
    def structured(prompt, schema):
        if "list the test function name" in prompt:
            return json.dumps(map_dict)
        return ""
    return structured


def test_validate_clean_oracle_seeds():
    crits = [_crit("c2", "sums expenses")]
    result = oq.validate_authored_oracle(
        _CLEAN, "python", _spec(*crits), _tasks(),
        generate_fn=lambda p: "",
        structured_generate_fn=_full_cover_structured({"c2": ["test_total_sums_expenses"]}),
    )
    assert result.verdict == "seed"
    assert result.findings == []
    assert result.coverage_fraction() == "1/1"
    assert result.regen_rounds == 0 and not result.regen_exhausted


def test_validate_hard_defect_refuses_when_regeneration_fails():
    # An ill-posed strategy the model never fixes → exhausted → refuse (counted).
    crits = [_crit("c2", "sums expenses")]
    result = oq.validate_authored_oracle(
        _ILLPOSED_STRATEGY, "python", _spec(*crits), _tasks(),
        generate_fn=lambda p: _ILLPOSED_STRATEGY,  # reauthor returns the SAME defect
    )
    assert result.verdict == "refuse"
    assert result.regen_exhausted
    assert result.counts[oq.CLASS_REGENERATE_EXHAUSTED] == 1
    assert result.counts[oq.CLASS_STRATEGY] >= 1


def test_validate_regeneration_fixes_defect():
    crits = [_crit("c2", "sums expenses")]

    def gen(prompt):
        if "ONE problem to fix" in prompt:
            return _BOUNDED_STRATEGY  # the reauthor bounds the strategy
        return ""

    result = oq.validate_authored_oracle(
        _ILLPOSED_STRATEGY, "python", _spec(*crits), _tasks(),
        generate_fn=gen,
        structured_generate_fn=_full_cover_structured({"c2": ["test_total"]}),
    )
    assert result.verdict == "seed"
    assert result.regen_rounds == 1 and not result.regen_exhausted
    # The reauthored oracle is the bounded strategy (extraction strips trailing whitespace).
    assert result.oracle_code.strip() == _BOUNDED_STRATEGY.strip()
    assert "min_value=0.01" in result.oracle_code


def test_validate_soft_coverage_gap_seeds_partial():
    # A clean oracle whose coverage map leaves c7 uncovered, and the append never lands
    # a covering test → SOFT residual → seed-partial with the gap disclosed.
    crits = [_crit("c2", "sums expenses"), _crit("c7", "no crash on empty", "smoke")]

    def gen(prompt):
        if "ONE pytest test function" in prompt:
            return "def test_noop():\n    pass\n"  # never covers c7
        return ""

    result = oq.validate_authored_oracle(
        _CLEAN, "python", _spec(*crits), _tasks(),
        generate_fn=gen,
        structured_generate_fn=_full_cover_structured({"c2": ["test_total_sums_expenses"], "c7": []}),
    )
    assert result.verdict == "seed-partial"
    assert result.uncovered == ["c7"]
    assert result.coverage_fraction() == "1/2"


def test_validate_append_covers_criterion():
    crits = [_crit("c2", "sums expenses"), _crit("c7", "no crash on empty", "smoke")]

    def gen(prompt):
        if "ONE pytest test function" in prompt:
            return "def test_no_crash_on_empty():\n    from expense import total\n    assert total() == 0\n"
        return ""

    result = oq.validate_authored_oracle(
        _CLEAN, "python", _spec(*crits), _tasks(),
        generate_fn=gen,
        structured_generate_fn=_cover_then_full(
            {"c2": ["test_total_sums_expenses"], "c7": []},
            {"c2": ["test_total_sums_expenses"], "c7": ["test_no_crash_on_empty"]},
        ),
    )
    assert result.verdict == "seed"
    assert "test_no_crash_on_empty" in result.oracle_code
    assert result.regen_rounds == 1


def _cover_then_full(first_map, second_map):
    calls = {"n": 0}

    def structured(prompt, schema):
        if "list the test function name" not in prompt:
            return ""
        calls["n"] += 1
        return json.dumps(first_map if calls["n"] == 1 else second_map)
    return structured


def test_validate_reauthor_false_gates_without_rewrite():
    # The override branch (caller-authorised oracle): validate + count + gate, never rewrite.
    crits = [_crit("c2", "sums expenses")]
    result = oq.validate_authored_oracle(
        _ILLPOSED_STRATEGY, "python", _spec(*crits), _tasks(),
        generate_fn=lambda p: pytest.fail("reauthor must not be called"),
        reauthor=False,
    )
    assert result.verdict == "refuse"  # HARD strategy defect → refuse, but no rewrite
    assert result.regen_rounds == 0


def test_validate_flags_invented_return_and_regenerates_b4n2():
    # #826 B4n2 AUTHORSHIP half: the oracle demands check_answer(...) == 'correct', a magic
    # string the spec never names → SOFT invented-return → single-focus regeneration drops
    # the invented value → seed. (The wrong-signature half is caught at the gate probe.)
    crits = [_crit("c2", "quizzes the user on flashcards")]
    tasks = _tasks(exports=("check_answer(word)",), creates=("flashcards.py",))
    fixed = ("from flashcards import check_answer\n\n"
             "def test_quiz():\n    assert check_answer('cat') is not None\n")

    def gen(prompt):
        if "ONE problem to fix" in prompt:
            return fixed
        return ""

    result = oq.validate_authored_oracle(
        _INVENTED_RETURN_ONLY, "python", _spec(*crits), tasks,
        generate_fn=gen,
        structured_generate_fn=_full_cover_structured({"c2": ["test_quiz"]}),
    )
    assert result.counts[oq.CLASS_INVENTED_RETURN] >= 1
    assert result.verdict == "seed"
    assert result.regen_rounds >= 1
    assert "correct" not in result.oracle_code


def test_validate_tightens_coverage_to_declared_callables():
    # #826 traceability thread: the callable-level subjects (the plan's DECLARED exports)
    # ride into #821's verify_traceability. A declared test that touches a first-party
    # symbol which is NOT a promised export (here only the module object) no longer counts
    # as covering the criterion → seed-partial, the gap disclosed.
    crits = [_crit("c2", "totals expenses")]
    tasks = _tasks(exports=("total()",), creates=("expense.py",))  # declared callable: total
    oracle = ("import expense\n\n"
              "def test_touches_module():\n    assert expense is not None\n")

    def gen(prompt):
        if "ONE pytest test function" in prompt:
            return "def test_noop():\n    pass\n"  # the append never covers c2
        return ""

    result = oq.validate_authored_oracle(
        oracle, "python", _spec(*crits), tasks,
        generate_fn=gen,
        structured_generate_fn=_full_cover_structured({"c2": ["test_touches_module"]}),
    )
    assert result.uncovered == ["c2"]
    assert result.verdict == "seed-partial"


def test_validate_spends_regeneration_on_the_real_gap_not_a_submodule_phantom_967():
    # The end-to-end shape of the 20260719-002208-bd failure. invented_contract ranks 4,
    # traceability_gap ranks 7, so a phantom invention WINS the round and the regeneration
    # budget is spent re-authoring around a legitimate submodule import while the genuine
    # coverage gap is never addressed. With the submodules declared, the rounds go to the
    # finding that is actually there.
    crits = [_crit("c2", "adds a card"), _crit("c7", "no crash on empty deck", "smoke")]
    tasks = _tasks(exports=_SUBMODULE_EXPORTS, creates=_SUBMODULE_CREATES)
    oracle = (
        "from flashcard_app import card_manager, quiz_engine\n"
        "from flashcard_app.card_manager import add_card\n\n"
        "def test_add_card():\n"
        "    add_card('cat', 'feline')\n"
        "    assert card_manager is not None and quiz_engine is not None\n"
    )
    asked: list[str] = []

    def gen(prompt):
        asked.append(prompt)
        if "ONE pytest test function" in prompt:
            return "def test_noop():\n    pass\n"  # the append never covers c7
        return ""

    result = oq.validate_authored_oracle(
        oracle, "python", _spec(*crits), tasks,
        generate_fn=gen,
        structured_generate_fn=_full_cover_structured({"c2": ["test_add_card"]}),
    )
    # No phantom was ever counted, so no round was spent re-authoring the whole file.
    assert result.counts[oq.CLASS_INVENTED_CONTRACT] == 0
    assert not any("ONE problem to fix" in p for p in asked)
    # The regeneration budget went to the REAL residual — the uncovered smoke criterion.
    assert any("ONE pytest test function" in p for p in asked)
    assert result.uncovered == ["c7"] and result.covered == ["c2"]
    assert result.coverage_fraction() == "1/2"
    assert result.verdict == "seed-partial"


def test_validate_node_oracle_REFUSES_a_thin_exam_after_trying_to_repair_it():
    """#1410. This test previously asserted ``verdict == "seed"`` on this exact fixture —
    and the fixture is ``test('x', () => {})``, an EMPTY test body. It was asserting that a
    vacuous website exam gets seeded, which is the defect, encoded as the expected result.

    Node used to return early from ``validate_authored_oracle`` ("we cannot AST-scan JS" —
    true when written, false since ``node_static_vacuity`` was built), so the bounded repair
    loop never ran. Nine consecutive B9 runs recorded ``verdict: refuse`` with
    ``regeneration.rounds: 0``: the model was never asked to fix anything.

    Now the loop runs. ``generate_fn`` here returns ``""``, so the repair produces nothing
    usable and the residual stands — which is the honest outcome and the one this fixture
    should always have had. ``language`` and ``collectability`` are unchanged: the execution
    probes still belong to the seed gate."""
    result = oq.validate_authored_oracle(
        "import test from 'node:test';\ntest('x', () => {});", "node",
        _spec(_crit("c2", "x")), _tasks(), generate_fn=lambda p: "")
    assert result.verdict == "refuse"
    assert result.regen_exhausted, "refused without the repair having been attempted"
    assert result.language == "node"
    assert result.collectability == "skipped"


def test_validate_node_oracle_still_seeds_an_ADEQUATE_exam():
    """The precision half. Without this, the test above is satisfied by a validator that
    refuses every node exam, which would be a worse defect than the one being fixed —
    it would stop websites being graded at all rather than graded badly."""
    adequate = (
        "import test from 'node:test'; import assert from 'node:assert';\n"
        "import { getPieces } from '../src/pieces/data.js';\n"
        "test('pieces load', async () => {\n"
        "  const pieces = await getPieces();\n"
        "  assert.ok(pieces.length > 0);\n"
        "});\n"
    )
    result = oq.validate_authored_oracle(
        adequate, "node", _spec(_crit("c2", "x")), _tasks(),
        generate_fn=lambda p: "")
    assert result.verdict == "seed"
    assert result.regen_rounds == 0, "an adequate exam needs no repair round"
    assert result.language == "node"
    assert result.collectability == "skipped"


def test_validate_empty_oracle_refuses():
    result = oq.validate_authored_oracle(
        "", "python", _spec(), _tasks(), generate_fn=lambda p: "")
    assert result.verdict == "refuse" and not result.validated


# ---------------------------------------------------------------------------
# Evidence-stamp shape (the #827/#832 contract)
# ---------------------------------------------------------------------------


def test_to_evidence_shape():
    r = oq.OracleQAResult(
        oracle_code=_CLEAN, verdict="seed-partial",
        counts={oq.CLASS_TRACEABILITY: 1}, covered=["c2"], uncovered=["c7"],
        coverage_denominator=2, regen_rounds=1, f2p_baseline="all-fail",
        collectability="confirmed",
    )
    ev = r.to_evidence()
    assert ev["verdict"] == "seed-partial"
    assert ev["oracle_coverage"] == "1/2"
    assert ev["covered"] == ["c2"] and ev["uncovered"] == ["c7"]
    assert ev["f2p_baseline"] == "all-fail" and ev["collectability"] == "confirmed"
    assert ev["regeneration"] == {"rounds": 1, "exhausted": False}
    # Every taxonomy class is present in the count map (stable shape for #827).
    assert set(ev["findings"]) == set(oq.ALL_CLASSES)
    assert ev["findings"][oq.CLASS_TRACEABILITY] == 1
    assert ev["findings_total"] == 1


def test_coverage_fraction_unknown_when_no_map():
    r = oq.OracleQAResult(oracle_code=_CLEAN, coverage_denominator=0)
    assert r.coverage_fraction() == "unknown"


# ---------------------------------------------------------------------------
# The runner-pins drift lock (interim, until grade_env.py SSOT lands via #822)
# ---------------------------------------------------------------------------


def test_qa_runner_pins_match_grade_path():
    # A "collectable here" verdict must genuinely predict "collectable at grade": the QA
    # subprocess pins MUST equal real_run_job_oracle's grade invocation (swap_ops.py).
    src = Path(oq.__file__).resolve().parents[1] / "fleet" / "swap_ops.py"
    text = src.read_text(encoding="utf-8")
    assert oq._QA_PYTEST_PIN in text, "QA pytest pin drifted from the grade-time runner"
    assert oq._QA_HYPOTHESIS_PIN in text, "QA hypothesis pin drifted from the grade-time runner"


def test_oracle_qa_enabled_kill_switch(monkeypatch):
    monkeypatch.delenv("BLARAI_ORACLE_QA", raising=False)
    assert oq.oracle_qa_enabled() is True
    for off in ("0", "false", "no", "off", ""):
        monkeypatch.setenv("BLARAI_ORACLE_QA", off)
        assert oq.oracle_qa_enabled() is False
    monkeypatch.setenv("BLARAI_ORACLE_QA", "1")
    assert oq.oracle_qa_enabled() is True


# ---------------------------------------------------------------------------
# Plan-time integration — acceptance.author_and_qa_job_oracle
# ---------------------------------------------------------------------------


def _job_gen(oracle=_CLEAN, **routes):
    def gen(prompt):
        if "JOB-LEVEL ACCEPTANCE" in prompt:
            return oracle
        if "ONE problem to fix" in prompt:
            return routes.get("reauthor", "")
        if "ONE pytest test function" in prompt:
            return routes.get("append", "")
        if "list the test function name" in prompt:
            return routes.get("coverage", "{}")
        return ""
    return gen


def test_author_and_qa_clean_passes():
    spec = _spec(_crit("c2", "sums expenses"))
    code, path, ev = acc.author_and_qa_job_oracle(
        "an expense tracker", spec, _tasks(),
        generate_fn=_job_gen(),
        structured_generate_fn=_full_cover_structured({"c2": ["test_total_sums_expenses"]}),
    )
    assert path == JOB_ORACLE_PATH_PYTHON
    assert "def test_total_sums_expenses" in code
    assert ev["verdict"] == "seed" and ev["oracle_coverage"] == "1/1"


def test_author_and_qa_refuses_hard_defect():
    spec = _spec(_crit("c2", "sums expenses"))
    code, path, ev = acc.author_and_qa_job_oracle(
        "g", spec, _tasks(),
        generate_fn=_job_gen(oracle=_ILLPOSED_STRATEGY, reauthor=_ILLPOSED_STRATEGY),
    )
    # A HARD-defective oracle the model never fixes → refused (a bad oracle is worse than
    # none): code/path dropped, but the evidence still records the refusal for #827.
    assert code == "" and path == ""
    assert ev["verdict"] == "refuse"
    assert ev["findings"][oq.CLASS_STRATEGY] >= 1


def test_author_and_qa_disabled_is_passthrough(monkeypatch):
    monkeypatch.setenv("BLARAI_ORACLE_QA", "0")
    spec = _spec(_crit("c2", "sums expenses"))
    code, path, ev = acc.author_and_qa_job_oracle(
        "g", spec, _tasks(), generate_fn=_job_gen(oracle=_ILLPOSED_STRATEGY))
    # QA off → the (ill-posed) authored oracle passes through unvalidated, byte-identical
    # to the pre-#821 author-only path.
    assert path == JOB_ORACLE_PATH_PYTHON
    assert code.strip() == _ILLPOSED_STRATEGY.strip() and ev == {}


# ---------------------------------------------------------------------------
# Seed-time integration — swap_ops.real_seed_job_oracle (the F2P gate)
# ---------------------------------------------------------------------------


def _config(tmp_path: Path) -> FleetDispatchConfig:
    setup = tmp_path / "setup"
    (setup / "scripts").mkdir(parents=True)
    return FleetDispatchConfig(
        scripts_dir=setup / "scripts",
        queue_path=setup / "state" / "fleet-queue.json",
        runs_dir=setup / "state" / "fleet-runs",
        projects_dir=tmp_path,
    )


def _mk_repo(tmp_path: Path, name: str = "proj") -> Path:
    repo = tmp_path / name
    (repo / ".git").mkdir(parents=True, exist_ok=True)
    return repo


def _git_ok(cmd, timeout_s, cwd=None):
    return (True, "", "")


def test_seed_gate_refuses_vacuous_oracle(tmp_path):
    config = _config(tmp_path)
    repo = _mk_repo(tmp_path)
    qa_run = _fake_run(out="_qa_f2p_probe.py::test_always PASSED\n1 passed in 0.01s")
    res = so.real_seed_job_oracle(
        config, "R1", str(repo), JOB_ORACLE_PATH_PYTHON, _NO_FIRST_PARTY, qa_run=qa_run)
    # A confirmed vacuous test refuses the seed → honest job-acceptance not-run.
    assert res["ok"] is False and "REFUSED" in res["evidence"]
    assert not (repo / JOB_ORACLE_PATH_PYTHON).exists()  # never seeded
    ev = json.loads((config.runs_dir / "R1" / "oracle-qa.json").read_text(encoding="utf-8"))
    assert ev["f2p_baseline"].startswith("vacuous")
    assert ev["verdict"] == "refuse"


def test_seed_gate_clean_seeds_and_writes_evidence(tmp_path, monkeypatch):
    config = _config(tmp_path)
    repo = _mk_repo(tmp_path)
    monkeypatch.setattr(so.shutil, "which", lambda name: f"C:/fake/{name}.exe")
    qa_run = _fake_run(out="_qa_f2p_probe.py::test_x FAILED\n1 failed in 0.02s")
    res = so.real_seed_job_oracle(
        config, "R1", str(repo), JOB_ORACLE_PATH_PYTHON, _CLEAN,
        qa_evidence_json=json.dumps({"verdict": "seed", "findings": {}, "language": "python"}),
        run=_git_ok, qa_run=qa_run)
    assert res["ok"] is True
    seeded = (repo / JOB_ORACLE_PATH_PYTHON).read_text(encoding="utf-8")
    assert "allow_module_level=True" in seeded  # still guard-wrapped
    ev = json.loads((config.runs_dir / "R1" / "oracle-qa.json").read_text(encoding="utf-8"))
    assert ev["f2p_baseline"] == "all-fail"


def test_seed_gate_no_runner_persists_plan_evidence_and_seeds(tmp_path, monkeypatch):
    config = _config(tmp_path)
    repo = _mk_repo(tmp_path)
    monkeypatch.setattr(so.shutil, "which", lambda name: f"C:/fake/{name}.exe")
    # qa_run omitted → the execution gate is skipped, but the plan-time evidence is kept.
    res = so.real_seed_job_oracle(
        config, "R1", str(repo), JOB_ORACLE_PATH_PYTHON, _CLEAN,
        qa_evidence_json=json.dumps(
            {"verdict": "seed-partial", "findings": {"traceability_gap": 1},
             "language": "python", "oracle_coverage": "1/2"}),
        run=_git_ok)
    assert res["ok"] is True
    ev = json.loads((config.runs_dir / "R1" / "oracle-qa.json").read_text(encoding="utf-8"))
    assert ev["f2p_baseline"] == "not-run"          # execution gate skipped
    # BOTH execution stamps, or the persisted evidence carries a verdict for a probe that
    # never ran. This branch defaulted only the f2p stamp, leaving `collectability` absent
    # entirely — indistinguishable to a reader from a key the writer forgot.
    assert ev["collectability"] == "not-run"
    assert ev["findings"]["traceability_gap"] == 1  # plan-time evidence persisted


def test_seed_gate_machinery_miss_never_blocks(tmp_path, monkeypatch):
    config = _config(tmp_path)
    repo = _mk_repo(tmp_path)
    monkeypatch.setattr(so.shutil, "which", lambda name: f"C:/fake/{name}.exe")
    qa_run = _fake_run(out="", err="")  # empty → f2p not-run (machinery miss)
    res = so.real_seed_job_oracle(
        config, "R1", str(repo), JOB_ORACLE_PATH_PYTHON, _CLEAN, run=_git_ok, qa_run=qa_run)
    assert res["ok"] is True  # a machinery miss NEVER blocks the seed
    assert (repo / JOB_ORACLE_PATH_PYTHON).exists()


def test_seed_gate_containment_unaffected(tmp_path):
    # The #821 gate rides INSIDE the existing containment — an unpinned path still refuses
    # before any QA runs.
    config = _config(tmp_path)
    repo = _mk_repo(tmp_path)
    res = so.real_seed_job_oracle(
        config, "R1", str(repo), "../../evil.py", _CLEAN, qa_run=_fake_run())
    assert res["ok"] is False and "refused" in res["evidence"]


# ---------------------------------------------------------------------------
# #1200 — the runner the probes actually get
#
# Everything above this line fakes the subprocess. That is what hid this defect for two
# live nights: `_qa_env` and `_pytest_cmd` are the seam the live path crosses, and an
# injected `run` never touches either. These lock the seam itself — the env the probes
# get, the command they build, and (in the @slow tier) the REAL `uv run` executing.
# ---------------------------------------------------------------------------


def _managed_root(app_data_base: Path) -> Path:
    """Build a REALISTIC uv managed-interpreter tree under *app_data_base* and return its
    ``uv/python`` root.

    A bare empty ``uv/python`` is not an installation — uv looks inside, finds nothing, and
    falls back — so a fixture that only mkdir'd the root was testing a state uv treats as
    absent while the old presence-check called it healthy."""
    install = app_data_base / "uv" / "python" / "cpython-3.13-windows-x86_64-none"
    install.mkdir(parents=True, exist_ok=True)
    (install / "python.exe").write_text("", encoding="utf-8")
    return app_data_base / "uv" / "python"


def _fake_app_data(monkeypatch, tmp_path, *, make_dirs: bool = True):
    """Point the app-data roots at a tmp tree, optionally with uv really installed there.

    Host-independent on purpose: the pinning must be asserted against a tree this test
    created, never against whatever this machine happens to have installed."""
    roaming = tmp_path / "Roaming"
    local = tmp_path / "Local"
    if make_dirs:
        _managed_root(roaming)
        (local / "uv" / "cache").mkdir(parents=True)
    else:
        roaming.mkdir(parents=True)
        local.mkdir(parents=True)
    monkeypatch.setenv("APPDATA", str(roaming))
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.delenv("UV_PYTHON_INSTALL_DIR", raising=False)
    monkeypatch.delenv("UV_CACHE_DIR", raising=False)
    return roaming, local


def test_qa_env_pins_uv_dirs_outside_the_isolated_home(tmp_path, monkeypatch):
    """The whole defect in one assertion: uv's dirs must survive the app-data redirect.

    Without this, uv cannot see its managed CPython, silently falls back to a system
    interpreter, and the probes below report on a runner nobody chose."""
    roaming, local = _fake_app_data(monkeypatch, tmp_path)
    home = tmp_path / "isolated"
    home.mkdir()

    env = oq._qa_env(home)

    assert env["UV_PYTHON_INSTALL_DIR"] == str(roaming / "uv" / "python")
    assert env["UV_CACHE_DIR"] == str(local / "uv" / "cache")


def test_qa_env_still_isolates_the_operators_app_data(tmp_path, monkeypatch):
    """The pinning must not buy grade parity by giving the isolation away: the app-data
    roots themselves still point into the throwaway home, and the two uv paths are the ONLY
    things reaching outside it."""
    _fake_app_data(monkeypatch, tmp_path)
    home = tmp_path / "isolated"
    home.mkdir()

    env = oq._qa_env(home)

    assert env["LOCALAPPDATA"] == str(home)
    assert env["APPDATA"] == str(home)
    escaping = {k for k, v in env.items()
                if k.startswith("UV_") and not str(v).startswith(str(home))}
    assert escaping == {"UV_PYTHON_INSTALL_DIR", "UV_CACHE_DIR"}


def test_uv_overlay_never_invents_a_directory(tmp_path, monkeypatch):
    """A path we made up is worse than uv's own default: it would look pinned and resolve
    to nothing."""
    _fake_app_data(monkeypatch, tmp_path, make_dirs=False)
    assert grade_env.uv_dir_overlay() == {}


def test_uv_overlay_leaves_an_explicit_override_alone(tmp_path, monkeypatch):
    """An operator/CI override always wins — the overlay pins what was NOT chosen."""
    _fake_app_data(monkeypatch, tmp_path)
    chosen = {"UV_PYTHON_INSTALL_DIR": "D:/pythons"}
    overlay = grade_env.uv_dir_overlay(chosen)
    assert "UV_PYTHON_INSTALL_DIR" not in overlay
    assert overlay["UV_CACHE_DIR"].endswith("cache")


def test_the_two_modules_share_ONE_uv_rule():
    """oracle_qa and oracle_mutation redirect the same roots for the same isolation and hit
    this defect independently. A second copy of the remedy is how a third module gets it
    wrong silently — the rule has one home."""
    env: dict = {}
    mutation._preserve_uv_dirs(env)
    assert env == grade_env.uv_dir_overlay({})


# --- the fail-loud half: a runner that never ran is not a verdict -----------


#: The real stderr shape of the fallback interpreter dying during pytest plugin load
#: (captured 2026-07-30): a traceback, and NO pytest summary line anywhere.
_BROKEN_RUNNER_STDERR = (
    "Traceback (most recent call last):\n"
    r'  File "C:\Python314\Lib\importlib\metadata\__init__.py", line 179, in load' "\n"
    "    module = import_module(match.group('module'))\n"
    r'  File "C:\Python314\Lib\site-packages\pytest_textual_snapshot.py", line 23' "\n"
    "    from rich.console import Console\n"
    "ModuleNotFoundError: No module named 'rich'\n"
)


def test_collect_probe_stamps_not_run_when_the_runner_died():
    """The control that makes avoidance safe. Pinning uv can stop working (an unset APPDATA,
    a moved install) — so the probe must be able to SAY it never ran, rather than reporting
    `unconfirmed`, which reads as a verdict on the oracle and is what banked for two nights."""
    run = _fake_run(out="", err=_BROKEN_RUNNER_STDERR)
    stamp, finding = oq.confirm_collectable(_CLEAN, run=run)
    assert stamp == "not-run", (
        "a runner that died before pytest printed anything produced NO evidence about the "
        "oracle; stamping 'unconfirmed' dresses a machinery miss as a measurement"
    )
    assert finding is None


def test_collect_probe_not_run_is_distinct_from_a_real_collection_failure():
    """The toggle on the distinction itself: the same non-zero exit, but WITH a pytest
    summary, is a genuine result and must still be read as one."""
    run = _fake_run(out="1 error in 0.10s", err="E   SyntaxError: invalid syntax")
    stamp, finding = oq.confirm_collectable(_ILLPOSED_STRATEGY, run=run)
    assert stamp == "unconfirmed" and finding is not None


def test_a_result_that_never_probed_does_not_claim_unconfirmed():
    """The plan-time path never reaches the subprocess probe. Its default said `unconfirmed`
    — a verdict on an exam nothing had looked at."""
    assert oq.OracleQAResult(oracle_code=_CLEAN).collectability == "not-run"


# --- the command: verbosity is load-bearing, and -q -v cancel ---------------


def test_execution_runs_are_verbose_enough_to_parse_per_test(tmp_path):
    """`_passed_tests` reads `<file>::<name> PASSED` lines. `-q` and `-v` are one counter in
    pytest, so the two together produce dot output and EVERY passing test parses as absent —
    a vacuous oracle then grades all-fail clean."""
    cmd = oq._pytest_cmd("t.py", tmp_path / "clean.ini", collect_only=False)
    assert cmd is not None
    assert "-v" in cmd and "-q" not in cmd


def test_collect_only_runs_stay_quiet(tmp_path):
    """Collect-only is read by exit code + a collection signal, not per test."""
    cmd = oq._pytest_cmd("t.py", tmp_path / "clean.ini", collect_only=True)
    assert cmd is not None
    assert "-q" in cmd and "-v" not in cmd


# --- the REAL runner: @slow, because they cost what production costs ---------
#
# Documented environmental delta: skipped where `uv` is absent. `_pytest_cmd` falls back to
# the current interpreter there, which is a different runner and cannot prove grade parity.

_NEEDS_UV = pytest.mark.skipif(shutil.which("uv") is None,
                               reason="grade parity is a uv property; no uv on this host")

#: A genuinely VACUOUS oracle: it passes against an empty tree, so the F2P baseline must
#: convict it. Reused by the real-runner pair below.
_REALLY_VACUOUS = "def test_always_green():\n    assert True\n"


@pytest.mark.slow
@_NEEDS_UV
def test_REAL_uv_runner_confirms_a_collectable_oracle():
    """The test this module never had. No injected `run` — the actual `uv run --no-project`
    command, the actual redirected env, the actual pytest.

    On this host it returned `unconfirmed` on every invocation before #1200, because uv fell
    back to a system interpreter whose site-packages broke pytest's plugin load."""
    started = time.perf_counter()
    stamp, finding = oq.confirm_collectable(_CLEAN)
    elapsed = time.perf_counter() - started

    assert stamp == "confirmed", f"the real runner could not collect a clean oracle: {finding}"
    assert elapsed > 1.0, (
        f"the probe finished in {elapsed:.2f}s — a real `uv run` does not, so this test has "
        "stopped exercising the seam it exists for"
    )


@pytest.mark.slow
@_NEEDS_UV
def test_REAL_uv_runner_convicts_a_vacuous_oracle(tmp_path):
    """The end-to-end property the whole gate exists for, driven for real: a test that passes
    with NO implementation present is vacuous and must be a HARD finding.

    Catches both #1200 defects at once — a broken runner stamps `not-run`, and a runner whose
    output cannot be parsed per test stamps `all-fail`, which is a FALSE clean."""
    skeleton = tmp_path / "skeleton"
    skeleton.mkdir()

    stamp, findings = oq.fail_to_pass_baseline(_REALLY_VACUOUS, str(skeleton))

    assert stamp == "vacuous:test_always_green", (
        f"stamp was {stamp!r}; 'not-run' means the runner never ran, 'all-fail' means it ran "
        "and its output could not be parsed per test — both let a vacuous oracle seed"
    )
    assert len(findings) == 1 and findings[0].hard


@pytest.mark.slow
@_NEEDS_UV
def test_TOGGLE_without_the_uv_pinning_the_probe_stops_confirming(monkeypatch):
    """Principle 12 — the control proved OFF. Removing the pinning must visibly change which
    interpreter runs, or the two tests above are passing for reasons unrelated to the fix.

    Asserted on the RESOLVED INTERPRETER rather than on the stamp: what the fallback
    interpreter happens to be is a property of the host, but that the redirect hides uv's
    managed one is a property of the redirect, and that is the defect."""
    import subprocess

    real_python_dir = grade_env.uv_dir_overlay({}).get("UV_PYTHON_INSTALL_DIR")
    if not real_python_dir:
        pytest.skip("uv has no managed interpreter installed here; nothing to hide")

    def resolve(env: dict, cwd: str) -> str:
        # cwd IS LOAD-BEARING and was missing (found 2026-08-15, the first time these
        # @slow tests were ever run). Without it the probe inherits pytest's working
        # directory — the BlarAI checkout — where `uv run` discovers `.venv/` and reports
        # THAT interpreter, so the precondition below failed against a correct product.
        # Production never resolves from the repo root: oracle_qa spawns with cwd set to
        # the isolated grade dir. Measured both ways: from the repo root uv returns
        # `BlarAI\.venv\Scripts\python.exe`, from an isolated dir it returns the managed
        # `uv\python\cpython-3.13-...\python.exe`.
        out = subprocess.run(  # noqa: S603 — argv list, no shell
            [shutil.which("uv"), "run", "--no-project", "python", "-c",
             "import sys; print(sys.executable)"],
            capture_output=True, text=True, env=env, timeout=300, cwd=cwd,
        )
        return out.stdout.strip()

    with tempfile.TemporaryDirectory(prefix="oracle_qa_toggle_") as home:
        isolated = tempfile.mkdtemp(prefix="oracle_qa_toggle_cwd_")
        pinned = oq._qa_env(Path(home))
        unpinned = dict(pinned)
        for var in ("UV_PYTHON_INSTALL_DIR", "UV_CACHE_DIR"):
            unpinned.pop(var, None)

        assert resolve(pinned, isolated).lower().startswith(real_python_dir.lower()), (
            "the pinned env did not reach uv's managed interpreter — the fix is not doing "
            "what the tests above credit it for"
        )
        assert not resolve(unpinned, isolated).lower().startswith(real_python_dir.lower()), (
            "removing the pinning changed nothing, so this host cannot demonstrate the "
            "defect and the tests above prove nothing about it"
        )


# --- the gap `not-run` cannot close: a pin that quietly did not take --------


def test_a_run_whose_uv_pin_did_not_take_is_not_called_confirmed(tmp_path, monkeypatch):
    """RESIDUAL 4. The pin can fail silently — a root variable unset, a permissions error, a
    uv release that relocates the directory — and where the fallback interpreter happens to
    WORK, the collect succeeds and nothing fails. `not-run` cannot fire. `confirmed` would be
    true about collectability and silently false about the parity the pin exists for."""
    # uv IS installed natively (so there is parity to lose) but the overlay failed to pin it —
    # a permissions error, a relocated directory. THAT is the degraded state. A host with no
    # managed interpreter at all is not degraded and must not be convicted; see below.
    _fake_app_data(monkeypatch, tmp_path, make_dirs=True)
    monkeypatch.setattr(grade_env, "uv_dir_overlay", lambda base=None: {})
    monkeypatch.setattr(shutil, "which", lambda name: "C:/tools/uv.exe" if name == "uv" else None)
    run = _fake_run(out="collected 2 items", ok=True)        # the fallback WORKED

    stamp, finding = oq.confirm_collectable(_CLEAN, run=run)

    assert stamp == "parity-unverified", (
        f"stamp was {stamp!r} — a collect that succeeded on an interpreter we could not pin "
        "must not borrow the clean word; that is the original defect wearing the fix's uniform"
    )
    assert finding is None, "an unvouched runner is not evidence of a defective oracle"


def test_TOGGLE_restoring_the_pin_restores_confirmed(tmp_path, monkeypatch):
    """The other half of the same control (principle 12): identical run, identical output,
    the ONLY difference is that uv's directory is now reachable. If this did not flip back to
    `confirmed`, the check above would be convicting every run rather than degraded ones."""
    _fake_app_data(monkeypatch, tmp_path, make_dirs=True)    # the overlay can pin now
    monkeypatch.setattr(shutil, "which", lambda name: "C:/tools/uv.exe" if name == "uv" else None)
    run = _fake_run(out="collected 2 items", ok=True)

    stamp, finding = oq.confirm_collectable(_CLEAN, run=run)

    assert (stamp, finding) == ("confirmed", None)


def test_the_non_uv_fallback_runner_is_not_convicted_of_a_parity_loss(tmp_path, monkeypatch):
    """Precision, so fail-loud does not become cry-wolf: where no uv exists the command runs
    the current interpreter and there is no uv pin to have lost. Convicting it would make the
    stamp meaningless on every host without uv."""
    _fake_app_data(monkeypatch, tmp_path, make_dirs=False)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    run = _fake_run(out="collected 2 items", ok=True)

    stamp, _ = oq.confirm_collectable(_CLEAN, run=run)

    assert stamp == "confirmed"


def test_an_override_pointing_at_nothing_is_not_a_pin(tmp_path, monkeypatch):
    """`uv_dir_overlay` honours an explicit override, so the parity check must not take the
    variable's mere presence as proof — uv ignores a path that holds no interpreter."""
    monkeypatch.setenv("APPDATA", str(_managed_root(tmp_path / "native").parent.parent))
    monkeypatch.delenv("UV_PYTHON_INSTALL_DIR", raising=False)
    assert not grade_env.uv_parity_is_vouched({"UV_PYTHON_INSTALL_DIR": str(tmp_path / "gone")})
    assert not grade_env.uv_parity_is_vouched({})
    assert grade_env.uv_parity_is_vouched(
        {"UV_PYTHON_INSTALL_DIR": str(_managed_root(tmp_path / "other"))})


# --- the same discipline on the sibling: `all-fail` reads as CLEAN ----------


def test_f2p_clean_verdict_from_an_unvouched_runner_is_not_called_all_fail(tmp_path, monkeypatch):
    """The symmetric case. `fail_to_pass_baseline` shares `_qa_env`, so it can complete on the
    same unvouched interpreter — and its clean word is `all-fail`, which is exactly the false
    green this gate exists to prevent. The asymmetry was worse than the original defect: the
    probe that refuses to borrow the clean word makes the one that does look deliberate."""
    _fake_app_data(monkeypatch, tmp_path, make_dirs=True)    # parity exists to be lost
    monkeypatch.setattr(grade_env, "uv_dir_overlay", lambda base=None: {})
    monkeypatch.setattr(shutil, "which", lambda name: "C:/tools/uv.exe" if name == "uv" else None)
    skeleton = tmp_path / "skeleton"
    skeleton.mkdir()
    run = _fake_run(out="_qa_f2p_probe.py::test_x FAILED\n1 failed in 0.10s")

    stamp, findings = oq.fail_to_pass_baseline(_CLEAN, str(skeleton), run=run)

    assert stamp == "parity-unverified", f"a clean F2P verdict was stamped {stamp!r}"
    assert findings == []


def test_TOGGLE_f2p_reachable_interpreter_restores_all_fail(tmp_path, monkeypatch):
    """Identical run, identical output; the only difference is a reachable directory."""
    _fake_app_data(monkeypatch, tmp_path, make_dirs=True)
    monkeypatch.setattr(shutil, "which", lambda name: "C:/tools/uv.exe" if name == "uv" else None)
    skeleton = tmp_path / "skeleton"
    skeleton.mkdir()
    run = _fake_run(out="_qa_f2p_probe.py::test_x FAILED\n1 failed in 0.10s")

    stamp, findings = oq.fail_to_pass_baseline(_CLEAN, str(skeleton), run=run)

    assert (stamp, findings) == ("all-fail", [])


def test_f2p_non_uv_runner_is_not_convicted_of_a_parity_loss(tmp_path, monkeypatch):
    """No uv, no uv pin to lose — convicting here would make the stamp noise."""
    _fake_app_data(monkeypatch, tmp_path, make_dirs=False)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    skeleton = tmp_path / "skeleton"
    skeleton.mkdir()
    run = _fake_run(out="_qa_f2p_probe.py::test_x FAILED\n1 failed in 0.10s")

    stamp, _ = oq.fail_to_pass_baseline(_CLEAN, str(skeleton), run=run)

    assert stamp == "all-fail"


def test_an_unvouched_runner_does_NOT_soften_a_vacuous_conviction(tmp_path, monkeypatch):
    """The deliberate asymmetry, locked. ONLY the clean outcome is downgraded.

    A test that PASSES with no implementation present is evidence whichever interpreter
    observed it, and softening a HARD finding would weaken the gate — a capability change, not
    a defect fix. `failure_taxonomy` also keys off the `vacuous` prefix, so the shape is load
    bearing beyond this module."""
    _fake_app_data(monkeypatch, tmp_path, make_dirs=True)
    monkeypatch.setattr(grade_env, "uv_dir_overlay", lambda base=None: {})
    monkeypatch.setattr(shutil, "which", lambda name: "C:/tools/uv.exe" if name == "uv" else None)
    skeleton = tmp_path / "skeleton"
    skeleton.mkdir()
    run = _fake_run(out="_qa_f2p_probe.py::test_always PASSED\n1 passed in 0.01s")

    stamp, findings = oq.fail_to_pass_baseline(_NO_FIRST_PARTY, str(skeleton), run=run)

    assert stamp == "vacuous:test_always"
    assert len(findings) == 1 and findings[0].hard


# --- a machinery miss must not be able to SPELL itself like a result -------


#: Real uv failure text. Contains " failed" twice and would have satisfied the old
#: substring-based `_run_completed`, turning a network failure into a clean F2P verdict.
_UV_FETCH_ERROR = (
    "error: Failed to fetch: https://pypi.org/simple/pytest/\n"
    "  Caused by: Request failed after 3 retries\n"
)


@pytest.mark.parametrize("blob", [
    _UV_FETCH_ERROR,
    "error: No interpreter found for Python 3.13 in managed installations\n",
    "error: Distribution not found: hypothesis==6.155.7\n",
    "The system cannot find the path specified.\n",
])
def test_machinery_failures_are_never_read_as_a_completed_run(blob):
    """`_run_completed` gates F2P's clean verdict. It once accepted the bare substrings
    ' passed' / ' failed' / ' error' / '=== ', which ordinary English contains — so a uv
    network error read as a run that completed with nothing passing, i.e. `all-fail`, i.e.
    CLEAN, from a run that never executed a test."""
    assert not oq._run_completed(blob), f"a machinery miss was read as a completed run: {blob!r}"


@pytest.mark.parametrize("blob", [
    "1 failed in 0.02s",
    "no tests collected, 1 error in 1.34s",
    "collected 2 items",
    "= 1 passed in 0.39s =",
    "no tests ran in 0.01s",
    "errors during collection",
])
def test_real_pytest_completions_are_still_recognised(blob):
    """The other direction: tightening must not turn genuine runs into false `not-run`s,
    which would make the gate permanently unmeasurable in the safe-looking direction."""
    assert oq._run_completed(blob)


def test_the_FAILURES_banner_still_counts_as_a_completed_run():
    """REGRESSION LOCK — `_run_completed` is NOT private to this module.

    `oracle_mutation._mutant_verdict` calls it, and there "the run completed and failed"
    means the mutant was KILLED while "the run did not complete" means NOT COUNTED. A repo
    whose ``addopts`` suppresses the short summary (``-rN --tb=no`` — exactly the config
    #1195 wrote its killer-parsing fallback for) produces a RED run carrying the FAILURES
    banner and NO count line.

    An earlier draft of this branch's anchoring pass dropped the banner along with the
    unanchored ``"=== "`` it was right to remove. Measured then: `_mutant_verdict(False,
    banner)` returned None where main returned False — a genuine kill silently leaving both
    `oracle_mutation_killed` and `oracle_mutation_ran`, which are REGISTERED counts
    (`shared/instrument_registry.py`). Main's own `test_oracle_mutation.py` stayed green
    throughout, because `failing_tests` and `_run_completed` read the same blob by different
    routes — so no existing gate could catch it.

    Toggle: delete `_PYTEST_FAILURES_RE` from `_run_completed` and this goes red.
    """
    banner = "=========== FAILURES ===========\n_________ test_beta _________\n"
    assert oq._run_completed(banner), (
        "a RED run whose repo suppresses the short summary was read as a machinery miss — "
        "downstream, oracle_mutation stops COUNTING a mutant it genuinely killed")


def test_the_banner_must_be_a_LINE_not_a_phrase():
    """CONTROL for the lock above, and the reason the pattern is line-anchored.

    Re-admitting the banner must not re-open the hole the anchoring pass closed: prose that
    merely mentions the banner is not evidence pytest ran."""
    assert not oq._run_completed("the doc says === FAILURES === appears in output")
    assert not oq._run_completed(
        "error: Failed to fetch https://x  Request failed after 3 retries")


def test_f2p_does_not_return_clean_from_a_uv_network_failure(tmp_path):
    """The blocker end to end, at the seam that matters: the vacuity gate must not certify a
    clean exam because uv could not reach the index.

    This branch was DEAD before the runner was fixed — F2P stamped `not-run` on every
    invocation on this host — so repairing the interpreter is what brought it live on the
    dispatch path, and with it this fail-open."""
    skeleton = tmp_path / "skeleton"
    skeleton.mkdir()

    stamp, findings = oq.fail_to_pass_baseline(
        _CLEAN, str(skeleton), run=_fake_run(out="", err=_UV_FETCH_ERROR))

    assert stamp == "not-run", (
        f"a uv network failure was stamped {stamp!r}; 'all-fail' would certify the oracle "
        "discriminates on the strength of a run that never executed a test"
    )
    assert findings == []


# --- the two edges that broke the presence-check predicate ------------------
#
# Both MEASURED on the real uv (2026-07-31) via sys._base_executable — sys.executable only
# reports uv's ephemeral build venv, which is what made the empty-directory case easy to miss.


def test_a_pin_at_an_EMPTY_directory_is_not_parity(tmp_path, monkeypatch):
    r"""TOO NARROW, the edge the presence-check let straight through.

    `UV_PYTHON_INSTALL_DIR` at a directory that exists but holds no interpreter: uv looks in,
    finds nothing, and falls back. Measured — `sys._base_executable` resolves to
    `C:\Python314\python.exe`, the exact contaminated interpreter #1200 exists because of —
    while `Path.is_dir()` reports the pin healthy. Reachable in production from a uv upgrade
    relocating the version dir, an interpreter removed, or a partial install."""
    _fake_app_data(monkeypatch, tmp_path, make_dirs=True)     # uv IS installed natively
    hollow = tmp_path / "hollow_pin"
    hollow.mkdir()

    assert not grade_env.uv_parity_is_vouched({"UV_PYTHON_INSTALL_DIR": str(hollow)}), (
        "an existing but empty interpreter directory was vouched as parity — uv abandons it "
        "for the system interpreter, so this is the original defect with a healthy-looking pin"
    )


def test_the_overlay_never_pins_an_EMPTY_interpreter_directory(tmp_path, monkeypatch):
    """The same question in the function that SETS the variable. Pinning a hollow directory
    would manufacture precisely the state the guard above convicts — a control firing on a
    state its own sibling created."""
    roaming, local = tmp_path / "Roaming", tmp_path / "Local"
    (roaming / "uv" / "python").mkdir(parents=True)           # present, no interpreter
    (local / "uv" / "cache").mkdir(parents=True)
    monkeypatch.setenv("APPDATA", str(roaming))
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.delenv("UV_PYTHON_INSTALL_DIR", raising=False)
    monkeypatch.delenv("UV_CACHE_DIR", raising=False)

    overlay = grade_env.uv_dir_overlay({})

    assert "UV_PYTHON_INSTALL_DIR" not in overlay, (
        "the overlay exported a pin at a directory uv ignores — not a pin, and it would make "
        "the parity guard convict a configuration the overlay itself created"
    )
    assert overlay["UV_CACHE_DIR"].endswith("cache"), "a cold cache costs a fetch, not parity"


def test_a_host_with_NO_managed_interpreter_is_not_convicted(tmp_path, monkeypatch):
    r"""TOO WIDE, and it is my own rule turned on my own fix: a fail-loud control that convicts
    healthy configurations gets muted.

    Where uv has no managed interpreter at all, the redirect changes NOTHING — measured, the
    probe-time and grade-time `sys._base_executable` are the same `C:\Python314\python.exe`,
    so parity genuinely holds. The presence-check version fired `unpinned` on every such run,
    forever, because the overlay had nothing to pin."""
    _fake_app_data(monkeypatch, tmp_path, make_dirs=False)    # uv NOT installed natively

    assert grade_env.uv_parity_is_vouched({}), (
        "a host that never had a managed interpreter has no parity to lose; convicting it "
        "makes parity-unverified permanent noise and the stamp gets ignored"
    )


def test_the_two_edges_disagree_so_the_predicate_is_doing_real_work(tmp_path, monkeypatch):
    """The pair pinned together, because each alone is satisfiable by a constant: a predicate
    hardwired True passes the no-interpreter case, hardwired False passes the hollow-pin case.
    Only both at once require it to actually ask the question."""
    _fake_app_data(monkeypatch, tmp_path, make_dirs=True)
    hollow = tmp_path / "hollow"
    hollow.mkdir()
    real = _managed_root(tmp_path / "elsewhere")

    assert not grade_env.uv_parity_is_vouched({"UV_PYTHON_INSTALL_DIR": str(hollow)})
    assert grade_env.uv_parity_is_vouched({"UV_PYTHON_INSTALL_DIR": str(real)})


# ---------------------------------------------------------------------------
# #1374 — the coverage map used to be gated on `_HARD_CLASSES` being empty, which
# meant `adequacy_floor` suppressed it. Measured 2026-08-10: every B9 run reported
# `adequacy_floor: 2`, so the requirement→assertion map was skipped on EVERY run
# that had ever happened and DoD capability 17 had no data at all.
#
# The old guard is right for oracles that cannot be collected, parsed or driven.
# It is wrong for a THIN oracle, which parses fine — and a thin exam is exactly
# when you most want to know which of the operator's requirements nobody asserted.
# That is #1342, where an exam that could not fail deleted a page he asked for.
# ---------------------------------------------------------------------------

#: A THIN oracle by the adequacy floor's own definition: it imports a first-party module
#: and no test EXERCISES a first-party symbol (no assertion on one, no no-raise call).
#: It parses and collects perfectly well — which is the whole point. Its requirements CAN
#: be traced, and tracing them is the most useful thing anyone could do with it.
#: (`_VACUOUS_ASSERT` above is exactly this shape; aliased so the intent reads locally.)
_THIN_ORACLE = _VACUOUS_ASSERT


def _coverage_spy(map_dict):
    """structured_generate_fn that RECORDS whether the coverage map was requested."""
    seen: list[str] = []

    def structured(prompt, schema):
        if "list the test function name" in prompt:
            seen.append(prompt)
            return json.dumps(map_dict)
        return ""

    return structured, seen


def test_a_THIN_oracle_still_gets_its_requirement_map_measured():
    """The #1374 fix: adequacy_floor must no longer suppress the coverage map."""
    crits = [_crit("c2", "sums expenses")]
    structured, seen = _coverage_spy({"c2": ["test_it_runs"]})
    result = oq.validate_authored_oracle(
        _THIN_ORACLE, "python", _spec(*crits), _tasks(),
        generate_fn=lambda p: "", structured_generate_fn=structured,
    )
    assert any(f.cls == oq.CLASS_ADEQUACY_FLOOR for f in result.findings), (
        "precondition: this oracle must trip the adequacy floor, or the test proves nothing"
    )
    assert seen, (
        "the requirement-to-assertion map must be REQUESTED on a thin oracle — this is the "
        "case capability 17 exists for, and it was silently skipped before #1374"
    )
    assert result.coverage_denominator > 0, "coverage must be MEASURED, not reported unknown"
    assert result.stage_measured()[oq.STAGE_COVERAGE] is True


def test_the_blocking_set_is_exactly_the_untraceable_classes():
    """Gate on what a finding MEANS, not on its severity.

    A thin or vacuous oracle parses; an uncollectable or ill-posed one does not. Only the
    second kind makes a map impossible, and this locks that distinction so a future edit
    cannot quietly fold `adequacy_floor` back in and re-suppress the measurement.
    """
    assert oq._COVERAGE_BLOCKING_CLASSES == frozenset({
        oq.CLASS_COLLECTABILITY, oq.CLASS_STRATEGY, oq.CLASS_INTERACTIVE_IO,
    })
    for thin in (oq.CLASS_ADEQUACY_FLOOR, oq.CLASS_F2P_VACUOUS):
        assert thin in oq._HARD_CLASSES, "still HARD — the oracle is still refused"
        assert thin not in oq._COVERAGE_BLOCKING_CLASSES, (
            f"{thin} means the exam is too THIN, not untraceable; it must not suppress the map"
        )


def test_an_ILLPOSED_oracle_still_skips_the_map(pytestconfig):
    """The half of the original guard that was right, kept.

    You cannot trace assertions through an oracle whose strategy is ill-posed, and paying
    for a model call each round to rediscover that is the waste the guard was written for.
    """
    crits = [_crit("c2", "sums expenses")]
    structured, seen = _coverage_spy({"c2": ["test_total"]})
    result = oq.validate_authored_oracle(
        _ILLPOSED_STRATEGY, "python", _spec(*crits), _tasks(),
        generate_fn=lambda p: "", structured_generate_fn=structured,
    )
    if not any(f.cls == oq.CLASS_STRATEGY for f in result.findings):
        pytest.skip("fixture no longer trips the strategy class; the lock below needs it")
    assert not seen, "an untraceable oracle must NOT pay for a coverage map"
    assert result.coverage_fraction() == "unknown"


def test_toggle_proof_the_guard_split_is_what_measures_coverage():
    """security_by_design principle 12 — prove the probe FAILS when the control is off.

    Restores the pre-#1374 guard (block on every HARD class) and shows the SAME thin
    oracle goes back to reporting `unknown`. Without this, a green suite cannot tell
    "capability 17 is measured" from "the assertion cannot reach the thing it checks".

    The two answers are the whole point, and they are #1342's distinction exactly:

        with the fix  -> coverage "0/1"      (MEASURED: it covers none of his criteria)
        without it    -> coverage "unknown"  (NOT measured: nobody looked)
    """
    crits = [_crit("c2", "sums expenses")]

    def measure():
        structured, seen = _coverage_spy({"c2": ["test_math"]})
        r = oq.validate_authored_oracle(
            _THIN_ORACLE, "python", _spec(*crits), _tasks(),
            generate_fn=lambda p: "", structured_generate_fn=structured,
        )
        return bool(seen), r.coverage_fraction()

    asked_now, cov_now = measure()
    assert asked_now and cov_now == "0/1", (
        f"precondition: the fix must MEASURE zero coverage on a thin oracle (got {cov_now})"
    )

    original = oq._COVERAGE_BLOCKING_CLASSES
    try:
        oq._COVERAGE_BLOCKING_CLASSES = oq._HARD_CLASSES   # the pre-#1374 guard
        asked_then, cov_then = measure()
    finally:
        oq._COVERAGE_BLOCKING_CLASSES = original

    assert not asked_then and cov_then == "unknown", (
        "with the old guard restored the map must NOT be requested and coverage must read "
        f"unknown — got requested={asked_then}, coverage={cov_then}. If it still measures, "
        "something else is doing the work and this guard is not what protects us."
    )
    assert measure() == (True, "0/1"), "the control must be restored"


# ---------------------------------------------------------------------------
# #1200, third lock: colour must not blind the readers (measured 2026-08-15)
# ---------------------------------------------------------------------------

_COLOURED_PASS = (
    "\x1b[1m============================= test session starts "
    "=============================\x1b[0m\n"
    "collected 1 item\n\n"
    "_qa_f2p_probe.py::test_always_green \x1b[32mPASSED\x1b[0m\x1b[32m       [100%]\x1b[0m\n\n"
    "\x1b[32m============================== \x1b[32m\x1b[1m1 passed\x1b[0m\x1b[32m "
    "in 0.44s\x1b[0m\x1b[32m ==============================\x1b[0m\n"
)


def test_a_coloured_PASSED_line_is_still_read_per_test():
    """The defect, reduced to the parse. With FORCE_COLOR set in the parent environment the
    escape sits between the test name and PASSED, so the per-test matcher missed and a
    VACUOUS oracle — one that passes with no implementation present — was stamped `not-run`
    rather than convicted. Measured end to end before this lock existed."""
    assert oq._passed_tests(_COLOURED_PASS) == ["test_always_green"]


def test_a_summary_whose_COUNT_PHRASE_is_interrupted_still_counts_as_a_completed_run():
    """DEFENCE IN DEPTH, and labelled as such because the honest version is less dramatic.

    On real coloured output `_run_completed` was NOT blinded: pytest wraps its escapes
    around `1 passed`, leaving the count phrase contiguous, so the anchors still matched.
    I wrote a lock against `_COLOURED_PASS` first and it passed with the strip DISABLED —
    a vacuous test asserting a defect that was never there. Kept, rearmed against a genuinely
    hostile shape: an escape INSIDE the phrase, which nothing produces today and which the
    matcher must survive anyway, since its correctness otherwise rests on where a third party
    chooses to put its escapes."""
    interrupted = "===== 1\x1b[0m passed\x1b[32m in 0.44s =====\n"
    assert oq._run_completed(interrupted) is True


def test_stripping_colour_did_NOT_loosen_the_anchoring():
    """Precision, and the reason the fix strips rather than widens.

    `_run_completed`'s patterns are deliberately anchored on shapes only pytest emits,
    because a uv network error containing the word "failed" once read as a completed run
    with nothing passing — i.e. CLEAN — from a run that never executed a test. Removing
    decoration must not resurrect that: the same error, coloured, must still be refused."""
    coloured_network_error = (
        "\x1b[31merror\x1b[0m: Failed to fetch: `https://pypi.org/simple/pytest/`\n"
        "  Caused by: Request failed after 3 retries\n"
    )
    assert oq._run_completed(coloured_network_error) is False
    assert oq._passed_tests(coloured_network_error) == []


def test_the_plain_uncoloured_shapes_are_unaffected():
    """The toggle. If the strip had broken plain parsing, every real battery run — which is
    uncoloured — would have regressed while these colour tests stayed green."""
    plain = ("_qa_f2p_probe.py::test_always_green PASSED   [100%]\n"
             "============================== 1 passed in 0.44s ==============================\n")
    assert oq._passed_tests(plain) == ["test_always_green"]
    assert oq._run_completed(plain) is True
