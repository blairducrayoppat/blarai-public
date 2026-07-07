"""Substrate (USE-CASE-002) performance benchmark — Vikunja #542.

Measures the two costs the Personal Knowledge Substrate adds to the Assistant
Orchestrator:

  (a) **embedder load** at startup — decomposed, and measured both *isolated*
      (a fresh process that has not imported ``transformers``) and *marginal*
      (``transformers`` already imported, as it always is in the real AO because
      ``gpu_inference`` imports it at module load for the 14B). The gap between
      the two is the whole story of #553.

  (b) **per-turn retrieval latency** — one query embed + brute-force cosine over
      the document and turn matrices — measured mean/p50/p95 across a
      representative prompt set at several corpus scales.

All measurement runs against a FRESH temporary substrate (``tempfile``); the
harness refuses to open the real ``%LOCALAPPDATA%\\BlarAI\\substrate.db``.
Numbers are written as a community-grade perf record via
``tests.harness.latency.write_perf_record`` (curated upstream by
``tools/perf_contrib``).
"""
