# Disposition — #1031 S2 elicitation interview CODE, independent pre-merge review (2026-07-28)

Review: independent author≠verifier subagent over commit `b375286c` on
`feat/1031-s2-interview`, verdict **NEEDS-FIXES** (2 MED / 3 LOW; "nothing undermines
dormancy or flag-off byte-identity"). The reviewer EXECUTED the touched suites (224
passed) and probed the parser by execution, not only reading — which is how F2 was found:
the F1 carve-out covered the pipe-less RUN shape but not the pipe-less CREATE shape, a
second door into the same eats-operator-text class. The reviewer also verified clean the
full list the brief demanded: every parser remainder shape, the marker seam (including
the marker×revise NON-interaction — both revise branches key on the original `idea`),
engagement byte-identity, the #1152 park-until-success contract untouched, threading at
every seam, and the §6 decision preserved for the LA as the design's recommended option.

Fixes at `06468c76` on the branch; fix-verification round returned to the same reviewer.

```disposition
F1 the design-committed end-to-end record lock was delivered spec-level only - no disk-record round-trip, no banked-replay case, no real-store intake park, despite the commit message claiming all 8 design-review findings folded | FIXED | 06468c76 - axis tags locked through the DISK acceptance record (write_acceptance_record → read_acceptance_record → from_dict); an intake park locked through the REAL born-encrypted store + restore_at_boot (intake=True survives); banked axes-tagged answers locked replaying intact through the real store; the §6 memory-defer notice locked rendering with the forget escape
F2 the F1 carve-out missed the pipe-less CREATE shape - "/dispatch advanced new look with dark mode" consumed a pending answer as a create attempt with "advanced new" eaten from the echo | FIXED | 06468c76 - the flag attaches only on create WITH a non-empty goal (the piped new-name-pipe-goal form); the pipe-less create shape re-parses the ORIGINAL text; parser lock + corridor lock (answer beginning "advanced new" recorded verbatim)
F3 the parser comment overstated the ambiguous-repo trade-off (the piped form for a repo named "advanced" still parses unchanged - only a never-valid shape was lost) | FIXED | 06468c76 - comment states the true milder trade-off; the piped repo-named-advanced form is locked parsing unchanged with the token on
F4 current-wiring vocabulary ("live") on the field docstring and the toml block - a posture claim that rots on re-weld | FIXED | 06468c76 - both surfaces now say "the front flag/key" without asserting posture, matching the sibling register
F5 the record carry admitted any non-blank string as an axis label (the shipped test PINNED "7" as accepted); answered_from_free_text with zero questions minted axes: [] | FIXED | 06468c76 - membership validation against the closed INTAKE_AXES vocabulary at the carry (deny-by-default; junk and all-junk lists dropped, locked); the empty-question emission guarded and locked
```

## Carried, not dispositioned

The reviewer's remaining untested-path notes: `advanced new <name> | <goal>` end-to-end
through `_create_and_plan` is exercised at the parser level and the `_plan` delegation is
one line whose `advanced` threading is locked at `_plan`'s own seam; AO threading with
`interview=True` through the real PLAN handler is covered by the conjunction locks at the
`generate_plan` layer plus the handler harness field (the same depth every sibling
sub-flag carries); the intake-template generation-failure fail-soft is the inherited #819
absolute fail-soft, untouched by this diff and locked at its own seam. Each is recorded
here as an accepted residual rather than silently dropped.
