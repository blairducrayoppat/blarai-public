"""#1690 review round 2 (R1-R4): the swap and its rollback never leave main unprotected, the shim runs the BASE
interpreter it verified and allows only on the guard's affirmative token, and chained previous hooks are bound
byte for byte.

Fast core: the representative failure injections, the fake-python and replaced-guard refusals, the missing
verifier, R3/R4. Slow tier: a failure injected at EVERY step of the swap in three modes (one transient failure,
every failure from that step on, a power cut), a locked file at each hook, and the mutants of every new control.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _git_hook_helpers import (  # noqa: E402
    ROOT, approved, commit, env, git, head, inst, installer, make_repo, quiet, record, stage, tiered,
)
from test_git_update_consent import (  # noqa: E402
    _harness, _own, _own_approved, _venv, change_main, covers, digest_of, fingerprint,
)


@pytest.fixture()
def tmp(tmp_path):
    return tmp_path


def rec_path(repo):
    return repo / ".git" / "blarai-install.json"


def edit_record(repo, fn):
    rec = json.loads(rec_path(repo).read_text(encoding="utf-8"))
    fn(rec)
    rec_path(repo).write_text(json.dumps(rec, indent=1) + "\n", encoding="utf-8", newline="\n")


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fake_python(tmp, body: str) -> Path:
    p = tmp / "fakepython"
    p.write_text("#!/bin/sh\n" + body, newline="\n")
    p.chmod(0o755)
    return p


def point_record_at(repo, fake: Path, sha: str | None = None):
    def fn(rec):
        rec["base_interpreter"] = fake.as_posix()
        rec["base_interpreter_sha256"] = sha or sha256_of(fake)
    edit_record(repo, fn)


def code_commit_refused(repo) -> bool:
    quiet(repo, "reset", "-q", check=False)
    stage(repo, "src/a.py")
    r = commit(repo)
    quiet(repo, "reset", "-q", check=False)
    return r.returncode != 0


# ---- R2: the base interpreter is run by its recorded path after a sha256 check, and only a token allows ------
def test_r2_a_pyvenv_cfg_repointed_at_a_fake_python_cannot_make_a_code_commit_succeed(tmp):
    repo = make_repo(tmp, "r", install=False)
    v, vpy = _venv(tmp)
    r = subprocess.run([str(vpy), str(repo / "scripts" / "install_git_hooks.py"), "--repo", str(repo)],
                       capture_output=True, text=True, env=env(), timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    fakehome = tmp / "fakehome"
    fakehome.mkdir()
    cfg = v / "pyvenv.cfg"
    lines = [ln if not ln.lower().startswith("home") else f"home = {fakehome.as_posix()}" for ln in cfg.read_text().splitlines()]
    cfg.write_text("\n".join(lines) + "\n")
    assert installer(repo, "--check").returncode == 1
    assert code_commit_refused(repo)  # the shims never use the venv launcher or the cfg


def test_r2_a_fake_python_that_exits_zero_is_refused_because_it_did_not_say_yes(tmp):
    repo = make_repo(tmp, "r")
    assert code_commit_refused(repo)
    point_record_at(repo, fake_python(tmp, "exit 0\n"))
    stage(repo, "src/a.py")
    r = commit(repo)
    assert r.returncode != 0 and "without the affirmative token" in r.stderr
    assert git(repo, "rev-list", "--count", "HEAD").stdout.strip() == "1"


def test_r2_a_fake_python_printing_the_wrong_token_is_refused(tmp):
    repo = make_repo(tmp, "r")
    point_record_at(repo, fake_python(tmp, 'echo "BLARAI-GUARD-OK ' + "0" * 64 + '"\nexit 0\n'))
    stage(repo, "src/a.py")
    r = commit(repo)
    assert r.returncode != 0 and "without the affirmative token" in r.stderr


def test_r2_a_replaced_guard_script_that_exits_zero_is_refused_even_with_a_consistent_record(tmp):
    repo = make_repo(tmp, "r")
    guard = inst(repo) / "hooks" / "git_native_pre_commit.py"
    guard.write_text("import sys\nsys.exit(0)\n", newline="\n")
    new = git(repo, "hash-object", "--no-filters", "--", str(guard)).stdout.strip()
    edit_record(repo, lambda rec: rec["hooks"].__setitem__("hooks/git_native_pre_commit.py", new))
    stage(repo, "src/a.py")
    r = commit(repo)
    assert r.returncode != 0 and "without the affirmative token" in r.stderr


def test_r2_a_base_interpreter_whose_sha256_differs_from_the_record_is_refused_before_it_runs(tmp):
    repo = make_repo(tmp, "r")
    marker = tmp / "ran.txt"
    point_record_at(repo, fake_python(tmp, f'echo ran > "{marker.as_posix()}"\nexit 0\n'), sha="0" * 64)
    stage(repo, "src/a.py")
    r = commit(repo)
    assert r.returncode != 0 and "recorded base python" in r.stderr and not marker.exists()


def test_r2_the_verifier_ignores_path_and_without_a_system_sha256sum_the_shim_fails_closed(tmp):
    sh = shutil.which("sh")
    if not sh:
        pytest.skip("no sh on PATH")
    empty = tmp / "emptybin"
    empty.mkdir()
    victim = tmp / "f.txt"
    victim.write_text("x")
    lib = tmp / "lib"
    lib.mkdir()
    src = (ROOT / "scripts" / "githooks" / "_lib.sh").read_text(encoding="utf-8")
    (lib / "_lib.sh").write_text(src, newline=NL)
    (lib / "_lib_noverifier.sh").write_text(src.replace("command -p sha256sum", "command -p sha256sum-absent"), newline=NL)
    script = 'cd "$1"; . "./$3"; echo LOADED; _sha256_of "$2"; echo "rc=$?"'

    def run(name):
        return subprocess.run([sh, "-c", script, "sh", lib.as_posix(), victim.as_posix(), name], capture_output=True,
                              text=True, env={"PATH": str(empty)}, timeout=60)
    ok = run("_lib.sh")  # an empty PATH changes nothing: the system sha256sum is used
    assert "LOADED" in ok.stdout and hashlib.sha256(b"x").hexdigest() + "rc=0" in ok.stdout
    bad = run("_lib_noverifier.sh")
    assert "LOADED" in bad.stdout and "rc=1" in bad.stdout  # no verifier: fail closed, never a fallback


def test_r2_the_record_names_the_base_interpreter_by_path_and_sha256(tmp):
    repo = make_repo(tmp, "r")
    rec = record(repo)
    assert Path(rec["base_interpreter"]).is_file() and rec["base_interpreter_sha256"] == sha256_of(Path(rec["base_interpreter"]))


NL = chr(10)


def _lying_sha256sum(tmp: Path, vouch_for: str, claim: str) -> Path:
    """A look-alike sha256sum a caller could put first on PATH: it vouches `claim` for the file named *vouch_for*."""
    d = tmp / "pathbin"
    d.mkdir(exist_ok=True)
    f = d / "sha256sum"
    body = ("#!/bin/sh"+NL+'for a in "$@"; do last=$a; done'+NL+'case "$last" in'+NL+'  *'+vouch_for+') echo "'+claim+'  $last";;'+NL+'  *) exec /usr/bin/sha256sum "$@";;'+NL+'esac'+NL)
    f.write_text(body, newline=NL)
    f.chmod(0o755)
    return d


def _attack_with_path_sha256sum(repo, tmp):
    # a fake python whose recorded sha256 is NOT its real one, printing the right token (it may read the guard),
    # plus a sha256sum first on PATH that vouches the recorded value for it
    fake = fake_python(tmp, 'h=$(command -p sha256sum "$4")'+NL+'echo "BLARAI-GUARD-OK ${h%% *}"'+NL+'exit 0'+NL)
    point_record_at(repo, fake, sha="1" * 64)
    d = _lying_sha256sum(tmp, "fakepython", "1" * 64)
    stage(repo, "src/a.py")
    r = commit(repo, env_extra={"PATH": str(d) + os.pathsep + os.environ["PATH"]})
    quiet(repo, "reset", "-q", check=False)
    return r


def test_r2_a_lookalike_sha256sum_first_on_path_cannot_vouch_for_a_changed_python(tmp):
    repo = make_repo(tmp, "r")
    r = _attack_with_path_sha256sum(repo, tmp)
    assert r.returncode != 0 and "recorded base python" in r.stderr


def _hostile_envs(tmp: Path):
    """Caller-controlled environment a hostile process could hand to `git commit`: each entry tries to choose which
    verifier, shell builtin or startup file the shim trusts."""
    d = _lying_sha256sum(tmp, "fakepython", "1" * 64)
    be = tmp / "benv.sh"
    be.write_text("sha256sum() { echo 1111111111111111111111111111111111111111111111111111111111111111; }" + NL
                  + "_sha256_of() { printf %s 1111111111111111111111111111111111111111111111111111111111111111; }" + NL
                  + "[() { return 0; }" + NL, newline=NL)
    fn = "() { return 0; }"
    return {
        "lying sha256sum first on PATH": {"PATH": str(d) + os.pathsep + os.environ["PATH"]},
        "BASH_ENV startup file": {"BASH_ENV": be.as_posix(), "ENV": be.as_posix()},
        "exported function overriding [": {"BASH_FUNC_[%%": fn, "BASH_FUNC_test%%": fn},
        "exported function overriding command and printf": {"BASH_FUNC_command%%": fn, "BASH_FUNC_printf%%": fn},
        "exported functions command and git vouching for everything": {
            "BASH_FUNC_command%%": "() { echo " + "1" * 64 + "  x; }", "BASH_FUNC_git%%": "() { echo feat/x; }"},
        "IFS set to path separators": {"IFS": "/:\ "},
        "PYTHON variables and a PATH-first python": {"PYTHONHOME": str(tmp), "PYTHONPATH": str(tmp), "PYTHONSTARTUP": str(be),
                                                    "PATH": str(d) + os.pathsep + os.environ["PATH"]},
    }


HOSTILE_KEYS = ["lying sha256sum first on PATH", "BASH_ENV startup file", "exported function overriding [",
                "exported function overriding command and printf",
                "exported functions command and git vouching for everything", "IFS set to path separators",
                "PYTHON variables and a PATH-first python"]


@pytest.mark.parametrize("key", HOSTILE_KEYS)
def test_r2_a_hostile_environment_cannot_make_the_shim_trust_a_changed_python(tmp, key):
    repo = make_repo(tmp, "r")
    fake = fake_python(tmp, 'echo "BLARAI-GUARD-OK ' + "1" * 64 + '"' + NL + "exit 0" + NL)
    point_record_at(repo, fake, sha="1" * 64)
    stage(repo, "src/a.py")
    r = commit(repo, env_extra=_hostile_envs(tmp)[key])
    quiet(repo, "reset", "-q", check=False)
    assert r.returncode != 0 and "recorded base python" in r.stderr, r.stderr
    assert git(repo, "rev-list", "--count", "HEAD").stdout.strip() == "1"


@pytest.mark.parametrize("key", HOSTILE_KEYS)
def test_r2_a_hostile_environment_cannot_move_main_through_the_reference_transaction_shim(tmp, key):
    repo = make_repo(tmp, "r", branch="feat/x")
    stage(repo, "src/a.py")
    quiet(repo, "commit", "-q", "-m", "code")
    quiet(repo, "checkout", "-q", "main")
    tip = git(repo, "rev-parse", "feat/x").stdout.strip()
    fake = fake_python(tmp, 'echo "BLARAI-GUARD-OK ' + "1" * 64 + '"' + NL + "exit 0" + NL)
    point_record_at(repo, fake, sha="1" * 64)
    before = head(repo)
    r = git(repo, "update-ref", "refs/heads/main", tip, env_extra=_hostile_envs(tmp)[key])
    assert r.returncode != 0 and head(repo) == before, r.stderr


# ---- R1: failures injected into the swap and its rollback never leave main unprotected -----------------------
def inject(mode: str, k: int = 0, target: str = "") -> str:
    return (
        "import os\n"
        "prev_rep = I._replace\n"
        "st = {'n': 0}\n"
        "def inj(a, b):\n"
        "    st['n'] += 1\n"
        f"    mode, k, target = {mode!r}, {k}, {target!r}\n"
        "    if mode == 'transient' and st['n'] == k:\n"
        "        raise PermissionError('injected')\n"
        "    if mode == 'sticky' and st['n'] >= k:\n"
        "        raise PermissionError('injected')\n"
        "    if mode == 'cut' and st['n'] == k:\n"
        "        os._exit(9)\n"
        "    if mode == 'locked' and str(b).replace(chr(92), '/').endswith(target):\n"
        "        raise PermissionError('injected')\n"
        "    prev_rep(a, b)\n"
        "I._replace = inj"
    )


def assert_protected(repo, before_names, before_fp, succeeded=False):
    names = {p.relative_to(inst(repo)).as_posix() for p in inst(repo).rglob("*") if p.is_file() and not p.name.endswith(".restore")}
    assert before_names <= names, f"hook files were removed: {sorted(before_names - names)}"
    assert code_commit_refused(repo)  # R1's probe: with the shims gone a code commit on main succeeded
    if succeeded:  # no failure was injected at this step: the update completed and the new copy verifies
        assert installer(repo, "--check").returncode == 0
        return
    state = fingerprint(repo)
    assert state == before_fp or not rec_path(repo).exists(), "neither the old copy nor a fail-closed state"


def run_injection(tmp, mode, k, target=""):
    repo = make_repo(tmp, "r")
    change_main(repo)
    before = fingerprint(repo)
    names = set(before[0])
    r = _harness(repo, "False", extra=inject(mode, k, target))
    assert_protected(repo, names, before, succeeded=r.returncode == 0)
    return repo, r, before


CASES = [("transient", 1), ("transient", 3), ("transient", 10), ("transient", 19), ("transient", 20),
         ("sticky", 1), ("sticky", 3), ("sticky", 10), ("sticky", 19), ("sticky", 20),
         ("cut", 2), ("cut", 10), ("cut", 20)]
FAST_CASES = {("transient", 3), ("sticky", 10), ("cut", 10)}


@pytest.mark.parametrize("mode,k", tiered(CASES, FAST_CASES))
def test_r1_a_failure_or_power_cut_at_each_step_never_unprotects_main(tmp, mode, k):
    run_injection(tmp, mode, k)


@pytest.mark.parametrize("mode,k", [pytest.param(m, k, marks=pytest.mark.slow) for m in ("transient", "sticky", "cut")
                                    for k in range(1, 23) if (m, k) not in CASES])
def test_r1_every_remaining_step_of_the_swap(tmp, mode, k):
    run_injection(tmp, mode, k)


LOCKS = ["githooks/pre-commit", "githooks/reference-transaction", "githooks/_lib.sh", "hooks/rules_common.py",
         "hooks/git_native_pre_commit.py", "blarai-install.json"]


@pytest.mark.parametrize("target", tiered(LOCKS, {"githooks/pre-commit"}))
def test_r1_a_locked_file_during_the_swap_and_its_rollback_never_unprotects_main(tmp, target):
    repo, r, before = run_injection(tmp, "locked", 0, target)
    assert r.returncode != 0


def test_r1_a_cut_swap_is_recoverable_by_update_and_refuses_everything_until_then(tmp):
    repo, r, before = run_injection(tmp, "cut", 10)
    assert r.returncode == 9 and not rec_path(repo).exists()
    assert code_commit_refused(repo)
    stage(repo, "docs/research/x.md")
    assert commit(repo).returncode != 0  # fail closed: even a companion commit is refused while the record is absent
    quiet(repo, "reset", "-q")
    assert approved(repo, "recover", "--accept-drift").returncode == 0 and installer(repo, "--check").returncode == 0


def test_r1_a_failed_swap_restores_the_old_copy_when_nothing_is_locked(tmp):
    repo, r, before = run_injection(tmp, "transient", 5)
    assert r.returncode != 0 and fingerprint(repo) == before and installer(repo, "--check").returncode == 1


# ---- R3 / R4 ------------------------------------------------------------------------------------------------
def _with_previous(tmp):
    prev = tmp / "prev hooks"
    prev.mkdir(parents=True)
    (prev / "pre-commit").write_text("#!/bin/sh\nexit 0\n", newline="\n")
    repo = make_repo(tmp, "r", pre_install=lambda r: git(r, "config", "core.hooksPath", str(prev), check=True))
    return repo, prev


def test_r3_a_chained_hook_changed_beyond_the_first_mebibyte_changes_the_digest(tmp):
    repo, prev = _with_previous(tmp)
    big = prev / "post-commit"
    big.write_bytes(b"#!/bin/sh\n" + b"#" * (2 << 20) + b"\nexit 0\n")
    change_main(repo)
    d1 = digest_of(installer(repo, "--update", "--dry-run").stdout)
    big.write_bytes(big.read_bytes()[:-8] + b"evil  0\n")  # same size, changed after the first MiB
    out = installer(repo, "--update", "--dry-run").stdout
    assert digest_of(out) != d1
    r = installer(repo, "--update", "--reason", "x", "--approve", d1, "--accept-drift")
    assert r.returncode == 3


def test_r3_a_chained_folder_with_more_than_100_files_is_refused_not_half_bound(tmp):
    repo, prev = _with_previous(tmp)
    for i in range(101):
        (prev / f"extra-{i:03d}").write_text("x")
    change_main(repo)
    before = fingerprint(repo)
    r = installer(repo, "--update", "--dry-run")
    assert r.returncode == 4 and "over the 100" in r.stdout
    assert fingerprint(repo) == before


def test_r4_the_review_shows_the_mirror_value_the_shims_chain_to_today(tmp):
    repo, prev = _with_previous(tmp)
    change_main(repo)
    out1 = installer(repo, "--update", "--dry-run").stdout
    assert "what the shims chain to TODAY: mirror file" in out1 and "MISMATCH" not in out1
    evil = tmp / "evil"
    evil.mkdir()
    (repo / ".git" / "blarai-previous-hooks").write_text(str(evil) + "\n")
    out2 = installer(repo, "--update", "--dry-run").stdout
    assert "MISMATCH with the install record" in out2 and "evil" in out2.split("what the shims chain to TODAY")[1]
    assert digest_of(out2) != digest_of(out1)
    assert any(x.startswith("mirror_file_now:") and "evil" in x for x in covers(out2))


# ---- slow tier: mutants of the new controls -------------------------------------------------------------------
def _mutate(repo, rel, old, new):
    p = repo / rel
    s = p.read_text(encoding="utf-8")
    assert old in s, old
    p.write_text(s.replace(old, new, 1), encoding="utf-8", newline="\n")
    quiet(repo, "commit", "-qam", "mutant")


# Each scenario returns True when the control HELD under the (possibly mutated) code.
def s_handshake_off(tmp):
    repo = make_repo(tmp, "a", edits=[("scripts/githooks/_lib.sh", '    if [ "$_out" != "BLARAI-GUARD-OK $_gsha" ]; then', "    if false; then")])
    point_record_at(repo, fake_python(tmp, "exit 0\n"))
    return code_commit_refused(repo)


def s_base_sha_unchecked(tmp):
    repo = make_repo(tmp, "b", edits=[("scripts/githooks/_lib.sh", '    if [ "$_have" != "$_pysha" ]; then', "    if false; then")])
    # the fake prints the right token (it is allowed to read the guard) but its sha256 is not the recorded one
    fake = fake_python(tmp, 'h=$(sha256sum "$4")\necho "BLARAI-GUARD-OK ${h%% *}"\nexit 0\n')
    point_record_at(repo, fake, sha="0" * 64)
    return code_commit_refused(repo)


def s_rollback_deletes_first(tmp):
    repo = make_repo(tmp, "c")
    _mutate(repo, "scripts/install_git_hooks.py", "problems = _restore_exact(repo, inst, old_dir) if old_dir.is_dir() else []",
            "problems = [(inst / k).unlink() for k in _files(inst)] and []")
    change_main(repo)
    r = _harness(repo, "False", extra=inject("locked", 0, "githooks/pre-commit"))
    return code_commit_refused(repo)


def s_record_not_aside(tmp):
    # without the record moved aside a crash mid-swap leaves mixed files with a valid-looking OLD record
    repo = make_repo(tmp, "d")
    _mutate(repo, "scripts/install_git_hooks.py", "        if had_record:\n            _replace(rec_path, rec_old)", "        if False:\n            _replace(rec_path, rec_old)")
    change_main(repo)
    _harness(repo, "False", extra=inject("cut", 3))
    return not rec_path(repo).exists()


def s_chain_hash_prefix_only(tmp):
    repo, prev = _with_previous(tmp)
    _mutate(repo, "scripts/install_git_hooks.py", "for chunk in iter(lambda: fh.read(1 << 20), b\"\"):", "for chunk in [fh.read(1 << 20)]:")
    big = prev / "post-commit"
    big.write_bytes(b"#!/bin/sh\n" + b"#" * (2 << 20) + b"\nexit 0\n")
    change_main(repo)
    d1 = digest_of(_own(repo, "--update", "--dry-run").stdout)
    big.write_bytes(big.read_bytes()[:-8] + b"evil  0\n")
    return digest_of(_own(repo, "--update", "--dry-run").stdout) != d1


def s_chain_count_unchecked(tmp):
    repo, prev = _with_previous(tmp)
    _mutate(repo, "scripts/install_git_hooks.py", "if len(names) > CHAIN_MAX_FILES:", "if False:")
    for i in range(101):
        (prev / f"extra-{i:03d}").write_text("x")
    change_main(repo)
    return _own(repo, "--update", "--dry-run").returncode == 4


def s_mirror_not_shown(tmp):
    repo, prev = _with_previous(tmp)
    _mutate(repo, "scripts/install_git_hooks.py", 'buf.append(f"  what the shims chain to TODAY:', 'buf.append(f"  (omitted):')
    change_main(repo)
    return "what the shims chain to TODAY" in _own(repo, "--update", "--dry-run").stdout


def s_sha256sum_found_on_path(tmp):
    repo = make_repo(tmp, "e", edits=[("scripts/githooks/_lib.sh", "command -p sha256sum /dev/null", "command -v sha256sum"),
                                      ("scripts/githooks/_lib.sh", "$(command -p sha256sum --", "$(sha256sum --")])
    return _attack_with_path_sha256sum(repo, tmp).returncode != 0


def s_function_overrides_not_unset(tmp):
    u = "unset -f '[' test echo printf read cd pwd command type git sed tr cat sha256sum true false exec 2>/dev/null" + NL
    edits = [("scripts/githooks/" + n, u, "") for n in ("_lib.sh", "pre-commit", "reference-transaction")]
    repo = make_repo(tmp, "f", edits=edits)
    fake = fake_python(tmp, 'echo "BLARAI-GUARD-OK ' + "1" * 64 + '"' + NL + "exit 0" + NL)
    point_record_at(repo, fake, sha="1" * 64)
    stage(repo, "src/a.py")
    r = commit(repo, env_extra={"BASH_FUNC_command%%": "() { echo " + "1" * 64 + "  x; }"})
    return r.returncode != 0


@pytest.mark.slow
@pytest.mark.parametrize("scenario", [s_handshake_off, s_base_sha_unchecked, s_rollback_deletes_first, s_record_not_aside,
                                      s_chain_hash_prefix_only, s_chain_count_unchecked, s_mirror_not_shown,
                                      s_sha256sum_found_on_path, s_function_overrides_not_unset],
                         ids=lambda f: f.__name__)
def test_each_mutant_of_the_round_two_controls_is_caught(tmp, scenario):
    assert scenario(tmp) is False, f"mutant survived: {scenario.__name__}"
