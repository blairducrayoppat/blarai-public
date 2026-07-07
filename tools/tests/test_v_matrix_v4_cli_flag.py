"""V matrix V4 -- CLI flag exposure parametrized per refactored entrypoint.

Asserts every refactored Python entrypoint that uses ``argparse`` exposes the
two project-context flags introduced by the Stage 2 platform-separation
refactor:

    --project-root    (path to the project root; falls back to discovery)
    --project-id      (Vikunja project_id; sanity-checked vs registry)

Coverage is via ``--help`` introspection over a subprocess invocation so the
test exercises the actual installed entrypoint surface and catches any future
regression where a maintainer drops one of the flags from the parser.

Stage 2.7.v2 V matrix V4 (closure V4 vs V matrix V4: closure V4 is the
host-state vikunja-process check; V matrix V4 is THIS test -- see Guide-#6
namespace clarification at item 2.7 close).
"""
from __future__ import annotations

import subprocess
import sys

import pytest


# Refactored entrypoints with --project-root / --project-id flags
# (per EA-3+EA-4 platform-separation refactor; empirically discovered via
#  grep_search "--project-root" across tools/**/*.py).
REFACTORED_ENTRYPOINTS = [
    "tools.fleet_observability.daily_digest",
    "tools.fleet_observability.welcome_back_digest",
    "tools.fleet_observability.credential_rotation_reminder",
    "tools.fleet_observability.weekly_summary",
    "tools.fleet_observability.dashboard_maintainer",
    "tools.gate_stale_cleaner.run_live",
]


@pytest.mark.parametrize("module", REFACTORED_ENTRYPOINTS)
def test_entrypoint_exposes_project_root_flag(module: str) -> None:
    """``--help`` output for each refactored entrypoint MUST mention --project-root."""
    result = subprocess.run(
        [sys.executable, "-m", module, "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"{module} --help exited non-zero: rc={result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    combined = result.stdout + result.stderr
    assert "--project-root" in combined, (
        f"{module} --help did not expose --project-root flag.\n"
        f"output: {combined!r}"
    )


@pytest.mark.parametrize("module", REFACTORED_ENTRYPOINTS)
def test_entrypoint_exposes_project_id_flag(module: str) -> None:
    """``--help`` output for each refactored entrypoint MUST mention --project-id."""
    result = subprocess.run(
        [sys.executable, "-m", module, "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"{module} --help exited non-zero: rc={result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    combined = result.stdout + result.stderr
    assert "--project-id" in combined, (
        f"{module} --help did not expose --project-id flag.\n"
        f"output: {combined!r}"
    )
