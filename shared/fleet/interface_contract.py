"""Interface-contract v3 (#826) — derive the FULL callable contract a job oracle
DEMANDS of the code under test, deterministically, from its AST.

The B4n2 park class (failure-taxonomy-20260711): the 14B-authored oracle asserted
``check_answer('cat', 'cat') == 'correct'`` — a callable *and a return contract* the
spec never stated. The coder built a reasonable, DIFFERENT signature (``check_answer``
returning a bool, taking one argument), the assertion could never pass, and the
mismatch surfaced only as a 2am park. rec-1 (#790) / #822 close the MODULE + import-NAME
layer (does ``check_answer`` resolve and is it importable); nothing closed the
CALLABLE/SIGNATURE/return-shape layer (is it called with the arity the oracle uses, and
does the oracle demand a return the requirements never mentioned).

This module is that missing layer — one SSOT AST walk, three consumers:

  * ``oracle_qa`` (#821, AUTHORSHIP time): :meth:`InterfaceContract.string_return_literals`
    feeds the invented-RETURN-contract check — a magic return string the spec never names
    is the B4n2 class and drives single-focus regeneration.
  * ``context_pack`` (#822 target-build, GATE prep): :meth:`InterfaceContract.probe_signatures`
    enriches each import-probe target with the per-callable arity contract the post-merge
    probe enforces (extends #822's ``names`` seam without reworking it).
  * ``acceptance.compile_prompts`` (rec-1 v3, TASK CONTEXT): :meth:`InterfaceContract.render_lines`
    shows the coder the full SIGNATURES the acceptance file calls, not just module names.

DELIBERATELY zero first-party imports (pure ``ast`` + stdlib): it is imported by
``oracle_qa`` / ``context_pack`` / ``acceptance`` with no cycle, and its arity dicts ride
the import-probe targets JSON into the stdlib-only ``import_probe`` subprocess (which
cannot import anything first-party). Deterministic: same source ⇒ same contract.

Scope discipline (precision-first — a false contract entry wrongly convicts valid work,
the very failure this prevents): the callable derivation covers the two dominant,
unambiguous shapes — ``from module import name`` then ``name(...)``, and ``import module``
then ``module.func(...)``. A deep ``import a.b`` / ``a.b.c.func()`` chain, a locally
shadowed name, or a call whose target is not import-bound is NOT recorded — it falls back
to #822's module-resolution-only probe. Return-shape derivation records comparisons on a
first-party call result; the invented-contract check consumes only the sharp STRING-equality
case (a magic status string), never numbers/booleans (legitimately spec-derivable, and a
false flag there is worse than the miss)."""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from typing import Callable, Optional

#: Non-first-party roots the derivation never treats as the code under test: the full
#: stdlib plus the test-runner frameworks (the oracle's own scaffolding). Mirrors the
#: first-party predicate ``context_pack`` / ``oracle_qa`` apply, so a callable recorded
#: here always corresponds to a real import-probe target.
_TEST_FRAMEWORK_ROOTS: frozenset[str] = frozenset({"pytest", "hypothesis", "__future__"})

#: Cap on rendered signature lines surfaced to the coder (rec-1 v3) — a runaway oracle
#: needs its contract summarised, not a wall of text in the prompt.
_RENDER_MAX = 16
#: Per-rendered-line character cap (defensive; a signature line is short by construction).
_RENDER_LINE_MAX = 160


def _default_is_first_party(top: str) -> bool:
    """A module's TOP package is first-party (the code under test) iff it is neither
    stdlib nor a test-runner framework. Matches ``context_pack._first_party``."""
    if not top:
        return False
    stdlib = getattr(sys, "stdlib_module_names", frozenset())
    return top not in stdlib and top not in _TEST_FRAMEWORK_ROOTS


# ---------------------------------------------------------------------------
# Contract element types (frozen — a contract is a value, deterministic + hashable)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CallSig:
    """ONE observed call to a first-party callable in the oracle.

    ``module`` is the first-party module the callable resolves from (``flashcards``);
    ``name`` is the export the coder must provide (``check_answer``). The arity fields
    record what the oracle's call site DEMANDS: ``positional`` bare positional args,
    ``keywords`` the keyword names, and the star flags mark an under-determined call
    (``f(*xs)`` / ``f(**kw)``) whose positional/keyword surface is a lower bound only."""

    module: str
    name: str
    positional: int
    keywords: tuple[str, ...]
    starargs: bool
    starkwargs: bool


@dataclass(frozen=True)
class ReturnShape:
    """An asserted SHAPE of a first-party callable's RETURN value.

    ``kind`` ∈ {``eq``, ``compare``, ``isinstance``, ``len``, ``subscript``, ``attr``,
    ``truthy``}. For ``eq`` (the B4n2-critical case) ``literal_kind`` ∈ {``str``, ``num``,
    ``bool``, ``none``, ``other``} and ``literal`` is the compared value's repr — the
    invented-return check consumes only ``kind == "eq" and literal_kind == "str"``."""

    module: str
    name: str
    kind: str
    literal_kind: str = ""
    literal: str = ""


@dataclass(frozen=True)
class InterfaceContract:
    """The full interface a job oracle demands of the code under test — every first-party
    callable it invokes (with arities) and every return shape it asserts. Empty when the
    source does not parse or invokes nothing first-party (fail-soft — the #822 module
    probe still runs; there is simply no callable/return layer to add)."""

    calls: tuple[CallSig, ...] = ()
    returns: tuple[ReturnShape, ...] = ()

    def callable_names(self) -> set[str]:
        """The set of first-party callable export names the oracle invokes."""
        return {c.name for c in self.calls}

    def probe_signatures(self) -> dict[str, list[dict[str, object]]]:
        """The per-MODULE arity contract for the gate probe (#822 seam extension),
        keyed by module → a list of ``{name, min_positional, max_positional, keywords,
        starargs, starkwargs}`` arity dicts (JSON-safe, deterministic order).

        Multiple call sites of one callable are MERGED: ``min/max_positional`` span the
        observed positional counts (so the probe verifies the built signature can bind
        BOTH the smallest and the largest call), ``keywords`` unions the keyword names,
        and the star flags OR together (an under-determined call relaxes the positional
        upper bound at probe time — precision-first)."""
        merged: dict[tuple[str, str], dict[str, object]] = {}
        order: list[tuple[str, str]] = []
        for c in self.calls:
            key = (c.module, c.name)
            entry = merged.get(key)
            if entry is None:
                order.append(key)
                merged[key] = {
                    "name": c.name,
                    "min_positional": c.positional,
                    "max_positional": c.positional,
                    "keywords": list(c.keywords),
                    "starargs": c.starargs,
                    "starkwargs": c.starkwargs,
                }
                continue
            entry["min_positional"] = min(int(entry["min_positional"]), c.positional)
            entry["max_positional"] = max(int(entry["max_positional"]), c.positional)
            kws = list(entry["keywords"])  # type: ignore[arg-type]
            for k in c.keywords:
                if k not in kws:
                    kws.append(k)
            entry["keywords"] = kws
            entry["starargs"] = bool(entry["starargs"]) or c.starargs
            entry["starkwargs"] = bool(entry["starkwargs"]) or c.starkwargs
        out: dict[str, list[dict[str, object]]] = {}
        for module, name in order:
            out.setdefault(module, []).append(merged[(module, name)])
        return out

    def string_return_literals(self) -> list[tuple[str, str]]:
        """The ``(callable_name, string_literal)`` pairs the oracle asserts a first-party
        call result equals (``check_answer(...) == 'correct'`` → ``("check_answer",
        "correct")``). The SHARP B4n2 signal: a magic status string the oracle demands.
        De-duplicated, order-preserving; numbers/booleans/None are excluded upstream."""
        out: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for r in self.returns:
            if r.kind == "eq" and r.literal_kind == "str":
                pair = (r.name, r.literal)
                if pair not in seen:
                    seen.add(pair)
                    out.append(pair)
        return out

    def render_lines(self, *, cap: int = _RENDER_MAX) -> list[str]:
        """Human-readable SIGNATURE lines for the coder prompt (rec-1 v3) — e.g.
        ``check_answer(2 positional args)``, ``total()``, ``greet(1 positional arg,
        keyword: greeting)``. One line per distinct callable, deterministic, capped."""
        lines: list[str] = []
        for name, spec in self._render_order():
            parts: list[str] = []
            maxp = int(spec["max_positional"])
            starargs = bool(spec["starargs"])
            if starargs:
                parts.append(f"{maxp}+ positional args")
            elif maxp == 1:
                parts.append("1 positional arg")
            elif maxp > 1:
                parts.append(f"{maxp} positional args")
            for k in spec["keywords"]:  # type: ignore[union-attr]
                parts.append(f"keyword: {k}")
            if bool(spec["starkwargs"]):
                parts.append("keyword: **")
            line = f"{name}({', '.join(parts)})"
            lines.append(line[:_RENDER_LINE_MAX])
            if len(lines) >= cap:
                break
        return lines

    def _render_order(self) -> list[tuple[str, dict[str, object]]]:
        """(name, merged-arity-spec) in first-observed order across all modules."""
        out: list[tuple[str, dict[str, object]]] = []
        for specs in self.probe_signatures().values():
            for spec in specs:
                out.append((str(spec["name"]), spec))
        return out


# ---------------------------------------------------------------------------
# Derivation (pure AST — deterministic, no model, no subprocess)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Binding:
    """How a bound NAME in the oracle maps to a first-party (module, export). ``kind`` is
    ``from`` (``from m import f`` / ``... as g`` — the name IS the callable) or ``mod``
    (``import m`` / ``import m as x`` — the name is a MODULE whose attributes are callables)."""

    kind: str      # "from" | "mod"
    module: str    # the resolvable first-party module
    export: str    # the export name for a "from" binding; "" for a "mod" binding


def _binding_map(tree: ast.AST, is_first_party: Callable[[str], bool]) -> dict[str, _Binding]:
    """Map every bound name that refers to a first-party symbol → its :class:`_Binding`.

    ``from m import f``            → ``f`` : from/m/f
    ``from m import f as g``       → ``g`` : from/m/f
    ``import m`` / ``import m as x`` → the bound name : mod/m/""
    A relative import (``from . import x``) lives inside ``tests/`` and is not a public
    module → skipped (never a contract callable). ``import a.b`` binds only the root
    ``a`` as a module (the deep ``a.b.f()`` chain is out of scope — precision-first)."""
    out: dict[str, _Binding] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:  # relative — inside tests/, not a public module
                continue
            module = node.module or ""
            if not module or not is_first_party(module.split(".", 1)[0]):
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                bound = alias.asname or alias.name
                out[bound] = _Binding("from", module, alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".", 1)[0]
                if not is_first_party(top):
                    continue
                if alias.asname:
                    out[alias.asname] = _Binding("mod", alias.name, "")
                else:
                    # `import m` binds `m`; `import a.b` binds only the root `a` (module
                    # `a`) — the deep attribute chain is not derived (scope discipline).
                    out[top] = _Binding("mod", top, "")
    return out


def _root_name(node: ast.AST) -> str:
    """The root identifier of a Name or an Attribute chain (``a.b.c`` → ``a``)."""
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else ""


def _resolve_call_target(func: ast.AST, bindings: dict[str, _Binding]) -> Optional[tuple[str, str]]:
    """Resolve a call's ``func`` to a (module, export) first-party callable, or ``None``.

    ``name(...)`` where ``name`` is a ``from`` binding    → (module, export).
    ``mod.attr(...)`` where ``mod`` is a ``mod`` binding  → (module, attr).
    Anything else (a deep chain, a non-bound name, a method on a local) is not a
    first-party contract callable → ``None`` (falls back to #822's module probe)."""
    if isinstance(func, ast.Name):
        b = bindings.get(func.id)
        if b is not None and b.kind == "from":
            return (b.module, b.export)
        return None
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        b = bindings.get(func.value.id)
        if b is not None and b.kind == "mod":
            return (b.module, func.attr)
        return None
    return None


def _call_arity(node: ast.Call) -> tuple[int, tuple[str, ...], bool, bool]:
    """(positional_count, keyword_names, starargs, starkwargs) at a call site.

    ``ast.Starred`` in ``args`` is ``*xs`` (starargs); a keyword with ``arg is None`` is
    ``**kw`` (starkwargs). Positional counts only the bare positional args; the star
    forms make the surface a lower bound (recorded, honoured at probe time)."""
    positional = sum(1 for a in node.args if not isinstance(a, ast.Starred))
    starargs = any(isinstance(a, ast.Starred) for a in node.args)
    keywords = tuple(kw.arg for kw in node.keywords if kw.arg)
    starkwargs = any(kw.arg is None for kw in node.keywords)
    return (positional, keywords, starargs, starkwargs)


def _literal_kind(node: ast.AST) -> tuple[str, str]:
    """Classify a comparison RHS/LHS constant → (literal_kind, literal_repr). Only a
    genuine ``ast.Constant`` yields a kind; a name/expression is ``("", "")``."""
    if not isinstance(node, ast.Constant):
        return ("", "")
    value = node.value
    if isinstance(value, str):
        return ("str", value)
    if isinstance(value, bool):
        return ("bool", repr(value))
    if isinstance(value, (int, float)):
        return ("num", repr(value))
    if value is None:
        return ("none", "None")
    return ("other", repr(value))


def _return_shapes(
    tree: ast.AST, bindings: dict[str, _Binding]
) -> list[ReturnShape]:
    """Every asserted return SHAPE of a first-party call result. Walks ``assert`` tests
    (and their boolean sub-expressions) for the demanded shape of ``<first-party call>``:
    an equality/comparison against a constant, an ``isinstance``/``len`` of it, a
    subscript/attribute on it, or a bare truthiness assertion."""
    shapes: list[ReturnShape] = []

    def _target(call: ast.Call) -> Optional[tuple[str, str]]:
        return _resolve_call_target(call.func, bindings)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assert):
            continue
        for sub in ast.walk(node.test):
            if isinstance(sub, ast.Compare) and len(sub.ops) == 1:
                left, right = sub.left, sub.comparators[0]
                op = sub.ops[0]
                for call_side, other in ((left, right), (right, left)):
                    if isinstance(call_side, ast.Call):
                        tgt = _target(call_side)
                        if tgt is None:
                            continue
                        if isinstance(op, ast.Eq):
                            lk, lit = _literal_kind(other)
                            shapes.append(ReturnShape(tgt[0], tgt[1], "eq", lk, lit))
                        else:
                            shapes.append(ReturnShape(tgt[0], tgt[1], "compare"))
            elif isinstance(sub, ast.Call):
                # isinstance(<call>, T) / len(<call>) shapes
                fn = sub.func
                fname = fn.id if isinstance(fn, ast.Name) else ""
                if fname in ("isinstance", "len") and sub.args:
                    first = sub.args[0]
                    if isinstance(first, ast.Call):
                        tgt = _target(first)
                        if tgt is not None:
                            shapes.append(ReturnShape(tgt[0], tgt[1],
                                                      "isinstance" if fname == "isinstance" else "len"))
            elif isinstance(sub, ast.Subscript) and isinstance(sub.value, ast.Call):
                tgt = _target(sub.value)
                if tgt is not None:
                    shapes.append(ReturnShape(tgt[0], tgt[1], "subscript"))
            elif isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Call):
                tgt = _target(sub.value)
                if tgt is not None:
                    shapes.append(ReturnShape(tgt[0], tgt[1], "attr"))
    return shapes


def derive_interface_contract(
    code: str, *, is_first_party: "Callable[[str], bool] | None" = None
) -> InterfaceContract:
    """Derive the :class:`InterfaceContract` a python job oracle demands, from its AST.

    Deterministic + fail-soft: unparseable source ⇒ an empty contract (the #822 module
    probe still runs; there is simply no callable/return layer). ``is_first_party``
    overrides the default (stdlib + test-framework) predicate so a caller can align the
    first-party policy with its own import filter."""
    if not code:
        return InterfaceContract()
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return InterfaceContract()
    fp = is_first_party or _default_is_first_party
    bindings = _binding_map(tree, fp)
    if not bindings:
        return InterfaceContract()
    calls: list[CallSig] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        tgt = _resolve_call_target(node.func, bindings)
        if tgt is None:
            continue
        positional, keywords, starargs, starkwargs = _call_arity(node)
        calls.append(CallSig(tgt[0], tgt[1], positional, keywords, starargs, starkwargs))
    returns = _return_shapes(tree, bindings)
    return InterfaceContract(calls=tuple(calls), returns=tuple(returns))
