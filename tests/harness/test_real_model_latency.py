"""Layer B — real-model latency on the GPU host (Vikunja #563).

Marked ``slow`` + ``hardware``: deselected by default, run with
``pytest -m hardware tests/harness``. These load the REAL OpenVINO models, so
they only pass on the runtime machine (Arc 140V) with the weights on disk;
elsewhere each scenario reports ``available: False`` and the test SKIPS.

They do NOT write artifacts — recording community-grade perf data is the CLI's
job (``python -m tests.harness``). Here we assert the real runtime loads and
runs within generous sanity bounds, so an agent can confirm the runtime is
functional and not catastrophically slow without a human boot — the
"reproduce the issue without the User-Operator" capability.
"""

from __future__ import annotations

import pytest

from tests.harness import scenarios

pytestmark = [pytest.mark.slow, pytest.mark.hardware]


def test_semantic_router_loads_and_classifies() -> None:
    result = scenarios.semantic_router_latency()
    if not result["available"]:
        pytest.skip(result["reason"])
    assert result["classify"]["count"] >= 1
    # bge-small on CPU classifies in well under a second per query.
    assert result["classify"]["p95_ms"] < 2000


def test_vlm_describe_image() -> None:
    result = scenarios.vlm_describe_latency()
    if not result["available"]:
        pytest.skip(result["reason"])
    assert result["description_chars"] > 0
    # Lazy load (~13 s) + inference; generous ceiling guards against a hang.
    assert result["load_plus_describe_ms"] < 180_000


def test_ao_chat_generates() -> None:
    result = scenarios.ao_chat_latency()
    if not result["available"]:
        pytest.skip(result["reason"])
    assert result["reply_chars"] > 0
    # Generous ceiling: cold 14B load + a short generation.
    assert result["wall_clock_generate_ms"] < 180_000
