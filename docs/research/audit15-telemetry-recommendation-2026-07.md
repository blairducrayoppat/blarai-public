# AUDIT-15 / #814 — In-runtime, air-gapped telemetry layer (recommendation)

*Research recommendation for the Lead Architect's decision. Read-only study — nothing was built, no config or runtime state was touched. Author: research session, 2026-07-17.*

**Scope note.** This document recommends on the **appliance** track of #814 — the BlarAI runtime services (`services/assistant_orchestrator`, `services/policy_agent`, the shared inference pipeline), which is the ticket-as-filed. The 2026-07-11 overnight comment on #814 surfaced a second, distinct surface — the **headless-coding fleet** (`battery.py`, swap driver) — and left "fleet / appliance / both" as an open LA scope call. That fleet-vs-appliance split is still the LA's to make; this study does not pre-empt it. Everything below concerns the appliance.

Acronyms on first use: **TTFT** = time-to-first-token; **RSS** = resident set size (a process's live memory); **fd** = file descriptor (an open file/socket handle; on Windows the equivalent is a "handle"); **p50/p95/p99** = the 50th/95th/99th percentile of a distribution (median, and the slow-tail readings); **MTTR** = mean time to recovery; **PA** = Policy Agent; **AO** = Assistant Orchestrator; **OTel** = OpenTelemetry; **In-Use RAM** = Total − Available system memory (the project's memory-accounting rule).

---

## 1. Recommendation (read this first)

**Build a local-only, in-process telemetry layer: a bounded in-memory aggregator that turns the per-call timings BlarAI already computes into rolling p50/p95/p99 latency + tokens/sec per surface, plus a periodic memory/handle sampler that records the In-Use-RAM and RSS *slope* over the process's life. It surfaces through the existing internal channels only — an in-process/health read (the natural data source for the #878 operations dashboard) and a rotated local append-log for long-horizon trend — and it contains no network client of any kind, by construction. A Prometheus- or OpenTelemetry-style exporter is the wrong tool here and is explicitly rejected: both add a network surface (a scrape endpoint or a phone-home client) to an appliance whose entire egress posture is deny-by-default behind a ceremony.**

The audit that produced #814 already pointed at this exact shape ("an in-runtime aggregator around `SharedInferencePipeline.generate` + the transport path"; "sample resident-process RSS + `num_fds`... asserting a bounded slope"). The design work is not *what* to measure — that is settled — it is *how* to collect it without paying a hot-path tax, without ever creating an egress surface, and without the aggregator itself becoming the memory leak it exists to detect. Those three are solved problems in this codebase: the byte-neutral-when-off instrumentation discipline (#900, lesson 279), the fail-soft `psutil` memory primitive already shipped (`shared/diagnostics.memory_snapshot`), and the deterministic pure-function aggregation pattern already shipped (`shared/fleet/flow_metrics`).

### Decision table

| Decision | This is the LA's call because… | Recommendation |
|---|---|---|
| **Fund the appliance telemetry layer?** | It is a new (observability) capability. | **Yes.** Highest-leverage cross-cutting investment per the audit — one layer serves Stability (RSS/fd slope), Resilience (MTTR/restart count), Performance (p50/p95/p99, tok/s). A decades-lived appliance without it is blind to gradual degradation between manual benchmark ceremonies. |
| **On-by-default, or off-behind-a-flag?** | It changes steady-state runtime behaviour (even if near-zero cost). | **On by default**, with a master kill-switch config flag that fail-safes to *off*. Collection is a fixed-size ring append (~nanoseconds, allocation-free) — cheap enough to always-on, which is the whole point of decades-long observability. The flag exists so the layer is provably removable and testable-off (principle 12). |
| **Encrypt the telemetry at rest?** | It is a privacy/at-rest posture call. | **No — because it is structurally metadata-only.** Telemetry records numbers (latencies, counts, RSS), never prompt/response content or the classified resource. Least-data-by-non-collection is a *stronger* posture than encrypting content you chose to collect: there is nothing sensitive to protect. (Guardrail: aggregate-only rows, no per-session identifiers in the durable log — see §4.) |
| **Where does the durable trend log live?** | It is a data-egress-surface call (git → public mirror). | **`%LOCALAPPDATA%\BlarAI\telemetry\` — NOT `docs/performance/`.** `docs/performance/` is git-tracked and flows to the public mirror; it is the *community benchmark* dataset. Runtime telemetry is the user's private operational data (his actual usage cadence) and must never auto-write into a public-synced tree. This is a security decision, not a filesystem convenience. |
| **Air-gap guarantee: config or structure?** | Posture-defining. | **Structural.** The telemetry package imports no network library and opens no socket; the code to phone home does not exist. A gate test asserts the no-network-import property (the "test the lock off" discipline). |

**Path explicitly NOT taken:** a Prometheus `/metrics` endpoint or an OTel/OTLP exporter. Both are the standard answer for a *networked* fleet and the wrong answer for an *air-gapped single-host appliance* — see §5.

---

## 2. Current state — what exists today, and why offline benchmarks are not runtime telemetry

### 2a. The raw numbers already exist per-call; nothing aggregates them

The instrumentation gap is **not** that BlarAI fails to *measure* — it is that every measurement is computed, returned or logged once, and discarded. There is no accumulator, no percentile, no trend.

- **AO generation** (`services/assistant_orchestrator/src/gpu_inference.py`, `_generate_from_prompt`): computes `total_ms` via `time.perf_counter()`, a TTFT figure, and `token_count`, and packages them in `GenerationResult.latency_total_ms` / `latency_first_token_ms` / `token_count`. It keeps two cumulative counters — `_total_tokens_generated`, `_total_requests` — and nothing else. No distribution, no p95, no tok/s trend.
- **PA adjudication** (`services/policy_agent/src/adjudicator.py`): computes a rich per-stage latency breakdown — `rule_engine_ms`, `integrity_ms`, `npu_inference_ms`, `total_ms` — into an `AdjudicationLatency` record, logs it per call, and increments `_adjudication_count`. Again: logged per-call, never aggregated.
- **Shared pipeline** (`shared/inference/shared_pipeline.py`): keeps a `generate_call_count` and serialises PA+AO on one lock. No latency aggregation; lock-wait time is discussed in the docstring but not measured into a series.
- **Governance doctrine already names this a gap.** `docs/governance/observability.md` §6 ("Performance instrumentation") states plainly: *"No steady-state tokens/sec metric is emitted to the log today… Performance-instrumentation is an acknowledged gap."* Its Open-Questions list carries three standing deferrals this design closes or touches: **GOV-12-METRICS-01** (no perf-metrics logger), **GOV-12-HEALTH-PERIODIC-01** (no periodic health probe — "health is sampled only at activation"), and **GOV-12-ROTATION-01** (`launcher.log` appends indefinitely, no rotation).

The AndyStanish System-Qualities audit (`docs/security/AUDIT_AndyStanish_SystemQualities.md`) that spawned #814 confirms the shape empirically: *"grep for `opentelemetry|prometheus|histogram|p95|p99` across `services/`+`shared/` returns nothing… the biggest observability gap,"* and records the current numbers that live **only** in the offline scripts: TTFT 876 ms median, generation 3.59 tok/s, PA 78 ms / 125 ms p95. It also names the Stability motive — two in-memory accumulators in the resident AO that grow monotonically under normal use (their clearing paths exist but are never wired into steady-state), which *no runtime soak metric would catch*.

### 2b. Why the offline benchmark scripts are not runtime telemetry

`scripts/benchmark_*.py` + `docs/performance/*.json` are **point-in-time ceremonies**, not continuous observability:

- They are **human-invoked** (or scheduled) one-shot runs. They load the model, drive a **fixed synthetic prompt set** a fixed number of times, and write one community-grade JSON. Between two ceremonies — which may be weeks apart — the runtime is dark.
- They measure a **controlled lab condition**, not real production load. Real per-turn latency under real session churn, real GPU contention with image-gen evictions, and real memory drift over a multi-hour session are exactly what the ceremony does *not* see.
- `scripts/perf_snapshot.py` is the closest existing thing, and the contrast is instructive: it is still a **manual** script that reads `launcher.log` + the newest `benchmark_*.json` and appends one row to `perf_history.jsonl`. It is a *snapshot-on-demand of already-captured numbers*, not a live in-process aggregator. It cannot catch a regression that happens between the moments a human runs it.

A production regression — RSS creeping 50 MB/hour, p99 first-token drifting from 900 ms to 3 s, an fd leak — is **invisible** in this model until the next ceremony, by which point the cause is cold. That invisibility is the #814 gap.

### 2c. The building blocks already in the tree

Three shipped components make this a *composition*, not a green-field build:

1. **`shared/diagnostics.py`** — `memory_snapshot()` already returns `{sys_total_mb, sys_available_mb, sys_used_pct, proc_rss_mb}`, fail-soft (no-op empty dict when `psutil` is absent), no network. `in_use_mb()` already computes the project's `Total − Available` accounting rule. This *is* the memory sampler primitive; the telemetry layer's periodic sampler calls it.
2. **`shared/diagnostics.py` (#900 half)** — the `reclaim_probe` / `record_reclaim` OFF-by-default pattern and **lesson 279**: *"Instrumentation for 'does X actually happen' must leave X byte-for-byte unchanged when the probe is off… the observer must not move the thing it measures."* This is the exact discipline the collection seam must honour (see §3, §6).
3. **`shared/fleet/flow_metrics.py`** — a deterministic, pure-function, fixture-testable aggregation module (mean, standard deviation, outlier detection over a series, all tz-aware and fail-soft). It aggregates *Vikunja timestamps*, not perf numbers, so it is not reusable directly — but it is the **canonical pattern** the appliance aggregator should mirror: pure functions over supplied data, no I/O, no clock reads inside the math, honest empty-state.

`psutil` handle counting is already exercised in-repo (`tests/substrate_benchmark/harness.py` and elsewhere reference `num_fds`/`num_handles`), so the fd/handle-slope metric has precedent.

---

## 3. Recommended design — a three-layer in-process telemetry layer

A single new module (proposed: `shared/telemetry/`) with three cleanly separated layers. **No layer imports a network library.**

### Layer 1 — Collection (the seam): near-zero-cost, byte-neutral

At the two hot paths that **already compute the numbers**, add a single cheap record call:

- `OrchestratorGPUInference._generate_from_prompt` — already has `total_ms`, TTFT, `token_count` at the point it builds `GenerationResult`. Emit `(surface="ao.generate", total_ms, ttft_ms, tokens)`.
- `Adjudicator.adjudicate` — already has `rule_engine_ms`, `integrity_ms`, `npu_inference_ms`, `total_ms`. Emit `(surface="pa.adjudicate", total_ms, stage breakdown, decision_label)`.

`decision_label` is `ALLOW`/`DENY` — a metadata enum, **never the CAR content or the classified resource**. This is the least-data line: the seam records *shape*, not *substance*.

The record call appends one fixed-width sample to a bounded ring (Layer 2). Appending a handful of floats to a pre-allocated ring is allocation-free and lock-light — cheap enough to run always-on. **The #900 discipline binds it:** the seam must not relocate a load-bearing step to fit a tidy wrapper (lesson 279 — e.g. do not drag a `gc.collect()` under a lock, do not snapshot after the thing moved). Because the numbers are *already computed* at these sites, the seam is a pure append after the existing measurement — it moves nothing. A master flag (`[telemetry].enabled`, default on) gates it; when off, the record call is a single boolean return, byte-neutral by the same pattern `reclaim_probe_enabled()` uses.

### Layer 2 — Aggregation: bounded in-memory, deterministic, pure-function

An in-process registry of **bounded ring buffers**, one per (surface, metric). Two rules keep it from becoming the leak it hunts:

- **Fixed capacity.** Each ring holds the last *N* samples (e.g. 1024). At a few floats per sample this is tens of KB per surface — a constant, not a growth. The aggregator that detects "memory creep" must not itself creep; a fixed ring guarantees that structurally.
- **Compute on read, not on write.** The write path only appends. Percentiles (p50/p95/p99), tok/s (derived `tokens / total_ms`), and mean/stddev are computed **when a reader asks** (dashboard refresh, health verb, rotation timer), over the current ring contents — mirroring `flow_metrics`'s pure-function style. A 1024-element percentile is trivial; it never touches the hot path.

A **periodic sampler thread** (a managed daemon with a stop-event + join, the pattern the substrate idle-monitor already uses) wakes on a bounded tick (e.g. 30–60 s) and records a time-series point into its own bounded ring:

- **In-Use RAM** (`Total − Available`, via the shipped `memory_snapshot()`/`in_use_mb()`) — the scarcest-resource signal, the figure that actually moves on the unified Lunar Lake pool.
- **Process RSS** and **handle/fd count** (`psutil.Process().num_handles()` on Windows / `num_fds()` on POSIX).
- The aggregator computes the **slope** (linear regression over the ring's time-series) so "memory creep" and "fd leak" become a single signed number per window — exactly the audit's "bounded RSS slope" ask.

### Layer 3 — Surfacing & retention: local-only, two faces, no socket

- **Live read (in-memory):** a health/telemetry read that returns the current aggregated snapshot (percentiles, tok/s, slopes, counts). This is the **data source for the #878 operations dashboard's "model-on-GPU / live latency" pane** (see §7). It is served over the **existing internal channel** — an in-process call in host-mode, or the existing vsock/IPC boundary — and **never opens a new listening port**. No `/metrics` HTTP endpoint.
- **Durable trend (append-log):** the rotation timer writes a periodic **aggregated** snapshot as one JSON line to `%LOCALAPPDATA%\BlarAI\telemetry\telemetry.jsonl`, size/day-rotated (a `RotatingFileHandler`-style bound — closing GOV-12-ROTATION-01 for this surface). This is the decades-scale record: months of nightly In-Use slope is how you *see* a leak that is 20 MB/hour. **It is aggregate-only and lives outside the git tree** (see §4).
- **Resilience counters (pairs with AUDIT-14 / #813):** the same in-process registry counts restart/recovery events (e.g. AoReensurer reboots, shared-pipeline reload-after-evict) so MTTR / restart-success gets its missing proxy from the one layer — the audit's "one gap serves three dimensions."

---

## 4. Air-gap & privacy security analysis

This is a **runtime** artifact, so it binds to the runtime rulebook: fail-closed, deny-by-default, defense-in-depth, structural absence, least-data, fail-loud, tested-off. The design was reasoned to the security-by-design principles *first*.

**Trust boundary named:** the telemetry layer sits entirely *inside* the appliance. It reads process/system counters (its own RSS, system available memory) and the perf numbers the services already compute. It writes to one local file and answers one local read. It touches **no untrusted input** and crosses **no network boundary**.

**The air-gap guarantee is structural, not configured (principle 4 — structural absence over configuration):**
1. **No network client exists in the path.** The telemetry package imports no `socket`, `http`, `requests`, `urllib`, OTel/Prometheus client — nothing that can open a connection. It *cannot* phone home because the capability is not present in the code, not merely disabled by a flag. This is the strongest dormancy the doctrine recognises.
2. **The live read reuses an existing internal channel.** It adds no listening socket. In host-mode it is an in-process method call; across the VM boundary it rides the existing vsock IPC. There is no new reachable surface and nothing bound to a TCP port that a config typo could expose on `0.0.0.0`.
3. **The durable sink is a local file** under `%LOCALAPPDATA%`, owner-DACL'd like the other runtime data files.

Three independent locks; no single mistake opens a network door (principle 3 — defense-in-depth).

**Least-data / metadata-only (principle 8), which subsumes born-encrypted (principle 6):** the telemetry is *numbers* — latencies, counts, RSS, slopes, an ALLOW/DENY enum. It records **no** prompt text, **no** response text, **no** classified resource string, **no** session content. This satisfies the born-encrypted principle by *non-collection*, which is stronger than encryption: there is no plaintext-bearing content to protect, so there is no decrypt point to defend. The one guardrail that keeps it that way: the durable log is **aggregate-only** — it stores distributions and slopes, not a per-turn or per-session row keyed to an identifier. (A per-session latency table would begin to reconstruct a usage timeline; the design deliberately does not build one. If a future need for per-session drill-down appears, that is a *new* privacy decision for the LA, not a default.)

**Why the durable log must not live in `docs/performance/`:** that tree is git-tracked and flows through the local→private→public sync pipeline to the public mirror. It is the *community benchmark* dataset — synthetic-prompt lab runs the user chose to publish. Runtime telemetry is the opposite: the user's **private operational data** (when and how much *he actually uses his own assistant*). Auto-writing that into a public-synced tree would be a privacy leak by filesystem accident. Runtime telemetry lives under `%LOCALAPPDATA%`, never in git. (This is the load-bearing reason the location is an LA decision, not a convenience.)

**Fail-loud & fail-soft in balance (principles 1, 11):** telemetry is an *observer*, so its own failures must never break a request — a `psutil` hiccup or a full disk degrades the probe to a no-op, exactly as `memory_snapshot()`/`reclaim_probe` already do; the instrumented service path is never taken down by its instrumentation. That is fail-**soft** for the observer, and it is correct here precisely because telemetry is not itself a security control. (The fail-**loud** obligation lands one level up: if the layer detects a bounded-slope breach — a real leak — that alarm must surface on the dashboard, not be swallowed.)

**Tested-off (principle 12):** ship two locks-proving tests — (a) a gate test asserting the telemetry package imports no network module (the structural air-gap, proven by the absence being enforced, mirroring the egress-lock discipline); (b) a byte-neutral test proving the instrumented hot paths are unchanged when `[telemetry].enabled=false` (the #900 pattern — instrumented-vs-not produces identical `GenerationResult`/`AdjudicationContext`).

---

## 5. Alternatives considered

### 5a. Prometheus `/metrics` endpoint — REJECTED

The industry-default for service metrics. It exposes an HTTP endpoint a Prometheus server *scrapes*. That is **a listening socket inside the runtime** — a new reachable network surface, on an appliance whose entire posture is deny-by-default egress welded behind an LA ceremony. Even bound to `localhost`, a listening socket is one config edit (or one bind-address bug) away from being reachable, and it is exactly the kind of "side door" the single-adjudication-door principle (5) forbids. It also presumes an external Prometheus/Grafana stack — infrastructure BlarAI does not run and would have to add. **Local-only wins:** the in-process ring gives the identical observable (percentiles, slopes) with zero network surface, and BlarAI's dashboard is #878 (in-process WinUI), not Grafana — so nothing is actually lost.

### 5b. OpenTelemetry / OTLP exporter — REJECTED

Worse than Prometheus for this context: an OTLP exporter is an **outbound** network client — a literal phone-home to a collector. That is the precise failure mode the two-tier rulebook exists to prevent (leaking the workshop's networked assumptions into the product). The OTel SDK's in-process API is elegant, but its reason-for-being is *export*, and importing it drags a network-capable dependency into the runtime for no local-only benefit. Structural absence beats a disabled exporter.

### 5c. Reuse the audit-log / segment infrastructure as the sink — PARTIALLY, not as designed

Option (b) in the #814 comment. The audit-log rotation machinery is good prior art for *rotation* and the design borrows its bounded-file discipline. But the audit log is a **security-evidence** surface with its own schema and retention meaning; overloading it with high-frequency perf samples would muddy an audit trail whose integrity matters, and couple two independently-evolving concerns. Recommendation: **reuse the rotation *pattern*, keep a separate telemetry sink.** Perf trend and security evidence are different data with different lifetimes.

### 5d. Periodic snapshot to `docs/performance/` on a timer — REJECTED as the primary sink

Option (c) in the #814 comment. Rejected for the privacy/public-sync reason in §4: `docs/performance/` is public-mirror-bound and is the community dataset, not private operational data. A local rotated log under `%LOCALAPPDATA%` is the right durable sink. (The *community* benchmark ceremonies keep writing to `docs/performance/` exactly as today — that is a separate, deliberately-published surface.)

### 5e. Do nothing / keep relying on offline ceremonies — REJECTED

The status quo. For a decades-lived appliance this is a standing blindness to gradual degradation (the audit's core finding). The whole value of the investment is catching the *slow* failure — the creep no single benchmark run reveals.

---

## 6. What needs measuring or prototyping (name the unknowns)

Per the performance-capture rule, the design carries measurable claims that must be *measured*, not assumed:

1. **Hot-path overhead of the collection seam — must be ~0.** Measure `GenerationResult`/`adjudicate` latency with `[telemetry].enabled` true vs false over a real run; confirm the ring-append delta is within noise. This is the #900 instrumented-vs-not discipline applied to the new seam. *(This is the single most important prototype: the layer is only justified if it is genuinely near-free.)*
2. **Windows handle-count surface.** Confirm `psutil.Process().num_handles()` on this build/host (Windows exposes `num_handles()`, not `num_fds()`); confirm it moves when handles leak. Precedent exists in `tests/substrate_benchmark/harness.py`.
3. **Ring sizing vs the slope signal.** What *N* and what sampler tick give a slope estimate stable enough to alarm on a real leak without false-alarming on normal variance? Prototype against a seeded synthetic leak (an intentionally-un-cleared dict) and confirm the slope crosses a threshold.
4. **Percentile-on-read cost at dashboard cadence.** Confirm p50/p95/p99 over a 1024-ring is trivial at the #878 refresh rate (near-certainly yes; verify, don't assume).
5. **Slope window / alarm threshold.** What time window defines "creep," and what signed slope trips the fail-loud alarm — an empirical calibration, likely refined after the first multi-hour soak with the layer live.

## 7. Fit with #878 (dashboard) and #855 (composed work-state)

- **#878 operations dashboard** is the primary consumer. Its "diagnosed gap" is that Vikunja is a *work board*, not a *control room* — it cannot show "model-on-GPU, live run phase, last latencies." This telemetry layer **is the data source for that pane**: `compose_work_state` (already built, #843) feeds the dashboard its *fleet/coordinator/board* state; this layer feeds it the *appliance perf/health* state (p95 TTFT, tok/s, In-Use slope, fd count). They are two complementary data sources behind one read-only dashboard — the dashboard observes, never acts, same severance as the coordinator. Recommend the live-read snapshot be shaped to slot directly into the dashboard's render model.
- **#855 composed work-state / shadow graduation** is a lighter touch: the appliance health snapshot can be *included* in the composed work-state the coordinator consults (so "is the box healthy right now" is one more signal alongside the flow metrics), but it is not on #855's critical path. Note it; do not couple the two builds.
- **#900 (lesson 279)** is the governing precedent for the collection seam's byte-neutrality — cited throughout §3–§4.

---

## Residual unknowns for the LA (plain language)

1. **On-by-default is a quality/behaviour call.** I recommend on (it is near-free and the point of the investment), with a kill-switch. If you would rather it ship dormant and be flipped at a ceremony like other new capabilities, that is a one-line default change — say the word.
2. **Aggregate-only vs per-session drill-down.** The design deliberately stores only distributions, never a per-session usage timeline, because the latter starts to reconstruct *when you use your assistant*. If you ever want per-session drill-down on the dashboard, that is a new privacy decision to make deliberately, not a default to slip in.
3. **Fleet vs appliance scope (still open from 2026-07-11).** This study is the appliance track only. Whether AUDIT-15 also funds the headless-coding-fleet telemetry surface is still your scope call.
