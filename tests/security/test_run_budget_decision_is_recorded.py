"""The run-budget decision must SAY which budget won and why (#1359).

**The incident, 2026-08-09.** Battery card B9 staged a 28,800 s per-card envelope and
logged it plainly: *"per-card run envelope: 28800s (driver + monitor)"*. The dispatch
was then killed at **10,901 s** — the 10,800 s config default plus shutdown. Run
``20260809-154357-bd``: two pages merged, one parked, ``implement-header-menu`` cut off
mid-task, and wave 2 (which holds the operator's individual-piece page) never reached.

The run's entire account of this was one line in ``swap-progress.log``:

    The overall run budget elapsed — restoring the 14B.

That sentence is equally true of a 28,800 s budget and a 10,800 s one, so it identifies
nothing. And **every rejection path in the resolver returned a bare ``None``** while the
caller silently fell back, so four candidate causes — never staged, stage failed, went
stale before the dispatch fired, file torn — were indistinguishable after the fact. The
defect could not be diagnosed from a completed run at all; only re-run and hoped at.

Both ends of the channel were silent, which is why the signature was so empty:

* the WRITER swallowed every ``OSError`` and returned ``None``, so a stage that never
  landed looked exactly like a card that never asked for one;
* the READER returned ``None`` for absent / unreadable / torn / non-positive / stale
  alike, and the caller logged nothing at all.

**What this module locks.** Not the budget value — that is a tuning question. It locks
that the DECISION is recorded: which budget was used, where it came from, and on the
rejection paths, why the staged one lost. A fallback that cannot say why it fell back is
not fail-safe, it is fail-silent (#1241 instrument class; security_by_design principle 11).

**Honest limit.** These are unit tests over the resolver and the writer. They prove the
reasons are produced and distinguishable; they do not prove the AO's logger is wired to a
file anyone reads, and they do not fix whatever caused the 2026-08-09 miss — that is still
undiagnosed, and this instrument exists so the next occurrence names itself.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from shared.fleet.swap_ops import (
    CARD_RUN_BUDGET_MAX_S,
    PENDING_RUN_BUDGET_FRESH_S,
    pending_run_budget_path,
    read_pending_run_budget,
    resolve_pending_run_budget,
    write_pending_run_budget,
)


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """A config whose swap dir is an empty tmp dir."""
    swap = tmp_path / "fleet-swap"
    swap.mkdir()
    monkeypatch.setattr("shared.fleet.swap_ops.swap_dir", lambda _c: swap)
    return SimpleNamespace(_swap=swap)


# ---------------------------------------------------------------------------
# Every rejection path names itself, and they are distinguishable
# ---------------------------------------------------------------------------


def test_absent_file_says_absent_and_names_the_path(cfg: SimpleNamespace) -> None:
    """The benign case and the failed-stage case share this signature — so name the path.

    A reader who knows WHICH path was checked can settle "was it ever written?" by
    looking. A bare None leaves them re-running the battery to find out.
    """
    seconds, reason = resolve_pending_run_budget(cfg)
    assert seconds is None
    assert "absent" in reason
    assert str(pending_run_budget_path(cfg)) in reason


def test_a_stale_budget_says_stale_and_reports_the_age(cfg: SimpleNamespace) -> None:
    """CONFIRMED as the 2026-08-09 cause, by this very reason string on its first run.

    Within thirty minutes of shipping, `night-20260809-194335` printed::

        run budget: using the CONFIG DEFAULT 10800s — staged budget REJECTED as STALE:
        28800s written 431s ago, freshness window 300s

    one second after `dispatch assets: 8/8 written`. The file is consumed at EXECUTE,
    on the far side of asset generation — ~303 s for 8 images — so the old 300 s window
    could never survive an image-carrying card. The arithmetic in the reason is what
    made that readable at a glance instead of another night of hypotheses.
    """
    path = pending_run_budget_path(cfg)
    path.write_text(
        json.dumps({
            "run_budget_s": 28800.0,
            "written_at": time.time() - (PENDING_RUN_BUDGET_FRESH_S + 60.0),
        }),
        encoding="utf-8",
    )
    seconds, reason = resolve_pending_run_budget(cfg)
    assert seconds is None
    assert "STALE" in reason
    assert "28800" in reason, "the reason must name the budget that was thrown away"
    assert str(int(PENDING_RUN_BUDGET_FRESH_S)) in reason, "and the window it missed"


def test_a_torn_file_says_unparseable_not_absent(cfg: SimpleNamespace) -> None:
    """A half-written file is a different defect from a missing one — and a different fix."""
    pending_run_budget_path(cfg).write_text('{"run_budget_s": 288', encoding="utf-8")
    seconds, reason = resolve_pending_run_budget(cfg)
    assert seconds is None
    assert "unparseable" in reason
    assert "absent" not in reason


def test_a_cleared_budget_is_not_reported_as_a_failure(cfg: SimpleNamespace) -> None:
    """Precision: a card asking for the default is normal, not a fault.

    Reporting it as one would train a reader to skim the line, which is how the real
    warning gets missed.
    """
    pending_run_budget_path(cfg).write_text(
        json.dumps({"run_budget_s": 0.0, "written_at": time.time()}), encoding="utf-8"
    )
    seconds, reason = resolve_pending_run_budget(cfg)
    assert seconds is None
    assert "CLEARED" in reason
    assert "REJECTED" not in reason


# ---------------------------------------------------------------------------
# The success paths are recorded too — "it worked" must be visible
# ---------------------------------------------------------------------------


def test_an_honored_budget_says_so_with_its_age(cfg: SimpleNamespace) -> None:
    """Silence on success is why nobody noticed this channel had never worked."""
    assert write_pending_run_budget(cfg, 28800.0) is True
    seconds, reason = resolve_pending_run_budget(cfg)
    assert seconds == 28800.0
    assert "HONORED" in reason
    assert "28800" in reason


def test_a_clamped_budget_says_clamped_rather_than_honored(cfg: SimpleNamespace) -> None:
    """A card asking beyond the ceiling gets less than it asked for — that is not a pass."""
    over = CARD_RUN_BUDGET_MAX_S + 3600.0
    write_pending_run_budget(cfg, over)
    seconds, reason = resolve_pending_run_budget(cfg)
    assert seconds == CARD_RUN_BUDGET_MAX_S
    assert "CLAMPED" in reason
    assert str(int(over)) in reason, "the reason must name what the card actually asked for"


def test_the_b9_envelope_is_honored_end_to_end(cfg: SimpleNamespace) -> None:
    """The exact 2026-08-09 value, through the real writer and the real reader.

    28,800 s sits ON the clamp ceiling, which is the value most likely to be quietly
    mishandled by an off-by-one — and it is the number B9 actually stages.
    """
    assert write_pending_run_budget(cfg, 28800.0) is True
    seconds, reason = resolve_pending_run_budget(cfg)
    assert seconds == 28800.0, f"B9's own envelope was not honored: {reason}"
    assert "CLAMPED" not in reason, "28800 is AT the ceiling, not over it"


# ---------------------------------------------------------------------------
# Contract preservation
# ---------------------------------------------------------------------------


def test_consume_once_still_holds(cfg: SimpleNamespace) -> None:
    """The file must not survive to a second dispatch — the guard predates #1359."""
    write_pending_run_budget(cfg, 28800.0)
    first, _ = resolve_pending_run_budget(cfg)
    assert first == 28800.0
    assert not pending_run_budget_path(cfg).exists(), "the override was not consumed"
    second, reason = resolve_pending_run_budget(cfg)
    assert second is None, "an override bled into a second dispatch"
    assert "absent" in reason


def test_a_torn_file_is_consumed_too(cfg: SimpleNamespace) -> None:
    """Deletion happens BEFORE honoring, so a hostile file cannot survive to retry."""
    pending_run_budget_path(cfg).write_text("{{{ not json", encoding="utf-8")
    resolve_pending_run_budget(cfg)
    assert not pending_run_budget_path(cfg).exists()


def test_the_thin_wrapper_still_returns_a_bare_value(cfg: SimpleNamespace) -> None:
    """Existing callers and tests depend on this signature; the refactor must not move it."""
    write_pending_run_budget(cfg, 14400.0)
    assert read_pending_run_budget(cfg) == 14400.0
    assert read_pending_run_budget(cfg) is None


def test_the_freshness_window_survives_asset_generation() -> None:
    """The window must outlast the gap it actually spans — write→EXECUTE, not write→dispatch.

    **The measured gap is 431 s** (`night-20260809-194335`), because the file is consumed
    at EXECUTE, which sits on the far side of the PLAN chain AND of dispatch-asset
    generation (~303 s for B9's 8 images at 37.9 s each). The old 300 s window could not
    survive that, so B9 silently ran on the config default every night it has ever run.

    This is a FLOOR, not a target. It exists because the previous value was chosen against
    the wrong interval and nothing caught it for weeks — the constant looked reasonable,
    and the rationale beside it named a gap that was not the one being measured.
    """
    from shared.fleet.swap_ops import PENDING_RUN_BUDGET_FRESH_S

    measured_gap_s = 431.0
    assert PENDING_RUN_BUDGET_FRESH_S > measured_gap_s, (
        f"the freshness window ({PENDING_RUN_BUDGET_FRESH_S:.0f}s) does not survive the "
        f"MEASURED write→EXECUTE gap ({measured_gap_s:.0f}s on night-20260809-194335), so "
        "every per-card budget on an image-carrying card is silently discarded (#1359)"
    )
    # PLAN's own budget (720 s) plus asset generation (~303 s) is the shape of the worst
    # case; a window under that is a bet that the plan is never slow.
    worst_case_s = 720.0 + 303.0
    assert PENDING_RUN_BUDGET_FRESH_S >= worst_case_s, (
        f"the window ({PENDING_RUN_BUDGET_FRESH_S:.0f}s) is under the theoretical worst "
        f"case ({worst_case_s:.0f}s = PLAN_RESPONSE_TIMEOUT_S + 8-asset generation)"
    )


def test_the_writer_reports_failure_instead_of_swallowing_it(
    cfg: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TOGGLE PROOF for the writer half. Before #1359 this returned None on any OSError.

    A stage that never landed produced the identical signature to a card that never
    asked for one, at both ends. That is the specific blindness this locks shut.
    """
    def _boom(*_a: object, **_k: object) -> None:
        raise OSError("disk is not having it")

    monkeypatch.setattr(Path, "write_text", _boom)
    assert write_pending_run_budget(cfg, 28800.0) is False, (
        "a failed stage reported success — the AO will silently use the config default "
        "and the card will be cut short with no record (#1359)"
    )
