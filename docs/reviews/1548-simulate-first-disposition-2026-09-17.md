---
title: "#1548 simulate-first fourth route outcome — adversarial review disposition"
status: final
area: security
---

# Disposition — #1548 (simulate-first as a fourth route outcome)

**Review run 2026-09-17, pre-merge, by an agent that did not write the code.** Target `d71fe7f0`;
fixes in `4e35c0d8`. The reviewer was briefed on this session's failure pattern and told to assume
the same disease.

**The defect in one line: the capability was not dormant, it was absent — and its three locks did
not lock.** A flag whose flip activates nothing is worse than no flag, because a go-live ceremony
would flip it and believe something had happened.

```disposition
# finding | status | evidence-or-predicate
review finding 1 (CRITICAL) — the outcome was UNREACHABLE, not merely unused. route_simulate_first, declares_dry_run and SIMULATE_FIRST had ZERO production callers; grep -c "SIMULATE" services/policy_agent/src/gpu_inference.py returned 0, so DeterministicPolicyChecker.check — the surface the ticket names — was untouched. The commit message claimed the outcome ships "reachable and unused", and "reachable" was false | FIXED | 4e35c0d8 — consulted in the AO tool loop immediately above tools.execute and AFTER the #1541 identity binding, so a routed action has already survived every prior lock. NOT wired into DeterministicPolicyChecker.check: that returns (verdict, rule_name) to two consumers that branch on DENY/ESCALATE, so a fourth verdict would fall through `if verdict == "DENY"` into an implicit allow — a change to the single adjudication door's contract, which is a decision and not a defect with one correct fix. Reaching the outcome REFUSES the dispatch, because the dry-run executor does not exist and a tool reported as simulated but in fact executed is the inversion this outcome exists to prevent. Locked by TestTheOutcomeIsWiredIntoTheToolLoop, mutation-proved three ways: deleting the block, moving the call below tools.execute, and dropping the refusal so control falls through each fail
review finding 2 (HIGH) — THE TOGGLE TESTS KILLED THE TRIPWIRE THEY WERE WRITTEN TO PROVE ALIVE. All four mutated tools._SIMULATE_FIRST_TOOLS and restored a HARDCODED frozenset() rather than the saved value, so under a whole-file run an earlier test blanked the global before test_the_declaring_set_is_empty read it. Reproduced by the reviewer and again by this session: adding generate_image to the declaring set left the file at 19 passed, with the capability tripwire silent | FIXED | 4e35c0d8 — every mutation is now monkeypatch.setattr, which restores the value that was actually there. The identical mutation now yields 2 failed, 17 passed, naming test_the_declaring_set_is_empty and the generate_image parametrisation
review finding 3 (HIGH) — THE CEREMONY-FLAG GATE WAS SELF-CERTIFYING. tests/security/test_config_comment_truth.py checks that a declared go-live flag is CONSUMED, and it passed only because the literal simulate_first appeared in route_simulate_first's own def line — 1 occurrence, against 4 to 707 for each of the other 28 ceremony flags. Renaming the symbol produced "[unconsumed-flag] ... a dead switch wearing a live label", which was the accurate description of the shipped state | FIXED | 4e35c0d8 — the flag now resolves through the real config path: a [simulate_first] section read, a simulate_first_enabled field on AssistantOrchestratorEntrypointConfig with a fail-closed default, a service property mirroring fleet_dispatch_enabled, and the consumption at the dispatch site. test_the_flag_resolves_off_the_real_config locks the resolution; the wiring lock locks the consumption
review finding 4 (MEDIUM) — flipping enabled = true changed only two bookkeeping assertions across 2906 tests, so nothing proved the flag had teeth | REJECTED | Re-measured after the fix: 4 failed / 2907 passed with the flag on, the same two-test delta. This is now the CORRECT result rather than a gap. With the declaring set empty no live tool routes, so a behavioural delta would mean the deny-by-default lock had failed. What was missing at d71fe7f0 was not a delta but evidence that the flag reached anything at all, and that is what findings 1 and 3 fixed. Recorded as rejected rather than deferred because there is nothing to come back for
review finding 5 (LOW) — the commit claimed the bar covers _EGRESS_TOOLS; _SIMULATE_FIRST_BARRED is an independent literal | REJECTED | test_every_egress_tool_is_barred already iterates tools._EGRESS_TOOLS and asserts membership, so a second egress tool added later fails the gate. Deriving the barred set from _EGRESS_TOOLS would be weaker, not stronger: the bar must be able to hold a tool that is NOT an egress tool, and a derived set could not
self-caught, pre-review — the reserved-namespace scan landed under #1547 earlier in this sprint refused the refusal reason host_error:simulate_first_unimplemented: that namespace is owned by the ACS specification and a host may not invent identifiers in it | FIXED | 4e35c0d8 — renamed to blarai_policy:simulate_first_unimplemented. Caught by a control this sprint built, on the same day it landed
```

## What the reviewer attacked and could not break

- **The egress bar wins over a declaration.** `web_search` added to the declaring set is still refused,
  and a non-barred tool with the same declaration is routable — so the refusal comes from the bar and
  not from a dead route.
- **The refusal shape.** `route_simulate_first` returns `None` rather than a permissive value for a
  tool that does not declare, leaving the caller's existing verdict untouched.
- **Regression.** The 2 doc-pointer failures match the documented ADR-013 worktree artifact exactly.

## The honest note

Finding 1 was caught by its author, but only after the false claim had been written into the commit
message and the module docstring — the same order as four earlier findings this sprint. Findings 2
and 3 were not caught by its author at all, and both are worse: a lock that cannot fire and a gate
that certifies itself are indistinguishable, from the inside, from a lock and a gate that work.
