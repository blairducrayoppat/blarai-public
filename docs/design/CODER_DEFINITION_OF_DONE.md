---
title: The coder — what "working" means, and how we know
status: living
area: design
owner: Lead Architect (the WHAT); Claude sessions (the HOW)
---

# The coder: definition of done

**Why this file exists.** On 2026-07-30 the Lead Architect asked *"I need to make sure you all
understand what the goal is right now."* He was right to. There was a defect inventory (#1195),
a measurement-gaps programme (`coder-fleet-overhaul-program-2026-07-30.md`) and thirty tickets —
and **nothing stating what a working coder IS**. Work was being done item-by-item against a list
of broken things rather than against a target, and every agent brief described a task without the
goal it served.

This is the target. Every coder-fleet ticket, agent brief and go-live should be checkable against
it. Its rule of admission: if a criterion cannot be OBSERVED, it does not belong here.

---

## The goal, in the operator's words

> *"a working, reliable, robust secure coder that can do secure python and secure websites, that
> has the advanced intake and advanced interview, a local corpus, and proper exams and reviewers."*
> — LA, 2026-07-30

And, extending it — the priority that this document could not express until capabilities 8-10 were
added:

> *"my current priority is for it to be able to engineer relatively complex website with multiple
> pages … advanced interview; advanced intake; proper user-asset incorporation … proper use of code
> seeds and/or the local corpus; proper ability to research answers it needs at the various steps …
> proper image, voice, narration, and animation generation as content for websites; proper test
> authoring; proper test authoring reviews; proper test execution; proper multiple candidates based
> on how difficult; proper decomposition … proper error handling; proper coordinator reviews;
> proper multiple iterations until a working finished product; proper parking of non-working
> product; proper inspection of parked product and picked up to iterate until completion; proper
> automated testing, including live visual and functional tests … We don't need to one-shot
> websites any more."*
> — LA, 2026-08-06

And the standard it is held to, from `CLAUDE.md`:

> *"A build that works but was not designed to these principles is a defective build — same
> standing as a failing gate."*

---

## The capabilities, and what each means when it is DONE

**1-7 were written for the 2026-07-30 goal above and are about ONE dispatch being honest and
complete. 8-10 were added 2026-08-06 for the multi-page-website goal, which no number of clean
single dispatches can satisfy.** Both goals are live; neither supersedes the other.

Each row is a capability, an **observable** acceptance test, and where it stands. Status is
measured, never asserted — an unmeasured capability is `UNKNOWN`, not `done`.

### 1. It builds what was actually asked for
**Done when:** the plan the operator approves is the plan that gets built, and no requirement is
attributed to him that he did not give.
**Observable:** a dispatch on a fresh repo never prints "The person clarified these requirements"
above an answer the system invented.
**Status: LIVE as of 2026-07-30** (`888b1b02`). Fixed on the advanced-intake path by #1174
(`de136b3c`), then on the default quick path by #1197 — verified by replaying
`20260729-164648-bd` through the real `DispatchCoordinator` on a plain `/dispatch` with no
`advanced` token (platform question `False`→`True`), and across a restart. The quick path now
records axes and separates operator-authored answers from system-chosen ones. Residual #1216
(surface provenance not threaded to the fleet queue) is a different hole.
*(Re-measured 2026-08-07. This row read PARTIAL for a week after the fix shipped, because
#1197's ticket was never closed and this document reads the board.)*

### 2. Advanced intake and interview
**Done when:** a non-technical operator is interviewed in plain language, can say "I don't know",
and sees his own words played back in the plan.
**Observable:** the live flags are on and an operator-driven dispatch completes without a
technical question being asked of him.
**Status: ARMED — all nine flags live; the observable was ATTEMPTED for the first time on
2026-08-08 and did not complete.**

**2026-08-08, the first attempt ever made.** The LA ran the exercise: the interview asked in
plain language, he answered `I don't know` and it moved on, the plan card played his own
words back, and he pressed **Approve & build** — the step this row had recorded as taken
zero times. The dispatch then delivered and merged **3 of 8 tasks** (`home-page`,
`pieces-list-page`, `individual-piece-page`; 10 commits, 5 pages in
`C:/Users/mrbla/projects/pottery-studio`) before `contact-page` parked. Run
`20260808-104536-bd`. **No technical question was asked of him at any point** — the intake
half of the observable held.

**It is still ARMED, not LIVE, because the observable says a dispatch COMPLETES and this one
did not.** What stopped it is capability 8's gap, demonstrated live rather than argued from
source: the park produced a `coord_redispatch` proposal at 14:02:35 that nothing consumes,
and there is no path that would let a later run pick the work up (#1321).

The exercise also worked as an instrument and found four defects, **three of them in its own
instructions rather than in the product**: the printed command was the run-an-existing form
and cannot work on a new project; BlarAI's own footer prints the same broken command; the
`advanced` token was silently absorbed into the project name when it came second; and step
1's guidance would have had him file a false report (#1335). New rule earned: **an
exercise's commands must be executed before they are printed.** All nine flags verified `true` on
disk 2026-08-07 (`default.toml:484, 523, 610, 656, 697, 740, 788, 824, 870`), each behind an
LA-present ceremony.

**But the observable above says a dispatch *completes*, and none ever has.** Measured
2026-08-07: `C:/Users/mrbla/projects/recipe-site` holds exactly one commit (`311cd66`, created
by BlarAI, assets in place and never consumed), and across **all 206**
`agentic-setup/state/fleet-runs/*/acceptance.json` records through 2026-08-06 (re-swept 2026-08-07
17:48 local; a 207th run was in flight that evening), **zero** carry an axes-tagged clarification,
**zero** carry `spec.operator_assets` — and the schema holds no clarification key of any spelling,
so the record cannot even EXPRESS one. The interview has been
driven to the plan card twice (#1031 S2; #1165 c.2665, 2026-07-29) and **approved zero times**.
The assets use-floor, exam grading on operator photos, and the entire BUILD half of this
capability have never executed on a real dispatch.

*(RE-SWEPT 2026-08-14, 223 records. One clause above was a structural claim drawn from a windowed
measurement, and the structure has since changed.*

***"The schema holds no clarification key of any spelling, so the record cannot even EXPRESS one"
is now false.** **113 of 223** `acceptance.json` carry `spec.clarifications`. The sweep it was
written from stopped at 2026-08-06 and was right about that window; what it should not have done is
promote "no record in this window has the field" to "the record cannot express it." Those are
different claims and only the first was measured.*

***But the honest number is much smaller than 113, and it is the one that matters:* only 9 of the
113 are NON-EMPTY.** The field being present is not the interview happening; it is the interview
being possible.*

*(2026-08-15 — the SECOND attempt at this row's observable, and it stopped EARLIER than the
first.* The LA ran the exercise from that morning's report. The interview asked its eight
questions in plain language and offered "you decide" — that half held again. He then answered
three of them, formatted as three numbered lines, **without the `/dispatch` prefix**, and got a
**completely empty assistant bubble**: `parse_dispatch_command` returns `None` for unprefixed
text, `None` routes to the ordinary chat path, and the model — handed three bare answers with no
question in front of it — called `generate_image` three times and emitted no prose (#1406, fixed
2026-08-15).

**The row does not move.** Its observable is a dispatch that COMPLETES, and this attempt did not
reach the plan card, so nothing here is evidence either way about the BUILD half. What it
establishes is narrower and was not previously on this row: **the interview's INSTRUCTIONS are
part of capability 2's surface**, and as of 2026-08-15 they had been verified only by reading.
The fix ships a structural control that drives every operator-facing "type this" literal through
the real parser (`tests/security/test_operator_instructions_parse.py`); it convicted five further
shipped instructions, one of them in the PLATFORM question's own render — *"Reply with the number
(e.g. `2`)"*, which the parser refuses — so this same defect was waiting one turn later even for
an operator who answered the interview correctly.

**Second time in eight days that the LA's own hands found what the standing gate passed** (#1345,
2026-08-07, was the first). Both findings were the same species: not a broken function, but a
broken assumption about what a person would do.*)

***And the axes-tagged example is thinner than it reads.** `20260808-104536-bd` carries exactly ONE
clarification record whose `axis` field is the full list — `['surface', 'persistence', 'feature',
'visual', 'scope', 'content', 'edge', 'nongoal']` — against a SINGLE combined answer beginning
*"Here are my answers. 1. It is a real website on the ..."*. That is one clarification wearing eight
tags, not eight axis-tagged clarifications. Anything downstream asking "what did he say about
CONTENT" must re-parse prose out of a blob, which is the same shape as asking the question and not
recording the answer — so "advanced intake" still cannot be distinguished from "one long question"
by any measurement this record supports.*

***`spec.operator_assets` remains 0 of 223.** Unchanged, and still the M2 gap.*

*Method note, because it nearly became a wrong number here: my first sweep reported 0 of 223 and was
wrong. `acceptance.json` has exactly two top-level keys, `repo` and `spec`, and I had read the wrong
nesting level. The tell was grepping the raw file for `"I don't know"` and finding it present while
the parser said the field was empty.)*

This row read `LIVE` for a week. It was true of the flags and false of the capability, and the
distinction is the whole point of an observable — see capability 11 below.

Known scope limits for a first run: #1165's **M2** (the interview's assets QUESTION), **M3**
(propose-and-veto) and **M6** (reference emulation) are unbuilt — no branches, no commits — so
the interview will not ask about assets and `assets/reference/` is read by nothing. There is
also **no GUI path**: the New-project button emits `/dispatch new` with no `advanced` token
(`services/ui_winui/MainWindow.xaml.cs:322`); the only route is typing
`/dispatch advanced <project> | <goal>` into the composer.

### 3. Secure Python and secure websites
**Done when:** the coder is TOLD what secure means and GRADED on whether it complied, on every
surface it can build.
**Observable:** a planted credential or injection sink in a delivery is reported, not banded A.
**Status: LIVE as of 2026-07-30** (#1182). Brief rules 4–8 + `green_quality/security.py`.
Measured across 144 real deliveries: 141 band A, 5 findings, all genuine.

*(RE-MEASURED 2026-08-14 — the row both oversells and undersells itself, and the underselling is
the more interesting half.*

***Oversells the denominator.** "144 real deliveries" is a reviewer's one-off sweep over archived
trees, not the production record. The production corpus is **44 `green-quality.json` in
`state/fleet-runs/`** — bands **B=38, A=5, C=1**. That is a materially different picture: the modal
production band is B, not A, so "141 band A" should not be read as the fleet's habitual output.*

***Undersells the observable, which HAS executed on a real website.** `20260807-195617-bd` carries
`surface: "node-web"`, `band: "C"`, `security.worst_severity: "high"`, `security.clean: false`,
26 files scanned, and `band_reasons.c` naming `unescaped-html-sink at public/app.js:25` — described
for the operator as *"it puts text straight into the page as page-code, so anything typed in that
looks like code could run in the browser."* So the stated observable — a planted or real injection
sink in a delivery is reported, not banded A — has been executed end to end on the operator's own
priority surface, which the row never claimed.*

***And the verb matters.** That record carries `advisory: true` and `mode: "det-only"`. The band
GRADED C; it did not REFUSE the delivery. Across all 44 production records **nothing was ever
blocked** — and note the wording, because an earlier draft of this sentence said "zero carry a
security block", which is false and was caught by an independent verifier. **Seven of the 44 DO
carry a populated `security` section** (six band B, `clean:true`; one band C, `clean:false` — the
record above). Bands across all 44: 5 A, 38 B, 1 C. What is zero is REFUSALS, not security data. Calling this a refusal would credit the control with a stopping power it does not have and
was not built to have — advisory-first is the #1345 precedent, and a new way for a build to fail is
the operator's ceremony, not a wiring decision. The honest statement is that the scanner sees, says
so in his language, and bands accordingly.)*

The planted-defect
observable has itself been executed at instrument level — this row under-cited its own evidence
until 2026-08-07: `tests/integration/test_green_quality_security.py` plants a Stripe-shaped key,
an f-string SQL query and an `innerHTML` sink and asserts findings plus band C, and
`test_seed_proof_real_b5_archive_has_an_html_injection` proves the scanner fires on a REAL
archived delivery, not only on defects its own author planted. Residuals #1188, #1193. Caveat
carried from the overhaul programme and not yet retired: craft grading is Python-centric — node/web
coverage is thinner than Python's.

### 4. Proper exams — the exam must be able to fail
**Done when:** an exam that cannot detect a wrong implementation is reported as such, and the
coder is told not to write one.
**Observable, three parts:**
- a delivered test that provably cannot fail is flagged → **LIVE** (`coder_test_qa`, #1170/#1195)
- the coder is instructed not to write one → **LIVE** (brief rule 8, 2026-07-30)
- an exam that survives a deliberately broken implementation is graded weak → **LIVE**
  (`oracle_mutation`, #1195 item 2). Its band was found INFLATING on 2026-08-07: budget-expired
  and machinery-missed mutants fell into neither `killed` nor `ran`, so the score and coverage
  band rose as the audit ran LESS. Fixed `69f59f2c` (#1231).

**2026-08-15 — THIS ROW'S FLAGSHIP CHECK HAS NEVER EXAMINED A WEBSITE, AND IT REPORTS THAT AS THE
CODER'S FAULT (#1416).** Bullet 1 — *"a delivered test that provably cannot fail is flagged"* — is
carried by `coder_test_qa`, which reads **Python only** (`shared/fleet/coder_test_qa.py:930`,
`if not name.endswith(".py"): continue`, over an `ast`-based module with no JavaScript parsing).
Across all 95 banked records, **55 of 55 website records return `no-tests`** while Python cards
produce 30 `clean` and the corpus's only `findings`.

Worse than blindness: the `no-tests` detail reads *"this task changed 19 file(s) and NONE of them
was a python test — **it wrote no exam for its own work**"*. Checked against the archived delivery
rather than assumed: last night's B9 tree carries **nine test files** (`test/api.test.js`,
`test/core.test.js`, `tests/data.test.mjs` and six more) and **zero Python files**. The coder wrote
its exams. The grader could not see them, then stated in the operator's reading language that none
existed — `measured: true` and `files_scanned: 0` in the same record. That is capability 7's defect
in its most damaging form: not a silent zero, but a confident and wrong accusation.

**Consequence for this row's own path to LIVE:** website nights cannot move bullet 1, no matter how
many run. The `unexecuted_property` half is unreachable on websites twice over — `aad2070`'s
`-StatsPath` fix lives inside the pytest branch only (`fleet-lib.ps1:3629`), and node runs
`npm test`, which never writes `.blarai-hypothesis-stats.txt`.

**2026-08-16 — THE STRUCTURAL BARRIER ABOVE IS REMOVED FOR BULLET 1. THE ROW HAS NOT MOVED.**
`coder_test_qa` now reads node as well as python, reusing `oracle_qa`'s exported tokeniser rather
than growing a second JavaScript parser. Measured on the same archived delivery the paragraph above
cites: **9 files scanned where it scanned 0**, `languages: {python: 0, node: 9}`, and one HARD
finding it could not previously reach — `tests/data.test.mjs`, a file named as an exam that declares
no test, asserts nothing, and prints *"All tests passed!"* whenever the code does not throw. The
accusation is gone from the harness in both directions: a candidate whose exam is in an unreadable
language now returns a new status `not-covered` whose sentence says *"this is a gap in the GRADER,
not a fault of the coder"*, and `Measured` is read from the scanner instead of being hardcoded
`$true`, which is what put `measured: true` and `files_scanned: 0` in one record.

**Why the status below is unchanged anyway, and this is capability 11 working rather than
pedantry.** Building an instrument is not evidence. Bullet 1 may move only when a RUN has produced a
website `coder-test-qa.json` reading a non-zero `languages.node` — and none has, because this landed
after the 08-15 nightly ended. What changed today is that such a record is now POSSIBLE; for 55
consecutive website deliveries it was not, and no number of further nights would have produced one.

**What is still structurally unreachable on a website, stated so it is not mistaken for fixed:**
`unexecuted_property` — untouched by this work and untouchable by it. Hypothesis is a Python
library; node runs `npm test` and writes no statistics file. That half of this row's proof set
cannot come from the website surface at all, and the operator's Python stand-down (#1385) is what
governs when it can come from anywhere.

**Status: PARTIAL — the three checks above are LIVE as instruments, but `unexecuted_property`
(half the capability's proof set) cannot fire in production — traced 2026-08-07 through both call
sites and re-derived that day — and the first mutation measurement is UNVOUCHED.**
`unexecuted_property`, half the proof set, still cannot fire — **the CONCLUSION is correct and was
re-verified 2026-08-15; every `[DEAD]` citation below it is not.** The mechanism has moved and the
reason has narrowed, so read the corrections at the foot of this row, not these pointers: the
dispatch path runs
`uv run … pytest -x -q` with no `--hypothesis-show-statistics`
(~~`agentic-setup/scripts/fleet-lib.ps1:3526`~~ **[DEAD — `aad2070` added the flag]**), no
statistics artifact is produced (~~`:3508-3535`~~ **[DEAD — it is produced; live writer
`fleet-lib.ps1:3643`]**),
and neither production call site passes `-StatsPath` or `-RequireProperty`
(~~`new-agent-task.ps1:601`, `:713`~~ **[DEAD — `-StatsPath` IS now passed, `new-agent-task.ps1:663`;
`-RequireProperty` still is not, by ZERO callers, and that is the live half]**; the omission is
deliberate, commented at ~~`:593-595`~~ **[DEAD — the live comment is `:657`]**), so
`PropertyExecutionMeasured` — the DISCLOSURE field, set from `[bool]$StatsPath`
(`fleet-lib.ps1:1200`, defaulted false `:1080`) — ~~is always false in production~~ **[SUPERSEDED
2026-08-15 — I struck this sentence's PREMISE two paragraphs up and left its CONCLUSION standing,
which is the inverse of the error I was checking for and was caught by an independent reviewer.
`-StatsPath` IS now passed at `new-agent-task.ps1:663`, so the field is TRUE on that path and
false only at `:779`, where it is deliberately withheld and says so. Not yet contradicted by
data — no post-`aad2070` Python run has banked it and the stats file dies with its worktree — so
this is wrong going forward rather than provably wrong today.]** and
`property_execution_finding()` is unreachable there **— still true, but for a DIFFERENT reason
than this sentence gives: not because the statistics are unmeasured, but because
`coder_test_qa.py:677-678` returns before reading them whenever `property_test_required` is
false, and `-RequireProperty` is passed by zero callers** (defined `shared/fleet/coder_test_qa.py:659`,
sole in-module call `:1003`; citations re-derived 2026-08-07 — the prior `:995`/`:592` had
drifted). #1199 is
now UNBLOCKED — its own `blocked-by` (#1195 item 1) has landed — and simply not done. The gap
is at least DISCLOSED rather than printed as a zero (`fleet-lib.ps1:1080/1312/1334`), which is
honesty, not capability. #1201 (whole-tree attribution) is FIXED — `db7b2525`, `--since` scoping
with `SCOPE_UNRESOLVED` failing closed, verified on a real five-worktree night.

**2026-08-15 — THIS ROW'S STATED BLOCKER IS FIXED, and the citations below no longer resolve.**
The gap named above — `fleet-lib.ps1` producing no statistics artifact, `new-agent-task.ps1`
passing neither `-StatsPath` nor `-RequireProperty` — was closed in agentic-setup `aad2070`,
merged to main 04:06 on 2026-08-15. `fleet-lib.ps1` now runs `pytest --hypothesis-show-statistics`
and persists `.blarai-hypothesis-stats.txt`; `new-agent-task.ps1` passes `-StatsPath` when that
file exists. The line numbers cited above (`:3526`, `:601`, `:713`) have shifted and no longer
point at this logic. **`-RequireProperty` is still deliberately unpassed and that half remains
accurate** — a new way for a build to fail is the operator's ceremony.

**CORRECTION, 2026-08-15 evening — the sentence that closed this banner was wrong, and wrong in
the direction that flatters the row.** It read: *"What is now outstanding is narrow: no production
dispatch has yet exercised the fixed path with a real `@given` test, so by capability 11's own
rule this reads ARMED until witnessed once."* That tells a reader row 4 is **one run away.** It is
not. Verified on disk:

- **`-RequireProperty` is passed by ZERO callers.** It exists in exactly three places: declared
  (`fleet-lib.ps1:1113`), consumed (`:1125`), and a comment at `new-agent-task.ps1:657` reading
  *"-RequireProperty is STILL NOT PASSED"*.
- `shared/fleet/coder_test_qa.py:677-678` is `if not property_test_required: return None` — the
  function exits **before it ever looks at the statistics**.

**So `unexecuted_property` cannot fire in production no matter how many dispatches run.** A
witness is not what this half is waiting for; passing the flag is, and that is an operator
ceremony because it creates a new way for a build to fail. `aad2070`'s `-StatsPath` fix genuinely
landed and is genuinely necessary — it is just not sufficient, and the old sentence let
"necessary" read as "nearly done".

*(Recorded against over-correction, because the check that found this overstated it: an
independent verifier reported the whole banner as materially wrong. It is not. The
`-RequireProperty` clause immediately above was already accurate and stays. **One closing sentence
was wrong — and it was the one that set the reader's expectation**, which is why it matters more
than its length suggests.)*

**The first measurement — b4 17/20 *adequate*, b2 15/20 **weak**, 5 survivors — was produced by
the PRE-#1231 scorer and must be treated as UNVOUCHED until re-derived.** Whether those runs
were budget-complete cannot be determined from the recorded figures.
*(Re-measured 2026-08-07.)*

**2026-08-08, #1350 — the strongest check this row owns has never once produced a result.**
The fail-to-pass baseline (run the exam against a tree where the product does not exist and
require it to FAIL) is *the* instrument for "an exam that cannot fail". Reading every banked
`oracle-qa.json` in `state/fleet-runs/`: **81 of 81 records carry `f2p_baseline: "not-run"`**,
across both ecosystems, since 2026-07-12. 67 of the 81 also report `findings_total: 0` while
neither execution probe ran. #1342 diagnosed a node-only early return and fixed it correctly,
but the Python rows are stamped `not-run` just as consistently, so the node skip was one of at
least two causes and closing it did not make the baseline start working.

*(RE-SWEPT 2026-08-14, and the last clause is now FALSE. It is 81 of **89**, and the node baseline
has produced a real measurement on every run since 2026-08-09 — **8 consecutive `all-fail`**, which
are also the eight most recent runs in the corpus: `20260809-140620-bd`, `-154357-`, `-194621-`,
`-230346-`, `20260810-012417-bd`, `-123348-`, `-230238-`, `20260811-232102-bd`. No gaps, no
regressions. "Closing the node skip did not make the baseline start working" was written before the
next run, and the next run falsified it.*

*Cross-tabbed by language the split is total and clean:*

| `f2p_baseline` | python | node |
|---|---|---|
| `not-run` | **63 of 63** | 18 |
| `all-fail` | 0 | **8** |

*So the correct statement is: **the node half works and has for eight straight runs; the Python half
has never produced a result and has not run at all since 2026-08-06** (`20260806-233512-bd`). Both
halves of that sentence matter, and reporting only the first would be this document's own #1241
shape. The Python figure is now a deliberate cadence choice rather than an open defect — #1385
defers Python nights until web is on par — and a future reader must not mistake it for a scheduling
gap.)* `BLARAI_ORACLE_QA` is
unset at every scope, so the kill-switch is not the cause. **The static half is real and does
catch vacuous oracles** — the escaped B9 oracle grades `verdict: refuse` on
`collectability`/`adequacy_floor` findings today — so this is not a claim that the QA does
nothing. It is the EXTENT of #1342's finding: every GREEN this project has banked rests on an
exam never shown able to fail, and the field saying so has read `not-run` since it was written.

### 5. Proper reviewers
**Done when:** work is not merged on the strength of an exam the candidate wrote for itself.
**Observable:** a green-gated task with a proof-grade exam defect has its review-skip withdrawn.
**Status: LIVE as of 2026-08-14 — the withdrawal event HAS been observed in a live dispatch, on
the current instrument version, with a named blind spot.** Cited:
`20260805-000122-bd/run-fleet-store-cards.log:19` and `:83` —

> `CODER TEST QA: 1 finding(s) over 1 test file(s) of the 16 file(s) THIS task changed, 1 PROVEN
> — the green-gate review SKIP was WITHDRAWN so the reviewer looks at this exam;`

Twice in one run: a green-gated task carrying a PROVEN exam defect had its review-skip withdrawn,
which is this row's observable word for word. Capability 11's third clause is satisfied too —
`shared/fleet/coder_test_qa.py` was last changed 2026-07-30 (`822bda60`), so the 2026-08-05 run
executed the CURRENT deciding instrument, not a superseded one.

*(This row read ARMED with "the withdrawal event has never been observed" until 2026-08-14, and
the dates are worse than that sounds. The event happened on **2026-08-05**. The sentence denying it
was written on **2026-08-07** — `5dcce590`, the capabilities 11–21 ratification — so the row
asserted "never observed" **two days after it had already happened**, and then carried that for
another week. Nobody grepped for it: the row was re-verified by re-reading the decision FUNCTION,
which had not changed and therefore still looked right, rather than by searching the run logs for
the EVENT. Re-reading a status line is not measuring it, and a status line written during a
ratification pass is the most dangerous kind, because the pass is where everything gets its
authority stamped at once.)*

**The blind spot, stated rather than buried, because it is the whole of what is thin here.** One
run of 258, and `language: python`. The trigger has never fired on a node/web task, and by the
operator's direction of 2026-08-14 (#1385) no Python night is scheduled until web development is on
par — so this row is LIVE on evidence that will not be added to for some time.

**2026-08-15 — THE PARAGRAPH ABOVE MISDIAGNOSES ITS OWN BLIND SPOT, AND THE CORRECTION IS WORSE
THAN THE ORIGINAL (#1416).** *"Evidence that will not be added to for some time"* describes a
CADENCE problem — the right nights are not being scheduled. It is a STRUCTURAL one. This row's
trigger is a `coder_test_qa` finding, and that scanner reads Python only:
`shared/fleet/coder_test_qa.py:930` is `if not name.endswith(".py"): continue`, over a module built
on Python's `ast` throughout, with no JavaScript or TypeScript parsing anywhere in it.

**So the trigger cannot fire on a website at all. A thousand website nights would not add one
data point to this row.** Measured across all 95 banked `state/reports/*.coder-test-qa.json`:
every Python card is graded (b2 19 clean, b4 11 clean + the corpus's only `findings`), and
**every website record — 55 of 55 across b9 and pottery-studio — returns `no-tests`.**

**The row does NOT move**, and that is deliberate rather than generous: capability 11 asks whether
the stated observable was executed and cited, and it was, on 2026-08-05, on the current instrument.
What changes is the honest reading of what LIVE means here — **this row is live on Python and
structurally unreachable on the operator's priority surface**, which the previous wording let a
reader mistake for a scheduling accident. The distinction matters most for #1385: the direction
stands down Python work *"until the website side is on par"*, and these instruments cannot come on
par by running websites. They have to be built for websites first.

**2026-08-16 — THEY HAVE NOW BEEN BUILT FOR WEBSITES. THE ROW'S BLIND SPOT IS A CADENCE PROBLEM
AGAIN, WHICH IS THE ONLY HONEST WAY IT COULD EVER BECOME ONE.** `coder_test_qa` reads node, and a
node exam that provably cannot fail now produces a HARD finding in the same `vacuous_test` class its
Python dual uses — so `Test-ShouldRunReview(green, green, hard>=1) => True` is reachable from a
website task. Proved through the real `Invoke-CoderTestQa` against a real node tree rather than a
mock, because "nobody ever ran this pair against a website" is the entire reason the defect survived
55 records: a planted empty-bodied `test/empty.test.js` returns `Status=findings`, `Hard=1`, and the
operator block reads *"the green-gate review SKIP was WITHDRAWN"*.

**Deliberately the SAME class, not a node-specific one.** A parallel taxonomy would leave the two
ecosystems incomparable, and incomparability is precisely what let this row read LIVE while half its
surface was ungraded. A count the operator reads now means one thing in both languages.

**This row still does not move, and for a new reason.** It has been LIVE since 2026-08-14 on the
2026-08-05 Python event, so there is no status to change. What is retired is the *"structurally
unreachable on the operator's priority surface"* clause: the withdrawal has still never fired on a
website, but that is now a fact about which nights have run, not about what the instrument can do.
**The next website night can settle it, and until one does, nobody should cite this row as evidence
that websites are graded.**

**#1385's retirement path is unblocked but not walked.** The stand-down ends only by the operator's
explicit act, and this closes one of the two things that made "on par" unmeetable by running web —
`coder_test_qa`, which carries rows 4 and 5. The other three Python-only graders named in #1416
(`green_audit`, `oracle_mutation`, and the ruff pass) are untouched, so the website ceiling has moved
from 11/15 to 12/15, not to 15/15. **That figure is DERIVED — #1416's own count of four Python-only
graders, minus this one — not a measurement taken here**, and it should be re-measured against the
banked records rather than inherited. (Called "a measured claim" in the first draft of this
paragraph; an independent reviewer caught it, which is the same overclaim this row is about.)

Verified 2026-07-30
against a real delivery's inputs beforehand: `hard=2`,
`Test-ShouldRunReview(green, green, hard=2) => True`. The clean-room second grader and the guest-VM
oracle predate this.

### 6. A local corpus
**Done when:** the planner works from real API documentation rather than recall, the coder can
look up an API it does not know without leaving the machine, code seeds are part of the same
grounding substrate (the operator's clause: "code seeds and/or the local corpus"), and research
is reachable at EVERY step that needs an answer — plan, build, fix, exam-author — not only the
two wired today. *(Seeds and every-step reach ratified 2026-08-07.)*
**Observable:** a plan cites names and semantics that exist, on a library the model does not know
well; and a coder lookup returns a real page rather than "dormant".

**Status: PLAN-TIME STOOD-DOWN (LA, 2026-07-30); BUILD-TIME ARMED + INSTRUCTED, never exercised —
armed 2026-08-06, instruction restored 2026-08-08 (agentic `ca981db`, merged `5fced14`), zero
coder lookups ever (re-measured 2026-08-14).**

**2026-08-16 05:02 — THIRD CONSECUTIVE COMPLETE JOB, SAME ANSWER. This is now a measurement, not
a gap awaiting one.** `state/research-usage.jsonl` is **unchanged at 1,990 records** — 1,986
`plan_grounding` (stood down) and 4 `search_docs_cli`, all pre-existing developer probes, the
newest of which carries `cwd: C:\Users\mrbla\agentic-setup` and is therefore a hand-run probe, not
a dispatch. Across the 2026-08-15/16 nightly (`20260815-230306-bd`): **5 tasks merged, wave 1
complete, every candidate and every fix pass logging `[research-docs] ARMED for this run` — and
not one lookup.**

Three complete jobs now: `20260814-230237-bd`, `20260815-161349-bd`, `20260815-230306-bd`. The
first was an instance, the second made it consecutive, the third settles it. **Armed, instructed,
reachable, and unused** — the tool works when driven by hand (verified EXACT 1.00 against the
13,803-page index) and the coder does not reach for it. That is a finding about the BRIEF or the
model's disposition, not about the wiring, and no further run is needed to establish it.

**2026-08-15 — THE ROW'S OWN TRIGGER FIRED, AND THE ANSWER IS NO.** This row said the build-time
half was *"blocked on a RUN — the next complete dispatch either produces the first coder lookup or
it does not."* That dispatch happened: `20260814-230237-bd`, six tasks, B9. Every task log carries
`[research-docs] ARMED for this run`, repeatedly, through three visual-fix passes each. And
`state/research-usage.jsonl` is **unchanged** — still 1,990 lines, still only 4 `search_docs_cli`
records, all of them pre-2026-08-08 developer probes. **The coder did not call the tool once
across a complete six-task job on the operator's priority surface.** Armed, instructed, and unused
is now a measurement rather than a gap awaiting one.

*(CORRECTION, 2026-08-14. This line read "BUILD-TIME ARMED + MUTE (#1320) — armed 2026-08-06, its
instruction reverted the same evening", and it contradicted its own row: the paragraph below
already said ARMED + INSTRUCTED. The header was describing a state that ended six days earlier.
Verified: the live brief carries the tool at `~/.config/opencode/AGENTS.md:91` — "You have a
`search_docs` tool. It searches a LOCAL, offline copy of the official documentation" — and
`configs/AGENTS.md` ships it. What DID hold up: `configs/fleet-driver.json` carries
`research_docs: true` while the note beside it opened "DORMANT ('false')" and described arming as
a future governance step; corrected in agentic `ec6d25d`.*

*"Zero coder lookups ever" survives re-measurement, and the reason it survives has changed, which
is the part that matters. Of the 1,990 records in `state/research-usage.jsonl`, **1,986 are
`plan_grounding`** (the stood-down half, all on 2026-07-30/31) and **4 are `search_docs_cli`**, run
by hand from the agentic-setup working directory. None is a coder lookup inside a dispatch, and the
last record of any kind is dated 2026-08-08. So this rung is no longer blocked on a wiring change.
It is blocked on a RUN — and the battery has banked nothing since 08-11 (#1380). The next complete
dispatch either produces the first coder lookup or it does not, and either answer moves this row
off "never exercised" onto a measurement.)*

This row read *"Blocked on the
operator: #746 docset approval"* until 2026-07-30 pm. That was wrong on both facts, and it was
steering sessions to wait for a decision already made. #746's design was **LA-APPROVED on
2026-07-05**, in his own words, naming the two research points and the deterministic-first
lookups; its one gated item was the docset DOWNLOAD, and the corpus has been **staged and
hash-verified since 2026-07-06** — 15 artifacts, 134.6 MB, index 13,803 pages, zero egress
(`models/docsets/MANIFEST.sha256.json`; `docs/DECISION_REGISTER.md:106`).

The two halves are separate rungs, blocked on different things, and neither is an approval:
- **Plan-time grounding** (`research_grounding = false`) went LIVE 2026-07-30 am and was STOOD
  DOWN the same evening at the LA's direction, because nobody had measured what the retrieval
  actually returned before arming it. Re-arming is gated on the #1204 relevance fix **and a fresh
  measurement on the operator's own goal shapes** — not on time passing. With the flag false the
  decompose prompt is byte-identical and `shared.research` is never imported.
- **Build/fix-time lookup** (#1206, `research_docs` in `configs/fleet-driver.json`) was **ARMED
  2026-08-06** at the LA's in-person direction, after sitting installed-but-unused since 07-24.
  Live-verified before and after against the real 13,803-page index (`collections.Counter` → exact
  hit, score 1.0), and `state/research-usage.jsonl` gained its first-ever `search_docs_cli` records.
  **Then measured again during a live run and found ARMED BUT UNUSED**: the arming ledger said
  `armed:true` on every candidate spawn while the usage ledger recorded zero coder lookups, because
  `search_docs` was named nowhere in the coder's brief. Fixed the same day (agentic `f92a4ef`).
  **Status is therefore ARMED + INSTRUCTED, still UNMEASURED for whether it helps** — that is a
  count in `research-usage.jsonl` on the next run and nothing else. Note the shape: *switched off*
  and *switched on and never mentioned* are indistinguishable in every artifact except that ledger,
  which itself could not tell a coder's lookup from a developer's probe until `2a4796a`.

  **CORRECTION, measured 2026-08-07 — "INSTRUCTED" is no longer true (#1320).** The 23-line
  section naming `search_docs` (`219d899`, 10:12) was **deleted the same day** by `609a925`
  (17:13, author `harness-sync`). The fix edited the *repo* copy of `configs/AGENTS.md`; the coder
  reads the *deployed* copy at `~/.config/opencode/AGENTS.md`, never updated (dated Jul 30);
  `sync-harness.ps1` syncs live→repo, so the sync faithfully captured the unfixed live file and
  reverted the commit. `grep -c search_docs ~/.config/opencode/AGENTS.md` → **0**, and 0 in both
  agentic-setup HEAD and the pinned battery tree. The 2026-08-06/07 overnight battery ran with
  `armed:true` on **every** spawn and the usage ledger gained **nothing**.
  **Real status as of 2026-08-08: ARMED + INSTRUCTED again — the revert was undone, live copy
  FIRST this time. Still zero coder lookups, so still short of the observable.** Re-measured
  2026-08-08 16:0x: `grep -c search_docs` returned **0** in the deployed brief, **0** in
  agentic-setup HEAD and **0** in the pinned battery tree — #1320's revert was still fully in
  force nine days on. Restored to `~/.config/opencode/AGENTS.md` **before** the repo, both
  verified byte-identical, so `sync-harness.ps1` (live→repo) cannot revert it a second time —
  that ordering is the fix, the text is secondary. Merged `01a528f`-line, agentic
  `fix/1320-restore-search-docs-instruction`. Tool proven live before claiming anything:
  `search_docs "URLSearchParams.getAll"` → EXACT 1.00 on both `[dom]` and `[node]`, offline,
  from the 13,803-page index. **The observable is a `search_docs_cli` record whose caller is a
  coder** — the ledger holds 1,989 records of which 3 are lookups, all developer probes.
  Arming, instructing and helping are three different things; this closes the second only.
  *(Prior state, retained: ARMED + MUTE. Zero coder lookups had ever occurred* (3 `search_docs_cli`
  records exist; all are developer probes — re-verified 2026-08-07 17:48: 1,989 ledger records,
  and a sweep of all 887 coder transcripts finds zero `search_docs` calls ever, while 8
  "Invalid Tool" listings prove the tool WAS offered to coders). #1206 was closed on a predicate
  the revert un-met.
  The fix survived seven hours and every artifact still reported success — the arming ledger, the
  ticket, and this row.

- **SECURITY, both halves (#1312, measured 2026-08-07):** the LIVE lookup
  (`agentic-setup/tools/search_docs.py:287-312`) does **not** datamark; the datamarking
  implementation (`BlarAI/tools/search_docs.py:103-113`, 63 gate tests) is wired to nothing — the
  JS wrapper default-resolves to agentic-setup's copy and `BLARAI_RESEARCH_TOOL` is set nowhere,
  while BlarAI's file's own docstring claims the wrapper shells out to it (that false prose is
  ticketed). The plan-time half does not datamark either: `shared/fleet/decompose.py:1248`
  prefixes the block `shared/research/plan_grounding.py` returns ABOVE the planner's
  instructions, unlabeled. #746 requires `UNTRUSTED_EXTERNAL` provenance on retrieved
  docs; **neither live path meets it**, and that is mitigated today only by the accident that one
  half is off and the other is mute. The plan-time datamark must land BEFORE `research_grounding`
  is re-armed.

- **The corpus itself is the right substrate and is not the problem.** Index measured directly
  2026-08-07 (`models/docsets/index/docset_index.sqlite3`, 102.9 MB): 13,803 pages / 26,329
  symbols, of which **web sources are 10,475 pages — 76%** (dom 7,766, javascript 1,291, css
  1,101, html 252, node 65). This is not a Python-only corpus.
  **But note:** every plan-time disproof was run on PYTHON goals. #1204 c.2736 asserts web goals
  clear the floor unaided, which means plan-time grounding would actually PRODUCE blocks on
  website goals — and **nobody has measured whether those blocks are right**. The website case is
  the least validated corner of the half that is already switched off.

**The lesson this row now carries:** an approval recorded in one place and a status line written in
another drift apart, and the status line is what gets read. A blocker naming a person should name
the artifact that proves it — a ticket, a date, a decision row — or it will outlive the block.

### 7. It is measurable — every number means what it says
**Done when:** no instrument in the pipeline can report a pass it did not measure.
**Observable:** every grader distinguishes "did not run" from "ran and found nothing".
**Status: PARTIAL — the instrument-honesty fixes are LIVE as of 2026-07-30 and that is where the
day was spent; two verification predicates outstanding (#1200, #1203).**

*(MEASURED 2026-08-14, and this row has been understating itself while carrying a trap. Across all
89 `oracle-qa.json`, `collectability` reads `unconfirmed` 63 times, `skipped` 18 and **`confirmed`
8** — and those eight are the eight MOST RECENT runs, consecutive, 2026-08-09 to 08-11. Eight
straight runs of the honest-measurement output this row exists to produce, unclaimed here.*

***The trap, and it is the reason this row must not be read as vindicated.** All eight `confirmed`
stamps are **node**. Cross-tabbed, the split is absolute:*

| `collectability` | python | node |
|---|---|---|
| `unconfirmed` | **63 of 63** | 0 |
| `skipped` | 0 | 18 |
| `confirmed` | **0** | **8** |

*#1200 is a Python/uv defect. Its fix merged in `24878d88` on **2026-08-07**, and the last Python
run of any kind is `20260806-233512-bd` on **2026-08-06** — so **not one Python job has run since
the fix landed**, and no `confirmed` stamp anywhere in the corpus exercises the path that fix
touches. Python is 63-for-63 `unconfirmed`, every one of those measurements taken against the
pre-fix code. So the recent run of green does not
discharge #1200's predicate, which is exactly why that predicate is a @slow-tier `uv` parity run
and not "the stamps look fine now." Reading eight node `confirmed` as "the instrument works" would
be a partial result presented as whole with an honest stamp lending it credibility — this row's own
subject, committed by this row.)*

Fixed: the battery now executes
merged code (#1181a); `assert True` can no longer mint GREEN-VERIFIED (#1184); an unmeasured
security scan cannot render clean (#1182); the advisory ruff lint runs at all for the first time
and says so when it cannot (#1189). The three holes this row listed as open have all LANDED IN
CODE (board re-measured 2026-08-07 evening): #1198 CLOSED (fixed 2026-07-30, agentic `5d1d5db`,
ticket unclosed for a week — the same shape as capability 1's week of false PARTIAL); #1200 fix
merged (`24878d88`), ticket open only pending a real @slow-tier run of
`test_oracle_qa_uv_parity.py` (the standing gate deselects it); #1203 fix merged (`b5d881a4`),
ticket open only pending a pinned-tree battery night (#1301) plus its owed disposition record.

**2026-08-15 — the @slow predicate was RUN for the first time, and running it found a live
defect this row is about.** Two corrections first: there is no `test_oracle_qa_uv_parity.py` —
the tests live in `shared/tests/test_oracle_qa.py` as three `@pytest.mark.slow` cases, and a
predicate naming a file that does not exist cannot be discharged by anyone looking for it. And
the confirmed count is now **9, still every one of them node**; tonight's B9 run
(`20260814-230237-bd`) added the ninth. Python stays **0 for 63**, every measurement pre-fix,
so the trap this row describes is unchanged and the row does not move.

On the first execution, two of the three failed. One was a defect in the LOCK: the toggle case
resolved `uv run` without passing `cwd`, so it inherited pytest's working directory — the
BlarAI checkout — where uv discovers `.venv/` and reports that interpreter. Production never
resolves from the repo root. It failed against a correct product.

The other was real, and it is this row's own subject. With `FORCE_COLOR` set in the parent
environment — as any agent harness, CI runner or multiplexer may set it — pytest colours its
output, the escape lands between the test name and `PASSED`, and `_passed_tests` misses. The
FAIL-TO-PASS baseline, the check that convicts an oracle passing with **no implementation
present**, then stamped `not-run` instead of `vacuous:<test>`. Measured both ways on the
identical call: `not-run` with `FORCE_COLOR=3`, `vacuous:test_always_green` with it cleared.
A grader reporting a non-answer that reads as innocuous, which is the row's definition of the
defect. Fixed with three independent locks (`--color=no` in the `grade_env` recipe SSOT and its
guest twin, colour-var scrubbing in `_qa_env`, and ANSI-stripping in the two parsers), each
toggle-proved. **The nightly battery does not set `FORCE_COLOR`, so this never fired there** —
which is exactly why it survived: a blind spot that only opens where the parent is colourful.

**#1200's predicate is now HALF discharged, and the halves are worth separating.** Its second
clause — *"the probe is exercised by a test that drives the REAL `uv run` command rather than a
substituted `pytest_cmd`"* — is MET: all three `@slow` cases now pass against real uv 0.10.0
with its managed 3.13.12. Its first clause — *"a run's `oracle-qa.json` reports a determinate
collectability result"* — still needs a Python job, and no node night can supply one.

**AND #1203 IS NOT WHAT THE PARAGRAPH ABOVE SAYS.** That text — *"fix merged (`b5d881a4`),
ticket open only pending a pinned-tree battery night (#1301) plus its owed disposition record"*
— implies the work is done and waiting on an event. **The event happened last night, and the
pin did not apply.** Measured, in order: the run's own spec (written 23:06:56, a minute before
the first `RUN-START`) records `scripts_dir: C:\Users\mrbla\agentic-setup\scripts` — the PRIMARY
checkout, the exact field with the exact wrong value this ticket was opened for. Its validator
could not object, because `scripts_pin_violation` returns `""` whenever no live run has declared
a pin, and `state/fleet-swap/pins` **does not exist on disk** — not empty, absent. Swept both
agentic trees, `blarai-ops`, and BlarAI's `launcher/`, `services/` and `tools/`: every reference
is a reader or a path helper, and **the only thing that has ever written a declaration is a test
fixture** (`test_fleet_dir_resolution.py:498-500`).

So +1,165 lines of fail-closed hardening are built and wired into nothing — this project's own
canonical failure, inside the fix for a defect of that shape, in the pin whose job is
guaranteeing the battery measures what it claims. Last night was not measurably harmed only
because the primary happened to sit on the same commit as the pinned tree for the whole run;
that is timing, not mechanism, and this row is about the difference. **Row 7 therefore does not
move, and #1203's remaining work is larger than "a disposition record": it needs a production
writer, and a test that fails when that writer is absent** — the present suite manufactures its
own input, which is why this survived from 2026-07-30 to now.

**2026-08-08 — a PRODUCTION demonstration of this row's own observable** (*"every grader
distinguishes 'did not run' from 'ran and found nothing'"*). `_rule_harness_budget` filed every
HARNESS fault as budget exhaustion on the attribution alone, reading neither elapsed nor
budget — 49%, 102% and 0.9% of budget all wore the one label. Fixed (#1324, `0550dcb6`) and
proven the same day on a real run: scorecard `20260808-160538-bd` reads `HARNESS-ENVIRONMENT`
with fingerprint `elapsed 295s of 28800s (1%) - NOT budget exhaustion`, and the battery
summary's taxonomy counter moved `HARNESS-BUDGET Δ-1 / HARNESS-ENVIRONMENT Δ+1`. The label can
now be CHECKED rather than believed, because the numbers travel with it. Honest limit: the run
this proves it on still FAILED, for a cause root-caused separately (#1341) — an honest
instrument is not a working system.

**2026-08-08, second instance the same day — the highest-authority grader in the system was
the one violating this row.** `oracle-qa.json` reported `validated: true, findings_total: 0`
with `f2p_vacuous: 0` sitting beside `f2p_baseline: "not-run"` and `collectability:
"skipped"` — a count of zero from a check that never ran, against an oracle that was
three-fifths vacuous. Downstream, `already_satisfied` read that pass and deleted two tasks
from the plan. Fixed (#1342 item 2, `83633ce0`): `CLASS_STAGE` maps every finding class to
the stage that produces it, and `findings_conclusive` is false whenever any producing stage
did not run — a total from unrun checks is a floor, not a count. `not_measured` names what
did not happen in sentences a person can read, and the operator's own review page now shows
it (agentic `9413f7f`), so *"this site was graded by an exam nobody checked"* reaches the
one reader whose verdict is this document's ground truth. Toggle-proved. **What is still
open on this row: item 5 — requirement coverage (`oracle_coverage: "unknown"`) does not gate
GREEN, so a delivery can still be certified against an exam that covers none of what was
asked.**

---

### 8. It finishes a product across MANY runs, not one

A complex multi-page site does not fit in one dispatch and never will. Today the system has no way
to express that: `parked` is a terminal task state, no resume path exists (#1277), the planner
re-decomposes the whole goal from text on every run with no memory of what a prior run built or
why, and there is no measure of *how much of the product is finished*.

**DONE means:** a run that does not finish parks honestly with its work recoverable; a later run
picks that work up, knows what was already built and decided, and continues rather than restarting;
and at any moment the operator can be told how much of the product exists. **Proper error handling
is part of this row (ratified 2026-08-07):** a run that fails for ANY reason — including
infrastructure failure — parks honestly and visibly; no failure path may end in a silent pass or a
vanished run. **A goal with no
progress measure has no finish line, and "iterate until complete" cannot terminate.**

**Status: PARTIAL as of 2026-08-10 — raised from UNKNOWN by measurement, and the row's own
prior text is falsified.** It read *"the resume path, run-to-run memory and progress measure do
not exist (#1277's own record: 'It does not create a resume path. None exists')."* Run
`20260810-012417-bd` shows all three working. Its journal records **eight separate `RUN-START`
invocations** under one run id, with the continuation counters climbing on every one:

```
RUN-START … resume_done=0 prior_dispatches=0   -> create-home-page        -> delivered=True
RUN-START … resume_done=1 prior_dispatches=1   -> create-contact-page     -> delivered=True
…
RUN-START … resume_done=4 prior_dispatches=4
  TASK-SKIP-DONE | implement-header-menu is on done.txt — it already delivered
                   (dispatches=1/4); not re-dispatched
…
RUN-START … resume_done=7 prior_dispatches=7   -> design-fix-1
```

A later invocation **read what an earlier one built and declined to rebuild it**. That is the
resume path and the run-to-run memory, exercised seven times in one night. The progress measure
exists too, as three files the run maintains: `done.txt` (7 entries), `done-reasons.txt` (why
each), and `dispatches.txt` (8, including the design-fix) — enough to answer *how much of the
product exists* without reading a log by hand, which is precisely what the 2026-08-08 entry above
said could not be done.

**Why PARTIAL and not LIVE, stated as a boundary rather than a hedge.** What was demonstrated is
continuation *within a run id* — sequential invocations of the same queue, each resuming the last.
What #1277 and #1321 describe is a **different and harder case**: a task that PARKS, and a
genuinely later run — new id, new night — picking it up from a `coord_redispatch` proposal that
`coord_redispatch.py:481-485` still records as *"THE SEAM, not the hook: nothing calls this
today."* No task parked on this run, so that path was not exercised and remains unproven. The
2026-08-08 observation stands for the parked case; it is simply no longer true of the general one.

Also unchanged: `DEFAULT_MAX_TASKS=8` still bounds how complex a product can be described (#1279).
This run authored **7** units (`decompose-diagnostics.json`: `mode=plan-graph`,
`cleaned_task_count=7`, `degraded=false`), so it passed under the cap rather than testing it. **DEMONSTRATED LIVE 2026-08-08** — no longer an argument from source reading. The LA's own
9-task dispatch (`20260808-104536-bd`) delivered and merged 3 tasks, then `contact-page`
parked. `coord_redispatch` staged a proposal at 14:02:35; **nothing consumed it**, exactly as
#1321 records (`coord_redispatch.py:481-485`, *"THE SEAM, not the hook: nothing calls this
today"*). `state/fleet-swap/task-queue.json` still holds the parked task — the intent
survived and there is no path that reads it. Re-dispatching would rebuild the three finished
pages from zero, and the operator cannot be told what fraction exists without reading
`done-reasons.txt` against `dispatches.txt` by hand. All five of this row's gaps, observed in
one run. Tracked: #1277 (the recovery handle,
fixed and live-verified 2026-08-06), #1279 (the 8-task cap that bounds how complex a product can
even be described — `DEFAULT_MAX_TASKS=8` at `decompose.py:87`, silent truncation `:1101`, B9
authored at 9 units and cut to 8), #1285 (parked work is preserved but unfindable from its own
run record).

**A SECOND failure path for this row, measured 2026-08-09 (#1357), and it is upstream of the
resume gap.** On `20260809-140620-bd` the coder ran `node src/server.js` — a web server, which
does not exit — and blocked on it for **602 seconds** until an external stop landed. The task
then parked, and because `create-piece-detail-page` and `acceptance-tests` both depend on it,
**both were skipped as dependency-blocked with 3 of 4 dispatches unspent.** One hung shell
command cost three quarters of the run's remaining capacity and the operator's individual-piece
page for a third consecutive delivery.

This is not a one-off: across all 932 banked agent logs, 17 contain a server-start command, and
the stall after it is measurable — 602 s and 601 s (both aborted), then 553 s, 519 s, 330 s,
276 s, spanning B5, B7, B9, `authorwebsite3000`, `pottery-studio` and `space-landing` since
2026-07-12.

> **CORRECTION, 2026-08-10.** This paragraph read: *"The `agentic-setup` coder runtime has no
> per-command timeout at all (verified against `https://opencode.ai/config.json` — only
> provider and MCP timeouts exist)."* **That is false.**
> `~/.config/opencode/plugin/command-timeout.js` caps bash at 300 s with a 10 s server probe,
> has been live since 2026-07-10, and prints its banner in **771 of 969** banked agent logs.
> The schema check was accurate; the conclusion was not. A published schema describes what a
> product's *config* accepts — a plugin is a different mechanism and the schema knows nothing
> about it. Verifying against a description of the product instead of the running system is
> this document's own capability-7 failure, committed while writing capability 8.
>
> **The corrected finding is worse than the original.** The plugin was written for this exact
> command — its comment cites `node src/server.js` by name from incident #688 — and its
> pattern was tested and **does match** it (via the `serve` alternation in `server.js`). On run
> `20260809-143821` the plugin was loaded, the pattern matched, and the command still ran
> **602 s**. A 10-second cap was configured, matched, and did not bound a ten-minute hang.
>
> **RESOLVED 2026-08-10 — the cap fired correctly and could not have worked.** The run's own
> tool-call record carries `"timeout": 10000`, so the clamp reached the tool; and the command
> was not `node src/server.js` but **`cd <worktree> && node src/server.js &`**. opencode's
> timeout races the *child's exit*, and collects the command's output afterwards, outside every
> branch of that race. A trailing `&` makes the shell exit in about a second — so the race
> resolves as `exit`, no kill branch runs, and the tool then reads output to end-of-stream on a
> pipe the detached server still holds open. Reproduced standalone: the same command redirected
> to a **file** returns in 1 s; piped, it never returns. Tracked on #1357.

So the honest statement of this row's second failure path is stronger than "a bound existed and
did not hold": **the bound was correctly applied and is structurally incapable of covering this
shape.** A timeout bounds a command that runs too long; `&` converts the command into one that
finishes immediately and leaves a pipe open. The fix is to refuse the shape, not to tune the
number — and the doom watchdog noticing the silence minutes later is what actually ended it.

That generalises past this one command, which is why it belongs in the DoD rather than only on a
ticket: **a control can be present, loaded, matched, and inert.** Three of this row's failure
paths were each read as the absence of a control when the control was there; the question worth
asking of any guard is not "does it exist" but "what does it race, and can the thing I fear win
that race by finishing early?" `node app.js` is separately a genuine gap in the plugin's pattern
— covered by the deny-list and not by the plugin — and is a much smaller finding than it looked
next to this one.

**The deny-list, by contrast, is now PROVEN in production** (2026-08-10, run `20260810-012417-bd`,
`design-fix-1`): `pattern="node src/server.js"` → `action=deny`, the coder was told a rule
prevented the call, and three minutes later it ran `node --test tests/page-structure.test.js`
instead — a bounded check. That is the observable this row wanted: not the absence of a hang, but
a refusal the coder recovered from. Two details had to be right and were only verified that day —
opencode resolves permissions with `findLast`, so the 23 deny rules win only because they sit
*below* the `"*": "allow"` wildcard rather than above it; and it evaluates each parsed sub-command
separately, so a `cd … &&` prefix does not defeat an anchored pattern. The first was correct by
authoring accident.

**And the same log shows the deny-list being walked around.** At 14:15:58 the coder started a
listening server by inlining it — `node -e "… server.listen(3000, …)"` — which no entry-point
pattern can match, and it was **allowed**. Not an evasion attempt; just a model expressing the
same intent in a shape the blocklist does not enumerate. This is the standing weakness of a
blocklist inside a `"*": "allow"` default, and it moved from argument to measured instance within
six hours of being named as theoretical.

Two things this row therefore requires that it did not name before: **a hung command must be
bounded by the coder, not rescued by a watchdog** (a stop that arrives after 10 minutes has
already cost the candidate), and **a park caused by infrastructure must not consume the task's
remaining dispatch budget** — best-of-N parked here without starting a fresh candidate (#771),
so the run spent one candidate on a hang and retired the task.

Worth recording alongside: the doom watchdog was **correct** on this run, and I twice diagnosed
it as faulty from file timestamps before reading the agent log that settled it in thirty
seconds (#1356, retracted). A control that fires correctly and gets blamed is one edit away
from being weakened; the log was on disk the whole time.

**A THIRD failure path, and the first with a MEASURED RATE (#1365, 2026-08-09 23:35).** The
23:00 nightly cleared every blocker above — archive guard fired, and the per-card budget was
**HONORED at 28,800 s for the first time ever**. Then the coder started a generation at
23:13:06, the model server wrote its last line at 23:13:03, and **both stayed silent for 624
seconds** until the run was stopped. Nothing came back; the card scored STALLED with eight
hours of granted budget unused.

Scanning all **947 banked coder logs** for the signature (a generation starts, then >300 s
with no further output) returns **seven candidates** — and **four sit at exactly 601 s**. That
is not a model behaving randomly, it is a boundary: `acp.idle_sec = 600`. Seven across B4, B5
and B9 since 2026-07-24 is roughly **0.7% of all banked candidates**, which is this row's first
quantified failure rate rather than an anecdote.

It also **unifies two failures that looked separate**: the 612 s entry is the `node
src/server.js` hang of #1357. One reaper, at least two causes — a blocked shell command and a
wedged generation — sharing a 601 s signature that made them read as one problem.

The defect is named in the harness's own comment (`fleet-lib.ps1:829`): the idle bound was
*"RAISED from the spike's 120 after the #790 A/B finding that a 120 s idle watchdog false-killed
~84% of 30B candidates: the 'no session/update' signal cannot tell a slow-generating 30B from a
genuinely wedged one."* **The signal was blind at 120 s and is still blind at 600 s** — raising
it cut false kills from ~84% to ~0.7% without making it any more able to answer the question.
Lesson 221 for the sixth time, and that lesson already names the remedy: *or the phase must
emit a heartbeat*.

Tonight's was a **true** kill, not a false one: the doom detector requires no coder CPU as well
as stale artifacts, `ovms` measures 14–29% per-core during live generation against a 5%
threshold, and it read idle. That is the worse finding — **the 30B stops producing and nothing
but a ten-minute timer notices.**

So this row requires two more things it did not name: a generation must expose a heartbeat the
reaper can read, and **a wedged candidate must be retried rather than spent** — tonight it
consumed the task's attempt, and best-of-N exists precisely so a bad candidate is not fatal. A
candidate that never produced a token is not a candidate at all.

### 9. He can SEE and USE the result

Every capability above is about *building*. None of them puts the product in front of him. A
finished website sitting in a sandbox repo he never opens is not a website, and a site he cannot
click through is one he cannot judge.

**DONE means:** he can view and use the built site without knowing git, and the way he does that
survives a reboot. **And it includes his own review loop** — *"the nav should be on the left, the
photos are too big"* — fed back as a next iteration. The system has coordinator reviews (machine
reviewing machine) and an eyeball tier that hands him a verdict; it has no path for his judgment to
become the next change. For a website, that judgment is most of the product.
**Status: PARTIAL as of 2026-08-08 — the SEEING half is done and was exercised for real; the
FEEDING-BACK half is not.** He opened a built site on 2026-08-08 for the first time and
recorded a verdict (`state/operator-reviews/20260808-185500-battery-b9-pottery-site.md`,
#1345). The loop that carried it is live: `Review Website.cmd` finds every build including
the archived ones that would otherwise vanish by morning, serves it, refuses to present
anything it cannot prove is the right build, shows the run's claims leading with what was
NOT built, hands him his own goal clause by clause, reports which links lead nowhere, and
saves his words against the run id (agentic `724b321`). A website battery run now fires this
automatically instead of relying on him remembering (`75e8e24f`). What remains is (b): his
judgment reaching the next run, ordered AFTER resume (#1321) because feeding back "make the
nav bigger" is worthless if the next run rebuilds the site from scratch. Tracked at #1280.

### 10. The product carries its own content

Generated images, voice, narration and animation are on the roadmap. **Words are not.** A pottery
site is mostly text — the studio description, the piece blurbs, the contact copy — and nothing in
the intake, the plan, or the exams asks for any of it, so the coder invents placeholder prose or
leaves lorem ipsum and every gate passes.

**DONE means:** written content is planned, authored and graded like any other deliverable, and the
operator's own words are used where he supplied them.
**Status: PARTIAL as of 2026-08-09 — GRADED and AUTHORED are met; PLANNED and "his own words"
are not. Re-measured; the paragraph above overstates the gap.**

**GRADED — yes, and it is a registered instrument.**
`tools/dispatch_harness/green_quality/placeholder_prose.py` scans delivered pages for
placeholder and lorem text, and it is entry #2 in `shared/instrument_registry.py`
(`result_type="ProseResult"`, `status="measured"`, `entrypoint="scan_repo"`) — so it carries the
same required toggle, seam and quiet tests as every other grader. It has fired on real battery
nights, and the counter distinguishes the three states this document cares about:

```
prose: placeholder=0, clean=1, no-prose-surface=0, not-measured=0
prose: placeholder=0, clean=0, no-prose-surface=1, not-measured=0
```

A delivery graded genuinely clean, and another correctly reported as having no prose surface to
grade rather than being counted clean by default.

**AUTHORED — yes, with operator evidence.** Reviewing the pottery site on 2026-08-08 the LA said
of the delivered pages: *"The text for the different was appropriately varied."* No lorem, no
placeholder, on the one delivery a human has actually read. That is the strongest evidence this
row can have, and it agrees with the grader.

**PLANNED — no.** Nothing in the intake or the plan asks what the site should SAY. The prose
appears because the coder writes it, not because anyone specified it, which means its quality is
unowned even though its placeholder-ness is now checked.

**"His own words used where he supplied them" — no, and it is the same hole as capabilities 2
and 18.** There is no path by which operator-supplied copy reaches a delivery; `assets/` intake
takes photographs and documents and nothing consumes them (`recipe-site`: 29 files, never used).

**What the grader cannot see, stated because a clean prose count reads stronger than it is:**
it catches placeholder and lorem. It does not judge whether the prose is *good*, whether it
describes the right product, or whether it contradicts the picture beside it — which is exactly
the defect the operator found by eye (*"descriptions of the products don't match the image"*) and
that no text grader will ever catch. Tracked at #1281.

---

## Capabilities 11-21 — RATIFIED 2026-08-07

**Provenance: 11-16 proposed by a Claude session 2026-08-07 am, at the LA's direct question
("are there any capabilities that are obviously missing... especially involving QA, review, and
testing?"); 17-21, the sharpenings to 11/14/15, the status legend, the goal-coverage map and the
row 6/8 amendments added the same evening by the DoD review session (#1323). RATIFIED by the LA
the same evening — the full proposed set, selection delegated to the review session's judgment in
his words: "I approve of all the proposed ones that you think are good." Recorded on #1325 and in
docs/DECISION_REGISTER.md; statuses document-wide follow the ratified legend, enforced by
`tests/security/test_coder_dod_grammar.py`.**

Capabilities 1-10 ask whether each instrument is honest. **Not one of them asks whether the
instruments are RIGHT**, and every gap below was found by hand rather than by anything in the
pipeline — which is itself the argument for adding them.

### 11. A capability is not LIVE until its own observable has been executed

Capability 2 read `LIVE` for a week on the strength of nine `true` flags while its observable — a
dispatch that *completes* — had never once happened. Capability 4's status cites a measurement
(`b4 17/20`) produced by a scorer later found to be inflating. **A flag is a configuration; an
observable is an event.** DONE means: no row here claims LIVE until the stated observable has
been run end to end at least once, with the run cited — and re-executed when the instrument that
grades it changes: an observable executed once, on an instrument since repaired, is `UNVOUCHED`,
not `LIVE` (capability 4's exact case). Everything else is `ARMED`.
**Status: PARTIAL — enforced for THIS document by the grammar gate, and as of 2026-08-15 the
other thirteen files are checked too; what remains is that a date is not proof of an event.**

**2026-08-15 — "checked by nothing" is retired.** The row named two defensible next steps —
extend the citation check to the twelve, or decide in writing that a ceremony record's date IS
its citation — and recorded that neither had been done. The first is now done:
`tests/security/test_status_claims_are_dated.py` scans `docs/ledger/`, `docs/runbooks/` and
`DECISION_REGISTER.md` for any `LIVE`/`ARMED`/`DORMANT` token and requires an ISO date in the
same file. It finds the same **thirteen** files this row measured, all compliant today. It scans
DIRECTORIES rather than an allowlist, so a new file publishing a claim is picked up instead of
passing by not being listed; it carries a population floor, so a broken glob fails loudly rather
than passing over an empty set; and it is toggle-proved — an undated claim planted in
`docs/runbooks/` makes it fail and name the file.

**The row stays PARTIAL, and the reason is the row's own subject.** A date is not proof an event
occurred, and no textual check can be. What is now refused is the specific failure capability 2
demonstrated — a status asserted with no event reference at all, which then read as settled for a
week. The floor moved from "someone remembered" to "the file says when". Promoting this row on
that would be exactly the move this row already refused once: a promotion bought by narrowing the
goal to what the available check happens to cover.

*(The tempting shortcut here was to declare the row DONE by scoping it to this document — its own
DONE clause does say "no row HERE claims LIVE", and the grammar gate enforces exactly that, and it
demonstrably fired today when it refused to let rows 5 and 17 move without a dated citation. That
would have been a row promotion bought by narrowing the goal, which is the one move this document
must never make. So I measured the wider property instead.*

***Thirteen files outside this document publish a `LIVE` / `ARMED` / `DORMANT` claim*** — three
under `docs/ledger/`, nine under `docs/runbooks/`, one in `DECISION_REGISTER.md` — with lines like
*"`web_search` is LIVE"* and *"The advanced-intake front (S1) is LIVE."* **Every one of them
carries a date**, because they are go-live ceremony records and sprint closes, which are dated by
construction. So the property is *conventionally* held out there. **Nothing checks it.** The tests
that read those paths (`test_doc_pointers_and_banners.py`, `test_doctrine_freshness.py`) check
pointers, banners and staleness — not that a status claim is backed by a cited event.*

*That is the honest position: PARTIAL because the discipline is enforced in exactly one file and
observed by habit in twelve others, and habit is what capability 2 had when it read LIVE for a week
on nine `true` flags. The next step is not a bigger claim, it is extending the citation check to
those twelve — or deciding, per surface and in writing, that a ceremony record's date IS its
citation. Either is defensible; neither has been done.)*

### 12. The gates' false-negative rate is measured — escaped defects are counted

Capability 3 records *144 deliveries, 141 band A, 5 findings*. That is either excellent work or a
weak grader, and **nothing in this document can distinguish those two.** Every capability above
measures whether an instrument ran honestly; none measures whether it was correct. DONE means:
defects found AFTER a delivery was banded are counted against the gate that missed them, and the
false-negative rate is a published number. Without it, a rising band average is not evidence of a
rising product. The operator's own eyeball verdict (capability 9) is the natural ground truth,
which is why 9 and 12 are one loop rather than two features.
**Status: PARTIAL as of 2026-08-08 (#1345) — the column has its first row, and it is not
encouraging. PARTIAL, not LIVE: this row's observable is a PUBLISHED RATE, and one reviewed
delivery is a data point.** One delivery reviewed (B9, run `20260807-195617-bd`, banded GREEN). Seven
observations from the operator; **three were real defects and none had been caught by any
gate**: the same image reused across products, product descriptions not matching the image
shown, and a "View Details" button on every gallery item leading to a JSON error. All three
verified on disk. The third is #1342's amputation seen from outside — the page was deleted
from the plan by an oracle that could not fail — and he found it in under a minute by
clicking a link, while the instrumentation took hours. **One delivery, three escaped
defects, four gates.** That is a rate of one reviewed delivery, so it is a data point and
not yet a rate; what it retires is the claim that the number is unknowable. One of the three
(the image mismatch) had already self-corrected by the following night's build, which is
only known because it was re-measured rather than assumed to carry.

*(RE-MEASURED 2026-08-14. Everything above holds. Two things have changed underneath it, and both
say the counter this row needs does not yet exist.*

***The schema cannot hold an escaped defect.** `state/operator-reviews/` contains exactly ONE
record. Its schema is `operator-website-review/v1` and its fields are `build_name`, `build_path`,
`build_source`, `capture_note`, `operator_feedback`, `pages`, `recorded_at`, `run_dir`, `run_id`,
`schema`, `skipped_tasks`, `verdict_at_review`. `verdict_at_review` holds what the gates said
(`GREEN`); `operator_feedback` holds his nine sentences as free text. **Nothing in it can be
counted.** The three defects are recoverable only by a human reading prose — so a false-negative
RATE, which is this row's stated observable, cannot be computed from the record even in principle.
The missing field is the whole capability.*

***And the count is already stale, because his findings do not arrive through the tool.** There are
**8 review session directories** and one record; the record's own `capture_note` says it was
*"Recorded from chat rather than the script's prompt — he reviewed in his own browser while the
loop was still being built."* Since 2026-08-08 at least three further defects have escaped the
gates and been found by him or by inspection — #1367 (`/` served the 1,044-byte scaffold stub past
four gates), #1370 (bounded fix passes discarded rather than judged), #1375 — and **not one of them
appears in any review record.** They became tickets by conversation.*

*So the counter this row owes must read BOTH paths, the tool and the conversation, or it will
report three forever while the true number climbs. Counting only what the tool captured would be
this document's own #1241 shape: a partial measurement presented as the whole, with an honest
schema lending it credibility.)*

*(BUILT the same evening — agentic `429f9d4`. "The schema cannot hold an escaped defect" was true
for about two hours. It holds one now, and it needed no new question put to him: **a clause HE
marked `not-met` on a build the pipeline BANDED is, by definition, a defect the gates passed and he
did not.** The marks have been taken since #1343; nobody counted them. `escaped_defects` carries
`count`, `denominator`, `verdict_at_review` and the offending clauses in his own words, so a RATE
is computable from a single record — which is this row's stated observable.*

*It refuses to report a zero three ways, and those refusals are the point rather than the
arithmetic. No checklist → `measured=false`, `count=null`, never 0, because "he was never shown a
list" and "he found nothing" are different facts. No verdict → also unmeasured, because a defect is
only ESCAPED relative to a gate that let it through. And `could-not-tell` / `not-reviewed` are
excluded, because counting his silence as a defect manufactures escapes. Toggle-proved by mutating
the unmeasured case to emit 0 instead of null: two checks fail, and they are exactly the two
guarding that property (`verify-website-review-loop.ps1`, 90 → 102 checks).*

***The row still does NOT move, and the reason is the paragraph above this one.*** The counter reads
one of the two paths. It states so in the record itself — `scope_note: "FLOOR, not a total"`,
naming #1367, #1370 and #1375 as known escapes it cannot see. And its denominator is still one
reviewed delivery, so what it can publish today is a data point, not a rate. What changed is that
the number is now **computable and honest about its own scope**, which it was not this morning.)*

### 13. The graders are themselves graded

#1231 (2026-08-07): `oracle_mutation`'s score and coverage band ROSE as the audit ran LESS,
because budget-expired and machinery-missed mutants fell out of the denominator. It measured
honestly and reported a partial result as a complete one — which capability 7's framing ("no
instrument can report a pass it did not measure") does not catch. It was found by reading the
file. DONE means: a grader's own arithmetic is verified by something that is not that grader,
and a partial result can never present as a whole one.
**Status: PARTIAL — the #1231 reconciliation invariants lock `oracle_mutation`; every other
grader is UNKNOWN.**

**2026-08-15 — THE DEFECT TABLE BELOW IS STALE BY A FULL NIGHT.** `link_lint` (#1389) and
`image_placement` (#1391) are fixed, closed, and each held by locks that fail when reverted;
`green_audit` (#1390) has its disclosure fixed, with only its fail-closed decision open and
correctly escalated. **Six further instances of the same class were found and fixed the same
night** — #1393 #1395 #1396 #1397 #1399 #1400 — three of them found by an independent verifier
re-checking fixes this document had already recorded as complete. A new control class exists that
this row's table has no column for: `tests/security/test_sibling_scanner_parity.py` requires the
two bounded scanners to disclose the same shortfalls or declare the difference with a reason,
after the same fix was carried to one sibling and not the other three times in one review pass.

**Second instance, 2026-08-08 (#1324):** the failure classifier presented an unmeasured
conclusion as a measured one — asserting budget exhaustion without reading the budget. Same
class as #1231, different grader, and again found by reading the file rather than by anything
in the pipeline. Its arithmetic is now verified by data it does not own (the card's
`run_budget_s`, stamped onto the scorecard) rather than by its own attribution field, and the
fingerprint publishes the inputs so a reader can re-derive the verdict. Two graders locked,
the rest still UNKNOWN — and two independent instances make this a class, not a coincidence.

**Third instance, 2026-08-14 (#1389) — found by LOOKING rather than by being bitten, which is
what a class is for.** `shared/fleet/link_lint.py` has both halves of the same mechanism. Its
published denominator is *derived from the numerators it is meant to check* —
`"references": tally.resolved + tally.broken + tally.undecidable + tally.external + tally.in_page`
— so a reference examined but landing in no bucket leaves numerator and denominator **together**
and the arithmetic stays internally consistent while under-reporting. And there is a live way to
land in no bucket: the classification loop writes
`setattr(tally, status.replace("-", "_"), …)`, a dynamic attribute write against a plain dataclass
with no `__slots__`, so a status that is not one of the five field names does not raise — it
creates a new attribute nothing reads.

Not firing today: every return path yields one of the five. **The defect is that nothing prevents
a sixth**, and adding one is a one-line change 200 lines from the tally, with no exception and no
red to mark it. Filed rather than fixed because `link_lint` runs at the wave-final floor — it is on
the battery's execution path, and the 23:00 run must not be decohered by a same-day change to an
instrument that fires exactly there (#740).

**Three instances now, and the third suggests the class is structural rather than incidental:**
each grader owns both its counters and its total, so none of them can detect its own losses. The
remaining twelve of fifteen should be assumed to share the shape until checked, not assumed sound.

**THIRD GRADER LOCKED, 2026-08-14 — and this one was already built right, which is the useful
finding.** `green_quality/traceability.py` computes `denominator` as `len(self.criteria)` — the
POPULATION itself, not a sum of its counters — so it does not have #1231's shape. That was
verified rather than assumed, and it is now held by four locks in
`tests/integration/test_oracle_traceability.py` that drive the result object from outside it:

- the buckets **partition** the criteria at every declared level, summing to the denominator;
- a criterion carrying a level no bucket recognises **still counts in the denominator** — the
  #1231 property stated directly, and the one that must never regress;
- the partition assertion is **not vacuous** (a known-bad level makes it fail), because an
  invariant that cannot fail proves nothing;
- and the property underneath all of it: **coverage cannot rise by losing criteria.** Degrading a
  criterion from `L3-ASSERTED` to an unrecognised level lowers the numerator and leaves the
  denominator alone, so the ratio can only fall.

Note the direction: here a lost criterion would UNDER-report coverage, the safe way round — but
"safe direction" was nobody's decision and nothing checked it, which is the whole of capability 13.

**ALL FIFTEEN AUDITED, 2026-08-14. The UNKNOWN this row has carried since ratification is
retired.** Four independent reviewers took the remaining twelve in parallel and read each one to
the same four questions: is the published denominator an independent population or a sum of the
instrument's own buckets; can an examined item land in no bucket; can the headline IMPROVE when the
instrument does LESS work; verdict. Every finding below was re-derived by me on disk before it was
written here.

| verdict | instruments |
|---|---|
| **SOUND** — denominator independent, partition total | traceability · security scan · placeholder prose · archetype regression · craft lint ×3 · coder-test QA · behaviour-smoke contract · seed divergence |
| **NO DENOMINATOR** — no ratio exists, so the arithmetic cannot occur | advisory ruff lint |
| **LOCKED PREVIOUSLY** | `oracle_mutation` (#1231) |
| ~~**DEFECTIVE**~~ **[SUPERSEDED 2026-08-15]** | ~~`link_lint` (#1389) · `green_audit` (#1390) · `image_placement` (#1391)~~ — **`link_lint` and `image_placement` are FIXED, CLOSED and locked; only `green_audit`'s fail-closed decision is still open, and that one is an operator ceremony.** |

**[SUPERSEDED 2026-08-15 — the row's own correction at the head of this section governs. Counted
on disk that day: **10 locked**, precisely three unlocked (`archetype_regression`,
`coder_test_qa`, behaviour-smoke contract) plus `green_audit`'s open half. The table above also
lists `coder-test QA` as SOUND, which is true of its arithmetic and misleading in a row about
whether graders can be trusted — it is Python-only and cannot fire on a website at all (#1416).
And `calibration.py` and `jury.py` each carry a full lock but are **absent from the 15-entry
registry**, so two graders on the shipping surface sit outside this table entirely.]**

~~**Eleven of fifteen are sound or structurally immune. Three carry the defect. One was already
locked.**~~ The sound verdicts matter as much as the defects: `archetype_regression` turns out to
have been hardened against exactly this class by #1270 and says so in its own docstring, and the
craft-lint family already ships the toggle/seam/quiet trio this row would have asked for.

**And the two new defects are worse than `link_lint`'s, in different ways.**

`image_placement` (#1391) is the true #1231 shape with no analogy needed. An unparseable catalog is
skipped with `continue`, its items never enter the `items` population, and the only trace is a
`SEVERITY_LOW` finding — while `_HARD_SEVERITIES = {SEVERITY_HIGH}`, so it never sets `hard`. Ten
items all missing images in a well-formed file produce ten HIGH findings and a hard fail; the same
ten behind one JSON syntax error produce one LOW finding and vanish. **A guaranteed hard-fail
becomes an invisible non-event**, and a truncated write is enough to trigger it.

`green_audit` (#1390) is not a ratio at all and is the more serious of the two, because it is the
instrument whose entire job is catching a coder gaming the gates. A first-party `.py` over
`_MAX_FILE_BYTES` (512 KiB) is skipped at `green_audit.py:648-650` **without incrementing
`files_scanned` and without any disclosure field existing to record it** — so it is unscanned,
uncounted and unmentioned, and `gamed` reads `False` on a tree that is gamed. Padding a file with a
comment blob is the whole attack.

***TWO MORE LOCKS, later the same evening.*** The audit flagged one risk the instruments
DISCLOSE but nothing asserted: `security` (`_MAX_FILES = 800`) and `placeholder_prose`
(`_MAX_FILES = 400`) both truncate their file list on a large repo, so `measured=True` with a
CLEAN headline can coexist with a credential — or placeholder copy — sitting in the file past the
cap. Disclosure in `status` is the entire defence, which makes the caveat load-bearing: if it ever
stops being emitted, a partial scan becomes indistinguishable from a complete one. Four tests now
hold it, two per instrument: a capped scan must name its bound AND still read clean (the pairing is
the point — clean and capped are true together, so the caveat is all that stands between the result
and a clean it did not earn), plus the toggle proving an uncapped scan does NOT claim partial
coverage. Both were locked in the same change, because finding the risk in one and fixing only that
one is the half-fix lesson 342 exists for.

**Five reconciliation locks now stand** — `oracle_mutation` (#1231), traceability, the shared
`corpus_block` rollup (which holds the three craft lints and the archetype probe), `security`, and
`placeholder_prose`. The craft lints additionally carry their own toggle/seam/quiet trio, found
during the audit rather than written for it.

**Status stays PARTIAL and the reason has changed completely.** It is no longer "every other grader
is UNKNOWN" — every grader now has a verdict. What remains is that only two of the eleven sound
ones are *held* by a lock (`oracle_mutation`, traceability); an audit is a snapshot, and a grader
that is right today is one refactor from being wrong. The remaining locks are TEST-only work that
needs no quiet battery night; the three defect fixes touch instruments on the battery's execution
path and wait for it.

### 14. Every gate is proven to fail — the standard we hold the coder to

Capability 4 rightly demands the coder's exams be able to fail. **We apply no such rule to our
own.** In one session on 2026-08-07: two new locks passed for the wrong reason and only mutation
caught them; a pre-existing test asserted `mutation_audit == "run"` for a run that reached NO
mutants (the defect written down as expected behaviour); and a live code path had no test at all,
so deleting its logic left the suite green. `CLAUDE.md` security_by_design principle 12 already
requires every control to ship with proof it fails when disengaged — it is not a coder capability
and it is not enforced. DONE means: a lock that has never been seen to fail is not a lock, and
the proof has a CADENCE — a control proven to fail once can still be edited into silence later
(the overhaul programme's #1142 case: a README-marker lint neutralised by a seed-text change,
"the band-A reading recorded a detector that stopped detecting"); periodic planted-defect CANARY
deliveries through the REAL pipeline re-prove the whole gate chain, which a one-time proof
cannot.
**Status: PARTIAL as of 2026-08-09 — the RECORD exists and is enforced; the CADENCE does not.
Re-measured, because this row read UNKNOWN while the mechanism it asks for was already live.**

`shared/instrument_registry.py` carries **15 instruments** (13 until 2026-08-09; `link_lint`
and `image_placement` were brought under its teeth the same morning this row was re-measured,
`e98cac79`), and for each one the proven-to-fail
pair is a REQUIRED, RESOLVED field — not a convention. It goes further than principle 12 asks,
naming THREE cases rather than two: a `toggle_test` (a renderer refuses to report clean over an
unmeasured result), a `seam_test` (the REAL entrypoint, driven for real, RETURNS unmeasured —
it may not construct the result type, because that is where mocks lie), and a `quiet_test` (the
instrument does NOT convict a healthy input, because a control that fires on correct
configurations gets muted). `test_instrument_registry` fails if any named test is renamed or
deleted, and `unclaimed_reads` surfaces BY NAME any unregistered grader wired into a registered
renderer — so a new gate's choice is "register it or argue why it is not an instrument", never
"nobody noticed". 143 tests, in `tests/security/`, inside the standing gate. Verified passing
2026-08-09.

So *"no gate has a systematic proven-to-fail record"* was false when written or has been false
since; either way this row was sending readers to build something that exists. The same failure
mode as an index line understating its own repo — and worth more than the correction, because a
DoD row that undersells the system is as misleading as one that oversells it.

**What is genuinely still missing, and it is the harder half.** The row asks for a CADENCE: *"a
control proven to fail once can still be edited into silence later"* (#1142 — a README-marker
lint neutralised by a seed-text change, so *"the band-A reading recorded a detector that stopped
detecting"*). The registry proves each control could fail **at the moment its test was
written**. Nothing re-proves the chain since. Periodic planted-defect CANARY deliveries through
the REAL pipeline are unbuilt, and no instrument shipped 2026-08-08 (`link_lint`,
`image_placement`) is registered yet — both carry toggle-proofs, neither is under the registry's
teeth — **closed the same morning**: both registered as `STATUS_PREDICATE` over a dict
result, verified by mutating production code 11 times and confirming all 11 caught. The gate
fought that registration once and won: it requires every registered renderer to CALL the
status predicate, and four were re-deriving the field inline. The renderers changed, not the
gate.

**A SWEEP, 2026-08-10 — counting what each instrument has actually done, across 256 banked runs.**
This row asks whether a lock has ever been seen to fail. The cheapest first pass is to ask whether
it has ever been seen to *fire at all*, which is a division over artifacts already on disk:

| artifact | runs producing it | ever non-clean | rate |
|---|---|---|---|
| `oracle-qa.json` | 89 | 20 | 22% |
| `import-probe-verdict.json` | 69 | **11** | 16% |
| `decompose-diagnostics.json` (`degraded`) | 105 | **0** | 0% |
| `oracle-flake.json` (non-`confirmed`) | 11 | **0** | 0% |

*(CORRECTED 2026-08-14, and one row of it was not a drifted denominator but a false claim. This
table read `import-probe-verdict.json | 68 | 0 | 0%`, and the paragraph below it said "the import
probe has returned a clean verdict 68 consecutive times." **It has returned a NON-clean verdict 11
times.** Re-measured directly: 69 records, 58 `ok:true`, 11 `ok:false`, every one of the 11
carrying real unresolved module names — `app.word_frequencies`, `flashcard_app`, `app.card_entry`,
`app.quiz_engine`, `app.score_tracker` — across runs dated 2026-07-12 to 2026-08-05. So the import
probe does not belong on this row's never-fired candidate list at all; it is the second
demonstrably-alive instrument in the table, and putting it on the starved list was this row making
the error it exists to catch. The other two figures moved by denominator drift only and their
zeroes hold: `decompose-diagnostics` is 105 runs with `degraded:false` in all 105, and all 11
`oracle-flake` records read `confirmed`.)*

`oracle-qa` and the import probe are both demonstrably alive. **The decomposition diagnostic has
never once reported `degraded` in 105 runs, and no `oracle-flake` record has ever read anything but
`confirmed` in 11.** Neither is a defect claim — a gate that never fires may simply be guarding
something that never happens, and that is the honest reading until a *negative* control says
otherwise (lesson 222: a positive control catches false red, only a negative control catches false
green). Those two are this row's candidate list, with real denominators, which is what it has
lacked.

**And the denominator lesson, which I got wrong twice on the way to it.** `link-lint.json` appears
in **1 of 256 runs**, which reads as an inert instrument. It is not. It runs once per RUN at the
wave-final floor, not per task — so its denominator is *runs that reached the floor*, of which
there have been **2** since it shipped on 2026-08-08. Its record is 1 of 2, and the run that
missed it predates the merge.

The real finding is that second number. **In the three days since `link_lint` shipped, the fleet
has reached the wave-final floor exactly twice.** Every instrument that only runs at the end of a
complete delivery — the link check, the media-placement check, the executability floor, the job
oracle's final grade — is starved by the same scarcity, and that is a large part of why rows in
this document keep reading UNKNOWN. It is not that the instruments are missing; it is that
*complete runs* are the scarce resource, and an end-of-run instrument inherits that scarcity.

Two consequences worth stating: a row that reads UNKNOWN should name whether the instrument is
absent or merely starved, because those need opposite work; and an instrument that runs per-task
buys measurement far faster than one that runs per-run, which is an argument for pushing checks
earlier when the check permits it.

### 15. The built product is EXERCISED, not just inspected

The LA asked for *"proper automated testing, including live visual and functional tests"*
(2026-08-06) and **no row above expresses it.** Capability 3 grades security by scanning;
capability 4 grades the exams. Nothing opens the thing. For a website that means: links resolve,
forms submit, the console is free of errors, the layout survives a phone width, and the page is
navigable by keyboard and screen reader. A site can pass every gate in this document and be
broken the moment it is opened. This capability names its isolation boundary at design time:
exercising a built site means EXECUTING untrusted code — the coder's own output — and where that
runs (guest VM, sandboxed browser context) is a security_by_design principle-9 decision made
before the first line, not after.
**2026-08-16 — FOUR OF THIS ROW'S FIVE CLAUSES WERE MEASURED IN ONE RUN, AND THE CONSOLE CLAUSE
CAUGHT A REAL DEFECT. The row does not move, because the fifth was not exercised.**
Run `20260816-134142-bd` (on-demand, `campaign-1410-witness-20260816`), harvested with
`tools/probes/harvest_run_evidence.py`:

| clause | measured | result |
|---|---|---|
| links resolve | yes | `link-lint.json` `checked: true` — 28 of 29 resolved, **0 broken**, 1 undecidable |
| console free of errors | yes | `errorCount: 2` — and see below |
| layout survives phone width | yes | no overflow at 390px |
| keyboard / screen reader | yes | `a11y.measured: true`, 0 findings |
| **forms submit** | **no** | `forms.formCount: 0` — **no form was found to exercise** |

**2026-08-16, later the same evening — THE FIFTH CLAUSE'S INSTRUMENT IS FIXED, AND THE ROW STILL
DOES NOT MOVE.** #1433, merged as `9880cd0` in `agentic-setup`. The `formCount: 0` above was never
a fact about the site: `assessForms` ran on the **entry page only**, before the multi-page sweep,
and its answer was published as a top-level field. `index.html` has no form; `contact.html` has
one. The check now runs on every page the sweep visits and publishes `pagesChecked`, so a measured
zero and an unchecked site stop rendering identically.

Replayed against the pinned 21:02 operator-review copy of this run's own delivery, served from a
scratch copy so neither that tree nor `~/projects` was touched:

```
before   "forms": {"measured":true, "formCount":0, "findings":[]}
after    "forms": {"measured":true, "pagesChecked":5, "pagesWithForms":1, "formCount":1,
                   "findings":[]}
         pages[contact.html].forms -> {"formCount":1, "loseDataUndecidable":1}
```

**Why the row still does not move, and this is the second honest part.** The first replay produced
a finding, and the finding was **wrong**: *"1 form(s) have neither an action nor a submit handler —
submitting reloads the page and throws the typed values away"*, against a form wired with
`form.addEventListener('submit', e => e.preventDefault())`. Both halves false. `assessForms`'s own
docstring had always said `addEventListener` is invisible to it; the rule never acted on its own
stated limitation, which was survivable only because it had never yet looked at a page with a form
on it. Running it per-page would have fired it on nearly every correctly-wired form in every web
run. So `wouldLoseData` now convicts only where `scriptCount == 0` — no script could have attached
a listener — and is otherwise counted as `loseDataUndecidable` and published.

**That leaves the clause measurable in COVERAGE and not in VERDICT.** The capture can now find
every form on a site and say how many pages it checked; it still cannot say whether those forms
submit, because it does not submit them and cannot see their listeners. #1434 is the instrument
that would decide it (CDP `DOMDebugger.getEventListeners`), against a fixture already on disk.
*"Forms submit"* remains unwitnessed — and it is now unwitnessed for a reason the record states
rather than one it hides behind a zero.

**The console clause earned its place.** The capture opened five pages against a live server and
found `SyntaxError: Unexpected token 'export'` in `enquiries.js`, so the contact form had no
working JavaScript at all. Banked on #1420.

~~The run's own design-fix cycle then removed the `export` statements and a re-capture showed the
error gone (`errorCount` 2 → 1, only a `favicon.ico` 404 left). That is the whole loop this row
exists for — build, exercise, find, fix, re-verify — closing inside one run.~~

**[RETRACTED 2026-08-16 22:15 — THE FIX NEVER LANDED, AND THE OPERATOR FOUND IT WITH HIS HANDS
BEFORE THIS DOCUMENT DID.]** He opened the delivered site, filled in the contact form, pressed
Send, and nothing happened. Verified on the delivered tree
(`state/operator-review/20260816-210245-battery-b9-pottery-site`): **`public/enquiries.js` still
carries 5 `export` statements** and `contact.html:81` still loads it as `<script src=…>` with no
`type="module"`. There is **exactly one** banked sidecar in the run directory and it reads
`errorCount: 2, hard: true`; **the re-capture showing 1 does not exist.**

The run's own log says why, in its own words:

```
FIX #1: the rebuilt app FAILED the verify gate; kept the prior merged version (not merged)
FIX #2: the rebuilt app FAILED the verify gate; kept the prior merged version (not merged)
FIX #3: the FIX pass produced no changes;      kept the prior merged version
RESULT: MERGED into your project - just open the app and try it.
```

**All three fix passes were discarded and the summary still said MERGED, just open the app and
try it.** That is the sentence he acted on. #1425 is the ticket for fix passes producing no
changes; this is its first witnessed instance, and it carries an extra defect that ticket does
not — the run's closing line reads as success directly beneath three failures.

**The lesson for this document, and it is the one it keeps paying for:** the retracted sentence
was written the same morning, from a re-capture nobody located in the run directory. It described
the loop this row exists to prove — *build, exercise, find, fix, re-verify* — closing for the
first time. It was the most satisfying possible result and it was not checked against the
delivered artifact. **A capture that finds a defect is not a loop that closes it**, and only
opening the site could tell the two apart.

**Why the row stays PARTIAL, and this is the honest part.** `forms.formCount: 0` on a site whose
contact page carries a form means the check RAN and found nothing to exercise — not that forms
submit. Measured-as-zero and exercised are different facts, and this document's whole discipline
is refusing to collapse them. *"Forms submit"* remains unwitnessed.

Two further caveats from the same artifact: `behavior.ok: false` (*"the primary action produced
no visible change when clicked"*, heuristic, not enforced), and the link check's own disclosure
that it verifies a target EXISTS and never that its content is correct — which is precisely the
gap the operator's own eyes filled on 2026-08-15 when he found the menu present but unstyled and
in the wrong place (#1343).

**Rarity, measured the same day:** this artifact pair has appeared in **5 of 58** (`link-lint`)
and **8 of 58** (`exec-smoke-web`) WEB runs — see #1431, whose first figures were wrong by a
six-fold denominator error and were corrected in place. So a run producing both is unusual, and
this row's evidence is scarce for reasons that are an INSTRUMENT problem, not a cadence one.

**Status: PARTIAL as of 2026-08-08 (#1345, `32a9ed1f`) — the LINKS half is measured. Every
`href`/`src` in a delivered site is now resolved against the root a server actually mounts
(`shared/fleet/link_lint.py`), wired into the per-build web floor and banked as
`link-lint.json`. It found, on the real delivered tree, the broken "View Details" link the
operator had found by hand — in both the `.js` and the inline-`<script>` copy. It is
ADVISORY, not blocking: a regression lock proves a broken site and a clean site produce
identical verdicts, because a new way for a build to fail is his ceremony, not a wiring
decision. ~~What is still UNKNOWN, and named rather than implied: forms are not submitted, the
console is read only by the existing CDP smoke tier, no phone-width layout check exists, and
nothing tests keyboard or screen-reader navigation.~~ **[SUPERSEDED 2026-08-15 — three of those
four shipped; see the correction directly below. Struck rather than deleted, because the sentence
is the evidence for how it went stale.]** A link check is the cheapest slice of
this row, not the row.**

**2026-08-15 — THE SENTENCE ABOVE IS FALSE, AND HAS BEEN SINCE 03:49 THIS MORNING.** Three of
the four things it says do not exist shipped in `agentic-setup/scripts/capture-web-cdp.mjs`
(`assessPhoneWidth:325`, `assessA11yBasics:371`, `assessForms:417`) — **each function's docstring
opens `/** DoD row 15:` and quotes this row's own clause back at it.** Measured across all six
banked `exec-smoke-web.png.console.json`: the five from 2026-07-21 to 08-11 do not carry the keys
at all, and `20260814-230237-bd` carries all three:

```
"phoneWidth": {"measured":true,"overflows":false,"overflowPx":0,"widthPx":401,"culprit":""}
"a11y":       {"measured":true,"findings":[]}
"forms":      {"measured":true,"formCount":0,"findings":[]}
"pagesRequested":6, "pagesVisited":6, "errorCount":0
```

**This is row 5's failure repeated exactly** — a status line denying an event that had already
happened, still standing because the row was re-verified by re-reading its own prose instead of
by looking for the artifact. Row 5 asserted "never observed" two days after the observation; this
row asserted "does not exist" the same day it shipped.

**The row does NOT move, and the limits are the reason — stated from source, not from the record:**

- **Forms are still not submitted, and that is deliberate**, not a gap. `assessForms`'s own
  docstring: *"it does NOT submit the form… Submitting is a side effect on someone else's
  software."* It is a DOM lint for two defects — no submit path, and no `action` with no handler.
  `formCount: 0` on the one run that has it, so **it has never yet had a form to look at.**
- **`a11y` is three DOM facts, not accessibility**: an `<img>` with no `alt` attribute at all, a
  control with no accessible name, and no `<h1>`. Its docstring names its own exclusions —
  contrast, focus-visible, tab order, ARIA, live regions.
- **All three are ADVISORY**, locked out of `computeHard` and toggle-proved that way. All three
  findings arrays are empty, so **not one of them has convicted yet.**

So the honest position is: four of this row's five slices now have an instrument and one execution
apiece, none has caught anything, and the form slice has never been exercised at all. That is a
large partial move and it is not LIVE. The cheapest way to make it mean something needs no coder
and no operator: replay `capture-web-cdp.mjs` over the nine archived site trees in
`state/operator-review/*/`, several of which have contact pages, so `formCount > 0` and the a11y
checks get a real population instead of one clean site.

**A PRIOR question this row never asked, measured 2026-08-10 (#1367): exercised — but WHICH
ARTIFACT?** On `20260810-012417-bd`, the first run in which B9 delivered all seven tasks, the
web floor recorded a **pass** — *"served + loaded + zero console errors"* — and the design
reviewer reported the app *"blank/unrendered … a single blue circle with the letter 'A' … no
indication of any of the required pages."* Both were describing `public/index.html`: **1033
bytes, mtime equal to the scaffold's own creation time, untouched by all seven tasks.** The six
pages that were built are `home.html`, `pieces.html`, `piece-detail.html`, `contact.html`,
`header.html` and `styles.css`. The reviewer was exactly right about the page it was shown and
silent about the product.

This is not only a gate defect. `src/server.js` serves `/` from `index.html`, so **the
operator's front door is the placeholder**, and the built pages disagree with each other about
where home is — the shared menu links `home.html` while three pages link `index.html`. Three
surfaces each behaved reasonably: the seed brief tells the coder *"your FIRST tool call should
be an EDIT to `public/index.html`"* (`fleet-lib.ps1:1747`), the decomposer asked for a task
called `create-home-page` and never named a file, and the capture walks a fixed list
(`capture-app.ps1:115`) whose first entry always exists in this scaffold. No two of them are
wrong; nothing reconciles them.

So this row gains a precondition that sits **above** links, forms, console and layout: *the
thing being exercised must be the thing that was built.* A pass over a scaffold placeholder is
the #1241 instrument-honesty shape at its purest — a partial result presented as whole, with an
honest-looking `pass` lending it credibility. A one-line check the run already has the data for
— *has any task modified the served entry point since the scaffold wrote it?* — turns this from
four gates passing into a loud failure.

**And the row's second precondition, which took three readings to get right.** The visual loop was
the **only** control in the run that noticed the product had no front door. It built a real home
page in the worktree — 1033-byte stub → **3221 bytes**, shared header, navigation pointing at
`home.html`, `pieces.html`, `contact.html` — and the vision model's own verdict is the proof: it
moved from *"blank/unrendered … a single blue circle with the letter 'A'"* to *"the menu items
'Home', 'Gallery', 'Contact' are not aligned with the logo."* You cannot critique alignment on a
placeholder.

**None of it shipped.** The delivered `public/index.html` is **1044 bytes**; the only commit that
ever touched it after the seed changed `<title>App</title>` to `<title>Pottery Studio</title>`.
The run's log says why, three times: *"visual FIX #N not applied: coder timed out on the FIX pass;
kept the prior merged version."* Not rejected by a gate — each fix pass hit a time bound and its
output was **discarded**, then the worktree was disposed with the changes uncommitted. Ninety-seven
minutes of dispatch, one changed title, and `RESULT: MERGED into your project` in the operator's
summary.

That is a second, independent violation of this row and of capability 8's *"parks honestly with
its work recoverable"*, tracked as **#1370**. The asymmetry is the defect: on the same run, a
bounded **base** candidate got *"work kept, the gate decides the merge"* and merged; a bounded
**fix** pass had its work deleted with no gate consulted. One path judges what a bounded agent
produced; the other assumes it produced nothing.

So item 1 above is necessary and not sufficient. The capture should resolve the visitor's entry
point **so the reviewer is told the truth about what it is looking at** and can wire rather than
rebuild — but even a correct entry point would have produced today's outcome, because the repair
it prompted was thrown away. And it argues strongly against weakening this loop: it is currently
the only safety net for a gap no deterministic gate covers, and it is being run in a mode where its
findings cannot land.

Related: capability 9 (he sees the seed, not the result), capability 1 (six pages exist and the
front door reached none of them), capability 12 (four gates passed this tree), and #1345, where
his own first look found three defects four gates had passed.

### 16. Every recorded measurement is reproducible

#1318 (2026-08-07): three recorded probes named image subjects that were never committed, so
results still being cited — including gate B evidence for the 35B consolidation decision — could
not be re-derived on any machine. Honest numbers, unverifiable. DONE means: a recorded result can
be re-run from the repository alone. Structural control shipped
(`tests/security/test_measurement_subjects.py`); the capability is stated here because the class
is wider than the one fix.
**Status: PARTIAL — the control is LIVE as of 2026-08-07 for the known class (#1318), and a
SECOND control shipped 2026-08-09 for the class that bit the same week.**

**2026-08-15 — THIS ROW'S TICKET CITATIONS DO NOT RESOLVE.** The tickets named here (#1355, #1385)
are unrelated to the enumerator ratchet this row describes — #1385 is the operator's Python-night
deferral, #1355 a computed-path instance. So the control is genuinely LIVE and ~~**no ticket tracks
it**~~ **[SUPERSEDED 2026-08-15 — see below]**, which means a regression would have no queue entry
to land on. Corrected under #1404.

**"No ticket tracks it" is UNPROVEN, not established** (2026-08-15). An independent check found
that the merge commit this row quotes carries a ticket number in its own branch name —
`fix/1383-link-lock-pinned-to-a-mutable-sandbox` — and **#1383 is open**. But #1383's DESCRIPTION
is about something else entirely: *"Five of agentic-setup's 63 verifiers are RED on main and
nobody is looking."* So the branch name says 1383 and the ticket body does not cover this control.

**Recorded as unresolved rather than corrected in either direction**, because both available
moves are wrong: asserting #1383 tracks this row on the strength of a branch name would repeat the
citation error the banner exists to fix, and leaving "no ticket tracks it" standing asserts an
absence that has now been challenged. What settles it is reading #1383's own history for whether
the link-lock work was folded into it — not another inference from a string.

`tests/security/test_measurement_subjects.py` covers a recorded probe naming subjects never
committed. `tests/security/test_evidence_is_immutable.py` (#1355) covers the opposite direction:
a TEST whose subject is a live working directory. No test may construct a path into
`~/projects/`, the coder fleet's working area, which every dispatch archives and recreates.

Written because the class bit twelve hours earlier. Three tests authored 2026-08-08 asserted
exact figures against the real delivered pottery site — the obvious subject, because it was the
tree in front of the author. They passed, and at 04:56 the next morning they were red on `main`
with nothing about the code under test changed: the overnight battery had rebuilt that
directory. Capability 16 committed by tests written to enforce it. Fixed by retargeting to a
dated `repos-archived/` snapshot whose findings are byte-identical.

Both false positives on the new gate's first run were fixed rather than allowlisted — test DATA
inside a function is not a subject, and the gate was matching its own text. Toggle-proved
against the verbatim line that broke.

**Still unknown:** mutable state reached by a computed path or an environment variable, and
every non-test surface. Two named classes have controls; the general property does not.

*(2026-08-14 — the computed-path half now has a real instance, and it is the one that matters.
`agentic-setup/scripts/verify-website-review-loop.ps1` pinned a check to the live B9 sandbox and
went red when a reboot-killed run left a different tree there; the file was byte-identical to
`HEAD`. Fixed hermetic in agentic `aa2a949`. Two things this row should record about it:*

***The control is BlarAI-only.** `test_evidence_is_immutable.py` walks `base.rglob("test_*.py")`.
agentic-setup's 63 `verify-*.ps1` have no equivalent (#1385).*

***And porting it would not have caught this one.** The gate matches path LITERALS —
`_MUTABLE_ROOTS = ("users/mrbla/projects", …)`. The offending check contained no such literal; it
reached the mutable root at runtime through `Get-WebsiteBuilds | Select -First 1`, a helper that
enumerates live sandboxes and archives together and returns the live one first. A literal-scanner
is blind to that in any language. So this is not a gap in coverage of the KNOWN class — it is the
first concrete example of the class this paragraph already calls unknown, and it says the general
property is not reachable by extending the literal scan.*

*The invariant that does hold regardless of language or path construction: a test's subject must
be immutable at the time the test runs. Detecting that from source is hard; detecting it from
BEHAVIOUR is not — a check whose result changes while nothing under test changed is the
observable, and it has fired twice this week.)*

**THIRD CONTROL SHIPPED 2026-08-14, and it is the behavioural one.** The root `conftest.py`
installs a CPython audit hook that sees every `open` and fails the RUN if any test reads
`~/projects/`. It does not parse code, so **it does not care how the path was produced** — literal,
helper return, environment variable, or assembled at runtime. That closes the half this row named
as unreachable by the literal scan, and it closes it for the reason the scan could not: reading is
what makes a subject load-bearing, so reading is what is watched.

Three properties worth recording, because each was a decision:

- **It reports at session end, not by raising inside the offending test.** A raise surfaces as an
  unrelated failure in whichever test happened to touch the tree; one collected report names every
  offender at once and cannot be mistaken for a flake.
- **The predicate is EXTRACTED** (`conftest.is_fleet_working_tree_path`) rather than buried in the
  hook closure, because principle 12 asks every control to prove it blocks — and a predicate that
  cannot be called cannot prove anything. Same reason `Get-BlockingRunOwner` was lifted out of the
  battery launcher the same day.
- **Its own toggle caught a fail-open in it on first run.** The predicate pre-filtered on the raw
  string for speed (`if "projects" not in path`) before a case-insensitive compare, so
  `C:\Users\mrbla\Projects\…` — Windows preserves case — never reached the check. A hole in a
  control is not worth a micro-optimisation, and the test that found it was written in the same
  change.

Measured cost: the full gate went 431.18 s → 439.57 s (+2%), with **zero violations across all
10,961 tests** — the correct starting state, since the literal offenders were already fixed.

**Still unknown after this:** mutable state reached through an environment variable that is not a
path, every non-test surface, and agentic-setup's 63 PowerShell verifiers, which no Python hook can
watch (#1385). Three named classes have controls now; the general property still does not.

### 17. The exam covers what was ASKED — requirement coverage

The overhaul programme (2026-07-30) called this **"the single largest gap against 'proper exams
and reviewers'"**: every GREEN to date has classified `GREEN-UNVERIFIED` with
`oracle_coverage=unknown` — a GREEN means *the oracle passed*, not *the deliverable does what was
asked*. Capability 4 measures whether the exam CAN FAIL (mutation adequacy); nothing in rows 1-16
measures whether it covers the requirements — a different axis, and the instrument for it has
since shipped (`green_quality/traceability.py`, the `GREEN-VERIFIED` classification, the
dashboard coverage card) while no capability row claims it, leaving #967/#1015 serving no
numbered capability. DONE means: every delivery carries a requirements→assertions coverage
figure, an `UNDECIDABLE` criterion blocks `GREEN-VERIFIED`, and the first `GREEN-VERIFIED` ever
stamped on a real run is a cited event.
**Status: PARTIAL as of 2026-08-14 — two of this row's three DONE clauses are met and one of
them was met before the row was written. The coverage figure is emitted on 10 runs; the
`UNDECIDABLE`-blocks-`GREEN-VERIFIED` rule is implemented, documented as a load-bearing invariant,
regression-locked, and has fired 10 times in production. Open: no run has ever stamped
`GREEN-VERIFIED` (0 of 31 artifacts), and the figure is emitted on 10 of 258 run directories
rather than on every delivery (#967, #1015, #1374).**

*(This row read `ARMED` from ratification until 2026-08-14, and the paragraphs below explain at
length why it could not move. Two of the load-bearing sentences in them were false. They are
corrected in place and the correction is recorded at the end of the row, because the reasoning
that produced them is worth keeping: it is a clean example of diagnosing an instrument by
reading one of its two artifacts.)*

**2026-08-10: the reason for the permanent zero is now IDENTIFIED and FIXED, and the status
still does not move.** Both halves matter.

The complete seven-task delivery of `20260810-012417-bd` produced no artifact from **the
incumbent map** — `oracle-qa.json` carries `coverage_map: false`, `oracle_coverage: "unknown"`
and the honest `not_measured` line *"no requirement-to-assertion map was built, so which of the
operator's requirements this exam covers is unknown"*. I filed that (#1374) as the instrument not
being on the path a real run takes. **That was wrong.** The incumbent map
(`oracle_qa.request_coverage_map`, #821) is wired and does run, from the audit loop at
`oracle_qa.py:1710`. The defect was the line above it:

```python
if test_criteria and not any(f.hard for f in findings):   # <- the coverage map's gate
```

`CLASS_ADEQUACY_FLOOR` is in `_HARD_CLASSES`, and every B9 run reports `adequacy_floor: 2`. So the
map was skipped, `coverage_denominator` stayed 0, `stage_measured()[coverage_map]` reported False,
and the artifact said *not measured* — honestly. The instrument was never absent; its precondition
was no longer being satisfied.

*(CORRECTION, 2026-08-14. That sentence read "skipped on **every run that has ever happened**",
and it is false. Measured across all 89 `oracle-qa.json` records: 75 carry `oracle_coverage:
"unknown"`, but **14 carry a real figure** — `7/8` on four runs and `0/6` on ten — every one of
them a Python job dated between 2026-07-12 and 2026-07-22. The stage ledger did not exist then;
it arrived with the #1342/#1350 honesty work, and on all 8 records that carry one, `coverage_map`
is `false`. So this is a REGRESSION with a date, not a capability that never worked. The map ran,
produced real requirement-coverage figures including a `7/8`, and then stopped — because the
`adequacy_floor` gate began refusing it. That changes what #1374 is: restoring a measurement the
fleet used to take, against a known-good baseline to compare the restored figure to, rather than
standing up something unproven. Reading a long run of zeroes as "never" is the same error this
document exists to catch, committed by the document.)*

The guard was right for the classes it was written against — you cannot trace assertions through
an oracle that will not collect, whose strategy is ill-posed, or that blocks on stdin. It was
wrong to include the two classes that mean the exam is **thin** rather than **broken**:
`adequacy_floor` and `f2p_vacuous` parse fine, and a thin exam is exactly when *which requirement
did nobody assert?* is most worth asking. That is capability 4's failure (#1342) and this row's
failure being the same event seen from two sides.

Fixed by gating on what a finding MEANS rather than its severity (`_COVERAGE_BLOCKING_CLASSES`).
Both classes stay HARD — the oracle is still refused; only the map is now built. **Toggle-proved,
and the two answers are this row's whole subject:**

| | coverage |
|---|---|
| with the fix | **`0/1`** — MEASURED: the exam covers none of the operator's criteria |
| without it | **`unknown`** — not measured; nobody looked |

**Why ARMED and not PARTIAL.** No run has stamped anything yet. The row moves when a real run
emits a real figure, not when the code that could emit one merges — which is capability 11's rule
applied to this row rather than argued around.

*(CORRECTION, 2026-08-14 — this heading's own verdict is superseded, and by capability 11's rule
rather than around it. Applied honestly, the rule moves this row UP. It asks whether a stated
observable has executed, and the row states three:*

*1. **"every delivery carries a requirements→assertions coverage figure"** — PARTIAL. Ten runs
carry one from the second instrument (`traceability.json`, `available:true`) and fourteen carry
one from the incumbent map, the most recent being the two B9 deliveries at `oracle_coverage=0/6
L3+`. "Every delivery" is not met: 31 of 258 run directories bank a `traceability.json` at all.*

*2. **"an `UNDECIDABLE` criterion blocks `GREEN-VERIFIED`"** — MET, and met before this row was
written. `undecidable == 0` is a required conjunct of `TraceabilityResult.verified_class`
(`green_quality/traceability.py:1372-1379`), named in the module's honesty invariants as the
load-bearing clause — "an instrument that goes blind must produce a WORSE class, never a clean
one" — regression-locked at `tests/integration/test_oracle_traceability.py:1503` ("undecidable > 0
must keep GREEN-VERIFIED unreachable"), and **fired 10 times in production**: every run with
`available:true` has `undecidable:5` and `verified_class:false`. The clause is not waiting to be
built. It is working, and this row spent a week describing it as unbuilt.*

*3. **"the first `GREEN-VERIFIED` ever stamped on a real run is a cited event"** — OPEN. Zero, of
31 artifacts. This is the whole of what remains.*

*So: `PARTIAL`, one clause open. The reason the row read `ARMED` is worth naming, because it is
this document's own recurring failure mode: the row was graded on the single clause its author was
working on, and the two clauses that were already passing were never re-read. A row is not
measured by re-reading its status line. #1374 is amended accordingly — its description enumerates
the 08-10 run directory and names ten artifacts while omitting `traceability.json`, the one that
answers it.)*

*(CORRECTION, 2026-08-14. This sentence continued "and tonight's cannot: the battery runs from a
measured tree pinned before this landed." That described a ONE-NIGHT lag as if it were a standing
condition, and it is wrong: `run-battery-night.ps1:542` calls `Sync-MeasuredTree` against
`blarai-battery-measured` every night, so the pin is re-taken per run rather than frozen. Verified
by `merge-base --is-ancestor`: that tree already carries `b3a7ecd7` — this row's own coverage-gate
fix — along with `8cc5538a` and `37c98d56`. So the precondition this row has never once satisfied
is now satisfiable, and the next complete run can stamp a figure. Per the toggle table above the
two possible answers are `0/1` (MEASURED — the exam covers none of the operator's criteria) and
`unknown` (not measured). `0/1` would move this row; `unknown` would mean the map still is not
running and the diagnosis is incomplete. Caveat that keeps this honest: the run must get far enough
to grade at all — the battery banked nothing 08-11 through 08-14 (#1380), and a starved run stamps
nothing here either, which is capability 14's denominator lesson rather than an instrument result.)*

Two things stay open and are NOT addressed here: the `GREEN-VERIFIED` classification path is the
**second** instrument (`green_quality/traceability.py`), distinct from the incumbent map fixed
above, and an `UNDECIDABLE` criterion blocking `GREEN-VERIFIED` is a quality-posture flip that is
the LA's call. Tracked on #1374.

### 18. The product's media content is generated, placed and graded

The operator's stated goal includes *"proper image, voice, narration, and animation generation as
content for websites."* Capability 10 covers WORDS and waves media to "the roadmap" with no
observable — a named goal clause with no row. The generators exist elsewhere in BlarAI (UC-010
image generation, voice). DONE means: the media a site needs is planned at intake, produced
through the pipeline (or its absence recorded as a decision), and graded like any other
deliverable — a pottery site with an empty gallery or placeholder images is reported, not banded
clean.
**Status: PARTIAL as of 2026-08-09 — two of the three clauses are met. Re-measured; "the
pipeline path does not [exist]" was false, and the row was the last UNKNOWN standing.**

**PRODUCED through the pipeline — YES, and it is not new.** The Assistant Orchestrator generates
dispatch assets before the model swap (`_generate_one_dispatch_asset`, SEAM A) and writes them
straight into the delivered repository. From real battery logs:

```
dispatch assets: wrote public/assets/bowl.png (2200016 bytes) into battery-b9-pottery-site
dispatch assets: wrote public/assets/mug.png  (1841482 bytes) into battery-b9-pottery-site
dispatch assets: wrote public/assets/vase.png (1985797 bytes) into battery-b9-pottery-site
dispatch assets: wrote public/assets/hero.png  (951058 bytes) into battery-b5-habit-web
```

Two different cards, real bytes, in `public/assets/` where the pages reference them. Generation
is fail-soft by design: *"dispatch assets: unexpected error (Fail-Soft, swap proceeds)"* — a
picture that cannot be made never costs the dispatch. Measured cost: **59.9 s/image** on this
hardware (`docs/performance/uc010_dispatch_asset_gen_2026-06-30.json`, 30 steps, Arc 140V).

**GRADED — YES as of 2026-08-08 (`74257ce7`).** `shared/fleet/image_placement.py` grades
placement: one asset serving three or more products, an item whose declared image names no file,
generated assets nothing references, and page furniture worn as a product photograph. Registered
under `shared/instrument_registry.py` on 2026-08-09 (`e98cac79`) with toggle, seam and quiet
tests. Against the delivery the operator reviewed it reproduces both of his complaints in his own
terms. **Advisory, not blocking** — a media finding does not move a verdict, and a lock proves it.

**PLANNED AT INTAKE — NO, and this is the open clause.** The asset specs reach the generator
already formed; nothing asks the operator what pictures his site needs. Capability 2 records the
same gap from the other side: #1165's **M2** (the interview's assets question) and **M6**
(reference emulation) are unbuilt, and `assets/reference/` is read by nothing. `recipe-site` is
the evidence — 29 of his own photographs sitting in the intake folder the scaffold told him to
fill, for a site that was never built.

**Also unmet: "or its absence recorded as a decision."** A site that generates no media at all is
reported by the grader as *nothing to grade* — honest about the measurement, silent about whether
anyone chose it. And the row's own worked example is only half-covered: an empty gallery is now
caught, while *placeholder* images are not, because nothing opens an image.

**Voice, narration and animation: entirely unmeasured.** This row's status speaks to IMAGES only.

### 19. Candidate count scales with difficulty

*"Proper multiple candidates based on how difficult"* (LA, 2026-08-06) appears nowhere in rows
1-16. DONE means: the dispatcher chooses HOW MANY independent candidates to build from the
declared or measured difficulty of the task, the choice and its reason are recorded on the run,
and hard tasks demonstrably get more attempts than trivial ones.
**Status: PARTIAL as of 2026-08-09 — the MECHANISM is live and predates this row; the
DEMONSTRATION is not. Re-measured, because UNKNOWN was understating the repo.**

**2026-08-15 — THE FIGURES BELOW DID NOT RECONCILE, AND ARE NOW RE-DERIVED.** This row stated
"580 of 618", above a table summing to 547, above a paragraph saying 546 — three numbers for one
quantity. Re-measured across `state/fleet-runs/*/run-fleet-*.log` today: **553 lines carrying a
label and both budgets, across 624 logs** — `moderate` 319, `simple` (up to 2) 233, `simple`
(up to 5) 1, `complex` **0**. The substantive finding is untouched and is the point of the row:
**`complex` has still never once been emitted.** The stale trio is recorded rather than quietly
replaced, because a document that silently corrects its own arithmetic teaches nobody why it was
wrong: the counts were taken at three moments and never reconciled against each other.

`agentic-setup/scripts/fleet-lib.ps1::Resolve-PassBudget` already maps a coarse difficulty
label onto the build-pass budget, which IS the best-of-N candidate count:

```
simple   -> 2 build / 1 review
moderate -> 3 build / 2 review
complex  -> 8 build / 3 review
```

Its own comment records the provenance: *"complex BUILD raised 5→8 on 2026-06-27, LA decision:
more total best-of-N shots at hard tasks … Sampling is near-free locally; best-of-N coverage is
the weak-model bottleneck."* A staged desktop-GUI surface floors BUILD at 5 regardless of label.
An absent or unrecognised label keeps the caller's defaults, so the signal is backward
compatible. `Add-ComplexityHint` additionally tells the coder the assessment *before pass 1*, as
a calibration signal that never prescribes an implementation.

The label is a SIGNAL from the upstream 14B, deliberately not a pass count — *"it is NOT a
coder, so it sends a signal, never a pass count. The SYSTEM maps that label"* — which is the
right split and worth preserving.

**Recorded, partially.** A run's own JSON carries `"complexity": "moderate"` (verified on
`20260807-195617-bd`), so the REASON is on the run. The resolved budget — the choice itself —
is not: no run artifact records "8 build passes because complex". Half of this row's recording
clause is met.

**What is genuinely missing: the demonstration.** *"Hard tasks demonstrably get more attempts
than trivial ones"* has never been measured. Nothing compares candidate counts across
difficulty bands, and the sampler's own summary line only prints when a task's best-of-N loop
actually drew more than one (`swap_driver.py:704`), so absence of the line is ambiguous between
"drew one" and "did not report". Until a run banks the resolved budget beside the label, the
correlation cannot be computed from banked state at all.

*(MEASURED 2026-08-14 — two claims above are false, and the measurement they said was impossible
turns out to be the most useful thing this row has.*

***"No run artifact records the resolved budget" is false.** `run-fleet-*.log` is banked per run
and carries the label and BOTH budgets in one line, ~~**580 of 618 times**~~ **[SUPERSEDED
2026-08-15 — this figure never reconciled with its own table below, which sums to 547. Re-derived
that day as 553 across 624 logs; the correction is at the head of this row. The substantive
finding — `complex` has never once been emitted — is untouched by the arithmetic and was correct
throughout.]**:*

| recorded line | count |
|---|---|
| `moderate -> up to 3 candidate(s), review budget 2` | 313 |
| `simple -> up to 2 candidate(s), review budget 1` | 233 |
| `simple -> up to 5 candidate(s), review budget 1` | 1 — the staged-GUI floor, visibly firing |
| `complex -> up to 8 …` | **0** |

*(Table left at the counts it was taken with — 313 + 233 + 1 + 0 = 547, which is the whole point:
a total and its own breakdown disagreeing by 33 is what nobody noticed for a week.)*

***"The correlation cannot be computed from banked state at all" is false.** `candidate N of M`
is banked per draw, 694 occurrences. Joining the two across 546 tasks that carry both:*

| label | n | budget | **mean actual draws** | max drawn |
|---|---|---|---|---|
| `moderate` | 313 | 3 | **1.31** | 3 |
| `simple` | 233 | 2 (one at 5) | **1.18** | 3 |

*Budget-versus-actual-draws correlation over 543 tasks: **r = 0.150**.*

***And that number is the finding.** Hard tasks DO draw more than trivial ones — 1.31 against 1.18,
the right direction, no exceptions in the budgets themselves — but the effect is tiny, and the
budget barely predicts what actually happens. **The budget is a ceiling almost never approached.**
Best-of-N exits on the first green candidate, so a task whose first attempt satisfies the oracle
draws one candidate whatever its label says it may have. That reframes the row: the mechanism
scales the CEILING correctly and demonstrably, while the FLOOR is set by early-exit and is
identical across bands.*

***Which means raising `complex` to 8 buys nothing on its own.** More budget only becomes more
attempts when candidate 1 fails, and `complex` has never once been emitted in 618 logs — so the
top of the scale is unexercised AND, on this evidence, would be largely unspent if it fired. The
open question this row should now be asking is not "do hard tasks get more attempts" — that is
measured, and weakly yes — but **"is early-exit-on-first-green the right stopping rule when the
label says the task is hard?"** That is a quality decision with a real trade-off (sampling is
near-free locally; more draws cost wall-clock), and it belongs to the operator, not to this
document.*

***And then the label side, which is worse.** `complexity` is a GOAL-level value the 14B assesses
once and `_task_build_fields` copies onto every decomposed task (#674). Across all **223** banked
`acceptance.json`: **`simple` 103, `moderate` 108, `complex` 0**, plus 12 carrying no `build_plan`
at all. **The system has never judged any goal complex.** Checked directly on the last six B9 runs
— `20260809-194621-bd` through `20260811-232102-bd` — every one reads `complexity=moderate,
surface=web` against the operator's goal *"a proper little website for it, not just one page."*
His stated priority, "engineer a relatively complex website with multiple pages", is assessed by
the system as not complex; and it is the goal that has taken 17 from-scratch attempts without
converging.*

***A quieter defect in the same field:** `COMPLEXITY_DEFAULT = "moderate"` is the fail-closed
default AND a legal answer, so "the 14B said moderate" and "we could not read the 14B's answer"
are indistinguishable in the record. Twelve records with no `build_plan` become `moderate`
silently. That is capability 7's own subject sitting inside the field that decides how hard the
coder tries.*

***Status stays PARTIAL, deliberately, and the reason has changed.** All three DONE clauses now
have evidence, but clause 3's spans 2→3 candidates rather than 2→8, the measured effect is 0.13 of
a draw, and the top band has never been reachable in production. The honest reading is not that
this row is under-exercised — it is that **the capability is inert end to end**: the labels never
reach `complex`, and even if they did, early-exit would leave the budget unspent. Those are one
problem, not two, and fixing either alone changes nothing. The stopping-rule half is a quality
decision for the operator (#1388); the label-calibration half is mine, and neither lands the night
after five dead ones, against a launcher that just changed, where the attribution would be
worthless (#740).)*

### 20. Decomposition is graded, not just performed

*"Proper decomposition"* has no row; its only trace today is a defect (#1279:
`DEFAULT_MAX_TASKS=8`, silent truncation — B9 was authored at 9 units and cut to 8 without
saying so). DONE means: the plan's task graph is sized by the goal rather than capped by a
constant, any truncation is LOUD, and a decomposition that produced an unbuildable or overlapping
task set is counted against the planner, not against the coder who inherited it.
**Status: PARTIAL as of 2026-08-09 — clause 3 has a mechanism, clause 1 is capped by
construction, and clause 2 is open BY AN EXPLICIT DECISION recorded in the code itself.**
Re-measured clause by clause, because UNKNOWN hid three different states.

**Clause 3 (charged to the planner) — has a mechanism.** `DECOMPOSE-DOWNGRADE` is a first-class
failure-taxonomy class, printed on every battery summary beside `ORACLE-DEFECT`,
`INTEGRATION-SEAM` and the rest. A decomposition fault has somewhere to land that is not the
coder's ledger. Never yet fired on a real run, so the mechanism is ARMED rather than exercised —
and that now has a denominator rather than being asserted: **`DECOMPOSE-DOWNGRADE: 0` in all 63
`battery-summary.json` that carry the field** (measured 2026-08-14; the class is printed even at
zero, which is why the denominator is knowable at all). It belongs on capability 14's candidate
list beside the two instruments that survived re-measurement there — but NOT beside
`import-probe-verdict`, which turned out to have fired 11 times and was removed from that list the
same day.

**The decision IS banked.** Each run writes `decompose-diagnostics.json`
(`decompose-decision/v1`): `mode` (`plan-graph` vs flat), `cleaned_task_count`, `task_slugs`,
`degraded`, and `flat_reason` — so a degradation to the flat queue is stated, not inferred.
Verified on `20260807-195617-bd`: `mode=plan-graph, cleaned_task_count=7, degraded=false`.

**Clause 2 (truncation is LOUD) — still open, and the code says so in its own words.** At
`decompose.py:1101` the cap's `break` carries:

> *"NOT FIXED HERE, and deliberately not half-fixed: `_ruler` is pure and has no logger, so
> saying it properly means returning the dropped count and threading it through both call sites
> into the decompose diagnostics and onto the operator's plan card. That is #1279, specified.
> What is NOT acceptable is a log line nobody reads standing in for it — the truncation has to
> become DATA, the way `regression_unmeasured` did, or it will keep being derivable and
> unstated."*

That is the correct call and the correct refusal to half-fix, and it means a truncated plan is
still only **derivable** (`coherent_tasks` exceeding `final_tasks`), never stated.

**Clause 1 (sized by the goal, not a constant) — not met, and it is the ceiling on the
operator's own stated priority.** `DEFAULT_MAX_TASKS = 8` still stands. B9 is authored to nine
units and expresses eight; its card says so. In the cap comment's words: *"a genuinely larger
site cannot be expressed in one plan at all, and until that is visible nobody can tell an
over-large ask from a weak build."* He asked for *"relatively complex websites with multiple
pages"* — this constant is where that ask currently stops.

### 21. Verdicts are stable — the "reliable" in the operator's own words

Promoted from this section's former "lower confidence" footnote. A grader that returns different
bands for the same delivery across runs makes every number in this document meaningless, and
nothing measures flake. DONE means: re-grading a fixed delivery N times yields the same band, the
flake rate is a published number, and a grader whose verdict flips is treated as a broken
instrument. (Capability 13's sibling: 13 checks the arithmetic, this checks the repeatability.)
**Status: PARTIAL as of 2026-08-14 — and the missing half is now MEASURED. Re-grading a fixed
delivery is stable (0 of 30, below). Re-RUNNING a fixed goal is not: the same 946-character goal,
run end to end eight times, produced three different terminal verdicts.**

**2026-08-15 — "EIGHT RUNS" STATES NO GROUPING RULE, AND TWO OTHER COUNTS FIT THE SAME WORDS.**
Under an explicit rule — run directories whose `journal.log` names the `b9-pottery` repo — there
are **11**, every one carrying both a `RUN-END` and an `acceptance.json`. A different reading of
"matching runs" yields 17. This row says eight and does not say how it counted, which is the
defect: a tally whose selection is unstated cannot be reproduced or challenged.
Separately, the row's *"no ticket exists"* clause is stale: **#1392 does.**

**2026-08-15, later the same day — THE DISTRIBUTION IS NOW RE-DERIVED, and the reason it was
deferred was half wrong.** The paragraph above declined to re-derive it, stating *"the verdict is
not in `acceptance.json`"*. True, and incomplete: **the verdict is in `scorecard.json`**, as
`verdict`, beside `job_acceptance.status` and `attribution`. So the distribution was derivable
from banked state the whole time. Re-derived under the same explicit rule above — 11 completed
runs, plus one in flight at the time of writing, all on a byte-identical goal
(`sha256[:16] = d525541909dbf1ae`, 12 of 12):

| terminal verdict | runs (of 11 completed) |
|---|---|
| `PARKED-HONEST` | **6** |
| `STALLED` | 2 |
| **`NO-SCORECARD`** | **2** |
| `GREEN` | 1 |

**SUPERSEDED by the third and fourth passes below — read those, not this paragraph.** Its figures
were derived under a grouping rule since found biased, and it is retained only because deleting a
wrong claim teaches nobody why it was wrong. Its two named runs are correctly classified below as
`finished-no-verdict`; its count of "two" is right for that bucket and wrong as a total.

**The new bucket is the finding.** Two completed runs — `20260807-174202-bd` and
`20260811-232102-bd` — produced **no scorecard at all**, and the eight-run table above has no
category that can hold them. A run that yields no verdict is the *most* unstable outcome
available, and counting only runs that produced a verdict removes exactly the failures this row
exists to count. That is this document's recurring defect — a denominator that excludes its own
failures — committed by the row about instrument reliability.

The same derivation carries the job-level grade, which is what every end-of-run instrument
divides by. Of the 9 runs that produced a scorecard: **`pending` 5, `failed` 2, `passed` 2** — so
on more than half of them **the job grade never resolved at all**. `attribution` splits **HARNESS
5 / BUILD 3, and one is EMPTY** (`20260807-195617-bd` carries `attribution: ""`) — 5 + 3 is 8, not
9, and an earlier draft of this paragraph presented the two named buckets as if they covered all
nine. A blank attribution is its own outcome and is not evidence about the harness or the coder.
On the eight that carry one, most of this instability is the machinery around the coder rather
than the coder's own output.

**2026-08-15, third pass — THE SELECTION ABOVE IS BIASED, AND THE BIAS RUNS TOWARD THE THING BEING
MEASURED.** An independent auditor re-derived the group by hashing `acceptance.json` `spec.goal`
instead of grepping `journal.log`, and found **18 runs, not 12.**

Selecting on `journal.log` naming the repo **conditions on the run having survived long enough to
write and keep a journal**, which is itself a partial success. When a run dies to an unclean
shutdown the reaper RENAMES the file — `20260810-230238-bd` carries `journal.log.reaped-20260811`
and a `REAPED.txt` reading *"KILLED by an unclean machine shutdown at 09:27 on 2026-08-11,
mid-task, during its design-fix cycle… it never wrote its final TASK-END"*. That is a **full
seven-task attempt with 33 files**, and the journal-keyed rule cannot see it. A tally counting
instability was dropping its worst cases *because* they were its worst cases.

Re-keyed on the goal — which is fixed by construction and cannot correlate with the outcome:

| fate | runs |
|---|---|
| produced a verdict | **9** — `GREEN` 1, `PARKED-HONEST` 6, `STALLED` 2 |
| died at launch (2 files) | **5** |
| **finished and produced NO verdict** | **2** |
| **reaped** (ran to near the end, killed, no verdict) | **1** |
| in flight at time of writing | **1** |
| **total attempts on the identical goal** | **18** |

***(Fourth pass, corrected the same evening — the third pass had `in flight or unfinished: 3`
and that bucket was doing the same work the second pass's omission did.*** The classifier had no
end-of-run test, so **every** verdict-less run fell through to "unfinished" — and two of the three
had actually FINISHED, carrying `RUN-END` and `SUMMARY.txt`. *"Not done yet, no conclusion
available"* and *"ran to the end and produced nothing"* are opposite facts, and the first reads as
innocuous. **A denominator quietly excluding its own worst failures, reintroduced by the fix for
exactly that defect, within two hours.** Now keyed on `RUN-END` or `SUMMARY.txt`, either
sufficient, and locked with a toggle in `tests/integration/test_harvest_run_evidence.py`.)*

**So the honest reliability statement is: of 17 COMPLETED attempts at a byte-identical goal, one
produced GREEN, and three ran to some length and produced no verdict at all.**

**The verdict-bearing distribution is rule-invariant** — `GREEN` 1 / `PARKED-HONEST` 6 /
`STALLED` 2 under both rules — so the finding above stands. What changes is the **rate**, and it
changes a lot: **one GREEN in eighteen attempts at a byte-identical goal**, not one in eleven.

Fates are reported separately rather than pooled, because a run that wrote two files at launch is
not evidence about a grader, and pooling it would overstate instability exactly as dropping the
reaped run understated it.

Derivation is reproducible from banked state alone and ships as a tool:
`tools/probes/harvest_run_evidence.py --across-runs <goal-sha16>` (`--list-goals` for the keys).
Locked by `tests/integration/test_harvest_run_evidence.py`, including a toggle proving that
disabling reaped-run detection makes the suite fail. No run required.

*(MEASURED 2026-08-14, and this is the first evidence this row has ever had for the half that
matters. The stability table below re-grades a FROZEN artifact — the right test for a grader, and
it passes. It says nothing about whether the SYSTEM is reliable, which is the operator's actual
word. That question needed a different measurement, and the banked state already contained it.*

***Eight runs of card B9, all against a byte-identical goal.** Every one of the eight
`acceptance.json` carries the same `spec.goal` — SHA-256 prefix `d525541909dbf1ae`, 946 characters,
identical text — so the input is fixed in the strongest form banked state can express.*

| terminal verdict | runs |
|---|---|
| `GREEN` | **1** |
| `PARKED-HONEST` | **5** |
| `STALLED` | **2** |

*Two of the eight (`20260809-194621-bd`, `20260809-230346-bd`) parked in 545 s and 963 s on the
first task, both logging "STOPPED: a /dispatch stop was observed mid-run" — an external
interruption, not a verdict. **Excluding those, six substantive end-to-end attempts remain**
(3,365 s to 28,801 s): **GREEN 1, PARKED-HONEST 3, STALLED 2.** Per-task outcomes vary too —
`create-home-page` merges in five of the six and parks in one; `integrate-styles` and
`create-piece-detail-page` flip between merged, parked and pending across runs. Each run begins
from a blank task slate, so this is attempt-to-attempt variance on identical input, not
accumulated progress.*

***And the planner is NOT the source, which is what makes the finding sharp.** All eight
`decompose-diagnostics.json` are a single signature: `mode=plan-graph`, `cleaned_task_count=7`,
`degraded=false`, and a byte-identical ordered slug list (`create-home-page`,
`create-contact-page`, `create-piece-list-page`, `create-piece-detail-page`,
`implement-header-menu`, `integrate-styles`, `acceptance-tests`). **Input fixed, plan fixed,
outcome spread across three verdicts.** The variance lives entirely in the build-and-review layer:
the coder's own sampling and the reviewer's verdict on it.*

***A correction to this row's framing while I am here.** `oracle-flake.json` is a DIFFERENT
instrument from the ten-times table below, and the row cites it only as a single data point. It is
the #829 flake differential (`swap_ops.py:2081-2141`): it fires only when a job oracle FAILS, then
re-runs that oracle ONCE in a hermetic subprocess to ask whether the failure was residue-driven.
Eleven records exist, 2026-07-13 to 08-10, and **all eleven read `verdict: confirmed`** — zero
flips. Verified deterministic-only from the code: `real_run_job_oracle` is pure subprocess test
execution with no model in the path, so it can catch a stale Hypothesis database or temp-dir
carryover and can never see model-driven nondeterminism. Which is precisely the variance the eight
B9 runs just exhibited.*

***So the row's own summary is now inverted from where it stood this morning.*** Grader
repeatability: measured, stable, 0 of 30. System repeatability: measured, **unstable — 3 terminal
verdicts from 6 identical attempts.** The second is the operator's word for what he wants, and it
is the one with no control, no published rate and no ticket. That is the honest state of
"reliable".)*

Re-graded a FIXED delivery ten times per instrument and compared outputs byte for byte.
Subject: `night-20260808-230002/repos-archived/battery-b9-pottery-site` (an archived snapshot,
chosen because nothing rewrites it — see capability 16).

| Instrument | Runs | Distinct outputs | Result |
|---|---|---|---|
| `shared.fleet.link_lint` | 10 | **1** | stable (`88f7df884aff3df8`) |
| `shared.fleet.image_placement` | 10 | **1** | stable (`01da19278b8217b6`) |
| `green_quality.traceability.assess_run` | 10 | **1** | stable |

**Flake rate over the measured set: 0 / 30.**

**What this does NOT measure, and it is the part that matters.** All three are deterministic
by construction — no model, no network, no wall-clock, no GPU. Finding them stable is close to
finding that arithmetic is stable; it is worth having as a floor, and it is not evidence about
the graders where flake would actually live. **Unmeasured: every model-driven judgement** — the
vision-language critique, the oracle author, the coder's own sampling, and any band that
depends on a timing budget. Those are the instruments a flipped verdict would come from, and
none of them is in the table above.

Also unmeasured: re-grading across a REBOOT or a different machine state. Ten runs in one
process on one warm box is the weakest form of repeatability. A grader that reads a cache, a
clock, or GPU availability could be byte-stable here and flip overnight.

So: the number is published, the method is repeatable from banked state, and the row stays
PARTIAL rather than LIVE because the measured set was chosen for being cheap, not for being
where the risk is.

### Status legend — ratified with capability 11

`LIVE` (observable executed end to end at least once, run cited, on the current instrument
version) · `ARMED` (configured and reachable; observable never executed) · `PARTIAL` (a named
subset executed) · `UNKNOWN` (unmeasured — legitimate and preferred over optimism) · `STOOD-DOWN`
(deliberately off; by whom and why) · modifier `UNVOUCHED` (the measurement exists but its
instrument was later found defective; re-derive before citing). One vocabulary, so "FLAGS LIVE",
"MOSTLY LIVE" and "armed and instructed" stop meaning whatever the row's author felt. Enforced
since ratification by `tests/security/test_coder_dod_grammar.py`, which parses every row against
this grammar and fails any `LIVE` lacking a dated citation — before which NOTHING machine-checked
this file (verified 2026-08-07: no size budget, no vocabulary scan, no freshness check).

### Goal-coverage map (ratified) — every clause of the operator's words, mapped or exposed

| Operator's clause (2026-08-06 + 2026-07-30) | Row |
|---|---|
| complex multi-page website | 8 (+#1279) |
| advanced interview / advanced intake | 2 |
| proper user-asset incorporation | 2 (sub-item; M2 unbuilt) |
| code seeds and/or local corpus | 6 — **seeds: amendment below** |
| research answers at the various steps | 6 (two steps of several) |
| image, voice, narration, animation as content | **row 18** |
| proper test authoring (+ reviews) | 4, 5 |
| proper test execution | 4 (known hole), 15 |
| multiple candidates by difficulty | **row 19** |
| proper decomposition | **row 20** |
| proper error handling | **amendment to 8 below** |
| coordinator reviews | 5, 9 |
| iterations until finished / parking / inspection+pickup | 8 |
| live visual and functional tests | 15 |
| working / secure python + websites | 1, 3 |
| **reliable**, robust | **row 21** |
| proper exams and reviewers | 4, 5, **17** |

### Amendments to rows 6 and 8 — ratified 2026-08-07 and applied in place

Row 6 now names code seeds and research-at-every-step; row 8 now names proper error handling.
The amended text lives in the rows themselves, above.

---

## What one complete delivery measured — run `20260810-012417-bd`, 2026-08-10

The first run in which B9 delivered **all seven decomposed tasks**, first dispatch each, plus an
eighth design-fix dispatch. Because status here changes only by measurement, a complete delivery
is the most evidence this document has ever had from a single night, and it is walked against the
rows here rather than left as an incident report.

**Read this as a coverage map, not a scorecard.** The rows it did not touch are named at the end,
and they are the more useful half.

### Rows this run MOVED

| row | before | after | what moved it |
|---|---|---|---|
| **8** — finishes across many runs | UNKNOWN | **PARTIAL** | eight `RUN-START`s under one id, `resume_done` 0→7, one `TASK-SKIP-DONE` where a later invocation read `done.txt` and declined to rebuild. The row's own text said these did not exist. |
| **15** — the product is EXERCISED | PARTIAL | **PARTIAL, with a precondition it did not previously state** | the web floor passed and the design reviewer reported "blank" — both describing `public/index.html`, the untouched scaffold stub, while six built pages sat beside it (#1367) |

### Rows this run gave EVIDENCE for without changing status

**Row 4 (exams must be able to fail) and row 13 (the graders are graded).** The job-acceptance
oracle was **refused before it could grade**: `oracle-qa.json` → `"verdict": "refuse"`,
`adequacy_floor: 2`. The system detected a defective exam and declined to seed it to the coder —
the machinery this row exists for, working, on a real delivery. Two honest qualifications, both
from the artifact itself: `findings_conclusive: false`, and `traceability_gap` is the one check
whose `findings_measured` flag is **false** — an absent measurement, named rather than counted as
clean. The refusal did not stop the oracle grading the final tree, where it failed; so the run
scored **PARKED-HONEST**, not GREEN, with `FALSE-DONE=0` and `interventions=0`.

**Row 21 (verdicts are stable).** `oracle-flake.json` → `"verdict": "confirmed"`: first run failed,
hermetic re-run failed, same evidence. A stable negative verdict, differentially confirmed. One
data point, and this row has had very few.

**Row 18 (media content is generated, placed and graded).** `image-placement.json` found a real
content defect at `severity: high` — *"3 different products all show the same picture
('assets/mug.png')"* — across 6 items with 3 distinct images. It also carries a six-line
`not_measured` list, including the load-bearing one: *"no image is ever opened: every judgement
about WHAT a picture shows is inferred from its file name."* The instrument is doing this row's
job and declaring its own blindness, which is what row 7 asks of every instrument.

**Row 19 (candidate count scales).** `Building candidate 1 of 3` — the mechanism authorized three
candidates for the design-fix task and needed one.

**Row 20 (decomposition is graded).** `decompose-diagnostics.json`: `mode=plan-graph`,
`cleaned_task_count=7`, `degraded=false`, `flat_reason=""`. A graded, non-degraded decomposition —
and at 7 units it passed **under** the `DEFAULT_MAX_TASKS=8` cap rather than testing it (#1279).

**Row 12 (escaped defects are counted).** Two new rows for the column, both from this run:
**#1367** — a site whose front door is the untouched scaffold placeholder passed four gates;
**#1370** — three visual-fix passes built the missing page, all three were discarded on a time
bound, the worktree was disposed with the work uncommitted, and the operator-facing summary said
`RESULT: MERGED into your project`. Both were found by scoring the run by hand, not by any gate.

### Rows this run did NOT measure, and that is the important list

* **Row 17 (requirement coverage)** — still **ARMED, now measured as unstamped**: the run
  directory contains no requirement-coverage artifact of any name. The instrument is shipped and
  reachable and no run has yet stamped it, including a complete delivery. That is the strongest
  available evidence that it is not wired into the path a real run takes.
* **Row 2 (advanced intake and interview)** — not exercised; this was a queued battery card, not
  an operator-driven dispatch, so nothing about the interview, playback or asset intake was
  touched.
* **Row 6 (local corpus)** — plan-time stood down; build-time armed and mute, unchanged.
* **Row 14 (every gate proven to fail)** — no toggle-proof cadence ran on this night.
* **Row 16 (measurements reproducible)** — no measurement from this run has been re-derived.
* **Rows 3, 5, 10, 11** — no new evidence either way.
* **The guest oracle** — `guest-not-run (non-python-oracle)`, so the isolation certificate is
  unavailable and `guest_oracle_agreement` records `guest-not-run: 1`. A node-language job cannot
  currently exercise that path at all.

### The one sentence this run adds to the document

A complete delivery is **not** the same as a working product. Seven tasks merged, every
deterministic gate passed, `FALSE-DONE=0`, and the operator opens the site to a placeholder that
says "App". Every row above was individually honest; the gap is that **nothing owns the question
"is the thing a visitor reaches the thing that was built?"** — which is why #1367 sits against
rows 1, 9, 12 and 15 at once rather than against any one of them.

## The single acceptance test

Everything above collapses to one thing the operator can do himself:

> **He runs an advanced dispatch on a real goal. The interview asks in plain language. The plan
> reflects what he said. The coder builds it. The exams could have failed and did not. Nothing in
> the report claims a measurement that was not taken. He reads the result and it is true.**

**Executed: NEVER** (as of 2026-08-07 — no operator-driven advanced dispatch has ever completed;
capability 2's evidence).

Until that has happened end to end, on a real goal, the coder is not done — regardless of how many
tickets are closed.

## The SECOND acceptance test — the one the website goal needs

The test above is a **one-dispatch** test, and it always was. It cannot express the operator's
stated priority (2026-08-06):

> *"my current priority is for it to be able to engineer relatively complex website with multiple
> pages … proper multiple iterations until a working finished product, proper parking of
> non-working product, proper inspection of parked product and picked up to iterate until
> completion … We don't need to one-shot websites any more."*

So it needs a second, and the first does not satisfy it no matter how many times it passes:

> **He asks for a real multi-page site. It does not finish in one run, and that is expected and
> fine. It parks honestly with the work kept. He looks at what exists, says what is wrong in his
> own words, and dispatches again. The next run continues rather than restarting. Across however
> many runs it takes, the site converges — and at every point he can see how much of it is built.
> At the end he opens it in a browser, uses it, and it is the site he asked for.**

**Executed: NEVER, and — measured 2026-08-14 — NOT EXECUTABLE ON THE BATTERY PATH AT ALL (#1381).**

This read *"no multi-run product has been attempted; the resume path does not exist, #1277"*, which
says the test is un-run. It is stronger than that: on the nightly battery it cannot be run.

`run-battery-night.ps1` archives the previous sandbox (`:1468`, a move) and force-removes every
worktree (`:1496-1503`, *"battery sandboxes are THROWAWAY"*) before `git init`-ing a fresh one —
and **archiving is the FIRST thing a night does**, so each run files away its predecessor's product
before it starts. Nothing reads `repos-archived/` as an INPUT: the sole consumer is
`review-website-lib.ps1:431`, the operator's viewing path. One writer, one reader, and the reader
is a human.

Measured on B9: **17 from-scratch attempts at the same site**, oscillating rather than converging.
The best `index.html` this card has ever produced (2,448 B) sits in an archive while the live tree
holds the 1,033 B scaffold stub; seven of the 17 produced no `public/` at all.

**This sits UPSTREAM of #1321.** That ticket is about the fleet having no resume path for a parked
task *within* a run. Even with it shipped, the battery would reseed at 23:00 and the resumed work
would have nothing to resume into. Note the irony the measurement exposes: the continuation
machinery already EXISTS and is exercised — `done.txt`, `done-reasons.txt`, `dispatches.txt`, with
a real `TASK-SKIP-DONE` where a later invocation read `done.txt` and declined to rebuild (see
capability 8). It is destroyed nightly along with the tree it describes. The system can resume;
the battery deletes what resumption would read.

Whether the nightly card should keep re-rolling from scratch (a capability sample — *how good is
one night's attempt*) or continue the previous night's tree (a convergence run — *can it finish a
product*) is an LA decision, because they measure different things and both are legitimate. What
is not legitimate is the present state, where the document claims the second and the system
performs the first.

**Nothing in the seven capabilities is sufficient for this**, and a system that scores DONE on all
seven can still fail it completely — which is precisely why it is written down separately rather
than folded into the first.

---

## What is NOT in scope here

Model choice and the 30B/14B question (#742, #923, #930); battery cadence and campaign design;
the coder's raw capability ceiling. This document is about whether the system around the coder is
honest and complete, not about how clever the model is.

---

## How to use this

- A ticket that does not advance a numbered capability above should say which one it serves, or be
  questioned.
- An agent brief should name the capability it is working toward, not just the task.
- A status here is only ever changed by a MEASUREMENT, with the measurement cited. `UNKNOWN` is a
  legitimate and preferred value over an optimistic one.
- Statuses speak the ratified legend — LIVE / ARMED / PARTIAL / UNKNOWN / STOOD-DOWN, modifier
  UNVOUCHED — and `tests/security/test_coder_dod_grammar.py` fails the gate when a status line
  leaves the vocabulary or a LIVE claim lacks a dated citation.
- Maintenance rules, ratified 2026-08-07 with the rest (#1325, disposition §5 items 3-6):
  statuses are RE-MEASURED at named events — the monthly retrospective, and before any go-live a
  row bears on — never on inspiration; a status cites its instrument AND its run artifact
  (start→finish, the test-governance stamp lesson); rows keep DONE-means + observable + current
  status + one lesson line, history lives on tickets, and corrections stay visible until
  re-measured; the goal-coverage map folds in each new operator goal statement when he makes one.
