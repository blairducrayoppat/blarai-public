---
title: "#1584 — a liveness canary that certified a crashed door, and cried outage at a healthy one"
status: final
area: security
---

# Disposition — #1584 (trust-spine liveness canary)

**Eight findings from an independent adversarial review, every one reproduced against the
shipped code. Three were blockers, and each defeated the ticket's own problem statement in a
different direction.**

**The finding in one line: the instrument built to detect a door that is not working reported
ALIVE for a door whose rule engine had crashed, reported ALIVE for a door that ALLOWED the
exfiltration payload, and logged an ERROR-level finding on every boot of a system whose door
was shut on purpose.**

```disposition
# finding | status | evidence-or-predicate
BLOCKER 1 — THE CANARY CERTIFIED A DOOR WHOSE RULE ENGINE HAD CRASHED. The dispatch deny-probe's entire predicate was `verdict is not None`. `_adjudicate_tool_dispatch` catches every exception and returns `("DENY", "ADJUDICATION_ERROR")` — the door reporting that it COULD NOT ADJUDICATE — and the probe read that as proof of health. Review reproduced `alive=True, findings=0` with the checker raising on the exfil CAR. Two neighbours of the same predicate, same run: a door returning `("ALLOW", "ok")` for the exfiltration payload was reported ALIVE (it allowed the exfiltration), and an ESCALATE — which routes to operator consent and can be approved — scored as a refusal. The probe asked "did the door return something?", not "did it refuse, and by the rule I am testing" | FIXED | feat/1584-trust-spine-canary — `_score_dispatch_denial` is deny-by-default about what it will accept as proof: only a DENY, only by `EXPECTED_DISPATCH_RULE`, with `ADJUDICATION_ERROR`, ALLOW, ESCALATE, a non-pair and an unreadable shape each REFUTED and each naming why. Locked by five tests including a parametrised junk-verdict sweep. Three mutations restoring the old leniency each fail
BLOCKER 2 — AN ERROR-LEVEL FINDING ON EVERY BOOT OF A DELIBERATELY SHUT SYSTEM. The UNPROVEN branch gated on an empty egress allowlist — the one weld mechanism this codebase does not use. The live welds are the capability flag and the sealed search key; with either absent no adjudicator registers while the allowlist stays populated, so the door refuses everything CORRECTLY and the canary called it a finding. Review reproduced it end-to-end through the real boot methods. It fired for the ENTIRE guest topology, which has no `[web_search]` section at all — and this change adds the canary section to that very file | FIXED | feat/1584-trust-spine-canary — `probe_egress_door` takes `egress_expected_live`, the caller's answer to "is this door supposed to be open", because only the caller knows whether registration was attempted and succeeded. The AO passes the real return of `_maybe_register_web_search`. Locked by `test_a_welded_door_is_UNPROVEN_not_a_finding`, its toggle, and a guest-topology test that fails if `guest_runtime.toml` ever gains a web_search section and invalidates its own premise
BLOCKER 3 — THE RECEIPT CLAIM WAS STRUCTURALLY IMPOSSIBLE, AND THE CANARY FORGED AUTHORISATION ROWS. I claimed on four surfaces — the module, the service, both config files, and the journal fragment — that canary receipts were distinguishable by a reserved purpose. `build_receipt` takes no purpose parameter; `_record_verdict` passes it only into an opaque identity hash. Review produced a canary allow-receipt and a real web_search allow-receipt with EVERY readable field identical. So with the flag on, each boot appended a signed, durable row asserting egress to kagi.com was authorised when no fetch happened, and an auditor counting how often BlarAI was permitted to reach the internet would have been counting boots | FIXED | feat/1584-trust-spine-canary — the canary adjudicates through `_adjudicate_uncorded` and writes NOTHING. Not marking the row; not writing it (`security_by_design` 4, structural absence over configuration). Every instance of the false claim is deleted from the module, the service, both configs and the journal fragment. Locked by `test_the_canary_uses_the_RECORD_FREE_door`
BLOCKER 3b — THE COST OF WRITING NOTHING, NAMED RATHER THAN HIDDEN. The canary no longer exercises the recording wrapper | FIXED | feat/1584-trust-spine-canary — `test_the_recording_door_still_wraps_the_record_free_one` asserts by syntax tree that `_adjudicate` delegates to `_adjudicate_uncorded`, so the two cannot diverge and leave the canary probing a path production does not take
FINDING 4 — THE EGRESS DENY PREDICATE WAS A BLOCKLIST. `_is_allow` was `name.upper().endswith("ALLOW")`, and anything not recognised as an allow scored as a PROVEN denial — the opposite of deny-by-default. Review reproduced `(None, "x")` scoring as a proven refusal, and a verdict spelled `DISALLOW` being read as an ALLOW, which would report a door denying everything as having ALLOWED the canary host: a false alarm in the alarming direction. Against the shipped enums the check happened to be sound, and ESCALATE not ending in ALLOW was luck rather than design | FIXED | feat/1584-trust-spine-canary — `_score_egress` requires an exact `DENY` for the deny direction and an exact `ALLOW` for the allow direction, with everything else REFUTED and named. Locked by a parametrised unreadable-verdict sweep and an explicit DISALLOW test
FINDING 5 — THREE LOCKS CERTIFIED MORE THAN THEIR FIXTURES REACHED, AND THE PRODUCTION PATH HAD NO TEST AT ALL. `test_an_empty_allowlist_makes_the_allow_probe_UNPROVEN` exercised the weld mechanism this codebase does not use, and was therefore what made blocker 2 invisible. `test_the_canary_runs_AFTER_the_egress_adjudicator_is_registered` compared `source.index()` positions and would pass with the two calls in different methods or inside `if False:`. `test_the_denied_payload_is_posture_independent` asserted that a string constant contained `/tmp/export/` — a claim about a literal, not about posture. And NO test drove the real egress door's ALLOW direction: every allow-direction test used a stub, so the single path that executes in production was exercised nowhere | FIXED | feat/1584-trust-spine-canary — new `tests/security/test_trust_spine_canary_postures.py` drives the REAL record-free door with the REAL registered adjudicator against the live allowlist, restores the adjudicator slot in a `finally`, and a companion test asserts no residue leaked to the sibling file. Posture independence is now measured by driving the real dispatch door under three different allowlists rather than by inspecting a string
FINDING 6 — THE CANARY'S OWN ENABLE CHECK FAILED SILENT, in a module whose thesis is fail-loud, and `resolved` carried no type annotation while every neighbouring method annotates it | FIXED | feat/1584-trust-spine-canary — the defensive `getattr(resolved, ..., False)` is replaced by a direct attribute read on an annotated `AssistantOrchestratorEntrypointConfig`, so a future rename raises loudly instead of silencing the canary with the flag set to true
FINDING 7 — NO TIMEOUT, ON THE BOOT THREAD. Both probes are synchronous with no bound of their own. Today's reachable verdicts are DENY and ALLOW, so no blocking path is live, but `_adjudicate_uncorded`'s ESCALATE branch calls `request_escalation_consent`, documented as blocking until the verifier answers, bounded at 120 s | DEFERRED | #1602, `blocked-by:` a rule that can return ESCALATE for a CAR whose resource is `canary.invalid` or `tool:get_current_time` — observable as an ESCALATE outcome from either probe, which the canary itself now reports as REFUTED rather than silently waiting. Not a momentum ticket: the mechanism is cited and the trigger is a rule change that does not exist, and the canary's own scorer treats an ESCALATE as a finding, so the condition announces itself
FINDING 8 — REGISTER AND LINT. The module docstring carried sprint narrative and a dated measurement, which CLAUDE.md's coding_standards forbid in docstrings; ruff flagged UP035/RUF022/UP037/F401/I001 | FIXED | feat/1584-trust-spine-canary — the docstring is rewritten as contracts only, with the measurements moved to the journal where they belong. The repo's own `test_security_prose_carries_no_time_anchored_wiring_claims` then caught one surviving instance ("the one weld mechanism this system does not currently use") and it is restated as a timeless contract claim. `CANARY_EXFIL_ARGS` added to `__all__`
```

## Verification

`tests/security/test_trust_spine_canary.py` + `test_trust_spine_canary_postures.py`:
**44 passed** (22 before). `tests/security/` (not hardware/winui/slow): **1472 passed**, plus the
2 known ADR-013 worktree doc-pointer artifacts.

**Six mutations restoring the blocker defects, each confirmed to fail its lock**: the deny probe
accepting any non-None; an ALLOW on the exfil payload counting as a refusal; the wrong rule
counting as the right one; UNPROVEN gating on the allowlist alone; the canary returning to the
recording door; the egress deny predicate accepting anything that is not an allow.

**Driven against the real doors**: the dispatch door proves ALIVE under three different egress
postures; the egress door proves ALIVE through the real record-free path with the production
adjudicator registered, and the slot is restored afterwards.

## The honest note

This one was worse than a wrong answer. A liveness canary that certifies a broken door is not a
neutral failure — it is an instrument that manufactures false confidence in exactly the place
the ticket said silence was already dangerous. Every test I wrote first drove a door that
worked; the three shapes that mattered were all reported ALIVE and none was in my suite.

The pattern across today's three reviews is the same one: I test the thing behaving, and the
reviewer tests the thing broken.
