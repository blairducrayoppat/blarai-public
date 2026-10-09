# Code review #1690 — round 3 (independent), commit 29f44d38

Reviewer: independent (did not write this code). Branch `feat/1690-install-hardening`, worktree
`C:/Users/mrbla/BlarAI-worktrees/1690-install`, tip `29f44d38`. All experiments in throwaway repos
under the session scratchpad `.../scratchpad/r3`; no installer was ever pointed at a real repo.
Interpreter `C:/Users/mrbla/BlarAI/.venv/Scripts/python.exe`; `LOCALAPPDATA` redirected per run.
Shell for hooks: git-for-windows bundled sh (git 2.55.0.windows.1).

## Verdict

- **R1 (any single failure during swap/rollback leaves main committable with protection off): CLOSED.**
- **R2 (fake/malicious interpreter lets a code commit on main succeed): CLOSED** (to the documented
  residual: an attacker who both rewrites the record's interpreter fields AND supplies a program that
  prints the token — explicitly out of scope, answered by #1689).
- No BLOCKING or SHOULD-FIX findings. Four NOTES below.

I could not break the protection with any input I constructed.

## Suites run (at 29f44d38, my own runs)

- `test_git_swap_and_handshake.py` + `test_git_companion_allowlist.py`, `-m "not slow"`: **33 passed** (193s).
- `test_git_hooks_hardening.py` + `test_git_native_pre_commit.py` + `test_git_install_hardening.py`
  + `test_git_install_recovery.py`, `-m "not slow"`: **88 passed** (320s).
- Slow mutant tier (`test_each_mutant_of_the_round_two_controls_is_caught` +
  `test_hardening_mutant_is_caught`), `-m slow`: **16 passed** (170s).
- `prove_commit_protection.py` (throwaway, no `--live`): **ALL PASS** (7 checks).
- Fast re-run of the five modified files incl. `test_git_update_consent.py`, `-m "not slow"`: **113 passed** (640s).
- R1 every-step slow tier (`test_r1_every_remaining_step_of_the_swap` × transient/sticky/cut for k=1..22,
  + `test_r1_a_locked_file_...` for all six LOCKS), `-m slow`: **58 passed** (661s).

## What I attacked and the result

### R2 / Q2 / Q3 — interpreter handshake and hostile environment
- Repointed the record's `base_interpreter` at a fake python that just `exit 0` (with the record's
  `base_interpreter_sha256` updated to match the fake). A code commit on main was REFUSED:
  `BLOCKED: the guard exited 0 without the affirmative token ...`; HEAD stayed at 1 commit.
  Repro: `scratchpad/r3` t3 — fake `fp.sh` `#!/bin/sh\nexit 0`, record repointed, `git commit` on main.
- The affirmative token is `BLARAI-GUARD-OK <sha256(guard file)>`; the shim recomputes that sha256
  itself via `_sha256_of` (system `sha256sum` through `command -p`), so a bare exit 0, a wrong token,
  a replaced guard, and a fake python without the protocol are all refusals. The token binds the guard
  *bytes* (same file the shim hashes), so it is not a blind constant that any exit-0 program satisfies.
- `command -p sha256sum` is used for the verifier, never the caller's PATH; the look-alike-`sha256sum`-
  first-on-PATH attack and the exported-function (`BASH_FUNC_*`), `BASH_ENV`/`ENV`, and PYTHON-var
  hostile environments are all defended — the parametrized `test_r2_a_hostile_environment_*` tests
  (both the pre-commit and the `git update-ref` paths) passed, and the mutants `s_sha256sum_found_on_path`
  and `s_function_overrides_not_unset` are killed in the slow tier.
- `--no-verify` (skips pre-commit) on a code commit on main is still REFUSED by the
  reference-transaction layer (defense in depth). Repro: t4.
- Residual (documented in ADR-043 and the explainer, and in my repro it is the ONLY surviving path):
  rewrite the record's interpreter fields AND provide a program that reads the guard and prints the
  token. Accepted, answered structurally by the three-account design (#1689). Not a finding.

### R1 / Q1 — swap and rollback failure injection
- I enumerated the swap steps in `_materialise` (record moved aside → per-file `os.replace` → stale
  unlink → per-file blob re-verify → `_write_record`) and the rollback (`_restore_exact`: copy2 side
  file → `os.replace` → extra-file unlink → post-restore comparison). Every `os.replace` is covered by
  the injection harness in three modes (transient, sticky, power-cut via `os._exit(9)`) plus a locked
  file at each hook; the invariant asserted each time is `code_commit_refused(repo)` on main.
- Steps the `os.replace` injection does NOT wrap (stale `unlink`, the `_git hash-object` verify loop,
  the `.restore` copy2) all fall through to the same `except BaseException` → rollback → fail-closed,
  and a leftover `pre-commit.restore` sidecar makes `verify_install` fail the file-count check (not a
  hook git runs), so it fails CLOSED, not open. The test's `assert_protected` tolerates `.restore`
  sidecars because the shim already refuses on them.
- A power-cut mid-swap leaves the record absent → every shim refuses every commit (even a companion)
  until `--update` → recoverable with `--accept-drift` (`test_r1_a_cut_swap_is_recoverable...`).
- Fast R1 cases (transient/sticky/cut, locked pre-commit) passed; mutants `s_rollback_deletes_first`
  and `s_record_not_aside` are killed. Full every-step slow tier result: see tail.

### Q4 — companion allowlist
- Journal is root `BUILD_JOURNAL.md` on main (confirmed `git ls-tree main`). The new lock
  (`test_git_companion_allowlist.py`) replicated by hand: with the real allowlist, missing-entries=[];
  re-adding the OLD bug `docs/BUILD_JOURNAL.md` makes the lock report it missing → the lock genuinely
  fails on a wrong entry (toggle confirmed, and `test_the_journal_commit_is_refused_when_the_allowlist_
  carries_the_wrong_path` passes).
- Journal-only commit on main ALLOWED. Smuggling attempts all REFUSED on main:
  `BUILD_JOURNAL.md`+`evilpkg/evil.py` (code file outside allowlist), `docs/reviews/evil.py` (code
  extension inside an allowlisted dir), new `docs/research/x.sh`, symlink named `LESSONS.md`
  (mode 120000). `..` path components are caught by `_path_problem`. Repros in t2.

### Q5 — mutant kill decision
- Kill is a discriminating split, not a crash-counter: `test_hardening_mutant_is_caught` asserts
  `baseline is True` (unmutated control blocks) AND `mutant is False` (mutated control ALLOWS the
  attack, i.e. commit returncode == 0). A crash in the mutant makes returncode != 0 → scenario returns
  True → `assert ... is False` FAILS loudly. So a crash is never counted as a kill. The five retargeted
  hardening mutants (notably "interpreter hash unchecked" → `if false`, isolated on a feature branch so
  only the shell check is load-bearing; "isolated python off" removing `-I -S`; "lib check skipped")
  and all new round-2 mutants pass (16/16 slow).

### Q6 — fail-silent paths and doc/code agreement
- The guard writes the token only to stdout on success (bytes, no CRLF), diagnostics to stderr, under
  `-I -S -B` (no stdout warnings), so the token is not polluted. Failure paths exit 1.
- The text guard imports `COMPANION_ALLOWLIST` from `rules_common` (no private copy;
  `test_text_guard_uses_the_shared_allowlist_and_has_no_copy`), so the journal-path fix reaches all
  three layers.
- ADR-043 and `commit-protection-explained.md`/`git-rules-guard.md` were updated to match the code
  (base interpreter + sha256 + token; root `BUILD_JOURNAL.md`). The ADR claim "a commit loop from
  another process during --update" is backed by a real test
  (`test_no_code_commit_on_main_succeeds_while_update_runs_in_a_loop_from_another_process`).

## NOTES (not blocking)

- **K1 (NOTE)** `scripts/githooks/_lib.sh:120` — on `main`, the shell `base_interpreter_sha256` check
  is redundant with the python-side `record_problems` (which also compares `base_interpreter_sha256`).
  It is load-bearing only on feature branches (where the python guard returns early). This is defense
  in depth, correctly tested by isolating it on a feature branch; no change needed.
- **K2 (NOTE)** Not exercised by any test: `IFS`, `LD_*`, and alias injection into the hook shell.
  Reading the code they appear inert — all `read` loops set `IFS=`, splitting is by explicit
  parameter-expansion/globs, aliases are not expanded in non-interactive sh, and `LD_*` does not apply
  to the native Windows `python.exe`. Worth one hostile-env row for `IFS` to close the gap by test
  rather than by argument.
- **K3 (NOTE)** The base interpreter's own DLLs and standard library are not hashed (Windows DLL-search
  / stdlib planting beside `C:/Users/mrbla/AppData/Local/Programs/Python/Python311`). Explicitly
  acknowledged in ADR-043 as a residual and assigned to #1689; stated, not a new finding.
- **K4 (NOTE)** Amending a companion commit on main is refused as a history rewrite (by design). Not a
  false positive — the lead adds new companion commits rather than rewriting main — but worth one line
  in the explainer so it is not mistaken for a bug in use.

## What I did NOT test

- The full `-m slow` fuzz/differential files (`test_fuzz_full_2000`, `test_git_rules_guard*`) — out of
  the round-3 scope and very long; I ran the swap/handshake/hardening/recovery/consent tiers instead.
- A genuine OS power-cut (simulated only via `os._exit(9)` injection, which the harness uses).
- `--live` prover against the real repo (would install into a real `.git`; prohibited).
- Real Windows file-locking by a separate antivirus/indexer process (simulated via injected
  `PermissionError` on `os.replace`, which is the Windows failure mode).
