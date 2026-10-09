"""Deliver path-scoped doctrine (.claude/rules/*.md) to every agent that needs it (#1700).

Claude Code loads a rules file natively only when the MAIN session reads or edits a path its
`paths:` frontmatter names. Two gaps remain, both measured elsewhere before this was built
(57 subagent writes, 0 rule loads; shell writes bypass a Write/Edit trigger):

  * a subagent starts with a fresh context and is never told;
  * a shell command or an MCP tool call touches the subject without a Read/Write/Edit.

This PreToolUse hook closes both. For each tool call it collects trigger evidence (the file
path of Read/Write/Edit/NotebookEdit; every path-like token of a Bash/PowerShell command after
heredoc bodies are stripped, since a heredoc is data; the tool name; the command text), selects
the rules files whose `paths`, `x-blarai-tools` or `x-blarai-commands` match, and returns each
one not yet delivered to THIS agent (as `additionalContext`, or as the reason of a one-time
hold, below).

"This agent" is keyed by agent_id when present, else session_id. A subagent shares its
parent's session_id, transcript_path and prompt_id; only agent_id differs. Keying on anything
shared would mark a rule delivered to the parent as delivered to every child, silently.
A changed rules file (different sha256) is delivered again. SessionStart (startup, resume,
clear, compact) resets the session's own record, because compaction drops what was delivered.

A Write/Edit/MultiEdit/NotebookEdit that is this agent's first contact with a rules subject
is HELD ONCE: denied, with the rules file as the reason, so the rule arrives before the write
instead of with its result. The delivery is recorded first, so the re-issued call passes.

State is one marker file per (agent, rules file) holding the delivered sha256, so parallel
calls of one agent delivering different files never contend for a path.

Fail-loud, never silent and never blocking on its own failure: any internal failure (a rules file that does not
parse, an unreadable directory, a crash) is returned to the model as an explicit DOCTRINE
DELIVERY FAILED notice on every call until fixed, and logged. It does not block the tool call:
blocking every Read would also block the repair. tests/security/test_doctrine_rules.py keeps
broken rules files from reaching main.

Environment: BLARAI_RULES_INJECT_STATE_DIR (default ~/.claude/state/rules_inject),
BLARAI_RULES_INJECT_LOG (default ~/.claude/logs/rules_inject.log), BLARAI_RULES_DIR (default:
.claude/rules beside this script's repository; tests point it elsewhere), BLARAI_DOCTRINE_CHECKOUT
(the checkout the SessionStart lag check inspects; default: this script's repository).

SessionStart also warns when the checkout's doctrine lags main (#1703): a rule merged to main is
not loaded in a session whose checkout predates it. The check is `main`'s latest commit touching
CLAUDE.md, .claude/rules/, .claude/agents/ or .claude/settings.json being an ancestor of HEAD, read from the
repository's own refs through fixed git arguments, never from a tool call. Like the delivery, it
informs and never blocks, and a failure to decide is reported, not read as "in sync".
Limits: it compares against the checkout's LOCAL refs/heads/main (a clone with a stale main
reads in sync; worktrees share refs); each git call is capped at 3 s so four calls stay inside
the 15 s hook timeout in .claude/settings.json; a cherry-picked copy of main's commit reads as
lagging.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

PATH_TOOLS = {"Read": "file_path", "Write": "file_path", "Edit": "file_path",
              "MultiEdit": "file_path", "NotebookEdit": "notebook_path"}
SHELL_TOOLS = frozenset({"Bash", "PowerShell"})
STATE_TTL_S = 3 * 24 * 3600
# A file-writing call that is this agent's FIRST contact with a rules subject is held once
# (denied, with the rules as the reason), because PreToolUse additionalContext arrives with
# the RESULT: without the hold the write goes out uninformed and the rule arrives after it.
HOLD_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})
HOLD_PREFIX = ("HELD ONCE, NOT AN ERROR: this is your first write to a subject with binding BlarAI "
               "doctrine you have not been shown. Read it below, then re-issue the same tool call, "
               "corrected if the doctrine requires; it will not be held again.\n\n")
MAIN_REF = "refs/heads/main"
DOCTRINE_PATHS = ("CLAUDE.md", ".claude/rules", ".claude/settings.json", ".claude/agents")
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
_SPLIT = re.compile(r"[\s;&|()<>`=,]+")


def rules_dir() -> Path:
    env = os.environ.get("BLARAI_RULES_DIR")
    return Path(env) if env else HERE.parent.parent / ".claude" / "rules"


def state_dir() -> Path:
    env = os.environ.get("BLARAI_RULES_INJECT_STATE_DIR")
    return Path(env) if env else Path.home() / ".claude" / "state" / "rules_inject"


def log_path() -> Path:
    env = os.environ.get("BLARAI_RULES_INJECT_LOG")
    return Path(env) if env else Path.home() / ".claude" / "logs" / "rules_inject.log"


def doctrine_checkout() -> Path:
    env = os.environ.get("BLARAI_DOCTRINE_CHECKOUT")
    return Path(env) if env else HERE.parent.parent


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                          encoding="utf-8", timeout=3, check=False)


def doctrine_lag_notice(root: Path) -> str:
    """A notice when `main` holds a doctrine change that HEAD of this checkout lacks, else "".

    Raises when it cannot decide (no main ref, git failing): the caller reports that, since
    silence would read as "in sync"."""
    if _git(root, "rev-parse", "--verify", "--quiet", MAIN_REF).returncode != 0:
        raise RuntimeError(f"{root} has no {MAIN_REF}; cannot tell whether its doctrine lags main")
    log = _git(root, "log", "-1", "--format=%H", MAIN_REF, "--", *DOCTRINE_PATHS)
    if log.returncode != 0:
        raise RuntimeError(f"git log on {MAIN_REF} failed: {log.stderr.strip()[:200]}")
    last = log.stdout.strip()
    if not last:
        return ""
    anc = _git(root, "merge-base", "--is-ancestor", last, "HEAD")
    if anc.returncode == 0:
        return ""
    if anc.returncode != 1:
        raise RuntimeError(f"git merge-base failed: {anc.stderr.strip()[:200]}")
    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() or "HEAD"
    return (f"DOCTRINE LAGS MAIN: the checkout {root} (branch {branch}) does not contain main's latest "
            f"change to CLAUDE.md, .claude/rules/ or .claude/settings.json ({last[:8]}). The doctrine "
            f"loaded into THIS session is NOT main's, so a rule merged since is not in force here. Say "
            f"so in your gate, and work from a worktree off main or merge main into this branch first.")


def strip_heredocs(command: str) -> str:
    """Drop heredoc bodies: their content is data, and stray quotes in it break tokenising."""
    out: list[str] = []
    pending: list[tuple[str, bool]] = []
    for line in command.replace("\r\n", "\n").split("\n"):
        if pending:
            delim, dash = pending[0]
            if (line.lstrip("\t") if dash else line) == delim:
                pending.pop(0)
            continue
        out.append(line)
        for m in _HEREDOC.finditer(line):
            pending.append((m.group(2), line[m.start():m.start() + 3] == "<<-"))
    return "\n".join(out)


def command_tokens(command: str) -> list[str]:
    """Every whitespace/operator-separated word of the command, quotes stripped."""
    return [t.strip("'\"") for t in _SPLIT.split(command) if t.strip("'\"")]


def agent_key(payload: dict) -> tuple[str, str]:
    for field, kind in (("agent_id", "agent"), ("session_id", "session"), ("transcript_path", "transcript")):
        v = payload.get(field)
        if isinstance(v, str) and v:
            return kind, v
    return "unknown", "unknown"


def _key_dir(key: str) -> Path:
    return state_dir() / hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def _delivered_digest(key: str, rule_name: str) -> str:
    """The sha256 last delivered to this agent for this rules file, or "" if none.

    One marker file per (agent, rules file), so parallel tool calls of one agent that
    deliver DIFFERENT files never write the same path. An unreadable marker (another call
    replacing it this instant) reads as "not delivered": the cost is one duplicate delivery."""
    try:
        return (_key_dir(key) / f"{rule_name}.sha").read_text(encoding="utf-8").strip()
    except (FileNotFoundError, PermissionError):
        return ""


def _mark_delivered(key: str, rule_name: str, digest: str) -> None:
    """Record a delivery. Two parallel calls delivering the SAME file race on one marker;
    on Windows the losing os.replace raises PermissionError. Both calls have delivered, so
    the loser retries briefly and then leaves the winner's identical marker in place. This
    is bookkeeping, not delivery: it never turns into a failure notice."""
    d = _key_dir(key)
    d.mkdir(parents=True, exist_ok=True)
    target = d / f"{rule_name}.sha"
    tmp = d / f"{rule_name}.{os.getpid()}.tmp"
    tmp.write_text(digest, encoding="utf-8")
    for attempt in range(5):
        try:
            os.replace(tmp, target)
            return
        except PermissionError:
            time.sleep(0.02 * (attempt + 1))
    try:
        tmp.unlink()
    except OSError:
        pass
    _log(f"marker {rule_name} for {key[:12]} left to a concurrent writer")


def _log(line: str) -> None:
    try:
        lp = log_path()
        lp.parent.mkdir(parents=True, exist_ok=True)
        with lp.open("a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%dT%H:%M:%S%z") + " " + line + "\n")
    except OSError:
        pass  # the log is an instrument; delivery itself must not depend on it


def select(rules: list, payload: dict) -> list[tuple[object, str]]:
    """(rules file, reason) for every rules file this tool call triggers."""
    from doctrine_rules import checkout_roots, path_matches, repo_relative
    tool = str(payload.get("tool_name") or "")
    tin = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    paths: list[str] = []
    command = ""
    if tool in PATH_TOOLS and isinstance(tin.get(PATH_TOOLS[tool]), str):
        paths.append(tin[PATH_TOOLS[tool]])
    if tool in SHELL_TOOLS and isinstance(tin.get("command"), str):
        command = strip_heredocs(tin["command"])
        paths += command_tokens(command)
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) and payload.get("cwd") else os.getcwd()
    roots = checkout_roots(HERE.parent.parent)
    # `git -C <dir>` and `cd <dir>` re-base the command's relative paths; resolve each token
    # against the call's cwd AND every such directory (over-inclusion is the safe direction).
    bases = [cwd] + [paths[i + 1] for i, tok in enumerate(paths[:-1]) if tok in ("-C", "cd", "pushd", "Set-Location")]
    rel_paths = [rel for rel in (repo_relative(p, b, roots) for p in paths for b in bases) if rel]
    hits = []
    for r in rules:
        reason = ""
        hit_path = next((p for p in rel_paths if path_matches(r, p)), None)
        if hit_path is not None:
            reason = f"path {hit_path}"
        elif any(rx.search(tool) for rx in r.tools):
            reason = f"tool {tool}"
        elif command and any(rx.search(command) for rx in r.commands):
            reason = "command"
        if reason:
            hits.append((r, reason))
    return hits


def _emit(event: str, context: str, hold: bool = False) -> None:
    if hold:
        out = {"hookSpecificOutput": {
            "hookEventName": event, "permissionDecision": "deny",
            "permissionDecisionReason": HOLD_PREFIX + context}}
    else:
        out = {"hookSpecificOutput": {"hookEventName": event, "additionalContext": context}}
    sys.stdout.write(json.dumps(out))
    sys.stdout.flush()


def handle_pre_tool_use(payload: dict) -> str:
    from doctrine_rules import load_rules
    rules = load_rules(rules_dir())
    kind, key = agent_key(payload)
    parts = []
    for r, reason in select(rules, payload):
        digest = hashlib.sha256(r.body.encode("utf-8")).hexdigest()
        if _delivered_digest(key, r.name) == digest:
            continue
        _mark_delivered(key, r.name, digest)
        parts.append(f"BlarAI doctrine, .claude/rules/{r.name} (binding, same standing as CLAUDE.md; "
                     f"delivered because this tool call touches its subject: {reason}):\n{r.body}")
        _log(f"deliver {r.name} to {kind}:{key[:12]} type={payload.get('agent_type') or 'main'} "
             f"tool={payload.get('tool_name')} reason={reason[:120]}")
    return "\n\n".join(parts)


def handle_session_start(payload: dict) -> str:
    kind, key = agent_key(payload)
    own = _key_dir(key)
    if own.is_dir():
        shutil.rmtree(own)
    d = state_dir()
    if d.is_dir():
        cutoff = time.time() - STATE_TTL_S
        for entry in d.iterdir():
            if entry.stat().st_mtime < cutoff:
                if entry.is_dir():
                    shutil.rmtree(entry)
                else:
                    entry.unlink()
    _log(f"reset {kind}:{key[:12]} source={payload.get('source')}")
    notice = doctrine_lag_notice(doctrine_checkout())
    if notice:
        _log(f"lag {kind}:{key[:12]} {notice[:160]}")
    return notice


def main() -> int:
    event = "PreToolUse"
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        if not isinstance(payload, dict):
            raise ValueError("hook payload is not a JSON object")
        event = str(payload.get("hook_event_name") or "PreToolUse")
        hold = False
        if event == "SessionStart":
            context = handle_session_start(payload)
        elif event == "PreToolUse":
            context = handle_pre_tool_use(payload)
            hold = bool(context) and payload.get("tool_name") in HOLD_TOOLS
        else:
            raise ValueError(f"unexpected hook event {event!r}")
        if context:
            _emit(event, context, hold)
        return 0
    except BaseException as exc:  # noqa: BLE001 - every failure is reported, none is silent
        msg = f"{type(exc).__name__}: {exc}"
        _log(f"FAILED {msg}")
        what = ("The SessionStart doctrine check did not complete: whether this checkout's doctrine lags "
                "main is UNKNOWN. Compare it with main by hand and fix the hook (tests/security/"
                "test_doctrine_rules.py names the defect)." if event == "SessionStart" else
                "The topic rules in .claude/rules/ were NOT delivered for this tool call. Read the "
                "relevant .claude/rules/*.md file directly before acting on its subject, and fix the "
                "hook or the rules file (tests/security/test_doctrine_rules.py names the defect).")
        _emit(event, "DOCTRINE DELIVERY FAILED (scripts/hooks/rules_inject.py): " + msg + ". " + what)
        return 0


if __name__ == "__main__":
    sys.exit(main())
