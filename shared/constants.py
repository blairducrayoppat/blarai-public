"""
Empirical Hardware Constants — Phase 2 Locked Baseline
=======================================================
Source: ADR-005, ADR-006, ADR-007, ADR-008, ADR-010, ADR-011, ADR-012
Branch: feature/phase2-scaffolding (commits a732399..66106cc)
Updated: 2026-02-28 (ADR-012 — Qwen3-14B confirmed, config optimization in progress)

These values are derived from physical hardware measurements on the
ASUS ExpertBook P5 (P5405CSA) with Intel Core Ultra 7 258V (Lunar Lake).
DO NOT modify without re-running Phase 2 validation gates.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Memory Ceiling (ADR-005, ADR-006)
# ---------------------------------------------------------------------------

EFFECTIVE_CEILING_GB: float = 31.323
"""Effective memory ceiling in GB. 32GB LPDDR5X-8533 minus 692.8MB firmware."""

FIRMWARE_RESERVATION_MB: float = 692.8
"""Total firmware reservation: DVMT + CSME + PTT + BIOS runtime."""

OS_VISIBLE_MB: float = 32_075.2
"""OS-visible memory in MB (Windows 11 Pro Build 26200)."""

TOLERANCE_MB: float = 128.0
"""Measurement tolerance for memory calculations."""

# ---------------------------------------------------------------------------
# NPU Scheduling (ADR-008) — DEPRECATED by ADR-011 (2026-02-27)
# NPU retired from P1 Core Loop. All LLM inference on GPU.
# Constants retained for backward compatibility and future NPU use cases.
# ---------------------------------------------------------------------------

NPU_SCHEDULING_MODEL: str = "parallel"
"""DEPRECATED (ADR-011): NPU retired from P1 Core Loop.
Empirical observation retained: Lunar Lake NPU executes true parallel dual-model inference."""

NPU_PARALLELISM_RATIO: float = 1.699
"""DEPRECATED (ADR-011): NPU retired from P1 Core Loop.
Concurrent/sequential execution time ratio. >1.3 = parallel."""

NPU_PA_PRIORITY: int = 0
"""DEPRECATED (ADR-010, ADR-011): PA moved to GPU. NPU retired from P1 Core Loop."""

PA_DEVICE: str = "GPU"
"""Policy Agent inference device (ADR-010, confirmed by ADR-011).
Empirical benchmark: GPU 78ms mean / 125ms P95 vs NPU 543ms mean.
The NPU cannot meet the 230ms PA adjudication budget."""

AO_DEVICE: str = "GPU"
"""Assistant Orchestrator inference device (ADR-011).
Empirical benchmark (P5-004): GPU 36-53 tps vs NPU 3-14 tps.
NPU retired from P1 Core Loop; all LLM inference on GPU."""

NPU_ORCH_PRIORITY: int = 1
"""DEPRECATED (ADR-011): AO moved to GPU. NPU retired from P1 Core Loop.
Retained for backward compatibility."""

NPU_SUBSTRATE_PRIORITY: int = 2
"""Substrate bi-encoder NPU scheduling priority.
NPU remains a candidate for future non-LLM workloads (USE-CASE-002/003)."""

NPU_KV_CACHE_PERSISTS: bool = True
"""Empirically confirmed: KV-cache survives context switches between models."""

PREEMPTION_P99_MS: float = 0.814
"""Measured preemption P99 latency (proxy model). Budget: 500ms."""

ORCHESTRATOR_RESUME_MAX_MS: float = 0.503
"""Measured max orchestrator resume latency (proxy model). Budget: 500ms."""

# ---------------------------------------------------------------------------
# Trust Boundary (ADR-007)
# ---------------------------------------------------------------------------

TDX_AVAILABLE: bool = False
"""TDX not present on client Lunar Lake (expected)."""

TRUST_POSTURE: str = "software_fallback"
"""Hyper-V + vsock AF_HYPERV + mTLS. See ADR-007."""

VBS_ENABLED: bool = True
"""Virtualization-Based Security confirmed active."""

SECURE_BOOT: bool = True
"""SecureBoot confirmed active in UEFI."""

TPM_PRESENT: bool = True
"""TPM 2.0 confirmed present."""

# ---------------------------------------------------------------------------
# Latency Budgets (Use Cases_FINAL.md)
# ---------------------------------------------------------------------------

PA_PREEMPTION_P95_BUDGET_MS: float = 200.0
"""Policy Agent preemption P95 latency budget."""

PA_PREEMPTION_P99_BUDGET_MS: float = 500.0
"""Policy Agent preemption P99 latency budget."""

ORCH_RESUME_BUDGET_MS: float = 500.0
"""Orchestrator resume latency budget after PA preemption."""

KV_CACHE_RECONSTRUCT_BUDGET_MS: float = 500.0
"""KV-cache reconstruction budget if evicted (not needed per ADR-008)."""

CONCURRENT_THROUGHPUT_FLOOR: float = 0.60
"""Minimum concurrent throughput ratio vs single-model baseline."""

SEMANTIC_ROUTER_LATENCY_MS: float = 80.0
"""Semantic Router CPU classification latency target."""

PA_GPU_LATENCY_MEAN_MS: float = 78.0
"""Empirical PA GPU classification mean latency (ms). ADR-010/ADR-011 benchmark."""

PA_GPU_LATENCY_P95_MS: float = 125.0
"""Empirical PA GPU classification P95 latency (ms). ADR-010/ADR-011 benchmark."""

PA_ADJUDICATION_BUDGET_MS: float = 230.0
"""PA adjudication latency budget (Use Cases_FINAL.md). GPU meets this; NPU does not."""

ORCH_FIRST_TOKEN_WARM_MS: float = 1_000.0
"""Orchestrator first-token latency from warm state (KV-cache resident)."""

ORCH_FIRST_TOKEN_COLD_MS: float = 1_500.0
"""Orchestrator first-token latency from context-switch state."""

# ---------------------------------------------------------------------------
# Circuit Breakers (USE-CASE-004, OWASP LLM04)
# ---------------------------------------------------------------------------

MAX_OUTPUT_TOKENS: int = 4_096
"""Hard cap: maximum output tokens per Orchestrator response."""

MAX_TOOL_CALL_DEPTH: int = 5
"""Maximum recursive tool-call chain depth per user query."""

# ---------------------------------------------------------------------------
# Model Specifications — ADR-012: Qwen3-14B confirmed, config optimization in progress
# Qwen2.5-1.5B demoted to legacy reference. Draft model under evaluation.
# ---------------------------------------------------------------------------

TARGET_MODEL: str = "Qwen3-14B"
"""ADR-012: Confirmed target model for PA, AO, and USE-CASE-005."""

TARGET_MODEL_PARAMS: str = "14B"
"""ADR-012: Target model parameter count. Locked."""

TARGET_MODEL_QUANT: str = "INT4"
"""ADR-012: Target model quantization (INT4 symmetric, group_size=128). Locked."""

TARGET_MODEL_WEIGHT_MB: int = 9_100
"""ADR-012: Measured target model weight file size (~9.1 GB openvino_model.bin)."""

TARGET_MODEL_OV_PATH: str = "models/qwen3-14b/openvino-int4-gpu"
"""ADR-012: Relative path to the Qwen3-14B OpenVINO INT4 GPU directory. Locked."""

DRAFT_MODEL_OV_PATH: str = "models/qwen3-0.6b-pruned-6l/openvino-int8-gpu"
"""Operational speculative-decoding draft model: Qwen3-0.6B pruned to 6 layers,
OpenVINO INT8 (GPU). Selected 2026-05-22 over the full INT4 0.6B draft because the
pruned draft streams tokens incrementally (first token ~0.7s) while the full draft
delivers each reply all-at-once. Clean A/B benchmark: throughput tied on
explanatory prompts, full draft ~20% faster on terse factual ones — streaming
chosen for interactive-chat responsiveness. Speculative decoding is exact, so the
draft model affects speed only, never output. See PERFORMANCE_LOG.md (2026-05-22)."""

SPECULATIVE_DECODING_ENABLED: bool = True
"""ADR-012: Speculative decoding is mandatory for the Qwen3-14B inference pipeline."""

NUM_ASSISTANT_TOKENS: int = 3
"""PROVISIONAL BEST (P5-005b): Optimal num_assistant_tokens for speculative decoding.
May shift with different draft model. See ADR-012 §2.2."""

# ---------------------------------------------------------------------------
# Voice (ADR-017) — STT (Whisper-small) + TTS (Kokoro, 54-voice bank)
# ---------------------------------------------------------------------------

VOICE_ENABLED: bool = False
"""Whether the launcher preloads the voice models (Whisper STT + the 54-voice
Kokoro TTS bank) at boot.

Default False (2026-06-04, #561): the User-Operator is not using voice yet and
does not want auto audio recital, and on the Arc 140V iGPU (no separate VRAM)
the voice models share the 32 GB system RAM with the resident 14B + on-demand
VLM — preloading them contributed to a 100%-RAM freeze. With voice disabled the
launcher builds a no-model VoiceEngine (the existing fail-soft path): STT/TTS
report unavailable, the UI gates the mic/speaker affordances off, and ``speak``
is gated off so replies are never auto-spoken. No capability the User-Operator
is using is lost; set True (and reboot) to restore voice. A future
lazy-load-on-first-use path could keep voice available without the boot cost.
This is a code constant rather than an env var on purpose: the launcher
self-elevates through UAC and a fresh elevated process does not inherit the
shell's environment (BUILD_JOURNAL lesson 11)."""

# --- Legacy model constants (retained for backward compat / rollback) ---
PA_MODEL_SIZE_PARAMS: str = "14B"
"""ADR-012: Policy Agent model parameter count. Unified with AO and USE-CASE-005."""

PA_MODEL_QUANT: str = "INT4"
"""ADR-012: Policy Agent quantization level."""

PA_MODEL_WEIGHT_MB: int = 9_100
"""ADR-012: Policy Agent weight file size (shared Qwen3-14B target model)."""

ORCH_MODEL_SIZE_PARAMS: str = "14B"
"""ADR-012: Orchestrator model parameter count. Unified with PA and USE-CASE-005."""

ORCH_MODEL_QUANT: str = "INT4"
"""ADR-012: Orchestrator quantization level."""

ORCH_MODEL_WEIGHT_MB: int = 9_100
"""ADR-012: Orchestrator weight file size (shared Qwen3-14B target model)."""

SEMANTIC_ROUTER_MODEL: str = "bge-small-en-v1.5"
"""Semantic Router model: BAAI/bge-small-en-v1.5 (33M params, 384-dim)."""

SEMANTIC_ROUTER_MODEL_MB: int = 128
"""Measured Semantic Router ONNX FP16 model size (evidence: 127.8 MB)."""

SEMANTIC_ROUTER_ONNX_PATH: str = "models/bge-small-en-v1.5/onnx-fp16/model.onnx"
"""Relative path to the Semantic Router ONNX model file."""

SEMANTIC_ROUTER_OV_PATH: str = "models/bge-small-en-v1.5/openvino-int8"
"""Relative path to the Semantic Router OpenVINO INT8 directory (NPU Substrate)."""

PA_OV_PATH: str = "models/qwen3-14b/openvino-int4-gpu"
"""ADR-012: Relative path to the PA / Orch / USE-CASE-005 shared Qwen3-14B model.
Both PA and AO compile this model for GPU. Unified target model locked by ADR-012."""

# ---------------------------------------------------------------------------
# Security Defaults (Fail-Closed)
# ---------------------------------------------------------------------------

FAIL_CLOSED: bool = True
"""Default security posture: deny all unclassified actions."""

JWT_VALIDITY_SECONDS: int = 5
"""Canonical Agentic-JWT hard TTL in seconds (Use Cases_FINAL.md §3).

Single source of truth for the capability-token lifetime, shared by the minter
(``services/policy_agent/src/constants.py`` re-exports this as its default) and
by every destination validator, which sizes its nonce-seen window to OUTLAST
this value (#638, ``shared.crypto.jwt_validator.aligned_nonce_ttl``). Keeping
the lifetime here — one number both the minter and the validators read — is what
stops the validity and the nonce-TTL drifting apart (the 5 s-nonce-under-30 s-
token replay window #638 closed). Per-service TOML ``[jwt] validity_seconds``
may override the minter at runtime within the entrypoint's 1..300 s guard."""

MMAP_READ_ONLY: bool = True
"""Shared weight file mmap is read-only, no copy-on-write."""

COSINE_SIMILARITY_THRESHOLD: float = 0.85
"""PGOV leakage detection threshold for retrieved-content similarity."""

# ---------------------------------------------------------------------------
# VM Provisioning (Orchestrator VM — Hyper-V)
# ---------------------------------------------------------------------------

ORCHESTRATOR_VM_NAME: str = "BlarAI-Orchestrator"
"""Hyper-V VM name for the Orchestrator service."""

ORCHESTRATOR_VM_ID: str = "9c7f986f-7afd-48b0-af5b-2c330df6b38f"
"""Hyper-V VM ID assigned at creation. Required for AF_HYPERV socket addressing."""

VSOCK_SERVICE_GUID: str = "0000c350-facb-11e6-bd58-64006a7986d3"
"""Registered vsock (AF_HYPERV) service GUID for host ↔ Orchestrator IPC.
Uses hv_sock template format: <port_hex>-facb-11e6-bd58-64006a7986d3."""

VSOCK_PORT: int = 50000
"""AF_VSOCK port number for guest-side listener (maps to VSOCK_SERVICE_GUID)."""

GUEST_PARSER_VSOCK_PORT: int = 50001
"""AF_VSOCK port for the guest parser service (UC-003 Stage C, ADR-030 §3).
Distinct from VSOCK_PORT — the parser is its own guest listener, not the
Orchestrator channel.  50001 == 0xC351 (maps to GUEST_PARSER_SERVICE_GUID)."""

GUEST_PARSER_SERVICE_GUID: str = "0000c351-facb-11e6-bd58-64006a7986d3"
"""hv_sock service GUID for the guest parser service (template
<port_hex>-facb-11e6-bd58-64006a7986d3 with port 0xC351 = 50001).  Host-side
registry registration of this service GUID is part of the host-glue wiring
task, not the Stage-C service build."""

ORCHESTRATOR_VM_MEMORY_GB: int = 2
"""Fixed memory allocation for the Orchestrator VM (GB)."""

ORCHESTRATOR_VM_VCPUS: int = 2
"""Virtual CPU count for the Orchestrator VM."""

ORCHESTRATOR_VM_DISK_PATH: str = r"C:\HyperV\BlarAI\Orchestrator.vhdx"
"""Path to the Orchestrator VM virtual disk."""

ORCHESTRATOR_VM_OS: str = "Alpine Linux 3.21.3"
"""Guest OS for the Orchestrator VM (minimal footprint)."""
