# Streaming Token Protocol & PGOV Handoff Governance

## Audience

**Primary**: developer — extends the streaming path (AO streamer,
Gateway, TUI) and MUST preserve the invariants documented here.

**Secondary**: operator (observes TUI behavior under streaming);
auditor (verifies the PGOV handoff closes Red Team ISSUE-005 at the
output boundary).

## Prerequisites

- [ADR-009](../adrs/ADR-009-Assistant-Interaction-Surface.md) —
  assistant interaction surface (Textual TUI, RichLog append-only
  rendering, Boot-Phase-3 state machine).
- [ADR-012 §2.4](../adrs/ADR-012-Qwen3-14B-Model-Selection-Speculative-Decoding.md)
  — Qwen3 thinking-mode strategy. PA runs `/no_think` MANDATORY with
  canonical prefill; AO permits thinking output but the **AO Streamer
  suppresses thinking tokens at source** (transport-layer strip, Task 5
  M3). This doc governs how that contract flows through the wire and
  the TUI.
- Peer governance: [ipc-protocol.md](ipc-protocol.md) defines the
  `StreamToken` wire shape and the `STREAM_TOKEN` / `PGOV_RESULT` /
  `GENERATION_COMPLETE` message sequence;
  [pgov-validation.md](pgov-validation.md) defines the six-stage
  validator whose verdict this doc surfaces.

## Source References

| Artifact | Path | Lines |
|---|---|---|
| TUI StreamingDisplay widget | `services/ui_shell/src/streaming.py` | full file |
| Buffer state machine (`_buffer`, `_streaming`) | `services/ui_shell/src/streaming.py` | lines 47-48, 66-77 |
| Tool-call rendering | `services/ui_shell/src/streaming.py` | lines 60-64 |
| `append_token` entry point | `services/ui_shell/src/streaming.py` | lines 52-70 |
| StreamToken wire shape | `services/ui_gateway/src/transport.py` | lines 68-112 |
| is_thinking suppression comment | `services/ui_gateway/src/transport.py` | lines 79-81 |
| Gateway `stream_tokens` dispatch | `services/ui_gateway/src/transport.py` | lines 493-604 |
| Tool-call buffering at the gateway | `services/ui_gateway/src/transport.py` | lines 639-672 |
| PGOV_RESULT caching | `services/ui_gateway/src/transport.py` | lines 557-574 |
| PGOV FALLBACK message (Orchestrator) | `services/assistant_orchestrator/src/pgov.py` | lines 93-97 |
| PGOV_DENIAL_FALLBACK (Gateway) | `services/ui_gateway/src/transport.py` | lines 175-178 |
| PGOV six-stage pipeline | `services/assistant_orchestrator/src/pgov.py` | lines 537-601 |

## Governance Content

### StreamToken Semantics (Wire)

Every token crossing the Orchestrator → Gateway boundary is a
`StreamToken` dataclass with these fields (see also
[ipc-protocol.md](ipc-protocol.md) for the full wire-shape table):

| Field | Type | Invariant |
|---|---|---|
| `token` | `str` | The rendered text fragment. Empty strings are not emitted. |
| `token_index` | `int` | 0-based, monotonically increasing within a response. |
| `is_final` | `bool` | True exactly once per response, on the last token. |
| `is_tool_call` | `bool` | True if this token participates in a tool-call block (buffered until PGOV clearance). |
| `session_id` | `str` | Correlates back to the session that issued the prompt. |
| `is_thinking` | `bool` | **Always False at the wire.** The AO Streamer strips thinking tokens at source per ADR-012 §2.4 M2. The field exists for future TUI collapsed-thinking rendering (`transport.py` lines 79-81). |

### Streaming Lifecycle

A full response traces this sequence (`transport.py` lines 524-604):

1. **First token** — Gateway enters its `stream_tokens` generator loop.
   The first `STREAM_TOKEN` message arrives; if `is_tool_call=False`,
   it is yielded immediately to the TUI. TUI flips `_streaming = True`
   and the cursor renders as active (`streaming.py` lines 66-70).
2. **Mid-stream** — Zero or more additional `STREAM_TOKEN` messages
   arrive. Each increments `processed_tokens`; the Gateway enforces
   `STREAM_TOKEN_BUFFER_LIMIT` (`transport.py` line 545) — exceeding
   the cap terminates the stream Fail-Closed.
3. **Tool-call block** — tokens with `is_tool_call=True` are NOT
   forwarded to the TUI; they accumulate in `_tool_call_buffer`
   (`transport.py` lines 639-656). The buffer itself is capped at
   `TOOL_CALL_BUFFER_MAX_TOKENS`; overflow is Fail-Closed.
4. **PGOV_RESULT message** — Orchestrator emits a `PGOV_RESULT`
   envelope carrying the final verdict (approved, sanitized_text,
   reason_codes). Gateway caches it keyed by `request_id`
   (`transport.py` lines 557-574). This may arrive **before** or
   **interleaved with** the last `STREAM_TOKEN` — the protocol does
   not mandate strict ordering between PGOV_RESULT and the final
   token.
5. **Final token** — a `STREAM_TOKEN` with `is_final=True` arrives.
   TUI sets `_streaming = False` (`streaming.py` line 70). The
   cursor-blink indicator goes dormant.
6. **End-of-sequence signal** — `GENERATION_COMPLETE` closes the
   loop. If the Gateway sees `GENERATION_COMPLETE` without a matching
   cached PGOV result, it logs a warning and continues waiting for
   PGOV or stream close (`transport.py` lines 576-587).

### When PGOV Runs Relative to Streaming

PGOV validates **AFTER all generation-side tokens have been collected**
on the Orchestrator side (the 6-stage pipeline operates on the full
response text, not per-token). By the time the `PGOV_RESULT` message
crosses the wire, the underlying text tokens have either already been
yielded or are in the Gateway's tool-call buffer awaiting the verdict.

**Consequence**: text tokens (`is_tool_call=False`) render **live**
into the TUI during generation. If PGOV later denies, those text
tokens have already been shown to the user — the fallback-message
substitution (below) replaces them on final render. Tool-call tokens
are held until clearance and never reach the user on denial.

### PGOV → TUI Feedback Loop on Suppression

If `PGOV_RESULT.approved == false`:

1. Gateway caches the `GatewayPGOVResult` with `approved=false`,
   `sanitized_text = PGOV_DENIAL_FALLBACK` (`transport.py` lines
   175-178: "The response was blocked by the output validator.
   Please rephrase your request.") and the populated `reason_codes`.
   Note: this gateway-side fallback string differs from the
   Orchestrator-side `FALLBACK_MESSAGE` (`pgov.py` lines 93-97) —
   both are intentionally generic; the gateway text is what the user
   actually sees.
2. On the buffered tool-call block, `flush_tool_call_buffer(false)`
   discards the held tokens (`transport.py` lines 658-672).
3. The TUI's response pane, having streamed partial text, receives
   the `sanitized_text` via the caller's
   `TransportGateway.get_pgov_result(request_id)` call. The calling
   widget is responsible for replacing the displayed streaming output
   with the fallback text. (TUI-side replacement logic lives in the
   calling screen, not in `StreamingDisplay` itself.)

There is **no distinct "output suppressed" banner** at the current TUI
surface — the fallback message IS the notification. See
[pgov-validation.md](pgov-validation.md) for the "User Notification of
Suppression" section covering why this is deliberate.

### Thinking-Token Handling in the TUI

ADR-012 §2.4 M2 locks the **AO Streamer suppresses thinking tokens at
source**. Consequently:

- `StreamToken.is_thinking` is **always False** on the wire
  (`transport.py` lines 79-81, explicit comment).
- `StreamingDisplay.append_token` does **not** branch on `is_thinking`
  today — the field is transport-layer reserved, not rendered
  differentially.
- If a future release enables a collapsed-thinking rendering option
  (the field's documented purpose), the change happens in
  `streaming.py`'s `append_token` branch structure, not on the wire.
  The wire contract ships the bit today so that downstream code can
  evolve without a schema change.

### Buffer / State Machine

`StreamingDisplay` maintains a simple two-element state
(`streaming.py` lines 47-48):

- `_buffer: str` — the mutable response-text accumulator.
- `_streaming: bool` — `True` while tokens are arriving.

`append_token` (lines 52-70) dispatches:

- **Tool-call token** → render atomically as a distinct block
  (`\n[dim]⚙ tool-call:[/dim] {token.token}\n`), return early. Does
  NOT update `_streaming`.
- **Text token** → set `_streaming = True`, append text to `_buffer`,
  trigger `_render_buffer()` which clears and re-writes the widget.
  If `is_final`, `_streaming = False`.

The inherited `RichLog.max_lines = RESPONSE_SCROLL_BACK_LINES` caps
scroll-back history.

### Backpressure if UI Can't Render Fast Enough

**None at the wire.** The Gateway does not throttle `STREAM_TOKEN`
reception; tokens are yielded to the consumer as they arrive. The
TUI's `append_token` is synchronous and re-renders on each call —
Textual's reactive event loop absorbs the cost. If a future profile
shows the re-render cost becoming dominant, a partial-render
optimization lives inside `_render_buffer`; the wire contract does
not need to change.

### Circuit-Breaker Integration

The AO's generation loop enforces `MAX_OUTPUT_TOKENS = 4096`
(`shared/constants.py` line 135). On breach:

1. The AO halts generation.
2. The AO emits a final `STREAM_TOKEN` with `is_final=True`.
3. PGOV Stage 1 validates the truncated output's token count against
   the cap; equality passes.
4. `GENERATION_COMPLETE` closes the stream.

From the TUI's perspective, a breach looks identical to a normal
end-of-stream — the response simply ends at the last token. Any
user-facing signaling of truncation would need to live inside the AO
or as a new reason code in `PGOV_RESULT`; no such signal exists today.

### Error States

- **AO crash mid-generation** — the Orchestrator closes the
  transport socket. The Gateway's `stream_tokens` loop sees
  `resp_bytes is None` (`transport.py` lines 528-532) and breaks.
  `get_pgov_result(request_id)` falls back to Fail-Closed DENY
  (`transport.py` lines 632-637): `approved=false`,
  `sanitized_text=PGOV_DENIAL_FALLBACK`,
  `reason_codes=[REASON_VALIDATION_ERROR]`.
- **Malformed STREAM_TOKEN** — `MessageFramer.decode` raises
  `ValueError`; the Gateway logs and continues (`transport.py` lines
  534-540). One bad frame does not tear down the stream; repeated
  malformations will eventually exhaust the token-limit guard.
- **Full recovery path** — crash recovery governance belongs to
  `docs/governance/error-recovery.md` (GOV-06, authored in a later
  EA). This doc forward-references that future doc and does not
  duplicate its content.

## Recovery / Remediation Procedures

- **User observes truncated response with fallback text** — PGOV
  denial. Re-examine the prompt; the fallback text does not encode
  which stage triggered (information-hiding). Enable DEBUG on the
  `services.assistant_orchestrator.src.pgov` logger to see the
  denial reason codes locally.
- **User observes streaming hang** — the most common cause is a
  stalled Orchestrator read. Verify PA handshake status via
  `check_pa_status`; if the gateway transitioned to `FAILED`,
  restart the UI shell.
- **Tool-call block appears in output** — by design, tool-call
  tokens render atomically only after PGOV clearance. If a
  tool-call token renders and subsequently disappears, that's
  expected on denial (buffer flush discards it before it lands in
  `_buffer`).

## Open Questions / Deferred Items

- **Collapsed thinking-panel rendering** — the `is_thinking` bit
  is reserved for this; no UX decision has been made. Deferred
  until a separate design pass post-Sprint 9.
- **Per-stage PGOV reason surfacing** — currently hidden by design.
  Reconsider only if triage friction becomes a documented incident
  driver (tracked against the "observability" cluster, pending
  GOV-12 authoring).
- **Partial render optimization** — `_render_buffer` does a full
  clear-and-rewrite per token. Acceptable today; revisit if profiles
  show it dominating TUI latency.
- **Crash-recovery governance** — `docs/governance/error-recovery.md`
  (GOV-06) is deferred to a later Sprint 9 EA. Cross-references here
  are forward-references only and MUST be reconciled when that doc
  lands.
