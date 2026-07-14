### 2026-07-12 — The 6,650 deletions that weren't

*Plain summary: reconciled the Coordinator C1 read surface (#843) onto current `main`
after the #848 self-governance boundary landed. The stale-based held branch's alarming
`git diff main..branch` (+4278/−6650, 77 files) was almost entirely a diff-direction
artifact — main's 27-commit advance the branch simply lacked, not conflicting content.
Recovered by cherry-pick onto a fresh branch off `main`, preserving #811 and #848 by
construction. Lesson 52 recurrence (successful proactive application).*

The handoff brief was confident and wrong in a specific, instructive way. It warned that
`feat/843-c1-read-surface` "carries its OWN `shared/coordinator/` state — all 6 files
differ from main's #848 version, ~1807 lines of divergence," and that a plain merge
"will conflict / clobber #848's F1 `st_nlink` work." That framing would have had me
hand-reconciling six governed-core files that, on disk, do not exist on the branch at all.

The branch predated #848 entirely: its merge-base with `main` (`f057243f`) sat 27 commits
back, before the self-governance boundary was even authored. So `git diff main..branch`
rendered #848's whole `shared/coordinator/` tree as *deletions* — 1807 lines shown with a
leading `−` not because C1 removed them but because C1 never had them. The headline
−6650 was the same illusion at scale: main's advance (journal fragments, `shared/tests`,
`shared/fleet` swap-driver work, #811, #848) all reads as "deleted" when you diff the old
branch against the new tip. The brief had inherited the wrong base's numbers and narrated
them as intent.

The one move that separated signal from noise was reading the commit's *own* patch —
`git diff f057243f f2e93531`, base to tip — which is what a cherry-pick actually replays.
That showed **+3853 / −8 across 19 files, essentially additive, touching none of
`dispatch.py` / `swap_driver.py` / `swap_ops.py`.** From there the reconciliation stopped
being scary: a cherry-pick onto fresh `main` replays only those additions, and it
*structurally cannot* drop #811's `resolve_fleet_root` or #848's `st_nlink` deny, because
C1's commit never touches the files they live in. The −6650 was never real work to
preserve; it was the absence of work the branch hadn't caught up to.

So I recreated C1 as a cherry-pick onto a fresh `feat/843-c1-reconcile` off `f1dc5627`.
Two conflicts, both the `[coordinator]` overlap I expected — and the `entrypoint.py` one
was the #811 watch-item made concrete: C1's stale side tried to reintroduce the pre-#811
`fleet_dispatch_projects_dir=str(...)` line, reverting the env-override resolver. I kept
main's `resolve_fleet_root(...)` line and #848's SG keys, and layered C1's three
read-surface keys on top — merging the two parallel-authored `[coordinator]` TOML sections
into one dormant section rather than letting the second header shadow the first. The proof
the LA asked for held exactly: `git diff main..reconciled` is C1's 19 files and nothing
else (+3845/−14), `shared/coordinator` and `dispatch.py` show empty diffs, and
`resolve_fleet_root` survives exactly once. An independent verifier (author≠verifier)
returned MERGE-READY on all five criteria; the LOCALAPPDATA-redirected standing gate ran
**7681 passed, 3 skipped, 0 failed**.

The trade-off worth naming: I chose cherry-pick-onto-fresh-`main` over both the
`git merge feat/843` the brief feared and the literal "re-type 3,853 lines fresh" reading
of "recreate the additions." The merge would have carried the stale branch as a parent and
risked silent stale-base deletions; the hand-rewrite is absurd at that size and error-prone.
The cherry-pick replays the exact additions with 3-way conflict surfacing where it matters,
and the additions-only diff is the safety net that would catch any stale-base deletion the
replay dragged in — which is precisely the check that let me trust the result.

**Next:** build C2 (#844 lifecycle coordination) on this reconciled foundation, then C3
(#845 heartbeat) on C2 — each dormant behind `[coordinator]` flags, author≠verifier
reviewed, and held for the LA's separate LIVE-flip ceremony (the one boundary that is not
mine to cross).

**Recurrence of lesson 52:** *(2026-07-12 — The 6,650 deletions that weren't)* the
Coordinator C1 branch was 27 commits stale, so `git diff main..branch` (+4278/−6650, 77
files, incl. #848's whole `shared/coordinator/` shown as deletions) read as C1 "carrying
its own conflicting governed-core files." Reading the commit's OWN base..tip patch showed
+3853/−8, additive, touching none of the governed core; recovery was a cherry-pick onto
fresh `main` that preserved #811/#848 by construction, proven by an additions-only
`git diff main..reconciled`. A successful *proactive* application of the "a builder's clean
N-file diff is only clean against its own base — diff against CURRENT main, read the
commit's own `git show --stat`, recover by cherry-pick onto fresh main" clause: the
discipline held *before* a bad merge this time, not after one.

*(commit `c1c15382` — C1 reconciled onto `main` via cherry-pick of `f2e93531`; landed via
merge `<this>`; independent author≠verifier review MERGE-READY; standing gate 7681
passed / 3 skipped / 0 failed, LOCALAPPDATA-redirected.)*
