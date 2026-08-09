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

#1182 adds the security scan (:mod:`~tools.dispatch_harness.green_quality.security`) as a
third input, and it is the ONE deterministic check that forces C on its own — deliberately
breaking the rule stated below for craft lints. The reason is cost asymmetry, not importance:
a craft lint reads a proxy ("no demo.py" for "hard to run") and a false C there costs the
operator a pointless look, while a security finding is the literal presence of a named
construct at a named line, and a false A there hands a non-technical operator a deliverable
with a live credential or an injection hole in it and tells him it looks clean. The scan is
also the one check whose SILENCE is dangerous: an unmeasured security scan is a B caveat, not
an A, because "we could not look" must never render as "we looked and it was fine". Silence
and emptiness are not the same thing, either — a scan that stopped early still reports what it
had already found, and those findings set the band exactly as a completed scan's would.

#1281 adds the placeholder-prose scan
(:mod:`~tools.dispatch_harness.green_quality.placeholder_prose`) as a fourth input, and it is
deliberately the QUIETEST of them. An unambiguous finding — Latin filler, or copy that
instructs someone to replace it — is a B caveat, which is that ticket's stated predicate: a
delivery that ships lorem ipsum is REPORTED rather than banded A. It is never a C, because
the cost asymmetry that earns security its C runs the other way here: a page of filler costs
the operator a reread, not a leaked credential. Its MEDIUM tier (starter boilerplate, a
scaffold's default title, template contact details) is recorded and rendered but never
band-moving at all, because each of those is conceivably deliberate and a control that
convicts a real choice is a control that gets muted.

Its silence is likewise NOT a caveat, which inverts the security rule above and is argued
rather than assumed: a tree unreadable enough to blind this scan blinds every Layer-1 lint
too, and spending a band on "the wording check could not run" would buy noise at the price of
the caveat the operator can act on. The unmeasured state is still stamped, still counted and
still rendered — it simply does not move a letter.

WHETHER A PROSE RESULT REACHES THIS FUNCTION AT ALL is not decided here, and deliberately so.
The composing caller (:func:`~tools.dispatch_harness.green_quality.audit_green`) passes
``prose=None`` unless ``[fleet_dispatch].green_quality_prose_band`` grants the contribution —
read that flag's value from the config, never from this docstring. Keeping the gate at the
composition seam rather than inside this module is what preserves the property the first
paragraph claims: this function stays PURE and TOTAL, deciding the band from its arguments and
from nothing else, and ``prose=None`` keeps its one existing meaning — no signal was supplied.
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
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
)
from .jury import JuryResult
from .layer1 import Layer1Result
from .placeholder_prose import RULE_PLAIN_LANGUAGE as PROSE_PLAIN_LANGUAGE, ProseResult
from .security import RULE_PLAIN_LANGUAGE, SecurityResult

#: A ruff finding count at/above this is a soft B trigger (a repo with dozens of style
#: violations shipped a no-cleanup pass). Below it, ruff is noted but not band-moving —
#: advisory ruff is a hint, not a verdict.
_RUFF_B_THRESHOLD = 10

#: Security findings named in a band reason before the reason is summarised. Enough for the
#: operator to see the shape of the problem, bounded so one bad file cannot flood the card.
_SECURITY_REASON_CAP = 3

#: Placeholder-prose findings named before the reason is summarised. One filler paragraph
#: repeated across six pages is one problem, not six band reasons.
_PROSE_REASON_CAP = 3


def _security_reasons(security: SecurityResult) -> tuple[list[str], list[str]]:
    """``(c_reasons, b_reasons)`` from the security scan.

    HIGH findings force C; MEDIUM findings are caveats; INFO is recorded in the sidecar but
    never band-moving. An UNMEASURED scan is a B caveat naming itself as unmeasured — the
    fail-closed reading of a fail-soft control (principles 1 + 11: no fail-opens, and a
    control that degrades silently is worse than none).

    ``measured`` does not gate the findings, and that ordering is the whole correctness of
    this function. An interrupted walk returns what it already found, so early-returning on
    ``not measured`` discarded a HIGH credential and banded B — while the KPI line counted
    the same finding, leaving the instrument contradicting itself about one run. Both facts
    reach the band: the findings drive the letter, and the unfinished walk is a caveat on
    top."""
    c: list[str] = []
    b: list[str] = []
    if not security.measured:
        b.append(f"the security scan did not complete ({security.status}) — this is NOT a "
                 f"clean result, only a partial one; anything listed alongside this was "
                 f"found before it stopped, and there may be more")
    for finding in security.at_or_above(SEVERITY_HIGH)[:_SECURITY_REASON_CAP]:
        c.append(f"security: {finding.rule} at {finding.path}:{finding.line} — "
                 f"{RULE_PLAIN_LANGUAGE.get(finding.rule, 'see the sidecar for detail')}")
    medium = [f for f in security.at_or_above(SEVERITY_MEDIUM) if f.severity == SEVERITY_MEDIUM]
    for finding in medium[:_SECURITY_REASON_CAP]:
        b.append(f"security: {finding.rule} at {finding.path}:{finding.line} — "
                 f"{RULE_PLAIN_LANGUAGE.get(finding.rule, 'see the sidecar for detail')}")
    return (c, b)


def _prose_reasons(prose: ProseResult) -> list[str]:
    """The B reasons from the placeholder-prose scan — never C reasons, and never a caveat
    for its own silence (this module's docstring argues both asymmetries).

    ONLY the unambiguous tier lands here. Latin filler and "your text here" cannot be the
    words the operator asked for whatever he asked for, so they are worth a letter; a
    scaffold's default ``<title>`` or a template phone number is near-certain but conceivably
    deliberate, and it reaches the sidecar, the stamp and the rollup without moving a band.

    ``measured`` does not gate the findings, for the reason :func:`_security_reasons` states
    at length: an interrupted walk returns what it already found, and early-returning on
    ``not measured`` would drop a real finding while the rollup went on counting it. The
    unfinished walk is reported in the status and the stamp instead of as a band reason."""
    reasons: list[str] = []
    high = prose.at_or_above(SEVERITY_HIGH)
    for finding in high[:_PROSE_REASON_CAP]:
        reasons.append(f"placeholder prose: {finding.rule} at {finding.path}:{finding.line} — "
                       f"{PROSE_PLAIN_LANGUAGE.get(finding.rule, 'see the sidecar for detail')}")
    return reasons


def band_reasons(
    layer1: Layer1Result,
    jury: Optional[JuryResult],
    security: Optional[SecurityResult] = None,
    prose: Optional[ProseResult] = None,
) -> tuple[str, list[str], list[str]]:
    """Return ``(band, c_reasons, b_reasons)`` — the band plus the NAMED triggers behind it,
    so the evidence + card can say *why* a GREEN scored C or B (never an opaque letter).

    Pure + total. This is the ONLY place the band is decided; :func:`compute_band` is the
    thin wrapper the rest of the package calls. ``security=None`` means the scan was not
    supplied by this caller at all (a partial composition, e.g. a band computed from a
    Layer-1 fixture in a test); it carries no signal, unlike a SUPPLIED result whose
    ``measured`` flag is False, which is the audited "could not determine" caveat. ``prose``
    follows the same convention and the same distinction."""
    c_reasons: list[str] = []
    b_reasons: list[str] = []

    if security is not None:
        sec_c, sec_b = _security_reasons(security)
        c_reasons.extend(sec_c)
        b_reasons.extend(sec_b)
    if prose is not None:
        b_reasons.extend(_prose_reasons(prose))

    # --- C triggers (worst; a MEASURED break on real input, or the jury READING that the
    # deliverable is unusable/wrong). A deterministic craft heuristic never alone forces C —
    # only a measured regression or a model READ (which sees more than a lint) does.
    # EVERY layer-1 trigger below is written `measured and <claim>`, and the guard is not
    # redundant belt-and-braces: it is the difference between a band that HOLDS this rule and
    # a band that merely happens to satisfy it. Each of these instruments currently returns a
    # falsy claim when it could not look, so today the guard changes nothing — which is
    # precisely why it was never written, and why an instrument whose unmeasured value ever
    # became truthy would have moved the band with nobody noticing. The rule the guard states
    # out loud: a band says something about the DELIVERABLE, and a check that could not run
    # says nothing about it. The unknown is reported in `Layer1Result.findings()` instead, so
    # it is loud without being blamed on the coder. (Security is the deliberate exception —
    # see this module's docstring: its silence is the one silence that is itself dangerous.)
    if layer1.regression.measured and layer1.regression.regressed:
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
    if layer1.regression.measured and layer1.regression.changed \
            and not layer1.regression.regressed:
        b_reasons.append(f"behaviour changed vs the last archived GREEN ({layer1.regression.detail})")
    # The deterministic no-entry-point lint is a caveat, not a break: the thing WORKS, the
    # operator just needs to write a little code to run it (the jury's "no" above is the
    # stronger, read-based signal that escalates it to C).
    if layer1.no_entry_point.measured and layer1.no_entry_point.flagged:
        b_reasons.append(layer1.no_entry_point.detail)
    if layer1.dead_scaffold.measured and layer1.dead_scaffold.flagged:
        b_reasons.append(layer1.dead_scaffold.detail)
    if layer1.stale_readme.measured and layer1.stale_readme.flagged:
        b_reasons.append(layer1.stale_readme.detail)
    # A delivered file still identical to the fleet seed is craft residue of the same class —
    # the deliverable works, its documentation describes a starter project. An UNMEASURED seed
    # check never lands here: the band states something about the DELIVERABLE, and a seed the
    # auditor could not read says nothing about it (the same rule that keeps an unmeasured
    # regression probe out of the band). The unknown is reported in `findings()` instead, so it
    # is loud without being blamed on the coder.
    if layer1.seed_divergence.measured and layer1.seed_divergence.flagged:
        b_reasons.append(layer1.seed_divergence.detail)
    # `is not None`, never truthiness. The old `if layer1.ruff_findings and …` read as a None
    # guard and worked as one only by accident of `0 >= 10` being false anyway; ruff's status
    # IS its Optional sentinel (#1189), so the one place it is consulted must say so.
    if layer1.ruff_findings is not None and layer1.ruff_findings >= _RUFF_B_THRESHOLD:
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


def compute_band(
    layer1: Layer1Result,
    jury: Optional[JuryResult] = None,
    security: Optional[SecurityResult] = None,
    prose: Optional[ProseResult] = None,
) -> str:
    """The A/B/C band for one GREEN — a deterministic function of scored fields ONLY.

    ``jury=None`` (the standing det-only posture, no GPU) computes the band from Layer 1
    alone; a wired jury adds its per-field MAJORITY (abstained fields excluded); a supplied
    security scan adds its findings (and its own inability to run); a supplied prose scan adds
    its unambiguous findings only. The model is nowhere in this function — that is the point."""
    return band_reasons(layer1, jury, security, prose)[0]
