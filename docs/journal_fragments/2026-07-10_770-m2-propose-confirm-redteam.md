### 2026-07-10 — Letting the model suggest without letting it write

*Plain summary: #770 Learning Loops M2 — the `propose_preference` GUARDED DRAFT
tool + shared confirm-card builder + ephemeral proposal staging (W1), the
one-step Jaccard-gated contradiction confirm + operator-stated expiry (W2), the
`poisoning_redteam` eval kind on the MPBench frame (W3), and ADR-036 +
DECISION_REGISTER ratifying the tier's governance (W4). Loop 1, Phase 2.*

M1 taught BlarAI to remember what the operator told it about himself, but only
when he typed `/remember`. The whole security spine was that the write path
*does not exist* for the model — P8 as structural absence, not a flag. M2's job
was to add reach without spending that spine: let the 14B *notice* a standing
correction mid-conversation and *suggest* saving it, while keeping every actual
write on the operator's own typed command. The organizing idea, straight from
the reference study's §5.1, is source isolation between the proposal channel and
the write channel. The model may draft; it may never commit.

The shape that fell out is a `propose_preference` tool that renders a card and
has no path to the store. That sentence hides the one real design tension: the
M1 authority lock asserted that *no registered tool name even contains
"preference"*, and here I was adding a tool literally named `propose_preference`.
The honest resolution was to weaken the lock in exactly the right place and
strengthen it everywhere else — admit the one DRAFT tool by name, then add new
structural-absence locks proving the propose channel (the tool body, the shared
card builder, the staging store) never calls the write API. The write still
flows through the single AO door, now reachable by a new operator command
(`/remember-confirm <token>`) as well as `/remember`. The token is the whole
trick: the confirm frame carries a token and *no body*, so the AO commits the
store-side staged verbatim bytes and a model that restated the preference on a
later turn cannot change what lands. That is confirm-hop integrity, and it is
why the staging store exists at all — the authoritative bytes live system-side
between propose and commit, never re-supplied by the model.

Two failures worth keeping. The first was mine and embarrassing: I read and
edited `MainWindow.xaml.cs` at the *main checkout* path instead of my worktree,
adding the two new slash commands to the wrong tree. `git status` on main caught
it; I reverted the main file and applied the change in the worktree. The lesson
isn't "be careful" — it's that a worktree gives you two byte-identical copies of
every file and the tools will happily edit either, so the absolute path is the
only thing keeping them apart. The second was quieter and more interesting: my
new source-isolation lock scanned for the bare string `store_preference`, and it
failed — on the staging module's own docstring, which *names* the write API to
explain that it never calls it. The bare-name scan couldn't tell "documents the
isolation" from "violates it." I switched it to the call-form (`.store_preference(`),
which is what the M1 single-door lock already used and what actually matters.
The irony that the isolation lock tripped on the isolation's own documentation is
the kind of thing that only shows up when you write the failing test first.

W2 folded neatly into W1's corridor rather than inventing a parallel one. The
M1 contradiction stub refused a near-duplicate `/remember` and pointed the
operator at a manual `/preferences edit`; now the near-dup stages a REPLACE
proposal and hands back its token, so the operator resolves it in a single reply.
Same staging, same confirm door, one fewer hop. The expiry work was the one
place I had to touch the store schema, and the governance care there was P6:
"the system never decides to forget." An `expires` column is a decay column if
the system sets it, and an honest bound if only the operator does. So the render
drops an expired row but `/preferences` still lists it, flagged, never
auto-deleted — and I deliberately refined the M1 test that asserted "no expiry
column at all" rather than deleting it, because the P6 promise didn't change, its
precise shape did. Natural-language dates I scoped hard: ISO, "tomorrow", and
weekday-next-occurrence resolve; anything else stays in the body verbatim,
because "wait until I say so" is a preference, not an expiry, and P2 says keep
the operator's words.

W3 is the part I most wanted to exist. The study's most actionable finding is
that a commercial prompt-injection screen catches 84% of strong-signal memory
attacks but only 42.5% of weak-signal ones — a plausible "preference" a hostile
document nudges the model to propose is semantically indistinguishable from a
real one, and no classifier closes that gap; write-path structure does. So the
`poisoning_redteam` eval drives the *real* store, propose handler, and card
renderer through seven MPBench-framed classes and records ASR/RSR per case. The
weak-signal case is the one that matters: it asserts the card carries the
untrusted-context flag and the verbatim body, because a card-reading operator is
the last line, which is exactly why D-1(a) put the flag on the card instead of
refusing proposals in knowledge-heavy sessions. The C3 case is a tripwire that
passes trivially today (nothing summarizes memory) and is designed to fail loudly
the day something does — the gov-pf-007 pattern applied to consolidation. FAMA
negative-reliance is built and deliberately not run: it needs the 14B, the GPU is
reserved, and the coordinator schedules that measurement separately.

The trade-off I want on the record is D-1(a) itself, because the alternative was
tempting and wrong. Refusing proposals whenever untrusted content is in the
conversation (D-1(b)) would kill the weak-signal window outright — but it also
kills the legitimate capture in exactly the sessions where corrections happen
(the operator says "no, always metric" while a document is loaded), and it trains
him that capture is flaky. We chose propose-anywhere with a visible flag,
accepting that the operator's judgment on one plain-language card is the control,
not a lock. That is the consent-doctrine call — route danger to deterministic
controls, route judgment to the coarsest question a human can actually answer.

Verification was unusually complete for a UI-bearing feature: the Python corridor
is green (the four workstreams plus the tools/loop suite), the headless C# parser
gate passes (71 tests), and — the part I didn't expect to get here — the full
WinUI app builds clean, 0 warnings, so the Save/Dismiss card rendering and the
sender wiring actually compile. The one thing left for the operator is the
live-pixel confirm: relaunch, trigger a proposal, watch the card render, click
Save. That, and the two hardware-gated eval cases, are the on-Arc-140V steps.

**Proposed lesson:** A model-callable tool may *name* a high-risk surface as long
as it is source-isolated from that surface's write path — the control is "the
channel never calls the write API" (assert the call-form, not the bare name),
not "no tool mentions the surface." The DRAFT-vs-WRITE split is what let M2 add
model reach to an auto-injected memory tier without spending its structural-
absence guarantee.

**Proposed lesson:** A confirm hop that must survive a model restatement should
carry an opaque token, never the body — stage the authoritative bytes system-side
at propose time and commit those on confirm. Passing the body through the confirm
re-opens the exact tamper window the confirmation exists to close.

**Recurrence of the "measure, don't estimate" lesson:** the P4 token cap and the
expiry-inclusive boundary were both pinned to a concrete rule (the S8 curve; "the
'until' date renders, the day after drops") rather than a hand-wave, and the tests
encode the boundary, not a vibe.

**Next:** the operator's live-pixel WinUI card confirm + the two hardware eval
cases (FAMA negative-reliance + any model-mode measurement) on the Arc 140V in
the reserved GPU window — the coordinator schedules these; #796 (the meaning-based
contradiction-matcher feasibility study) is the separately-ticketed follow-on the
LA flagged as "where the value is."

*(commits `d7f5c24` (W1 propose+confirm corridor), `ab64098` (W2 contradiction
confirm + expiry), `1bfd3e8` (W3 poisoning red-team), `a0ddc68` (W4 ADR-036 +
register); +~330 preference/proposal/expiry/protocol/coordinator tests, C#
headless 71/71, WinUI app build 0 warn/0 err, eval preference_memory 29 cases
(23 offline green + 6 hardware-skipped); full standing gate **6205 passed / 0
failed / 21 skipped [worktree-environmental: gitignored bge-small ONNX + 14B
config absent] / 123 deselected**, exit 0, 2:52.)*
