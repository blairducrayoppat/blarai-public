"""The sustained-throughput harness must stamp WHEN each run was taken (#1487 item 2).

WHY THIS EXISTS. #1487 measured one unchanged coder configuration at 16.55, then 11.82, then
9.59 tok/s inside one hour on an idle box. The effect was invisible for exactly one reason:
**nothing in any performance stamp recorded when in the session a number was taken**, so a
sequential A/B could not be distinguished from the machine degrading underneath it. A stamp
that silently stops being written looks identical to a machine that stopped drifting.

THIS FILE IS THE STRUCTURAL CONTROL LESSON 30 OWED, and its first version was an instance of
lesson 30 instead. Independent review mutated the harness seven ways; **four passed clean**:

    M1  elapsed_session_s pinned to 0.0 on every run        -> 5 passed
    M3  machine_uptime_s() frozen to a constant             -> 5 passed
    M4  elapsed_session_s = absolute wall clock, not offset -> 5 passed
    M5  the clock captured AFTER the generate call          -> 5 passed
    M7  every stamp removed entirely                        -> 2 failed only

Root causes, both now closed: `sorted()` is satisfied by a constant sequence, and
`machine_uptime_s` was checked for KEY PRESENCE and never for type or value. The old toggle
test was worse than useless -- it deleted keys from a dict it had just built and asserted they
were missing, which holds for any input including a harness that stamps nothing.

WHAT IS LOCKED NOW. Offsets and machine age must be positive, real numbers, and STRICTLY
increasing. Run 0's offset must be small enough to prove the clock was read BEFORE the call
rather than after it. A run whose generation RAISED still carries all three fields. And the
toggle disables `stamp_run` in the harness itself and re-runs these same assertions, so it
mutates the subject rather than re-implementing a check.

HONEST LIMITS, stated because a docstring implying an airtight predicate is how the first
version got trusted.
  * This drives `main()` with the model server stubbed out, so it locks the STAMPING contract
    and not the measurement. Throughput correctness needs a real GPU and belongs to the
    hardware tier.
  * **A counter is not fully distinguishable from a clock here.** Replacing the session offset
    with `i * 0.5` -- a bare counter with no clock behind it -- passes every assertion below,
    because in a stubbed harness where each generation takes a fixed `_GEN_SECONDS`, a counter
    whose step coincides with that time produces exactly the sequence a real clock would. What
    constrains the OFFSET's origin is `offs[0] < _GEN_SECONDS`, not the cross-check; the
    cross-check constrains RATE AGREEMENT between the two clocks. No assertion available in a
    stubbed harness closes the counter case. Found by independent review; recorded rather than
    papered over.
  * **The machine clock's ORIGIN is validated by nothing (#1493).** A reading in correct units
    from the wrong origin -- seconds since local midnight, or uptime minus a constant -- passes
    every assertion here: the rate is right, so the cross-check agrees *exactly*, and only
    origins more than a year off breach the plausibility bound. It also reads plausibly to a
    human. **This is the failure that would silently invalidate #1487's like-machine-age
    comparisons**, because a constant offset shifts every record identically. Closing it needs a
    second, independent boot-time source -- `Win32_OperatingSystem.LastBootUpTime`, from the CIM
    class `sample_resources()` already shells to. Ticketed as #1493 rather than built here.
  * A SCALE error strictly between x0.5 and x1.58 also passes both guards (the rate check admits
    x0.5-x3.0, the cross-check x0.417-x1.583). Real unit confusions -- x1000, x60, x2 -- all fall
    outside and are caught, so this is recorded for completeness, not as a gap worth machinery.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "scripts" / "measure_coder_sustained.py"

#: How long each stubbed generation takes. Must be comfortably larger than the harness's own
#: per-run overhead, because run 0's offset is compared against it to prove the clock is read
#: before the call (mutation M5) rather than after.
_GEN_SECONDS = 0.6


def _load_harness():
    """Import the script by path -- `scripts/` is not a package."""
    spec = importlib.util.spec_from_file_location("_measure_coder_sustained", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def harness():
    return _load_harness()


# ── the shared predicate: used by the real locks AND by the toggle ──────────


def assert_fully_stamped(rec: dict, expected_runs: int) -> None:
    """Every property #1487 item 2 requires of a record. Raises AssertionError naming the miss.

    Called by the locks below against a real record, and by the toggle against a record from a
    harness whose stamping was disabled. One implementation, two subjects -- that is what makes
    the toggle evidence rather than decoration.
    """
    runs = rec["runs"]
    assert len(runs) == expected_runs, f"expected {expected_runs} runs, got {len(runs)}"
    assert [r.get("index") for r in runs] == list(range(expected_runs)), (
        f"run indices must be 0..{expected_runs - 1}, got {[r.get('index') for r in runs]}"
    )

    for r in runs:
        for field in ("elapsed_session_s", "machine_uptime_s"):
            assert field in r, f"run {r.get('index')} carries no {field}"
        off = r["elapsed_session_s"]
        assert isinstance(off, (int, float)) and not isinstance(off, bool), (
            f"elapsed_session_s must be a number, got {off!r}"
        )
        assert off >= 0, f"elapsed_session_s must not be negative, got {off}"
        age = r["machine_uptime_s"]
        assert isinstance(age, (int, float)) and not isinstance(age, bool), (
            f"machine_uptime_s must be a number, got {age!r} -- a null stamp answers nothing"
        )
        assert age > 0, f"machine_uptime_s must be positive, got {age}"

    offs = [r["elapsed_session_s"] for r in runs]
    assert all(b > a for a, b in zip(offs, offs[1:])), (
        f"session offsets must STRICTLY increase -- a constant passes a sorted() check while "
        f"recording nothing (mutation M1/M4). Got {offs}"
    )
    ages = [r["machine_uptime_s"] for r in runs]
    assert all(b > a for a, b in zip(ages, ages[1:])), (
        f"machine age must STRICTLY increase -- a frozen clock is the M3 mutation and it is "
        f"indistinguishable from a healthy one without this. Got {ages}"
    )

    # `offs` and `ages` measure the SAME elapsed interval from different origins, so their
    # per-run deltas must agree. This kills a seconds/milliseconds unit error at any uptime: a
    # ms-valued age advances ~1000x faster than the offset over the same wall time.
    for (o0, a0), (o1, a1) in zip(zip(offs, ages), zip(offs[1:], ages[1:])):
        assert abs((a1 - a0) - (o1 - o0)) <= 0.35, (
            f"session offset advanced {o1 - o0:.1f}s while machine age advanced {a1 - a0:.1f}s "
            f"over the same interval -- two clocks over one interval must agree (a unit error "
            f"in either shows up here regardless of how long the box has been up)"
        )

    # M5: the clock is read BEFORE the generation, so run 0's offset reflects the moment it
    # started, not the moment it finished. Captured after, run 0's offset would include a whole
    # generation.
    assert offs[0] < _GEN_SECONDS, (
        f"run 0's offset is {offs[0]}s, >= one generation ({_GEN_SECONDS}s) -- the clock is "
        f"being read AFTER the call, so a run that times out is stamped where it ENDED"
    )

    clock = rec["session_clock"]
    assert isinstance(clock.get("machine_uptime_at_start_s"), (int, float))
    assert clock["machine_uptime_at_start_s"] > 0
    assert clock["harness_wall_s"] >= 0
    assert "#1487" in clock["note"]
    assert "interleav" in clock["note"].lower()


# ── driving the harness with the server stubbed ────────────────────────────


def _ok_run(_n):
    return {"prompt_tokens": 100, "completion_tokens": 8, "wall_s": 1.0,
            "decode_tps": 8.0, "output_chars": 500, "produced_markup": True}


def _run_main(harness, monkeypatch, tmp_path, generate_impl, runs=3):
    """Drive main() with the server stubbed, and return the record it wrote."""
    # main() issues a DISCARDED warmup generation before run 0. Counting it as a run is how the
    # first version of this test aimed its induced failure at the wrong index -- so the warmup is
    # identified by its fixed 64-token budget and excluded.
    calls = {"n": 0}

    def fake_generate(prompt, max_tokens, timeout):
        if max_tokens == 64:
            return _ok_run(0)
        calls["n"] += 1
        time.sleep(_GEN_SECONDS)  # real elapsed time, so the offset checks have something to see
        return generate_impl(calls["n"])

    monkeypatch.setattr(harness, "generate", fake_generate)
    monkeypatch.setattr(harness, "ao_is_up", lambda: False)
    monkeypatch.setattr(harness, "build_prompt", lambda: "PROMPT")
    monkeypatch.setattr(harness, "sample_resources", lambda: None)

    class _Resp:
        def read(self):
            return b'{"data":[{"id":"coder-30b"}]}'

    monkeypatch.setattr(harness.urllib.request, "urlopen", lambda *a, **k: _Resp())
    # The harness writes to _REPO_ROOT/docs/performance, NOT the working directory -- so chdir
    # alone would bank fake records into the real dataset. Found by running it: the first green
    # attempt left a `coder_sustained_locktest_*.json` beside genuine measurements.
    monkeypatch.setattr(harness, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        sys, "argv",
        ["measure_coder_sustained.py", "--runs", str(runs), "--max-tokens", "8",
         "--sample-every", "999", "--label", "locktest"],
    )

    assert harness.main() == 0
    written = list((tmp_path / "docs" / "performance").glob("coder_sustained_locktest_*.json"))
    assert len(written) == 1, f"expected exactly one record, got {written}"
    return json.loads(written[0].read_text(encoding="utf-8"))


# ── the locks ──────────────────────────────────────────────────────────────


def test_machine_uptime_reads_a_plausible_positive_value(harness):
    """The clock the whole finding rests on. None is allowed (a non-Windows checkout); a
    negative or zero reading is not, because it would silently anchor every record to boot.

    THE UNIT CHECK IS THE POINT, and the bound below is not enough on its own. Dropping the
    `/1000.0` from `GetTickCount64()` makes every stamped age 1000x too large, and that passes
    positivity, strict increase and `isinstance` -- every other lock in this file. The one-year
    bound catches it ONLY once the machine has been up more than 8.76 hours, so on a
    recently-booted box a unit error is green. A lock whose ability to fail depends on when you
    run it is the defect class this file exists to remove, so the clock is watched ADVANCING
    instead.
    """
    up = harness.machine_uptime_s()
    if up is None:
        pytest.skip("GetTickCount64 unavailable on this platform")
    assert up > 0, f"machine uptime must be positive, got {up}"
    assert up < 60 * 60 * 24 * 365, f"implausible uptime {up}s -- unit error?"

    before = harness.machine_uptime_s()
    time.sleep(0.3)
    after = harness.machine_uptime_s()
    advanced = after - before
    assert 0.15 <= advanced <= 0.9, (
        f"machine_uptime_s advanced {advanced} over 0.3 s of wall time -- it must be SECONDS. "
        f"A milliseconds reading advances ~300 here, and the one-year bound above only catches "
        f"that once uptime exceeds 8.76 hours."
    )


def test_a_full_run_is_stamped_with_index_offset_and_machine_age(harness, monkeypatch, tmp_path):
    rec = _run_main(harness, monkeypatch, tmp_path, _ok_run, runs=3)
    assert_fully_stamped(rec, expected_runs=3)


def test_a_run_that_RAISED_still_carries_its_position_in_time(harness, monkeypatch, tmp_path):
    """A failed run is evidence about the machine at that moment; dropping its timestamp loses
    exactly the run most worth placing."""
    def flaky(n):
        if n == 2:
            raise RuntimeError("server died mid-generation")
        return _ok_run(n)

    rec = _run_main(harness, monkeypatch, tmp_path, flaky, runs=3)
    assert_fully_stamped(rec, expected_runs=3)

    failed = [r for r in rec["runs"] if "error" in r]
    assert len(failed) == 1, f"expected exactly one failed run, got {rec['runs']}"
    assert failed[0]["index"] == 1
    assert rec["errors"] == 1


# ── the toggle: the harness itself is mutated, and the REAL locks are re-run ─


def test_a_harness_that_STOPS_STAMPING_is_REFUSED(harness, monkeypatch, tmp_path):
    """Disable `stamp_run` in the harness and prove the assertions above go red.

    This is the lock that was decoration in the first version: it used to delete keys from a
    dict it had just built and assert they were missing, which is true of any input. It was
    green against a harness that stamped nothing. Now the SUBJECT is mutated and the SAME
    predicate runs, so a pass here means the predicate can actually fail.
    """
    monkeypatch.setattr(harness, "stamp_run", lambda r, index, session_s, uptime_s: r)
    rec = _run_main(harness, monkeypatch, tmp_path, _ok_run, runs=3)
    with pytest.raises(AssertionError):
        assert_fully_stamped(rec, expected_runs=3)


def test_a_FROZEN_machine_clock_is_REFUSED(harness, monkeypatch, tmp_path):
    """Mutation M3. A clock that never advances passed every check in the first version, and it
    is the exact failure a stale or broken uptime source would produce."""
    monkeypatch.setattr(harness, "machine_uptime_s", lambda: 1234.0)
    rec = _run_main(harness, monkeypatch, tmp_path, _ok_run, runs=3)
    with pytest.raises(AssertionError, match="STRICTLY increase"):
        assert_fully_stamped(rec, expected_runs=3)


def test_a_NULL_machine_clock_is_REFUSED(harness, monkeypatch, tmp_path):
    """Mutation M2. It used to surface as a SKIP, which the gate's `0 skipped` bar would catch
    only by accident; a record whose machine age is null answers nothing and must fail here."""
    monkeypatch.setattr(harness, "machine_uptime_s", lambda: None)
    rec = _run_main(harness, monkeypatch, tmp_path, _ok_run, runs=3)
    with pytest.raises(AssertionError, match="machine_uptime_s must be a number"):
        assert_fully_stamped(rec, expected_runs=3)
