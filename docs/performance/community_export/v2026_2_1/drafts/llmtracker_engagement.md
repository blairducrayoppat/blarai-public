# llm-tracker.info engagement — issue-first, then an optional PR

Engagement-first, decline-able offer to **Leonard Lin** (maintainer of llm-tracker.info; GitHub [@lhl](https://github.com/lhl), org AUGMXNT). The Intel-GPUs page already has llama.cpp CPU/Vulkan/SYCL + IPEX-LLM numbers on the **same** Core Ultra 7 258V / Arc 140V silicon — the gap is precisely *zero OpenVINO data*. So this is "add the OpenVINO column," apples-to-apples on a page that already has the scaffolding.

**Sequencing (per the operator's engagement-first norm):** open the issue FIRST and wait for @lhl to confirm he's still maintaining (the vault repo last synced ~Nov 2025, ~7 months stale) and welcomes an OpenVINO/Arc-140V section. Only build the PR if he says yes. There is no CONTRIBUTING/PR template and a license ambiguity (About page says MIT, repo metadata says none) — worth a one-line check in the issue.

- Issue/PR repo: `AUGMXNT/llm-tracker.info-vault`
- Target file for the PR: `howto/Intel-GPUs.md` (Quartz + Obsidian, plain Markdown)

---

## Part 1 — GitHub issue (`AUGMXNT/llm-tracker.info-vault`)

**Suggested title:** OpenVINO/Qwen3 numbers on the Core Ultra 7 258V / Arc 140V — offer to add an OpenVINO section

**Body:**

Hi @lhl,

Your Intel-GPUs page has been a genuinely useful reference for me — it's one of the few places with careful, real numbers on this exact silicon, and the llama.cpp / SYCL / Vulkan / IPEX-LLM coverage is the kind of cross-runtime picture that's hard to find anywhere else. Thanks for keeping it up.

I've been measuring local inference on the same Core Ultra 7 258V (Lunar Lake) / Arc 140V chip, but via **OpenVINO** — a runtime the page doesn't cover yet, so the numbers would slot in alongside what you have rather than re-run it. What I have is Qwen3-centric and published CC-BY-4.0:

https://huggingface.co/datasets/blairducrayoppat/openvino-arc140v-lunarlake

- Spec-decode decode rates for the 14B and 8B (INT4), spec-off vs spec-on (small 0.6B GPU draft).
- A Qwen3-Coder-30B-A3B (MoE) prefill/decode profile, and a Qwen3-VL-8B vision model.
- A 14B **co-residency** study — what a resident 14B costs when a second model (SDXL, or the VLM) shares the same iGPU and shared RAM — with per-phase Intel GPU telemetry (power / freq / GPU-busy / bandwidth; NPU confirmed at 0 W).
- A clean **OpenVINO 2026.1.0 → 2026.2.1 version A/B** (held driver/models/methodology constant): cold prefill is ≈28–36% faster and the VLM TTFT ≈19% faster (generation flat) — and a GPU-vs-CPU **draft-device** comparison (GPU draft wins ≈13% at identical acceptance on this unified-memory iGPU).

If an OpenVINO data point would be useful to your readers, I'd be happy to write it up as a clean Markdown section in your `howto/Intel-GPUs.md` format (a draft is ready) or open a PR — whichever is least work for you. Just as happy to leave it as a link here if you'd rather not expand the runtime list. Entirely your call.

Two upfront notes: (1) this is an AI-assisted effort — the measurements are real (run on my own hardware), but the harnesses, analysis, and write-up were done with an AI assistant under my direction; the dataset card says the same. (2) Quick housekeeping if I do PR — the About page lists MIT but the repo has no license file; happy to follow whatever you prefer.

Either way, thanks for the page.

---

## Part 2 — ready PR section for `howto/Intel-GPUs.md` (only if @lhl says yes)

> Insert as a new "OpenVINO (GenAI)" subsection under the Arc 140V / Lunar Lake area, matching the page's existing model / precision / backend / pp tok/s / tg tok/s column style. All numbers are on one Core Ultra 7 258V / Arc 140V, GPU driver 32.0.101.8826, Windows 11, OpenVINO GenAI (in-process) and OVMS for the 30B; INT4 weights; greedy.

### OpenVINO GenAI on the Arc 140V (Lunar Lake)

Single-model, all on the iGPU (NPU idle, telemetry-confirmed 0 W). `tg` = decode tok/s (median); `pp` = cold prefill tok/s. Spec-decode draft = Qwen3-0.6B-pruned-6L INT8 on the GPU.

`pp` below is **cold pp@512** (dedicated harness, prefix-caching off — matching the page's cold-prefill convention), shown 2026.1.0 → 2026.2.1.

| Model | Precision | Backend | pp@512 tok/s (cold) | tg tok/s (spec-off → spec-on) | OpenVINO |
|---|---|---|---|---|---|
| Qwen3-14B | INT4 | OpenVINO GenAI (GPU) | 595 → 761 | 11.1 → 17.1 | 2026.1.0 / 2026.2.1 |
| Qwen3-8B | INT4 | OpenVINO GenAI (GPU) | 1086 → 1477 | 19.8 → 27.4 | 2026.1.0 / 2026.2.1 |
| Qwen3-Coder-30B-A3B (MoE, ~3B active) | INT4 | OVMS 2026.2 (cont. batching, GPU) | ~480 (cold, @421-tok) | 38.1 | 2026.2 |
| Qwen3-VL-8B-Instruct (vision) | INT4 | OpenVINO GenAI (GPU) | — | TTFT 162 ms / TPOT 47 ms (2026.2.1) | 2026.2.1 |

Notes for the page's cross-runtime context (neutral — not a head-to-head):
- **Speculative decoding** gives ≈1.5× on the 14B and ≈1.4× on the 8B (small 0.6B GPU draft); keep the draft on the **GPU** (a CPU draft is ≈13% slower here at identical acceptance — unified memory, so it pulls the same LPDDR5X and adds a CPU↔GPU sync per round).
- **MoE is the mirror image of the dense models:** fastest decode/TTFT, slowest cold prefill (≈480 pp vs ≈595–760 cold for the dense models) — it routes every prompt token through all experts at prefill but activates only ≈3B params per decode step. (All cold pp; a prefix-cache-warm probe reads much higher.)
- **Version note:** 2026.1.0 → 2026.2.1 speeds cold prefill ≈28–36% and the VLM TTFT ≈19% (decode flat; controlled A/B, same driver/models/methodology).
- **Co-residency** (a resident 14B + a second model on the one iGPU) and per-phase Intel-UT telemetry are in the linked dataset — the part that's hard to find elsewhere.

Full per-run data + methodology (CC-BY-4.0): https://huggingface.co/datasets/blairducrayoppat/openvino-arc140v-lunarlake
