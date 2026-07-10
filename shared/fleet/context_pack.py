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
