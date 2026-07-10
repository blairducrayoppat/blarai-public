"""A TINY reference structural extractor — the N6 assertion target (W3 stub).

The real thing is Lane A/W3's ``shared/fleet/context_pack.py`` (plan §4.4 / §10
S2): "structural-only extraction — file paths from ``git diff --name-only``;
export *signatures* via Python ``ast`` / mjs export-line parsing — never
comments, docstrings, or file bodies." That module does not exist yet.

This stub exists so the N6 rig has a concrete, TEST-FIRST contract to assert
against TODAY: given a built dependency file, return ONLY its path + public
signatures, with the human-language body (comments, docstrings, string
literals) structurally UNREACHABLE. It is deliberately minimal and conservative
(signatures only, no bodies) — W3 should implement its extractor to satisfy the
SAME assertions in ``shared/tests/test_m2_rigs.py`` and then this stub is
retired. Marked for W3: DO NOT ship this as production; it is a fixture oracle.

Security property under test (S2): the returned strings contain paths and
signatures and NOTHING copied out of comments / docstrings / string literals —
so an adversarial instruction planted in a dependency's body can never ride a
context pack into the next task's prompt.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

#: mjs/js export forms we recognize structurally (name only — never the body).
_MJS_EXPORT_FN = re.compile(
    r"^\s*export\s+(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(([^)]*)\)"
)
_MJS_EXPORT_CONST = re.compile(
    r"^\s*export\s+(?:const|let|var)\s+([A-Za-z_$][\w$]*)"
)


def extract_python_signatures(source: str) -> list[str]:
    """Public ``def``/``class`` signatures from Python source via ``ast`` — NAMES +
    parameter names only. Docstrings, comments, and bodies are never read: we walk
    the parsed tree, so anything that is not a def/class header is structurally out
    of reach. Underscore-prefixed names are treated as private and skipped."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    out: list[str] = []
    for node in tree.body:  # module top level only — the public surface
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_"):
                continue
            params = [a.arg for a in node.args.args]
            out.append(f"{node.name}({', '.join(params)})")
        elif isinstance(node, ast.ClassDef):
            if node.name.startswith("_"):
                continue
            out.append(f"class {node.name}")
    return out


def extract_mjs_signatures(source: str) -> list[str]:
    """Public ``export`` signatures from mjs/js source by line regex — export
    NAMES only, never the body between braces. A ``const``/`let` export yields its
    name; a function export yields ``name(params)``."""
    out: list[str] = []
    for line in source.splitlines():
        m = _MJS_EXPORT_FN.match(line)
        if m:
            params = ", ".join(p.strip().split("=")[0].strip()
                               for p in m.group(2).split(",") if p.strip())
            out.append(f"{m.group(1)}({params})")
            continue
        m = _MJS_EXPORT_CONST.match(line)
        if m:
            out.append(m.group(1))
    return out


def extract_pack_signatures(rel_path: str, source: str) -> dict:
    """The structural card for one built file: ``{"path": rel, "signatures": [...]}``.

    This is the ONLY shape a context pack derives from a built artifact. The
    human-language part of a pack comes exclusively from the ruler-validated PLAN
    contract, never from here (S2). Ecosystem is chosen by extension.
    """
    suffix = Path(rel_path).suffix.lower()
    if suffix == ".py":
        sigs = extract_python_signatures(source)
    elif suffix in (".mjs", ".js"):
        sigs = extract_mjs_signatures(source)
    else:
        sigs = []
    return {"path": rel_path, "signatures": sigs}
