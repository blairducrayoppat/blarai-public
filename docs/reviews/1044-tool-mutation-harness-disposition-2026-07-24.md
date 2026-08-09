---
title: Finding disposition — mutation-harness-1044 tool branch review
status: record
area: reviews
---

# Disposition — `tools/mutation-harness-1044` independent review

**Change under review:** BlarAI branch `tools/mutation-harness-1044`@`8ebbebdd` (cut from main
`78c4186d`) — a dev-only mutation-testing harness (`tools/mutation_harness/run_1044_mutations.py`)
built to independently verify the #1044 bad-input-floor's test coverage by mutating shared source
and confirming the suite catches every mutation.

**Reviewer:** independent agent dispatch (isolated worktree), author≠verifier — the reviewer did not
write the tool and reproduced every claim by execution rather than by reading commit messages.

**Verdict:** MERGE. All 6 required claims independently reproduced (gate-collection immunity,
no-default-mutation-root, all four dirty/attached/self-repo/no-args refusal paths triggered live,
per-root LOCALAPPDATA derivation confirmed on disk, the "ring six" busy-vs-stranded-tree residual gap
honestly documented not overclaimed, and a real end-to-end run measuring 0/29 survived with restore
independently verified via `git status`/`git diff`, not the tool's own self-report).

## Why this record exists

`<deferral_discipline>` binds any pass that returns findings, including a clean MERGE verdict that
still surfaces one non-blocking observation.

```disposition
missing-pre-mutation-baseline-assertion | DEFERRED | #1103 blocked-by: a pre-mutation baseline-green assertion that does not yet exist in tools/mutation_harness/run_1044_mutations.py; the observable predicate is that assertion, refusing loudly when the baseline run is deliberately broken (e.g. wrong interpreter path) and staying quiet when the baseline is healthy
```

## What the review validated and should not be re-litigated

The four refusal paths (no-args, nonexistent dir, self-repo, attached-branch, dirty-tree) were each
triggered LIVE against real throwaway trees, not read about. The end-to-end mutation run (0/29
survived) was independently reproduced by the reviewer in its own fresh detached worktree at
`afa40bf7`, with `git status`/`git diff`/`git rev-parse HEAD` all checked afterward rather than
trusting the tool's own "restore verified" line — this is the same standard the tool itself was
built to enforce on #1044's claims, now applied to the tool.

## The one finding, plainly

The harness has no explicit pre-mutation baseline run asserting the two target suites are green on
UNMUTATED code before the mutation loop starts. `run()`'s only signal for "GREEN (survived)" is
`returncode==0` on the mutated run; anything else — including a broken environment unrelated to the
mutation itself — buckets as "RED (caught)", indistinguishable from a genuine catch. Same family as
the vacuous-check-vs-guard-that-cannot-fire class this whole night's work was hunting, in the form of
a missing guard rather than a guard that cannot fire. Not currently biting: the reviewer's real run
produced 29 distinct, semantically-appropriate RED verdicts (each naming the specific test that caught
that mutation), which is itself evidence of a healthy environment for that run. Filed as #1103 with a
one-line, cheap fix named (run the suites once unmutated first, refuse loudly if not green) rather
than deferred on vibes.
