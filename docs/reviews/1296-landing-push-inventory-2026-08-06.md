---
title: "#1296 landing push — the inventory"
status: evidence
area: governance
date: 2026-08-06
---

# #1296 landing push — what is actually out there

**Measured 2026-08-06 evening local, against `main` @ `85677aeb`.** Every number below came
out of a script over `git`, not out of a reading of ticket prose — the commands are in §5 so
a later session can re-run them rather than trust this file. #1296 requires this inventory to
be published *before* anything is landed, on the grounds that the ranking is worthless without
it. That turned out to be right for a reason nobody had written down: see §2.

## 1. The count

**26 branches are not merged into `main`.** #1296 measured 28 this morning; #1289 (`c2a3f8f0`)
and #1281 (`20f922be`) landed during the day, which accounts for the difference exactly.

The raw branch total is **411** and remains the wrong number to quote — 385 of those are
already in `main` and simply were never deleted, because destructive git is forbidden here.
Merged branches accumulate permanently by design.

## 2. The finding that changes the ranking

#1296 assumed the useful split was rot risk. It is not. It is **evidence**.

Of the 26 branches, the number carrying a recorded standing-gate figure is **one** —
`feat/746-search-docs-cli-v2`, which records `9940 passed`. Today's baseline is **10313**.
That figure is **373 tests stale**, so it is evidence about a repository that no longer
exists. Three more branches assert green in prose with no number at all ("gate green",
"0 failed" with no total). The remaining **22 have no gate evidence of any kind.**

A fourth, `fix/1204-salvage-goal-set`, mentions the standing gate only to say it is *waiting*
on an in-flight count — it reads like evidence in a keyword scan and is the opposite of it.
That one is worth remembering: prose-matching for "gate" finds the branches that talk about
the gate, not the branches that passed it.

**So the honest answer to "which of these could land this hour" is: none of them.**
Every single one needs a build and a gate run before it can be reviewed, let alone merged.
That is a materially different plan from "pick the low-rot ones and merge them", and it is
the reason #1296 insisted the inventory come first.

## 3. Four groups, not 26 individuals

**(a) Three ancient branches that are not feature work at all.**
`copilot/worktree-2026-03-13T06-25-42` and `fix/vpux-crash-reproduction-intel-pr` have
**byte-identical tips** (`e151a6750404c717944a8d16563ade8fbf2593ca`); `feature/openvino-contrib-agent`
(`734ec9ab`) is the same shape. All three are ~3037 commits behind and carry ~1,046,000
insertions. Those insertions are **model export artifacts** —
`phase2_gates/evidence/intel_pr_reproduction/qwen3-0.6b-fresh-export/tokenizer.json` alone is
757,480 lines, plus `merges.txt` and `openvino_model.xml`.

These must not be landed. Model artifacts are gitignored by policy, and merging a million
lines of exported weights into `main` would be a defect, not a ship. They need classifying
(SUPERSEDED, or PARKED with a predicate naming where the Intel-PR evidence properly lives) —
and the two identical tips mean at most one classification decision is needed, not two.

**(b) One branch that is a snapshot, not work.** `backup/wip-rolling` (41 commits ahead,
1 day old) contains exactly six files: `SoCWatchHelp.json`, `blarai_lighthouse3.png`,
`blarai_logo_linkedin.jpg`, `cook_test.html`, `hand2.png`, `si.js`. **Those are precisely the
six untracked files currently sitting in the primary checkout.** It is a rolling WIP snapshot
of loose operator files, not a feature branch, and it should never be evaluated as one.

**(c) Two integration/staging branches.** `integration/0730-evening` and
`integration/1075-check-2026-07-24` are merge-staging branches by their own commit subjects
("test-merge: #1075...", "Merge branch 'docs/1206-746-not-blocked' into integration/0730").
Their content most likely reached `main` by other routes; each needs a per-commit
already-applied check before anyone treats them as outstanding work.

**(d) Twenty genuine work branches**, the real subject of the landing push.

## 4. The table

Sorted by rot risk, then by how far behind `main` each branch is. `churn 4w` is how many
commits `main` took in the last four weeks under that branch's own paths — the measure of how
fast the ground is moving underneath it.

| branch | tip | age d | ahead | behind | churn 4w | rot | files | worktree | gate evidence |
|---|---|---|---|---|---|---|---|---|---|
| `copilot/worktree-2026-03-13T06-25-42` | `e151a675` | 149 | 22 | 3037 | 662 | **HIGH** | 45 | none | UNKNOWN - - |
| `feature/openvino-contrib-agent` | `734ec9ab` | 112 | 23 | 3037 | 662 | **HIGH** | 45 | none | UNKNOWN - - |
| `fix/vpux-crash-reproduction-intel-pr` | `e151a675` | 149 | 22 | 3037 | 662 | **HIGH** | 45 | none | UNKNOWN - - |
| `feat/746-research-wiring` | `c96b65bd` | 31 | 1 | 1405 | 845 | **HIGH** | 8 | none | UNKNOWN - - |
| `feat/763-oracle-to-coder` | `90fbc3d4` | 25 | 1 | 1059 | 416 | **HIGH** | 2 | clean | UNKNOWN - - |
| `feat/843-c1-read-surface` | `f2e93531` | 25 | 1 | 1055 | 431 | **HIGH** | 19 | clean | UNKNOWN - - |
| `fix/911-gap-prompt-datamark` | `832f1a9c` | 21 | 1 | 875 | 737 | **HIGH** | 3 | none | UNKNOWN - - |
| `feat/774-st2-procspawn-migration` | `1bfe25e1` | 20 | 1 | 780 | 861 | **HIGH** | 9 | clean | CLAIMED - "gate green", no figure |
| `docs/pub-p1-drafts` | `46695dff` | 18 | 3 | 733 | 662 | **HIGH** | 5 | clean | UNKNOWN - - |
| `docs/pub-p2-drafts` | `07cc0ec1` | 18 | 2 | 733 | 662 | **HIGH** | 4 | clean | UNKNOWN - - |
| `fix/967-d1-submodule-invented-contract` | `2cb97a5e` | 18 | 1 | 731 | 844 | **HIGH** | 6 | none | CLAIMED - "0 failed", no total |
| `feat/1067-negation-aware-guard` | `bdc51069` | 14 | 2 | 478 | 294 | **HIGH** | 2 | none | UNKNOWN - - |
| `feat/1067-v4-whole-text` | `79e24fee` | 14 | 2 | 461 | 822 | **HIGH** | 4 | clean | UNKNOWN - - |
| `feat/1067-v5-closed-accept-surface` | `41e200e1` | 14 | 6 | 461 | 822 | **HIGH** | 24 | clean | UNKNOWN - - |
| `integration/1075-check-2026-07-24` | `458e3aea` | 14 | 1 | 376 | 803 | **HIGH** | 6 | none | UNKNOWN - - |
| `fix/1117-dialog-preserves-typed-text` | `3a2e7177` | 9 | 1 | 280 | 323 | **HIGH** | 2 | clean | UNKNOWN - - |
| `feat/746-search-docs-cli` | `e69cdf4f` | 7 | 1 | 136 | 354 | **MED** | 3 | clean | UNKNOWN - - |
| `feat/746-search-docs-cli-v2` | `7a5f736b` | 7 | 2 | 134 | 241 | **MED** | 3 | clean | MEASURED - `9940 passed` - STALE, 373 behind today's 10313 |
| `fix/1181a-pin-dispatch-scripts` | `794de269` | 7 | 9 | 121 | 371 | **MED** | 5 | clean | UNKNOWN - - |
| `fix/1200-oracle-qa-uv-python` | `b9ee43c8` | 7 | 5 | 121 | 861 | **MED** | 8 | clean | CLAIMED - "0 failed", no total |
| `feat/1195-l4-kills` | `f7d9d259` | 7 | 1 | 118 | 871 | **MED** | 9 | clean | UNKNOWN - - |
| `integration/0730-evening` | `684ddcc4` | 7 | 10 | 111 | 892 | **MED** | 18 | clean | UNKNOWN - - |
| `fix/1231-budget-honesty` | `ca8ca3a6` | 7 | 1 | 103 | 429 | **MED** | 5 | clean | UNKNOWN - - |
| `fix/1204-salvage-goal-set` | `95eb90b1` | 7 | 2 | 60 | 662 | **MED** | 4 | clean | UNKNOWN - prose names the gate only to say it WAITS on an in-flight count |
| `fix/uc010-dormancy-docstring-rot` | `8e34a393` | 0 | 1 | 36 | 737 | **MED** | 2 | none | UNKNOWN - - |
| `backup/wip-rolling` | `b07fc24e` | 1 | 41 | 58 | 0 | **LOW** | 6 | none | UNKNOWN - - |

`backup/wip-rolling` shows churn 0 because its six files are untracked in `main` — there is
no history under those paths to move. It is LOW-rot in the arithmetic and out of scope in
reality; see §3(b).

## 5. How to reproduce this

Read-only, no checkouts, no worktree changes. Run from the primary checkout:

```bash
git branch --no-merged main --format='%(refname:short)'          # the 26
# NOTE: returns 27 once `docs/0806-baseline-derivation` exists - the branch carrying
# THIS file, created after the measurement. Exclude it and you get 26. A later reader
# who gets 27 has not found a discrepancy; they have found this file.
git rev-list --count main..<branch>                              # ahead
git rev-list --count <branch>..main                              # behind (the rot measure)
git diff --name-only main...<branch>                             # files touched
git log main --since='4 weeks ago' --oneline -- <its top dirs>   # churn under those paths
git log main..<branch> --format='%B' | grep -oE '\b(9|10)[0-9]{3} passed'   # gate evidence
git worktree list --porcelain                                    # which branch has a tree
```

Rot was scored, not felt: HIGH = churn >= 40 under its own paths AND >= 150 commits behind;
MED = churn >= 15 or >= 250 behind; LOW otherwise.

## 6. What this pass did NOT do, stated so nobody assumes it

- **No branch was reviewed.** This is an inventory of position and evidence, not of quality.
  Author != verifier still applies to every one of these, and today's two landings both
  turned up blocking-class defects in work that had been reported green.
- **No gate was run on any branch.** That is the 26-fold cost this inventory exists to
  schedule rather than to pay blindly.
- **No terminal state was assigned.** §3 proposes groupings; the four terminal states in
  #1296 get assigned per branch, on its own ticket, with evidence.
- **Nothing was deleted, pruned or cleaned.** Explicitly out of scope per #1296.
- **Ticket cross-referencing is not in this pass.** Each branch's ticket DESCRIPTION still
  needs reading before its terminal state is decided — several branch names name a ticket,
  but a name is not a claim about status.

## 7. The scheduling consequence

Because every branch needs a build and a gate before review, and a gate run is ~5.5 minutes
of an otherwise-quiet box, landings are **serial by construction** and cannot be stacked
against a battery run. Tonight's evidence for that is direct: a B5 battery launch at 16:55
failed to boot the Assistant Orchestrator at all (the Policy-Agent mTLS handshake timed out
on all 16 attempts) while six subagents and a collection run were loading the machine; the
identical launch on a quiet box at 17:09 brought the AO up in **39 seconds**. Heavy loads do
not merely slow each other down here, they make each other fail — and the failure presents as
something else entirely.
