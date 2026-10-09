"""scripts/hf_publish.py driven through its real CLI entry point on tmp dirs; hf.exe is a fake
executable (HF_EXE) that records its calls. No network, no real upload."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import hf_publish  # noqa: E402

FAKE_PY = '''\
import json, os, sys
with open(os.environ["FAKE_HF_LOG"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps(sys.argv[1:]) + "\\n")
if sys.argv[1:3] == ["datasets", "ls"]:
    sys.stdout.write(open(os.environ["FAKE_HF_LISTING"], encoding="utf-8").read())
elif sys.argv[1] == "upload":
    print("url=https://huggingface.co/datasets/x/y/commit/abc123")
'''


@pytest.fixture
def fake_hf(tmp_path, monkeypatch):
    """A fake hf executable; returns (log_path, listing_path)."""
    py = tmp_path / "fake_hf.py"
    py.write_text(FAKE_PY, encoding="utf-8")
    if os.name == "nt":
        exe = tmp_path / "fake_hf.cmd"
        exe.write_text(f'@echo off\r\n"{sys.executable}" "{py}" %*\r\n', encoding="utf-8")
    else:
        exe = tmp_path / "fake_hf.sh"
        exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{py}" "$@"\n', encoding="utf-8")
        exe.chmod(0o755)
    log, listing = tmp_path / "calls.log", tmp_path / "listing.json"
    monkeypatch.setenv("HF_EXE", str(exe))
    monkeypatch.setenv("FAKE_HF_LOG", str(log))
    monkeypatch.setenv("FAKE_HF_LISTING", str(listing))
    return log, listing


def calls(log: Path) -> list[list[str]]:
    return [json.loads(ln) for ln in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []


def clean_dir(tmp_path: Path) -> Path:
    d = tmp_path / "ds"
    (d / "raw").mkdir(parents=True)
    (d / "speed_visits.csv").write_text("arm,decode_tps_mean\na,12.5\n", encoding="utf-8")
    (d / "raw" / "report.json").write_text(
        json.dumps({"cases": [{"id": "c1", "status": "pass", "actual": "DENY"}], "out_sha256": "ab" * 32}), encoding="utf-8")
    return d


def run(*argv: str) -> int:
    return hf_publish.main(list(argv))


GOOD_CARD = """---
license: cc-by-4.0
configs:
  - config_name: study
    data_files: ds/speed_visits.csv
---
# Study
## Setup
Intel Core Ultra 7 258V, Arc 140V iGPU, GPU driver 32.0.101.8831. OpenVINO 2026.4.0, GenAI 2026.4.0.0.
Model INT8 revision e4d8de7a25bc3007261c28785bc190c97cabd243.
## Conditions
AC power.
## Not measured
Sustained load.
## Method notes
A pre-registered limit of 5 percent.
License: CC-BY-4.0
"""


# ---- preflight --------------------------------------------------------------------------------

def test_preflight_passes_clean_dir(tmp_path, capsys):
    assert run("preflight", "--dir", str(clean_dir(tmp_path))) == 0
    assert "CLEAN" in capsys.readouterr().out


def test_preflight_catches_username(tmp_path, capsys):
    d = clean_dir(tmp_path)
    (d / "notes.txt").write_text("run by MrBla on the box", encoding="utf-8")
    assert run("preflight", "--dir", str(d)) == 1
    assert "notes.txt: contains identity string 'mrbla'" in capsys.readouterr().out


def test_preflight_catches_generated_text_field(tmp_path, capsys):
    d = clean_dir(tmp_path)
    (d / "raw" / "report.json").write_text(
        json.dumps({"cases": [{"id": "c1", "actual": "Sure, here is a long generated answer to the question"}]}), encoding="utf-8")
    assert run("preflight", "--dir", str(d)) == 1
    assert "generated-text field 'actual'" in capsys.readouterr().out


def test_preflight_allow_key_is_explicit_exemption(tmp_path):
    d = clean_dir(tmp_path)
    (d / "raw" / "r.json").write_text(json.dumps({"detail": "grader diagnostic that is longer than 24 chars"}), encoding="utf-8")
    assert run("preflight", "--dir", str(d)) == 1
    assert run("preflight", "--dir", str(d), "--allow-key", "detail") == 0


def test_preflight_catches_oversize_file(tmp_path, capsys):
    d = clean_dir(tmp_path)
    (d / "big.csv").write_text("a\n" + "1\n" * 600, encoding="utf-8")
    assert run("preflight", "--dir", str(d), "--max-bytes", "1000") == 1
    out = capsys.readouterr().out
    assert "big.csv" in out and "exceeds cap" in out


def test_preflight_catches_non_utf8_and_local_path(tmp_path, capsys):
    d = clean_dir(tmp_path)
    (d / "bad.bin").write_bytes(b"\xff\xfe\x00bad")
    (d / "paths.txt").write_text("loaded from C:\\Users\\someoneelse\\models", encoding="utf-8")
    assert run("preflight", "--dir", str(d)) == 1
    out = capsys.readouterr().out
    assert "bad.bin: not valid UTF-8" in out
    assert "paths.txt: absolute local path" in out


def test_preflight_cli_exit_code_via_subprocess(tmp_path):
    d = clean_dir(tmp_path)
    (d / "n.txt").write_text("NORTHSTAR100", encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPTS / "hf_publish.py"), "preflight", "--dir", str(d)], capture_output=True, text=True)
    assert r.returncode == 1 and "n.txt" in r.stdout


# ---- upload ------------------------------------------------------------------------------------

def test_upload_refuses_on_preflight_failure_and_never_calls_hf(tmp_path, fake_hf, capsys):
    log, _ = fake_hf
    d = clean_dir(tmp_path)
    (d / "leak.txt").write_text("C:/Users/mrbla/x", encoding="utf-8")
    assert run("upload", "--dir", str(d), "--config", "study", "--path-in-repo", "ds", "--message", "m") == 1
    assert "REFUSED" in capsys.readouterr().out
    assert calls(log) == []


def test_upload_clean_dir_calls_hf_once_with_expected_args(tmp_path, fake_hf, capsys):
    log, _ = fake_hf
    d = clean_dir(tmp_path)
    assert run("upload", "--dir", str(d), "--config", "study", "--path-in-repo", "ds", "--message", "msg one") == 0
    got = calls(log)
    assert len(got) == 1
    assert got[0] == ["upload", "--repo-type", "dataset", "--commit-message", "msg one", "--", hf_publish.REPO, str(d), "ds"]
    assert "commit/abc123" in capsys.readouterr().out
    assert not any("token" in a.lower() for a in got[0])


def test_upload_with_card_publishes_readme_second(tmp_path, fake_hf):
    log, _ = fake_hf
    d = clean_dir(tmp_path)
    card = tmp_path / "README.md"
    card.write_text(GOOD_CARD, encoding="utf-8")
    assert run("upload", "--dir", str(d), "--config", "study", "--path-in-repo", "ds", "--message", "m", "--card", str(card)) == 0
    got = calls(log)
    assert [c[0] for c in got] == ["upload", "upload"] and got[1][-1] == "README.md" and got[1][-4] == "--"


def test_upload_refuses_card_missing_config_entry(tmp_path, fake_hf):
    log, _ = fake_hf
    d = clean_dir(tmp_path)
    card = tmp_path / "README.md"
    card.write_text(GOOD_CARD.replace("config_name: study", "config_name: other"), encoding="utf-8")
    assert run("upload", "--dir", str(d), "--config", "study", "--path-in-repo", "ds", "--message", "m", "--card", str(card)) == 1
    assert calls(log) == []


def test_upload_rejects_traversal_path(tmp_path, fake_hf):
    log, _ = fake_hf
    assert run("upload", "--dir", str(clean_dir(tmp_path)), "--config", "study", "--path-in-repo", "../x", "--message", "m") == 2
    assert calls(log) == []


def test_hf_exe_absent_is_a_clear_error_with_no_fallback(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HF_EXE", str(tmp_path / "nope.exe"))
    assert run("upload", "--dir", str(clean_dir(tmp_path)), "--config", "study", "--path-in-repo", "ds", "--message", "m") == 3
    assert "hf CLI not found" in capsys.readouterr().out


def test_cli_has_no_token_argument(tmp_path):
    with pytest.raises(SystemExit):
        run("upload", "--dir", str(tmp_path), "--config", "c", "--path-in-repo", "p", "--message", "m", "--token", "hf_x")


# ---- verify ------------------------------------------------------------------------------------

def _listing(path: Path, entries: dict[str, int]) -> None:
    path.write_text(json.dumps([{"path": k, "size": v} for k, v in entries.items()]), encoding="utf-8")


def _local_sizes(d: Path) -> dict[str, int]:
    return {"ds/" + p.relative_to(d).as_posix(): p.stat().st_size for p in d.rglob("*") if p.is_file()}


def test_verify_passes_on_matching_listing(tmp_path, fake_hf, capsys):
    _, listing = fake_hf
    d = clean_dir(tmp_path)
    _listing(listing, _local_sizes(d))
    assert run("verify", "--dir", str(d), "--config", "study", "--path-in-repo", "ds") == 0


def test_verify_detects_size_mismatch(tmp_path, fake_hf, capsys):
    _, listing = fake_hf
    d = clean_dir(tmp_path)
    sizes = _local_sizes(d)
    sizes["ds/speed_visits.csv"] += 1
    _listing(listing, sizes)
    assert run("verify", "--dir", str(d), "--config", "study", "--path-in-repo", "ds") == 1
    assert "size mismatch: ds/speed_visits.csv" in capsys.readouterr().out


def test_verify_detects_missing_remote_file(tmp_path, fake_hf, capsys):
    _, listing = fake_hf
    d = clean_dir(tmp_path)
    sizes = _local_sizes(d)
    del sizes["ds/raw/report.json"]
    _listing(listing, sizes)
    assert run("verify", "--dir", str(d), "--config", "study", "--path-in-repo", "ds") == 1
    assert "missing remote: ds/raw/report.json" in capsys.readouterr().out


def test_verify_unknown_remote_size_is_a_failure(tmp_path, fake_hf):
    _, listing = fake_hf
    d = clean_dir(tmp_path)
    listing.write_text(json.dumps(list(_local_sizes(d))), encoding="utf-8")  # names only, no sizes
    assert run("verify", "--dir", str(d), "--config", "study", "--path-in-repo", "ds") == 1


# ---- card-check / plan -------------------------------------------------------------------------

def test_card_check_passes_good_card(tmp_path):
    c = tmp_path / "README.md"
    c.write_text(GOOD_CARD, encoding="utf-8")
    assert run("card-check", "--readme", str(c)) == 0


def test_card_check_flags_missing_not_measured_section(tmp_path, capsys):
    c = tmp_path / "README.md"
    c.write_text(GOOD_CARD.replace("## Not measured\nSustained load.\n", ""), encoding="utf-8")
    assert run("card-check", "--readme", str(c)) == 1
    assert "FAIL NOT-measured section" in capsys.readouterr().out


def test_card_check_flags_missing_pre_registered_limits(tmp_path, capsys):
    c = tmp_path / "README.md"
    c.write_text(GOOD_CARD.replace("pre-registered", "agreed"), encoding="utf-8")
    assert run("card-check", "--readme", str(c)) == 1
    assert "FAIL pre-registered limits" in capsys.readouterr().out


def test_plan_lists_files_and_front_matter_and_touches_nothing(tmp_path, fake_hf, capsys):
    log, _ = fake_hf
    d = clean_dir(tmp_path)
    assert run("plan", "--dir", str(d), "--config", "study", "--path-in-repo", "ds", "--message", "m") == 0
    out = capsys.readouterr().out
    assert "config_name: study" in out and "data_files: ds/speed_visits.csv" in out and "speed_visits.csv" in out
    assert calls(log) == []


# ---- F1: argv injection through free-text arguments ---------------------------------------------

@pytest.mark.parametrize("bad", [
    "--delete=*", "--revision=x", "-x", "ds/--delete=*", "ds/-x", "a//b", "./x", "C:evil", "a b", "ds;rm", "ds/..", "..", "ds\\x",
])
def test_upload_refuses_option_shaped_path_in_repo_before_any_subprocess(tmp_path, fake_hf, bad):
    log, _ = fake_hf
    assert run("upload", "--dir", str(clean_dir(tmp_path)), "--config", "study", f"--path-in-repo={bad}", "--message", "m") == 2
    assert calls(log) == []


@pytest.mark.parametrize("bad", ["--delete=*", "-m", "a\nb", "x" * 201, "bad`tick", "", " lead"])
def test_upload_refuses_option_shaped_message_before_any_subprocess(tmp_path, fake_hf, bad):
    log, _ = fake_hf
    assert run("upload", "--dir", str(clean_dir(tmp_path)), "--config", "study", "--path-in-repo", "ds", f"--message={bad}") == 2
    assert calls(log) == []


def test_upload_refuses_option_shaped_config(tmp_path, fake_hf):
    log, _ = fake_hf
    assert run("upload", "--dir", str(clean_dir(tmp_path)), "--config=--delete=*", "--path-in-repo", "ds", "--message", "m") == 2
    assert calls(log) == []


def test_plan_refuses_option_shaped_message(tmp_path, fake_hf):
    assert run("plan", "--dir", str(clean_dir(tmp_path)), "--config", "study", "--path-in-repo", "ds", "--message=--delete=*") == 2


def test_positionals_follow_a_literal_double_dash(tmp_path, fake_hf):
    log, _ = fake_hf
    assert run("upload", "--dir", str(clean_dir(tmp_path)), "--config", "study", "--path-in-repo", "ds/sub-1.2", "--message", "Phase 1: 9B (INT8)") == 0
    argv = calls(log)[0]
    i = argv.index("--")
    assert argv[i + 1:] == [hf_publish.REPO, argv[i + 2], "ds/sub-1.2"]
    assert not any(a.startswith("-") for a in argv[i + 1:])


# ---- F4: secrets, e-mail, environment identity, wider text keys, prose files ------------------------

def _problems(tmp_path, name: str, body: str, **kw) -> list[str]:
    d = clean_dir(tmp_path)
    (d / name).parent.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(body, encoding="utf-8")
    return hf_publish.preflight(d, **kw)


def _problems_in_place(tmp_path, name: str, body: str) -> list[str]:
    d = tmp_path / "ds"
    (d / name).write_text(body, encoding="utf-8")
    return hf_publish.preflight(d)


@pytest.mark.parametrize("name,body,needle", [
    ("a.csv", "k\nhf_" "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789\n", "Hugging Face token shape"),
    ("b.json", json.dumps({"x": "sk-abcdefghijklmnopqrstuvwx"}), "API-key shape"),
    ("c.json", json.dumps({"x": "AKIAABCDEFGHIJKLMNOP"}), "API-key shape"),
    ("d.txt", "Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123", "bearer/credential assignment"),
    ("e.json", json.dumps({"api_key": "abcdefghijklmnop1234"}), "bearer/credential assignment"),
    ("f.txt", "contact someone.else@example.org please", "e-mail address"),
    ("g.json", json.dumps({"email": "mr.blair.do@gmail.com"}), "e-mail address"),
    ("h.txt", "run on NORTHSTAR100", "identity string 'NORTHSTAR100'"),
    ("i.txt", "run by Mrbla", "identity string 'mrbla'"),
])
def test_preflight_refuses_secret_and_identity_shapes(tmp_path, name, body, needle):
    assert any(needle in h for h in _problems(tmp_path, name, body))


def test_preflight_refuses_current_username_and_computername(tmp_path, monkeypatch):
    monkeypatch.setenv("USERNAME", "zebulonq")
    monkeypatch.setenv("COMPUTERNAME", "BOXOFDOOM77")
    hits = _problems(tmp_path, "n.txt", "hello zebulonq and boxofdoom77")
    assert any("'zebulonq'" in h for h in hits) and any("'BOXOFDOOM77'" in h for h in hits)


def test_preflight_ignores_short_or_generic_env_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("USERNAME", "bob")
    monkeypatch.setenv("COMPUTERNAME", "user")
    assert _problems(tmp_path, "n.txt", "bob and user are fine words here") == []


@pytest.mark.parametrize("key", ["text", "prompt", "out", "output", "response", "completion", "message", "content",
                                 "answer", "reply", "answer_text"])
def test_preflight_refuses_generated_text_under_wider_key_set_at_depth(tmp_path, key):
    body = json.dumps({"a": {"b": [{"c": {key: "The budget ceiling is forty seven thousand five hundred euros."}}]}})
    assert any(f"generated-text field '{key}'" in h for h in _problems(tmp_path, "g.json", body))


@pytest.mark.parametrize("key", ["out", "text", "prompt", "output"])
def test_preflight_refuses_generated_text_in_csv_columns(tmp_path, key):
    body = f"id,{key}\n1,I searched your local knowledge bank and found nothing relevant to that\n"
    assert any(f"generated-text column '{key}'" in h for h in _problems(tmp_path, "g.csv", body))


def test_preflight_refuses_generated_text_under_an_unlisted_key_when_long(tmp_path):
    body = json.dumps({"zzz_unlisted": "w " * 400})
    assert any("free text" in h for h in _problems(tmp_path, "g.json", body))


def test_preflight_refuses_prose_in_md_and_txt(tmp_path):
    prose = "Here is a long generated paragraph " * 10
    assert any("prose line" in h for h in _problems(tmp_path, "g.md", prose))
    (tmp_path / "ds" / "g.md").unlink()
    assert any("prose line" in h for h in hf_publish.preflight(tmp_path / "ds")) is False
    assert any("prose line" in h for h in _problems_in_place(tmp_path, "g.txt", prose))


def test_preflight_still_passes_short_notes_and_labels(tmp_path):
    assert _problems(tmp_path, "notes.md", "# Notes\nshort line\n") == []


def test_preflight_allows_long_lines_in_the_arcs_own_readme_but_still_scans_it(tmp_path):
    prose = "A long authored paragraph about the study. " * 12
    assert _problems(tmp_path, "README.md", prose) == []
    assert any("e-mail address" in h for h in _problems_in_place(tmp_path, "README.md", prose + " mail me@example.org"))


@pytest.mark.parametrize("msg", ["token hf_" "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789","from me@example.org", "run on NORTHSTAR100"])
def test_upload_refuses_a_commit_message_that_carries_a_secret_or_identity(tmp_path, fake_hf, msg):
    log, _ = fake_hf
    assert run("upload", "--dir", str(clean_dir(tmp_path)), "--config", "study", "--path-in-repo", "ds", f"--message={msg}") in (1, 2)
    assert calls(log) == []


# --- front-matter data_files may be one inline path or a list (the extended qwen35_small configs) -------------

_LIST_FM = (
    "---\nlicense: cc-by-4.0\nconfigs:\n"
    "  - config_name: other\n    data_files: elsewhere/a.csv\n"
    "  - config_name: study\n    data_files:\n      - ds/speed_visits.csv\n      - ds9/speed_visits.csv\n"
    "  - config_name: third\n    data_files: ds9/x.csv\n---\n"
)


@pytest.mark.parametrize("path", ["ds", "ds9"])
def test_card_check_accepts_a_data_files_list_with_an_entry_under_the_path(path):
    fm = hf_publish._front_matter(_LIST_FM)
    assert hf_publish._config_lists_path(fm, "study", path)


def test_card_check_refuses_a_list_without_an_entry_under_the_path():
    fm = hf_publish._front_matter(_LIST_FM)
    assert not hf_publish._config_lists_path(fm, "study", "ds10")
    assert not hf_publish._config_lists_path(fm, "study", "elsewhere")


def test_card_check_does_not_borrow_another_configs_entry():
    fm = hf_publish._front_matter(_LIST_FM)
    assert not hf_publish._config_lists_path(fm, "other", "ds9")
    assert hf_publish._config_lists_path(fm, "third", "ds9")


def test_card_check_inline_form_still_works_and_missing_config_is_refused():
    fm = hf_publish._front_matter(GOOD_CARD)
    assert hf_publish._config_lists_path(fm, "study", "ds")
    assert not hf_publish._config_lists_path(fm, "nope", "ds")


def test_a_config_without_data_files_does_not_inherit_the_next_configs():
    fm = hf_publish._front_matter(
        "---\nconfigs:\n  - config_name: empty\n    default: true\n"
        "  - config_name: study\n    data_files: ds/x.csv\n---\n"
    )
    assert not hf_publish._config_lists_path(fm, "empty", "ds")
    assert hf_publish._config_lists_path(fm, "study", "ds")


def test_an_entry_must_sit_under_the_path_not_merely_start_with_it():
    fm = hf_publish._front_matter("---\nconfigs:\n  - config_name: s\n    data_files: ds10/x.csv\n---\n")
    assert not hf_publish._config_lists_path(fm, "s", "ds")
