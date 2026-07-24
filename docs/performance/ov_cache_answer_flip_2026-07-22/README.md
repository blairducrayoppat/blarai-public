# OpenVINO `CACHE_DIR` changed a greedy model's answer — cold RIGHT, warm WRONG ×3

**Status: rescued evidence, NOT yet a filed report. One more run is needed before this is
strong enough to take upstream — see "What is missing" below.**

Measured 2026-07-22 on BlarAI's dev box. These artifacts sat in a session scratchpad — a
temp directory that gets cleaned — and were rescued into the repo the same day. Nothing has
been posted anywhere; whether this is reported upstream is the operator's decision.

## The observation

Identical model, identical device, identical image, identical prompt, **greedy decoding**
(`do_sample = False`, `max_new_tokens = 64`). The only variable is whether OpenVINO's
compiled-blob cache (`CACHE_DIR`) was populated.

| run | cache before | load | answer |
|---|---|---|---|
| `cache_cold` | 0.0 GB | 200.52 s | `{"render": "broken", "reason": "The text is overlapping with the blue header lines, and the layout is not properly spaced."}` |
| `cache_warm` | 14.279 GB | 26.40 s | `{"render": "ok", "reason": "The text is clearly legible, well-spaced … no overlapping elements"}` |
| `cache_warm2` | 14.279 GB | 24.37 s | `{"render": "ok", …}` (identical) |
| `cache_warm3` | 14.279 GB | 23.29 s | `{"render": "ok", …}` (identical) |

**The subject is `subjects/cook_broken.png` — a deliberately broken render.** Ground truth is
"broken". The cold run got it right and named the actual defect; all three warm runs got it
wrong and asserted the opposite, reproducibly.

The cache does what it is for on speed: load drops 200.52 s → ~24 s. The concern is that the
*answer* moved with it.

## Stack

- **Model:** `gemma-4-26B-A4B-it-int4-ov` (INT4), `VLMPipeline`
- **Device:** GPU — Intel Arc 140V iGPU (Xe2), driver 32.0.101.8826
- **CPU/RAM:** Intel Core Ultra 7 258V (Lunar Lake), 32 GiB LPDDR5X → 31.323 GiB visible
- **OpenVINO GenAI:** 2026.2.1.0-3123-7dea0459b2a
- **OS:** Windows 11 Pro 26200

## Reproduce

```
python cache_probe.py <model_dir> GPU <cache_dir> cold    # cache_dir empty
python cache_probe.py <model_dir> GPU <cache_dir> warm    # same cache_dir, now populated
```

`cache_probe.py` and the subject image are both in this directory, so the repro is
self-contained apart from the model weights.

## What is missing before this is contributable

Stated plainly, because the finding is only as strong as its weakest leg:

1. **The cold arm is N=1.** Three warm runs agree with each other; exactly one cold run
   disagrees with them. "Cold is stably right" is not established — a repeat cold run is the
   single highest-value addition and is cheap.
2. **One subject, one prompt.** `cook_ok.png` exists alongside the broken one and was not run
   through this probe; the control (does the cache also flip an *ok* page to broken?) is
   unmeasured.
3. **One model, one device, one runtime version.** Nothing here says whether this is specific
   to this model, to `VLMPipeline`, to Xe2, or general.
4. **This model is known to hallucinate image content.** The 2026-07-22 head-to-head record
   withdrew an earlier "trust the 26B for screenshot checking" verdict on exactly that basis.
   So a wrong answer from it is less surprising than it looks, and the cold run being right
   could itself be luck. **This is the caveat that most weakens the finding** and it must
   travel with it.
5. **Not isolated to the emission.** Cold and warm differ in load path and baseline RAM as
   well; nothing here proves the compiled blob is what changed the logits rather than some
   other cold/warm difference.

A stronger version would be: N≥3 cold and N≥3 warm, both subjects, and ideally a text-only
model to remove the vision path as a variable.

## Why this is recorded despite being incomplete

BlarAI already treats `CACHE_DIR` as unsafe on this evidence — the #1005 grading comparison
ran with no cache anywhere and says so in its own record — so the finding is *already load-
bearing internally* even though it is not yet strong enough to file upstream. An
internally-load-bearing measurement living only in a temp directory is the failure class
ticketed as #1040.

## Related

`docs/performance/cache_dir_probe_2026-06-03/` — an earlier, unrelated `CACHE_DIR` probe
(different question: whether caching reduces the load-time spike).
