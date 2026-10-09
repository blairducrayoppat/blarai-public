"""Speed bench: Qwen3.5 INT8 (+MTP) vs the shipped Qwen3-14B INT4 + 0.6B draft.

Arms (``--arms``):
  <size>-mtp-off, <size>-mtp-on, <size>-prefix-cache  (size 4b or 9b, see
                                            phase1_sizes.SIZES; each size loads
                                            its own --model-<size> directory)
                                          -> evals.cb_pipeline.CBEnginePipeline
  14b-ship                                -> ov_genai.LLMPipeline + pruned-0.6B
                                             draft + prefix caching ON, built as
                                             shared_pipeline's text path builds it.

Cells (``--cells``): ``pa`` (production Policy-Agent prompt, 16 new tokens),
``ao-long`` (~6000 input tokens, 128 new), ``multiturn`` (6 turns, 48 new each).
Prompts are fixed text (the multi-turn history uses scripted assistant turns, so
every arm and round sees byte-identical prompts); token counts are measured with
each arm's own tokenizer and recorded. All generation is greedy with
``apply_chat_template=False`` and the closed empty think block.

Protocol: per round, each arm is loaded in turn (start arm rotates by round), one
discarded warm-up generation (a neutral prompt unrelated to any cell, so prefix
caching is not pre-populated with a cell), every cell once, unload, then wait for
In-Use RAM to return to within 1 GB of the pre-run baseline (cap 90 s).

The pure helpers (statistics, MDE, identity, ratio refusal) import no openvino.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import gc
import hashlib
import json
import math
import os
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))  # sample_system (read_thermal)

import phase1_sizes as sizes  # noqa: E402

ARMS_4B = sizes.cb_arms("4b")
ARM_14B = sizes.ARM_14B
ALL_ARMS = ARMS_4B + (ARM_14B,)  # the --arms default
KNOWN_ARMS = sizes.all_arms(tuple(sizes.SIZES))
ALL_CELLS = ("pa", "ao-long", "multiturn")
CV_LIMIT_PCT = 15.0
MULTITURN_TURNS = 6
HEAT_CAP = 40
MEM_RETURN_GB = 1.0
MEM_WAIT_S = 90.0
AO_TARGET_TOKENS = 6000
EMPTY_THINK = "<think>\n\n</think>\n\n"

MDE_FORMULA = (
    "mde_tps = 2 * pooled_sd / sqrt(n); pooled_sd = sqrt(mean(sd_i^2)) over the "
    "per-(arm,cell) decode tok/s standard deviations that have n>=2; n = the "
    "smallest per-cell sample count. An effect in decode tok/s below this is not "
    "a finding."
)


# ---------------------------------------------------------------------------
# Pure helpers (no openvino)
# ---------------------------------------------------------------------------


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def describe(values: list[float]) -> dict[str, Any]:
    """n, mean, sample sd (ddof=1), CV%. sd/CV are None when n < 2 or mean == 0."""
    vals = [float(v) for v in values if v is not None]
    n = len(vals)
    if n == 0:
        return {"n": 0, "mean": None, "sd": None, "cv_pct": None}
    mean = statistics.fmean(vals)
    sd = statistics.stdev(vals) if n >= 2 else None
    cv = (sd / abs(mean) * 100.0) if (sd is not None and mean) else None
    return {
        "n": n,
        "mean": round(mean, 4),
        "sd": None if sd is None else round(sd, 4),
        "cv_pct": None if cv is None else round(cv, 2),
    }


def min_detectable_effect(sds: list[float | None], n: int) -> float | None:
    """2 * pooled_sd / sqrt(n); None when no usable sd or n < 2."""
    usable = [s for s in sds if s is not None]
    if not usable or n < 2:
        return None
    pooled = math.sqrt(statistics.fmean([s * s for s in usable]))
    return round(2.0 * pooled / math.sqrt(n), 4)


def identity_group(hashes: list[str]) -> dict[str, Any]:
    """Byte-identity of a set of output hashes."""
    distinct = sorted(set(hashes))
    return {
        "n": len(hashes),
        "identical": len(distinct) == 1 if hashes else None,
        "n_distinct": len(distinct),
    }


def cross_identity(a_hashes: list[str], b_hashes: list[str]) -> dict[str, Any]:
    """Whether two arms produced the same single output on a cell."""
    sa, sb = set(a_hashes), set(b_hashes)
    return {
        "identical": bool(sa) and len(sa) == 1 and sa == sb,
        "a_distinct": len(sa),
        "b_distinct": len(sb),
        "shared_hashes": len(sa & sb),
    }


def ratio_or_refuse(
    num: dict[str, Any], den: dict[str, Any], cv_limit: float = CV_LIMIT_PCT
) -> dict[str, Any]:
    """num.mean / den.mean, refused when either side is unstable or unmeasured."""
    for side in (num, den):
        cv = side.get("cv_pct")
        if side.get("mean") in (None, 0) or cv is None or cv > cv_limit:
            return {"ratio": None, "status": "unstable: no ratio"}
    return {"ratio": round(num["mean"] / den["mean"], 4), "status": "ok"}


def plateau_reached(tpots: list[float], window: int = 4, tol: float = 0.05, min_n: int = 8) -> bool:
    """True when >= ``min_n`` values exist and every one of the last ``window``
    is within ``tol`` (fraction) of their mean."""
    vals = [float(v) for v in tpots if v is not None]
    if len(vals) < max(min_n, window):
        return False
    tail = vals[-window:]
    mean = statistics.fmean(tail)
    return bool(mean) and all(abs(v - mean) / mean <= tol for v in tail)


def wait_for_cold(
    read_thermal_fn,
    target_c: float,
    max_wait_s: float,
    clock=time.time,
    sleep=time.sleep,
    poll_s: float = 2.0,
) -> dict[str, Any]:
    """Wait until ``temp_c <= target_c`` or ``max_wait_s``. Absent temp = NOT MEASURED."""
    t0 = clock()
    while True:
        temp = (read_thermal_fn() or {}).get("temp_c")
        waited = clock() - t0
        if temp is None:
            return {"waited_s": round(waited, 1), "temp_c": None, "reached": None, "measured": False}
        if temp <= target_c:
            return {"waited_s": round(waited, 1), "temp_c": temp, "reached": True, "measured": True}
        if waited >= max_wait_s:
            return {"waited_s": round(waited, 1), "temp_c": temp, "reached": False, "measured": True}
        sleep(poll_s)


def _summarize_protocol(valid: list[dict[str, Any]]) -> dict[str, Any]:
    cells: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for r in valid:
        cells.setdefault(r["arm"], {}).setdefault(r["cell"], []).append(r)

    per_cell: dict[str, dict[str, Any]] = {}
    for arm, by_cell in cells.items():
        per_cell[arm] = {}
        for cell, rs in sorted(by_cell.items()):
            visits: dict[int, list[dict[str, Any]]] = {}
            for r in rs:
                visits.setdefault(int(r.get("visit", 0)), []).append(r)
            vm_tps = {v: describe([x["decode_tps"] for x in vr if x.get("decode_tps") is not None])["mean"]
                      for v, vr in sorted(visits.items())}
            vm_ttft = {v: describe([x["ttft_ms"] for x in vr if x.get("ttft_ms") is not None])["mean"]
                       for v, vr in sorted(visits.items())}
            per_cell[arm][cell] = {
                "ttft_ms": describe([r["ttft_ms"] for r in rs if r.get("ttft_ms") is not None]),
                "decode_tps": describe([r["decode_tps"] for r in rs if r.get("decode_tps") is not None]),
                "output_identity": identity_group([r["output_sha256"] for r in rs]),
                "per_visit_mean_decode_tps": {str(k): v for k, v in vm_tps.items()},
                "visit_cv_pct_decode_tps": describe([v for v in vm_tps.values() if v is not None])["cv_pct"],
                "per_visit_mean_ttft_ms": {str(k): v for k, v in vm_ttft.items()},
                "visit_cv_pct_ttft_ms": describe([v for v in vm_ttft.values() if v is not None])["cv_pct"],
            }
    arm_identity = {
        arm: identity_group([r["output_sha256"] for rs in by_cell.values() for r in rs])
        for arm, by_cell in cells.items()
    }
    # ``mtp_off_vs_on_identity`` is the 4b size's (the Phase 1 key); every other
    # size reports under ``mtp_off_vs_on_identity_<size>``, never under the 4b key.
    mtp_cmp: dict[str, Any] = {}
    mtp_cmp_other: dict[str, dict[str, Any]] = {}
    for size in sizes.SIZES:
        off = cells.get(sizes.arm_name(size, "mtp-off"), {})
        on = cells.get(sizes.arm_name(size, "mtp-on"), {})
        cmp_size = {
            cell: cross_identity([r["output_sha256"] for r in off[cell]], [r["output_sha256"] for r in on[cell]])
            for cell in sorted(set(off) & set(on))
        }
        if size == "4b":
            mtp_cmp = cmp_size
        elif cmp_size:
            mtp_cmp_other[f"mtp_off_vs_on_identity_{size}"] = cmp_size
    sds, ns = [], []
    for arm in per_cell.values():
        for st in arm.values():
            d = st["decode_tps"]
            if d["sd"] is not None:
                sds.append(d["sd"])
            if d["n"]:
                ns.append(d["n"])
    n_min = min(ns) if ns else 0
    mde = {
        "formula": MDE_FORMULA,
        "n": n_min,
        "pooled_sd": (round(math.sqrt(statistics.fmean([s * s for s in sds])), 4) if sds else None),
        "mde_decode_tps": min_detectable_effect(sds, n_min),
    }
    ratios: dict[str, Any] = {}
    arms = sorted(per_cell)
    for i, a in enumerate(arms):
        for b in arms[i + 1:]:
            for cell in sorted(set(per_cell[a]) & set(per_cell[b])):
                ratios[f"{a}/{b}:{cell}"] = {
                    "decode_tps": ratio_or_refuse(per_cell[a][cell]["decode_tps"], per_cell[b][cell]["decode_tps"]),
                    "ttft_ms": ratio_or_refuse(per_cell[a][cell]["ttft_ms"], per_cell[b][cell]["ttft_ms"]),
                }
    return {
        "per_arm_cell": per_cell,
        "arm_output_identity": arm_identity,
        "mtp_off_vs_on_identity": mtp_cmp,
        **mtp_cmp_other,
        "mde": mde,
        "ratios": ratios,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-protocol summaries; plateau and cold rows are never mixed.

    Heat-loop rows (status 'heat') and invalid rows are excluded from every statistic.
    """
    valid = [r for r in rows if r.get("status") == "ok"]
    protocols = sorted({r.get("protocol", "plateau") for r in valid})
    return {
        "protocols": {
            p: _summarize_protocol([r for r in valid if r.get("protocol", "plateau") == p])
            for p in protocols
        },
        "ratio_rule": f"no ratio when either side's CV% > {CV_LIMIT_PCT} or CV is undefined (n<2); computed per protocol",
        "invalid_rows": sum(1 for r in rows if r.get("status") not in ("ok", "heat")),
        "heat_rows_excluded": sum(1 for r in rows if r.get("status") == "heat"),
    }


# ---------------------------------------------------------------------------
# Memory + environment
# ---------------------------------------------------------------------------


def _in_use_gb() -> float:
    import psutil

    vm = psutil.virtual_memory()
    return (vm.total - vm.available) / (1024**3)


class MemSampler:
    """1 Hz In-Use sampler; ``begin()``/``end()`` bracket a peak window."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._peak = 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.is_set():
            v = _in_use_gb()
            with self._lock:
                self._peak = max(self._peak, v)
            self._stop.wait(1.0)

    def begin(self) -> None:
        with self._lock:
            self._peak = _in_use_gb()

    def end(self) -> float:
        v = _in_use_gb()
        with self._lock:
            self._peak = max(self._peak, v)
            return round(self._peak, 3)


def wait_memory_return(baseline_gb: float) -> dict[str, Any]:
    t0 = time.time()
    while True:
        cur = _in_use_gb()
        waited = time.time() - t0
        if cur <= baseline_gb + MEM_RETURN_GB:
            return {"settled": True, "waited_s": round(waited, 1), "in_use_gb": round(cur, 3)}
        if waited >= MEM_WAIT_S:
            return {"settled": False, "waited_s": round(waited, 1), "in_use_gb": round(cur, 3)}
        time.sleep(1.0)


def gpu_driver_version() -> dict[str, Any]:
    cmd = (
        "Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion | "
        "ConvertTo-Json -Compress"
    )
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd],
            capture_output=True, text=True, timeout=60,
        ).stdout.strip()
        data = json.loads(out) if out else []
        if isinstance(data, dict):
            data = [data]
        intel = [d for d in data if "intel" in str(d.get("Name", "")).lower() or "arc" in str(d.get("Name", "")).lower()]
        return {"intel": intel, "all": data}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def _now_iso() -> str:
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Workload (needs the repo on sys.path; imports are lazy)
# ---------------------------------------------------------------------------

_PROSE = (
    "The harbour town kept its records in ledgers bound in grey cloth, and every "
    "spring the clerk would carry the previous year's volumes up the hill to the "
    "dry room above the chapel. There the pages were aired, the spines oiled, and "
    "the margins checked for the small brown marks that meant damp had found its "
    "way in. Entries were made in a plain hand: the arrival of a boat, the weight "
    "of its cargo, the name of the pilot who brought it past the shoals, and the "
    "fee paid. Disputes were rare, because everything was written down and "
    "everyone knew it would be read again. "
)

_AO_SYSTEM = (
    "You are a careful assistant. Answer the user's question using only the "
    "supplied notes, and keep the answer short."
)

_MT_SYSTEM = "You are a concise assistant. Answer in one or two sentences."
_MT_QUESTIONS = (
    "Name the capital of France and one river that flows through it.",
    "Which of those two facts would a tourist more likely care about, and why?",
    "Give me a three-item packing list for a weekend there in October.",
    "Which item on that list is easiest to forget, and how do I avoid forgetting it?",
    "Suggest one museum and one neighbourhood to walk through afterwards.",
    "Summarise the whole plan we made in two sentences.",
)
_MT_REPLIES = (
    "The capital of France is Paris, and the Seine flows through it.",
    "A tourist would more likely care about the river, because walking its banks is a classic way to see the city.",
    "Pack a light waterproof jacket, comfortable walking shoes, and a portable phone charger.",
    "The charger is easiest to forget; put it in your bag the night before and tick it off a list by the door.",
    "Visit the Musee d'Orsay, then stroll through the Latin Quarter for cafes and bookshops.",
)

_WARMUP_PROMPT = (
    "<|im_start|>system\nYou are terse.<|im_end|>\n"
    "<|im_start|>user\nSay the word ready.<|im_end|>\n"
    "<|im_start|>assistant\n" + EMPTY_THINK
)


def build_pa_prompt() -> tuple[str, str]:
    """The real production PA prompt for the first model-mode golden case."""
    from evals.loader import golden_path, load_golden  # noqa: F401
    from evals.suites.pa_classification import _build_car
    from services.policy_agent.src.gpu_inference import CARPromptFormatter

    path = REPO_ROOT / "evals" / "golden" / "pa_classification.jsonl"
    case = None
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if obj.get("mode") == "model":
                case = obj
                break
    if case is None:
        raise RuntimeError("no model-mode case in pa_classification.jsonl")
    return CARPromptFormatter.build_prompt(_build_car(case["car"])), case["id"]


def build_ao_prompt(count_tokens, target: int = AO_TARGET_TOKENS) -> str:
    """ChatML prompt of ~``target`` tokens (per ``count_tokens``): repeated prose notes."""
    question = "Based on the notes above, what did the clerk check for in the margins?"

    def render(n_blocks: int) -> str:
        notes = "".join(f"Note {i + 1}. {_PROSE}\n" for i in range(n_blocks))
        return (
            f"<|im_start|>system\n{_AO_SYSTEM}<|im_end|>\n"
            f"<|im_start|>user\nNotes:\n{notes}\n{question}<|im_end|>\n"
            f"<|im_start|>assistant\n{EMPTY_THINK}"
        )

    lo, hi = 1, 1
    while count_tokens(render(hi)) < target:
        lo, hi = hi, hi * 2
        if hi > 4096:
            raise RuntimeError("ao-long calibration did not converge")
    while lo < hi:  # smallest block count with >= target tokens
        mid = (lo + hi) // 2
        if count_tokens(render(mid)) >= target:
            hi = mid
        else:
            lo = mid + 1
    return render(lo)


def build_multiturn_prompts() -> list[str]:
    """Turn k's prompt = system + k-1 scripted (user, assistant) pairs + user k."""
    prompts = []
    for k in range(MULTITURN_TURNS):
        parts = [f"<|im_start|>system\n{_MT_SYSTEM}<|im_end|>\n"]
        for j in range(k):
            parts.append(f"<|im_start|>user\n{_MT_QUESTIONS[j]}<|im_end|>\n")
            parts.append(f"<|im_start|>assistant\n{_MT_REPLIES[j]}<|im_end|>\n")
        parts.append(f"<|im_start|>user\n{_MT_QUESTIONS[k]}<|im_end|>\n")
        parts.append(f"<|im_start|>assistant\n{EMPTY_THINK}")
        prompts.append("".join(parts))
    return prompts


# ---------------------------------------------------------------------------
# Arm runners
# ---------------------------------------------------------------------------


class _Arm:
    """One loaded model. ``generate`` returns a raw measurement dict."""

    name: str
    header: dict[str, Any]

    def count_tokens(self, text: str) -> int: ...
    def generate(self, prompt: str, max_new: int) -> dict[str, Any]: ...
    def mtp_summary(self) -> dict[str, Any] | None:
        return None


def _tok_count(tokenizer: Any, text: str) -> int:
    ids = tokenizer.encode(text).input_ids.data
    return int(ids.shape[-1])


class CBArm(_Arm):
    def __init__(self, name: str, model_dir: Path) -> None:
        from evals.cb_pipeline import CBEnginePipeline

        engine = sizes.engine_for(name)
        self.name = name
        self.pipe = CBEnginePipeline(model_dir, engine)
        self.header = dict(self.pipe.header)
        self._tok = self.pipe.get_tokenizer()

    def count_tokens(self, text: str) -> int:
        return _tok_count(self._tok, text)

    def generate(self, prompt: str, max_new: int) -> dict[str, Any]:
        import openvino_genai as g

        cfg = g.GenerationConfig()
        cfg.max_new_tokens = max_new
        cfg.do_sample = False
        cfg.apply_chat_template = False
        t0 = time.perf_counter()
        text = self.pipe.generate(prompt, generation_config=cfg)
        wall = (time.perf_counter() - t0) * 1000.0
        st = dict(text.stats)
        out = {
            "text": str(text),
            "wall_ms": round(wall, 2),
            "ttft_ms": st.get("ttft_ms"),
            "tpot_ms": st.get("tpot_ms"),
            "generated_tokens": st.get("generated_tokens"),
            "pm_input_tokens": st.get("input_tokens"),
        }
        if self.pipe._spec.mtp:
            for k in ("draft_tokens", "accepted_tokens", "rejected_tokens", "acceptance_rate"):
                out[k] = st.get(k)
        return out

    def mtp_summary(self) -> dict[str, Any] | None:
        from evals.cb_pipeline import assert_mtp_engaged

        if not self.pipe._spec.mtp:
            return None
        return assert_mtp_engaged(self.pipe)  # raises CBEngineError when not engaged


class LLM14Arm(_Arm):
    def __init__(self, model_dir: Path, draft_dir: Path) -> None:
        import openvino_genai as ov_genai
        from shared.constants import NUM_ASSISTANT_TOKENS

        self.name = ARM_14B
        self._ov = ov_genai
        self._nat = NUM_ASSISTANT_TOKENS
        scheduler = ov_genai.SchedulerConfig()
        scheduler.cache_size = 3
        scheduler.enable_prefix_caching = True
        t0 = time.perf_counter()
        draft = ov_genai.draft_model(
            str(draft_dir), "GPU",
            PERFORMANCE_HINT="LATENCY", INFERENCE_PRECISION_HINT="f16",
            GPU_ENABLE_SDPA_OPTIMIZATION="ON", CACHE_DIR="",
        )
        target_props: dict[str, Any] = {
            "PERFORMANCE_HINT": "LATENCY", "MODEL_PRIORITY": "HIGH",
            "INFERENCE_PRECISION_HINT": "f16", "GPU_ENABLE_SDPA_OPTIMIZATION": "ON",
            "CACHE_DIR": "",
        }
        self.pipe = ov_genai.LLMPipeline(
            str(model_dir), "GPU", **target_props, scheduler_config=scheduler, draft_model=draft
        )
        self._tok = self.pipe.get_tokenizer()
        self.header = {
            "engine": ARM_14B, "model_dir": str(model_dir), "draft_dir": str(draft_dir),
            "prefix_caching": True, "num_assistant_tokens": NUM_ASSISTANT_TOKENS,
            "scheduler": {"cache_size_gb": 3, "enable_prefix_caching": True},
            "compile_properties": target_props,
            "draft_compile_properties": {
                "PERFORMANCE_HINT": "LATENCY", "INFERENCE_PRECISION_HINT": "f16",
                "GPU_ENABLE_SDPA_OPTIMIZATION": "ON", "CACHE_DIR": "",
            },
            "kv_cache_precision": "plugin default (unset, as in production default)",
            "genai_version": getattr(ov_genai, "__version__", "?"),
            "load_seconds": round(time.perf_counter() - t0, 2),
        }

    def count_tokens(self, text: str) -> int:
        return _tok_count(self._tok, text)

    def generate(self, prompt: str, max_new: int) -> dict[str, Any]:
        cfg = self._ov.GenerationConfig()
        cfg.max_new_tokens = max_new
        cfg.do_sample = False
        cfg.apply_chat_template = False
        cfg.num_assistant_tokens = self._nat
        t0 = time.perf_counter()
        res = self.pipe.generate([prompt], cfg)  # a bare str prompt returns a plain str with no perf_metrics
        wall = (time.perf_counter() - t0) * 1000.0
        pm = res.perf_metrics
        text = res.texts[0] if getattr(res, "texts", None) else str(res)
        return {
            "text": text,
            "wall_ms": round(wall, 2),
            "ttft_ms": round(float(pm.get_ttft().mean), 2),
            "tpot_ms": round(float(pm.get_tpot().mean), 2),
            "generated_tokens": int(pm.get_num_generated_tokens()),
            "pm_input_tokens": int(pm.get_num_input_tokens()),
        }


def load_arm(name: str, args: argparse.Namespace) -> _Arm:
    if name == ARM_14B:
        from shared.constants import DRAFT_MODEL_OV_PATH

        draft = Path(args.models_root) / DRAFT_MODEL_OV_PATH
        return LLM14Arm(Path(args.model_14b), draft)
    return CBArm(name, sizes.model_dir_for(name, args))


# ---------------------------------------------------------------------------
# Main protocol
# ---------------------------------------------------------------------------


def _row_from(raw: dict[str, Any], base: dict[str, Any], input_tokens: int, valid: str) -> dict[str, Any]:
    tpot = raw.get("tpot_ms")
    gen = raw.get("generated_tokens")
    tps_wall = None
    if gen and gen > 1 and raw.get("ttft_ms") is not None:
        dec_ms = raw["wall_ms"] - raw["ttft_ms"]
        tps_wall = round((gen - 1) / (dec_ms / 1000.0), 3) if dec_ms > 0 else None
    row = {
        **base,
        "status": valid,
        "ttft_ms": raw.get("ttft_ms"),
        "tpot_ms": tpot,
        "decode_tps": round(1000.0 / tpot, 3) if tpot else None,
        "decode_tps_wall": tps_wall,
        "generated_tokens": gen,
        "input_tokens": input_tokens,
        "pm_input_tokens": raw.get("pm_input_tokens"),
        "output_sha256": sha256_text(raw["text"]),
        "output_chars": len(raw["text"]),
        "wall_ms": raw["wall_ms"],
    }
    for k in ("draft_tokens", "accepted_tokens", "rejected_tokens", "acceptance_rate"):
        if k in raw:
            row[k] = raw[k]
    return row


def _turn_list(args: argparse.Namespace) -> list[int]:
    turns = sorted({int(t) for t in str(args.multiturn_turns).split(",") if t.strip()})
    for t in turns:
        if not 1 <= t <= MULTITURN_TURNS:
            raise SystemExit(f"--multiturn-turns value {t} outside 1..{MULTITURN_TURNS}")
    return turns


def _cold_cells(args: argparse.Namespace) -> list[str]:
    wanted = [c.strip() for c in args.cold_cells.split(",") if c.strip()]
    cells = [c.strip() for c in args.cells.split(",") if c.strip()]
    return [c for c in wanted if c.split(":")[0] in cells]


def _plateau_cells(args: argparse.Namespace) -> list[str]:
    cells = [c.strip() for c in args.cells.split(",") if c.strip()]
    out: list[str] = []
    for c in ALL_CELLS:
        if c not in cells:
            continue
        if c == "multiturn":
            out += [f"multiturn:t{t}" for t in _turn_list(args)]
        else:
            out.append(c)
    return out


def run(args: argparse.Namespace) -> dict[str, Any]:
    import psutil

    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    cells = [c.strip() for c in args.cells.split(",") if c.strip()]
    for a in arms:
        if a not in KNOWN_ARMS:
            raise SystemExit(f"unknown arm {a!r}")
    for c in cells:
        if c not in ALL_CELLS:
            raise SystemExit(f"unknown cell {c!r}")
    do_plateau = args.protocol in ("plateau", "both")
    do_cold = args.protocol in ("cold", "both")
    plateau_cells = _plateau_cells(args) if do_plateau else []
    cold_cells = _cold_cells(args) if do_cold else []

    import openvino
    import openvino_genai
    from sample_system import read_thermal

    pa_prompt, pa_case = build_pa_prompt()  # also the heat-loop prompt
    mt_prompts = build_multiturn_prompts()

    # (arm, visit) entries; visit = index of that arm's occurrence in --arms.
    seen: dict[str, int] = {}
    entries: list[tuple[str, int]] = []
    for a in arms:
        entries.append((a, seen.get(a, 0)))
        seen[a] = seen.get(a, 0) + 1
    repeated = any(v > 1 for v in seen.values())

    sampler = MemSampler()
    sampler.start()
    baseline = round(_in_use_gb(), 3)
    cache_arms = ", ".join([sizes.arm_name(s, "prefix-cache") for s in (sizes.sizes_in(arms) or ["4b"])] + [ARM_14B])
    meta = {
        "tag": args.tag,
        "started": _now_iso(),
        "python": sys.executable,
        "openvino_version": openvino.__version__,
        "openvino_genai_version": openvino_genai.__version__,
        "gpu_driver": gpu_driver_version(),
        "uptime_h": round((time.time() - psutil.boot_time()) / 3600.0, 2),
        "baseline_in_use_gb": baseline,
        "thermal_at_start": read_thermal(),
        "cache_dir": "",
        "cache_dir_note": "CACHE_DIR='' (model cache disabled) in every compile-property set",
        "rounds": args.rounds,
        "arms": arms,
        "arm_order_rotated": not repeated,
        "cells": cells,
        "protocol": args.protocol,
        "reps": args.reps,
        "multiturn_turns": _turn_list(args),
        "plateau_cells": plateau_cells,
        "cold_cells": cold_cells,
        "cold_temp_c": args.cold_temp,
        "cold_max_wait_s": args.cold_max_wait,
        "plateau_rule": "heat loop on the pa prompt: stop when >=8 generations and the last 4 tpot values are each within 5% of their mean; cap 40",
        "pa_case_id": pa_case,
        "models": models_meta(args, arms),
        "max_new_tokens": {"pa": 16, "ao-long": 128, "multiturn": 48},
        "warmup": "1 discarded generation per loaded arm on a neutral prompt unrelated to any cell",
        "multiturn_note": "prior assistant turns are scripted, so prompts are byte-identical across arms/rounds",
        "prefix_cache_note": "repeated identical prompts (heat loop, reps) hit the prefix cache on prefix-cache-ON arms (" + cache_arms + ")",
    }

    rows: list[dict[str, Any]] = []
    arm_rounds: list[dict[str, Any]] = []
    status_fh = open(args.status_file, "a", encoding="utf-8") if args.status_file else None

    def emit(obj: dict[str, Any]) -> None:
        if status_fh:
            status_fh.write(json.dumps(obj) + "\n")
            status_fh.flush()

    exit_code = 0
    try:
        for rnd in range(args.rounds):
            k = 0 if repeated else rnd % len(entries)
            order = entries[k:] + entries[:k]
            for pos, (name, visit) in enumerate(order):
                rec: dict[str, Any] = {"arm": name, "visit": visit, "round": rnd, "order_in_round": pos}
                sampler.begin()
                arm = None
                try:
                    arm = load_arm(name, args)
                    rec["header"] = arm.header
                    rec["genai_version"] = openvino_genai.__version__
                    rec["openvino_version"] = openvino.__version__
                    arm.generate(_WARMUP_PROMPT, 8)  # discarded
                    ao_prompt = build_ao_prompt(arm.count_tokens) if "ao-long" in cells else None

                    def prompt_for(cell: str) -> tuple[str, int]:
                        if cell == "pa":
                            return pa_prompt, 16
                        if cell == "ao-long":
                            return ao_prompt, 128
                        return mt_prompts[int(cell.split(":t")[1]) - 1], 48

                    pending: list[dict[str, Any]] = []

                    def gen(cell: str, prompt: str, max_new: int, protocol: str, status: str = "ok",
                            extra: dict[str, Any] | None = None) -> dict[str, Any]:
                        th_before = read_thermal()
                        raw = arm.generate(prompt, max_new)
                        th_after = read_thermal()
                        base = {
                            "t": _now_iso(), "arm": name, "visit": visit, "round": rnd, "cell": cell,
                            "protocol": protocol,
                            "genai_version": openvino_genai.__version__,
                            "openvino_version": openvino.__version__,
                            "prompt_sha256": sha256_text(prompt),
                            "thermal_before": th_before, "thermal_after": th_after,
                            **(extra or {}),
                        }
                        row = _row_from(raw, base, arm.count_tokens(prompt), status)
                        pending.append(row)
                        emit({"t": time.time(), "arm": name, "visit": visit, "round": rnd, "cell": cell,
                              "protocol": protocol, "ttft_ms": row["ttft_ms"], "tps": row["decode_tps"]})
                        return row

                    if do_cold:
                        for cell in cold_cells:
                            w = wait_for_cold(read_thermal, args.cold_temp, args.cold_max_wait)
                            prompt, mx = prompt_for(cell)
                            gen(cell, prompt, mx, "cold", extra={"cold_wait": w})
                    if do_plateau:
                        tpots: list[float] = []
                        n_heat = 0
                        reached = False
                        while n_heat < HEAT_CAP:
                            r = gen("heat", pa_prompt, 16, "plateau", status="heat", extra={"heat_index": n_heat})
                            n_heat += 1
                            tpots.append(r["tpot_ms"])
                            if plateau_reached(tpots):
                                reached = True
                                break
                        rec["plateau_reached"] = reached
                        rec["heat_generations"] = n_heat
                        rec["heat_tpot_ms"] = tpots
                        for cell in plateau_cells:
                            prompt, mx = prompt_for(cell)
                            for rep in range(args.reps):
                                gen(cell, prompt, mx, "plateau", extra={"rep": rep})
                    try:
                        rec["mtp_summary"] = arm.mtp_summary()
                    except Exception as exc:  # noqa: BLE001 - recorded, arm marked invalid
                        rec["mtp_error"] = f"{type(exc).__name__}: {exc}"
                        for r in pending:
                            if r["status"] == "ok":
                                r["status"] = "invalid_mtp_not_engaged"
                    rows.extend(pending)
                except Exception as exc:  # noqa: BLE001 - one arm failing must not kill the others
                    rec["error"] = f"{type(exc).__name__}: {exc}"
                    exit_code = 1
                finally:
                    arm = None
                    gc.collect()
                    rec["peak_in_use_gb"] = sampler.end()
                    rec["return_to_baseline"] = wait_memory_return(baseline)
                    arm_rounds.append(rec)
    finally:
        sampler.stop()

    meta["finished"] = _now_iso()
    result = {
        "meta": meta,
        "arm_rounds": arm_rounds,
        "rows": rows,
        "summary": summarize(rows),
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=1)
    emit({"done": True, "exit": exit_code})
    if status_fh:
        status_fh.close()
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0], allow_abbrev=False)
    ap.add_argument("--arms", default=",".join(ALL_ARMS))
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--models-root", default="C:/Users/mrbla/BlarAI")
    sizes.add_model_args(ap)
    ap.add_argument("--model-14b", default=None)
    ap.add_argument("--status-file", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cells", default=",".join(ALL_CELLS))
    ap.add_argument("--tag", default="")
    ap.add_argument("--protocol", choices=("plateau", "cold", "both"), default="both")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--multiturn-turns", default="1,3,6")
    ap.add_argument("--cold-temp", type=float, default=None)
    ap.add_argument("--cold-max-wait", type=float, default=180.0)
    ap.add_argument("--cold-cells", default="pa,ao-long,multiturn:t1")
    args = ap.parse_args(argv)
    if args.protocol in ("cold", "both") and args.cold_temp is None:
        ap.error("--cold-temp is required when --protocol includes cold")
    # Resolve every path to absolute BEFORE any chdir.
    args.models_root = str(Path(args.models_root).resolve())
    sizes.resolve_model_args(args)
    args.model_14b = str(
        Path(args.model_14b).resolve()
        if args.model_14b
        else (Path(args.models_root) / "models" / "qwen3-14b" / "openvino-int4-gpu").resolve()
    )
    args.out = str(Path(args.out).resolve())
    if args.status_file:
        args.status_file = str(Path(args.status_file).resolve())
    return args


def models_meta(args: Any, arms: list[str]) -> dict[str, Any]:
    """The ``meta.models`` block: model_4b and model_14b always, model_<size> for every other size that has an arm."""
    return {
        "model_4b": args.model_4b,
        **{f"model_{s}": getattr(args, f"model_{s}") for s in sizes.sizes_in(arms) if s != "4b"},
        "model_14b": args.model_14b,
        "models_root": args.models_root,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    sys.path.insert(0, str(REPO_ROOT))
    os.chdir(args.models_root)  # shared.constants paths are cwd-relative
    try:
        run(args)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        if args.status_file:
            with open(args.status_file, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"done": True, "exit": 2, "error": f"{type(exc).__name__}: {exc}"}) + "\n")
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main())
