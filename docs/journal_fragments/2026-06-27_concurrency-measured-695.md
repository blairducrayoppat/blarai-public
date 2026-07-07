### 2026-06-27 — Measuring the ceiling instead of guessing it (best-of-N concurrency, #695)

#689 shipped best-of-N sequentially on purpose, with a promise attached: the solve-rate win
(independent samples fed to the gate we already own) is orthogonal to parallelism, so prove the
solve-rate first and MEASURE whether the integrated Arc 140V can actually run candidates
concurrently before building for it. The research said OVMS continuous batching is real on Intel
Arc and Core Ultra, but it also said the honest thing: the concurrency ceiling on an INTEGRATED
GPU — shared LPDDR5X, no discrete VRAM — is undocumented. You do not predict that number. You
read it off the box.

So I read it off the box. Firing N identical `/v3/chat/completions` requests at the resident
Qwen3-Coder-30B-A3B (INT4) and watching the OVMS `llm_executor` log tick through
`All requests / Scheduled requests / cache usage %`, three things came clear. Continuous batching
genuinely engages — OVMS scheduled up to seven-to-eight sequences at once and aggregate throughput
rose 1.87x at four concurrent and 2.37x at eight. The KV cache is NOT the binding constraint, and
that surprised me until it didn't: eight concurrent 6,675-token contexts — a realistic agent-sized
prompt — cost only 10.5% of the 4 GB pool, because `enable_prefix_caching` stores the SHARED
best-of-N prompt exactly once and `u8` halves the KV bytes. The thing that was supposed to be the
wall is almost free for this workload precisely because best-of-N candidates share their prompt.
What DOES bind is compute: the integrated GPU saturates around 40-90 tok/s aggregate, so the
speedup is real but sub-linear and per-request latency climbs with N (5.1 s to 17.2 s at eight).
The net for best-of-N is a \~1.9x-to-2.4x cut in wall-clock-to-best-result, cache-cheap, with
little to gain past about four concurrent.

That is a clean, favorable answer to the question #695 was created to ask — parallelism is
possible, and the constraint is the GPU's compute, not its memory. It is also community-grade
OpenVINO data (hardware, server config, model precision, methodology, and what was NOT measured
all recorded), which is half the point of running it on this particular box.

The honest boundary is the part I did NOT rush. Turning this measurement into a running feature
means concurrent candidates in SEPARATE git worktrees and a real restructure of a harness that is
deliberately one-active-agent today — the ticket itself calls it "a large change," and the DoD
reserves the decision to DEFAULT concurrency above one for the operator, because running several
multi-minute agent process-trees at once is a resource posture, not a mechanical flip. The wrong
move here would be to cram a concurrency feature into the tail of a long session and ship something
subtly wrong into the live dispatch the operator prizes for its reliability. So the measurement,
the recommendation, and the design are delivered; the build is surfaced as the operator's
go/no-go with its number attached.

**Next:** the recommendation on the record — wire concurrency as a config knob defaulting to C=1
(today's exact sequential behaviour, untouched), build the concurrent path ADDITIVELY so the
sequential dispatch is byte-identical, prove one live C=2 dispatch (two candidates → gate-selected
merge), and propose C=2-3 as the production default for the operator to approve. The measurement
says the box can hold it; the operator says when to turn it on.

**Proposed lesson:** *On integrated hardware, measure the ceiling — and find the real constraint,
which is rarely the obvious one.* The KV cache was the predicted wall for best-of-N concurrency; on
this box, prefix-caching the shared prompt made it a non-issue and compute became the limit
instead. And when the measured next step is a large change to a reliability-critical harness with a
resource-posture default, the mature delivery is the measurement plus a recommendation with a
number, not a rushed feature — the operator owns the turn-it-on call by design.

*(commits: blarai `<this>` (the community-grade measurement: `PERFORMANCE_LOG.md` entry +
`docs/performance/dispatch_concurrency_arc140v_2026-06-27.json`); measured on the Arc 140V
2026-06-27 — continuous batching 1.87x @ N=4 / 2.37x @ N=8, KV cache 10.5% @ 8×6.7K-token contexts,
compute-bound. The concurrent-execution build is the operator-gated next step under #695.)*
