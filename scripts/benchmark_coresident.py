"""
Co-Resident Inference Benchmark — what the 14B costs when paired with another model
====================================================================================
On the Arc 140V the GPU shares the 31.323 GB system RAM, so "the cost of keeping a
second model beside the always-resident 14B" has several dimensions, all measured here:

  1. MEMORY FIT  — peak co-resident system-RAM use during a real base-1024^2 generate
     (does it fit under the 31.323 GB ceiling, and with how much headroom). System-
     available RAM is the iGPU memory proxy (OpenVINO/Level-Zero GPU allocations come
     from system RAM and the Windows GPU perf counters under-report them).
  2. THE FULL 14B METRIC SUITE in three states — generation tok/s, pp (prefill) tok/s,
     and TTFT (the SAME metrics as the standalone benchmark, so a pairing's effect on
     each is visible):
       * baseline  : 14B alone
       * idle      : partner RESIDENT but idle (memory occupied, GPU free)
       * contention: partner ACTIVELY generating (both time-share the one GPU).
  3. PARTNER op time — seconds for one base-1024^2 image generate / one VLM describe.

External Intel UT telemetry (vccgt-pwr GPU rail power, ddr-bw memory bandwidth,
hw-igfx-pstate GPU frequency, pkg-pwr, npu-pwr) is captured by wrapping THIS script in
``ut.exe`` and merged into the result JSON post-run.

Partners (loaded via BlarAI's own modules so the footprint is faithful):
  photoreal (SDXL-uncensored), illustration (base SDXL), cartoon (base SDXL + LoRA),
  vlm (Qwen3-VL-8B). The 14B is loaded ONCE (spec-on, production config) per run.
NOT measured: hires-fix (a 1536^2 refine EVICTS the 14B by design, ADR-033 Am.2).

Usage:
  .venv\\Scripts\\python.exe scripts\\benchmark_coresident.py --partners photoreal
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import threading
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import psutil  # noqa: E402

import benchmark_gpu_inference as bench  # noqa: E402
from shared.inference import image_gen, vlm  # noqa: E402
from shared.inference.image_gen import (  # noqa: E402
    ImageGenConfig,
    KIND_TEXT2IMAGE,
    VARIANT_ILLUSTRATION,
    VARIANT_ILLUSTRATION_CARTOON,
    VARIANT_PHOTOREAL_SDXL,
)

MEM_CEILING_GIB = 31.323

_CARTOON_LORA = _REPO_ROOT / "models" / "sdxl-illustration" / "lora" / "DD-vector-v2.safetensors"
_CARTOON_LORA_SHA = "b4c8132f85ab7d75f5789eaf0054153a6011b505719f1253fb7d8837a498fe89"

_GEN_PROMPT = "a detailed landscape with mountains and a lake at sunset, sharp focus"
_GEN_W = _GEN_H = 1024
_GEN_STEPS = 20
_TAX_PROMPT_IDX = (2, 3)  # the two longer prompts (stable rate)


def avail_gib() -> float:
    return psutil.virtual_memory().available / (1024 ** 3)


def used_gib() -> float:
    return MEM_CEILING_GIB - avail_gib()


def measure_14b(engine, n_gen: int = 1, n_pp: int = 2, max_tokens: int = 128) -> dict:
    """The full 14B metric suite over the two longer prompts: generation tok/s,
    TTFT, and prefill pp tok/s (probe pp-v1) — the SAME metrics as the standalone
    benchmark. ``n_pp``=0 skips the prefill probe (warmup). ``max_tokens`` caps
    each generation; use a SMALL cap for contention so a GPU-starved 14B (which
    drops to ~0.5 tok/s while a diffuser runs) stays time-bounded."""
    saved_cfg = bench._GEN_CONFIG
    bench._GEN_CONFIG = bench.GenerationConfig(
        max_new_tokens=max_tokens, temperature=0.0, top_k=0, top_p=1.0, do_sample=False)
    gen_rates: list[float] = []
    ttfts: list[float] = []
    totals: list[float] = []
    try:
        for _ in range(n_gen):
            for i in _TAX_PROMPT_IDX:
                m = bench._measure_one(engine, bench.PROMPTS[i], i)
                if m.error is None and m.token_count > 0:
                    gen_rates.append(m.throughput_tok_per_sec)
                    totals.append(m.latency_total_ms)
                    if m.latency_first_token_ms >= 0:
                        ttfts.append(m.latency_first_token_ms)
    finally:
        bench._GEN_CONFIG = saved_cfg
    pp_med = 0.0
    pp_measured = False
    pp_in = 0.0
    if n_pp > 0:
        pstats = bench.aggregate_prefill(bench.measure_prefill(engine, n_pp))
        pp_med = pstats.median_pp
        pp_measured = pstats.measured
        pp_in = pstats.mean_input_tokens
    return {
        "gen_tps": round(statistics.median(gen_rates), 2) if gen_rates else 0.0,
        "ttft_ms": round(statistics.median(ttfts), 1) if ttfts else -1.0,
        "total_ms": round(statistics.median(totals), 1) if totals else 0.0,
        "pp_tps": round(pp_med, 1) if pp_measured else 0.0,
        "pp_measured": pp_measured,
        "pp_input_tokens": round(pp_in, 0),
        "gen_rates": [round(r, 2) for r in gen_rates],
    }


def _measure_sustained_14b(engine, duration_s: float = 15.0, max_tokens: int = 8) -> dict:
    """14B generation rate under SUSTAINED contention: run generations back-to-back
    for ``duration_s`` while the partner generates CONTINUOUSLY in the caller's bg
    thread, then rate = total_tokens / elapsed. Each generation is capped small so
    the loop re-checks the clock often even when the 14B is starved to ~0.5 tok/s.
    Replaces the single short probe, whose result depended on how many partner
    generations happened to overlap it (the 0.5-vs-7 noise across SDXL pairings)."""
    saved = bench._GEN_CONFIG
    bench._GEN_CONFIG = bench.GenerationConfig(
        max_new_tokens=max_tokens, temperature=0.0, top_k=0, top_p=1.0, do_sample=False)
    toks = 0
    n = 0
    ttfts: list[float] = []
    t0 = time.perf_counter()
    try:
        while (time.perf_counter() - t0) < duration_s:
            m = bench._measure_one(engine, bench.PROMPTS[3], 3)
            if m.error is not None:
                break
            toks += m.token_count
            n += 1
            if m.latency_first_token_ms >= 0:
                ttfts.append(m.latency_first_token_ms)
    finally:
        bench._GEN_CONFIG = saved
    elapsed = time.perf_counter() - t0
    return {
        "gen_tps": round(toks / elapsed, 2) if elapsed > 0 else 0.0,
        "tokens": toks, "elapsed_s": round(elapsed, 1), "n_14b_gens": n,
        "ttft_ms": round(statistics.median(ttfts), 1) if ttfts else -1.0,
        "pp_tps": 0.0, "pp_measured": False,
        "method": "sustained 15s: 14B back-to-back during continuous partner generation",
    }


def _fmt(d: dict) -> str:
    return (f"gen {d['gen_tps']:.1f} tok/s | pp {d['pp_tps']:.0f} | "
            f"TTFT {bench._fmt_ms(d['ttft_ms'])}ms")


def _spawn_mem_sampler(stop_evt: threading.Event, out: list, interval: float = 0.4):
    """Daemon thread recording the MIN system-available RAM (= peak used) into
    ``out[0]`` until ``stop_evt`` is set. A PLAIN function — NOT a Thread subclass
    (assigning self._stop there shadows Thread._stop(), which join() calls)."""
    def _run() -> None:
        while not stop_evt.is_set():
            out[0] = min(out[0], avail_gib())
            time.sleep(interval)
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t


# --------------------------------------------------------------------------
# Partner load / generate adapters (BlarAI's own modules — faithful footprint)
# --------------------------------------------------------------------------


def _configure_sdxl(model_dir: str, variant: str, lora: Path | None) -> None:
    image_gen.configure(ImageGenConfig(
        enabled=True,
        model_dir=_REPO_ROOT / model_dir,
        weight_manifest=None,
        require_signed_manifest=False,
        model_variant=variant,
        steps=_GEN_STEPS,
        hires_enabled=False,
        lora_adapter_path=lora,
        lora_adapter_sha256=(_CARTOON_LORA_SHA if lora is not None else ""),
    ))


_SDXL = {
    "photoreal": {"model_dir": "models/sdxl-uncensored/openvino-int8-gpu",
                  "variant": VARIANT_PHOTOREAL_SDXL, "lora": None},
    "illustration": {"model_dir": "models/sdxl-illustration/openvino-int8-gpu",
                     "variant": VARIANT_ILLUSTRATION, "lora": None},
    "cartoon": {"model_dir": "models/sdxl-illustration/openvino-int8-gpu",
                "variant": VARIANT_ILLUSTRATION_CARTOON,
                "lora": (_CARTOON_LORA if _CARTOON_LORA.exists() else None)},
}
_ALL_PARTNERS = ["photoreal", "illustration", "cartoon", "vlm"]


def _load_partner(name: str) -> dict:
    if name == "vlm":
        if not vlm.is_available():
            return {"loaded": False, "why": f"vlm.is_available() False ({vlm.VLM_MODEL_DIR})"}
        pipe = vlm._get_pipe()
        return {"loaded": pipe is not None, "why": "" if pipe else "vlm _get_pipe None"}
    spec = _SDXL[name]
    _configure_sdxl(spec["model_dir"], spec["variant"], spec["lora"])
    if not image_gen.is_available():
        return {"loaded": False, "why": f"image_gen.is_available() False ({spec['model_dir']})"}
    pipe = image_gen._get_pipe(KIND_TEXT2IMAGE)
    return {"loaded": pipe is not None, "why": "" if pipe else "image_gen _get_pipe None"}


def _partner_generate_once(name: str, test_image: Path) -> bool:
    if name == "vlm":
        return vlm.describe_image(str(test_image), max_new_tokens=128) is not None
    png = image_gen.generate_text2image(_GEN_PROMPT, width=_GEN_W, height=_GEN_H, steps=_GEN_STEPS)
    return png is not None


def _unload_partner(name: str) -> None:
    (vlm.unload if name == "vlm" else image_gen.unload)()


def _make_test_image(path: Path) -> None:
    try:
        import numpy as np
        from PIL import Image
        h, w = 1024, 1024
        y = np.linspace(0, 255, h, dtype=np.uint8)[:, None]
        x = np.linspace(0, 255, w, dtype=np.uint8)[None, :]
        arr = np.stack([np.broadcast_to(y, (h, w)), np.broadcast_to(x, (h, w)),
                        np.full((h, w), 128, np.uint8)], axis=-1)
        Image.fromarray(arr, "RGB").save(path)
    except Exception as exc:  # noqa: BLE001
        print(f"  [WARN] test image build failed: {exc}")


def measure_partner(name: str, engine, baseline: dict, test_image: Path) -> dict:
    print(f"\n{'=' * 68}\n  PARTNER: {name}\n{'=' * 68}")
    rec: dict = {"partner": name, "phases": {}}
    base_gen = baseline["gen_tps"]

    avail_before = avail_gib()
    print(f"  avail before partner load : {avail_before:.2f} GiB (14B resident; used {used_gib():.2f})")

    _t_load = time.time()
    t0 = time.perf_counter()
    status = _load_partner(name)
    rec["loaded"] = status["loaded"]
    rec["load_s"] = round(time.perf_counter() - t0, 1)
    rec["phases"]["partner_load"] = [round(_t_load, 3), round(time.time(), 3)]
    if not status["loaded"]:
        rec["error"] = status["why"]
        print(f"  [LOAD FAILED] {status['why']}")
        return rec
    avail_idle = avail_gib()
    rec["partner_resident_gib"] = round(avail_before - avail_idle, 2)
    rec["used_with_partner_idle_gib"] = round(used_gib(), 2)
    print(f"  partner loaded in {rec['load_s']}s | partner resident "
          f"+{rec['partner_resident_gib']:.2f} GiB | used {rec['used_with_partner_idle_gib']:.2f} GiB")

    # 14B full suite — partner resident-idle (phase-timestamped for per-phase power)
    rec["phases"]["idle"] = [round(time.time(), 3), None]
    rec["idle_14b"] = measure_14b(engine, n_gen=1, n_pp=2)
    rec["phases"]["idle"][1] = round(time.time(), 3)
    print(f"  14B partner-idle : {_fmt(rec['idle_14b'])}  (baseline gen {base_gen:.1f})")

    # partner's own op time (one op, 14B resident-idle)
    rec["phases"]["partner_op"] = [round(time.time(), 3), None]
    t0 = time.perf_counter()
    ok = _partner_generate_once(name, test_image)
    rec["partner_op_s"] = round(time.perf_counter() - t0, 2) if ok else None
    rec["phases"]["partner_op"][1] = round(time.time(), 3)
    print(f"  partner op time (1 op)    : {rec['partner_op_s']}s (ok={ok})")

    # contention: partner generating CONTINUOUSLY while the 14B runs back-to-back
    # for a fixed 15s window (sustained — kills the overlap-timing noise).
    stop = threading.Event()
    errs: list[str] = []
    n_gens = [0]

    def _loop() -> None:
        while not stop.is_set():
            ok2 = False
            try:
                ok2 = _partner_generate_once(name, test_image)
            except Exception as exc:  # noqa: BLE001
                errs.append(f"{type(exc).__name__}: {exc}")
            if not ok2:
                errs.append("partner op returned None/failed")
                break
            n_gens[0] += 1

    sample_stop = threading.Event()
    mem_min = [avail_gib()]
    th = threading.Thread(target=_loop, daemon=True)
    print("  [CONTENTION] partner generating continuously; 14B back-to-back for 15s ...")
    sampler_th = _spawn_mem_sampler(sample_stop, mem_min)
    th.start()
    time.sleep(3.0)  # let the partner get mid-generation before we measure
    rec["phases"]["contention"] = [round(time.time(), 3), None]
    rec["contention_14b"] = _measure_sustained_14b(engine, duration_s=15.0)
    rec["phases"]["contention"][1] = round(time.time(), 3)
    stop.set()
    th.join(timeout=180.0)
    sample_stop.set()
    sampler_th.join(timeout=2.0)
    min_avail = min(mem_min[0], avail_gib())
    rec["partner_gens_during"] = n_gens[0]
    rec["peak_used_gib"] = round(MEM_CEILING_GIB - min_avail, 2)
    rec["headroom_gib"] = round(min_avail, 2)
    rec["fits"] = bool(min_avail > 0.5)
    rec["contention_errors"] = errs[:3]
    cont_gen = rec["contention_14b"]["gen_tps"]
    print(f"  14B contention   : {_fmt(rec['contention_14b'])}  "
          f"({(cont_gen / base_gen * 100) if base_gen else 0:.0f}% of baseline gen)")
    print(f"  peak co-resident used     : {rec['peak_used_gib']:.2f} GiB "
          f"(headroom {rec['headroom_gib']:.2f}; fits={rec['fits']}; partner gens {n_gens[0]})"
          + (f" | errs {errs[:2]}" if errs else ""))

    _unload_partner(name)
    import gc
    gc.collect()
    time.sleep(1.0)
    rec["avail_after_unload_gib"] = round(avail_gib(), 2)
    return rec


def main() -> int:
    parser = argparse.ArgumentParser(description=(
        "Co-resident benchmark: the 14B's memory + full metric-suite cost (gen/pp/TTFT) "
        "when paired with each image-gen model and the VLM, on the Arc 140V."))
    parser.add_argument("--partners", nargs="*", default=_ALL_PARTNERS,
                        choices=_ALL_PARTNERS)
    parser.add_argument("--out-tag", default="", help="extra tag in the output filename")
    args = parser.parse_args()

    timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    test_image = _REPO_ROOT / "docs" / "performance" / "_coresident_vlm_probe.png"
    if "vlm" in args.partners:
        _make_test_image(test_image)

    print("=" * 68)
    print("  BlarAI Co-Resident Benchmark — 14B + {image-gen | VLM} on the Arc 140V")
    print(f"  Timestamp     : {timestamp}")
    print(f"  OpenVINO      : {bench._OV_VERSION}")
    print(f"  Mem ceiling   : {MEM_CEILING_GIB} GiB | Partners: {args.partners}")
    print(f"  avail (idle box): {avail_gib():.2f} GiB")
    print("=" * 68)

    print("\n  [14B] loading Qwen3-14B INT4 spec-on ...")
    avail_pre_14b = avail_gib()
    engine = bench.OrchestratorGPUInference(
        model_dir=str(_REPO_ROOT / "models" / "qwen3-14b" / "openvino-int4-gpu"),
        device="GPU",
        draft_model_dir=str(_REPO_ROOT / "models" / "qwen3-0.6b-pruned-6l" / "openvino-int8-gpu"),
        speculative_decoding_enabled=True,
        enable_prefix_caching=True,
    )
    t0 = time.perf_counter()
    if not engine.load_model():
        print("  [FATAL] 14B failed to load.")
        return 1
    load_s = time.perf_counter() - t0
    resident_14b = avail_pre_14b - avail_gib()
    spec_active = bool(getattr(engine, "speculative_decoding_active", False))
    print(f"  [14B] loaded in {load_s:.1f}s | spec_active={spec_active} "
          f"| 14B resident ~{resident_14b:.2f} GiB | used {used_gib():.2f} GiB")

    print("  [14B] warmup ...")
    measure_14b(engine, n_gen=1, n_pp=0)
    _t_base = time.time()
    baseline = measure_14b(engine, n_gen=2, n_pp=2)
    baseline_phase = [round(_t_base, 3), round(time.time(), 3)]
    print(f"  [14B] baseline alone: {_fmt(baseline)} (~{baseline['pp_input_tokens']:.0f} pp input tok)")

    results = []
    for name in args.partners:
        try:
            results.append(measure_partner(name, engine, baseline, test_image))
        except Exception as exc:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            print(f"  [PARTNER {name} ERROR] {type(exc).__name__}: {exc}")
            results.append({"partner": name, "error": f"{type(exc).__name__}: {exc}"})
        try:
            _unload_partner(name)
        except Exception:  # noqa: BLE001
            pass

    engine.unload()

    print(f"\n{'=' * 68}\n  SUMMARY — 14B baseline {_fmt(baseline)}; ceiling {MEM_CEILING_GIB} GiB"
          f"\n{'=' * 68}")
    print(f"  14B resident alone ~{resident_14b:.2f} GiB, load {load_s:.0f}s, spec_active={spec_active}")
    print(f"  {'partner':<13}{'resident':>9}{'peakUsed':>9}{'headroom':>9}{'fits':>6}"
          f"{'gen idle':>9}{'gen cont':>9}{'pp idle':>8}")
    for r in results:
        if "partner_resident_gib" not in r:
            print(f"  {r['partner']:<13}  ERROR: {r.get('error')}")
            continue
        i = r.get("idle_14b", {})
        c = r.get("contention_14b", {})
        print(f"  {r['partner']:<13}{r.get('partner_resident_gib',0):>8.2f}G"
              f"{r.get('peak_used_gib',0):>8.2f}G{r.get('headroom_gib',0):>8.2f}G"
              f"{str(r.get('fits','?')):>6}{i.get('gen_tps',0):>8.1f}{c.get('gen_tps',0):>9.1f}"
              f"{i.get('pp_tps',0):>8.0f}")

    out = {
        "benchmark": "coresident_14b_pairings",
        "timestamp": timestamp,
        "hardware": {"cpu": "Intel Core Ultra 7 258V (Lunar Lake)",
                     "gpu": "Intel Arc 140V (Xe2, iGPU, shared LPDDR5X)",
                     "mem_ceiling_gib": MEM_CEILING_GIB,
                     "gpu_driver": "32.0.101.8826"},
        "openvino_version": bench._OV_VERSION,
        "method": ("14B loaded once (spec-on, prod config); rate probes capped at 128 new "
                   "tokens over prompts P2+P3; pp probe pp-v1. Per partner: full 14B suite "
                   "(gen tok/s, pp tok/s, TTFT) at baseline/partner-idle/contention; peak "
                   "co-resident system-RAM during a base-1024^2 generate (avail = iGPU mem "
                   "proxy); partner op time. hires NOT tested (evicts the 14B by design). "
                   "Intel UT telemetry (vccgt-pwr/ddr-bw/igfx-pstate/pkg-pwr/npu-pwr) merged "
                   "post-run from the ut.exe wrapper."),
        "14b_baseline": {"resident_gib": round(resident_14b, 2), "load_s": round(load_s, 1),
                         "spec_active": spec_active, **baseline},
        "baseline_phase": baseline_phase,
        "partners": results,
    }
    out_dir = _REPO_ROOT / "docs" / "performance"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts_file = timestamp.replace(":", "-").replace("T", "_")
    tag = (args.out_tag + "_") if args.out_tag else ""
    out_path = out_dir / f"benchmark_coresident_{tag}{ts_file}.json"
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\n[SAVE] {out_path}")
    try:
        test_image.unlink(missing_ok=True)
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
