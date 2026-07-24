"""#821 (QUALITY-3) — oracle-QA locks.

Every taxonomy defect class is a fixture (the ill-posed strategy B1n2, the invented
contract + interactive-IO B4, the ``sys.listdir`` no-raise smoke B6), plus the
FAIL-TO-PASS vacuous case, the traceability unmapped-criterion case, the no-raise
adequacy-floor case, the regeneration accounting, and the evidence-stamp shape. The
model calls + subprocesses are faked throughout (offline; the live 14B/subprocess proof
rides the next live dispatch), so the whole gate runs model-free and subprocess-free.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.fleet import acceptance as acc
from shared.fleet import clarify as clr
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


def test_confirm_collectable_structural_defect_flags():
    run = _fake_run(out="E   hypothesis.errors.InvalidArgument: min_value > max_value")
    stamp, finding = oq.confirm_collectable(_ILLPOSED_STRATEGY, run=run)
    assert stamp == "unconfirmed" and finding is not None
    assert finding.cls == oq.CLASS_COLLECTABILITY


def test_confirm_collectable_import_miss_is_no_finding():
    # A stub-synthesis miss must NEVER false-park a valid oracle.
    run = _fake_run(out="E   ModuleNotFoundError: No module named 'expense'")
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


def test_validate_node_oracle_skips_deep_qa():
    result = oq.validate_authored_oracle(
        "import test from 'node:test';\ntest('x', () => {});", "node",
        _spec(_crit("c2", "x")), _tasks(), generate_fn=lambda p: "")
    assert result.verdict == "seed"
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
