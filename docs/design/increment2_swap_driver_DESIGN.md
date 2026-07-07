# Increment 2 — Model-Swap Driver — DESIGN (APPROVED FOR BUILD)

**Status:** APPROVED FOR BUILD (LA, 2026-06-21). Round-1 rulings + round-2 failure-path
gaps folded below; the LA verifies them in the built code (no third design round).
**Build contract:** ship DORMANT behind `[fleet_dispatch].enabled`; tests at the
state-machine / reconciler-idempotency / gate-abort / cancel / fail-path level (real
execution, mocked at the model-swap boundary); ADR + BUILD_JOURNAL in the same commit;
shown for review before any merge; the live swap on real hardware is the LA's step.

**Scope:** the host-level model-swap driver that lets a `/dispatch` load the agentic-setup
30B by stepping BlarAI's 14B fully aside, then restores the 14B.
**Grounding:** brief §4 (the Option-A swap state machine) + the milestone-1 measurement
(this repo, `chore/milestone1-14b-release-measurement`).

**Round-2 gaps folded (LA review 2):** (1) RESTART-AO failure path — bounded retry + an
out-of-band failure signal + the explicit "backend won't come back" branch (§2.3); (2)
conv-state at rest — persist only `{run_id, session_id, tasks, phase}`, reload conversation
from the encrypted `sessions.db` by `session_id` (§4.1). Minors: the restore is two
mechanisms across a process boundary (§2); a pre-step-aside guard (step 5b); whole-queue +
dormant + cancel-granularity confirmations (§9).

---

## 0. Comprehension (one paragraph)

Increment 2 automates the 14B⇄30B model swap so a coding dispatch can run the fleet's 30B,
which cannot co-reside with BlarAI's 14B in \~31 GB. The 14B does its one intelligent job —
decomposing the request into validated fleet tasks — while still resident, then BlarAI
enqueues them, persists `{run_id, session_id, tasks, phase}` (NOT conversation content) to
disk, hands off to a **detached host driver** (spawned breakaway so it outlives BlarAI), and
**fully steps its backend aside (the 14B process EXITS)**. The driver gates on real ambient
headroom, loads the 30B via `start-llm.ps1 -Force`, runs `run-fleet.ps1` against the persisted
RunId for the whole queue, then **disarms the watchdog and stops OVMS**, and restarts BlarAI's
backend with a bounded retry — always converging to "14B up, 30B down," and signalling loudly
out-of-band if the backend won't come back. The restarted AO reloads the conversation from the
encrypted `sessions.db`, reads the RunId's `SUMMARY.txt`, and reports into the session. The
single biggest design fact: milestone 1 showed a bare in-process unload frees only \~20.1 GB
(below the 30B's load need), so a **full process step-aside** is required, which is why a
detached driver (not the AO) runs the swap.

---

## 1. Core design decision — full step-aside ⇒ a detached driver (RATIFIED divergence from brief §4.2)

Brief §4.2 keeps the **AO process alive**, unloads the 14B in-process, gates \~21 GiB, and has
the alive AO drive the swap. **Milestone 1 measured the bare in-process unload reaches only
\~20.1 GB** — below the brief's own gate and the 30B's \~22–23 GB load need. The \~6 GB gap is the
AO process's non-model residency (Python heap, INT8 draft, Level-Zero context, KV/embedding
caches) that only a **process exit** frees; an idle box with BlarAI gone sits at \~26 GB.

**Therefore (LA-ratified):** UNLOAD is a **full backend-process step-aside (exit)**, and because
the AO is then gone for the run, a **detached host driver** (spawned breakaway, the increment-1
`run_fleet` mechanism) executes the swap and restarts the backend. This diverges from the brief's
in-process framing (which treated a full restart as a last resort); the divergence is forced by
the milestone-1 number and is exactly the "host-level driver surviving teardown" + "full
step-aside" invariants.

---

## 2. The state machine (brief §4.2 states, realized with the detached driver)

Phases are persisted **write-ahead** (before each transition) so a crash reflects the last-
entered phase (§2.1). `‹14B›` = runs while the 14B is resident; `‹driver›` = the detached host
process.

```
IDLE-14B
 ‹14B›  1. DECOMPOSE   user's coding idea -> N concrete fleet tasks (the 14B's only job)
 ‹14B›  2. VALIDATE    deterministic ruler per task (repo under projects, slug, prompt);
                       fail -> abort cleanly, 14B untouched, nothing swapped
 ‹14B›  3. RESERVE     run_id R = new_run_id(); persist {R, session_id, tasks, phase} ONLY
                       (NO conversation content to disk — privacy; conv stays in the encrypted
                       sessions.db, reloaded by session_id at step 13)
 ‹14B›  4. ENQUEUE     add-fleet-task.ps1 per task   (engine enqueue_task)
 ‹14B›  5. HANDOFF     spawn driver detached+breakaway with (R, swap-state path);
                       tell the user "dispatching R — assistant offline until it returns"
 ‹14B›  5b. PRE-GUARD  if Available + expected-freed (14B ≈10-13 GB) < gate -> ABORT BEFORE any
                       teardown (box too loaded for step-aside to clear the gate); 14B untouched,
                       tell the user. Avoids a pointless teardown+reload that can't help.
 ‹14B›  6. STEP-ASIDE  finish any in-flight gen (no mid-stream teardown); the 14B BACKEND PROCESS
                       EXITS (conv already safe in sessions.db)
--- the 14B is now fully gone; the driver takes over ---
 ‹driver› 7. SETTLE    poll until the OLD backend PID is GONE (the release); headroom is
                       the GATE's job (8), so "released but still loaded" is a clean gate-abort
 ‹driver› 8. GATE      Available >= [fleet_dispatch].swap_min_free_gb (default 21) -> proceed;
                       below -> SKIP load, go to 11 (graceful, never-zero): restore the 14B and
                       report "not enough headroom now (X < 21) — free something or retry"
 ‹driver› 9. LOAD-30B  start-llm.ps1 -Model coder-30b -Force   (kills+restarts ovms, ARMS watchdog
                       via server-should-run.txt, starts the :8099 qwen-proxy);
                       WAIT READY: poll GET 127.0.0.1:8000/v3/models until id==coder-30b (~240s);
                       fail -> ROLLBACK to 11
 ‹driver› 10. CODE     run the queue under RunId R (per-task; §2.2), one residency; fleet owns
                       build/verify/merge; writes state/fleet-runs/R/SUMMARY.txt.
                       Check the cancel sentinel at each task boundary (§2.2).
 ‹driver› 11. UNLOAD-30B  (a) rm state/server-should-run.txt   <-- DISARM watchdog FIRST
                          (b) Stop-Process -Force -Name ovms    (NOT stop-llm.ps1 — interactive/Start-VM)
 ‹driver› 12. RESTART-AO  re-launch BlarAI's backend (cold) with BOUNDED RETRY; persistent fail
                          -> OUT-OF-BAND failure signal (§2.3), never strand silently
--- the 14B is loaded fresh by the restarted backend ---
 ‹14B›  13. RELOAD     fresh LLMPipeline (never a half-freed one — #33896 garble); reload conv
                       from the encrypted sessions.db by session_id
 ‹14B›  14. SMOKE      one tiny generation must be coherent; fail -> last resort: full process restart
 ‹14B›  15. REPORT     read_summary(R) -> post MERGED/PARK/BLOCKED into session_id; mark REPORTED
IDLE-14B
```

**The restore is two mechanisms across a process boundary**, not one `finally`: (i) the
**driver's `finally` covers steps 11–12** (disarm+stop the 30B, then restart the backend with
bounded retry) on every failure path (gate-fail, load-fail, mid-run crash, cancel); (ii) the
**every-boot reconciler covers steps 13–15** (fresh 14B reload + coherence smoke + report) once
the backend is back — the driver cannot reach into the restarted process. The `:8099` proxy is
fixed infrastructure that survives the transition; the driver leaves it running.

### 2.1 Mid-swap crash recovery — the concrete convergence mechanism (LA must-nail #1)

**Scenario:** the box dies/reboots mid-swap with the **30B up and the 14B down**. Convergence to
"14B up, 30B down" is guaranteed by an **idempotent reconciler that runs on EVERY BlarAI backend
boot, before the AO serves**, **gated on a non-terminal BlarAI swap-state file ONLY** (F2 — NOT
the fleet's `state/server-should-run.txt` sentinel, which is the FLEET's, armed whenever the operator
runs the 30B; keying off it would kill the operator's running 30B on any BlarAI boot). When a swap
WAS in flight it then disarms the sentinel + stops OVMS:
1. **DISARM:** `rm state/server-should-run.txt` (idempotent) — the watchdog can't resurrect the
   30B without it; done first.
2. **FREE:** `Stop-Process -Force -Name ovms` if present (idempotent; reboot may already have killed it).
3. **COLD-LOAD 14B:** the normal backend boot loads the 14B fresh (brief §4.2 default recovery).
4. **RECONCILE THE RUN:** read the swap-state. phase ≥ CODE: check `state/fleet-runs/R/SUMMARY.txt`
   → present → report into `session_id`; absent/partial → "dispatch R was interrupted; completed
   tasks are in the fleet's done.txt and it's resumable — re-dispatch or `/dispatch status R`."
   **No auto-resume on boot** (that would re-enter an unattended swap). Mark RECOVERED.

**Both crash shapes:** soft crash (a live start-llm-spawned watchdog could re-arm OVMS → step 1
removes the sentinel before its next poll); reboot (OVMS + a spawned watchdog die → boot at zero
models → reconciler removes the stale sentinel + cold-loads 14B). The one residual — a *persistent
scheduled-task* watchdog beating the reconciler on reboot — is a build-time confirm (§6.2);
escalate if the documented sentinel can't win it. The reconciler runs **every boot** and is a
no-op when no swap was in flight (steps 1–2 idempotent, 3 is the normal boot).

### 2.2 Minimal cancel — per-task granularity (LA-ratified)
A **cancel sentinel** (e.g. `state/fleet-swap/cancel`) is checked by the driver **at each task
boundary** (step 10). On cancel: stop after the current task, then fall through to UNLOAD-30B →
RESTART-AO → restore 14B; the report shows tasks merged/parked before cancel + the rest as
"cancelled (resumable via `-RunId R`)." **Granularity = per-task:** we do NOT tree-kill a task
mid-flight (that orphans a half-built worktree); a long single task therefore delays the cancel
until it completes (the fleet's own `MaxRunMinutes` breaker bounds a runaway task). The sentinel
is written by the WinUI "Cancel dispatch" action in backend-only mode, or a documented manual
touch in the full-relaunch fallback.

### 2.3 RESTART-AO failure — the "backend won't come back" branch (LA must-nail #1)
Step 12 is the single most dangerous action: by then the 30B is stopped, so a failure leaves
**zero models and a down assistant that cannot notify through itself.** Handling:
1. **Bounded retry:** retry the backend relaunch up to N times (default 3) with a short backoff,
   re-confirming via a **readiness probe** (the AO health endpoint) that the backend actually came
   up — not merely that the launch command returned.
2. **Out-of-band failure signal** when retries are exhausted (the assistant is NOT coming back on
   its own):
   - **backend-only mode:** the still-running WinUI shows a loud, persistent banner — *"Model swap
     failed — BlarAI's assistant did not restart. Run R is done; restart BlarAI to recover."*
     (the WinUI polls a driver-written status file).
   - **full-relaunch mode (no WinUI up):** the driver writes a conspicuous status file
     (`state/fleet-swap/SWAP_FAILED_<R>.txt`) with the diagnosis + recovery steps so the failure is
     visible without the assistant. (A real Windows toast is a #670 follow-up — the prior inline pwsh
     did NOT actually raise one, so it is dropped; the status file IS the signal.)
3. **Bounded + safe:** the watchdog stays disarmed and OVMS stays stopped, so the box sits at
   **zero models** (not a resurrected 30B) until the user restarts BlarAI — at which point the
   **every-boot reconciler (§2.1)** cold-loads the 14B and reports run R. Loud failure, one-action
   recovery (restart BlarAI), never a silent strand.

---

## 3. Invariant → mechanism

| Invariant (yours + brief §4.3) | Mechanism |
|---|---|
| Host-level driver, survives teardown | Detached + `CREATE_BREAKAWAY_FROM_JOB` (increment-1 `run_fleet`) |
| Full step-aside | Backend **process exits** (step 6) — frees 14B + draft + caches + Level-Zero |
| Never two large models resident | 30B load (9) gated behind "backend PID gone + pool returned" (7); OVMS stopped (11) before AO restart (12) |
| Never end at zero | Driver `finally` (11–12, w/ retry) + the every-boot reconciler (13–15); coherence smoke confirms the 14B answered; last-resort full restart |
| RESTART-AO can fail | Bounded retry + readiness probe + out-of-band signal + the §2.3 zero-models-but-loud branch |
| Crash-recoverable / idempotent | §2.1 boot reconciler (disarm → free → cold-load → reconcile); runs every boot; default = tear down + cold 14B |
| Disarm watchdog before OVMS stop | Step 11 / reconciler step 1: `rm server-should-run.txt` **before** `Stop-Process ovms` |
| Never `stop-llm.ps1` from automation | Bare `Stop-Process -Force -Name ovms` (stop-llm is interactive + may `Start-VM` the BlarAI VM) |
| Headroom gate (LA-set) | 21 GiB (`swap_min_free_gb`, = start-llm's gate); milestone-1-margin rec was 24; graceful by design |
| Graceful gate-abort | Gate-fail (8) + pre-guard (5b) restore the 14B + return "X < 21, free/retry" — never a hard failure |
| No conv-state in plaintext | Persist `{run_id, session_id, tasks, phase}` only; reload conv from encrypted sessions.db (§4.1) |

---

## 4. The three things you asked me to address explicitly

### (1) AO → driver handoff + post-restart continuity (privacy-correct)
- **Up front (step 3, 14B resident)** BlarAI writes ONLY `{run_id R, session_id, tasks, phase,
  ts}` to the swap-state file — **no conversation content** (privacy-absolute / born-encrypted:
  raw conversation must never hit a plaintext file). The conversation already lives in the
  encrypted `sessions.db`; the restarted AO **reloads it by `session_id`** (step 13), exactly as a
  normal cold boot resumes a session. `R` comes from `new_run_id()`; `run_fleet` accepts a provided
  `-RunId R` (increment-1 supports it), so the persisted id is the exact id the fleet writes its
  summary under. (Realizes brief §4.2 "persist AO/PA state" **without** a plaintext conv file; if
  more ever must be persisted, the swap-state file is encrypted — but reload-by-session_id avoids it.)
- **Handoff:** the driver receives `(R, swap-state path)` as argv; it never needs the live AO.
- **Recovery on restart (the §2.1 reconciler):** fleet done → `read_summary(R)` → post into
  `session_id`; not done → "in progress / interrupted," and `/dispatch status R` reads `SUMMARY.txt`
  directly (works since increment 1). **Continuity never depends on the driver and AO being up at
  the same instant.**

### (2) Where the 14B decomposition sits — explicit ordering
`DECOMPOSE → VALIDATE → RESERVE(R) → ENQUEUE → HANDOFF → 5b PRE-GUARD → (only now) STEP-ASIDE →
swap`. Decompose+enqueue happen **while the 14B is resident, before any teardown** — matching the
brief §4.2 UNLOAD trigger verbatim ("decomposed it AND enqueued the tasks") and its batch rule
(decompose+enqueue all, swap once, run the queue, swap back once — never ping-pong; each swap is
30–90 s of dead GPU compile). The decomposer is templated + checked by a **deterministic ruler** at
VALIDATE (never self-certified); a failed ruler aborts before any swap, 14B untouched.

### (3) Pre-load headroom gate — **21 GiB** (LA-set), tunable + graceful
- **Measured reality:** 30B load peak \~22–23 GB; bare unload-only reached only \~20.1 GB; full
  step-aside → \~26 GB idle.
- **Gate: abort the load if post-step-aside `Available < 21 GiB`** (LA directive). 21 matches
  start-llm's own coder-30b gate and aborts only on a genuinely-too-low ambient; after a full
  step-aside (\~26 GB) it rarely binds. **Trade-off on record:** milestone-1 put the load peak at
  \~22–23 GB, so 21 can sit right at the margin — the milestone-1-margin recommendation was 24
  (\~1–2 GB above the peak). The LA chose 21 (fewer false-aborts; consistency with start-llm),
  accepting the marginal-load case — safe here because the gate is GRACEFUL: a load at 21–23 GB
  thrashes-then-loads rather than hard-failing, and a true abort restores the 14B.
- **(a) Graceful + recoverable** (LA): gate-fail (8) and pre-guard (5b) restore the 14B + return
  "not enough headroom now (X < 21) — free something or retry." Nothing swapped; assistant back as
  before.
- **(b) Config key** (LA): `[fleet_dispatch].swap_min_free_gb` (default 21), tunable without a code
  change — sits with the pre-go-live path keys (#670). Raise toward 24 for the milestone-1 margin.

---

## 5. `-Force` — RATIFIED (use `-Force` + our own gate before start-llm)

`start-llm.ps1 -Model coder-30b -Force`, with the **driver's own deterministic 21 GiB gate run
BEFORE `start-llm`**. `-Force` is mandatory per brief §4.1/§4.2/§4.3/§8 to run start-llm
**non-interactively** — without it the interactive memory assistant (`Read-Host`) hangs headless
and can **`Stop-VM 'BlarAI-Orchestrator'`** mid-swap. The only thing `-Force` skips is start-llm's
own redundant memory gate — moot here, because our gate already checked headroom (first,
deterministically) and the 14B has stepped fully aside. (The original "never `-Force`" conflated
"don't rely on the skipped gate" with "don't use the flag"; resolved.)

---

## 6. Build-time confirmations — RESOLVED by investigation (2026-06-21)

### 6.1 WinUI reconnect → backend-only NOT viable; build uses FULL RELAUNCH (LA must-nail #2)
**Resolved:** the WinUI connects over a single named pipe ("BlarAI") with **NO reconnect logic**
(`Ipc/PipeClient.cs`, `Ipc/BackendClient.cs`) — when the backend dies the pipe is stale and the UI
bricks until a manual window reopen. AND the backend is **not a separable child**: the 14B runs
**in-process in the launcher** (`launcher/__main__.py` `build_shared_pipeline()` + the AO/PA daemon
threads), so freeing it means the **launcher process exits**, which also takes down the pipe server.
So backend-only step-aside (WinUI stays + reconnects) is **NOT viable as-is**. Per the LA's
pre-authorized fallback, **the build uses FULL RELAUNCH**: the driver relaunches the whole launcher
(`python -m launcher --winui`), which reloads the 14B and re-opens the WinUI window.
**UX consequence (surfaced to LA):** the WinUI window **closes for the duration of the swap and
re-opens when the 14B is back** — it does not stay up with a live banner. The out-of-band failure
signal is therefore a **driver-written status file** (not an in-UI banner; a real toast is a #670 follow-up), and
cancel is a **documented sentinel** (no in-UI button while the window is down). *Follow-up option
(tracked #670, not in this build):* add WinUI reconnect logic (poll-timer + reconnect + status
banner) for the nicer backend-only UX (window stays up across the swap).

### 6.2 Other confirms — RESOLVED
- **Step-aside handle:** the launcher runs the backend in-process; "step-aside" = the launcher
  PROCESS exits and the driver relaunches `python -m launcher --winui` (the launcher passes its own
  `sys.executable` + argv + cwd to the driver so the relaunch is identical). The reconciler hook is
  `AssistantOrchestratorService.start()` (entrypoint.py), after config load, BEFORE the 14B GPU load.
- **Watchdog:** a **scheduled-task** script (`scripts/watchdog.ps1`, \~2-min cadence), **NOT currently
  registered** on this box — so nothing auto-restarts OVMS today (crash or reboot). If registered it
  has `-AtLogOn` + repetition ⇒ would survive reboot and could re-arm the 30B; the reconciler's
  **disarm-first** (`rm server-should-run.txt`) is the defense and the documented contract.
  `start-llm.ps1 -Force` itself disarms before its own OVMS kill (`:208`); the driver must still
  disarm before ITS `Stop-Process ovms`.
- **`run-fleet` per-task:** confirmed — re-invoking with a shared `-RunId` + single-task queue files
  accumulates `done.txt`/`journal.log`/the run-folder (option a), enabling per-task cancel. Caveat:
  `SUMMARY.txt` is **overwritten per invocation** (only the last task), so the driver **accumulates
  the cumulative report itself** across the per-task loop rather than relying on one whole-queue file.
- **`-Force` skips the 21 GiB gate** (confirmed `start-llm.ps1:116-205` wraps the gate in
  `if (-not $Force)`) — exactly why our **own 21 GiB gate runs first** (§5).
- **`:8099` proxy / `opencode.json` routing** — a live-time check (not blocking the dormant build).

---

## 7. Decisions — all RATIFIED

`-Force` (use it + our gate, §5); full step-aside (§1); gate 21 GiB (LA-set) graceful + config key (§4.3);
minimal cancel per-task (§2.2); backend-only step-aside contingent on §6.1; offline-during-run
accepted (named in the ADR + journal at build).

---

## 8. Scope — increment 2 includes / defers

**Built + tested + dormant (this increment):** the swap SUBSYSTEM — the detached swap driver
(steps 7–15), write-ahead swap-state + the every-boot reconciler (§2.1, wired into the AO boot),
the graceful config-keyed gate + pre-guard, the fleet start/stop discipline, the per-task minimal
cancel (§2.2), the bounded-retry restart + out-of-band failure signal (§2.3), the cumulative
report, the 14B decomposer→ruler (replacing increment-1's single-task framing), the real
`SwapOps`, and the AO-side `orchestrate_swap_dispatch`. **42 tests**, mocked at the model-swap
boundary.

**Lands with the on-hardware go-live (live-only-validatable):** the final COMMAND-HOOKUP — wiring
`orchestrate_swap_dispatch` into the live `/dispatch` through the gateway/launcher (the AO
`generate_fn` for decomposition, the launcher's step-aside callback, the `old_pid`/relaunch-argv
capture). The launcher-exit→relaunch dance + the real subprocess ops can only be validated on the
real box; wiring them unvalidated into the live boot/dispatch path would add risk no headless test
catches. So `/dispatch` keeps its increment-1 behavior until the go-live welds this last seam.

**Defers:** anything weakening the fleet's verify gate (never — advisory self-review only);
multi-host generalization + the WinUI-reconnect "window-stays-up" UX (both #670).

---

## 9. Confirmations (LA-requested)

- **Whole-queue:** confirmed — a `/dispatch` runs the **entire pending queue** (`run-fleet -Queue`
  processes every entry, including a pre-existing practice/add-function task), per the brief's batch
  model. **Be aware:** the first real dispatch also runs whatever is already queued. If a dispatch
  should ever run ONLY its just-enqueued tasks, that's a scoping change — say so and I'll add a
  per-dispatch queue partition; default = whole queue (intended).
- **Dormant:** confirmed — increment 2 ships behind the SAME `[fleet_dispatch].enabled` flag. False
  → the coordinator never reaches the swap path; no swap/teardown; no behavior change until the flip
  **and** a WinUI rebuild (the cancel/out-of-band banner is new C#). Dormant exactly like increment 1.
- **Cancel granularity:** per-task (§2.2) — a long single task delays the cancel until it completes.
- **Pre-step-aside guard:** added (step 5b).

---

**APPROVED FOR BUILD (LA, 2026-06-21).** Ships dormant; ADR + BUILD_JOURNAL land in the same
commit; shown for review before any merge. The live swap on real hardware is the LA's step.
