# C3 — The Heartbeat: Implementation Design (#845)

**Status:** DRAFT — authored 2026-07-14 for the LA design checkpoint (the LA chose the
checkpoint-first path on 2026-07-13: design doc → LA approval → build; no C3 code exists or
is authorized by this document until that approval).
**Doctrine:** ADR-039 (esp. §2.10 C3, §2.13 items 1–2, §2.14.1, §2.14.2, §2.14.4–2.14.6,
§2.12 items 5/6/7/9/12); program plan `docs/research/coordinator-program-plan-2026-07.md`
(design SSOT). **Ticket:** #845 (scope + acceptance shape). **Shadow gate:** #855.
**Substrate:** the merged C0–C2 chain — seven C2 units (the increment-1 decision core plus
six increment-2 limbs; complete ledger at #844 c.1877), every piece dormant behind
`[coordinator]` flags, all `false` on disk in
`services/assistant_orchestrator/config/default.toml` (§7 below lists the keys this design
adds).
**Author:** interactive Claude session (this doc).
**Review:** independently adversarially reviewed 2026-07-14 (read-only verifier agent,
author ≠ verifier) — verdict CHECKPOINT-READY-WITH-FIXES; all findings (5 major, 5 minor,
4 nits) applied to this revision before the checkpoint. The majors, for the record: the
mode ladder's swap-read-`UNREACHABLE` fail-open (fixed, §1); machinery-health alarms
shadow-routed into an unread journal (fixed — health is never shadow-gated, §6.2/§7.2);
a fixed dead-man threshold false-alarming across battery cadence (fixed — the stamp
carries its own deadline, §6.1); the age mechanism's read-inject-before-compose ordering
left implicit (fixed, §2/§4.3); drafting's lock-acquired ≠ 14B-resident conflation vs the
image-generation eviction path (fixed — positive residency required, never a reload,
§3.4).

---

## 0. What this document settles

| # | Open item | Settled where | Doctrine anchor |
|---|---|---|---|
| 1 | The flow-metric **"age" definition** + its timestamp source — the ADR's most load-bearing open item | §4 | ADR-039 §2.14.2, §5.1 |
| 2 | The timer's **exact launcher integration point** + failure isolation (a coordinator fault must never degrade chat) | §3 | §2.13.1; #845 threat model |
| 3 | The wake cycle's **composition order** over the C2 pieces | §2 | §2.10 C3, §2.14.5 |
| 4 | How the cycle sources the **trusted `repo_id`** for `stage_redispatch_proposals` + the #844 c.1876 defensive-wrap caller obligation | §5 | §2.2 control 1 (CaMeL) |
| 5 | The **dead-man liveness check's home** (outside the heartbeat) | §6 | §2.14.1 |
| 6 | The **#855 shadow-journal seam** | §7 | §2.12.7, §2.13.2 |
| 7 | The **digest surface** | §7.4 | §2.10 C3; §2.12.13 |
| 8 | **Quiet-queue tripwire** (tri-state-aware), **operator-absence mode**, **power/thermal-aware cadence** — each explicit, none implicit in "cycle order" | §8 | §2.12 items 6/9/12; §2.9 |
| 9 | The build's **limb decomposition** (C2's limb-flow shape, for LA affirmation) | §11 | — |

Everything here composes already-merged, already-reviewed substrate; §9 names the only three
genuinely new primitives (verified absent from the tree, not assumed): a runtime battery
probe, a runtime-readable overnight window, and a persisted heartbeat liveness stamp.

---

## 1. The shape in one paragraph, and the mode ladder

The heartbeat is a bounded, deterministic-FIRST wake cycle on an in-process,
launcher-managed timer (ADR-039 §2.13.1 — no new Windows Scheduled Task; the elevated 23:00
task remains the only app-not-running wake path). Each cycle: read the composed work-state
snapshot → maintain the bucket-transition record (the §4 age mechanism) → harvest the
latest run → drive board moves / stall comments / redispatch staging through the merged C2
pieces → evaluate the quiet-queue tripwire → (only when safe) invoke the 14B for bounded
single-decision drafting → emit at most one digest → write the liveness stamp. READ +
PROPOSE only: every state-changing intent lands in the born-encrypted proposal store behind
operator approval; the model is invoked only to draft, never to act (§2.11, §2.14.5).

**The mode ladder** — resolved fresh at the top of every cycle by pure code over probes:

| Mode | Condition (any ⇒ at most this mode) | What runs |
|---|---|---|
| `FULL` | 14B resident (no swap in flight), on AC power, outside the overnight window | Everything, incl. model drafting + digest prose |
| `DETERMINISTIC-ONLY` | swap in flight (`WorkStateSnapshot.swap_in_flight`, `shared/fleet/work_state.py:397-398` over `swap_state.is_in_flight`, `swap_state.py:55-63`); **or the swap-state read itself is `UNREACHABLE`** (unknown ≠ idle: an unreadable swap state is treated as a possible in-flight swap, never as clearance to draft — the same conservative direction as the battery probe); **or** on battery / power state undeterminable; **or** inside the overnight window | All deterministic steps; model drafting deferred to a later cycle (never queued) |
| `SKIP` | `_cleanup_started` observed, or the previous cycle is somehow still running (single-flight guard) | Nothing but the liveness stamp note |

The cycle **never forces a swap, never loads a model, never waits for the pipeline**
(ADR-039 §2.10 C3, review F8): drafting happens only against an already-resident, currently
idle 14B (§3.4), and a deferral is a normal outcome recorded in the cycle result, not an
error.

---

## 2. The wake cycle — composition order over the C2 substrate

One cycle, in order. Every step is fail-soft toward the cycle (a step failure is recorded
and the cycle proceeds or ends cleanly — never crashes the thread, §3.3); targeting checks
inside steps stay fail-closed (a refused target refuses that action, §5).

1. **Mode resolution** (pure; §1 ladder) from: the swap tri-state read, the battery probe
   (§8.3), the overnight-window config (§8.3), and the teardown flag. Result pins the
   cycle's mode and the *next* interval (battery multiplier).
2. **Store reconcile / TTL sweep** — `ProposalStore.expire_stale(now)`
   (`proposal_store.py:500`; idempotent; STAGED past TTL → DRAFT with a note, §2.12.5),
   **skipped while operator-absence is active** (§8.2 — TTLs pause). `reconcile_at_boot`
   runs once at heartbeat construction, not per cycle.
3. **Read the transition record, then compose the snapshot** — the prior cycle's
   bucket-transition record (§4.3) is read FIRST, and the composer extension injects each
   task's observed entered-bucket timestamp as a synthetic field, so the per-project flow
   metrics and `detect_stalls` inside `compose_work_state(...)` (`work_state.py:372-456`)
   compute on the OBSERVED age basis in the same pass (today's composer defaults to the
   `created` basis with no basis parameter, `work_state.py:403-410` — extending it is limb
   1). The snapshot covers: swap WAL, fleet queue, latest run SUMMARY outcomes,
   battery-campaign file, per-project board + summary + flow + stalls, Vikunja liveness,
   stall seen-set, ACP progress. Every read tri-state (`OK/EMPTY/UNREACHABLE`, §2.12.6) —
   an `UNREACHABLE` substrate is a surfaced condition on the snapshot, never "no data."
4. **Bucket-transition record update** — AFTER compose: pure diff of each project's fresh
   bucket membership against the persisted record; first-seen timestamps recorded,
   departed entries pruned (episode semantics). A card first observed this cycle therefore
   contributes no observed age until the next cycle — the §4.4 observation lag, stated
   rather than hidden.
5. **Harvest the latest run → board movement** — for the latest run's structured facts,
   `coord_lifecycle.resolve_board_transition(...)` (`coord_lifecycle.py:167-197`; Done
   requires `oracle_passed AND merged` — the forged-Done lock is upstream and untouched) →
   `vikunja_bridge.move_job_card(...)` (`vikunja_bridge.py:1052-1109`, fail-soft, names
   resolved never hardcoded) through the **output router** (§7.2 — live vs shadow).
6. **Stall pass** — the snapshot already carries per-project `detect_stalls` output
   (per-class aging outliers, `coord_lifecycle.py:320-366`, now on the observed age basis);
   `run_stall_cycle(current_stalls, seen_path=…, post_comment=<routed sink>, now=…)`
   (`coord_stall_monitor.py:101-150`) enforces one comment per NEW stall episode; a failed
   post is not persisted and retries next cycle by construction.
7. **Redispatch staging** — `stage_redispatch_proposals(outcomes, run_id=…, repo_id=…,
   projects_dir=…, roots=…, store=…)` (`coord_redispatch.py:267-432`), with the trusted
   `repo_id` sourced per §5 and **the whole invocation wrapped defensively** (the #844
   c.1876 caller obligation): any exception is caught, recorded on the cycle result, and
   the cycle proceeds — because no proposal was written, the same evidence retries next
   cycle (the module's own fail-soft contract). **Promotion, named:** the C2 stager only
   ever writes DRAFTs (`add_draft`, `coord_redispatch.py:390`); in live mode
   (post-graduation) this step then promotes fresh heartbeat-originated DRAFTs to STAGED
   (`mark_staged`, `proposal_store.py:462`) — STAGED is what surfaces and what the TTL
   clock runs on. In shadow mode proposals stay DRAFT (§7.2), so the TTL-expiry and
   absence-pause machinery (step 2, §8.2) is live-inert until graduation, by design — its
   locks are tested against directly-staged fixtures.
8. **Quiet-queue tripwire** (pure; §8.1) over the snapshot — suppressed on any
   `UNREACHABLE` consulted substrate ("PM substrate unreachable" surfaces instead), during
   swaps, inside the overnight window, and within the post-boot idle-grace.
9. **Model drafting** (`FULL` mode only; §3.4) — bounded single-decision calls (§2.11,
   §2.15): summarize the one finished run; render one detected condition's proposal in
   plain language. Grammar fail-soft (#743 pattern); **no correctness ever depends on the
   model path** — every draft has a deterministic fallback rendering (facts without prose).
10. **Digest** — at most ONE per cycle (§7.4): deterministic skeleton (queue depth, flow
    deltas, stalls flagged/new, gated/unreachable conditions, proposals pending) plus the
    step-9 prose when available; routed to the shadow journal until #855 graduation; never
    a Vikunja comment (§2.10 C3 invariant). Absence mode filters/accumulates per §8.2.
11. **Liveness stamp + cycle telemetry** — `heartbeat-liveness.json` (§6.1): started/
    completed timestamps, mode, per-step results (incl. deferrals and surfaced
    conditions). Written atomically; this stamp is what the dead-man reads.

The composer-only sensory rule (§2.14.5) holds throughout: deterministic code composes
every model-call context from exactly the three defined legs (policy = `CoordinatorConfig`
plus, once control 7 ships, the signed policy file — until then the compiled-in
governed-core defaults are authoritative, per the §2.17 claim discipline; state = the
`work_state` composer; work = the paginated `vikunja_bridge` reads). The model never
navigates to a fourth source.

**Crash convergence (acceptance: forced-crash-mid-cycle converges clean):** every
persistent write in the cycle is single-artifact atomic (temp + `os.replace`, the
`coord_stall_state.py:134-140` `_atomic_write` pattern) or a single-row SQLite commit (the
store). A crash
between any two steps leaves: no duplicate stall comment (the seen-set persists only on
successful post), no duplicate proposal (store fingerprint dedup, `add_draft` idempotency,
`proposal_store.py:408`), no duplicate board move (moving to the current bucket is a
no-op), and a stale liveness stamp — which is exactly what the dead-man (§6) and the boot
reconcile exist to notice.

---

## 3. Timer integration — the launcher seam, and the four isolation walls

### 3.1 Where it lives (facts from the tree, not assumption)

The launcher (`launcher/__main__.py`, `main()` at `:1298`) has **no event loop and no
timer machinery**: after boot it blocks in the UI surface (TUI `app.run()` `:2164`; WinUI
`proc.wait()` `:814`), and the only in-repo long-lived-thread template is the step-aside
watchdog (`launcher/step_aside.py:147-164` — a named `daemon=True` thread with an injected
clock/sleep for testability). The heartbeat is therefore a **named daemon thread**
(`blarai-coord-heartbeat`) owned by the launcher, started immediately before the UI
surface blocks (after the Step-6b prompt-flow preflight, so a heartbeat can never delay or
fail boot), and stopped **first** in `_cleanup()` (`:1153`) — before services stop, so a
mid-cycle action can never race teardown. Belt and suspenders: the cycle loop also
observes `_cleanup_started` (`:1063`) and the thread is a daemon, so it can never hold the
process open — the timer *dies with the app*, which is the §2.13.1 fail-safe property that
motivated the in-process choice over a Scheduled Task.

### 3.2 Construction gating — the C2 dormancy precedent, reused exactly

C2 already wired coordinator code into a live path (the swap driver) while staying
dormant, and that pattern is regression-proven; the timer reuses it verbatim rather than
inventing a new dormancy idiom:

| Element | C2 doom watchdog (precedent) | C3 heartbeat (this design) |
|---|---|---|
| Default-off injection | `SwapDriver(..., doom_watchdog=None)` (`swap_driver.py:1251`) | `main()` holds `heartbeat=None` unless built |
| Factory returns `None` when the key is absent/false | `build_doom_watchdog` (`swap_ops.py:3343-3385`) | `build_heartbeat(...)` returns `None` unless `heartbeat_enabled` is true — **no object, no thread, no store handle, nothing constructed** |
| Lazy import (OFF path never imports the machinery) | TYPE_CHECKING-only import (`swap_driver.py:34-35`) | the factory imports the cycle module inside itself |
| Byte-identical-when-off locks | absent-key→None `test_doom_check.py:456`; false-key→None `:459`; ON-builds-with-registered-grace `:463`; OFF-is-byte-identical `:544` | same four lock shapes: absent-key→None, false-key→None, ON-builds-with-registered-interval, OFF-boot byte-identical |
| Go-live flip | TOML + spec-writer threading | TOML flip only (the plumbing below ships with C3, dormant) |

**A plumbing gap the recon verified:** `[coordinator].heartbeat_enabled` is parsed into
`CoordinatorConfig` (`shared/coordinator/config.py:157`) but is surfaced to **no
consumer** — the launcher currently sees only `coordinator_enabled`,
`coordinator_projects`, and `coordinator_battery_campaign_state_path` via AO properties
(`entrypoint.py:1002-1041`) threaded at `__main__.py:1959-1963`. C3 adds
`coordinator_heartbeat_enabled` (and the §7/§8 keys) as sibling AO properties — the same
one-source-of-truth path, no second TOML read in the launcher. Note this is a stricter
gate than C1's: C1 constructs `CoordCoordinator` unconditionally and checks the flag
inside `handle_command` (`coord_coordinator.py:113`) — correct for a read-only
command object, but the heartbeat is a *thread with side-effect sinks*, so it gets
**structural absence** (ADR-039 principle 4): flag false ⇒ the thread does not exist.

### 3.3 Failure isolation — the walls between a heartbeat fault and chat

1. **Thread wall.** The chat path never calls heartbeat code; the heartbeat never calls
   into the gateway/UI. Shared surfaces are files (atomic), the store (WAL SQLite), the
   loopback bridge (2 s cap, fail-soft), and the drafting seam (wall 4).
2. **Cycle wall.** The entire cycle body runs under a catch-all; an exception marks the
   cycle failed in the stamp and waits for the next tick. Per-step wraps (§2) keep one
   step's fault from starving the rest.
3. **Thread-death wall (fail-loud, principle 11).** An escape past the cycle wall is
   caught by the thread's outer handler: logged at ERROR, written into the liveness stamp
   as `thread_dead=true` — which the dead-man watchdog (§6) then surfaces. A silent
   heartbeat death is structurally impossible to miss twice.
4. **Inference wall.** Model drafting acquires the AO's single-flight inference seam
   **non-blocking** (try-acquire): if a chat turn (or anything) holds it, drafting is
   deferred to a later cycle. The heartbeat never waits on, never queues behind, and never
   preempts a chat generation; deterministic steps never touch the pipeline at all. The
   concrete acquire point is the drafting limb's first build task, against the AO's
   existing serialization (a bounded `coordinator_draft()` entry on the AO service object
   the launcher already holds — no conversational round-trip, per §2.13.7).

Import safety inherits the launcher's hardest-won lesson: no module-scope side effects, no
module-scope `atexit` (the #783 incident and its child-interpreter locks,
`launcher/tests/test_import_side_effects.py`; registration-in-`main()` at
`__main__.py:1311`). The heartbeat module ships with the same bare-import lock.

### 3.4 Never forcing the model

"14B resident" is not a stored fact anywhere (recon §1: `swap_state` only answers "is a
swap mid-flight"), and **acquiring the generation lock is not evidence of residency** —
the shared-pipeline lock serializes concurrency, while the UC-010 image-generation path
can evict the 14B and later release the lock with the model absent. Drafting eligibility
is therefore computed conservatively, in order: the swap read is `OK` and no swap is in
flight (an `UNREACHABLE` read already forced deterministic-only at the ladder) AND the AO
service is up AND the AO reports the 14B pipeline **positively resident** (the same
eviction bookkeeping the image-generation big jobs use — the exact accessor is the
drafting limb's first build task) AND the try-acquire succeeds. `coordinator_draft()`
returns a tri-state (`drafted` / `busy` / `not_resident`) and **must never initiate a
load, a reload, an eviction, or a swap** — a non-resident 14B is a defer, exactly like a
busy one. Mid-swap cycles are deterministic-only by the mode ladder before this check is
even reached (acceptance lock: a mid-swap cycle provably makes zero model calls; a
companion lock proves a `not_resident` report triggers no load).

---

## 4. The age decision (ADR-039 §2.14.2) — SETTLED

### 4.1 The decision

**Age = time since the card entered its current bucket, operationalized as
first-observed-in-bucket by the heartbeat's snapshot-diff; for pull fairness the
load-bearing case is entered-Ready.** Ties inside one observation batch break by Vikunja
`created` (older first). This is the ADR's "entered-Ready" option, chosen over
"ticket-created," with the observation mechanism the ADR's first-named candidate
(heartbeat snapshot-diffing).

### 4.2 Why entered-Ready over created (both options on the record, per §2.14.2)

- **FIFO fairness (the pull policy's spine, §2.8/§2.12.8):** under a created basis, a
  ticket refined in Backlog for three weeks enters Ready with three weeks of "age" and
  jumps every card that was genuinely waiting — backlog dwell is not queue wait, and
  Standard-class FIFO is only fair at the Ready boundary.
- **Aging-WIP honesty (stall detection):** under a created basis, two cards pulled into
  In Progress the same day carry ages that differ by their backlog history — the older
  creation gets falsely flagged an outlier while a genuinely stuck newer card hides under
  the inflated class mean. Stage-relative age measures the thing `detect_stalls` claims to
  measure.
- **Coherent gated-age semantics (§2.9, already locked):** a resource-gated card *stays in
  Ready* and its age must accrue through the gate so a released card catches up. With an
  entered-Ready basis that sentence is exact; with a created basis it is vacuously true and
  carries no information.
- What created has going for it — zero infrastructure, survives everything, already
  shipped — is preserved anyway: it remains the tie-break and the surfaced fallback (§4.4),
  and C1 built the swap seam for exactly this move (`flow_metrics.DEFAULT_AGE_BASIS_FIELD`
  is an explicit, swappable parameter, `flow_metrics.py:39`; the module docstring
  anticipates this decision verbatim).

### 4.3 The mechanism

A **bucket-transition record**: per configured project, per task, per bucket, the first
cycle-timestamp at which the heartbeat observed the card in that bucket. Maintained by pure
diff code each cycle (step 4): newly observed (task, bucket) pairs are recorded; pairs
whose card left the bucket are pruned — **episode semantics**, exactly like the stall
seen-set (a card that bounces back to Ready starts a fresh wait; its serviced wait is not
credited forward). Storage posture: task ids, bucket titles, timestamps — non-content-
bearing coordinator runtime metadata ⇒ **plaintext, owner-DACL, atomic write**, the
LA-affirmed `coord_stall_state.py` posture and code pattern (`:78-143`), in the same
coordinator state dir. Consumption, with the data flow explicit (it matters): each cycle
reads the PRIOR record, injects the observed timestamp as a synthetic field on each task
mapping, and passes `age_basis_field` pointing at it into the compose pass —
`flow_metrics` itself does not change (`compute_age` reads `task[basis_field]`,
`flow_metrics.py:86-116`); the record is diffed and re-written only AFTER compose (§2
steps 3–4), so a card first observed this cycle contributes no observed age until the
next. `detect_stalls` and the flow ages switch basis in the same limb so the definition is
**single and consistently applied** from the first enabled cycle.

### 4.4 Honest biases and the fallback (named, not papered over)

- **Observation lag:** entered-bucket is observed no finer than the cycle interval. At a
  15-minute cadence this is noise against hours-to-days queue waits (the §2.8 timescale).
- **App-off windows:** cards that moved while the app was off are first-observed on the
  next boot's first cycle — one collapsed batch, relative order restored by the `created`
  tie-break. Bounded, honest, and conservative (a late observation under-counts age; a
  card is never unfairly *promoted* by the gap).
- **Cold start / pre-enablement history:** at the first enabled cycle every existing card
  is "first observed" — age ordering degenerates to exactly today's created ordering and
  converges from there. Shadow mode (§7) runs this convergence for free before any live
  output depends on it.
- **Record unreachable/corrupt:** tri-state discipline (§2.12.6/§2.14.4) — the cycle falls
  back to the created basis **with the condition surfaced on the snapshot and digest**,
  never silently (`UNKNOWN` never renders as fresh data).
- **The fallback is per-project, and C4 must inherit that explicitly:** a project whose
  record is degraded joins any cross-project ordering on the created basis while the
  others use the observed basis — a mixed-basis snapshot. Harmless for C3 (no global pull
  exists), but C4's global class-then-age pull (§2.12.8) must treat mixed basis as a
  surfaced degraded state, not silently commensurable numbers. Recorded here so C4
  inherits the rule rather than the accident.

### 4.5 Rejected (on the record)

- **Created as the standing definition** — §4.2; it survives as tie-break + fallback only.
- **Coordinator-journaled own moves as the mechanism** — the coordinator's own
  `move_job_card` calls are a minority of board movement (the operator's webUI edits and
  the MCP server move cards too); a self-journal misses most transitions. Own-move
  journaling is a *precision refinement* to the same record (exact timestamps for the
  moves the coordinator itself makes) — a named residual, not required for correctness.
- **Polling a Vikunja audit/history API** — none exists on v2.3.0 (§2.14.2's premise).

---

## 5. The trusted `repo_id`, and the defensive wrap (CaMeL, §2.2 control 1)

`stage_redispatch_proposals` declares its provenance contract: *`run_id` and `repo_id` are
TRUSTED, from the run/dispatch record; the caller owns that provenance*
(`coord_redispatch.py:282`). The heartbeat honors it as follows:

- **Source:** the run's own structured dispatch record — the queue/task record's `repo`
  field, written by the trusted dispatch path at enqueue time and validated against
  `projects_dir` at dispatch (`swap_ops.py:3298`, `:3606`), persisted per-run alongside the
  acceptance record (`read_acceptance_record`, `swap_ops.py:3290-3291`). The build limb
  pins the exact accessor (queue entry vs per-run record) — the **rule** settled here is
  the load-bearing part: the target selector comes from a dispatch-written structured
  field, **never** from `SUMMARY.txt`, task names, RESULT lines, or any other run-report
  text (which remain free to shape proposal *wording* only).
- **No structured record ⇒ no staging:** if no dispatch-written `repo` resolves for the
  harvested run, the cycle skips redispatch staging for that run and surfaces the
  condition — fail-closed for targeting, fail-soft for the cycle. It never "recovers" a
  repo id from text.
- **The ruler still rules:** the sourced `repo_id` passes `derive_workspace_target` +
  `check_target(phase="STAGING")` inside the C2 module regardless — the trusted source is
  defense-in-depth on top of the SG ruler, not a substitute for it.
- **The c.1876 obligation, discharged:** the heartbeat wraps the **entire**
  `stage_redispatch_proposals` invocation in a catch-all (cycle step 7); a raise is
  recorded and retried naturally next cycle (no proposal was written).
- **The execution seam, explicitly not wired:** `revalidate_for_execution`
  (`coord_redispatch.py:440-479`) remains the standing obligation on whatever future hook
  executes an approved redispatch (`phase="EXECUTION"`, TOCTOU closure, §2.12.4). C3 does
  not build that hook (§10.3): at C3, approval records a disposition; acting on it remains
  the operator's explicit `/dispatch`.

---

## 6. Dead-man liveness (§2.14.1) — SETTLED

The §2.14.1 premise: every alarm C2–C4 can raise is computed *by* the cycle, so a wedged
or dead heartbeat silences its own alarm, and operator noticing is vigilance, which is
disallowed. Recon confirmed no launcher-written liveness artifact exists today — the stamp
below is a new primitive.

1. **The stamp (written by the heartbeat, read by everyone else):**
   `heartbeat-liveness.json` in the coordinator state dir — `started_at`, `completed_at`,
   mode, per-step results, `thread_dead` (§3.3), and the cycle's **own declaration of when
   the next beat is due**: `next_interval_s` + `next_expected_by` (computed from the mode
   ladder's chosen interval, so battery/overnight cadence stretching travels inside the
   stamp). Atomic, plaintext (non-content-bearing), owner-DACL.
2. **The launcher dead-man watchdog (the check OUTSIDE the heartbeat):** a second,
   independent daemon thread whose entire job is one comparison — `now >
   next_expected_by + slack` (fixed registered slack, §9). Because the stamp carries its
   own deadline, the watchdog needs no knowledge of intervals or modes and **cannot
   false-alarm across cadence changes** — a battery-stretched cycle declares its longer
   deadline itself. On trip: fail-loud — ERROR log + an operator-surface notice that is
   **exempt from shadow routing** (§7.2: machinery health is never shadow-gated). It
   shares no code with the cycle beyond reading the stamp file; its reliability argument
   is its triviality. Built by the same factory gate (§3.2) — no heartbeat, no watchdog.
3. **Boot reconcile:** at heartbeat construction, a stale stamp from the previous session
   (older than K × interval relative to its own `started_at` chain) surfaces one boot-time
   notice — catching "it was wedged before the crash/shutdown," which a fresh in-session
   watchdog cannot see.

**Same-process limit, stated honestly:** the watchdog catches the realistic failure class —
a wedged or dead heartbeat *thread* inside a live app (I/O hang, escaped exception, logic
wedge). A dead *app* is not a heartbeat failure (nothing is supposed to be beating; the
elevated 23:00 task remains the only app-not-running wake path, §2.13.1). **Rejected:**
piggybacking the check on the overnight task's PowerShell (`run-battery-night.ps1`,
agentic-setup repo) — cross-repo coupling for zero added coverage of the wedge class the
check exists to catch; reconsider only if an app-independent auditor is later wanted, as
its own decision.

Lock shapes (acceptance): a fake heartbeat that stops stamping trips the watchdog surface
within K intervals; `thread_dead=true` trips it immediately; watchdog absent when
`heartbeat_enabled=false`.

---

## 7. The shadow seam (#855) and the digest surface — SETTLED

### 7.1 The split between C3 and #855

- **C3 builds:** the `[coordinator].shadow_mode` key (**default `true`**), the shadow
  journal store, and the output router (§7.2). C3's cycles run FULL pipelines from day one
  — deterministic evidence, ruler, staging, drafting — with all operator-visible and
  board-visible effects diverted to the journal.
- **#855 builds:** the grading harness over that journal (fixture-board eval suite in
  `evals/` per the #717 committed-baseline pattern — suite → baselines → regression exit
  codes, `evals/baseline.py:78-179`, `evals/run.py:11-43`), the measured-precision
  graduation, and the graduation ceremony mechanics.
- **Two independent locks on live output (principle 3):** flipping
  `heartbeat_enabled=true` (its own LA ceremony) starts *shadow* cycles;
  only the #855 graduation ceremony flips `shadow_mode=false`. No single flip
  produces operator-visible output.

### 7.2 The output router (shadow vs live), per side effect

| Side effect | Shadow (`shadow_mode=true`) | Live (post-graduation) |
|---|---|---|
| Stall comment (`post_task_comment`) | Journal entry (seen-set updates on journal success, so dedup behavior is gradable) | Vikunja comment |
| Board move (`move_job_card`) | Journal entry | Vikunja bucket move |
| Redispatch proposal | **Real store, DRAFT only** (never promoted to STAGED) + full-context journal copy | Store DRAFT → STAGED (surfaced) |
| Digest | Journal entry | Operator surface (§7.4) |
| Quiet-queue tripwire alarm (a coordinator *judgment* — its false-alarm rate is precisely what shadow measures) | Journal entry | Operator surface |
| **Machinery health** — dead-man staleness, `thread_dead`, substrate-`UNREACHABLE` conditions | **Operator surface, always** — never shadow-gated: routing the watchdog's own alarm into an unread journal would re-create the vigilance dependence §2.14.1 exists to kill (and would silently bias #855's cycle accounting) | Operator surface |
| Liveness stamp, transition record, cycle telemetry | **Always live** (internal, operator-invisible; the age history §4 accrues during shadow on purpose) | Always live |

Proposals landing in the real store as DRAFTs during shadow keeps fingerprint dedup and
decision history continuous across graduation (`add_draft` idempotency
`proposal_store.py:408`; the any-status `find_by_fingerprint` history check
`proposal_store.py:622`, consumed by the stager's `already_decided` split at
`coord_redispatch.py:343`) while honoring #855's "zero operator-visible output, zero
Vikunja writes" — surfacing *is* the STAGED transition plus rendering, and neither happens
in shadow.

**Graduation hygiene (the seen-set):** `run_stall_cycle` persists posted fingerprints to
the one seen-set regardless of sink (`coord_stall_monitor.py:118,136-142`), so a stall
ongoing at graduation would carry a shadow-era fingerprint and its first LIVE comment
would be suppressed. On the first live cycle after shadow (detected by comparing the
liveness stamp's recorded `shadow_mode` against the current config), the stall seen-set is
reset once — every ongoing stall earns its first live comment as a fresh episode — and the
shadow/live divergence is named for #855's grading rather than assumed away.

### 7.3 The shadow journal store

Content-bearing (proposal payload copies, digest text, comment text) ⇒ **born-encrypted**
(ADR-039 §2.13.2 names the shadow journal explicitly): an append-only log store in
`shared/coordinator/`, a fourth consumer of the existing one-DEK sealed-store machinery
(`build_proposal_store`'s factory shape, `proposal_store.py:668-763` — refuse-to-start
without a provisioned keystore, AAD-bound rows, sanctioned-API-only writes; **no new
crypto**). It lives under `coordinator_store_root`, which `GovernedCoreRoots` already
enumerates for exactly this store (`shared/coordinator/config.py:261-262`) — governed core
from birth.

### 7.4 The digest surface

A digest is a structured `DigestRecord`: deterministic skeleton (queue depth per project,
flow deltas, new/ongoing stalls, gated or unreachable conditions, proposals pending, runs
harvested) + optional model prose, tagged as model-drafted (provenance-honest). At most
one per cycle; absence mode accumulates instead (§8.2). Live rendering (post-graduation,
not built live in C3): the AO renders it in chat under the `UNTRUSTED` provenance tier
(§2.12.13 — ticket-title injection must not become chat injection) at the next
conversational opportunity, and the WinUI typed progress feed (#712 lineage) may carry the
skeleton. **Never a Vikunja comment** — the bridge's outcomes-only invariant is untouched
(§2.10 C3; the anti-firehose F11 lock: digest-never-a-ticket-comment).

---

## 8. Tripwire, absence mode, power/thermal cadence — each explicit

### 8.1 Quiet-queue tripwire (tri-state-aware; §2.12.6, plan §C3)

**Fires** (defect-grade surface: "Ready work exists and nothing is pulling") only when ALL
hold: Ready non-empty for some project (from `OK` board reads), dispatch WIP below the
global cap of 1 (no swap in flight, no active run), and no pull within the configured
grace. **Suppressed, with the suppression itself surfaced where informative:**

- any consulted substrate `UNREACHABLE` → suppress + surface "PM substrate unreachable"
  (unknown ≠ quiet — a dead Vikunja must never look like a finished backlog);
- swap in flight; inside the overnight window (the fleet owns the night); within the
  post-boot idle-grace (§9);
- operator-absence active and the condition is not Expedite-class (§8.2).

**Resource-eligibility seam (forward-named, honestly scoped):** the §2.9 `Resource:*`
registry and its evaluators are not yet built (verified; C4-era with the pull policy). The
tripwire's predicate is written against *eligible* Ready from day one, with "eligible" ≡
"all Ready" until the registry lands — at which point an all-gated Ready column reports as
the gated-inventory digest line, never a tripwire alarm, per the already-locked doctrine.
Nothing in C3 has to change shape for that; the seam is a function argument.

### 8.2 Operator-absence mode (§2.12.9)

C3 ships the **config switch** (`operator_absent`, operator-set outside BlarAI like every
`[coordinator]` key): only Expedite-class conditions surface; digests accumulate into one
catch-up brief (emitted on the first non-absent cycle); **proposal TTLs pause**. The TTL
pause is real, not a sweep-skip: skipping `expire_stale` during absence and sweeping on
return would demote everything at once — instead the store gains one sanctioned-API method
(`extend_ttl(delta)`-shaped — a NEW method, nothing of the kind exists today), applied at
absence exit for the absence duration; the duration itself needs a recorded start, so the
flip to `operator_absent=true` is stamped in the coordinator state dir the first cycle
that observes it. This keeps "absence never returns to a wall of stale asks" literally
true. **Auto-detect via N
unanswered briefings is C4's** (briefings do not exist until C4) — named here so the seam
is explicit, not silently dropped.

### 8.3 Power/thermal-aware cadence (§2.12.12)

Recon verified the runtime has **zero power awareness today** (battery detection exists
only in offline bench scripts, e.g. `phase2_gates/scripts/run_p5_feasibility_003.py:97-119`;
thermal has no live sensor anywhere, TTFT-proxy only). C3 adds:

- **Battery probe** — `psutil.sensors_battery()` (psutil is already a declared runtime
  dependency — `pyproject.toml:61`, used at `swap_state.py:196`), read once per cycle,
  fail-soft, with three distinguished outcomes: a present battery discharging ⇒ battery
  restrictions (interval × the configured multiplier AND no model drafting); a present
  battery on AC ⇒ AC; **`None` — psutil's documented "no battery device" — ⇒ AC, with the
  condition noted in cycle telemetry** (treating a battery-less desktop as perpetually
  throttled would silently degrade the multi-operator case, §2.2 control 5, for no safety
  gain; the telemetry note keeps a laptop driver anomaly visible). A probe
  **exception/undeterminable state** resolves conservatively to battery-equivalent
  restrictions with the condition surfaced (`UNKNOWN` never renders as "plugged in",
  §2.14.4 discipline).
- **Overnight window, runtime-readable** — new config keys (§9); today the 23:00 window
  exists only as a Windows Scheduled Task + sibling-repo PowerShell, invisible to the
  runtime. Inside the window: deterministic-only (the GPU belongs to the fleet) and
  tripwire quiet.
- **Thermal throttling, stated honestly:** there is no in-tree throttle signal, and this
  design does not fake one. The practical throttle windows on this device are covered by
  the three gates above (battery, overnight fleet work, mid-swap); a first-class Windows
  thermal probe is a **named residual** (investigate at build; own ticket if viable) — not
  a silent claim (principle 11: no control that pretends to exist).

---

## 9. Config and registry additions (all dormant-default)

New `[coordinator]` keys (parsed into `CoordinatorConfig.from_toml`, surfaced via new AO
properties per §3.2; every one operator-only per control 4):

| Key | Default | Meaning |
|---|---|---|
| `shadow_mode` | `true` | §7 — output router; flips only at the #855 graduation ceremony |
| `heartbeat_interval_s` | `900` | AC-power cycle interval (15 min — coarse enough to be invisible, fine enough for hours-scale flow) |
| `heartbeat_battery_multiplier` | `4` | battery interval = interval × multiplier (60 min) |
| `heartbeat_boot_grace_s` | `300` | first cycle waits out boot/preflights; also the tripwire idle-grace floor |
| `overnight_window` | `"23:00-09:00"` | runtime-readable quiet window (§8.3) |
| `operator_absent` | `false` | §8.2 |

`timeout_registry.py` rows in the same change (the gate test cross-checks live values;
pattern per `DOOM_STALL_GRACE_S` `:457-466`): `heartbeat_interval_s` (900), the dead-man
**slack** (checked against the stamp's own `next_expected_by` deadline, §6.2 — the
registered constant is the slack, not a computed threshold, so cadence stretching never
false-alarms), `heartbeat_boot_grace_s` (300). Poll-grain minutiae go to BACKLOG per the
registry's own convention. (`heartbeat_enabled` itself
already exists — `default.toml:476`, `config.py:157`.)

---

## 10. Security-by-design walk and scope fences

### 10.1 The principles, applied (CLAUDE.md §security_by_design)

1/2 (fail-closed, deny-by-default): targeting refusals are final; `build_heartbeat` builds
nothing unless explicitly enabled; probe-unknown degrades restrictive (§8.3). 3
(defense-in-depth): trusted-source + SG ruler on every target (§5); two ceremonies before
live output (§7.1); staging-time + (future) execution-time rulers. 4 (structural absence):
no flag ⇒ no thread/object/import (§3.2). 5 (single adjudication door): the heartbeat adds
no adjudicator and no execution surface; approved redispatches still travel the existing
`/dispatch` path under its own CARs (ADR-039 §2.6). 6 (born-encrypted): shadow journal
(§7.3); proposal payloads already are; new plaintext artifacts are non-content-bearing by
construction (§4.3, §6.1). 7 (validate before trust): repo ids re-derived from structured
fields and ruler-checked (§5); predicate/config values never from model text. 8 (least
data): stamp/record carry ids and timestamps, no content. 9 (isolation): no new parsing of
untrusted external input; ticket text stays inside the existing provenance regime. 10:
no new signing surface (control 7 unchanged). 11 (fail-loud): thread-death stamping +
dead-man (§3.3/§6); surfaced fallbacks (§4.4, §8.1). 12 (every control tested off): the
byte-identical-when-off locks (§3.2) and the watchdog-absent-when-disabled lock (§6). 13
(irreversible = ceremony): both flips are LA ceremonies (§7.1).

### 10.2 Threat model (per #845)

Injection via ticket/run content reaches at most proposal *wording* and digest *prose* —
never a target (§5), never a gating predicate, and digest prose renders under `UNTRUSTED`
provenance in chat (§7.4). Wake-cycle failure fail-softs toward the assistant through four
walls (§3.3). No new egress: every read is local files or the loopback-pinned bridge
(`assert_loopback`, `vikunja_bridge.py:113`); the one-network-client invariant is
untouched. Crash-safe by §2's convergence argument plus `reconcile_at_boot`. The
heartbeat's own trigger definition (timer + interval keys) is governed core (§2.1 item 8):
BlarAI has no write path to any of it (control 4), and this design adds none.

### 10.3 What C3 deliberately does not do

- No approve→execute wiring: `/coord approve|reject <id>` records a disposition on a
  STAGED proposal (store transitions, `proposal_store.py:478-489`); executing an approved
  redispatch remains the operator's explicit `/dispatch`. Single-approval UX arrives with
  C4 briefings (§2.13.5), where `revalidate_for_execution` becomes binding (§5).
- No work origination (C4), no briefings or briefing ledger (C4), no autonomy flips (C5).
- No `Resource:*` registry/evaluators (§8.1 seam), no thermal probe (§8.3 residual), no
  own-move journal refinement (§4.5 residual).
- No new Windows Scheduled Task, no change to the 23:00 task, no VM involvement.

---

## 11. Build plan — seven limbs, C2-shaped (for LA affirmation)

C2's limb flow (one reviewable unit at a time; each dormant, gate-green, author≠verifier
reviewed, journal-fragmented, merged) is reused. Order chosen so every limb lands on
already-merged substrate; all limbs are battery-safe (no swap-path code anywhere in C3).

| # | Limb | Contents | Keyed acceptance locks (#845) |
|---|---|---|---|
| 1 | **Transition record + observed age** | record store (stall-seen pattern) + pure diff + composer injection; created fallback surfaced | dedup-grade determinism tests; UNREACHABLE-fallback lock |
| 2 | **Cadence/mode policy + probes** | pure mode ladder; battery probe; overnight-window config; new keys + registry rows | battery/unknown/overnight/mid-swap mode locks |
| 3 | **Cycle engine (pure)** | the §2 orchestration as a pure function over injected substrate handles + sinks; tripwire; absence filter; defensive wraps | forced-crash convergence; tripwire suppression + UNREACHABLE locks; dedup lock (same condition, 3 simulated cycles → 1 proposal); TTL-expiry lock; absence locks |
| 4 | **Shadow journal + output router** | born-encrypted journal store; §7.2 routing; `shadow_mode` key | zero-Vikunja-writes-in-shadow lock; encrypted-at-rest lock; one-digest-per-cycle + never-a-ticket-comment locks |
| 5 | **Drafting adapter** | `coordinator_draft()` AO seam; try-acquire; grammar fail-soft + deterministic fallback | mid-swap-zero-model-calls lock; busy-defers lock |
| 6 | **Launcher timer + plumbing** | `build_heartbeat` factory; AO properties; thread + teardown + import safety; liveness stamp | absent/false→None; OFF-boot byte-identical; bare-import lock |
| 7 | **Dead-man watchdog + boot reconcile** | §6 | wedge-trips-surface; absent-when-disabled |

Sequencing note: limbs 1–5 are pure/leaf modules (mergeable in any adjacent order); limb 6
is the first live-path touch and lands only after 1–5 are on main; limb 7 rides
immediately after 6. Standing-gate green before and after every merge; the #845 ticket
gets a dated CURRENT-STATE comment per landing (the C2 discipline).

---

## 12. Rejected alternatives (consolidated)

| Rejected | Why |
|---|---|
| Age = ticket-created as the standing definition | conflates backlog dwell with queue wait; distorts Standard FIFO and aging-WIP (§4.2); kept only as tie-break + surfaced fallback |
| Own-move journaling as the sole age mechanism | misses human/webUI/MCP moves — most of today's board movement (§4.5) |
| A new Windows Scheduled Task as the trigger | new privilege surface, blind to swap state, outlives the app (§2.13.1 already decided; restated for completeness) |
| An asyncio loop retrofitted into the launcher | the launcher's keep-alive is a blocking UI call (`:2164`/`:814`); a retrofit is a boot-architecture change for zero heartbeat benefit |
| Blocking/queued pipeline access for drafting | any wait couples heartbeat latency to chat; try-acquire-or-defer keeps chat untouchable (§3.3 wall 4) |
| C1's construct-always/check-inside dormancy for the timer | right for a read-only command object; too weak for a side-effecting thread — structural absence instead (§3.2) |
| Overnight-task dead-man | cross-repo coupling, no added coverage for the in-process wedge class (§6) |
| TTL sweep-skip as the absence pause | demotes everything at once on return; real pause via one sanctioned-API extension (§8.2) |
| Faking a thermal signal (e.g., TTFT proxy) in the cycle | a control that pretends to exist; battery+overnight+swap gates cover the envelope, residual named (§8.3) |
| Digest as a Vikunja comment | violates the outcomes-only invariant; locked off (§7.4) |
| A fixed dead-man threshold (K × AC interval) | false-alarms every battery/overnight-stretched cycle, retraining the operator to ignore it; the stamp declares its own deadline instead (§6) |
| Treating probe-`None` (no battery device) as on-battery | a battery-less desktop would never draft — silent multi-operator degradation for no safety gain; `None`→AC with telemetry note, exceptions still restrict (§8.3) |
| Shadow-routing machinery-health alarms | the watchdog's own alarm in an unread journal is vigilance by another name (§2.14.1); health is never shadow-gated (§7.2) |

---

## 13. Checkpoint asks (for the LA — plain language)

1. **Approve (or amend) this design** — approval authorizes the C3 *build* under §11's
   plan; nothing turns on (every new key ships off or shadow-defaulted; live output stays
   behind both the heartbeat ceremony and the #855 graduation ceremony).
2. **Affirm the limb decomposition** (§11) — the same one-reviewable-piece-at-a-time flow
   C2 used.
3. **Note the age decision** (§4): a coordinator-owned technical call per ADR-039's own
   header precedent, presented here with both options on the record rather than decided
   silently — say so if you want it revisited.
4. FYI residuals recorded, not built: thermal probe, `Resource:*` evaluators, own-move
   journal precision, C4's briefing/absence auto-detect.

---

## 14. Implementation errata (build phase — mechanism refinements within settled decisions)

**§6.3 boot reconcile (limb 7, 2026-07-14; named at the limb-7 review's dimension-3 recommendation).**
The approved text sketched boot-time staleness as "older than K × interval relative to its own
started_at chain." As literally specified, every ordinary app-off night leaves a wall-clock-stale
stamp, so the heuristic cannot distinguish a wedge from a shutdown and would notice at every boot —
the §2.14.1 alarm-retraining failure in boot-notice form. The shipped mechanism keeps §6.3's intent
(catch "wedged before the crash/shutdown") with sharper evidence: a **clean-stop marker** written by
`Heartbeat.stop()` in the launcher's stop-first teardown motion, an **overdue-aware guard** on that
marker (a heartbeat already past its own declared deadline + the registered slack at teardown — or
one whose deadline cannot be parsed — withholds the marker, so a wedge-into-shutdown is never buried),
and a **three-way reconcile** at the next enabled boot: `thread_dead` → wedge notice; neither dead nor
cleanly stopped → crash/wedge notice; cleanly stopped or no stamp → silence. Stamps additionally carry
a per-boot **session identity** (limb-7 review MAJOR 1): the in-session dead-man treats any stamp that
is not this boot's exactly like no-stamp (the boot-expectation grace governs, uniformly), so a leftover
crash stamp can never raise a present-tense alarm — the boot reconcile voices prior-session evidence,
past tense, once. Intent unchanged; verified at the limb-7 re-verification pass.
