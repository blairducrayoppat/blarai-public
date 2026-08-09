### 2026-07-30 — The probe that could not say it never ran

*Plain summary: the check that confirms our exams can actually be run had been quietly answering "I can't tell" on every single invocation, and because "I can't tell" is a plausible-sounding answer, nobody heard it as a broken instrument.*

I came to #1200 with a one-line fix already written for me. `oracle_qa`'s `_qa_env` redirects
`APPDATA` into a throwaway directory so a grading run can never touch Blair's real
application data. uv keeps its managed CPython under `%APPDATA%\uv\python`. The redirect
therefore hides uv's interpreter from uv — and uv does not fail, it falls back. The sibling
module `oracle_mutation` hit this exact wall and fixed it in `f0a0e0be` by pinning
`UV_PYTHON_INSTALL_DIR` and `UV_CACHE_DIR` before the redirect. Copy it across, done.

I ran the real thing first, which is the only reason the rest of this entry exists. A clean,
obviously collectable oracle came back `unconfirmed` in 6.76 s. The captured stderr showed
uv resolving `C:\Python314\python.exe` instead of its own `cpython-3.13`, that interpreter's
site-packages injecting `pytest_textual_snapshot`, and pytest dying inside plugin load with
`ModuleNotFoundError: No module named 'rich'` before printing a single character of output.
The probe read empty output as a failed collection and stamped `unconfirmed`. Permanently.
Both banked nights, `20260729-232458-bd` and `20260729-230125-bd`, say exactly that.

Then I applied the pin and measured again, and this is where the ticket's one-liner would
have made things worse rather than better. The FAIL-TO-PASS baseline — the gate that
convicts an exam which passes with no implementation present — went from `not-run` to
`all-fail`, which reads as *clean*. I fed it a deliberately vacuous oracle, `def
test_always_green(): assert True`, the most convictable input that exists. Still `all-fail`.
Still zero findings. The runner was now correct and the verdict was now confidently wrong.

The reason is four characters long. `_pytest_cmd` builds the command with `-q`; the F2P
caller appended `-v` with the comment *"verbose so PASSED/FAILED lines are per-test
parseable"*. In pytest those two flags are one counter, so they cancel to default dot
output, `_qa_f2p_probe.py .`, and `_passed_tests` — which parses `<file>::<name> PASSED` —
finds nothing and reports that nothing passed. Measured side by side: with `-q -v` the
parser returns `[]`, with `-v` alone it returns `['test_always']`. That comment had been
describing an intention the command never carried out, and it could only ever be wrong on a
host where the runner worked, which was no host at all. Fixing the interpreter would have
converted an honest `not-run` into a false clean and shipped it as a win.

So the real question was never which env var to set. It was why a load-bearing grader could
be inoperative for weeks in plain sight, and the answer is the one CLAUDE.md already
records: every test in `test_oracle_qa.py` injected a fake `run` that returns a canned
string. The module's own docstring said so proudly — *"subprocesses are faked throughout"*.
`_qa_env` and `_pytest_cmd` are the seam the live path crosses, and not one test had ever
touched them. Worse than the sibling, which at least spawned a real process with the wrong
runner. Two of the existing fixtures asserted against blobs real pytest cannot emit: a bare
`E   ModuleNotFoundError` line with no summary. I only learned that by running a genuine
syntax error through the real runner and reading what came back — `no tests collected, 1
error in 1.34s`. Real pytest always prints a summary. That measurement is what let me
distinguish "the oracle failed to collect" from "the runner never ran" without guessing.

That distinction is the actual fix, and it matters more than the pin. Pinning is avoidance,
and avoidance can silently stop working — an unset `APPDATA`, a moved install, and the whole
failure returns wearing the same plausible word. So `confirm_collectable` now has a third
stamp. `not-run` means the runner died before pytest said anything, checked first, because
nothing a process printed on its way down is evidence about the file it never read.
`unconfirmed` now means what it always claimed to mean. I moved the pinning rule itself into
`grade_env.uv_dir_overlay`, the module that already owns the grading recipe, and made
`oracle_mutation` delegate to it — two modules had independently paid for this lesson and a
third copy is how a third module inherits it silently. The gate in
`tests/integration/test_uv_survives_appdata_redirect.py` AST-scans for any module that
redirects the app-data roots and invokes uv without the overlay, and carries its own
proved-off test so a detector that convicts nothing cannot pass as a clean tree.

I rejected two tempting alternatives. Hardcoding the real uv paths would survive every
reboot perfectly and follow the operator to no other machine — durable in precisely the
wrong direction, so the overlay resolves from the live environment and omits any directory
that is not actually on disk rather than inventing one. And `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`
would have killed the contaminating plugin at the root, which is genuinely the cleaner
mechanism, but it changes what loads during a real grade — hypothesis's plugin included — and
that is a grading-semantics decision I am not entitled to make inside a defect fix. I put it
to the Lead Architect's delegate and it came back no, for a reason sharper than mine: it
trades a contamination bug for a parity bug, which is the same currency this ticket is
denominated in.

Then review asked the question I should have asked myself: what happens when my own pin
fails? A root variable unset, a permissions error, a uv release that moves the directory. I
had an answer for half of it — the pin fails, the fallback interpreter is broken, pytest dies,
`not-run` fires, loud. But the other half was the defect surviving inside its own fix. Where
the pin fails and the fallback interpreter happens to *work*, the collect genuinely succeeds
and `confirmed` is a true statement about collectability and a silently false one about grade
parity, which is the entire reason the pin exists. Nothing fails, so no fail-loud stamp can
fire. I named it and did not fix it, on the grounds that I had been told to stand down; the
answer that came back is the right one and worth writing down — *a defect with one correct fix
you can name gets fixed; only a genuine trade-off gets deferred*, and naming the gap is not
the same as disposing of it. So there is now a fifth stamp, `parity-unverified`, decided from
the env we are about to hand over, before the spawn, because once uv has silently fallen back
a successful collect looks identical either way and that is the last moment the question is
still decidable. It is deliberately narrow: a command that never invokes uv has no uv pin to
lose and is not convicted, or fail-loud would become cry-wolf on every host without uv.

The numbers. Collectability on a clean oracle: `unconfirmed` before, `confirmed` after. The
vacuous oracle: `not-run` before, `vacuous:test_always_green` with one hard finding after.
The real runner takes 11.2 s and 12.9 s where the substituted one took under a second, so the
new tests assert an elapsed floor — a probe that finishes in a second has stopped exercising
the seam it exists for. Both halves proved off by mutation: neutering the overlay fails them
with `not-run`, restoring the `-q -v` cancellation fails them with `all-fail`. `shared/tests/`
is 3664 passed, 0 failed, 0 skipped.

Proposed lesson: *an instrument that cannot distinguish "I did not run" from "I ran and found
nothing" will report the second and mean the first, and the more reasonable its vocabulary
the longer it survives.* `unconfirmed` lasted two nights precisely because it sounds like a
finding.

Proposed second lesson, from the review round: *avoidance is not a control. Any fix that
prevents a failure rather than detecting it can itself fail silently, and the failure then
returns wearing the fix's uniform.* The test is simple and I now want to apply it to every
guard I write — ask what happens when the guard does not take, and if the answer is "the same
bad outcome, quieter", the guard is half a fix.

Then the same delegate reversed the stand-down that had stopped me widening, and was right to.
I had left `fail_to_pass_baseline` alone — it runs on the same env and can still return
`all-fail`, which reads as *clean*, from an equally unvouched interpreter — while saying in the
same breath that leaving it was wrong by the project's own rule. The reversal named what I had
only half-seen: the asymmetry was worse than the original defect, because a probe that refuses
to borrow the clean word makes the sibling that borrows it freely look deliberate. So
`parity-unverified` now applies to both, decided at the same moment, before the spawn.

What I did NOT do there matters more than what I did. Only the CLEAN outcome is downgraded. A
`vacuous` verdict still convicts with its HARD finding intact, because a test that passes with
no implementation present is evidence whichever interpreter observed it — and softening a hard
finding is a capability change, not a defect fix, which is not mine to make. `failure_taxonomy`
keys off the `vacuous:` prefix too, so the shape is load-bearing past this module. Both
outcomes carry identical findings, so the seed proceeds exactly as before; the only thing that
changed is that the evidence stopped claiming more than it measured. One residual I can name
and did not act on: a contaminated interpreter could satisfy an import the clean one would not,
manufacturing a false vacuous conviction. That direction is fail-soft — a false refusal to
seed, never a false green — so it stays, on the ticket.

The same narrowing discipline held on both. A command that never invokes uv has no uv pin to
lose and is not convicted, because a fail-loud control that convicts healthy configurations
gets muted, and then it is worse than the silence it replaced.

Independent verification then found two things, and the first is the entry's best joke at my
expense. The structural gate I wrote to catch this defect class had the defect class. One
line: `REMEDY_NAMES & names | attrs`. `&` binds tighter than `|`, so it computed
`(REMEDY_NAMES ∩ names) ∪ attrs`, and `attrs` contains `environ` for any module doing
`dict(os.environ)` — so the set was always non-empty, `not(...)` was always False, and the
gate convicted nothing, ever. The reviewer built a module redirecting both roots, calling
`shutil.which("uv")`, never naming the remedy, ran my gate over it and got `1 passed in
0.04s`. I *had* written a proved-off test and it did not catch this, because it drove
`_redirects_app_data` in isolation rather than the composed guard: every sub-predicate was
correct and the composition was not. The fix is a paren. The lesson is that a principle-12
toggle has to exercise the whole decision, or it certifies the parts and ships the seam — so
the guard is now one function the proved-off test drives end to end, against a real offender
module written out as source and parsed by the real scanner.

The second was worse, and it was mine. `_run_completed` decides whether a run counted, and it
accepted the bare substrings `" passed"`, `" failed"`, `" error"`, `"=== "`. Ordinary English
contains those. `error: Failed to fetch ... Request failed after 3 retries` — a uv network
failure — matches `" failed"`, so the run reads as completed with nothing passing, which is
`all-fail`, which is CLEAN: a vacuity gate certifying an exam on the strength of a run that
never executed a test. And it was *new*. Before the interpreter fix, F2P stamped `not-run` on
every invocation on this host, so the `all-fail` branch was dead code and this could not fire.
Repairing the runner is what brought it live on the dispatch path. I introduced a fail-open by
fixing something else — precisely the shape I had congratulated myself for catching two rounds
earlier with `-q -v`, arriving from the other direction. Every accepted shape is now one only
pytest emits: a count, a collection line, or a phrase it prints verbatim. Both directions are
locked, four machinery failures that must not read as completed and six real completions that
must, because tightening a predicate can just as easily make a working gate permanently
unmeasurable in the safe-looking direction.

The last round is the one I would keep if I could keep only one. Verification came back with
the predicate both parity stamps rest on, and it was wrong in *both* directions — one proxy
failure, not two bugs. I had asked `Path.is_dir()`, which answers "is a folder there", when the
question is "will uv resolve a managed interpreter". Measured on `sys._base_executable`
(`sys.executable` reports only uv's ephemeral build venv, which is what makes this easy to
miss): pointing `UV_PYTHON_INSTALL_DIR` at a directory that exists but is EMPTY resolves to
`C:\Python314\python.exe` — the exact contaminated interpreter this whole ticket exists because
of — while my guard vouched for it as healthy. The gap the guard was written to catch walked
straight through the guard. In the other direction, a host with no managed interpreter at all
loses nothing to the redirect: probe-time and grade-time resolve the same system python, parity
genuinely holds, and my guard would have fired on every run, forever. That is my own sentence
turned on my own fix — a fail-loud control that convicts healthy configurations gets muted, and
then it is worse than the silence it replaced.

One corrected question fixes both directions: if uv would not have used a managed interpreter
anyway there is no parity to lose, otherwise the env must actually reach one. The same question
now governs `uv_dir_overlay`, which carried the identical `is_dir()` assumption in the function
that SETS the variable — it could export a pin at a hollow directory and so manufacture exactly
the state the guard convicts, a control firing on a state its own sibling created. Both edges
shipped as regression tests rather than merely fixed, and pinned together in one test, because
each alone is satisfiable by a constant: a predicate hardwired True passes the no-interpreter
case, hardwired False passes the hollow-pin case, and only both at once force it to ask the
question. Three rounds of review, three defects in my own instruments rather than in the thing
being measured. The instrument is the harder problem, and I no longer find that surprising.

**Next:** two things I found and did not fix, each ticketed. The
collect-only probe cannot actually catch an ill-posed Hypothesis strategy — the real runner
collects `min_value=10, max_value=1` without complaint and only raises at call time, so
`confirm_collectable`'s `InvalidArgument` branch may be unreachable in production and passes
today only against a fabricated blob: a test green over a shape production cannot emit, in a
module written to detect exactly that. `swap_ops:1244` sets a default `f2p_baseline` but never
`collectability`, so a disabled-QA run persists evidence missing the key entirely. The
plugin-autoload question is decided and closed as a deliberate rejection, ticketed with the
three things a future look would have to settle rather than left as folklore. The symmetric
case is now fixed rather than deferred. What remains for whoever takes this branch is the
false-vacuous direction above, and the honest limit under all of it: every one of these
controls tells you the runner was not vouched for, and none of them tells you the verdict was
therefore wrong.
