# GPU Runtime & Speculative Decoding Governance

## Audience

**Primary**: operator — runs BlarAI day-to-day, cares about what the GPU is
doing during inference, what the memory envelope looks like, how to tell
when something is wrong, and how to roll back the model if Qwen3-14B fails
validation on a future weight refresh.

**Secondary**: developer (maintains the AO inference loop and speculative
decoding wiring), auditor (reviews the ADR-011 "NPU retired from P1 Core
Loop" boundary and the ADR-012 §2.2 `num_assistant_tokens` lock).

## Prerequisites

- [ADR-011](../adrs/ADR-011-All-LLM-Inference-GPU-NPU-Retirement.md) — all
  LLM inference is on GPU; the NPU is retired from the P1 Core Loop. Any
  discussion of NPU here is for historical context only (DEPRECATED
  constants in `shared/constants.py` lines 37-60 are retained for future
  non-LLM workloads, not for inference).
- [ADR-012](../adrs/ADR-012-Qwen3-14B-Model-Selection-Speculative-Decoding.md)
  — Qwen3-14B INT4 as the unified target model across PA, AO, and the
  future USE-CASE-005; speculative decoding with a Qwen3-0.6B draft is
  **mandatory**.
- ADR-012 §2.2 — `NUM_ASSISTANT_TOKENS = 3` lock (the draft proposes
  three tokens; the target verifies; the ratio is the observed sweet
  spot for the current draft/target pairing).
- ADR-012 §2.4 — thinking-mode strategy. PA runs `/no_think` mandatory;
  AO allows thinking output with a transport-layer strip.
- ADR-012 §5 — Qwen2.5-1.5B retained as the legacy rollback target if
  Qwen3-14B fails a future integrity check.
- DEC-01..DEC-10 — production configuration decisions from Task 4.
  Load-bearing for runtime: memory-ceiling discipline, KV-cache
  retention, and the thinking-strip boundary.
- Peer governance docs: [circuit-breaker.md](circuit-breaker.md) for the
  `MAX_OUTPUT_TOKENS` interaction with KV-cache;
  [error-recovery.md](error-recovery.md) for model-load failure handling
  and the rollback recovery procedure; [ipc-protocol.md](ipc-protocol.md)
  for the PROMPT_REQUEST envelope that feeds `generate_text`.

## Source References

| Artifact | Path | Section / Constant |
|---|---|---|
| AO GPU inference harness | `services/assistant_orchestrator/src/gpu_inference.py` | `OrchestratorGPUInference.load_model` (line 354) |
| LLMPipeline target init (speculative) | `services/assistant_orchestrator/src/gpu_inference.py` | lines 405-444 (draft_config + target_config) |
| LLMPipeline fallback init (standard) | `services/assistant_orchestrator/src/gpu_inference.py` | lines 446-464 |
| KV-cache warm / invalidate | `services/assistant_orchestrator/src/gpu_inference.py` | `warm_kv_cache`, `invalidate_kv` (lines 717-811) |
| Generation config + stop tokens | `services/assistant_orchestrator/src/gpu_inference.py` | `_build_generation_config` (lines 838-875) |
| Thinking-block strip | `services/assistant_orchestrator/src/gpu_inference.py` | lines 929-936 (`re.sub` over `<\|think\|>…`) |
| AO entrypoint — device validation | `services/assistant_orchestrator/src/entrypoint.py` | `_validate_config_data` GPU check (lines 449-465) |
| AO entrypoint — model-load Fail-Closed | `services/assistant_orchestrator/src/entrypoint.py` | `start()` lines 241-248 |
| Unified target / draft paths | `shared/constants.py` | `TARGET_MODEL_OV_PATH` line 158, `DRAFT_MODEL_OV_PATH` line 161 |
| Speculative decoding toggle | `shared/constants.py` | `SPECULATIVE_DECODING_ENABLED` line 166 |
| Assistant tokens constant | `shared/constants.py` | `NUM_ASSISTANT_TOKENS` line 169 |
| Memory ceiling | `shared/constants.py` | `EFFECTIVE_CEILING_GB` line 19 (31.323 GB) |
| Output-token cap | `shared/constants.py` | `MAX_OUTPUT_TOKENS` line 135 (4096) |
| Qwen3 `<\|im_end\|>` stop token | `services/assistant_orchestrator/src/gpu_inference.py` | `QWEN3_IM_END_TOKEN_ID = 151_645` (line 96) |
| PA device lock | `shared/constants.py` | `PA_DEVICE` line 48 (`"GPU"`) |
| AO device lock | `shared/constants.py` | `AO_DEVICE` line 53 (`"GPU"`) |
| Weight integrity verify | `shared/models/weight_integrity.py` | `verify_weight_integrity` |

## Governance Content

### Device Binding — Both Models on Arc 140V

Both PA and AO compile their Qwen3-14B instances on the same Arc 140V Xe2
GPU. `shared/constants.py` locks `PA_DEVICE = "GPU"` (line 48) and
`AO_DEVICE = "GPU"` (line 53). The AO entrypoint further enforces this at
config-load time: `_validate_config_data` rejects any configured device
other than `GPU` with `AO_CFG_DEVICE_INVALID` and cites ADR-011 in the
error message (`entrypoint.py` lines 449-455). There is no runtime toggle
to move inference back to the NPU — the toggle does not exist, and the
DEPRECATED `NPU_*` constants in `shared/constants.py` remain only for
future non-LLM workloads.

### Target Model Load Procedure

`OrchestratorGPUInference.load_model` (`gpu_inference.py` line 354)
executes a deterministic four-step load:

1. **OpenVINO GenAI availability** — the harness imports
   `openvino_genai` at module scope. If the import fails,
   `_OV_GENAI_AVAILABLE = False`, and `load_model()` immediately returns
   `False` at line 367. Fail-Closed: the service cannot start.
2. **Model files present** — `openvino_model.xml` and `openvino_model.bin`
   must both exist in `self._model_dir` (default
   `models/qwen3-14b/openvino-int4-gpu` per `TARGET_MODEL_OV_PATH`). If
   either is missing, `load_model()` returns `False` at line 380 and the
   entrypoint raises `AO_MODEL_LOAD_FAILED`.
3. **Weight integrity verification** — when `manifest_path` is supplied
   (required in production via `_validate_security_material` at
   `entrypoint.py` lines 659-691), `verify_weight_integrity` compares the
   SHA-256 digest of `openvino_model.bin` against the Known-Good
   Manifest. A mismatch returns an `IntegrityCheckResult` with
   `verified=False` and `load_model()` returns `False` at line 393.
4. **LLMPipeline instantiation** — built with `PERFORMANCE_HINT=LATENCY`,
   `INFERENCE_PRECISION_HINT=f16`, `GPU_ENABLE_SDPA_OPTIMIZATION=ON`,
   `CACHE_DIR=""` (compilation cache disabled by deliberate choice — the
   empty string suppresses OpenVINO's on-disk compilation cache, so the
   pipeline recompiles fresh on every start).

   **Why disabled — measured 2026-06-03 (supersedes the original
   "guaranteed identical compiled state" rationale):** an empirical probe
   on the Arc 140V (`PERFORMANCE_LOG.md` → `2026-06-03`;
   `docs/performance/cache_dir_probe_2026-06-03/`) established that (a) a
   warm cache produces **byte-identical** output to a fresh compile — the
   cache does not threaten reproducibility, it preserves it — and (b) the
   cache yields **no reliable startup win**: a fresh 14B + draft compile is
   \~11 s, indistinguishable from a cold-disk read of the \~9 GB cache blob,
   while enabling it costs a one-time +42 s blob write, +9 GB disk per
   `{OV version, device, model, shape}` key, and a re-write on every
   OpenVINO / driver / model change (and the mandatory integrity-hash of
   the derived blob would push it firmly negative — see the 2026-05-22
   boot-time investigation in `BUILD_JOURNAL.md`). The cache is therefore
   left off because it buys no measurable startup benefit at real cost, not
   to secure an identical compiled state it already provides.

### Draft Model Load and Device Binding

When `SPECULATIVE_DECODING_ENABLED = True` (line 166 of
`shared/constants.py`, the operational default) AND the draft directory
resolves to an existing path, the AO wires a `draft_model` into the
target `LLMPipeline` via the nested config (`gpu_inference.py` lines
405-444). The draft is Qwen3-0.6B INT4 at `models/qwen3-0.6b/openvino-
int4-gpu` per `DRAFT_MODEL_OV_PATH` (line 161). Both draft and target
bind to `self._device` — the same GPU slot — so the two models share
the Arc 140V Xe2 without cross-device handoff.

If the speculative init raises, the harness logs a warning and falls
back to a standard single-model `LLMPipeline` (lines 440-464). The
fallback is a safety net for partially-populated draft directories; in
the normal operational posture, the speculative path is hot.

### Speculative Decoding Lock — `num_assistant_tokens = 3`

The speculative pair passes `num_assistant_tokens = NUM_ASSISTANT_TOKENS`
to the target config (`gpu_inference.py` line 427) and into each
individual `GenerationConfig` where supported (lines 869-873). The
constant is `3` (`shared/constants.py` line 169), locked per ADR-012
§2.2 as the empirically-observed sweet spot for the current
Qwen3-14B / Qwen3-0.6B pairing. Higher values drive more draft-token
overhead when the target frequently rejects; lower values underutilize
the draft. Any proposal to change the constant MUST cite a replayable
benchmark on the current draft/target pairing — this is threshold-
tuning governance, not operator tuning.

### KV-Cache Management

The KV-cache persists across generations within a single
`LLMPipeline` instance. `warm_kv_cache` (`gpu_inference.py` lines
717-751) runs a one-token prefill pass over a context to populate the
cache — this is how the AO achieves the warm-state first-token
target (`ORCH_FIRST_TOKEN_WARM_MS = 1000.0`, `shared/constants.py` line
125) versus the cold-state target (`ORCH_FIRST_TOKEN_COLD_MS = 1500.0`,
line 128). Per-session warm state is tracked in `self._kv_warm_sessions`
(a `set[str]`).

Approximate working sizes (from P5-005 measurement series; exact values
shift with context length): PA cache settles in the 350-550 MB range;
AO cache sits in the 1.0-1.2 GB range when actively streaming. The
cache is FP16 — OpenVINO GenAI's default for the pipeline under
`INFERENCE_PRECISION_HINT=f16`.

### Circuit-Breaker Interaction with KV-Cache

`MAX_OUTPUT_TOKENS = 4096` (`shared/constants.py` line 135) is the hard
token cap. When the AO's generation hits the cap mid-stream, the
circuit-breaker trip does NOT flush the KV-cache — the cache remains
warm for the current `LLMPipeline` instance and the next request
against that session benefits from the prefill state already resident.
The cache IS flushed when `invalidate_kv` is called explicitly — the
documented trigger for that flush is Code Agent activation entering the
USE-CASE-004 degradation posture (see `invalidate_kv` docstring at
`gpu_inference.py` lines 782-798). Operator-facing rule: a circuit-
breaker trip is not a cache invalidation event; explicit degradation
is. See [circuit-breaker.md](circuit-breaker.md) for the full trip
semantics.

### Thinking-Mode Suppression

The AO supports thinking output per ADR-012 §2.4 but suppresses it at
the transport boundary. Two mechanisms cooperate:

1. **Stop-token wiring**. `_build_generation_config` sets
   `gen_config.stop_token_ids = [QWEN3_IM_END_TOKEN_ID]` (line 859) —
   where `QWEN3_IM_END_TOKEN_ID = 151_645` (line 96). The generation
   halts on `<|im_end|>`, so a runaway thinking block that forgets to
   close is still bounded by the chat-turn terminator, AND the output-
   token cap stays authoritative.
2. **Post-generation strip**. After `self._pipeline.generate(...)`
   returns, the harness applies `re.sub(r"<\|think\|>.*?(?:</\|think\|>|$)",
   "", output_text, flags=re.DOTALL)` (lines 931-936). This removes
   both closed `<|think|>…</|think|>` blocks AND an unterminated
   trailing block (if generation ends mid-think). The user-facing
   `text` field never carries thinking content.
3. **Stream suppression**. The streamer callback at lines 895-915
   tracks a `_in_thinking_block` flag across chunks so that
   `stream_callback` (which feeds the UI Gateway) is NEVER invoked
   during a thinking span. The streamed UI surface sees only post-
   strip tokens.

For PA, the directive is stricter: `/no_think` is appended to the
default system prompt (`gpu_inference.py` line 144), and the PA service
relies on the same stop-token + strip machinery for any stray thinking
output. The PA path is configured to not emit thinking at all; the
mechanics are defense-in-depth.

### Stop-Token Ids Note

STYLE.md does not require a verbatim recitation of stop-token IDs, but
for completeness:

- `QWEN3_IM_END_TOKEN_ID = 151_645` — chat-turn terminator
  (`gpu_inference.py` line 96). Authoritative stop token for AO.
- `_DEFAULT_EOS_TOKEN_ID = 151_643` — module default, overridden at
  tokenizer load time if the Qwen3 tokenizer advertises its own EOS
  (`_load_tokenizer` lines 504-507).
- ADR-012 §2.4 discusses the historical `[151645, 151668]` pairing for
  explicit thinking-block truncation. The current harness relies on
  stop-token-id + post-strip rather than a second stop token; if the
  model family changes, the stop-token set is reviewed against ADR-012.

### Weight Integrity and XAttention Posture

`verify_weight_integrity` (imported from `shared/models/weight_
integrity.py`) is the boot-time gate. Its detailed governance is
deferred to `weight-integrity.md` (GOV-10 / Vikunja #23), currently
blocked on ISS-4 Pluton investigation. Until that doc lands, the
operational contract is: at each AO start, the SHA-256 digest of
`openvino_model.bin` is compared against the Known-Good Manifest;
mismatch is Fail-Closed. See [error-recovery.md](error-recovery.md)
for the Fail-Closed path on mismatch.

XAttention is OFF in the current runtime. The harness does not set
any OpenVINO flag to enable it; `GPU_ENABLE_SDPA_OPTIMIZATION=ON` is
scaled-dot-product-attention optimization, a separate code path. If a
future ADR amendment enables XAttention, it would appear as a new key
in `target_config` / `fallback_config` at `gpu_inference.py` lines
415-452.

### Empirical Performance Baseline

The empirical throughput baseline from the P5-005 series (recorded at
the time of the Qwen3-14B + Qwen3-0.6B speculative decoding pairing):

- **\~10.7 tps @ 4K-token context**
- **\~4.2 tps @ 20K-token context**

These numbers are the load-bearing datum for the ADR-012 §2.2
`num_assistant_tokens = 3` choice. The primary evidence path is
`phase2_gates/evidence/` — P5-005b specifically. At Sprint 9 EA-2
authoring time, the evidence artifact was not directly locatable by
filename; the numbers above are the operational baseline cited in
ADR-012 and in the USE-CASE-004 acceptance record. A future sprint
should re-run the benchmark and recommit the evidence JSON under a
stable filename, then update this doc's citation.

### Memory Ceiling Discipline

The effective memory ceiling is **31.323 GB** (`EFFECTIVE_CEILING_GB`,
`shared/constants.py` line 19) — 32 GB LPDDR5X minus 693 MB firmware
reservation (`FIRMWARE_RESERVATION_MB = 692.8`, line 22). The runtime
stays under this ceiling by:

- Qwen3-14B INT4 weights ≈ 9.1 GB (`TARGET_MODEL_WEIGHT_MB = 9_100`,
  line 155), mmap-resident read-only, shared between PA and AO.
- Qwen3-0.6B draft weights << 1 GB (INT4 quantization; exact size
  depends on the operational variant — PROVISIONAL per line 162).
- Combined KV-cache FP16 working set: ≈ 1.3-1.7 GB active when both
  services stream.
- OS + TUI + launcher + observability ≈ 3-4 GB depending on session
  history and embedded logs.

There is no runtime OOM guard in the AO inference path — the system
relies on the fixed memory budget and DEC-* load-bearing sizing to
stay under the ceiling. If memory pressure materializes (e.g., a
future ADR adds a third model), the circuit breakers and the
invalidate-KV degradation posture are the levers, not a runtime
`psutil` check.

## Recovery / Remediation Procedures

### Model Rollback — Qwen3-14B → Qwen2.5-1.5B

ADR-012 §5 retains Qwen2.5-1.5B as the rollback target if Qwen3-14B
fails a future validation or integrity check. The rollback is not
automatic — it is operator-gated. Procedure:

1. Verify the failure class. Integrity mismatch → re-download and
   re-verify weights BEFORE rolling back (the rollback is for
   persistent failure, not transient corruption).
2. Replace `TARGET_MODEL_OV_PATH` in `shared/constants.py` with the
   legacy Qwen2.5-1.5B path. This is a code change — intentional, to
   prevent runtime rollback via config edit.
3. Regenerate the Known-Good Manifest for the legacy weights.
4. Restart the AO service. On boot, the entrypoint's
   `_validate_security_material` (lines 649-711) validates the new
   model's digest.
5. Record the rollback in the ledger with the failure fingerprint
   and the rationale. See [error-recovery.md](error-recovery.md) for
   the general rollback escalation matrix.

This path is a rehearsal-only posture today — Qwen3-14B has been the
operational model since ADR-012 locked. A live rollback has not
occurred in production.

### KV-Cache Corruption — Invalidate + Re-Warm

If output quality collapses mid-session (symptom: the AO produces
nonsense for a warm session but fresh sessions are healthy), flushing
the session's KV-cache is the first remediation step:

1. Obtain the session id from the failing request (visible in the
   UI Gateway's session panel or the AO log at INFO level).
2. Call `invalidate_kv(session_id=...)` on the running
   `OrchestratorGPUInference` instance. This discards the session's
   warm-set entry AND calls `finish_chat` / `reset` / `clear_history`
   on the pipeline if available (`gpu_inference.py` lines 803-811) —
   whichever method the current OpenVINO GenAI build exposes.
3. The next request against that session incurs cold-start latency
   (up to `ORCH_FIRST_TOKEN_COLD_MS = 1500 ms`) while the cache
   rebuilds; steady-state warm latency restores once the session has
   a stable context.

A global flush (`invalidate_kv(None)`, line 795) is the sledgehammer —
it drops every session's warm state. Reserve for Code Agent
degradation activation per the docstring.

## Open Questions / Deferred Items

- **Boot-sequence governance** — the AO startup path crosses
  `launcher/__main__.py` and `services/assistant_orchestrator/src/
  entrypoint.py`; a consolidated boot-sequence governance doc would
  be the natural place to describe the full launcher→VM→service
  handshake. Tracked as GOV-15 / Vikunja #124 for a future sprint.
  Within this doc, source files are cited directly (the relevant
  startup entry points are `launcher/__main__.py` and
  `services/assistant_orchestrator/src/entrypoint.py`).
- **P5-005b empirical baseline evidence path** — the evidence JSON
  cited in the Empirical Performance Baseline section was not
  directly locatable by filename at authoring time. The baseline
  numbers are cited from ADR-012. A future sprint should recommit
  the evidence artifact under a stable path and update this doc.
- **XAttention re-enablement** — not currently in scope. If ever
  enabled, this doc gets a new subsection under Governance Content
  and the `target_config` dict in `gpu_inference.py` gets a new key.
- **Weight-integrity governance** — the full ceremony around the
  Known-Good Manifest, Pluton-sealing, and re-attestation is
  Pluton-blocked per ISS-4. Until GOV-10 /
  [weight-integrity.md](weight-integrity.md) lands, the operational
  contract is the Fail-Closed mismatch behavior documented in the
  Weight Integrity subsection above.
- **Draft-model variant churn** — `DRAFT_MODEL_OV_PATH` is labelled
  PROVISIONAL in `shared/constants.py` line 162; the operational
  draft may shift to a pruned Qwen3-0.6B variant or to Qwen3-1.7B
  pending further empirical work. The `num_assistant_tokens = 3`
  constant is paired with the current draft; any draft change
  triggers a re-pairing exercise per ADR-012 §2.3.
