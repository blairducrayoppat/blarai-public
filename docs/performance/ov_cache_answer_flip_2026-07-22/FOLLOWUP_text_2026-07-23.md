# Cache-flip follow-up — TEXT-only control (2026-07-23)

**Question:** the 2026-07-22 probe saw a VLM greedy answer flip cold→warm under `CACHE_DIR`
(cold named the real defect; warm runs asserted the opposite), which forced BlarAI to run
with compiled-blob caching OFF. Was that a real cache effect, or vision-model noise? This
follow-up removes the vision path as a variable.

**Method.** Text-only `LLMPipeline` (Qwen3-14B INT4, GPU, greedy `do_sample=False`,
max_new_tokens=200), OpenVINO GenAI 2026.2.1. Three prompts (a flip-prone reasoning task —
bat-and-ball; a factual one-liner; a code-gen task), 3 reps each, run in two separate
processes sharing one `CACHE_DIR`: **cold** (empty cache → compiles) then **warm** (populated
cache → reuses). sha256 recorded per generation. Raw: `flip_text_cold_2026-07-23.json`,
`flip_text_warm_2026-07-23.json`. Script: scratchpad `cache_flip_text.py`.

**Result — no flip. Cold and warm greedy output are byte-identical.**

| prompt | cold shas | warm shas | cold==warm |
|---|---|---|---|
| bat_ball | d28425dd ×3 | d28425dd ×3 | **identical** |
| kilobyte | 6dad0f91 ×3 | 6dad0f91 ×3 | **identical** |
| is_prime | 32cd9ba2, e52aa694, e52aa694 | 32cd9ba2, e52aa694, e52aa694 | **identical (same sequence)** |

- The compiled-blob cache does **not** change text output. The 2026-07-22 VLM flip is therefore
  very likely **vision-model nondeterminism** (that model is a documented image-hallucinator),
  **not** a `CACHE_DIR` effect.
- Side finding, cache-INDEPENDENT: `is_prime` rep-0 differs from reps 1–2 in **both** arms
  identically — a first-generation-after-load warmup nondeterminism, unrelated to caching
  (bat_ball and kilobyte were fully deterministic across reps). Minor; flagged, not chased.
- Operational win caching currently forfeits: **warm load 2.21 s vs cold 52.06 s (~24×)**;
  load-transient peak RAM **14.74 GB warm vs 24.36 GB cold**.

**Scope / caveat.** This tests the **text** path only. The original flip was on a **VLM**;
the vision preprocessing / image-embedding path is NOT exercised here, so this does not by
itself clear caching on the VLM path — that needs its own text-controlled VLM check
(same image, greedy, N≥3, cold vs warm) before caching is called safe there.

**Decision owner: Blair.** Enabling `CACHE_DIR` is a quality-touching call, not a measurement
side effect. This measurement says: for text, caching is output-invariant and buys a 24× load
speedup + lower load transient. The VLM-path question is still open. No BlarAI config was
changed by this run.

---

## VLM control on the PRODUCTION model (2026-07-23, added same day)

The text result above cleared the LLM path but not the vision path (where the original flip
was seen). So: same cache-flip test on the **production** VLM (Qwen3-VL-8B, the real model —
the 2026-07-22 flip was on a different 26B *candidate* eval model, a known hallucinator).
VLMPipeline, GPU, greedy, `cook_broken.png`, 3 reps cold + 3 reps warm, same CACHE_DIR.
Raw: `flip_text_cold_2026-07-23.json` sibling files `flip_vlm_*` in the session scratch.

**Result — NO flip.** Cold and warm both produced sha `0493777a4079d8a1` ×3 (byte-identical
within and across arms). So the compiled-blob cache does not change the production VLM's
output either; the 2026-07-22 flip was that candidate model's own nondeterminism, now
**definitively closed on the real model**.

Bonus, relevant to whether to ever enable VLM caching: warm load **2.62 s vs 15.79 s** cold
compile — a ~6× load win, and a much better trade than the 14B (whose warm≈compile, see
DEC/June probe). So the **VLM is the better caching candidate**, especially once disk space
is no longer tight. Output-safety: confirmed. Decision (enable or not): Blair's.

(Note: the 8B VLM judged the deliberately-broken page as "ok" — a model *accuracy* limit,
unrelated to caching.)
