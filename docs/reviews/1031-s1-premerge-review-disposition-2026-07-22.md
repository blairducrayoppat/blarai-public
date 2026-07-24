---
title: "#1031 S1 pre-merge review — finding disposition"
status: closed
area: reviews
date: 2026-07-22
---

# #1031 S1 pre-merge review — disposition

**Subject:** `feat/1031-s0-dormant-flag` @ `dce986db` (2 commits, 669 insertions, 5 files),
unmerged, base `main` @ `d080cd59`.

**Reviewer:** independent agent, dispatched 2026-07-22 by the day session. It did not author
the branch, did not author any of the three earlier blocker fixes, and wrote no fixes — it
reported only. The day session that commissioned it also did not author the branch, but
inherits authorship by succession and therefore does not sign it off either.

**Verdict: DO-NOT-MERGE.**

7 BLOCKERs, 3 findings, 3 nits. All eight commissioned review lines were examined; none was
skipped. Every finding below was CONFIRMED by reproduction, not argued. A 32-mutant campaign
ran against production code only (tests never mutated); both harnesses reported
`RESTORE VERIFIED BYTE-EXACT: True` against pre-run SHA256 digests.

## Why nothing here was fixed in this arc

Every finding is **branch-local and not live**: `feat/1031-s0-dormant-flag` is unmerged and
`[fleet_dispatch].advanced_intake` has never been true anywhere. There is no production
exposure to close.

The deliberate sequencing call, stated so it is checkable rather than assumed: five of the
findings (#1041) share one root cause and need a **design decision, not a patch** — the
delivery floor decides "does this spec already have a real delivery check?" by
substring-matching model-authored English, which is the same technique this branch's own
earlier round already deleted from the sibling ruler as unworkable. Patching the other four
around a pending redesign would produce churn in the same functions. Both tickets carry
observable predicates and both must close before S1 merges.

**What this means for the LA:** the #1031 go-live ceremony is **not offered** and should not
be, on this branch, in this shape. L6-1 is the reason it matters that this was caught before
the ceremony rather than at it.

## The findings

| id | severity | line | one line |
|---|---|---|---|
| L1-1 | BLOCKER | L1 | TOML parse coerces instead of validating — a quoted or garbage value ENGAGES the dormant capability; the shipped docstring claims it "can never engage by accident" |
| L3-1 | BLOCKER | L3 | A `build`-tier criterion suppresses the delivery floor, but `build` ∉ `TEST_TIERS`, so the spec can end with zero test-tier delivery verification |
| L3-2 | BLOCKER | L3 | `_DELIVERY_MARKERS` false-positives on ordinary web criteria and silently disables the floor — the technique BLOCKER-2 deleted, surviving on the other ruler with a worse failure direction |
| L3-3 | BLOCKER | L3 | The "load-bearing guard-then-floor ordering" no longer buys what the code, commit message and comment claim, after BLOCKER-2 narrowed the guard to empty checks |
| L4-1 | BLOCKER | L4 | Mutant M20 reverses the ordering at the real call site and all 39 tests stay green — the test composes the helpers itself and never reaches the wiring |
| L4-2 | BLOCKER | L4 | M24/M25/M26 each flip a "fail-closed default" to True and all survive — the dormancy, which is the entire justification for merging now, is the one control untested |
| L6-1 | BLOCKER | — | `default.toml` (the ceremony's primary artifact) describes four capabilities the flag does not deliver, and the realism guard in its **withdrawn** form |
| L4-3 | finding | L4 | 8 of 9 `_DELIVERY_MARKERS` entries are dead weight — M13c shrinks the tuple to one and everything stays green |
| L5-1 | finding | L5 | Both rulers rebuild `AcceptanceSpec` field-by-field and drop `asset_specs` + `clarifications`; latent today, one reordering from live |
| R1-a | nit | R1 | `_is_card_driven` does not basename a path-shaped repo, unlike both mirrors; the "pins all three" test pins values, not semantics |
| N1 | nit | L3 | Injected-criterion id can collide when criteria ids are non-sequential |
| N2 | nit | L3 | The criteria cap can be exceeded by 1–2 |
| N3 | nit | L3 | An `ambiguous` surface never gets the floor even when `web` is among its candidates — fail-closed, but undocumented |

**Clean, demonstrated rather than asserted:** L2 (toggle-off byte-identity — three SHA256
digests equal across branch-default, branch-flag-off, and `main`), R1 (the battery-card
suppression fix, verified against all 8 real cards through the real loader), R2 (the substring
allowlist verified gone from the guard), R3 (the never-zero-tests invariant verified and
locked).

**Test-honesty verdict on the two rewritten tests** — the author's explicit ask, and the
reviewer's call rather than the author's: Rewrite 1 **legitimate** (design genuinely changed;
input kept, assertion inverted, gap documented in the test's own docstring). Rewrite 2
**legitimate but incomplete** — the lock still bites (M31 and M32 both kill it) so it is not a
fake lock, but the removed counterexample was never re-pinned and the production comment it
proved was left claiming a guarantee the code no longer provides. That gap is L3-3.

## Disposition

```disposition
L1-1-toml-parse-coerces-fail-open | DEFERRED | #1042 blocked-by: `feat/1031-s0-dormant-flag` carrying a test asserting `_load_entrypoint_config` resolves advanced_intake to False for the string "false" (mutants M24/M25/M26 RED)
L3-1-build-tier-criterion-suppresses-the-floor | DEFERRED | #1041 blocked-by: `_ensure_delivery_floor` suppression path no longer calling `_names_delivery` on the branch tip
L3-2-delivery-markers-substring-allowlist-false-positives | DEFERRED | #1041 blocked-by: absence of the symbol `_DELIVERY_MARKERS` in `shared/fleet/acceptance.py` on the branch tip
L3-3-ordering-guarantee-no-longer-holds | DEFERRED | #1041 blocked-by: mutant M20 (reverse the gate order at the `generate_plan` call site) going RED
L4-1-ordering-has-no-lock-at-the-wiring | DEFERRED | #1041 blocked-by: mutant M20 going RED against an end-to-end `generate_plan` test
L4-2-three-dormancy-defaults-untested | DEFERRED | #1042 blocked-by: `services/assistant_orchestrator/tests/test_plan_handler.py` asserting all three production defaults directly - the dataclass field default on `EntrypointConfig`, the real `_load_entrypoint_config` over a key-removed config copy, and the resolved property with `_resolved_config=None`
L6-1-default-toml-describes-unshipped-capabilities | DEFERRED | #1042 blocked-by: `services/assistant_orchestrator/config/default.toml` advanced_intake comment naming S2-S4 as not-yet-shipped
L4-3-eight-of-nine-delivery-markers-unexercised | DEFERRED | #1041 blocked-by: absence of the symbol `_DELIVERY_MARKERS` in `shared/fleet/acceptance.py` on the branch tip
L5-1-rulers-drop-asset-specs-and-clarifications | DEFERRED | #1042 blocked-by: both rulers using `replace(spec, criteria=...)` in `shared/fleet/acceptance.py`
R1-a-is-card-driven-does-not-basename-a-path-shaped-repo | DEFERRED | #1042 blocked-by: `_is_card_driven` in `shared/fleet/acceptance.py` basenaming its repo argument before the prefix test
N1-injected-criterion-id-can-collide | DEFERRED | #1041 blocked-by: absence of the symbol `_DELIVERY_MARKERS` in `shared/fleet/acceptance.py` on the branch tip
N2-criteria-cap-exceeded-by-one-or-two | REJECTED | The cap is a prompt-shaping bound on what the 14B is asked to emit, not a spec invariant; the floor deliberately adds a criterion the model did not author, and refusing to inject on a full spec would trade a real delivery check for an arbitrary count. Revisit only if a downstream consumer is found that assumes the cap is hard.
N3-ambiguous-surface-never-floors | DEFERRED | #1041 blocked-by: the `ambiguous`-surface behaviour being stated in `_ensure_delivery_floor`'s docstring on the branch tip
```

## Honest limit of this record

The verifier checks the FORM of a disposition once one exists; it cannot see a finding that
was never written down. Thirteen findings were reported by the reviewer and thirteen appear
above. The reviewer also stated plainly which lines it did not examine, so the boundary of
this review is recorded rather than implied.

## Evidence

Reviewer's full findings file, with per-finding reproduction commands and actual output, was
written incrementally to the session scratchpad
(`s1-review-findings.md`, 698 lines) — deliberately, because a previous reviewer on this same
branch completed the work and then lost all of it by reporting only at the end.
Mutant harnesses: `mutants.py` (26) and `mutants2.py` (8), both byte-exact-restore verified.
