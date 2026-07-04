"""
Verify a community-scrub: nothing sensitive leaked, NO measurement/label lost.
=============================================================================
The community-contribution phase publishes DERIVED COPIES of the performance
artifacts with machine-local paths genericized. This is the adversarial gate on
that transform. It NEVER mutates anything — it COMPARES an original against its
scrubbed copy and fails loud on either failure mode:

  (1) UNDER-scrub — a sensitive token survived in the scrubbed copy (a local
      absolute path, the username, the session scratch dir, a secret-shaped
      string). Hard fail. (Plus a softer WARN list for BlarAI-internal terms that
      should never appear in a hardware-perf artifact.)
  (2) OVER-scrub  — the scrub changed something it must NOT have. For JSON, every
      number / bool / null leaf, every dict key, and every array length MUST be
      byte-identical between original and scrubbed. THIS is what guarantees the
      measurements, labels, units, and structure are preserved. Only string
      *values* may differ, and only by a KNOWN local-path -> placeholder
      substitution; any other string change is reported.

Originals are the source of truth and are never written. Run this on every
artifact before it is published, IN ADDITION TO an independent human/agent review
(it cannot judge prose semantics — only structured-data integrity + residue).

INTERNAL TOOL — it embeds the local-path patterns (incl. the username). Do NOT
publish this script. Extend SUBSTITUTIONS / SENSITIVE_FAIL / WARN_INTERNAL for
your machine (hostname, etc.) before relying on it.

Usage:
  python scripts/verify_community_scrub.py --original <f.json> --scrubbed <f.json>
  python scripts/verify_community_scrub.py --original-dir <a> --scrubbed-dir <b>
Exit code 0 = PASS (safe to publish, integrity intact); non-zero = FAIL/needs review.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# --- Known local-path -> placeholder substitutions (the ONLY string changes the
#     scrub is allowed to make). Order: most-specific first. Patterns match the
#     PARSED string (single backslashes), case-insensitive, both slash styles. ---
SUBSTITUTIONS: list[tuple[str, str]] = [
    (r"[A-Za-z]:[\\/]Users[\\/]mrbla[\\/]AppData[\\/]Local[\\/]Temp[\\/]claude[\\/][^\"'\s]*", "<scratch>"),
    (r"[A-Za-z]:[\\/]Users[\\/]mrbla[\\/]tools[\\/]intel-ut[^\"'\s]*", "<ut-home>"),
    (r"[A-Za-z]:[\\/]Users[\\/]mrbla[\\/](?:blarai|BlarAI)", "<repo>"),
    (r"[A-Za-z]:[\\/]Users[\\/]mrbla", "<home>"),
    (r"\bmrbla\b", "<user>"),
]

# --- Residual scan: these MUST NOT survive in a scrubbed artifact (hard fail). ---
SENSITIVE_FAIL: list[tuple[str, str]] = [
    (r"mrbla", "username"),
    (r"[A-Za-z]:[\\/]Users", "windows user path"),
    (r"[A-Za-z]:\\", "windows absolute path (backslash)"),
    (r"AppData[\\/]Local", "appdata path"),
    (r"\.venv[\\/]", "venv path"),
    (r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "uuid (session/scratch)"),
    (r"(?i)\b(api[_-]?key|secret|token|password|bearer)\b\s*[:=]", "secret-shaped assignment"),
]

# --- Soft warnings: BlarAI-internal terms that should not appear in a public
#     hardware-perf artifact. Not auto-fail (avoid false positives); human-confirm. ---
WARN_INTERNAL: list[str] = [
    "BlarAI", "ADR-", "vsock", "policy_agent", "assistant_orchestrator",
    "Hyper-V", "USE-CASE", "air-gap", "air gap", "Vikunja",
]


def apply_subs(s: str) -> str:
    out = s
    for pat, repl in SUBSTITUTIONS:
        out = re.sub(pat, repl, out)
    return out


def deep_check(orig, scrub, path: str = "$") -> list[tuple[str, str]]:
    """Return a list of (json-path, problem). Empty list == structurally intact."""
    issues: list[tuple[str, str]] = []
    # numeric equivalence: treat 1 and 1.0 as equal, but otherwise exact
    if isinstance(orig, bool) or isinstance(scrub, bool):
        if orig != scrub or type(orig) is not type(scrub):
            issues.append((path, f"bool/value changed: {orig!r} -> {scrub!r}"))
        return issues
    if isinstance(orig, (int, float)) and isinstance(scrub, (int, float)):
        if float(orig) != float(scrub):
            issues.append((path, f"NUMBER CHANGED: {orig!r} -> {scrub!r}"))
        return issues
    if type(orig) is not type(scrub):
        issues.append((path, f"type changed: {type(orig).__name__} -> {type(scrub).__name__}"))
        return issues
    if isinstance(orig, dict):
        if set(orig) != set(scrub):
            removed, added = set(orig) - set(scrub), set(scrub) - set(orig)
            issues.append((path, f"KEYS changed: removed={sorted(removed)} added={sorted(added)}"))
        for k in orig:
            if k in scrub:
                issues += deep_check(orig[k], scrub[k], f"{path}.{k}")
    elif isinstance(orig, list):
        if len(orig) != len(scrub):
            issues.append((path, f"ARRAY LENGTH changed: {len(orig)} -> {len(scrub)}"))
        for i, (a, b) in enumerate(zip(orig, scrub)):
            issues += deep_check(a, b, f"{path}[{i}]")
    elif isinstance(orig, str):
        if orig != scrub:
            predicted = apply_subs(orig)
            if scrub != predicted:
                issues.append((path, f"UNEXPECTED string change: {orig!r} -> {scrub!r} "
                                     f"(known-scrub would give {predicted!r})"))
    else:  # None
        if orig != scrub:
            issues.append((path, f"value changed: {orig!r} -> {scrub!r}"))
    return issues


def residual_scan(text: str) -> tuple[list[str], list[str]]:
    fails, warns = [], []
    for pat, label in SENSITIVE_FAIL:
        for m in re.finditer(pat, text):
            snippet = text[max(0, m.start() - 20):m.start() + 40].replace("\n", " ")
            fails.append(f"{label}: …{snippet}…")
    for term in WARN_INTERNAL:
        if re.search(re.escape(term), text):
            warns.append(term)
    return fails, warns


def check_pair(original: Path, scrubbed: Path) -> bool:
    print(f"\n=== {original.name} -> {scrubbed.name} ===")
    ok = True
    is_json = original.suffix.lower() == ".json"
    if is_json:
        try:
            o = json.loads(original.read_text(encoding="utf-8"))
            s = json.loads(scrubbed.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"  [FAIL] could not parse JSON: {e}")
            return False
        issues = deep_check(o, s)
        if issues:
            ok = False
            print(f"  [FAIL] {len(issues)} integrity issue(s) — measurements/labels/structure NOT preserved:")
            for p, msg in issues[:40]:
                print(f"         {p}: {msg}")
        else:
            print("  [ok] structural integrity intact (all numbers/keys/units/array-lengths identical;")
            print("       only known local-path strings changed)")
    else:
        # text/script: every changed line must be explained by a known substitution
        o_lines = original.read_text(encoding="utf-8", errors="replace").splitlines()
        s_lines = scrubbed.read_text(encoding="utf-8", errors="replace").splitlines()
        if len(o_lines) != len(s_lines):
            ok = False
            print(f"  [FAIL] line count changed {len(o_lines)} -> {len(s_lines)} (text diff needs human review)")
        for i, (a, b) in enumerate(zip(o_lines, s_lines), 1):
            if a != b and apply_subs(a) != b:
                ok = False
                print(f"  [FAIL] line {i} changed beyond known scrub:\n         - {a!r}\n         + {b!r}")
        if ok:
            print("  [ok] every changed line explained by a known local-path substitution")
        print("  [note] non-JSON: structural check is line-based; still needs independent prose review")

    fails, warns = residual_scan(scrubbed.read_text(encoding="utf-8", errors="replace"))
    if fails:
        ok = False
        print(f"  [FAIL] {len(fails)} sensitive token(s) survived in the scrubbed copy:")
        for f in fails[:20]:
            print(f"         {f}")
    else:
        print("  [ok] no residual sensitive tokens (paths/username/uuid/secrets)")
    if warns:
        print(f"  [WARN] BlarAI-internal term(s) present — confirm intended: {sorted(set(warns))}")
    print(f"  => {'PASS' if ok else 'FAIL'}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description="Adversarial integrity gate for community-scrubbed artifacts.")
    ap.add_argument("--original")
    ap.add_argument("--scrubbed")
    ap.add_argument("--original-dir")
    ap.add_argument("--scrubbed-dir")
    args = ap.parse_args()

    pairs: list[tuple[Path, Path]] = []
    if args.original and args.scrubbed:
        pairs.append((Path(args.original), Path(args.scrubbed)))
    elif args.original_dir and args.scrubbed_dir:
        od, sd = Path(args.original_dir), Path(args.scrubbed_dir)
        for o in sorted(od.rglob("*")):
            if o.is_file():
                s = sd / o.relative_to(od)
                if s.exists():
                    pairs.append((o, s))
                else:
                    print(f"[WARN] no scrubbed counterpart for {o}")
    else:
        print("FATAL: pass --original/--scrubbed or --original-dir/--scrubbed-dir")
        return 2
    if not pairs:
        print("FATAL: no file pairs to check")
        return 2

    results = [check_pair(o, s) for o, s in pairs]
    n_pass = sum(results)
    print(f"\n=== SUMMARY: {n_pass}/{len(results)} PASS ===")
    if n_pass != len(results):
        print("DO NOT PUBLISH — integrity or residue check failed above.")
        return 1
    print("Structured-integrity + residue checks PASSED. Still require the independent")
    print("adversarial review + operator approval before publishing (see the handoff brief).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
