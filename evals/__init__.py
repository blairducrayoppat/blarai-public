"""
BlarAI Model-Quality Eval Harness (#717)
=========================================
Golden-set evals that measure the *intelligence* of the system — the PA's
classification judgment, the AO's tool-call parsing/dispatch behaviour, and
the deterministic governance verdicts — so any future model or prompt change
can be scored against a committed baseline.

This package measures MODEL/POLICY QUALITY, not software correctness (the
standing pytest gate owns software correctness). Deterministic suites run
with no GPU and no network; model-in-the-loop cases are flagged
``requires_hardware`` and only run on the Arc 140V when explicitly requested.

Entry point:  python -m evals.run --suite <name>|all
Suites:       pa_classification, tool_calling, governance
Golden data:  evals/golden/*.jsonl
Baselines:    evals/baselines/*.json  (committed; regressions exit nonzero)

Design mirrors tests/pa_quality_benchmark/ and
services/assistant_orchestrator/tests/websearch_benchmark/ (the two
pre-existing quality-benchmark precedents in this repo).
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "1.0.0"
