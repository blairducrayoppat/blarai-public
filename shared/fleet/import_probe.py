"""Symbol-level import-contract PROBE (#822 H3/H3b/H4) — the deterministic resolver
the wave gate runs post-merge to move the job-oracle import contract from ADVISORY
(surfaced into the coder's prompt, #790 rec-1) to ENFORCED.

The B4/B6/B7 park class (failure-taxonomy-20260711): the coder MERGED working code,
then the wave-final job oracle failed at ``from cli_interface import run_cli`` /
``ERR_MODULE_NOT_FOUND src/slugify-phrase.js`` — a module the coder placed at a
DIFFERENT path than the oracle imports (B6n2: built ``app/cli_interface.py`` while the
oracle imports top-level ``cli_interface``; the coder was 23/24 close, then turn-capped
without ever being told the exact unresolved entry). This probe RESOLVES every contract
entry from the repo root exactly as the oracle will, getattrs each named export, and
names the exact unresolved/mismatched entry so the coder gets ONE targeted fix cycle
instead of a wave-final surprise.

**Two halves, one recipe.** The Python half (:func:`probe_python_targets` + the
``__main__`` CLI) is the SCRIPT the host/guest run via ``python`` under the #822 H1
clean-env recipe (``--import-mode=importlib``, ``PYTHONSAFEPATH=1``,
``PYTHONPATH=<repo>``) — the SAME cwd/interpreter/import-mode the oracle grades with,
so probe-green ⇒ oracle-imports-green by construction (H4), never a probe/oracle split.
Pure stdlib: this file is executed BY PATH under ``PYTHONPATH=<target-repo>`` (never the
BlarAI checkout), so it can import nothing first-party. The node half
(:func:`build_node_probe_script`) EMITS a ``node:`` ESM probe the caller runs with
``node`` (node resolution has no Python equivalent) — its dynamic ``import()`` resolves
each specifier relative to the probe file placed in the oracle's own directory, byte-
identical to how the node oracle resolves them.

**What a probe FAILURE means** (each names the exact entry — the signal B6n2 lacked):
  * module does not resolve from the repo root (B6n2 / B7n1 — the layout-drift class);
  * module resolves but a contract-named export is ABSENT under ``getattr`` (the
    stub/lazy/re-export evasion — C1: ``import cli_interface`` resolves but ``run_cli``
    is a no-op / missing);
  * module resolves at a ``__file__`` OUTSIDE the repo (C2 — a site-packages / ``.pth``
    shadow of a first-party name);
  * #826 — a contract callable resolves but its SIGNATURE cannot accept the arity the
    oracle CALLS it with (the built-wrong-signature B4n2 delta: the oracle asserts
    ``check_answer('cat', 'cat')`` but the coder built ``check_answer(question)``). The
    per-callable arity contract rides each target's ``signatures`` field (attached
    host-side from :mod:`shared.fleet.interface_contract`); the probe binds sentinels to
    ``inspect.signature`` — it never invokes the callable.

Design invariants: precision-first (a module that resolves with every named export
present is NEVER flagged on ``__file__`` grounds alone — only a file that exists OUTSIDE
the repo fails H3b, so an implicit namespace package with the names present passes; an
arity mismatch is reported ONLY on a concrete ``Signature.bind`` TypeError, never on an
un-introspectable builtin); fail-closed at the caller (a probe that cannot run is an
honest not-run, never an implied pass).
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import json
import sys
from pathlib import Path

#: Cap on how many unresolved entries a single verdict carries (a runaway oracle with
#: dozens of bad imports needs its first few named, not a wall of text in the prompt).
_MAX_UNRESOLVED = 16
#: Per-reason string cap (an import error message can carry an arbitrarily long path).
_REASON_MAX = 400
#: Distinct-from-None sentinel for getattr (a module may legitimately export ``None``).
_MISSING = object()


def _clip(text: str, cap: int = _REASON_MAX) -> str:
    """One-line, length-capped reason string (deterministic; no newlines into JSON)."""
    return " ".join(str(text).split())[:cap]


def _check_callable_arity(obj: object, sig: dict) -> "str | None":
    """#826 — does the RESOLVED callable accept the arity the acceptance oracle CALLS it
    with? Returns a reason string on a DEFINITE mismatch (the built-wrong-signature B4n2
    delta), or ``None`` when it is fine OR cannot be decided (precision-first: an
    un-introspectable builtin, a *args-relaxed contract, or any inspect failure NEVER
    yields a false red — the sound signal is a concrete ``Signature.bind`` TypeError).

    ``sig`` is one arity contract from a target's ``signatures`` list:
    ``{name, min_positional, max_positional, keywords, starargs, starkwargs}``. The
    check binds SENTINELS (never invokes the callable — probe, don't run): the built
    signature must bind both the smallest and the largest observed positional call and
    accept every keyword the oracle passes; if it cannot, that TypeError names the delta."""
    name = str(sig.get("name", ""))
    if not callable(obj):
        return (f"contract callable '{name}' resolves but is not callable "
                "(the acceptance test calls it)")
    try:
        signature = inspect.signature(obj)
    except (ValueError, TypeError):
        return None  # builtin / C-level / unintrospectable → cannot decide, never a red
    starargs = bool(sig.get("starargs"))
    starkwargs = bool(sig.get("starkwargs"))
    keywords = [str(k) for k in (sig.get("keywords") or []) if k]
    try:
        max_pos = int(sig.get("max_positional", 0))
        min_pos = int(sig.get("min_positional", max_pos))
    except (TypeError, ValueError):
        return None
    # The oracle passed **kw (unknown keyword names) → the built signature could need any
    # of them; do not attempt to falsify the keyword surface.
    kw_sentinels = {} if starkwargs else {k: None for k in keywords}
    if starargs:
        # A ``f(*xs)`` call is under-determined in BOTH directions (the splat may supply
        # any number of positionals) — the positional count is unsound to falsify, so only
        # the keyword surface is checked (bind_partial tolerates missing required args and
        # fails ONLY on a keyword the built signature cannot accept).
        if kw_sentinels:
            try:
                signature.bind_partial(**kw_sentinels)
            except TypeError as exc:
                return (f"built signature {name}{signature} cannot accept the acceptance "
                        f"test's call ({_clip(str(exc), cap=160)})")
        return None
    # Positional counts to falsify: the largest and smallest observed bare-positional
    # calls (equal for a fixed-arity callable → one bind). The built signature must bind
    # BOTH — too many (coder built fewer params) and too few required (coder built more).
    counts = {min_pos, max_pos}
    for count in sorted(counts):
        try:
            signature.bind(*([None] * count), **kw_sentinels)
        except TypeError as exc:
            return (f"built signature {name}{signature} cannot accept the acceptance "
                    f"test's call ({_clip(str(exc), cap=160)})")
    return None


def probe_python_targets(targets: list[dict], repo_root: "str | Path") -> dict:
    """Resolve each first-party Python target from the current ``sys.path`` (which the
    clean-env recipe has set to ``[<repo>, <stdlib>, <pytest env>]``) and getattr each
    contract-named export. Returns ``{"ok": bool, "unresolved": [...], "probed": int}``.

    Each unresolved entry is ``{"raw", "module", "name"?, "reason"}`` — the exact
    contract line and why it did not resolve, for the coder's targeted fix cycle.
    Relative imports (``level > 0``) are recorded as ``skipped`` (a package-relative
    import cannot be resolved standalone without a package context) and never counted
    as unresolved — they are not the layout-drift class this probe targets."""
    try:
        repo = Path(repo_root).resolve()
    except Exception:  # noqa: BLE001 — an unresolvable repo path is a machinery failure
        return {"ok": None, "unresolved": [], "probed": 0,
                "error": f"repo path did not resolve: {repo_root!r}"}
    unresolved: list[dict] = []
    probed = 0
    skipped = 0
    for t in targets:
        module = str(t.get("module", "") or "")
        level = int(t.get("level", 0) or 0)
        names = [str(n) for n in (t.get("names") or [])]
        raw = _clip(str(t.get("raw", module) or module), cap=_REASON_MAX)
        if level > 0 or not module:
            skipped += 1
            continue
        probed += 1
        try:
            mod = importlib.import_module(module)
        except BaseException as exc:  # noqa: BLE001 — ANY import failure is a real miss
            unresolved.append({
                "raw": raw, "module": module,
                "reason": _clip(
                    f"module '{module}' does not resolve from the repo root "
                    f"({type(exc).__name__}: {exc})"),
            })
            continue
        # H3b: a first-party module that carries a __file__ must live UNDER the repo.
        # A None __file__ (implicit namespace package / builtin) is NOT flagged on its
        # own — precision-first; the getattr checks below are the real symbol test.
        modfile = getattr(mod, "__file__", None)
        if modfile:
            try:
                mp = Path(modfile).resolve()
                if not mp.is_relative_to(repo):
                    unresolved.append({
                        "raw": raw, "module": module,
                        "reason": _clip(
                            f"module '{module}' resolves at {mp} — OUTSIDE the repo "
                            "(a site-packages/.pth shadow of a first-party name)"),
                    })
                    continue
            except Exception:  # noqa: BLE001 — an unreadable __file__ path is not a miss
                pass
        # H3: each contract-named export must be present under getattr (closes the
        # stub-module evasion — resolves but the export is absent/lazy/a no-op).
        absent: set[str] = set()
        for name in names:
            if not name or name == "*":
                continue
            if not hasattr(mod, name):
                absent.add(name)
                unresolved.append({
                    "raw": raw, "module": module, "name": name,
                    "reason": _clip(
                        f"module '{module}' resolves but export '{name}' is absent "
                        "(stub/partial module — the import contract is unmet)"),
                })
        # #826: the SIGNATURE layer — each contract callable must accept the arity the
        # oracle CALLS it with (built-wrong-signature is the B4n2 park; #822 only proved
        # the name resolves). Probe, don't invoke: bind sentinels to inspect.signature.
        for sig in (t.get("signatures") or []):
            if not isinstance(sig, dict):
                continue
            cname = str(sig.get("name", ""))
            if not cname or cname in absent:
                continue  # already named absent by H3 → don't double-report
            obj = getattr(mod, cname, _MISSING)
            if obj is _MISSING:
                # A callable named only in the signature contract (an `import m; m.f()`
                # form whose `f` was not in `names`) that the module does not provide.
                unresolved.append({
                    "raw": raw, "module": module, "name": cname,
                    "reason": _clip(
                        f"module '{module}' resolves but contract callable '{cname}' is "
                        "absent (the acceptance test calls it)"),
                })
                continue
            mismatch = _check_callable_arity(obj, sig)
            if mismatch is not None:
                unresolved.append({
                    "raw": raw, "module": module, "name": cname,
                    "reason": _clip(mismatch),
                })
    return {"ok": len(unresolved) == 0, "unresolved": unresolved[:_MAX_UNRESOLVED],
            "probed": probed, "skipped": skipped}


def build_node_probe_script(targets: list[dict], out_path: "str | Path") -> str:
    """Emit a ``node:`` ESM probe that dynamic-imports each first-party specifier
    (resolution) and checks each contract-named export (presence), writing its verdict
    JSON to *out_path*. The caller writes this to a ``.mjs`` file in the ORACLE'S OWN
    directory and runs it with ``node`` — so every relative specifier resolves exactly
    as the node oracle resolves it (H4, node twin). Deterministic: targets + out path
    are embedded as JSON literals (JSON is valid JS; any special char is JSON-escaped,
    so no specifier content can restructure the script)."""
    node_targets = [
        {"raw": str(t.get("raw", "") or ""),
         "spec": str(t.get("spec", "") or ""),
         "names": [str(n) for n in (t.get("names") or [])],
         "callables": [str(n) for n in (t.get("callables") or [])]}
        for t in targets if str(t.get("spec", "") or "")
    ]
    targets_json = json.dumps(node_targets, ensure_ascii=True)
    out_json = json.dumps(str(out_path), ensure_ascii=True)
    return (
        "import { writeFileSync } from 'node:fs';\n"
        f"const TARGETS = {targets_json};\n"
        f"const OUT = {out_json};\n"
        "const unresolved = [];\n"
        "for (const t of TARGETS) {\n"
        "  let ns;\n"
        "  try {\n"
        "    ns = await import(t.spec);\n"
        "  } catch (e) {\n"
        "    const code = (e && e.code) || (e && e.message) || 'error';\n"
        "    unresolved.push({ raw: t.raw, spec: t.spec, reason: "
        "\"specifier '\" + t.spec + \"' does not resolve (\" + code + \")\" });\n"
        "    continue;\n"
        "  }\n"
        "  for (const name of (t.names || [])) {\n"
        "    if (!name || name === '*') continue;\n"
        "    if (ns[name] === undefined) {\n"
        "      unresolved.push({ raw: t.raw, spec: t.spec, name, reason: "
        "\"module '\" + t.spec + \"' resolves but export '\" + name + \"' is absent\" });\n"
        "    }\n"
        "  }\n"
        # #826 node twin (cheap + sound): a contract callable that resolves must BE a
        # function — arity via fn.length is unreliable (rest/default params), so only the
        # typeof check fires; a non-function where the oracle calls it is a named delta.
        "  for (const name of (t.callables || [])) {\n"
        "    if (!name || name === '*') continue;\n"
        "    const val = name === 'default' ? ns.default : ns[name];\n"
        "    if (val !== undefined && typeof val !== 'function') {\n"
        "      unresolved.push({ raw: t.raw, spec: t.spec, name, reason: "
        "\"contract callable '\" + name + \"' resolves but is not a function\" });\n"
        "    }\n"
        "  }\n"
        "}\n"
        "writeFileSync(OUT, JSON.stringify({ ok: unresolved.length === 0, unresolved }));\n"
        "process.exit(unresolved.length === 0 ? 0 : 1);\n"
    )


def _main(argv: "list[str] | None" = None) -> int:
    """Python-probe CLI: read the targets JSON, resolve them, write the verdict JSON to
    ``--out``, and exit 0 (all resolved) / 1 (unresolved) / 2 (machinery error).

    The verdict is written to a FILE (never stdout): a probed module's own import-time
    ``print`` would otherwise corrupt a stdout-parsed verdict. stdout carries only a
    short human line for the run log."""
    parser = argparse.ArgumentParser(prog="python -m shared.fleet.import_probe")
    parser.add_argument("--targets", required=True, help="path to the targets JSON file")
    parser.add_argument("--repo", required=True, help="the integrated repo root")
    parser.add_argument("--out", required=True, help="path to write the verdict JSON")
    args = parser.parse_args(argv)
    try:
        targets = json.loads(Path(args.targets).read_text(encoding="utf-8"))
        if not isinstance(targets, list):
            raise ValueError("targets JSON is not a list")
    except Exception as exc:  # noqa: BLE001 — a bad targets file is a machinery failure
        _write_verdict(args.out, {"ok": None, "unresolved": [],
                                  "error": f"could not read targets: {type(exc).__name__}"})
        print(f"import-probe: could not read targets: {type(exc).__name__}")
        return 2
    verdict = probe_python_targets(targets, args.repo)
    _write_verdict(args.out, verdict)
    n = len(verdict.get("unresolved", []))
    print(f"import-probe: probed={verdict.get('probed', 0)} unresolved={n} "
          f"ok={verdict.get('ok')}")
    if verdict.get("ok") is None:
        return 2
    return 0 if verdict.get("ok") else 1


def _write_verdict(out_path: str, verdict: dict) -> None:
    try:
        Path(out_path).write_text(json.dumps(verdict), encoding="utf-8")
    except OSError:
        pass


if __name__ == "__main__":
    sys.exit(_main())
