---
sprint_id: "iss-2"
title: "ISS-2 — Think-Tag Rendering in Textual TUI"
status: ACCEPTED
edd_version: "v1"
artifact_type: "engineering-design-document"
substrate_pattern: "EDD-CompletionReport-SWAGR (ADR-020)"
orchestrator_authored_on: "2026-05-20T07:30:00Z"
la_approved_on: "2026-05-20T07:43:09Z"
authored_by: "guide-#16 (proxy for autonomous Orchestrator at sprint-kickoff time; fleet runs continuously post-G7-P5-3 commit 3e9d0e7)"
target_codebase: "C:\\Users\\mrbla\\BlarAI"
fleet_cwd: "C:\\Users\\mrbla\\devplatform"
vikunja_tracking_task_id: "4 (ISS-2: Think Tags in TUI, project 3 BlarAI Core Development)"
predecessor_sprint: "cf-post-3 (cf-program closer; G7 P5-3 commit 3e9d0e7 on devplatform main)"
predecessor_head_blarai: "(see §7.2 for the BlarAI main HEAD captured at EDD authoring)"
mature_not_minimal_floor: 250
parent_program: "FIRST POST-CF-PROGRAM SPRINT — first BlarAI-product autonomous run by cf-2-shape fleet"
---

# Engineering Design Doc — Sprint ISS-2: Think-Tag Rendering in Textual TUI

> **Acronyms on first use** (User-Operator-facing): EDD = Engineering Design Document; CR = Completion Report; SWAGR = Strategic Work Analysis and Gap Report; WI = Work Item; SC = Sprint Coordinator; TUI = Textual UI (terminal app); AO = Assistant Orchestrator (BlarAI runtime); ADR = Architectural Decision Record; RBV = Runtime-Binding-Validation; LA = User-Operator (Lead Architect); MAST = Multi-Agent System Failure Taxonomy.

**This is the FIRST post-cf-program sprint and the FIRST BlarAI-product sprint executed by the cf-2-shape autonomous fleet.** cf-post-3 validated the fleet on devplatform-cosmetic work. ISS-2 validates on a real BlarAI runtime feature in a sibling repo (BlarAI). The fleet's cwd remains `C:\Users\mrbla\devplatform`; this sprint operates on `C:\Users\mrbla\BlarAI` via cross-repo absolute paths.

## 1. Title

**ISS-2 — Think-Tag Rendering in Textual TUI.** Reasoning-trace markup (`<think>...</think>`) emitted by Qwen3-family models is currently passed through to the TUI as raw markup characters cluttering the response pane. This sprint adds detection + rendering — think blocks become visually de-emphasized (Rich `[dim italic]...[/dim italic]`) while remaining visible for inspection.

## 2. Authors

- **Sprint substrate** (this EDD): Guide-#16 as proxy for the autonomous Orchestrator. Per ADR-020, sprint substrate (EDD / CR / SWAGR) is authored by Orchestrator-role at sprint kickoff. At this moment the fleet is between cron firings; Guide-#16 authors the EDD substrate so the next firing has a sprint to dispatch on. Future post-resumption sprints will see the autonomous Orchestrator author its own EDDs once a `kickoff` cadence pattern is established.
- **Implementation** (WIs): autonomous Orchestrator + dispatched specialist subagents (code-specialist + settings-specialist), spawned at next `\\DevPlatform\\Wake orchestrator` firing per wake_launcher.ps1 Proposal #23 SC-state ready-WI detection.

## 3. Reviewers

- **Sprint substrate verification**: Auditor (NEW top-level Claude Code session per ADR-023 §9.4 inheritance-bypass + memory `feedback_manual_auditor_invocation_paused_fleet`) authors the SWAGR after CR commit. The Auditor independently verifies WI-by-WI delivery vs §8.2 acceptance criteria + §10.10 verification commands.
- **Cross-repo sweep**: the Auditor verifies the BlarAI commits land cleanly + ui_shell pytest baseline reproduces independently.

## 4. Goals

Aggregate target: **7/7 PASS**. G1 + G5 are load-bearing — a miss on either fails the sprint. G2 / G3 / G4 / G6 PARTIALs are acceptable if WI-level acceptance criteria are met.

| # | Goal | Verification method |
|---|---|---|
| G1 | `pytest-textual-snapshot` installed in `services/ui_shell` dev deps + baseline snapshot captured for current StreamingDisplay rendering of a `<think>...</think>`-containing token stream. | Read `services/ui_shell/pyproject.toml` for the dep; verify baseline SVG exists under `services/ui_shell/tests/__snapshots__/`; verify pytest passes with `--snapshot-update` first, then without it (no diff). |
| G2 | Pure-function think-tag parser `parse_think_segments(text: str) -> list[tuple[str, bool]]` implemented in a new module (suggested: `services/ui_shell/src/think_parser.py`) with unit tests covering: complete tags, partial tags across stream boundaries, nested-tag rejection, empty tags, unclosed tags. | Read the new module; verify pytest unit-test suite for the parser passes with ≥10 test cases. |
| G3 | `StreamingDisplay._render_buffer` (`services/ui_shell/src/streaming.py`) applies the parser; think segments render with Rich `[dim italic]...[/dim italic]` markup; non-think segments render unchanged. | Read `streaming.py` diff; verify integration test renders a known-good buffer with think markup applied. |
| G4 | Snapshot test in `services/ui_shell/tests/test_streaming.py` (or new `test_think_rendering.py`) feeds a streaming sequence containing `<think>reasoning</think>response` and locks the rendered SVG as golden. | Verify snapshot file exists; verify pytest pass on second invocation (no diff vs golden). |
| G5 | Full `services/ui_shell` pytest suite passes — no regression in existing `test_app.py` / `test_session_panel.py` / `test_streaming.py` / `test_pgov_display.py` baselines. | `pytest services/ui_shell/tests/` exits 0; specialist commit messages cite test count delta. |
| G6 | EDD-§10.10 verification commands all observable (each goal's verification command runs cleanly with documented expected output). | Auditor SWAGR §6 reproduces each command independently. |
| G7 | Sprint-close cadence: LA CR sign-off (touchpoint 2) + LA sprint-close commit (touchpoint 3). Mirrors cf-post-3 EDD §10.11 3-touchpoint cadence (EDD sign-off + CR sign-off + sprint-close commit). | Git history shows three `[la-via-guide-proxy]` or `[la-…]` attribution commits at sprint boundaries. |

## 5. Non-goals

1. **No expansion of think-tag behavior beyond visual rendering** — no folding/collapsing UX, no keybinding toggles, no per-session preference. (Tracked for a future sprint if/when LA prioritizes.)
2. **No changes to the model-side think-tag emission** — AO / PA emit `<think>` blocks per Qwen3 convention; this sprint only changes how the TUI RENDERS them.
3. **No changes to non-TUI surfaces** — `ui_gateway` transport layer + AO + PA continue passing raw think markup through their pipelines. Filtering is TUI-local.
4. **No protocol changes** — `shared/ipc/protocol.py` and IPC message schemas untouched.
5. **No cross-cutting refactors of streaming.py** — minimum-change addition of think-handling; broader `StreamingDisplay` refactors out of scope.

## 6. Vikunja sprint task

**Vikunja task #4** (project 3 BlarAI Core Development): "ISS-2: Think Tags in TUI". Body: "Deferred from Task 5. Think tag rendering in Textual TUI." LA selection 2026-05-19 as the first post-cf-program BlarAI sprint per memory `project-next-sprint-iss-2`.

## 7. Predecessor / Context

### 7.1 Predecessor sprint

cf-post-3 closed 2026-05-20 at commit `3e9d0e7` (G7 P5-3 fleet-resume). cf-post-3 SWAGR `a976363`: ACCEPTABLE_ALIGNMENT / SIGNIFICANT / STABLE, 0 CRITICAL + 0 MAJOR + 7 MINOR. **cf-program officially CLOSED.**

ISS-2 inherits the fleet substrate cf-program built: autonomous Orchestrator (devplatform `.claude/agents/orchestrator.md`); specialist subagents (code-specialist + settings-specialist + review-specialist); Sprint Coordinator (`tools/sprint_coordinator/`); wake_launcher dispatch (`tools/scheduled-tasks/wake_launcher.ps1`); Auditor (NEW top-level session); ADR-020 EDD/CR/SWAGR substrate; ADR-023 iterate-until-converged loop; ADR-024 notification taxonomy.

### 7.2 BlarAI repository state at EDD authoring

- **BlarAI repo root**: `C:\Users\mrbla\BlarAI`
- **TUI surface**: `services/ui_shell/` (Textual >= 0.89, per pyproject.toml)
- **Key files**: `src/app.py` (top-level App), `src/streaming.py` (StreamingDisplay widget — the think-tag rendering site), `src/session_panel.py` (sidebar), `src/pgov_display.py` (governance display)
- **Existing tests**: `tests/test_app.py`, `tests/test_streaming.py`, `tests/test_session_panel.py`, `tests/test_pgov_display.py`, `tests/test_constants_ui_shell.py`
- **Existing dev deps**: pytest>=7.4, pytest-cov>=4.1, pytest-asyncio>=0.23, ruff>=0.1, mypy>=1.7
- **No think-tag handling exists** — `grep -r "think" services/ui_shell/` returns zero matches in source files.

### 7.3 Cross-repo execution convention

The autonomous fleet's cwd is `C:\Users\mrbla\devplatform` per CLAUDE.md §Runtime-Binding-Validation. ISS-2 operates on `C:\Users\mrbla\BlarAI` via cross-repo absolute paths:

- Read/Write/Edit tools accept absolute paths (`C:\Users\mrbla\BlarAI\services\ui_shell\src\streaming.py` works as-is).
- Bash commands targeting BlarAI use `cd C:\Users\mrbla\BlarAI && pytest services/ui_shell/tests/` or `git -C C:\Users\mrbla\BlarAI ...` form.
- Specialist subagents (code-specialist / settings-specialist) inherit unrestricted Bash per their agent definitions — cross-repo commits work.
- Orchestrator's session-level allowedTools restricts its Bash to devplatform patterns; cross-repo git commits are delegated to specialists (consistent with cf-post-3 commit attribution pattern).

## 8. Detailed design

### 8.1 Architecture sketch

```
Token stream → StreamingDisplay.append_token()
                  ↓
              _append_text() → buffer accumulation (string)
                  ↓
              _render_buffer() → calls Textual RichLog.write()
                  ↓ (NEW)
              parse_think_segments(buffer) → [(segment, is_think), ...]
                  ↓
              for each segment:
                  if is_think:  write(f"[dim italic]{segment}[/dim italic]")
                  else:         write(segment)
```

Parser state machine (handles streaming partial tags):
- States: OUTSIDE / IN_OPEN_TAG / IN_THINK / IN_CLOSE_TAG
- Buffer characters as they arrive; emit segments at state transitions
- Handle `<think>`, `</think>`, partial `<thi` / `nk>` across token boundaries
- Reject nested `<think>` (close current think, log warning, treat as text)
- Empty `<think></think>` → emit empty think segment (parser is robust; renderer skips empty)
- Unclosed `<think>` (model output truncated) → treat trailing buffer as think segment

### 8.2 Acceptance criteria per Goal

- **G1 (snapshot infra + baseline)**: `services/ui_shell/pyproject.toml` `[project.optional-dependencies].dev` includes `"pytest-textual-snapshot>=1.0"`. Baseline test file (e.g., `tests/test_baseline_streaming_snapshot.py`) renders a known sequence with raw `<think>...</think>` content; first invocation with `--snapshot-update` creates `tests/__snapshots__/test_baseline_streaming_snapshot.svg`. Second invocation passes without flag (zero diff).
- **G2 (parser)**: `services/ui_shell/src/think_parser.py` exports `parse_think_segments(text: str) -> list[tuple[str, bool]]`. Unit tests in `tests/test_think_parser.py` cover: complete `<think>X</think>` (1 case); multiple think blocks in one buffer (1 case); `<think>` at buffer start (1 case); `<think>` at buffer end (1 case); partial-tag-across-boundary simulation via sequential parser calls with state (2 cases); empty `<think></think>` (1 case); unclosed `<think>X` (1 case); non-think text only (1 case); nested `<think><think>X</think></think>` rejection (1 case). Total ≥10 tests; all pass.
- **G3 (StreamingDisplay integration)**: `streaming.py` `_render_buffer` modified to call `parse_think_segments` and apply Rich markup per segment. Existing markup support (`markup=True` in `__init__`) means Rich's `[dim italic]...[/dim italic]` is rendered correctly.
- **G4 (snapshot lock)**: New snapshot test (or extension of G1 test) feeds a streaming sequence containing think markup; renders via the integrated `StreamingDisplay`; snapshot SVG captures the dim-italic rendering. Golden locked.
- **G5 (no regression)**: `pytest services/ui_shell/tests/` returns exit 0 with prior test count preserved + new tests added.
- **G6 (verification command observability)**: each §10.10 row's verification command produces the documented expected output when run from the documented cwd.
- **G7 (LA touchpoints)**: 3 LA touchpoints landed at sprint boundaries — EDD sign-off (touchpoint 1; ACCEPTED status flip + la_approved_on populated) + CR sign-off (touchpoint 2; CR status flip) + sprint-close commit (touchpoint 3; `chore(blarai): close iss-2 sprint -- think-tag rendering shipped`).

### 8.3 Work-item plan

| WI-# | Category | Working title | One-sentence purpose | Depends on | Approx size |
|---|---|---|---|---|---|
| WI-1 | s | pytest-textual-snapshot setup + baseline | Add `pytest-textual-snapshot>=1.0` to `services/ui_shell/pyproject.toml` dev deps; install in BlarAI venv; capture baseline snapshot of `StreamingDisplay` rendering a `<think>...</think>`-containing token sequence (locks pre-state). | — | S |
| WI-2 | s | Think-tag parser module | Implement pure-function `parse_think_segments(text: str) -> list[tuple[str, bool]]` in `services/ui_shell/src/think_parser.py` with ≥10 unit tests in `services/ui_shell/tests/test_think_parser.py` covering complete / partial / nested / empty / unclosed cases. | — | S |
| WI-3 | s | StreamingDisplay think-rendering integration | Modify `StreamingDisplay._render_buffer` in `services/ui_shell/src/streaming.py` to apply `parse_think_segments`; render think segments with Rich `[dim italic]` markup. | WI-2 | S |
| WI-4 | s | Snapshot test for think-rendered output | Add snapshot test feeding a think-tag-containing streaming sequence to integrated `StreamingDisplay`; lock golden SVG; verify pytest passes on re-run. | WI-1, WI-3 | S |

**Batch dispatch expectation**: WI-1 + WI-2 dispatched in parallel (disjoint working sets — pyproject.toml + new parser module). WI-3 follows WI-2 (depends on parser). WI-4 follows WI-3 (depends on integrated rendering). Then CR + SWAGR + sprint-close commit.

## 9. Cross-references

- **ADR-020** (cf-1.5) — EDD/CR/SWAGR substrate pattern. This EDD follows it.
- **ADR-023** (cf-1.5) — Orchestrator + specialist + Auditor topology; iterate-until-converged. ISS-2 inherits.
- **ADR-024** (cf-1.5 v1.2) — Notification taxonomy. Hooks fire for INTENT_CAPTURED / EXECUTION_COMPLETED / CLOSEOUT_PERSISTED per phase7 EA-22 wiring.
- **CLAUDE.md** (devplatform) — §Runtime-Binding-Validation (cross-repo cwd discipline); §Context-Exhaustion-Handoff-Discipline.
- **Memory `project-next-sprint-iss-2`** — LA selection rationale.
- **post-resumption-backlog.md §2.6** — cost-tracking instrumentation (HIGH priority; first post-resumption sprint candidate per cf-post-3 SWAGR §15.2 routing).

## 10. Workflow conventions

### 10.1 Sprint Coordinator state

- **Location**: `C:\Users\mrbla\devplatform\.sprint_state\iss-2\state.json`
- **Convention**: sprint_id "iss-2" (with hyphen) per parser-frontmatter convention.

### 10.7 Sprint phases

Per ADR-023 + ADR-020:

| Phase | Activity | Role |
|---|---|---|
| 0 | Fleet pause check | wake_launcher Test-WorkAvailable |
| 1 | (Skipped — no Vikunja Pending-Human escalation queue work for ISS-2 at kickoff) | — |
| 2 | (Already done — this EDD is Phase 2 output) | Orchestrator (proxied by Guide-#16) |
| 3a | (Skipped — no Phase-3a CR-authoring trigger until WIs done) | — |
| 3b | Within-sprint loop: dispatch specialists per WI, mark done | Orchestrator + specialists |
| 4 | (Skipped — this isn't validation-as-Phase-4-entry like cf-post-3) | — |
| 5 | (Skipped) | — |
| 6 | Close-out: Orchestrator authors CR; Auditor authors SWAGR; LA touchpoints 2 + 3 | Orchestrator + Auditor + LA |

### 10.10 Verification commands per Goal

| Goal | Verification command (run from devplatform cwd unless noted) | Expected observable |
|---|---|---|
| G1 | `cd C:\Users\mrbla\BlarAI && python -m pip install -e services/ui_shell[dev]` then `cd C:\Users\mrbla\BlarAI && pytest services/ui_shell/tests/ --snapshot-update` then `cd C:\Users\mrbla\BlarAI && pytest services/ui_shell/tests/` | First run captures snapshots; second run exits 0 with zero diffs. |
| G2 | `cd C:\Users\mrbla\BlarAI && pytest services/ui_shell/tests/test_think_parser.py -v` | ≥10 tests pass, 0 fail. |
| G3 | Read `services/ui_shell/src/streaming.py` diff — `_render_buffer` calls `parse_think_segments`; per-segment write applies `[dim italic]` markup for `is_think=True`. | Source code diff visible. |
| G4 | `cd C:\Users\mrbla\BlarAI && pytest services/ui_shell/tests/test_think_rendering.py -v` (or wherever the snapshot test lives) | Test passes; snapshot SVG present at `__snapshots__/`. |
| G5 | `cd C:\Users\mrbla\BlarAI && pytest services/ui_shell/tests/` | Exit 0; test count = (pre-sprint baseline + WI-2 unit tests + WI-1/WI-4 snapshot tests). |
| G6 | Auditor reproduces G1-G5 commands independently in SWAGR §6. | Observable evidence. |
| G7 | `cd C:\Users\mrbla\devplatform && git log --oneline --grep="\\[la" -- docs/sprints/iss_2/` or BlarAI equivalent. | 3 LA-attribution commits at boundaries. |

### 10.11 LA touchpoint cadence (3 sign-offs)

Per cf-post-3 EDD §10.11 precedent + LA preference for minimal sign-offs:

1. **EDD sign-off** (touchpoint 1; sprint kickoff / plan acceptance) — LA reviews this EDD + grants `status: ACCEPTED → ACCEPTED` + populates `la_approved_on`. THIS sprint's touchpoint 1 happens IMMEDIATELY after EDD authoring (no dispatch until ACCEPTED).
2. **CR sign-off** (touchpoint 2; close / retrospective acceptance) — LA reads the Orchestrator-authored CR + the Auditor-authored SWAGR jointly; grants CR `status: ACCEPTED → ACCEPTED`.
3. **Sprint-close commit** (touchpoint 3; operational close) — `chore(blarai): close iss-2 sprint -- think-tag rendering shipped`. This is the BlarAI-side equivalent of cf-post-3's `chore(ops): resume fleet ...`.

## 11. Risks

| # | Risk | Severity | Likelihood | Mitigation |
|---|---|---|---|---|
| 1 | Cross-repo git commits surface allowedTools gaps (orchestrator's session-level Bash restricts to devplatform git patterns) | MED | MED | Specialists' unrestricted Bash handles BlarAI commits per cf-post-3 commit-attribution pattern; orchestrator just dispatches. If a gap surfaces, document + fix as Proposal #25 candidate. |
| 2 | `pytest-textual-snapshot` install fails in BlarAI venv (e.g., conflict with existing deps) | LOW | LOW | WI-1 surfaces this immediately; specialist can pin a different snapshot tool (`pytest-snapshot`) as fallback. |
| 3 | Parser state machine has edge-case bugs in streaming partial-tag handling | MED | MED | WI-2's ≥10 unit tests target this surface. Auditor SWAGR §6 re-runs the parser tests. |
| 4 | Rich `[dim italic]` markup doesn't render as expected in the user's terminal (e.g., Windows Terminal vs ConEmu vs etc.) | LOW | LOW | Snapshot SVG captures the SVG-level markup; actual terminal rendering is downstream of the test. Future LA visual check (post-sprint) can confirm. |
| 5 | Proposal #24 (wake_launcher CR-authoring detection) checks devplatform/docs/sprints/, not BlarAI/docs/sprints/ — so post-WI-completion the wake_launcher won't auto-trigger CR authoring | MED | HIGH | EXPECTED — this surfaces a cross-repo extension need for Proposal #24. Workaround: manual trigger file post-WI-completion. Permanent fix: Proposal #25 candidate. |
| 6 | First-ever BlarAI sprint surfaces other cf-2 substrate gaps not seen during devplatform-only cf-post-3 (e.g., subagent agent-definition tool gaps, working-tree cross-repo coordination) | HIGH | MED-HIGH | EXPECTED per gap-closure-plan §7 R-1 ("Phase 3 integration surfaces new gaps"). Each surfaced gap is a discovery moment; fix in-flight per LA "fix and keep moving" autonomous-mode authorization. CR §10 captures the surfaced gaps. |

## 12. Out of scope

1. AO / PA / ui_gateway changes — see §5 Non-goal #2.
2. UX additions beyond visual rendering (folding, toggles) — see §5 Non-goal #1.
3. ISS-1 (AO Speculative Decoding) — separate ticket; later sprint.
4. ISS-3 (PA Quality Benchmark Suite) — separate ticket; later sprint; recommended as the 2nd post-cf-program BlarAI sprint per LA TUI-testing-question response cycle.
5. ISS-8 (AO conversation context across turns) — separate ticket; later sprint.
6. Retirement of stale ISS-4 (wake_launcher) / ISS-6 (STALE-QUEUE) / ISS-7 (per-sprint SCR roster transition) — defer to a dedicated devplatform-cleanup sprint OR ad-hoc EAs against the running fleet.
7. cf-post-3 §10 NON-OPTIONAL carry-overs (post-resumption-backlog §2.6 cost-tracking; §2.7 MAST FM no-op; §2.8 wake_launcher audit) — addressed in parallel post-resumption work; not bundled into ISS-2.

## 13. Timeline / estimates

- **Agent wall-clock estimate**: 1-2 hours for the 4 WIs (WI-1 setup \~20 min; WI-2 parser \~30-40 min including 10+ tests; WI-3 integration \~15-20 min; WI-4 snapshot test \~15-20 min). Plus CR + SWAGR \~30-60 min.
- **LA active-time estimate**: \~15-30 min total (EDD review + CR + SWAGR read + 3 typed sign-offs).
- **Aggregate**: \~2-3 hour fleet wall-clock + \~30 min LA-time. Comparable to cf-post-3's \~2-hour fleet + \~30-min LA pattern (per `feedback_calibrate_time_estimates_against_actuals` recalibration).
- **Calendar**: dispatch begins at next `\\DevPlatform\\Wake orchestrator` firing post-EDD-sign-off (every 15 min). First WI commits expected within \~30-45 min of EDD sign-off.

## 14. Version log

| Version | Date | Authoring | Changes |
|---|---|---|---|
| v1 PROPOSED | 2026-05-20 | Guide-#16 (proxy for autonomous Orchestrator) | Initial authoring post-cf-post-3 close. Targets BlarAI `services/ui_shell/` think-tag rendering per LA selection 2026-05-19 + LA setup-instruction 2026-05-20. |