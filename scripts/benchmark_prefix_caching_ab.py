"""
Prefix-caching A/B re-validation harness (``enable_prefix_caching``) — #711.
============================================================================
Standalone A/B for the production ``enable_prefix_caching=True`` lock
(ADR-012 Amendment 3, hardcoded at ``launcher/__main__.py:1542``), per the
LA-approved plan ``docs/performance/prefix_caching_ab_validation_plan.md``.

The flag is FLIPPED PER ARM, never pinned: every angle runs once with
``enable_prefix_caching=False`` and once with ``True``, each on a FRESH
pipeline (build, run, ``del``/``gc``/settle — the #709 kv-sweep protocol).
The primary pipeline is the PRODUCTION seam itself —
``shared.inference.shared_pipeline.build_shared_pipeline(...,
enable_prefix_caching=...)`` — so the A/B exercises exactly the config the
launcher ships (INT4 14B + Qwen3-0.6B pruned-6L draft, spec-decode ON,
``cache_size=3``). Non-production controls (``--cache-size != 3``, the S5
spec-OFF sub-arm) use a direct mirrored build and are LABELLED as controls
in the output.

Angles (see the plan; S8 added by LA direction on #711):
  S1  shared-prefix repeated turns        — the claimed win (cold vs warm TTFT)
  S2  realistic agentic multi-turn        — growing history, ~10 turns
  S3  no-reuse worst case                 — unique nonce prompts (overhead probe)
  S4  long context 16K at cache_size=3    — starved-pool interaction (#709)
  S5  spec-decode acceptance / speedup    — spec-ON vs spec-OFF per caching arm
  S6  correctness / determinism           — exact output equality OFF vs ON
  S7  co-resident pressure (14B-only)     — memory instruments vs the ceiling
  S8  pinned operator-preference block    — byte-stable N-token block at a fixed
      early position, N in {256,512,1024,2048}: cold / warm-identical /
      one-line-edit invalidation TTFT cost curve

Methodology (plan-locked, pre-committed before any run):
  * N >= 5 timed runs (--runs) + >= 2 discarded warmups (--warmup).
  * median + std + p95 reported for every aggregate.
  * streamer-callback TTFT (hardware-timed first token), as in the kv sweep.
  * fixed, version-controlled prompt builders (pure functions, unit-tested).
  * memory: GPU_MEMORY_STATISTICS (cl_mem/usm_host/...) + psutil avail-RAM
    delta vs the 31.323 GiB ceiling. HONEST CAVEAT (carried from #709): the
    reserved KV pool is fixed at cache_size regardless of hits, so memory
    readouts are largely BLIND to prefix-cache hit savings — the win is read
    from TTFT/throughput; memory is watched for pressure/regression only.
  * thermal: inter-combo cooldown (default 120 s) OR --steady-state
    (warm-to-plateau first, then back-to-back at the throttled plateau) —
    the kv-sweep lesson-8 third-instance control, preserved.
  * refuse-to-start: if the AO/app appears to hold the GPU (port 5001
    responding, or an OVMS process alive) the harness FAILS LOUD (exit 2)
    and does not queue. A minimum-available-RAM cleanliness gate must also
    pass before the first pipeline build.

Decision criteria live in the plan (pre-committed): keep ON iff S1/S2 win
AND S6 no drift AND S5 no acceptance collapse AND S3/S4 no material
regression; otherwise OFF or workload-conditional.

Usage (repo root, runtime venv, app CLOSED, daylight GPU window):
  .venv\\Scripts\\python.exe scripts\\benchmark_prefix_caching_ab.py
  # rig-validation dry run first (plan next-step):
  .venv\\Scripts\\python.exe scripts\\benchmark_prefix_caching_ab.py \
      --angles S1,S3 --runs 2 --warmup 1
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
import sys
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Heavy/optional imports are guarded so the PURE helpers below (and their unit
# tests) import on any machine, even without the OpenVINO runtime or a GPU.
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


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HARNESS_NAME = "prefix_caching_ab"
SCHEMA_VERSION = 1
PLAN_PATH = "docs/performance/prefix_caching_ab_validation_plan.md"

MEM_CEILING_GIB = 31.323  # effective system RAM (32 GB - 693 MB firmware)

ANGLES: tuple[str, ...] = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8")

ANGLE_DESCRIPTIONS: dict[str, str] = {
    "S1": "shared-prefix repeated turns (fixed ~3K system+tools prefix, distinct short queries)",
    "S2": "realistic agentic multi-turn (fixed system+tools, history grows each turn)",
    "S3": "no-reuse worst case (every prompt fully unique via nonce prefix)",
    "S4": "long context 16K at the shipped cache_size (starved-pool interaction, #709)",
    "S5": "spec-decode acceptance / speedup (spec-ON vs spec-OFF per caching arm)",
    "S6": "correctness / determinism (exact output equality OFF vs ON, temp=0)",
    "S7": "co-resident pressure — 14B-only memory instruments vs the 31.323 GiB ceiling",
    "S8": "pinned operator-preference-block cost curve (cold / warm-hit / one-line-edit)",
}

# Production model paths (shared/constants.py — kept as literals so this
# standalone module imports without the shared package on any machine).
DEFAULT_MODEL_DIR = "models/qwen3-14b/openvino-int4-gpu"
DEFAULT_DRAFT_MODEL_DIR = "models/qwen3-0.6b-pruned-6l/openvino-int8-gpu"

# DEC-01 / ISS-1: per-request num_assistant_tokens (NOT pipeline-construction).
NUM_ASSISTANT_TOKENS_PROD = 3

# AO loopback port — = launcher.__main__.ORCHESTRATOR_HOST_LOOPBACK_PORT.
# Hardcoded with this pointer comment (importing launcher.__main__ drags in the
# full runtime), mirroring the root conftest.py leak-detector pattern.
AO_LOOPBACK_PORT = 5001

S8_BLOCK_SIZES: tuple[int, ...] = (256, 512, 1024, 2048)
_S8_TOKENS_PER_LINE_EST = 16  # approximate; actual token counts recorded at runtime
_S8_PREAMBLE = (
    "System: You are BlarAI, a local assistant. The operator's pinned "
    "preference block follows; honor it in every reply.\n"
)

_GPU_MEM_KEYS = ("cl_mem", "unknown", "usm_device", "usm_host", "usm_shared")

# Neutral, version-controlled filler (same sentence as the kv sweep, held
# constant for cross-harness comparability; ~30 tokens per repetition).
_BASE = (
    "The quick brown fox jumps over the lazy dog near the river bank while the "
    "sun sets slowly behind the distant mountains and a gentle wind carries the "
    "scent of pine across the quiet valley below. "
)


# ---------------------------------------------------------------------------
# PURE helpers (no hardware, no model — unit-tested)
# ---------------------------------------------------------------------------

def parse_angles(spec: str) -> tuple[str, ...]:
    """Parse a comma-separated angle subset, e.g. ``"S1,S3,s8"``.

    Case-insensitive; duplicates collapse; returned in canonical S1..S8 order.
    Raises ``ValueError`` on any unknown angle (fail-closed — a typo must not
    silently shrink the matrix).
    """
    wanted = {tok.strip().upper() for tok in spec.split(",") if tok.strip()}
    if not wanted:
        raise ValueError("no angles given")
    unknown = wanted - set(ANGLES)
    if unknown:
        raise ValueError(
            f"unknown angle(s) {sorted(unknown)}; valid: {', '.join(ANGLES)}"
        )
    return tuple(a for a in ANGLES if a in wanted)


def percentile(vals: Sequence[float], pct: float) -> float:
    """Linear-interpolated percentile (pct in [0,100]) of ``vals``."""
    if not vals:
        return 0.0
    s = sorted(vals)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * (pct / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return s[int(k)]
    return s[f] + (s[c] - s[f]) * (k - f)


def aggregate(vals: list[float]) -> dict[str, float | int]:
    """median / mean / std / p95 / n over a list of measurements (plan-locked
    aggregate shape: median + std + p95 on every reported metric)."""
    clean = [v for v in vals if v is not None]
    if not clean:
        return {"median": 0.0, "mean": 0.0, "std": 0.0, "p95": 0.0, "n": 0}
    return {
        "median": round(statistics.median(clean), 2),
        "mean": round(statistics.mean(clean), 2),
        "std": round(statistics.pstdev(clean), 2) if len(clean) > 1 else 0.0,
        "p95": round(percentile(clean, 95.0), 2),
        "n": len(clean),
    }


def compute_tpot_ms(total_ms: float, ttft_ms: float, n_tokens: int) -> float:
    """Time-per-output-token (ms); -1.0 sentinel when it can't be computed
    (no first token, <=1 token) so it is filtered from aggregates."""
    if ttft_ms < 0 or n_tokens <= 1 or total_ms < ttft_ms:
        return -1.0
    return (total_ms - ttft_ms) / (n_tokens - 1)


def filler_text(approx_tokens: int, tag: str) -> str:
    """Deterministic ~approx_tokens filler with ``tag`` baked into the FIRST
    line, so differently-tagged texts can never share a token prefix (this is
    what keeps angles/arms from accidentally hitting each other's cache
    entries). Token count is approximate; actual counts are recorded at
    runtime via the tokenizer."""
    reps = max(1, math.ceil(approx_tokens / 30))
    return f"[{tag}] " + (_BASE * reps).strip()


# -- S1: shared-prefix repeated turns ---------------------------------------

def build_s1_prefix(approx_tokens: int = 3072) -> str:
    """The fixed system+tools-style shared prefix (byte-stable across calls)."""
    return (
        "System: You are BlarAI, a local assistant with tool access. "
        "The tool schemas and standing instructions follow.\n"
        + filler_text(approx_tokens, "s1-shared-prefix")
    )


def build_s1_queries(n: int) -> list[str]:
    """``n`` distinct, deterministic short user queries."""
    topics = (
        "the weather pattern", "a packing checklist", "the meeting summary",
        "a unit conversion", "the recipe steps", "a filename convention",
        "the backup schedule", "a keyboard shortcut", "the release notes",
        "a travel itinerary",
    )
    return [
        f"Question {i + 1}: give one short sentence about {topics[i % len(topics)]} "
        f"(variant {i})."
        for i in range(n)
    ]


def build_s1_prompt(prefix: str, query: str) -> str:
    return f"{prefix}\n\nUser: {query}\nAssistant:"


# -- S2: realistic agentic multi-turn ----------------------------------------

def build_s2_turns(
    n_turns: int = 10,
    prefix_tokens: int = 1024,
    session_tag: str = "s2",
) -> list[str]:
    """``n_turns`` growing-history prompts. Each prompt EXTENDS the previous
    one (``prompts[i].startswith(prompts[i-1])`` holds), which is exactly the
    reuse shape prefix caching should exploit turn-over-turn. ``session_tag``
    keeps separate sessions token-disjoint."""
    if n_turns < 1:
        raise ValueError("n_turns must be >= 1")
    prefix = (
        "System: You are BlarAI with tool access. Tool schemas follow.\n"
        + filler_text(prefix_tokens, f"s2-prefix-{session_tag}")
    )
    prompts: list[str] = []
    history = prefix
    for t in range(n_turns):
        prompt = (
            f"{history}\nUser: step {t + 1} of the task — check item {t * 3 + 1} "
            f"and report its status.\nAssistant:"
        )
        prompts.append(prompt)
        history = (
            prompt
            + f' {{"tool_call": "check_item", "item": {t * 3 + 1}, '
            f'"status": "ok-{t}"}}'
        )
    return prompts


# -- S3: no-reuse worst case --------------------------------------------------

def build_s3_prompts(n: int, approx_tokens: int = 2048, tag: str = "s3") -> list[str]:
    """``n`` fully-unique prompts — each begins with a unique nonce line so no
    two share ANY token prefix (caching cannot help; probes pure overhead)."""
    return [
        f"nonce-{tag}-{i}-{i * 7 + 13}\n" + filler_text(approx_tokens, f"{tag}-{i}")
        for i in range(n)
    ]


# -- S6: correctness / determinism -------------------------------------------

def build_s6_prompt_set() -> list[str]:
    """Fixed, deterministic prompt set for exact-output comparison (temp=0).
    Mixed shapes: short factual, structured, list, long-prefix, arithmetic."""
    return [
        "User: name the four seasons in order, comma-separated.\nAssistant:",
        'User: reply with exactly this JSON: {"status": "ok", "count": 3}\nAssistant:',
        "User: list three primary colors, one per line.\nAssistant:",
        build_s1_prompt(build_s1_prefix(1024), "summarize the standing instructions in one sentence."),
        "User: what is 17 multiplied by 23? Answer with the number only.\nAssistant:",
    ]


# -- S8: pinned operator-preference-block cost curve --------------------------

def build_s8_block(n_tokens: int) -> str:
    """Byte-stable preference block of ~``n_tokens`` tokens (a pure function of
    ``n_tokens`` — identical bytes on every render). Each line carries the
    block-size tag so blocks of DIFFERENT sizes never share a token prefix
    (no cross-size cache hits polluting the cost curve)."""
    if n_tokens not in S8_BLOCK_SIZES:
        raise ValueError(f"S8 block size must be one of {S8_BLOCK_SIZES}, got {n_tokens}")
    n_lines = max(4, n_tokens // _S8_TOKENS_PER_LINE_EST)
    lines = [
        f"pref[{n_tokens}] {i:04d}: the operator prefers option {i % 7} for "
        f"topic {i % 13}, tone level {i % 5}, detail grade {i % 3}, kept stable."
        for i in range(n_lines)
    ]
    return "\n".join(lines)


def edit_s8_block(block: str) -> str:
    """The one-line-edit variant: the SAME block with exactly ONE line changed
    (the middle line — a fixed, deterministic position), same line count.
    Models the operator amending one preference; everything before the edit
    stays cache-valid, everything after is invalidated."""
    lines = block.split("\n")
    k = len(lines) // 2
    lines[k] = lines[k] + " (EDITED: this preference was amended by the operator.)"
    return "\n".join(lines)


def build_s8_prompt(block: str, query: str) -> str:
    """Block at a FIXED early position: constant preamble, then the block,
    then the user turn. ``len(_S8_PREAMBLE)`` is the byte offset of the block
    in every render."""
    return f"{_S8_PREAMBLE}{block}\nUser: {query}\nAssistant:"


def s8_preamble() -> str:
    """The fixed preamble (exposed for the position-stability lock test)."""
    return _S8_PREAMBLE


# -- Refuse-to-start guard -----------------------------------------------------

def port_held(port: int, host: str = "127.0.0.1") -> bool:
    """True iff ``port`` on ``host`` is currently in use (non-blocking bind
    probe — bind succeeds only when no listener holds the port; mirrors the
    root conftest.py ``_port_held``)."""
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
    """Names among ``process_names`` that look like an OVMS process
    (case-insensitive substring). ``None`` enumerates live processes via
    psutil; pass an explicit iterable in tests."""
    if process_names is None:
        if psutil is None:
            return []
        names: list[str] = []
        for proc in psutil.process_iter(["name"]):
            try:
                name = proc.info.get("name") or ""
            except Exception:  # noqa: BLE001
                continue
            names.append(name)
        process_names = names
    return sorted({n for n in process_names if "ovms" in n.lower()})


def gpu_hold_reasons(
    ao_port: int = AO_LOOPBACK_PORT,
    process_names: Iterable[str] | None = None,
    port_probe: Callable[[int], bool] = port_held,
) -> list[str]:
    """Why the GPU appears held by the AO/app. Empty list = clear to start.

    Fail-loud policy (#711): the harness REFUSES to start on any reason —
    it never queues behind a live app (an interleaved benchmark is garbage
    data AND a risk to the operator's live session)."""
    reasons: list[str] = []
    if port_probe(ao_port):
        reasons.append(
            f"port {ao_port} (AO loopback) is responding -- the BlarAI app "
            "appears to be running and holding the GPU"
        )
    hits = ovms_process_names(process_names)
    if hits:
        reasons.append(
            "OVMS process(es) alive: " + ", ".join(hits)
            + " -- the fleet model server appears to hold the GPU"
        )
    return reasons


def cleanliness_gate(avail_gib_now: float, min_avail_gib: float) -> str | None:
    """First-combo cleanliness gate (kv-sweep lesson-8 third-instance control,
    preserved): refuse the FIRST pipeline build unless the machine starts
    clean. Returns the failure reason, or None when clear."""
    if avail_gib_now < min_avail_gib:
        return (
            f"only {avail_gib_now:.1f} GiB RAM available (< {min_avail_gib:.1f} "
            "GiB floor) -- a prior model/pipeline appears resident; the first "
            "combo would not start from a clean pool. Free memory and re-run."
        )
    return None


# -- Output assembly -----------------------------------------------------------

def default_not_measured(
    angles: Sequence[str],
    steady_state: bool,
) -> list[str]:
    """The explicit not-measured list (community-grade mandate: name what is
    NOT covered rather than implying full coverage). Extended at runtime with
    anything that turns out unavailable (e.g. acceptance metrics)."""
    nm = [
        "prefix-cache HIT memory savings -- the reserved KV pool is fixed at "
        "cache_size regardless of hits, so GPU/host memory readouts are blind "
        "to hit savings; the caching win is read from TTFT/throughput only "
        "(plan honest-caveat, carried from #709)",
    ]
    skipped = [a for a in ANGLES if a not in angles]
    if skipped:
        nm.append("angles not selected this run: " + ", ".join(skipped))
    if "S7" in angles:
        nm.append(
            "S7 measures the 14B-only footprint; the paired-SDXL co-resident "
            "run needs the image model staged and is a separate supervised step"
        )
    if not steady_state:
        nm.append(
            "thermal steady-state plateau (cooldown-separated run; re-run with "
            "--steady-state for the sustained-throttled comparison)"
        )
    return nm


def assemble_output(
    *,
    config: dict[str, Any],
    environment: dict[str, Any],
    results: list[dict[str, Any]],
    not_measured: list[str],
    steady_state_warmup: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The community-grade JSON record (schema locked by the shape test)."""
    return {
        "harness": HARNESS_NAME,
        "schema_version": SCHEMA_VERSION,
        "plan": PLAN_PATH,
        "vikunja": "#711",
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "environment": environment,
        "methodology": {
            "ab_protocol": (
                "flag flipped PER ARM (never pinned): fresh pipeline per "
                "(angle x enable_prefix_caching) combo, del+gc+settle between"
            ),
            "pipeline": (
                "primary arms use the PRODUCTION seam build_shared_pipeline"
                "(..., enable_prefix_caching=<arm>) — INT4 14B + pruned-6L "
                "draft, spec-decode ON, per-request num_assistant_tokens="
                f"{NUM_ASSISTANT_TOKENS_PROD} (DEC-01/ISS-1); non-production "
                "controls (cache_size != 3, spec-OFF sub-arms) use a direct "
                "mirrored build and are labelled pipeline_kind=direct_control"
            ),
            "runs": config.get("runs"),
            "warmup_discarded": config.get("warmup"),
            "aggregates": "median + std + p95 (+ mean, n) on every metric",
            "ttft": "streamer-callback hardware-timed first token",
            "do_sample": False,
            "cache_size_gb": config.get("cache_size"),
            "thermal": (
                "steady-state plateau then back-to-back"
                if config.get("steady_state")
                else f"cooldown-separated combos ({config.get('cooldown_s')} s)"
            ),
            "memory_instruments": {
                "gpu_mem_*": "GPU_MEMORY_STATISTICS (cl_mem ~ reserved KV pool, usm_host ~ weights/working)",
                "sys_peak_used_gib": f"psutil avail-RAM delta vs the {MEM_CEILING_GIB} GiB ceiling (shared-LPDDR5X iGPU proxy)",
                "caveat": "blind to prefix-cache hit savings (pool reserved at cache_size); watched for pressure only",
            },
            "prompts": "fixed version-controlled builders in this script (unit-tested byte-stability)",
        },
        "config": config,
        "steady_state_warmup": steady_state_warmup,
        "results": results,
        "not_measured": not_measured,
    }


def _headline_metrics(arm: dict[str, Any]) -> str:
    """One summary line of an arm record's headline numbers (robust to
    partial/errored arms)."""
    if not isinstance(arm, dict):
        return "(missing)"
    if "error" in arm:
        return f"ERROR: {arm['error']}"
    parts: list[str] = []
    for key, val in arm.items():
        if isinstance(val, dict) and "median" in val:
            parts.append(f"{key} med={val['median']} p95={val.get('p95')}")
        elif isinstance(val, (int, float)) and not isinstance(val, bool):
            if key.startswith(("ttft", "decode", "speedup", "cumulative")):
                parts.append(f"{key}={val}")
    return "; ".join(parts) if parts else "(no scalar metrics)"


def format_summary(output: dict[str, Any]) -> str:
    """PERFORMANCE_LOG-ready summary block, printed at the end of a run."""
    env = output.get("environment", {})
    cfg = output.get("config", {})
    lines = [
        "",
        "=" * 74,
        "PERFORMANCE_LOG-ready summary (adapt into PERFORMANCE_LOG.md):",
        "=" * 74,
        f"### {time.strftime('%Y-%m-%d')} -- Prefix-caching A/B (#711, "
        f"{PLAN_PATH})",
        f"Hardware: {env.get('cpu', 'unknown CPU')} / {env.get('gpu', 'unknown GPU')} "
        f"(driver {env.get('gpu_driver', 'unavailable')})",
        f"OpenVINO GenAI {env.get('openvino_genai_version', '?')} / "
        f"OpenVINO {env.get('openvino_version', '?')}; model {cfg.get('model_dir', '?')}",
        f"Methodology: N={cfg.get('runs')} timed + {cfg.get('warmup')} warmup "
        f"discarded; median/std/p95; cache_size={cfg.get('cache_size')} GB; "
        f"flag flipped per arm on the production build_shared_pipeline seam.",
        "",
    ]
    for rec in output.get("results", []):
        lines.append(f"{rec.get('angle')}: {rec.get('description', '')}")
        lines.append(f"  OFF: {_headline_metrics(rec.get('off', {}))}")
        lines.append(f"  ON : {_headline_metrics(rec.get('on', {}))}")
        for key in ("outputs_identical", "note"):
            if key in rec:
                lines.append(f"  {key}: {rec[key]}")
    lines.append("")
    lines.append("Not measured:")
    for item in output.get("not_measured", []):
        lines.append(f"  - {item}")
    lines.append("=" * 74)
    return "\n".join(lines)


def build_arg_parser() -> argparse.ArgumentParser:
    """The harness CLI (exposed for the arg-parsing lock tests)."""
    ap = argparse.ArgumentParser(
        description="BlarAI prefix-caching A/B re-validation harness (#711).",
    )
    ap.add_argument("--angles", default=",".join(ANGLES),
                    help="comma-separated subset of S1..S8 (default: all)")
    ap.add_argument("--runs", type=int, default=5,
                    help="timed runs per measurement point (plan: N >= 5)")
    ap.add_argument("--warmup", type=int, default=2,
                    help="discarded warmup generates per arm (plan: >= 2)")
    ap.add_argument("--cache-size", type=int, default=3, dest="cache_size",
                    help="SchedulerConfig.cache_size GB (3 = production; any "
                         "other value runs the right-sized control via the "
                         "direct mirrored build)")
    ap.add_argument("--output-dir", default="docs/performance", dest="output_dir",
                    help="where the community-grade JSON lands")
    ap.add_argument("--model-dir", default=DEFAULT_MODEL_DIR)
    ap.add_argument("--draft-model-dir", default=DEFAULT_DRAFT_MODEL_DIR,
                    dest="draft_model_dir")
    ap.add_argument("--gen-tokens", type=int, default=128, dest="gen_tokens")
    ap.add_argument("--s2-turns", type=int, default=10, dest="s2_turns")
    ap.add_argument("--s5-gen-tokens", type=int, default=256, dest="s5_gen_tokens")
    ap.add_argument("--prefix-tokens", type=int, default=3072, dest="prefix_tokens",
                    help="approx token size of the S1 shared prefix (plan: 2-4K)")
    ap.add_argument("--cooldown-s", type=float, default=120.0, dest="cooldown_s",
                    help="idle seconds between (angle x arm) combos (0 disables)")
    ap.add_argument("--steady-state", action="store_true", dest="steady_state",
                    help="warm the iGPU to a thermal plateau first, then run "
                         "back-to-back (forces --cooldown-s 0)")
    ap.add_argument("--min-avail-gib", type=float, default=20.0, dest="min_avail_gib",
                    help="cleanliness floor: refuse to start below this much free RAM")
    return ap


# ---------------------------------------------------------------------------
# Hardware helpers (need OpenVINO / a GPU — NOT unit-tested; @hardware only)
# ---------------------------------------------------------------------------

def avail_gib() -> float:
    return psutil.virtual_memory().available / (1024 ** 3) if psutil else 0.0


def gpu_mem_stats(core: Any) -> dict[str, int]:
    """Best-effort GPU_MEMORY_STATISTICS snapshot (bytes)."""
    try:
        ms = core.get_property("GPU", "GPU_MEMORY_STATISTICS")
        return {k: int(ms.get(k, 0)) for k in _GPU_MEM_KEYS}
    except Exception:  # noqa: BLE001
        return {}


def _b_to_gib(n: int) -> float:
    return round(n / (1024 ** 3), 3)


def count_tokens(tok: Any, text: str) -> int:
    return len(tok(text)["input_ids"])


def make_nonce_prompt(tok: Any, n_tokens: int, nonce: str) -> tuple[str, int]:
    """~n_tokens-token prompt with a unique nonce prefix (defeats any residual
    prefix cache), tokenizer-trimmed to length. Returns (prompt, count)."""
    raw = nonce + " " + filler_text(n_tokens + 64, nonce)
    ids = tok(raw)["input_ids"][:n_tokens]
    prompt = tok.decode(ids, skip_special_tokens=True)
    return prompt, count_tokens(tok, prompt)


def make_gen_config(max_new_tokens: int, spec_decode: bool) -> Any:
    gen = ov_genai.GenerationConfig()
    gen.max_new_tokens = max_new_tokens
    gen.do_sample = False
    if spec_decode:
        # ISS-1 fix shape: per-request GenerationConfig, never construction-time.
        gen.num_assistant_tokens = NUM_ASSISTANT_TOKENS_PROD
    return gen


def timed_generate(pipe: Any, prompt: str, gen: Any) -> tuple[float, float, int]:
    """One generation; TTFT hardware-timed via streamer callback; TPOT from the
    total span + streamed token count. Returns (ttft_ms, tpot_ms, n_tokens)."""
    fired: list[float] = []
    ntok = [0]

    def _cb(_subword: str) -> bool:
        if not fired:
            fired.append(time.perf_counter())
        ntok[0] += 1
        return False  # continue generation

    t0 = time.perf_counter()
    pipe.generate(prompt, gen, streamer=_cb)
    t_end = time.perf_counter()
    ttft_ms = (fired[0] - t0) * 1000.0 if fired else -1.0
    total_ms = (t_end - t0) * 1000.0
    return ttft_ms, compute_tpot_ms(total_ms, ttft_ms, ntok[0]), ntok[0]


def _result_text(res: Any) -> str:
    """Text out of an ov_genai generate() result (str or DecodedResults)."""
    if isinstance(res, str):
        return res
    texts = getattr(res, "texts", None)
    if texts:
        return str(texts[0])
    return str(res)


def make_pipeline_factory(
    args: argparse.Namespace, model_dir: Path, draft_dir: Path
) -> Callable[..., tuple[Any, str]]:
    """Factory over the two build paths.

    Returns ``factory(enable_prefix_caching, spec_decode=True) ->
    (pipeline, pipeline_kind)``:
      * production seam — ``build_shared_pipeline`` (spec ON, cache_size=3;
        manifests verified when present next to the weights);
      * direct_control — mirrored LLMPipeline build for the cache_size
        control and the S5 spec-OFF sub-arm.
    """

    def factory(enable_prefix_caching: bool, spec_decode: bool = True) -> tuple[Any, str]:
        if spec_decode and int(args.cache_size) == 3:
            from shared.inference.shared_pipeline import build_shared_pipeline

            tmani = model_dir / "manifest.json"
            dmani = draft_dir / "manifest.json"
            res = build_shared_pipeline(
                model_dir=model_dir,
                draft_model_dir=draft_dir,
                enable_prefix_caching=enable_prefix_caching,
                device="GPU",
                target_manifest_path=tmani if tmani.exists() else None,
                draft_manifest_path=dmani if dmani.exists() else None,
            )
            if not res.ok or res.pipeline is None:
                raise RuntimeError(
                    f"build_shared_pipeline FAILED (fail-closed): {res.error}"
                )
            return res.pipeline, "shared_pipeline_production_seam"

        # Direct mirrored build (control arms) — same knobs as the seam.
        sched = ov_genai.SchedulerConfig()
        sched.cache_size = int(args.cache_size)
        sched.enable_prefix_caching = enable_prefix_caching
        target_config: dict[str, Any] = {
            "PERFORMANCE_HINT": "LATENCY",
            "MODEL_PRIORITY": "HIGH",
            "INFERENCE_PRECISION_HINT": "f16",
            "GPU_ENABLE_SDPA_OPTIMIZATION": "ON",
            "CACHE_DIR": "",
            "scheduler_config": sched,
        }
        if spec_decode:
            target_config["draft_model"] = ov_genai.draft_model(
                str(draft_dir), "GPU",
                PERFORMANCE_HINT="LATENCY",
                INFERENCE_PRECISION_HINT="f16",
                GPU_ENABLE_SDPA_OPTIMIZATION="ON",
                CACHE_DIR="",
            )
        pipe = ov_genai.LLMPipeline(str(model_dir), "GPU", **target_config)
        return pipe, "direct_control"

    return factory


def teardown_pipeline(pipe: Any) -> None:
    """Fresh-pool teardown between combos: release, gc, settle (#709 protocol)."""
    try:
        release = getattr(pipe, "release_gpu_for_exit", None)
        if callable(release):
            release()
    finally:
        del pipe
        gc.collect()
        time.sleep(2.0)


def warm_to_steady_state(
    factory: Callable[..., tuple[Any, str]],
    tok: Any,
    context: int = 3072,
    tol: float = 0.04,
    window: int = 3,
    max_iter: int = 20,
) -> dict[str, Any]:
    """Drive the fanless iGPU to a thermal PLATEAU before measuring (TTFT as
    the thermal proxy — same control as the kv sweep). Uses a prefix-caching-
    OFF pipeline with nonce prompts so every warm iteration pays a real
    prefill."""
    pipe, _ = factory(enable_prefix_caching=False)
    gen = make_gen_config(4, spec_decode=True)  # heat is in PREFILL
    ramp: list[float] = []
    reached = False
    print(f"   [steady-state] warming to thermal plateau at {context} tok "
          f"(tol {tol:.0%}, window {window}, max {max_iter}) ...")
    try:
        for i in range(max_iter):
            prompt, _n = make_nonce_prompt(tok, context, f"ss{i}")
            ttft, _, _ = timed_generate(pipe, prompt, gen)
            ramp.append(round(ttft, 1))
            print(f"      warm {i}: TTFT={ttft:.0f}ms")
            if len(ramp) >= window:
                recent = ramp[-window:]
                spread = (max(recent) - min(recent)) / statistics.mean(recent)
                if spread <= tol:
                    reached = True
                    print(f"      plateau reached (last {window} within {spread:.1%})")
                    break
    finally:
        teardown_pipeline(pipe)
    return {"context": context, "tol": tol, "window": window,
            "iters": len(ramp), "reached": reached, "ttft_ramp_ms": ramp}


# -- Per-angle runners (each builds + tears down its own pipeline(s)) ---------

def _mem_open(core: Any) -> dict[str, Any]:
    return {"gpu": gpu_mem_stats(core), "avail_gib": avail_gib()}


def _mem_close(rec: dict[str, Any], core: Any, opened: dict[str, Any]) -> None:
    peak = gpu_mem_stats(core)
    rec["gpu_mem_peak_bytes"] = peak
    rec["gpu_mem_kv_pool_gib"] = _b_to_gib(peak.get("cl_mem", 0)) if peak else None
    rec["gpu_mem_host_gib"] = _b_to_gib(peak.get("usm_host", 0)) if peak else None
    rec["sys_peak_used_gib"] = round(opened["avail_gib"] - avail_gib(), 2)


def run_s1(factory: Callable[..., tuple[Any, str]], tok: Any, core: Any,
           args: argparse.Namespace, arm: bool) -> dict[str, Any]:
    opened = _mem_open(core)
    pipe, kind = factory(enable_prefix_caching=arm)
    try:
        rec: dict[str, Any] = {"pipeline_kind": kind}
        gen = make_gen_config(args.gen_tokens, spec_decode=True)
        prefix = build_s1_prefix(args.prefix_tokens)
        rec["prefix_tokens_actual"] = count_tokens(tok, prefix)
        # Warmup on NONCE prompts — the shared prefix must stay COLD for the
        # first timed turn (warming on it would fake the cold measurement).
        for w in range(args.warmup):
            wp, _ = make_nonce_prompt(tok, 1024, f"s1warm-{int(arm)}-{w}")
            pipe.generate(wp, gen)
        queries = build_s1_queries(args.runs + 1)
        cold_ttft, cold_tpot, _ = timed_generate(
            pipe, build_s1_prompt(prefix, queries[0]), gen)
        warm_ttfts: list[float] = []
        warm_tpots: list[float] = []
        totals: list[float] = []
        for q in queries[1:]:
            t0 = time.perf_counter()
            ttft, tpot, _n = timed_generate(pipe, build_s1_prompt(prefix, q), gen)
            totals.append((time.perf_counter() - t0) * 1000.0)
            if ttft >= 0:
                warm_ttfts.append(ttft)
            if tpot >= 0:
                warm_tpots.append(tpot)
        rec["ttft_cold_first_ms"] = round(cold_ttft, 1)
        rec["tpot_cold_first_ms"] = round(cold_tpot, 2)
        rec["ttft_warm_ms"] = aggregate(warm_ttfts)
        rec["tpot_warm_ms"] = aggregate(warm_tpots)
        rec["total_latency_warm_ms"] = aggregate(totals)
        med_tpot = rec["tpot_warm_ms"]["median"]
        rec["decode_tok_s_warm"] = round(1000.0 / med_tpot, 2) if med_tpot else None
        _mem_close(rec, core, opened)
        return rec
    finally:
        teardown_pipeline(pipe)


def run_s2(factory: Callable[..., tuple[Any, str]], tok: Any, core: Any,
           args: argparse.Namespace, arm: bool) -> dict[str, Any]:
    opened = _mem_open(core)
    pipe, kind = factory(enable_prefix_caching=arm)
    try:
        rec: dict[str, Any] = {"pipeline_kind": kind, "turns": args.s2_turns}
        gen = make_gen_config(48, spec_decode=True)  # tool-call-style short outputs
        for w in range(args.warmup):
            wp, _ = make_nonce_prompt(tok, 1024, f"s2warm-{int(arm)}-{w}")
            pipe.generate(wp, gen)
        per_turn: list[list[float]] = [[] for _ in range(args.s2_turns)]
        cumulative: list[float] = []
        for s in range(args.runs):
            turns = build_s2_turns(args.s2_turns, session_tag=f"{int(arm)}-{s}")
            t_session = time.perf_counter()
            for t, prompt in enumerate(turns):
                ttft, _tp, _n = timed_generate(pipe, prompt, gen)
                if ttft >= 0:
                    per_turn[t].append(ttft)
            cumulative.append((time.perf_counter() - t_session) * 1000.0)
        rec["per_turn_ttft_median_ms"] = [
            round(statistics.median(v), 1) if v else None for v in per_turn
        ]
        rec["cumulative_session_ms"] = aggregate(cumulative)
        _mem_close(rec, core, opened)
        return rec
    finally:
        teardown_pipeline(pipe)


def run_s3(factory: Callable[..., tuple[Any, str]], tok: Any, core: Any,
           args: argparse.Namespace, arm: bool) -> dict[str, Any]:
    opened = _mem_open(core)
    pipe, kind = factory(enable_prefix_caching=arm)
    try:
        rec: dict[str, Any] = {"pipeline_kind": kind}
        gen = make_gen_config(args.gen_tokens, spec_decode=True)
        prompts = build_s3_prompts(args.warmup + args.runs, tag=f"s3-{int(arm)}")
        for wp in prompts[: args.warmup]:
            pipe.generate(wp, gen)
        ttfts: list[float] = []
        tpots: list[float] = []
        for prompt in prompts[args.warmup:]:
            ttft, tpot, _n = timed_generate(pipe, prompt, gen)
            if ttft >= 0:
                ttfts.append(ttft)
            if tpot >= 0:
                tpots.append(tpot)
        rec["ttft_ms"] = aggregate(ttfts)
        rec["tpot_ms"] = aggregate(tpots)
        med = rec["tpot_ms"]["median"]
        rec["decode_tok_s"] = round(1000.0 / med, 2) if med else None
        _mem_close(rec, core, opened)
        return rec
    finally:
        teardown_pipeline(pipe)


def run_s4(factory: Callable[..., tuple[Any, str]], tok: Any, core: Any,
           args: argparse.Namespace, arm: bool) -> dict[str, Any]:
    context = 16384  # = max_context_tokens (plan S4)
    opened = _mem_open(core)
    pipe, kind = factory(enable_prefix_caching=arm)
    try:
        rec: dict[str, Any] = {"pipeline_kind": kind, "context": context,
                               "cache_size_gb": int(args.cache_size)}
        gen = make_gen_config(32, spec_decode=True)
        errors: list[str] = []
        # One untimed warm AT LENGTH (pays one-time alloc), nonce'd.
        try:
            wp, _ = make_nonce_prompt(tok, context, f"s4warm-{int(arm)}")
            pipe.generate(wp, gen)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"warmup: {type(exc).__name__}: {exc}")
        cold: list[float] = []
        for r in range(args.runs):
            try:
                prompt, _n = make_nonce_prompt(tok, context, f"s4c-{int(arm)}-{r}")
                ttft, _tp, _g = timed_generate(pipe, prompt, gen)
                if ttft >= 0:
                    cold.append(ttft)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"cold r{r}: {type(exc).__name__}: {exc}")
        warm: list[float] = []
        try:
            fixed, _n = make_nonce_prompt(tok, context, f"s4w-{int(arm)}")
            for r in range(args.runs):
                ttft, _tp, _g = timed_generate(pipe, fixed, gen)
                if ttft >= 0:
                    warm.append(ttft)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"warm-identical: {type(exc).__name__}: {exc}")
        rec["ttft_cold_unique_ms"] = aggregate(cold)
        rec["ttft_warm_identical_ms"] = aggregate(warm)
        rec["errors"] = errors
        _mem_close(rec, core, opened)
        return rec
    finally:
        teardown_pipeline(pipe)


def run_s5(factory: Callable[..., tuple[Any, str]], tok: Any, core: Any,
           args: argparse.Namespace, arm: bool) -> dict[str, Any]:
    rec: dict[str, Any] = {}
    tok_s: dict[str, float | None] = {}
    for spec in (True, False):
        label = "spec_on" if spec else "spec_off_control"
        pipe, kind = factory(enable_prefix_caching=arm, spec_decode=spec)
        try:
            gen = make_gen_config(args.s5_gen_tokens, spec_decode=spec)
            for w in range(args.warmup):
                wp, _ = make_nonce_prompt(tok, 1024, f"s5w-{label}-{int(arm)}-{w}")
                pipe.generate(wp, gen)
            tpots: list[float] = []
            accepted: list[float] = []
            for r in range(args.runs):
                prompt, _n = make_nonce_prompt(tok, 1024, f"s5-{label}-{int(arm)}-{r}")
                ttft, tpot, _g = timed_generate(pipe, prompt, gen)
                if tpot >= 0:
                    tpots.append(tpot)
                if spec:
                    # Acceptance is best-effort: only some GenAI builds expose
                    # extended perf metrics on a non-streamer generate.
                    try:
                        res = pipe.generate(prompt, gen)
                        epm = getattr(res, "extended_perf_metrics", None)
                        rate = getattr(epm, "get_acceptance_rate", None)
                        if callable(rate):
                            accepted.append(float(rate()))
                    except Exception:  # noqa: BLE001
                        pass
            agg = aggregate(tpots)
            rec[f"tpot_ms_{label}"] = agg
            tok_s[label] = round(1000.0 / agg["median"], 2) if agg["median"] else None
            rec[f"decode_tok_s_{label}"] = tok_s[label]
            if spec:
                rec["acceptance_rate"] = (
                    aggregate(accepted) if accepted else "unavailable"
                )
                rec["pipeline_kind_spec_on"] = kind
        finally:
            teardown_pipeline(pipe)
        if args.cooldown_s > 0:
            time.sleep(min(args.cooldown_s, 30.0))
    on = tok_s.get("spec_on")
    off = tok_s.get("spec_off_control")
    rec["spec_speedup_x"] = round(on / off, 2) if on and off else None
    return rec


def run_s6(factory: Callable[..., tuple[Any, str]], tok: Any, core: Any,
           args: argparse.Namespace, arm: bool) -> dict[str, Any]:
    pipe, kind = factory(enable_prefix_caching=arm)
    try:
        rec: dict[str, Any] = {"pipeline_kind": kind}
        gen = make_gen_config(128, spec_decode=True)
        outputs: list[dict[str, Any]] = []
        within_arm_stable = True
        for i, prompt in enumerate(build_s6_prompt_set()):
            text1 = _result_text(pipe.generate(prompt, gen))
            # Second pass: under ON this is the CACHE-HIT path — a hit must
            # not change the output (the sharp determinism probe).
            text2 = _result_text(pipe.generate(prompt, gen))
            if text1 != text2:
                within_arm_stable = False
            outputs.append({
                "prompt_index": i,
                "sha256": hashlib.sha256(text1.encode("utf-8")).hexdigest(),
                "head": text1[:120],
                "len": len(text1),
                "repeat_identical": text1 == text2,
            })
        rec["outputs"] = outputs
        rec["within_arm_repeat_identical"] = within_arm_stable
        return rec
    finally:
        teardown_pipeline(pipe)


def run_s7(factory: Callable[..., tuple[Any, str]], tok: Any, core: Any,
           args: argparse.Namespace, arm: bool) -> dict[str, Any]:
    opened = _mem_open(core)
    pipe, kind = factory(enable_prefix_caching=arm)
    try:
        rec: dict[str, Any] = {"pipeline_kind": kind, "sdxl_paired": False}
        rec["gpu_mem_before_bytes"] = opened["gpu"]
        gen = make_gen_config(args.gen_tokens, spec_decode=True)
        prefix = build_s1_prefix(args.prefix_tokens)
        for w in range(args.warmup):
            wp, _ = make_nonce_prompt(tok, 1024, f"s7w-{int(arm)}-{w}")
            pipe.generate(wp, gen)
        for i, q in enumerate(build_s1_queries(args.runs)):
            pipe.generate(build_s1_prompt(prefix, q), gen)
        _mem_close(rec, core, opened)
        rec["headroom_vs_ceiling_gib"] = round(
            MEM_CEILING_GIB - (psutil.virtual_memory().total / (1024 ** 3)
                               - psutil.virtual_memory().available / (1024 ** 3)),
            2,
        ) if psutil else None
        return rec
    finally:
        teardown_pipeline(pipe)


def run_s8(factory: Callable[..., tuple[Any, str]], tok: Any, core: Any,
           args: argparse.Namespace, arm: bool) -> dict[str, Any]:
    pipe, kind = factory(enable_prefix_caching=arm)
    try:
        rec: dict[str, Any] = {"pipeline_kind": kind, "sizes": []}
        gen = make_gen_config(16, spec_decode=True)  # TTFT-focused
        for w in range(args.warmup):
            wp, _ = make_nonce_prompt(tok, 1024, f"s8w-{int(arm)}-{w}")
            pipe.generate(wp, gen)
        for n in S8_BLOCK_SIZES:
            block = build_s8_block(n)
            size_rec: dict[str, Any] = {
                "block_target_tokens": n,
                "block_actual_tokens": count_tokens(tok, block),
            }
            # (a) COLD: the block's first-ever exposure (single-shot by
            # nature — the first exposure consumes the cold state).
            ttft, _tp, _g = timed_generate(
                pipe, build_s8_prompt(block, f"cold turn for block {n}."), gen)
            size_rec["ttft_cold_ms"] = round(ttft, 1)
            # (b) WARM: repeated turns with the IDENTICAL block (only the
            # trailing user turn varies) — the prefix-cache hit path when ON.
            warm: list[float] = []
            for r in range(args.runs):
                ttft, _tp, _g = timed_generate(
                    pipe, build_s8_prompt(block, f"warm turn {r} for block {n}."),
                    gen)
                if ttft >= 0:
                    warm.append(ttft)
            size_rec["ttft_warm_ms"] = aggregate(warm)
            # (c) EDIT: the turn immediately after a one-line block edit —
            # the invalidation cost (single-shot by nature).
            edited = edit_s8_block(block)
            ttft, _tp, _g = timed_generate(
                pipe, build_s8_prompt(edited, f"post-edit turn for block {n}."),
                gen)
            size_rec["ttft_after_one_line_edit_ms"] = round(ttft, 1)
            rec["sizes"].append(size_rec)
        rec["note"] = (
            "cold and post-edit TTFTs are single-shot by nature (the first "
            "exposure consumes the cache state); warm TTFT carries the full "
            "median/std/p95 aggregate"
        )
        return rec
    finally:
        teardown_pipeline(pipe)


_ANGLE_RUNNERS: dict[str, Callable[..., dict[str, Any]]] = {
    "S1": run_s1, "S2": run_s2, "S3": run_s3, "S4": run_s4,
    "S5": run_s5, "S6": run_s6, "S7": run_s7, "S8": run_s8,
}


def _post_process(angle: str, rec: dict[str, Any]) -> None:
    """Cross-arm derived figures (computed only when both arms succeeded)."""
    off, on = rec.get("off"), rec.get("on")
    if not isinstance(off, dict) or not isinstance(on, dict):
        return
    if "error" in off or "error" in on:
        return
    if angle == "S1":
        o = off.get("ttft_warm_ms", {}).get("median")
        n = on.get("ttft_warm_ms", {}).get("median")
        if o and n:
            rec["warm_ttft_on_over_off"] = round(n / o, 3)
    if angle == "S6":
        offs = {x["prompt_index"]: x["sha256"] for x in off.get("outputs", [])}
        ons = {x["prompt_index"]: x["sha256"] for x in on.get("outputs", [])}
        rec["outputs_identical"] = bool(offs) and offs == ons


def run_ab_angle(angle: str, factory: Callable[..., tuple[Any, str]], tok: Any,
                 core: Any, args: argparse.Namespace) -> dict[str, Any]:
    """One angle, both arms — flag flipped per arm, fresh pipeline each."""
    rec: dict[str, Any] = {"angle": angle,
                           "description": ANGLE_DESCRIPTIONS[angle]}
    for arm in (False, True):
        label = "on" if arm else "off"
        print(f"\n== {angle} | enable_prefix_caching={arm} ==")
        try:
            rec[label] = _ANGLE_RUNNERS[angle](factory, tok, core, args, arm)
        except Exception as exc:  # noqa: BLE001
            # Fail-closed reporting: the error is recorded loudly in the
            # results (and flips the exit code), never swallowed.
            print(f"   !! {angle}/{label} FAILED: {type(exc).__name__}: {exc}")
            rec[label] = {"error": f"{type(exc).__name__}: {exc}"}
        if args.cooldown_s > 0:
            print(f"   [cooldown] idling {args.cooldown_s:.0f}s ...")
            time.sleep(args.cooldown_s)
    _post_process(angle, rec)
    return rec


def capture_environment(core: Any) -> dict[str, Any]:
    """Community-grade environment record (hardware, versions, driver)."""
    env: dict[str, Any] = {
        "cpu": platform.processor() or platform.machine(),
        "os": f"{platform.system()} {platform.version()}",
        "python": platform.python_version(),
        "openvino_version": ov.__version__ if ov else None,
        "openvino_genai_version": ov_genai.__version__ if ov_genai else None,
        "total_ram_gib": round(psutil.virtual_memory().total / (1024 ** 3), 2)
        if psutil else None,
        "mem_ceiling_gib": MEM_CEILING_GIB,
    }
    try:
        env["gpu"] = str(core.get_property("GPU", "FULL_DEVICE_NAME"))
    except Exception:  # noqa: BLE001
        env["gpu"] = "unavailable"
    env["gpu_driver"] = "unavailable"
    for key in ("GPU_DRIVER_VERSION", "DRIVER_VERSION"):
        try:
            env["gpu_driver"] = str(core.get_property("GPU", key))
            break
        except Exception:  # noqa: BLE001
            continue
    return env


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.steady_state:
        args.cooldown_s = 0.0

    try:
        angles = parse_angles(args.angles)
    except ValueError as exc:
        print(f"FATAL: {exc}")
        return 2

    # REFUSE-TO-START: never queue behind a live app / fleet model server.
    reasons = gpu_hold_reasons()
    if reasons:
        print("FATAL: the GPU appears to be held -- refusing to start (#711 policy:")
        print("fail loud, do not queue). Reasons:")
        for reason in reasons:
            print(f"  - {reason}")
        print("Close the BlarAI app / stop OVMS, then re-run.")
        return 2

    if ov is None or ov_genai is None or psutil is None:
        print("FATAL: OpenVINO / OpenVINO GenAI / psutil not importable here.")
        return 1

    # First-combo cleanliness gate (preserved from the kv sweep).
    gate = cleanliness_gate(avail_gib(), args.min_avail_gib)
    if gate is not None:
        print(f"FATAL: cleanliness gate failed -- {gate}")
        return 2

    md = Path(args.model_dir)
    model_dir = md if md.is_absolute() else (_REPO_ROOT / md).resolve()
    dd = Path(args.draft_model_dir)
    draft_dir = dd if dd.is_absolute() else (_REPO_ROOT / dd).resolve()
    if not (model_dir / "openvino_model.xml").exists():
        print(f"FATAL: target model not found at {model_dir}")
        return 1
    if not (draft_dir / "openvino_model.xml").exists():
        print(f"FATAL: draft model not found at {draft_dir}")
        return 1

    from transformers import AutoTokenizer  # local import (heavy)

    tok = AutoTokenizer.from_pretrained(str(model_dir))
    core = ov.Core()
    env = capture_environment(core)
    factory = make_pipeline_factory(args, model_dir, draft_dir)

    print(f"== Prefix-caching A/B (#711) == ov_genai={env['openvino_genai_version']}")
    print(f"   model={model_dir}")
    print(f"   angles={','.join(angles)} runs={args.runs} warmup={args.warmup} "
          f"cache_size={args.cache_size} cooldown={args.cooldown_s}s "
          f"steady_state={args.steady_state}")

    steady = warm_to_steady_state(factory, tok) if args.steady_state else None

    results: list[dict[str, Any]] = []
    for angle in angles:
        results.append(run_ab_angle(angle, factory, tok, core, args))

    not_measured = default_not_measured(angles, args.steady_state)
    if "S5" in angles:
        for rec in results:
            if rec["angle"] == "S5":
                on_arm = rec.get("on", {})
                if on_arm.get("acceptance_rate") == "unavailable":
                    not_measured.append(
                        "spec-decode acceptance % — this GenAI build does not "
                        "expose extended perf metrics; speedup ratio recorded "
                        "instead"
                    )
                break

    config = {
        "angles": list(angles),
        "runs": args.runs,
        "warmup": args.warmup,
        "cache_size": args.cache_size,
        "gen_tokens": args.gen_tokens,
        "s2_turns": args.s2_turns,
        "s5_gen_tokens": args.s5_gen_tokens,
        "prefix_tokens": args.prefix_tokens,
        "cooldown_s": args.cooldown_s,
        "steady_state": args.steady_state,
        "model_dir": str(model_dir),
        "draft_model_dir": str(draft_dir),
    }
    out = assemble_output(config=config, environment=env, results=results,
                          not_measured=not_measured, steady_state_warmup=steady)

    out_dir = Path(args.output_dir)
    out_dir = out_dir if out_dir.is_absolute() else (_REPO_ROOT / out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_ov = (env["openvino_genai_version"] or "unknown").split("-")[0].replace(".", "_")
    ts = time.strftime("%Y-%m-%d_%H-%M-%S")
    outpath = out_dir / f"{HARNESS_NAME}_ov{safe_ov}_{ts}.json"
    outpath.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\n[SAVE] {outpath}")

    print(format_summary(out))

    errored = [
        f"{r['angle']}/{label}"
        for r in results
        for label in ("off", "on")
        if isinstance(r.get(label), dict) and "error" in r[label]
    ]
    if errored:
        print(f"\nWARNING: {len(errored)} arm(s) errored: {', '.join(errored)} "
              "— JSON written; exit 1.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
