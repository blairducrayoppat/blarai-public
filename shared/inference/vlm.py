"""Qwen3-VL image understanding via OpenVINO GenAI VLMPipeline (ADR-015, vision MVP).

Load-on-demand + cached. **Fail-Soft:** ``describe_image()`` returns ``None`` on ANY
failure (model missing, GPU OOM, ``openvino_genai`` absent, decode error) so callers
degrade gracefully to the store-only placeholder rather than breaking the app.

Hardware-validated 2026-06-03 on the Arc 140V: VLMPipeline loads in ~13 s and produces
accurate image descriptions.

**Memory note (the live-test unknown):** the VLM (~5 GB) loads on the GPU alongside the
resident 14B (~8.7 GB) against the 31.3 GB shared ceiling. Co-residency is exercised by
real use; Fail-Soft means an OOM degrades to the placeholder instead of crashing. If
co-residency proves unstable, load-on-demand eviction of the 14B is the next iteration
(ADR-015 / Vikunja #550). No external network.
"""

from __future__ import annotations

import gc
import logging
import threading
from pathlib import Path

from shared.diagnostics import log_memory, record_reclaim

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
VLM_MODEL_DIR = _REPO_ROOT / "models" / "qwen3-vl-8b-instruct" / "openvino-int4-ov"
_DEVICE = "GPU"

# Question-agnostic rich description produced at attach-time and fed to the 14B as
# grounding (the 14B then answers the user's actual question against it). Deliberately
# instructs AGAINST inventing measurements — VLMs guess at metrics, and false precision
# is worse than none for a bid (see the landscape use-case discussion / ADR-015).
_DEFAULT_PROMPT = (
    "Describe this image in detail for a landscaping professional. Note any plants, "
    "trees, shrubs, grass, flowers, and hardscaping (patios, walls, walkways, edging), "
    "structures, terrain, and notable features you can identify. Do NOT estimate exact "
    "measurements, dimensions, or distances — describe relative layout instead."
)

_pipe = None
_lock = threading.Lock()
_load_failed = False


def is_available() -> bool:
    """True iff the VLM model is on disk and openvino_genai is importable."""
    if not (VLM_MODEL_DIR / "openvino_language_model.xml").exists():
        return False
    try:
        import openvino_genai  # noqa: F401
    except ImportError:
        return False
    return True


def _get_pipe():
    """Lazily load + cache the VLMPipeline on the GPU. Returns None on failure (Fail-Soft)."""
    global _pipe, _load_failed
    if _pipe is not None:
        return _pipe
    if _load_failed:
        return None
    with _lock:
        if _pipe is not None:
            return _pipe
        if _load_failed:
            return None
        try:
            import openvino_genai as ov_genai

            log_memory(logger, "vlm.load.before")
            logger.info("Loading Qwen3-VL (%s) on %s", VLM_MODEL_DIR.name, _DEVICE)
            _pipe = ov_genai.VLMPipeline(str(VLM_MODEL_DIR), _DEVICE)
            log_memory(logger, "vlm.load.after")
            logger.info("Qwen3-VL loaded.")
            return _pipe
        except Exception as exc:  # noqa: BLE001 — Fail-Soft: any load failure degrades gracefully
            logger.error("VLM load failed; vision degrades to placeholder: %s", exc)
            _load_failed = True
            return None


def describe_image(image_path, prompt: str | None = None, max_new_tokens: int = 256) -> str | None:
    """Return a text description of the image, or ``None`` on any failure (Fail-Soft).

    Args:
        image_path: Path to an image file.
        prompt: Optional override; defaults to the landscaping-oriented description prompt.
        max_new_tokens: Generation cap.
    """
    if not is_available():
        return None
    pipe = _get_pipe()
    if pipe is None:
        return None
    try:
        import numpy as np
        import openvino as ov
        import openvino_genai as ov_genai
        from PIL import Image

        img = Image.open(image_path).convert("RGB")
        arr = np.array(img)
        dims = f"{img.width}x{img.height}"
        megapixels = round(img.width * img.height / 1_000_000.0, 1)
        tensor = ov.Tensor(arr)
        cfg = ov_genai.GenerationConfig()
        cfg.max_new_tokens = max_new_tokens
        cfg.do_sample = False
        # Log the input size alongside memory: a high-resolution image is the
        # dominant cost driver for the vision encoder (#561 — a 50 MP photo
        # swap-thrashed a 4-minute describe; a 2.4 MP one finished in seconds).
        log_memory(logger, "vlm.describe.before", img=dims, mp=megapixels)
        # VLMPipeline is not concurrency-safe; serialise generate (and the lazy load).
        with _lock:
            res = pipe.generate(
                prompt or _DEFAULT_PROMPT, images=[tensor], generation_config=cfg
            )
        log_memory(logger, "vlm.describe.after", img=dims, mp=megapixels)
        text = str(res).strip()
        return text or None
    except Exception as exc:  # noqa: BLE001 — Fail-Soft
        logger.error("VLM describe_image failed for %s: %s", image_path, exc)
        return None


def unload() -> None:
    """Release the cached VLMPipeline and free its ~5 GB. Idempotent, Fail-Soft.

    The Arc 140V iGPU has no separate VRAM — the VLM shares the 32 GB system
    RAM with the always-resident 14B (~8.7 GB) + draft + KV-cache + voice +
    embedder. Holding the VLM after a vision turn (the original load-once-and-
    cache-forever behaviour) saturated RAM and froze the host on a real
    multimodal session (Vikunja #561 follow-up). Evicting it after each
    ``describe_image`` caps the co-resident peak to the describe window; the
    next image re-loads on demand (~12-16 s).

    Resets ``_load_failed`` so a later image can re-load cleanly (without the
    reset, ``_get_pipe`` would stay in the failed state and never retry). The
    mutation runs under ``_lock`` so it cannot race a mid-flight ``generate``;
    ``gc.collect()`` then forces prompt reclamation rather than waiting for the
    next GC cycle (the codebase's proven OpenVINO-release pattern — no explicit
    ``.release()`` exists on the GenAI pipelines).
    """
    global _pipe, _load_failed
    with _lock:
        already_clear = _pipe is None and not _load_failed
        _pipe = None
        _load_failed = False
    if already_clear:
        return
    before = log_memory(logger, "vlm.unload.before")
    gc.collect()
    after = log_memory(logger, "vlm.unload.after")
    # Honest accounting (#561): report what the OS actually reclaimed rather
    # than asserting "released". On this runtime gc may NOT return the VLM's
    # native GPU/system memory intra-process — the driver pools it — so the
    # before/after numbers tell the truth. Reliable reclamation needs process
    # exit / isolation; tracked for the post-harness memory decision.
    if before and after:
        freed = after.get("sys_available_mb", 0.0) - before.get("sys_available_mb", 0.0)
        logger.info(
            "Qwen3-VL pipeline dereferenced + gc; system available %+.0fMB "
            "(native GPU memory may be driver-pooled).", freed,
        )
    else:
        logger.info("Qwen3-VL pipeline dereferenced + gc.")
    # Structured In-Use reclaim record (#900, OFF by default). The VLM is one of
    # the "other resident caches" the AO evicts before an image generate, so its
    # reclaim behaviour is part of the same #33896 question. Reuses the snapshots
    # above — no extra cost until a measurement run arms the probe. Fail-soft.
    record_reclaim("vlm.unload", before, after, log=logger, model="qwen3-vl")
