"""
Eval Harness — Oracle-Quality Check Engine (#765)
==================================================
The deterministic half of the oracle-quality measurement: given an oracle's
SOURCE TEXT (the 14B-written acceptance-test file — per-task #690 or
job-level W4), this module answers four kinds of question with no model in
the loop:

  * STATIC findings — is the oracle structurally trustworthy? (real test
    functions with real assertions; no degenerate ``assert True`` bodies;
    no module-level skip; imports parseable.)

  * CONTRACT findings — does the oracle import only first-party symbols the
    job's declared task contracts actually export (the #752-F3 class: "the
    seeded per-task oracle does `from text_analyzer import analyze_text`;
    the coder named its module differently"). This is a THIN WRAPPER over
    the real production check (:func:`shared.fleet.oracle_qa.
    scan_invented_contracts`, #821 ``CLASS_INVENTED_CONTRACT``) — the eval
    suite measures the SAME logic the live dispatch fleet's authorship-time
    QA gate runs, never a parallel implementation that could drift from it.

  * CRITERIA-COVERAGE findings — does every ``[behavior]``/``[smoke]``
    acceptance criterion map to at least one test in the oracle? This is a
    deliberately SEPARATE, self-contained lexical heuristic (keyword overlap
    between a criterion's text/check and each test function's name+body) —
    NOT the production #821 ``verify_traceability`` matrix, which verifies a
    MODEL-DECLARED coverage map and therefore cannot run model-free. See
    :func:`criteria_coverage_findings` for the exact rule and its documented
    blind spot (a same-behavior paraphrase with disjoint vocabulary reads as
    uncovered — a coarse LEXICAL match, not semantic understanding).

  * EXECUTION outcome — what happens when the oracle runs against a given
    implementation tree? The vocabulary matters more than the boolean:
    ``passed`` / ``failed`` / ``collection-error`` / ``timeout`` / ``crash``.
    ``collection-error`` is the #752-F3 plumbing class (the oracle could not
    even import the code it grades) — a VERIFY-side defect signal that must
    never be read as a coder-capability datum. This is the same failure-mode
    vocabulary #765 Layer 2 adds to live scorecard evidence.

The soundness/sensitivity semantics live in the golden cases, not here:
  soundness    — a trustworthy oracle MUST ``pass`` against the frozen
                 known-good reference implementation (a failure means the
                 oracle punishes correct code).
  sensitivity  — the same oracle MUST ``fail`` against a deliberately
                 broken mutant of that reference (a pass means the oracle
                 cannot catch the break it exists to catch).

Mutations are APPEND-OVERRIDE transforms: appending a later ``def`` of the
same name to a module makes the broken definition win at import time,
deterministically, regardless of the module's internal implementation.
Mutations are applied to a TEMP COPY only — fixtures are never modified.

The executor runs ``python -m pytest`` as a subprocess in the temp copy.
The reference apps are plain generated CLI projects (no BlarAI imports), so
no LOCALAPPDATA isolation question arises; the subprocess still runs with
``-p no:cacheprovider`` and a scoped cwd so nothing writes outside the temp
tree.
"""

from __future__ import annotations

import ast
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Reused, not reimplemented: the real #821 authorship-time QA check for the
# #752-F3 import/contract class. shared.fleet.oracle_qa is pure-Python and
# model-free (verified: no torch/openvino/genai import anywhere under
# shared/fleet/, and evals/plan_calibration.py already imports
# shared.fleet.dispatch — the same cross-package reuse precedent).
from shared.fleet.oracle_qa import scan_invented_contracts

#: Execution-outcome vocabulary (mirrors #765 Layer 2's scorecard evidence values).
RUN_PASSED = "passed"
RUN_FAILED = "failed"
RUN_COLLECTION_ERROR = "collection-error"
RUN_TIMEOUT = "timeout"
RUN_CRASH = "crash"

#: Static-finding flags (stable identifiers the golden cases assert on).
FLAG_NO_TESTS = "no-tests"
FLAG_DEGENERATE_ASSERT = "degenerate-assert"
FLAG_MODULE_SKIP = "module-skip"
FLAG_LOW_ASSERTIONS = "low-assertions"
FLAG_SYNTAX_ERROR = "syntax-error"

#: Contract-finding flag: a first-party import the job's declared task
#: contracts never export (the #752-F3 class).
FLAG_IMPORT_NOT_IN_CONTRACT = "import-not-in-contract"

#: Criteria-coverage flag: at least one test-tier ([behavior]/[smoke])
#: criterion has no test that lexically overlaps it.
FLAG_UNCOVERED_CRITERIA = "uncovered-criteria"

#: A test function with fewer real assertions than this is flagged low.
_MIN_ASSERTS_PER_TEST = 1

#: The oracle is written to this fresh name in the temp copy so the run never
#: collides with a reference tree's own test files (only THIS file is run).
_ORACLE_EVAL_RELPATH = "tests/test_oracle_eval.py"


@dataclass(frozen=True)
class OracleRunResult:
    """Outcome of executing one oracle against one implementation tree."""

    status: str                 # one of the RUN_* vocabulary values
    detail: str = ""            # short classifier note (never a raw log dump)
    returncode: int | None = None


@dataclass(frozen=True)
class StaticFindings:
    """Deterministic structural findings for one oracle source text."""

    test_count: int = 0
    assert_counts: dict[str, int] = field(default_factory=dict)
    flags: tuple[str, ...] = ()
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_count": self.test_count,
            "assert_counts": dict(self.assert_counts),
            "flags": list(self.flags),
            "detail": self.detail,
        }


def _is_degenerate_assert(node: ast.Assert) -> bool:
    """True for ``assert True`` / ``assert 1`` — an assertion that can never fail."""
    test = node.test
    return isinstance(test, ast.Constant) and bool(test.value) is True


def static_oracle_findings(oracle_code: str) -> StaticFindings:
    """Structural trust checks over the oracle SOURCE (no execution).

    Fail-closed: unparseable source is itself a finding (``syntax-error``),
    never an exception — a malformed oracle must surface as a measured
    defect, not a harness crash.
    """
    try:
        tree = ast.parse(oracle_code)
    except SyntaxError as exc:
        return StaticFindings(flags=(FLAG_SYNTAX_ERROR,), detail=f"SyntaxError: {exc.msg}")

    flags: list[str] = []
    assert_counts: dict[str, int] = {}

    # Module-level skip: pytest.skip(..., allow_module_level=True) anywhere at
    # module scope means the oracle never grades anything (the seed-guard shape
    # leaking into plan-carried bytes would be exactly this defect).
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            func = node.value.func
            name = (
                func.attr if isinstance(func, ast.Attribute)
                else func.id if isinstance(func, ast.Name)
                else ""
            )
            if name == "skip":
                flags.append(FLAG_MODULE_SKIP)
                break

    degenerate = False
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            asserts = [n for n in ast.walk(node) if isinstance(n, ast.Assert)]
            assert_counts[node.name] = len(asserts)
            if any(_is_degenerate_assert(a) for a in asserts):
                degenerate = True

    if not assert_counts:
        flags.append(FLAG_NO_TESTS)
    if degenerate:
        flags.append(FLAG_DEGENERATE_ASSERT)
    if assert_counts and any(c < _MIN_ASSERTS_PER_TEST for c in assert_counts.values()):
        flags.append(FLAG_LOW_ASSERTIONS)

    return StaticFindings(
        test_count=len(assert_counts),
        assert_counts=assert_counts,
        flags=tuple(flags),
    )


# ---------------------------------------------------------------------------
# Contract findings — the #752-F3 class (imports satisfiable against the
# declared job contract). A thin wrapper over the real #821 production check.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ContractFindings:
    """Whether the oracle's first-party imports stay within the job's
    declared task contracts (union of every task's ``contract.exports``,
    #740 W2 shape). Empty ``declared_exports`` is a caller error here (the
    eval case always supplies one) — production code's own fail-soft-empty
    behavior lives in :func:`shared.fleet.oracle_qa.scan_invented_contracts`
    and is preserved (an empty contract simply finds nothing, never raises).
    """

    flags: tuple[str, ...] = ()
    invented_symbols: tuple[str, ...] = ()
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "flags": list(self.flags),
            "invented_symbols": list(self.invented_symbols),
            "detail": self.detail,
        }


def contract_import_findings(
    oracle_code: str, declared_exports: "list[str] | tuple[str, ...] | set[str]"
) -> ContractFindings:
    """The #752-F3 static check: does the oracle import a first-party NAME
    (``from <module> import <name>``) that no task's declared ``contract.
    exports`` actually promises? An oracle importing a symbol the contract
    never exports is a defect — the coder was never told to build it, so
    collection fails on plumbing, not logic, and a real coder failure is
    indistinguishable from a VERIFY-side defect (BUILD_JOURNAL 2026-07-07,
    "Measuring the judge").

    Delegates to :func:`shared.fleet.oracle_qa.scan_invented_contracts` — the
    SAME AST walk the live dispatch fleet's authorship-time QA gate (#821)
    runs before a job oracle seeds — so this eval measures production
    behavior verbatim rather than a second, possibly-drifting heuristic.
    Fail-closed: unparseable source yields no importable symbols (the upstream
    ``_first_party_imports`` catches ``SyntaxError``/``ValueError`` and
    returns ``[]``), so a syntax-broken oracle reads as contract-clean here —
    :func:`static_oracle_findings` is the check that catches that class; this
    function answers ONLY the import/contract question."""
    exports = {str(e) for e in declared_exports}
    findings = scan_invented_contracts(oracle_code, exports)
    symbols = tuple(f.subject for f in findings)
    flags = (FLAG_IMPORT_NOT_IN_CONTRACT,) if symbols else ()
    detail = "; ".join(f.message for f in findings) if findings else ""
    return ContractFindings(flags=flags, invented_symbols=symbols, detail=detail)


# ---------------------------------------------------------------------------
# Criteria-coverage findings — a self-contained lexical heuristic (NOT the
# production #821 verify_traceability matrix, which verifies a MODEL-
# DECLARED coverage map and so cannot run model-free; see the module
# docstring).
# ---------------------------------------------------------------------------

#: Criterion tiers whose text becomes coder test-writing instructions —
#: mirrors ``shared.fleet.acceptance.TEST_TIERS`` (duplicated as a small,
#: stable 2-value vocabulary rather than imported, so this module's only
#: cross-package coupling stays the one deliberate reuse above).
_CRITERIA_TEST_TIERS: frozenset[str] = frozenset({"behavior", "smoke"})

#: A criterion counts as COVERED by a test when at least this many of the
#: criterion's significant words also appear in that test's name+body
#: (floored to the criterion's own word count when it has fewer). Low by
#: design: this is a coarse LEXICAL heuristic (exact-token overlap, no
#: stemming/synonyms), not semantic understanding — see
#: :func:`criteria_coverage_findings`.
_MIN_KEYWORD_OVERLAP = 2

#: Short/grammatical words dropped before matching — carry no domain content
#: and would otherwise inflate overlap between unrelated criterion/test pairs.
_STOPWORDS: frozenset[str] = frozenset({
    "the", "an", "and", "are", "was", "were", "been", "being", "its", "that",
    "this", "these", "those", "into", "for", "with", "when", "then", "should",
    "must", "can", "will", "shall", "not", "does", "each", "your", "you",
})

_WORD_RE = re.compile(r"[a-z0-9]+")


def _significant_words(text: str) -> set[str]:
    """Lowercased, punctuation-split (underscores split too — a regex over
    ``[a-z0-9]+`` treats ``word_frequencies`` as two tokens, which is what
    lets a snake_case test name overlap a plain-English criterion), with
    stopwords and sub-3-character tokens dropped."""
    words = _WORD_RE.findall(text.lower())
    return {w for w in words if len(w) >= 3 and w not in _STOPWORDS}


@dataclass(frozen=True)
class CriteriaCoverageFindings:
    """Per-criterion lexical coverage verdict over one oracle."""

    flags: tuple[str, ...] = ()
    covered: tuple[str, ...] = ()
    uncovered: tuple[str, ...] = ()
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "flags": list(self.flags),
            "covered": list(self.covered),
            "uncovered": list(self.uncovered),
            "detail": self.detail,
        }


def criteria_coverage_findings(
    oracle_code: str, criteria: "list[dict[str, Any]]"
) -> CriteriaCoverageFindings:
    """Deterministic, offline HEURISTIC answering: does each ``[behavior]``/
    ``[smoke]`` acceptance criterion map to >=1 test in the oracle?

    Each ``criteria`` item is an ``AcceptanceCriterion``-shaped dict
    (``shared.fleet.acceptance.AcceptanceCriterion.to_dict()``):
    ``{"id": ..., "text": ..., "tier": ..., "check": ...}`` — the exact shape
    (and the ``- [tier] text (check: ...)`` rendering) the real
    ``generate_acceptance_oracle`` / job-level W4 prompts already use, so a
    caller can pass a spec's real criteria unmodified.

    Rule (documented, not hidden): tokenize each test-tier criterion's
    ``text + check`` into significant words (:func:`_significant_words`);
    tokenize every ``def test*`` function's full source (name + body) the
    same way. A criterion is COVERED iff at least one test shares
    ``min(2, len(criterion_words))`` or more words with it. Criteria outside
    :data:`_CRITERIA_TEST_TIERS` (visual/human) are ignored — never counted
    covered or uncovered — mirroring
    :attr:`shared.fleet.acceptance.AcceptanceSpec.human`'s carve-out (only an
    operator can judge those).

    KNOWN LIMITATION (pinned by a golden case, not swept under the rug): this
    is exact-token lexical overlap — no stemming, no synonyms. A test that
    correctly covers a criterion but is phrased with disjoint vocabulary (a
    genuine paraphrase) reads as uncovered. That is the documented boundary
    of "heuristic keyword/structure match" (#765); closing it needs either
    stemming or the model-assisted #821 traceability matrix, not this
    function.

    Fail-closed: unparseable oracle source returns the ``syntax-error`` flag
    (mirroring :func:`static_oracle_findings`) rather than silently reporting
    every criterion covered or uncovered."""
    try:
        tree = ast.parse(oracle_code)
    except SyntaxError as exc:
        return CriteriaCoverageFindings(
            flags=(FLAG_SYNTAX_ERROR,), detail=f"SyntaxError: {exc.msg}"
        )

    test_word_sets: list[set[str]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            segment = ast.get_source_segment(oracle_code, node) or node.name
            test_word_sets.append(_significant_words(segment))

    covered: list[str] = []
    uncovered: list[str] = []
    for c in criteria:
        tier = str(c.get("tier", ""))
        if tier not in _CRITERIA_TEST_TIERS:
            continue
        label = str(c.get("id") or c.get("text") or "criterion")
        crit_words = _significant_words(str(c.get("text", "")) + " " + str(c.get("check", "")))
        needed = min(_MIN_KEYWORD_OVERLAP, len(crit_words))
        is_covered = bool(crit_words) and needed > 0 and any(
            len(crit_words & tw) >= needed for tw in test_word_sets
        )
        (covered if is_covered else uncovered).append(label)

    flags = (FLAG_UNCOVERED_CRITERIA,) if uncovered else ()
    detail = (
        f"covered={covered} uncovered={uncovered}"
        if (covered or uncovered) else "no test-tier criteria supplied"
    )
    return CriteriaCoverageFindings(
        flags=flags, covered=tuple(covered), uncovered=tuple(uncovered), detail=detail
    )


def _apply_mutations(root: Path, mutations: "list[dict] | tuple[dict, ...]") -> None:
    """Apply append-override mutations to the TEMP copy (never a fixture).

    Each mutation is ``{"file": "<relpath>", "append": "<python source>"}``;
    appending a later definition of the same name makes the broken definition
    win at import time. A mutation naming a missing file is a harness error —
    raise (the golden case is wrong, and a silently unapplied mutation would
    turn a sensitivity case into a false pass).
    """
    for m in mutations or ():
        rel = str(m["file"])
        target = root / rel
        if not target.is_file():
            raise FileNotFoundError(f"mutation target missing in reference: {rel}")
        with target.open("a", encoding="utf-8") as fh:
            fh.write("\n\n# --- oracle-quality sensitivity mutation (eval-injected) ---\n")
            fh.write(str(m["append"]).rstrip() + "\n")


def _classify(returncode: int, output: str) -> OracleRunResult:
    """Map a pytest subprocess outcome onto the RUN_* vocabulary.

    pytest exit codes: 0 all passed; 1 tests failed; 2 interrupted (includes
    collection errors); 3 internal error; 4 usage error; 5 no tests collected.
    The text check is the belt for the rc=2 ambiguity — a collection error
    prints ``ERROR`` + ``error`` markers during collection.
    """
    if returncode == 0:
        return OracleRunResult(status=RUN_PASSED, returncode=0)
    low = output.lower()
    collectish = ("errors during collection" in low or "error collecting" in low
                  or "collection error" in low)
    if returncode in (2, 5) or (collectish and returncode != 1):
        detail = "no tests collected" if returncode == 5 else "collection error"
        return OracleRunResult(status=RUN_COLLECTION_ERROR, detail=detail, returncode=returncode)
    if returncode == 1:
        return OracleRunResult(status=RUN_FAILED, detail="assertion failure(s)", returncode=1)
    return OracleRunResult(status=RUN_CRASH, detail=f"pytest exit {returncode}", returncode=returncode)


def run_oracle_against(
    reference_dir: Path,
    oracle_code: str,
    *,
    mutations: "list[dict] | tuple[dict, ...]" = (),
    timeout_s: float = 120.0,
) -> OracleRunResult:
    """Execute *oracle_code* against a temp copy of *reference_dir*.

    Copies the reference implementation, applies any sensitivity mutations,
    writes the oracle to a fresh test file, and runs ONLY that file via
    ``python -m pytest``. Returns the classified outcome; the temp tree is
    always removed. Fail-closed: any harness-side exception maps to CRASH
    (an unevaluable oracle is never a silent pass).
    """
    tmp = Path(tempfile.mkdtemp(prefix="oracle-eval-"))
    try:
        shutil.copytree(reference_dir, tmp, dirs_exist_ok=True)
        _apply_mutations(tmp, mutations)
        oracle_file = tmp / _ORACLE_EVAL_RELPATH
        oracle_file.parent.mkdir(parents=True, exist_ok=True)
        oracle_file.write_text(oracle_code, encoding="utf-8")
        proc = subprocess.run(  # noqa: S603 — fixed argv, no shell, temp cwd
            [sys.executable, "-m", "pytest", _ORACLE_EVAL_RELPATH,
             "-q", "-p", "no:cacheprovider"],
            cwd=str(tmp), capture_output=True, text=True, timeout=timeout_s,
        )
        return _classify(proc.returncode, (proc.stdout or "") + (proc.stderr or ""))
    except subprocess.TimeoutExpired:
        return OracleRunResult(status=RUN_TIMEOUT, detail=f"exceeded {timeout_s:.0f}s")
    except FileNotFoundError:
        # A bad mutation spec is a golden-data defect — surface it loudly.
        raise
    except Exception as exc:  # noqa: BLE001 — fail-closed: unevaluable is never a pass
        return OracleRunResult(status=RUN_CRASH, detail=f"harness: {exc}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
