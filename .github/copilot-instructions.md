<!-- BlarAI coding-agent instructions. Auto-loaded for GitHub Copilot / Codex / AGENTS.md-style sessions
     in this repo. Rewritten 2026-07-19 (ticket #945, Decision D7) to the current world; the prior version
     described a retired agent fleet, pointed into a being-sunset sibling repo, and pinned a stale test count.
     Maintained by: the merging session that changes what this file asserts — if your change alters a fact
     here (build flags, the gate command, repo layout, a security posture), update this file in the SAME
     commit. There is no separate owner; a fact that moved while this doc stood still is the exact defect this
     rewrite fixes. CLAUDE.md is the authoritative doctrine; this mirrors it, compressed, for non-Claude agents. -->

# BlarAI — Coding Agent Instructions

## What BlarAI is

A personal, locally-run, security-first AI system built to be used and matured over decades — not a
prototype, not an MVP. It runs entirely on the operator's own hardware (Intel Core Ultra 7 258V "Lunar Lake"
laptop, Arc 140V integrated GPU), with its own model, trust spine, and governance. Absolute local execution
and privacy of the operator's data are design invariants, not features.

**Mature not minimal.** Build the advanced, cohesive version, never minimum-viable wiring. When you are
calibrating how much depth a task deserves, this is the tiebreaker.

## Who directs the work

- **The Lead Architect (LA)** owns the WHY — vision, priorities, capability scope, the quality bar,
  security/governance posture, go-live decisions. He is non-technical by design and directs in plain language.
  Never ask him a technical question: research it, decide, and report the decision plainly, leading with the
  outcome and spelling out every acronym on first use.
- **You (the coding agent)** own the HOW — architecture within already-locked decisions, libraries,
  algorithms, data structures, test strategy, tooling, sequencing. Own every technical call; do not hand him a
  menu of technical options.
- **Escalate to the LA** — with a recommendation plus named alternatives — anything that changes what BlarAI
  can do (adds/drops/gates a capability), lowers answer quality even temporarily, or shifts a
  security/governance posture (egress, privacy, encryption defaults, a go-live flip). Test: a defect has one
  correct fix you can name → fix it and report it; a decision has trade-offs only the LA should weigh →
  escalate it.

## Work queue — Vikunja

The task source-of-truth is Vikunja at http://localhost:3456 (local only), reached through the MCP tools
registered in `.vscode/mcp.json`. Before sustained work, set the ticket to "Doing" and comment; on completion,
close it citing the shipping commit SHA. A live capability with an open ticket is an incomplete ship. Record
decisions on the ticket that caused them — no standalone decision tickets. Use the server-canonical label
names (list them; never invent variants). The LA works tickets through the web UI, so keep the board accurate.

## Git discipline (there is no human safety net; other agents share this tree)

- **Never commit work directly to `main`.** Always a feature branch. The only sanctioned commit on main is the
  merge commit that lands a reviewed, gate-green branch.
- **No destructive git operations, ever** — no branch deletion, force-push, history rewrite, `reset --hard`, or
  `checkout --` discards. A backup is not authorization. If something looks wrong, stop and surface it; never
  "clean up" with a destructive verb. Preserve failed branches for audit.
- **Never `git add -A`.** Stage explicit paths only — a blanket add sweeps other sessions' untracked work in.
- **Parallel work uses `git worktree add`** (own dir, own branch) — never `checkout`/`switch` a tree another
  session is using. Before any commit in the primary checkout, verify `git branch --show-current` matches your
  intent; a worktree launch can silently switch it.

## Every ship is one atomic motion

merge to main (via the feature branch) **+** the Vikunja ticket closed citing the shipping SHA **+** a journal
entry **+** the regression lock (a test that fails without your fix) — one motion, no piece omitted.
"Committed" is not "done": done = live-verified on the real system AND merged AND ticket closed AND worktree
cleaned up.

## Journal

Three surfaces: `BUILD_JOURNAL.md` (narrative), `LESSONS.md` (curated, permanently numbered lessons),
`FIELD_NOTES.md` (mechanical gotchas — grep it before touching a named surface). Because sessions run in
parallel, **write each journal entry as a fragment in `docs/journal_fragments/` (one file per entry) — never
append `BUILD_JOURNAL.md` directly.** An integrator folds fragments at lulls. Every substantive ship needs an
entry naming the lesson and the trade-off (the rejected path), with real numbers and real commit SHAs.
Failures stay in — a sanitized journal does not compound.

## Test gate

Standing gate — the bar is 0 failed and 0 skipped in a clean environment (an unexplained skip is a defect,
investigated, never waved through):

```
pytest shared/ services/ launcher/ tests/integration/ tests/security/ -m "not hardware and not winui and not slow"
```

**Run pytest so the repo-root `conftest.py` LOCALAPPDATA redirect engages.** It repoints `LOCALAPPDATA`/`HOME`
to a throwaway directory before collection. An unredirected run once wrote dev-key-encrypted rows into the
operator's real `sessions.db`, which the production key could not decrypt, and the backend then refused to
start. Never point tests at the real `%LOCALAPPDATA%\BlarAI\`.

**Do NOT pin a test count in this file.** The live baseline figure lives in `docs/TEST_GOVERNANCE.md` §1 and in
CLAUDE.md `<status_snapshot>` — read those two surfaces (a gate test enforces this; a pinned integer here is a
governance violation). Every fix ships its regression lock in the same change. The `hardware`, `winui`, and
`slow` tiers are deselected by default and run at their own dev-machine ceremonies.

## Security is designed in, never reviewed in

Every new surface is a security design problem first and a functionality problem second. The controls already
shipped are the bar — match them, never dilute them:

- **Fail-closed everywhere** — every error path denies; a component that cannot verify its precondition refuses
  to start or act, never proceeds hopefully.
- **Deny-by-default** — allowlists, never blocklists; an empty allowlist denies everything. New capability
  starts denied and is explicitly granted.
- **One Policy-Agent adjudication door** — every risky action flows through the single Policy-Agent gate. Never
  add a side door or a second adjudicator.
- **Born-encrypted** — content-bearing data is encrypted from creation, secure-delete on; decrypted bytes never
  touch disk except by explicit operator action.
- **Nothing that ships opens a network path.** BlarAI began fully air-gapped; egress is now deny-by-default
  behind multiple independent locks and opens one named door at a time only via an LA-present go-live ceremony.
  Runtime code you write makes no external network calls.
- **Defense-in-depth** — multiple independent locks on every dangerous door; one lock is a design smell. Every
  control ships with a test proving it blocks when engaged AND a toggle-test proving the probe fails with it off.

## Build facts (verified on disk 2026-07-19)

- **Runtime:** Python 3.12 services under `shared/`, `services/` (policy_agent, assistant_orchestrator,
  semantic_router, ui_gateway, ui_shell, ui_winui, voice), and `launcher/`. Runtime dependencies are declared
  in `pyproject.toml` (gate-locked against the actual import graph) and reproduced from the lock file — do not
  `pip install .` into the runtime venv.
- **Build/conversion toolchains** (diffusers, torch, model conversion) live in a SEPARATE venv, never the
  runtime `.venv`. Dev-side installs are pre-approved; runtime dependencies are not.
- **WinUI 3 desktop app** (`services/ui_winui/BlarAI.Desktop.csproj`) is the primary face and builds ONLY with
  `-p:Platform=x64 -r win-x64 --self-contained`. A Textual TUI (`services/ui_shell`) predates it and still exists.
- **Shell:** PowerShell 7 is the primary shell on a Windows 11 Pro host. Elevated vs non-elevated matters (2
  symlink tests skip on a non-elevated shell — benign, documented).
- **Paths:** use forward slashes in tool-call paths (avoids `\u`-style escape pitfalls on Windows). The prior
  version of this file said "use backslashes" — that is wrong; current doctrine is forward slashes.

## You build BlarAI; you are not BlarAI

You operate on BlarAI's code from the outside, with full internet, web search, and dev installs — use them to
fetch the docs, weights, and benchmarks the air-gapped product never could. But everything that SHIPS obeys the
runtime rulebook above: local-only, fail-closed, policy-gated. Never write a cloud dependency or external
network call into runtime code because "we have internet here," and never refuse a dev-side fetch/install
because "BlarAI is private." Litmus test: does this run inside BlarAI, or does it build BlarAI? Inside →
runtime rulebook; building → dev rulebook. Keep the operator's data protected either way; default to
local/privacy-respecting services (no Google/big-tech dependencies without LA approval).

## Authoritative surfaces (read these; never trust a pinned count/hash)

- `CLAUDE.md` — the full current doctrine (this file is its compressed mirror).
- `docs/TEST_GOVERNANCE.md` §1–§2 — gate scope, live baseline, LOCALAPPDATA isolation rule.
- `docs/DECISION_REGISTER.md` — the decision/ADR index (source of truth).
- `services/assistant_orchestrator/config/default.toml` — real runtime flags; LIVE vs dormant is read from
  config, never from memory.
- Vikunja (http://localhost:3456) — ticket-level truth.
