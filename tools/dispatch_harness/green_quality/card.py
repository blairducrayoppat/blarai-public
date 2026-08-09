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

from .constants import BAND_A, BAND_B, BAND_C, EVIDENCE_VALUE_CAP, SEVERITY_HIGH, SEVERITY_MEDIUM
from .layer1 import Layer1Result
from .placeholder_prose import RULE_PLAIN_LANGUAGE as PROSE_PLAIN_LANGUAGE, ProseResult
from .security import RULE_PLAIN_LANGUAGE, SecurityResult

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


def _and_unfinished(caveat: str, measured: bool) -> str:
    """Carry a finding's caveat AND the fact that the scan stopped early, in one sentence the
    operator reads once. The finding leads because it is the half he can act on."""
    if measured:
        return caveat
    return (caveat.rstrip().rstrip(".")
            + " — and the check did not finish, so there may be more it never looked at.")


def _caveat_from_security(security: Optional[SecurityResult]) -> str:
    """The security caveat, or '' when there is nothing to say. Ranked ABOVE every other
    caveat in :func:`_caveat_from_layer1` because it is the only finding class where acting
    on the deliverable — publishing the site, pointing it at real data — is what makes the
    problem expensive; a behaviour change merely wants a double-check.

    A scan that could not run says so. The operator's card is where a silent security
    degradation would do its damage, so this is the one place the audit must volunteer its
    own blind spot rather than let band A's 'looks clean' speak for it.

    An INTERRUPTED scan that already found something says BOTH — the finding first, because
    it is the actionable half, then the unfinished walk. Checking ``measured`` above the
    findings suppressed the credential entirely and told the operator only that a check had
    not run, which reads as "nothing to see" for the one deliverable that had something."""
    if security is None:
        return ""
    high = security.at_or_above(SEVERITY_HIGH)
    if high:
        return _and_unfinished(RULE_PLAIN_LANGUAGE.get(
            high[0].rule, "the security check flagged something worth a look before you rely "
                          "on it."), security.measured)
    medium = [f for f in security.at_or_above(SEVERITY_MEDIUM) if f.severity == SEVERITY_MEDIUM]
    if medium:
        return _and_unfinished(RULE_PLAIN_LANGUAGE.get(
            medium[0].rule, "the security check flagged something minor worth knowing about."),
            security.measured)
    if not security.measured:
        return ("the automatic security check could not run on this one, so treat "
                "'no problems found' as unknown rather than as a clean bill of health.")
    return ""


def _caveat_from_prose(prose: Optional[ProseResult]) -> str:
    """The placeholder-prose caveat, or '' when there is nothing to say.

    RANKED BELOW SECURITY AND ABOVE THE CRAFT LINTS, which is a judgment about the operator's
    single caveat slot rather than about importance. Security first because acting on the
    deliverable is what makes that problem expensive. Prose second because "the page still
    says lorem ipsum" is the one finding a non-technical reader can verify with his own eyes
    in five seconds, and it makes the difference between a site he can show someone and one he
    cannot — where "some unused starter code was left behind" does not.

    ONLY THE UNAMBIGUOUS TIER SPEAKS HERE, on the same reasoning as the band: a scaffold's
    default title is worth recording and is not worth the operator's one caveat.

    The card does NOT volunteer an unmeasured prose scan, and that is deliberate rather than
    an oversight — the same call :func:`_caveat_from_layer1` makes for the craft lints, and
    the opposite of the one :func:`_caveat_from_security` makes. Spending the slot on "the
    wording check could not run" would displace a finding he can act on, and the absence is
    stated in the sidecar, the evidence stamp and the night's rollup regardless.

    WHETHER A PROSE RESULT IS SUPPLIED at all is the composing caller's decision, gated on
    ``[fleet_dispatch].green_quality_prose_band`` (read the config for its value, never this
    docstring). The displacement argued above is exactly why that gate exists and why it starts
    closed: the ordering in :func:`build_card` puts prose ABOVE the craft lints, so a wrong
    prose sentence does not merely add noise to the card — it removes a true one."""
    if prose is None:
        return ""
    high = prose.at_or_above(SEVERITY_HIGH)
    if high:
        return _and_unfinished(PROSE_PLAIN_LANGUAGE.get(
            high[0].rule, "one of its pages still carries placeholder text rather than real "
                          "words."), prose.measured)
    return ""


def _caveat_from_layer1(layer1: Layer1Result) -> str:
    """Derive the ONE honest, plain-language caveat from the deterministic findings —
    regression first (the sharpest), then the craft residue. '' when nothing to warn about.

    Every branch is gated on the producing check's ``measured`` bit, because a caveat is a
    statement about the DELIVERABLE and an unmeasured lint supports none. Today each of these
    returns ``flagged=False`` when it could not look, so the guards change no card that has
    ever been rendered; they are here because "the caveat happens to be right" and "the caveat
    cannot be wrong" are different properties, and only the second survives an edit.

    THE CARD DOES NOT VOLUNTEER AN UNMEASURED CRAFT LINT, and that is a deliberate call
    rather than an oversight. The card carries exactly ONE caveat, and it is the operator's
    whole window into quality; spending it on "a tidiness check could not run" would displace
    the finding he can act on. A tree unreadable enough to blind these lints also blinds the
    regression probe, and ``Layer1Result.findings()`` states every one of those absences in
    the full report and the sidecar. Security is the deliberate exception above — see
    :func:`_caveat_from_security` for why its silence is the one silence worth the slot."""
    reg = layer1.regression
    # Pull the concerning input out of the probe detail ("input 'X': now ... vs was ...").
    m = re.search(r"input (?P<q>['\"].*?['\"]):", reg.detail)
    example = m.group("q") if m else ""
    if reg.measured and reg.regressed:
        if example:
            return (f"it may mishandle ordinary inputs like {example} — it now returns much less "
                    "than the previous version did, so double-check results on real input.")
        return "it now returns less than the previous working version did — double-check real results."
    if reg.measured and reg.changed:
        if example:
            return (f"its results changed from the previous version (e.g. for {example}) — "
                    "worth a quick double-check on your own input.")
        return "its behaviour changed from the previous version — worth a quick double-check."
    if layer1.no_entry_point.measured and layer1.no_entry_point.flagged:
        return "there is no ready-made way to run it without writing a little code."
    if layer1.dead_scaffold.measured and layer1.dead_scaffold.flagged:
        return "it still contains some unused starter code that was never cleaned up (harmless, but untidy)."
    seed = layer1.seed_divergence
    if seed.measured and seed.flagged:
        # Ranked ABOVE the marker lint below: this one is measured against the actual template,
        # so it is the sharper statement of the same complaint.
        if "README.md" in seed.identical:
            return ("its README is word-for-word the starter template — nothing was written "
                    "about what you actually got.")
        return ("its project description is still the starter template's placeholder text, "
                "not a description of what was built.")
    if layer1.stale_readme.measured and layer1.stale_readme.flagged:
        return "its README still describes the empty starter project, not what was actually built."
    return ""


def build_card(
    job_id: str,
    surface: str,
    band: str,
    layer1: Layer1Result,
    *,
    jury_uncertain: Optional[list[str]] = None,
    security: Optional[SecurityResult] = None,
    prose: Optional[ProseResult] = None,
) -> WhatYouGotCard:
    """Assemble the surface-aware card. The run hint adapts to the declared surface (never
    the generic 'open the app'); the caveat is mechanically derived, security first, then
    placeholder prose, then the Layer-1 craft residue."""
    surf = str(surface or layer1.surface or "").strip().lower()
    run_hint = _SURFACE_RUN_HINT.get(surf, "Ask for a quick how-to-run note — the surface was not recognised.")
    headline = _BAND_HEADLINE.get(band, _BAND_HEADLINE[BAND_B])
    return WhatYouGotCard(
        job_id=job_id,
        surface=surf,
        band=band,
        headline=headline,
        run_hint=run_hint,
        caveat=(_caveat_from_security(security)
                or _caveat_from_prose(prose)
                or _caveat_from_layer1(layer1)),
    )
