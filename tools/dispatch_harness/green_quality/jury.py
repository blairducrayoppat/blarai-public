"""#837 Layer 2 — the DIVERSE small-model jury (constrained-rubric scorer, GREEN-only).

A 14B is a noisy judge, so this layer is emphatically NOT "review this code." It is the
literature-backed shape for a constrained calibration budget (Judge-Panel Finite-
Calibration Regime Map, arXiv 2606.01034): a panel of DIVERSE small jurors, each answering
the SAME compact enum-scored rubric under a GRAMMAR CONSTRAINT, aggregated by a per-field
MAJORITY with ABSTAIN-on-disagreement. Diversity comes from a per-juror lens EMPHASIS (one
leans correctness-beyond-oracle, one graceful-bad-input, one operator-legibility) plus a
distinct seed — decorrelating the errors a homogeneous panel would repeat. The band is NOT
asked of the jury; a deterministic formula (:mod:`~tools.dispatch_harness.green_quality.band`)
renders it from these fields.

Reuse, not new machinery (dossier §4.7 R2): the correctness-lens juror is the DORMANT 14B
critic's seam turned read-only — its wheelhouse ("a specific input that yields a wrong
output") is exactly the correctness field, and its model call is the same cross-model swap
the critic already owns (:func:`shared.fleet.swap_ops.real_run_critic`, bounded by the
registered ``CRITIC_RUN_TIMEOUT_S``). We keep the critic's findings, discard its verdict.

GPU reality: the jury runs are 14B slots, so this module is built to run OFFLINE now — the
model call is injected (:class:`Juror.structured_generate_fn`), tests pass fakes, and the
live 3-juror pass is a supervised GPU-window slot. ``build_default_jury(None)`` returns
``None`` (the standing det-only posture); nothing here loads a model on import.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Optional

from .constants import (
    ABSTAIN,
    RUBRIC_FIELDS,
)

#: A juror's model call — the SAME ``(prompt, json_schema_text) -> str`` shape the #743
#: ``_grammar_first`` hook drives. Offline it is a fake; live it is backed by the critic
#: swap-seam. Returns the raw constrained emission text (grammar-pinned JSON).
StructuredGenerateFn = Callable[[str, str], str]


# ---------------------------------------------------------------------------
# The rubric emission schema (grammar-constrained — every field enum-pinned)
# ---------------------------------------------------------------------------


def green_quality_emission_json_schema(*, max_findings: int = 4) -> dict:
    """The JSON schema for one juror's grammar-constrained rubric emission — every rubric
    field pinned to its closed enum, ``additionalProperties: false``, and a bounded free-
    text ``findings`` array (short observations, never prose paragraphs). A 14B constrained
    to enums is far less noisy than one writing prose — the same discipline that made the
    #718/#743 tool-call + plan emissions reliable."""
    return {
        "type": "object",
        "properties": {
            **{
                name: {"enum": list(values)}
                for name, values in RUBRIC_FIELDS.items()
            },
            "findings": {
                "type": "array",
                "maxItems": max_findings,
                "items": {"type": "string", "maxLength": 200},
            },
        },
        "required": list(RUBRIC_FIELDS.keys()),
        "additionalProperties": False,
    }


def _usable_emission(text: str) -> bool:
    """True iff *text* carries a JSON object that scores at least one rubric field with a
    LEGAL enum value — the ``usable`` predicate ``_grammar_first`` gates on."""
    return bool(parse_emission(text))


def parse_emission(text: str) -> dict[str, str]:
    """Extract ``{field: enum_value}`` for every rubric field the emission scored with a
    LEGAL value (illegal/absent fields are dropped — never coerced to a middling guess).
    ``{}`` on unparseable input (the juror then abstains everywhere). Total; never raises."""
    if not isinstance(text, str) or not text:
        return {}
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {}
    try:
        obj = json.loads(match.group(0))
    except (ValueError, TypeError):
        return {}
    if not isinstance(obj, dict):
        return {}
    out: dict[str, str] = {}
    for name, values in RUBRIC_FIELDS.items():
        val = obj.get(name)
        if isinstance(val, str) and val in values:
            out[name] = val
    return out


# ---------------------------------------------------------------------------
# One juror
# ---------------------------------------------------------------------------

#: The three diverse lenses. The prompt EMPHASIS differs per juror (the diversity that
#: decorrelates errors); every juror still scores every field so each gets a full 3-vote
#: majority. LENS_CORRECTNESS is the reused critic seam's lens.
LENS_CORRECTNESS = "correctness-beyond-oracle"
LENS_BAD_INPUT = "graceful-bad-input"
LENS_LEGIBILITY = "operator-legibility"
LENSES: tuple[str, ...] = (LENS_CORRECTNESS, LENS_BAD_INPUT, LENS_LEGIBILITY)

_LENS_EMPHASIS: dict[str, str] = {
    LENS_CORRECTNESS: (
        "Pay special attention to CORRECTNESS on inputs the oracle never tried: given the "
        "supplied real-world inputs, does any public entry point produce an obviously wrong "
        "answer? (This is the code-critic's lens.)"
    ),
    LENS_BAD_INPUT: (
        "Pay special attention to BAD-INPUT handling: on empty, malformed, or edge input, "
        "does a public entry point degrade gracefully, or throw, or silently mishandle it?"
    ),
    LENS_LEGIBILITY: (
        "Pay special attention to OPERATOR LEGIBILITY: could a non-programmer actually run "
        "this, and are the names and module layout coherent across the whole repo?"
    ),
}


@dataclass(frozen=True)
class Juror:
    """One diverse juror: a lens emphasis + a seed + the injected model call. The prompt is
    built COMPACT — a fixed rubric-question block plus ONE emphasis line (never four lenses
    in one prompt: a 14B degrades on long rubrics)."""

    lens: str
    structured_generate_fn: StructuredGenerateFn
    seed: int = 0

    def build_prompt(self, subject: str) -> str:
        emphasis = _LENS_EMPHASIS.get(self.lens, "")
        return (
            "You are auditing the QUALITY of a program that already passed its tests. Answer "
            "ONLY the rubric below, each field as one of its listed choices. Do not write "
            "prose; do not re-grade whether it works.\n"
            f"{emphasis}\n\n"
            "RUBRIC (choose exactly one value per field):\n"
            "- runnable_surface: yes | only-by-writing-code | no\n"
            "- bad_input_handling: graceful | throws | unchecked\n"
            "- naming_structure: clear | mixed | poor\n"
            "- correctness_probe: none | minor | wrong\n\n"
            f"SUBJECT:\n{subject}\n"
        )


@dataclass(frozen=True)
class JurorVote:
    """One juror's scored fields (only the fields it emitted a LEGAL value for)."""

    lens: str
    fields: dict[str, str] = field(default_factory=dict)


def run_juror(juror: Juror, subject: str, *, max_findings: int = 4) -> JurorVote:
    """Run one juror over *subject* via the #743 ``_grammar_first`` hook and return its
    scored fields. Wholly FAIL-SOFT: a missing hook, a raising model, or an unparseable
    emission all yield an EMPTY vote (the juror abstains on every field) — never an
    exception, and never a fabricated score."""
    try:  # lazily reuse the existing grammar hook (kept out of import to keep the package light)
        from shared.fleet.acceptance import _grammar_first
    except Exception:  # noqa: BLE001 — no hook available -> this juror abstains
        return JurorVote(juror.lens, {})
    raw = _grammar_first(
        juror.build_prompt(subject),
        structured_generate_fn=juror.structured_generate_fn,
        schema=green_quality_emission_json_schema(max_findings=max_findings),
        usable=_usable_emission,
    )
    if not raw:
        return JurorVote(juror.lens, {})
    return JurorVote(juror.lens, parse_emission(raw))


# ---------------------------------------------------------------------------
# The jury (per-field majority + abstain-on-disagreement)
# ---------------------------------------------------------------------------


@dataclass
class JuryResult:
    """The aggregated jury verdict: per field, the MAJORITY value or :data:`ABSTAIN`."""

    #: field -> majority value, or ABSTAIN where the panel disagreed / lacked a majority.
    scores: dict[str, str] = field(default_factory=dict)
    #: fields that abstained (stamped honestly — never a guessed middling pass).
    uncertain: list[str] = field(default_factory=list)
    #: how many jurors voted (for the mode stamp / evidence).
    juror_count: int = 0

    def value(self, field_name: str) -> Optional[str]:
        """The majority value for *field_name*, or ``None`` when it abstained/was unscored.
        ``None`` is the band formula's 'no signal' — it never worsens the band."""
        v = self.scores.get(field_name)
        return None if v in (None, ABSTAIN) else v


def _majority(values: list[str], *, panel_size: int) -> Optional[str]:
    """The value ≥2 jurors agree on (a real majority of a small panel), or ``None`` (abstain)
    when the top value has fewer than 2 votes or ties another at 2 (impossible for n≤3, kept
    for robustness). A single lone vote is NOT a majority — it abstains, honestly."""
    if not values:
        return None
    counts = Counter(values)
    (top, top_n), = counts.most_common(1)
    if top_n < 2:
        return None
    # No other value may also reach the winning count (a genuine tie -> abstain).
    if sum(1 for _v, n in counts.items() if n == top_n) > 1:
        return None
    return top


def tally(votes: list[JurorVote]) -> JuryResult:
    """Aggregate juror votes into per-field majorities with honest abstention. A field with
    no ≥2 agreement is ABSTAINED and named in ``uncertain`` — the honest ``ok=None`` the
    dossier demands, never a guessed pass."""
    result = JuryResult(juror_count=len(votes))
    for name in RUBRIC_FIELDS:
        cast = [v.fields[name] for v in votes if name in v.fields]
        winner = _majority(cast, panel_size=len(votes))
        if winner is None:
            result.scores[name] = ABSTAIN
            result.uncertain.append(name)
        else:
            result.scores[name] = winner
    return result


def run_jury(jurors: list[Juror], subject: str, *, max_findings: int = 4) -> JuryResult:
    """Run every juror over *subject* and tally the majority. Fail-soft end-to-end (a juror
    that errors simply abstains); an EMPTY juror list yields an all-abstain result."""
    votes = [run_juror(j, subject, max_findings=max_findings) for j in jurors]
    return tally(votes)


def build_default_jury(
    structured_generate_fn: Optional[StructuredGenerateFn],
) -> Optional[list[Juror]]:
    """The standard 3-juror diverse panel over ONE model call, or ``None`` when no model is
    wired (the standing det-only posture — Layer 2 is a supervised GPU slot).

    All three share the injected ``structured_generate_fn`` (one 14B load) but differ by
    lens emphasis + seed — the correctness juror is the reused critic seam's lens. To vary a
    second local model per juror, pass a dispatcher fn that routes on the seed; the shape is
    unchanged."""
    if structured_generate_fn is None:
        return None
    return [Juror(lens, structured_generate_fn, seed=i) for i, lens in enumerate(LENSES)]
