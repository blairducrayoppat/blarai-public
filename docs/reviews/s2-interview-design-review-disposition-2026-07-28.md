# Disposition — S2 elicitation-interview DESIGN, independent adversarial review (2026-07-28)

Review: independent author≠verifier subagent over the committed design doc
(`docs/design/advanced_intake_S2_elicitation_interview_DESIGN.md` @ `6e0b22a4`), verdict
**APPROVE-WITH-FIXES** (1 HIGH / 3 MED / 4 LOW, no blockers). This review was the LA's
explicit overnight condition: a reviewer on the DESIGN itself, before code is built from
it, because a fresh design written and built off in one unattended stretch is where a
wrong assumption compounds. The reviewer verified 20+ line anchors on disk (clarify.py in
full), confirmed the doc's claimed parked-question mislabel defect is real and its fix
sufficient, and confirmed flag-off byte-identity except at the two seams it flagged.

All eight findings are DESIGN-TEXT amendments, folded into the doc at `68a06fa3` (the doc's §3.1/§3.2/§3.4/
§3.6/§3.7/§5 now carry each fix inline, tagged "review F<n>").

```disposition
F1 the advanced-token rule eats the word "advanced" from pipe-less operator text (a pending requirements answer starting with "advanced" reaches the corridor with its first word stripped — the #1116/#1126 eats-operator-text class, third instance would owe a structural control) | FIXED | 68a06fa3 - §3.2 rewritten: the flag attaches ONLY on create or piped run (non-empty repo); a pipe-less run-shaped remainder re-parses the ORIGINAL text untouched; a dedicated parse lock for the answer-starting-with-"advanced" shape added to S2c's locks
F2 _requirements_to_payload carrying intake unconditionally writes an extra key on every flag-off quick-path park — a byte change at the store seam the doc's own §3.6 discipline forbids | FIXED | 68a06fa3 - §3.4: the writer emits the key ONLY when True; reader stays d.get("intake", False)
F3 the §3.7 no-questions notice cannot reach its seam as written (_finalize_plan has no clarified_note parameter) and the Inc-4-interposes path would render a false notice colliding with _choose's own note | FIXED | 68a06fa3 - §3.7 states the _finalize_plan passthrough, restricts the notice to the direct tail call, deliberately suppresses it when the Inc-4 question fires, and adds the lock case
F4 the slice table calls S2d mutually independent of S2c but S2d's producer half (record_axes=True call sites) lives in S2c's functions | FIXED | 68a06fa3 - producer half moved into S2c's build cell; S2d reduced to the _coerce_clarifications carry + locks; dependency sentence corrected to S2d depends on S2a AND S2c
F5 the engagement conjunction omits its third member — [fleet_dispatch].clarify (live, operator-documented off-switch); with clarify=false an advanced dispatch silently yields the no-questions notice | FIXED | 68a06fa3 - §3.1 names clarify=true as a precondition and the go-live runbook obligation; §3.7 cross-references it
F6 project-memory replay re-emits banked axes tags onto later (including quick) dispatches once memory is live — unnamed interaction | FIXED | 68a06fa3 - §3.6 names the replay behaviour, scopes it to the LA-held §6 intersection, and extends the transcript round-trip lock to the banked-answer path
F7 S2a omits the template-selector mechanics (generate_clarifying_questions hardcodes _CLARIFY_TEMPLATE) and the max_questions threading for interview mode | FIXED | 68a06fa3 - S2a row names the template parameter (template: str = _CLARIFY_TEMPLATE); S2b row states generate_plan passes axes/max_questions/template explicitly over the existing max_questions carrier
F8 quote citation points at the wrong line (:16-17 wording differs; verbatim phrase at clarify.py:236 / acceptance.py:3827); the parallel-work note omits S3-G | FIXED | 68a06fa3 - citation corrected in §3.3; the builder note now names S3-F AND S3-G and the coordinator touch point
```

## Carried, not dispositioned

The reviewer's verified-TRUE list (sentinel survivability through revise/recall, WinUI
allowlist untouched, security-section honesty, §6 being the only genuine operator
decision) is recorded in the review report itself and stands as independent corroboration
of the design's load-bearing claims; nothing there asserted a defect. The reviewer's
honesty list names what it did NOT verify (the 2026-07-21 sketch's full content, the
quality-ledger row, live execution of any path) — none of those are load-bearing for the
build, and the build's own locks cover the executable claims.
