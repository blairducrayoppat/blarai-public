# Independent curation review — journal fold 2026-07-22

**Reviewer:** independent (did not author the change).
**Scope:** LESSON CURATION ONLY — `LESSONS.md` + `docs/archive/lessons/LESSONS_ARCHIVE.md`
as changed by `a89783f8` and `2c6d403b` on `docs/journal-fold-20260722`.
**Spec:** `LESSONS.md` "Rules of this file" — Rules 2 (search before you mint),
3 (third-instance rule), 6 (numbering at fold-in only).

Findings are appended incrementally as each check completes. Ordering follows the
review brief: (A) third-instance compliance, (B) over-minting, (C) tally targeting,
(D) arithmetic.

---

## Status

- [x] (A) third-instance compliance — 1 finding, 2 nits
- [x] (B) over-minting — 0 over-mints; 1 finding on placement, 1 nit
- [x] (C) tally targeting — 10/11 clean; 1 mechanical defect, 1 nit
- [x] (D) arithmetic — touched lines all reconcile; 6 untouched lines drift (pre-existing)

**VERDICT: MERGE** (see justification at the end)

---

## Findings

### Method (shared by all four checks)

Script `scratchpad/rev/cmp.py` parses `LESSONS.md`'s "Index of every lesson" section
and `LESSONS_ARCHIVE.md`'s numbered corpus at BOTH `6df70ad5` (merge base) and branch
HEAD, then diffs them. Counts `↺n` on the index line against `\*\(recurred[:\s]`
markers in the archive full text, and `control:` occurrences.

Structural sanity at HEAD: 300 index lines, 300 archive entries, no duplicate numbers,
no number gaps 1..300, no index-without-archive or archive-without-index. Rule 6
(serial numbering at fold-in) is satisfied — 296-300 are contiguous, and no number
above 300 exists.

### (D) ARITHMETIC — touched lines reconcile; 7 untouched lines still drift

Base -> HEAD for every touched lesson (flag / archive `recurred:` count):

| # | flag | archive recurred | instances | ctrl idx | ctrl archive |
|---|------|------------------|-----------|----------|--------------|
| 3 | 0->1 | 0->1 | 2 | no | no |
| 8 | 4->5 | 4->5 | 6 | no->YES | yes |
| 33 | 0->1 | 0->1 | 2 | no | no |
| 46 | 6->7 | 5->7 | 8 | yes | yes |
| 47 | 2->3 | 2->3 | 4 | no->YES | yes |
| 156 | 1->2 | 1->2 | 3 | no->YES | none->YES |
| 171 | 0->1 | 0->1 | 2 | no | no |
| 194 | 0->1 | 0->1 | 2 | no | no |
| 222 | 6->7 | 6->7 | 8 | yes | **not found by string match — verified separately below** |
| 265 | 0->1 | 0->1 | 2 | no | no |
| 293 | 0->1 | 0->1 | 2 | no | yes |
| 296-300 | new, ↺0 | 0 | 1 | — | — |

**All 11 tallies reconcile at HEAD.** The author's arithmetic claim holds, verified
independently. Lesson 46's pre-existing off-by-one is real and is fixed: base carried
`↺6` against 5 archive markers; the change added 2 markers (one per commit) and set the
flag to 7, so 7 == 7. Naively bumping would have produced `↺8`.

_(the repo-wide drift half of (D) is below, after (C))_

### (A) THIRD-INSTANCE COMPLIANCE

Touched lessons at or past three instances: **8 (6), 46 (8), 47 (4), 156 (3), 222 (8)**.
All five have a control named in their archive full text. I read each. The author's
claim that only 156 newly crossed the line, and that 8 and 47 had pre-existing but
unmarked controls, **is true as far as it goes** — but it is not the whole picture.

Verified controls:
- **8** — `*(third instance — control: the steady-state benchmark protocol in
  scripts/benchmark_kv_cache_sweep.py … #709.)*` Real, pre-existing. `✓ctrl` justified.
- **46** — `*(control: the #762 load-line canary — agentic-setup scripts/fleet-lib.ps1
  Test-PluginLoadLines + Write-PluginCanaryVerdict …)*` Real, pre-existing, already marked.
- **47** — control named inline inside the 2026-07-11 tally: `control: the three-property
  tests/security/test_dependency_truth.py (forward truth, reverse truth,
  manifest<->lock consistency), watched failing against deliberate mutations before
  trusted. #810.` Real, pre-existing. **But see FINDING A1.**
- **156** — control shipped in this change: `control:
  test_every_post_seed_consumer_takes_the_planning_seed_not_the_bare_goal — an ast
  enumeration of EVERY call after the seed mint … deny-by-default against an explicit
  allowlist (rule_spec alone) … reached-by-the-seed assertion … planted violation.`
  Correct discharge of Rule 3, in the same change, with a toggle-off. No finding.
- **222** — control present but in a **non-standard marker**: `*(THIRD INSTANCE — the
  class's control is the positive-control discipline made structural across the
  grading-instrument fleet … #827/#828/#837.)*`, not the `*(control: …)*` form Rule 3
  prescribes. Substance is there; form deviates. See NIT A3.

---

**[FINDING] A1 — Lesson 47 was marked `✓ctrl` in the same change that recorded an
instance the existing control provably does not cover, and the admitted gap was left
with no fix, no ticket and no predicate.**

The new fourth-instance tally on 47 says so itself, verbatim:

> "Note the control shipped at the third instance (`tests/security/test_dependency_truth.py`)
> covers MANIFESTS, not ceremony-read config comments — **that gap is this instance's
> finding**. #1031/#1042."

So the change simultaneously (a) records a fourth instance that escaped the control,
(b) states in writing that the control does not cover the escaping shape, and (c) adds
`✓ctrl` to the index line, whose entire function is to tell a future reader "this class
is enforced, stop worrying about it." The pre-mint search surface is the index. A
reader doing a Rule-2 search on the config-comment-lies class now sees 47 flagged as
controlled and moves on.

The author's stated rationale — "an unmarked control reads as an outstanding Rule-3 debt
that does not exist" — is only half true. The manifest control exists. **An outstanding
Rule-3 debt also exists**, for the ceremony-read-config-comment shape, and it is
newly created by this very tally. Marking `✓ctrl` erases the signal for exactly the
shape that just cost the most ("the most expensive surface this class has yet reached"
— its own words: the artifact the LA reads AT a go-live ceremony).

`#1031`/`#1042` are the S1 build/review tickets, not a control ticket, so this does not
satisfy `<deferral_discipline>` either: the finding is stated, then neither fixed nor
given a `blocked-by:` predicate a later session can observe.

**Fix (either is acceptable, the first is better):** ship the control — a gate test that
parses `default.toml` comments for flags in the go-live set and asserts each claim
against the code, which is the same shape as the already-shipped WinUI passthrough
allowlist parser; or, if it is genuinely a decision, mark the index line
`✓ctrl(partial)` (or drop `✓ctrl`) and file a ticket with an observable predicate,
cited in the tally in place of "#1031/#1042".

**[NIT] A2 — Lesson 222 carries a live sub-class obligation that this change's own tally
walks past.** 222's 2026-07-21 tally ends: *"Second never-wired-instrument instance in
two days; **a third must ship a structural control in the same change**. #1001."* The
2026-07-22 tally added here (1005 grading-differently-wrong) is a different shape — an
instrument artefact under an unconstrained probe, not a never-wired instrument — so the
sub-class obligation is **not** triggered and nothing is owed here. Recording this only
because the armed obligation is now buried under a newer tally and the next session to
tally 222 needs to see it. No action required in this change.

**[NIT] A3 — Lesson 222's control is recorded as `*(THIRD INSTANCE — the class's control
is …)*` rather than Rule 3's prescribed `*(control: …)*`.** Pre-existing, not introduced
here. It defeats a mechanical Rule-3 audit: a script grepping for the prescribed marker
reports 222 as an uncontrolled 8-instance lesson. Worth normalising at the 2026-10-01
quarterly pass, not worth blocking a fold.

### (B) OVER-MINTING — no finding. All five mints survive an independent search.

Method: for each of 296-300 I ran keyword sweeps over the "Index of every lesson"
(lines 272-604 of `LESSONS.md`) and over the full archive, then read every candidate
neighbour's full archive text rather than judging from its index line.

**299 (destructive git during cleanup) — the contested one. The author is right.**
This is the mint I most expected to overturn, and it holds. Evidence:

```
grep -oE "git (checkout -- |reset --hard|branch -D|branch -d|clean -f|push --force)" \
    docs/archive/lessons/LESSONS_ARCHIVE.md
```
returns exactly two hits, `git checkout --` and `git branch -D`, **both on line 613,
which is lesson 299 itself.** Before this change the archive contained zero mentions of
any destructive git verb. An index sweep for
`destruct|discard|irrevers|checkout|reset|delete|undo|recover|backup|non-destructive`
returns 52, 53, 85, 173, 192, 207, 216, 226, 283, 286 — none of them this class.

The two named candidates fail on reading:
- **52** is wrong-branch-commit ("the worktree-isolation quirk can switch the main
  checkout's branch"). Its recovery narrative *cites* the never-discard rule — "Recovery
  stayed inside the never-discard rule" — but the lesson is about verifying `git branch
  --show-current`, not about destructive verbs. Citing a rule is not owning it.
- **172** is `git add -A` on a shared tree — a *staging* reflex, and the opposite
  polarity (sweeping work in, not throwing work out). Its own line: "the staged diff is
  evidence you *read*, never a net you cast."

The rule genuinely lived only in `CLAUDE.md <absolute_rules>` and in the memory file
`feedback_no_destructive_git_operations.md` — neither of which is a numbered lesson, and
Rule 2's search surface is the index. Minting was correct.

**300 (handoff omits the queue)** — closest neighbour is 14 ("a handoff brief is a map,
not proof the terrain is passable"), which is about the brief's *facts* being unverified
and whose control (`scripts/verify_handoff_brief.py`, #929) checks anchors. 300 is about
the brief's *scope* — a brief every one of whose facts verified green. Different failure,
different control. Mint correct.

**297 (name the surface that owns a claim)** — closest neighbour is 48 ("a load-bearing
factual premise gets verified on disk, not inherited through the review chain", ↺4,
controlled). I read 48 in full. 48's failure is *trusting a claim you did not check*;
297's failure is the opposite — the session checked exhaustively, but against derived
surfaces while the owning surface sat unopened. The remedies differ (verify-on-disk vs.
identify-the-owner-first). Mint defensible.

**296 (migrate doctrine by copy-then-verify)** — closest neighbour is 230 (one truth in
several copies, updating one gets it silently reverted). 296 is lossy *migration* out of
a repo being retired plus a pointer whose target dies, not sync-clobber. It cites 230 and
288 as `cf.` — which is exactly the Rule-2 behaviour of having searched, found the
neighbours, and argued the distinction. Mint defensible; this is the closest call of the
five and the author showed his work.

**298 (an instruction naming a command that cannot establish the precondition it
demands)** — neighbours 69, 144, 225 cited; 225 is about *sequencing* a cheap probe
before an expensive resource, 298 about an instruction being internally incoherent.
Mint correct. But see FINDING B1.

---

**[FINDING] B1 — Lesson 225's third-instance obligation is asserted inside lesson 298's
text and recorded nowhere on lesson 225 itself.**

298's control marker says the deny-by-default version "**remains lesson 225's unbuilt
third-instance control**, deferred to a battery attribution window because it changes the
instrument." But lesson 225's index line reads `225. Gate the expensive resource … · ↺1`
— two instances — and its archive full text (which I read in full) contains no control
marker, no pending-obligation note, and no ticket reference. The third instance lives in
the held-back fragment `989-ab-day-cadence-20260721.md`, which this change deliberately
did not fold.

The hold itself is well-judged and I am not contesting it: landing a sandbox-freshness
precondition inside the battery harness mid-A/B would break one-change-per-run, and
`#1058` is a real durable record. The defect is **placement**. A future session doing
Rule-3 work reads the index, sees 225 at two instances with no `✓ctrl` and no debt
marker, and has no reason to open lesson 298 — a lesson about a *different* class — to
discover that 225 is carrying an armed obligation. This is the same "a rule living in
only one of two mirrors is a rule waiting to be dropped" reasoning lesson 300's own
control invokes, applied to the lessons file itself.

**Fix:** add a marker on 225 in the archive naming the pending obligation and its
observable predicate — e.g. `*(third-instance control PENDING: sandbox-freshness
precondition in the battery harness; blocked-by: #1058 — instrument change, must not
land inside a battery attribution window)*` — and flag the index line so the debt is
visible at the search surface. No ordering problem: this records the obligation without
landing the instrument change.

**[NIT] B2 — The `perf-log-orphaned-narratives` tally on 33 leans on 33's first clause
and not its second.** 33 reads "Capturing data and publishing data are two separate
disciplines — **and a record that implies more coverage than it has is worse than none at
all**." The incident is a record that was *absent*, not one that overstated. The first
clause fits literally and the standing instruction was default-to-tally, so I would not
overturn this — but the fit is partial, and I note it because the tally's own framing
("the dataset row survives and the reading that makes it usable dies") is arguably a
distinct class. Acceptable as recorded.

### (C) TALLY TARGETING — 10 of 11 correct; one mechanical defect; the two 46 tallies are NOT inflation

I read each target lesson's full archive text before judging, and each new tally against it.

| tally | target | verdict |
|---|---|---|
| 877-revise-repo-path | 3 | correct — fixtures shared the code's blind spot, which is 3's literal text |
| 1006-answer-quality-ceremony | 8 | correct — instrument fixed between measurement and decision |
| perf-log-orphaned-narratives | 33 | acceptable (see NIT B2) |
| 1031-s1-do-not-merge (test composition) | 46 | correct |
| the fold's own scheduled task | 46 | correct target, **wrong ordinal — see C1** |
| 1031-s1-do-not-merge (config comment) | 47 | correct — "a comment that claims a property the code does not enforce" is verbatim |
| 1032-exam-authored-blind | 156 | correct, but broadens the class — see C3 |
| 877-bill-splitter-parked-honest | 171 | correct |
| handoff-queue-continuity | 194 | correct |
| 1005-grading-differently-wrong | 222 | **correct, and better than 8** — see below |
| 1031-s1-do-not-merge (reviewer stake) | 265 | correct |
| 1050-gate-that-measured-nothing | 293 | correct — explicitly the false-negative mirror of 293's rule |

**On 222 vs 8 (the author's flagged call): the author is right, and 222 is the tighter
fit, not merely an acceptable one.** 222's headline reads "…prove it can produce PASS on
a known-good subject **under production conditions**…" The 1005 incident is precisely
that: the 14B juror's "0-of-9 non-determinism" was produced by an unconstrained probe and
became 8-of-9 on the production grammar path. The failure was a verdict about an
instrument, measured off-production. 8 (thermal/confound hygiene, "fixing the instrument
once") would have been a loose fit, and 8 already absorbed the 1006 tally in this same
fold — putting both there would have blurred two different instrument failures into one
line.

**On the two tallies on lesson 46: not inflation.** I checked this specifically because
the author states the opposing standard himself, on lesson 171 in this same change:
*"Recorded as ONE recurrence covering both faces observed that day … splitting one
engagement's symptoms would inflate the tally the third-instance rule keys on."* Applying
that standard to 46:

- Tally 1 (from `1031-s1-do-not-merge`, commit `a89783f8`) — a regression lock that
  composed two ruler functions directly instead of the way production composes them.
- Tally 2 (from the fold session itself, commit `2c6d403b`) — a scheduled task that
  registered, reported `State=Ready`, and could not execute because its action invoked
  `pwsh` from `C:\Program Files\WindowsApps`, whose ACLs deny the SYSTEM principal
  (win32 1920).

Different engagements, different days' work, different subjects, discovered eight minutes
and one commit apart, and the second was found by the fold session test-firing something —
not by re-reading the first. 171's rule forbids splitting one engagement's symptoms across
multiple tallies **on the same lesson**; that is not what happened. Both are genuine
instances of 46's class ("a green suite proves the mechanism, never that the running system
invokes it" — a task reporting Ready is exactly that shape). I would have recorded both too.

For the same reason I do not fault `1031-s1-do-not-merge` producing three tallies (46, 47,
265): one incident-rich engagement instantiating three different classes is not
double-counting, and each tally lands on a class the others do not cover.

---

**[FINDING] C1 — Lesson 46's two new tallies both narrate themselves as the "SEVENTH
instance"; the second is the eighth.**

Verified by walking the ordinal chain in the archive text in order:

```
recurrence #1 (instance 2)  2026-07-07  narrated: (none)
recurrence #2 (instance 3)  2026-07-07  narrated: THIRD INSTANCE
[control marker: #762 load-line canary]
recurrence #3 (instance 4)  2026-07-08  narrated: FOURTH instance
recurrence #4 (instance 5)  2026-07-08  narrated: FIFTH instance
recurrence #5 (instance 6)  2026-07-11  narrated: sixth recorded instance
recurrence #6 (instance 7)  2026-07-22  narrated: SEVENTH instance   <- a89783f8, correct
recurrence #7 (instance 8)  2026-07-22  narrated: SEVENTH instance   <- 2c6d403b, WRONG
```

The `↺7` index flag is right and the marker count is right — only the prose ordinal is
wrong, so no arithmetic is affected. But 46 is a lesson whose recurrences are narrated by
ordinal precisely so a reader can audit the chain without counting, and two consecutive
SEVENTHs break exactly that.

**Fix:** in `2c6d403b`'s tally on 46, change "SEVENTH instance, in scheduled-task form"
to "EIGHTH instance, in scheduled-task form".

**Side benefit worth recording:** this ordinal chain independently corroborates the
author's lesson-46 off-by-one fix by a method he did not use. The chain runs unbroken to
"sixth recorded instance" at the pre-existing 2026-07-11 marker, which means the corpus
itself said 46 stood at six instances before this fold — so the base index line's `↺6`
(implying seven) was over by one, and the archive was the correct authority. The
correction is right, and now double-confirmed.

**[NIT] C3 — The 156 tally broadens the class without broadening the index headline.**
156 reads "When a value becomes **config-driven**, audit every consumer — a half-promoted
**config** is worse than a hardcoded one." The 1032 incident is a `planning_seed`, not
config: a value threaded to eight sub-generations where the eighth kept the bare `goal`.
The generalisation is sound and I would have tallied it here too — but the index line is
the Rule-2 pre-mint search surface, and a future session searching for "a value threaded
to N consumers, one missed" will not match on the word "config". The shipped control
(`test_every_post_seed_consumer_takes_the_planning_seed_not_the_bare_goal`) is now
attached to a headline that does not describe it. **Fix:** widen 156's index text to name
the general class, e.g. "When a value becomes centrally-sourced (config, a computed seed),
audit every consumer — a half-promoted value is worse than a hardcoded one."

### (D, second half) REPO-WIDE DRIFT — real, pre-existing, and the change did not sweep it

Re-running the reconciliation with a **broadened** marker regex (the corpus uses at least
two dialects: `*(recurred: …)*` and `*(THIRD INSTANCE: …)*`; my first pass wrongly flagged
lesson 64, which uses the second form) gives the honest figure:

**6 index lines drift at HEAD — 45, 52, 72, 196, 214, 237 — every one of them
over-counting, and every one of them already drifting at the merge base `6df70ad5`.**
Lesson 46 was a seventh; this change fixed it. So the change *reduced* repo-wide drift
from 8 to 6 (46 fixed, 64 was my false positive) and introduced none.

```
45:  index ↺1  archive markers 0   (+1)
52:  index ↺4  archive markers 3   (+1)
72:  index ↺2  archive markers 1   (+1)
196: index ↺3  archive markers 0   (+3)
214: index ↺3  archive markers 2   (+1)
237: index ↺1  archive markers 0   (+1)
```

There is also an **under-count** class no marker-based audit can see: lessons **6** and
**162** narrate recurrences in prose ("*It came back on 2026-05-22:*") and carry `↺0`.
Those are real second instances that were never tallied.

**Clean result worth stating:** every `✓ctrl` on the index — all of them, including the
two this change added — is backed by a control named in the archive text. There are zero
false `✓ctrl` flags in the corpus. The flags added here are honest by that test.

---

**[FINDING] D1 — The change diagnosed a mechanically-detectable defect class, fixed the
single instance in front of it, and did not run its own script over the other 299 lines.**

The author wrote a reconciliation check, used it to catch lesson 46's off-by-one, and
reported "**All 11 tally counts now reconcile against the archive programmatically**" —
which is true, and scoped to eleven. The same script over the whole file (thirty seconds)
surfaces six more drifting lines and eight lessons at three-plus instances carrying no
control:

```
52  (~5 instances)   72  (~3)   151 (~4)   170 (~3)
186 (~3)             193 (~3)   195 (~3)   214 (~4)
```

Two of those admit the debt in their own text and have been sitting on it:
- **52**: "…the stale-base-merge shape still has no structural control — only the
  discipline clause — **flagged as an open third-instance obligation at the 2026-07-17
  fold-in**." Five days ago.
- **214**: "**SECOND RECURRENCE — the third instance rule arms**: the next mute-conversion
  in this class must ship a structural control." Its index line already says `↺3`, so by
  the index's own count the third instance has been and gone with no control.

This is lesson 64's class ("fixing a defect where you found it and fixing a defect CLASS
are different acts — the class is closed when every copy is bound to ONE shared fix") and
lesson 296's own corollary ("the author's sweep finds the copies the author remembers"),
both of which this change touches.

**Mitigating, and it is why this is not a blocker:** Rule 5 already owns this work with a
date — the quarterly consolidation pass, next due **2026-10-01**, explicitly "adds missing
recurrence tallies, and verifies every third-instance lesson has its control." That is a
real owner and an observable predicate, so the drift is not an undisposed finding in the
`<deferral_discipline>` sense.

**Fix (cheap, and it is what makes the discovery durable):** the author now has the one
thing the quarterly pass will otherwise have to rebuild from scratch — a working
reconciliation script. Commit it as `tools/doc_hygiene/reconcile_lesson_tallies.py` (or
note it in the fold plan) with the six drifting lines and eight uncontrolled lessons
listed as the pass's worklist. Better still, wire it into
`tests/security/test_doctrine_freshness.py` as a warn-only check now and a gate after the
quarterly cleanup — the same shape lesson 293 (tallied in this very change) prescribes:
measure the false-positive rate before gating.

---

## Summary of findings

| id | severity | title |
|---|---|---|
| A1 | FINDING | Lesson 47 marked `✓ctrl` in the same change that recorded an instance the control does not cover; gap admitted, not disposed |
| B1 | FINDING | Lesson 225's third-instance obligation lives only in lesson 298's text, not on 225 |
| C1 | FINDING | Lesson 46's two new tallies both narrate "SEVENTH instance"; the second is the eighth |
| D1 | FINDING | The reconciliation script was run over 11 lines, not 300; 6 drifting lines and 8 uncontrolled lessons left unlisted |
| A2 | NIT | Lesson 222 carries a live sub-class obligation now buried under a newer tally (no action owed here) |
| A3 | NIT | Lesson 222's control uses a non-standard marker, defeating mechanical Rule-3 audit (pre-existing) |
| B2 | NIT | The 33 tally fits 33's first clause but not its second |
| C3 | NIT | The 156 tally broadens the class without broadening the index headline |

Nothing here is a BLOCKER.

---

## VERDICT: MERGE

The curation is substantively correct, and the two judgments the author flagged as most
contestable both survive independent checking — the one I most expected to overturn
(299, destructive git) is the one the evidence most clearly supports: the archive
contained zero mentions of any destructive git verb before this commit, and the two
named candidate lessons (52, 172) are about branch verification and staging reflexes
respectively. The arithmetic claim is true as stated and verified by my own script; the
lesson-46 off-by-one fix is right and is independently corroborated by the archive's own
ordinal chain, which the author did not use as evidence. Ten of eleven tallies are on the
correct lesson, the two tallies on lesson 46 are two genuinely separate incidents rather
than one fold inflated into two, and every `✓ctrl` in the entire corpus — not just the
ones added here — is backed by a real named control. Rule 6 is satisfied: 296-300 are
contiguous, no gaps, no duplicates, 300 index lines against 300 archive entries.

What holds it back from clean is a consistent pattern rather than any single error: the
change is rigorous *within the eleven lines it touched* and stops at that boundary. A1,
B1 and D1 are three faces of the same habit — an admitted control gap on 47 recorded but
not ticketed, an obligation on 225 written into a different lesson's text, and a
reconciliation script run over 11 of 300 lines while reporting "all reconcile." None of
them makes a landed record false, and Rule 5's quarterly pass (2026-10-01) is a real
owner for the drift, which is why none is a blocker. C1 is a one-word factual error in a
record that is otherwise append-only, so it is worth fixing on this branch before the
merge commit rather than as a later correction.

**Recommended before merge:** C1 (one word). **Recommended soon, on a ticket:** A1's
missing control ticket, B1's marker on lesson 225.

---

## What I checked vs. what I did not

**Checked, with method:**
- Rule 6 / structural integrity — parsed both files at base and HEAD: 300 index lines,
  300 archive entries, no duplicate numbers, no gaps 1..300, no orphans either direction.
- Arithmetic on all 11 touched lessons — `↺n` against archive markers, base and HEAD
  (`scratchpad/rev/cmp.py`), plus lesson 46's ordinal chain walked separately as an
  independent cross-check of the off-by-one fix.
- Repo-wide arithmetic — the same script over all 300 lines, with the marker regex
  broadened after lesson 64 proved my first pass had a false positive.
- Rule 3 on every touched lesson at ≥3 instances (8, 46, 47, 156, 222) — read each
  lesson's **full archive text**, located and quoted the control in each. Did not accept
  the author's claim about 8 and 47; verified both independently.
- Repo-wide Rule 3 — scanned all 300 for ≥3 instances without a control.
- Over-minting — keyword sweeps over the index and the whole archive per new lesson,
  then read the full archive text of every candidate neighbour (52, 172, 14, 48, 163,
  230, 288, 225) rather than judging from index lines.
- Tally targeting — read each target lesson's full text and each new tally against it.
- One deferral predicate spot-checked live: `#1040`, cited in the lesson-33 tally, is a
  real open ticket with a detailed description and `blocked-by: nothing`. That is what
  made lesson 47's *absent* ticket stand out.

**Not checked (out of the assigned scope):**
- `BUILD_JOURNAL.md` — whether the 16 folded entries are faithful to their fragments,
  whether narrative was preserved verbatim, entry form, dates, or ordering.
- The shipped test `shared/tests/test_acceptance_clarify.py` — I confirmed lesson 156's
  control is *named and specific*, but did not open the test file, run it, or verify the
  mutation/toggle-off proofs the commit message claims.
- The gate figure (8779), `docs/TEST_GOVERNANCE.md`, `CLAUDE.md`, and the fold plan's
  execution record. I did not run pytest, per instruction.
- Whether the held-back fragment's hold is correct on the battery-cadence merits, or
  whether `#1058` is adequate — I checked only that 225 carries no trace of it.
- The 6 pre-existing drifting lines were confirmed as *drift*, but I did not adjudicate
  which surface is right in each case (index over-counted, or an archive marker was never
  written) — that is the quarterly pass's job and needs per-lesson history archaeology.
- Vikunja state generally, and whether tickets were opened/closed for this fold.
