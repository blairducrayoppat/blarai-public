---
title: "#1543 verify-on-load — adversarial review disposition"
status: final
area: security
---

# Disposition — #1543, Gap D (verify the audit chain on load, refuse rather than extend)

**Review run 2026-09-17, pre-merge, by an agent that did not write the code.** Target commit
`ea5ba692` on `trust-spine-gap-closure-393181`. The reviewer attacked the change by running it:
driving the real constructors, mutation-testing every lock, and reproducing each finding before
reporting it. Fixes landed in `0dc9fc80`.

**The headline, recorded because it is the point of the rule.** The change closed "a control
nothing calls" by adding a control that nothing calls *in production*. The Policy Agent's
production branch returned before the verify was reached, so the check ran in dev and on no real
boot — while the ADR amendment, the DECISION_REGISTER row and the timeout-registry incident field
all asserted it ran at both production constructors. Every one of the nine locks passed, because
every one resolved through a config hardcoding `dev_mode = true`. Author-is-not-verifier is why
this was caught before merge and not by the operator's hands later.

```disposition
# finding | status | evidence-or-predicate
review finding 1 (CRITICAL) — PolicyAgentService._build_audit_log had the production TPM branch as its own early `return AuditLog.from_path(...)` with the new verify block below it, so verify() ran only on the dev/HMAC fall-through; the shipped config is dev_mode=false, so the control was absent on every real PA boot — the pre-#1543 behaviour with a governance record asserting otherwise | FIXED | 0dc9fc80 — restructured to ONE construction site and ONE exit so a branch cannot skip the check by returning early (structural, not a patch to the branch); mutation-proved by reinstating the early return, which fails exactly test_production_tampered_chain_is_REFUSED and nothing else
review finding 2 (HIGH) — tests/security/test_audit_verify_on_load.py claimed in its docstring to drive "the REAL production constructors" while _CONFIG hardcodes dev_mode=true, so no test entered the production branch; that false premise is what made finding 1 invisible | FIXED | 0dc9fc80 — TestProductionBranchIsAlsoLocked added: dev_mode=False through the real constructor with the TPM stubbed by an HMAC signer of identical key material (reachability of the check is under test, not the chip), covering baseline-constructs and tampered-refused; the file docstring now states both arms are covered and why the dev-only version shipped green
review finding 2b — the commit message claimed "the production ceiling reaches the constructed log" but TestProductionCeilingIsApplied asserted only on the dict returned by _audit_retention_kwargs; the claim was true and untested | FIXED | 0dc9fc80 — test_production_constructed_log_carries_the_clamped_ceiling constructs a log in production mode and asserts its _max_active_records equals PRODUCTION_MAX_ACTIVE_RECORDS
review finding 3 (HIGH) — the Assistant Orchestrator half had ZERO coverage; neutering its verify() produced no new failure across tests/security/ plus the knowledge-bank wiring suite. It was the half that worked and the half nothing locked | FIXED | 0dc9fc80 — TestIngestConstructorIsLocked added: untampered constructs, tampered refused with AuditChainError as __cause__, and the in-memory (empty local_root) branch asserted so a future change there is caught rather than discovered
review finding 7 (MEDIUM) — "verify(full=True) at the manifest-signing ceremony still walks every record" names a caller that does not exist; every `full=True` in production Python is a docstring or comment. The claim was load-bearing for the "no coverage is lost" argument that justified rejecting tail-sampling, and appeared on four surfaces this change authored | FIXED | 0dc9fc80 — withdrawn IN PLACE (not deleted) on shared/security/audit_log.py, docs/adrs/ADR-029 (Amendment), docs/DECISION_REGISTER.md and shared/timeout_registry.py; each now states the exhaustive walk is UNSCHEDULED and that the conclusion survives on the boot-time anchor check, which pins each sealed .jsonl.gz by SHA-256 and verifies its per-segment signature. Scheduling an exhaustive walk is named as worth doing and explicitly not done here
review finding 8 (LOW) — docs/governance/trust-spine-claim-register.md row 29 still read "Gap D — ticketed (#1543), design-only … no code written", the governance SSOT for the gap this change closes, untouched on a branch named after that register | FIXED | 0dc9fc80 — row 29 now reads "Gap D — CLOSED in code (#1543, sprint 19)" and records what was built, both constructor sites, the locks, and that the production arm exists only because the first version did not have it
review finding 9 (LOW) — docs/performance/audit_chain_verify_cost_2026-09-17_22-50-00.json recorded "python": "3.12 (.venv)"; the venv is Python 3.11.9. The value had been copied from CLAUDE.md rather than measured, inside a record whose purpose is stating measured conditions | FIXED | 0dc9fc80 — corrected to the measured 3.11.9 with the correction left visible in the field, naming the cause (documentation is not evidence, applied to a performance record about its own conditions)
review finding 5 (MEDIUM) — the budget contract prices only PRODUCTION_MAX_ACTIVE_RECORDS x per-record cost, while _verify_segment_index does a full-file read + SHA-256 AND one TPM signature verify per retained sealed segment on every boot; dropping the ceiling 100,000 -> 1,000 produces 100x as many segments, so the clamp multiplies the unpriced term. Reviewer reproduced ~26 s true cost against a 15 s budget at 1M lifetime records, with the gate still passing | DEFERRED | #1571 blocked-by: #1543 merged. Observable: `tests/security/test_audit_verify_budget.py` exists on merged main and `grep -n "PRODUCTION_MAX_ACTIVE_RECORDS" shared/security/audit_log.py` returns a hit. Not a line edit — an honest sealed-segment term needs a MEASURED per-segment signature cost plus a bytes-scaled hash term, held to the same standard as the per-record figure it would sit beside
review finding 6 (MEDIUM) — rotation is evaluated only inside append() via _should_rotate, so _load_existing reads an entire oversized active segment and verify() walks all of it; the clamp bounds the steady state and not the transition into it. The migration boot on any pre-#1543 segment verifies up to 100,000 records, this ticket's own 11-21 minute figure. Reviewer reproduced 2,500 records loaded and verified against a 1,000 clamp, no rotation at load | DEFERRED | #1571 blocked-by: #1543 merged, same observable as finding 5. Needs a boot-behaviour DECISION (rotate on load, verify-then-rotate, or refuse an over-ceiling segment), each changing what happens at boot on a chain the operator cannot easily inspect. Incidence today is zero — the PA chain has never been written, the AO chain holds 33 records — which is a reason to schedule it, not a reason to call the bound enforced
reviewer's note on the toggle-test — test_tampered_chain_opens_when_the_check_is_REMOVED constructs AuditLog.from_path directly rather than toggling the shipped control, so it passes with or without the fix and survived the PA mutation; it is honest about what it does but is not a principle-12 toggle of the shipped control | REJECTED | Rejected as a DEFECT and accepted as a CHARACTERISATION. The test's job is to establish that the tamper is detectable ONLY because of the added call, which is what makes the tamper cases interpretable; it is kept and its docstring already says exactly that. The principle-12 obligation is discharged elsewhere and now verifiably: test_production_tampered_chain_is_REFUSED was mutation-proved against the reinstated early return, and test_audit_verify_budget.py::test_the_adr_029_default_would_NOT_fit_the_budget proves the budget inequality is not vacuous. Renaming or deleting the from_path test would lose a true statement; adding the missing arm was the right repair and it is done
reviewer's note — the branch is not gate-green in this worktree: tests/security/test_doc_pointers_and_banners.py fails 2 tests on ADR-013's relative links to ../../../devplatform/claude-workspace/overnight-report.md | REJECTED | Not a #1543 defect and not a defect at all: a worktree-depth artifact, verified by direct resolution rather than by citing the note that predicts it — the path resolves to an existing file from the primary checkout (C:/Users/mrbla/devplatform/claude-workspace/overnight-report.md, present) and to a nonexistent path from a worktree three levels deeper. docs/TEST_GOVERNANCE.md:60 names "an ADR-013 relative link" among the artifacts that "all PASS in the real tree". The post-merge gate on the primary checkout is the authoritative reading and is required regardless
reviewer's limit, recorded rather than dismissed — no probe ran against real TPM hardware; every production-branch test stubs tpm_signer with an HMAC signer of identical key material | REJECTED | Rejected as a gap in THIS change. Reachability of the check does not depend on the signer, which is what findings 1-3 are about. Signature correctness on the real chip is shared/tests/test_tpm_record_signer.py's subject and passes. What DOES depend on the chip is the 7-13 ms per-signature figure, and that was measured on the real TPM before any of this was written (docs/performance/audit_chain_verify_cost_2026-09-17_22-50-00.json); it was not re-measured after these fixes, and nothing in them touches signing
```

## What the reviewer attacked and could not break, recorded because a null result is evidence

- **Fail-closed on unexpected exception types.** No try/except wraps `_build_adjudicator` on the
  boot path; a `TpmRecordSignerError` or `AuditSinkError` escaping `verify()` kills PA boot. On the
  AO, `_verified` catches only `AuditChainError` and the caller's broad handler disables the
  knowledge feature loudly while chat survives — the documented posture. No swallow, no
  log-and-continue, no fail-open found.
- **The `_verified` closure and the in-memory early return** in the AO constructor: `_verified` is
  defined before `audit_path` is bound but called only after, so the closure resolves; the
  `not local_root` branch skips verification on a freshly-created in-memory chain with nothing to
  verify, which is correct.
- **Regression.** `shared/tests/test_audit_log.py`, `shared/tests/test_tpm_record_signer.py`,
  `services/policy_agent/tests/test_entrypoint.py`, `tests/integration/test_timeout_registry.py`,
  `tests/integration/test_security_cascade.py` — 202 passed. The timeout-registry live-constant
  check passes against the new row.
- **Arithmetic across surfaces.** 100,000 × 6.78 ms = 11.3 min and × 13 ms = 21.7 min, so "11–21
  minutes" holds; 1,000 × 0.013 = 13.0 ≤ 15.0 holds; the constants in `audit_log.py`,
  `timeout_registry.py`, the ADR amendment and the DECISION_REGISTER row agree with each other.

## Tree integrity during the review

The reviewer mutated file copies and restored by `cp`, using no git verbs, and confirmed
restoration by `md5sum` with `git diff HEAD -- services/ shared/ tests/` empty. A `git status`
taken by this session *during* a mutation window showed a modified file that was clean seconds
later — both readings correct. The hazard that creates is now recorded in `FIELD_NOTES.md`: a
`git add` landing mid-mutation would commit a disabled control together with the tests that
certify it works, and the gate would pass.
