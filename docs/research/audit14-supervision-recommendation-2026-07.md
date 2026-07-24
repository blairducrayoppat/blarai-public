# AUDIT-14 / #813 — Steady-State Supervision & Auto-Restart: Recommendation

*Research deliverable for LA decision. Read-only research (no build, no config, no runtime change). Dev-side research producing a recommendation about BlarAI **runtime** architecture — so the recommendation itself is held to the runtime rulebook (fail-closed, deny-by-default, defense-in-depth, single Policy-Agent door, structural absence over configuration, no new egress).*

Author: research subagent · Date: 2026-07-17 · Grounded on `main` (launcher/`__main__.py`, `shared/fleet/swap_driver.py`, `services/ui_gateway/src/transport.py`, `services/assistant_orchestrator/src/{entrypoint,substrate,circuit_breaker}.py`, `shared/coordinator/{heartbeat,deadman}.py`, `tools/dispatch_harness/battery.py`, ADR-034/ADR-037, LESSONS 216/221) · Verified against the 2026-07-12 research pass (ticket #813 comment; sub-tickets #865–#868)

---

## 1. Recommendation (bottom line up front)

**Adopt a two-tier, swap-aware, fail-closed supervision model, and answer the "circuit breaker" finding with a health-signal + degraded reply rather than a classical breaker. One genuine LA decision remains: the Tier-2 relaunch *mechanism*.**

- **Tier 1 — a launcher-owned in-process health supervisor + MTTR telemetry (the keystone; #865).** A daemon thread started in `main()`, config-gated, that on a deterministic interval probes AO `:5001` liveness (no model in the path), the shared-pipeline's responsiveness, and a dormant VM/guest vsock seam — *swap-aware* so it never fires during a legitimate silent window — and records every unhealthy→healthy transition so **Mean-Time-To-Recovery (MTTR) becomes a measured number instead of "time until the operator notices."** This alone closes the *measurability* half of the gap at near-zero risk and is the health signal every other limb consumes.
- **Tier 2 — a minimal out-of-process detached relauncher (#868).** The *dominant* real-world failure is whole-launcher death (crash / out-of-memory / unhandled exception / the operator closes the window) — which takes Policy Agent (PA), Assistant Orchestrator (AO), gateway and the resident 14B model down at once. A process cannot restart itself, so this case is **structurally impossible** for Tier 1 to cover and needs a tiny always-on external agent. Closing this case + bounding its MTTR is what actually closes the resilience gap.
- **Resilience #3 is answered by design, not by a new breaker.** `circuit_breaker.py` is correctly a per-request token/recursion cap (OWASP LLM04); a classical open/half-open circuit breaker is the *wrong primitive* for a co-resident (loopback/in-process) backend. Keep it as-is and add a **health-signal + degraded-mode reply** (#866): when the supervisor knows the backend is down or restarting, the gateway returns a clean "the assistant is restarting, one moment" instead of a raw fail-closed error.
- **Reject the Windows Service path.** A Windows service runs in Session 0, which has **no GPU access and no interactive desktop** — BlarAI runs all LLM inference on the Arc 140V iGPU and shows a WinUI window on the operator's desktop, and the launcher self-elevates through a UAC prompt. All three are structurally impossible from Session 0. This is a recommendation to record as a path-not-taken in the supervision ADR, not an LA judgement call.

**The single genuine LA decision** (a real trade-off, not a defect fix): the Tier-2 relaunch *mechanism* — a minimal detached relauncher (recommended) vs. a Windows Scheduled-Task restart vs. a Windows Service (recommend reject). Everything else on this ticket is defect-closing and is yours (the builder's) to decide. A second, smaller decision the LA owns: the **observe-vs-act go-live split** (see §5.7) — the observe-only health/telemetry half is low-risk-live; every *restart action* should merge dormant and wait for an LA-present go-live ceremony.

### Decision table

| Decision | Recommendation | Alternatives weighed | Why | Whose call |
|---|---|---|---|---|
| Overall model | **Two-tier**: in-process supervisor (Tier 1) + out-of-process relauncher (Tier 2) | single in-process tier only; single external tier only | each tier covers a failure class the other *structurally cannot* | LA endorses direction; builder executes |
| Tier-1 supervisor form | Launcher **daemon thread**, config-gated, swap-aware, writes MTTR telemetry | external poller only; asyncio task on the UI loop | cheapest; reuses the live `substrate._idle_monitor_loop` + `deadman.py` liveness-stamp patterns | builder (defect-closing) |
| Tier-1 liveness probe | Reuse `real_backend_ready` + the AoReensurer socket-**and**-mTLS probe; **no model call** | bespoke probe; a real model ping | no-model-in-health-path (ADR-037 §8); catches a cert-orphaned AO | builder |
| Restart policy | Bounded retries + escalating capped backoff + **crash-loop cap → fail-closed** (stop + surface loudly) | infinite blind restart; unbounded retry | matches systemd `StartLimitBurst` / Erlang-OTP restart-intensity; never masks a persistent fault | builder |
| Resilience #3 ("circuit breaker") | **Keep** `circuit_breaker.py`; add health-signal + degraded reply (#866) | add a classical open/half-open breaker for the backend | a co-resident subprocess is not a remote flaky dependency | builder (design settled) |
| **Tier-2 relaunch mechanism** | **Minimal detached relauncher** | Windows Scheduled-Task restart; Windows Service | Scheduled-Task is blind to a clean window-close + a wedge; Service = Session 0 | **⚠ LA DECISION** |
| Windows Service | **Reject** | — | Session 0 has no GPU, no GUI, breaks UAC self-elevation | recommendation; LA ratifies in the ADR |
| Go-live grain | Observe-only half **live**; every restart **action** dormant behind a flag until an LA ceremony | ship the whole thing enabled | auto-restart is a new capability / runtime-behaviour change | **LA (posture)** |

---

## 2. Current-state map — what supervises what today

**Verified on disk.** The 2026-07-12 research pass was accurate; this section confirms it against the code and notes two refinements (marked ⓘ).

**Topology reframe (this is what makes the design non-obvious).** PA + AO + gateway + the resident 14B all run inside **one process** — `python -m launcher`, AO on loopback `:5001` with mTLS. The sealed Hyper-V VM is **dormant/lazy** since #788 (started only for URL-ingest guest parsing or a dispatch guest-oracle run, each behind its own point-of-use guard), so "supervise AO/PA/VM" in normal interactive use reduces to **supervising the launcher's own in-process health**. After the UI launches, the launcher's main thread simply **blocks** on `proc.wait()` (WinUI) or `app.run()` (TUI) — `launcher/__main__.py:814` / `:2268` — with **no supervision loop of any kind**.

| Mechanism | Location | What it actually does | Supervises steady-state AO/PA/VM? |
|---|---|---|---|
| Fleet-dispatch budget watchdog | `shared/fleet/swap_driver.py:396–475` | Daemon thread; tree-kills the **run-fleet coder child** when one headless-coding job exceeds its wall-clock budget. "NEVER force-stops the driver." | **No** — a coding-run watchdog |
| `DoomWatchdog` (stop-doomed-fast) | `shared/fleet/doom_check.py:353–437` | Dooms a stalled coder after 240 s of no progress. Dormant by default. | **No** — coding-run scope |
| Embedding-cache idle unload | `services/assistant_orchestrator/src/substrate.py:953–983` | Daemon thread `substrate-embed-idle-unload`; zeroes the decrypted embedding matrix after 900 s idle. RAM-secret hygiene. | **No** — memory hygiene |
| `swap_driver._restart_with_retry` | `shared/fleet/swap_driver.py:2969–3050` (sole caller `:1526`) | Restarts the AO/14B backend via the `_ops.restart_launcher()` seam, proven ready via `_ops.backend_ready()`. Retries=3, backoff 3 s→×2→cap 30 s, anti-stacking via `_relaunch_in_flight()`. | **No** — reachable **only** inside the 30B→14B swap teardown |
| `AoReensurer` | `tools/dispatch_harness/battery.py:461–574` | Before each battery job: if the AO is down (socket **and** mTLS probe), re-boots the launcher and waits up to 180 s. | **No** — nightly battery only; never wired into any interactive path |
| Gateway boot health gate (ⓘ `#808`, not `#750`) | `services/ui_gateway/src/transport.py:538–618` | One-shot PA `HANDSHAKE_REQUEST` at boot (Step 6a), budgeted 180 s. Short-circuits `if self._connected: return True` (`:561–563`) — **never re-probes**. | **No** — boot-time only; a dead AO after boot surfaces only as per-prompt fail-closed errors |
| C3 coordinator heartbeat (ⓘ running in shadow) | `shared/coordinator/heartbeat.py`; wired `launcher/__main__.py:1157`/`:2180` | Runs the coordinator **self-governance wake cycle** — reads fleet/Kanban board state, composes snapshots, stages redispatch/stall comments. Writes `heartbeat-liveness.json`. | **No** — watches *coordinator work*, not backend processes. Does not probe VM/PA/AO/gateway |
| Dead-man watchdog | `shared/coordinator/deadman.py` | Trips if the heartbeat's own liveness stamp goes stale. | **No** — watches only the heartbeat |
| Step-aside / force-exit watchdog | `launcher/step_aside.py` | Forces `os._exit` if the main thread wedges **during a model-swap teardown**. | **No** — a shutdown watchdog |
| `orphan_guard.py` | `launcher/orphan_guard.py` | Kill-on-close Job Object — children can't outlive the launcher. Does not restart anything. | **No** |
| `instance_lock.py` | `launcher/instance_lock.py` | Single-instance PID lock; **reclaims a stale lock** when the holder PID is not a live `-m launcher`. | **No** — but this is the enabler that makes a Tier-2 relaunch safe (see §3.4) |

**Two refinements to the prior narrative (verified):**
- ⓘ The mTLS boot-handshake health is tagged **`#808`** in code, not `#750`; `#750` is the fix that gave the *AoReensurer* its socket-and-mTLS readiness definition (`battery.py`). The prior comment's "#750 mTLS-health" conflated the two. Both are real; the citation is the only correction.
- ⓘ The heartbeat's docstring says it "ships `false`," but the shipped `services/assistant_orchestrator/config/default.toml` has `heartbeat_enabled = true` + `shadow_mode = true` (flipped at the 2026-07-14 go-live ceremony). So the `heartbeat-liveness.json` + `deadman.py` **dead-man pattern is live precedent in the tree today** — Tier 1 should follow it, not invent a new one.

**Conclusion (confirmed):** nothing performs steady-state health-checking of AO/PA/VM during normal interactive use. Post-boot, the only signals a core service has died are (a) per-prompt fail-closed errors in the gateway, and (b) the next nightly battery job's `AoReensurer` — neither of which recovers an interactive session. MTTR is unbounded and unmeasured. **The gap is real.**

---

## 3. The design

### 3.1 Two failure classes (the design pivots on this split)

1. **Whole-launcher death** — crash, OOM, unhandled exception, or the operator closing the window. PA+AO+gateway+14B all gone at once. **Dominant** real-world case. An in-process supervisor **structurally cannot** self-restart (the same reason the model swap uses a *detached* driver, ADR-034). Requires an **out-of-process** agent → Tier 2.
2. **In-process subsystem wedge** — the `:5001` listener thread dies, or the pipeline hangs, while the process itself lives. Recoverable **in-process** → Tier 1 recovery.

The hard part is **not** the restart (that machinery exists and is battle-tested — `_restart_with_retry`, the AoReensurer, the detached-relaunch path). The hard part is a **deterministic, swap-aware health *decision* that never fires during a legitimate silent window** (lesson 221's window/budget coherence; ADR-037 §8's no-model-in-the-health-path; lesson 216's verify-the-death-don't-infer-it).

### 3.2 Tier 1 — launcher-owned in-process health supervisor + MTTR telemetry (#865, the keystone)

A daemon thread started in `main()` (the `substrate._idle_monitor_loop` shape — `daemon=True`, config-knob-gated), running a steady-state loop that on a deterministic interval probes:

- **AO `:5001` liveness** via the existing `real_backend_ready` stability probe — reusing the **AoReensurer's readiness definition**: socket liveness **AND** a real mTLS handshake, so a *cert-orphaned* AO (socket up, but the leaf no longer verifies against the current CA — the #906/#805 class) is correctly seen as unhealthy. **No model call in this path** (ADR-037 §8): the AO answers `HANDSHAKE_REQUEST`/`HEARTBEAT` on `:5001` even when the model isn't loaded, so a slow cold load is never misread as death.
- **Shared-pipeline responsiveness** — a cheap in-process liveness check (thread-alive / queue-depth style), explicitly **not** a generation.
- **VM/guest vsock frame-probe SEAM** — reuse `launcher.guest_parser_health.make_health_probe`, left as a **no-op slot while the guest is dormant** (do not build VM recovery now; leave the seam so the design is complete when the VM is exercised).

**Swap-aware suppression (the load-bearing correctness property).** The supervisor reads the fleet-swap state file (`state/fleet-swap/current.json`) and **suppresses all verdicts while a swap is non-terminal** — mirroring the #740/lesson 216 leak-detector fix ("a recovery path must verify the death, not infer it from its own start"). Critically, per **lesson 221**, the suppression window must be **bounded**: if the swap state stays non-terminal past the swap's own registered budget, the supervisor stops suppressing and treats it as a real failure — otherwise a hung swap would be masked forever by an unbounded silent window. Identity-plus-liveness (lesson 216): trust the swap driver's stamped pid + process-create-time, not the mere presence of a state file.

**Telemetry (this is half the deliverable).** The supervisor writes a launcher heartbeat + health status (following the `heartbeat-liveness.json`/`deadman.py` precedent) and records **every unhealthy→healthy transition with timestamps** — turning MTTR into a measured number and making Resilience #4 (RTO/RPO/MTTR) reportable. It is also the natural producer for #814's telemetry surface and #878's dashboard (cross-link, don't subsume).

**Fail-safe:** any supervisor error degrades to today's manual posture and **never kills a healthy launcher** (the launcher-test tripwire class from #902 — a supervisor that could tree-kill or `os._exit` a live production launcher is the exact anti-pattern the gate now guards against). This is observe-only and low-risk; it authors the supervision ADR (DECISION_REGISTER same-change rule).

### 3.3 Tier 1 recovery — bounded, swap-aware in-process recovery (#867)

For the in-process wedge, reuse the `swap_driver` seams — `_ops.restart_launcher()` / `_ops.backend_ready()` — and its bounded retry + escalating-backoff + anti-stacking machinery rather than reinventing them. **Open question flagged (§7):** whether the AO daemon thread can be restarted *in place* given the GPU/Level-Zero context and the per-boot mTLS cert material (the #906 stale-cert-across-swap and #805 self-heal-cache classes suggest cert/GPU context is fragile across an in-process restart) — or whether even a subsystem wedge is safest handled by escalating to a full Tier-2 relaunch. This needs live validation before committing to in-place thread restart.

### 3.4 Tier 2 — out-of-process detached relauncher (#868) — ⚠ the LA decision

Covers whole-launcher death. **Recommended shape:** a minimal always-on external agent that reuses the **proven detached-relaunch path** the swap already uses (per #868: `compute_relaunch_argv` + a detached `python -m launcher` on the blessed `shared/procspawn.py` spawn seam — the seam hardened across lessons 219's five scars), driven by a tiny poll loop that reads Tier 1's launcher heartbeat + the fleet-swap `current.json` and **relaunches only when the launcher is confirmed dead AND no swap is in flight**. It reuses `instance_lock`'s stale-reclaim so the relaunch is safe (the dead launcher's lock is reclaimed as stale), and the AO boot reconciler — already wired into `AssistantOrchestratorService.start()` and hardened by lesson 216 — converges the models after relaunch. Fail-safe: if the watchdog itself dies, the posture reverts to today's manual recovery (never worse).

**Why this is a genuine LA decision, not a defect fix:** the *mechanism* is a real trade-off with governance texture (an always-on external process on the operator's box), and the three candidates differ in what they can even detect:

- **(a) Minimal detached relauncher [recommended]** — sees *both* a clean window-close and a wedge (it polls a liveness stamp, not just a process exit code); runs at the operator's integrity in the interactive session where the GPU + GUI live; reuses machinery already proven on this box.
- **(b) Windows Scheduled-Task restart-on-failure** — fires **only on a nonzero task exit**, so it is *blind* to a clean window-close (exit 0) and to an in-process wedge (the process is still alive). Coarse, and awkward to reconcile with the launcher's own UAC self-elevation.
- **(c) Windows Service [recommend REJECT]** — see §4.

### 3.5 Restart policy — the fail-closed core

Whichever tier restarts, the policy is the same and is **fail-closed by construction**: bounded retries with escalating, capped backoff, plus **crash-loop detection** — if more than *N* restarts occur within a *T*-second window, **stop restarting, surface the failure loudly, and stay down until the operator intervenes.** Never an infinite blind restart. This is not a novel invention; it is the settled industry pattern:

- **systemd** `StartLimitBurst` / `StartLimitIntervalSec`: after *burst* restarts within the interval, systemd **stops trying and leaves the unit failed** until manual restart. ([systemd restart policies](https://dohost.us/index.php/2025/10/27/implementing-service-recovery-and-restart-policies-in-systemd/))
- **Erlang/OTP supervisors** `intensity`/`period`: if more than `MaxR` restarts happen within `MaxT` seconds, the supervisor **terminates rather than loop forever** — the docs explicitly warn that `intensity=10, period=1` produces an "up to 10 restarts per second, forever, filling your logs until someone intervenes" anti-pattern. ([OTP supervisor behaviour](https://www.erlang.org/doc/system/sup_princ.html)) That anti-pattern *is* the fail-open this design must avoid.

Concretely for a single-operator appliance: a small burst tolerance (survive a transient) with a window long enough that a persistent fault trips the cap fast and hands off to the human — never a supervisor that hides a broken or tampered binary by relaunching it forever. A supervisor that **cannot verify** the component came up healthy (`backend_ready` + mTLS probe both green) treats the attempt as *not recovered* and counts it against the crash-loop budget.

### 3.6 Degraded-mode reply (#866) — answers Resilience #3

Instead of a classical dependency breaker, wire the supervisor's health signal into the gateway so a prompt arriving while the backend is down/recovering gets a clean **degraded-mode reply** ("the assistant is restarting, one moment") rather than a raw fail-closed stack error. This is the right primitive for a co-resident backend and directly closes the "`CircuitBreaker` is misnamed / there is no dependency breaker" audit finding — by design, not by adding a second breaker. `circuit_breaker.py` stays exactly as it is (a correctly-scoped OWASP LLM04 per-request cap).

---

## 4. Alternatives / paths-not-taken

- **Windows Service (Tier-2 mechanism) — REJECT.** A service runs in **Session 0**, which "doesn't have access to the GPU… prevents any and all GPU applications via CUDA, OpenCL… from running as a Windows service," and "user interfaces in Session 0 are not supported." ([Session 0 isolation](https://learn.microsoft.com/en-us/answers/questions/27517/is-there-any-workaround-in-win10-to-allow-service), [GPU-as-a-service impact](https://de.scribd.com/doc/58343489/Windows-Session-0-Isolation-Impact-on-GPU-as-Service)) BlarAI runs *all* inference on the Arc 140V iGPU and shows a WinUI window on the operator's desktop; the launcher self-elevates via UAC. A service would have to spawn the real launcher into the user session via `CreateProcessAsUser` anyway — i.e. it would *become* option (a) with a Session-0 shell wrapped around it, adding a service-install/permission surface for no benefit. (A third-party wrapper like NSSM has the identical Session-0 problem plus a new external dependency.)
- **Windows Scheduled-Task restart (Tier-2 mechanism) — not recommended.** Blind to a clean window-close and to a wedge; see §3.4(b). Retained as a documented alternative because it needs no long-lived companion process.
- **Single-tier only — rejected.** In-process-only leaves the dominant case (whole-launcher death) uncovered; external-only misses the cheap, near-zero-risk measurability win and the fast in-process recovery of a subsystem wedge.
- **Classical open/half-open circuit breaker for the backend — rejected.** Wrong primitive for a loopback/in-process co-resident; §3.6.
- **In-place AO-thread restart vs. escalate-to-relaunch for a wedge — open** (§3.3, §7); recommend prototyping the in-place path but keeping full relaunch as the fail-closed fallback.

---

## 5. Security analysis (held to the runtime rulebook)

The supervisor is a new steady-state actor on the trust spine; it must strengthen the posture, never open a door. Mapping to the security-by-design principles:

1. **Fail-closed (P1).** Crash-loop cap → stop + surface, never infinite restart. A supervisor that cannot verify health treats the component as *not recovered*. The swap-suppression window is itself bounded (lesson 221) so a hung swap is never masked forever.
2. **Deny-by-default (P2).** The supervisor watches an **explicit allowlist** of components (AO, PA, pipeline, and a dormant VM seam) — it does not "restart whatever looks wrong."
3. **Defense-in-depth (P3).** It adds a lock (auto-recovery) *behind* the existing ones (boot gate, instance-lock, orphan-guard); it removes none. A restarted component still comes up through every boot gate.
4. **Structural absence over configuration (P4) + self-governance mirror.** This is the crucial one: the supervisor **observes and restarts but has zero authority over the governed core.** A "restart" is *re-invoking the full launcher boot path*, which re-runs PA measured boot + per-boot mTLS provisioning + signed-manifest verification. There is deliberately **no side-door that starts AO/PA directly** bypassing those gates — the supervisor has no code path to the policy core, exactly mirroring the 2026-07-11 self-governance boundary (BlarAI has zero write path to its own governed core; its self-directed output is advisory-only). Structural severance, not vigilance.
5. **Single adjudication door (P5).** The supervisor never adjudicates and never bypasses the Policy Agent; a restarted AO/PA re-enters through the same one door. No second adjudicator, no bypass.
6. **No new egress.** Purely local: loopback health probes, local-filesystem liveness stamps, local process spawn. No network client is introduced (would be a decision_boundary escalation — it is not needed).
7. **Fail-loud (P11).** Supervisor state (restart counts, MTTR, last failure, suppression-window status) is logged and is the natural #878 dashboard / #814 telemetry surface. A silently-degraded supervisor is a defect.
8. **Every control tested off (P12).** Ships with a **kill-the-AO-thread test** proving the supervisor detects + restarts, **and** a **toggle-test** proving detection *fails* when the supervisor is disabled — so "supervised" is distinguishable from "the test can't reach it." Plus a negative control: a legitimate swap window must **not** trip a restart.
9. **The supervisor must not kill/be killed by the live system (test-governance).** Given the #902 launcher-test history (a test's boot-reconcile tree-killed a live dispatch; an `os._exit` silently killed the gate), the supervisor's own restart action must be pid-and-create-time-confirmed against a real `-m launcher` (lesson 216 identity+liveness) before it touches anything.

### 5.7 Irreversibility / go-live grain (LA posture call)

Auto-restart changes BlarAI's runtime behaviour, so it is capability-adjacent. Recommended split, mirroring the heartbeat's own shadow→graduation model:

- **Observe-only half (Tier-1 health probes + MTTR telemetry, #865) — low-risk-live.** It only reads and logs; it changes no behaviour, exactly like the heartbeat running in shadow today. This can ship enabled.
- **Every restart *action* (Tier-1 recovery #867, Tier-2 relaunch #868) — merge dormant behind a config flag and wait for an LA-present go-live ceremony.** First autonomous restart of a governed component is a posture flip (principle 13: irreversible = ceremony).

---

## 6. Integration with existing signals (don't duplicate)

- **#808 boot handshake** — reuse the *probe* (`check_pa_status`/`real_backend_ready`), not the boot gate; the supervisor is the missing *steady-state* re-check the boot gate deliberately short-circuits away.
- **#855 heartbeat + `deadman.py`** — reuse the **liveness-stamp + dead-man *pattern*** (it is live precedent), but do **not** overload the coordinator heartbeat: it watches board/fleet *work*, not backend processes, and folding backend health into it would blur the self-governance boundary. Cross-link, don't subsume.
- **AoReensurer** — **generalize** its socket-and-mTLS readiness definition from battery-only into the interactive supervisor; it is the closest existing thing to an AO liveness+restart supervisor and its readiness predicate is already correct.
- **#878 operations dashboard** — supervision state (up/down, restart count, MTTR, current suppression window) is a natural first-class dashboard surface. Cross-link.
- **#814 in-runtime telemetry** — the supervisor's health/restart events are a producer for that layer; cross-link, don't subsume (both #865 and #814 note this).

---

## 7. Residual unknowns — what needs measuring / prototyping

1. **Real cold-relaunch MTTR** (14B load; the AoReensurer budgets 180 s) — measure it on the box to set the crash-loop window sensibly (lesson 221: window must exceed the longest legitimate silent phase).
2. **False-positive rate of the health probe during legitimate swap windows** — prototype the swap-phase suppression and verify on the real box that it *never* fires mid-swap, and that the bounded-suppression backstop *does* fire on a genuinely hung swap.
3. **Can the AO daemon thread restart in-place?** — given GPU/Level-Zero context + per-boot mTLS cert material (#906/#805 fragility). If not clean, even a subsystem wedge escalates to a full relaunch. Live-validate before committing to in-place restart.
4. **Tier-2 relauncher behaviour across the launcher's UAC self-elevation** — the launcher elevates; measure whether the relauncher must itself run elevated or can hand off the elevation hop.
5. **Crash-loop threshold tuning (N/T)** — needs the real crash-mode distribution; start conservative and refine from Tier-1's own MTTR telemetry once it exists.
6. **The cheap "pipeline responsiveness" probe** — define a no-model liveness signal for the shared pipeline (thread-alive + a bounded internal queue check) that is meaningful without a generation.

---

## 8. Sub-ticket cross-reference & sequencing

The 2026-07-12 pass already filed the limbs (project 3); this recommendation endorses them with the refinements above:

- **#865 [RESILIENCE-T1]** — launcher health supervisor + MTTR telemetry (keystone; observe-only, low-risk-live). **Sequence: FIRST.**
- **#866 [RESILIENCE-T2]** — degraded-mode reply (answers Resilience #3).
- **#867 [RESILIENCE-T3]** — bounded swap-aware in-process recovery (Tier-1 action; dormant until ceremony).
- **#868 [RESILIENCE-T4]** — out-of-process relauncher (Tier-2, the dominant case; dormant until ceremony) — **carries the one genuine LA decision: the relaunch mechanism.**

Sequence: **T1 → T2 → {T3, T4}.** T1+T4 are the pair that actually closes the resilience gap. **#813 stays open as the research home.** The LA prioritizes T1–T4, decides the T4 mechanism, and makes the observe-vs-act go-live call (§5.7).
