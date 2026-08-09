# Comment to post on discussion #36604 (the co-residency thread)

Posted by the author (blairducrayoppat) on https://github.com/openvinotoolkit/openvino/discussions/36604. Two jobs: (1) a **clarification** of which prefill regime the post's ≈1960 tok/s figure measured (prefix-cache-warm vs cold), and (2) a forward-pointer to the 2026.2.1 follow-up. Factual, non-promotional, framed as clarifying — not retracting (the number isn't wrong, it's a different regime). Post AFTER the 2026.2.1 follow-up discussion exists, and fill in its URL.

---

Two small follow-ups on this post.

**Clarifying the prefill figure.** The ≈1960 tok/s prefill rate I cite above is measured **prefix-cache-warm** — the single-model probe runs with prefix caching on over a repeated prompt set, so it's an upper bound for repeated prompts that hit the KV cache, not a cold first-prompt rate. With a dedicated **cold** prefill harness (prefix-caching off) the same 14B reads ≈595–761 tok/s at 512 tokens (2026.1.0 → 2026.2.1). Both are valid — they're just different regimes — but for a cold / first-prompt or cross-runtime `pp512` comparison the cold numbers are the ones to use. (It also means the dense-vs-MoE prefill gap is ≈1.3–1.6× cold rather than the ≈4× the warm figure implies — the MoE still has the slowest prefill, by a smaller cold margin.) Details in the follow-up below.

**Follow-up post.** I re-measured this stack across the **OpenVINO GenAI 2026.1.0 → 2026.2.1** bump (same hardware, same driver 32.0.101.8826, same methodology): cold prefill is ≈28–36% faster and the VLM TTFT ≈19% faster (token generation unchanged), the co-residency pattern here reproduces (a smaller N=1 confirmatory pass — the N=3 variance study stays the one in this post), and there's a GPU-vs-CPU draft-device result + a 30B MoE accuracy-flag cost. Full numbers: <FILL-IN 2026.2.1 discussion URL>. The dataset has been extended with the 2026.2.1 splits and a cold/warm-prefill reconciliation note.
