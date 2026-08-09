# Outreach draft — offer OpenVINO/Qwen3 data to llm-tracker.info

Cooperative, decline-able offer to **AUGMXNT** (maintainer of llm-tracker.info) to
contribute an OpenVINO data point on the same Intel Core Ultra 7 258V / Arc 140V
silicon their Intel-GPUs page already characterizes.

Notes before sending:
- Replace the dataset URL placeholder once the Hugging Face dataset is published:
  `https://huggingface.co/datasets/blairducrayoppat/openvino-arc140v-lunarlake`
- GitHub issue goes on the vault repo: `AUGMXNT/llm-tracker.info-vault`
- This is an offer, not a correction. Their call entirely.

---

## Variant 1 — GitHub issue (`AUGMXNT/llm-tracker.info-vault`)

**Suggested title:** OpenVINO/Qwen3 numbers on the Core Ultra 7 258V / Arc 140V — offer to contribute

**Body:**

Hi @AUGMXNT,

Your Intel-GPUs page has been a genuinely useful reference for me — it's one of the
few places with careful, real numbers on this silicon, and the llama.cpp / SYCL /
Vulkan / IPEX-LLM coverage is exactly the kind of cross-runtime picture that's hard
to find anywhere else. Thanks for keeping it up.

I've been measuring local inference on the same Intel Core Ultra 7 258V (Lunar Lake)
/ Arc 140V chip, but via OpenVINO — a different runtime from the builds already on
the page, so the numbers would sit alongside what you have rather than re-run it.
What I've got is Qwen3-centric: spec-decode decode rates for the 14B and 8B (INT4),
a Qwen3-Coder-30B-A3B MoE prefill/decode profile, a Qwen3-VL-8B vision model, and a
14B co-residency study (what a resident 14B costs when a second model shares the same
iGPU and shared RAM), with per-phase Intel GPU telemetry. It's published CC-BY-4.0:

https://huggingface.co/datasets/blairducrayoppat/openvino-arc140v-lunarlake

If an OpenVINO data point would be useful to your readers, I'd be happy to write it
up as a clean markdown section in your format, or open a PR — whichever is least work
for you. Just as happy to leave it as a link here if you'd rather not expand the
runtime list. Entirely your call.

One thing to be upfront about: this is an AI-assisted effort on my end — the
measurements are real (run on my own hardware), but the analysis and write-up were
done with an AI assistant working under my direction. The dataset card notes the same.

Either way, thanks for the page.

---

## Variant 2 — Social / DM (X: @augmxnt)

Hi @augmxnt — your Intel-GPUs page is a reference I lean on a lot, thanks for keeping
it up. I've measured OpenVINO/Qwen3 numbers on the same Core Ultra 7 258V / Arc 140V
(spec-decode 14B & 8B, a 30B MoE, a VLM, plus a 14B co-residency study), published
CC-BY-4.0: https://huggingface.co/datasets/blairducrayoppat/openvino-arc140v-lunarlake
. If an OpenVINO data point would be useful for the page I'm happy to send a clean
markdown section or PR — no worries at all if not, your call. (Heads up — it's AI-assisted: real measurements on my hardware, but the analysis and write-up were AI-assisted.)
