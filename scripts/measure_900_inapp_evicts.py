"""
#900 memory-reclaim @hardware driver — the in-app evict paths (live BlarAI)
===========================================================================
Companion to ``scripts/measure_900_memory_reclaim.py`` (the route-B 14B
headline). This half drives the evict paths that ARE live in the production
config, through the REAL production stack — a second ``TransportGateway``
client speaking mTLS to the live Assistant Orchestrator, exactly as the WinUI
backend does:

  * ``image_gen.sdxl.unload``      — /imagine turns; SDXL evicts in the AO's finally.
  * ``vlm.unload``                 — photo-upload + describe turns; VLM evicts after.
  * ``substrate.embed_cache.unload`` — embedding-cache idle-unload
    (``[substrate].embed_cache_idle_unload_s`` = 900 s), captured by idling
    past the window after the last turn.

The samples are the wired #900 instrumentation's ``MEM_RECLAIM`` lines in
launcher.log — this driver never computes a delta itself. PRECONDITIONS: the
launcher was booted with ``BLARAI_MEM_RECLAIM_PROBE=1`` in its environment,
BlarAI is UP (:5001), and this script runs from the repo root in the runtime
venv AFTER the boot (per-boot certs are re-minted each boot):

  .venv\\Scripts\\python.exe scripts\\measure_900_inapp_evicts.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from shared.perf_env_capture import capture_box_state  # noqa: E402

_CERTS = _REPO_ROOT / "certs"
_LAUNCHER_LOG = (
    Path(os.environ.get("LOCALAPPDATA", "")) / "BlarAI" / "launcher.log"
)
_USERDATA = _REPO_ROOT / "userdata"
_PROBE_PHOTO = "probe900_photo.png"

_RECLAIM_LINE = re.compile(
    r"MEM_RECLAIM op=(?P<op>\S+) in_use_before=(?P<before>-?\d+)MB "
    r"in_use_after=(?P<after>-?\d+)MB reclaimed=(?P<reclaimed>[+-]?\d+)MB "
    r"avail_before=(?P<avail_before>-?\d+)MB avail_after=(?P<avail_after>-?\d+)MB "
    r"proc_rss_delta=(?P<rss_delta>[+-]?\d+)MB(?P<extra>.*)"
)

_TURN_DRAIN_TIMEOUT_S = 420.0  # VLM load ~12-16 s + describe + PGOV; generous.


def _make_probe_photo() -> None:
    """A synthetic probe image (never the operator's personal photos)."""
    from PIL import Image, ImageDraw

    _USERDATA.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (512, 512), (30, 60, 110))
    d = ImageDraw.Draw(img)
    d.ellipse((96, 96, 416, 416), fill=(240, 200, 60), outline=(255, 255, 255), width=6)
    d.rectangle((216, 236, 296, 416), fill=(180, 40, 40))
    img.save(_USERDATA / _PROBE_PHOTO)


def _parse_new_reclaim_lines(offset: int) -> list[dict[str, Any]]:
    if not _LAUNCHER_LOG.exists():
        return []
    data = _LAUNCHER_LOG.read_bytes()[offset:]
    samples: list[dict[str, Any]] = []
    for line in data.decode("utf-8", errors="replace").splitlines():
        m = _RECLAIM_LINE.search(line)
        if m is None:
            continue
        samples.append(
            {
                "op": m.group("op"),
                "in_use_before_mb": float(m.group("before")),
                "in_use_after_mb": float(m.group("after")),
                "reclaimed_mb": float(m.group("reclaimed")),
                "available_before_mb": float(m.group("avail_before")),
                "available_after_mb": float(m.group("avail_after")),
                "proc_rss_delta_mb": float(m.group("rss_delta")),
                "extra": m.group("extra").strip(),
            }
        )
    return samples


async def _drain(gw: Any, sid: str) -> str:
    """Drain one turn's token stream; returns the concatenated text."""
    parts: list[str] = []

    async def _inner() -> None:
        async for tok in gw.stream_tokens(sid):
            if getattr(tok, "text", None):
                parts.append(tok.text)
            if getattr(tok, "final", False):
                return

    await asyncio.wait_for(_inner(), timeout=_TURN_DRAIN_TIMEOUT_S)
    return "".join(parts)


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    from launcher.__main__ import resolve_gateway_port
    from services.ui_gateway.src.transport import TransportGateway

    port = resolve_gateway_port(dev_mode=False, host_mode=True)
    gw = TransportGateway(
        session_store=None,
        dev_mode=False,
        host_mode=True,
        host="127.0.0.1",
        port=port,
        mtls_cert_path=str(_CERTS / "gateway_client.pem"),
        mtls_key_path=str(_CERTS / "gateway_client_key.pem"),
        ca_cert_path=str(_CERTS / "ca.pem"),
    )
    sid = f"probe900-{datetime.now().strftime('%H%M%S')}"
    turns: list[dict[str, Any]] = []

    # Production-mode liveness handshake first (the WinUI boot does the same);
    # logged but non-fatal — the prompt transport opens per-operation anyway.
    try:
        alive = await gw.check_pa_status()
        print(f"[handshake] liveness: {alive}")
    except Exception as exc:  # noqa: BLE001 — diagnostics only
        print(f"[handshake] check_pa_status raised (continuing): {exc}")

    async def _text_turn(prompt: str, label: str) -> None:
        t0 = time.perf_counter()
        await gw.send_prompt(sid, prompt)
        text = await _drain(gw, sid)
        turns.append(
            {
                "label": label,
                "seconds": round(time.perf_counter() - t0, 1),
                "reply_head": text[:160],
            }
        )
        print(f"[turn] {label}: {turns[-1]['seconds']}s — {text[:80]!r}")

    # 1) A plain text turn — exercises the full prompt path and puts the
    #    embedding cache into USE so its idle clock is meaningfully reset.
    await _text_turn("In one sentence, what is a lighthouse?", "text-1")
    await asyncio.sleep(args.settle_seconds)

    # 2) /imagine rounds — each SDXL generate evicts in the AO's finally.
    for i in range(1, args.imagine_rounds + 1):
        t0 = time.perf_counter()
        reply = await gw.handle_imagine_command(
            sid, f"/imagine a small watercolor lighthouse at dusk, study {i}"
        )
        turns.append(
            {
                "label": f"imagine-{i}",
                "seconds": round(time.perf_counter() - t0, 1),
                "reply_head": (reply or "")[:160],
            }
        )
        print(f"[turn] imagine-{i}: {turns[-1]['seconds']}s — {(reply or '')[:80]!r}")
        if reply is None or "unavailable" in (reply or "").lower():
            raise RuntimeError(f"/imagine round {i} did not run: {reply!r}")
        await asyncio.sleep(args.settle_seconds)

    # 3) photo describe rounds — paperclip flow: stash the probe photo, then a
    #    normal prompt drains it into the PROMPT_REQUEST; VLM evicts after.
    for i in range(1, args.describe_rounds + 1):
        gw.load_document(sid, _PROBE_PHOTO)
        await _text_turn(
            "Describe the attached photo in one short sentence.", f"describe-{i}"
        )
        await asyncio.sleep(args.settle_seconds)

    # 4) embed-cache idle-unload: idle past the 900 s window.
    if not args.skip_embed_wait:
        print(f"[idle] waiting {args.embed_idle_wait_s:.0f}s for embed-cache idle-unload…")
        waited = 0.0
        while waited < args.embed_idle_wait_s:
            step = min(60.0, args.embed_idle_wait_s - waited)
            await asyncio.sleep(step)
            waited += step
            print(f"[idle] {waited:.0f}s / {args.embed_idle_wait_s:.0f}s")

    return {"session_id": sid, "turns": turns}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--imagine-rounds", type=int, default=3)
    parser.add_argument("--describe-rounds", type=int, default=3)
    parser.add_argument("--settle-seconds", type=float, default=10.0)
    parser.add_argument("--embed-idle-wait-s", type=float, default=960.0)
    parser.add_argument("--skip-embed-wait", action="store_true")
    args = parser.parse_args()

    if not _LAUNCHER_LOG.exists():
        print(f"REFUSED: launcher.log not found at {_LAUNCHER_LOG} — is BlarAI up?")
        return 1
    _make_probe_photo()
    log_offset = _LAUNCHER_LOG.stat().st_size
    box_state_at_start = capture_box_state()

    drive = asyncio.run(_run(args))

    samples = _parse_new_reclaim_lines(log_offset)
    by_op: dict[str, list[float]] = {}
    for s in samples:
        by_op.setdefault(s["op"], []).append(s["reclaimed_mb"])
    medians = {op: round(statistics.median(v), 1) for op, v in by_op.items()}

    summary: dict[str, Any] = {
        "ticket": "#900",
        "measurement": "memory_reclaim_inapp_evict_paths",
        "route": (
            "live BlarAI (production launcher boot, BLARAI_MEM_RECLAIM_PROBE=1), "
            "driven by a second mTLS TransportGateway client through the real "
            ":5001 prompt/imagine corridors"
        ),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "methodology": (
            f"1 text turn + {args.imagine_rounds} /imagine turns (SDXL evicts in "
            f"the caller's finally) + {args.describe_rounds} photo-describe turns "
            "(VLM evicts after) + idle past [substrate].embed_cache_idle_unload_s "
            f"(900 s); {args.settle_seconds}s settle between turns; samples are "
            "the wired MEM_RECLAIM lines appended to launcher.log during the "
            "session (In-Use = Total − Available, never working sets)."
        ),
        "environment": {
            "box_state_at_start": box_state_at_start,
            "box_state_at_end": capture_box_state(),
        },
        "drive": drive,
        "samples": samples,
        "median_reclaimed_mb_by_op": medians,
        "not_measured": [
            "the 14B mid-life evict via the in-app route (hires_enabled=false in "
            "production — measured separately via the route-B harness, same day)",
            "shared_pipeline.14b.release_gpu_for_exit under a model swap "
            "(no dispatch tonight)",
            "co-resident contention beyond the production-designed SDXL/VLM "
            "residency patterns",
        ],
    }

    out_dir = _REPO_ROOT / "docs" / "performance"
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    out_path = out_dir / f"mem_reclaim_900_inapp_{stamp}.json"
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print()
    print("=== #900 in-app evict paths ===")
    for op, med in medians.items():
        print(f"{op}: median reclaimed {med} MB over {len(by_op[op])} samples")
    missing = {
        "image_gen.sdxl.unload",
        "vlm.unload",
        "substrate.embed_cache.unload",
    } - set(medians)
    if missing:
        print(f"MISSING ops (investigate before recording): {sorted(missing)}")
    print(f"results: {out_path}")
    return 0 if samples else 1


if __name__ == "__main__":
    sys.exit(main())
