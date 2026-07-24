---
title: Publication Program — Verified Facts
status: living
area: research
---

# Verified facts — the program's checked sheet

Every fact a surveyor or author carries about this project comes from HERE, and each
row names its primary source and verification date. Facts marked **VOLATILE** must be
re-verified at draft time (Author Kit §B); stable facts still get spot-checked in the
fact-audit. Two gate-caught errors motivated this sheet (LA amendment 1): "two years
of journal" (it is 58 days) and a stale "pending review" belief about PR #4082 (it
merged 2026-07-08).

## Project + corpus

| Fact | Value | Primary source | Verified |
|---|---|---|---|
| Project first commit | `fc0eda64`, 2026-02-04 — project ≈5.5 months old | `git log --reverse` | 2026-07-19 |
| Build journal born | 2026-05-21 | audit pack README; `docs/archive/journal/2026-05.md` | 2026-07-19 |
| Journal corpus | **465 entries**, 2026-05-21 → 2026-07-17 (**58 days**) | audit pack README ¶ plain-summary; synthesis header | 2026-07-19 |
| Anthology | **exactly 64 entries**, verbatim, five acts, three reading paths | `grep -c '^### ' docs/BUILD_JOURNAL_ANTHOLOGY.md` = 64 | 2026-07-19 |
| Lessons corpus | 284 numbered lessons (three-tier since 2026-07-19) — **VOLATILE** (grows) | audit README ¶6; CLAUDE.md snapshot | 2026-07-19 |
| Cross-era threads | six, named: novice-as-instrument · two-correct-things-collide · instrument-trust ladder · dormancy grammar · honesty economy · upstream citizenship | `synthesis_journal_gems.md` §B | 2026-07-19 |
| Session transcripts mined by audit | 771 | audit README ¶1 | 2026-07-19 |
| Composition-failure specimens | **7 enumerated** in the audit synthesis (replay window 06-09 · SSRF-precheck kill-switch 06-12 · write-only knowledge bank 06-14 · unreachable ALLOW 07-02 · leak-validator swallow 07-02 · instance-lock gate kill 07-04 · recovery-killed-the-swap 07-07). The synthesis's own "~8" is an estimate; the P2 survey flagged the 7-vs-8 mismatch — P2's author enumerates the exact count from the journal before ANY count prints | synthesis §B2; P2-verdict §5 | 2026-07-19 |

## Upstream / community

| Fact | Value | Primary source | Verified |
|---|---|---|---|
| openvino.genai PR #4082 | **MERGED 2026-07-08T13:07:36Z** — "Fix xgrammar structured-output crash at EOS under speculative decoding"; approvals: apaniukov, pavel-esir; DCO-signed; AI-assistance disclosed; commit `4c797722` on `blairducrayoppat:fix/xgrammar-stop-token-spec-decode` | GitHub API `pulls/4082` + `/reviews` | 2026-07-19 |
| #4082 release inclusion | **UNVERIFIED** — merge ≠ released; check release notes/tags before any "shipped in release" claim — **VOLATILE** | — | flagged 2026-07-19 |
| Companion issue | openvino.genai #4081 (filed with the PR) | journal 2026-07-05 entry (anthology) | 2026-07-19 |
| Thinking-tag reproduction | contributed to openvino.genai issue #3937 — authors verify contribution form + current state via API before print — **VOLATILE** | synthesis §B6 | 2026-07-19 |
| OpenVINO Discussion #36484 | the LA's OWN published spec-decode characterization on this exact box (GPU-target + NPU-draft; Qwen3-14B INT4 + 0.6B INT4 draft; GPU-only 12.2 tok/s; CPU-draft 1.35×; NPU-draft 0.55–0.74×; n=3, single prompt, limits stated), posted 2026-06-20 under blairducrayoppat. Found by the P1 survey — previously MISSING from this sheet. P1/S2 must cite + reconcile it (different experiment than the 16K figures). Authorship + date + title **GraphQL-CONFIRMED 2026-07-19** (createdAt 2026-06-20T14:11:44Z; title states "works, but consistently slower than GPU-only (0.55–0.74×)"); body numbers from the rendered read | GitHub GraphQL discussion(36484); P1-verdict §0 | 2026-07-19 |
| Lunar Lake Key Locker CPUID data | novel data documented 2026-06-09 — authors pull the entry + exact claim before print | synthesis §B6 | 2026-07-19 |
| Public mirrors | blarai-public + agentic-setup-public, actually public since 2026-07-14; local → private → public leak-gated weekly sync | memory/journal; mirrors themselves | 2026-07-19 |
| GitHub handle | blairducrayoppat | standing doctrine | 2026-07-19 |

## Hardware / performance (headline claims surveyors may carry; authors re-derive exact figures + conditions from the log)

| Fact | Value | Primary source | Verified |
|---|---|---|---|
| The box | Intel Core Ultra 7 258V (Lunar Lake), Arc 140V iGPU (Xe2), NPU, 32 GB LPDDR5X (31.323 GB effective); Windows 11 Pro | CLAUDE.md host_environment | 2026-07-19 |
| Stack | OpenVINO GenAI substrate; Qwen3-14B resident brain; pruned Qwen3-0.6B INT4 draft (spec-decode, ADR-012); bge-small-en-v1.5 on NPU; Whisper on GPU; SDXL INT8 on demand | CLAUDE.md stack | 2026-07-19 |
| NPU embedding offload | **13.6×** vs CPU on document-window texts (the knowledge-ingest case); static-compile boot cost ~12.1 s noted | PERFORMANCE_LOG.md:353–358 | 2026-07-19 |
| Spec-decode at 16K | acceptance ~46–57% across bands; 4.94 TPS ≈ **2.3×** the earlier 2.13 TPS record at 16K; DEC-03 reaffirmed | PERFORMANCE_LOG.md:1654 | 2026-07-19 |
| 14B decode figures | median ~13.6 tok/s (2026-05-22/06-05 entries) later **superseded upward** by the tuned pruned-6L draft — authors MUST cite the latest entry (PERFORMANCE_LOG:868 region), not this row — **VOLATILE** | PERFORMANCE_LOG.md:868, 951 | 2026-07-19 |
| Cross-runtime (vs llama.cpp) | 14B decode: OpenVINO 1.8× spec-on (13.6 vs 7.52), **1.2× draftless-vs-draftless** (the honest apples-to-apples, from addendum A1 — always cite BOTH); coder-30B 1.4×; backend ranking is model-specific (35B-A3B: SYCL 8.14 > Vulkan 7.37; coder-30B: Vulkan 27.07 ≫ SYCL 6.56) | PERFORMANCE_LOG.md:2735 | 2026-07-19 |
| Datasets in hand | KV-cache two-regime sweep · co-residency telemetry · MoE comparisons · prefix-caching A/B (2026-07-09 JSON) · community export staging `docs/performance/community_export/` (coresidency + single_model CSV/JSONL, drafts/, v2026_2_1/) — staging is IN FLIGHT by another session; P1 author coordinates, does not touch | docs/performance/ listing | 2026-07-19 |

## External references pieces lean on

| Fact | Value | Status |
|---|---|---|
| OpenClaw CVSS-8.8 chain (P4 foil) | **VERIFIED AS A CONFLATION (2026-07-19, P4 survey) — the phrase "OpenClaw CVSS-8.8 agent-memory chain" MUST NOT print.** Three separate facts were fused by secondary blogs: CVE-2026-25253 (8.8, WebSocket-gateway 1-click RCE) and CVE-2026-24763 (8.8, Docker sandbox command injection) are NOT memory issues; the actual memory-file CVE (CVE-2026-53844, shared-memory-search visibility bypass) scores ~6.0; "ClawHavoc" (Koi Security, 2026-02-01) is a 341-skill SUPPLY-CHAIN campaign, not memory poisoning. REBUILT FOIL (per P4-verdict §0): use OpenClaw's self-written SOUL.md/MEMORY.md *design* as the "gives the model a pen" foil; anchor severity on OWASP ASI06:2026 (memory-poisoning class), not a CVSS number; cite ClawHavoc and CVE-2026-25253 only as what they actually are. Re-verify the fast-moving CVE landscape at draft time — **VOLATILE** |
| Automation-bias literature (P5 relates to) | P5 inverts it — related-work review mandated by README §1 | survey + author pass to build the map |

## Standing framing facts

- Public framing: "personal research project" / "long-term local AI system" — never
  "prototype" (LA doctrine).
- The corpus is n=1: one project, one box, one operator — every piece frames
  accordingly (Author Kit §E).
- The LA is a non-technical Lead Architect directing through plain-language governance;
  the development fleet is Claude-based; BlarAI itself is local-only with policy-gated,
  ceremony-opened egress. The identity split (dev tools ≠ product) is itself one of the
  publishable ideas (thread 6).
