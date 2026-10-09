"""#1231 reconciliation lock — the GREEN-quality JURY's published denominator (`jury.py`).

THE DEFECT CLASS THIS FILE EXISTS TO REFUSE. A grader publishes a rate or a count whose
DENOMINATOR is derived by summing its own buckets. An item that lands in NO bucket then
leaves the numerator and the denominator together, the arithmetic stays perfectly self-
consistent, and the published figure under-reports in silence — it reads cleaner than the
truth. The jury has two denominators exposed to exactly that mistake:

* **The juror population.** ``juror_count`` is published to the operator's sidecar as the
  panel's size. A juror whose model raises or emits garbage scores nothing, so a count
  derived from the votes that landed would shrink to match the buckets and report a
  3-juror panel as a 2-juror one — the SAME rubric read by fewer eyes, stamped as though
  nothing were missing.
* **The rubric-field population.** Four fields are always asked. A field with no >=2
  majority has no bucket to sit in, so a ``scores`` dict built from the winners alone would
  publish three fields and let the fourth vanish. Absence would then be how "the panel could
  not agree" is expressed, and absence is indistinguishable from "never asked".

Both are SOUND today, and this file is the regression lock that keeps them sound.

LOCK THE SURFACE THAT SHIPS (lesson 354). The in-memory :class:`JuryResult` is not what
reaches anybody. Two artifacts do, and both are asserted here on the far side of the REAL
battery-close entry point (:func:`audit_greens`), driven over a REAL temp tree of REAL
files with REAL :class:`Juror` objects:

* the ``jury`` block of ``green-quality.json``, READ BACK OFF DISK rather than off the
  result object, because the file is what a later reader opens;
* the reserved ``green_quality_*`` evidence stamp on the Scorecard — the run record the
  operator's night is reconstructed from. Its four rubric keys are written ONLY when the
  field carried a majority, which is legitimate only because ``green_quality_uncertain``
  NAMES every field that did not. Those two halves are one statement, and every test below
  asserts them together: published fields + uncertain fields == the whole rubric, always.

The model call is injected here (``Juror.structured_generate_fn``) exactly as the security
and prose scanners are injected in this suite's siblings — that seam is the module's own
design (Layer 2 is a supervised GPU slot), not a mock of the thing under test. The grader
— ``run_jury``/``tally``, the audit, the sidecar writer, the stamp — is real throughout.

RESIDUAL, deliberately NOT asserted here: ``card.build_card`` accepts ``jury_uncertain``
and discards it, so the jury's shortfall reaches the sidecar and the stamp but never the
plain-language card. That is card.py's defect, not jury.py's, and locking it would freeze
a wrong behaviour rather than a right one.
"""

from __future__ import annotations

import json
from pathlib import Path

from tools.dispatch_harness.green_quality import audit_greens
from tools.dispatch_harness.green_quality.constants import (
    ABSTAIN,
    EV_BAD_INPUT,
    EV_CORRECTNESS,
    EV_MODE,
    EV_NAMING,
    EV_RUNNABLE,
    EV_UNCERTAIN,
    FIELD_BAD_INPUT,
    FIELD_CORRECTNESS_PROBE,
    FIELD_NAMING_STRUCTURE,
    FIELD_RUNNABLE_SURFACE,
    GREEN_QUALITY_SIDECAR_NAME,
    MODE_DET_JURY,
    RUBRIC_FIELDS,
)
from tools.dispatch_harness.green_quality.jury import Juror
from tools.dispatch_harness.scorecard import Scorecard, validate

#: field -> the reserved evidence key it is published under. The stamp writes a key only
#: when the field carried a majority, so this mapping is how a test asks "which fields did
#: the operator's run record actually receive a value for?"
_FIELD_TO_EV_KEY: dict[str, str] = {
    FIELD_RUNNABLE_SURFACE: EV_RUNNABLE,
    FIELD_BAD_INPUT: EV_BAD_INPUT,
    FIELD_NAMING_STRUCTURE: EV_NAMING,
    FIELD_CORRECTNESS_PROBE: EV_CORRECTNESS,
}

# ---------------------------------------------------------------------------
# A real deliverable on disk — the tree the audit resolves and Layer 1 lints.
#
# Deliberately ordinary: nothing here is meant to move the band. The band is not what this
# file locks; the published population is.
# ---------------------------------------------------------------------------


def _make_repo(root: Path) -> Path:
    """A small python-lib deliverable of the battery's ordinary shape, written to disk."""
    (root / "budget").mkdir(parents=True, exist_ok=True)
    (root / "budget" / "__init__.py").write_text("", encoding="utf-8")
    (root / "budget" / "totals.py").write_text(
        "def total(entries):\n"
        '    """Sum the amounts of every entry."""\n'
        "    return sum(e['amount'] for e in entries)\n",
        encoding="utf-8",
    )
    (root / "main.py").write_text(
        "from budget.totals import total\n\n"
        "if __name__ == '__main__':\n"
        "    print(total([{'amount': 3}, {'amount': 4}]))\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text(
        "# Budget totals\nAdd up a list of expenses and print the total.\n", encoding="utf-8"
    )
    return root


# ---------------------------------------------------------------------------
# Real jurors — three ways one lands in NO bucket
# ---------------------------------------------------------------------------


def _scoring_juror(lens: str, emission: dict) -> Juror:
    """A juror whose model returns a legal grammar-constrained emission."""
    return Juror(lens=lens, structured_generate_fn=lambda prompt, schema: json.dumps(emission))


def _raising_juror(lens: str) -> Juror:
    """THE ITEM IN NO BUCKET, form 1: the model call raises. The juror scores nothing at all,
    so every bucket-derived count would drop it — while the panel it was part of is still the
    size the operator was told about."""
    def _boom(prompt: str, schema: str) -> str:
        raise RuntimeError("juror model exploded")

    return Juror(lens=lens, structured_generate_fn=_boom)


def _garbage_juror(lens: str) -> Juror:
    """THE ITEM IN NO BUCKET, form 2: the model answers, but with nothing parseable. Distinct
    from the raiser on purpose — a count that survives an exception can still be derived from
    'votes with fields', and this juror is the one that catches that."""
    return Juror(lens=lens, structured_generate_fn=lambda prompt, schema: "I decline to score.")


#: The full agreeing emission, reused so every population below differs ONLY in its shortfall.
_AGREED = {
    FIELD_RUNNABLE_SURFACE: "yes",
    FIELD_BAD_INPUT: "graceful",
    FIELD_NAMING_STRUCTURE: "clear",
    FIELD_CORRECTNESS_PROBE: "none",
}


# ---------------------------------------------------------------------------
# The REAL entry point: battery close over a real scorecard, sidecar read off disk
# ---------------------------------------------------------------------------


def _audit(tmp_path: Path, jurors: list[Juror]) -> tuple[Scorecard, dict, dict]:
    """Drive ``audit_greens`` — the battery-close entry point — over one real GREEN.

    Returns ``(scorecard, sidecar_read_off_disk, rollup_block)``. The rollup is asserted here
    rather than in each test because ``audit_greens`` is fail-soft per card: an audit that
    RAISED would leave every population assertion below vacuously true over a jury block that
    was never written. ``audited == 1`` is what makes the rest of this file mean anything.
    """
    out_dir = tmp_path / "out"
    runs_dir = tmp_path / "runs"
    _make_repo(out_dir / "repos-archived" / "battery-b3-budget-lib")
    sc = Scorecard(job_id="B3", verdict="GREEN", repo="battery-b3-budget-lib", run_id="R1")
    block = audit_greens(
        [sc],
        runs_dir=runs_dir,
        out_dir=out_dir,
        # Hermetic: no probe set for B3, no fleet seed to compare against, and the prose
        # consequence gate pinned rather than read from live config.
        probe_dir=tmp_path / "no-probes",
        seed_root=tmp_path / "no-seed",
        job_surfaces={"B3": "python-lib"},
        jurors=jurors,
        prose_band=False,
    )
    assert block["audited"] == 1, f"the audit did not run: {block}"
    assert block["audit_failed"] == 0, f"the audit raised and was swallowed: {block}"
    sidecar = json.loads(
        (runs_dir / "R1" / GREEN_QUALITY_SIDECAR_NAME).read_text(encoding="utf-8")
    )
    return sc, sidecar, block


def _published_fields(evidence: dict) -> set[str]:
    """The rubric fields the SCORECARD actually carries a value for."""
    return {f for f, key in _FIELD_TO_EV_KEY.items() if key in evidence}


# ---------------------------------------------------------------------------
# The juror denominator: the panel size, not the count of panels that answered
# ---------------------------------------------------------------------------


def test_published_juror_count_counts_every_juror_dispatched_not_every_juror_that_scored(tmp_path):
    """Delete this and ``juror_count`` may be re-derived from the votes that carried fields.

    Four jurors are dispatched; two land in no bucket (one raises, one emits garbage). The
    sidecar the operator's run record points at must still say four. A panel silently reported
    as half its size is the #1231 shape exactly: the figure stays self-consistent, and the
    reader has no way to see that half the eyes never opened.
    """
    _sc, sidecar, _block = _audit(tmp_path, [
        _scoring_juror("correctness-beyond-oracle", _AGREED),
        _scoring_juror("graceful-bad-input", _AGREED),
        _raising_juror("operator-legibility"),
        _garbage_juror("fourth-lens"),
    ])
    assert sidecar["jury"] is not None, "a dispatched jury wrote no block at all"
    assert sidecar["jury"]["juror_count"] == 4, (
        "the published juror count shrank to the jurors that scored — the two that landed in "
        "no bucket left the numerator and the denominator together"
    )
    # The mode is the second half of the same claim: a jury that ran says so.
    assert sidecar["mode"] == MODE_DET_JURY


def test_a_panel_where_nobody_scored_still_publishes_its_full_juror_count(tmp_path):
    """Delete this and a total shortfall can publish ``juror_count: 0`` — three 14B slots
    spent, and a record that reads as though the jury never ran.

    The sharpest form of the class: EVERY bucket is empty, so a bucket-derived denominator is
    zero and perfectly self-consistent. Zero jurors dispatched and three jurors that all
    failed are different facts, and only one of them is true here.
    """
    _sc, sidecar, _block = _audit(tmp_path, [
        _raising_juror("correctness-beyond-oracle"),
        _raising_juror("graceful-bad-input"),
        _garbage_juror("operator-legibility"),
    ])
    assert sidecar["jury"]["juror_count"] == 3, (
        "the published juror count collapsed to the empty buckets — three spent 14B slots "
        "reported as a panel that never sat"
    )
    assert sidecar["jury"]["scores"], "an all-abstain jury published no scores at all"


# ---------------------------------------------------------------------------
# The rubric denominator: every field asked is accounted for, on both surfaces
# ---------------------------------------------------------------------------


def test_the_sidecar_accounts_for_every_rubric_field_when_the_panel_cannot_agree(tmp_path):
    """Delete this and ``scores`` may be built from the winners alone, so a field with no
    majority disappears from the sidecar instead of being named.

    The population: two jurors agree on three fields and split on ``naming_structure``, and
    two more land in no bucket. Three fields therefore carry a majority and one does not. The
    published dict must still hold all four — the fourth marked ABSTAIN and NAMED in
    ``uncertain`` — because a missing key cannot be told apart from a question never asked.
    """
    _sc, sidecar, _block = _audit(tmp_path, [
        _scoring_juror("correctness-beyond-oracle", _AGREED),
        _scoring_juror("graceful-bad-input", {**_AGREED, FIELD_NAMING_STRUCTURE: "mixed"}),
        _raising_juror("operator-legibility"),
        _garbage_juror("fourth-lens"),
    ])
    jury_block = sidecar["jury"]
    assert set(jury_block["scores"]) == set(RUBRIC_FIELDS), (
        "the published scores dropped a rubric field instead of abstaining on it"
    )
    assert jury_block["scores"][FIELD_NAMING_STRUCTURE] == ABSTAIN
    assert FIELD_NAMING_STRUCTURE in jury_block["uncertain"], (
        "the split field was absorbed: abstained in the dict but not disclosed in `uncertain`"
    )
    # The reconciliation itself: decided + uncertain == the whole rubric, no overlap, no gap.
    decided = {f for f, v in jury_block["scores"].items() if v != ABSTAIN}
    uncertain = set(jury_block["uncertain"])
    assert decided.isdisjoint(uncertain), "a field was published as decided AND as uncertain"
    assert decided | uncertain == set(RUBRIC_FIELDS), (
        f"decided {sorted(decided)} + uncertain {sorted(uncertain)} does not reconcile to the "
        f"rubric {sorted(RUBRIC_FIELDS)}"
    )
    assert len(decided) + len(uncertain) == len(RUBRIC_FIELDS) == 4


def test_the_scorecard_stamp_names_every_rubric_field_it_did_not_publish(tmp_path):
    """Delete this and the stamp can quietly omit a field the panel split on.

    THE SHIPPING SURFACE, and the one that matters most: the reserved ``green_quality_*``
    evidence on the Scorecard is what the operator's run record carries — the sidecar is a
    pointer away, the stamp is right there. Four rubric keys are written CONDITIONALLY, which
    is honest only while ``green_quality_uncertain`` names the rest. This asserts the two
    halves as one figure: stamped fields + uncertain fields == the rubric, disjoint and whole.
    Without it, silence becomes a legal way to say "no majority", and a stamp with three keys
    reads identically to a jury that was never asked the fourth question.
    """
    sc, _sidecar, _block = _audit(tmp_path, [
        _scoring_juror("correctness-beyond-oracle", _AGREED),
        _scoring_juror("graceful-bad-input", {**_AGREED, FIELD_NAMING_STRUCTURE: "mixed"}),
        _raising_juror("operator-legibility"),
        _garbage_juror("fourth-lens"),
    ])
    published = _published_fields(sc.evidence)
    assert published == {FIELD_RUNNABLE_SURFACE, FIELD_BAD_INPUT, FIELD_CORRECTNESS_PROBE}, (
        f"the stamped rubric fields were {sorted(published)}"
    )
    assert EV_UNCERTAIN in sc.evidence, (
        "three rubric keys were stamped and the fourth field was absorbed into silence"
    )
    disclosed = set(sc.evidence[EV_UNCERTAIN])
    assert FIELD_NAMING_STRUCTURE in disclosed, (
        f"the split field is not named in the stamp's disclosure {sorted(disclosed)}"
    )
    assert published.isdisjoint(disclosed), "a field was stamped with a value AND as uncertain"
    assert published | disclosed == set(RUBRIC_FIELDS), (
        f"stamped {sorted(published)} + uncertain {sorted(disclosed)} does not reconcile to the "
        f"rubric {sorted(RUBRIC_FIELDS)} — a field the panel was asked reached the operator's "
        f"run record in no form at all"
    )
    assert sc.evidence[EV_MODE] == MODE_DET_JURY


def test_a_stamp_carrying_no_rubric_value_discloses_all_four_fields(tmp_path):
    """Delete this and a jury that agreed on nothing can stamp a scorecard indistinguishable
    from a det-only night.

    Every juror lands in no bucket, so NO rubric key is written. What remains must be a
    positive statement — all four fields named uncertain — rather than an absence. This is
    the case where a bucket-derived denominator is most tempting and most wrong: zero
    published over zero asked reconciles beautifully and says nothing true.
    """
    sc, sidecar, _block = _audit(tmp_path, [
        _raising_juror("correctness-beyond-oracle"),
        _raising_juror("graceful-bad-input"),
        _garbage_juror("operator-legibility"),
    ])
    assert _published_fields(sc.evidence) == set(), "a scoreless panel published a rubric value"
    # Asked as a membership question FIRST: a missing key must read as a failed disclosure
    # claim, not as a KeyError a later reader has to decode.
    assert EV_UNCERTAIN in sc.evidence, (
        "the panel scored nothing and the stamp said nothing — indistinguishable from a "
        "det-only night on which no jury ran at all"
    )
    assert set(sc.evidence[EV_UNCERTAIN]) == set(RUBRIC_FIELDS), (
        f"the panel scored nothing and disclosed only {sorted(sc.evidence[EV_UNCERTAIN])}"
    )
    # The sidecar tells the same story, from the same run: no decided field, all four named.
    assert set(sidecar["jury"]["uncertain"]) == set(RUBRIC_FIELDS)
    assert all(v == ABSTAIN for v in sidecar["jury"]["scores"].values()), (
        f"a scoreless panel published a majority: {sidecar['jury']['scores']}"
    )


def test_a_unanimous_panel_stamps_no_uncertain_key(tmp_path):
    """The lock turned OFF. Delete this and every assertion above could be satisfied by a
    stamp that always names all four fields uncertain — "secure" and "the test cannot tell"
    would look identical.

    A panel that agrees publishes four rubric values and NO uncertain key, which is what makes
    the presence of that key in the tests above attributable to the shortfall rather than to
    the disclosure being unconditional.
    """
    sc, sidecar, _block = _audit(tmp_path, [
        _scoring_juror("correctness-beyond-oracle", _AGREED),
        _scoring_juror("graceful-bad-input", _AGREED),
        _scoring_juror("operator-legibility", _AGREED),
    ])
    assert _published_fields(sc.evidence) == set(RUBRIC_FIELDS), (
        "a unanimous panel failed to stamp all four rubric values, so the disclosure tests "
        "above prove nothing about the shortfall"
    )
    assert EV_UNCERTAIN not in sc.evidence, (
        "the uncertain disclosure is stamped unconditionally — its presence above is therefore "
        "not attributable to the shortfall"
    )
    assert sidecar["jury"]["uncertain"] == []
    assert sidecar["jury"]["juror_count"] == 3


def test_the_uncertain_disclosure_survives_the_scorecard_validator(tmp_path):
    """Delete this and the disclosure could be stamped in a shape the writer rejects, so the
    scorecard carrying it never lands — a shortfall disclosed into a file that is never
    written is a shortfall absorbed, one layer further out.

    ``write_scorecard`` fails closed on an invalid card, and the S6 evidence contract is
    ``{str: str | [str, ...]}``. The abstained-field list has to satisfy it.
    """
    sc, _sidecar, _block = _audit(tmp_path, [
        _scoring_juror("correctness-beyond-oracle", _AGREED),
        _scoring_juror("graceful-bad-input", {**_AGREED, FIELD_NAMING_STRUCTURE: "mixed"}),
        _raising_juror("operator-legibility"),
    ])
    assert EV_UNCERTAIN in sc.evidence, "there was no disclosure to validate"
    assert validate(sc) == [], (
        f"the stamped shortfall disclosure fails scorecard validation: {validate(sc)}"
    )
