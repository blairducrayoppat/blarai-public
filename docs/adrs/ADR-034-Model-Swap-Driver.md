# ADR-034 — Headless-coding dispatch increment 2: the host-level model-swap driver

**Status:** PROPOSED 2026-06-22 (design `docs/design/increment2_swap_driver_DESIGN.md` is the
approved spec — LA-approved-for-build with round-1 + round-2 rulings folded; this ADR records the
decision). Built **DORMANT** — `[fleet_dispatch].enabled=false` ships, so no swap, teardown, or
subprocess ever runs until a separate go-live. The live swap on real hardware is the LA's
on-hardware step.
**Deciders:** Lead Architect (blarai); the build (this session).
**Builds on:** the increment-1 dispatch surface (`shared/fleet/dispatch.py`, `/dispatch`, ADR-less
feature merge `04d9778`); the agentic-setup brief §4 (the Option-A swap state machine — the fleet
side is the authority on its own scripts); milestone-1 (`chore/milestone1-14b-release-measurement` —
the memory-domain measurement that forces the design).
**Relates to:** Vikunja #670; `Use Cases_FINAL.md` (dev-tooling capability, not a numbered UC).

## Context

BlarAI's 14B (host-side, in OpenVINO GenAI on the Arc 140V) and the agentic-setup fleet's 30B coder
cannot co-reside in the 31.323 GB shared ceiling. Increment 1 dispatched coding tasks to the fleet
with the 30B loaded **manually**. Increment 2 automates the 14B⇄30B swap so a `/dispatch` can run the
30B end-to-end and restore the 14B — the one genuinely new hard part (brief §4).

The brief's §4.2 keeps the AO process alive and unloads the 14B in-process (gate \~21 GiB). **Milestone
1 measured that the bare in-process unload frees only to \~20.1 GB on this box** — below the 30B's
\~22–23 GB load peak — because \~6 GB of the live AO process (Python heap, the INT8 draft, the
Level-Zero context, KV/embedding caches) is freed only by a process exit; a fully-gone BlarAI sits at
\~26 GB. So the brief's in-process path does not clear on this box.

## Decision

A **detached host-level swap driver** executes the swap, because a process cannot tear itself down and
bring itself back, and "full step-aside" (a process exit, not an in-process unload) is required by the
milestone-1 number:

1. **Decompose while resident, before teardown** (the 14B's one job): NL idea → N concrete fleet tasks
   via the 14B, **validated by a deterministic ruler** (the model proposes, the ruler disposes — never
   self-certifies, brief §7.3), with a single-task fallback so a dispatch never produces zero work.
2. **Reserve a RunId, persist a write-ahead swap-state record, enqueue, hand off** to the driver
   (spawned detached + `CREATE_BREAKAWAY_FROM_JOB`, the increment-1 pattern, so it outlives BlarAI),
   then the launcher **fully steps aside (the process exits)**.
3. The driver **gates on real headroom** (graceful, recoverable abort), **loads the 30B**
   (`start-llm.ps1 -Force` — mandatory per brief §4 to avoid the interactive `Stop-VM` hang; our own
   gate runs first), runs the queue **per-task** (cancel-aware), **disarms the watchdog sentinel then
   stops OVMS**, and **restarts the launcher with a bounded retry**.
4. **NEVER-ZERO** is structural: the driver's teardown (stop 30B → restart launcher) runs on every
   path (clean finish, gate-abort, settle-timeout, load-fail, cancel, exception). If the restart
   persistently fails, it signals **out-of-band** (a status file; a real toast is a #670 follow-up) — zero models, but
   loud and one-action-recoverable (restart BlarAI), never a silent strand.
5. **Crash recovery** is an idempotent reconciler that runs on **every backend boot** (wired into
   `AssistantOrchestratorService.start()`), **gated on a non-terminal BlarAI swap-state ONLY** (F2 —
   never the fleet's sentinel): when a swap was mid-flight it disarms the sentinel → stops the 30B →
   cold-loads the 14B → reports; otherwise a total no-op that never touches the fleet's OVMS/sentinel.
   Converges to "14B up, 30B down" after any crash or reboot.

**Key rulings folded:** the pre-load gate is **`[fleet_dispatch].swap_min_free_gb = 21`** (LA-set,
matching start-llm's own gate; the milestone-1-margin recommendation was 24, recorded as a trade-off —
the gate is graceful so a 21–23 GB load thrashes-then-loads, never a hard fail); **conv-state is never
persisted to disk** (only `{run_id, session_id, tasks, phase}`; the conversation reloads from the
encrypted `sessions.db` by `session_id` — privacy-absolute); cancel granularity is **per-task**.

**Build-time confirmations RESOLVED by investigation:** the backend is **in-process in the launcher**
(step-aside = the launcher exits; the driver relaunches `python -m launcher`); the **WinUI has no
reconnect logic**, so backend-only step-aside is not viable → the build uses the LA-pre-authorized
**full-relaunch** (the WinUI window closes for the swap and re-opens when the 14B is back — out-of-band
signal is a status file (not an in-UI banner; a real toast + WinUI-reconnect are tracked at #670);
the fleet **watchdog scheduled-task is not currently registered** (nothing auto-restarts OVMS today;
disarm-first remains the contract); **`run-fleet` per-task** invocation under a shared `-RunId` is
supported (enabling per-task cancel; the driver accumulates the cumulative report since `SUMMARY.txt`
is overwritten per invocation).

**Security posture:** the driver is host-level orchestration (outside BlarAI's runtime trust domain,
like the fleet itself) — local subprocess + loopback only, **no external network egress**; the
swap-state file carries no conversation content; the dispatch targets the operator's OTHER projects
(the fleet refuses `~/BlarAI`); ships dormant behind the SAME `[fleet_dispatch].enabled` flag as
increment 1.

**Scope built this increment:** the full swap **subsystem** — state machine + reconciler + decomposer
+ orchestration + real ops + config — built, tested (42 tests, mocked at the model-swap boundary), and
dormant. The **final command-hookup** (wiring `orchestrate_swap_dispatch` into the live `/dispatch`
through the gateway/launcher, with the AO `generate_fn` and the launcher step-aside callback) lands
**with the on-hardware go-live**, because the launcher-exit→relaunch dance is only validatable live —
wiring it unvalidated into the live boot/dispatch path would add risk no test could catch.

## Consequences

- **Offline-during-run** (accepted, named): for the whole 30B residency (minutes–hours) the assistant
  cannot answer. Mitigations: the up-front "assistant offline until it returns" notice, the per-task
  cancel, and the disk-mediated continuity report on return.
- **Full-relaunch UX:** the WinUI window closes during the swap and re-opens after (a consequence of
  the in-process-14B architecture + the no-reconnect WinUI; the nicer window-stays-up UX is the #670
  reconnect follow-up).
- **21 GiB gate** trades the milestone-1 margin for fewer false-aborts + start-llm consistency; safe
  because the gate is graceful.

## Rejected alternatives

- **In-process unload, AO stays alive** (brief §4.2): milestone-1 measured \~20.1 GB free — below the
  30B's load peak. Rejected on this box; forces the full step-aside + detached driver.
- **Option B — serve the 14B via OVMS** (brief §4): a second listener in BlarAI's trust domain;
  rejected for air-gap purity (brief's own decision).
- **Whole-queue run + tree-kill cancel:** simpler, but cancel would abandon an in-flight task; rejected
  for per-task graceful cancel.
- **Backend-only step-aside (WinUI stays + reconnects):** not viable — the WinUI has no reconnect and
  the 14B is not a separable child. Deferred as the #670 reconnect follow-up.
- **`never -Force`** (an earlier LA instruction): reversed — the brief makes `-Force` mandatory to run
  start-llm non-interactively; our own gate covers the headroom concern that motivated it.

## Amendment 1 — Phase-B run-1 hardening: single-instance guard, venv relaunch, guaranteed step-aside exit (2026-06-22, still DORMANT)

The first on-hardware Phase-B shakedown (the swap fired for the first time) Fail-Closed-exited at the
gateway↔Policy-Agent mTLS handshake (`CERTIFICATE_VERIFY_FAILED`), and the relaunch came up under the
wrong interpreter. Root cause: the swap-relaunch was built and tested as a **single-instance, in-process**
operation, and the live box violated that assumption — four launcher instances were running.

**Root cause is precise — HOST-SIDE multi-instance, NOT the VM.** `provision_per_boot_certs` (ADR-026)
mints a fresh in-memory CA every boot into the **shared `<repo_root>/certs/`** dir (overwriting), and there
was **no single-instance guard**, so the four boots stomped one another's CA — a leaf signed by one boot's
CA presented to a peer trusting another's fails verification. The BlarAI-Orchestrator VM did **not**
contribute: `[guest_parser].enabled=false`, so the VM is not a per-boot-cert consumer and the PA mTLS is
host-side loopback. A cert-resync-to-VM channel would solve a non-problem and was **not** built (revisit
only when guest-parser/VM-mode goes live — there a forced exit's skipped graceful VM-stop would matter).

Three controls, all DORMANT-compatible (the swap still fires only on `[fleet_dispatch].enabled=true` +
`/dispatch approve`):

1. **Single-instance guard** (`launcher/instance_lock.py`; Step 1.4, acquired BEFORE cert provisioning). A
   per-checkout PID-file lock (`certs/launcher.lock`). A second launcher refuses with a novice-actionable
   message — *"BlarAI is already running (PID N) — close that one first."* — and `os._exit(1)` **WITHOUT**
   `_cleanup` (a refused instance acquired/started nothing, and running `_cleanup_vm` (policy=always) would
   stop the LIVE instance's VM). The holder is **confirmed to actually be a launcher** (cmdline runs
   `-m launcher`) before refusing, so a recycled pid after a crash reclaims-as-stale rather than falsely
   refusing. Released in `_cleanup` (graceful); a forced exit leaves it stale for the relaunch to reclaim.
   Worktree-scoped; production-scoped (matches cert provisioning).
2. **venv relaunch** (`shared/fleet/swap_ops.compute_relaunch_argv`). Resolves the checkout's own `.venv`
   interpreter deterministically; `sys.executable` is a last-resort fallback only. Run-1 came up under
   system `Python311` because the relaunch trusted `sys.executable` — whatever started the firing launcher.
3. **Guaranteed step-aside exit** (`launcher/step_aside.py`). The daemon→main `_thread.interrupt_main()`
   may never be delivered if the WinUI native loop is parked (the run-1 wedge), which deadlocks the
   driver's settle (waits on `old_pid` death). A daemon watchdog forces the process down if the graceful
   interrupt+teardown does not complete — **forceful termination is the load-bearing fix; a wider settle
   window only helps a teardown that is slow-but-completes, never a never-delivered interrupt.** A
   `cleanup_started` flag distinguishes the wedge (force at a short grace) from a slow-but-running teardown
   (allow up to a budget, then backstop). A forced exit skips graceful cleanup — the OS reclaims GPU memory
   on process death (**verify at the re-run, do not assume — Arc/Windows GPU-release timing**).

**Lock/relaunch ordering (deadlock-safe):** the relaunch acquires only after the old instance is gone —
graceful → `_cleanup` releases; wedged → the watchdog force-kills the old → its lock goes stale → relaunch
reclaims. The settle (waiting on `old_pid` death) sequences it.

**Testability boundary.** Unit-tested (22 net-new, standing gate green): the guard's acquire /
refuse-live-launcher / reclaim-stale-pid / reclaim-recycled-pid / release; the watchdog's force-decision
over an injected clock; the venv resolution + fallback. **LIVE-ONLY at the re-run:** the forced exit
actually terminating, the GPU actually releasing so the 30B fits, and — still unproven from run-1, which
never reached it — the swap CORE (30B load + FIT + build + 14B swap-back). A/B/C only clear the
cert/instance wall.

**Rejected:** a cert-resync-to-VM channel (VM isn't a cert consumer with guest_parser disabled); a
machine-wide lock (the cert-stomp is per-checkout, so a per-checkout lock matches the scope and preserves
parallel-worktree dev); widening the settle window as the primary fix (cannot wake a never-delivered
interrupt). Builds on ADR-026 (the per-boot cert invariant the guard protects).

## Amendment 2 — Phase-B run-2 swap-core: start-llm pipe-deadlock + GPU handoff (2026-06-22, still DORMANT)

The first run with A/B/C cleared the cert/instance wall (single-instance boot, PA handshake on attempt 1,
dispatch→approve→step-aside→gate→30B load). Then the driver hung at "loading the 30B." The investigation
corrected an initial GPU-OOM hypothesis against the actual logs.

**What the logs showed — NOT a GPU/memory problem.** The OVMS log records the 30B reaching
`state changed to: AVAILABLE` \~30 s after launch with a **zero-byte** error log — a clean GPU load — and
start-llm armed the watchdog sentinel + started the qwen-proxy (it detected READY). So the 30B loaded and
*fit* on the Arc; the box runs it (the operator separately demonstrated the 30B standalone at \~88% system
memory). The hang was the DRIVER not observing it: `dispatch._safe_run` uses
`subprocess.run(capture_output=True)`, and start-llm launches LONG-LIVED grandchildren (OVMS + the proxy)
that inherit the captured stdout/stderr pipe on Windows, so the pipe never reaches EOF and the wait (even
the timeout's own `communicate()`) blocks forever — AFTER start-llm loaded the 30B and exited.

Two fixes, both DORMANT-compatible:

1. **(1) start-llm pipe-deadlock** (`swap_ops._run_to_logfile` + `real_load_30b`). The start-llm launch
   redirects stdout/stderr to a per-run **log file** (kept for diagnosis) with `close_fds` and waits — no
   captured pipe, so a long-lived grandchild can't keep it open. SCOPED: the generic `_safe_run` is
   UNCHANGED for the run-fleet build/test/verify callers, which parse stdout (regression-locked).
2. **(2) GPU handoff — timing luck → guarantee.** Run-2's clean load relied on `os._exit` freeing the
   14B's GPU within OVMS's \~30 s load window (interrupt_main never woke the main thread, confirmed, so the
   graceful `_cleanup`/GPU-unload never ran). (2a) `SharedInferencePipeline.release_gpu_for_exit()` drops
   the 14B for the process-exit path (bypassing `unload()`'s rebuild-closure guard); the step-aside
   watchdog runs it **bounded** before `os._exit` so the 30B loads onto a clean GPU. (2b) the driver polls
   **GPU-free** until it clears the 30B's need before loading (a wait-verify, not a single snapshot;
   abort-to-safe if still busy, proceed if the probe is unavailable). (2c) GPU-free is logged before/after
   the step-aside.

**iGPU probe caveat (LA-accepted).** The Arc 140V is an iGPU — GPU memory is shared system RAM, and the
Windows GPU perf counters under-report OpenVINO/Level-Zero allocations (observed \~0.47 GiB with a 15 GB
model loaded), so there is no reliable discrete-GPU 'budget-free' probe. `real_gpu_free_gb` therefore
reads GPU-free as **system-RAM-free** (the pool the iGPU allocates from, which tracks the 14B's release).
Consequence on this same-pool hardware: the GPU wait-verify (step 8b, ≥15 GiB) sits after the i2 RAM gate
(step 8, ≥21 GiB single-snapshot) reading the SAME pool, so 8b never actually *waits* when 8 passes — 8b
is effectively instrumentation here, and the graceful unload (2a) is the real timing fix. WATCH-ITEM: if
the re-run shows a premature step-8 gate-abort (the 14B's release lagging the snapshot), give step 8 the
same wait-verify (or run 8b's poll before step 8's snapshot). A true GPU-budget probe (Level-Zero sysman /
`xpu-smi`) is a deferred live-validate follow-up.

**Testability.** Unit-tested (14 net-new): the no-capture-pipe launch + parsing-callers-still-capture;
`release_gpu_for_exit` (releases without a rebuild, idempotent); the watchdog runs the unload BOUNDED
before the exit + the bounded-unload timeout; the GPU gate (abort-busy / proceed-clear / proceed-None /
wait-then-proceed). LIVE-ONLY at the re-run: the GPU context actually releasing on `release_gpu_for_exit`,
and — still unproven — the swap CORE (30B BUILD of the task + 14B swap-back), now that the pipe wall is
cleared.

**Rejected:** dropping `capture_output` globally (breaks the run-fleet stdout parsing); a discrete-GPU
budget probe before the re-run (the iGPU doesn't expose it reliably; RAM-free is the right proxy here).
