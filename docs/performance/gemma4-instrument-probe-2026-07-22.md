# Gemma 4 instrument probe — measured, 2026-07-22 (#1005)

**Plain summary: Gemma 4 runs here today, on the GPU, with no Intel ticket and no conversion
work — but only on the GPU. The CPU path, which the ticket assumed would be the easy fallback,
is the one that is broken.**

Machine-readable record: `gemma4-instrument-probe-2026-07-22.json`.

## Verdict

**YES — Gemma 4 runs on this box, on the Arc 140V GPU, via `openvino_genai.VLMPipeline`
loading a pre-converted INT4 IR straight from Hugging Face.** No Intel ticket, no custom
export, no `optimum-intel` branch, nothing installed into the runtime `.venv`.

Recommended instrument: **`OpenVINO/gemma-4-E4B-it-int4-ov`**.

| | E2B INT4 | E4B INT4 |
|---|---|---|
| On disk | 4.06 GB | 6.02 GB |
| Load (GPU) | 8.1 s | 14.9 s |
| Steady RAM added | **+4.52 GB** | **+6.62 GB** |
| Transient peak added | +7.98 GB | **+11.74 GB** |
| Residual after evict | 0.76 GB | 0.79 GB |
| Throughput | 31.0 tok/s | 18.1 tok/s |
| TTFT | 733 ms | 768 ms |
| Greedy determinism | 3/3 identical | 3/3 identical |
| Real jury rubric | 6/6 parse, 6/6 det. | 6/6 parse, 6/6 det. |
| Judgment quality | noisy | **correct** |

## The inversion

The ticket set a deliberately low bar — "CPU-only at low throughput is a PASS." The measured
reality is the opposite of what that anticipated:

- **GPU: correct and deterministic.** 3/3 byte-identical greedy runs, clean JSON, natural stop.
- **CPU: corrupt and non-deterministic.** Three identical greedy runs produced *two distinct
  outputs*; two of them emitted 2 characters while burning the full 120-token budget. The
  tokenizer round-trips cleanly on the same pipeline, so this is the model emitting garbage
  token IDs under the CPU plugin, not a detokenizer fault.
- **NPU: does not compile.** `[NPU_VCL] Compiler returned msg: Compilation failed`.

So the ADR-011 GPU mandate turns out to be load-bearing here for a reason nobody predicted:
not latency, but *correctness*.

## RAM envelope (31.323 GB ceiling)

The number that governs is the **transient load peak**, not the steady footprint — E4B spikes
to roughly double its resting size while compiling and loading (+11.74 GB transient vs
+6.62 GB steady). Against a ~8.7 GB idle baseline that peaked at 20.5 GB, leaving ~10.8 GB
headroom on an otherwise-idle box.

**Not demonstrated:** co-residency with Qwen3-14B. The 14B was never loaded during these runs.
Evicting it first (the established SDXL / hires-refine pattern) is the indicated approach, and
the arithmetic fits comfortably — but the arithmetic is not a measurement.

## Instrument fitness

Driven through BlarAI's **real** `green_quality` jury rubric (prompt copied verbatim from
`tools/dispatch_harness/green_quality/jury.py`), E4B returned 6/6 parseable in-enum verdicts,
6/6 deterministic, and correctly discriminated a clean CLI from a deliberately defective
module. It showed lens sensitivity — different answers under the correctness vs legibility
lens on the same subject — which is what a diverse panel wants.

It also *missed* the unguarded division in the defective subject (`correctness_probe: none`
in every cell). That is a weaker grader than the 14B. Under the instrument framing that is
acceptable, and arguably the point: an independent grader needs to be *differently wrong*,
not better.
