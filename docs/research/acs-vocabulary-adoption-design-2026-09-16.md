# Adopt the Agent Control Specification as a vocabulary, not a dependency

*Written 2026-09-16. Fifth document in the research set on #1537. The first four established that neither Microsoft Agent Framework nor the Agent Governance Toolkit should enter BlarAI's runtime, and that the reusable assets in that stack are the Agent Control Specification (ACS) text and its reserved-reasons list, with its conformance fixtures still to be read (**they were read on 2026-09-17 under #1570 — see the SUPERSEDED banner at "Testing against the specification without running its engine"; **zero of 70 across BOTH suites are runnable against BlarAI's doors**, and the count of 49 referred to a different suite than the first pass examined**), and the CAVA open-core package's approval-binding code as a second reference. This document is the design for using those assets: what BlarAI adopts, what it refuses, how each of BlarAI's existing doors maps to the specification's names, and what the signed receipt and the approval binding look like when written in that vocabulary. Nothing here is built. Specification citations are to `policy-engine/spec/SPECIFICATION.md` in the toolkit clone at `c63c51e8`; BlarAI citations are to commit `39a9ee2b`.*

## Outcome first

**BlarAI should write its own doors and receipts to the ACS vocabulary and import nothing.** The specification is MIT-licensed and framework-neutral. Its eight intervention point names, its closed verdict set, its two closed namespaces of reserved reasons, and its content-bound action identity are a naming standard. BlarAI's existing 150-line checker, its Canonical Action Representation (CAR), and its TPM-signed audit chain are the implementation. The work is the five receipt items already proposed in the comparison documents; the specification tells you what to call the fields so that a reviewer who knows it can read BlarAI's receipts without a glossary.

**What this buys.** Receipts that an outside reviewer, a certification assessor, or a future BlarAI session can read against a public document rather than against BlarAI's private conventions. No new dependency, no exemption in the import scan, no second adjudicator, no exposure to the specification's alpha release train beyond a pinned version string and one test that fails if the names drift.

**What this is not.** It is not conformance. BlarAI will not run the ACS engine, will not load manifests, will not evaluate Rego or Cedar, and must never describe itself as "ACS-conformant" unless the conformance suite has actually been run against its doors. The right phrase is "ACS-vocabulary aligned", and the receipts should say which version.

## What is being adopted, section by section

Each item names the specification section, quotes or paraphrases the rule, and states BlarAI's position.

**§1.1 Invariants: stateless, deterministic, fail-closed, no I/O during evaluation.** "The runtime is deterministic. Two evaluations with the same manifest, snapshot, mode, and dispatcher results MUST produce the same verdict." "The runtime fails closed. Any error during evaluation MUST yield a `deny` verdict whose reason is one of the reserved identifiers." BlarAI's checker already satisfies all four: it is a stateless class method, pure string and path logic, every exception is DENY, and it does no network or file I/O (one log line inside the RULE 3 carve-out is its only side effect). This section is adopted as a statement of what the checker already is, and it should be quoted in the checker's docstring so the property is named rather than implied.

**§4 Eight intervention points, a closed set.** `agent_startup`, `input`, `pre_model_call`, `post_model_call`, `pre_tool_call`, `post_tool_call`, `output`, `agent_shutdown`. "A host MUST NOT invent new identifiers." Adopted as the `intervention_point` field on every receipt. BlarAI will emit at four of the eight and must say which four (see the mapping below). Not emitting at a point is honest; inventing a ninth is not.

**§7 and §8 The canonical policy input and its serialisation.** The specification hashes a five-member object (intervention point, policy target, snapshot, annotations, tool) serialised with sorted keys. BlarAI's canonical input is the CAR, already serialised with sorted keys and compact separators by `canonical_hash()`. Adopted in spirit: BlarAI's identity is a SHA-256 over its own canonical input, and the receipt must say which input shape produced it. Not adopted: the five-member object itself, which presumes a manifest-driven engine BlarAI does not run.

**§13 and §13.1 Verdicts and action identities.** Decisions are `allow`, `deny`, `transform`; `warn` normalises to allow with a warning; `escalate` normalises to "a `deny` carrying an `approval` block". Two identities, `input_identity` and `enforced_identity`, each "`sha256:` followed by lowercase hexadecimal", equal whenever no transform applied. Adopted: the three-valued decision, escalate-as-liftable-deny, and the `sha256:` identity encoding. BlarAI has no transform path, so `transform` is a reserved value the receipts will never carry, and the two identities will always be equal. Both facts go in the receipt schema's docstring.

**§16 Reserved reasons, two closed namespaces.** `runtime_error:*` is emitted by the engine; `host_error:*` by the host. "A host MUST NOT invent new identifiers in either set." Adopted with one BlarAI-specific rule: BlarAI's rule names (`DENY_RESTRICTED_PATH`, `ESCALATE_CRYPTO_MATERIAL`, and the rest) are *policy* reasons, which the specification permits freely as long as they do not start with `runtime_error:`. Operational failures map to reserved reasons where one fits and to a `detail` field outside the reason namespace where none does. The mapping is given below.

**§17 and §17.1 Host obligations and the approval path.** "In `enforce` mode the host MUST NOT carry out the action of a `deny` verdict; when that `deny` carries an `approval` block it is liftable." "The SDK MUST rederive the `enforced_identity` from the current policy input before proceeding and MUST fail closed with `host_error:approval_identity_mismatch` when it differs from the approved identity." "When no approval path is configured, or when the path fails or returns an unrecognized outcome, the host MUST fail closed." Adopted whole. This is the design for closing the approval-binding gap, and it matches what BlarAI's tool loop already does for the deny and no-verifier cases; the missing piece is the identity re-derivation.

**§19 Telemetry and audit.** "An audit record SHOULD record the intervention point, the mode, the verdict, the reason, the error class for runtime errors, and the action identities when available. It MUST follow the same redaction rule as telemetry so that it carries no sensitive value." "The runtime MUST NOT emit policy target values, tool arguments or results, annotation values, model messages, secrets, or personal data." Adopted as the receipt's minimum field set and its redaction rule. BlarAI's escalation context already follows the redaction rule by construction; the receipt inherits it.

**§22 Versioning.** The specification is `-alpha`, status Draft, and "an implementation SHOULD pin the exact version it targets." Adopted: a single constant `ACS_VOCABULARY_VERSION` recorded on every receipt — **whose value is UNRESOLVED and must not be pinned to `0.4.0-alpha.3` without checking.** That string traces to a CRATE RELEASE version in the sibling verdict document, and every one of the 23 conformance cases machine-scanned under #1570 declares `agent_control_specification_version: 0.4.0-alpha.1` inside its manifest. A package version may have been promoted to a specification version. The only versions verified from artefacts are `AGENT-HOOKS-0.1`, SDK `0.1.0-alpha.3`, CTK tag `v0.1.0-alpha.3`, crate tree `a830ed5`, and spec `0.4.0-alpha.1` as declared by the cases, and a gate test that holds the eight point names and the reserved-reason list as literals so that a future re-pin is a deliberate, reviewed change.

## What is deliberately not adopted

- **The engine, in any language.** No crate, no wheel, no shim. The verdict document gives the reasons from the source of both the toolkit and the crate: a compiled-in HTTP client, alpha status on a separate release train, and no receipts.
- **Manifests, Rego, Cedar, annotators, URL-loaded policy.** BlarAI's policy is ten rules in Python locked by 49 tests. Nothing today needs a policy language. If a second engine is ever wanted for expressiveness, Cedar is the candidate because it embeds without a subprocess, but it would *replace* the checker behind the same door, never sit beside it, under the single-adjudication-door principle.
- **The `transform` verdict.** BlarAI does not rewrite tool arguments or outputs under policy. Reserved, unused, documented as such.
- **The wall-clock timestamp inside the hashed input.** ACS hashes a snapshot that includes a timestamp, which makes every approval unreplayable even for identical arguments on a later turn. BlarAI's CAR hash already excludes timestamp and request id, which is the right choice here, because the per-turn envelope's "one touch covers up to three searches" behaviour is an LA decision and would break under a timestamped identity. Expiry is by turn, not by hash.
- **`result_labels` and information-flow control.** The specification's return channel for labels is designed for a host that propagates taint. BlarAI's provenance layer is one-axis today. When a confidentiality axis is added (proposed item 5 in the comparison document), this channel is the shape to reuse. Not before.

## Mapping BlarAI's doors to the vocabulary

| BlarAI surface | File | Intervention point | Policy target (never recorded, only hashed) | Verdict producer | Outcomes today | Outcomes in the vocabulary |
|---|---|---|---|---|---|---|
| Tool-loop dispatch check | `services/assistant_orchestrator/src/entrypoint.py` `_adjudicate_tool_dispatch` | `pre_tool_call` | CAR: verb EXECUTE, resource `tool:<name>` or the Kagi endpoint, canonical args | `DeterministicPolicyChecker.check` | None (allow), DENY, ESCALATE | `allow`; `deny`; `deny` with approval block (liftable) |
| Layer-3 untrusted-content action lock | same entrypoint, before the checker | `pre_tool_call` | tool name and session provenance set | host control (not the checker) | refuse or proceed | `deny`, reason `LAYER3_UNTRUSTED_CONTEXT` (a policy reason, BlarAI-named) |
| Egress door | `shared/security/guarded_fetch.py` `_adjudicate` | `pre_tool_call` | CAR: verb EGRESS, resource URL, purpose | registered adjudicator, deterministic today | ALLOW, DENY, ESCALATE | as above; the empty-slot case is a BlarAI-named `deny` with a `detail`, see the reason table |
| Per-turn Hello envelope | `services/assistant_orchestrator/src/egress_envelope.py` | part of the §17.1 approval path, not an intervention point | session id, counter | host state | allowed, denied | approval outcome `allow` or `deny` on the enclosing `pre_tool_call` receipt |
| Escalation consent | `shared/security/escalation_consent.py` | the §17.1 approval path | rule label, tool name, summary, and (new) action identity | registered verifier (Hello, or the TUI prompt) | approved, denied | `allow`, `deny`, never `suspend` (BlarAI has no out-of-band resumption) |
| Injection scan on fetched bodies | `shared/security/injection_scan.py` via `guarded_fetch` step 4 | `post_tool_call` | fetched body | scanner, annotate-not-block | flags | `allow` with `warnings[]` (the `warn` intent) |
| Post-Generation Output Validator | `services/assistant_orchestrator/src/pgov.py` | `output` | assembled final response | six-stage pipeline | approved, fallback | `allow`; `deny` with reason from the stage that failed |
| Measured boot | `services/policy_agent/src/entrypoint.py` phases | `agent_startup` | none | boot ladder | booted, locked | one `allow` receipt per boot, or the process is not up |

Four points are emitted: `agent_startup`, `pre_tool_call`, `post_tool_call`, `output`. Four are not: `input` (the gateway does input validation but it is not a policy verdict today), `pre_model_call` and `post_model_call` (no policy runs at the model seam; PGOV covers the assembled output), `agent_shutdown` (no closure record exists). The receipt schema should carry this coverage statement as a constant so that a reader knows the absence of a `pre_model_call` receipt means "not instrumented", not "always allowed". This is PCAA's enforcement-depth disclosure done in ACS's terms.

## Mapping BlarAI's failure classes to reserved reasons

The specification's two namespaces are closed. BlarAI's rule names are policy reasons and need no mapping. The operational failures do:

| BlarAI failure | Where | Reserved reason | Fit |
|---|---|---|---|
| Checker raised; caught as `("DENY", "DENY_EXCEPTION")` | checker, last `except` | `runtime_error:policy_invocation_failed` | exact |
| Null CAR | checker, `DENY_NULL_CAR` | `runtime_error:path_missing` | close; the input the policy needed is absent |
| Adjudication error in the tool loop (`ADJUDICATION_ERROR`) | `_adjudicate_tool_dispatch` `except` | `runtime_error:policy_invocation_failed` | exact |
| No adjudicator registered at the door | `guarded_fetch._adjudicate` | none fits; `host_error:approval_unresolved` is about approvals, not adjudicators | use `deny`, reason `DENY_NO_ADJUDICATOR` (policy namespace, BlarAI-named), `detail` "door slot empty". Do not mint a `host_error:` name |
| Adjudicator raised or returned a malformed verdict | same | `runtime_error:policy_output_invalid` | exact for malformed; `policy_invocation_failed` for raised |
| Approval verifier absent | `escalation_consent` | `host_error:approval_unresolved` | exact |
| Approval verifier raised, timed out, returned None or malformed | same | `host_error:approval_resolver_failed` | exact |
| Approved identity differs from the CAR about to dispatch | new check in the tool loop | `host_error:approval_identity_mismatch` | exact, and the whole point |
| Tool not in the fixed allowlist | tool loop, before the checker | `runtime_error:tool_unknown` | exact |

Three of BlarAI's failures fit no reserved reason and get BlarAI-named policy reasons with a `detail` field. That is what the specification tells a host to do: "A host extends behavior through the `custom` policy type ... rather than by adding identifiers."

## The receipt

BlarAI's signed audit record already exists: `AuditLog.append` in `shared/security/audit_log.py` takes an adjudication id, a decision, the CAR hash, the CAR's source, destination, verb, resource and sensitivity, a rule-engine flag, a confidence, and a timestamp; it chains each record to the previous by SHA-256 and signs the canonical bytes with a TPM-held key in production. It serves the ingest path and the vestigial hybrid adjudicator. It does not serve the two live doors.

The design keeps the chain and the signer untouched and adds the vocabulary fields. Every field is a label, a hash, or an enum; no field carries a payload.

| Field | Source | Notes |
|---|---|---|
| `acs_vocabulary_version` | constant | `"0.4.0-alpha.3"` until re-pinned |
| `intervention_point` | the door | one of the four BlarAI emits |
| `mode` | constant | always `"enforce"`; BlarAI has no evaluate-only posture and should not add one silently |
| `decision` | verdict | `allow` or `deny`; `transform` reserved and never emitted |
| `liftable` | verdict | true when the deny carried an approval block (BlarAI's ESCALATE) |
| `reason` | verdict | a BlarAI rule name, or a reserved `runtime_error:*` / `host_error:*` identifier |
| `error_class` | verdict | present only for runtime errors; the exception type name, never its message |
| `detail` | door | short fixed strings only, for the three failures with no reserved reason |
| `input_identity` | `sha256:` + CAR `canonical_hash()` | the BlarAI canonical input; the docstring must say it covers source, destination, verb, resource, parameters, sensitivity and excludes timestamp and request id |
| `enforced_identity` | same value | equal by construction; kept so the record shape matches the specification |
| `approval_outcome` | approval path | absent, `allow`, or `deny`; never `suspend` |
| `approver_identity` | `ApprovalResult.verifier_identity` | which verifier answered (Hello, TUI prompt), never who |
| `source_door` | the door | `tool_loop`, `guarded_fetch`, `pgov`, `boot` |
| existing chain fields | `AuditLog` | `seq`, `prev_hash`, `record_hash`, `signature`, `timestamp_utc`, unchanged |

One existing field needs a decision. `resource` today would carry the URL at the egress door, and a URL can carry a query string with a secret in it. The specification's redaction rule forbids that. Two options: record only the host (`kagi.com`) in `resource` and let `input_identity` carry the full URL's contribution as a hash; or hash the resource field itself for EGRESS verbs. The first is simpler and reads better in an audit; it is the recommendation. This is a privacy posture choice and is the LA's, marked [PROPOSED].

**Non-execution proof.** Every `deny`, liftable or final, writes a receipt. That is the single largest change in observable behaviour: today a refusal is a warning log line. In PCAA's terms this is `non_execution_proof`; in ACS's terms it is simply a `decision: deny` record. The receipt for a lifted deny records both the original `deny` with `liftable: true` and, on the same `input_identity`, an `approval_outcome: allow` before execution.

## The approval binding

This is the concrete design for the gap every document has named first.

1. In `_adjudicate_tool_dispatch`, the CAR is built and checked. Its `canonical_hash()` is computed regardless of outcome and returned alongside the verdict.
2. On ESCALATE, the tool loop builds the `EscalationContext` as today and adds one new field, `action_identity: str`, holding `sha256:<car hash>`. It is a descriptor, not payload, so the no-payload rule in `escalation_consent.py` is unchanged. The `describe()` line can show its first twelve characters so the operator's prompt and the receipt can be matched by eye.
3. The verifier's `ApprovalResult` echoes `action_identity` back. A result without it, or with a different value, is treated as `deny` with `host_error:approval_resolver_failed`.
4. Immediately before `tools.execute`, the loop rebuilds the CAR from the tool name and arguments it is about to dispatch, recomputes `canonical_hash()`, and compares it with the approved `action_identity`. Mismatch is `deny` with `host_error:approval_identity_mismatch`, a receipt is written, and the turn ends. This is the §17.1 obligation word for word.
5. The approval is consumed once: the loop clears it after the comparison, so a second dispatch in the same turn with the same hash re-escalates. The Hello envelope's separate N-searches lease is unaffected; it governs a different question (how many egress queries one touch covers), and it stays exactly as the LA set it.

Regression locks, each driving real objects through the real entry point: approve one argument set and dispatch another, assert refusal and the mismatch reason on the receipt; approve and dispatch the same set, assert execution and two chained records; verifier returns a result without the identity, assert refusal.

## The five items, in this vocabulary

These are items 1, 2, 6, 8 and 9 from the comparison and PCAA documents, restated so the fields have their specification names.

1. **Wire both live doors to `AuditLog`.** Every verdict at `pre_tool_call` (tool loop and egress door) and `output` (PGOV) appends a receipt with the fields above. Lock: a real tool dispatch yields a chained, signed record whose `input_identity` equals the CAR hash.
2. **Bind escalation approval to `input_identity`.** The five-step design above. Lock: the three tests listed.
3. **Trace the deny-mid-stream persistence path.** Read-only. Determines whether a `deny` at `output` can leave partial assistant text in the encrypted session store, which the specification's spirit (verdict-gated persistence in Agent Hooks, "MUST NOT carry out the action of a deny") would forbid.
4. **Close every deny into a receipt.** Covered by item 1 once `liftable` and `approval_outcome` exist; called out separately because it is the behavioural change a reviewer will notice.
5. **Attach decision basis.** Add to the receipt: the exfil-screen detection labels (labels only), the provenance set active at the door, the tool's risk tier, and a hash of the effective `default.toml`. The specification does not name these fields; they are BlarAI's `custom` extension and should live under one `basis` object so the specification-named fields stay clean.

Items 1, 2 and 4 are one branch. Item 5 follows once the record shape has settled. Item 3 is a separate read-only session and should run first, because its answer might add a field to item 1.

## The Policy Agent itself

The right "replacement" for the Policy Agent remains subtraction under #910, which ADR-041 already decided: remove the idle listener, the JWT minter, the hybrid adjudicator and the GPU classifier that has never scored a live action; keep `DeterministicPolicyChecker.check`; and wire that function to the receipts described above. Nothing in this design adds to the Policy Agent. The vocabulary work and the #910 removal are independent and can land in either order, but the receipt fields assume the function is the only adjudicator, so #910 should not reintroduce a second one.

## Testing against the specification without running its engine

> ## CORRECTED 2026-09-17, SECOND PASS (#1570) — READ THIS BEFORE THE BANNER BELOW IT
>
> **The first banner answered the wrong question, and this correction is recorded in place rather
> than quietly rewritten.** The sentence this section opens with — "the verdict crate ships a
> 49-file conformance suite against the Agent Hooks contract" — **conflates two different
> artefacts**, and the first pass inherited that conflation and went looking at only one of them.
>
> **There are TWO conformance sets, in two repositories:**
>
> 1. **`responsibleai/agent-hooks` CTK — 47 scenario vectors.** Everything in the banner below is
>    accurate about these, including that **zero are runnable** against a hand-written door.
> 2. **`responsibleai/agent-control-spec` @ `a830ed5` — the crate's OWN `tests/conformance/` tree.**
>    This is almost certainly what "49" meant: `tests/conformance/cases` (**23**) +
>    `streaming/inputs` (18) + `bindings` (7) + `bindings/bundle` (1) = **49**. The sibling
>    landscape document attributes "49 conformance fixtures" to this crate, not to agent-hooks.
>
> **All 23 cases were fetched and machine-scanned, and they are the shape the plan below hoped
> for.** Every one is `operation: "evaluate"` with a `policy_response` input and an `expected`
> output. **No `model_script`, no mocked `tools`, no `RunRecord`** — the three things that make the
> agent-hooks vectors unrunnable are all absent. `spec-14-verdict-normalization.case-01` maps
> `{"decision": "block"}` to `deny` / `runtime_error:policy_output_invalid`;
> `spec-08-action-identity.case-08` maps an `escalate` to a `deny` carrying `action_identity` and
> `approval`. Those are rules BlarAI's deterministic checker could be driven against directly.
>
> **CORRECTED AGAIN, after reading all 23 rather than two.** An earlier version of this banner
> said the `manifest_yaml` is "identical boilerplate" in every case. It is not: there are **9
> distinct manifests across the 23**, so the engine's configuration — which intervention points
> exist, what the policy target is, which transforms are declared — is part of what each case
> tests. Generalising from two files to twenty-three was the same error this whole ticket is
> about, made one level down.
>
> **What the full triage shows.** All 23 are `operation: "evaluate"`, meaning *run the engine's
> evaluate with this manifest and this stubbed policy response*. **BlarAI has no manifest loader
> and no Rego evaluator, so none of the 23 is RUNNABLE either.** Zero of 70 across both suites.
>
> But unlike agent-hooks, some of their **rules** are portable in substance. The cases whose
> input→output mapping BlarAI's own checker could be held to, because they test verdict
> vocabulary rather than engine plumbing: `spec-14-verdict-normalization.case-01`
> (`{"decision":"block"}` → `deny` / `runtime_error:policy_output_invalid`) and
> `spec-08-action-identity.case-08` (`escalate` → `deny` carrying `action_identity` and
> `approval`, which is exactly #1541's rule). The remaining nineteen turn on features BlarAI does
> not have and does not intend to build — tool projection, annotators, the engine dispatcher,
> resource limits, information-flow control, the effects/transform model, and which of the eight
> intervention points a manifest declares.
>
> They also assert **six distinct `runtime_error:*` reasons**, a namespace the agent-hooks suite
> never exercises: `policy_output_invalid` (×6), `intervention_point_unknown`, `tool_unknown`,
> `policy_invocation_failed`, `transform_target_forbidden`, `resource_limit_exceeded`. Between the
> two suites, **both** reserved namespaces are covered.
>
> **Status (superseded 2026-09-17 by the disclosure): the applicability question is now SETTLED
> for both suites — zero of 70 runnable. This paragraph said 'REOPENED' while the block above it
> already said 'zero of 70', settling and un-settling within one banner; the disclosure at
> `docs/governance/acs-conformance-disclosure.md` is the answer it was waiting for.**
> No score may be published for either until suite 2 has been triaged with the same rigour, and
> whether BlarAI can be driven against these cases without a manifest concept is **not yet
> established** — it is the next thing #1570 does. What is already certain is that "zero
> applicable" was an answer about agent-hooks only, and was never an answer about this crate.
>
> ---
>
> ## SUPERSEDED 2026-09-17, FIRST PASS (#1570) — accurate about the agent-hooks CTK, and about nothing else
>
> **The agent-hooks fixtures were read.** This section assumed some of them have narrow, portable
> inputs a hand-written door could accept. **None of the 47 do.** Two corrections:
>
> **The count is 47 test cases, not 49.** Confirmed three ways: a direct listing of
> `conformance/vectors/` at the pinned tag; the byte-identical vendored copy inside
> `agent-control-spec@a830ed5`; and that repository's own `REPORT.md`, whose reference-host run
> reads *"46 passed, 0 failed, 1 skipped (capability-gated) of 47."* The 49 appears to come from
> counting files in the directory rather than test cases.
>
> **Zero of the 47 are runnable against BlarAI's doors.** Every fixture carries
> `scenario.model_script` — a mocked LLM turn sequence — and 41 also carry `scenario.tools`.
> Each additionally requires an `Interceptor` registered at all eight interception points, a
> `ScriptedInterceptor` replaying `interceptor_script`/`approval_script`, and an assembled
> `RunRecord` for `expect` to check against. `conformance/HARNESS.md` calls that scaffolding
> "the ~100-line shim a framework author writes".
>
> **`AH-CTK-072` and `AH-CTK-071` were opened and read in full** — the two this section named as
> most likely to port. `AH-CTK-072` ("resolution violating the §9 echo rule →
> `host_error:approval_identity_mismatch`", the exact subject of #1541) is a full scripted
> scenario: a mocked `wire_transfer` tool returning `UNREACHED`, a two-turn model script, an
> interceptor script, an `approval_script` carrying an `identity_override`, and an `expect` block
> asserting `interceptions_absent`, `tool_not_invoked` and an assembled records list. It is not a
> verdict-in/verdict-out case.
>
> **No conformance percentage may be published**, including "X of 47". A fraction implies BlarAI
> could attempt some of the suite's own pass bar; it cannot attempt one vector without first
> building the harness this document already declined to build — and declining it remains right,
> because conforming to the suite's eight interception points would mean reshaping four
> hand-written doors to fit a test rig.
>
> **What replaces the plan.** A mechanical criterion, applied to all 47 rather than a hand-picked
> sample: a fixture is *vocabulary-relevant* when its assertions reference a reserved-namespace
> reason or the approval-identity rule — the elements this document actually adopts. That yields
> **15 fixtures** (12 assert a reserved reason, 8 match on approval identity, union 15). **Not
> '15 of 47' — that is a score position and this is not a score.** The disclosure bars the form;
> and the criterion's second arm matches the bare token `identity`, which sweeps in four
> bigint/provider-fault vectors while missing the `approval_script` family, so the figure is a
> reading aid rather than a measurement. The suite
> asserts **7 distinct reserved reasons**: `host_error:context_invalid` (×4),
> `host_error:verdict_invalid` (×2), `host_error:transform_invalid` (×2),
> `host_error:approval_identity_mismatch`, `host_error:transform_conflict`,
> `host_error:composition_disagreement`, `host_error:no_interceptor`.
>
> **15 is not a denominator either.** Those 15 are exactly as unrunnable as the other 32 — same
> scenario shape. They are where the vocabulary is quoted from, and nothing more. Tests BlarAI
> writes from them are **BlarAI-native tests using ACS vocabulary**, never "CTK vectors passed".
>
> **Artefacts read, so the claim can be checked rather than trusted:** suite from
> `responsibleai/agent-hooks` at tag `v0.1.0-alpha.3`, sha
> `60647b160487cdefb5779301bcdaab65e05d73e8` — the version this document pins via
> `agent-hooks-sdk = "0.1.0-alpha.3"`. All 47 vectors machine-scanned for their top-level and
> `scenario` keys; `AH-CTK-072` and `AH-CTK-071` opened and read in full; `conformance/HARNESS.md`
> read; `agent-control-spec@a830ed5`'s `REPORT.md` and `PROVENANCE.md` used for the 49→47
> correction. Full disposition on Vikunja #1570.

The verdict crate ships a 49-file conformance suite against the Agent Hooks contract. Those fixtures exercise a manifest-driven engine and most will not apply to a hand-written door. Some may: the verdict normalisation cases (which shapes are invalid), the reserved-reason cases (which failures produce which identifier), and the approval identity cases (mismatch fails closed). One session should read the fixtures and pull across the ones whose inputs BlarAI's doors can accept, as BlarAI's own tests. Until that is done, BlarAI can claim vocabulary alignment and nothing more.

## Decisions for the LA, marked [PROPOSED]

- **Resource redaction at the egress door.** Host only in `resource`, full URL only through the hash. Recommended; privacy posture, so yours.
- **Naming.** "ACS-vocabulary aligned, version 0.4.0-alpha.3" in receipts and in any portfolio or certification write-up. Never "conformant" without the suite.
- **Coverage statement.** Publish which four intervention points BlarAI emits and which four it does not, in the receipt schema and in the security runbooks. Recommended; it is the honest form of the claim.

Everything else in this document is technical and mine to carry out once the roadmap places it.

## What was not verified

- The 49 conformance fixtures were not read; the claim that some apply is an expectation.
- `AuditLog.append` was read for its signature; whether adding fields changes the canonical bytes for existing ingest records (and so the chain's `verify()` for old segments) was not traced. It must be, before item 1.
- The `escalation_consent` verifier implementations (Hello, TUI prompt) were not read for how they would echo an identity; the design assumes the `ApprovalResult` dataclass gains one field.

## Sources

- `policy-engine/spec/SPECIFICATION.md` sections 1.1, 4, 7, 8, 13, 13.1, 16, 17, 17.1, 19, 22, and `policy-engine/spec/reserved-reasons.json` (schema version 2, the toolkit's copy; the crate's own `spec/` at `a830ed5` is schema version 1 and carries no `host_error:*` identifiers, so the `host_error:*` names adopted here are pinned to the toolkit's file), in `microsoft/agent-governance-toolkit` at `c63c51e8`; `policy-engine/LICENSE.acs` (MIT, responsibleai, 2026).
- `responsibleai/agent-control-spec` at `a830ed5` (15 September 2026): `engine/Cargo.toml` for the feature flags and dependencies.
- BlarAI: `shared/security/audit_log.py` (`append` at 769), `shared/schemas/car.py` (`canonical_hash` at 112), `shared/security/escalation_consent.py` (`from_pa_verdict` at 120), `services/assistant_orchestrator/src/entrypoint.py` (dispatch check at 302, escalate branch near 6878), `shared/security/guarded_fetch.py` (`_adjudicate` at 615), `services/policy_agent/src/gpu_inference.py` (checker at 349).
