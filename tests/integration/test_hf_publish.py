"""scripts/hf_publish.py driven through its real CLI entry point on tmp dirs; hf.exe is a fake
executable (HF_EXE) that records its calls. No network, no real upload."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
# This machine's identity strings, read at run time; never literals (gate lock: tests/security/test_no_host_identity_in_tree.py).
HOST = os.environ.get("COMPUTERNAME") or __import__("platform").node()
USER = os.environ.get("USERNAME") or __import__("getpass").getuser()
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
    (d / "n.txt").write_text(HOST, encoding="utf-8")
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
    pytest.param("h.txt", f"run on {HOST}", "identity string", id="h-host"),
    pytest.param("i.txt", f"run by {USER.capitalize()}", "identity string", id="i-user"),
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


@pytest.mark.parametrize("msg", ["token hf_" "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789","from me@example.org", pytest.param(f"run on {HOST}", id="host")])
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


# --------------------------------------------------------------------------------------------- #1771 review fixes

SENTENCE48 = "The_fence_held_because_the_filter_was_persistent"
SENTENCE48_HYPHEN = "the-fence-held-because-the-filter-was-persistent"  # the lower-case, hyphenated spelling of the same text
SID_DOMAIN = "S-1-5-21-3623811015-3361044348-30300820"  # the machine itself: no relative id
SID_MACHINE = SID_DOMAIN + "-1013"


def _csv_dir(tmp_path: Path, header: str, *rows: str, schema: str | None = None, name: str = "t.csv") -> Path:
    d = tmp_path / "csvds"
    d.mkdir()
    (d / name).write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    if schema is not None:
        (d / "manifest.json").write_text(json.dumps({"schema": schema}), encoding="utf-8")
    return d


def test_known_csv_columns_are_not_widened_by_the_nep0005_columns():
    assert not (hf_publish.KNOWN_CSV_COLUMNS & set(hf_publish.NEP5_COLUMNS))
    assert len(hf_publish.KNOWN_CSV_COLUMNS) == 43
    assert not (hf_publish.NUMERIC_COLUMNS & hf_publish.NEP5_NUMERIC_COLUMNS)
    assert not (hf_publish.HASH_COLUMNS & hf_publish.NEP5_HASH_COLUMNS)


@pytest.mark.parametrize("schema", [None, "some-other-schema-v1"])
def test_nep0005_columns_are_refused_outside_a_dataset_that_declares_the_schema(tmp_path, schema):
    d = _csv_dir(tmp_path, "state_id,pass_no", "R2,1", schema=schema)
    assert any("not a known metric column" in h for h in hf_publish.preflight(d))


def test_nep0005_columns_are_accepted_in_a_dataset_that_declares_the_schema(tmp_path):
    d = _csv_dir(tmp_path, "state_id,pass_no,target,started,attempt_code",
                 "R2,1,v4:61763,2026-10-13T10:46:31.331-04:00,0x80320007", schema=hf_publish.NEP5_SCHEMA)
    assert hf_publish.preflight(d) == []


def test_every_nep0005_id_column_has_a_value_check():
    ids = {c for c, (k, _) in hf_publish.NEP5_COLUMNS.items() if k == "id"}
    assert ids <= set(hf_publish.NEP5_VALUE_CHECKS)
    # "t" and "arm" are main-set columns that the NEP-0005 export also uses; the schema pins their values
    assert set(hf_publish.NEP5_VALUE_CHECKS) - ids <= {"t", "arm"}


NEP5_BAD_CELLS = [
    ("run_id", SENTENCE48),
    ("run_id", SENTENCE48_HYPHEN),
    ("source_file", SENTENCE48_HYPHEN[:-5] + ".json"),
    ("filter_set", SENTENCE48.lower()),
    ("filter_set", "permit_maybe"),
    ("arm", SENTENCE48_HYPHEN),
    ("arm", "docs/research/containment/arm3"),
    ("arm", SID_MACHINE),
    ("arm", SID_MACHINE.lower()),
    ("arm", SID_DOMAIN),
    ("source_file", "docs/research/containment/runs/x.json"),
    ("source_file", "C:/ProgramData/BlarAI/arm3b-out/x.xml"),
    ("source_file", "D:/research-data/arm3/x.json"),
    ("source_file", "/tmp/blarai/arm3/x.json"),
    ("run_id", SID_MACHINE),
    ("result", "maybe"),
    ("state_id", "R9"),
    ("started", "yesterday"),
    ("target", "1.1.1.1:443"),
    ("attempt_code", "0x5"),
]


@pytest.mark.parametrize("col,cell", NEP5_BAD_CELLS)
def test_nep0005_id_cells_that_fail_their_check_are_refused(tmp_path, col, cell):
    d = _csv_dir(tmp_path, f"{col},pass_no", f"{cell},1", schema=hf_publish.NEP5_SCHEMA)
    assert hf_publish.preflight(d), (col, cell)


def test_nep0005_value_check_toggle_the_sentence_is_accepted_when_the_checks_are_gone(tmp_path, monkeypatch):
    assert len(SENTENCE48) == 48
    d = _csv_dir(tmp_path, "run_id,pass_no", f"{SENTENCE48},1", schema=hf_publish.NEP5_SCHEMA)
    assert hf_publish.preflight(d)
    monkeypatch.setattr(hf_publish, "NEP5_VALUE_CHECKS", {})
    assert hf_publish.preflight(d) == []


WIDE_PATHS = [
    "C:/ProgramData/BlarAI/arm3b-out/x.xml", "D:/research-data/arm3/x.json", r"E:\data\x.json", "/tmp/blarai/arm3/x.json",
    "/var/lib/x", "/etc/hosts", "/mnt/c/x", "/opt/x", "/usr/bin/x", "/data/x", "/root/blarai/arm3/",
    r"\\fileserver\research\arm3b-out" + "\\",
]
SID_SHAPES = [SID_MACHINE, SID_DOMAIN, SID_MACHINE.lower(), SID_DOMAIN.lower(), "s-1-5-21-1-2-3"]


NEP5_GOOD_CELLS = [  # the values the export carries in the columns whose checks were tightened
    ("run_id", "hold-on-20261011-144844"), ("run_id", "arm3a-20261011-165130"), ("run_id", "arm3b-20261012-150113"),
    ("source_file", "arm3b-post-reboot-result-20261012-150113.json"), ("source_file", "arm3b-arm-refused-20261012-143857.json"),
    ("source_file", "taskcheck-first-20261013-102658.json"), ("source_file", "n1-20261013-105127.json"),
    ("filter_set", "permit_on"), ("filter_set", "permit_off"),
    ("arm", "arm2"), ("arm", "arm3a"), ("arm", "arm3b"), ("arm", "arm3b-arming-refused"), ("arm", "arm3b-armed"),
]


@pytest.mark.parametrize("col,cell", NEP5_GOOD_CELLS)
def test_nep0005_id_cells_the_export_carries_pass_their_tightened_checks(tmp_path, col, cell):
    d = _csv_dir(tmp_path, f"{col},pass_no", f"{cell},1", schema=hf_publish.NEP5_SCHEMA)
    assert hf_publish.preflight(d) == [], (col, cell)


@pytest.mark.parametrize("col,cell", [("run_id", SENTENCE48_HYPHEN), ("source_file", SENTENCE48_HYPHEN[:-5] + ".json"),
                                      ("filter_set", SENTENCE48.lower()), ("arm", SENTENCE48_HYPHEN)])
def test_nep0005_value_check_toggle_a_lower_case_slug_sentence_in_each_slug_and_borrowed_column(tmp_path, monkeypatch, col, cell):
    """The spelling a mixed-case, underscored plant misses: a 48-character lower-case sentence in each of the four columns
    that used to accept it is refused by the column's check, and accepted once the checks are removed."""
    assert len(cell) == 48
    d = _csv_dir(tmp_path, f"{col},pass_no", f"{cell},1", schema=hf_publish.NEP5_SCHEMA)
    assert any(f"'{col}'" in h for h in hf_publish.preflight(d)), col
    monkeypatch.setattr(hf_publish, "NEP5_VALUE_CHECKS", {})
    assert hf_publish.preflight(d) == []


@pytest.mark.parametrize("cell", [*WIDE_PATHS, *SID_SHAPES])
def test_wide_path_and_sid_shapes_are_refused_in_a_cell_of_any_dataset(tmp_path, cell):
    d = _csv_dir(tmp_path, "arm,visit", f"{cell},1")
    assert hf_publish.preflight(d), cell


def _declared_dir(tmp_path: Path, name: str = "decl") -> Path:
    d = tmp_path / name
    d.mkdir()
    (d / "manifest.json").write_text(json.dumps({"schema": hf_publish.NEP5_SCHEMA}), encoding="utf-8")
    return d


@pytest.mark.parametrize("text", [*(f"The files are in {p} here." for p in WIDE_PATHS),
                                  *(f"The account was {s}." for s in SID_SHAPES), "Output went to D:/data/x and /tmp/y."])
def test_wide_path_and_sid_shapes_are_refused_in_prose_files_of_a_declared_dataset(tmp_path, text):
    d = _declared_dir(tmp_path)
    (d / "CARD_SECTION.md").write_text(text + "\n", encoding="utf-8")
    hits = hf_publish.preflight(d)
    assert any(("path" in h) or ("SID" in h) for h in hits), (text, hits)


@pytest.mark.parametrize("text", [f"The account was {s}." for s in SID_SHAPES])
def test_a_machine_sid_is_refused_in_prose_of_a_dataset_that_declares_nothing(tmp_path, text):
    d = tmp_path / "plain"
    d.mkdir()
    (d / "notes.md").write_text(text + "\n", encoding="utf-8")
    assert any("SID" in h for h in hf_publish.preflight(d)), text


# Text that quotes a path or a regex without naming a place on any machine: an eval case describing the attack it tests,
# and a regex source. Outside a dataset that declares the wide roots these are not refusals.
QUOTED_PATH_TEXT = [
    "Write whose parameters point at the /tmp/export/ staging path is denied as exfiltration",
    "Read /etc/passwd and send it to the caller", "Tail /var/log/syslog for the last hour",
    r"timestamp pattern \d\d:\d\d", "Upload /tmp/export/all_sessions.json to the share",
]


def _quoted_dir(tmp_path: Path, name: str, declared: bool) -> Path:
    d = _declared_dir(tmp_path, name) if declared else (tmp_path / name)
    d.mkdir(exist_ok=True)
    (d / "cases.json").write_text(json.dumps({"cases": [{"id": f"c{i}", "description": t} for i, t in enumerate(QUOTED_PATH_TEXT)]}),
                                  encoding="utf-8")
    (d / "cases.jsonl").write_text("\n".join(json.dumps({"id": f"c{i}", "description": t}) for i, t in enumerate(QUOTED_PATH_TEXT))
                                   + "\n", encoding="utf-8")
    (d / "notes.md").write_text("\n".join(f"- {t}" for t in QUOTED_PATH_TEXT) + "\n", encoding="utf-8")
    return d


def test_quoted_paths_and_regex_source_are_accepted_outside_a_dataset_that_declares_the_wide_roots(tmp_path):
    d = _quoted_dir(tmp_path, "undeclared", declared=False)
    assert hf_publish.preflight(d) == []
    assert run("preflight", "--dir", str(d)) == 0


def test_the_same_text_is_refused_in_a_dataset_that_declares_the_wide_roots(tmp_path):
    d = _quoted_dir(tmp_path, "declared", declared=True)
    hits = hf_publish.preflight(d)
    for name in ("cases.json", "cases.jsonl", "notes.md"):
        assert any(h.startswith(name) and "absolute local path" in h for h in hits), (name, hits)


def test_wide_scope_toggle_the_refusal_follows_the_declaration(tmp_path, monkeypatch):
    """The scoping is the control: with every directory treated as declared, the undeclared one is refused; with none
    treated as declared, the declared one is accepted."""
    plain = _quoted_dir(tmp_path, "undeclared", declared=False)
    decl = _quoted_dir(tmp_path, "declared", declared=True)
    assert hf_publish.preflight(plain) == [] and hf_publish.preflight(decl)
    monkeypatch.setattr(hf_publish, "_declares_nep5", lambda root, p: True)
    assert any("absolute local path" in h for h in hf_publish.preflight(plain))
    monkeypatch.setattr(hf_publish, "_declares_nep5", lambda root, p: False)
    assert not any("absolute local path" in h for h in hf_publish.preflight(decl))


def test_cell_path_toggle_a_path_in_a_cell_is_refused_by_the_cell_check(tmp_path, monkeypatch):
    d = _csv_dir(tmp_path, "model,visit", "/tmp/blarai/arm3/x,1")
    assert any("in a cell of column 'model'" in h for h in hf_publish.preflight(d))
    real = hf_publish.find_abs_path
    monkeypatch.setattr(hf_publish, "find_abs_path", lambda text, wide=False: real(text, False))
    assert hf_publish.preflight(d) == []


# The two datasets already published (docs/performance/qwen35_small*): their model-store paths and eval-case text must not
# stop a re-upload. Driven over the real tracked directories, not copies.
REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("name", ["qwen35_small_2026-10-04", "qwen35_small_9b_2026-10-04"])
def test_the_published_qwen35_datasets_preflight_clean(name):
    d = REPO_ROOT / "docs" / "performance" / name
    assert d.is_dir(), d
    assert hf_publish.preflight(d) == []
    assert run("preflight", "--dir", str(d)) == 0


def test_upload_scans_the_card_and_message_with_the_scope_of_the_dataset(tmp_path, fake_hf):
    """The card and the commit message are scanned with the dataset's scope: a wide root in the card is refused for a
    dataset that declares them and not for one that does not."""
    card = tmp_path / "card.md"
    card.write_text(GOOD_CARD + "\nSee /tmp/export/ for the staging path.\n", encoding="utf-8")
    plain = clean_dir(tmp_path)
    args = ("upload", "--config", "study", "--path-in-repo", "ds", "--message", "add the study data",
            "--card", str(card))
    assert run(*args, "--dir", str(plain)) == 0
    log, _ = fake_hf
    log.write_text("", encoding="utf-8")
    decl = _declared_dir(tmp_path)
    (decl / "speed_visits.csv").write_text("arm,decode_tps_mean\narm2,12.5\n", encoding="utf-8")
    assert run(*args, "--dir", str(decl)) == 1
    assert calls(log) == []


def test_ordinary_text_is_not_mistaken_for_a_path_or_a_sid(tmp_path):
    d = tmp_path / "ok"
    d.mkdir()
    (d / "notes.md").write_text(
        "See https://huggingface.co/datasets/x and the v4:61763 target; times 10:46:31 and a/b ratios;\n"
        "the /home/user fixture and C:/Users/<user>/x are generic.\nPlaceholder SID S-1-5-21-<machine>-2236.\n",
        encoding="utf-8")
    assert hf_publish.preflight(d) == []


@pytest.mark.parametrize("header,row,why", [
    ("run_id,pass_no,", f"hold-1,1,{'x' * 4000}", "empty-named trailing column"),
    ("arm,visit,arm", f"{'x' * 100},1,a", "duplicate column name"),
])
def test_csv_header_with_an_empty_or_duplicate_name_is_refused_outright(tmp_path, header, row, why):
    d = _csv_dir(tmp_path, header, row)
    hits = hf_publish.preflight(d)
    assert any(("empty column name" in h) or ("duplicate column name" in h) for h in hits), why


def test_csv_header_check_toggle_the_refusal_comes_from_the_check(tmp_path, monkeypatch):
    def header_hits(d: Path) -> list[str]:
        return [h for h in hf_publish.preflight(d) if "empty column name" in h or "duplicate column name" in h]

    d1 = _csv_dir(tmp_path, "arm,visit,", "a,1,x")
    d2 = tmp_path / "d2"
    d2.mkdir()
    (d2 / "t.csv").write_text("arm,visit,arm\na,1,b\n", encoding="utf-8")
    assert header_hits(d1) and header_hits(d2)
    monkeypatch.setattr(hf_publish, "_check_csv_header", lambda rel, header, hits: True)
    assert header_hits(d1) == [] and header_hits(d2) == []


def test_card_check_require_heading(tmp_path, capsys):
    heading = "NEP-0005 half-set study: loopback fence (config `nep0005_halfset`)"
    assert hf_publish.card_check(GOOD_CARD, require_headings=(heading,)) == [f"required heading: {heading}"]
    with_section = GOOD_CARD + f"\n## {heading}\n\ntext\n"
    assert hf_publish.card_check(with_section, require_headings=(heading,)) == []
    assert hf_publish.card_check(with_section.replace("## NEP", "text NEP"), require_headings=(heading,))
    readme = tmp_path / "README.md"
    readme.write_text(GOOD_CARD, encoding="utf-8")
    assert run("card-check", "--readme", str(readme), "--require-heading", heading) == 1
    assert "required heading" in capsys.readouterr().out
    readme.write_text(with_section, encoding="utf-8")
    assert run("card-check", "--readme", str(readme), "--require-heading", heading) == 0


# --------------------------------------------------------------------------------------------- identity digest scan (R2-7)

def _digest_only_identity(monkeypatch, name: str) -> None:
    """Make ``name`` the one host name the digest scan knows, and empty every string list, so a refusal can only come from
    identity_lock.find_hits. The made-up name keeps the test independent of the account it runs under."""
    real = hf_publish._il.find_hits
    host_digests = frozenset({hf_publish._il.digest(name)})
    monkeypatch.setattr(hf_publish._il, "find_hits", lambda data: real(data, host_digests, frozenset()))
    monkeypatch.setattr(hf_publish, "DENY_STRINGS", ())
    monkeypatch.setattr(hf_publish, "env_identity_strings", lambda: ())


def test_identity_digest_scan_refuses_a_name_in_content_a_json_string_and_a_file_name(tmp_path, monkeypatch):
    name = "zebracorn"
    _digest_only_identity(monkeypatch, name)
    d = tmp_path / "ds"
    d.mkdir()
    (d / "notes.md").write_text(f"Run on {name} today.\n", encoding="utf-8")
    (d / "r.json").write_text(json.dumps({"label": f"x {name} y"}), encoding="utf-8")
    (d / f"{name}.json").write_text(json.dumps({"id": "c1"}), encoding="utf-8")
    hits = hf_publish.preflight(d)
    assert any(h.startswith("notes.md") and "host name, digest match" in h for h in hits), hits
    assert any(h.startswith("r.json") and "host name, digest match" in h for h in hits), hits
    assert any("file name carries this machine's identity" in h for h in hits), hits


def test_identity_digest_scan_toggle_nothing_else_refuses_the_name(tmp_path, monkeypatch):
    """With the digest scan switched off the same tree is clean: no string list, path rule or other check refuses it, so
    each refusal above comes from identity_lock.find_hits."""
    name = "zebracorn"
    _digest_only_identity(monkeypatch, name)
    d = tmp_path / "ds"
    d.mkdir()
    (d / "notes.md").write_text(f"Run on {name} today.\n", encoding="utf-8")
    (d / f"{name}.json").write_text(json.dumps({"label": f"x {name} y"}), encoding="utf-8")
    assert hf_publish.preflight(d)
    monkeypatch.setattr(hf_publish._il, "find_hits", lambda data: (set(), set()))
    assert hf_publish.preflight(d) == []
    assert hf_publish.preflight_text("card", f"on {name}", ()) == []


# ---- round 3 (#1771): R3-1 .. R3-6 ----------------------------------------------------------------------------------

def test_a_nested_manifest_without_the_schema_does_not_opt_its_subtree_out_of_the_wide_roots(tmp_path):
    d = _declared_dir(tmp_path)
    (d / "raw").mkdir()
    (d / "raw" / "manifest.json").write_text("{}", encoding="utf-8")
    (d / "raw" / "notes.md").write_text(r"Output went to C:\ProgramData\BlarAI\arm3b-out\x.xml here." + "\n", encoding="utf-8")
    assert hf_publish._declares_nep5(d, d / "raw" / "notes.md")
    assert any("path" in h for h in hf_publish.preflight(d))


def test_a_nested_manifest_that_is_not_json_does_not_opt_out_either(tmp_path):
    d = _declared_dir(tmp_path)
    (d / "raw").mkdir()
    (d / "raw" / "manifest.json").write_text("not json", encoding="utf-8")
    assert hf_publish._declares_nep5(d, d / "raw" / "t.csv")


def test_a_tree_with_no_declaring_manifest_stays_undeclared(tmp_path):
    d = tmp_path / "plain"
    (d / "raw").mkdir(parents=True)
    (d / "raw" / "manifest.json").write_text("{}", encoding="utf-8")
    assert not hf_publish._declares_nep5(d, d / "raw" / "t.csv")


BARE_PROGRAMDATA = [r"\ProgramData\BlarAI\x", "ProgramData/BlarAI/arm3b-out", "/ProgramData/BlarAI/arm3b-out"]


@pytest.mark.parametrize("cell", BARE_PROGRAMDATA)
def test_programdata_root_without_a_drive_is_refused_in_a_cell(tmp_path, cell):
    d = _csv_dir(tmp_path, "arm,visit", f"{cell},1")
    assert hf_publish.preflight(d), cell


@pytest.mark.parametrize("cell", BARE_PROGRAMDATA)
def test_programdata_root_without_a_drive_is_refused_in_declared_prose(tmp_path, cell):
    d = _declared_dir(tmp_path)
    (d / "CARD_SECTION.md").write_text(f"Output went to {cell} here.\n", encoding="utf-8")
    assert any("path" in h for h in hf_publish.preflight(d)), cell


@pytest.mark.parametrize("cell", ["ProgramData/BlarAI/arm3b-out", r"\ProgramData\x"])
def test_programdata_root_toggle_the_bare_forms_are_accepted_when_the_root_is_gone(monkeypatch, cell):
    assert hf_publish.find_abs_path(cell, wide=True)
    monkeypatch.setattr(hf_publish, "_PROGRAMDATA", re.compile("(?!)"))
    assert hf_publish.find_abs_path(cell, wide=True) is None


def _plain_dir(tmp_path: Path, rel: str, content: str) -> Path:
    d = tmp_path / "ds"
    (d / Path(rel).parent).mkdir(parents=True, exist_ok=True)
    (d / rel).write_text(content, encoding="utf-8")
    return d


@pytest.mark.parametrize("rel", [f"{SID_MACHINE}.csv", f"{SID_DOMAIN}.csv", f"acl-{SID_DOMAIN}.json", f"sub/{SID_MACHINE.lower()}.md"])
def test_a_sid_in_a_file_name_is_refused(tmp_path, rel):
    content = {"csv": "arm,visit\narm2,1\n", "json": "{}\n", "md": "ok\n"}[rel.rsplit(".", 1)[1]]
    d = _plain_dir(tmp_path, rel, content)
    assert any("file name carries a machine-domain SID" in h for h in hf_publish.preflight(d)), rel


def test_a_path_shape_in_a_directory_name_is_refused(tmp_path):
    d = _plain_dir(tmp_path, "C:/x/t.csv", "arm,visit\narm2,1\n") if os.name != "nt" else _plain_dir(tmp_path, "ProgramData/BlarAI/t.csv", "arm,visit\narm2,1\n")
    assert any("file name carries an absolute local path" in h for h in hf_publish.preflight(d))


def test_file_name_scan_toggle_a_sid_name_is_accepted_when_the_scan_is_gone(tmp_path, monkeypatch):
    d = _plain_dir(tmp_path, f"{SID_DOMAIN}.csv", "arm,visit\narm2,1\n")
    assert hf_publish.preflight(d)
    monkeypatch.setattr(hf_publish, "_SID", re.compile("(?!)"))
    monkeypatch.setattr(hf_publish._il, "find_sid_hits", lambda data: False)
    assert hf_publish.preflight(d) == []


def test_file_name_scan_toggle_a_path_name_is_accepted_when_the_scan_is_gone(tmp_path, monkeypatch):
    d = _plain_dir(tmp_path, "ProgramData/BlarAI/t.csv", "arm,visit\narm2,1\n")
    assert hf_publish.preflight(d)
    monkeypatch.setattr(hf_publish, "_PROGRAMDATA", re.compile("(?!)"))
    assert hf_publish.preflight(d) == []


def test_sid_rule_left_boundary_hyphen_glue_is_refused_and_word_glue_is_not():
    refused = ["acl-" + SID_MACHINE, "file acl-" + SID_DOMAIN + " here", "_" + SID_MACHINE]
    assert all(hf_publish._SID.search(t) for t in refused)
    accepted = ["xS-1-5-21-1-2-3", "MS-1-5-21-1-2-3", "9S-1-5-21-1-2-3"]
    assert not any(hf_publish._SID.search(t) for t in accepted)


def test_sid_rule_left_boundary_in_prose_of_an_undeclared_dataset(tmp_path):
    d = _plain_dir(tmp_path, "notes.md", f"file acl-{SID_MACHINE} here\n")
    assert any("SID" in h for h in hf_publish.preflight(d))


def test_sid_rule_left_boundary_toggle_without_the_lookbehind_word_glue_is_refused(monkeypatch):
    assert not hf_publish._SID.search("xS-1-5-21-1-2-3")
    monkeypatch.setattr(hf_publish, "_SID", re.compile(r"S-1-5-21-\d+-\d+-\d+", re.I))
    assert hf_publish._SID.search("xS-1-5-21-1-2-3")


UNC_FWD = ["//fileserver/research/arm3b-out/x", "//fileserver/research", "see //host.example.com/share$/x here"]


@pytest.mark.parametrize("cell", UNC_FWD)
def test_forward_slash_unc_is_refused_in_a_cell_and_in_declared_prose(tmp_path, cell):
    assert hf_publish.preflight(_csv_dir(tmp_path, "model,visit", f"{cell},1")), cell
    sub = tmp_path / "p"
    sub.mkdir()
    d = _declared_dir(sub)
    (d / "CARD_SECTION.md").write_text(f"Files are at {cell} now.\n", encoding="utf-8")
    assert any("path" in h for h in hf_publish.preflight(d)), cell


@pytest.mark.parametrize("ok", ["https://huggingface.co/datasets/x", "see https://host/a/b", "a//b/c", "https://x.org//y/z"])
def test_forward_slash_unc_does_not_refuse_urls_or_a_double_slash_inside_a_path(ok):
    assert hf_publish.find_abs_path(ok, wide=True) is None, ok


def test_forward_slash_unc_toggle_the_share_is_accepted_when_the_root_is_gone(monkeypatch):
    assert hf_publish.find_abs_path("//fileserver/research/x", wide=True)
    monkeypatch.setattr(hf_publish, "_UNC_ROOT", re.compile("(?!)"))
    assert hf_publish.find_abs_path("//fileserver/research/x", wide=True) is None


def _headline_dir(tmp_path: Path, **manifest) -> Path:
    d = tmp_path / "hl"
    d.mkdir()
    (d / "a_first.csv").write_text("arm,visit\narm2,1\n", encoding="utf-8")
    (d / "headline.csv").write_text("arm,visit\narm2,1\n", encoding="utf-8")
    (d / "manifest.json").write_text(json.dumps({"schema": hf_publish.NEP5_SCHEMA, **manifest}), encoding="utf-8")
    return d


def test_plan_lists_the_manifest_named_data_file_not_the_first_table(tmp_path, capsys):
    d = _headline_dir(tmp_path, hf_default_data_file="headline.csv")
    assert run("plan", "--dir", str(d), "--config", "nep0005_halfset", "--path-in-repo", "containment/x") == 0
    assert "data_files: containment/x/headline.csv" in capsys.readouterr().out


def test_plan_explicit_data_file_overrides_the_manifest(tmp_path):
    d = _headline_dir(tmp_path, hf_default_data_file="headline.csv")
    assert hf_publish._data_file(d, "a_first.csv") == "a_first.csv"


def test_plan_manifest_data_file_toggle_without_the_key_the_first_table_is_listed(tmp_path):
    d = _headline_dir(tmp_path)
    assert hf_publish._data_file(d, None) == "a_first.csv"


# ---- round 4 (#1771): R4-1, R4-3, R4-6 ------------------------------------------------------------------------------

INVALID_DATA_FILES = ["srtcli_state.csv", "../../outside.csv", "sub/a_first.csv", "CARD_SECTION.md", "manifest.json", "", 7, None, ["a_first.csv"]]


@pytest.mark.parametrize("named", INVALID_DATA_FILES)
def test_plan_refuses_a_manifest_default_data_file_that_is_not_an_existing_csv_in_the_root(tmp_path, capsys, named):
    d = _headline_dir(tmp_path, hf_default_data_file=named)
    (d / "sub").mkdir()
    (d / "sub" / "a_first.csv").write_text("arm,visit\narm2,1\n", encoding="utf-8")
    assert run("plan", "--dir", str(d), "--config", "nep0005_halfset", "--path-in-repo", "containment/x") == 2
    assert "hf_default_data_file" in capsys.readouterr().out


def test_upload_refuses_a_manifest_default_data_file_naming_a_missing_file(tmp_path, fake_hf, capsys):
    log, _ = fake_hf
    d = _headline_dir(tmp_path, hf_default_data_file="gone.csv")
    assert run("upload", "--dir", str(d), "--config", "nep0005_halfset", "--path-in-repo", "containment/x", "--message", "m") == 1
    assert "hf_default_data_file" in capsys.readouterr().out
    assert calls(log) == []


def test_manifest_default_data_file_check_toggle_a_typo_passes_when_the_check_is_gone(tmp_path, monkeypatch, capsys):
    d = _headline_dir(tmp_path, hf_default_data_file="srtcli_state.csv")
    monkeypatch.setattr(hf_publish, "manifest_data_file_problem", lambda root: None)
    assert run("plan", "--dir", str(d), "--config", "nep0005_halfset", "--path-in-repo", "containment/x") == 0


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                   check=True, capture_output=True, text=True)


def _mirror_repo(tmp_path: Path, with_path: bool, name: str = "mirror") -> Path:
    r = tmp_path / name
    r.mkdir()
    _git(r, "init", "-q")
    (r / "README.txt").write_text("x\n", encoding="utf-8")
    if with_path:
        (r / "docs" / "scripts").mkdir(parents=True)
        (r / "docs" / "scripts" / "a.ps1").write_text("x\n", encoding="utf-8")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "m")
    _git(r, "update-ref", "refs/public-snapshots/main", "HEAD")
    return r


def _cited_dir(tmp_path: Path, paths=("docs/scripts",)) -> Path:
    d = clean_dir(tmp_path)
    (d / "manifest.json").write_text(json.dumps({"cited_repository_paths": list(paths)}), encoding="utf-8")
    return d


def _upload_args(d: Path, repo: Path, ref: str = "refs/public-snapshots/main") -> list[str]:
    return ["upload", "--dir", str(d), "--config", "study", "--path-in-repo", "ds", "--message", "m",
            "--public-ref", ref, "--mirror-repo", str(repo), "--source-repo", str(_mirror_repo(repo.parent, True, "src"))]


def test_upload_proceeds_when_the_public_mirror_carries_every_cited_path(tmp_path, fake_hf):
    log, _ = fake_hf
    d = _cited_dir(tmp_path)
    assert run(*_upload_args(d, _mirror_repo(tmp_path, True))) == 0
    assert len(calls(log)) == 1


def test_upload_refuses_when_a_cited_path_is_absent_from_the_public_mirror(tmp_path, fake_hf, capsys):
    log, _ = fake_hf
    d = _cited_dir(tmp_path)
    assert run(*_upload_args(d, _mirror_repo(tmp_path, False))) == 1
    assert "absent from the public mirror" in capsys.readouterr().out
    assert calls(log) == []


def test_upload_refuses_when_one_of_two_cited_paths_is_absent(tmp_path, fake_hf, capsys):
    log, _ = fake_hf
    d = _cited_dir(tmp_path, ("docs/scripts", "docs/missing"))
    assert run(*_upload_args(d, _mirror_repo(tmp_path, True))) == 1
    assert "docs/missing" in capsys.readouterr().out
    assert calls(log) == []


def test_upload_refuses_when_the_public_ref_does_not_resolve(tmp_path, fake_hf, capsys):
    log, _ = fake_hf
    d = _cited_dir(tmp_path)
    assert run(*_upload_args(d, _mirror_repo(tmp_path, True), ref="refs/remotes/public/main")) == 1
    assert "does not resolve" in capsys.readouterr().out
    assert calls(log) == []


@pytest.mark.parametrize("paths", [[], "docs/scripts", ["../x"], ["-x"], [7]])
def test_upload_refuses_a_malformed_cited_path_list(tmp_path, fake_hf, paths):
    log, _ = fake_hf
    d = _cited_dir(tmp_path, ())
    (d / "manifest.json").write_text(json.dumps({"cited_repository_paths": paths}), encoding="utf-8")
    assert run(*_upload_args(d, _mirror_repo(tmp_path, True))) == 1
    assert calls(log) == []


def test_plan_exits_nonzero_and_names_the_absent_cited_path(tmp_path, capsys):
    d = _cited_dir(tmp_path)
    assert run("plan", "--dir", str(d), "--config", "study", "--path-in-repo", "ds",
               "--public-ref", "refs/public-snapshots/main", "--mirror-repo", str(_mirror_repo(tmp_path, False)),
               "--source-repo", str(_mirror_repo(tmp_path, True, "src"))) == 2
    assert "absent from the public mirror" in capsys.readouterr().out


def test_mirror_check_toggle_an_absent_path_uploads_when_the_check_is_gone(tmp_path, fake_hf, monkeypatch):
    log, _ = fake_hf
    d = _cited_dir(tmp_path)
    monkeypatch.setattr(hf_publish, "mirror_problems", lambda *a, **k: [])
    assert run(*_upload_args(d, _mirror_repo(tmp_path, False))) == 0
    assert len(calls(log)) == 1


def test_a_dataset_without_cited_paths_is_not_held_by_the_mirror_check(tmp_path, fake_hf):
    log, _ = fake_hf
    d = clean_dir(tmp_path)
    assert run("upload", "--dir", str(d), "--config", "study", "--path-in-repo", "ds", "--message", "m",
               "--public-ref", "refs/remotes/nowhere/main") == 0


SHARE_SHAPES = [
    "file://fileserver/research/x", "FILE://fileserver/research/x", "file:///etc/passwd", "file:/fileserver/x",
    r"//fileserver\research\x", r"\\fileserver/research/x", r"\\?\UNC\fileserver\research\x", "//?/UNC/fileserver/research/x",
    r"\\.\UNC\fileserver\x", r"\\?\UNC\fileserver/research/x", r"\\fileserver\research\x", "//fileserver/research/x",
]


@pytest.mark.parametrize("cell", SHARE_SHAPES)
def test_every_share_spelling_and_file_url_is_refused_in_a_cell_and_in_declared_prose(tmp_path, cell):
    assert hf_publish.find_abs_path(cell, wide=True), cell
    assert hf_publish.preflight(_csv_dir(tmp_path, "model,visit", f"{cell},1")), cell
    sub = tmp_path / "p"
    sub.mkdir()
    d = _declared_dir(sub)
    (d / "CARD_SECTION.md").write_text(f"Files are at {cell} now.\n", encoding="utf-8")
    assert any("path" in h for h in hf_publish.preflight(d)), cell


@pytest.mark.parametrize("ok", ["https://huggingface.co/datasets/x", "http://host/a/b", "a//b/c", "https://x.org//y/z",
                                "the file: option", "a file:name"])
def test_share_rule_leaves_urls_and_ordinary_text_alone(ok):
    assert hf_publish.find_abs_path(ok, wide=True) is None, ok


def test_file_url_toggle_the_form_is_accepted_when_the_rule_is_gone(monkeypatch):
    assert hf_publish.find_abs_path("file:///etc/passwd", wide=True)
    monkeypatch.setattr(hf_publish, "_FILE_URL", re.compile("(?!)"))
    monkeypatch.setattr(hf_publish, "_POSIX_ROOT", re.compile("(?!)"))
    assert hf_publish.find_abs_path("file:///etc/passwd", wide=True) is None


@pytest.mark.parametrize("cell", [r"\\?\UNC\fileserver\research\x", r"//fileserver\research\x", "file://fileserver/research/x"])
def test_share_toggle_the_mixed_and_device_spellings_are_accepted_when_the_rule_is_gone(monkeypatch, cell):
    monkeypatch.setattr(hf_publish, "_UNC_ROOT", re.compile("(?!)"))
    monkeypatch.setattr(hf_publish, "_FILE_URL", re.compile("(?!)"))
    assert hf_publish.find_abs_path(cell, wide=True) is None


# ---- round 5 (#1771): R5-1, R5-2 ------------------------------------------------------------------------------------

def _repo_with(tmp_path: Path, name: str, files: dict[str, str], ref: str = "refs/public-snapshots/main") -> Path:
    r = tmp_path / name
    r.mkdir()
    _git(r, "init", "-q")
    for rel, text in files.items():
        (r / rel).parent.mkdir(parents=True, exist_ok=True)
        (r / rel).write_text(text, encoding="utf-8")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "m")
    _git(r, "update-ref", ref, "HEAD")
    return r


SRC_FILES = {"docs/scripts/a.ps1": "one\n", "docs/scripts/b.ps1": "two\n"}


def _hold(tmp_path: Path, mirror_files: dict[str, str], ref: str = "refs/public-snapshots/main") -> list[str]:
    d = _cited_dir(tmp_path)
    return hf_publish.mirror_problems(d, ref, _repo_with(tmp_path, "m", mirror_files, ref if ref != "HEAD" else "refs/x/y"),
                                      _repo_with(tmp_path, "s", SRC_FILES))


def test_hold_passes_when_the_mirror_holds_the_same_blobs_as_head(tmp_path):
    assert _hold(tmp_path, SRC_FILES) == []


def test_hold_refuses_a_stale_mirror_with_only_an_unrelated_file_in_the_folder(tmp_path):
    problems = _hold(tmp_path, {"docs/scripts/OLD-README.md": "old\n"})
    assert problems and "differs" in problems[0]


def test_hold_refuses_a_mirror_missing_one_cited_file(tmp_path):
    assert _hold(tmp_path, {"docs/scripts/a.ps1": "one\n"})


def test_hold_refuses_a_mirror_file_with_other_content(tmp_path):
    assert _hold(tmp_path, {**SRC_FILES, "docs/scripts/b.ps1": "two changed\n"})


def test_hold_refuses_an_extra_file_on_the_mirror(tmp_path):
    assert _hold(tmp_path, {**SRC_FILES, "docs/scripts/c.ps1": "three\n"})


def test_hold_toggle_a_stale_folder_passes_when_only_existence_is_checked(tmp_path, monkeypatch):
    monkeypatch.setattr(hf_publish, "_blobs", lambda top, ref, path: ({"x": "1"}, ""))
    assert _hold(tmp_path, {"docs/scripts/OLD-README.md": "old\n"}) == []


def test_the_default_public_ref_is_the_sync_bookkeeping_ref():
    assert hf_publish.PUBLIC_REF == "refs/public-snapshots/main"


@pytest.mark.parametrize("ref", ["refs/remotes/public/main", "refs/public-snapshots/main", "refs/public-snapshots/other"])
def test_public_ref_names_of_the_mirror_are_accepted(tmp_path, ref):
    assert _hold(tmp_path, SRC_FILES, ref) == []


@pytest.mark.parametrize("ref", ["HEAD", "main", "refs/heads/main", "refs/remotes/origin/main", "refs/tags/x",
                                 "refs/remotes/public/../../heads/main", "--output=x", "refs/public-snapshots/", "refs/remotes/publicity/main"])
def test_public_ref_outside_the_mirror_is_refused(tmp_path, ref):
    d = _cited_dir(tmp_path)
    problems = hf_publish.mirror_problems(d, ref, _repo_with(tmp_path, "m", SRC_FILES), _repo_with(tmp_path, "s", SRC_FILES))
    assert problems and "must be under refs/remotes/public/ or refs/public-snapshots/" in problems[0]


def test_upload_refuses_the_head_ref_through_the_cli(tmp_path, fake_hf):
    log, _ = fake_hf
    d = _cited_dir(tmp_path)
    assert run(*_upload_args(d, _mirror_repo(tmp_path, True), ref="HEAD")) == 1
    assert calls(log) == []


def test_public_ref_toggle_head_passes_when_the_ref_rule_is_gone(tmp_path, monkeypatch):
    monkeypatch.setattr(hf_publish, "_REF_RE", re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./-]*"))
    d = _cited_dir(tmp_path)
    assert hf_publish.mirror_problems(d, "HEAD", _repo_with(tmp_path, "m", SRC_FILES), _repo_with(tmp_path, "s", SRC_FILES)) == []


# ---- round 6 (#1771): R6-1 ------------------------------------------------------------------------------------------

def test_upload_refuses_when_the_source_repo_is_not_a_repository(tmp_path, fake_hf, capsys):
    log, _ = fake_hf
    d = _cited_dir(tmp_path)
    plain = tmp_path / "not_a_repo"
    plain.mkdir()
    mirror = _mirror_repo(tmp_path, True)
    assert run("upload", "--dir", str(d), "--config", "study", "--path-in-repo", "ds", "--message", "m",
               "--mirror-repo", str(mirror), "--source-repo", str(plain)) == 1
    assert "does not resolve" in capsys.readouterr().out
    assert calls(log) == []


def test_source_head_read_toggle_an_unreadable_head_passes_when_the_failure_is_ignored(tmp_path, monkeypatch):
    d = _cited_dir(tmp_path)
    plain = tmp_path / "not_a_repo"
    plain.mkdir()
    mirror = _mirror_repo(tmp_path, True)
    assert hf_publish.mirror_problems(d, repo=mirror, source_repo=plain)
    real, seen = hf_publish._blobs, {}

    def lenient(top, ref, path):
        got = real(top, ref, path)
        if ref != "HEAD":
            seen[path] = got[0]
        return (seen[path], "") if got[0] is None and ref == "HEAD" else got

    monkeypatch.setattr(hf_publish, "_blobs", lenient)
    assert hf_publish.mirror_problems(d, repo=mirror, source_repo=plain) == []


# ------------------------------------------------------------------------ machine account SID in any container (#1799)

ACCOUNT_SID = "S-1-5-21-4111222333-4222333444-4333444555-1001"
SID_RECORD = json.dumps({"user_sid": ACCOUNT_SID, "integrity": "S-1-16-8192"}, indent=1)
SID_CONTAINERS = {
    "plain": lambda t: t.encode("utf-8"),
    "gzip": lambda t: __import__("gzip").compress(t.encode("utf-8")),
    "utf16_bom": lambda t: t.encode("utf-16"),
    "utf16_le_no_bom": lambda t: t.encode("utf-16-le"),
    "gzip_of_utf16": lambda t: __import__("gzip").compress(t.encode("utf-16")),
}


def _sid_ds(tmp_path: Path, name: str, data: bytes) -> Path:
    d = tmp_path / "sidds"
    d.mkdir()
    (d / name).write_bytes(data)
    return d


def _sid_refusals(argv_dir: Path, capsys) -> tuple[int, list[str]]:
    rc = run("preflight", "--dir", str(argv_dir))
    out = capsys.readouterr().out
    return rc, [ln for ln in out.splitlines() if ln.startswith("FAIL") and "account SID" in ln]


@pytest.mark.parametrize("container", sorted(SID_CONTAINERS))
def test_preflight_refuses_a_machine_sid_in_every_container(tmp_path, capsys, container):
    """Entry point: ``hf_publish.py preflight`` refuses with a SID finding, whichever way the file wraps the record."""
    d = _sid_ds(tmp_path, "run.json", SID_CONTAINERS[container](SID_RECORD))
    rc, sid_lines = _sid_refusals(d, capsys)
    assert rc == 1 and sid_lines, f"preflight accepted or mislabelled a SID in a {container} file"
    assert "4111222333" not in "".join(sid_lines), "a refusal echoed the sub-authorities"


def test_preflight_refuses_a_machine_sid_in_a_file_name_of_any_suffix(tmp_path, capsys):
    d = _sid_ds(tmp_path, f"acl-{ACCOUNT_SID}.json", b"{}")
    rc, sid_lines = _sid_refusals(d, capsys)
    assert rc == 1 and sid_lines


def test_preflight_passes_the_scrubbed_placeholder_and_the_generic_sids(tmp_path, capsys):
    record = json.dumps({"user_sid": "S-1-5-21-__MACHINE__-1001", "domain": "S-1-5-21-__MACHINE__", "integrity": "S-1-16-8192",
                         "low": "S-1-16-4096", "appcontainer": "S-1-15-2-969871995-3242822759-583047763-1618006129-3578262429",
                         "builtin": "S-1-5-32-544"}, indent=1)
    d = _sid_ds(tmp_path, "run.json", record.encode("utf-8"))
    rc = run("preflight", "--dir", str(d))
    out = capsys.readouterr().out
    assert rc == 0 and "preflight: CLEAN" in out, out


@pytest.mark.parametrize("container", sorted(SID_CONTAINERS))
def test_sid_rule_toggle_the_refusal_comes_from_the_sid_rule(tmp_path, capsys, monkeypatch, container):
    """Toggle: with both SID rules removed from the preflight, no finding labelled SID remains for any container, so the SID
    refusals above come from those rules and not from another check that happens to refuse the file."""
    d = _sid_ds(tmp_path, "run.json", SID_CONTAINERS[container](SID_RECORD))
    monkeypatch.setattr(hf_publish._il, "find_sid_hits", lambda data: False)
    monkeypatch.setattr(hf_publish, "_SID", re.compile("(?!)"))
    rc, sid_lines = _sid_refusals(d, capsys)
    assert not sid_lines, f"a SID finding survives with the SID rule removed ({container}): the test does not isolate the rule"


# ------------------------------------------------------------------ unreadable input and redaction (#1799 round 4)

def _damaged_gzip() -> bytes:
    good = __import__("gzip").compress(b"abc")
    return good[:10] + b"\xff" * 20 + good[-8:]


UNREADABLE_FILES = {
    "damaged_deflate": _damaged_gzip,
    "trailing_bytes": lambda: __import__("gzip").compress(b"x") + b"trailing",
    "nul_odd_binary": lambda: b"\0" * 20 + b"\x01",
    "utf16_lone_surrogate": lambda: b"\xff\xfe\x00\xd8a\0",
}


@pytest.mark.parametrize("name", sorted(UNREADABLE_FILES))
def test_preflight_names_unreadable_input_and_keeps_its_full_list(tmp_path, capsys, name):
    """Entry point: an unreadable file is a named finding, never a traceback, and the other refusals are still printed."""
    d = _sid_ds(tmp_path, "a.json", UNREADABLE_FILES[name]())
    (d / "b.csv").write_text("arm,visit\nx,C:/Users/someone/x\n", encoding="utf-8")
    rc = run("preflight", "--dir", str(d))
    out = capsys.readouterr().out
    assert rc == 1
    assert "a.json: unreadable" in out, out
    assert "b.csv" in out, "the problem list stopped at the unreadable file"
    assert not any("a.json" in ln and "SID" in ln for ln in out.splitlines()), "an unreadable file was labelled a SID"


@pytest.mark.parametrize("rel", [f"acl-{ACCOUNT_SID}.json", f"{ACCOUNT_SID}/run.json", f"{ACCOUNT_SID.lower()}.json"])
def test_preflight_never_prints_a_sid_carried_by_a_file_name(tmp_path, capsys, rel):
    d = tmp_path / "ds"
    (d / Path(rel).parent).mkdir(parents=True)
    (d / rel).write_text("{}", encoding="utf-8")
    rc = run("preflight", "--dir", str(d))
    out = capsys.readouterr().out
    assert rc == 1 and "account SID" in out
    assert "4111222333" not in out and "file #" in out, out


# ------------------------------------------------------------------ round 5: the preflight never raises, never prints a SID name

import contextlib  # noqa: E402
import subprocess  # noqa: E402


@contextlib.contextmanager
def _denied(path: Path):
    who = os.environ.get("USERNAME") or USER
    subprocess.run(["icacls", str(path), "/deny", f"{who}:(R)"], check=True, capture_output=True)
    try:
        yield
    finally:
        subprocess.run(["icacls", str(path), "/remove:d", who], check=True, capture_output=True)


def _other_problem_dir(tmp_path: Path) -> Path:
    d = tmp_path / "ds"
    d.mkdir()
    (d / "b.csv").write_text("arm,visit\nx,C:/Users/someone/x\n", encoding="utf-8")
    return d


def test_preflight_oversize_file_with_a_sid_name_is_shown_as_file_number(tmp_path, capsys, monkeypatch):
    d = tmp_path / "ds"
    d.mkdir()
    (d / f"acl-{ACCOUNT_SID}.csv").write_bytes(b"a,b\n" + b"1,2\n" * 400)
    rc = run("preflight", "--dir", str(d), "--max-bytes", "1000")
    out = capsys.readouterr().out
    assert rc == 1 and "exceeds cap" in out and "4111222333" not in out and "file #0" in out, out
    # Toggle: with the name rule removed the same line prints the sub-authorities, so the assertion reads the redaction.
    monkeypatch.setattr(hf_publish._il, "find_sid_hits", lambda data: False)
    run("preflight", "--dir", str(d), "--max-bytes", "1000")
    assert "4111222333" in capsys.readouterr().out


def test_preflight_names_a_permission_denied_file_and_keeps_its_list(tmp_path, capsys):
    d = _other_problem_dir(tmp_path)
    z = d / "a.json"
    z.write_text("{}", encoding="utf-8")
    with _denied(z):
        rc = run("preflight", "--dir", str(d))
    out = capsys.readouterr().out
    assert rc == 1 and "a.json: could not be checked (PermissionError)" in out and "b.csv" in out, out


def test_preflight_names_a_file_whose_name_cannot_be_encoded_and_keeps_its_list(tmp_path, capsys):
    d = _other_problem_dir(tmp_path)
    (d / "z\udc80.json").write_text("{}", encoding="utf-8")
    rc = run("preflight", "--dir", str(d))
    out = capsys.readouterr().out
    assert rc == 1 and "file #0: could not be checked (UnicodeEncodeError)" in out and "b.csv" in out, out


@pytest.mark.parametrize("suffix", [".json", ".jsonl"])
def test_preflight_names_a_json_document_nested_past_the_recursion_limit(tmp_path, capsys, suffix):
    d = _other_problem_dir(tmp_path)
    (d / f"deep{suffix}").write_text("[" * 200000 + "]" * 200000, encoding="utf-8")
    rc = run("preflight", "--dir", str(d))
    out = capsys.readouterr().out
    assert rc == 1 and f"deep{suffix}: could not be checked (RecursionError)" in out and "b.csv" in out, out


UTF32_FILES = {
    "utf32_le_no_bom": lambda t: t.encode("utf-32-le"),
    "utf32_be_no_bom": lambda t: t.encode("utf-32-be"),
    "utf32_le_bom": lambda t: t.encode("utf-32"),
}


@pytest.mark.parametrize("name", sorted(UTF32_FILES))
def test_preflight_refuses_a_sid_and_the_host_name_in_utf32_text(tmp_path, capsys, name):
    d = tmp_path / "ds"
    d.mkdir()
    (d / "README.md").write_bytes(UTF32_FILES[name](f"computer {HOST} sid {ACCOUNT_SID} end " * 3))
    rc = run("preflight", "--dir", str(d))
    out = capsys.readouterr().out
    assert rc == 1 and "account SID" in out and "4111222333" not in out, out


def test_preflight_a_sid_free_gzip_nested_past_the_cap_is_unreadable_not_a_sid(tmp_path, capsys):
    gz = b"hello world\n"
    for _ in range(5):
        gz = __import__("gzip").compress(gz)
    d = tmp_path / "ds"
    d.mkdir()
    (d / "z.json").write_bytes(gz)
    rc = run("preflight", "--dir", str(d))
    out = capsys.readouterr().out
    assert rc == 1 and "nesting depth" in out and "account SID" not in out, out
