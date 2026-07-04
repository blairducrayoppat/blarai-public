# Circuit Breaker Governance

## Audience

**Primary**: developer — maintains the Orchestrator circuit-breaker
module and calls `CircuitBreaker.record_tokens` / `record_tool_call`
from the generation and tool-dispatch loops. Any change to breaker
thresholds, trip semantics, or fallback text flows through this
governance doc before merge.

**Secondary**: incident responder (investigates truncated conversations
where the breaker fired and must distinguish breaker trips from PGOV
denials or model-level stop-token emission); auditor (verifies OWASP
LLM04 "Model Denial of Service" mitigation is hard-enforced, not
advisory).

## Prerequisites

- [ADR-012 §2.4](../adrs/ADR-012-Qwen3-14B-Model-Selection-Speculative-Decoding.md)
  — Qwen3 Thinking Mode and Stop Token Strategy. The Orchestrator
  allows thinking tokens to be emitted by the model, so the raw token
  stream counted by the breaker includes `<|think|>…</|think|>` content
  before stripping. The breaker therefore bounds **total decoder work**,
  not just user-visible text.
- [DEC-05](../POST_OPERATIONAL_MATURATION_LEDGER.md) — Production
  configuration values (AO `max_output_tokens = 4096`). DEC-05 is the
  reason the value exists at `MAX_OUTPUT_TOKENS` in `shared/constants.py`
  rather than being hard-coded in the breaker module.
- [Use Cases_FINAL.md](../../Use%20Cases_FINAL.md) — USE-CASE-004
  (Assistant Orchestrator) specifies bounded-latency conversational
  response; the token breaker is the hard bound that guarantees the
  latency envelope never runs away even under adversarial prompting.
- Peer governance docs:
  [pgov-validation.md](pgov-validation.md) (six-stage validator that
  re-checks the token count at end-of-stream and enforces its own
  budget stage); [error-recovery.md](error-recovery.md) (how a breaker
  trip is surfaced through the UI and logged).

## Source References

Canonical implementation and its load-bearing constants.

| Artifact | Path | Lines |
|---|---|---|
| CircuitBreaker module | `services/assistant_orchestrator/src/circuit_breaker.py` | full file |
| `BreakerState` dataclass | `services/assistant_orchestrator/src/circuit_breaker.py` | lines 31-43 |
| Token breaker `record_tokens` | `services/assistant_orchestrator/src/circuit_breaker.py` | lines 70-83 |
| Depth breaker `record_tool_call` | `services/assistant_orchestrator/src/circuit_breaker.py` | lines 85-97 |
| `safe_truncation_message` | `services/assistant_orchestrator/src/circuit_breaker.py` | lines 99-117 |
| AO-local constant aliases | `services/assistant_orchestrator/src/constants.py` | lines 46-47 |
| `MAX_OUTPUT_TOKENS = 4_096` | `shared/constants.py` | line 135 |
| `MAX_TOOL_CALL_DEPTH = 5` | `shared/constants.py` | line 138 |
| Breaker unit tests | `services/assistant_orchestrator/tests/test_circuit_breaker.py` | full file |
| PGOV `FALLBACK_MESSAGE` (distinct string) | `services/assistant_orchestrator/src/pgov.py` | lines 93-97 |

## Governance Content

### 1. Two Independent Breakers

The module defines **two** breakers that run in parallel inside a single
`BreakerState`:

1. **Token Breaker** — caps decoder output at
   `MAX_OUTPUT_TOKENS = 4096` (`shared/constants.py` line 135, aliased
   into the AO package as `OUTPUT_TOKEN_CAP` at `constants.py` line 46).
2. **Depth Breaker** — caps tool-call recursion at
   `MAX_TOOL_CALL_DEPTH = 5` (`shared/constants.py` line 138, aliased
   as `TOOL_CALL_DEPTH_CAP` at `constants.py` line 47).

Either breaker tripping sets `BreakerState.tripped = True`
(`circuit_breaker.py` lines 40-43). Callers check the aggregate
`tripped` property after each `record_*` call and short-circuit the
generation or tool-dispatch loop. Trips are non-negotiable: there is
no escalation path that raises the caps mid-request.

### 2. Token Counter Semantics

`record_tokens(state, count)` accumulates into
`state.tokens_generated` and trips when
`tokens_generated >= max_tokens` (`circuit_breaker.py` lines 80-82).
The comparison is `>=`, not `>`, so the 4096th token is the trip
boundary. The counter is incremented once per decoder step, with
`count` representing the delta since the last call — incremental
accumulation is covered by
`TestTokenBreaker.test_incremental_accumulation`
(`test_circuit_breaker.py` lines 30-37).

**Thinking tokens count.** Per ADR-012 §2.4 the Orchestrator permits
the model to emit `<|think|>…</|think|>` content. Those tokens traverse
the same decoder pipeline that calls `record_tokens`, so thinking
content is bounded by the same 4096-token cap. This is intentional:
the breaker bounds **total decoder work** (which drives latency and
GPU residency), not just post-strip user-visible text. Deferring the
count until after think-tag stripping would defeat the DoS-mitigation
purpose.

### 3. Tool-Call Depth Counter Semantics

`record_tool_call(state)` increments `state.tool_call_depth` by 1 per
hop and trips when `tool_call_depth >= max_depth`
(`circuit_breaker.py` lines 94-96). A "hop" is a complete tool
invocation that produces a tool-result message appended to the
conversation. The counter resets only at the start of a new request
(see §6 below).

### 4. Trip Behavior

When either breaker trips, the caller MUST:

1. Stop advancing the decoder / tool-dispatch loop on the next
   iteration boundary.
2. Call `breaker.safe_truncation_message(state)` to retrieve the
   user-facing notice.
3. Deliver the (possibly partial) generated text plus the truncation
   notice to the downstream stage (PGOV + streaming).
4. Log the trip at the launcher-log level — see
   [error-recovery.md](error-recovery.md) for the log-line shape and
   path.

Breaker evaluation errors themselves trip the breaker (module
docstring, `circuit_breaker.py` lines 14-18 — "Fail-Closed: breaker
evaluation errors trip the breaker"). There is no "breaker is broken,
continue anyway" path.

### 5. Exact Fallback Message Text

`safe_truncation_message` composes one or both of these exact strings
(`circuit_breaker.py` lines 108-117):

- Token trip: `"Output token limit reached (4096 tokens)."`
- Depth trip: `"Tool-call recursion limit reached (5 hops)."`
- Neither: `"No circuit breaker triggered."` (defensive default,
  should never reach the user in practice)

When both breakers trip on the same request, the function joins the
two sentences with a single space.

**The breaker fallback is NOT the PGOV fallback.** PGOV's
`FALLBACK_MESSAGE`
(`"I'm unable to provide that response due to content policy
constraints. Please rephrase your request."`, `pgov.py` lines 93-97)
replaces the entire response on a content-policy denial. The breaker
message is **appended** to whatever partial response was already
generated — the user sees the truncated answer plus the notice.
Mixing the two breaks the "why was my response stopped?" signal.

### 6. Per-Session vs. Cross-Session Reset

Breaker state is **per-request** — the module docstring
(`circuit_breaker.py` line 16) states "Breaker state is per-request
(no cross-request leakage)." `CircuitBreaker.new_request()` returns a
fresh zeroed `BreakerState` (`circuit_breaker.py` lines 66-68); the
caller MUST invoke `new_request()` at the start of each user turn.

"Per-request" means per-user-turn, not per-session. Across a
multi-turn conversation, each user turn gets 4096 new output tokens
and 5 fresh tool-call hops. Cross-request carryover would be a
correctness bug: a long conversation would eventually reach the
budget floor on its first turn and refuse to answer.

### 7. Threshold-Tuning Governance

Both thresholds live in `shared/constants.py` (lines 135 and 138)
because DEC-05 froze production configuration in the ledger. Any
proposal to change either value MUST:

1. Open a ledger entry in
   `docs/POST_OPERATIONAL_MATURATION_LEDGER.md` (or its successor
   per-file directory under `docs/ledger/`) identifying the decision
   as a DEC-05 amendment.
2. Provide empirical justification (e.g., 95th-percentile token
   utilization measurement from production traffic) rather than a
   feel-based adjustment.
3. Re-run the `test_circuit_breaker.py` suite and update the unit
   tests whose assertions reference the old numeric values
   (`test_token_truncation_message` pins `"100 tokens"` because the
   test constructs a 100-token instance — unit tests are parametric,
   but the doc-level reference `(4096 tokens)` in
   `safe_truncation_message` output is production-fixed).
4. Update this doc's §5 fallback-message table and §1 threshold
   citations in the same commit as the constants change.

No runtime configuration surface exists to override these caps. This
is deliberate: OWASP LLM04 mitigation that a request can disable is
not a mitigation.

### 8. Monitoring

Breaker trips SHOULD be logged with enough context to reconstruct the
offending request class (user prompt category, token count at trip,
depth at trip) without logging the prompt body. The exact log shape is
specified in [error-recovery.md](error-recovery.md) §Logging; this doc
does not duplicate that surface.

**Open Question (GOV-07-OBS-01).** No observability dashboard exists
yet for aggregated breaker trip rates. Until one is added, incident
responders rely on `%LOCALAPPDATA%\BlarAI\launcher.log` greps. A
per-breaker counter exposed via the launcher's health endpoint is a
plausible next step but is deferred pending operator demand.

### 9. Interaction with PGOV

The breaker runs **during** generation; PGOV runs **after**
end-of-stream (see [pgov-validation.md](pgov-validation.md) §Six-Stage
Pipeline — Authoritative Order). When the token breaker truncates
mid-generation, PGOV receives the truncated text plus a token count
equal to the cap. PGOV's Stage 1 (Token Budget Enforcement) then
re-checks the count and treats at-cap as acceptable (the breaker's
hard stop already enforced the budget). The result envelope delivered
to the UI carries PGOV's `approved` flag alongside the breaker's
truncation notice — both surfaces must be present for the user to
distinguish "stopped because too long" from "stopped because
policy-violating."

### 10. Interaction with Streaming

The TUI streaming widget (`services/ui_shell/src/streaming.py`,
`StreamingDisplay.append_token`) relies on `StreamToken.is_final` to
close the display.
When the breaker trips mid-stream, the generation loop MUST emit a
final token carrying the
`safe_truncation_message(state)` text so the stream closes cleanly
with the notice rendered inline. The UI does not receive a separate
"breaker tripped" control message; the notice is the payload.

### 11. Interaction with KV-Cache

A breaker trip does not invalidate or reset the KV-cache for the
current request — cache state is a per-request property of the
generation pipeline, and the request ends when the breaker trips.
Subsequent requests start with a fresh `BreakerState` and a fresh
cache scope per the standard AO generation path. Cross-request cache
poisoning via the breaker path is not possible because there is no
state carried across the `new_request()` boundary.

### 12. Example Scenarios

**Scenario A — Long-form model elaboration.** User asks for a
detailed technical writeup. Model generates 4096 tokens without
finishing. Token breaker trips on the 4096th token. The partial
response plus `"Output token limit reached (4096 tokens)."` flows to
PGOV, is approved (no policy violation), and renders in the UI.
Incident responder action: none. Log entry at INFO.

**Scenario B — Runaway tool recursion.** Model decides to call the
same tool repeatedly (possibly under prompt-injection influence).
After the 5th `record_tool_call`, depth breaker trips. The partial
response (if any) plus `"Tool-call recursion limit reached
(5 hops)."` flows through. Incident responder action: inspect the
prompt class in the log to determine whether the recursion was
benign or adversarial. This is the OWASP LLM04 DoS-mitigation path.

**Scenario C — Both breakers trip.** A long generation that also
made 5 tool calls. `safe_truncation_message` returns
`"Output token limit reached (4096 tokens). Tool-call recursion
limit reached (5 hops)."` — both sentences joined by a single space.
The UI renders the composite notice.

## Recovery / Remediation Procedures

Breaker trips are not failures — they are the mitigation firing as
designed. The recovery surface is therefore minimal:

1. **User-facing recovery.** The user sees the partial response plus
   the truncation notice. They may retry with a narrower prompt or
   accept the truncated output. No system intervention is required.
2. **Operator recovery.** If breaker-trip rate spikes above baseline
   (tracked qualitatively via launcher log until GOV-07-OBS-01 is
   addressed), the operator consults
   [error-recovery.md](error-recovery.md) §Retry vs. Escalation
   Matrix to distinguish adversarial traffic from a model-behavior
   regression. No reset command exists — per-request state means
   each new turn starts clean.
3. **Developer recovery (threshold change).** Follow §7
   Threshold-Tuning Governance. Any change that relaxes the caps
   without the DEC-05 amendment path is a protocol violation and
   MUST be rejected at SDO review.

No "clear the breaker" administrative action exists because there is
no persistent breaker state to clear.

## Open Questions / Deferred Items

- **GOV-07-OBS-01 (Observability).** Aggregate breaker trip-rate
  dashboard. Deferred pending operator demand; current volume does
  not justify the infrastructure. Interim: log greps.
- **GOV-07-THNK-01 (Thinking-token accounting).** Current policy
  counts thinking tokens toward the 4096 cap (see §2). Open question
  whether to split into a separate `MAX_THINKING_TOKENS` budget so
  long reasoning traces do not starve the user-visible answer. No
  empirical evidence yet that this is a problem in practice; defer
  to a DEC-05 amendment if production traffic shows thinking-token
  starvation.
- **GOV-07-BOOT-01 (Boot-sequence cross-reference).** The
  initialization ordering of the breaker relative to model load and
  KV-cache warm-up is documented implicitly by the AO entrypoint
  but will be cross-referenced from a future `boot-sequence.md`
  governance doc (GOV-15, out of scope for EA-2). Until GOV-15 lands,
  treat §11 KV-Cache interaction as authoritative.
- **GOV-07-WEIGHT-01 (Weight-integrity forward-reference).** A
  compromised model weight could emit tokens at unusual rates; the
  breaker bounds the damage regardless. Full weight-integrity
  governance lives in the Pluton-blocked weight-integrity.md doc
  (see [error-recovery.md](error-recovery.md) forward-reference).
  The breaker is defense-in-depth against an already-compromised
  model, not the primary mitigation for weight tampering.
