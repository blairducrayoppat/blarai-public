# Disposition: is `qwen2.5-1.5b(-instruct)` dead weight?

- **Ticket:** Vikunja #916 (identifier #301) — LOW-priority hygiene, surfaced during #107 (model-manifest signing).
- **Date:** 2026-07-16
- **Verdict:** The ticket's claim is **VERIFIED**. `Qwen2.5-1.5B-Instruct` is **NOT a served model** — no runtime service (`services/`), the launcher (`launcher/`), or any served-model config loads or serves it. Its only references are (a) load-bearing exclusion rationale + a regression-lock test in the signing paths, (b) an accurate legacy note in `shared/constants.py`, and (c) the dev/feasibility harness + evidence + decision record of the NPU LLM-inference investigation that retired it.
- **Disposition:** **RETAIN. No code references removed** — every reference is load-bearing (nothing is dead *code*). "Dead weight" applies only in the narrow disk sense: ~1.05 GB of gitignored weights that nothing serves. Physical deletion is an optional operator follow-up for the LA (see §5).

---

## 1. What Qwen2.5-1.5B-Instruct was, and why it is unused now

`Qwen2.5-1.5B-Instruct` (OpenVINO INT4-MIXED, NPU) was the **original Assistant-Orchestrator model on the NPU** during the P5 feasibility era (Feb 2026):

- **ADR-010** (2026-02-24) moved the Policy Agent from NPU to GPU on latency evidence, but kept the Orchestrator on the NPU running the "production model (Qwen2.5-1.5B-Instruct INT4-MIXED)" (ADR-010 §... line 23). ADR-010 §96 explicitly retained the path `models/qwen2.5-1.5b-instruct/openvino-int4-npu/` as-is.
- **ADR-011** (All LLM Inference on GPU — NPU Retirement) retired the NPU for *all* LLM inference. This is where Qwen2.5-1.5B/NPU stopped being served. Its NPU latency baseline was recorded as **invalidated** (`phase2_gates/evidence/p5_task4_1_adr_addendum.json:13` — `"replaces": "ADR-010 §3.2 — 125ms P95 (Qwen2.5-1.5B/NPU — invalidated)"`).
- **ADR-012** selected **Qwen3-14B** (GPU, INT4) as the single served model for PA + AO, with **qwen3-0.6b-pruned-6l** (INT8, GPU) as the speculative-decoding draft.

`shared/constants.py:143` records the outcome: *"Qwen2.5-1.5B demoted to legacy reference."* The served set today is exactly `{ Qwen3-14B, qwen3-0.6b-pruned-6l draft }` — Qwen2.5-1.5B is in neither.

## 2. Served-vs-unserved evidence (strongest first)

| Evidence | File:line | Meaning |
|---|---|---|
| `services/` has **zero** references to the qwen2.5-1.5b **model** | (grep for `qwen2.5-1.5b` / `qwen2_5-1.5b`, no matches) | No runtime service loads or serves the model. |
| `launcher/` has **zero** references to the model | (grep, no matches) | The launcher's model-load/boot path does not preload it. (`launcher/` "fallback" hits are all parse/topology fallbacks, not model fallbacks.) |

> **Naive-grep caveat — chat-template label vs. model.** A bare `grep -ri qwen2.5 services/` returns two *source* hits — `services/policy_agent/src/gpu_inference.py:325,327` ("Build the full classification prompt in Qwen2.5 chat format" / "Uses the Qwen2.5 chat template") plus their tests `services/policy_agent/tests/test_gpu_inference.py:125,146`. These are **not** a reference to the qwen2.5-1.5b *model*: they name the **Qwen2.5 ChatML chat-template convention** (`<|im_start|>` / `<|im_end|>` roles), which the Qwen2.5 and Qwen3 families share. That code path builds the prompt for the **served Qwen3-14B** on the GPU, not for qwen2.5-1.5b. (`__pycache__/*.pyc` binary matches are stale compiled bytecode, not tracked source.) So the "served by nothing" finding holds: there is no reference to the *model* in `services/`, only to a format label shared with Qwen3.
| Served-model constants name only 14B + the 0.6b draft | `shared/constants.py:146` (`TARGET_MODEL = "Qwen3-14B"`), `:158` (`TARGET_MODEL_OV_PATH = "models/qwen3-14b/openvino-int4-gpu"`), `:161` (`DRAFT_MODEL_OV_PATH = "models/qwen3-0.6b-pruned-6l/openvino-int8-gpu"`) | The served/draft paths never point at qwen2.5-1.5b. |
| Signing stager's served set excludes it by name | `shared/models/stage_production_manifest.py:62` — *"and qwen2.5-1.5b (not a served model at all)"*; `_DRAFT_MODEL_DIRS` (`:63-65`) contains only the pruned-6l draft | #107 correctly excluded it from the signing set (signing it would wire a verify path to nothing). |
| Signing-key provisioner excludes it by name | `shared/security/provision_manifest_signing_key.py:92` — *"qwen2.5-1.5b — not a served model at all (only phase2_gates/ + dev scripts)"*; `DRAFT_MANIFEST_PATHS` (`:93-95`) contains only the pruned-6l manifest | Same #107 exclusion, on the key-provisioning side. |
| Regression lock enforces the exclusion | `shared/tests/test_draft_manifest_signing.py:308-311` — asserts the no-arg ceremony's served set = 14B + the one enforced draft, and *"the non-served qwen2.5-1.5b must NOT be signed, since no code verifies them"* | Structural control (a test) keeps qwen2.5-1.5b out of the signing set permanently. |
| No runtime code imports the dev scripts | grep for `import ... (export_qwen25_npu\|smoke_npu_genai\|benchmark_npu_latency)` / `from scripts` → no runtime importers | The dev scripts are entry-point tools, not a runtime dependency. |

**Conclusion:** the served set is `{ Qwen3-14B, qwen3-0.6b-pruned-6l }`. Qwen2.5-1.5B is served by nothing. The #107 exclusion was correct.

## 3. Full reference inventory (every hit, classified)

### A. Runtime code (`shared/`) — comments + regression lock, all load-bearing → RETAIN
- `shared/constants.py:143` — legacy-reference note in the ADR-012 model-spec block. Accurate historical context.
- `shared/models/stage_production_manifest.py:62` — #107 exclusion rationale (why the stager does not stage it).
- `shared/security/provision_manifest_signing_key.py:92` — #107 exclusion rationale (why the provisioner does not sign it).
- `shared/tests/test_draft_manifest_signing.py:308-311` — the **regression lock** that structurally keeps it out of the signing set.

### B. Dev scripts (`scripts/`) — NPU-feasibility harness, not runtime-imported → RETAIN
- `scripts/export_qwen25_npu_model.py` — exports `Qwen/Qwen2.5-1.5B-Instruct` to OpenVINO INT4-MIXED for NPU (lines 2,4,24,47,48,62).
- `scripts/smoke_npu_genai.py` — NPU smoke test via OpenVINO GenAI `LLMPipeline` (lines 2,6,26,60,65,133,153,305).
- `scripts/benchmark_npu_latency.py` — NPU PA-classification latency benchmark (lines 66,525).
- All last touched **2026-02-24** (the ADR-010 commit `fdfbf925`) — stable historical artifacts, not churning.

### C. Feasibility gates + evidence (`phase2_gates/`) — P5 evidence of the NPU investigation → RETAIN
- Scripts: `phase2_gates/scripts/run_p5_feasibility_002.py` (`:38,:859`), `run_p5_feasibility_003.py` (`:28,:560`), `run_p5_feasibility_004.py` (`:34,:171,:367,:448,:455`).
- Evidence JSONs (community-grade performance data): `npu_latency_benchmark.json`, `p5_input_length_latency_matrix.json`, `p5_memory_pressure_matrix.json`, `p5_multi_device_capability_matrix.json`, `p5_output_length_latency_matrix.json`, `p5_pgov_stage5_long_output_coverage.json`, `p5_redecision_protocol.json`, `p5_pa_long_input_stability.json`, `p5_runtime_ceiling_*` (4 files), `p5_task4_1_adr_addendum.json` (records the invalidated baseline).

### D. Decision record / documentation (`docs/`, ADRs, root) — historical → RETAIN
- ADRs: `ADR-010` (superseded — the model's served era), `ADR-011` (NPU retirement), `ADR-012` (Qwen3-14B selection).
- Feasibility + reports: `docs/NPU_SMOKE_TEST_REPORT.md`, `docs/FEASIBILITY_*`, `docs/GAP_TO_OPERATIONAL_REPORT.md`, `docs/UAT-2_ACCEPTANCE_PLAN.md`, `docs/P5_*` prompts, `docs/Task4.1_ADR_Addendum_Summary.md`, `docs/P5_TASK5_MODEL_UPGRADE_PLAN.md`.
- Governance / maps / plan: `docs/governance/{README,weight-integrity,gpu-runtime,error-recovery}.md`, `docs/security/DATA_MAP.md`, `docs/IMPLEMENTATION_PLAN.md`, `docs/POST_OPERATIONAL_MATURATION_LEDGER.md`, `docs/ledger/…sprint9_ea4…md`, `Use Cases_FINAL.md`, `.github/copilot-instructions.md`, sprint_9 reports.

None of D is code; none of C/D is runtime-reachable.

### NOT a reference to the model (excluded from the inventory — format label, not a model)
`services/policy_agent/src/gpu_inference.py:325,327` and `services/policy_agent/tests/test_gpu_inference.py:125,146` mention "Qwen2.5 chat format / chat template". These name the **Qwen2.5 ChatML template convention** (shared with Qwen3), used to build prompts for the **served Qwen3-14B** — they do **not** reference or load the qwen2.5-1.5b model, so they are not counted above. Listed here only so a naive `grep -ri qwen2.5 services/` does not appear to contradict the "served by nothing" finding.

## 4. Decision

**RETAIN. No code references removed.** Rationale:

1. **The runtime-code references are load-bearing, not dead code.** The `shared/` signing-path comments are the #107/#917 exclusion rationale — they document *why* an integrity-verified system deliberately does not sign this model. Removing them would re-introduce the exact "why isn't qwen2.5-1.5b in the signed set?" ambiguity that #107 resolved. The `test_draft_manifest_signing.py` assertion is the *structural control* that enforces the exclusion — removing it would remove the guard.
2. **The dev/feasibility artifacts are the documented journey, not superseded dead code.** The scripts + `phase2_gates` evidence + ADR-010/011 are the reproducible harness and community-grade performance data of the NPU LLM-inference feasibility study that produced the GPU-only decision. They are not broken, not misleading, and not replaced by a newer script; they are the evidence trail for a real, concluded investigation. Scrubbing them would erase why the GPU-only architecture was chosen.
3. **Nothing is dead *code*.** There is no broken import, no stale served-config entry pointing at a phantom model, no unreachable branch. Every reference is either an intentional exclusion, a regression lock, or historical evidence/decision record.

"Dead weight" is therefore true only in the narrow physical-disk sense (§5), not in the code sense.

## 5. Follow-up (optional; LA's call — destructive operator step)

The physical weights at `models/qwen2.5-1.5b-instruct/openvino-int4-npu/` are present on disk (~1.05 GB — `openvino_model.bin` ≈ 1.02 GB plus tokenizers, a `manifest.json`, and a `.npucache/`). They are **gitignored**; deleting them is a destructive filesystem operation and thus the LA's decision, not an autonomous one.

- **Value of keeping:** it is the reproduction target for the NPU-feasibility harness (§3.B) and the ADR-010/011 evidence baseline. If NPU LLM inference is ever revisited (new OpenVINO NPU driver / new candidate), the export → smoke → benchmark loop runs against it directly.
- **Value of deleting:** reclaims ~1.05 GB on the 32 GB-class dev/prod machine.
- **Recommendation:** LOW-urgency disk reclaim. Leave to the LA; if he wants the space, it is a one-line manual `rm -r` of the gitignored directory. No code change is needed either way — nothing serves it, and the signing set already excludes it.

### Noted, not fixed — a micro-nit outside this ticket's scope
`shared/constants.py:143` reads *"Draft model under evaluation."* That is stale — the speculative-decoding draft (`qwen3-0.6b-pruned-6l`) is **locked/selected** (see `DRAFT_MODEL_OV_PATH` docstring, `constants.py:161-168`, "Selected 2026-05-22"). This concerns the *draft* model, not qwen2.5-1.5b, so it is out of #916's scope and left untouched here to keep this a docs-only disposition. Flagged for a future one-line comment tidy if a session is already editing `constants.py`.

## 6. Change summary

Docs-only. This disposition doc + a journal fragment. No source/config/test changed, so the standing gate is unaffected (pytest does not collect `docs/`). Nothing imports this doc.
