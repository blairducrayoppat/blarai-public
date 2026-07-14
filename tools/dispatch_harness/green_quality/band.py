"""#837 — the DETERMINISTIC band formula (the model never renders the band).

The load-bearing lock of the whole instrument: a small (noisy) 14B answers narrow,
enum-scored observations (:mod:`~tools.dispatch_harness.green_quality.jury`); a FIXED FORMULA
here aggregates those answers plus the deterministic Layer-1 findings into the A/B/C band.
The taste-judgment lives in this pure function, never in the model — so the band cannot
drift with the model's mood, and (with the schema's structural block on band→verdict) the
noisy judge can never gate.

Precedence is worst-wins: any C trigger → C; else any B trigger → B; else A. An ABSTAINED
jury field carries NO signal — it never pushes the band toward a worse letter (silence is
not evidence). Layer-1 signals rank ABOVE the jury (the LA principle, #740 c.1721): the
archetype-regression flag alone forces C, because a measured behaviour regression is the
one thing you cannot afford to sample past.
"""

from __future__ import annotations

from typing import Optional

from .constants import (
    BAND_A,
    BAND_B,
    BAND_C,
    FIELD_BAD_INPUT,
    FIELD_CORRECTNESS_PROBE,
    FIELD_NAMING_STRUCTURE,
    FIELD_RUNNABLE_SURFACE,
)
from .jury import JuryResult
from .layer1 import Layer1Result

#: A ruff finding count at/above this is a soft B trigger (a repo with dozens of style
#: violations shipped a no-cleanup pass). Below it, ruff is noted but not band-moving —
#: advisory ruff is a hint, not a verdict.
_RUFF_B_THRESHOLD = 10


def band_reasons(layer1: Layer1Result, jury: Optional[JuryResult]) -> tuple[str, list[str], list[str]]:
    """Return ``(band, c_reasons, b_reasons)`` — the band plus the NAMED triggers behind it,
    so the evidence + card can say *why* a GREEN scored C or B (never an opaque letter).

    Pure + total. This is the ONLY place the band is decided; :func:`compute_band` is the
    thin wrapper the rest of the package calls."""
    c_reasons: list[str] = []
    b_reasons: list[str] = []

    # --- C triggers (worst; a MEASURED break on real input, or the jury READING that the
    # deliverable is unusable/wrong). A deterministic craft heuristic never alone forces C —
    # only a measured regression or a model READ (which sees more than a lint) does.
    if layer1.regression.regressed:
        c_reasons.append(f"behaviour regressed (data loss) vs the last archived GREEN "
                         f"({layer1.regression.detail})")
    if jury is not None:
        if jury.value(FIELD_CORRECTNESS_PROBE) == "wrong":
            c_reasons.append("jury majority: a supplied real input yields an obviously wrong output")
        if jury.value(FIELD_RUNNABLE_SURFACE) == "no":
            c_reasons.append("jury majority: no way for a non-coder to run this")

    # --- B triggers (has caveats; drift/craft residue or a soft jury concern, nothing broken).
    # A behaviour CHANGE that did NOT lose data is a caveat, not a break — the leniency-drift
    # signal worth the operator's eyes ("double-check", not "concerning").
    if layer1.regression.changed and not layer1.regression.regressed:
        b_reasons.append(f"behaviour changed vs the last archived GREEN ({layer1.regression.detail})")
    # The deterministic no-entry-point lint is a caveat, not a break: the thing WORKS, the
    # operator just needs to write a little code to run it (the jury's "no" above is the
    # stronger, read-based signal that escalates it to C).
    if layer1.no_entry_point.flagged:
        b_reasons.append(layer1.no_entry_point.detail)
    if layer1.dead_scaffold.flagged:
        b_reasons.append(layer1.dead_scaffold.detail)
    if layer1.stale_readme.flagged:
        b_reasons.append(layer1.stale_readme.detail)
    if layer1.ruff_findings and layer1.ruff_findings >= _RUFF_B_THRESHOLD:
        b_reasons.append(f"ruff: {layer1.ruff_findings} advisory findings (no cleanup pass)")
    if jury is not None:
        if jury.value(FIELD_RUNNABLE_SURFACE) == "only-by-writing-code":
            b_reasons.append("jury majority: runnable only by writing code")
        if jury.value(FIELD_BAD_INPUT) == "unchecked":
            b_reasons.append("jury majority: bad input is unchecked")
        if jury.value(FIELD_NAMING_STRUCTURE) == "poor":
            b_reasons.append("jury majority: naming/structure is poor")
        if jury.value(FIELD_CORRECTNESS_PROBE) == "minor":
            b_reasons.append("jury majority: a minor correctness issue on a supplied input")

    if c_reasons:
        return (BAND_C, c_reasons, b_reasons)
    if b_reasons:
        return (BAND_B, c_reasons, b_reasons)
    return (BAND_A, c_reasons, b_reasons)


def compute_band(layer1: Layer1Result, jury: Optional[JuryResult] = None) -> str:
    """The A/B/C band for one GREEN — a deterministic function of scored fields ONLY.

    ``jury=None`` (the standing det-only posture, no GPU) computes the band from Layer 1
    alone; a wired jury adds its per-field MAJORITY (abstained fields excluded). The model
    is nowhere in this function — that is the point."""
    return band_reasons(layer1, jury)[0]
