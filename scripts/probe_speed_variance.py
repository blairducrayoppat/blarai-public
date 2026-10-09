"""Instrument-variance probe for the speed benchmark (#1663; global rule 1).

Loads ONE engine arm in a fresh process and runs a scripted sequence of cells,
printing/recording the per-generation decode rate, so the variance of the
instrument (and any state effect of an earlier long prompt) is known BEFORE two
arms are compared. Cells are the benchmark's own (``bench_qwen35_speed``), so the
probe measures the same thing the campaign will.

Sequence syntax: comma list of ``cell*count`` e.g. ``pa*10,mt2*10,ao*2,pa*10``.
``mt2`` is multi-turn turn 2, ``ao`` the ~6000-token context, ``pa`` the
Policy-Agent prompt. Generations run with ``max_new_tokens`` fixed per cell and
the model's natural stop, exactly like the campaign.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import phase1_sizes as sizes  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--engine", default="cb-mtp-off")
    ap.add_argument("--size", choices=tuple(sizes.SIZES), default="4b", help="which --model-<size> directory to load")
    sizes.add_model_args(ap)
    ap.add_argument("--models-root", default="C:/Users/mrbla/BlarAI")
    ap.add_argument("--sequence", default="pa*10,mt2*10,ao*2,pa*10")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    out = a.out.resolve()
    model = Path(getattr(a, f"model_{a.size}"))
    import os

    os.chdir(a.models_root)

    from sample_system import read_thermal  # noqa: E402

    import bench_qwen35_speed as b  # noqa: E402 - sibling script, pure helpers + prompt builders
    from evals.cb_pipeline import CBEnginePipeline
    import openvino_genai as g

    pipe = CBEnginePipeline(model, a.engine)
    tok = pipe.get_tokenizer()
    count = lambda t: b._tok_count(tok, t)  # noqa: E731
    pa_prompt, _ = b.build_pa_prompt()
    ao_prompt = b.build_ao_prompt(count)
    mt_prompts = b.build_multiturn_prompts()
    cells = {"pa": (pa_prompt, 16), "ao": (ao_prompt, 128), "mt2": (mt_prompts[1], 48)}

    def gen(prompt: str, max_new: int) -> dict:
        cfg = g.GenerationConfig()
        cfg.max_new_tokens = max_new
        cfg.do_sample = False
        cfg.apply_chat_template = False
        t0 = time.perf_counter()
        text = pipe.generate(prompt, generation_config=cfg)
        wall = (time.perf_counter() - t0) * 1000.0
        st = dict(text.stats)
        return {"wall_ms": round(wall, 1), "ttft_ms": st.get("ttft_ms"), "tpot_ms": st.get("tpot_ms"),
                "gen": st.get("generated_tokens"), "acc": st.get("accepted_tokens"), "drafted": st.get("draft_tokens")}

    gen(b._WARMUP_PROMPT, 8)  # discarded warm-up, as the campaign does
    rows = []
    idx = 0
    for item in a.sequence.split(","):
        if item.startswith("rest"):
            time.sleep(float(item[4:]))
            th = read_thermal()
            rows.append({"i": idx, "cell": item, "thermal": th})
            print(f"{idx:3d} {item} thermal={th}", flush=True)
            idx += 1
            continue
        name, _, n = item.partition("*")
        for _ in range(int(n or 1)):
            prompt, max_new = cells[name]
            th0 = read_thermal()
            r = gen(prompt, max_new)
            r.update({"i": idx, "cell": name, "thermal_before": th0})
            rows.append(r)
            print(f"{idx:3d} {name:4s} tpot={r['tpot_ms']} ttft={r['ttft_ms']} gen={r['gen']} temp={th0.get('temp_c')} lim={th0.get('passive_limit_pct')} thr={th0.get('throttle_reasons')} perf={th0.get('cpu_perf_pct')}", flush=True)
            idx += 1
    out.write_text(json.dumps({"engine": a.engine, "sequence": a.sequence, "rows": rows, "header": pipe.header}, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
