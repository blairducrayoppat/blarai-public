# Disposition — #1165 M4 playback contract, independent pre-merge review (2026-07-29)

Review: independent author≠verifier reviewer over commits `71209ced` + `86d87a99` on
`feat/1165-m4-playback-contract`, verdict **NEEDS-FIXES** — ONE finding (F1, MEDIUM,
merge-blocking); everything else verified clean, including all five adjudicated claims
and both of the builder's argued deviations (accepted as argued — recorded below as
REJECTED rows carrying the reviewer's rulings). The builder's blocked-card reading was
pressure-tested at the builder's own request and REJECTED end-to-end (probe-confirmed
in all three blocked states); the deciding principle was the builder's own journal
fragment: a card text that offers a future action must be derived from the same state
that gates the action.

Fix at `90ee9289` on the branch; fix-verification round returned to the same reviewer.
The journal fragment's false "is locked" claim about the blocked-card reading was
corrected in the same commit — the fragment now narrates the rejected reading and the
fix, not the reading as shipped truth.

```disposition
F1 the playback invitation is blocked-blind - it appends AFTER the S3-F blocked footer yet offers "/dispatch approve when it reads right" while approve returns the blocked refusal, promises "I'll fix the plan" on the orphan-only block whose own footer says changing the plan's steps cannot fix that gap class, and at blocked-cap unconditionally offers the approve the blocked revise cap refusal deliberately withholds | FIXED | 90ee9289 - the carried coverage_blocked marker threads _close_card into _playback_invitation; the two questions render in every state, the approve tail drops while blocked, the orphan variant drops the fixing promise (classified from the CARRIED marker via coverage_blocked_is_orphan_only, whose signature sentence is embedded by the message builder in the same file so text and predicate cannot drift; builder output byte-identical), blocked-cap offers reject only mirroring the blocked revise refusal; five locks added (standard, orphan, blocked-cap walked through the real corridor, blocked toggle-off delta byte-identity, builder-predicate drift pair)
R1 reviewer recommendation, non-blocking: both revise cap refusals (plain and blocked) consume the operator's free text without echoing it back, so a re-routed playback reply at the cap loses its words - the one dispatch-corridor reply class still outside the #1116 keep-text guarantee | DEFERRED | #1168 blocked-by: #1168 ships `_keep_operator_text` wrapped around both cap refusals in `_revise` so the explicit verb and the re-routed playback path keep the words identically
D1 builder deviation, adjudicated: the cap-variant invitation wording is the builder's own - the design names the requirement that the card says so when the budget is exhausted but dictates no wording | REJECTED | not a defect - the reviewer accepted the argument: the design's sentence is a requirement without a template, the built variant keeps the template's two questions and swaps only the false fixing promise for the true exits, and the wording is now additionally state-correct after F1 (the blocked-cap variant mirrors the blocked revise refusal)
D2 builder deviation, adjudicated: re-routed free text at the revision cap hits the existing cap refusal rather than a keep-text wrapper, losing the echo an invited reply arguably deserves | REJECTED | not a defect - the reviewer accepted the symmetry argument: a playback correction IS a revision on one code path with no duplicated message to drift, the explicit verb behaves identically, and the capped invitation no longer invites free text which keeps the path rare; the missing echo is real but belongs to both cap refusals equally and is queued as #1168 rather than patched asymmetrically here
```

## Carried, not dispositioned

The reviewer verified and passed without findings: both flag-off toggle bars (the
usage/keep-text reply and the card delta) pinned by exact string equality; the carrier
round-trip discipline on both hold classes including pre-M4 restore and quick-park
byte-identity; reserved-verb precedence at the approval turn extending the #1160 lock
family; the #1158 launcher-harness parity chain including the new three-key
conjunction; and the validated-not-coerced resolution quartet on the new sub-key. The
full standing gate runs on the final tip at merge time (M1 merges first; this branch
reconciles after), not in this record.
