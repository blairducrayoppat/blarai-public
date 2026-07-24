"""Locks for the C3 heartbeat timer thread + factory + liveness stamp (#845 limb 6).

The design-§3.2 dormancy locks (the doom-watchdog factory pattern, verbatim shapes:
absent→None, false→None, true→builds-with-registered-cadence, OFF-path-imports-
nothing), the §6.1 self-declaring liveness stamp, the §3.3 wall-3 thread-death
stamp, the §7.2 graduation seen-set reset wiring, the limb-4/5 review obligations
(conditions through route_tripwire; proposal copies; the has_text draft mapping),
and the #783-class bare-import lock (child interpreter — no module-scope side
effects, no thread, no lazy-machinery import on the OFF path).
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from shared.coordinator import cadence
from shared.coordinator import heartbeat as hb
from shared.coordinator import heartbeat_cycle as hc
from shared.fleet.coord_redispatch import RedispatchCycleResult, StagedRedispatch
from shared.fleet.coord_stall_state import read_seen_state, write_seen_state, StallSeenState

_REPO_ROOT = str(Path(__file__).resolve().parents[2])

NOW = datetime(2026, 7, 14, 20, 0, 0, tzinfo=timezone.utc)
LOCAL = datetime(2026, 7, 14, 15, 0, 0)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


class _RouterSpy:
    def __init__(self) -> None:
        self.tripwire: list[Any] = []
        self.copies: list[Any] = []
        self.digests: list[Any] = []

    def route_tripwire(self, condition):
        self.tripwire.append(condition)

    def record_proposal_copy(self, payload):
        self.copies.append(dict(payload))

    def route_digest(self, digest):
        self.digests.append(digest)


def _decision(interval: float = 900.0) -> cadence.CycleDecision:
    return cadence.CycleDecision(
        mode=cadence.CycleMode.FULL, next_interval_s=interval
    )


def _result(
    *,
    interval: float = 900.0,
    conditions: tuple = (),
    digest: "hc.DigestRecord | None" = None,
    redispatch: "RedispatchCycleResult | None" = None,
) -> hc.CycleResult:
    return hc.CycleResult(
        started_at=NOW.isoformat(),
        decision=_decision(interval),
        steps=(hc.StepOutcome("mode-resolution", True, "FULL"),),
        conditions=conditions,
        digest=digest,
        redispatch=redispatch,
    )


def _heartbeat(
    tmp_path: Path,
    *,
    cycle_fn,
    router: "_RouterSpy | None" = None,
    shadow_mode: bool = True,
    boot_grace_s: float = 0.0,
    cleanup_started=lambda: False,
    max_cycles: "int | None" = 1,
    interval_s: float = 900.0,
) -> "tuple[hb.Heartbeat, _RouterSpy, Path, Path]":
    spy = router or _RouterSpy()
    stamp = tmp_path / "coord" / "heartbeat-liveness.json"
    seen = tmp_path / "coord" / "stall_seen.json"
    beat = hb.Heartbeat(
        env=SimpleNamespace(),  # the injected cycle_fn never touches it
        router=spy,
        interval_s=interval_s,
        boot_grace_s=boot_grace_s,
        shadow_mode=shadow_mode,
        stamp_path=stamp,
        seen_path=seen,
        cleanup_started=cleanup_started,
        clock=lambda: NOW,
        local_clock=lambda: LOCAL,
        cycle_fn=cycle_fn,
        max_cycles=max_cycles,
    )
    return beat, spy, stamp, seen


def _run_to_completion(beat: hb.Heartbeat, timeout: float = 10.0) -> None:
    beat.start()
    thread = beat._thread  # noqa: SLF001 — test joins the real thread
    assert thread is not None
    thread.join(timeout=timeout)
    assert not thread.is_alive(), "heartbeat thread did not finish in time"


# ---------------------------------------------------------------------------
# Factory dormancy locks (§3.2 — the four doom-watchdog shapes)
# ---------------------------------------------------------------------------


class _FakeService(SimpleNamespace):
    """The AO-property surface the factory reads (attributes only)."""


def _enabled_service(tmp_path: Path) -> _FakeService:
    return _FakeService(
        coordinator_heartbeat_enabled=True,
        coordinator_enabled=False,
        coordinator_projects={"alpha": 3},
        coordinator_battery_campaign_state_path="",
        coordinator_heartbeat_interval_s=900.0,
        coordinator_heartbeat_battery_multiplier=4.0,
        coordinator_heartbeat_boot_grace_s=300.0,
        coordinator_overnight_window="23:00-09:00",
        coordinator_operator_absent=False,
        coordinator_shadow_mode=True,
        fleet_dispatch_agentic_setup_dir=str(tmp_path / "agentic"),
        fleet_dispatch_projects_dir=str(tmp_path / "projects"),
    )


def test_absent_attribute_builds_nothing() -> None:
    assert hb.build_heartbeat(object(), cleanup_started=lambda: False) is None


def test_false_flag_builds_nothing() -> None:
    service = _FakeService(coordinator_heartbeat_enabled=False)
    assert hb.build_heartbeat(service, cleanup_started=lambda: False) is None


def test_true_flag_builds_with_registered_cadence(tmp_path: Path) -> None:
    beat = hb.build_heartbeat(
        _enabled_service(tmp_path),
        cleanup_started=lambda: False,
        data_dir=tmp_path / "data",
        dev_mode=True,
    )
    assert isinstance(beat, hb.Heartbeat)
    assert beat._interval_s == 900.0  # noqa: SLF001 — the registered default
    assert beat._boot_grace_s == 300.0  # noqa: SLF001
    assert beat._shadow_mode is True  # noqa: SLF001
    assert not beat.running  # built, NOT started — start() is the launcher's call


def test_built_env_wires_router_sinks_and_store(tmp_path: Path) -> None:
    beat = hb.build_heartbeat(
        _enabled_service(tmp_path),
        cleanup_started=lambda: False,
        data_dir=tmp_path / "data",
        dev_mode=True,
    )
    assert beat is not None
    env = beat._env  # noqa: SLF001
    router = beat._router  # noqa: SLF001
    assert env.post_stall_comment == router.post_stall_comment
    assert env.move_card == router.move_card
    assert env.shadow_mode is True
    assert env.store is not None  # dev-mode store built + boot-reconciled
    assert env.roots.coordinator_store_root == tmp_path / "data" / "coordinator"
    assert env.coordinator_projects == {"alpha": 3}


def test_journal_provisioning_failure_refuses_to_start(
    tmp_path: Path, monkeypatch
) -> None:
    """Fail-closed: no journal ⇒ no heartbeat (in shadow the journal IS the
    output path). The factory returns None with an ERROR log, never a
    journal-less heartbeat."""
    monkeypatch.delenv("BLARAI_DEK_KEYSTORE", raising=False)
    beat = hb.build_heartbeat(
        _enabled_service(tmp_path),
        cleanup_started=lambda: False,
        data_dir=tmp_path / "data",
        dev_mode=False,  # production posture, no keystore provisioned
    )
    assert beat is None


# ---------------------------------------------------------------------------
# The loop: stamp, cadence, teardown, thread-death (§3.1/§3.3/§6.1)
# ---------------------------------------------------------------------------


def test_one_cycle_writes_self_declaring_stamp(tmp_path: Path) -> None:
    beat, _spy, stamp_path, _ = _heartbeat(
        tmp_path, cycle_fn=lambda env, **kw: _result(interval=3600.0)
    )
    _run_to_completion(beat)
    stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
    assert stamp["mode"] == "FULL"
    assert stamp["thread_dead"] is False
    assert stamp["shadow_mode"] is True
    assert stamp["next_interval_s"] == 3600.0
    # The stamp declares its OWN deadline: completed + the DECISION's interval
    # (battery/overnight stretching travels inside the stamp, §6.1).
    expected = (NOW + timedelta(seconds=3600.0)).isoformat()
    assert stamp["next_expected_by"] == expected
    assert stamp["steps"][0]["name"] == "mode-resolution"


def test_cycle_kwargs_first_cycle_is_boot_grace(tmp_path: Path) -> None:
    seen_kwargs: list[dict] = []

    def cycle_fn(env, **kw):
        seen_kwargs.append(kw)
        return _result(interval=0.01)  # keep the inter-cycle wait test-fast

    beat, *_ = _heartbeat(tmp_path, cycle_fn=cycle_fn, max_cycles=2)
    _run_to_completion(beat)
    assert len(seen_kwargs) == 2
    assert seen_kwargs[0]["in_boot_grace"] is True  # the idle-grace floor
    assert seen_kwargs[1]["in_boot_grace"] is False
    assert seen_kwargs[0]["now"] == NOW and seen_kwargs[0]["local_now"] == LOCAL


def test_stop_during_boot_grace_runs_no_cycle(tmp_path: Path) -> None:
    calls: list[int] = []
    beat, _spy, stamp_path, _ = _heartbeat(
        tmp_path,
        cycle_fn=lambda env, **kw: calls.append(1) or _result(),
        boot_grace_s=30.0,
        max_cycles=None,
    )
    beat.start()
    time.sleep(0.05)
    beat.stop()
    assert calls == []
    # No CYCLE ran — the only stamp is stop()'s clean-stop marker (§6.3), which
    # the next boot's reconcile reads as silence (limb 7).
    stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
    assert stamp["stopped_cleanly"] is True and stamp["mode"] == "STOPPED"


def test_cleanup_started_exits_before_cycle(tmp_path: Path) -> None:
    calls: list[int] = []
    beat, *_ = _heartbeat(
        tmp_path,
        cycle_fn=lambda env, **kw: calls.append(1) or _result(),
        cleanup_started=lambda: True,
        max_cycles=None,
    )
    _run_to_completion(beat)
    assert calls == []


def test_escaped_exception_stamps_thread_dead(tmp_path: Path) -> None:
    """§3.3 wall 3: an escape past the cycle wall is stamped thread_dead=true —
    what the limb-7 dead-man trips on immediately. The note carries the
    exception TYPE only (review 8c18ed43 MINOR-2 — the message could carry
    deep-layer content; the full text belongs to the ERROR log)."""

    def exploding(env, **kw):
        raise RuntimeError("wall-2 breach with a secret ticket title in it")

    beat, _spy, stamp_path, _ = _heartbeat(tmp_path, cycle_fn=exploding)
    _run_to_completion(beat)
    stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
    assert stamp["thread_dead"] is True
    assert stamp["note"] == "RuntimeError"
    assert "secret ticket title" not in json.dumps(stamp)
    assert not beat.running  # the thread died — loudly, not silently


def test_failed_step_detail_bounded_to_exception_type(tmp_path: Path) -> None:
    """Review 8c18ed43 MINOR-2: a FAILED step's stamp record carries the
    exception type, never the message; a successful step's deterministic
    detail stays."""
    result = hc.CycleResult(
        started_at=NOW.isoformat(),
        decision=_decision(),
        steps=(
            hc.StepOutcome("compose-snapshot", True, "3 projects"),
            hc.StepOutcome(
                "redispatch-staging", False,
                "RuntimeError: refused task 'fix the SECRET widget'",
            ),
        ),
    )
    beat, _spy, stamp_path, _ = _heartbeat(tmp_path, cycle_fn=lambda env, **kw: result)
    _run_to_completion(beat)
    stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
    by_name = {s["name"]: s for s in stamp["steps"]}
    assert by_name["compose-snapshot"]["detail"] == "3 projects"
    assert by_name["redispatch-staging"]["detail"] == "RuntimeError"
    assert "SECRET" not in json.dumps(stamp)


def test_rematerialized_config_covers_every_cycle_read() -> None:
    """Review 8c18ed43 MINOR-1 drift lock: the factory re-materializes only the
    CoordinatorConfig fields the cycle engine reads — any NEW cfg.<field> read
    in the engine fails here until the field is carried (or a real
    coordinator_config AO property replaces the re-materialization)."""
    import inspect
    import re

    source = inspect.getsource(hc)
    reads = set(re.findall(r"\bcfg\.(\w+)", source))
    carried = {
        "enabled",
        "heartbeat_enabled",
        "heartbeat_interval_s",
        "heartbeat_battery_multiplier",
        "heartbeat_boot_grace_s",
        "overnight_window",
        "operator_absent",
        "shadow_mode",
    }
    assert reads, "the scan found no cfg.<attr> reads — the lock's regex rotted"
    assert reads <= carried, (
        f"the cycle engine reads CoordinatorConfig fields the factory drops: "
        f"{sorted(reads - carried)}"
    )


def test_next_wait_follows_the_decision_interval(tmp_path: Path) -> None:
    """Battery/overnight stretching travels into the WAIT, not just the stamp:
    the heartbeat is constructed with a 999 s interval, but the cycle DECISION
    says 0.02 s — two cycles completing within the join window proves the loop
    waits on the decision's interval, not the constructor's."""
    beat, _spy, stamp_path, _ = _heartbeat(
        tmp_path,
        cycle_fn=lambda env, **kw: _result(interval=0.02),
        max_cycles=2,
        interval_s=999.0,
    )
    _run_to_completion(beat, timeout=10.0)
    stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
    assert stamp["next_interval_s"] == 0.02  # and the stamp declares the same


# ---------------------------------------------------------------------------
# Routing obligations (limb-4/5 reviews — #845 c.1895/c.1896)
# ---------------------------------------------------------------------------


def test_every_condition_routes_through_route_tripwire(tmp_path: Path) -> None:
    conditions = (
        hc.SurfacedCondition("quiet-queue-tripwire", "ready and idle"),
        hc.SurfacedCondition("substrate-unreachable", "vikunja down", machinery_health=True),
    )
    beat, spy, *_ = _heartbeat(
        tmp_path, cycle_fn=lambda env, **kw: _result(conditions=conditions)
    )
    _run_to_completion(beat)
    assert [c.kind for c in spy.tripwire] == [
        "quiet-queue-tripwire",
        "substrate-unreachable",
    ]


def test_shadow_staged_drafts_get_proposal_copies(tmp_path: Path) -> None:
    redispatch = RedispatchCycleResult(
        staged=(
            StagedRedispatch(task="fix widget", proposal_id="p-1", fingerprint="fp-1"),
        )
    )
    beat, spy, *_ = _heartbeat(
        tmp_path, cycle_fn=lambda env, **kw: _result(redispatch=redispatch)
    )
    _run_to_completion(beat)
    assert len(spy.copies) == 1
    assert spy.copies[0]["proposal_id"] == "p-1"
    assert spy.copies[0]["fingerprint"] == "fp-1"


def test_digest_routes_exactly_once_per_cycle(tmp_path: Path) -> None:
    digest = hc.DigestRecord(
        cycle_started_at=NOW.isoformat(),
        mode="FULL",
        queue_depth={},
        open_by_project={},
        open_delta_by_project={},
        stalls_new=0,
        stalls_ongoing=0,
        conditions=(),
        proposals_pending=0,
        runs_harvested=(),
    )
    beat, spy, *_ = _heartbeat(
        tmp_path, cycle_fn=lambda env, **kw: _result(digest=digest)
    )
    _run_to_completion(beat)
    assert spy.digests == [digest]


def test_router_fault_does_not_kill_the_loop(tmp_path: Path) -> None:
    class _ExplodingRouter(_RouterSpy):
        def route_tripwire(self, condition):
            raise RuntimeError("router down")

    conditions = (hc.SurfacedCondition("quiet-queue-tripwire", "x"),)
    beat, _spy, stamp_path, _ = _heartbeat(
        tmp_path,
        cycle_fn=lambda env, **kw: _result(conditions=conditions),
        router=_ExplodingRouter(),
    )
    _run_to_completion(beat)
    stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
    assert stamp["thread_dead"] is False  # wall 2 held; the stamp still landed


# ---------------------------------------------------------------------------
# Graduation seen-set reset wiring (§7.2)
# ---------------------------------------------------------------------------


def _write_stamp_with_mode(stamp_path: Path, shadow: bool) -> None:
    stamp_path.parent.mkdir(parents=True, exist_ok=True)
    stamp_path.write_text(
        json.dumps({"shadow_mode": shadow, "started_at": "x"}), encoding="utf-8"
    )


def test_shadow_to_live_edge_resets_seen_set(tmp_path: Path) -> None:
    beat, _spy, stamp_path, seen_path = _heartbeat(
        tmp_path, cycle_fn=lambda env, **kw: _result(), shadow_mode=False
    )
    _write_stamp_with_mode(stamp_path, shadow=True)  # prior boot ran shadow
    write_seen_state(
        StallSeenState(fingerprints=frozenset({"Standard:42"})), path=seen_path
    )
    _run_to_completion(beat)
    assert read_seen_state(seen_path).fingerprints == frozenset()  # reset once


def test_graduation_reset_stamps_current_mode_immediately(tmp_path: Path) -> None:
    """Review 8c18ed43 MINOR-3: the reset and the current-mode recording are
    one motion — a crash between the reset and the first cycle's stamp can no
    longer re-fire the reset next boot."""
    beat, _spy, stamp_path, seen_path = _heartbeat(
        tmp_path,
        cycle_fn=lambda env, **kw: _result(),
        shadow_mode=False,
        boot_grace_s=60.0,  # crash window: the stamp must land BEFORE any cycle
        max_cycles=None,
    )
    _write_stamp_with_mode(stamp_path, shadow=True)
    write_seen_state(
        StallSeenState(fingerprints=frozenset({"Standard:42"})), path=seen_path
    )
    beat.start()
    deadline = time.monotonic() + 5.0
    stamp = None
    while time.monotonic() < deadline:
        raw = json.loads(stamp_path.read_text(encoding="utf-8"))
        if raw.get("mode") == "GRADUATED":
            stamp = raw
            break
        time.sleep(0.01)
    beat.stop()
    assert stamp is not None, "the graduation stamp never landed pre-cycle"
    assert stamp["shadow_mode"] is False  # the edge is closed atomically
    assert read_seen_state(seen_path).fingerprints == frozenset()


def test_proposal_copy_enriched_from_store(tmp_path: Path) -> None:
    """Review 8c18ed43 MINOR-4: the journal copy carries the store proposal's
    full payload (target/goal) so #855 can grade from the journal alone; a
    store fault degrades to the pointer-grade copy."""

    class _StoreStub:
        def get(self, proposal_id):
            return SimpleNamespace(
                payload={"goal": "redispatch it", "target": "C:/projects/widget"},
                status=SimpleNamespace(value="draft"),
            )

    redispatch = RedispatchCycleResult(
        staged=(
            StagedRedispatch(task="fix widget", proposal_id="p-9", fingerprint="fp-9"),
        )
    )
    beat, spy, *_ = _heartbeat(
        tmp_path, cycle_fn=lambda env, **kw: _result(redispatch=redispatch)
    )
    beat._env = SimpleNamespace(store=_StoreStub())  # noqa: SLF001
    _run_to_completion(beat)
    assert spy.copies[0]["payload"]["target"] == "C:/projects/widget"
    assert spy.copies[0]["status"] == "draft"


def test_shadow_to_shadow_keeps_seen_set(tmp_path: Path) -> None:
    beat, _spy, stamp_path, seen_path = _heartbeat(
        tmp_path, cycle_fn=lambda env, **kw: _result(), shadow_mode=True
    )
    _write_stamp_with_mode(stamp_path, shadow=True)
    write_seen_state(
        StallSeenState(fingerprints=frozenset({"Standard:42"})), path=seen_path
    )
    _run_to_completion(beat)
    assert read_seen_state(seen_path).fingerprints == {"Standard:42"}


def test_missing_stamp_never_resets(tmp_path: Path) -> None:
    beat, _spy, _stamp, seen_path = _heartbeat(
        tmp_path, cycle_fn=lambda env, **kw: _result(), shadow_mode=False
    )
    write_seen_state(
        StallSeenState(fingerprints=frozenset({"Standard:42"})), path=seen_path
    )
    _run_to_completion(beat)
    assert read_seen_state(seen_path).fingerprints == {"Standard:42"}


# ---------------------------------------------------------------------------
# The drafting-seam adapter (limb-5 review finding 2 — has_text preserved)
# ---------------------------------------------------------------------------


class _DraftResult(SimpleNamespace):
    pass


def _service_drafting(result: _DraftResult) -> SimpleNamespace:
    return SimpleNamespace(coordinator_draft=lambda prompt, **kw: result)


def test_drafted_with_text_maps_drafted() -> None:
    fn = hb.draft_fn_from_service(
        _service_drafting(_DraftResult(status="drafted", text="prose", reason=""))
    )
    outcome = fn("p")
    assert outcome.status == "drafted" and outcome.text == "prose"


def test_drafted_empty_maps_failed_never_success() -> None:
    """The limb-5 in-band failure: drafted-with-no-text is a DEGRADATION."""
    fn = hb.draft_fn_from_service(
        _service_drafting(_DraftResult(status="drafted", text="", reason="grammar fell over"))
    )
    outcome = fn("p")
    assert outcome.status == "failed"
    assert "grammar fell over" in outcome.reason


def test_enum_statuses_map_through() -> None:
    class _Status:
        value = "busy"

    fn = hb.draft_fn_from_service(
        _service_drafting(_DraftResult(status=_Status(), text="", reason="chat holds it"))
    )
    assert fn("p").status == "busy"


def test_unknown_status_maps_failed() -> None:
    fn = hb.draft_fn_from_service(
        _service_drafting(_DraftResult(status="evicting", text="", reason=""))
    )
    assert fn("p").status == "failed"


def test_service_without_seam_maps_none() -> None:
    assert hb.draft_fn_from_service(object()) is None


# ---------------------------------------------------------------------------
# Import hygiene (#783 pattern) + OFF-path lazy-import lock
# ---------------------------------------------------------------------------

_CHILD_BARE_IMPORT = """
import sys, threading
sys.path.insert(0, {root!r})
before = threading.active_count()
import shared.coordinator.heartbeat as hb
assert threading.active_count() == before, "import started a thread"
for lazy in ("shared.coordinator.heartbeat_cycle",
             "shared.coordinator.output_router",
             "shared.coordinator.shadow_journal"):
    assert lazy not in sys.modules, f"bare import pulled {{lazy}}"
"""

_CHILD_OFF_PATH = _CHILD_BARE_IMPORT + """
class Off:
    coordinator_heartbeat_enabled = False
assert hb.build_heartbeat(Off(), cleanup_started=lambda: False) is None
for lazy in ("shared.coordinator.heartbeat_cycle",
             "shared.coordinator.output_router",
             "shared.coordinator.shadow_journal"):
    assert lazy not in sys.modules, f"OFF factory pulled {{lazy}}"
"""


def _run_child(body: str) -> None:
    proc = subprocess.run(
        [sys.executable, "-c", body.format(root=_REPO_ROOT)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, (
        f"child interpreter failed (rc={proc.returncode}):\n{proc.stderr}"
    )


def test_bare_import_is_side_effect_free() -> None:
    """No module-scope threads, no lazy-machinery import (#783 class)."""
    _run_child(_CHILD_BARE_IMPORT)


def test_off_factory_imports_none_of_the_machinery() -> None:
    """The OFF-boot byte-identical lock's import half: flag false ⇒ the factory
    returns None WITHOUT importing the cycle/router/journal modules."""
    _run_child(_CHILD_OFF_PATH)
