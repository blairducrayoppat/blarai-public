---
title: "#1031 S1 rebuild (#1041 + #1042) — finding disposition"
status: closed
area: reviews
date: 2026-07-22
---

# #1031 S1 rebuild — disposition

The original S1 pre-merge review returned **DO-NOT-MERGE** with 13 findings, split into
#1041 (delivery-floor redesign) and #1042 (dormancy + spec integrity). Both were rebuilt and
re-reviewed by the same independent reviewer that returned the original verdict; it authored
none of the fixes.

**Rebuild verdicts:** #1042 **MERGE** (`f8d3779f`); #1041 **MERGE-AFTER-FIXES** → fixes applied
in `de97f5db`, pending the reviewer's confirmation of the ordering lock.

## Why one finding came back

The reviewer's #1041-1 is the finding that matters, because it is the **same class that failed
S1 the first time (L4-1: an ordering that affects output with no lock)** — and my first fix
asserted the ordering no longer mattered rather than locking it. It does matter: the realism
guard and the delivery floor couple through the guard's never-zero-tests invariant, and the
reviewer measured 258 inputs where guard-first and floor-first produce different specs,
reachable through the real `generate_plan`. My "correctly UNKILLABLE" comment was measurably
false.

Worse, my *first* attempt at the lock composed the two helpers directly in the test and stayed
green under the order-reversal mutant — the built-but-wired-into-nothing shape, inside the fix
meant to close exactly that shape. Caught, rewritten to drive `generate_plan`, and mutant B1
now turns it red.

## Disposition

```disposition
L1-1-toml-parse-coerces-fail-open | FIXED | f8d3779f
L4-2-three-dormancy-defaults-untested | FIXED | f8d3779f
L6-1-default-toml-describes-unshipped-capabilities | FIXED | f8d3779f
L5-1-rulers-drop-asset-specs-and-clarifications | FIXED | f8d3779f
R1-a-is-card-driven-does-not-basename-a-path-shaped-repo | FIXED | f8d3779f
L3-1-build-tier-criterion-suppresses-the-floor | FIXED | de97f5db
L3-2-delivery-markers-substring-allowlist-false-positives | FIXED | de97f5db
L3-3-ordering-guarantee-no-longer-holds | FIXED | de97f5db
L4-1-ordering-has-no-lock-at-the-wiring | FIXED | de97f5db
L4-3-eight-of-nine-delivery-markers-unexercised | FIXED | de97f5db
N1-injected-criterion-id-can-collide | FIXED | de97f5db
N3-ambiguous-surface-never-floors | FIXED | de97f5db
1041-1-ordering-still-load-bearing-comment-says-otherwise | FIXED | de97f5db
1041-2-test-docs-assert-the-old-ordering-story | FIXED | de97f5db
N2-criteria-cap-exceeded-by-one-or-two | REJECTED | Re-confirmed by the rebuild review: rule_spec already exceeds DEFAULT_MAX_CRITERIA by one via its build floor on main, so the cap is soft by existing design and the delivery floor does not introduce the property. A duplicate delivery criterion at worst drives one bounded soft-class regeneration, never a refusal. Revisit only if a downstream consumer is found that treats the cap as hard.
```

## Evidence

The reviewer independently reproduced every mutant (its own set plus mine, all restore
byte-exact): the three dormancy defaults (M24/M25/M26 — which SURVIVED the original suite and
now die), the fail-open reverts (M27/M28), the four floor mutants, and the order-reversal (B1).
Full record: the reviewer's findings file in the session scratchpad
(`1041-1042-review-findings.md`) and the original `1031-s1-premerge-review-disposition-2026-07-22.md`.

## Merge posture

S1 merges **DORMANT** — `advanced_intake` stays `false`, and its go-live remains an LA
ceremony. #1042's L6-1 fix is what makes that ceremony honest: the `default.toml` comment the
LA reads now describes only the two deterministic rulers S1 actually ships, not the four S2–S4
capabilities the original comment implied.

## Honest limit

The standing gate has not yet been re-measured on the rebuild worktree — the B6 battery run is
holding the box. It will be measured on the branch and again on merged main before the merge is
called done, per the merge-guards discipline; this record covers the findings, not the gate.
