#!/usr/bin/env python3
"""Generate a ``--require-hashes`` hash-pinned lock from a version-pinned lock.

Supply-chain integrity control for BlarAI's runtime dependency set (#560 b1).

BlarAI already commits a version-pinned reproduction lock
(``requirements.2026.2.1.lock.txt`` — the exact resolved venv, gate-locked by
``tests/security/test_dependency_truth.py``). Version pins are
*version-containment*, not *supply-chain integrity*: a compromised build of an
*allowed* version installs silently (lesson 71). This script derives the
hash-pinned companion — ``requirements.<ver>.hashed.lock.txt`` — carrying a
``--hash=sha256:`` for every distribution file of each pinned version, so a
fresh ``pip install --require-hashes`` reproduces the set tamper-evidently and
a swapped artifact fails closed.

DEV-SIDE TOOL. It reaches the public PyPI JSON API to read the *already
published* SHA-256 digests PyPI records for each pinned release — it downloads
no packages, installs nothing, and never touches the runtime ``.venv``. Run it
with any system Python (stdlib only); it is not runtime code and is not
imported by anything the runtime loads.

Un-hashable entries (local ``-e`` editables and ``git+``/URL VCS installs)
CANNOT appear in a ``--require-hashes`` file — pip rejects the whole file if
they do. They are emitted as a documented, commented exclusion block (pinned by
VCS ref / local path, not by hash) rather than dropped silently, so the two
locks remain reconcilable.

Usage::

    python scripts/generate_hashed_lock.py \
        requirements.2026.2.1.lock.txt \
        requirements.2026.2.1.hashed.lock.txt

Exit non-zero if any ``name==version`` line resolves to zero published
digests — a silent gap in a supply-chain control is a defect, not a warning.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date

_PYPI_JSON = "https://pypi.org/pypi/{name}/{version}/json"
_PYPI_JSON_PKG = "https://pypi.org/pypi/{name}/json"
_PIN_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9.!+*]+)$")
_TIMEOUT = 30
_WORKERS = 8


def _normalize(name: str) -> str:
    """PEP 503 distribution-name normalization (for the PyPI URL fallback)."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _get_json(url: str) -> dict | None:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def _hashes_for(name: str, version: str) -> list[str]:
    """Sorted, de-duplicated sha256 digests for every file of name==version.

    Tries the exact version endpoint, then the PEP 503-normalized name, then
    the package-level ``releases`` map — covering the name-form differences
    ``pip freeze`` can emit versus PyPI's canonical routing.
    """
    data = _get_json(_PYPI_JSON.format(name=name, version=version))
    if data is None and _normalize(name) != name:
        data = _get_json(_PYPI_JSON.format(name=_normalize(name), version=version))
    files: list[dict] = []
    if data is not None:
        files = data.get("urls", []) or []
    if not files:
        pkg = _get_json(_PYPI_JSON_PKG.format(name=_normalize(name)))
        if pkg is not None:
            files = pkg.get("releases", {}).get(version, []) or []
    digests = {
        f["digests"]["sha256"]
        for f in files
        if f.get("digests", {}).get("sha256")
    }
    return sorted(digests)


class Entry:
    __slots__ = ("name", "version", "hashes")

    def __init__(self, name: str, version: str) -> None:
        self.name = name
        self.version = version
        self.hashes: list[str] = []


def _classify(lock_text: str) -> tuple[list[Entry], list[str]]:
    """Split a version-pinned lock into hashable pins and un-hashable lines."""
    pins: list[Entry] = []
    unhashable: list[str] = []
    pending_comment: str | None = None
    for raw in lock_text.splitlines():
        line = raw.strip()
        if not line:
            pending_comment = None
            continue
        if line.startswith("#"):
            # A `pip freeze` note preceding an editable line ("# Editable
            # install with no version control ..."). Keep it with the entry.
            pending_comment = line
            continue
        m = _PIN_RE.match(line)
        if m:
            pins.append(Entry(m.group(1), m.group(2)))
            pending_comment = None
            continue
        # Editable (-e ...) or VCS/URL ("name @ git+...") — un-hashable.
        if pending_comment:
            unhashable.append(pending_comment)
            pending_comment = None
        unhashable.append(line)
    return pins, unhashable


def _render(
    pins: list[Entry], unhashable: list[str], source_name: str
) -> str:
    lines: list[str] = [
        "# BlarAI runtime dependency HASH-PINNED lock (--require-hashes).",
        "#",
        f"# GENERATED from {source_name} by scripts/generate_hashed_lock.py on",
        f"# {date.today().isoformat()}. DO NOT hand-edit — regenerate at each",
        "# substrate ceremony when the version-pinned lock is refreshed.",
        "#",
        "# This is the SUPPLY-CHAIN INTEGRITY companion to the version-pinned",
        "# reproduction lock: identical version set, plus a --hash=sha256: for",
        "# every published distribution file of each pinned version. A fresh",
        "#   pip install --require-hashes -r <this file>",
        "# reproduces the set tamper-evidently; a substituted artifact whose",
        "# digest is not listed fails the install closed. This file is DORMANT",
        "# groundwork (#560 b1): committed, gate-checked, and NOT wired into any",
        "# boot or install path. Enabling --require-hashes at install time is a",
        "# separate, LA-gated step.",
        "#",
        "# The leading --require-hashes makes the file self-enforcing: pip",
        "# refuses any entry that lacks a hash, so the control cannot silently",
        "# decay to a plain version pin.",
        "--require-hashes",
        "",
    ]
    for e in sorted(pins, key=lambda x: (_normalize(x.name), x.version)):
        lines.append(f"{e.name}=={e.version} \\")
        for i, h in enumerate(e.hashes):
            suffix = " \\" if i < len(e.hashes) - 1 else ""
            lines.append(f"    --hash=sha256:{h}{suffix}")
    if unhashable:
        lines += [
            "",
            "# ---------------------------------------------------------------",
            "# UN-HASHABLE ENTRIES — present in the version-pinned lock but",
            "# structurally incompatible with --require-hashes (pip rejects a",
            "# hashes file that contains an editable or a VCS/URL requirement).",
            "# Recorded here for reconciliation; each is pinned by its VCS ref",
            "# or local path in the version-pinned lock, NOT by content hash.",
            "# None is a declared runtime dependency in pyproject.toml (they are",
            "# dev/build-conversion toolchain and a co-resident non-BlarAI",
            "# editable project). They are intentionally NOT installed by a",
            "# --require-hashes reproduction of the runtime set.",
            "# ---------------------------------------------------------------",
        ]
        lines += [f"#   {u}" for u in unhashable]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source", help="version-pinned lock (input)")
    ap.add_argument("output", help="hash-pinned lock (output)")
    args = ap.parse_args(argv)

    with open(args.source, encoding="utf-8") as fh:
        pins, unhashable = _classify(fh.read())

    print(
        f"[hashed-lock] {len(pins)} pinned dists, "
        f"{len(unhashable)} un-hashable line(s) excluded",
        file=sys.stderr,
    )

    def fill(e: Entry) -> Entry:
        e.hashes = _hashes_for(e.name, e.version)
        return e

    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        list(pool.map(fill, pins))

    missing = [f"{e.name}=={e.version}" for e in pins if not e.hashes]
    for e in sorted(pins, key=lambda x: _normalize(x.name)):
        print(
            f"[hashed-lock] {e.name}=={e.version}: {len(e.hashes)} sha256",
            file=sys.stderr,
        )
    if missing:
        print(
            "[hashed-lock] ERROR: no published sha256 for:\n  "
            + "\n  ".join(missing),
            file=sys.stderr,
        )
        return 1

    source_name = args.source.replace("\\", "/").rsplit("/", 1)[-1]
    with open(args.output, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(_render(pins, unhashable, source_name))
    print(f"[hashed-lock] wrote {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
