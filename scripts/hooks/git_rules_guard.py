#!/usr/bin/env python
# enforces-rule: critical_rules.git-has-no-human-safety-net -- git add -A and commit-on-main halves; destructive verbs are the external hook
# enforces-rule: git_discipline.shared_tree.no-git-add-a-ever
# enforces-rule: git_discipline.absolute_rules.never-commit-work-directly-to-main
"""PreToolUse guard for two CLAUDE.md git rules that otherwise rest on memory.

(Rule ids from docs/governance/rules-corpus.yaml.)

Scope: BlarAI repositories only. A git command whose resolved repository's top-level (or
git common dir parent) holds a CLAUDE.md containing `blarai_project_instructions` is
guarded; a repository that is positively not BlarAI passes untouched; a scope that cannot
be determined for a repository under a BlarAI tree is blocked.

Blocks, for Bash and PowerShell tool calls:
  1. Blanket staging: `git add|stage` with -A/--all/-u/--update/.|*|:/|:/*|:(top) (long
     options matched by unique-prefix abbreviation too), `git commit -a|--all|-am`, and a
     `git commit` whose only pathspec is blanket.
  2. `git commit` on main/master, except a COMPANION commit: nothing but COMPANION_ALLOWLIST
     paths are staged, the command stages nothing itself and carries no pathspec. There is
     no merge exception: MERGE_HEAD/MERGE_MODE are files a session can write, so they are
     never trusted. Work lands on main by `git merge --no-ff <branch>` (never fast-forward);
     a conflict is resolved by merging main INTO the feature branch, on the branch, and then
     merging the branch into main with `git merge --no-ff`.
  3. State drift: a commit that shares a call with any branch/HEAD/index-changing git
     operation, or with GIT_DIR/GIT_WORK_TREE/GIT_INDEX_FILE (inline, exported, or in the
     hook process environment), because the guard reads repository state at hook time.
  4. Wrapped and built forms: git behind any wrapper token (env, nice, timeout, xargs, sudo,
     eval, `bash -c`, `pwsh -c`, heredoc or pipe to a shell, backticks, `$(...)`), git aliases
     whose expansion is blanket staging or a commit, and any add/stage/commit argument or
     subcommand that is an unresolved expansion (variable, substitution, brace, splat,
     xargs stdin): those cannot be checked, so they are blocked.
  5. Switching the git-native pre-commit hook off (scripts/hooks/git_native_pre_commit.py):
     `commit --no-verify`/`-n`, `merge --no-verify`, `git -c core.hooksPath=...`,
     `--config-env`, `git config` touching core.hooksPath, GIT_CONFIG_COUNT/PARAMETERS.

Hook contract (Claude Code PreToolUse): JSON on stdin (tool_name, tool_input.command, cwd);
exit 2 blocks the call and feeds stderr to the model; any other exit lets it proceed.

Fail direction: CLOSED. Exit 1 or any code other than 2 lets the tool call proceed, so every
fault path ends in exit 2: unparseable text, unterminated quotes/heredocs/`$(`/`${`, invalid
JSON or UTF-8, a RecursionError/MemoryError/timeout, nesting beyond MAX_DEPTH, a failing git
subprocess or alias lookup, git missing from PATH. The only allows on a fault are tool names
other than Bash/PowerShell and commands proven unable to run git (no "git" even with quotes
and escapes squeezed out, no expansion/eval/source/invoke syntax). The settings.json wrapper
also maps a crashed or missing interpreter or script to a block.

Escape hatch: the operator sets BLARAI_GIT_RULES_OVERRIDE=<reason> in the environment of the
Claude Code process, by hand. Each override it permits is appended to the override log
(BLARAI_GIT_RULES_OVERRIDE_LOG, default ~/.claude/logs/git_rules_override.log).

Limits: cherry-pick, revert, am and commit-tree commits and ref updates (`push .`,
`fetch .`, `branch -f`) are not covered as commits; programs and scripts that run git
internally (make, python, .sh files, shell functions or aliases defined earlier) are not
seen. tests/security/test_git_rules_guard_differential.py checks the parser against what
real bash and pwsh pass to git. A backstop to discipline, not an adversarial boundary.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ENABLED = True
SHELL_TOOLS = {"Bash": "bash", "PowerShell": "pwsh"}
DRIFT_ENV_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS")

try:  # one definition of branches, scope marker, companion allowlist, override log
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import rules_common
    from rules_common import (  # noqa: F401
        COMPANION_ALLOWLIST, OVERRIDE_ENV, OVERRIDE_LOG_ENV, PROTECTED_BRANCHES, SCOPE_MARKER,
    )
except BaseException:  # noqa: BLE001 - a guard that cannot load its definitions must block
    sys.stderr.write("BLOCKED by the git-rules guard: scripts/hooks/rules_common.py cannot be "
                     "imported; restore it with git checkout.\n")
    sys.stderr.flush()
    os._exit(2)

_SKIP_WORDS = {
    "then", "do", "else", "elif", "if", "while", "until", "!", "time", "command", "exec",
    "builtin", "nohup", "sudo", "env", "call", "&",
}
_INERT_HEADS = {
    "echo", "printf", "grep", "egrep", "fgrep", "rg", "ag", "cat", "ls", "head", "tail", "wc",
    "man", "help", "which", "where", "whereis", "type", "write-output", "write-host",
    "select-string", "sls", "findstr", "get-content", "gc", "get-help", "get-command", "gcm",
    "less", "more", "diff", "sed", "awk", "tee",
}
_SHELL_HEADS = {"bash", "sh", "zsh", "dash", "ksh", "pwsh", "powershell", "cmd"}
_EVAL_HEADS = {"eval", "iex", "invoke-expression", "start-process", "invoke-command", "icm"}
_CD_WORDS = {"cd", "pushd", "chdir", "set-location", "sl", "push-location"}
_BUILTIN_SUBS = frozenset(
    "add am archive bisect blame branch bundle checkout cherry cherry-pick clean clone commit "
    "config describe diff fetch format-patch gc grep init log ls-files ls-remote ls-tree merge "
    "merge-base mv notes pull push range-diff read-tree rebase reflog remote reset restore "
    "revert rev-list rev-parse rm shortlog show show-ref sparse-checkout stash status "
    "submodule switch symbolic-ref tag update-ref update-index version worktree stage "
    "commit-tree checkout-index cat-file diff-tree for-each-ref count-objects fsck help "
    "var whatchanged apply".split()
)
_READ_ONLY_SUBS = frozenset(
    "status log diff show branch fetch blame describe grep ls-files ls-tree ls-remote "
    "merge-base rev-parse rev-list shortlog show-ref tag remote config reflog cat-file "
    "diff-tree for-each-ref count-objects fsck help version var push clone init bundle "
    "archive bisect notes submodule sparse-checkout gc clean update-index".split()
)
_STATE_SUBS = frozenset(
    "checkout switch reset restore symbolic-ref update-ref merge pull rebase cherry-pick "
    "revert am read-tree".split()
)
_BRANCH_STATE_OPTS = {"-f", "--force", "-m", "-M", "--move", "-c", "-C", "--copy"}
_GIT_GLOBAL_VALUE_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}

_ADD_LONG = (
    "--dry-run --verbose --interactive --patch --auto-advance --unified= --inter-hunk-context= "
    "--edit --force --update --renormalize --intent-to-add --all --ignore-removal --refresh "
    "--ignore-errors --ignore-missing --sparse --chmod= --pathspec-from-file= "
    "--pathspec-file-nul --no-dry-run --no-verbose --no-interactive --no-patch "
    "--no-auto-advance --no-edit --no-force --no-update --no-renormalize --no-intent-to-add "
    "--no-all --no-ignore-removal --no-refresh --no-ignore-errors --no-ignore-missing "
    "--no-sparse --no-chmod --no-pathspec-from-file --no-pathspec-file-nul"
).split()
_COMMIT_LONG = (
    "--quiet --verbose --file= --author= --date= --message= --reedit-message= "
    "--reuse-message= --fixup= --squash= --reset-author --trailer= --signoff --template= "
    "--edit --cleanup= --status --gpg-sign --all --include --interactive --patch --unified= "
    "--inter-hunk-context= --only --no-verify --dry-run --short --branch --ahead-behind "
    "--porcelain --long --null --amend --no-post-rewrite --untracked-files "
    "--pathspec-from-file= --pathspec-file-nul --verify --post-rewrite --no-quiet "
    "--no-verbose --no-file --no-author --no-date --no-message --no-reedit-message "
    "--no-reuse-message --no-fixup --no-squash --no-reset-author --no-trailer --no-signoff "
    "--no-template --no-edit --no-cleanup --no-status --no-gpg-sign --no-all --no-include "
    "--no-interactive --no-patch --no-only --no-dry-run --no-short --no-branch "
    "--no-ahead-behind --no-porcelain --no-long --no-null --no-amend --no-untracked-files "
    "--no-pathspec-from-file --no-pathspec-file-nul --allow-empty --allow-empty-message"
).split()
_ADD_BLANKET_LONG = {"--all", "--update", "--no-ignore-removal"}
_COMMIT_VALUE_LONG = {o[:-1] for o in _COMMIT_LONG if o.endswith("=")} - {"--unified", "--inter-hunk-context"}
_COMMIT_VALUE_LONG |= {"--unified", "--inter-hunk-context"}
_COMMIT_SHORT_VALUE_CHARS = "mFCct"
_BLANKET_PATHSPEC_RE = re.compile(r"^(?:\./?|\./\*|\*{1,2}|:/(?:\*|\.)?|:\(top\)(?:\*|\.)?)$")
_LOOSE_GIT_RE = re.compile(r"\bgit(?:\.exe)?\b[^\n;|&]{0,200}?\b(?:add|stage|commit)\b", re.I)
_HEREDOC_RE = re.compile(r"<<-?[ \t]*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
_PS_HERESTRING_RE = re.compile(r"@(['\"])[ \t]*\r?\n.*?\r?\n\1@", re.DOTALL)
_SHELL_BEFORE_HEREDOC_RE = re.compile(
    r"(?:^|[\s;&|(])(?:bash|sh|zsh|dash|pwsh|powershell)(?:\.exe)?(?:[ \t]+-\S+)*[ \t]*$"
)
_MSYS_DRIVE_RE = re.compile(r"^/([A-Za-z])(?:/|$)")
_DRIFT_TEXT_RE = re.compile(r"GIT_(?:DIR|WORK_TREE|INDEX_FILE|CONFIG_COUNT|CONFIG_PARAMETERS|CONFIG_KEY_\d+)", re.I)

SEPARATE_CALLS = "run the state change and the commit in separate calls"

MAX_DEPTH = 8  # nesting of $(...), `...`, bash -c payloads, heredoc-to-shell; deeper is blocked
MAX_COMMAND_CHARS = 1_000_000  # a longer command that could touch git is blocked
BUDGET_SECONDS = 8.0  # whole-analysis wall clock; the hook timeout (20 s) fails OPEN, ours blocks
GIT_CALL_TIMEOUT = 3.0
_RISKY_RE = re.compile(
    r"[$`&\x00]|\b(?:eval|source|iex|invoke-\w+|start-process|icm)\b|\\x|\\u|\\[0-7]{3}", re.I
)
_deadline: list[float] = [0.0]


def could_touch_git(cmd: str) -> bool:
    """False only for text proven unable to run git: no "git" even with quotes/escapes
    squeezed out, and no unresolved-expansion, eval/source/invoke or encoding syntax."""
    low = cmd.lower()
    if "git" in low or "git" in re.sub(r"[\s'\"\\`^]", "", low):
        return True
    return bool(_RISKY_RE.search(cmd))


def _tick() -> None:
    if time.monotonic() > _deadline[0]:
        raise Violation("budget", f"analysis exceeded {BUDGET_SECONDS:.0f}s; refusing (fail-closed).")


class Unparseable(Exception):
    """The command mentions git but cannot be analysed with certainty."""


class Violation(Exception):
    def __init__(self, rule: str, message: str) -> None:
        super().__init__(message)
        self.rule = rule
        self.message = message


@dataclass
class Inv:
    """One git invocation found in a command."""
    dir: str | None
    sub: str
    args: list[str]
    drift: bool = False
    aliases: dict = field(default_factory=dict)
    piped_args: bool = False
    hooks_override: str = ""


# ---- tokenising ---------------------------------------------------------------------------
def strip_heredocs(cmd: str, shell: str) -> tuple[str, list[str]]:
    """Remove heredoc bodies / PowerShell here-strings. Returns (text, bodies fed to a shell)."""
    bodies: list[str] = []
    if shell == "pwsh":
        cmd = _PS_HERESTRING_RE.sub('""', cmd)
    pos = 0
    while True:
        _tick()
        m = _HEREDOC_RE.search(cmd, pos)
        if not m:
            return cmd, bodies
        tag = m.group(2)
        line_end = cmd.find("\n", m.end())
        if line_end == -1:
            pos = m.end()
            continue
        offset = line_end + 1
        found = None
        while offset <= len(cmd):
            nl = cmd.find("\n", offset)
            end = len(cmd) if nl == -1 else nl
            if cmd[offset:end].strip() == tag:
                found = end
                break
            if nl == -1:
                break
            offset = nl + 1
        if found is None:
            pos = m.end()  # not a real heredoc (e.g. "<< word" in prose)
            continue
        line_start = cmd.rfind("\n", 0, m.start()) + 1
        if _SHELL_BEFORE_HEREDOC_RE.search(cmd[line_start:m.start()]):
            bodies.append(cmd[line_end + 1:found])
        cmd = cmd[:line_end] + cmd[found:]
        pos = line_end


DYN = "\x00"  # marks an expansion the guard cannot resolve (variable, substitution, brace)
_VAR_RE = re.compile(r"\$(?:\{[^}]*\}|[A-Za-z_][A-Za-z0-9_:]*|[0-9@*#?!$-])")
_ANSI_SIMPLE = {"n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "e": "\x1b", "E": "\x1b",
                "f": "\f", "v": "\v", "\\": "\\", "'": "'", '"': '"', "?": "?"}


def _match_paren(text: str, i: int) -> int:
    """Index of the ')' matching the '(' at text[i]; quote-aware. Raises Unparseable."""
    depth, j, n = 0, i, len(text)
    while j < n:
        c = text[j]
        if c == "\\":
            j += 2
            continue
        if c == "'":
            k = text.find("'", j + 1)
            if k == -1:
                raise Unparseable("unbalanced quote")
            j = k
        elif c == '"':
            j += 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            if j >= n:
                raise Unparseable("unbalanced quote")
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return j
        j += 1
    raise Unparseable("unbalanced parenthesis")


def _ansi_c(text: str, i: int) -> tuple[str, int]:
    """Decode $'...' starting at the quote text[i]=="'"; returns (value, index after)."""
    out, j, n = [], i + 1, len(text)
    while j < n and text[j] != "'":
        c = text[j]
        if c != "\\" or j + 1 >= n:
            out.append(c)
            j += 1
            continue
        e = text[j + 1]
        if e in _ANSI_SIMPLE:
            out.append(_ANSI_SIMPLE[e])
            j += 2
        elif e == "x":
            m = re.match(r"[0-9A-Fa-f]{1,2}", text[j + 2:])
            out.append(chr(int(m.group(), 16)) if m else "\\x")
            j += 2 + (len(m.group()) if m else 0)
        elif e in "01234567":
            m = re.match(r"[0-7]{1,3}", text[j + 1:])
            out.append(chr(int(m.group(), 8) & 0xFF))
            j += 1 + len(m.group())
        elif e in "uU":
            m = re.match(r"[0-9A-Fa-f]{1,8}" if e == "U" else r"[0-9A-Fa-f]{1,4}", text[j + 2:])
            out.append(chr(int(m.group(), 16)) if m else "\\" + e)
            j += 2 + (len(m.group()) if m else 0)
        else:
            out.append("\\" + e)
            j += 2
    if j >= n:
        raise Unparseable("unbalanced quote")
    return "".join(out), j + 1


def _expansion_at(cmd: str, i: int, shell: str, substs: list[str]) -> int | None:
    """If an expansion starts at cmd[i], record any inner command and return the end index."""
    c = cmd[i]
    if c == "$" and cmd[i + 1:i + 2] == "(":
        j = _match_paren(cmd, i + 1)
        substs.append(cmd[i + 2:j])
        return j + 1
    if c == "$":
        m = _VAR_RE.match(cmd, i)
        if m is None and cmd[i + 1:i + 2] == "{":
            raise Unparseable("unterminated ${")
        return m.end() if m else None
    if c == "`" and shell == "bash":
        j = cmd.find("`", i + 1)
        if j == -1:
            raise Unparseable("unbalanced backtick")
        substs.append(cmd[i + 1:j])
        return j + 1
    return None


def split_segments(cmd: str, shell: str) -> tuple[list[list[str]], list[str]]:
    """Quote-aware split into command segments of unquoted tokens, plus the inner text of
    every command/process substitution. Unresolvable expansions become DYN in the token.
    Raises Unparseable."""
    segments: list[list[str]] = []
    substs: list[str] = []
    tokens: list[str] = []
    cur: list[str] = []
    has = False
    quote = ""
    i, n = 0, len(cmd)
    esc = "`" if shell == "pwsh" else "\\"
    seps = "\n;&|{}()" if shell == "pwsh" else "\n;&|()"

    def flush_tok() -> None:
        nonlocal cur, has
        if has:
            tokens.append("".join(cur))
        cur, has = [], False

    def flush_seg() -> None:
        nonlocal tokens
        flush_tok()
        if tokens:
            segments.append(tokens)
        tokens = []

    while i < n:
        if not i & 1023:
            _tick()
        c = cmd[i]
        if quote:
            if c == quote and shell == "pwsh" and cmd[i + 1:i + 2] == quote:
                cur.append(quote)  # PowerShell: '' inside '...' and "" inside "..." is a literal quote
                i += 2
                continue
            if c == quote:
                quote = ""
            elif quote == '"' and (c == "$" or (c == "`" and shell == "bash")):
                end = _expansion_at(cmd, i, shell, substs)
                if end is None:
                    cur.append(c)
                else:
                    cur.append(DYN)
                    i = end
                    continue
            elif c == esc and quote == '"' and i + 1 < n and (
                cmd[i + 1] in '"`$' if shell == "pwsh" else cmd[i + 1] in '"\\$`'
            ):
                cur.append(cmd[i + 1])
                i += 1
            else:
                cur.append(c)
            i += 1
            continue
        if c == "$" and shell == "bash" and cmd[i + 1:i + 2] == "'":
            val, i = _ansi_c(cmd, i + 1)
            cur.append(val)
            has = True
            continue
        if c in "$`" and (c == "$" or shell == "bash"):
            end = _expansion_at(cmd, i, shell, substs)
            if end is not None:
                cur.append(DYN)
                has = True
                i = end
                continue
        if shell == "pwsh" and c == "@" and not has and re.match(r"@[A-Za-z_(]", cmd[i:i + 2]):
            if cmd[i + 1] == "(":
                j = _match_paren(cmd, i + 1)
                substs.append(cmd[i + 2:j])
                i = j + 1
            else:
                m = re.compile(r"@[A-Za-z_][A-Za-z0-9_]*").match(cmd, i)
                i = m.end()
            cur.append(DYN)
            has = True
            continue
        if shell == "pwsh" and c == "(" and (tokens or has):
            j = _match_paren(cmd, i)
            substs.append(cmd[i + 1:j])
            cur.append(DYN)
            has = True
            i = j + 1
            continue
        if shell == "bash" and c in "<>" and cmd[i + 1:i + 2] == "(":
            j = _match_paren(cmd, i + 1)
            substs.append(cmd[i + 2:j])
            cur.append(DYN)
            has = True
            i = j + 1
            continue
        if shell == "bash" and c == "{" and not (not has and cmd[i + 1:i + 2] in ("", " ", "\t", "\n")):
            j = i + 1
            while j < n and cmd[j] not in "} \t\r\n;&|":
                j += 1
            if j < n and cmd[j] == "}" and ("," in cmd[i + 1:j] or ".." in cmd[i + 1:j]):
                cur.append(DYN)
                has = True
                i = j + 1
                continue
            cur.append(c)
            has = True
            i += 1
            continue
        if shell == "bash" and c == "}" and has:
            cur.append(c)
            i += 1
            continue
        if shell == "bash" and c in "{}":
            flush_seg()
            i += 1
            continue
        if c in "'\"":
            quote, has = c, True
        elif c == esc and i + 1 < n:
            nxt = cmd[i + 1]
            if nxt == "\n":
                i += 1
            else:
                cur.append(nxt)
                has = True
                i += 1
        elif c in " \t\r":
            flush_tok()
        elif shell == "pwsh" and c == "&" and not has and not tokens and cmd[i + 1:i + 2] in (" ", "\t"):
            cur.append("&")  # call operator, not a separator
            has = True
        elif c in seps:
            flush_seg()
        elif c == "#" and not has:
            while i < n and cmd[i] != "\n":
                i += 1
            continue
        else:
            cur.append(c)
            has = True
        i += 1
    if quote:
        raise Unparseable("unbalanced quote")
    flush_seg()
    return segments, substs


# ---- paths and repositories -----------------------------------------------------------------
def _norm_path(p: str) -> str:
    m = _MSYS_DRIVE_RE.match(p)
    if m:
        p = m.group(1).upper() + ":/" + p[m.end():]
    return p


def _resolve(base: str | None, target: str) -> str | None:
    if base is None:
        return None
    if not target or "$" in target or "`" in target or DYN in target or target == "-":
        return None
    target = os.path.expanduser(_norm_path(target))
    return os.path.normpath(os.path.join(base, target))


def _run_git(dir_: str, *args: str, input_text: str | None = None) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in DRIFT_ENV_VARS}
    remaining = _deadline[0] - time.monotonic()
    if remaining <= 0:
        raise Violation("budget", f"analysis exceeded {BUDGET_SECONDS:.0f}s; refusing (fail-closed).")
    return subprocess.run(
        ["git", "-C", dir_, *args], capture_output=True, text=True,
        timeout=min(GIT_CALL_TIMEOUT, remaining), env=env, input=input_text,
    )


_marker_in = rules_common.marker_in


_SCOPE_CACHE: dict[str, bool] = {}


def in_scope(dir_: str | None) -> bool:
    """True if dir_ is inside a BlarAI repository, False if positively not; raises if unknown."""
    if dir_ is None:
        raise Violation("scope-unknown", "cannot determine which repository this git command "
                        "targets (dynamic cd/-C/--git-dir path). Use a literal path.")
    if dir_ in _SCOPE_CACHE:
        return _SCOPE_CACHE[dir_]
    probe, existed = dir_, os.path.isdir(dir_)
    while not os.path.isdir(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    try:
        top = _run_git(probe, "rev-parse", "--show-toplevel")
        if top.returncode != 0:
            if "not a git repository" in top.stderr.lower():
                _SCOPE_CACHE[dir_] = False
                return False
            raise Violation("scope-unknown", f"cannot determine the repository of {dir_}: "
                            f"{top.stderr.strip()[:200]}")
        # Scope is read from HEAD, not from the working tree a session can edit; only an unborn
        # HEAD (no commit yet) falls back to the working-tree marker.
        scoped = rules_common.commit_scope(lambda a: _run_git(probe, *a))
        if scoped is None:
            scoped = _marker_in(Path(top.stdout.strip()))
    except (OSError, subprocess.SubprocessError) as exc:
        raise Violation("scope-unknown", f"cannot run git to scope {dir_} ({exc}).")
    if scoped and not existed:
        raise Violation("scope-unknown", f"the target directory {dir_} does not exist yet, so "
                        "its repository cannot be checked. Create it in an earlier call.")
    _SCOPE_CACHE[dir_] = scoped
    return scoped


def _branch(dir_: str) -> str:
    try:
        r = _run_git(dir_, "symbolic-ref", "-q", "--short", "HEAD")
    except (OSError, subprocess.SubprocessError) as exc:
        raise Violation("branch-unknown", f"cannot run git to read the branch ({exc}).")
    if r.returncode != 0 or not r.stdout.strip():
        raise Violation("branch-unknown", f"cannot determine the current branch in {dir_} "
                        "(detached HEAD or unreadable repository).")
    return r.stdout.strip()


def _staged_problems(dir_: str) -> tuple[list, list[str]]:
    try:
        return rules_common.staged_problems(lambda a, input=None: _run_git(dir_, *a, input_text=input))
    except (OSError, subprocess.SubprocessError, RuntimeError, ValueError) as exc:
        raise Violation("branch-unknown", f"cannot read the staged set ({exc}).")


_is_companion = rules_common.is_companion


# ---- option parsing -------------------------------------------------------------------------
def _long_candidates(opt: str, universe: list[str]) -> list[str]:
    """Candidates for a long option under git's unique-prefix abbreviation rule."""
    name = opt.split("=", 1)[0]
    names = [u.rstrip("=") for u in universe]
    if name in names:
        return [name]
    return [u for u in names if u.startswith(name)]


def _add_blanket(args: list[str]) -> str | None:
    only_paths = False
    for a in args:
        if DYN in a:
            return a.replace(DYN, "<expansion>")
        if only_paths:
            if _BLANKET_PATHSPEC_RE.match(a):
                return a
        elif a == "--":
            only_paths = True
        elif a.startswith("--"):
            if set(_long_candidates(a, _ADD_LONG)) & _ADD_BLANKET_LONG:
                return a
        elif a.startswith("-") and len(a) > 1:
            if "A" in a or "u" in a or any(ch in a for ch in "*?["):
                return a
        elif _BLANKET_PATHSPEC_RE.match(a):
            return a
    return None


@dataclass
class CommitFlags:
    blanket: str = ""
    dynamic: str = ""
    no_verify: str = ""
    allow_empty: bool = False
    positionals: list[str] = field(default_factory=list)


def _value_attached(a: str) -> bool:
    """True when a short-option cluster's expansion sits inside an attached option value."""
    for ch in a[1:]:
        if ch == DYN:
            return False
        if ch in _COMMIT_SHORT_VALUE_CHARS + "uS":
            return True
    return False


def _commit_flags(args: list[str]) -> CommitFlags:
    f = CommitFlags()
    i, only_paths = 0, False
    while i < len(args):
        a = args[i]
        if DYN in a and not f.dynamic and not only_paths:
            if a.startswith("--"):
                unresolved = DYN in a.split("=", 1)[0]
            elif a.startswith("-") and len(a) > 1:
                unresolved = not _value_attached(a)
            else:
                unresolved = True
            if unresolved:
                f.dynamic = a.replace(DYN, "<expansion>")
        elif DYN in a and not f.dynamic:
            f.dynamic = a.replace(DYN, "<expansion>")
        if only_paths:
            f.positionals.append(a)
        elif a == "--":
            only_paths = True
        elif a.startswith("--"):
            cands = _long_candidates(a, _COMMIT_LONG)
            if "--all" in cands:
                f.blanket = a
            if cands == ["--allow-empty"]:
                f.allow_empty = True
            if "--no-verify" in cands:
                f.no_verify = a
            if "=" not in a and len(cands) == 1 and cands[0] in _COMMIT_VALUE_LONG:
                i += 1
        elif a.startswith("-") and len(a) > 1:
            for j, ch in enumerate(a[1:], start=1):
                if ch in "*?[":
                    f.dynamic = a
                if ch == "a":
                    f.blanket = a
                if ch == "n":
                    f.no_verify = a
                if ch in _COMMIT_SHORT_VALUE_CHARS:
                    if j == len(a) - 1:
                        i += 1
                    break
                if ch in "uS":
                    break
        else:
            f.positionals.append(a)
        i += 1
    if not f.blanket and f.positionals and all(_BLANKET_PATHSPEC_RE.match(p) for p in f.positionals):
        f.blanket = " ".join(f.positionals)
    return f


# ---- collecting invocations -----------------------------------------------------------------
def _git_head(tok: str) -> bool:
    return tok.replace("\\", "/").rsplit("/", 1)[-1].lower() in ("git", "git.exe")


def _parse_git(tokens: list[str], j: int, dir_: str | None, drift: bool) -> Inv | None:
    i, gdir, aliases, hooks_override = j + 1, dir_, {}, ""
    while i < len(tokens) and tokens[i].startswith("-"):
        opt = tokens[i]
        if opt == "-C" and i + 1 < len(tokens):
            gdir = _resolve(gdir, tokens[i + 1])
            i += 2
        elif opt.startswith("-c") and len(opt) > 2 or opt == "-c":
            kv = opt[2:] if len(opt) > 2 else (tokens[i + 1] if i + 1 < len(tokens) else "")
            if kv.lower().startswith("alias.") and "=" in kv:
                k, v = kv.split("=", 1)
                aliases[k[6:]] = v
            if kv.lower().startswith("core.hookspath") or DYN in kv:
                hooks_override = kv
            i += 1 if len(opt) > 2 else 2
        elif opt.startswith("--config-env"):
            hooks_override = hooks_override or opt
            i += 2 if opt == "--config-env" else 1
        elif opt.startswith("--work-tree="):
            gdir = _resolve(gdir, opt.split("=", 1)[1])
            i += 1
        elif opt.startswith("--git-dir"):
            gdir = None
            i += 2 if opt == "--git-dir" else 1
        elif opt in _GIT_GLOBAL_VALUE_OPTS:
            i += 2
        else:
            i += 1
    if i >= len(tokens):
        return None
    return Inv(gdir, tokens[i], tokens[i + 1:], drift, aliases, hooks_override=hooks_override)


_WRAP_HEADS = {"env", "xargs", "sudo", "nice", "timeout", "nohup", "time", "command", "exec",
               "doas", "setsid", "stdbuf", "wsl", "parallel", "runas", "start", "ssh"}
_STDIN_ARG_HEADS = {"xargs", "parallel"}


def _flag_blanket(tokens: list[str]) -> bool:
    return any(
        (t.startswith("-") and not t.startswith("--") and "A" in t)
        or t.startswith(("--al", "--upd")) for t in tokens
    )


def collect(cmd: str, shell: str, cwd: str | None, invs: list[Inv], depth: int = 0) -> None:
    """Append every git invocation found in cmd to invs. Raises Unparseable / Violation."""
    _tick()
    if depth > MAX_DEPTH:
        if could_touch_git(cmd):
            raise Violation("depth-cap", f"commands nested more than {MAX_DEPTH} levels deep "
                            "cannot be checked; write the git command out directly.")
        return
    text, bodies = strip_heredocs(cmd, shell)
    segments, substs = split_segments(text, shell)
    dir_: str | None = _norm_path(cwd) if cwd else None
    drift = bool(_DRIFT_TEXT_RE.search(cmd))
    sub_shell = "bash" if shell == "bash" else "pwsh"
    for idx, tokens in enumerate(segments):
        orig_head = tokens[0].lower()
        tokens = _strip_prefix(tokens)
        if not tokens:
            continue
        head = tokens[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
        head = head[:-4] if head.endswith(".exe") else head
        if head in _CD_WORDS:
            rest = [t for t in tokens[1:] if t.lower() not in ("/d", "-path", "-literalpath")]
            dir_ = _resolve(dir_, rest[0]) if rest else os.path.expanduser("~")
            continue
        if head in _INERT_HEADS:
            continue
        dyn_n = sum(1 for t in tokens if DYN in t)
        if dyn_n and not any(_git_head(t) for t in tokens):
            wrapperish = head in _WRAP_HEADS or orig_head in _WRAP_HEADS
            if (any(t in ("add", "stage", "commit") for t in tokens[1:])
                    or (DYN in head and (dyn_n >= 2 or _flag_blanket(tokens[1:])))
                    or (wrapperish and dyn_n >= 2)):
                raise Violation("dynamic-command", "an unresolved variable or substitution may be "
                                "building a git command; call git directly with literal arguments.")
        if any(t.replace("\\", "/").rsplit("/", 1)[-1] == "install_git_hooks.py" for t in tokens) \
                and any(len(t) > 3 and "--uninstall".startswith(t) for t in tokens) and in_scope(dir_):
            raise Violation("hooks-disable", "`install_git_hooks.py --uninstall` switches the git-native "
                            "hooks off; the operator runs that by hand.")
        wrapper = head in _SHELL_HEADS or head in _EVAL_HEADS or head in _WRAP_HEADS or orig_head in _WRAP_HEADS
        if wrapper:
            joined = " ".join(tokens[1:])
            for t in tokens[1:]:
                if re.search(r"\s", t):
                    try:
                        collect(t, "bash" if head in ("bash", "sh", "zsh", "dash", "ksh") else sub_shell,
                                dir_, invs, depth + 1)
                    except Unparseable:
                        if could_touch_git(t):
                            raise
            if head in _EVAL_HEADS and _LOOSE_GIT_RE.search(joined):
                raise Violation("wrapped-git", f"`{head}` wraps git add/commit; run git directly.")
            if head in _SHELL_HEADS or head in _EVAL_HEADS:
                reads_stdin = not any(not t.startswith(("-", "/")) for t in tokens[1:])
                if reads_stdin and idx > 0:
                    prev = _strip_prefix(segments[idx - 1])
                    prev_head = prev[0].lower() if prev else ""
                    if prev_head in ("echo", "printf"):
                        collect(" ".join(prev[1:]), sub_shell, dir_, invs, depth + 1)
                    else:
                        raise Violation("wrapped-git", f"the input of `{head}` comes from another command; "
                                        "the commands it runs cannot be checked. Run git directly.")
        for j, t in enumerate(tokens):
            if _git_head(t):
                inv = _parse_git(tokens, j, dir_, drift)
                if inv:
                    inv.piped_args = head in _STDIN_ARG_HEADS or orig_head in _STDIN_ARG_HEADS
                    invs.append(inv)
                break
    for body in bodies:
        collect(body, "bash", dir_ if dir_ else cwd, invs, depth + 1)
    for inner in substs:
        try:
            collect(inner, sub_shell, dir_ if dir_ else cwd, invs, depth + 1)
        except Unparseable:
            if could_touch_git(inner):
                raise


def _strip_prefix(tokens: list[str]) -> list[str]:
    while tokens:
        t = tokens[0]
        if t.lower() in _SKIP_WORDS or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", t):
            tokens = tokens[1:]
        else:
            break
    return tokens


# ---- evaluation -----------------------------------------------------------------------------
def _expand_alias(inv: Inv, depth: int = 0) -> list[Inv]:
    sub = "add" if inv.sub == "stage" else inv.sub
    if sub in _BUILTIN_SUBS:
        return [Inv(inv.dir, sub, inv.args, inv.drift, inv.aliases, inv.piped_args, inv.hooks_override)]
    if depth > 3:
        raise Violation("alias", f"git alias '{sub}' nests more than 3 levels; refusing (fail-closed).")
    value = inv.aliases.get(sub)
    if value is None:
        if not in_scope(inv.dir):
            return [inv]
        try:
            r = _run_git(inv.dir, "config", "--get-regexp", r"^alias\.")
        except (OSError, subprocess.SubprocessError) as exc:
            raise Violation("alias", f"cannot read git aliases ({type(exc).__name__}); refusing (fail-closed).")
        for line in r.stdout.splitlines():
            key, _, val = line.partition(" ")
            if key.lower() == f"alias.{sub.lower()}":
                value = val
                break
    if value is None:
        return [inv]
    if value.startswith("!"):
        if _LOOSE_GIT_RE.search(value) or re.search(r"\b(?:add|commit)\b", value):
            raise Violation("alias", f"git alias '{sub}' runs a shell command that stages or "
                            "commits; call git add <path> / git commit directly.")
        return [inv]
    try:
        parts = shlex.split(value)
    except ValueError:
        raise Violation("alias", f"git alias '{sub}' cannot be parsed; refusing (fail-closed).")
    if not parts:
        return [inv]
    return _expand_alias(Inv(inv.dir, parts[0], parts[1:] + inv.args, inv.drift, inv.aliases,
                             inv.piped_args, inv.hooks_override), depth + 1)


def _is_state_op(inv: Inv) -> bool:
    if inv.sub in _STATE_SUBS:
        return True
    if inv.sub == "branch":
        return any(a in _BRANCH_STATE_OPTS or (a.startswith("-") and not a.startswith("--") and any(c in a for c in "fmMcC")) for a in inv.args)
    if inv.sub == "stash":
        return bool(inv.args) and inv.args[0] in ("pop", "apply")
    if inv.sub == "worktree":
        return bool(inv.args) and inv.args[0] in ("add", "remove")
    return False


_MAIN_ROUTE_SUBS = frozenset(("merge", "pull", "cherry-pick", "revert", "rebase", "am", "reset"))
_CONTINUATION = frozenset(("--abort", "--quit", "--continue", "--skip", "--edit-todo", "--show-current-patch"))


def _main_route_message(inv: Inv) -> str | None:
    """Why this command must not run while main/master is checked out, or None. These routes only
    fail at the ref update (reference-transaction hook), after git has already changed the work
    tree; refusing them here leaves the files untouched."""
    sub, args = inv.sub, inv.args
    if any(a in _CONTINUATION for a in args):
        return None
    if sub == "merge":
        if any(len(a) >= 6 and "--no-ff".startswith(a) for a in args) and "--ff-only" not in args and "--ff" not in args:
            return None
        return ("`git merge` on main must be `git merge --no-ff <branch>` (a fast-forward, `--ff-only`, "
                "`--ff` or `--squash` would change your files and then be refused at the ref update).")
    if sub == "pull":
        return ("`git pull` on main fetches and fast-forwards or merges; update main with "
                "`git merge --no-ff <branch>` instead.")
    if sub in ("cherry-pick", "revert", "rebase", "am"):
        return (f"`git {sub}` on main would put commits there without a reviewed branch; do it on a feature "
                "branch and land that with `git merge --no-ff <branch>`.")
    if sub == "reset" and any(a in ("--hard", "--keep") for a in args):
        return ("`git reset --hard/--keep` on main moves or rewrites main; to undo a blocked merge use "
                "`git reset --merge`.")
    return None


def evaluate(invs: list[Inv]) -> None:
    resolved: list[Inv] = []
    for inv in invs:
        resolved.extend(_expand_alias(inv))
    scoped_commits: list[tuple[Inv, CommitFlags]] = []
    moves_branch = any(i.sub in ("checkout", "switch", "worktree") for i in resolved)
    for inv in resolved:
        _tick()
        if inv.sub in _MAIN_ROUTE_SUBS and not moves_branch:
            msg = _main_route_message(inv)
            if msg and in_scope(inv.dir):
                try:
                    on_main = _branch(inv.dir) in PROTECTED_BRANCHES
                except Violation:
                    on_main = False  # detached or unreadable: not main, so not this rule
                if on_main:
                    raise Violation("main-route", msg)
        if DYN in inv.sub and in_scope(inv.dir):
            raise Violation("dynamic-subcommand", "the git subcommand comes from an unresolved "
                            "variable, substitution or brace expansion; write it out literally.")
        if inv.hooks_override and in_scope(inv.dir):
            raise Violation(
                "hooks-disable",
                f"`git -c {inv.hooks_override.lstrip('-')}` overrides core.hooksPath, which switches "
                "the git-native pre-commit guard off. Run git without it.",
            )
        if inv.sub == "config" and any(
                "core.hookspath" in a.lower() or "previoushookspath" in a.lower() or DYN in a
                for a in inv.args) \
                and in_scope(inv.dir):
            raise Violation("hooks-disable", "`git config` touching core.hooksPath would switch the "
                            "git-native pre-commit guard off; use scripts/install_git_hooks.py.")
        if inv.sub == "merge" and any(a == "--no-verify" for a in inv.args) and in_scope(inv.dir):
            raise Violation("no-verify", "`git merge --no-verify` skips the hooks; run it without.")
        if inv.sub in ("add", "commit") and inv.piped_args and in_scope(inv.dir):
            raise Violation("stdin-args", f"`git {inv.sub}` arguments come from stdin "
                            "(xargs/parallel), so they cannot be checked; name the paths.")
        if inv.sub == "add":
            bad = _add_blanket(inv.args)
            if bad and in_scope(inv.dir):
                raise Violation(
                    "blanket-add",
                    f"`git add {bad}` stages everything, including other sessions' untracked "
                    "files. Stage explicit paths: `git add <path> ...`.",
                )
        elif inv.sub == "commit":
            if inv.drift or any(v in os.environ for v in DRIFT_ENV_VARS):
                raise Violation(
                    "env-drift",
                    "GIT_DIR/GIT_WORK_TREE/GIT_INDEX_FILE is set (inline, exported, or in the "
                    "environment), so the guard cannot know which repository this commit "
                    "targets. Unset it and use `git -C <path>`.",
                )
            if not in_scope(inv.dir):
                continue
            flags = _commit_flags(inv.args)
            if flags.blanket:
                raise Violation(
                    "blanket-commit",
                    f"`git commit {flags.blanket}` commits every tracked change, including "
                    "other sessions' work. Stage explicit paths with `git add <path>`, then "
                    "`git commit`.",
                )
            if flags.dynamic:
                raise Violation(
                    "dynamic-arg",
                    f"`git commit` argument `{flags.dynamic}` is an unresolved expansion "
                    "(variable, substitution, brace or glob), so it cannot be checked; write "
                    "the arguments out literally.",
                )
            if flags.no_verify:
                raise Violation(
                    "no-verify",
                    f"`git commit {flags.no_verify}` skips the git-native pre-commit guard. "
                    "Commit without --no-verify / -n.",
                )
            scoped_commits.append((inv, flags))
    if not scoped_commits:
        return
    branches = [(inv, flags, _branch(inv.dir)) for inv, flags in scoped_commits]
    on_main = any(b in PROTECTED_BRANCHES for _, _, b in branches)
    for other in resolved:
        if other.sub == "commit":
            continue
        if _is_state_op(other) or (other.sub == "add" and on_main):
            raise Violation("state-drift", f"`git {other.sub}` shares a call with `git commit`; "
                            f"{SEPARATE_CALLS} (the guard reads repository state before the "
                            "command runs).")
    for inv, flags, branch in branches:
        if branch not in PROTECTED_BRANCHES:
            continue
        if flags.positionals:
            raise Violation("commit-on-main", f"`git commit` with pathspecs on '{branch}'. "
                            "Stage the files first, then run a bare `git commit`.")
        if flags.allow_empty:
            raise Violation("commit-on-main", f"`git commit --allow-empty` on '{branch}'.")
        changes, problems = _staged_problems(inv.dir)
        if changes and not problems:
            continue
        what = "nothing is staged" if not changes else "not a companion change: " + "; ".join(problems[:5])
        raise Violation(
            "commit-on-main",
            f"`git commit` on '{branch}': {what}. Work goes on a feature branch "
            "(`git checkout -b <branch>` or a worktree) and lands on main with `git merge --no-ff "
            "<branch>` (never fast-forward). To resolve a conflict, merge main INTO the feature "
            "branch first, on the branch. On main only a companion commit is allowed; companion "
            f"commits touch only: {', '.join(COMPANION_ALLOWLIST)} (plain data/prose files).",
        )


def analyze(cmd: str, shell: str, cwd: str | None) -> None:
    """Raise Violation or Unparseable; return None if every git invocation is permitted."""
    invs: list[Inv] = []
    collect(cmd, shell, cwd, invs)
    evaluate(invs)


# ---- hook entry -----------------------------------------------------------------------------
_log_override = rules_common.log_override


def _blocked_text(message: str) -> str:
    return (
        "BLOCKED by the git-rules guard (scripts/hooks/git_rules_guard.py; CLAUDE.md "
        f"git_discipline).\n{message}\n"
        f"Operator override (set by hand, logged): {OVERRIDE_ENV}=<reason>\n"
    )


def decide(raw: bytes) -> tuple[int, str]:
    """Hook decision for one stdin payload: (exit code, stderr text). Never raises.

    Exit 1 or any code other than 2 lets the tool call proceed, so every fault path here maps to
    2 for Bash/PowerShell input and to 0 only for tool names that are not shells.
    """
    _deadline[0] = time.monotonic() + BUDGET_SECONDS
    cmd, shell, cwd = "", None, None
    try:
        text = raw.decode("utf-8", errors="replace").lstrip("\ufeff")
        data = json.loads(text)
        if not isinstance(data, dict) or not isinstance(data.get("tool_input") or {}, dict):
            return 2, _blocked_text("hook input has an unexpected shape; refusing (fail-closed).")
        name = data.get("tool_name")
        shell = SHELL_TOOLS.get(name) if isinstance(name, str) else None
        if not ENABLED or shell is None:
            return 0, ""
        cmd = (data.get("tool_input") or {}).get("command") or ""
        cwd = data.get("cwd") or None
        if not isinstance(cmd, str) or (cwd is not None and not isinstance(cwd, str)):
            return 2, _blocked_text("hook input has an unexpected shape; refusing (fail-closed).")
    except BaseException as exc:  # noqa: BLE001 - fail closed on anything, incl. RecursionError
        return 2, _blocked_text(f"hook input is not valid JSON ({type(exc).__name__}); refusing (fail-closed).")
    rule, message = "", ""
    try:
        if len(cmd) > MAX_COMMAND_CHARS:
            if not could_touch_git(cmd):
                return 0, ""
            raise Violation("too-long", f"command longer than {MAX_COMMAND_CHARS} characters "
                            "cannot be checked; split it up.")
        analyze(cmd, shell, cwd)
        return 0, ""
    except Violation as v:
        rule, message = v.rule, v.message
    except BaseException as exc:  # noqa: BLE001 - parse faults, RecursionError, MemoryError, ...
        try:
            risky = could_touch_git(cmd)
        except BaseException:  # noqa: BLE001
            risky = True
        if not risky:
            return 0, ""
        kind = "cannot parse this command" if isinstance(exc, Unparseable) else \
            f"guard fault ({type(exc).__name__})"
        rule, message = ("unparseable" if isinstance(exc, Unparseable) else "guard-error"), \
            f"{kind}; refusing (fail-closed): {str(exc)[:200]}"
    reason = os.environ.get(OVERRIDE_ENV, "").strip()
    if reason:
        try:
            _log_override(reason, cmd, rule)
        except BaseException as exc:  # noqa: BLE001
            return 2, _blocked_text(f"{message}\nOverride set but the override log failed "
                                    f"({type(exc).__name__}); refusing.")
        return 0, f"git-rules guard OVERRIDDEN ({rule}): {reason}\n"
    return 2, _blocked_text(message)


def _emit(text: str) -> None:
    """Write to stderr without ever raising: an encoding error must not turn a block into an
    allow (an uncaught exception exits 1, which the hook contract treats as proceed)."""
    if not text:
        return
    try:
        stream = getattr(sys.stderr, "buffer", None)
        if stream is not None:
            stream.write(text.encode("utf-8", errors="replace"))
            stream.flush()
        else:
            sys.stderr.write(text.encode("ascii", errors="replace").decode("ascii"))
    except BaseException:  # noqa: BLE001
        pass


def main() -> None:
    try:
        raw = sys.stdin.buffer.read()
    except BaseException:  # noqa: BLE001
        _emit(_blocked_text("cannot read hook input; refusing (fail-closed)."))
        os._exit(2)
    try:
        code, text = decide(raw)
    except BaseException as exc:  # noqa: BLE001
        code, text = 2, _blocked_text(f"guard fault ({type(exc).__name__}); refusing (fail-closed).")
    _emit(text)
    try:
        sys.stderr.flush()
    except BaseException:  # noqa: BLE001
        pass
    os._exit(code)


if __name__ == "__main__":
    main()
