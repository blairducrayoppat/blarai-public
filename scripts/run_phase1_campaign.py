"""Serial quality campaign for #1663 Phase 1 (one model, GPU-exclusive).

Runs a fixed job list through ``run_evals_instrumented.py``, one process at a
time (never two models resident). Every job appends to ONE status file, and this
script writes the campaign-level ``{"done": true}`` line only when the whole list
has finished, so a Monitor reading that file sees one DONE for the campaign.

Job lists (``--model``):

``<size>-on``   Qwen3.5 INT8 of that size (4b, 9b), MTP head ON  (engine cb-mtp-on)
``<size>-off``  Qwen3.5 INT8 of that size, MTP head OFF (engine cb-mtp-off)
``14b``         Qwen3-14B INT4 as it ships (text-llm, pruned-draft speculative decode)

Each size loads its own directory from ``phase1_sizes.SIZES`` (``--model-dir``
overrides it for the one model being run).

Per model: every suite once (random datamark = the production condition); the
two model-driven suites (agentic, conversation) twice more at random marker; then
three PINNED-marker repeats, and the V1 / V2 perturbations at a pinned marker.
Pinned repeats carry ``--io-log`` so input identity is measured, not assumed.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import phase1_sizes as sizes  # noqa: E402

MODELS_ROOT = Path("C:/Users/mrbla/BlarAI")
PY_2026_4 = MODELS_ROOT / ".venv-2026.4/Scripts/python.exe"
PY_SHIP = MODELS_ROOT / ".venv/Scripts/python.exe"
DIR_14B = MODELS_ROOT / "models/qwen3-14b/openvino-int4-gpu"
import tempfile

#: pytest-style isolation: the AO/PA write session state under LOCALAPPDATA, which
#: must never be the operator's real one.
LOCALAPPDATA_SANDBOX = Path(tempfile.gettempdir()) / "blarai_eval_localappdata"

MODEL_SUITES = ("agentic", "conversation")


def target_args(model: str, model_dir: Path | None = None) -> tuple[Path, list[str]]:
    if model == sizes.MODEL_14B:
        return PY_SHIP, ["--model-dir", str(model_dir or DIR_14B), "--capability", "text-llm"]
    target = sizes.quality_target(model)
    if target is None:
        raise SystemExit(f"unknown --model {model!r}")
    size, engine = target
    return PY_2026_4, ["--model-dir", str(model_dir or sizes.SIZES[size]), "--capability", "multimodal-vlm", "--engine", engine]


def supplement_jobs(model: str) -> list[dict]:
    """Added after the independent review (F2, F5): V3 (trim-proof perturbation) and
    repeats of the suites that run once in the main list."""
    jobs: list[dict] = []
    for suite in MODEL_SUITES:
        jobs.append({"tag": f"{model}-{suite}-pinned-V3-r1", "suites": [suite], "extra": ["--pin-marker", "--perturb", "V3"]})
    # The Policy Agent half decides whether a brain can sit behind the adjudication
    # door, so it gets repeats; answer_quality / preference_memory stay n=1 per arm
    # (no conclusion is drawn from a single run of either).
    for rep in (2, 3):
        jobs.append({"tag": f"{model}-pa_classification-random-r{rep}", "suites": ["pa_classification"], "extra": []})
    return jobs


def job_list(model: str) -> list[dict]:
    jobs: list[dict] = [{"tag": f"{model}-all-random-r1", "suites": ["all"], "extra": []}]
    for rep in (2, 3):
        for suite in MODEL_SUITES:
            jobs.append({"tag": f"{model}-{suite}-random-r{rep}", "suites": [suite], "extra": []})
    for rep in (1, 2, 3):
        for suite in MODEL_SUITES:
            jobs.append({"tag": f"{model}-{suite}-pinned-V0-r{rep}", "suites": [suite], "extra": ["--pin-marker", "--perturb", "V0"]})
    for variant in ("V1", "V2"):
        for suite in MODEL_SUITES:
            jobs.append({"tag": f"{model}-{suite}-pinned-{variant}-r1", "suites": [suite], "extra": ["--pin-marker", "--perturb", variant]})
    return jobs


def job_command(py: Path, targ: list[str], model: str, job: dict, out_dir: Path, status: Path) -> list[str]:
    """The exact argv of one quality job. Every non-14B job carries ``--engine-summary``: it is the
    MTP witness, and a job without it can run with the engine off and still look like data."""
    tag = job["tag"]
    cmd = [
        str(py), str(REPO / "scripts/run_evals_instrumented.py"),
        "--status-file", str(status), "--models-root", str(MODELS_ROOT), "--tag", tag,
        "--io-log", str(out_dir / f"{tag}_io.jsonl"),
        "--suite", job["suites"][0], "--include-hardware", *targ,
        "--report", str(out_dir / f"{tag}_report.json"), *job["extra"],
    ]
    if model != sizes.MODEL_14B:
        cmd += ["--engine-summary", str(out_dir / f"{tag}_engine.json")]
    return cmd


def main() -> int:
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--model", required=True, choices=sizes.quality_models())
    ap.add_argument("--model-dir", type=Path, default=None, help="override the model directory for --model")
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--status-file", type=Path, required=True)
    ap.add_argument("--only", default=None, help="comma list of job-tag substrings to run")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--supplement", action="store_true", help="run only the post-review supplement jobs")
    a = ap.parse_args()

    out_dir = a.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    status = a.status_file.resolve()
    py, targ = target_args(a.model, a.model_dir)
    jobs = supplement_jobs(a.model) if a.supplement else job_list(a.model)
    if a.only:
        wanted = a.only.split(",")
        jobs = [j for j in jobs if any(w in j["tag"] for w in wanted)]
    if a.dry_run:
        print("target", py.name, targ)
        for j in jobs:
            print(j["tag"], j["suites"], j["extra"])
        return 0

    def log(row: dict) -> None:
        row = {"t": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **row}
        with open(status, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + chr(10))

    LOCALAPPDATA_SANDBOX.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, LOCALAPPDATA=str(LOCALAPPDATA_SANDBOX))
    worst = 0
    for j in jobs:
        tag = j["tag"]
        cb_stats = out_dir / f"{tag}_cb_stats.jsonl"
        env["BLARAI_EVAL_CB_STATS"] = str(cb_stats)
        log({"job_start": tag})
        cmd = job_command(py, targ, a.model, j, out_dir, status)
        with open(out_dir / f"{tag}.out", "w", encoding="utf-8") as so, open(out_dir / f"{tag}.err", "w", encoding="utf-8") as se:
            code = subprocess.run(cmd, stdout=so, stderr=se, env=env, cwd=str(REPO)).returncode
        log({"job_end": tag, "exit": code})
        worst = max(worst, code if code in (0, 1) else 2)  # 1 = baseline regression (data, not a crash)
        if code not in (0, 1):  # 3 = MTP witness failed; anything else = crash
            log({"job_failed": tag, "exit": code})
    log({"done": True, "campaign": a.model, "worst_exit": worst})
    return 0


if __name__ == "__main__":
    sys.exit(main())
