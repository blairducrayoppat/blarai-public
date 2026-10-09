"""#1231 — the calibration agreement rate reconciles against its TRUE input population.

The defect class this file locks out: a grader publishes a rate whose DENOMINATOR is derived
by summing its own buckets. An item that classifies into NO bucket then leaves the numerator
and the denominator TOGETHER, the arithmetic stays perfectly self-consistent, and the figure
under-reports in silence. Nothing looks wrong — the published number reads CLEANER than the
truth, which is the only reason it survives review.

:func:`~tools.dispatch_harness.green_quality.calibration.agreement_rate` is the audit's
self-measurement: "how often did the band's concern flag match the operator's own accept /
reject?" It publishes an explicit ``k/n``, so a silent shrinkage of ``n`` would not read as a
smaller sample — it would read as a MORE CONFIDENT one, and the figure exists to decide
whether the auditor can eventually be trusted to gate. Under-reporting here is
self-flattering by construction.

Two proofs carry this file, per the standing rule that a lock ships with evidence it HOLDS
and evidence the probe FAILS when the lock is off:

* **The rogue population.** A pair whose band is in no A/B/C bucket and a pair whose verdict
  is outside the recorded vocabulary are driven through the REAL grader — in memory and again
  off a REAL log on disk written by the REAL recorder. The published denominator must equal
  the true population, and the rogue must be DISCLOSED (its own bucket, named) rather than
  absorbed into a known band or dropped.
* **The toggle.** The same assertion is aimed at a deliberately bucket-derived renderer of the
  #1231 shape and must FAIL. Without that half, "reconciles" and "the assertion cannot reach
  it" look identical.

SCOPE — what is locked and what is NOT. The grader's own contract is what is locked: the
denominator it publishes is the population it was HANDED, and every pair the real recorder
accepted survives the round trip into it. The LOADER's tolerance of lines the recorder never
wrote (a crash-truncated line, a non-dict, a verdict outside the vocabulary — dropped at
``calibration.py:94-102`` with no field disclosing the loss) is measured, is the same #1231
shape one layer further back, and is NOT locked here: that assertion fails today, which makes
it a defect to fix rather than a regression to lock. Reported to the parent, not xfailed —
an xfail here would file the shortfall under "known" and let it stop being a defect.

SHIPPING SURFACE. The dict returned by ``agreement_rate`` IS the published figure: the
package exports the function (``green_quality/__init__.py:96``) and nothing else renders the
rate — no summary string, no card line, no ``EV_*`` stamp. So the lock is aimed at the
exported callable's return value, and a tripwire below fails the day a second renderer
appears, because a lock aimed at yesterday's surface while the operator reads a new one is
lesson 354 exactly.
"""

from __future__ import annotations

import pytest

# Imported through the PACKAGE, not the private module: the export is what a consumer can
# reach, and driving anything else would prove a surface nobody ships.
from tools.dispatch_harness.green_quality import (
    CalibrationPair,
    agreement_rate,
    record_pair,
)
from tools.dispatch_harness.green_quality import calibration as calib
from tools.dispatch_harness.green_quality.constants import BAND_A, BAND_B, BAND_C

#: A band string the A/B/C formula has no bucket for. Empty rather than exotic on purpose:
#: this is the shape a missing/blank ``band`` field actually takes on the way out of the log,
#: not a value invented to make the test interesting.
_NO_BAND = ""

#: A verdict outside ``OP_VERDICTS``. Unreachable through :func:`record_pair` (it refuses one
#: at the door) and therefore only reachable the way it would really arrive: an older schema,
#: a hand-edited log, or a future verdict word added at one end and not the other.
_UNKNOWN_VERDICT = "unsure"


# ---------------------------------------------------------------------------
# The reconciliation assertion itself — one helper, aimed at the real grader below
# and at a deliberately defective renderer in the toggle, so both halves test the
# SAME claim rather than two claims that merely sound alike.
# ---------------------------------------------------------------------------


def _rate(report: dict) -> tuple[int, int]:
    """Split the published ``"k/n"`` into its two integers."""
    k, _, n = str(report["agreement"]).partition("/")
    return int(k), int(n)


def _assert_reconciles(report: dict, true_population: int) -> None:
    """The #1231 property, asserted three ways because any one of them alone is defeatable.

    ``pairs`` is the count the report volunteers, the ``/n`` is the denominator the operator
    actually reads, and the bucket total is the number a bucket-derived implementation would
    have produced. A grader that drops an unclassifiable item keeps all three CONSISTENT with
    each other and wrong together — so consistency is asserted against the true population,
    never against a sibling field."""
    assert report["pairs"] == true_population, (
        f"published 'pairs' {report['pairs']} != true input population {true_population}")
    k, n = _rate(report)
    assert n == true_population, (
        f"published rate {report['agreement']} reports a denominator of {n} over a true "
        f"population of {true_population} — the dropped item left BOTH halves")
    assert k <= n, f"published rate {report['agreement']} has a numerator above its own denominator"
    bucket_total = sum(sum(bucket.values()) for bucket in report["by_band"].values())
    assert bucket_total == true_population, (
        f"the by_band buckets account for {bucket_total} of {true_population} pairs — the "
        f"remainder is disclosed nowhere")


def _absorbing_agreement_rate(pairs: list[CalibrationPair]) -> dict:
    """THE LOCK TURNED OFF: the #1231 renderer, written the way it is usually written.

    Buckets first, then derives ``n`` by summing the buckets — and an unrecognised band simply
    never opens one. Every field it publishes agrees with every other field it publishes. This
    is the only implementation in the tree allowed to be wrong, and it exists so the assertion
    above can be shown to have teeth."""
    by_band: dict[str, dict[str, int]] = {}
    agree = 0
    for p in pairs:
        band = str(p.band).upper()
        if band not in (BAND_A, BAND_B, BAND_C):
            continue  # classified nowhere -> leaves the numerator and the denominator together
        bucket = by_band.setdefault(band, {calib.OP_ACCEPT: 0, calib.OP_REJECT: 0})
        bucket[p.operator_verdict] = bucket.get(p.operator_verdict, 0) + 1
        if calib.band_flags_concern(band) == (p.operator_verdict == calib.OP_REJECT):
            agree += 1
    n = sum(sum(b.values()) for b in by_band.values())
    return {"pairs": n, "agreement": f"{agree}/{n}" if n else "0/0", "by_band": by_band}


def _rogue_population() -> list[CalibrationPair]:
    """Two well-formed pairs plus one that falls into NO bucket on both axes at once.

    The rogue is the whole point: a population of only well-formed pairs cannot tell a grader
    that counts its input apart from a grader that counts its own buckets."""
    return [
        CalibrationPair("B2", "r1", BAND_A, calib.OP_ACCEPT),
        CalibrationPair("B2", "r2", BAND_C, calib.OP_REJECT),
        CalibrationPair("B2", "r3", _NO_BAND, _UNKNOWN_VERDICT),
    ]


# ---------------------------------------------------------------------------
# The grader, driven through its real entry point
# ---------------------------------------------------------------------------


def test_a_pair_in_no_recognised_band_stays_inside_the_published_denominator():
    """The lock. Delete it and a future refactor may derive ``n`` from the by_band buckets —
    at which point an unbandable pair vanishes from the sample and the agreement rate rises
    for free, with every published field still agreeing with every other."""
    pairs = _rogue_population()
    _assert_reconciles(agreement_rate(pairs), len(pairs))


def test_the_two_published_denominators_never_drift_apart():
    """The figure states its denominator TWICE — as ``pairs`` and as the ``/n`` of the rate.
    Delete this and the two can be computed from different populations, leaving the report
    self-contradicting in a way nobody reading one line of it would notice (lesson 354: the
    half the operator reads is not always the half a test is aimed at)."""
    report = agreement_rate(_rogue_population())
    _, n = _rate(report)
    assert report["pairs"] == n, (
        f"'pairs' {report['pairs']} and the rate {report['agreement']} disagree about the "
        f"same sample")


def test_an_unrecognised_band_is_disclosed_as_its_own_bucket_not_folded_into_a_known_one():
    """Disclosure, not merely retention. Delete this and an unbandable pair could be swept
    into band A to keep the denominator whole — the count would reconcile and the breakdown
    the later per-field tuning reads would be quietly fabricated."""
    with_rogue = agreement_rate(_rogue_population())
    without_rogue = agreement_rate(_rogue_population()[:2])

    assert "?" in with_rogue["by_band"], (
        f"the unbandable pair is not disclosed under its own key: {with_rogue['by_band']}")
    # The known bands are byte-identical with and without the rogue: it was disclosed, not
    # redistributed. Asserting only that "?" EXISTS would pass on an implementation that
    # created the bucket and ALSO counted the pair under A.
    for band in (BAND_A, BAND_B, BAND_C):
        assert with_rogue["by_band"].get(band) == without_rogue["by_band"].get(band), (
            f"band {band} changed when an unbandable pair was added — it was absorbed")


def test_a_verdict_outside_the_recorded_vocabulary_is_disclosed_by_name():
    """The second axis an item can fall off. Delete this and a verdict word added at one end
    of the system and not the other could be dropped from the bucket it does not fit, leaving
    the pair counted in ``n`` but described nowhere — a denominator that reconciles over a
    breakdown that has lost the reason it grew."""
    report = agreement_rate(_rogue_population())
    rogue_bucket = report["by_band"]["?"]
    assert rogue_bucket.get(_UNKNOWN_VERDICT) == 1, (
        f"the unknown verdict is not named in the published breakdown: {rogue_bucket}")


def test_an_empty_calibration_set_publishes_a_denominator_rather_than_silence():
    """Zero is an answer; absence is not. Delete this and an empty set could publish a bare
    ``""`` or omit the rate entirely, which reads as "nothing to report" rather than as "the
    auditor has never yet been measured against the operator"."""
    report = agreement_rate([])
    assert report["pairs"] == 0
    assert report["agreement"] == "0/0"


# ---------------------------------------------------------------------------
# The same claim off a REAL log, written by the REAL recorder — the round trip is
# where a denominator gets lost in practice, so it is driven, not simulated.
# ---------------------------------------------------------------------------


def test_every_pair_the_real_recorder_wrote_survives_into_the_published_denominator(tmp_path):
    """The end-to-end lock: real files on a real directory, ``record_pair`` -> ``load_pairs``
    -> ``agreement_rate``, with one recorded pair carrying no usable band. The true population
    is counted off the LOG ITSELF, never off this test's own bookkeeping — a test that trusts
    its own count of what it wrote cannot see a write that silently did not happen.

    Delete this and either end of the round trip may start filtering: the published figure
    would then describe a subset of the operator's actual verdicts while still calling itself
    the agreement rate."""
    log_dir = tmp_path / "state"
    written = [
        CalibrationPair("B2", "r1", BAND_A, calib.OP_ACCEPT),
        CalibrationPair("B3", "r2", BAND_C, calib.OP_REJECT),
        # Accepted by the recorder (it validates the VERDICT, not the band) and therefore a
        # real inhabitant of a real log — the item that falls into no bucket downstream.
        CalibrationPair("B5", "r3", _NO_BAND, calib.OP_REJECT),
    ]
    for pair in written:
        assert record_pair(log_dir, pair) is True

    log = log_dir / calib.CALIBRATION_LOG_NAME
    true_population = len(
        [line for line in log.read_text(encoding="utf-8").splitlines() if line.strip()])
    assert true_population == 3, "the fixture did not write the log it thinks it wrote"

    report = agreement_rate(calib.load_pairs(log_dir))
    _assert_reconciles(report, true_population)
    assert "?" in report["by_band"], (
        f"the recorded pair with no usable band is disclosed nowhere: {report['by_band']}")


# ---------------------------------------------------------------------------
# The toggle — proof the assertion above can fail
# ---------------------------------------------------------------------------


def test_the_reconciliation_assertion_catches_a_bucket_derived_denominator():
    """The lock, turned off. ``_absorbing_agreement_rate`` is the #1231 shape: internally
    consistent, quietly two-thirds of the sample. Delete this and ``_assert_reconciles`` could
    rot into a no-op — asserting a field against itself, or against a population it derives
    from the same buckets — and every test above would still be green."""
    pairs = _rogue_population()
    absorbed = _absorbing_agreement_rate(pairs)

    # Self-consistent, and that is exactly the problem: nothing inside the report contradicts
    # anything else inside it. Only the true population exposes the loss.
    assert absorbed["pairs"] == sum(sum(b.values()) for b in absorbed["by_band"].values())
    assert absorbed["pairs"] == len(pairs) - 1

    with pytest.raises(AssertionError):
        _assert_reconciles(absorbed, len(pairs))


# ---------------------------------------------------------------------------
# Lesson 354 — keep the lock aimed at the surface that actually ships
# ---------------------------------------------------------------------------


def test_the_published_figure_has_exactly_one_renderer(tmp_path):
    """The tripwire. Today the exported ``agreement_rate`` dict IS the published figure —
    nothing renders it to a summary string, a card line or an ``EV_*`` stamp — so locking that
    dict locks what the operator would read. The day a second renderer appears (a
    ``summary()``, a card line), the assertions above would still pass against the dict while
    the SHIPPING string was free to state a different denominator.

    Delete this and that divergence lands silently. Failing here is not a defect in the new
    code — it is the instruction to point the lock at the new surface as well."""
    published = {
        name for name, obj in vars(calib).items()
        if not name.startswith("_")
        and callable(obj)
        and getattr(obj, "__module__", "") == calib.__name__
    }
    assert published == {"band_flags_concern", "CalibrationPair", "record_pair",
                         "load_pairs", "agreement_rate"}, (
        f"calibration.py grew or lost a public callable ({published}) — if the new one renders "
        f"the agreement figure for an operator, the reconciliation lock must cover it too")

    # And the exported name is the same object, not a wrapper that could re-render the rate
    # on the way out.
    from tools.dispatch_harness import green_quality as gq
    assert gq.agreement_rate is calib.agreement_rate
    assert gq.record_pair is calib.record_pair
