# Independent review — journal fold, branch `docs/journal-fold-20260722`

**Reviewer:** independent session (did not author the change).
**Reviewed state:** commit **`a89783f8`** *(docs(journal): fold 16 fragments, mint lessons
296-300, ship lesson 156's third-instance control)*, parent `6df70ad5`.
The author committed mid-review; my earlier analysis was against the staged tree that
became that commit, and every number below was **re-derived against the commit itself**.
**Spec graded against:** `CLAUDE.md` `<journal_discipline>`, `<deferral_discipline>`,
`<testing>`; `LESSONS.md` "Rules of this file" (lines 8–52).

**Two premises in my review brief were wrong and are corrected here** (the brief was written
against a pre-correction state): the control ships **3** tests, not 4, and the doctrine pair
reads **8779**, not 8780. The author caught this miscount themselves before committing and
disclosed it in the commit message. Both surfaces are consistent *and* correct — see §4.

---

## Attack line 1 — CONTENT FIDELITY

**Result: CLEAN. No prose lost, no prose reworded.**

Wrote a paragraph-level differ that, for each of the 16 backup fragments, extracts every
paragraph from the first `### ` header onward, drops only the permitted scaffolding classes,
whitespace-normalises, and requires each remaining paragraph to appear **verbatim** in
`BUILD_JOURNAL.md`; anything not matching exactly was fuzzy-matched against every journal
paragraph to catch rewording.

```
./.venv/Scripts/python.exe <scratchpad>/fidelity.py
```

All 16 returned `OK — every narrative paragraph found verbatim`. **151 narrative paragraphs
checked** (5, 9, 7, 8, 10, 7, 11, 9, 16, 12, 6, 8, 12, 11, 12, 8).

The one flagged mismatch was a false positive of my own filter:
`1022-gate-spec-erosion-20260721.md:15` opens with a bare `Proposed lesson: migrating
doctrine out of a repo being sunset…` (no `**` markers). I read the fragment; it is genuinely
fragment-only scaffolding and became lesson 296. Correctly stripped.

**[NIT] Two folded fragments were never tracked in git.**
- `1003-order-probe-20260721.md` and `1031-s1-shipped-dormant-20260722.md` are in neither
  `HEAD` nor the index — they were untracked working-tree files, now deleted from disk.
- Reproduced: `git ls-tree -r --name-only HEAD docs/journal_fragments/` lists 14 fragments +
  README; the backup dir holds 16.
- Both fragments' prose **did** land verbatim (verified above), so nothing was lost. The point
  is that the safety of this fold rested on a scratchpad backup rather than on git. Worth
  noting the author fixed exactly this exposure for the *held* fragment (see §5), which makes
  its absence for these two an inconsistency rather than an oversight of principle.

---

## Attack line 2 — LESSON CURATION CORRECTNESS

**Result: arithmetic fully correct; no Rule-3 breach; one new index/archive inconsistency.**

I built a cross-check that parses `LESSONS.md`'s *Index of every lesson* section and the
archive volume, counts `(recurred:` and `control:` markers per lesson, and compares them —
run against **both** `HEAD` and the commit so findings could be attributed rather than
blamed. (My first pass used a stricter `\(control:` regex and produced four false positives
on lessons 8/47/156/222, whose controls are recorded as `control:` mid-prose. Corrected
before reporting.)

### Tally arithmetic — all 11 correct

| L | archive `recurred:` | index `↺` | instances | control in archive | `✓ctrl` |
|---|---|---|---|---|---|
| 3 | 1 | ↺1 | 2 | — | — |
| 8 | 5 | ↺5 | 6 | yes (#709) | ✓ |
| 33 | 1 | ↺1 | 2 | — | — |
| 46 | 6 | ↺6 | 7 | yes | ✓ |
| 47 | 3 | ↺3 | 4 | yes | ✓ |
| 156 | 2 | ↺2 | **3** | yes | ✓ |
| 171 | 1 | ↺1 | 2 | — | — |
| 194 | 1 | ↺1 | 2 | — | — |
| 222 | 7 | ↺7 | 8 | (pre-existing gap) | ✓ |
| 265 | 1 | ↺1 | 2 | — | — |
| 293 | 1 | ↺1 | 2 | yes | (pre-existing gap) |

Every `↺` reconciles against the archive. **Rule 3 is satisfied for every lesson this change
touched** — 156 (the third instance) ships a control and is marked; 8, 46, 47 all carry real
controls.

### The fold FIXED three pre-existing defects (verified, not claimed)

- **L46 off-by-one corrected.** At `HEAD` the index read `↺6` against 5 archive markers. The
  fold added a tally and landed at `↺6`/6 — i.e. it corrected rather than propagated.
- **L8 and L47 `✓ctrl` restored.** Both carried real third-instance controls in archive text
  (`scripts/benchmark_kv_cache_sweep.py` #709; `tests/security/test_dependency_truth.py`
  #810) while their index lines lacked the marker — reading as Rule-3 debt that did not
  exist. I read both archive texts and confirm the controls are genuinely described.

### Mint-vs-tally: all five mints defensible; the contested one is *correctly* argued

The standing instruction was DEFAULT TO TALLY, so I attacked the mints hardest.

**Lesson 299 is the interesting case, and the author got it right against its own fragment's
advice.** `1045-destructive-verb-20260722.md:39` explicitly instructs: *"this is no longer a
mint-or-tally question. It is a tally against the existing never-destructive-git rule."* The
author minted anyway and argued why in both the lesson text and the execution record. **I
independently verified the argument and it holds:**

```
grep -oniE "checkout -- |reset --hard|force-push|push --force|branch -D|destructive (git|command|verb)" \
  docs/archive/lessons/LESSONS_ARCHIVE.md
```
Every hit is on **line 613 — lesson 299 itself**. No prior numbered lesson covers the class.
The git-adjacent lessons are different classes: 52 (worktree branch-switch), 172 (`git add
-A`), 35 (merge landing), 89 (worktree writes). The "existing rule" the fragment refers to
lives in `CLAUDE.md <git_discipline>`, which is doctrine, not a numbered lesson — there was
nothing to tally against. Rule 2 ("search before you mint") is satisfied, and the disposition
was *argued, not asserted*.

296, 297, 298, 300 are each a genuinely distinct class with `cf.` cross-references to their
near-neighbours. **All five claimed controls exist on disk** — I checked each rather than
trusting the text:

| Lesson | Claimed control | Verified |
|---|---|---|
| 296 | `test_gate_section_list_complete_on_every_surface` | `tests/security/test_doctrine_freshness.py:239` |
| 297 | `CLAUDE.md <authority_first>` | `CLAUDE.md:86` |
| 298 | `docs/runbooks/battery_cadence_and_targeted_runs.md` | present, 11 101 bytes |
| 299 | `~/.claude/hooks/block_destructive_git.py` | present, executable |
| 300 | handoff template `## Work queue` REQUIRED | `docs/governance/handoff-brief-template.md:7,84` |

**[FINDING] Lesson 298 is the one new inconsistency: control in archive, no `✓ctrl` on the index.**
- `docs/archive/lessons/LESSONS_ARCHIVE.md:611` carries a `*(control: …)*` marker for 298;
  `LESSONS.md`'s index line for 298 has no `✓ctrl`, unlike 296/297/299/300.
- Reproduced by the sweep above: `REGRESSIONS INTRODUCED: {298: 'CTRLDIS'}` — the only row
  this change added to the discrepancy set.
- It may well be deliberate — 298's control is a *runbook*, and its own text says the
  deny-by-default version "remains lesson 225's unbuilt third-instance control." If so the
  reasoning is invisible, and the index is the pre-mint search surface where it matters.
- **Fix:** either add `✓ctrl` for consistency, or add a half-marker/note on the index line
  recording that the control is documentary and the structural one is tracked at #1058.

**[NIT] Lesson 297 records a four-instance class as a fresh mint with no `↺` flag.**
- 297's own text opens *"Four instances in a single overnight session"* and `CLAUDE.md:86`
  labels `<authority_first>` a *"Rule-3 control; 2026-07-22 four-instance class."* The index
  line shows no `↺`, so the pre-mint search surface reads it as a single-instance lesson.
- **On reflection this is defensible and I am not asking for a change.** Rule 3 is what
  matters and the control shipped in the same change, exactly as the rule demands;
  `CLAUDE.md:291` explicitly directed this mint (*"<authority_first> mints next"*); and four
  sub-instances of one session are not four dated recurrences, so `↺3` would be its own kind
  of lie. Decisively, it is **consistent with the author's own precedent in this same fold** —
  lesson 171's tally text argues that *"splitting one engagement's symptoms would inflate the
  tally the third-instance rule keys on."* The same reasoning applied to 297 is principled,
  not sloppy.
- **Fix (optional, cosmetic):** note "(four instances in one session)" on the index line so a
  future curator sees the weight without inventing tallies.

**[FINDING] Lesson 47's fourth-instance text names an uncovered gap, and nothing was filed for it.**
- The new 2026-07-22 tally on 47 states: *"the control shipped at the third instance
  (`tests/security/test_dependency_truth.py`) covers MANIFESTS, not ceremony-read config
  comments — that gap is this instance's finding."* That is an explicit, self-declared
  finding with no FIXED / DEFERRED / REJECTED disposition anywhere.
- Reproduced: searched the board for a matching ticket —
  `search_tasks(project_id=3, query="ceremony config comment")` → 0 results;
  `query="default.toml comment"` → 0 results.
- This is asymmetric rigor: lesson 225's gap got a header, a tracked fragment, a ticket, a
  `blocked-by:` predicate and a definition of done (§5). Lesson 47's gap got a sentence.
  A config comment read *at a go-live ceremony* is the surface `<security_by_design>` §13
  calls an LA-present irreversible event, so it is not a small class.
- **Fix:** file a ticket for a ceremony-read config-comment control (the natural shape: extend
  the `test_dependency_truth.py` family to assert `default.toml` flag comments against the
  behaviour their branch actually ships), and cite it in 47's tally text.

**Pre-existing debt (NOT this change):** 21 index rows still disagree with the archive,
including 8 lessons at ↺≥2 with no `✓ctrl` (52, 72, 149, 151, 170, 186, 193, 195, 196, 214).
The fold neither caused nor worsened these. `LESSONS.md` Rule 5 schedules exactly this
reconciliation for the quarterly pass (next due 2026-10-01); worth pointing that pass at the
programmatic cross-check rather than a manual read.

---

## Attack line 3 — THE CONTROL (verified by execution)

**Result: the control is real and works for the shape it targets. Its documented claim is
broader than its demonstrated reach.**

### It passes, and it goes RED against the real defect

```
./.venv/Scripts/python.exe -m pytest shared/tests/test_acceptance_clarify.py -q
→ 16 passed in 0.44s
```

Backed up `shared/fleet/acceptance.py` **by file copy** (sha256
`62bd29836db99118597c27628611f8f4ef9bbfdf83c3aadd704262573547838b`), reintroduced the #1032
defect at line 3441–3442 (`planning_seed` → `goal` in the `author_and_qa_job_oracle(` call),
and re-ran:

```
→ 3 failed, 13 passed
FAILED test_every_post_seed_consumer_takes_the_planning_seed_not_the_bare_goal
FAILED test_the_job_oracle_author_is_reached_by_the_seed_not_the_goal
FAILED test_requirements_reach_the_MULTI_task_job_oracle_author   (the pre-existing #1032 lock)
```

Restored **by file copy**, never by a git verb; digest re-verified identical and
`git status --short shared/fleet/acceptance.py` empty. Both new locks have teeth.

### The allowlist is correct — verified in source, not from the comment

`_LEGITIMATE_BARE_GOAL_CONSUMERS = {"rule_spec"}` is right. The clean-goal contract is stated
in two independent places:
- `shared/fleet/acceptance.py:3207-3210` at the mint: *"``spec.goal`` stays the CLEAN goal
  (below) so the preview/report headers never carry the block; the seed only shapes what gets
  built."*
- `shared/fleet/acceptance.py:3245` at the call site: *"rule_spec keeps spec.goal the CLEAN
  goal so the preview header never shows the block"*, with `rule_spec(goal, …)` on line 3258.

### [FINDING] Demonstrated blind spots — the control matches bare `ast.Name` only

I injected four plausible new consumers after the seed mint and ran the enumerating test on
each, restoring and digest-verifying after every variant:

| Injected consumer | Control verdict |
|---|---|
| `brief = goal` then `f(brief, …)` — intermediate variable | **MISSED (green)** |
| `f(spec.goal, …)` — attribute access | **MISSED (green)** |
| `f(f"{goal}", …)` — f-string wrap | **MISSED (green)** |
| `f(**{'g': goal})` — kwargs unpack | **MISSED (green)** |
| `f(goal, …)` — bare name *(positive control)* | **CAUGHT (red)** |

`restore digest match: True`

These are not theoretical: `context = goal` for readability is an ordinary way to write the
ninth call site, and it defeats the check silently. The test's own docstring claims it
"re-derives the consumer set from the source on every run, so a **NINTH call site added
tomorrow is caught the day it lands**" — unqualified, and true only for the literal
`f(goal)` / `f(x=goal)` shape.

That overclaim is *lesson 47's own class* — a comment claiming a property the code does not
enforce — landing in the same commit that records lesson 47's fourth instance. Note the
contrast with lesson 299's control, which documents its honest limit explicitly ("a
determined evasion — a heredoc body line, an env-prefixed invocation — still slips past").

- **Fix:** add an honest-limit note to the comment block naming the demonstrated evasions
  (Name-only matching: intermediate variable, attribute, f-string, unpack), and soften the
  docstring's "is caught" to "is caught when it passes `goal` directly." Optionally widen the
  matcher to flag any post-seed call whose arguments *transitively* reference `goal` within
  the function body — a local assignment-tracking pass would close variant A, the most likely
  of the four.

---

## Attack line 4 — DOCTRINE PAIR

**Result: the pair agrees AND the figure is correct against reality.**

- `CLAUDE.md:288` — `Standing gate: 8779 / 0 failed / 0 skipped / 125 deselected`
- `docs/TEST_GOVERNANCE.md:30` — `LIVE_GATE_BASELINE: 8779 passed / 0 failed / 0 skipped / 125 deselected`

The freshness gate only compares the two docs to each other, so I checked the number against
the suite itself:

```
./.venv/Scripts/python.exe -m pytest shared/ services/ launcher/ tests/integration/ \
  tests/security/ -m "not hardware and not winui and not slow" --collect-only -q
→ 8779/8904 tests collected (125 deselected) in 17.02s
```

**8779 and 125 both match reality.** The arithmetic also checks out: prior baseline 8776, and
the commit adds exactly **3** test functions —
`test_every_post_seed_consumer_takes_the_planning_seed_not_the_bare_goal`,
`test_the_job_oracle_author_is_reached_by_the_seed_not_the_goal`,
`test_the_control_can_see_a_planted_violation` — so 8776 + 3 = 8779.

Worth crediting explicitly since it is the failure mode the doctrine warns about: the author
initially wrote **+4 / 8780** into both surfaces from a miscount, the measurement corrected
it, and the commit message says so in the open. A wrong-but-consistent pair would have passed
the gate; it was caught by measuring, not by the gate.

---

## Attack line 5 — THE DEFERRAL

**Result: legitimate. This is the strongest-executed part of the change.**

`989-ab-day-cadence-20260721.md` is the one fragment not folded.

- **Observable predicate — yes, genuinely.** The fragment's header names *"a sandbox-freshness
  precondition in `tools/dispatch_harness/` that refuses a card whose sandbox git history
  carries `agent:` commits, shipped with its regression lock and a toggle-off proof."* That
  is a path plus a testable behaviour — `<deferral_discipline>` asks for "a #ticket, a date,
  a `symbol`, a path" and this names two of the four. Not "follow-up" in a costume.
- **The reason is substantive, not momentum.** Shipping the control changes the battery
  *instrument* and would land inside another measurement's attribution window, violating
  one-change-per-run (`docs/runbooks/battery_cadence_and_targeted_runs.md`). Holding the fold
  is the conservative choice, and it costs the author the tidiness of a complete fold — the
  opposite of the "box feels closed" failure the doctrine warns about.
- **Durable record — verified on the board.** `get_task(1058)` returns an open ticket:
  *"Lesson 225 third-instance control: sandbox-freshness precondition in the battery harness
  (deny-by-default, recorded opt-out)"*, project 3, `done: false`. Its description carries the
  measured gap (the nightly wrapper owns the archive+init at ~line 662; targeted runs bypass
  it), an explicit `blocked-by:` line, a do-not-stack list (#1049, #1036, #1048, #1043,
  #1044, #969), and a definition of done that includes folding the fragment and resuming
  numbering at 301.
- **Tracked in git — yes, and this was actively fixed.** `989-ab-day-cadence-20260721.md`
  is `A` (added) in `a89783f8`. It was previously untracked, i.e. unrecoverable; the commit
  message calls this out. Good catch by the author.

**[NIT] The fragment header points at "the lesson-225 control ticket" without the number.**
- `docs/journal_fragments/989-ab-day-cadence-20260721.md:21` says *"Tracked on the board — see
  the lesson-225 control ticket"* — no `#1058`. The fold plan and commit message both name
  #1058, so it is recoverable, but the fragment is the surface a future folder reads first.
- **Fix:** write `#1058` into that line.

**[FINDING] Lesson 225's index line gives a future curator no signal that it is at its third instance.**
- `LESSONS.md:500` still reads `225. … · ↺1` (2 instances, no control), while lesson 298's
  archive text asserts 225's third-instance control "remains unbuilt." Rule 3 binds "the
  change that records the third tally," and this change deliberately does not record it — so
  this is *literally* compliant and I am not calling it a breach.
- But `LESSONS.md`'s index is explicitly "the pre-mint search surface." A session searching it
  next week sees ↺1 and no hint that a third instance is sitting in a held fragment.
- **Fix:** add a forward-reference to 225's index line — e.g. `· ↺1 (3rd instance held, #1058)`
  — which costs nothing and removes the dependence on someone finding the fragment.

---

## Attack line 6 — SELF-CONSISTENCY OF THE EXECUTION RECORD

**Result: every claim I could test is TRUE.** This is the attack line I expected to find
something on, and did not.

| Claim in the execution record | Verdict | How I checked |
|---|---|---|
| 1045 minted (299) not tallied; no numbered lesson covers the class | **TRUE** | Independent regex sweep of the full archive — every destructive-git hit is on line 613 (lesson 299 itself) |
| 1005 tallied on 222, not 8 | **TRUE** | 222 carries a new `2026-07-22` tally; 8's new tally is the #1006 harness one |
| perf-log tallied on 33, not minted | **TRUE** | 33 carries a new `2026-07-22` tally |
| Lesson 8's index lacked `✓ctrl` though archive carries #709 control | **TRUE** | Archive: `*(third instance — control: … scripts/benchmark_kv_cache_sweep.py …; #709.)*`; index at `HEAD` had no `✓ctrl` |
| Lesson 47's index lacked `✓ctrl` though 3rd instance shipped `test_dependency_truth.py` | **TRUE** | Archive 47's 2026-07-11 tally: `control: the three-property tests/security/test_dependency_truth.py …` |
| L46 off-by-one found and corrected rather than propagated | **TRUE** | `HEAD` = arch 5 / idx ↺6; commit = arch 6 / idx ↺6 |
| Both 877 fragments recorded as ONE recurrence on 171 | **TRUE** | 171 has exactly 1 new tally, whose text says so explicitly and tickets the structural answer at #1025 |
| 156's control mutation-proven red with byte-exact restore | **TRUE** | Independently reproduced — see §3 |
| Gate 8779, prior 8776, +3 | **TRUE** | Collection = 8779/125; 3 test functions added |

The record also volunteers information against its own interest (the +4 miscount, the
pre-existing L46 defect it could have silently inherited), which is the opposite of the
self-congratulatory failure mode the brief asked me to look for.

---

## Attack line 7 (not in the brief) — DOCTRINE STALENESS

**[BLOCKER] `CLAUDE.md`'s `<status_snapshot>` journal bullet is false in every clause, in the
very commit that made it false.**

`CLAUDE.md:291` (committed state, unchanged by `a89783f8` — the commit touches only the gate
figure on line 288):

```
- Journal: **12 fragments AWAITING FOLD; fold DEFERRED** — one proposes lesson **225's THIRD
  instance**, whose Rule-3 control (a sandbox-freshness precondition check) would change the
  battery harness mid-A/B. All 12 dispositioned in `docs/governance/fold-plan-2026-07-22.md`,
  whose addendum names two more possible third instances. Lessons at 295; <authority_first>
  mints next. LOUD DEBT: lesson-14 control → #929.
```

Every factual clause is now wrong:

| Claim | Reality after `a89783f8` |
|---|---|
| "12 fragments AWAITING FOLD" | 16 folded, **1** remains |
| "fold DEFERRED" | the fold **EXECUTED** |
| "All 12 dispositioned" | 17 dispositioned |
| "Lessons at 295" | lessons at **300** |
| "`<authority_first>` mints next" | it **minted** — lesson 297 |

Reproduced: `git show a89783f8:CLAUDE.md | sed -n '291p'` and
`git diff 6df70ad5 a89783f8 -- CLAUDE.md` (a single-line change, the gate figure only).

Why this is a blocker rather than a nit:

1. `<status_snapshot>`'s own contract says *"A shipped arc is history the moment it merges…
   **Replace, do not append**"* and `<maintenance>` says volatile state lives **only** here,
   *"refreshed at merge clusters."* This is a merge cluster; the bullet is precisely the
   volatile state that just changed.
2. `<session_start_protocol>` makes this file the **first** grounding action of every session.
   A successor grounding tomorrow reads "12 fragments awaiting fold, lessons at 295" and will
   either redo the fold or mint 296 on top of the author's 296. The `<live_state_pointers>`
   caveat ("never trust pinned counts… if its date is old") does not help — the snapshot is
   dated **2026-07-22**, today, so it reads as fresh.
3. The freshness gate cannot catch it: `test_doctrine_freshness` pins the *gate figure* pair,
   not this bullet. This is the same "wrong-but-consistent pair passes" blind spot the
   snapshot warns about, one bullet lower.

The commit is otherwise scrupulous about durability — which makes this the one place the
change fails its own standard.

**Fix (small, and the change is not safe to merge without it):** replace the bullet, e.g.

```
- Journal: fold EXECUTED 2026-07-22 (`a89783f8`) — 16 of 17 fragments folded, lessons
  **296–300** minted, 11 tallies recorded. **1 fragment HELD**:
  `989-ab-day-cadence-20260721.md`, lesson **225's third instance**, blocked on its
  battery-harness control → **#1058**; numbering resumes at **301**. Lessons at **300**.
  LOUD DEBT: lesson-14 control → #929.
```

---

## ROUND 2 — re-review after `2c6d403b`, `4a57e237`, `bdd3346f`

Three commits landed after my round-1 pass. Re-verified against the current tree.

**[RESOLVED] The round-1 BLOCKER is fixed.** `4a57e237` replaces both stale
`<status_snapshot>` bullets. The journal line now reads *"FOLD DONE 2026-07-22 — 16 of 17
fragments folded, lessons 296–300 minted + 12 tallies. ONE fragment HELD…"*. Verified:
`git show 4a57e237 -- CLAUDE.md`. This no longer blocks the merge.

**[NOT A DEFECT] The two lesson-46 tallies dated 2026-07-22 are NOT double-counting.**
This was the lead's specific question, and the answer is no — they are two genuinely distinct
incidents of one class, verified by reading both tally texts in full:
- **Tally A (#1031/#1041):** a pytest lock for the ruler-ordering dependency composed the two
  ruler functions *directly in the test* instead of driving the real planner, so it stayed
  green when the call site was reversed. Subject: a test file on the S1 branch.
- **Tally B (#1057):** a one-shot Scheduled Task registered cleanly, reported `State=Ready`,
  and was structurally unable to run — its action invoked `pwsh` under
  `C:\Program Files\WindowsApps`, whose ACLs deny the SYSTEM principal, dying win32 1920.
  Subject: a Windows task registration.

Different subjects, different tickets, different failure mechanisms. Both are honestly lesson
46 ("a green suite proves the mechanism, never that the running system invokes it"). Recording
them as two tallies is correct; collapsing them would have *under*-counted.

**[FINDING] But both tallies label themselves "SEVENTH instance" — one of them is the eighth.**
- Counting the archive's ordinals in order: original (1), `#743` (2), `#759` "THIRD" (3),
  `#758` "FOURTH" (4), `#744` "FIFTH" (5), `#801` "the sixth recorded instance" (6),
  `#1031/#1041` "SEVENTH" (7), `#1057` "SEVENTH instance, in scheduled-task form" — **(8)**.
- Archive now carries 7 `*(recurred:` markers, so original + 7 = 8 instances. The `#1057`
  tally is the **eighth**.
- This matters because the ordinal written into the tally text is what a future curator reads
  to decide whether Rule 3 has bitten; two lessons labelled "seventh" makes the series
  unauditable by reading.
- **Fix:** change `#1057`'s "SEVENTH instance, in scheduled-task form" to "EIGHTH".

### [FINDING — highest value in this review] A THIRD surface is drifting, and the new reconciler is blind to it

The lead asked me to check whether the tally drift extends beyond the lines they touched. It
does, on an axis nobody's tooling covers.

`LESSONS.md` carries **two** full-text copies for 32 lessons: the **Canon-32 residency tier**
(`LESSONS.md:203`, "full text") and the archive volume. I compared recurrence markers across
all three surfaces:

```
./.venv/Scripts/python.exe -c "<canon-32 vs archive vs index sweep>"
→ Canon-32 lessons carrying full text: 32; STALE against archive: 7
```

| Lesson | Canon-32 | Archive | Index |
|---|---|---|---|
| 3 | 0 | **1** | 1 |
| 8 | 4 | **5** | 5 |
| 30 | 0 | **1** | 1 |
| 46 | 5 | **7** | 7 |
| 217 | 0 | **1** | 1 |
| 221 | 3 | **4** | 4 |
| 222 | 4 | **7** | 7 |

**This fold made 4 of the 7 worse** — lessons 3, 8, 46 and 222 all received tallies today that
landed in the archive and the index but never reached their Canon-32 copy. Lesson 46's hot
copy shows 5 recurrences against the archive's 7; lesson 222's shows 4 against 7.

**It is a doctrine defect, not carelessness.** Rule 2 (`LESSONS.md:14-20`) names exactly two
write targets — append the tally "to that lesson's full text **in the archive volume**" and
"bump the `↺` flag on its index line here." Rule 7 independently establishes that Canon-32
also carries full text. So a curator following Rule 2 **exactly and correctly** leaves
Canon-32 stale every time. The procedure structurally cannot keep the third surface in sync.

**The new #1059 control inherits the same blind spot.**
`tools/doc_hygiene/check_lesson_tallies.py:48` defines `INDEX_HEADING = "## Index of every
lesson"` and compares that section against the archive — full stop. Running it:

```
./.venv/Scripts/python.exe tools/doc_hygiene/check_lesson_tallies.py
→ index lines scanned: 300   archive full texts: 300
→ 7 index line(s) disagree with the archive: 45, 52, 64, 72, 196, 214, 237
```

Useful and correct as far as it goes (it independently confirms my round-1 pre-existing-debt
finding). But it reports **zero** of the seven Canon-32 discrepancies, because it never reads
that section. A drift-checker that covers two of three mirrors will now be trusted as though
it covers all of them.

**Why this is worth more than the rest of the review:** the inverted reliability. Canon-32 is
the *hot* tier — the copy described as earning "permanent hot residency," the one a session
reads first — while the accurate copy is "one grep away." The stale text is the one most
likely to be read. This is lesson 149's class (a hand-copied mirror drifts in silence; guard
it with a gate test, not vigilance) and lesson 230's (a truth with several copies, only one
updated), currently recurring inside the very file that records them.

**Fix (recommend before reporting the work done, not necessarily before merge):**
1. Extend `check_lesson_tallies.py` to parse the Canon-32 section as a third surface and
   fail on any lesson whose three copies disagree; wire it into the doctrine-freshness gate so
   it has teeth rather than being a hand-run tool.
2. Amend Rule 2 to name all three write targets, so the SOP stops manufacturing this drift.
3. Backfill the 7 stale Canon-32 texts (a mechanical copy from the archive).

---

## Disposition obligation (for the author, not me)

This pass returned findings, so `<deferral_discipline>` binds: it needs a record at
`docs/reviews/journal-fold-20260722-disposition-2026-07-22.md` carrying a fenced
` ```disposition ` block, pipe-delimited `<finding> | <status> | <evidence-or-predicate>`,
run through `scripts/verify_disposition.py` before the work is reported done. `FIXED` needs a
commit-ish token; `DEFERRED` needs both a `#NNN` and an observable `blocked-by:`; `REJECTED`
needs an argued reason. I am deliberately **not** filling in the statuses — author ≠ verifier
runs both ways, and the dispositions are the author's calls. The finding IDs to disposition:

```
canon32-full-text-drift-7-of-32        | ? | (FINDING-high, Round 2)
lesson-46-1057-tally-ordinal-wrong     | ? | (FINDING, Round 2)
stale-status-snapshot-journal-bullet   | FIXED | 4a57e237 (verified round 2)
lesson-47-fourth-instance-gap-unfiled  | ? | (FINDING, §2)
control-name-only-blind-spots          | ? | (FINDING, §3)
lesson-298-missing-ctrl-marker         | ? | (FINDING, §2)
lesson-225-index-no-third-instance-ref | ? | (FINDING, §5)
fragment-header-missing-1058           | ? | (NIT, §5)
untracked-fragments-1003-and-s1        | ? | (NIT, §1)
lesson-297-no-multi-instance-note      | ? | (NIT, §2 — REJECTED is a reasonable call here)
```

---

## VERDICT

**VERDICT (round 1): DO-NOT-MERGE** — pending one small, mechanical fix.
**VERDICT (round 2, final): MERGE** — the blocker was fixed in `4a57e237`; the remaining
findings are follow-ups, not merge gates. Justification after the round-1 text below.

This is a high-quality change and the finding that blocks it is a one-line edit, not a design
problem. Content fidelity is perfect across 151 narrative paragraphs; all 11 recurrence
tallies reconcile arithmetically against the archive; every claimed control exists on disk;
the lesson-156 control is genuinely mutation-proven red and restored byte-exact; the gate
figure is correct against the suite itself rather than merely self-consistent; the deferral is
the best-executed part of the change, with a real ticket, an observable predicate and a
definition of done; and every claim in the execution record that I could test is true,
including several the author volunteered against their own interest. The mint I expected to be
an over-mint (299, against its own fragment's "tally" instruction) survives an independent
archive sweep. But `CLAUDE.md`'s `<status_snapshot>` still tells the next session that the
fold has not happened, that lessons are at 295, and that `<authority_first>` mints next — in
the commit that folded 16 fragments and minted through 300. That surface is the first thing
every session reads, the doctrine explicitly assigns it this exact refresh duty at merge
clusters, and no gate can catch it. Fix that bullet and this merges. The three substantive
non-blocking findings — lesson 47's undisposed fourth-instance gap, the control's
demonstrated Name-only blind spot versus its unqualified docstring claim, and lesson 298's
missing `✓ctrl` — should be dispositioned but need not gate the merge.

**Round-2 justification.** `4a57e237` replaced both stale snapshot bullets, which was the only
thing I was holding the merge for; I verified it rather than taking it on report. Nothing found
since rises to a merge gate: the lesson-46 double-tally the lead flagged as their own worst
fear is *not* inflation (two distinct incidents, verified by reading both texts), the ordinal
mislabel is a one-word edit, and the Canon-32 drift is a pre-existing structural gap that this
fold worsened by four rows but did not create. That last one is the most valuable finding in
the review and should be ticketed with an observable predicate before this work is reported
done — but it is a defect in the curation SOP and its tooling, not in the fold, and holding a
correct fold hostage to it would be the wrong trade. Merge, then fix the SOP.

### What I drove

- **Content fidelity:** paragraph-level differ over all 16 backup fragments vs
  `BUILD_JOURNAL.md`; 151 paragraphs; fuzzy-match fallback for rewording; read
  `1022-gate-spec-erosion` in full to adjudicate the one flag.
- **Lesson curation:** programmatic index-vs-archive cross-check of **all 300 lessons**, run
  against both `HEAD` and the commit to separate introduced defects from inherited debt;
  corrected my own regex after it produced four false positives; read the full archive text of
  lessons 8, 47, 156, 225, 296–300 and index lines for 52, 172; independent archive-wide grep
  to test the 299 mint justification; existence-checked all five claimed controls on disk.
- **The control:** ran the suite (16 passed); reintroduced the #1032 defect and confirmed 3
  tests red; restored by file copy with sha256 verified byte-exact and `git status` clean;
  **drove four additional mutation variants** to demonstrate blind spots, each restored and
  digest-verified; read `acceptance.py:3207-3258` to verify the `rule_spec` allowlist.
- **Doctrine pair:** read both surfaces; counted added test functions from the commit diff;
  ran `--collect-only` over the real gate selection to check 8779/125 against reality.
- **Deferral:** read the held fragment and its header; `get_task(1058)`; confirmed the
  fragment is staged `A` in the commit; two board searches for a lesson-47 gap ticket.
- **Self-consistency:** verified all nine execution-record claims individually.

### What I did NOT examine

- **The full gate pass/skip counts.** I launched a full run and **killed it at ~84% at the
  lead's request** to avoid stacking two five-directory sweeps (standing project rule). So I
  verified test *collection* (8779/125) against reality but did **not** independently confirm
  0 failed / 0 skipped — that measurement is the author's, and the standing rule requires a
  re-measure on **merged main** after the merge regardless.
  *(Record correction: the run was launched with `./.venv/Scripts/python.exe`, not the system
  python — confirmed by the kill record and by the run reaching 84% rather than dying at
  collection with exit 4. The stacking objection was valid; the interpreter diagnosis was not.)*
- **Prose quality/judgment of the 16 journal entries** — I verified they were transported
  faithfully, not that each is well-written or that its lesson assignment is the most apt
  reading. Several tally targets (e.g. 1005 → 222 vs 8) are judgment calls where I confirmed
  the author's reasoning is coherent rather than independently re-deriving the best answer.
- **The 21 rows of pre-existing index/archive debt** — enumerated and attributed as
  not-this-change, but not individually adjudicated.
- **`BUILD_JOURNAL.md` entry ordering, heading format, and `**Next:**` conformance** beyond
  what the fidelity differ touched.
- **The four ignored paths** (`branding/`, `scripts/benchmark_coresident.py`,
  `scripts/capture_one.ps1`, `scripts/verify_community_scrub.py`) — other sessions' in-flight
  work, excluded per the brief.
- **`docs/TEST_GOVERNANCE.md` beyond §1's baseline line.**
