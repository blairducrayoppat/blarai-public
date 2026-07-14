"""#837 — the surface-aware "what you got" card (the operator's only window into GREEN quality).

The operator cannot read code, so for a GREEN this card *is* his access to quality — load-
bearing, not cosmetic. It replaces the fixed, often-false ``"just open the app and try it"``
(the B2 SUMMARY.txt told the operator to open an app for a library that has none) with a
per-surface run line, and carries the ONE honest caveat the audit surfaced, in plain
language, derived MECHANICALLY from Layer 1's regression/probe findings.

Nothing here judges — it renders the deterministic band + findings into a sentence a non-
programmer can act on. A missing or false "what you got" line is itself a reportable audit
finding (dossier §5), so the card is produced for every GREEN, not just concerning ones.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .constants import BAND_A, BAND_B, BAND_C, EVIDENCE_VALUE_CAP
from .layer1 import Layer1Result

#: Per-surface run hint — the honest replacement for "just open the app". A ``{repo}`` token
#: is filled with the deliverable's package/repo name where it clarifies the call.
_SURFACE_RUN_HINT: dict[str, str] = {
    "python-lib": "It is a Python library: import and call it from Python (see demo.py if present).",
    "library": "It is a library: import and call it from your code (see demo.py if present).",
    "python-cli": "It is a command-line tool: run it from a terminal.",
    "command-line": "It is a command-line tool: run it from a terminal.",
    "node-cli": "It is a Node command-line tool: run it from a terminal.",
    "node": "It is a Node command-line tool: run it from a terminal.",
    "node-web": "It is a web app: open it in a browser and look.",
    "desktop-gui": "It is a desktop app: open it and look.",
    "web": "It is a web app: open it in a browser and look.",
}

_BAND_HEADLINE: dict[str, str] = {
    BAND_A: "Looks clean — no problems the automatic audit could find.",
    BAND_B: "Works, with some rough edges worth knowing about.",
    BAND_C: "Works on its tests, but the audit flagged something worth your eyes before you rely on it.",
}


@dataclass(frozen=True)
class WhatYouGotCard:
    """The plain-language operator card for one GREEN."""

    job_id: str
    surface: str
    band: str
    headline: str
    run_hint: str
    #: The ONE honest caveat (or "" when the audit found nothing to warn about).
    caveat: str

    def render(self) -> str:
        """The multi-line operator-facing block (goes into the run's SUMMARY-style output)."""
        lines = [f"What you got ({self.job_id}): {self.headline}", f"  How to use it: {self.run_hint}"]
        if self.caveat:
            lines.append(f"  One thing to watch: {self.caveat}")
        return "\n".join(lines)

    def to_evidence(self) -> str:
        """A single-line, capped caveat summary for ``evidence.green_quality_card`` (S6:
        pointers + short statuses, never multi-line). The full card lives in the sidecar."""
        core = self.caveat or self.headline
        flat = re.sub(r"\s+", " ", f"[{self.band}] {core}").strip()
        return flat[:EVIDENCE_VALUE_CAP]


def _caveat_from_layer1(layer1: Layer1Result) -> str:
    """Derive the ONE honest, plain-language caveat from the deterministic findings —
    regression first (the sharpest), then the craft residue. '' when nothing to warn about."""
    reg = layer1.regression
    # Pull the concerning input out of the probe detail ("input 'X': now ... vs was ...").
    m = re.search(r"input (?P<q>['\"].*?['\"]):", reg.detail)
    example = m.group("q") if m else ""
    if reg.regressed:
        if example:
            return (f"it may mishandle ordinary inputs like {example} — it now returns much less "
                    "than the previous version did, so double-check results on real input.")
        return "it now returns less than the previous working version did — double-check real results."
    if reg.changed:
        if example:
            return (f"its results changed from the previous version (e.g. for {example}) — "
                    "worth a quick double-check on your own input.")
        return "its behaviour changed from the previous version — worth a quick double-check."
    if layer1.no_entry_point.flagged:
        return "there is no ready-made way to run it without writing a little code."
    if layer1.dead_scaffold.flagged:
        return "it still contains some unused starter code that was never cleaned up (harmless, but untidy)."
    if layer1.stale_readme.flagged:
        return "its README still describes the empty starter project, not what was actually built."
    return ""


def build_card(
    job_id: str,
    surface: str,
    band: str,
    layer1: Layer1Result,
    *,
    jury_uncertain: Optional[list[str]] = None,
) -> WhatYouGotCard:
    """Assemble the surface-aware card. The run hint adapts to the declared surface (never
    the generic 'open the app'); the caveat is mechanically derived from Layer 1."""
    surf = str(surface or layer1.surface or "").strip().lower()
    run_hint = _SURFACE_RUN_HINT.get(surf, "Ask for a quick how-to-run note — the surface was not recognised.")
    headline = _BAND_HEADLINE.get(band, _BAND_HEADLINE[BAND_B])
    return WhatYouGotCard(
        job_id=job_id,
        surface=surf,
        band=band,
        headline=headline,
        run_hint=run_hint,
        caveat=_caveat_from_layer1(layer1),
    )
