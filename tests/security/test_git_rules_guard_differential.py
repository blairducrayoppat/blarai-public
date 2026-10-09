"""Differential harness for scripts/hooks/git_rules_guard.py (#1690).

For each command variant the REAL shell (Git Bash or pwsh) runs in a temp BlarAI-marked repo
with a shim `git` first on PATH that records its argv and does nothing else. An independent
oracle (defined here, not borrowed from the guard) decides whether the argv the shell really
produced is a blanket-staging form or a commit; the guard is then fed the same command text.

  oracle says dangerous + guard allows  => BYPASS  (test fails unless listed in RESIDUAL)
  oracle says safe      + guard blocks  => false positive (reported; fails only for MUST_ALLOW)

The shell is the arbiter of what git is called with. Variants that the shell rejects or that
never reach git record nothing and are not counted as bypasses.
"""
from __future__ import annotations

import itertools
import json
import os
import shlex
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _git_hook_helpers import mark_slow_except, tiered  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "hooks" / "git_rules_guard.py"
MARKER_DOC = "<blarai_project_instructions>x</blarai_project_instructions>\n"
# usr/bin/bash does not prepend /mingw64/bin to PATH, so a shim `git` on PATH wins
GIT_BASH = Path("C:/Program Files/Git/usr/bin/bash.exe")
BASH = str(GIT_BASH) if GIT_BASH.exists() else shutil.which("bash")
PWSH = shutil.which("pwsh")

# Bypasses that are known and accepted, each with the reason. Empty is the goal.
RESIDUAL: dict[str, str] = {}

# Variants whose real argv is safe and which the guard must keep allowing.
MUST_ALLOW = {
    "git add -- -A", "git add a.py", "git add -p a.py", "git add 'a b.py'", "git add -- a.py",
    "git commit -m x", "git commit -m \"$(cat <<'EOF'\nmsg\nEOF\n)\"",
    "git commit -m 'msg with -a and git add -A'", "git status", "git log --oneline",
    "git add -N a.py", "git add docs/.",
}

DANGEROUS_ADD = ["add -A", "add --all", "add .", "add -u", "stage -A", "add --al", "add ':/'",
                 "add -fA", "add --upd", "add -Av"]


def _git(cwd, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   capture_output=True, text=True, check=True, env=env)


def _repo(path: Path, branch: str) -> Path:
    path.mkdir(parents=True)
    _git(path, "init", "-q", "-b", "main")
    (path / "f.txt").write_text("x")
    (path / "CLAUDE.md").write_text(MARKER_DOC)
    _git(path, "add", ".")
    _git(path, "commit", "-q", "-m", "init")
    if branch != "main":
        _git(path, "checkout", "-q", "-b", branch)
    return path


# ---- independent oracle over the argv the shell really produced -------------------------------
def oracle(argv: list[str]) -> str:
    """'' if safe, else 'add-blanket' | 'commit-blanket' | 'commit'."""
    i = 0
    while i < len(argv) and argv[i].startswith("-"):
        i += 2 if argv[i] in ("-C", "-c", "--git-dir", "--work-tree") else 1
    if i >= len(argv):
        return ""
    sub, rest = argv[i], argv[i + 1:]
    if sub in ("add", "stage"):
        paths_only = False
        for a in rest:
            if paths_only:
                if a in (".", "./", ":/", ":/*", ":(top)"):
                    return "add-blanket"
            elif a == "--":
                paths_only = True
            elif a.startswith("--"):
                name = a.split("=")[0]
                if any(o.startswith(name) and len(name) > 2 for o in ("--all", "--update", "--no-ignore-removal")):
                    return "add-blanket"
            elif a.startswith("-"):
                if "A" in a or "u" in a:
                    return "add-blanket"
            elif a in (".", "./", ":/", ":/*", ":(top)", "*"):
                return "add-blanket"
    if sub == "commit":
        skip = False
        for a in rest:
            if skip:
                skip = False
            elif a in ("-m", "-F", "-C", "-c", "-t", "--message", "--file"):
                skip = True
            elif a == "--all" or (a.startswith("-") and not a.startswith("--") and "a" in a.split("m")[0]):
                return "commit-blanket"
        return "commit"
    return ""


# ---- variants ---------------------------------------------------------------------------------
def _bash_wrappers():
    q = shlex.quote
    return [
        lambda c: c, lambda c: f"cd . && {c}", lambda c: f"true; {c}", lambda c: f"{c} &\nwait",
        lambda c: f"({c})", lambda c: "{ " + c + "; }", lambda c: f"! {c}", lambda c: f"true && {c}",
        lambda c: f"false || {c}", lambda c: f"{c} | cat", lambda c: f"{c} # trailing",
        lambda c: f"if true; then {c}; fi", lambda c: f"for i in 1; do {c}; done",
        lambda c: f"while true; do {c}; break; done", lambda c: f"X=1 {c}", lambda c: f"env X=1 {c}",
        lambda c: f"env -i {c}", lambda c: f"command {c}", lambda c: f"exec {c}", lambda c: f"time {c}",
        lambda c: f"nice -n 5 {c}", lambda c: f"timeout 5 {c}", lambda c: f"bash -c {q(c)}",
        lambda c: f"sh -c {q(c)}", lambda c: f"bash -lc {q(c)}", lambda c: f"eval {q(c)}",
        lambda c: f"eval {c}", lambda c: f"echo {q(c)} | bash", lambda c: f"bash <<< {q(c)}",
        lambda c: f"bash <<'EOF'\n{c}\nEOF", lambda c: f"f() {{ {c}; }}; f",
        lambda c: f"env -S {q(c)}", lambda c: f"echo hi\n{c}", lambda c: f"cd .\n{c}",
        lambda c: f"X=$(echo hi); {c}",
    ]


BASH_HAND = [
    # quoting and escapes
    "git 'add' -A", 'git "add" "-A"', 'g"it" add -A', "git a'dd' -A", "git add -'A'", "git add $'-A'",
    r"git $'\x61dd' -A", r"git $'\141dd' -A", r"git ad\d -A", r"git add \-A", r"git add -\A",
    '"git" add -A', "'git' add -A", r"\git add -A", "git add \\\n-A", "git \\\nadd -A", "git  add\t-A",
    "git add -A\\\n", "git add ''-A", 'git add ""-A', r"git ad''d -A", "git add -A ''",
    "/usr/bin/git add -A" if False else "git add -A",
    # expansions that must fail closed
    "git add $(echo -A)", "git add `echo -A`", 'git add "$(echo -A)"', "git $(echo add) -A",
    "git add -$(echo A)", "X=-A; git add $X", "X=add; git $X -A", "git add ${X:--A}", "git add -A$Y",
    'set -- -A; git add "$@"', 'A=(add -A); git "${A[@]}"', "git add <(echo)", "echo -A | xargs git add",
    "echo . | xargs git add", "printf -- -A | xargs git add", "git a{dd,} -A", "git {add,} -A",
    "git add {-A,x}", "git add -{A,}", "git add {.,x}", "git ad{d,d} -A", "git add -{A..A}",
    "g=git; $g add -A", "g=git; ${g} add -A", 'g=git; "$g" add -A', "$(echo git) add -A",
    "`echo git` add -A", "git add -A$(true)", "git add --a$(echo ll)", "git add $(echo -A) a.py",
    "git add ~", "git add -A ${Z-}", "g''it add -A", r"$'\x67it' add -A", r"g\it add -A",
    "\"$(echo g)it\" add -A", "g\"\"it add -A",
    # git option placement and synonyms
    "git -C . add -A", "git -c x=y add -A", "git --no-pager add -A", "git -ccore.x=y add -A",
    "git --git-dir=.git add -A", "git --git-dir .git --work-tree . add -A", "git -C . -c a=b add .",
    "git add -fA", "git add -vA", "git add -- .", "git add ./", "git add ':(top)'", "git add ':/*'",
    "git add -A -- a.py", "git add a.py -A", "git add --no-ignore-removal", "git add --no-ignore-r",
    # abbreviations
    "git add --a", "git add --all=", "git add --upd", "git add --updat",
    # commit
    "git commit -a", "git commit -am x", "git commit -m x -a", "git commit --all -m x",
    "git commit --al -m x", "git commit -m x :/", "git commit -m x -- .", "git commit -sam x",
    "git commit -qa -m x", "git commit -m x -a -a",
    # must stay allowed
    "git add -- -A", "git add a.py", "git add -p a.py", "git add 'a b.py'", "git add -- a.py",
    "git commit -m x", "git commit -m \"$(cat <<'EOF'\nmsg\nEOF\n)\"",
    "git commit -m 'msg with -a and git add -A'", "git status", "git log --oneline",
    "git add -N a.py", "git add docs/.", "git add -- . ", "git add -- :/",
]

PWSH_HAND = [
    "git add -A", "& git add -A", "& 'git' add -A", '& "git" add -A', "git 'add' -A", "git add '-A'",
    "git add `-A", "git ad`d -A", "git add -A # c", "git add -A; git status", "git add -A && git status",
    "git add -A\ngit status", "git add `\n-A", "$a='-A'; git add $a", "$a=@('add','-A'); git @a",
    "git add (echo -A)", "git add $(echo -A)", 'git add "$(echo -A)"', "git (echo add) -A",
    "$x='git'; & $x add -A", "& ('g'+'it') add -A", "Invoke-Expression 'git add -A'", "iex 'git add -A'",
    "& { git add -A }", "if ($true) { git add -A }", "1..1 | % { git add -A }",
    "foreach ($i in 1) { git add -A }", "$env:X='1'; git add -A", "cmd /c git add -A",
    "& cmd /c 'git add -A'", "git add -u", "git add --all", "git add --al", "git add .", "git add ./",
    "git stage -A", "git add -fA", "git add ':/'", "git add -- .", "git add -- -A", "git add a.py",
    "git commit -am x", "git commit -a -m x", "git commit -m x", "git commit -m x :/",
    "git -C . add -A", "git -c a=b add -A", "$p=@{}; git add -A @p", "git add -A $null",
    "'git' add -A", "Write-Output hi; git add -A", "git status", "git add -p a.py",
    "iex 'Invoke-Expression ''& (''''g''''+''''it'''') a`dd $(''''-fA'''')'''",
    "Invoke-Expression 'git add ''-A'''", "iex 'git add \"\"-A\"\"'", 'iex "git add ""-A"""',
    "$a='add'; git $a -A", "git add $env:X", "git add ${env:X}", "(git add -A)",
    "try { git add -A } catch {}", "git add -A | Out-Null", "git add -A 2>&1", "git add -A *> $null",
]


def build_variants() -> list[tuple[str, str, str]]:
    """(shell, repo-kind, command). repo-kind 'feat' for staging, 'main' for commit-on-main."""
    out: list[tuple[str, str, str]] = []
    for w, form in itertools.product(_bash_wrappers(), DANGEROUS_ADD):
        out.append(("bash", "feat", w(f"git {form}")))
    for w in _bash_wrappers()[:12]:
        out.append(("bash", "main", w("git commit -m x")))
    for c in BASH_HAND:
        out.append(("bash", "feat", c))
        if "commit" in c:
            out.append(("bash", "main", c))
    for form in ["commit -m x", "'commit' -m x", "com'mit' -m x", "$(echo commit) -m x",
                 "c{ommit,} -m x", "-C . commit -m x", "commit \\\n-m x"]:
        out.append(("bash", "main", "git " + form))
    out.append(("bash", "main", "X=commit; git $X -m x"))
    out.append(("bash", "main", "echo x | xargs git commit -m"))
    for c in PWSH_HAND:
        out.append(("pwsh", "feat", c))
        if "commit" in c:
            out.append(("pwsh", "main", c))
    for form in ["commit -m x", "'commit' -m x", "& git commit -m x", "$c='commit'; git $c -m x",
                 "Invoke-Expression 'git commit -m x'"]:
        out.append(("pwsh", "main", form if "git" in form else "git " + form))
    return list(dict.fromkeys(out))


# ---- machinery --------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def world(tmp_path_factory):
    root = tmp_path_factory.mktemp("diff")
    shim_py = root / "shim.py"
    shim_py.write_text(
        "import json, os, sys\n"
        "with open(os.environ['SHIM_LOG'], 'a', encoding='utf-8') as f:\n"
        "    f.write(json.dumps(sys.argv[1:]) + '\\n')\n", encoding="utf-8")
    py = sys.executable.replace("\\", "/")
    bdir = root / "shim_bash"
    bdir.mkdir()
    (bdir / "git").write_text(f'#!/bin/sh\nexec "{py}" "{str(shim_py).replace(chr(92), "/")}" "$@"\n', newline="\n")
    pdir = root / "shim_pwsh"
    pdir.mkdir()
    (pdir / "git.cmd").write_text(f'@"{sys.executable}" "{shim_py}" %*\r\n')
    return {"feat": _repo(root / "feat", "feat/d"), "main": _repo(root / "main", "main"),
            "bdir": bdir, "pdir": pdir, "root": root}


_counter = itertools.count()


def real_argvs(world, shell: str, repo: str, cmd: str) -> list[list[str]]:
    log = world["root"] / f"log{next(_counter)}.jsonl"
    env = dict(os.environ, SHIM_LOG=str(log))
    env = {k: v for k, v in env.items() if not k.startswith("GIT_") and k != "BLARAI_GIT_RULES_OVERRIDE"}
    cwd = world[repo]
    if shell == "bash":
        env["PATH"] = str(world["bdir"]) + os.pathsep + env["PATH"]
        args = [BASH, "-c", cmd]
    else:
        env["PATH"] = str(world["pdir"]) + os.pathsep + env["PATH"]
        args = [PWSH, "-NoProfile", "-NonInteractive", "-Command", cmd]
    try:
        subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, timeout=60,
                       input="")
    except subprocess.TimeoutExpired:
        return []
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]


def guard_blocks(world, shell: str, repo: str, cmd: str) -> bool:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") and k != "BLARAI_GIT_RULES_OVERRIDE"}
    env["BLARAI_GIT_RULES_OVERRIDE_LOG"] = str(world["root"] / "ov.log")
    payload = json.dumps({"tool_name": "Bash" if shell == "bash" else "PowerShell",
                          "tool_input": {"command": cmd}, "cwd": str(world[repo])})
    r = subprocess.run([sys.executable, str(SCRIPT)], input=payload, capture_output=True, text=True,
                       env=env, timeout=90)
    return r.returncode == 2


@pytest.fixture(scope="module")
def results(world):
    if BASH is None or PWSH is None:
        pytest.skip("bash and pwsh are required for the differential harness")
    variants = build_variants()

    def one(v):
        shell, repo, cmd = v
        argvs = real_argvs(world, shell, repo, cmd)
        verdicts = [oracle(a) for a in argvs]
        dangerous = [x for x in verdicts if x and (x != "commit" or repo == "main")]
        return v, argvs, dangerous, guard_blocks(world, shell, repo, cmd)

    with ThreadPoolExecutor(max_workers=8) as ex:
        return list(ex.map(one, variants))


def test_variant_count():
    assert len(build_variants()) >= 200


def test_harness_can_see_the_shell(results):
    """The shim really records what the shell passes; most variants must reach git."""
    reached = sum(1 for _, argvs, _, _ in results if argvs)
    assert reached >= 0.8 * len(results), (reached, len(results))


def test_expansions_are_resolved_by_the_real_shell(results):
    """Evidence the oracle is not seeing the command text: expansions arrive resolved."""
    seen = {cmd: argvs for (_, _, cmd), argvs, _, _ in results}
    assert ["add", "-A"] in seen["git add $(echo -A)"] or ["add", "-A"] in seen.get("git add `echo -A`", [])
    assert ["add", "-A"] in seen[r"git $'\x61dd' -A"]
    assert ["add", "-A"] in seen["git {add,} -A"]


def test_no_bypass(results):
    bypasses = [(shell, repo, cmd, argvs) for (shell, repo, cmd), argvs, dangerous, blocked in results
                if dangerous and not blocked and cmd not in RESIDUAL]
    assert not bypasses, "\n".join(f"{s}/{r}: {c!r} -> real argv {a}" for s, r, c, a in bypasses)


def test_must_allow_stays_allowed(results):
    wrong = [(shell, cmd) for (shell, repo, cmd), argvs, dangerous, blocked in results
             if cmd in MUST_ALLOW and repo == "feat" and blocked]
    assert not wrong, wrong


def test_false_positives_are_only_expansion_forms(results):
    """Safe-argv variants the guard blocks must involve an expansion, wrapper or ambiguity."""
    fp = [(shell, repo, cmd) for (shell, repo, cmd), argvs, dangerous, blocked in results
          if argvs and not dangerous and blocked]
    for shell, repo, cmd in fp:
        assert any(ch in cmd for ch in "$`{(@*") or "xargs" in cmd or "--a" in cmd or "-- ." in cmd \
            or ":/" in cmd or "<" in cmd or "cmd /c" in cmd or "commit" in cmd or "iex" in cmd.lower() \
            or "Invoke-Expression" in cmd or "-- -A" in cmd, (shell, repo, cmd)


def test_harness_detects_a_disabled_guard(results, world, tmp_path):
    """Toggle: with the guard off, the same harness must report bypasses (it can fail)."""
    off = tmp_path / "off.py"
    off.write_text(SCRIPT.read_text(encoding="utf-8").replace("ENABLED = True", "ENABLED = False", 1),
                   encoding="utf-8")
    shutil.copy(SCRIPT.parent / "rules_common.py", tmp_path / "rules_common.py")
    sample = [(v, argvs) for v, argvs, dangerous, _ in results if dangerous][:30]
    assert len(sample) == 30

    def run_off(item):
        (shell, repo, cmd), _ = item
        payload = json.dumps({"tool_name": "Bash" if shell == "bash" else "PowerShell",
                              "tool_input": {"command": cmd}, "cwd": str(world[repo])})
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        return subprocess.run([sys.executable, str(off)], input=payload, capture_output=True,
                              text=True, env=env, timeout=60).returncode == 0

    with ThreadPoolExecutor(max_workers=8) as ex:
        allowed = list(ex.map(run_off, sample))
    assert all(allowed)


# ---- fuzzer: seeded random combinations of the constructs above -----------------------------------
import random  # noqa: E402

FUZZ_FEAT_FORMS = [["add", "-A"], ["add", "--all"], ["add", "."], ["add", "-u"], ["stage", "-A"],
                   ["add", "--al"], ["add", ":/"], ["add", "-fA"], ["add", "--", "."], ["add", "-Av"],
                   ["add", "--upd"], ["add", "a.py"], ["add", "--", "-A"], ["status"], ["add", "-p", "a.py"]]
FUZZ_MAIN_FORMS = [["commit", "-m", "x"], ["commit", "-a", "-m", "x"], ["commit", "-am", "x"]]


def _bash_tok(tok: str, rng: random.Random, pre: list[str]) -> str:
    k = rng.randrange(14)
    if k <= 2 or not tok:
        return tok
    if k == 3:
        return "'" + tok.replace("'", "'\"'\"'") + "'"
    if k == 4:
        return '"' + tok + '"'
    if k == 5:
        i = rng.randrange(len(tok))
        return tok[:i] + "\\" + tok[i:]
    if k == 6:
        i = rng.randrange(len(tok) + 1)
        return tok[:i] + rng.choice(["''", '""']) + tok[i:]
    if k == 7:
        return "$'" + "".join("\\x%02x" % ord(c) for c in tok) + "'"
    if k == 8:
        v = "V%d" % rng.randrange(1000)
        pre.append(f"{v}={shlex.quote(tok)};")
        return rng.choice(["$" + v, '"$' + v + '"', "${" + v + "}"])
    if k == 9:
        return "$(printf %%s %s)" % shlex.quote(tok)
    if k == 10:
        return "`printf %%s %s`" % shlex.quote(tok)
    if k == 11:
        return "{%s,%s}" % (tok, tok)
    if k == 12:
        return "".join(rng.choice([c, "\\" + c, "'" + c + "'"]) for c in tok)
    return '"$(printf %%s %s)"' % shlex.quote(tok)


def _bash_wrappers_fuzz():
    q = shlex.quote
    return [lambda c: f"X=1 {c}", lambda c: f"env {c}", lambda c: f"command {c}", lambda c: f"nice {c}",
            lambda c: f"timeout 5 {c}", lambda c: f"time {c}", lambda c: f"exec {c}",
            lambda c: f"bash -c {q(c)}", lambda c: f"sh -c {q(c)}", lambda c: f"eval {q(c)}",
            lambda c: f"bash -lc {q(c)}", lambda c: f"({c})", lambda c: "{ " + c + "; }",
            lambda c: f"if true; then {c}; fi", lambda c: f"echo hi; {c}", lambda c: f"{c} | cat",
            lambda c: f"{c} &\nwait", lambda c: f"echo {q(c)} | bash", lambda c: f"bash <<< {q(c)}",
            lambda c: f"bash <<'EOF'\n{c}\nEOF", lambda c: f"X=$(echo hi); {c}", lambda c: f"true && {c}",
            lambda c: f"false || {c}", lambda c: f"! {c}", lambda c: f"{c} # x",
            lambda c: f"for i in 1; do {c}; done", lambda c: f"f() {{ {c}; }}; f",
            lambda c: f"env -S {q(c)}", lambda c: f"cd .\n{c}", lambda c: f"echo $({c})",
            lambda c: f"echo `{c}`", lambda c: f"xargs -a /dev/null {c}"]


def gen_bash(rng: random.Random) -> tuple[str, str, str]:
    main = rng.random() < 0.22
    form = rng.choice(FUZZ_MAIN_FORMS if main else FUZZ_FEAT_FORMS)
    pre: list[str] = []
    head = rng.choice(["git", "git", "git", "'git'", '"git"', "\\git", "g''it", 'g"i"t', "$'\\x67it'",
                       "$(printf %s git)", "`printf %s git`"])
    if rng.random() < 0.1:
        v = "G%d" % rng.randrange(1000)
        pre.append(f"{v}=git;")
        head = rng.choice(["$" + v, '"$' + v + '"', "${" + v + "}"])
    toks = [head] + [_bash_tok(t, rng, pre) for t in form]
    sp = [rng.choice([" ", " ", " ", "  ", "\t", " \\\n"]) for _ in toks]
    cmd = "".join(t + s for t, s in zip(toks, sp)).rstrip()
    cmd = "".join(pre) + cmd
    wr = _bash_wrappers_fuzz()
    for _ in range(rng.choice([0, 0, 1, 1, 2, 3])):
        cmd = rng.choice(wr)(cmd)
    return ("bash", "main" if main else "feat", cmd)


def _ps_tok(tok: str, rng: random.Random, pre: list[str]) -> str:
    k = rng.randrange(9)
    if k <= 2 or not tok:
        return tok
    if k == 3:
        return "'" + tok.replace("'", "''") + "'"
    if k == 4:
        return '"' + tok + '"'
    if k == 5:
        cands = [i for i, c in enumerate(tok) if c not in "abfnrtv0`$"]
        return tok[:cands[0]] + "`" + tok[cands[0]:] if cands else tok
    if k == 6:
        v = "v%d" % rng.randrange(1000)
        pre.append(f"${v}='{tok}';")
        return "$" + v
    if k == 7:
        return "$('" + tok + "')"
    return "('" + tok + "')"


def gen_pwsh(rng: random.Random) -> tuple[str, str, str]:
    main = rng.random() < 0.22
    form = rng.choice(FUZZ_MAIN_FORMS if main else FUZZ_FEAT_FORMS)
    pre: list[str] = []
    toks = [rng.choice(["git", "git", "& git", "& 'git'", '& "git"', "& ('g'+'it')", "'git'"])]
    if rng.random() < 0.15:
        pre.append("$g='git';")
        toks = ["& $g"]
    toks += [_ps_tok(t, rng, pre) for t in form]
    if rng.random() < 0.12 and len(form) >= 2:
        toks = ["git", "@a"]
        pre = ["$a=@(%s);" % ",".join("'%s'" % t for t in form)]
    cmd = "".join(pre) + " ".join(toks)
    wr = [lambda c: f"& {{ {c} }}", lambda c: f"if ($true) {{ {c} }}", lambda c: f"1..1 | % {{ {c} }}",
          lambda c: "Invoke-Expression '" + c.replace("'", "''") + "'",
          lambda c: "iex '" + c.replace("'", "''") + "'", lambda c: f"try {{ {c} }} catch {{}}",
          lambda c: f"{c}; echo hi", lambda c: f"echo hi; {c}", lambda c: f"foreach ($i in 1) {{ {c} }}",
          lambda c: f"{c} | Out-Null", lambda c: f"({c})", lambda c: f"{c} # x"]
    for _ in range(rng.choice([0, 0, 1, 1, 2])):
        cmd = rng.choice(wr)(cmd)
    return ("pwsh", "main" if main else "feat", cmd)


def fuzz_variants(seed: int, n_bash: int, n_pwsh: int) -> list[tuple[str, str, str]]:
    rng = random.Random(seed)
    out = [gen_bash(rng) for _ in range(n_bash)] + [gen_pwsh(rng) for _ in range(n_pwsh)]
    return list(dict.fromkeys(out))


def guard_code(world, shell: str, repo: str, cmd: str, script: Path = SCRIPT) -> int:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") and k != "BLARAI_GIT_RULES_OVERRIDE"}
    env["BLARAI_GIT_RULES_OVERRIDE_LOG"] = str(world["root"] / "ov.log")
    payload = json.dumps({"tool_name": "Bash" if shell == "bash" else "PowerShell",
                          "tool_input": {"command": cmd}, "cwd": str(world[repo])})
    r = subprocess.run([sys.executable, str(script)], input=payload, capture_output=True, text=True,
                       env=env, timeout=90)
    if r.returncode not in (0, 2):  # the exit-1 class fails OPEN: keep the evidence
        (world["root"] / "crash.log").open("a", encoding="utf-8").write(
            f"{r.returncode} {cmd!r} {r.stderr[-400:]!r}\n")
    return r.returncode


def _dangerous(argvs, repo):
    return [x for x in (oracle(a) for a in argvs) if x and (x != "commit" or repo == "main")]


def run_fuzz(world, variants, script: Path = SCRIPT):
    _LAST_WORLD_ROOT[:] = [world["root"]]
    def one(v):
        shell, repo, cmd = v
        argvs = real_argvs(world, shell, repo, cmd)
        return v, argvs, _dangerous(argvs, repo), guard_code(world, shell, repo, cmd, script)

    with ThreadPoolExecutor(max_workers=8) as ex:
        return list(ex.map(one, variants))


def CRASH_LOG():
    p = _LAST_WORLD_ROOT[0] / "crash.log" if _LAST_WORLD_ROOT else None
    return p.read_text(encoding="utf-8")[:1500] if p and p.exists() else ""


_LAST_WORLD_ROOT: list = []


def _check_fuzz(results):
    crashes = [(v, code) for v, _, _, code in results if code not in (0, 2)]
    assert not crashes, f"guard exit codes other than 0/2 (1 = fail OPEN): {crashes[:5]} {CRASH_LOG()}"
    bypasses = [(v, argvs) for v, argvs, dangerous, code in results if dangerous and code == 0]
    assert not bypasses, f"{len(bypasses)} bypasses, first 10:\n" + "\n".join(
        f"{v[0]}/{v[1]}: {v[2]!r} -> {a}" for v, a in bypasses[:10])
    reached = sum(1 for _, argvs, _, _ in results if argvs)
    dangerous_n = sum(1 for _, _, d, _ in results if d)
    assert reached >= 0.6 * len(results), (reached, len(results))
    assert dangerous_n >= 0.3 * len(results), (dangerous_n, len(results))
    return dangerous_n, reached


def _need_shells():
    if BASH is None or PWSH is None:
        pytest.skip("bash and pwsh are required")


def test_fuzz_default_subset(world):
    _need_shells()
    _check_fuzz(run_fuzz(world, fuzz_variants(1690, 220, 40)))


@pytest.mark.slow
@pytest.mark.parametrize("seed", [20261005, 424242])
def test_fuzz_full_2000(world, seed):
    """2000 seeded variants per seed (run with: pytest -m slow tests/security/test_git_rules_guard_differential.py)."""
    _need_shells()
    variants = fuzz_variants(seed, 1740, 300)
    assert len(variants) >= 1900
    _check_fuzz(run_fuzz(world, variants))


def test_fuzz_detects_a_disabled_guard(world, tmp_path):
    _need_shells()
    off = tmp_path / "off.py"
    off.write_text(SCRIPT.read_text(encoding="utf-8").replace("ENABLED = True", "ENABLED = False", 1),
                   encoding="utf-8")
    shutil.copy(SCRIPT.parent / "rules_common.py", tmp_path / "rules_common.py")
    res = run_fuzz(world, fuzz_variants(5, 40, 10), script=off)
    assert sum(1 for _, _, d, code in res if d and code == 0) >= 10


GARBAGE_ALPHABET = ["git", " add ", " -A", "commit", "'", '"', "$(", ")", "`", "${", "}", "\\", "\n", "<<", "EOF",
                    "{a,b}", "$X", "&&", ";", "|", "(", "eval ", "bash -c ", "\x00", "☃", "\ud800", "&", "<(",
                    "$'", "\\x", " ", "\t", "\r\n"]


def test_garbage_never_crashes_or_fails_open(world):
    """Random token soup: exit code must be 0 or 2 (never 1 / a traceback)."""
    rng = random.Random(77)
    cases = ["".join(rng.choice(GARBAGE_ALPHABET) for _ in range(rng.randrange(1, 40))) for _ in range(400)]

    def one(c):
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") and k != "BLARAI_GIT_RULES_OVERRIDE"}
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": c}, "cwd": str(world["feat"])})
        r = subprocess.run([sys.executable, str(SCRIPT)], input=payload.encode("utf-8", "surrogatepass"),
                           capture_output=True, env=env, timeout=90)
        return c, r.returncode, r.stderr

    with ThreadPoolExecutor(max_workers=8) as ex:
        out = list(ex.map(one, cases))
    bad = [(c, code) for c, code, _ in out if code not in (0, 2)]
    assert not bad, bad[:5]
    assert not [c for c, _, err in out if b"Traceback" in err]


mark_slow_except(globals(), {"test_variant_count", "test_fuzz_default_subset", "test_fuzz_detects_a_disabled_guard"})
