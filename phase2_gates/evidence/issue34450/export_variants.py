"""Driver: export Qwen3-0.6B INT4 variants for issue #34450 reproduction.

Runs ``optimum-cli export openvino`` once per cell into
``phase2_gates/evidence/issue34450/exports/<cell_name>/``. Captures full
stdout/stderr per cell into a sibling ``cell_<name>_export.log``.

Cells are described in ``README.md``. This script ONLY does exports; the
crash-reproduction step is run separately by ``run_matrix.py`` against
``repro_npu_draft.py``.

Idempotent: if an export directory already contains ``openvino_model.xml``
the cell is skipped. To force re-export, delete the directory.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = Path(__file__).parent
EXPORTS = EVIDENCE / "exports"

# Default export-only venv: optimum 1.27.0 + optimum-intel 1.25.2 (released)
# + transformers 4.51.3. Keep this separate from the main .venv (which holds
# the editable optimum-intel dev clone used by the runtime).
DEFAULT_EXPORT_PY = ROOT / ".export-venv" / "Scripts" / "python.exe"

MODEL_ID = "Qwen/Qwen3-0.6B"

# Each cell carries its FULL optimum-cli args (no implicit COMMON_ARGS) so
# precision/group-size variants can override cleanly. Cell A is omitted; it
# uses the pre-existing on-disk artifact at models/qwen3-0.6b/openvino-int4-npu/.
CELLS: dict[str, list[str]] = {
    # Diego's exact stack (Apr 24, 2026)
    "cell_b": [
        "--weight-format", "int4", "--group-size", "128", "--ratio", "1.0",
        "--task", "text-generation-with-past",
    ],
    # Same as B but explicit --sym (Intel's documented OV 2026.1 NPU LLM
    # recipe uses symmetric INT4). Tests whether the NPUW failure persists
    # under the officially recommended quantization scheme.
    "cell_b_sym": [
        "--weight-format", "int4", "--group-size", "128", "--ratio", "1.0",
        "--sym", "--task", "text-generation-with-past",
    ],
    # Same as B but stateless (legacy non-stateful export)
    "cell_c": [
        "--weight-format", "int4", "--group-size", "128", "--ratio", "1.0",
        "--task", "text-generation-with-past", "--disable-stateful",
    ],
    # Channel-wise INT4 (no per-group quantization). Tests whether per-group
    # is the trigger for the StopLocationVerifierPass / 0-channel bug.
    "cell_h": [
        "--weight-format", "int4", "--group-size", "-1", "--ratio", "1.0",
        "--task", "text-generation-with-past",
    ],
    # INT8 weight-only. Tests whether INT4 specifically is required.
    "cell_i": [
        "--weight-format", "int8",
        "--task", "text-generation-with-past",
    ],
}


def export_cell(name: str, extra_args: list[str], python_exe: Path) -> dict:
    out_dir = EXPORTS / name
    log_path = EVIDENCE / f"{name}_export.log"

    if (out_dir / "openvino_model.xml").exists():
        return {
            "cell": name,
            "skipped": True,
            "reason": "export already present",
            "out_dir": str(out_dir),
            "log_path": str(log_path) if log_path.exists() else None,
        }

    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(python_exe), "-m", "optimum.commands.optimum_cli",
        "export", "openvino",
        "--model", MODEL_ID,
        *extra_args,
        str(out_dir),
    ]

    print(f"[{name}] {' '.join(cmd)}", flush=True)
    t0 = time.monotonic()
    with log_path.open("w", encoding="utf-8") as log:
        log.write(f"# command: {' '.join(cmd)}\n")
        log.write(f"# started: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n\n")
        log.flush()
        proc = subprocess.run(
            cmd, stdout=log, stderr=subprocess.STDOUT,
            cwd=str(ROOT), check=False,
        )
    elapsed = time.monotonic() - t0

    success = proc.returncode == 0 and (out_dir / "openvino_model.xml").exists()
    if not success:
        # Leave partial artifacts in place for forensics, but flag clearly.
        print(f"[{name}] FAILED (exit={proc.returncode}, elapsed={elapsed:.1f}s)", flush=True)
    else:
        print(f"[{name}] ok (elapsed={elapsed:.1f}s)", flush=True)

    return {
        "cell": name,
        "skipped": False,
        "command": cmd,
        "exit_code": proc.returncode,
        "elapsed_seconds": round(elapsed, 1),
        "success": success,
        "out_dir": str(out_dir),
        "log_path": str(log_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, default=DEFAULT_EXPORT_PY,
                        help=f"Python interpreter (default: {DEFAULT_EXPORT_PY}).")
    parser.add_argument("--cells", nargs="*", default=list(CELLS.keys()),
                        help=f"Subset of cells to export (default: all of {list(CELLS.keys())}).")
    args = parser.parse_args()

    EXPORTS.mkdir(parents=True, exist_ok=True)

    results = []
    for name in args.cells:
        if name not in CELLS:
            print(f"unknown cell: {name}", file=sys.stderr)
            return 2
        results.append(export_cell(name, CELLS[name], args.python))

    print("\n--- export summary ---")
    print(json.dumps(results, indent=2))
    return 0 if all(r.get("success") or r.get("skipped") for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
