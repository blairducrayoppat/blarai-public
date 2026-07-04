### 2026-06-27 — Bounding the run from both sides (the task envelope, #691)

The decomposer already had a LOWER bound. `_collapse` (the #670 ruler) exists because a
free-associating 14B once exploded "write an is_leap_year function" into nine fleet tasks —
a task per test case, a define/implement split, a create-file step — each of which would
spin its own worktree and model-swap. So the ruler drops atomic over-splits and keeps the
fewest coherent feature tasks. What it had no opinion about was the OTHER error: a whole app
crammed into one task. And that error is the more expensive one, because the local 30B's
success on an autonomous run falls roughly p^N with the step count (Toby Ord, arXiv:2505.05115)
and METR measures \~100% on tasks under \~4 minutes against <10% past \~4 hours. A coder asked to
build add, list, complete, and delete in one eight-minute run is being set up to fall off the
cliff. #691 is the UPPER bound: the dispatch unit is one coherent deliverable sized for one
short gated run, and a goal the 14B under-split gets broken into gated increments instead.

The primary lever turned out to be the cheapest one: the decompose prompt itself. I added an
ENVELOPE rule — a multi-screen / multi-command / multi-service app is MULTIPLE tasks, one per
independent part, whole-app-in-one-task is the exception — carefully phrased NOT to loosen the
anti-over-split rules above it (a single function or a single small screen is still one task).
On the Arc 140V the real 14B then decomposed "a command-line todo app with add, list, complete,
and delete commands" into exactly four gated tasks, and left "write an is_leap_year function" as
one. The prompt makes the semantic call a regex never could: it knows "add and delete commands"
are two units while "adds and subtracts" is one calculator.

Behind the prompt sits the deterministic BACKSTOP — the recursive split the module was always
scaffolded for (`max_depth`, `_is_leaf_goal` as the stop-condition, finally load-bearing). When
a clearly-multi-unit goal still collapses to a single task, that lone task is offered to a "go
finer" split prompt; the children run through the SAME `_collapse` ruler; and they replace the
lump ONLY on a strict improvement (>=2 coherent tasks), so a coherent small app the 14B re-judges
as one step is kept untouched. The honest tension is that this re-introduces the very over-split
risk the ruler was built to suppress — so the trigger is deliberately narrow (a multi-unit goal
only, never a leaf; live-verified that is_leap_year is never offered to it), the children are
re-collapsed, and the strict-improvement fail-safe is the backstop's backstop. It is bounded to
exactly one extra depth level; the children are not re-split.

Two things the live box taught me that the unit tests, with their clean canned model output,
could not. First, the backstop did NOT fire on the whole-app goal — because the prompt had
already split it. That is the right outcome, not a miss: the cheap lever handles the common
case and the expensive mechanism is insurance, exactly the order you want them in. Second, and
sharper: when I drove the backstop directly, it intermittently fell back even on a goal it
should split. The cause was not the logic — it was the 14B's `<think>` block eating the plan
token budget. Every PLAN call shares `_PLAN_MAX_NEW_TOKENS = 1024`, and the split prompt, being
a "reason about how to break this down" task, induced a long think block that spent the budget
and TRUNCATED the JSON array mid-stream, so the parse failed and the fail-safe held. The fix is
the ADR-012 §2.4 posture already used for the PA's structural classification: `/no_think`. A
split is a structural JSON enumeration, not a reasoning task; suppressing thinking gave the whole
budget to the answer, and the same call then returned six clean gated steps DETERMINISTICALLY
across repeated runs. That one debugging detour also surfaced a latent risk bigger than this
ticket — the same truncation can hit decompose or criteria on a complex goal — which is now
written down (Vikunja #699) rather than discovered in production.

**Next:** #695 — the measured parallel-execution follow-up. With the envelope splitting a goal
into several short gated tasks, the case for running best-of-N candidates concurrently (and
measuring the real OVMS continuous-batching ceiling on the integrated Arc 140V) is stronger, not
weaker: more, smaller tasks is more parallelism to harvest. And as local models climb the horizon
curve (METR: the 50%-task length doubles \~every 7 months) this same envelope rides it for free —
a bigger coherent unit simply stops tripping the upper bound.

**Proposed lesson:** *Bound the work from both sides, and let the cheapest lever lead.* A ruler
that only prevents over-splitting is half a policy; the whole-app one-shot is the costlier error
on a model whose success decays p^N with step count. Fix it first in the prompt (the model can
make the semantic granularity call a regex cannot) and keep the deterministic recursive split as
bounded, fail-safe insurance. And a STRUCTURAL model call should not think on a tight token
budget — a `<think>` block that truncates the answer is worse than no thinking at all.

*(commits: blarai `<this>` (decompose.py envelope upper-bound: strengthened prompt + bounded
recursive split + `/no_think` on the split + envelope-policy doc; +10 tests; standing gate green);
live on the Arc 140V 2026-06-27 — whole-app goal -> 4 gated tasks via the prompt, leaf -> 1 task,
the backstop split -> 6 deterministic gated steps once /no_think freed the budget. Follow-ups
#695 (measured parallel execution), #699 (/no_think for the other structural plan calls).)*
