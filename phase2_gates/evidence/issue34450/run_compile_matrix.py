"""D-J cell orchestrator for issue #34450 expansion.

Cell map:
  D: cell_b IR + device=CPU + mode=direct        (validate IR via CPU)
  E: cell_b IR + device=GPU + mode=direct        (validate IR via GPU)
  F: cell_b IR + device=NPU + mode=direct        (raw NPU, no NPUW)
  G: cell_b IR + device=NPU + mode=llmpipeline   (NPUW, no spec-decode wrapper)
  H: cell_h IR + device=NPU + mode=direct        (channel-wise INT4)
  I: cell_i IR + device=NPU + mode=direct        (INT8)
  J1: cell_b IR + device=NPU + mode=direct + NPU_COMPILER_TYPE=MLIR
  J2: cell_b IR + device=NPU + mode=direct + NPU_COMPILER_TYPE=DRIVER

Each cell runs in a subprocess via repro_compile.py with stdout+stderr captured
to ``cell_<id>_compile.log``. Outputs:
  * compile_matrix.json
  * compile_matrix.md
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
HARNESS = EVIDENCE / "repro_compile.py"

EXPORT_VENV_PY = ROOT / ".export-venv" / "Scripts" / "python.exe"


@dataclass
class CompileCell:
    cell: str
    description: str
    ir_dir: str
    device: str
    mode: str
    ov_config: dict = field(default_factory=dict)
    requires_export: str | None = None  # cell_b/cell_h/cell_i

CELLS: list[CompileCell] = [
    CompileCell("D",  "Cell B IR, direct compile on CPU (validate IR)",
                str(EXPORTS / "cell_b"), "CPU", "direct", requires_export="cell_b"),
    CompileCell("E",  "Cell B IR, direct compile on GPU (validate IR)",
                str(EXPORTS / "cell_b"), "GPU", "direct", requires_export="cell_b"),
    CompileCell("F",  "Cell B IR, direct compile on NPU (raw, no NPUW)",
                str(EXPORTS / "cell_b"), "NPU", "direct", requires_export="cell_b"),
    CompileCell("G",  "Cell B IR, LLMPipeline on NPU (NPUW, no spec-decode wrapper)",
                str(EXPORTS / "cell_b"), "NPU", "llmpipeline", requires_export="cell_b"),
    CompileCell("H",  "Cell H IR (channel-wise INT4), direct compile on NPU",
                str(EXPORTS / "cell_h"), "NPU", "direct", requires_export="cell_h"),
    CompileCell("I",  "Cell I IR (INT8), direct compile on NPU",
                str(EXPORTS / "cell_i"), "NPU", "direct", requires_export="cell_i"),
    CompileCell("J1", "Cell B IR, direct compile on NPU with NPU_COMPILER_TYPE=MLIR",
                str(EXPORTS / "cell_b"), "NPU", "direct",
                ov_config={"NPU_COMPILER_TYPE": "MLIR"}, requires_export="cell_b"),
    CompileCell("J2", "Cell B IR, direct compile on NPU with NPU_COMPILER_TYPE=DRIVER",
                str(EXPORTS / "cell_b"), "NPU", "direct",
                ov_config={"NPU_COMPILER_TYPE": "DRIVER"}, requires_export="cell_b"),
]


@dataclass
class CompileResult:
    cell: str
    description: str
    ir_dir: str
    ir_xml_sha256: str | None
    ir_bin_sha256: str | None
    device: str
    mode: str
    ov_config: dict
    log_path: str
    exit_code: int | None
    elapsed_seconds: float | None
    outcome: str  # ok | python_exception | aborted | skipped
    stderr_tail: str
    python_exception_class: str | None = None
    python_exception_msg: str | None = None


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run_cell(cell: CompileCell, python_exe: Path) -> CompileResult:
    ir_dir = Path(cell.ir_dir)
    xml = ir_dir / "openvino_model.xml"
    bin_p = ir_dir / "openvino_model.bin"

    if not xml.exists():
        return CompileResult(
            cell=cell.cell, description=cell.description, ir_dir=str(ir_dir),
            ir_xml_sha256=None, ir_bin_sha256=None,
            device=cell.device, mode=cell.mode, ov_config=cell.ov_config,
            log_path="", exit_code=None, elapsed_seconds=None,
            outcome="skipped",
            stderr_tail=f"IR missing: {xml} -- export {cell.requires_export} not performed",
        )

    xml_hash = sha256(xml)
    bin_hash = sha256(bin_p) if bin_p.exists() else None

    log_path = EVIDENCE / f"cell_{cell.cell.lower()}_compile.log"
    cmd = [
        str(python_exe), str(HARNESS),
        "--ir", str(ir_dir),
        "--device", cell.device,
        "--mode", cell.mode,
    ]
    for k, v in cell.ov_config.items():
        cmd.extend(["--ov-config", f"{k}={v}"])
    print(f"[{cell.cell}] {' '.join(cmd)}", flush=True)

    t0 = time.monotonic()
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        log.write(f"# command: {' '.join(cmd)}\n")
        log.write(f"# started: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n")
        log.write(f"# ir xml sha256: {xml_hash}\n")
        log.write(f"# ir bin sha256: {bin_hash}\n\n")
        log.flush()
        proc = subprocess.run(
            cmd, stdout=log, stderr=subprocess.STDOUT,
            cwd=str(ROOT), check=False,
        )
    elapsed = time.monotonic() - t0
    text = log_path.read_text(encoding="utf-8", errors="replace")
    tail = "\n".join(text.splitlines()[-40:])

    if proc.returncode == 0 and any(ln.startswith("OK ") for ln in text.splitlines()[-5:]):
        outcome = "ok"
        py_cls = py_msg = None
    elif "PYTHON_EXCEPTION:" in text:
        outcome = "python_exception"
        marker = next((ln for ln in text.splitlines()
                       if ln.startswith("PYTHON_EXCEPTION:")), "")
        parts = marker.split(":", 2)
        py_cls = parts[1] if len(parts) >= 2 else None
        py_msg = parts[2] if len(parts) >= 3 else None
    else:
        outcome = "aborted"
        py_cls = py_msg = None

    print(f"[{cell.cell}] outcome={outcome} exit={proc.returncode} elapsed={elapsed:.1f}s",
          flush=True)
    return CompileResult(
        cell=cell.cell, description=cell.description, ir_dir=str(ir_dir),
        ir_xml_sha256=xml_hash, ir_bin_sha256=bin_hash,
        device=cell.device, mode=cell.mode, ov_config=cell.ov_config,
        log_path=str(log_path), exit_code=proc.returncode,
        elapsed_seconds=round(elapsed, 1),
        outcome=outcome, stderr_tail=tail,
        python_exception_class=py_cls, python_exception_msg=py_msg,
    )


def collect_versions_via(python_exe: Path) -> dict:
    code = (
        "import json, importlib.metadata as md;"
        "out = {};"
        "import sys; out['python'] = '%d.%d.%d' % sys.version_info[:3];"
        "from contextlib import suppress\n"
        "for pkg in ['openvino','openvino-genai','optimum','optimum-intel',"
        "'transformers','nncf','torch']:\n"
        "    try:\n"
        "        out[pkg] = md.version(pkg)\n"
        "    except Exception:\n"
        "        out[pkg] = None\n"
        "print(json.dumps(out))"
    )
    proc = subprocess.run([str(python_exe), "-c", code],
                          capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return {"_error": proc.stderr.strip()[:400]}
    return json.loads(proc.stdout.strip())


def write_markdown(matrix: dict, md_path: Path) -> None:
    lines: list[str] = []
    lines.append("# Issue #34450 \u2014 Compile Matrix (Cells D\u2013J)\n")
    lines.append(f"_Generated: {matrix['generated_utc']}_\n")
    lines.append("## Environment\n")
    lines.append("### Compile-time interpreter (.venv)\n")
    lines.append("| Package | Version |")
    lines.append("|---|---|")
    for k, v in matrix["compile_versions"].items():
        lines.append(f"| {k} | `{v}` |")
    lines.append("")
    lines.append("### Export-time interpreter (.export-venv) \u2014 used to produce IR\n")
    lines.append("| Package | Version |")
    lines.append("|---|---|")
    for k, v in matrix["export_versions"].items():
        lines.append(f"| {k} | `{v}` |")
    lines.append("")
    h = matrix["host"]
    lines.append("### Host\n")
    lines.append(f"- {h['system']} {h['release']} ({h['machine']})")
    lines.append(f"- {h['processor']}")
    lines.append("")
    lines.append("## Results\n")
    lines.append("| Cell | Description | Device | Mode | ov_config | Outcome | Exit | Elapsed | Notes |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for c in matrix["cells"]:
        ovc = ", ".join(f"{k}={v}" for k, v in c["ov_config"].items()) or "\u2014"
        notes = c.get("python_exception_msg") or ""
        if not notes and c["outcome"] == "aborted":
            for ln in reversed(c["stderr_tail"].splitlines()):
                if "ERROR" in ln or "LLVM" in ln or "Exception" in ln:
                    notes = ln.strip()[:140]
                    break
        notes = notes.replace("|", "\\|")[:140]
        lines.append(
            f"| {c['cell']} | {c['description']} | {c['device']} | {c['mode']} | "
            f"{ovc} | {c['outcome']} | {c['exit_code']} | "
            f"{c['elapsed_seconds']}s | {notes} |"
        )
    lines.append("")
    lines.append("## Per-cell log tails\n")
    for c in matrix["cells"]:
        lines.append(f"### Cell {c['cell']} \u2014 {c['description']}")
        lines.append(f"- ir: `{c['ir_dir']}`")
        lines.append(f"- ir xml sha256: `{c['ir_xml_sha256']}`")
        lines.append(f"- ir bin sha256: `{c['ir_bin_sha256']}`")
        lines.append(f"- log: `{c['log_path']}`")
        lines.append("")
        lines.append("```")
        lines.append(c["stderr_tail"])
        lines.append("```")
        lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, default=Path(sys.executable),
                        help="Compile interpreter (defaults to current .venv).")
    parser.add_argument("--cells", nargs="*", default=[c.cell for c in CELLS],
                        help="Subset of cells to run (e.g. F J1 J2).")
    parser.add_argument("--skip-export", action="store_true",
                        help="Do not invoke export_variants.py first.")
    args = parser.parse_args()

    selected = [c for c in CELLS if c.cell in set(args.cells)]
    if not selected:
        print(f"FATAL: no matching cells in {args.cells}", file=sys.stderr)
        return 2

    needed_exports = sorted({c.requires_export for c in selected if c.requires_export})
    if not args.skip_export and needed_exports:
        print(f"--- ensuring exports: {needed_exports} ---", flush=True)
        rc = subprocess.call([
            str(args.python), str(EVIDENCE / "export_variants.py"),
            "--cells", *needed_exports,
        ], cwd=str(ROOT))
        if rc != 0:
            print(f"WARN: export driver returned {rc}; continuing", flush=True)

    print("--- collect versions ---", flush=True)
    compile_versions = collect_versions_via(args.python)
    export_versions = collect_versions_via(EXPORT_VENV_PY)

    host = {
        "system": platform.system(), "release": platform.release(),
        "version": platform.version(), "machine": platform.machine(),
        "processor": platform.processor(),
    }

    print("--- run compile cells ---", flush=True)
    results = [asdict(run_cell(c, args.python)) for c in selected]

    matrix = {
        "issue": "openvinotoolkit/openvino#34450",
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "host": host,
        "compile_versions": compile_versions,
        "export_versions": export_versions,
        "cells": results,
    }
    json_path = EVIDENCE / "compile_matrix.json"
    md_path = EVIDENCE / "compile_matrix.md"
    json_path.write_text(json.dumps(matrix, indent=2), encoding="utf-8")
    write_markdown(matrix, md_path)
    print(f"\nwrote: {json_path}")
    print(f"wrote: {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
