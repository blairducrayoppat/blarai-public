# CACHE_DIR empirical probe — 2026-06-03

Raw evidence for the GPU compile-cache (`CACHE_DIR`) cold/warm load-time + output
numeric-identity measurement. Re-opens the `CACHE_DIR=""` governance choice
(`docs/governance/gpu-runtime.md:99-102`) per the voice handoff §7.1 / Vikunja
#545. **Narrative + headline table: see the `2026-06-03` entry in the repo-root
`PERFORMANCE_LOG.md`.**

## Conditions
AC power, standalone PowerShell (VS Code closed). Intel Arc 140V (Xe2) iGPU,
shared LPDDR5X (31.3 GB effective). openvino 2026.1.0, openvino-genai 2026.1.0.0.

## Method
Five fresh-process builds of the production shared pipeline (Qwen3-14B INT4
target + Qwen3-0.6B-pruned-6L INT8 draft), compile config mirrored exactly from
`shared/inference/shared_pipeline.py` (LATENCY / f16 / SDPA ON / MODEL_PRIORITY=
HIGH, scheduler cache_size=3 + prefix_caching=True, spec-decode
num_assistant_tokens=3). The **only** variable across runs is `CACHE_DIR`
(`prod*` = `""`; `cold`/`warm*` = a throwaway temp dir). Greedy generation
(`do_sample=False`), 3 fixed prompts, 128 max new tokens. Each run is a separate
OS process so cold/warm load timing is not contaminated by in-process warm state.

## Files
- `cache_probe.py` — the harness (run/compare subcommands). Was executed from
  `userdata/_cache_probe/`; its `REPO_ROOT` resolves via `parents[2]`, so to
  reproduce, run it from a path two levels under the repo root (or adjust).
- `run_all.sh` — driver: 5 runs + compare.
- `run_{prod1,prod2,cold,warm1,warm2}.json` — per-run results (load time, per-
  prompt output text, SHA-256, generation time, cache-blob size).
- `_verdict.json` — machine-readable comparison (identity booleans + load means).

## Result (one line)
Output is **byte-identical** across all 5 runs (fresh compile == warm cache);
the warm cache yields **no reliable startup win** on this hardware (fresh 14B
compile \~11 s ≈ cold-disk 9 GB blob read) at a one-time +42 s write + 9.0 GB
disk cost. Recommendation on record: keep `CACHE_DIR=""`, correct the
gpu-runtime.md rationale. Decision pending (User-Operator).
