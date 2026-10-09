---
paths:
  - "docs/sprints/**"
  - ".claude/rules/vikunja.md"
x-blarai-tools:
  - '^mcp__vikunja__'
---
<vikunja>
- Session start: `project_summary`. Use the mcp__vikunja__* MCP tools directly; he uses the webUI for manual work.
- Shipping closes the ticket (non-negotiable): the merging agent closes the ticket with a one-line comment citing the shipping SHA, in the same motion as the merge. Live capability + open ticket = incomplete ship. Partial landings: dated "CURRENT STATE (YYYY-MM-DD)" top comment with built-vs-remaining + evidence.
- Lifecycle: before starting → set "Doing" + comment. Complete → complete_task + results comment. Failure → comment with summary, do NOT mark complete. Umbrella/epic tickets close when the last in-scope limb lands; new residuals get their own tickets.
- Decisions recorded on the ticket that caused them — no standalone decision tickets. Sustained multi-artifact work opens a task at start. Hardening follow-ups / deferred cleanup ALWAYS get tickets.
- Labels: use the server-canonical exact names (Active, Complete, Blocked, Architecture, Infrastructure, Testing, Documentation, Security, Defunct, Gate:*) — verify via list_labels; never invent variants (a prior doc's "P5-Active" did not exist on the server).
- update_task is a full PUT — wipes unspecified fields; prefer comments.
- The board is what he reads: a stale board is misinformation delivered to the person steering.
- If MCP fails with connection errors: start the server — C:/Users/mrbla/devplatform/tools/vikunja/vikunja-v2.3.0-windows-4.0-amd64.exe (localhost:3456, local only).
</vikunja>
