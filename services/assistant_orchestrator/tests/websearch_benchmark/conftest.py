"""Local pytest configuration for the web-search quality benchmark (W3).

Registers the `slow` and `hardware` markers used by the real-14B benchmark
test (`test_quality_benchmark_real_14b`).

Why this is needed
------------------
The repo-root ``pyproject.toml`` registers these markers and deselects `slow`
by default (``addopts = "... -m 'not slow'"``), so the normal full-suite run
(``pytest shared/ services/ launcher/``, rooted at the repo) is fine. But a
*scoped* run rooted at the Assistant-Orchestrator package
(``pytest services/assistant_orchestrator/...``) uses the AO ``pyproject.toml``,
which enables ``--strict-markers`` *without* registering any markers — so
collection would fail with ``'slow' not found in markers configuration``.

Registering them here (loaded for any run that collects this directory) keeps a
scoped AO run green. This does NOT weaken the GPU-safety guarantee: the real-14B
test is independently protected by a ``BLARAI_RUN_HARDWARE`` ``skipif`` guard in
its own body, so it never loads the model in a default run regardless of which
config registers or deselects the markers.
"""

from __future__ import annotations

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Register the benchmark's markers so ``--strict-markers`` accepts them.

    Idempotent with the repo-root registration: ``addinivalue_line`` simply
    appends, and duplicate marker definitions are harmless under pytest.
    """
    config.addinivalue_line(
        "markers",
        "slow: real-hardware or long-running tests; deselected by default at the repo root.",
    )
    config.addinivalue_line(
        "markers",
        "hardware: requires real OpenVINO models on the GPU/CPU; deselected by default.",
    )
