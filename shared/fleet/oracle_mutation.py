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
DORMANT until a GREEN-path caller invokes it (offline / off the dispatch critical
path); kill-switchable via ``BLARAI_ORACLE_MUTATION`` (default ON — inert until a
caller runs it, so ON is safe).
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

from shared.fleet import oracle_qa

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


def oracle_mutation_enabled() -> bool:
    """The kill-switch: ON unless ``BLARAI_ORACLE_MUTATION`` is a falsey token.

    Defaults ON. Because nothing on the dispatch critical path calls the audit yet
    (it is an offline / GREEN-only pass), ON is inert until a caller invokes it;
    OFF makes the entry point a no-op skip. Read at the entry point so a disabled
    audit never parses a file or spawns a subprocess."""
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
    """One mutation opportunity: its operator class, source line, and the in-place
    ``mutate`` closure over the specific node in a (deep-copied) tree."""

    operator: str
    lineno: int
    mutate: Callable[[], None]


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


def _iter_sites(tree: ast.AST) -> list[_Site]:
    """Every mutation opportunity in ``tree``, in a DETERMINISTIC order (``ast.walk``
    BFS — stable across the deep copy used for application, so the k-th site here
    and the k-th site in a copy are the SAME logical mutation). Each ``_Site``
    closes over ``tree``'s own nodes."""
    sites: list[_Site] = []
    for node in ast.walk(tree):
        line = int(getattr(node, "lineno", 0) or 0)
        if isinstance(node, ast.Compare):
            for i, op in enumerate(node.ops):
                repl = _BOUNDARY_FLIP.get(type(op))
                if repl is not None:
                    sites.append(_Site(OP_BOUNDARY, line, _flip_compare(node, i, repl)))
        elif isinstance(node, ast.BinOp):
            repl = _ARITH_FLIP.get(type(node.op))
            if repl is not None:
                sites.append(_Site(OP_ARITHMETIC, line, _flip_binop(node, repl)))
        elif isinstance(node, ast.Constant):
            if _perturbable_const(node.value):
                sites.append(_Site(OP_CONSTANT, line, _perturb_const(node)))
        elif isinstance(node, ast.If):
            sites.append(_Site(OP_NEGATE_COND, line, _negate_if(node)))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _nontrivial_body(node):
                sites.append(_Site(OP_EARLY_RETURN, line, _inject_return(node)))
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
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []
    return [(s.operator, s.lineno) for s in _iter_sites(tree)]


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
    sites: list[tuple[str, int]]


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
                sites=[(s.operator, s.lineno) for s in sites],
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


def _mutation_env(isolated_home: Path, repo: str) -> dict:
    """A subprocess env with LOCALAPPDATA/APPDATA redirected into an isolated dir
    (the standing 'LOCALAPPDATA-redirected pytest ALWAYS' discipline — the audit
    never touches the operator's app data), bytecode off, and the repo on
    PYTHONPATH so the oracle's first-party imports resolve exactly as ``-m pytest``
    from ``cwd=repo`` would (safe-path is left DEFAULT for grade parity)."""
    env = dict(os.environ)
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
        "planned": 0,
        "total_sites": 0,
        "by_operator": {},
        "survivors": [],
        "targets": [],
        "seed": "",
        "budget_s": float(budget_s),
    }


def _band(killed: int, ran: int) -> str:
    """The advisory coverage band (a quality opinion, never a verdict): ``unknown``
    when nothing ran, ``strong`` at 100% kills, ``adequate`` at ≥80% (the mutation-
    testing convention), ``weak`` below — the #828 low-score → ``weak`` stamp."""
    if ran <= 0:
        return "unknown"
    frac = killed / ran
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
        out = Path(config.runs_dir) / run_id / "oracle-mutation.json"
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

    targets = _resolve_targets(repo, oracle_code, rel_path)
    if not targets:
        evidence["mutation_audit"] = "skipped-no-targets"
        return _done(evidence, config, run_id, persist)
    evidence["targets"] = [t.relpath for t in targets]
    evidence["seed"] = _seed_digest(targets)

    pool: list[dict] = []
    for t in sorted(targets, key=lambda x: x.relpath):
        for k, (op, lineno) in enumerate(t.sites):
            pool.append({"target": t, "k": k, "operator": op, "lineno": lineno})
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
    by_op: dict[str, dict[str, int]] = {op: {"killed": 0, "ran": 0} for op in OPERATORS}
    budget_hit = False
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

        for item in selected:
            if clock() >= deadline:
                budget_hit = True
                break
            target: _Target = item["target"]
            op = item["operator"]
            src = _mutant_source(target.tree, item["k"])
            if src is None:
                continue  # un-unparseable mutant — skipped, never counted
            target_file = repo_path / target.relpath
            try:
                target_file.write_text(src, encoding="utf-8")
                remaining = deadline - clock()
                if remaining <= 0:
                    budget_hit = True
                    break
                m_ok, m_blob = _run_oracle(
                    str(repo_path), cmd, runner, min(per_mutant_cap, max(1.0, remaining)))
            finally:
                _restore(target_file, file_priors.get(target.relpath))
            verdict = _mutant_verdict(m_ok, m_blob)
            if verdict is None:
                continue  # machinery miss — honestly not counted
            ran += 1
            by_op[op]["ran"] += 1
            if verdict is False:  # oracle RED → mutant KILLED (the oracle has teeth here)
                killed += 1
                by_op[op]["killed"] += 1
            elif len(survivors) < _MAX_SURVIVORS_REPORTED:  # oracle passed wrong code
                survivors.append(
                    {"operator": op, "file": target.relpath, "line": item["lineno"]})
    finally:
        _restore(oracle_target, oracle_prior)
        for t in targets:
            _restore(repo_path / t.relpath, file_priors.get(t.relpath))

    evidence["killed"] = killed
    evidence["ran"] = ran
    evidence["survived"] = ran - killed
    evidence["oracle_mutation_score"] = f"{killed}/{ran}"
    evidence["oracle_mutation_coverage"] = _band(killed, ran)
    evidence["by_operator"] = {op: v for op, v in by_op.items() if v["ran"]}
    evidence["survivors"] = survivors
    if budget_hit:
        evidence["mutation_audit"] = "partial-budget" if ran else "skipped-budget"
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
