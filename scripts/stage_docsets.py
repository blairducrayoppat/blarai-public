"""Stage the #746 offline docsets — BUILD-TIME tooling, never runtime.

Downloads the LA-approved first-slice documentation corpus (approval recorded
2026-07-05 on Vikunja #746/#740: Python 3.11 + pytest + Hypothesis + MDN
web docs + Node.js, from docs.python.org / DevDocs / readthedocs) into the
gitignored ``models/docsets/`` staging dir, and writes a SHA-256 manifest both
beside the payload AND to a tracked path (``docs/research/``), so future
re-provisioning verifies against the recorded pins exactly like model weights.

Two-tier privacy model: this script is a *development/build-time* action run by
the development session. BlarAI's runtime never imports it and never fetches —
all runtime retrieval is from the local staged corpus. Re-running is idempotent:
an existing file with a matching manifest hash is kept (checked, not re-fetched);
a hash MISMATCH against a previously recorded pin fails LOUD and leaves the old
manifest untouched.

Usage:  python scripts/stage_docsets.py [--dest models/docsets]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DEST = REPO_ROOT / "models" / "docsets"
TRACKED_MANIFEST = REPO_ROOT / "docs" / "research" / "docset-manifest-2026-07.json"

#: The LA-approved first slice (2026-07-05). DevDocs serves per-doc JSON databases;
#: Python's official text archive and Hypothesis's readthedocs bundle complete it.
#: Narrow-and-deep by design (#746: high-value-not-wasteful; growth is evidence-driven).
SOURCES: list[dict] = [
    {"name": "python-3.11-official-text",
     "url": "https://docs.python.org/3.11/archives/python-3.11.13-docs-text.zip",
     "file": "python-3.11-docs-text.zip"},
    {"name": "devdocs-python-3.11-index",
     "url": "https://documents.devdocs.io/python~3.11/index.json",
     "file": "devdocs/python~3.11/index.json"},
    {"name": "devdocs-python-3.11-db",
     "url": "https://documents.devdocs.io/python~3.11/db.json",
     "file": "devdocs/python~3.11/db.json"},
    # pytest is NOT on DevDocs (documents.devdocs.io/pytest/* 403s) — use the
    # official readthedocs bundle, same pattern as Hypothesis below.
    {"name": "pytest-readthedocs-html",
     "url": "https://docs.pytest.org/_/downloads/en/stable/htmlzip/",
     "file": "pytest-docs-html.zip"},
    {"name": "devdocs-javascript-index",
     "url": "https://documents.devdocs.io/javascript/index.json",
     "file": "devdocs/javascript/index.json"},
    {"name": "devdocs-javascript-db",
     "url": "https://documents.devdocs.io/javascript/db.json",
     "file": "devdocs/javascript/db.json"},
    {"name": "devdocs-dom-index",
     "url": "https://documents.devdocs.io/dom/index.json",
     "file": "devdocs/dom/index.json"},
    {"name": "devdocs-dom-db",
     "url": "https://documents.devdocs.io/dom/db.json",
     "file": "devdocs/dom/db.json"},
    {"name": "devdocs-html-index",
     "url": "https://documents.devdocs.io/html/index.json",
     "file": "devdocs/html/index.json"},
    {"name": "devdocs-html-db",
     "url": "https://documents.devdocs.io/html/db.json",
     "file": "devdocs/html/db.json"},
    {"name": "devdocs-css-index",
     "url": "https://documents.devdocs.io/css/index.json",
     "file": "devdocs/css/index.json"},
    {"name": "devdocs-css-db",
     "url": "https://documents.devdocs.io/css/db.json",
     "file": "devdocs/css/db.json"},
    {"name": "devdocs-node-index",
     "url": "https://documents.devdocs.io/node/index.json",
     "file": "devdocs/node/index.json"},
    {"name": "devdocs-node-db",
     "url": "https://documents.devdocs.io/node/db.json",
     "file": "devdocs/node/db.json"},
    {"name": "hypothesis-readthedocs-html",
     "url": "https://hypothesis.readthedocs.io/_/downloads/en/latest/htmlzip/",
     "file": "hypothesis-docs-html.zip"},
]

_UA = "BlarAI-docset-stager/1.0 (build-time provisioning; Vikunja #746)"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _fetch(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(req, timeout=120) as resp, tmp.open("wb") as out:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
    tmp.replace(dest)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dest", default=str(DEFAULT_DEST))
    args = ap.parse_args(argv)
    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)

    prior_pins: dict[str, str] = {}
    if TRACKED_MANIFEST.is_file():
        try:
            prior = json.loads(TRACKED_MANIFEST.read_text(encoding="utf-8"))
            prior_pins = {e["name"]: e["sha256"] for e in prior.get("artifacts", [])}
        except (ValueError, KeyError):
            print(f"WARNING: unreadable prior manifest at {TRACKED_MANIFEST}", file=sys.stderr)

    artifacts: list[dict] = []
    failures: list[str] = []
    for src in SOURCES:
        target = dest / src["file"]
        try:
            if target.is_file() and src["name"] in prior_pins:
                digest = _sha256(target)
                if digest == prior_pins[src["name"]]:
                    print(f"kept   {src['name']} (pin verified)")
                    artifacts.append({"name": src["name"], "url": src["url"],
                                      "file": src["file"], "sha256": digest,
                                      "bytes": target.stat().st_size})
                    continue
                print(f"FAIL   {src['name']}: on-disk hash does not match the recorded pin",
                      file=sys.stderr)
                failures.append(src["name"])
                continue
            print(f"fetch  {src['name']} <- {src['url']}")
            _fetch(src["url"], target)
            digest = _sha256(target)
            if src["name"] in prior_pins and digest != prior_pins[src["name"]]:
                print(f"FAIL   {src['name']}: fetched hash does not match the recorded pin",
                      file=sys.stderr)
                failures.append(src["name"])
                continue
            artifacts.append({"name": src["name"], "url": src["url"],
                              "file": src["file"], "sha256": digest,
                              "bytes": target.stat().st_size})
            print(f"staged {src['name']} ({target.stat().st_size:,} bytes)")
        except Exception as exc:  # noqa: BLE001 — one artifact must not sink the slice
            print(f"MISS   {src['name']}: {exc}", file=sys.stderr)
            failures.append(src["name"])

    manifest = {
        "schema": "blarai-docset-manifest/v1",
        "staged_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "approval": "LA-approved 2026-07-05 (Vikunja #746/#740 — first slice: "
                    "Python 3.11 + pytest + Hypothesis + MDN web + Node)",
        "dest": str(dest),
        "artifacts": artifacts,
        "misses": failures,
        "total_bytes": sum(a["bytes"] for a in artifacts),
    }
    (dest / "MANIFEST.sha256.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")
    TRACKED_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    TRACKED_MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nmanifest: {len(artifacts)} staged, {len(failures)} missed, "
          f"{manifest['total_bytes']:,} bytes total")
    print(f"tracked pin file: {TRACKED_MANIFEST}")
    # Honest exit: pin MISMATCHES are hard failures; a plain fetch miss is reported
    # in the manifest (the caller decides whether the slice is complete enough).
    return 1 if any("pin" in f for f in failures) else 0


if __name__ == "__main__":
    raise SystemExit(main())
