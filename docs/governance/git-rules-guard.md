# Git rules guard (#1690)

Two layers enforce two CLAUDE.md git_discipline rules (no work commits on main; no blanket staging).

| Layer | Where it runs | Strength |
|---|---|---|
| Git-native hooks: `pre-commit` + `reference-transaction` | inside git (`core.hooksPath`) | strong for what lands on main: no command parser to fool |
| PreToolUse text guard | Claude Code, before a Bash/PowerShell call | best effort: it reads command text |

One shared definition (branches, allowlist, scope and integrity checks, override log):
`scripts/hooks/rules_common.py`. Rule trace: `enforces-rule:` markers in the three hook modules.

## Process

Work lands on main ONLY by `git merge --no-ff <branch>` (never fast-forward), or as a companion-only
commit. On a conflict: merge main INTO the feature branch, resolve there, then `git merge --no-ff`.

## Install (one time per clone; covers every worktree, any checked-out branch)

    python scripts/install_git_hooks.py            # copy the hooks from main's tip, record, set core.hooksPath
    python scripts/install_git_hooks.py --check    # exit 0 only if installed, intact AND equal to main's tip
    python scripts/install_git_hooks.py --status   # plain language: ON or OFF, and what would turn it off
    python scripts/install_git_hooks.py --update --dry-run, then --update --reason "why" --approve <digest>   # sanitised review, digest-bound
    python scripts/install_git_hooks.py --uninstall
    python scripts/prove_commit_protection.py [--live --i-am-the-lead]   # PASS/FAIL proof, temp repo

The files are COPIED (blobs verified) to `<git-common-dir>/blarai-hooks/{githooks,hooks}` and
`core.hooksPath` is that ABSOLUTE directory (`git push .` runs hooks from inside `.git`): no checkout,
branch switch or deleted folder changes what git runs. `<git-common-dir>/blarai-install.json` records the
repository identity (root commit hashes + common dir), every file's hash, the main commit copied and the
interpreter (absolute path + hash). An existing `core.hooksPath` (or default `.git/hooks`) is stored in
`blarai.previoushookspath` (mirrored in `<git-dir>/blarai-previous-hooks`); every shim chains to the
same-named hook there after our logic passes. Not installed, or `core.hooksPath` changed: layer 1 is OFF.

## Layer 1: git-native hooks

Scope is the identity recorded at install (never `CLAUDE.md` content, never HEAD).
- `pre-commit` (on main/master): the installed files equal the record; the staged set is non-empty
  and all companion; detached HEAD, unborn main and `--allow-empty` are refused.
- `reference-transaction` (state `prepared`): an update of `refs/heads/main|master` (an all-zero old
  value is resolved to the ref's real tip) passes only if
  (a) the new commit is a two-parent merge whose first parent is the old tip, whose second parent
  is on a local non-main branch, and whose tree equals `git merge-tree --write-tree old second`
  (a real `merge --no-ff`: no octopus, unrelated history, `-s ours`, smuggled changes), or
  (b) old is an ancestor and every commit in old..new is single-parent and companion-only, or
  (c) the override is set. Deleting, creating, rewinding or rewriting main aborts, as do
  fast-forward merge, cherry-pick, revert, am, rebase, pull, commit-tree + update-ref,
  `branch -f`, `push . x:main`, `merge --squash` + commit. Other refs are never judged. The refusal
  names `git reset --merge` (git has already changed the files). Ref names match case-insensitively.
- The shims verify `_lib.sh` (inline, before sourcing it) and then every installed file against the
  record, and run the RECORDED base interpreter (full path, sha256 checked first, never found on PATH) as `python -I -S -B`; allow only on the guard's printed token.
Companion allowlist: `docs/journal_fragments/` `docs/ledger/` `BUILD_JOURNAL.md`
`docs/BUILD_JOURNAL_ANTHOLOGY.md` `LESSONS.md` `FIELD_NOTES.md` `docs/sprints/ACTIVE_SPRINT.md`
`docs/ROADMAP.md` `docs/DECISION_REGISTER.md` `docs/archive/` `PERFORMANCE_LOG.md`
`docs/performance/` `docs/reviews/` `docs/research/`; only plain 100644 files of type
`.md .txt .json .jsonl .csv .yaml .yml .svg .png .jpg`, at most 2 MB, with a safe path (no
backslash, `..`, `:`, trailing dot/space, dotfile, non-NFC, or case-variant of a tracked path).
Symlinks, gitlinks, executables and mode changes are refused. About 56 existing `.py` files sit in
allowlisted dirs: they stay tracked and may be deleted, but new or modified `.py` there ride a branch.

## Layer 2: PreToolUse text guard (`scripts/hooks/git_rules_guard.py`, `.claude/settings.json`)

Git has no `add` hook, so text is the only seam for blanket staging: best effort, not airtight.
It blocks `git add|stage` with `-A --all -u . * :/ ...`, `commit -a`, only-blanket pathspecs, through
wrappers, aliases and unresolved expansions; a commit sharing a call with a state change or with
`GIT_DIR`/`GIT_CONFIG_*`; the companion rule on main (an early readable refusal); and the ways to
switch layer 1 off: `commit/merge --no-verify` and `-n`, `git -c core.hooksPath=...`, `--config-env`,
`git config` touching `core.hooksPath` or `blarai.previoushookspath`, `install_git_hooks.py
--uninstall`. Quality is measured against real bash and pwsh (differential harness, seeded fuzzer,
`pytest -m slow`); every fault ends in exit 2. `.claude/settings.json` fails closed (missing
script or crashed interpreter blocks every shell call; recovery: `git checkout` the file, or override).

## Operator override (both layers)

`BLARAI_GIT_RULES_OVERRIDE=<reason>` in the environment of the process that runs git (for Claude
Code: before launching it); each use is logged to `BLARAI_GIT_RULES_OVERRIDE_LOG` (default
`~/.claude/logs/git_rules_override.log`); an unwritable log keeps the block. Unset it after use.

## Honest limits

- Not installed means off; `--check` and `--status` report it. Branches, checkouts and deleted
  `scripts/` folders no longer matter: git runs the installed copy.
- `commit --no-verify` skips pre-commit and git cannot stop it; the reference-transaction hook still
  judges the update of main, and the text guard blocks the flag.
- The two installed shims are the first code git runs and cannot verify themselves: editing ONE leaves
  the other to refuse updates of main; editing BOTH to `exit 0`, editing `.git/config` or the install
  record (unsigned, same trust as `.git`), or a program that runs git internally switches it off.
  Edit/Write-tool changes to files inside `.git` are not seen by the text guard (shell text only);
  `--check` shows them. A byte-level difference of any installed file, including line endings, counts.
- Editing the guard or settings changes the control itself: same trust level as the destructive-git hook.
