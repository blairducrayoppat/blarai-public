# ADR-036 — Operator-Feedback-Memory Governance (Learning Loop 1)

**Status:** ACCEPTED 2026-07-10 (Lead-Architect-ratified; decisions D-0..D-4 + the §2.2a removal-semantics
position settled in-chat 2026-07-10, recorded on Vikunja #770/#792 and in the committed iteration plan).
M1 shipped 2026-07-09; M2 (this ADR's subject) shipped 2026-07-10.
**Amendment 1 (2026-07-11, #792):** Decision 8 — the confirm card's provenance NOTICE is now sized to the
untrusted grain (a proportionate notice for the operator's own knowledge-bank recall vs the strong warning
for a document/web result). Fixes the live mislabel where an auto-recalled `UNTRUSTED_KNOWLEDGE` fresh
session read as "a document or web result." Presentation-only; the Layer-3 gating and D-1(a) allow-with-notice
posture are unchanged.
**Deciders:** Lead Architect (blarai); Orchestrator (facilitation).
**Builds on:** ADR-023 (Provenance-Based Trust Model — the GUARDED tier + #570 per-dispatch PA mediation
the propose tool rides; the `UNTRUSTED_*` provenance the untrusted-context card flag reads),
ADR-031 (Substrate v2 / the `EncryptedKnowledgeBank` this tier is a table on), ADR-025 (the DEK /
FieldCipher / AAD posture the born-encrypted rows inherit).
**Classifies under (cross-repo):** the devplatform cf-program **ADR-022 self-modification-surface
taxonomy** (MCP design principles v1.1) — this ADR records the classification of the auto-injected
preference tier and its M2 proposal channel within that taxonomy (§ "Self-modification classification"
below). The devplatform ADR-022 remains the authoritative taxonomy; this is the BlarAI-side stamp.
**Relates to:** Vikunja #770 (Learning Loops program), #792 (M2 build), #793 (M3 miner — separate),
#796 (the meaning-based contradiction-matcher feasibility study — D-3, separate); the iteration plan
`docs/research/preference_memory_m2_m3_iteration_plan_2026-07.md` (committed blarai `8d3a9c63`, the LA
direction this ADR ratifies); the external design study `docs/research/assistant_memory_reference_study_2026-07.md`.

## Context

BlarAI could remember documents, images, and conversation history, but nothing the operator *told it
about himself*. Learning Loop 1 adds a durable, operator-authored **preference tier** whose rows are
injected into every conversational turn's system prompt. An auto-injected memory that a model can write
is the highest-risk self-modification surface in the agentic-memory literature — the MINJA / AgentPoison
class (study §5.1): poison the store once, and it steers every future turn across sessions (OWASP ASI06).
The whole design is organized around making that write path **not exist for the model**, while still
letting the operator — and, in M2, the operator *via a card the model may draft* — shape it.

M1 built the tier (verbatim, born-encrypted, pin-only), the `/remember` + `/preferences` operator write
door, the byte-stable pinned-block renderer, the P4 budgets, and the P8 sole-committer locks. M2 adds the
propose-and-confirm capture lane, the one-step contradiction confirm, operator-stated expiry, and the
poisoning red-team eval. This ADR is the governance record the M1 fragment (2026-07-09) said "awaits M2
ratification": it makes the tier semantics, the write authority, the budgets, and the leak-feed call
citable, and it formalizes the LA's D-0..D-4 + §2.2a decisions.

## Decision

1. **Tier semantics — pinned-only, off the retrieval surface (D-0).** The `operator_preferences` tier
   stores the operator's utterance **verbatim** (P2 — never paraphrased; small models cannot recover from
   summarization loss and the store must not inflict it), **born-encrypted** (ADR-025 DEK/FieldCipher, AAD
   bound to the row), in **deterministic insertion order** (rowid, not timestamp — the 2026-07-09
   same-tick-collision lesson). It is deliberately **never chunked, embedded, indexed, or retrieved**: at
   the M1/M2 scale (≤64 rows × ≤500 chars, all inside the 1024-token pinned block by construction),
   retrieval over preferences would add recall risk and zero reach. This is also the tier's poisoning
   posture — never retrieved means **RSR is structurally 0** for anything that somehow landed. Hybrid
   recall enters the memory story only with a future **episodic tier** (own ADR), riding the existing
   knowledge-bank RRF machinery, not new retrieval over preferences.

2. **P8 write authority — one operator door; the proposal channel is source-isolated from it.** The ONLY
   writer of the tier is the AO `PREFERENCE_WRITE` handler, whose frames originate exclusively from the
   gateway's parse of operator-typed `/remember` / `/preferences` / `/remember-confirm` /
   `/remember-dismiss`. The model-reachable write path **does not exist** — asserted by structural-absence
   locks (registry + allowlist inspection, a source scan proving exactly one production caller of the
   write API, and a forged `<tool_call>` for a preference write failing closed to DANGEROUS).

   **M2 adds exactly one model-callable tool that names the preference surface — `propose_preference` —
   and it is a DRAFT, never a write (study §5.1 source isolation).** Its runner renders a confirm card and
   stages the proposed verbatim bytes in an ephemeral, system-owned staging store; it has **no path to the
   store**. The write happens only when the operator types/clicks `/remember-confirm`, which rides the same
   PREFERENCE_WRITE door. The confirm frame carries **only a token**, never a body — so the AO commits the
   store-side staged bytes and a model restatement between proposal and commit cannot change what is
   written (**confirm-hop integrity, P2 across the hop**). New source-isolation locks assert the propose
   channel (the tool body, the card builder, the staging store) never calls the write API. `propose_preference`
   is GUARDED and **lock-exempt** (D-1(a) below): it may fire under untrusted content, because the card's
   untrusted-context flag — not a lock — is the weak-signal defense; the #570 PA per-dispatch adjudication
   still runs on every dispatch.

3. **P4 budgets — three measured caps.** `PINNED_BLOCK_TOKEN_CAP=1024` (estimated), `PREFERENCE_BODY_MAX_CHARS=500`,
   `PREFERENCE_MAX_COUNT=64`, registered in `shared/preference_budgets.py` and gate-locked (the
   timeout-registry pattern). The token cap was **measured from the #711 S8 prefix-caching A/B**, not
   guessed: warm-hit cost is flat (~0.4–0.8 s at every size) while the binding costs — the one-line-edit
   re-prefill and the session-cold first turn — scale ~4.4 ms/token, putting an edit at ~4.2 s and a cold
   session at ~9 s at 1024 (both >2× at 2048). The cap is enforced at the single write door (a write whose
   candidate render would exceed it is refused) and backstopped by deterministic truncation in the renderer.

4. **Leak-feed treatment — RATIFIED as TRUSTED_MEMORY-mirroring.** The tier is treated as
   operator-authored by construction (P8 is the design's own answer to the injection-surface question), so
   a rendered preference is **not** fed to the Stage-5 cosine leakage detector — echoing the operator's own
   standing voice back to him is definitionally not a leak. M1 took this provisionally; this ADR ratifies
   it. Note the asymmetry with retrieval tiers: preferences are never retrieved (D-0), so unlike
   `UNTRUSTED_KNOWLEDGE`/`UNTRUSTED_WEB` (ADR-023 Am.2/3) there is no untrusted-content path to screen here.

5. **Contradiction confirm — one step, Jaccard-gated (D-3(a)).** A `/remember` (or confirmed proposal)
   that near-duplicates an existing row surfaces "this replaces: '<existing>' — confirm?" and, on confirm,
   supersedes in place (stable `pref_id`, audit row retained). The **deterministic Jaccard probe remains
   THE gating signal** — offline-testable, gate-locked; last-writer-wins never fires silently. The
   meaning-based (embedding) matcher is **committed, measured work — #796 — not shipped here** (the LA:
   "the smarter version is really where the value is"); if it proves out it becomes an *advisory* second
   signal that may ADD a confirm prompt, never remove one.

6. **Removal semantics — retractions are removals, never appended negations (§2.2a).** Store-side deletion
   is already TRUE removal (status→`deleted`, the row leaves the injected surface, the old text survives
   only as encrypted audit that never enters a prompt — negation-by-accretion is structurally impossible in
   the tier). The M2 gap the LA named — the model's natural response to "stop doing X" is proposing a NEW
   "don't do X" preference (the append-negation anti-pattern re-entering through the card) — is closed: the
   propose tool **supports proposing a delete/edit of the matching existing row** (the P5 probe locates the
   target; the card reads "remove/replace preference N: '<existing>'?"), and a proposed ADDITION that
   near-duplicates or negates an existing row is **steered to the retraction/replace card, never stored
   alongside it**. (The same rule binds the future M3 miner as a format lint — separate, #793.)

7. **Operator-stated expiry — the operator's bound, never the system's (D-4(a) + §2.2a).** An optional,
   operator-authored `expires` date drops a row from the **pinned render** on/after its date (inclusive —
   "answer in French until Friday" applies on Friday, gone Saturday) while `/preferences` still LISTS it,
   flagged expired. This does **not** violate P6: the *system* never decides to forget — only the
   operator's own stated bound applies, nothing is auto-deleted, and a preference with no stated expiry is
   unbounded exactly as before. Parsed at the gateway (`--until <date>` or trailing natural phrasing —
   ISO date, "tomorrow", weekday-name next-occurrence); an unresolvable clause stays in the body verbatim
   (P2 — "wait until I say so" is not an expiry).

8. **Card surface — built once in the shared backend (D-2(a)).** The confirm card is rendered by one
   shared builder (`shared/ipc/preference_proposal.py`): verbatim proposed text (display-sanitized so a
   body cannot break the card frame or forge a datamark) + type tag + **provenance sized to the source**
   ("your last message" vs "a document you loaded" vs "content recalled from your knowledge bank" vs
   "content from a document or web result") + a **grain-sized untrusted-context notice** when untrusted
   content was in the turn (Am.1, #792): a PROPORTIONATE notice when the operator's OWN curated
   knowledge-bank recall (`UNTRUSTED_KNOWLEDGE`) was the SOLE untrusted tier — his own content, so no
   alarm — versus the STRONG warning for a document / pasted-external / web-search result, where a hostile
   instruction could be hiding (the weak-signal defense). Any mixed or unrecognized untrusted tier fails
   **safe to the strong warning**. The GATING is unchanged — knowledge recall still trips the Layer-3
   action-lock exactly like a document (ADR-023 Am.2); only the disclosure grain differs, so an
   auto-recalled knowledge bank in a fresh session no longer mis-reads as "a document or web result." The
   WinUI renders it as a Save/Dismiss card; every text-only surface shows the same readable text (which
   names the exact commands). Both emit the identical operator-typed
   `/remember-confirm`/`/remember-dismiss` — the operator's action is the write authority.

9. **Dormant implicit-extraction lane (recorded, not built).** Program P1's implicit half stays dormant.
   If ever revisited, the governance shape is fixed here: a separately-privileged background job whose
   output is **proposals into the M2 card flow, never writes** (study verdict row 10, the Letta shape). It
   does not get its own write path; it reuses the propose→confirm corridor this ADR governs.

## Self-modification classification (the ADR-022 taxonomy stamp)

Within the devplatform cf-program ADR-022 self-modification-surface taxonomy, the operator-preference
tier is classified as follows:

- **Surface:** an auto-injected, cross-session behavioral-context store (highest-risk class — the MINJA
  precondition). **Read** by the model (it is in every system prompt); **draftable** by the model in M2
  (the `propose_preference` card); **writable** only by the operator.
- **Control:** the MINJA precondition is killed **structurally** — the model-reachable write path does not
  exist (P8 structural-absence locks), the proposal channel is source-isolated from the write channel
  (Decision 2), and the write authority is an operator-typed command. This is stronger than the certified
  SMSR HMAC defense (study §5.1): the write path is absent, not merely authenticated.
- **Residual, tracked:** the weak-signal induced-proposal window (a hostile document nudging a plausible
  proposal the operator rubber-stamps). Mitigated by the card's verbatim body + provenance + untrusted flag
  (Decision 8), which the poisoning red-team eval (`poisoning_redteam`, §6.7) measures per case (ASR/RSR).
  The C3 structural-absence tripwire in that suite fails loudly the day any consolidation/summarization
  path acquires a write to the tier — the arm-on-change control this classification requires.

## Consequences

- The tier is safe to auto-inject because it is operator-authored by construction and structurally
  unwritable by the model; the M2 propose lane adds reach (the model can *suggest*) without adding a write.
- Every preference is verbatim and never decays by system action; the operator's stated expiry is the only
  time bound, and it is honest (still listed, never silently deleted).
- The Jaccard-only contradiction signal will miss paraphrase-contradictions until #796 lands; the operator
  can always see both rows in `/preferences`, so the failure mode is visible-not-silent.
- The poisoning posture is legible in one place (the eval suite) in the published MPBench ASR/RSR frame,
  suitable for external contribution if ever offered.

## Rejected alternatives (on the record)

- **Propose-refuse under untrusted content (D-1(b)):** kills the weak-signal window but also kills
  legitimate captures in knowledge-heavy sessions (exactly where corrections happen) and trains the
  operator that capture is flaky. Rejected — the card flag is the judgeable defense (D-1(a)).
- **Provenance in audit only, no card flag (D-1(c)):** removes the operator's only weak-signal defense.
- **Retrieval over the preference tier:** adds recall risk + a poisoning retrieval surface for zero reach
  at this scale (D-0).
- **Build both Jaccard + embedding matchers in W2 (D-3(b)):** the meaning-based check is real value but
  unproven; shipping it unmeasured risks false-confirm fatigue. Deferred to the measured #796 study.
- **Defer expiry to the episodic tier (D-4(b)) / reject it permanently (D-4(c)):** leaves expired rules
  rendering until manually deleted and teaches the operator to distrust `/remember` for temporary things.
- **A content classifier / tripwire on proposal text:** rejected on the same grounds as ADR-033 — the
  control is governance + the operator's judgeable card, not a classifier.

## References

- Iteration plan: `docs/research/preference_memory_m2_m3_iteration_plan_2026-07.md` (committed blarai
  `8d3a9c63`; D-0..D-7 index in §5; §2.2a removal semantics).
- External design study: `docs/research/assistant_memory_reference_study_2026-07.md` (§5.1 defenses, §5.2
  MPBench taxonomy, §5.3 FAMA).
- Code: `services/assistant_orchestrator/src/knowledge_bank.py` (the tier + store),
  `services/assistant_orchestrator/src/preference_block.py` (renderer + expiry filter),
  `services/assistant_orchestrator/src/entrypoint.py` (the write door + propose handler),
  `services/assistant_orchestrator/src/proposal_staging.py` (confirm-hop staging),
  `shared/ipc/preference_proposal.py` (the shared card builder),
  `shared/preference_budgets.py` (the P4 caps).
- Locks: `services/assistant_orchestrator/tests/test_preference_write_authority.py` (P8 + source
  isolation); `evals/suites/preference_memory.py` §6.7 (`poisoning_redteam`, the MPBench frame).
- Cross-repo taxonomy: `C:\Users\mrbla\devplatform\docs\adrs\` ADR-022 (self-modification surface taxonomy).
