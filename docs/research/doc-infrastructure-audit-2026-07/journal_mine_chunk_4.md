# Journal Mining — Chunk 4 of 7 (lines 7534–10093)

## 1. ERA

**Dates covered: 2026-06-16 → 2026-06-26** (~37 entries; numbered lessons 151–175 + 198).

This is the project's most sustained *build-and-ship* arc, and it runs two capabilities in parallel. The first week (June 16–17) is the **UC-010 local image-generation go-live** — taking a double-dormant, uncensored SDXL image capability from "config knob wired to nothing" through a real LA-present ceremony to a live feature with a gallery, born-encrypted at rest, that the operator can actually see and manage. The rest (June 21–26) is the far larger **headless-coding dispatch** arc: teaching BlarAI to hand a plain-English goal to an external coder fleet, which forces the single hardest hardware problem in the whole project — a **14B⇄30B model swap** on a 31.3 GB box where the two models cannot co-reside — plus an acceptance/decomposition layer for a non-developer, and a **VLM design-critique loop** that culminates in the era's thesis: *every soft oracle (LLM-as-judge) gets a deterministic gate under it, or it isn't a gate.* The through-line of the whole span is intellectual honesty under adversarial and live-verification pressure: dormant-merge governance, "the screen caught what the tests missed," and repeated self-correction of confidently-held wrong verdicts. This is the project maturing from "builds features" into "builds features it can honestly trust."

## 2. GEMS

1. **2026-06-16 — The verifier I almost broke for the whole fleet** — [engineering][governance/security][failure-story] — A "harden it everywhere" instinct on the *shared* manifest verifier would have refused the very next signed-manifest boot (14B/PA/draft all use the flat path); scoped the change to the one-caller nested path + added a regression lock so a future "finish the job" trips a test, not the operator's boot. A green synthetic-fixture gate would never have caught it.

2. **2026-06-16 — Content safety as a signature, not a classifier** — [governance/security] — For an uncensored *local* generator, content safety is a documented, operator-signed accepted-risk that names the boundary (legality, CSAM the absolute example), NOT a filter. Rejected a content classifier as ineffective locally, memory-costly, and privacy-invasive (it would re-inspect the operator's own private output). "Put the accountability where it lives." Pure AIGP governance gold.

3. **2026-06-17 — The go-live that was a config knob wired to nothing, then a memory ceiling** — [engineering][failure-story][human-AI-collaboration] — A dormant feature is one nobody has run. `steps=0` had been dead since written (one-step noise passes a PNG-decode assertion — the screen caught what 3 green layers missed); then the 1536² hires refine drove the box to 99.8% memory and *paged the always-resident 14B out to disk* (proc_rss collapsed to 142 MB). Lesson: **measure the memory before you believe the design** — the design review nodded through a pass that could never run in production.

4. **2026-06-17 — The command the operator couldn't type, and the "saved" that wasn't true** — [engineering][human-AI-collaboration][failure-story] — Two transferable lessons: *backend-complete ≠ operator-reachable* (a hand-maintained WinUI allowlist silently dropped `/imagine`, then `/images`); and *a "saved" flag is memory; a content hash is truth* — a decrypt-and-hash reconcile against the real save folder corrected the operator's own memory (8 byte-identical on disk vs a remembered ~14).

5. **2026-06-17 — The gallery that tested green and showed nothing** — [engineering][failure-story] — Textbook mock-lies: a *sync* `_FakeGateway` standing in for an *async* gateway let a `to_thread`-vs-`await` bug pass 13 green tests and ship; the live run failed instantly ("Object of type coroutine is not JSON serializable"), and fail-closed-to-empty swallowed it into a state indistinguishable from "store is empty." Lesson: a test double for an async object must itself be async — mirror the real shape, including await-ability.

6. **2026-06-21 — Measuring whether releasing the 14B actually opens the door for the 30B** — [engineering][process][failure-story] — A masterclass in honesty: **three successive wrong verdicts**, each corrected from *outside* the numbers (a reviewer's skepticism, the operator's daily experience, then the reviewer distinguishing the scenario measured from the one run). Exact: bare 14B-release lands ~20.1 GB (sub-threshold); the 30B load drove Available to **67 MB**, Committed to 29.1 GB, **206k page-ins/s** for 6 s. Lesson 151: confirm the measurement and the ground-truth fact are about the *same scenario* before letting one override the other. (Explicitly retired an earlier, too-strong draft lesson.)

7. **2026-06-22 — The swap you can only watch run on the real box** — [engineering][process] — Lesson 153: *inject the danger so you can test the logic.* A subsystem whose whole job is irreversible side-effects (kill a model, load another, relaunch the app) is exactly the one to drive in tests — every side-effect a passed-in `SwapOps` callable, so NEVER-ZERO / disarm-before-stop / bounded-retry become assertions, not hopes. 42 tests at the seam; the thin real subprocess wrappers are the only live-only remainder.

8. **2026-06-22 — The stage that wasn't there, and the check that never ran** — [engineering][governance/security][failure-story] — Lesson 154 (read the system you're dispatching to — the brief mapped onto a fleet "launch+console-scan" stage that doesn't exist) + Lesson 155 (**an unrun check is not a pass** — a .NET app gets no behavioral test, so `none` must render as UNVERIFIED as loudly as a failure; a verification feature that rounds "didn't check" up to "passed" is worse than none). Chose honest-asymmetric assurance (real gating for Python/Node, build-only for .NET, said out loud).

9. **2026-06-22 — The swap assumed it was alone** — [engineering][failure-story] — Passed every unit test and the standing gate, then failed on first real run because *four* launcher instances shared one per-boot certs dir → four CAs stomping one directory → mTLS `CERTIFICATE_VERIFY_FAILED`. Lesson 158/159 (single-instance is a control, guarantee termination don't widen the window). Naming the cause *precisely* (host-side multi-instance, NOT the VM) avoided building a cert-resync-to-VM channel for a problem that didn't exist.

10. **2026-06-22 — The thirty-second load the driver never saw** — [engineering][failure-story] — Lesson 160: *the log decides, not the hypothesis.* A confidently-held GPU-OOM story was wrong on every count — the OVMS log showed a clean 30 s load to AVAILABLE; the real cause (Lesson 161) was a captured-pipe deadlock: OVMS + a coding-proxy grandchild inherit the pipe on Windows so it never EOFs and the wait blocks forever *after* the model is ready. Had we "fixed the GPU," the deadlock would have shipped untouched.

11. **2026-06-23 — The teardown that ran on the next boot instead of mine** — [process][governance/security][failure-story] — Lesson 162: **"I reviewed it adversarially" and "it is correct" are different claims.** The author's own MERGE-READY adversarial pass read right past a real never-zero hole (`except Exception` guarding the two calls that *are* the 14B restore, while a `BaseException` was reachable via Ctrl+Break); an independent merge-gate caught it. Also: a design red-team caught a no-destructive-data violation (writing `[]` over the operator's shared queue) *before a line was written*.

12. **2026-06-24 — The load that should not have fit, and the trust grain for code I did not write** — [engineering][governance/security] — Double gem. Hardware truth (Lesson 169): **OOM is a commit-limit event, not a physical-RAM event** — this box page-storms, it doesn't OOM, so gate on measured Available-RAM headroom, never on catching an allocation failure. Governance: code the AI writes is **UNTRUSTED, not TRUSTED_LOCAL** — a provenance call named on the record with the rejected alternative (datamark it; containment cost is ~zero because read-and-discuss loses nothing). AIGP + community-relevant.

13. **2026-06-24 — Making the clarifying question actually fire** — [engineering][human-AI-collaboration] — Lesson 171: **a built-correct feature can be dormant in practice** — merged 4300/0 green, but the real 14B never once reached for `ambiguous`; the *live model probe* is the acceptance test, not the unit gate. A balanced few-shot prompt (vs a paragraph of instruction) took a small model to **15/15 with zero over/under-asking**. The operator chose the Conservative aggressiveness (ask only on genuinely platform-forking goals).

14. **2026-06-25 — The one place the machine still graded its own work** — [engineering][governance/security][human-AI-collaboration] — The era's capstone. The VLM design critic false-passed an overlapping calculator ("neatly aligned… clean grid") and the session *relayed* it — "I rubber-stamped the rubber-stamp"; the operator's "did you look at the image?" is the whole lesson. Fix (Lesson 198): a deterministic `layout_lint.py` XAML gate in front of the soft oracle, VLM demoted to a per-criterion loop-signal that can never mark a design "done." *Verify-the-artifact applies to the critic, not just the coder.*

15. **2026-06-25 — The seam the unit tests couldn't see** — [engineering][failure-story] — Lesson 175: *unit-green is not seam-green.* 137 green PowerShell tests hid a `GetNewClosure()` scope bug (rebinds function lookup to global scope): worked one level deep in every test, threw `Add-VisualFeedback is not recognized` two levels deep in production — and failed *soft*, so the whole design loop silently skipped with a clean merge. Environment (nesting depth, residency pressure, an idle-tuned timeout), not logic, is the seam mocks never reproduce.

## 3. LA MOMENTS (non-technical operator's judgment shaping outcomes)

The single richest LA-behavior chunk in the corpus so far — the operator repeatedly catches *quality and governance* misses the AI waved through, and owns the UX/risk calls:

- **Content-safety posture (06-16):** the go-live Step-3 governance gate is literally the operator signing sole responsibility for an accepted risk — the human owns the boundary no local control can enforce.
- **The saved-flag is a boolean, not a ledger (06-17):** the LA settled it in the brief; the AI notes the deeper reason — a path/timestamp export log is "a little map of the operator's filesystem habits," which a privacy-absolute system shouldn't hoard.
- **Evicting the shared 14B (06-17):** operator-approved because it amends a locked ADR — a capability/quality call escalated correctly rather than decided silently.
- **Gallery layout + memory gate (06-17, 06-22):** the LA chose the overlay pane over a split view; and set the pre-load swap gate to 21 (not the AI-recommended 24), a risk-acceptance call taken with the trade-off flagged and the alternative on record.
- **Ground-truth vs instrument (06-21):** the operator's plain-language fact ("I build with this 30B routinely, so it plainly works") corrected the AI's misattributed verdict — the non-technical operator's *experience* was a valid check on the instrument.
- **He caught the assurance holes (06-22):** the LA caught that a C#/UWP app gets *no* behavioral test (the acceptance layer would have rubber-stamped math it never ran), and collapsed the command surface to one always-confirm flow ("a non-developer should never have a path that does work he didn't approve").
- **"Build the calculator, not only the rocket" (06-23):** the LA added the rule that mattered most — primary functionality is non-optional.
- **The design-loop correction (06-25):** the operator's "this is not good enough… did you look at the image?" drove the entire deterministic-gate redesign; and "test end-to-end too… test the seams" caught two bugs 252 unit tests missed.
- **Fix the signal, don't route around it (06-26):** the operator endorsed taking the unreliable judge out of the critical path *and* insisted the broken signal itself be fixed, not merely bypassed.
- **He gates process integrity (06-23):** "The LA, gating, noticed I'd surfaced all four [behavior changes] rather than the one he'd named."

## 4. MOTIFS (and cross-era echoes to check)

- **Mock-passes / prod-crashes (the project's signature lesson class)** — recurs 6+ times here alone (async-fake shape, GetNewClosure scope, stubbed capture, `System.Drawing`-on-PS7, dead `steps=0` passing a PNG decode, sync-fake-for-async). *A synthesizer should trace this back to the frozen-dataclass origin in the earliest era and forward to see whether the "test the seam / drive real objects" control finally sticks.*
- **Dormant-merge + LA-present ceremony governance** — nearly every entry ships behind a config flag; go-live is a human event. *Check the air-gap-removal era and later egress ceremonies for the same pattern and its evolution.*
- **Deterministic gate under every soft oracle (LLM-as-judge)** — the design-loop arc's thesis; "never trust the model's self-report." *Check later coordinator / self-governance-boundary eras — the same "advisory-only, structural severance" logic.*
- **Verify-don't-assert / read-the-code-not-the-docstring / read-the-system-you-dispatch-to** — Lessons 154, 163, 165, 167, plus the "zero C# change" and "os was never imported" overclaim corrections. Pairs with "verify the LA's technical premises."
- **Measure the real scenario, not the convenient one** — memory (151, 169), timeouts tuned on idle vs loaded boxes, the two-level nesting repro. Recurring debugging discipline.
- **Self-correcting overclaim / independent-gate-beats-self-review** — Lessons 151, 162, 198; author≠verifier. The corpus's intellectual-honesty spine.
- **Scope to the path that needs it / least-authority-as-default-not-dogma** — shared-primitive scoping (06-16) + the global-by-id resolve decision (06-16).

## 5. WASTE PROFILE (approx. % of chunk tokens)

This chunk is unusually high-signal — dense failure narratives with named trade-offs. Waste is low; most "waste" is lesson-text that also lives in LESSONS.md, not empty status.

- **Genuinely-narrative ~48%** — the bulk. E.g. "Measuring whether releasing the 14B…", "The one place the machine still graded its own work", "The gallery that tested green and showed nothing". KEEP.
- **Duplicated-in-LESSONS ~25%** — the bolded `**Lesson NNN:**` blocks (151–175, 198) restate what LESSONS.md canonicalizes; the surrounding narrative is not duplicated. E.g. the Lesson 152/153/166 blocks.
- **Superseded-by-later-events ~12%** — dormant-state + "Next:" plans overtaken by go-lives, and iterative shakedown entries that each correct the last. E.g. "The swap assumed it was alone", "The thirty-second load the driver never saw", "Wiring the dormant dispatch…".
- **Changelog-shaped ~10%** — incremental-wiring entries heavy on commit detail. E.g. "Showing the operator the build before he signs off on it", "Confirming what I assumed before he commits half an hour to it", "Building the headless WinUI…" (parts).
- **Status-shaped (no lesson) ~5%** — mostly component descriptions. E.g. "The signal that never becomes a verdict" (critique.py tour), "The critic that costs nothing when silent" (spill-over mechanism note), parts of "Giving the operator a way to see what they made".

## 6. CURATION VERDICTS

**KEEP-HOT (the exceptional few — must stay instantly findable):**
- 2026-06-16 — Content safety as a signature, not a classifier *(AIGP governance keystone)*
- 2026-06-21 — Measuring whether releasing the 14B actually opens the door for the 30B *(three-swings honesty masterclass)*
- 2026-06-24 — The load that should not have fit, and the trust grain for code I did not write *(OOM=commit-limit + UNTRUSTED-provenance)*
- 2026-06-25 — The one place the machine still graded its own work *(LLM-as-judge deterministic floor, Lesson 198)*
- 2026-06-17 — The gallery that tested green and showed nothing *(async-fake mock-lies, textbook)*
- 2026-06-22 — The stage that wasn't there, and the check that never ran *(an unrun check is not a pass — assurance governance)*
- 2026-06-16 — The verifier I almost broke for the whole fleet *(shared-primitive scoping; a near-brick averted)*

**ARCHIVE-WHOLE (default — safe in a cold volume; valuable narrative, but lesson canonicalized in LESSONS.md and not needed instantly):**
- 2026-06-16 — The doc that promised a door that wasn't wired
- 2026-06-16 — The least-authority instinct that didn't pay rent
- 2026-06-16 — The runbook that assumed the wrong python
- 2026-06-17 — The go-live that was a config knob wired to nothing *(strong, but long; lesson lives on)*
- 2026-06-17 — Giving the operator a way to see what they made
- 2026-06-17 — The last leg to a pixel, and the "zero C# change" that was never true
- 2026-06-17 — The command the operator couldn't type, and the "saved" that wasn't true
- 2026-06-17 — The gallery that reused everything, and the allowlist that drifts in silence
- 2026-06-21 — Dispatching to a fleet you must not become
- 2026-06-22 — The swap you can only watch run on the real box
- 2026-06-22 — Wiring the dormant dispatch to a backend that can step out of its own way
- 2026-06-22 — The swap assumed it was alone
- 2026-06-22 — The thirty-second load the driver never saw
- 2026-06-22 — The ruler that collapsed the wrong things first
- 2026-06-23 — The teardown that ran on the next boot instead of mine *(borderline; Lesson 162 is strong — promote if a KEEP-HOT slot frees)*
- 2026-06-23 — The fix the brief pointed away from
- 2026-06-23 — The acceptance task that tested nothing for twenty-four minutes
- 2026-06-23 — The stop button that was already wired, minus the button
- 2026-06-23 — Confirming what I assumed before he commits half an hour to it
- 2026-06-23 — Showing the operator the build before he signs off on it
- 2026-06-24 — Giving the 14B back the platform knowledge we were throwing away
- 2026-06-24 — Building the headless WinUI so the box can test itself
- 2026-06-24 — Asking one question, and only one, and never letting the model write it
- 2026-06-24 — Making the clarifying question actually fire *(borderline — Lesson 171 is quotable)*
- 2026-06-24 — The second model, wired as a choice and blessed before it speaks *(borderline — the git add -A governance catch, Lesson 172)*
- 2026-06-25 — Letting the model do the half it's good at
- 2026-06-25 — The signal that never becomes a verdict
- 2026-06-25 — Watching the machine watch its own work
- 2026-06-25 — The seam the unit tests couldn't see *(borderline — Lesson 175 is one of the best "unit-green ≠ seam-green" statements)*
- 2026-06-26 — The live test that found four real bugs the theory had explained away
- 2026-06-26 — The critic that costs nothing when silent *(spill-over past line 10073)*
