# BlarAI — Project Instructions for Claude Desktop

## Project Identity

BlarAI is a personal, locally-run, security-first AI system designed for decades of use.
It runs entirely on local hardware with zero external network dependency and hardware-rooted trust.
This is not a prototype — it is a long-term platform that evolves across hardware generations.

**Current state**: USE-CASE-001 (Policy Agent) and USE-CASE-004 (Assistant Orchestrator)
are OPERATIONAL. 7 Use Cases defined in `Use Cases_FINAL.md` constitute the full vision.

## ACTIVE BUILD — headless-coding-dispatch (temporary; remove when shipped)
Builder: read `C:\Users\mrbla\agentic-setup\docs\blarai-headless-coding-agent-brief.md` (full spec — start at §9 milestones; operational lessons in §10). Take no destructive action — model swap, stopping OVMS, etc. — without an explicit task from the user.

## Build-Journal Discipline (NON-NEGOTIABLE)

`BUILD_JOURNAL.md` at the repo root is the running narrative of how
BlarAI is being built — failures, recoveries, lessons, trade-offs, and
the judgment behind every meaningful call. It is **load-bearing** for
the User-Operator's professional portfolio and his IAPP AIGP
(Artificial Intelligence Governance Professional) certification track,
where the documented journey *is* the portfolio. Treat it accordingly.

The journal surface is **three files** (split 2026-07-03, lesson 196):

- `BUILD_JOURNAL.md` — the chronological narrative entries (this section's
  main subject).
- `LESSONS.md` — the distilled numbered lessons, led by a curated
  **Canonical Tier** (\~20 classes). Its top-of-file Rules section is the
  authoritative curation SOP: search-before-mint, recurrence tallies,
  the third-instance rule, quarterly consolidation. Numbers are permanent;
  never renumber.
- `FIELD_NOTES.md` — mechanical, environment-specific gotchas (API traps,
  engine dialects, driver quirks). Reference material, not judgment; grep
  it before touching the named surface.

**Every agent working in this repo MUST append a journal entry when
shipping anything substantive.** This is not a nice-to-have. An
otherwise-perfect commit that ships product code without a journal
entry is an incomplete commit.

### When an entry is REQUIRED

- A feature is shipped (any user-visible capability).
- A bug is fixed where the bug itself is portfolio-worthy (judgment
  shown, root cause non-obvious, or a lesson worth keeping).
- An ADR is authored or amended.
- A performance change is measured (entry in `PERFORMANCE_LOG.md` too,
  but the journal carries the *story*).
- A governance decision is made — flag flipped, policy set, default
  changed.
- A trade-off is taken — choosing path A over path B with a stated
  reason that future-you needs to remember.
- A failure happens that's worth keeping in (mock-passes-but-prod-
  crashes, locked-design-but-shipped-wrong-version, screen-caught-what-
  test-missed). **These are the most portfolio-valuable entries.**

### When an entry is NOT required

- Pure mechanical commits (typos, formatting-only, dependency bumps
  with no behavior change, test-only refactors that change no logic).
- Sweep-cleanup commits that don't make a decision.

### Form

- **Dated section header**: `### YYYY-MM-DD — Title that names the
  lesson or arc` — NOT the change. *"The optimisation I measured to
  nothing"* and *"Locking the door the documents come through"* are
  the right shape. *"Add boot cache"* is not.
- **Plain-language subtitle**, one italic line directly under the
  header: `*Plain summary: <what literally changed, which subsystem,
  which lesson class if any>.*` The poetic title is the voice; the
  subtitle is the index — it is what makes 250+ entries searchable.
  Required on every new entry (entries before 2026-07-03 are exempt).
- **Narrative prose, first-person, reflective tone**. Not bullet
  points. Not a changelog. Reads like a portfolio essay, not release
  notes.
- **Mature-not-minimal, sized to the JUDGMENT, not the bookkeeping.**
  A small fix is a tight paragraph; a multi-day arc earns several.
  Underwritten entries don't show portfolio-grade judgment and don't
  compound — but neither does inflation: gate counts, merge mechanics,
  and per-commit minutiae belong in the trailing italics line, the
  ledger, or `PERFORMANCE_LOG.md`, not the narrative body. If a
  paragraph carries no failure, no trade-off, and no lesson, cut it.
- **End with `**Next:**`** pointing the reader forward — real next
  steps, not vague aspirations.
- **Trailing commit references** in italics + parens at the end of the
  entry: `*(commits `abc1234` (what); test count; what awaits live
  verify.)*`
- **No emoji.** No machine-readable tables in the body unless they
  carry essential data (the closure-measurements table from the model-
  sharing arc is a fair use; *"Status: Done"* tables are not).

### Content

- **Failures stay in.** The frozen-dataclass mock-shape divergence,
  the Layer 3 session-scope-vs-turn-scope bug that the screen caught
  after three sweeps passed, the pivot-memory-was-day-stale moment —
  those are the entries that prove governance judgment. Sanitised
  journals don't compound.
- **Specific numbers**: exact measurements (`17 GB → 8.7 GB`, `42.8s
  → 29.9s`), exact file:line references when relevant, real commit
  SHAs (no `<this>` placeholders left in committed entries), real
  metric values. Vague entries don't compound.
- **Trade-offs named** with the rejected alternative visible. The AIGP
  cert track wants governance decisions documented with the path-not-
  taken on the record, not just the chosen path. *"I went with X
  because Y, accepting Z"* is the load-bearing shape.
- **Lessons distilled** in `LESSONS.md` (the compounding portfolio
  surface; the journal entries are the evidence). When the work earns
  a lesson, follow the curation rules at the top of that file — the
  short form:
  1. **Search `LESSONS.md` first.** If the incident is a recurrence of
     an existing lesson, add a dated tally to that lesson
     (`*(recurred: YYYY-MM-DD — <entry title>)*`) — do NOT mint a new
     number.
  2. **Third instance → structural control.** The change recording a
     third tally MUST also ship an enforcement (gate test / CI check /
     hook / required checklist line) and record it on the lesson
     (`*(control: …)*`). A lesson recurring without a control is a
     defect in this discipline.
  3. Only a genuinely new class gets the next number.
  4. **Mechanics go to `FIELD_NOTES.md`**, not the lessons list — a
     Windows API trap or regex-engine dialect is a field note; the
     transferable judgment (if any) is the lesson, linking the note.
- **Monthly retrospective**: at each month's end (or the first quiet
  tree after), one session writes a `### YYYY-MM-DD — Monthly
  retrospective: <arc title>` entry — where the project stands, what
  the month changed, what it cost, what recurred. This is the wide
  shot that makes the portfolio arc legible without reading every
  micro-entry. Status detail stays in the ledger; the retrospective
  carries the arc.

### Frame

- BlarAI is the artifact; the journal is the evidence of how it was
  built and the judgment behind each call.
- Every meaningful governance decision wants an ADR + a journal entry
  naming the trade-off, not just the answer.
- *"Every work session ends with something that runs, not a document"*
  is in the lessons list. But the journal IS the documentation of
  what runs and what was learned shipping it. They are not in tension.

### Commit hygiene around journal entries

- Best path: the journal entry is in the **same commit** as the code
  it documents. The commit body can be short ("see BUILD_JOURNAL.md
  entry"); the journal entry carries the narrative.
- Acceptable path: a follow-up commit landing the journal entry on
  top of the work commit, same day. The work commit references the
  forthcoming entry by date.
- Anti-pattern: shipping work without a journal entry and "writing it
  later." It does not get written later. Write it now or it is lost.

### Parallel / multi-session journal entries (fragments)

When more than one session or worktree runs at once, **do NOT edit
`BUILD_JOURNAL.md` directly** — concurrent appends to the same file collide on
every cross-branch merge (this bit the Tier-1 wave, the web-search merge, and the
2026-06-05 spec-decode commit). Instead, drop your entry as a standalone fragment:

    docs/journal_fragments/YYYY-MM-DD_<short-slug>.md

One file per entry — each session writes a *different* file, so there is nothing
to conflict on. A fragment carries the same content as a real entry (dated `###`
header + plain-summary subtitle + narrative + `**Next:**`), and if it earned a
new lesson it adds a `**Proposed lesson:**` block — *described, never
pre-numbered* (numbers are assigned at fold-in, serially, so two parallel
sessions never grab the same one). A recurrence of an existing lesson is
proposed as `**Recurrence of lesson N:**` instead. One integrator folds
fragments into `BUILD_JOURNAL.md` in date order at a quiet point (sprint close /
uncontended tree), applies the `LESSONS.md` curation rules (tally vs. new
number; third-instance control check), and deletes them. The canonical
portfolio surfaces stay `BUILD_JOURNAL.md` + `LESSONS.md`; fragments are only
the parallel-safe inbox that feeds them. See `docs/journal_fragments/README.md`.

A single session alone on a quiet tree may still write `BUILD_JOURNAL.md`
directly — the fragment rule is specifically for parallel work.

### Anti-patterns (forbidden)

- Vague entries — *"refactored the tool loop"* with no measurement, no
  trade-off, no lesson — these are noise, not portfolio value.
- Changelog-style bullets in place of narrative prose.
- Trade-off-free entries — change documented, alternative not named,
  reasoning missing. The cert track penalises this.
- Sanitised entries that hide the failure path. The honest journal is
  the valuable journal.
- `<SHA>` or `<this>` placeholders left in a committed entry **when
  referencing a prior commit you already know the SHA of**. Resolve
  the SHA before commit. The one carveout is *self-reference* — an
  entry citing the commit that introduces it cannot know its own SHA
  at write-time, so `<this>` in that single position is acceptable
  (and readers can unambiguously map it to the commit that landed
  the entry).
- Skipping the entry "because the work was small." Small work that
  earned a lesson earns an entry. Small work that did not (pure
  mechanical changes) does not need one.
- Status-shaped entries — an entry that names no failure, no
  trade-off, and no lesson is a changelog wearing narrative clothes;
  it belongs in the ledger, not the journal.
- Minting a new lesson number without searching `LESSONS.md` for the
  class first — near-duplicate lessons are how the compounding surface
  stopped compounding (lesson 196).

### The lessons surface (`LESSONS.md`)

The numbered list in `LESSONS.md` is the compounding portfolio
surface. Before writing a new entry, read at minimum its **Canonical
Tier** (the \~20 classes at the top) — that is the canonical language
of the project's judgment, and the search key for the
recurrence-vs-new-lesson call. The file's own Rules section is the
authoritative curation SOP; the quarterly consolidation pass (next
due 2026-10-01) refreshes the tier, reconciles tallies, and verifies
every third-instance lesson carries its control.

## Architecture Summary

- **Target hardware**: Intel Core Ultra 7 258V (Lunar Lake), Arc 140V (Xe2) GPU
- **Memory ceiling**: 31.323 GB effective (32 GB LPDDR5X minus 693 MB firmware reservation)
- **LLM inference**: All on GPU (Arc 140V). NPU retired from P1 Core Loop (ADR-011)
- **Target model**: Qwen3-14B with speculative decoding via Qwen3-0.6B INT4 draft (ADR-012)
- **Framework**: OpenVINO GenAI for inference. Textual (Python) for TUI. SQLite for sessions.
- **VM isolation**: Hyper-V Gen 2 VM (Alpine Linux) for service execution. vsock communication.
- **Privacy mandate (two-tier)**:
  - **BlarAI runtime code**: Absolute. No external network calls. Fail-closed. Zero tolerance.
  - **Claude development sessions** (Chat / Code / Cowork): Full internet, MCP, and web search permitted — these are the tools used to *build* BlarAI, not part of the runtime.

## Task Tracking — Vikunja (MCP)

Vikunja v2.3.0 is wired as an MCP server in **three** places so every Claude surface can reach it:
- `%APPDATA%\Claude\claude_desktop_config.json` — Claude Desktop (Chat)
- `.mcp.json` at repo root — Claude Code (project-scoped, gitignored)
- `.vscode/mcp.json` — VS Code Copilot

You have direct access to 19 tools for task management. **Use them.**

### Available MCP Tools
Tool call names are prefixed `mcp__vikunja__` (e.g. `mcp__vikunja__project_summary`):
`list_projects`, `create_project`, `get_project`, `update_project`, `delete_project`,
`list_tasks`, `create_task`, `get_task`, `update_task`, `complete_task`, `delete_task`,
`list_labels`, `create_label`, `add_label_to_task`, `list_task_comments`,
`add_task_comment`, `search_tasks`, `bulk_create_tasks`, `project_summary`

### Vikunja Conventions
- Start every session by calling `project_summary` to understand current task state.
- Task titles: `"Task N.M: Short Description"` or `"ISS-N: Short Description"`.
- Priority scale: 0=unset, 1=low, 2=medium, 3=high, 4=urgent, 5=do-now.
- Labels (server-canonical, verified 2026-04-20 via `list_labels`):
  Active (id 1, blue `#2196F3`), Complete (id 2, green `#4CAF50`),
  Blocked (id 3, red `#F44336`), Architecture (id 4, purple `#9C27B0`),
  Infrastructure (id 5, orange `#FF9800`), Testing (id 6, cyan `#00BCD4`),
  Documentation (id 7, brown `#795548`), Security (id 8, pink `#E91E63`).
  Defunct (id 22, gray `#9E9E9E`).
  Gate labels (Agent Gates bus, project 6): Gate:Pending-SDO (id 9),
  Gate:Pending-CoLead (id 10), Gate:Pending-Human (id 11), Gate:Approved (id 12),
  Gate:Rejected (id 13), Gate:Escalation (id 14).
  Always use these exact names — previous CLAUDE.md revisions referenced
  `P5-Active`/`P5-Complete` which are NOT on the server.
- Before starting work on a task, set its status to "Doing" and add a comment.
- On completion, mark it done via `complete_task` and comment with results.
- On failure, comment with summary — do NOT mark complete.

### Vikunja Server
The Vikunja server must be running for MCP tools to work. If tools fail with connection errors:
```powershell
# Start Vikunja manually
cd C:\Users\mrbla\devplatform\tools\vikunja
.\vikunja-v2.3.0-windows-4.0-amd64.exe
```
It runs at http://localhost:3456 (local only, no network exposure).

*See also: `C:\Users\mrbla\devplatform\CLAUDE.md` §Vikunja-Bridge.*

## Project Structure

```
shared/              # Shared libraries (semantic_router, config, types, vsock)
services/
  policy_agent/      # USE-CASE-001: Content classification on GPU
  assistant_orchestrator/  # USE-CASE-004: Conversational AI on GPU
launcher/            # Hyper-V VM manager and deployment
docs/                # Architecture docs, ADRs, implementation plan, ledgers
  IMPLEMENTATION_PLAN.md       # Full milestone tracking across all phases
  POST_OPERATIONAL_MATURATION_LEDGER.md  # Phase 5+ milestone records (FROZEN at Entry 52; new entries → docs/ledger/)
  ledger/                       # Directory-per-entry ledger (Q1-1, 2026-04-22 onward). See ledger/README.md
  GAP_TO_OPERATIONAL_REPORT.md  # Frozen — Phase 4 closed record
  TEST_GOVERNANCE.md            # Test policy, marker taxonomy, baseline
phase2_gates/        # Empirical validation evidence artifacts
tests/               # Integration tests
tools/
  vikunja/           # Vikunja v2.3.0 server binary + config
  vikunja_mcp/       # MCP server (19 tools) + CLI wrapper
```

*See also: `C:\Users\mrbla\devplatform\CLAUDE.md` §Current-Active-Sprint.*

## Phase History (Condensed)

| Phase | Status | Summary |
|-------|--------|---------|
| 1 — Architectural Definition | CLOSED | Use Cases locked. Canonical architecture defined. |
| 2 — Empirical Validation | CLOSED | All 4 HW gates passed. P1.0-P1.10 backend complete (533 tests). |
| 3 — UI Design & Scaffolding | CLOSED | TUI shell via Textual. P1.11-P1.15 done (747 tests). ADR-009. |
| 4 — Operational Gap Closure | CLOSED | UAT-1 through UAT-3. Sign-off HEAD 8f60259. 765 tests. |
| **5 — Post-Operational Dev** | **ACTIVE** | Tasks 4-7 COMPLETE. Sprints 7-18 COMPLETE. Sprint 18 (The Pre-Gate Sweep): model-loaded automation + **§5.1 production-posture verification DONE** (C1 reproduced in `dev_mode=False`; SWAGR STRONG_ALIGNMENT; C3 PARTIAL → #632). Sprint 17 (The Boot Cluster) COMPLETE. Domain 6 MCP config COMPLETE. Standing gate **3492 passed / 0 skipped / 116 deselected / 0 failed** (2026-06-14, +204 over the prior 3288 from the UC-003 review cluster: #663-B display-only images DORMANT (`97ad2ae`), #664 knowledge-recall leakage carve-out (ADR-023 Am.2, new `UNTRUSTED_KNOWLEDGE` provenance tier), + the #663 editable-preview Done-Editing display fix; the prior 3288 was +49 over 3225 from #663-A editable ingest preview `156818a` + #660 voice toggles/delete-rename `d15cf23`). Prior 3225 chapter — (deterministic — C6/#630 teardown-leak fixed; `require_signed=true`; +126 from the 2026-06-09/10 LA-added gate-criteria merges #634/#643/#637/#639/#649, then +61 from the 2026-06-10 #652/#607/#653 merges, then +18 from the #611 embedding-cache idle-unload, then +4 #657 / +90 #577 egress door / +323 #655 UC-002/003 program / +7 #655 merge-time integration test — all 2026-06-10 — then +131 #655 Stage C parse-channel + guest-provisioning + +9 parser error-path hardening, then +29 #655 version bridge (3.14 AF_HYPERV) + +15 #655 plaintext-AF_HYPERV bring-up fix (2026-06-11), then +40 #655 sub-task 6 host glue — the `/ingest <url>` fetch→guest-parse→preview corridor (`75ba1c7`, 2026-06-12), then +7 #655 url-adjudicator deterministic adapter — in-process `DeterministicPolicyChecker` over the ADR-027 §2 egress carve-out (`be603db`), then +3 #655 go-live prep — ADR-027 Am.1 precondition-2 verification (all 4 met) + dormant mTLS host plumbing, `6096387`). **#598 §5.12 sign-off RECORDED (GO, #598 c.1026, 2026-06-10)**; the UC-003 cleaner program is merged and its **guest-homed parser is PROVISIONED + ROUND-TRIP PROVEN on the real AF_HYPERV vsock boundary** (2026-06-11) with the fetch limb still dormant by structural absence. The **URL-mode host glue is MERGED** (`75ba1c7`, 2026-06-12 — `/ingest <url>` → one PA-gated `guarded_fetch` door → guest parse → host §5 compose → preview → existing approve flow), with the egress door **deny-by-default** by **three** independent locks (the `url_adjudicator` is built-not-registered, `guest_parser` ships `enabled=false`, AND the deterministic egress allowlist is empty so RULE 3 / `DENY_EXTERNAL_NETWORK` denies every URL by policy). The PA adjudicate function is now BUILT (`make_deterministic_url_adjudicate` — the in-process `DeterministicPolicyChecker` the AO already uses for tool dispatch, over the already-dormant ADR-027 §2 egress carve-out; verified-correct pathway, NOT a vsock hop / second GPU adjudicator); **ADR-027 Amendment 1 is verified against the shipped code — all four activation preconditions now MET** (2026-06-12), and the dormant mTLS host-side plumbing is built (`[guest_parser].mtls_cert/key/ca`, plaintext default). Going-live is now purely operational: register the deterministic adjudicator with the operator's host allowlisted for one fetch, bring up the resident guest parser, fire the first `/ingest <url>` GET, prove the corridor, then re-weld the three locks — the first irreversible outbound GET is the LA-present go-live moment. |

## Locked Architectural Decisions

- **ADR-010**: Policy Agent classification on GPU
- **ADR-011**: All LLM inference on GPU; NPU retired from P1 Core Loop
- **ADR-012**: Qwen3-14B unified model (PA + AO + UC-005), speculative decoding mandatory
- **ADR-012 §2.4**: Thinking mode strategy locked (PA: /no_think; AO: thinking allowed with strip)
- **DEC-01 through DEC-10**: Production configuration decisions from Task 4

## Active State

- **HEAD reference**: prefer `git log --oneline main` over pinning a hash here — the BlarAI main HEAD advances each merge and pinning it in doctrine becomes stale within a sprint.
- **Sprint state**: Sprint 18 ("The Pre-Gate Sweep" — model-loaded automation + §5.1 production-posture SWAGR, Vikunja #631) is **COMPLETE** (2026-06-08): C1/C2/C4/C6 MET (agent-run green on the Arc 140V); C3 **PARTIAL** — the AO→router wiring it targeted does not exist (verified by grep + the test; escalated → #632, a built-ahead-vs-gap LA decision); independent production-posture SWAGR **STRONG_ALIGNMENT**, 0 CRITICAL / 0 MAJOR / 5 MINOR (all dispositioned at close). **§5.1 production-posture verification limb is DONE** — C1 (gateway → real AO over real `CERT_REQUIRED` mTLS, `dev_mode=False`, signed-manifest boot → real PGOV → STREAM_TOKEN) reproduced by the Auditor; **scopes the verification criterion ONLY** — and the gate state has since moved (2026-06-10): the **§5.12 LA sign-off is RECORDED (GO, #598 c.1026)**, #607 landed as ADR-029, and the egress door (#577) + UC-003 cleaner program (#655) are merged with the fetch limb dormant by structural absence; going-live awaits Stage C + the URL-mode wiring + the LA go-live ceremony. First sprint under the **#629 automate-first reframe**: the agent ran every tier including the model-loaded @hardware tiers; **no LA terminal time** (two touches: comprehension gate + close). Sprint 17 (The Boot Cluster) + Sprints 7–16 COMPLETE. No sprint currently active — the remaining pre-gate work is the #612 capstone phase (gate-phase 6) then the sign-off (phase 7). Live pointer: `docs/sprints/ACTIVE_SPRINT.md`; per-sprint SDV/SCR/SWAGR under `docs/sprints/sprint_*/`.
- **Test baseline** (live, 2026-07-08 overnight, **post the #744 AF_HYPERV transport merge + the two overnight gate-integrity fixes**): **5804 passed, 0 failed, 0 errors, 122 deselected, exit 0** on the **standing gate** (merged main `f44710e`, LOCALAPPDATA redirected, 8:22, measured **while the battery campaign actively dispatched B3** — the live proof of the leak-detector fleet-awareness fix). The +80 over the 2026-07-07 5724: the 07-07 evening merges (bucket-A residual locks — 5742 measured at `4d9ddf7` — then the #766 PLAN-budget fix, ISS-3 closure, timeout registry +11) grew the gate to 5760 (= tonight's measured 5803 − the transport's 43); then tonight +43 #744 transport (43 locks, triple dormancy — `e7ed3b6`), +1 the `_phase` driver-stamp composition lock (`f44710e`); the leak-detector's 13 contract tests live at `tests/` root outside the gate selection. Two overnight defect fixes (#740 c.1453): the port-5001 leak detector false-positived a gate spanning a battery job's AO restore AND tree-kill-targeted the production AO (fixed: fleet-swap-fingerprint verdict + session-descendant-only kill, `ac5d709`); the #758 driver-alive stamp was clobbered by `SwapDriver._phase`'s fresh-SwapState on the first phase write — live current.json read phase CODE / driver_pid 0 (fixed: the stamp rides every write, `f44710e`). **Prior chapter — 5724** (2026-07-07, **post the day-shift six-fix cluster — #757 honest-timeout/budget, #758 reconcile driver-alive gate + test guard, #693 critic base SHA, the B8 in-dispatch chain lock, #743 grammar-constrained plan calls, #744 dormant guest-oracle executor**): **5724 passed, 0 failed, 122 deselected** on the **standing gate** (merged main `2034fbc`, LOCALAPPDATA redirected, single-selection run 3:14, measured **with the live AO up on :5001** — 7 environmental port-5001 skips, the exact scenario the new #758 root-conftest reconcile guard makes safe: an AO-entrypoint `service.start()` test's boot reconcile used to fall back to the REAL fleet root and could kill a live dispatch mid-run — stop the real OVMS, stamp RECOVERED; found live when a gate run killed the #757 proof re-run, fixed same-day two-layer: the test guard + `reconcile_swap_state` now verifies the recorded driver pid is DEAD before recovering, lesson 216). The +625 over the 2026-07-04 5099: the 07-04→07-06 dispatch/M2 merges grew the gate to 5586, then today's +14 #757 (TIMEOUT labeling on both kill paths; `swap_run_budget_s` 5400→10800 s — the 90-min budget was tree-killing the battery's final acceptance-tests task, the night-2 pass-blocker; per-task ceiling 3600→14400 s), +3 net #693/#758, +5 B8 chain locks (real nets → battery adoption → FALSE-DONE tripwire, offline), +18 #743 (criteria/assumptions/build-signal/asset-specs now grammar-first over the W2 hook, fail-soft byte-identical; the W2 decompose hook was also found built-but-unthreaded on the live PLAN path — lesson 46 tally — and fixed), +112 #744 (the DORMANT guest-certified oracle: knob `guest_oracle_enabled=false` + `transport=None` structural absence, advisory-only `guest-oracle.json`, teardown RAM-free window; the live in-guest proof is a supervised slot). 4 fragments folded same-day (lessons 46/55/195/214 tallied; **216** minted). **Prior chapter — 5099** (live, 2026-07-04, **post the answer-quality eval suite (#738) + the #626 orphan removal + the launcher-test gate-integrity fix**): **5099 passed, 0 failed, 0 skipped, 121 deselected** on the **standing gate** (merged main, LOCALAPPDATA redirected; measured as three disjoint slices summed — shared+services 3749 / launcher+security 659 / integration 691, pytest exit 0 on EACH slice — and cross-checked against the single-selection collect-only, exactly 5099/121; run **with the operator's live app open**, the very scenario that had silently killed the gate at 76% via the launcher's instance-lock `os._exit` inside a test — fixed by the `launcher/tests/conftest.py` autouse isolation + the `TestInstanceLockRefusal` production-semantics lock, lesson 209, merge `b9e0aca`). The +180 over the prior 4919: +45 tonight (44 answer-quality gate tests `2c64b8c` + the refusal lock), the rest from the 2026-07-02→03 merges that postdate the 4919 measurement (#724 Kagi v1 fix, W4/W5 going-online build, #718 legacy-format retirement). **Eval gate now 4-suite green** (`python -m evals.run --suite all` exit 0 — pa_classification 22/22, tool_calling 49/49, governance **50/50** (the 38/38 below is the stale 07-02 figure), **answer_quality 21/21 offline** — its model-in-the-loop cases MEASURED on the Arc 140V (first 2026-07-04; re-measured 2026-07-07 and 2026-07-09 — 34/40, 6 baseline-tracked known-fails incl. 3 injection-family, byte-stable across substrate changes; #717 c.1543)). `tools/tests` **REMOVED** (#626 closed — the whole directory was orphaned platform-separation duplicates; the maintained twins run 85-green in devplatform; full-suite collection here is now **0-error** (4941 collected clean), unblocking the bare-`pytest`-as-gate line, TEST_GOVERNANCE §1). Journal: the 16 pending fragments folded (lessons **197–207**; L188 hit its **third instance with the unified control OUTSTANDING → #739**), plus tonight's 3 (lessons **208–209**, L149 tally). **Prior chapter — 4919** (2026-07-02, **post the capability-program merges — eval harness + native JSON tool calls + NPU offload + retrieval tools**): **4919 passed, 0 skipped, 120 deselected** on the **standing gate** (measured on merged `main` `29cd53e`, LOCALAPPDATA redirected, 2:31), **plus the new model-quality eval gate green** (`python -m evals.run --suite all` exit 0 — pa_classification 22/22, tool_calling 49/49, governance 38/38). The overnight LA-pre-approved program (Vikunja #717–#720, drafts in Project 9): **#717** the first model-quality eval harness (`evals/` — 3 golden-set suites, committed per-case baselines, regression exit codes with teeth; +39 gate tests; merge `584d1d9`); **#720** NPU encoder offload — `[embeddings].device` knob, default flipped **CPU→NPU on measurement** (13.6x @512-token document windows, cosine parity 0.999996, blob-cached \~2.5s warm compile; Whisper-on-NPU measured NOT viable — `ZE_RESULT_ERROR_DEVICE_LOST` on GenAI 2026.2.1 / NPU driver 32.0.100.4778, STT stays GPU; +34; merge `1fe2078`); **#718** Qwen3-NATIVE JSON tool calls + the xgrammar structural-tags grammar constraint **ON** (`[generation].tool_call_grammar=true`; composes with spec-decode + streaming — proven offline 6-leg on the production pipeline shape AND **live on the 14B**: native emission, 0 legacy-fallback hits, 0 fail-closed drops, 4.8s tool turn; system prompt \~270→841 tokens (schema block), all Layer-3/allowlist/#570-adjudication/ESCALATE governance regression-locked on the new format; +80; merge `a75b958`); the **cross-merge golden re-baseline** `897afd9` — the eval harness caught golden case tc-parse-010 encoding the old parser's nested-paren defect as *expected behavior* on its first combined gate (BUILD_JOURNAL lesson 186) — + the live-verify evidence merge `6756ef3` carrying the **FIRST ISS-3 measurement** (PA classification 26/30 = 86.7%; all 4 misses are false-DENIES of benign actions — an OVER-denial shape, 0 dangerous false-ALLOWs; evidence `phase2_gates/evidence/eval_pa_classification_model_897afd9.json`; disposition ESCALATED to the LA on #717); **#719** tool-surface expansion — `search_knowledge` **LIVE** as a GUARDED model-callable tool (delegates to the same `_knowledge_retrieve` the auto-recall uses; results grounded via `add_grounded_context` with **UNTRUSTED_KNOWLEDGE** provenance — datamarked, Layer-3 feedstock, Stage-5-exempt per ADR-023 Am.2; 4000-char deterministic result cap) + `web_search` **STRUCTURALLY DORMANT** (a runner seam NO production code registers — no Kagi adapter and no enable flag exist to flip; egress posture UNTOUCHED: RULE 3 + empty allowlist + the new go-live tripwire eval gov-pf-007 that forces a reviewed baseline refresh at the ADR-027 Am.1 ceremony; +55; merge `29cd53e`), **live-smoked on the 14B** (`9e00195` — the model CHOSE `search_knowledge` unprompted for a knowledge question, query `'hostname of my NAS'`, grounded the result, used the fact; 5.7s turn). Perf recorded community-grade (PERFORMANCE_LOG.md 2026-07-02 ×2 + docs/performance/ JSONs). Journal fragments folded same-night (lessons **183–186**). **Open LA decisions flagged, not decided:** ISS-3 over-denial disposition; grammar-ON soak-vs-keep; legacy tool-format fallback retirement; whether the web_search CAR carries the real URL at go-live (RULE 3 at the loop too); the knowledge-session /trust UX (auto-recalled knowledge locks GUARDED tools in exactly the sessions search_knowledge serves); answer-quality eval suite (LLM-judge vs rubric). (The intervening dispatch-era merges 2026-06-18→30 (#670/#687/#689/#703/#712 …) grew the gate 3884→\~4711 without a chapter here; tonight's post-merge runs measured 4750→4784→4864→4919, **0 failures at every step**.) **Prior chapter — 3884** (2026-06-17, **post the UC-010 image-management Phase-2 (gallery) merge**): **3884 passed, 2 skipped [non-elevated symlink], 118 deselected** on the **standing gate** (merge `438bc1a`, full run 2:07) — **+15 over 3869** from UC-010 image-management Phase 2 (#668): the WinUI generated-image **gallery** — an **overlay pane** (LA-chosen layout) opened from a sidebar photo icon, layered over the chat (X returns to it), with **display-only** thumbnails resolved + decoded through the SAME `resolve_image` corridor the inline render uses (in-memory `BitmapImage`, `IsHitTestVisible=false`, no nav/tap), saved-✓ / encrypted-only-🔒 badges, and **always-visible** per-tile Save + Delete (Save = `FileSavePicker` → write full-res bytes → `mark_saved`, the sanctioned ADR-033 §D export; Delete = modal confirm → `secure_delete` wipe) — plus the **session-delete always-visible fix** (the per-row button shipped `Opacity=0`/hover-only + restored-to-0, so it was undiscoverable → dim-visible `0.55`, brighten on hover, restore to `0.55`) and a **backend-passthrough allowlist SSOT** (`shared/ipc/slash_commands.py` + `tests/integration/test_winui_passthrough_allowlist.py`, which parses the WinUI C# `BackendPassthroughCommands` array out of `MainWindow.xaml.cs` and fails loudly naming any missing canonical command — the durable, gate-enforced fix for the `/imagine`-then-`/images` silent-drop class). Two new ui_backend dispatcher RPCs `list_generated_images`/`manage_generated_image` mirror `_m_resolve_image` (non-streaming, fail-closed, getattr-reachable, anchored-`\A[0-9a-f]{32}\Z` id-gate + action-allowlist validated BEFORE the gateway is consulted so a forged delete never reaches the born-encrypted store), delegating to the existing Phase-1 `_list_generated_images`/`_manage_generated_image` gateway legs — **metadata-only wire** (no pixels/prompts). **+15 Python tests** (13 `test_dispatcher_image_management.py` driving the real `RpcDispatcher.handle` with a recording fake gateway + 2 allowlist); **C# headless +12 → 59/0** (`GalleryManagementGateTests`, the client-side id-gate incl. the `\z`-anchor newline case — NOT in the Python gate); **WinUI build 0 warn / 0 err** (`-p:Platform=x64 -r win-x64 --self-contained`). Security posture **unchanged** (born-encrypted at rest, metadata-only list/manage wire, decrypted bytes only via the resolve corridor / explicit Save, no new egress, fail-closed). Builder-built on an isolated worktree (`feat/uc010-gallery-phase2`, `36640e3`), Guide-reviewed (display-only/metadata-only/fail-closed/reachability verified in code + independent on-main gate `3884/0` + C# build/test re-run) + merged. The **live-pixel confirm** (gallery renders thumbnails, the Save dialog appears, a delete removes the tile) is the operator's on-hardware step. **Prior chapter — 3869** (2026-06-17, **post the UC-010 image-management Phase-1 merge**): **3869 passed, 2 skipped [non-elevated symlink], 118 deselected** on the **standing gate** (merge `85fdd53`, full run 2:08) — **+64 over 3805** from UC-010 generated-image management Phase 1 (#666 content-mgmt): a `/images` chat command to **LIST** (metadata-only — `length(data)` size, NO decrypt; capped 200/frame with a `truncated` flag), **DELETE** by full-32-hex-id (reuses the existing `secure_delete=ON` wipe; idempotent; the operator's `/save`'d copies on disk untouched), and a forward-looking **saved / encrypted-only** flag (set fail-soft after a successful `/save`; idempotent `ALTER` migration for pre-existing stores). New `IMAGE_LIST`/`IMAGE_MANAGE` IPC verbs (metadata-only on the wire), AO handlers (fail-closed), `list_generated_images`/`mark_generated_image_saved` on `knowledge_bank`. Builder-built on an isolated worktree (`feat/uc010-image-management-phase1`, `423ad24`), Guide-reviewed (metadata-only posture verified at every layer: backend `length()` no-decrypt, IPC metadata-only capped, the full-id delete gate, the secure_delete reuse) + merged. **Prior chapter — 3805** (2026-06-17, **post the UC-010 inline-image-render merge**): **3805 passed, 0 skipped (clean env), 118 deselected** on the **standing gate** (merge `836988c`, the ui_gateway+ui_backend blast radius re-run 543/0 on main; the unchanged remainder holds at the prior 3804) — **+1 over 3804** from the UC-010 inline `blarai-img://` render (#666 / #665 Pass B, ADR-033/ADR-032 display posture): the WinUI markdown renderer (`MarkdownBlock`) now resolves a generated-image ref to locally-decrypted PNG bytes via `BackendClient.ResolveImageAsync` (the IMAGE_RESOLVE corridor) and renders it inline — **display-only** (no `NavigateUri`/pointer/tap handlers, `IsHitTestVisible=false`, `Image.Source` is an in-memory `BitmapImage` ONLY, id-gated via `ExtractImageId`, fail-closed to an alt-text placeholder), async placeholder-then-fill with the decode marshaled to the UI thread; the `imagine_coordinator` success reply now LEADS with the `![generated image](blarai-img://<id>)` markdown embed so the render path fires. **+19 C# render-gate tests** (`InlineImageRenderGateTests`, 28→**47** headless, adversarial scheme/forgery coverage — NOT in the Python gate; independently re-run green) + 1 Python coordinator test. Builder-built on an isolated worktree (`feat/665-inline-image-render`, `c267466`), Guide-reviewed (display-only seam verified IN CODE + the C# 47/0 + Python 543/0 independently re-run) + merged. The **live-pixel confirm** — the image actually rendering in the running app — is the operator's on-hardware step (relaunch → `/imagine` → inline image). **Prior chapter — 3804** (2026-06-17, **post the UC-010 image-generation GO-LIVE merge**): **3804 passed, 0 skipped (clean env), 118 deselected** on the **standing gate** selection `pytest shared/ services/ launcher/ tests/integration/ tests/security/ -m "not hardware and not winui and not slow"` (measured on merged `main` `af60ddf`, LOCALAPPDATA redirected, 2:47; the as-run showed 9 ENVIRONMENTAL skips — 2 symlink [non-elevated shell] + 7 port-5001-in-use [a live BlarAI app was open during the run] — **0 failures**) — **+26 over the prior 3778** from the UC-010 image-generation **GO-LIVE** (#666, ADR-033 Am.2, merge `af60ddf`): the capability is now **LIVE** (`[image_generation].enabled=true`; `require_signed_manifest` stays true). Landed the fixes the DORMANT build hid once run live on the Arc 140V — the dead-`steps`-knob fix (the `0` "unspecified" sentinel floored every generate to 1 step → pure noise; `_resolve_steps` treats `<=0` as "use the configured steps"), quality knobs (EULER_ANCESTRAL_DISCRETE scheduler via set_scheduler-before-compile/fail-soft + `guidance_scale` + a QUALITY-only `negative_prompt` — no content terms, the uncensored posture is intact — all TOML-tunable), **hires-fix** (upscale + low-strength img2img refine, the fix for small faces in wide shots; bounded by `hires_max_edge`, fail-soft to the base image), the **14B-eviction-for-hires** rework (a 1536² refine measured \~26 GB and cannot co-reside with the resident 14B — it thrashed the 14B to disk; so a HIRES generate now evicts the shared PA+AO 14B via `SharedInferencePipeline.unload()` + lazy reload on the next generate, gated to the hires path — **ADR-033 §Memory Am.2** relaxes "14B never evicted" for hires only; base 1024² keeps the 14B), the imagine IPC fail-safe 90→175s, and the `/edit`+`/save` cap decoupling from the 2 MiB egress cap (16 MiB seed-staging + resolve cap; the egress door is UNCHANGED) so hires-sized (\~3 MB) images can be edited/saved. Live-verified end-to-end on the Arc 140V (generate → born-encrypted store → resolve → `/save`; café multi-subject + sharp faces). +26 regression locks. Also this session: the key-rotation `SESSION_ROW_DECRYPT_QUARANTINE` cleanup (2 pre-dev→prod-transition orphan sessions + 24 turns removed from the live `sessions.db`, backed up, `integrity_check ok`, 34→32 — operator-approved, dev test data). **Prior chapter — 3778** (2026-06-16, **post the UC-010 generation go-live-prerequisites merge**): **3778 passed, 0 skipped, 118 deselected** on the **standing gate** selection `pytest shared/ services/ launcher/ tests/integration/ tests/security/ -m "not hardware and not winui and not slow"` (measured on merged `main` `f6611f8`, LOCALAPPDATA redirected, 1:30) — **+88 over the prior 3690** from the UC-010 generation go-live **PREREQUISITES** (#666, merge `f6611f8`), built DORMANT: **WS1** nested weight-manifest signing (`require_signed` via `load_manifest_verified`) + `.xml`/`model_index.json` coverage **scoped to the SDXL/nested path** — the FLAT 14B/PA verifier + the existing signed production manifests are **byte-unchanged + regression-locked** (`test_flat_bin_only_14b_shape_still_verifies_unchanged`; no live-boot break, the Guide WS1 correction); **WS2** `secure_delete=ON` (FULL) at all five store-open sites (knowledge/substrate×2/session×2; SE-1 free-page probes toggle-validated — fail with the PRAGMA off); **WS3** the host→WinUI display-resolve corridor (`shared/ipc/resolve_channel.py` — chunked, 2-MiB-capped, fail-closed, decrypted bytes never to disk except the explicit operator `/save`; pipe+vsock only, **zero new egress**) + the first-ever **C# id-gate test project** (#665 item-1, `dotnet 28/0`) + the `get_knowledge_image` per-doc primitive (built-ahead) + the un-refused `/save`; + a **Guide doc-honesty fix-pass** (`85c6651` — BackendClient catch-comment + ADR-032 WAL-checkpoint wording). Still **DOUBLE-DORMANT**: `enabled=false` + model gitignored-absent, `is_available()` False, no image generated/stored/rendered. Guide-reviewed (independent 7-dimension adversarial workflow + finding-level refutation + independent gate/dotnet re-run, **MEETS_WITH_NITS**, #666 c.1133). Going live stays a SEPARATE LA-present ceremony (`docs/runbooks/uc010_image_gen_go_live.md`): stage+sign the SDXL manifest → one-time content attestation → flip `enabled=true` → live GPU verify; the one open posture call is the generated-image **by-id resolve grain** (global vs session-scoped — affirm or scope at the ceremony). Tracked NITs (none blocking): DH-1 ad-hoc `ADR-033 §`-letter citations (need a section-anchor scheme), DH-3 commit-vs-fragment count, + 3 optional code-hardening NITs (#666 c.1133). **Prior chapter — 3690** (2026-06-16, **post the UC-010 image-generation merge**): **3690 passed, 0 skipped, 118 deselected** on the **standing gate** selection `pytest shared/ services/ launcher/ tests/integration/ tests/security/ -m "not hardware and not winui and not slow"` (measured on merged `main` `109b224`, LOCALAPPDATA redirected, 2:13) — **+57 over the prior 3633** from UC-010 Local Generative Imaging (#666, ADR-033, merge `109b224`): the DORMANT local text→image + image+text→image capability (uncensored SDXL-INT8 finetune on the Arc 140V) — the `shared/inference/image_gen.py` load-on-demand inference module (mirrors `vlm.py`), the `/imagine`+`/edit`+`/save` `imagine_coordinator`, the IMAGE_GEN_REQUEST/RESULT IPC verbs (metadata-only; the `/edit` seed rides the encrypted staging blob), the born-encrypted `generated_images` store (AAD-bound, DELETE-on-discard, never-embedded), the GUARDED `generate_image` tool (no PA-logic change), + a **Guide post-review fix-pass** (`6e79291` — kind-swap lock re-check, command-neutral UNC refusal, a no-residue-on-error regression test, idle_unload/weight-manifest doc-honesty). The **+2 deselected** (116→118) are the 2 new `@hardware` go-live tests. **DOUBLE-DORMANT**: ships `enabled=false` AND the model gitignored-absent — `is_available()` False, **zero new egress** (the exactly-one-network-client invariant holds; `/edit` refuses URLs), no image generated/stored/rendered. The Phase-0 memory gate closed with the **14B RESIDENT** (26.0 GB co-resident peak vs the 31.323 GB ceiling, 5.3 GB headroom; community-grade in `PERFORMANCE_LOG.md` + `docs/performance/image_gen_phase0_2026-06-16.json`). Content-safety = **governance + a one-time go-live attestation, NOT a classifier** (LA-locked; uncensored for legal content, the legal boundary the operator's documented accepted-risk). Guide-reviewed (adversarial 7-dimension workflow + finding-level refutation + independent gate re-run, MEETS_WITH_NITS, #666 c.1125). Going live is a SEPARATE LA-present ceremony — the one-time content attestation + the **tracked weight-manifest-integrity hardening** (`.xml`/`model_index.json` coverage + signature-verify the SDXL manifest like the 14B) + the `secure_delete` posture call are all REQUIRED before the `enabled=true` flip. **Prior chapter — 3633** (2026-06-16, **post the UC-003 image-go-live Pass A merge**): **3633 passed, 0 skipped, 116 deselected** on the **standing gate** selection `pytest shared/ services/ launcher/ tests/integration/ tests/security/ -m "not hardware and not winui and not slow"` (measured on merged `main` `87d4a00`, LOCALAPPDATA redirected, 2:21) — **+58 over the prior 3575** from the UC-003 image-go-live Pass A safety controls (#663, merge `87d4a00`): W1 BED-3 decompression-bomb ceiling (header-only max-edge/max-pixel, no decode; coordinator gate + `store_image` mirror), W2 truncated-image drop (the door's `truncated` flag was computed-but-unread), W3 TD-4 drop-on-unreadable-header (inverts ADR-032 Am.1 #7), W4 PRIV-2 pinned generic User-Agent on both egress doors (wire-asserted, no Cookie/Referer), W5 CD-1 off-site per-article egress-consent seam (`shared/security/image_egress_consent.py`, exact-host same-site grain, fail-closed: no verifier → off-site dropped; paste/file never fetches), + W6-W8 doc-honesty restatement / real-resolver + boot-wiring tests (ADR-032 Amendment 2, same-commit DECISION_REGISTER row). The image egress path stays welded throughout — DORMANT, no image fetched/stored/rendered; the four at-rest locks + the two image-specific go-live-surviving locks (BED-1 purpose-deny + `images_enabled`) all untouched. Guide-reviewed (adversarial 6-dimension workflow + finding-level refutation + independent gate re-run, #663 c.1116; merged c.1118). The C# id-gate test project (#665 item-1) + the live-pixel render seam are Pass B. **Prior chapter — 3575** (2026-06-15, **post the UC-003 Workstream B headless-blockers + BED-1 merge**): **3575 passed, 0 skipped, 116 deselected** on the **standing gate** selection `pytest shared/ services/ launcher/ tests/integration/ tests/security/ -m "not hardware and not winui and not slow"` (measured on merged `main` `57c08d4`, LOCALAPPDATA redirected, 3:54) — **+83 over the prior 3492** from the UC-003 Workstream B headless go-live blockers (#663, merge `100e80f`): the 7 headless blockers (gateway flag wiring, edit-approve image survival, approve/reject lifecycle, forged-id format gate, binary-door SSRF/ESCALATE tests, store-time MIME re-validation, sub-32px drop; +79), DELETE-on-reject image posture (+0 tests), **BED-1** image-purpose-deny (the shared PA adjudicator refuses `uc003-image-ingest` until a separate image go-live, restoring defense-in-depth after text go-live; +3), and the coupling-lock test binding the deny-set to `_IMAGE_FETCH_PURPOSE` (+1). The image egress path stays welded throughout — DORMANT, no image fetched or stored; Guide-reviewed (adversarial 7-dimension workflow + re-review, #663 c.1106/c.1110). **Prior chapter — 3492** (2026-06-14, **post the UC-003 review-cluster triple-merge**): **3492 passed, 0 skipped, 116 deselected** on the **standing gate** selection `pytest shared/ services/ launcher/ tests/integration/ tests/security/ -m "not hardware and not winui and not slow"` (measured on merged `main` `97ad2ae`, LOCALAPPDATA redirected, 4:27) — **+204 over the prior 3288** from #663-B display-only images (DORMANT behind the new 4th weld lock `[knowledge].images_enabled=false`, \~+173), #664 knowledge-recall leakage carve-out (new `UNTRUSTED_KNOWLEDGE` provenance tier exempt from the Stage-5 leak feed but still tool-locked + datamarked, ADR-023 Am.2, \~+31), and the #663 editable-preview Done-Editing display fix (WinUI, +0 to the headless gate). The image egress path stays welded — **at rest** by four locks (`images_enabled=false` + the shared PA adjudicator unregistered + `guest_parser` disabled + empty egress allowlist), and **after text URL-ingest go-live** by two image-SPECIFIC locks that survive it: the adjudicator's **image-purpose-deny** (`uc003-image-ingest` DENIED until a separate image go-live — BED-1, #663) + `images_enabled` (the other two — the shared adjudicator-registration + the egress allowlist — release at text go-live; `fetch_external_binary` rides the SAME single PA adjudicator as the text door, so they were never image-independent); no image is fetched or stored. Each branch was Guide-reviewed before merge (B across 3 rounds — a live link-regression, doc-honesty overclaims, and a control-char escape evasion all caught + fixed). Go-live blockers for the image path are tracked at #663 c.1094. **Prior chapter — 3288** (2026-06-14): +49 over 3225 from #663-A editable ingest preview `156818a` + #660 voice toggles/delete-rename `d15cf23`. **Prior chapter — 3225** (2026-06-12, **post the #655 go-live prep**): **3225 passed, 0 skipped, 116 deselected** on the **standing gate** selection `pytest shared/ services/ launcher/ tests/integration/ tests/security/ -m "not hardware and not winui and not slow"` — the 3222 url-adjudicator figure grew **+3** from #655 go-live prep (ADR-027 Am.1 precondition-2 verification — **all four activation preconditions now MET** — + dormant mTLS host-side plumbing; `6096387`, measured **3225/0/116 green on clean main**, 2:21). The egress door stays welded by **three implementation locks** (adjudicator not-registered + `guest_parser` disabled + empty deterministic egress allowlist). **Prior chapter — 3222** (2026-06-12, **post the #655 url-adjudicator deterministic adapter**): the 3215 host-glue figure (prior chapter, below) grew **+7** from `make_deterministic_url_adjudicate` (the in-process `DeterministicPolicyChecker` the AO already runs for tool dispatch, over the already-dormant ADR-027 §2 egress carve-out — verified-correct pathway, NOT a vsock hop nor a second GPU `HybridAdjudicator`; `be603db`, measured **3222/0/116 green on clean main**, 2:18). The egress door is now welded by **THREE** locks — adjudicator not-registered, `guest_parser` disabled, AND the deterministic egress allowlist empty (RULE 3 / `DENY_EXTERNAL_NETWORK` denies every URL by policy; a test drives the REAL checker to assert it). Opening the door = ADR-027 Amendment 1 populating that allowlist (LA governance). **Prior chapter — 3215** (2026-06-12, **post the #655 sub-task 6 host glue**): the 3175 bridge+fix figure (prior chapter, below) grew **+40** from the UC-003 URL-ingest host glue (`75ba1c7`, merged to main, measured **3215/0/116 green on clean main**, 2:10): `clean_from_guest_parse` (8 tests — host ADR-030 §5 injection compose, proven byte-identical to `clean_html` over the fixture corpus), `parse_round_trip` + `GuestParserManager.parse_html` (10 — bridge/in-process content parse, mirroring `make_health_probe`), the `ingest_coordinator` URL path through the one PA-gated `guarded_fetch` door + guest parse hop (9), and the `url_adjudicator` factory (13 — CAR + ALLOW/DENY/ESCALATE→Verdict). **The egress door stays deny-by-default**: the `url_adjudicator` is built-not-registered and `guest_parser` ships `enabled=false`, so URL ingest refuses by two independent locks until the LA go-live ceremony (no live fetch performed). **Prior chapter — 3175** (2026-06-11, **post the #655 Stage C merges + parser error-path hardening + the version bridge + plaintext-AF_HYPERV fix**): the 2565 post-eight-merge figure (prior chapter, below) grew **+4** (#657 VM stop-on-exit) then **+90** (#577 `guarded_fetch` egress door) → **2659** (door merge-gate re-run 2659/2/116 non-elevated), then **+323** measured net-new from the **#655 UC-002/003 program** (knowledge bank / cleaner / ingest UX / Stage-A ADRs; collect-only derivation 2661→2984 selected, zero shortfall; **2984/0/116 measured green** on the integrated tree 2026-06-10, symlink-privilege shell — without the privilege expect the standing ±2 symlink-skip delta noted below; then **+7** from the merge-time real-pipeline integration test, `689a08e` → **2991/0/116 measured green on clean main**; then **+70** Stage C parse channel + **+61** Stage C guest provisioning/launcher wiring (2026-06-11) → **3122/0/116 measured green**, derivation zero-shortfall; then **+9** parser error-path hardening locks (`526e798`) → **3131/0/116**; then **+29** the #655 version bridge (3.14 AF_HYPERV subprocess, `83580ab`) + **+15** the plaintext-AF_HYPERV bring-up fix (`01538fb`) → **3175/0/116 measured green** on the bridge+fix tree, 4:48). **Prior chapter — 2565** (2026-06-10, post the eight LA-added gate-criteria merges; that live run measured 2563/2/116 on a non-elevated shell — the ±2 is exactly the standing symlink-privilege delta noted below; bumped from the 2026-06-09 2360/0/116 by **+126 regression tests across #634 exfil-screen wiring (+14, `651ef4a`), #643 egress proving (+11, `14d21c3`), #637 data-map DACL hardening (+30, `2d82f69`), #639 ESCALATE human-review consumer (+31, `494ebb8`), and #649 Windows-Hello biometric verifier (+40, `c1f51e9`)** — taking the gate to 2486 — then **+61 more across the 2026-06-10 #652 launcher privilege-strip (+26: 16 privilege-strip + 10 orphan-guard), #607 audit-retention/segmentation (+24), and #653 egress fingerprint re-arm (+11)**; all eight landed in the gate selection (deselected unchanged at 116), then **+18 from #611 embedding-cache idle-unload** (2026-06-10, a live-memory footprint feature, not a gate criterion) → 2565. The 2360 itself = the Sprint-18-close 2342/0/113 + 18 #638 token-containment tests + 3 @hardware/@slow from the post-close #612 capstone work). **0 skipped is the clean baseline; the port-5001 skip-shift (\~2333/9) is now FIXED (Sprint 18 C6/#630):** the WinUI-harness teardown reaps the spawned process tree (`tests/harness/process_tree.py`), and a session-scoped autouse fail-loud detector in the root `conftest.py` surfaces a leaked AO on loopback 5001 as a *failure* (free→held delta), not a silent skip — so the deterministic **2342/0 reproduces without a manual process-kill** (re-confirmed twice from main + by the Sprint-18 Auditor SWAGR). **Model-loaded @hardware tiers** (C1 production-posture round-trip, C2 IPC-routing lock, C3 router-in-turn) are agent-run green on the Arc 140V (perf: `PERFORMANCE_LOG.md` 2026-06-08); they are `@hardware`, deselected from the standing gate. **(FUT-04 C7 `require_signed_manifest = true` remains live** — Sprint-18 C1 verified the detached `manifest.json.sig` at boot.) **Shell-elevation (Sprint-18 finding):** 2565/0 is the **elevated-shell** number; a **non-elevated shell yields 2563/2** — the two `shared/tests/test_runtime_config.py` symlink tests skip without the symlink-create privilege (0 failures, same coverage, NOT a regression). (An isolated worktree lacking the gitignored `bge-small-en-v1.5` ONNX model also env-skips \~20 `semantic_router` router tests — benign, not a regression; they pass on the main checkout.) **The gate scope was widened at the Sprint-16 close (LA-directed, 2026-06-07):** the #619 production-parity lane (`tests/integration/`) + the security posture guards (`tests/security/`) are now folded into the standing gate so their locks actually fire — both were previously orphaned (Sprint-16 SWAGR MINOR-4; BUILD_JOURNAL lesson 70). `addopts` now deselects `hardware`+`winui`+`slow` by default. The prior `shared/ services/ launcher/` subset was 2187; the dev-machine tiers (GPU boot-smoke #619, GUI harness #621) remain outside the gate (`tools/tests` was REMOVED 2026-07-04 — #626 closed; the suite's maintained twins live in devplatform). See `docs/TEST_GOVERNANCE.md` §1. (The prior `1001 passed` figure was a 2026-05-12 Sprint-11 snapshot on the *unfiltered* `shared/ services/ launcher/` selection; the suite has since grown across Sprints 12–15. See `docs/sprints/sprint_11/test_baseline_drift_investigation.md` for the selection/environment history and `docs/TEST_GOVERNANCE.md` §1 for the named-scope baselines.)
- **Task 7** (Test Quality Audit): COMPLETE — closed by Sprint 8 execution (5 EAs merged, 45 TEST_AUDIT_FINDINGS items serviced). Sprint 8 SWAGR: `docs/sprints/sprint_8/Strategic_Work_Analysis_and_Gap_Report_Sprint_8_20260424_051646.md`.
- **Domain 6** (MCP Ecosystem): COMPLETE — Tier A+B servers installed and live-verified 6/6 (2026-04-20).
- **LEDGER**: monolithic `docs/POST_OPERATIONAL_MATURATION_LEDGER.md` FROZEN at Entry 52 (2026-04-22, commit `dc768b1`). New entries land in `docs/ledger/` per-file (Q1-1 format). See `docs/ledger/README.md`. **Permanent rule** (Sprint 11 DEC-17 ratified): no exceptions — all future ledger entries go to `docs/ledger/` regardless of sprint or EA.
- **Open issues**: ISS-2 (think tags in TUI), ISS-3 **RESOLVED 2026-07-07** (PA over-denial: first measured 2026-07-02 at 26/30 = 86.7%, 4 false-DENIES of benign actions, 0 dangerous false-ALLOWs, `eval_pa_classification_model_897afd9.json`; at tree `1deed99` the four cases (pa-mdl-001/002/006/008) pass in **three consecutive hardware runs, 35/35 each** — `eval_pa_classification_model_1deed99*.json` — variance excluded; attribution: a side effect of the intervening generation-substrate fixes (most plausibly #725), no deliberate tuning ever landed; the standing eval gate re-measures these cases at every hardware ceremony, so any recurrence fails the gate and reopens with data. Closure: #717 c.1448). ISS-1 (AO speculative decoding) RESOLVED 2026-05-21 by commit `b699ad1` (`num_assistant_tokens` moved from pipeline-construction to per-request `GenerationConfig`; spec-decode now engages, \~2x throughput; draft = Qwen3-0.6B pruned-6L INT8, tuned `e851405` 2026-05-22). Closure record: `docs/ledger/20260604_184221_iss1-spec-decode-closure.md`. ISS-4/5/6/7 resolved during Sprint 8. ISS-8 (#618 bulk-read decrypt-quarantine) + ISS-10 (#620 gateway→AO prompt routing) RESOLVED in Sprint 15 (`4af2033`/`6fe1fcc`/`ecbd991`).
- **F-1** (partial): Vikunja password redacted from README; rotation in Vikunja UI recommended.
- **Sprint 16 carry-overs** (Sprint 17 candidates, per SCR §5 + SWAGR §10/§13): the **deferred dev-machine green runs** (D real-GPU boot-smoke #619 + A GUI tiers #621 — Sprint-17-kickoff prerequisites, BEFORE the first #615/egress edit), **MINOR-4** (fold `tests/integration` non-slow into the standing gate scope so the production-parity lock fires — LA decision recorded on #619), **#626** (RESOLVED 2026-07-04 — the orphaned `tools/tests/` removed; coverage lives in devplatform), the dependency hash-pinning lockfile, and the forward gate decisions (egress policy; measured-boot attestation scope; audit retention #607). Landed in Sprint 16: #619 lane pt1, #106 weight-sweep (PARTIAL), #621 harness extend + #622 coverage audit, dependency pins, the verified §5 gate-tracker. Remaining #598 gate-critical work: **#615** (guest-boundary AF_HYPERV handshake — Sprint 17 Boot Cluster), **#106** (full FUT-04 weight integrity — the signed-manifest ceremony + flip), Tier-3 egress mediation + exfil-screen + kill-switch arming, **#612** (capstone security presentation). (#623 gateway-method rename + the Sprint-15 cold-reboot continuity boot remain low-priority.)

### Comprehension Gate

Before starting any work in an interactive Claude Desktop / Code session touching this repo, present a brief summary of what you understand the task to be and what you plan to do. Wait for Lead Architect confirmation before proceeding.

*See also: `C:\Users\mrbla\devplatform\CLAUDE.md` §Agent-Operating-Model (authoritative) and §Fleet-Pause-SOP.*

## Agent-Operating-Model (cf-3 close — standardized terminology)

As of cf-3 cutover (2026-05-14), the autonomous fleet that builds BlarAI operates under the cf-program redesigned shape. The authoritative operating-model doctrine lives in `C:\Users\mrbla\devplatform\CLAUDE.md` §Agent-Operating-Model. This section records the standardized terminology for cross-repo consistency per framing v6 §10.4.1.

### Standardized role names (post-cf-3)

| Legacy name (pre-cf-program) | Standardized name (post-cf-3) | Status |
|---|---|---|
| Co-Lead Architect | **Orchestrator** | Active — Anthropic orchestrator-worker pattern |
| SDO (Senior Design Orchestrator) | (DROPPED) | Responsibilities absorbed by Orchestrator per ADR-015 |
| EA Code (Execution Agent) | **Specialist subagent** (`code-specialist`, `research-specialist`, `review-specialist`, etc.) | Active — on-demand function-named subagents per ADR-017 |
| EA CoWork | (Absorbed into specialist subagents) | Per ADR-015 §3.1 |
| Configuration Agent | **settings-specialist** | Active — per ADR-017 §4.2 |
| Sprint Auditor | **Auditor** | Active — name kept; scope refined per ADR-026 §2 |
| Sprint Coordinator | **Sprint Coordinator** (kept — Python module, not LLM) | Deterministic Python module; not an LLM role |

### cf-program ADR references

The new fleet shape is governed by ADRs authored during cf-1 through cf-3 (all in devplatform `docs/adrs/`):

- **ADR-015** — Fleet shape change: SDO drop, Orchestrator absorbs planning.
- **ADR-016** — ReAct loop specification for Orchestrator + specialist subagents.
- **ADR-017** — Subagents / Agent Teams adoption: `.claude/agents/*.md` subagent definitions.
- **ADR-018** — Hooks and plan-mode adoption.
- **ADR-019** — Smart-orchestrator model differentiation (Opus/Sonnet/Haiku per role).
- **ADR-020** — Document substrate decision (EDD / CR / SWAGR).
- **ADR-021** — File-ticket comment streams.
- **ADR-022** — MCP design principles (v1.1 — classifier self-modification surface taxonomy; tool gating posture).
- **ADR-023** — Sprint Coordinator state-schema + circuit-breaker.
- **ADR-024** — Auditability notification taxonomy (v1.1 — 9-channel reconciled enum; UUIDv7 sub-ms discipline).
- **ADR-025** — Process efficiency model.
- **ADR-026** — DEC governance supersession amendment.

Full cross-repo pointer: `C:\Users\mrbla\devplatform\CLAUDE.md` §DEC-References.

### Fleet-pause

Fleet-pause is a dev-side operational norm — NOT a BlarAI runtime constraint. The authoritative fleet-pause SOP lives in `C:\Users\mrbla\devplatform\.github\copilot-instructions.md` (fleet_pause_sop XML element). See also devplatform CLAUDE.md §Fleet-Pause-SOP.

## Context-Exhaustion-Handoff-Discipline

Claude Code sessions have finite context windows. The authoritative discipline for proactive context-exhaustion self-reporting + handoff-brief authoring lives in `C:\Users\mrbla\devplatform\CLAUDE.md` §Context-Exhaustion-Handoff-Discipline. **This rule applies universally to any Claude Code session — including BlarAI runtime-code sessions** — not specifically to cf-program work. See devplatform/CLAUDE.md for full triggers + protocol + anti-patterns.

Key application for BlarAI sessions: any session spanning multiple substantive commits (multi-EA sprint work, cross-feature implementation, ledger materialization, doctrine propagation) MUST self-report when context approaches the limit + author a handoff brief at `docs/handoffs/<sprint-or-topic>-handoff-brief.md` (a gitignored working-tree dir, relocated from repo-root 2026-06-05 to keep root uncluttered; cf-3 precedent established at devplatform/`cf3-handoff-brief.md` + devplatform/`cf-post-1-handoff-brief.md`).

The 5 self-report triggers (post-compaction signal / ≥6 specialist dispatches / \~3-4 hours session-time / quality degradation / User-Operator friction) apply identically to BlarAI sessions. When triggered: pause cleanly, author brief, surface to User-Operator, do NOT continue substantive work.

**Authoring a brief? Use the fill-in template — do NOT freewrite.** `docs/governance/handoff-brief-template.md` is the tracked template that bakes in the doctrine's required structure. The **load-bearing, most-skipped requirement**: a handoff brief instructs the successor to **ground itself on disk (the ≤6-item first-action reads), then present a comprehension gate — its own-words understanding of role / task / specifics / scope / risks / constraints — and WAIT for User-Operator confirmation before any substantive or irreversible action.** Authorization to *do the work* is never authorization to *skip the gate*: never frame a brief as "execute end to end," "do not add blocking gates," or anything that biases the successor past its comprehension gate (the 2026-07-05 failure this control closes). Read the authoritative anti-patterns in devplatform §Context-Exhaustion-Handoff-Discipline before authoring.

## Proactive Defect-Fixing (NON-OPTIONAL)

When an independent check an agent runs — a merge-gate diff review, an
Auditor/SWAGR pass, or a production live-verify — surfaces a **real defect with a
clear, in-scope fix**, the agent FIXES it proactively (dispatch a worktree builder
subagent, or fix it directly) and surfaces the action to the LA with a one-line
off-ramp (*"say so if you'd rather ticket it instead"*). Do NOT block on a
pre-ask for a clear defect: **act + transparent + reversible**. Finding such a
defect and only reporting it — leaving the fix for "later" or a pre-approval
round-trip — is an incomplete response, the same standing as shipping product
code without a `BUILD_JOURNAL.md` entry.

This is for genuine DEFECTS: a fail-open, a "built but wired into nothing" gap, a
control that fails to refuse-to-start where it must, a test polluting real user
data, a missing regression lock, a stale/incorrect doc claim the code contradicts.

**The boundary — this does NOT override escalation.** A genuine *decision* —
anything that changes what BlarAI can do, lowers answer quality, drops a
capability, or sets a security/governance posture — is still ESCALATED to the LA
with a recommendation and the named alternatives. Never silently "fix" a decision.
The test: a **defect** has one correct fix the agent can name → fix it; a
**decision** has trade-offs only the LA should weigh → escalate it. (See
§Agent-Operating-Model; pairs with the escalate-quality/capability-decisions rule
and the hardening-follow-ups-are-non-optional rule.)

Validated repeatedly in Sprint 14, each endorsed by the LA: SWAGR MINOR-3 (a store
factory fail-open) → EA-7 refuse-to-start; a confirmed test-isolation defect that
had corrupted the live `sessions.db` → EA-8 then EA-9 (the durable root-level fix).

## Coding Standards

- Python: strict type hints, PEP 8
- Deterministic execution: temperature=0 equivalent
- Gate-check order: Compile → Test → Oracle
- Error handling: deterministic failure fingerprinting
- Never commit directly to main — always feature branches
- If validation fails, preserve the branch for audit

## Testing-Data Capture (community-grade) — NON-OPTIONAL

Every agent that runs **hardware or model performance tests** (inference
benchmarks, load/latency timings, memory measurements, model probes) MUST record
the results — never leave them only in chat. This is load-bearing for two reasons:
the User-Operator's portfolio AND **contributing his specific hardware's
local-model performance data to the OpenVINO / HuggingFace community** (he is an
OpenVINO upstream contributor — the data is meant to be published, not just kept).

- **Where:** a dated entry in `PERFORMANCE_LOG.md` (human narrative) + the
  machine-readable `docs/performance/` JSON / `perf_history.jsonl` (the dataset
  that feeds community contribution).
- **Format (community-grade, reproducible):** hardware (CPU + GPU), OpenVINO +
  GPU-driver version, model + precision, methodology (prompt set / config / run
  count), and the measured numbers. **Name what is NOT measured** (e.g.,
  co-resident cost) rather than implying full coverage.
- **Unrecorded test results are an incomplete task** — same standing as shipping
  product code without a BUILD_JOURNAL entry.

## Key Documents

| Document | Purpose |
|----------|---------|
| `.github/copilot-instructions.md` | VS Code Copilot agent instructions (authoritative) |
| `AGENTS.md` | Codex agent instructions |
| `docs/DECISION_REGISTER.md` | SSOT index of BlarAI runtime DEC-01..DEC-10 + runtime trust/security ADRs + cross-repo pointer to cf-program ADRs. **MUST be updated in the same change that authors/amends a runtime trust/security ADR or records a runtime DEC** (load-bearing SSOT — see the register's Maintenance rule, mirrors the BUILD_JOURNAL + TEST_GOVERNANCE update rules). |
| `docs/IMPLEMENTATION_PLAN.md` | Full milestone tracking across all phases |
| `docs/POST_OPERATIONAL_MATURATION_LEDGER.md` | Phase 5+ milestone records |
| `docs/TEST_GOVERNANCE.md` | Test policy, marker taxonomy, baseline management |
| `docs/governance/handoff-brief-template.md` | Fill-in template for context-exhaustion handoff briefs — bakes in the required successor comprehension-gate protocol. Use it; do not freewrite a brief. |
| `Use Cases_FINAL.md` | Canonical Use Case definitions |
| `shared/timeout_registry.py` | The timeout taxonomy — every budget with the incident that justified it; gate-locked against drift (`test_timeout_registry.py`); new/changed timeouts MUST register in the same change; reviewed at the LESSONS quarterly pass |
| `pyproject.toml` | Project config, pytest markers, dependencies |

## Security Constraints

- All code must enforce fail-closed logic
- No external network calls in generated code
- Hyper-V VM isolation for service execution
- vsock for host↔guest communication (no TCP/IP networking in VM)
- Privacy is absolute — zero tolerance for data leakage
- Do NOT install packages, add dependencies, or make network requests without explicit approval
