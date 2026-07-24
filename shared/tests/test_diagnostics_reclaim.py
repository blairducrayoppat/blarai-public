"""Tests for the #900 memory-reclaim probe (shared.diagnostics) and its wiring
into the GPU-side evict paths (SDXL image-gen, the 14B, the VLM).

The probe answers #900's question — does an eviction actually return system RAM
to Windows on the Arc 140V's unified pool, or does the GPU driver retain it
(openvino #33896)? — by recording the ``In-Use = Total − Available`` delta across
an eviction. These tests are FULLY GPU-FREE: they never load a model. The probe
math is exercised with MOCKED memory snapshots, and the evict paths are driven
through their REAL entry points with a mocked memory source + a fake resident
object, so the instrumentation is proven reachable (not just present).

Two invariants get explicit coverage, mirroring the security-control test rule
(a control ships with a proof it fires when engaged AND a proof it is silent when
disengaged):
  * probe OFF (the shipped default) → the evict paths emit NO reclaim record and
    behave byte-for-byte as before;
  * probe ON → the evict paths emit a structured ``MEM_RECLAIM`` record carrying
    the correct In-Use delta.
"""

from __future__ import annotations

import json
import logging
import threading

import pytest

import shared.diagnostics as diag


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_probe(monkeypatch: pytest.MonkeyPatch):
    """Every test starts with the probe env unset + override cleared, and leaves
    it that way — a leaked ``enabled`` override would make unrelated gate tests
    start emitting reclaim records."""
    monkeypatch.delenv(diag.RECLAIM_PROBE_ENV, raising=False)
    diag.set_reclaim_probe_enabled(None)
    yield
    diag.set_reclaim_probe_enabled(None)


def _snap(total: float, avail: float, *, pct: float = 0.0, rss: float = 0.0) -> dict:
    """Build a memory snapshot dict in the shape ``memory_snapshot`` returns."""
    return {
        "sys_total_mb": total,
        "sys_available_mb": avail,
        "sys_used_pct": pct,
        "proc_rss_mb": rss,
    }


# Representative 14B eviction: ~9.7 GB returns to Windows (avail 5.0 GB → 14.7 GB).
_BEFORE = _snap(31323.0, 5000.0, pct=84.0, rss=12000.0)
_AFTER = _snap(31323.0, 14700.0, pct=53.0, rss=3000.0)
_RECLAIMED = 9700.0  # in_use_before(26323) − in_use_after(16623)


class ScriptedSnapshot:
    """A ``memory_snapshot`` stand-in returning scripted values in call order.

    Clamps at the last entry so an unexpected extra call cannot IndexError. Counts
    calls so a test can assert the OFF path never snapshots."""

    def __init__(self, snaps: list[dict]) -> None:
        self._snaps = snaps
        self.calls = 0

    def __call__(self) -> dict:
        snap = self._snaps[min(self.calls, len(self._snaps) - 1)]
        self.calls += 1
        return dict(snap)


# ---------------------------------------------------------------------------
# in_use_mb — the load-bearing Total − Available math
# ---------------------------------------------------------------------------


class TestInUseMb:
    def test_computes_total_minus_available(self) -> None:
        assert diag.in_use_mb(_snap(31323.0, 5000.0)) == pytest.approx(26323.0)

    def test_empty_snapshot_is_none(self) -> None:
        assert diag.in_use_mb({}) is None

    def test_missing_key_is_none(self) -> None:
        assert diag.in_use_mb({"sys_total_mb": 100.0}) is None

    def test_never_uses_working_set(self) -> None:
        """In-Use must be system-wide (Total − Available), independent of RSS — a
        working-set sum would miss the GPU allocation entirely on the unified pool."""
        low_rss = diag.in_use_mb(_snap(31323.0, 5000.0, rss=10.0))
        high_rss = diag.in_use_mb(_snap(31323.0, 5000.0, rss=30000.0))
        assert low_rss == high_rss == pytest.approx(26323.0)


# ---------------------------------------------------------------------------
# build_reclaim_sample — the delta, ungated
# ---------------------------------------------------------------------------


class TestBuildReclaimSample:
    def test_positive_reclaim_when_available_rises(self) -> None:
        s = diag.build_reclaim_sample("op", _BEFORE, _AFTER)
        assert s is not None
        assert s.in_use_before_mb == pytest.approx(26323.0)
        assert s.in_use_after_mb == pytest.approx(16623.0)
        assert s.reclaimed_mb == pytest.approx(_RECLAIMED)

    def test_zero_reclaim_when_driver_retains(self) -> None:
        """Available unchanged across the evict ⇒ the driver held the memory
        (the #33896 failure signature): reclaimed ≈ 0."""
        s = diag.build_reclaim_sample("op", _BEFORE, _snap(31323.0, 5000.0))
        assert s is not None
        assert s.reclaimed_mb == pytest.approx(0.0)

    def test_negative_reclaim_when_available_drops(self) -> None:
        s = diag.build_reclaim_sample("op", _BEFORE, _snap(31323.0, 4000.0))
        assert s is not None
        assert s.reclaimed_mb == pytest.approx(-1000.0)

    def test_none_when_before_empty(self) -> None:
        assert diag.build_reclaim_sample("op", {}, _AFTER) is None

    def test_none_when_after_empty(self) -> None:
        assert diag.build_reclaim_sample("op", _BEFORE, {}) is None

    def test_extra_metadata_passed_through(self) -> None:
        s = diag.build_reclaim_sample("op", _BEFORE, _AFTER, model="sdxl", variant="photoreal")
        assert s is not None
        assert s.extra == {"model": "sdxl", "variant": "photoreal"}


class TestToRecord:
    def test_json_serialisable_with_expected_keys(self) -> None:
        s = diag.build_reclaim_sample("image_gen.sdxl.unload", _BEFORE, _AFTER, model="sdxl")
        assert s is not None
        rec = s.to_record()
        # Round-trips through JSON (it is destined for the community dataset).
        assert json.loads(json.dumps(rec)) == rec
        assert rec["op"] == "image_gen.sdxl.unload"
        assert rec["reclaimed_mb"] == pytest.approx(_RECLAIMED)
        assert rec["in_use_before_mb"] == pytest.approx(26323.0)
        assert rec["extra"] == {"model": "sdxl"}

    def test_empty_extra_omitted(self) -> None:
        s = diag.build_reclaim_sample("op", _BEFORE, _AFTER)
        assert s is not None
        assert "extra" not in s.to_record()


# ---------------------------------------------------------------------------
# Gating — enabled/disabled resolution
# ---------------------------------------------------------------------------


class TestGate:
    def test_default_off(self) -> None:
        assert diag.reclaim_probe_enabled() is False

    def test_env_truthy_variants_enable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for val in ("1", "true", "TRUE", "on", "yes"):
            monkeypatch.setenv(diag.RECLAIM_PROBE_ENV, val)
            assert diag.reclaim_probe_enabled() is True, val

    def test_env_falsey_variants_stay_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for val in ("0", "false", "off", "no", ""):
            monkeypatch.setenv(diag.RECLAIM_PROBE_ENV, val)
            assert diag.reclaim_probe_enabled() is False, val

    def test_override_wins_over_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(diag.RECLAIM_PROBE_ENV, "1")
        diag.set_reclaim_probe_enabled(False)
        assert diag.reclaim_probe_enabled() is False
        diag.set_reclaim_probe_enabled(True)
        assert diag.reclaim_probe_enabled() is True
        diag.set_reclaim_probe_enabled(None)  # defer back to env
        assert diag.reclaim_probe_enabled() is True


# ---------------------------------------------------------------------------
# record_reclaim — gated emission from existing snapshots
# ---------------------------------------------------------------------------


class TestRecordReclaim:
    def test_off_is_noop(self, caplog: pytest.LogCaptureFixture) -> None:
        sink: list = []
        with caplog.at_level(logging.INFO):
            assert diag.record_reclaim("op", _BEFORE, _AFTER, sink=sink.append) is None
        assert sink == []
        assert "MEM_RECLAIM" not in caplog.text

    def test_on_emits_logs_and_sink(self, caplog: pytest.LogCaptureFixture) -> None:
        diag.set_reclaim_probe_enabled(True)
        sink: list = []
        log = logging.getLogger("test.reclaim")
        with caplog.at_level(logging.INFO):
            sample = diag.record_reclaim(
                "shared_pipeline.14b.unload", _BEFORE, _AFTER, log=log, sink=sink.append
            )
        assert sample is not None
        assert sample.reclaimed_mb == pytest.approx(_RECLAIMED)
        assert len(sink) == 1 and sink[0] is sample
        assert "MEM_RECLAIM op=shared_pipeline.14b.unload" in caplog.text
        assert "reclaimed=+9700MB" in caplog.text

    def test_on_but_empty_snapshot_is_none(self) -> None:
        diag.set_reclaim_probe_enabled(True)
        assert diag.record_reclaim("op", {}, _AFTER) is None

    def test_failsoft_when_sink_raises(self, caplog: pytest.LogCaptureFixture) -> None:
        """A raising sink must never propagate — instrumentation cannot break an
        eviction."""
        diag.set_reclaim_probe_enabled(True)

        def boom(_s) -> None:
            raise RuntimeError("sink blew up")

        with caplog.at_level(logging.INFO):
            # Must not raise.
            assert diag.record_reclaim("op", _BEFORE, _AFTER, sink=boom) is None


# ---------------------------------------------------------------------------
# reclaim_probe context manager — gated bracket for gc-based evictions
# ---------------------------------------------------------------------------


class TestReclaimProbeCM:
    def test_off_runs_body_once_and_never_snapshots(self) -> None:
        snap = ScriptedSnapshot([_BEFORE, _AFTER])
        ran: list[int] = []
        with diag.reclaim_probe("op", snapshot_fn=snap):
            ran.append(1)
        assert ran == [1]
        assert snap.calls == 0  # OFF ⇒ zero snapshot cost

    def test_on_snapshots_and_records(self, caplog: pytest.LogCaptureFixture) -> None:
        diag.set_reclaim_probe_enabled(True)
        snap = ScriptedSnapshot([_BEFORE, _AFTER])
        sink: list = []
        ran: list[int] = []
        with caplog.at_level(logging.INFO):
            with diag.reclaim_probe(
                "substrate.embed_cache.unload", snapshot_fn=snap, sink=sink.append, vectors=42
            ):
                ran.append(1)
        assert ran == [1]
        assert snap.calls == 2  # before + after
        assert len(sink) == 1
        assert sink[0].reclaimed_mb == pytest.approx(_RECLAIMED)
        assert sink[0].extra == {"vectors": 42}

    def test_on_body_runs_even_if_snapshot_raises(self) -> None:
        diag.set_reclaim_probe_enabled(True)

        def boom() -> dict:
            raise RuntimeError("counter read failed")

        ran: list[int] = []
        # Must not raise; body runs exactly once despite both snapshots failing.
        with diag.reclaim_probe("op", snapshot_fn=boom):
            ran.append(1)
        assert ran == [1]

    def test_late_binding_of_default_snapshot_fn(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """With no snapshot_fn, the CM resolves diag.memory_snapshot at CALL time,
        so a monkeypatch of the module global is honoured (the default arg does not
        capture the original)."""
        diag.set_reclaim_probe_enabled(True)
        snap = ScriptedSnapshot([_BEFORE, _AFTER])
        monkeypatch.setattr(diag, "memory_snapshot", snap)
        sink: list = []
        with caplog.at_level(logging.INFO):
            with diag.reclaim_probe("op", sink=sink.append):
                pass
        assert snap.calls == 2
        assert sink and sink[0].reclaimed_mb == pytest.approx(_RECLAIMED)


# ---------------------------------------------------------------------------
# Wiring: the real GPU-side evict entry points call the probe (GPU-free)
# ---------------------------------------------------------------------------


class TestImageGenUnloadWiring:
    """Drive the REAL image_gen.unload() with a fake resident pipe + a mocked
    memory source — no diffusion model is ever loaded."""

    def test_off_emits_nothing_but_still_evicts(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        import shared.inference.image_gen as ig

        monkeypatch.setattr(diag, "memory_snapshot", ScriptedSnapshot([_BEFORE, _AFTER]))
        ig._pipe = object()  # fake resident diffusion pipe
        ig._load_failed = False
        with caplog.at_level(logging.INFO):
            ig.unload()
        assert ig._pipe is None  # eviction happened
        assert "MEM_RECLAIM" not in caplog.text

    def test_on_emits_reclaim_record(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        import shared.inference.image_gen as ig

        diag.set_reclaim_probe_enabled(True)
        monkeypatch.setattr(diag, "memory_snapshot", ScriptedSnapshot([_BEFORE, _AFTER]))
        ig._pipe = object()
        ig._load_failed = False
        with caplog.at_level(logging.INFO):
            ig.unload()
        assert ig._pipe is None
        assert "MEM_RECLAIM op=image_gen.sdxl.unload" in caplog.text
        assert "reclaimed=+9700MB" in caplog.text

    def test_noop_unload_emits_no_record(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An already-clear unload (nothing resident) must not emit a bogus
        zero-delta record even when the probe is armed."""
        import shared.inference.image_gen as ig

        diag.set_reclaim_probe_enabled(True)
        monkeypatch.setattr(diag, "memory_snapshot", ScriptedSnapshot([_BEFORE, _AFTER]))
        ig._pipe = None
        ig._load_failed = False
        with caplog.at_level(logging.INFO):
            ig.unload()
        assert "MEM_RECLAIM" not in caplog.text


class TestVlmUnloadWiring:
    def test_on_emits_reclaim_record(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        import shared.inference.vlm as vlm

        diag.set_reclaim_probe_enabled(True)
        monkeypatch.setattr(diag, "memory_snapshot", ScriptedSnapshot([_BEFORE, _AFTER]))
        vlm._pipe = object()
        vlm._load_failed = False
        with caplog.at_level(logging.INFO):
            vlm.unload()
        assert vlm._pipe is None
        assert "MEM_RECLAIM op=vlm.unload" in caplog.text
        assert "reclaimed=+9700MB" in caplog.text

    def test_off_still_evicts_silently(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        import shared.inference.vlm as vlm

        monkeypatch.setattr(diag, "memory_snapshot", ScriptedSnapshot([_BEFORE, _AFTER]))
        vlm._pipe = object()
        vlm._load_failed = False
        with caplog.at_level(logging.INFO):
            vlm.unload()
        assert vlm._pipe is None
        assert "MEM_RECLAIM" not in caplog.text


class TestSharedPipeline14bWiring:
    """Construct a SharedInferencePipeline directly with a fake pipeline + rebuild
    closure (no LLMPipeline / GPU) and drive its two evict methods."""

    @staticmethod
    def _make():
        from shared.inference.shared_pipeline import SharedInferencePipeline

        return SharedInferencePipeline(
            pipeline=object(), lock=threading.Lock(), rebuild=lambda: object()
        )

    def test_unload_on_emits_reclaim_record(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        diag.set_reclaim_probe_enabled(True)
        monkeypatch.setattr(diag, "memory_snapshot", ScriptedSnapshot([_BEFORE, _AFTER]))
        wrapper = self._make()
        with caplog.at_level(logging.INFO):
            wrapper.unload()
        assert wrapper.is_loaded is False
        assert "MEM_RECLAIM op=shared_pipeline.14b.unload" in caplog.text
        assert "reclaimed=+9700MB" in caplog.text

    def test_unload_off_is_byte_identical(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        snap = ScriptedSnapshot([_BEFORE, _AFTER])
        monkeypatch.setattr(diag, "memory_snapshot", snap)
        wrapper = self._make()
        with caplog.at_level(logging.INFO):
            wrapper.unload()
        assert wrapper.is_loaded is False
        assert "MEM_RECLAIM" not in caplog.text
        assert snap.calls == 0  # off ⇒ no snapshot taken

    def test_unload_refused_without_rebuild_emits_nothing(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """No rebuild closure ⇒ unload() refuses (keeps the 14B) and records
        nothing — the probe must not fire on a refused eviction."""
        from shared.inference.shared_pipeline import SharedInferencePipeline

        diag.set_reclaim_probe_enabled(True)
        monkeypatch.setattr(diag, "memory_snapshot", ScriptedSnapshot([_BEFORE, _AFTER]))
        wrapper = SharedInferencePipeline(
            pipeline=object(), lock=threading.Lock(), rebuild=None
        )
        with caplog.at_level(logging.INFO):
            wrapper.unload()
        assert wrapper.is_loaded is True  # refused — still resident
        assert "MEM_RECLAIM" not in caplog.text

    def test_release_gpu_for_exit_on_emits_record(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        diag.set_reclaim_probe_enabled(True)
        monkeypatch.setattr(diag, "memory_snapshot", ScriptedSnapshot([_BEFORE, _AFTER]))
        wrapper = self._make()
        with caplog.at_level(logging.INFO):
            released = wrapper.release_gpu_for_exit()
        assert released is True
        assert wrapper.is_loaded is False
        assert "MEM_RECLAIM op=shared_pipeline.14b.release_gpu_for_exit" in caplog.text
        assert "reclaimed=+9700MB" in caplog.text

    def test_release_gpu_for_exit_off_is_silent(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        snap = ScriptedSnapshot([_BEFORE, _AFTER])
        monkeypatch.setattr(diag, "memory_snapshot", snap)
        wrapper = self._make()
        with caplog.at_level(logging.INFO):
            assert wrapper.release_gpu_for_exit() is True
        assert "MEM_RECLAIM" not in caplog.text
        assert snap.calls == 0
