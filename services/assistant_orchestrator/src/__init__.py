"""
Assistant Orchestrator — Conversational Generation Engine (USE-CASE-004)
=========================================================================
NPU Sole Consumer (ADR-010) | KV-cache warm | PGOV | Circuit Breakers | Context Spotlighting

The Orchestrator handles user-facing conversational generation.
ADR-010: PA moved to GPU — Orchestrator is sole NPU consumer, no preemption contention.
"""

__version__ = "0.1.0"
