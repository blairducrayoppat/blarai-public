# Contribution Plan — OpenVINO 2026.2.1 dataset extension (Session 3)

**Status:** drafted, structural scrub gate GREEN, independent adversarial review in progress. **Nothing posted.** Awaiting the two hard gates: (a) operator approval of this plan + the drafts, and (b) the security/path-scrub review (structural done; adversarial pending).

**Tracking:** Vikunja #706.

---

## 1. The corrected premise (and what it changes)

The first contribution **is live** (verified at the venues themselves, the authoritative check):
- HF dataset `blairducrayoppat/openvino-arc140v-lunarlake` (2026.1.0 single-model + N=3 co-residency).
- OpenVINO discussion **#36604** (co-residency Show-and-tell), and the earlier **#36484** (NPU-vs-CPU draft) + its dataset `npu-specdecode-lunarlake`.

So this is an **EXTENSION of a live series**, not a debut. The drafts are written to read as a faithful continuation of the same author's same voice (Show-and-tell, scoped, humble, AI-assisted-disclosed). Decision (operator-confirmed): **extend the live `openvino-arc140v-lunarlake` dataset** with clearly-versioned 2026.2.1 splits + a version-delta section, and present the 2026.2.1 story as a follow-up that cross-links #36604 (and references #36484, where our new GPU-vs-CPU draft result completes the draft-device sweep).

## 2. The hook (what's genuinely new)

1. **A clean OpenVINO 2026.1.0 → 2026.2.1 version A/B** (same driver/models/methodology, two venvs back-to-back): **generation is unchanged, but cold prefill is ≈28–36% faster (tight at 512 tokens) and the VLM TTFT ≈19% faster.** The nuance ("the bump speeds prompt-*reading* and the vision model, not token-*generation*") is the headline.
2. **GPU-draft vs CPU-draft** speculative decoding on a unified-memory iGPU: GPU draft wins ≈13% at *identical* acceptance — completing the device sweep from #36484 (which had none/CPU/NPU but no GPU-draft row): **GPU > CPU > NPU.**
3. **30B MoE accuracy-flag cost** (`MOE_USE_MICRO_GEMM_PREFILL=0`): ≈19% gen / ≈28% TTFT, for an accuracy benefit a 2.2K-context eval could not show (cost measured, benefit not).
4. **Co-residency refresh on 2026.2.1** (N=1 confirmatory; the N=3 variance study stays the 2026.1.0 split) — the pattern holds: SDXL stalls the resident 14B to ≈0.6–0.7%, VLM ≈10.5%; compute-scheduling-bound.

Co-residency + per-phase Intel-UT telemetry remain the most novel assets; the version A/B is the new framing layer.

## 3. The publishable artifact set (all in this dir; built from committed source JSONs, never hand-typed)

| Artifact | What / where it goes | Conforms to |
|---|---|---|
| `README.md` | Full merged HF dataset card = live 2026.1.0 card **byte-for-byte** + a new "2026.2.1 update" section + 4 new `configs:`. Replaces the live card. | HF dataset-card norms (frontmatter configs, Key-findings→Files→Methodology→Caveats→Feedback) |
| `version_delta.csv/.jsonl` | The 2026.1.0↔2026.2.1 A/B (gen, prefill, VLM), 13 rows | HF tabular config |
| `draft_device.csv/.jsonl` | GPU vs CPU draft (14B+8B): tps, acceptance, 4 rows | HF tabular config |
| `moe_flag.csv/.jsonl` | 30B MoE flag on/off: tps, TTFT, eval, 2 rows | HF tabular config |
| `coresidency_2026_2_1.csv/.jsonl` | N=1 refresh, same schema as the published `coresidency` table, 4 rows | HF tabular config |
| `raw/*.json` (32) | Scrubbed per-run source JSONs behind the tables | dataset `raw/` (checkability) |
| `drafts/discussion_openvino_version_delta.md` | NEW OpenVINO "Show and tell" discussion (the series' 3rd post) | the live series voice (matches #36604/#36484) |
| `drafts/comment_on_36604_forward_pointer.md` | short comment on #36604 linking forward | factual, non-promotional |
| `drafts/reddit_localllama_combined.md` | r/LocalLLaMA post (whole dataset, leads with novel parts) | r/LocalLLaMA: data-in-body, links-in-top-comment, plain title, Resources flair |
| `drafts/llmtracker_engagement.md` | GitHub issue (engagement-first) + a ready PR section | engagement-first (issue before PR), `howto/Intel-GPUs.md` Markdown |
| `drafts/secondary_venues.md` | Intel Community forum + r/IntelArc + LocalScore arch-label correction | each venue's norms |

**Layout (operator directive):** the AI-assistance disclosure is placed **at the end** of each post (discussion, Reddit) — a trailing note, not a front-of-post block — so it doesn't sit between the reader and the data/learnings (this also matches #36484's own placement). The forum / r/IntelArc drafts already trail it; the llm-tracker outreach keeps it as a brief end-note. In the republished dataset card it is moved from near-top to just before "## License and citation" (the rest of the live card is byte-preserved).

**Not published:** the build/scrub scripts (`build_community_dataset_2026_2_1.py`, `assemble_dataset_card_2026_2_1.py`, `scrub_community_export.py`, `verify_community_scrub.py`), `raw_manifest.txt`, this plan. They are internal.

## 4. Venue + sequencing plan (verified live this session)

Canonical home = the HF dataset + the OpenVINO Show-and-tell discussion. Recommended order:

1. **Extend the HF dataset** (push the 4 tables + the 32 `raw/` JSONs + replace `README.md`). The permanent, citable home.
2. **New OpenVINO "Show and tell" discussion** (the version-delta post) — cross-links #36604, #36484, and the extended dataset.
3. **Comment on #36604** pointing forward to the new discussion (fill in its URL once #2 exists).
4. **r/LocalLLaMA** — strong precedent (the exact 258V/Arc 140V llama.cpp thread, *no OpenVINO* in it → we're additive). Body = data only; links in a **top comment** (10% self-promo rule); plain hardware-first title; **Resources** flair.
5. **llm-tracker.info** — best-fit cross-link (same chip, the page already has llama.cpp/SYCL/IPEX numbers, the gap is *zero OpenVINO*). **Engagement-first: open the issue to @lhl first**; build the PR only if he's responsive + says yes.
6. **Secondary (optional reach):** Intel Community OpenVINO forum (official), r/IntelArc (Benchmark flair, niche), an optional good-faith LocalScore *arch-label* correction. **LocalScore is NOT a submission target** — it's CLI-only llamafile/llama.cpp with no Intel-GPU path, so any "submission" would be a CPU-fallback number.

## 5. Scrub gate status (§6/§6a)

- **Structural integrity gate — GREEN.** `verify_community_scrub.py`: raw scrub **32/32 PASS** (every number/key/unit/array-length byte-identical original↔scrubbed; no residual paths/username/hostname/uuid/secrets). Fresh-authored tables + README + all 6 drafts: **scan-only clean** (no sensitive tokens, no BlarAI-internal-term warnings).
- **Independent adversarial review — DONE, findings folded.** Fresh-context agent fact-checked every headline number against the source JSONs + the four live published artifacts and leak-scanned the full tree. **Verdict: no blockers, no privacy leaks, every number source-confirmed.** One MAJOR + four MINOR, all fixed:
  - **MAJOR (fixed):** the inherited "≈1960 tok/s" prefill figure is **prefix-cache-warm** (verified on disk: the single-model probe runs `enable_prefix_caching=true` over a repeated prompt set), not cold — citing it as "the prefill rate" is backwards for cold/first-prompt or cross-runtime `pp512` comparison, and it inflates the dense-vs-MoE "mirror" to ≈4× (cold-vs-cold it's ≈1.3–1.6×). **Fixed in everything I control:** the Reddit table and llm-tracker PR now lead with **cold pp@512** (595→761, 1086→1477); a **cold-vs-warm reconciliation note** was added to the card's new section. *(See the operator decision in §6 about the inherited live-card/#36604 framing — that's already-public content.)*
  - **MINOR (fixed):** the 2026.2.1 co-residency refresh used 20-step SDXL vs the N=3 study's 30-step — now flagged in both the card and the discussion post; "≈30%+" softened to the accurate "≈28–36%"; the card's dangling "follow-up discussion" reference now carries a `<FILL-IN URL>` marker; the card's Files coverage now lists the 32 new `raw/` JSONs.
  - **NIT (internal, non-gating):** `PERFORMANCE_LOG.md` shows 14B spec-off 2026.2.1 = 10.92 while the source JSON + all artifacts correctly say 10.95 — a stale value in the internal log (artifacts are right).
- **Bandwidth unit — RESOLVED to GB/s, sourced.** Confirmed against Intel's OA metric definition in Mesa's `oa-lnl.xml` (`units="gbps"`; equation = byte-counter ÷ GpuTime[ns] = bytes/ns = GB/s; **bytes-based, not bits** — stated explicitly to pre-empt an 8× misread). The "unconfirmed" caveat is dropped in all new artifacts (consistent with the live parent card). *Internal-doc follow-up (low priority, non-gating): the `PERFORMANCE_LOG.md` 2026-06-29 entries still say "unconfirmed" — worth a one-line update for internal consistency.*

## 6. Operator-only open items (privacy/logistics judgments, not technical)

1. **Reddit account standing** — confirm the posting account has some karma/age before posting (AutoMod may hold a brand-new account); this could not be verified from research.
2. **@lhl responsiveness** — the llm-tracker vault repo last synced ~Nov 2025 (~7 mo). Issue-first; only build the PR if he replies.
3. **Posting order detail** — the #36604 comment and the Reddit/llm-tracker links reference the new discussion URL, which only exists after step 2; the `<FILL-IN 2026.2.1 discussion URL>` markers get filled at that point.
4. **One methodology transparency note to confirm:** the 2026.2.1 co-residency refresh used **20-step** SDXL vs the published N=3 study's **30-step** (a runtime config change between campaigns). The ≈1% retained-throughput finding is robust to step count (it's about compute monopolization, not diffusion duration), but the step difference is stated in the table labels; flag if you'd like it called out more prominently.
5. **DECISION — the inherited live-card / #36604 prefill framing (your already-public content).** The review found that the **live** `openvino-arc140v-lunarlake` card and discussion **#36604** present that same prefix-cache-**warm** ≈1960 tok/s as "the prefill rate to cite" — a pre-existing, now-known-misleading framing (it overstates cold prefill ≈2.5× and the dense-vs-MoE prefill gap ≈4× vs ≈1.3–1.6× cold). I did **not** silently rewrite that published content; instead the republished card adds a transparent **reconciliation note** that flags the ≈1960 as warm and points to the cold numbers. **Your call on going further:** (a) leave the inherited text as-is (the new note already corrects it) — *default*; or (b) I also lightly tighten the inherited "rate to cite" line on republish + post a one-line clarifying comment on #36604 so the public record is self-consistent. Either is fine; (b) is the more thorough correction of your live artifacts. *(Low-priority internal follow-up regardless: update the `PERFORMANCE_LOG.md` 2026-06-29 entries — the "unconfirmed" bandwidth caveat and the 10.92 vs 10.95 stale value — for internal consistency.)*

## 7. The two hard gates (restated)

Nothing is posted until BOTH: **(a)** you approve this plan + the drafts, and **(b)** the security/path-scrub review passes (structural ✓; adversarial review folded). Publishing is irreversible and outward-facing.
