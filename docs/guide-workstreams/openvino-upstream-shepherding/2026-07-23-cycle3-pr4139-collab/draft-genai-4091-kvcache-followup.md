# DRAFT — openvino.genai#4091 follow-up nudge (data-led). Blair posts. NOT posted.

Target: https://github.com/openvinotoolkit/openvino.genai/issues/4091 (Blair's own issue)
Status: draft, held. Numbers are the already-measured 2026.2.1 prefill figures from the
original filing (PERFORMANCE_LOG 2026-07-01 / kv_cache_sweep_ov2026_2_1_0_*.json). Last
activity on the issue: 2026-07-09 (Wovchena, waiting on internal arch review). Today:
2026-07-23 — a ~2-week cadence with new framing is normal, not impatient.

8< ---------------------------------------------------------------- 8<

Following up with the per-context prefill numbers behind this request, in case having the
cost quantified helps the design discussion — I know this is waiting on an architecture
review, so I'm offering data, not chasing a date.

The cost persistent KV would remove, measured on the integrated-GPU / unified-memory path
this feature most affects — **Intel Core Ultra 7 258V (Lunar Lake), Arc 140V iGPU, 32 GB
LPDDR5X**, Qwen3-14B INT4 weights on GPU, plain autoregressive, prefix cache off, OpenVINO
GenAI 2026.2.1, warm steady-state plateau, N=3 median:

| Cold prefill (fixed stable prefix) | TTFT |
|---|---|
| 16K tokens (FP16 KV) | ~46 s |
| 32K tokens (INT8 KV) | ~159 s |
| 32K tokens (FP16 KV) | ~369 s |

This is paid in full on every fresh process, because in-memory prefix caching doesn't
survive a restart — and on this box it recurs constantly: the 14B planner and a 30B coder
can't co-reside in 31.3 GB, so they swap per job, and each swap-in cold-prefills a large
byte-stable preamble. Restoring that prefix KV from a local NVMe read instead of recomputing
it would turn a minutes-long cold start into a bounded read: a few GB of KV at modern NVMe
speeds (7+ GB/s sequential) is on the order of ~1 s against the 159–369 s prefill above — a
~100–300× reduction on this hardware, and the trade is most favorable exactly on a
memory-bandwidth-bound iGPU where recompute is the expensive part.

I know the direction is still open (whether to revive #3209's `dump_dir`/`load_dir` shape or
go to a first-class savable/restorable cache object) and that it's pending an arch-review
call — so this is just to make sure the numbers are on the table for whoever makes it. And
the standing offer holds: once a design is picked, I'm happy to validate it on this Lunar
Lake / Arc 140V hardware — cold-prefill vs restore-from-disk across context lengths and KV
precisions — and publish the measured results. I build OpenVINO GenAI from source already
(I've been doing token-exact measurement on #4139 on the same box), so I can test a
prototype branch directly rather than waiting on a release.

No rush on my account — flagging the data in case it's useful for the decision.

---
*AI-assistance disclosure: measurements gathered on the stated hardware and analyzed with AI
assistance (Claude); all numbers are from real runs and were human-reviewed before posting.*

8< ---------------------------------------------------------------- 8<

## NOT FOR POSTING — notes
- Numbers are the original-filing figures (2026-07-01, OV GenAI 2026.2.1, clean
  cooldown-separated N=3). A fresh spot-check on 2026-07-23 (same model/version) measured
  32K u8 at 217 s (single-combo) / 243 s (with a cold driver-kernel cache) — i.e. the exact
  figure is thermal/methodology-sensitive but the MAGNITUDE is unchanged (still minutes).
  The original clean numbers are the right cite; do NOT swap in the higher spot-check figure.
- NVMe restore-time claim: ~1 s for a few-GB KV at 7+ GB/s is a general-hardware figure
  (matches the incoming Crucial P310: 7100 MB/s / 1M IOPS). Framed generically in the post,
  not tied to the specific drive.
- Tone follows Blair's four points: lead with data, acknowledge the arch-review wait, normal
  cadence, offer don't demand.
