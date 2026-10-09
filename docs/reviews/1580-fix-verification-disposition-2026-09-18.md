---
title: "#1580 fix-verification of fc3106fb — disposition"
status: final
area: security
---

# Disposition — fix-verification of `fc3106fb` (#1580 round 2)

Companion to `1580-exfil-off-test-disposition-2026-09-18.md`, which disposed the ORIGINAL review of
`718e5b42`. This record disposes the independent re-attack of the FIXES that record claimed.
Separate file because the gate requires exactly one disposition block per record, and because these
are findings against my repairs rather than against the original change.

---

# Addendum — fix-verification of `fc3106fb`

**Run 2026-09-18, pre-merge, by an agent that wrote neither the code nor the fixes.** It re-attacked
all seven fixes independently rather than trusting the ten-mutant table, and reproduced every claim
by running code. Its own restore was verified: `git status --porcelain` empty, source md5s identical
to its pre-mutation backups.

**Its verdict on the original seven: 2, 4, 5, 6 and 7 genuinely fixed; 1 and 3 half fixed with the
load-bearing half still open; two new defects introduced by the fixes themselves.**

```disposition
# finding | status | evidence-or-predicate
verification finding 1 (CRITICAL) — THE SCREEN IS STRUCTURALLY BLIND TO TLS, AND fc3106fb IS THE COMMIT THAT PUT THE WORD "every" INTO THE GOVERNANCE REGISTER WITH A DATE ON IT. guarded_fetch permits https only (guarded_fetch.py:152) and drives httpx.Client; httpcore calls ssl_context.wrap_socket, and ssl.SSLSocket._create does fileno=sock.fileno() then sock.detach(), so the sending object is an ssl.SSLSocket with neither the guarded sendall nor _screen_outbound_enabled. Measured end to end with the real screen wired: plain HTTP produced 2 screener calls, tripped, secret blocked; real TLS produced 0 calls, not tripped, SECRET REACHED THE SERVER. Pre-existing, not caused by this branch — but the summary contradicted the record it summarised | FIXED | 46384fe3 — row 12 rewritten a second time the same day: the claim is struck through, the row states the screen is a control against PLAINTEXT-socket exfiltration that is never invoked for HTTPS, and carries the five-arm measurement with its three positive controls. What the control positively IS is stated alongside, because a residual that only names a gap misdescribes a mechanism that genuinely works for the traffic it can see. The reach itself is #1592, with its own arc: the failing-today TLS twin of the off-test, then the design, and opening a new interception point inside the one egress door is an LA posture call
verification finding 2 (HIGH) — FINDING 1 OF THE ORIGINAL REVIEW WAS HALF FIXED. test_connect_TAGS_ stubbed the decision with a lambda that ignores both arguments, so it locked "connect calls something" and not "connect asks about the destination it connected to". Two one-line production mutants — connect() passing a hardcoded 127.0.0.1 tuple, and the tagger passing family 0 — each make _screen_outbound_enabled never become True in production, and each left the file 36/36 green. With test_egress_sandbox_proving.py ignored, simulating the loopback-only box whose module-level skipif is the whole premise of the original finding 1, both also left the FULL security tier green | FIXED | 46384fe3 — the stub is now a recording function and the test asserts the real destination tuple and the socket own family reach the decision. Mutants N7 and N8 both die. The disposition prose above ("covers the decision and the connect() wiring separately, unconditionally") was an overclaim and is corrected by this addendum rather than edited away
verification finding 3 (HIGH) — connect_ex HAS ITS OWN TAGGING CALL AND HAD NO LOCK ON ANY BOX. Zero test references to connect_ex anywhere in the tree. Making its _tag_screen_outbound call unreachable left tests/security/ at 2 failed and 1300 passed WITH the sandbox module running — identical to the clean baseline. Worse than finding 2: unlocked everywhere, not only on a loopback-only box | FIXED | 46384fe3 — test_connect_ex_TAGS_the_socket_and_asks_about_the_REAL_destination plus its paired negative control, asserting the tag, the destination and the family. Mutant M8x dies
verification finding 5 (MEDIUM, NEW DEFECT INTRODUCED BY MY OWN FIX) — A Ctrl-C THROUGH THE SCREENER LATCHED THE KILL-SWITCH, cutting all egress including the loopback Policy-Agent gateway and the AF_HYPERV vsock, with a Lead-Architect-only re-arm. Reproduced: after the interrupt, a subsequent LOOPBACK connect raises EgressTripped. Before fc3106fb the interrupt propagated and nothing latched. An operator interrupt is not an ADR-027 section 3 anomaly, and this was a posture trade-off decided silently — which decision_boundary reserves to the LA | FIXED | 46384fe3 — SystemExit, KeyboardInterrupt and GeneratorExit now log at ERROR and propagate WITHOUT latching; a BaseException that is not control flow still latches, because that IS a screen failure and a later send must not proceed as though the screen were healthy. The original hole (nothing recorded, so the next send assumed health) is closed by the recording, which is what it needed; the latch was never the part that closed it. Mutants R3 (control flow latches again) and R4 (non-control-flow stops latching) both die
verification finding 6 (MEDIUM, NEW DEFECT INTRODUCED BY MY OWN FIX) — TRIP-ON-UNSCREENABLE FIRED FOR PAYLOADS THE KERNEL WOULD HAVE REFUSED ANYWAY. _screen_outbound runs BEFORE super().send(); a str, an object(), a __buffer__ that raises and a strided memoryview are each rejected by the raw socket with TypeError or BufferError, and each now cut ALL egress. The implication runs one way: if the socket ACCEPTS a payload it is C-contiguous, on which the cast succeeds — so None means it was never going to leave, and every trip on that path was a false positive with a whole-process blast radius | FIXED | 46384fe3 — EgressDenied with a loud ERROR naming the type, and NO latch. Still fail-closed: the payload is refused and does not go. Locked by test_an_unscreenable_payload_is_REFUSED_without_cutting_all_egress over three shapes, with test_a_screenable_buffer_is_still_screened_and_still_trips as the control that the refusal is scoped to the unscreenable. Mutants R1 (trips again) and R2 (silently skipped again) both die
verification finding 7 (LOW) — trip() RAISING REPLACED THE PROPAGATING EXCEPTION, in exactly the shutdown case the fix own comment cites: _alert_operator can raise when logging handlers are closed. Reproduced: propagated RuntimeError, identity not preserved. The latch was still set and the original survived in __context__, so nothing was lost — but "re-raises unchanged" was not unconditionally true | FIXED | 46384fe3 — trip() is guarded in BOTH arms. The latch is set before the alert, so a raising alert costs the notification and never the state or the caller exception. Locked by test_a_raising_trip_does_not_replace_the_propagating_exception, which asserts identity and the latch. Mutant R5 dies
verification finding 4 (MEDIUM-HIGH) — THE dup() FIX COVERS dup() ONLY, and "the tag belongs to the connection" is false as written. socket.fromfd and detach-then-rewrap both DELIVERED the planted secret off a tagged connection with no screen, no trip, no log. makefile() is covered (it routes through the guarded send); os.dup is a non-route on Windows | DEFERRED | #1592 — the two uncovered routes have ZERO incidence in the runtime tree (a grep for fromfd, .detach(), os.dup and .dup() across shared/, services/ and launcher/ returns nothing outside egress_guard itself), and detach() is precisely the route ssl.SSLSocket._create takes, so this is the same defect as verification finding 1 seen from the object side rather than a separate one. Closing it separately would build a second answer to a question #1592 must answer properly. blocked-by: #1592 — the TLS reach design, which decides whether screening stays at the socket layer at all
verification finding 8 (LOW) — THE DISPOSITION AND ROW 12 OVERCLAIM IN PROSE. verify_disposition.py passes and every cited test exists and does what it says, but three sentences did not survive measurement: "unconditionally" (finding 2), "the tag belongs to the CONNECTION" (finding 4), and "the word every became true on 2026-09-18" (finding 1). The ten-mutant table is accurate for the ten it names; the gap is coverage — none touched connect_ex, the arguments connect() passes, or a non-dup duplication route | FIXED | 46384fe3 plus this addendum — row 12 corrected for the TLS finding, and the two remaining sentences corrected HERE rather than edited out of the rows above, so the overclaim and its correction both stay visible. That is the same discipline the register itself now follows
verification note — WHAT IT ATTACKED AND COULD NOT BREAK | REJECTED | Not defects. The full leak table (ten rows across bytes, bytearray, memoryview and array via send, sendall and dup) blocked with every trip reason naming a POSITIVE DETECTION rather than an unscreenable payload. Sixteen buffer shapes against two payloads: no shape delivered a secret and no shape a raw socket accepts was mis-screened — the cast produced exactly the bytes the kernel sends in every accepting case. The BaseException arm preserved exception identity and args in all four types tried. makefile() does not leak. The dup fix is a COPY not a set, so an internal socket duplicate cannot self-trip. One weak mutant survived by its own judgement — screening only the first registered screener — where exactly one is ever registered. One it could not run: sendmsg with a generator of buffers, a HYPOTHESIS it flagged as unreproducible because socket.sendmsg does not exist on Windows, and pre-existing either way
```

## Mutation, round 2

Twelve mutants against `tests/security/test_egress_screen_wiring.py`, including the three the
verification found surviving. All dead; baseline and restore both 43 passed.

| mutant | outcome |
|---|---|
| N7 `connect()` asks about a hardcoded address | DEAD |
| N8 the tagger passes family `0` | DEAD |
| M8x `connect_ex` no longer tags | DEAD |
| R1 an unscreenable payload trips again | DEAD |
| R2 an unscreenable payload is silently skipped again | DEAD |
| R3 control flow latches again | DEAD |
| R4 a non-control-flow `BaseException` stops latching | DEAD |
| R5 a raising `trip()` replaces the exception again | DEAD |
| M1 `_is_external_screen_target` always False | DEAD |
| M9 `_as_payload_bytes` back to the three-type form | DEAD |
| M11 `dup()` no longer carries the tag | DEAD |
| M15 the arm-hook is a fresh lambda again | DEAD |

## Verification

`tests/security/` after round 2: **1307 passed, 2 failed, 0 skipped, 94.06 s**, elevated — the 2 are
the known ADR-013 worktree artifact. 1278 to 1300 to 1307 across the two fix rounds.

## The honest note, second attempt

The first note said every defect was in the wiring. The verification's answer is sharper: two of my
seven fixes traded a fail-open for a **denial of service**, and I took both trades without saying so.
Tripping a kill-switch that cuts the runtime's own internal IPC — on a local type error, and on the
operator pressing Ctrl-C — is a posture decision, and `decision_boundary` puts posture with the Lead
Architect. Fail-closed was the right instinct; choosing the blast radius silently was not, and
"fail-closed" is not a licence that makes any radius correct.
