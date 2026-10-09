# Code review: #1690 `--update` consent (review display, digest, install), 2026-10-05

Reviewer: independent adversarial reviewer. Branch `feat/1690-install-hardening` @ `36a1dedf` (base main `32e31564`).
Every installer run used throwaway repos under `%TEMP%\atk1690*` made with `tests/security/_git_hook_helpers.make_repo`
(real installer, real git, real shims). The real repository's hooks and git config were not touched.
Probe scripts: `<scratchpad>/attack1.py`, `attack2.py` / `attack2b.py`, `attack3.py`, run with
`LOCALAPPDATA=$(mktemp -d)` and `C:/Users/mrbla/BlarAI/.venv/Scripts/python.exe`.

Lead under attack (Vikunja #1690 comment 3905): *review-display-differential*. The result is that the lead is
**confirmed in two forms**: bytes that are installed but not shown (W1), and installed state that is neither shown nor
bound by the digest (W2, W3). One lock requires the W1 defect.

## Findings

### W1 — BLOCKING — the review hides the tail of any line longer than 240 characters, and the digest approves it
- `scripts/install_git_hooks.py:188,215` (`LINE_CAP`, `_esc`). The `_esc` docstring (l.194-196) says "nothing printed can ... hide text".
- The scenario: main's `reference_transaction.py` gains the line `x = 1` followed by 300 spaces and then `; import os; os.system('echo PWNED')`.
  The review prints `+x = 1      ...[+101 chars]`. `PWNED` appears nowhere in the review. The approver copies the DIGEST, and
  the installed file contains the payload.
- Reproduced (attack1.py §A):
  `display line: ... ...[+101 chars]` / `PWNED visible in review: False` / `apply rc 0 | installed contains PWNED: True`.
- The lock requires the defect: `tests/security/test_git_update_consent.py:163` asserts `"...[+" in r.stdout  # the 600-character line is capped`.
  ADR-043 l.44 ("long lines are capped") and disposition row S5 ("lines capped") certify the cap as part of the fix for S5,
  "the diff the lead reads can differ from what is installed". The cap reintroduces that differential.
- What it costs: the digest-bound approval is the control the guard's strength rests on (ADR-043). Here it approves bytes the
  approver never saw. The only signal is a `[+N chars]` suffix in a long diff.
- Incidence: the current shims and modules contain no line over 240 characters. The attack needs a hook-file change to land on
  main, which is exactly the case the review exists for.

### W2 — SHOULD-FIX — `--update` rewrites the chained "previous hooks" path without showing it, and the digest does not cover it
- `install_git_hooks.py:502,531-535` (prev comes from `blarai.originalhookspath`, then `PREV_KEY` and the mirror are written).
  `_review` (l.416-474) never prints prev, and `_digest` (l.237) does not include it.
- The scenario: a process with `.git/config` access sets `blarai.originalhookspath=<dir with pre-commit>`. The lead runs
  `--update --dry-run`, sees an unchanged review and the SAME digest, and approves. The mirror now points at that directory, and
  its `pre-commit` runs on every commit, after our guard passes.
- Reproduced (attack1.py §B): `digest unchanged after originalhookspath rewritten: True`, `evil path shown in review: False`,
  `apply rc 0 ... previous hooks path C:/.../evilhooks kept`, `--check rc 0`, `feature commit rc 0 | evil ran: True`.
- Related hole, found while probing: editing `<common>/blarai-previous-hooks` directly gives the same execution, and `--check`
  and `--status` still report OK/ON (attack3.py: `--check after mirror edit rc 0`, `--status: Commit protection is ON`,
  `evil ran: True`). The mirror is not compared with the record's `previous_hooks_path`. Review rounds 1-6 (report l.893) called that
  field "harmless" because the shims read the mirror, but the mirror is the live lever, and nothing verifies it.
- What it costs: no bypass of main's protection, because a chained hook can only add a refusal. It does give arbitrary code on
  every hook event, while `--check` certifies the install.

### W3 — SHOULD-FIX — the interpreter pin hashes the venv launcher, not the interpreter; the digest omits the interpreter path
- `install_git_hooks.py:138-143,237`; `_lib.sh run_guard`; `rules_common.record_problems` (interpreter check).
- (a) Every 3.11 venv's `Scripts/python.exe` is the same stub. `git hash-object` gives `f7cb1e38955b...` for both
  `BlarAI/.venv` and `agentic-setup/.venv`. Which Python actually runs is decided by `pyvenv.cfg home`, which is not hashed.
  Reproduced (attack2.py §F): the hooks were installed under a temp 3.11 venv, then its `pyvenv.cfg` was set to the 3.14 home.
  The recorded launcher then runs `3.14.4`, `--check rc 0`, and the guard executed under 3.14 (its own BLOCKED verdict came back,
  not "recorded python changed"). `--status` item 3 ("The recorded Python program is ... replaced") overclaims.
- (b) The review shows the interpreter path, but the digest binds only the hash, so the path can change after the review.
  Reproduced (§K): the dry run showed `C:/Users/mrbla/BlarAI/.venv/Scripts/python.exe`, the same digest was applied from
  `venvB`, the approval was accepted (`rc 0`), and the record now pins `.../venvB/Scripts/python.exe`.

### W4 — NOTE — `--accept-drift` accepts drift that was never shown
- `install_git_hooks.py:525`; the drift is not part of the digest.
- Reproduced (§H): the dry run showed only `DRIFT: hooks/rules_common.py`. After it, `_lib.sh` was also edited and an unrecorded
  `githooks/pre-rebase` was planted. `--approve <same digest> --accept-drift` gave `rc 0`, and the log lists 3 drift entries.
- Tampering evidence is accepted unseen. The files themselves are overwritten or removed by the update.

### W5 — NOTE — case-variant hook name on main: the review misstates it, and the rollback does not restore the prior state
- Fixture: `scripts/githooks/Pre-commit` added next to `pre-commit` with `core.protectNTFS=false`.
- On NTFS, `_build` writes both names into one file. As a result:
  - The review prints `0 changed, 1 added`, with no content for `Pre-commit`.
  - The digest's sha256 for `Pre-commit` is that of `pre-commit`'s bytes, not main's blob.
- `_materialise` then hits FileNotFoundError and rolls back. After the rollback the file is named `Pre-commit`, and:
  - `--check` reports `Pre-commit: installed but not recorded; pre-commit: recorded but missing`.
  - Main stays blocked, which is fail-closed.
  - `--update` cannot recover while main holds the alias.
  - The rollback docstring and test claim "restores the old hooks", which is not byte-identical here.
- Trailing-dot names (`pre-commit.`, `post-index-change.`) are refused cleanly by `_build`'s hash check.
- Reproduced: attack2b.py §G.

### W6 — NOTE — the shared fixed staging folder `blarai-hooks.new` has no lock
- A concurrent `--update --dry-run` (anyone running a review) deletes and rebuilds `.new` under an approved update. The approved
  run then crashes mid-swap (`FileNotFoundError ... blarai-hooks.new\githooks\_lib.sh`) and rolls back.
- This is fail-closed: the old copy was restored and main was refused. It surfaces as a traceback, not a message.
- Reproduced: attack2b.py §I.

### W7 — NOTE — the diff stat counts added files as "changed"
- `install_git_hooks.py:449-454`.
- Adding one non-empty and one empty file prints `1 changed, 2 added`, but no existing file changed. The same stat goes to the
  install log.
- Reproduced: attack1.py §E.

### W8 — NOTE — any extra file in `scripts/githooks/` becomes a live, unwrapped git hook
- Reproduced (§E): `post-index-change` is shown as added, then installed, and `--check` gives `rc 0`. It then ran on
  `git add` on a feature branch.
- The review shows it, but nothing tells the approver that a new name in that folder is a hook that git will run outside the shim.

## Verified clean (attacked, could not break)
- Exit 3 or 4, dry run, no approval, wrong digest, short digest, `--check` and `--status` change nothing in `.git`. I compared
  SHA-256 of every file under `.git` (objects, logs and index excluded), config included, before and after (attack1.py §D):
  all `changed=[]`. Unsafe content (ESC) gives exit 4 and nothing changed.
- If main moves after the review, the digest is refused (the existing test passed, and §I confirmed it). A staged blob that
  changes after the digest is caught by the re-hash before the swap and the hash check after it.
- Trailing-dot and ADS-style aliases are refused before any swap. CR, DEL, C1, zero-width and bidi characters are shown as escapes.
  `"` and `/` cannot reach the shell `_rec_get` substring lookup through a filename, by reasoning: `/` is illegal in a tree entry
  name and `"` is illegal on Windows. That last point is a hypothesis, not run.
- A locked installed file (opened without share-delete) makes `os.replace` fail. The rollback restored the installed copy
  byte-identical, the record came back, and a code commit on main was refused (attack2b.py §J).
- The probe inside the swap is covered by the fast tests (`test_a_code_commit_on_main_is_refused_while_the_swap_is_under_way`),
  which pass. I did not run the 45-minute slow tier (the every-replacement probe and the loop).
- The first install, `--check`, and `--status` all work, and the interpreter is recorded as an absolute path (attack3.py).
- Hypothesis, not run because this is Windows: an installed shim whose content is unchanged but which has lost its exec bit
  is not detected by the record (hash only). On POSIX, git would then silently skip that hook.

## Suites run (worktree @ 36a1dedf, non-elevated, LOCALAPPDATA redirected)
- Fast core of the 7 touched hook test files + test_doctrine_freshness + test_doc_pointers_and_banners + test_rules_corpus:
  `-m "not hardware and not winui and not slow"`: **204 passed, 163 deselected, 0 failed, 0 skipped** (522 s, serial).
  Every test passed, including the one that locks the W1 defect.
- `scripts/verify_disposition.py docs/reviews/rules-tooling-1690-disposition-2026-10-05.md`: PASS, 56 ok / 0 unjustified.
  Rows S5 and S7 are marked FIXED, but W1, W2 and W3 contradict them.

## Merge read
NOT MERGE-READY. Block on W1: the consent control approves bytes it does not display, and a test requires it. W2 and W3 are
the same differential class, where installed state is not shown or not bound, and should land with W1 or go on named-predicate
rows. W4-W8 are notes.

---

# Round 2: re-verification at `db605011` (2026-10-06)

Round 1 above stays as written; it was tested at `36a1dedf`.

Method: the same rules as round 1. Every attack ran in throwaway repos under `%TEMP%\r2_1690_*` and `w3main_*`, with
LOCALAPPDATA redirected. Probe scripts are `<scratchpad>/r2.py` (tags W1..W7, D, J, F, C) and `w3main2.py`. The real repos'
hooks and config were not touched.

## Round-1 findings re-attacked

| W | Verdict at db605011 | Evidence |
|---|---|---|
| W1 | FIXED | The payload past column 240 is now shown on a `[cont]` line (`PWNED visible: True`). A file whose review output is over 64 KiB gives exit 4, and `.git` is unchanged. A spoofed `[cont]` line from the content still shows as `+[cont] ...`, so it can be told apart. |
| W2 | FIXED (with residual R4) | The original-hooks-path redirect is shown (`recorded @default -> proposed <dir> CHANGED`, plus the chained file's sha256), the digest changes, and the old digest gives exit 3. A mirror edit gives `--check` rc 1 and `--status` "DEGRADED", rc 1. |
| W3 | PARTIAL, see **R2 (blocking)** | A `pyvenv.cfg` repoint now fails `--check`. A digest from one venv applied under another gives exit 3. **But the hook enforcement does not check any of this.** |
| W4 | FIXED | The drift is listed with its sha256 and bound in the digest. New drift after the review gives exit 3, even with `--accept-drift`. |
| W5 | FIXED | A case alias on main gives exit 4 and `.git` is unchanged. A case-renamed INSTALLED file is shown as RENAME. A failed swap (injected in `_write_record`) restores the exact names and bytes. |
| W6 | FIXED | A concurrent dry run inside the approved swap: the approved update completes (rc 0) and `--check` is OK. Two approved updates nested inside each other: the inner one is refused (exit 3) and the outer one rolls back. Main is still refused. |
| W7 | FIXED | One ADDED and one CHANGED file give `1 changed, 1 added`, and each file is labelled. |
| W8 | FIXED | A file in `scripts/githooks` that is not on the allowlist gives exit 4 and `.git` is unchanged. |

## New findings at db605011

### R1 — BLOCKING (regression) — a rollback that hits a locked file leaves main UNPROTECTED
- Location: `scripts/install_git_hooks.py`, the rollback in `_materialise`.
  - It now unlinks every installed file, then `copytree`s the old folder back.
  - If an unlink fails, the rollback aborts halfway: most shims are deleted and the record is moved aside.
- Trigger: an ordinary event, such as an editor, indexer or AV scanner holding one installed file open without share-delete
  during `--update`.
  - `os.replace` fails, and the rollback's `unlink` of the same file then raises WinError 32.
  - `githooks/` is left without `pre-commit` or `reference-transaction`, so git runs no hook, and the record is absent.
- Reproduced (`r2.py J`):
  - `restored byte-identical: False | missing: ['githooks/_lib.sh', 'githooks/applypatch-msg', ...]`
  - `code commit on main rc 0`
  - `feature commit rc 0`
- At `36a1dedf` the same probe restored the copy byte-identical and main was refused (round 1, section J). This is the "main is
  never without protection" invariant broken by the fix.
- The locks do not reach it. Both rollback tests (`test_a_failure_during_the_swap_restores_the_old_hooks_and_record` and
  `test_w5_...restores_the_exact_names`) and the `s_rollback_not_exact` mutant inject the failure in `_write_record`, never in a
  file operation during the swap or the rollback.

### R2 — BLOCKING — the interpreter pin is enforced only by the interpreter it pins
- Locations: `_lib.sh run_guard` and `rules_common.record_problems` / `interpreter_facts`.
  - `run_guard` still checks only the launcher hash, which is the same stub in every venv. It then runs the guard under whatever
    Python `pyvenv.cfg home` names.
  - The new `pyvenv_cfg_sha256` / `base_interpreter_hash` checks run inside that Python (the guard) or in `--check`. A replaced
    interpreter is never made to verify itself.
- Reproduced (`w3main2.py`):
  - Hooks installed from a temp 3.11 venv; a baseline code commit on main gives rc 1.
  - `home` was then pointed at a folder holding a copy of Python 3.14 whose `Lib/encodings/__init__.py` is
    `import nt; nt._exit(0)`.
  - `--check` gives rc 1, but **`code commit on main rc 0 | HEAD moved: True`**.
- What it costs: the main-branch protection is bypassed with one edit to a file outside `.git`, plus a folder anywhere. The
  remaining surface goes beyond `pyvenv.cfg`: the base `python3XX.dll` and stdlib are hashed by nothing.
- Status of the claims:
  - Round 1's W3 rated this should-fix; this reproduction shows a full bypass, so it is raised to blocking.
  - ADR-043 l.44 and `--status` item 3 still state the interpreter pin as protection.

### R3 — NOTE — the digest binds a chained previous hook over 1 MiB by its name only, and binds only the first 100 files
- Location: `_chained` (`"oversize"`, `[:100]`).
- Reproduced (`r2.py C`): a 2 MiB `pre-commit` in the previous-hooks folder was swapped after the review, and the update was
  applied with the same digest (rc 0).
- That folder can change after the install anyway, so the bound is advisory. The display should say "not bound" rather than
  imply that it is bound.

### R4 — NOTE — the shims still chain to the mirror file while `--check` reports DEGRADED, and `--update` does not show it
- After a mirror edit, the redirected hook keeps running on every commit (`r2.py W2b`: `feature commit rc 0 | evil still runs:
  True`) until `--update` rewrites the mirror.
- The `--update` review shows `recorded @default -> proposed @default` and nothing about the mirror's current wrong value.
- Detection meets the round-2 bar. Prevention would mean the shim compares the mirror with the record.

## Attacked and not broken at db605011
- No-change guarantees:
  - Dry run, no approval, no reason, wrong digest, `--check`, `--status` and `--dry-run` leave `.git` byte-identical.
  - Refusals with exit 4 (over-cap, alias, not allowlisted) leave `.git` unchanged.
- First install: `--check` and `--status` give rc 0.
- Losing both the record and the installed files: the update dry run shows `17 added, +860 lines` under the caps and offers
  `--accept-drift`.
- Byte cap as a denial of update: the largest hook file is 16.8 KB, and a full re-add totals about 40 KB, against caps of 64 and
  256 KiB. The headroom is about 3.5x, so not a present risk. A refusal names the manual path.
- The unique staging folders are not left behind after any probe.

## Suites at db605011 (non-elevated, serial, LOCALAPPDATA redirected)
- The fast tier of the 7 touched hook test files and the three docs tests: **214 passed, 176 deselected, 0 failed, 0 skipped**
  (769 s).
  - This differs from the coordinator's 150. The selection was the same 10 files with
    `-m "not hardware and not winui and not slow"`.
  - I did not run the slow tier.
- `verify_disposition`: PASS, 56/56. The record has **no rows for this review yet**.

## Disposition rows needed (one row each)
- W1 through W8: FIXED rows citing `db605011`. W3's row must not say FIXED while R2 stands; its evidence is the same as R2's.
- R1 (rollback regression, blocking) and R2 (enforcement does not check the pin, blocking): FIXED only with a lock that injects
  the failure the probe used. That means a locked or undeletable file during the swap and during the rollback for R1, and a
  fake base Python behind `pyvenv.cfg` for R2. Each needs a commit on main asserted refused.
- R3 and R4: FIXED, or DEFERRED with an observable `blocked-by:` predicate.

## Merge read, round 2
NOT MERGE-READY. Block on R1 and R2: each one lets a code commit land on main. R1 is a regression from this fix commit, and its
trigger is an ordinary locked file. R2 makes the W3 fix detection-only. W1, W2 and W4-W8 are verified fixed.
