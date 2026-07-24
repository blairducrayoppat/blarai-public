"""
VLMPipeline Long-Context Decode-Curve Benchmark — Qwen3.6-35B-A3B (#932 / #930)
================================================================================
The consolidation research (#932) named the "35B long-context decode curve" as
an unmeasured unknown, and the status snapshot flags that NO protocol-clean
long-context instrument exists for the ``VLMPipeline`` class:
``scripts/benchmark_vlm_text_inference.py`` uses a fixed *short* prompt set
(256-token generations, tiny prompts), and ``scripts/kv_cache_sweep.py`` sweeps
context but on the ``LLMPipeline`` + KV-precision path (the resident 14B), not
the multimodal ``VLMPipeline`` class the 35B loads under. This script closes
that gap: it measures how decode throughput, prefill throughput, time-to-first-
token (TTFT) and memory behave as the *input context* grows, for the natively-
multimodal Qwen3.6-35B-A3B driven text-only.

WHY THE NUMBERS ARE COMPARABLE TO THE SHORT-CONTEXT 35B BENCH
------------------------------------------------------------
Comparability is a design goal, not an afterthought. This harness *imports and
reuses* the proven per-generation measurement primitive from
``scripts/benchmark_vlm_text_inference.py`` (``_measure_one``, its greedy
``GenerationConfig``, and the ``compute_median``/``compute_mean``/``compute_p95``
statistics) rather than re-deriving the timing math. The decode-throughput
definition is therefore byte-identical to the short-context 35B entries:
``tok/s = generated_tokens / (total_latency - ttft)``, greedy (do_sample=False),
``max_new_tokens`` = the short bench's value (256). The ONLY axis that changes
band-to-band is the *prompt length*; the generation length and timing logic are
held constant. A reviewer can place a long-context row beside a short-context
row and read the decode falloff directly.

WHAT IS MEASURED, PER CONTEXT BAND
----------------------------------
* decode throughput (tok/s) — median / mean / p95 over N measured runs after M
  warmup runs (the short bench's cadence);
* prefill (prompt-processing, "pp") throughput (tok/s) — DERIVED at the band's
  own length as ``actual_input_tokens / (ttft_seconds)``: at long context the
  band prompt *is* the prefill workload, so pp is read from the band generation
  itself rather than from a separate fixed short probe;
* TTFT (ms) — median, straight from the reused primitive;
* peak memory — BOTH disciplines: system In-Use = Total - Available (a
  background sampler, the RAM-accounting rule for this shared-memory box) AND
  process RSS (psutil.Process peak);
* a coherence spot-check — a fixed "needle" fact is planted near the START of
  the context and a question at the END asks the model to restate it and
  summarize. Full output text is captured for the REVIEWER to judge (coherence
  is never scored by this script, matching the short bench's #3870 stance). A
  cheap deterministic ``needle_recalled`` boolean rides along as a SUPPLEMENTARY
  signal only — it is not a quality gate.

THE MEMORY-CEILING STOP CONDITION (fail-closed, model-aware)
------------------------------------------------------------
The Arc 140V iGPU shares the 31.323 GiB system RAM, so a band that would breach
the ceiling must be REFUSED, not thrashed into a death-spiral. Before each band
this harness projects peak In-Use = (resident-after-load) + (analytical KV-cache
at that band) + working-set margin, and SKIPS the band (status
``skipped_memory_ceiling``) if the projection breaches the ceiling minus a
safety margin. Because the bands are monotone increasing, the first breach stops
the sweep.

CRITICAL MODEL FACT — the 35B is a HYBRID-attention MoE. Its ``config.json``
``text_config.layer_types`` shows only 10 of 40 layers are ``full_attention``;
the other 30 are ``linear_attention`` (recurrent/SSM-style, fixed-size state
that does NOT grow with context). The KV-cache growth term is therefore computed
from the FULL-ATTENTION layer count (read from ``layer_types``), NOT all 40
layers. A naive "all 40 layers" projection would over-estimate KV by ~4x and
could falsely skip a perfectly feasible 32K band. ``max_position_embeddings`` is
262144 (256K), so 2K-32K is well within trained context — the memory ceiling,
not the context limit, is the binding cap on this box.

DETERMINISM & POWER
-------------------
Greedy decode (temperature-0 equivalent). AC power is enforced fail-closed (a
battery-only run is refused) and the harness refuses to start if the BlarAI app
or a fleet model server appears to be holding the GPU. A pre-load memory-
headroom guard refuses to start a ~19 GiB load below a safe available-RAM floor
(the load-bearing 2026-06-21 lesson: check headroom BEFORE the load).

Usage (repo root, BlarAI runtime venv, app closed / AO stopped, LOCALAPPDATA
redirected if any pytest ran first):
  .venv\\Scripts\\python.exe scripts\\benchmark_vlm_longcontext.py
  .venv\\Scripts\\python.exe scripts\\benchmark_vlm_longcontext.py --bands 2048,8192,16384,32768
  .venv\\Scripts\\python.exe scripts\\benchmark_vlm_longcontext.py --runs 5 --warmup 2

Companion methodology note: ``docs/performance/README_vlm_longcontext.md``.
"""

from __future__ import annotations

import argparse
import gc
import json
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Protocol

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

# #816 Part 2: box-state stamp for the result JSON (shape-locked by
# tests/integration/test_perf_harness_env_capture.py — this harness is
# registered in that gate's _HARNESSES tuple).
from shared.perf_env_capture import capture_box_state  # noqa: E402

# Reuse the SHORT-context 35B measurement primitive verbatim so the long-context
# decode numbers are directly comparable (same timing math, same greedy config,
# same statistics). benchmark_vlm_text_inference guards its openvino imports, so
# importing it here never requires openvino to be present (pure helpers remain
# importable for the unit test).
import benchmark_vlm_text_inference as vlm_bench  # noqa: E402

try:
    import openvino as ov  # type: ignore[import-untyped]

    _OV_VERSION: str = ov.__version__
except ImportError:
    ov = None  # type: ignore[assignment]
    _OV_VERSION = "unavailable"

try:
    import openvino_genai as ov_genai  # type: ignore[import-untyped]

    _OV_GENAI_VERSION: str = ov_genai.__version__
except ImportError:
    ov_genai = None  # type: ignore[assignment]
    _OV_GENAI_VERSION = "unavailable"

try:
    import psutil  # type: ignore[import-untyped]
except ImportError:
    psutil = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_MODEL_DIR = "C:/Users/mrbla/models/qwen36-35b-a3b-int4-ov-OFFICIAL"
_DEVICE = "GPU"

#: Default context bands (input-prompt token targets). 2K/8K/16K/32K — a
#: doubling ladder that spans the short-bench regime up to a genuinely long
#: context, all well inside the model's 256K trained window. Larger bands are
#: gated by the memory ceiling, not the context limit, on this box.
DEFAULT_BANDS: tuple[int, ...] = (2048, 8192, 16384, 32768)

#: Effective system RAM ceiling (32 GB LPDDR5X - 693 MB firmware reservation),
#: the same constant the sibling memory harnesses use.
MEM_CEILING_GIB: float = 31.323

#: Pre-load available-RAM floor for the ~19 GiB INT4 35B load. A model load
#: transiently stages weights on CPU + GPU simultaneously, so available memory
#: must comfortably exceed the weight size before load (2026-06-21 lesson).
_HEADROOM_FLOOR_GB: float = 22.0

#: Working-set slack added to (weights + KV) when projecting a band's peak:
#: activations, the OpenVINO GPU allocator's headroom, and decode scratch. A
#: deliberate over-estimate so the guard never UNDER-projects and thrashes.
_WORKING_MARGIN_GIB: float = 2.0

#: Safety margin below the hard ceiling; a band is skipped if its projected peak
#: would land within this margin of 31.323 GiB.
_CEILING_SAFETY_GIB: float = 1.5

#: FP16 KV-cache elements (2 bytes). OpenVINO GenAI keeps the KV cache at the
#: inference precision by default; this harness does NOT sweep KV precision (see
#: kv_cache_sweep.py for that lever), so FP16 is the single, documented basis.
_KV_BYTES_PER_ELEM: int = 2

#: Geometry fallback if config.json cannot be read — the measured Qwen3.6-35B
#: hybrid geometry (10 full-attention layers of 40, 2 KV heads, 256 head_dim).
#: Named so the projection degrades to a documented value, never to a guess.
_GEOM_FALLBACK: dict[str, Any] = {
    "num_hidden_layers": 40,
    "full_attention_layers": 10,
    "num_key_value_heads": 2,
    "head_dim": 256,
    "max_position_embeddings": 262144,
    "layer_types_present": False,
}

# ---------------------------------------------------------------------------
# Coherence probe corpus — fixed & version-controlled so the prompt at a given
# band is byte-stable across runs and releases (the same discipline the short
# bench applies to its prefill probe). Neutral expository English, no code or
# unusual symbols, so the token count stays stable across tokenizer revisions.
# ---------------------------------------------------------------------------
PROMPT_CORPUS_VERSION: str = "lc-v1"
NEEDLE_VERSION: str = "ndl-v1"

#: The planted fact. Distinctive enough that it will not occur by chance in the
#: filler, so the supplementary needle_recalled check is meaningful.
_NEEDLE_ANSWER: str = "MERIDIAN-2718-ANCHOR"

_PREAMBLE: str = (
    "You are reading a long reference document. Read it carefully from start to "
    "finish. A single important fact is stated near the beginning; the question "
    "at the very end will ask you to recall it, so keep track of it as you read."
)

_NEEDLE: str = (
    f"IMPORTANT FACT TO REMEMBER: the archive access code for this document is "
    f"{_NEEDLE_ANSWER}. Do not lose track of this code; you will be asked for it "
    "at the end."
)

_CORPUS: str = (
    "On a memory bandwidth limited device such as an integrated graphics "
    "processor that shares system memory with the host, language model inference "
    "divides into two phases with very different behaviour. The first phase is "
    "prompt processing, also called prefill, in which the model reads and encodes "
    "every token of the input before producing a single new token. Prefill is "
    "compute bound and highly parallel, because the model processes all of the "
    "prompt tokens together in large batched matrix multiplications. The second "
    "phase is generation, in which each new token depends on the token produced "
    "before it, so the work is sequential and bound by how quickly the device can "
    "stream the model weights and the accumulated key value cache out of memory. "
    "As the context grows longer, the key value cache grows with it, and the "
    "amount of memory traffic per generated token rises, which is why generation "
    "throughput tends to fall as the prompt gets longer. Holding the wording of "
    "this passage constant across every run keeps the measured token counts "
    "comparable over time, in the same way that holding the generation prompts "
    "constant keeps the generation numbers comparable. "
)

_QUESTION: str = (
    "QUESTION: First, state the archive access code that was given near the "
    "beginning of this document. Then, in two or three sentences, summarize what "
    "the document explained about the two phases of language model inference."
)


# ===========================================================================
# Tokenizer protocol (so prompt construction is unit-testable with a fake)
# ===========================================================================
class TokenizerLike(Protocol):
    """The narrow slice of the HuggingFace tokenizer interface used here."""

    def __call__(self, text: str) -> Any: ...  # returns a mapping with "input_ids"

    def decode(self, ids: Any, skip_special_tokens: bool = ...) -> str: ...


def _count_tokens(tokenizer: TokenizerLike, text: str) -> int:
    """Token length of ``text`` under ``tokenizer`` (HF ``input_ids`` shape)."""
    return len(tokenizer(text)["input_ids"])


# ===========================================================================
# Pure helpers — prompt construction (no model / no openvino needed)
# ===========================================================================
def build_band_prompt(
    tokenizer: TokenizerLike, target_tokens: int
) -> tuple[str, int, str]:
    """Assemble a coherent long prompt targeting ``target_tokens`` input tokens.

    Layout is invariant regardless of band: ``preamble + needle + filler +
    question``. The needle (with the answer) sits at the START and the question
    at the END; only the neutral filler in the middle is grown/truncated to hit
    the band, so the coherence probe is identical across bands apart from
    document length.

    Returns ``(prompt, actual_token_count, needle_answer)``.
    """
    head = _PREAMBLE + "\n\n" + _NEEDLE + "\n\n"
    tail = "\n\n" + _QUESTION
    head_tail_tokens = _count_tokens(tokenizer, head + tail)
    budget = target_tokens - head_tail_tokens

    filler = ""
    if budget > 0:
        corpus_tokens = max(1, _count_tokens(tokenizer, _CORPUS))
        reps = (budget // corpus_tokens) + 2
        ids = tokenizer(_CORPUS * reps)["input_ids"][:budget]
        filler = tokenizer.decode(ids, skip_special_tokens=True)

    prompt = head + filler + tail
    actual = _count_tokens(tokenizer, prompt)
    return prompt, actual, _NEEDLE_ANSWER


def check_needle(output_text: str, needle_answer: str) -> bool:
    """Supplementary (NON-authoritative) recall signal: did the model echo the
    planted code? Case-insensitive substring. The reviewer judges real
    coherence from the captured text; this is only a cheap deterministic flag.
    """
    return needle_answer.strip().lower() in (output_text or "").lower()


# ===========================================================================
# Pure helpers — model geometry & the memory-ceiling projection
# ===========================================================================
def load_geometry(model_dir: str | Path) -> dict[str, Any]:
    """Read the KV-relevant geometry from the model's ``config.json``.

    Handles the Qwen3.6 hybrid-attention MoE shape: geometry lives under
    ``text_config``, and only ``layer_types == "full_attention"`` layers keep a
    growing KV cache (the ``linear_attention`` layers hold a fixed recurrent
    state that does not scale with context). Returns :data:`_GEOM_FALLBACK` on
    any read failure so the projection always has a documented basis.
    """
    try:
        cfg_path = Path(model_dir) / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — a missing/broken config degrades to fallback
        return dict(_GEOM_FALLBACK)

    text_cfg = cfg.get("text_config", cfg)
    layer_types = text_cfg.get("layer_types")
    full_attention_layers: int | None
    if isinstance(layer_types, list) and layer_types:
        full_attention_layers = sum(1 for t in layer_types if t == "full_attention")
    else:
        full_attention_layers = None

    return {
        "num_hidden_layers": int(text_cfg.get("num_hidden_layers", 40)),
        "full_attention_layers": full_attention_layers,
        "num_key_value_heads": int(text_cfg.get("num_key_value_heads", 2)),
        "head_dim": int(text_cfg.get("head_dim", 256)),
        "max_position_embeddings": int(text_cfg.get("max_position_embeddings", 262144)),
        "layer_types_present": isinstance(layer_types, list) and bool(layer_types),
    }


def kv_layer_count(geom: dict[str, Any]) -> int:
    """Number of layers whose KV cache GROWS with context.

    Prefers the counted ``full_attention`` layers; falls back to the total layer
    count (a conservative over-estimate) only when ``layer_types`` was absent.
    """
    n_full = geom.get("full_attention_layers")
    if isinstance(n_full, int) and n_full > 0:
        return n_full
    return int(geom.get("num_hidden_layers", 40))


def analytical_kv_gib(
    context_tokens: int, geom: dict[str, Any], bytes_per_elem: int = _KV_BYTES_PER_ELEM
) -> float:
    """Analytical KV-cache size in GiB for a full context of ``context_tokens``.

    ``bytes/token = kv_layers * kv_heads * head_dim * 2 (K and V) * bytes``. This
    is an order-of-magnitude PROJECTION for the fail-closed pre-band guard, not a
    measurement — the live sampler records the true peak. It counts only the
    growing (full-attention) layers for the hybrid 35B (see :func:`kv_layer_count`).
    """
    bytes_per_token = (
        kv_layer_count(geom)
        * int(geom["num_key_value_heads"])
        * int(geom["head_dim"])
        * 2
        * bytes_per_elem
    )
    return (bytes_per_token * context_tokens) / (1024.0**3)


def project_peak_used_gib(
    used_after_load_gib: float,
    band_tokens: int,
    geom: dict[str, Any],
    working_margin_gib: float = _WORKING_MARGIN_GIB,
) -> float:
    """Projected peak system In-Use for a band = resident-after-load + analytical
    KV at the band + working-set margin. All GiB.
    """
    return used_after_load_gib + analytical_kv_gib(band_tokens, geom) + working_margin_gib


@dataclass
class BandPlan:
    """The admit/skip decision for one context band (pure, pre-execution)."""

    target_tokens: int
    admitted: bool
    skip_reason: str | None
    projected_peak_gib: float | None
    kv_gib: float | None


def plan_bands(
    bands: list[int],
    geom: dict[str, Any],
    used_after_load_gib: float,
    ceiling_gib: float = MEM_CEILING_GIB,
    safety_gib: float = _CEILING_SAFETY_GIB,
    working_margin_gib: float = _WORKING_MARGIN_GIB,
) -> list[BandPlan]:
    """Decide, band by band (ascending), which bands are safe to run.

    A band is skipped ``over_max_context`` if it exceeds the trained window, or
    ``memory_ceiling`` if its projected peak lands within ``safety_gib`` of the
    hard ceiling. Because both KV size and prompt length grow monotonically with
    the band, once one band trips the ceiling every larger band is skipped too
    (``memory_ceiling_after_prior``) — the sweep stops rather than thrashes.
    """
    plans: list[BandPlan] = []
    max_ctx = int(geom.get("max_position_embeddings", 262144))
    stopped = False
    for band in sorted(bands):
        kv = analytical_kv_gib(band, geom)
        projected = project_peak_used_gib(used_after_load_gib, band, geom, working_margin_gib)
        if stopped:
            plans.append(BandPlan(band, False, "memory_ceiling_after_prior", round(projected, 3), round(kv, 3)))
            continue
        if band > max_ctx:
            plans.append(BandPlan(band, False, "over_max_context", round(projected, 3), round(kv, 3)))
            stopped = True
            continue
        if projected > (ceiling_gib - safety_gib):
            plans.append(BandPlan(band, False, "memory_ceiling", round(projected, 3), round(kv, 3)))
            stopped = True
            continue
        plans.append(BandPlan(band, True, None, round(projected, 3), round(kv, 3)))
    return plans


# ===========================================================================
# Pure helpers — power, refuse-to-start, git, hardware
# ===========================================================================
def detect_power_envelope() -> dict[str, Any]:
    """AC/battery state via psutil. Never raises."""
    state: dict[str, Any] = {
        "sensor_available": False,
        "power_plugged": None,
        "battery_percent": None,
    }
    if psutil is None:
        return state
    try:
        battery = psutil.sensors_battery()
    except Exception as exc:  # noqa: BLE001
        state["sensor_error"] = str(exc)
        return state
    if battery is None:
        return state
    state["sensor_available"] = True
    state["power_plugged"] = bool(battery.power_plugged)
    state["battery_percent"] = (
        float(battery.percent) if battery.percent is not None else None
    )
    return state


def enforce_ac_power_or_fail_closed() -> dict[str, Any]:
    """Refuse to run on battery (thermal/clock variance would poison the curve).

    Mirrors ``phase2_gates/.../run_p5_task4_3_nat_sweep.py`` — replicated locally
    (~15 lines) rather than imported, because that module imports openvino_genai
    unguarded at top and would defeat this harness's guarded-import testability.
    """
    state = detect_power_envelope()
    if state.get("sensor_available") and state.get("power_plugged") is False:
        raise RuntimeError(
            "AC_POWER_REQUIRED: battery-only operation detected — fail closed "
            "per benchmark mandate"
        )
    return state


def _port_held(port: int, host: str = "127.0.0.1") -> bool:
    """True if something already holds ``host:port`` (bind fails)."""
    if psutil is None:
        return False
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
        return False
    except OSError:
        return True
    finally:
        sock.close()


def gpu_hold_reasons(
    ao_port: int = 5001, port_probe: Callable[[int], bool] = _port_held
) -> list[str]:
    """Reasons the GPU appears held (refuse-to-start, #711 policy: fail loud,
    never queue behind a live app / fleet model server)."""
    reasons: list[str] = []
    if port_probe(ao_port):
        reasons.append(
            f"port {ao_port} (AO loopback) responding — the BlarAI app appears "
            "up and holding the GPU"
        )
    if psutil is not None:
        hits = sorted(
            {
                (p.info.get("name") or "")
                for p in psutil.process_iter(["name"])
                if "ovms" in (p.info.get("name") or "").lower()
            }
        )
        if hits:
            reasons.append("OVMS process(es) alive: " + ", ".join(hits))
    return reasons


def git_head() -> str:
    """Current commit SHA, or ``UNKNOWN``."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=_REPO_ROOT, text=True
        ).strip()
    except Exception:  # noqa: BLE001
        return "UNKNOWN"


def _gpu_driver_version() -> str:
    """Arc GPU driver version via WMI (community-grade metadata)."""
    try:
        out = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-CimInstance Win32_VideoController | Where-Object "
                "{ $_.Name -match 'Arc' } | Select-Object -First 1 "
                "-ExpandProperty DriverVersion)",
            ],
            capture_output=True,
            text=True,
            timeout=25,
        )
        return out.stdout.strip() or "unavailable"
    except Exception:  # noqa: BLE001
        return "unavailable"


def capture_hardware() -> dict[str, Any]:
    """Community-grade hardware/version record (CPU, GPU, driver, RAM, versions)."""
    import platform

    env: dict[str, Any] = {
        "cpu": "Intel Core Ultra 7 258V (Lunar Lake)",
        "cpu_platform": platform.processor() or platform.machine(),
        "os": f"{platform.system()} {platform.version()}",
        "python": platform.python_version(),
        "openvino_version": _OV_VERSION,
        "openvino_genai_version": _OV_GENAI_VERSION,
        "ram_spec": "32 GB LPDDR5X (shared CPU/iGPU)",
        "total_ram_gib": (
            round(psutil.virtual_memory().total / (1024.0**3), 2)
            if psutil is not None
            else None
        ),
        "mem_ceiling_gib": MEM_CEILING_GIB,
        "gpu": "Intel(R) Arc(TM) 140V GPU (16GB) (iGPU)",
        "gpu_uarch": None,
        "gpu_driver": _gpu_driver_version(),
    }
    if ov is not None:
        try:
            core = ov.Core()
            env["gpu"] = str(core.get_property("GPU", "FULL_DEVICE_NAME"))
        except Exception:  # noqa: BLE001
            pass
        try:
            core = ov.Core()
            env["gpu_uarch"] = str(core.get_property("GPU", "GPU_UARCH_VERSION"))
        except Exception:  # noqa: BLE001
            pass
    return env


# ===========================================================================
# Memory sampler — BOTH disciplines at once (system In-Use + process RSS)
# ===========================================================================
class DualMemorySampler:
    """Background thread sampling system Available RAM AND process RSS.

    ``peak_used_gib`` = Total - min(Available) over the window (the In-Use rule
    for this shared-memory box). ``peak_rss_mb`` = max process RSS. ``min_avail
    _gib`` records how close the run came to exhausting RAM.
    """

    def __init__(self, interval_s: float = 0.05) -> None:
        self._interval_s = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        if psutil is not None:
            vm = psutil.virtual_memory()
            self._total = float(vm.total)
            self._min_avail = float(vm.available)
            self._proc = psutil.Process()
            self._peak_rss = float(self._proc.memory_info().rss)
        else:
            self._total = 0.0
            self._min_avail = 0.0
            self._proc = None
            self._peak_rss = 0.0

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                avail = float(psutil.virtual_memory().available)
                if avail < self._min_avail:
                    self._min_avail = avail
                if self._proc is not None:
                    rss = float(self._proc.memory_info().rss)
                    if rss > self._peak_rss:
                        self._peak_rss = rss
            except Exception:  # noqa: BLE001 — sampling must never crash the run
                pass
            time.sleep(self._interval_s)

    def start(self) -> None:
        if psutil is None:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    @property
    def peak_used_gib(self) -> float:
        if psutil is None:
            return -1.0
        return (self._total - self._min_avail) / (1024.0**3)

    @property
    def peak_rss_mb(self) -> float:
        return self._peak_rss / (1024.0**2)

    @property
    def min_avail_gib(self) -> float:
        if psutil is None:
            return -1.0
        return self._min_avail / (1024.0**3)


# ===========================================================================
# Per-band measurement
# ===========================================================================
@dataclass
class BandResult:
    """Aggregated measurement for one context band."""

    band_target_tokens: int
    band_actual_input_tokens: int
    status: str
    skip_reason: str | None
    projected_peak_gib: float | None
    kv_gib: float | None
    decode: dict[str, Any] = field(default_factory=dict)
    ttft: dict[str, Any] = field(default_factory=dict)
    prefill_pp: dict[str, Any] = field(default_factory=dict)
    memory: dict[str, Any] = field(default_factory=dict)
    coherence: dict[str, Any] = field(default_factory=dict)
    runs: list[dict[str, Any]] = field(default_factory=list)


def measure_band(
    pipe: object,
    prompt: str,
    actual_input_tokens: int,
    plan: BandPlan,
    runs: int,
    warmup: int,
    cooldown_s: float,
    needle_answer: str,
) -> BandResult:
    """Warmup then N measured greedy generations at one band, sampling memory.

    Decode/TTFT come from the reused short-bench primitive (``_measure_one``);
    prefill pp is derived per run as ``actual_input_tokens / ttft_seconds``.
    """
    for w in range(warmup):
        print(f"    warmup {w + 1}/{warmup} (band {plan.target_tokens}) ...")
        vlm_bench._measure_one(pipe, prompt, plan.target_tokens)

    per_run: list[dict[str, Any]] = []
    tps_vals: list[float] = []
    ttft_vals: list[float] = []
    pp_vals: list[float] = []
    peak_used_vals: list[float] = []
    peak_rss_vals: list[float] = []
    min_avail_vals: list[float] = []
    output_texts: list[str] = []
    needle_flags: list[bool] = []

    for r in range(runs):
        sampler = DualMemorySampler()
        sampler.start()
        m = vlm_bench._measure_one(pipe, prompt, plan.target_tokens)
        sampler.stop()

        ttft_ms = m.latency_first_token_ms
        pp = (
            actual_input_tokens / (ttft_ms / 1000.0)
            if ttft_ms > 0 and actual_input_tokens > 0
            else 0.0
        )
        recalled = check_needle(m.output_text, needle_answer)
        run_row: dict[str, Any] = {
            "run_index": r,
            "error": m.error,
            "generated_tokens": m.token_count,
            "decode_tok_per_sec": round(m.throughput_tok_per_sec, 3),
            "ttft_ms": round(ttft_ms, 1),
            "prefill_pp_tok_per_sec": round(pp, 1),
            "total_ms": round(m.latency_total_ms, 1),
            "peak_used_gib": round(sampler.peak_used_gib, 3),
            "peak_rss_mb": round(sampler.peak_rss_mb, 1),
            "min_avail_gib": round(sampler.min_avail_gib, 3),
            "needle_recalled": recalled,
        }
        per_run.append(run_row)

        if m.error is None and m.token_count > 0:
            tps_vals.append(m.throughput_tok_per_sec)
            if ttft_ms > 0:
                ttft_vals.append(ttft_ms)
                pp_vals.append(pp)
            peak_used_vals.append(sampler.peak_used_gib)
            peak_rss_vals.append(sampler.peak_rss_mb)
            min_avail_vals.append(sampler.min_avail_gib)
            output_texts.append(m.output_text)
            needle_flags.append(recalled)

        status = m.error or (
            f"{m.token_count} tok, {m.throughput_tok_per_sec:.1f} tok/s, "
            f"ttft {ttft_ms:.0f}ms, peak_used {sampler.peak_used_gib:.2f}GiB, "
            f"needle={'Y' if recalled else 'N'}"
        )
        print(f"    run {r + 1}/{runs} (band {plan.target_tokens}): {status}")
        if r < runs - 1 and cooldown_s > 0:
            time.sleep(cooldown_s)
        gc.collect()

    ok_count = len(tps_vals)
    result = BandResult(
        band_target_tokens=plan.target_tokens,
        band_actual_input_tokens=actual_input_tokens,
        status="completed" if ok_count > 0 else "all_failed",
        skip_reason=None,
        projected_peak_gib=plan.projected_peak_gib,
        kv_gib=plan.kv_gib,
        runs=per_run,
    )
    result.decode = {
        "median_tok_per_sec": round(vlm_bench.compute_median(tps_vals), 3),
        "mean_tok_per_sec": round(vlm_bench.compute_mean(tps_vals), 3),
        "p95_tok_per_sec": round(vlm_bench.compute_p95(tps_vals), 3),
        "n": ok_count,
    }
    result.ttft = {
        "median_ms": round(vlm_bench.compute_median(ttft_vals), 1),
        "mean_ms": round(vlm_bench.compute_mean(ttft_vals), 1),
        "n": len(ttft_vals),
    }
    result.prefill_pp = {
        "median_tok_per_sec": round(vlm_bench.compute_median(pp_vals), 1),
        "mean_tok_per_sec": round(vlm_bench.compute_mean(pp_vals), 1),
        "derivation": "actual_input_tokens / ttft_seconds",
        "n": len(pp_vals),
    }
    result.memory = {
        "peak_used_gib_system": round(max(peak_used_vals), 3) if peak_used_vals else None,
        "peak_rss_mb": round(max(peak_rss_vals), 1) if peak_rss_vals else None,
        "sys_available_min_gib": round(min(min_avail_vals), 3) if min_avail_vals else None,
        "discipline": "In-Use = Total - Available (system) + process RSS",
    }
    result.coherence = {
        "needle_answer": needle_answer,
        "needle_recalled_count": sum(1 for f in needle_flags if f),
        "needle_recalled_of": len(needle_flags),
        "needle_recall_is_authoritative": False,
        "note": (
            "Full output texts are the reviewer's coherence evidence; the "
            "needle flag is a supplementary deterministic signal only."
        ),
        "output_texts": output_texts,
    }
    return result


# ===========================================================================
# Main
# ===========================================================================
def _parse_bands(raw: str) -> list[int]:
    return [int(x) for x in raw.split(",") if x.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="VLMPipeline long-context decode-curve benchmark")
    parser.add_argument("--model-dir", default=DEFAULT_MODEL_DIR)
    parser.add_argument(
        "--bands",
        default=",".join(str(b) for b in DEFAULT_BANDS),
        help="Comma-separated input-token context bands (ascending).",
    )
    parser.add_argument("--runs", type=int, default=5, help="Measured runs per band.")
    parser.add_argument("--warmup", type=int, default=2, help="Warmup runs per band.")
    parser.add_argument(
        "--cooldown",
        type=float,
        default=15.0,
        help="Seconds between measured runs (thermal settle).",
    )
    parser.add_argument(
        "--force", action="store_true", help="Skip the pre-load memory headroom guard."
    )
    parser.add_argument(
        "--allow-gpu-held",
        action="store_true",
        help="Skip the refuse-to-start GPU-hold guard (NOT for real measurement).",
    )
    args = parser.parse_args()

    # #816 Part 2: stamp the box state AT RUN START — before any guard or model
    # load shifts it. Fail-soft: a probe failure stamps "unknown", never breaks.
    box_state_at_start = capture_box_state()

    if ov_genai is None:
        print("FATAL: openvino_genai is not importable in this environment.")
        return 2

    bands = _parse_bands(args.bands)
    if not bands:
        print("FATAL: no bands parsed from --bands.")
        return 2

    model_dir = Path(args.model_dir).resolve()
    if not (model_dir / "openvino_language_model.xml").exists():
        print(f"FATAL: no openvino_language_model.xml under {model_dir}")
        return 2

    # Refuse-to-start if the GPU appears held (fail loud, never queue).
    if not args.allow_gpu_held:
        held = gpu_hold_reasons()
        if held:
            print("FATAL: the GPU appears held — refusing to start (#711 policy):")
            for reason in held:
                print(f"  - {reason}")
            return 3

    # AC power fail-closed.
    try:
        power = enforce_ac_power_or_fail_closed()
    except RuntimeError as exc:
        print(f"FATAL: {exc}")
        return 3
    print(f"Power: plugged={power.get('power_plugged')}, battery={power.get('battery_percent')}%")

    # Pre-load headroom guard (the ~19 GiB 35B load).
    available_gb = vlm_bench._sys_available_gb()
    if not args.force and 0 <= available_gb < _HEADROOM_FLOOR_GB:
        print(
            f"ABORT: system available memory {available_gb:.1f} GiB is below the "
            f"{_HEADROOM_FLOOR_GB:.0f} GiB pre-load floor for the ~19 GiB 35B load. "
            "Close the BlarAI app / stop the AO / lean the box, then re-run "
            "(--force overrides, accepting the death-spiral risk)."
        )
        return 3

    geom = load_geometry(model_dir)
    print(
        f"Geometry: {geom['num_hidden_layers']} layers, "
        f"{geom.get('full_attention_layers')} full-attention (KV-growing), "
        f"{geom['num_key_value_heads']} KV heads, head_dim {geom['head_dim']}, "
        f"max_ctx {geom['max_position_embeddings']}"
    )

    print(
        f"Loading {model_dir.name} on {_DEVICE} "
        f"(OV {_OV_VERSION} / GenAI {_OV_GENAI_VERSION})"
    )
    mem_before_load = vlm_bench._sys_available_gb()
    t_load = time.perf_counter()
    pipe = ov_genai.VLMPipeline(str(model_dir), _DEVICE)
    load_s = time.perf_counter() - t_load
    mem_after_load = vlm_bench._sys_available_gb()
    total_gib = (
        psutil.virtual_memory().total / (1024.0**3) if psutil is not None else 0.0
    )
    used_after_load_gib = total_gib - mem_after_load if mem_after_load >= 0 else -1.0
    print(
        f"Loaded in {load_s:.1f}s; available {mem_before_load:.1f} -> "
        f"{mem_after_load:.1f} GiB (resident-after-load ~{used_after_load_gib:.1f} GiB)"
    )

    # Plan bands against the measured resident footprint + the ceiling.
    plans = plan_bands(bands, geom, max(used_after_load_gib, 0.0))
    for plan in plans:
        verdict = (
            "ADMIT"
            if plan.admitted
            else f"SKIP({plan.skip_reason})"
        )
        print(
            f"  band {plan.target_tokens}: {verdict} | KV~{plan.kv_gib} GiB | "
            f"projected peak ~{plan.projected_peak_gib} GiB"
        )

    # Build prompts (with the injected real tokenizer).
    from transformers import AutoTokenizer  # noqa: E402 — lazy: keeps helpers importable

    tokenizer = AutoTokenizer.from_pretrained(str(model_dir), trust_remote_code=True)

    band_results: list[BandResult] = []
    for plan in plans:
        if not plan.admitted:
            band_results.append(
                BandResult(
                    band_target_tokens=plan.target_tokens,
                    band_actual_input_tokens=0,
                    status="skipped",
                    skip_reason=plan.skip_reason,
                    projected_peak_gib=plan.projected_peak_gib,
                    kv_gib=plan.kv_gib,
                )
            )
            print(f"\n=== band {plan.target_tokens}: SKIPPED ({plan.skip_reason}) ===")
            continue

        prompt, actual_tokens, needle_answer = build_band_prompt(tokenizer, plan.target_tokens)
        print(
            f"\n=== band {plan.target_tokens} (actual {actual_tokens} input tokens) ==="
        )
        result = measure_band(
            pipe,
            prompt,
            actual_tokens,
            plan,
            runs=args.runs,
            warmup=args.warmup,
            cooldown_s=args.cooldown,
            needle_answer=needle_answer,
        )
        band_results.append(result)
        print(
            f"  -> decode median {result.decode['median_tok_per_sec']} tok/s | "
            f"pp median {result.prefill_pp['median_tok_per_sec']} tok/s | "
            f"ttft median {result.ttft['median_ms']} ms | "
            f"peak_used {result.memory['peak_used_gib_system']} GiB"
        )

    summary: dict[str, Any] = {
        "benchmark": "vlm_longcontext_decode_curve",
        "model": model_dir.name,
        "model_precision": "INT4 (OpenVINO IR)",
        "device": _DEVICE,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "commit": git_head(),
        "openvino_version": _OV_VERSION,
        "openvino_genai_version": _OV_GENAI_VERSION,
        # #816 Part 2: box state this run was measured under (start anchor + end).
        "environment": {
            "box_state_at_start": box_state_at_start,
            "box_state_at_end": capture_box_state(),
            "hardware": capture_hardware(),
            "power_envelope": power,
        },
        "model_geometry": geom,
        "methodology": {
            "bands_requested": bands,
            "prompt_corpus_version": PROMPT_CORPUS_VERSION,
            "needle_version": NEEDLE_VERSION,
            "prompt_construction": (
                "preamble + planted needle (start) + neutral filler grown/"
                "truncated to the band + question (end); only the middle filler "
                "varies across bands"
            ),
            "warmup_runs": args.warmup,
            "measured_runs": args.runs,
            "cooldown_s": args.cooldown,
            "max_new_tokens": vlm_bench.MAX_NEW_TOKENS,
            "decode_metric": "generated_tokens / (total_latency - ttft) [reused from benchmark_vlm_text_inference._measure_one]",
            "prefill_metric": "actual_input_tokens / ttft_seconds (derived at band length)",
            "memory_metric": "In-Use = Total - Available (system sampler) + process RSS peak",
            "greedy": True,
            "kv_cache_precision": "FP16 default (this harness does NOT sweep KV precision)",
            "model_max_context": geom["max_position_embeddings"],
            "memory_ceiling_gib": MEM_CEILING_GIB,
            "memory_stop_condition": (
                "per-band projected peak = resident-after-load + analytical KV "
                "(full-attention layers only) + working margin; skip if within "
                f"{_CEILING_SAFETY_GIB} GiB of the {MEM_CEILING_GIB} GiB ceiling"
            ),
            "comparability": (
                "decode/TTFT timing + statistics reused verbatim from "
                "scripts/benchmark_vlm_text_inference.py so long-context rows are "
                "directly comparable to the short-context 35B entries"
            ),
        },
        "load": {
            "load_seconds": round(load_s, 1),
            "sys_available_gib_before_load": round(mem_before_load, 2),
            "sys_available_gib_after_load": round(mem_after_load, 2),
            "resident_after_load_gib": round(used_after_load_gib, 2),
        },
        "bands": [asdict(b) for b in band_results],
        "not_measured": [
            "vision / image inputs (text-only probe)",
            "speculative decoding (does not exist for the VLMPipeline class/model family)",
            "co-resident cost (benchmarked alone, GPU free)",
            "KV-cache precision alternatives (FP16 default only; see kv_cache_sweep.py)",
            "coherence/answer QUALITY as a scored metric (captured for reviewer; needle flag is supplementary only)",
            "context bands beyond the highest completed band (memory-ceiling stopped)",
            "concurrent-request / batched throughput (single sequential request)",
        ],
    }

    out_dir = _REPO_ROOT / "docs" / "performance"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    out_path = out_dir / f"vlm_longcontext_{model_dir.name}_{stamp}.json"
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("\n" + "=" * 64)
    print(f"=== {model_dir.name} long-context decode curve ({_DEVICE}) ===")
    for b in band_results:
        if b.status == "completed":
            print(
                f"  {b.band_target_tokens:>6} tok (actual {b.band_actual_input_tokens}): "
                f"decode {b.decode['median_tok_per_sec']} tok/s | "
                f"pp {b.prefill_pp['median_tok_per_sec']} tok/s | "
                f"ttft {b.ttft['median_ms']} ms | "
                f"peak_used {b.memory['peak_used_gib_system']} GiB | "
                f"needle {b.coherence['needle_recalled_count']}/{b.coherence['needle_recalled_of']}"
            )
        else:
            print(f"  {b.band_target_tokens:>6} tok: {b.status} ({b.skip_reason})")
    print(f"results: {out_path}")

    del pipe
    gc.collect()
    any_ok = any(b.status == "completed" for b in band_results)
    return 0 if any_ok else 1


if __name__ == "__main__":
    sys.exit(main())
