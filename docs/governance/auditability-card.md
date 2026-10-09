---
title: Auditability Card
status: living
area: governance
---

# BlarAI Auditability Card

**Written 2026-09-17 under #1544, sprint 19.** Shaped to the Auditability Card from *Auditable
Agents* (arXiv 2604.05485), whose six questions are the section headings below. Its purpose is the
one PCAA's enforcement-depth disclosure names: **find any surface that is observer-only without
anyone having said so.**

**Every row was traced for this document rather than taken from a design note.** Where a claim could
not be established by reading the code, it says so.

---

## 1. Which actions are recorded?

| Surface | Interception depth | Writes to the signed audit chain? |
|---|---|---|
| **AO tool loop** (`_adjudicate_tool_dispatch`) | **Inline pre-execution gate.** Builds a CAR, runs the Policy Agent's own `DeterministicPolicyChecker.check` in-process, refuses before `tools.execute`. | **Yes**, since #1542 (`dc0b8623`). Every dispatch verdict writes one receipt to the VERDICT chain, allows and refusals both, `source_door="ao_tool_dispatch"`. **An allow that cannot be recorded REFUSES** — fail-closed, because a chain missing its allows is evidence of nothing. A refusal that cannot be recorded logs at ERROR and stands, the action having already not happened. |
| **Egress door** (`guarded_fetch.fetch_external`) | **Inline pre-fetch gate**, plus resolve-and-recheck against the single deterministic allowlist. Note it **returns** a denial rather than raising, so what the operator sees depends on the caller: the web-search adapter swallows it to an empty result (refusing the *fetch*, not the *turn*), while the ingest coordinator surfaces it verbatim — *"URL ingest refused: {reason}. Nothing was fetched into the knowledge bank."* An earlier version generalised the silent case to all callers, which got a fail-loud path exactly backwards. `fetch_external_binary` is a second door function on the same module. | **Yes**, since #1542 (`dc0b8623`), via the receipt sink the AO registers at boot (`_register_egress_receipt_sink`), `source_door="guarded_fetch_egress"`. Allows and denials both. The sink first shipped with no production caller — a registration seam nothing called, while three docstrings said otherwise — and that is now gate-locked. |
| **Post-Generation Output Validator** (`validate_output`) | **Post-generation gate** at the `output` point — but it runs *after* `_on_stream_chunk` has already shipped tokens to the client, so on a non-approval the raw text has already left. It replaces the *stored and final* answer with a fallback and skips the knowledge ingest; it does not un-send what streamed. That is #1547's subject and has its own disposition. An earlier version described it as a clean replace. | **No** — and this row was PREDICTED to change with #1542 (see the limits at the end of this document) and did not. `grep source_door=` returns exactly two values in production, and neither is this door. |
| **URL adjudicator** (`ui_gateway/url_adjudicator.py`) | **Inline gate** for operator-pasted URLs; calls the same `DeterministicPolicyChecker.check`. | **No.** |
| **Knowledge ingest** (`_build_ingest_audit_log`) | Inline. Was the only surface writing receipts until #1542 added the two doors above. | **Yes.** SUBMIT/APPROVE/REJECT, TPM-signed, hash-chained. Verified on load since #1543. |
| **Policy Agent adjudication chain** *(a record SINK, not an enforcement point — listed for coverage)* | Constructed at PA boot; verified on load since #1543. | **Configured, never written**, and the reason is structural rather than observational: `grep -rn "AdjudicationRequest(" --include=*.py` outside tests returns **zero production constructors**, so `adjudicate_car` is unreachable in production. An earlier version argued from an empty directory, which is gitignored, absent from every worktree, and overridable three ways — an inference that did not follow even though its conclusion was right. Consistent with ADR-041 recording the Agentic-JWT dual-gate receipt machinery as vestigial. |
| **Coder-fleet dispatch** (`_handle_execute_request` → `shared/fleet/dispatch.py`) | **Inline gate, and a NAME-BASED one.** `validate_repo` checks path components against `_FORBIDDEN_REPO_ROOTS = ("BlarAI", ".openclaw")` plus containment. **LIVE** (`[fleet_dispatch] enabled = true`, GO-LIVE 2026-06-27). See §7. | **No.** |
| **Coordinator proposal staging** (`shared/coordinator/governed_core.py`) | Inline identity gate — four layers — but at **DoR filtering and proposal staging**, not at dispatch execution. | **No.** |

**So: two chains are written — ingest and verdict — by three enforcement points, and four enforcement points still decide without leaving a durable record** (the output validator, the URL adjudicator, coder-fleet dispatch, and coordinator proposal staging).

An earlier version said "seven enforcement points, one writes records". That count was wrong in
both directions: it counted the Policy Agent chain, which is a record **sink** with no client and
cannot intercept anything, and it omitted the live coder-fleet dispatch door entirely (§7). The
sentence people would have quoted was the least-verified line in the document.

Two further *writers* not listed above, neither reachable as shipped:
`services/policy_agent/src/adjudicator.py` (`_persist_context_with_car`, production-wired but dead
for the reason in the PA row) and `audit_log.py`'s `RETENTION_PRUNE` self-append. Neither adds a
surface to the count above.

---

## 2. Which lifecycle phases are covered?

**BlarAI emits at ONE of the eight intervention points today: `pre_tool_call`.** Since #1542 the
dispatch door and the egress door both write there, and `pre_tool_call` is the only value any
production call site passes — the parameter defaults to it and nothing overrides it. The other
seven points emit nothing.

An earlier version of this section said "emits at four, not at the other four", which was wrong
twice over: it used the design document's *planned* mapping as a present-tense fact, and it misread
that mapping, swapping `agent_startup` (planned: emitted) for `input` (planned: not emitted). The
4/4 arithmetic read clean, which is why nothing looked wrong. Worse, the point that made the count
four rather than three is `agent_startup` — a Policy-Agent boot receipt on the chain §1 shows has
never had a record appended.

**The planned mapping** — still only partly built; #1542 delivered `pre_tool_call` alone — is four emitted (`agent_startup`, `pre_tool_call`,
`post_tool_call`, `output`) and four not (`input`, `pre_model_call`, `post_model_call`,
`agent_shutdown`) — per `acs-vocabulary-adoption-design-2026-09-16.md`, which is the surface that
owns it.

Stated plainly because it is the honest form of the claim: **BlarAI has no record of what the model
was asked or what it replied** at the policy layer. Prompt and response live in the session store,
governed by a different mechanism with a different purpose.

---

## 3. Which policies are mechanically checkable?

The deterministic rules in `DeterministicPolicyChecker.check` are pure Python, stateless and
locked by tests. They are checkable by reading them.

**A limit found while writing this card, and a retraction that belongs with it.** The AO dispatch
CAR pins `verb` to `EXECUTE`, `resource` to one of eight fixed strings, and `parameters_schema` to a
single opaque argument string, which does make several ESCALATE rules unreachable — the two
requiring `WRITE` and the three matching on `resource`.

**An earlier version of this card said no live tool could produce an ESCALATE verdict at all, citing
two sweeps of 104 and 64 combinations. That is false.** Four of the eight tools escalate on a plain
English query containing an unquoted `reviewed: false` — RULE 8 regexes the serialised arguments,
and a JSON-*quoted* payload escapes to `reviewed\": false` which cannot match while an unquoted one
survives and does. **Both sweeps fed quoted payloads, so neither could have produced the trigger**,
and their agreement was cited as independent confirmation. Agreement is only evidence when the two
figures could have disagreed.

What the corrected picture shows is worse than the claim it replaces: `ESCALATE_UNVERIFIED_CODE`
fires on the **user's phrasing**, not on any property of the action. Asking "was it reviewed: false?"
escalates a `calculate`. Tracked as **#1573**, retitled.

---

## 4. What is the responsibility chain?

Operator → UI surface → gateway → Assistant Orchestrator → the door for the action class. The
operator is the only approver; there is no delegation and no service account.

**Known break, tracked as #1574:** at an escalation the operator is shown `EXECUTE tool:<name>` and
nothing about the arguments, while the approval is cryptographically bound to those arguments
(#1541). The machine half of the binding holds; the informed-consent half does not.

---

## 5. What integrity protection do the records have?

The chains that are written are SHA-256 hash-chained and signed — TPM-backed ECDSA P-256 in
production, HMAC in dev. Sealed segments are anchored by a signed index. Since **#1543**, both
production constructors verify on load and **refuse** a chain that does not verify.

**Two limits, both measured:** verification is chip-bound at 7–13 ms per signature, so the
production active-segment ceiling is clamped to 1,000 records to keep boot affordable (ADR-029
Amendment); and the boot budget prices only the active segment while the clamp multiplies sealed
segments — tracked as **#1571**. `verify(full=True)` exists and **no production caller invokes it**;
the coverage argument rests on the boot-time anchor check.

---

## 6. What happens when logs are missing?

The Policy Agent **refuses to start** in production with no audit path or an unverifiable chain. The
ingest sink raises, and its caller disables the knowledge feature loudly while chat survives. Both
are fail-closed and neither degrades silently.

**The honest asymmetry:** those postures protect the chain that *is* written. The six surfaces that
write nothing have no missing-log condition to detect, because they have no log.

---

## 7. The finding this card was written to surface

The ticket predicted the coder-fleet dispatch row would surprise, because its interception depth had
never been traced. **The first version of this card got it wrong in the direction that flatters the
system, and the correction is the finding.**

That version credited the dispatch path with `shared/coordinator/governed_core.py` — an inline
identity gate with four independent layers, including a content sentinel that catches a renamed
clone. That module is real and correct, and **it does not run on the dispatch path.** Independent
review established it by execution; this session re-verified it. The execute-request handler
contains **zero** references to `governed_core`, `check_target` or `assert_workspace_target`.

**What actually gates the live dispatch is `shared/fleet/dispatch.py::validate_repo`, and it is
name-based:** `_FORBIDDEN_REPO_ROOTS = ("BlarAI", ".openclaw")`, casefolded path components, plus a
containment check. The discriminating case, run against both real objects: a **renamed clone** of the
governed core placed under the projects directory is **denied by `governed_core`** and **accepted by
`validate_repo`** — the gate that runs.

This matters because the dispatch is live, and because the code calls it *"the single most
destructive op (evict the 14B, take over the box)"*. ADR-039 §2.2 names `_FORBIDDEN_REPO_ROOTS` as
precisely the check identity-based membership was meant to replace. It is still the live check.

**And ADR-039 §2.6 requires more than severance here**, which the earlier version of this section
also got wrong. It specifies that coordinator dispatches are *"adjudicated first-class"*, reduced to
a CAR carrying the Coordinator's own `source_agent`, riding the same adjudication path. So the
absence of a CAR on this surface is not a defensible design choice under ADR-039 — it is
**ADR-039 §2.6 unbuilt**. The earlier text cited that ADR as authority for an absence the ADR
forbids, and called it "not a defect". That was wrong on both counts.

**The honest finding, which is what the ticket went looking for:** BlarAI's most destructive live
surface is guarded by the weakest of its gates, a strictly stronger gate for the same question
exists in the tree and is not wired to it, and the ADR governing the surface mandates an
adjudication path that was never built. Tracked as **#1576**.

## What this card does NOT establish

- It does **not** cover the vsock guest services. The ticket names them; they were not traced, and
  claiming coverage from the other rows would be exactly the failure this document exists to
  prevent. **Open.**
- Interception depth is read from code, not observed under load. Only the AO tool loop and the
  egress door have been driven end-to-end in this sprint.
- "Writes no record" is the *current* state, re-traced 2026-09-20. #1542 (`dc0b8623`) changed it
  for the first TWO rows, not the three this note previously predicted — the output validator
  still writes nothing. This document asserted the pre-#1542 state for two days because it merged
  two hours BEFORE the change that falsified it and nothing re-opened it, while #1583 put it on a
  screen in the meantime.
