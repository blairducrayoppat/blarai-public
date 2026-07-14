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
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

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

# ---------------------------------------------------------------------------
# Budgets (registered in shared/timeout_registry.py — same change, the gate enforces it)
# ---------------------------------------------------------------------------

#: The advisory collectability subprocess (``py_compile`` is in-process; this bounds
#: the ``pytest --collect-only`` confirmation against the synthesised stub skeleton).
ORACLE_QA_COLLECT_TIMEOUT_S: float = 60.0
#: The FAIL-TO-PASS baseline subprocess (the oracle run once against the pre-wave
#: skeleton). Bounds a slow property test / a cold ``uv`` resolve; the oracle grades in
#: seconds, so this is an abort bound with wide margin — well under grade-time's 600 s.
ORACLE_QA_F2P_TIMEOUT_S: float = 120.0

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
    collectability: str = "unconfirmed"
    language: str = "python"
    validated: bool = True

    @property
    def seedable(self) -> bool:
        return self.verdict in ("seed", "seed-partial")

    def coverage_fraction(self) -> str:
        """``"k/n"`` over the test-tier criteria (behavior+smoke), or ``"unknown"``
        when no traceability map could be verified (no grammar hook / model failure)."""
        if self.coverage_denominator <= 0:
            return "unknown"
        return f"{len(self.covered)}/{self.coverage_denominator}"

    def to_evidence(self) -> dict:
        """The ``oracle_qa`` evidence block (stable shape) stamped into the run
        scorecard for #827 (classifier) + #832 (green-audit). Carries the full
        taxonomy count map, the coverage disclosure, the f2p stamp, and the
        regeneration accounting."""
        counts = {c: int(self.counts.get(c, 0)) for c in ALL_CLASSES}
        return {
            "validated": self.validated,
            "language": self.language,
            "verdict": self.verdict,
            "findings": counts,
            "findings_total": sum(counts.values()),
            "regeneration": {"rounds": self.regen_rounds, "exhausted": self.regen_exhausted},
            "oracle_coverage": self.coverage_fraction(),
            "covered": list(self.covered),
            "uncovered": list(self.uncovered),
            "f2p_baseline": self.f2p_baseline,
            "collectability": self.collectability,
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


def scan_invented_contracts(code: str, declared_exports: set[str]) -> list[OracleFinding]:
    """A first-party imported NAME the plan never promised is an invented contract
    (B4's ``check_answer``). Precise + conservative: only a name imported ``from
    <first-party> import <name>`` and ABSENT from the union of declared task exports is
    flagged — a local helper, a stdlib name, or an exported name is never touched.
    Empty ``declared_exports`` disables the check (no contract to judge against →
    fail-soft, never invent a false invention)."""
    if not declared_exports:
        return []
    out: list[OracleFinding] = []
    seen: set[str] = set()
    for imp in _first_party_imports(code):
        if not imp.is_from:
            continue
        for name in imp.names:
            if name in declared_exports or name in seen:
                continue
            seen.add(name)
            out.append(OracleFinding(
                CLASS_INVENTED_CONTRACT,
                f"imports `{name}` from `{imp.module}` but the plan declares no such "
                "export — an invented contract that convicts valid work",
                subject=name,
            ))
    return out


def _is_first_party(top: str) -> bool:
    """The first-party predicate for the #826 interface-contract derivation — aligned
    with :func:`_first_party_imports` (a top package that is neither stdlib nor a
    test-runner framework), so a derived callable always has a real import behind it."""
    return bool(top) and top not in _stdlib_roots()


def _spec_corpus(spec) -> str:
    """The lowercased text the SPEC actually states — the goal + every criterion's text
    and check — as one searchable blob. The invented-RETURN check tests whether a demanded
    magic string is GROUNDED here; a value the requirements never mention is the B4n2
    invention. Fail-soft: a spec without criteria yields the goal alone (or '')."""
    parts: list[str] = [str(getattr(spec, "goal", "") or "")]
    for c in getattr(spec, "criteria", ()) or ():
        parts.append(str(getattr(c, "text", "") or ""))
        parts.append(str(getattr(c, "check", "") or ""))
    return " ".join(parts).lower()


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
    Windows; the caller owns the isolated cwd + env (LOCALAPPDATA/PYTHONPATH)."""
    try:
        cp = subprocess.run(  # noqa: S603 — argv list, no shell
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout_s,
            env=env, creationflags=_NO_WINDOW,
        )
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
    a carried path still resolves), where ``grade_env.clean_grade_env`` REPLACES."""
    env = dict(os.environ)
    env["LOCALAPPDATA"] = str(isolated_home)
    env["APPDATA"] = str(isolated_home)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
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
    runner is available."""
    import shutil

    base = [
        "-m", "pytest", "-q",
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
    Returns ``(stamp, finding)`` where stamp ∈ {``confirmed``, ``unconfirmed``, ``skipped``}.

    Deliberately CANNOT false-park a valid oracle: a clean collect stamps ``confirmed``;
    a non-zero exit stamps ``unconfirmed`` (the stub synthesis could be imperfect — an
    inert name used as a constant, a missed module) and returns NO finding UNLESS the
    output carries an unambiguous structural-defect signature that the stubs could not
    have caused (a SyntaxError, or a Hypothesis InvalidArgument with no import error).
    The sound HARD collectability finding is :func:`check_syntax`'s in-process compile;
    this only ever ADDS confidence, never subtracts it."""
    with tempfile.TemporaryDirectory(prefix="oracle_qa_collect_") as td:
        workdir = Path(td)
        oracle = workdir / "test_job_acceptance.py"
        oracle.write_text(code, encoding="utf-8")
        _synthesize_skeleton(code, workdir)
        clean = _clean_ini(workdir)
        cmd = _pytest_cmd("test_job_acceptance.py", clean, collect_only=True)
        if cmd is None:
            return ("skipped", None)
        ok, out, err = run(cmd, str(workdir), ORACLE_QA_COLLECT_TIMEOUT_S,
                           _qa_env(workdir, extra_path=str(workdir)))
        if ok:
            return ("confirmed", None)
        blob = (out + "\n" + err)
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


def fail_to_pass_baseline(
    code: str,
    skeleton_dir: str,
    *,
    run: "Callable[..., tuple[bool, str, str]]" = _default_run,
) -> tuple[str, list[OracleFinding]]:
    """The FAIL-TO-PASS baseline (r1extern lever 1 / SWE-bench F→P / AgentLens Lucky
    Pass): run the oracle ONCE against the PRE-IMPLEMENTATION skeleton and require EVERY
    test to fail/error. A test that PASSES there is vacuous / non-discriminating — it can
    only ever mint a false GREEN.

    Returns ``(stamp, findings)`` where stamp ∈ {``all-fail``, ``vacuous:<names>``,
    ``not-run``}. ``all-fail`` (or a collection error — nothing passed) is clean.
    ``vacuous:...`` names the passing tests and yields a HARD finding per test. Any
    machinery failure (no runner, timeout, unreadable output) is an honest ``not-run``
    with NO finding — the discrimination check is best-effort, and a machinery miss must
    never block a dispatch (only a CONFIRMED vacuous pass is a gate defect)."""
    try:
        repo = Path(skeleton_dir)
        if not repo.is_dir():
            return ("not-run", [])
        clean = _clean_ini(repo)
        rel = "_qa_f2p_probe.py"
        probe = repo / rel
        probe.write_text(code, encoding="utf-8")
        try:
            cmd = _pytest_cmd(rel, clean, collect_only=False)
            if cmd is None:
                return ("not-run", [])
            # verbose so PASSED/FAILED lines are per-test parseable
            cmd = cmd + ["-v"]
            with tempfile.TemporaryDirectory(prefix="oracle_qa_home_") as home:
                ok, out, err = run(cmd, str(repo), ORACLE_QA_F2P_TIMEOUT_S,
                                  _qa_env(Path(home), extra_path=str(repo)))
            blob = out + "\n" + err
            passed = _passed_tests(blob)
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
            # absent, a timeout, a crash → honest not-run, never a false 'clean').
            if _run_completed(blob):
                return ("all-fail", [])
            return ("not-run", [])
        finally:
            try:
                probe.unlink()
            except OSError:
                pass
            try:
                clean.unlink()
            except OSError:
                pass
    except Exception:  # noqa: BLE001 — machinery failure is an honest not-run
        return ("not-run", [])


def _passed_tests(output: str) -> list[str]:
    """Parse pytest ``-v`` output for the names of tests that PASSED (the vacuous set).
    Matches ``<file>::<name> PASSED`` and ``<name> PASSED`` shapes; de-duped,
    order-preserving. A collection error / all-fail run yields none."""
    import re

    out: list[str] = []
    seen: set[str] = set()
    for line in output.splitlines():
        m = re.search(r"(?:::)?([A-Za-z_]\w*)\s+PASSED\b", line)
        if not m:
            continue
        name = m.group(1)
        if name.startswith("test") and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def _run_completed(output: str) -> bool:
    """True iff pytest actually RAN the file (vs a machinery miss). Matches a pytest
    summary/collection signal so a timeout / missing-runner / crash (no such signal) is
    an honest ``not-run`` rather than a false ``all-fail``."""
    import re

    if not output:
        return False
    low = output.lower()
    if re.search(r"\d+\s+(passed|failed|error|errors|skipped|deselected|xfailed)", low):
        return True
    return any(
        s in low for s in (
            "no tests ran", "errors during collection", "collected 0 items",
            "error collecting", "=== ", " passed", " failed", " error",
        )
    )


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
    code: str, exports: set[str], modules: set[str], spec_corpus: str = ""
) -> list[OracleFinding]:
    """Run the AST-decidable static stages in priority order. If the syntax check fires,
    return it alone (everything downstream is moot on unparseable code)."""
    syntax = check_syntax(code)
    if syntax is not None:
        return [syntax]
    findings: list[OracleFinding] = []
    findings += scan_strategies(code)
    findings += scan_interactive_io(code)
    floor = adequacy_floor(code)
    if floor is not None:
        findings.append(floor)
    findings += scan_invented_contracts(code, exports)
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
) -> OracleQAResult:
    """PLAN-time validation (14B resident) — the static AST stages + the criterion→test
    traceability matrix, with a bounded single-focus REGENERATION loop.

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
        # node/other: the authoring path already applied its structural check; we cannot
        # AST-scan JS. Honest stamp, seed as today.
        result.collectability = "skipped"
        return result

    test_criteria = [c for c in getattr(spec, "criteria", ()) if c.tier in _test_tiers()]
    exports, modules = _declared_symbols(tasks)
    spec_corpus = _spec_corpus(spec)
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

    while True:
        findings = _static_findings(code, exports, modules, spec_corpus)
        # Traceability (needs a model call for the map) — only when the static pass is
        # HARD-clean (a coverage gap is moot on an uncollectable/ill-posed oracle; fixing
        # the HARD defect first also avoids a wasted map call each round).
        cov_map: "dict[str, list[str]] | None" = None
        if test_criteria and not any(f.hard for f in findings):
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
                coverage_denominator = 0  # unknown — no usable map
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
    never on a machinery miss — pipeline degradation is fail-soft-honest). Non-python
    oracles skip the execution stages (there is no pytest for a ``.mjs`` oracle) and seed."""
    result = _result_from_prior(code, prior_evidence)
    if not rel_path.endswith(".py"):
        result.language = "node" if rel_path.endswith(".mjs") else result.language
        result.collectability = "skipped"
        result.f2p_baseline = "not-run"
        if result.verdict != "refuse":
            result.verdict = result.verdict or "seed"
        return result

    stamp, collect_finding = confirm_collectable(code, run=run)
    result.collectability = stamp
    f2p_stamp, f2p_findings = fail_to_pass_baseline(code, skeleton_dir, run=run)
    result.f2p_baseline = f2p_stamp

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
