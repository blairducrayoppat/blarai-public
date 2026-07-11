### 2026-07-10 — The slowdown that was three measurement bugs in a coat

*Plain summary: the #778 dedicated A/B refuted the #711 S5 "spec-decode net-negative on
short turns" finding — speculative decoding is 1.48–1.68x positive on BOTH turn shapes
sustained (short benefits MORE); S5 stacked three instrument flaws (nonce prompts, a
nonexistent acceptance-metric call, non-interleaved thermal drift). ADR-012 unchanged.
Subsystem: inference substrate / benchmark harness. Lesson class: era-rot re-measurement
done right; instruments earn belief before their failure classes do (lesson 222 family).*

The scare was respectable: a locked architectural mandate (ADR-012, spec-decode required)
apparently measured as a production slowdown on the assistant's most common turn shape.
The dedicated A/B took the scare apart in one afternoon. On realistic conversational
prompts the draft model's acceptance ran 50–53% of generated tokens and speculative
decoding won on both shapes — short turns MORE than long (1.68x vs 1.48x decode,
sustained-throttle regime), the opposite of the scare, because the predictable Qwen3
think-preamble is a larger fraction of a short turn. Greedy outputs were byte-identical
with spec on or off: lossless. The ISS-1 "~2x" reproduced exactly once per session — in
the cool-burst regime before the silicon throttles — which is itself a finding worth
keeping: this box's thermal envelope can sign-flip a naive A/B.

S5's net-negative was three stacked instrument flaws, each individually survivable: nonce
filler prompts a 0.6B draft cannot predict (near-zero acceptance BY CONSTRUCTION — spec
can only lose there), an acceptance metric logged "unavailable" because the harness
called a method that does not exist on this API (the real GenAI 2026.2.1 API exposes it),
and an AABB non-interleaved matrix that let thermal drift ride the comparison. A field
note rides the entry: on this substrate a draft-wired pipeline REQUIRES
num_assistant_tokens XOR assistant_confidence_threshold on every request — there is no
per-request draft-off, so spec ON/OFF are two pipeline constructions, and the OFF arm is
a true autoregressive baseline.

**Recurrence of lesson 222** (a verdict-issuing instrument needs a positive control
before its failure class is believed): S5's spec-negative verdict carried measurement's
authority for a day while all three of its flaws would have been caught by one run on a
prompt the draft could plausibly predict.

**Next:** the standing harness (`scripts/benchmark_spec_decode_ab.py`) re-measures at
every substrate bump; the thermal-regime sensitivity belongs in any future perf A/B design.
