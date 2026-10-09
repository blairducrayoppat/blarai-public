"""Sustained coder-throughput measurement with continuous resource sampling.

WHY THIS EXISTS. Every performance number taken during the 2026-08-31 investigation was
a SNAPSHOT, and snapshots drifted: the same configuration reported "+6.22 GB returned"
in one reading and "+1.38 GB" in another, because one was taken warm and one cold. A
single sample cannot tell you what to expect from a coder run that lasts an hour.

WHAT IT MEASURES
  * N consecutive REALISTIC generations -- a long operator-content prompt in, a
    page-sized completion out -- not 128-token toys.
  * Resource state sampled CONTINUOUSLY on a background thread throughout, so RAM and
    GPU-shared memory are reported as min/mean/max over the window rather than as one
    lucky instant.
  * DRIFT explicitly: first vs last run, and the spread across runs. A configuration
    that starts at 18 tok/s and ends at 6 is not an 18 tok/s configuration, and a
    single median would hide that.

HONEST LIMITS, stated because this file exists to stop over-claiming:
  * It measures ONE stream. The fleet runs candidates sequentially, so that matches, but
    it says nothing about concurrency.
  * `FreePhysicalMemory` is the OS's number; "GPU shared memory" on this iGPU IS system
    RAM, so the two figures are not independent and must not be added.
  * It does not model tool-call round trips, which the real coder interleaves with
    generation. Real per-task wall time will be longer than the sum of these decodes.

Usage (repo root, OVMS already serving, AO DOWN):
  .venv\\Scripts\\python.exe scripts\\measure_coder_sustained.py --runs 6 --max-tokens 1500
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
ENDPOINT = "http://127.0.0.1:8000/v3/chat/completions"
MODELS_URL = "http://127.0.0.1:8000/v3/models"
ASSETS = Path("C:/Users/mrbla/projects/blairproweb/assets")
AO_PORT = 5001

_PS = (
    "$os = Get-CimInstance Win32_OperatingSystem; "
    "$t = $os.TotalVisibleMemorySize/1MB; $a = $os.FreePhysicalMemory/1MB; "
    "$g = Get-Counter '\\GPU Process Memory(*)\\Shared Usage' -EA SilentlyContinue | "
    "Select-Object -Expand CounterSamples | Where-Object {$_.CookedValue -gt 500MB} | "
    "Measure-Object CookedValue -Sum; "
    "'{0:N3},{1:N3},{2:N3}' -f $a, ($t-$a), ($g.Sum/1GB)"
)


def sample_resources() -> dict | None:
    """One (ram_avail, ram_in_use, gpu_shared) reading in GiB. None if unreadable."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", _PS],
            capture_output=True, text=True, timeout=25,
        ).stdout.strip().splitlines()
        if not out:
            return None
        a, u, g = (float(x.replace(",", "")) for x in out[-1].split(","))
        return {"ram_avail_gib": a, "ram_in_use_gib": u, "gpu_shared_gib": g}
    except Exception:  # noqa: BLE001 -- a failed sample must never fail the measurement
        return None


def ao_is_up() -> bool:
    """The AO and the coder cannot both be resident (#1477). Refuse rather than
    report a contended number as a baseline."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        s.bind(("127.0.0.1", AO_PORT))
        return False
    except OSError:
        return True
    finally:
        s.close()


def machine_uptime_s() -> float | None:
    """Seconds since the machine booted, or None where it cannot be read.

    WHY THIS IS IN A PERFORMANCE HARNESS. #1487 measured one unchanged configuration
    at 16.55, 11.82 and 9.59 tok/s inside one hour, and neither idling nor restarting
    the server recovered it. Whether the decay is bounded by the OS session or by
    something longer-lived is decidable ONLY if every record says how old the machine
    was when it was taken. A number with no clock behind it cannot answer that later.
    """
    try:
        import ctypes
        return ctypes.windll.kernel32.GetTickCount64() / 1000.0
    except Exception:  # noqa: BLE001 -- an unreadable clock must never fail a measurement
        return None


def stamp_run(r: dict, index: int, session_s: float, uptime_s: "float | None") -> dict:
    """Attach WHEN this run happened: its ordinal, its offset into this harness run, and the
    machine's age.

    SEPARATED ON PURPOSE. A test can monkeypatch this to a no-op, drive the harness, and run
    the REAL assertions against the result -- a toggle that mutates the subject rather than one
    that re-implements an assertion against a dict it built. The first version of that lock was
    the second kind and was green against a harness that stamped nothing (lesson 30, whose third
    instance this discharges).
    """
    r["index"] = index
    r["elapsed_session_s"] = session_s
    r["machine_uptime_s"] = round(uptime_s, 1) if uptime_s is not None else None
    return r


def build_prompt() -> str:
    """The operator's REAL content files -- the shape the coder actually receives."""
    parts = []
    for name in ("what-this-site-must-do.md", "bio.md", "about-blarai.md",
                 "certifications.md", "openvino-contributions.md", "image-notes.md"):
        p = ASSETS / name
        if p.is_file():
            parts.append(f"--- {name} ---\n{p.read_text(encoding='utf-8', errors='replace')}")
    if not parts:
        raise SystemExit(f"no content files found under {ASSETS}")
    return (
        "You are extending ONE self-contained index.html for a personal website. Below "
        "are the operator's own content files. Read them and write a complete section: "
        "semantic HTML plus an inline <style> block. Use the operator's real words. "
        "Output only HTML.\n\n" + "\n\n".join(parts)
    )


def generate(prompt: str, max_tokens: int, timeout: float) -> dict:
    body = json.dumps({"model": "coder-30b",
                       "messages": [{"role": "user", "content": prompt}],
                       "max_tokens": max_tokens, "temperature": 0}).encode()
    t0 = time.time()
    resp = urllib.request.urlopen(
        urllib.request.Request(ENDPOINT, body, {"Content-Type": "application/json"}),
        timeout=timeout)
    d = json.loads(resp.read())
    el = time.time() - t0
    u = d["usage"]
    txt = (d["choices"][0]["message"].get("content") or "")
    return {"prompt_tokens": u["prompt_tokens"], "completion_tokens": u["completion_tokens"],
            "wall_s": round(el, 2), "decode_tps": round(u["completion_tokens"] / el, 2),
            "output_chars": len(txt), "produced_markup": "<" in txt and len(txt) > 400}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=6)
    ap.add_argument("--max-tokens", type=int, default=1500)
    ap.add_argument("--timeout", type=float, default=1800)
    ap.add_argument("--sample-every", type=float, default=10.0)
    ap.add_argument("--label", default="", help="config under test, e.g. 'cs4+offload40'")
    ap.add_argument("--allow-ao-resident", action="store_true")
    args = ap.parse_args()

    if ao_is_up() and not args.allow_ao_resident:
        print("FATAL: port 5001 has a listener -- the AO is up and the coder's weights")
        print("will spill. Close the app and re-run, or pass --allow-ao-resident to")
        print("measure anyway (the record is stamped and is NOT a baseline).")
        return 2
    if "coder-30b" not in urllib.request.urlopen(MODELS_URL, timeout=10).read().decode():
        print("FATAL: OVMS is not serving coder-30b.")
        return 1

    harness_t0 = time.time()
    uptime_at_start = machine_uptime_s()

    samples: list[dict] = []
    stop = threading.Event()

    def sampler() -> None:
        while not stop.is_set():
            s = sample_resources()
            if s:
                s["t"] = round(time.time(), 1)
                samples.append(s)
            stop.wait(args.sample_every)

    th = threading.Thread(target=sampler, daemon=True)
    th.start()

    prompt = build_prompt()
    print(f"prompt: {len(prompt):,} chars | runs: {args.runs} | max_tokens: {args.max_tokens}",
          flush=True)
    print("warming (discarded) ...", flush=True)
    try:
        generate(prompt, 64, args.timeout)
    except Exception as exc:  # noqa: BLE001
        print(f"warmup failed: {exc}")

    runs: list[dict] = []
    for i in range(args.runs):
        # #1487 item 2: WHEN a run was taken is part of the measurement, not metadata.
        # Captured BEFORE the call so a failed run still carries its position in time.
        started_session_s = round(time.time() - harness_t0, 1)
        started_uptime_s = machine_uptime_s()
        try:
            r = generate(prompt, args.max_tokens, args.timeout)
        except Exception as exc:  # noqa: BLE001
            r = {"error": f"{type(exc).__name__}: {exc}"}
        stamp_run(r, i, started_session_s, started_uptime_s)
        runs.append(r)
        print(f"  run{i}: " + (r.get("error") or
              f"{r['completion_tokens']} tok in {r['wall_s']}s = {r['decode_tps']} tok/s"),
              flush=True)

    stop.set()
    th.join(timeout=30)

    ok = [r for r in runs if "error" not in r]
    tps = [r["decode_tps"] for r in ok]
    drift = None
    if len(tps) >= 2:
        drift = {
            "first_tps": tps[0], "last_tps": tps[-1],
            "delta_pct": round(100 * (tps[-1] - tps[0]) / tps[0], 1),
            "spread_pct": round(100 * (max(tps) - min(tps)) / statistics.median(tps), 1),
        }

    def agg(key: str) -> dict:
        v = [s[key] for s in samples if key in s]
        return {"min": round(min(v), 2), "mean": round(statistics.mean(v), 2),
                "max": round(max(v), 2), "n": len(v)} if v else {}

    out = {
        "benchmark": "coder_sustained_throughput",
        "label": args.label,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "ao_resident": ao_is_up(),
        "session_clock": {
            "machine_uptime_at_start_s": round(uptime_at_start, 1) if uptime_at_start is not None else None,
            "harness_wall_s": round(time.time() - harness_t0, 1),
            "note": ("#1487: the same config decayed 16.55 -> 9.59 tok/s across one hour on this "
                     "box. Compare records at LIKE machine age, and never A/B two configs "
                     "back-to-back without interleaving them."),
        },
        "runs": runs,
        "errors": len(runs) - len(ok),
        "throughput_tps": {
            "median": round(statistics.median(tps), 2) if tps else None,
            "mean": round(statistics.mean(tps), 2) if tps else None,
            "min": min(tps) if tps else None, "max": max(tps) if tps else None,
        },
        "drift": drift,
        "resources_over_the_whole_window": {
            "ram_avail_gib": agg("ram_avail_gib"),
            "ram_in_use_gib": agg("ram_in_use_gib"),
            "gpu_shared_gib": agg("gpu_shared_gib"),
            "note": "gpu_shared is carved from system RAM on this iGPU -- do NOT add it to ram_in_use",
        },
        "not_measured": [
            "concurrency -- single stream only",
            "tool-call round trips, which the real coder interleaves with generation, so"
            " real per-task wall time exceeds the sum of these decodes",
            "thermal soak beyond the duration of this run",
        ],
    }

    print("\n=== SUSTAINED RESULT ===")
    print(f"  throughput  : median {out['throughput_tps']['median']} tok/s "
          f"(min {out['throughput_tps']['min']}, max {out['throughput_tps']['max']})")
    # The machine's age is printed, not just banked. A number taken on a soaked box is
    # allowed to exist; it is not allowed to look clean on the console (#1487). No
    # threshold is asserted here: what predicts decay is accumulated GPU work in the OS
    # session, which nothing measures -- uptime is a PROXY and is labelled as one.
    if uptime_at_start is not None:
        _run0 = next((r["machine_uptime_s"] for r in runs
                      if r.get("machine_uptime_s") is not None), None)
        _age = _run0 if _run0 is not None else uptime_at_start
        print(f"  machine age : {_age / 60:.0f} min since boot at run 0 "
              f"(PROXY for session soak. 2026-08-31, ONE OS session, same config: "
              f"16.55 -> 9.59 tok/s over ~1 h; a reboot restored it)")
    if drift:
        print(f"  DRIFT       : first {drift['first_tps']} -> last {drift['last_tps']} "
              f"({drift['delta_pct']:+}%), spread {drift['spread_pct']}%")
    r = out["resources_over_the_whole_window"]
    print(f"  RAM avail   : min {r['ram_avail_gib'].get('min')} / mean "
          f"{r['ram_avail_gib'].get('mean')} / max {r['ram_avail_gib'].get('max')} GiB "
          f"({r['ram_avail_gib'].get('n')} samples)")
    print(f"  GPU shared  : min {r['gpu_shared_gib'].get('min')} / mean "
          f"{r['gpu_shared_gib'].get('mean')} / max {r['gpu_shared_gib'].get('max')} GiB")
    print(f"  errors      : {out['errors']}")

    outdir = _REPO_ROOT / "docs" / "performance"
    outdir.mkdir(parents=True, exist_ok=True)
    stamp = out["timestamp"].replace(":", "-").replace("T", "_")
    lbl = (args.label or "run").replace("+", "_").replace(" ", "")
    path = outdir / f"coder_sustained_{lbl}_{stamp}.json"
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"  record      : {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
