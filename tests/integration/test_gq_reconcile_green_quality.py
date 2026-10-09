"""#1231 — the RECONCILIATION LOCK over ``corpus_block``'s four PROSE counters.

The defect class: a grader publishes a count whose denominator is derived by summing its own
buckets. An item that lands in NO bucket leaves the numerator and the denominator TOGETHER,
the arithmetic stays perfectly self-consistent, and the published figure under-reports while
reading cleaner than the truth.

``corpus_block`` is SOUND on this axis today and nothing asserted it. The four prose counters
are each read off ``ProseResult.disposition()``, which returns exactly one of four exhaustive
constants, so they partition ``results``; ``audited`` is ``len(results)`` — an INDEPENDENT
population count, never a sum of the buckets; and a GREEN whose audit raised is counted
separately as ``audit_failed``, so the night's true size stays recoverable. This file locks
that arrangement so it STAYS sound.

It is the unguarded half of an otherwise-guarded aggregator: the identical property on the
same function is already locked for the BAND buckets
(``test_green_quality.py::test_the_bands_partition_the_audited_population`` and its three
siblings). Everything grepping for the prose counters today asserts a single scenario's value
(``== 1`` / ``== 0``); nothing sums the four, and nothing compares them to ``audited``.

The risk is live rather than hypothetical. #1395's fix asks whether a truncated scan may
coexist with a clean disposition; a FIFTH disposition state added there drops a GREEN out of
all four prose buckets while ``audited`` stays correct — and ``render_kpi``'s prose line
prints the four counters with no total of their own, so the shortfall has to be visible some
other way or it is not visible at all. The last test in this file — the printed night summary
disclosing a prose shortfall rather than absorbing it — is the half that matters most: it locks
the SHIPPING surface (the block that lands in ``battery-summary.json`` and the KPI stanza the
operator reads), not an internal status object he never sees.

The surfaces locked here, in the order the night reaches them:

* ``audit_greens`` -> ``battery.py``'s ``BatterySummary.green_quality`` (the battery-close
  method) -> ``summary.green_quality_block``;
* -> ``BatterySummary.to_dict()["green_quality"]``, the block written into
  ``battery-summary.json``;
* -> ``render_kpi`` -> ``BatterySummary.render()``, the printed night summary.

Two design properties are deliberately NOT treated as defects here, both verified in the
source: the three SECURITY counters are not a partition and may double-count (a measured-clean
GREEN is in none of them; an unmeasured result carrying a HIGH finding is in two), so no clean
residual is derivable there; and ``audit_greens``'s ``if result is None: continue`` is
unreachable, because ``audit_green`` returns ``None`` only for a non-GREEN, which the loop has
already filtered.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from tools.dispatch_harness.battery import BatterySummary
from tools.dispatch_harness.green_quality import audit_greens, render_kpi
from tools.dispatch_harness.green_quality import placeholder_prose as prose
from tools.dispatch_harness.green_quality.constants import BANDS
from tools.dispatch_harness.scorecard import Scorecard

# ---------------------------------------------------------------------------
# Fixture trees — one real deliverable per prose disposition
#
# Real files on a real temp directory, read by the REAL scanner through the REAL battery-close
# entry point. Nothing about the grader under test is mocked: each disposition is EARNED by the
# tree's own contents, which is the only way a partition assertion means anything (a fixture
# that hands the counters their answers proves the fixture partitions, not the grader).
# ---------------------------------------------------------------------------

#: -> DISPOSITION_PLACEHOLDER. Latin filler in a delivered page, the HIGH-severity rule.
_PLACEHOLDER_INDEX = """<!doctype html><html><head><title>Ridge Pottery</title></head>
<body><h1>Ridge Pottery</h1>
<p>Lorem ipsum dolor sit amet, consectetur adipiscing elit.</p></body></html>
"""

#: -> DISPOSITION_CLEAN. The same page shape carrying words a person wrote: a real title, no
#: template contact details, nothing from the scaffold-title list.
_WRITTEN_INDEX = """<!doctype html><html><head><title>Ridge Pottery, Hexham</title></head>
<body><h1>Ridge Pottery</h1>
<p>We fire stoneware in a wood kiln twice a year and sell from the studio door on the first
Saturday of every month.</p>
<p>Open Thursday to Saturday, ten until four.</p></body></html>
"""

#: -> DISPOSITION_NOT_APPLICABLE. A library: no page, no template, nothing to read. Measured,
#: and deliberately NOT "clean" — the scan approved nothing here.
_LIBRARY_MODULE = "def totals(rows):\n    return sum(r['amount'] for r in rows)\n"

#: The run_id of the card whose audit RAISES. A scorecard field the persist step cannot turn
#: into a path: ``_stamp_and_persist`` guards the sidecar write against ``OSError``, and an
#: embedded null raises ``ValueError`` instead, so the fault escapes to ``audit_greens``'s
#: fail-soft handler exactly as a genuine per-card audit fault does. The MECHANISM is
#: incidental — every assertion below is on the OUTCOME (one GREEN left ``results``), and
#: :func:`_night` asserts the fixture still produces one so a future change that makes this
#: input harmless fails with an explanation rather than a mystery.
_CORRUPT_RUN_ID = "R5\x00corrupt"

#: The night's fifth GREEN: audited fine, then lost at persist time.
_RAISING_JOB = "B5"


def _site(root: Path, markup: str) -> Path:
    """One delivered static site."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "index.html").write_text(markup, encoding="utf-8")
    (root / "style.css").write_text("body { font-family: system-ui; }\n", encoding="utf-8")
    return root


def _library(root: Path) -> Path:
    """One delivered Python library — a tree with no user-visible prose in it at all."""
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "src" / "totals.py").write_text(_LIBRARY_MODULE, encoding="utf-8")
    return root


def _scorecards(*, corrupt_run_id: bool) -> list[Scorecard]:
    """Six cards: five GREENs and one PARKED.

    The PARKED one is the denominator's other honesty half — the population this rollup
    describes is the night's GREENs, so a non-GREEN must not inflate ``audited`` either.
    """
    ev = {"oracle_status": "passed"}
    return [
        Scorecard(job_id="B1", verdict="GREEN", repo="b1-pottery-web", run_id="R1", evidence=dict(ev)),
        Scorecard(job_id="B2", verdict="GREEN", repo="b2-pottery-web", run_id="R2", evidence=dict(ev)),
        Scorecard(job_id="B3", verdict="GREEN", repo="b3-budget-lib", run_id="R3", evidence=dict(ev)),
        # No archived tree is ever written for this slug: the repo does not resolve, so the
        # scan reports "could not determine" rather than borrowing the word clean.
        Scorecard(job_id="B4", verdict="GREEN", repo="b4-never-archived", run_id="R4", evidence=dict(ev)),
        Scorecard(job_id=_RAISING_JOB, verdict="GREEN", repo="b5-pottery-web",
                  run_id=_CORRUPT_RUN_ID if corrupt_run_id else "R5", evidence=dict(ev)),
        Scorecard(job_id="B6", verdict="PARKED", attribution="harness-defect",
                  repo="b6-pottery-web", run_id="R6"),
    ]


def _build_trees(out_dir: Path) -> None:
    """The archived deliverables ``_resolve_current_repo`` reads at battery close."""
    archived = out_dir / "repos-archived"
    _site(archived / "b1-pottery-web", _PLACEHOLDER_INDEX)
    _site(archived / "b2-pottery-web", _WRITTEN_INDEX)
    _library(archived / "b3-budget-lib")
    _site(archived / "b5-pottery-web", _WRITTEN_INDEX)
    _site(archived / "b6-pottery-web", _WRITTEN_INDEX)


def _night(tmp_path: Path, *, corrupt_run_id: bool = True) -> tuple[BatterySummary, dict]:
    """Drive the whole night through ``BatterySummary.green_quality`` — the method
    ``battery.py`` itself calls at close — and return ``(summary, block)``.

    Nothing is injected: the real prose scanner reads the real trees, and the block returned
    is the object that becomes ``battery-summary.json``'s ``green_quality`` key.
    """
    out_dir = tmp_path / "battery" / "20260814-000001"
    _build_trees(out_dir)
    cards = _scorecards(corrupt_run_id=corrupt_run_id)
    summary = BatterySummary(scorecards=cards, out_dir=str(out_dir))
    summary.green_quality(
        runs_dir=tmp_path / "runs", out_dir=out_dir,
        job_surfaces={"B1": "web", "B2": "web", "B3": "python-lib", "B4": "web",
                      _RAISING_JOB: "web"},
    )
    block = summary.green_quality_block
    if corrupt_run_id:
        # The fixture's own precondition, asserted rather than assumed: if this input stops
        # producing a raising card the tests below would still pass while testing nothing.
        assert block["audit_failed"] == 1, (
            "the fixture no longer produces a GREEN whose audit raises — choose another "
            f"per-card fault; the property under test is unchanged. block={block}"
        )
    return summary, block


def _prose_total(block: dict) -> int:
    """The sum of the four published prose counters — the number a reader would reach for if
    the block carried no independent population count. It must never BE the denominator."""
    return sum(int(block[k]) for k in
               ("prose_placeholder", "prose_clean", "prose_not_applicable", "prose_unmeasured"))


class _FifthState(prose.ProseResult):
    """A prose result in a state no counter recognises — #1395's shape, one release early.

    #1395's DONE-means item 2 asks whether a TRUNCATED scan may coexist with a clean
    disposition. Any answer that adds a fifth ``disposition()`` value produces exactly this
    object, and a GREEN carrying it falls out of all four prose buckets. Subclassing the real
    result rather than faking one keeps every OTHER surface (the sidecar, the card, the band)
    reading a genuine ``ProseResult``, so what this stands up is the future state and not a
    hole in the fixture.
    """

    def disposition(self) -> str:
        return "truncated-added-later"


def _fifth_state_scanner(repo, surface: str = "") -> prose.ProseResult:
    """The SCANNER swapped, never the aggregator under test.

    ``audit_greens`` documents ``prose_scan`` as an injection seam for exactly this purpose,
    and the sibling suites use it the same way. One tree comes back in the unrecognised state;
    every other tree is read by the real scanner, so the night stays otherwise honest.
    """
    if repo is not None and Path(repo).name == "b3-budget-lib":
        return _FifthState(measured=True, applicable=True, pages_scanned=1,
                           status="scan truncated (a state added after this rollup was written)")
    return prose.scan_repo(repo, surface)


def _kpi_stanza(summary: BatterySummary) -> str:
    """The green-quality lines of the PRINTED night summary — the operator's actual read."""
    return "\n".join(line for line in summary.render().splitlines()
                     if "green-quality" in line or line.startswith("  prose:")
                     or line.startswith("  security:"))


def _printed_prose_counts(stanza: str) -> dict[str, int]:
    """The four numbers as they are PRINTED, parsed back off the rendered line.

    Read off the string rather than the dict on purpose: the dict is what the JSON carries,
    and this is what the operator sees. A counter that stops being rendered is invisible to
    him whatever the block says.
    """
    match = re.search(r"prose: placeholder=(\d+), clean=(\d+), no-prose-surface=(\d+), "
                      r"not-measured=(\d+)", stanza)
    assert match, f"the prose line is missing from the printed night summary:\n{stanza}"
    return dict(zip(("placeholder", "clean", "not_applicable", "unmeasured"),
                    (int(g) for g in match.groups())))


def _printed_band_counts(stanza: str) -> dict[str, int]:
    """The band counts as PRINTED — the independent population figure that shares the KPI
    stanza with the prose line.

    The bands partition ``audited`` (locked in ``test_green_quality.py::test_the_bands_
    partition_the_audited_population``), so their total is what a prose shortfall shows up
    AGAINST on a line that prints no prose total of its own.
    """
    out: dict[str, int] = {}
    for band in BANDS:
        match = re.search(rf"\b{re.escape(band)} (\d+)\b", stanza)
        assert match, f"band {band} is missing from the printed KPI line:\n{stanza}"
        out[band] = int(match.group(1))
    return out


# ---------------------------------------------------------------------------
# THE PARTITION — every audited GREEN is in exactly one prose bucket
# ---------------------------------------------------------------------------


def test_the_four_prose_counters_partition_the_audited_population(tmp_path: Path) -> None:
    """Delete this and the prose counters may quietly stop summing to the night.

    Four real deliverables, one per disposition, driven through the real battery-close entry
    point: a site with Latin filler, a site with written copy, a library with no prose surface
    at all, and a GREEN whose tree never archived. Each must land in exactly one bucket, and
    the four must total the published denominator. If a fifth state is ever added without a
    counter — or an existing counter's predicate is narrowed — this is what says so.
    """
    _summary, block = _night(tmp_path)

    # Each state is genuinely represented: a partition over one populated bucket is arithmetic
    # nobody can get wrong, and would lock nothing.
    assert block["prose_placeholder"] == 1
    assert block["prose_clean"] == 1
    assert block["prose_not_applicable"] == 1
    assert block["prose_unmeasured"] == 1

    assert block["audited"] == 4
    assert _prose_total(block) == block["audited"], (
        "the prose counters do not partition the audited population: they sum to "
        f"{_prose_total(block)}, audited={block['audited']}"
    )


def test_the_denominator_is_the_GREEN_population_not_every_scorecard(tmp_path: Path) -> None:
    """Delete this and the mirror defect goes unguarded — a denominator inflated instead of
    deflated.

    ``audited`` describes the GREENs this rollup graded. A PARKED card is filtered before the
    audit and belongs to no prose bucket for the honest reason, so it must not appear in the
    denominator either: six scorecards, five GREENs, four audited.
    """
    summary, block = _night(tmp_path)

    assert len(summary.scorecards) == 6
    assert sum(1 for s in summary.scorecards if s.verdict == "GREEN") == 5
    assert block["audited"] == 4, "a non-GREEN reached the audited population"
    assert _prose_total(block) == 4


# ---------------------------------------------------------------------------
# THE ITEM THAT FALLS INTO NO BUCKET — and the shortfall it must not hide
# ---------------------------------------------------------------------------


def test_a_GREEN_whose_audit_raised_leaves_the_prose_counters_and_the_denominator_together(
    tmp_path: Path,
) -> None:
    """Delete this and a night that graded four of five GREENs can be published as a whole one.

    This is the #1231 shape in its live form. A card whose audit raises never reaches
    ``results``, so it is in none of the four prose buckets AND not in ``audited`` — numerator
    and denominator leaving together, the arithmetic staying self-consistent while the figure
    silently under-reports. What makes the rollup honest is that the loss is published beside
    the counts: ``audit_failed`` restores the night's true size and ``audit_failed_jobs`` NAMES
    what was lost.
    """
    summary, block = _night(tmp_path)

    greens = sum(1 for s in summary.scorecards if s.verdict == "GREEN")
    assert greens == 5

    # The self-consistent under-report, stated plainly: the buckets agree with the denominator
    # and both are smaller than the night.
    assert _prose_total(block) == block["audited"] == 4
    assert block["audited"] < greens

    # ...and the shortfall is DISCLOSED, not absorbed.
    assert block["audit_failed"] == 1
    assert block["audited"] + block["audit_failed"] == greens, (
        "the night's true size is not recoverable from the published block"
    )
    assert block["audit_failed_jobs"] == [_RAISING_JOB], "the lost GREEN is named, not counted"


def test_the_shipping_block_carries_the_shortfall_into_battery_summary_json(
    tmp_path: Path,
) -> None:
    """Delete this and the disclosure could be lost between the aggregator and the artifact.

    The counters are only worth locking on the surface that actually reaches the operator's
    tooling: ``BatterySummary.to_dict()["green_quality"]``, serialised into
    ``battery-summary.json``. Asserted after a JSON round-trip, because a value that cannot
    survive serialisation is a value the night's record does not have.
    """
    summary, block = _night(tmp_path)

    shipped = json.loads(json.dumps(summary.to_dict()))["green_quality"]
    assert shipped["schema"] == "green-quality/v1"
    assert shipped["audited"] == block["audited"]
    assert _prose_total(shipped) == shipped["audited"]
    # The independent population count travels WITH the buckets, which is what makes a future
    # shortfall computable from the artifact alone.
    assert shipped["audit_failed"] == 1
    assert shipped["audit_failed_jobs"] == [_RAISING_JOB]


def test_a_prose_state_no_counter_recognises_does_not_shrink_the_denominator(
    tmp_path: Path,
) -> None:
    """Delete this and #1231's exact failure can land the day a fifth prose state is added.

    A GREEN whose prose result is in an unrecognised state must STILL count in ``audited``. If
    ``audited`` were derived by summing the prose buckets — as ``link_lint``'s denominator is
    (#1389) — that GREEN would leave numerator and denominator together, the block would stay
    perfectly self-consistent, and a night that classified less would be indistinguishable from
    a smaller night. The published shortfall is what makes it visible instead.
    """
    out_dir = tmp_path / "battery" / "20260814-000002"
    _build_trees(out_dir)
    cards = [s for s in _scorecards(corrupt_run_id=False)
             if s.job_id in ("B1", "B2", "B3")]
    block = audit_greens(cards, runs_dir=tmp_path / "runs", out_dir=out_dir,
                         job_surfaces={"B1": "web", "B2": "web", "B3": "python-lib"},
                         prose_scan=_fifth_state_scanner)

    assert block["audited"] == 3, "a GREEN in an unrecognised prose state left the population"
    assert _prose_total(block) == 2, "sanity: the unrecognised state is in no prose bucket"
    # The divergence must be VISIBLE — the denominator does not shrink to match the buckets.
    assert block["audited"] - _prose_total(block) == 1, (
        "the prose shortfall is not computable from the published block"
    )


def test_the_printed_night_summary_discloses_a_prose_shortfall_rather_than_absorbing_it(
    tmp_path: Path,
) -> None:
    """Delete this and the lock points only at surfaces the operator never reads.

    THE SHIPPING-SURFACE HALF, and the reason this file exists. ``render_kpi`` prints the four
    prose counters with no total of their own, so a bucket-drop cannot show up on the prose
    line by itself. It shows up against the BAND counts printed in the same stanza, which
    partition the same ``audited`` population and are locked to do so elsewhere.

    Both directions, per the standing rule that a lock ships with evidence it blocks and
    evidence the probe fails when the lock is off:

    * a SOUND night prints prose counts totalling the band counts — the operator's line
      reconciles against itself;
    * a night carrying an unrecognised prose state prints prose counts totalling LESS, so the
      shortfall is on the page rather than inside a status object.

    Without the second half the first is satisfied by any pair of numbers that happen to agree,
    and "the KPI discloses a shortfall" and "the probe cannot produce one" look identical.
    """
    # --- sound night: the printed line reconciles ---
    summary, block = _night(tmp_path)
    stanza = _kpi_stanza(summary)
    printed = _printed_prose_counts(stanza)
    bands = _printed_band_counts(stanza)

    assert sum(printed.values()) == block["audited"]
    assert sum(bands.values()) == block["audited"], (
        "the band counts are no longer an independent population figure on this line — the "
        "prose shortfall would have nothing to show up against"
    )
    assert sum(printed.values()) == sum(bands.values())
    # The night's loss is printed beside the counts, not instead of them (#1270).
    assert "audit-failed=1" in stanza, stanza

    # --- the same stanza with one GREEN in a state no counter recognises ---
    out_dir = tmp_path / "battery" / "20260814-000003"
    _build_trees(out_dir)
    cards = [s for s in _scorecards(corrupt_run_id=False) if s.job_id in ("B1", "B2", "B3")]
    rogue_block = audit_greens(cards, runs_dir=tmp_path / "runs2", out_dir=out_dir,
                               job_surfaces={"B1": "web", "B2": "web", "B3": "python-lib"},
                               prose_scan=_fifth_state_scanner)
    rogue = BatterySummary(scorecards=cards, out_dir=str(out_dir),
                           green_quality_block=rogue_block)
    rogue_stanza = _kpi_stanza(rogue)
    rogue_printed = _printed_prose_counts(rogue_stanza)
    rogue_bands = _printed_band_counts(rogue_stanza)

    assert sum(rogue_bands.values()) == rogue_block["audited"] == 3
    assert sum(rogue_printed.values()) == 2
    assert sum(rogue_printed.values()) < sum(rogue_bands.values()), (
        "a GREEN in no prose bucket was ABSORBED by the printed KPI line: the prose counts "
        f"still total the population.\n{rogue_stanza}"
    )
    # And the surface carrying it is the PRINTED summary — not a log, not a sidecar. Every KPI
    # line reaches it contiguously and in order, so nothing can be rendered by `render_kpi` and
    # then dropped on the way to the page.
    assert "\n".join(render_kpi(rogue_block)) in rogue.render()
