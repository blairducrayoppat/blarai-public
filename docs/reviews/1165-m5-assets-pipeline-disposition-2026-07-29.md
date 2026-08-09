# Disposition — #1165 M5 operator-assets pipeline, independent pre-merge review (2026-07-29)

Review: independent author≠verifier subagent over commit `393944b9` on
`feat/1165-m5-assets-pipeline`, verdict **NEEDS-FIXES** (one MEDIUM missing lock, two
LOW hardenings; every deviation the builder argued was verified clean, and the
builder-disclosed UC-010 seam was confirmed end-to-end by probe). The reviewer EXECUTED
eleven adversarial probes outside the worktree (junction + nested junction, non-elevated
directory symlink, blinded-predicate containment, raw trailing-dot/space creations,
NFC/NFD + 8.3 tilde shapes, reserved device names, instruction-shaped conforming names,
real-constant cap breaches at 65 files / 26 MiB, forged wire payloads, the UC-010
non-web collision through the real `generate_plan`, and three-direction flag-off
byte-identity with files present).

Fixes at `c9225236` on the branch; fix-verification round returns to the same reviewer.
The UC-010 re-target ruling minted #1172 (accept-and-disclose interim; the builder's
refusal to pre-exclude a `generated/` subfolder was upheld — silently ignoring an
operator's real folder of that name would trade a visible mixed-provenance line for an
invisible loss).

```disposition
F1 the design-required containment-after-resolution lock was missing from the suite - the control worked when probed (real junction, reparse predicate blinded, the resolve/relative_to check still refused) but no test pinned it independently, so a refactor could silently collapse two locks into one lock wearing two hats | FIXED | c9225236 - test_containment_alone_stops_a_junction_escape drives a REAL junction escape with _is_reparse_point monkeypatched False and asserts every escaped file is refused, counted, and never enumerated
F2 _coerce_operator_assets re-validated the NAME but only membership-checked the CLASS, so a forged local payload could relabel evil.py as image into the coder stamp; the docstring claimed more than the code enforced | FIXED | c9225236 - the wire twin re-DERIVES the class via _operator_asset_class and DROPS a mismatch (validate-don't-coerce); docstring restated to exactly what is enforced; locked by test_coerce_drops_a_class_that_the_name_does_not_derive
F3 Win32-unstatable trailing-dot/space names died in the reparse probe's fail-closed arm and were miscounted as unsupported-type instead of earning the rename advice; the skipped_other card line said file(s) when one skip can be a whole too-deep folder | FIXED | c9225236 - the filename rule now runs BEFORE any stat (pure string check first), locked with raw backslash-question-mark-backslash creations; the card line reads item(s) and names the too-deeply-nested case
UC-010 non-web generated images target assets/slug.png inside the operator folder contract - a previously image-generating non-web project carries machine-made files the card acknowledges as folder contents (mixed provenance, visible and vetoable; web targets are structurally collision-free and locked) | DEFERRED | #1172 blocked-by: #1172 re-targets the UC-010 non-web generated-image path out of the operator assets root; until it lands the interim posture is accept-and-disclose (enumerate_operator_assets docstring + the locked web non-collision)
```

## Carried, not dispositioned

Two reviewer observations, no action required this round: (1) reserved Windows device
names (`CON.txt`, `NUL.png`) conform to the filename allowlist and ride as quoted inert
data — safe by construction (names never gain instruction authority and are never
dereferenced as paths by anything but the walk that found them), recorded as a
friendly-hardening candidate for a later pass; (2) the `battery-` repo-prefix
self-suppression means a hypothetical non-battery project whose name starts with
`battery-` never gets the pipeline — the pre-existing `_is_card_driven` trade-off shared
by every S1/S3 floor, accepted when that predicate shipped, not widened by M5.
