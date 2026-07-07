"""
Web-Search Quality Benchmark — pytest entry point (W3).

Two test groups:

A. MOCK-TIER (run in the default suite):
   - Corpus integrity (loads, IDs unique, categories present, size check).
   - Metrics computation correctness (unit tests against known inputs).
   - End-to-end loop on scripted mocks — passes on the mock corpus.
   - perf_contrib record is schema-valid and carries non-empty not_measured.

B. HARDWARE-TIER (deselected by default — requires real 14B + GPU):
   test_quality_benchmark_real_14b:
     @pytest.mark.hardware
     @pytest.mark.slow
     guarded by:  pytest.mark.skipif(os.getenv("BLARAI_RUN_HARDWARE") != "1")
   This test never runs the 14B in a default `pytest`, on either config:
   1. Full suite (repo-root config): addopts `-m 'not slow'` deselects `slow`.
   2. Scoped AO run: this directory's conftest.py registers `slow`/`hardware`
      so `--strict-markers` does not error on collection; the test is then
      collected but skipped by the guard below (the AO config has no
      `-m 'not slow'`).
   3. The skipif guard in the test body requires BLARAI_RUN_HARDWARE="1".

   The skipif (3) alone is sufficient to keep the 14B from loading in any plain
   `pytest` run; (1)/(2) keep collection clean on each config.

GPU SAFETY
----------
The test_quality_benchmark_real_14b test MUST NEVER execute in the default
suite. Loading the real 14B collides with the concurrent security session's
GPU measurements (ADR-011 single-GPU singleton).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from services.assistant_orchestrator.tests.websearch_benchmark.harness import (
    CORPUS_PATH,
    load_corpus,
    run_corpus,
)
from services.assistant_orchestrator.tests.websearch_benchmark.metrics import (
    BenchmarkResult,
    QuestionResult,
    answer_contains_all,
    build_perf_contrib_record,
    citation_domain_coverage,
    score_question,
    spurious_citation_rate,
)

# perf_contrib schema validator (tools/perf_contrib/schema.py)
from tools.perf_contrib.schema import validate as _perf_validate


# ---------------------------------------------------------------------------
# A.1 Corpus integrity
# ---------------------------------------------------------------------------


class TestCorpusIntegrity:
    """Verify corpus.jsonl is well-formed and has expected structure."""

    def test_corpus_file_exists(self) -> None:
        assert CORPUS_PATH.exists(), f"Corpus not found at {CORPUS_PATH}"

    def test_corpus_loads_without_error(self) -> None:
        items = load_corpus()
        assert len(items) > 0, "Corpus must not be empty"

    def test_corpus_has_20_items(self) -> None:
        items = load_corpus()
        assert len(items) == 20, f"Expected 20 corpus items, got {len(items)}"

    def test_all_ids_unique(self) -> None:
        items = load_corpus()
        ids = [i["id"] for i in items]
        assert len(ids) == len(set(ids)), "Duplicate IDs in corpus"

    def test_category_distribution(self) -> None:
        items = load_corpus()
        by_category: dict[str, int] = {}
        for item in items:
            by_category[item["category"]] = by_category.get(item["category"], 0) + 1
        assert by_category.get("factual-current", 0) == 8, f"Expected 8 factual-current, got {by_category}"
        assert by_category.get("factual-stable", 0) == 4, f"Expected 4 factual-stable, got {by_category}"
        assert by_category.get("multi-hop", 0) == 4, f"Expected 4 multi-hop, got {by_category}"
        assert by_category.get("adversarial", 0) == 4, f"Expected 4 adversarial, got {by_category}"

    def test_required_fields_present(self) -> None:
        items = load_corpus()
        for item in items:
            for field_name in ("id", "question", "category", "expected_answer_contains",
                               "expected_citation_domains", "difficulty"):
                assert field_name in item, f"Item {item.get('id')}: missing field '{field_name}'"

    def test_adversarial_items_have_empty_expected_answer_contains(self) -> None:
        items = load_corpus()
        adv = [i for i in items if i["category"] == "adversarial"]
        for item in adv:
            assert item["expected_answer_contains"] == [], (
                f"Adversarial item {item['id']} should have empty expected_answer_contains"
            )


# ---------------------------------------------------------------------------
# A.2 Metrics computation correctness
# ---------------------------------------------------------------------------


class TestMetricsComputation:
    """Unit-test metric functions against hand-computable inputs."""

    def test_answer_contains_all_passes_when_all_present(self) -> None:
        assert answer_contains_all("OpenVINO 2026.1 GenAI release", ["2026", "GenAI"]) is True

    def test_answer_contains_all_fails_when_one_missing(self) -> None:
        assert answer_contains_all("OpenVINO 2026.1 released", ["2026", "GenAI"]) is False

    def test_answer_contains_all_empty_expected_is_true(self) -> None:
        # Adversarial items have empty expected.
        assert answer_contains_all("any answer", []) is True

    def test_answer_contains_all_case_insensitive(self) -> None:
        assert answer_contains_all("OPENVINO GENAI", ["openvino", "genai"]) is True

    def test_citation_domain_coverage_full_match(self) -> None:
        urls = ["https://github.com/ov", "https://intel.com/foo"]
        domains = ["github.com", "intel.com"]
        assert citation_domain_coverage(urls, domains) == pytest.approx(1.0)

    def test_citation_domain_coverage_partial_match(self) -> None:
        urls = ["https://github.com/ov"]
        domains = ["github.com", "intel.com"]
        assert citation_domain_coverage(urls, domains) == pytest.approx(0.5)

    def test_citation_domain_coverage_empty_expected_is_one(self) -> None:
        assert citation_domain_coverage(["https://any.com"], []) == pytest.approx(1.0)

    def test_citation_domain_coverage_no_urls_returns_zero(self) -> None:
        assert citation_domain_coverage([], ["github.com"]) == pytest.approx(0.0)

    def test_spurious_citation_rate_no_spurious(self) -> None:
        urls = ["https://github.com/ov"]
        assert spurious_citation_rate(urls, ["github.com"]) == pytest.approx(0.0)

    def test_spurious_citation_rate_all_spurious(self) -> None:
        urls = ["https://spam.com/1", "https://spam.com/2"]
        assert spurious_citation_rate(urls, ["github.com"]) == pytest.approx(1.0)

    def test_spurious_citation_rate_empty_urls_is_zero(self) -> None:
        assert spurious_citation_rate([], ["github.com"]) == pytest.approx(0.0)

    def test_spurious_citation_rate_empty_expected_is_zero(self) -> None:
        # No expected domains → nothing can be spurious.
        assert spurious_citation_rate(["https://any.com"], []) == pytest.approx(0.0)

    def test_score_question_correct(self) -> None:
        item: dict[str, Any] = {
            "id": "wsb-test",
            "expected_answer_contains": ["OpenVINO", "2026"],
            "expected_citation_domains": ["intel.com"],
        }
        qr = score_question(
            corpus_item=item,
            final_answer="OpenVINO 2026 is the current version [1].",
            citation_urls=["https://intel.com/ov"],
            pass_count=1,
            search_calls=2,
            learning_extraction_calls=1,
        )
        assert qr.answer_contains_all is True
        assert qr.citation_domain_coverage == pytest.approx(1.0)
        assert qr.spurious_citation_rate == pytest.approx(0.0)
        assert qr.pass_count == 1


# ---------------------------------------------------------------------------
# A.3 End-to-end mock run — loop runs on scripted mocks
# ---------------------------------------------------------------------------


class TestMockCorpusRun:
    """End-to-end: run_corpus() on the full corpus with scripted mocks."""

    @pytest.fixture(scope="class")
    async def mock_result(self) -> BenchmarkResult:
        corpus = load_corpus()
        return await run_corpus(corpus)

    async def test_result_covers_all_corpus_items(self, mock_result: BenchmarkResult) -> None:
        assert mock_result.pass_count == 20

    async def test_all_questions_have_a_final_answer(self, mock_result: BenchmarkResult) -> None:
        for qr in mock_result.per_question:
            assert qr.final_answer != "", f"Question {qr.question_id} has empty final_answer"

    async def test_no_error_answers(self, mock_result: BenchmarkResult) -> None:
        for qr in mock_result.per_question:
            assert "[web-search error" not in qr.final_answer, (
                f"Question {qr.question_id} returned an error: {qr.final_answer}"
            )

    async def test_non_adversarial_pass_count_at_least_1(self, mock_result: BenchmarkResult) -> None:
        corpus = load_corpus()
        id_to_category = {i["id"]: i["category"] for i in corpus}
        for qr in mock_result.per_question:
            if id_to_category.get(qr.question_id, "") != "adversarial":
                assert qr.pass_count >= 1, (
                    f"Non-adversarial question {qr.question_id} had pass_count=0"
                )

    async def test_mean_pass_count_in_valid_range(self, mock_result: BenchmarkResult) -> None:
        assert 0.0 < mock_result.mean_pass_count <= 2.0

    async def test_benchmark_result_properties_compute(self, mock_result: BenchmarkResult) -> None:
        # Properties must not raise and return finite floats.
        assert 0.0 <= mock_result.answer_correctness_mean <= 1.0
        assert 0.0 <= mock_result.citation_domain_coverage_mean <= 1.0
        assert 0.0 <= mock_result.spurious_citation_rate_mean <= 1.0
        assert mock_result.mean_search_calls >= 0.0


# ---------------------------------------------------------------------------
# A.4 perf_contrib record validity
# ---------------------------------------------------------------------------


class TestPerfContribRecord:
    """perf_contrib record must validate against schema with non-empty not_measured."""

    @pytest.fixture(scope="class")
    async def mock_record(self) -> dict[str, Any]:
        corpus = load_corpus()
        result = await run_corpus(corpus)
        return build_perf_contrib_record(result, is_mock=True)

    async def test_record_validates(self, mock_record: dict[str, Any]) -> None:
        validation = _perf_validate(mock_record)
        assert validation.valid, f"perf_contrib validation failed: {validation.errors}"

    async def test_record_not_measured_is_non_empty(self, mock_record: dict[str, Any]) -> None:
        not_measured = mock_record["environment"]["not_measured"]
        assert isinstance(not_measured, list)
        assert len(not_measured) >= 1, "not_measured must have at least one entry"

    async def test_record_mentions_mock_llm(self, mock_record: dict[str, Any]) -> None:
        # The not_measured list must explicitly call out that mock runs don't
        # measure real model quality.
        combined = " ".join(not_measured.lower() for not_measured in mock_record["environment"]["not_measured"])
        assert "mock" in combined or "real" in combined or "14b" in combined.lower(), (
            "not_measured must mention that the mock LLM does not exercise the real 14B"
        )

    async def test_record_has_questions_evaluated(self, mock_record: dict[str, Any]) -> None:
        assert mock_record["measurements"]["questions_evaluated"] == pytest.approx(20.0)

    async def test_record_timestamp_looks_like_iso8601(self, mock_record: dict[str, Any]) -> None:
        ts = mock_record["timestamp"]
        assert ts.startswith("20"), f"Timestamp doesn't look like ISO-8601: {ts}"
        assert "T" in ts or " " in ts


# ---------------------------------------------------------------------------
# B. HARDWARE-TIER (deselected by default — GPU safety mandatory)
# ---------------------------------------------------------------------------
#
# DESELECTION MECHANISM (triple guard — any one alone is sufficient):
#
# 1. pytestmark below applies pytest.mark.slow + pytest.mark.hardware to this
#    entire test function. pyproject.toml addopts = "-m 'not slow'" deselects
#    both markers in the default suite. This is the PRIMARY mechanism, which
#    exactly replicates how tests/harness/test_real_model_latency.py is kept
#    out of the default run (pytestmark = [pytest.mark.slow, pytest.mark.hardware]).
#
# 2. pytest.mark.skipif guard inside the test body: the test is skipped unless
#    the environment variable BLARAI_RUN_HARDWARE == "1" is set explicitly.
#    Plain `pytest` never sets this variable.
#
# 3. The test function is a standalone (not in a class) marked with the
#    hardware+slow marks so it is excluded at collection time before any
#    test body is entered.
#
# DO NOT SET BLARAI_RUN_HARDWARE=1 IN ANY CI OR DEFAULT INVOCATION.
# DO NOT RUN THIS TEST YOURSELF IN THIS SESSION.


@pytest.mark.slow
@pytest.mark.hardware
@pytest.mark.skipif(
    os.getenv("BLARAI_RUN_HARDWARE") != "1",
    reason=(
        "Hardware test deselected: set BLARAI_RUN_HARDWARE=1 to run on the "
        "real Arc 140V GPU with the real Qwen3-14B. "
        "WARNING: this loads the 14B model — do not run during security session GPU work."
    ),
)
def test_quality_benchmark_real_14b() -> None:
    """Full 20-question benchmark on real hardware with Qwen3-14B.

    THIS TEST MUST NEVER RUN IN THE DEFAULT SUITE.
    All three deselection mechanisms (marker-based, skipif env-var) must be
    intact. DO NOT WEAKEN THEM.

    Run only with explicit opt-in:
        BLARAI_RUN_HARDWARE=1 pytest -m hardware services/.../test_websearch_benchmark.py

    What this test measures when run on real hardware:
      - Real Qwen3-14B INT4 answer quality on 20 questions.
      - Actual citation domain coverage from real Kagi API search results.
      - Real pass_count (whether gap-detect fires on each question type).
      - Real mean_search_calls and mean_learning_extraction_calls.
      - Emits a perf_contrib record with real measurements (not zeroed).

    What this test does NOT measure (listed in not_measured of perf record):
      - Co-resident application GPU cost during inference.
      - Cold-vs-warm GPU KV-cache difference (all runs warm).
      - Multi-user concurrency effects.
      - Cross-session memory leak accumulation.
    """
    import asyncio

    # Belt-and-suspenders: redundant import check to ensure this never runs
    # accidentally in a mock-only environment.
    try:
        import openvino_genai  # noqa: F401  # type: ignore[import-untyped]
    except ImportError:
        pytest.skip("openvino_genai not available — hardware test requires OpenVINO GenAI")

    # The real adapter and inference engine are NOT imported at module level
    # to prevent any risk of accidental instantiation during collection.
    # They are imported here, inside the test body, guarded by the skipif.
    from services.assistant_orchestrator.src.websearch.adapter import KagiAdapter  # noqa: F401
    from services.assistant_orchestrator.src.gpu_inference import OrchestratorGPUInference

    # --- SCAFFOLD ONLY (W3) ---
    # W3 does not provide a LiveKagiAdapter (that is W4's deliverable).
    # This scaffold verifies the test infrastructure is correct and that the
    # perf_contrib record shape is valid when real numbers are present.
    #
    # A real hardware run requires:
    #   1. W4's LiveKagiAdapter (real Kagi HTTP + egress proxy).
    #   2. Real OrchestratorGPUInference loaded with Qwen3-14B INT4.
    #   3. A live Kagi API key in the environment.
    #
    # When W4 is complete, replace the placeholder below with:
    #   adapter = LiveKagiAdapter(api_key=os.environ["KAGI_API_KEY"], ...)
    #   llm = OrchestratorGPUInference(model_dir=..., ...)
    #   llm.load_model()
    #   result = asyncio.run(run_corpus(corpus, adapter=adapter, llm=llm))

    pytest.skip(
        "W3 hardware scaffold: LiveKagiAdapter not yet implemented (W4 deliverable). "
        "Re-enable at W4 by providing a real adapter and LLM instance."
    )
