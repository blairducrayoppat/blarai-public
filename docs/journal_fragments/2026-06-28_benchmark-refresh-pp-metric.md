### 2026-06-28 — The MoE bargain, and the pipe I'd been warned about

The deferred (a) benchmark refresh finally had its hardware. I re-measured all three of the
models the box actually runs — the 14B assistant, the 8B, and the coder 30B — five measured
runs plus two warmup each, thermal cooldown between runs, on the current stack, and for the
first time with the prefill-throughput (pp) metric I'd built and unit-tested a day earlier but
never run on silicon. The numbers were good and a couple were genuinely informative. The 14B
with speculative decoding came in at a median 17.1 tok/s, up from the 13.6 we recorded back in
May — the tuned pruned-6L draft on the newer stack is worth a real 1.5x over standard decoding,
and it firmly fills the datapoint the community simply does not have (there is no trustworthy
14B-on-GPU figure out there; the one public "14B" number is almost certainly CPU). The 8B took
the same 0.6B draft to 27.4 tok/s. Nice, but expected.

The interesting result was the shape, not any single number, and it only became visible because
pp now sits next to generation throughput. The 30B-A3B is a mixture-of-experts model: ~30B total
parameters, ~3B active per token. It posted the fastest decode of anything I measured (38 tok/s,
roughly double the dense 14B) and the fastest time-to-first-token (214 ms) — and the *slowest*
prefill of anything, pp ~480 against the dense models' ~1960. That is the MoE bargain stated in
two measured numbers: decode only wakes ~3B of active params, so tokens are cheap; but prefill
routes every prompt token across all 128 experts, so reading the prompt pays the full ~30B. The
dense 14B and 8B are the mirror image — heavier per-token decode, featherweight prefill. I have
been describing MoE this way in the abstract for weeks; it is a different thing to have it fall
out of a benchmark you can hand to someone. I was careful not to oversell it: the in-process pp
is measured over ~970 chat-formatted tokens and the OVMS pp over ~421 bare ones, on two different
OpenVINO versions, so I wrote the comparison up as directional and named every confound rather
than implying a clean A/B. The 4x prefill gap is far larger than the confounds, so the finding
stands, but the honest framing is the one that compounds.

Then the part that belongs in here precisely because it went wrong. Bringing up the 30B means
starting OVMS through the fleet's `start-llm.ps1`, and I piped that launch through `Tee-Object` so
I could keep its output. It hung. Not the model — the model loaded and was serving `coder-30b` on
:8000 within ninety seconds, exactly as designed — but my *wrapper* never returned, so the harness
never got its "done" signal, and I sat waiting on a notification that could not come. It cost the
whole night. The bitter detail: the mechanism is documented, in this repo, in the file I had read
an hour earlier. `swap_ops.py` spells out the #670 deadlock — start-llm spawns long-lived
grandchildren (OVMS, the proxy) that inherit a captured stdout pipe on Windows, so the pipe never
reaches EOF and the wait blocks forever after the work is already done — and it works around it by
redirecting to a real file, never a pipe. I read that, understood it, and then reached for
`Tee-Object` anyway. Recovery was quick once I stopped waiting and looked: process list, port
check, and the start-llm log all agreed OVMS was healthy, so I ran the benchmark straight against
the live server, got clean numbers, then tore the server down and reaped the hung wrapper. The
lesson is not "Tee-Object is bad." It is that reading a hard-won lesson is not the same as applying
it, and the moment to apply this one is any time I capture the output of a script that spawns
servers — redirect to a file, or run it detached and poll the readiness endpoint, never hold its
pipe.

**Proposed lesson:** *Never capture a server-spawning launcher's output through a pipe (Tee-Object,
captured stdout).* Its long-lived grandchildren inherit the pipe handle on Windows and it never
reaches EOF, so the wait hangs forever after the server is already up — the #670 deadlock, which
the codebase already solved with file-redirection. Redirect to a file or poll the readiness
endpoint; the launcher's own exit is not a reliable signal when it leaves children holding the pipe.

**Next:** fold this fragment into BUILD_JOURNAL.md at the next quiet point; the pp metric and the
OVMS-HTTP harness are now both hardware-proven, so future refreshes are a single command per model.
The natural follow-on is a co-resident measurement — every number here was taken with the model
alone on the GPU, and the question the dataset cannot yet answer is what the assistant 14B costs
when something else is resident beside it.

*(commits `<this>` (pp metric + OVMS-HTTP bench + 2026-06-28 measurement entry, comparison-JSON
refresh, this fragment); 14B/8B via `benchmark_gpu_inference.py`, 30B via new `benchmark_ovms_http.py`;
+18 OVMS-bench unit tests; 3 result JSONs under docs/performance/.)*
