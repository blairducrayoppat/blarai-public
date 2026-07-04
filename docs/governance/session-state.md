# Session State Governance

## Audience

**Primary**: developer — maintains the session identity surface that
bridges UI Shell, UI Gateway, and Assistant Orchestrator. Any
change to session ID minting, persistence schema, reconnect
semantics, or the scope at which per-session state (PGOV results,
circuit-breaker state, context window) is keyed flows through this
governance doc before merge.

**Secondary**: incident responder (distinguishes "session lost" vs
"conversation replayed" vs "session_id collision" during operator
support); auditor (verifies that sessions do not bleed across the
SQLite boundary and that deletion cascades correctly).

## Prerequisites

- [STYLE.md](STYLE.md) — governance doc template and source-anchoring
  rules. This doc conforms to the seven-header template and cites an
  ADR plus source files below.
- [ADR-009](../adrs/ADR-009-Assistant-Interaction-Surface.md) —
  Assistant-Interaction-Surface. Governs the UI Shell ↔ UI Gateway ↔
  AO contract that session state rides on. ADR-009 is the
  closest-relevant ADR per STYLE.md's source-anchoring rule; no ADR
  directly governs SQLite session persistence (see §Open Questions
  for the future-ADR candidate note).
- **Anchor-source substitution notice.** The continuation XML
  originally named `services/assistant_orchestrator/src/session.py`
  as the primary anchor for session persistence. That file does not
  exist in the AO source tree. Authoritative session persistence
  lives at the UI Gateway boundary in
  `services/ui_gateway/src/session_store.py`. The AO does not
  maintain its own session persistence; it threads `session_id` as
  an opaque identifier through `ContextManager` keyed dictionaries.
  This substitution matches EA-2's precedent (e.g., `gpu_inference.py`
  substituted for a phantom `model_loader.py`). The substitution is
  also called out in the EA-3 ledger's Notes / Substitutions section.
- Peer governance docs [context-spotlighting.md](context-spotlighting.md)
  (explains how `session_id` keys each `ConversationContext` inside
  the AO) and [pgov-validation.md](pgov-validation.md) (per-turn
  PGOV results that this doc explains are persisted per-turn in the
  session store).

## Source References

Canonical implementation — session persistence authoritative surface
lives in the UI Gateway; AO-side is identity threading only.

| Artifact | Path | Symbol / Lines |
|---|---|---|
| SQLite session store (authoritative) | `services/ui_gateway/src/session_store.py` | `SessionStore` class (lines 165-474) |
| Schema DDL (sessions + turns) | `services/ui_gateway/src/session_store.py` | `_SCHEMA_SQL` (lines 141-162) |
| `SessionSummary` dataclass | `services/ui_gateway/src/session_store.py` | lines 86-108 |
| `Turn` dataclass (per-turn row) | `services/ui_gateway/src/session_store.py` | lines 110-133 |
| `create_session` (UUID mint + active flag) | `services/ui_gateway/src/session_store.py` | lines 208-228 |
| `add_turn` (role validation + timestamp) | `services/ui_gateway/src/session_store.py` | lines 287-327 |
| `delete_session` (CASCADE) | `services/ui_gateway/src/session_store.py` | lines 329-346 |
| `set_active_session` (exclusive active bit) | `services/ui_gateway/src/session_store.py` | lines 365-376 |
| `derive_session_title` (auto-title helper) | `services/ui_gateway/src/session_store.py` | lines 57-83 |
| `set_title_if_empty` (auto-title on first prompt) | `services/ui_gateway/src/session_store.py` | lines 380-403 |
| `update_session_title` (the `/rename` command) | `services/ui_gateway/src/session_store.py` | lines 405-427 |
| `_backfill_empty_titles` (one-time data repair) | `services/ui_gateway/src/session_store.py` | lines 429-473 |
| Auto-title wiring on first prompt | `services/ui_gateway/src/transport.py` | `send_prompt` — `set_title_if_empty` call after the user turn |
| `/rename` command handler | `services/ui_shell/src/app.py` | `action_submit_prompt` — `/rename` branch |
| UI-side panel consuming the store | `services/ui_shell/src/session_panel.py` | `SessionPanel` class (lines 52-154), `_label_markup` |
| AO-side identity threading | `services/assistant_orchestrator/src/context_manager.py` | `_sessions` dict (line 78), `create_session` (lines 81-90), `destroy_session` (lines 188-203) |
| AO prompt handler (session_id parse) | `services/assistant_orchestrator/src/entrypoint.py` | `_handle_prompt_request` lines 769-790 |
| ADR-009 (Assistant-Interaction-Surface) | `docs/adrs/ADR-009-Assistant-Interaction-Surface.md` | full ADR |

## Governance Content

### 1. Where Session State Lives

BlarAI splits session concerns across three processes by design:

- **UI Shell (Textual TUI).** Holds ephemeral UI state: which
  session is selected in the left panel, scroll position, input
  buffer. No persistence; crash = lost UI state, not lost history.
- **UI Gateway.** Owns the authoritative persistence surface
  (`session_store.py`, SQLite at `%LOCALAPPDATA%\BlarAI\sessions.db`).
  Every conversation turn is written here after PGOV completes.
  This is the single source of truth for "what did the user and
  model say across turns."
- **Assistant Orchestrator (AO).** Holds per-session in-memory
  working state: `ConversationContext` (delimited system prompt,
  grounded chunks, turn history used for the current-turn prompt
  assembly) and KV-cache warmth flags. This state is
  process-local; AO restart discards it, and it MUST be
  reconstructable from the UI Gateway session store on the next
  turn by replaying the persisted turns into `add_turn`.

This split is load-bearing: the AO never owns authoritative history,
so AO restart is non-destructive to the user's conversation, and the
UI Gateway never has to understand model-format context assembly
because that is the AO's job.

### 2. Session Identity Lifecycle

**Mint.** `SessionStore.create_session` (lines 208-228) generates a
UUID4 via `uuid.uuid4()`, timestamps it with `datetime.now(timezone.utc)`,
truncates the title to `SESSION_TITLE_MAX_CHARS`, and inserts a row
into `sessions` with `is_active=1`. The returned UUID string is the
session_id that propagates through every downstream surface. A session
is minted with an **empty title** — the title is filled later (see
Title below), not at mint time.

**Title.** The `title` column is a human-facing label, distinct from
the UUID identity. It is filled in one of three ways:

- **Auto-title on first prompt.** When a session's first user turn is
  persisted, the UI Gateway's `send_prompt` calls
  `SessionStore.set_title_if_empty` (lines 380-403) with a title
  derived by `derive_session_title` (lines 57-83): the format is
  `<first SESSION_TITLE_PROMPT_CHARS chars of the prompt>… · <date>`
  (e.g. `What's the capi… · May 22, 2026`). The `WHERE title = ''`
  guard makes this idempotent — it fires only on the first prompt.
- **Explicit rename.** The `/rename <new title>` UI command calls
  `SessionStore.update_session_title` (lines 405-427), an
  unconditional overwrite. A renamed title is never re-clobbered by
  the auto-title path (the `set_title_if_empty` guard sees a
  non-empty title and no-ops).
- **Backfill.** `_backfill_empty_titles` (lines 429-473) runs once at
  `SessionStore.__init__` and repairs historical rows: any session
  still holding an empty title is given an auto-title derived from
  its first persisted user turn. It is additive (empty titles only),
  idempotent, and leaves genuinely-unused sessions (no user turn)
  empty. This closed the original data-quality fault in which every
  session was stored title-less and surfaced as the indistinguishable
  placeholder "New session".

A title is rendered through `SessionListItem._label_markup`, which
escapes Rich markup — a title carrying `[...]` renders literally
rather than being parsed as a markup tag.

**Scope.** session_id is a process-stable identifier that survives
AO restarts, UI reconnects, and user-driven session switches. It is
retired only by explicit `delete_session`; there is no TTL.

**Retire.** `delete_session` (lines 329-346) deletes the `sessions`
row; CASCADE on the `turns(session_id)` foreign key (DDL line 158)
removes all associated turns. AO-side state for that session in
`ContextManager._sessions` is NOT cleaned up by this delete — that
cleanup happens on the next AO restart, because no
delete-notification IPC exists today (see §Open Questions
GOV-09-DELETE-01).

### 3. Persistence Surface

The schema (SQL DDL at `session_store.py` lines 141-162):

```sql
CREATE TABLE sessions (
    id         TEXT PRIMARY KEY,  -- UUID4
    title      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,  -- ISO 8601 UTC
    updated_at TEXT NOT NULL,  -- ISO 8601 UTC
    is_active  INTEGER NOT NULL DEFAULT 0  -- exclusive flag
);

CREATE TABLE turns (
    id           TEXT PRIMARY KEY,  -- UUID4
    session_id   TEXT NOT NULL,  -- FK -> sessions.id
    role         TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    content      TEXT NOT NULL DEFAULT '',
    pgov_status  TEXT NOT NULL DEFAULT 'N/A',
    pgov_reasons TEXT NOT NULL DEFAULT '[]',  -- JSON array of strings
    timestamp    TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);
```

Pragmas set at connection time (lines 194-195):

- `journal_mode=WAL` — UI Shell reads (panel refresh) and UI
  Gateway writes (turn append) can proceed concurrently without
  blocking each other.
- `foreign_keys=ON` — required for the CASCADE semantics above.

The schema is authoritative. Any change requires a coordinated
migration path — SQLite does not support column drops without table
rebuild, so additive changes are preferred. No migration framework
exists today; the schema is currently immutable by convention.

### 4. Per-Turn Persistence Surface

Every assistant response write goes through `add_turn` (lines
287-327). The write includes:

- The role (`user` or `assistant` — validated at line 310; any
  other value raises `ValueError`).
- The content (the post-PGOV `sanitized_text`, NOT the raw model
  output — so denied turns persist `FALLBACK_MESSAGE`, not the
  violating content).
- The PGOV status (`approved` / `denied` / `error` / `N/A` for
  user turns).
- The PGOV reason codes as a JSON-encoded list (empty for
  approved / user turns; populated with codes like
  `"TOKEN_BUDGET_EXCEEDED"`, `"PII_DETECTED"` — see
  [pgov-validation.md](pgov-validation.md) for the reason-code
  taxonomy).
- A UTC ISO-8601 timestamp minted at write time.

`add_turn` also bumps the parent session's `updated_at` (lines
322-325), which drives the "most recently updated" ordering in
`list_sessions` (line 240). The same `send_prompt` path that
persists the user turn also applies the auto-title via
`set_title_if_empty` immediately afterward (see §2 Title).

### 5. UI Shell ↔ UI Gateway ↔ AO Bridge

The end-to-end path for a single user turn:

1. **UI Shell** — User types a prompt, hits Enter.
   `ChatScreen.on_submit` reads the `active_session_id` from
   `SessionPanel._active_session_id` and calls the gateway client
   with `(session_id, prompt)`.
2. **UI Gateway** — Receives the CAR request, calls
   `SessionStore.add_turn(session_id, "user", prompt, "N/A", [])`
   to persist the user turn, then issues a `PROMPT_REQUEST` over
   vsock (see [ipc-protocol.md](ipc-protocol.md)) with the same
   `session_id` in the payload.
3. **AO** — `_handle_prompt_request` (entrypoint.py lines 769-790)
   parses `session_id` and `prompt` from the payload; uses
   `session_id` as the opaque key for `ContextManager` operations.
   The model sees no session_id in the token stream — it is a
   routing identifier only.
4. **AO generation** — `ContextManager.build_context(session_id)`
   produces the prompt; the model generates; PGOV validates;
   streaming and final PGOV result flow back to the UI Gateway.
5. **UI Gateway** — Calls
   `SessionStore.add_turn(session_id, "assistant", sanitized_text,
   pgov_status, pgov_reasons)` to persist the assistant turn.
6. **UI Shell** — Refreshes the panel (or receives a push) and
   renders the new turn count.

This loop is the minimal session lifecycle. The session_id threads
through every step and never changes within the turn.

### 6. Reconnect Semantics

**UI Shell reconnect to an existing session.** When the user
selects a session from the left panel (or the TUI reloads after a
crash), `SessionPanel.refresh_list` (lines 90+) calls
`SessionStore.list_sessions()` and renders the summaries. Selecting
one sets `_active_session_id`. The turn history is NOT eagerly
loaded — it is pulled by `get_session_turns(session_id)` only when
the conversation pane opens.

**AO-side reconstruction.** On the first turn for a session_id that
the AO has not seen since its last restart, `ContextManager` has no
entry in `_sessions`. The AO currently relies on `create_session`
being called with the same session_id (via `_handle_prompt_request`
logic upstream of the current implementation — see §Open Questions
GOV-09-RECON-01 for the gap). The UI Gateway is expected to replay
prior turns via `add_turn` before issuing the prompt request; this
replay is NOT wired in the current code path, which means that
after an AO restart, the first turn for any pre-existing session
has no historical context until the user has a full subsequent
turn. This is a known gap documented below.

**Fresh session.** A new session is created (`Ctrl+N`, or lazily on
first prompt) with an empty title. It is given an auto-generated
title — `<first prompt fragment>… · <date>` — when its first user
prompt is persisted, via `SessionStore.set_title_if_empty` called
from the UI Gateway's `send_prompt`. Until that first prompt, the
panel shows the `TITLE_PLACEHOLDER` ("New session"). The user may
override the title at any time with the `/rename <new title>`
command, which calls `SessionStore.update_session_title`. See §2
Title for the full title lifecycle.

### 7. Scope of Per-Session State

Which subsystems key state per-session vs process-wide:

| Subsystem | Keyed per-session? | Reference |
|---|---|---|
| PGOV configuration (cosine threshold, allowlist) | No — process-wide | `pgov.py` lines 197-209, 93-97 |
| PGOV result (approved / violations list) | Per-turn, persisted in `turns.pgov_reasons` | `session_store.py` lines 287-327 |
| Circuit breaker state (`BreakerState`) | Per-request (not per-session) — a new `BreakerState` is minted per user turn | [circuit-breaker.md §6](circuit-breaker.md) |
| Context window (`ConversationContext`) | Per-session, keyed by session_id in `ContextManager._sessions` | `context_manager.py` line 78 |
| KV-cache warmth flag | Per-session (`_kv_warm` set) | `context_manager.py` line 79 |
| Grounded chunks | Per-session (`ConversationContext.grounded_chunks`) | `context_manager.py` line 59 |

The pattern: policy surfaces are process-wide (one cosine threshold
applies to all sessions); observed state surfaces are per-session
(each session has its own context window and KV-cache posture);
enforcement events are per-turn (each turn produces its own PGOV
result and breaker trip, written into the persisted turn row).

### 8. Failure Modes

| Mode | Symptom | Detection |
|---|---|---|
| Orphaned session (sessions.db corrupted post-create) | `create_session` succeeds, next `add_turn` raises | SQLite integrity error surfaces in UI Gateway log |
| Cross-session bleed-through | User sees another session's turn | Would require a session_id collision OR a dict-key confusion bug in `ContextManager._sessions`; UUID4 collision probability is effectively zero |
| session_id not a UUID4 | External caller submits arbitrary string | CHECK-constraint-free on `sessions.id`; accepted as-is. Not an injection risk (parameterized queries), but violates convention |
| AO restart mid-turn | Turn generation aborts; user sees incomplete response | UI Gateway handles reconnect; user retries. Session persistence is unaffected. |
| Stale AO-side `_sessions` entry for deleted session | AO still accepts prompts for a session the UI Gateway deleted | AO has no delete notification; stale entries accumulate until AO restart |

### 9. Audience Guidance

- **Operator** — `%LOCALAPPDATA%\BlarAI\sessions.db` is the file to
  back up if preserving conversation history matters. WAL mode
  means both `sessions.db` AND `sessions.db-wal` should be copied
  while the gateway is stopped. A crashed gateway may leave an
  incomplete WAL; SQLite will roll forward on next open.
- **Developer** — Do not add columns to `turns` without coordinating
  with every `SELECT` in `get_session_turns` and the downstream
  rendering code. No ORM buffers this — SQL columns are a direct
  surface. Prefer a JSON blob column over a new scalar if the
  field is write-rarely-read-rarely.
- **Auditor** — CASCADE delete is the only built-in cleanup path.
  There is no "redact a single turn" operation; deleting a turn
  means deleting its session (or running raw SQL, which bypasses
  the `SessionStore` API).
- **Incident responder** — Confusion between "session lost" and
  "session empty" is common. Check `turns` row count for the
  session_id first; if zero, the session was never populated. If
  non-zero but the user cannot see them, the UI Shell is not
  pointing at the right session_id (check `_active_session_id`).
- **Future agent** — This doc assumes the AO does NOT own session
  persistence. If that assumption changes (e.g., if a future
  milestone adds an AO-side session cache for cold-start speed),
  update §1 and §7 tables first, then amend the bridge in §5.

## Recovery / Remediation Procedures

Session-layer failures split into two classes: persistence-layer
(corrupt DB, missing file) and identity-layer (orphaned sessions,
stale AO entries). The recovery matrix:

1. **DB missing or corrupted.** `SessionStore.__init__` creates a
   fresh database on open (`executescript(_SCHEMA_SQL)` line 196
   is `CREATE TABLE IF NOT EXISTS`). A deleted `sessions.db` is
   equivalent to a fresh install — no prior history. If recovery
   is desired, restore from a backup before opening the gateway;
   the gateway will refuse to overwrite an existing schema.
2. **WAL roll-forward failure.** SQLite's default behavior is to
   recover on next open. If recovery fails, the DB is unusable;
   the operator must delete it (losing history) or restore a
   backup.
3. **Stale AO-side session entry.** Restart the AO service. There
   is no in-flight purge command.
4. **Developer schema migration.** No migration tooling exists.
   Schema change requires (a) authoring a migration script that
   runs `ALTER TABLE` / `CREATE TABLE` + data copy, (b) pausing
   the gateway while it runs, (c) updating `_SCHEMA_SQL` to match
   the new steady-state so `CREATE TABLE IF NOT EXISTS` remains
   correct for fresh installs. See GOV-09-SCHEMA-01 below.

## Open Questions / Deferred Items

- **GOV-09-ADR-01 (ADR absence).** No direct ADR governs SQLite
  session persistence. ADR-009 is the closest-relevant (the UI
  Shell / UI Gateway / AO contract that sessions ride on) and is
  cited in Prerequisites per STYLE.md's closest-relevant rule. A
  future ADR — nominally "Session Persistence Contract" — would
  pin schema-change governance, retention policy, and
  backup/restore semantics. Deferred pending either a schema
  change large enough to warrant the decision-record cost or an
  operator-driven retention requirement.
- **GOV-09-DELETE-01 (No AO delete notification).** When the UI
  Gateway deletes a session, the AO's in-memory `_sessions` entry
  (if any) is not purged until AO restart. Low-severity
  because: (a) memory footprint is small, (b) a "zombie" session
  that receives a new prompt would still return model output —
  semantically odd but not a correctness bug. Proper fix: add a
  `SESSION_DELETE` vsock message type.
- **GOV-09-RECON-01 (AO restart history replay).** After AO
  restart, the first turn for a pre-existing session loses
  historical context because the UI Gateway does not replay
  prior turns into the AO before issuing the prompt. Mitigation:
  the model still responds correctly to the user's current
  prompt; it just cannot reference prior-turn content. Proper
  fix: either the UI Gateway replays turns on cold-session hit,
  or the AO eagerly reconstructs `ConversationContext` from the
  session store on first-turn for unknown session_id.
- **GOV-09-SCHEMA-01 (No migration framework).** The schema is
  mutable only via coordinated code + data changes; no framework
  manages versioning. If a breaking schema change is needed,
  design the migration surface before the schema change.
- **GOV-09-BOOT-01 (Boot-sequence cross-reference).**
  `SessionStore.__init__` creates the DB on first open, but the
  startup ordering relative to UI Gateway bind and AO readiness
  is documented implicitly by `guest_deploy.py` — will be
  cross-referenced from `boot-sequence.md` (forthcoming /
  GOV-15). Until then, §5 Bridge is authoritative.
