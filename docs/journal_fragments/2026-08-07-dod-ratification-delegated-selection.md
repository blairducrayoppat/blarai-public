# Fragment — fold into BUILD_JOURNAL.md (lesson proposed, not numbered)

### 2026-08-07 — Ratification by delegation, and the document that got truer by reading worse

*Plain summary: the Lead Architect ratified the Definition of Done extensions the same evening
they were proposed — "I approve of all the proposed ones that you think are good" — and applying
the ratified status vocabulary moved two capability rows DOWN, because honest words for statuses
make optimistic labels impossible.*

The review report merged at 18:54 local; within the hour the Lead Architect ratified the whole
proposed set — capabilities 11-21, the status legend, the goal-coverage map, the row-6/8
amendments — with the selection delegated to me: approve the ones the review judged good. I
began executing at 19:22. That delegation was only receivable
as a full-set ratification because every item already carried a written endorsement in the review
record; had one row been endorsed with reservations, the delegation would have forced a
follow-up question instead of an action. Proposed lesson: **a WHY-owner delegating WHICH to the
HOW-owner is only safe when the HOW-owner's judgment is already on the record item by item —
endorsements written before the delegation arrives are what make "the ones you think are good"
an executable instruction rather than a new decision.**

The mechanically interesting part of my evening was applying the legend to the ten ratified
rows. Two moved DOWN under my relabel: capability 5 (reviewers) from LIVE to ARMED, because what I could verify from July was the
decision function with real inputs, and the observable — a review-skip actually withdrawn inside
a live dispatch — has never been seen; capability 4 (exams) from LIVE to PARTIAL, half its proof
set being unreachable in production and its first measurement unvouched. Nothing about the
system changed tonight; only the words did, and the document now reads worse and is truer. The
enforcement landed in the same change (`tests/security/test_coder_dod_grammar.py`): every row
must carry a status, statuses must lead with a legend word, LIVE requires a dated citation, the
two acceptance tests must state their execution — and the checker is itself proven on synthetic
bad inputs, per the freshly-ratified capability 14 rule that a lock that has never been seen to
fail is not a lock. Trade-off taken: the grammar checks FORM, not truth — a fabricated "LIVE as
of" date passes it; the defense against that stays the re-measurement cadence and the
event-driven reviews, and the gate's docstring says so rather than implying more than it checks.
Executed under shared-tree pressure: another session held the primary checkout (feat/1327 plus
untracked work), so this arc ran from a dedicated worktree with junctioned model directories —
the first time the full standing gate ran gate-equivalent outside the primary tree.

**Next:** the operator-facing morning read picks up B9's processed=1-of-4 shortfall; #1326
clears the two prose-vs-wiring defects; the first measurement against ratified rows 17-21 needs
its own attribution window.
