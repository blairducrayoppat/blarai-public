"""Locks for the deterministic flow-metrics module (#843, ADR-039 §2.8).

Every assertion here is against KNOWN, hand-computed timestamps — the "prove
against a fixture board with known timestamps" requirement. No Vikunja I/O:
these are pure functions over plain dicts shaped like
``shared.fleet.vikunja_bridge`` read results.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from shared.fleet import flow_metrics as fm

_NOW = datetime(2026, 7, 12, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# parse_vikunja_timestamp
# ---------------------------------------------------------------------------


def test_parse_accepts_z_suffix():
    ts = fm.parse_vikunja_timestamp("2026-07-01T12:00:00Z")
    assert ts == datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert ts.tzinfo is not None  # tz-AWARE, never naive


def test_parse_accepts_explicit_offset():
    ts = fm.parse_vikunja_timestamp("2026-07-01T08:00:00-04:00")
    assert ts == datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)


def test_parse_treats_naive_timestamp_as_utc():
    ts = fm.parse_vikunja_timestamp("2026-07-01T12:00:00")
    assert ts == datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("bad", ["", None, "not-a-date", "2026-13-99T99:99:99Z"])
def test_parse_fails_soft_on_malformed_input(bad):
    assert fm.parse_vikunja_timestamp(bad) is None


# ---------------------------------------------------------------------------
# compute_age
# ---------------------------------------------------------------------------


def test_compute_age_known_delta():
    task = {"id": 1, "title": "t1", "created": "2026-07-10T12:00:00Z"}  # 2 days before _NOW
    age = fm.compute_age(task, now=_NOW)
    assert age is not None
    assert age.age_seconds == pytest.approx(2 * 86400)
    assert age.basis_field == "created"


def test_compute_age_none_when_timestamp_missing():
    assert fm.compute_age({"id": 1, "title": "t1"}, now=_NOW) is None


def test_compute_age_none_when_timestamp_unparseable():
    assert fm.compute_age({"id": 1, "created": "garbage"}, now=_NOW) is None


def test_compute_age_clamps_negative_to_zero():
    future = {"id": 1, "title": "t1", "created": "2026-07-13T12:00:00Z"}  # AFTER _NOW
    age = fm.compute_age(future, now=_NOW)
    assert age is not None
    assert age.age_seconds == 0.0


def test_compute_age_respects_alternate_basis_field():
    task = {"id": 1, "title": "t1", "entered_ready": "2026-07-11T12:00:00Z", "created": "2026-01-01T00:00:00Z"}
    age = fm.compute_age(task, now=_NOW, basis_field="entered_ready")
    assert age.age_seconds == pytest.approx(86400)
    assert age.basis_field == "entered_ready"


def test_compute_ages_skips_unparseable_without_raising():
    tasks = [
        {"id": 1, "title": "good", "created": "2026-07-10T12:00:00Z"},
        {"id": 2, "title": "bad", "created": "garbage"},
        {"id": 3, "title": "missing"},
    ]
    ages = fm.compute_ages(tasks, now=_NOW)
    assert len(ages) == 1
    assert ages[0].title == "good"


# ---------------------------------------------------------------------------
# compute_cycle_time / compute_cycle_times
# ---------------------------------------------------------------------------


def test_compute_cycle_time_known_delta():
    task = {
        "done": True,
        "created": "2026-07-01T00:00:00Z",
        "done_at": "2026-07-04T00:00:00Z",  # exactly 3 days
    }
    assert fm.compute_cycle_time(task) == pytest.approx(3 * 86400)


def test_compute_cycle_time_none_when_not_done():
    task = {"done": False, "created": "2026-07-01T00:00:00Z", "done_at": "2026-07-04T00:00:00Z"}
    assert fm.compute_cycle_time(task) is None


def test_compute_cycle_time_none_when_done_at_missing():
    task = {"done": True, "created": "2026-07-01T00:00:00Z", "done_at": None}
    assert fm.compute_cycle_time(task) is None


def test_compute_cycle_times_mixed_board():
    tasks = [
        {"done": True, "created": "2026-07-01T00:00:00Z", "done_at": "2026-07-02T00:00:00Z"},  # 1 day
        {"done": True, "created": "2026-07-01T00:00:00Z", "done_at": "2026-07-06T00:00:00Z"},  # 5 days
        {"done": False, "created": "2026-07-01T00:00:00Z"},  # not done -> excluded
    ]
    cts = fm.compute_cycle_times(tasks)
    assert sorted(cts) == pytest.approx([86400, 5 * 86400])


# ---------------------------------------------------------------------------
# compute_throughput
# ---------------------------------------------------------------------------


def test_throughput_counts_within_half_open_window():
    window_start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    window_end = datetime(2026, 7, 8, tzinfo=timezone.utc)
    tasks = [
        {"done": True, "done_at": "2026-07-01T00:00:00Z"},  # ON window_start -> included
        {"done": True, "done_at": "2026-07-05T00:00:00Z"},  # inside -> included
        {"done": True, "done_at": "2026-07-08T00:00:00Z"},  # ON window_end -> EXCLUDED (half-open)
        {"done": True, "done_at": "2026-06-30T23:59:59Z"},  # just before -> excluded
        {"done": False, "created": "2026-07-03T00:00:00Z"},  # not done -> excluded
    ]
    assert fm.compute_throughput(tasks, window_start=window_start, window_end=window_end) == 2


def test_throughput_zero_on_empty_board():
    window_start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    window_end = datetime(2026, 7, 8, tzinfo=timezone.utc)
    assert fm.compute_throughput([], window_start=window_start, window_end=window_end) == 0


# ---------------------------------------------------------------------------
# aging_wip_outliers
# ---------------------------------------------------------------------------


def _age(seconds: float, title: str = "t") -> fm.WorkItemAge:
    return fm.WorkItemAge(task_id=1, title=title, age_seconds=seconds, basis_field="created")


def test_aging_outliers_flags_the_straggler():
    # Nine items around ~1 day old, one item 60 days old -> a clear outlier.
    ages = [_age(86400 + i * 100, f"normal-{i}") for i in range(9)]
    ages.append(_age(60 * 86400, "straggler"))
    outliers = fm.aging_wip_outliers(ages)
    assert len(outliers) == 1
    assert outliers[0].title == "straggler"


def test_aging_outliers_empty_below_two_samples():
    assert fm.aging_wip_outliers([]) == []
    assert fm.aging_wip_outliers([_age(100)]) == []


def test_aging_outliers_empty_when_uniform():
    ages = [_age(86400, f"t{i}") for i in range(5)]  # identical ages -> stddev 0
    assert fm.aging_wip_outliers(ages) == []


# ---------------------------------------------------------------------------
# compute_flow_metrics — the composed, fixture-board proof
# ---------------------------------------------------------------------------


def test_compute_flow_metrics_fixture_board_known_timestamps():
    """One fixture board, every timestamp hand-picked, every metric verified
    against a hand computation — the end-to-end proof the C1 report cites."""
    open_tasks = [
        {"id": 1, "title": "fresh", "created": "2026-07-12T06:00:00Z", "done": False},  # 6h old
        {"id": 2, "title": "stale", "created": "2026-06-01T12:00:00Z", "done": False},  # 41 days old
        {"id": 3, "title": "unparseable", "created": "not-a-date", "done": False},  # dropped
    ]
    done_tasks = [
        {
            "id": 4, "title": "shipped-1", "done": True,
            "created": "2026-07-01T00:00:00Z", "done_at": "2026-07-03T00:00:00Z",  # 2-day cycle
        },
        {
            "id": 5, "title": "shipped-2", "done": True,
            "created": "2026-06-01T00:00:00Z", "done_at": "2026-07-11T00:00:00Z",  # 40-day cycle
        },
    ]
    all_tasks = open_tasks + done_tasks
    window_start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    window_end = datetime(2026, 7, 13, tzinfo=timezone.utc)

    metrics = fm.compute_flow_metrics(
        open_tasks, all_tasks, now=_NOW, window_start=window_start, window_end=window_end,
    )

    # Age: 2 of 3 open tasks parse (the third is dropped, not crashed on).
    assert metrics.open_count == 3
    assert len(metrics.ages) == 2
    assert metrics.skipped_unparseable == 1
    fresh_age = 0.25 * 86400  # 6 hours
    stale_age = 41.0 * 86400  # from 2026-06-01T12:00 to 2026-07-12T12:00, exactly 41 days
    assert metrics.oldest_age_seconds == pytest.approx(stale_age, rel=1e-3)
    assert metrics.mean_age_seconds == pytest.approx((fresh_age + stale_age) / 2, rel=1e-3)

    # Cycle time: both done tasks contribute (2 days, 40 days).
    assert sorted(metrics.cycle_times_seconds) == pytest.approx([2 * 86400, 40 * 86400])
    assert metrics.mean_cycle_time_seconds == pytest.approx(21 * 86400, rel=1e-3)

    # Throughput: both done_at timestamps fall inside [2026-07-01, 2026-07-13).
    assert metrics.throughput_count == 2
    assert metrics.throughput_window_start == window_start.isoformat()
    assert metrics.throughput_window_end == window_end.isoformat()

    # Aging outliers: only 2 samples (fresh vs stale) — below the 2-sample floor
    # is false, so a stddev IS computed; the stale item is far enough from the
    # mean to trip the default 1.5-stddev threshold in this 2-point set (a
    # symmetric 2-point distribution puts BOTH points at +-1 stddev from the
    # mean, so a 1.5-stddev threshold flags neither — asserting that keeps
    # this test honest about the detector's actual behavior on a tiny sample,
    # rather than asserting a result that would only hold for a larger board).
    assert fm.aging_wip_outliers(list(metrics.ages)) == []

    # computed_at + age_basis_field are recorded for audit/reproducibility.
    assert metrics.computed_at == _NOW.isoformat()
    assert metrics.age_basis_field == fm.DEFAULT_AGE_BASIS_FIELD == "created"


def test_compute_flow_metrics_empty_board_never_crashes():
    metrics = fm.compute_flow_metrics(
        [], [], now=_NOW,
        window_start=_NOW - timedelta(days=7), window_end=_NOW,
    )
    assert metrics.open_count == 0
    assert metrics.ages == ()
    assert metrics.oldest_age_seconds is None
    assert metrics.mean_age_seconds is None
    assert metrics.cycle_times_seconds == ()
    assert metrics.mean_cycle_time_seconds is None
    assert metrics.throughput_count == 0
    assert metrics.aging_outliers == ()
    assert metrics.skipped_unparseable == 0


def test_naive_datetime_raises_not_silently_wrong():
    """A caller passing a NAIVE clock read is a caller bug (ADR-039 requires
    tz-aware timestamps throughout) — Python's own naive-vs-aware comparison
    TypeError is the correct, loud failure mode here, not a silent
    misinterpretation as UTC or local time."""
    naive_now = datetime(2026, 7, 12, 12, 0, 0)  # no tzinfo
    with pytest.raises(TypeError):
        fm.compute_age({"id": 1, "created": "2026-07-01T00:00:00Z"}, now=naive_now)


# ---------------------------------------------------------------------------
# compute_partitioned_flow_metrics — the #887 headline / test-class split
# ---------------------------------------------------------------------------


def _win():
    return datetime(2026, 7, 1, tzinfo=timezone.utc), datetime(2026, 7, 13, tzinfo=timezone.utc)


def _is_test(task):
    """A test-class predicate keyed on a marker field (stands in for the real
    label-driven ``coord_lifecycle.is_test_class`` — flow_metrics is label-agnostic
    and only applies the injected predicate)."""
    return bool(task.get("_test"))


def test_partition_splits_headline_from_test_class():
    open_tasks = [
        {"id": 1, "title": "real", "created": "2026-07-10T12:00:00Z", "done": False},
        {"id": 2, "title": "synthetic", "created": "2026-06-01T12:00:00Z", "done": False, "_test": True},
    ]
    done_tasks = [
        {"id": 3, "title": "real-done", "done": True,
         "created": "2026-07-01T00:00:00Z", "done_at": "2026-07-03T00:00:00Z"},
        {"id": 4, "title": "synthetic-done", "done": True, "_test": True,
         "created": "2026-07-01T00:00:00Z", "done_at": "2026-07-05T00:00:00Z"},
    ]
    ws_, we_ = _win()
    part = fm.compute_partitioned_flow_metrics(
        open_tasks, open_tasks + done_tasks, is_test_class=_is_test,
        now=_NOW, window_start=ws_, window_end=we_,
    )
    # Headline covers REAL work only.
    assert part.headline.open_count == 1
    assert part.headline.ages[0].title == "real"
    assert part.headline.throughput_count == 1  # only the real done task
    # Test class carries exactly the synthetic work — surfaced, not dropped.
    assert part.test_class.open_count == 1
    assert part.test_class.ages[0].title == "synthetic"
    assert part.test_class.throughput_count == 1


def test_partition_headline_byte_identical_with_no_test_tasks():
    """The #887 back-compat lock: with ZERO test tickets the headline equals a
    plain compute_flow_metrics over the whole board."""
    open_tasks = [
        {"id": 1, "title": "a", "created": "2026-07-10T12:00:00Z", "done": False},
        {"id": 2, "title": "b", "created": "2026-06-20T12:00:00Z", "done": False},
    ]
    done_tasks = [
        {"id": 3, "done": True, "created": "2026-07-01T00:00:00Z", "done_at": "2026-07-04T00:00:00Z"},
    ]
    ws_, we_ = _win()
    all_tasks = open_tasks + done_tasks
    part = fm.compute_partitioned_flow_metrics(
        open_tasks, all_tasks, is_test_class=lambda t: False,
        now=_NOW, window_start=ws_, window_end=we_,
    )
    plain = fm.compute_flow_metrics(
        open_tasks, all_tasks, now=_NOW, window_start=ws_, window_end=we_,
    )
    assert part.headline == plain
    assert part.test_class.open_count == 0
    assert part.test_class.throughput_count == 0


def test_partition_predicate_fault_keeps_ticket_on_headline():
    """A predicate that RAISES must not hide a ticket — it stays on the actionable
    headline (the conservative direction)."""
    def _boom(task):
        raise RuntimeError("classifier fault")

    open_tasks = [{"id": 1, "title": "x", "created": "2026-07-10T12:00:00Z", "done": False}]
    ws_, we_ = _win()
    part = fm.compute_partitioned_flow_metrics(
        open_tasks, open_tasks, is_test_class=_boom,
        now=_NOW, window_start=ws_, window_end=we_,
    )
    assert part.headline.open_count == 1   # visible on the headline, never hidden
    assert part.test_class.open_count == 0
