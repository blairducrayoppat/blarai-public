# BlarAI Ledger (Q1-1 directory-per-entry, 2026-04-22)

This directory is the **go-forward** home for ledger entries. Each entry lives in its own file. This structure eliminates the merge-conflict class that Sprint 8 EA-1 and Sprint 9 EA-1 hit 2026-04-22, when both branches independently claimed the next incremental "Entry 51" in the monolithic `docs/POST_OPERATIONAL_MATURATION_LEDGER.md`.

## Filename convention

```
<YYYYMMDD_HHMMSS>_sprint<N>_ea<M>_<short-slug>.md
```

- `YYYYMMDD_HHMMSS` — UTC timestamp of entry authoring. **Sortable**. Collision-free.
- `sprint<N>` — the DEC-15 `sprint_id` that this entry belongs to.
- `ea<M>` — the EA milestone number within that sprint.
- `<short-slug>` — lower-kebab-case short description (≤ 40 chars).

**Example**: `20260422_163000_sprint9_ea1_security-wire-protocol.md`

Non-EA entries (Co-Lead sprint transitions, configuration-agent domain closeouts, etc.) substitute the `ea<M>` segment:
- Co-Lead SCR: `20260425_120000_sprint9_scr_governance-documentation.md`
- Configuration Agent: `20260422_080000_domain9_closeout.md`

## Frontmatter (required)

Every entry starts with YAML frontmatter:

```yaml
---
ledger_id: <free-form short id, unique within this directory — often same as filename stem>
date: <YYYY-MM-DD>
sprint_id: <int, or null for non-sprint work>
entry_type: EA | SCR | SWAGR | CAR | DOMAIN-CLOSEOUT | OTHER
predecessor: <ledger_id of predecessor entry, or "Entry <N>" for pre-2026-04-22 monolithic entries>
branch: <feature branch name, or null>
merge_commit: <7-char hash of the merge to main, or null if not merged>
disposition: COMPLETE | PARTIAL | ROLLED-BACK | ARCHIVED
---
```

## Body

Same markdown structure as the monolithic-era entries: Summary → Deliverables → Files Changed → Quality Gate → any entry-specific sections. See the monolithic `docs/POST_OPERATIONAL_MATURATION_LEDGER.md` final entries (Entry 51, Entry 52) for pattern reference.

## Legacy monolithic ledger

`docs/POST_OPERATIONAL_MATURATION_LEDGER.md` contains Entry 1 through Entry 52 (closed 2026-04-22). It is **frozen** — no new entries appended. Historical references to that file remain valid (all ~100 existing cross-references point to the frozen archive, no updates needed).

The monolithic ledger's numbered sequence (Entry 1..52) does not continue here. Per-entry files use timestamp-based filenames instead of sequential numbers, eliminating the collision class that forced the migration. If a tool needs a chronological roll-up for human reading, it reads the monolithic file first, then `ls docs/ledger/` sorted chronologically, and concatenates.

## Why timestamp instead of incremental number

Two EAs on two parallel branches, each reading main's current ledger, will both correctly compute "next = Entry N+1" and commit their entries to the monolithic file at the same line range. When the second branch merges, git sees "both sides added an Entry N+1" — unresolvable auto-merge.

Timestamp filenames avoid this: two EAs authoring simultaneously produce `20260422_163000_*` and `20260422_163015_*`, distinct files, zero merge conflict.

## Rendering a combined chronological view

Not yet automated (deferred as "nice-to-have" — the directory listing itself is chronologically sortable). If a future tool is needed:

```bash
# Chronological ledger render (shell)
cat docs/POST_OPERATIONAL_MATURATION_LEDGER.md
echo "---"
for f in $(ls docs/ledger/*.md | sort); do
  [[ "$f" == *README.md ]] && continue
  echo ""
  cat "$f"
  echo ""
done
```

## Authoring guidance for SDO-authored EA prompts

SDO authors EA prompts. When the prompt includes a "ledger entry update" deliverable, SDO must specify the target path using the convention above — NOT appending to `docs/POST_OPERATIONAL_MATURATION_LEDGER.md`. See `docs/scheduled/wake_templates/sdo.md` § "Ledger entry convention (Q1-1)" for the authoritative template.
