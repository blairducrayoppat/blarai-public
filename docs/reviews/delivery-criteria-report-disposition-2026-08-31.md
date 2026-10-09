# Disposition — delivery-vs-criteria probe (#1439), adversarial review 2026-08-31

**Change under review:** `feat/1439-delivery-criteria-report` — `8535488d` + `630d8a1b`
(journal fragment) + `804660f9`, built 2026-08-17 and unmerged for two weeks — plus the three
fixes made under this review: `0b6ad383`, `4ab51df6`, `48820c21`. Merged as `d483ffef`.

**Reviewer:** independent adversarial pass in isolated worktrees; the author of the fixes wrote
none of the review and the reviewer wrote none of the fixes. Every finding was reproduced by
running the probe against the 21 banked deliveries and against constructed trees, not by reading
it. The reviewer additionally ran the standing selection three times (main control, branch alone,
trial merge) and executed 10 mutations against the 26 pre-existing locks.

**Outcome:** 5 findings plus one process finding. **One was a merge blocker and was fixed before
merging, not ticketed.** Nothing deferred. Two further defects were found by the author while
fixing the blocker — both in the author's own new locks — and are recorded here rather than
quietly corrected.

**Verification after fixes:** standing gate on merged main, REAL checkout: **11342 passed /
0 failed / 0 skipped / 133 deselected** (383.45 s). The branch run in a worktree read
11317 / 2 / 23, and 11317 + 2 + 23 = 11342 — the 25 are worktree-depth artifacts that pass
in the real tree. Predicted 11317 and it printed 11342; the miss was chased rather than
overwritten, and it showed the prior 11286 stamp was itself a worktree figure.
Probe suite 31 locks, all green, toggle-proved — a mutation restoring the pre-fix behaviour turns
all three new c1 locks red, and the restore was verified byte-identical by sha256 using
`read_bytes`/`write_bytes`.

**The strongest evidence is not the tests.** The reviewer computed, before seeing any fix, what a
correct one must produce: c1 SATISFIED falling from 11/21 to **exactly 2/21**, naming
`20260810-094231` and `20260810-204018` as the two survivors. The fix produces exactly those two.
An independent falsifiable prediction, met precisely, is worth more than a suite the author wrote.

```disposition
c1-rewards-deleting-pages: c1 was decided by an INBOUND orphan audit alone, so a site got BETTER at it by shipping FEWER pages. Delivery 20260830-011833 (one content page, no contact page, menu linking to two files not on disk) scored SATISFIED and OUTSCORED a strictly better three-page build. 11 of 21 deliveries scored SATISFIED, 9 shipping no piece page at all, the three worst being the three most recent | FIXED | BlarAI@0b6ad383 + 48820c21 - three halves now: COUNT (read from his sentence only), OUTBOUND (every linked .html was delivered, exempting a link an exact quoted server route answers), INBOUND (unchanged). Count unreadable -> NOT DECIDABLE, never SATISFIED. Corpus 11/21 -> 2/21, matching the reviewer's independent prediction exactly. Locks: test_a_link_to_a_page_that_was_never_delivered_fails_c1, test_fewer_pages_than_the_criterion_names_fails_c1, test_deleting_the_orphan_must_not_turn_a_failure_into_a_pass.
c1-docstring-promised-an-absent-check: the function's docstring claimed it verified "at least as many content pages were delivered as his sentence names"; grep for that count returned only the docstring. Prose that never matched its code, for two weeks, in a file whose whole purpose is not overclaiming | FIXED | BlarAI@0b6ad383 - the promised check is now implemented and the docstring rewritten to describe all three halves and to state WHY the first two are not optional. Had it been implemented, the blocker above would not exist.
fixtures-cannot-express-the-failing-shape: build_site() had knobs for every defect except omitting pages, so the 26 locks exercised a full site and a no-HTML tree and never the degenerate middle where the defect lives. No test mentioned page count or dangling targets | FIXED | BlarAI@0b6ad383 - 5 locks added building the degenerate shapes by deleting pages from a complete fixture, which is exactly what the real deliveries did. The pre-existing assertion that a FULL site earns c1 SATISFIED was kept, not deleted, so the fix cannot over-correct into permanent NOT DECIDABLE.
authors-property-lock-was-decoration-twice: the author's own regression lock for the blocker passed against the very defect it named, in two successive versions. v1 compared total SATISFIED counts (deleting pages also degrades c3/c4/c5, so the total falls while c1 wrongly improves); v2 compared c1 before and after deletion (under the defect BOTH read SATISFIED) | FIXED | BlarAI@0b6ad383 - v3 reproduces the corpus inversion: orphan the detail page so c1 fails, then DELETE the orphan, and under the old code the verdict improves. Both dead versions were caught ONLY by mutating the fix out and watching the lock stay green, which is the entire argument for toggle-proving rather than trusting a lock.
outbound-audit-convicted-route-served-links: a naive file-existence audit would call a page served as "/contact" by a server route with no contact.html on disk a dead link. Reviewer measured 15 dangling targets across 21 deliveries, NONE route-served, so zero false positives today | FIXED | BlarAI@48820c21 - the audit consults delivery.server_js (already read for the c5 method check) before convicting. Deliberately conservative: only an EXACT quoted route exempts, so an unrecognised route form convicts rather than excuses - a false alarm is loud, a wrong exemption hides a real dead link. Corpus verdicts unchanged, confirming it is a guard against a shape that has not yet appeared rather than a behaviour change.
banked-c6-tally-contradicts-the-code: ticket comment 3207 and the journal fragment both state c6 across the twelve deliveries is "6 NOT SATISFIED, 5 NOT DECIDABLE, 1 SATISFIED"; the code at that same hash measures 7/4/1 | FIXED | BlarAI@0b6ad383 - all seven NOT SATISFIED deliveries re-inspected, each having zero per-field messages, so the CODE is right and the STATISTIC was a miscount. The journal fragment now states 7/4/1 and records that it first said 6/5/1 and why it changed. Record corrected, probe untouched.
documented-cli-flag-does-not-exist: the module docstring's Usage block said `--delivery <path>`; the real flag is `--delivery-path` (`delivery` is positional). It worked only by argparse prefix matching and would silently break every documented invocation the moment any second `--delivery*` flag was added | FIXED | BlarAI@0b6ad383 - docstring corrected to the real flag.
no-disposition-record: per deferral_discipline, a review returning findings requires a disposition record before the work is reported done, and docs/reviews/ held nothing for #1439 | FIXED | BlarAI@d483ffef merged the work; this record is docs/reviews/delivery-criteria-report-disposition-2026-08-31.md, committed on branch docs/1439-disposition. The verifier rejected the first draft of this row for naming no commit-ish evidence, which is the control working on its own record.
```

## What was attacked and held — recorded because a clean result is a result

The reviewer states these plainly rather than manufacturing findings, and they are the reason the
branch was worth merging rather than rewriting:

- **The empty-input guard is real.** Six degenerate trees (empty directory, README-only,
  fragments-only, empty `public/`, binary-garbage HTML, pages outside the web root) all return
  **8/8 NOT DECIDABLE, zero SATISFIED**. All seven web checks call `_no_web_surface`.
- **The 26 pre-existing toggle-proofs are genuine.** Ten mutations reintroducing the defects the
  locks claim to pin — c7 inferring green from a start script, c8 allowed to return SATISFIED,
  the guard removed, HTTP method dropped, dead scripts treated as runnable, the error-write
  counter accepting `textContent = ''` clears, and others — **every one turned at least one lock
  red. No lock passed against broken code.**
- **The c6 correction in `804660f9` is right, and the author's pushback against the reviewer of
  that round was justified.** `20260817-070902` attaches `blur` and `change` listeners writing
  `'Name is required'` on empty input, so SATISFIED is correct there; a blanket "required +
  submit-only ⇒ NOT DECIDABLE" rule would have lost the one build in twelve that solved it.
- **Distinctness holds.** Three named fixtures → 3 distinct profiles with the documented tallies
  3/2/3 · 3/3/2 · 5/1/2; first twelve → 6 distinct; all 21 → 10 distinct.
- **The merge is mechanically clean.** 3 new files, 2,696 insertions, zero deletions, no
  conflicts, and it touches nothing `main` changed in two weeks — a `git diff main..branch`
  appears to show `morning_digest` changes, but those are `main`'s own #1442 work displayed in
  reverse. Verified by `git log` over the paths from the merge base.

## Notes carried forward, not deferred

- **This ticket was nearly rebuilt from scratch today.** A session read the ticket DESCRIPTION and
  `docs/ROADMAP.md`'s row and never listed the ticket's COMMENTS, so it did not learn the work
  already existed on an unmerged branch. It produced a 612-line duplicate, and its "correction" of
  the ticket's hand-computed c6 verdict re-asserted an error comment 3207 had retracted two weeks
  earlier. Retracted at comment 3306; the duplicate branch is preserved, not deleted. **The
  roadmap's own text names this gap** — its verifier catches a CLOSED ticket but cannot catch an
  OPEN one whose remaining work is not what the row says. Roadmap row 1 needs re-describing from
  "build the probe" to "merge the built probe"; recorded on #1439 as the next action.
- **The probe is still wired into nothing.** It is advisory and runs by hand. #1439's description
  names it as the per-criterion signal #1321's carry-forward will key on — which is precisely why
  the blocker had to be fixed before merging rather than ticketed, since carry-forward driven by
  the unfixed version would have preferentially kept the emptiest build.
- **The count check is the weak leg and does not carry SATISFIED alone.** Counting page-kinds from
  an English sentence is guesswork, and a bare count is satisfied by four pages of any kind. The
  outbound audit is the load-bearing half; SATISFIED requires the count derived *and* both audits
  clean. Stated here so a later change does not quietly let the count stand on its own.
- **A gate run was killed and restarted** because the author edited files while it was in flight.
  A gate that spans an edit describes a tree that no longer exists. The restarted run on a settled
  tree is the 11317 figure recorded above.
