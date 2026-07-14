"""
Shared LLMPipeline Tests
==========================
Phase 4 of the model-sharing refactor (ADR-012 Amendment 3): unit tests
for the threading-lock-serialised wrapper + the boot-time builder.

Test groups:
  A. SharedInferencePipeline wrapper (4 tests) — serialisation, forwarding,
     raw access, call counting.
  B. build_shared_pipeline error paths (6 tests) — OV-GenAI unavailable,
     missing files, integrity failures.

The happy-path "construct an actual ov_genai.LLMPipeline" case is
deliberately left to live verification on the operator's hardware — it
requires the real OpenVINO runtime + GPU + model weights and is the
journal-mandated screen-test, not a unit-test concern.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from shared.inference.shared_pipeline import (
    SharedInferencePipeline,
    SharedPipelineBuildResult,
    build_shared_pipeline,
)


# ---------------------------------------------------------------------------
# Group A — SharedInferencePipeline wrapper
# ---------------------------------------------------------------------------


class TestSharedInferencePipeline:
    """Wrapper-only tests using a fake pipeline; no OV GenAI required."""

    def test_generate_forwards_args_and_return(self) -> None:
        """.generate() must forward args/kwargs and return the underlying value."""
        fake = MagicMock()
        fake.generate.return_value = "RESULT"
        wrapper = SharedInferencePipeline(fake, threading.Lock())

        out = wrapper.generate("hello", config={"k": 1})

        assert out == "RESULT"
        fake.generate.assert_called_once_with("hello", config={"k": 1})

    def test_raw_exposes_underlying_pipeline(self) -> None:
        """.raw returns the wrapped object for boot-time / unload-time access."""
        fake = object()
        wrapper = SharedInferencePipeline(fake, threading.Lock())
        assert wrapper.raw is fake

    def test_generate_call_count_increments(self) -> None:
        """Per-call counter increments under the lock."""
        fake = MagicMock()
        fake.generate.return_value = None
        wrapper = SharedInferencePipeline(fake, threading.Lock())

        assert wrapper.generate_call_count == 0
        wrapper.generate("a")
        wrapper.generate("b")
        wrapper.generate("c")
        assert wrapper.generate_call_count == 3

    def test_lock_serialises_concurrent_callers(self) -> None:
        """Two threads calling .generate() must NOT overlap inside the lock.

        Uses a fake pipeline that sleeps inside generate so any overlap is
        observable as wall-clock overlap of the recorded intervals.
        """
        intervals: list[tuple[float, float]] = []
        intervals_lock = threading.Lock()

        def slow_generate(*_args: object, **_kwargs: object) -> str:
            start = time.perf_counter()
            time.sleep(0.05)
            end = time.perf_counter()
            with intervals_lock:
                intervals.append((start, end))
            return "ok"

        fake = MagicMock()
        fake.generate.side_effect = slow_generate
        wrapper = SharedInferencePipeline(fake, threading.Lock())

        threads = [
            threading.Thread(target=wrapper.generate, args=("p",))
            for _ in range(2)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(intervals) == 2
        a, b = sorted(intervals, key=lambda iv: iv[0])
        # b must START after a ENDS — the canonical "no overlap" assertion.
        assert b[0] >= a[1], (
            f"lock did not serialise: a=({a[0]:.4f}, {a[1]:.4f}) "
            f"b=({b[0]:.4f}, {b[1]:.4f})"
        )


class TestSharedInferencePipelineUnloadReload:
    """Eviction + lazy reload (UC-010 #666): the shared 14B is evicted to free
    RAM for the diffusion hires pass and lazily reloaded on the next generate()."""

    def test_unload_then_generate_reloads(self) -> None:
        """After unload(), the next generate() rebuilds via the closure and runs
        on the FRESH pipeline — transparent to PA/AO callers."""
        fresh = MagicMock()
        fresh.generate.return_value = "AFTER"
        stale = MagicMock()
        stale.generate.return_value = "BEFORE"
        rebuilds: list[int] = []

        def rebuild() -> MagicMock:
            rebuilds.append(1)
            return fresh

        wrapper = SharedInferencePipeline(stale, threading.Lock(), rebuild=rebuild)
        assert wrapper.generate("p") == "BEFORE"
        assert wrapper.is_loaded
        wrapper.unload()
        assert not wrapper.is_loaded
        assert wrapper.generate("p") == "AFTER"  # reloaded, runs on fresh
        assert wrapper.is_loaded
        assert len(rebuilds) == 1
        stale.generate.assert_called_once()  # only the pre-unload call

    def test_release_gpu_for_exit_releases_without_rebuild(self) -> None:
        """release_gpu_for_exit() drops the 14B for the PROCESS-EXIT path (#670 run-2) even
        with NO rebuild closure — unlike unload(), which refuses without one (no reload would
        be possible). At a step-aside the process is dying, so no reload is needed; the GPU
        context just has to be released before the 30B loads. Idempotent."""
        fake = MagicMock()
        wrapper = SharedInferencePipeline(fake, threading.Lock())  # NO rebuild closure
        assert wrapper.is_loaded
        wrapper.unload()  # refuses without a rebuild closure -> keeps the 14B
        assert wrapper.is_loaded
        assert wrapper.release_gpu_for_exit() is True  # exit path releases unconditionally
        assert not wrapper.is_loaded
        assert wrapper.release_gpu_for_exit() is False  # idempotent: already released

    def test_unload_is_idempotent(self) -> None:
        wrapper = SharedInferencePipeline(
            MagicMock(), threading.Lock(), rebuild=lambda: MagicMock()
        )
        wrapper.unload()
        wrapper.unload()  # no raise
        assert not wrapper.is_loaded

    def test_unload_refused_without_rebuild_closure(self) -> None:
        """No rebuild closure => unload() refuses (it could not reload) and keeps
        the pipeline, so the service is never wedged (Fail-Closed)."""
        wrapper = SharedInferencePipeline(MagicMock(), threading.Lock())
        wrapper.unload()
        assert wrapper.is_loaded  # refused

    def test_generate_after_unload_without_rebuild_raises(self) -> None:
        """An unloaded pipeline with no rebuild closure raises on generate()
        rather than silently degrading (Fail-Closed)."""
        wrapper = SharedInferencePipeline(MagicMock(), threading.Lock())
        wrapper._pipeline = None  # force the unloaded state
        with pytest.raises(RuntimeError):
            wrapper.generate("p")

    def test_reload_failure_raises(self) -> None:
        """A rebuild closure that returns no pipeline => generate() raises."""
        wrapper = SharedInferencePipeline(
            MagicMock(), threading.Lock(), rebuild=lambda: None
        )
        wrapper.unload()
        with pytest.raises(RuntimeError):
            wrapper.generate("p")

    def test_call_count_survives_reload(self) -> None:
        """generate_call_count keeps counting across an unload/reload cycle."""
        wrapper = SharedInferencePipeline(
            MagicMock(), threading.Lock(), rebuild=lambda: MagicMock()
        )
        wrapper.generate("a")
        wrapper.unload()
        wrapper.generate("b")
        assert wrapper.generate_call_count == 2


# ---------------------------------------------------------------------------
# Group A2 — try_run_exclusive (#845 C3 drafting seam, design §3.3 wall 4/§3.4)
# ---------------------------------------------------------------------------


def _lock_is_free(wrapper: SharedInferencePipeline) -> bool:
    """True iff the wrapper's single-flight lock is currently free."""
    got = wrapper._lock.acquire(blocking=False)
    if got:
        wrapper._lock.release()
    return got


class TestTryRunExclusive:
    """The heartbeat drafting seam's acquire point: non-blocking, residency-
    gated, never-reloading, lock-released-on-every-path."""

    def test_busy_when_lock_held_and_fn_never_called(self) -> None:
        """Lock held by anyone => ('busy', None) immediately; fn untouched
        (the busy-defers lock: zero model calls)."""
        fake = MagicMock()
        wrapper = SharedInferencePipeline(fake, threading.Lock())
        fn = MagicMock()

        assert wrapper._lock.acquire(blocking=False)
        try:
            status, value = wrapper.try_run_exclusive(fn)
        finally:
            wrapper._lock.release()

        assert status == "busy"
        assert value is None
        fn.assert_not_called()
        fake.generate.assert_not_called()

    def test_not_resident_after_real_eviction_and_never_reloads(self) -> None:
        """After the REAL UC-010 eviction path (unload()), the seam reports
        not_resident and — unlike generate() — NEVER consults the rebuild
        closure (the not_resident-defers lock: zero load/reload calls)."""
        rebuild = MagicMock()
        fake = MagicMock()
        wrapper = SharedInferencePipeline(fake, threading.Lock(), rebuild=rebuild)
        wrapper.unload()  # the image-gen eviction bookkeeping: _pipeline -> None
        assert not wrapper.is_loaded
        fn = MagicMock()

        status, value = wrapper.try_run_exclusive(fn)

        assert status == "not_resident"
        assert value is None
        fn.assert_not_called()
        rebuild.assert_not_called()  # the load path is never touched
        assert not wrapper.is_loaded  # still evicted — no load was initiated
        assert _lock_is_free(wrapper)

    def test_ran_passes_raw_pipeline_with_residency_pinned(self) -> None:
        """Resident + free => fn runs exactly once, receives the RAW handle,
        and residency is pinned for the duration (unload serialises on the
        same lock)."""
        fake = MagicMock()
        wrapper = SharedInferencePipeline(fake, threading.Lock())
        seen: list[object] = []

        def fn(raw: object) -> str:
            seen.append(raw)
            assert wrapper.is_loaded  # pinned: cannot be evicted under us
            return "VALUE"

        status, value = wrapper.try_run_exclusive(fn)

        assert status == "ran"
        assert value == "VALUE"
        assert seen == [fake]  # the raw pipeline, not the wrapper
        assert _lock_is_free(wrapper)

    def test_exception_from_fn_propagates_and_releases_lock(self) -> None:
        """fn raising must not leak the lock (the lock-always-released lock)."""
        wrapper = SharedInferencePipeline(MagicMock(), threading.Lock())

        with pytest.raises(RuntimeError, match="boom"):
            wrapper.try_run_exclusive(MagicMock(side_effect=RuntimeError("boom")))

        assert _lock_is_free(wrapper)

    def test_lock_released_on_every_status_path(self) -> None:
        """busy, not_resident and ran all leave the lock free afterwards."""
        # ran
        wrapper = SharedInferencePipeline(MagicMock(), threading.Lock())
        wrapper.try_run_exclusive(lambda raw: None)
        assert _lock_is_free(wrapper)
        # not_resident
        wrapper._pipeline = None
        wrapper.try_run_exclusive(lambda raw: None)
        assert _lock_is_free(wrapper)
        # busy: the holder still holds it afterwards (the seam took nothing)
        assert wrapper._lock.acquire(blocking=False)
        try:
            wrapper.try_run_exclusive(lambda raw: None)
            assert not wrapper._lock.acquire(blocking=False)  # still held by us
        finally:
            wrapper._lock.release()
        assert _lock_is_free(wrapper)

    def test_generate_call_count_not_incremented(self) -> None:
        """try_run_exclusive counts nothing — generate_call_count is the
        wrapper.generate() counter and fn is opaque to the wrapper."""
        wrapper = SharedInferencePipeline(MagicMock(), threading.Lock())
        wrapper.try_run_exclusive(lambda raw: raw.generate("p"))
        assert wrapper.generate_call_count == 0

    def test_status_vocabulary_matches_module_constants(self) -> None:
        """The seam's status strings are the module's exported constants —
        the AO adapter maps them 1:1 onto the coordinator tri-state."""
        from shared.inference.shared_pipeline import (
            TRY_RUN_BUSY,
            TRY_RUN_NOT_RESIDENT,
            TRY_RUN_RAN,
        )

        assert TRY_RUN_BUSY == "busy"
        assert TRY_RUN_NOT_RESIDENT == "not_resident"
        assert TRY_RUN_RAN == "ran"


# ---------------------------------------------------------------------------
# Helpers for build_shared_pipeline error-path tests
# ---------------------------------------------------------------------------


def _make_model_dir(tmp_path: Path, name: str, payload: bytes = b"x") -> Path:
    """Create a minimal model directory with openvino_model.xml + .bin."""
    d = tmp_path / name
    d.mkdir()
    (d / "openvino_model.xml").write_text("<dummy/>", encoding="utf-8")
    (d / "openvino_model.bin").write_bytes(payload)
    return d


def _write_manifest_for(model_bin: Path, manifest_path: Path) -> None:
    """Write a Known-Good Manifest whose digest matches the file at model_bin."""
    digest = hashlib.sha256(model_bin.read_bytes()).hexdigest()
    manifest_path.write_text(
        json.dumps(
            {
                "version": "1.0.0",
                "digests": {model_bin.name: digest},
            }
        ),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Group B — build_shared_pipeline error paths
# ---------------------------------------------------------------------------


class TestBuildSharedPipelineErrors:
    """Fail-Closed verification — every error path must produce !ok and an error."""

    def test_returns_error_when_ov_genai_unavailable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If openvino_genai is not importable, builder fails closed."""
        import shared.inference.shared_pipeline as mod
        monkeypatch.setattr(mod, "_OV_GENAI_AVAILABLE", False)

        result = build_shared_pipeline(
            model_dir=tmp_path / "missing",
            draft_model_dir=tmp_path / "missing-draft",
            enable_prefix_caching=False,
        )
        assert not result.ok
        assert "OpenVINO GenAI" in (result.error or "")

    def test_returns_error_when_target_model_files_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Target model dir without openvino_model.{xml,bin} fails."""
        import shared.inference.shared_pipeline as mod
        monkeypatch.setattr(mod, "_OV_GENAI_AVAILABLE", True)

        empty_target = tmp_path / "empty-target"
        empty_target.mkdir()
        draft = _make_model_dir(tmp_path, "draft")

        result = build_shared_pipeline(
            model_dir=empty_target,
            draft_model_dir=draft,
            enable_prefix_caching=False,
        )
        assert not result.ok
        assert "Target model files missing" in (result.error or "")

    def test_returns_error_when_draft_model_files_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Draft model dir without openvino_model.{xml,bin} fails."""
        import shared.inference.shared_pipeline as mod
        monkeypatch.setattr(mod, "_OV_GENAI_AVAILABLE", True)

        target = _make_model_dir(tmp_path, "target")
        empty_draft = tmp_path / "empty-draft"
        empty_draft.mkdir()

        result = build_shared_pipeline(
            model_dir=target,
            draft_model_dir=empty_draft,
            enable_prefix_caching=False,
        )
        assert not result.ok
        assert "Draft model files missing" in (result.error or "")

    def test_returns_error_when_target_integrity_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A manifest digest mismatch on the target must Fail-Closed."""
        import shared.inference.shared_pipeline as mod
        monkeypatch.setattr(mod, "_OV_GENAI_AVAILABLE", True)

        target = _make_model_dir(tmp_path, "target", payload=b"correct")
        draft = _make_model_dir(tmp_path, "draft", payload=b"draft-data")
        bad_manifest = tmp_path / "target-bad-manifest.json"
        bad_manifest.write_text(
            json.dumps(
                {
                    "version": "1.0.0",
                    "digests": {"openvino_model.bin": "0" * 64},
                }
            ),
            encoding="utf-8",
        )

        result = build_shared_pipeline(
            model_dir=target,
            draft_model_dir=draft,
            enable_prefix_caching=False,
            target_manifest_path=bad_manifest,
        )
        assert not result.ok
        assert result.target_integrity is not None
        assert result.target_integrity.verified is False
        assert "Target weight integrity FAILED" in (result.error or "")

    def test_returns_error_when_draft_integrity_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A manifest digest mismatch on the draft must Fail-Closed."""
        import shared.inference.shared_pipeline as mod
        monkeypatch.setattr(mod, "_OV_GENAI_AVAILABLE", True)

        target = _make_model_dir(tmp_path, "target", payload=b"target-data")
        draft = _make_model_dir(tmp_path, "draft", payload=b"actual-draft")
        good_target_manifest = tmp_path / "target.json"
        _write_manifest_for(target / "openvino_model.bin", good_target_manifest)

        bad_draft_manifest = tmp_path / "draft-bad.json"
        bad_draft_manifest.write_text(
            json.dumps(
                {
                    "version": "1.0.0",
                    "digests": {"openvino_model.bin": "0" * 64},
                }
            ),
            encoding="utf-8",
        )

        result = build_shared_pipeline(
            model_dir=target,
            draft_model_dir=draft,
            enable_prefix_caching=False,
            target_manifest_path=good_target_manifest,
            draft_manifest_path=bad_draft_manifest,
        )
        assert not result.ok
        assert result.target_integrity is not None
        assert result.target_integrity.verified is True
        assert result.draft_integrity is not None
        assert result.draft_integrity.verified is False
        assert "Draft weight integrity FAILED" in (result.error or "")

    def test_build_result_dataclass_is_immutable(
        self, tmp_path: Path
    ) -> None:
        """SharedPipelineBuildResult is a frozen dataclass."""
        r = SharedPipelineBuildResult(
            pipeline=None,
            target_integrity=None,
            draft_integrity=None,
            error="sanity check",
        )
        with pytest.raises(Exception):
            r.error = "mutated"  # type: ignore[misc]
