"""Tests for shared.coordinator.drafting — the C3 drafting seam's result
contract (#845 limb 5, design §3.4).

The vocabulary lock matters most: the heartbeat's step-9 handling is written
against EXACTLY the tri-state {drafted, busy, not_resident}, with model-path
failure travelling in-band as an empty ``drafted`` — a fourth status is a
contract change and must fail here first.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from shared.coordinator.drafting import CoordinatorDraftResult, DraftStatus

_REPO_ROOT = Path(__file__).resolve().parents[2]


class TestDraftStatus:
    def test_tri_state_vocabulary_is_exactly_the_design_contract(self) -> None:
        """§3.4: drafted / busy / not_resident — and NOTHING else."""
        assert {m.value for m in DraftStatus} == {
            "drafted",
            "busy",
            "not_resident",
        }
        assert len(list(DraftStatus)) == 3

    def test_deferred_split(self) -> None:
        """busy + not_resident defer (retry a LATER cycle); drafted — even an
        empty fail-softed one — is not a defer."""
        assert DraftStatus.BUSY.deferred
        assert DraftStatus.NOT_RESIDENT.deferred
        assert not DraftStatus.DRAFTED.deferred


class TestCoordinatorDraftResult:
    def test_frozen(self) -> None:
        result = CoordinatorDraftResult(
            status=DraftStatus.DRAFTED, text="a note", reason="drafted"
        )
        with pytest.raises(FrozenInstanceError):
            result.text = "mutated"  # type: ignore[misc]

    def test_has_text_is_the_prose_availability_check(self) -> None:
        """The in-band structured-failure encoding: a DRAFTED result with
        empty/whitespace text means 'attempt ran, no usable prose — render
        the deterministic fallback' (design §2 step 9)."""
        drafted = CoordinatorDraftResult(
            status=DraftStatus.DRAFTED, text="The run finished green.", reason="drafted"
        )
        failed = CoordinatorDraftResult(
            status=DraftStatus.DRAFTED,
            text="",
            reason="generation failed fail-soft: boom — deterministic fallback applies",
        )
        whitespace = CoordinatorDraftResult(
            status=DraftStatus.DRAFTED, text="   \n", reason="empty emission"
        )
        assert drafted.has_text
        assert not failed.has_text
        assert not whitespace.has_text

    def test_defer_results_carry_reason_not_text(self) -> None:
        busy = CoordinatorDraftResult(
            status=DraftStatus.BUSY, text="", reason="inference lock held"
        )
        assert busy.status.deferred
        assert not busy.has_text
        assert busy.reason


class TestImportSafety:
    def test_bare_import_constructs_nothing(self) -> None:
        """Importing the contract module (and the wrapper module carrying the
        seam) must have zero side effects — no output, no threads of THEIR
        making (the C3 bare-import posture, design §3.3).

        The wrapper module is imported FIRST so its pre-existing module-scope
        ``openvino_genai`` try-import (whose runtime may spawn internal
        threads — not this limb's doing) settles before the thread snapshot;
        the drafting module and the wrapper module's own top level must then
        add nothing."""
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import threading, sys; "
                    "import shared.inference.shared_pipeline; "  # ov settles here
                    "before = threading.active_count(); "
                    "import shared.coordinator.drafting; "
                    "sys.exit(0 if threading.active_count() == before else 3)"
                ),
            ],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert proc.returncode == 0, (
            f"bare import failed or spawned threads: rc={proc.returncode} "
            f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        )
        assert proc.stdout == ""
        assert proc.stderr == ""
