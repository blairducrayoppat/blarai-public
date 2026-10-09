"""#1690 final items: --update shows a SANITISED two-baseline review and binds the lead's approval to a DIGEST of
exactly what will be installed; the swap never has a moment in which a code commit on main can succeed.

Fast core: refusal without reason / approval, digest binding (wrong digest, main moved after the review), the
digest's content, sanitisation, unsafe-content refusal, drift flag, dry run, logging, rollback, one probe inside the
swap. Slow tier: the remaining unsafe-content kinds, a probe before EVERY replacement, a commit loop from another
process during --update, a tampered stage, and the mutants of every new control.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _git_hook_helpers import approved, commit, env, git, inst, installer, make_repo, quiet, record, stage  # noqa: E402

INSTALL_LOG = "blarai-install.log"
HOOK = "scripts/hooks/reference_transaction.py"


@pytest.fixture()
def tmp(tmp_path):
    return tmp_path


def change_main(repo, text="# a legitimate change\n", raw: bytes | None = None):
    p = repo / HOOK
    p.write_bytes(p.read_bytes() + (raw if raw is not None else ("\n" + text).encode("utf-8")))
    quiet(repo, "commit", "-qam", "change a hook")


def fingerprint(repo):
    files = {p.relative_to(inst(repo)).as_posix(): p.read_bytes() for p in inst(repo).rglob("*") if p.is_file()}
    rec = repo / ".git" / "blarai-install.json"
    return files, (rec.read_bytes() if rec.exists() else None)


def log_lines(repo):
    return [json.loads(x) for x in (repo / ".git" / INSTALL_LOG).read_text().splitlines()]


def digest_of(out: str) -> str:
    return re.search(r"^DIGEST: ([0-9a-f]{64})$", out, re.M).group(1)


# ---- consent: reason and a digest-bound approval ------------------------------------------------------------
def test_update_without_approval_prints_the_review_and_digest_exits_3_and_changes_nothing(tmp):
    repo = make_repo(tmp, "r")
    change_main(repo)
    before = fingerprint(repo)
    r = installer(repo, "--update", "--reason", "reviewed")
    assert r.returncode == 3 and "NOT APPLIED" in r.stdout and "--approve " + digest_of(r.stdout) in r.stdout
    assert "+# a legitimate change" in r.stdout and "installed/hooks/reference_transaction.py" in r.stdout
    assert "diff stat: 1 changed, 0 added, 0 removed" in r.stdout and "interpreter: recorded" in r.stdout
    assert "BASELINE: installed copy against the install record" in r.stdout and "no drift" in r.stdout
    assert fingerprint(repo) == before and installer(repo, "--check").returncode == 1


def test_update_without_a_reason_is_refused_even_with_the_right_digest(tmp):
    repo = make_repo(tmp, "r")
    change_main(repo)
    before = fingerprint(repo)
    d = digest_of(installer(repo, "--update", "--dry-run").stdout)
    for flags in (("--approve", d), ("--approve", d, "--reason", "   ")):
        r = installer(repo, "--update", *flags)
        assert r.returncode == 3 and '--reason "<why>"' in r.stdout
    assert fingerprint(repo) == before


def test_a_wrong_digest_is_refused_and_nothing_changes(tmp):
    repo = make_repo(tmp, "r")
    change_main(repo)
    before = fingerprint(repo)
    r = installer(repo, "--update", "--reason", "x", "--approve", "0" * 64)
    assert r.returncode == 3 and "what you read is not what would be installed" in r.stdout
    assert fingerprint(repo) == before


def test_the_approval_dies_when_main_moves_after_the_review(tmp):
    repo = make_repo(tmp, "r")
    change_main(repo)
    d = digest_of(installer(repo, "--update", "--dry-run").stdout)
    change_main(repo, "# a second, unreviewed change\n")  # main's tip moves between display and approval
    before = fingerprint(repo)
    r = installer(repo, "--update", "--reason", "x", "--approve", d)
    assert r.returncode == 3 and "what you read is not what would be installed" in r.stdout
    assert fingerprint(repo) == before
    assert approved(repo, "second look").returncode == 0 and installer(repo, "--check").returncode == 0


def test_the_digest_is_the_sha256_of_the_printed_covers_lines_and_those_hold_the_independent_hashes(tmp):
    import hashlib
    repo = make_repo(tmp, "r")
    change_main(repo)
    out = installer(repo, "--update", "--dry-run").stdout
    lines = covers(out)
    assert hashlib.sha256("\n".join(lines).encode()).hexdigest() == digest_of(out)
    assert lines[0] == git(repo, "rev-parse", "main").stdout.strip()
    paths = git(repo, "ls-tree", "-r", "--name-only", "main", "--", "scripts/githooks", "scripts/hooks").stdout.split()
    keys = {f"githooks/{p.rsplit('/', 1)[1]}": p for p in paths if p.startswith("scripts/githooks/")}
    keys.update({f"hooks/{p.rsplit('/', 1)[1]}": p for p in paths if p.startswith("scripts/hooks/")
                 and p.rsplit("/", 1)[1] in ("git_native_pre_commit.py", "reference_transaction.py", "rules_common.py")})
    for k in sorted(keys):
        blob = subprocess.run(["git", "-C", str(repo), "show", f"main:{keys[k]}"], capture_output=True).stdout
        assert f"{k}:{hashlib.sha256(blob).hexdigest()}" in lines
    rec = record(repo)
    for fact in (f"interpreter_hash:{rec['interpreter_hash']}", f"base_interpreter_hash:{rec['base_interpreter_hash']}",
                 f"pyvenv_cfg_sha256:{rec['pyvenv_cfg_sha256']}", f"previous_hooks_path:{rec['previous_hooks_path']}"):
        assert fact in lines


def test_dry_run_prints_the_review_and_changes_nothing_even_with_a_valid_approval(tmp):
    repo = make_repo(tmp, "r")
    change_main(repo)
    before = fingerprint(repo)
    d = digest_of(installer(repo, "--update", "--dry-run").stdout)
    r = installer(repo, "--update", "--dry-run", "--approve", d, "--reason", "x")
    assert r.returncode == 0 and "dry run: nothing changed" in r.stdout and "+# a legitimate change" in r.stdout
    assert fingerprint(repo) == before and len(log_lines(repo)) == 1


def test_the_log_carries_reason_digest_diff_stat_source_commit_and_removed_files(tmp):
    repo = make_repo(tmp, "r")
    change_main(repo)
    stray = inst(repo) / "hooks" / "stray.py"
    stray.write_text("print('planted')\n")
    r = approved(repo, "merged the hook change", "--accept-drift")
    assert r.returncode == 0
    last = log_lines(repo)[-1]
    assert last["action"] == "update" and last["reason"] == "merged the hook change"
    assert last["source_commit"] == git(repo, "rev-parse", "main").stdout.strip() and len(last["digest"]) == 64
    assert last["diff_stat"].startswith("1 changed, 0 added, 1 removed") and last["files_removed"] == ["hooks/stray.py"]
    assert last["accepted_drift"] is True and [d[:2] for d in last["drift"]] == [["hooks/stray.py", "UNRECORDED"]]
    assert not stray.exists() and installer(repo, "--check").returncode == 0


def test_the_review_names_the_source_commit_its_subject_author_and_date(tmp):
    repo = make_repo(tmp, "r")
    change_main(repo)
    out = installer(repo, "--update", "--dry-run").stdout
    assert f"main {git(repo, 'rev-parse', 'main').stdout.strip()} author t date " in out and "subject change a hook" in out


def test_an_up_to_date_install_needs_no_flags(tmp):
    repo = make_repo(tmp, "r")
    r = installer(repo, "--update")
    assert r.returncode == 0 and r.stdout.startswith("already up to date")


# ---- display differential: what is printed is sanitised, and unsafe content is refused -----------------------
def test_the_printed_diff_shows_control_and_non_ascii_characters_as_visible_escapes(tmp):
    repo = make_repo(tmp, "r")
    hidden = "x = 1\r# shown​а\x08\x07é\U0001F600" + "y" * 600 + "\n"
    change_main(repo, raw=("\n" + hidden).encode("utf-8"))
    r = installer(repo, "--update", "--dry-run")
    assert r.returncode == 0
    for raw in ("\r", "​", "а", "\x08", "\x07", "é", "\U0001F600", "\x1b"):
        assert raw not in r.stdout.replace("\r\n", "\n"), repr(raw)
    for shown in ("\\r", "\\u200b", "\\u0430", "\\x08", "\\x07", "\\xe9", "\\U0001f600"):
        assert shown in r.stdout, shown
    assert "...[+" not in r.stdout and r.stdout.count("y") >= 600  # a long line continues, it is never cut
    new = (repo / HOOK).read_bytes()
    import hashlib
    assert f"{len(new)} bytes, sha256 {hashlib.sha256(new).hexdigest()}" in r.stdout


@pytest.mark.parametrize("payload,why", [
    (b"\n# \x1b[2J\x1b[Hall clear\n", "contains ESC"),
    pytest.param(b"\n# nul \x00 byte\n", "contains NUL", marks=pytest.mark.slow),
    pytest.param("\n# ‮ bidi override\n".encode(), "contains bidi control characters", marks=pytest.mark.slow),
    pytest.param(b"\n# bad \xff\xfe utf8\n", "is not valid UTF-8", marks=pytest.mark.slow),
])
def test_a_changed_file_with_esc_nul_bidi_or_bad_utf8_is_refused_whatever_flags_are_given(tmp, payload, why):
    repo = make_repo(tmp, "r")
    change_main(repo, raw=payload)
    before = fingerprint(repo)
    for flags in (("--dry-run",), ("--reason", "x", "--approve", "0" * 64, "--accept-drift")):
        r = installer(repo, "--update", *flags)
        assert r.returncode == 4 and why in r.stdout and "REFUSED" in r.stdout
        assert "\x1b" not in r.stdout and "\x00" not in r.stdout and "‮" not in r.stdout
    assert fingerprint(repo) == before


# ---- review baseline: drift of the installed copy against the record -----------------------------------------
def test_an_installed_file_that_differs_from_the_record_is_flagged_and_needs_accept_drift(tmp):
    repo = make_repo(tmp, "r")
    change_main(repo)
    tampered = inst(repo) / "hooks" / "rules_common.py"
    tampered.write_bytes(tampered.read_bytes() + b"\nimport os  # planted\n")
    out = installer(repo, "--update", "--dry-run").stdout
    assert "DRIFT: hooks/rules_common.py installed sha256 " in out and "recorded/hooks/rules_common.py" in out
    assert "+import os  # planted" in out
    before = fingerprint(repo)
    r = installer(repo, "--update", "--reason", "x", "--approve", digest_of(out))
    assert r.returncode == 3 and "--accept-drift" in r.stdout and fingerprint(repo) == before
    ok = installer(repo, "--update", "--reason", "x", "--approve", digest_of(out), "--accept-drift")
    assert ok.returncode == 0 and installer(repo, "--check").returncode == 0
    assert [d[:2] for d in log_lines(repo)[-1]["drift"]] == [["hooks/rules_common.py", "DRIFT"]]


def test_a_missing_record_cannot_be_checked_so_it_counts_as_drift(tmp):
    repo = make_repo(tmp, "r")
    (repo / ".git" / "blarai-install.json").unlink()
    out = installer(repo, "--update", "--dry-run").stdout
    assert "the install record is missing or unreadable" in out and "--accept-drift" in out
    assert approved(repo, "x").returncode == 3
    assert approved(repo, "x", "--accept-drift").returncode == 0


# ---- the swap ------------------------------------------------------------------------------------------------
def _harness(repo, probe_when: str, extra: str = "", approve: bool = True) -> subprocess.CompletedProcess:
    """Run the repo's own installer in-process with a hook around every file replacement: `probe` tries a code
    commit on main and prints PROBE <returncode>."""
    extra = textwrap.indent(extra, " " * 8).lstrip()
    code = textwrap.dedent(f"""
        import contextlib, io, re, subprocess, sys
        sys.path.insert(0, {str(repo / 'scripts')!r})
        import install_git_hooks as I
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            I.main(["--repo", {str(repo)!r}, "--update", "--dry-run"])
        digest = re.search(r"^DIGEST: ([0-9a-f]{{64}})$", buf.getvalue(), re.M).group(1)
        orig = I._replace
        calls = [0]
        def probe():
            r = subprocess.run(["git", "-C", {str(repo)!r}, "-c", "user.name=t", "-c", "user.email=t@t",
                                "commit", "-q", "-m", "probe"], capture_output=True, text=True)
            print("PROBE", r.returncode, flush=True)
        def rep(src, dst):
            calls[0] += 1
            if {probe_when}:
                probe()
            orig(src, dst)
        I._replace = rep
        {extra}
        sys.exit(I.main(["--repo", {str(repo)!r}, "--update", "--reason", "probe", "--approve", digest]))
    """)
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env(), timeout=600)


def _probes(r):
    return [int(x.split()[1]) for x in r.stdout.splitlines() if x.startswith("PROBE")]


def test_a_code_commit_on_main_is_refused_while_the_swap_is_under_way(tmp):
    repo = make_repo(tmp, "r")
    change_main(repo)
    stage(repo, "src/a.py")
    r = _harness(repo, "calls[0] in (1, 8)")
    assert r.returncode == 0, r.stdout + r.stderr
    probes = _probes(r)
    assert len(probes) == 2 and all(p != 0 for p in probes)
    assert installer(repo, "--check").returncode == 0 and commit(repo).returncode != 0  # intact, still refuses code
    assert not (repo / ".git" / "blarai-hooks.prev").exists() and not list((repo / ".git").glob("blarai-hooks.new*"))


def test_a_failure_during_the_swap_restores_the_old_hooks_and_record(tmp):
    repo = make_repo(tmp, "r")
    change_main(repo)
    before = fingerprint(repo)
    r = _harness(repo, "False", extra="I._write_record = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom'))")
    assert r.returncode != 0 and "boom" in r.stderr
    assert fingerprint(repo) == before
    assert not (repo / ".git" / "blarai-hooks.prev").exists() and not (repo / ".git" / "blarai-install.json.prev").exists()
    assert installer(repo, "--check").returncode == 1 and "run --update" in installer(repo, "--check").stdout


# ---- review leads W1-W8 (code-review-1690-update-consent-2026-10-05.md) ----------------------------------------
def covers(out: str) -> list[str]:
    block = out.split("DIGEST COVERS", 1)[1].split("DIGEST: ", 1)[0]
    return [ln[2:] for ln in block.splitlines()[1:] if ln.startswith("  ")]


def test_w1_a_payload_far_beyond_column_240_is_shown_in_full_on_continuation_lines(tmp):
    repo = make_repo(tmp, "r")
    change_main(repo, raw=b"\nx = 1" + b" " * 300 + b"; import os; os.system('echo PWNED')\n")
    r = installer(repo, "--update", "--dry-run")
    assert r.returncode == 0 and "PWNED" in r.stdout and "[cont] " in r.stdout and "...[+" not in r.stdout
    assert "; import os; os.system('echo PWNED')" in r.stdout and r.stdout.count("[cont] ") >= 2  # every byte, none cut


def test_w1_a_file_whose_review_would_pass_the_byte_cap_is_refused_never_abbreviated(tmp):
    repo = make_repo(tmp, "r")
    change_main(repo, raw=b"".join(b"# padding line %05d %s\n" % (i, b"x" * 60) for i in range(1000)))
    before = fingerprint(repo)
    for flags in (("--dry-run",), ("--reason", "x", "--approve", "0" * 64, "--accept-drift")):
        r = installer(repo, "--update", *flags)
        assert r.returncode == 4 and "over the 65536 cap per file" in r.stdout and "Review the file by hand" in r.stdout
    assert fingerprint(repo) == before


def _with_previous(tmp, name="r"):
    prev = tmp / "prev hooks"
    prev.mkdir(parents=True)
    (prev / "post-commit").write_text("#!/bin/sh\nexit 0\n", newline="\n")
    return make_repo(tmp, name, pre_install=lambda r: git(r, "config", "core.hooksPath", str(prev), check=True)), prev


def test_w2_the_previous_hooks_path_and_its_files_are_shown_bound_and_checked(tmp):
    repo, prev = _with_previous(tmp)
    change_main(repo)
    out = installer(repo, "--update", "--dry-run").stdout
    assert f"PREVIOUS HOOKS (chained to after our checks): recorded {prev.as_posix()}" in out.replace("\\\\", "/")
    assert "chained file post-commit sha256 " in out and any(x.startswith("previous_hooks_path:") for x in covers(out))
    evil = tmp / "evil"
    evil.mkdir()
    (evil / "pre-commit").write_text("#!/bin/sh\nexit 0\n", newline="\n")
    git(repo, "config", "--local", "blarai.originalhookspath", str(evil), check=True)
    out2 = installer(repo, "--update", "--dry-run").stdout
    assert digest_of(out2) != digest_of(out) and "CHANGED" in out2 and "chained file pre-commit sha256 " in out2
    r = installer(repo, "--update", "--reason", "x", "--approve", digest_of(out), "--accept-drift")
    assert r.returncode == 3 and "what you read is not what would be installed" in r.stdout


def test_w2_a_rewritten_previous_hooks_mirror_or_config_key_fails_check_and_status_says_degraded(tmp):
    repo, prev = _with_previous(tmp)
    assert installer(repo, "--check").returncode == 0
    mirror = repo / ".git" / "blarai-previous-hooks"
    mirror.write_text(str(tmp / "evil") + "\n")
    c, s = installer(repo, "--check"), installer(repo, "--status")
    assert c.returncode == 1 and "previous hooks path" in c.stdout
    assert s.returncode == 1 and "DEGRADED" in s.stdout and "ON for this repository" not in s.stdout
    mirror.write_text(str(prev) + "\n")
    assert installer(repo, "--check").returncode == 0
    git(repo, "config", "--local", "blarai.previoushookspath", "elsewhere", check=True)
    assert installer(repo, "--check").returncode == 1 and "DEGRADED" in installer(repo, "--status").stdout


def _venv(tmp):
    v = tmp / "venv2"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(v)], check=True, capture_output=True, timeout=300)
    return v, next(p for p in (v / "Scripts" / "python.exe", v / "bin" / "python") if p.exists())


def test_w3_the_interpreter_pin_covers_cfg_and_base_and_a_pyvenv_cfg_repoint_fails_check(tmp):
    repo = make_repo(tmp, "r", install=False)
    v, vpy = _venv(tmp)
    r = subprocess.run([str(vpy), str(repo / "scripts" / "install_git_hooks.py"), "--repo", str(repo)],
                       capture_output=True, text=True, env=env(), timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    rec = record(repo)
    assert rec["pyvenv_cfg_sha256"] and rec["base_interpreter"] and rec["base_interpreter_hash"] and rec["interpreter_real"]
    assert installer(repo, "--check").returncode == 0
    stage(repo, "docs/research/x.md")
    assert commit(repo).returncode == 0  # a companion commit on main is allowed while the pin holds
    cfg = v / "pyvenv.cfg"
    cfg.write_text(cfg.read_text() + "# repointed\n")
    c = installer(repo, "--check")
    assert c.returncode == 1 and "pyvenv_cfg_sha256 changed" in c.stdout
    stage(repo, "docs/research/y.md")
    assert commit(repo).returncode != 0  # the hook itself refuses at run time too


def test_w3_the_digest_binds_the_interpreter_path_so_an_approval_from_another_python_dies(tmp):
    repo = make_repo(tmp, "r")
    change_main(repo)
    out = installer(repo, "--update", "--dry-run").stdout
    assert any(x.startswith("interpreter:") for x in covers(out)) and "interpreter pin: real path" in out
    _, vpy = _venv(tmp)
    r = subprocess.run([str(vpy), str(repo / "scripts" / "install_git_hooks.py"), "--repo", str(repo), "--update",
                        "--reason", "x", "--approve", digest_of(out)], capture_output=True, text=True, env=env(), timeout=300)
    assert r.returncode == 3 and "what you read is not what would be installed" in r.stdout


def test_w4_accept_drift_lists_every_drifted_file_with_its_sha256_and_a_new_drift_voids_the_digest(tmp):
    repo = make_repo(tmp, "r")
    change_main(repo)
    a = inst(repo) / "hooks" / "rules_common.py"
    a.write_bytes(a.read_bytes() + b"\n# a\n")
    out = installer(repo, "--update", "--dry-run").stdout
    import hashlib
    assert f"DRIFT: hooks/rules_common.py installed sha256 {hashlib.sha256(a.read_bytes()).hexdigest()}" in out
    b = inst(repo) / "githooks" / "_lib.sh"
    b.write_bytes(b.read_bytes() + b"\n# b\n")
    (inst(repo) / "githooks" / "pre-rebase").write_text("#!/bin/sh\n")
    before = fingerprint(repo)
    r = installer(repo, "--update", "--reason", "x", "--approve", digest_of(out), "--accept-drift")
    assert r.returncode == 3 and "what you read is not what would be installed" in r.stdout
    assert fingerprint(repo) == before
    assert approved(repo, "x", "--accept-drift").returncode == 0


def test_w6_a_dry_run_during_an_approved_update_cannot_break_it(tmp):
    repo = make_repo(tmp, "r")
    change_main(repo)
    inst_py = str(repo / "scripts" / "install_git_hooks.py")
    extra = ("prev_rep = I._replace\n"
             "def rep2(a, b):\n"
             "    if calls[0] == 0:\n"
             f"        subprocess.run([sys.executable, {inst_py!r}, '--repo', {str(repo)!r}, '--update', '--dry-run'],\n"
             "                       capture_output=True)\n"
             "    prev_rep(a, b)\n"
             "I._replace = rep2")
    r = _harness(repo, "False", extra=extra)
    assert r.returncode == 0, r.stdout + r.stderr
    assert installer(repo, "--check").returncode == 0
    assert not list((repo / ".git").glob("blarai-hooks.new*"))


def test_w7_the_summary_counts_added_changed_and_removed_separately(tmp):
    repo = make_repo(tmp, "r")
    change_main(repo)
    (inst(repo) / "githooks" / "post-merge").unlink()
    r = approved(repo, "x", "--accept-drift")
    assert r.returncode == 0
    assert log_lines(repo)[-1]["diff_stat"].startswith("1 changed, 1 added, 0 removed")


def test_w8_a_file_in_scripts_githooks_outside_the_allowlist_is_refused_before_anything_changes(tmp):
    repo = make_repo(tmp, "r")
    p = repo / "scripts" / "githooks" / "post-index-change"
    p.write_text("#!/bin/sh\nexit 0\n", newline="\n")
    quiet(repo, "add", "scripts/githooks/post-index-change")
    quiet(repo, "commit", "-qm", "add a hook")
    before = fingerprint(repo)
    for flags in (("--dry-run",), ("--reason", "x", "--approve", "0" * 64)):
        r = installer(repo, "--update", *flags)
        assert r.returncode == 4 and "post-index-change is not an allowlisted hook name" in r.stdout
    assert fingerprint(repo) == before and installer(repo, "--check").returncode == 1


def _case_insensitive(tmp) -> bool:
    probe = tmp / "CaseProbe"
    probe.write_text("x")
    return (tmp / "caseprobe").exists()


@pytest.mark.slow
def test_w5_two_names_differing_only_in_case_on_main_are_refused_as_an_alias(tmp):
    repo = make_repo(tmp, "r")
    sha = git(repo, "rev-parse", "HEAD:scripts/githooks/pre-commit").stdout.strip()
    quiet(repo, "-c", "core.protectNTFS=false", "update-index", "--add", "--cacheinfo",
          f"100755,{sha},scripts/githooks/Pre-commit")
    quiet(repo, "commit", "-qm", "alias")
    before = fingerprint(repo)
    r = installer(repo, "--update", "--dry-run")
    assert r.returncode == 4 and "ALIAS: " in r.stdout and "Pre-commit" in r.stdout
    assert fingerprint(repo) == before


@pytest.mark.slow
def test_w5_a_case_renamed_installed_file_is_shown_as_a_rename_and_a_failed_swap_restores_the_exact_names(tmp):
    if not _case_insensitive(tmp):
        pytest.skip("case-sensitive file system: names that differ only in case are different files")
    repo = make_repo(tmp, "r")
    change_main(repo)
    old = inst(repo) / "hooks" / "reference_transaction.py"
    old.rename(old.with_name("Reference_Transaction.py"))
    out = installer(repo, "--update", "--dry-run").stdout
    assert "RENAME: installed hooks/Reference_Transaction.py -> hooks/reference_transaction.py" in out
    before = fingerprint(repo)
    r = _harness(repo, "False", extra="I._write_record = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom'))")
    assert r.returncode != 0 and fingerprint(repo) == before and "hooks/Reference_Transaction.py" in fingerprint(repo)[0]
    assert approved(repo, "x", "--accept-drift").returncode == 0 and installer(repo, "--check").returncode == 0
    assert "hooks/reference_transaction.py" in fingerprint(repo)[0] and "hooks/Reference_Transaction.py" not in fingerprint(repo)[0]


# ---- slow tier ---------------------------------------------------------------------------------------------
@pytest.mark.slow
def test_a_staged_file_changed_between_display_and_install_is_refused_and_nothing_is_installed(tmp):
    repo = make_repo(tmp, "r")
    change_main(repo)
    before = fingerprint(repo)
    extra = ("orig_review = I._review\n"
             "def tamper(top, staged, *a):\n"
             "    out = orig_review(top, staged, *a)\n"
             "    f = staged['dir'] / 'hooks' / 'rules_common.py'\n"
             "    f.write_bytes(f.read_bytes() + b'\\n# swapped after the review\\n')\n"
             "    return out\n"
             "I._review = tamper")
    r = _harness(repo, "False", extra=extra)
    assert r.returncode != 0 and "staged copy changed after it was shown" in (r.stdout + r.stderr)
    assert fingerprint(repo) == before


@pytest.mark.slow
def test_a_code_commit_is_refused_before_every_single_replacement_and_after_the_last(tmp):
    repo = make_repo(tmp, "r")
    change_main(repo)
    stage(repo, "src/a.py")
    r = _harness(repo, "True")
    assert r.returncode == 0, r.stdout + r.stderr
    probes = _probes(r)
    assert len(probes) >= 14 and all(p != 0 for p in probes)


@pytest.mark.slow
def test_no_code_commit_on_main_succeeds_while_update_runs_in_a_loop_from_another_process(tmp):
    repo = make_repo(tmp, "r")
    stage(repo, "src/a.py")
    stop = repo / "stop.flag"
    loop = textwrap.dedent(f"""
        import pathlib, subprocess, sys
        n = ok = 0
        while not pathlib.Path({str(stop)!r}).exists():
            r = subprocess.run(["git", "-C", {str(repo)!r}, "-c", "user.name=t", "-c", "user.email=t@t",
                                "commit", "-q", "-m", "loop"], capture_output=True, text=True)
            n += 1
            ok += r.returncode == 0
        print("ATTEMPTS", n, "SUCCESSES", ok)
    """)
    p = subprocess.Popen([sys.executable, "-c", loop], stdout=subprocess.PIPE, text=True, env=env())
    try:
        for i in range(4):
            change_main(repo, f"# change {i}\n")
            u = approved(repo, f"round {i}")
            assert u.returncode == 0, u.stdout + u.stderr
    finally:
        stop.write_text("x")
        out, _ = p.communicate(timeout=300)
    attempts, successes = int(out.split()[1]), int(out.split()[3])
    assert attempts >= 8 and successes == 0, out
    assert installer(repo, "--check").returncode == 0


# ---- slow tier: mutants of the new controls ---------------------------------------------------------------
def _mutate(repo, old, new):
    p = repo / "scripts" / "install_git_hooks.py"
    s = p.read_text(encoding="utf-8")
    assert old in s, old
    p.write_text(s.replace(old, new, 1), encoding="utf-8", newline="\n")
    quiet(repo, "commit", "-qam", "mutant")


def _own(repo, *flags):
    return subprocess.run([sys.executable, str(repo / "scripts" / "install_git_hooks.py"), "--repo", str(repo), *flags],
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env=env({"PYTHONIOENCODING": "utf-8"}), timeout=120)


def _own_approved(repo, reason="r", *flags):
    return approved(repo, reason, *flags, run=lambda r, *a: _own(r, *a))


# Each scenario returns True when the control HELD under the (possibly mutated) installer.
def s_wrong_digest_applied(tmp):
    repo = make_repo(tmp, "a")
    _mutate(repo, "elif approve.strip().lower() != digest:", "elif False:")
    change_main(repo)
    return _own(repo, "--update", "--reason", "r", "--approve", "0" * 64).returncode == 3


def s_reason_ignored(tmp):
    repo = make_repo(tmp, "b")
    _mutate(repo, "    if not reason.strip():\n        need.append", "    if False:\n        need.append")
    change_main(repo)
    d = digest_of(_own(repo, "--update", "--dry-run").stdout)
    return _own(repo, "--update", "--approve", d).returncode == 3


def s_dry_run_applies(tmp):
    repo = make_repo(tmp, "c")
    _mutate(repo, "    if dry_run:\n        print(f'dry run: nothing changed.", "    if False:\n        print(f'dry run: nothing changed.")
    change_main(repo)
    before = fingerprint(repo)
    d = digest_of(_own(repo, "--update", "--dry-run").stdout)
    _own(repo, "--update", "--dry-run", "--reason", "r", "--approve", d)
    return fingerprint(repo) == before


def s_no_rollback(tmp):
    repo = make_repo(tmp, "d")
    _mutate(repo, "    except BaseException:\n        problems = _restore_exact(", "    except BaseException:\n        raise\n        problems = _restore_exact(")
    change_main(repo)
    before = fingerprint(repo)
    _harness(repo, "False", extra="I._write_record = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom'))")
    return fingerprint(repo) == before


def s_stale_kept(tmp):
    repo = make_repo(tmp, "e")
    _mutate(repo, "            (inst / stale).unlink()", "            pass")
    change_main(repo)
    (inst(repo) / "hooks" / "stray.py").write_text("x\n")
    _own_approved(repo, "r", "--accept-drift")
    return not (inst(repo) / "hooks" / "stray.py").exists()


def s_unsafe_not_refused(tmp):
    repo = make_repo(tmp, "f")
    _mutate(repo, '    if facts["unsafe"]:', "    if False:")
    change_main(repo, raw=b"\n# \x1b[2J\n")
    return _own(repo, "--update", "--dry-run").returncode == 4


def s_escaping_off(tmp):
    repo = make_repo(tmp, "g")
    _mutate(repo, "def _esc_tokens(text: str) -> list[str]:\n    out = []", "def _esc_tokens(text: str) -> list[str]:\n    return list(text)\n    out = []")
    change_main(repo, raw="\n# a​b\rc\n".encode())
    return "​" not in _own(repo, "--update", "--dry-run").stdout


def s_drift_ignored(tmp):
    repo = make_repo(tmp, "h")
    _mutate(repo, 'if (facts["drift"] is None or facts["drift"]) and not accept_drift:', "if False:")
    change_main(repo)
    f = inst(repo) / "hooks" / "rules_common.py"
    f.write_bytes(f.read_bytes() + b"\n# drift\n")
    d = digest_of(_own(repo, "--update", "--dry-run").stdout)
    return _own(repo, "--update", "--reason", "r", "--approve", d).returncode == 3


def s_digest_without_commit(tmp):
    repo = make_repo(tmp, "i")
    _mutate(repo, "return [commit, *[", 'return ["", *[')
    change_main(repo)
    return digest_of(_own(repo, "--update", "--dry-run").stdout) == digest_of(installer(repo, "--update", "--dry-run").stdout)


def s_no_recheck_before_swap(tmp):
    repo = make_repo(tmp, "j")
    _mutate(repo, "    if _staged_digest(staged) != digest:", "    if False:")
    change_main(repo)
    extra = ("orig_review = I._review\n"
             "def tamper(top, staged, *a):\n"
             "    out = orig_review(top, staged, *a)\n"
             "    f = staged['dir'] / 'hooks' / 'rules_common.py'\n"
             "    f.write_bytes(f.read_bytes() + b'\\n# swapped\\n')\n"
             "    return out\n"
             "I._review = tamper")
    r = _harness(repo, "False", extra=extra)
    return "staged copy changed after it was shown" in (r.stdout + r.stderr)


def s_sha256_not_shown(tmp):
    repo = make_repo(tmp, "k")
    _mutate(repo, "{len(new)} bytes, sha256 {_sha256(new)}", "{len(new)} bytes")
    change_main(repo)
    return "bytes, sha256" in _own(repo, "--update", "--dry-run").stdout.split("PROPOSED CHANGE")[1]


def s_wrap_drops_continuation(tmp):
    repo = make_repo(tmp, "l")
    _mutate(repo, "        cur.append(tok)\n        n += len(tok)", "        if not lines:\n            cur.append(tok)\n        n += len(tok)")
    change_main(repo, raw=b"\nx = 1" + b" " * 300 + b"; PAYLOAD_AFTER_COLUMN_240\n")
    return "PAYLOAD_AFTER_COLUMN_240" in _own(repo, "--update", "--dry-run").stdout


def s_cap_not_enforced(tmp):
    repo = make_repo(tmp, "m")
    _mutate(repo, "if per_file and size > FILE_CAP:", "if False:")
    change_main(repo, raw=b"".join(b"# padding line %05d %s\n" % (i, b"x" * 60) for i in range(1000)))
    return _own(repo, "--update", "--dry-run").returncode == 4


def s_previous_not_bound(tmp):
    repo = make_repo(tmp, "n")
    _mutate(repo, 'f"previous_hooks_path:{prev}", f"mirror_file_now:{mirror_now}", f"config_previous_now:{config_now}",',
            'f"mirror_file_now:{mirror_now}",')
    change_main(repo)
    d1 = digest_of(_own(repo, "--update", "--dry-run").stdout)
    git(repo, "config", "--local", "blarai.originalhookspath", str(tmp / "evil"), check=True)
    return digest_of(_own(repo, "--update", "--dry-run").stdout) != d1


def s_previous_not_checked(tmp):
    repo = make_repo(tmp, "o")
    _mutate(repo, "    want = rec.get(\"previous_hooks_path\")\n", "    return []\n    want = rec.get(\"previous_hooks_path\")\n")
    (repo / ".git" / "blarai-previous-hooks").write_text(str(tmp / "evil") + "\n")
    return _own(repo, "--check").returncode == 1


def s_pin_not_compared(tmp):
    repo = make_repo(tmp, "p", install=False,
                     edits=[("scripts/hooks/rules_common.py", "            if now.get(key) != rec[key]:", "            if False:")])
    v, vpy = _venv(tmp)
    subprocess.run([str(vpy), str(repo / "scripts" / "install_git_hooks.py"), "--repo", str(repo)],
                   capture_output=True, text=True, env=env(), timeout=300, check=True)
    (v / "pyvenv.cfg").write_text((v / "pyvenv.cfg").read_text() + "# repointed\n")
    return _own(repo, "--check").returncode == 1


def s_drift_not_bound(tmp):
    repo = make_repo(tmp, "q")
    _mutate(repo, 'facts += [f"drift:{k}:{kind}:{sha}" for k, kind, sha in drift]', "facts += []")
    change_main(repo)
    f = inst(repo) / "hooks" / "rules_common.py"
    f.write_bytes(f.read_bytes() + b"\n# a\n")
    d = digest_of(_own(repo, "--update", "--dry-run").stdout)
    g = inst(repo) / "githooks" / "_lib.sh"
    g.write_bytes(g.read_bytes() + b"\n# b\n")
    return _own(repo, "--update", "--reason", "r", "--approve", d, "--accept-drift").returncode == 3


def s_alias_allowed(tmp):
    repo = make_repo(tmp, "r2")
    _mutate(repo, "        if len(keys) > 1:", "        if False:")
    _mutate(repo, 'if key.startswith("githooks/") and key.split("/", 1)[1] not in SHIMS:', "if False:")  # the allowlist also catches an alias
    sha = git(repo, "rev-parse", "HEAD:scripts/githooks/pre-commit").stdout.strip()
    quiet(repo, "-c", "core.protectNTFS=false", "update-index", "--add", "--cacheinfo",
          f"100755,{sha},scripts/githooks/Pre-commit")
    quiet(repo, "commit", "-qm", "alias")
    return _own(repo, "--update", "--dry-run").returncode == 4


def s_rollback_not_exact(tmp):
    repo = make_repo(tmp, "s")
    _mutate(repo, "problems = _restore_exact(repo, inst, old_dir) if old_dir.is_dir() else []", "problems = []")
    change_main(repo)
    before = fingerprint(repo)
    _harness(repo, "False", extra="I._write_record = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom'))")
    return fingerprint(repo) == before


def s_staging_shared(tmp):
    repo = make_repo(tmp, "t")
    _mutate(repo, 'tmp = Path(tempfile.mkdtemp(prefix=rc.INSTALL_DIR + ".new-", dir=_common(repo)))',
            'tmp = _common(repo) / "blarai-hooks.new"\n    shutil.rmtree(tmp, ignore_errors=True)\n    tmp.mkdir()')
    change_main(repo)
    inst_py = str(repo / "scripts" / "install_git_hooks.py")
    extra = ("prev_rep = I._replace\n"
             "def rep2(a, b):\n"
             "    if calls[0] == 0:\n"
             f"        subprocess.run([sys.executable, {inst_py!r}, '--repo', {str(repo)!r}, '--update', '--dry-run'],\n"
             "                       capture_output=True)\n"
             "    prev_rep(a, b)\n"
             "I._replace = rep2")
    return _harness(repo, "False", extra=extra).returncode == 0


def s_counts_added_as_changed(tmp):
    repo = make_repo(tmp, "u")
    _mutate(repo, "changed += exists", "changed += 1")
    change_main(repo)
    (inst(repo) / "githooks" / "post-merge").unlink()
    _own_approved(repo, "r", "--accept-drift")
    return log_lines(repo)[-1]["diff_stat"].startswith("1 changed, 1 added")


def s_allowlist_off(tmp):
    repo = make_repo(tmp, "v")
    _mutate(repo, 'if key.startswith("githooks/") and key.split("/", 1)[1] not in SHIMS:', "if False:")
    p = repo / "scripts" / "githooks" / "post-index-change"
    p.write_text("#!/bin/sh\nexit 0\n", newline="\n")
    quiet(repo, "add", "scripts/githooks/post-index-change")
    quiet(repo, "commit", "-qm", "add a hook")
    return _own(repo, "--update", "--dry-run").returncode == 4


@pytest.mark.slow
@pytest.mark.parametrize("scenario", [s_wrong_digest_applied, s_reason_ignored, s_dry_run_applies, s_no_rollback,
                                      s_stale_kept, s_unsafe_not_refused, s_escaping_off, s_drift_ignored,
                                      s_digest_without_commit, s_no_recheck_before_swap, s_sha256_not_shown,
                                      s_wrap_drops_continuation, s_cap_not_enforced, s_previous_not_bound,
                                      s_previous_not_checked, s_pin_not_compared, s_drift_not_bound,
                                      s_alias_allowed, s_rollback_not_exact, s_staging_shared,
                                      s_counts_added_as_changed, s_allowlist_off],
                         ids=lambda f: f.__name__)
def test_each_mutant_of_the_update_controls_is_caught(tmp, scenario):
    assert scenario(tmp) is False, f"mutant survived: {scenario.__name__}"
