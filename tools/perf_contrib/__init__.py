"""BlarAI perf-contribution pipeline.

Validates, curates, and aggregates community-grade OpenVINO / HuggingFace
perf records from ``docs/performance/`` into a publishable dataset.

Public API
----------
- :mod:`tools.perf_contrib.schema`     — record schema validation
- :mod:`tools.perf_contrib.aggregator` — validation + scrub + CSV/JSONL export
- :mod:`tools.perf_contrib.cli`        — CLI entry-point (``python -m tools.perf_contrib``)

No external network calls are made.  Submission is a deliberate manual act.
"""
