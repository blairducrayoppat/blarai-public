"""#752 F3 — the per-task acceptance oracle and the coder must AGREE on the module layout.

The seeded python skeleton pins the coder to the ``app`` package (the ``agentic-setup``
build-infra reference seeds ``app/__init__.py`` + ``app/core.py``, and its ``tests/test_core.py``
does ``from app.core import summarize``). Before F3 the 14B-authored oracle was told to import
from "a clearly-named module you choose (for example ``from calendar_math import add_days``)", so
it invented a top-level module the coder never created -> ``ModuleNotFoundError`` at pytest
collection -> the oracle never ran and the job scored RED on import-plumbing, not the coder's
logic (B2's exact failure).

F3 closes the loop from BOTH ends and this file locks both halves:

  (a) ``_ORACLE_TEMPLATE`` now tells the model to import from the already-present ``app`` package
      and NOT to invent a new top-level module (``test_oracle_template_pins_the_model_to_app``); and
  (b) ``compile_prompts`` parses the concrete import symbols out of the generated oracle and
      states them to the coder as a HARD public-API requirement, so even if the oracle's names
      drift the coder builds exactly what the protected file imports
      (``test_compile_prompts_surfaces_the_concrete_import_contract`` +
      ``test_import_contract_closes_the_loop_even_when_oracle_names_drift``).
"""
from __future__ import annotations

import ast

from shared.fleet.acceptance import (
    ACCEPTANCE_ORACLE_PATH,
    AcceptanceCriterion,
    AcceptanceSpec,
    _oracle_import_contract,
    compile_prompts,
    generate_acceptance_oracle,
)

#: A python build-signal (language_hint=python) so the #690 single-feature oracle path fires.
_PY_SPEC = AcceptanceSpec(
    goal="text stats",
    criteria=(AcceptanceCriterion("c1", "word_count('a b c') is 3", "behavior", ""),),
    build_plan={
        "surface": "command-line",
        "language_hint": "python",
        "complexity": "simple",
        "components": [],
    },
)


def test_oracle_template_pins_the_model_to_app():
    # (a) The prompt that has the 14B author the oracle must instruct importing from the
    # already-seeded `app` package and forbid inventing a new top-level module (the pre-F3
    # `calendar_math`-style invention was B2's import-plumbing RED). The model output below is
    # faked; the durable lock is the INSTRUCTION, which is what steers the real 14B.
    captured: dict[str, str] = {}

    def gen(prompt: str) -> str:
        captured["p"] = prompt
        return (
            "from app.core import word_count\n\n"
            "def test_counts_words():\n"
            "    assert word_count('a b c') == 3\n"
        )

    code = generate_acceptance_oracle(
        "text stats", _PY_SPEC,
        [{"prompt": "Implement word_count(text) -> int"}],
        generate_fn=gen,
    )

    # the generated oracle imports from `app`, not an invented top-level module
    assert "from app.core import word_count" in code
    roots = {
        (n.module or "").split(".", 1)[0]
        for n in ast.walk(ast.parse(code))
        if isinstance(n, ast.ImportFrom)
    }
    assert "app" in roots
    assert "calendar_math" not in roots and "text_analyzer" not in roots

    # and the PROMPT itself pins `app` + forbids a second top-level module.
    # The pinned example is the generic `from app.<module> import <fn>` form:
    # the neutral seed (#1048) retired `app/core.py`, so no single module is
    # canonical — the durable contract is the app-package pin, not one name.
    prompt = captured["p"]
    assert "from app.<module> import" in prompt
    assert "top-level module" in prompt          # the explicit "do NOT invent a new top-level module"
    assert "calendar_math" in prompt             # named only as the FORBIDDEN example now
    # spec-blind routing guard preserved (must not collide with the criteria-proposal prompt)
    assert "ACCEPTANCE CRITERIA" not in prompt


def test_compile_prompts_surfaces_the_concrete_import_contract():
    # (b) The coder prompt must state the EXACT importable names the protected oracle imports,
    # as a hard requirement -- so the coder's public API matches what the acceptance file
    # collects (no ModuleNotFoundError at pytest collection).
    oracle = (
        "from app.core import word_count, char_count\n\n"
        "def test_words():\n    assert word_count('a b') == 2\n\n"
        "def test_chars():\n    assert char_count('ab') == 2\n"
    )
    out = compile_prompts(
        [{"repo": "R", "task": "only", "prompt": "build text stats"}],
        _PY_SPEC,
        oracle_code=oracle,
    )
    assert len(out) == 1
    prompt = out[0]["prompt"]

    # the concrete symbols are surfaced as a HARD contract, pointed at the `app` package
    assert "app.core.word_count" in prompt
    assert "app.core.char_count" in prompt
    assert "MUST provide" in prompt
    assert "app` package" in prompt              # steered back into the seeded package

    # existing #690 protections preserved (protected oracle, restored before grade)
    assert prompt.startswith("build text stats")
    assert "DO NOT EDIT" in prompt and ACCEPTANCE_ORACLE_PATH in prompt
    assert "Write automated tests" not in prompt  # codes against the oracle, does not write its own
    assert out[0]["acceptance_test_code"] == oracle
    assert out[0]["acceptance_test_path"] == ACCEPTANCE_ORACLE_PATH


def test_import_contract_closes_the_loop_even_when_oracle_names_drift():
    # Belt-and-braces: if the model IGNORES (a) and still invents a top-level module, (b) STILL
    # surfaces that exact name to the coder, so the two AGREE and the oracle can be COLLECTED --
    # the loop closes from the compile side regardless of the model's drift.
    drifted = (
        "from text_analyzer import analyze\n\n"
        "def test_analyze():\n    assert analyze('hi')['words'] == 1\n"
    )
    prompt = compile_prompts(
        [{"repo": "R", "task": "only", "prompt": "build it"}],
        _PY_SPEC,
        oracle_code=drifted,
    )[0]["prompt"]
    assert "text_analyzer.analyze" in prompt
    assert "MUST provide" in prompt
    # a drifted (non-app) contract must NOT falsely claim the symbol lives in `app`
    assert "app` package" not in prompt


def test_compile_prompts_surfaces_call_signatures_rec1_v3():
    # #826 rec-1 v3: the coder is shown the CALL SIGNATURES the oracle uses (arity +
    # keywords), not just the importable names — so the built callable accepts the exact
    # call the acceptance file makes (the B4n2 park was a one-arg build vs a two-arg call).
    oracle = (
        "from app.core import check_answer\n\n"
        "def test_quiz():\n    assert check_answer('cat', 'cat') == 'correct'\n"
    )
    prompt = compile_prompts(
        [{"repo": "R", "task": "only", "prompt": "build quiz"}],
        _PY_SPEC, oracle_code=oracle,
    )[0]["prompt"]
    assert "argument shapes" in prompt
    assert "check_answer(2 positional args)" in prompt
    # additive: the existing importable-names contract is still present (byte-preserved).
    assert "app.core.check_answer" in prompt and "MUST provide" in prompt


def test_compile_prompts_no_signature_line_when_no_calls():
    # An oracle that imports but never CALLS a first-party callable → no signature line
    # (byte-identical to the pre-#826 prompt for that shape).
    oracle = (
        "from app.core import CONSTANT\n\n"
        "def test_const():\n    assert CONSTANT == 3\n"
    )
    prompt = compile_prompts(
        [{"repo": "R", "task": "only", "prompt": "build it"}],
        _PY_SPEC, oracle_code=oracle,
    )[0]["prompt"]
    assert "argument shapes" not in prompt
    assert "app.core.CONSTANT" in prompt  # the import contract still surfaces


def test_oracle_import_contract_parser_shapes():
    # Unit-level: the parser extracts first-party symbols and drops test-runner/stdlib deps.
    code = (
        "import pytest\n"
        "import math\n"
        "from hypothesis import given, strategies as st\n"
        "from app.core import summarize, mean\n"
        "from app.stats import median\n"
        "import app.util\n"
        "def test_x():\n    assert summarize([]) == {}\n"
    )
    contract = _oracle_import_contract(code)
    assert contract == [
        "app.core.summarize",
        "app.core.mean",
        "app.stats.median",
        "app.util",
    ]
    # order-preserving + de-duplicated, stdlib/pytest/hypothesis excluded
    assert "math" not in " ".join(contract)
    assert "hypothesis.given" not in contract and "pytest" not in " ".join(contract)

    # fail-soft: junk that will not parse -> [] (generic guidance still stands)
    assert _oracle_import_contract("def broken( :::") == []
    assert _oracle_import_contract("") == []

    # relative imports (inside tests/) are not public modules -> skipped
    assert _oracle_import_contract("from . import helper\ndef test_a():\n    pass\n") == []
