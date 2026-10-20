# THE ROADMAP
**Last refresh (2026-10-20)**. Every number below was checked on disk, not taken
from a ticket.

> **A date bump is a claim, so this one says exactly what it re-measured.** The 2026-10-20
> refresh ran `scripts/verify_roadmap.py` against the live board: **21 rows checked, 0 stale,
> 0 missing, 1 needs-the-operator, 0 deliberately unticketed.** Every cited ticket exists and
> is still OPEN.
>
> **What this refresh did NOT do:** it did not re-verify the prose claims inside each row, and it
> did not re-rank anything. The order below is the one the 2026-09-16 refresh left; ranking is a
> judgement and it stays the operator's.
>
> **Why the date moved at all.** The 2026-10-20 merge of the case-4 measurement (#1764, the
> delegated non-administrator row of NEP-0005 Q2) advanced `main` sixteen days past the
> 2026-10-04 stamp, and the post-merge standing gate failed on exactly this test while the
> branch had passed it. Same mechanism as the 2026-10-04 and 2026-09-16 refreshes: re-read,
> then stamp; never stamp alone. This block REPLACES the previous one; the 2026-10-04 narrative
> is in git history.

> **This file is THE ORDER.** `CLAUDE.md`'s `<live_state_pointers>` names it, so a session
> reads the ranking here instead of re-deriving one from whatever it happens to open first.
> Vikunja stays the ticket-level truth; this is the sequence, and it points at tickets rather
> than restating them.
>
> **A stale roadmap is worse than none**, so this one is checked rather than trusted — see
> `## The machine-checkable order` at the foot of the file, `scripts/verify_roadmap.py`, and
> `tests/security/test_roadmap_is_not_stale.py`. What those can prove is narrow and stated
> there; **the ORDER itself is a judgement and remains the operator's.**

---

## Right now, and next

**Written 2026-08-17 morning. The section this replaces still described 15 August**, and that staleness had a cost worth recording: on the evening of the 16th a session arrived holding a handoff card naming a rank 1 that had already shipped, and only the machine-checkable block at the foot of this file put it on the right work. **The block is checked; this prose is not.** If they ever disagree, the block wins.

**You reviewed a delivered site on the evening of the 16th and said "not good".** That ten minutes is the most informative thing that has happened to this project so far, and it reset the top of the order:

- **7 defects your hands found. 0 flagged as blocking by any automated gate. 8 requirements you stated, checked by nothing at all.**
- The single biggest cause was one line: the stylesheet defines a page container and no page applies it. The phone-width check passed that delivery and *could not have failed it*, because content with no width limit never overflows a phone.
- The contact form was dead — and the design reviewer had named that exact fault twice, told the coder to fix it first, and all three repair passes were discarded while the run still reported "MERGED, just open the app and try it."

**What has shipped since:** #1433 (merged `e729b208` + `9880cd0`, gate 11267 / 0 / 0 / 133) — the browser capture now checks every page of a site for forms instead of only the front page, and it was witnessed doing so on the 23:00 nightly. A claim in the definition-of-done that this loop had *found, fixed and re-verified* the broken form was **retracted**: the fix never landed, and only your hands disproved it.

**What is being built now, none of it needing a run or a decision from you:** ~~the probe that would have told you "four of your eight requirements failed" automatically (#1439, rank 1)~~ — **that probe SHIPPED on 2026-08-31, `d483ffef`**, and its row is gone from the block below — the layout check that would have caught the edge-to-edge pages (#1435), and the content check for repeated photographs and pages nothing links to (#1437).

**The measurement that reframes everything below.** Three from-scratch builds of the same goal inside 26 hours: the 16th-morning build owns the layout, last night's owns the contact form, and **none is best at everything.** It is not improving or degrading — it is re-rolling. That makes carry-forward (#1321) larger than its ticket assumed: not "resume the last tree", which keeps the worse one, and not even "resume the best tree", which would have discarded last night's form fix — but **per criterion**, which is why #1439 ranks above it.

---

<details>
<summary>Superseded: what this section said on 2026-08-15 (kept, because a roadmap that silently rewrites its own claims is what this document exists to replace)</summary>

**Both of the morning's two items are settled, and the test run is running.** Written the morning of 2026-08-15; this section updated the same evening rather than left describing a day that has since happened.

**Item 1 — DONE, merged `04d07953`.** The exam that grades the coder can *delete* remaining work from the plan, and the guard authorising that deletion never asked whether the quality checker accepted the exam. It now reads the verdict. Same family as the defect that deleted the "View Details" page you clicked and found broken on 7 August.

*(Corrected 13:20 after tracing it rather than accepting the survey: a **refused** exam is never installed at all, so it cannot reach that guard — the refusal genuinely works, and last night proves it. The live hole was narrower: an exam the checker accepted only **partially** still passed a guard that never read the verdict. The overstated version is left visible because a roadmap that quietly rewrites its own claims is the thing this document exists to replace.)*

**Item 2 — REJECTED, not built (#1413, closed 16:20).** The claim was that the final exam waits on all six jobs, so one cosmetic styling job giving up discards the whole night's grade. **That is false.** The grade is a separate instrument and fires regardless — measured in the code and confirmed in last night's own log, which shows the task being skipped *and* the grade running anyway. It failed for an unrelated reason: the exam itself, which is item 1. The real remaining behaviour — a coder task skipped when a dependency parks — is defensible, and the argument for closing rather than building is recorded on the ticket, along with the single observation that would make the rejection wrong.

**This is the third time in one day a claim survived until someone read the artifact instead of the sentence describing it**, and the only reason it was caught is that the ticket carried an instruction to verify before building.

**Item 3 — RUNNING.** A website test run launched **16:09**, using a throwaway settings file so it banks nothing and cannot disturb the 23:00 nightly. Expected to land about 21:00, from the last run's measured 4.82 hours (derived from its own stamps: directory `20260814-230237-bd` through its final file write at 03:51:34). It is the only run before tonight, and it is what the definition-of-done rows are actually waiting on — not more code.

---

## The four measurements this plan rests on

I verified each of these myself rather than trusting the surveys.

1. **The deletion guard never looked at the verdict.** `shared/fleet/swap_driver.py` checked exactly two stamps and stopped. Last night's record (`state/fleet-runs/20260814-230237-bd/oracle-qa.json`) reads `verdict: "refuse"` alongside the two stamps it did check — so a refused exam passed the guard that authorises deleting your work. Confirmed by reading both files. **FIXED the same day, `04d07953`; first exercised by a run only on the afternoon of 2026-08-15.**
2. ~~**The finish-line exam waits on a decoration.**~~ **This measurement was correct about the plan file and wrong about the consequence, and the difference is the whole lesson.** `acceptance-tests` does list all six siblings as prerequisites — that part is true and re-confirmed. But the conclusion drawn from it, that skipping the task discards the night's grade, does not follow: the grade is a separate instrument that never reads the task's status. **Reading the plan file was not enough; the code path had to be read too.** Retracted at #1413 and closed there. This is a good example of a true observation supporting a false claim, which no amount of care with the observation itself would have caught.
3. **The nightly is not a gate.** The launcher takes a daytime switch (`-Now`) and a throwaway settings file (`-CampaignConfig`) — parameters at lines 39–40, passed to the driver by NAME at 313–314 (a hashtable splat, not an array; the array form silently broke every side-config run). A daytime run happened on 14 August at 13:28, and another on 15 August at 16:09. Confirmed by reading the script and by launching one.
4. **The box was free.** No model server running, largest process 0.07 GB, graphics card idle at 13:13 on a working day. **No longer true from 16:09 on 15 August** — the run at item 3 is using it, which is the point.

</details>

Point 3 is the mechanical form of your complaint. Twenty-seven open tickets say they are waiting for "the 23:00 run". The rule they all cite says the opposite three lines above the correct command: it limits *how many changes go into one run*, not *how many runs happen in a day*.

---

## The ordered list

### NOW — today, 15 August

**1. ~~Stop a refused exam from deleting planned work.~~ DONE — merged `04d07953`, 2026-08-15.** *(ticket #1410, item 2)*
What it was: the coder's work is judged by an exam. A separate quality checker inspects that exam and can say "refuse". A refused exam still counted as authority to strike tasks off the plan.
Why it was here: smallest change on this list, and the one that destroyed work you asked for. Everything reported at the end of a run only fires after a pass, so nothing downstream could be trusted while a refused exam could still be authoritative.
Unblocked: every end-of-run measurement — capability rows 4, 12, 14, 17, 21. **Note the verb: unblocked, not delivered.** The fix has never been exercised by a run, and by capability 11's rule no row moves until it has been. That is what item 3 is for.

**2. ~~Stop one cosmetic failure cancelling the whole grade.~~ REJECTED — #1413, closed 16:20 on 2026-08-15.** *(had no ticket until it was split out; now has one, and it is closed)*
What it claimed: the final exam waits on all six sibling jobs, so one cosmetic styling job parking discards the whole night's grade.
**Why it was wrong:** the grade never consults that task's status. `_run_job_acceptance` gates on two conditions — did anything merge, did a wave gate fail — and last night's log carries both the skip *and* the grade running anyway. The grade failed because the exam was refused (item 1), not because the task was skipped.
What is genuinely left, and why it is not worth building: a coder task whose job is closing integration gaps is skipped when a dependency parks. That is defensible — a task asked to close a gap against work that does not exist has nothing to build against, and candidates are the scarce resource. The counter-argument (the parked task was *styling*, which has no bearing on what the exam asserts) is recorded on the ticket rather than buried, along with the exact observation that would make the rejection wrong.
**"Runs have reached their finish line 3 times in the last 17" is still true and still matters — it just belongs to item 1, not here.**

**3. Start a test run this afternoon. — LAUNCHED 16:09 on 2026-08-15.** *(no ticket needed; tracked under the session arc #1414)*
What it is: the coder launched on demand with a throwaway settings file, so it records nothing to the official scorecard and cannot disturb the 23:00 run.
The decision rule was: launch as soon as items 1 and 2 are settled, **or at 17:00, whichever comes first**. Item 1 merged, item 2 was measured away, so it launched at 16:09 — ahead of the deadline and carrying item 1's fix, which means this run is the first ever to exercise it.
Expected to land about 21:00, from the previous run's **4.82 hours** derived from its own stamps. Bounded externally rather than by editing the card's 8-hour budget — that budget is shared with the nightly and changing it would alter tonight's run too.
Unblocks: the batch of items already built, already merged, and waiting only to be observed. **How many is a measurement, not an estimate, and it is being taken while the run proceeds** — the earlier "at least eight" was a guess and is retracted here rather than quietly carried.

**4. Stop eating your typed answers.** *(#1409)*
What it is: when the coder asks you a question during setup, some of your own words are read as commands instead of as answers. An answer starting with "reject" or "stop" cancels the job. An answer containing a vertical bar gets cut in half. An answer that is just a number is read as picking option two.
Why here: it is the first inch of the loop you asked to shorten, it is the only path that moves when *you* drive it by hand, and it is plain code with no run required. It was parked behind an overnight run it does not touch at all.
Unblocks: capability row 2 ("a job you started yourself runs to completion") — the row that has been armed and unproven longest.
Needs you: no.

**5. Close the tickets that are already finished.** *(#1367, #1370, #1341, #1220, #1239, #954 — and finish the real remaining half of #1390)*
What it is: about a third of the high-priority board is completed work still showing as open. In three cases the ticket's newest note says the opposite of what the code history says. Two of them state in their own words that their closing condition was met and then decline to close.
Why here: this is your complaint in the tickets' own handwriting, and your board is currently telling you that *less* is finished than actually is. Every ranking decision after this one is harder while that is true.
Unblocks: an honest picture. Nothing technical — which is the argument for doing it fast rather than carefully.
Needs you: no.

**6. One question for you.** *(#1381, item 2)*
What it is: when a night's work is left unfinished, should the next night carry on from where it stopped, or start the same goal fresh? Today it always starts fresh, and nobody has ever decided whether that is what you want.
Why here: it costs you one sentence and it decides the shape of item 12, which is the largest unbuilt thing on this list. Asking now is the difference between building it once and building it twice. It is in the "What you decide" section below.
Needs you: yes — one sentence.

---

### THIS WEEK — 16 to 22 August

**7. A real detector for fake tests.** *(#1410, item 1)*
What it is: the current check only catches tests with completely empty bodies. A test that checks a value it just set itself, a test that asserts nothing, and a test of a built-in language feature all still count as genuine.
Why here: items 1 and 2 stop the active damage; this is what makes the resulting pass mean something. It is developed against the eighteen exams already saved on disk, replaying in a hundredth of a second, so it can be iterated dozens of times in an afternoon with no run.
Unblocks: an honest pass or fail on your stated priority. Rows 4 and 12.
Needs you: no.

**8. Fix what stops the *second* run of the day.** *(#1360 and #1328)*
What it is: two faults where one run poisons the next — a half-written bookkeeping file that blocks every subsequent run, and a leftover model-server process that starves the next run of memory.
Why here: these were mid-table when runs happened once a night. If item 3 works and runs become a tool used two or three times a day, whatever blocks the second run becomes the constraint on everything. One of these two already cost five consecutive nights by its own ticket's account, and neither has ever been picked up.
Unblocks: the entire premise of same-day iteration.
Needs you: no.

**9. Report which of your requirements were actually checked.** *(#1374)*
What it is: after each run, a plain list of which of your stated requirements the exam covered and which it never touched, naming the uncovered ones in your own words.
Why here: this is the direct answer to "did it build what I asked for", and the raw material is already banked — your eight requirement sentences for the current job are stored with the plan ("the contact page should provide feedback if a user leaves a field blank"), and there are 32 archived runs to compute the mapping over. No graphics card, no run. Only the official stamp needs items 1 and 2 to have landed.
Unblocks: row 17, and the class of check that would have caught the broken front page four automated gates approved.
Needs you: not for the measurement. Whether a missing requirement should be allowed to *fail* a job is your call, later.

**10. Rebuild the board so it survives a session change.** *(no ticket)*
What it is: sort all 409 open tickets into four visible lanes — on the main path, keeping the machinery running, waiting on you, parked — tag each main-path ticket with the capability it serves, record the "this waits on that" relationships as real links the software understands, and add an automatic check that refuses to accept finished work unless its ticket is closed in the same motion.
Why here: this is your "project manager that survives past sessions", built as structure rather than as an agent. Worth knowing why the previous attempt died: there is already a ticket meant to be exactly that durable ordered queue, and it has been stale for 25 days. A hand-maintained list cannot survive; a graph can. Today 189 tickets describe what blocks them in prose and exactly zero use the linking feature the software already has, which is why nobody can answer "what does finishing this free up" without re-reading 189 descriptions.
One incidental finding: **your two projects are named backwards.** The website goal lives in the project called "Infrastructure". The one called "Core Development" is where old tickets go to die. You have been opening the obvious one and seeing almost none of the real work.
Unblocks: your default view dropping from 409 tickets to roughly 115, and every future session ranking your queue in seconds instead of commissioning a survey like this one.
Needs you: no — but tell me if you want the projects renamed rather than the work moved.

**11. Make the planner say what it dropped.** *(#1279, part 1)*
What it is: when you describe a website needing more than eight steps, the planner silently discards the extras. Last night's job was authored at nine units and cut to eight without a word.
Why here: the shortfall then reads as the coder under-delivering, when the plan was trimmed before the coder ever saw it. That misreading is currently baked into every judgement about whether the coder is improving.
Unblocks: row 20, and your ability to trust that a disappointing result is actually about the coder.
Needs you: no. Whether eight is the *right* number is a separate measured question, deliberately not bundled.

**12. Carry unfinished work into the next run.** *(#1321)*
What it is: when a run gives up partway, that work is gone. The next run re-reads your goal from scratch and re-plans everything, so two nights on one goal are two independent attempts rather than one accumulating one.
Why here: it is the largest genuinely unbuilt thing on this list and it is what makes iteration accumulate instead of oscillate. It is not higher for three reasons: it is multi-day architecture, items 1 and 2 have to land first for a resumed run to be judgeable at all, and your one sentence at item 6 decides its shape. Start this week on the durable record of what a job has achieved — that half needs no run and no answer from you.
Unblocks: your review comments reaching the next run instead of being re-read as fresh text; rows 2, 8, 9 and 21; multi-night website goals.
Needs you: for half of it — see item 6.

**13. Make the version-pin real.** *(#1203)*
What it is: the mechanism that guarantees a night measured the exact version of the code it claims to have measured has never once been triggered by the live system. Over a thousand lines of it are built and connected to nothing; the only thing that has ever written one of these records is a test feeding itself.
Why here: every number the loop produces rests on this. Last night's numbers are trustworthy only by luck — the two copies happened to be on the same version.
Unblocks: rows 7 and 16, and the credibility of everything items 1 to 3 are designed to start producing.
Needs you: no.

**14. Publish how often it actually works.** *(#1392, item 1)*
What it is: same goal, six serious attempts, and an honest tally — how many finished, how many gave up cleanly, how many stalled. It is a report over data already on disk, not a new experiment.
Why here: it is the one number that tells you what "reliable" currently means. It sits after the fixes because those will change the number — though there is an argument for running it first to have the before-picture. I will produce both.
Unblocks: row 21, and judging progress by a trend rather than by last night's anecdote.
Needs you: no. Deciding what rate is *acceptable* is yours, later.

**15. Two honesty defects in the security claims.** *(#1207 and #999)*
What it is: a code comment still says a channel is structurally switched off, months after it was switched on — a false protection claim sitting in a security file. And separately, the scan that proves nothing can reach the internet does not cover the folder the coder's own tooling runs from.
Why here: the first is minutes of work and true on disk today. The second is contested and I will not pretend otherwise: one survey found it a clear gap, another found a comment in the same file naming that exclusion as a deliberate line between the development workshop and the shipped system. That is a question — "is the coder's harness workshop or product?" — to be answered in writing in one paragraph, and acted on only if the answer is "product". I will not spend an afternoon "fixing" a documented design decision.
Unblocks: an honest statement of what the coder's live path can reach.
Needs you: no.

---

### LATER — after the loop is closing reliably

**16. Build the website-side sabotage check.** *(#1385, item 2)*
What it is: deliberately break the code and confirm the tests notice. This exists for Python and not for websites.
Why here: your standing direction pauses overnight Python work until website work catches up. That direction cannot expire on its own, because the thing that would retire it — this — is unbuilt and unstarted. It gets substantially easier once item 7 exists, which is why it is here and not in the middle.
Unblocks: rows 3, 4 and 5 on the surface you actually care about.
Needs you: no.

**17. Make the interview ask about your own material.** *(#1165, milestone 2)*
What it is: the setup interview never asks what pictures, words or media the site should contain. There are 29 of your own photographs sitting in a test project that nothing has ever read.
Why here: it is the only open item serving the row about the product carrying real content, and even it does not finish that row. The stated reason for holding it does not survive inspection: your pending review is of the interview *template's wording*, not of whether the interview asks about assets at all. Those are separable. It is still multi-day and it does not shorten the build-look-correct loop, so it waits.
Unblocks: rows 10 and 18 partially, and the assets half of row 2. None fully.
Needs you: your template read releases the wording half.

**18. Teach the time-limit register to spot a nested override.** *(#1366)*
What it is: a short deadline hidden inside a longer one silently wins, which happened three times in one day. Sixty-four time limits are already recorded on disk to check against.
Why here: real, pure code, nothing on the main path waits for it. It retires a nuisance that has now recurred six times.
Needs you: no.

**19. Voice, narration and animation.** *(no ticket)*
What it is: one capability row covers the product carrying its own media. Images are being worked on; voice, narration and animation are entirely unmeasured and nothing on the board serves them.
Why here: it needs a decision from you about whether it is in scope at all before any engineering, and that decision is not urgent. I am listing it so that row does not keep looking one ticket away from done, because it is not.
Needs you: eventually, one sentence — not this month.

---

## The critical path, as one chain

**Read this before ranking anything.** The order below is not a list of good ideas; each link
exists because the one before it is currently false. Referenced by TICKET, never by rank —
ranks move (twice on 2026-08-15 alone) and a chain written against them goes stale silently,
which is a staleness `verify_roadmap.py` cannot see.

### Where the chain starts, and why it is here

The goal is every row of `CODER_DEFINITION_OF_DONE.md` reading LIVE, and capability 11 makes
that strict: a row is LIVE only when its **own observable has been executed end to end at least
once, with the run cited**. Code being written never counts. So the binding question is never
"is it built" — it is "has a run produced the evidence, and can anyone read it."

That is why almost every link below is about **a run producing a readable result**, not about
the coder getting cleverer.

### The chain

> **A website exam that can be repaired rather than only refused** (#1410, fixed 2026-08-15)
> **unblocks** an exam that can pass at all —
> for nine consecutive nights the model authored a thin exam, it was correctly refused, and
> nothing ever asked it to try again, because plan-time QA returned early for every non-python
> ecosystem. The repair loop existed and node never reached it.
>
> → **an exam that can pass unblocks a job-level grade that means something**, which is the
> denominator every end-of-run instrument divides by. Rows 12, 13, 14, 15, 17, 18 and 21 all
> read partial for this one shared reason.
>
> → **a grade that means something unblocks the requirement-coverage report**, which is what
> turns the operator's answers into a number rather than a feeling.
>
> → **a number unblocks carrying work across runs** (#1321 for the parked task within a run,
> #1381 for the tree between nights), which is what makes two nights on one goal accumulate
> instead of oscillate. Measured: 17 from-scratch attempts at the same site, the best result
> sitting in an archive while the live tree holds the seed stub.
>
> → **which unblocks rows 2, 8 and 9 — and a website that actually gets better across several
> nights**, which is the operator's stated priority in his own words: *"We don't need to
> one-shot websites any more."*

### Running alongside the chain, not inside it

- **Daytime on-demand runs.** `battery-bootstrap.ps1 -Now -CampaignConfig <side-file>` banks
  nothing and runs any time. This makes every link above testable in hours rather than
  overnight. 27 open tickets wrongly claim to be waiting for the 23:00 run; #740 RULE 2 bounds
  changes per run, not runs per day. **Treat "waiting for the nightly" as a smell.**
- **The operator's own hands** (#1343, #1165). His verdict on a built site is the only ground
  truth the automated graders have, and it has twice found what four gates passed (#1345,
  #1406). No amount of instrumentation substitutes for it.
- **This roadmap and its checks** (#1411), because a session that re-derives priorities from
  whatever it opens first will walk off the chain without noticing.

### How today's work connected, because the order only makes sense with the thread

2026-08-15, in causal order rather than chronological:

1. The operator answered the intake interview without the `/dispatch` prefix and got an **empty
   assistant bubble** (#1406). Second time his hands found what the gates passed.
2. That exposed a **class**: instructions that print text the parser refuses. The structural
   control built for it (`test_operator_instructions_parse.py`) immediately convicted **six more
   shipped instructions** — including the platform question's own render telling him to type a
   bare `2`, which the parser rejects. He would have hit the same defect one turn later.
3. Correcting one of those **blinded the battery harness**, which recognises a clarifying
   question by matching operator prose (#1408). A copy-edit could have stalled a night.
4. Separately, measuring last night answered a three-week-old cost question (#1322): GPU busy
   **84.7%**, harness overhead **~3.2%** — the cost is model time, so cadence is the lever, not
   plumbing. Only **37.9%** of coder GPU time reached the delivered site.
5. That reframed the card question — and then the real blocker turned out to be **#1410**, the
   exam. Which is why B9 has graded its stated goal **once in eighteen attempts**.
6. And on the path where he does everything right, a sentence beginning "reject" **cancelled his
   dispatch**, while a pipe silently halved his answer (#1409).

**The meta-finding, and the one worth inheriting:** every real defect that day was found by
RUNNING the code; every wrong claim survived exactly until someone read the artifact instead of
the sentence describing it. Reading was wrong **six** times — #1390, #1005, #1381, #1413, and
the first two diagnoses of #1410 — and that is six items, not five. **The undercount was itself
an instance**, caught 2026-08-15 pm by counting the list instead of reading the number in front
of it, which is the same move the sentence is about. Running was wrong none.

Everything not on the chain above, or not on the operator's own two items, is not the goal.

---

## The loop: how a change gets tested the same day

You were right to shout about this. Here is the mechanism, measured.

**There are three speeds, and almost everything belongs in the first one.**

| Speed | Takes | What it answers | Used for |
|---|---|---|---|
| Replay | **seconds** | did my change to a grader do what I intended? | every change to how the coder is judged |
| Full test sweep | **about 8 minutes** | did I break anything else in the system? | before merging anything |
| Full run | **about 5 hours** | does the whole night still hold together end to end? | integration only |

The graders are ordinary functions over files already saved on disk. Measured today: the fake-test check replays across all eighteen archived exams in **0.010 seconds**; the code-quality scan replays across all 180 archived deliveries in **1.1 seconds**; the relevant targeted tests finish in **3 seconds**. There are 180 past deliveries, 90 past exam records and 32 past coverage records sitting on disk to replay against.

Today, five separate tickets were pushed into a five-hour overnight slot for questions a three-second replay answers. That is the whole of "we keep going down side routes", mechanically.

**When a full run genuinely is needed, it does not wait for 23:00.** The launcher takes a "run now" switch and a throwaway settings file. The throwaway file records nothing to the official scorecard, cannot unregister the nightly, and there are about a dozen previous ones on disk — including one from 6 August launched at 11:45 and one from yesterday at 13:28. The runbook's own words: *"that bounds changes per run, not runs per day — daytime targeted runs are how you get that speed without waiting for 23:00."*

**The shape of a normal day from here:**
- Morning: read last night's result. Decide the day's one or two changes.
- Through the day: make each change, replay it in seconds, run the full test sweep before merging.
- Mid-afternoon: launch an on-demand run carrying the day's changes. It runs itself for five hours in the background while work continues.
- Evening: read the on-demand run's result, correct if needed.
- 23:00: the nightly runs on the same code, as a repeat rather than a new experiment.

That is two measurements a day instead of one, and a correction turned around in hours instead of a day and a half.

**Two real constraints, stated so nobody has to rediscover them:** the full 8-minute test sweep must not run while a coder run is live — they interfere — so it runs before the launch or after it finishes. And every run gets a watchdog attached so a stall is caught in minutes rather than at breakfast.

*For whoever runs it, not for you:*
```
pwsh -c "& C:\Users\mrbla\agentic-battery-measured\scripts\battery-bootstrap.ps1 -Now `
         -CampaignConfig C:\Users\mrbla\agentic-setup\state\<side-file>.json"
```
The side file must set `pass_banking_frozen: true`, must have `completed_passes` below `target_full_passes`, and must carry an `end_date`. Each of those three has cost a failed launch before.

---

## What you have to decide

Honestly: **almost nothing.** Of the open tickets, roughly 73 are live work, and on the path that matters you own about five sentences in total. **The two that were outstanding this morning you answered the same afternoon, so nothing is waiting on you right now.**

*(Board count: 409 when this file was first written on the morning of 2026-08-15; **412** by that evening. The per-sweep figures further down are left at the number each sweep actually ran over, because a sweep's denominator is part of its result.)*

### ANSWERED 2026-08-15 — both, in his own words

**1. Carry on, don't restart.** Asked as: when a run leaves work unfinished, should the next run carry on from where it stopped, or start the same goal fresh?

> *"When a run leaves work unfinished, the next run should CARRY ON from where it stopped — accumulation toward a finished product matters more to me than clean per-night comparisons."*

This settles the shape of item 12, which was the reason for asking. He weighed the trade-off explicitly and accepted the cost: **per-night comparability is what is being given up.** That has a consequence to build for — once runs accumulate, two nights on one goal stop being two independent samples, so any success-rate or stability figure spanning nights must record whether those nights were separate attempts or one continuing one (items 14 and 19, rows 19 and 21). Recorded on #1381 and #1321.

**2. The Python pause covers daytime probes too.** Asked as the clarification below.

> *"My Python pause DOES also cover daytime probes for now — hold all Python-side probing until the website side is on par, and I will lift it explicitly."*

So the stand-down is not an overnight-window rule, it is a whole-surface rule, and **it ends by an explicit act of his** — not by a session judging that the website side looks on par. Recorded on #1385. The practical effect is that several Python-side measurement gaps (`f2p_baseline` 63-for-63 `not-run`, `collectability` 63-for-63 `unconfirmed`, and #1200's first clause) are now **deliberate cadence choices, not open defects**, and must not be re-filed as scheduling accidents.

### Still yours, later, when the measurement exists to answer against

- Should a job be allowed to pass while some of your stated requirements were never checked? (item 9 builds the measurement; you set the bar.)
- What success rate counts as acceptable? (item 14 produces the number; you decide what it has to be.)
- Your read of the interview template, which currently holds the wording half of item 17.

Everything else on this list is mine to decide and do, and it will be done without asking.

---

## STOP DOING

Named side routes, with the reason each one is a side route.

1. **Stop writing "waiting for the 23:00 run" as a reason to defer.** It appears on 27 open tickets, 11 of them high priority — including #1410, #1279, #1386, #1398, #1390 and #1203. It is refuted by the launcher's own source, by the runbook three lines above the correct command, and by yesterday's 13:28 run. If a ticket's change replays offline, that predicate is not a blocker. It is a habit.
2. **Stop inventing a second finish condition once the first one is met.** #1390 has a note at 03:07 today recording its blocker satisfied and another at 11:45 the same day inventing a replacement. #1367 and #1370 each state in their own newest note that their condition passed on a real run, then decline to close. This is not laziness — it is momentum. The box feels closed, and one more condition preserves the feeling of being finished. It is your complaint, verbatim.
3. **Stop using a five-hour run as the development loop.** Measured: 0.010 seconds to replay all eighteen exams, 1.1 seconds for all 180 deliveries, 3 seconds for the targeted tests. Reaching for five hours to answer a three-second question is the single largest source of "nothing is moving".
4. **Stop triaging the pre-#1100 backlog.** That is 227 tickets, 55% of the board, of which four have been touched in the last fortnight and 97 have never received a single comment. They get labelled into a parked lane in one scripted pass — reversible — not read one by one. Reading them *is* the side route.
5. **Stop reading priority as a signal of what matters.** 276 of 409 tickets sit at the two middle priorities, which carries no information at all, and 33 of the highest-priority tickets are not on the goal path — including an archived log for a night that ended over a week ago. Priority means urgency within a lane and nothing more.
6. **Stop maintaining #859 as the master work queue.** It is the previous attempt at exactly what you are now asking for, and it has been stale for 25 days. That staleness is the evidence that a hand-kept list cannot survive a session change. Close it; item 10 replaces it.
7. **Stop filing session logs, night records, research watchlists and "decision" placeholders as tickets.** There are at least eleven such items on your board and they are indistinguishable from real work in every view you have. Their durable content belongs in the build journal.
8. **Stop building new end-of-run measurements until runs reach the end.** One recent instrument has produced output in 3 of the last 17 runs; another in 32 of 260. Anything added behind that gate measures nothing.
9. **Stop planning a second website card, and stop re-deriving its time budget.** A second card is a second card marked by the same broken ruler, and the existing budget was computed from a run whose tasks were short precisely because two of them were deleted by the defect at item 1.
10. **Stop hunting for duplicate tickets.** A sweep of all 409 titles found four near-duplicate pairs. The board's noise is staleness and non-closure, not double-filing. Effort spent there is effort not spent closing.
11. **Stop deferring a merge out of attribution anxiety.** A throwaway settings file records nothing and can carry three changes at once. "One change per night" has been serialising a queue the rule never applied to.
12. **Stop merging work without closing its ticket in the same motion.** Every done-but-still-open case traced back to exactly that. The moment work lands is the moment of maximum knowledge; a week later nobody remembers. Item 10's automatic check makes it mechanically impossible.

---

## What this roadmap does not cover

Said plainly so you are not surprised by an absence.

- **The other ~355 open tickets.** They are swept into lanes, not worked. If something in there matters, it will surface when its lane is filtered — not by anyone reading them.
- **The rest of BlarAI.** The assistant itself, image generation, voice, the desktop app, knowledge ingestion, the evaluation and grading-adoption arc, model upgrades, the public mirror. All alive, none of it on this list, because this list is about one goal: every row of the coder definition reading "live".
- **Anything requiring a go-live ceremony.** No network doors, no posture changes, no capability switches are proposed here. If one becomes necessary it will come to you as its own event.
- **Python-side coder measurement,** per your standing direction — except for building the website equivalents, which is the only thing that can ever retire that direction.
- **Voice, narration and animation** (item 19), which needs a scope decision from you first.
- **Hardware and model performance work.** Separate track, separate log.
- **Dates beyond "today", "this week" and "later".** Where a date is real it is stated. I am not manufacturing a delivery date for multi-day architecture, and the four capability rows that depend on repeated observation cannot be dated at all until the loop is producing a result a day.
---

## The machine-checkable order

Everything above is prose for a human. This block is the same order in a form a script can
check, and it is what `scripts/verify_roadmap.py` and `tests/security/test_roadmap_is_not_stale.py`
read. **If the two disagree, the prose is wrong** — the block is generated from the same
measurements and is the one that gets verified.

Columns: `rank | ticket | when | needs-operator | one line`.
`when` ∈ `now` / `this-week` / `later`. `needs-operator` ∈ `yes` / `no`.
`ticket` is a real Vikunja id, or `-` for work that has none yet — and a `-` is itself a
finding, because work with no ticket cannot survive this session.

```roadmap
# rank | ticket | when | needs-operator | one line
1 | #1435 | now | no | the stylesheet defines a page container and 0 of 5 pages apply it — his "not good" in one line; and phone-width passed it because unconstrained content never overflows a phone
2 | #1425 | now | no | visual FIX passes are cut off during reconnaissance — 3 passes, 25 min of GPU, zero edits, and the record calls it "produced no changes". WITNESSED 08-16: all 3 discarded, summary still said MERGED
3 | #1410 | now | no | the 08-16 witness run gave job_acceptance not-run (a wave gate failed, tree not a candidate) -- so it is STILL waiting, and the next run is the next chance
4 | #1434 | now | no | split out of #1433: the "would lose data" rule cannot see addEventListener, so row 15's forms clause is measurable in COVERAGE and not in VERDICT; fixture on disk, no GPU
5 | #1402 | now | no | a run's archive holds the PREVIOUS run's repo, so its own output is misfiled under the wrong stamp; confirmed end to end 2026-08-15
6 | #1321 | this-week | no | parked work SURVIVES in the archive and nothing reads it; 3 builds of one goal in 26h and NONE was best at everything, so carry-forward must be PER CRITERION and needs #1439 first
7 | #1343 | now | yes | he opens the built site and answers the checklist; nothing else can produce the input the escaped-defect counter needs. RAN 08-16: 7 escaped defects, 0 flagged blocking, 8 requirements checked by nothing
8 | #1381 | this-week | no | a continue mode the battery does not use — he decided "fresh on the battery, continue on demand" on 14 Aug; distinct build from #1321
9 | #1385 | this-week | no | gap 4 of five CLOSED by #1416; the mutation audit still has no node path, which is the largest remaining bar on his stand-down
10 | #1437 | this-week | no | 8 products share 3 images and 4 generated images are used by nothing; the ratio is decidable from the data file, no browser needed
11 | #1436 | this-week | no | the design critic returns Ok:true while NeedsWork/ShouldIterate/LayoutHard/RuntimeHard are all true, and its feedback loops one sentence 15x then truncates mid-word
12 | #1417 | this-week | no | a refused oracle renders as a confident Python path, so an absence reads as a specific wrong decision
13 | #1165 | this-week | no | the interview still never asks what photos or words the site should contain — M2, M3 and M6 unbuilt, no branches, no commits
14 | #1408 | this-week | no | the battery harness recognises the corridor by matching operator prose; a copy-edit can stall a night
15 | #1412 | this-week | no | the running system cannot be verified without taking it down; both headless modes are echo-only
16 | #1407 | this-week | no | a bare URL answer is still claimed by the link previewer before it reaches the question
17 | #1415 | this-week | no | a daytime run can silence the next morning's dead-man alarm, because the watchdog judges the newest directory rather than the newest NIGHTLY
18 | #1411 | now | no | a fresh session must read this file and act on rank 1; #1416 and #1433 were each rank 1 and each taken first, which is two demonstrations
19 | #1430 | later | no | nothing asks whether an assertion was FORGED; coder_test_qa measures carelessness by design and green_audit has no such fingerprint
20 | #1429 | later | no | node:test subtests are invisible to the shared tokeniser; the obvious fix reintroduces the regex-.test( defect just removed
21 | #1428 | later | no | no tautology check and no stdlib-only check exist, in EITHER language — the carelessness siblings of #1430
```

### SEVENTH revision, 2026-08-31 evening — rank 1 shipped, so its row is retired

**#1439 is CLOSED** (merged `d483ffef`, disposition `c3511b5f` at 8/8 PASS, standing gate
11342 / 0 / 0 / 133 on merged main). The row is **removed and the ranks renumbered 1..21**,
which is the same bookkeeping this file already did for #1005 below — and it is recorded here
rather than quietly deleted, for the same reason.

**Nothing was re-ranked.** This is the 2026-08-17 order with one finished row taken out and the
remainder closed up. Everything that was rank 2 is now rank 1, and so on down. Ranking is a
judgement about what matters and it belongs to the operator; retiring a row for work that has
demonstrably shipped does not.

**The verifier found it, and it found nothing else.** `scripts/verify_roadmap.py` reported
`1 stale / 0 missing / 0 unreachable-operator of 22 rows` — the stale one being #1439 — and
confirmed the other **21 cited tickets are each still OPEN**. That is the check earning its
place twice over: it named the row to remove *and* it certified that no other row is pointing
at finished work.

**Worth naming, because it is the failure this file exists to catch and it happened anyway.**
#1439's code merged at 17:30 and its ticket stayed **open** for two hours afterwards, with
#1321 — the ticket that depends on its output — carrying nothing newer than 17 August. The row
below therefore said *"build it"* about an instrument that was already on `main`. A session
arriving in that window and trusting rank 1 would have started building something finished,
which is precisely what happened to #1439 itself earlier the same day: it was rebuilt from
scratch by a session that read the description and the roadmap row and never listed the
ticket's comments. **The roadmap was accurate about the ranking and wrong about the state, and
only the board could tell the difference.**

### SIXTH revision, 2026-08-17 morning — the operator opened a site, and his ten minutes reordered the top

**#1433 is CLOSED** (merged `e729b208` + `9880cd0`, gate 11267 / 0 / 0 / 133 on merged main). It was rank 1 and was taken first — the third consecutive time, recorded on #1411's row.

**Everything else here is forced by his review of 2026-08-16, not by a session's opinion.** He opened the delivered pottery site, said *"not good"*, and then named two more things. What that produced: **7 defects his hands found, 0 flagged as blocking by any gate, and 8 stated requirements checked by nothing at all.** Four new tickets, all his findings rather than mine.

**#1439 enters at 1.** He gave the system eight acceptance criteria when he set the job up. The run checked **zero** of them (`traceability.json`: `denominator: 0`, `criteria: []`), because the exam was skipped when a dependency parked. The probe that exists (#1374, shipped 08-15) grades *whether the exam covered his requirements* — so with no exam it correctly reports nothing. **Nobody asks whether the DELIVERY satisfies them.** Six of his eight were decidable from static facts in four minutes by hand. It needs no run, no GPU and no decision from him, three disagreeing fixtures are already banked, and **#1321 cannot be built without it** — see below.

**#1435 enters at 2.** The single largest cause of his verdict, and it is one line: `styles.css` defines `.container { max-width: 1200px; margin: 0 auto }` and **0 of 5 pages apply it**. Worth its rank for the second half rather than the first — `assessPhoneWidth` passed this delivery and was *structurally incapable* of failing it, because unconstrained content is never wider than a 390px phone. An unwrapped page and a correct one produce an identical verdict today.

**#1425 drops 1 → 3 without losing standing**, and gained its first witness: all three visual fix passes discarded on `20260816-134142-bd` while the run's closing line still read *"MERGED into your project - just open the app and try it."* That is the sentence he acted on. It sits below the two above it only because both of those are cheaper and one of them is the measurement everything else is judged by.

**#1437 and #1436 enter at 11 and 12** — real, his, and lower because neither blocks anything.

**#1321's row is re-described, not re-ranked, because a fact changed.** Three from-scratch builds of one goal inside 26 hours, measured against each other: the 08-16 morning build owns the layout (container on 5 of 5), last night's owns the contact form (16 per-field error writes where the reviewed build had a dead script), and **none is best at everything.** So carry-forward cannot mean "resume the last tree" (that keeps the worse one) and cannot even mean "resume the best tree" (that discards last night's form fix). It has to be **per criterion** — which is a materially larger build than the ticket assumed, and which needs #1439's signal to know which build won which criterion.

**What did NOT change:** the operator rows keep their standing (#1343 stays at 8 and is the only `needs-operator: yes`), and nothing was promoted or demoted on a session's opinion of what matters. Every move above is either a new ticket entering from his own review or a row re-described because a measurement changed.

### FIFTH revision, 2026-08-16 evening — rank 1 shipped again, and its own replay filed the next one

**#1433 is CLOSED** (merged `9880cd0` in `agentic-setup`, with the BlarAI half in the same
motion). A fresh session read this file and took rank 1 first — the second consecutive time, now
recorded on #1411's row as two demonstrations rather than claimed as closing it.

**#1434 enters at 3**, and it exists because the fix was *replayed against a real delivery instead
of read*. The per-page forms check immediately convicted a correctly-wired contact form: the rule
cannot see `addEventListener`, which its own docstring had said for weeks while the code carried
on asserting anyway. Latent when it only ever looked at entry pages; about to fire on nearly every
correct JS form once it looked at all of them. So row 15's forms clause is now measurable in
**coverage** and not in **verdict**, and #1434 is the instrument that would decide it. It ranks
above #1402 because it is offline, fixtured and on the row closest to fully measurable.

**Not raised, deliberately:** #1425 and #1410 keep their standing. #1433 was one rank-1 item and
finishing it does not license re-sorting the rest on a session's opinion.

### FOURTH revision, 2026-08-16 — rank 1 shipped, and three residuals entered

**#1416 is CLOSED** (merged `2558220f` + agentic-setup `360472b`). It was rank 1, a fresh
session read this file and took it first, and that is the demonstration #1411 asks for —
recorded in #1411's own row rather than claimed as closing it, because one instance is not
a habit.

**#1418 takes rank 1** on the reasoning #1410's row already carries: the repair loop shipped
but its verdict is unobservable, so running it again produces nothing anyone can read. The
order within the chain is unchanged — make the instrument honest, then run it.

**#1425 enters at 3.** Filed at 00:40 on 08-16 while monitoring the nightly, after the
previous revision was written. Three visual fix passes, 25 minutes of GPU, zero edits, and a
record that reads *"the FIX pass produced no changes"* — the same absence-as-a-confident-value
shape #1416 was about, in the fix loop instead of the grader.

**#1428, #1429 and #1430 enter at the foot**, all split out of #1416 rather than bundled into
it. Each carries an observable predicate. #1430 is the one worth reading: nothing currently
asks whether a coder FORGED an assertion, and the sentence that said `green_audit` owns that
question was wrong — checked, not assumed.

**What did NOT change:** the operator rows (#1343, #1165) keep their standing, and nothing was
promoted or demoted on a session's opinion. #1385's row is re-described because one of its five
named gaps is now closed and four are not — that is a fact changing, not a judgement.

### THIRD revision, 2026-08-15 evening — the checker caught this one within an hour

`#1374` was rank 6 and **I closed it myself** after merging its work (`a691bd77`), then left it
sitting in the order. `verify_roadmap.py` reported it stale on the next run. That is twice in one
day the same check has caught a row pointing at work I had just finished — the failure is not
carelessness, it is that **closing a ticket and updating the order are two separate acts and only
one of them feels like finishing.**

Rank 1 also moved. `#1410`'s row said *"the run launched 16:09 is producing it"*; that run finished
at 18:38 and produced **no job-level grade at all**, so the witness it promised does not exist. It
drops to 2 behind **#1416**, which the day's measurement showed is the larger constraint: a
website night cannot move four of the fifteen instruments no matter how many times it runs.

**#1417** and **#1418** enter — both found by tracing why this run produced no grade.


### SECOND revision the same evening, after an independent check of the first

The block above was rewritten once at ~16:20 and again at ~17:00. **The second pass exists because the first one introduced errors of its own**, and they are recorded rather than quietly overwritten.

**What the first pass got wrong:**
- **#1409 was still listed.** It is finished — both defects fixed, 17 regression tests, no open item on the ticket. Worse, the row I wrote for it (*"needs one witnessed dispatch an operator started by hand"*) described **capability 2's observable**, not #1409's work, and marked it `needs-operator: no` while describing something that needs his hands. Row deleted, ticket closed.
- **#1381's row said "the remainder is #1321's work."** Wrong — the ticket's own description draws the line: #1321 is the fleet having no resume for a task parked *within* a run; #1381 is the battery discarding the product *between* runs. Different builds.
- **#1402 was described as destroying output.** It does not. The battery uses `Move-Item`, not a delete — the parked branch and commit survive in the archive, **misfiled under the next run's stamp and read by nothing**. That makes #1321 cheaper (it needs a reader, not a rescue) and removes the hard `blocked-by` the first pass put in front of it.
- **#1407 said "three residual ways."** One of the three was fixed by #1409 today and another the ticket itself calls correct. It is one.
- **#1165 and #1343 were carried over unexamined** and were stale in both directions: he approved the interview template on 29 July in his own words, so #1165 is not waiting on him; #1343's items 1–4 shipped and only its item 5 remains.

**Two tickets were missing entirely**, both promoted by things that happened today: **#1374**, which this file's own critical-path chain names as a link and the block omitted; and **#1385**, which his stand-down decision this afternoon turned into the gate on an entire ecosystem's measurement.

**The lesson, since it is the same one twice in one file:** the first rewrite was checked by `verify_roadmap.py` and passed, because every ticket it cited was open. Six of its fourteen rows still described work that was not what was left. **A check that a row points at live work is not a check that the row is true**, and this file says so at the foot — it took an independent reader, not the script, to find it.

### What changed in this block on the evening of 2026-08-15, and what did NOT

Stated explicitly, because **the order is the operator's judgement and a session quietly
re-ranking it is worse than a stale row.** Every change below is either a forced
correction or a direct consequence of something he decided today — none of it is a
session substituting its own priorities.

**Forced corrections** (the row was pointing at something untrue):
- **#1413 removed.** Closed as REJECTED; its premise was measured false. `verify_roadmap.py`
  caught it the moment the ticket closed, which is the check working as designed.
- **#1409 and #1410 re-described.** Both had their code merged today. Neither row's work is
  the fix any more — it is the **witness**, which is a different task with a different
  blocker, and describing them as unfixed would send the next session to re-do the fix.
- **#1381's `needs-operator` flag cleared.** He answered it. A row asking him a question he
  has already answered is the #1390 shape this file exists to prevent.

**Consequences of his decisions today** (the facts changed, not the judgement):
- **#1402 rises to 3.** It was confirmed end to end this afternoon, and his "carry on"
  answer converts it from a tidy-up into a prerequisite: a resume path cannot be built on
  an artifact that is destroyed between runs. **#1321 is now explicitly blocked by it.**
- **#1415 added at 11.** Filed today. It exists *because* of this roadmap — the more the
  project leans on daytime on-demand runs, the more likely a daytime run masks a failed
  nightly. Work with no ticket does not survive the session that thought of it.

**What did NOT change:** the three operator rows (#1165, #1343, and the now-cleared #1381)
keep their relative standing, and nothing was promoted or demoted on a session's opinion of
what matters. If the operator wants #1402 lower or #1409 higher, that is his call and this
note is here so he can see exactly what moved and reverse it.

### The first run of the verifier found a stale row in THIS file

`scripts/verify_roadmap.py`, run for the first time on 2026-08-15, reported:

```
[STALE] rank 11: #1005 is CLOSED — Gemma 4 as an out-of-family measurement instrument
```

**#1005 was closed on 2026-07-23** — three weeks earlier. It was still being cited as a live
operator decision in `CLAUDE.md`'s status snapshot, in its "near-term LA queue" line, and from
there it went straight into the first draft of this roadmap. Nobody was careless; the ticket
was simply never re-read, and a closed ticket looks exactly like an open one in a sentence.

That is the #1390 shape and it is the reason this check exists. The row is removed and the
ranks re-numbered. The find is recorded here rather than quietly deleted, because a document
that silently rewrites its own claims is what this one exists to replace.

### The second correction, an hour later — and it is the same failure

Starting rank 1 meant reading #1381, and reading it retired the row. Its first item — *"the
DoD says explicitly which acceptance test the BATTERY can and cannot exercise"* — was **already
done**, thoroughly, in `CODER_DEFINITION_OF_DONE.md`, including the exact sentence the item
asked for: *"Whether the nightly card should keep re-rolling from scratch … or continue the
previous night's tree … is an LA decision."* Its remaining items are that decision and work
blocked behind #1321.

So #1381 was ranked 1 and marked `needs-operator: no`, and it is neither. It needs him, and
nothing on it is buildable today. The row also **described the wrong defect** — the
finish-line-exam dependency is a different mechanism that was living as a clause in #1381's
comment tail with no ticket at all. It is now #1413, and it takes rank 1.

**Three times in one day I was one step from re-doing finished work** (#1390, #1005, now this),
and every time the fix was to read the artifact instead of the sentence about it. A roadmap
built from ticket titles inherits exactly this. `verify_roadmap.py` catches a CLOSED ticket; it
cannot catch an OPEN ticket whose remaining work is not what the row says. That gap is real and
is stated below rather than papered over.

### What these checks can and cannot prove

Stated here rather than left to be discovered, because overclaiming is the failure this
project keeps paying for.

**They CAN prove:** the block parses; ranks are unique and contiguous from 1; every row names
a ticket or an explicit `-`; `when` and `needs-operator` use the declared vocabulary; the
refresh date does not trail `main` (the same rule `ACTIVE_SPRINT.md` already lives under); and
— via `verify_roadmap.py`, which reaches Vikunja and therefore cannot run inside the offline
gate — that **every cited ticket is actually still OPEN.** That last one is the #1390 case:
that ticket sat on the operator's decision queue while half of it was already merged.

**They CANNOT prove the order is right.** No check can. Ranking is a judgement about what
matters, and it is the operator's. What the checks remove is the class of staleness that
*looks* like judgement — an entry pointing at finished work, a blocker nobody can observe, a
top item that has not moved in a fortnight with no note saying why.

**And they cannot see work that was never written down.** A roadmap is only as complete as the
board behind it; the same honest limit `verify_disposition.py` states about findings nobody
recorded.
