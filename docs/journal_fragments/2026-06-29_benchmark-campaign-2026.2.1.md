### 2026-06-29 — The upgrade that didn't speed up generation, and the browser that faked a regression

The job was narrow and the discipline was the point: re-measure the whole model
matrix on the freshly-upgraded OpenVINO 2026.2.1 stack under the *exact* committed
2026.1.0 methodology, so the numbers are directly comparable and publishable. Same
prompts, same 5+2 runs, same 30-second cooldowns, same driver held constant. The
comparability is the entire value — change the harness and the comparison evaporates.

The first real lesson arrived disguised as a crisis. The very first 2026.2.1 run of
the 14B read spec-on generation at 14.6 tok/s — a 14% drop from the baseline's 17.1
— while spec-off stayed flat. That is exactly the shape of a version regression in
the speculative-decoding path, and I very nearly wrote it up as one. I didn't,
because the rule is verify-before-escalating: a 14% drop on the production path
earns a confirmation run, not a headline. The operator then supplied the missing
variable — he'd had browser windows open during that first run and not during the
baseline. That reframed everything. Speculative decoding is compute-scheduling-
bound; the draft and target both contend for the iGPU's Xe scheduler, so a
background browser compositor nibbling GPU scheduling knocks \~14% off spec-on while
leaving the steady autoregressive path untouched. The clean re-run on a dedicated
machine restored spec-on to 17.2, dead-on the baseline. The "regression" was an
environment artifact — and a free, accidental corroboration of the co-residency
study's central claim that the exhausted resource on this iGPU is compute
scheduling, not bandwidth. The lesson I'm keeping: a single background GPU client
can perfectly impersonate a runtime regression, and the only defense is measuring
the environment, not just the model.

The headline finding is a study in why a single up-or-down number lies. Generation
throughput is a **no-op** across the version bump — 14B \~17 tok/s, 8B \~27, 30B \~38,
all flat. If that were the whole story the upgrade would look pointless. But a
dedicated prefill harness — built this session, multi-length, multi-repeat, cold
prefill — showed prompt *processing* is \~30%+ faster on 2026.2.1 (14B at 512 tokens
595 → 761 pp; 8B 1086 → 1477), and the Qwen3-VL TTFT is \~19% faster. The bump
doesn't speed up writing tokens; it speeds up reading the prompt and the vision
model. That nuance is the contribution. It also vindicated a methodology instinct:
the old single-shot prefill probe had screamed "8B prefill doubled," which was
noise; only a proper A/B in a back-to-back version window separated the real \~30%
win from the probe's variance. The operator made the prefill harness a permanent
part of the baseline on the strength of that.

Two findings earned their keep by being honestly negative. CPU-draft speculative
decoding — the tempting "free the GPU" idea — is a clean loss on unified memory:
identical token acceptance (the draft device can't change *which* tokens a greedy
pair accepts, only how fast), \~13% slower, and the telemetry shows it just shifts
draft compute off the graphics rail onto the CPU package for more heat and less
throughput. And the KV-cache precision sweep, the one I most wanted to deliver a
memory win from (INT4 KV could let the hires-SDXL path stop evicting the 14B),
produced a null I had to report as a null: peak shared-RAM was flat to two decimals
across FP16/u8/u4 and across 16K/32K context, which is the unmistakable signature
of a load-time GPU memory pool that host-RAM sampling simply cannot see. The honest
move was to name the method's blind spot rather than manufacture a saving from a
flat line. The 30B MoE accuracy flag was the inverse trap: its label promised a
"slight TTFT cost only," but measured it costs \~19% generation throughput too, for
an accuracy benefit a 2.2K-context eval couldn't demonstrate — a real tradeoff the
production config is currently paying, surfaced for the operator to weigh.

The campaign also widened the baseline twice on the operator's direction, and both
were the mature call: every single-model run now also gets a separate, clearly-
annotated Intel-UT telemetry pass (so we accumulate per-run power/frequency/GPU-busy
over time without contaminating the comparable spine), and the prefill benchmark
became a standing companion harness. Neither was strictly asked for by the original
brief; both make the dataset compound rather than expire.

**Next:** finish the co-residency N=1 refresh (the pattern reproduces — SDXL stalls
the resident 14B to \~1%, VLM/cartoon milder, all pairings fit under 31.3 GiB), then
the Session-3 community-postings phase publishes the sequel — leading with the
co-residency cost and the version-A/B nuance, cross-linked to the first
contribution, behind the two hard gates (scrub + operator approval).

**Proposed lesson:** *Measure the environment, not just the model.* A background GPU
client (a browser compositor) faked a 14% speculative-decoding regression that
survived three internal-consistency checks; only the operator's note that the box
wasn't quiet caught it. On a shared-resource iGPU, a benchmark number is only as
trustworthy as the idleness of the machine under it — confirm the environment is
clean before believing any delta, especially on the scheduling-bound spec-decode path.
