# enforces-rule: security_by_design.principles.validate-before-trust -- purpose binding only
"""`purpose` is a PATH IDENTITY, not a claim the model makes (#1586, #977).

The one Policy-Agent-gated egress door takes a caller-supplied ``purpose``
string (``shared/security/guarded_fetch.py``). A #977 redesign that rests any
adjudication on that string is only safe if the string cannot be chosen by the
model. This file settles that, and keeps it settled.

**The answer: the model chooses a DOOR, never the string.** Every runtime path
into ``fetch_external`` / ``fetch_external_binary`` carries a compiled-in
module-level literal. The model's only influence is which tool it calls, which
selects which literal is pinned on the way through. A model can no more type a
``purpose`` than it can type one of its own source file's constants.

**Why this is AST and not a text search.** A source scan cannot tell a call from
a comment, and cannot tell a module constant from a parameter that happens to
share its name. Both have defeated locks in this repository.

**What the analyser understands, and what it does with what it does not.** It
classifies every direct call to the door, and every call through an injected
``*_fetch_fn`` callable — including the
``asyncio.to_thread(self._url_fetch_fn, url, PURPOSE)`` shape both shipped
gateway sites use, where the callable travels as data and the purpose travels as
a positional. It resolves ``from X import NAME`` to X's module-level binding,
follows a parameter-threaded argument through its callers with a depth bound and
a cycle guard, and refuses to treat a name bound more than once at module level
as a constant. **Any arrangement it does not recognise is FORGEABLE, never
proof** — an unrecognised indirection is the one case where guessing favourably
would defeat the whole purpose of the check.
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]

#: The one sanctioned egress door's two entrypoints.
_DOOR_FUNCS = frozenset({"fetch_external", "fetch_external_binary"})

#: Attribute-name suffix marking an injected egress-fetch callable. The ingest
#: coordinator holds the door behind ``self._url_fetch_fn`` /
#: ``self._image_fetch_fn`` so the corridor is testable with a fake.
_FETCH_ATTR_SUFFIX = "_fetch_fn"

#: Bound on caller-chasing. Reaching it is a FAILURE, not a pass: an argument
#: whose origin could not be followed has not been shown to be pinned.
_MAX_DEPTH = 6

#: The trees this claim is SCOPED TO. `scripts/`, `tools/` and `evals/` are
#: deliberately outside it — they are operator-run, not model-reachable — so
#: "every runtime path" means every path in these three. `scripts/
#: uc003_live_fetch_smoke.py` does call the door and does carry a literal;
#: it is simply not what this lock is about (#1586 review, finding 8).
_RUNTIME_ROOTS = ("services", "shared", "launcher")
_EXCLUDED_DIR_NAMES = frozenset({"tests", "__pycache__"})


# ---------------------------------------------------------------------------
# The analyser
# ---------------------------------------------------------------------------
def _runtime_files(repo: Path) -> list[Path]:
    out: list[Path] = []
    for root in _RUNTIME_ROOTS:
        base = repo / root
        if not base.exists():
            continue
        for f in base.rglob("*.py"):
            if _EXCLUDED_DIR_NAMES & set(f.parts) or f.name.startswith("test_"):
                continue
            out.append(f)
    return out


def _called_name(call: ast.Call, module: "_Module | None" = None) -> str | None:
    """The name this call refers to, resolved through module-level import aliases.

    **Matching the SPELLED name failed open (#1586 review, finding 1A.)**
    ``from shared.security.guarded_fetch import fetch_external as _f`` followed by
    ``_f(url, purpose)`` reaches the door under a name the analyser had never
    heard of, so it produced NO ROW — not a FORGEABLE one, none at all. A hole
    that emits nothing is worse than one that emits a finding, because the report
    looks complete.

    An alias is resolved to the name it was imported UNDER, so the door is
    recognised however it is spelled at the call site. An attribute call
    (``guarded_fetch.fetch_external(...)``) still matches on the attribute.
    """
    if isinstance(call.func, ast.Name):
        name = call.func.id
        if module is not None:
            return module.import_origin_names.get(name, name)
        return name
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


class _Module:
    """One parsed runtime module and the facts the resolver needs from it."""

    def __init__(self, path: Path, repo: Path) -> None:
        self.rel = path.relative_to(repo).as_posix()
        self.tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        self.consts = self._single_assign_string_constants()
        self.imported_names = self._imported_names()
        self.import_origin_names = self._import_origin_names()
        self._functions = [
            n
            for n in ast.walk(self.tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]

    def _single_assign_string_constants(self) -> dict[str, str]:
        """Module-level names bound EXACTLY ONCE to a string literal.

        A name rebound at module level is not a constant however it is spelled,
        and the LAST binding is what ships — so such names are excluded rather
        than trusted.
        """
        counts: dict[str, int] = {}
        values: dict[str, str] = {}
        for node in self.tree.body:
            targets: list[ast.expr] = []
            value: ast.expr | None = None
            if isinstance(node, ast.Assign):
                targets, value = list(node.targets), node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets, value = [node.target], node.value
            for t in targets:
                if isinstance(t, ast.Name):
                    counts[t.id] = counts.get(t.id, 0) + 1
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        values[t.id] = value.value
        return {n: v for n, v in values.items() if counts.get(n) == 1}

    def _imported_names(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for alias in node.names:
                    out[alias.asname or alias.name] = node.module
        return out

    def _import_origin_names(self) -> dict[str, str]:
        """local name -> the name it was imported UNDER.

        ``from x import fetch_external as _f`` gives ``{"_f": "fetch_external"}``,
        so a call spelled ``_f(...)`` is recognised as the door (#1586 review 1A).
        Identity entries are kept too, which costs nothing and keeps the lookup
        total.
        """
        out: dict[str, str] = {}
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    out[alias.asname or alias.name] = alias.name
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.asname:
                        out[alias.asname] = alias.name
        return out

    def enclosing_function(
        self, node: ast.AST
    ) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
        best = None
        line = getattr(node, "lineno", -1)
        for fn in self._functions:
            if fn.lineno <= line <= (fn.end_lineno or fn.lineno):
                if best is None or fn.lineno > best.lineno:
                    best = fn
        return best


def _param_names(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    a = fn.args
    names = [arg.arg for arg in [*a.posonlyargs, *a.args, *a.kwonlyargs]]
    if a.vararg:
        names.append(a.vararg.arg)
    if a.kwarg:
        names.append(a.kwarg.arg)
    return names


def _default_for(
    fn: ast.FunctionDef | ast.AsyncFunctionDef, param: str
) -> ast.expr | None:
    a = fn.args
    positional = [arg.arg for arg in [*a.posonlyargs, *a.args]]
    if param in positional and a.defaults:
        offset = len(positional) - len(a.defaults)
        idx = positional.index(param) - offset
        if idx >= 0:
            return a.defaults[idx]
    for arg, default in zip(a.kwonlyargs, a.kw_defaults):
        if arg.arg == param:
            return default
    return None


def _injected_fetch_seam(
    call: ast.Call, module: "_Module | None" = None
) -> tuple[str, ast.expr | None] | None:
    """Classify a call reaching the door through an injected callable.

    Recognises ``self._url_fetch_fn(url, PURPOSE)`` and
    ``asyncio.to_thread(self._url_fetch_fn, url, PURPOSE)``. Returns
    ``(attribute_name, purpose_expression)``, with ``None`` for the expression
    when no purpose argument can be identified — which the caller reports as
    FORGEABLE. Returns ``None`` entirely when this is not a fetch seam.
    """

    def _attr_name(expr: ast.expr) -> str | None:
        if isinstance(expr, ast.Attribute) and expr.attr.endswith(_FETCH_ATTR_SUFFIX):
            return expr.attr
        if isinstance(expr, ast.Name) and expr.id.endswith(_FETCH_ATTR_SUFFIX):
            return expr.id
        return None

    if _called_name(call, module) == "to_thread" and call.args:
        name = _attr_name(call.args[0])
        if name is None:
            return None
        kw = next((k for k in call.keywords if k.arg == "purpose"), None)
        if kw is not None:
            return (name, kw.value)
        rest = call.args[1:]
        return (name, rest[1] if len(rest) > 1 else None)

    name = _attr_name(call.func)
    if name is None:
        return None
    kw = next((k for k in call.keywords if k.arg == "purpose"), None)
    if kw is not None:
        return (name, kw.value)
    return (name, call.args[1] if len(call.args) > 1 else None)


class _Resolver:
    def __init__(self, modules: list[_Module]) -> None:
        self.modules = modules
        self.by_dotted: dict[str, _Module] = {}
        for m in modules:
            dotted = m.rel[:-3].replace("/", ".")
            self.by_dotted[dotted] = m
            if dotted.endswith(".__init__"):
                self.by_dotted[dotted[: -len(".__init__")]] = m

    def resolve_name(self, mod: _Module, name: str, depth: int) -> tuple[str, str]:
        if depth > _MAX_DEPTH:
            return ("FORGEABLE", f"depth bound reached resolving {name}")
        if name in mod.consts:
            return ("PINNED", f"{mod.rel}:{name}={mod.consts[name]!r}")
        src = mod.imported_names.get(name)
        if src is not None:
            target = self.by_dotted.get(src)
            if target is None:
                return ("FORGEABLE", f"{name} imported from unscanned module {src}")
            return self.resolve_name(target, name, depth + 1)
        return ("FORGEABLE", f"{name} is not a single-assignment module constant")

    def classify(
        self,
        mod: _Module,
        expr: ast.expr,
        node: ast.AST,
        depth: int,
        seen: frozenset[tuple[str, str]],
    ) -> tuple[str, str]:
        if depth > _MAX_DEPTH:
            return ("FORGEABLE", "depth bound reached")
        if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
            return ("PINNED", f"literal {expr.value!r}")
        if isinstance(expr, ast.Name):
            fn = mod.enclosing_function(node)
            if fn is not None and expr.id in _param_names(fn):
                return self.resolve_through_callers(mod, fn, expr.id, depth, seen)
            return self.resolve_name(mod, expr.id, depth)
        return ("FORGEABLE", f"expression of type {type(expr).__name__}")

    def resolve_through_callers(
        self,
        mod: _Module,
        fn: ast.FunctionDef | ast.AsyncFunctionDef,
        param: str,
        depth: int,
        seen: frozenset[tuple[str, str]],
    ) -> tuple[str, str]:
        key = (mod.rel, fn.name)
        if key in seen:
            return ("FORGEABLE", f"cycle resolving {fn.name}({param})")
        seen = seen | {key}

        ordered = [a.arg for a in [*fn.args.posonlyargs, *fn.args.args]]
        index = ordered.index(param) if param in ordered else None

        outcomes: list[tuple[str, str]] = []
        call_sites = 0
        for caller in self.modules:
            for call in ast.walk(caller.tree):
                if not isinstance(call, ast.Call) or _called_name(call, caller) != fn.name:
                    continue
                call_sites += 1
                kw = next((k for k in call.keywords if k.arg == param), None)
                if kw is not None:
                    outcomes.append(self.classify(caller, kw.value, call, depth + 1, seen))
                elif index is not None and len(call.args) > index:
                    outcomes.append(
                        self.classify(caller, call.args[index], call, depth + 1, seen)
                    )
                else:
                    default = _default_for(fn, param)
                    if default is not None:
                        outcomes.append(
                            self.classify(caller, default, call, depth + 1, seen)
                        )
                    else:
                        outcomes.append(
                            (
                                "FORGEABLE",
                                f"{caller.rel}:{call.lineno} passes {param} indirectly",
                            )
                        )

        if call_sites == 0:
            attr = self.find_seam_binding(fn.name)
            if attr is not None:
                return (
                    "FORWARDER",
                    f"{fn.name} forwards {param}; bound to {attr} — the seam row decides",
                )
            return ("UNCALLED", f"no runtime caller or value-binding of {fn.name} found")

        bad = [o for o in outcomes if o[0] != "PINNED"]
        if bad:
            return (
                "FORGEABLE",
                f"via {fn.name}({param}): " + "; ".join(d for _, d in bad[:3]),
            )
        return ("PINNED", f"via {fn.name}({param}): all {len(outcomes)} caller(s) pinned")

    def find_seam_binding(self, func_name: str) -> str | None:
        """The ``*_fetch_fn`` attribute a function is bound to, if any.

        Matches ``self._url_fetch_fn = url_fetch_fn or _default_url_fetch``.
        Returns the attribute name so a FORWARDER verdict can say WHICH seam
        carries it, rather than merely asserting that one does.
        """
        for mod in self.modules:
            for node in ast.walk(mod.tree):
                if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                    continue
                if node.value is None:
                    continue
                if not any(
                    isinstance(n, ast.Name) and n.id == func_name
                    for n in ast.walk(node.value)
                ):
                    continue
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for t in targets:
                    if isinstance(t, ast.Attribute) and t.attr.endswith(
                        _FETCH_ATTR_SUFFIX
                    ):
                        return t.attr
        return None


def _classify_purpose_sites(repo: Path) -> list[tuple[str, int, str, str, str]]:
    """Every egress-door purpose site under ``repo``, classified."""
    modules: list[_Module] = []
    for path in _runtime_files(repo):
        try:
            modules.append(_Module(path, repo))
        except SyntaxError:  # pragma: no cover - a repo that does not parse
            continue
    resolver = _Resolver(modules)

    rows: list[tuple[str, int, str, str, str]] = []
    for mod in modules:
        for node in ast.walk(mod.tree):
            if not isinstance(node, ast.Call):
                continue
            fname = _called_name(node, mod)
            if fname in _DOOR_FUNCS:
                kw = next((k for k in node.keywords if k.arg == "purpose"), None)
                if kw is None:
                    rows.append((mod.rel, node.lineno, fname, "FORGEABLE", "no purpose argument"))
                    continue
                verdict, detail = resolver.classify(mod, kw.value, node, 0, frozenset())
                rows.append((mod.rel, node.lineno, fname, verdict, detail))
                continue

            seam = _injected_fetch_seam(node, mod)
            if seam is None:
                continue
            attr, purpose_expr = seam
            if purpose_expr is None:
                rows.append(
                    (
                        mod.rel,
                        node.lineno,
                        f"via {attr}",
                        "FORGEABLE",
                        "injected fetch callable invoked with no identifiable purpose",
                    )
                )
                continue
            verdict, detail = resolver.classify(mod, purpose_expr, node, 0, frozenset())
            rows.append((mod.rel, node.lineno, f"via {attr}", verdict, detail))
    return rows


def _unsettled(rows: list[tuple[str, int, str, str, str]]) -> list[tuple[str, int, str, str, str]]:
    """Rows that do not amount to a pinned purpose.

    A FORWARDER is not itself pinned and is not itself a hole: it hands the
    question to a NAMED seam. It settles only if that seam has a PINNED row,
    which is looked up rather than assumed.
    """
    # PER MODULE, and the scoping is the fix for #1586 review finding 1B.
    # This set used to be tree-wide, so a FORWARDER in ANY module was excused by
    # a pinned seam of the same attribute NAME in ANY OTHER module. A second
    # consumer that named its injected seam `_url_fetch_fn` — the obvious name to
    # copy from ingest_coordinator — inherited that module's proof without having
    # earned it, and could then thread a model-supplied purpose through.
    # A proof belongs to the module that carries it.
    seam_pinned: dict[str, set[str]] = {}
    for rel, _l, fn, verdict, _d in rows:
        if verdict == "PINNED" and fn.startswith("via "):
            seam_pinned.setdefault(rel, set()).add(fn.removeprefix("via "))
    out = []
    for row in rows:
        rel, verdict, detail = row[0], row[3], row[4]
        if verdict == "PINNED":
            continue
        if verdict == "FORWARDER" and any(
            f"bound to {a}" in detail for a in seam_pinned.get(rel, ())
        ):
            continue
        out.append(row)
    return out


def _render(rows: list[tuple[str, int, str, str, str]]) -> str:
    return "\n  ".join(
        f"{rel}:{line} {fn} [{verdict}] {detail}" for rel, line, fn, verdict, detail in rows
    )


# ---------------------------------------------------------------------------
# The real tree
# ---------------------------------------------------------------------------
def test_the_analyser_finds_the_egress_door_at_all() -> None:
    """Guard the guard: an analyser that finds no call sites proves nothing.

    Without this, every assertion below would pass vacuously the day the door
    is renamed or the roots drift — the failure mode that makes a green scan
    indistinguishable from a blind one.
    """
    rows = _classify_purpose_sites(_REPO)
    assert rows, (
        "no egress-door purpose sites found — the analyser is blind, not the "
        "runtime clean. Check _DOOR_FUNCS and _RUNTIME_ROOTS."
    )
    assert any(fn in _DOOR_FUNCS for _r, _l, fn, _v, _d in rows), (
        f"no DIRECT door call found among {len(rows)} site(s) — only indirect "
        "ones, which means the direct-call path is not being examined"
    )


def test_every_runtime_purpose_is_pinned_to_a_module_literal() -> None:
    """THE TICKET. `purpose` must not be choosable by the model.

    Every runtime path into the door must carry a compiled-in literal, so the
    model's only influence is which door it enters. A failure here REJECTS any
    #977 design that adjudicates on `purpose`; it does not merely flag it.
    """
    rows = _classify_purpose_sites(_REPO)
    unsettled = _unsettled(rows)
    assert not unsettled, (
        "`purpose` is NOT provably pinned at every runtime egress-door site, so "
        "it cannot carry adjudication weight (#1586 / #977). Unsettled:\n  "
        + _render(unsettled)
        + "\n\nAll sites:\n  "
        + _render(rows)
    )


# ---------------------------------------------------------------------------
# THE OFF-TESTS — can this analyser fail?
# ---------------------------------------------------------------------------
_DOOR_SRC = '''import httpx


def fetch_external(url: str, *, purpose: str) -> None:
    pass


def fetch_external_binary(url: str, *, purpose: str) -> None:
    pass
'''

_BASELINE = '''import asyncio

from shared.security.guarded_fetch import fetch_external

_URL_FETCH_PURPOSE: str = "uc003-url-ingest"


def _default_url_fetch(url: str, purpose: str):
    return fetch_external(url, purpose=purpose)


class Coordinator:
    def __init__(self, url_fetch_fn=None) -> None:
        self._url_fetch_fn = url_fetch_fn or _default_url_fetch

    async def ingest(self, url: str):
        return await asyncio.to_thread(self._url_fetch_fn, url, _URL_FETCH_PURPOSE)
'''


def _synthetic_repo(root: Path, coordinator: str) -> Path:
    door = root / "shared" / "security"
    door.mkdir(parents=True)
    (door / "guarded_fetch.py").write_text(textwrap.dedent(_DOOR_SRC), encoding="utf-8")
    svc = root / "services" / "ui_gateway" / "src"
    svc.mkdir(parents=True)
    (svc / "ingest_coordinator.py").write_text(textwrap.dedent(coordinator), encoding="utf-8")
    return root


def test_the_synthetic_baseline_is_SETTLED(tmp_path: Path) -> None:
    """The control. Every mutant below differs from this by one condition.

    Without it, a mutant failing would prove only that the synthetic tree is
    unlike the real one.
    """
    rows = _classify_purpose_sites(_synthetic_repo(tmp_path, _BASELINE))
    assert rows, "the synthetic tree produced no sites — the fixture is wrong"
    assert not _unsettled(rows), _render(rows)


@pytest.mark.parametrize(
    ("label", "coordinator"),
    [
        (
            "purpose is a method PARAMETER at the seam — the ticket's hazard itself",
            _BASELINE.replace(
                "    async def ingest(self, url: str):\n"
                "        return await asyncio.to_thread(self._url_fetch_fn, url, _URL_FETCH_PURPOSE)\n",
                "    async def ingest(self, url: str, purpose: str):\n"
                "        return await asyncio.to_thread(self._url_fetch_fn, url, purpose)\n",
            ),
        ),
        (
            "purpose is BUILT with an f-string — not a literal even if every piece looks safe",
            _BASELINE.replace(
                "asyncio.to_thread(self._url_fetch_fn, url, _URL_FETCH_PURPOSE)",
                'asyncio.to_thread(self._url_fetch_fn, url, f"{_URL_FETCH_PURPOSE}-x")',
            ),
        ),
        (
            "the constant is REBOUND at module level — the second binding is what ships",
            _BASELINE.replace(
                '_URL_FETCH_PURPOSE: str = "uc003-url-ingest"\n',
                '_URL_FETCH_PURPOSE: str = "uc003-url-ingest"\n'
                '_URL_FETCH_PURPOSE = "anything-i-like"\n',
            ),
        ),
        (
            "the seam attribute is RENAMED so the matcher misses it — must fail CLOSED",
            _BASELINE.replace("_url_fetch_fn", "_door"),
        ),
        (
            "a direct call takes purpose from a dict subscript",
            '''from shared.security.guarded_fetch import fetch_external


def go(url: str, spec: dict):
    return fetch_external(url, purpose=spec["purpose"])
''',
        ),
    ],
)
def test_a_forgeable_purpose_is_CAUGHT(label: str, coordinator: str, tmp_path: Path) -> None:
    """Each mutant varies ONE condition from the baseline and must be caught.

    The renamed-seam case is the one that decides whether this is a lock or a
    decoration: an indirection the analyser does not understand must read as
    FORGEABLE. Guessing favourably there would defeat the entire check, because
    the whole point is to REJECT a design when the property cannot be shown.
    """
    rows = _classify_purpose_sites(_synthetic_repo(tmp_path, coordinator))
    assert _unsettled(rows), (
        f"the analyser accepted a forgeable purpose — {label}\n  " + _render(rows)
    )


# ---------------------------------------------------------------------------
# The three shapes the #1586 adversarial review defeated this lock with.
#
# All three made it fail OPEN — two of them emitted NO ROW AT ALL, which is
# worse than a finding, because the report then looks complete. They are kept
# as their own block, with a SECOND module, because that is the axis the
# original five mutants never varied: every one of them mutated the single
# coordinator, and both surviving excuses lived in the space between modules.
# ---------------------------------------------------------------------------

#: A second runtime consumer, of the shape the runbook's own out-of-scope list
#: anticipates (a summarizer / feed reader / agentic `summarize_url`). It names
#: its injected seam with the obvious name copied from `ingest_coordinator`.
#:
#: **The call site copies the seam to a LOCAL on purpose.** An earlier version of
#: this fixture called the seam directly, which produced its own FORGEABLE row —
#: so the test passed whether or not the per-module scoping was in place, i.e.
#: for the wrong reason. Measured: reverting the scoping left it green. Via a
#: local, the seam call is not recognised at all and the FORWARDER row is the
#: ONLY thing standing between a model-supplied purpose and the door — which is
#: exactly where the tree-wide excuse used to apply.
_SECOND_CONSUMER_REUSING_THE_SEAM_NAME = '''from shared.security.guarded_fetch import fetch_external


def _other_url_fetch(url: str, purpose: str):
    return fetch_external(url, purpose=purpose)


class Summarizer:
    def __init__(self, url_fetch_fn=None) -> None:
        self._url_fetch_fn = url_fetch_fn or _other_url_fetch

    def summarize(self, url: str, purpose: str):
        fn = self._url_fetch_fn
        return fn(url, purpose)
'''


def _synthetic_repo_two_modules(root: Path, second: str) -> Path:
    """The baseline coordinator PLUS a second runtime module."""
    repo = _synthetic_repo(root, _BASELINE)
    (repo / "services" / "ui_gateway" / "src" / "summarizer.py").write_text(
        textwrap.dedent(second), encoding="utf-8"
    )
    return repo


def test_an_ALIASED_door_import_is_still_seen(tmp_path: Path) -> None:
    """Review finding 1A: the door matched on the SPELLED name.

    ``from shared.security.guarded_fetch import fetch_external as _f`` followed
    by ``_f(url, purpose=purpose)`` reaches the door under a name the analyser
    had never heard of. It produced NO ROW — not a FORGEABLE one, none — so both
    shipped assertions passed while a model-supplied purpose went through.

    A hole that emits nothing is worse than one that emits a finding.
    """
    aliased = '''from shared.security.guarded_fetch import fetch_external as _f


def go(url: str, purpose: str):
    return _f(url, purpose=purpose)
'''
    rows = _classify_purpose_sites(_synthetic_repo(tmp_path, aliased))
    assert rows, (
        "the aliased door call produced NO ROW AT ALL — the analyser is blind to "
        "it, and a report with no rows reads as a clean bill of health"
    )
    assert _unsettled(rows), (
        "an aliased door import let a parameter-supplied purpose through\n  "
        + _render(rows)
    )


def test_a_SECOND_module_cannot_borrow_another_modules_pinned_seam(
    tmp_path: Path,
) -> None:
    """Review finding 1B: the FORWARDER excuse was keyed TREE-WIDE.

    A FORWARDER row is excused when the seam it names has a PINNED row. That
    lookup used to search every module, so a second consumer that named its seam
    ``_url_fetch_fn`` — the obvious name to copy — inherited
    ``ingest_coordinator``'s proof without having earned it, and could thread a
    model-supplied purpose straight through.

    A proof belongs to the module that carries it.
    """
    rows = _classify_purpose_sites(
        _synthetic_repo_two_modules(tmp_path, _SECOND_CONSUMER_REUSING_THE_SEAM_NAME)
    )
    unsettled = _unsettled(rows)
    assert unsettled, (
        "a second module inherited another module's pinned-seam proof\n  "
        + _render(rows)
    )
    assert any("summarizer.py" in row[0] for row in unsettled), (
        "something was flagged, but not the second consumer — this test is "
        "passing for the wrong reason\n  " + _render(unsettled)
    )


def test_the_BASELINE_still_settles_with_a_well_behaved_second_module(
    tmp_path: Path,
) -> None:
    """The control for the two tests above, and it is doing real work.

    Per-module scoping and alias resolution must not make the analyser reject
    everything — a lock that refuses correct code is an outage, and it would
    make the two tests above pass for free. This second consumer pins its own
    purpose in its own module and must SETTLE.
    """
    well_behaved = '''import asyncio

from shared.security.guarded_fetch import fetch_external

_OWN_PURPOSE: str = "uc003-summarize"


def _other_url_fetch(url: str, purpose: str):
    return fetch_external(url, purpose=purpose)


class Summarizer:
    def __init__(self, url_fetch_fn=None) -> None:
        self._url_fetch_fn = url_fetch_fn or _other_url_fetch

    async def summarize(self, url: str):
        return await asyncio.to_thread(self._url_fetch_fn, url, _OWN_PURPOSE)
'''
    rows = _classify_purpose_sites(_synthetic_repo_two_modules(tmp_path, well_behaved))
    assert rows, "the two-module fixture produced no sites — the fixture is wrong"
    assert not _unsettled(rows), (
        "a second module that pins its OWN purpose was rejected — the scoping is "
        "too strict and this is an outage, not a control\n  " + _render(rows)
    )
