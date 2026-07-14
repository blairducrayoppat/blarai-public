# BlarAI Fleet-Dispatch KPI Log

This file is the authoritative tracked long-term log of the headless **coding-fleet's
dispatch KPIs** — how well the autonomous coder fleet performs, and how its
configurations compare over time.

It is the fleet-dispatch analog of `PERFORMANCE_LOG.md`. Where `PERFORMANCE_LOG.md`
answers *"how fast does BlarAI's own 14B/PA model generate"* (model-inference
throughput), this file answers *"how well does the coder-fleet dispatch
build → verify → merge, and how do its driver / model / containment configurations
compare."* Two different subsystems, two different logs, so neither muddies the other.

## What belongs here

- **Driver comparisons** — stdin vs ACP, and any future coder driver (wall-clock,
  turns-to-green, observability, cancel/stall behavior).
- **Coder-model-in-dispatch performance** — per coder model (coder-30B-A3B, future
  candidates): wall-clock, turns, merge rate on a fixed task.
- **Dispatch reliability KPIs** — merge rate, PARKED/STALLED rates, best-of-N
  efficacy, circuit-breaker / idle-stop frequency, per the nightly battery.
- **Containment / topology comparisons** — operator-account vs restricted-account
  (`blarai-coder`) overhead; host vs VM dispatch (when that lands).

## Log-management rules

1. **Newest entry at the TOP.** Dated `### YYYY-MM-DD — <title>` sections.
2. Every entry MUST name: the configs compared, the task + methodology, the run
   count, the measured numbers, and — explicitly — **what was NOT measured / the
   confounds** (never imply full coverage).
3. **Machine-readable companion data** lives in `docs/performance/*.json`, linked
   per entry (the dataset that can feed analysis / community contribution).
4. KPIs are only comparable across entries when the **task + methodology match** —
   say so when they don't.
5. **Fleet-dispatch wall-clock is coder-stochasticity-heavy** (the coder runs at
   temperature 0.7): prefer distributions + named confounds over single-run point
   numbers. A single clean run proves little; a single slow run indicts nothing.

---

### 2026-07-12 — Nightly battery 20260712: B5 STALL (leaked-AO port-collision) → same-day Option A fix

**Config:** M2 nightly battery, coder-30B-A3B (INT4, OVMS), **acp driver** (first full night after
the #775 acp flip), best-of-N. Jobs requested: B1 B2 B4 B5 B6 B7. Run `night-20260712-004004`.

**Result (runner exit 1 → campaign NOT counted as a full pass):**

| Job | Verdict | Wall | Attribution |
|---|---|---|---|
| B1 | PARKED-HONEST | 1,978s | BUILD |
| B2 | PARKED-HONEST | 2,147s | BUILD |
| B4 | PARKED-HONEST | 3,467s | BUILD |
| B5 | **STALLED** | 480s | **HARNESS** |
| B6 | PARKED-HONEST | 1,212s | BUILD |
| B7 | PARKED-HONEST | 3,108s | BUILD |

Reliability (#789 honest denominator): GREEN 0/5 plan-graph-eligible (raw 0/6); flat-queue=0
(structurally non-GREEN, under-decomposed); mode-unknown=1.

**Reading:** 5/6 jobs produced **HONEST PARKED-HONEST[BUILD]** results (**0 FALSE-DONE** — the core
grading invariant held all night; standing Confirmation-2 evidence). The one HARNESS failure (B5,
"No response from AO", 480s) is the AO-lifecycle-overlap / leaked-AO port-collision (#750) —
root-caused + **FIXED same-day: Option A** (the teardown barrier, prove-prior-AO-dead-before-boot)
merged `3a348bcd` + **LIVE-VERIFIED** (killed a real leaked AO from the 07-11 PT10H-killed run, freed
:5001 in ~2s, clean mTLS recovery at 55s). Tomorrow night runs the barrier before every reboot, so B5's
failure class should not recur.

**0 GREEN — the known #763 gap, not new:** in plan-graph mode the coder codes blind to the oracle, so
plan-graph jobs PARK-HONEST rather than GREEN. The oracle-to-coder fix is built + held
(`feat/763-oracle-to-coder @90fbc3d4`), landing when the campaign banks 3 passes (per the standing trigger).

**NOT measured / confounds:** per-job wall-clock is coder-stochasticity-heavy (temp 0.7) — single-night,
not a distribution; the B5 STALL truncated the night (no B5 build signal); no driver A/B tonight
(acp-only); campaign pass-rate unaffected (this run not counted).

**Data:** `agentic-setup/state/battery/night-20260712-004004/MORNING-REPORT.md` (+ battery-runner.log +
scorecards). Refs: #750 (Option A fix, closed), #740 (campaign), #763 (0-GREEN gap), #871 (leaked-AO residual).

---

### 2026-07-11 — ACP vs stdin coder-driver A/B (Decision-A) + driver go-live

**Config compared:** the fleet coder DRIVER — `stdin` (production `opencode run` +
transcript-regex monitoring, per-turn re-spawn) vs `acp` (a persistent
`opencode acp` session over the agent-client-protocol 0.11.0 Python client, typed
event stream). Coder model coder-30B-A3B (INT4, OVMS), temp 0.7. Ticket #775.

**Task / methodology:** a fixed one-file build+test (`wordstats.py` + pytest),
`-Complexity simple -LanguageHint python -MaxRunMinutes 20 -Concurrency 1`
(best-of-2). 3 rounds × 2 legs, **alternating leg order across rounds for thermal
fairness** (#778); process-scoped `BLARAI_FLEET_DRIVER_CONFIG` override for the acp
legs (production config untouched); wall-clock via Stopwatch; every acp leg
void-guarded (`[driver=acp]`, no fallback). R2 legs box-CPU-load-sampled.

**Measured (6 legs, all MERGED, all tests+verify pass):**

| Round (order) | ACP wall | stdin wall |
|---|---|---|
| R1 (stdin 1st / acp 2nd·hot) | 911.6s (verbose 17-step) | 360.9s |
| R2 (acp 1st·cool / stdin 2nd·hot) | 534.7s (10-turn spin) | 612.4s |
| R3 (stdin 1st / acp 2nd·hot) | 394.5s (both candidates idle-stuck, stall-bounded) | 413.9s |

acp mean 613.6s / median 534.7s · stdin mean 462.4s / median 413.9s · per-run range **360–912s**.

**Disposition — WALL-CLOCK INCONCLUSIVE (coder-stochasticity-dominated), as ACP-01 §6
predicted.** The ±550s stochastic swing at N=3 swallows any driver signal; each acp
leg's excess was a distinct transport-INDEPENDENT coder event; the drivers' different
*stop-mechanisms* moved wall-clock more than transport did. acp mean ~30% higher but
NOT attributable to transport. **Observability/stall/cancel superiority is proven +
was demonstrated live** (acp's typed-event stall-detector cleanly caught 3 wedged-coder
phases the stdin CPU-probe heuristic historically false-doomed/#687). **Decision: flip
to `driver=acp`** on the ACP-01 §6 basis (observability merits, not a wall-clock win the
confound can't deliver); LA-approved after the ambiguous-D-A escalation; first flipped
production dispatch verified `[driver=acp]`/MERGED. #779 closed. Live since
agentic-setup `2ef37e5`.

**NOT measured / confounds:** tokens (local-model proxy reported `usage_update: used:0`;
a-priori driver-independent); a low-variance controlled comparison (temp-0 coder / N>3)
that would settle the raw-mean gap and the 2/3-acp-idle-events question (acp's more-
sensitive detection firing vs acp inducing more wedges — unresolved at N=3); per-leg box
load for R1/R3 (R2 only: acp ~44% / stdin ~33%).

**Data:** `docs/performance/acp_ab_driver_2026-07-11.json` · narrative:
`BUILD_JOURNAL` fragment `2026-07-11_775-acp-driver-flip.md` · ticket: #775.
