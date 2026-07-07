# `docs/performance/_invalid/` — quarantined performance runs

Performance JSON in this directory is **methodologically invalid** and **must
not** be published to the OpenVINO / Hugging Face community dataset, cited as a
result, or fed to `scripts/build_community_dataset.py`.

## Why this directory exists

`docs/performance/` is the source-of-truth for community-grade benchmark data.
A run that turns out to be mis-measured (bad harness config, blind instrument,
non-comparable methodology) is **quarantined here rather than deleted** — the
project's testing-data discipline values "name what is NOT measured," and the
record of *how* a measurement went wrong is portfolio- and methodology-valuable.
Deleting it would lose the audit trail.

## Quarantine convention (two layers, defense-in-depth)

1. **In-file marker** — every quarantined JSON carries a top-level `"validity"`
   block (`status: "INVALID"`, `do_not_publish: true`, `reason`,
   `superseded_by`). This travels with the file even if it is copied out of this
   directory. The block is the ONLY addition; all original measured fields are
   preserved byte-for-byte so the run stays auditable.
2. **Directory isolation** — the leading-underscore directory name keeps these
   files out of the default "good source JSON" location and out of any
   `docs/performance/*.json` glob.

`scripts/build_community_dataset.py` reads an explicit hardcoded allowlist of
source files, so it never touches this directory — but the marker + isolation
also protect against a future glob-based harvester or a human browsing for data.

## How to clear an entry

Fix the harness, re-run, capture the corrected run to `docs/performance/`
(+ `PERFORMANCE_LOG.md`) per the standing methodology, then leave the
quarantined original in place referencing the superseding run.

## Current contents

- `kv_cache_sweep_2026-06-29_13-11-56.json` — long-context (16K/32K) KV-precision
  sweep. `cache_size=3` KV starvation produced pathological TTFT (310s @ 32K) and
  the host-RAM instrument was blind to the GPU KV pool (flat \~20.85 GB).
  Superseded by **Vikunja #709** (harness fix + GPU-mem instrumentation).
