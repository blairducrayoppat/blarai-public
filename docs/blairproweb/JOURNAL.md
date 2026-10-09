# blairproweb — build journal

**The effort:** get BlarAI to build Blair's personal website — the one that shows his
homelab work, his certifications, and his OpenVINO GenAI open-source contributions.

**Project folder:** `C:\Users\mrbla\projects\blairproweb`
**Started:** 2026-08-30
**Status:** BLOCKED on throughput. Attempts #1 and #2 both produced nothing; a clean-box measurement puts the coder at 0.80 tok/s against a 38.58 baseline (#1476). No page has been built yet.

---

## Why this journal exists

So that when this website turns out well or badly, it is possible to say **which part
did it**. Three different things are at work and they are easy to confuse:

| | What it is | What it contributes here |
|---|---|---|
| **BlarAI** | The local AI system on Blair's laptop. Its coder fleet writes the website. | The actual website code. |
| **Blair** | The Lead Architect. Non-technical by design. Owns the vision, the priorities, and what "good" means. | The direction, the real content, and the review that decides whether it is any good. |
| **Claude Code** | The AI development tool that builds *BlarAI itself*. Not part of BlarAI, never runs inside it. | Fixes to BlarAI's machinery when this effort exposes a defect. |

The distinction that matters most: **when the website is bad, it is not automatically
BlarAI's fault** — the fault may be in the machinery that feeds BlarAI the job, which is
Claude's work, or in the material and direction it was given, which is Blair's. Each
entry below separates the three.

### How to read an entry

Every entry records what was attempted, what came out, and then three lines — what
BlarAI did, what Blair did, what Claude did. Failures stay in. An entry that hides the
failure path is worth nothing later.

---

## Standing scorecard

Updated whenever an attempt completes. Empty until the first build runs.

| # | Date | Attempt | Outcome | Blair's verdict |
|---|---|---|---|---|
| 0 | 2026-08-30 | first dispatch, `advanced-website22` | **never started** — coverage gate refused the plan: the exam imported six `.mjs` modules no task built | — |
| 1 | 2026-08-30 | `20260830-225825-bd`, 7 tasks | **cancelled at 12 min**, PARKED-HONEST. The exam imported `.html` as ES modules (unrunnable) and its contract was instructing a ONE-PAGE goal to be built as six pages | — (nothing to look at) |
| 2 | 2026-08-31 | `20260831-003919-bd`, 8 tasks | **nothing built.** The coder read his content files correctly, then all 3 candidates were killed mid-write by the 600 s idle breaker — measured 0.80 tok/s vs a 38.58 baseline (#1476) | — (nothing to look at) |
| 3 | 2026-08-31 | `20260831-115814-bd`, 8 tasks | **nothing built.** Cancelled at 9 min. The prompt told the coder to EDIT `index.html` and, eleven lines earlier, not to touch it. It read the file and declined, 3× — correctly. Speed was fine (110–133 s/candidate, no watchdog kill) (#1479) | — (nothing to look at) |
| 4 | 2026-08-31 | `20260831-122757-bd`, 8 tasks | **nothing built.** Cancelled. The KV pool I had just shrunk held 21,845 tokens; the coder's session needed 20,214 and OVMS evicted it after one tool call. My regression, from sizing a cache on speed alone (`agentic-setup` `b844dc0`) | — (nothing to look at) |

**Baseline expectation, recorded before the first attempt so it cannot be revised
afterwards:** across every website-shaped build this fleet has ever attempted, **1 came
out fully clean in 46**. Of the builds Blair has opened himself, **not one** has been
recorded in this project's journals as acceptable to him — every single time he opened
one, he found real defects, and almost none had been flagged by any automatic check. A
good result here would be genuinely new, not a continuation of a trend.

---

### 2026-08-30 — Before the first build: the machinery could not have used his material

*Plain summary: Blair asked whether he could give the builder a photo of himself. The
answer turned out to be "the photo yes, his words no" — and that gap is the likely
reason previous websites came back describing a person who does not exist.*

**What was attempted.** Nothing was built. Blair started a dispatch (`/dispatch new
advanced Website22 | …`), answered the interview questions, and reached a plan awaiting
approval. Before approving, he asked whether he could hand it assets — a photo of
himself — and what else he should provide.

**What was found.** Tracing the path from the assets folder to the coder turned up
three things, in ascending order of importance.

1. **The `advanced` keyword never took effect.** It is only recognised as the first word
   after `/dispatch`. He typed it after `new`, so it was absorbed into the project name —
   which is why the folder was called `advanced-website22`. The same thing happened on
   8 August. The app's own "New Project" button never sends the keyword at all.
2. **The assets folder is scanned once, when the plan is written.** His plan had been
   written against an empty folder, so approving it would have built with nothing, and
   `/dispatch revise` would not have rescued it — it reuses the plan's existing (empty)
   inventory rather than rescanning.
3. **The coder was only ever told about images.** This is the one that matters. Files in
   the assets folder do physically reach the coder — the fleet commits the folder as a
   baseline before starting. But the only code that *names* those files into the coder's
   instructions listed five image extensions and nothing else. Every document, every
   video, every font an operator had ever placed there was committed into the coder's
   working copy and **never mentioned to it**. Meanwhile the plan card told Blair the
   build was "graded on actually using them."

   And the grading was worse than silent: the automatic check asserted that the provided
   filenames appear **in the page's markup** — which, aimed at a `bio.md`, demands the
   opposite of the right outcome. A link to a biography is not a biography. The check
   could have passed while the page was written about an invented stranger.

**Why this is the interesting finding.** Blair's recurring complaint about delivered
sites — that they contain a fabricated person — had been read as the coder being weak.
It was not. Nothing was carrying his words into the build, and the one instrument that
mentioned his files was checking for the wrong thing.

**What was changed** (all of it in BlarAI's machinery, none of it in the website):

- The coder is now told about three kinds of file, with different instructions for each:
  images are referenced, video and audio are embedded, and **documents are read** — with
  an explicit instruction to open them and use the words inside, overriding the standing
  "don't spend turns reading the existing tree" rule for those specific files. It also
  forbids the two observed failure shapes: linking a document instead of writing its
  content out, and inventing a biography for something the file already answers.
- Size limits raised at Blair's direction: **25 MB → 2 GB per file, 200 MB → 3 GB total,
  64 → 256 files**, and phone/camera video formats (`.mov`, `.m4v`, `.mkv`, `.avi`) added.
  Limits were kept rather than removed because the fleet commits that folder into the
  project's permanent git history before every build, and that history cannot be undone —
  an unbounded folder is an unbounded, unrecoverable repository, re-copied per build.
- The markup check now applies only to media. A documents-only folder gets no automatic
  markup check at all — because the honest assertion over a bio is that its *words* were
  used, which no filename check can make.
- The plan card now discloses the total size once it passes 64 MB, because approving the
  card is what commits those bytes.
- A pre-existing bug, found by running the code against Blair's real project folder
  instead of a test fixture: **every asset was being listed to the coder twice**, because
  `assets` and `Assets` are the same directory on Windows. The existing test suite could
  not see it — a duplicate still satisfies a "contains" check.
- The seeded note in `assets/reference/` stopped promising a feature that does not exist.
  It had been telling operators to put screenshots there to copy the look of; nothing
  reads that folder, and nothing will until that capability is built.

**Evidence.** BlarAI standing test gate: 11272 passed, 7 skipped, 133 deselected (481.93 s,
2026-08-30 21:49) — the 7 skips all name `AO loopback port 5001 is in use`, the documented
signature of Blair's app being open. Fleet-side verifier: 15 → 37 checks, all passing.
Commits `3925d3e` and `d772b52` in `agentic-setup`. Ticket #1469.

**Who did what**

- **BlarAI did:** nothing yet. It created the project folder and produced a plan; no
  website has been built. Its interview asked five sensible questions and its plan card
  correctly listed the assets it found — the card was honest, the pipeline behind it
  was not.
- **Blair did:** asked the question that exposed all of this. "Can I give it a photo?"
  is not a technical question, and it found a defect that three months of automated
  gates had not. He also set the size requirement and, when asked whether limits were
  needed at all, chose bounded-with-headroom over unbounded once the permanence cost was
  explained. He wrote nothing and reviewed nothing yet — the content is still ahead of him.
- **Claude did:** traced the corridor rather than trusting the plan card's wording,
  found the three defects, and shipped the fixes above. Also got the first answer wrong —
  told him to drop his photo and four written files in and dispatch, which would have
  produced a site built from the photo alone, and only caught it by verifying the claim
  before he acted on it. Wrote the four content templates now sitting in his assets
  folder.

**Next:** Blair fills in the `TODO_BLAIR:` lines in the four content files, adds a photo
and any footage, then dispatches with the keyword in the position that parses:
`/dispatch advanced blairproweb | <goal>`. That will be attempt #1, and the first real
test of whether any of tonight's work matters.

---

### 2026-08-30 (later) — The fix would have shipped his photo as a broken image

*Plain summary: an independent review of the morning's fix found that it handed the
coder a path guaranteed to fail, and the automatic check would have passed it anyway.*

The fix above was reviewed by a separate agent whose only job was to attack it, on the
rule that the author of a change cannot be the one who verifies it. It reproduced nine
defects by running the code rather than reading it. Three were bad enough to block.

**The worst one is the one that would have hurt.** A BlarAI web project serves the
`public/` folder **and nothing else** — a file anywhere else exists on disk and is a 404
in the browser. His photo goes in `assets/`, which is *outside* `public/`. The fix I
shipped that morning told the coder, for every file, *"the file is served from public/,
so the assets/... path resolves."* For his photograph that sentence is simply false, and
the seed's own instructions said the opposite two paragraphs earlier in the same prompt.

The coder would have written `<img src="assets/portrait.jpg">`, the browser would have
shown a broken image, and **the automatic check would have passed it** — because that
check only asks whether the filename appears in the markup, not whether the picture
loads. A green result, a broken page, and the only thing standing between him and that
outcome was a criterion he judges with his own eyes, which a plan revision is allowed to
delete.

That is the same shape as every previous complaint on this project: the instrument
reported success on something his eyes would have failed.

The other two blockers: **fonts** were graded but never mentioned to the coder — the
check demanded a font filename appear in the page while the coder was never told the
font existed, which is unpassable by construction. And the plan card and the coder's
instructions **named different files**: the card applies a strict filename rule and
reports the rest as skipped, the coder's list applied none, so the card would say *"5
files skipped, rename them"* about the exact five the coder was told to use. An
apostrophe was enough to trigger it — `Blair's CV.pdf`.

All nine are fixed, none deferred. The checks went 37 → **55**, green on both PowerShell
versions. Disposition record: `docs/reviews/operator-assets-large-media-disposition-2026-08-30.md`.

**Who did what**

- **BlarAI did:** still nothing — no build has run. It remains untested against any of this.
- **Blair did:** nothing in this round; he was not asked to. The value of his earlier
  question compounds though — none of these three defects would have been looked for if
  he had not asked whether he could hand it a photo.
- **Claude did:** wrote the defective fix, then commissioned the review that caught it,
  then fixed all nine. Worth recording plainly: the morning's version was verified green
  by its own 37 checks and by a live run against the real project folder, and it was still
  wrong in a way that would have produced exactly the failure this whole effort exists to
  stop. Passing your own tests is not the same as being correct, and the only reason this
  was caught before a build is that the review was independent.

**Next:** unchanged — the ball is with Blair. Fill in the content files, add a photo,
dispatch.

---

### 2026-08-30 (late) — The material arrives, and the 35 MB file proves the point

*Plain summary: Blair handed over his photographs, his credential, his logo and two videos;
the assets folder went from empty to fifteen files, and one of them could not have been
accepted twelve hours earlier.*

The folder now holds **fifteen files, 55.3 MB, nothing skipped**: three portraits, the
BlarAI logo, the IAPP badge, the NIST AI Risk Management Framework diagram, the GitHub and
Hugging Face marks, two videos, and six content documents.

**The proof point is `blarai-demo.mp4` at 35 MB.** The per-file cap this morning was 25 MB.
That file — a recording of the system this whole site exists to show off — would have been
silently skipped, counted in a "left out" line on the plan card, and never seen by the
coder. It is the first artifact that required tonight's change in order to exist in the
build at all, and it arrived within hours of the cap being raised. The 2 GB ceiling was
asked for speculatively; the need was immediate.

**The content stopped being invented.** The four documents I wrote at 21:23 were scaffolds
with `TODO_BLAIR:` markers — my guesses at what he might say. They have all been replaced
with material traced to a source: the bio from his own published profile text and his
cleared claims register; the credential from the signed W3C verifiable credential file
(awarded 2026-07-28, valid to 2028-07-31); the OpenVINO section from the live GitHub API.
**Not one `TODO_BLAIR:` marker survives.**

More useful than the content is what came with it. His campaign material carries a claims
register whose own rule is *"if a claim is not in this file, it is not cleared for
publication."* Reading it produced a list of things the site must **not** say, and several
would have been easy, natural errors: describing BlarAI as "compliant with" ISO/IEC 42001
when he holds the credential and the system does not; saying "OpenVINO contributor" when
the merged work is in the GenAI repository and the core-repo submissions were closed
unmerged; quoting "about 2×" for speculative decoding, a figure he walked back himself, in
place of the measured 1.48–1.68×; giving a WCAG conformance level that is not recoverable
from any document he holds. Each of those is now an explicit prohibition inside the content
files, where the coder will read it, rather than a note in a session that will end.

One upgrade the campaign material did not know about: PR #4082 **shipped in OpenVINO GenAI
2026.3.0.0 on 5 August**, credited by name. His register, last updated 18 August, still
recorded it only as merged. "Merged and shipped in a tagged release" is the stronger and
equally true claim.

**Who did what**

- **BlarAI did:** still nothing. Fifteen files are staged for it and no build has run.
- **Blair did:** supplied every piece of real material on the page — the photographs, the
  signed credential, the logo, the NIST diagram, the videos — and answered the one question
  that gated the certifications section. He also produced, months ago and for a different
  purpose, the claims register that is now the site's accuracy control.
- **Claude did:** verified each artifact before use rather than trusting the filename —
  opened the badge, parsed the credential, checked the PR against the live API, read the
  claims register for prohibitions. Fetched the GitHub and Hugging Face marks dev-side so
  the built page makes no runtime request. Wrote the content files as instructions the
  coder must follow, not prose it may paraphrase.

**Next:** `/dispatch advanced blairproweb | <goal>`. Attempt #1.

---

### 2026-08-30 — Attempt #1: the exam was writing the architecture

*Plain summary: the first real build was stopped twelve minutes in, because the test that
was supposed to grade the website was quietly instructing it to be six websites.*

**What was attempted.** Blair answered the interview, revised the plan once, approved, and
run `20260830-225825-bd` dispatched seven tasks to the coder fleet at 23:35.

**What went wrong, in two rounds.**

The first dispatch never started at all. The coverage gate refused approval: the exam the
model had written imported six `.mjs` modules that no task in the plan built, so a pass
would have meant nothing. That gate did its job and I was glad to see it — the honest
framing in its own message is that it declines to record a green it could not earn.

I tried to fix that by steering the exam's author through the goal text, telling it in
capital letters that this was a static website and the acceptance test must open the built
page rather than import source modules. **It complied with the letter and defeated the
intent.** It stopped importing `.mjs` and started importing `.html`:

    import { default as photoAndBio } from '../src/add-photo-and-bio-section/index.html';

Node cannot import an HTML file. `ERR_UNKNOWN_FILE_EXTENSION`, at load, before a single
assertion runs. I confirmed that in one command rather than reasoning about it.

**The part that made it worth stopping the run for.** An exam that always fails is a wasted
grade. This was worse. The run journal records that the oracle's import contract is
*"surfaced to every task"* — so every one of the seven coder tasks was being told the
finished product consists of six separate `src/<section>/index.html` files. Blair's goal said
ONE PAGE in capital letters. **The exam was not merely failing to measure the build; it was
writing it.** Letting it finish would not have produced a good site with a bad score, it
would have produced six fragments.

Cancelled at 23:38 by the sentinel the driver polls between tasks. Verdict PARKED-HONEST,
attribution HARNESS, all seven tasks ended.

**Two rolls, two unrunnable exams, different shapes. That is the signal.** One bad exam is
variance and you retry. The second one told me the author has no notion that a static
website's acceptance is *serve the page and look at it* — it reaches for module imports
because that is the only exam shape it knows, and prompt text moves which extension it picks
rather than whether it picks one. A third dispatch would have been a third roll of the same
dice.

**The root cause was not a hallucination.** The oracle imports what the tasks declare they
create, and the gate deciding whether a usable contract exists only asked whether
`creates`/`exports` was *non-empty* — never whether the named artifact was *importable*. A
static site's contracts name `.html`, and the oracle did exactly as it was told. The defect
was ours, in a check that had been asking an incomplete question since long before tonight.

**The fix (#1474, merged `e327297f`).** On node, a contract counts only if it declares
something Node can actually import. When nothing does, no exam is authored **and the model
is never even asked** — which is what stops the contract reaching the task prompts. Job
acceptance then reads `not-run`, which is never an implied pass, and the delivery is graded
by the instrument built for it: the browser check that loads the served page.

I deliberately did not write the blunter rule, "no job oracle for web goals." That would
have silenced genuine node web apps that do build modules, and a test now locks the
distinction. The narrow version was harder to argue for and is the one that will still be
right in six months.

One existing test broke and it deserved scrutiny, because changing a test to make a change
pass is exactly how a gate rots. It turned out to be the fixture: the test asserts that a web
surface routes to the node oracle, and it had been proving that with tasks declaring
`src/m0.py` — Python files, which no node job creates. The paths were incidental to its
assertion and my gate made them load-bearing. The assertion is untouched.

**Evidence.** Gate 11286 passed / 0 failed / **0 skipped** / 133 deselected — the night's
first clean-environment run, because Blair closed the app, so the pinned baseline is now
measured rather than derived. Seven new tests, three of them kill-strength.

**Who did what**

- **BlarAI did:** produced two plans and one twelve-minute build attempt, delivered nothing,
  and — through the coverage gate — correctly refused the first plan. It is still 0-for-1 on
  producing a page anyone has looked at.
- **Blair did:** answered the interview twice, caught my "not cute" as an assumption he had
  never made, and reframed the whole brief mid-session from *show my skills* to **build
  trust** — which is a better thesis and made his own accuracy constraints into the strategy
  rather than chores. He also asked the question that ended the retry loop: he did not ask
  for a third attempt.
- **Claude did:** wrote the goal text that produced the second broken exam, which is a fair
  thing to record — steering a model with words moved the symptom and I should have read the
  authoring path the first time rather than the second. Then found the real cause, fixed it
  narrowly, and stopped a run that would have burned hours to produce fragments.

**Next:** restart the launcher so the fix is live — a merged fix does nothing for the
operator while the process holds the old code — then attempt #2.

---

### 2026-08-31 — Attempt #2: it read his words, then died to a clock

*Plain summary: the fix worked and the build still failed — the machine is running roughly
fifty times slower than its own benchmark, and a watchdog cannot tell a slow writer from a
dead one.*

**What was attempted.** Run `20260831-003919-bd`, 8 tasks, dispatched 00:47 after the
launcher was restarted so the oracle fix was actually live. Stopped 01:47 with nothing
built.

**The fix worked, and the transcript proves it.** The coder's steps, in order: globbed
`assets/*`, read `bio.md`, read `what-this-site-must-do.md`, read `certifications.md`, read
`image-notes.md`, opened `index.html`. That is precisely the behaviour the #1469 content
block was written to produce — the coder reading Blair's real words instead of inventing a
person. Two nights ago it would have seen none of those files.

Then it went to write the page and produced nothing for ten minutes, and the circuit breaker
killed it as "genuinely stuck". All three candidates, the same way. Fifty-two minutes, zero
changes.

**It was not stuck.** A clean-box measurement afterwards — nothing else running, 7.3 GiB
free — put decode at **0.80 tok/s against a 38.58 tok/s baseline** taken on the same model,
same server, same flags, same machine. Roughly **48× slower**. At that rate a three-thousand
token page needs about an hour of unbroken generation, and a single long file write emits no
intermediate step, so the 600-second idle watchdog cannot distinguish it from a hang.

**Three things about that are worth keeping.**

The watchdog confusion is not new. `fleet-lib.ps1`'s own comment records a 120-second window
false-killing **84% of 30B candidates** before it was raised to 600. This is the same defect
recurring one threshold up, and the fix I would reach for first — raise it again — is wrong
without care: the registry enforces that outer doom windows (900 s) strictly exceed this
inner judge, and a gate test asserts it.

The error message named the wrong number. It printed *"no new step/edit for 240s"* while the
threshold that actually fired was 600, because the ACP path uses a different constant from
the one the message renders. That sent me to the wrong place first.

And **the cause of the slowness is not established.** Either my own OVMS version round-trip
tonight degraded the GPU state, or this has been true since June and nobody measured. I could
not separate them at two in the morning and did not want to guess — I had already been wrong
once tonight by arguing from a document instead of a measurement.

**Why the second possibility is the important one.** If the box has been running at a
fraction of its benchmark for two months, then the fleet's record — one clean website in
forty-six attempts — is partly a **speed** problem that has been read as a **quality**
problem. Every candidate racing a clock it cannot beat. That would change the reading of B9,
of the sixteen partial rows in the definition of done, and of much of the instrument-honesty
work. One reboot and one probe settles it, and that is worth doing before any more effort
goes into making the coder smarter.

**Who did what**

- **BlarAI did:** read the operator's real content for the first time, correctly, and then
  could not write fast enough to survive its own watchdog. Still 0-for-2 on producing a page
  anyone has looked at.
- **Blair did:** nothing was asked of him and nothing was his fault. He closed the app when
  asked, which incidentally produced the night's only clean-environment test gate.
- **Claude did:** shipped a fix that demonstrably worked, and quite possibly broke the
  machine it ran on. The OVMS round-trip — install 2026.3, measure, roll back, quarantine 33
  cache entries — is the leading suspect for the slowdown, and it was my idea to pursue it
  tonight rather than hand it to the research agent from the start. Recorded as #1476 with
  the evidence and the one experiment that settles it.

**Next:** reboot, re-run the probe. If throughput returns, attempt #3. If it does not, the
website waits and the throughput question becomes the priority, because nothing else about
the coder can be judged fairly until it is answered.

---

---

---

### 2026-08-31 — Attempts #3 and #4: we forbade the file we ordered written, then I starved the cache

*Plain summary: two more empty builds in one afternoon. The first was an instruction that
contradicted itself; the second was my own fix for yesterday's problem, which traded a speed
defect for a memory one.*

**Attempt #3 (`20260831-115814-bd`), cancelled at nine minutes.** The composed prompt handed to
`photo-bio-section` contained both of these, eleven lines apart:

> These files are contracted to OTHER tasks in this job and are NOT yours to create:
> `index.html`, `styles.css`. **Do NOT create, stub, or implement them.**

> **ACT FIRST — your FIRST tool call should be an EDIT to `index.html`.**

The coder read the file, declined to edit it, and reported no changes. Three times. The
transcript is one message and one `read` per attempt, 20,214 tokens of a 65,536 window — no
overflow, no error, no confusion. **It was not stuck, not slow, and not wrong. It obeyed the
instruction it was given, and the instruction was ours.**

Two surfaces compose that prompt and neither knows the other exists: `Add-WebStaticHint` in
agentic-setup emits the edit order, `_scope_ceiling` in BlarAI emits the ownership boundary.
Each is correct alone, each has passing tests, and nothing was ever asked to read the result as
one document. **The seam had no owner because both sides were right.**

Fixed in `cea13366`: on a single-page build the negative half is dropped, because there is one
file and every task must extend it. I wrote a broader fix first — *a task with no contract never
gets a bare prohibition* — and it broke a test that turned out to encode a real decision: on a
multi-file project a contract-less task genuinely is the unanchored over-producer and should be
fenced. The test was right and my generalisation was wrong. Keying the fix to the build shape
keeps that test passing untouched, which is both the evidence the fix is narrow and the toggle
proving the guard still fires elsewhere.

**Two corrections to what I first reported, because both would mislead.** I said "seven of eight
tasks were forbidden." Seven were *exposed* by the plan; the run *dispatched* one, which parked
after six no-change attempts while the rest never ran. And I cited `state/fleet-swap/plan.json`
as evidence — a single mutable file the next dispatch overwrites. Within the hour it held the
*next* run's plan, which has the opposite shape, so anyone auditing my report would have found a
plan that did not show the defect. It survived only because an independent reviewer had copied
it. That is now fixed at the root (`cda79147`): every run banks its own plan before anything
else can fail.

**Attempt #4 (`20260831-122757-bd`), and this one is mine.** Yesterday's coder was running at
~3 tok/s because the KV cache pool was 4 GB; I bisected it, found 1 GB gave 39 tok/s, shipped
that, and never probed what a 1 GB pool can *hold*. It holds 21,845 tokens. The coder's first
session used 20,214. OVMS's own log records the consequence — `cache usage: 100.0% of 1024.0 MB`,
then `All requests: 2; Scheduled requests: 1`, then a reset to 6.7%. The session was evicted
after one tool call and returned nothing, which the fleet reports as "produced no changes",
indistinguishable from a lazy model.

My own performance record for that fix has, under `not_measured`: *"the KV capacity ceiling at
cache_size 1 — the failure point was not probed."* **I shipped it with that box unticked and it
cost a dispatch.** A KV pool is a token ceiling, not a speed knob; tuning it on one axis while
the other goes unmeasured is how a fix ships a new defect.

Corrected to 2 GB (43,690 tokens) against a 40,960-token window, so the client compacts before
the server can evict. That pairing is load-bearing rather than tidy, because I also found — by
crashing it — that **OVMS does not refuse an over-large request, it dies**: process gone, empty
error log. Also found while there: the live coder config had drifted to a 64K window while the
tracked config said 32K, invisible for as long as a 4 GB pool could hold either.

**The trade underneath all of this is still unexplained.** In June this machine served 38.58
tok/s with a 4 GB pool. Today the same model, driver and GPU pool gives about 3. That single
regression is what forces the choice between memory and speed; solve it and no compromise is
needed. It is the next thing worth doing and it is open on #1477.

**Who did what**

- **BlarAI did:** planned both runs correctly, authored no exam either time, and built nothing —
  once because its own prompt contradicted itself, once because I had starved its cache.
- **Blair did:** caught me with both models resident when I had convinced myself I had stopped
  one, which was true and I had not verified it; rejected my offer to write the site by hand,
  correctly, because this is a validation exercise and a page I wrote would prove nothing; and
  pushed back on narrow, reactive fixing.
- **Claude did:** diagnosed both defects from the coder's own transcript and the server's own
  log rather than from the symptom, and shipped both fixes with locks. Also ran a benchmark into
  a live build, killed a process by the wrong name and measured without checking, crashed the
  server with a prompt I sized by guessing, and twice wrote kill filters that matched my own
  shell. Four self-inflicted failures in one afternoon, all the same root: acting on an assumed
  state instead of a verified one.

**Next:** attempt #5 on the corrected pool, watched from the first second. Then #1477 — why this
machine lost 13× since June.

---

### 2026-08-31 (evening) — What we actually learned: the instrument was the defect

*Plain summary: I spent an afternoon fixing a 13x slowdown, and the sustained measurement at
the end suggests the slowdown may never have existed in the work the coder actually does.*

Every throughput number this project had — including the 38.58 tok/s June baseline this whole
investigation was anchored to — came from `benchmark_ovms_http.py`, which generates **256-token
completions**. The coder sends ~7,000-token prompts and generates page-sized files. Nobody had
ever measured that.

When I finally did, with four consecutive realistic generations per configuration and
continuous resource sampling:

| config | median tok/s | drift across runs |
|---|---|---|
| `cache_size 2`, no offload (shipped) | 11.37 | **−9.7%** |
| `cache_size 1`, no offload | 12.61 | +6.3% |
| `cache_size 2` + offload 30 | 10.13 | +3.3% |

**The cliff I spent the afternoon explaining is an 11% spread under real load, not 1.9×.** And
today's short probe at `cache_size 1` measures 35.5 against June's 38.58 — within 8%. The
machine may not have regressed at all in the work we care about. What regressed is short-probe
throughput at large KV pools, which is a real effect and possibly an irrelevant one.

**Three things I asserted today and had to retract**, all for the same reason — I measured
something cheap and reported it as something expensive:

- The shared-GPU budget "is 15.66 GiB". I took it from a web article's 50%-of-RAM rule and
  labelled the conclusion ROOT CAUSE ESTABLISHED. Measured: **17.98 GiB**. Blair challenged the
  number; I had never checked it, and this project's own record already held a figure that
  contradicted it.
- MoE offloading "buys back throughput" — 24.7, 28.9, 30.5 tok/s. All 128-token probes. Under
  real load offload **costs** 11% and returns 3.3 GB of RAM. It is a memory lever, not a speed
  lever. I had written the caveat about per-token expert fetching in my own notes and then
  quoted the flattering number anyway.
- "Seven of eight tasks hit the prohibition." The plan exposed seven; the run dispatched one.

**The one finding that survived all of it** is structural rather than numeric: `cache_size 2`
runs at 18.04 GiB mean GPU-shared against a measured 17.98 GiB budget, and it is the only
configuration that *degrades* across consecutive runs. `cache_size 1` sits under the budget and
improves. The budget is real and it shows up as **drift**, not as a headline number — which is
exactly the thing a single snapshot can never see.

**Who did what**

- **BlarAI did:** nothing today. Five attempts, no page. Two of its defects were fixed (#1479,
  #1481) and neither was ever the throughput problem.
- **Blair did:** rejected my offer to hand-write the site, correctly, because this is a
  validation exercise. Caught both models resident when I had convinced myself I'd stopped one.
  Challenged the 15.66 GiB figure, which was wrong. Insisted on realistic verification before
  production, which is the only reason a 3.05 tok/s configuration didn't ship as 18.5. Then
  asked for drift protection, which produced the table that overturned the day's conclusions.
- **Claude did:** shipped three real fixes with locks and an independent review, moved a
  23 GiB cache off a 1%-free system drive, upgraded OVMS, and built the sustained harness that
  should have existed first. Also published an inferred constant as a root cause, ran a
  benchmark into a live build, killed a process by the wrong name, crashed the server with a
  prompt sized by guessing, and reported a capability reduction as a restoration. Four of the
  five corrections in this entry came from Blair, not from me.

**Next:** re-judge #1484 and #1485 against sustained numbers — both were justified by probes
that did not survive. Then attempt #5.
