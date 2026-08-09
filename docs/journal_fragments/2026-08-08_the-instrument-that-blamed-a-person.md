### 2026-08-08 — The instrument that blamed a person who was not there

*Plain summary: three of our tools reported a confident cause they had no way to know, and the operator caught the worst one by simply saying "I never did that" — which turned a slow build into a measured 25% defect.*

I opened today expecting to protect a battery night and spent it discovering that four
separate instruments were each asserting something their mechanism could not see. The
guard was the one I planned for. The other three found me.

The gate came first, and it paid for itself before I wrote a line. The landing card I
inherited said last night's 23:00 collision archived a live sandbox but that "nothing was
lost" — the archive is a rename, all twenty files intact. True, and it stops one step too
early. I read the night's own scorecard instead of the card's account of it. The nightly
had not merely collided; it had **stalled at 255.97 seconds** and written
`failure_class: HARNESS-BUDGET` against a **28,800-second** budget. Nine-tenths of one
percent of its budget, filed as running out of time. And the boot log showed the GPU was
healthy throughout — pipeline built on GPU at 23:01:05, the fourteen-billion-parameter
model resident at 23:01:14 — so the label was wrong about the cause *and* the machine was
fine. The collision had two casualties: a sandbox that was recoverable, and an eight-hour
measurement window that was not. The card recorded the first and not the second, which is
how a true sentence can still leave the next session with the wrong picture.

Then the guard, where I nearly shipped the same defect one level up. The ticket said to
extend the archive guard from task-level to run-level: it counts `TASK-START` against
`TASK-END`, those balance between waves, so go up a level. Journals do carry
`RUN-START`/`RUN-END`, so this looks right. I checked it against the run that actually
died — `20260807-195617-bd` — before building it. **RUN-START=6, RUN-END=6.** Balanced.
Those markers are emitted per *wave*, not per dispatch, so a run-level predicate would
have admitted the collision for precisely the reason the task-level one did. The journal
has no marker for the outer interval at any level; no reading of that file can answer the
question. What owns the sandbox for the whole run is the **process** driving it, and a
process is an interval by construction. I would have fixed the instance again and left the
class open for a third time, and the only thing that stopped me was measuring the obvious
fix before writing it.

The trade I rejected: relaxing `permission.external_directory` from `"ask"` to `"allow"`
would have cleared the day's other blockage in one line and immediately sped up a build
the operator was waiting on. It is a containment control, so it is his call and not mine —
but the honest reason not to propose it is that it treats the symptom. It would let the
coder reach the entire filesystem instead of pointing it at the right directory. I noted
it, recommended against it, and left the posture alone.

The instrument-honesty thread ran through everything and I was not exempt. The desktop app
told the operator **"BlarAI backend not running"** while the backend was verifiably serving
— it had asserted a whole-system verdict from one channel timing out, the mirror image of
#1324's port check claiming a readiness it could not see. My own watchdog then announced
his build had lost its backend, twice: once because I sampled a port at an instant while
the swap driver was legitimately restarting the model between waves, and once because I
treated `SUMMARY.txt` as a run-terminal marker when it is written every wave. **I made the
interval-vs-instant mistake twice, in instruments I built, on the same day I shipped a fix
for it.** Writing that down is the point. The class is not obscure and knowing it by name
did not stop me; only checking the marker against a completed run did.

The best finding of the day was not mine. Reading a coder log over my shoulder, the
operator said: *"i never rejected the permission. that's not true."* He was right. The
message is `The user rejected permission to use this specific tool call`, the run is
headless, and no human is in that loop at all. I had taken it at face value for several
minutes and gone looking for a permissions problem. What it actually meant: the coder was
sending `filePath: "/public/index.html"` — a leading slash, which resolves at the
filesystem root, lands outside the project, trips an `"ask"` rule, finds nobody to ask, and
is denied. Every read, write and edit in that attempt failed; **not one succeeded**. The
coder spent forty steps and seventeen minutes routing around it with `cat`, `cp` and
`echo`, which is exactly what its own instructions forbid — and it never saw the guidance
that would have helped, because the guidance did not exist. `AGENTS.md` warned only about
absolute paths *outside* the project, which reads as being about the home folder, and never
mentioned the one shape that always fails.

That fix is a documentation change, and it is the most valuable thing I shipped today.
Consecutive tasks of the same dispatch, same repo, same model, minutes apart:

| Task | Wall clock | Denials | Path shape |
|---|---|---|---|
| `home-page` (before) | 67.3 min | 11 | `/public/index.html` |
| `pieces-list-page` (after) | 50.2 min | 0 | fully drive-qualified, all of them |

Seventeen minutes and twenty-five percent, from one corrected sentence. I am deliberately
recording what that is *not* evidence of: the denial count 11 → 0 is exact and directly
attributable, but the minutes are confounded — task one also ran more visual-fix cycles,
and n=1 per arm. A 25% figure will get quoted, so the caveat belongs next to it.

Two things the guard work cost me that are worth naming. `b7af0a0` shipped sixty lines of
guard with **no test at all** — one file changed, nothing referencing it anywhere in the
repo — so nobody could have found the task-vs-run defect by running anything. An untested
control failed the way untested controls fail. And the existing taxonomy test asserted the
defect: `test_harness_attribution_routes_to_harness_budget` read `== CLASS_HARNESS_BUDGET`
and passed, so the bug was the recorded contract and three green sweeps never questioned
it. Baselines are evidence, and that one was evidence for the wrong thing.

The new verifier therefore has two modes and neither pretends to be the other. Its default
**refuses to run** while a dispatch is live, because the "nothing is running" cases cannot
be evaluated then, and passing them vacuously to reach a green total is the exact defect
the guard exists to stop. `-LiveProof` does the opposite and states in its result line what
it did not evaluate. It ran against the operator's real in-flight build — pid 22988, three
driving processes — which is a proof that was available today and will not be reproducible
tomorrow.

**Next:** merge the guard once his build ends, advance the pinned driver tree the 23:00
task actually runs from — a merge to `main` alone does not protect tonight — and re-verify
against that tree; then land the taxonomy split without advancing the measured tree, so
tonight carries exactly one battery-path change.

---

**Lesson proposals** (unnumbered — the integrator mints; search `LESSONS.md` first, and note
`LESSONS.md` is 1,772 bytes from its gate so #1319's size relief comes first):

1. An error message that names a CAUSE the mechanism cannot observe costs more than no
   message: "the user rejected permission" where no user exists, and "backend not running"
   from one channel's timeout, both sent readers to a fix that could not work. A tool may
   report what it observed and must not report who decided.
2. When a guard is defeated, measure the obvious next-level fix against the artifact that
   defeated it BEFORE building it — `RUN-START`/`RUN-END` looked like the level up and
   balanced 6-and-6 on the very run that died. Possible recurrence of the class that lesson
   30 owns; check before minting.
3. Operator-facing instructions are production surface, and their GAPS are defects: the
   coder failed for seventeen minutes on a path shape its instruction file never named,
   while the file did carry a rule it then broke. Check overlap with the
   documentation-is-not-evidence line before minting.
