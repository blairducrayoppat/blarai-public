# Gemma 4 vs Qwen3-VL-8B — visual screenshot checking, head-to-head, 2026-07-22 (#1005)

**Plain summary: the model we already rely on cannot tell that a page lost its stylesheet. It
says the page looks fine. That is the same failure we just rejected a Gemma model for, and it
is in our current stack today.**

Machine-readable: `gemma4-vs-qwen3vl-headtohead-2026-07-22.json`.
Prior records: `gemma4-instrument-probe-2026-07-22.*`, `gemma4-vision-instrument-probe-2026-07-22.*`.

## The finding that matters most

`cook_broken.png` is a real page with its stylesheet stripped and its title element deleted —
unstyled, full-bleed, title gone. Asked whether it renders correctly:

> **Qwen3-VL-8B (the incumbent):** `{"render": "ok", "reason": "The page appears correctly
> rendered with clear headings, numbered points, and readable text. The layout is consistent
> and well-structured, with no visible styling or layout issues."}`

Deterministic, reproduced across two independent passes. **It fails in the unsafe direction —
declaring a broken page healthy.** That is precisely why E4B was disqualified. A screenshot
check built on Qwen3-VL-8B would pass a page whose CSS failed to load.

It *does* catch a blatant `Error 500` page. The gap is specifically **"renders, but styled
wrong."**

## The table

| | E4B | 26B-A4B | **Qwen3-VL-8B (incumbent)** |
|---|---|---|---|
| Accuracy (4 graded Qs) | 3/4 | **4/4** | 3/4 |
| Render battery (4 subjects) | not run | 3/4 | 3/4 |
| Determinism | 5/5 | 5/5 | 5/5 |
| Load time | 8.9 s | 35–51 s | 8.4–13.3 s |
| Steady RAM added | +6.4 GB | +13.3–15.2 GB | **+5.7–6.0 GB** |
| Absolute peak in-use | 20.9 GB* | **31.312–31.323 GB** | **16.1 GB** |
| Min available at peak | 10.4 GB* | **0.005–0.012 GB** | **15.2 GB** |
| Per-question latency | 0.7–3.9 s | 1.5–4.1 s | 1.1–5.5 s |
| `cook_broken` render | ok — **WRONG** | broken — right verdict, fabricated reason | ok — **WRONG** |

\* in-process sampler; E4B was already ruled out so no external pass was run. All other
peak/min figures are external-sampler.

## Why the 26B's 4/4 does not survive contact with a harder test

Two subjects cannot separate *capability* from *answer bias*. I added two more (one clean, one
blatantly broken) so that always-"ok" and always-"broken" both score 2/4:

| | score | spread | bias | reason quality |
|---|---|---|---|---|
| Qwen3-VL-8B | 3/4 | ok:3 / broken:1 | too permissive | accurate, grounded |
| Gemma 4 26B | 3/4 | ok:1 / broken:3 | **false alarms** | **hallucinates** |

The 26B called a clean dashboard broken, justifying it with *"a large block of nonsensical
text/characters ('This is a screenshot of a web page...') overlapping the content"* — it
described **my own prompt text** as visible image content. Its one correct broken-page verdict
also cited overlap that does not exist.

So both land on 3/4, failing in opposite directions. The 26B's earlier 4/4 was partly its
broken-leaning bias meeting a set that contained one broken page.

## Three direct answers

1. **Does Qwen3-VL-8B get the layout-regression question right?** **No.** It answers "ok".
2. **Any reason to prefer the 26B?** **No.** It wins the narrow set 4/4 vs 3/4, but ties 3/4 on
   the wider one while costing ~2.6× the steady RAM, 3–6× the load time, pinning peak memory to
   within 5–11 MB of the ceiling, and hallucinating image content.
3. **Direction of the incumbent's failure?** **The unsafe one.** Same blind spot as E4B.

## The honest read

Neither model solves "renders but styled wrong" at any size tested. Scaling from 6 GB → 13.6 GB
did not fix it; it traded a permissive failure for a hallucinating one. **[PROPOSED]** If that
capability is what is actually wanted, a deterministic check — DOM assertions, or a pixel diff
against a golden screenshot — would catch a missing stylesheet with total reliability and no
RAM cost. That is not something that was asked for; it is where the measurement points.

## Caveat, carried deliberately

**Four graded questions on two UI subjects, plus a four-subject render set, is a failure
*shape*, not a *rate* — for every model in the table.** The comparison should not be read as
implying more precision than that. All UI subjects are headless-rendered HTML, not real WinUI
surfaces (which capture black on this box). One prompt phrasing throughout, identical across
models and deliberately untuned; a prompt naming CSS explicitly might move several of these
results and was not tried. The 31B was never loaded — its download was started and halted, and
nothing here claims anything about it.
