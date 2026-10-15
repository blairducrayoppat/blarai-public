# Disposition: independent review of the "replace wrong statements" rewrite (#1740)

**Review:** an independent adversarial-reviewer agent (did not write the rewrite), 2026-10-11, against branch
`docs/1740-replace-wrong-statements` at `7f1273a5` over `main` `1b947f9e`: the primer, the ADR-045 amendment, the
register row, the interim report and two journal fragments. It checked every replaced statement against the
workstream-0 notes and the banked data, hunted for surviving correction markup, and looked for new unsupported
claims. The rewrite was built by a builder agent; this disposition and the fixes were written by the lead session.
**Outcome:** verdict merge-after-fixes; five should-fix and four nits, all fixed in the same change that
rewrites the report for the phase-2 results.

What each fix is:

- `finding-1-primer-acl-order-is-a-new-incorrect-four-step-order`: primer section 2 and report: inherited entries are ordered level by level, refusals before allows at each level
- `finding-2-primer-section-5-still-says-the-sealed-room-starts-with-nothing`: primer section 5 rewritten from the measured results; sealed room now has a window onto Windows and Program Files
- `finding-3-primer-acl-coverage-and-per-launch-profile-claims-imprecise`: primer section 2 covers every securable object; section 5 states the profile persists per user until deleted
- `finding-4-journal-fragment-deleted-a-true-account-of-a-failure`: the 2026-10-10 #1740 fragment again records that the first draft said a restricted token cannot be the network fence and that the independent reviewer blocked it
- `finding-5-report-plan-stale-after-the-LA-approved-running-phase-2-now-and-adding-arm-E`: report rewritten: phase 2 and arm E run and reported; the ticket records the decision
- `finding-6-vm-stops-in-kernel-exploit-goes-beyond-the-source`: report and primer say a virtual machine is a separately serviced boundary and the stronger option
- `finding-7-primer-states-the-deny-entry-rule-flat-without-the-limits`: primer says no Microsoft page states it and lists the three places it held (access check, real file open, 12 of 12 launches)
- `finding-8-no-upper-bound-for-when-it-changed-is-known-is-false`: primer, ADR, report: the folder alone cannot say when it was locked
- `finding-9-coder-could-write-windows-temp-is-an-inference-from-a-throwaway-account`: ADR and primer: a throwaway restricted account could write it on 2026-10-05
- `finding-10-wording-section-4-lists-what-is-confirmed-and-adr-heading-parenthetical`: report section on the primer lists confirmed and unstated items separately; ADR heading parenthetical corrected

```disposition
finding-1-primer-acl-order-is-a-new-incorrect-four-step-order | FIXED | a34b2ebe
finding-2-primer-section-5-still-says-the-sealed-room-starts-with-nothing | FIXED | a34b2ebe
finding-3-primer-acl-coverage-and-per-launch-profile-claims-imprecise | FIXED | a34b2ebe
finding-4-journal-fragment-deleted-a-true-account-of-a-failure | FIXED | a34b2ebe
finding-5-report-plan-stale-after-the-LA-approved-running-phase-2-now-and-adding-arm-E | FIXED | a34b2ebe
finding-6-vm-stops-in-kernel-exploit-goes-beyond-the-source | FIXED | a34b2ebe
finding-7-primer-states-the-deny-entry-rule-flat-without-the-limits | FIXED | a34b2ebe
finding-8-no-upper-bound-for-when-it-changed-is-known-is-false | FIXED | a34b2ebe
finding-9-coder-could-write-windows-temp-is-an-inference-from-a-throwaway-account | FIXED | a34b2ebe
finding-10-wording-section-4-lists-what-is-confirmed-and-adr-heading-parenthetical | FIXED | a34b2ebe
```
