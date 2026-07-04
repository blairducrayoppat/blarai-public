# Issue 34450 — Empirical Reproduction Bundle

Reproduction evidence for [openvinotoolkit/openvino#34450](https://github.com/openvinotoolkit/openvino/issues/34450)
(LLVM ABORT in `as_convolution` pass on Lunar Lake NPU compiling Qwen3-0.6B INT4
as a heterogeneous speculative-decoding draft).

## Purpose

Resolve the reproduction gap surfaced by `@diego-villalobos` on 2026-04-24:
his repro produces `StopLocationVerifierPass: Found 40 duplicated names`
while the original report shows `as_convolution` SIGABRT. We test three
export variants against an isolated subprocess harness to identify which
optimum-intel export flag(s) drive the divergence.

## Files

| File | Purpose | Committed? |
|---|---|---|
| `repro_npu_draft.py` | Subprocess-isolated harness. Constructs `LLMPipeline(GPU, draft=NPU)` against a given draft path. SIGABRT-safe (parent process survives child abort). | yes |
| `export_variants.py` | Driver that runs the three `optimum-cli export openvino` variants (Cells B and C) into `exports/<cell>/`, captures full stderr/stdout. | yes |
| `run_matrix.py` | Top-level orchestrator. Runs Cell A (existing artifact), then exports + runs Cells B and C. Writes one log per cell + `repro_matrix.json`. | yes |
| `repro_matrix.md` | Human-readable structured report for the GitHub comment. | yes (after run) |
| `repro_matrix.json` | Machine-readable companion (versions, sha256s, exit codes, stderr tails). | yes (after run) |
| `cell_*_export.log` | Full optimum-cli output per cell. | yes (after run) |
| `cell_*_crash.log` | Full subprocess stderr per cell. | yes (after run) |
| `exports/` | Exported OpenVINO IR artifacts for cells B and C (~1.1 GB). | NO (gitignored) |

## Cells

| Cell | Export `--task` | Export `--disable-stateful` | Hypothesis |
|---|---|---|---|
| A | n/a (existing on-disk artifact at `models/qwen3-0.6b/openvino-int4-npu/`) | n/a | Original SIGABRT reproduces deterministically. |
| B | `text-generation-with-past` | no | Tests whether `--task` flag alone changes anything (existing export was implicit `text-generation-with-past`, so we expect Cell B ≡ Cell A byte-for-byte). |
| C | `text-generation-with-past` | yes | Stateless export; tests whether disabling state folding produces diego's `StopLocationVerifierPass` failure. |

OV 2026.1.0 (Cell D) is **deferred** — would require a separate venv and is
disruptive to in-flight work; not required to resolve the reproduction gap.

## Provenance

- Host: Intel Core Ultra 7 258V (Lunar Lake), Arc 140V, 32 GB LPDDR5X-8533
- OS: Windows 11 Pro Build 26200
- NPU driver: 32.0.100.4514 (2025-12-17)
- OpenVINO: 2026.0.0-20965-c6d6a13a886-releases/2026/0
- OpenVINO GenAI: 2026.0.0.0-2820-dab5b993a38
- optimum-intel: 1.27.0.dev0+d8864c45
- Python venv: `.venv` at repo root

All numbers are populated automatically from `repro_matrix.json` after the
matrix runs. Do not hand-edit; re-run `run_matrix.py` to refresh.
