"""Deterministic PIXEL-level visual checks for the headless-coding design loop.

The reference-free complement to :mod:`shared.fleet.layout_lint` (XAML geometry, Lever A)
and :mod:`shared.fleet.critique` (the soft VLM, Lever C). A small vision-language model
hallucinates exactly the COUNTABLE / COLOUR / POSITION facts a histogram computes with
certainty — it called a near-blank page "a nice blue background" and miscounts cards
(VLMs-Are-Blind 2407.06581; Eyes-Wide-Shut 2401.06209). This module reads the CAPTURED
SCREENSHOT and flags high-precision visual defects with ZERO model judgement, so a
degenerate render or a flat-out-missing colour is caught even when the VLM says PASS.

**Master principle (NON-NEGOTIABLE).** This gate only ever ADDS findings — a HARD finding
forces another coder FIX iteration (exactly like ``layout_lint``'s HIGH findings). It NEVER
marks a criterion done / verified / passed: a clean image yields NO findings, which is
*silence, not a PASS*. The visual acceptance tier stays ``STATUS_EYEBALL``
(``shared/fleet/acceptance.py :: criterion_status``); the operator's eye is the only verdict.
When this gate — or the VLM — is unavailable, the loop does NOT auto-progress (an empty
fail-soft result simply means "no deterministic objection from pixels this pass").

**Scope (LA-locked 2026-06-26): colour-presence + element-geometry from the screenshot only.**
TEXT-presence is deliberately NOT here. It would need OCR (a new, heavy dependency), and the
design loop's concern is text *rendered visibly* (pixels) — which stays a VLM signal;
source-text presence is already an acceptance concern (``acceptance.py`` spec-blind tests).
The golden-reference block-match / CLIP path is a thin INERT seam only — see
:func:`compare_to_golden`.

**Precision-first severity.** A false HARD nags the coder into "fixing" correct work AND
costs a ~1–2 min model swap, so HARD fires ONLY on near-certain defects; everything noisier
is computed and folded into a HARD guard rather than emitted as a finding the bridge would
drop:

  blank-render          HIGH  the render is empty / a single flat colour / has no content.
  named-colour-absent   HIGH  a basic chromatic colour the criteria/goal explicitly name is
                              essentially absent from the render (generous HSV band, <=0.5%).
  content-collapsed     HIGH  all content is a tiny blob jammed into one corner of an
                              otherwise-blank canvas (a known broken-render mode); centred or
                              spread layouts never trigger.

**Fail-soft contract:** any failure (missing / unreadable / invalid PNG, decode error)
yields ``{"findings": [], "hard": False, ...}`` and never raises, so the design loop
degrades to the layout+VLM signal rather than crashing.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np

# Reuse layout_lint's Finding contract verbatim so the PowerShell bridge
# (Invoke-PixelLint, mirroring Invoke-LayoutLint) parses both linters identically.
from shared.fleet.layout_lint import (  # noqa: F401  (format_findings re-exported for callers)
    SEVERITY_HIGH,
    SEVERITY_LOW,
    Finding,
    format_findings,
    has_hard_findings,
)

# ---------------------------------------------------------------------------
# Tunables (module constants so the tests can reason about exact thresholds)
# ---------------------------------------------------------------------------

# Downscale the screenshot to at most this on its longest edge before analysis:
# denoises antialiasing/gradients and keeps the pixel maths fast + deterministic.
_DOWNSCALE_MAX = 128

# A render counts as BLANK if a single quantised colour covers >= this fraction.
_BLANK_TOP_FRACTION = 0.985
# Quantisation bucket width (0-255 per channel) for the blank / background mode.
_QUANT = 32

# A named colour is "essentially absent" (HARD) below this fraction of pixels.
_COLOR_PRESENCE_MIN = 0.005  # 0.5 %

# Chromatic-colour HSV gate: generous so a pale/"soft" shade still counts as PRESENT
# (false ABSENCE is the only dangerous direction — it would force a needless fix).
_SAT_MIN = 0.15
_VAL_MIN = 0.18

# content-collapsed guard: content must be both tiny AND cornered to fire HARD.
_COLLAPSE_CONTENT_MAX = 0.04   # content-collapsed fires only when < 4 % of the canvas is content...
_CONTENT_DELTA = 0.12          # a pixel is "content" when its normalised RGB distance from the
                               # background exceeds this (0-1); denoises antialiasing / gradients.

# Hue bands in DEGREES [0,360); contiguous, cover the wheel. Red wraps at 0/360.
_HUE_BANDS: dict[str, tuple[float, float]] = {
    "orange": (15.0, 40.0),
    "yellow": (40.0, 70.0),
    "green": (70.0, 165.0),
    "cyan": (165.0, 195.0),
    "blue": (195.0, 255.0),
    "purple": (255.0, 290.0),
    "pink": (290.0, 345.0),
}
# Canonical chromatic colours we will HARD-flag for absence. "red" is the wrap band.
_CANONICAL_COLORS = ("red", *_HUE_BANDS.keys())

# Colour words -> canonical bucket. Achromatic (white/black/gray) are intentionally NOT
# nameable for HARD absence ("a black page is missing black" is rarely a real defect, and
# low-saturation detection is unreliable); they are excluded by simply not appearing here.
_COLOR_SYNONYMS: dict[str, str] = {
    "red": "red", "crimson": "red", "scarlet": "red", "maroon": "red", "ruby": "red",
    "orange": "orange", "amber": "orange", "tangerine": "orange",
    "yellow": "yellow", "gold": "yellow", "golden": "yellow",
    "green": "green", "lime": "green", "emerald": "green", "olive": "green",
    "cyan": "cyan", "teal": "cyan", "turquoise": "cyan", "aqua": "cyan",
    "blue": "blue", "navy": "blue", "sky": "blue", "azure": "blue", "indigo": "blue",
    "purple": "purple", "violet": "purple", "lavender": "purple",
    "pink": "pink", "magenta": "pink", "rose": "pink", "fuchsia": "pink",
}
_COLOR_WORD_RE = re.compile(
    r"\b(" + "|".join(sorted(_COLOR_SYNONYMS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Pure colour-space helpers (numpy only — no PIL, no I/O — so analyze() is testable)
# ---------------------------------------------------------------------------

def _rgb_to_hsv(arr: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Vectorised RGB->HSV. ``arr`` is HxWx3 float in [0,1]. Returns (H deg [0,360), S, V)."""
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    mx = arr.max(axis=-1)
    mn = arr.min(axis=-1)
    diff = mx - mn
    v = mx
    s = np.where(mx <= 0.0, 0.0, diff / np.where(mx <= 0.0, 1.0, mx))

    # Hue: guard the diff==0 (achromatic) case to 0 to avoid div-by-zero.
    safe = np.where(diff == 0.0, 1.0, diff)
    rc = (mx - r) / safe
    gc = (mx - g) / safe
    bc = (mx - b) / safe
    h = np.zeros_like(mx)
    h = np.where(mx == r, bc - gc, h)
    h = np.where(mx == g, 2.0 + rc - bc, h)
    h = np.where(mx == b, 4.0 + gc - rc, h)
    h = (h / 6.0) % 1.0
    h = np.where(diff == 0.0, 0.0, h)
    return h * 360.0, s, v


def _color_mask(h: np.ndarray, s: np.ndarray, v: np.ndarray, color: str) -> np.ndarray:
    """Boolean mask of pixels belonging to ``color`` (a canonical chromatic bucket)."""
    chroma = (s >= _SAT_MIN) & (v >= _VAL_MIN)
    if color == "red":
        hue = (h < 15.0) | (h >= 345.0)
    else:
        lo, hi = _HUE_BANDS[color]
        hue = (h >= lo) & (h < hi)
    return hue & chroma


def color_presence(arr_rgb: np.ndarray, color: str) -> float:
    """Fraction of pixels in ``arr_rgb`` (HxWx3 uint8) belonging to ``color``."""
    f = arr_rgb.astype(np.float32) / 255.0
    h, s, v = _rgb_to_hsv(f)
    return float(_color_mask(h, s, v, color).mean())


def extract_named_colors(text: str) -> list[str]:
    """Canonical chromatic colours explicitly named in ``text`` (order-stable, de-duped)."""
    seen: list[str] = []
    for word in _COLOR_WORD_RE.findall(text or ""):
        canon = _COLOR_SYNONYMS[word.lower()]
        if canon not in seen:
            seen.append(canon)
    return seen


# ---------------------------------------------------------------------------
# Geometry / blank helpers
# ---------------------------------------------------------------------------

def _quantised_top_fraction(arr_rgb: np.ndarray) -> tuple[float, np.ndarray]:
    """Largest single quantised-colour fraction, and that colour (uint8 RGB), for the image."""
    q = (arr_rgb.astype(np.int32) // _QUANT)
    flat = q.reshape(-1, 3)
    # Encode each quantised RGB triple as one int for fast bincount-style counting.
    codes = (flat[:, 0] << 16) | (flat[:, 1] << 8) | flat[:, 2]
    vals, counts = np.unique(codes, return_counts=True)
    i = int(counts.argmax())
    frac = float(counts[i]) / float(codes.shape[0])
    top_code = int(vals[i])
    top_q = np.array([(top_code >> 16) & 0xFF, (top_code >> 8) & 0xFF, top_code & 0xFF],
                     dtype=np.float32)
    bg_rgb = (top_q * _QUANT + _QUANT / 2.0)  # bucket centre back in 0-255
    return frac, bg_rgb


def _content_stats(arr_rgb: np.ndarray, bg_rgb: np.ndarray) -> tuple[float, bool]:
    """Per-pixel content analysis against the background colour.

    Returns ``(content_fraction, cornered)`` where ``content_fraction`` is the share of pixels
    whose normalised RGB distance from ``bg_rgb`` exceeds :data:`_CONTENT_DELTA`, and
    ``cornered`` is True iff the bounding box of those content pixels lies entirely within a
    single quadrant of the image (the "jammed in one corner" geometry). Pixel-level (not a
    coarse grid) so the thresholds are exact and the rule is deterministically testable.
    """
    f = arr_rgb.astype(np.float32) / 255.0
    bg = bg_rgb.astype(np.float32) / 255.0
    dist = np.sqrt(((f - bg) ** 2).sum(axis=-1) / 3.0)  # 0-1 per pixel
    mask = dist > _CONTENT_DELTA
    frac = float(mask.mean())
    ys, xs = np.nonzero(mask)
    if ys.size == 0:
        return frac, False
    h, w = arr_rgb.shape[:2]
    midy, midx = h / 2.0, w / 2.0
    vert = (ys.max() < midy) or (ys.min() >= midy)   # all content above OR all below mid
    horiz = (xs.max() < midx) or (xs.min() >= midx)  # all content left OR all right of mid
    return frac, bool(vert and horiz)


# ---------------------------------------------------------------------------
# Core analysis (pure: takes a numpy array, returns Findings — no file I/O)
# ---------------------------------------------------------------------------

def analyze(
    arr_rgb: np.ndarray,
    criteria_text: str = "",
    *,
    fully_transparent: bool = False,
    source: str = "",
) -> list[Finding]:
    """Run the deterministic pixel checks on an HxWx3 uint8 RGB array. Pure; never raises.

    ``criteria_text`` is the concatenation of the visual criteria (+ goal) prose, scanned for
    explicitly-named colours. ``fully_transparent`` is passed by the loader when the source
    PNG's alpha channel is entirely zero (nothing was painted).
    """
    findings: list[Finding] = []

    # --- blank-render (HARD) -------------------------------------------------
    if fully_transparent:
        return [Finding(rule="blank-render", severity=SEVERITY_HIGH,
                        message="The rendered app is fully transparent — nothing was drawn.",
                        element="render", file=source)]
    top_frac, bg_rgb = _quantised_top_fraction(arr_rgb)
    if top_frac >= _BLANK_TOP_FRACTION:
        return [Finding(
            rule="blank-render", severity=SEVERITY_HIGH,
            message=(f"The render is essentially a single flat colour "
                     f"({top_frac * 100:.0f}% one colour) — the app appears blank / unrendered."),
            element="render", file=source)]

    # --- named-colour-absent (HARD) -----------------------------------------
    for color in extract_named_colors(criteria_text):
        frac = color_presence(arr_rgb, color)
        if frac < _COLOR_PRESENCE_MIN:
            findings.append(Finding(
                rule="named-colour-absent", severity=SEVERITY_HIGH,
                message=(f"The design calls for {color}, but {color} is essentially absent "
                         f"from the render ({frac * 100:.2f}% of pixels)."),
                element=color, file=source))

    # --- content-collapsed (HARD, tightly guarded) --------------------------
    # Compute geometry once; only flag the unambiguous "tiny blob in one corner" mode.
    content_frac, cornered = _content_stats(arr_rgb, bg_rgb)
    if 0.0 < content_frac < _COLLAPSE_CONTENT_MAX and cornered:
        findings.append(Finding(
            rule="content-collapsed", severity=SEVERITY_HIGH,
            message=(f"Almost all of the canvas is blank and the little content there is "
                     f"({content_frac * 100:.1f}%) is jammed into one corner — the layout "
                     "looks collapsed rather than laid out."),
            element="render", file=source))

    return findings


# ---------------------------------------------------------------------------
# Image loader + screenshot entry point (the only file I/O — fail-soft)
# ---------------------------------------------------------------------------

def _load_rgb(png_path) -> "tuple[np.ndarray, bool] | None":
    """Load + downscale a PNG to (HxWx3 uint8 RGB, fully_transparent). None on any failure."""
    try:
        from PIL import Image  # local import keeps the module importable without PIL
    except Exception:  # noqa: BLE001 — fail-soft: no PIL -> no pixel checks
        return None
    try:
        p = Path(png_path)
        if not p.is_file() or p.stat().st_size == 0:
            return None
        with Image.open(p) as im:
            im.load()
            fully_transparent = False
            if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
                alpha = im.convert("RGBA").split()[-1]
                fully_transparent = (np.asarray(alpha).max() == 0)
            rgb = im.convert("RGB")
            rgb.thumbnail((_DOWNSCALE_MAX, _DOWNSCALE_MAX))  # in-place, preserves aspect
            arr = np.asarray(rgb, dtype=np.uint8)
        if arr.ndim != 3 or arr.shape[2] != 3 or arr.size == 0:
            return None
        return arr, fully_transparent
    except Exception:  # noqa: BLE001 — any decode error -> fail-soft
        return None


def lint_screenshot(png_path, criteria_text: str = "") -> dict:
    """Lint one screenshot PNG. Returns ``{"findings": [...], "hard": bool, "image": str}``.

    Fail-soft: a missing / unreadable / undecodable image yields no findings (the design loop
    keeps its layout+VLM signal). Mirrors :func:`shared.fleet.layout_lint.lint_app_dir`'s shape.
    """
    name = Path(png_path).name if png_path else ""
    loaded = _load_rgb(png_path)
    if loaded is None:
        return {"findings": [], "hard": False, "image": name}
    arr, transparent = loaded
    findings = analyze(arr, criteria_text, fully_transparent=transparent, source=name)
    return {
        "findings": [asdict(f) for f in findings],
        "hard": has_hard_findings(findings),
        "image": name,
    }


# ---------------------------------------------------------------------------
# INERT golden-reference seam (block-match / CLIP) — interface stub ONLY (YAGNI)
# ---------------------------------------------------------------------------

def compare_to_golden(screenshot_path, golden_path=None, criteria_text: str = "") -> list[Finding]:
    """Reserved seam for golden-reference block-match (text/position/colour deltas) and
    CLIP-similarity scoring (Design2Code 2403.03163). **Deliberately INERT** — always returns
    ``[]`` until a named use case wires a real golden in.

    Two reasons it stays dormant (LA-locked 2026-06-26):

    1. A golden reference only exists for a REGRESSION check — re-rendering an *existing* app
       across design iterations to detect drift. A fresh dispatch has nothing to compare
       against, which is every dispatch today, so there is nothing for this to do yet.
    2. Activating the CLIP limb loads an image-text model that CO-RESIDES with the 30B coder /
       14B on the 31.323 GB unified pool — so turning it on is a MEMORY decision (a [PROPOSED]
       escalation), not merely a question of golden availability.

    Keeping the signature here means the day a regression use case appears, the design loop
    composes one more deterministic lever exactly like :func:`lint_screenshot`, with no
    re-architecture.
    """
    return []


# ---------------------------------------------------------------------------
# __main__ CLI — the fleet PowerShell bridge (mirrors layout_lint's CLI)
# ---------------------------------------------------------------------------
#
# Usage:
#   python -m shared.fleet.pixel_lint --screenshot <png> [--criteria-json '["..."]'] [--goal "..."]
#
# Stdout: a single JSON object on one line: {"findings": [...], "hard": bool, "image": str}
# Exit codes:
#   0 — always (even with findings; the JSON carries the state — this is a SIGNAL the loop
#       merges with layout_lint + the VLM, never a gate that blocks on its own).
#   2 — only for a usage error (no --screenshot, or unparseable --criteria-json).

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m shared.fleet.pixel_lint",
        description="Deterministic pixel-level visual linter — prints JSON findings to stdout.",
    )
    parser.add_argument("--screenshot", required=True, help="Path to the screenshot PNG.")
    parser.add_argument(
        "--criteria-json", default="[]",
        help='JSON array of visual criterion text strings to scan for named colours. Default "[]".',
    )
    parser.add_argument("--goal", default="", help="Optional product goal prose (also scanned for colours).")
    args = parser.parse_args()

    try:
        crit = json.loads(args.criteria_json)
        if not isinstance(crit, list):
            raise ValueError("criteria-json must be a JSON array")
        criteria_text = " ".join(str(c) for c in crit)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: --criteria-json is not a valid JSON array: {exc}", file=sys.stderr)
        sys.exit(2)

    combined = (criteria_text + " " + (args.goal or "")).strip()
    result = lint_screenshot(args.screenshot, combined)
    print(json.dumps(result))
    sys.exit(0)
