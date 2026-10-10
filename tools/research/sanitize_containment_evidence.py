"""Copy raw containment-evidence files into the published bundle with the operator's identifiers replaced.

Run:  python tools/research/sanitize_containment_evidence.py SRC DST [--domain S-1-5-21-a-b-c ...]

The replacements are exactly the ones the bundle's CHANGES.md documents, so the bundle gate
(tests/security/test_containment_evidence_bundle.py) recounts them: the user name and the machine name become
``_OPERATOR_`` and ``_MACHINE_`` (case-insensitive, everywhere); each real account-domain SID prefix becomes one of the
two shape-valid placeholder domains (relative ids kept); JSON files are re-serialised (indent 2, UTF-8 without BOM) with
``text`` / ``completion`` / ``body`` strings cut to 100 characters plus the marker. Text files are written LF (the bundle
folder is pinned ``eol=lf``). Nothing else is changed: a number, a timestamp or a verdict never is.

The user and machine names come from the environment of the machine that produced the data (USERNAME, COMPUTERNAME),
never from this file, so the script itself carries no identifier the gate forbids. Real SID domains are read from the
local accounts unless ``--domain`` names them. The script refuses to overwrite a destination file that differs from
what it would write unless ``--force`` is given, so a re-run is a check.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

USER_PH, MACH_PH = "_OPERATOR_", "_MACHINE_"
PH_DOMAINS = ("1000000001-1000000002-1000000003", "1000000004-1000000005-1000000006")
CUT = 100
MARKER = "...[truncated to 100 chars]"
TEXT_SUFFIXES = {".ps1", ".py", ".cmd", ".md", ".txt", ".json", ".sha256"}
SID_DOMAIN_RE = re.compile(r"S-1-5-21-(\d+-\d+-\d+)-\d+")


def local_sid_domains() -> list[str]:
    """Account-domain prefixes of the local accounts (read with PowerShell; empty when that is unavailable)."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Get-LocalUser | ForEach-Object { $_.SID.Value }"],
            capture_output=True, text=True, timeout=60, check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    found: list[str] = []
    for m in SID_DOMAIN_RE.finditer(out):
        if m.group(1) not in found:
            found.append(m.group(1))
    return found


def cut_model_text(value: object) -> object:
    if isinstance(value, dict):
        out: dict = {}
        for k, v in value.items():
            if k in ("text", "completion") and isinstance(v, str) and len(v) > CUT:
                out[k] = v[:CUT] + MARKER
            elif k == "body" and isinstance(v, str):
                try:
                    out[k] = json.dumps(cut_model_text(json.loads(v)))
                except ValueError:
                    out[k] = v[:CUT] + MARKER if len(v) > CUT else v
            else:
                out[k] = cut_model_text(v)
        return out
    if isinstance(value, list):
        return [cut_model_text(v) for v in value]
    return value


def sanitize_text(text: str, user: str, machine: str, domains: list[str]) -> str:
    text = re.sub(re.escape(user), USER_PH, text, flags=re.IGNORECASE)
    if machine:
        text = re.sub(re.escape(machine), MACH_PH, text, flags=re.IGNORECASE)
    for i, dom in enumerate(domains):
        text = text.replace(f"S-1-5-21-{dom}-", f"S-1-5-21-{PH_DOMAINS[i % len(PH_DOMAINS)]}-")
    return text


def render(src: Path, user: str, machine: str, domains: list[str]) -> bytes:
    raw = src.read_bytes()
    text = raw.decode("utf-8-sig").replace("\r\n", "\n")
    if src.suffix == ".json":
        obj = cut_model_text(json.loads(text))
        text = json.dumps(obj, indent=2, ensure_ascii=False) + "\n"
    text = sanitize_text(text, user, machine, domains)
    return text.encode("utf-8")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("src", type=Path)
    ap.add_argument("dst", type=Path)
    ap.add_argument("--domain", action="append", default=None, help="real SID domain prefix a-b-c (repeatable)")
    ap.add_argument("--force", action="store_true", help="overwrite destination files that differ")
    ap.add_argument("--user", default=os.environ.get("USERNAME", ""))
    ap.add_argument("--machine", default=os.environ.get("COMPUTERNAME", ""))
    a = ap.parse_args(argv)
    if not a.user:
        print("no user name (USERNAME unset and --user not given)", file=sys.stderr)
        return 2
    domains = a.domain or local_sid_domains()
    if len(domains) > len(PH_DOMAINS):
        print(f"{len(domains)} SID domains found but only {len(PH_DOMAINS)} placeholders exist: name them with --domain", file=sys.stderr)
        return 2
    files = [a.src] if a.src.is_file() else sorted(p for p in a.src.rglob("*") if p.is_file())
    rc = 0
    for src in files:
        if src.suffix.lower() not in TEXT_SUFFIXES:
            print(f"skip (not a text type): {src}")
            continue
        rel = src.name if a.src.is_file() else src.relative_to(a.src)
        dst = a.dst / rel
        want = render(src, a.user, a.machine, domains)
        if dst.exists() and dst.read_bytes().replace(b"\r\n", b"\n") == want:
            print(f"unchanged: {dst}")
            continue
        if dst.exists() and not a.force:
            print(f"DIFFERS (use --force to overwrite): {dst}")
            rc = 1
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(want)
        print(f"written: {dst}")
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
