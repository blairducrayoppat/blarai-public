---
title: "#1547 deny-mid-stream persistence trace — disposition"
status: final
area: security
---

# Disposition — #1547 (can a denied turn leave partial assistant text in the encrypted store?)

**This ticket is a read-only investigation, so its "findings" are its own.** The disposition below
dispositions what the trace found rather than what a reviewer found about a change — there is no
code change to review. The investigation ran in two stages: a static trace of the persistence path,
then a live probe driving the real `_handle_prompt_request` through the real connection handler.

**The answer is YES, and it is live rather than latent.** The three paths this ticket names are
clean. A fourth class it does not name is not.

```disposition
# finding | status | evidence-or-predicate
THE ANSWER — a denied turn DOES leave the artifact of the denied action in the encrypted store, marked "approved". Measured by driving the real _handle_prompt_request and capturing the PGOV_RESULT frame the dispatcher persists: on a Policy-Agent DENY the persisted text is '<tool_call>{"name": "get_current_time", "arguments": {}}</tool_call>' with approved=True, against a control where an undenied turn persists the model's real answer ("It's 3pm.") | DEFERRED | #1575 blocked-by: an LA decision on what a denied turn should persist, recorded as a comment on #1575. Observable: a comment from the operator on that ticket. This ticket is READ-ONLY by its own description ("no code change from this ticket itself"), and its stated deliverable is "a finding recorded on this ticket with file:line evidence and, if partial text persists, a hardening ticket of its own" — #1575 is that ticket. The posture question is genuinely his: the three existing deny paths already disagree with each other, two persisting help text as approved and one persisting a fallback as denied, so there is no house answer to inherit
the persistence chain, established link by link rather than assumed | REJECTED | Not a defect at all — recorded as the evidence standard this finding rests on. (1) dispatcher.py:852-856 calls add_turn with pgov.sanitized_text and status "approved" when pgov.approved; (2) session_store.py:882+ validates ONLY the role, encrypts the content verbatim and inserts, with no content filtering; (3) entrypoint.py:7246 ingests the same text into substrate.db. Each read directly. The frame was measured; the three links were read
the persisted status is "approved", which makes it REPLAYED rather than merely retained — transport.py:2334-2337 builds prompt history from user turns plus assistant turns where pgov_status == "approved", and the substrate carries it across sessions | DEFERRED | #1575 blocked-by: an LA decision on what a denied turn should persist, recorded as a comment on #1575. Observable: a comment from the operator on that ticket. This is why the finding is a privacy posture matter and not only a hygiene one: the artifact of a refused action re-enters the model's context on later turns
the output validator cannot catch it, structurally — entrypoint.py:116 imports TOOL_CALL_ALLOWLIST FROM pgov, and Stage 4 flags only names OUTSIDE that set, but any tool call reaching the adjudication had already passed the allowlist check, so it is allowlisted by construction | REJECTED | Rejected as a PGOV defect. PGOV is behaving correctly for what it is: a check on tool names it does not recognise. The defect is that four break paths hand it text they should have replaced first, which is #1575's subject. Fixing PGOV to object to allowlisted tool-call text would make it reject legitimate content
the code comment at the Policy-Agent deny break reads "PGOV sees the text", which is true and useless — PGOV sees it and has no rule that objects | DEFERRED | #1575 blocked-by: an LA decision on what a denied turn should persist, recorded as a comment on #1575. Observable: a comment from the operator on that ticket. The comment sits inside the break #1575 rewrites, so correcting it there is one edit instead of two, and editing it here would ship a code change from a ticket whose own description says it ships none
the three paths this ticket NAMES are clean, and that is not retracted — the Layer-3 lock and the egress envelope both dataclass_replace the text before validation so the model's text is structurally discarded, and the PGOV output fallback persists FALLBACK_MESSAGE with status "denied" and skips the substrate ingest entirely | REJECTED | Rejected as a finding: these are correct. Recorded because a reader of the headline could easily over-read it into "denials leak", which is false. The defect is confined to the fourth class — the Policy-Agent deny, the allowlist miss, a tools.execute exception, and the grounding fail-closed — which are the breaks that do not rewrite generation.text
the egress door's deny never ends the turn at all — fetch_external RETURNS a FetchResult(denied_reason=...) rather than raising, live_adapter.py:336-341 swallows it to [], and the loop continues to a normal answer. The ticket's framing of it as a turn-ending deny path is wrong | REJECTED | Rejected as a defect and accepted as a correction to the ticket's premise. The behaviour is deliberate and safe; the ticket's description simply mis-describes which paths end a turn, and this record is where that is noted
a method-level trap that nearly cost a whole UI surface: ui_shell's two add_turn writes do not match a naive `add_turn(` grep, because they are passed as bare callables to asyncio.to_thread | FIXED | e9847958 — FIELD_NOTES, 'Searching Python for call sites'. Anyone re-running this trace with that grep alone will miss an entire persistence surface
the live probe injected the Policy-Agent DENY verdict, because none of the eight shipped tools produced DENY on the payloads tried — so which LIVE inputs reach these breaks is not established | DEFERRED | #1573 blocked-by: #1541 merged (already true — c2c3737d). Observable: grep for _operator_approved_dispatch in services/assistant_orchestrator/src/entrypoint.py on merged main. #1573 owns the question of what the dispatch CAR can express; the reviewer of #1541 measured 8 DENYs across 104 combinations, so the break is reachable, but pinning the live inputs belongs with the ticket that owns the CAR's narrowness
```

## Limits of this investigation, stated plainly

- The `PGOV_RESULT` frame was **measured**; the three links from that frame to an encrypted row on
  disk were **read**, not observed. A decrypted read-back of `sessions.db` would close the last
  inch, and it is named as the first step of #1575 rather than claimed here.
- The DENY verdict was injected. What the probe establishes is *what happens when that break
  fires*, not *how often it fires in ordinary use*.
- `tools.execute` exceptions and the grounding fail-closed break were traced statically and
  reasoned to be in the same class as the measured one, because they share the property of not
  rewriting `generation.text`. Neither was driven.
