# Headless-Coding Dispatch Go-Live Runbook

<!-- doc-rot gate (#994): the config flag(s) gating this ceremony. The EXECUTED banner below must agree with their LIVE state in services/assistant_orchestrator/config/default.toml — read there, never from this doc. -->
<!-- Gating-flag: [fleet_dispatch].enabled -->

> ## STATUS: EXECUTED — 2026-06-27. Do not re-run.
>
> This ceremony has already been performed. `[fleet_dispatch].enabled` is
> **`true`** in `services/assistant_orchestrator/config/default.toml`; the flip
> from `false` to `true` landed in commit `20c95530`
> ("feat(dispatch): make the dispatch LIVE — fleet_dispatch.enabled=true").
>
> **What this means for you:** `/dispatch` is LIVE and will spawn a real coder
> run today. The wiring described below is already in place. Everything written
> in the present tense as "not yet connected" describes the pre-2026-06-27 state.
>
> **The flip warning below is therefore spent, not live.** Step 2 tells you to
> flip the flag with the LA present; it is already flipped. Do not read that as
> "still safe to flip" — there is nothing left to flip.
>
> This file is kept as the historical record of how dispatch was activated.

**Wire → flip → first dispatch → eyeball.** ADR-034 (model swap) + ADR-035 (acceptance
layer). For the Lead Architect (non-developer-friendly). This is the on-hardware session
that takes headless-coding dispatch from DORMANT to live. The BUILD phase (increments
1+2+3) is complete and merged to `main`; everything below is the deliberately-deferred
wiring + the first real run, which are only validatable on the box.

> **What this makes live:** `/dispatch <repo> | <goal>` against the operator's OTHER
> project repos under `C:\Users\mrbla\projects` — BlarAI turns a plain goal into
> acceptance criteria, you approve them, BlarAI steps its 14B aside, loads the
> agentic-setup fleet's 30B coder, runs the work, swaps the 14B back, and reports
> honestly. It does **NOT** open any network door — the swap is loopback + local
> subprocess only, zero egress. It does **NOT** touch BlarAI's own tree (the fleet
> refuses `~/BlarAI`).

> **The one thing that flips it on:** `[fleet_dispatch].enabled = true`. Do NOT flip it
> without the LA present (this runbook's session). Until Step 2 it stays `false` and an
> enabled-but-unwired `/dispatch` just says "wiring not connected".

## Preconditions (verify BEFORE starting)

1. `main` has increments 1+2+3 merged (the dormant subsystem). On-main standing gate is
   green. (This step used to pin `4014/0` at the i3 merge `f8d0f5d`. That figure was
   accurate when written — the journal records `4014 passed / 0 failed / 0 skipped /
   118 deselected` on main at that merge, dated 2026-06-22 — but it is long out of
   date now and must not be compared against. The only figure kept in sync with the
   gate is `docs/TEST_GOVERNANCE.md` §1's `LIVE_GATE_BASELINE` line — read that.)
2. The agentic-setup fleet is installed and works **standalone**: `add-fleet-task.ps1`,
   `run-fleet.ps1`, and `start-llm.ps1 -Model coder-30b -Force` all run, and the 30B
   loads on the Arc 140V (this is the operator's existing coder fleet — confirm it works
   on its own BEFORE wiring BlarAI to it).
3. The milestone-1 memory-domain reality holds: the 14B and 30B cannot co-reside, so the
   swap is a **full step-aside** (the launcher process exits during the run). The WinUI
   window will close for the run and reopen when the 14B is back — expected.
4. A throwaway target repo exists under `C:\Users\mrbla\projects` for the first dispatch —
   make it a **Python** repo (Python behavior tests actually run in the fleet gate; .NET
   is build-only — see ADR-035), e.g. an empty git repo with a `pyproject.toml`.

> **INTERPRETER — run every Python command with the project venv, not bare `python`.**
> `C:/Users/mrbla/blarai/.venv/Scripts/python.exe` (3.11.9, full deps). Run from the repo
> root `C:\Users\mrbla\BlarAI` so `shared.*` imports resolve.

## Step 1 — Wire the IPC (the deferred command-hookup — this is CODE, so branch + tests + journal)

This connects the gateway's confirm flow to the resident 14B (PLAN) and to the swap driver
(EXECUTE). `DispatchCoordinator` (`services/ui_gateway/src/dispatch_coordinator.py`,
constructed in `services/ui_gateway/src/transport.py` — find it by symbol, not by
line number; the runbook's original "\~line 367" is now 482) shipped **at the time
this was written** with `plan_fn=None` / `execute_fn=None`. **That is no longer
true: both are wired today** (`plan_fn=self._dispatch_plan_fn`,
`execute_fn=self._dispatch_execute_fn`), which is what the go-live did. The
injection described below is the work that was done, not work to do. Inject both as AO round-trips (mirror how the
`ingest`/`imagine` coordinators reach the AO via their async `transport_call`):

- **`plan_fn(repo, goal)`** → a new AO PLAN verb that runs
  `shared.fleet.acceptance.generate_plan(goal, repo, generate_fn=<the AO's text generator>,
  projects_dir=<config>)` while the 14B is resident, and returns the `PlanResult`
  (tasks + `spec.to_dict()` on the wire). Nothing irreversible — the operator approves next.
- **`execute_fn(session_id, run_id, repo, tasks, spec)`** → a new AO EXECUTE verb that fires
  `shared.fleet.swap_ops.orchestrate_swap_dispatch` with the **already-approved `tasks`**
  (skip re-decompose — add the small pass-through so EXECUTE enqueues the approved tasks
  rather than re-running the 14B), supplying the AO's own `old_pid` (`os.getpid()`) +
  `relaunch_argv`/`relaunch_cwd`, then signaling the launcher to step aside (exit). Build the
  **internal branch** here: if the 30B is already loaded (OVMS ready), skip the swap — just
  enqueue + `run_fleet` directly (no step-aside); else do the full swap. Either way the
  confirm already happened (this fires only from `/dispatch approve`).
- The gateway already writes the run-id-keyed acceptance record on approve (so
  `/dispatch status` can render the honest report after the swap restart) — no extra work.

While here, clear the two standing pre-go-live items:
- ~~**Promote the hardcoded paths:** `_AGENTIC_SETUP` / `_PROJECTS` in
  `shared/fleet/dispatch.py` → `[fleet_dispatch]` config keys.~~ **DONE** — the keys
  exist (`[fleet_dispatch].agentic_setup_dir` / `projects_dir`, `default.toml:420-421`)
  with env and TOML override over a compiled-in fallback. Listed here as pending
  work in the original; it has since shipped.
- **Harden the acceptance prompt (Enhancement-1, partial):** ~~change the
  `acceptance-tests` task prompt in `acceptance.compile_prompts` to *"assert the
  criterion's REQUIRED behavior, not whatever the code currently does."*~~ **The prompt
  change is DONE** — `shared/fleet/acceptance.py` carries that anti-mirror instruction
  verbatim inside `compile_prompts`, plus a property-test clause that goes further.
  Only the remainder below is still open. The full red-first / mutation validation (confirm
  the test fails on broken code before trusting its pass) is the remaining Enhancement-1.

Land Step 1 on a feature branch with tests (the PLAN/EXECUTE handlers, the skip-swap branch,
the config-paths promotion), an ADR-035 amendment ("live wiring activated"), and a journal
entry — same discipline as the build increments. Keep `enabled=false` through this step.

## Step 2 — Flip the flag (LA present)

With Step 1 merged and the fleet confirmed standalone, flip the master lock:

- `services/assistant_orchestrator/config/default.toml` → `[fleet_dispatch] enabled = true`.

Restart the backend so the launcher threads the new value through to the gateway. `/dispatch`
now plans + confirms for real.

## Step 3 — First dispatch (small, Python, throwaway)

In the running app:

1. `/dispatch <your-python-test-repo> | add an add(a, b) function that returns a + b`
2. Read the **criteria preview**: it should list a build criterion + a behavior criterion
   ("add(2,3) is 5" or similar), and — because this is Python — NOT show the .NET
   build-only caveat. If it reads wrong, `/dispatch reject` and refine the goal.
3. `/dispatch approve` — this is the only thing that fires work.

## Step 4 — Eyeball + verify (what "it worked" looks like)

1. **Swap fires:** the WinUI window closes for the run (full step-aside) and reopens when
   the 14B is back. While it's down, the assistant is offline (expected; minutes).
2. **Honest report:** `/dispatch status` shows PASS for the behavior criterion that
   actually ran (Python → the test ran), and the run merged into your project. A criterion
   whose test didn't run would read NOT AUTO-CHECKED, never a false PASS.
3. **Open the app:** run the printed open-the-app command (for Python, `python <entry>` or
   "open the folder") and confirm the change is there.
4. **14B restored, 30B down:** the assistant answers again; `Get-Process ovms` is empty
   (the swap disarmed the watchdog sentinel then stopped OVMS).
5. **Zero egress:** nothing left the box — the swap is loopback + subprocess only. (The
   air-gap guard `tests/security/test_no_external_egress.py` already proves the runtime
   imports no network client; confirm no surprise connections during the run.)
6. **Crash recovery (optional, worth doing once):** kill the swap driver mid-run and
   reboot the backend — the every-boot reconciler should converge to "14B up, 30B down"
   on its own (ADR-034 NEVER-ZERO).

## Step 5 — Record (community-grade + portfolio)

- Swap + run latencies (14B-release, 30B-load, end-to-end) → `PERFORMANCE_LOG.md` +
  `docs/performance/` (the real Arc 140V numbers; name what's not measured).
- A BUILD_JOURNAL entry for the go-live (the arc + the live measurements + the first real
  dispatch). Update the CLAUDE.md Active-State test baseline if a count moved.
- Close the remaining Enhancement-1 (full red-first/mutation validation) on #670, or keep
  it open with a date.

## Notes / out of scope

- **Full red-first/mutation validation (Enhancement-1):** the 30B writes its own acceptance
  tests, so a wrong/vacuous test can still false-pass. Step 1's prompt-hardening nudges it;
  the durable fix (run the test against deliberately-broken code first, require it to fail)
  is the remaining #670 item.
- **WinUI reconnect (#670):** the nicer "window stays up with a building… state" instead of
  closing/reopening is the deferred reconnect work; the full-relaunch UX above is the
  shipped behavior.
- **No network door:** unlike the UC-003/web-search go-lives, this opens nothing on the
  egress side. If a future enhancement wants the fleet to fetch anything, that is a
  separate egress-governance event (ADR-027), not part of this.
