"""
Speculative-decoding net-cost A/B on the production seam — #778.
================================================================
Dedicated A/B answering the #711 S5 finding: on OpenVINO GenAI 2026.2.1, is
speculative decoding NET-NEGATIVE on short turns but still ~2x on long answers,
or is the S5 result an artifact (nonce-prompt low acceptance / thermal confound /
a harness bug that mislabeled acceptance as "unavailable")?

WHAT #711 S5 FOUND (to reconcile): spec-ON decode tok/s was ~0.73-0.78x of the
spec-OFF control in BOTH caching arms, contradicting the ISS-1 closure's ~2x on
longer answers. Three unmeasured reconciliations were named:
  (a) short generations can't amortize fixed draft/spec overhead;
  (b) draft acceptance degraded on the 2026.2.1 substrate / current pairing;
  (c) a late-matrix thermal confound.
Two methodological findings from reading the #711 harness + a rig probe here:
  * S5 used NONCE/FILLER prompts (random-ish text). A draft model cannot predict
    random filler, so acceptance is near-zero BY CONSTRUCTION there — spec-decode
    can only ever be net-negative on such prompts. Real conversational / answer
    text is far more predictable, which is where a draft earns its keep. This A/B
    therefore uses REALISTIC prompts that generate natural, coherent text.
  * S5 recorded acceptance "unavailable" because it called a method that does not
    exist on this build (`get_acceptance_rate`). The REAL API on GenAI 2026.2.1 is
    `DecodedResults.extended_perf_metrics` (an `SDPerModelsPerfMetrics`), exposed
    only via the LIST form `generate([prompt], cfg)`, with
    `get_num_accepted_tokens()` / `get_num_generated_tokens()` /
    `draft_model_metrics.get_num_generated_tokens()`. So acceptance IS measurable
    here — hypothesis (b) can be tested directly, not inferred from a tok/s ratio.

SUBSTRATE FACT (found here, worth a field note): a draft-wired (speculative)
LLMPipeline on GenAI 2026.2.1 REQUIRES `num_assistant_tokens` XOR
`assistant_confidence_threshold` on EVERY request — omitting it raises
"Speculative decoding should have initialized options ... xor num_assistant_tokens"
(pipeline_impl.cpp:178). There is therefore NO per-request way to "turn the draft
off" on a draft-wired pipeline. Spec ON vs OFF is two CONSTRUCTIONS:
  ON  = build_shared_pipeline(...) — INT4 14B + pruned-6L INT8 draft wired.
  OFF = a no-draft LLMPipeline (same GPU knobs, cache_size=3, prefix_caching) —
        autoregressive by construction. This is exactly the ADR-012 counterfactual
        ("ship the draft or not"), and matches the #711 S5 spec-OFF control.

DESIGN
------
* Two shapes: (1) SHORT conversational / tool-call turns (~30-80 generated
  tokens); (2) LONG answers (~400-600 generated tokens).
* FOUR cells = shape x arm (short/long × ON/OFF). N>=5 timed runs per cell.
* INTERLEAVED, not blocked: the run proceeds in ROUNDS; each round measures BOTH
  arms, and the leading arm alternates every round (round 0 ON-first, round 1
  OFF-first, ...). Because two 14B pipelines cannot co-reside under the 31.3 GB
  ceiling, interleaving is at the arm-BLOCK grain (build one arm's pipeline, run
  its short+long block, tear down, build the other) with the per-round lead swap
  spreading each arm evenly across the thermal window — far better than the #711
  single-block-each AABB, which is the (c) confound this reconciles.
* Metrics per run come from the runtime's own perf metrics — ON produces
  `SDPerModelsPerfMetrics` (ttft/tpot/throughput + generated/accepted/draft
  counts); OFF produces a plain `PerfMetrics` (no draft => acceptance structurally
  absent). Plus a wall-clock total-turn time. Reported per cell: median decode
  tok/s (from TPOT, steady-state, EXCLUDES prefill), prefill ms (TTFT), total turn
  ms, generated-token count; and for ON the acceptance rate.

BOX RULES (LA direction, #778): the assistant stays DOWN — this harness never
starts the AO or OVMS. It refuses to start if either appears to hold the GPU
(port 5001 / an OVMS process), holds ONE pipeline resident at a time, and releases
the model at the end so RAM returns.

NOT the posture decision: this script delivers DATA + a printed reconciliation.
The ADR-012 keep/relax/length-condition decision goes to the LA via the coordinator.

Usage (repo root, runtime venv, app CLOSED, dedicated GPU window):
  .venv\\Scripts\\python.exe scripts\\benchmark_spec_decode_ab.py
  # quick rig check:
  .venv\\Scripts\\python.exe scripts\\benchmark_spec_decode_ab.py --rounds 1 \
      --runs-per-block 1 --warmup 1 --long-max-new 96
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import platform
import socket
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    import openvino as ov  # noqa: E402
except Exception:  # noqa: BLE001
    ov = None
try:
    import openvino_genai as ov_genai  # noqa: E402
except Exception:  # noqa: BLE001
    ov_genai = None
try:
    import psutil  # noqa: E402
except Exception:  # noqa: BLE001
    psutil = None

# #816 Part 2: box-state stamp for the result JSON (shape-locked by
# tests/integration/test_perf_harness_env_capture.py).
from shared.perf_env_capture import capture_box_state  # noqa: E402


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HARNESS_NAME = "spec_decode_ab"
SCHEMA_VERSION = 1
VIKUNJA = "#778"
MEM_CEILING_GIB = 31.323  # 32 GB LPDDR5X - 693 MB firmware reservation

DEFAULT_MODEL_DIR = "models/qwen3-14b/openvino-int4-gpu"
DEFAULT_DRAFT_MODEL_DIR = "models/qwen3-0.6b-pruned-6l/openvino-int8-gpu"

# DEC-01 / ISS-1: per-request num_assistant_tokens (NOT pipeline-construction).
NUM_ASSISTANT_TOKENS_PROD = 3
# Production generation posture (services/.../config/default.toml [generation]).
REPETITION_PENALTY_PROD = 1.1

AO_LOOPBACK_PORT = 5001  # = launcher.__main__.ORCHESTRATOR_HOST_LOOPBACK_PORT

# A representative BlarAI system+tools prefix (production shape). Held byte-stable
# so, with prefix caching on (production default), it stays cache-valid
# turn-over-turn exactly as in a live session — identical for BOTH arms, so the
# ON-vs-OFF comparison is unaffected by it.
_SYSTEM_PREFIX = (
    "System: You are BlarAI, a private, locally-run assistant with tool access. "
    "Answer accurately and concisely. Prefer the user's own data. You have these "
    "tools available:\n"
    '  - search_knowledge(query: string): search the user\'s local knowledge bank.\n'
    '  - web_search(query: string): search the web via the approved provider.\n'
    '  - check_item(item: int): report the status of a checklist item.\n'
    "Call a tool by emitting a single JSON object {\"name\": <tool>, "
    "\"arguments\": {...}}. Otherwise reply in plain prose. Standing instructions: "
    "be direct, cite the user's documents when used, and never invent facts.\n"
)

_SHORT_QUERIES: tuple[str, ...] = (
    "What is the capital of France? Answer in one short sentence.",
    "Convert 10 kilometers to miles and show the arithmetic briefly.",
    "Write a one-line git commit message for a bug fix in the auth module.",
    "Emit a JSON tool call to check the status of checklist item 7.",
    "In one sentence, what does a firewall do?",
    "List three Linux commands to check disk usage, comma-separated.",
    "Give a JSON object with keys name, port, enabled for a service 'web' on "
    "port 8080 that is enabled.",
    "What is 17 multiplied by 23? Reply with just the number.",
)

_LONG_QUERIES: tuple[str, ...] = (
    "Explain how the TCP three-way handshake establishes a connection, step by "
    "step, and why sequence numbers matter. Be thorough.",
    "Describe how public-key cryptography works and why it provides both "
    "confidentiality and authentication. Give concrete detail.",
    "Walk through how to set up a secure home network from scratch, explaining "
    "the reason behind each step.",
    "Explain the difference between processes and threads, with examples, their "
    "memory implications, and when to use each.",
    "Give a detailed overview of how a modern CPU instruction pipeline works, "
    "including fetch, decode, execute, and hazards.",
    "Explain how HTTPS establishes a secure connection, from DNS resolution "
    "through the TLS handshake to encrypted data transfer.",
    "Describe how a write-ahead log keeps a database durable and consistent "
    "across a crash, and the trade-offs involved.",
    "Explain how garbage collection works in a managed runtime, covering "
    "mark-and-sweep, generational collection, and pause times.",
)


# ---------------------------------------------------------------------------
# PURE helpers
# ---------------------------------------------------------------------------

def percentile(vals: Sequence[float], pct: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * (pct / 100.0)
    f, c = math.floor(k), math.ceil(k)
    if f == c:
        return s[int(k)]
    return s[f] + (s[c] - s[f]) * (k - f)


def aggregate(vals: Sequence[float]) -> dict[str, float | int | None]:
    clean = [float(v) for v in vals if v is not None]
    if not clean:
        return {"median": None, "mean": None, "std": None, "p95": None,
                "min": None, "max": None, "n": 0}
    return {
        "median": round(statistics.median(clean), 3),
        "mean": round(statistics.mean(clean), 3),
        "std": round(statistics.pstdev(clean), 3) if len(clean) > 1 else 0.0,
        "p95": round(percentile(clean, 95.0), 3),
        "min": round(min(clean), 3),
        "max": round(max(clean), 3),
        "n": len(clean),
    }


def round_arm_order(round_idx: int) -> tuple[str, str]:
    """Alternate the leading arm each round (round 0 ON-first, 1 OFF-first, ...)."""
    return ("on", "off") if round_idx % 2 == 0 else ("off", "on")


def _prompt(prefix_tag: str, i: int, query: str) -> str:
    """System prefix (cache-stable) + a nonce-tagged fresh user turn."""
    return f"{_SYSTEM_PREFIX}\nUser: [{prefix_tag}{i:03d}] {query}\nAssistant:"


def short_prompt(arm: str, idx: int) -> str:
    return _prompt(f"s-{arm}-", idx, _SHORT_QUERIES[idx % len(_SHORT_QUERIES)])


def long_prompt(arm: str, idx: int) -> str:
    return _prompt(f"l-{arm}-", idx, _LONG_QUERIES[idx % len(_LONG_QUERIES)])


# -- Refuse-to-start guard -----------------------------------------------------

def port_held(port: int, host: str = "127.0.0.1") -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        sock.bind((host, port))
        return False
    except OSError:
        return True
    finally:
        sock.close()


def ovms_process_names(process_names: Iterable[str] | None = None) -> list[str]:
    if process_names is None:
        if psutil is None:
            return []
        names = []
        for proc in psutil.process_iter(["name"]):
            try:
                names.append(proc.info.get("name") or "")
            except Exception:  # noqa: BLE001
                continue
        process_names = names
    return sorted({n for n in process_names if "ovms" in n.lower()})


def gpu_hold_reasons(ao_port: int = AO_LOOPBACK_PORT,
                     process_names: Iterable[str] | None = None,
                     port_probe: Callable[[int], bool] = port_held) -> list[str]:
    reasons: list[str] = []
    if port_probe(ao_port):
        reasons.append(f"port {ao_port} (AO loopback) responding — the BlarAI app "
                       "appears up and holding the GPU")
    hits = ovms_process_names(process_names)
    if hits:
        reasons.append("OVMS process(es) alive: " + ", ".join(hits))
    return reasons


# ---------------------------------------------------------------------------
# Hardware helpers
# ---------------------------------------------------------------------------

def avail_gib() -> float:
    return psutil.virtual_memory().available / (1024 ** 3) if psutil else 0.0


def gpu_driver_version() -> str:
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_VideoController | Where-Object "
             "{ $_.Name -match 'Arc' } | Select-Object -First 1 "
             "-ExpandProperty DriverVersion)"],
            capture_output=True, text=True, timeout=25,
        )
        return out.stdout.strip() or "unavailable"
    except Exception:  # noqa: BLE001
        return "unavailable"


def capture_environment(core: Any) -> dict[str, Any]:
    env: dict[str, Any] = {
        "cpu": "Intel Core Ultra 7 258V (Lunar Lake)",
        "cpu_platform": platform.processor() or platform.machine(),
        "os": f"{platform.system()} {platform.version()}",
        "python": platform.python_version(),
        "openvino_version": ov.__version__ if ov else None,
        "openvino_genai_version": ov_genai.__version__ if ov_genai else None,
        "total_ram_gib": round(psutil.virtual_memory().total / (1024 ** 3), 2)
        if psutil else None,
        "mem_ceiling_gib": MEM_CEILING_GIB,
        "ram_spec": "32 GB LPDDR5X (shared CPU/iGPU)",
    }
    try:
        env["gpu"] = str(core.get_property("GPU", "FULL_DEVICE_NAME"))
    except Exception:  # noqa: BLE001
        env["gpu"] = "Intel(R) Arc(TM) 140V GPU (16GB) (iGPU)"
    try:
        env["gpu_uarch"] = str(core.get_property("GPU", "GPU_UARCH_VERSION"))
    except Exception:  # noqa: BLE001
        env["gpu_uarch"] = None
    env["gpu_driver"] = gpu_driver_version()
    return env


def make_gen_config(max_new_tokens: int, spec_decode: bool) -> Any:
    gen = ov_genai.GenerationConfig()
    gen.max_new_tokens = max_new_tokens
    gen.do_sample = False  # greedy — production temperature=0 posture
    gen.repetition_penalty = REPETITION_PENALTY_PROD
    if spec_decode:
        gen.num_assistant_tokens = NUM_ASSISTANT_TOKENS_PROD
    return gen


def _pair_mean(fn: Callable[[], Any]) -> float | None:
    try:
        return round(float(fn().mean), 4)
    except Exception:  # noqa: BLE001
        return None


def read_result(res: Any, draft_prev: int) -> tuple[dict[str, Any], int]:
    """Extract per-run metrics from a list-form generate() result.

    The draft sub-model token counter is CUMULATIVE over the pipeline lifetime, so
    it is differenced against draft_prev; new_draft_prev is the updated cumulative
    value (advance it on every ON run so per-call draft_proposed stays correct)."""
    epm = getattr(res, "extended_perf_metrics", None)
    is_sd = epm is not None and type(epm).__name__ == "SDPerModelsPerfMetrics"
    metrics = epm if epm is not None else getattr(res, "perf_metrics", None)

    row: dict[str, Any] = {
        "metrics_type": type(epm).__name__ if epm is not None
        else type(getattr(res, "perf_metrics", None)).__name__,
    }
    if metrics is None:
        row["note"] = "no perf metrics on result"
        return row, draft_prev

    row["ttft_ms"] = _pair_mean(metrics.get_ttft)
    row["tpot_ms"] = _pair_mean(metrics.get_tpot)
    row["throughput_tok_s_runtime"] = _pair_mean(metrics.get_throughput)
    try:
        row["generated_tokens"] = int(metrics.get_num_generated_tokens())
    except Exception:  # noqa: BLE001
        row["generated_tokens"] = None
    try:
        row["input_tokens"] = int(metrics.get_num_input_tokens())
    except Exception:  # noqa: BLE001
        row["input_tokens"] = None

    new_prev = draft_prev
    if is_sd:
        try:
            row["accepted_tokens"] = int(metrics.get_num_accepted_tokens())
        except Exception:  # noqa: BLE001
            row["accepted_tokens"] = None
        try:
            draft_cum = int(metrics.draft_model_metrics.get_num_generated_tokens())
            row["draft_proposed_tokens"] = draft_cum - draft_prev
            new_prev = draft_cum
        except Exception:  # noqa: BLE001
            row["draft_proposed_tokens"] = None
    return row, new_prev


def timed_generate(pipe: Any, prompt: str, gen: Any,
                   draft_prev: int) -> tuple[dict[str, Any], int]:
    t0 = time.perf_counter()
    res = pipe.generate([prompt], gen)
    wall_ms = (time.perf_counter() - t0) * 1000.0
    row, new_prev = read_result(res, draft_prev)
    row["wall_total_ms"] = round(wall_ms, 2)
    gen_tok = row.get("generated_tokens") or 0
    row["total_turn_tok_s"] = round(gen_tok / (wall_ms / 1000.0), 3) if wall_ms else None
    tpot = row.get("tpot_ms")
    row["decode_tok_s"] = round(1000.0 / tpot, 3) if tpot else None
    try:
        texts = getattr(res, "texts", None)
        text = texts[0] if texts else ""
        row["output_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        row["output_head"] = text[:80]
    except Exception:  # noqa: BLE001
        pass
    return row, new_prev


# -- Pipeline construction (one resident at a time) ----------------------------

def build_on_pipeline(model_dir: Path, draft_dir: Path) -> Any:
    """Draft-wired production seam (spec ON)."""
    from shared.inference.shared_pipeline import build_shared_pipeline
    tmani = model_dir / "manifest.json"
    dmani = draft_dir / "manifest.json"
    res = build_shared_pipeline(
        model_dir=model_dir, draft_model_dir=draft_dir,
        enable_prefix_caching=True, device="GPU",
        target_manifest_path=tmani if tmani.exists() else None,
        draft_manifest_path=dmani if dmani.exists() else None,
    )
    if not res.ok or res.pipeline is None:
        raise RuntimeError(f"build_shared_pipeline failed: {res.error}")
    return res.pipeline


def build_off_pipeline(model_dir: Path) -> Any:
    """No-draft LLMPipeline (spec OFF — autoregressive by construction), same GPU
    knobs + cache_size=3 + prefix caching as the seam, minus the draft_model."""
    sched = ov_genai.SchedulerConfig()
    sched.cache_size = 3
    sched.enable_prefix_caching = True
    return ov_genai.LLMPipeline(
        str(model_dir), "GPU",
        PERFORMANCE_HINT="LATENCY", MODEL_PRIORITY="HIGH",
        INFERENCE_PRECISION_HINT="f16", GPU_ENABLE_SDPA_OPTIMIZATION="ON",
        CACHE_DIR="", scheduler_config=sched,
    )


def teardown(pipe: Any, target_gib: float = 18.0, timeout_s: float = 45.0) -> tuple[bool, float]:
    """Release a pipeline and WAIT for the RAM to actually come back.

    The draft-wired wrapper (ON) exposes ``release_gpu_for_exit`` and frees
    promptly; a raw no-draft ``LLMPipeline`` (OFF) does not, and its GPU context
    can linger for several seconds after ``del`` until the destructor runs. Since
    two 14B pipelines cannot co-reside, the next build must not start until this
    one's memory is back — so gc + poll until free RAM recovers past target_gib
    (or timeout, then warn and proceed; the next allocation usually forces the
    reclaim anyway)."""
    released = False
    try:
        rel = getattr(pipe, "release_gpu_for_exit", None)
        if callable(rel):
            released = bool(rel())
    except Exception:  # noqa: BLE001
        pass
    del pipe
    deadline = time.perf_counter() + timeout_s
    while True:
        gc.collect()
        free = avail_gib()
        if free >= target_gib or time.perf_counter() >= deadline:
            if free < target_gib:
                print(f"   [teardown] WARN: only {free:.1f} GiB free after "
                      f"{timeout_s:.0f}s wait (target {target_gib:.0f}); proceeding.")
            return released, free
        time.sleep(2.5)


def measure_block(pipe: Any, arm: str, runs_per_block: int, warmup: int,
                  short_max_new: int, long_max_new: int,
                  idx_base: int) -> list[dict[str, Any]]:
    """Warm the fresh pipeline, then run runs_per_block SHORT + runs_per_block LONG
    timed generations for this arm. Fresh pipeline => draft counter resets to 0."""
    spec = (arm == "on")
    gen_short = make_gen_config(short_max_new, spec_decode=spec)
    gen_long = make_gen_config(long_max_new, spec_decode=spec)
    draft_prev = 0
    # Warmup (discarded): warms the shared system prefix cache + settles the
    # pipeline. A short gen suffices (same prefix serves both shapes).
    warm_gen = make_gen_config(48, spec_decode=spec)
    for w in range(warmup):
        r = pipe.generate([short_prompt(arm, 900 + w)], warm_gen)
        if spec:
            epm = getattr(r, "extended_perf_metrics", None)
            if epm is not None and type(epm).__name__ == "SDPerModelsPerfMetrics":
                try:
                    draft_prev = int(epm.draft_model_metrics.get_num_generated_tokens())
                except Exception:  # noqa: BLE001
                    pass
    rows: list[dict[str, Any]] = []
    for shape, builder, gen in (("short", short_prompt, gen_short),
                                ("long", long_prompt, gen_long)):
        for k in range(runs_per_block):
            prompt = builder(arm, idx_base + k)
            row, draft_prev = timed_generate(pipe, prompt, gen, draft_prev)
            row["arm"] = arm
            row["shape"] = shape
            rows.append(row)
            print(f"   [{shape:5s} {arm:3s} #{idx_base + k:02d}] "
                  f"gen={row.get('generated_tokens')} "
                  f"decode={row.get('decode_tok_s')} tok/s "
                  f"prefill={row.get('ttft_ms')} ms total={row.get('wall_total_ms')} ms "
                  f"acc={row.get('accepted_tokens')}/{row.get('draft_proposed_tokens')}")
    return rows


# -- Cell aggregation ----------------------------------------------------------

def summarize_cell(runs: list[dict[str, Any]]) -> dict[str, Any]:
    decode = [r["decode_tok_s"] for r in runs if r.get("decode_tok_s")]
    prefill = [r["ttft_ms"] for r in runs if r.get("ttft_ms")]
    total = [r["wall_total_ms"] for r in runs if r.get("wall_total_ms")]
    turn_tps = [r["total_turn_tok_s"] for r in runs if r.get("total_turn_tok_s")]
    gen = [r["generated_tokens"] for r in runs if r.get("generated_tokens")]
    rt = [r["throughput_tok_s_runtime"] for r in runs
          if r.get("throughput_tok_s_runtime")]
    cell: dict[str, Any] = {
        "n": len(runs),
        "decode_tok_s": aggregate(decode),
        "prefill_ms": aggregate(prefill),
        "total_turn_ms": aggregate(total),
        "total_turn_tok_s": aggregate(turn_tps),
        "runtime_throughput_tok_s": aggregate(rt),
        "generated_tokens": aggregate(gen),
        "metrics_types": sorted({r.get("metrics_type", "?") for r in runs}),
    }
    accepted = [r["accepted_tokens"] for r in runs if r.get("accepted_tokens") is not None]
    proposed = [r["draft_proposed_tokens"] for r in runs
                if r.get("draft_proposed_tokens") is not None]
    if accepted:
        tot_acc = sum(accepted)
        tot_gen = sum(gen) if gen else 0
        tot_prop = sum(proposed) if proposed else 0
        cell["acceptance"] = {
            "total_accepted": tot_acc,
            "total_generated": tot_gen,
            "total_draft_proposed": tot_prop,
            "accepted_per_generated": round(tot_acc / tot_gen, 4) if tot_gen else None,
            "accepted_per_draft_proposed": round(tot_acc / tot_prop, 4) if tot_prop else None,
        }
    return cell


def _med(cell: dict, key: str) -> float | None:
    try:
        return cell[key]["median"]
    except Exception:  # noqa: BLE001
        return None


def reconcile(results: dict[str, Any]) -> dict[str, Any]:
    verdict: dict[str, Any] = {"per_shape": {}}
    for shape in ("short", "long"):
        on, off = results[shape]["on"], results[shape]["off"]
        on_d, off_d = _med(on, "decode_tok_s"), _med(off, "decode_tok_s")
        on_t, off_t = _med(on, "total_turn_tok_s"), _med(off, "total_turn_tok_s")
        acc = on.get("acceptance", {})
        verdict["per_shape"][shape] = {
            "decode_speedup_on_over_off": round(on_d / off_d, 3) if on_d and off_d else None,
            "total_turn_speedup_on_over_off": round(on_t / off_t, 3) if on_t and off_t else None,
            "on_decode_tok_s": on_d, "off_decode_tok_s": off_d,
            "on_total_turn_tok_s": on_t, "off_total_turn_tok_s": off_t,
            "acceptance_per_generated": acc.get("accepted_per_generated"),
            "acceptance_per_draft_proposed": acc.get("accepted_per_draft_proposed"),
            "gen_tokens_median_on": _med(on, "generated_tokens"),
            "gen_tokens_median_off": _med(off, "generated_tokens"),
            "off_metrics_types": off.get("metrics_types"),
            "on_metrics_types": on.get("metrics_types"),
        }
    return verdict


# ---------------------------------------------------------------------------
# CLI + main
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="BlarAI spec-decode net-cost A/B (#778).")
    ap.add_argument("--rounds", type=int, default=3,
                    help="interleave rounds; each round runs BOTH arms (lead swaps)")
    ap.add_argument("--runs-per-block", type=int, default=2, dest="runs_per_block",
                    help="timed runs per shape per arm-block; N per cell = rounds x this")
    ap.add_argument("--warmup", type=int, default=1, help="discarded warmups per block")
    ap.add_argument("--short-max-new", type=int, default=100, dest="short_max_new")
    ap.add_argument("--long-max-new", type=int, default=600, dest="long_max_new")
    ap.add_argument("--model-dir", default=DEFAULT_MODEL_DIR)
    ap.add_argument("--draft-model-dir", default=DEFAULT_DRAFT_MODEL_DIR, dest="draft_model_dir")
    ap.add_argument("--output-dir", default="docs/performance", dest="output_dir")
    ap.add_argument("--min-avail-gib", type=float, default=18.0, dest="min_avail_gib")
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    # #816 Part 2: stamp the box state AT RUN START — before even the
    # refuse-to-start guard, so the evidence records exactly what was resident
    # (VMs, AO, OVMS, RAM) the moment this run began (the 2026-07-10
    # unnoticed-VM incident).  Fail-soft: a probe failure stamps "unknown",
    # never breaks the run.
    box_state_at_start = capture_box_state()

    reasons = gpu_hold_reasons()
    if reasons:
        print("FATAL: GPU appears held — refusing to start (do not queue behind a live app).")
        for r in reasons:
            print(f"  - {r}")
        return 2
    if ov is None or ov_genai is None or psutil is None:
        print("FATAL: OpenVINO / GenAI / psutil not importable.")
        return 1
    now_avail = avail_gib()
    if now_avail < args.min_avail_gib:
        print(f"FATAL: only {now_avail:.1f} GiB free (< {args.min_avail_gib} floor).")
        return 2

    md = Path(args.model_dir)
    model_dir = md if md.is_absolute() else (_REPO_ROOT / md).resolve()
    dd = Path(args.draft_model_dir)
    draft_dir = dd if dd.is_absolute() else (_REPO_ROOT / dd).resolve()
    for p, label in ((model_dir, "target"), (draft_dir, "draft")):
        if not (p / "openvino_model.xml").exists():
            print(f"FATAL: {label} model not found at {p}")
            return 1

    core = ov.Core()
    env = capture_environment(core)
    n_per_cell = args.rounds * args.runs_per_block
    print(f"== spec-decode A/B (#778) == genai={env['openvino_genai_version']} "
          f"driver={env['gpu_driver']}")
    print(f"   target={model_dir.name}  draft={draft_dir.parent.name}/{draft_dir.name}")
    print(f"   rounds={args.rounds} runs_per_block={args.runs_per_block} "
          f"=> N={n_per_cell}/cell; warmup={args.warmup}/block; "
          f"short_max_new={args.short_max_new} long_max_new={args.long_max_new}")
    print(f"   free RAM at start: {now_avail:.1f} GiB")

    short_on: list[dict] = []
    short_off: list[dict] = []
    long_on: list[dict] = []
    long_off: list[dict] = []
    build_times: dict[str, list[float]] = {"on": [], "off": []}
    block_log: list[dict] = []

    for rnd in range(args.rounds):
        for arm in round_arm_order(rnd):
            idx_base = rnd * args.runs_per_block
            print(f"\n== round {rnd} | arm={arm.upper()} (build + block) ==")
            t_build = time.perf_counter()
            pipe = build_on_pipeline(model_dir, draft_dir) if arm == "on" \
                else build_off_pipeline(model_dir)
            build_s = time.perf_counter() - t_build
            build_times[arm].append(round(build_s, 1))
            print(f"   {arm} pipeline built in {build_s:.1f}s "
                  f"(free {avail_gib():.1f} GiB)")
            try:
                rows = measure_block(pipe, arm, args.runs_per_block, args.warmup,
                                     args.short_max_new, args.long_max_new, idx_base)
            finally:
                released, free_after = teardown(pipe, target_gib=args.min_avail_gib)
            for row in rows:
                row["round"] = rnd
                block_log.append(row)
                if row["shape"] == "short":
                    (short_on if arm == "on" else short_off).append(row)
                else:
                    (long_on if arm == "on" else long_off).append(row)
            print(f"   {arm} block torn down (released={released}); free {free_after:.1f} GiB")

    results = {
        "short": {"on": summarize_cell(short_on), "off": summarize_cell(short_off)},
        "long": {"on": summarize_cell(long_on), "off": summarize_cell(long_off)},
    }
    verdict = reconcile(results)

    not_measured = [
        "draft ACCEPTANCE is exposed by this GenAI build and IS recorded here "
        "(accepted/generated + accepted/draft_proposed) — not a gap; noted because "
        "#711 S5 wrongly logged it 'unavailable' (called a nonexistent method).",
        f"N={n_per_cell} per cell (rounds x runs_per_block) — small-N medians; "
        "std/p95/min/max are reported so spread is visible.",
        "spec ON vs OFF are two CONSTRUCTIONS (draft-wired vs no-draft) because a "
        "draft-wired pipeline on GenAI 2026.2.1 requires a per-request spec param "
        "and cannot be disengaged per-request — so interleaving is at the arm-BLOCK "
        "grain (per-round lead swap), NOT single-generation; within-round thermal "
        "drift is controlled, ambient day-to-day variation is not.",
        "coordinator-session RAM overhead (~2 GiB of this box's used RAM is THIS "
        "measurement session + MCP servers, not the model).",
        "single dedicated GPU window on one day; no multi-day thermal envelope.",
        "TTFT/prefill is measured with the shared system prefix cache-WARM (as in a "
        "live session); the cold first-prefill is absorbed by the per-block warmup.",
        "co-resident cost (14B + anything else) is NOT measured — one pipeline is "
        "resident at a time, matching the AO-only posture.",
    ]

    out = {
        "harness": HARNESS_NAME,
        "schema_version": SCHEMA_VERSION,
        "vikunja": VIKUNJA,
        "question": ("Is speculative decoding net-negative on short turns but ~2x on "
                     "long answers on OpenVINO GenAI 2026.2.1? Reconcile #711 S5 vs "
                     "the ISS-1 ~2x closure."),
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        # #816 Part 2: static box facts + the box state this run was measured
        # under (start stamp = the evidence anchor; end stamp = what changed
        # under the run — battery jobs start/stop the AO/OVMS on this box).
        "environment": {
            **env,
            "box_state_at_start": box_state_at_start,
            "box_state_at_end": capture_box_state(),
        },
        "methodology": {
            "spec_on": ("build_shared_pipeline production seam — INT4 14B + pruned-6L "
                        "INT8 draft wired, cache_size=3, prefix_caching=True; per-request "
                        f"num_assistant_tokens={NUM_ASSISTANT_TOKENS_PROD} (DEC-01/ISS-1)"),
            "spec_off": ("no-draft LLMPipeline, same GPU knobs + cache_size=3 + "
                         "prefix_caching — autoregressive by construction (ADR-012 "
                         "counterfactual; = the #711 S5 spec-OFF control)"),
            "substrate_fact": ("a draft-wired pipeline on GenAI 2026.2.1 REQUIRES "
                               "num_assistant_tokens XOR assistant_confidence_threshold "
                               "on every request (pipeline_impl.cpp:178); there is no "
                               "per-request draft disengage, so ON/OFF are two builds"),
            "interleave": ("rounds; each round runs BOTH arms, leading arm alternates "
                           "per round (ABAB at the arm-block grain); one pipeline "
                           "resident at a time (two 14B pipelines exceed the 31.3 GB "
                           "ceiling)"),
            "shapes": {"short": f"~30-80 gen tokens (max_new={args.short_max_new}), "
                                "realistic conversational/tool-call turns",
                       "long": f"~400-600 gen tokens (max_new={args.long_max_new}), "
                               "realistic long-answer questions"},
            "prompts": ("realistic version-controlled prompts (NOT #711 nonce filler — "
                        "nonce text has near-zero draft acceptance by construction); "
                        "shared system+tools prefix, fresh nonce-tagged user turn per run"),
            "generation": f"do_sample=False (greedy), repetition_penalty="
                          f"{REPETITION_PENALTY_PROD} (production [generation] posture)",
            "metrics": ("runtime perf metrics — SDPerModelsPerfMetrics (ON) / PerfMetrics "
                        "(OFF) via list-form generate — ttft/tpot/throughput/generated + "
                        "ON accepted/draft_proposed; plus wall-clock total turn time"),
            "decode_tok_s": "1000/TPOT — steady-state, EXCLUDES prefill",
            "runs_per_cell": n_per_cell,
            "rounds": args.rounds,
            "runs_per_block": args.runs_per_block,
            "warmup_discarded_per_block": args.warmup,
            "build_times_s": build_times,
        },
        "results": results,
        "reconciliation": verdict,
        "ordered_run_log": block_log,
        "not_measured": not_measured,
        "box_state": {
            "ao_started": False, "ovms_started": False,
            "free_gib_at_start": round(now_avail, 2),
            "free_gib_at_end": round(avail_gib(), 2),
        },
    }

    out_dir = Path(args.output_dir)
    out_dir = out_dir if out_dir.is_absolute() else (_REPO_ROOT / out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%d_%H-%M-%S")
    safe_ov = (env["openvino_genai_version"] or "unknown").split("-")[0].replace(".", "_")
    outpath = out_dir / f"{HARNESS_NAME}_ov{safe_ov}_{ts}.json"
    outpath.write_text(json.dumps(out, indent=2), encoding="utf-8")

    print(f"\n[SAVE] {outpath}")
    print("\n" + "=" * 78)
    print("SPEC-DECODE A/B — 4-cell summary (median)")
    print("=" * 78)
    print(f"{'cell':14s} {'decode tok/s':>13s} {'prefill ms':>11s} {'total ms':>11s} "
          f"{'gen tok':>8s} {'accept/gen':>11s}")
    for shape in ("short", "long"):
        for arm in ("on", "off"):
            c = results[shape][arm]
            acc = (c.get("acceptance") or {}).get("accepted_per_generated")
            print(f"{shape + '/' + arm:14s} {str(_med(c,'decode_tok_s')):>13s} "
                  f"{str(_med(c,'prefill_ms')):>11s} {str(_med(c,'total_turn_ms')):>11s} "
                  f"{str(_med(c,'generated_tokens')):>8s} {str(acc):>11s}")
    print("-" * 78)
    for shape in ("short", "long"):
        v = verdict["per_shape"][shape]
        print(f"{shape}: decode speedup ON/OFF = {v['decode_speedup_on_over_off']}x | "
              f"total-turn speedup = {v['total_turn_speedup_on_over_off']}x | "
              f"acceptance/gen = {v['acceptance_per_generated']} | "
              f"acceptance/proposed = {v['acceptance_per_draft_proposed']}")
    print("=" * 78)
    print(f"free RAM at end: {avail_gib():.1f} GiB (AO down, OVMS down)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
