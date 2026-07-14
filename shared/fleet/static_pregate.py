"""Error-level static pre-gate (#831 QUALITY-13) — the cheapest per-task code gate.

The rank-2 failure lever the taxonomy kept surfacing is a coder that merges code with
a *trivial* defect — a syntax error, an undefined name — which then rides all the way
to the wave suite / the finish-line oracle / the GPU spend before failing there, opaque
and expensive. Today there is zero CODE-level lint anywhere in the pipeline: the only
lint is the VISUAL/layout one (:mod:`shared.fleet.layout_lint`). This module is its
code-level sibling — the fail-fast net that catches a ``SyntaxError`` / ``F821`` the
instant a task's code lands, names the EXACT line, and feeds ONE targeted fix cycle,
BEFORE the expensive grading spends.

**The taste-immunity hard lock (the load-bearing design constraint).** A 30B coder
DROWNS in style nits — it cannot tell an important finding from a cosmetic one when
handed a wall of E501/line-length/import-order noise, and a gate that parks on taste is
worse than no gate (small-model note, c.1721). So this gate selects **ERROR level ONLY**
— :data:`PYTHON_ERROR_SELECT` = ``(E9, F821, F823)`` — and NO style rule is ever
selectable here. A file with long lines / unsorted imports / bad spacing but no
error-level defect PASSES UNTOUCHED. Widening the select set to any style rule is
forbidden; ``test_static_pregate`` locks it.

**Clean-environment gating (the #822 H1 lesson, applied to ruff).** The coder OWNS the
tree this gate runs over, so a coder ``ruff.toml`` / ``pyproject [tool.ruff]`` that
``ignore``\\s F821 would be a grader-environment evasion exactly like the conftest one
#822 closed. Ruff runs with ``--isolated`` (ALL config files ignored), so the subject's
tree can never influence the verdict — the same principle as grade_env's hermetic
pytest recipe, one turn cheaper (ruff never imports the code; it parses it).

**Two legs, one shape.** Python → ``ruff check --isolated --select E9,F821,F823
--output-format json`` (ruff pulled per-invocation via ``uv run --with`` — pinned
:data:`RUFF_PIN`, never a global install; the SAME mechanism the job-oracle grade uses
for pytest). Node → ``node --check`` per created file (syntax-only; it never executes
the module). A missing ruff DEGRADES HONESTLY to ``skipped-no-ruff`` (``ok=None``) and
says so — a missing tool never blocks a dispatch, it is recorded as a not-run.

Design invariants: error-level-only is a HARD lock (taste-immunity); fail-soft at every
subprocess boundary (a tool that cannot run is an honest ``skipped``, never a false
green nor a false red); pure + deterministic (subprocess ``run`` + ``which`` are
injected, so the whole gate is testable without a real ruff/node); JSON-serialisable
result (it crosses the swap-driver seam + the ``--out`` CLI file for #827 evidence).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

#: The ONLY ruff rule codes this gate selects — ERROR level: E9 (syntax / parse
#: errors, surfaced by ruff as ``invalid-syntax``), F821 (undefined name — the
#: ``convertUnits`` shape), F823 (local variable referenced before assignment).
#: THE TASTE-IMMUNITY HARD LOCK: no style rule is ever added here. A small-model
#: coder acts cleanly on "F821 undefined name 'convertUnits' at cli.js:12" and drowns
#: in style nits, so a file with long lines / import-order issues but no E9/F821/F823
#: MUST pass untouched. ``test_static_pregate`` pins this tuple; widening it is a defect.
PYTHON_ERROR_SELECT: tuple[str, ...] = ("E9", "F821", "F823")

#: Pinned ruff (reproducibility + host/tool parity, the ``pytest==9.1.1`` precedent):
#: pulled per-invocation via ``uv run --no-project --with`` — never a global install,
#: so a box without ruff installed still runs the leg as long as uv can resolve it, and
#: degrades honestly to ``skipped-no-ruff`` only when neither uv-ruff nor a direct ruff
#: is reachable. Bump only with a measured re-verify (the error-level codes are stable).
RUFF_PIN: str = "ruff==0.14.3"

#: File suffixes each leg claims. Anything else (``.md`` / ``.json`` / ``.cs`` / …) is
#: not statically checkable here and is simply not counted (a doc-only merge is clean).
PYTHON_SUFFIXES: tuple[str, ...] = (".py",)
NODE_SUFFIXES: tuple[str, ...] = (".js", ".mjs", ".cjs")

#: CLI / standalone timeout fallback. The LIVE driver seam passes
#: ``swap_ops.STATIC_PREGATE_TIMEOUT_S`` (the registered, scarred constant) — this
#: literal only bounds a hand-run ``python -m shared.fleet.static_pregate``.
_DEFAULT_TIMEOUT_S: float = 120.0

#: Cap on how many named errors ride a single verdict (a file with 40 undefined names
#: needs its first few named for the fix cycle, not a wall of text into a small model).
_MAX_ERRORS: int = 16
#: Per-message cap (a ruff/node message can carry an arbitrarily long path).
_REASON_MAX: int = 400

#: Node stderr shapes: the leading ``<file>:<line>`` frame and the ``SyntaxError: …``.
_NODE_LINE_RE = re.compile(r":(?P<line>\d+)\s*$")
_NODE_MSG_RE = re.compile(r"^(?P<type>[A-Za-z]*Error):\s*(?P<msg>.*)$")

#: The verdict-stamp vocabulary (the #827 evidence token). ``fixed:<n>`` is a
#: DRIVER-level overlay (set after a successful fix cycle) — the module emits the three
#: base states only.
STAMP_CLEAN = "clean"
STAMP_FAIL = "fail"
STAMP_SKIPPED = "skipped"


def _clip(text: object, cap: int = _REASON_MAX) -> str:
    """One-line, length-capped string (deterministic; never a newline into JSON)."""
    return " ".join(str(text).split())[:cap]


def _relpath(filename: object, repo_root: "str | Path") -> str:
    """``filename`` (ruff echoes it absolute) made repo-relative with ``/`` separators;
    falls back to the raw string if it does not live under the repo."""
    raw = str(filename or "")
    try:
        return str(Path(raw).resolve().relative_to(Path(repo_root).resolve())).replace(
            "\\", "/")
    except (ValueError, OSError):
        return raw.replace("\\", "/")


def classify_files(files: list[str]) -> tuple[list[str], list[str]]:
    """Split *files* into ``(python, node)`` by suffix (case-insensitive). A file with
    neither suffix belongs to neither leg — it is not statically checkable here."""
    py: list[str] = []
    node: list[str] = []
    for f in files:
        low = str(f).lower()
        if low.endswith(PYTHON_SUFFIXES):
            py.append(f)
        elif low.endswith(NODE_SUFFIXES):
            node.append(f)
    return py, node


# ---- python leg (ruff, ERROR level only) ----------------------------------


def resolve_ruff_argv(
    which: Callable[[str], "str | None"] = shutil.which,
) -> "list[str] | None":
    """The argv PREFIX that invokes ruff, or ``None`` when ruff is unreachable.

    Prefers ``uv run --no-project --with <pinned> ruff`` (the fleet's established
    tool-pull mechanism — no global install needed), else a direct ``ruff`` on PATH.
    ``None`` is the honest ``skipped-no-ruff`` signal — the caller degrades, never
    blocks (do NOT synthesise a green from a missing tool)."""
    uv = which("uv")
    if uv:
        return [uv, "run", "--no-project", "--with", RUFF_PIN, "ruff"]
    ruff = which("ruff")
    if ruff:
        return [ruff]
    return None


def build_ruff_cmd(argv_prefix: list[str], files: list[str]) -> list[str]:
    """The full ruff argv: ERROR-level select, ``--isolated`` (deny the coder's tree any
    config influence — the #822 clean-env lesson), JSON output, ``--`` before the file
    list so a hostile filename can never be read as a flag."""
    return [
        *argv_prefix, "check", "--isolated",
        "--select", ",".join(PYTHON_ERROR_SELECT),
        "--output-format", "json", "--", *files,
    ]


def parse_ruff_json(stdout: str) -> "list[dict] | None":
    """Ruff's ``--output-format json`` is a top-level array (``[]`` when clean). Return
    the list, or ``None`` when the output is not a JSON array — the machinery-failure
    signal (uv could not resolve ruff, an internal ruff error) that degrades to a
    not-run rather than a false verdict."""
    try:
        data = json.loads(stdout)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, list) else None


def _ruff_finding(entry: dict, repo_root: "str | Path") -> dict:
    """One ruff JSON entry → the module's error dict (path/line/col/code/message + a
    single-line ``summary`` == the fix-cycle line)."""
    loc = entry.get("location") if isinstance(entry.get("location"), dict) else {}
    try:
        line = int(loc.get("row") or 0)
    except (TypeError, ValueError):
        line = 0
    try:
        col = int(loc.get("column") or 0)
    except (TypeError, ValueError):
        col = 0
    code = str(entry.get("code") or "invalid-syntax")
    message = _clip(entry.get("message") or "")
    path = _relpath(entry.get("filename") or "", repo_root)
    summary = f"{path}:{line} {code}: {message}"
    return {"path": path, "line": line, "col": col, "code": code,
            "message": message, "lang": "python", "raw": summary, "summary": summary}


def probe_python_files(
    files: list[str],
    repo_root: "str | Path",
    *,
    run: Callable[..., tuple],
    which: Callable[[str], "str | None"] = shutil.which,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> dict:
    """Run the ERROR-level ruff check over *files* (repo-relative, cwd=repo).

    ``{"ok": True|False|None, "errors": [...], "checked": int, "reason": str}``:
    ``True`` no error-level findings, ``False`` at least one (each named), ``None``
    could-not-run (no ruff → ``reason='no-ruff'``; a ruff/uv machinery failure →
    ``reason='ruff-could-not-run: …'``). Fail-soft — never raises."""
    files = [f for f in files if f]
    if not files:
        return {"ok": True, "errors": [], "checked": 0, "reason": ""}
    prefix = resolve_ruff_argv(which)
    if prefix is None:
        return {"ok": None, "errors": [], "checked": 0, "reason": "no-ruff"}
    try:
        ok, out, err = run(build_ruff_cmd(prefix, files), timeout_s, str(repo_root))
    except Exception as exc:  # noqa: BLE001 — a spawn failure is a not-run, never a raise
        return {"ok": None, "errors": [], "checked": 0,
                "reason": f"ruff-could-not-run: {type(exc).__name__}"}
    parsed = parse_ruff_json(out or "")
    if parsed is None:
        return {"ok": None, "errors": [], "checked": 0,
                "reason": "ruff-could-not-run: " + _clip(err or out or "no ruff output")}
    errors = [_ruff_finding(e, repo_root) for e in parsed if isinstance(e, dict)]
    return {"ok": len(errors) == 0, "errors": errors[:_MAX_ERRORS],
            "checked": len(files), "reason": ""}


# ---- node leg (node --check, syntax only) ---------------------------------


def _parse_node_error(rel: str, stderr: str) -> dict:
    """``node --check`` failure stderr → the module's error dict. Node prints
    ``<file>:<line>`` then a caret frame then ``SyntaxError: <msg>``; we take the line
    number and the error message (the path is the file we checked, so relative)."""
    line = 0
    message = ""
    for raw in (stderr or "").splitlines():
        s = raw.strip()
        if line == 0:
            m = _NODE_LINE_RE.search(s)
            if m:
                try:
                    line = int(m.group("line"))
                except (TypeError, ValueError):
                    line = 0
        if not message:
            m2 = _NODE_MSG_RE.match(s)
            if m2:
                message = _clip(f"{m2.group('type')}: {m2.group('msg')}")
    if not message:
        message = "syntax error (node --check failed)"
    summary = f"{rel}:{line} syntax-error: {message}"
    return {"path": rel, "line": line, "col": 0, "code": "syntax-error",
            "message": message, "lang": "node", "raw": summary, "summary": summary}


def probe_node_files(
    files: list[str],
    repo_root: "str | Path",
    *,
    run: Callable[..., tuple],
    which: Callable[[str], "str | None"] = shutil.which,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> dict:
    """Run ``node --check`` over each *file* (repo-relative, cwd=repo). Syntax-only —
    node parses the module, it never executes it. Same result shape as
    :func:`probe_python_files`; a missing node degrades to ``ok=None`` (``no-node``)."""
    files = [f for f in files if f]
    if not files:
        return {"ok": True, "errors": [], "checked": 0, "reason": ""}
    node = which("node")
    if not node:
        return {"ok": None, "errors": [], "checked": 0, "reason": "no-node"}
    errors: list[dict] = []
    checked = 0
    for rel in files:
        try:
            ok, out, err = run([node, "--check", rel], timeout_s, str(repo_root))
        except Exception as exc:  # noqa: BLE001 — one file's spawn failure never raises
            errors.append(_parse_node_error(
                rel, f"SyntaxError: node --check could not run ({type(exc).__name__})"))
            checked += 1
            continue
        checked += 1
        if not ok:
            errors.append(_parse_node_error(rel, err or out or ""))
    return {"ok": len(errors) == 0, "errors": errors[:_MAX_ERRORS],
            "checked": checked, "reason": ""}


# ---- orchestration --------------------------------------------------------


def run_static_pregate(
    files: list[str],
    repo_root: "str | Path",
    *,
    run: Callable[..., tuple],
    which: Callable[[str], "str | None"] = shutil.which,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> dict:
    """The whole gate over *files* (a task's created/changed source, repo-relative).

    Runs the python leg (ruff, error-level) + the node leg (node --check), combines,
    and returns a JSON-serialisable verdict::

        {"ok": True|False|None, "errors": [...], "checked": int,
         "skipped": [...], "stamp": "clean"|"fail"|"skipped", "evidence": str}

    ``ok`` — ``True`` the gate ran and found no error-level defect; ``False`` at least
    one (each NAMED for the fix cycle); ``None`` a relevant leg could not run (a tool
    was missing) and nothing errored. An error ALWAYS wins over a skip (a real defect in
    one leg is reported even if the other leg's tool was absent). ``stamp`` is the #827
    token; ``skipped`` lists the degraded legs (``no-ruff`` / ``no-node``)."""
    py_files, node_files = classify_files([str(f) for f in files if f])
    py = probe_python_files(py_files, repo_root, run=run, which=which, timeout_s=timeout_s)
    nd = probe_node_files(node_files, repo_root, run=run, which=which, timeout_s=timeout_s)

    errors = list(py.get("errors", [])) + list(nd.get("errors", []))
    errors = errors[:_MAX_ERRORS]
    checked = int(py.get("checked", 0)) + int(nd.get("checked", 0))
    skipped: list[str] = []
    if py_files and py.get("ok") is None:
        skipped.append(str(py.get("reason") or "no-ruff"))
    if node_files and nd.get("ok") is None:
        skipped.append(str(nd.get("reason") or "no-node"))

    if errors:
        ok: "bool | None" = False
        stamp = STAMP_FAIL
        named = "; ".join(e.get("summary", "") for e in errors[:6])
        evidence = f"{len(errors)} error-level defect(s): {named}"
    elif skipped:
        # A relevant leg's tool was missing and nothing errored — honest not-run.
        ok = None
        stamp = STAMP_SKIPPED
        evidence = "; ".join(skipped)
    else:
        ok = True
        stamp = STAMP_CLEAN
        evidence = f"{checked} file(s) clean" if checked else "no python/node source to check"
    return {"ok": ok, "errors": errors, "checked": checked,
            "skipped": skipped, "stamp": stamp, "evidence": _clip(evidence, 1200)}


def format_fix_prompt(errors: list[dict]) -> str:
    """The single-focus fix-cycle prompt — the EXACT error verbatim (``file:line
    code: message``), one per line, and NOTHING else (the small-model discipline: a 30B
    coder acts cleanly on a named error, not on a vague 'clean it up')."""
    lines = "\n".join(
        f"  {e.get('summary') or e.get('raw') or ''}"
        for e in errors if isinstance(e, dict)
    )
    return (
        "STATIC PRE-GATE FIX (single focus — fix ONLY these exact error-level "
        "defects, change nothing else): the code you merged has a syntax error or an "
        "undefined name, caught statically BEFORE the test suite ran. Fix each named "
        "line exactly; do NOT refactor, rename, reformat, or touch anything unrelated.\n"
        f"{lines}"
    )


# ---- CLI (run-fleet's cheapest-first per-task step can invoke this) --------


def _default_run(cmd: list[str], timeout_s: float, cwd: "str | None" = None) -> tuple:
    """Bounded, no-shell subprocess for the standalone CLI (the driver seam injects the
    fleet's console-safe ``_safe_run`` instead). Fail-closed: any error → ``(False, …)``."""
    try:
        cp = subprocess.run(  # noqa: S603 — vector argv, no shell
            cmd, capture_output=True, text=True, timeout=timeout_s, cwd=cwd or None)
        return (cp.returncode == 0, cp.stdout or "", cp.stderr or "")
    except subprocess.TimeoutExpired:
        return (False, "", f"timed out after {timeout_s:.0f}s")
    except Exception as exc:  # noqa: BLE001 — fail-closed
        return (False, "", f"spawn error: {type(exc).__name__}: {exc}")


def _write_verdict(out_path: str, verdict: dict) -> None:
    try:
        Path(out_path).write_text(json.dumps(verdict), encoding="utf-8")
    except OSError:
        pass


def _main(argv: "list[str] | None" = None) -> int:
    """CLI: read the created-files JSON, run the gate over the target repo, write the
    verdict JSON to ``--out``, and exit 0 (clean) / 1 (error-level defect) / 2
    (skipped / could-not-run — a missing tool is never a hard fail)."""
    parser = argparse.ArgumentParser(prog="python -m shared.fleet.static_pregate")
    parser.add_argument("--files", required=True,
                        help="path to a JSON list of repo-relative files")
    parser.add_argument("--repo", required=True, help="the integrated repo root")
    parser.add_argument("--out", required=True, help="path to write the verdict JSON")
    parser.add_argument("--timeout", type=float, default=_DEFAULT_TIMEOUT_S)
    args = parser.parse_args(argv)
    try:
        files = json.loads(Path(args.files).read_text(encoding="utf-8"))
        if not isinstance(files, list):
            raise ValueError("files JSON is not a list")
    except Exception as exc:  # noqa: BLE001 — a bad files file is a machinery skip
        _write_verdict(args.out, {"ok": None, "errors": [], "checked": 0,
                                  "skipped": ["bad-files-arg"], "stamp": STAMP_SKIPPED,
                                  "evidence": f"could not read files: {type(exc).__name__}"})
        print(f"static-pregate: skipped (could not read files: {type(exc).__name__})")
        return 2
    result = run_static_pregate([str(f) for f in files], args.repo,
                                run=_default_run, timeout_s=args.timeout)
    _write_verdict(args.out, result)
    print(f"static-pregate: {result.get('stamp')} checked={result.get('checked')} "
          f"errors={len(result.get('errors', []))}")
    ok = result.get("ok")
    if ok is None:
        return 2
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_main())
