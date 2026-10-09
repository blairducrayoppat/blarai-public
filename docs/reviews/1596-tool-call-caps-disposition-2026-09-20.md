---
title: "#1596 — two tool-call caps, and the one the register cites has no caller"
status: final
area: security
---

# Disposition — #1596 (the cap the operator is told about, and the one that runs)

**Found while deciding #1594, widened by the #1594 adversarial review, reproduced
independently here before anything was changed.**

**The finding in one line: a 306-line governance document, a claim-register row marked
LIVE, and a passing unit-test file all described a control that never executed — and the
effect it claimed was true anyway, through mechanisms none of them mentioned.**

```disposition
# finding | status | evidence-or-predicate
THE CONTROL CLAIM-REGISTER ROW 24 CITES HAS NO PRODUCTION CALLER, AND ITS STATUS IS LIVE. `CircuitBreaker` — BOTH breakers, token and depth — is imported by exactly one file, its own test; the single construction in the source sits inside a docstring; `record_tokens` and `record_tool_call` are called by nothing. GOV-07 (`docs/governance/circuit-breaker.md`, 306 lines) describes its trip semantics, its fallback strings and its reset behaviour in detail, and its audience section addresses "the developer who calls CircuitBreaker.record_tokens / record_tool_call from the generation and tool-dispatch loops". There is no such caller and there was never one | FIXED | fix/1596-tool-call-caps — the class and its test are DELETED, and `TOOL_CALL_DEPTH_CAP` with them: that alias existed for this one dead consumer, so it outlived its only reader. Verified by AST rather than grep before and after, because this file's own comments name the class and a text scan flags them — matching prose when the claim is about code is the defect this session has caught in its own work three times
THE NUMBER WAS ALSO WRONG, AND IN THE DOCUMENTED DIRECTION. Row 24 and `MAX_TOOL_CALL_DEPTH` said 5 chained tool calls. The AO tool loop enforced 3, via `_TOOL_LOOP_MAX: int = 3` — a function-local literal seven thousand lines into `entrypoint.py`, invisible to `shared/timeout_registry.py` or anything else that audits limits, while the registered constant was the one a reader would find. I made exactly that mistake on #1594, reported the wrong figure to the LA and retracted it the same hour | FIXED | fix/1596-tool-call-caps — `MAX_TOOL_CALL_DEPTH` is 3 and the loop READS it. One name for the bound. The constant's docstring carries why it changed, because a value that moves without its reason is the next session's puzzle
DELETE RATHER THAN WIRE, and the rejected path is the intuitive one | REJECTED | Wiring the breaker would have made GOV-07 true at the cost of a SECOND counter for a limit already enforced — two mechanisms for one cap, which is precisely the drift that produced this defect. Both caps are real and each has exactly one enforcement point: tokens via `MAX_OUTPUT_TOKENS` as the `max_new_tokens` default in `gpu_inference.py`, depth via the loop. Adding a third participant to a two-document disagreement does not resolve it. `security_by_design` 4: structural absence over vigilance
ROW 24'S EFFECT WAS TRUE BY ACCIDENT, AND THAT IS THE PART WORTH CARRYING. The turn IS bounded — so every check anyone ran against the claim passed, and the row read as confirmed. It would have read identically if nothing bounded the loop at all, because nothing connected the row to the enforcement. A row that is accidentally right is not a weaker version of a row that is right; it is a row nobody will notice going wrong | FIXED | fix/1596-tool-call-caps — `tests/security/test_claim_register_row24_tool_call_cap.py`. It deliberately does NOT re-test the cap (the loop-exhaustion and eighth-exit locks do that). It asserts that the number IN THE ROW equals the bound the loop uses; that the loop READS the registered constant rather than holding a literal that happens to agree — a literal `3` would satisfy any value assertion while re-creating the defect; and that the deleted class has not returned to the runtime. The loop is located by AST, never by line number, because a line citation is what broke in #1592
GOV-07 DESCRIBES A MODULE THAT NO LONGER EXISTS, in six sections, with line citations | FIXED | fix/1596-tool-call-caps — corrected IN PLACE rather than rewritten: a banner at the top stating where each cap is actually enforced, and the six mechanism sections marked SUPERSEDED. The sections that describe the CAPS rather than the CLASS — threshold-tuning governance, monitoring, the PGOV/streaming/KV-cache interactions, the no-runtime-override posture — are explicitly NOT superseded and are still accurate. Kept rather than deleted because the shape of the failure is the useful artifact: this is what it looks like when a document, a governance row and a test suite all agree with each other and none of them checks the code
THE #1594 DECISION_REGISTER ROW SAYS `MAX_TOOL_CALL_DEPTH = 5` "FEEDS THE CIRCUIT BREAKER'S DEPTH BREAKER" — literally true when written, and now describing a deleted class | REJECTED | Not corrected, and deliberately. That row is a DATED record of a retraction made on 2026-09-19; it documents what I believed and what I found that day, and rewriting it would falsify the record of the error. The new row appended for #1596 supersedes it in the same file, immediately below, which is how this register carries corrections
```

## Verification

`tests/security/` + `services/assistant_orchestrator/tests/`: **3118 passed, 3 skipped**,
elevated — the 2 failures in that run are the known ADR-013 worktree doc-pointer artifact,
and the 3 skips are the documented Known-Good-Manifest env-skips.

The row-24 lock: **5 passed**. Its own vacuity control
(`test_the_loop_bound_is_findable_at_all`) is first in the file, because every other
assertion in it is meaningless if the loop cannot be located.

**No behaviour changed.** The loop enforced 3 before this change and enforces 3 after;
the token cap is untouched. What changed is that the constant, the code, the claim
register and the governance document now say the same thing.

## The honest note

I found this by making the mistake myself. On #1594 I needed the worst-case number of
fingerprint prompts in a turn, read `MAX_TOOL_CALL_DEPTH = 5` in the shared constants,
reported five to the LA, and retracted it an hour later when I read the loop. The trap is
that the wrong surface is the *discoverable* one: registered, cited in the claim register,
exactly where the project's own `authority_first` rule sends a reader. The right one is an
un-annotated local integer. Finding the true bound required knowing in advance that the
obvious answer was wrong.
