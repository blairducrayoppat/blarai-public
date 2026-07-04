### 2026-06-29 — The benchmark that copied production's homework

A sibling perf agent ran a long-context KV-cache precision sweep and got
numbers that looked like data but weren't: time-to-first-token of 47 seconds at
16K context and 310 seconds at 32K, two repeats apart by the better part of a
minute, and a memory column that sat flat at ~20.85 GB no matter whether the KV
cache was FP16, INT8, or INT4. A sweep built to measure the precision lever was
measuring nothing of the sort. It surfaced to me as "is this being tracked?" —
and the honest answer was that it shouldn't be *published*, because every number
in it was an artifact.

The cause was a single line the harness inherited without thinking: it copied
the production `SchedulerConfig`, `cache_size = 3`. Three gigabytes of KV budget
is exactly right for the short conversational turns BlarAI actually serves, and
exactly wrong for a 32K-token prompt. The arithmetic is unforgiving — Qwen3-14B
carries 160 KiB of KV per token at FP16 (2 x 40 layers x 8 KV-heads x 128
head_dim x 2 bytes), so a 32K context needs 5.0 GiB. It does not fit in 3, and
when it doesn't fit, the continuous-batching scheduler evicts blocks and
recomputes prefill — which is precisely the 10x-too-slow, wildly-variable TTFT
that showed up. The flat memory was the same bug wearing a different hat: a fixed
3 GiB pool is pre-reserved regardless of precision, so the precision lever could
never move the needle the harness was watching.

I didn't patch the original — it existed as no file in any repo, an ephemeral
script the sibling ran inline. So the fix was to author the thing properly:
`scripts/benchmark_kv_cache_sweep.py`, a standing harness that sizes `cache_size`
per (precision, context) from the analytical KV requirement instead of a
production constant, rebuilds a fresh pipeline between every combo, warms at the
real context length, and runs N>=5 with a reported median. The proof came on the
exact case that was pathological: 32K FP16 went from **310,715 ms to 175,725 ms
with a std of 217 ms** — the two repeats landed within 0.4 seconds of each other.
That stability is the tell. The remaining 176 seconds isn't slowness to chase;
it's the genuine O(n-squared) cost of a 32K cold prefill on an iGPU. The eviction
thrash is simply gone.

Two smaller lessons paid for themselves in the same session. The first run of my
own harness reported TTFT of -1: I'd reached for `perf_metrics.get_ttft()`, but
`generate(..., streamer=cb)` returns a bare `str` with no metrics attached, while
the streamer callback fires perfectly well on the no-draft continuous-batching
backend (the "CB doesn't stream" caveat in the repo only bites the *speculative*
path). A one-load probe — not a guess, not a series of expensive full runs —
settled it in ninety seconds. The second: the GPU memory does read out, just not
where I first looked. On this shared-LPDDR5X iGPU the allocations land in
`cl_mem` (the reserved KV pool, which tracks `cache_size` to the byte) and
`usm_host` (weights plus buffers); `usm_device`, the discrete-GPU field, stays at
four megabytes forever. I'd been headlining the one field guaranteed to be empty.

The invalid run wasn't deleted. It's quarantined under
`docs/performance/_invalid/` with an in-file `validity` block and a README that
says why — the record of how a measurement went wrong is worth more kept than
erased, and the community dataset must never harvest it.

Then the full sweep tried to teach me the wrong lesson twice, and both times the
operator or the data caught me. The first full run came in with the browser open
— a few tabs sharing the same iGPU inflated TTFT ~31% and blew variance up 25x.
The operator flagged it; a cleanliness gate (compare the first combo to the
isolated smoke) confirmed it and the re-run cleaned up. The second was subtler and
entirely mine: a clean sweep still showed 16K times *climbing* with run-order
(FP16 49s, then INT8 121s, then INT4 135s) and 32K reading 315s where the isolated
smoke had read 176s. I called it thermal throttling from cumulative heat, quarantined
the run, added an inter-combo cooldown — and then the steady-state warm-up ramp
showed the opposite: from cold the chip ran *slow* (131s) and got *faster* (46s)
as it warmed. Throttling gets slower under load, not faster. My "residual heat"
story was wrong; the real effect was a cold GPU coming out of idle — the iGPU
downclocks hard, and the first heavy prefill or two pay a clock-ramp + first-run
compile tax before snapping to the warm plateau. I had stated the thermal theory
with more confidence than the evidence carried, and the ramp is the clean
experiment that refuted it.

What survived is a genuinely two-part thermal story on a fanless chip: a cold-start
ramp (fixed by warming to a TTFT plateau before measuring) and a real
self-throttle during the very long 32K prefills (TTFT drifts up mildly within the
combo). Measuring every precision back-to-back at the same hot plateau finally gave
a fair comparison — and a clean result. At 16K, compute-bound, KV quantization is
slightly *slower* (dequant overhead): FP16 45.8s, INT8 46.8s, INT4 51.5s. At 32K,
bandwidth-bound reading a 5 GiB KV cache every step, quantization is a big *speed*
win: INT8 159s is 2.3x faster than FP16's 369s. INT8 is the sweet spot — INT4
saves the most memory but its 4-bit dequant cost lands it slightly slower than INT8
(174s). That non-monotonicity is the tell that this is a compute/bandwidth
tradeoff, not thermal. The memory lever is the whole point and it is clean: INT8
halves, INT4 quarters the KV footprint.

**Next:** the KV-precision memory + speed characterisation is landed in
`PERFORMANCE_LOG.md`; the one thing not instrumented is GPU frequency/temperature/
power, so the 32K bandwidth-vs-any-residual-thermal mechanism is strongly indicated
but not measured — ticketed as a follow-up UT (Intel Unified Telemetry) pass
reusing `scripts/capture_single_ut.ps1`. Close #709.

**Proposed lesson:** *A benchmark harness must not inherit production config it
doesn't understand.* The starving `cache_size=3` was correct for the runtime and
catastrophic for the measurement; the harness copied it because copying is
easier than deriving. Size the knobs that bound a measurement from the
measurement's own regime, and when a result is both slow and high-variance,
suspect the harness before the hardware. Pairs with the standing rule that
unrecorded — or mis-recorded — test results are an incomplete task.

**Proposed lesson:** *On a fanless chip, define the thermal state before you
trust a latency number.* A slow first measurement is a cold clock, not residual
heat (the warm-up ramp gets faster, not slower); a slow sustained measurement can
be genuine self-throttle. Warm to a plateau and measure everything at the same
state, or the run-order confound will masquerade as a real effect — and don't
narrate a thermal mechanism with more confidence than a temperature trace you
haven't captured.

*(commits `<this>` (harness + steady-state protocol + 27 unit tests; standing gate
green 4658/0; steady-state sweep: 16K FP16/INT8/INT4 = 45.8/46.8/51.5s, 32K =
368.9/159.0/174.5s; superseded runs quarantined). UT freq/temp/power pass ticketed
as follow-up.)*
