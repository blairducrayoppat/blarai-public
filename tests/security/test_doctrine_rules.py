"""Path-scoped doctrine (.claude/rules/) and its delivery hook (#1700).


Four properties, each with a proof that its check can fail:

1. Every rules file parses under the narrow grammar in scripts/hooks/doctrine_rules.py AND as
   YAML with the same `paths`. Anthropic documents that unparseable frontmatter is ignored and
   the file then loads in EVERY session; a broken file must fail here, not degrade silently.
2. CLAUDE.md's <rules_index> and the directory agree, so a session can find every file.
3. .claude/settings.json wires the hook for the tool calls it must see (PreToolUse) and for the
   resets (SessionStart). A rules file that loads only natively never reaches a subagent.
4. The hook, driven through its real entry point (``python -I -S`` on a JSON payload, exactly
   as Claude Code runs it), delivers the right file once per AGENT: a subagent whose parent was
   already told still gets it (subagents share session_id; keying on it starves them), shell
   writes count, heredoc bodies do not, a changed file is delivered again, the first WRITE to a
   rules subject is held once so the rule arrives before it, parallel calls of one agent never
   raise a false failure, and every real failure reaches the model as an explicit notice.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import atexit
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
RULES_DIR = REPO_ROOT / ".claude" / "rules"
HOOK = REPO_ROOT / "scripts" / "hooks" / "rules_inject.py"
SETTINGS = REPO_ROOT / ".claude" / "settings.json"
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"

sys.path.insert(0, str(REPO_ROOT / "scripts" / "hooks"))
import doctrine_rules as dr  # noqa: E402

REQUIRED_MATCHER_TOOLS = ("Read", "Write", "Edit", "MultiEdit", "NotebookEdit", "Bash", "PowerShell", "WebFetch",
                          "mcp__vikunja__get_task")


# ---------------------------------------------------------------- 1. grammar

def test_every_rules_file_parses_and_is_yaml_with_the_same_paths() -> None:
    rules = dr.load_rules(RULES_DIR)
    assert len(rules) >= 7, f"expected the #1700 topic files, found {[r.name for r in rules]}"
    for r in rules:
        raw = r.path.read_text(encoding="utf-8").replace("\r\n", "\n")
        front = raw.split("\n---\n", 1)[0].removeprefix("---\n")
        parsed = yaml.safe_load(front)
        assert parsed["paths"] == list(r.paths), f"{r.name}: YAML and the hook disagree on paths"
        for key in parsed:
            assert key in dr.KNOWN_KEYS, f"{r.name}: unknown frontmatter key {key}"
        for rx in r.tools + r.commands:
            assert rx.pattern in parsed.get(dr.TOOLS_KEY, []) + parsed.get(dr.COMMANDS_KEY, [])


GOOD = '---\npaths:\n  - "X.md"\n  - ".claude/rules/t.md"\n---\n<sec>\n- a rule.\n</sec>\n'


@pytest.mark.parametrize("bad, why", [
    (GOOD.replace('paths:\n  - "X.md"\n  - ".claude/rules/t.md"\n', ""), "paths"),
    (GOOD.replace('  - ".claude/rules/t.md"\n', ""), "must list the file itself"),
    (GOOD.replace('"X.md"', "X.md"), "list entries"),
    (GOOD.replace('"X.md"', "'X.md'"), "list entries"),
    (GOOD.replace("paths:", "path:"), "expected one of"),
    (GOOD.replace('  - "X.md"', '\t- "X.md"'), "expected one of"),
    (GOOD.replace('"X.md"', '"a\\\\b"'), "backslash"),
    (GOOD.replace("---\n<sec>", "<sec>"), "not closed"),
    (GOOD.replace("</sec>", "</sec>\n<two>\n</two>"), "exactly one"),
    ("<sec>\n</sec>\n", "first line"),
    (GOOD + "x-blarai-tools:\n  - '('\n", ""),
])
def test_grammar_refuses_each_deviation(bad: str, why: str) -> None:
    with pytest.raises(dr.RulesFileError, match=re.escape(why) if why else None):
        dr.parse_rules_text("t.md", bad)


def test_grammar_accepts_the_reference_shape() -> None:
    r = dr.parse_rules_text("t.md", GOOD)
    assert r.paths == ("X.md", ".claude/rules/t.md") and r.top_tag == "sec"


def test_stray_entry_in_rules_dir_is_refused(tmp_path: Path) -> None:
    (tmp_path / "t.md").write_text(GOOD, encoding="utf-8")
    dr.load_rules(tmp_path)
    (tmp_path / "sub").mkdir()
    with pytest.raises(dr.RulesFileError, match="only flat"):
        dr.load_rules(tmp_path)


@pytest.mark.parametrize("glob, path, hit", [
    ("BUILD_JOURNAL.md", "BUILD_JOURNAL.md", True),
    ("BUILD_JOURNAL.md", "docs/BUILD_JOURNAL.md", False),
    ("BUILD_JOURNAL.md", "BUILD_JOURNAL.md.bak", False),
    ("docs/journal_fragments/**", "docs/journal_fragments/2026-10-07-x.md", True),
    ("**/test_*.py", "shared/tests/test_a.py", True),
    ("**/test_*.py", "shared/a_test.py", False),
    ("scripts/*bench*", "scripts/run_bench.ps1", True),
    ("scripts/*bench*", "scripts/sub/bench.ps1", False),
    ("**/*.{py,cs}", "app/x.cs", True),
])
def test_glob_matching(glob: str, path: str, hit: bool) -> None:
    r = dr.parse_rules_text("t.md", GOOD.replace('"X.md"', f'"{glob}"'))
    assert dr.path_matches(r, path) is hit


def test_paths_resolve_lexically_to_the_checkout_that_holds_them(tmp_path: Path) -> None:
    import os
    nc = lambda p: os.path.normcase(os.path.normpath(str(p)))  # noqa: E731
    primary, nested = tmp_path / "BlarAI", tmp_path / "BlarAI" / ".claude" / "worktrees" / "x"
    roots = (nc(primary), nc(nested), nc(tmp_path / "BlarAI-worktrees" / "wt"))
    assert dr.repo_relative(str(primary / "docs" / "a.md"), "C:/", roots) == "docs/a.md"
    assert dr.repo_relative(str(primary / "docs" / "a.md").replace("/", "\\"), "C:/", roots) == "docs/a.md"
    assert dr.repo_relative("docs/a.md", str(primary), roots) == "docs/a.md"
    assert dr.repo_relative("../LESSONS.md", str(primary / "docs"), roots) == "LESSONS.md"
    assert dr.repo_relative(str(nested / "LESSONS.md"), "C:/", roots) == "LESSONS.md", "the nested worktree wins"
    assert dr.repo_relative(str(tmp_path / "BlarAI-worktrees" / "wt" / "BUILD_JOURNAL.md"), "C:/", roots) == "BUILD_JOURNAL.md"
    assert dr.repo_relative(str(tmp_path / "BlarAI-other" / "LESSONS.md"), "C:/", roots) is None, "prefix is not containment"
    assert dr.repo_relative(str(tmp_path / "LESSONS.md"), "C:/", roots) is None
    assert dr.repo_relative(str(primary), "C:/", roots) is None


def test_git_bash_drive_paths_resolve() -> None:
    import os
    roots = (os.path.normcase(os.path.normpath("C:/Users/mrbla/BlarAI-worktrees/wt")),)
    for form in ("/c/Users/mrbla/BlarAI-worktrees/wt/LESSONS.md", "/cygdrive/c/Users/mrbla/BlarAI-worktrees/wt/LESSONS.md",
                 "/mnt/c/Users/mrbla/BlarAI-worktrees/wt/LESSONS.md"):
        assert dr.repo_relative(form, "D:/elsewhere", roots) == "LESSONS.md", form
    assert dr.repo_relative("docs/a.md", "/c/Users/mrbla/BlarAI-worktrees/wt", roots) == "docs/a.md"
    assert dr.repo_relative("/cx/Users/a.md", "D:/", roots) is None


def test_checkout_roots_refuse_empty_or_missing_metadata(tmp_path: Path) -> None:
    common = tmp_path / "repo" / ".git"
    (common / "worktrees" / "wt").mkdir(parents=True)
    (common / "worktrees" / "wt" / "gitdir").write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="empty git metadata"):
        dr.checkout_roots(tmp_path / "repo")
    (common / "worktrees" / "wt" / "gitdir").unlink()
    with pytest.raises(FileNotFoundError):
        dr.checkout_roots(tmp_path / "repo")


def test_checkout_roots_come_from_git_metadata() -> None:
    import os
    roots = dr.checkout_roots(REPO_ROOT)
    assert os.path.normcase(os.path.normpath(str(REPO_ROOT))) in roots
    assert len(roots) == len(set(roots))


@pytest.mark.parametrize("path, cwd", [
    ("//attacker/share/x/LESSONS.md", "C:/Users"),
    ("\\\\attacker\\share\\LESSONS.md", "C:/Users"),
    ("//?/UNC/attacker/share/LESSONS.md", "C:/Users"),
    ("//?/C:/Users/x/LESSONS.md", "C:/Users"),
    ("LESSONS.md", "//attacker/share/wt"),
    ("Z:/mapped/share/LESSONS.md", "C:/Users"),
    ("C:LESSONS.md", "C:/Users"),
    ("~/LESSONS.md", "C:/Users"),
    ("%USERPROFILE%/LESSONS.md", "C:/Users"),
])
def test_no_tool_call_path_is_ever_opened_or_stat(path: str, cwd: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """The hook runs before the permission check: it must not touch a path the call supplied."""
    import os
    touched: list[str] = []

    def spy(name):  # type: ignore[no-untyped-def]
        def f(*a, **kw):  # type: ignore[no-untyped-def]
            touched.append(f"{name}{a[:1]}")
            raise AssertionError(f"{name} called on a tool-call path")
        return f

    roots = dr.checkout_roots(REPO_ROOT)
    for name in ("open", "stat", "lstat", "listdir", "scandir"):
        monkeypatch.setattr(f"os.{name}", spy(name))
    monkeypatch.setattr("builtins.open", spy("builtins.open"))
    monkeypatch.setattr("os.path.exists", spy("exists"))
    monkeypatch.setattr("os.path.realpath", spy("realpath"))
    dr.repo_relative(path, cwd, roots)
    assert touched == [], touched


# ---------------------------------------------------------------- 2. index

def _index_names(text: str) -> set[str]:
    m = re.search(r"\n<rules_index[^>]*>\n(.*?)\n</rules_index>", text, re.S)
    assert m, "CLAUDE.md lost its <rules_index> section"
    return set(re.findall(r"^- ([a-z_-]+\.md) — ", m.group(1), re.M))


def _index_drift(text: str, names: set[str]) -> list[str]:
    listed = _index_names(text)
    return [f"unindexed: {n}" for n in sorted(names - listed)] + [f"no such file: {n}" for n in sorted(listed - names)]


def test_rules_index_and_directory_agree() -> None:
    names = {r.name for r in dr.load_rules(RULES_DIR)}
    assert not _index_drift(CLAUDE_MD.read_text(encoding="utf-8"), names)


def test_index_check_fires_on_a_missing_entry() -> None:
    text = CLAUDE_MD.read_text(encoding="utf-8")
    names = {r.name for r in dr.load_rules(RULES_DIR)}
    assert _index_drift(re.sub(r"\n- journal\.md — [^\n]*", "", text), names) == ["unindexed: journal.md"]
    assert _index_drift(text, names - {"journal.md"}) == ["no such file: journal.md"]


def _claimed_surface_drift(text: str, rules: list, top_dirs: set[str]) -> list[str]:
    """Each top-level directory an index line says its file is "delivered on" must be matched, at any depth, by a path glob of that rule."""
    m = re.search(r"\n<rules_index[^>]*>\n(.*?)\n</rules_index>", text, re.S)
    assert m, "CLAUDE.md lost its <rules_index> section"
    by_name = {r.name: r for r in rules}
    out: list[str] = []
    for name, claim in re.findall(r"^- ([a-z_-]+\.md) — .*?delivered on ([^\n]*)", m.group(1), re.M):
        rule = by_name.get(name)
        if rule is None:
            continue
        for word in re.findall(r"[a-z_]+", claim):
            if word in top_dirs and not all(dr.path_matches(rule, f"{word}/{tail}") for tail in ("x.md", "a/b/x.md")):
                out.append(f"{name}: the index says it is delivered on {word}/, the file's path globs do not match every path under {word}/ (a narrower glob delivers on part of it)")
    return out


def _repo_top_dirs() -> set[str]:
    return {p.name for p in REPO_ROOT.iterdir() if p.is_dir()}


def test_rules_index_delivery_claims_match_the_frontmatter() -> None:
    names = _repo_top_dirs()
    assert {"docs", "scripts", "tools", "tests"} <= names
    assert not _claimed_surface_drift(CLAUDE_MD.read_text(encoding="utf-8"), dr.load_rules(RULES_DIR), names)


def test_delivery_claim_check_fires_when_a_surface_is_narrowed() -> None:
    """R4-4: the claim check must be able to fail (the index names scripts/, tools/ and tests/ for identity.md)."""
    text = CLAUDE_MD.read_text(encoding="utf-8")
    rules = dr.load_rules(RULES_DIR)
    ident = next(r for r in rules if r.name == "identity.md")
    for dropped in ("scripts", "tools", "tests", "docs"):
        narrowed = [g for g in ident.paths if not g.startswith(dropped + "/")]
        stub = type("R", (), {"name": "identity.md", "paths": tuple(narrowed)})()
        drift = _claimed_surface_drift(text, [stub], _repo_top_dirs())
        assert drift and dropped in drift[0], (dropped, drift)


def test_identity_rule_is_delivered_on_every_surface_the_index_claims(tmp_path: Path) -> None:
    """R4-4 through the real hook: a new file under each claimed directory shows the rule (held once per agent)."""
    for rel in ("scripts/new_tool.py", "tests/security/test_new.py", "tools/probes/x.py", "docs/governance/x.md",
                "docs/sprints/x.md", "docs/design/x.md"):
        assert "identity.md" in Hook(tmp_path / rel.replace("/", "_")).delivered(_edit(rel)), rel


# ---------------------------------------------------------------- 3. wiring

def _wiring_faults(settings: dict) -> list[str]:
    faults = []
    hooks = settings.get("hooks", {})
    pre = [h for e in hooks.get("PreToolUse", []) for h in e.get("hooks", [])
           if "rules_inject.py" in h.get("command", "")]
    matchers = [e.get("matcher", "") for e in hooks.get("PreToolUse", [])
                if any("rules_inject.py" in h.get("command", "") for h in e.get("hooks", []))]
    if len(pre) != 1:
        faults.append(f"PreToolUse rules_inject entries: {len(pre)} (want 1)")
    for tool in REQUIRED_MATCHER_TOOLS:
        if not any(re.fullmatch(m, tool) for m in matchers):
            faults.append(f"PreToolUse matcher misses {tool}")
    start = [h for e in hooks.get("SessionStart", []) for h in e.get("hooks", [])
             if "rules_inject.py" in h.get("command", "")]
    if len(start) != 1:
        faults.append(f"SessionStart rules_inject entries: {len(start)} (want 1)")
    for h in pre + start:
        if "DOCTRINE DELIVERY FAILED" not in h.get("command", ""):
            faults.append("wrapper has no loud fallback when the script cannot run")
    return faults


def test_settings_wire_the_hook() -> None:
    assert not _wiring_faults(json.loads(SETTINGS.read_text(encoding="utf-8")))


def test_wiring_check_fires_when_unwired() -> None:
    s = json.loads(SETTINGS.read_text(encoding="utf-8"))
    for e in s["hooks"]["PreToolUse"]:
        if "Bash" in e.get("matcher", "") and any("rules_inject" in h["command"] for h in e["hooks"]):
            e["matcher"] = "Read|Write|Edit"
    assert "PreToolUse matcher misses Bash" in _wiring_faults(s)
    del s["hooks"]["SessionStart"]
    assert any(f.startswith("SessionStart") for f in _wiring_faults(s))


# ---------------------------------------------------------------- 4. delivery, end to end

def _git(root: Path, *args: str) -> str:
    p = subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                       capture_output=True, text=True, encoding="utf-8", check=True)
    return p.stdout.strip()


def make_repo(root: Path) -> Path:
    """A scratch repo on main holding one doctrine file; the lag check is pointed here so the
    hook tests do not depend on which branch the real checkout is on."""
    root.mkdir(parents=True)
    _git(root, "init", "-q", "-b", "main")
    (root / "CLAUDE.md").write_text("v1\n", encoding="utf-8")
    _git(root, "add", "CLAUDE.md")
    _git(root, "commit", "-q", "-m", "doctrine v1")
    return root


def _make_writable_and_retry(func, path, _exc) -> None:
    """git's object files are read-only; on Windows rmtree cannot delete them until cleared."""
    os.chmod(path, 0o700)
    func(path)


_SYNCED: list[Path] = []


def synced_checkout() -> Path:
    if not _SYNCED:
        d = Path(tempfile.mkdtemp(prefix="blarai-lag-"))
        atexit.register(shutil.rmtree, d, False, _make_writable_and_retry)
        _SYNCED.append(make_repo(d / "repo"))
    return _SYNCED[0]


class Hook:
    def __init__(self, tmp: Path, rules: Path = RULES_DIR, checkout: Path | None = None) -> None:
        self.env = {**os.environ, "BLARAI_RULES_INJECT_STATE_DIR": str(tmp / "state"),
                    "BLARAI_RULES_INJECT_LOG": str(tmp / "inject.log"), "BLARAI_RULES_DIR": str(rules),
                    "BLARAI_DOCTRINE_CHECKOUT": str(checkout or synced_checkout())}

    def call(self, payload: object, event: str = "PreToolUse") -> tuple[str, bool]:
        """(text delivered to the model, whether the tool call was held)."""
        if isinstance(payload, dict):
            payload = {"hook_event_name": event, "session_id": "sess-1", "cwd": str(REPO_ROOT), **payload}
        raw = payload if isinstance(payload, str) else json.dumps(payload)
        p = subprocess.run([sys.executable, "-I", "-S", str(HOOK)], input=raw, capture_output=True,
                           text=True, encoding="utf-8", env=self.env, timeout=30, check=False)
        assert p.returncode == 0, p.stderr
        return parse_output(p.stdout, event)

    def run(self, payload: object, event: str = "PreToolUse") -> str:
        return self.call(payload, event)[0]

    def delivered(self, payload: dict) -> set[str]:
        return names_in(self.run(payload))


def parse_output(stdout: str, event: str) -> tuple[str, bool]:
    if not stdout:
        return "", False
    out = json.loads(stdout)["hookSpecificOutput"]
    assert out["hookEventName"] == event
    if out.get("permissionDecision") == "deny":
        assert "additionalContext" not in out
        return out["permissionDecisionReason"], True
    assert "permissionDecision" not in out, "the hook never allows or asks; it only holds or informs"
    return out["additionalContext"], False


def names_in(text: str) -> set[str]:
    return set(re.findall(r"BlarAI doctrine, \.claude/rules/([a-z_-]+\.md) ", text))


def _edit(path: str, **kw: str) -> dict:
    return {"tool_name": "Edit", "tool_input": {"file_path": path}, **kw}


def _bash(cmd: str, **kw: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": cmd}, **kw}


def test_delivers_the_matching_file_verbatim(tmp_path: Path) -> None:
    h = Hook(tmp_path)
    ctx, held = h.call({"tool_name": "Read", "tool_input": {"file_path": str(REPO_ROOT / "BUILD_JOURNAL.md")}})
    body = next(r.body for r in dr.load_rules(RULES_DIR) if r.name == "journal.md")
    assert body in ctx and not held, "a Read is informed, never held"


def test_first_write_to_a_rules_subject_is_held_once(tmp_path: Path) -> None:
    """additionalContext arrives with the RESULT; a first write would go out uninformed."""
    h = Hook(tmp_path)
    write = {"tool_name": "Write", "tool_input": {"file_path": "docs/journal_fragments/x.md", "content": "y"}}
    ctx, held = h.call(write)
    assert held and ctx.startswith("HELD ONCE, NOT AN ERROR") and names_in(ctx) == {"journal.md", "identity.md"}
    assert h.call(write) == ("", False), "the re-issued write passes"
    assert h.call({**write, "agent_id": "child-1"})[1], "a subagent's first write is held for it too"
    assert h.call(_edit("LESSONS.md")) == ("", False), "already told: no second hold on another file"


def test_nothing_outside_a_blarai_checkout_is_a_rules_subject(tmp_path: Path) -> None:
    """The hold must not deny writes to the user's memory, a scratchpad or another repo."""
    h = Hook(tmp_path)
    home_claude = Path.home() / ".claude"
    for path in (tmp_path / "scratch" / "probe.py", home_claude / "CLAUDE.md",
                 home_claude / "projects" / "x" / "memory" / "MEMORY.md",
                 tmp_path / "agentic-setup" / "BUILD_JOURNAL.md"):
        assert h.call({"tool_name": "Write", "tool_input": {"file_path": str(path)}}) == ("", False), path
    # A literal outside path: tmp_path itself contains "pytest", which the testing.md command trigger would match.
    assert h.call(_bash("sed -i 's/a/b/' C:/elsewhere/LESSONS.md")) == ("", False)


def test_hold_applies_only_to_file_writing_tools(tmp_path: Path) -> None:
    h = Hook(tmp_path)
    assert h.call(_bash("cat > BUILD_JOURNAL.md <<'EOF'\nx\nEOF")) [1] is False
    assert h.call({"tool_name": "mcp__vikunja__get_task", "tool_input": {}})[1] is False
    for i, tool in enumerate(("Write", "Edit", "MultiEdit")):
        assert Hook(tmp_path / str(i)).call({"tool_name": tool, "tool_input": {"file_path": "LESSONS.md"}})[1]
    nb = {"tool_name": "NotebookEdit", "tool_input": {"notebook_path": "docs/performance/a.ipynb"}}
    assert Hook(tmp_path / "nb").call(nb)[1]


def test_parallel_calls_of_one_agent_never_raise_a_false_failure(tmp_path: Path) -> None:
    """Parallel Reads are the default opening; a replace race must not read as a broken hook."""
    targets = ["LESSONS.md", "docs/TEST_GOVERNANCE.md", "PERFORMANCE_LOG.md", "LESSONS.md",
               "docs/handoffs/a-landing-20261007.md", "CLAUDE.md", "BUILD_JOURNAL.md", "x.py"]
    h = Hook(tmp_path)
    for rnd in range(6):
        procs = [subprocess.Popen([sys.executable, "-I", "-S", str(HOOK)], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                  encoding="utf-8", env=h.env)
                 for _ in targets]
        payloads = [json.dumps({"hook_event_name": "PreToolUse", "session_id": "s", "agent_id": f"a{rnd}",
                                "cwd": str(REPO_ROOT),
                                "tool_name": "Read", "tool_input": {"file_path": f}}) for f in targets]
        for proc, raw in zip(procs, payloads):
            proc.stdin.write(raw)
            proc.stdin.close()
        outs = [proc.stdout.read() for proc in procs]
        for proc in procs:
            assert proc.wait(timeout=60) == 0
        texts = [parse_output(o, "PreToolUse")[0] for o in outs]
        assert not [x for x in texts if x.startswith("DOCTRINE DELIVERY FAILED")], texts
        got = set().union(*(names_in(x) for x in texts))
        assert {"journal.md", "testing.md", "performance.md", "handoff.md", "doctrine.md", "coding.md"} <= got
    assert not list((tmp_path / "state").rglob("*.tmp")), "no orphaned temp files"


def test_once_per_agent_and_a_child_is_not_starved_by_its_parent(tmp_path: Path) -> None:
    h = Hook(tmp_path)
    assert h.delivered(_edit("LESSONS.md")) == {"journal.md"}
    assert h.delivered(_edit("LESSONS.md")) == set(), "the same agent is told once"
    child = _edit("LESSONS.md", agent_id="agent-7", agent_type="general-purpose")
    assert h.delivered(child) == {"journal.md"}, "a subagent shares session_id; it must still be told"
    assert h.delivered(child) == set()
    assert h.delivered(_edit("LESSONS.md", agent_id="agent-8")) == {"journal.md"}


def test_session_start_resets_what_compaction_dropped(tmp_path: Path) -> None:
    h = Hook(tmp_path)
    assert h.delivered(_edit("FIELD_NOTES.md")) == {"journal.md"}
    assert h.run({"source": "compact"}, event="SessionStart") == ""
    assert h.delivered(_edit("FIELD_NOTES.md")) == {"journal.md"}


def test_a_changed_rules_file_is_delivered_again(tmp_path: Path) -> None:
    rules = tmp_path / "rules"
    shutil.copytree(RULES_DIR, rules)
    h = Hook(tmp_path, rules)
    assert h.delivered(_edit("BUILD_JOURNAL.md")) == {"journal.md"}
    j = rules / "journal.md"
    j.write_text(j.read_text(encoding="utf-8").replace("- Failures stay in.", "- Failures stay in, always."),
                 encoding="utf-8")
    assert h.delivered(_edit("BUILD_JOURNAL.md")) == {"journal.md"}


@pytest.mark.parametrize("cmd, want", [
    ("cat > BUILD_JOURNAL.md <<'EOF'\nx\nEOF", {"journal.md"}),
    ("printf 'x' | tee docs/journal_fragments/a.md b.txt", {"journal.md", "identity.md"}),
    ("sed -i 's/a/b/' LESSONS.md", {"journal.md"}),
    ("Set-Content -Path docs\\performance\\run.json -Value 1", {"performance.md", "identity.md"}),
    ("cat > notes.txt <<'EOF'\nsee BUILD_JOURNAL.md, don't > LESSONS.md\nEOF", set()),
    ("cat > notes.txt <<-EOF\n\tBUILD_JOURNAL.md\n\tEOF", set()),
    ("LOCALAPPDATA=/tmp/x python -m pytest shared/ -q", {"testing.md"}),
    ("python -m evals.run --suite all", {"performance.md"}),
    ("python scripts/measure_decode.py --runs 5", {"performance.md", "coding.md", "identity.md"}),
    ("Start-ScheduledTask -TaskName BlarAI-Probe", {"performance.md"}),
    ("curl -s https://api.github.com/repos/o/r/pulls/1/reviews", {"performance.md"}),
    ("git status", set()),
    (f"cat /{str(REPO_ROOT)[0].lower()}{str(REPO_ROOT)[2:]}/LESSONS.md".replace("\\", "/"), {"journal.md"}),
    (f"git -C {REPO_ROOT.as_posix()} add docs/journal_fragments/a.md", {"journal.md", "identity.md"}),
])
def test_shell_commands(tmp_path: Path, cmd: str, want: set[str]) -> None:
    assert Hook(tmp_path).delivered(_bash(cmd)) == want


def test_git_dash_c_and_cd_rebase_relative_tokens(tmp_path: Path) -> None:
    h = Hook(tmp_path)
    away = "C:/Windows"
    assert h.delivered(_bash(f"git -C {REPO_ROOT.as_posix()} add docs/journal_fragments/a.md", cwd=away)) == {"journal.md", "identity.md"}
    assert Hook(tmp_path / "2").delivered(_bash(f"cd {REPO_ROOT.as_posix()} && cat LESSONS.md", cwd=away)) == {"journal.md"}
    assert Hook(tmp_path / "3").delivered(_bash("cat LESSONS.md", cwd=away)) == set()


def test_tool_triggers_and_unrelated_calls(tmp_path: Path) -> None:
    h = Hook(tmp_path)
    assert h.delivered({"tool_name": "mcp__vikunja__project_summary", "tool_input": {}}) == {"vikunja.md"}
    assert h.delivered({"tool_name": "WebFetch", "tool_input": {"url": "https://github.com/o/r/pull/1"}}) == {"performance.md"}
    assert h.delivered({"tool_name": "Read", "tool_input": {"file_path": "README.md"}}) == set()
    assert h.delivered({"tool_name": "Glob", "tool_input": {"pattern": "**/*.md"}}) == set()


def test_every_rules_file_is_reachable_through_its_own_triggers(tmp_path: Path) -> None:
    """A rules file whose triggers match nothing would be built-but-wired-into-nothing."""
    for r in dr.load_rules(RULES_DIR):
        real = [g for g in r.paths if g != f".claude/rules/{r.name}"]
        probe = next((g.replace("**/", "a/").replace("**", "x.md").replace("*", "x") for g in real), None)
        h = Hook(tmp_path / r.name)
        if probe is not None:
            assert r.name in h.delivered(_edit(probe)), f"{r.name} unreachable via {probe}"
        else:
            assert r.tools, f"{r.name} has no trigger besides its own path"


@pytest.mark.parametrize("breakage", ["frontmatter", "missing-dir"])
def test_failure_is_loud_and_does_not_block(tmp_path: Path, breakage: str) -> None:
    rules = tmp_path / "rules"
    if breakage == "frontmatter":
        shutil.copytree(RULES_DIR, rules)
        (rules / "journal.md").write_text("paths: BUILD_JOURNAL.md\n<x>\n</x>\n", encoding="utf-8")
    ctx = Hook(tmp_path, rules).run(_edit("BUILD_JOURNAL.md"))
    assert ctx.startswith("DOCTRINE DELIVERY FAILED"), ctx
    assert "FAILED" in (tmp_path / "inject.log").read_text(encoding="utf-8")


def test_garbage_payload_is_loud(tmp_path: Path) -> None:
    assert Hook(tmp_path).run("not json").startswith("DOCTRINE DELIVERY FAILED")


def test_settings_wrapper_is_loud_when_the_script_is_missing(tmp_path: Path) -> None:
    """Run the real wrapper command from settings.json with a project dir that has no script."""
    bash = shutil.which("bash")
    if bash is None:
        pytest.fail("bash is required: Claude Code runs this hook through bash")
    s = json.loads(SETTINGS.read_text(encoding="utf-8"))
    cmd = next(h["command"] for e in s["hooks"]["PreToolUse"] for h in e["hooks"]
               if "rules_inject.py" in h["command"])
    p = subprocess.run([bash, "-c", cmd], input="{}", capture_output=True, text=True, timeout=30,
                       env={**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)}, check=False)
    assert p.returncode == 0
    assert json.loads(p.stdout)["hookSpecificOutput"]["additionalContext"].startswith("DOCTRINE DELIVERY FAILED")


def test_settings_wrapper_delivers_through_the_python_on_path(tmp_path: Path) -> None:
    """The interpreter Claude Code runs is bash's `python`, not this venv's: drive a delivery
    through the real wrapper so a PATH interpreter that cannot run the hook fails here."""
    bash = shutil.which("bash")
    if bash is None:
        pytest.fail("bash is required: Claude Code runs this hook through bash")
    s = json.loads(SETTINGS.read_text(encoding="utf-8"))
    cmd = next(h["command"] for e in s["hooks"]["PreToolUse"] for h in e["hooks"]
               if "rules_inject.py" in h["command"])
    env = {**Hook(tmp_path).env, "CLAUDE_PROJECT_DIR": str(REPO_ROOT).replace("\\", "/")}
    payload = json.dumps({"hook_event_name": "PreToolUse", "session_id": "w", "tool_name": "Read",
                          "cwd": str(REPO_ROOT),
                          "tool_input": {"file_path": "LESSONS.md"}})
    p = subprocess.run([bash, "-c", cmd], input=payload, capture_output=True, text=True,
                       encoding="utf-8", env=env, timeout=30, check=False)
    assert p.returncode == 0, p.stderr
    assert names_in(parse_output(p.stdout, "PreToolUse")[0]) == {"journal.md"}, p.stdout[:300]


# ---------------------------------------------------------------- 5. doctrine lag at SessionStart (#1703)

def _lagging_repo(tmp: Path) -> Path:
    """main gains a doctrine change that the checked-out branch `old` does not contain."""
    repo = make_repo(tmp / "repo")
    _git(repo, "branch", "old")
    (repo / "CLAUDE.md").write_text("v2\n", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "doctrine v2")
    _git(repo, "checkout", "-q", "old")
    return repo


def test_session_start_warns_when_the_checkout_lacks_a_doctrine_change_on_main(tmp_path: Path) -> None:
    repo = _lagging_repo(tmp_path)
    ctx = Hook(tmp_path, checkout=repo).run({"source": "startup"}, event="SessionStart")
    assert ctx.startswith("DOCTRINE LAGS MAIN"), ctx
    assert "branch old" in ctx and _git(repo, "rev-parse", "--short=8", "main") in ctx and "worktree off main" in ctx


def test_session_start_is_silent_when_the_checkout_contains_main_doctrine(tmp_path: Path) -> None:
    repo = _lagging_repo(tmp_path)
    _git(repo, "merge", "-q", "--no-edit", "main")
    assert Hook(tmp_path, checkout=repo).run({"source": "startup"}, event="SessionStart") == ""


def test_session_start_is_silent_for_a_branch_ahead_of_main_and_for_non_doctrine_drift(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo")
    _git(repo, "checkout", "-q", "-b", "feat")
    (repo / "CLAUDE.md").write_text("ahead\n", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "branch edits doctrine")
    (repo / "x.py").write_text("1\n", encoding="utf-8")
    _git(repo, "add", "x.py")
    _git(repo, "commit", "-q", "-m", "code")
    _git(repo, "checkout", "-q", "main")
    (repo / "y.py").write_text("2\n", encoding="utf-8")
    _git(repo, "add", "y.py")
    _git(repo, "commit", "-q", "-m", "main code only")
    _git(repo, "checkout", "-q", "feat")
    assert Hook(tmp_path, checkout=repo).run({"source": "startup"}, event="SessionStart") == ""


def test_lag_check_failing_to_decide_is_loud_not_in_sync(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo")
    _git(repo, "branch", "-m", "main", "trunk")
    ctx = Hook(tmp_path, checkout=repo).run({"source": "startup"}, event="SessionStart")
    assert ctx.startswith("DOCTRINE DELIVERY FAILED") and "refs/heads/main" in ctx, ctx


def test_lag_probe_fails_when_the_check_is_removed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Toggle: with the doctrine paths emptied the same lagging repo reads in sync, so the
    notice above is produced by the check and not by the scenario."""
    sys.path.insert(0, str(HOOK.parent))
    import rules_inject as ri
    repo = _lagging_repo(tmp_path)
    assert ri.doctrine_lag_notice(repo).startswith("DOCTRINE LAGS MAIN")
    monkeypatch.setattr(ri, "DOCTRINE_PATHS", ("no-such-doctrine-path",))
    assert ri.doctrine_lag_notice(repo) == ""


@pytest.mark.parametrize("relpath", [".claude/rules/x.md", ".claude/settings.json", ".claude/agents/a.md", "CLAUDE.md"])
def test_each_doctrine_path_alone_makes_a_lag(tmp_path: Path, relpath: str) -> None:
    repo = make_repo(tmp_path / "repo")
    _git(repo, "branch", "old")
    target = repo / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("changed on main\n", encoding="utf-8")
    _git(repo, "add", relpath)
    _git(repo, "commit", "-q", "-m", "doctrine on main")
    _git(repo, "checkout", "-q", "old")
    ctx = Hook(tmp_path, checkout=repo).run({"source": "startup"}, event="SessionStart")
    assert ctx.startswith("DOCTRINE LAGS MAIN"), (relpath, ctx)


def test_an_ancestor_check_that_errors_is_loud_not_in_sync(tmp_path: Path) -> None:
    """HEAD unborn: `main` has doctrine history but merge-base cannot resolve HEAD."""
    repo = make_repo(tmp_path / "repo")
    _git(repo, "checkout", "-q", "--orphan", "unborn")
    ctx = Hook(tmp_path, checkout=repo).run({"source": "startup"}, event="SessionStart")
    assert ctx.startswith("DOCTRINE DELIVERY FAILED") and "merge-base" in ctx, ctx
    assert "NOT delivered for this tool call" not in ctx and "UNKNOWN" in ctx


def test_delivery_claim_check_fires_when_a_surface_is_narrowed_to_a_subdirectory() -> None:
    """R5-2: ``docs/reviews/**`` opens with ``docs/`` but does not deliver on docs; the claim check alone must fail."""
    text = CLAUDE_MD.read_text(encoding="utf-8")
    ident = next(r for r in dr.load_rules(RULES_DIR) if r.name == "identity.md")
    narrowed = tuple("docs/reviews/**" if g == "docs/**" else g for g in ident.paths)
    assert narrowed != tuple(ident.paths)
    stub = type("R", (), {"name": "identity.md", "paths": narrowed})()
    drift = _claimed_surface_drift(text, [stub], _repo_top_dirs())
    assert drift and "docs" in drift[0], drift


def test_delivery_claim_check_accepts_an_equivalent_glob() -> None:
    """R1-3: ``docs/**/*`` delivers on the same paths as ``docs/**``; the claim check asks the matcher, not the spelling."""
    text = CLAUDE_MD.read_text(encoding="utf-8")
    ident = next(r for r in dr.load_rules(RULES_DIR) if r.name == "identity.md")
    spelled = tuple("docs/**/*" if g == "docs/**" else g for g in ident.paths)
    assert spelled != tuple(ident.paths)
    stub = dr.RulesFile(name="identity.md", path=ident.path, paths=spelled, tools=ident.tools, commands=ident.commands,
                        body=ident.body, top_tag=ident.top_tag)
    assert _claimed_surface_drift(text, [stub], _repo_top_dirs()) == []
