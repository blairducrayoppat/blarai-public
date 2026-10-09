---
title: "#1569 tamper-vs-rotation classification — adversarial review disposition"
status: final
area: security
---

# Disposition — #1569 (distinguish a key rotation from a tamper)

**Review run 2026-09-17, pre-merge, by an agent that did not write the code.** Target `85eb30db`;
fixes in `e5038018`. The reviewer was briefed on this session's failure pattern — four prior
documents reasoning from a mechanism's intent rather than from what executes — and told to assume
the same disease. **It found it, and this instance had a real exploit path.**

**The defect in one line: the classifier read bytes the attacker writes.** A control whose
classification input is controlled by the actor it defends against is worse than no classification,
because it converts a tamper alarm into a reassurance.

```disposition
# finding | status | evidence-or-predicate
review finding 1 (CRITICAL) — _classify substring-matched the REASON STRING, and six of the seven raise sites interpolate values read straight off disk (prev_hash, record_hash, filename, file_sha256) with no format validation, by an attacker this module's own threat model explicitly includes. Writing "signature verification failed" into any of those fields filed a REAL TAMPER as a benign key problem. Reproduced through the real PolicyAgentService._build_audit_log: a record altered to tool:NEVER_APPROVED reported fault=key_mismatch, is_tamper=False, and printed "Every record hash is intact" IMMEDIATELY AFTER "record_hash mismatch", withholding the forensics instruction. Three vectors: record_hash injection, prev_hash injection, and a deleted sealed segment whose index filename carried the string — the last one free, because filename is deliberately excluded from the signed summary, a premise true until this change made it an input to a security classification | FIXED | e5038018 — all seven raise sites in verify() now pass fault= explicitly, so the code that knows which check failed names the class. _classify is demoted to a FALLBACK for callers outside verify() and ALWAYS returns TAMPER, ignoring its message entirely. Re-verified by this session: the same injected string now yields fault=tamper, is_tamper=True. The docstring that asserted "does not trust anything inside an unverified record" while consuming prev_hash and record_hash is corrected with the defect recorded in place rather than scrubbed
review finding 2 (HIGH) — the locks certified 2 of 7 raise sites, and three misclassification mutants survived the entire suite: sealed-segment sha mismatch reclassified as a key problem, prev_hash mismatch reclassified, and a loosened predicate. Each produced counts identical to baseline. The commit's "mutation-proved" claim was true but tested only the two directions the two fixtures already covered, so a mutant silently reclassifying a SEALED-SEGMENT TAMPER as benign was invisible | FIXED | e5038018 — added locks for attacker-injected strings in record_hash and prev_hash, the fallback ignoring its message, a corrupted sealed segment, and a DELETED sealed segment (the #606 tail-deletion class), plus two baselines (a genuine rotation is still KEY_MISMATCH; a rotated chain with the right key still verifies) without which everything-is-TAMPER would pass. Mutation-proved against the three that previously survived: all three now fail
review finding 3 (HIGH) — the commit's headline claim, that both production constructors carry the fault class and guidance into their refusal, is TRUE in the code and LOCKED BY NOTHING. Deleting the interpolations from both entrypoints leaves the suite green. This is the shape #1543's review already caught once, recorded in the very file that repeats it | FIXED | fix/1569-tamper-vs-rotation — TestTheFaultClassReachesTheOperator added, driving BOTH real constructors and asserting the fault class and the remedy reach the operator-facing message. The disposition gate refused this as a deferral and was right to: a test per constructor is a same-day fix, not a delay with a predicate. Mutation-proved — stripping the fault class and guidance from the PA refusal, which previously left the whole suite green, now fails test_pa_refusal_names_the_fault_class_and_the_remedy
review finding 4 (MEDIUM) — a tamper that corrupts the signature HEX escapes classification entirely: bytes.fromhex raises a bare ValueError, which AuditChainError (a ValueError subclass) does not catch. The PA still fails closed, but the AO logs it as "Knowledge bank disabled: ... non-hexadecimal number found in fromhex()", which reads like a bug rather than a tamper | DEFERRED | #1578 blocked-by: #1569 merged, same observable. Pre-existing from #1543 and still fail-closed in both services, so it is a diagnosis gap rather than a security hole — but #1569 is the ticket that owns what the operator is told, so it belongs in the follow-up that owns the rest of the reporting surface
review finding 5 (MEDIUM) — operator_guidance names a remedy the operator cannot perform. verify(signer=...) exists and behaves as implied, but there is no CLI, no script and no runbook entry; and it DIAGNOSES without RECOVERING — after a genuine rotation the chain can never verify under the new key, so the PA refuses to start permanently. The ticket's goal of "a documented recovery path that is not your audit log looks tampered with" is half-met | DEFERRED | #1578 blocked-by: #1569 merged, same observable. Flagged in the merge read as a DECISION about how much rotation tooling to build rather than a defect with one correct fix — the Lead Architect is permanently non-technical, so "run verify(signer=...)" is not an operator-facing remedy, and what replaces it is his call
review finding 6 (LOW) — the AO refusal lost the sentence stating the chain was refused; the TAMPER guidance never says so, while only the KEY_MISMATCH guidance ends "Either way the chain is refused". For the MORE serious class the operator now gets less | DEFERRED | #1578 blocked-by: #1569 merged, same observable. A message-quality fix that belongs with the rest of the reporting surface rather than alone
review finding 7 (LOW) — the test class name TestTheAdversarialCaseIsNotMistakenForRotation states the opposite of what the test asserts: the forgery IS classified KEY_MISMATCH, i.e. it IS indistinguishable from a rotation. The docstring is honest; the name is what a reader scanning the file sees | DEFERRED | #1578 blocked-by: #1569 merged, same observable. Renaming a test is trivial, but doing it inside the security-fix commit would bury it; it goes with the reporting-surface work where a reader will see why
review finding 8 (LOW) — the journal fragment's proposed lesson ("check whether they already fail differently") rests on the disproved premise, since an attacker chooses the text the classifier reads | FIXED | e5038018 and the fragment correction committed alongside this record — the lesson is rewritten around what the episode actually taught, which is the opposite of what I first drew from it
reviewer's note — the author's "5648 passed" is a different selection from the reviewer's 5253+395 across the four briefed suites | REJECTED | Not a discrepancy: different selections, both stated with their scope. Recorded because an unexplained count difference between two runs is exactly the kind of thing this sprint has learned not to wave past — the numbers agree once the selections are named
```

## What the reviewer attacked and could not break

- **TPM rotation reachability.** The KEY_MISMATCH class is genuinely reachable in production —
  `tpm_signer.verify` returns `False` on a bad signature rather than raising, so a real rotation
  reaches the classifier as designed.
- **False alarms in the other direction.** No genuine rotation classifies as TAMPER, across all four
  `verify()` topologies including the sealed-segment anchor path.
- **Both AO arms** route through `_verified`; the dev/production divergence that produced #1543's
  review finding 1 is not repeated here.
- **Gunzip failures** are reachable only via `full=True`, which has no production caller.
- **Regression** — the 2 doc-pointer failures and 3 symlink skips match the documented worktree
  artifacts exactly. Nothing new.
