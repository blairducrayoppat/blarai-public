# #772 evidence — B5 attempt-4 false-red: file:// capture vs the served app (2026-07-09)

Same merged code (battery-b5-habit-web, night-20260709-055439), same pinned
headless-Edge invocation:

1. `1_file_uri_dead_shell.png` — the harness's file:// view: module script
   blocked (CORS, origin null), client never runs, "Loading..." + blank
   canvas. This is exactly what the design reviewer doomed.
2. `2_http_served_rendered.png` — the same app over its own
   `node src/server.js`: chart rendered, status "Ready". The coder had
   built a working app.
3. `3_fixed_capture_tier_web.png` — the FIXED capture-app.ps1 Tier WEB
   (serve-then-capture, ephemeral verified-free port, server tree reaped)
   producing the honest shot end-to-end.

Fix: agentic-setup `fix/772-web-capture-serve`. Ticket: Vikunja #772
(orphan-server sibling: #773). Incident: #740 c.1527.
