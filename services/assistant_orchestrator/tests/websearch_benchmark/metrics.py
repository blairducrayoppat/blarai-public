"""
Web-Search Quality Benchmark — Metrics (W3).

Two measurement axes (ADR-024 §2.6):

1. Answer correctness:
   - answer_contains_all(answer, expected): all expected strings present (binary).
   - citation_domain_coverage(citations, expected_domains): fraction of expected
     domains that appear in the actual citations.
   - spurious_citation_rate(citations, expected_domains): citations to domains
     NOT in expected set / total citations.

2. Loop efficiency:
   - pass_count (state.pass_count)
   - search_calls (total Kagi search() calls that would have been made)
   - learning_extraction_calls (Step 4b LLM calls)

BenchmarkResult aggregates per-question results and computes means.

perf_contrib integration:
  build_perf_contrib_record() emits a perf_contrib-compatible record
  (dict matching tools/perf_contrib/schema.py's ValidationResult schema).
  Mock runs emit measurements zeroed with is_mock=True in notes.
  The not_measured field explicitly names what mock runs do NOT cover.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Per-question result
# ---------------------------------------------------------------------------


@dataclass
class QuestionResult:
    """Outcome for a single benchmark question.

    Attributes:
        question_id:               Corpus item id (e.g. "wsb-001").
        answer_contains_all:       True if all expected_answer_contains strings
                                   appear in the final_answer (case-insensitive).
        citation_domain_coverage:  Fraction of expected_citation_domains present
                                   in the actual citations.  0.0 when no domains
                                   are expected.
        spurious_citation_rate:    Citations to domains NOT in expected set,
                                   divided by total citations.  0.0 when no
                                   citations present.
        pass_count:                Number of search passes completed.
        search_calls:              Total adapter.search() calls made.
        learning_extraction_calls: Total Step 4b LLM calls made.
        final_answer:              The synthesised answer string.
    """

    question_id: str
    answer_contains_all: bool
    citation_domain_coverage: float
    spurious_citation_rate: float
    pass_count: int
    search_calls: int
    learning_extraction_calls: int
    final_answer: str = ""


@dataclass
class BenchmarkResult:
    """Aggregated results across all corpus questions.

    Attributes:
        per_question:             List of per-question results in corpus order.
        pass_count:               Total questions evaluated (all categories).
        answer_correctness_mean:  Mean of answer_contains_all (0..1).
        citation_domain_coverage_mean: Mean citation domain coverage (0..1).
        spurious_citation_rate_mean:   Mean spurious citation rate (0..1).
        mean_pass_count:          Mean search passes per question.
        mean_search_calls:        Mean Kagi search calls per question.
        mean_learning_extraction_calls: Mean Step 4b LLM calls per question.
    """

    per_question: list[QuestionResult] = field(default_factory=list)

    @property
    def pass_count(self) -> int:
        return len(self.per_question)

    @property
    def answer_correctness_mean(self) -> float:
        if not self.per_question:
            return 0.0
        return sum(1.0 if r.answer_contains_all else 0.0 for r in self.per_question) / len(self.per_question)

    @property
    def citation_domain_coverage_mean(self) -> float:
        if not self.per_question:
            return 0.0
        return sum(r.citation_domain_coverage for r in self.per_question) / len(self.per_question)

    @property
    def spurious_citation_rate_mean(self) -> float:
        if not self.per_question:
            return 0.0
        return sum(r.spurious_citation_rate for r in self.per_question) / len(self.per_question)

    @property
    def mean_pass_count(self) -> float:
        if not self.per_question:
            return 0.0
        return sum(r.pass_count for r in self.per_question) / len(self.per_question)

    @property
    def mean_search_calls(self) -> float:
        if not self.per_question:
            return 0.0
        return sum(r.search_calls for r in self.per_question) / len(self.per_question)

    @property
    def mean_learning_extraction_calls(self) -> float:
        if not self.per_question:
            return 0.0
        return sum(r.learning_extraction_calls for r in self.per_question) / len(self.per_question)


# ---------------------------------------------------------------------------
# Metric functions
# ---------------------------------------------------------------------------


def answer_contains_all(
    final_answer: str,
    expected: list[str],
) -> bool:
    """Return True if all expected strings appear in final_answer.

    Case-insensitive comparison. Empty expected list returns True (no
    expected strings to check — used for adversarial corpus items).

    Args:
        final_answer: The synthesised answer from SearchState.final_answer.
        expected:     List of strings that must appear in the answer.

    Returns:
        True if all strings are present (or expected is empty).
    """
    if not expected:
        return True
    lower_answer = final_answer.lower()
    return all(e.lower() in lower_answer for e in expected)


def _extract_domain(url: str) -> str:
    """Extract the registered domain (host without www.) from a URL.

    Args:
        url: A URL string.

    Returns:
        The domain string (lower-case, without leading www.).
        Empty string if no domain can be extracted.
    """
    m = re.match(r"https?://(?:www\.)?([^/?\#]+)", url.lower())
    if m:
        return m.group(1)
    return ""


def citation_domain_coverage(
    citation_urls: list[str],
    expected_domains: list[str],
) -> float:
    """Fraction of expected_domains present in the actual citation_urls.

    Args:
        citation_urls:    List of URLs from Citation.url in the final state.
        expected_domains: Expected domain strings (e.g. ["github.com"]).

    Returns:
        Float in [0.0, 1.0]. 1.0 if expected_domains is empty (vacuously
        true — adversarial items have no expected domains).
    """
    if not expected_domains:
        return 1.0
    actual_domains = {_extract_domain(u) for u in citation_urls if u}
    matched = sum(1 for d in expected_domains if d.lower() in actual_domains)
    return matched / len(expected_domains)


def spurious_citation_rate(
    citation_urls: list[str],
    expected_domains: list[str],
) -> float:
    """Fraction of actual citations to domains NOT in expected_domains.

    Args:
        citation_urls:    List of URLs from Citation objects.
        expected_domains: Expected domain strings.

    Returns:
        Float in [0.0, 1.0]. 0.0 if no citations present (nothing to be
        spurious). 0.0 if expected_domains is empty (adversarial items
        have no expected domains — any citation is fine).
    """
    if not citation_urls:
        return 0.0
    if not expected_domains:
        return 0.0
    lower_expected = {d.lower() for d in expected_domains}
    spurious = sum(
        1 for u in citation_urls
        if u and _extract_domain(u) not in lower_expected
    )
    return spurious / len(citation_urls)


def score_question(
    corpus_item: dict[str, Any],
    final_answer: str,
    citation_urls: list[str],
    pass_count: int,
    search_calls: int,
    learning_extraction_calls: int,
) -> QuestionResult:
    """Compute all metrics for one corpus item.

    Args:
        corpus_item:              Raw dict from corpus.jsonl.
        final_answer:             SearchState.final_answer.
        citation_urls:            [c.url for c in SearchState.citations].
        pass_count:               SearchState.pass_count.
        search_calls:             Total adapter.search() calls for this question.
        learning_extraction_calls: Total Step 4b LLM calls for this question.

    Returns:
        A QuestionResult.
    """
    expected_answer_contains: list[str] = corpus_item.get("expected_answer_contains") or []
    expected_citation_domains: list[str] = corpus_item.get("expected_citation_domains") or []

    return QuestionResult(
        question_id=corpus_item["id"],
        answer_contains_all=answer_contains_all(final_answer, expected_answer_contains),
        citation_domain_coverage=citation_domain_coverage(citation_urls, expected_citation_domains),
        spurious_citation_rate=spurious_citation_rate(citation_urls, expected_citation_domains),
        pass_count=pass_count,
        search_calls=search_calls,
        learning_extraction_calls=learning_extraction_calls,
        final_answer=final_answer,
    )


# ---------------------------------------------------------------------------
# perf_contrib record builder
# ---------------------------------------------------------------------------


# Not-measured items that apply to ALL mock-tier benchmark runs.
# A real 14B hardware run has additional not_measured items
# (real-model answer quality, GPU cost) listed in the hardware test.
_MOCK_NOT_MEASURED: list[str] = [
    "real-model answer quality (mock LLM returns scripted canned text; no 14B inference)",
    "co-resident GPU cost during inference (mock; no GPU loaded)",
    "actual Kagi API latency (MockKagiAdapter; zero network calls)",
    "actual OpenVINO GenAI pipeline overhead (no OV runtime loaded)",
    "cold-vs-warm GPU KV-cache difference",
    "multi-user concurrency effects",
]


def build_perf_contrib_record(
    result: BenchmarkResult,
    is_mock: bool = True,
    openvino_version: str = "unavailable",
    notes: str = "",
) -> dict[str, Any]:
    """Build a perf_contrib-compatible record dict for a benchmark run.

    The record matches the schema validated by
    tools/perf_contrib/schema.validate().

    For mock runs (is_mock=True, the default):
      - measurements are real loop counts but model-quality metrics are 0.0
        (mock LLM returns scripted text, not real answers).
      - not_measured explicitly lists what the mock does NOT cover.

    For hardware runs (is_mock=False):
      - measurements carry real numbers.
      - not_measured is still required (lists remaining uncovered items).

    Args:
        result:           Completed BenchmarkResult.
        is_mock:          True for mock-tier runs (default).
        openvino_version: OpenVINO version string for hardware runs.
        notes:            Optional additional notes.

    Returns:
        A dict ready to pass to tools.perf_contrib.schema.validate().
    """
    timestamp = datetime.now(tz=timezone.utc).isoformat()

    not_measured: list[str] = list(_MOCK_NOT_MEASURED)
    if not is_mock:
        # Real hardware run — GPU cost is measurable but we still don't
        # measure everything.
        not_measured = [
            "co-resident application GPU cost during inference",
            "cold-vs-warm GPU KV-cache difference (all runs warm)",
            "multi-user concurrency effects",
            "cross-session memory leak accumulation",
        ]

    record: dict[str, Any] = {
        "name": "websearch_quality_benchmark",
        "timestamp": timestamp,
        "model": "MockLLM" if is_mock else "Qwen3-14B",
        "precision": "mock" if is_mock else "INT4",
        "methodology": (
            f"20-question corpus (corpus.jsonl); "
            f"adapter={'MockKagiAdapter' if is_mock else 'LiveKagiAdapter'}; "
            f"llm={'MockLLM' if is_mock else 'OrchestratorGPUInference'}; "
            "max_passes=2; summarizer=false; "
            "categories: factual-current(8), factual-stable(4), multi-hop(4), adversarial(4). "
            "Metrics: answer_contains_all, citation_domain_coverage, spurious_citation_rate, "
            "mean_pass_count, mean_search_calls."
        ),
        "environment": {
            "cpu": "Intel Core Ultra 7 258V (Lunar Lake)" if not is_mock else "mock-environment",
            "gpu": "Intel Arc 140V (Xe2)" if not is_mock else "none (mock run)",
            "openvino_version": openvino_version,
            "not_measured": not_measured,
        },
        "measurements": {
            "answer_correctness_mean": result.answer_correctness_mean if not is_mock else 0.0,
            "citation_domain_coverage_mean": result.citation_domain_coverage_mean if not is_mock else 0.0,
            "spurious_citation_rate_mean": result.spurious_citation_rate_mean if not is_mock else 0.0,
            "mean_pass_count": result.mean_pass_count,
            "mean_search_calls": result.mean_search_calls,
            "mean_learning_extraction_calls": result.mean_learning_extraction_calls,
            "questions_evaluated": float(result.pass_count),
        },
        "notes": notes or (
            "Mock-tier run: scripted LLM and adapter. "
            "No real model or network calls. "
            "Measurement values for model-quality metrics are 0.0 by construction."
            if is_mock
            else ""
        ),
    }
    return record
