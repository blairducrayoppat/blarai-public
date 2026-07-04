# SDO Prompt-Discipline Checklist

**Purpose**: Quarterly spot-check that SDO-generated EA prompts are maintaining the discipline codified in lessons L-12, L-13, and related rules.

**Source of authority**: Recommendation §6.3 (`docs/CLAUDE_WORKFLOW_OPTIMIZATION_D7.md`). Reinforces the EA Prompt Library checklist at `docs/claude_projects/03_EA_PROMPT_LIBRARY_INSTRUCTIONS.md` §EA-prompt-review-checklist.

**Reviewer**: Co-Lead Architect (Tier 1). Not the SDO itself — this is an independence check.

**Cadence**: quarterly OR every 5 EA prompts produced by the SDO, whichever comes first.

---

## 1. Why this check exists

Two incidents in Task 7 produced corrective re-execution:

- **L-12** (2026-04-18, ledger Entry 40) — EA-1 produced semantically correct content but violated the deliverable's structural contract. Root cause: the EA prompt's comprehension gate did not force verbatim structural recitation.
- **L-13** (2026-04-18, ledger Entry 41) — EA-2 branched from a stale main commit before predecessor corrections merged. Root cause: the EA prompt did not specify exact `parent_head` and did not require the EA to verify match.

Both lessons are codified in role instructions. **Codification is not enforcement.** Over time, SDO prompt-generation discipline can drift. This check catches drift early.

---

## 2. What to pull for review

From the most recent quarter (or last 5 EAs), collect the EA prompt `.xml` files:

```powershell
$git = 'C:\Program Files\Git\cmd\git.exe'
$repo = 'C:\Users\mrbla\BlarAI'
# List recent EA prompts via git log
& $git -C $repo log --since='3 months ago' --diff-filter=A --name-only --pretty=format: -- 'docs/P*_TASK*_EA*.xml' 'docs/P*_TASK*_EA_*.xml' | Sort-Object -Unique | Where-Object { $_ -ne '' }
```

---

## 3. The checklist (apply to EACH pulled prompt)

### C-1. Comprehension gate — structural recitation requirement (L-12)

Open the prompt. Find the `<comprehension_gate>` section. **Does it require the EA to recite the exact deliverable structure verbatim — file names, section headers, content boundaries — before executing?**

- PASS: explicit "recite the following structure verbatim" or equivalent mandate.
- FAIL: gate only asks for a general summary.
- CONCERN: gate mentions structure but doesn't force recitation.

### C-2. Negative constraints (L-12)

Find `<role_constraints>` or equivalent. **Are there explicit negative constraints (what the EA must NOT do)?**

- PASS: bullet list of ≥3 negative constraints relevant to the milestone's common overreach patterns (e.g., "DO NOT add sections", "DO NOT rename required headers", "DO NOT populate deferred stubs").
- FAIL: only positive constraints, or no negative-constraint section.
- CONCERN: generic negatives that don't address foreseeable overreach for this milestone.

### C-3. Exact parent_head (L-13)

Find `<metadata>` or `<branch_setup>`. **Is there an exact `parent_head` commit SHA, and does the EA prompt require the EA to verify match before branching?**

- PASS: exact SHA + verification command (`git rev-parse HEAD`).
- FAIL: missing `parent_head` entirely, or references a branch name only.
- CONCERN: `parent_head` present but no verification command.

### C-4. Verification commands (Non_Dev_Verification_Requirement)

Find `<verification>`. **Are the verification commands verbatim, copy-pasteable terminal commands that the Lead Architect can run without reading code?**

- PASS: every command is runnable as-is; no placeholders.
- FAIL: instructions like "run the tests" or "check the output" without the actual command.
- CONCERN: commands present but require the Lead Architect to substitute paths or arguments.

### C-5. Oracle / DOC_ONLY gate where applicable

If the milestone is DOC_ONLY, **does `<quality_gate>` include an `ORACLE` check asserting `git diff --name-only` shows only documentation paths?**

- PASS: ORACLE present with exact allowed-paths list.
- FAIL: no ORACLE for a DOC_ONLY milestone.
- CONCERN: ORACLE present but allowed paths are too broad.

### C-6. Rollback instructions

**Is there a rollback section with exact commands to revert the milestone if something goes wrong?**

- PASS: exact `git checkout HEAD -- <files>` or branch-delete command.
- FAIL: no rollback section.
- CONCERN: rollback described in prose without commands.

### C-7. Commit template

**Is there a pre-formatted commit message with HEREDOC syntax?**

- PASS: complete commit command block with correct HEREDOC.
- FAIL: no commit template.
- CONCERN: template present but incomplete (placeholder strings, wrong HEREDOC syntax).

### C-8. Comprehension gate posts to Agent Gates bus (2026-04-19+ prompts only)

For prompts produced after 2026-04-19 (Agent Gates bus landing), **does the comprehension gate instruct the EA to submit its gate to Vikunja Project 6 with label `Gate:Pending-SDO` and title prefix `[EA-<M>]`?**

- PASS: explicit gate-bus submission instructions with exact label and title pattern.
- FAIL: no gate-bus submission (pre-2026-04-19 prompts are exempt).
- CONCERN: submission mentioned but label / title pattern incorrect.

---

## 4. Output format

For each prompt reviewed, produce a row:

```xml
<prompt_discipline_review prompt="docs/P5_TASK7_EA3_UI_GATEWAY_UI_SHELL_AUDIT.xml" reviewed="2026-07-20" reviewer="CoLead">
  <C1_structural_recitation>PASS</C1_structural_recitation>
  <C2_negative_constraints>PASS</C2_negative_constraints>
  <C3_parent_head>PASS</C3_parent_head>
  <C4_verification_commands>CONCERN — test command requires substitution</C4_verification_commands>
  <C5_oracle>PASS</C5_oracle>
  <C6_rollback>FAIL — missing</C6_rollback>
  <C7_commit_template>PASS</C7_commit_template>
  <C8_gate_bus_submission>PASS</C8_gate_bus_submission>
  <overall>2 concerns; recommend amend-on-next-edit</overall>
</prompt_discipline_review>
```

Aggregate across prompts: report counts of PASS / FAIL / CONCERN per checklist item. If any item shows > 50% FAIL across the window, that's a drift signal — surface to the Lead Architect with a recommended SDO-instruction edit.

---

## 5. Scheduled reminder setup (one-time, on the Lead Architect's machine)

This creates a Windows Task Scheduler entry that creates a Vikunja reminder ticket every three months.

### 5.1 Prerequisites

- Vikunja CLI wrapper at `tools/vikunja_mcp/cli.py` or direct Vikunja REST access.
- Python 3 installed.
- Vikunja running at startup (see `tools/vikunja/vikunja-v2.3.0-windows-4.0-amd64.exe`).

### 5.2 Create the reminder-producer script

Save as `C:\Users\mrbla\BlarAI\tools\vikunja_mcp\schedule_sdo_discipline_check.py`:

```python
"""Quarterly reminder: Co-Lead should run the SDO prompt-discipline checklist."""
import os
import sys
import httpx

BASE_URL = os.environ.get("VIKUNJA_URL", "http://localhost:3456/api/v1")
TOKEN = os.environ.get("VIKUNJA_TOKEN")  # set from your local env

TITLE = "Quarterly SDO prompt-discipline check (Co-Lead)"
DESCRIPTION = (
    "Quarterly reminder per `docs/runbooks/SDO_PROMPT_DISCIPLINE_CHECKLIST.md`. "
    "Co-Lead: pull the last quarter's EA prompts, apply the C-1 through C-8 "
    "checklist, produce the XML review block. Aggregate drift signals."
)

def main() -> int:
    if not TOKEN:
        print("VIKUNJA_TOKEN not set; refusing to create reminder.", file=sys.stderr)
        return 2
    headers = {"Authorization": f"Bearer {TOKEN}"}
    # Project 4 = BlarAI Infrastructure
    payload = {"title": TITLE, "description": DESCRIPTION, "priority": 2}
    r = httpx.put(f"{BASE_URL}/projects/4/tasks", headers=headers, json=payload, timeout=10)
    r.raise_for_status()
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

### 5.3 Register the scheduled task (run once, elevated PowerShell)

```powershell
$action = New-ScheduledTaskAction -Execute 'py' -Argument '-3 C:\Users\mrbla\BlarAI\tools\vikunja_mcp\schedule_sdo_discipline_check.py'
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddDays(1).AddHours(9) -RepetitionInterval (New-TimeSpan -Days 90)
Register-ScheduledTask -TaskName 'BlarAI-SDO-Discipline-Check' -Action $action -Trigger $trigger -Description 'Quarterly Co-Lead reminder to audit SDO prompt discipline (L-12, L-13).'
```

### 5.4 Verify the task is registered

```powershell
Get-ScheduledTask -TaskName 'BlarAI-SDO-Discipline-Check'
```

---

## 6. Cross-references

- [03_EA_PROMPT_LIBRARY_INSTRUCTIONS.md](../claude_projects/03_EA_PROMPT_LIBRARY_INSTRUCTIONS.md) §EA-prompt-review-checklist — primary source of the checklist items.
- [01_CO_LEAD_ARCHITECT_INSTRUCTIONS.md](../claude_projects/01_CO_LEAD_ARCHITECT_INSTRUCTIONS.md) §EA-prompt-review-checklist — Co-Lead's parallel checklist.
- [POST_OPERATIONAL_MATURATION_LEDGER.md](../POST_OPERATIONAL_MATURATION_LEDGER.md) Entries 39, 40, 41 — L-12 and L-13 incident records.
- §6.3 in [CLAUDE_WORKFLOW_OPTIMIZATION_D7.md](../CLAUDE_WORKFLOW_OPTIMIZATION_D7.md).
- [claude-projects-dirty-check scheduled task precedent](../CLAUDE_PROJECTS_MANIFEST.md) — Domain 4 pattern this runbook emulates.

---

## 7. Document lifecycle

- **v1.0** — 2026-04-20 — initial, authored during Domain 7 recommendations implementation (§6.3).
