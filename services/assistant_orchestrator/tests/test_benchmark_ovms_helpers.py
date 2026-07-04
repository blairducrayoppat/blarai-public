"""
OVMS HTTP Benchmark Helper Unit Tests
=====================================
Tests for the pure / parser logic in ``scripts/benchmark_ovms_http.py``:
  - Statistics + throughput (mirrors of the GPU bench, lightly re-covered)
  - aggregate / aggregate_prefill
  - chat_stream: SSE delta + terminal-usage parsing (the novel logic)
  - chat_nonstream: usage extraction (prompt_tokens for pp)
  - measure_prefill: unique-prefix probe -> pp computation
  - served_model_ids: /v3/models id extraction
  - format_markdown_entry: pp row present iff measured

No network, no live OVMS — the HTTP layer (_post_json / urlopen) is faked.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "scripts"
_BENCH_PATH = _SCRIPTS_DIR / "benchmark_ovms_http.py"


def _load_module() -> object:
    spec = importlib.util.spec_from_file_location("benchmark_ovms_http", str(_BENCH_PATH))
    if spec is None or spec.loader is None:
        pytest.skip(f"Cannot locate OVMS benchmark script at {_BENCH_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["benchmark_ovms_http"] = module
    try:
        spec.loader.exec_module(module)  # type: ignore[attr-defined]
    except (ImportError, SystemExit) as exc:  # stdlib-only, so this should not fire
        sys.modules.pop("benchmark_ovms_http", None)
        pytest.skip(f"Skipping — cannot import OVMS benchmark module: {exc}")
    return module


_ovms = _load_module()

compute_mean = getattr(_ovms, "compute_mean")
compute_median = getattr(_ovms, "compute_median")
compute_p95 = getattr(_ovms, "compute_p95")
tokens_per_sec = getattr(_ovms, "tokens_per_sec")
prefill_tokens_per_sec = getattr(_ovms, "prefill_tokens_per_sec")
aggregate = getattr(_ovms, "aggregate")
aggregate_prefill = getattr(_ovms, "aggregate_prefill")
SingleRunMetrics = getattr(_ovms, "SingleRunMetrics")
PrefillRunMetrics = getattr(_ovms, "PrefillRunMetrics")
PrefillStats = getattr(_ovms, "PrefillStats")
format_markdown_entry = getattr(_ovms, "format_markdown_entry")
chat_stream = getattr(_ovms, "chat_stream")
chat_nonstream = getattr(_ovms, "chat_nonstream")
measure_prefill = getattr(_ovms, "measure_prefill")
served_model_ids = getattr(_ovms, "served_model_ids")


# ---------------------------------------------------------------------------
# Fakes for the HTTP layer
# ---------------------------------------------------------------------------


class _FakeStreamResp:
    """Context-manager + iterable yielding SSE byte-lines (like a urlopen response)."""

    def __init__(self, lines: list[bytes]) -> None:
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def __iter__(self):
        return iter(self._lines)


class _FakeReadResp:
    """Context-manager with .read() returning a JSON body (non-streaming response)."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def read(self) -> bytes:
        return self._body


def _sse(obj: dict) -> bytes:
    return ("data: " + json.dumps(obj) + "\n").encode("utf-8")


# ---------------------------------------------------------------------------
# Statistics (mirrors — light)
# ---------------------------------------------------------------------------


def test_mean_median_p95_basic():
    assert compute_mean([2.0, 4.0]) == 3.0
    assert compute_median([1.0, 2.0, 3.0]) == 2.0
    assert compute_p95([float(i) for i in range(1, 101)]) == 95.0


def test_mean_empty_is_zero():
    assert compute_mean([]) == 0.0
    assert compute_median([]) == 0.0
    assert compute_p95([]) == 0.0


def test_tokens_per_sec_and_guard():
    assert tokens_per_sec(100, 1000.0) == 100.0
    assert tokens_per_sec(100, 0.0) == 0.0


def test_prefill_tokens_per_sec_and_guards():
    assert prefill_tokens_per_sec(900, 100.0) == pytest.approx(9000.0)
    assert prefill_tokens_per_sec(900, 0.0) == 0.0
    assert prefill_tokens_per_sec(0, 100.0) == 0.0
    assert prefill_tokens_per_sec(-5, 100.0) == 0.0


# ---------------------------------------------------------------------------
# aggregate / aggregate_prefill
# ---------------------------------------------------------------------------


def test_aggregate_excludes_errors_and_unmeasured_ttft():
    runs = [
        SingleRunMetrics(0, 50, 200.0, 5000.0, 10.0, None),
        SingleRunMetrics(1, 60, -1.0, 6000.0, 10.0, None),  # TTFT unmeasured
        SingleRunMetrics(2, 0, 0.0, 0.0, 0.0, "boom"),       # error excluded
    ]
    agg = aggregate(runs)
    assert agg.total_runs == 3
    assert agg.error_runs == 1
    assert agg.mean_tps == pytest.approx(10.0)
    # only the one run with a real TTFT contributes
    assert agg.mean_ttft_ms == pytest.approx(200.0)


def test_aggregate_prefill_all_errors_unmeasured():
    runs = [PrefillRunMetrics(-1, 0.0, 0.0, "no usage")]
    p = aggregate_prefill(runs)
    assert p.measured is False
    assert p.error_runs == 1


def test_aggregate_prefill_measured():
    runs = [PrefillRunMetrics(900, 100.0, 9000.0, None),
            PrefillRunMetrics(900, 200.0, 4500.0, None)]
    p = aggregate_prefill(runs)
    assert p.measured is True
    assert p.mean_input_tokens == pytest.approx(900.0)
    assert p.mean_pp == pytest.approx(6750.0)


# ---------------------------------------------------------------------------
# chat_stream — SSE parsing (the novel logic)
# ---------------------------------------------------------------------------


def test_chat_stream_uses_terminal_usage(monkeypatch):
    lines = [
        _sse({"choices": [{"delta": {"content": "Hello"}}]}),
        _sse({"choices": [{"delta": {"content": " world"}}]}),
        _sse({"choices": [{"delta": {"content": "!"}}]}),
        _sse({"choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 3}}),
        b"data: [DONE]\n",
    ]
    monkeypatch.setattr(_ovms, "_post_json", lambda url, body, timeout: _FakeStreamResp(lines))
    out = chat_stream("http://x/v3/chat/completions", "coder-30b", "hi", 256, 5.0)
    assert out["error"] is None
    assert out["completion_tokens"] == 3       # from usage, not the chunk count
    assert out["prompt_tokens"] == 12
    assert out["usage_present"] is True
    assert out["ttft_ms"] >= 0.0
    assert out["total_ms"] >= out["ttft_ms"]


def test_chat_stream_falls_back_to_chunk_count_when_no_usage(monkeypatch):
    lines = [
        _sse({"choices": [{"delta": {"content": "a"}}]}),
        _sse({"choices": [{"delta": {"content": "b"}}]}),
        b"data: [DONE]\n",
    ]
    monkeypatch.setattr(_ovms, "_post_json", lambda url, body, timeout: _FakeStreamResp(lines))
    out = chat_stream("http://x", "coder-30b", "hi", 256, 5.0)
    assert out["error"] is None
    assert out["completion_tokens"] == 2       # fallback: counted content deltas
    assert out["prompt_tokens"] is None
    assert out["usage_present"] is False


def test_chat_stream_ignores_non_data_and_keepalive_lines(monkeypatch):
    lines = [
        b": ping\n",                                            # SSE comment / keepalive
        b"\n",                                                  # blank
        _sse({"choices": [{"delta": {"role": "assistant"}}]}),  # role-only, no content
        _sse({"choices": [{"delta": {"content": "X"}}]}),
        b"data: [DONE]\n",
    ]
    monkeypatch.setattr(_ovms, "_post_json", lambda url, body, timeout: _FakeStreamResp(lines))
    out = chat_stream("http://x", "coder-30b", "hi", 256, 5.0)
    assert out["completion_tokens"] == 1
    assert out["ttft_ms"] >= 0.0


def test_chat_stream_http_error_is_caught(monkeypatch):
    def _boom(url, body, timeout):
        raise OSError("connection refused")

    monkeypatch.setattr(_ovms, "_post_json", _boom)
    out = chat_stream("http://x", "coder-30b", "hi", 256, 5.0)
    assert out.get("error")


# ---------------------------------------------------------------------------
# chat_nonstream — usage extraction (pp source)
# ---------------------------------------------------------------------------


def test_chat_nonstream_extracts_prompt_tokens(monkeypatch):
    body = json.dumps({
        "choices": [{"message": {"content": "."}}],
        "usage": {"prompt_tokens": 970, "completion_tokens": 1},
    }).encode("utf-8")
    monkeypatch.setattr(_ovms, "_post_json", lambda url, b, timeout: _FakeReadResp(body))
    out = chat_nonstream("http://x", "coder-30b", "probe", 1, 5.0)
    assert out["error"] is None
    assert out["prompt_tokens"] == 970
    assert out["total_ms"] >= 0.0


# ---------------------------------------------------------------------------
# measure_prefill — unique prefix + pp computation
# ---------------------------------------------------------------------------


def test_measure_prefill_computes_pp(monkeypatch):
    monkeypatch.setattr(
        _ovms, "chat_nonstream",
        lambda endpoint, model, prompt, max_tokens, timeout: {
            "total_ms": 100.0, "prompt_tokens": 900, "completion_tokens": 1, "error": None},
    )
    runs = measure_prefill("http://x", "coder-30b", num_runs=3, timeout=5.0, run_cooldown=0)
    assert len(runs) == 3
    assert all(r.error is None and r.input_tokens == 900 for r in runs)
    assert runs[0].prefill_tok_per_sec == pytest.approx(9000.0)
    p = aggregate_prefill(runs)
    assert p.measured and p.mean_pp == pytest.approx(9000.0)


def test_measure_prefill_marks_unmeasured_without_usage(monkeypatch):
    monkeypatch.setattr(
        _ovms, "chat_nonstream",
        lambda endpoint, model, prompt, max_tokens, timeout: {
            "total_ms": 100.0, "prompt_tokens": None, "completion_tokens": 1, "error": None},
    )
    runs = measure_prefill("http://x", "coder-30b", num_runs=2, timeout=5.0, run_cooldown=0)
    assert all(r.error is not None for r in runs)
    assert aggregate_prefill(runs).measured is False


# ---------------------------------------------------------------------------
# served_model_ids
# ---------------------------------------------------------------------------


def test_served_model_ids_parses_data(monkeypatch):
    body = json.dumps({"data": [{"id": "coder-30b"}, {"id": "other"}]}).encode("utf-8")
    monkeypatch.setattr(_ovms.urllib.request, "urlopen",
                        lambda req, timeout=5.0: _FakeReadResp(body))
    assert served_model_ids("http://127.0.0.1:8000/v3/models") == ["coder-30b", "other"]


def test_served_model_ids_empty_on_error(monkeypatch):
    def _boom(req, timeout=5.0):
        raise OSError("refused")

    monkeypatch.setattr(_ovms.urllib.request, "urlopen", _boom)
    assert served_model_ids("http://127.0.0.1:8000/v3/models") == []


# ---------------------------------------------------------------------------
# format_markdown_entry
# ---------------------------------------------------------------------------


def _stats(mean_tps=37.0):
    return aggregate([SingleRunMetrics(0, 100, 150.0, 2700.0, mean_tps, None)])


def test_markdown_includes_pp_row_when_measured():
    pstats = PrefillStats(mean_pp=820.0, median_pp=820.0, p95_pp=820.0,
                          mean_input_tokens=970.0, total_runs=5, error_runs=0, measured=True)
    md = format_markdown_entry("2026-06-28T01:02:03", {"model_name": "Qwen3-Coder-30B-A3B"},
                               _stats(), pstats, 5, 2)
    assert "Prefill pp (tok/s)" in md
    assert "820.0" in md
    assert "llama-bench pp512" in md


def test_markdown_omits_pp_row_when_unmeasured():
    pstats = PrefillStats(0.0, 0.0, 0.0, 0.0, 0, 0, measured=False)
    md = format_markdown_entry("2026-06-28T01:02:03", {"model_name": "Qwen3-Coder-30B-A3B"},
                               _stats(), pstats, 5, 2)
    assert "Prefill pp (tok/s)" not in md
    assert "Throughput (tok/s)" in md
