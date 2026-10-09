---
title: "#1582 — one readable statement of what BlarAI is allowed to do, and the reassuring sentence it printed"
status: final
area: governance
---

# Disposition — #1582 (permission profile)

**Eight findings from an independent adversarial review, every one reproduced by the reviewer.
Four were blockers. The review confirmed the change's central claim about the uncovered case
and then demolished the corollary I had printed alongside it.**

**The finding in one line: the profile told a non-technical operator that a local model judges
every action no rule covers. Nothing does — the model is never consulted on a tool call at
all — and the sentence was wrong in the reassuring direction, in the one document whose entire
premise is that it contains no false statements.**

```disposition
# finding | status | evidence-or-predicate
BLOCKER 1 — THE PROFILE PRINTED A REASSURANCE THE SYSTEM DOES NOT OWE. It said an action no rule covers "goes to the Policy Agent, which decides using the model". `_adjudicate_tool_dispatch` is the only production consumer of `DeterministicPolicyChecker.check` and its own docstring says "the PA's GPU classifier is not invoked here"; `check` returning None means no rule objected, and at that door no objection means EXECUTE. Reproduced: `check(car) is None` and `_adjudicate_tool_dispatch(UNK) is None` for an unclassified tool. The review also corrected my ordering: the control that stops an unknown NAME is the `TOOL_CALL_ALLOWLIST` check, not the risk tier, and it sits AFTER the Layer-3 lock | FIXED | feat/1582-permission-profile — the section now states all three branches in the order they fire: an unknown NAME is refused by name before anything else; a callable-but-unclassified tool is DANGEROUS and refused outright under untrusted content; and in any other conversation IT WOULD RUN, because the rules catch known-bad actions and an action no rule mentions draws no objection. Locked by `test_the_profile_never_claims_a_model_judges_an_uncovered_action` (which refuses four separate reassuring phrasings) and `test_the_profile_says_an_unclassified_tool_WOULD_RUN`. Mutating the honest sentence back to the reassuring one fails both
BLOCKER 2 — THE REFUSAL CLAIM WAS WELDED TO THE WRONG CONDITION. The REFUSED paragraph branched on `[pgov].block_tools_on_untrusted_content` alone. The lock's own predicate is `tier != SAFE`. Review mutated `risk_tier`'s fallback to SAFE: enforcement stopped refusing and the display kept its confident paragraph, while also printing "the most restricted setting, not the least" — a stored editorial claim reassuring the operator about the exact loosening it should have flagged | FIXED | feat/1582-permission-profile — `UncoveredBehaviour.tier_is_locked_under_untrusted_content` is computed from the lock's own predicate, and both the REFUSED paragraph and the "most restricted setting" line are conditional on it. `test_a_SAFE_fallback_tier_removes_the_refusal_claim` drives the real `risk_tier` through a monkeypatched fallback and asserts the paragraph is replaced by a WARNING
BLOCKER 3 — THE OUTPUT CONTRADICTED ITSELF ON THE RE-WELD PATH. The outbound section rendered from `_EGRESS_TOOLS` independent of the capability flags, so with `[web_search].enabled = false` — step 1 of the re-weld runbook — one page said both "Search the web - switched off" and "web_search leaves this machine". The operator verifying a re-weld was told the thing they had just switched off still reaches the network. No test caught it because the toggle test used `image_generation`, a NON-egress capability, so the interaction was never exercised | FIXED | feat/1582-permission-profile — `Profile.egress_tools_live` is the outbound set filtered by its governing capability, via an explicit `_CAPABILITY_TOOLS` map, and the outbound section renders from it. `test_switching_off_the_web_capability_removes_it_from_what_leaves` performs the actual re-weld step on a real config copy. `test_every_outbound_tool_is_governed_by_a_capability_switch` holds the map complete, because an outbound tool under no switch would show as live however much the operator switched off
BLOCKER 4 — THE ORPHAN DETECTOR GAVE FALSE ALL-CLEARS, AND REVIEW PROVED IT BY PLANTING ONE. The AST walk collected every string subscript and every `.get(str)` first argument anywhere in a 7,500-line file, on any object — 164 strings, mostly JSON payload keys (`body`, `filename`, `decision`, `height`). Review appended a `[decision]` section to the settings file and the orphan test PASSED. My vacuity control (`len(read) > 20`) guarded under-collection; the failure here was over-collection | FIXED | feat/1582-permission-profile — every access is now anchored on the receiver being the config object itself (`_CONFIG_OBJECT_NAMES`), which drops the collection from 164 strings to 16 real sections. `test_the_orphan_detector_is_wrong_in_NEITHER_direction` asserts both directions: five known-live sections must be seen (via BOTH access shapes), and four payload keys that demonstrably appear in the entrypoint must NOT be. `test_a_planted_orphan_section_is_actually_caught` reproduces review's planted case against the real assertion
THE DELETION ITSELF WAS SAFE, INDEPENDENTLY CONFIRMED | REJECTED | Rejected as a finding AGAINST the deletion, and recorded because the lock certifying it was wrong even though the change was right. Review swept Python, C#, PowerShell, TOML and tests: no reader of `[preemption]` or `[circuit_breaker]` anywhere; `require_section_dict` has no unknown-section rejection; neither section is in the required-section list or the optional `.get()` block; no config-parity test exists between the two files. The `max_tool_call_depth = 5` vs `MAX_TOOL_CALL_DEPTH = 3` discrepancy is real. The deletion ships
FINDING 5 — THE COMMAND CRASHED UNDER GUEST TOPOLOGY. Five of the six capability sections do not exist in `guest_runtime.toml`; the profile raised `KeyError`. Fail-loud was the right instinct in the wrong place — a raw traceback is not a governance statement, and "cannot state whether that capability is on" is not the honest answer when the honest answer is "that capability does not exist in this topology" | FIXED | feat/1582-permission-profile — `Capability.present` distinguishes absent from off, and absent capabilities render under NOT PART OF THIS TOPOLOGY. The fail-loud case moved to where it belongs: `test_the_host_settings_file_carries_every_capability_switch` fails in the GATE if a section is deleted, rather than at the operator's terminal. `test_the_command_runs_under_guest_topology` drives `main()` under `BLARAI_RUNTIME_MODE=guest`
FINDING 6 — "web search only" WAS A STORED COPY. The capability description hardcoded "This is the only thing that leaves this machine", and the outbound line hardcoded "web search only". Review mutated `_EGRESS_TOOLS` to `{send_email}` and got both claims in one render: a stored one and a resolved one, disagreeing | FIXED | feat/1582-permission-profile — the stored sentence is gone from the capability description, and the outbound line is composed from the resolved live set. What remains in the description is the SECOND condition (finding 7), which is a fact about the capability rather than a claim about the tool set
FINDING 7 — `[web_search].enabled` IS ONE OF TWO CONDITIONS. Registration also requires the DPAPI-sealed Kagi key to load; with the blob absent the capability is structurally dormant and the profile still printed "IT CAN: Search the web" | FIXED | feat/1582-permission-profile — fixed as far as it can honestly go. The capability description now says the sealed key is also required and that without it the capability stays dormant whatever the switch says. NOT resolved to a live yes/no: reading the sealed blob to answer would mean a read-only governance display touching a credential, which is a worse trade than an honest "this switch is necessary but not sufficient". The operator is told the condition exists rather than shown a green light that might be wrong
FINDING 8 — THE FORBIDDEN SET COVERED NONE OF THE DECIDING FUNCTIONS THAT EXIST, and named one (`is_egress_allowed`) that does not exist anywhere in the tree — padding without coverage. Uncovered: `register_url_adjudicator` and `clear_url_adjudicator`, which mutate the single adjudicator slot and are the precise principle-5 violation the test claims to hold | FIXED | feat/1582-permission-profile — the set now names the real deciders and both adjudicator-registration functions, the non-existent name is gone, and the test asserts that the functions it forbids actually EXIST before asserting they are not called. A forbidden name for a function that does not exist certifies nothing
TWO STALE POINTERS IN THE SAME NEIGHBOURHOOD, not caused by this change and surfaced by the review | FIXED | feat/1582-permission-profile — `docs/governance/circuit-breaker.md` still asserted `MAX_TOOL_CALL_DEPTH = 5` and cited both a deleted alias and a deleted test file; `docs/governance/trust-spine-claim-register.md` row 21–24 still cited `services/assistant_orchestrator/src/circuit_breaker.py`, which #1596 deleted. Both corrected in place with SUPERSEDED markers rather than rewritten, so the wrong number stays visible where it was asserted. This is the FIFTH place that 5 has been found since #1596 traced it; the count is recorded because the pattern is the point
```

## Verification

`tests/security/test_permission_profile.py`: **24 passed**. Eleven mutations across the
change, every one confirmed to fail its lock — including the five blocker fixes, each mutated
back to its defective form.

`services/assistant_orchestrator/tests/ tests/security/ tests/integration/ shared/`
(not hardware/winui/slow): **9863 passed, 6 skipped**, plus the 2 known ADR-013 worktree
doc-pointer artifacts. All 6 skips are documented gitignored-asset deltas — model weights and
a staged docset index — each naming its reason, each running in the primary checkout.

**Driven for real in both topologies**: host mode reports 5 capabilities on, 1 off, outbound
to `kagi.com` only; guest mode reports 1 on and 5 NOT PART OF THIS TOPOLOGY, outbound nothing.

## The honest note

The review confirmed my central claim — that an unclassified tool is genuinely refused under
untrusted content, unconditionally, with `/trust` unable to lift it — and then showed that the
sentence I had written *next to* it was false. I had traced the refusal carefully and then
narrated the non-refusal case from memory of how the architecture ought to work. The careful
half and the careless half sat in the same paragraph, and the careless half was the one that
would reassure.

A governance statement's value is entirely in its being true. The one sentence in it that was
invented is the sentence that would have been quoted.
