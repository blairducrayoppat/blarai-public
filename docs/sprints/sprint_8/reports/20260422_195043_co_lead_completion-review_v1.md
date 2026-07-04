---
role: co_lead_architect
phase: completion-review
revision: 1
tracking_task: 82
sprint_id: 8
reviewed_artifact: docs/scheduled/ea_queue/staging/P5_TASK8_EA3_UI_HARDENING.xml
reviewed_against:
  - docs/P5_TASK8_SDO_CONTINUATION_v1.0.xml (§5 EA-3 lines 255-274)
  - docs/sprints/sprint_8/strategic_design_vision.md (§5.1 item 3)
posted_at: 2026-04-22T19:50:43Z
verdict: ADJUST
---

# Sprint 8 EA-3 Staged-Prompt Completion Review

## Verdict

**ADJUST** — one blocker (phantom required-attachment). Not a strike (per Co-Lead template ADJUST semantics). SDO re-authors in staging/ and re-submits.

## Staged artifact

- Path: `docs/scheduled/ea_queue/staging/P5_TASK8_EA3_UI_HARDENING.xml`
- Authored: 2026-04-22 (SDO)
- Commit: `885ce6c` — `[agent:sdo] author EA-3 prompts (staged, awaiting Co-Lead review) for Task 82 + Task 121`

## What's strong (non-blocking — worth preserving through revision)

- **15 work items** with priority tiers (7 HIGH / 6 MEDIUM / 2 LOW) and production-realistic acceptance each.
- **8 risks** with concrete resolutions: Textual App construction-only strategy (I.1), `asyncio.to_thread` monkeypatch pattern (I.2), LOCALAPPDATA path-shape assertion (I.7), `asyncio.sleep` AsyncMock pattern (I.8), production-string authority (I.5), EA-2 overlap avoidance (I.4), boot-poll entanglement fallback (I.6), deprecated-loop-API hygiene (I.3).
- **8 negative constraints** including strong L-15 production-file prohibition, no-new-seams rule (NC-7), no live Textual App (NC-6), scope-limited test dirs (NC-8).
- **Comprehension-gate structural recitation** A-J with strict section ordering.
- **Quality gates**: COMPILE / TEST-FOCUSED / TEST-FULL / ORACLE with concrete pytest commands and ORACLE grep filter.
- **Mature-not-minimal** 1-hour adjacent-work cap explicit (§10).

## Blocker — phantom required attachment

The prompt references `docs/sprints/sprint_8/audit/ea3_scope_audit.md` in three load-bearing places:

1. **Required attachment** (line ~845) with reason `"SDO scope audit — exact line anchors, missing-test names, priority classifications for every WI"`.
2. **Milestone objective** (line 78) anchors narrative to this audit's findings.
3. **`source=` attribute on 11 of 15 WIs** — e.g. `"ea3_scope_audit.md §1 (transport.py:545-550)"`, `"ea3_scope_audit.md §3 (transport.py:258-260)"`, `"ea3_scope_audit.md §5 (app.py:405-445)"`.

### Verification

- `find . -path ./.git -prune -o -iname "*ea3*scope*" -print` → empty.
- `find . -path ./.git -prune -o -type d -name "audit" -print` → empty (no `audit/` directory anywhere under `docs/sprints/`).
- `docs/P5_TASK8_SDO_CONTINUATION_v1.0.xml` §5 EA-3 block (lines 255-274) does **not** reference the audit file either — it was introduced during EA-3 prompt authoring without the underlying artifact.

### Consequence

- The EA's L-12 comprehension-gate recitation of `FILES TO READ` will fail on the missing file.
- If the EA proceeds anyway, WI scope is anchored to non-existent §-numbered findings — the EA will either fabricate scope from reading production code (no authoritative line anchors), or produce coverage that misses the actual gap set.

## Guidance to SDO

Choose one of two revision paths. Both are acceptable; SDO decides based on effort vs. future reuse.

### Path A — Author the audit doc first (preferred)

Create `docs/sprints/sprint_8/audit/ea3_scope_audit.md` with the `§1`-`§9` structure the prompt assumes. For each existing WI, the audit doc should contain:

- Exact production file + line range anchor.
- 2-3 sentence problem statement (what coverage is missing / what assertion is tautological).
- Priority classification (HIGH / MEDIUM / LOW) with rationale.

Then re-stage the EA-3 prompt unchanged (attachment now resolves).

**Benefit**: future sprints can reference the audit artifact. Matches the pattern of having an explicit SDO scope-analysis output.

### Path B — Remove the audit dependency from the prompt

- Strike the `ea3_scope_audit.md` required-attachment entry.
- Rewrite each WI's `source=` attribute to cite directly: continuation XML §5 EA-3 + the production file + line range (most WI bodies already carry the line range in parentheses, e.g. `(transport.py:545-550)` on WI-1).
- Update §3 milestone `<objective>` to anchor against continuation XML EA-3 scope and SDV §5.1 item 3 directly.

**Benefit**: faster. Prompt-internal coherence preserved.

## Non-blocking observations

- **`parent_head` `df686b8`**: one SDO authoring commit behind current main HEAD `885ce6c` (the EA-3 prompt commit itself, which adds no code). The prompt's L-13 rebase-if-advanced instruction covers this. Acceptable.
- **Predecessor ledger id** `20260422_184004_sprint8_ea2_ao_sr_hardening` verified present at `docs/ledger/20260422_184004_sprint8_ea2_ao_sr_hardening.md`.
- **Oracle grep filter** at line 741 correctly negates `tests|conftest|docs|pyproject` — L-15 machine-verifiable.

## Label action

- `Gate:Pending-CoLead` (id 10): **retained** (ADJUST keeps the gate open).
- `Gate:Approved` (id 12): untouched. Stale from EA-2 cycle; not cleaned in this phase.

## Strike count

ADJUST is not a strike. No increment.
