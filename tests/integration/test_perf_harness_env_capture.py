"""Gate: both perf harnesses stamp box state into their result JSON (#816 Part 2).

WHY THIS GATE EXISTS — the 2026-07-10 unnoticed-VM incident.
------------------------------------------------------------
The sealed BlarAI-Orchestrator guest ran through an evening of #769
measurements and nothing in the evidence recorded it — the addendum had to be
human-reconstructed.  The fix is self-capture: every perf-result JSON stamps
the box state (ALL Hyper-V VMs, AO :5001, OVMS :8000 + process, available
RAM) at run START via ``shared.perf_env_capture.capture_box_state``, under
the result's ``"environment"`` key.

This gate is a STATIC AST lock (precedent:
``test_winui_passthrough_allowlist.py`` — a source-level conformance check
over a surface the type system cannot bind).  The harnesses' JSON writers
live inside ``main()`` and only execute on real GPU hardware, so the wiring
cannot be exercised here; instead the lock parses each harness source and
fails loudly — naming the file — if the wiring is removed or renamed:

  (a) the harness imports ``capture_box_state`` from
      ``shared.perf_env_capture``;
  (b) exactly one ``box_state_at_start = capture_box_state()`` assignment
      exists (the run-START stamp);
  (c) the dict-literal keys ``"environment"``, ``"box_state_at_start"`` and
      ``"box_state_at_end"`` are all present (the JSON embedding);
  (d) the start stamp precedes every other capture call in source order (the
      end stamp cannot masquerade as the start stamp).

Import-level execution of the harnesses is deliberately avoided: importing
them pulls openvino/openvino_genai into the gate for no verification gain.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# This file lives at <repo_root>/tests/integration/<this>.py, so parents[2] is
# the repo root regardless of where the checkout / worktree is on disk.
_REPO_ROOT = Path(__file__).resolve().parents[2]

_HELPER_MODULE = "shared.perf_env_capture"
_HELPER_FUNC = "capture_box_state"
_START_NAME = "box_state_at_start"
_REQUIRED_DICT_KEYS = {"environment", "box_state_at_start", "box_state_at_end"}

#: Every perf harness whose result JSON must self-capture its environment.
#: A NEW harness that writes docs/performance/ evidence should be added here
#: in the same change that creates it.
_HARNESSES: tuple[str, ...] = (
    "scripts/benchmark_vlm_text_inference.py",
    "scripts/benchmark_spec_decode_ab.py",
)


def _tree(rel: str) -> ast.Module:
    path = _REPO_ROOT / rel
    assert path.exists(), f"harness {rel} not found — update _HARNESSES if it moved"
    return ast.parse(path.read_text(encoding="utf-8"), filename=rel)


def _capture_calls(tree: ast.Module) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == _HELPER_FUNC
    ]


@pytest.mark.parametrize("rel", _HARNESSES)
def test_harness_imports_the_shared_capture_helper(rel: str) -> None:
    tree = _tree(rel)
    imported = any(
        isinstance(node, ast.ImportFrom)
        and node.module == _HELPER_MODULE
        and any(alias.name == _HELPER_FUNC for alias in node.names)
        for node in ast.walk(tree)
    )
    assert imported, (
        f"{rel} no longer imports {_HELPER_FUNC} from {_HELPER_MODULE} — its "
        "result JSON would stop self-capturing the box state, which is how the "
        "2026-07-10 unnoticed-VM incident happened. Restore the import (and the "
        "start/end stamps) or update this gate deliberately."
    )


@pytest.mark.parametrize("rel", _HARNESSES)
def test_harness_stamps_box_state_at_run_start(rel: str) -> None:
    tree = _tree(rel)
    start_assigns = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == _START_NAME
            for target in node.targets
        )
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == _HELPER_FUNC
    ]
    assert len(start_assigns) == 1, (
        f"{rel} must contain exactly one '{_START_NAME} = {_HELPER_FUNC}(...)' "
        f"assignment (found {len(start_assigns)}) — the run-START stamp is the "
        "evidence anchor; without it a resident VM/model silently vanishes from "
        "the record."
    )


@pytest.mark.parametrize("rel", _HARNESSES)
def test_harness_embeds_environment_with_start_and_end_stamps(rel: str) -> None:
    tree = _tree(rel)
    dict_keys = {
        key.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Dict)
        for key in node.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }
    missing = _REQUIRED_DICT_KEYS - dict_keys
    assert not missing, (
        f"{rel} result-JSON assembly is missing dict key(s) {sorted(missing)} — "
        "the capture must land under 'environment' as 'box_state_at_start' + "
        "'box_state_at_end' (the shape downstream evidence scrapers key on)."
    )


@pytest.mark.parametrize("rel", _HARNESSES)
def test_harness_start_stamp_precedes_every_other_capture(rel: str) -> None:
    tree = _tree(rel)
    calls = _capture_calls(tree)
    assert len(calls) >= 2, (
        f"{rel} calls {_HELPER_FUNC} {len(calls)} time(s) — expected the start "
        "stamp AND the completion stamp (>= 2 calls)."
    )
    start_line = min(call.lineno for call in calls)
    start_assign_lines = [
        node.value.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == _START_NAME
            for target in node.targets
        )
        and isinstance(node.value, ast.Call)
    ]
    assert start_assign_lines and start_assign_lines[0] == start_line, (
        f"{rel}: the FIRST {_HELPER_FUNC} call (line {start_line}) is not the "
        f"'{_START_NAME}' assignment — the run-start stamp must be taken before "
        "any other capture (the end stamp records drift, not the anchor)."
    )
