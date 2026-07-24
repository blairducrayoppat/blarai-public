# Independent review — `a89783f8` control + execution record

**Reviewer:** independent (did not author the change). **Date:** 2026-07-22.
**Scope (narrow, deliberately):** (1) the lesson-156 third-instance control in
`shared/tests/test_acceptance_clarify.py`; (2) truthfulness of the EXECUTION RECORD
appended to `docs/governance/fold-plan-2026-07-22.md`.
Written incrementally, section by section, as each is driven.

---

## (1a) The control runs — VERIFIED

```
$ ./.venv/Scripts/python.exe -m pytest shared/tests/test_acceptance_clarify.py -q
16 passed in 0.46s
```

`grep -c "^def test_"` = 16 test functions in the file.
`git show a89783f8 -- shared/tests/test_acceptance_clarify.py | grep "^+def test_"` returns
exactly 3:

- `test_every_post_seed_consumer_takes_the_planning_seed_not_the_bare_goal`
- `test_the_job_oracle_author_is_reached_by_the_seed_not_the_goal`
- `test_the_control_can_see_a_planted_violation`

Matches the claim. No finding.

Baseline digest of the mutation target before any edit:
`shared/fleet/acceptance.py` = `62bd29836db99118597c27628611f8f4ef9bbfdf83c3aadd704262573547838b`

---

## (1b) Mutation proof — the control is genuinely load-bearing, VERIFIED

Procedure (no git verb used at any point; restore was a file copy):

1. `cp shared/fleet/acceptance.py $SCRATCH/acceptance.py.pristine` — backup digest
   `62bd2983…7838b`, identical to the working file.
2. Reintroduced the #1032 defect at `shared/fleet/acceptance.py:3442` — the first positional
   argument of the `author_and_qa_job_oracle(` call changed from `planning_seed` to `goal`.
3. Re-ran the file. **RED, 3 failed / 13 passed:**
   - `test_every_post_seed_consumer_takes_the_planning_seed_not_the_bare_goal` (new enumerator)
   - `test_the_job_oracle_author_is_reached_by_the_seed_not_the_goal` (new reached-by assertion)
   - `test_requirements_reach_the_MULTI_task_job_oracle_author` (the pre-existing #1032 lock)

   The enumerator's failure message named the offending site and line; the reached-by test's
   message showed the seed-fed set with `author_and_qa_job_oracle` genuinely absent:
   `{'_asset_specs_from_plan', '_refine_web_static', 'decompose_request', 'format', 'generate_acceptance_oracle'}`.
4. `cp $SCRATCH/acceptance.py.pristine shared/fleet/acceptance.py`.

**Digests:** before mutation `62bd29836db99118597c27628611f8f4ef9bbfdf83c3aadd704262573547838b`;
after restore `62bd29836db99118597c27628611f8f4ef9bbfdf83c3aadd704262573547838b` — byte-exact.
`git status --porcelain shared/fleet/acceptance.py` is empty, and the file is 16/16 green again.

Both new locks are mutation-proven. The commit message's claim on this point is accurate.
No finding.

---

## (1c) What the control MISSES — demonstrated, not speculated

Method: I did **not** re-implement the detector. I pointed `acc.__file__` at synthetic module
sources and called the shipped helpers `t._bare_goal_consumers_after_seed()` and
`t._generate_plan_ast()` directly, plus the second lock's logic verbatim.
Script: `…/scratchpad/blindspots.py`. Result table:

| scenario | enumerator | reached-by lock |
|---|---|---|
| A — `x = goal; author_and_qa_job_oracle(x)` | **BLIND** | CATCHES (missing `author_and_qa_job_oracle`) |
| A2 — `x = goal; new_ninth_consumer(x)` | **BLIND** | **passes** |
| B — new consumer inside a nested `def` | CATCHES `{'new_ninth_consumer': [8]}` | passes |
| B2 — new consumer inside a comprehension | CATCHES `{'new_ninth_consumer': [7]}` | passes |
| C — wrapper `_helper(goal)` → oracle author | CATCHES `{'_helper': [10]}` | passes |
| D — `planning_seed = goal` unconditionally | **BLIND** | **passes** |

Reading each:

- **B, B2, C are NOT blind spots.** `ast.walk` descends into nested `FunctionDef` and
  comprehension bodies, so a new consumer hidden in either is still enumerated. The wrapper
  case is caught for a better reason than luck: deny-by-default means the *wrapper itself*
  (`_helper`) is an un-allowlisted bare-`goal` consumer and trips the assert. The author's
  deny-by-default choice is what buys this — a blocklist would have missed all three.

- **A2 is a REAL GAP** — see FINDING-1 below. It is the exact case the enumerator's own
  docstring promises to cover ("a NINTH call site added tomorrow is caught the day it
  lands"). One intermediate assignment defeats it, and the second lock does not backstop it
  because that lock pins three *hardcoded existing* names, not new arrivals. Case A (the
  same laundering applied to an already-pinned site) *is* caught, but only by that name pin.

- **D is a scope limit, acceptably handled — but only by luck of file composition.** Neither
  ast lock sees a mis-COMPUTED seed. I mutated the real source instead of arguing about it:
  `shared/fleet/acceptance.py:3210` → `planning_seed = goal`, re-ran the file, got
  **2 failed / 14 passed** — `test_requirements_thread_into_prompts_and_tasks_and_spec_goal_stays_clean`
  and `test_requirements_reach_the_MULTI_task_job_oracle_author`. Both are **pre-existing
  behavioural** tests, not part of this commit. So the defect class *is* covered in this
  file; the new control simply is not the thing covering it. Restored byte-exact
  (digest `62bd2983…7838b`, `git status` clean, 16/16 green) after the mutation.

### [FINDING] The enumerator is defeated by one intermediate assignment, and this is not documented

`shared/tests/test_acceptance_clarify.py:395-412` (`_bare_goal_consumers_after_seed`) matches
only `ast.Name` arguments whose `id == "goal"`. A new consumer written as:

```python
x = goal
new_ninth_consumer(x)
```

is invisible to it (demonstrated, row A2 — both locks pass on a source containing exactly
this defect). The gap matters because the enumerator is the *only* forward-looking lock; the
reached-by test at `:434` guards a hardcoded triple of names that already exist.

I judge this a **FINDING, not a BLOCKER**: the realistic recurrence shape for lesson 156 is
"someone adds a call site and passes the variable that is in scope and obviously named" —
which is `goal`, and which the control catches. Laundering through a temp is not the observed
failure mode. But the control's docstring states a broader guarantee than it delivers, and the
whole point of a Rule-3 control is that a later session trusts it.

**Fix (either is sufficient, both are cheap):**
1. *Documentation* — amend the `_bare_goal_consumers_after_seed` docstring to state the limit
   explicitly: "direct `goal` Name arguments only; a value laundered through an intermediate
   local is not tracked." A named limit is a limit a successor can reason about; an unnamed
   one reads as coverage that exists.
2. *Closing it* — taint-track locals: pre-walk the function for `Assign` nodes whose value is
   `Name('goal')` after the seed line, collect those target ids into an alias set, and treat a
   call passing any alias as a bare-goal consumer. ~6 lines, same `ast` pass, no new dependency.

I recommend (2) with (1) as the comment above it, but (1) alone clears the finding.

### [NIT] The toggle-off test re-implements the detector instead of calling it

`test_the_control_can_see_a_planted_violation` (`:463`) rebuilds the walk/`defaultdict` logic
inline over a planted source rather than invoking `_bare_goal_consumers_after_seed`. It
therefore proves *a* detector fires, not that *the shipped* detector fires — the two could
drift and the toggle-off would stay green. This is the mock-shape-divergence pattern applied
to a test's own subject.

The scenario harness I wrote for (1c) shows the honest version is easy: point `acc.__file__`
at a synthetic module and call the real helper. Suggested fix — plant the violation in a temp
file, `monkeypatch.setattr(acc, "__file__", str(tmp))`, then assert on the real
`_bare_goal_consumers_after_seed()` output. NIT rather than FINDING because the current
version does prove the *logic* is correct and the real-source mutation in (1b) independently
proves the shipped path fires.

---

## (1d) The allowlist `{"rule_spec"}` — CORRECT

`_LEGITIMATE_BARE_GOAL_CONSUMERS = {"rule_spec"}` is right, and the contract is stated at
the mint site rather than invented by the test:

- `shared/fleet/acceptance.py:3207-3209` (the mint-site comment): *"The seed the sub-generations
  plan FROM… ``spec.goal`` stays the CLEAN goal (below) so the preview/report headers never
  carry the block; the seed only shapes what gets built."*
- `:3244-3245` restates it at the criteria step: *"the criteria plan FROM planning_seed…, but
  rule_spec keeps spec.goal the CLEAN goal so the preview header never shows the block."*
- The call itself, `:3258`: `spec = rule_spec(goal, _parse_criteria(...), ...)` — the only
  post-seed bare-`goal` call in the function.

`rule_spec` builds the `AcceptanceSpec` whose `goal` field is operator-facing text. Feeding it
`planning_seed` would render the clarified-requirements block into preview/report headers —
a user-visible regression, not a fix. The pre-existing test
`test_requirements_thread_into_prompts_and_tasks_and_spec_goal_stays_clean` pins exactly that
asymmetry, and it failed under my seed mutation in (1c), so the contract is independently
enforced rather than resting on the allowlist comment.

The allowlist is also correctly *minimal* — one entry, deny-by-default, with the reason
written next to it. No finding.

---

## (2) EXECUTION-RECORD TRUTHFULNESS — every checked claim is TRUE

I treated the record (`docs/governance/fold-plan-2026-07-22.md:174+`) as a set of falsifiable
assertions and tried to break each one. None broke.

### 2.1 Lessons 8 and 47 — `✓ctrl` added, and the controls are real

```
$ git show a89783f8 -- LESSONS.md | grep -E "^[+-](8|47)\. "
-8.  … · ↺4 ★              +8.  … · ↺5 ✓ctrl ★
-47. … · ↺2                +47. … · ↺3 ✓ctrl
```

Both index lines genuinely gained `✓ctrl`. The archive full texts name real controls, and both
exist on disk:

- Lesson 8 → *"the steady-state benchmark protocol in `scripts/benchmark_kv_cache_sweep.py` —
  warm-to-plateau, inter-combo cooldown, and a first-combo-vs-isolated-smoke cleanliness gate;
  #709"*. File present (24,395 bytes).
- Lesson 47 → *"control: the three-property `tests/security/test_dependency_truth.py` (forward
  truth, reverse truth, manifest↔lock consistency), watched failing against deliberate
  mutations before trusted. #810"*. File present (12,425 bytes).

The record's stated *reason* for 47 mattering ("47 took a fourth tally here, and an unmarked
control would read as an outstanding Rule-3 debt that does not exist") is also verifiable: 47's
archive text carries a 2026-07-22 fourth recurrence (#1031/#1042). Accurate.

### 2.2 The three disposition changes — all three match the diff

| claim | verified how | verdict |
|---|---|---|
| `1045-destructive-verb` **minted 299**, not tallied | `+299. A destructive command is most dangerous during CLEANUP… · ✓ctrl` present in the diff | TRUE |
| `1005-grading` tallied on **222, not 8** | 222's index line `↺6 → ↺7` in the diff; 8's bump is attributable to its own separate tally | TRUE |
| `perf-log-orphaned-narratives` tallied on **33, not minted** | 33's index line gained `· ↺1` (it previously carried no flag at all) | TRUE |

The mint-not-tally justification also holds. The record names 52 and 172 as the near-misses;
both are as characterized (52 = worktree branch-switch quirk, 172 = `git add -A` reflex), and a
sweep for any other numbered lesson covering the destructive-git class
(`grep -niE "^[0-9]+\. .*(destructive|force-push|reset --hard|git checkout --)" LESSONS.md`)
returns only 299 itself. There was genuinely nothing to tally against.
299's `✓ctrl` is backed by a real artifact: `~/.claude/hooks/block_destructive_git.py`
(6,468 bytes, mtime 2026-07-22 18:40 — i.e. shipped *before* the 20:19 fold commit, exactly as
"the already-shipped hook recorded as its control" claims).

### 2.3 The lesson-46 off-by-one — REAL, and the hardest claim to fake

This was the claim most worth attacking, because the correction is **invisible in the diff**:
the record says the pre-existing value and the corrected value are both `↺6`, so `LESSONS.md`
shows no `46.` index-line change at all. A fabricated "defect found and fixed" would look
identical. It is real:

```
6df70ad5 (parent) : archive recurred-markers=5  index-flag=↺6   <- genuine off-by-one
a89783f8 (fold)   : archive recurred-markers=6  index-flag=↺6   <- reconciled by the new tally
2c6d403b          : archive recurred-markers=7  index-flag=↺7   <- the separate 7th instance
HEAD              : archive recurred-markers=7  index-flag=↺7
```

The pre-change index asserted 6 recurrences against 5 archive markers. The fold added the 6th,
so the correct post-fold value *is* `↺6` — the bump was absorbed by the correction rather than
propagating the error to `↺7`. Exactly as described.

I also checked the broader claim *"All 11 tally counts now reconcile against the archive
programmatically"* by reconciling every tallied lesson's index flag against its archive
`(recurred:` marker count at HEAD — lessons 3, 8, 33, 46, 47, 156, 171, 194, 222, 265, 293:
**11/11 OK, zero mismatches.**

### 2.4 `989-ab-day-cadence-20260721.md` is genuinely tracked

```
$ git ls-files --error-unmatch docs/journal_fragments/989-ab-day-cadence-20260721.md
docs/journal_fragments/989-ab-day-cadence-20260721.md   (exit 0)
```

Tracked. The deferral is therefore durable in the sense claimed — the held-back fragment
survives in git rather than as an untracked file, and the record pairs it with an observable
predicate (#1058) plus a battery-instrument reason for the hold, which satisfies
`<deferral_discipline>`'s requirement that a `blocked-by:` name something a later session can
observe.

**No finding in section (2).** The record is written in a self-crediting register, but I could
not find a single overstated or unverifiable factual claim in it. Notably, the two claims that
would have been easiest to inflate — the invisible lesson-46 correction and the "all 11
reconcile" assertion — are both true under independent measurement.

---

## VERDICT: MERGE

The change is already merged into `main` (`a89783f8`, with `2c6d403b` and `4a57e237` on top);
read this as "nothing here warrants a revert, and the one finding is a follow-up, not a
blocker." The lesson-156 control is real and load-bearing: I reintroduced the exact #1032
defect and watched all three relevant locks go RED, then restored the file byte-exact by copy
(digest `62bd2983…7838b`, `git status` clean, 16/16 green). Its deny-by-default design is
better than it needed to be — it survives nested functions, comprehensions, and wrapper
indirection, three shapes I expected to defeat it. The allowlist is minimal and its single
entry is backed by a contract stated at the mint site, not invented by the test. The execution
record survived every falsification attempt I made, including the one correction that leaves
no diff trace. The single FINDING — one intermediate assignment defeats the enumerator, which
is the very "ninth site added tomorrow" case its docstring promises — is a documentation or
six-line taint-tracking fix, not a reason to hold the merge, because the realistic recurrence
shape is the one it catches.

### What I drove vs. did not examine

**Drove (executed, not read):**
- `pytest shared/tests/test_acceptance_clarify.py` at baseline, under two distinct mutations, and after each restore.
- Mutation 1: `acceptance.py:3442` `planning_seed` → `goal` (the #1032 defect) — 3 failed / 13 passed.
- Mutation 2: `acceptance.py:3210` `planning_seed = goal` (mis-computed seed) — 2 failed / 14 passed.
- Both restores by file copy from a scratch backup, digests compared, `git status` confirmed clean. No git verb was used to restore anything.
- The shipped detector helpers driven against 6 synthetic sources via `acc.__file__` redirection (`…/scratchpad/blindspots.py`).
- Programmatic reconciliation of all 11 tallied lessons' index flags against archive markers.
- `git show` diffs of `LESSONS.md` at the fold commit and its parent; `git ls-files`; on-disk existence and size of both claimed controls and the destructive-git hook.

**Did NOT examine (out of the assigned narrow scope):**
- The full pytest gate — explicitly instructed not to re-run it; I therefore cannot confirm the
  claimed 8779 / 0 / 0 / 125 figure or its re-measurement on merged main. **Unverified by me.**
- The 16 folded journal entries themselves — whether narrative was preserved verbatim from the
  deleted fragments, and whether lessons 296-300's *text* is well-formed. I checked 299's
  existence and control, not the prose quality of the mint batch.
- Lessons 3, 156, 171, 194, 265, 293 beyond their tally arithmetic — I did not read their
  recurrence prose for accuracy.
- `author_and_qa_job_oracle`'s own behaviour, the oracle-QA gate, or anything downstream of
  `generate_plan`. I verified argument threading only.
- The held-back 225 third-instance control (the sandbox-freshness check) — designed, not built;
  #1058 is the durable record and it was correctly out of this change.
- Whether `docs/journal_fragments/` is now empty apart from 989, and the fragment-deletion
  bookkeeping generally.

---

## ADDENDUM — concurrent edit observed during the final check (not a defect in `a89783f8`)

My closing re-run of the control file errored at collection:

```
E   File "…/shared/tests/test_acceptance_clarify.py", line 506
E       "def generate_plan(goal):
E   SyntaxError: unterminated string literal (detected at line 506)
```

**This is not my change and not a defect in the reviewed commit.** Every measurement in this
review was taken against the committed state, which was clean and 16/16 green at the time
(three separate green runs recorded above). `git status` shows the file is now ` M` with
+87/−26 from **another agent working concurrently in this tree**, and the content of the edit
makes its origin plain — the toggle-off test has become
`test_the_control_can_see_a_planted_violation(tmp_path, monkeypatch)`, now drives the *real*
`_bare_goal_consumers_after_seed` via `monkeypatch.setattr(acc, "__file__", …)`, and its
planted source has gained a `laundered = goal; new_ninth_consumer(laundered)` case. That is
this review's NIT and this review's FINDING being implemented while I was writing them up.

I did **not** touch that file — it is another session's in-flight work
(`<git_discipline>` shared-tree rule).

Two things follow, and both are coordination facts rather than review findings:

1. **The working tree is transiently unparseable right now.** Anyone running the standing gate
   before that edit lands will get a collection error (exit 4), not a test failure. It needs to
   settle before the next gate measurement is trusted.
2. **My FINDING should be considered already-addressed pending verification of that edit.** I
   have not reviewed the in-flight version and make no claim about its correctness — notably,
   whether the enumerator itself gained the alias/taint tracking, or only the *test* gained a
   laundering case it would then fail on. Those are different changes: the second without the
   first would plant a violation the shipped detector cannot see. **That needs an independent
   check once the edit is committed**, and it is not one I can make from a half-written file.

My verdict above stands unchanged: it is a verdict on `a89783f8` as committed and measured.

---

# VERIFICATION ROUND 2 — the fix at `b854d476`

Independent verification of the fix for my FINDING and NIT. I did not author it.

**Two corrections to my round-1 write-up, both accepted:**

1. **The work is NOT on `main`.** `main` is at `6df70ad5`; the fold lives on branch
   `docs/journal-fold-20260722` (`git branch --contains b854d476` → that branch only). My
   round-1 verdict framing ("nothing here warrants a revert") understated the leverage —
   nothing has landed, so a BLOCKER prevents a merge rather than requiring a follow-up. I
   restate the verdict on those terms at the end of this section.
2. **The concurrent edit in my ADDENDUM was the fold author's own**, not a third party — one
   author, one branch, a transient heredoc-escaping error since fixed. My conclusion (leave
   the file alone, a half-written file cannot be reviewed) was right; my inference about *who*
   was editing was wrong.

## R2.1 The alias tracking is REAL and it closes the gap — VERIFIED

`shared/tests/test_acceptance_clarify.py:408-419` now builds a one-hop alias set before the
consumer walk: post-mint `ast.Assign` nodes whose `value` is an `ast.Name` already in
`goal_aliases` contribute their `ast.Name` targets, and the call matcher tests membership in
that set rather than equality with `"goal"`.

Re-ran my round-1 scenario harness against the **new shipped helper** (same method: redirect
`acc.__file__` at a synthetic module, call the real function). `…/scratchpad/blindspots2.py`:

| scenario | round 1 | round 2 |
|---|---|---|
| A — `x = goal; author_and_qa_job_oracle(x)` | BLIND | **CATCHES** `{'author_and_qa_job_oracle': [6]}` |
| A2 — `x = goal; new_ninth_consumer(x)` | **BLIND (my finding)** | **CATCHES** `{'new_ninth_consumer': [7]}` |
| B — nested `def` | CATCHES | CATCHES |
| B2 — comprehension | CATCHES | CATCHES |
| C — wrapper `_helper(goal)` | CATCHES | CATCHES |
| D — `planning_seed = goal` | BLIND | **BLIND (unchanged, as the author stated)** |

Both laundering rows flipped. No previously-caught shape regressed. **The fix does what it
claims, and the author changed the enumerator itself — not merely the test.** That was the
specific risk I flagged; it did not materialise.

**D is confirmed still-blind and still honestly disclosed.** The author did not silently claim
to close it. I re-confirmed D remains covered by the two pre-existing behavioural tests:
mutating `shared/fleet/acceptance.py:3210` to `planning_seed = goal` in round 1 produced
2 failures (`test_requirements_thread_into_prompts_and_tasks_and_spec_goal_stays_clean`,
`test_requirements_reach_the_MULTI_task_job_oracle_author`). That coverage is unchanged by
this commit, which touches no behavioural test.

## R2.2 Is the stated limit honest? — three of four claims TRUE, one wrong direction, plus a fifth shape

The docstring (`:396-401`) claims alias tracking is one hop and flow-insensitive, and that a
goal laundered through **an attribute, a container, an f-string, or a chain of two locals** is
NOT tracked. I tested each rather than reading it:

| claimed-untracked shape | actual |
|---|---|
| `o.g = goal; f(o.g)` | BLIND — **claim honest** |
| `d['g'] = goal; f(d['g'])` | BLIND — **claim honest** |
| `s = f'{goal}'; f(s)` | BLIND — **claim honest** |
| `a = goal; b = a; f(b)` | **CATCHES** — claim is wrong, but *under*-claims |
| `if c: a = goal` then `b = a; f(b)` | BLIND |

Three of the four are exactly as stated. The fourth is over-modest, which is the harmless
direction — but the *mechanism* description is wrong in a way worth correcting, see NIT-2.

I also probed for shapes the limit list does not name that a reader would assume covered:

| probe | result |
|---|---|
| `p = q = goal; f(q)` (multi-target) | CATCHES — handled |
| `f(x := goal)` (walrus) | BLIND — contrived, acceptable |
| `x, y = goal, other; f(x)` (tuple unpack) | BLIND — unnamed |
| **`x: str = goal; f(x)` (annotated assign)** | **BLIND — unnamed, see FINDING-2** |

### [FINDING-2] `x: str = goal` is a one-hop alias the tracker misses, and the limit list does not name it

`shared/tests/test_acceptance_clarify.py:412` matches `isinstance(node, ast.Assign)`. An
**annotated** assignment is `ast.AnnAssign`, a different node type, so:

```python
x: str = goal
new_ninth_consumer(x)
```

is BLIND (demonstrated, row X1). This is not a two-hop or container case — it is exactly the
one-hop `x = goal` the docstring says IS tracked, wearing a type annotation.

Why this is a finding and not a nit: `CLAUDE.md <coding_standards>` mandates **"Python: strict
type hints"** for this repo. The annotated form is the *house idiom*, so the shape most likely
to be written by a future author is the shape the tracker cannot see — and the docstring's
limit list, which is otherwise scrupulous, does not warn them. A reader who checks the limits
before adding a call site would conclude they are covered.

**Fix (2 lines, same pass):** widen the alias collection to annotated assignments —

```python
if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.lineno > seed_line \
        and isinstance(node.value, ast.Name) and node.value.id in goal_aliases:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
```

(`AnnAssign.value` is `None` for a bare `x: str` declaration, which the `isinstance(..., ast.Name)`
guard already rejects.) Tuple unpacking (`x, y = goal, other`, row X2) is the same family and
stays uncovered by that fix — I would name it in the limit list rather than chase it, since it
is not idiomatic here. The walrus case (row X3) is contrived; ignore it.

### [NIT-2] The "chain of two locals" limit is stated absolutely but is actually order-dependent

The docstring says a chain of two locals is NOT tracked. Measured, it depends on AST walk
order, because the alias set is built during a single `ast.walk` (BFS) rather than in source
order:

- `a = goal; b = a; f(b)` — both at function-body level → **CAUGHT** (row L4)
- `if c: a = goal` … then `b = a; f(b)` — the first alias is one level deeper, so `b = a` is
  visited *before* `a` joins the alias set → **BLIND** (row L4b)

The direction is safe (the docstring under-claims, so nobody over-trusts it), which is why this
is a NIT. But "not tracked" describes the mechanism wrongly, and a successor who observes L4
being caught may reasonably infer chains are supported and then be surprised by L4b. Suggest
restating as: *"chains resolve only when the intermediate assignment is visited after the one
it copies — a single `ast.walk` pass, so a chain whose first link sits deeper in the tree is
missed. Do not rely on chain tracking."*

## R2.3 The toggle-off and the negative control — VERIFIED, both have teeth

`test_the_control_can_see_a_planted_violation` (`:492`) now takes `(tmp_path, monkeypatch)`,
writes a synthetic module, calls `monkeypatch.setattr(acc, "__file__", str(planted))`, and
asserts on the **real** `_bare_goal_consumers_after_seed()` output. The re-implemented walk is
gone. It also asserts `"decompose_request" not in offenders`, pinning the false-positive
direction too. My NIT is fully addressed.

The new `test_the_enumerator_does_not_flag_a_clean_function` (`:531`) is a genuine negative
control, proven by mutation. I replaced the enumerator's discrimination with
`takes_goal = True` (flag everything unconditionally):

```
3 failed, 14 passed
  FAILED test_every_post_seed_consumer_takes_the_planning_seed_not_the_bare_goal
  FAILED test_the_control_can_see_a_planted_violation
  FAILED test_the_enumerator_does_not_flag_a_clean_function
```

The negative control fires exactly as designed — "planted violation is caught" can no longer be
satisfied by an enumerator that flags everything. Restored by file copy, digest
`b455dc60e44e5cf8f4f215d0d8352b595ec28b254a90a2d3b9d6ed342a77ac7b`, `git status` clean.

## R2.4 End-to-end mutation of the laundered shape — 3 RED confirmed

Inserted `_laundered = goal` after the seed mint (`shared/fleet/acceptance.py:3211`) and passed
`_laundered` to `author_and_qa_job_oracle` (`:3443`):

```
3 failed, 14 passed
  FAILED test_requirements_reach_the_MULTI_task_job_oracle_author
  FAILED test_every_post_seed_consumer_takes_the_planning_seed_not_the_bare_goal
  FAILED test_the_job_oracle_author_is_reached_by_the_seed_not_the_goal
```

Matches the author's measurement of 3 RED. Restored by file copy, digest
`62bd29836db99118597c27628611f8f4ef9bbfdf83c3aadd704262573547838b`, `git status` clean,
17/17 green. No git verb was used to restore anything.

### [FINDING-3] The commit message's "(previously 0)" is wrong — it was 2

`b854d476`'s message states: *"a laundered `_laundered = goal` fed to `author_and_qa_job_oracle`
now turns 3 tests RED (previously 0)."* I measured the "previously" directly rather than
assuming it, by extracting the pre-fix control (`git show b854d476^:…`, read-only) over the
working file while leaving the same laundered mutation in place:

```
2 failed, 14 passed
  FAILED test_requirements_reach_the_MULTI_task_job_oracle_author
  FAILED test_the_job_oracle_author_is_reached_by_the_seed_not_the_goal
```

**Previously 2, not 0.** Laundering into an *already-pinned* site was never invisible — the
reached-by lock and the pre-existing behavioural lock both caught it, which is what my round-1
table already showed (row A: enumerator BLIND, reached-by CATCHES). The shape that genuinely
had **zero** coverage is laundering into a **new** consumer (row A2), where the enumerator is
the only lock that could ever fire.

So the fix's value is real but differently located than the message says: it closes A2
(0 → 1 lock) and adds defence-in-depth on A (2 → 3 locks). The claim as written overstates the
hole that existed.

This is a FINDING rather than a NIT because it is the same defect class this entire review
exists to police — a record asserting more than the measurement supports — and a commit message
is permanent, unamendable history once merged. It is also trivially fixable *right now*, since
nothing has landed. **Fix:** reword to "now turns 3 tests RED (previously 2; the
laundered-to-a-NEW-consumer shape was the one with zero coverage)."

## VERDICT (round 2): MERGE — after a one-line commit-message correction

The fix is **correct and complete for the gap I reported**. The author changed the enumerator
itself, not merely the test — the specific risk I flagged did not materialise. Alias tracking
flips both laundering rows from BLIND to CAUGHT with no regression to the five previously-caught
shapes; D remains blind, unclosed, and honestly disclosed, still covered by the two pre-existing
behavioural tests; the toggle-off now drives the shipped detector; and the new negative control
has real teeth under mutation. Three of the four stated limits are exactly true, which is a
better record than most limit disclaimers survive.

`main` is at `6df70ad5` and none of this has landed, so I am using that leverage as invited.
I am **not** raising a BLOCKER: neither remaining item can produce a wrong answer at runtime —
FINDING-2 is a hole in a test's coverage of a hypothetical future call site, and FINDING-3 is a
prose error. But FINDING-3 should be fixed **before** the merge rather than after, because a
commit message cannot be corrected once it is history, and this branch's whole subject is
records that claim more than they measured. FINDING-2 is a two-line change I would take now
while the file is open, given that the missed shape is the one the project's own coding standard
makes idiomatic; documenting it in the limit list is an acceptable alternative.

### What I drove vs. did not examine (round 2)

**Drove (executed):**
- `git show b854d476` + `git branch --contains`; confirmed unmerged, `main` at `6df70ad5`.
- The scenario harness re-run against the NEW shipped helper — 16 scenarios, including all four
  claimed limits and four candidate fifth shapes (`…/scratchpad/blindspots2.py`).
- Mutation A: enumerator forced to `takes_goal = True` → negative control RED (3 failed).
- Mutation B: `_laundered = goal` threaded to `author_and_qa_job_oracle` → 3 RED.
- Mutation B against the **pre-fix** control → 2 RED (disproving "previously 0").
- Three restores by file copy, each digest-verified, `git status` clean, 17/17 green at the end.

**Did NOT examine:**
- The full gate / the doctrine figure pair — the author's measurement, in flight, explicitly
  not mine.
- The lesson-47 `✓ctrl(partial)` change, the lesson-225 `⚠debt(#1058)` marker, the new legend
  line, and the `bdd3346f` tally-reconciliation commit — these answer the *curation* reviewer's
  findings, not mine, and a second reviewer should not silently adopt them.
- Tickets #1059 and #1060 (existence, predicates, wording).
- Whether `_laundered`-style aliasing occurs anywhere in the real `generate_plan` today; I
  tested the control's detection, not the production code's current cleanliness (the enumerator
  running green against the real file is itself that evidence).
