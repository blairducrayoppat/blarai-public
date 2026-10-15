"""scripts/build_nep0005_dataset.py run through its CLI on the real study records (#1771).

Row counts and the in-range verify, session-end and deny-entry cells are recounted here straight from the source files
with independent code; the publisher's own preflight is the acceptance check; a toggle test plants a free-text cell in a
known id column of this export and a machine SID, and shows the preflight refuses both.
"""

from __future__ import annotations

import ast
import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"
STUDY = REPO / "docs" / "research" / "containment-evidence-2026-10-05"
NEP = STUDY / "nep0005-open-questions" / "runs"
sys.path.insert(0, str(SCRIPTS))

import build_nep0005_dataset as builder  # noqa: E402
import hf_publish  # noqa: E402
import identity_lock  # noqa: E402
import nep0005_card_section as card_mod  # noqa: E402

COMMITTED = STUDY / "hf-export"
_PATH_SHAPE = re.compile(r"[A-Za-z]:[\\/]|(?:^|[\s\"',])/(?:Users|home|Windows|Program Files|projects)[\\/]", re.I)


def _run_build(out: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-I", str(SCRIPTS / "build_nep0005_dataset.py"), "--out", str(out)],
                          capture_output=True, text=True, timeout=120)


def _files(d: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(d.iterdir())}


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("nep5") / "out"
    r = _run_build(out)
    assert r.returncode == 0, r.stderr
    return out


def _j(name: str) -> dict:
    return json.loads((NEP / name).read_text(encoding="utf-8"))


def _rows(built: Path, name: str) -> list[dict]:
    with (built / name).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_build_is_deterministic(built, tmp_path):
    second = tmp_path / "again"
    assert _run_build(second).returncode == 0
    assert _files(built) == _files(second)


def test_committed_export_is_current(built):
    norm = lambda b: b.replace(b"\r\n", b"\n")  # noqa: E731  (autocrlf checkouts)
    assert {k: norm(v) for k, v in _files(COMMITTED).items()} == {k: norm(v) for k, v in _files(built).items()}


def test_row_counts_equal_the_records_in_the_sources(built):
    halfset, ours, n1 = (_j(f) for f in ("halfset-20261013-104631.json", "ours-20261013-104930.json", "n1-20261013-105127.json"))
    srt = _j("srtcli-results-summary.json")
    hold = json.loads((STUDY / "arm2-hold/runs/hold-on-20261011-144844.json").read_text(encoding="utf-8"))
    recs = halfset["records"] + ours["records"] + n1["records"]
    assert (len(halfset["records"]), len(ours["records"]), len(n1["records"])) == (24, 18, 3)
    probes = 0
    for r in recs:
        for step in ("control", "during"):
            probes += len(((r["steps"].get(step) or {}).get("account") or {}).get("Rows") or [])
    want = {
        "nep5_state_passes.csv": len(recs),
        "nep5_probes.csv": probes,
        "nep5_n1_passes.csv": len(n1["records"]),
        "nep5_phases.csv": 5,
        "srtcli_states.csv": sum(len(b["states"]) for b in srt["builds"]),
        "srtcli_commands.csv": sum(len(b["reinstalls"]) + len(b["restores_force"]) for b in srt["builds"]),
        "srtcli_cycles.csv": sum(len(b["after_uninstall"]) for b in srt["builds"]),
        "arm2_hold_samples.csv": len(hold["samples"]),
        "arm_runs.csv": 5,
    }
    for name, n in want.items():
        assert len(_rows(built, name)) == n, name
    manifest = json.loads((built / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["row_counts"] == want


INPUTS = [  # every file the build reads, relative to the study folder
    "nep0005-open-questions/runs/results-summary.json",
    "nep0005-open-questions/runs/halfset-20261013-104631.json",
    "nep0005-open-questions/runs/ours-20261013-104930.json",
    "nep0005-open-questions/runs/n1-20261013-105127.json",
    "nep0005-open-questions/runs/taskcheck-first-20261013-102658.json",
    "nep0005-open-questions/runs/taskcheck-20261013-104554.json",
    "nep0005-open-questions/runs/srtcli-results-summary.json",
    "arm2-hold/runs/hold-on-20261011-144844.json",
    "arm3-persist/runs/arm3a-20261011-165130.json",
    "arm3-persist/runs/arm3b-post-reboot-result-20261012-150113.json",
    "arm3-persist/runs/arm3b-arm-refused-20261012-143857.json",
    "arm3-persist/runs/arm3b-armed-20261012-144923.json",
]


def _lf_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def test_manifest_lists_every_input_with_its_hash(built):
    manifest = json.loads((built / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == hf_publish.NEP5_SCHEMA == builder.SCHEMA
    assert {s["file"] for s in manifest["sources"]} == set(INPUTS)
    for s in manifest["sources"]:
        assert s["sha256"] == _lf_sha(STUDY / s["file"]), s["file"]
    rs = _j("results-summary.json")
    recorded = {v["sanitised_sha256"] for v in rs["files"].values()}
    assert recorded <= {s["sha256"] for s in manifest["sources"]} and len(recorded) == 5


def test_summary_hashes_are_the_ones_as_run_records(built):
    as_run = (NEP / "AS_RUN.md").read_text(encoding="utf-8")
    manifest = json.loads((built / "manifest.json").read_text(encoding="utf-8"))
    by_file = {s["file"]: s for s in manifest["sources"]}
    for name in ("results-summary.json", "srtcli-results-summary.json"):
        entry = by_file[f"nep0005-open-questions/runs/{name}"]
        assert entry["sha256"] in as_run, name
        assert "AS_RUN.md" in entry["sha256_origin"]
    for name, pinned in builder.PINNED_SHA256.items():
        assert by_file[next(f for f in by_file if f.endswith(name))]["sha256"] == pinned
    assert all("AS_RUN.md records the same value" not in s["sha256_origin"] for s in manifest["sources"])


def _study_copy(monkeypatch, tmp_path: Path) -> Path:
    study = tmp_path / "study"
    for sub in ("nep0005-open-questions/runs", "arm2-hold/runs", "arm3-persist/runs"):
        shutil.copytree(STUDY / sub, study / sub)
    monkeypatch.setattr(builder, "NEP", study / "nep0005-open-questions/runs")
    monkeypatch.setattr(builder, "ARM2", study / "arm2-hold/runs")
    monkeypatch.setattr(builder, "ARM3", study / "arm3-persist/runs")
    return study


def test_the_copied_study_builds_untampered(monkeypatch, tmp_path):
    _study_copy(monkeypatch, tmp_path)
    assert builder.main(["--out", str(tmp_path / "ok")]) == 0


@pytest.mark.parametrize("rel", INPUTS)
def test_build_exits_non_zero_when_any_input_is_tampered(rel, monkeypatch, tmp_path):
    study = _study_copy(monkeypatch, tmp_path)
    target = study / rel
    target.write_bytes(target.read_bytes() + b" ")
    assert builder.main(["--out", str(tmp_path / "tampered")]) == 1


def test_no_absolute_path_and_no_identity_in_any_output(built):
    assert _files(built)
    for name, data in _files(built).items():
        hosts, users = identity_lock.find_hits(data)
        assert not hosts and not users, name
        text = data.decode("utf-8")
        assert not _PATH_SHAPE.search(text), name


def test_publisher_preflight_accepts_the_output(built):
    assert hf_publish.preflight(built) == []
    r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "hf_publish.py"), "preflight", "--dir", str(built)],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr


def test_every_column_is_allow_listed_with_a_class_and_a_reason(built):
    for p in built.glob("*.csv"):
        cols = next(csv.reader(p.open(newline="", encoding="utf-8")))
        assert set(cols) <= hf_publish.KNOWN_CSV_COLUMNS | set(hf_publish.NEP5_COLUMNS), p.name
    for col, (cls, reason) in hf_publish.NEP5_COLUMNS.items():
        assert cls in ("id", "num", "hash") and reason.strip(), col
        assert (col in hf_publish.NEP5_NUMERIC_COLUMNS) == (cls == "num")
        assert (col in hf_publish.NEP5_HASH_COLUMNS) == (cls == "hash")
        assert col not in hf_publish.NUMERIC_COLUMNS | hf_publish.HASH_COLUMNS | hf_publish.KNOWN_CSV_COLUMNS


def test_toggle_preflight_refuses_a_sentence_in_a_known_id_column_and_a_sid(built, tmp_path, monkeypatch):
    """The acceptance check could fail: a 48-character sentence planted in a known id column (run_id) of this export is
    refused, and so is a machine SID in a cell and in CARD_SECTION.md; with the per-column value checks removed the
    sentence is accepted, so the refusal comes from the check."""
    sentence = "The_fence_held_because_the_filter_was_persistent"
    sid = "S-1-5-21-3623811015-3361044348-30300820-1013"
    assert len(sentence) == 48

    def planted(name: str, cell: str) -> Path:
        bad = tmp_path / name
        shutil.copytree(built, bad)
        f = bad / "arm_runs.csv"
        f.write_text(f.read_text(encoding="utf-8").replace("arm3a-20261011-165130", cell, 1), encoding="utf-8")
        return bad

    assert hf_publish.preflight(built) == []
    sentence_dir = planted("sentence", sentence)
    hits = hf_publish.preflight(sentence_dir)
    assert any("run_id" in h for h in hits), hits
    sid_dir = planted("sid", sid)
    assert any("SID" in h for h in hf_publish.preflight(sid_dir))
    prose_dir = tmp_path / "prose"
    shutil.copytree(built, prose_dir)
    card = prose_dir / "CARD_SECTION.md"
    card.write_text(card.read_text(encoding="utf-8") + "\nThe account was " + sid + ".\n", encoding="utf-8")
    assert any("SID" in h for h in hf_publish.preflight(prose_dir))
    monkeypatch.setattr(hf_publish, "NEP5_VALUE_CHECKS", {})
    assert hf_publish.preflight(sentence_dir) == []


def test_card_section_numbers_come_from_the_rows(built):
    text = (built / "CARD_SECTION.md").read_text(encoding="utf-8")
    assert f"| `nep5_state_passes.csv` | {len(_rows(built, 'nep5_state_passes.csv'))} |" in text
    assert f"| `nep5_probes.csv` | {len(_rows(built, 'nep5_probes.csv'))} |" in text
    assert "120 of 120 probes refused" in text and "## " in text
    assert max(len(ln) for ln in text.splitlines()) <= hf_publish.PROSE_LINE_MAX


def test_build_refuses_a_directory_with_foreign_files(built, tmp_path):
    out = tmp_path / "dirty"
    shutil.copytree(built, out)
    (out / "notes.txt").write_text("x", encoding="utf-8")
    r = _run_build(out)
    assert r.returncode == 1 and "notes.txt" in r.stderr
    assert (out / "notes.txt").exists()


def test_build_refuses_a_source_whose_hash_differs(monkeypatch, tmp_path):
    src = tmp_path / "runs"
    shutil.copytree(NEP, src)
    first = src / "n1-20261013-105127.json"
    first.write_bytes(first.read_bytes() + b" ")
    monkeypatch.setattr(builder, "NEP", src)
    with pytest.raises(builder.BuildError, match="differs from the recorded"):
        builder.build(tmp_path / "o")


# --------------------------------------------------------------------------------------------- #1771 review fixes

def _srt() -> dict:
    return _j("srtcli-results-summary.json")


def test_in_range_verify_cells_carry_the_source_values(built):
    rows = _rows(built, "srtcli_states.csv")
    got: dict = {}
    for r in rows:
        if r["verify_v4_in"] or r["verify_v6_in"]:
            key = (r["build"], r["state_id"], r["verify_v4_in"], r["verify_v6_in"])
            got[key] = got.get(key, 0) + 1
    want: dict = {}
    for b in _srt()["builds"]:
        for x in b["states"]:
            if "verify_v4_in_range" in x:
                key = (b["build"], x["state"], x["verify_v4_in_range"], x["verify_v6_in_range"])
                want[key] = want.get(key, 0) + 1
    assert got == want and sum(got.values()) == 18
    expect = {("stock", "F"): "connected", ("patched", "F"): "connected", ("stock", "HP"): "blocked", ("patched", "HP"): "blocked",
              ("stock", "HP-after-reinstall"): "blocked", ("patched", "HP-after-reinstall"): "connected"}
    for (build_, state, v4, v6), n in got.items():
        assert v4 == v6 == expect[(build_, state)] and n == 3


def test_a_state_that_would_lose_an_in_range_result_stops_the_build():
    assert builder._in_range({"state": "H4"}) == {"verify_v4_in": None, "verify_v6_in": None}
    with pytest.raises(builder.BuildError):
        builder._in_range({"state": "H4", "verify_v4_in_range": "blocked", "verify_v6_in_range": "blocked"})
    with pytest.raises(KeyError):
        builder._in_range({"state": "HP", "verify_v4_in_range": "blocked"})


def test_phase_rows_read_the_session_end_from_the_records(built):
    rows = {r["phase"]: r for r in _rows(built, "nep5_phases.csv")}
    assert set(rows) == set(builder.PHASE_FILES)
    for phase in ("n1", "taskcheck-first", "taskcheck-second"):
        doc = _j(builder.PHASE_FILES[phase][1])
        assert "session_exit" not in doc
        se = doc["records"][0]["steps"]["session_exit"]
        assert rows[phase]["task_restored"] == str(se["TaskRestored"]) == "True"
        assert rows[phase]["definition_matches"] == str(se["DefinitionMatches"]) == "True"
        assert rows[phase]["reprovision_exit"] == str(se["Reprovision"]["ExitCode"]) == "0"
        assert rows[phase]["files_left"] == str(len(se["Files"]["Left"]))
    for phase in rows:
        assert rows[phase]["task_restored"] == "True" and rows[phase]["reprovision_exit"] == "0"


def test_session_exit_is_never_defaulted():
    with pytest.raises(builder.BuildError):
        builder._session_exit({"records": [{"steps": {}}]}, "x.json")
    partial = {"TaskRestored": True, "DefinitionMatches": True, "Reprovision": {"ExitCode": 0}}  # no Files block
    docs = {p: {"session_exit": partial, "records": [], "started": "", "finished": "", "exit_code": 0, "passes": 3}
            for p in builder.PHASE_FILES}
    with pytest.raises(KeyError):
        builder.phase_rows(docs)


def test_card_has_no_code_licence_statement(built):
    text = (built / "CARD_SECTION.md").read_text(encoding="utf-8")
    assert "Apache" not in text and "code that built it" not in text
    assert "Data in this section: CC-BY-4.0 (cc-by-4.0)." in text


def test_card_provenance_sentence_lists_what_is_not_computed(built):
    flat = " ".join((built / "CARD_SECTION.md").read_text(encoding="utf-8").split())
    assert "none is typed in" not in flat
    for item in ("Read from the run records, not the tables", "Typed from the run notes", "1.1.1.1:443", "600 s", "-04:00",
                 "the permit range"):
        assert item in flat, item
    assert "Speed: a connect takes" not in flat


def test_speed_line_is_read_back_from_the_hold_samples(built):
    text = " ".join((built / "CARD_SECTION.md").read_text(encoding="utf-8").split())
    m = re.search(r"Speed: each hold probe took (\d+) to (\d+) ms", text)
    assert m
    ms = [int(r["probe_ms"]) for r in _rows(built, "arm2_hold_samples.csv")]
    assert (int(m.group(1)), int(m.group(2))) == (min(ms), max(ms))


def test_deny_entry_identifier_is_the_relative_id_only(built):
    want = []
    for b in _srt()["builds"]:
        for u in b["after_uninstall"]:
            ids = re.findall(r"\(D;[^)]*-(\d+)\)", u["store_dir_sddl"])
            assert len(ids) == 1
            want.append(ids[0])
    got = [r["store_dir_deny_rid"] for r in _rows(built, "srtcli_cycles.csv")]
    assert got == want == ["2236", "2238", "2240", "2242", "2244", "2246"]
    assert builder._deny_rid("D:PAI(D;OICI;FA;;;S-1-5-21-<machine>-2236)(A;OICI;FA;;;SY)") == "2236"
    assert builder._deny_rid("D:PAI(A;OICI;FA;;;SY)") is None


def test_armed_run_is_a_row_and_the_card_explains_the_refused_one(built):
    rows = {r["arm"]: r for r in _rows(built, "arm_runs.csv")}
    assert set(rows) == {"arm2", "arm3a", "arm3b-arming-refused", "arm3b-armed", "arm3b"}
    armed = json.loads((STUDY / "arm3-persist/runs/arm3b-armed-20261012-144923.json").read_text(encoding="utf-8"))
    assert rows["arm3b-armed"]["started"] == armed["armed_at"]
    assert rows["arm3b-armed"]["source_file"] == "arm3b-armed-20261012-144923.json"
    text = " ".join((built / "CARD_SECTION.md").read_text(encoding="utf-8").split())
    t1 = datetime.fromisoformat(rows["arm3b-arming-refused"]["finished"])
    t2 = datetime.fromisoformat(rows["arm3b-armed"]["started"])
    minutes = round((t2 - t1).total_seconds() / 60)
    assert f"{t2.strftime('%H:%M:%S')}, {minutes} minutes later" in text
    refused = rows["arm3b-arming-refused"]
    assert f"exit {refused['exit_code']}, fence {refused['fence_state']} before it" in text


def test_card_section_heading_is_the_one_the_publisher_requires(built):
    section = (built / "CARD_SECTION.md").read_text(encoding="utf-8")
    assert section.splitlines()[0] == f"## {card_mod.HEADING_TEXT}"
    stub = ("---\nlicense: cc-by-4.0\n---\n# Card\n## Setup\nIntel Core Ultra CPU, Arc iGPU, GPU driver 32.0.101.8831. "
            "OpenVINO 2026.4.0, GenAI 2026.4.0.0. INT8 e4d8de7a25bc3007261c28785bc190c97cabd243\n## Conditions\nx\n"
            "## Not measured\nx\npre-registered\n")
    assert hf_publish.card_check(stub) == []
    need = (card_mod.HEADING_TEXT,)
    assert hf_publish.card_check(stub, require_headings=need) == [f"required heading: {card_mod.HEADING_TEXT}"]
    assert hf_publish.card_check(stub + "\n" + section, require_headings=need) == []


# --------------------------------------------------------------------------------------------- #1771 review round 2

_PLACEHOLDER = re.compile(r"\{[A-Za-z_][\w.]*(?:\[[^\]]*\])?\}")


def _placeholder_literals(source: str) -> list[str]:
    """String literals of a module (the literal parts of f-strings included) that read as an unrendered ``{name}``."""
    return [n.value for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and _PLACEHOLDER.search(n.value)]


def test_card_section_has_no_unrendered_placeholder(built):
    text = (built / "CARD_SECTION.md").read_text(encoding="utf-8")
    assert _PLACEHOLDER.findall(text) == []
    assert "Per cycle the account connects to 6 loopback targets" in " ".join(text.split())


def test_card_renderer_source_has_no_literal_that_reads_as_a_placeholder():
    assert _placeholder_literals(Path(card_mod.__file__).read_text(encoding="utf-8")) == []


def test_placeholder_lock_toggle_it_flags_a_plain_string_between_two_f_strings():
    """The shape that shipped a literal ``{n_targets}``: a plain literal concatenated between two f-strings."""
    buggy = 'x = (f"a {y} " "connects to {n_targets} targets " f"b {z}")'
    found = _placeholder_literals(buggy)
    assert len(found) == 1 and "{n_targets}" in found[0]
    assert _PLACEHOLDER.findall("connects to {n_targets} targets") == ["{n_targets}"]
    assert _placeholder_literals('x = f"connects to {n} targets"') == []


def test_card_section_spacing_after_a_label_colon(built):
    text = " ".join((built / "CARD_SECTION.md").read_text(encoding="utf-8").split())
    assert not re.search(r"per pass:\S", text)
    assert "per pass: 6 (x3)" in text


def _blocks(text: str) -> list[str]:
    return [" ".join(b.split()) for b in text.split("\n- ")]


def _tally_of(rows: list[dict], key: str) -> str:
    seen: dict = {}
    for r in rows:
        seen[r[key]] = seen.get(r[key], 0) + 1
    return ", ".join(f"{k} (x{n})" for k, n in sorted(seen.items()))


def test_hp_card_lines_cite_the_in_range_verify_beside_the_out_of_range_one(built):
    text = (built / "CARD_SECTION.md").read_text(encoding="utf-8")
    blocks = _blocks(text)
    ss = _rows(built, "srtcli_states.csv")
    want_in = {("stock", "HP"): "blocked", ("patched", "HP"): "blocked",
               ("stock", "HP-after-reinstall"): "blocked", ("patched", "HP-after-reinstall"): "connected"}
    for build_ in ("stock", "patched"):
        for state, opener in (("HP", f"{build_} build, HP (both permits deleted)"),
                              ("HP-after-reinstall", f"{build_} build, plain `install` after HP:")):
            sel = [r for r in ss if r["build"] == build_ and r["state_id"] == state]
            assert len(sel) == 3
            block = next(b for b in blocks if b.startswith(opener))
            expect = (f"verify v4 out {_tally_of(sel, 'verify_v4_out')}, v6 out {_tally_of(sel, 'verify_v6_out')}, "
                      f"v4 in range {_tally_of(sel, 'verify_v4_in')}, v6 in range {_tally_of(sel, 'verify_v6_in')}")
            assert expect in block, (build_, state)
            v = want_in[(build_, state)]
            assert f"v4 in range {v} (x3), v6 in range {v} (x3)" in block, (build_, state)


def test_card_lines_of_states_without_an_in_range_verify_do_not_invent_one(built):
    for b in _blocks((built / "CARD_SECTION.md").read_text(encoding="utf-8")):
        if b.startswith(("stock build, H6 (", "stock build, H4 (", "patched build, H6 (", "patched build, H4 (")):
            assert "in range" not in b and "(none)" not in b, b


# AS_RUN.md is the root of trust for two hashes; its anchor rows are named in the builder and the manifest.

def _as_run_text() -> str:
    return (NEP / "AS_RUN.md").read_bytes().replace(b"\r\n", b"\n").decode("utf-8")


def test_manifest_records_the_as_run_anchor(built):
    manifest = json.loads((built / "manifest.json").read_text(encoding="utf-8"))
    anchor = manifest["hash_anchor"]
    raw = (NEP / "AS_RUN.md").read_bytes().replace(b"\r\n", b"\n")
    assert anchor["file"] == "nep0005-open-questions/runs/AS_RUN.md" == builder.AS_RUN_FILE
    assert anchor["bytes"] == len(raw) and anchor["sha256"] == hashlib.sha256(raw).hexdigest()
    lines = raw.decode("utf-8").split("\n")
    by_file = {s["file"]: s for s in manifest["sources"]}
    assert set(anchor["rows"]) == set(builder.AS_RUN_ANCHORS) == {"results-summary.json", "srtcli-results-summary.json"}
    for name, row in anchor["rows"].items():
        recorded = by_file[f"nep0005-open-questions/runs/{name}"]
        assert recorded["sha256"] in lines[row["line"] - 1], name
        assert f"line {row['line']} " in recorded["sha256_origin"], name
        assert row["row_is"].strip()
    assert "AS_RUN.md" in (builder.__doc__ or "") and "AS_RUN_ANCHORS" in (builder.__doc__ or "")


def _as_run_edit(monkeypatch, tmp_path: Path, edit) -> None:
    study = _study_copy(monkeypatch, tmp_path)
    f = study / "nep0005-open-questions/runs/AS_RUN.md"
    f.write_bytes(edit(f.read_bytes().replace(b"\r\n", b"\n").decode("utf-8")).encode("utf-8"))


def _row_line(name: str) -> str:
    pat = re.compile(builder.AS_RUN_ANCHORS[name][0])
    return next(ln for ln in _as_run_text().split("\n") if pat.search(ln))


@pytest.mark.parametrize("name", sorted(builder.AS_RUN_ANCHORS))
@pytest.mark.parametrize("where,other_hash", [("after", True), ("before", True), ("after", False)])
def test_a_second_as_run_row_for_a_summary_file_stops_the_build(name, where, other_hash, monkeypatch, tmp_path, capsys):
    line = _row_line(name)
    real = re.search(r"[0-9a-f]{64}", line).group(0)
    neighbour = line.replace(real, "0" * 64) if other_hash else line

    def edit(text: str) -> str:
        return text.replace(line, line + "\n" + neighbour if where == "after" else neighbour + "\n" + line, 1)

    _as_run_edit(monkeypatch, tmp_path, edit)
    assert builder.main(["--out", str(tmp_path / "o")]) == 1
    assert "exactly one is required" in capsys.readouterr().err


@pytest.mark.parametrize("name", sorted(builder.AS_RUN_ANCHORS))
def test_an_as_run_without_the_row_stops_the_build(name, monkeypatch, tmp_path, capsys):
    line = _row_line(name)
    _as_run_edit(monkeypatch, tmp_path, lambda text: text.replace(line + "\n", "", 1))
    assert builder.main(["--out", str(tmp_path / "o")]) == 1
    assert f"AS_RUN.md records no sha256 for {name}" in capsys.readouterr().err


@pytest.mark.parametrize("name", sorted(builder.AS_RUN_ANCHORS))
def test_an_as_run_hash_that_differs_from_its_source_stops_the_build(name, monkeypatch, tmp_path, capsys):
    line = _row_line(name)
    real = re.search(r"[0-9a-f]{64}", line).group(0)
    _as_run_edit(monkeypatch, tmp_path, lambda text: text.replace(line, line.replace(real, "0" * 64), 1))
    assert builder.main(["--out", str(tmp_path / "o")]) == 1
    assert "differs from the recorded" in capsys.readouterr().err


# ---- round 3 (#1771): R3-6 and R3-7 ---------------------------------------------------------------------------------

def test_manifest_names_the_headline_table_for_the_hf_config(built):
    doc = json.loads((built / "manifest.json").read_text(encoding="utf-8"))
    assert doc["hf_default_data_file"] == "srtcli_states.csv" == builder.HF_DEFAULT_DATA_FILE
    assert (built / doc["hf_default_data_file"]).is_file()
    assert hf_publish._data_file(built, None) == "srtcli_states.csv"


def test_card_section_cites_no_commit_but_the_upstream_pin(built):
    text = (built / "CARD_SECTION.md").read_text(encoding="utf-8")
    assert card_mod._COMMIT_ID.findall(text) == [card_mod.SRT_WIN_PIN]
    assert "716fd87a" not in text
    assert card_mod.MATRIX_SCRIPTS_PATH in " ".join(text.split())
    assert (REPO / card_mod.MATRIX_SCRIPTS_PATH).is_dir()


@pytest.mark.parametrize("cited", ["716fd87a6e1f4b530185fcebfcf0b052ccad6120", "716fd87a", "a1b2c3d4e5f6"])
def test_card_renderer_refuses_a_bare_commit_id(cited):
    with pytest.raises(ValueError, match="commit id"):
        card_mod.refuse_commit_ids(f"Matrix scripts at commit {cited}.")


def test_card_renderer_commit_guard_accepts_the_pin_hashes_and_ordinary_words():
    ok = f"pin {card_mod.SRT_WIN_PIN}; code 0x80320007; run 20261011144844; effaced; sha256 " + "ab12" * 16
    assert card_mod.refuse_commit_ids(ok) == ok


def test_card_renderer_commit_guard_toggle_a_commit_passes_when_the_guard_is_gone(monkeypatch):
    monkeypatch.setattr(card_mod, "_COMMIT_ID", re.compile("(?!)"))
    assert card_mod.refuse_commit_ids("at commit 716fd87a6e1f4b530185fcebfcf0b052ccad6120")


# ---- round 4 (#1771): R4-1, R4-2, R4-4, R4-5 ------------------------------------------------------------------------

COMMIT = "716fd87a6e1f4b530185fcebfcf0b052ccad6120"


def test_no_output_file_carries_a_commit_id_but_the_upstream_pin(built):
    for p in sorted(built.iterdir()):
        found = {m.group(0).lower() for m in card_mod._COMMIT_ID.finditer(p.read_text(encoding="utf-8"))}
        assert found <= {card_mod.SRT_WIN_PIN}, (p.name, found)
    doc = json.loads((built / "manifest.json").read_text(encoding="utf-8"))
    assert "source_commit_of_matrix_run" not in doc


def test_manifest_lists_the_paths_the_card_cites_as_carried_by_the_public_snapshot(built):
    doc = json.loads((built / "manifest.json").read_text(encoding="utf-8"))
    assert doc["cited_repository_paths"] == [card_mod.MATRIX_SCRIPTS_PATH.rstrip("/")]
    card_text = " ".join((built / "CARD_SECTION.md").read_text(encoding="utf-8").split())
    assert all(p in card_text for p in doc["cited_repository_paths"])
    assert hf_publish.mirror_problems(built, ref="refs/remotes/no/such/ref") != []  # fail-closed with no mirror ref


def test_commit_guard_toggle_the_builder_loop_is_what_stops_a_commit_in_the_manifest(monkeypatch, tmp_path):
    monkeypatch.setattr(builder, "HF_DEFAULT_DATA_FILE", COMMIT)
    with pytest.raises(ValueError, match="commit id"):
        builder.build(tmp_path / "o")
    monkeypatch.setattr(card_mod, "_COMMIT_ID", re.compile("(?!)"))
    assert builder.build(tmp_path / "o2")


@pytest.mark.parametrize("cited", [COMMIT.upper(), "commit716fd87a", "716fd87a_x", "716FD87A", "(716fd87a)", "sha:716fd87a6e1f"])
def test_commit_guard_refuses_upper_case_and_word_glued_ids(cited):
    with pytest.raises(ValueError, match="commit id"):
        card_mod.refuse_commit_ids(f"Matrix scripts at {cited}.")


@pytest.mark.parametrize("ok", ["code 0x8032000A and 0x80320007", "sha256 " + "ab12" * 16, "SHA " + "AB12" * 16,
                                "run 20261011144844", "effaced", "ordinary words"])
def test_commit_guard_accepts_status_codes_long_hashes_and_words(ok):
    assert card_mod.refuse_commit_ids(ok) == ok


def test_commit_guard_compares_the_pin_lower_cased():
    assert card_mod.refuse_commit_ids(f"pin {card_mod.SRT_WIN_PIN.upper()} here")
    with pytest.raises(ValueError, match="commit id"):
        card_mod.refuse_commit_ids("abbreviated pin " + card_mod.SRT_WIN_PIN[:8])


def test_commit_guard_toggle_without_case_and_hex_bounds_the_reviewers_examples_pass(monkeypatch):
    monkeypatch.setattr(card_mod, "_COMMIT_ID", re.compile(r"\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b"))
    for text in (COMMIT.upper(), "commit716fd87a", "716fd87a_x"):
        assert card_mod.refuse_commit_ids(text) == text


def test_render_itself_runs_the_commit_guard(monkeypatch, tmp_path):
    """The call inside ``render`` (the builder's loop over the outputs would also catch a commit, so the call is observed)."""
    captured = {}
    real_render = card_mod.render

    def spy(*args):
        captured["args"] = args
        return real_render(*args)

    monkeypatch.setattr(card_mod, "render", spy)
    builder.build(tmp_path / "o")
    monkeypatch.setattr(card_mod, "render", real_render)
    seen = []
    real_guard = card_mod.refuse_commit_ids
    monkeypatch.setattr(card_mod, "refuse_commit_ids", lambda text: seen.append(text) or real_guard(text))
    text = real_render(*captured["args"])
    assert seen == [text]
