---
ledger_id: 20260604_184221_iss1-spec-decode-closure
date: 2026-06-04
sprint_id: null
entry_type: OTHER
predecessor: Entry 52
branch: feat/multimodal-responsiveness
merge_commit: b699ad1
disposition: COMPLETE
---

# ISS-1 (AO Speculative Decoding) — Closure Record

## Summary

ISS-1 was logged in the monolithic ledger (Entry-52 era issues table) as
*"AO speculative decoding fails — `num_assistant_tokens` not supported"*,
MEDIUM severity. It was carried as an open issue through every subsequent
SWAGR (Sprints 8, 9, 10, 11, and the ISS-2 sprint) and in both CLAUDE.md
and `.github/copilot-instructions.md`.

The underlying defect was fixed on **2026-05-21** by commit `b699ad1`
("Fix speculative decoding — it now actually engages (\~2x throughput)"),
which is on `main`. The issue-tracking layer was never reconciled because
the last SWAGR to list ISS-1 (the ISS-2 sprint, signed off **2026-05-20
09:08**) predated the fix by \~38 hours. This entry is the formal closure
record; the doctrine files are updated to match in the same change.

## Root cause and fix

Speculative decoding was silently disabled at runtime: the config requested
it, but the GenAI pipeline rejected one construction property and fell back
to standard autoregressive decoding on every load.

The offending property was `num_assistant_tokens`. It was being passed as a
**pipeline-construction / GPU-plugin** property, where the GPU plugin rejects
it ("Option not found: num_assistant_tokens") and aborts the speculative
pipeline. It is in fact a **per-request `GenerationConfig`** parameter.
Commit `b699ad1` moved it into `_build_generation_config()` (applied
per-request), leaving the draft model wired at construction via
`ov_genai.draft_model(...)`. With that one move, speculative decoding
engages.

`gpu_inference.py` now carries the root-cause explanation inline as a NOTE
comment at the construction site, so the trap is documented where the next
reader would otherwise re-introduce it.

## Verification

- **Functional**: `speculative_decoding_active` reflects the *achieved*
  state (True only when the draft pipeline actually initialises), not the
  requested state — so a silent fallback can no longer masquerade as success.
- **Performance**: \~2x throughput reported at fix time (BUILD_JOURNAL.md
  entry "Speculative decoding now actually works"). Benchmark artifacts under
  `docs/performance/benchmark_2026-05-22_*.json`.

## Production configuration (current)

`services/assistant_orchestrator/config/default.toml` (and
`guest_runtime.toml`):

```toml
draft_model_dir = "models/qwen3-0.6b-pruned-6l/openvino-int8-gpu"  # pruned 6-layer INT8 draft (chosen 2026-05-22)
speculative_decoding_enabled = true                                # ADR-012 §2.6
```

The draft was subsequently tuned: commit `e851405` (2026-05-22) added a
configurable draft device and prefix caching; the draft model itself was
moved to a 6-layer-pruned INT8 GPU build on 2026-05-22.

## Files changed (this closure)

- `CLAUDE.md` — moved ISS-1 out of the open-issues line to RESOLVED with
  commit + date + closure pointer.
- `.github/copilot-instructions.md` — same reconciliation in the Task 5
  deferred-issues note.
- `docs/ledger/20260604_184221_iss1-spec-decode-closure.md` — this record.

## Notes

- The frozen monolithic ledger (`docs/POST_OPERATIONAL_MATURATION_LEDGER.md`,
  Entry 52) still lists ISS-1 in its issues table. That file is frozen and
  is a historical snapshot — correct as of its freeze date — so it is left
  unchanged; this entry supersedes it.
- ADR-012's speculative-decoding mandate is therefore satisfied in
  production. Any future model swap (e.g. a Qwen3-VL or Ministral-class
  replacement) must re-establish an equivalent draft or EAGLE-style
  spec-decode path to preserve this latency profile.
