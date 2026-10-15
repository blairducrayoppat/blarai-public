"""
Deterministic community-export scrub  —  the TRANSFORM half of the §6a control.
=============================================================================
Copies committed performance artifacts to a SEPARATE export dir, applying ONLY an
enumerated set of machine-local-path -> placeholder substitutions. It never touches
numbers, keys, units, or labels, and it never mutates the originals (read-only in,
new files out).

This is the SCRUB (the transform). It is deliberately kept INDEPENDENT from the
integrity gate `scripts/verify_community_scrub.py`, which adversarially checks the
result against the original. Do NOT merge the two — a scrub that self-certifies is
not a check; independence is the entire point.

The operator and host names are not embedded: the path patterns read them from the
machine and apply_subs also replaces any token identity_lock recognises by digest, so the
scrub holds under any account. Keep SUBSTITUTIONS in sync (independently) with the verifier.

Usage:
  python scripts/scrub_community_export.py --out-dir <dir> <file> [<file> ...]
  python scripts/scrub_community_export.py --out-dir <dir> --manifest <list.txt>

Every output is written under --out-dir with the source basename preserved. After
running this, run the verifier on every (original, scrubbed) pair; exit 0 required.
"""

from __future__ import annotations

import argparse
import getpass
import os
import platform
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import identity_lock as _il  # noqa: E402  (digest recognition of this machine's names; works under any account)

# Enumerated machine-local-path -> placeholder substitutions: the ONLY string changes
# the scrub is permitted to make. Most-specific FIRST. Patterns match the parsed file
# text, both slash styles, case-insensitive where noted. Defined here independently of
# the verifier on purpose (two implementations that must agree).
# A path separator in the file TEXT may be a single backslash, a JSON-escaped double
# backslash (`\\` in the on-disk text), or a forward slash. Match all three so the
# scrub works on raw JSON text (where separators are `\\`) AND plain text / Unix paths.
_SEP = r"(?:\\{1,2}|/)"
# The operator user name and the host name are read from the machine, never held as literals (gate lock: tests/security/test_no_host_identity_in_tree.py).
# Set USERNAME / COMPUTERNAME to scrub another machine's names.
_USER = re.escape(os.environ.get("USERNAME") or getpass.getuser())
_HOST = re.escape(os.environ.get("COMPUTERNAME") or platform.node())
SUBSTITUTIONS: list[tuple[str, str]] = [
    (rf"[A-Za-z]:{_SEP}Users{_SEP}{_USER}{_SEP}AppData{_SEP}Local{_SEP}Temp{_SEP}claude{_SEP}[^\"'\s]*", "<scratch>"),
    (rf"[A-Za-z]:{_SEP}Users{_SEP}{_USER}{_SEP}tools{_SEP}intel-ut[^\"'\s]*", "<ut-home>"),
    (rf"[A-Za-z]:{_SEP}Users{_SEP}{_USER}{_SEP}(?:blarai|BlarAI)", "<repo>"),
    (rf"[A-Za-z]:{_SEP}Users{_SEP}{_USER}", "<home>"),
    (rf"(?i)\b{_HOST}\b", "<host>"),
    (rf"(?i)\b{_USER}\b", "<user>"),
]


def apply_subs(text: str) -> tuple[str, int]:
    out = text
    n = 0
    for pat, repl in SUBSTITUTIONS:
        out, k = re.subn(pat, repl, out)
        n += k
    hosts, users = _il.find_hits(out.encode('utf-8', 'surrogatepass'))
    for tok in sorted(hosts, key=len, reverse=True):
        out, k = re.subn(re.escape(tok.decode()), '<host>', out, flags=re.IGNORECASE)
        n += k
    for tok in sorted(users, key=len, reverse=True):
        out, k = re.subn(r'(?<![A-Za-z])' + re.escape(tok.decode()) + r'(?![A-Za-z])', '<user>', out, flags=re.IGNORECASE)
        n += k
    return out, n


def main() -> int:
    ap = argparse.ArgumentParser(description="Deterministic community-export scrub (transform only).")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("files", nargs="*")
    ap.add_argument("--manifest", help="optional newline-delimited file list (# comments allowed)")
    args = ap.parse_args()

    files: list[str] = list(args.files)
    if args.manifest:
        for line in Path(args.manifest).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                files.append(line)
    if not files:
        print("FATAL: no input files given (pass files and/or --manifest)")
        return 2

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    total = 0
    for f in files:
        src = Path(f)
        if not src.is_file():
            print(f"[FAIL] missing input: {src}")
            return 2
        scrubbed, n = apply_subs(src.read_text(encoding="utf-8"))
        dst = out_dir / src.name
        dst.write_text(scrubbed, encoding="utf-8")
        total += n
        flag = "" if n else "  (clean — copied verbatim)"
        print(f"  {src.name}: {n} substitution(s) -> {dst}{flag}")

    print(f"\nScrubbed {len(files)} file(s); {total} total substitution(s). Originals untouched.")
    print("NEXT: verify_community_scrub.py on every (original, scrubbed) pair — exit 0 required.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
