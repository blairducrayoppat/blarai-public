### 2026-07-10 — Probe, don't predict: ending the 20-vs-18 argument for good

*Plain summary: added `tools/dispatch_harness/probe.py` (`python -m tools.dispatch_harness.probe`) and reworked the battery night launcher's LEAN PREFLIGHT so that in the marginal RAM band it attempts a real 30B load OUTSIDE any job instead of admitting the night by arithmetic; #784.*

The LA put it plainly: the arithmetic swap gate was "an unnecessary
constraint that adds no value." He was right, and the shape of why is worth
keeping. The battery launcher admitted a night by *predicting* — it summed the
current Available RAM with the ~8.7 GiB the resident 14B gives back when the AO
steps aside, and proceeded only if that projection cleared a threshold (20.5
GiB = the swap driver's 20.0 gate plus margin). The #777 measurement then proved
a clean 30B load from **19.85 GiB** available. So there is a dead band — roughly
19.85 to 20.5 — where the launcher would wait all night, on 30-minute retries to
04:00, on a load that would have worked. Worse than idle: a burned night.

The tempting fix is to argue the threshold down — 20, then 18, then 17.5 as each
measurement lands. But every one of those numbers is a *proxy* for a fact we can
just observe. The threshold argument never ends because prediction is the wrong
instrument. So the gate now probes reality: in the marginal band it fires
`probe.py`, which stops the AO, attempts the real 30B load once, waits for it to
serve, and — always, in a `finally` — restores the AO. Load serves within the
deadline → run the night. Load fails → clean up and rejoin the retry loop. A
probe-over-threshold ends the argument permanently: the only question that ever
mattered was "will it load," and now we ask *that*, not a stand-in for it.

Two trade-offs went on the record. First, the **double load**: a probe that
succeeds loads the 30B, tears it down, and the night's first job loads it again
(~13 s warm). The alternative — hand the already-loaded 30B to job 1 — was
rejected: it would mean the probe reaching into the AO-mediated dispatch flow the
driver owns, fighting the step-aside/relaunch choreography for a 13-second
saving. A clean, stamps-nothing probe that the driver never has to know about is
worth one warm reload. Second, the **below-floor cutoff stays at 15 GiB** — but
now as a *sanity bound*, not a prediction. Below 15 GiB Available the box is
genuinely starved and the probe refuses to even try (exit 3, zero side effects);
above it, we measure rather than guess. 15 is a floor on "is it worth attempting,"
not a claim about "will it succeed" — that claim is the probe's job.

The load-bearing discipline was **side-effect containment** (lesson 224). The
probe runs OUTSIDE any job, so it must stamp *nothing* — no swap-state phase, no
scorecard, no fleet sentinel — or a probe attempt could be mistaken for a run and
poison the night it was meant to protect. Every side-effecting step reuses an
audited leg (`real_load_30b`, `real_stop_ovms`, `boot_launcher_detached`,
`real_backend_ready`, `procspawn.terminate_process_tree`); the probe adds no new
subprocess op. I audited each: none writes shared swap-state when called outside a
`SwapDriver`. The one wrinkle is stopping the AO. The driver *never* kills the AO
— in a real swap the AO steps aside by exiting itself and the driver merely waits
on its PID. The probe can't trigger that in-process step-aside on a separate live
AO, so it finds the launcher by its single-instance lock (`certs/launcher.lock`,
the authoritative pid), CONFIRMS the pid is genuinely a `-m launcher` (never a
recycled stranger), and tree-kills it. A forceful stop skips the launcher's
graceful cleanup and leaves a stale lock — exactly the driver's own `os._exit`
step-aside residual, which the next detached boot reclaims. I did NOT default the
probe's timeout to a fresh number: it reuses the already-registered
`START_LLM_TIMEOUT_S` (480 s), so no new timeout entered the registry.

Built and proven offline only: 12 injected-seam unit tests over the pure
`run_probe` (happy / load-fail / below-floor-touches-nothing / exception-mid-load
/ KeyboardInterrupt-abort / restore-raises-but-exit-preserved / --json shape /
timeout-reuse), the timeout-registry gate still green, and a live below-floor CLI
smoke (floor 999 → exit 3, measures RAM, touches nothing). The real load probe —
the thing that actually stops the AO and loads the 30B — is deliberately left to
the daylight verify: it is a live surface, and the battery owns the box overnight.

**Next:** in daylight, with the box idle, run `probe.py` for real once (watch it
stop the AO, load the 30B, restore the AO), confirm the JSON outcome + timings,
record the load seconds community-grade in `PERFORMANCE_LOG.md`, then merge both
branches and let the first probe-admitted night run.

**Proposed lesson:** *When a gate predicts a measurable outcome, replace the
prediction with the measurement.* An admission test that computes a proxy
(projected headroom) for the real question ("will the load succeed") will always
invite an argument about the proxy's threshold; attempting the real thing once,
outside the protected path and always-restoring, ends the argument and closes the
dead band the proxy created. The cost to weigh is a bounded double-cost (here, one
warm reload) against the bankability the real signal buys.
