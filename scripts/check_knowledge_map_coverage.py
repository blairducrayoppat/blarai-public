#!/usr/bin/env python
"""Knowledge-map coverage check (#1744).

Every study in docs/research/ must be either CITED in at least one
docs/research/KNOWLEDGE_MAP*.md file, or LISTED with a reason in
docs/research/knowledge_map_unmapped.yaml, so a new study cannot silently drop
out of the knowledge base.

What counts as a study (a DENY-list: everything is a study unless excluded):
  * every TRACKED top-level file or folder of docs/research (``git ls-files``),
    whatever its type; anything below depth 1 belongs to its top-level folder.
    An untracked draft is therefore invisible to the check; committing an
    uncited, unlisted study turns it red.  Outside a git repository (or when
    git is unavailable) the filesystem is scanned instead and the report says
    so.
  * Explicit exclusions, and only these:
      - the map files themselves: any .md file whose name starts KNOWLEDGE_MAP
        (case-insensitive; only .md files are read as maps, so any other
        KNOWLEDGE_MAP* file or folder is a study like any other);
      - knowledge_map_unmapped.yaml;
      - the folder ``fixtures``;
      - ``docset-manifest*.json``;
      - a folder ``<stem>_files`` ONLY when a sibling saved page
        ``<stem>.htm`` or ``<stem>.html`` exists (a browser asset folder);
      - everything below depth 1 (e.g. windows-containment-comparison-2026-10/
        sources/): the owning top-level folder is the unit.

What counts as a citation: the study's name appearing as a whole token in the
text of a tracked KNOWLEDGE_MAP*.md, with an acceptable path prefix: none,
``./``, ``../research/``, ``docs/research/`` or ``/docs/research/`` (any
number of leading ``./`` / ``../``).  A path under any OTHER directory with the
same basename does not count.  A folder is cited by its name, optionally
followed by ``/`` and a path that EXISTS inside it; a citation of a
non-existent child does not cover the folder.  Matching is case-insensitive
and applied after URL-decoding (%20), HTML-unescaping and backslash to slash.
Text in fenced code blocks (CommonMark rules: closing fence needs the same
character, at least the opening length, and no info string) and in HTML
comments is ignored.  An indented (4-space) block is NOT treated as code,
because nested lists in the maps are indented the same way: a citation there
counts.  Inline code spans count.

Unmapped list (docs/research/knowledge_map_unmapped.yaml): a restricted YAML
subset parsed by hand (standard library only)::

    unmapped:            # or:  unmapped: []
      - path: some-study.md
        reason: not yet mapped: batch 5 candidate     # >= 12 chars, no placeholder
        ticket: "#1750"                               # optional

``path`` is a top-level name.  A BOM, CRLF, ``- path:`` at the same indent as
``unmapped:`` and a trailing ``# comment`` are tolerated.  An entry whose file
is untracked is tolerated (it is simply not a study yet).

Exit codes: 0 all covered; 1 uncovered studies; 2 stale unmapped entries (the
file is gone, is cited, or is excluded by the rules above); 3 malformed input.
If several apply: 3 beats 1 beats 2.
Usage: python -I scripts/check_knowledge_map_coverage.py [--root REPO_ROOT]
"""
from __future__ import annotations

import argparse
import html
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

RESEARCH = Path("docs") / "research"
RESEARCH_GIT = "docs/research"
UNMAPPED_NAME = "knowledge_map_unmapped.yaml"
ALLOWED_KEYS = {"path", "reason", "ticket"}
MIN_REASON = 12
PLACEHOLDER_REASONS = {"x", "-", "test", "todo", "tbd", "n/a", "na", "none", "...",
                       "not applicable", "to be determined", "to be decided",
                       "placeholder text", "no reason given"}
DELIMS = " \t\r\n()[]`'\"<>|=,;"
PREFIX_OK = re.compile(r"(?:\./|\.\./)*(?:research/|/?docs/research/)?")


class Malformed(Exception):
    """Input the checker cannot trust (exit 3)."""


# --------------------------------------------------------------------------
# discovery
# --------------------------------------------------------------------------

def git_tracked(root: Path) -> list[str] | None:
    """Tracked paths under docs/research relative to it, or None if the root
    is not itself a git work tree root (caller falls back to the filesystem)."""
    try:
        top = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=60)
        if top.returncode != 0 or not os.path.samefile(top.stdout.strip(), root):
            return None
        ls = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--", RESEARCH_GIT],
                            capture_output=True, timeout=60)
        if ls.returncode != 0:
            return None
        out = []
        for p in ls.stdout.decode("utf-8").split("\0"):
            if p.startswith(RESEARCH_GIT + "/") and os.path.lexists(root / p):
                out.append(p[len(RESEARCH_GIT) + 1:])
        return out
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError):
        return None


def fs_listing(research: Path) -> list[str]:
    out = []
    for dirpath, _dirs, files in os.walk(research):
        for f in files:
            out.append(Path(dirpath, f).relative_to(research).as_posix())
    return out


class Unit:
    """A top-level entry of docs/research: a file, or a folder and its contents."""

    def __init__(self, name: str, is_dir: bool) -> None:
        self.name = name
        self.is_dir = is_dir
        self.children: set[str] = set()  # casefolded relative paths inside a folder


def build_units(rels: list[str]) -> dict[str, Unit]:
    units: dict[str, Unit] = {}
    for rel in rels:
        parts = rel.split("/")
        key = parts[0].casefold()
        if len(parts) == 1:
            units.setdefault(key, Unit(parts[0], False))
        else:
            u = units.setdefault(key, Unit(parts[0], True))
            for i in range(1, len(parts) + 1):
                u.children.add("/".join(parts[1:i]).casefold())
    return units


def is_excluded(u: Unit, units: dict[str, Unit]) -> bool:
    low = u.name.casefold()
    if (not u.is_dir) and u.name.upper().startswith("KNOWLEDGE_MAP") and low.endswith(".md"):
        return True
    if low == UNMAPPED_NAME:
        return True
    if u.is_dir and low == "fixtures":
        return True
    if not u.is_dir and low.startswith("docset-manifest") and low.endswith(".json"):
        return True
    if u.is_dir and low.endswith("_files"):
        stem = low[: -len("_files")]
        for ext in (".htm", ".html"):
            sib = units.get(stem + ext)
            if sib is not None and not sib.is_dir:
                return True
    return False


# --------------------------------------------------------------------------
# citation matching
# --------------------------------------------------------------------------

_FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_FENCE_CLOSE = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*$")


def strip_fences(text: str) -> str:
    """Drop fenced code blocks following CommonMark: the closing fence uses the
    same character, is at least as long as the opening one and has no info
    string; an unclosed fence runs to the end."""
    kept: list[str] = []
    fence: tuple[str, int] | None = None
    for line in text.splitlines():
        if fence is None:
            m = _FENCE_OPEN.match(line)
            if m and not (m.group(1)[0] == "`" and "`" in m.group(2)):
                fence = (m.group(1)[0], len(m.group(1)))
                continue
            kept.append(line)
        else:
            m = _FENCE_CLOSE.match(line)
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= fence[1]:
                fence = None
    return "\n".join(kept)


def prepare(text: str) -> str:
    text = strip_fences(text)
    text = re.sub(r"<!--.*?(?:-->|\Z)", " ", text, flags=re.DOTALL)
    text = unquote(html.unescape(text))
    return text.replace("\\", "/").casefold()


def is_cited(u: Unit, text: str) -> bool:
    """text must already be prepared (casefolded)."""
    pat = re.compile(re.escape(u.name.casefold()) + r"(?![\w-]|\.\w)")
    for m in pat.finditer(text):
        i = m.start()
        while i > 0 and text[i - 1] not in DELIMS:
            i -= 1
        if not PREFIX_OK.fullmatch(text[i:m.start()]):
            continue
        end = m.end()
        follows_slash = text[end:end + 1] == "/"
        if not u.is_dir:
            if follows_slash:
                continue
            return True
        if not follows_slash:
            return True
        j = end + 1
        while j < len(text) and text[j] not in DELIMS:
            j += 1
        rest = re.split(r"[#?]", text[end + 1:j], maxsplit=1)[0].rstrip("/.:!*")
        if not rest or rest in u.children:
            return True
    return False


# --------------------------------------------------------------------------
# unmapped list
# --------------------------------------------------------------------------

_HEADER = re.compile(r"^unmapped:[ \t]*(\[[ \t]*\])?[ \t]*(?:#.*)?$")
_ITEM = re.compile(r"^[ \t]*-[ \t]+(\w+):[ \t]*(.*)$")
_KV = re.compile(r"^[ \t]+(\w+):[ \t]*(.*)$")


def _scalar(val: str, n: int) -> str:
    v = val.strip()
    if v[:1] == '"':
        m = re.fullmatch(r'"((?:[^"\\]|\\.)*)"\s*(?:#.*)?', v)
        if not m:
            raise Malformed(f"line {n}: bad double-quoted value")
        return m.group(1).replace('\\"', '"').replace("\\\\", "\\")
    if v[:1] == "'":
        m = re.fullmatch(r"'((?:[^']|'')*)'\s*(?:#.*)?", v)
        if not m:
            raise Malformed(f"line {n}: bad single-quoted value")
        return m.group(1).replace("''", "'")
    if v.startswith("#"):
        return ""
    return re.sub(r"\s+#.*$", "", v)


def parse_unmapped(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise Malformed(f"{path.name} is missing")
    entries: list[dict[str, str]] = []
    cur: dict[str, str] | None = None
    seen_header = False
    empty_flow = False
    for n, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not seen_header:
            h = _HEADER.match(line)
            if not h:
                raise Malformed(f"line {n}: file must begin with 'unmapped:'")
            seen_header = True
            empty_flow = bool(h.group(1))
            continue
        if empty_flow:
            raise Malformed(f"line {n}: entries after 'unmapped: []'")
        m = _ITEM.match(line)
        k = _KV.match(line)
        if m:
            cur = {}
            entries.append(cur)
            key, val = m.group(1), m.group(2)
        elif k and cur is not None:
            key, val = k.group(1), k.group(2)
        else:
            raise Malformed(f"line {n}: cannot parse {stripped!r}")
        if key not in ALLOWED_KEYS:
            raise Malformed(f"line {n}: unknown key {key!r}")
        assert cur is not None
        if key in cur:
            raise Malformed(f"line {n}: duplicate key {key!r}")
        cur[key] = _scalar(val, n)
    if not seen_header:
        raise Malformed("empty file: no 'unmapped:' header")
    seen: set[str] = set()
    for e in entries:
        if not e.get("path"):
            raise Malformed("an entry has no path")
        p = e["path"].replace("\\", "/").rstrip("/")
        if "/" in p:
            raise Malformed(f"{p}: list the top-level study name, not a path inside it")
        reason = e.get("reason", "").strip()
        if not reason:
            raise Malformed(f"{p}: reason is missing or empty")
        if reason.casefold() in PLACEHOLDER_REASONS or len(reason) < MIN_REASON:
            raise Malformed(f"{p}: reason must be a real sentence of at least "
                            f"{MIN_REASON} characters, not a placeholder (got {reason!r})")
        if p.casefold() in seen:
            raise Malformed(f"{p}: listed twice")
        seen.add(p.casefold())
        e["path"] = p
    return entries


# --------------------------------------------------------------------------
# run
# --------------------------------------------------------------------------

def run(root: Path) -> int:
    research = root / RESEARCH
    try:
        if not research.is_dir():
            raise Malformed(f"{research} not found")
        rels = git_tracked(root)
        mode_note = ""
        if rels is None:
            rels = fs_listing(research)
            mode_note = ("NOTE: not a git repository (or git unavailable): scanned the "
                         "filesystem, so untracked drafts count as studies here.")
        units = build_units(rels)
        map_units = [u for u in units.values()
                     if not u.is_dir and u.name.upper().startswith("KNOWLEDGE_MAP")
                     and u.name.lower().endswith(".md")]
        if not map_units:
            raise Malformed("no KNOWLEDGE_MAP*.md files found")
        entries = parse_unmapped(research / UNMAPPED_NAME)
        text = "\n".join(prepare((research / u.name).read_text(encoding="utf-8"))
                         for u in sorted(map_units, key=lambda x: x.name))
    except (Malformed, UnicodeDecodeError, OSError) as exc:
        print(f"MALFORMED INPUT: {exc}")
        return 3

    studies = [u for k, u in sorted(units.items()) if not is_excluded(u, units)]
    study_keys = {u.name.casefold() for u in studies}
    cited = {u.name.casefold() for u in studies if is_cited(u, text)}
    listed = {e["path"].casefold(): e for e in entries}

    uncovered = [u for u in studies
                 if u.name.casefold() not in cited and u.name.casefold() not in listed]
    stale: list[tuple[str, str]] = []
    for key, e in listed.items():
        p = e["path"]
        if not (research / p).exists():
            stale.append((p, "the file or folder no longer exists"))
        elif key in cited:
            stale.append((p, "now cited in a knowledge map; remove it from the list"))
        elif key in units and key not in study_keys:
            stale.append((p, "is tracked but excluded from the study rules; remove it"))
    n_listed = len([k for k in listed if k in study_keys and k not in cited])

    if mode_note:
        print(mode_note)
    print(f"Knowledge-map coverage: {len(studies)} studies found in docs/research/")
    print(f"  cited in a KNOWLEDGE_MAP*.md: {len(cited)}")
    print(f"  listed as unmapped (with reason): {n_listed}")
    if uncovered:
        print(f"\n{len(uncovered)} study(ies) neither cited in a knowledge map nor listed in {UNMAPPED_NAME}:")
        for u in uncovered:
            hint = ""
            if not u.is_dir and not u.name.lower().endswith((".md", ".html")):
                hint = "  (unrecognised file type: still a study)"
            print(f"  - {u.name}{hint}")
        print("Fix: cite each in a KNOWLEDGE_MAP*.md card, or add it to the list with a reason.")
    if stale:
        print(f"\n{len(stale)} stale entry(ies) in {UNMAPPED_NAME}:")
        for p, why in stale:
            print(f"  - {p}: {why}")
    if uncovered:
        return 1
    if stale:
        return 2
    print("\nOK: every study is cited or listed.")
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="Knowledge-map coverage check")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    args = ap.parse_args(argv)
    return run(Path(args.root))


if __name__ == "__main__":
    sys.exit(main())
