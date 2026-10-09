"""The publishable form of the #1699 run-time dataset stays publishable and stays in step with its sources.

scripts/build_gate_runtime_dataset.py derives three tables from the banked logs; the Hugging Face publisher
refuses anything its allowlists do not know. This builds into a temporary directory and requires both a clean
preflight and the row counts the banked state files imply, so a changed column or an over-long id fails here
and not at upload time. A deliberately bad column proves the preflight can fail on this shape of data.
"""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "docs" / "performance" / "gate_runtime_2026-10-07"


def _build(out: Path) -> None:
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_gate_runtime_dataset.py"), "--src", str(SRC),
                    "--out", str(out)], check=True, capture_output=True, cwd=ROOT)


def _preflight(d: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "hf_publish.py"), "preflight", "--dir", str(d)],
                          capture_output=True, text=True, cwd=ROOT)


def test_the_derived_tables_pass_the_publisher_preflight_and_match_the_state_files(tmp_path: Path) -> None:
    out = tmp_path / "pub"
    _build(out)
    p = _preflight(out)
    assert p.returncode == 0 and "CLEAN" in p.stdout, p.stdout + p.stderr
    runs = list(csv.DictReader((out / "runs.csv").open(encoding="utf-8")))
    clean = sum(1 for f in ("timing_runs", "post_fix_runs")
                for r in json.loads((SRC / f / "state.json").read_text(encoding="utf-8"))["runs"]
                if r["status"] == "clean")
    assert len(runs) == clean == 8
    par = list(csv.DictReader((out / "parallel_runs.csv").open(encoding="utf-8")))
    assert len(par) == 13 and sum(r["status"] == "clean" for r in par) == 9, "13 parallel runs, 4 of them the evidence of a leak"
    assert {r["arm"] for r in par if r["arm"].endswith("_tail")} == {"parallel_g3_tail", "parallel_g5_tail", "parallel_g6_tail"}
    assert {r["arm"] for r in runs} == {"old_3be0e22e_wt", "new_ca4fab46_wt", "fixed_f407d2af_wt", "fixed_f407d2af_real"}
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["conditions"]["voided_runs"] == 0
    assert all(s["all_ac"] and s["idle_never_below_start_idle"] for s in summary["sampler"].values())


def test_the_preflight_refuses_a_column_it_does_not_know(tmp_path: Path) -> None:
    out = tmp_path / "pub"
    _build(out)
    text = (out / "runs.csv").read_text(encoding="utf-8")
    (out / "runs.csv").write_text(text.replace("wall_ms", "free_text", 1), encoding="utf-8")
    p = _preflight(out)
    assert p.returncode != 0 and "free_text" in p.stdout + p.stderr


def test_the_committed_publish_directory_equals_a_fresh_build(tmp_path: Path) -> None:
    out = tmp_path / "pub"
    _build(out)
    for name in ("runs.csv", "per_file_ms.csv", "parallel_runs.csv", "summary.json"):
        assert (out / name).read_bytes().replace(b"\r\n", b"\n") == (SRC / "hf_publish" / name).read_bytes().replace(b"\r\n", b"\n"), name
