# ADR-035 — Headless-coding dispatch increment 3: the Acceptance Layer

**Status:** PROPOSED 2026-06-22 (plan LA-approved-for-build with the two refinements folded — the
.NET honest-status rule and the single always-confirm flow; this ADR records the decision). Built
**DORMANT** — `[fleet_dispatch].enabled=false` ships. **Amendment 1 (2026-06-22): the go-live wiring
(Phase A) is BUILT** — config-driven #670 root, the PLAN/EXECUTE IPC split, the EXECUTE pass-through,
reply-then-step-aside, the daemon→main step-aside, the restart-surviving progress log — and is
**still DORMANT** (`enabled=false`). The flip + the first real goal→confirm→swap→report is the LA's
on-hardware Phase-B shakedown. **Amendment 2 (2026-06-23, #670 Problem 3 — the first live shakedown's
right-sizing refinement): `compile_prompts` now FOLDS the behavior/smoke criteria into the lone feature
task when a goal right-sizes to exactly ONE feature** (e.g. `is_palindrome`), instead of appending a
separate `acceptance-tests` fleet task that would spin its own worktree + model-swap cycle WITHOUT the
implementation in it (the live shakedown had that sibling run \~24 min failing). The dedicated final task
is RETAINED for ≥2-feature goals (its duplicate-test-file rationale only applies there); the anti-mirror
"assert the REQUIRED behavior" header is preserved verbatim in the folded prompt. Still **DORMANT**.
**Deciders:** Lead Architect (blarai); the build (this session).
**Builds on:** increment 1 (`shared/fleet/dispatch.py`, `/dispatch`, merge `04d9778`); increment 2
(the model swap + `decompose_request`, ADR-034); the agentic-setup fleet's verify gate
(`new-agent-task.ps1` / `verify-project.ps1` — the fleet side is the authority on its own gate).
**Relates to:** Vikunja #670; `Use Cases_FINAL.md` (dev-tooling capability, not a numbered UC).

## Context

The operator is a non-developer who will not write tests. For headless dispatch to produce
*verifiable* work, a plain natural-language goal ("a space-rocket calculator for an 8-year-old")
must become acceptance criteria that are actually checked. Increment 2 already decomposes a goal
into fleet tasks while the 14B is resident; increment 3 adds the criteria, the confirm, and the
honest read-back on top of it.

**A premise correction found by investigation (the load-bearing finding):** the brief assumed the
fleet's gate includes a launch + console-scan stage ("SMOKE"). It does not. The fleet's gate is
BUILD (the coder) → **TESTS** (`pytest -x -q` / `npm test` only) → **VERIFY**
(`verify-project.ps1`: per-ecosystem build/lint/typecheck — incl. `dotnet build`, `py:compile`) →
REVIEW agent → AUTO-MERGE. Crucially, `verify-project.ps1` runs `dotnet build` for .NET but there
is **no `dotnet test`**, and the TESTS stage is `pytest`/`npm test` only. So for a C#/UWP app a
behavior or smoke test **never runs** and comes back `none`, not `pass`.

## Decision

A pure acceptance core (`shared/fleet/acceptance.py`) + a single always-confirmed gateway flow
(`DispatchCoordinator`), with the fleet's gate reused verbatim and read back **honestly**:

1. **Model proposes, ruler disposes.** While resident, the 14B emits an `AcceptanceSpec` (criteria
   tagged `build|behavior|smoke|visual|human`) alongside the task decomposition. A **deterministic
   ruler** (`rule_spec`) drops vacuous (too-short) / malformed (bad-tier) / duplicate criteria and
   **injects a build floor** if nothing checkable survives — a dispatch is never gated by nothing.
   The model never self-certifies (brief §7.3; mirrors `decompose`).

2. **One flow, always confirmed (no unconfirmed fast-path).** Every `/dispatch <repo> | <goal>`
   runs PLAN (decompose + criteria + ruler) → renders the plain-English criteria → **WAITS**.
   Work fires **only** via `/dispatch approve`; `/dispatch reject` discards. The increment-1
   "enqueue + run immediately" entry is **removed**. "Skip the model swap when the 30B is already
   loaded" is an **internal branch of EXECUTE** (still confirmed), never a separate surface. The
   confirm is mandatory **by construction** — no code path reaches EXECUTE except the approve verb.

3. **Criteria reach the coder folded into the lone feature task, or via a dedicated final task —
   never baked into every task.** When a goal right-sizes to exactly ONE feature, `compile_prompts`
   FOLDS the behavior/smoke criteria into that task's prompt (#670 Problem 3 Am.2 — one worktree, one
   merge, so a separate task would only spin a doomed implementation-less worktree). When there are
   ≥2 feature tasks, it appends ONE `acceptance-tests` task carrying the criteria, run **last** (after
   the feature tasks auto-merge): baking the same tests into every task would write duplicate/conflicting
   test files across the per-task worktree merges, so one final test-writer runs against the complete
   code. Either shape carries the anti-mirror "REQUIRED behavior" header verbatim.
   **Semantics (stated plainly):** because the feature tasks auto-merge *before* the acceptance task
   runs, the acceptance task **reports and best-effort-repairs** against the already-merged code — it
   does **NOT** hard-block the feature merge. A failed criterion surfaces as `FAIL` in the report
   (and the acceptance task attempts a fix against the merged feature code), but the feature is
   already in `main`; the operator re-dispatches a fix if needed. This is intentional and honest: a
   post-hoc gate cannot un-merge, so the report tells the truth about what passed rather than
   pretending to block. A hard pre-merge acceptance gate would require changing the fleet's per-task
   auto-merge — fleet-internal, out of scope.

4. **Read the result back HONESTLY — never rubber-stamp an unrun check (the core anti-false-pass
   rule).** `criterion_status` returns `verified` **only** on an actual `pass`; `fail`→`failed`;
   **`none`/`skip`→`unverified`** ("NOT AUTO-CHECKED — verify yourself"); visual/human→`eyeball`.
   The report renders `unverified` distinctly from a pass and says plainly that for C#/.NET only the
   build is checked. An unrun behavior/smoke criterion is UNVERIFIED, not passed — the exact
   false-pass this layer exists to prevent.

5. **Honest ecosystem coverage, stated UP FRONT.** Python + Node get real behavior-gating; **.NET
   is BUILD-ONLY**. The confirm-time preview detects the repo's ecosystem and warns before approval
   ("a clean report means 'it compiled,' not 'the math is right'"), so a clean-looking report never
   misleads.

6. **Open-it-myself report.** The post-run report ends with the single, dead-simplest command to
   open the built app (`npm start` / `dotnet run` / `python <entry>`, else "open the folder") — one
   obvious step, not a fragile one-tap auto-launch that would grab the operator's screen. Criteria
   persist run-id-keyed (`runs/<run_id>/acceptance.json`) so the report survives the swap restart.

## Consequences

- **Ecosystem-asymmetric assurance (named, not hidden):** for Python/Node a green report means the
  behavior tests ran and passed; for .NET it means it compiled and the rest is the operator's
  eyeball. This asymmetry is stated at confirm time and in every report.
- **`criterion_status` trusts `TESTS: pass` at face value** — a vacuous or wrong coder-written test
  still reads `verified` (the 30B writes its own acceptance tests, so it can codify a wrong
  implementation as "passing"). Closing that needs red-first / mutation validation (**Enhancement-1**,
  deferred, tracked at #670) — kept explicitly in view, not lost. **Go-live hardening (LA, recorded
  here):** at go-live the `acceptance-tests` prompt is hardened to *"assert the criterion's REQUIRED
  behavior, not whatever the code currently does"*, so the coder writes tests against the spec, not
  against the implementation it just wrote.
- **An extra fleet run** for the dedicated acceptance task **on multi-feature goals** (a marginal 30B
  run); accepted for correctness (no duplicate test files) and clarity. Single-feature goals fold the
  tests in (#670 Problem 3 Am.2) and pay no extra run.
- **Live wiring deferred:** the PLAN/EXECUTE AO-IPC round-trip + the launcher step-aside on approve
  are unset in the shipped build; an enabled-but-unwired `/dispatch` confirms and then reports
  "wiring not connected" rather than firing. The first real run is the on-hardware go-live.

## Rejected alternatives

- **Bake criteria into every task prompt:** duplicate/conflicting acceptance-test files across the
  per-task auto-merges. Rejected for the dedicated final acceptance task.
- **Keep the increment-1 unconfirmed immediate path as a fast-path:** rejected by LA ruling — one
  flow, always confirmed; a non-dev should never have a path that fires work without the criteria
  confirm.
- **Add `dotnet test` to the fleet so .NET behavior is gated:** fleet-internal, out of scope
  ("dispatch to the fleet, don't modify its internals"). Represented honestly instead; noted as the
  future/escalation item that would close the .NET behavior-gating gap.
- **VLM screenshot pre-screen / screenshot-in-chat for VISUAL/HUMAN:** dropped (LA) — loads a third
  model, slow and unnecessary; the operator opens the app and looks.
- **One-tap in-chat app launcher:** fragile across project types and a screen-takeover; deferred as
  Enhancement-2. The report prints the one command instead.
- **Mark an unrun objective check as a pass / "assume it's fine":** the false-pass the whole layer
  exists to prevent. Rejected — `none`/`skip` is always UNVERIFIED.

## Amendment 1 (2026-06-22) — the go-live wiring (Phase A), still DORMANT

Phase A wires the dormant layer to the live backend in four reviewable sub-parts (all built +
tested behind `[fleet_dispatch].enabled=false`; the flip + the first real swap are the Phase-B
on-hardware shakedown, the LA's step):

- **Config-driven dispatch target (#670, root-only):** the compiled-in `_AGENTIC_SETUP`/`_PROJECTS`
  become fallbacks; the target is `[fleet_dispatch].agentic_setup_dir` + `projects_dir`, resolved
  AO-side and threaded to the gateway. The agentic-setup **ROOT** is exposed (not separate
  scripts/state keys) because the fleet's internal `state\` layout is fixed — only the root is
  configurable, never the structure. **Writer-root == reconciler-root:** the swap-state WRITE and the
  boot reconciler READ both derive from `build_default_config(resolved roots)`, so a crashed swap is
  recovered under the root it was written to (a test pins them equal). The boot reconciler was
  retrofitted to read the configured root — it had used the fallback (the half-delivered #670 the LA
  caught at the sub-part-1 review).

- **The PLAN/EXECUTE split (the single always-confirm flow):** `/dispatch <repo> | <goal>` →
  `PLAN_REQUEST` → the AO runs `generate_plan` over a DIRECT, deterministic single-shot 14B
  completion (greedy `do_sample=False`, `<think>`-stripped — NOT the conversational `PROMPT_REQUEST`
  path) + the deterministic ruler → criteria preview (with a fell-back degradation notice when the
  14B couldn't parse the goal) → the operator approves → `EXECUTE_REQUEST` fires the swap. EXECUTE is
  reachable ONLY via `/dispatch approve`; "skip the swap if the 30B is already loaded" stays an
  internal EXECUTE branch, never a surface. **EXECUTE runs the operator-APPROVED tasks (the
  pre-decomposed pass-through) — it NEVER re-decomposes**, so the run cannot drift from what was
  approved.

- **Reply-then-step-aside + the daemon→main signal:** `_handle_execute_request` enqueues + hands off
  to the detached driver, sends the `EXECUTE_RESULT` reply, THEN (only on `ok`) waits a configurable
  grace (`step_aside_grace_s`) and steps the launcher aside — so the operator sees the "stepping
  aside" notice before the WinUI window closes. On an enqueue refusal there is NO step-aside (the 14B
  stays up). **The AO independently honors `[fleet_dispatch].enabled`:** an explicit enabled gate at
  the top of `_handle_execute_request` refuses the swap (never fires, never steps aside) when
  disabled — the swap is the single most destructive op, so it keeps its OWN dormancy lock beside the
  gateway's `enabled` (the two-lock posture). `set_swap_context` runs UNCONDITIONALLY at startup, so
  the `_swap_step_aside`-None "not-wired" check is a SECONDARY fail-safe, not the dormancy lock. (The
  same explicit gate is on `_handle_plan_request` for uniformity — PLAN is non-destructive, so it's
  belt-and-suspenders there.) The AO runs on a daemon thread and CANNOT
  `sys.exit` the process, so it asks the launcher's MAIN thread to exit via `_thread.interrupt_main()`
  → `atexit`→`_cleanup` (unload the 14B, free the GPU) → the detached driver loads the 30B and
  relaunches the launcher (never-zero). `old_pid` is `os.getpid()` (the launcher PID); `gate_gb` is
  the configured `swap_min_free_gb` (never a default); the relaunch is captured from the launcher's
  REAL startup mode (`compute_relaunch_argv`).

- **Restart-surviving progress log:** the WinUI closes during the swap, so the AO and the detached
  driver both append a human-readable trail to the SAME run-id-keyed `swap-progress.log` (stepping
  aside → 30B loading → gate pass/abort → fleet running → swapping back → 14B restored), surfaced by
  `/dispatch status` after the box returns.

**The i2 safety guarantees are untouched** — the EXECUTE path calls the same `prepare_and_launch_swap`
/ driver: never two large models resident, never end at zero, disarm-before-stop, `-Force` mandatory,
the `swap_min_free_gb` gate aborts-to-safe and is never bypassed.

**Testability boundary (stated plainly):** unit-tested with fakes — the PLAN/EXECUTE protocol
round-trips, the AO handlers (fake generator / injected swap + step-aside; no exit, no real swap),
the gateway seams, the relaunch capture, the pass-through, writer-root consistency, the progress
log, the launcher's swap-context wiring, and the built-but-wired dormancy guard. **LIVE-ONLY (the
Phase-B shakedown — a green suite does NOT prove these):** the launcher actually exiting, the 14B
freed + GPU released, the driver surviving the teardown, the real 30B loading + *fitting* (the first
live memory validation), the 14B coming back, the WinUI close/reopen, and the reply-then-exit timing.

*(A module-level `os` import was added for `_fire_swap`; `os` was previously function-local only, so
no production path was broken — the two now-redundant local imports were tidied.)*

## Amendment 3 (2026-06-24) — the confidence-gated clarifying question (build-signal increment 4, #677), still DORMANT

The build-signal architecture (`agentic-setup/docs/dispatch-build-signal-architecture.md`) closes
with one operator-facing refinement on top of increment 1 (the 14B's `surface` classification, merged
`a293dc2`): when the 14B genuinely **cannot tell which PLATFORM** a clearly-GUI/app goal targets
(desktop vs web vs phone — the textbook ambiguity), the SYSTEM asks **ONE** curated, product-level
question rather than guessing. The discipline that keeps this from becoming a rubber-stamp quiz: the
**14B only FLAGS the ambiguity**; the **SYSTEM owns the question text and the answer→surface mapping**
(small models write leading/irrelevant questions). For every other goal the surface is clear/unknown
and the flow is **byte-identical to today** — guess + confirm in the preview (increment 1). It is
**strictly additive + fail-closed**: a wrong/absent ambiguity signal can never change the existing
flow (locked by kill-tests).

- **The signal (Part A, `shared/fleet/acceptance.py`).** A new `SURFACE_AMBIGUOUS = "ambiguous"`
  sentinel, DISTINCT from `SURFACE_UNKNOWN` (`unknown` = "couldn't classify at all" → no scaffold;
  `ambiguous` = "classified the KIND but the platform forks" → ask one question). The 14B emits it
  with a `candidates` list of the real surfaces it is torn between; `_parse_build_plan` validates the
  candidates fail-closed (keep only members of the REAL buildable enum — desktop-gui / web / mobile /
  command-line / automation / library; drop sentinels/garbage; dedupe; cap 4) and enforces a
  **coupling**: an `ambiguous` flag with `<2` real candidates is a non-fork (the model hedged) → coerce
  `surface→unknown` (today's behavior); a non-ambiguous surface forces candidates empty. The
  `candidates` key is attached to the parsed dict **only** when the fork is real, so every clear/unknown
  plan keeps its exact pre-increment-4 four-key shape — byte-identical wire/output (every existing
  payload + exact-equality test is unaffected). `ambiguous` is deliberately ABSENT from
  `_SURFACE_FRIENDLY`, so it never renders a "Building this as" preview line (there is no single
  platform to name yet).

- **The curated decision map + the two pure functions.** `_CLARIFY_DECISION_MAP` is **SMALL by
  design** — v1 is the PLATFORM case ONLY (`{desktop-gui, web, mobile}` and its three 2-way subsets),
  keyed on the candidate **frozenset** (order-independent). The platform fork is the textbook decision
  that (a) materially forks the build, (b) the 14B genuinely cannot assume, and (c) the operator can
  answer in product terms ("Where will you mainly use this? ① On this computer ② In a web browser
  ③ On a phone"). Everything else stays assume-and-show-in-the-preview (the assumptions block); the map
  grows only when a NEW decision clears all three bars — the same principle as routing consent to the
  coarsest meaningful grain (ask the human only what they can actually judge). `resolve_clarifying_question`
  (PURE) returns `{question, options}` ONLY when `surface == "ambiguous"` AND the candidate-set has a map
  entry — else `None` (no question → today's flow). `apply_clarification` (PURE) maps the operator's
  answer to a real surface, VALIDATED against the plan's OWN candidates (an off-list answer is ignored →
  the plan is returned unchanged so the caller re-asks/falls back), and clears `candidates`. The
  `_BUILD_PLAN_TEMPLATE` gains a SHORT gated instruction ("use ambiguous ONLY if … do NOT use it as a
  hedge — over-asking is worse than a wrong guess the operator corrects in the preview" — the small-model
  long-prompt-regression lesson).

- **The interactive sub-state (Part B, `DispatchCoordinator`).** ONE bounded sub-state EXTENDING the
  existing pending-approval machinery (not a parallel flow). After PLAN, the coordinator calls
  `resolve_clarifying_question(spec.build_plan)`; if it returns a question it holds the planned dispatch
  in a new `PendingClarification` slot and asks the numbered question BEFORE the normal preview. The
  operator answers with the option number (`/dispatch <n>`, also `/dispatch use <n>`); the coordinator
  `apply_clarification`s, **re-threads the goal-level build fields onto the already-compiled tasks**
  (only `surface` changed; the folded test block is untouched — NOT a re-run of `compile_prompts`),
  updates `spec.build_plan`, then proceeds to the SAME approval preview a clear surface would have shown.
  **Bounded to one clarifying turn per dispatch** (the #6 one-pending-slot concern): the slot clears on
  answer OR fallback; a malformed/out-of-range answer FALLS BACK to the un-refined plan (re-threaded so
  the unresolved `ambiguous` surface coerces to `unknown` == the fleet's no-seed path) with a plain
  note — never a hang/loop. `reject` cancels at the question phase too; a new `/dispatch` while a
  question is pending is refused (the 14B is not re-run).

- **No new IPC verb/field (the brief's "prefer reusing the PLAN-preview channel").** The ambiguity
  signal (`surface=ambiguous` + `candidates`) rides INSIDE the spec dict over the EXISTING `PLAN_RESULT`
  channel — the AO sends `criteria=spec.to_dict()`; the gateway reconstructs via
  `AcceptanceSpec.from_dict`, so `build_plan` (incl. `candidates`) survives end-to-end. `build_plan` was
  already round-tripped for increment 1; `candidates` is just a new key inside that already-transported
  dict, and the answer path is gateway-side state riding the existing `EXECUTE_REQUEST`. A
  PLAN-seam test binds the property.

- **Defence-in-depth.** `_task_build_fields` coerces an unresolved `ambiguous` surface to `unknown` so
  the sentinel can never reach the fleet (which knows nothing about it) — the safe no-seed path.

**Verification (off-dispatch, the green E2E the LA re-runs):** +44 tests — Part A: the decision-map
mapping (3-way + each 2-way subset, order-independent), `apply_clarification` (valid/off-list/copy/None),
the fail-closed coupling, the GATING kill-tests (a CLEAR surface resolves to `None` + a non-ambiguous
plan parses byte-identical), `_validate_candidates`, the candidates round-trip, the fleet-threading
defence, and end-to-end `generate_plan`; Part B: the clarifying sub-state, the answer threads the
surface into the task + the approve/record, the KILL-TEST that a clear surface (and a no-build_plan
plan) drive NO extra turn, the fallback (out-of-range/non-numeric → un-refined, no hang), the
unmapped-fork fall-through, reject-clears-question, and execute-fires-only-on-approve across the new
sub-state; + the IPC-transparency lock. Standing gate **4300 passed / 20 skipped (the documented `bge`
model-absent isolated-worktree env-skips) / 118 deselected / 0 failed** (`+44` over the same selection on
`main`).

**NOT verified here (the LA's step):** the live 14B ambiguity-detection QUALITY — whether the model
flags `surface: ambiguous` + sensible `candidates` for a genuinely ambiguous goal AND classifies a clear
goal as clear (not over-asking). That needs a real decompose (the off-dispatch live PLAN probe scheduled
before/with the increment-4 test dispatch). The signal-plumbing + the system's question/mapping are
proven; the classifier's judgment is the on-hardware open item (named in §9 risks: 14B mis-classification,
mitigated by the enum constraint + the preview confirm + the downstream gates). **Still DORMANT** behind
the SAME `[fleet_dispatch].enabled=false` — no flag flip, no go-live.
