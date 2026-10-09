"""Path-scoped doctrine files under .claude/rules/: parsing, trigger matching, splicing (#1700).

One definition shared by the delivery hook (scripts/hooks/rules_inject.py), the rules-corpus
extractor (scripts/extract_rules_corpus.py) and their tests. Stdlib only: the hook runs under
``python -I -S``.

A rules file is YAML frontmatter followed by exactly one doctrine section in CLAUDE.md's tag
register. The frontmatter grammar is deliberately narrower than YAML so that a file this
parser accepts is one Claude Code also reads as intended:

    ---
    paths:
      - "<glob>"
    x-blarai-tools:
      - '<regex on the tool name>'
    x-blarai-commands:
      - '<regex on a Bash/PowerShell command>'
    ---

``paths`` (double-quoted entries) is the only key Claude Code reads; it loads the file when
the session reads or edits a matching path. Claude Code ignores the ``x-blarai-*`` keys, which
only the delivery hook reads (single-quoted entries, so a regex backslash is literal in YAML
too). Anthropic documents that frontmatter which fails to parse is IGNORED and the file then
loads unconditionally, so every deviation from this grammar raises RulesFileError rather than
degrading into an always-loaded file.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

PATHS_KEY = "paths"
TOOLS_KEY = "x-blarai-tools"
COMMANDS_KEY = "x-blarai-commands"
KNOWN_KEYS = (PATHS_KEY, TOOLS_KEY, COMMANDS_KEY)
_QUOTE_FOR = {PATHS_KEY: '"', TOOLS_KEY: "'", COMMANDS_KEY: "'"}
_TAG_OPEN = re.compile(r"^<(\w+)((?:\s[^>]*)?)>$")


class RulesFileError(Exception):
    """A rules file does not match the narrow grammar; it must not be loaded or delivered."""


@dataclass(frozen=True)
class RulesFile:
    name: str
    path: Path
    paths: tuple[str, ...]
    tools: tuple[re.Pattern[str], ...]
    commands: tuple[re.Pattern[str], ...]
    body: str
    top_tag: str


def parse_rules_text(name: str, raw: str, path: Path | None = None) -> RulesFile:
    """Parse one rules file; raise RulesFileError on any deviation from the grammar."""
    lines = raw.replace("\r\n", "\n").split("\n")
    if not lines or lines[0] != "---":
        raise RulesFileError(f"{name}: first line must be '---' (frontmatter opener)")
    try:
        end = lines.index("---", 1)
    except ValueError:
        raise RulesFileError(f"{name}: frontmatter is not closed by '---'") from None
    fields: dict[str, list[str]] = {}
    key: str | None = None
    for n, line in enumerate(lines[1:end], start=2):
        if not line.startswith(" "):
            if not line.endswith(":") or line[:-1] not in KNOWN_KEYS:
                raise RulesFileError(f"{name}:{n}: expected one of {KNOWN_KEYS} followed by ':'")
            key = line[:-1]
            if key in fields:
                raise RulesFileError(f"{name}:{n}: duplicate key {key}")
            fields[key] = []
            continue
        q = _QUOTE_FOR[key] if key else '"'
        if key is None or not (line.startswith(f"  - {q}") and line.endswith(q) and len(line) > 6):
            raise RulesFileError(f"{name}:{n}: list entries are '  - {q}value{q}' under a key")
        value = line[5:-1]
        if q in value:
            raise RulesFileError(f"{name}:{n}: value contains its own quote character")
        if q == '"' and "\\" in value:
            raise RulesFileError(f"{name}:{n}: a backslash in a double-quoted YAML path is an escape")
        fields[key].append(value)
    paths = tuple(fields.get(PATHS_KEY, ()))
    if not paths:
        raise RulesFileError(f"{name}: 'paths' is required; a rules file without it loads in every session")
    own = f".claude/rules/{name}"
    if own not in paths:
        raise RulesFileError(f"{name}: 'paths' must list the file itself ({own})")
    try:
        tools = tuple(re.compile(p) for p in fields.get(TOOLS_KEY, ()))
        commands = tuple(re.compile(p) for p in fields.get(COMMANDS_KEY, ()))
    except re.error as exc:
        raise RulesFileError(f"{name}: bad regex: {exc}") from None
    body_lines = [l for l in lines[end + 1:]]
    while body_lines and not body_lines[-1]:
        body_lines.pop()
    if not body_lines:
        raise RulesFileError(f"{name}: no doctrine body after the frontmatter")
    m = _TAG_OPEN.match(body_lines[0])
    if not m or body_lines[-1] != f"</{m.group(1)}>":
        raise RulesFileError(f"{name}: body must be exactly one <section>...</section> block")
    return RulesFile(name=name, path=path or Path(own), paths=paths, tools=tools,
                     commands=commands, body="\n".join(body_lines), top_tag=m.group(1))


def load_rules(rules_dir: Path) -> list[RulesFile]:
    """Every *.md in rules_dir (non-recursive, sorted). A subdirectory or non-.md file raises:
    Claude Code discovers .md files recursively, so an unexpected file is unreviewed doctrine."""
    if not rules_dir.is_dir():
        raise RulesFileError(f"rules directory missing: {rules_dir}")
    out = []
    for p in sorted(rules_dir.iterdir()):
        if p.is_dir() or p.suffix != ".md":
            raise RulesFileError(f"unexpected entry in {rules_dir}: {p.name} (only flat *.md files)")
        out.append(parse_rules_text(p.name, p.read_text(encoding="utf-8"), p))
    if not out:
        raise RulesFileError(f"no rules files in {rules_dir}")
    return out


def glob_to_regex(glob: str) -> re.Pattern[str]:
    """Translate a Claude Code style glob (**, *, ?, {a,b}) to an anchored regex on '/' paths."""
    i, out = 0, []
    while i < len(glob):
        c = glob[i]
        if glob.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
            continue
        if glob.startswith("**", i):
            out.append(".*")
            i += 2
            continue
        if c == "*":
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "{":
            j = glob.index("}", i)
            out.append("(?:" + "|".join(re.escape(a) for a in glob[i + 1:j].split(",")) + ")")
            i = j + 1
            continue
        else:
            out.append(re.escape(c))
        i += 1
    return re.compile("".join(out) + r"\Z", re.I)


def normalise(path: str) -> str:
    return path.replace("\\", "/").strip().strip("'\"")


def _read_git_pointer(path: Path) -> str:
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise ValueError(f"empty git metadata file: {path}")
    return value


def checkout_roots(repo_root: Path) -> tuple[str, ...]:
    """Every checkout of the repository that holds this file: its primary working tree and
    each linked worktree, normcased and normalised.

    Read ONLY from the repository's own git metadata (`.git` or the `gitdir:` file it points
    to, `commondir`, and `worktrees/*/gitdir`), never from a path a tool call supplied. Any
    unreadable entry raises, so the caller reports a delivery failure instead of guessing."""
    dotgit = repo_root / ".git"
    if dotgit.is_file():
        pointer = _read_git_pointer(dotgit)
        if not pointer.startswith("gitdir:"):
            raise ValueError(f"{dotgit} is not a gitdir pointer")
        gitdir = Path(pointer[len("gitdir:"):].strip())
        common = (gitdir / _read_git_pointer(gitdir / "commondir")).resolve()
    else:
        common = dotgit.resolve()
    roots = {common.parent}
    worktrees = common / "worktrees"
    if worktrees.is_dir():
        for entry in sorted(worktrees.iterdir()):
            roots.add(Path(_read_git_pointer(entry / "gitdir")).parent)
    return tuple(sorted(os.path.normcase(os.path.normpath(str(r))) for r in roots))


def repo_relative(path: str, cwd: str, roots: tuple[str, ...]) -> str | None:
    """The path relative to the BlarAI checkout that contains it, or None.

    PURELY LEXICAL: no file is opened, stat'ed or resolved for a tool-call path. The hook
    runs in PreToolUse, before Claude Code's permission check, and touching an
    attacker-shaped path (//host/share, a mapped drive, a junction to a share) makes
    Windows authenticate to that host. So the path is normalised as text and compared with
    the known checkout roots; the longest containing root wins, which keeps a worktree
    nested inside the primary checkout distinct from it. A relative path joins cwd first.
    A path outside every checkout (the user's memory, a scratchpad, another repository) is
    not a BlarAI subject."""
    raw = posix_drive(normalise(path))
    if not raw:
        return None
    base = posix_drive(normalise(cwd))
    joined = os.path.normpath(raw if os.path.isabs(raw) else os.path.join(base, raw))
    full = os.path.normcase(joined)
    best = ""
    for r in roots:
        if (full == r or full.startswith(r.rstrip(os.sep) + os.sep)) and len(r) > len(best):
            best = r
    if not best or full == best:
        return None
    return joined[len(best.rstrip(os.sep)) + 1:].replace("\\", "/")


_POSIX_DRIVE = re.compile(r"^/(?:cygdrive/|mnt/)?([A-Za-z])(/|$)")


def posix_drive(path: str) -> str:
    """Git Bash / Cygwin / WSL spellings of a Windows drive path (/c/Users, /cygdrive/c,
    /mnt/c) as the drive path they name (C:/Users), on Windows only. Shell commands on this
    machine use these forms more than any other; left alone, they would join cwd as a
    relative path and match nothing."""
    if os.name != "nt":
        return path
    m = _POSIX_DRIVE.match(path)
    return f"{m.group(1).upper()}:/{path[m.end():]}" if m else path


def path_matches(rules: RulesFile, rel_path: str) -> bool:
    """True if a repo-relative path matches one of the file's globs (Claude Code semantics:
    globs are anchored at the project root)."""
    rel = normalise(rel_path)
    return bool(rel) and any(glob_to_regex(g).match(rel) for g in rules.paths)


def splice(claude_md: str, rules: list[RulesFile]) -> tuple[str, list[tuple[int, str]]]:
    """CLAUDE.md with every rules body inserted before the closing root tag.

    Returns the combined text and (first_line, source) pairs, so a record's 1-based line
    number maps back to the file that holds it: the last pair whose first_line <= line."""
    text = claude_md.replace("\r\n", "\n").rstrip("\n")
    lines = text.split("\n")
    if not lines or not lines[-1].startswith("</"):
        raise RulesFileError("CLAUDE.md does not end with its closing root tag")
    head, close = lines[:-1], lines[-1]
    sources = [(1, "CLAUDE.md")]
    for r in rules:
        sources.append((len(head) + 1, f".claude/rules/{r.name}"))
        head += r.body.split("\n")
    sources.append((len(head) + 1, "CLAUDE.md"))
    return "\n".join(head + [close]) + "\n", sources


def source_for(line: int, sources: list[tuple[int, str]]) -> str:
    found = sources[0][1]
    for first, src in sources:
        if first <= line:
            found = src
    return found
