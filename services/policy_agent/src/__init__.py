"""
Policy Agent — Action Authorization Boundary (USE-CASE-001)
============================================================
GPU Inference (ADR-010) | CAR adjudication | Agentic JWT | vsock mTLS | Measured Boot

The Policy Agent is the security-critical gatekeeper. Every inter-agent
tool call must be authorized through this service before execution.
"""

__version__ = "0.1.0"
