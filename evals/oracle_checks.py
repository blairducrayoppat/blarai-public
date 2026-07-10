"""
Eval Harness — Oracle-Quality Check Engine (#765)
==================================================
The deterministic half of the oracle-quality measurement: given an oracle's
SOURCE TEXT (the 14B-written acceptance-test file — per-task #690 or
job-level W4), this module answers two kinds of question with no model in
the loop:

  * STATIC findings — is the oracle structurally trustworthy? (real test
    functions with real assertions; no degenerate ``assert True`` bodies;
    no module-level skip; imports parseable.)

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
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
