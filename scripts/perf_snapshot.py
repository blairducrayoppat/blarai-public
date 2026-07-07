"""
BlarAI performance snapshot
===========================
Captures one performance data point and appends it to a single, growing
time-series dataset: ``docs/performance/perf_history.jsonl`` (one JSON
object per line). Run it whenever a data point is worth keeping — after a
driver update, a model swap, a boot-time change, or just periodically —
so memory, boot time, and inference latency can be tracked over the life
of the project.

Each snapshot captures:
  - memory   — system RAM in use + BlarAI's own host and GPU footprint
               (the Arc 140V is an integrated GPU, so its memory is
               system RAM). Live; null fields if BlarAI is not running.
  - boot     — the most recent boot duration, parsed from launcher.log.
  - inference— median time-to-first-token (TTFT) and throughput, ingested
               from the most recent benchmark_*.json if one exists.
  - context  — timestamp, git SHA, OpenVINO version.

This script does not run inference itself — it is light and safe to run
while BlarAI is live. For fresh inference numbers run
``scripts/benchmark_gpu_inference.py`` first, then this.

Usage (from repo root, BlarAI venv):
  .venv\\Scripts\\python.exe scripts\\perf_snapshot.py
  .venv\\Scripts\\python.exe scripts\\perf_snapshot.py --note "after Arc driver update"
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PERF_DIR = _REPO_ROOT / "docs" / "performance"
_HISTORY_PATH = _PERF_DIR / "perf_history.jsonl"

# launcher.log boot markers.
_BOOT_START_RE = re.compile(
    r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),(\d+).*Startup: Checking Administrator"
)
_BOOT_DONE_RE = re.compile(
    r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),(\d+).*Boot-Phase-3: OPERATIONAL"
)
_TS_FMT = "%Y-%m-%d %H:%M:%S"


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested)
# ---------------------------------------------------------------------------


def _parse_log_ts(date_part: str, millis: str) -> datetime:
    """Parse a launcher.log timestamp ('2026-05-22 14:18:47', '605')."""
    base = datetime.strptime(date_part, _TS_FMT)
    return base.replace(microsecond=int(millis) * 1000)


def parse_latest_boot(log_text: str) -> dict | None:
    """Find the most recent *complete* boot in launcher.log text.

    The completed boot is the last 'Boot-Phase-3: OPERATIONAL' line plus
    the last 'Checking Administrator' line preceding it. A boot still in
    progress — a start with no OPERATIONAL line yet — is skipped in
    favour of the previous complete boot. Returns ``{"started": ...,
    "seconds": float}`` or None if no complete boot is present.
    """
    starts: list[tuple[int, datetime]] = []
    dones: list[tuple[int, datetime]] = []
    for idx, line in enumerate(log_text.splitlines()):
        m = _BOOT_START_RE.match(line)
        if m:
            starts.append((idx, _parse_log_ts(m.group(1), m.group(2))))
            continue
        m = _BOOT_DONE_RE.match(line)
        if m:
            dones.append((idx, _parse_log_ts(m.group(1), m.group(2))))
    if not starts or not dones:
        return None
    done_idx, done_ts = dones[-1]  # most recent completed boot's end
    preceding = [s for s in starts if s[0] < done_idx]
    if not preceding:
        return None
    _, start_ts = preceding[-1]  # the start that boot belongs to
    return {
        "started": start_ts.isoformat(sep=" "),
        "seconds": round((done_ts - start_ts).total_seconds(), 1),
    }


def extract_benchmark_metrics(data: dict) -> dict:
    """Pull headline TTFT + throughput from a benchmark_*.json payload.

    Prefers the speculative-decoding-ON result (how BlarAI actually runs);
    falls back to whatever single result config is present.
    """
    results = data.get("results", {})
    if not isinstance(results, dict) or not results:
        return {}
    block = results.get("spec_on") or next(iter(results.values()), None)
    if not isinstance(block, dict):
        return {}
    agg = block.get("aggregate", {})
    if not isinstance(agg, dict):
        return {}
    config = "spec_on" if "spec_on" in results else next(iter(results), "")
    return {
        "config": config,
        "median_ttft_ms": agg.get("median_ttft_ms"),
        "median_tps": agg.get("median_tps"),
        "load_ms": block.get("load_ms"),
    }


def find_latest_benchmark(perf_dir: Path) -> Path | None:
    """Return the newest benchmark_*.json by its filename timestamp.

    The filename — ``benchmark_YYYY-MM-DD_HH-MM-SS.json`` — encodes when
    the benchmark actually ran and sorts chronologically. mtime is not
    used: it is disturbed by file copies and git checkouts (observed on
    this repo — an old run had the newest mtime).
    """
    candidates = sorted(perf_dir.glob("benchmark_*.json"), reverse=True)
    return candidates[0] if candidates else None


def build_record(
    *,
    git_sha: str,
    openvino_version: str,
    memory: dict,
    power: dict,
    boot: dict | None,
    inference: dict,
    note: str,
) -> dict:
    """Assemble one perf-history record."""
    return {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_sha": git_sha,
        "openvino_version": openvino_version,
        "boot": boot,
        "memory": memory,
        "power": power or None,
        "inference": inference or None,
        "note": note,
    }


def append_jsonl(record: dict, path: Path) -> None:
    """Append one record as a JSON line, creating the file/dir if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")


# ---------------------------------------------------------------------------
# Live measurement (not unit-tested — depends on the running system)
# ---------------------------------------------------------------------------

_PS_SNAPSHOT = r"""
$os = Get-CimInstance Win32_OperatingSystem
$totalMB = [math]::Round($os.TotalVisibleMemorySize/1KB,1)
$freeMB  = [math]::Round($os.FreePhysicalMemory/1KB,1)
$py = Get-Process python -ErrorAction SilentlyContinue | Sort-Object WorkingSet64 -Descending | Select-Object -First 1
$pid2 = if ($py) { $py.Id } else { 0 }
$wsMB = if ($py) { [math]::Round($py.WorkingSet64/1MB,1) } else { 0 }
$gpuMB = 0
if ($py) {
  try {
    (Get-Counter '\GPU Process Memory(*)\Local Usage' -ErrorAction Stop).CounterSamples |
      Where-Object { $_.InstanceName -match ('pid_' + $pid2 + '_') } |
      ForEach-Object { $gpuMB += $_.CookedValue/1MB }
  } catch {}
}
# BlarAI is "running" only if the top python process is GB-scale.
$running = ($wsMB -gt 1024)
# Power line status — a real confound for perf numbers (battery throttles).
$lineStatus = 'Unknown'; $battPct = $null
try {
  Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
  $ps = [System.Windows.Forms.SystemInformation]::PowerStatus
  $lineStatus = $ps.PowerLineStatus.ToString()
  $bp = $ps.BatteryLifePercent
  if ($bp -ge 0 -and $bp -le 1) { $battPct = [math]::Round($bp*100,0) }
} catch {}
[pscustomobject]@{
  system_total_mb=$totalMB; system_free_mb=$freeMB
  blarai_running=$running; blarai_pid=$pid2
  blarai_host_ws_mb=$wsMB; blarai_gpu_mb=[math]::Round($gpuMB,1)
  power_line_status=$lineStatus; battery_percent=$battPct
} | ConvertTo-Json -Compress
"""


def measure_system() -> dict:
    """Measure system/BlarAI memory and power state via PowerShell.

    Power state is captured because it is a real confound for any perf
    number — on battery the CPU/GPU throttle, so a battery measurement is
    not comparable to one on AC. Returns ``{"memory": {...}, "power":
    {...}}``, or ``{"error": ...}`` if the measurement could not be taken
    (non-Windows, PowerShell failure).
    """
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS_SNAPSHOT],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        raw = json.loads(out.stdout.strip())
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        return {"error": f"system measurement unavailable: {e}"}

    total_gb = round(raw["system_total_mb"] / 1024, 2)
    free_gb = round(raw["system_free_mb"] / 1024, 2)
    running = bool(raw.get("blarai_running"))
    memory = {
        "system_total_gb": total_gb,
        "system_used_gb": round(total_gb - free_gb, 2),
        "system_free_gb": free_gb,
        "blarai_running": running,
        "blarai_host_ws_mb": raw["blarai_host_ws_mb"] if running else None,
        "blarai_gpu_mb": raw["blarai_gpu_mb"] if running else None,
    }
    power = {
        "line_status": raw.get("power_line_status", "Unknown"),
        "battery_percent": raw.get("battery_percent"),
    }
    return {"memory": memory, "power": power}


def git_sha() -> str:
    """Short git SHA of the repo HEAD, or 'unknown'."""
    try:
        out = subprocess.run(
            ["git", "-C", str(_REPO_ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _openvino_version() -> str:
    try:
        import openvino as ov  # type: ignore[import-untyped]

        return str(ov.__version__)
    except Exception:  # noqa: BLE001
        return "unavailable"


def _read_launcher_log() -> str:
    local = os.environ.get("LOCALAPPDATA", "")
    if not local:
        return ""
    log_path = Path(local) / "BlarAI" / "launcher.log"
    try:
        return log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _fmt(value: object, suffix: str = "") -> str:
    return f"{value}{suffix}" if value is not None else "n/a"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture a BlarAI performance snapshot.")
    parser.add_argument("--note", default="", help="free-text note for this data point")
    parser.add_argument(
        "--history",
        default=str(_HISTORY_PATH),
        help="path to the perf-history JSONL dataset",
    )
    args = parser.parse_args(argv)

    sysinfo = measure_system()
    if "error" in sysinfo:
        memory: dict = {"error": sysinfo["error"]}
        power: dict = {}
    else:
        memory = sysinfo["memory"]
        power = sysinfo["power"]
    boot = parse_latest_boot(_read_launcher_log())

    inference: dict = {}
    latest = find_latest_benchmark(_PERF_DIR)
    if latest is not None:
        try:
            inference = extract_benchmark_metrics(json.loads(latest.read_text("utf-8")))
            inference["source"] = latest.name
        except (OSError, ValueError):
            inference = {}

    record = build_record(
        git_sha=git_sha(),
        openvino_version=_openvino_version(),
        memory=memory,
        power=power,
        boot=boot,
        inference=inference,
        note=args.note,
    )
    history_path = Path(args.history)
    append_jsonl(record, history_path)

    # Human-readable summary.
    print(f"Performance snapshot recorded -> {history_path}")
    print(f"  timestamp   {record['ts']}  (git {record['git_sha']})")
    if "error" in memory:
        print(f"  memory      {memory['error']}")
    elif memory.get("blarai_running"):
        print(
            f"  memory      system {memory['system_used_gb']}/"
            f"{memory['system_total_gb']} GB used  |  "
            f"BlarAI host {_fmt(memory['blarai_host_ws_mb'],' MB')}, "
            f"GPU {_fmt(memory['blarai_gpu_mb'],' MB')}"
        )
    else:
        print(
            f"  memory      system {memory['system_used_gb']}/"
            f"{memory['system_total_gb']} GB used  |  BlarAI not running"
        )
    if power:
        bp = power.get("battery_percent")
        bp_str = f", battery {bp}%" if bp is not None else ""
        print(f"  power       {power.get('line_status', 'Unknown')}{bp_str}")
    if boot:
        print(f"  boot        {boot['seconds']}s  (started {boot['started']})")
    else:
        print("  boot        n/a (no complete boot in launcher.log)")
    if inference:
        print(
            f"  inference   TTFT {_fmt(inference.get('median_ttft_ms'),' ms')} median, "
            f"{_fmt(inference.get('median_tps'),' tok/s')} median  "
            f"[{inference.get('source','?')}]"
        )
    else:
        print("  inference   n/a (no benchmark_*.json; run benchmark_gpu_inference.py)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
