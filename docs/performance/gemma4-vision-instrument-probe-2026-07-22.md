# Gemma 4 vision probe — screenshot checking, measured, 2026-07-22 (#1005)

> **SUPERSEDED IN PART — read `gemma4-vs-qwen3vl-headtohead-2026-07-22.md` first (2026-07-22, later same day).**
>
> Two headline claims in this record did not survive further measurement by their own author:
>
> 1. **"Fits by 11 MB" was the wrong framing.** The transient peak is not a fixed requirement —
>    it EXPANDS to fill available RAM (mmap page-cache behaviour). Loads starting from 6.3, 7.3
>    and 9.1 GB baselines all peaked at ~31.32 GB, and 8/8 loads succeeded, one from only 20.8 GB
>    available. The number that characterises the model is STEADY STATE (~13.3-15.2 GB), not the peak.
> 2. **"Capable" rested on a 2-subject test that could not separate discrimination from bias.**
>    On a 4-subject set (2 clean, 2 broken) the 26B ties the ~5 GB incumbent at 3/4 — and its
>    errors are FALSE ALARMS on clean pages, including hallucinating the prompt text as visible
>    image content. The per-run NUMBERS below remain valid; the judgement built on them does not.
>
> The measured RAM, latency and determinism figures in this record stand as recorded.

**Plain summary: the small model is not good enough for screenshot checking, and the model
that IS good enough fits this machine by eleven megabytes. Both facts are measured, and the
second one is the decision.**

Machine-readable record: `gemma4-vision-instrument-probe-2026-07-22.json`.
Sibling (text-grader probe, same day, earlier): `gemma4-instrument-probe-2026-07-22.json`.

## Verdict

| | E4B INT4 | 26B-A4B INT4 |
|---|---|---|
| Loads on Arc 140V | yes | yes |
| **Vision accuracy** | **3/4** | **4/4** |
| Determinism | 5/5 | 5/5, and stable across two loads |
| Steady RAM added | +6.38 GB | +13.3 to +14.6 GB |
| Transient peak added | +11.49 GB | **+22.1 to +22.8 GB** |
| **Absolute peak in-use** | ~20.5 GB | **31.312 / 31.318 GB** |
| **Headroom at peak (of 31.323)** | ~10.8 GB | **0.011 / 0.005 GB** |
| Load time | 8.9 s | 50.7 s |
| Per-question latency | 0.7–3.9 s | 1.5–4.1 s |

**E4B is not good enough.** It scored 3/4 — and the one it missed is the question that matters
most. Shown a page with its entire stylesheet stripped and its title header deleted, it
answered `"render": "ok"` and justified it: *"The text is clearly legible and appears to be a
standard, well-formatted page."* It correctly noticed the **missing title element**, so
element-presence checking works. What fails is **layout/visual regression** — and it fails by
declaring a broken render healthy. That is the unsafe direction: a checker that produces false
confidence is worse than none. It is the same direction as its text-grading miss in the sibling
record. The LA's instinct that E4B is too small is correct, and now has evidence.

**26B-A4B is good enough on capability.** 4/4, twice, byte-identical. It caught the broken page
with a specific, real observation — *"The text is overlapping with the blue header lines, and
the layout is not properly spaced."* Its description of the control image was also sharper than
E4B's. On quality it does the job.

## The multiplier did NOT hold — and it did not matter

The expectation was that the ~1.95× on-disk→transient multiplier from E2B/E4B would put a
13.6 GB model at ~26.6 GB transient and rule it out.

| Model | On disk | Transient peak delta | Multiplier |
|---|---|---|---|
| E2B | 4.062 GB | 7.977 GB | 1.964× |
| E4B | 6.016 GB | 11.740 GB | 1.951× |
| **26B-A4B** | **13.634 GB** | **22.094 GB** | **1.621×** |

The MoE model's multiplier is materially lower, so it loaded when extrapolation said it would
not. (Also worth noting: measured on-disk is **13.634 GB**, not the 14.3 GB HF metadata claimed.)

**But the absolute number is what governs, and it is brutal.** Two independent end-to-end loads
peaked at **31.312 GB** and **31.318 GB** against a **31.323 GB** ceiling, with minimum
available RAM of 12 MB and 5 MB. Measured by an external sampler so the peak survives process
death.

That is not headroom. That is total memory saturation that happened to survive, twice. It loads
because OpenVINO memory-maps weights and Windows can evict standby pages under pressure — not
because the memory exists. The 50.7 s load, against 8.9 s for E4B at ~2.3× fewer weights, is
consistent with heavy paging.

**Operationally:** this was on an already-lean box with BlarAI **down**. Nothing on the
permitted close-list was even running — there was no RAM left to reclaim. Any concurrent
consumer (the resident 14B, a browser, the WinUI app) erases the margin.

## 31B — not attempted

Three independent disqualifiers: the "26B loaded with real headroom" precondition was not met;
17.4 GB on disk extrapolates past the ceiling even before noting that a *dense* 31B should not
borrow the *MoE* multiplier; and it would breach the download cap. **The non-fit is an
extrapolation, not a measurement.**

## Honest gaps

- **No Qwen3-VL-8B head-to-head.** This says what Gemma 4 does; it does not compare it to the
  incumbent it would displace. That comparison is the real decision input and it is missing.
- **Small sample** — 4 graded questions on 2 UI subjects. A failure *shape*, not a rate.
- **The UI subjects are a rendered HTML page, not the actual WinUI product surface.** WinUI
  captures black except via full-desktop capture, and launching the app was out of scope.
- **Repo image candidates were rejected as primary subjects** — `blarai_lighthouse3.png` and
  `hand2.png` are UC-010 generated art, not screenshots, and `docs/demo/` has no images. Ground
  truth was built from `cook_test.html` instead and visually verified before grading.
- One prompt phrasing per question; no sensitivity sweep. A sterner prompt naming CSS/layout
  might change E4B's miss.
