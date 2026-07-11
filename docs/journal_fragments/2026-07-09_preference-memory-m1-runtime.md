### 2026-07-09 — The system learns to be told who it is talking to

*Plain summary: #770 Learning Loops M1 runtime slice — the `OPERATOR_PREFERENCE`
tier (verbatim, born-encrypted, on the existing knowledge-bank substrate), the
`/remember` + `/preferences` backend commands over new PREFERENCE_WRITE/LIST IPC
verbs, the byte-stable pinned-block renderer at a fixed system-prompt slot
(prefix-cache-aligned), gate-locked P4 budgets set from the S8 measurement, P8
sole-committer security locks, and the `preference_memory` eval suite (§6 cases
1-6). WinUI half deliberately deferred to the allowlist-SSOT step.*

BlarAI has been able to remember documents, images, and its own conversation
history for months. What it could not remember was anything the operator *told
it about himself*. Tonight's slice is the first loop of the learning-loops
program: `/remember Always call me Blair` becomes a durable, encrypted row that
shapes every future turn — and the interesting engineering was not the storing,
it was the *bytes*.

P9 made this a byte-level discipline. The #711 S8 measurement had already told
us the physics: with prefix caching on, a pinned block's warm-hit cost is flat
(~0.4-0.8 s at every size we measured), and the real costs — the one-line-edit
re-prefill and the session-cold first turn — scale linearly at ~4.4 ms/token.
So the renderer's contract IS its bytes: deterministic insertion order, stable
`[p-<id8>]` line ids, one flattened line per preference, a datamark minted once
per *process* rather than once per render (the grounded-context marker rotates
per load for anti-forgery; rotating this one per render would invalidate the
whole block's KV every turn and defeat the point — the anti-forgery property is
preserved by neutralizing marker-shaped text out of bodies instead), and an
edit that changes exactly one line's bytes in place. The cap came off the S8
curve, not out of the air: 1024 estimated tokens keeps an edit at ~4.2 s and a
cold session under ~9 s, where 2048 pushes edits past 9 s and cold past 18 s. I
took the coordinator's constraint that the budget lock must be offline-testable
and pinned a documented conservative estimator (`ceil(chars/3.0)`, over-counting
for English so the real token count sits safely under the enforced number) with
its own drift test — the estimator is now as gate-locked as the cap it enforces.

The failure worth keeping: my first order key was `(created, pref_id)`, and the
store's own test caught it within minutes — five stores landing in the same
clock tick share an ISO timestamp, so ordering fell through to random UUIDs and
two same-second preferences could render in an order the operator never issued
(deterministic, but not append-order; a byte-stable block that reorders on the
day you add two preferences quickly is exactly the subtle P9 violation the
tests exist for). The fix was to stop pretending timestamps are a sequence and
order by the rowid — insertion order, monotonic, collision-free. Timestamps
stay as audit metadata.

P8 was the design's security spine and I built it as structural absence, not a
flag: the ONLY writer of the tier is the AO's PREFERENCE_WRITE handler, whose
frames originate exclusively from the gateway's parse of operator-typed text.
The lock tests assert the model-reachable write path *does not exist* — no tool
in the registry or allowlist names the surface, `tools.py` never references the
write API, a source scan across `services/ shared/ launcher/` proves exactly
one production caller of `store/update/delete_preference` and exactly one
builder of write frames, and a forged `<tool_call>` for a preference write
fail-closes to DANGEROUS like any unknown tool. A preference body that tries to
smuggle spotlighting delimiters or a forged datamark is neutralized at render —
operator-authored by construction does not mean trusted as instructions.

Trade-offs taken, alternatives on the record: I mirrored `TRUSTED_MEMORY`'s
leak-feed handling for the tier (operator-authored by construction — P8 is the
design's own answer to the injection-surface question; the untrusted-side
treatment was the alternative, rejected because echoing the operator's own
standing voice back to him is definitionally not a leak; M2's governance ADR
ratifies this formally). The P5 contradiction confirm is a stub tonight —
`requires_confirmation` refuses the write and routes the operator through the
explicit `/preferences edit` path, so last-writer-wins never fires silently;
the WinUI card is M2. And the block composes at the *end* of the static system
prompt rather than its head: "early" in the P9 sense means ahead of all
grounded content and history, and the latest fixed slot inside the system
region maximizes the static persona prefix that survives a preference edit.

The `preference_memory` eval suite (22 golden cases, §6 classes 1-6) runs the
real store, the real cipher, and the real renderer offline — 17/17 green with 5
model-in-the-loop cases (`model_applies`, `abstention`) waiting on the first
`--include-hardware` run on the Arc 140V. The abstention cases are the ones I
most want to see: a 14B that answers "what language do I prefer?" from a tier
that only knows the operator's name is the confabulation failure LongMemEval
says small models commit.

Deliberately deferred, loudly: `/remember` and `/preferences` are NOT in the
backend-passthrough SSOT constant tonight — listing them forces the WinUI C#
mirror in the same change (the gate test that exists precisely because hand
mirrors silently dropped `/imagine` and `/images`), and the C# side is
tomorrow's step with the allowlist-SSOT change. A TODO in the constant names
the step. Until then the capability is runtime-complete and GUI-unreachable.

**Proposed lesson:** Timestamps are not a sequence — any "deterministic order"
contract that sorts by wall-clock timestamps silently degrades to arbitrary
tie-break order for same-tick writes; when insertion order is the actual
contract (append-minimal rendering, stable numbering an operator sees), sort by
a monotonic insertion key (rowid/sequence) and demote timestamps to audit
metadata. Caught here by a five-writes-in-one-tick test within minutes of
writing the defect.

**Recurrence of lesson 151 (measure, don't estimate):** the P4 cap was set
from the S8 measured curve (warm-flat, ~4.4 ms/token edit/cold cost) instead of
the "1960 pp tok/s means 2k is ~1s" estimate the design itself flagged as
unproven — the measurement moved the answer from "2k is fine" to "1k, because
the binding cost is the edit re-prefill, not the warm turn."

**Next:** M1 day-2 — the WinUI passthrough half (`/remember` + `/preferences`
into the SSOT constant + the C# `BackendPassthroughCommands` mirror + the
dispatcher call, one change under the gate test), then the first
`--include-hardware` run of `preference_memory` on the Arc 140V (evidence
artifact + PERFORMANCE_LOG if it carries timings), then M2: the
`propose_preference` GUARDED tool + the WinUI confirm card + eval case 7
(poisoning red-team) + the governance ADR that ratifies the tier semantics,
write authority, budgets, and the leak-feed call.

*(commits `<this>` (runtime slice on `feat/770-preference-memory-m1`); +~145
new tests across budgets/store/renderer/handlers/authority/protocol/
coordinator/transport/eval-gate; full standing gate in-worktree **6061
passed / 0 failed / 28 skipped [worktree-environmental: gitignored ONNX
model absent + symlink privilege] / 123 deselected**, exit 0, 2:11; eval
gate 6-suite green offline, `preference_memory` 17/17 + 5 hardware-skipped.)*
