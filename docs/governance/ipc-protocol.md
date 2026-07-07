# IPC Protocol & Message Format Governance

## Audience

**Primary**: developer — authors new inter-agent messages and destination
services, and MUST conform to the CAR + envelope contracts documented
here.

**Secondary**: auditor — reviews the wire-protocol boundary for the
Action Authorization Boundary (AAB) and verifies replay / revocation
hardening.

## Prerequisites

- [ADR-007](../adrs/ADR-007-iGPU-Trust-Boundary-Software-Fallback.md) —
  establishes the software-fallback trust posture (Hyper-V + vsock +
  mTLS). Cited directly in `shared/ipc/vsock.py` (module docstring,
  lines 4-9). This is the closest-relevant ADR for IPC; **no ADR
  directly locks the CAR schema** — CAR is defined in
  `shared/schemas/car.py` and amendments proceed through ordinary code
  review + Policy Agent rule-engine updates, not an ADR amendment.
- [ADR-010](../adrs/ADR-010-PA-Device-Allocation-GPU-Classification.md)
  — Policy Agent on GPU. The PA is the IPC termination point for every
  CAR `ADJUDICATION_REQUEST`.
- [ADR-012 §2.4](../adrs/ADR-012-Qwen3-14B-Model-Selection-Speculative-Decoding.md)
  — thinking-mode strategy adds the `is_thinking` bit to `StreamToken`
  (see [streaming-output.md](streaming-output.md) for the transport
  semantics of that bit).
- Peer governance: [pgov-validation.md](pgov-validation.md) defines the
  `PGOV_RESULT` message shape conceptually;
  [streaming-output.md](streaming-output.md) defines the streaming
  lifecycle that the `STREAM_TOKEN` / `PGOV_RESULT` /
  `GENERATION_COMPLETE` message sequence implements.

## Source References

| Artifact | Path | Lines |
|---|---|---|
| Canonical Action Representation (CAR) | `shared/schemas/car.py` | lines 61-142 |
| AdjudicationDecision + DecisionArtifact (JWT payload) | `shared/schemas/car.py` | lines 145-197 |
| IPC MessageType enum | `shared/ipc/protocol.py` | lines 41-74 |
| AdjudicationRequest / AdjudicationResponse envelopes | `shared/ipc/protocol.py` | lines 77-144 |
| MessageFramer encode/decode | `shared/ipc/protocol.py` | lines 147-377 |
| VsockAddress + VsockConfig | `shared/ipc/vsock.py` | lines 47-78 |
| 4-byte length-prefix framing constants | `shared/ipc/vsock.py` | lines 34-36 |
| `AF_HYPERV = 34` | `shared/ipc/vsock.py` | line 39 |
| PolicyAgentListener (destination side) | `services/policy_agent/src/ipc.py` | full file |
| NonceStore + EpochTracker (replay + revocation) | `services/policy_agent/src/ipc.py` | lines 42-115 |
| JWT validator incl. nonce/epoch claims | `shared/crypto/jwt_validator.py` | full file |
| Gateway StreamToken / GatewayPGOVResult | `services/ui_gateway/src/transport.py` | lines 68-152 |
| Orchestrator VM / vsock constants | `shared/constants.py` | lines 225-247 |

## Governance Content

### Canonical Action Representation (CAR) — Schema

The CAR is the **lingua franca of the Action Authorization Boundary**
(`car.py` lines 1-20). Every inter-agent tool call is reduced to a CAR
before the Policy Agent adjudicates it. The schema (`car.py` lines
61-110):

| Field | Type | Required | Description |
|---|---|---|---|
| `source_agent` | `str` | yes | Cryptographic identity of the requesting agent (mTLS CN). |
| `destination_service` | `str` | yes | Target microservice for the action. |
| `verb` | `ActionVerb` enum | yes | One of: `READ`, `WRITE`, `EXECUTE`, `DELETE`, `QUERY`, `DISPATCH`, `EGRESS`. |
| `resource` | `str` | yes | Target resource identifier (e.g., `substrate.vector_store`). |
| `parameters_schema` | `dict[str, Any]` | default `{}` | JSON Schema of the action parameters — the **schema**, not the values. |
| `sensitivity` | `Sensitivity` enum | yes | One of: `PUBLIC`, `INTERNAL`, `SENSITIVE`, `UNCLASSIFIED`. **No default** — prevents silent misclassification (`car.py` line 95). |
| `timestamp` | `datetime` (UTC) | default `now()` | CAR creation time. |
| `request_id` | `str` | yes | Unique correlation identifier. |
| `session_id` | `str` | default `""` | Multi-turn session identifier; empty for stateless. |

**Validation rules** (`car.py` lines 132-142): `is_complete()` returns
True only if `source_agent`, `destination_service`, `resource`, and
`request_id` are all non-empty. Incomplete CARs are **Fail-Closed
rejected** — the PA will not adjudicate them.

**Privacy** (`car.py` lines 17-19): CARs never contain raw user data —
only action metadata (verb, resource, destination, parameters **schema**)
sufficient for the PA to adjudicate intent without seeing payload
content.

### CAR Serialization

CARs are transported as **JSON** inside the `car_json` field of an
`AdjudicationRequest` envelope (`protocol.py` lines 77-100). Pydantic
`BaseModel` governs field typing; JSON encoding uses Python's standard
`json` module with deterministic key ordering when hashing.

Canonical hash (`car.py` lines 112-130): `canonical_hash()` produces a
deterministic SHA-256 over **identity + action fields only** —
`source_agent`, `destination_service`, `verb`, `resource`,
`parameters_schema`, `sensitivity`. Timestamp and request_id are
deliberately excluded so the same logical action yields the same hash
across retries. The hash uses `json.dumps(..., sort_keys=True,
separators=(",", ":"))` for stability.

### IPC Envelope Format

Every IPC message is a JSON envelope with three fields (`protocol.py`
module docstring lines 16-21):

```json
{
  "type": "ADJUDICATION_REQUEST",
  "request_id": "<uuid>",
  "payload": { ... }
}
```

- `type` — one of the `MessageType` values (see below).
- `request_id` — correlation UUID; required for request/response
  matching.
- `payload` — type-specific body.

### Message Types (MessageType Enum)

Source: `protocol.py` lines 41-74.

| Type | Direction | Purpose |
|---|---|---|
| `ADJUDICATION_REQUEST` | Agent → PA | Serialized CAR for evaluation. |
| `ADJUDICATION_RESPONSE` | PA → Agent | Decision + optional Agentic JWT. |
| `ERROR` | PA → Agent | Processing error (Fail-Closed DENY). |
| `HEARTBEAT` | Bidirectional | Liveness check. |
| `HANDSHAKE_REQUEST` | Gateway → Orchestrator | Boot-Phase-3 PA status check. |
| `HANDSHAKE_RESPONSE` | Orchestrator → Gateway | PA operational status. |
| `PROMPT_REQUEST` | Gateway → Orchestrator | User prompt for generation. |
| `STREAM_TOKEN` | Orchestrator → Gateway | Single generated token (streamed). |
| `PGOV_RESULT` | Orchestrator → Gateway | PGOV validation outcome. |
| `GENERATION_COMPLETE` | Orchestrator → Gateway | End of token stream. |

### StreamToken — Wire Shape

Source: `services/ui_gateway/src/transport.py` lines 68-112. A
`StreamToken` carries the following fields (all required unless noted):

| Field | Type | Default | Notes |
|---|---|---|---|
| `token` | `str` | — | The generated token text. |
| `token_index` | `int` | — | 0-based position in the generation sequence. |
| `is_final` | `bool` | — | True on the last token of the response. |
| `is_tool_call` | `bool` | — | True if part of a tool-call block (buffered until PGOV clearance). |
| `session_id` | `str` | — | Correlates to the originating session. |
| `is_thinking` | `bool` | `False` | Transport-layer bit added in Task 5 M3 per ADR-012 §2.4. Currently **always False** at the wire because the AO Streamer suppresses thinking tokens at source (see `transport.py` lines 79-81). Field reserved for future collapsed-thinking rendering options. |

`to_dict()` / `from_dict()` define the JSON wire form (lines 91-112).
Unknown fields are ignored on decode (forward compatibility); missing
required fields default via type coercion — tests enforce round-trip
stability.

### Request / Response Envelope Details

- **mTLS frame shape** — at the socket layer (vsock), each message is a
  4-byte big-endian unsigned length prefix followed by the JSON
  envelope bytes (`vsock.py` lines 34-36: `_HEADER_FORMAT = "!I"`,
  `_HEADER_SIZE = 4`). The SSL/TLS layer wraps the socket transparently
  via `VsockTransport`; the framing is AFTER TLS decryption.
- **JWT payload** (Agentic JWT = `DecisionArtifact`, `car.py` lines
  153-197) contains:
  `car_hash`, `decision`, `request_id`, `deterministic_pass`,
  `probabilistic_pass`, `confidence`, `timestamp`, `expiry_seconds`
  (default **5 s** hard TTL per Use Cases §3), `issuer`
  (always `"policy_agent"`).
- **CAR hash computation and placement** — the `car_hash` claim is
  computed by `CanonicalActionRepresentation.canonical_hash()` (SHA-256)
  and placed into the JWT by the PA. Destinations recompute the hash
  over the received CAR and verify equality before executing.

### vsock Wire Protocol

- **Socket family** — `AF_HYPERV = 34` in production (`vsock.py` line
  39). dev_mode substitutes TCP loopback.
- **Address form** — `VsockAddress(cid, port)` (`vsock.py` lines
  47-55). CID is the Hyper-V Context Identifier; port is the service
  port within the VM.
- **Canonical constants** (`shared/constants.py` lines 225-247):
  `ORCHESTRATOR_VM_ID = "9c7f986f-7afd-48b0-af5b-2c330df6b38f"`,
  `VSOCK_SERVICE_GUID = "0000c350-facb-11e6-bd58-64006a7986d3"`,
  `VSOCK_PORT = 50000`.
- **TCP-like behavior** — vsock is stream-oriented; reads may yield
  short counts. The transport layer handles read-until-length-prefix-
  satisfied semantics.
- **Max message size** — 64 KB default (`VsockConfig.max_message_bytes
  = 65_536`, `vsock.py` line 77; mirrored as
  `DEFAULT_MAX_MESSAGE_BYTES = 65_536` in `protocol.py` line 38).
  Enforced on **send and receive** to prevent unbounded-read attacks.

### Message Ordering and Flow Control

- **Message ordering guarantees** — within a single connection,
  messages are delivered in send order (TCP-like property inherited
  from vsock stream semantics). Across connections: **none**. The PA
  listener processes **one request per connection** (`policy_agent/src/
  ipc.py` lines 96-98); connections are single-use by architectural
  design. The UI Gateway similarly opens a fresh transport per prompt
  (`transport.py` lines 371-389).
- **Backpressure / flow-control** — **none** at the protocol layer.
  The sender blocks on write until the kernel buffer accepts; the
  receiver pulls on its own cadence. The streaming path (Orchestrator
  → Gateway) has an application-level cap: `STREAM_TOKEN_BUFFER_LIMIT`
  (`transport.py` line 545) is Fail-Closed enforced — exceeding the
  limit terminates the stream.

### Error Response Format

On any protocol-level failure the PA returns a `MessageType.ERROR`
envelope carrying an `AdjudicationResponse` with `decision="DENY"` and
a non-empty `error` string (`protocol.py` lines 103-144, encode at lines
281-287). Destinations treat the DENY as authoritative and refuse the
requested action. **No silent drops** — every failure path emits an
ERROR.

### JWT Verification at Destination

The destination microservice performs a **staged validation**
(`shared/crypto/jwt_validator.py` module docstring lines 1-21, and
`policy_agent/src/ipc.py` replay/revocation governance notes):

1. Signature verification (CA public key).
2. `car_hash` verification — recompute over the received CAR and
   compare.
3. **Epoch validation** (Stage 3) — JWT `epoch` claim ≥ destination's
   `last_seen_epoch`; if greater, update the stored value (lazy
   revocation).
4. **Nonce uniqueness** (Stage 4) — `NonceStore.check_and_add(nonce)`
   returns False if the nonce was already seen; False rejects the JWT
   (`policy_agent/src/ipc.py` lines 70-82). The nonce-seen set is
   TTL-GC'd (default 5 s, lines 91-96).

Every claim-shape field (`car_hash`, `decision`, `request_id`,
`deterministic_pass`, `probabilistic_pass`, `confidence`, `timestamp`,
`expiry_seconds`, `issuer`) is defined by `DecisionArtifact`
(`car.py` lines 153-197) and validated against that schema before
the semantic stages run.

### Example Request/Response Cycles

**Happy path — classify and allow:**

```
Agent → PA (ADJUDICATION_REQUEST, car_json):
  CAR { source_agent="orchestrator", destination_service="substrate",
        verb=QUERY, resource="substrate.vector_store",
        parameters_schema={...}, sensitivity=INTERNAL,
        request_id="<uuid>" }

PA → Agent (ADJUDICATION_RESPONSE):
  { decision="ALLOW", jwt_token="<Agentic JWT with car_hash+nonce+epoch>",
    car_hash="<sha256>", request_id="<uuid>", error="" }

Agent → Destination (with JWT) → executes.
```

**Denial — DPC denial (Policy Agent deterministic rule rejection):**

```
PA → Agent (ADJUDICATION_RESPONSE):
  { decision="DENY", jwt_token="", car_hash="<sha256>",
    request_id="<uuid>", error="DETERMINISTIC_RULE_REJECTED" }
```

**Denial — PGOV denial (Orchestrator output path):**

```
Orchestrator → Gateway (PGOV_RESULT):
  { approved=false, sanitized_text="<fallback>",
    reason_codes=["LEAKAGE_DETECTED"], request_id="<uuid>" }
```

### Timeout Behavior

- **Sender wait SLA** — `PA_HANDSHAKE_TIMEOUT_S` for initial handshake,
  `PROMPT_RESPONSE_TIMEOUT_S` for prompt/stream (both in
  `services/ui_gateway/src/constants.py`). On timeout, the transport
  closes Fail-Closed and the gateway demotes to `FAILED` state.
- **Receiver processing SLA** — the PA listener enforces
  `VsockConfig.timeout_ms` (default 5 s) per read. Stalled connections
  are closed without response — the Agent sees a closed socket and
  MUST treat it as DENY.

## Recovery / Remediation Procedures

- **Handshake retry** — the UI Gateway performs exponential backoff
  (`PA_HANDSHAKE_MAX_RETRIES` × `PA_HANDSHAKE_BACKOFF_BASE_S × 2**attempt`,
  `transport.py` lines 265-292). After exhaustion the gateway goes
  `FAILED` and surfaces a Fail-Closed denial to the user.
- **Malformed message** — `MessageFramer.decode` raises `ValueError`
  on unparseable JSON or unknown `type`; the listener catches and
  returns an `ERROR` envelope.
- **Message-size breach** — any message larger than
  `max_message_bytes` is rejected at `encode` time (sender-side guard)
  and truncated-read-rejected at `receive` time (receiver-side guard).

## Open Questions / Deferred Items

- **CAR schema amendments** — no ADR governs CAR directly. If the
  schema evolves (new `ActionVerb`, new required field), convention is
  a coordinated PR against `car.py` + PA rule engine + this doc.
  Elevate to an ADR only if the schema change has cross-use-case
  ramifications.
- **Per-message flow control** — currently none. If streaming
  throughput grows past 4 KiB/s sustained (not observed at Sprint 9
  EA-1 time), revisit via a future GOV ticket.
- **JWT revocation broadcast** — nonce + epoch provide **lazy**
  revocation. An eager revocation channel (PA broadcasts revoked
  agent CNs to destinations on mTLS revocation) is an open design
  question; tracked informally against the "observability" cluster
  pending ISS-4 resolution.
