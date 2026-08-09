"""QA for the CODER'S OWN tests — the exam the candidate wrote for itself.

:mod:`shared.fleet.oracle_qa` validates the SEALED job oracle: an exam authored away
from the coder, restored from a clean copy before grading, which the coder codes toward
but can never edit. That machinery is rigorous and it works. It has one blind spot, and
2026-07-29 walked straight through it.

When a dispatch's deterministic gates come back green, ``new-agent-task.ps1`` skips the
review leg entirely — the reasoning being that build + tests + verify already decided.
But on a flat-queue run there is no sealed oracle, so "tests" means *the tests the coder
wrote for its own code*. The candidate sets the exam, sits the exam, marks the exam, and
the harness reports the mark as evidence. Run
``ceremony-check-create-kitchen-conversion-helper-20260729-164936`` merged a unit
converter whose ounce factor is wrong by 2.5x (``'ounce': 14.2`` teaspoons; the true
figure on the file's own stated water-density basis is ~5.67), against an acceptance
criterion that said in terms "conversions between cups, tablespoons, grams and ounces
give correct results". The test that should have caught it reads:

    result = convert(1, 'gram', 'ounce')
    # The exact conversion should be ~0.0353 oz per gram, but we'll accept a reasonable range
    assert 0.01 <= result <= 0.1

The coder knew the right answer well enough to write it down, observed that its code did
not produce it, and widened the band until the exam passed. Every artifact the operator
reads said TESTS: pass.

So this module asks of the coder's tests the question the gate never asks: not *did they
pass* but *could they have failed*. Four fingerprints, each one measured off real
delivered code rather than imagined:

``dead_property``
    A Hypothesis ``@given`` function nested inside a test and never invoked. Pytest
    collects the OUTER function, whose body merely *defines* the property and returns.
    It passes in microseconds having generated nothing. The 07-29 run shipped one; the
    same nested-definition idiom appears in battery-b1 and battery-b6, where the coder
    DID remember the trailing call — so this fires on the slip, not on the style.

``vacuous_test``
    A collected ``test_*`` that cannot fail: no assert, no raise, no ``pytest.raises``.
    battery-b4 shipped two, both certifying "the default save path is cards.json" by
    calling the function and concluding that the absence of an exception proved it. The
    implementation happened to be correct, which is luck, not evidence.

``accommodated_assertion``
    The 07-29 fingerprint proper. A range or tolerance assertion whose nearby comment
    names a CONCRETE expected value that the asserted band does not pin. Deliberately
    narrow (see :func:`scan_accommodated_assertions`): a band whose own endpoint is the
    named value is a legitimate tolerance and never fires.

``decorative_hypothesis``
    ``hypothesis`` imported with no property test that can actually execute — the shape
    of compliance without the substance, invisible in every report.

Runtime companion: :func:`property_execution_finding` converts Hypothesis' own
statistics into a finding when a mandated property test generated ZERO examples, so a
decorator-shaped no-op can no longer read identically to a real property test.

Posture. Findings here are ADVISORY by default and become blocking only when the caller
says so — a false block costs the operator an unattended night, and the fingerprints
above are heuristics over source, not proofs. The two that ARE proofs (a property test
that provably never ran; a test that provably cannot fail) are the HARD set. Everything
softer reports and lets the merge proceed, because a gate nobody trusts gets switched
off, and a switched-off gate protects nothing.

Attribution. A finding names a TASK, and a task can only answer for the exam IT wrote.
So the scan is scoped to what changed since a named baseline commit
(:func:`resolve_scope`); given no baseline it reads the whole tree and SAYS SO, because
on any repo with history that reading is a true statement about the tree and a false
statement about the task. The three modes are distinct facts and stay distinct all the
way to the operator: a scoped verdict, an unscoped one, and — when a baseline was named
and could not be turned into a file list — no verdict at all. Silently widening to the
whole tree would be the same mis-attribution wearing a different hat, and silently
reporting zero would be worse.
"""

from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass, field, replace
from typing import Optional, Sequence

__all__ = [
    "CoderTestFinding",
    "CLASS_DEAD_PROPERTY",
    "CLASS_VACUOUS_TEST",
    "CLASS_ACCOMMODATED_ASSERTION",
    "CLASS_DECORATIVE_HYPOTHESIS",
    "CLASS_UNEXECUTED_PROPERTY",
    "ALL_CODER_TEST_CLASSES",
    "CoderTestQAResult",
    "SCOPE_FULL_TREE",
    "SCOPE_CHANGED_SINCE",
    "SCOPE_UNRESOLVED",
    "CODER_TEST_SCOPE_GIT_TIMEOUT_S",
    "TestScope",
    "full_tree_scope",
    "resolve_scope",
    "coder_test_qa_enabled",
    "scan_dead_property_tests",
    "scan_vacuous_tests",
    "scan_accommodated_assertions",
    "scan_decorative_hypothesis",
    "property_execution_finding",
    "parse_hypothesis_example_count",
    "scan_source",
    "discover_test_files",
]

# ---------------------------------------------------------------------------
# Finding classes
# ---------------------------------------------------------------------------

#: A ``@given`` property function defined inside a test and never called — collected,
#: green, and it generated nothing. PROVABLE from the AST → HARD.
CLASS_DEAD_PROPERTY = "dead_property"
#: A collected test with no assert, no raise and no ``pytest.raises`` — it cannot fail,
#: so its pass carries no information. PROVABLE from the AST → HARD.
CLASS_VACUOUS_TEST = "vacuous_test"
#: A range/tolerance assertion sitting next to a comment that names a concrete expected
#: value the band does not pin — the "I know the answer, I'll widen the exam" shape.
#: Heuristic over prose → SOFT (reported, never blocking on its own).
CLASS_ACCOMMODATED_ASSERTION = "accommodated_assertion"
#: ``hypothesis`` imported with no executable module-level property test. SOFT: a file
#: may legitimately import strategies for a helper.
CLASS_DECORATIVE_HYPOTHESIS = "decorative_hypothesis"
#: Runtime proof: a mandated property test generated ZERO examples. HARD — this is not
#: an inference about source, it is Hypothesis' own statistics.
CLASS_UNEXECUTED_PROPERTY = "unexecuted_property"

ALL_CODER_TEST_CLASSES: tuple[str, ...] = (
    CLASS_DEAD_PROPERTY,
    CLASS_VACUOUS_TEST,
    CLASS_ACCOMMODATED_ASSERTION,
    CLASS_DECORATIVE_HYPOTHESIS,
    CLASS_UNEXECUTED_PROPERTY,
)

#: The classes an AST or a statistics counter PROVES, as opposed to infers from prose.
#: Only these may block a merge; see the module docstring on why the soft set stays soft.
_HARD_CODER_TEST_CLASSES: frozenset[str] = frozenset({
    CLASS_DEAD_PROPERTY,
    CLASS_VACUOUS_TEST,
    CLASS_UNEXECUTED_PROPERTY,
})


def is_hard(finding_class: str) -> bool:
    """Whether a finding class is provable (blocking-eligible) rather than heuristic."""
    return finding_class in _HARD_CODER_TEST_CLASSES


# ---------------------------------------------------------------------------
# Scope — which test files this task is answerable for
# ---------------------------------------------------------------------------

#: Every python test file under the repo. What a scan gets when no baseline is named.
#: Honest as a reading of the TREE; never an attribution to a task, because a repo with
#: any history carries exams this task did not write.
SCOPE_FULL_TREE = "full-tree"
#: Only the test files that changed since a named baseline commit — this task's own exam.
SCOPE_CHANGED_SINCE = "changed-since"
#: A baseline was named and could not be turned into a file list. Not a narrower scope —
#: no scope at all: nothing may be attributed under it and no verdict is emitted.
SCOPE_UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class TestScope:
    """The set of files a scan is entitled to charge to the task that asked for it.

    ``keys`` holds normalised absolute path STRINGS and is consulted ONLY by
    :meth:`admits`, as a membership test over paths the scanner discovered by walking the
    tree itself. A path reported by git is joined to the repository root to build that
    string and is never opened, stat'd, listed or read — so no file enters the scan
    because git named it, only because the walk found it. A scope argument therefore
    cannot reach a file outside the scanned root no matter what it says: that is
    structural, not a check that could be forgotten. It is also why a change set naming a
    file the task DELETED costs nothing — the key simply matches no walked path.

    ``resolved`` is False for exactly one mode, and a caller that reads ``findings``
    without reading it will believe an unexamined tree was a clean one."""

    mode: str
    since: str = ""
    reason: str = ""
    keys: frozenset[str] = frozenset()

    @property
    def resolved(self) -> bool:
        return self.mode != SCOPE_UNRESOLVED

    def admits(self, path: "os.PathLike[str] | str") -> bool:
        """Whether *path* is inside this scope. An unresolved scope admits NOTHING —
        a scan under it would attribute files to a task on no evidence at all."""
        if self.mode == SCOPE_FULL_TREE:
            return True
        if self.mode == SCOPE_UNRESOLVED:
            return False
        return _scope_key(path) in self.keys

    def to_evidence(self) -> dict:
        return {
            "mode": self.mode,
            "resolved": self.resolved,
            "since": self.since,
            "changed_files": len(self.keys),
            "reason": self.reason,
        }


def _scope_key(path: "os.PathLike[str] | str") -> str:
    """The comparison form of a path: absolute, separator- and case-normalised.

    Pure string work — it never touches the filesystem and never resolves a symlink, so
    two names for one file compare equal only when they are spelled equivalently. On a
    case-insensitive filesystem that is what makes ``Tests/`` and ``tests/`` the same
    entry; on a case-sensitive one ``normcase`` is the identity and they stay distinct,
    which is also correct there."""
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def full_tree_scope(reason: str = "") -> TestScope:
    """The unscoped read: every test file under the root, and a reason saying so."""
    return TestScope(
        SCOPE_FULL_TREE,
        reason=reason or ("no task baseline was given, so every python test file under "
                          "the tree was examined — findings are attributed to the TREE, "
                          "not to one task"),
    )


@dataclass(frozen=True)
class CoderTestFinding:
    """One coder-test defect: taxonomy class, human message, and the subject named.

    Field names mirror :class:`shared.fleet.oracle_qa.OracleFinding` so both layers read
    the same downstream, but this is deliberately its OWN type rather than a reuse of
    that one: ``OracleFinding.hard`` resolves against the JOB-ORACLE taxonomy, which
    contains none of the classes above, so a reused finding would answer ``hard ==
    False`` for a provable defect. A severity predicate that silently returns the wrong
    answer is exactly the kind of quiet fail-open this module exists to close."""

    cls: str
    message: str
    subject: str = ""

    @property
    def hard(self) -> bool:
        return is_hard(self.cls)


@dataclass
class CoderTestQAResult:
    """The verdict over one project's coder-authored tests.

    ``measured`` is the honesty bit, and it mirrors ``Invoke-CoderTestQa``'s ``.Measured`` on
    the PowerShell side, whose callers already gate on it and never on ``.Findings.Count``.
    The two layers held opposite contracts until #1223: the wrapper refused to call an
    unexamined project clean, while this result — the thing the wrapper wraps — could not
    tell an unexamined project from a clean one at all. It defaults to False so a result
    assembled without scanning anything reads as ignorance rather than as a pass."""

    findings: list[CoderTestFinding] = field(default_factory=list)
    files_scanned: int = 0
    #: Files the scanner could not parse. Reported, never fatal: a syntax error in a test
    #: file is the TEST gate's business, and it will already be red.
    unparsed: list[str] = field(default_factory=list)
    #: Whether the scan actually ran over a resolved set of test files. False == no verdict
    #: was obtained; an empty ``findings`` list then means "nobody looked", not "nothing found".
    measured: bool = False
    #: What the count above is a count OF. Rides the result rather than the call site so
    #: every consumer of the evidence learns whose exam this was, not just how it graded.
    scope: TestScope = field(default_factory=full_tree_scope)

    @property
    def hard_findings(self) -> list[CoderTestFinding]:
        return [f for f in self.findings if is_hard(f.cls)]

    @property
    def clean(self) -> bool:
        """True ONLY when the scan ran and found nothing. An unmeasured scan is never clean —
        the fail-closed reading of a fail-soft control, and the same contract
        :meth:`~tools.dispatch_harness.green_quality.security.SecurityResult.is_clean` holds."""
        return self.measured and not self.findings

    def counts(self) -> dict[str, int]:
        """Full-taxonomy count map — every class present even at zero, so the evidence
        shape is stable across runs (the #827 convention)."""
        out = {c: 0 for c in ALL_CODER_TEST_CLASSES}
        for f in self.findings:
            out[f.cls] = out.get(f.cls, 0) + 1
        return out

    def to_evidence(self) -> dict:
        return {
            "measured": self.measured,
            "files_scanned": self.files_scanned,
            "unparsed": list(self.unparsed),
            "counts": self.counts(),
            "hard": len(self.hard_findings),
            "scope": self.scope.to_evidence(),
            "findings": [
                {"class": f.cls, "message": f.message, "subject": f.subject}
                for f in self.findings
            ],
        }


def coder_test_qa_enabled(env: "dict[str, str] | None" = None) -> bool:
    """The kill-switch, mirroring :func:`oracle_qa.oracle_qa_enabled`.

    Defaults ON. ``BLARAI_CODER_TEST_QA`` set to a falsey token restores the pre-#1170
    behaviour exactly (the coder's tests are trusted unexamined)."""
    import os

    raw = (env or os.environ).get("BLARAI_CODER_TEST_QA", "").strip().lower()
    return raw not in {"0", "false", "no", "off"}


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _decorator_names(node: ast.AST) -> list[str]:
    """Bare names of a function's decorators (``@given``/``@st.given``→``given``)."""
    out: list[str] = []
    for dec in getattr(node, "decorator_list", []):
        target = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(target, ast.Name):
            out.append(target.id)
        elif isinstance(target, ast.Attribute):
            out.append(target.attr)
    return out


def _referenced_names(node: ast.AST, *, skip: ast.AST) -> set[str]:
    """Every bare NAME referenced under ``node``, excluding the subtree ``skip``.

    Deliberately wider than "called": a nested property function that is passed to a
    runner, aliased, or stored in a list is still REACHABLE, and flagging it dead would
    be a false positive. Only a name that appears nowhere outside its own definition is
    provably unreachable."""
    seen: set[str] = set()
    for child in ast.walk(node):
        if child is skip:
            continue
        # Do not descend into the skipped subtree.
        if any(child is n for n in ast.walk(skip)):
            continue
        if isinstance(child, ast.Name):
            seen.add(child.id)
        elif isinstance(child, ast.Attribute):
            seen.add(child.attr)
    return seen


def _test_functions(tree: ast.AST) -> list[ast.FunctionDef]:
    """Module-level and Test-class-method ``def test*`` nodes — pytest's discovery
    contract, matching :func:`oracle_qa._test_functions` so both layers agree on what
    counts as a collected test."""
    out: list[ast.FunctionDef] = []
    for node in getattr(tree, "body", []):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            out.append(node)
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and sub.name.startswith("test"):
                    out.append(sub)
    return out


def _nested_functions(func: ast.AST) -> list[ast.FunctionDef]:
    return [
        n for n in ast.walk(func)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n is not func
    ]


# ---------------------------------------------------------------------------
# Fingerprint 1 — the dead property test
# ---------------------------------------------------------------------------


def scan_dead_property_tests(code: str) -> list[CoderTestFinding]:
    """A ``@given`` function nested in a test and never referenced outside its own body.

    The nested-definition idiom itself is FINE and the fleet's coder uses it everywhere:
    define the property inside the test, then call it on the last line so Hypothesis
    drives it. battery-b1 and battery-b6 both do exactly that and both genuinely execute.
    What this catches is the missing trailing call — the 07-29 shape, where the property
    is defined, decorated, and then simply left there while the outer test returns green
    having generated nothing.

    Reachability, not just invocation: a nested property that is referenced ANYWHERE
    outside its definition (called, aliased, passed to a runner) is left alone. Only a
    name that appears nowhere else is provably dead."""
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return []
    if "given" not in code:
        return []

    out: list[CoderTestFinding] = []
    for test in _test_functions(tree):
        for inner in _nested_functions(test):
            if "given" not in _decorator_names(inner):
                continue
            if inner.name in _referenced_names(test, skip=inner):
                continue  # reachable → not dead
            out.append(CoderTestFinding(
                CLASS_DEAD_PROPERTY,
                f"`{test.name}` defines the property test `{inner.name}` (@given) but "
                f"never calls it — pytest collects `{test.name}`, which generates no "
                f"examples and passes instantly; add `{inner.name}()` as its last line",
                subject=f"{test.name}.{inner.name}",
            ))
    return out


# ---------------------------------------------------------------------------
# Fingerprint 2 — the vacuous test
# ---------------------------------------------------------------------------

#: Call targets that can carry a test's whole verdict without a literal ``assert``.
_VERDICT_BEARING_CALLS: frozenset[str] = frozenset({
    "raises", "warns", "fail", "xfail", "approx", "check", "assert_called",
    "assert_called_once", "assert_called_with", "assert_called_once_with",
    "assert_any_call", "assert_has_calls", "assert_not_called",
    "assertEqual", "assertTrue", "assertFalse", "assertRaises", "assertIn",
    "assertIsNone", "assertIsNotNone", "assertAlmostEqual", "assert_frame_equal",
    "assert_array_equal", "assert_allclose",
})


def _bears_a_verdict(func: ast.AST) -> bool:
    """Whether a test can fail by design: an assert, a raise, a ``with pytest.raises``,
    a unittest assertion, or a mock's ``assert_*``. Conservative on purpose — anything
    that could plausibly carry the verdict spares the test."""
    for node in ast.walk(func):
        if isinstance(node, (ast.Assert, ast.Raise)):
            return True
        if isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                ctx = item.context_expr
                target = ctx.func if isinstance(ctx, ast.Call) else ctx
                name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "")
                if name in _VERDICT_BEARING_CALLS:
                    return True
        if isinstance(node, ast.Call):
            target = node.func
            name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "")
            if name in _VERDICT_BEARING_CALLS or name.startswith("assert"):
                return True
    return False


def scan_vacuous_tests(code: str) -> list[CoderTestFinding]:
    """A collected test that cannot fail unless the code under it throws.

    battery-b4 shipped two of these against the criterion "the file is cards.json in the
    working directory unless a path names another file". Both call ``save_cards(cards,
    None)`` and stop, one of them commenting "If we got here without error, the default
    path handling works". It would pass if the function wrote to a temp file, to the
    wrong directory, or nowhere at all.

    A test whose body only DEFINES a nested property is exempt here — that is the
    dead-property fingerprint's business, and double-reporting one defect as two would
    inflate the count the operator steers by."""
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return []

    out: list[CoderTestFinding] = []
    for test in _test_functions(tree):
        if _bears_a_verdict(test):
            continue
        nested = _nested_functions(test)
        if any("given" in _decorator_names(n) for n in nested):
            continue  # owned by scan_dead_property_tests
        if any(_bears_a_verdict(n) for n in nested):
            continue
        out.append(CoderTestFinding(
            CLASS_VACUOUS_TEST,
            f"`{test.name}` has no assertion, no raise and no pytest.raises — it passes "
            "unless the code throws, so its green carries no information about whether "
            "the behaviour is correct",
            subject=test.name,
        ))
    return out


# ---------------------------------------------------------------------------
# Fingerprint 3 — the accommodated assertion
# ---------------------------------------------------------------------------

#: Hedging vocabulary that, next to a widened band, marks a KNOWN answer being dodged.
#: "should be", "exact", "actual" are the load-bearing ones; the rest ride along.
_HEDGE = re.compile(
    r"\b(should\s+be|exact|actually|true\s+value|correct\s+(value|answer)|"
    r"reasonable\s+range|accept\w*\s+(a\s+)?range|close\s+enough|approximat\w*|"
    r"we'?ll\s+accept|for\s+now|good\s+enough)\b",
    re.IGNORECASE,
)
#: A decimal or integer literal in a comment. A bare integer alone is too common to be
#: evidence, so :func:`scan_accommodated_assertions` requires a DECIMAL.
_DECIMAL_IN_COMMENT = re.compile(r"\d+\.\d+(?:[eE][-+]?\d+)?")


def _numeric_literals(node: ast.AST) -> set[float]:
    out: set[float] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, (int, float)) and not isinstance(child.value, bool):
            out.add(float(child.value))
        elif isinstance(child, ast.UnaryOp) and isinstance(child.op, ast.USub):
            inner = child.operand
            if isinstance(inner, ast.Constant) and isinstance(inner.value, (int, float)):
                out.add(-float(inner.value))
    return out


def _is_banded_assert(test: ast.AST) -> bool:
    """``lo <= x <= hi`` (a chained compare) or ``abs(a - b) < tol``."""
    if not isinstance(test, ast.Compare):
        return False
    if len(test.comparators) >= 2:
        return True
    left = test.left
    return (
        isinstance(left, ast.Call)
        and isinstance(left.func, ast.Name)
        and left.func.id == "abs"
    )


def scan_accommodated_assertions(code: str) -> list[CoderTestFinding]:
    """A widened band next to a comment that names the value the band declines to pin.

    This is the 07-29 defect's exact signature, and it is deliberately hard to trigger.
    ALL of the following must hold, or nothing fires:

    1. the assertion is a range or an ``abs()`` tolerance (a plain ``==`` never fires);
    2. a comment within the four preceding lines carries a DECIMAL literal;
    3. that comment also carries hedging vocabulary ("the exact conversion should be…");
    4. the named decimal is NOT among the assertion's own numeric literals.

    Condition 4 is what keeps honest tolerances safe. ``# 0.1 tolerance`` beside
    ``assert abs(x - y) < 0.1`` names a number the assertion already contains, so it
    passes. The 07-29 case names 0.0353 beside a band of 0.01–0.1 — the author wrote
    down the right answer and then asserted something that does not require it.

    SOFT by construction: it reads prose, and prose is not proof. It reports so a human
    (or the cross-model exam critic) looks; it never blocks a merge by itself."""
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return []

    lines = code.splitlines()
    out: list[CoderTestFinding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assert) or not _is_banded_assert(node.test):
            continue
        start = max(0, node.lineno - 5)
        window = lines[start: node.lineno - 1]
        comments = [ln.strip() for ln in window if ln.strip().startswith("#")]
        if not comments:
            continue
        text = " ".join(comments)
        if not _HEDGE.search(text):
            continue
        named = {float(m) for m in _DECIMAL_IN_COMMENT.findall(text)}
        if not named:
            continue
        asserted = _numeric_literals(node.test)
        unpinned = {v for v in named if v not in asserted}
        if not unpinned:
            continue  # the comment names a bound the assertion actually uses → honest
        shown = ", ".join(repr(v) for v in sorted(unpinned))
        out.append(CoderTestFinding(
            CLASS_ACCOMMODATED_ASSERTION,
            f"line {node.lineno}: the comment names an expected value ({shown}) that "
            "this range/tolerance assertion does not require — the test was widened "
            "around a known answer instead of asserting it",
            subject=f"line:{node.lineno}",
        ))
    return out


# ---------------------------------------------------------------------------
# Fingerprint 4 — decorative hypothesis
# ---------------------------------------------------------------------------


def scan_decorative_hypothesis(code: str) -> list[CoderTestFinding]:
    """``hypothesis`` imported with no property test that can actually run.

    Fires only when the import exists AND there is no module-level ``@given`` test AND
    no reachable nested one. A file that imports strategies to build a fixture is
    untouched, because such a file has no ``@given`` at all and the import alone is not
    the complaint — the complaint is the SHAPE of compliance without its substance."""
    if "hypothesis" not in code:
        return []
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return []

    imports_hypothesis = any(
        (isinstance(n, ast.ImportFrom) and (n.module or "").split(".")[0] == "hypothesis")
        or (isinstance(n, ast.Import) and any(a.name.split(".")[0] == "hypothesis" for a in n.names))
        for n in ast.walk(tree)
    )
    if not imports_hypothesis:
        return []

    for test in _test_functions(tree):
        if "given" in _decorator_names(test):
            return []  # a real module-level property test
        for inner in _nested_functions(test):
            if "given" in _decorator_names(inner) and inner.name in _referenced_names(test, skip=inner):
                return []  # a reachable nested one

    return [CoderTestFinding(
        CLASS_DECORATIVE_HYPOTHESIS,
        "imports hypothesis but has no property test that can execute — the file carries "
        "the shape of a property-based suite without one",
        subject="hypothesis",
    )]


# ---------------------------------------------------------------------------
# Runtime proof — did the property test actually generate anything?
# ---------------------------------------------------------------------------

#: Hypothesis' ``--hypothesis-show-statistics`` block reports, per property test, a line
#: of the form "- 100 passing examples, 0 failing examples, 0 invalid examples".
_HYP_EXAMPLES = re.compile(
    r"(\d+)\s+passing\s+examples?,\s*(\d+)\s+failing\s+examples?,\s*(\d+)\s+invalid\s+examples?",
    re.IGNORECASE,
)


def parse_hypothesis_example_count(stats_text: str) -> Optional[int]:
    """Total examples Hypothesis reports having generated across all property tests.

    ``None`` when the output carries no statistics block at all — an ABSENT measurement,
    which is not the same fact as a measured zero and must never be reported as one."""
    matches = _HYP_EXAMPLES.findall(stats_text or "")
    if not matches:
        return None
    return sum(int(p) + int(f) + int(i) for p, f, i in matches)


def property_execution_finding(
    stats_text: str,
    *,
    property_test_required: bool,
) -> Optional[CoderTestFinding]:
    """Turn Hypothesis' own statistics into a finding when a MANDATED property test
    generated nothing.

    The acceptance-test prompt requires a property-based test wherever a criterion states
    an invariant. Until now nothing checked that the requirement produced anything that
    runs: a dead ``@given`` and a real one are indistinguishable in the report, and the
    only tell was that the whole suite finished in 0.2 seconds. This makes the
    distinction observable — and HARD, because it is Hypothesis' own count, not an
    inference about source.

    Absent statistics is reported as absent (``None`` → no finding). Fail-loud on a
    measured zero; stay quiet on an unmeasured one, and let the AST fingerprints carry
    that case."""
    if not property_test_required:
        return None
    count = parse_hypothesis_example_count(stats_text)
    if count is None:
        return None
    if count > 0:
        return None
    return CoderTestFinding(
        CLASS_UNEXECUTED_PROPERTY,
        "a property-based test was required and Hypothesis reports 0 generated examples "
        "— the property test exists in name only and proved nothing",
        subject="hypothesis-statistics",
    )


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def scan_source(code: str, *, path: str = "") -> list[CoderTestFinding]:
    """Every AST fingerprint over one test file, in report order."""
    findings: list[CoderTestFinding] = []
    findings.extend(scan_dead_property_tests(code))
    findings.extend(scan_vacuous_tests(code))
    findings.extend(scan_accommodated_assertions(code))
    findings.extend(scan_decorative_hypothesis(code))
    if path:
        # CoderTestFinding is frozen — rebuild rather than mutate, so the qualified
        # subject cannot silently no-op the way an in-place assignment would raise.
        findings = [
            replace(f, subject=f"{path}::{f.subject}" if f.subject else path)
            for f in findings
        ]
    return findings


def scan_paths(paths: "Sequence[str]") -> CoderTestQAResult:
    """Scan a set of test files on disk. Unreadable/unparseable files are recorded and
    skipped — a broken test file is the TEST gate's business, already red there.

    ``measured`` is set only when at least one file was actually READ AND PARSED. An empty
    path list, a tree whose files all failed to open, or a suite that is entirely
    unparseable all yield ``measured=False``: each is an unexamined project, and an
    unexamined project must not be able to read as an examined one that found nothing."""
    from pathlib import Path

    result = CoderTestQAResult()
    parsed = 0
    for raw in paths:
        p = Path(raw)
        try:
            code = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            result.unparsed.append(str(p))
            continue
        result.files_scanned += 1
        try:
            ast.parse(code)
        except (SyntaxError, ValueError):
            result.unparsed.append(str(p))
            continue
        parsed += 1
        result.findings.extend(scan_source(code, path=p.name))
    result.measured = parsed > 0
    return result


# ---------------------------------------------------------------------------
# CLI — the harness's entry point (`python -m shared.fleet.coder_test_qa <repo>`)
# ---------------------------------------------------------------------------


#: Abort ceiling on each of the three bounded git reads one scope resolution makes. A
#: wedged git must not hold a dispatch open; a slow one must not lose the scope.
CODER_TEST_SCOPE_GIT_TIMEOUT_S = 30.0

#: What may be spelled as a baseline. Deliberately narrower than git's own ref grammar:
#: a commit id or a plain branch name, nothing that git would read as an option, a
#: revision range, a pathspec or a reflog selector. Deny-by-default — a caller that needs
#: ``HEAD~1`` resolves it to an id first.
_BASELINE_REF_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._/-]{0,254}\Z")


def _valid_baseline_ref(ref: str) -> bool:
    """Whether ``ref`` may be handed to git as a revision.

    The first-character rule is what makes option injection impossible (``--upload-pack=``
    and friends are refused before argv is built); the substring rules refuse the three
    spellings that would silently change what ``git diff`` compares — a range (``a..b``),
    a reflog selector (``@{…}``) and a lock name."""
    ref = (ref or "").strip()
    if not _BASELINE_REF_RE.match(ref):
        return False
    return ".." not in ref and "@{" not in ref and not ref.endswith(".lock")


def _git(repo: str, args: "Sequence[str]", timeout: float) -> "tuple[bool, str]":
    """One bounded, non-shell git read. ``(True, stdout)`` or ``(False, why)``.

    The failure string carries git's own last words rather than a rewrite of them: a
    scope that could not be established has to name its cause, and only git knows whether
    this was an unknown revision, a shallow clone or a missing binary.

    Routed through :func:`shared.procspawn.run_captured` rather than a raw
    ``subprocess.run``, because this read runs UNATTENDED — it is on the exam path the
    overnight battery drives, where no operator is watching to notice a stall. TWO of that
    helper's guarantees are load-bearing here and neither is a property of
    ``subprocess.run``: stdin is ``DEVNULL``, so a git that reaches a credential helper or
    a pager cannot block forever on a stdin nobody will ever write to; and a timeout kills
    the whole PROCESS TREE, so a helper git spawned cannot outlive the read that gave up on
    it and go on holding the budget.

    The helper's third guarantee, its UTF-8 environment pin, does NOT apply to this call
    and must not be cited for it: ``_child_env`` sets ``PYTHONUTF8`` and
    ``PYTHONIOENCODING``, which are CPython interpreter variables that ``git.exe`` does not
    read. Git's output encoding is identical before and after this routing. Stated because
    the reverse claim was written here first and is the kind a later reader would inherit
    as settled rather than re-check."""
    from shared.procspawn import run_captured

    try:
        proc = run_captured(["git", "-C", str(repo), *args], timeout_s=timeout)
    except OSError as exc:
        # The spawn itself failed — a missing git binary, or a path the OS refuses — so
        # there is no result to inspect.
        return False, f"{type(exc).__name__}: {exc}"
    if proc.timed_out:
        # `run_captured` REPORTS a timeout instead of raising it, so this branch replaces
        # the `TimeoutExpired` the raw call used to throw into the handler above. Stated
        # plainly, because a scope that could not be established must name its cause.
        return False, (
            f"git did not finish within {timeout:g}s and its process tree was killed")
    if proc.returncode != 0:
        tail = " ".join((proc.stderr or "").split())[:200]
        return False, tail or f"git exited {proc.returncode} with no message"
    return True, proc.stdout or ""


def _relative_paths_are_safe(rels: "Sequence[str]") -> bool:
    """Whether every path git reported is a plain repo-relative name.

    Git does not emit absolute paths or ``..`` components from these plumbing reads, so a
    violation means the output is not what it claims to be. Validated before anything is
    normalised, because normalising first would fold a traversal into a legitimate-looking
    path and hide exactly the thing this refuses."""
    for rel in rels:
        if not rel or os.path.isabs(rel) or rel.startswith("\\"):
            return False
        if ".." in rel.replace("\\", "/").split("/"):
            return False
    return True


def resolve_scope(repo: str, since: str,
                  *, timeout: float = CODER_TEST_SCOPE_GIT_TIMEOUT_S) -> TestScope:
    """The files that changed in ``repo`` since the baseline commit ``since``.

    The union of two bounded reads — the working tree against the baseline (every tracked
    file this task committed OR left dirty) and the untracked-but-not-ignored set. A
    superset of what the task committed, never a subset: the cost of one extra file in
    scope is a finding the task can answer for, and the cost of one missing file is an
    exam nobody examines.

    Every failure returns :data:`SCOPE_UNRESOLVED` with the cause named, and an
    unresolved scope admits nothing. Widening to the whole tree here would re-create the
    mis-attribution the scope exists to prevent, and returning an empty CHANGED scope
    would report a measured zero over a scan that never happened."""
    def unresolved(why: str) -> TestScope:
        return TestScope(SCOPE_UNRESOLVED, since=since, reason=why)

    # Normalise ONCE, here, so the value that was validated is the value that reaches
    # argv. Validating a stripped copy and then passing the raw one is how a guard comes
    # to be checking something other than what runs.
    since = (since or "").strip()
    if not _valid_baseline_ref(since):
        return unresolved(
            f"the baseline {since!r} is not a plain commit id or branch name, so it was "
            "refused before it could reach git")

    ok, top_out = _git(repo, ["rev-parse", "--show-toplevel"], timeout)
    if not ok:
        return unresolved(f"the repository root could not be read: {top_out}")
    top = (top_out or "").strip().splitlines()[0].strip() if top_out.strip() else ""
    if not top:
        return unresolved("git reported no repository root for this path")

    # `--end-of-options` stops the baseline being parsed as a flag; the trailing `--`
    # stops it being parsed as a pathspec (a ref that happens to name an existing file
    # would otherwise diff that file and exit 0 — a wrong answer that looks right).
    # `--no-renames` keeps the output independent of git's rename heuristics, and `-z`
    # removes quoting so a path with a space, a quote or a non-ASCII name survives whole.
    ok, diff_out = _git(
        repo,
        ["diff", "--name-only", "--no-renames", "-z", "--end-of-options", since, "--"],
        timeout)
    if not ok:
        return unresolved(f"the baseline {since!r} could not be diffed: {diff_out}")

    ok, others_out = _git(
        repo,
        ["ls-files", "--others", "--exclude-standard", "--full-name", "-z"],
        timeout)
    if not ok:
        return unresolved(f"the untracked files could not be listed: {others_out}")

    rels = [r for r in (diff_out + others_out).split("\0") if r]
    if not _relative_paths_are_safe(rels):
        return unresolved(
            "git reported a path that is not a plain repo-relative name, so the change "
            "set was refused rather than trusted")

    keys = frozenset(_scope_key(os.path.join(top, rel)) for rel in rels)
    return TestScope(
        SCOPE_CHANGED_SINCE, since=since, keys=keys,
        reason=f"{len(keys)} file(s) changed since {since}")


def discover_test_files(repo: str, *, scope: Optional[TestScope] = None) -> list[str]:
    """Python test files under ``repo`` that ``scope`` admits, excluding the SEALED job
    oracle.

    ``tests/test_job_acceptance.py`` is authored away from the coder and restored from a
    clean copy before grading — it is the control, not the subject. Scanning it here would
    at best duplicate :mod:`oracle_qa` and at worst let a finding against the CONTROL park
    a run whose actual defect is elsewhere. Build debris is excluded for the same reason
    ``oracle_qa`` avoids it: a vendored dependency's test suite is not this coder's exam,
    and neither is a nested agent worktree or a tool's own state directory.

    ``scope`` defaults to the whole tree. That answers "what does this tree contain",
    which is a different question from "what did this task write" — see :class:`TestScope`
    for why the caller has to say which one it is asking."""
    from pathlib import Path

    root = Path(repo)
    if not root.is_dir():
        return []
    if scope is not None and not scope.resolved:
        return []
    # Directories whose python files are never the coder's exam: VCS and tool state, the
    # dependency trees, build output, and the two that hold OTHER checkouts' work — a
    # nested agent worktree and an agent's own state directory.
    skip_parts = {".git", ".venv", "venv", "node_modules", "__pycache__",
                  ".pytest_cache", ".hypothesis", "build", "dist", "site-packages",
                  ".claude", ".worktrees", ".tox", ".mypy_cache", ".ruff_cache", ".eggs"}
    out: list[str] = []
    # Pruned walk rather than rglob: an excluded directory is never DESCENDED, only
    # skipped. rglob enumerated every object inside .git and node_modules and then threw
    # the results away, which is most of what a scan of a large tree spent its time on.
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in skip_parts)
        parent = os.path.basename(dirpath)
        for name in sorted(filenames):
            if not name.endswith(".py"):
                continue
            if name == "test_job_acceptance.py":
                continue  # the SEALED oracle — the control, not the subject
            if not (name.startswith("test_") or name.endswith("_test.py") or parent == "tests"):
                continue
            p = Path(dirpath) / name
            if scope is not None and not scope.admits(p):
                continue  # a real test file, but not one this task wrote
            out.append(str(p))
    return out


def main(argv: "Sequence[str] | None" = None) -> int:
    """Emit one compact JSON object describing the coder's own exam.

    Exit code is ALWAYS 0. The harness decides what to do with ``hard`` — this tool
    reports, it does not adjudicate, and a scanner that can hard-fail a dispatch on its
    own exit code would be a second merge authority. One arbiter, in the harness.

    Every exit carries the same keys, including ``scope``, so no consumer can read a
    missing field as a zero. ``scope.resolved`` is the one a caller must read before
    ``hard``: with ``--since`` the counts describe only what that task changed, without
    it they describe the whole tree, and when it is false nothing was examined at all."""
    import argparse
    import json

    parser = argparse.ArgumentParser(prog="coder_test_qa", description=__doc__)
    parser.add_argument("repo", help="project root to scan")
    parser.add_argument("--since", default="",
                        help="baseline commit this task started from; the scan is then "
                             "limited to the files changed after it. Omitted, the whole "
                             "tree is read and the output says so.")
    parser.add_argument("--stats", default="", help="path to a pytest run's Hypothesis statistics output")
    parser.add_argument("--require-property", action="store_true",
                        help="a property-based test was mandated for this task")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if not coder_test_qa_enabled():
        # A switched-off control is an ABSENT measurement, so the emitted blob says so in the
        # same key the enabled path uses. Without it a reader would have to infer honesty from
        # `enabled`, and the two are different questions: a control can be on and still have
        # examined nothing.
        print(json.dumps({"enabled": False, "measured": False, "hard": 0, "findings": [],
                          "counts": {c: 0 for c in ALL_CODER_TEST_CLASSES},
                          "files_scanned": 0, "unparsed": [],
                          "scope": TestScope(SCOPE_UNRESOLVED, since=args.since,
                                             reason="the kill-switch is off, so nothing "
                                                    "was scanned or scoped").to_evidence()}))
        return 0

    scope = resolve_scope(args.repo, args.since) if args.since else full_tree_scope()
    if not scope.resolved:
        # No verdict, and it must not be mistaken for one. Every count is zero because
        # nothing was examined — `scope.resolved: false` is the field that says which
        # kind of zero this is, and a caller that ignores it will read an unexamined
        # tree as a clean exam.
        print(json.dumps({"enabled": True, "hard": 0, "findings": [],
                          "counts": {c: 0 for c in ALL_CODER_TEST_CLASSES},
                          "files_scanned": 0, "unparsed": [],
                          "scope": scope.to_evidence()}))
        return 0

    result = scan_paths(discover_test_files(args.repo, scope=scope))
    result.scope = scope

    if args.stats:
        from pathlib import Path

        try:
            stats_text = Path(args.stats).read_text(encoding="utf-8", errors="replace")
        except OSError:
            stats_text = ""
        finding = property_execution_finding(stats_text, property_test_required=args.require_property)
        if finding is not None:
            result.findings.append(finding)

    evidence = result.to_evidence()
    evidence["enabled"] = True
    print(json.dumps(evidence))
    return 0


if __name__ == "__main__":  # pragma: no cover — exercised via the harness + a CLI lock
    raise SystemExit(main())
