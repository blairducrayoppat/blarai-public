"""
OVMS HTTP Inference Benchmark — Qwen3-Coder-30B-A3B (served as ``coder-30b``)
============================================================================
Repeatable inference-performance benchmark for the coding fleet's 30B MoE model
as served by OpenVINO Model Server (OVMS) on the Arc 140V. Measures the SAME
three metrics as ``scripts/benchmark_gpu_inference.py`` so the 30B is directly
comparable to the in-process 14B / 8B numbers in PERFORMANCE_LOG.md:

  * generation throughput (tok/s)  = completion_tokens / total_latency
  * TTFT (time-to-first-token, ms) = time from request send to first streamed token
  * prefill pp (tok/s)             = prompt_tokens / prefill_time  (== llama-bench pp512)

The 30B is served by the operator's coding fleet via ``start-llm.ps1 -Model
coder-30b -Force`` on the OpenAI-compatible endpoint http://127.0.0.1:8000/v3.
Bring it up FIRST (the 30B and the 14B cannot co-reside in 31.3 GB), then run
this. The endpoint is LOOPBACK ONLY (127.0.0.1) — no network egress; this is a
dev/benchmark tool (in ``scripts/``), NOT BlarAI runtime code, so the urllib HTTP
client the runtime air-gap forbids is fine here against a local socket.

OVMS serves coder-30b with ``--enable_prefix_caching true``, so the prefill probe
prepends a unique per-run prefix (identical method to the GPU bench) — without it
the cache would serve runs 2..N and report a falsely-huge pp.

Usage (from repo root, with OVMS already serving coder-30b on :8000):
  .venv\\Scripts\\python.exe scripts\\benchmark_ovms_http.py
  .venv\\Scripts\\python.exe scripts\\benchmark_ovms_http.py --runs 5 --warmup 2 --run-cooldown 30
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Fixed prompt set — MUST stay byte-identical to scripts/benchmark_gpu_inference.py
# PROMPT_SET v1, so the OVMS 30B numbers are comparable to the in-process 14B/8B
# numbers in the same report. (Duplicated, not imported, to keep this bench free
# of the heavy OpenVINO/gpu_inference import chain — it only needs urllib.)
# ---------------------------------------------------------------------------
PROMPT_SET_VERSION: str = "v1"

PROMPTS: list[str] = [
    "What is the capital city of France?",
    "How many bytes are in one kilobyte?",
    "Explain what a transformer neural network is in plain language.",
    "What is quantization in the context of machine learning models, "
    "and why does it help with inference speed?",
]

# ---------------------------------------------------------------------------
# Prefill (prompt-processing) probe — byte-identical to benchmark_gpu_inference.py
# pp-v1. pp = prompt_tokens / prefill_time, comparable to llama-bench pp512.
# ---------------------------------------------------------------------------
PREFILL_PROBE_VERSION: str = "pp-v1"

_PREFILL_PROBE: str = (
    "This is a fixed, version-controlled prefill probe used to measure the "
    "prompt-processing throughput of a local language model on integrated "
    "graphics hardware. Prompt processing, sometimes called prefill, is the "
    "phase in which the model reads and encodes every token of the input "
    "prompt before it begins to generate a single new token. On a memory "
    "bandwidth limited device such as an integrated graphics processor that "
    "shares system memory with the host, the prefill phase behaves very "
    "differently from the token generation phase. Prefill is compute bound and "
    "highly parallel, because the model can process all of the prompt tokens "
    "together in large batched matrix multiplications, whereas generation is "
    "memory bound and sequential, because each new token depends on the one "
    "produced before it. For this reason the two phases are reported as two "
    "separate numbers in most benchmarking tools, one for prompt processing "
    "throughput and one for generation throughput, and they can differ by more "
    "than an order of magnitude on the same hardware. The purpose of this "
    "passage is simply to provide a stable and reasonably long block of "
    "natural language text so that the prefill measurement reflects a "
    "realistic prompt length rather than a trivial one. A trivial prompt of "
    "only a handful of tokens is dominated by fixed dispatch overhead and does "
    "not reveal the true sustained prefill rate of the device. By holding the "
    "wording of this passage constant across every run and every release, the "
    "benchmark keeps its prompt processing numbers comparable over time, in "
    "the same way that holding the generation prompts constant keeps the "
    "generation numbers comparable. The text deliberately avoids unusual "
    "symbols, code, or formatting so that the token count remains stable "
    "across tokenizer revisions. When this probe is run through the production "
    "generation path, the model first encodes all of these tokens during "
    "prefill, then produces exactly one new token, so the measured latency "
    "closely approximates the pure prefill time. Dividing the number of input "
    "tokens by that time yields the prompt processing throughput, expressed in "
    "tokens per second, which can then be compared directly against the "
    "community reported prefill figures for the same class of integrated "
    "graphics hardware."
)

DEFAULT_ENDPOINT: str = "http://127.0.0.1:8000/v3/chat/completions"
DEFAULT_MODELS_URL: str = "http://127.0.0.1:8000/v3/models"
DEFAULT_MODEL_ID: str = "coder-30b"
DEFAULT_MODEL_NAME: str = "Qwen3-Coder-30B-A3B"


# ---------------------------------------------------------------------------
# Statistics helpers (mirror benchmark_gpu_inference.py — also unit-tested)
# ---------------------------------------------------------------------------


def compute_mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def compute_median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0


def compute_p95(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    rank = math.ceil(0.95 * len(s))
    rank = max(1, min(rank, len(s)))
    return s[rank - 1]


def tokens_per_sec(token_count: int, latency_total_ms: float) -> float:
    if latency_total_ms <= 0:
        return 0.0
    return token_count / (latency_total_ms / 1000.0)


def prefill_tokens_per_sec(num_input_tokens: int, prefill_ms: float) -> float:
    """pp = input_tokens / prefill_seconds (== llama-bench pp512). 0.0 guard."""
    if prefill_ms <= 0 or num_input_tokens <= 0:
        return 0.0
    return num_input_tokens / (prefill_ms / 1000.0)


def _fmt_ms(value: float) -> str:
    return "n/a" if value < 0 else f"{value:.0f}"


# ---------------------------------------------------------------------------
# Per-run metrics + aggregation (mirror the GPU bench shapes)
# ---------------------------------------------------------------------------


@dataclass
class SingleRunMetrics:
    prompt_index: int
    token_count: int
    latency_first_token_ms: float
    latency_total_ms: float
    throughput_tok_per_sec: float
    error: str | None


@dataclass
class PrefillRunMetrics:
    input_tokens: int
    prefill_ms: float
    prefill_tok_per_sec: float
    error: str | None


@dataclass
class AggregateStats:
    mean_tps: float
    median_tps: float
    p95_tps: float
    mean_ttft_ms: float
    median_ttft_ms: float
    p95_ttft_ms: float
    mean_total_ms: float
    median_total_ms: float
    p95_total_ms: float
    total_runs: int
    error_runs: int


@dataclass
class PrefillStats:
    mean_pp: float
    median_pp: float
    p95_pp: float
    mean_input_tokens: float
    total_runs: int
    error_runs: int
    measured: bool


def aggregate(runs: list[SingleRunMetrics]) -> AggregateStats:
    good = [r for r in runs if r.error is None]
    tps_vals = [r.throughput_tok_per_sec for r in good]
    ttft_vals = [r.latency_first_token_ms for r in good if r.latency_first_token_ms >= 0]
    total_vals = [r.latency_total_ms for r in good]
    ttft_measured = bool(ttft_vals)
    return AggregateStats(
        mean_tps=compute_mean(tps_vals),
        median_tps=compute_median(tps_vals),
        p95_tps=compute_p95(tps_vals),
        mean_ttft_ms=compute_mean(ttft_vals) if ttft_measured else -1.0,
        median_ttft_ms=compute_median(ttft_vals) if ttft_measured else -1.0,
        p95_ttft_ms=compute_p95(ttft_vals) if ttft_measured else -1.0,
        mean_total_ms=compute_mean(total_vals),
        median_total_ms=compute_median(total_vals),
        p95_total_ms=compute_p95(total_vals),
        total_runs=len(runs),
        error_runs=len(runs) - len(good),
    )


def aggregate_prefill(runs: list[PrefillRunMetrics]) -> PrefillStats:
    good = [r for r in runs if r.error is None and r.input_tokens > 0 and r.prefill_ms > 0]
    pp_vals = [r.prefill_tok_per_sec for r in good]
    tok_vals = [float(r.input_tokens) for r in good]
    return PrefillStats(
        mean_pp=compute_mean(pp_vals),
        median_pp=compute_median(pp_vals),
        p95_pp=compute_p95(pp_vals),
        mean_input_tokens=compute_mean(tok_vals),
        total_runs=len(runs),
        error_runs=len(runs) - len(good),
        measured=bool(good),
    )


# ---------------------------------------------------------------------------
# OVMS OpenAI-compatible HTTP calls (loopback only)
# ---------------------------------------------------------------------------


def _post_json(url: str, body: dict, timeout: float):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 — loopback only


def chat_stream(
    endpoint: str, model: str, prompt: str, max_tokens: int, timeout: float
) -> dict:
    """Streaming chat completion. Returns timing + token counts.

    TTFT = time from send to first streamed content delta. total = time to the
    last content delta. completion_tokens from the terminal usage chunk
    (stream_options.include_usage); falls back to counting content deltas.
    """
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    t0 = time.perf_counter()
    first_t: float | None = None
    last_t = t0
    n_chunks = 0
    usage: dict | None = None
    parts: list[str] = []
    try:
        with _post_json(endpoint, body, timeout) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                payload = line[len("data:"):].strip()
                if payload == "[DONE]":
                    break
                try:
                    obj = json.loads(payload)
                except ValueError:
                    continue
                if obj.get("usage"):
                    usage = obj["usage"]
                for ch in obj.get("choices", []) or []:
                    content = (ch.get("delta") or {}).get("content")
                    if content:
                        now = time.perf_counter()
                        if first_t is None:
                            first_t = now
                        last_t = now
                        n_chunks += 1
                        parts.append(content)
    except (urllib.error.URLError, OSError) as e:
        return {"error": f"http: {e}"}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}
    ttft_ms = (first_t - t0) * 1000.0 if first_t is not None else -1.0
    total_ms = (last_t - t0) * 1000.0
    comp = (usage or {}).get("completion_tokens")
    if comp is None:
        comp = n_chunks
    return {
        "ttft_ms": ttft_ms,
        "total_ms": total_ms,
        "completion_tokens": int(comp),
        "prompt_tokens": (usage or {}).get("prompt_tokens"),
        "usage_present": usage is not None,
        "error": None,
    }


def chat_nonstream(
    endpoint: str, model: str, prompt: str, max_tokens: int, timeout: float
) -> dict:
    """Non-streaming chat completion — reliable ``usage`` (prompt_tokens). Used for
    the prefill probe (max_tokens=1 => total latency ~= prefill time)."""
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "stream": False,
    }
    t0 = time.perf_counter()
    try:
        with _post_json(endpoint, body, timeout) as resp:
            obj = json.loads(resp.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError) as e:
        return {"error": f"http: {e}"}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}
    total_ms = (time.perf_counter() - t0) * 1000.0
    usage = obj.get("usage") or {}
    return {
        "total_ms": total_ms,
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "error": None,
    }


def measure_generation(
    endpoint: str, model: str, num_runs: int, max_tokens: int,
    timeout: float, run_cooldown: int = 0,
) -> list[SingleRunMetrics]:
    runs: list[SingleRunMetrics] = []
    for run_idx in range(num_runs):
        if run_idx > 0 and run_cooldown > 0:
            print(f"    [RUN-COOLDOWN] idling {run_cooldown}s ...")
            time.sleep(run_cooldown)
        for p_idx, prompt in enumerate(PROMPTS):
            r = chat_stream(endpoint, model, prompt, max_tokens, timeout)
            if r.get("error"):
                runs.append(SingleRunMetrics(p_idx, 0, 0.0, 0.0, 0.0, r["error"]))
                print(f"    run {run_idx + 1}/{num_runs}, prompt {p_idx}: ERROR {r['error']}")
                continue
            tps = tokens_per_sec(r["completion_tokens"], r["total_ms"])
            runs.append(SingleRunMetrics(
                p_idx, r["completion_tokens"], r["ttft_ms"], r["total_ms"], tps, None))
            print(
                f"    run {run_idx + 1}/{num_runs}, prompt {p_idx}: "
                f"{r['completion_tokens']} tok | tps={tps:.1f} | "
                f"ttft={_fmt_ms(r['ttft_ms'])}ms | total={r['total_ms']:.0f}ms"
            )
    return runs


def measure_prefill(
    endpoint: str, model: str, num_runs: int, timeout: float, run_cooldown: int = 0,
) -> list[PrefillRunMetrics]:
    """pp probe: non-streaming max_tokens=1 over the fixed probe with a unique
    per-run prefix (OVMS prefix-caching is ON, so the prefix forces a cold
    prefill). prefill_ms ~= total latency; pp = prompt_tokens / prefill_s."""
    runs: list[PrefillRunMetrics] = []
    for i in range(num_runs):
        if i > 0 and run_cooldown > 0:
            time.sleep(run_cooldown)
        probe = f"(prefill probe, iteration {i}) {_PREFILL_PROBE}"
        r = chat_nonstream(endpoint, model, probe, 1, timeout)
        if r.get("error"):
            runs.append(PrefillRunMetrics(-1, 0.0, 0.0, r["error"]))
            continue
        n_in = r.get("prompt_tokens")
        if n_in is None:
            runs.append(PrefillRunMetrics(-1, r["total_ms"], 0.0, "no prompt_tokens in usage"))
            continue
        pp = prefill_tokens_per_sec(int(n_in), r["total_ms"])
        runs.append(PrefillRunMetrics(int(n_in), r["total_ms"], pp, None))
    return runs


# ---------------------------------------------------------------------------
# Connectivity / model presence
# ---------------------------------------------------------------------------


def served_model_ids(models_url: str, timeout: float = 5.0) -> list[str]:
    """GET /v3/models -> the list of served model ids ([] on any error)."""
    try:
        req = urllib.request.Request(models_url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — loopback
            obj = json.loads(resp.read().decode("utf-8", "replace"))
        return [str(m.get("id")) for m in obj.get("data", []) if m.get("id")]
    except Exception:  # noqa: BLE001
        return []


# ---------------------------------------------------------------------------
# Markdown entry (same table shape as the GPU bench)
# ---------------------------------------------------------------------------


def format_markdown_entry(
    timestamp: str, config_stamp: dict, stats: AggregateStats, prefill: PrefillStats,
    num_runs: int, num_warmup: int,
) -> str:
    model_name = str(config_stamp.get("model_name", DEFAULT_MODEL_NAME))
    served = str(config_stamp.get("served_model_id", DEFAULT_MODEL_ID))
    pp_rows: list[str] = []
    pp_note = ""
    if prefill.measured:
        pp_rows = [f"| Prefill pp (tok/s) | {prefill.mean_pp:.1f} | "
                   f"{prefill.median_pp:.1f} | {prefill.p95_pp:.1f} |"]
        pp_note = (
            f"*Prefill (pp) measured over ~{prefill.mean_input_tokens:.0f} server-counted "
            f"prompt tokens via a max_tokens=1 completion on probe {PREFILL_PROBE_VERSION} "
            f"(unique per-run prefix defeats OVMS prefix-caching); pp = prompt_tokens / "
            f"prefill_time, comparable to llama-bench pp512.* "
        )
    lines = [
        f"### {timestamp[:10]} — {model_name} (OVMS, Arc 140V)",
        "",
        f"**Date:** {timestamp[:10]}  ",
        f"**Benchmark script:** `scripts/benchmark_ovms_http.py` (prompt-set "
        f"{PROMPT_SET_VERSION})  ",
        f"**Runs:** {num_runs} measured + {num_warmup} warmup  ",
        "",
        "#### Config stamp",
        "",
        "| Field | Value |",
        "|-------|-------|",
        f"| Model | `{model_name}` (served id `{served}`) |",
        f"| Server | OVMS {config_stamp.get('ovms_version', '')} |",
        f"| Endpoint | {config_stamp.get('endpoint', '')} |",
        f"| Device | {config_stamp.get('device', 'GPU')} |",
        f"| OVMS flags | {config_stamp.get('ovms_flags', '')} |",
        f"| Driver version | {config_stamp.get('driver_version', '')} |",
        "",
        "#### Results",
        "",
        "| Metric | mean | median | P95 |",
        "|--------|------|--------|-----|",
        f"| Throughput (tok/s) | {stats.mean_tps:.1f} | {stats.median_tps:.1f} | "
        f"{stats.p95_tps:.1f} |",
        *pp_rows,
        f"| TTFT (ms) | {_fmt_ms(stats.mean_ttft_ms)} | {_fmt_ms(stats.median_ttft_ms)} | "
        f"{_fmt_ms(stats.p95_ttft_ms)} |",
        f"| Total latency (ms) | {stats.mean_total_ms:.0f} | {stats.median_total_ms:.0f} | "
        f"{stats.p95_total_ms:.0f} |",
        "",
        f"Runs: {stats.total_runs - stats.error_runs} ok, {stats.error_runs} errors",
        "",
        f"**Notes:** {pp_note}*(add any observations here)*",
        "",
        "---",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="OVMS HTTP inference benchmark — coder-30b (Qwen3-Coder-30B-A3B) "
        "on the Arc 140V. gen tok/s + TTFT + pp, comparable to benchmark_gpu_inference.py."
    )
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--models-url", default=DEFAULT_MODELS_URL)
    parser.add_argument("--model-id", default=DEFAULT_MODEL_ID,
                        help="Served model id (OVMS --model_name). Default: coder-30b.")
    parser.add_argument("--model-name", default=DEFAULT_MODEL_NAME,
                        help="Human model name for the record. Default: Qwen3-Coder-30B-A3B.")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--max-tokens", type=int, default=256)
    parser.add_argument("--run-cooldown", type=int, default=0,
                        help="Seconds idle between measured runs (thermal). Default 0.")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--prefill", default="on", choices=["on", "off"])
    parser.add_argument("--ovms-version", default="")
    parser.add_argument("--ovms-flags", default="")
    parser.add_argument("--driver-version", default="")
    args = parser.parse_args()

    timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    measure_pp = args.prefill == "on"

    print("=" * 68)
    print("  BlarAI OVMS HTTP Inference Benchmark")
    print(f"  Timestamp     : {timestamp}")
    print(f"  Endpoint      : {args.endpoint}")
    print(f"  Model id      : {args.model_id}")
    print(f"  Model name    : {args.model_name}")
    print(f"  Runs / warmup : {args.runs} / {args.warmup}")
    print(f"  Run cooldown  : {args.run_cooldown}s")
    print(f"  Max tokens    : {args.max_tokens}")
    print("=" * 68)

    # Connectivity pre-flight — fail loudly if OVMS is not serving the model.
    ids = served_model_ids(args.models_url)
    if not ids:
        print(f"\nFATAL: OVMS not reachable at {args.models_url}. Bring it up first:")
        print("  pwsh -File C:\\Users\\mrbla\\agentic-setup\\scripts\\start-llm.ps1 "
              "-Model coder-30b -Force")
        return 1
    if args.model_id not in ids:
        print(f"\nFATAL: OVMS is serving {ids}, not '{args.model_id}'. "
              f"Run start-llm.ps1 -Model coder-30b -Force.")
        return 1
    print(f"  [OK] OVMS serving: {ids}")

    # Warmup — discarded
    if args.warmup > 0:
        print(f"  [WARMUP] {args.warmup} pass(es) over {len(PROMPTS)} prompts ...")
        for _w in range(args.warmup):
            for prompt in PROMPTS:
                chat_stream(args.endpoint, args.model_id, prompt, args.max_tokens, args.timeout)
        print("  [WARMUP] Done.")

    # Measured generation
    print(f"  [BENCH] {args.runs} run(s) x {len(PROMPTS)} prompts ...")
    gen_runs = measure_generation(
        args.endpoint, args.model_id, args.runs, args.max_tokens,
        args.timeout, args.run_cooldown)
    stats = aggregate(gen_runs)

    # Prefill / pp
    prefill_runs: list[PrefillRunMetrics] = []
    if measure_pp:
        print(f"  [PREFILL] {args.runs} pp probe run(s) (max_tokens=1) ...")
        prefill_runs = measure_prefill(
            args.endpoint, args.model_id, args.runs, args.timeout, args.run_cooldown)
    pstats = aggregate_prefill(prefill_runs)
    if pstats.measured:
        print(f"  [PREFILL] pp tok/s: mean={pstats.mean_pp:.1f} median={pstats.median_pp:.1f} "
              f"P95={pstats.p95_pp:.1f} (~{pstats.mean_input_tokens:.0f} prompt tokens)")
    elif measure_pp:
        print("  [PREFILL] pp NOT measured (no usage.prompt_tokens / probe error).")

    # Summary
    print(f"\n{'=' * 68}\n  SUMMARY — {args.model_name} (OVMS coder-30b)\n{'=' * 68}")
    print(f"  Throughput (tok/s) : mean={stats.mean_tps:.1f} median={stats.median_tps:.1f} "
          f"P95={stats.p95_tps:.1f}")
    if pstats.measured:
        print(f"  Prefill pp (tok/s) : mean={pstats.mean_pp:.1f} median={pstats.median_pp:.1f} "
              f"P95={pstats.p95_pp:.1f} (~{pstats.mean_input_tokens:.0f} prompt tok)")
    print(f"  TTFT (ms)          : mean={_fmt_ms(stats.mean_ttft_ms)} "
          f"median={_fmt_ms(stats.median_ttft_ms)} P95={_fmt_ms(stats.p95_ttft_ms)}")
    print(f"  Total latency (ms) : mean={stats.mean_total_ms:.0f} median={stats.median_total_ms:.0f} "
          f"P95={stats.p95_total_ms:.0f}")
    print(f"  Runs (ok/err)      : {stats.total_runs - stats.error_runs}/{stats.error_runs}")

    config_stamp = {
        "timestamp": timestamp,
        "model_name": args.model_name,
        "served_model_id": args.model_id,
        "endpoint": args.endpoint,
        "device": "GPU",
        "ovms_version": args.ovms_version,
        "ovms_flags": args.ovms_flags,
        "driver_version": args.driver_version,
        "prompt_set_version": PROMPT_SET_VERSION,
        "prefill_probe_version": PREFILL_PROBE_VERSION,
        "num_runs": args.runs,
        "num_warmup": args.warmup,
        "run_cooldown_s": args.run_cooldown,
        "max_tokens": args.max_tokens,
    }
    results = {
        "ovms_served": {
            "aggregate": {
                "mean_tps": round(stats.mean_tps, 2),
                "median_tps": round(stats.median_tps, 2),
                "p95_tps": round(stats.p95_tps, 2),
                "mean_ttft_ms": round(stats.mean_ttft_ms, 1),
                "median_ttft_ms": round(stats.median_ttft_ms, 1),
                "p95_ttft_ms": round(stats.p95_ttft_ms, 1),
                "mean_total_ms": round(stats.mean_total_ms, 1),
                "median_total_ms": round(stats.median_total_ms, 1),
                "p95_total_ms": round(stats.p95_total_ms, 1),
                "total_runs": stats.total_runs,
                "error_runs": stats.error_runs,
            },
            "prefill": {
                "measured": pstats.measured,
                "mean_pp": round(pstats.mean_pp, 2),
                "median_pp": round(pstats.median_pp, 2),
                "p95_pp": round(pstats.p95_pp, 2),
                "mean_input_tokens": round(pstats.mean_input_tokens, 1),
                "probe_version": PREFILL_PROBE_VERSION,
                "total_runs": pstats.total_runs,
                "error_runs": pstats.error_runs,
                "raw_runs": [
                    {"input_tokens": pr.input_tokens, "prefill_ms": round(pr.prefill_ms, 1),
                     "prefill_tok_per_sec": round(pr.prefill_tok_per_sec, 2), "error": pr.error}
                    for pr in prefill_runs
                ],
            },
            "raw_runs": [
                {"prompt_index": r.prompt_index, "token_count": r.token_count,
                 "latency_first_token_ms": round(r.latency_first_token_ms, 1),
                 "latency_total_ms": round(r.latency_total_ms, 1),
                 "throughput_tok_per_sec": round(r.throughput_tok_per_sec, 2), "error": r.error}
                for r in gen_runs
            ],
        }
    }

    output_dir = _REPO_ROOT / "docs" / "performance"
    output_dir.mkdir(parents=True, exist_ok=True)
    ts_file = timestamp.replace(":", "-").replace("T", "_")
    json_path = output_dir / f"benchmark_ovms_{args.model_id}_{ts_file}.json"
    evidence = {
        "benchmark": f"ovms_http_{args.model_id}",
        "config_stamp": config_stamp,
        "results": results,
        "prompts": {"version": PROMPT_SET_VERSION, "texts": PROMPTS},
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(evidence, f, indent=2)
    print(f"\n[SAVE] JSON results -> {json_path}")

    md = format_markdown_entry(timestamp, config_stamp, stats, pstats, args.runs, args.warmup)
    print(f"\n{'=' * 68}\n  PERFORMANCE_LOG.md ENTRY\n{'=' * 68}\n")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
