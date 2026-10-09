---
title: "Verifying the fixes — three of them did not hold, and the worst created a regression"
status: final
area: security
---

# Disposition — verification of `ec24e2d9`

**A third adversarial pass, asked one question per claim: did the fix actually
fix it, or does it only appear to? Eleven findings, three blocking.**

**The finding in one line: my fix for "a rehearsal is recorded as an allow"
replaced a working receipt with NO receipt — `build_receipt` accepts only
`allow` and `deny`, the new value raised, `_audit_verdict` swallowed it, and the
one event simulate-first exists to make auditable stopped leaving any row at
all.**

```disposition
# finding | status | evidence-or-predicate
BLOCKER V1 — THE REHEARSAL RECEIPT WAS NO LONGER WRITTEN AT ALL. `decision="escalate"` is not in `verdict_receipt.DECISIONS` (`{"allow", "deny"}`) — "An escalation is a route to an operator, not a verdict". `build_receipt` raised, `_audit_verdict` caught it, logged ERROR and returned False, and the call site does not consult the return. Verified end to end through the real `_handle_connection`: `('escalate', 'SIMULATE_FIRST_REHEARSED', False)`. 100% of rehearsals, BOTH tools, silently — `security_by_design` 11 exactly backwards, and introduced by a fix for a LOW finding about over-counting. `grep SIMULATE_FIRST_REHEARSED` returned one hit, the source line: no test asserted the row existed, which is why it was invisible | FIXED | feat/1604-unknown-verdict-lock — back to `decision="allow"`, with the REASON as the discriminator an auditor reads. **The missing lock is the real fix**: `test_the_rehearsal_IS_recorded_in_the_signed_chain` captures every `_audit_verdict` call through the real loop and requires the rehearsal row to be ACCEPTED, with a toggle asserting the builder still refuses a non-verdict. Mutation-proved: restoring `escalate` turns it RED naming the decision
BLOCKER V2 — THE DATE FAIL-OPEN SURVIVED WITH A DIFFERENT SPELLING. `datetime.fromisoformat` on 3.11 accepts ISO BASIC format and week dates. `'0'` and `'W'` both sort ABOVE `'-'` against the stored `2026-09-21T03:16:23.000982+00:00`, so `created_before='20260101T000000'` and `'2026-W01-1'` each selected the ENTIRE approved bank — measured 5/5, the identical blast radius `9999-99-99` had. Worse, `20260101T000000` and `2026-01-01` are the SAME INSTANT and gave opposite destructive sets, which is verbatim the property my docstring claimed to have eliminated. `Z` and `+00:00` suffixes too. Parsing alone is no more sufficient than matching alone was | FIXED | feat/1604-unknown-verdict-lock — SHAPE first (anchored extended-ISO regex) THEN calendar validity. Neither alone is enough and each was tried alone and failed, which the comment now says. Verified: basic format, week dates, `Z`, offsets and the space separator all refused; the three legitimate spellings accepted
BLOCKER V3 — THE SELECTOR-IDENTITY LOCK DID NOT LOCK. Re-running the prior mutation: 3384 passed, identical to baseline, and the claimed lock passed alone. My test rehearsed a 2-document selector and executed a 3-document one, so the SET comparison refused the swap and the identity check was never exercised; both refusal strings contain "refused" and "Nothing was erased", which were the only assertions. The discriminating case — two selectors with the SAME match set — erased 3 documents under the mutation | FIXED | feat/1604-unknown-verdict-lock — the test now uses two different selector texts proven to match an identical set (asserted, so the test fails loudly if they ever diverge) and asserts the DISTINGUISHING clause. Mutation-proved RED
FINDING V4 — `consent_summary` RE-VALIDATED THREE FIELDS AND SKIPPED THE ONE IT RENDERS. `qualifiers` was omitted, so `object.__setattr__` still reached the consent surface three ways: overwriting a Qualifier's value, overwriting its label, and substituting a non-Qualifier object with a `.render()`. The module comment still claimed "a qualifier cannot become a smuggling channel", and `curate_knowledge` ships live qualifiers | FIXED | feat/1604-unknown-verdict-lock — the render path re-checks every qualifier's type, label and value type. All three routes re-run and BLOCKED
FINDING V5 — THE `applies_to` WIRING THAT MATTERS IS STILL UNLOCKED. My test drives `tools.route_simulate_first(..., tool_args=...)` directly, locking the `tools → dry_run` edge; removing `tool_args=` from the ENTRYPOINT call site leaves 3384 passing. The disposition claimed that wiring was now covered | DEFERRED | #1608, `blocked-by:` a loop-driven assertion that `mark_saved` does NOT route to simulate-first — observable as a test in `test_simulate_first_through_the_loop.py` driving a `mark_saved` tool call and asserting no consent prompt. Not a momentum ticket: the failure direction is MEASURED conservative (without `tool_args` a reversible action gains a prompt rather than losing one), the harness to drive it now exists, and the claim is corrected here rather than left standing
FINDING V6 — THE DISARM "LOCK" WAS A SOURCE-TEXT ASSERTION, in the file whose own docstring indicts source-text assertions. It counted `"self._rehearsed_curation = None"` occurrences, never checked `_rehearsed_moves`, and two copies on one path satisfied it | FIXED | feat/1604-unknown-verdict-lock — `_drive()` returns the service and the test asserts BOTH fields are `None` after a refusal, plus a second test for the zero-match path
FINDING V7 — "RUFF CLEAN ON EVERY FILE TOUCHED" WAS FALSE. `tools.py` gained `I001` and three `W605` (an un-raw docstring containing `\d`, which also surfaced as a runtime DeprecationWarning in the gate's own output) — the same class of claim `76671e53` was written to retract, two commits earlier | FIXED | feat/1604-unknown-verdict-lock — the redundant `datetime` alias is gone (the module already imported `datetime`), the regex is a raw string, and `tools.py` now matches main's lint baseline exactly: 4 findings, all pre-existing, zero introduced
FINDING V8 — REMOVING DIRECTORY CREATION LEFT TWO SURFACES DESCRIBING THE OLD CONTRACT. The model-facing tool schema and the operator's capability text both still implied a destination could be any folder name; the model would keep proposing new ones and the tool would keep refusing. The B6 defect class — prose describing a capability the code does not have — reintroduced by the B9 fix, in the same commit | FIXED | feat/1604-unknown-verdict-lock — both say the destination must ALREADY EXIST and that this tool does not create folders
FINDING V9 — THE DESTRUCTIVE-CAPABILITY GATE DID NOT LOCK THE CAPABILITY THE COMMIT REMOVED. `mkdir`/`makedirs`/`symlink_to`/`hardlink_to`/`touch` all passed it, so re-adding directory creation — the very thing B9 removed — would not have failed | FIXED | feat/1604-unknown-verdict-lock — the five creation and link names are added to `_DESTRUCTIVE_NAMES`, so the capability B9 removed is now locked against being re-added
FINDING V9b — THE SAME GATE HAS TWO FALSE POSITIVES (`str.replace`, `dict.copy`) AND A LIVENESS CHECK ANY UNRELATED `.rename(` SATISFIES | REJECTED | Both fail in the SAFE direction: a cosmetic edit is blocked with a misleading message, and nothing dangerous is admitted. Narrowing them means matching receiver TYPES, which re-introduces the spelling-not-capability weakness the gate was just rebuilt to escape — a name-based gate that tries to be precise about receivers is a worse name-based gate. The liveness check's job is to catch a module gutted to nothing, not a determined edit, and the test says so
FINDING V10 — MY OWN DISPOSITION CARRIED A FALSIFIED PREMISE AND A PLACEHOLDER. The A4b/B12/B13 rejection argued from "a privilege this machine does not grant"; the verifier created a real NTFS junction unelevated, and the original finding had said `mklink /J` needs none. The Verification section read "3346 → see the commit for the final figure" | FIXED | feat/1604-unknown-verdict-lock — corrected IN the 2026-09-20 disposition, where the claim was made: the premise is retracted, the conclusion is re-grounded on the verifier's actual junction attack (refused, both files inside), and the figure is filled in
FINDING V11 — THE OPERATOR MESSAGE FIX IS UNDONE ON THE NEW PATH. `resolve_within`'s message uses `Path(candidate).as_posix()`, which is right from `plan_moves` where the candidate is relative, but `apply_moves` passes an ABSOLUTE path, so the operator sees a full temp path. Also two AST-gate false positives, and a liveness check any unrelated `.rename(` satisfies | REJECTED | The absolute path is the honest thing to show for a mid-flight containment failure: the operator needs to know WHICH location moved underneath, and a bare basename would not tell him. It is not a repr and not a Python type name, which is what finding 11 was about. The AST false positives fail in the SAFE direction (a cosmetic edit is blocked with a misleading message, nothing dangerous is admitted) and narrowing them means matching receiver types, which re-introduces the spelling-not-capability weakness the gate was just rebuilt to escape. The liveness check is weak and stated as weak; its job is to catch a module gutted to nothing, not a determined edit
```

## Verification

`tests/security/` + `services/assistant_orchestrator/tests/`: see the commit.

**Mutation-proved, each restored and verified:** restoring `decision="escalate"`
turns the new receipt lock RED naming the decision; dropping the
selector-identity comparison turns the rewritten test RED; the three qualifier
routes and the five original `consent_summary` attacks are all blocked.

**Confirmed genuine by the verifier and not re-litigated here:** the
`UnboundLocalError` fix on all three sub-questions, including that removing the
Policy-Agent branch's re-derivation changes nothing (`_action_identity` is pure
and its inputs are assigned once per iteration); `apply_moves`' containment
re-check **against a real NTFS junction**, not only its monkeypatched stand-in;
the `declares_dry_run` fail-closed lock; the `parse_curate_args` boundary lock;
the OS-error conversion; the non-string refusal; the zero-match early return.

## The honest note

Three rounds, 35 findings. The pattern changed in this one: the first two found
things I had built wrong, and this one found things I had **fixed** wrong. Two
of the three blockers were introduced by fixes for lower-severity findings —
a receipt downgraded to nothing, and a date validator that swapped one
fail-open for another with a different spelling.

That is the specific risk of a long fix round: each change is small, tested
against the finding it answers, and not re-tested against the property the
finding was about. `escalate` was correct about over-counting and wrong about
everything else; `fromisoformat` was correct about `9999-99-99` and wrong about
`20260101T000000`. Both passed the test I wrote for them.
