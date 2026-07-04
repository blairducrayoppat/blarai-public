"""
Web-Search Quality Benchmark — Harness (W3).

Corpus loading, MockKagiAdapter + MockLLM construction for deterministic
benchmark runs, and the run_corpus() orchestrator.

All benchmark runs are network-free and model-free (MockKagiAdapter returns
pre-scripted fixtures; MockLLM returns canned answers).  A hardware-gated
variant (test_websearch_benchmark.py) calls the same run_corpus() with a
real adapter and real LLM.

Design mirrors tests/pa_quality_benchmark/harness.py.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from services.assistant_orchestrator.src.websearch.adapter import MockKagiAdapter
from services.assistant_orchestrator.src.websearch.types import SearchResult, SummaryResult
from services.assistant_orchestrator.src.websearch.state import WebSearchConfig
from services.assistant_orchestrator.src.websearch.loop import run_web_search
from services.assistant_orchestrator.tests.websearch_benchmark.metrics import (
    BenchmarkResult,
    QuestionResult,
    score_question,
)

CORPUS_PATH: Path = Path(__file__).parent / "corpus.jsonl"


# ---------------------------------------------------------------------------
# Corpus loading
# ---------------------------------------------------------------------------


def load_corpus(path: Path = CORPUS_PATH) -> list[dict[str, Any]]:
    """Load the labeled corpus from corpus.jsonl.

    Args:
        path: Path to the corpus.jsonl file.

    Returns:
        List of corpus item dicts with id/question/category/
        expected_answer_contains/expected_citation_domains/difficulty.

    Raises:
        FileNotFoundError: If the corpus file does not exist.
        ValueError: If a line is malformed or missing required fields.
    """
    items: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Corpus line {lineno}: invalid JSON — {exc}") from exc

            for required in ("id", "question", "category"):
                if required not in item:
                    raise ValueError(
                        f"Corpus line {lineno}: missing required field '{required}'"
                    )
            items.append(item)
    return items


# ---------------------------------------------------------------------------
# Mock fixtures — scripted to the corpus for deterministic runs
# ---------------------------------------------------------------------------


def _build_scripted_fixtures(
    corpus: list[dict[str, Any]],
) -> tuple[dict[str, list[SearchResult]], dict[str, SummaryResult]]:
    """Build MockKagiAdapter fixtures scripted to the corpus questions.

    Each question gets at least one search result pointing to a mock URL.
    The mock URL summary carries the expected_answer_contains strings so
    the loop's learning-extraction and synthesis steps can produce a
    "passing" answer in mock mode.

    Args:
        corpus: List of corpus item dicts.

    Returns:
        A (search_fixture, summary_fixture) tuple for MockKagiAdapter.
    """
    search_fixture: dict[str, list[SearchResult]] = {}
    summary_fixture: dict[str, SummaryResult] = {}

    for item in corpus:
        qid = item["id"]
        question = item["question"]
        expected_contains: list[str] = item.get("expected_answer_contains") or []
        expected_domains: list[str] = item.get("expected_citation_domains") or []

        # Build a mock URL using the first expected domain (if any).
        domain = expected_domains[0] if expected_domains else "mock-source.example.com"
        mock_url = f"https://{domain}/{qid}"

        # The search fixture maps the raw question (used as the first query
        # by the scripted MockLLM decomposition response) to one result.
        search_fixture[question] = [
            SearchResult(
                url=mock_url,
                title=f"Mock source for {qid}",
                snippet=f"Information about: {question[:80]}",
                rank=1,
            )
        ]
        # Add generic sub-query forms to catch the scripted decomposition output.
        search_fixture[f"{question} overview"] = search_fixture[question]
        search_fixture[f"{question} details"] = search_fixture[question]

        # Build summary text that contains all expected_answer_contains strings
        # so the metrics pass on mock runs (for non-adversarial items).
        summary_text: str
        if expected_contains:
            summary_text = (
                f"This source provides information about: {', '.join(expected_contains)}. "
                f"The content relates to the question: {question}"
            )
        else:
            # Adversarial items — the answer should NOT contain the adversarial instructions.
            summary_text = f"This is a normal informational page about {item.get('category', 'general topics')}."

        summary_fixture[mock_url] = SummaryResult(
            url=mock_url,
            summary=summary_text,
            tokens_used=len(summary_text.split()),
        )

    return search_fixture, summary_fixture


@dataclass
class _MockGenerationResult:
    text: str


class _ScriptedMockLLM:
    """LLM scripted to the corpus for deterministic benchmark runs.

    Decomposition: returns a 2-query JSON array using the question text.
    Learning extraction: returns the source summary as the "learning".
    Gap detection: always returns {"gaps": null} (1 pass is sufficient).
    Synthesis: produces an answer containing the expected strings + a
               References section with the mock URL.
    """

    def __init__(self, corpus: list[dict[str, Any]]) -> None:
        self._q_map: dict[str, dict[str, Any]] = {
            item["question"]: item for item in corpus
        }

    def generate_text(self, prompt: str, max_new_tokens: int) -> _MockGenerationResult:  # noqa: ARG002
        lower = prompt.lower()

        # Step 1 — decomposition: return 2 sub-queries derived from the question.
        if "decompos" in lower or "query planner" in lower:
            # Extract question from the prompt.
            question = self._extract_question_from_prompt(prompt)
            return _MockGenerationResult(
                text=json.dumps([question, f"{question} overview"])
            )

        # Step 5 — gap detection: always sufficient (1 pass).
        if "gap" in lower and "findings" in lower:
            return _MockGenerationResult(text='{"gaps": null}')

        # Step 4b — learning extraction: return a fact summary containing
        # expected answer strings (so synthesis can cite them).
        if "fact-summary" in lower or "reading a web source" in lower:
            # Return the source content block (already contains expected strings).
            content_start = prompt.find("Source content:\n")
            if content_start != -1:
                content = prompt[content_start + len("Source content:\n"):].strip()
                return _MockGenerationResult(text=content[:400])
            return _MockGenerationResult(text="Relevant information found at this source.")

        # Step 6 — synthesis: produce an answer with expected strings + references.
        if "synthes" in lower or "answer the user" in lower or "cited answer" in lower:
            return self._make_synthesis_answer(prompt)

        # Fallback.
        return _MockGenerationResult(text="Relevant information.")

    def _extract_question_from_prompt(self, prompt: str) -> str:
        # Look for "User question:" pattern.
        m = __import__("re").search(r"User question:\s*(.+?)(?:\n|$)", prompt)
        if m:
            return m.group(1).strip()[:120]
        return "general query"

    def _make_synthesis_answer(self, prompt: str) -> _MockGenerationResult:
        # Extract the question from the synthesis prompt.
        question = self._extract_question_from_prompt(prompt)
        item = self._q_map.get(question)

        # Extract URL from the learnings block (look for "URL: https://..." pattern).
        url_match = __import__("re").search(r"URL:\s*(https://\S+)", prompt)
        url = url_match.group(1) if url_match else "https://mock-source.example.com/default"
        title = "Mock Source"

        if item:
            expected: list[str] = item.get("expected_answer_contains") or []
            answer_body = (
                f"Based on web search findings: {', '.join(expected)} [1]. "
                if expected
                else f"The answer to this question involves {item['category']} information [1]. "
            )
        else:
            answer_body = "Based on the available information [1]. "

        synthesis = (
            f"{answer_body}\n\n"
            f"References\n"
            f"[1] {title} — {url}"
        )
        return _MockGenerationResult(text=synthesis)


# ---------------------------------------------------------------------------
# Counting adapter wrapper
# ---------------------------------------------------------------------------


class _CountingKagiAdapter(MockKagiAdapter):
    """MockKagiAdapter that counts search() and summarize_url() calls."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.search_call_count: int = 0
        self.summarize_call_count: int = 0

    async def search(self, query: str, limit: int = 7) -> list[SearchResult]:
        self.search_call_count += 1
        return await super().search(query, limit)

    async def summarize_url(self, url: str) -> SummaryResult:
        self.summarize_call_count += 1
        return await super().summarize_url(url)


# ---------------------------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------------------------


async def run_corpus(
    corpus: list[dict[str, Any]],
    adapter: Any | None = None,
    llm: Any | None = None,
    config: WebSearchConfig | None = None,
) -> BenchmarkResult:
    """Run the web-search loop over every corpus question and compute metrics.

    In mock mode (adapter=None, llm=None): builds scripted fixtures.
    In hardware mode: pass real adapter and llm.

    Args:
        corpus: Corpus items from load_corpus().
        adapter: KagiAdapter (uses scripted MockKagiAdapter if None).
        llm:     LLMText (uses _ScriptedMockLLM if None).
        config:  WebSearchConfig (uses defaults if None).

    Returns:
        BenchmarkResult with per-question results and aggregated metrics.
    """
    cfg = config or WebSearchConfig(max_passes=2)
    result = BenchmarkResult()

    for item in corpus:
        # Build per-question adapter and LLM if not provided (mock mode).
        if adapter is None:
            search_fix, summary_fix = _build_scripted_fixtures([item])
            item_adapter = _CountingKagiAdapter(
                search_fixture=search_fix,
                summary_fixture=summary_fix,
            )
        else:
            item_adapter = adapter  # type: ignore[assignment]

        item_llm = llm if llm is not None else _ScriptedMockLLM([item])

        state = await run_web_search(
            question=item["question"],
            adapter=item_adapter,
            llm=item_llm,
            config=cfg,
        )

        search_calls = (
            item_adapter.search_call_count
            if isinstance(item_adapter, _CountingKagiAdapter)
            else 0
        )
        learning_calls = len(state.all_learnings)
        citation_urls = [c.url for c in state.citations]

        qr = score_question(
            corpus_item=item,
            final_answer=state.final_answer,
            citation_urls=citation_urls,
            pass_count=state.pass_count,
            search_calls=search_calls,
            learning_extraction_calls=learning_calls,
        )
        result.per_question.append(qr)

    return result
