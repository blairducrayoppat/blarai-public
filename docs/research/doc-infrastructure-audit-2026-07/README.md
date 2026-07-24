---
title: Documentation-Infrastructure Audit + Archive Mining — Evidence Pack
status: reference
area: research
---

# Documentation-Infrastructure Audit + Archive Mining — Evidence Pack (2026-07-18)

*Plain summary: the full evidence behind the 2026-07-18 Archivist's Report — measured read
patterns from 771 session transcripts, the 7-agent mining of all 465 BUILD_JOURNAL entries,
the 284-lesson disposition, the doctrine staleness audit, the archive architecture, and the
ten-decision restructure sheet awaiting LA triage on Vikunja #945.*

**LA-facing report (read this first):** https://claude.ai/code/artifact/55cd953d-9d84-494b-8099-b6166328ddde
(a self-contained copy is committed here as `archivists_report.html`).

**Status of the work:** this pack is EVIDENCE ONLY. Nothing was restructured, moved, or
deleted in the repo by the audit itself. The restructure executes only after LA triage of
decisions D1–D10 (recorded on #945, mirrored in the report §11). Ticket #267's April
archive-not-delete decision and `docs/governance/doc-lifecycle.md` are the standing policy
this work extends.

## Headline findings

1. **Cost, measured:** ~14.5K tokens auto-inject into every session AND subagent
   (CLAUDE.md ~9.6K + memory index ~4.9K; ≈11M lifetime tokens across 771 transcripts).
   The mandated session-start reads add ~9K more, much of it stale.
2. **The worst poison:** `docs/sprints/ACTIVE_SPRINT.md` — force-read every session,
   15/15 recent reads full-file, ~80% of its active-block claims false (frozen 2026-06-07).
3. **Root cause (systemic):** every frozen doctrine surface names a maintenance owner that
   is a retired role ("Co-Lead Architect Phase 3", "the EA that changes test counts");
   every healthy surface (DECISION_REGISTER, FIELD_NOTES, handoff template) has a living
   owner. Ownerless docs freeze; a freshness gate must enforce what vigilance cannot.
4. **Three gate counts:** CLAUDE.md 8518 · TEST_GOVERNANCE 8490 · copilot-instructions 2212
   — three always-on surfaces, three different "current" baselines, sync rule unenforced.
5. **The journal is a mine, not a landfill:** ~50% genuinely-narrative; 62 KEEP-HOT gems;
   five acts; six cross-era threads (novice-as-instrument · two-correct-things-collide ·
   instrument-trust ladder · dormancy grammar · honesty economy · upstream citizenship).
6. **LESSONS.md:** 284 lessons / ~81K tokens, read 87× in the last 14 days; tiering cuts
   the mandatory pre-mint search to ≤7K (−91%). The corpus's own L196 + L217 prescribe
   exactly this restructure.
7. **19 live tug-vector surfaces** present retired worlds as current; the three
   `/sprint-*` commands are the strongest (43 retired-term hits; `/sprint-kickoff` boots
   "Co-Lead Architect mode").
8. **Corrected during audit:** the agentic-setup coder brief does NOT load per-dispatch
   (earlier claim wrong; it is a build spec — the per-dispatch surface is opencode's
   AGENTS.md). docs/security's 290 MB is git-ignored vendored node_modules, not content.

## Decision sheet (LA triage — full text in the report §11 and on #945)

D1 journal monthly rotation + 62-gem anthology · D2 LESSONS three-tier (canon-32 / index /
archive) · D3 retire+replace ACTIVE_SPRINT · D4 TEST_GOVERNANCE §1 slim · D5 PERFORMANCE_LOG
rotation + insertion-order fix · D6 execute #267's one-time archive moves · D7 rewrite
copilot-instructions + retire latent old-fleet manuals · D8 re-own/budget/gate-check every
always-loaded doc (freshness gate + retired-lexicon scanner + owned monthly rotation) ·
D9 slim the build-spec brief + clear node_modules debris · D10 rewrite the three /sprint-*
commands for the current world.

## File inventory

| File | What it is |
|---|---|
| `archivists_report.html` | The LA-facing visual report (self-contained copy of the artifact) |
| `transcript_read_patterns.txt` | Measured read patterns from 771 transcripts (summary tables) |
| `mine_transcripts.py` | The transcript-mining instrument (stdlib-only, re-runnable) |
| `journal_mine_chunk_1..7.md` | Per-era mining of all 465 journal entries (gems, LA moments, motifs, waste, verdicts) |
| `synthesis_journal_gems.md` | Cross-era synthesis: five acts, six threads, anthology proposal |
| `lessons_mine.md` | All-284 lesson disposition, canon-32, meta-lessons, tier design |
| `doctrine_audit.md` | Per-file staleness verdicts, the 19-entry tug-vector register, slim targets, structural controls |
| `logs_archives_audit.md` | Append-log anatomy, handoffs/sprints/ledger census, unified archive architecture |
| `crossrepo_sweep.md` | agentic-setup, worktree inventory, memory dispositions, skills register |
| `claude_md_memory_assessment.md` | CLAUDE.md section-by-section + memory-index prune plan |

*Method note: journal mining ran as 7 parallel era-scoped agents + 1 synthesis; specialist
audits as 4 parallel agents; read patterns measured (not estimated) from every stored
transcript. Where an agent's finding contradicted the briefing (the dispatch-brief premise,
the snapshot-drift direction), the on-disk finding won and the correction is recorded.*
