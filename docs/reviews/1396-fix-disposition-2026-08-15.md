# Disposition — independent review of the #1396 fix, 2026-08-15

Four independent reviewers (three read-only lenses plus a toggle-injector) were run against
the uncommitted #1396 change on `fix/1396-caveat-on-the-shipping-surface`. The author did not
review his own fix; every finding below was produced by an agent that did not write the code,
and every one was proved by EXECUTION against real trees rather than argued from the source.

**The headline is not flattering and is the point of the exercise: my first fix for "the
caveat is dropped on the surface that ships" dropped the caveat on a surface that ships,
three separate ways.** The review caught all three before the change left the branch.

Fix commit: `514c6362`. 258 tests pass. Two `xfail(strict=True)` markers deleted.

## What the review cost, and what it bought

| | |
|---|---|
| reviewers | 4 (completeness · over-firing · verdict-neutrality · toggle) |
| blockers found | 2 |
| majors found | 7 |
| of those, in MY fix rather than pre-existing | 3 blockers/majors |
| vacuous locks found | 1 (mine, in the same change) |
| tree left dirty by the injector | no — SHA-256 verified restore |

```disposition
# finding | status | evidence-or-predicate
_caveat_from_prose still passed `measured` after the helper was renamed to `finished` | FIXED | 514c6362 — helper now takes the RESULT and derives the predicate, so no call site can pass the wrong bool
to_sidecar dropped coverage_partial, relocating the substring dependency into the archive | FIXED | 514c6362 — persisted in both security and prose blocks
coverage_partial set from the file bound alone while its docstring promised "for ANY reason" | FIXED | 514c6362 — now bound OR unreadable OR unparsed OR abandoned-walk; docstring narrowed to what is implemented
unreadable files SHRINK `scanned`, so the bound test was false on genuinely truncated walks | FIXED | 514c6362 — `unreadable` is a disjunct; the files that prove the shortfall no longer hide it
_MAX_HIGH_FINDINGS break abandons the walk with nothing recorded (10 of 430 files, measured) | FIXED | 514c6362 — `walk_abandoned` set, named in status, prefixed on the stamp
is_clean() exclusion justified by a claim that is FALSE ON DISK ("it feeds the band") | FIXED | 514c6362 — band.py never calls it; the real reason (44 archived artifacts depend on the key's meaning) is now the one recorded in code
card comment claimed the new caveat "costs the slot only when there is no finding to displace" | FIXED | 514c6362 — it does displace prose/layer1; comment corrected to say so and to name the precedent it follows
prose docstring claimed the sibling field "carries the same contract" when it did not | FIXED | 514c6362 — reconciled disjunct for disjunct, including the shared deliberate exclusion
test_a_finding_on_a_capped_scan_says_BOTH was guarded by `if result.findings:` (vacuous shape) | FIXED | 514c6362 — hard assertion; measured that the branch is genuinely reached (1 finding, PARTIAL SCAN — 1 high: provider-credential)
test_the_cap_caveat_is_absent_when_nothing_was_truncated passed with the defect injected | REJECTED | it is a lock on `status`, not on `coverage_partial`, and predates this change; it asserts the absence of the prose sentence and is correct at what it locks. The new field's toggle is test_the_card_stays_silent_when_the_scan_really_did_cover_everything, which DID fail under injection 6.
prose all-unreadable site reports `applicable=False` — a positive claim, fail-open | DEFERRED | #1399 blocked-by: the 2026-08-14 23:00 battery run completing, or being confirmed not to have run
layer1 partial-coverage detail reaches no shipping surface; walk capped at 400/800 uncounted | DEFERRED | #1397 blocked-by: the 2026-08-14 23:00 battery run completing, or being confirmed not to have run
grader source edited 27 minutes into a live battery run | REJECTED | consequence nil and now verified rather than assumed: run-battery-night.ps1:1395 Push-Locations to $BlarMeasuredRoot, so `-m tools.dispatch_harness.battery` imports from the pinned tree (`blarai-battery-measured` @ 266f5af7), not the working checkout. The process criticism stands and is recorded below; the risk did not.
PARTIAL SCAN prefix can clip a trailing rule id off the 300-char evidence stamp | DEFERRED | #1400 blocked-by: the 2026-08-14 23:00 battery run completing, or being confirmed not to have run
exact-boundary overfire: a tree of exactly _MAX_FILES claims partial coverage | DEFERRED | #1400 blocked-by: the 2026-08-14 23:00 battery run completing, or being confirmed not to have run
band-A headline "Looks clean" now sits beside a coverage caveat with no bridging sentence | DEFERRED | #1400 blocked-by: the 2026-08-14 23:00 battery run completing, or being confirmed not to have run
guard-alias shape (`incomplete = ...`, `finished = ...`) inside two registered renderers | DEFERRED | #1400 blocked-by: the 2026-08-14 23:00 battery run completing, or being confirmed not to have run
```

## The process finding, kept because it is the transferable one

A reviewer noted that the grader source was edited 27 minutes into a live battery run, and
that the author established the consequence was nil only *afterwards*. That is correct and
worth keeping even though the risk was real-zero.

I did check the pin before editing — `blarai-battery-measured @ 266f5af7`, taken at 23:00:03 —
and that check was the right instinct. But it answers a different question than the one that
mattered. **The pin protects the SOURCE the battery reads; it says nothing about which tree a
already-running process resolves imports from.** Those happen to coincide here because the
launcher `Push-Location`s to the measured root, but I did not know that when I started editing.
The check I ran was necessary and I mistook it for sufficient.

## The pattern worth naming

Three of the four things the review found in my own work are the same shape: **I fixed an
instance, wrote a paragraph naming the class, and did not grep for the class.** Lesson 342,
for the third and fourth time in one night. The structural response is in the code rather than
in resolve: `_and_unfinished` no longer accepts a bool it can be handed wrongly.

The second pattern is subtler and worse. My `is_clean()` exclusion was justified by a factual
claim about a surface I had not read — I asserted it "feeds the band" and it does not. That is
LESSONS Rule 3 / authority_first: name the surface that owns the claim and READ it. A wrong
reason that reaches a correct conclusion still poisons the next session, which inherits the
reason and not the conclusion.
