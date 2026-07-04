# AGENTS.md — BlarAI repo pointer

This repo is the BlarAI product (locally-run Qwen3 runtime — see CLAUDE.md §Project Identity). It is NOT a Claude host environment; Claude / Codex / Copilot agents work ON this repo from a separate dev environment.

When a dev-side agent touches code or docs in this repo, treat the following as authoritative:

- [`CLAUDE.md`](CLAUDE.md) — BlarAI runtime architecture, ADRs, Use Cases, security mandates, project structure, coding standards
- Fleet operating-model context (Orchestrator / specialist subagents / Auditor mechanics, sprint lifecycle, fleet-pause SOP): `C:\Users\mrbla\devplatform\CLAUDE.md`

## cf-3 close authority structure (post-cf-program)

As of cf-3 cutover (2026-05-14), the autonomous fleet operates under the cf-program redesigned shape per ADR-015..ADR-026 (devplatform `docs/adrs/`):

- **Orchestrator** — replaces Co-Lead Architect as the persistent Tier-1 meta-layer LLM agent. Breaks down sprint work items and delegates to specialist subagents.
- **Specialist subagents** — replace EA Code and EA CoWork. Function-named on-demand delegates: `code-specialist`, `research-specialist`, `review-specialist`, `settings-specialist`, `swagr-specialist`, etc. Each runs in isolated context and returns a ≤2K-token summary to the Orchestrator per ADR-017.
- **Auditor** — renamed from Sprint Auditor. Performs independent SWAGR audit post-sprint; never reads the Completion Report (CR) before authoring SWAGR (DEC-12 / ADR-026 §2 independence).
- **Sprint Coordinator** — Python deterministic module (not an LLM agent). Manages WI ordering, dispatch, and state.
- **SDO (Senior Design Orchestrator)** — DROPPED per ADR-015. Responsibilities absorbed by Orchestrator.
- **Configuration Agent** — DROPPED; replaced by `settings-specialist` subagent per ADR-017 §4.2.

See framing §10.4.1 at `devplatform/docs/cloud-fleet-redesign/program-framing.md` for the full legacy → standardized naming mapping table.

BlarAI's own coding-assistant Use Case (UC-005) is a future Qwen3 agent that will run *inside* the BlarAI runtime. It has nothing to do with Claude. When it ships, it will have its own doctrine separate from this file.
