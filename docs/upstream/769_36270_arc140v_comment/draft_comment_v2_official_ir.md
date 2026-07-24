# POSTED 2026-07-16 (LA-directed) → https://github.com/openvinotoolkit/openvino/issues/36270#issuecomment-4998835192

> Supersedes the v1 caveated table (v1 carried the unofficial-IR OV-MoE cell and the
> "architecture-dependent inversion" headline — both now known wrong; v1 was never posted).
> Post from the operator's account (blairducrayoppat) after his review.
> Both arms banked (2026-07-16); reviewed by an independent pre-merge pass same evening.

---

Adding a same-box datapoint from a different silicon generation, plus a finding about IR
provenance that may matter to this thread's numbers.

**Hardware / stack:** Intel Core Ultra 7 258V (Lunar Lake), Arc 140V iGPU, 32 GB LPDDR5X,
Windows 11 Pro 26200, GPU driver 32.0.101.8826. OpenVINO GenAI 2026.2.1. llama.cpp b9957
official win-vulkan-x64 + win-sycl-x64 release binaries (SYCL zip bundles the oneAPI runtime).
Box lean for all runs (no other GPU/model workloads resident). Methodology: OV via a
VLMPipeline text-only bench (greedy, 256 new tokens, 5 runs + 2 warmup, 30 s cooldowns,
441-token prefill probe); llama.cpp via `llama-bench -ngl 99 -p 512 -n 128 -r 3`; GPU layer
placement verified in the load log (no CPU fallback on the DeltaNet ops).

**Qwen3.6-35B-A3B (the thread's model class), INT4:**

| Runtime | Artifact | Prefill (tok/s) | Decode (tok/s) | TTFT |
|---|---|---|---|---|
| OpenVINO GenAI | **OpenVINO/Qwen3.6-35B-A3B-int4-ov (official)** | **525** | **35.0** | 372 ms |
| OpenVINO GenAI | community INT4 conversion (unofficial) | 4.0 | 1.59 | 2448 ms |
| llama.cpp Vulkan | unsloth UD-IQ4_XS | 245.8 | 7.37 | — |
| llama.cpp SYCL | unsloth UD-IQ4_XS | 156.5 | 8.14 | — |

**Qwen3.6-27B (dense-hybrid), INT4 class:**

| Runtime | Artifact | Prefill (tok/s) | Decode (tok/s) |
|---|---|---|---|
| OpenVINO GenAI | OpenVINO/Qwen3.6-27B-int4-ov (official) | 219 | 3.59 |
| llama.cpp Vulkan | unsloth IQ4_NL | 50.8 | 1.49 |
| llama.cpp SYCL | unsloth IQ4_NL | 25.2 | 0.71 |

Two observations for the thread:

**1. On the MoE-ratio question (re the 2026-07-09/10 comments):** on this Xe2 iGPU the
official 35B-A3B INT4 IR appears to achieve a healthy active-parameter ratio — 35.0 tok/s
decode vs 11.1 tok/s for dense Qwen3-14B INT4 on the same box (~3.2×, roughly tracking the
~3B-active vs 14B-dense arithmetic), and in our runs it outran both llama.cpp backends here.
So whatever is suppressing MoE ratios elsewhere doesn't appear to reproduce on Arc
140V/Lunar Lake with this artifact — though this is one box and one artifact revision. Artifact detail for comparability: my copy of the official IR reports
`INT4_ASYM, ratio 1.0, group_size 64, backup INT8_SYM` in its `openvino_config.json` —
I've seen gs128 cited in this thread, so the published revision may have changed;
worth pinning the exact quantization config when comparing across reports.

**2. IR provenance can be a >20× variable — a cautionary datapoint for cross-report
comparisons:** the same 35B-A3B on the same box and OpenVINO build ran **22× slower decode
and 131× slower prefill** on a community INT4 conversion (4.0 pp / 1.59 tg) than on the
official IR. That community-IR number initially looked to us like an architecture-level
OV-MoE kernel gap and seems to have been nothing of the sort. It suggests an
OV-vs-llama.cpp comparison in this class can be dominated by which IR was benched before
backend or silicon enter the picture. A same-class MoE served daily on this box
(Coder-30B-A3B INT4 via OVMS, 38.6 tok/s median) is consistent with the official-IR figure.

`MOE_USE_MICRO_GEMM_PREFILL=0` (accuracy mode) on the official IR: no measurable cost at
this prompt scale — 540 pp / 35.8 tg vs the default arm's 525 / 35.0 (within run-to-run
noise; the second arm ran with a warm page cache). On a same-class Coder-30B-A3B at 2.2K
context we previously measured ~19% gen / ~28% TTFT cost for this flag, so the cost appears
to be context-scale-dependent; the probe here is 441 tokens.

**Not measured / caveats:** quantization parity is approximate (GGUF IQ4/UD-IQ4 vs OV
INT4_ASYM g64 are closest analogs, not identical); rows were measured on the same box/driver
on different dates — 27B OV 2026-07-08, all llama.cpp rows 2026-07-10, 35B OV official-IR
2026-07-16; no flash-attn variants on llama.cpp (Intel-iGPU stability default);
single-evening thermal envelopes; the 35B numbers are text-only (the official IR is a
multimodal export; vision path not benched).

---

## Internal notes (strip before posting)

- Evidence: `docs/performance/benchmark_vlm_text_qwen36-35b-a3b-int4-ov-OFFICIAL_2026-07-16_18-22-59.json`
  (+ arm B JSON), `docs/performance/llamacpp_vs_openvino_769_2026-07-10.json`,
  `docs/performance/benchmark_ovms_coder-30b_2026-06-29_13-29-30.json`.
- The July-10 "symmetric architecture-dependent inversion" headline is DEAD — do not reuse it
  anywhere. The corrected headline: "official-IR OV leads on both architectures on this box;
  IR provenance is a >20× variable."
- genai #3937 note for the companion draft: the official 35B IR also emits untagged visible
  thinking under greedy defaults (observed in this run's coherence texts) — the /no_think
  blocker class applies to the official artifact too; the llama-server probe (leg 4) isolates
  backend-dependence.
- Engagement-first: this is a comment on the existing issue thread, not a new issue.
- Thread state at draft time (API-checked 2026-07-16): latest comments are PlanteAmigor
  2026-07-09/10 (285H iGPU + Arc Pro B60 data; claim that only Qwen3-30B-A3B and GPT-OSS-20B
  achieve expected MoE throughput ratios — our datapoint engages this directly);
  diego-villalobos (Intel) 2026-07-06 gave a layer-count analysis; the LA (blairducrayoppat)
  already posted the 27B dense numbers 2026-07-08, so this is a follow-up from the same
  account. The thread's own 35B numbers were measured on the OFFICIAL org IR (cited gs128
  there vs g64 in our copy — revision pinning matters; raised in the public body).
- The 14B 11.1 tok/s figure used for the ratio sentence is the LA's own 2026-07-08 post in
  this thread (same box) — consistent sourcing.
