# BlarAI Claude Chat Projects — Setup and Governance

**Purpose:** This directory is the source of truth for the four Claude Chat Projects that
embody the multi-agent workflow used to develop BlarAI. The detailed role instructions
here are read by Project chat sessions via the filesystem MCP server at session start;
the Claude Desktop "Custom Instructions" UI field holds only a short pointer block.

This pattern keeps role instructions version-controlled in git and eliminates the manual
"re-paste after every edit" failure mode.

---

## The four Projects (created in Claude Desktop → Chat → Projects)

| # | Project name | Tier | Role summary | Detailed instructions |
|---|---|---|---|---|
| 1 | **BlarAI — Co-Lead Architect** | T1 | Persistent strategic advisor, reviews SDO gates, generates SDO init prompts | [01_CO_LEAD_ARCHITECT_INSTRUCTIONS.md](01_CO_LEAD_ARCHITECT_INSTRUCTIONS.md) |
| 2 | **BlarAI — SDO (Active Task)** | T2 | Task-scoped strategic orchestrator, reviews EA gates, generates EA prompts | [02_SDO_INSTRUCTIONS.md](02_SDO_INSTRUCTIONS.md) |
| 3 | **BlarAI — EA Prompt Library** | Reference | Assist drafting/reviewing EA prompts; never execute EA work | [03_EA_PROMPT_LIBRARY_INSTRUCTIONS.md](03_EA_PROMPT_LIBRARY_INSTRUCTIONS.md) |
| 4 | **BlarAI — Core Reference** | Shared | Pure knowledge base; answer questions about the project | [04_CORE_REFERENCE_INSTRUCTIONS.md](04_CORE_REFERENCE_INSTRUCTIONS.md) |

---

## Comprehension-gate ladder — Vikunja-bus based

```
EA fires comprehension gate          → SDO reviews + posts response via Agent Gates bus
SDO fires comprehension gate         → Co-Lead Architect reviews + posts response via Agent Gates bus
Co-Lead fires comprehension gate     → Human Lead Architect reviews (Gate:Pending-Human)
```

All gate flow goes through Vikunja project **BlarAI Agent Gates** (ID 6).
Reviewers poll their `Gate:Pending-<role>` label at session start. The
Lead Architect is NO LONGER a copy-paste pipe — the Human is only a
reviewer (for Co-Lead gates) and an operator (wakes Project chats until
Domain 8 autonomy lands).

Canonical protocol: [docs/CLAUDE_AGENT_GATE_PROTOCOL.md](../CLAUDE_AGENT_GATE_PROTOCOL.md)

Today: Lead Architect clicks between Project chats to "wake" each agent
(the agent's session-start polling drains its queue). Domain 8 replaces
these clicks with scheduled tasks / webhooks.

---

## Filesystem MCP usage policy (applies to all four Projects)

All four Projects have access to the filesystem MCP server scoped to
`C:\Users\mrbla\BlarAI`. **Use it read-only.**

- ✅ ALLOWED: `read_text_file`, `read_multiple_files`, `list_directory`,
  `directory_tree`, `search_files`, `get_file_info`, `list_allowed_directories`
- ❌ FORBIDDEN in Desktop chat: `write_file`, `edit_file`, `move_file`,
  `create_directory`

If you need to modify a file, produce the change as text and hand it to the
Lead Architect to apply via Claude Code (which tracks all writes in git).

This policy is repeated in every detailed instructions file so it is
enforceable even if this README is not consulted.

---

## Setup procedure (one-time per Project)

For each of the four Projects:

1. **Create the Project**
   - Claude Desktop → Chat → Projects → "New project" (top right)
   - Name: exactly as listed in the table above (copy-paste to avoid typos)
   - Description: see per-Project section in [CUSTOM_INSTRUCTIONS_UI_PASTE.md](CUSTOM_INSTRUCTIONS_UI_PASTE.md)

2. **Set Custom Instructions**
   - Inside the Project, click the Project name → "Set project instructions"
   - Paste the short block from [CUSTOM_INSTRUCTIONS_UI_PASTE.md](CUSTOM_INSTRUCTIONS_UI_PASTE.md)
     for that Project
   - The short block is a stable pointer; the detailed role definition lives
     in this directory and is loaded via filesystem MCP on session start

3. **Upload minimal knowledge files** (optional but recommended as a safety net
   in case filesystem MCP is unavailable):
   - See per-Project section in [CUSTOM_INSTRUCTIONS_UI_PASTE.md](CUSTOM_INSTRUCTIONS_UI_PASTE.md)

4. **Verify** by starting a new chat in the Project and pasting:
   > "Confirm: what role do you play, which agent's comprehension gate do you
   > review, and what is your filesystem MCP policy?"
   >
   > You should read your detailed instructions from
   > `C:\Users\mrbla\BlarAI\docs\claude_projects\` before answering.

   Correct answer format: role name, which tier's gate it reviews, and
   "read-only / never write".

---

## Updating instructions

When role instructions change:

1. Edit the appropriate `0N_*_INSTRUCTIONS.md` file in this directory
2. Commit to git (normal feature branch workflow)
3. The git post-commit hook logs the change to `docs/_claude_projects_dirty.log`
4. The weekly scheduled task creates a Vikunja ticket reminding you to
   re-verify the Project (usually no UI action needed — the pointer block
   in custom instructions already points at the file, which is now updated)
5. If the short pointer block in custom instructions ALSO changed, the ticket
   will say so — follow the [CLAUDE_PROJECTS_REFRESH_RUNBOOK.md](../CLAUDE_PROJECTS_REFRESH_RUNBOOK.md)

See [CLAUDE_PROJECTS_MANIFEST.md](../CLAUDE_PROJECTS_MANIFEST.md) for what is
tracked and when a refresh is required.

---

## Why this design

- **Role instructions in git**: survive session boundaries, auditable, diffable
- **Pointer-style custom instructions**: rarely change → minimal UI re-paste
- **Filesystem MCP for live reads**: no stale snapshots, no manual re-upload
- **Safety-net knowledge uploads**: if filesystem MCP is down, role identity
  is still anchored in the Project knowledge
- **Automation-backed freshness**: git hook + scheduled task + Vikunja ticket
  ensure you are reminded when manual action is actually required
