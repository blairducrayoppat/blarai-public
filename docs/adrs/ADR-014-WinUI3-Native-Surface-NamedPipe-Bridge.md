# ADR-014: Native Windows Surface (WinUI 3) over a Named-Pipe JSON-RPC Bridge

**Status:** ACCEPTED — 2026-06-02
**Author:** Lead Architect (Blair) + Claude Opus 4.7
**Supersedes:** ADR-009 migration path (the Phase 4+ "Native Desktop Shell
(PyQt6 / Tkinter)" target). ADR-009's Textual TUI remains the operational
fallback until the WinUI 3 surface reaches feature parity, then is deprecated
in-tree (kept dormant, not deleted).
**Related (reserved):** ADR-015 (vision-model integration — the deferred
photo/video understanding this surface is shaped for), ADR-016 (Substrate /
semantic memory).

---

## 1. Context

USE-CASE-004's interaction surface shipped as a Textual TUI (ADR-009). The TUI
is genuinely usable, but the daily personal assistant the User-Operator wants
is shaped like Google Gemini: conversational-and-multimodal first, with
attachments (PDF, photo, video, screenshots) as first-class inline citizens of
the chat, not a terminal command line. ADR-009 already anticipated a
post-MVP migration to a native desktop shell and deliberately kept the
Transport Gateway **interface-agnostic** for exactly this moment. ADR-009's
named migration target was PyQt6/Tkinter; the User-Operator has re-pointed it at
**WinUI 3** (Microsoft's native Windows 11 UI stack).

WinUI 3 is C#/.NET on the Windows App SDK. The existing services — Transport
Gateway, SessionStore, PGOV, the Assistant Orchestrator, document loading — are
Python. The new surface is therefore a **separate process** in a different
language, and the load-bearing decision is how the C# front end talks to the
Python back end.

## 2. Decision

**The WinUI 3 app communicates with the Python services through a Windows
named pipe carrying length-prefixed JSON-RPC frames. A thin Python "UI backend"
daemon hosts the existing `TransportGateway` + `SessionStore` behind that pipe;
the WinUI app is a `NamedPipeClientStream` client and holds no business logic.**

### 2.1 Why a named pipe (not localhost HTTP / gRPC)

ADR-009 evaluated a local web UI and scored it down specifically because
"localhost HTTP introduces a TCP/IP listening socket" — a network attack
surface inconsistent with BlarAI's absolute no-external-network mandate. That
reasoning is unchanged. A **named pipe is a kernel object, not a socket**:
there is no listening TCP/IP port, no DNS, no loopback socket for another local
process or a misconfigured firewall rule to reach. The server additionally sets
`PIPE_REJECT_REMOTE_CLIENTS`, so even the (normally local-only) named-pipe
namespace cannot be driven from another machine. This is the choice that keeps
the front-end/back-end boundary inside the same privacy posture the vsock IPC
layer already holds.

gRPC and localhost HTTP were rejected for the same reason ADR-009 rejected the
web UI: they stand up a listening network socket. The marginally easier
cross-language tooling does not justify reintroducing the surface ADR-009 was
designed to avoid.

### 2.2 Why length-prefixed JSON

The framing mirrors `shared/ipc/vsock.py` exactly — a 4-byte big-endian
unsigned length prefix followed by UTF-8 JSON. A developer who understands the
vsock wire format understands this one. JSON is natively spoken by both
`System.Text.Json` (C#) and Python's `json` module, so no schema-compiler or
code-gen toolchain is introduced. Frame size is hard-capped on both encode and
decode (`MAX_FRAME_BYTES = 4 MB`) to refuse unbounded reads.

### 2.3 Protocol shape

Request: `{"id", "method", "params"}`. Non-streaming reply: a single
`{"id","ok":true,"result"}` or `{"id","ok":false,"error":{code,message}}`.
The streaming `prompt` method emits a sequence of `token` frames, then a `pgov`
frame (the validator verdict), then an `end` frame — preserving the
streaming-output contract (governance/streaming-output.md): text tokens stream
live; `<tool_call>` tokens are buffered until PGOV clearance; thinking tokens
are suppressed at source.

### 2.4 The backend is the single source of chat orchestration

The chat turn (send prompt → stream tokens → resolve PGOV → persist the
assistant turn) lives once, in the backend's `RpcDispatcher._m_prompt`, instead
of being duplicated in each front end. The TUI keeps its own inline copy for
now (it predates this ADR and stays dormant after parity); the WinUI surface
stays thin by driving the dispatcher. This deliberately avoids the
two-surfaces-one-backend drift risk: new capabilities are wired in the backend,
and both the eventual single surface and any test client see them identically.

## 3. Consequences

### Positive
- Zero new network attack surface — named pipe, not socket; remote clients
  rejected at the OS level.
- The Transport Gateway, SessionStore, PGOV, and document pipeline are reused
  unchanged; the backend is a thin host, not a rewrite of logic.
- Front end and back end can evolve independently across the language boundary;
  the JSON contract is the only coupling.
- The dispatcher centralizes chat orchestration, so the WinUI surface carries
  no policy or persistence logic that could drift from the TUI's behavior.

### Negative / accepted trade-offs
- A second process and a C#/.NET toolchain (Windows App SDK) are introduced —
  dev-time build dependencies, installed under the two-tier privacy rule as
  *build* tooling, not BlarAI runtime dependencies.
- A WinUI GUI cannot be driven headlessly the way pytest drives Python, so the
  on-screen behavior (streaming render, drag-drop, theming) is verified live by
  the User-Operator per phase, while the Python backend, dispatcher, and
  protocol stay held to automated coverage. This relaxation is scoped to the
  GUI layer only and was explicitly accepted at the mission gate.
- Until parity, two surfaces exist over one backend. Mitigated by keeping all
  logic in the dispatcher and marking the TUI dormant the moment parity lands.

### Security notes
- `PIPE_REJECT_REMOTE_CLIENTS` set on every pipe instance.
- Default pipe security descriptor (creating user + administrators); no
  world-writable ACL.
- Frame-size cap enforced on encode and decode (Fail-Closed on oversize).
- The pipe carries the same content the TUI path already carries; it does not
  widen what the model can do. Layer 3 (ADR-013) remains paused, and the file
  picker is a host-side copy into `userdata/`, not a model-invokable tool, so it
  does not change the tool blast radius that would require un-pausing it.

## 4. Implementation

- `services/ui_backend/src/protocol.py` — framing codec + frame builders.
- `services/ui_backend/src/dispatcher.py` — transport-agnostic RPC core
  (session, document/attachment, and streaming `prompt` methods).
- `services/ui_backend/src/server.py` — pywin32 named-pipe server driving the
  dispatcher (one connection at a time; `PIPE_REJECT_REMOTE_CLIENTS`).
- `services/ui_backend/src/client.py` — Python client (smoke/tests; the
  production client is the C# WinUI app).
- `services/ui_backend/src/_stub.py` — no-GPU echo gateway for headless smoke.
- `scripts/pipe_smoke.py` — end-to-end transport smoke (PASS/FAIL).
- Tests: `services/ui_backend/tests/test_protocol.py`,
  `services/ui_backend/tests/test_dispatcher.py`.

Production serving (the real gateway behind the pipe, launched by the launcher
in place of the TUI) is wired in Phase 2 alongside the WinUI scaffold.

## 5. Deferred

- Isochronous retrieval timing and the full multi-VM IPC posture remain on the
  long-term architecture (Use Cases §002 ISSUE-007); not in scope here.
- Multi-client pipe fan-out is unnecessary for a single-user assistant; the
  server accepts one connection at a time and loops on reconnect.
