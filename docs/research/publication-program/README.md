---
title: Publication Program — canonical instruction
status: living
area: research
---

# Publication Program — mining the BlarAI corpus for publishable work

**Status:** LA-commissioned 2026-07-19. THIS FILE is the canonical standing instruction
for every session in the publication program.
**Provenance:** relocated from `docs/handoffs/publication-program-brief-2026-07-19.md`
(now a pointer stub; that dir has a 7-day archive sweep and this program runs for weeks)
and amended per seven binding LA directives given at the Phase 0 gate, 2026-07-19 — see
the amendment log at the bottom. Where this file and the old brief differ, this file wins.
**Origin:** the 2026-07-18 documentation audit (#945; evidence in
`docs/research/doc-infrastructure-audit-2026-07/`) mined all 465 journal entries
(2026-05-21 → 2026-07-17, 58 days) and produced the 64-entry anthology
(`docs/BUILD_JOURNAL_ANTHOLOGY.md`), six cross-era threads, and one publishable thesis.
**Tracking:** Vikunja project **Publications** (id 13) · epic **#956** · Phase 0 **#957**.

---

## 0. Non-negotiable standards (bind every session in this program)

1. **The LA's professional standing is the asset being built — and the constraint.**
   High integrity and rigor beat volume. A piece that cannot survive expert scrutiny
   does not ship. When in doubt, cut the claim or cut the piece.
2. **Nothing publishes without the LA's explicit per-piece approval.** Publishing is
   outward-facing egress of content under his name — always his decision, at a review
   ceremony where he reads the final draft. No session ever posts anything anywhere.
3. **Research is READ-ONLY everywhere, in every phase** (LA amendment 7): no posts,
   comments, votes, account creation, or community engagement of any kind, anywhere,
   without explicit per-piece LA approval. Surveying a venue means reading it.
4. **n=1 honesty.** This is a single-project case corpus. Every piece frames itself as
   a documented case study / field report, never as a generalized empirical claim.
   "Here is what happened, fully documented and verifiable" is the strength — use it.
5. **Verifiability is the credibility strategy** (the LA has no publication record —
   evidence must do the work a byline cannot): cite the public mirrors, the merged
   upstream work (openvino.genai PR #4082, merged 2026-07-08 — API-verified), and the
   `docs/performance/` dataset. Every number exact and traceable; every quote verbatim;
   no reconstructed dialogue; no [SHA] placeholders.
6. **Every date and number re-derived from primary artifacts before print** (LA
   amendment 1, minted after the Phase 0 gate itself contained two date errors — a
   wrong number in print is fatal to this program). The Author Kit §B pass is
   mandatory for every draft; `VERIFIED_FACTS.md` is the program's checked sheet.
7. **Rigor lives in the pieces, not just the gate** (LA amendment 4): every
   expert-facing piece carries a prior-work treatment fed by the novelty survey; every
   data piece carries a methods section (hardware, software versions, methodology, and
   what was NOT measured — the existing community-grade format); single-case framing
   language everywhere.
8. **Public framing rules (standing LA doctrine):** "personal research project" /
   "long-term local AI system" — never "prototype." Softened certainty in public prose
   (hedged, evidence-scoped); exact numbers stay exact. Nothing that leaks personal
   data or security-sensitive residuals: source only from content that clears the same
   leak-gate standard as the public-mirror sync; when unsure, exclude and flag.
9. **AI-authorship disclosure:** the LA decides the stance at the Phase 0 ceremony
   (recommendation: full transparency — the pieces are drafted with the AI fleet they
   describe; for this project that disclosure is both an integrity requirement and the
   story itself). Whatever he decides applies uniformly to every piece.
10. **Session hygiene:** each phase/thread = its own clean session, grounded per
    CLAUDE.md, presenting its own comprehension gate and WAITING for LA confirmation
    before substantive work (this file authorizes the WORK, never the skipping of a
    gate). Everything tracked on the Vikunja epic. Journal fragments to
    `docs/journal_fragments/` per doctrine.
11. **Author ≠ verifier, enforced:** every draft passes an adversarial review panel of
    independent subagents before the LA sees it (§4). Reviewers never rewrite; authors
    never grade their own work.

---

## 1. The candidate inventory (Phase 0 pressure-tests, de-duplicates, and sequences this)

Portfolio purpose per LA amendment 6: **AIGP** = the LA's AI-governance certification
portfolio (IAPP AIGP) · **OV** = OpenVINO/hardware community standing · **REACH** =
general audience reach. Author briefs name their piece's purpose.
**Post-ceremony precedence:** where this inventory and the decided state differ,
`ROADMAP.md` §5 (the LA's decisions) and `VERIFIED_FACTS.md` win — venue lists here
are historical candidates; the approved allowlist is ROADMAP §5c.

| # | Working title / thread | Tier | Purpose | Primary channels (unknown-author-realistic) | Notes |
|---|---|---|---|---|---|
| P1 | **The Lunar Lake local-AI performance corpus** (KV-cache two-regime sweep, co-residency telemetry, MoE bargain, NPU offload 13.6× on document-window embedding, spec-decode A/B, the #725 crash→upstream-fix arc) | Technical, data-first | OV | Home base + Hacker News · OpenVINO community blog via DevRel · Hugging Face community blog · the `docs/performance/community_export/` staging (in flight by another session — coordinate at author time) | **First win.** Easiest, strongest existing standing, reproducible dataset in hand. Carved into the S1–S4 series (ROADMAP §2). |
| P2 | **When two correct things collide** — the composition-failure specimen collection (enumerated at audit: replay window, self-tripping kill-switch, write-only knowledge bank, unreachable ALLOW, leak-validator swallow, gate-killed-by-instance-lock, recovery-killed-the-patient; exact count re-derived from the journal at author time) | Security education | REACH + security standing | Long-form on home base + Hacker News · LessWrong crosspost · later: BSides CFP (first-timer-friendly) / ACM Queue or IEEE S&P practitioner-department pitch | Each specimen: setup, collision, root cause, structural fix, transferable rule. |
| P3 | **The instrument-trust ladder** — tests → live-verify → instruments that must earn belief; positive controls for AI judges; a deterministic gate under every soft oracle; the honesty machinery (four-grade scale, FALSE-DONE zero tolerance, verdict grammars) | Engineering epistemology | REACH | Home base + LessWrong (the LLM-as-judge reliability debate is live there) · HN | Merges audit threads 3+5 — Phase 0 confirms the merge. Very timely. |
| P4 | **Structural absence beats vigilance** — agent-memory write-path severance vs the industry survey (surveyed systems give the model a pen; this one structurally has none; the OpenClaw self-written-memory *design* as the foil — foil spec binds per VERIFIED_FACTS + P4-verdict §0) | Security architecture | AIGP + security standing | Home base + HN · LessWrong · possibly a short IAPP-angle governance variant | Most externally TIMELY security piece. Careful, verifiable comparisons only. |
| P5 | **The novice was the best instrument in the lab** — the flagship thesis: a domain-blind, rigor-literate human governance layer catches failure classes automated verification structurally cannot (the documented catch-catalog from all five acts) | Flagship essay / governance case study | AIGP (centerpiece) | Long-form on home base · IAPP practitioner channel · LessWrong · workshop-paper stretch (HCI/oversight workshops accept case studies) | Publishes AFTER P1–P3 exist to link to. Inverts the automation-bias literature interestingly — related-work review mandatory. |
| P6 | **One laptop, night-shift fleet** — the accessible narrative: a non-technical person's private local AI system, built by an AI fleet that works while he sleeps | Enthusiast/general | REACH | Home base + HN normal link (Show HN is disqualified per HN's own rules) · outlets (XDA-class) via pickup ONLY — never pitch | Same integrity bar, warmer register. Governance-led hub; links to everything else. |
| P7 | **A cleanup without a gate is a loan** — doc governance for agent-driven projects (the #945 arc: ownerless docs freeze; freshness as a gate test) | Practitioner short | REACH | Home base · dev-adjacent aggregators | Small, quick, optional. |

**Home base (Phase 0 confirms with the LA):** a GitHub Pages blog on the existing
public mirror — zero new infrastructure, canonical URLs he owns, every community post
links back.
**Sequencing rationale (credibility ladder):** P1 → P2/P3 (parallel) → P4 → P5 → P6 →
talks/pitches. arXiv is NOT the door in (new-author endorsement friction); revisit only
if a collaborator materializes.

---

## 2. Phase 0 — the Editorial Board session (one session; ran 2026-07-19)

Mission: turn the inventory into a de-duplicated, venue-checked, LA-approved
publication roadmap and mint the per-piece author briefs. Steps:

1. Ground + gate per CLAUDE.md; fold LA amendments; **record-correction pass** —
   re-derive every carried fact from artifacts (output: `VERIFIED_FACTS.md`).
2. **Author Kit** (`AUTHOR_KIT.md`, same dir): §0 expanded into working rules — voice
   per tier; claim typing (measured / documented-event / interpretation); citation
   formats; privacy/leak screen; the date-and-number verification pass; n=1 framing
   language; the survey rubric (written BEFORE surveyors launch, given to all seven);
   AI-disclosure boilerplate once the LA decides.
3. **Novelty + venue survey** (seven parallel web-research subagents, one per piece,
   all running the shared rubric): what exists, whether our data adds value for expert
   readers, venue fit + submission mechanics + each venue's posting/self-promotion
   rules from primary sources + 2–3 gold-standard exemplar posts per venue. Output:
   per-piece verdicts in `novelty-survey/`.
4. **De-duplicate and scope:** confirm/deny the P3 merge; carve P1 into its post
   series; kill or demote anything saturated. Honest kills are a success condition.
5. **LA decision ceremony** (the only mid-phase stop): roadmap + the standing
   decisions — (a) AI-disclosure stance, (b) home base, (c) venue comfort list,
   (d) threads in flight at once, (e) kill/keep calls.
6. **Mint the machinery:** per-piece tickets in the Publications project; one author
   brief per green-lit piece in `author-briefs/` (committed; template-compliant,
   gate-preserving; carrying: evidence pointers, the survey verdict, venue targets,
   portfolio purpose, format/length guidance, review-panel spec). Journal fragment.
   Ship the whole phase via the normal docs branch-and-merge motion.

## 3. Phase 1+ — author sessions (one per piece; multi-session via handoffs is expected)

Each author session: gate → deep novelty verification (its own pass, deeper than the
survey; a GO/NO-GO it must justify in writing — NO-GO is respectable) → source harvest
(anthology entries verbatim, archive volumes, evidence pack, dataset) → outline →
draft(s): the long-form canonical piece and, where flagged, the short-channel variant
(same facts, different register — never a dumbed-down claim) → self-check against the
Author Kit (including the §B date/number pass) → review panel (§4) → revise → package
for the LA ceremony (final draft + a one-page "what this claims, what supports it,
what reviewers challenged, what changed" memo). The LA approves, requests changes, or
kills. Only after his approval does a session take the named publishing action, and
only the specific one he approved.

## 4. The adversarial review panel (per draft, independent subagents, reviewers never rewrite)

- **Fact auditor:** every claim traced to its artifact (journal line, dataset row, PR,
  commit); every number re-derived; every quote diffed against source; every date
  checked against the §B traps. Output: a claims table with verdicts.
- **Rigor skeptic:** attacks novelty ("who said this before, better?"), overclaiming,
  n=1 overreach, survivorship framing, and any place hedging is missing or dishonest.
- **Audience editor:** does the piece earn its length for the target venue; is the
  register right for the tier; would an expert keep reading past paragraph two.
- **Integrity/privacy screen:** personal-data leakage, security-sensitive residuals,
  public-framing compliance, disclosure-stance compliance, venue-rules compliance
  (self-promo policies from the survey), tone (no praise-seeking, no vendor-bashing;
  collaborative-upstream rules where a community is named).
A draft ships to the LA only when the fact auditor reports zero unresolved reds and
the author has dispositioned every panel finding in writing (accept/fix/rebut).

## 5. What this program is NOT

Not marketing, not volume content, not a race. If the whole program yields three
pieces that genuine experts respect, it has succeeded. Every session inherits the
motto: mature not minimal — and its publication corollary: published means defensible.

## 6. Program filesystem + tracking

```
docs/research/publication-program/     ← COMMITTED (LA amendment 2 — durability)
  README.md            this file — canonical instruction
  AUTHOR_KIT.md        working rules + survey rubric (§2.2)
  VERIFIED_FACTS.md    the checked fact sheet; volatile items re-verified at draft time
  novelty-survey/      P1..P7 one-page verdicts with sources
  ROADMAP.md           the sequenced, LA-decided roadmap (draft until ceremony)
  author-briefs/       one gate-preserving brief per green-lit piece
```
Vikunja: project **Publications** (13) — epic #956, Phase 0 #957, one ticket per
green-lit piece. Upstream CODE work stays in OSS Contributions (LA amendment 5).
Ships happen by the normal docs branch-and-merge motion, fragment included — never
handoffs-only artifacts (that dir sweeps after 7 days).

## Amendment log

**2026-07-19 (LA, at the Phase 0 gate) — seven binding amendments:**
1. Record correction + mandatory date/number verification pass (two date errors were
   made at the gate itself; the journal is 58 days old, not "two years"; the project
   ~5.5 months — first commit 2026-02-04).
2. Program artifacts are committed repo files here, not handoffs-only; this README
   supersedes the handoffs brief.
3. One shared survey rubric written before surveyors launch; venue research from
   primary sources incl. posting/self-promo rules + exemplar posts.
4. Prior-work treatment in every expert-facing piece; methods section in every data
   piece; n=1 framing everywhere.
5. Dedicated Publications Vikunja project.
6. Every author brief names its portfolio purpose (AIGP / OV standing / reach).
7. Standing reminder: research is read-only everywhere; no engagement anywhere in any
   phase without explicit per-piece LA approval.
