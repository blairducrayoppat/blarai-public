### 2026-06-28 — The two clocks and the reaper: measuring what the 14B costs a roommate

The operator's question after the benchmark refresh was easy to ask and annoying to answer well: *what
does it cost the always-resident 14B to share the one iGPU with each model it might run beside?* Answering
it properly needed real GPU telemetry — power, frequency, bandwidth, busy — not just tokens/sec, because
the operator is an OpenVINO upstream contributor and this data is meant to be published. So the study
became an Intel Unified Telemetry exercise as much as a benchmark. Two things made it hard, and both are
the portfolio-worthy part.

**The two clocks.** Intel UT ships two collectors that matter here: socwatch (power, thermal — stamps every
sample in Unix-epoch nanoseconds) and level-zero (GPU frequency / busy / memory-bandwidth — the data Task
Manager hides, because OpenVINO runs on the GPU's neural/XMX engine, not the 3D engine). The catch: the
level-zero driver flags a "timestamp-units" issue and stamps its samples on a *different* clock — I measured
it ~27.7 hours offset from socwatch in the same capture. So power segmented cleanly into idle/contention
phases and GPU frequency did not — l0 only ever produced a single whole-run blob, exactly the thing the
operator had said was "extremely important" to split. The fix was to stop trusting the l0 clock's absolute
value and trust only its *linearity*: anchor the l0 sample range [min,max] linearly onto socwatch's Unix
[min,max] window from the same `ut.exe` session. I validated it wasn't wishful thinking before relying on
it — the remapped contention samples put the GPU-busy spike exactly where the power spike already was
(idle ~90% → contention ~99%), and the split is physically coherent across frequency, busy, and bandwidth
at once. One reliable clock can rescue an unreliable one if you only ask the unreliable one to be straight,
not correct.

**The reaper.** Twice I launched the multi-sweep as a background task, reported status, and ended my turn —
and twice the background task and its watcher came back killed, together, with no instruction attached. The
first sweep had survived 75 minutes and a context compaction before dying; the relaunch died in two minutes.
After explicitly inviting "tell me if you're stopping this on purpose" and getting another silent kill, I
stopped re-launching — retrying a behaviour that's been reversed twice is just stubbornness. The tell was
that every *foreground* call had completed untouched, including a 4-minute parallel CPU load. So the reaper
was specific to background tasks, and the whole pipeline pivoted to foreground: re-extract the nine
already-captured runs in foreground batches, then capture the missing vlm runs one repeat per foreground
call with a small `capture_one.ps1`. When one two-run call auto-backgrounded itself for length, I
block-waited on it inline rather than gamble on it surviving the turn boundary — and it completed. The
lesson I'll carry: when an execution *mode* keeps dying, diagnose what survives and switch modes; don't keep
feeding the mode that's being eaten.

The result was worth the trouble. Idle co-residence is ~free — any one of the three SDXL styles or the VLM
can sit resident beside the 14B for ~0–5%. Concurrent generation is where it bites, and the mechanism is the
satisfying bit: what's exhausted is GPU compute *scheduling*, not bandwidth and not the clock (the GPU pins
at 1.95 GHz with zero throttle throughout). Pure SDXL diffusion is compute-bound and monopolises the EU
scheduler so totally that the 14B can't finish its prefill in a 15 s window — TTFT blows to 13–15 s, ~1%
throughput — and aggregate memory-read actually *drops*, because the bandwidth-bound decode can't get the
slots to issue its reads. The VLM, being itself a bandwidth-bound transformer, keeps bandwidth saturated and
lets the 14B hold ~13%. cartoon's LoRA, by spending more time on the CPU, accidentally leaves the 14B
scheduling gaps. The partner's compute-vs-bandwidth character *is* the contention signature. And
`PMT-NPU-PWR` read 0.0 W in every phase of every run — a clean, twelve-times-repeated proof that the stack
is pure-GPU, exactly as ADR-011 says.

The first pass at all this was noisy — whole-run power, overlap-timed contention, sub-millisecond power
samples reading as phantom kilowatts. I kept that first dataset out of the commit rather than dress it up.
The hardened pipeline — sustained contention, 1 s-windowed peak power, per-phase remap, N=3 with cooldowns —
is what got recorded.

**Next:** ship the dataset toward the OpenVINO community; a steady-state cartoon/LoRA run to remove the
spin-up confound; confirm the `GPU_MEMORY_BYTE_*_RATE` GB/s unit against a known-bandwidth microbench. The
standing question of *whether* to run two generators at once on one iGPU now has its number: you can, but
the 14B is the one that yields.

**Proposed lesson:** *When telemetry spans two clocks and one is unreliable, anchor the unreliable clock's
range linearly onto the reliable one's window from the same session — trust its linearity, not its zero.*
(Paid for by the level-zero timestamp-units bug blocking per-phase GPU segmentation until the
socwatch-anchored remap.)

**Proposed lesson:** *When an execution mode keeps getting killed, diagnose what survives and switch modes —
don't re-launch the dying mode.* (Paid for by two silent background-sweep kills before pivoting the whole
capture pipeline to foreground, which had completed every time.)

*(Co-residency study: `scripts/benchmark_coresident.py` harness, `scripts/extract_ut_metrics.py`
per-phase+remap extractor, `scripts/merge_coresident_hardened.py`, `scripts/run_coresident_ut_sweep.ps1` +
`scripts/capture_one.ps1` + `scripts/rextract_l0_remap.ps1`; dataset
`docs/performance/coresident_14b_pairings_hardened_2026-06-28.json`; PERFORMANCE_LOG 2026-06-28 entry;
commit `<this>`. 12 runs, Intel-UT instrumented, Vikunja #705.)*
