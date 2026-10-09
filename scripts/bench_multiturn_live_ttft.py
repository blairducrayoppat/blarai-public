"""Multi-turn time-to-first-token with LIVE history (#1663, gate-review D5).

The price MTP charges is that it requires prefix caching OFF, so every turn of a
conversation re-reads its whole history. The speed benchmark's multi-turn cells
used SCRIPTED assistant replies, which diverge from what a cache holds, so they
cannot show that cost (independent review F6). This script runs one conversation
per arm visit in which every assistant turn is the model's OWN greedy reply, laid
out the way a chat template lays out real turns (history assistant messages carry
no think block; only the final assistant header carries the closed empty one), so
what a prefix cache can reuse is exactly what production would let it reuse.

Six user turns of ~450 tokens each grow the prompt to a few thousand tokens.
Arms (``--arms``): <size>-mtp-off, <size>-mtp-on, <size>-prefix-cache for a size in
phase1_sizes.SIZES (2026.4 interpreter; default 4b) and 14b-ship (either interpreter). Each visit waits for the thermal zone to cool first.
One JSON out, one status line per turn.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import phase1_sizes as sizes  # noqa: E402

SYSTEM = "You are a concise assistant. Answer in one short sentence."
TURNS = 6
EMPTY_THINK = "<think>\n\n</think>\n\n"
_PARA = (
    "The harbour authority published its quarterly figures this week, covering cargo volumes, "
    "berth occupancy, crane downtime and the average time a vessel waits before it is cleared to dock. "
    "Container traffic rose slightly while bulk traffic fell, and the report attributes the difference to "
    "seasonal grain shipments finishing earlier than in previous years. Maintenance on the third crane "
    "was completed ahead of schedule, which reduced downtime, but a storm in the second week closed the "
    "channel for two days and pushed the waiting-time average back up. The authority also noted that the "
    "new scheduling software was used for the first full quarter and that planners reported fewer manual "
    "overrides than expected. "
)


def user_message(k: int) -> str:
    body = (_PARA * 3) + f"Note {k + 1}: "
    asks = ["What rose?", "What fell?", "Why did bulk fall?", "What closed the channel?", "What did planners report?", "What was finished early?"]
    return body + asks[k % len(asks)]


def chatml(history: list[tuple[str, str]], user: str) -> str:
    parts = [f"<|im_start|>system\n{SYSTEM}<|im_end|>\n"]
    for u, a in history:
        parts.append(f"<|im_start|>user\n{u}<|im_end|>\n")
        parts.append(f"<|im_start|>assistant\n{a}<|im_end|>\n")
    parts.append(f"<|im_start|>user\n{user}<|im_end|>\n")
    parts.append(f"<|im_start|>assistant\n{EMPTY_THINK}")
    return "".join(parts)


def strip_think(text: str) -> str:
    return re.sub(r"<think>.*?(?:</think>|$)", "", text, flags=re.DOTALL).strip()


def main() -> int:
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--arms", default="4b-mtp-off,4b-mtp-on,4b-prefix-cache")
    ap.add_argument("--visits", type=int, default=3)
    ap.add_argument("--models-root", default="C:/Users/mrbla/BlarAI")
    sizes.add_model_args(ap)
    ap.add_argument("--model-14b", default=None)
    ap.add_argument("--cold-temp", type=float, required=True)
    ap.add_argument("--cold-max-wait", type=float, default=240.0)
    ap.add_argument("--status-file", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--max-new", type=int, default=48)
    a = ap.parse_args()
    a.status_file, a.out = a.status_file.resolve(), a.out.resolve()
    sizes.resolve_model_args(a)
    a.model_14b = str(Path(a.model_14b or Path(a.models_root) / "models/qwen3-14b/openvino-int4-gpu").resolve())
    os.chdir(a.models_root)

    import bench_qwen35_speed as b
    import openvino
    import openvino_genai
    from sample_system import read_thermal

    arms = [x.strip() for x in a.arms.split(",") if x.strip()]
    rows: list[dict] = []
    visits_meta: list[dict] = []
    with open(a.status_file, "a", encoding="utf-8") as status:
        for visit in range(a.visits):
            order = arms[visit % len(arms):] + arms[: visit % len(arms)]
            for name in order:
                cold = b.wait_for_cold(read_thermal, a.cold_temp, a.cold_max_wait)
                arm = b.load_arm(name, a)
                arm.generate(b._WARMUP_PROMPT, 8)  # discarded
                history: list[tuple[str, str]] = []
                for k in range(TURNS):
                    th0 = read_thermal()
                    user = user_message(k)
                    prompt = chatml(history, user)
                    raw = arm.generate(prompt, a.max_new)
                    reply = strip_think(raw["text"])
                    history.append((user, reply))
                    row = {
                        "arm": name, "visit": visit, "turn": k + 1,
                        "input_tokens": arm.count_tokens(prompt),
                        "ttft_ms": raw.get("ttft_ms"), "tpot_ms": raw.get("tpot_ms"),
                        "generated_tokens": raw.get("generated_tokens"),
                        "reply_sha256": b.sha256_text(reply), "prompt_sha256": b.sha256_text(prompt),
                        "thermal_before": th0, "cold_wait": cold if k == 0 else None,
                        "genai_version": openvino_genai.__version__,
                    }
                    rows.append(row)
                    status.write(json.dumps({"t": time.time(), "arm": name, "visit": visit, "turn": k + 1, "ttft_ms": row["ttft_ms"]}) + chr(10))
                    status.flush()
                visits_meta.append({"arm": name, "visit": visit, "header": arm.header})
                arm = None
                gc.collect()
                time.sleep(5)
        result = {
            "meta": {"started": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "python": sys.executable,
                     "openvino": openvino.__version__, "genai": openvino_genai.__version__,
                     "max_new_tokens": a.max_new, "turns": TURNS, "cold_temp_c": a.cold_temp,
                     "design": "live greedy assistant replies; history assistant messages carry no think block; final header carries the closed empty think block"},
            "visits": visits_meta, "rows": rows,
        }
        a.out.write_text(json.dumps(result, indent=1), encoding="utf-8")
        status.write(json.dumps({"done": True, "exit": 0}) + chr(10))
    return 0


if __name__ == "__main__":
    sys.exit(main())
