"""#837 QUALITY-17 — GREEN-quality-audit shared constants (the leaf every layer imports).

The GREEN-quality audit is the QUALITY companion to #832's earned-GREEN INTEGRITY audit
(`green_audit.py`): #832 asks "did the coder tamper with its grader?" (a verdict-changing
integrity gate that can downgrade GREEN→PARKED); this module asks the distinct QUALITY
question "is this banked GREEN fragile, ugly, or unusable?" — an ADVISORY, never-verdict-
changing read that composes BENEATH #832's gate (integrity first, quality second, neither
fights the other — the dossier's "integrity != quality boundary"). Nobody audited GREEN
*quality* before it — the job oracle is spec-blind, the deterministic gate is forgiving by
design, and the 14B critic is dormant + blocker-only — so a GREEN's quality was invisible
until it broke in the non-technical operator's hands (the r4greens dossier's headline: B2
text-stats banked GREEN three nights while its tokenizer silently regressed from handling
``"don't"`` to dropping it).

Two design invariants live here as constants because both are load-bearing and both are
read by more than one module:

* **The band is written ONLY under the open ``evidence`` object** (the reserved
  ``green_quality_*`` keys below). ``scorecard.schema.json`` hard-codes ``GREEN →
  attribution: ""`` and closes the verdict enum, so a quality band *physically cannot* be
  expressed as a verdict — the honesty discipline is structural, not merely documented.
* **The band (A/B/C) is computed by a DETERMINISTIC FORMULA** over scored fields
  (:mod:`~tools.dispatch_harness.green_quality.band`) — the model answers narrow
  observations, a formula renders judgment. The rubric-field enums below are the model's
  answer space; the band is never one of them.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Sidecar / schema identity
# ---------------------------------------------------------------------------

#: The advisory sidecar this audit writes into each GREEN's run dir — a SEPARATE file from
#: #832's ``green-audit.json`` (its integrity/gaming sidecar, which #827's
#: ``failure_taxonomy._gaming_signal`` reads). The two never collide: distinct filenames,
#: distinct evidence keys, distinct concerns. This quality band is carried by the battery
#: summary's ``green_quality`` block + the reserved evidence keys below; it is not a gaming
#: fingerprint and never feeds #827's GREEN-GAMED signal.
GREEN_QUALITY_SIDECAR_NAME = "green-quality.json"
GREEN_QUALITY_SCHEMA = "green-quality/v1"

# ---------------------------------------------------------------------------
# The advisory band (the "what you got" headline)
# ---------------------------------------------------------------------------

#: A — clean: no regression, no craft residue, and (if the jury ran) no concern.
BAND_A = "A"
#: B — has caveats: craft residue (dead scaffold / stale README / no runnable surface) or
#: a soft jury concern, but nothing that breaks the deliverable on ordinary input.
BAND_B = "B"
#: C — concerning: a behavior REGRESSION vs the last archived GREEN, or the jury majority
#: found an output obviously wrong, or a runnable surface the operator was promised is
#: absent. The band that most wants the operator's eyes before he relies on it.
BAND_C = "C"

#: Stable order (worst-first is how the formula resolves; A is the clean floor).
BANDS: tuple[str, ...] = (BAND_A, BAND_B, BAND_C)

# ---------------------------------------------------------------------------
# Layer-2 rubric fields (the DIVERSE-JURY answer space — narrow enums, never prose)
#
# Each field is ONE question a small (noisy) 14B can actually answer, scored as a closed
# enum. The jury emits these under a grammar constraint; the band FORMULA aggregates the
# per-field majority. A field the jury disagrees on ABSTAINS (:data:`ABSTAIN`) — stamped
# honestly as uncertain, never a guessed middling pass.
# ---------------------------------------------------------------------------

#: Does a non-coder have a way to run this? (operator-legibility lens)
FIELD_RUNNABLE_SURFACE = "runnable_surface"
RUNNABLE_VALUES: tuple[str, ...] = ("yes", "only-by-writing-code", "no")

#: On empty / malformed / edge input does a public entry point degrade gracefully?
#: (graceful-bad-input lens)
FIELD_BAD_INPUT = "bad_input_handling"
BAD_INPUT_VALUES: tuple[str, ...] = ("graceful", "throws", "unchecked")

#: Are names and module layout coherent across the whole repo? (operator-legibility lens)
FIELD_NAMING_STRUCTURE = "naming_structure"
NAMING_VALUES: tuple[str, ...] = ("clear", "mixed", "poor")

#: Given supplied real-world inputs, is any output obviously wrong? (correctness-beyond-
#: oracle lens — the critic-seam juror's wheelhouse; the deterministic probe also feeds it)
FIELD_CORRECTNESS_PROBE = "correctness_probe"
CORRECTNESS_VALUES: tuple[str, ...] = ("none", "minor", "wrong")

#: The full rubric, field -> its enum. COMPACT by mandate (a 14B degrades on long rubrics):
#: four single-focus fields, lenses SPLIT across jurors rather than any one prompt lengthened.
RUBRIC_FIELDS: dict[str, tuple[str, ...]] = {
    FIELD_RUNNABLE_SURFACE: RUNNABLE_VALUES,
    FIELD_BAD_INPUT: BAD_INPUT_VALUES,
    FIELD_NAMING_STRUCTURE: NAMING_VALUES,
    FIELD_CORRECTNESS_PROBE: CORRECTNESS_VALUES,
}

#: The honest abstain sentinel — a field the jury could not agree on. Stamped as
#: ``uncertain``; the band formula treats an abstained field as "no signal" (it never
#: pushes the band toward a worse letter — silence is not evidence).
ABSTAIN = "uncertain"

# ---------------------------------------------------------------------------
# Reserved evidence keys (the classifier-style advisory stamp — the audit is their SOLE
# writer; it writes nothing else, and NEVER touches verdict/attribution)
# ---------------------------------------------------------------------------

EV_BAND = "green_quality_band"                       # A/B/C — DETERMINISTIC formula, not a model verdict
EV_REGRESSED = "green_quality_regressed"             # Layer-1 archetype-diff finding (no model)
EV_RUNNABLE = "green_quality_runnable_surface"       # rubric field (jury majority)
EV_BAD_INPUT = "green_quality_bad_input"             # rubric field (jury majority)
EV_DEAD_SCAFFOLD = "green_quality_dead_scaffold"     # Layer-1 lint (also a rubric lens; det wins)
EV_NAMING = "green_quality_naming_structure"         # rubric field (jury majority)
EV_CORRECTNESS = "green_quality_correctness_probe"   # rubric field (jury majority)
EV_UNCERTAIN = "green_quality_uncertain"             # fields the jury abstained on (array)
EV_FINDINGS = "green_quality_findings"               # POINTER to the sidecar, never content
EV_CARD = "green_quality_card"                       # one-line "what you got" caveat (operator legibility)
EV_MODE = "green_quality_mode"                       # which layers ran: "det-only" | "det+14b-x3"

#: Every reserved key — the advisory-stamp allowlist (the invariant test asserts the
#: audit writes only these + never a verdict/attribution).
RESERVED_EVIDENCE_KEYS: frozenset[str] = frozenset({
    EV_BAND, EV_REGRESSED, EV_RUNNABLE, EV_BAD_INPUT, EV_DEAD_SCAFFOLD,
    EV_NAMING, EV_CORRECTNESS, EV_UNCERTAIN, EV_FINDINGS, EV_CARD, EV_MODE,
})

# ---------------------------------------------------------------------------
# Audit modes (which layers actually ran — honest about depth)
# ---------------------------------------------------------------------------

#: Layer 1 only — the deterministic floor (no GPU). The standing overnight posture: the
#: 14B jury is a supervised GPU slot, so the battery runs det-only until a jury is wired.
MODE_DET_ONLY = "det-only"
#: Layer 1 + a 3-juror 14B rubric ensemble (the GPU-window depth).
MODE_DET_JURY = "det+14b-x3"

#: One-line cap for any evidence value (mirrors the scorecard S6 discipline — pointers +
#: short statuses, never raw logs; the scorecard writer caps at 1000, we stay well under).
EVIDENCE_VALUE_CAP = 300
