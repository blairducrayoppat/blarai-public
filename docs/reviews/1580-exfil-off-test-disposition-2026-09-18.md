---
title: "#1580 exfil-screen off-test — adversarial review disposition"
status: final
area: security
---

# Disposition — #1580 (the exfil screen finally has an off-test)

**Review run 2026-09-18, pre-merge, by an agent that did not write the code.** Target `718e5b42` on
`fix/1580-exfil-off-test`, branched off `5b4ab773`. Reviewer baseline reproduced exactly:
`tests/security/` = 1278 passed, 2 failed (the known ADR-013 worktree artifact), 0 skipped, 101.03 s.

**The finding in one line: the ticket was about a missing off-test, and the review found two live
fail-opens behind it — a planted secret left the host twice, measured, with no screen, no trip and
no log.**

```disposition
# finding | status | evidence-or-predicate
review finding 1 (HIGH) — THE PAIR'S VARIED CONDITION IS A TEST-ONLY ATTRIBUTE. _external_tagged_client sets `_screen_outbound_enabled = True` by hand, so allow_external_endpoint, _is_external_screen_target and _tag_screen_outbound are not in the fixture at all. Three production mutants (allowlist widening a no-op; the screen-target decision always False; the tagger a no-op) all left the new class 3/3 green, and two of them survived the whole reviewed file. The tagger's only lock across all of tests/security/ was test_egress_sandbox_proving.py, whose module-level skipif disables it when the box has no non-loopback interface — the posture this project is built toward, on which the production trigger had NO lock | FIXED | fc3106fb — TestTheExternalTagIsEarnedNotAssumed, five tests, none needing a network. The DECISION is driven directly (allowlisted -> target; empty allowlist -> not; a loopback entry forced into _external_allowlist -> still not). The WIRING is driven separately by stubbing only the decision and making a real loopback connect, so `connect()` failing to call the tagger is visible. Mutants M1/M2/M8 now all die. The forcing itself is KEPT and is not the defect: _is_external_screen_target refuses every loopback host by design and TEST-NET-3 is unroutable, so no real connect can earn the tag without real external egress; holding the tag FIXED is what makes the pair's single varied condition honest. The class docstring now says this instead of implying the scoping is part of the fixture
review finding 2 (HIGH) — `array.array("B", secret)` WALKED THE PLANTED SECRET PAST THE REGISTERED SCREEN AND LEFT THE HOST. _as_payload_bytes recognised only bytes/bytearray/memoryview and returned None for everything else; _screen_outbound took None as "skip this frame" and returned bare. Measured on the ON-test's exact setup with the real exfil_screen wired: delivered=YES, no exception, kill-switch not tripped, nothing logged. A silent skip in a control path, which security_by_design 11 names as a defect outright. It also falsified the claim register's row-12 word "every", and broke the off-test's own logic — the OFF arm reads DELIVERED as the signature of an absent screener, and an unscreenable buffer shape produces that signature identically, so the pair could not distinguish the world it claimed to have eliminated | FIXED | fc3106fb — Any C-contiguous buffer is now normalised through `memoryview(data).cast("B").tobytes()`, which is the same bytes the kernel would send. None now means "not a buffer at all" and the caller TRIPS on it rather than passing the frame — an unscreenable payload bound for an external destination is an ADR-027 §3 anomaly, not a frame to wave through. Re-ran the reviewer's leak table: all six rows held, array.array screened and blocked via both send and sendall. Locked by TestEveryBufferShapeIsScreened
review finding 3 (MEDIUM-HIGH) — `sock.dup()` OF AN EXTERNAL-TAGGED SOCKET RETURNED AN UNSCREENED SOCKET ON THE SAME TCP CONNECTION. socket.dup() builds self.__class__(..., fileno=fd) and __init__ cleared the tag for every fileno-built socket. Correct for accept(), where the peer never connected through this guard; wrong for a duplicate of a connected socket. Measured: bytes via sendall on the dup delivered the planted secret, no trip | FIXED | fc3106fb — dup() overridden to copy the tag from the parent, because the tag belongs to the CONNECTION, not to the Python object holding the handle. Locked by TestADuplicatedSocketKeepsItsTag, with the untagged-parent control so the fix is a COPY and not a set — an internal socket's duplicate becoming screened would self-trip on the first PA-to-AO message
review finding 4 (MEDIUM) — THE FIX SHIPPED WITHOUT CORRECTING THE SURFACE THAT STATED THE GAP. At 718e5b42 the claim register's row 12 still read "No off-test found", so the commit that retires the claim and the document asserting it disagreed. The register is the LA-facing governance document, and the branch is named for it | FIXED | fc3106fb — Row 12 rewritten in this commit: the off-test and the new tagging locks are cited by class name, "No off-test found" is gone, and the row now says plainly that the word "every" became true on 2026-09-18 and was not before, naming both fail-opens and their fixes. The reviewer also noted no disposition record existed for the pass that produced the register — this file is that record for this pass
review finding 5 (MEDIUM) — THE FAIL-LOUD TEST CERTIFIED A CLASS AND EXERCISED ONE INSTANCE. _screen_outbound caught Exception only. Measured: SystemExit, KeyboardInterrupt and a bare BaseException from a screener each left the payload undelivered — so this was never an open door, and the reviewer said so — but the kill-switch did NOT latch and nothing was recorded, so the next send on the next socket proceeded as though the screen were healthy | FIXED | fc3106fb — A BaseException arm that trips and then RE-RAISES UNCHANGED. Re-raising is the point: swallowing SystemExit or KeyboardInterrupt to force a trip would break interpreter shutdown and Ctrl-C, which would be its own defect. Locked by TestAScreenerThatRaisesOutsideExceptionStillLatches, parametrised over the three, asserting both that the exception propagates and that the latch is set
review finding 6 (LOW) — THE TRIP REASON STATED A TRUTHINESS TEST THE CODE NEVER MADE. _normalise_screen_result's fallback is reached by any value with no readable verdict, falsy included — correct and fail-closed — but it labelled the trip "non-standard TRUTHY verdict", so an operator whose screener returned 0 or "" was told something false about their own system while reading a kill-switch alert | FIXED | fc3106fb — Reason is now "exfil screener returned an unreadable verdict", and the docstring states explicitly that the branch is NOT conditioned on truthiness. Locked by TestAnUnreadableVerdictTripsWithAnHonestReason over 0, "", 0.0 and a bare object, with None/False as the fail-closed-must-not-become-fail-always control
review finding 7 (LOW) — wire_into_egress_guard's IDEMPOTENCY DOCSTRING WAS HALF FALSE, AND THE TEST GUARDING IT COULD NOT SEE THE ERROR. register_arm_hook de-duplicates by identity and the hook was a fresh lambda every call, so three calls stacked three arm-hooks; test_wire_is_idempotent's docstring claimed BOTH halves de-duplicated but asserted only the screener count, which register_screener's own de-dup held at 1 regardless | FIXED | fc3106fb — The hook is now a named module-level function, so identity de-duplication can see it. The test calls the wiring THREE times (two would also pass against an off-by-one) and asserts the arm-hook count as well as the screener count. Mutant M15 restoring the lambda kills it
reviewer's note — WHAT COULD NOT BE BROKEN, recorded because a failed attack is evidence | REJECTED | Not a defect. Isolation and ordering held under every arrangement tried: the class alone, each test alone, five consecutive fresh sessions, reversed class order, ON immediately followed by OFF to carry the trip latch, and the file forced first in the directory — 14/14 or 3/3 every time. No state leaked outward (0 skipped). The registration toggle itself is genuinely locked: five independent production mutants (register_screener a no-op, sendall skipping screening, the verdict computed then ignored, trip firing while the payload still leaves, exfil_screen.screen never detecting) each killed the ON test. Axis 7 had no target — nothing reads this file's source text as a lock. Scenario 3 does not overclaim
```

## Mutation, after the fixes

Ten mutants, each reverting exactly one fix, run against `tests/security/test_egress_screen_wiring.py`:

| mutant | outcome |
|---|---|
| M1 `_is_external_screen_target` always False | DEAD |
| M2 `_tag_screen_outbound` a no-op | DEAD |
| M8 `allow_external_endpoint` a no-op | DEAD |
| M9 `_as_payload_bytes` back to the three-type form | DEAD |
| M10 unscreenable payload silently skipped again | DEAD |
| M11 `dup()` no longer carries the tag | DEAD |
| M12 BaseException handler removed | DEAD |
| M13 the unreadable-verdict reason says "truthy" again | DEAD |
| M14 an unreadable verdict passes as clean | DEAD |
| M15 the arm-hook is a fresh lambda again | DEAD |

**M9 survived the first attempt, and that is the part worth recording.** The end-to-end array test
asserted only that the secret was not delivered and that the guard tripped — which stayed true with
the fix reverted, because finding 2's other half now makes an *unscreenable* payload trip as well.
"Screened and blocked" and "unscreenable and refused" produced the identical signature, so the test
could not tell which had happened. It now asserts the trip REASON names a positive detection, and a
separate test asserts `_as_payload_bytes(array.array(...))` returns the exact secret bytes. That is
the same two-worlds-one-signature defect the off-test itself exists to retire, reproduced inside the
fix for it.

## Verification

`tests/security/` with all fixes in: **1300 passed, 2 failed, 0 skipped, 93.72 s**, elevated. The 2
are the known ADR-013 doc-pointer artifact, which fail in this worktree and pass in the primary
checkout. 1278 → 1300 is exactly the 22 tests added here. The reviewed file alone: 36 passed.
