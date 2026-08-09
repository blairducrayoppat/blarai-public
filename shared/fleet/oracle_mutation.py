"""Oracle Mutation Audit — does the job oracle actually CATCH wrong code? (#828)

The DISCRIMINATION sibling of #821's well-posedness oracle-QA (``oracle_qa.py``).
Where #821 proves the oracle *won't reject valid work*, this module measures the
dual the honesty layer structurally cannot — that the oracle *rejects invalid
work*. It is the bounded, offline, deterministic-operator slice of mutation
testing (ADR-037 §Decision-5, gate G9; r1extern lever 2 / STING's finding that
77% of SWE-bench Verified oracles had a surviving wrong-but-passing variant), and
it is ADVISORY-ONLY by construction — a low score never un-banks a GREEN; it only
stamps the oracle's coverage as weak and feeds the #827 trend.

The mechanic (GREEN-path only — it audits the GRADER, not the coder)::

    a candidate PASSES the job oracle
      → mutate the passing FEATURE code with a fixed deterministic operator table
      → re-run the SAME oracle against each mutant in the same grade-time harness
      → oracle_mutation_score = killed / ran      (killed = the oracle went RED)

A *surviving* mutant (wrong code the oracle still passes) is an oracle hole. A
known-vacuous oracle scores 0/n (nothing it checks depends on the code); a sharp
oracle kills the classic mutants.

``ran`` is what actually produced a verdict, and that is a SUBSET of what was selected
whenever the budget expires or the machinery cannot reach a mutant. The score therefore
says nothing about completeness on its own. ``planned`` is the selection size and the
three buckets reconcile against it::

    planned = ran + not_run + unreachable

``not_run`` = dropped by the wall-clock budget before being attempted; ``unreachable`` =
source that would not unparse, or a run that returned no readable verdict (a per-mutant
timeout is the usual cause). ``mutation_audit`` stamps the shortfall (``partial-budget`` /
``partial-machinery``), and the coverage BAND is computed over the SELECTED set, so a
mutant that was never put to the question can only ever lower it — by either cause,
because neither is evidence that the oracle caught anything (#1231). Read the score as
"of the mutants that ran", never as "of the oracle".

Attribution — WHICH symbol, killed by WHICH test (#1195 item 3)
---------------------------------------------------------------

The score above is a whole-file figure, and a whole-file figure cannot answer the
question the traceability ladder's top rung asks: *did THIS criterion's test fail
when THIS criterion's subject was broken?* So every counted mutant additionally
records the top-level symbol its site lives in and, when the oracle went RED, the
test names that actually failed — parsed from the run pytest already produced, at
no extra subprocess cost. :data:`EV_MUTANTS` carries those rows;
``tools/dispatch_harness/green_quality/traceability.py`` folds them into
``L4-KILLS``.

Attribution is EVIDENCE, not inference, and it degrades toward silence: a site
outside any top-level ``def``/``class`` records no symbol, and a RED run whose
failing tests could not be parsed (a repo ``pytest.ini`` carrying ``-rN --tb=no``
suppresses both the summary and the headers — measured, not assumed) records no
killers. Either way the mutant still counts toward killed/ran and simply supplies
no rung. A mutant that cannot say who killed it must never be read as proof that
something did.

The fixed operator table (five classic operators, exactly the #828 mandate):

  * ``boundary``            — a relational operator shifts its boundary
                              (``<``↔``<=``, ``>``↔``>=``).
  * ``arithmetic``          — a binary operator swaps (``+``↔``-``, ``*``↔``/``).
  * ``constant``            — a numeric constant is perturbed (``n`` → ``n+1``; a
                              bool flips).
  * ``early_return``        — ``return None`` is injected as a function's first
                              statement (the body is skipped).
  * ``negate_conditional``  — an ``if`` test is wrapped in ``not (...)``.

Small-model note (#740 c.1721): this is pure determinism — no model in the loop,
the "more cheap attempts over cleverness" play. STING's LLM-mutation half is
REJECTED (ADR-037 R1: a model here competes with the 30B for the one GPU and adds
nondeterminism); only the deterministic operators live here.

Honesty invariants honored (ADR-037 §Decision-1):

  * ADVISORY-ONLY (invariant 5) — the audit returns an evidence dict with NO
    verdict field and exposes no symbol that moves a verdict. A 0/n score stamps
    ``oracle_mutation_coverage: weak`` and changes nothing.
  * BOUNDED + BUDGETED — at most :data:`MAX_MUTANTS` mutants under the registered
    :data:`ORACLE_MUTATION_BUDGET_S` wall-clock cap; a budget squeeze stamps
    honestly (``mutation_audit: partial-budget`` / ``skipped-budget``), never a
    faked full score.
  * FAIL-SOFT (invariant 3) — every machinery miss (no runner, unparse failure, a
    non-passing baseline, a per-mutant timeout) is an honest skip/not-counted
    stamp, never an implied pass and never a raised error.

Naming note (collision-avoidance, NAMED per the #828 handoff): the ticket phrases
the weak stamp as ``oracle_coverage: weak``, but #821 already owns the key
``oracle_coverage`` for the criterion k/n fraction in ``oracle-qa.json``. So that
both evidence blocks can compose without one clobbering the other, the mutation
band is stamped under the distinct key ``oracle_mutation_coverage`` (this module's
evidence lands in a separate ``oracle-mutation.json``).

PYTHON-only today; a node oracle (#830 territory — no host ``.js`` mutation runner
exists yet) returns an honest ``mutation_audit: skipped-no-python-runner`` stamp.
Off the dispatch critical path by construction — the audit is GREEN-only and runs
where the inputs exist; see ``tools/dispatch_harness/green_quality/mutation.py``
for which seam calls it. Kill-switchable via ``BLARAI_ORACLE_MUTATION`` (default ON).
"""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from shared.fleet import grade_env, oracle_qa

# ---------------------------------------------------------------------------
# Budgets (registered in shared/timeout_registry.py — same change; the standing
# gate cross-checks the constant against the registry row).
# ---------------------------------------------------------------------------

#: Overall wall-clock cap for ONE GREEN job's mutation audit (all mutants). The
#: audit is offline and GREEN-only (rare — ~1/night), so this bounds the whole
#: pass, not one mutant; the per-mutant subprocess reuses #821's already-registered
#: FAIL-TO-PASS bound (:data:`oracle_qa.ORACLE_QA_F2P_TIMEOUT_S`) — one oracle run
#: against one tree is the identical shape. On expiry the audit stamps honestly
#: (``partial-budget`` / ``skipped-budget``); it never fakes a full score.
ORACLE_MUTATION_BUDGET_S: float = 300.0

#: Hard cap on mutants per job (the #828 N≤20 mandate). Deterministic,
#: operator-diverse selection (see :func:`_select`) trims the enumerated site
#: pool to this many before any subprocess spends.
MAX_MUTANTS: int = 20

#: Cap on feature files mutated (the oracle's directly-imported first-party
#: modules). Bounds the enumeration on a wide repo; the selection cap above bounds
#: the actual spend.
_MAX_TARGET_FILES: int = 10

#: Cap on surviving-mutant loci reported into evidence (a survivor names WHERE the
#: oracle is blind — for #827/#837 — but the list is bounded so evidence stays small).
_MAX_SURVIVORS_REPORTED: int = 12

#: The advisory sidecar this audit writes into a run dir (mirrors #821's ``oracle-qa.json``).
#: Exported so a caller banks and reads the evidence under the ONE name :func:`_persist`
#: writes, rather than re-declaring the literal at the seam.
ORACLE_MUTATION_SIDECAR_NAME: str = "oracle-mutation.json"

#: Evidence key holding the per-mutant attribution rows (see :func:`_mutant_row`). Named so a
#: consumer binds to the constant rather than to the literal.
EV_MUTANTS: str = "mutants"
#: Evidence key holding the SHA-256 of the exact oracle text this audit mutated against. A
#: consumer that grades a different exam than the one that was audited must be able to detect
#: that rather than silently attribute one exam's kills to another's tests.
EV_ORACLE_SHA: str = "oracle_sha256"
#: Evidence key holding the repo-relative path the audited oracle was graded at.
EV_ORACLE_PATH: str = "oracle_path"

#: Cap on failing-test names recorded for ONE mutant. A truncated list can only ever LOSE a
#: killer (and so under-award the rung), never invent one, and :data:`_KILLERS_TRUNCATED_KEY`
#: records that it happened so a consumer is not left guessing.
_MAX_KILLERS_RECORDED: int = 32
_KILLERS_TRUNCATED_KEY: str = "killed_by_truncated"


def oracle_mutation_enabled() -> bool:
    """The kill-switch: ON unless ``BLARAI_ORACLE_MUTATION`` is a falsey token.

    Defaults ON. The audit is an offline GREEN-only pass, so ON costs nothing until
    a caller invokes it; OFF makes the entry point a no-op skip. Read at the entry
    point so a disabled audit never parses a file or spawns a subprocess."""
    return str(os.environ.get("BLARAI_ORACLE_MUTATION", "1")).strip().lower() not in (
        "0", "false", "no", "off", ""
    )


# ---------------------------------------------------------------------------
# The fixed operator table
# ---------------------------------------------------------------------------

OP_BOUNDARY = "boundary"
OP_ARITHMETIC = "arithmetic"
OP_CONSTANT = "constant"
OP_EARLY_RETURN = "early_return"
OP_NEGATE_COND = "negate_conditional"

#: Selection round-robins across the operators in THIS order for diversity — a job
#: never spends its whole budget on one operator class.
OPERATORS: tuple[str, ...] = (
    OP_BOUNDARY, OP_ARITHMETIC, OP_CONSTANT, OP_EARLY_RETURN, OP_NEGATE_COND,
)

#: Relational operator replacement, boundary-shifting only (the #828 ``<``→``<=``
#: family). ``==``/``!=`` are deliberately NOT here — those are equality, not a
#: boundary shift, and conditional negation already covers the branch-flip class.
_BOUNDARY_FLIP: dict[type, type] = {
    ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt,
}

#: Binary arithmetic operator replacement (the #828 ``+``→``-`` family). Kept to
#: the four common operators so a mutant is a plausible off-by-operator slip.
_ARITH_FLIP: dict[type, type] = {
    ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.Div, ast.Div: ast.Mult,
}


@dataclass
class _Site:
    """One mutation opportunity: its operator class, source line, the top-level symbol whose
    body encloses it, and the in-place ``mutate`` closure over the specific node in a
    (deep-copied) tree."""

    operator: str
    lineno: int
    mutate: Callable[[], None]
    #: The enclosing TOP-LEVEL ``def``/``class`` name, or ``""`` for a module-level site.
    symbol: str = ""


def _perturbable_const(value: object) -> bool:
    """A constant this operator perturbs: a bool (flipped) or a non-bool int/float
    (``n`` → ``n+1``). Complex/str/bytes/None are left untouched — string
    perturbation is noisy and docstrings are ``ast.Constant`` strings."""
    if isinstance(value, bool):
        return True
    return isinstance(value, (int, float))


def _nontrivial_body(node: ast.AST) -> bool:
    """True iff injecting an early ``return None`` would change behaviour — i.e. the
    function body (minus a leading docstring) is more than ``pass`` / ``...`` / a
    lone ``return``/``return None``. Skips equivalent-mutant noise (an injected
    return before a body that already returns nothing is a no-op)."""
    body = list(getattr(node, "body", []))
    if body and isinstance(body[0], ast.Expr) and isinstance(
        getattr(body[0], "value", None), ast.Constant
    ) and isinstance(body[0].value.value, str):
        body = body[1:]  # drop the docstring
    if not body:
        return False
    if len(body) == 1:
        stmt = body[0]
        if isinstance(stmt, ast.Pass):
            return False
        if isinstance(stmt, ast.Expr) and isinstance(
            getattr(stmt, "value", None), ast.Constant
        ) and stmt.value.value is Ellipsis:
            return False
        if isinstance(stmt, ast.Return) and (
            stmt.value is None
            or (isinstance(stmt.value, ast.Constant) and stmt.value.value is None)
        ):
            return False
    return True


# --- mutation closures (factories, so late-binding never captures the wrong node) ---


def _flip_compare(node: ast.Compare, index: int, repl: type) -> Callable[[], None]:
    def _m() -> None:
        node.ops[index] = repl()
    return _m


def _flip_binop(node: ast.BinOp, repl: type) -> Callable[[], None]:
    def _m() -> None:
        node.op = repl()
    return _m


def _perturb_const(node: ast.Constant) -> Callable[[], None]:
    def _m() -> None:
        value = node.value
        node.value = (not value) if isinstance(value, bool) else value + 1
    return _m


def _negate_if(node: ast.If) -> Callable[[], None]:
    def _m() -> None:
        node.test = ast.UnaryOp(op=ast.Not(), operand=node.test)
    return _m


def _inject_return(node: ast.AST) -> Callable[[], None]:
    def _m() -> None:
        node.body.insert(0, ast.Return(value=ast.Constant(value=None)))  # type: ignore[attr-defined]
    return _m


def _toplevel_spans(tree: ast.AST) -> list[tuple[int, int, str]]:
    """``(first line, last line, name)`` of every TOP-LEVEL ``def``/``class`` in a module.

    TOP-LEVEL is the right grain because it is the grain a consumer can match: an oracle
    binds names through ``from app.x import NAME``, so the exported symbol — not a nested
    helper — is what a criterion's subject can ever be. A site inside a nested function or a
    method therefore attributes to the exported name that contains it, which is the name whose
    behaviour the mutation actually changed."""
    spans: list[tuple[int, int, str]] = []
    for node in getattr(tree, "body", None) or []:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        start = int(getattr(node, "lineno", 0) or 0)
        if start:
            spans.append((start, int(getattr(node, "end_lineno", 0) or start), node.name))
    return spans


def _symbol_at(spans: list[tuple[int, int, str]], line: int) -> str:
    """The top-level symbol whose body encloses *line*, or ``""``.

    ``""`` is a real answer meaning "module scope, or not inside any exported definition" —
    a decorator expression sits ABOVE its function's ``lineno`` and lands here too. It is
    never a synonym for "unknown symbol, assume the obvious one": an unattributed site simply
    supplies no evidence, which under-awards rather than misattributes."""
    if line <= 0:
        return ""
    for start, end, name in spans:
        if start <= line <= end:
            return name
    return ""


def _iter_sites(tree: ast.AST) -> list[_Site]:
    """Every mutation opportunity in ``tree``, in a DETERMINISTIC order (``ast.walk``
    BFS — stable across the deep copy used for application, so the k-th site here
    and the k-th site in a copy are the SAME logical mutation). Each ``_Site``
    closes over ``tree``'s own nodes."""
    sites: list[_Site] = []
    spans = _toplevel_spans(tree)
    for node in ast.walk(tree):
        line = int(getattr(node, "lineno", 0) or 0)
        sym = _symbol_at(spans, line)
        if isinstance(node, ast.Compare):
            for i, op in enumerate(node.ops):
                repl = _BOUNDARY_FLIP.get(type(op))
                if repl is not None:
                    sites.append(_Site(OP_BOUNDARY, line, _flip_compare(node, i, repl), sym))
        elif isinstance(node, ast.BinOp):
            repl = _ARITH_FLIP.get(type(node.op))
            if repl is not None:
                sites.append(_Site(OP_ARITHMETIC, line, _flip_binop(node, repl), sym))
        elif isinstance(node, ast.Constant):
            if _perturbable_const(node.value):
                sites.append(_Site(OP_CONSTANT, line, _perturb_const(node), sym))
        elif isinstance(node, ast.If):
            sites.append(_Site(OP_NEGATE_COND, line, _negate_if(node), sym))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _nontrivial_body(node):
                sites.append(_Site(OP_EARLY_RETURN, line, _inject_return(node), sym))
    return sites


def _mutant_source(tree: ast.AST, index: int) -> Optional[str]:
    """Apply the ``index``-th mutation to a DEEP COPY of ``tree`` and unparse it.
    ``None`` on any failure (out-of-range index, unparse error) — a broken mutant is
    silently skipped, never counted."""
    copied = copy.deepcopy(tree)
    sites = _iter_sites(copied)
    if index < 0 or index >= len(sites):
        return None
    try:
        sites[index].mutate()
        ast.fix_missing_locations(copied)
        return ast.unparse(copied)
    except Exception:  # noqa: BLE001 — a mutant that won't unparse is a skip, not a crash
        return None


# --- public generator surface (pure, offline — for tests and future callers) ----


def mutation_sites(source: str) -> list[tuple[str, int]]:
    """The ``(operator, lineno)`` of every mutation opportunity in ``source`` (pure,
    deterministic, no subprocess). ``[]`` on unparseable source."""
    return [(op, line) for op, line, _sym in mutation_sites_attributed(source)]


def mutation_sites_attributed(source: str) -> list[tuple[str, int, str]]:
    """:func:`mutation_sites` plus the top-level symbol each site lives in (``""`` at module
    scope) — the attribution half, exposed for tests and consumers without disturbing the
    two-tuple contract above."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []
    return [(s.operator, s.lineno, s.symbol) for s in _iter_sites(tree)]


def build_mutant(source: str, index: int) -> Optional[str]:
    """The ``index``-th operator-mutant of ``source`` as Python text, or ``None``
    (unparseable source / out-of-range / un-unparseable mutant)."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    return _mutant_source(tree, index)


# ---------------------------------------------------------------------------
# Target resolution — the oracle's directly-imported first-party feature files
# ---------------------------------------------------------------------------


@dataclass
class _Target:
    path: Path
    relpath: str
    tree: ast.AST
    #: ``(operator, lineno, enclosing top-level symbol)`` per site, in enumeration order.
    sites: list[tuple[str, int, str]]


def _module_file_candidates(imp) -> list[str]:
    """Relative posix candidates a first-party import could resolve to: the module
    as a file and as a package ``__init__``, plus (for ``from m import name``) each
    ``name`` as a submodule (``name`` may be a module, not just a symbol)."""
    parts = imp.module.split(".")
    base = "/".join(p for p in parts if p)
    cands = [f"{base}.py", f"{base}/__init__.py"]
    if imp.is_from:
        for name in imp.names:
            cands.append(f"{base}/{name}.py")
            cands.append(f"{base}/{name}/__init__.py")
    return cands


def _resolve_targets(repo: str, oracle_code: str, rel_path: str) -> list[_Target]:
    """The feature files this oracle DIRECTLY imports that exist, are inside the
    repo, are not the oracle/tests, and carry ≥1 mutation site. Bounded by
    :data:`_MAX_TARGET_FILES`. Mutating exactly the oracle's own import surface
    keeps the audit about THIS oracle's discrimination and bounded (transitive
    closure would explode; it is out of scope by design)."""
    from shared.fleet.acceptance import JOB_ORACLE_ALLOWED_PATHS

    repo_path = Path(repo).resolve()
    disallowed = set(JOB_ORACLE_ALLOWED_PATHS) | {rel_path}
    out: list[_Target] = []
    seen: set[str] = set()
    for imp in oracle_qa._first_party_imports(oracle_code):
        for cand in _module_file_candidates(imp):
            path = repo_path / cand
            if not path.is_file():
                continue
            try:
                rel = path.resolve().relative_to(repo_path)
            except (ValueError, OSError):
                continue  # containment: never mutate outside the repo
            relstr = rel.as_posix()
            if relstr in disallowed or relstr.startswith("tests/") or relstr in seen:
                continue
            seen.add(relstr)
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError, ValueError):
                continue
            sites = _iter_sites(tree)
            if not sites:
                continue
            out.append(_Target(
                path=path, relpath=relstr, tree=tree,
                sites=[(s.operator, s.lineno, s.symbol) for s in sites],
            ))
            if len(out) >= _MAX_TARGET_FILES:
                return out
    return out


def _seed_digest(targets: list[_Target]) -> str:
    """A stable reproducibility fingerprint of the audited surface (sorted
    relpath+source). The selection is deterministic without an RNG (round-robin —
    :func:`_select`); this digest makes a given tree's mutant set auditable and
    reproducible across runs."""
    h = hashlib.sha256()
    for t in sorted(targets, key=lambda x: x.relpath):
        h.update(t.relpath.encode("utf-8"))
        try:
            h.update(t.path.read_bytes())
        except OSError:
            pass
    return h.hexdigest()[:16]


def _select(pool: list[dict], cap: int) -> list[dict]:
    """Deterministic, operator-diverse selection of ≤``cap`` mutants: round-robin
    across the fixed operator buckets (each internally in enumeration order), take
    the first ``cap``. No RNG — the order is a pure function of the source, and the
    :func:`_seed_digest` stamps the fingerprint that makes it reproducible."""
    buckets: dict[str, list[dict]] = {op: [] for op in OPERATORS}
    for item in pool:
        buckets.setdefault(item["operator"], []).append(item)
    ordered: list[dict] = []
    depth = 0
    while True:
        progressed = False
        for op in buckets:
            if depth < len(buckets[op]):
                ordered.append(buckets[op][depth])
                progressed = True
        if not progressed:
            break
        depth += 1
    return ordered[:cap]


# ---------------------------------------------------------------------------
# Oracle execution (grade-time parity + the standing LOCALAPPDATA-redirect discipline)
# ---------------------------------------------------------------------------


def _grade_cmd(rel_path: str) -> "list[str] | None":
    """The grade-parity pytest invocation — byte-for-byte the runner shape
    ``real_run_job_oracle`` grades with (``uv run --no-project --with pytest==…
    --with hypothesis==… python -m pytest -q <path>``), pinned via #821's
    ``_QA_*_PIN`` so a "killed here" verdict genuinely predicts "red at grade".
    ``None`` when ``uv`` is absent — the live audit REQUIRES grade parity (mirrors
    ``real_run_job_oracle`` returning not-run without ``uv``), so it honestly skips
    rather than grade with an unpinned runner."""
    uv = shutil.which("uv")
    if not uv:
        return None
    return [
        uv, "run", "--no-project",
        "--with", oracle_qa._QA_PYTEST_PIN, "--with", oracle_qa._QA_HYPOTHESIS_PIN,
        "python", "-m", "pytest", "-q", rel_path,
    ]


def _preserve_uv_dirs(env: dict) -> None:
    """Pin uv's interpreter + cache directories to their REAL locations before the app-data
    redirect below hides them, so a "killed here" verdict still predicts "red at grade" —
    grade parity only holds while both run the same interpreter.

    The rule itself is :func:`grade_env.uv_dir_overlay`, shared with the seed-time oracle QA
    that hit this identically (#1200): two modules redirecting the same roots for the same
    isolation must not each carry their own copy of the remedy, or the next one silently
    won't."""
    env.update(grade_env.uv_dir_overlay(env))


def _mutation_env(isolated_home: Path, repo: str) -> dict:
    """A subprocess env with LOCALAPPDATA/APPDATA redirected into an isolated dir
    (the standing 'LOCALAPPDATA-redirected pytest ALWAYS' discipline — the audit
    never touches the operator's app data), bytecode off, and the repo on
    PYTHONPATH so the oracle's first-party imports resolve exactly as ``-m pytest``
    from ``cwd=repo`` would (safe-path is left DEFAULT for grade parity).

    uv's own directories are pinned to their real locations FIRST — see
    :func:`_preserve_uv_dirs` for why the redirect would otherwise silently change which
    interpreter grades the oracle."""
    env = dict(os.environ)
    _preserve_uv_dirs(env)
    env["LOCALAPPDATA"] = str(isolated_home)
    env["APPDATA"] = str(isolated_home)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    prior = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(repo) + (os.pathsep + prior if prior else "")
    return env


_PASSED_RE = re.compile(r"(\d+)\s+passed\b")


def _passed_count(blob: str) -> int:
    """The ``N passed`` count from a pytest summary (0 if none). Used ONLY for the
    baseline: a GREEN tree's oracle must actually PASS ≥1 test — an exit-0 run with
    0 passed (all-skipped seeded guard, collected-0, empty oracle) is not a green
    baseline and the audit honestly declines."""
    m = _PASSED_RE.search(blob or "")
    return int(m.group(1)) if m else 0


def _run_oracle(
    repo: str, cmd: list[str], run: Callable[..., tuple[bool, str, str]], timeout_s: float,
) -> tuple[bool, str]:
    """Run the oracle once (cwd=repo, hardened env). Returns ``(ok, blob)`` —
    ``ok = exit 0``; ``blob`` = combined stdout+stderr for the completion/kill
    interpretation the callers apply."""
    with tempfile.TemporaryDirectory(prefix="oracle_mut_home_") as home:
        env = _mutation_env(Path(home), repo)
        ok, out, err = run(cmd, repo, timeout_s, env)
    return ok, (out or "") + "\n" + (err or "")


#: pytest's short test summary line: ``FAILED tests/t.py::test_x - AssertionError: …`` (and
#: the ``ERROR`` form for a setup/fixture failure). Present by DEFAULT under ``-q`` — pytest's
#: default ``reportchars`` is ``fE`` — which is what makes attribution free: the grade-parity
#: run already prints this, so no second invocation and no changed command is needed.
_SUMMARY_KILLER_RE = re.compile(r"^(?:FAILED|ERROR)\s+(\S+::\S+)", re.MULTILINE)
#: The per-failure banner inside the ``=== FAILURES ===`` section
#: (``______ test_x ______``). A fallback for a repo whose config suppresses the summary but
#: not the traceback; a name containing whitespace (``ERROR at setup of test_x``) is left to
#: the line above rather than guessed at here.
_HEADER_KILLER_RE = re.compile(r"^_+ (\S+) _+$", re.MULTILINE)


def _test_name(node_id: str) -> str:
    """The bare test-function name of a pytest node id: the last ``::`` segment (or the last
    ``.`` segment of a ``Class.method`` banner) with any parametrisation dropped.

    ``tests/t.py::TestDeck::test_add[2]`` → ``test_add``. This is the SAME grain a consumer
    can hold — an AST reader of the exam sees ``def test_add``, never a node id — so the
    normalisation happens here, once, beside the producer."""
    name = (node_id or "").rsplit("::", 1)[-1].rsplit(".", 1)[-1]
    return name.split("[", 1)[0].strip()


def failing_tests(blob: str) -> tuple[str, ...]:
    """The test-function names that FAILED in a pytest run, sorted and deduplicated.

    Empty is a legitimate and load-bearing answer: it means *this run does not say who
    failed*, which happens when a repo's own ``pytest.ini`` suppresses the summary and the
    traceback (``addopts = -rN --tb=no`` — measured on the pinned runner, both sections
    vanish). A caller must treat empty as "cannot attribute", never as "nothing failed" — the
    RED/GREEN question is already answered by the exit code, and this only ever names names."""
    text = blob or ""
    names = {_test_name(m) for m in _SUMMARY_KILLER_RE.findall(text)}
    if not names:
        names = {_test_name(m) for m in _HEADER_KILLER_RE.findall(text)}
    return tuple(sorted(n for n in names if n))


def oracle_digest(oracle_code: str) -> str:
    """SHA-256 of the exact oracle text an audit mutated against.

    Banked so a downstream grader can prove it is reading the attribution of the SAME exam it
    is grading. Two exams in one run dir, or a re-seeded oracle between the audit and the
    read, would otherwise let one exam's kills be credited to another exam's tests — a
    misattribution that would look exactly like evidence."""
    return hashlib.sha256((oracle_code or "").encode("utf-8", "replace")).hexdigest()


def _mutant_row(item: dict, outcome: str, killers: "tuple[str, ...]") -> dict:
    """One mutant's attribution row: WHERE it was injected, and WHO caught it.

    ``killed_by`` is populated only for a killed mutant and may still be empty (see
    :func:`failing_tests`). ``symbol`` may be ``""`` (module-level site). Both empties mean
    "no rung can be awarded from this row", never "the row proves an absence"."""
    row = {
        "operator": item["operator"],
        "file": item["target"].relpath,
        "line": item["lineno"],
        "symbol": item["symbol"],
        "outcome": outcome,
        "killed_by": list(killers[:_MAX_KILLERS_RECORDED]),
    }
    if len(killers) > _MAX_KILLERS_RECORDED:
        row[_KILLERS_TRUNCATED_KEY] = True
    return row


def _mutant_verdict(ok: bool, blob: str) -> Optional[bool]:
    """Interpret a mutant's oracle run: ``True`` = oracle PASSED (mutant SURVIVED),
    ``False`` = oracle went RED on a run that actually completed (mutant KILLED),
    ``None`` = machinery miss (timeout / crash / no-runner — pytest never produced a
    summary). A miss is honestly NOT COUNTED (never inflates kills), reusing #821's
    completion detector."""
    if ok:
        return True
    if oracle_qa._run_completed(blob):
        return False
    return None


# ---------------------------------------------------------------------------
# Evidence + the public audit
# ---------------------------------------------------------------------------


def _base_evidence(rel_path: str, budget_s: float) -> dict:
    """The stable ``oracle-mutation.json`` shape (every key present so #827/#837 see
    a fixed schema even on a skip). Carries NO verdict field — the ADVISORY-ONLY
    invariant is structural (§Decision-1 invariant 5)."""
    return {
        "audit": "oracle_mutation",
        "language": "node" if rel_path.endswith((".mjs", ".js")) else "python",
        "mutation_audit": "not-run",
        "oracle_mutation_score": "0/0",
        "oracle_mutation_coverage": "unknown",
        "killed": 0,
        "survived": 0,
        "ran": 0,
        # Always present for the same reason as the attribution keys below: a consumer must
        # never have to tell "this audit predates budget accounting" from "this audit dropped
        # nothing" by key absence (#1231).
        "not_run": 0,
        "unreachable": 0,
        "planned": 0,
        "total_sites": 0,
        "by_operator": {},
        "survivors": [],
        "targets": [],
        "seed": "",
        "budget_s": float(budget_s),
        # Attribution, always present so a consumer never has to distinguish "this audit
        # predates attribution" from "this audit attributed nothing" by key absence.
        EV_ORACLE_PATH: rel_path,
        EV_ORACLE_SHA: "",
        EV_MUTANTS: [],
    }


#: The ``mutation_audit`` stamps under which a score was actually established. Every other
#: stamp is a machinery miss, and :func:`is_measured` refuses to read it as a result.
#: ``partial-machinery`` belongs here for the same reason ``partial-budget`` does: mutants
#: were missed, but the ones that ran produced a real verdict, and discarding that evidence
#: would trade one distortion for another. The completeness question is answered by the
#: stamp and by ``not_run`` / ``unreachable``, never by the score alone (#1231).
MEASURED_STATUSES: frozenset[str] = frozenset(
    {"run", "partial-budget", "partial-machinery"})


def not_measured_evidence(rel_path: str, reason: str, budget_s: float = ORACLE_MUTATION_BUDGET_S) -> dict:
    """The stable evidence shape for an audit that never got to run, stamped with *reason*.

    For a CALLER that fails its own precondition (no run dir, no banked oracle, no resolvable
    tree) before :func:`run_oracle_mutation_audit` is reachable. Such a caller must still bank
    a sidecar: a run with no ``oracle-mutation.json`` at all is indistinguishable from a run
    whose audit found nothing, and that ambiguity is the fail-open this audit exists to refuse.
    Carries no verdict field, exactly like every other emission here."""
    evidence = _base_evidence(rel_path, budget_s)
    evidence["mutation_audit"] = reason
    return evidence


def is_measured(evidence: dict) -> bool:
    """Whether *evidence* records an audit that ACTUALLY discriminated — a run that completed
    (or partially completed under budget) AND counted at least one mutant.

    The single predicate every reader uses, so ``killed == 0`` from a vacuous oracle can never
    be confused with ``killed == 0`` because nothing ever ran. A ``0/0`` is not a clean sheet."""
    if not isinstance(evidence, dict):
        return False
    return (
        str(evidence.get("mutation_audit", "")) in MEASURED_STATUSES
        and int(evidence.get("ran", 0) or 0) > 0
    )


def _band(killed: int, ran: int, not_run: int = 0) -> str:
    """The advisory coverage band (a quality opinion, never a verdict): ``unknown``
    when nothing ran, ``strong`` at 100% kills, ``adequate`` at ≥80% (the mutation-
    testing convention), ``weak`` below — the #828 low-score → ``weak`` stamp.

    ``not_run`` counts mutants the budget dropped before they were attempted, and they
    count AGAINST the band (#1231). The band describes the SELECTED set; a mutant that
    was never run is not evidence of a kill, so folding it into the denominator is the
    fail-closed reading. Without it the band rose as the budget fell — the audit looked
    better the less of it actually happened, which is the one direction a quality signal
    must never move.

    ``unknown`` still wins when nothing ran at all: with no attempts there is no opinion
    to hold, and reporting ``weak`` would assert a finding the run cannot support."""
    if ran <= 0:
        return "unknown"
    frac = killed / (ran + max(0, not_run))
    if frac >= 1.0:
        return "strong"
    if frac >= 0.8:
        return "adequate"
    return "weak"


def _persist(config, run_id: str, evidence: dict) -> None:
    """Best-effort write of the evidence to ``<run>/oracle-mutation.json`` (mirrors
    #821's ``oracle-qa.json``). Never fatal — a persistence miss is not a defect in
    an advisory pass."""
    try:
        out = Path(config.runs_dir) / run_id / ORACLE_MUTATION_SIDECAR_NAME
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    except (OSError, AttributeError, TypeError):
        pass


def _done(evidence: dict, config, run_id: str, persist: bool) -> dict:
    if persist and config is not None:
        _persist(config, run_id, evidence)
    return evidence


def run_oracle_mutation_audit(
    config,
    run_id: str,
    repo: str,
    rel_path: str,
    oracle_code: str,
    *,
    run: "Callable[..., tuple[bool, str, str]] | None" = None,
    pytest_cmd: "Callable[[str], list[str] | None] | None" = None,
    budget_s: float = ORACLE_MUTATION_BUDGET_S,
    max_mutants: int = MAX_MUTANTS,
    persist: bool = True,
    clock: Callable[[], float] = time.monotonic,
) -> dict:
    """Run the bounded, offline, deterministic mutation audit for ONE passing job
    and return (and persist) the ADVISORY evidence dict.

    Precondition: the caller passes the SAME raw plan oracle bytes
    ``real_run_job_oracle`` grades (not the seed-guarded copy) for a job whose
    oracle PASSED (the GREEN path). ``run``/``pytest_cmd`` are injectable for tests;
    live callers get grade-parity ``uv`` + #821's ``_default_run``.

    The evidence NEVER carries a verdict — a low ``oracle_mutation_score`` stamps
    ``oracle_mutation_coverage: weak`` and nothing else moves. Every off-nominal
    path is an honest ``mutation_audit`` skip stamp."""
    evidence = _base_evidence(rel_path, budget_s)

    if not oracle_mutation_enabled():
        evidence["mutation_audit"] = "skipped-disabled"
        return _done(evidence, config, run_id, persist)
    if not oracle_code:
        evidence["mutation_audit"] = "skipped-no-oracle"
        return _done(evidence, config, run_id, persist)
    if not rel_path.endswith(".py"):
        # Node/web mutation is #830 territory — no host .js mutation runner exists.
        evidence["mutation_audit"] = "skipped-no-python-runner"
        return _done(evidence, config, run_id, persist)
    # Stamped as soon as the exam bytes are known to be auditable, so even a later skip
    # records WHICH exam was declined rather than leaving that unanswerable.
    evidence[EV_ORACLE_SHA] = oracle_digest(oracle_code)

    targets = _resolve_targets(repo, oracle_code, rel_path)
    if not targets:
        evidence["mutation_audit"] = "skipped-no-targets"
        return _done(evidence, config, run_id, persist)
    evidence["targets"] = [t.relpath for t in targets]
    evidence["seed"] = _seed_digest(targets)

    pool: list[dict] = []
    for t in sorted(targets, key=lambda x: x.relpath):
        for k, (op, lineno, symbol) in enumerate(t.sites):
            pool.append({"target": t, "k": k, "operator": op, "lineno": lineno,
                         "symbol": symbol})
    evidence["total_sites"] = len(pool)
    selected = _select(pool, max(0, int(max_mutants)))
    evidence["planned"] = len(selected)
    if not selected:
        evidence["mutation_audit"] = "skipped-no-sites"
        return _done(evidence, config, run_id, persist)

    runner = run if run is not None else oracle_qa._default_run
    build_cmd = pytest_cmd if pytest_cmd is not None else _grade_cmd
    cmd = build_cmd(rel_path)
    if not cmd:
        evidence["mutation_audit"] = "skipped-no-runner"
        return _done(evidence, config, run_id, persist)

    per_mutant_cap = float(oracle_qa.ORACLE_QA_F2P_TIMEOUT_S)
    repo_path = Path(repo).resolve()
    oracle_target = repo_path / rel_path
    oracle_prior = _read_bytes(oracle_target)
    file_priors = {t.relpath: _read_bytes(repo_path / t.relpath) for t in targets}
    deadline = clock() + float(budget_s)

    killed = ran = 0
    survivors: list[dict] = []
    mutants: list[dict] = []
    by_op: dict[str, dict[str, int]] = {op: {"killed": 0, "ran": 0} for op in OPERATORS}
    budget_hit = False
    # Mutants the budget dropped before they were ever attempted. They are NOT in ``ran``
    # (they were not put to the question) and NOT in ``killed`` — so without them the score
    # loses its denominator as the budget tightens, and reads BETTER the less work was done.
    dropped: list[dict] = []
    # Mutants the MACHINERY could not put to the question: source that would not unparse,
    # or a run that returned no readable verdict (per-mutant timeout). Same standing as a
    # budget drop for the band's purposes — neither is evidence that the oracle caught
    # anything — but tracked separately because the causes need different fixes.
    unreachable: list[dict] = []
    try:
        oracle_target.parent.mkdir(parents=True, exist_ok=True)
        oracle_target.write_text(oracle_code, encoding="utf-8")  # plan bytes ALWAYS win

        # Baseline: the GREEN precondition — the oracle must actually PASS ≥1 test on
        # the unmutated tree, or "killed vs survived" is meaningless. An exit-0 run
        # with 0 passed (all-skipped guard / collected-0) is NOT green.
        base_ok, base_blob = _run_oracle(
            str(repo_path), cmd, runner, min(per_mutant_cap, max(1.0, deadline - clock())))
        if not (base_ok and _passed_count(base_blob) >= 1):
            evidence["mutation_audit"] = (
                "skipped-baseline-not-green"
                if oracle_qa._run_completed(base_blob) else "skipped-baseline-not-run"
            )
            return _done(evidence, config, run_id, persist)

        for idx, item in enumerate(selected):
            if clock() >= deadline:
                budget_hit = True
                dropped = selected[idx:]
                break
            target: _Target = item["target"]
            op = item["operator"]
            src = _mutant_source(target.tree, item["k"])
            if src is None:
                # Un-unparseable mutant. It was never put to the question, so it counts
                # exactly like a budget drop: recorded, and counted AGAINST the band.
                unreachable.append(item)
                continue
            target_file = repo_path / target.relpath
            try:
                target_file.write_text(src, encoding="utf-8")
                remaining = deadline - clock()
                if remaining <= 0:
                    budget_hit = True
                    dropped = selected[idx:]
                    break
                m_ok, m_blob = _run_oracle(
                    str(repo_path), cmd, runner, min(per_mutant_cap, max(1.0, remaining)))
            finally:
                _restore(target_file, file_priors.get(target.relpath))
            verdict = _mutant_verdict(m_ok, m_blob)
            if verdict is None:
                # The mutant ran but the runner produced nothing readable (a per-mutant
                # timeout is the common cause). "Honestly not counted" was only half the
                # job: excluded from the DENOMINATOR too, seven timeouts out of eight left
                # `run — 1/1 — strong` with no partial stamp to contradict it — a stronger
                # false claim than the budget case, because nothing marked it incomplete.
                unreachable.append(item)
                continue
            ran += 1
            by_op[op]["ran"] += 1
            if verdict is False:  # oracle RED → mutant KILLED (the oracle has teeth here)
                killed += 1
                by_op[op]["killed"] += 1
                # WHO caught it, from the run pytest has already printed. Parsed only on the
                # RED path: a passing run names no failures, and asking it to would be the
                # kind of question whose empty answer invites a wrong reading.
                mutants.append(_mutant_row(item, "killed", failing_tests(m_blob)))
            else:  # oracle passed wrong code
                mutants.append(_mutant_row(item, "survived", ()))
                if len(survivors) < _MAX_SURVIVORS_REPORTED:
                    survivors.append(
                        {"operator": op, "file": target.relpath, "line": item["lineno"],
                         "symbol": item["symbol"]})
    finally:
        _restore(oracle_target, oracle_prior)
        for t in targets:
            _restore(repo_path / t.relpath, file_priors.get(t.relpath))

    evidence["killed"] = killed
    evidence["ran"] = ran
    evidence["survived"] = ran - killed
    # ``planned`` (above) is the authority on the selection size; no second key restates it.
    # The three accounted buckets reconcile against it: ran + not_run + unreachable.
    evidence["not_run"] = len(dropped)
    evidence["unreachable"] = len(unreachable)
    evidence["oracle_mutation_score"] = f"{killed}/{ran}"
    # The BAND is an opinion about the SELECTED set, not about the subset that happened to
    # get a verdict, so every mutant that was NOT put to the question counts against it --
    # whether the budget dropped it or the machinery could not reach it. Scoring on ``ran``
    # alone made it rise as the work fell: 7 of 8 mutants timing out reported the same
    # "strong" as 8 of 8 killed. An unknown must never be able to improve a quality claim,
    # and the two causes are equivalent here because neither is evidence of a kill.
    evidence["oracle_mutation_coverage"] = _band(
        killed, ran, len(dropped) + len(unreachable))
    evidence["by_operator"] = {op: v for op, v in by_op.items() if v["ran"]}
    evidence["survivors"] = survivors
    # Every mutant the audit accounted for: killed, survived, or never attempted. The
    # ``not-run`` rows are what keep a partial audit from LOOKING complete downstream --
    # traceability's ``mutated`` already admits only killed/survived, so these rows are
    # recorded without ever being read as "this subject was put to the question".
    evidence[EV_MUTANTS] = (
        mutants
        + [_mutant_row(item, "not-run", ()) for item in dropped]
        + [_mutant_row(item, "no-verdict", ()) for item in unreachable]
    )
    if budget_hit:
        evidence["mutation_audit"] = "partial-budget" if ran else "skipped-budget"
    elif unreachable:
        # ``run`` asserts the audit completed. With mutants the machinery never reached,
        # it did not -- and this path carries no other signal that anything was missed,
        # which is what made it the more misleading of the two partial cases.
        evidence["mutation_audit"] = "partial-machinery" if ran else "skipped-machinery"
    else:
        evidence["mutation_audit"] = "run"
    return _done(evidence, config, run_id, persist)


# ---------------------------------------------------------------------------
# Small filesystem helpers (capture/restore — the tree is left EXACTLY as found)
# ---------------------------------------------------------------------------


def _read_bytes(path: Path) -> "bytes | None":
    try:
        return path.read_bytes()
    except OSError:
        return None


def _restore(path: Path, prior: "bytes | None") -> None:
    """Put ``path`` back exactly as captured (write prior bytes, or remove if it did
    not exist before). Best-effort — a restore miss must never raise out of the
    audit (the audit is advisory; a raise here would be worse than the miss)."""
    try:
        if prior is not None:
            path.write_bytes(prior)
        else:
            path.unlink(missing_ok=True)
    except OSError:
        pass
