# How BlarAI protects its main branch (plain-language explainer)
For the Lead Architect (LA). Decision record: ADR-043. Technical detail: `git-rules-guard.md`. Built 2026-10-05 (#1690).

## The outcome
Two rules used to rest on every Claude session remembering them:
1. No work goes straight onto `main` (the branch holding the finished, reviewed code). Work is built
   on a side branch and brought in with one deliberate step.
2. No "stage everything" commands (`git add -A`, `git add .`, `git commit -a`). Staging chooses which
   changed files enter the next commit; "everything" sweeps in files another session was still editing.

Both were written in `CLAUDE.md` and broken anyway: a sweep silently put another session's
half-finished files into a commit, and code landed on `main` without branch, test run or review.
Now git itself refuses the commits that break rule 1, by whatever route. Rule 2 is best effort only
(layer 3); this page says so.

## How it works: four layers

### Layer 1: a check inside git before every commit (strong)

A "hook" is a small program git runs automatically at a fixed moment; `pre-commit` runs just before
a commit is recorded. It checks the commit itself, not the words typed. On `main` it asks:
- **Is this the repository it was installed for?** Its identity (first commit and git folder) is
  compared with the one written at install. Not `CLAUDE.md` text, not the checked-out branch:
  deleting `CLAUDE.md` or standing on an unrelated branch cannot switch the guard off.
- **Is everything in the commit a "companion" file?** Companions are the paperwork of a finished
  piece of work: journal fragments, ledger, reviews, lessons, roadmap, performance logs. The list is
  short and fixed; only plain data and prose files (`.md .txt .json .csv .yaml .svg .png` and
  similar, up to 2 MB). Programs, scripts, shortcuts, executables and hidden files are refused.
- **Are the guard's own files untouched?** Compared with fingerprints (hashes) written at install.

### Layer 2: a check on every move of main, whatever the route (strong)

Git has many ways to put a commit on `main` without "making" one: copying a commit across
(`cherry-pick`), fast-forwarding, rewriting history (`rebase`), writing the branch pointer directly
(`update-ref`), pushing to itself (`push .`). The `reference-transaction` hook runs whenever any
branch pointer is about to change and judges the change itself. For `main` it allows two things:
- a real **merge commit** made by `git merge --no-ff` (the flag forces git to record an explicit
  "this branch was merged here" commit). The hook rebuilds the merge with `git merge-tree` and
  requires the result to match exactly, so nothing can be smuggled into a merge;
- a **companion-only commit** (the same list as layer 1).

Everything else is refused (deleting or recreating `main`, fast-forwards, cherry-picks, rebases,
reverts, `update-ref`, `branch -f`, `merge --squash` plus a commit). So the working rule is now:
**always `git merge --no-ff`, never fast-forward.**

### Layer 3: a text guard in Claude Code (best effort, not airtight)

Git has no hook for "add" (staging), so for rule 2 the only seam is the text of the command before
Claude runs it. A Claude Code "PreToolUse" hook (a check run before a shell command) blocks
blanket-staging forms and the ways to switch layers 1 and 2 off: `--no-verify` (skip the hooks),
changing the hook path, uninstalling. Reading text is weak: shells have many spellings for the same
command. A test program that generated thousands of variants through real bash and PowerShell found
more than 24 ways around this guard over several rounds; each was fixed and locked with a test.
That is why layers 1 and 2 exist and why this layer is a help, not a wall.

### Layer 4: the rules index (traceability, not enforcement)
`rules-corpus.yaml` lists every rule and what enforces it (`enforces-rule:` markers); `rules-gaps.md` lists rules with none.

## Install, check, status, update (lead-facing commands)
First save your hooks path: `git config --get core.hooksPath > hooks-path-before.txt`. Then run
`python scripts/install_git_hooks.py` in the repository, and:
- `--check`: exit 0 only if protection is installed, intact AND equal to what `main` holds (the command to trust).
- `--status`: plain words: is protection ON, and the three facts that would turn it off.
- `--update --dry-run` prints the sanitised review in full (source commit, DRIFT of installed files, diff against
  `main`, python pin, chained previous hooks, a DIGEST of it all). Read it, then `--update --reason "<why>"
  --approve <digest>` (plus `--accept-drift`); a stale digest exits 3; unsafe content (ESC, NUL, bidi, bad UTF-8),
  a review too big to show, case aliases or unlisted hook names exit 4. `--uninstall` restores your hooks path.
- `python scripts/prove_commit_protection.py --live --i-am-the-lead`: PASS/FAIL proof in a throwaway
  repository (code refused, companion and `--no-ff` merge allowed, your dirty-log hook fires, uninstall restores).

Install COPIES the hook files from `main` into `.git` (no branch, checkout or deleted folder can change
them) and points git there by absolute path. `.git/blarai-install.json` records the repository identity,
a fingerprint of every file, the `main` commit and the Python program with its fingerprint; only that
Python (the base one, checked by sha256 first) runs the guard, isolated, and counts only if it prints the guard's proof token.
Your original hooks path is kept in `blarai.originalhookspath` and still runs.

The three things that turn it off: (1) `core.hooksPath` in `.git/config` stops pointing at the
installed folder; (2) the installed files or the record inside `.git` are changed or deleted;
(3) the recorded Python is moved or replaced. The operator can do all three; the text guard blocks
the command forms a session could use. The override
`BLARAI_GIT_RULES_OVERRIDE=<reason>` is set by hand before starting a session; each use is logged.

## A legitimate day

1. A session makes a branch (`git checkout -b feat/1700-thing`) and commits there. Nothing is blocked.
2. Once reviewed and tested, it goes in with `git merge --no-ff feat/1700-thing` while on `main`.
   Layer 2 rebuilds the merge, finds it identical, allows it.
3. The journal entry is a companion commit: stage `docs/journal_fragments/...`, then `git commit`
   as a separate step. Both layers see only companion files and allow it.
4. On a conflict: merge `main` into the side branch, fix it there, then run the `--no-ff` merge.

Amending a commit that is already on main is refused as a history rewrite, by design: a correction to a journal or companion commit goes in as a new commit, never an amend.

## Three blocked attempts (messages shortened; the real ones name the files)

- **Code committed on main.** `git commit` with `services/app.py` staged:
  `BLOCKED by the git-native pre-commit guard ... commit on 'main' contains changes that are not
  companion changes: services/app.py: outside the companion allowlist. Work goes on a feature
  branch ... and lands on main with git merge --no-ff <branch>.`
- **Fast-forward.** `git merge feat/x` that would only slide main forward:
  `BLOCKED by the git-native reference-transaction guard ... commit 3f2a... would land on
  refs/heads/main but is not a companion commit ... Work lands on main only by git merge --no-ff.`
  (git then aborts after already changing your files: the message says to run `git reset --merge`,
  which undoes that and keeps your own edits. The text guard refuses such commands first.)
- **Stage everything.** `git add -A`:
  `BLOCKED by the git-rules guard ... git add -A stages everything, including other sessions'
  untracked files. Stage explicit paths: git add <path> ...`

## What this does NOT stop

- Anything while it is not installed or after the setting is removed; `--check` shows it.
- `--no-verify` skips the commit hook; layer 2 and the text guard still catch it.
- Editing BOTH installed shims, the record or `.git/config`, a Python faking the proof token, or git run internally.
  The record and copies live in `.git`, which a session can write: fingerprints catch drift and
  single-file edits (a record that disagrees with the repository blocks `main`), but are NOT a
  boundary. Editor-tool edits there are not seen by the text guard; only `--check` shows them.
- `--update` installs whatever `main` holds: the guard is only as strong as review of changes to the
  hook files, so it shows the review and needs `--reason` and the digest; every state of the swap refuses `main`.
  `--i-am-the-lead` is a typed flag, harmless because `--live` only reads.
- Blanket staging in a command shape the text guard cannot read (no git-native control exists), use
  of the logged override, or wrong code on a branch (this controls the route onto `main`).

## Choices not made, and why

- **(a) The text guard alone.** Rejected as the main control: every round found new bypasses (shells and
  git offer many spellings). Kept only for staging, where nothing better exists.
- **(b) Git hooks only.** Not enough: no hook for staging, `--no-verify` skips the commit hook, and
  the default folder (`.git/hooks`) is not versioned. Chosen: versioned hooks installed through
  `core.hooksPath`, plus the text guard for what hooks cannot see.
- **(c) Server-side protection (a rule on a remote server).** No hosted remote is in the working loop
  (the public copy is an unrelated history patched via a temporary worktree); possible later for the mirror.
- **(d) File permissions.** Sessions run as the operator, who owns the files; denying them needs a
  separate account. The three-account design (#1689) is the long-term answer for the coder fleet.
- **(e) Signed commits.** A signature proves who made a commit, not whether it belongs on `main`.
- **(f) Claude Code permission rules denying `git commit`.** Text patterns again; they also block the merge routine.
- **(g) Doing nothing, relying on discipline.** The rule was in `CLAUDE.md` and failed through memory.
- **(h) A separate "gatekeeper" repository** where sessions only push and one process alone updates
  `main`. Strongest, but a change to how work is organised: the possible next step if the gaps above bite.
- **(i) Use the TPM (signed hook manifest): not adopted; the session's reasoning.** A TPM stops a key
  being copied, not used by a process running as the same user (ADR-018 says so for `tpm_signer.py`);
  the checker in `.git` is writable by that user; the real failure was accidents, which fingerprints
  cover; each hook change would need a ceremony and recovery mode (the brittleness behind the 2026-07-15
  decline of PCR sealing). Revisit under a separate account: an administrators-only folder is stronger.
