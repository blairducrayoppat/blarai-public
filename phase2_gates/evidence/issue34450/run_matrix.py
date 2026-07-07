"""Top-level orchestrator for issue #34450 reproduction matrix.

Runs each cell, captures crash logs, computes artifact sha256s, and emits
two reports:

* ``repro_matrix.json`` -- machine-readable, full provenance.
* ``repro_matrix.md``   -- human-readable, suitable for a GitHub comment.

The crash subprocess (``repro_npu_draft.py``) is allowed to abort with
SIGABRT; this orchestrator captures the exit code + stderr and continues
to the next cell. The TARGET model (Qwen3-14B INT4 GPU) must be present
on disk; if absent, this script will refuse to run rather than guessing
substitutes -- a half-empirical matrix is worse than no matrix.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = Path(__file__).parent
EXPORTS = EVIDENCE / "exports"
HARNESS = EVIDENCE / "repro_npu_draft.py"

TARGET_PATH = ROOT / "models" / "qwen3-14b" / "openvino-int4-gpu"
EXPORT_VENV_PY = ROOT / ".export-venv" / "Scripts" / "python.exe"

# Cell name -> (description, draft model path resolver). Cell A uses the
# pre-existing artifact; Cells B and C use freshly exported artifacts.
CELL_DESCRIPTIONS = {
    "cell_a": "Existing on-disk NPU export (no --task, no --disable-stateful, stateful by default)",
    "cell_b": "Fresh export with --task text-generation-with-past (stateful)",
    "cell_c": "Fresh export with --task text-generation-with-past --disable-stateful",
}

CELL_DRAFT_PATHS = {
    "cell_a": ROOT / "models" / "qwen3-0.6b" / "openvino-int4-npu",
    "cell_b": EXPORTS / "cell_b",
    "cell_c": EXPORTS / "cell_c",
}


@dataclass
class CellResult:
    cell: str
    description: str
    draft_path: str
    draft_present: bool
    draft_xml_sha256: str | None
    draft_bin_sha256: str | None
    draft_input_names: list[str] = field(default_factory=list)
    has_past_kv_inputs: bool = False
    crash_log_path: str | None = None
    exit_code: int | None = None
    elapsed_seconds: float | None = None
    outcome: str = "not_run"  # ok | python_exception | aborted | skipped | not_run
    stderr_tail: str = ""
    python_exception_class: str | None = None
    python_exception_msg: str | None = None


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def inspect_model(xml_path: Path) -> tuple[list[str], bool]:
    """Return (input_names, has_past_kv_inputs)."""
    import openvino as ov  # local import keeps orchestrator startup cheap
    m = ov.Core().read_model(str(xml_path))
    names = [i.get_any_name() for i in m.inputs]
    return names, any("past_key_values" in n for n in names)


def run_cell(name: str, python_exe: Path, target_path: Path) -> CellResult:
    draft_path = CELL_DRAFT_PATHS[name]
    desc = CELL_DESCRIPTIONS[name]

    if not draft_path.is_dir() or not (draft_path / "openvino_model.xml").exists():
        return CellResult(
            cell=name, description=desc, draft_path=str(draft_path),
            draft_present=False, draft_xml_sha256=None, draft_bin_sha256=None,
            outcome="skipped",
            stderr_tail="draft path missing or empty -- export not performed",
        )

    xml_path = draft_path / "openvino_model.xml"
    bin_path = draft_path / "openvino_model.bin"
    xml_hash = sha256(xml_path)
    bin_hash = sha256(bin_path) if bin_path.exists() else None

    try:
        input_names, has_past = inspect_model(xml_path)
    except Exception as exc:  # noqa: BLE001
        input_names, has_past = [], False
        print(f"[{name}] WARN: model inspection failed: {exc}", flush=True)

    crash_log_path = EVIDENCE / f"{name}_crash.log"
    cmd = [
        str(python_exe), str(HARNESS),
        "--target", str(target_path),
        "--draft", str(draft_path),
    ]
    print(f"[{name}] {' '.join(cmd)}", flush=True)

    t0 = time.monotonic()
    with crash_log_path.open("w", encoding="utf-8", errors="replace") as log:
        log.write(f"# command: {' '.join(cmd)}\n")
        log.write(f"# started: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n")
        log.write(f"# draft sha256 (xml): {xml_hash}\n")
        log.write(f"# draft sha256 (bin): {bin_hash}\n\n")
        log.flush()
        proc = subprocess.run(
            cmd, stdout=log, stderr=subprocess.STDOUT,
            cwd=str(ROOT), check=False,
        )
    elapsed = time.monotonic() - t0
    text = crash_log_path.read_text(encoding="utf-8", errors="replace")
    tail_lines = text.splitlines()[-40:]
    tail = "\n".join(tail_lines)

    if proc.returncode == 0 and "OK" in text.splitlines()[-5:]:
        outcome = "ok"
        py_cls = py_msg = None
    elif "PYTHON_EXCEPTION:" in text:
        outcome = "python_exception"
        marker = next((ln for ln in text.splitlines() if ln.startswith("PYTHON_EXCEPTION:")), "")
        parts = marker.split(":", 2)
        py_cls = parts[1] if len(parts) >= 2 else None
        py_msg = parts[2] if len(parts) >= 3 else None
    else:
        outcome = "aborted"
        py_cls = py_msg = None

    print(f"[{name}] outcome={outcome} exit={proc.returncode} elapsed={elapsed:.1f}s",
          flush=True)

    return CellResult(
        cell=name, description=desc, draft_path=str(draft_path),
        draft_present=True, draft_xml_sha256=xml_hash, draft_bin_sha256=bin_hash,
        draft_input_names=input_names, has_past_kv_inputs=has_past,
        crash_log_path=str(crash_log_path),
        exit_code=proc.returncode, elapsed_seconds=round(elapsed, 1),
        outcome=outcome, stderr_tail=tail,
        python_exception_class=py_cls, python_exception_msg=py_msg,
    )


def collect_versions(python_exe: Path) -> dict:
    """Collect package versions for an arbitrary interpreter.

    Tolerant of missing packages (e.g. openvino_genai not installed in
    .export-venv) and import-time failures (e.g. editable optimum-intel that
    chokes against installed transformers in the runtime venv).
    """
    code = (
        "import json, sys; import importlib.metadata as md\n"
        "out = {'python': '%d.%d.%d' % sys.version_info[:3]}\n"
        "for pkg in ['openvino','openvino-genai','optimum','optimum-intel',"
        "'transformers','nncf','torch']:\n"
        "    try:\n"
        "        out[pkg.replace('-', '_')] = md.version(pkg)\n"
        "    except Exception:\n"
        "        out[pkg.replace('-', '_')] = None\n"
        "print(json.dumps(out))"
    )
    proc = subprocess.run(
        [str(python_exe), "-c", code],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        return {"_error": proc.stderr.strip()[:400]}
    return json.loads(proc.stdout.strip())


def write_markdown(matrix: dict, md_path: Path) -> None:
    env = matrix["environment"]
    lines: list[str] = []
    lines.append("# Issue #34450 — Reproduction Matrix\n")
    lines.append(f"_Generated: {matrix['generated_utc']}_\n")
    lines.append("## Environment\n")
    lines.append("### Compile-time interpreter (--python)\n")
    lines.append("| Field | Value |")
    lines.append("|---|---|")
    lines.append(f"| Host | {env['host']['system']} {env['host']['release']} ({env['host']['machine']}) |")
    lines.append(f"| Python | {env['versions'].get('python')} |")
    lines.append(f"| OpenVINO | {env['versions'].get('openvino')} |")
    lines.append(f"| OpenVINO GenAI | {env['versions'].get('openvino_genai')} |")
    lines.append(f"| optimum-intel | {env['versions'].get('optimum_intel')} |")
    lines.append(f"| transformers | {env['versions'].get('transformers')} |")
    lines.append(f"| nncf | {env['versions'].get('nncf')} |")
    lines.append(f"| Target model | `{matrix['target_path']}` |")
    lines.append("")
    lines.append("### Export-time interpreter (.export-venv)\n")
    lines.append("| Field | Value |")
    lines.append("|---|---|")
    ev = env.get("export_versions", {})
    if "_error" in ev:
        lines.append(f"| _error_ | {ev['_error']} |")
    else:
        lines.append(f"| Python | {ev.get('python')} |")
        lines.append(f"| OpenVINO | {ev.get('openvino')} |")
        lines.append(f"| optimum | {ev.get('optimum')} |")
        lines.append(f"| optimum-intel | {ev.get('optimum_intel')} |")
        lines.append(f"| transformers | {ev.get('transformers')} |")
        lines.append(f"| nncf | {ev.get('nncf')} |")
    lines.append("")
    lines.append("## Results\n")
    lines.append("| Cell | Description | Stateful? | Outcome | Exit | Notes |")
    lines.append("|---|---|---|---|---|---|")
    for cell in matrix["cells"]:
        stateful = "n/a" if not cell["draft_present"] else (
            "stateful" if not cell["has_past_kv_inputs"] else "stateless"
        )
        notes = cell.get("python_exception_msg") or ""
        if not notes and cell["outcome"] == "aborted":
            # Surface the most diagnostic line from the crash log tail.
            for ln in reversed(cell["stderr_tail"].splitlines()):
                if "ERROR" in ln or "LLVM" in ln or "Diagnostic" in ln:
                    notes = ln.strip()[:120]
                    break
        lines.append(f"| {cell['cell']} | {cell['description']} | {stateful} | "
                     f"{cell['outcome']} | {cell['exit_code']} | {notes} |")
    lines.append("")
    lines.append("## Per-cell crash log tails\n")
    for cell in matrix["cells"]:
        lines.append(f"### {cell['cell']}")
        lines.append(f"- draft path: `{cell['draft_path']}`")
        lines.append(f"- xml sha256: `{cell['draft_xml_sha256']}`")
        lines.append(f"- bin sha256: `{cell['draft_bin_sha256']}`")
        lines.append(f"- inputs: {cell['draft_input_names']}")
        lines.append(f"- has past_key_values inputs: {cell['has_past_kv_inputs']}")
        lines.append(f"- crash log: `{cell['crash_log_path']}`")
        lines.append("")
        lines.append("```")
        lines.append(cell["stderr_tail"])
        lines.append("```")
        lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, default=Path(sys.executable),
                        help="Python interpreter (defaults to current).")
    parser.add_argument("--target", type=Path, default=TARGET_PATH,
                        help="GPU target model directory.")
    parser.add_argument("--cells", nargs="*", default=list(CELL_DRAFT_PATHS.keys()),
                        help="Subset of cells to run.")
    parser.add_argument("--skip-export", action="store_true",
                        help="Do not run export_variants.py first; assume exports done.")
    args = parser.parse_args()

    if not args.target.is_dir():
        print(f"FATAL: target path does not exist: {args.target}", file=sys.stderr)
        return 2

    if not args.skip_export:
        export_cells = [c for c in args.cells if c in {"cell_b", "cell_c"}]
        if export_cells:
            print(f"--- exports ({export_cells}) ---", flush=True)
            # Note: do NOT forward --python here. export_variants.py defaults to
            # the dedicated .export-venv (optimum-intel 1.27.0 + nncf 3.0.0 +
            # transformers 4.51.3, matching issue #34450's environment). The
            # main .venv has an editable optimum-intel dev clone whose
            # _CAN_RECORD_REGISTRY import errors against installed transformers.
            rc = subprocess.call([
                str(args.python), str(EVIDENCE / "export_variants.py"),
                "--cells", *export_cells,
            ], cwd=str(ROOT))
            if rc != 0:
                print(f"WARN: export driver returned {rc}; continuing to inspect", flush=True)

    versions = collect_versions(args.python)
    export_versions = collect_versions(EXPORT_VENV_PY) if EXPORT_VENV_PY.exists() else {
        "_error": f"export venv interpreter not found at {EXPORT_VENV_PY}",
    }
    host = {
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
    }

    print("--- run cells ---", flush=True)
    cell_results = [asdict(run_cell(name, args.python, args.target))
                    for name in args.cells]

    matrix = {
        "issue": "openvinotoolkit/openvino#34450",
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "target_path": str(args.target),
        "environment": {"host": host, "versions": versions,
                        "export_versions": export_versions},
        "cells": cell_results,
    }

    json_path = EVIDENCE / "repro_matrix.json"
    md_path = EVIDENCE / "repro_matrix.md"
    json_path.write_text(json.dumps(matrix, indent=2), encoding="utf-8")
    write_markdown(matrix, md_path)
    print(f"\nwrote: {json_path}")
    print(f"wrote: {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
