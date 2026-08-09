---
title: "P1-S1 source harvest + outline — Co-residency on one 32 GB Lunar Lake box"
status: outline-only (NOT a draft) — stretch deliverable of the S4 author dispatch
area: research
piece: P1-S1
prepared: 2026-07-19
harvest_verified_against: worktree at c4eff36f (committed state only)
---

# S1 — Co-residency on one 32 GB Lunar Lake box: harvest + outline

Per P1-verdict §2.1 and §3: S1 is the series flagship — "multi-model co-residency
telemetry on one shared-memory Lunar Lake box" is genuine white space (the survey
found only generic fit-in-VRAM guidance and big-GPU serving literature). This file
is the source harvest and structural outline for the S1 author pass. It is NOT a
draft; every number below re-derives from the named artifact before print.

## 0. Coordination + status notes (read first at S1 author time)

- **`docs/performance/community_export/` staging is another session's in-flight
  work** — at harvest time (2026-07-19) the directory and its script family
  (`build_community_dataset*.py`, `scrub_community_export.py`,
  `assemble_dataset_card_2026_2_1.py`, modified `verify_community_scrub.py`,
  modified `benchmark_coresident.py`) are UNCOMMITTED untracked files in the main
  working tree. **No Vikunja ticket found** under "export"/"dataset"/"community"
  in projects 9 (BlarAI Drafts) or 11 (OSS Contributions) on 2026-07-19 — the
  work is board-untracked. S1 author: re-check commit + ticket state; coordinate;
  do not touch the staging dir; if the curated export has landed by then, cite IT
  as the dataset-of-record (it is the community-facing packaging of exactly S1's
  JSONs).
- The S4 draft (same branch) already establishes the series' framing, disclosure
  boilerplate, and mirror-citation pattern — reuse, don't re-derive.
- Publish order per ROADMAP §3: S4 first, then S1. S1 is the piece the survey
  says nobody else has written — it earns the fullest length of the series.

## 1. The claim S1 makes (from the survey verdict, binding)

Measured telemetry for a heterogeneous local stack — resident 14B LLM + INT4
draft + NPU embeddings + Whisper + on-demand SDXL/VLM — sharing ONE 31.323 GiB
unified-memory pool on consumer silicon, with:
1. the In-Use = Total − Available accounting discipline (and its honestly
   measured LIMIT — see the KV-cache null result),
2. the evict-and-lazily-reload discipline for jobs that don't fit,
3. instrumented contention mechanics (Intel UT: busy/bandwidth/power/thermal),
4. the supersession-honest verdict arc (June "not viable" inference → LA
   challenge → July measured 13 s load → gate floor moved 21→20 GB).
NOT the claim: any raw tok/s headline (saturated; S2's territory), any
generality beyond this box (n=1 framing throughout).

## 2. Source harvest (all in PERFORMANCE_LOG.md unless noted; line refs at c4eff36f)

### 2a. The core studies

| Entry | What it gives S1 | Headline numbers (re-derive before print) | Machine-readable |
|---|---|---|---|
| **2026-06-28 "What the resident 14B costs a roommate"** (L715) | THE centerpiece: 4 pairings × 3 states × N=3, Intel-UT instrumented | Idle co-residence ~free (SDXL idle tax within noise; VLM ~5.4%); contention: photoreal 0.22 tok/s (1.1% of baseline), illustration 0.19 (1.0%), cartoon 3.27 (16.8%), VLM 2.58 (13.5%); peaks 24.55–27.59 GiB vs 31.323 ceiling; mechanism: GPU busy ~99%, ZERO throttle, clock pinned ~1.95 GHz — starvation is compute scheduling, not bandwidth/thermal; mem-read DROPS under SDXL contention (~70→22 GB/s*); NPU 0.0 W in all 12 runs (pure-GPU confirmation) | `coresident_14b_pairings_hardened_2026-06-28.json` + `coresident/ut_hardened/` + `README_coresident_ut.md` (reproduce-me doc) |
| **2026-06-29 "the pattern holds"** (L453) | Version-bump robustness (2026.1.0 → 2026.2.1), N=1 confirmatory | Same shape: idle ~free; contention 0.1–2.5 tok/s; peaks 25.00–28.82 GiB; UT mechanism reproduces (99.99% busy, 66→18.9 GB/s*) | `benchmark_coresident_*_2026-06-29_*.json` + `coresident/ut_hardened/*_r1` |
| **2026-06-16 UC-010 Phase-0 memory gate** (L1242) | The build-or-no-build gate pattern: measure BEFORE building | 14B + ~3k KV + SDXL INT8 + 1024² generate peak **~26.0 GB**, headroom **~5.3 GB**; SDXL cold load 18.7 s; verdict: budget closes WITH 14B resident → build proceeded | `image_gen_phase0_2026-06-16.json` |
| **2026-06-21 M1 swap measurement** (L1164) | The eviction half: in-process release/reload proven; the three-case honest verdict | 14B release returns ~10.1 GB in ~1 s (openvino #33896 does NOT bite here); reload ~18.5–21 s coherent; 30B standalone marginal (Available → **67 MB**, ~6 s page-storm); bare swap NOT viable from 19.9 GB ambient (20.1 < 23.1 threshold) — gate correctly ABORTED | `milestone1_14b_release_2026-06-21.json` |
| **2026-07-09 swap-gate floor (#777)** (L2264) | The supersession arc's resolution + a governance beat: the LA challenged the untested inference | 30B load from a PINNED 19.85 GiB ambient: READY ~13 s, NO page storm, Available floor 4.6 GiB; gate floor lowered 21→20 GB in lockstep across 3 configs | `swap_gate_floor_2026-07-09/` |
| **2026-07-10 probe-not-predict (#784)** (L2286) | Probe-over-predict doctrine live; the co-resident-load contrast number | Clean path: 30B READY 15.5 s after stopping the 14B; co-resident artifact arm: 34.8 s (~2.2× cost of loading beside the resident 14B); below-floor backstop proven (9.8 < 15.0 → abort, nothing touched) | `probe_livecheck_2026-07-10.json` |
| **2026-07-10 coder-in-VM feasibility** (L2316) | The envelope's outer edge: 30B + 6 GB VM under the ceiling | 30B alone lean: In-Use 22.03 GiB (~14.9 GiB footprint); + static 6 GB VM: peak 27.5 GiB, FITS (headroom 3.82 GiB; ~5.8 lean-adjusted) | `coder_in_vm_memory_2026-07-10.json` |

### 2b. Supporting measurements

| Entry | Contribution | Numbers |
|---|---|---|
| 2026-06-14 voice RAM (#660) (L1288) | On-demand load/unload reclaim halves; co-resident-with-14B column was PENDING at entry time — CHECK for the later completion before citing | `voice_ram_2026-06-14_*.json` |
| 2026-06-24 Playground v2.5 footprint (L1076) | Delta-isolation method: footprint measured WITH a co-resident 30B (+8.16 GB load; 8.42 GB peak) — honest caveat pattern | `playground-v2.5-int8-arc140v-2026-06-24.json` (in main tree — verify committed state at author time) |
| 2026-06-29 KV-cache precision sweep (L543) | **The honest null that bounds the accounting method**: {FP16,u8,u4}×{16K,32K} peak host In-Use FLAT at ~20.85 GB — host Available CANNOT resolve the GPU pool on unified memory → "INT4-KV frees RAM" is UNCONFIRMED | `kv_cache_sweep_*.json` |
| 2026-07-06 OVMS compile cache (#747) (L159) | Swap-cost mitigation: coder load 289 s cold → **12 s warm** (~16 GB .cl_cache); why the evict/reload discipline is affordable | `ovms_compile_cache_coder30b_2026-07-06.json` |
| 2026-06-24 dispatch swap telemetry (L1109) | The no-OOM mechanism corroborated on a live dispatch | `dispatch_swap_telemetry_2026-06-24.json` |
| 2026-07-15 RAM census | Whole-box accounting snapshot | `ram_census_2026-07-15.json` (verify content before use) |

### 2c. Narrative beats (journal; quote verbatim only)

- **docs/archive/journal/2026-06.md** — the co-residency arc's failures (S1 must
  keep them; sanitized posts don't compound): the VLM co-resident host FREEZE and
  its unload-in-finally fix ("an unbounded deferred risk does not wait politely;
  it comes due as a hard freeze, not a graceful degrade" — L375 region); the
  hires-refine OOM cascade → hires evicts-the-14B by design (ADR-033 Am.2;
  "worse than an OOM" L7561 region); the one-model-per-phase swap-sequence
  doctrine (L9267 region). Exact titles/dates re-derived at author time.
- 2026-06-28/29 co-residency journal fragments (referenced from the log close
  blocks) — the foreground-capture-after-reaped-background story.
- The anthology (docs/BUILD_JOURNAL_ANTHOLOGY.md) — check which of these made
  the 64; cite anthology where available.

### 2d. Standing facts (VERIFIED_FACTS + CLAUDE.md host row; re-verify at draft)

31.323 GiB effective ceiling · In-Use = Total − Available doctrine · ADR-011
all-LLM-inference-on-GPU (the 12×-repeated NPU 0.0 W is its measured proof) ·
ADR-033 Am.2 hires-evicts · Shared-GPU override ~87% (~27 GB window, 06-21 entry)
· forbidden pairing: image model + 30B coder = 32.5 GB breach → SEAM A generates
pre-swap (L449).

## 3. Proposed structure (S1 draft)

1. **Lead: the constraint, not the chip.** One unified 31.323 GiB pool, five
   models with standing jobs, no dedicated VRAM. The question a serving cluster
   answers with hardware, answered here with discipline. (No tok/s in the lead.)
2. **The accounting rule and its measured limit.** In-Use = Total − Available;
   why working-set sums lie; the KV-sweep null as the honest boundary of what
   host-side accounting can see on unified memory (methods candor, early — it
   buys trust for everything after).
3. **Who fits beside the resident 14B (memory).** The 06-28 pairing table +
   06-16 gate spike; the forbidden pairing; cartoon-LoRA as tightest fit.
4. **What co-residence costs (throughput + mechanism).** Idle ~free vs
   contention collapse; the UT mechanism story (occupancy, not bandwidth/thermal;
   zero throttle; the bandwidth DROP under compute-bound contention); partner
   taxonomy (diffusion vs bandwidth-bound transformer vs CPU-assisted LoRA).
   Bandwidth-unit caveat carried verbatim (GB/s inferred, UNCONFIRMED).
5. **When it doesn't fit: evict and lazily reload.** The freeze and OOM-cascade
   failures that minted the discipline; release/reload numbers (10.1 GB back in
   ~1 s; reload ~18.5–21 s); the compile-cache mitigation (289→12 s); the VM
   envelope as the outer edge.
6. **The verdict that had to be corrected.** June's "bare swap not viable"
   (gate-declined inference) → the LA's challenge ("no load below 23.1 was ever
   TESTED") → July's measured 13 s load from 19.85 GiB → floor 21→20. The
   series' supersession-honesty thread as a lived example, and a non-technical
   reviewer catching an untested inference.
7. **Methods** (§H community-grade): both study configs (2026.1.0 N=3 study;
   2026.2.1 N=1 refresh), UT instrumentation + the clock-remap caveat, prompt/
   probe design, ceilings/overrides; **what was NOT measured** (steady-state
   LoRA contention; bandwidth unit; N; co-residence during voice/VLM+generate;
   GPU-allocation-level memory).
8. **Prior work** (§H): vLLM/serving colocation + KVQuant-class work = different
   world (big-GPU, dedicated VRAM); consumer-side prior art (B/C/D/E per the
   verdict) never co-resides models; NITRO/NPU-LLM work is the opposite split.
   What S1 adds: the measured multi-tenant discipline on one consumer iGPU.
9. **n=1 framing + disclosure boilerplate** (§F verbatim) + dataset links
   (mirror URLs; the community_export packaging if landed by then).

## 4. S1-specific §B hazards (author pass must clear)

1. **Version split:** the N=3 study is 2026.1.0; the refresh is 2026.2.1 (N=1).
   Never blend rows across versions without labeling; the throughput baselines
   differ slightly (19.1–19.8 vs 17.7–19.0 tok/s).
2. **Bandwidth unit UNCONFIRMED** (`GPU_MEMORY_BYTE_*_RATE` unit N/A) — carry
   the asterisk exactly as the log does; open follow-up #2 in the 06-28 entry.
3. **Cartoon's 16.8% is partly a spin-up artifact** (fixed 15 s window) — the
   log says so; print the caveat with the number, or drop the pairing.
4. **The 06-21 "not viable" verdict is SUPERSEDED in scope** by #777 (2026-07-09)
   on the newer substrate + warm cache — trap 3 (superseded figures) applies
   directly; the draft must present the arc, never the June verdict alone.
5. **The 23.1 GiB threshold was an observed-minimum on the OLD substrate**, not
   a law — #777 measured success from 19.85 GiB with a WARM compile cache;
   cold-cache from ~20 GiB remains NOT measured (named).
6. **Idle-state pp figure in the 06-28 dataset is cache-warm** — not a clean
   prefill measure (log's own caveat); don't cite it as prefill.
7. **Voice co-resident column was PENDING at the 06-14 entry** — verify whether
   the LA's step-2 measurement ever landed before citing any voice number.
8. **Privacy screen:** UT captures + JSONs may embed local paths in metadata —
   screen the cited JSON fields (the community_export scrub pipeline exists for
   exactly this; another reason to prefer the curated export if landed).

## 5. Open items the S1 author should resolve

- Whether the steady-state cartoon re-run and bandwidth-unit confirmation
  (06-28 follow-ups 1–2) have happened by author time — grep the log after
  2026-07-19 before writing "open follow-up."
- community_export landed? → cite the curated dataset + its card as primary.
- Which co-residency journal entries made the anthology (citation preference:
  anthology > archive volume).
- Whether ram_census_2026-07-15.json adds a whole-box table worth printing.
- Length/venue: S1 is the flagship long-form for home base; HF community blog
  is the strongest syndication candidate (the Neural-Hacker NPU post proves the
  register lands there) — but venue actions remain LA-ceremony-gated per piece.
