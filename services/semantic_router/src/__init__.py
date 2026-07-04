"""
Semantic Router — CPU-Based Intent Classifier (USE-CASE-004)
==============================================================
CPU bge-small-en-v1.5 (~128MB ONNX FP16) | ONNX Runtime | Sub-80ms | Stateless

The Semantic Router classifies user intents to determine whether a query
requires the Orchestrator, a skill dispatch, or is out-of-scope. It uses
BAAI/bge-small-en-v1.5 (384-dim embedding) on CPU via ONNX Runtime to
avoid contention with the PA/Orchestrator NPU workloads.
"""

__version__ = "0.1.0"
