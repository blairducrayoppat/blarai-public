"""Oracle Quality Assurance — validate the generated job oracle BEFORE it seeds (#821).

The dispatch fleet seeds a 14B-authored, spec-blind pytest oracle into every
best-of-N candidate and grades the final integrated tree against it (#690/#748/#740).
That oracle is the single place the machinery can stamp GREEN and be WRONG — a
defective oracle either CONVICTS valid work (an ill-posed strategy, an invented
return-contract, an un-collectable file → the coder is falsely blamed and the job
parks) or, worse, MINTS a false GREEN (a vacuous test that passes with no
implementation). The failure taxonomy measured the first class at ~3-4 parks/night;
the adequacy dossier measured the second in both banked GREENs (graded 4-of-6
criteria, the no-crash smoke criterion never asserted).

This module is the oracle-lifecycle stage the grading subsystem was missing:

    author (14B) → [VALIDATE] → seed (protected, #748) → grade → evidence

It runs DETERMINISTIC stages (no model in the honesty-critical path — ADR-037/#825's
house rule; the model PROPOSES, a deterministic pass DISPOSES) and, where the 14B is
still resident (plan time), a bounded REGENERATION loop that feeds ONE named defect
back per round (the small-model discipline, #740 c.1721 — structure over prose,
single-focus corrections, cheap narrow retries). A hopeless oracle is a COUNTED
not-run, never a blocked dispatch (pipeline degradation is fail-soft-honest; only the
seed GATE fails closed on a confirmed defect — a bad oracle is worse than none).

Two lifecycle points, one coherent pipeline:

  * PLAN time (14B resident — :func:`validate_authored_oracle`): the AST-decidable
    static stages + the criterion→test traceability matrix, WITH regeneration. This
    is where a defect can still be fixed by re-authoring.
  * SEED time (30B resident, 14B gone — :func:`f2p_seed_gate`): the execution stages
    (advisory collectability confirmation + the FAIL-TO-PASS baseline) against the
    real pre-wave skeleton, as a fail-closed GATE (refuse to seed a vacuous oracle),
    no regeneration possible.

Every validation-failure class is COUNTED into the run evidence (the #827 classifier
consumes it; the #832 green-audit matches on it), and every GREEN discloses its
coverage (``oracle_coverage: k/n``) so a partially-graded win banks but says so
(the ADR-037 false-completeness rule). DORMANT until ``[fleet_dispatch].enabled``;
individually kill-switchable via ``BLARAI_ORACLE_QA`` (default ON).

Deep QA (AST + pytest) is PYTHON-only; a node oracle gets the structural pass the
authoring path already applies plus an honest ``language: node`` stamp (the taxonomy
defects — B1n2 ill-posed strategy, B4 invented contract, B6 ``sys.listdir`` — are all
Python, and there is no ``ast`` for JS).
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import time
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Sequence

from shared import procspawn
from shared.fleet import grade_env

# ---------------------------------------------------------------------------
# The validation-failure taxonomy (every class counted into run evidence, #827)
# ---------------------------------------------------------------------------

#: The oracle does not compile / cannot be collected (SyntaxError, or the known
#: Hypothesis size-kwarg TypeError that fires at collection — B1n1).
CLASS_COLLECTABILITY = "collectability"
#: A property-test strategy is ill-posed — unbounded where the spec bounds it, so it
#: feeds spec-invalid inputs and CONVICTS valid work (B1n2's ``st.floats()`` → 0.0).
CLASS_STRATEGY = "strategy_illposed"
#: The oracle drives interactive I/O (``input()`` / ``sys.stdin``) — under pytest the
#: read raises and the test errors every run, so the job can NEVER pass (B4).
CLASS_INTERACTIVE_IO = "interactive_io"
#: The oracle asserts against a first-party symbol the spec never declared — an
#: invented return-contract that convicts a coder who built exactly what was asked
#: (B4's ``check_answer(...) == "correct"``).
CLASS_INVENTED_CONTRACT = "invented_contract"
#: The oracle asserts a first-party call RETURNS a specific magic STRING the spec never
#: names (B4n2's ``check_answer(...) == "correct"`` — the callable exists, but the
#: DEMANDED return value is invented). A distinct axis from the import-name invention:
#: the name resolves, the SIGNATURE/return-shape is the fabrication. SOFT (regeneratable
#: — drop the invented value, assert only the spec's behaviour) so a heuristic string
#: match never REFUSES an oracle; the callable-arity half of B4n2 is caught at the gate
#: probe (#826/#822), the return-value half here at authorship.
CLASS_INVENTED_RETURN = "invented_return_contract"
#: The oracle's first-party import surface exceeds the declared plan contract (the
#: coder is never told to build what the oracle imports → ModuleNotFoundError at
#: collection → falsely RED on plumbing, not logic). Light self-consistency; the deep
#: layout check is #822/#826.
CLASS_IMPORT_CONTRACT = "import_contract"
#: The oracle makes NO behavioural assertion (and no no-raise call) against any
#: first-party symbol, or imports nothing first-party — a vacuous/thin oracle that can
#: only ever mint a false GREEN (the adequacy floor, r2adequacy §3.5).
CLASS_ADEQUACY_FLOOR = "adequacy_floor"
#: A test-tier (behavior/smoke) criterion has no verified assertion in the oracle — a
#: coverage gap (the criterion→test traceability matrix, r2adequacy rank-1). SOFT:
#: seeds with an honest ``oracle_coverage: partial`` disclosure.
CLASS_TRACEABILITY = "traceability_gap"
#: A test PASSES on the pre-implementation skeleton — vacuous / non-discriminating,
#: it can only mint a false GREEN (the FAIL-TO-PASS baseline, r1extern lever 1;
#: SWE-bench's F→P invariant / AgentLens "Lucky Pass").
CLASS_F2P_VACUOUS = "f2p_vacuous"
#: The bounded regeneration loop exhausted its rounds with a HARD defect unresolved —
#: its OWN counted class so a chronically-defective oracle is a visible metric, never
#: a comfortable generic not-run (r3adversary H5).
CLASS_REGENERATE_EXHAUSTED = "regenerate_exhausted"

#: Stamp values that mean a probe DID NOT RUN. The module that writes a stamp owns what
#: it means, so this vocabulary lives here rather than in each consumer — `swap_driver`
#: imports it. Anything outside this set is a real result and therefore evidence.
STAMPS_NOT_MEASURED: frozenset[str] = frozenset({"", "not-run", "skipped", "unknown"})

#: Which STAGE each finding class comes from. This is the map that makes a count of zero
#: interpretable: `f2p_vacuous: 0` means "we looked for vacuous tests and found none" ONLY
#: if the fail-to-pass baseline actually ran. When the producing stage did not run, the
#: class's zero is the absence of a measurement, not the measurement of an absence —
#: #1342, where `f2p_vacuous: 0` sat beside `f2p_baseline: "not-run"` on an oracle that
#: was three-fifths vacuous, and every reader took the zero at face value.
STAGE_STATIC = "static_scan"
STAGE_COLLECTABILITY = "collectability_probe"
STAGE_F2P = "f2p_baseline"
STAGE_COVERAGE = "coverage_map"
STAGE_ALWAYS = "bookkeeping"

CLASS_STAGE: dict[str, str] = {
    CLASS_COLLECTABILITY: STAGE_COLLECTABILITY,
    CLASS_F2P_VACUOUS: STAGE_F2P,
    CLASS_TRACEABILITY: STAGE_COVERAGE,
    CLASS_STRATEGY: STAGE_STATIC,
    CLASS_INTERACTIVE_IO: STAGE_STATIC,
    CLASS_INVENTED_CONTRACT: STAGE_STATIC,
    CLASS_INVENTED_RETURN: STAGE_STATIC,
    CLASS_IMPORT_CONTRACT: STAGE_STATIC,
    CLASS_ADEQUACY_FLOOR: STAGE_STATIC,
    # The regeneration counter is written by the loop itself, so it is always measured.
    CLASS_REGENERATE_EXHAUSTED: STAGE_ALWAYS,
}

#: Plain-language name for each stage, for the ``not_measured`` disclosure. These are read
#: by people deciding whether to trust a delivery, so they say what was not done, not which
#: function did not run.
_STAGE_PROSE: dict[str, str] = {
    STAGE_STATIC: "the oracle's source was never scanned, so nothing about how it is "
                  "written was checked",
    STAGE_COLLECTABILITY: "the oracle was never loaded, so whether its tests can even be "
                          "collected is unknown",
    STAGE_F2P: "the oracle was never run against a tree where the product does not exist, "
               "so it has NOT been shown capable of failing",
    STAGE_COVERAGE: "no requirement-to-assertion map was built, so which of the operator's "
                    "requirements this exam covers is unknown",
}

#: Every class, for a zero-initialised count map (so evidence always carries the full
#: taxonomy, even the classes that did not fire this run — a stable shape for #827).
ALL_CLASSES: tuple[str, ...] = (
    CLASS_COLLECTABILITY,
    CLASS_STRATEGY,
    CLASS_INTERACTIVE_IO,
    CLASS_INVENTED_CONTRACT,
    CLASS_INVENTED_RETURN,
    CLASS_IMPORT_CONTRACT,
    CLASS_ADEQUACY_FLOOR,
    CLASS_TRACEABILITY,
    CLASS_F2P_VACUOUS,
    CLASS_REGENERATE_EXHAUSTED,
)

#: The HARD classes — a residual after bounded regeneration REFUSES the seed (a bad
#: oracle is worse than none: don't-seed → honest job-acceptance not-run). Everything
#: else is SOFT: it seeds with an honest disclosure stamp (a partial-coverage GREEN
#: banks but says so, mirroring the "oracle-not-run beats a lying green" rule).
_HARD_CLASSES: frozenset[str] = frozenset({
    CLASS_COLLECTABILITY,
    CLASS_STRATEGY,
    CLASS_INTERACTIVE_IO,
    CLASS_ADEQUACY_FLOOR,
    CLASS_F2P_VACUOUS,
})

#: Findings that make a requirement→assertion map IMPOSSIBLE, as opposed to merely
#: unflattering (#1374). The coverage map used to be gated on ``_HARD_CLASSES`` being
#: empty, and the consequence was measured on 2026-08-10: every B9 run reported
#: ``adequacy_floor: 2``, so the map was skipped on **every run that had ever happened**
#: and capability 17 had no data at all.
#:
#: The original guard's reasoning was right for the classes it was written against —
#: you cannot trace assertions through an oracle that will not collect, whose strategy is
#: ill-posed, or that blocks on stdin. Those three stay.
#:
#: ``adequacy_floor`` and ``f2p_vacuous`` are a different animal. They do not mean *this
#: exam is broken*; they mean *this exam is too thin*. A thin exam parses fine, and it is
#: exactly when you most want to know WHICH of the operator's requirements nobody wrote an
#: assertion for — that is #1342, where an exam that could not fail deleted a page he had
#: asked for in his own words. Grouping "too thin to trust" with "too broken to parse"
#: suppressed the measurement precisely when it was most informative.
_COVERAGE_BLOCKING_CLASSES: frozenset[str] = frozenset({
    CLASS_COLLECTABILITY,
    CLASS_STRATEGY,
    CLASS_INTERACTIVE_IO,
})

# ---------------------------------------------------------------------------
# Budgets (registered in shared/timeout_registry.py — same change, the gate enforces it)
# ---------------------------------------------------------------------------

#: The advisory collectability subprocess (``py_compile`` is in-process; this bounds
#: the ``pytest --collect-only`` confirmation against the synthesised stub skeleton, and
#: its node dual — the ``node --check`` parse of a ``.mjs`` oracle, which needs a small
#: fraction of the same budget and shares the bound rather than minting a second one).
ORACLE_QA_COLLECT_TIMEOUT_S: float = 60.0
#: The FAIL-TO-PASS baseline subprocess (the oracle run once against the pre-wave
#: skeleton). Bounds a slow property test / a cold ``uv`` resolve; the oracle grades in
#: seconds, so this is an abort bound with wide margin — well under grade-time's 600 s.
ORACLE_QA_F2P_TIMEOUT_S: float = 120.0
#: The NODE FAIL-TO-PASS baseline subprocess (``node --test`` over the raw oracle against
#: the pre-wave skeleton). Its own bound rather than a reuse of the python one: node
#: resolves no wheels and starts cold in well under a second, so the python bound's margin
#: is entirely `uv`-shaped and would only delay an abort here. On expiry the stamp is
#: ``not-run`` — fail-soft, exactly as the python path.
ORACLE_QA_NODE_F2P_TIMEOUT_S: float = 60.0

#: Bounded regeneration rounds (matches the ticket's "bounded retries, 2"). ONE named
#: defect per round; after the cap a HARD residual is a COUNTED regenerate-exhausted.
MAX_REGEN_ROUNDS: int = 2

#: Runner pins — MUST match real_run_job_oracle's grade invocation (swap_ops.py) so a
#: "collectable here" verdict genuinely predicts "collectable at grade". The
#: ``test_qa_runner_pins_match_grade_path`` lock asserts this against the live source.
_QA_PYTEST_PIN = "pytest==9.1.1"
_QA_HYPOTHESIS_PIN = "hypothesis==6.155.7"

#: Windows: keep the QA subprocess console-less (mirrors swap_ops' _NO_WINDOW).
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def oracle_qa_enabled() -> bool:
    """The kill-switch: ON unless ``BLARAI_ORACLE_QA`` is a falsey token.

    Defaults ON (validate every generated oracle). Off (``0``/``false``/``no``/``off``)
    is byte-identical to the pre-#821 behaviour — the authored oracle seeds unvalidated.
    Read at each entry point so a disabled QA never spawns a subprocess or a model call."""
    return str(os.environ.get("BLARAI_ORACLE_QA", "1")).strip().lower() not in (
        "0", "false", "no", "off", ""
    )


# ---------------------------------------------------------------------------
# Result / finding types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OracleFinding:
    """One validation defect: its taxonomy class, a human message, and the subject
    (a test name, a criterion id, or a symbol) the single-focus feedback names."""

    cls: str
    message: str
    subject: str = ""

    @property
    def hard(self) -> bool:
        return self.cls in _HARD_CLASSES


@dataclass
class OracleQAResult:
    """The outcome of validating one job oracle.

    ``verdict`` is one of ``"seed"`` (clean or SOFT-only residual — seed it),
    ``"seed-partial"`` (SOFT residual with a disclosed coverage gap — seed + stamp),
    or ``"refuse"`` (a HARD residual — do NOT seed → honest job-acceptance not-run).
    ``oracle_code`` is the final (possibly regenerated) source; on ``refuse`` the
    caller drops it. The counts + coverage + f2p stamp feed #827/#832."""

    oracle_code: str
    verdict: str = "seed"
    findings: list[OracleFinding] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    covered: list[str] = field(default_factory=list)
    uncovered: list[str] = field(default_factory=list)
    coverage_denominator: int = 0
    regen_rounds: int = 0
    regen_exhausted: bool = False
    f2p_baseline: str = "not-run"
    #: ``not-run`` until the subprocess probe has actually run: the plan-time path never
    #: reaches it, and a default of ``unconfirmed`` there claimed a verdict on an exam
    #: nothing had looked at. Set by :func:`confirm_collectable` via :func:`f2p_seed_gate`.
    collectability: str = "not-run"
    language: str = "python"
    validated: bool = True
    #: WHY an execution probe produced no result (#1350). Empty when it ran. Populated by
    #: :func:`_not_run` via the seed gate; published in ``to_evidence`` under
    #: ``not_measured_detail`` so a reader can act on a `not-run` instead of only seeing it.
    f2p_diagnostics: dict = field(default_factory=dict)

    @property
    def seedable(self) -> bool:
        return self.verdict in ("seed", "seed-partial")

    def coverage_fraction(self) -> str:
        """``"k/n"`` over the test-tier criteria (behavior+smoke), or ``"unknown"``
        when no traceability map could be verified (no grammar hook / model failure)."""
        if self.coverage_denominator <= 0:
            return "unknown"
        return f"{len(self.covered)}/{self.coverage_denominator}"

    def stage_measured(self) -> dict[str, bool]:
        """Which QA stages actually produced a result on this run.

        A stage that did not run cannot have found anything, so every finding class it
        owns is unmeasured rather than clean (see :data:`CLASS_STAGE`)."""
        return {
            STAGE_STATIC: bool(self.validated),
            STAGE_COLLECTABILITY: (
                str(self.collectability).strip().lower() not in STAMPS_NOT_MEASURED
            ),
            STAGE_F2P: str(self.f2p_baseline).strip().lower() not in STAMPS_NOT_MEASURED,
            STAGE_COVERAGE: self.coverage_denominator > 0,
            STAGE_ALWAYS: True,
        }

    def not_measured(self) -> list[str]:
        """Plain sentences naming every check that did not happen. Empty ⇒ all ran."""
        measured = self.stage_measured()
        return [_STAGE_PROSE[s] for s in _STAGE_PROSE if not measured.get(s, False)]

    def to_evidence(self) -> dict:
        """The ``oracle_qa`` evidence block (stable shape) stamped into the run
        scorecard for #827 (classifier) + #832 (green-audit). Carries the full
        taxonomy count map, the coverage disclosure, the f2p stamp, and the
        regeneration accounting.

        #1342 item 2 — WHY THE MEASUREMENT BLOCK EXISTS. This record used to read
        ``validated: true, findings_total: 0`` beside ``f2p_baseline: "not-run"`` and
        ``collectability: "skipped"``. Every reader takes zero findings to mean *we looked
        and found nothing*; here it meant *we did not look*, and the oracle it was
        certifying was three-fifths vacuous. The honest field sat next to the confident one
        and lent it credibility. So the block now says, in the same breath as the count,
        which stages ran — and ``findings_conclusive`` is the single field a reader can
        trust: false whenever any stage that could have produced a finding did not run.

        Additive only: every pre-existing key keeps its name, position and meaning, so no
        consumer of this shape has to change to keep working.
        """
        counts = {c: int(self.counts.get(c, 0)) for c in ALL_CLASSES}
        measured = self.stage_measured()
        # A class is conclusive only if the stage that produces it ran.
        conclusive = {c: measured.get(CLASS_STAGE.get(c, STAGE_STATIC), False) for c in ALL_CLASSES}
        unmeasured = self.not_measured()
        if all(measured.values()):
            status = "measured"
        elif any(measured[s] for s in (STAGE_STATIC, STAGE_COLLECTABILITY, STAGE_F2P, STAGE_COVERAGE)):
            status = "partial"
        else:
            status = "unmeasured"
        return {
            "validated": self.validated,
            "language": self.language,
            "verdict": self.verdict,
            "findings": counts,
            "findings_total": sum(counts.values()),
            # The three fields that stop a zero being misread. `findings_conclusive` is
            # false when ANY stage did not run, because the total is then a floor, not a
            # count: unrun checks can only have missed things, never over-reported them.
            "findings_conclusive": all(conclusive.values()),
            "findings_measured": conclusive,
            "measurement": {"status": status, "stages": measured},
            "not_measured": unmeasured,
            "regeneration": {"rounds": self.regen_rounds, "exhausted": self.regen_exhausted},
            "oracle_coverage": self.coverage_fraction(),
            "covered": list(self.covered),
            "uncovered": list(self.uncovered),
            "f2p_baseline": self.f2p_baseline,
            "collectability": self.collectability,
            # #1350: a `not-run` that says WHY. Empty dict when the probe ran — the presence
            # of a cause here is itself the signal that an execution stage did not.
            "not_measured_detail": dict(self.f2p_diagnostics),
        }


# ---------------------------------------------------------------------------
# Import analysis (this module's own — richer than acceptance's flat contract:
# it needs the module/name split for the invented-contract check + stub synthesis)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ImportInfo:
    module: str              # the dotted module ("app.core", "storage")
    names: tuple[str, ...]   # imported names for `from m import a, b`; () for `import m`
    is_from: bool


def _stdlib_roots() -> frozenset[str]:
    """The test-runner deps + stdlib roots that are NOT first-party (lazy import of
    acceptance's single source, so the two can never drift)."""
    from shared.fleet.acceptance import _ORACLE_NON_API_ROOTS

    return _ORACLE_NON_API_ROOTS


def _first_party_imports(code: str) -> list[_ImportInfo]:
    """The oracle's FIRST-PARTY imports (module + names + kind), stdlib/test-runner
    dropped, relative imports (inside ``tests/``) skipped. Fail-soft: unparseable → []."""
    if not code:
        return []
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return []
    stdlib = _stdlib_roots()
    out: list[_ImportInfo] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:  # relative: within tests/, not a public module
                continue
            module = node.module or ""
            if not module or module.split(".", 1)[0] in stdlib:
                continue
            names = tuple(a.name for a in node.names if a.name != "*")
            out.append(_ImportInfo(module=module, names=names, is_from=True))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".", 1)[0] in stdlib:
                    continue
                out.append(_ImportInfo(module=alias.name, names=(), is_from=False))
    return out


def _first_party_symbol_names(imports: list[_ImportInfo]) -> set[str]:
    """The set of bare names that resolve to a first-party symbol — the ``from m import
    NAME`` names plus the top-level bound name of each ``import a.b.c`` (``a``)."""
    names: set[str] = set()
    for imp in imports:
        if imp.is_from:
            names.update(imp.names)
        else:
            names.add(imp.module.split(".", 1)[0])
    return names


def _test_functions(tree: ast.AST) -> list[ast.FunctionDef]:
    """Module-level + Test-class-method ``def test*`` nodes (pytest discovery contract)."""
    out: list[ast.FunctionDef] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith(
            "test"
        ):
            out.append(node)  # type: ignore[arg-type]
    return out


def _root_name(node: ast.AST) -> str:
    """The root identifier of a Name or an Attribute chain (``a.b.c`` → ``a``)."""
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else ""


def _exercises_first_party(func: ast.AST, first_party: set[str]) -> bool:
    """True iff the test EXERCISES a first-party symbol — an ``assert`` whose subtree
    references one, OR a no-raise CALL of one (the r2adequacy floor rule: a bare
    no-raise call on a first-party symbol COUNTS, so a legitimate smoke oracle like
    B6's ``run_cli()`` passes the floor and is not false-flagged)."""
    if not first_party:
        return False
    for node in ast.walk(func):
        if isinstance(node, ast.Assert):
            for sub in ast.walk(node.test):
                if isinstance(sub, (ast.Name, ast.Attribute)) and _root_name(sub) in first_party:
                    return True
        elif isinstance(node, ast.Call):
            if _root_name(node.func) in first_party:
                return True
    return False


# ---------------------------------------------------------------------------
# Static stages (pure, deterministic — no model, no subprocess)
# ---------------------------------------------------------------------------


def check_syntax(code: str) -> Optional[OracleFinding]:
    """``py_compile``-equivalent: the source must compile, and no known-invalid
    Hypothesis size kwarg (``min_length=``/``max_length=`` on a strategy — B1n1) may
    survive. The authoring path repairs the latter before we see it; this is the belt."""
    try:
        compile(code, "<job-oracle>", "exec")
    except SyntaxError as exc:
        return OracleFinding(CLASS_COLLECTABILITY, f"does not compile: {exc.msg}")
    # Residual Hypothesis-kwarg check (AST-scoped to call-site kwargs, mirrors the repair).
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return OracleFinding(CLASS_COLLECTABILITY, "does not parse")
    if "hypothesis" in code:
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg in ("min_length", "max_length"):
                return OracleFinding(
                    CLASS_COLLECTABILITY,
                    f"strategy uses `{node.arg}=` (invalid on a Hypothesis strategy — "
                    "use min_size=/max_size=); it raises TypeError at collection",
                )
    return None


#: Hypothesis strategy factories whose numeric/collection RANGE must be bounded, or they
#: can emit spec-invalid extremes (B1n2: ``st.floats()`` → 0.0 fails a ">0 amount" spec).
#: A call to one of these with NO bounding kwarg is ill-posed → regenerate.
_BOUND_REQUIRED_STRATEGIES: dict[str, frozenset[str]] = {
    "integers": frozenset({"min_value", "max_value"}),
    "floats": frozenset({"min_value", "max_value"}),
    "text": frozenset({"min_size", "max_size", "alphabet"}),
    "binary": frozenset({"min_size", "max_size"}),
    "lists": frozenset({"min_size", "max_size"}),
    "sets": frozenset({"min_size", "max_size"}),
    "dictionaries": frozenset({"min_size", "max_size"}),
}


def _strategy_call_name(func: ast.AST) -> str:
    """The strategy factory name of a call (``st.integers`` → ``integers``,
    ``strategies.floats`` → ``floats``); '' if it is not an attribute call."""
    return func.attr if isinstance(func, ast.Attribute) else ""


def scan_strategies(code: str) -> list[OracleFinding]:
    """Property-test well-posedness. A small ALLOWLIST beats verifying arbitrary
    strategies: a bound-requiring factory (``integers``/``floats``/``text``/… ) called
    with NO bounding kwarg is flagged ill-posed — it can feed spec-invalid inputs that
    convict valid work (B1n2). Conservative: only clearly-unbounded range factories
    fire; a bounded strategy (or one constrained by ``alphabet``/``sampled_from``)
    passes. 'Fail toward regeneration' — a false flag costs one cheap round."""
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return []
    if "hypothesis" not in code and "given" not in code:
        return []
    out: list[OracleFinding] = []
    seen: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _strategy_call_name(node.func)
        required = _BOUND_REQUIRED_STRATEGIES.get(name)
        if required is None:
            continue
        kwargs = {kw.arg for kw in node.keywords if kw.arg}
        if kwargs & required:
            continue  # at least one bound present → well-posed
        if name in seen:
            continue
        seen.add(name)
        out.append(OracleFinding(
            CLASS_STRATEGY,
            f"strategy `st.{name}()` is unbounded — it can generate spec-invalid inputs "
            f"and fail valid work; bound it ({'/'.join(sorted(required))}=)",
            subject=name,
        ))
    return out


def scan_interactive_io(code: str) -> list[OracleFinding]:
    """The oracle must not drive interactive I/O: ``input()`` / ``raw_input()`` calls
    or ``sys.stdin`` reads inside a test raise under pytest (no tty) and error the test
    EVERY run, so the job can never pass (B4 drove ``main()`` → OSError on stdin)."""
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return []
    out: list[OracleFinding] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id in ("input", "raw_input"):
                out.append(OracleFinding(
                    CLASS_INTERACTIVE_IO,
                    f"calls `{fn.id}()` — interactive input raises under pytest; drive "
                    "the entry point with concrete arguments instead",
                    subject=fn.id,
                ))
        elif isinstance(node, ast.Attribute):
            # sys.stdin.read / sys.stdin.readline / .readlines
            if isinstance(node.value, ast.Attribute) and node.value.attr == "stdin":
                out.append(OracleFinding(
                    CLASS_INTERACTIVE_IO,
                    "reads `sys.stdin` — interactive input raises under pytest; drive the "
                    "entry point with concrete arguments instead",
                    subject="stdin",
                ))
    # De-dupe by subject (one finding per interactive primitive).
    uniq: dict[str, OracleFinding] = {}
    for f in out:
        uniq.setdefault(f.subject, f)
    return list(uniq.values())


def scan_invented_contracts(
    code: str,
    declared_exports: set[str],
    declared_modules: "set[str] | None" = None,
) -> list[OracleFinding]:
    """A first-party imported NAME the plan never promised is an invented contract
    (B4's ``check_answer``). Precise + conservative: only a name imported ``from
    <first-party> import <name>`` and ABSENT from the declared task contracts is
    flagged — a local helper, a stdlib name, or an exported name is never touched.

    A declared name is EITHER a declared export OR a declared SUBMODULE: ``from
    flashcard_app import card_manager`` names a module the plan's ``creates`` promised,
    not a function, and Python resolves it identically. Judging a submodule import
    against the function-export set alone convicted valid work (#967 D1 — the
    20260719-002208-bd run burned both regeneration rounds re-authoring around
    ``card_manager``/``quiz_engine``/``score_tracker`` while ``oracle_coverage`` sat at
    0/6). Only these two declared sets are honoured — an unknown name is still flagged,
    which is the whole value of the check.

    Empty ``declared_exports`` disables the check (no contract to judge against →
    fail-soft, never invent a false invention); ``declared_modules`` only ever WIDENS
    what counts as declared, so it can never manufacture a new conviction."""
    if not declared_exports:
        return []
    declared = declared_exports | (declared_modules or set())
    out: list[OracleFinding] = []
    seen: set[str] = set()
    for imp in _first_party_imports(code):
        if not imp.is_from:
            continue
        for name in imp.names:
            if name in declared or name in seen:
                continue
            seen.add(name)
            out.append(OracleFinding(
                CLASS_INVENTED_CONTRACT,
                f"imports `{name}` from `{imp.module}` but the plan declares no such "
                "export or submodule — an invented contract that convicts valid work",
                subject=name,
            ))
    return out


def _is_first_party(top: str) -> bool:
    """The first-party predicate for the #826 interface-contract derivation — aligned
    with :func:`_first_party_imports` (a top package that is neither stdlib nor a
    test-runner framework), so a derived callable always has a real import behind it."""
    return bool(top) and top not in _stdlib_roots()


def _spec_corpus(spec, operator_answers: "Sequence[str] | None" = ()) -> str:
    """The lowercased REQUIREMENT TEXT THE CODER WAS ALSO GIVEN — as one searchable blob.
    The invented-RETURN check tests whether a demanded magic string is GROUNDED here; a
    value that reached only the oracle is the B4n2 invention.

    THE ADMISSION RULE, and it is NOT "the operator wrote it". A source belongs here when
    it is BOTH:

      1. **Requirement content the CODER was also given** — the finding's whole meaning is
         "this oracle demands a value the coder was never told about", so a value the coder
         saw cannot blindside them and excusing it is right no matter who phrased it. This
         is why a criterion qualifies even though the 14B WRITES the criteria
         (``generate_plan`` step 2 — the model proposes, ``rule_spec`` disposes):
         :func:`compile_prompts` puts every criterion's ``text``/``check`` verbatim into the
         coder's task prompt, so a criterion naming ``'Ledgered'`` genuinely instructed the
         coder to produce it.
      2. **A statement of what to build, not house framing.** Both parties also see our own
         prose — the requirements block's fixed header, its ``(assumed)`` tags — and that
         prose demands nothing. Admitting it grounds the judge on "person", "build",
         "requirements", excusing an oracle that asserts our own boilerplate back at us.

    Clarify QUESTIONS fail BOTH tests, which is what makes them the sharp case: the model
    writes them, they routinely name a candidate value ("Should this return 'Saved'?"), and
    :func:`shared.fleet.clarify.compose_requirements_block` renders ANSWERS only — so a
    question reaches the oracle author and never the coder. Admitting one lets the model
    launder its own invention into its own excuse, and excuses an assertion the operator's
    answer explicitly REFUSED.

    Rule 2 is why ``operator_answers`` is a SEQUENCE OF ANSWERS and never rendered prompt
    text; a caller holding a block extracts them with
    :func:`shared.fleet.clarify.operator_answers_from_block`.

    Sources, all optional:

      * ``spec.goal`` + every criterion's ``text``/``check`` — the spec as compiled into the
        coder's prompts;
      * ``spec.clarifications`` (#819) — each record's ``answer`` only;
      * ``operator_answers`` — the answers behind an enriched planning seed. ``spec.goal``
        is deliberately the CLEAN goal, so a caller that authored the oracle from an
        enriched seed MUST supply these, or the oracle is judged against a narrower corpus
        than it was written from and convicted for asserting what the operator asked for
        (#1043). Absent means "the operator supplied nothing extra", never "judge loosely".

    Fail-soft throughout: a spec with no sources yields ``''`` (which disables the check —
    never invent a false invention)."""
    parts: list[str] = [str(getattr(spec, "goal", "") or "")]
    parts.extend(str(a or "") for a in (operator_answers or ()))
    for c in getattr(spec, "criteria", ()) or ():
        parts.append(str(getattr(c, "text", "") or ""))
        parts.append(str(getattr(c, "check", "") or ""))
    for cl in getattr(spec, "clarifications", ()) or ():
        if isinstance(cl, dict):
            parts.append(str(cl.get("answer", "") or ""))
    return " ".join(p for p in parts if p).lower()


def scan_invented_return_contracts(code: str, spec_corpus: str) -> list[OracleFinding]:
    """B4n2's deep half (the return-value invention #826 adds over the import-name
    invention above) — a first-party call whose RESULT the oracle asserts equals a magic
    STRING the spec never names (``check_answer(...) == "correct"`` where the requirements
    never said "correct"). The callable may exist and import cleanly; the fabricated part
    is the DEMANDED return value, which convicts a coder who built a reasonable different
    contract, and it surfaces only as a 2am park.

    Precise + conservative (a false flag here convicts a VALID oracle — worse than the
    miss): ONLY string-literal equality on a first-party call result is judged, and ONLY
    when that string is ABSENT from the spec corpus. Numbers/booleans/None are never
    flagged (legitimately spec-derivable — ``add(2, 3) == 5`` needs no "5" in prose). A
    trivial string (empty / a single non-space char) is skipped. Empty corpus disables
    the check (no spec to judge against → never invent a false invention). SOFT class:
    it drives single-focus regeneration, never a refusal."""
    if not code or not spec_corpus:
        return []
    from shared.fleet.interface_contract import derive_interface_contract

    contract = derive_interface_contract(code, is_first_party=_is_first_party)
    out: list[OracleFinding] = []
    seen: set[tuple[str, str]] = set()
    for name, literal in contract.string_return_literals():
        norm = literal.strip()
        if len(norm) < 2:  # "", " ", a single char — too weak to call an invented contract
            continue
        if norm.lower() in spec_corpus:
            continue  # the spec names this value → a grounded, legitimate assertion
        key = (name, norm)
        if key in seen:
            continue
        seen.add(key)
        out.append(OracleFinding(
            CLASS_INVENTED_RETURN,
            f"asserts `{name}(...) == {literal!r}` but the requirements never name the "
            f"return value {literal!r} — an invented return contract that convicts a "
            "coder who built a reasonable different signature",
            subject=name,
        ))
    return out


def check_import_contract(code: str, declared_modules: set[str]) -> list[OracleFinding]:
    """Light self-consistency: the oracle's first-party MODULE surface should be within
    the modules the plan assigns (else the coder is never told to build what the oracle
    imports → ModuleNotFoundError at collection → falsely RED on plumbing). Empty
    ``declared_modules`` disables it (the deep layout check is #822/#826's job)."""
    if not declared_modules:
        return []
    out: list[OracleFinding] = []
    seen: set[str] = set()
    for imp in _first_party_imports(code):
        top = imp.module.split(".", 1)[0]
        if imp.module in declared_modules or top in declared_modules or imp.module in seen:
            continue
        seen.add(imp.module)
        out.append(OracleFinding(
            CLASS_IMPORT_CONTRACT,
            f"imports `{imp.module}`, which no plan task declares — the coder is never "
            "told to build it (collection would fail on the import)",
            subject=imp.module,
        ))
    return out


#: How many successively-numbered identifiers sharing one stem constitute a repetition
#: collapse rather than a deliberately enumerated fixture. Precision-first: a hand-written
#: test legitimately uses `item1, item2, item3`, and a generated one occasionally goes to
#: five or six. Fifty-four is not a fixture. Eight is comfortably clear of honest usage and
#: comfortably below the observed collapse.
_DEGENERACY_RUN_THRESHOLD = 8

#: `habits2`, `habits3`, ... — a stem followed by a bare integer.
_NUMBERED_IDENT_RE = re.compile(r"\b([A-Za-z_][A-Za-z_]*)(\d+)\b")


def generation_degeneracy(code: str) -> Optional[OracleFinding]:
    """The model looped instead of finishing (#1351). LANGUAGE-AGNOSTIC, no parse required.

    **The artifact.** `20260806-094526-bd` and `20260806-171303-bd` each seeded a job oracle
    of 6544 bytes ending mid-token at `const habits55 = await get`, containing `habits2`
    through `habits55` — 54 successive variables of one shape. The two files are
    **byte-identical**, because generation here is deterministic: the same prompt collapses
    the same way every time, so RETRY IS NOT A REMEDY. That is worse than a flaky truncation,
    and it is why this is worth detecting rather than absorbing.

    **Why this is not covered by the parse check.** `node --check` (and `check_syntax` on the
    Python path) catches these two files because the collapse ran into the generation budget
    mid-token. A repetition loop that happens to terminate on a statement boundary parses
    perfectly and would be seeded as a real exam — a fifty-line oracle that asserts one thing
    fifty times is a failed generation whether or not it compiles.

    Runs on raw text deliberately: a collapsed generation is frequently unparseable, which is
    exactly when this finding is most useful.

    HARD, because an exam produced by a degenerate generation is not an exam.
    """
    stems: dict[str, set[int]] = {}
    for match in _NUMBERED_IDENT_RE.finditer(code):
        stem, digits = match.group(1), match.group(2)
        if len(stem) < 2:  # `x1`, `y2` — coordinate-ish, not a generated run
            continue
        stems.setdefault(stem, set()).add(int(digits))

    for stem, seen in stems.items():
        if len(seen) < _DEGENERACY_RUN_THRESHOLD:
            continue
        # A RUN, not merely a count: consecutive integers are what a loop emits, while a
        # scattered set is more likely deliberate (error codes, HTTP statuses, years).
        ordered = sorted(seen)
        longest = run = 1
        for prev, cur in zip(ordered, ordered[1:]):
            run = run + 1 if cur == prev + 1 else 1
            longest = max(longest, run)
        if longest >= _DEGENERACY_RUN_THRESHOLD:
            return OracleFinding(
                CLASS_ADEQUACY_FLOOR,
                f"the generation collapsed into repetition: `{stem}1`..`{stem}{ordered[-1]}` "
                f"({longest} consecutive) - a failed generation, not an exam. Deterministic "
                f"sampling means a retry reproduces it byte-for-byte, so the prompt or the "
                f"sampling must change rather than the job being re-run",
                subject=stem,
            )
    return None


def adequacy_floor(code: str) -> Optional[OracleFinding]:
    """The non-vacuity floor (r2adequacy §3.5, r3adversary B1/B4): the oracle must
    import at least one first-party module AND at least one test must EXERCISE a
    first-party symbol (an assertion OR a no-raise call — the mid-build amendment, so a
    legitimate ``run_cli()`` smoke test passes). A floor failure is a vacuous oracle
    that can only ever mint a false GREEN → HARD."""
    imports = _first_party_imports(code)
    if not imports:
        return OracleFinding(
            CLASS_ADEQUACY_FLOOR,
            "imports nothing first-party — a vacuous oracle that tests no real behaviour",
        )
    first_party = _first_party_symbol_names(imports)
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return None  # a syntax finding already fired; don't double-count
    tests = _test_functions(tree)
    if any(_exercises_first_party(t, first_party) for t in tests):
        return None
    return OracleFinding(
        CLASS_ADEQUACY_FLOOR,
        "no test exercises a first-party symbol (no assertion and no no-raise call on a "
        "planned module/function) — the oracle asserts nothing real",
    )


# ---------------------------------------------------------------------------
# The criterion → test traceability matrix (grammar-declared + AST-verified)
# ---------------------------------------------------------------------------


def coverage_map_emission_json_schema(test_tier_ids: list[str]) -> dict:
    """The JSON schema for the grammar-constrained COVERAGE-MAP emission (#743 hook).

    The schema PRE-FILLS the keys — ``required`` is exactly the test-tier (behavior +
    smoke) criterion ids — so the grammar structurally cannot let the 14B close the
    emission without naming a test for EVERY objective criterion (r2adequacy rank-1: the
    model's whole job shrinks to filling a map whose keys it cannot forget). Each value
    is a non-empty array of test-function names. The DETERMINISTIC AST verify then
    disposes — a named test that does not exist, or does not exercise the criterion's
    subject, is treated as uncovered regardless of the declaration."""
    ids = list(dict.fromkeys(test_tier_ids))  # de-dup, order-preserving
    return {
        "type": "object",
        "properties": {
            cid: {"type": "array", "items": {"type": "string"}, "minItems": 1}
            for cid in ids
        },
        "required": ids,
        "additionalProperties": False,
    }


_COVERAGE_MAP_TEMPLATE = (
    "Below is a pytest ACCEPTANCE-TEST file and the numbered acceptance criteria it must "
    "verify. For EACH criterion id, list the test function name(s) in the file that "
    "assert that criterion's required behaviour. Return ONLY a JSON object mapping every "
    "criterion id to a non-empty array of test-function names (no prose).\n\n"
    "Criteria:\n{criteria}\n\n"
    "Test functions present in the file: {test_names}\n\n"
    "Oracle:\n{code}\n"
)


def _parse_coverage_map(text: str, ids: list[str]) -> dict[str, list[str]]:
    """Best-effort parse of the model emission into ``{id: [test_name]}`` — a JSON
    object whose keys are known ids and whose values are string lists. Anything else is
    dropped fail-closed (an id with no usable value is simply absent → treated as
    uncovered by the verifier). ``{}`` on any failure."""
    if not text:
        return {}
    start = text.find("{")
    if start < 0:
        return {}
    depth, in_str, esc, end = 0, False, False, -1
    for i in range(start, len(text)):
        ch = text[i]
        if esc:
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == '"':
            in_str = not in_str
        elif not in_str:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
    if end < 0:
        return {}
    try:
        data = json.loads(text[start:end])
    except (ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    id_set = set(ids)
    out: dict[str, list[str]] = {}
    for k, v in data.items():
        if k not in id_set:
            continue
        if isinstance(v, list):
            out[k] = [str(x) for x in v if isinstance(x, str) and x.strip()]
        elif isinstance(v, str) and v.strip():
            out[k] = [v.strip()]
    return out


def request_coverage_map(
    code: str,
    test_criteria: list,
    *,
    generate_fn: Callable[[str], str],
    structured_generate_fn: "Callable[[str, str], str] | None" = None,
) -> "dict[str, list[str]] | None":
    """Ask the 14B for the ``{criterion_id: [test_name]}`` map — grammar-first over the
    schema whose keys are pre-filled with the test-tier ids (#743), fail-soft to
    free-text. Returns the parsed map, or ``None`` when no usable emission was obtained
    (no grammar hook AND free-text failed) — the caller then stamps coverage 'unknown'
    rather than inventing a verdict. The model only PROPOSES the map; the AST disposes."""
    ids = [c.id for c in test_criteria]
    if not ids:
        return {}
    criteria_block = "\n".join(f"- {c.id} [{c.tier}] {c.text}" for c in test_criteria)
    try:
        tree = ast.parse(code)
        test_names = ", ".join(t.name for t in _test_functions(tree)) or "(none)"
    except (SyntaxError, ValueError):
        test_names = "(unparseable)"
    prompt = _COVERAGE_MAP_TEMPLATE.format(
        criteria=criteria_block, test_names=test_names, code=code
    )
    raw: "str | None" = None
    if structured_generate_fn is not None:
        try:
            emitted = structured_generate_fn(
                prompt, json.dumps(coverage_map_emission_json_schema(ids))
            )
        except Exception:  # noqa: BLE001 — the hook must never add a failure mode
            emitted = ""
        if emitted and _parse_coverage_map(emitted, ids):
            raw = emitted
    if raw is None:
        try:
            raw = generate_fn(prompt)
        except Exception:  # noqa: BLE001 — a coverage-map failure must not crash the plan
            return None
    parsed = _parse_coverage_map(raw or "", ids)
    return parsed if parsed else None


def verify_traceability(
    code: str,
    coverage_map: dict[str, list[str]],
    test_criteria: list,
    *,
    criterion_subjects: "dict[str, set[str]] | None" = None,
) -> tuple[list[str], list[str], list[OracleFinding]]:
    """DETERMINISTIC (AST, no model) verification of the declared coverage map against
    the oracle. A test-tier criterion is COVERED iff at least one DECLARED test for it
    (a) is a real ``def test*`` in the AST AND (b) exercises a first-party symbol — and,
    when ``criterion_subjects`` is supplied (the future #826 spec→callable map), that the
    test references the criterion's OWN subject (the tighter binding; without it, any
    first-party symbol counts). A declaration pointing at a missing test, or at a test
    that touches nothing first-party, is a FALSE declaration and the criterion is
    uncovered (this is what stops the model 'declaring' a criterion covered by an
    unrelated test — r2adequacy §3.2 step 3b).

    Returns ``(covered_ids, uncovered_ids, findings)``."""
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return ([], [c.id for c in test_criteria], [])
    tests = {t.name: t for t in _test_functions(tree)}
    first_party = _first_party_symbol_names(_first_party_imports(code))
    covered: list[str] = []
    uncovered: list[str] = []
    findings: list[OracleFinding] = []
    for crit in test_criteria:
        declared = coverage_map.get(crit.id, [])
        subjects = (criterion_subjects or {}).get(crit.id)
        ok = False
        for tname in declared:
            node = tests.get(tname)
            if node is None:
                continue
            symbols = subjects if subjects else first_party
            if _exercises_first_party(node, symbols):
                ok = True
                break
        if ok:
            covered.append(crit.id)
        else:
            uncovered.append(crit.id)
            findings.append(OracleFinding(
                CLASS_TRACEABILITY,
                f"criterion {crit.id} ('{crit.text}') has no verified test assertion",
                subject=crit.id,
            ))
    return (covered, uncovered, findings)


# ---------------------------------------------------------------------------
# Execution stages (subprocess) — collectability confirmation + FAIL-TO-PASS baseline
# ---------------------------------------------------------------------------


def _default_run(cmd: list[str], cwd: str, timeout_s: float, env: dict) -> tuple[bool, str, str]:
    """The QA's own bounded subprocess primitive (injectable for tests). Returns
    ``(ok, stdout, stderr)`` — ``ok = (returncode == 0)``, fail-closed. Console-less on
    Windows; the caller owns the isolated cwd + env (LOCALAPPDATA/PYTHONPATH).

    Routed through ``shared.procspawn.hidden_console`` (#774 sub-task 2): the blessed twin
    of this shape (``subprocess.run`` + ``CREATE_NO_WINDOW`` == ``_NO_WINDOW`` above). The
    caller's full ``env`` is passed as-is (hidden_console replaces the child env with it,
    exactly as before) plus the lesson-219 UTF-8/DEVNULL-stdin pins."""
    try:
        cp = procspawn.hidden_console(cmd, cwd=cwd, timeout_s=timeout_s, env=env)
        return (cp.returncode == 0, cp.stdout or "", cp.stderr or "")
    except subprocess.TimeoutExpired:
        return (False, "", "TIMEOUT")
    except Exception as exc:  # noqa: BLE001 — machinery failure → honest not-run upstream
        return (False, "", f"{type(exc).__name__}: {exc}")


def _clean_ini(workdir: Path) -> Path:
    """Write the harness-owned clean pytest config into ``workdir`` and return its path —
    the ``grade_env`` SSOT (#839): byte-shared with the host grade + guest twin so a
    'collectable here' verdict grades under the exact recipe used at grade time. (Was an
    inline ``[pytest]``/empty-``addopts`` redeclaration; ``CLEAN_GRADE_INI_CONTENT`` adds
    only comments — which pytest ignores — so behavior is byte-identical.)"""
    return grade_env.write_clean_grade_ini(workdir)


def _qa_env(isolated_home: Path, extra_path: "str | None" = None) -> dict:
    """A subprocess env with LOCALAPPDATA/APPDATA redirected into an isolated dir (never
    touch the operator's app data — the standing 'LOCALAPPDATA-redirected pytest'
    discipline), bytecode off, and safe-path on (deny cwd/``.pth`` injection). ``extra_path``
    prepends a repo root to PYTHONPATH so the oracle's first-party imports resolve.

    The clean-env overlay (PYTHONSAFEPATH + the PYTHONPATH base) is the ``grade_env`` SSOT
    (#839). QA-specific deviation preserved for byte-identical behavior: this PREPENDS
    ``extra_path`` onto any inherited PYTHONPATH (the collect-stub / skeleton root wins, but
    a carried path still resolves), where ``grade_env.clean_grade_env`` REPLACES.

    uv's own directories are pinned to their real locations FIRST — see
    :func:`grade_env.uv_dir_overlay` for why the redirect would otherwise silently change
    which interpreter runs the probes below."""
    env = dict(os.environ)
    env.update(grade_env.uv_dir_overlay(env))
    env["LOCALAPPDATA"] = str(isolated_home)
    env["APPDATA"] = str(isolated_home)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    # #1200: the SECOND lock on the same defect. `--color=no` in the clean recipe already
    # stops PYTEST colouring, and that is the output actually parsed; this stops everything
    # ELSE in the blob (uv's own progress lines, a plugin's banner) from carrying escapes
    # into `_run_completed`. Inherited colour is the failure mode — a parent that exports
    # FORCE_COLOR turned a vacuous-oracle conviction into `not-run` — so the variables are
    # dropped rather than trusted, and NO_COLOR is set for tools that honour only that.
    env["NO_COLOR"] = "1"
    for _colour_var in ("FORCE_COLOR", "CLICOLOR_FORCE", "PY_COLORS", "CLICOLOR"):
        env.pop(_colour_var, None)
    overlay = grade_env.clean_grade_env(extra_path or "")
    env["PYTHONSAFEPATH"] = overlay["PYTHONSAFEPATH"]
    if extra_path:
        prior = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = overlay["PYTHONPATH"] + (os.pathsep + prior if prior else "")
    return env


def _pytest_cmd(oracle_path: str, clean_ini: Path, *, collect_only: bool) -> "list[str] | None":
    """Build the clean-env pytest invocation (uv-with-pins for grade-time parity, falling
    back to the current interpreter). The clean-recipe flags (``--noconftest -c clean.ini
    -o addopts= --import-mode=importlib``) are the ``grade_env`` SSOT (#839). ``None`` if no
    runner is available.

    VERBOSITY IS LOAD-BEARING and is owned here rather than by the caller. A collect-only
    run is read by exit code plus a collection signal, so it stays quiet; an executing run
    is read PER TEST by :func:`_passed_tests`, which needs the ``<file>::<name> PASSED``
    lines only ``-v`` emits. ``-q`` and ``-v`` are a single counter in pytest, so the two
    together cancel to the default dot output and every per-test name parses as absent.

    Keeping ``-q`` on the collect-only path is a CHOICE, not a necessity, and it has a cost
    worth naming: pytest's non-quiet header prints ``platform win32 -- Python 3.13.12 ...``,
    which would have exposed #1200's interpreter substitution directly in the output. It is a
    version banner rather than an interpreter identity, and reading it would put the collect
    parser in the business of headers it otherwise ignores — so parity is established from the
    environment BEFORE the spawn (:func:`grade_env.uv_parity_is_vouched`) instead. If that
    pre-spawn check ever proves insufficient, this is the first lever to revisit."""
    import shutil

    base = [
        "-m", "pytest", "-q" if collect_only else "-v",
        *grade_env.clean_pytest_args(clean_ini),
        "-p", "no:cacheprovider",
    ]
    if collect_only:
        base.append("--collect-only")
    else:
        base += ["-p", "no:randomly", "--tb=no"]
    base.append(oracle_path)
    uv = shutil.which("uv")
    if uv:
        return [uv, "run", "--no-project", "--with", _QA_PYTEST_PIN,
                "--with", _QA_HYPOTHESIS_PIN, "python", *base]
    if shutil.which(sys.executable) or Path(sys.executable).exists():
        return [sys.executable, *base]
    return None


def _synthesize_skeleton(code: str, workdir: Path) -> None:
    """Create INERT stub modules for the oracle's first-party imports under ``workdir``,
    so ``pytest --collect-only`` can IMPORT the module and evaluate its decorators /
    strategies (surfacing a collection-time TypeError/InvalidArgument the pure AST pass
    cannot see). Each stub uses a module-level ``__getattr__`` returning a universal
    callable, so any imported name resolves. Used ONLY for the ADVISORY collect-only
    confirmation — NEVER for the FAIL-TO-PASS baseline (inert stubs would false-pass a
    smoke test; the F2P baseline runs against the REAL pre-wave skeleton)."""
    stub_body = (
        "def __getattr__(name):\n"
        "    def _inert(*a, **k):\n"
        "        return None\n"
        "    return _inert\n"
    )
    for imp in _first_party_imports(code):
        parts = imp.module.split(".")
        # All but the last component are packages; the last is the module hosting
        # __getattr__ (which resolves both `import a.b` and `from a.b import name`).
        cur = workdir
        for pkg in parts[:-1]:
            cur = cur / pkg
            cur.mkdir(parents=True, exist_ok=True)
            init = cur / "__init__.py"
            if not init.exists():
                init.write_text(stub_body, encoding="utf-8")
        leaf = parts[-1]
        pkg_dir = cur / leaf
        mod_file = cur / f"{leaf}.py"
        # Prefer a plain module file; if a package dir already exists for this name, stub
        # its __init__ instead (a later `import a.b.c` created the dir).
        if pkg_dir.is_dir():
            init = pkg_dir / "__init__.py"
            if not init.exists():
                init.write_text(stub_body, encoding="utf-8")
        elif not mod_file.exists():
            mod_file.write_text(stub_body, encoding="utf-8")


def confirm_collectable(
    code: str, *, run: "Callable[..., tuple[bool, str, str]]" = _default_run
) -> tuple[str, Optional[OracleFinding]]:
    """ADVISORY collectability confirmation (r3adversary H6): synthesise inert stubs so
    the oracle's imports resolve, then ``pytest --collect-only --noconftest -c clean.ini``.
    Returns ``(stamp, finding)`` where stamp ∈ {``confirmed``, ``parity-unverified``,
    ``unconfirmed``, ``not-run``, ``skipped``}.

    Deliberately CANNOT false-park a valid oracle: a clean collect stamps ``confirmed``;
    a non-zero exit stamps ``unconfirmed`` (the stub synthesis could be imperfect — an
    inert name used as a constant, a missed module) and returns NO finding UNLESS the
    output carries an unambiguous structural-defect signature that the stubs could not
    have caused (a SyntaxError, or a Hypothesis InvalidArgument with no import error).
    The sound HARD collectability finding is :func:`check_syntax`'s in-process compile;
    this only ever ADDS confidence, never subtracts it.

    ``not-run`` is the fail-loud stamp and the reason this probe can be trusted at all: a
    runner that dies BEFORE pytest reports anything (a missing runner, a timeout, an
    interpreter whose site-packages break plugin load) produced no evidence about the
    oracle, and saying ``unconfirmed`` there would dress a machinery miss as a verdict on
    the exam. Checked FIRST, because nothing a runner printed on its way down is evidence.
    An unrun probe is the one result a reader must never be able to mistake for a measured
    one — which is exactly what ``unconfirmed`` did on every invocation on this host.

    ``parity-unverified`` closes the gap ``not-run`` cannot. Pinning uv's directories is
    AVOIDANCE, and avoidance fails silently: where the pin does not take and the fallback
    interpreter happens to WORK, the collect genuinely succeeds and ``confirmed`` is true
    about collectability while being silently false about the thing the pin exists for — that
    this verdict was reached on the interpreter the grade will use. Nothing fails, so no
    fail-loud stamp can fire. The precondition is therefore checked BEFORE spawning, from the
    env we are about to hand over, and a run we cannot vouch for reports what it is instead
    of borrowing the clean word."""
    with tempfile.TemporaryDirectory(prefix="oracle_qa_collect_") as td:
        workdir = Path(td)
        oracle = workdir / "test_job_acceptance.py"
        oracle.write_text(code, encoding="utf-8")
        _synthesize_skeleton(code, workdir)
        clean = _clean_ini(workdir)
        cmd = _pytest_cmd("test_job_acceptance.py", clean, collect_only=True)
        if cmd is None:
            return ("skipped", None)
        env = _qa_env(workdir, extra_path=str(workdir))
        # Checked BEFORE the spawn: once uv has silently fallen back, a successful collect
        # looks identical either way, so the only place this is still decidable is here.
        unpinned = (grade_env.runner_is_uv(cmd)
                    and not grade_env.uv_parity_is_vouched(env))
        ok, out, err = run(cmd, str(workdir), ORACLE_QA_COLLECT_TIMEOUT_S, env)
        if ok:
            return ("parity-unverified" if unpinned else "confirmed", None)
        blob = (out + "\n" + err)
        if not _run_completed(blob):
            return ("not-run", None)
        low = blob.lower()
        import_miss = ("modulenotfounderror" in low or "importerror" in low)
        structural = (
            "syntaxerror" in low or "indentationerror" in low
            or "invalidargument" in low or "flaky" in low
        )
        if structural and not import_miss:
            return ("unconfirmed", OracleFinding(
                CLASS_COLLECTABILITY,
                f"pytest could not collect the oracle: {_tail(blob)}",
            ))
        return ("unconfirmed", None)


def _not_run(
    diagnostics: "dict | None",
    cause: str,
    detail: str,
    *,
    elapsed_s: "float | None" = None,
    cmd: "list[str] | None" = None,
    stdout: str = "",
    stderr: str = "",
) -> tuple[str, list[OracleFinding]]:
    """Return the ``not-run`` stamp and, when the caller supplied a dict, WHY.

    #1350. ``not-run`` is fail-loud but it was never DIAGNOSTIC: it says the probe produced
    no result and nothing else. All 81 banked ``oracle-qa.json`` records carry it, across
    both ecosystems since 2026-07-12, and nobody could tell from the record whether the
    runner was missing, timed out, or died on its way up — so the single most load-bearing
    check in the QA system reported the same word for a month and no one could act on it.

    **The stamp string is EXACTLY ``not-run`` and must stay so.** Several gates decide
    whether an oracle may delete work by membership test against
    :data:`STAMPS_NOT_MEASURED` (``swap_driver._oracle_execution_validated``), and a
    decorated stamp like ``not-run:timeout`` would fail that test — turning an unvalidated
    oracle back into evidence, which is precisely the #1342 amputation. The cause therefore
    rides in a SEPARATE dict, never in the stamp.

    Output is tail-truncated: a runner that died mid-plugin-load can emit a great deal, and
    a diagnostic nobody can read is the defect wearing the fix's uniform.
    """
    if diagnostics is not None:
        diagnostics.update({
            "cause": cause,
            "detail": detail,
            "elapsed_s": elapsed_s,
            "cmd": " ".join(str(c) for c in cmd) if cmd else "",
            "stdout_tail": (stdout or "")[-800:],
            "stderr_tail": (stderr or "")[-800:],
        })
    return ("not-run", [])


def fail_to_pass_baseline(
    code: str,
    skeleton_dir: str,
    *,
    run: "Callable[..., tuple[bool, str, str]]" = _default_run,
    diagnostics: "dict | None" = None,
) -> tuple[str, list[OracleFinding]]:
    """The FAIL-TO-PASS baseline (r1extern lever 1 / SWE-bench F→P / AgentLens Lucky
    Pass): run the oracle ONCE against the PRE-IMPLEMENTATION skeleton and require EVERY
    test to fail/error. A test that PASSES there is vacuous / non-discriminating — it can
    only ever mint a false GREEN.

    Returns ``(stamp, findings)`` where stamp ∈ {``all-fail``, ``parity-unverified``,
    ``vacuous:<names>``, ``not-run``}. ``all-fail`` (or a collection error — nothing passed)
    is clean. ``vacuous:...`` names the passing tests and yields a HARD finding per test. Any
    machinery failure (no runner, timeout, unreadable output) is an honest ``not-run``
    with NO finding — the discrimination check is best-effort, and a machinery miss must
    never block a dispatch (only a CONFIRMED vacuous pass is a gate defect).

    ``parity-unverified`` is ``all-fail``'s honest form when the runner could not be vouched
    for (see :func:`grade_env.uv_parity_is_vouched`). ONLY the clean outcome is
    downgraded, and deliberately so. A CLEAN verdict from an interpreter nobody chose is the
    false-green this gate exists to prevent, so it does not get to borrow the clean word. A
    vacuous verdict is left convicting: a test that PASSES with no implementation present is
    evidence whichever interpreter observed it, and downgrading a HARD finding would weaken
    the gate — a capability change, not a defect fix. Findings are identical either way, so
    the seed proceeds exactly as before; what changes is that the evidence stops claiming
    more than it measured."""
    _t0 = time.monotonic()
    try:
        repo = Path(skeleton_dir)
        if not repo.is_dir():
            return _not_run(diagnostics, "skeleton-absent",
                            f"the pre-implementation skeleton does not exist: {skeleton_dir}")
        clean = _clean_ini(repo)
        rel = "_qa_f2p_probe.py"
        probe = repo / rel
        probe.write_text(code, encoding="utf-8")
        try:
            cmd = _pytest_cmd(rel, clean, collect_only=False)
            if cmd is None:
                return _not_run(diagnostics, "no-runner",
                                "neither uv nor the current interpreter could be resolved, "
                                "so no pytest invocation could be built")
            # (verbosity is _pytest_cmd's — appending -v here cancelled its -q instead)
            with tempfile.TemporaryDirectory(prefix="oracle_qa_home_") as home:
                env = _qa_env(Path(home), extra_path=str(repo))
                # Decided BEFORE the spawn, as in confirm_collectable: after a silent uv
                # fallback a successful run is indistinguishable from a vouched one.
                unpinned = (grade_env.runner_is_uv(cmd)
                            and not grade_env.uv_parity_is_vouched(env))
                ok, out, err = run(cmd, str(repo), ORACLE_QA_F2P_TIMEOUT_S, env)
            blob = out + "\n" + err
            passed = _discriminating_tests(_passed_tests(blob))
            if passed:
                findings = [
                    OracleFinding(
                        CLASS_F2P_VACUOUS,
                        f"test `{name}` PASSES on the pre-implementation skeleton — it is "
                        "vacuous (asserts nothing that needs the implementation)",
                        subject=name,
                    )
                    for name in passed
                ]
                return (f"vacuous:{','.join(passed)}", findings)
            # Nothing passed. Distinguish a real discriminating run (every test failed /
            # errored on the missing implementation → clean) from a machinery miss (uv
            # absent, a timeout, a crash → honest not-run, never a false 'clean') — and
            # from a run that completed on an interpreter we could not vouch for.
            if _run_completed(blob):
                return ("parity-unverified" if unpinned else "all-fail", [])
            return _not_run(
                diagnostics, "runner-produced-nothing",
                "the runner exited without pytest reporting a result - a timeout, a crash "
                "before plugin load, or an interpreter that died on its way up",
                elapsed_s=round(time.monotonic() - _t0, 2), cmd=cmd, stdout=out, stderr=err)
        finally:
            try:
                probe.unlink()
            except OSError:
                pass
            try:
                clean.unlink()
            except OSError:
                pass
    except Exception as exc:  # noqa: BLE001 — machinery failure is an honest not-run
        return _not_run(diagnostics, "raised",
                        f"the baseline raised {type(exc).__name__}: {exc}")


def _discriminating_tests(passed: list[str]) -> list[str]:
    """Drop the tests F2P's premise does not apply to, leaving those whose pre-implementation
    PASS really is evidence of vacuity.

    Exactly one class is dropped today: the machine-injected bad-input floor (#1044, reserved
    prefix ``bad_input_floor.FLOOR_TEST_PREFIX``). F2P asks "does this test discriminate an
    implemented build from an empty one", and treats a pre-implementation pass as proof the
    test can only ever mint a false GREEN. A floor test legitimately answers no. It is a FLOOR,
    not a discriminator: on a brownfield tree whose entry point already exists and already
    validates its input, it passes before any wave runs and is still doing precisely its job.
    Left in the set it would be classed CONFIRMED-vacuous, which is a HARD finding, which
    REFUSES the whole job oracle — so a floor added to strengthen grading would instead delete
    grading for the entire dispatch, and the more defensively the existing code was written the
    more certainly it would happen.

    Deliberately a PREFIX allowlist over reserved, machine-owned names and nothing else: a
    model-authored test that passes pre-implementation is still vacuous and still convicted.
    The parsing stays in :func:`_passed_tests`, which reports what the run said; this decides
    what that means, and the two are kept apart so neither has to lie for the other.
    """
    from shared.fleet.bad_input_floor import FLOOR_TEST_PREFIX

    return [name for name in passed if not name.startswith(FLOOR_TEST_PREFIX)]


#: ANSI SGR escapes. Stripped before every parse below — the THIRD lock on #1200, and the
#: only one that does not depend on controlling the producer. `--color=no` in the clean
#: recipe and the colour-var scrub in `_qa_env` both stop pytest emitting escapes; this
#: makes the reader immune to them however they arrive (a plugin banner, a future runner, a
#: caller that builds its own blob). Measured 2026-08-15: coloured output put an escape
#: between the test name and PASSED, so a VACUOUS oracle — one that passes with no
#: implementation present — stamped `not-run` instead of being convicted. A grader that
#: reads output as text must not be defeated by how that text is decorated.
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def _passed_tests(output: str) -> list[str]:
    """Parse pytest ``-v`` output for the names of tests that PASSED (the vacuous set).
    Matches ``<file>::<name> PASSED`` and ``<name> PASSED`` shapes; de-duped,
    order-preserving. A collection error / all-fail run yields none.

    ANSI-tolerant: see :data:`_ANSI_RE`."""
    import re

    out: list[str] = []
    seen: set[str] = set()
    for line in _ANSI_RE.sub("", output).splitlines():
        m = re.search(r"(?:::)?([A-Za-z_]\w*)\s+PASSED\b", line)
        if not m:
            continue
        name = m.group(1)
        if name.startswith("test") and name not in seen:
            seen.add(name)
            out.append(name)
    return out


#: Pytest's end-of-run count line — ``1 failed in 0.02s``, ``no tests collected, 1 error``.
#: Anchored on a COUNT so a prose sentence containing the same word cannot match.
_PYTEST_COUNT_RE = re.compile(
    r"\b\d+\s+(passed|failed|error|errors|skipped|deselected|xfailed|xpassed)\b")

#: Pytest's collection line — the other shape that only exists once pytest has run.
_PYTEST_COLLECTED_RE = re.compile(r"\bcollected\s+\d+\s+items?\b")

#: Pytest's FAILURES section header. A repo whose ``addopts`` suppresses the short summary
#: (``-rN --tb=no``) produces a RED run carrying this banner and NO count line — so without
#: this, such a run reads as a machinery miss.
#:
#: THIS ONE IS NOT OPTIONAL, AND DROPPING IT MOVED A REGISTERED INSTRUMENT. The old
#: unanchored ``"=== "`` acceptance was removed here for a good reason (a uv network error
#: matched it), but ``_run_completed`` is NOT private to this module: ``oracle_mutation``
#: calls it from ``_mutant_verdict``, where "the run completed and failed" means the mutant
#: was KILLED and "the run did not complete" means NOT COUNTED. Measured on this branch
#: before the fix: ``_mutant_verdict(False, <banner>)`` returned ``None`` where main returned
#: ``False`` — a genuine kill silently leaving both ``oracle_mutation_killed`` and
#: ``oracle_mutation_ran`` (registered counts, ``shared/instrument_registry.py``). Main's own
#: ``test_oracle_mutation.py`` stayed GREEN through that change, because ``failing_tests``
#: and ``_run_completed`` read the same blob by different routes.
#:
#: Anchored to a whole line so the sentence "=== FAILURES ===" in prose cannot match, which
#: keeps the win the anchoring pass was for.
_PYTEST_FAILURES_RE = re.compile(r"^=+\s*FAILURES\s*=+$", re.M)

#: Phrases pytest emits verbatim when it ran and had nothing to report.
_PYTEST_COMPLETION_PHRASES = (
    "no tests ran",
    "no tests collected",
    "errors during collection",
    "error collecting",
)


def _run_completed(output: str) -> bool:
    """True iff pytest actually RAN the file (vs a machinery miss). Matches a pytest
    summary/collection signal so a timeout / missing-runner / crash (no such signal) is
    an honest ``not-run`` rather than a false ``all-fail``.

    DELIBERATELY ANCHORED, and the anchoring is load-bearing. This once accepted the bare
    substrings ``" passed"``, ``" failed"``, ``" error"`` and ``"=== "``, which any English
    sentence can contain — ``error: Failed to fetch ... Request failed after 3 retries`` is a
    uv network failure that matched ``" failed"``, and :func:`fail_to_pass_baseline` would
    read the resulting "completed run with nothing passing" as ``all-fail``: CLEAN, from a run
    that never executed a test. A machinery miss must never be able to spell itself like a
    result, so every accepted shape here is one only pytest produces — a count, a collection
    line, or a phrase it emits verbatim.

    ANSI-tolerant (see :data:`_ANSI_RE`), as DEFENCE IN DEPTH rather than as an observed
    fix. Measured honestly: on real coloured pytest output this matcher was NOT blinded —
    pytest wraps the escapes around ``1 passed``, leaving the count phrase contiguous, so the
    anchors still matched. Only :func:`_passed_tests` actually broke, because there the
    escape lands between the test name and ``PASSED``. The strip is here so that a matcher
    whose correctness currently rests on where a third party happens to place its escapes
    stops resting on that. Stripping keeps the anchoring strict rather than loosening it —
    the fix for a matcher blinded by decoration is to remove the decoration, never to widen
    the match until the decorated form fits."""
    if not output:
        return False
    low = _ANSI_RE.sub("", output).lower()
    if _PYTEST_COUNT_RE.search(low) or _PYTEST_COLLECTED_RE.search(low):
        return True
    # Searched against the ORIGINAL, not ``low``: the banner is upper-case and the pattern
    # is written that way so it reads like the thing it matches.
    if _PYTEST_FAILURES_RE.search(output):
        return True
    return any(s in low for s in _PYTEST_COMPLETION_PHRASES)


def _tail(text: str, cap: int = 300) -> str:
    """A structural, capped tail of subprocess output for an evidence line."""
    flat = " ".join(str(text or "").split())
    return flat[-cap:] if len(flat) > cap else flat


# ---------------------------------------------------------------------------
# Regeneration (single-focus, keep-and-append — the small-model discipline)
# ---------------------------------------------------------------------------


def single_focus_feedback(finding: OracleFinding) -> str:
    """ONE short, single-focus instruction naming exactly one defect (#740 c.1721 — a
    small model acts on a narrow correction, not a broad critique)."""
    if finding.cls == CLASS_STRATEGY:
        return (f"The Hypothesis strategy `st.{finding.subject}()` is unbounded and can "
                "generate spec-invalid inputs. Bound it (add min/max), keeping every "
                "other test unchanged.")
    if finding.cls == CLASS_INTERACTIVE_IO:
        return (f"A test uses `{finding.subject}` (interactive input), which raises under "
                "pytest. Replace it by calling the entry point with concrete arguments, "
                "keeping every other test unchanged.")
    if finding.cls == CLASS_INVENTED_CONTRACT:
        return (f"A test imports/asserts `{finding.subject}`, which the specification "
                "never defined. Remove that invented contract and assert only the declared "
                "behaviour, keeping every other test unchanged.")
    if finding.cls == CLASS_INVENTED_RETURN:
        return (f"A test asserts what `{finding.subject}(...)` RETURNS using a specific "
                "value the requirements never state. Assert only the behaviour the spec "
                "describes (not an invented return value), keeping every other test "
                "unchanged.")
    if finding.cls == CLASS_IMPORT_CONTRACT:
        return (f"The oracle imports `{finding.subject}`, which no task builds. Import only "
                "the modules the plan declares, keeping every other test unchanged.")
    if finding.cls == CLASS_ADEQUACY_FLOOR:
        return ("The oracle asserts nothing about the real code. Add at least one test that "
                "calls a planned first-party function and asserts its required behaviour.")
    if finding.cls == CLASS_COLLECTABILITY:
        return (f"The oracle cannot be collected: {finding.message}. Fix that one problem, "
                "keeping every other test unchanged.")
    return finding.message


_APPEND_TEST_TEMPLATE = (
    "Write ONE pytest test function that verifies this single acceptance criterion, "
    "and NOTHING else. Return ONLY the function definition (no prose, no imports, no "
    "fences).\n"
    "Criterion: {text}\n"
    "It MUST call the first-party function(s) the project provides with concrete inputs "
    "and assert the REQUIRED behaviour (never assert what the code merely happens to do). "
    "Name it test_<behaviour>.\n"
)

_REAUTHOR_TEMPLATE = (
    "Here is a pytest acceptance-test file with ONE problem to fix:\n{feedback}\n\n"
    "Return the COMPLETE corrected file. Keep every existing test function unchanged "
    "EXCEPT as strictly needed to fix that one problem; add no unrelated tests. Return "
    "ONLY Python code (no prose, no markdown fences).\n\n{code}\n"
)


def _reauthor(code: str, feedback: str, generate_fn: Callable[[str], str]) -> "str | None":
    """Whole-file single-focus re-emit (keep all other tests). Returns validated code or
    ``None`` (the round failed — counts toward exhaustion)."""
    from shared.fleet.acceptance import (
        _extract_python_code, _has_test_function, _repair_hypothesis_strategy_kwargs,
    )

    try:
        raw = generate_fn(_REAUTHOR_TEMPLATE.format(feedback=feedback, code=code))
    except Exception:  # noqa: BLE001
        return None
    new = _repair_hypothesis_strategy_kwargs(_extract_python_code(raw))
    if not new:
        return None
    try:
        tree = ast.parse(new)
    except (SyntaxError, ValueError):
        return None
    return new if _has_test_function(tree) else None


def _append_one_test(code: str, criterion, generate_fn: Callable[[str], str]) -> "str | None":
    """Keep-and-append: ask for ONE test covering the uncovered criterion and append it
    to the oracle (never re-author the file — r2adequacy §3.2 step 4). Returns the
    extended code, or ``None`` if the emitted function is not a valid single test."""
    from shared.fleet.acceptance import _extract_python_code, _repair_hypothesis_strategy_kwargs

    try:
        raw = generate_fn(_APPEND_TEST_TEMPLATE.format(text=criterion.text))
    except Exception:  # noqa: BLE001
        return None
    snippet = _repair_hypothesis_strategy_kwargs(_extract_python_code(raw))
    if not snippet:
        return None
    try:
        snippet_tree = ast.parse(snippet)
    except (SyntaxError, ValueError):
        return None
    if not any(
        isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test")
        for n in snippet_tree.body
    ):
        return None
    combined = code.rstrip() + "\n\n\n" + snippet.strip() + "\n"
    try:
        ast.parse(combined)  # the append must keep the file collectable
    except (SyntaxError, ValueError):
        return None
    return combined


# ---------------------------------------------------------------------------
# Orchestrators
# ---------------------------------------------------------------------------


def _declared_symbols(tasks: list[dict]) -> tuple[set[str], set[str]]:
    """From the plan tasks' ruler-validated contracts, the declared (export_names,
    module_top_names). Exports like ``"save(x)"`` → name ``save``; creates like
    ``"src/storage.py"`` → module tops ``src`` + ``storage``."""
    import re

    exports: set[str] = set()
    modules: set[str] = set()
    for t in tasks:
        contract = t.get("contract") if isinstance(t.get("contract"), dict) else {}
        for e in contract.get("exports", []) or []:
            m = re.match(r"\s*([A-Za-z_]\w*)", str(e))
            if m:
                exports.add(m.group(1))
        for c in contract.get("creates", []) or []:
            stem = Path(str(c)).name
            if stem.endswith(".py"):
                stem = stem[:-3]
            mod = re.sub(r"[^A-Za-z0-9_]", "", stem)
            if mod:
                modules.add(mod)
            # also the top package dir, if any (src/storage.py → src)
            parts = str(c).replace("\\", "/").split("/")
            if len(parts) > 1 and re.match(r"^[A-Za-z_]\w*$", parts[0]):
                modules.add(parts[0])
    return (exports, modules)


def _static_findings(
    code: str, exports: set[str], modules: set[str], spec_corpus: str = "",
    *, ecosystem: str = "",
) -> list[OracleFinding]:
    """Run the AST-decidable static stages in priority order. If the syntax check fires,
    return it alone (everything downstream is moot on unparseable code)."""
    # BEFORE the syntax short-circuit, deliberately. A collapsed generation usually does not
    # parse (it stops mid-token when the budget runs out), so running this after the return
    # would mean it never fires on the case it was written for. Reporting "the generation
    # collapsed" is also strictly more actionable than "it does not parse": the first names a
    # cause a retry cannot cure, the second names a symptom.
    degeneracy = generation_degeneracy(code)
    # #1410 NOTE, kept because it explains why this function takes an ecosystem it barely
    # uses: every stage below parses `code` as PYTHON — `check_syntax` calls
    # `compile(code, ..., "exec")` and the scanners walk a Python AST. Handed a `.mjs` exam
    # they say nothing true; measured on the real 2026-08-14 B9 exam, this returns exactly
    # `['collectability']`, a false "does not compile" on valid JavaScript, and short-circuits
    # everything else away. That is why node is routed to `_validate_node_oracle` BEFORE this
    # is reached, rather than being guarded stage by stage in here.
    if str(ecosystem or "").strip().lower() == "node":  # pragma: no cover — routed earlier
        raise AssertionError(
            "a node oracle must not reach the python static pass — "
            "validate_authored_oracle routes it to _validate_node_oracle"
        )
    syntax = check_syntax(code)
    if syntax is not None:
        return [degeneracy, syntax] if degeneracy is not None else [syntax]
    findings: list[OracleFinding] = []
    if degeneracy is not None:
        findings.append(degeneracy)
    findings += scan_strategies(code)
    findings += scan_interactive_io(code)
    floor = adequacy_floor(code)
    if floor is not None:
        findings.append(floor)
    findings += scan_invented_contracts(code, exports, modules)
    findings += scan_invented_return_contracts(code, spec_corpus)
    findings += check_import_contract(code, modules)
    return findings


def _priority(finding: OracleFinding) -> int:
    order = {
        CLASS_COLLECTABILITY: 0, CLASS_STRATEGY: 1, CLASS_INTERACTIVE_IO: 2,
        CLASS_ADEQUACY_FLOOR: 3, CLASS_INVENTED_CONTRACT: 4, CLASS_INVENTED_RETURN: 5,
        CLASS_IMPORT_CONTRACT: 6, CLASS_TRACEABILITY: 7,
    }
    return order.get(finding.cls, 9)


def _validate_node_oracle(
    code: str,
    result: "OracleQAResult",
    *,
    generate_fn: Callable[[str], str],
    reauthor: bool = True,
) -> "OracleQAResult":
    """#1410 — the bounded single-focus repair loop for a NODE exam.

    The python path's loop in :func:`validate_authored_oracle` cannot be reused directly:
    every stage it runs walks a Python AST, and on JavaScript `check_syntax` reports a false
    "does not compile" that short-circuits the rest. So this runs the stages that ARE
    decidable on JS — :func:`node_static_vacuity` per test, plus the language-agnostic
    collapsed-generation check — through the same regenerate-one-named-defect discipline.

    What it deliberately does NOT do:

    * **no traceability/coverage map.** That stage resolves criteria against Python symbols;
      claiming a coverage number for node here would be inventing one, and an unmeasured
      figure presented as measured is the failure this whole module exists to refuse.
      ``oracle_coverage`` stays unknown, as it is today.
    * **no execution probes.** ``collectability`` stays ``"skipped"``: the fail-to-pass
      baseline and collectability checks belong to :func:`_node_seed_gate` and still run
      there. This function adds a repair opportunity; it removes no defence.

    A HARD residual after the bounded rounds refuses, exactly as the python path does — but
    now ``regen_exhausted`` means the model was actually asked and could not fix it, rather
    than nobody having asked.
    """
    counts: dict[str, int] = result.counts or {c: 0 for c in ALL_CLASSES}
    rounds = 0
    residual: list[OracleFinding] = []

    while True:
        findings = list(node_static_vacuity(code))
        degeneracy = generation_degeneracy(code)
        if degeneracy is not None:
            findings.insert(0, degeneracy)
        for f in findings:
            counts[f.cls] = counts.get(f.cls, 0) + 1
        if not findings:
            residual = []
            break
        if not reauthor or rounds >= MAX_REGEN_ROUNDS:
            residual = findings
            break
        target = min(findings, key=_priority)
        rounds += 1
        new_code = _reauthor(code, single_focus_feedback(target), generate_fn)
        if new_code is None or new_code == code:
            # The round produced nothing usable — stop rather than burn the next one on a
            # model that is not moving. Mirrors the python loop's own rule.
            residual = findings
            break
        code = new_code

    result.oracle_code = code
    result.findings = residual
    result.counts = counts
    result.regen_rounds = rounds
    result.collectability = "skipped"
    if [f for f in residual if f.hard]:
        result.verdict = "refuse"
        result.regen_exhausted = True
    else:
        result.verdict = "seed"
    return result


def validate_authored_oracle(
    code: str,
    ecosystem: str,
    spec,
    tasks: list[dict],
    *,
    generate_fn: Callable[[str], str],
    structured_generate_fn: "Callable[[str, str], str] | None" = None,
    reauthor: bool = True,
    criterion_subjects: "dict[str, set[str]] | None" = None,
    operator_answers: "Sequence[str] | None" = (),
) -> OracleQAResult:
    """PLAN-time validation (14B resident) — the static AST stages + the criterion→test
    traceability matrix, with a bounded single-focus REGENERATION loop.

    ``operator_answers`` are the operator's clarified ANSWERS (#819) behind the planning
    seed the oracle was authored from — answer strings, never the rendered requirements
    block, whose house prose would ground the judge on words the operator never used. They
    let the invented-return scanner see what the author saw: ``spec.goal`` is the clean goal
    by design, so an oracle authored from an enriched seed would otherwise be judged against
    a narrower corpus than it was written from and convicted for asserting what the operator
    asked for (#1043). Empty == the operator supplied nothing extra.

    Deep QA is python-only; a node oracle returns validated-but-unscanned with a
    ``language: node`` stamp (the taxonomy defects are all python; there is no ast for
    JS). ``reauthor=False`` (the caller-authorised override branch) validates + counts +
    stamps but never rewrites the caller's deliberate oracle — the seed-time F2P gate
    still applies.

    Returns an :class:`OracleQAResult` carrying the final code + verdict + the evidence.
    A HARD residual after the bounded rounds → ``verdict="refuse"`` (honest not-run); a
    SOFT-only residual (a coverage gap) → ``verdict="seed-partial"`` with the gap
    disclosed; clean → ``verdict="seed"``."""
    result = OracleQAResult(oracle_code=code, language=ecosystem or "python")
    if not code:
        result.verdict = "refuse"
        result.validated = False
        return result
    if (ecosystem or "python") != "python":
        # #1410: "we cannot AST-scan JS" was true when this branch was written and is not
        # true now — `node_static_vacuity` convicts a `.mjs` exam per test, and has since it
        # was built for the seed gate. But the seed gate runs AFTER this function, so its
        # findings arrived where nothing could act on them: a thin node exam was refused,
        # never repaired, nine runs in a row, and the multi-page website card has therefore
        # never been gradeable. Measured on 2026-08-14 — `adequacy_floor: 2` beside
        # `regeneration.rounds: 0`.
        #
        # Node now gets the same bounded repair the python path has had all along. The seed
        # gate still runs its own checks afterwards; this adds a chance to fix, it removes
        # no defence.
        if str(ecosystem).strip().lower() == "node":
            return _validate_node_oracle(
                code, result, generate_fn=generate_fn, reauthor=reauthor,
            )
        # other ecosystems: unchanged — honest stamp, seed as today.
        result.collectability = "skipped"
        return result

    test_criteria = [c for c in getattr(spec, "criteria", ()) if c.tier in _test_tiers()]
    exports, modules = _declared_symbols(tasks)
    spec_corpus = _spec_corpus(spec, operator_answers)
    # #826 — thread the callable-level subjects into the #821 traceability seam. When the
    # caller did not supply an explicit map, bind every test-tier criterion to the plan's
    # DECLARED export callables, so a criterion counts as covered only when a declared test
    # actually exercises a PROMISED contract callable (not merely any incidental first-party
    # symbol). Degrades safely: an empty declared-export set → empty subjects → verify_
    # traceability falls back to today's any-first-party rule (byte-identical behaviour).
    if criterion_subjects is None and exports:
        criterion_subjects = {c.id: set(exports) for c in test_criteria}

    counts: dict[str, int] = {c: 0 for c in ALL_CLASSES}
    rounds = 0
    residual: list[OracleFinding] = []
    covered: list[str] = []
    uncovered: list[str] = []
    coverage_denominator = 0
    coverage_skipped: str = ""

    while True:
        findings = _static_findings(
            code, exports, modules, spec_corpus, ecosystem=ecosystem
        )
        # Traceability (needs a model call for the map) — only when the static pass is
        # HARD-clean (a coverage gap is moot on an uncollectable/ill-posed oracle; fixing
        # the HARD defect first also avoids a wasted map call each round).
        cov_map: "dict[str, list[str]] | None" = None
        # #1374: gate on what a finding MEANS, not on its severity. A thin oracle
        # (adequacy_floor / f2p_vacuous) parses fine and is the case where the coverage
        # map matters most; only an oracle that cannot be collected, parsed or driven
        # makes the map impossible. See _COVERAGE_BLOCKING_CLASSES.
        _blocking = [f for f in findings if f.cls in _COVERAGE_BLOCKING_CLASSES]
        if test_criteria and not _blocking:
            cov_map = request_coverage_map(
                code, test_criteria, generate_fn=generate_fn,
                structured_generate_fn=structured_generate_fn,
            )
            if cov_map is not None:
                coverage_denominator = len(test_criteria)
                covered, uncovered, trace_findings = verify_traceability(
                    code, cov_map, test_criteria, criterion_subjects=criterion_subjects,
                )
                findings += trace_findings
            else:
                coverage_denominator = 0  # unknown — the model returned no usable map
                coverage_skipped = "the model returned no usable requirement-to-assertion map"
        elif not test_criteria:
            coverage_skipped = "no test-tier criteria were supplied, so there was nothing to map"
        else:
            coverage_skipped = (
                "the oracle cannot be traced: "
                + ", ".join(sorted({f.cls for f in _blocking}))
            )
        # Count every finding this round (the measurement of oracle quality over time).
        for f in findings:
            counts[f.cls] = counts.get(f.cls, 0) + 1

        if not findings:
            residual = []
            break
        if not reauthor or rounds >= MAX_REGEN_ROUNDS:
            residual = findings
            break

        # Regenerate ONE defect (highest priority): keep-and-append for a coverage gap,
        # whole-file single-focus re-emit for everything else.
        target = min(findings, key=_priority)
        rounds += 1
        if target.cls == CLASS_TRACEABILITY:
            crit = next((c for c in test_criteria if c.id == target.subject), None)
            new_code = _append_one_test(code, crit, generate_fn) if crit else None
        else:
            new_code = _reauthor(code, single_focus_feedback(target), generate_fn)
        if new_code is None or new_code == code:
            # The round produced nothing usable — stop (don't burn the second round on a
            # model that isn't moving); the residual stands.
            residual = findings
            break
        code = new_code

    result.oracle_code = code
    result.findings = residual
    result.counts = counts
    result.covered = covered
    result.uncovered = uncovered
    result.coverage_denominator = coverage_denominator
    result.regen_rounds = rounds
    hard_residual = [f for f in residual if f.hard]
    soft_residual = [f for f in residual if not f.hard]
    if hard_residual:
        # A hopeless oracle: don't seed (a bad oracle is worse than none). The exhaustion
        # is its OWN counted class (H5) so a chronically-defective oracle is visible.
        result.verdict = "refuse"
        result.regen_exhausted = True
        counts[CLASS_REGENERATE_EXHAUSTED] = counts.get(CLASS_REGENERATE_EXHAUSTED, 0) + 1
    elif soft_residual:
        result.verdict = "seed-partial"
    else:
        result.verdict = "seed"
    return result


# ---------------------------------------------------------------------------
# Node ecosystem — static vacuity + the FAIL-TO-PASS baseline for a `.mjs` oracle
# ---------------------------------------------------------------------------
#
# Why this exists (#1342): every non-python oracle used to skip the execution stages
# outright and seed unconditionally, so the ONE exam with authority over a whole job was
# the one exam never proven able to fail. Measured on B9's `20260807-195617-bd`: a
# 33-line, five-test node oracle with two EMPTY bodies passed, the `already_satisfied`
# optimisation (#1049) read that pass as proof of completeness, and a required page was
# deleted from the plan. The stages below are the dual of the python path — same stamps,
# same fail-soft-on-machinery / fail-closed-on-confirmed-defect asymmetry.
#
# The static and execution stages are deliberately INDEPENDENT, because neither subsumes
# the other and the escaped artifact proves it: F2P convicts a vacuous test only where the
# skeleton lets the oracle's imports RESOLVE, and on a greenfield tree the whole file dies
# at import, which node reports as ONE failing aggregate — a clean `all-fail`. Measured,
# that is exactly what the escaped oracle produces. The static pass is what convicts there.

#: Node's own runner, in the shape the driver grades with (`npm test` → `node --test`).
#: TAP is requested EXPLICITLY: the default reporter's glyphs are TTY/locale-dependent,
#: while TAP's ``ok <n> - <name>`` is a stable per-test contract this module can parse.
_NODE_TAP_ARGS: tuple[str, ...] = ("--test", "--test-reporter=tap")

#: Node test-declaration heads. ``.skip``/``.todo`` are DELIBERATELY absent: a skipped or
#: todo test is an explicit, honest non-assertion, and a ``todo`` body is empty BY
#: CONTRACT — flagging either would convict a correctly-marked placeholder.
#:
#: The leading ``(?<![.\w$])`` is load-bearing and was added 2026-08-16 (#1416). ``\b`` alone
#: matches ``test`` in ``SLUG_RE.test(`` — the boundary sits between the dot and the ``t`` —
#: so any regex ``.test(`` call read as a test DECLARATION and whatever followed became a
#: test BODY. Found by an independent reviewer against a plain helper module holding no test
#: at all: it was convicted as vacuous and rendered to the operator as ``helpers.js::-``,
#: the ``-`` recovered from a ``join('-')`` argument. A member call is never a declaration
#: here; ``it.only(`` and ``test.concurrent(`` still match because their dot comes AFTER.
_NODE_TEST_HEAD_RE = re.compile(r"(?<![.\w$])(?:it|test)\s*(?:\.\s*(?:only|concurrent)\s*)*\(")

#: What counts as an assertion. Deliberately GENEROUS (node:assert, chai, jest-style
#: matchers, bare ``ok(``/``fail(``): a missed vacuous test costs one weak exam, while a
#: false positive REFUSES a whole job and blocks real work. The asymmetry is the design.
_NODE_ASSERTION_RE = re.compile(
    r"\bassert\b|\bexpect\s*\(|\bshould\b|\bthrows?\b|\brejects?\b"
    r"|\bdoesNotThrow\b|\bdoesNotReject\b|\bfail\s*\(|\bok\s*\("
    r"|\.\s*to[A-Z]\w*\s*\(|\bmust\s*\("
)

#: ESM import statements, read from the RAW source (the masker blanks literal bodies, and
#: the specifier is the thing being read).
_NODE_IMPORT_RE = re.compile(
    r"\bimport\s+(?P<clause>[^;]*?)\s+from\s*(?P<q>['\"])(?P<spec>[^'\"]+)(?P=q)"
)

#: TAP's per-test result line.
_NODE_TAP_OK_RE = re.compile(r"^\s*ok\s+\d+\s*-\s*(?P<name>.*?)\s*$")

#: TAP end-of-run signals — the node dual of :func:`_run_completed`. Their ABSENCE is how a
#: machinery miss (no node, a timeout, a runner that died before TAP said anything) stays
#: an honest ``not-run`` instead of borrowing the clean ``all-fail`` word.
_NODE_TAP_DONE_RE = re.compile(r"^\s*(?:1\.\.\d+|#\s+(?:tests|pass|fail)\s+\d+)\s*$", re.M)

#: Characters after which a ``/`` begins a REGEX rather than a division, plus the keywords
#: with the same property. Used only by the masker's fail-soft scan.
_JS_REGEX_PRECEDERS = frozenset("(,=:[!&|?{};+-*%^~<>")
_JS_REGEX_KEYWORDS = frozenset({
    "return", "typeof", "case", "in", "of", "new", "delete", "void", "instanceof",
    "do", "else", "yield", "await",
})


def _node_mask(code: str) -> "str | None":
    """Blank every COMMENT and string/template LITERAL body in ``code``, preserving length
    and newlines, so brace-matching and token scans read code and only code.

    Returns ``None`` on any ambiguity — an unterminated string/comment/regex, or a frame
    stack that does not unwind. That is the fail-soft contract the whole node static pass
    rests on: this module would rather see nothing than mis-tokenise a legitimate oracle
    into a REFUSE, so an unparseable file yields no findings at all (``node --check`` owns
    the "is it even valid" question, and unlike this scan it is sound)."""
    out = list(code)
    n = len(code)
    i = 0
    # Each frame is [mode, brace_depth]; a `${` inside a template pushes a code frame.
    frames: list[list] = [["code", 0]]

    def blank(a: int, b: int) -> None:
        for k in range(a, min(b, n)):
            if out[k] != "\n":
                out[k] = " "

    while i < n:
        mode = frames[-1][0]
        c = code[i]
        if mode == "template":
            if c == "\\":
                blank(i, i + 2)
                i += 2
                continue
            if c == "`":
                frames.pop()
                i += 1
                continue
            if c == "$" and i + 1 < n and code[i + 1] == "{":
                frames.append(["code", 0])
                i += 2
                continue
            blank(i, i + 1)
            i += 1
            continue
        # --- code mode ---
        if c == "/" and i + 1 < n and code[i + 1] == "/":
            j = code.find("\n", i)
            j = n if j == -1 else j
            blank(i, j)
            i = j
            continue
        if c == "/" and i + 1 < n and code[i + 1] == "*":
            j = code.find("*/", i + 2)
            if j == -1:
                return None
            blank(i, j + 2)
            i = j + 2
            continue
        if c in ("'", '"'):
            j = i + 1
            while j < n:
                if code[j] == "\\":
                    j += 2
                    continue
                if code[j] == c or code[j] == "\n":
                    break
                j += 1
            if j >= n or code[j] != c:
                return None
            blank(i + 1, j)
            i = j + 1
            continue
        if c == "`":
            frames.append(["template", 0])
            i += 1
            continue
        if c == "/":
            k = i - 1
            while k >= 0 and out[k] in " \t\r\n":
                k -= 1
            prev = out[k] if k >= 0 else ""
            word = ""
            if prev.isalnum() or prev == "_":
                w = k
                while w >= 0 and (out[w].isalnum() or out[w] == "_"):
                    w -= 1
                word = "".join(out[w + 1:k + 1])
            if k < 0 or prev in _JS_REGEX_PRECEDERS or word in _JS_REGEX_KEYWORDS:
                j = i + 1
                in_class = False
                while j < n:
                    if code[j] == "\\":
                        j += 2
                        continue
                    if code[j] == "\n":
                        return None
                    if code[j] == "[":
                        in_class = True
                    elif code[j] == "]":
                        in_class = False
                    elif code[j] == "/" and not in_class:
                        break
                    j += 1
                if j >= n or code[j] != "/":
                    return None
                blank(i + 1, j)
                i = j + 1
                continue
        if c == "{":
            frames[-1][1] += 1
        elif c == "}":
            if frames[-1][1] == 0:
                if len(frames) == 1:
                    return None  # unbalanced — refuse to guess
                frames.pop()  # closes a `${ ... }` interpolation
                i += 1
                continue
            frames[-1][1] -= 1
        i += 1
    if len(frames) != 1 or frames[0][1] != 0:
        return None
    return "".join(out)


def _node_import_bindings(code: str) -> "list[tuple[str, set[str]]]":
    """``(specifier, local binding names)`` for every ESM ``import … from '<spec>'``.

    The raw material BOTH first-party rules are built from, and the reason it is its own
    function: this module decides first-party status from the ``./`` prefix (a relative
    specifier is the deliverable by construction), while the harness's traceability
    assessor decides it from the run's own banked resolve-probe. Same parse, two
    predicates — and one parse, so the two can never disagree about what the file imported.

    Read from the raw source deliberately: a commented-out import contributes a name that
    is never called, which can only ADD names and therefore only ever makes a caller MORE
    forgiving — the safe direction."""
    out: "list[tuple[str, set[str]]]" = []
    for m in _NODE_IMPORT_RE.finditer(code):
        names: set[str] = set()
        clause = m.group("clause").strip()
        head, brace, braced = clause.partition("{")
        head = head.strip().rstrip(",").strip()
        if head.startswith("*"):
            names.add(head.split(" as ")[-1].strip())
        elif head:
            names.add(head)
        if brace:
            for item in braced.rstrip("}").split(","):
                item = item.strip()
                if item:
                    names.add(item.split(" as ")[-1].strip())
        out.append((m.group("spec"),
                    {n for n in names if re.fullmatch(r"[A-Za-z_$][\w$]*", n or "")}))
    return out


def _node_first_party_names(code: str) -> set[str]:
    """Local binding names imported from a RELATIVE specifier — the node analogue of
    :func:`_first_party_imports`. A relative specifier (``./`` / ``../``) is first-party by
    construction; a bare specifier is a dependency and ``node:*`` is the platform."""
    names: set[str] = set()
    for spec, bound in _node_import_bindings(code):
        if spec.startswith("."):
            names |= bound
    return names


def _node_test_bodies(masked: str) -> list[tuple[int, str]]:
    """``(declaration_offset, body_slice)`` for every ``test(...)``/``it(...)`` in the
    masked source. Handles a braced callback body and a concise arrow body
    (``test('x', () => assert.ok(v))``). A declaration whose body cannot be delimited is
    SKIPPED rather than guessed at — the same fail-soft rule as :func:`_node_mask`."""
    out: list[tuple[int, str]] = []
    n = len(masked)
    for m in _NODE_TEST_HEAD_RE.finditer(masked):
        open_paren = m.end() - 1
        depth = 0
        close_paren = -1
        for k in range(open_paren, n):
            if masked[k] == "(":
                depth += 1
            elif masked[k] == ")":
                depth -= 1
                if depth == 0:
                    close_paren = k
                    break
        if close_paren == -1:
            continue
        args = masked[open_paren + 1:close_paren]
        arrow = args.find("=>")
        if arrow != -1:
            rest = args[arrow + 2:]
            if rest.lstrip().startswith("{"):
                body = _node_braced_body(rest)
                if body is None:
                    continue
                out.append((m.start(), body))
            else:
                out.append((m.start(), rest))
            continue
        fn = re.search(r"\bfunction\b[^{]*\{", args)
        if not fn:
            continue
        body = _node_braced_body(args[fn.end() - 1:])
        if body is None:
            continue
        out.append((m.start(), body))
    return out


def _node_braced_body(text: str) -> "str | None":
    """The contents of the first ``{...}`` block in ``text`` by brace matching, or ``None``
    when it does not close (fail-soft: the declaration is then skipped, never guessed)."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for k in range(start, len(text)):
        if text[k] == "{":
            depth += 1
        elif text[k] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:k]
    return None


def _node_declared_name(code: str, offset: int) -> str:
    """The test's declared name, recovered from the RAW source at the masked declaration's
    offset (the masker blanked the literal holding it). ``""`` when unrecoverable — the
    finding still stands, it just names the test positionally."""
    m = re.compile(r"\(\s*(['\"`])(?P<name>[^'\"`]*)\1").search(code, offset)
    if not m or m.start() > offset + 200:
        return ""
    return m.group("name")


# --- The node tokeniser, exported (#1348) ----------------------------------------------
#
# ``tools/dispatch_harness/green_quality/traceability.py`` reads the SAME ``.mjs`` oracles
# this module validates, and needs the same four answers: where are the literals, what did
# the file import, where are the test bodies, what is each test called. These aliases exist
# so it reuses THIS tokeniser rather than the repository growing a second one — and a second
# JavaScript tokeniser is not a duplicate, it is a divergence waiting to happen, where two
# instruments disagree about what a test body contains and neither is wrong on its own terms.
#
# Underscore-private is still the right default for the rest of this file; these five names
# are the deliberate, documented seam. Behaviour is unchanged by exporting them.
node_mask = _node_mask
node_import_bindings = _node_import_bindings
node_first_party_names = _node_first_party_names
node_test_bodies = _node_test_bodies
node_declared_name = _node_declared_name
#: Deliberately GENEROUS — see :data:`_NODE_ASSERTION_RE`. A consumer whose failure
#: asymmetry is INVERTED (where a generous match MINTS a claim rather than withholding one)
#: must not use this as its predicate; traceability uses it only for the "does this test
#: assert anything at all" flag, never to award coverage.
NODE_ASSERTION_RE = _NODE_ASSERTION_RE


def node_static_vacuity(code: str) -> list[OracleFinding]:
    """Per-test STATIC vacuity — the shapes that need no execution to convict, and the only
    stage that can convict the escaped B9 oracle at all (its imports do not resolve on a
    greenfield skeleton, so F2P legitimately reports ``all-fail`` there).

    Two HARD shapes, both the existing adequacy floor (:data:`CLASS_ADEQUACY_FLOOR`)
    applied per TEST rather than per file:

      * an EMPTY body (statements absent; comments already blanked) — it cannot fail on any
        tree, for any implementation, ever;
      * a body with NO assertion AND NO call of a first-party symbol — nothing in it can
        throw on a missing implementation, so it cannot discriminate either.

    Deliberately NOT flagged: an assertion-free body that DOES call a first-party symbol
    (the bare no-raise smoke test). That is this module's own established floor rule — see
    :func:`_exercises_first_party`, whose docstring exists precisely so a legitimate smoke
    oracle "passes the floor and is not false-flagged". Such a test still fails on a
    skeleton (the call throws), so it genuinely discriminates; where the skeleton lets its
    imports resolve, :func:`node_fail_to_pass_baseline` convicts it BY MEASUREMENT.
    Hard-refusing it statically would contradict a rule written to prevent a false flag.

    Fail-soft by construction: an unmaskable source yields ``[]``."""
    masked = _node_mask(code)
    if masked is None:
        return []
    first_party = _node_first_party_names(code)
    findings: list[OracleFinding] = []
    for idx, (offset, body) in enumerate(_node_test_bodies(masked), start=1):
        subject = _node_declared_name(code, offset) or f"test #{idx}"
        if not body.strip():
            findings.append(OracleFinding(
                CLASS_ADEQUACY_FLOOR,
                f"test `{subject}` has an EMPTY body — it asserts nothing and cannot fail "
                "on any tree, so it can only ever mint a false GREEN",
                subject=subject,
            ))
            continue
        if _NODE_ASSERTION_RE.search(body):
            continue
        if not any(
            re.search(r"\b" + re.escape(name) + r"\s*(?:\(|\.\s*\w+\s*\()", body)
            for name in first_party
        ):
            findings.append(OracleFinding(
                CLASS_ADEQUACY_FLOOR,
                f"test `{subject}` makes no assertion and calls no first-party symbol — "
                "nothing in it can fail on a missing implementation",
                subject=subject,
            ))
    return findings


def node_confirm_collectable(
    code: str, *, run: "Callable[..., tuple[bool, str, str]]" = _default_run
) -> tuple[str, Optional[OracleFinding]]:
    """The node dual of :func:`confirm_collectable`: ``node --check`` PARSES the oracle
    without executing it. Returns ``(stamp, finding)``, stamp ∈ {``confirmed``,
    ``unconfirmed``, ``not-run``}.

    A parse failure here is SOUND — unlike the python collect probe nothing is stubbed and
    nothing is imported, ``--check`` only parses — so it yields a HARD collectability
    finding. A missing runner is ``not-run`` with no finding: the node oracle previously
    stamped a flat ``skipped`` on this axis regardless, which read as a measurement to
    every consumer of ``oracle-qa.json`` while measuring nothing."""
    import shutil

    node = shutil.which("node")
    if not node:
        return ("not-run", None)
    with tempfile.TemporaryDirectory(prefix="oracle_qa_node_check_") as td:
        workdir = Path(td)
        probe = workdir / "acceptance.job.test.mjs"
        probe.write_text(code, encoding="utf-8")
        ok, out, err = run(
            [node, "--check", probe.name], str(workdir),
            ORACLE_QA_COLLECT_TIMEOUT_S, _qa_env(workdir),
        )
        if ok:
            return ("confirmed", None)
        blob = (out + "\n" + err).strip()
        if not blob:
            return ("not-run", None)
        return ("unconfirmed", OracleFinding(
            CLASS_COLLECTABILITY,
            f"node could not parse the oracle: {_tail(blob)}",
        ))


def node_fail_to_pass_baseline(
    code: str,
    skeleton_dir: str,
    *,
    run: "Callable[..., tuple[bool, str, str]]" = _default_run,
    diagnostics: "dict | None" = None,
) -> tuple[str, list[OracleFinding]]:
    """The node dual of :func:`fail_to_pass_baseline`: run the oracle ONCE against the REAL
    pre-implementation skeleton with ``node --test`` and require every test to fail. A test
    that PASSES with no implementation present is vacuous and yields a HARD finding.

    Stamps: ``all-fail`` (clean), ``vacuous:<names>``, ``not-run``. The asymmetry is the
    python path's, unchanged and deliberate — any MACHINERY failure (node absent, timeout,
    a runner that died before TAP said anything) is a fail-soft ``not-run`` with NO finding,
    while a CONFIRMED pre-implementation pass is fail-closed.

    The probe is written into the pinned oracle's OWN directory
    (:data:`shared.fleet.acceptance.JOB_ORACLE_PATH_NODE`'s parent), not the repo root: ESM
    relative specifiers resolve from the importing file's location, so a root-level probe
    would resolve the oracle's ``../src/...`` imports outside the tree entirely and turn
    every run into a meaningless import error."""
    import shutil

    probe: "Path | None" = None
    created_dir = False
    started = time.monotonic()
    try:
        repo = Path(skeleton_dir)
        if not repo.is_dir():
            return _not_run(diagnostics, "skeleton-absent",
                            f"the pre-implementation skeleton {skeleton_dir!r} is not a directory, "
                            "so there is no tree to run the oracle against")
        node = shutil.which("node")
        if not node:
            return _not_run(diagnostics, "no-runner",
                            "node is not on PATH, so the fail-to-pass baseline cannot be taken")
        from shared.fleet.acceptance import JOB_ORACLE_PATH_NODE

        rel_parent = Path(JOB_ORACLE_PATH_NODE).parent
        probe_dir = repo / rel_parent
        created_dir = not probe_dir.exists()
        probe_dir.mkdir(parents=True, exist_ok=True)
        probe = probe_dir / "_qa_f2p_probe.test.mjs"
        probe.write_text(code, encoding="utf-8")
        rel = (rel_parent / probe.name).as_posix()
        with tempfile.TemporaryDirectory(prefix="oracle_qa_node_home_") as home:
            ok, out, err = run(
                [node, *_NODE_TAP_ARGS, rel], str(repo),
                ORACLE_QA_NODE_F2P_TIMEOUT_S, _qa_env(Path(home)),
            )
        blob = out + "\n" + err
        passed = _node_passed_tests(blob)
        if passed:
            return (f"vacuous:{','.join(passed)}", [
                OracleFinding(
                    CLASS_F2P_VACUOUS,
                    f"test `{name}` PASSES on the pre-implementation skeleton — it is "
                    "vacuous (asserts nothing that needs the implementation)",
                    subject=name,
                )
                for name in passed
            ])
        if _NODE_TAP_DONE_RE.search(blob):
            return ("all-fail", [])
        # THE EXIT THAT HAS FIRED EVERY TIME, and until now it said nothing (#1350).
        # The runner started and TAP never reached its `1..N` / `# fail` terminator, so we
        # cannot tell a passing test from a test that never ran — the whole point of the
        # baseline. Bank the command and both streams: on a node oracle this is almost
        # always an ESM resolution error against the pre-implementation skeleton, and that
        # is unreadable from the stamp alone.
        return _not_run(
            diagnostics, "runner-produced-nothing",
            "node --test ran but TAP never reported a plan or a done marker, so no test "
            "outcome could be read",
            elapsed_s=time.monotonic() - started,
            cmd=[node, *_NODE_TAP_ARGS, rel], stdout=out, stderr=err,
        )
    except Exception as exc:  # noqa: BLE001 — machinery failure is an honest not-run
        # Previously a bare `return ("not-run", [])`: every exception in this function --
        # an unreadable skeleton, a failed mkdir, an import error on JOB_ORACLE_PATH_NODE --
        # collapsed into the same silent word. Fail-soft is correct here (a machinery miss
        # must never block a dispatch); fail-SILENT never was.
        return _not_run(
            diagnostics, "raised",
            f"{type(exc).__name__}: {exc}",
            elapsed_s=time.monotonic() - started,
        )
    finally:
        try:
            if probe is not None and probe.exists():
                probe.unlink()
            if created_dir and probe is not None:
                probe.parent.rmdir()
        except OSError:
            pass


def _node_passed_tests(output: str) -> list[str]:
    """TAP ``ok <n> - <name>`` lines — the names that PASSED. ``# SKIP``/``# TODO``
    directives are dropped (a skipped test is not a pass, and counting one would invent a
    vacuity finding against a test that never ran). De-duped, order-preserving."""
    out: list[str] = []
    seen: set[str] = set()
    for line in output.splitlines():
        m = _NODE_TAP_OK_RE.match(line)
        if not m:
            continue
        name = m.group("name")
        if re.search(r"#\s*(SKIP|TODO)\b", name, re.I):
            continue
        name = name.strip()
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def _node_seed_gate(
    code: str,
    skeleton_dir: str,
    result: OracleQAResult,
    *,
    run: "Callable[..., tuple[bool, str, str]]" = _default_run,
) -> OracleQAResult:
    """Assemble the node verdict: ``node --check`` + static vacuity + the F2P baseline,
    merged into the plan-time evidence exactly as the python path merges its own."""
    result.language = "node"
    stamp, collect_finding = node_confirm_collectable(code, run=run)
    result.collectability = stamp
    # Diagnostics threaded through exactly as the python path does (#1350). Without this the
    # node half — the operator's stated priority, since websites are node jobs — stamped
    # `not-run` from five different causes with no way to tell them apart, and did so on
    # every record since 2026-07-12. The dict lands in `not_measured_detail` in the banked
    # oracle-qa.json, which already serialises it.
    f2p_diag: dict = {}
    f2p_stamp, f2p_findings = node_fail_to_pass_baseline(
        code, skeleton_dir, run=run, diagnostics=f2p_diag)
    result.f2p_baseline = f2p_stamp
    result.f2p_diagnostics = f2p_diag

    new_findings = list(result.findings)
    for f in (collect_finding, *node_static_vacuity(code), *f2p_findings):
        if f is None:
            continue
        new_findings.append(f)
        result.counts[f.cls] = result.counts.get(f.cls, 0) + 1
    result.findings = new_findings

    if any(f.hard for f in new_findings):
        result.verdict = "refuse"
    elif any(not f.hard for f in new_findings) or result.uncovered:
        result.verdict = "seed-partial"
    else:
        result.verdict = "seed"
    return result


def f2p_seed_gate(
    code: str,
    rel_path: str,
    skeleton_dir: str,
    *,
    prior_evidence: "dict | None" = None,
    run: "Callable[..., tuple[bool, str, str]]" = _default_run,
) -> OracleQAResult:
    """SEED-time gate (30B resident, 14B gone — no regeneration): the advisory
    collectability confirmation + the FAIL-TO-PASS baseline against the REAL pre-wave
    skeleton. Merges the plan-time evidence (``prior_evidence`` — the counts/coverage
    from :func:`validate_authored_oracle`) and returns the final verdict.

    ``refuse`` iff a CONFIRMED vacuous test exists (a real defect → don't seed → honest
    not-run). Any machinery failure (no runner, timeout) is fail-soft: the f2p stamp is
    ``not-run`` and the seed proceeds (the gate fails closed only on a CONFIRMED defect,
    never on a machinery miss — pipeline degradation is fail-soft-honest).

    A ``.mjs`` oracle takes the node dual of the same stages (:func:`_node_seed_gate`) —
    ``node --check``, the per-test static vacuity pass, and the ``node --test`` FAIL-TO-PASS
    baseline. It previously returned an unconditional ``seed`` with both execution stamps
    faked flat, which made the operator's stated priority (websites — node jobs) precisely
    the case where the highest-authority exam was never proven able to fail (#1342). Any
    OTHER ecosystem still seeds unstamped: there is no runner here to make a claim with,
    and the stamps say so rather than borrowing a measured word."""
    result = _result_from_prior(code, prior_evidence)
    if rel_path.endswith(".mjs"):
        return _node_seed_gate(code, skeleton_dir, result, run=run)
    if not rel_path.endswith(".py"):
        result.collectability = "skipped"
        result.f2p_baseline = "not-run"
        if result.verdict != "refuse":
            result.verdict = result.verdict or "seed"
        return result

    stamp, collect_finding = confirm_collectable(code, run=run)
    result.collectability = stamp
    f2p_diag: dict = {}
    f2p_stamp, f2p_findings = fail_to_pass_baseline(
        code, skeleton_dir, run=run, diagnostics=f2p_diag)
    result.f2p_baseline = f2p_stamp
    result.f2p_diagnostics = f2p_diag

    new_findings = list(result.findings)
    for f in (collect_finding, *f2p_findings):
        if f is None:
            continue
        new_findings.append(f)
        result.counts[f.cls] = result.counts.get(f.cls, 0) + 1
    result.findings = new_findings

    if any(f.hard for f in new_findings):
        result.verdict = "refuse"
    elif any(not f.hard for f in new_findings) or result.uncovered:
        result.verdict = "seed-partial"
    else:
        result.verdict = "seed"
    return result


def _result_from_prior(code: str, prior: "dict | None") -> OracleQAResult:
    """Reconstruct an :class:`OracleQAResult` from a plan-time evidence dict so the seed
    gate can merge into it. Fail-soft: a missing/garbage prior yields a clean-slate
    result (the seed gate then judges on the F2P run alone)."""
    result = OracleQAResult(oracle_code=code)
    if not isinstance(prior, dict):
        result.counts = {c: 0 for c in ALL_CLASSES}
        return result
    result.counts = {c: int(prior.get("findings", {}).get(c, 0)) for c in ALL_CLASSES}
    result.language = str(prior.get("language", "python"))
    result.covered = list(prior.get("covered", []) or [])
    result.uncovered = list(prior.get("uncovered", []) or [])
    cov = str(prior.get("oracle_coverage", "unknown"))
    if "/" in cov:
        try:
            result.coverage_denominator = int(cov.split("/", 1)[1])
        except (ValueError, IndexError):
            result.coverage_denominator = 0
    regen = prior.get("regeneration", {}) if isinstance(prior.get("regeneration"), dict) else {}
    result.regen_rounds = int(regen.get("rounds", 0) or 0)
    result.regen_exhausted = bool(regen.get("exhausted", False))
    result.verdict = str(prior.get("verdict", "seed"))
    return result


def _test_tiers() -> frozenset[str]:
    from shared.fleet.acceptance import TEST_TIERS

    return TEST_TIERS
