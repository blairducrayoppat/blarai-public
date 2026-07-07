# ADR-009: Assistant Interaction Surface — Terminal/TUI (Textual Framework)

## Status
**ACCEPTED** — 2026-02-23
**SUPERSEDED (2026-06-02)** by ADR-014 for the primary interaction surface. The
native WinUI 3 app is the daily-use surface and has reached and exceeded the
parity this ADR's TUI defined (chat, streaming markdown, multimodal attachments,
persistent semantic memory, theming, voice). The Textual TUI is **retained
in-tree as a dormant fallback — not deleted** (User-Operator's explicit call):
it still runs and stays under test coverage, but new capabilities are wired in
the UI backend (ADR-014) and surfaced by WinUI, not added here.

## Context

Phase 3 requires an explicit user interaction surface for USE-CASE-004 (Context-Aware
Private Assistant). P1.0–P1.10 implemented the full backend: Policy Agent hybrid
adjudication, Orchestrator NPU generation, Semantic Router CPU classification, PGOV
6-stage output validation, and vsock IPC with mTLS. The system lacks a user-facing
shell — no prompt input, streaming token display, session management, or PGOV reason
code presentation.

### Gap Analysis

The following capabilities are implicit in USE-CASE-004 but have no concrete specification:
- User-to-system prompt input mechanism
- Streaming token-by-token response display
- Session creation, listing, restoration, and deletion
- PGOV rejection reason code display (PII, delimiter echo, tool-call violation, leakage)
- Boot Phase 3 gating (UI blocked until Policy Agent is operational)
- Error display under Fail-Closed conditions

### Architectural Constraints (from Use Cases_FINAL.md)

1. **vsock mandate:** "The chatbot UI connects via vsock (AF_HYPERV) — zero TCP/IP
   network stack exposure." This governs the inter-VM IPC layer. The user-facing shell
   is a host-side process communicating to the Orchestrator VM via a transport gateway.
2. **Zero external network calls:** "Zero user queries transmitted to any external service
   except Policy-Agent-approved, Fail-Closed-gated anonymous utility calls." The anonymous
   utility carve-out is NOT in MVP scope.
3. **mTLS on all IPC:** All vsock connections are mTLS-authenticated with per-session
   ephemeral certificates issued during Boot Phase 2.
4. **Boot Phase 3 gate:** "Only after Phase 2 completes successfully does the Policy Agent
   open the user-facing interaction surface." The UI must not accept input until the PA
   is operational.
5. **Memory ceiling:** 31.323 GB effective (ADR-005). The UI must minimize footprint.

## Decision

**Option A: Terminal/TUI using the Textual framework.**

The user-facing interaction surface is implemented as a Textual-based terminal application
running on the host (Windows 11 Pro). It communicates with the Orchestrator VM via a
Transport Gateway that bridges host-side function calls to vsock + mTLS IPC.

### Options Evaluated

| Option | Framework | Score | Disposition |
|--------|-----------|-------|-------------|
| **A: Terminal/TUI** | Textual (MIT) | **98** | **SELECTED** |
| B: Local Web UI | FastAPI + localhost | 86 | Rejected — localhost HTTP introduces TCP/IP listening socket |
| C: Native Desktop | PyQt6 / Tkinter | 82 | Rejected for MVP — high complexity, GPL license risk (PyQt6) |

### Scoring Criteria (HIGH=3×, MEDIUM=2×, LOW=1×)

| Criterion | Weight | A: TUI | B: Web | C: Desktop |
|-----------|--------|--------|--------|------------|
| Streaming token latency | HIGH | 5 (1–5ms) | 4 (10–50ms) | 5 (1–5ms) |
| Session state persistence | MEDIUM | 4 | 5 | 4 |
| PGOV display fidelity | HIGH | 3 | 5 | 4 |
| Boot-phase-3 integration | HIGH | 5 | 4 | 4 |
| MVP complexity / velocity | HIGH | 5 (1–2 days) | 3 (3–5 days) | 2 (5–7 days) |
| Memory footprint | MEDIUM | 5 (20–50MB) | 3 (80–150MB) | 3 (100–200MB) |
| Network attack surface | HIGH | 5 (zero) | 3 (localhost HTTP) | 5 (zero) |
| Dependency weight/risk | MEDIUM | 4 (5MB, MIT) | 4 (5MB, MIT) | 2 (80MB, GPL) |
| Future extensibility | LOW | 3 | 5 | 4 |

### Rationale

1. **Zero network attack surface.** No TCP/IP listening sockets. No HTTP stack. User
   interaction is terminal stdin/stdout. Perfect alignment with UC-004 vsock mandate.
2. **MVP velocity.** Textual provides async-native Python widgets (CSS-like styling,
   scrollable panels, modal overlays, live-updating areas). Scaffold-to-functional: 1–2 days.
3. **Memory discipline.** 20–50MB for the UI shell. On a 31.323 GB ceiling, this is the
   most conservative choice.
4. **PGOV display is adequate.** Styled panels display reason codes as colored inline badges
   (e.g., `[DENIED: PII_DETECTED, DELIMITER_ECHO]`). Meets "reason labels, not raw errors."
5. **No license complications.** Textual is MIT-licensed.
6. **Boot gating is trivial.** TUI process blocks on PA vsock handshake.

### Accepted Trade-offs

- PGOV display fidelity is lower than Web UI (scored 3 vs 5). Text-based panels vs HTML
  modals. Adequate for MVP reason labels.
- Markdown/code rendering in responses is limited to terminal capabilities. Textual's
  `Markdown` widget provides basic rendering; syntax highlighting requires custom work.
- Copy/paste of code blocks requires manual terminal selection.

### Migration Path (Phase 4+)

Per Lead Architect directive, the documented migration target for post-MVP is **Native
Desktop Shell (PyQt6 or Tkinter)**, not Web UI. Migration strategy:

1. **P1.11 Transport Gateway is interface-agnostic.** The gateway exposes a Python API
   (`send_prompt()`, `stream_tokens()`, `get_sessions()`, `get_pgov_result()`). The TUI
   shell calls these methods directly. A future PyQt6 shell calls the same API through
   Qt signal/slot bridging.
2. **Session persistence layer (SQLite) is shared.** Both TUI and Desktop read/write the
   same session database.
3. **PGOV reason code model is serializable.** `PGOVResult` dataclass serializes to JSON;
   the desktop shell can deserialize and render in Qt dialog boxes.
4. **Migration gate:** Phase 4+ migration to PyQt6 requires a new ADR evaluating:
   (a) GPL v3 license implications for distribution, (b) Qt/asyncio event loop bridging
   (`qasync`), (c) high-DPI rendering on target hardware, (d) memory impact (\~100–200MB
   delta). Tkinter is the stdlib fallback if GPL is unacceptable.

---

## Interaction Flow

```
User types prompt in Textual Input widget
  ↓
TUI Shell: validate non-empty, trim whitespace
  ↓
Transport Gateway: construct AdjudicationRequest
  ↓
Transport Gateway → vsock + mTLS → Orchestrator VM
  ↓
Orchestrator VM: Semantic Router classifies intent (<80ms)
  ↓
Orchestrator VM: NPU autoregressive generation (token-by-token)
  ↓
Orchestrator VM → vsock → Transport Gateway: streaming tokens
  ↓
TUI Shell: append each token to response panel (1–5ms per token)
  ↓
Orchestrator VM: PGOV validates complete response (6-stage)
  ↓
Orchestrator VM → vsock → Transport Gateway: PGOVResult
  ↓
TUI Shell: if PGOV approved → finalize display
           if PGOV denied → replace response with fallback + reason codes
  ↓
Transport Gateway: log session turn to SQLite
```

---

## Boot-Phase-3 Gating

The TUI shell implements a deterministic startup gate:

1. **Launch:** TUI process starts. Displays "Initializing BlarAI..." splash screen
   (Textual `LoadingIndicator` widget).
2. **PA Handshake:** Transport Gateway attempts vsock connection to Policy Agent.
   Retries with exponential backoff (1s, 2s, 4s) up to 3 attempts.
3. **Success:** PA responds with operational status. TUI transitions to main chat
   screen. Input widget is enabled. Session list is loaded from SQLite.
4. **Failure:** After 3 failed attempts, TUI displays "Policy Agent unavailable.
   System is in Fail-Closed state. See boot_failure.log for diagnostics." Input
   remains disabled. User can retry via keyboard shortcut (Ctrl+R).
5. **Invariant:** No user prompt is accepted, and no request is dispatched to the
   Orchestrator, until the PA handshake succeeds. This is Fail-Closed.

---

## Streaming Behavior

| Parameter | Value | Source |
|-----------|-------|--------|
| Token display latency | ≤5ms (terminal write) | Textual benchmark |
| Token streaming protocol | Length-prefixed JSON over vsock | shared/ipc/protocol.py |
| Buffering strategy | Unbuffered — each token appended immediately | TUI design |
| PGOV buffering | Tool-call blocks buffered until PGOV clears | UC-004 mandate |
| Text tokens | Streamed in real-time to user | UC-004 mandate |
| Thinking block filtering | `<\|think\|>…</\|think\|>` tokens stripped at gateway; never displayed to user | ADR-012 §2.4 |
| Target display rate | ≤100ms per token (system end-to-end) | MVP acceptance |
| Circuit breaker | 4,096 token hard cap per response | shared/constants.py |

### Streaming Protocol

The Transport Gateway receives a stream of `StreamToken` messages from the Orchestrator
via vsock. Each message contains:
- `token: str` — the generated token text
- `token_index: int` — position in sequence (0-based)
- `is_final: bool` — last token flag
- `is_tool_call: bool` — if True, token is part of a tool-call block (buffered)
- `is_thinking: bool` — if True, token is inside a `<|think|>…</|think|>` block
- `session_id: str` — session identifier

Text tokens (`is_tool_call=False`, `is_thinking=False`) are forwarded immediately to
the TUI for display. Tool-call tokens (`is_tool_call=True`) are buffered in the gateway
until the complete tool-call block is received and PGOV validation clears it.

**Thinking token handling (ADR-012 §2.4):** The Assistant Orchestrator runs Qwen3 with
thinking mode enabled (`<|im_end|>` as the only stop token) because internal reasoning
may improve response quality. Thinking tokens (`is_thinking=True`) are **silently
discarded** by the Transport Gateway and never forwarded to the TUI Shell. The user
sees only the final answer content. The Policy Agent is unaffected — it uses `/no_think`
in its system prompt plus dual stop token IDs (`<|im_end|>` + `<|think|>`) to suppress
thinking entirely, and its classification output is never streamed to the UI.

---

## Session Management

| Feature | Implementation |
|---------|---------------|
| Storage backend | SQLite (local file, no cloud sync) |
| Database location | `%LOCALAPPDATA%\BlarAI\sessions.db` |
| Session schema | `id` (UUID), `title` (auto-generated from first prompt), `created_at`, `updated_at`, `is_active` |
| Turn schema | `id` (UUID), `session_id` (FK), `role` (user/assistant), `content`, `pgov_status`, `pgov_reasons`, `timestamp` |
| Create session | Automatic on first prompt if no active session |
| Restore session | TUI session list panel → select → load turns from SQLite |
| Delete session | TUI session list → delete key or context menu → CASCADE delete turns |
| Clear history | Delete all turns for a session, preserving the session record |
| Max sessions | Unbounded (SQLite handles millions of rows) |
| Session list display | Sidebar `ListView` with title, timestamp, turn count |

---

## PGOV / Tool-Block Reason Display

When PGOV denies a response, the TUI replaces the streamed content with:

```
┌─ Response Suppressed ─────────────────────────────────────┐
│                                                            │
│  The response was blocked by the output validator.         │
│                                                            │
│  Reason codes:                                             │
│    • PII_DETECTED — Potential personal information found   │
│    • DELIMITER_ECHO — Context delimiter leaked in output   │
│                                                            │
│  Action: Please rephrase your request.                     │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

Reason code labels (not raw error strings):
- `TOKEN_BUDGET_EXCEEDED` — Response exceeded 4,096 token cap
- `PII_DETECTED` — PII regex match (SSN, credit card, email, etc.)
- `DELIMITER_ECHO` — Context Spotlighting delimiter in output
- `TOOL_CALL_VIOLATION` — Unauthorized tool-call reference
- `LEAKAGE_DETECTED` — Cosine similarity ≥ 0.85 with retrieved content
- `VALIDATION_ERROR` — Catch-all for unexpected PGOV failures

---

## Error Display (Fail-Closed)

| Condition | Display |
|-----------|---------|
| PA unreachable | "Policy Agent unavailable. System in Fail-Closed state." |
| Orchestrator timeout | "Response generation timed out. Please try again." |
| vsock connection failure | "Internal communication error. See diagnostics." |
| PGOV exception | Response replaced with fallback message + `VALIDATION_ERROR` |
| Session DB error | "Session could not be saved. Operating in ephemeral mode." |

All error states result in **no partial response being visible**. Fail-Closed means
the user never sees an unvalidated response fragment.

---

## Data Flow Diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│                        HOST (Windows 11 Pro)                         │
│                                                                      │
│  ┌──────────────┐     direct call      ┌──────────────────────────┐  │
│  │  TUI Shell   │ ◄─────────────────► │   Transport Gateway      │  │
│  │  (Textual)   │    Python API        │   (vsock + mTLS relay)   │  │
│  │              │                      │                          │  │
│  │  • Input     │  stream_tokens()     │  • mTLS handshake        │  │
│  │  • Response  │ ◄──────────────────  │  • Message framing       │  │
│  │  • Sessions  │                      │  • Token buffering       │  │
│  │  • PGOV      │  send_prompt()       │  • PGOV relay            │  │
│  │    display   │ ──────────────────►  │  • Session persistence   │  │
│  │              │                      │                          │  │
│  │  20–50 MB    │                      │  ~10 MB                  │  │
│  └──────────────┘                      └──────────┬───────────────┘  │
│                                                    │                  │
│                                          vsock + mTLS                │
│                                          (AF_HYPERV)                 │
│                                                    │                  │
├────────────────────────────────────────────────────┼──────────────────┤
│                     HYPER-V VM BOUNDARY             │                  │
│                                                    ▼                  │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │                    Orchestrator VM                               │  │
│  │                                                                 │  │
│  │  ┌─────────────┐  ┌───────────────┐  ┌──────────┐              │  │
│  │  │  Semantic    │  │  Orchestrator  │  │  PGOV    │              │  │
│  │  │  Router      │→│  GPU Gen       │→│  6-stage  │              │  │
│  │  │  (CPU,<80ms) │  │  (GPU, Arc140V)│  │  (CPU)   │              │  │
│  │  └─────────────┘  └───────┬───────┘  └──────────┘              │  │
│  │                           │                                     │  │
│  │                    vsock + mTLS                                  │  │
│  │                           │                                     │  │
│  │                    ┌──────▼──────┐                               │  │
│  │                    │ Policy Agent │                               │  │
│  │                    │ (GPU,Arc140V)│                               │  │
│  │                    │ Adjudication │                               │  │
│  │                    │ JWT Minting  │                               │  │
│  │                    └─────────────┘                               │  │
│  └─────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Security Constraints

| Constraint | Enforcement |
|-----------|-------------|
| Zero external network calls | TUI makes no network calls. Gateway connects only to vsock. |
| Attestation gating | UI blocked until Boot Phase 3 PA handshake succeeds |
| mTLS relay | Gateway loads PA-issued ephemeral cert for vsock connections |
| Session data locality | SQLite at `%LOCALAPPDATA%\BlarAI\sessions.db` — no cloud sync |
| PGOV reasons display | Approved/denied status + local reason code labels only |
| No telemetry | Zero usage data collected or transmitted |
| Fail-Closed default | All errors → deny/block. No partial responses. No silent acceptance. |

### Network Security Policy (MVP)

**ZERO external network connections from the UI layer.** The Transport Gateway connects
exclusively to the local vsock endpoint. No HTTP, no WebSocket, no DNS resolution, no
outbound TCP/IP of any kind. This policy is enforced at three layers:

1. **Code-level:** No `socket`, `requests`, `urllib`, `httpx`, or equivalent imports in
   `services/ui_gateway/` or `services/ui_shell/`.
2. **Architecture-level:** The Transport Gateway's only communication channel is vsock
   (AF_HYPERV), which is a hypervisor-internal transport with no IP stack.
3. **Network-level:** The Ubiquiti Router independently blocks unauthorized outbound
   connections from the host.

The "Fail-Closed-gated anonymous utility calls" carve-out in UC-004 is documented but
**deferred to a future phase** requiring a new ADR for network access authorization.

---

## Dependencies

| Package | Version | License | Size | Purpose |
|---------|---------|---------|------|---------|
| textual | ≥0.89 | MIT | \~5 MB | TUI framework |
| rich | (transitive) | MIT | \~3 MB | Terminal rendering |

No additional dependencies beyond the existing Python 3.11.9 venv.

---

## Consequences

### Positive
- Zero network attack surface for the user interaction layer
- Minimal memory footprint (20–50 MB) on a constrained 31.323 GB ceiling
- Fast MVP delivery (1–2 day scaffold-to-functional)
- Clean separation: TUI Shell ↔ Transport Gateway ↔ vsock IPC
- Interface-agnostic gateway enables future migration to PyQt6/Tkinter

### Negative
- PGOV display limited to text panels (no HTML modals, collapsible trees)
- Markdown rendering in responses is basic (Textual `Markdown` widget)
- Code block copy/paste requires manual terminal selection
- No rich data visualizations (charts, diagrams) without terminal-graphics hacks

### Migration Path
- Phase 4+: Native Desktop Shell (PyQt6 or Tkinter) per Lead Architect directive
- Gateway API remains stable; only the UI Shell is replaced
- New ADR required evaluating: GPL license, Qt/asyncio bridging, high-DPI, memory delta

---

## Related ADRs

- **ADR-005:** Empirical Memory Ceiling Correction (31.323 GB effective)
- **ADR-006:** Empirical Memory Budget Tier Summation
- **ADR-007:** iGPU Trust Boundary — Software Fallback Posture
- **ADR-008:** NPU Concurrent Scheduling Characterization
- **ADR-012 §2.4:** Qwen3 Thinking Mode and Stop Token Strategy (thinking block filtering rationale)
