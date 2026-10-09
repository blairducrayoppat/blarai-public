# Independent pre-merge review: #1690 rules tooling (2026-10-05)

Reviewer: independent adversarial reviewer (did not author either branch). Report only, no fixes.

Tested at:
- `feat/1690-git-rule-hooks` @ `6d7b719f` (worktree C:/Users/_OPERATOR_/blarai-wt-1690-hooks)
- `feat/1690-rules-corpus` @ `717d0039` (worktree C:/Users/_OPERATOR_/blarai-wt-1690-corpus)
- both one commit off main `caab37f2`; hashes re-checked unchanged at the end of the review.

Suites run (LOCALAPPDATA=$(mktemp -d), .venv Python 3.11.9, one file at a time):
- `tests/security/test_git_rules_guard.py` @6d7b719f: 91 passed. Same on the merged tree.
- `tests/security/test_rules_corpus.py` @717d0039: 26 passed. Same on the merged tree.
- Merged tree (detached worktree of `caab37f2` at C:/Users/_OPERATOR_/blarai-wt-1690-review-merged, `merge --no-ff` of both, then removed):
  `test_doctrine_freshness.py` 19 passed, `test_doc_pointers_and_banners.py` 34 passed. (When the merged worktree sat in the
  scratchpad, the doc-pointer test failed 2 on ADR-013's `../../../devplatform/...` link. That is caused by where the worktree
  sits, not by either branch. At a sibling path of the repo it passes.)
- `scripts/extract_rules_corpus.py --check` on 717d0039: exit 0. CLAUDE.md is byte-identical to main (`git diff caab37f2` is empty).

The guard probes were run as real `python scripts/hooks/git_rules_guard.py` processes fed stdin JSON, using the same `python` on PATH
(3.14.3) that the hook command uses, against real temp repos on `main` and `feat/x`. The driver and case tables are in the
session scratchpad: drive.py, t1.py to t6.py.

## Hook contract (checked against https://code.claude.com/docs/en/hooks)

The builder's claims are confirmed. The PreToolUse stdin carries `tool_name`, `tool_input.command` and `cwd`. PowerShell uses the
same `command` field. Exit 2 blocks the call and feeds stderr to the model. Exit 1 or any other non-2 exit is non-blocking, so the
call proceeds, and a timeout also lets the call proceed. `"Bash|PowerShell"` is a valid exact-match list, and both tool names are
exact. `shell: "bash"`, `timeout` and `statusMessage` are valid fields. `${CLAUDE_PROJECT_DIR}` points at the project root where
the session started and does not follow a worktree. Hooks from the user and project levels merge and run in parallel. A hook
process inherits the parent environment. Hook edits are hot-reloaded.

## Findings

### Git guard (`feat/1690-git-rule-hooks` @ 6d7b719f)

**N1 · BLOCKING: the guard blocks a commit that CLAUDE.md allows on main, and the only way through is a relaunch by the LA.**
- Where: scripts/hooks/git_rules_guard.py:271 (`_check_commit`), and docs/governance/git-rules-guard.md:42-44 ("companion commits
  on main need the override").
- CLAUDE.md git_discipline says: "The one sanctioned commit type on main is the merge commit ... **(plus its atomic ticket/journal
  companions)**." The guard blocks every non-merge commit on main. Its only escape is an environment variable that must be set
  by hand before Claude Code launches. A session cannot set it, and the LA is non-technical.
- How often this happens: `git log --first-parent --no-merges --since=2026-09-01 main` gives **9 of 102** first-parent commits on
  main. They include companions such as `68306937 docs: the gate baseline is confirmed on MERGED MAIN` and five `docs(#930)` commits.
- What it costs: about one ship in ten stalls at the guard. Either the doctrine or the guard has to change, in the same change,
  before merge. Today the two disagree, and a session that hits the guard either stops or routes around it (N4 lists working
  detours).
- Reproduced: `git commit -m x` with cwd on main gives exit 2, "the only commit allowed on main is the merge commit".

**N2 · SHOULD-FIX: the doc says a missing script "fails open", but it blocks every shell call. The doc's own user-level wiring
would block every Bash and PowerShell call in every project today.**
- Where: docs/governance/git-rules-guard.md:26-30.
- When Python cannot open the script it exits with **code 2**, which Claude Code treats as a block, for every Bash and PowerShell
  call, `ls` included. The suggested user-level entry `python "C:/Users/_OPERATOR_/BlarAI/scripts/hooks/git_rules_guard.py"` points
  at the primary checkout. That checkout is on `feat/1616-corpus-tier` right now, which has no `scripts/hooks/`.
- Reproduced:
  `echo '{"tool_name":"Bash","tool_input":{"command":"ls"}}' | CLAUDE_PROJECT_DIR=C:/Users/_OPERATOR_/BlarAI bash -c 'python "${CLAUDE_PROJECT_DIR}/scripts/hooks/git_rules_guard.py"'`
  gives `can't open file ... rc=2`. With `CLAUDE_PROJECT_DIR` unset it also gives rc=2.
- The project-level wiring is mostly safe, because settings.json and the script appear and disappear together and hooks
  hot-reload. Only the documented user-level option and the "fails open" sentence are wrong.
- Related: `.claude/settings.json` is not locked by any test. A typo in the matcher, or the command path, would still pass all 91
  tests. The guard can be reached only through that file.

**N3 · SHOULD-FIX: a lock requires a known defect. A fast-forward `merge --no-commit` followed by `commit` produces a non-merge
commit on main.**
- Where: git_rules_guard.py:333-335 (`merge_pending` is set from `--no-commit` alone), and the lock
  tests/security/test_git_rules_guard.py:182-183 `test_merge_no_commit_then_commit_allowed`. In that lock's fixture the main
  repo has no `feat/x` branch, so it never shows that a merge commit actually results.
- Reproduced (temp repo, main behind feat/a, a staged change): the guard returns `(0, [])` for
  `git merge --no-commit feat/a && git commit -m sneaky`. Real git fast-forwards, leaves no MERGE_HEAD, then records
  `e4612cd parents=772db0e sneaky`, a single-parent commit on main.
- A related check that also reads disk state: a leftover MERGE_HEAD pointing at an already-merged commit. The guard allows the
  commit and git writes a single-parent commit (`7568f85 parents=e4612cd`). How often this happens is unknown, and it is rare.

**N4 · SHOULD-FIX: forms that should be blocked but pass. The guard misses blanket staging and commits on main that git really
executes.** Every allow below was run through the guard. For the git-semantic cases, real git was run on a temp repo to confirm
the effect.

| Command | Guard | Real git effect |
|---|---|---|
| `git add -u` (and `--update`) | ALLOW, and the lock lists it as allowed (test file:100) | stages every tracked modification. This is the same sweep as `commit -a`, which the guard blocks. `git add -u && git commit` is `commit -a` in two steps |
| `git add --al` | ALLOW | git accepts the abbreviation and staged the untracked `u` |
| `git stage -A` | ALLOW | `stage` is a built-in synonym for `add`, and it staged `u` |
| `git add ':/*'` | ALLOW | staged everything repo-wide |
| `git commit -m x :/` (also `-- .` at root) | ALLOW | committed every tracked change repo-wide, so it is a blanket commit |
| `GIT_DIR=../main/.git git commit`, `export GIT_DIR=...;`, `$env:GIT_DIR=...` | ALLOW | the guard strips the env prefix and checks the branch of cwd, not of GIT_DIR |
| `git checkout - && git commit` (previous branch main) | ALLOW | the commit lands on main |
| `git symbolic-ref HEAD refs/heads/main && git commit` | ALLOW | the commit lands on main |
| `git cherry-pick`, `git revert`, `git am`, `git commit-tree` on main | ALLOW | non-merge commits on main. cherry-pick and revert are documented limits; am and commit-tree are not |
| `git push . HEAD:main`, `git fetch . feat:main`, `git branch -f main HEAD`, `git update-ref refs/heads/main HEAD` | ALLOW | puts feature commits onto main with no commit at all |
| ``echo `git add -A` ``, `eval git add -A`, `bash -ce '...'`, `echo 'git add -A' \| bash`, `bash <<'EOF'` body, `nice/timeout git add -A`, `xargs git add`, `iex '...'`, `cmd /c git add -A` (unquoted), PowerShell splat `git @a`, `Start-Process git` | ALLOW | the documented limit names only a "quoted `$(...)`". Unquoted backticks, eval, piped or heredoc shells and runner prefixes are not documented |

- Which of these a model would plausibly write without trying to evade: `git add -u` (common), pathspec commits at the root, and
  `timeout N git ...`. The rest are evasions. The guard says it is a backstop, not a boundary, which is a fair description. But
  `add -u`, `--al`, `stage` and `:/*` are one-line fixes. GIT_DIR in the environment, both inline and exported, is a real gap in
  the "branch of the target repo" check.
- What the review could NOT break: every listed form of `-A`, `--all`, `.`, `*`, `:/`, `-fA`, `-Av` and `-- .` in any segment.
  Also: after `;`, `&&`, `||`, `|`, `&`, `( )` and `{ }`; after env prefixes, `command`, `exec`, `time`, `\git`, a full-path
  git.exe, `--no-pager`, `-c` and `-ccore.x=y`; with `-C`, `--git-dir`, `--work-tree`, `bash/sh -c` and `-lc`; inside if/for
  bodies; across line continuations in both shells; and as `& git` / `& "...git.exe"` / `Invoke-Command { }` in PowerShell.
  `git commit -a/--all/-am/-sa/-qa/-vam/-m x -a` are all blocked.

**N5 · SHOULD-FIX: the guard applies to every repository, not only BlarAI, while the destructive-git hook it sits next to is
scoped by repo.**
- Where: git_rules_guard.py:36 and :271. There is no repo scope, while block_destructive_git.py:40-48 scopes itself.
- If a BlarAI-rooted session commits in another repo that is on main, it is blocked. agentic-setup is on main, with **4 of 11**
  first-parent commits since 09-01 being direct non-merge commits. devplatform is on main with 1 of 1. A detached HEAD always
  blocks, which also covers commits in a detached worktree, such as patching the public mirror off `public/main` (hypothesis:
  the exact public-sync commands were not found on disk).
- No collision with the dispatch fleet: it runs opencode, not Claude Code, so no hooks load, and `scripts/*.ps1` calling
  `git add -A` internally is not visible to a command-string hook. No collision with block_destructive_git.py either: both run in
  parallel, and a deny from either one wins.

**N6 · NOTE: things the guard blocks that are legitimate (all in the fail-closed direction, each costing one retry).**
- `git worktree add ../wt -b feat/z && cd ../wt && git commit` is blocked with "cannot determine the current branch", because the
  directory does not exist yet when the hook runs. This is the CLAUDE.md parallel-work pattern done in a single command.
- `git checkout feat/y && git commit` and `git switch feat/y && git commit` from main are blocked, because only `-b` or a protected
  name moves `branch_override`.
- `(cd ../main && git status); git commit` is blocked, because the subshell `cd` leaks into later segments.
- `git -C "$WT" commit`, `cd "$(git rev-parse --show-toplevel)" && git commit` and `git commit -m $'don\'t'` (ANSI-C quoting) are
  blocked. The first two are deliberate (dynamic path).
- `Push-Location ../main; git commit` is the opposite case, wrongly allowed, because `push-location` is not in `_CD_WORDS`.
- What the review could NOT break on the false-positive side: about 90 ordinary commands passed, including the merge ritual
  (`merge --no-ff ... -m`, `-C <main> merge`, `merge --no-ff --no-commit && commit`), explicit-path adds,
  `git add -p/-N/-f/--/./docs/x.md/.gitignore`, every commit option that takes a value (`-m -F -C -c -t -S --author --trailer
  --fixup --message=all -m -a -m'-a'`), heredoc and here-string messages that contain `git add -A`, `commit -am` and `main`
  (including apostrophes and an indented terminator), `git log --oneline main`, `checkout main && git log`, `stash
  list/push/pop`, `worktree add/list/remove`, and grep, echo, rg and Select-String over the literal text.

**N7 · NOTE: what the override reads is correct, and part of its documentation is right.**
- Reproduced: `BLARAI_GIT_RULES_OVERRIDE=x git add -A`, `export ...;` and `$env:...=` written inside the command all stay
  blocked. The process-environment override allows the call and writes
  `{"ts":..., "reason":"LA test", "rule":"blanket-add", "command":"git add -A"}`. When the log path is unwritable the call stays
  blocked. A whitespace-only value is ignored.
- Hypothesis, not run: a session that edits `.claude/settings.local.json` `env`, or the guard's own `ENABLED`, defeats the guard.
  That sits at the same trust level as editing the hook, so it is acceptable for a backstop.
- Gaps: the log location `~/.claude/logs/` is shared with other tooling, and nothing reports overrides. The override stays set for
  the whole process ("unset it after use" is a manual step).

**N8 · NOTE: fail-closed behaviour checked.**
- Blocked (exit 2): malformed JSON, empty stdin, a JSON list, `tool_input` as a string (the message wrongly says "not valid
  JSON"), UTF-16 input, non-UTF-8 bytes.
- Large inputs are handled quickly: a 5 MB command took 0.9 s, 200k segments 0.7 s, 300k quoted tokens 0.3 s, a 100k-line
  unterminated heredoc 0.3 s. No pathological slowness was found.
- Allowed: `tool_input: null`, a `command` that is a list, and a missing `tool_name`. All are harmless because the matcher
  already filters on tool name.
- Fails open: an interpreter crash before `main()` (exit 1), `python` missing from PATH (127), and the hook timeout (20 s, against
  two 10 s git calls). This matches the stated contract.

**N9 · NOTE: the guard's mutation coverage is real.** Six extra mutants were each caught by the existing suite, run on a temp
copy: heredoc stripping removed (1 fail), MERGE_HEAD on disk ignored (2), checkout tracking removed (1), nested shells disabled
(2), override not logging (2), `-a` no longer detected inside combined flags (4).

### Rules corpus (`feat/1690-rules-corpus` @ 717d0039)

**N10 · BLOCKING: 7 of the 26 "enforced" mappings are false or point at the wrong file, and README step 4 tells reviewers to
treat them as already checked.**
I opened each referenced file. For 22 of the 26 records I compared what it tests with what the rule says.
- `testing.standing_gate.selection-...` maps to kind `gate`, ref `docs/TEST_GOVERNANCE.md`. That is a document, not an enforcing
  mechanism, and the record's own note says "documented, run by the lead". This takes the rule off the gap list.
- `testing.protect_the_gate.the-gate-must-not` maps to `tests/test_port_leak_detector.py`. That file's docstring says it is
  "OUTSIDE the explicit-path standing gate ... the standing gate does NOT collect it". The enforcing code is the autouse fixture
  in conftest.py.
- `testing.standing_gate.every-fix-ships-its` maps to `tests/security/test_timeout_ordering.py` for "timeout-registration". That
  file tests outer and inner budget ordering (#1122). The registration lock is `tests/integration/test_timeout_registry.py`
  ("B. DISCOVERY ... a new timeout cannot land invisibly"), which is not mapped.
- `maintenance.volatile-state-lives-only` maps to `test_status_claims_are_dated.py`. That test checks that LIVE/ARMED/DORMANT
  claims in other docs carry dates. It never mentions `status_snapshot` (grep finds 0 hits) and does not test the rule.
- `security_by_design.principles.n08` (LEAST DATA) maps to `test_ipc_frame_cap_agreement.py`. That test locks cap AGREEMENT across
  both channel ends, after a cap was raised. It does not test minimisation.
- `principles.n03` (independent locks) maps to `test_trust_spine_canary.py`, which tests that a door loaded. Nothing in it tests
  independence.
- `principles.n11` (FAIL-LOUD security controls) maps to `test_instrument_toggles.py`, which tests renderers for measurement
  instruments, not security controls.

Why the mechanism allows this: a mapping is "found" when a single regex term appears anywhere in the file (`5001`, `date`, `cap`,
`canary`). That proves the file mentions a word, not that it enforces the rule.

**N11 · SHOULD-FIX: enforcement the builder missed, so the gap list is wrong.**
- `critical_rules.n03` and `identity_split.failure_modes.n01` (no network or cloud dependencies in runtime code) both read `none`.
  The suggested "Import-scan test ... same shape as the single-file httpx import scan" already exists:
  `tests/security/test_no_external_egress.py` forbids `requests`/`httpx`/cloud and LLM SDKs in runtime modules.
- The timeout registration half: `tests/integration/test_timeout_registry.py`, as above.
- `journal_discipline` entry form: `tests/security/test_journal_integrity.py` checks chronology and duplicates. That is partial,
  but it is enforcement, and the gap list's own suggestion names this file.
- The spot-check covered 15 `none` records: n01, n02, n05, n06, n07 and n09 of critical_rules; principles n04, n09 and n13; both
  absolute_rules; and four journal, vikunja and perf rows. Rows not listed above held up: no enforcement found.

**N12 · SHOULD-FIX: inserting one rule into a numbered list silently moves enforcement onto the wrong rules, and the test's fix
instruction approves the result.**
- Where: extract_rules_corpus.py:222-232 select by `nNN` with text regex `r"."` (anything), and ids are list positions.
- Reproduced by in-memory edits to CLAUDE.md, comparing records that have the same text before and after:
  - **E2, a new principle inserted as #4:** 10 records change id and **9 change enforcement**. STRUCTURAL ABSENCE inherits the
    door test, BORN-ENCRYPTED inherits `test_purpose_unforgeable`, ISOLATION inherits the signed-manifest posture pin, HARDWARE
    INTEGRITY inherits `test_instrument_toggles`, and EVERY CONTROL TESTED OFF loses both of its mappings.
  - **E1, a new critical rule #5:** 6 ids change, and critical rules 8 (LOCALAPPDATA) and 10 (landing card) silently drop to
    `none`.
  - **E3, rewording the opening words of two bullets:** 2 slug ids change. This is expected under the scheme.
- README:28-29 says "Editing elsewhere never renumbers a rule". That is true only for edits outside the list. No slug collisions
  exist today (0 near-collisions), and a future collision raises and turns the gate red.
- The test's FIX message is "Run: python scripts/extract_rules_corpus.py". Running it approves the wrong mappings and the gate goes
  green again. So the docstring's "silently degrades ... trips the committed-vs-fresh check" claim produces an approval step, not
  a review.

**N13 · SHOULD-FIX: excluding sections by name drops real rules.** Seven top-level tags and two `facts` sub-tags are excluded
whole. About 18 lines in them are imperatives the corpus never sees:
- stack: "Toolchain hygiene ... never in the runtime .venv"; "Never state which scopes are live from memory or from a docstring";
  "Do not propose swaps as routine improvement"; "build REQUIRES `-p:Platform=x64 ...`".
- host_environment: "Overnight/scheduled GPU work MUST launch via elevated Scheduled Task"; "Measure RAM as In-Use ..."; "Big
  jobs ... must explicitly evict".
- repo_constellation: "build no new dependencies on it"; "public/main ... never merged directly".
- live_state_pointers: "DoD work: USE agent `dod-witness`"; "Read it before ranking work".
- user_operator/facts: "NEVER 'prototype'".
- authority: "keep this terse directive register".

In the other direction, a few pure facts or rationale sentences are included, for example `vikunja.update-task-is-a` ("update_task
is a full PUT", which is FIELD_NOTES material) and `vikunja.the-board-is-what`. Severity and owner assignments are consistent
with the README (12 critical, 13 high, 124 normal; 5 LA).

**N14 · SHOULD-FIX: after both branches merge, the corpus contradicts the guard.** `critical_rules.n04` and both
`git_discipline.absolute_rules` / `shared_tree` "no `git add -A`" records still read hook-external-only or `none`. Their note says
"does not cover git add -A or commits on main", and the gap list suggests building exactly the guard N1-N9 review. Nothing trips,
because `ENFORCEMENT` has no entry for `scripts/hooks/git_rules_guard.py`. Whichever branch merges second should add that entry.
The `external:` ref for the destructive hook is never checked on disk either.

**N15 · SHOULD-FIX: the "cheapest check" column is mostly generated from keywords.**
- 29 rows suggest "Pre-commit or pre-merge hook asserting the git invariant named in the rule", including "Time is the scarce
  resource" and "Committed ≠ done".
- 17 rows suggest a Vikunja API script, including "Stop doomed runs fast".
- 34 rows read "No cheap deterministic check".

Only the 9 hand-written critical-rule suggestions are specific, and one of them proposes a test that already exists (N11). The
column advertises "suggestion, not decision", but as written it is noise for about 46 rows.

**N16 · NOTE: one trailing space in CLAUDE.md, even inside the excluded status_snapshot, turns the gate red.**
- Reproduced: E4 adds a trailing space to the snapshot "Phase 5 ACTIVE" line, and E5 indents a continuation line. The extractor
  raises "leading/trailing whitespace is not a known shape", so `test_rules_corpus` fails.
- The snapshot is refreshed at every merge cluster. Failing closed here is defensible, but the whitespace rule applies before
  sections are classified, so fact-only edits can break the gate.

**N17 · NOTE: the corpus diverges from the analysis it implements**
(C:/Users/_OPERATOR_/blarai-research-data/ideation/rules-corpus-skills-analysis-2026-10-05.md §6).
- The analysis said the hand-authored why/scope/enforcement fields would be *preserved* by the generator, and "enforcement:none
  has no ticket" would fail the test. The build instead generates enforcement from a code table, and 120 `none` records carry no
  ticket.
- The analysis said to start with about 35 explicit rules. The build has 149.
- Ticket #1690 item 3, the rules-review procedure proven on a real diff and mutation-checked, and the skills audit are not on
  either branch. README "How a reviewer uses it" is an unproven procedure. The ticket cannot close on these two branches.

**N18 · NOTE: test certification.**
- Four corpus mutants were run on a temp copy. Removing the term check was caught (2 fail), removing the text_re guard was caught
  (2), removing the file-exists check was caught (1), and removing CRLF normalisation was caught (1).
- Two mutants survived, both harmlessly: removing the why-title check (every title exists today) and removing the
  unclassified-tag check at open (emit raises it later).
- Most of the protection comes from one snapshot comparison, committed == fresh. It catches any change in output, but it cannot
  tell a correct regeneration from an incorrect one (N12).
- `test_every_rule_line_in_a_rule_section_has_a_record` checks 2 of 17 rule sections. Its docstring says "independent", which is
  true, but it covers only those two.
- Determinism was verified: two fresh runs match, and an LF→CRLF CLAUDE.md gives identical output.

### Both branches

**N19 · NOTE: the gate figure is not updated.** The two branches add 26 + 91 = 117 gate tests in `tests/security/`. Neither
updates `TEST_GOVERNANCE §1 LIVE_GATE_BASELINE` or the CLAUDE.md snapshot figure ("update BOTH in the count-changing commit").
test_doctrine_freshness checks only that the two agree with each other, so it stays green.
`rules-corpus.yaml` is not a hot surface: it is not in `SIZE_BUDGETS` and not scanned for retired vocabulary. The freshness and
doc-pointer tests pass on the merged tree.

### Leads from the automated security review of 6d7b719f (coordinator request)

The automated review flagged two cases of "state drift" and one "parser differential". State drift means the guard decides from
repository state read when the hook runs, while the command then acts on a different state. A parser differential means the
guard's reading of the command differs from what the shell or git actually runs.

**P1 · SHOULD-FIX: state drift (1). Branch and repository state are read when the hook runs, while the command changes them
before it commits.** All of these were reproduced:
- `git checkout - && git commit` and `git symbolic-ref HEAD refs/heads/main && git commit` are allowed, and the commit lands on
  main.
- `git merge --no-commit X && git commit` is allowed. On a fast-forward it makes a non-merge commit on main (N3).
- A leftover or forged MERGE_HEAD is trusted: the commit is allowed and git wrote a single-parent commit on main.
- `(cd ../main && ...); git commit` and `Push-Location` resolve the target directory wrongly (N6).
- Handled correctly: `git checkout main && git commit`, `switch main`, `checkout -q/-f main` and `-C <main> checkout main` all
  block, and `checkout -b` and `switch -c` move the branch.
- Can a model hit this: yes, without trying to evade, in the `merge --no-commit` and `checkout -` cases. The forged-MERGE_HEAD
  case is adversarial.
- Covered by the stated limits: no.
- Fix: treat `merge --no-commit` as pending only together with `--no-ff`, or re-check after the fact with a post-commit or
  pre-commit git hook in the repo (`.git/hooks/pre-commit` reading `git symbolic-ref` at commit time removes all drift). Treat any
  branch-moving segment the guard cannot resolve (`checkout -`, `symbolic-ref`, `update-ref`, `branch -f`, `reset`) as
  "branch unknown", which blocks. For MERGE_HEAD, require it not to be an ancestor of HEAD.

**P2 · SHOULD-FIX: state drift (2). The target repository is taken from cwd, `cd` and `-C`, while git takes it from the
environment.** Reproduced:
- `GIT_DIR=../main/.git git commit`, `export GIT_DIR=...; git commit` and PowerShell `$env:GIT_DIR=...; git commit` are all
  allowed. The guard strips the env prefix and checks the branch of cwd.
- `_run_git` deliberately removes GIT_DIR and GIT_WORK_TREE from its own environment. That is correct for its own read, but the
  command's inline values are ignored.
- `--git-dir` as a flag is handled (blocked as branch-unknown).
- Failures to read state: a git timeout or OSError raises Violation and blocks (correct). A guard crash before `main()` exits 1
  and the call proceeds. The hook timeout lets the call proceed. Both match the documented contract.
- Can a model hit this: rarely by accident, easily on purpose.
- Covered by the stated limits: no.
- Fix: when a segment's env prefix or an earlier `export` / `$env:` sets `GIT_DIR`, `GIT_WORK_TREE` or `GIT_INDEX_FILE`, treat the
  target as unknown and block. Symlinked repos were not tested (hypothesis): `os.path.normpath` does not resolve links, but git
  does, so the read would still be correct.

**P3 · SHOULD-FIX: the guard's tokeniser disagrees with bash, PowerShell and git.** Reproduced (table in N4):
- git abbreviations and synonyms: `add --al` (git accepts it and staged an untracked file), `stage -A`, `-c alias.aa='add -A'
  aa`. No aliases are configured on this box today (`git config --get-regexp alias` is empty).
- Bash: unquoted backticks, `eval`, `bash -ce`, heredoc bodies and piped strings run by a shell, ANSI-C `$'..'` (which gives a
  false block), and the runner prefixes `nice` and `timeout`.
- PowerShell: `iex` / `Invoke-Expression`, splatting `git @a`, `Start-Process`, and unquoted `cmd /c git ...`.
- Correctly handled: backslash and backtick line continuations, `\git`, `command git`, here-strings that only contain message
  text, and `& git`.
- Can a model hit this: unintentionally, mostly not; with evasive intent, trivially.
- Covered by the stated limits: only "quoted `$(...)`" is named. Unquoted backticks, eval, piped and heredoc shells, abbreviations
  and `stage` are not.
- Fix, in order of value:
  1. Normalise git long options by unique prefix against git's own list (`git add --git-completion-helper` prints them), and add
     `stage` as a synonym of `add`.
  2. Block when a segment's head is `eval`, `iex` or `Invoke-Expression`, or a shell run with stdin or a `-c*` flag cluster,
     whenever the payload mentions git.
  3. Add `nice`, `timeout`, `xargs`, `Start-Process` and `cmd /c` (unquoted) to the prefix or wrapper handling.
  4. Update the doc's Limits section to list what remains.

  A repo pre-commit hook (P1 fix) would also close every case of P1, P2 and P3 that ends in a commit on main, whatever the
  spelling.

## Verified clean

- Hook contract fields, exit codes, matcher syntax, `shell` value and environment inheritance, all against the live docs.
- All blanket and commit-on-main forms the guard claims to block, in both shells (N4 lists what was attacked and could not be
  broken).
- About 90 legitimate commands, including the merge ritual and messages that mention `git add -A` or `main`, with no false block.
- A command cannot set the override for itself. Overrides are logged, and an unwritable log keeps the block.
- Fail-closed on bad stdin, and large inputs run fast.
- No collision with block_destructive_git.py or the opencode dispatch fleet.
- Extractor determinism and CRLF handling, the `--check` exit codes, refusal on malformed tags, and no CLAUDE.md bytes added.
- Freshness and doc-pointer tests on the merged tree.
- The other 19 enforcement mappings: LOCALAPPDATA → conftest and root isolation, handoff → verifier and test, deferral → verifier
  and test, the time-anchored lint, the doctrine-freshness rule, the egress screen for fail-closed and allowlist, the door test,
  production posture for the keystore and signed manifest, purpose binding, and the reviewer refs. Each is genuine where its
  `note` narrows it.

## Merge read

- `feat/1690-git-rule-hooks` @6d7b719f: **NOT MERGE-READY.** N1 must be resolved in the same change, either by amending the
  doctrine or by an allowance in the guard. N2 (the doc text) and N3 (the lock that requires a defect) should be fixed before
  merge. The N4 one-liners (`-u`, `--al`, `stage`, `:/*`, pathspec commits, GIT_DIR) are cheap. The rest can be a ticketed
  follow-up with predicates.
- `feat/1690-rules-corpus` @717d0039: **NOT MERGE-READY.** N10 means the corpus's main product, the enforcement column, is wrong
  for 7 of 26 rows in the direction that hides gaps. N12 makes later edits silently mis-map. N11, N13 and N14 are the same kind of
  accuracy problem. The machinery is sound (determinism, fail-closed parse, drift gate); the data and the position-based keying
  are not.

---

# Round 2: final re-verification of `feat/1690-rules-corpus` @ 15c6528f (single branch)

Tested at 15c6528f (it contains the guard branch at 95923193 and the native hook bcba0906). Everything below was RUN. The guard
was driven through stdin JSON, the native hook through real `git` in temp BlarAI-marked repos with
`scripts/install_git_hooks.py` installed (`--check` exit 0). Scripts are in the session scratchpad (nh/mk.sh, nh/atk.sh, t7.py).

Suites on the branch (LOCALAPPDATA=$(mktemp -d), `-m "not slow"`, one file at a time):

| File | Result |
|---|---|
| test_rules_corpus | 39 passed |
| test_git_rules_guard | 188 passed |
| test_git_rules_guard_differential | 10 passed, 2 deselected |
| test_git_rules_guard_failclosed | 140 passed |
| test_git_native_pre_commit | 34 passed |
| test_doctrine_freshness | 19 passed |
| test_doc_pointers_and_banners | 34 passed |

CLAUDE.md: the blob equals main's (`git diff caab37f2 HEAD -- CLAUDE.md` is empty). It is **47,948 bytes**, not the 47,835 in
the brief. That leaves 52 B of headroom under the 48,000 budget.

## (1) Round-1 findings

| # | Verdict | Evidence |
|---|---|---|
| N1 companion commits blocked | FIXED (narrowed) | `git commit -m j` on main with only `docs/research/a.md` staged: ALLOW. Code staged: BLOCK, naming the path. But `git add <companion> && git commit` in ONE call on main is BLOCKED ("shares a call with a state change"). The companion ritual must be two calls. Of the 9 direct main commits since 09-01, 6 fit the allowlist and 3 would now be blocked: `c8e19a4d` (code, correct to block), `033d4dc6` (7 config/script paths), and `68306937` (CLAUDE.md + TEST_GOVERNANCE gate-figure update, a doctrine companion the allowlist excludes; it now needs a branch). |
| N2 missing script fails open | FIXED | Wrapper, script missing: rc=2. Python missing: rc=2 ("exit 127"). Script present, `ls`: rc=0. With the override set and the script missing, rc=0 is returned WITHOUT a log line (the wrapper does not log). |
| N3 FF `merge --no-commit` + commit | FIXED | Text guard blocks it ("shares a call"). Native: the `merge --squash` and `--no-ff --no-commit` concluding commits are held. MERGE_HEAD is no longer trusted. |
| N4 / P3 bypass forms | FIXED for all 28 round-1 forms except one | `Push-Location ../main; git commit` still ALLOWs in the text guard (the native layer now catches it). |
| N5 repo scope | FIXED | agentic-setup on main: `git commit -m x` and `git add .` ALLOW. |
| N6 false positives | PARTLY | `worktree add -b && cd && commit` and `$'..'` quoting now ALLOW. `git checkout feat/x && git commit` is still blocked, now by design (state drift). |
| P1 state drift | FIXED | `checkout -`, `symbolic-ref`, `merge` sharing a call with commit: all BLOCK. |
| P2 GIT_DIR / env | FIXED | Inline, exported and `$env:` GIT_DIR, and `GIT_CONFIG_COUNT`, all BLOCK. |
| N7 override | FIXED | Inline or exported in the command text: BLOCK. Process env: ALLOW and logged. Unwritable log: BLOCK. Whitespace-only value: BLOCK. |
| N8 fail-closed | FIXED | `command` as a list and `tool_input` as a string now give 2. Over 1,000,000 chars: 2. Still 0 for `tool_input: null`, a missing tool_name and lowercase `bash` (harmless: the matcher filters). |
| N10 false mappings | FIXED | All 7 removed: TEST_GOVERNANCE gate, port-leak (now conftest's autouse fixture, line 397), timeout (now test_timeout_registry), status_claims, ipc cap, canary, instrument_toggles for FAIL-LOUD. |
| N11 missed enforcement | PARTLY | no_external_egress → critical "you-are-not-blarai" and identity_split; journal_integrity (honest note); timeout_registry: all added. Still `none`: `testing.seams.test-the-boundary-itself` while `tests/integration/test_winui_passthrough_allowlist.py` exists, and `live_state_pointers.services-assistant-orchestrator-config-default-toml` / `stack.trust-spine` while `test_config_comment_truth.py` and `test_doc_pointers_and_banners.py` (banners checked against flags) enforce part of each. |
| N12 position ids | FIXED | Temp CLAUDE.md with a principle inserted at #3: 168→169 records, 0 ids changed, 0 enforcement changed. Critical rule inserted at #5: the same. Renaming a rule's lead words whose id is named by a marker makes the extractor REFUSE (loud). Cosmetic: one id is `repo_constellation.c`, and `blarai_identity.self-governance-boundary-la-2026-07-11` embeds a date. |
| N13 fact sections | FIXED (heuristic) | 19 fact items now included by imperative marker; status_snapshot skipped. A trailing space in the snapshot no longer refuses. A trailing space in a rule line still refuses (N16, fail-closed, acceptable). |
| N14 corpus vs guard | FIXED | `never-commit-work-directly-to-main` ← native hook + guard + test; `no-git-add-a-ever` ← guard + test. |
| N15 suggestions | FIXED | Generic keyword suggestions replaced with "none proposed". |
| N17 ticket scope | NOT FIXED (ticket matter) | README now labels the reviewer procedure "proposed, not yet proven". The skills audit and the proven rules-review are still absent: #1690 cannot close on this branch. |
| N18 mutants | Not re-run | The corpus test grew 26→39. Round-1 mutants were not repeated at this hash. |
| N19 gate baseline | NOT FIXED | TEST_GOVERNANCE is untouched while the branch adds 39+188+10+140+34 = 411 non-slow tests in tests/security/ (plus 2 slow). The baseline line and the CLAUDE.md snapshot figure must move at merge. |

## (2) The git-native pre-commit hook (installed in temp repos with the real installer)

**Routes that HELD (no code reached main):** 22 routes.
- Plain `commit`, `commit -a`, `commit <path>`, `-o path`, `-i path`, and amend (code into the last commit, and amending a companion
  commit with code staged).
- `cherry-pick -n` + commit, `merge --squash` + commit, `merge --no-ff --no-commit` + commit, `stash pop` + commit,
  `checkout feat -- file` + commit.
- Index tampering then commit: `update-index --cacheinfo` and `read-tree feat`; a `GIT_INDEX_FILE` alternate index + commit.
- `--allow-empty`; detached HEAD (blocked); an unborn or orphan `master`; a linked worktree checked out on main.
- Python missing from PATH: the shim blocks.
- Index paths `Docs/Research/z.py`, `docs/research/../../services/evil.py` and `docs/research./x.py`.

**Q1 · SHOULD-FIX (adversarial bypass; the doc's claim "strong: no parser to fool" overstates it). The scope and the hook code
are read from the WORKING TREE, which the committer controls.** All of these were reproduced, and each landed code on main:
- (a) `git rm CLAUDE.md` + code in the same commit: landed (the hook decided "not BlarAI"). The text guard ALLOWs
  `git rm CLAUDE.md && git commit -m x`.
- (b) CLAUDE.md emptied or moved away in the working tree, unstaged: landed. The text guard ALLOWs `echo > CLAUDE.md && git commit`.
- (c) An unstaged edit adding `services/` to `rules_common.COMPANION_ALLOWLIST`: landed.
- (d) An unstaged edit making the `pre-commit` shim `exit 0`: landed.
- (e) `scripts/githooks/` deleted: landed. git silently skips a missing hooks dir; the shim's own "script missing" branch
  cannot fire when the shim itself is gone.

Edits by the Edit/Write tools are invisible to the Bash/PowerShell text guard. How exploitable: only by a session acting
adversarially. No ordinary command does this.

Fix:
- Read the marker from `git show HEAD:CLAUDE.md` (from the index on an unborn HEAD).
- Treat any staged change to CLAUDE.md, `scripts/githooks/**` or `scripts/hooks/**` on main as non-companion. It already is,
  but only once scope holds.
- Have the shim verify `git diff --quiet HEAD -- scripts/githooks scripts/hooks/git_native_pre_commit.py
  scripts/hooks/rules_common.py`, or run the HEAD blobs (`git show HEAD:...`), and block when they differ.
- Optional: a PreToolUse matcher for `Edit|Write` on `.git/config`, `scripts/githooks/`, `scripts/hooks/` and CLAUDE.md.

**Q2 · SHOULD-FIX: code reaches main with no pre-commit at all, and the text guard allows most of it.** Each route below landed
`services/app.py` on main. The second column is the text guard's verdict on the same command with cwd on main.

| Route | Text guard on main |
|---|---|
| `cherry-pick feat` | ALLOW |
| `revert` | ALLOW |
| `am` | ALLOW |
| `merge --ff-only feat` | ALLOW |
| plain `merge feat` (fast-forward) | ALLOW |
| `pull . feat` | ALLOW |
| `rebase feat` | blocked only by the user-level destructive hook |
| `commit-tree` + `update-ref` / `merge --ff-only <sha>` | ALLOW |
| `branch -f main feat` | ALLOW |
| `push . feat:main` | ALLOW |

- The doc lists update-ref, `push .`, `fetch .`, `branch -f`, cherry-pick, revert and am as limits. It does NOT list
  fast-forward merge, pull or rebase. It *prescribes* "fast-forward main" for conflicted merges.
- Ordinary, non-adversarial forms a model will plausibly type: `git cherry-pick <fix>` on main, `git merge feat` without
  `--no-ff`, and `git pull`.
- Fix (hypothesis, not built or run): one `scripts/githooks/reference-transaction` hook (git ≥2.28; the box has 2.55). In the
  `prepared` state, abort any update of `refs/heads/main|master` unless the new value is a merge commit whose first parent is
  the old value, or its diff against the old value is companion-only. That one native hook closes every route in the table,
  including the ref-plumbing ones. Interim cheap fix: the text guard blocks cherry-pick, revert, am, pull and a non-`--no-ff`
  merge when the resolved branch is main.

**Q3 · SHOULD-FIX (doc): the conflict-resolution instruction conflicts with the merge-commit rule.**
- git-rules-guard.md and the guard message say: "merge main INTO the feature branch, then fast-forward main." Fast-forwarding
  puts the feature branch's commits onto main's first-parent history, which skips the `--no-ff` merge commit the doctrine
  sanctions.
- A conflicted `git merge --no-ff` concluded on main is now blocked by both layers. The correct route is: merge main into the
  feature branch, resolve there, then `git merge --no-ff feat` on main, which is now conflict-free and runs no pre-commit.
  This is a one-line doc and message fix.

**Q4 · SHOULD-FIX: the allowlist matches by path, not by content.**
- Landed on main via the companion route, each reproduced: a symlink `docs/research/link.py` → `../../services/app.py` (mode
  120000), an executable `docs/research/tool.py` (100755), a gitlink `docs/research/sub` (160000), and
  `docs/research/.gitattributes` with `* filter=evil`.
- Path tricks held: `..`, backslash, trailing dot, case variant. Windows 8.3 names and NTFS streams were not tested: git
  refuses `:`-containing and `~1` paths by default on Windows (`core.protectNTFS`), so this is a hypothesis.
- Risk: no gate collects `docs/`, so nothing runs automatically. But the allowlisted directories already hold 56 `.py`
  (50 under `docs/reviews/1067-v5-evidence/*-probes`), 1 `.sh` and 518 `.json`. Runnable code can therefore reach main with
  no review, no gate and no branch, and a later session may run it. The `.gitattributes` case changes only attributes for that
  directory, and filters need non-committed config, so it is low. The symlink and gitlink do not execute.
- Fix:
  - Reject modes 120000, 160000 and 100755, and any mode change.
  - Reject dotfiles (`.gitattributes`, `.gitmodules`, `.gitignore`).
  - Allow per-directory extensions (`.md .json .jsonl .csv .txt .yaml .png .svg .html .xml .log`).
  - Optionally add a size cap.
  - Scripts used as evidence go via a branch.

**Q5 · NOTE: state drift inside git.**
- `-a`, `-o`, `-i` and pathspec temp indexes, and a worktree-specific index: all judged correctly (held, above).
- `commit.template` and `prepare-commit-msg` change only the message (and scripts/githooks has no other hooks).
- Concurrent index writes: hypothesis, not reproduced. For a plain `git commit`, git releases the index lock after refresh and
  re-reads the index after pre-commit. A concurrent `git add` by another agent sharing the tree, in the milliseconds between
  hook and tree write, would be committed unjudged. The window is tiny and needs a concurrent writer. The reference-transaction
  hook (Q2) would close it, because it judges the final commit.
- Unborn HEAD: judged (blocked). A linked worktree on a main commit that lacks `scripts/githooks`: landed, but contrived (main
  itself would have to drop the hooks).

**Q6 · BLOCKING FOR THE INSTALL STEP, not the merge: installing silently disables an existing hook.**
- BlarAI's local config today has `core.hooksPath = C:\Users\_OPERATOR_\blarai\.git\hooks` (scope local, `.git/config`), which runs
  the `post-commit` hook (the Claude-Projects dirty log).
- `install_git_hooks.py` overwrites it (it prints "(was ...)") and `scripts/githooks/` has no `post-commit`. So the install
  turns that hook off for every worktree. `--check` reports "NOT installed" today.

**Text-guard coverage of the routes that switch the hook off (Q7, NOTE).**
- BLOCKED: `--no-verify`, `-n`, `-c core.hooksPath=NUL`, `GIT_CONFIG_COUNT`, `--config-env`, and `git config` in
  set/`--worktree`/`--unset`/`-f`/`--file=`/`--replace-all`/lower-case form.
- ALLOWED: `printf ... >> .git/config`, PowerShell `Add-Content .git/config`, `python scripts/install_git_hooks.py --uninstall`,
  `rm scripts/githooks/pre-commit`, `sed -i` on rules_common.py, and the Edit/Write tools.
- The doc names .git/config editing and hook-file deletion as limits; `--uninstall` is not named and is one cheap token match.

**Other repos.** A branch named `main` in a non-BlarAI repo is untouched by the native hook (scope false) and by the text guard
(agentic-setup verified above). The hook is per-repository config, so it never applies outside BlarAI.

## (3) Text-guard fuzz, differential and fail-closed results

| Run | Variants | Result |
|---|---|---|
| Committed slow seeds 20261005 and 424242 (run incidentally, through an import) | 2000 each | both passed |
| New seed 31337 (1740 bash + 300 pwsh) | 2034 unique | 0 bypasses; exit codes {2: 1904, 0: 130}, only 0 or 2; 1364 dangerous by the independent oracle; 1732 reached git |

- The non-slow differential suite passed 10, and the fail-closed suite passed 140.
- Limit of the fuzzer: its oracle only judges blanket staging and commit-on-main argv. Hook-disabling forms and the ref-moving
  routes (Q2, Q7) are outside what it measures, so a zero there certifies nothing about those.
- From the round-1 probes re-run on the new guard:
  - Exit codes were only 0 or 2.
  - A nonexistent cwd or a non-repository directory gives 0 ("positively not BlarAI"). Harmless, because git fails there too.
  - A nonexistent subdirectory of a BlarAI repo blocks.
- The settings.json wrapper fails closed: a missing script gives 2 even for `ls`, and missing python gives 2.

## (4) Corpus re-verification

- Totals: 168 records, 29 with a mapping, 139 `none`. Every marker resolves: the extractor refuses unknown ids, and renaming a
  marked rule's lead words REFUSES.
- I spot-checked 22 of the 29 mappings against the referenced file. All are genuine within their notes: conftest's autouse
  leak fixture, test_timeout_registry discovery, test_no_external_egress import scan, and the rest.
- I spot-checked 15 `none` records again. Three are still missing a mapping (N11 above): `testing.seams.test-the-boundary-itself`
  ← tests/integration/test_winui_passthrough_allowlist.py; `live_state_pointers...default-toml` and `stack.trust-spine` ←
  test_config_comment_truth.py and test_doc_pointers_and_banners.py, each partial.
- The corpus records `never-commit-work-directly-to-main` as enforced by the native hook, while the hook is OFF until installed.
  The marker note says so, but the gap list will drop that rule from the gaps even before anyone installs the hook.
- Id stability: a principle inserted at #3 changed no ids and no mappings (above). `--check` exit 0.

## (5) Merged tree

Detached worktree of main `caab37f2` at C:/Users/_OPERATOR_/blarai-wt-1690-review-merged2, `merge --no-ff 15c6528f`; the worktree
was removed afterwards.

| File | Result |
|---|---|
| test_rules_corpus | 39 passed |
| test_git_rules_guard | 188 passed |
| test_git_rules_guard_differential | 10 passed, 2 deselected |
| test_git_rules_guard_failclosed | 140 passed |
| test_git_native_pre_commit | 34 passed |
| test_doctrine_freshness | 19 passed |
| test_doc_pointers_and_banners | 34 passed |

`extract_rules_corpus.py --check`: 0.

## Round-2 merge read (15c6528f)

**MERGE-READY for feat/1690-rules-corpus.** Nothing in this round blocks the merge itself, given these conditions:
- On merge, the text guard goes live for sessions rooted in the repo and fails closed. The native layer stays dormant until an
  install.
- Every round-1 blocking finding is fixed.
- The remaining findings are should-fix with named fixes, or limits the doc already states. One exception: Q2's fast-forward
  merge, pull and rebase gap is not in the doc, and the doc *prescribes* a fast-forward (Q3). Fix that doc line in the merge
  motion or immediately after.
- N19: update the gate baseline in the merge motion, +411 non-slow tests in tests/security.

**What must be true before the install step** (`scripts/install_git_hooks.py` on C:/Users/_OPERATOR_/BlarAI):
1. Q6: the existing `core.hooksPath` (`C:\Users\_OPERATOR_\blarai\.git\hooks`, with the post-commit dirty-log hook) is carried
   over. Either copy or chain `post-commit` into `scripts/githooks/`, or have the installer refuse to overwrite a non-empty
   foreign value.
2. Q1: the hook reads its scope marker from `HEAD:CLAUDE.md` and refuses when its own files differ from HEAD. Without this,
   the "strong layer" is defeated by working-tree edits.
3. Q3: the conflict instruction says `merge --no-ff` after resolving on the branch, not "fast-forward main". Otherwise the
   first ceremony that hits a conflict lands feature commits on main's first-parent line.
4. Q2: decide whether a `reference-transaction` hook is built (it closes fast-forward merges, cherry-pick, revert, am, pull and
   ref plumbing). If not, the doc must list fast-forward merge, pull and rebase as uncovered routes.
5. Q4: tighten the allowlist by mode and extension (no 120000, 160000 or 100755, no dotfiles, document extensions only).
6. `--check` exits 0 on the primary checkout after install. Do one live code commit on main as a negative test, then `git
   merge --no-ff` of a real branch as the positive test.

---

# Round 3: final verification of `feat/1690-rules-corpus` @ 938ab848, re-checked at 0693fb77

The HEAD moved to 0693fb77 during the review. That commit is docs only: ADR-043, the explainer, a DECISION_REGISTER row and
the README. I re-ran the doc-pointer (34), freshness (19) and corpus (39) tests at 0693fb77, and all passed. Every hook result
below is from 938ab848, whose code is unchanged at 0693fb77.

**How it was tested.** Temp BlarAI-marked repos were built from `git archive 938ab848` of CLAUDE.md, the guard files, the
shims and the installer. Each repo had autocrlf=true and a PREVIOUS `core.hooksPath` directory holding a post-commit hook, and
was then set up with the real `python scripts/install_git_hooks.py` (`--check` exit 0). Scripts are in the session scratchpad
n3/ (mk.sh, atk.sh, atk2.sh, dbg*.sh).

## Merged tree (detached worktree of main + `merge --no-ff 938ab848`, removed afterwards)

Non-slow results:

| File | Result |
|---|---|
| rules_corpus | 39 passed |
| git_rules_guard | 188 passed |
| differential | 10 passed, 2 deselected |
| failclosed | 140 passed |
| git_native_pre_commit | 88 passed, 10 deselected |
| git_reference_transaction | 32 passed, 4 deselected |
| git_hooks_chain | 14 passed |
| git_hooks_hardening | 35 passed, 7 deselected |
| doctrine_freshness | 19 passed |
| doc_pointers_and_banners | 34 passed |

`--check` exit 0. CLAUDE.md is 47,948 B and unchanged.

## The LA's ordinary ritual (all allowed, verified)

- `git worktree add <p> -b feat/q2 main`, `git checkout -b feat/q`, `git add docs/research/a.md`.
- A companion commit on main: `git commit -qm j`. The previous post-commit hook chained and logged.
- `git merge --no-ff -m "Merge feat/x" feat/x` on main, and the same inside a linked worktree whose branch is main.
- A commit with a heredoc message (text guard allow).
- `git merge -X theirs` with no conflict, and `git pack-refs --all`.
- `git merge --ff-only feat/x` on main is BLOCKED by the native hook. The message says "Work lands on main only by `git merge
  --no-ff <branch>` (never fast-forward ...)". Confirmed.

## Q1-Q7 from round 2

| # | Verdict | Reproduction |
|---|---|---|
| Q1 working-tree scope and hook edits | PARTLY | Held: `git rm CLAUDE.md` + code, CLAUDE.md emptied in the work tree, an edit to the rules_common allowlist, the pre-commit shim set to `exit 0`, an `_lib.sh` edit, `.git/blarai-python` repointed, `PYTHONPATH` sitecustomize, a fake `git` first on PATH. Still landed code: replacing BOTH `pre-commit` and `reference-transaction` shims with `exit 0` (unverified shell files, a documented residual), and deleting `scripts/githooks` (git skips a missing dir, documented). New scope bypasses: R1 and R2. |
| Q2 routes with no pre-commit | FIXED | All held: cherry-pick, revert, am, `merge --ff-only`, plain fast-forward merge, `pull .`, rebase, `rebase --onto`, commit amend on main, `reset --soft` + commit, a reset rewind, commit-tree + update-ref, `update-ref --stdin` (batch and start/prepare/commit), `--no-deref`, via HEAD, `refs/heads/Main` / `MAIN`, `branch -f/-D/-m`, `fetch .`, `push .` (also forced), `worktree add -B`, `checkout -B`, `switch -C`, stash flows, an evil merge (both via `--no-commit`+edit and via commit-tree), `-s ours`, octopus, unrelated histories, a loose-commit merge, `gc`, a packed-refs `--no-prune` delete, a forged packed-refs delete. Still MOVED: `-c core.hooksPath=NUL commit` (the text guard blocks it; git cannot) and a direct write to `.git/refs/heads/main` (the text guard ALLOWs `echo x > .git/refs/heads/main`). |
| Q3 fast-forward instruction | FIXED | The messages and the doc say `merge --no-ff`. |
| Q4 allowlist content | FIXED for modes, types and dotfiles | Held: symlink, exec, `.py`, gitlink, `.gitattributes`, `Docs/Research` case, a newline path, a code→docs rename. Still MOVED by design: a `.md` file containing a shell script, a `.json` file, and code CONTENT copied into a `.md`. That is path-plus-extension policy, acceptable. |
| Q5 drift in git | unchanged | Not re-tested beyond the `-a/-o/-i` routes, which still hold. |
| Q6 install drops existing hook | FIXED | The previous hooksPath post-commit ran after install. `--uninstall` restored the exact previous value, and the post-commit then ran from it. The `.git/blarai-*` files were removed. |
| Q7 text guard on switch-off routes | PARTLY | `--uninstall` and `blarai.previoushookspath` edits are now blocked, per the commit. `echo > .git/refs/heads/main` and `printf ... >> .git/config` are still allowed. |

## New findings

**R1 · SHOULD-FIX: merging a branch that deletes CLAUDE.md switches the native layer off for main.**
- Reproduced (atk2.sh): a side branch `nocl` runs `git rm CLAUDE.md` and adds `services/evil.py`, then `git merge --no-ff nocl`
  on main is ALLOWED. The merge-tree is equal, so this is the sanctioned route. Main's new tip has no CLAUDE.md, so every later
  route is unscoped: `echo q>>services/app.py; git add; git commit` on main MOVED main.
- Exploitability: needs a merged branch that deletes CLAUDE.md. That would be visible in review, but nothing mechanical stops
  it. ADR-043 line 17 ("scope ... read from the committed CLAUDE.md of the ref's own tip") is precisely the assumption this
  breaks.
- Fix: record the repo's identity at install (for example the root commit hash, or a `blarai.scope=on` config key written by
  the installer) and take scope from that, never from content. In addition, treat a change that deletes or edits CLAUDE.md's
  marker on main as non-companion.

**R2 · SHOULD-FIX: with HEAD on an orphan branch, main can be deleted and recreated from arbitrary history.**
- Reproduced (dbg.sh, dbg2.sh, dbg5.sh): HEAD is on `--orphan orp` (a commit with no CLAUDE.md).
  - `git branch -D main` passes, and `git branch --delete --force main` passes.
  - `printf "delete refs/heads/main\n" | git update-ref --stdin` passes, and `git update-ref -d refs/heads/main` passes.
  - `git branch -m orp main` or `git branch main orp` then creates main from the orphan history. Main is replaced.
- Why: for a deletion git passes old = all-zero. `check()` then scopes from `HEAD` (the orphan, so "not BlarAI") and skips the
  judgment. Run on a BlarAI HEAD, the same deletion is BLOCKED.
- Exploitability: adversarial only. The user-level destructive hook blocks `branch -D` and `update-ref -d` text in Claude
  sessions, but not `update-ref --stdin` "delete". The text guard ALLOWs all of these.
- Fix: for a deletion with old=0, resolve old to the ref's current value (as is already done for creation), and scope from the
  recorded identity (R1 fix).

**R3 · BLOCKING FOR THE INSTALL STEP: the control's state depends on which branch the INSTALLING checkout has checked out.**
`core.hooksPath` is an absolute path into the installing checkout's working tree, and the guard verifies its own files against
main's tip.
- (E) The installing checkout switches to a branch WITHOUT `scripts/githooks`. Any branch cut before this merge lacks it,
  which today is every branch, including the primary checkout's `feat/1616-corpus-tier`. All hooks are then OFF repo-wide:
  a code commit on main from a linked worktree LANDED (`ea2b114 code on main`).
- (F3) The installing checkout is on a branch whose guard modules differ from main's tip. Every main update is BLOCKED
  repo-wide ("guard modules ... differ from the committed files"), including `git worktree add <p> main` itself and the
  sanctioned `merge --no-ff`.
- The real primary checkout `C:/Users/_OPERATOR_/BlarAI` routinely sits on feature branches. The guard would therefore flip between
  silently off and blocking every merge, according to branch state no one is watching. `--check` reports neither state while
  the files exist.
- Fix: point `core.hooksPath` at a location no checkout's branch changes. For example, the installer materialises
  `<git-common-dir>/blarai-hooks/` from main's tip blobs, and the reference-transaction hook refreshes it after main moves.
  The guard modules then run from there, verified against main's tip, independent of any working tree. `--check` should also
  fail when the hooks directory is missing or its files differ from main's tip.

**R4 · NOTE: what a blocked ref update leaves behind (asked for).**
- Reproduced (dbg2.sh D and B). `git merge feat/x` / `--ff-only` on main is blocked at the ref update. git has already updated
  the index and work tree: feature files show staged (`M services/app.py`, `A services/new.py`) while HEAD and main stay at the
  old tip. The LA's own unrelated uncommitted edit (`docs/research/a.md`) is preserved.
- Nothing is lost. But the next `git merge --no-ff feat/x` fails: "Your local changes would be overwritten ... Merge with
  strategy ort failed". A later companion commit is refused, because code is staged.
- The obvious recoveries are `git reset --hard` / `git checkout -- .` / `git restore`, which the destructive-git hook refuses,
  so a session can get stuck or improvise.
- Verified non-destructive recovery: `git reset --merge`. It reset the staged feature files and KEPT the uncommitted
  `docs/research/a.md` edit, after which `git merge --no-ff -m m feat/x` succeeded (`737a0bf m`).
- Mitigation:
  - Print `git reset --merge` (and "then git merge --no-ff <branch>") in the reference-transaction BLOCKED message for
    merge-originated refusals.
  - Have the text guard pre-block `git merge` without `--no-ff` and `--ff-only` / `pull` on main, so the work tree is never
    touched. At the moment the text guard ALLOWs `git merge feat/x`, `--ff-only`, `pull` and `cherry-pick` on main.
  - Name `git reset --merge` in explainer line 101 ("can be set aside").

**R5 · NOTE: what the parser-differential lead covered.**
- Refs under main (`refs/heads/main/x`) and `main.lock` names are rejected by git itself (held).
- Case variants of main and master are held.
- Paths: newline, non-ASCII and spaces are handled (`-z`). A code-file rename into docs is held (`--no-renames` effective).
- Not tested: a sha256 repository (64-hex ids) and a CRLF-terminated stdin from a third-party transaction. Both are hypothesis
  only.
- The installer handles a repo path with spaces: `--check` 0, code held, companion allowed. Guard files checked out CRLF under
  autocrlf still verify.

## Round-3 merge read

**Merging is safe.** On merge, the native layers stay DORMANT until the install step, and the text guard behaves as round 2
measured: fuzz 0 bypasses, every suite green, CLAUDE.md untouched. R1 and R2 are adversarial-only. R3 and R4 matter only
once installed.

**MERGE-READY for `feat/1690-rules-corpus` @ 0693fb77**, on condition that the install step is gated as below.

**What must be true before `install_git_hooks.py` runs on C:/Users/_OPERATOR_/BlarAI:**
1. R3: `core.hooksPath` is independent of the installing checkout's branch: hooks materialised from main's tip into the
   common dir, or equivalent. Verify by switching the primary checkout to an old branch and a guard-edit branch: a code
   commit on main must still be refused, and `merge --no-ff` must still be allowed.
2. R1 and R2: scope comes from a recorded repo identity, not CLAUDE.md content, and a deletion with old=0 resolves the real
   old value. Verify that the merge of a branch deleting CLAUDE.md and the orphan delete-and-recreate route are refused.
3. R4: the blocked-merge message names `git reset --merge`. Preferably the text guard refuses non-`--no-ff` merge, pull and
   cherry-pick on main before git touches the work tree.
4. `--check` fails when the hooks directory is missing or differs from main's tip. It reports OK today in state E.
5. The live ceremony on the real repo, with exact commands: `--check` 0; a code commit on main refused; `git merge --no-ff`
   of a real branch from a worktree on main succeeds; a companion commit succeeds; the post-commit dirty-log hook still
   fires; `--uninstall` restores `C:\Users\_OPERATOR_\blarai\.git\hooks`.
6. The gate baseline (TEST_GOVERNANCE §1 + the CLAUDE.md snapshot figure) is updated for the new tests. Mind CLAUDE.md's 52 B
   of headroom.

---

# Round 4: `feat/1690-install-hardening` @ bd9bb54e (off main 32e31564)

Report appended in the install worktree's copy of this file, uncommitted.

**Method.** Each temp repo was built with `git archive bd9bb54e` of CLAUDE.md, the guard, the shims, the installer and the
proof script, committed on main. It has autocrlf=true and a PREVIOUS `core.hooksPath` directory holding a logging
post-commit, and was then set up with the real `python scripts/install_git_hooks.py`. Scripts are in the session scratchpad
n4/ (mk.sh, atk.sh, inst.sh, dbg.sh, t9.py).

## R1-R4

| # | Verdict | Reproduction |
|---|---|---|
| R1 a merge that deletes CLAUDE.md switches the guard off | FIXED | `merge --no-ff nocl` (which deletes CLAUDE.md and adds `services/evil.py`) is allowed, as the sanctioned route. The next code commit on main is HELD, because scope is now the recorded identity. |
| R2 orphan delete and recreate | FIXED | Orphan HEAD: `branch -D main`, `update-ref --stdin` delete, `update-ref -d`, `branch -M orp main`, `branch -f main orp`, and `checkout --orphan` + commit + `branch -M new main`: all HELD. |
| R3 depends on the primary checkout's branch | FIXED | Primary on a branch WITHOUT `scripts/githooks`: a code commit on main from a worktree is HELD, while `worktree add <p> main` + `merge --no-ff` MOVED (allowed). Primary on a branch with an EDITED guard: code is HELD and the ritual is allowed. Deleting the working-tree `scripts/githooks` and `scripts/hooks`: HELD. |
| R4 blocked merge leaves files changed | FIXED | Text guard on main: `merge` (plain, `--ff`, `--ff-only`, `--squash`, `--no-ff --ff-only`), `pull` (even `--no-ff`), `cherry-pick`, `revert`, `rebase`, `am`, `reset --hard/--keep`: all BLOCK, PowerShell too, before git touches files. The messages name `git merge --no-ff <branch>` and `git reset --merge`. NOT blocked on a feature branch (`merge main`, `pull`, `cherry-pick`, `rebase main`, `revert`, `merge --ff-only main` all ALLOW). On main, `merge --no-ff [-m]`, `--abort`, `reset --merge`, `cherry-pick --abort` and `reset HEAD <path>` ALLOW. `git -C <main-wt> merge --no-ff` from a feature worktree ALLOWs; without `--no-ff` it BLOCKs. The ref-transaction refusal text now names `git reset --merge`. |

## The LA's ritual (allowed, verified)

`git worktree add <p> main` (and `-b feat/q main`), `git merge --no-ff -m "Merge feat/x" feat/x` from the main worktree,
a companion commit on main (the previous post-commit chained and logged), `git checkout -b`, and explicit-path `git add`.
A code commit on main is refused.

## Installer

| Case | Result |
|---|---|
| Real shape: previous `core.hooksPath='C:\Users\x\blarai\.git\hooks'` | Install, then `--uninstall`, restores the EXACT string (backslashes kept). The installed copies are removed; `blarai-install.log` stays. |
| Install twice | Second run: "already installed"; `--check` 0; previous path kept. |
| Install from a linked worktree on feat/x | Copies from main; `--check` OK; the primary checkout is protected. |
| Previous value relative, unset or a missing directory | Each round-trips through `--uninstall`. With a missing directory, the companion commit still works. |
| Path with spaces | OK. Case-variant cwd `SP ACE`: `--check` OK. |
| Guard change merged to main | `--check` says NOT OK, "run --update". `--status` says ON (older copy) with a note. `--update --reason` re-copies and logs; `--check` is OK again. |
| autocrlf | The installed copies are byte-exact LF (`--no-filters` hashing). |
| Repo folder MOVED (legitimate) | Protection silently OFF: a code commit on main LANDED. The absolute `core.hooksPath` now points at a folder that no longer exists, and git skips it. `--check` reports NOT OK. Documented by the installer docstring and `--status` item 1. |

## Install-record tampering (the record and copies live in `.git`)

| Change | Result |
|---|---|
| Edit an installed module alone | HELD (hash mismatch). |
| Plant an extra installed file | HELD. |
| Delete the record | HELD. |
| Repoint the interpreter in the record (hash updated) | HELD. |
| Replace BOTH installed shims (`pre-commit`, `reference-transaction`) with `exit 0` | LANDED. The shims cannot verify themselves; documented. |
| `core.hooksPath` edited | LANDED; documented. |

**S1 · SHOULD-FIX: a one-field edit of the install record switches protection OFF instead of failing closed.**
- Reproduced (dbg.sh A): set `"common_dir"` to `"C:/elsewhere"`, or `repo_roots` to an unknown hash. The next code commit on
  main succeeds: `commit rc=0`, `90e2e9c c`. Both guards treat "not the recorded repository" as "out of scope, allow".
- `--check` reports "identity does not match" and `--status` reports OFF/BROKEN, so it is visible, but only if someone looks.
- This is the same class as the fail-open-scope lead: the identity check was meant to stop a scope switch-off, and it turned
  into a new switch.
- Fix: the hooks run from `<common>/blarai-hooks`, so the repository is this one by construction. A mismatch or missing root
  should BLOCK (fail closed, "run --check"), never allow. Use the record only to detect tampering.

**What the hash pinning actually protects against (plainly).**
- The record and the copies both sit in `.git`, which any process with file access, a model included, can write.
- Pinning stops accidental drift and a careless single-file edit: a lone edit to an installed module is refused.
- It does NOT stop a deliberate attacker. Reproduced (dbg.sh B): an edited `rules_common.py` with its hash written into the
  record RAN, and its refusal message listed the injected `services/` allowlist entry. An attacker who also writes a
  consistent edit has full control. The same holds for the interpreter, whose path and hash both sit in the same file.
- The text guard does not block writing `.git/blarai-install.json` (`sed -i ... .git/blarai-install.json` ALLOW), and Edit/
  Write tools are not seen at all.
- So pinning raises the bar from "edit one file" to "edit two files consistently". It is not a boundary, and the doc's
  "backstop to discipline" wording is the honest one.

**`--update` and a compromised main tip.**
- `--update` installs whatever is on main's tip. Reproduced (dbg.sh C): a `rules_common.py` change merged with `--no-ff` (the
  sanctioned route, nothing judges guard files) was installed by `--update`, and the edited code then ran.
- So the guard is exactly as strong as review of merges that touch `scripts/hooks/**` and `scripts/githooks/**`.
- The text guard ALLOWs `install_git_hooks.py --update` (it blocks `--uninstall`).
- Recommendation: treat a main update that changes the guard files as needing the override (logged). Alternatively, have
  `--update` print the diff of the guard files and require a `--reason`; it logs today but does not require one.

**TOCTOU.**
- `_materialise` writes `blarai-hooks.new`, hashes each file, then `rmtree(blarai-hooks)` and `os.replace`. Between the rmtree
  and the replace, the hooks folder is absent, and git silently runs NO hooks: a millisecond fail-open window during
  install/`--update`.
- A process that edits `.new` between hash and replace is caught later, because the record carries the blob hashes from main
  and the shims re-verify.
- Hypothesis, not raced.

**The proof script.**
- I read it: `--live` runs only `--check` and `--status` against the repo, plus the temp-repo proof. Verified read-only: the
  install worktree's common dir (= C:/Users/_OPERATOR_/BlarAI/.git) `config` mtime 00:17:16 and md5 `f53ec056...` were unchanged
  across the run, and no `blarai*` files appeared.
- Temp mode: 7/7 PASS.
- `--live` today: it FAILS 2/8 ("LIVE --check": the real hooksPath is still `C:\Users\_OPERATOR_\blarai\.git\hooks`; and "code
  commit on main is refused"). Because main is still at 32e31564, the proof built from main's tip tests the PRE-hardening
  files. That is expected: `--live` is meaningful only after this branch is merged.
- Note: `--i-am-the-lead` is a typed flag, not an authentication. Anything can pass it; it is harmless only because `--live`
  is read-only.

## Merged tree (detached worktree of main 32e31564 + `merge --no-ff bd9bb54e`, removed)

Fast core, `-m "not slow"`:

| File | Result |
|---|---|
| install_hardening | 18 passed, 17 deselected |
| git_rules_guard | 79 passed, 109 deselected |
| differential | 3 passed, 9 deselected |
| failclosed | 26 passed, 114 deselected |
| native_pre_commit | 55 passed, 40 deselected |
| reference_transaction | 7 passed, 28 deselected |
| hooks_chain | 2 passed, 12 deselected |
| hooks_hardening | 10 passed, 32 deselected |
| rules_corpus | 39 passed |
| doctrine_freshness | 19 passed |
| doc_pointers | 34 passed |

`--check` 0; CLAUDE.md 47,948 B, unchanged. The slow tier was NOT run in this round (the brief asked for the fast core).

## Round-4 merge read

**MERGE-READY for feat/1690-install-hardening @ bd9bb54e.** R1-R4 are fixed by reproduction. Merging installs nothing, so
nothing changes on this machine. S1, the `--update` trust and the TOCTOU window are should-fix items that matter at install
time and for the hardening claim, not for the merge.

**What the lead runs for the live install, and what proves success** (in C:/Users/_OPERATOR_/BlarAI after this branch is on main;
the primary checkout may be on any branch):
1. `git -C C:/Users/_OPERATOR_/BlarAI config --get core.hooksPath`. Note the value; today it is `C:\Users\_OPERATOR_\blarai\.git\hooks`.
2. `python scripts/install_git_hooks.py --reason "LA install"`. Success: a line starting `installed: hooks copied from main
   (<sha>)` ending `previous hooks path C:\Users\_OPERATOR_\blarai\.git\hooks is chained to`.
3. `python scripts/install_git_hooks.py --check`. Success: exit 0 and `OK: installed from main <sha>, intact, equal to
   main's tip`.
4. `python scripts/install_git_hooks.py --status`. Success: `Commit protection is ON for this repository`, with no "OFF or
   BROKEN" line.
5. `python scripts/prove_commit_protection.py --live --i-am-the-lead`. Success: 8 PASS lines and `ALL PASS`, including
   `PASS  LIVE: --check on this repository`.
6. Real-repo negative test from a throwaway worktree on main:
   `git worktree add C:/Users/_OPERATOR_/blarai-wt-protect-test main`, create `services/_probe.py`, `git add services/_probe.py`,
   `git commit -m probe`. Success: `BLOCKED by the git-native pre-commit guard` and `services/_probe.py: ...`, and
   `git log -1 main` unchanged. Clean up with `git reset -q services/_probe.py`, delete the file, then
   `git worktree remove C:/Users/_OPERATOR_/blarai-wt-protect-test`.
7. Post-commit chain: the next normal companion commit on main still writes its Claude-Projects dirty-log line, as before.
8. Undo path, if anything is wrong: `python scripts/install_git_hooks.py --uninstall`. Success: `core.hooksPath restored to
   C:\Users\_OPERATOR_\blarai\.git\hooks`, and step 1's command prints exactly that again.

Before step 2, fix S1. Otherwise one edit to `.git/blarai-install.json` silently turns protection off. Step 3 would show it,
but nothing re-runs step 3 by itself.

---

# Round 5: S1 re-verification, `feat/1690-install-hardening` @ a4e195ee

Method: temp repos built with the real installer (scratchpad n4/s1.sh). In each one, a code commit on main, a companion
commit, a `merge --no-ff` of a feature branch, `--check`, and a feature-branch commit were each tried after one record
tamper.

- **S1 FIXED.** Each of these tampers blocked the code commit, the companion commit and the `merge --no-ff` on main, and
  `--check` reported NOT OK:
  - `common_dir`
  - `repo_roots` (unknown hash, or an extra bogus root)
  - `version` (2, or the string "1")
  - `source_commit`
  - `source_branch` deleted
  - interpreter path, `interpreter_hash`
  - a hook hash
  - `hook_count`, `hook_count_str`
  - record deleted, garbled, `{}`, or `[]`
- Not validated, and harmless: `previous_hooks_path` and `installed_at` edits still allow. The shims chain via
  `blarai-previous-hooks`, not that field.
- **Valid record:** code is refused; the companion commit and `merge --no-ff` land; the chained post-commit fires;
  `--check` is OK.
- **Feature branches are NOT unaffected by every corruption.** A feature-branch commit still works after the identity, hook
  and count tampers. It is REFUSED (rc=1) when the interpreter fields are bad or the record is deleted, garbled, `{}` or `[]`:
  "BLOCKED: the recorded python () is missing or changed; run: python scripts/install_git_hooks.py --update". This is fail
  closed, but it means every commit on every branch, in every worktree, is refused until `--update` runs.
- **Recovery works and the text guard allows it on main:** `--status` (exit 1, OFF/BROKEN), `--check` (NOT OK), `--update`
  ("updated: hooks re-copied from main"), and plain install are all ALLOWED; `--uninstall` stays BLOCKED (operator only).
  After `--update`, `--check` is OK, a companion commit works, and the chained post-commit fired.

**S2 · SHOULD-FIX (affects the documented recovery): plain install after the record is lost overwrites the previous
hooksPath with its own folder.**
- Reproduced: delete `.git/blarai-install.json`, then run `python scripts/install_git_hooks.py`. It sets
  `blarai.previoushookspath` to `.git/blarai-hooks/githooks`, its own folder.
- From then on, the chained post-commit no longer fires (0 log lines).
- `--uninstall` then "restores" `core.hooksPath` to the deleted `.git/blarai-hooks/githooks`. The original value (here,
  `C:\Users\_OPERATOR_\blarai\.git\hooks`) is lost, and the dirty-log hook is off.
- `--status` itself suggests this command ("Fix: python scripts/install_git_hooks.py (first install) or --update").
- Fix: never record a previous value equal to the installed folder; keep an existing `blarai.previoushookspath`. Have
  `--status` and `--check` advise `--update` when an install is present.

**Fast core on a throwaway merge into main** (main 32e31564 + `merge --no-ff a4e195ee`, removed):

| File | Result |
|---|---|
| install_hardening | 21 passed |
| git_rules_guard | 79 passed |
| differential | 3 passed |
| failclosed | 26 passed |
| native_pre_commit | 55 passed |
| reference_transaction | 7 passed |
| hooks_chain | 2 passed |
| hooks_hardening | 10 passed |
| rules_corpus | 39 passed |
| doctrine_freshness | 19 passed |
| doc_pointers | 34 passed |

All are `-m "not slow"`. CLAUDE.md is 47,948 B and unchanged.

**MERGE-READY for feat/1690-install-hardening @ a4e195ee.** Fix S2 before the live install.

**Change to the live-install list:**
- Step 8, the undo: if the record is ever lost or corrupted, the lead runs `python scripts/install_git_hooks.py --update`,
  NEVER the plain installer (S2). Then `--check` must print OK.
- Add to step 1: save the previous value now, so a manual restore is possible:
  `git config --get core.hooksPath > %USERPROFILE%\blarai-hookspath-before.txt`.

---

# Round 6: S2 re-verification, `feat/1690-install-hardening` @ c9bdeeba (fix 1f640d76)

Method: temp repos built with the real installer, starting from a PREVIOUS `core.hooksPath` directory that holds a logging
post-commit (scratchpad n4/s2.sh).

- **S2 FIXED.** Four cases were run: the record deleted or garbled, followed by (a) the PLAIN installer or (b) `--update`,
  then (c) `--uninstall`. In all four:
  - The rebuild reported "updated: hooks re-copied from main".
  - `blarai.previoushookspath` stayed the original directory, and `--check` was OK.
  - The chain kept firing: a companion commit wrote its post-commit log line, before and after uninstall.
  - A code commit was still refused.
  - `--uninstall` restored the EXACT original string.
- Plain installer run twice: "already installed" both times, the chain fires, and the exact restore holds.
- Originally unset: restore leaves `core.hooksPath` unset, even after record loss plus a plain reinstall.
- Original relative `.old-hooks`: record garbled, then `--update`, then `--uninstall` restores `.old-hooks`.
- `blarai.originalhookspath` missing alone: uninstall falls back to `blarai.previoushookspath` (correct value).
- Both keys missing plus the record deleted: `--uninstall` REFUSES (rc=1) with "the hooks path from before the install is
  unknown ... Set it by hand", and leaves the installed path in place. It does not guess and does not restore a missing
  folder.
- Ritual with a valid record: feature commit OK, `worktree add <p> main` + `merge --no-ff` OK, companion commit with the chain
  firing OK, code commit refused, `--check` OK.

Fast core on a throwaway merge into main (main + `merge --no-ff c9bdeeba`, removed), `-m "not slow"`:

| File | Result |
|---|---|
| install_hardening | 21 passed |
| git_rules_guard | 79 passed |
| differential | 3 passed |
| failclosed | 26 passed |
| native_pre_commit | 55 passed |
| reference_transaction | 7 passed |
| hooks_chain | 2 passed |
| hooks_hardening | 10 passed |
| rules_corpus | 39 passed |
| doctrine_freshness | 19 passed |
| doc_pointers | 34 passed |

CLAUDE.md is 47,948 B and unchanged.

**MERGE-READY for feat/1690-install-hardening @ c9bdeeba.** The round-5 caveat "never run the plain installer for recovery"
is withdrawn: both the plain installer and `--update` now recover correctly. Step 1's saved copy of the old value stays as a
belt-and-braces measure.
