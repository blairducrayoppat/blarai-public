# Disposition — #1161 d1+d2 / #1160 d2 plan-time brittleness arc, independent pre-merge review (2026-07-29)

Review: independent author≠verifier subagent over `fix/1161-1160-plan-time-brittleness`
(build `ff1e359a` + vocabulary pins `73192215` + bare-site tier `1c9350cd`), verdict
**NEEDS-FIXES** (1 HIGH, 2 MED, 2 LOW — all confirmed by execution probes, not reading).
The reviewer also verified the core promise adversarially (assumed defaults can never
masquerade as operator words; no silent-timeout path; the #1160 accidental-answer path
defaults gradeable; mobile refusal pre-model on both plan paths; direction 3 genuinely
absent) and proved the seam locks reach the control via a neutered-refiner probe. Fixes
at `c7490a22`; fix-verification round returned to the same reviewer — **FIX-VERIFIED**,
19/19 probes, no new findings. A final test-only commit `a021a4a7` re-aimed one stale
harness fixture the full gate then caught (it silently pinned the pre-F3 menu — the
defect-era-configuration class) and added the F3 contrapositive lock at the dry-run
seam; the reviewer verified it on disk and extended the verdict across all five commits. Suite figure of record at tip: 432 passed across the four
primary files (81/120/21/210) + 561 adjacent, 0 failed 0 skipped (the fix commit
MESSAGE's per-file split is wrong and superseded by these measured figures).

```disposition
F1 the web-force arm overrode an operator-NAMED CLI or desktop platform whenever a web word co-occurred ("a command-line tool that scrapes a website for prices" force-flipped to web) - violating the refiner's own only-unanswered-questions charter | FIXED | c7490a22 - the force now requires that neither the CLI nor the desktop word-scan matched the operator text (the bare-site subordination pattern one tier up); all three review probes + no-regression pins + the site-tier-leak re-verify locked; the web+cli-both-named residual documented honestly in the fragment
F2 a model-authored language_hint (dotnet) suppressed the refiner - desktop-from-nothing survived that emission shape though the measured morning shape (hint null) was retired | FIXED | c7490a22 - _operator_corroborates_hint gates non-gated hints on operator-word corroboration (powershell/pwsh/ps1, c++/cpp scans; dotnet via the desktop early-return, defense in depth); the probe shape now steers to python CLI with the assumption note; both directions locked incl. corroborated legitimate asks
F3 the Inc-4 numbered menu still offered "On a phone" on an empty repo - an approvable mobile plan while the corridor refusal calls mobile not-a-capability | FIXED | c7490a22 - structural absence: suppress_phone_option_for_fresh_repo at the single menu-build site, before parking (parked question carries exactly the menu shown); 2-way forks degrade to an explicit one-option confirm; existing repos byte-identical (sibling lock); offer-then-refuse rejected as the menu itself being the lie
F4 the build-risk card line self-contradicted for exam-blind command-line plans ("Approve only if a command-line tool is really what you want" while recommending one) | FIXED | c7490a22 - names "A python command-line tool" when the blind stack IS command-line; desktop keeps the generic clause; locked both directions
F5 bare /dispatch revise, forget, or new at the question stage got the generic re-ask with no state correction - the uncorrected-misbelief half of the #1160 class | FIXED | c7490a22 - _no_plan_yet_lead gives each bare verb an honest per-verb lead (forget/new also state the job did not run), question stays parked, plain empty answer keeps the bare nag byte-identically; locked per verb
```

## Carried, not dispositioned

The reviewer's two documented-cost notes on the bare-site tier stand as in-code
documented costs, re-verified post-F1: "a job site for listing vacancies" is eaten by
the job modifier (the one genuinely two-sided compound; safe direction — disclosed CLI
default, one reject); novel compounds ("site survey tool", "site 9 inspection log")
read web but can no longer reach the force when a platform is named. The reviewer's
calibration caution is part of this record: the LA's kitchen-converter live-verify
demonstrates d1's measured shape and must NOT be read as clearing F1/F2/F3 — those are
cleared by their locks.
