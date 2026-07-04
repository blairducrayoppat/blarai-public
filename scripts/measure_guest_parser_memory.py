#!/usr/bin/env python3.14
"""Measure the BlarAI guest-parser VM memory footprint for right-sizing (#661).

Boots the ``BlarAI-Orchestrator`` Hyper-V guest, waits for the resident
trafilatura parser to report READY over the AF_HYPERV vsock parse channel, then
samples ``MemoryDemand`` / ``MemoryAssigned`` across four phases:

    boot   — cold-boot poll until the parser answers a health frame
    rest   — parser resident, idle (no parsing)
    burst  — sustained near-cap (~250 KiB) parses (keeps demand elevated long
             enough for Hyper-V's multi-second-cadence MemoryDemand to register,
             and proves Dynamic Memory hot-adds under load without OOM)
    settle — parsing stopped; confirms the balloon reclaims back toward rest

It REUSES the production parse harness (``make_health_probe`` /
``parse_round_trip``) rather than hand-rolling a vsock client, and it does NOT
open the egress door: the guest is driven with LOCAL HTML over the existing
on-box host<->guest parse channel — never a live ``/ingest <url>`` fetch. The
``[guest_parser].enabled=false`` weld and the three egress locks are untouched
(those are #659 go-live locks, not this script's).

Run under Python 3.14 (needs ``socket.AF_HYPERV``; the 3.11 runtime venv lacks
it). With no bridge bound, ``parse_round_trip`` takes the in-process AF_HYPERV
path — guest-side memory is identical to the production 3.14-subprocess bridge,
so this faithfully measures what the guest does on a real ingest.

Read-only on the repo. Writes a JSONL of raw samples + a summary JSON under
``docs/performance/``. Hyper-V cmdlets (Start-VM / Get-VM) require an elevated
shell.

Security: no external network calls. The only sockets opened are AF_HYPERV vsock
to the local guest; the only subprocesses are local PowerShell Hyper-V queries.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import subprocess
import sys
import time
import tomllib
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from launcher.guest_parser_health import make_health_probe, parse_round_trip  # noqa: E402
from launcher.parser_channel_seam import ParserEndpoint  # noqa: E402
from shared.constants import ORCHESTRATOR_VM_ID, ORCHESTRATOR_VM_NAME  # noqa: E402
from shared.ipc.parse_channel import (  # noqa: E402
    PARSE_BODY_MAX_BYTES,
    encode_parse_request,
)

# Sentinel source_url metadata for the measurement parses. Printable ASCII,
# under PARSE_SOURCE_URL_MAX_CHARS. The guest NEVER fetches it (ADR-030 §4) — it
# is extractor-heuristic metadata only.
MEASURE_SOURCE_URL = "blarai://measure-661-vm-rightsizing"


def _ps(command: str, timeout: float = 30.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def vm_mem(vm_name: str) -> tuple[str, int, int]:
    """Return (state, demand_mb, assigned_mb) for *vm_name* via Get-VM.

    MemoryDemand reads 0 until the guest's integration services begin reporting;
    callers treat a 0 during early boot as "not yet reporting", not as truth.
    """
    cmd = (
        f"$v = Get-VM -Name '{vm_name}' -ErrorAction SilentlyContinue; "
        "if ($null -eq $v) { 'NA|0|0' } else { "
        "'{0}|{1}|{2}' -f $v.State, "
        "[int]([math]::Round($v.MemoryDemand/1MB)), "
        "[int]([math]::Round($v.MemoryAssigned/1MB)) }"
    )
    out = _ps(cmd).stdout.strip()
    state, demand, assigned = out.split("|")
    return state, int(demand), int(assigned)


def start_vm(vm_name: str) -> None:
    proc = _ps(f"Start-VM -Name '{vm_name}' -ErrorAction Stop", timeout=120.0)
    if proc.returncode != 0:
        raise RuntimeError(f"Start-VM failed: {proc.stderr.strip()}")


def build_large_html(target_bytes: int) -> bytes:
    """Deterministically build a representative long-form article near *target*.

    Realistic article markup — headings, paragraphs of prose, inline links,
    lists, blockquotes, figures/images — so trafilatura extracts it as clean
    article text. Byte-deterministic (no RNG): re-running yields identical input.
    This is TYPICAL-LARGE at the channel's max body size, NOT an adversarial /
    pathological lxml structure (named as such in the perf record).
    """
    sentences = [
        "Local-first inference keeps every token on the user's own silicon, "
        "which reframes the privacy question from policy to physics.",
        "The parser runs inside a NIC-less guest so hostile page bytes never "
        "touch the host filesystem or the model that answers the user.",
        "Speculative decoding pairs a small draft model with the target model "
        "to raise throughput without changing the sampled distribution.",
        "Dynamic memory lets the hypervisor reclaim idle pages while leaving "
        "headroom for the rare spike a large document parse can produce.",
        "Fail-closed is the default everywhere: an unreachable guest refuses "
        "the ingest rather than silently falling back to host-side parsing.",
        "Extraction strips navigation, comment threads, and paywall teasers, "
        "returning the readable article body and little else of the markup.",
        "A hardware-rooted trust chain measures the boot path so the platform "
        "can prove which code produced the answer the user is reading.",
        "The build journal carries the judgment behind each call, including "
        "the failures, because a sanitised record does not compound over time.",
    ]
    head = (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        "<title>A Representative Long-Form Article for Parser Memory "
        "Measurement</title></head><body><article>"
        "<h1>A Representative Long-Form Article for Parser Memory "
        "Measurement</h1>"
        '<p class="byline">Synthetic content generated for BlarAI #661 — not a '
        "real URL, not adversarial structure.</p>"
    )
    tail = "</article></body></html>"
    sections: list[str] = []
    cur = len(head.encode("utf-8")) + len(tail.encode("utf-8"))
    section = 0
    while True:
        section += 1
        n = len(sentences)
        paras = "".join(
            "<p>"
            + " ".join(sentences[(section + p + k) % n] for k in range(6))
            + f' <a href="https://example.org/ref/{section}-{p}">'
            "related reading</a>.</p>"
            for p in range(4)
        )
        items = "".join(
            f"<li>Point {section}.{j}: {sentences[(section + j) % n][:60]}</li>"
            for j in range(3)
        )
        block = (
            f"<section><h2>Section {section}</h2>{paras}"
            f"<ul>{items}</ul>"
            f"<blockquote>{sentences[section % n]}</blockquote>"
            f'<figure><img src="https://example.org/img/{section}.jpg" '
            f'alt="Figure {section}"><figcaption>Figure {section}.'
            "</figcaption></figure></section>"
        )
        blen = len(block.encode("utf-8"))
        if cur + blen > target_bytes:
            break
        sections.append(block)
        cur += blen
    html = head + "".join(sections) + tail
    return html.encode("utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rest-s", type=float, default=20.0)
    ap.add_argument("--burst-s", type=float, default=60.0)
    ap.add_argument("--settle-s", type=float, default=25.0)
    ap.add_argument("--sample-interval-s", type=float, default=1.5)
    ap.add_argument("--target-bytes", type=int, default=250_000)
    ap.add_argument("--out-tag", default="2026-06-13")
    args = ap.parse_args()

    vm = ORCHESTRATOR_VM_NAME
    cfg = tomllib.loads((REPO / "launcher/config/default.toml").read_text())[
        "guest_parser"
    ]
    port = int(cfg["vsock_port"])
    guid = str(cfg["service_guid"])
    health_timeout_s = float(cfg["health_timeout_s"])  # 120 — cold-boot budget

    # Per-probe / per-parse transport budget. Generous for a ~250 KiB round-trip
    # (a refused connect during boot still returns in ms, so polling stays fast).
    endpoint = ParserEndpoint(
        vm_id=ORCHESTRATOR_VM_ID,
        service_guid=guid,
        vsock_port=port,
        timeout_s=30.0,
    )
    probe = make_health_probe()

    big_html = build_large_html(args.target_bytes)
    assert len(big_html) <= PARSE_BODY_MAX_BYTES, "fixture exceeds channel cap"
    real_html = (
        REPO / "services/cleaner/tests/fixtures/news_quantum.html"
    ).read_bytes()

    out_dir = REPO / "docs/performance"
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = out_dir / f"guest_parser_memory_{args.out_tag}.jsonl"
    json_path = out_dir / f"guest_parser_memory_{args.out_tag}.json"
    jl = jsonl_path.open("w", encoding="utf-8")

    samples: list[dict] = []

    def sample(phase: str, t0: float) -> dict:
        state, demand, assigned = vm_mem(vm)
        rec = {
            "t_s": round(time.monotonic() - t0, 2),
            "phase": phase,
            "state": state,
            "demand_mb": demand,
            "assigned_mb": assigned,
        }
        samples.append(rec)
        jl.write(json.dumps(rec) + "\n")
        jl.flush()
        print(json.dumps(rec), flush=True)
        return rec

    print(f"# big fixture = {len(big_html)} bytes; real fixture = "
          f"{len(real_html)} bytes; cap = {PARSE_BODY_MAX_BYTES}", flush=True)

    t0 = time.monotonic()
    print("# Start-VM (cold boot)…", flush=True)
    start_vm(vm)

    # ── boot: poll the health frame until READY or the 120s cold-boot budget ──
    ready = False
    while time.monotonic() - t0 < health_timeout_s:
        sample("boot", t0)
        try:
            if probe(endpoint):
                ready = True
                break
        except Exception as exc:  # noqa: BLE001 — fail-closed, keep polling
            print(f"# probe raised (continuing): {type(exc).__name__}", flush=True)
        time.sleep(1.0)
    time_to_ready_s = round(time.monotonic() - t0, 2)

    summary: dict = {
        "task": "BlarAI #661 — VM RAM right-sizing (guest-parser footprint)",
        "measured_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "vm": vm,
        "vm_id": ORCHESTRATOR_VM_ID,
        "parser": {"vsock_port": port, "service_guid": guid},
        "fixture": {
            "near_cap_bytes": len(big_html),
            "real_fixture": "services/cleaner/tests/fixtures/news_quantum.html",
            "real_fixture_bytes": len(real_html),
            "channel_cap_bytes": PARSE_BODY_MAX_BYTES,
        },
        "cold_boot": {
            "health_timeout_s": health_timeout_s,
            "time_to_ready_s": time_to_ready_s,
            "ready": ready,
            "covers_boot": ready and time_to_ready_s < health_timeout_s,
        },
        "single_parses": [],
        "burst": {},
        "by_phase": {},
    }

    if not ready:
        print(f"# HEALTH TIMEOUT after {time_to_ready_s}s — parser not READY",
              flush=True)
        json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        jl.close()
        return 2

    print(f"# parser READY in {time_to_ready_s}s", flush=True)

    # ── rest: idle, parser resident ──
    rest_end = time.monotonic() + args.rest_s
    while time.monotonic() < rest_end:
        sample("rest", t0)
        time.sleep(args.sample_interval_s)

    # ── single parses (latency + functional correctness) ──
    for label, html in (("real_small", real_html), ("near_cap", big_html)):
        frames = encode_parse_request(
            request_id=uuid.uuid4().hex, html=html, source_url=MEASURE_SOURCE_URL
        )
        t1 = time.monotonic()
        resp = parse_round_trip(endpoint, frames)
        dt = round(time.monotonic() - t1, 3)
        rec = {
            "label": label,
            "in_bytes": len(html),
            "ok": resp is not None,
            "status": getattr(resp, "status", None),
            "out_text_len": len(getattr(resp, "text", "") or "") if resp else 0,
            "seconds": dt,
        }
        summary["single_parses"].append(rec)
        print("# single_parse " + json.dumps(rec), flush=True)

    # ── burst: sustained near-cap parses; sample on a time cadence ──
    frames_big = encode_parse_request(
        request_id=uuid.uuid4().hex, html=big_html, source_url=MEASURE_SOURCE_URL
    )
    burst_end = time.monotonic() + args.burst_s
    n_ok = n_fail = 0
    first_fail: dict | None = None
    last_sample = 0.0
    while time.monotonic() < burst_end:
        r = parse_round_trip(endpoint, frames_big)
        if r is not None:
            n_ok += 1
        else:
            n_fail += 1
            if first_fail is None:
                first_fail = {"at_parse": n_ok + n_fail}
        if time.monotonic() - last_sample >= args.sample_interval_s:
            sample("burst", t0)
            last_sample = time.monotonic()
    summary["burst"] = {
        "duration_s": args.burst_s,
        "parses_ok": n_ok,
        "parses_fail": n_fail,
        "first_fail": first_fail,
    }
    print("# burst " + json.dumps(summary["burst"]), flush=True)

    # ── settle: parsing stopped; balloon should reclaim toward rest ──
    settle_end = time.monotonic() + args.settle_s
    while time.monotonic() < settle_end:
        sample("settle", t0)
        time.sleep(args.sample_interval_s)

    # ── per-phase rollups ──
    for ph in ("boot", "rest", "burst", "settle"):
        ds = [s["demand_mb"] for s in samples if s["phase"] == ph and s["demand_mb"] > 0]
        a_ = [s["assigned_mb"] for s in samples if s["phase"] == ph]
        if a_:
            summary["by_phase"][ph] = {
                "n": len(a_),
                "demand_mb_min": min(ds) if ds else None,
                "demand_mb_max": max(ds) if ds else None,
                "assigned_mb_min": min(a_),
                "assigned_mb_max": max(a_),
            }

    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    jl.close()
    print("\n=== SUMMARY ===", flush=True)
    print(json.dumps(summary, indent=2), flush=True)
    print(f"\n# wrote {json_path}", flush=True)
    print(f"# wrote {jsonl_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
