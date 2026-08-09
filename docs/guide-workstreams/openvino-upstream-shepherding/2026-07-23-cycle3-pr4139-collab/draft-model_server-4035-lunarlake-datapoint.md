# DRAFT — model_server#4035 comment (Lunar Lake data point). Blair posts. NOT posted.

Target: https://github.com/openvinotoolkit/model_server/issues/4035
Status: draft, held. Backed by TWO fresh direct 30B captures (2026-07-23): released genai
2026.2.1 AND from-source genai 2026.4.0 dev — identical usm split. Raw:
`docs/performance/capture_4035_usm_coder30b_2026-07-23.json` (2026.2.1) and
`capture_4035_usm_coder30b_2026.4dev_2026-07-23.json` (2026.4 dev).

8< ---------------------------------------------------------------- 8<

Adding a **Lunar Lake / Arc 140V (Xe2)** data point, since the reports here are Alder Lake
(12900HK), Meteor Lake (125H), and Arrow Lake (265U) — all iGPU generations older than
Lunar Lake — and @geunhwan's note was "not supported on MTL and former generations," so a
newer-generation part (not the latest silicon — that's Panther Lake / Xe3 — but newer than
every box reported here) seemed worth checking.

**Short version:** the exact model here (`Qwen3-Coder-30B-A3B-Instruct-int4-ov`) loads and
serves fine on this iGPU; the weights land in the shared host pool with `usm_device` at
**zero**; and I get the *same* allocation on both a released **2026.2.1** stack and a
from-source **2026.4.0 dev** build — so on this hardware it's version-stable. The ~2× RAM
fill you're seeing appears to be a transient, load-dependent spike during load rather than a
persistent second copy of the weights — the steady state is a single copy.

**Hardware / how measured:**
- Intel Core Ultra 7 258V (Lunar Lake), Arc 140V iGPU (Xe2), 32 GB unified LPDDR5X
  (~31.3 GiB effective), Windows 11.
- In production I serve this model via OVMS `--target_device GPU` (20/20 generations,
  0 errors, ~30.5 tok/s).
- For the memory breakdown I loaded the same model on GPU via OpenVINO GenAI (the backend
  OVMS runs on) and read `GPU_MEMORY_STATISTICS` directly, on **two stacks**: released
  **2026.2.1** and a from-source **2026.4.0 dev** build.

**Where the weights land (GPU_MEMORY_STATISTICS, direct on the 30B — identical on both stacks):**
- `usm_host` = **15.06 GiB** (the ~16 GB of int4 weights), `usm_device` = **0.00 GiB**,
  `cl_mem` = 0. The weights resolve to the **shared host pool**; nothing lands on a
  device-local pool — which is why the `[CL ext] Can not allocate ... for USM Device`
  failure in the OP doesn't fire here. A single steady copy, not a persistent 2×. This was
  the same on 2026.2.1 and 2026.4 dev (`usm_host` identical to ~15.06 GiB, within ~0.3 MB),
  so it isn't a version artifact on this part.

**The transient spike is large but variable — not a persistent second copy.** Sampling system
RAM through the load, one load spiked system RAM ~10 GiB above the steady footprint — on a
31 GiB box that pushed available RAM close to exhaustion — while another went essentially
straight to the single ~15 GiB copy with no meaningful spike. (I didn't fully isolate why it
varied — cache/compile state, version, and session memory pressure all differed between the
two — so I'd take the *variability* as the signal, not any single peak.) Since the steady
footprint is a single copy either way (the `usm_host` figure above), that transient looks
like one-time load/compile staging rather than a persistent doubling of the weights.

**So, possibly useful for narrowing this down:** on this newer iGPU the allocation is
single-copy and version-stable, and the RAM fill is a transient spike, not a persistent 2×.
Two things that might be worth checking on the failing ADL/MTL/ARL boxes: (1) does a
**pre-warmed `--cache_dir`** avoid the crash (in case the spike is one-time compile staging)?
and (2) is a large **pagefile-backed commit limit** enough to let the transient spill instead
of OOM-killing OVMS? If either helps, it's a usable mitigation today; if neither does, the
device-side `usm_device` allocation path may genuinely differ on the older iGPUs. Happy to
run whatever would help tell those apart on this hardware.

---
*AI assistance disclosure: measurements gathered on the stated hardware and analyzed with AI
assistance (Claude); all numbers are from real runs and were human-reviewed before posting.*

8< ---------------------------------------------------------------- 8<

## Numbers (all verified on disk, 2026-07-23)
- 2026.2.1 (released): usm_host 15.06 GiB, usm_device 0.0, steady delta 13.1 GB, transient
  peak in-use 31.32 GB / min avail 0.001 GB (COLD driver cache), load 57.3 s, gen 1.83 s.
- 2026.4.0 dev (from-source, PR #4139 branch): usm_host 15.06 GiB (matched to the byte),
  usm_device 0.0, steady delta 16.1 GB, transient peak 23.57 GB / min avail 7.75 GB (warmer
  kernel cache — no near-OOM), load 33.5 s, gen 1.55 s.
- The transient spread (31.3 GB cold vs 23.6 GB warm, same weights) is why the draft frames
  the spike as compile staging, not persistent weight doubling — honest and reproducible.
- Production OVMS 20/20 runs 0 errors / 30.5 tok/s: benchmark_ovms_coder-30b_2026-06-29.json.
- 2026.4 caveat: it's a from-source dev build of the #4139 branch (thinking-suppression
  changes touch the sampling path, NOT GPU allocation) — noted here, not load-bearing for
  the usm result. Not a true OVMS 2026.3/2026.4 (no such OVMS release exists yet).
