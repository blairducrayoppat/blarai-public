---
ledger_id: 20260512_172500_sprint11_ea5_cleanup-batch
date: 2026-05-12
sprint_id: 11
entry_type: EA
predecessor: 20260512_162515_sprint11_ea4_test-baseline-drift.md
branch: feature/p5-task11-ea5-cleanup-batch
merge_commit: <written-on-merge>
disposition: COMPLETE
---

# Sprint 11 EA-5 — Doctrine + Doc-Hygiene Cleanup Batch

## Summary

Sprint 11 EA-5 ships the cross-repo cleanup batch closing Sprint 10's
remaining MINOR doctrine defects and the long-pending Stage 6.7.5
doc-hygiene items. Co-Lead direct execution under LA-delegated authority
(consistent with EA-4 same-sprint bypass).

**Five deliverables across both repos**:

1. **BlarAI `.github/copilot-instructions.md:93`** — narrative `DEC-15
   sprint lifecycle, fleet-driven` phrase replaced with a structured
   `<sprint_lifecycle_pointer>` element pointing at devplatform doctrine.
   Closes Sprint 10 SWAGR §13 gap #2.
2. **devplatform `CLAUDE.md`** — 13 `<BlarAI>` template tokens expanded
   to literal `C:\Users\mrbla\BlarAI` absolute paths. Closes Sprint 10
   SWAGR §13 gap #3 (cross-reference style asymmetry).
3. **devplatform `docs/decisions/DEC-19_cross-reference-style-convention_v1.md`** —
   new formal DEC ratifying absolute-paths-everywhere as the canonical
   cross-repo cross-reference convention (\~140 lines, mature-not-minimal
   floor exceeded). Joins DEC-16/17/18 (Sprint 11 EA-1 bundle) in the
   devplatform `docs/decisions/` directory.
4. **devplatform `docs/scheduled/wake_templates/sprint_auditor.md` §2.2** —
   NARROW EXCEPTION clause added permitting strictly-read-only sweep of
   the single sprint-close `[agent:co_lead][phase:completion]` Vikunja
   comment on the tracking task during SWAGR §5.1 row "Sprint-close
   comment" verification. Explicit guardrails: one comment per audit,
   post-SCR timestamp gate, read-only, scope-limited. Closes Sprint 10
   SWAGR §13 gap #5 and Sprint 9 SWAGR §15.3 carry-over.
5. **devplatform `tools/vikunja_mcp/README.md`** — Quick Start `cd`
   references fixed to use absolute devplatform paths (was
   `cd tools\vikunja` and `cd C:\Users\mrbla\BlarAI` — the latter
   pointed at a tree that no longer holds the server post Stage 4/6
   platform separation). Cwd-agnostic invocation. Stage 6.7.5 doc-hygiene
   backlog item closed.

## Deliverables

| Artifact | Path | Repo | Lines changed |
|---|---|---|---|
| copilot-instructions.md L93 fix | `.github/copilot-instructions.md` | BlarAI | +2 / −1 |
| devplatform CLAUDE.md token expansion | `CLAUDE.md` | devplatform | 13 substitutions in place |
| DEC-19 | `docs/decisions/DEC-19_cross-reference-style-convention_v1.md` | devplatform | +140 (new) |
| sprint_auditor.md §2.2 amendment | `docs/scheduled/wake_templates/sprint_auditor.md` | devplatform | +13 / −1 |
| vikunja_mcp README Quick Start | `tools/vikunja_mcp/README.md` | devplatform | +5 / −3 |
| EA-5 ledger entry | `docs/ledger/20260512_172500_sprint11_ea5_cleanup-batch.md` | BlarAI | this file |

## Files Changed

### BlarAI side
- `.github/copilot-instructions.md` — L93 narrative fix.
- `docs/ledger/20260512_172500_sprint11_ea5_cleanup-batch.md` — this entry.

### devplatform side (already committed at `2b06d79`)
- `CLAUDE.md` — 13 `<BlarAI>` → `C:\Users\mrbla\BlarAI` substitutions.
- `docs/decisions/DEC-19_cross-reference-style-convention_v1.md` — new DEC.
- `docs/scheduled/wake_templates/sprint_auditor.md` — §2.2 NARROW EXCEPTION clause.
- `tools/vikunja_mcp/README.md` — Quick Start cd fixes.

## Verification Matrix

| Check | Expected | Result | Evidence |
|---|---|---|---|
| copilot-instructions.md regex (Sprint 10 SDV criterion #1 + Sprint 11 SDV criterion #5) returns zero non-pointer matches | DEC-15 reference now inside `<sprint_lifecycle_pointer>` element | Confirmed | `grep -n "DEC-15" .github/copilot-instructions.md` returns single match inside pointer XML element |
| `grep -n "<BlarAI>" devplatform/CLAUDE.md` returns zero | All 13 tokens expanded | Confirmed | Post-edit grep returns no matches |
| DEC-19 file exists on devplatform main | ≥ 50-line mature-not-minimal floor | Confirmed (\~140 lines) | `docs/decisions/DEC-19_*.md` present |
| sprint_auditor §2.2 has NARROW EXCEPTION clause | Sprint-close comment read-only sweep guardrails present | Confirmed | New text inserted; 4 explicit guardrails (single comment, timestamp gate, read-only, scope-limited) |
| vikunja_mcp README Quick Start uses absolute paths | `cd` references are cwd-agnostic | Confirmed | Lines 31, 42, 158 updated |
| BlarAI commit on feature branch | `[sprint:11][role:co_lead][phase:completion]` tag | This commit | Single BlarAI commit covers both BlarAI-side edits + ledger |

All checks PASS. Sprint 11 SDV v3 success criteria #5, #6, and #7 satisfied on this commit.

## Quality Gate

- **Mature-not-minimal**: DEC-19 at \~140 lines well exceeds the 50-line floor; sprint_auditor.md §2.2 amendment has full guardrails not just a single-line allowance; vikunja_mcp README fix replaces both stale `cd` references and adds a one-line context note explaining why the path moved.
- **Fail-closed safety**: no impact. No production source touched, no test files touched, no test config touched.
- **Privacy mandate**: held. No external network calls.
- **Cross-repo discipline**: devplatform-side committed first (per Stage 6.7.5 direct-to-main N-6) at `2b06d79`; BlarAI-side feature branch (this branch) commits after, merges via standard trusted_scope pathway (or direct merge under LA-delegated authority).
- **Sprint 11 SDV v3 success criteria #5, #6, #7**: all satisfied per Verification Matrix above.

## Decision

`PASS` (Co-Lead direct execution; LA-delegated).

## Sprint 11 Status After This Merge

5 of 5 EAs complete. Sprint 11 is now ready for SCR (Strategic Completion
Report) authoring by Co-Lead Phase 3. The Sprint Auditor will subsequently
fire on its next cadence to author the SWAGR.

The Sprint 11 SCR §14.1 carry-overs to Sprint 12 (already enumerated in
EA-4's investigation report §7) are:

1. Fleet bug — within-sprint parallel EA + multi-EA-on-same-tracking-task
   state-machine misclassification.
2. Fleet bug — Vikunja label-revert phenomenon on tracking task #410.

Both warrant Sprint 12 attention before any future within-sprint parallel
sprint is attempted.

---

*Sprint 11 EA-5 ledger entry. Q1-1 per-file format per DEC-17 (Sprint
11 EA-1 deliverable). Cross-references DEC-19 (this EA's primary new
artifact). Authored by Co-Lead under LA-delegated authority 2026-05-12;
bypassing the standard EA Code chain due to documented fleet bugs (see
Sprint 11 SCR §14.1 carry-overs).*
