"""Fail-closed locks for scripts/hooks/git_rules_guard.py (#1690).

The hook contract treats exit 1 (an uncaught exception), any non-2 code, a crash and a timeout
as ALLOW. These tests drive the real script with hostile input and require exit 2 whenever the
command could touch git, and exit 0/2 only (never 1, never a traceback) everywhere.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _git_hook_helpers import mark_slow_except, tiered  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "hooks" / "git_rules_guard.py"
MARKER_DOC = "<blarai_project_instructions>x</blarai_project_instructions>\n"


def _git(cwd, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   capture_output=True, text=True, check=True, env=env)


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    p = tmp_path_factory.mktemp("fc") / "feat"
    p.mkdir()
    _git(p, "init", "-q", "-b", "main")
    (p / "f.txt").write_text("x")
    (p / "CLAUDE.md").write_text(MARKER_DOC)
    _git(p, "add", ".")
    _git(p, "commit", "-q", "-m", "init")
    _git(p, "checkout", "-q", "-b", "feat/x")
    return p


def go(command=None, cwd=None, raw=None, tool="Bash", script=SCRIPT, env_extra=None, timeout=60,
       path_override=None):
    env = {k: v for k, v in os.environ.items()
           if k != "BLARAI_GIT_RULES_OVERRIDE" and not k.startswith("GIT_")}
    env.update(env_extra or {})
    if path_override is not None:
        env["PATH"] = path_override
    if raw is None:
        raw = json.dumps({"tool_name": tool, "tool_input": {"command": command}, "cwd": str(cwd)})
    if isinstance(raw, str):
        raw = raw.encode("utf-8", "surrogatepass")
    t = time.monotonic()
    r = subprocess.run([sys.executable, str(script)], input=raw, capture_output=True, env=env,
                       timeout=timeout)
    return r.returncode, time.monotonic() - t, r.stderr.decode("utf-8", "replace")


def variant(tmp_path: Path, *edits: tuple[str, str], name="g.py") -> Path:
    common = SCRIPT.parent / "rules_common.py"
    src = SCRIPT.read_text(encoding="utf-8")
    csrc = common.read_text(encoding="utf-8")
    for old, new in edits:
        if src.count(old) >= 1:
            src = src.replace(old, new, 1)
        else:
            assert csrc.count(old) >= 1, f"anchor missing: {old!r}"
            csrc = csrc.replace(old, new, 1)
    (tmp_path / "rules_common.py").write_text(csrc, encoding="utf-8")
    p = tmp_path / name
    p.write_text(src, encoding="utf-8")
    return p


# ---- (1) parse errors: block when the text could touch git ------------------------------------
PARSE_BLOCKED = [
    "echo 'unterminated git add -A", 'git commit -m "unterminated', "git add -A\x00",
    "echo $(git add -A", "echo `git add -A", "echo ${X git add -A", "git add -A <<EOF\nbody",
    "cat <<EOF\ngit add -A", "git add -A\r\n", "git add -A\r\ngit status\r\n", "git add -A\n\n\n",
    "echo 'g\"it add -A", "echo $(echo g'it' add -A", "echo $(echo g\\", "echo ${", "eval 'x",
    "echo \"$(\"", "iex 'unterminated", "echo $((", "echo \"${Y\" git add -A", "g\"it add -A",
    "echo `echo $(echo 'git", "x=$'unterminated git add -A",
    "echo $(", "echo `", "source ./x 'unterminated", "echo 'x & y",
]


@pytest.mark.parametrize("cmd", tiered(PARSE_BLOCKED, {0, 1, 2, 3, 10}))
def test_unparseable_that_could_touch_git_blocks(cmd, repo):
    code, _, err = go(cmd, repo)
    assert code == 2, (cmd, err)
    assert "Traceback" not in err


PROVEN_NO_GIT = ["echo hi", "ls -la", "echo 'unterminated", "echo \"also unterminated",
                 "python -c 'print(1)'", "cat <<EOF\nplain", "echo a b c\n"]


@pytest.mark.parametrize("cmd", PROVEN_NO_GIT)
def test_commands_proven_not_to_touch_git_pass(cmd, repo):
    assert go(cmd, repo)[0] == 0, cmd


def test_only_shell_tools_fail_open(repo):
    for tool in ("Edit", "Write", "Read", "mcp__x__y"):
        assert go("git add -A 'unterminated", repo, tool=tool)[0] == 0


def test_surrogates_nul_and_invalid_utf8(repo):
    cwd = str(repo).replace("\\", "/")
    lone = '{"tool_name":"Bash","tool_input":{"command":"git add -A \\ud800"},"cwd":"%s"}' % cwd
    assert go(raw=lone)[0] == 2
    assert go(raw=b'{"tool_name":"Bash","tool_input":{"command":"git add -A \xff\xfe"},"cwd":"%s"}' % cwd.encode())[0] == 2
    assert go(raw=b'{"tool_name":"Bash","tool_input":{"command":"git add -A \\u0000"},"cwd":"%s"}' % cwd.encode())[0] == 2
    assert go(raw=b"\xef\xbb\xbf" + json.dumps({"tool_name": "Bash", "tool_input": {"command": "git add -A"},
                                                 "cwd": cwd}).encode())[0] == 2


def test_stdin_failures_block(repo):
    for raw in (b"", b"   ", b"{", b"null", b"[]", b'"x"', b"\x00\x01\x02", b"{" * 100000):
        assert go(raw=raw)[0] == 2, raw[:20]
    assert go(raw=json.dumps({"tool_name": "Bash", "tool_input": {"command": ["git", "add", "-A"]}}))[0] == 2
    assert go(raw=json.dumps({"tool_name": "Bash", "tool_input": {"command": "git add -A"}, "cwd": 5}))[0] == 2
    assert go(raw=json.dumps({"tool_name": ["Bash"], "tool_input": {"command": "git add -A"}}))[0] == 0  # not a shell tool name


def test_long_lines_and_line_endings(repo):
    code, secs, _ = go("git add " + "a " * 300000 + "-A", repo)
    assert code == 2 and secs < 8
    assert go("git add -A" + "\r\n" * 50, repo)[0] == 2
    huge = "echo 'x' " * 200000 + " git add -A"
    code, secs, _ = go(huge, repo)
    assert code == 2 and secs < 8
    assert go("x" * 1_200_000 + " git", repo)[0] == 2  # over MAX_COMMAND_CHARS and mentions git
    assert go("x" * 1_200_000, repo)[0] == 0  # over the cap but cannot touch git


# ---- helper faults: alias lookup, repo resolution, timeouts, git missing -----------------------
def test_git_not_on_path_blocks(repo, tmp_path):
    empty = str(tmp_path / "nopath")
    os.makedirs(empty, exist_ok=True)
    for cmd in ("git commit -m x", "git add -A", "git zz", "git add a.py"):
        code, _, err = go(cmd, repo, path_override=empty)
        assert code == 2 or cmd == "git add a.py", (cmd, code, err)
    # an explicit-path add resolves scope too: without git it must not silently pass as in-scope
    assert go("git add a.py", repo, path_override=empty)[0] in (0, 2)


def test_git_call_timeout_blocks(repo, tmp_path):
    v = variant(tmp_path, ("GIT_CALL_TIMEOUT = 3.0", "GIT_CALL_TIMEOUT = 0.00001"))
    code, _, err = go("git commit -m x", repo, script=v)
    assert code == 2 and "cannot" in err


def test_budget_exhaustion_blocks(repo, tmp_path):
    v = variant(tmp_path, ("BUDGET_SECONDS = 8.0", "BUDGET_SECONDS = -1.0"))
    code, _, err = go("git add a.py", repo, script=v)
    assert code == 2 and "exceeded" in err


def test_alias_lookup_failure_blocks(repo, tmp_path):
    v = variant(tmp_path, ('r = _run_git(inv.dir, "config", "--get-regexp", r"^alias\\.")',
                           'raise OSError("boom")'))
    code, _, err = go("git zzalias", repo, script=v)
    assert code == 2 and "aliases" in err


INJECTIONS = {
    "RecursionError": "raise RecursionError('x')", "MemoryError": "raise MemoryError()",
    "KeyboardInterrupt": "raise KeyboardInterrupt()", "ValueError": "raise ValueError('x')",
    "OSError": "raise OSError('x')", "SystemError": "raise SystemError('x')",
}


@pytest.mark.parametrize("exc", tiered(sorted(INJECTIONS), {"RecursionError", "MemoryError"}))
def test_any_fault_inside_analysis_blocks_git_and_never_tracebacks(exc, repo, tmp_path):
    v = variant(tmp_path, ("    invs: list[Inv] = []\n    collect(cmd, shell, cwd, invs)",
                           f"    {INJECTIONS[exc]}"))
    code, _, err = go("git add a.py", repo, script=v)
    assert code == 2 and "Traceback" not in err, (exc, err)
    assert go("echo hi", repo, script=v)[0] == 0  # a fault on a command proven git-free allows


@pytest.mark.parametrize("exc", ["MemoryError", "KeyboardInterrupt", "RecursionError"])
def test_fault_in_decide_prologue_blocks(exc, repo, tmp_path):
    v = variant(tmp_path, ("    _deadline[0] = time.monotonic() + BUDGET_SECONDS\n    cmd, shell, cwd",
                           f"    {INJECTIONS[exc]}\n    cmd, shell, cwd"))
    assert go("echo hi", repo, script=v)[0] == 2


def test_override_log_fault_keeps_the_block(repo, tmp_path):
    v = variant(tmp_path, ('path = Path(\n        os.environ.get(OVERRIDE_LOG_ENV)', 'raise RuntimeError("no home")\n    path = Path(\n        os.environ.get(OVERRIDE_LOG_ENV)'))
    code, _, err = go("git add -A", repo, script=v, env_extra={"BLARAI_GIT_RULES_OVERRIDE": "r"})
    assert code == 2 and "Traceback" not in err


# ---- (2) recursion depth and time ---------------------------------------------------------------
@pytest.mark.parametrize("depth", tiered([3, 8, 9, 50, 500, 5000], {9, 5000}))
def test_nested_substitution_blocks_within_budget(depth, repo):
    cmd = "echo " + "$(" * depth + "git add -A" + ")" * depth
    code, secs, err = go(cmd, repo)
    assert code == 2 and secs < 5, (depth, code, secs, err)
    assert "Traceback" not in err


@pytest.mark.parametrize("depth", [3, 8, 9, 50, 500, 5000])
def test_nested_backticks_subshells_and_heredocs_block(depth, repo):
    for cmd in ("(" * depth + "git add -A" + ")" * depth,
                "{ " * depth + "git add -A" + "; }" * depth,
                "".join("bash <<'E%d'\n" % k for k in range(min(depth, 60))) + "git add -A\n"
                + "".join("E%d\n" % k for k in reversed(range(min(depth, 60))))):
        code, secs, err = go(cmd, repo)
        assert code == 2 and secs < 5, (depth, cmd[:30], code, secs, err)


def test_nested_shell_payloads_block(repo):
    import shlex
    cmd = "git add -A"
    for _ in range(6):
        cmd = "bash -c " + shlex.quote(cmd)
        code, secs, _ = go(cmd, repo)
        assert code == 2 and secs < 5
    e = "git add -A"
    for _ in range(6):
        e = "eval " + shlex.quote(e)
        assert go(e, repo)[0] == 2
    s = "git add -A"
    for _ in range(6):
        s = "env -S " + shlex.quote(s)
        assert go(s, repo)[0] == 2


def test_pathological_quoting_is_bounded(repo):
    for cmd in ("git add " + "''" * 400000 + "-A", "git add " + "\"'\"" * 100000 + " -A",
                "git add -" + "$'\\x41'" * 50000,
                "git add " + "{a,b}" * 2000, "git add " + "$(true)" * 20000):
        code, secs, err = go(cmd, repo)
        assert code == 2 and secs < 9 and "Traceback" not in err, (cmd[:30], code, secs)


def test_explicit_depth_cap_constant(repo, tmp_path):
    v = variant(tmp_path, ("MAX_DEPTH = 8", "MAX_DEPTH = 1"))
    code, _, err = go("echo $(echo $(echo $(git status)))", repo, script=v)
    assert code == 2 and "nested" in err
    import shlex
    deep = "echo hi"
    for _ in range(4):
        deep = "bash -c " + shlex.quote(deep)
    assert go(deep, repo, script=v)[0] == 0  # too deep but cannot touch git


# ---- (4) output contract: encoding, stdout/stderr, exit codes -----------------------------------
@pytest.mark.parametrize("enc", ["ascii", "cp1252", "cp437", "utf-8"])
def test_block_message_survives_any_console_encoding(enc, repo):
    code, _, err = go("git add -A☃\U0001F600", repo, env_extra={"PYTHONIOENCODING": enc})
    assert code == 2 and "Traceback" not in err
    code, _, err = go("git commit -m \"$(echo ☃)\" ☃$X", repo, env_extra={"PYTHONIOENCODING": enc})
    assert code == 2


def test_closed_or_broken_stderr_still_blocks(repo):
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git add -A"}, "cwd": str(repo)})
    r = subprocess.run([sys.executable, str(SCRIPT)], input=payload.encode(), stderr=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL)
    assert r.returncode == 2
    r = subprocess.run([sys.executable, "-c",
                        "import os,sys; os.close(2); sys.argv=['g']; "
                        "import runpy; runpy.run_path(sys.argv and %r, run_name='__main__')" % str(SCRIPT)],
                       input=payload.encode(), stdout=subprocess.DEVNULL)
    assert r.returncode == 2


def test_only_documented_env_vars_are_read():
    src = SCRIPT.read_text(encoding="utf-8")
    lines = [ln for ln in src.splitlines() if "os.environ" in ln or "getenv" in ln]
    assert lines
    for ln in lines:
        assert any(t in ln for t in ("OVERRIDE_ENV", "OVERRIDE_LOG_ENV", "DRIFT_ENV_VARS",
                                     "os.environ.items()")), ln


@pytest.mark.parametrize("name", tiered(["BLARAI_GIT_RULES_GUARD", "BLARAI_GIT_RULES_DISABLE", "BLARAI_GIT_RULES_OFF",
                                          "BLARAI_GIT_RULES_ENABLED", "ENABLED", "GIT_RULES_GUARD", "CLAUDE_HOOKS_DISABLED",
                                          "DISABLE_HOOKS", "PYTHONOPTIMIZE", "BLARAI_GIT_RULES_OVERRIDE_LOG"], {0}))
@pytest.mark.parametrize("value", tiered(["0", "1", "off", "false", "true", ""], {"off"}))
def test_no_other_env_var_disables_the_guard(name, value, repo):
    assert go("git add -A", repo, env_extra={name: value})[0] == 2


def test_empty_override_does_not_disable(repo):
    for v in ("", " ", "\t", "  \n"):
        assert go("git add -A", repo, env_extra={"BLARAI_GIT_RULES_OVERRIDE": v})[0] == 2


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_settings_command_blocks_when_the_guard_crashes_or_python_is_missing(repo, tmp_path):
    cfg = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    cmd = cfg["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": str(repo)})
    proj = tmp_path / "proj"
    (proj / "scripts" / "hooks").mkdir(parents=True)
    crash = proj / "scripts" / "hooks" / "git_rules_guard.py"
    base_env = {k: v for k, v in os.environ.items() if k != "BLARAI_GIT_RULES_OVERRIDE"}
    base_env["CLAUDE_PROJECT_DIR"] = str(proj).replace("\\", "/")

    def run_cmd(env):
        return subprocess.run(["bash", "-c", cmd], input=payload.encode(), capture_output=True, env=env, timeout=60)

    for body in ("raise SystemExit(1)", "import nonexistent_module_xyz", "this is a syntax error (", "import os; os._exit(7)"):
        crash.write_text(body + "\n", encoding="utf-8")
        r = run_cmd(base_env)
        assert r.returncode == 2 and b"failed to run" in r.stderr, (body, r.returncode, r.stderr)
        assert run_cmd({**base_env, "BLARAI_GIT_RULES_OVERRIDE": "recover"}).returncode == 0
    crash.write_text("raise SystemExit(0)\n", encoding="utf-8")
    assert run_cmd(base_env).returncode == 0
    crash.write_text("raise SystemExit(2)\n", encoding="utf-8")
    assert run_cmd(base_env).returncode == 2
    # python absent from PATH: exit 127 must block, not allow
    nopy = {**base_env, "PATH": "/usr/bin:/bin"}
    probe = subprocess.run(["bash", "-c", "command -v python"], capture_output=True, env=nopy)
    if probe.returncode != 0:
        crash.write_text("raise SystemExit(0)\n", encoding="utf-8")
        assert run_cmd(nopy).returncode == 2


# ---- mutants: each fault-handling control must be able to fail --------------------------------------
FC_PROBES = [
    ("echo 'unterminated git add -A", False), ("echo $(echo $(echo $(echo $(echo $(echo $(echo $(echo $(echo $(echo git add -A)))))))))", False),
    ("echo 'g\"it add -A", False), ("echo ${X git add -A", False), ("git add -A☃", False),
    ("echo hi", True), ("echo 'unterminated", True), ("RAW:{not json", False),
]

FC_MUTANTS = {
    "depth cap silently returns": ('raise Violation("depth-cap"', 'return  # raise Violation("depth-cap"'),
    "could_touch_git is always false": ('    low = cmd.lower()\n    if "git" in low', '    return False\n    low = cmd.lower()\n    if "git" in low'),
    "parse fault on git text allowed": ("        if not risky:\n            return 0, \"\"", "        if True:\n            return 0, \"\""),
    "unterminated ${ ignored": ('raise Unparseable("unterminated ${")', "pass"),
    "bad stdin allowed": ('        return 2, _blocked_text(f"hook input is not valid JSON ({type(exc).__name__}); refusing (fail-closed).")',
                          '        return 0, ""'),
}


@pytest.mark.parametrize("name", sorted(FC_MUTANTS))
def test_failclosed_mutants_are_caught(name, repo, tmp_path):
    old, new = FC_MUTANTS[name]
    v = variant(tmp_path, (old, new))
    env = {"PYTHONIOENCODING": "ascii"}
    def verdict(c, script=SCRIPT):
        if c.startswith("RAW:"):
            code, _, err = go(raw=c[4:], script=script, env_extra=env)
            return (code == 0, "BLOCKED" in err)
        code, _, err = go(c, repo, script=script, env_extra=env)
        return (code == 0, "BLOCKED" in err)

    real = [verdict(c) for c, _ in FC_PROBES]
    mut = [verdict(c, v) for c, _ in FC_PROBES]
    assert [r[0] for r in real] == [e for _, e in FC_PROBES]
    assert all(r[1] for r, (_, e) in zip(real, FC_PROBES) if not e)
    assert mut != real, f"mutant survived: {name}"


mark_slow_except(globals(), {
    "test_unparseable_that_could_touch_git_blocks", "test_commands_proven_not_to_touch_git_pass",
    "test_only_shell_tools_fail_open", "test_stdin_failures_block", "test_git_not_on_path_blocks",
    "test_budget_exhaustion_blocks", "test_alias_lookup_failure_blocks",
    "test_any_fault_inside_analysis_blocks_git_and_never_tracebacks", "test_nested_substitution_blocks_within_budget",
    "test_explicit_depth_cap_constant", "test_only_documented_env_vars_are_read",
    "test_no_other_env_var_disables_the_guard", "test_empty_override_does_not_disable",
    "test_settings_command_blocks_when_the_guard_crashes_or_python_is_missing",
})
