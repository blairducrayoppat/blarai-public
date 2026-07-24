"""M2 W3 (#740) — deterministic context packs for dependency-ordered dispatch tasks.

A task whose ``depends_on`` is non-empty gets a CONTEXT PACK appended to its prompt at
enqueue: what its dependencies declared they would build (the ruler-validated plan
CONTRACT) plus what they *actually* built (the as-built delta — file list from the
dependency's merge, public signatures structurally extracted from the changed sources),
ending with the one instruction that stops the 30B re-discovering or re-implementing its
foundations. The whole pack is hard-capped (~1200 chars, plan §4.4) because an
over-stuffed prompt degrades a small coder — a pack is an interface card, not
documentation.

SECURITY (plan §10 S2 — the one genuinely novel channel M2 creates): a pack copies
content *derived from task A's built output* into task B's *prompt* — worm-shaped if
done carelessly. The controls here are STRUCTURAL, not prompt rules:

  * The only human-language text a pack may carry is the CONTRACT (already
    ruler-validated at plan time: control-stripped, length-capped — the S2 rule that
    plan-sourced contract text is the sole prose channel).
  * The as-built side is paths + signatures ONLY — never comments, docstrings, or file
    bodies. Python signatures are RECONSTRUCTED from the ``ast`` (never source slices):
    parameter NAMES only, **defaults are never rendered** (a default value is an
    arbitrary expression that can carry an instruction-string payload), and an
    annotation is included only when its rendering carries no quote/backtick/newline.
    mjs/js exports come from export-LINE regexes with the same quote-gate on captured
    parameter lists — any quoted content in a captured group replaces the group with
    ``…``. So no string-literal content from a built file can enter a prompt, by
    construction (the N6 poisoned-dependency rig).
  * Every extracted token is control-char-stripped and length-capped.

Pure and deterministic: no model calls, no subprocess, no file I/O — the git reads that
feed ``files``/``signatures`` live behind the injected ``SwapOps.dep_delta`` seam
(``swap_ops.real_dep_delta``); this module only ever transforms strings. Same input ⇒
byte-identical pack (regression-locked).
"""

from __future__ import annotations

import ast
import re

#: Hard cap on a whole pack (plan §4.4). The instruction line always survives the cap.
CONTEXT_PACK_MAX_CHARS = 1200

#: The load-bearing instruction (plan §4.4 item 3) — ALWAYS the pack's last line, never
#: truncated away (a pack that lists modules without this line invites a rebuild).
PACK_INSTRUCTION = (
    "These modules exist and are tested - import and use them; "
    "do NOT reimplement or modify them."
)

PACK_HEADER = "--- Context: what this task's dependencies already built ---"

#: Characters that mark a captured group as carrying string-literal content — the S2
#: quote-gate. A parameter list / annotation containing any of these is dropped or
#: replaced with an ellipsis, so quoted payloads in built files can never ride a pack.
_QUOTE_CHARS = ('"', "'", "`")

#: Control characters (incl. newlines) stripped from every extracted token.
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")

#: Per-token length cap (a signature is an interface card entry, not a paragraph).
_TOKEN_MAX = 160
#: Annotation rendering cap — anything longer is noise for the next coder.
_ANN_MAX = 40

# ---------------------------------------------------------------------------
# Token hygiene
# ---------------------------------------------------------------------------


def _clean_token(text: str, max_len: int = _TOKEN_MAX) -> str:
    """Control-strip + whitespace-collapse + length-cap one extracted token."""
    cleaned = " ".join(_CTRL_RE.sub(" ", str(text)).split())
    return cleaned[:max_len]


def _quote_free(text: str) -> bool:
    return not any(q in text for q in _QUOTE_CHARS)


# ---------------------------------------------------------------------------
# Python signature extraction (ast — never source slices)
# ---------------------------------------------------------------------------


def _py_annotation(node: "ast.expr | None") -> str:
    """Render an annotation IFF it is short and quote-free; else ``''`` (omitted).

    The quote-gate is the S2 control: ``Literal["..."]`` or any annotation carrying a
    string constant is dropped rather than rendered — an annotation must never be a
    prose channel out of a built file."""
    if node is None:
        return ""
    try:
        rendered = ast.unparse(node)
    except Exception:  # noqa: BLE001 — an unrenderable annotation is simply omitted
        return ""
    rendered = " ".join(rendered.split())
    if not rendered or len(rendered) > _ANN_MAX or not _quote_free(rendered):
        return ""
    if "\n" in rendered:
        return ""
    return rendered


def _py_arg(arg: ast.arg) -> str:
    ann = _py_annotation(arg.annotation)
    return f"{arg.arg}: {ann}" if ann else arg.arg


def _py_signature(node: "ast.FunctionDef | ast.AsyncFunctionDef", prefix: str = "") -> str:
    """Reconstruct ``def name(params) -> ret`` from the AST. Parameter NAMES only —
    defaults are NEVER rendered (a default is an arbitrary expression: the classic
    instruction-payload carrier in a poisoned file)."""
    a = node.args
    parts: list[str] = []
    for arg in list(getattr(a, "posonlyargs", [])) + list(a.args):
        parts.append(_py_arg(arg))
    if a.vararg is not None:
        parts.append("*" + a.vararg.arg)
    elif a.kwonlyargs:
        parts.append("*")
    for arg in a.kwonlyargs:
        parts.append(_py_arg(arg))
    if a.kwarg is not None:
        parts.append("**" + a.kwarg.arg)
    ret = _py_annotation(node.returns)
    suffix = f" -> {ret}" if ret else ""
    lead = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    return _clean_token(f"{lead} {prefix}{node.name}({', '.join(parts)}){suffix}")


def extract_python_signatures(source: str) -> list[str]:
    """Public interface signatures of a Python module — module-level ``def``/``class``
    plus public class methods, reconstructed from the AST.

    STRUCTURAL ONLY: no docstring, comment, string constant, or default value can
    appear in the output (the N6 guarantee). Unparseable source ⇒ ``[]`` (a dependency
    that doesn't parse contributes nothing — fail-soft, the contract still carries)."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []
    out: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                out.append(_py_signature(node))
        elif isinstance(node, ast.ClassDef):
            if node.name.startswith("_"):
                continue
            out.append(_clean_token(f"class {node.name}"))
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
                    not sub.name.startswith("_") or sub.name == "__init__"
                ):
                    out.append(_py_signature(sub, prefix=f"{node.name}."))
    return out


# ---------------------------------------------------------------------------
# mjs / js export extraction (export-LINE regexes — plan §4.4: "no model calls")
# ---------------------------------------------------------------------------

_MJS_FUNC_RE = re.compile(
    r"^\s*export\s+(?:default\s+)?(async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)\s*\(([^)]*)\)"
)
_MJS_CONST_RE = re.compile(
    r"^\s*export\s+(?:const|let|var)\s+([A-Za-z_$][\w$]*)"
)
_MJS_CLASS_RE = re.compile(
    r"^\s*export\s+(?:default\s+)?class\s+([A-Za-z_$][\w$]*)"
)
_MJS_NAMES_RE = re.compile(r"^\s*export\s*\{([^}]*)\}")


def _mjs_params(raw: str) -> str:
    """The captured parameter group, quote-gated: ANY quoted content (a default like
    ``x = "payload"``) replaces the whole group with ``…`` — names are useful, quoted
    payloads are the S2 channel we refuse."""
    cleaned = _clean_token(raw, max_len=80)
    if not cleaned:
        return ""
    if not _quote_free(cleaned):
        return "…"
    return cleaned


def extract_mjs_exports(source: str) -> list[str]:
    """Public exports of an mjs/js module from its ``export`` LINES only (never bodies,
    comments, or string content — the same N6 guarantee as the Python side)."""
    out: list[str] = []
    seen: set[str] = set()

    def add(sig: str) -> None:
        if sig and sig not in seen:
            seen.add(sig)
            out.append(sig)

    for line in (source or "").splitlines():
        m = _MJS_FUNC_RE.match(line)
        if m:
            is_async, name, params = m.group(1), m.group(2), m.group(3)
            lead = "async function" if is_async else "function"
            add(_clean_token(f"{lead} {name}({_mjs_params(params)})"))
            continue
        m = _MJS_CONST_RE.match(line)
        if m:
            add(_clean_token(f"const {m.group(1)}"))
            continue
        m = _MJS_CLASS_RE.match(line)
        if m:
            add(_clean_token(f"class {m.group(1)}"))
            continue
        m = _MJS_NAMES_RE.match(line)
        if m:
            names = _clean_token(m.group(1), max_len=120)
            if names and _quote_free(names):
                add(f"exports {{ {names} }}")
    return out


def extract_signatures(rel_path: str, source: str) -> list[str]:
    """Dispatch by extension: ``.py`` → ast; ``.mjs``/``.js`` → export-line regex;
    anything else → ``[]`` (only ecosystems with a structural extractor contribute)."""
    low = str(rel_path).lower()
    if low.endswith(".py"):
        return extract_python_signatures(source)
    if low.endswith((".mjs", ".js")):
        return extract_mjs_exports(source)
    return []


# ---------------------------------------------------------------------------
# Job-oracle import contract (#790 rec-1) — the FIRST-PARTY module interface the
# final integrated tree must provide, surfaced so the coder builds toward it
# ---------------------------------------------------------------------------
#
# The B4/B6/B7 park class (night-20260709): the coder MERGED working code, then the
# wave-final job oracle failed at `from cli import main` / `from inventory_manager
# import InventoryManager` / `import … from '../src/slugify-phrase.js'` — a module the
# coder placed at a different path than the oracle imports. The seeded oracle is
# guard-hidden during node gates, so "unit-green ≠ job-green" surfaced only at the end.
# Surfacing the oracle's import LINES into every task's context turns that silent
# layout-divergence into an explicit contract the coder codes toward.

#: Per-contract-line length cap (an import line, not a paragraph).
_IMPORT_LINE_MAX = 120
#: Max import lines surfaced — an oracle imports a handful of first-party modules;
#: more than this is noise that would crowd a small coder's prompt.
_IMPORT_CONTRACT_MAX = 12

#: Test-framework top-level modules an oracle imports to RUN the tests, never the
#: coder's own layout it grades — dropped so the contract shows only first-party names.
_ORACLE_IMPORT_SKIP: frozenset[str] = frozenset(
    {"pytest", "_pytest", "hypothesis", "unittest", "nose", "nose2", "mock"}
)


def _py_import_contract(source: str) -> list[str]:
    """First-party import STATEMENTS a Python oracle imports against — ``import a.b`` /
    ``from a import x, y`` / relative ``from .a import z`` — with stdlib and the test
    framework dropped. Reconstructed from the AST (module names + dotted paths only),
    so no string/comment/default content can ride (the N6 guarantee). Imports nested
    inside test functions ARE included: an oracle routinely imports the module under
    test inside its test body. Unparseable source ⇒ ``[]`` (fail-soft)."""
    import sys

    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []
    stdlib = getattr(sys, "stdlib_module_names", frozenset())

    def _first_party(top: str) -> bool:
        return bool(top) and top not in stdlib and top not in _ORACLE_IMPORT_SKIP

    out: list[str] = []
    seen: set[str] = set()

    def _add(line: str) -> None:
        cleaned = _clean_token(line, max_len=_IMPORT_LINE_MAX)
        if cleaned and _quote_free(cleaned) and cleaned not in seen:
            seen.add(cleaned)
            out.append(cleaned)

    # ast.walk is deterministic (module-level children first, then nested), so the
    # module's own imports lead and the output is byte-stable for a given source.
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _first_party(alias.name.split(".")[0]):
                    _add(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            # A relative import (level > 0) is ALWAYS first-party; an absolute one only
            # when its top package is neither stdlib nor a known test framework.
            if node.level == 0 and not _first_party(module.split(".")[0]):
                continue
            names = [a.name for a in node.names if a.name]
            if not names:
                continue
            target = "." * node.level + module
            _add(f"from {target} import {', '.join(names)}")
    return out[:_IMPORT_CONTRACT_MAX]


def _first_party_specifier(spec: str) -> bool:
    """An ESM/CJS import specifier is FIRST-PARTY (a file the coder must place) when it
    is a relative/absolute PATH — never a bare package (``express``) or a ``node:``
    builtin. A quote/backtick inside a specifier (never in a real path) refuses it."""
    s = str(spec).strip()
    return bool(s) and (s.startswith("./") or s.startswith("../") or s.startswith("/")) and (
        _quote_free(s)
    )


_MJS_IMPORT_FROM_RE = re.compile(
    r"""^\s*import\s+(?P<what>.+?)\s+from\s+(?P<q>['"])(?P<spec>[^'"]+)(?P=q)"""
)
_MJS_SIDE_EFFECT_IMPORT_RE = re.compile(
    r"""^\s*import\s+(?P<q>['"])(?P<spec>[^'"]+)(?P=q)"""
)
_MJS_REQUIRE_RE = re.compile(
    r"""(?:const|let|var)\s+(?P<what>[^=;]+?)\s*=\s*require\(\s*(?P<q>['"])(?P<spec>[^'"]+)(?P=q)\s*\)"""
)


def _mjs_import_contract(source: str) -> list[str]:
    """First-party import STATEMENTS an mjs/js oracle imports against, from its import
    LINES only (never bodies/comments). A specifier is kept only when it is a local
    path (:func:`_first_party_specifier`) — bare packages + ``node:`` builtins (the test
    framework) are dropped. The specifier is re-emitted single-quoted BY US; a binding
    (``what``) carrying a quote payload is dropped, and a backtick anywhere refuses the
    line — so no string content from the oracle can restructure the prompt."""
    out: list[str] = []
    seen: set[str] = set()

    def _add(line: str) -> None:
        cleaned = _clean_token(line, max_len=_IMPORT_LINE_MAX)
        if cleaned and "`" not in cleaned and cleaned not in seen:
            seen.add(cleaned)
            out.append(cleaned)

    def _binding(raw: str) -> str:
        what = " ".join(_clean_token(raw, max_len=80).split())
        return what if _quote_free(what) else ""

    for raw in (source or "").splitlines():
        m = _MJS_IMPORT_FROM_RE.match(raw)
        if m and _first_party_specifier(m.group("spec")):
            what, spec = _binding(m.group("what")), m.group("spec").strip()
            _add(f"import {what} from '{spec}'" if what else f"import '{spec}'")
            continue
        m = _MJS_SIDE_EFFECT_IMPORT_RE.match(raw)
        if m and _first_party_specifier(m.group("spec")):
            _add(f"import '{m.group('spec').strip()}'")
            continue
        m = _MJS_REQUIRE_RE.search(raw)
        if m and _first_party_specifier(m.group("spec")):
            what, spec = _binding(m.group("what")), m.group("spec").strip()
            _add(f"const {what} = require('{spec}')" if what else f"require('{spec}')")
    return out[:_IMPORT_CONTRACT_MAX]


def extract_import_contract(rel_path: str, source: str) -> list[str]:
    """The module-import surface a job-acceptance oracle imports against — the exact
    module paths + public names the FINAL integrated tree must provide, surfaced into
    every plan-graph task's context so the coder builds toward the layout the oracle
    grades instead of a divergent one it is never shown (#790 rec-1).

    Dispatch by extension (``.py`` → ast; ``.mjs``/``.js`` → import-line regex; other
    → ``[]``). STRUCTURAL + deterministic: import STATEMENTS only, never bodies or
    string content; stdlib + the test framework dropped so only the coder's own module
    contract shows; each line control-stripped, length-capped, de-duplicated. Same
    input ⇒ byte-identical output (regression-locked)."""
    low = str(rel_path).lower()
    if low.endswith(".py"):
        return _py_import_contract(source or "")
    if low.endswith((".mjs", ".js")):
        return _mjs_import_contract(source or "")
    return []


#: The leading top-level identifier of a PYTHON import line ("from X…" / "import X…").
#: A node contract line never matches: its module position is a quoted specifier (and
#: the whole line is refused by the quote check below before this regex runs).
_CANONICAL_PACKAGE_RE = re.compile(r"^(?:from|import)\s+([A-Za-z_][A-Za-z0-9_]*)\b")


def canonical_package_from_contract(contract: "list[str] | None") -> str:
    """The ONE top-level python package/module root every job-oracle contract line
    imports from, or ``""`` when no single root exists (#790 sub-task 5).

    The scaffold seeder (agentic-setup ``Copy-ScaffoldInto``) historically seeded the
    GENERIC ``app/`` skeleton into every fresh python target, so a plan-graph job whose
    oracle imports ``flashcard_app`` grew TWO top-level trees — the stale ``app/`` twin
    (placeholder ``core.py`` + a ``tests/test_core.py`` importing ``app.core``) beside
    the real package — the B4 duplicate-scaffold defect (night 20260716-001549-bd).
    This derivation rides each fleet task dict (``canonical_package``) so the seeder
    names the skeleton's package after the oracle's contract and ONE canonical tree is
    seeded and extended.

    Deterministic + conservative (a miss seeds the legacy skeleton — never worse):
    python import lines only (a quoted specifier marks a node line, skipped; a relative
    import has no leading identifier after the keyword, skipped), and anything but
    EXACTLY ONE distinct root yields ``""`` — two roots cannot both be the canonical
    package, so the seeder must not guess between them."""
    roots: set[str] = set()
    for line in contract or []:
        text = str(line or "").strip()
        if not text or not _quote_free(text):
            continue
        match = _CANONICAL_PACKAGE_RE.match(text)
        if match:
            roots.add(match.group(1))
    if len(roots) != 1:
        return ""
    return next(iter(roots))


# ---------------------------------------------------------------------------
# Job-oracle import PROBE targets (#822 H3/H3b/H4) — the STRUCTURED sibling of
# extract_import_contract: the same first-party import surface, but as machine
# targets a resolve-probe can import + getattr, not the human contract STRINGS
# ---------------------------------------------------------------------------
#
# extract_import_contract SURFACES the oracle's imports into the coder's prompt as
# advisory text; #822 moves that contract from advisory to ENFORCED — a post-merge
# probe that actually RESOLVES each module from the repo root exactly as the oracle
# will, and getattrs each named export (closing the stub-module evasion: a module
# that imports but whose export is absent). The probe needs the imports STRUCTURED
# (module + names), not rendered lines, so this sibling walks the SAME AST/regex and
# emits targets. It is byte-decoupled from extract_import_contract (that function's
# string output is regression-locked green-path bytes and must not move), but the two
# read the same source with the same first-party/skip rules, so a probe target exists
# for every contract line that names a resolvable module.

#: A single import the probe must resolve on the merged tree.
#:   kind    "py" | "node"
#:   module  (py) the dotted module the oracle imports (``cli`` / ``a.b``);
#:           "" for a node target (node keys on ``spec``).
#:   spec    (node) the exact ESM/CJS specifier (``../src/storage.mjs``); "" for py.
#:   level   (py) the relative-import level (0 = absolute; >0 = a package-relative
#:           import the standalone probe cannot resolve without a package context —
#:           recorded but not probed, see real_run_import_probe).
#:   names   the export NAMES the oracle binds from the module (``["addExpense"]``);
#:           [] when the oracle imports the module itself (``import x`` / ``import
#:           '..'`` / ``import * as ns``) — then only resolution is checked.
#:   raw     the human contract line (for naming the exact unresolved entry in the
#:           coder's fix-cycle prompt — the signal B6n2's coder lacked at 23/24).


def _py_probe_targets(source: str) -> list[dict]:
    """Structured first-party import targets from a Python oracle (mirror of
    :func:`_py_import_contract`, same first-party/skip filtering)."""
    import sys

    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []
    stdlib = getattr(sys, "stdlib_module_names", frozenset())

    def _first_party(top: str) -> bool:
        return bool(top) and top not in stdlib and top not in _ORACLE_IMPORT_SKIP

    out: list[dict] = []
    seen: set[str] = set()

    def _add(target: dict) -> None:
        raw = _clean_token(target["raw"], max_len=_IMPORT_LINE_MAX)
        if not raw or not _quote_free(raw) or raw in seen:
            return
        seen.add(raw)
        target["raw"] = raw
        out.append(target)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _first_party(alias.name.split(".")[0]):
                    _add({"kind": "py", "module": alias.name, "spec": "",
                          "level": 0, "names": [], "raw": f"import {alias.name}"})
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level == 0 and not _first_party(module.split(".")[0]):
                continue
            names = [a.name for a in node.names if a.name]
            if not names:
                continue
            target = "." * node.level + module
            _add({"kind": "py", "module": module, "spec": "", "level": node.level,
                  "names": list(names),
                  "raw": f"from {target} import {', '.join(names)}"})
    _attach_python_signatures(out, source, _first_party)
    return out[:_IMPORT_CONTRACT_MAX]


def _attach_python_signatures(
    targets: list[dict], source: str, is_first_party
) -> None:
    """#826 — attach the per-callable ARITY contract to each python probe target (the
    SIGNATURE layer the gate probe enforces beyond #822's name-resolution). Derives the
    interface contract (:mod:`shared.fleet.interface_contract`) with the SAME first-party
    predicate as the target walk, so every signature maps to a target that exists, and
    adds an OPTIONAL ``signatures`` key (absent when the module has no derived call —
    byte-identical to the pre-#826 target for a pure ``import``-only oracle)."""
    try:
        from shared.fleet.interface_contract import derive_interface_contract

        sig_by_module = derive_interface_contract(
            source, is_first_party=is_first_party
        ).probe_signatures()
    except Exception:  # noqa: BLE001 — a derivation miss must never break target-building
        return
    for tgt in targets:
        sigs = sig_by_module.get(str(tgt.get("module", "")))
        if sigs:
            tgt["signatures"] = sigs


def _node_import_names(what: str) -> list[str]:
    """The EXPORT names a node import binding requires, from the text between
    ``import`` and ``from``. ``{ a, b as c }`` → the export names ``a``, ``b`` (the
    alias ``c`` is local, the module must export ``b``); a bare default binding
    (``Foo``) → ``default``; ``* as ns`` → [] (namespace — resolution only)."""
    names: list[str] = []
    text = " ".join(str(what).split())
    brace = re.search(r"\{([^}]*)\}", text)
    if brace:
        for part in brace.group(1).split(","):
            token = part.strip()
            if not token:
                continue
            export_name = token.split(" as ")[0].strip()
            if export_name and _quote_free(export_name) and export_name not in names:
                names.append(export_name)
        # A default binding may precede the brace group: `Foo, { a }`.
        head = text[: brace.start()].rstrip().rstrip(",").strip()
    else:
        head = text
    if head and "*" not in head and head not in ("", "default"):
        # `Foo` or `Foo, ` — a default import binds the module's default export.
        if "default" not in names:
            names.insert(0, "default")
    return names


def _node_probe_targets(source: str) -> list[dict]:
    """Structured first-party import targets from a node oracle (mirror of
    :func:`_mjs_import_contract`, same first-party-specifier filtering)."""
    out: list[dict] = []
    seen: set[str] = set()

    def _add(spec: str, names: list[str], raw: str) -> None:
        raw = _clean_token(raw, max_len=_IMPORT_LINE_MAX)
        if not raw or "`" in raw or raw in seen:
            return
        seen.add(raw)
        out.append({"kind": "node", "module": "", "spec": spec.strip(),
                    "level": 0, "names": list(names), "raw": raw})

    for line in (source or "").splitlines():
        m = _MJS_IMPORT_FROM_RE.match(line)
        if m and _first_party_specifier(m.group("spec")):
            spec = m.group("spec").strip()
            what = " ".join(_clean_token(m.group("what"), max_len=80).split())
            names = _node_import_names(what) if _quote_free(what) else []
            _add(spec, names, f"import {what} from '{spec}'" if what else f"import '{spec}'")
            continue
        m = _MJS_SIDE_EFFECT_IMPORT_RE.match(line)
        if m and _first_party_specifier(m.group("spec")):
            spec = m.group("spec").strip()
            _add(spec, [], f"import '{spec}'")
            continue
        m = _MJS_REQUIRE_RE.search(line)
        if m and _first_party_specifier(m.group("spec")):
            spec = m.group("spec").strip()
            what = " ".join(_clean_token(m.group("what"), max_len=80).split())
            names = _node_import_names(what) if _quote_free(what) else []
            _add(spec, names, f"const {what} = require('{spec}')" if what else f"require('{spec}')")
    for tgt in out:
        called = [n for n in tgt["names"] if _node_name_is_called(source or "", n)]
        if called:
            tgt["callables"] = called
    return out[:_IMPORT_CONTRACT_MAX]


def _node_name_is_called(source: str, name: str) -> bool:
    """#826 node twin (cheap + sound): is the imported EXPORT ``name`` invoked as
    ``name(`` anywhere in the oracle? Bounds the typeof-function check to callables the
    oracle actually calls (``default`` is skipped — the local binding differs from the
    export name, so we never mislabel it). A pure structural scan; false negatives (a
    call we cannot see) simply skip the check — never a false red."""
    if not name or name == "default":
        return False
    return bool(re.search(r"(?<![\w$.])" + re.escape(name) + r"\s*\(", source))


def extract_import_probe_targets(rel_path: str, source: str) -> list[dict]:
    """The STRUCTURED first-party import surface of a job-acceptance oracle — the same
    module/spec + export names as :func:`extract_import_contract`, but as machine
    targets a post-merge resolve-probe imports and getattrs (#822). Dispatch by
    extension (``.py`` → ast; ``.mjs``/``.js`` → import-line regex; other → ``[]``).
    Pure + deterministic; each ``raw`` control-stripped, length-capped, de-duplicated —
    same input ⇒ same targets."""
    low = str(rel_path).lower()
    if low.endswith(".py"):
        return _py_probe_targets(source or "")
    if low.endswith((".mjs", ".js")):
        return _node_probe_targets(source or "")
    return []


# ---------------------------------------------------------------------------
# PRECISE module-ownership keys (#790 defect 2) — shared by the driver's
# unresolved-module -> owning-task resolution and the #989 coverage/sprawl checks
# ---------------------------------------------------------------------------
#
# The pre-#790 owner resolution used a COARSE substring match: a python
# ``app.word_frequencies`` collapsed to the token ``app`` (``rsplit('.',1)[0]``), which
# is a substring of every ``app/``-package sibling's ``creates`` paths, so a fix cycle
# re-ran a merged SIBLING while the task that actually OWNS the missing module was never
# a candidate. These pure helpers map a module token / created-file path to identity
# keys matched by EQUALITY, never substring. They live HERE (not the swap driver)
# because ownership matching is consumed on both sides of the plan/run seam: the driver
# (fix-cycle targeting, scope-sprawl findings) AND plan-time contract-coverage
# (:func:`contract_coverage`, called from the acceptance layer, which the driver
# imports — so the driver cannot be their home without a cycle).

#: File extensions that are code modules (stripped when normalizing a path/module to its
#: identity). A dotted python module tail (``app.word_frequencies``) is NOT an extension,
#: so it survives normalization and is later reinterpreted as a package path.
_CODE_EXTS = frozenset({"py", "pyi", "js", "mjs", "cjs", "ts", "tsx", "jsx"})


def _drop_code_ext(path: str) -> str:
    """Strip ONE trailing code extension (``.py``/``.js``/``.mjs``/…). Leaves a dotted
    python-module tail like ``app.word_frequencies`` intact (``word_frequencies`` is not
    a code extension), so it can be reinterpreted as the package path below."""
    base, dot, ext = path.rpartition(".")
    return base if (base and dot and ext.lower() in _CODE_EXTS) else path


def normalize_module_token(token: str) -> str:
    """A module token / node spec / file path -> forward-slash form, no leading ``./``
    ``../`` relative prefix, no trailing code extension. (``../src/x.js`` -> ``src/x``.)"""
    t = str(token or "").strip().replace("\\", "/")
    while t.startswith("./") or t.startswith("../"):
        t = t[t.index("/") + 1:]
    return _drop_code_ext(t.strip("/"))


def module_forms(token: str) -> set[str]:
    """PRECISE ownership keys for ONE imported-module token — matched by EQUALITY
    against a task's created-file forms, NEVER as a substring (the ``app``-substring bug).

    A python dotted module ``app.word_frequencies`` yields the file path
    ``app/word_frequencies`` and the leaf ``word_frequencies``; a node spec
    ``../src/unit-converter-helper.js`` yields ``src/unit-converter-helper`` and the leaf
    ``unit-converter-helper``. Deliberately does NOT emit a bare parent-package token
    (``app``) — that coarse token is exactly what re-ran a sibling."""
    t = normalize_module_token(token)
    if not t:
        return set()
    forms = {t, t.rsplit("/", 1)[-1]}
    if "/" not in t and "." in t:  # a python dotted module -> its file path + leaf
        dotted = t.replace(".", "/")
        forms |= {dotted, dotted.rsplit("/", 1)[-1]}
    return {f.lower() for f in forms if f}


def create_forms(path: str) -> set[str]:
    """Ownership keys a task's contract ``creates`` entry answers to: its extensionless
    path, its leaf basename, and each ANCESTOR PACKAGE directory as a segment-boundary
    path prefix (so a bare-package import ``flashcard_app`` maps to the task that creates
    ``flashcard_app/card_manager.py`` — the B4 shape). The package prefixes are whole path
    segments, NEVER substrings, and a SPECIFIC module import never reduces to a bare parent
    dir, so they cannot re-introduce the ``app``-substring false match."""
    t = normalize_module_token(path)
    if not t:
        return set()
    forms = {t, t.rsplit("/", 1)[-1]}
    segments = t.split("/")
    for i in range(1, len(segments)):  # ancestor package dirs: a, a/b, … (+ each leaf seg)
        forms.add("/".join(segments[:i]))
        forms.add(segments[i - 1])
    return {f.lower() for f in forms if f}


def export_symbol(entry: str) -> str:
    """The bare symbol of a contract ``exports`` signature: ``convertUnit(a, b)`` ->
    ``convertunit``; ``CardManager`` -> ``cardmanager`` (lowercased for case-insensitive
    equality)."""
    s = str(entry or "").strip()
    for sep in ("(", " ", ":", "="):
        s = s.split(sep, 1)[0]
    return s.strip().lower()


# ---------------------------------------------------------------------------
# Plan-time contract coverage (#989) — does every build task own a slice of the
# oracle's import surface, and does every oracle import have an owning task?
# ---------------------------------------------------------------------------


def contract_coverage(
    tasks: "list[dict]", oracle_rel: str, oracle_code: str
) -> "dict | None":
    """Coverage between a multi-task plan's contracts and its job oracle's imports.

    The measured predictor of clean wave-1 scope distribution (#989): a build task
    whose contract owns NO module the job-acceptance oracle imports has no anchored
    slice of the final app and tends to build ALL of it, and an oracle import that no
    task's contract owns is a module no task is ever told to build (the B4 shape).

    ``tasks`` are decompose-shaped dicts (``{task, contract: {creates, exports}}``);
    the oracle side is the #822 probe-target surface
    (:func:`extract_import_probe_targets`). Ownership is the PRECISE equality matching
    of :func:`module_forms` / :func:`create_forms` / :func:`export_symbol` — never
    substring. Relative oracle imports (``level > 0``) are skipped: they resolve inside
    the test package, not to any task's deliverable.

    Returns ``None`` when the check is NOT COMPUTABLE — no oracle code, or the oracle
    names no first-party import target (an ABSENCE of a measurement, never a clean
    bill; oracle absence is surfaced separately as job-acceptance not-run). Otherwise::

        {"tasks": <build tasks checked>, "targets": <import targets checked>,
         "uncovered_tasks": [task ids owning no target],
         "orphan_imports": [raw import lines no task owns]}

    Pure + deterministic: same inputs ⇒ same dict."""
    usable: list[tuple[set[str], set[str], str]] = []
    for target in extract_import_probe_targets(oracle_rel, oracle_code or ""):
        if target.get("kind") == "py" and target.get("level"):
            continue
        path_keys = module_forms(str(target.get("module") or target.get("spec") or ""))
        if not path_keys:
            continue
        symbol_keys = {
            str(n).strip().lower()
            for n in (target.get("names") or [])
            if str(n).strip() and str(n).strip() != "*"
        }
        usable.append((path_keys, symbol_keys, str(target.get("raw") or "")))
    if not usable:
        return None
    owned = [False] * len(usable)
    uncovered: list[str] = []
    n_tasks = 0
    for task in tasks:
        if not isinstance(task, dict):
            continue
        n_tasks += 1
        raw_contract = task.get("contract")
        contract = raw_contract if isinstance(raw_contract, dict) else {}
        creates_raw = contract.get("creates")
        exports_raw = contract.get("exports")
        forms: set[str] = set()
        for c in creates_raw if isinstance(creates_raw, list) else []:
            forms |= create_forms(str(c))
        symbols = {
            export_symbol(str(e)) for e in (exports_raw if isinstance(exports_raw, list) else [])
        }
        symbols.discard("")
        covered = False
        for i, (path_keys, symbol_keys, _raw) in enumerate(usable):
            if (forms & path_keys) or (symbols & symbol_keys):
                covered = True
                owned[i] = True
        if not covered:
            uncovered.append(str(task.get("task", "") or "?"))
    return {
        "tasks": n_tasks,
        "targets": len(usable),
        "uncovered_tasks": uncovered,
        "orphan_imports": [raw for i, (_pk, _sk, raw) in enumerate(usable) if not owned[i]],
    }


# ---------------------------------------------------------------------------
# Pack assembly (deterministic, capped)
# ---------------------------------------------------------------------------


def dep_entry(task_id: str, contract: dict | None, delta: dict | None) -> dict:
    """Normalize one dependency into the pack-builder's input shape.

    ``contract`` is the ruler-validated plan contract (``{creates, exports, notes}``);
    ``delta`` is the as-built result from the injected git seam (``{files,
    signatures}``). Both tolerate ``None``/garbage — the entry degrades to just the id
    (a dependency with no known interface still gets named)."""
    contract = contract if isinstance(contract, dict) else {}
    delta = delta if isinstance(delta, dict) else {}

    def _str_list(raw: object, max_items: int) -> list[str]:
        if not isinstance(raw, list):
            return []
        vals = [_clean_token(v) for v in raw if isinstance(v, str)]
        return [v for v in vals if v][:max_items]

    return {
        "id": _clean_token(str(task_id), max_len=64),
        "creates": _str_list(contract.get("creates"), 16),
        "exports": _str_list(contract.get("exports"), 16),
        "notes": _clean_token(str(contract.get("notes", "") or ""), max_len=280),
        "files": _str_list(delta.get("files"), 24),
        "signatures": _str_list(delta.get("signatures"), 32),
    }


def _render(deps: list[dict], sig_drop: dict[str, int], file_drop: dict[str, int]) -> str:
    """Render the pack with per-dep signature/file drop counts applied (the truncation
    knobs). Deterministic: fixed section order, original dep order."""
    lines: list[str] = [PACK_HEADER]
    for d in deps:
        lines.append(f"Dependency '{d['id']}':")
        contract_bits: list[str] = []
        if d["creates"]:
            contract_bits.append("creates " + ", ".join(d["creates"]))
        if d["exports"]:
            contract_bits.append("exports " + "; ".join(d["exports"]))
        if d["notes"]:
            contract_bits.append("notes: " + d["notes"])
        if contract_bits:
            lines.append("  contract: " + "; ".join(contract_bits))
        n_files = len(d["files"]) - file_drop.get(d["id"], 0)
        if n_files > 0:
            shown = d["files"][:n_files]
            more = len(d["files"]) - n_files
            suffix = f" (+{more} more)" if more > 0 else ""
            lines.append("  as-built files: " + ", ".join(shown) + suffix)
        sigs = d["_kept_sigs"]
        if sigs:
            lines.append("  as-built exports: " + "; ".join(sigs))
    lines.append(PACK_INSTRUCTION)
    return "\n".join(lines)


def build_context_pack(deps: list[dict], *, max_chars: int = CONTEXT_PACK_MAX_CHARS) -> str:
    """Assemble the pack for one task from its normalized dependency entries
    (:func:`dep_entry`), deterministically truncated to *max_chars*.

    Truncation order (plan §4.4 — "longest-signature-last" means the longest
    signatures are the FIRST to go, so the short, dense interface lines survive):

      1. drop as-built SIGNATURES, longest first (tie → the later one);
      2. then trim as-built FILE lists from the tail (``+N more``);
      3. then a hard character cut of the body — the INSTRUCTION line always survives.

    Empty *deps* ⇒ ``''`` (no pack — the caller appends nothing)."""
    if not deps:
        return ""
    work = [dict(d) for d in deps]
    for d in work:
        d["_kept_sigs"] = list(d.get("signatures", []))

    sig_drop: dict[str, int] = {}
    file_drop: dict[str, int] = {d["id"]: 0 for d in work}

    def render() -> str:
        return _render(work, sig_drop, file_drop)

    text = render()
    # 1. drop signatures, longest first (deterministic tie-break: the LATER entry).
    while len(text) > max_chars:
        longest_dep = None
        longest_idx = -1
        longest_len = -1
        for d in work:
            for i, s in enumerate(d["_kept_sigs"]):
                if len(s) >= longest_len:
                    longest_len = len(s)
                    longest_dep = d
                    longest_idx = i
        if longest_dep is None:
            break
        longest_dep["_kept_sigs"].pop(longest_idx)
        text = render()
    # 2. trim file lists from the tail, round-robin over deps with the most files.
    while len(text) > max_chars:
        candidates = [d for d in work if len(d["files"]) - file_drop[d["id"]] > 0]
        if not candidates:
            break
        target = max(candidates, key=lambda d: len(d["files"]) - file_drop[d["id"]])
        file_drop[target["id"]] += 1
        text = render()
    # 3. hard cut — the instruction line ALWAYS survives (append after the cut).
    if len(text) > max_chars:
        budget = max_chars - len(PACK_INSTRUCTION) - 1
        body = text[: max(budget, 0)]
        body = body.rsplit("\n", 1)[0] if "\n" in body else body
        text = body + "\n" + PACK_INSTRUCTION
    return text


def context_pack_for_task(
    plan_task,
    plan,
    *,
    delta_fn,
    max_chars: int = CONTEXT_PACK_MAX_CHARS,
) -> str:
    """The driver-facing entry: build *plan_task*'s pack from its plan dependencies.

    ``plan_task``/``plan`` are ``plan_graph.PlanTask``/``JobPlan``; ``delta_fn`` is the
    injected as-built reader (``(dep_task_id) -> {files, signatures}`` — the driver
    threads its ``SwapOps.dep_delta`` + recorded merge refs through this). A task with
    no dependencies gets ``''`` (no pack — today's prompt, byte-identical)."""
    if not getattr(plan_task, "depends_on", None):
        return ""
    entries: list[dict] = []
    for dep_id in plan_task.depends_on:
        dep = plan.task(dep_id)
        try:
            delta = delta_fn(dep_id)
        except Exception:  # noqa: BLE001 — a delta failure degrades to contract-only
            delta = {}
        entries.append(dep_entry(dep_id, dep.contract.to_raw(), delta))
    return build_context_pack(entries, max_chars=max_chars)
