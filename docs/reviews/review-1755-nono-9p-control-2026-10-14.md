# Adversarial review: the extended nono 9P fail-closed control (#1755)

Reviewer: independent (Fable). Wrote no fix, committed nothing, edited nothing in the worktree except this file.
Clock 2026-10-14 22:48 to 23:06 -04:00, elevated shell, Windows python 3.11.9 (`.venv`), run with `-I`.
Reviewed: `tools/probes/nono_9p_failclosed_control.py` on branch `feat/1755-nono-9p-control`, worktree
`%USERPROFILE%\BlarAI-worktrees\nono-9p-control`, tip `7da29183`, file sha256
`b7cc9a6a53089ffdfc68b82ac3b5f2bad87f3eff6940d44da143939c44536302` (hashed at the start and the end, unchanged;
`git status` clean before this file was written). 1764 lines.
Mutations ran on copies under the session scratchpad, `%LOCALAPPDATA%\Temp\claude\<project>\49a071f9-7987-438f-a8f2-fc02b987e80e\scratchpad\r1755\`
(`orig.py`, `mut_*.py`, `mutate.py`, `break_preflight.py`, `hostile_names.py`, `force_cleanup.py`).

## VERDICT: PASS, with R1-1 to fix before merge and R1-3 to fix in the ticket wording

## SAFE TO RUN LIVE: yes

Conditions: run `--prepare-windows` from an elevated shell (Developer Mode is off on this machine, so symlinks need
elevation; the record I made shows all seven links created only because the shell was elevated); keep Explorer and any
AV scan off `C:\wsl` during the run (R1-6); read the first case's `prompt_path` values and `output_tail` before trusting
a case where W_IN and L_IN are both denied (R1-4). The live run writes only under `/mnt/c/wsl/<fixture>`, `/root/work`
(created) and the `--out` path; the matrix is bounded (60 s per run, abort after 6 consecutive timeouts).

Not run, by the brief: `--live`, nono, anything inside WSL, the pty runner (`run_pty`, lines 760-820) and the WSL
self-test. The lead's WSL self-test result was not on the ticket when I read it (22:49).

## Findings, most severe first

### R1-1 MEDIUM: the headline fix has no lock. The first script's "nono started" rule passes the self-test unchanged.
- **Cost.** The one defect the builder found in the first script (started accepted on exit 0/1/2 without the banner)
  can be put back by the next edit and 990/990 still prints. The builder's "8 mutations all caught" does not cover it.
- **Where.** `execute`, line 567 (`started = SANDBOX_MARKER in (res.out + res.err)`); the only not-started fixture is
  `SimNono(started=False)`, lines 1368-1369, which returns rc 127, and the old rule also treated 127 as not started.
  Checks at line 1502 (`not-started`, 30 rows) and 1434 (`judge`) exercise rc 127 and `started=False` as an input;
  neither exercises "exit 2, no banner".
- **Reproduced.** `mutate.py M04b` (line 567 -> `... or res.rc in (0, 1, 2)`): `self-test: 990 checks, 0 failed`.
  For contrast `M04` (`started = bool(res.out + res.err)`): 30 failed.
- **Self-test check covers it?** No. A discriminating fixture is one more `SimNono` variant that prints no banner and
  exits 2 (nono fails before `Applying sandbox`); the row must read INCONCLUSIVE.

### R1-2 LOW: the live plumbing is only exercised in modes where nothing is inconclusive and every control succeeds.
- **Cost.** A regression that drops INCONCLUSIVE rows from the record, or skips the controls, keeps 990/990; a public
  "n of 360" count would then be computed on a thinned population.
- **Where.** `run_matrix` line 601 (`results.append(row)`), `run_live` line 1697 (`controls = ...`), the `live` checks
  at 1549-1556 (`len(controls) == 30` only; `plain` is a leaky sim that always succeeds).
- **Reproduced.** `mutate.py`: `M10` (controls assumed ok) 0 failed; `M11` (INCONCLUSIVE rows not appended) 0 failed;
  `M12` (preflight expects what it got) 0 failed, see R1-5 for why that one still fails on a broken fixture;
  `M19` (`respell` returns the path unchanged: CASE_* become plain R_OUT/W_OUT) 0 failed; `M20` (S83_R reads the long
  name) 0 failed; `M21` (`ls` check without `rc == 0`) and `M22` (read check also searches stderr) 0 failed, both
  loosen in the strict direction and are harmless with these commands.
- **Self-test check covers it?** No. The dry run is the only place a human would see M19/M20 (I checked it: the
  spelled, 8.3 and stream paths print as the table says).

### R1-3 MEDIUM (wording, not code): the supersession reading is right in effect but its stated evidence is a truncation artefact.
- **Cost.** A public correction that says the first run's sandbox "may not have started" would be wrong, and a
  maintainer can see it from the record.
- **What the old record shows** (`%USERPROFILE%\blarai-research-data\nono-9p\agent-run-20261012-005615.json`,
  read-only): every row stores `stderr_head = err[:500]` (first script, line 126). All 48 heads carry
  `nono v0.79.0`, the `Capabilities:` block and `kernel Landlock V6`. `Applying sandbox...` appears in 12 of 48 heads,
  all of case C; in A, B and D the `Skipping CWD prompt (non-interactive)` line pushes it past 500 characters. So "no
  banner in 36 rows" is where the head was cut, not evidence of a sandbox not applied. The old record also shows the
  sandbox ran commands: B L_IN exit 0 ALLOWED, every C row allowed.
- **What holds.** The first script's rule was `"Applying sandbox" in (out + err) or rc in (0, 1, 2)` (line 113), so the
  old record cannot PROVE the banner for 36 rows, and the box has moved since: the prepare record reads
  `WSL version: 3.0.3.0 / Kernel version: 6.18.54.1-1`, the old record ran `6.18.40.1` on WSL 3.0.1. Supersede on
  those two grounds; never say the sandbox may not have started.

### R1-4 LOW (hypothesis, not reproducible without nono): "started" means the banner was printed, which precedes the restrict call.
- **Cost.** A nono that fails between `Applying sandbox...` and exec (ruleset or restrict error, exit non-zero, command
  never run) reads DENIED_AS_POLICY on every deny probe and OVERDENIAL on every allow probe of that case. That is the
  same shape as the #2089 over-denial the first run saw in cases A and D (W_IN and L_IN denied, exit 2).
- **Where.** `execute` line 567; `judge_run` line 500.
- **What separates the two.** The row's `output_tail` (line 570: 400 characters after the banner) carries the inner
  command's own error text (`cat: ... Permission denied`, `sh: 1: cannot create ...`) when the command ran, and nono's
  own text when it did not. The first run's exit codes (2 for `ls` and `sh` denials) fit a command that ran. Reading
  rule for the live record: a case with W_IN and L_IN both denied is read from its tails before it is counted.

### R1-5 LOW: `--preflight-windows` and `--live` take the fixture name without the name gate; the record path is built from it.
- **Cost.** None today: a record must exist at the traversed path with matching `fixture` and `schema`, and
  `--prepare-windows` refuses such names so none is ever written. The inconsistency is that the two modes that write
  probe effects to disk are the ones without the gate.
- **Where.** `load_prepare` line 1626 (`f"{root}/{fixture}.prepare.json"`), `preflight_windows` line 1203, `live`
  line 1668; `FIXTURE_RE` is applied only at lines 1017 and 1161.
- **Reproduced.** `hostile_names.py`: for every one of 10 hostile names (`r1755-review`, `../p1755-x`, `p1755-../x`,
  `C:p1755-x`, `P1755-X`, `p1755-`, `p1755-x/y`, `p1755-x\y`, `p1755-x `, `/p1755-x`) prepare and cleanup exit 2
  `REFUSED: fixture name must match ...`; preflight exits 4 with the traversed path in the message, e.g.
  `INCONCLUSIVE: prepare record C:\wsl/../p1755-x.prepare.json not readable`. Two valid names in my list
  (`p1755-` + 31 letters, `p1755-nono-try`) were prepared and cleaned in the same run; `C:\wsl` before == after: True.
- **Self-test check covers it?** Line 1612 tests the regex only.

### R1-6 LOW (strict direction): any unexpected entry in an ungranted folder is FAIL_OPEN_SUSPECTED, exit 10, do-not-post.
- **Cost.** A Windows artefact (`desktop.ini` from an Explorer customisation, a `Thumbs.db`, an AV marker) in
  `other/` or the fixture root during the run routes the result to the private-advisory notice. The entry is named on
  the row and the notice already says "(or an ungranted folder changed)", so a human can tell; the run should still
  not share the folder with Explorer.
- **Where.** `sweep` line 645 and `windows_sweep` line 1118; `overall` line 515.
- **Reproduced (mechanism).** A file planted through the junction: `--cleanup-windows` exit 10, `other: unexpected
  entry planted.txt`, fixture, record, junction and `other/secret.txt` all kept intact (see commands).

### R1-7 LOW: two WSL-side environment facts read "" when their command is missing, not "missing".
- **Where.** `env_record` line 892, helper `sh()` returns `run_plain(cmd).out` which is "" on rc 127, so
  `nono_version` (line 906) and `kernel` would be empty strings. `findmnt_c` empty is fail-closed (line 1678 refuses).
  The Windows-side facts are honest: `unavailable: ...`, `unknown: ...`, `unreadable: ...` (lines 985-1010), and I
  read them in the record: elevated True, developer_mode False, 8dot3 ENABLED on C:, case sensitivity disabled on
  `C:\wsl`, WSL 3.0.3.0 / kernel 6.18.54.1-1, `.wslconfig` four lines (mirrored, 4 GB, 4 cpus), Bitdefender present
  by both routes (3 image names, 3 company names).

### R1-8 NOTE: the WSL-side sweep does not compare the `ads_stream` content; the Windows-side one does.
- `sweep` (line 645) checks `secret.txt`, the long file and the two write targets; `windows_sweep` (line 1118) also
  checks `ads_host.txt:ads_stream`. Nothing in the matrix writes to that stream (ADS_W creates a new stream name), so
  no verdict depends on it.

## Framing hazard for the public correction (a decision, not a defect)
A read or write that succeeds through a Windows junction or symlink planted inside the grant reads POLICY_VIOLATION
and routes to the private form. That is the stated rule (judged against what the command line grants) and it is the
conservative side. The correction will need to separate what an attacker can plant (a repository can ship a Windows
symlink; git for Windows creates them with `core.symlinks=true` under Developer Mode or elevation) from what only the
operator can make (a junction does not come from a checkout). The script is consistent either way; the wording is the
lead's and the LA's.

## What I attacked and could not break
- **Policy table vs. the command lines**, all 30 probes x 4 cases, derived by hand from `cases()` (line 243) and
  compared with `policy()` (line 325) and the docstring table: no disagreement. W_* and *_W probes land outside `leaf`
  in every case (deny); R/L probes land in `other` or `ungranted_long_dir`, which B (`--read /mnt/c`) and D
  (`--read <fixture>`) grant for reading and A, C do not; GRANT_CASE_R is inside the grant in every case (allow, so an
  over-denial of the upper-case spelling reads OVERDENIAL, never a violation).
- **HL_IN deny in B and D.** Landlock's link hook needs the REFER right on both parent directories and refuses a
  link that would give the file more access than it had; `--read` on `other` grants neither, and a link into the
  write grant would make a read-only file writable. A success is a violation in Landlock's own terms. MV_OUT: a
  Landlock-denied rename returns EXDEV, `mv` falls back to copy + unlink and the copy needs create rights in `other`,
  so the observable (a file in `other`) is the same.
- **Lenient direction.** Every write probe verifies at the real location (`write_spec`, line 368) and the setup
  checks and clears that path first with deterministic tags (`_need_clean`, M07 caught: 12). The per-probe control
  runs the same check (`run_control`, line 575), so an effect the checker cannot see reads INCONCLUSIVE, not DENIED
  (M09 caught: 30). A seen leak beats a missing banner and a failed control (judge order, M01 caught). An unreadable
  effect is INCONCLUSIVE (M14 caught). The effect is read before cleanup (M17 caught: 73). A fixture item that was
  not created is INCONCLUSIVE and not run (M13 caught: 17). On the 9P side, v9fs in cached mode drops negative
  dentries at zero refcount (`v9fs_cached_dentry_delete`), so a pre-run `lexists` does not blind a post-run one; and
  the control would catch it if it did.
- **Strict direction.** Read probes match the secret token in stdout, not a file name; list probes need exit 0 and
  the name; nono's banner carries neither. The verify path of a link write is `other/...`, so a write that lands
  inside the grant is not a violation (M05 caught by the faithful runner: 15). Exit 10 and the notice on a leak
  (M16 caught), the sweep alarm (M15, M08 caught), the timeout abort (M18 caught), a skipped probe (M03 caught: 3).
- **Preflight** on my fixture `p1755-r1755-review`: 30 of 30 baseline. Junction removed by `rmdir`: exactly JCT_R,
  JCT_W, JCT_L fail, each twice (control and verdict); restored: 30/30. Stream content replaced: exactly ADS_R; restored:
  30/30. Short name changed with `fsutil file setshortname ... UNGRAX~1`: exactly S83_R, S83_W; restored to `UNGRAN~1`:
  30/30. The preflight exercises the same `Spec` objects, `execute`, `run_control` and `sweep` as the live run; only
  the operation differs (`SimNono` interprets `cat`/`ls`/`sh -c`/`mv`/`ln` against the real NTFS fixture through
  `MappedFS`), which is what the live control covers. Its claim ("the probe can see a leak through that very link,
  spelling or stream; nothing about nono or 9P") is accurate.
- **Fixture safety.** Links are removed first and never followed: an extra junction I put inside `leaf` pointing at
  a folder outside the fixture was removed and its target's file survived. A folder with a valid name but no marker
  file is refused (exit 2) and left alone. A planted file makes plain cleanup refuse (exit 10) and `--force-cleanup`
  remove (exit 0). Every path operation in the script (lines 632, 688, 692, 937-953, 1025-1030, 1086, 1114, 1195,
  1662, 1684) is under the fixture, the record, the `--out` path or `/root/work`. `C:\wsl` before and after my
  session: `nono-try/`, `p/` (`leaf/`, `other/`), `ubuntu-2404-base.tar`, identical.
- **pty path (read only).** Assumes a yes/no prompt that ends the terminal text (`PROMPT_RE`, line 178) or, after
  1.5 s of silence before the banner, text mentioning the working directory (`CWD_WORDS_RE`, line 179, line 806).
  Each branch is on the row: `pty_prompt_answered_N`, `pty_answered_on_idle_cwd_text`, `pty_no_prompt_seen`,
  `pty_timeout_no_prompt_pattern_matched` (rc 124, killed by `killpg`), `piped_fallback_pty_unavailable: ...`,
  `piped_fallback_pty_error: ...` (`make_runner`, line 829). A prompt nono draws as a selector that ignores `N\n`
  times out, reads INCONCLUSIVE (no banner), and the matrix aborts after six in a row (about 6 min); `--stdin-mode
  piped` is the stated fallback. Stdout and stderr are merged by the pty, so the banner and the token checks see one
  stream. Unverified by execution.

## Self-test shape
990 checks: judge 14, docs 33 (table and string equality), matrix 360 and residue 360 (behavioural, against the
in-memory model with faithful, tight and leaky runners), sweep 5, missing-fixture 17, control 120, not-started 30,
stale 14, exit 6, live 13, prompt 8, windows 10; 1 skip (pty) on Windows. Mutations: 16 of 24 caught (M01-M09, M13-M18,
M06b), 8 not caught (M04b, M10, M11, M12, M19, M20, M21, M22), per R1-1 and R1-2. The Windows-side functions
(`prepare_windows`, `preflight_windows`, `cleanup_windows`, `windows_sweep`, `remove_tree_no_follow`) are not called by
the self-test at all; they were exercised here on real fixtures instead.

## Commands run and results
- `--self-test` (worktree): `990 checks, 0 failed, 1 skipped`, exit 0.
- `--dry-run` (worktree): matrix 4 x 30 x 3 = 360 plus 30 controls; spelled, 8.3 and stream paths print as the table says.
- `--prepare-windows --fixture p1755-r1755-review`: exit 0, 7 links created and verified, 8.3 `UNGRAN~1 / SECRET~1.TXT`
  (dir /x and GetShortPathNameW agree), ADS created, elevated True, developer_mode False, Bitdefender present.
- `--preflight-windows --fixture p1755-r1755-review`: 30/30 PASSED, exit 0 (nine runs in `break_preflight.py`, results above).
- `hostile_names.py`: 13 names x 3 modes, results in R1-5; `C:\wsl` before == after.
- `mutate.py`: 24 copies, `--self-test` on each, results in R1-1, R1-2 and the self-test shape.
- `force_cleanup.py`: marker-less refusal exit 2; outward junction removed first, target intact; planted file: plain
  cleanup exit 10, `--force-cleanup` exit 0; `C:\wsl` back to the start.
- `--cleanup-windows --fixture p1755-r1755-review`: `windows-side sweep: ungranted places unchanged`, 7 links removed
  first, `CLEANED`, exit 0.
- Old record: read with a python one-liner (counts by case of the banner in `stderr_head`, head lengths all 500, the
  W_IN/L_IN rows per case, `findmnt_c`, `not_measured`).

## Merge read
Run live now with the three conditions above; the script's verdict logic, controls, fixture safety and preflight hold
under everything I could run. Before merge: R1-1 (one not-started fixture with exit 2 and no banner), and R1-3 in the
ticket's and the correction's wording (supersede on "cannot prove the banner for 36 rows" and the kernel/WSL change,
not on "nono may not have started"). R1-2, R1-5, R1-7 are small and can land with R1-1 or be ticketed with a
`blocked-by:` that names this file. R1-4 and R1-6 are reading rules for the live record, not code changes.

# Round 2 (2026-10-15)

Reviewer: independent (Opus). Wrote no fix, committed nothing; only this section was appended (uncommitted).
Tip `73086d4c`; script sha256 `9b699d84f912d723ae35691a7314a1a63abc61ad2700520264eaff0a2cbc76a3`. Windows python 3.11.9 (`.venv`, `-I`), LOCALAPPDATA redirected to the session scratchpad. Not run: `--live`, nono, WSL, anything against `/mnt/c` or `C:\wsl`. Mutations on copies under `%LOCALAPPDATA%\Temp\claude\<project>\fa34dd2b-fa00-4bdf-b9b5-bbd8b80a2c99\scratchpad\r2\` (`mutate.py`, `mut_*.py`, `check.py`, `abort_probe.py`, `mclone/`).

## VERDICT: PASS for the script and the numbers; FAIL for publication as banked until R2-2 is fixed. R2-1 and R2-5 before merge.

## Round-1 findings
- **R1-1 FIXED, locked.** `not-started` now runs exit 0/1/2/127 with no banner per probe (120 checks). Round-1 mutation M04b (`or res.rc in (0, 1, 2)`): `1265 checks, 90 failed`; M04c (`or res.rc != 127`): 90 failed.
- **R1-2 FIXED except M12.** M10 2 failed, M11 5, M19 2, M20 1 (were 0). M12 (pre-flight expects what it got) still `0 failed`: `preflight_windows`, `prepare_windows`, `cleanup_windows` are still not called by the self-test. Open; predicate: `preflight_windows` exercised by `--self-test` against a temporary fixture (or a #ticket naming it).
- **R1-5 FIXED, locked.** Gate on `--live`, `--preflight-windows`, `--dry-run`, `load_prepare`; `$` became `\Z` (closes `p1755-x\n`). Mutations G1 12 failed, G2 12, G3 4.
- **R1-7 FIXED, locked.** `command_fact`; mutation F1 3 failed.
- **R1-3** handled in the README's 2026-10-12 section (supersedes on the 500-character limit and the kernel/WSL move, says plainly it is not evidence the sandbox failed to start). **R1-4** reading rule applied by the record: all 63 OVERDENIAL and 222 DENIED rows carry the inner command's own error (`Permission denied` / `Invalid cross-device link`); 0 DENIED rows without the banner.
- New-code mutations caught: T1 (timeout ignored) 34, T2 (`overall` ignores abort) 1, E1 (unexpected list emptied) 1, B1 (bare `mv`) 19, P1 (Esc cap) 2, L1 (old list rule) 3.

## Findings

### R2-1 MEDIUM: "an aborted matrix reads INCONCLUSIVE overall (exit 4), never none seen" has no lock that can fail.
- `conclude` line 678 passes `rec["aborted"]` to `overall`; `run_live` lines 2126-2128 force exit 4. The only end-to-end check (self-test lines 1755-1762) aborts a matrix whose six rows are all INCONCLUSIVE, so `overall` reads INCONCLUSIVE through the all-inconclusive branch whatever `aborted` says.
- Reproduced: T3 (`conclude` passes `False`) `0 failed`; A1 (`run_live` returns `code` on abort) `0 failed`; T3+A1 `0 failed`. `abort_probe.py` on 12 DENIED + 6 INCONCLUSIVE rows with `aborted` set: HEAD `INCONCLUSIVE 4`; T3 and T3+A1 `NO_POLICY_VIOLATION_OBSERVED 0`. That is run 1's wrong shape (a clean overall on an aborted matrix) with nothing to stop it returning.
- Fix: one check that aborts after judged rows (faithful runner for the first runs, then hung) and asserts the record's `overall` INCONCLUSIVE and `run_live` exit 4.

### R2-2 MEDIUM (publication): both run records publish the C: volume's serial number, which the scrub does not see.
- `runs/run1-...json` and `runs/run2-...json` lines 125-126 (`prepare_record.short_names.dir_x_base`, `dir_x_long_dir`) carry the raw `dir /x` header: `Volume in drive C is OS` and `Volume Serial Number is <serial>`. A stable per-machine identifier, new to the public tree (`git grep` on main: 0 hits). `scrub_public_identifiers.py --check` on the merged tree: `0 finding(s) in 4054 tracked files` (it covers host and account names only).
- Fix: the script records only the entry lines of `dir /x` (drop the two header lines) in `prepare_windows`; the banked copies get the same redaction, and the README's "byte-identical to the originals" line becomes "identical except the volume header lines removed".

### R2-3 LOW: the README's list-probe claim is stated as checked from stored fields, and the stored fields cannot show it.
- README "Script changes made after these runs", bullet 2. In piped mode `execute` stores `tail_after_banner(out + "\n" + err)`: the banner is on stderr, after stdout, so the row never keeps the command's stdout. Run 2: the allowed `L_IN` rows of case B have `effect_seen` true and a tail with no listing in it; all 48 list tails are exactly 400 characters, cut at the front. The claim is true (the 33 exit-2 tails each end in `ls: cannot open directory ...: Permission denied`, and that ls prints no entries), but by inference from ls's behaviour, not from the record.
- Fix: say "inferred from the stderr of the 33 exit-2 rows (ls could not open the directory); stdout is not stored in piped rows". The same blind spot means a violation's stdout evidence would not be on the row; one line in the README's limits.

### R2-4 LOW (wording): the PERFORMANCE_LOG plain summary says "30 operations that the command line does NOT grant".
- W_IN, L_IN and GRANT_CASE_R are granted in every case (the README table says `allow allow allow allow`); 27 probes are denied in at least one case. Fix: "30 operations, 27 of them not granted in at least one configuration".

### R2-5 LOW (process): no disposition record for round 1.
- `docs/reviews/` on the branch has the review only; CLAUDE.md `deferral_discipline` needs a `docs/reviews/<topic>-disposition-<date>.md` for #1755 (R1-1..R1-8, R2-1..R2-6) and `scripts/verify_disposition.py` run before the work is reported done. R1-2's M12 residue needs its `blocked-by:` predicate there.

### R2-6 NOTE (merge): `git merge --no-ff` into main `677f9344` conflicts in `PERFORMANCE_LOG.md` only.
- Both sides prepend at line 15 (main's two 2026-10-13 #1763 entries). Resolution: keep both, the 2026-10-14 #1755 entry above them. With that resolution (scratch commit `732ea99b`), `KNOWLEDGE_MAP.md` auto-merges.

## Item 3: the banked records against the README (recomputed with `check.py`)
- Every cell of the 30 x 4 table, the totals 222/51/63/24/0, the group and case tables in PERFORMANCE_LOG, 219 `Permission denied` + 3 EXDEV (case C HL_IN), 222 of 222 with "No path denials were observed", 270 "Skipping CWD prompt" (A, B, D 90 each), 0 exit 124, 0.25-2.32 s, median 0.34, total 136.97 s, controls 29 of 30 (ADS_R), list rows 33 exit 2 / 15 exit 0, the MV_OUT error text and exit 1 without banner, env (kernel, distro, Landlock ABI 7, `lsm` unreadable, `findmnt`, Bitdefender, script sha256 `b7cc9a6a...` in both): all equal.
- Run 1: 6 rows, exit 124, 60.07-60.18 s, `pty_prompt_answered_N`, DENIED_AS_POLICY and overall NO_POLICY_VIOLATION_OBSERVED as written; the tail carries `Review denied paths` and `grant /mnt/c/wsl/p1755-run1 (write dirs)`. README and filename mark it superseded with its wrong labels visible; KNOWLEDGE_MAP cites run 2 only. The file's own `overall` still reads clean to anyone who opens it alone (the filename is the only marker inside the file set).
- README post-run statement: true against `git diff 7da29183 22b5d643` for verdicts (no exit 124 in run 2; list verdicts unchanged; `448e237c` changes argv and labels only). Not mentioned and verdict-neutral: `output_tail` 400 -> 700 characters, timeout judged before the banner.
- Run file sha256: run1 `6f919f73b3b9fb224ccd6d91e69bf20282d4501cdadda283c51bdab45fdd042a`, run2 `6d27fe841cdcb308cea0eeddcb3825eb2c7c9bceb9cf80d8d30c7e2b24c79aa9`. Neither README nor PERFORMANCE_LOG records them. They equal the originals in `%USERPROFILE%\blarai-research-data\nono-9p\` (`agent-run-20261014-230957.json`, `agent-run-20261014-231822-piped.json`), so the "byte-identical" claim holds today.

## Item 4: publication
- Scrub `--check` (main's script, merged tree): exit 0. Folder, fragment and script: 0 operator name, 0 host name, 0 `C:\Users`/`C:/Users`, 0 SIDs (`S-1-5-21`). No campaign wording (job, contact form, Discord, career, recruit, portfolio, campaign: 0). "advisory form" (4) is nono's private security-advisory route, not the campaign's contact form. R2-2 is the one identifier.

## Could not break
R1-1 lock (90 failures under both mutations). The timeout rule (34). The Esc-only key set and the Esc cap. The name gate including the trailing-newline form. The banked numbers: no README or PERFORMANCE_LOG figure differs from the JSON.

## Suites at this hash
`--self-test` at `73086d4c`: `1265 checks, 0 failed, 1 skipped` (pty, no pty on Windows), exit 0. Scratch merge `732ea99b` (main `677f9344` + branch, conflict resolved as R2-6): `tests/security/test_no_host_identity_in_tree.py`, `test_public_snapshot_excludes_private_material.py`, `test_doctrine_freshness.py`, `test_journal_integrity.py`, `test_approval_identity_binding.py`: 235 passed, 0 failed, 0 skipped. Scrub `--check` exit 0.

## Merge read
Block on R2-2 (an identifier into a public snapshot) and R2-1 (the lock behind the defect that made run 1 wrong). R2-3, R2-4 are one-line wording; R2-5 is the disposition record. Not blocking: R2-6 (trivial conflict), the M12 residue with a predicate.

# Round 3 (2026-10-15)

Reviewer: independent (Opus). Wrote no fix, committed nothing; only this section was appended (uncommitted).
Tip `e02f8128` (`804651ad` fixes, `e02f8128` disposition); script sha256 `f1a305875439b11b4f9e912d25f412ee00cb9ca14276b5d3cbae1236f4aa9716`. Elevated shell, Windows python 3.11.9 (`.venv`, `-I`), LOCALAPPDATA redirected. Not run: `--live`, nono, WSL, anything against `/mnt/c` or `C:\wsl` (`C:\wsl` listed before and after: `nono-try/`, `p/`, `ubuntu-2404-base.tar`, unchanged). Scratch under the session scratchpad `r2\r3\` and `r2\mclone3\`.

## VERDICT: PASS. R2-1 and R2-2 are fixed with locks that fail when reverted; the merge into current main is clean apart from the known PERFORMANCE_LOG prepend. Three LOW wording points (R3-1..R3-3), none blocking.

## 1. R2-2: redacted JSONs
- Structural diff of each published JSON against the file the run wrote (`%USERPROFILE%\blarai-research-data\nono-9p\agent-run-20261014-230957.json`, `agent-run-20261014-231822-piped.json`), walking every key and list index: the only differing paths are `/prepare_record/short_names/dir_x_base` and `/prepare_record/short_names/dir_x_long_dir`, in both files. `counts` and `overall` equal.
- Neither file contains `Serial Number`, `Volume in drive`, `Directory of`, `bytes free` or the serial's digits. The remaining text is the dated entry lines only.
- README hashes recomputed: as run `6f919f73...` / `6d27fe84...` (the originals), as published `14e0503f58fbfe15c664ae6239cfdab417f2c4b85f153914f39912ce959831f3` / `71abf7a3d75346fba990bd95f10a9a453d3d8d1b746a5250cd15b638ad1fdb7d`: all four equal the table.

## 2. Locks, by reverting each fix in a scratch copy (`mutate3.py`)
- Self-test at tip: `1275 checks, 0 failed, 1 skipped` (pty), exit 0.
- T3 (`conclude` drops `aborted`): 1 failed, `abort: its record reads INCONCLUSIVE overall, never none seen`.
- A1 (`run_live` returns the conclusion's code on abort): 1 failed, `abort: run_live forces exit 4 on an abort even when the conclusion says 0`.
- M12 (pre-flight expectation read from the result): 1 failed, `windows-fixture: pre-flight with a runner that denies everything fails, exit 1`.
- R2-2 revert (`listing.strip()` recorded again): 1 failed, `windows-fixture: the recorded dir /x text keeps entry lines and no volume header`. Filter regex widened to match any line: 2 failed (that check and `windows: dir listing filter keeps entries only`).
- Not caught, NOTE only: dropping the failed-control list from the pre-flight's `bad` (M12b) stays 0 failed, because a failed control already makes the probe's verdict INCONCLUSIVE, which the probe check catches. Redundant by design, not a gap.

## 3. Test hooks
- `win_root`, `wsl_root`, `mode` and `MappedFS(wsl_root, nt_root)` are parameters only; the CLI calls `prepare_windows(a.fixture ...)`, `cleanup_windows(a.fixture, force=...)` and `preflight_windows(a.fixture)` with no way to set them (`main`, lines 2233-2243), and the defaults equal the old constants (`C:\wsl`, `/mnt/c/wsl`, `leaky`, `C:` for `/mnt/c`). The live path uses `RealFS()` in WSL, never `MappedFS`.
- The self-test's Windows block writes only under `tempfile.TemporaryDirectory()`. The `/mnt/c/wsl/p1755-selftest` paths map to `<tmp>/p1755-selftest`, including the UPPER and Title spellings (`_m` now matches the root case-insensitively and keeps the tail as spelled). Junction and symlink targets are fixture siblings, so `rmtree`/`cleanup_windows(force=True)` stays inside `<tmp>`. `C:\wsl` was unchanged across the run.
- Hypothesis, not run: a non-elevated self-test has `prepare_windows` return 0 with the symlink kinds missing (it warns rather than fails), so the pre-flight's gaps exclude them and the checks still hold. This shell was elevated, so the self-test's `windows-fixture` result covers the elevated case only.

## 4. Merge into current main (scratch clone `mclone3`, main `677f9344`)
- `git merge --no-ff origin/feat/1755-nono-9p-control`: one conflict, `PERFORMANCE_LOG.md`, one hunk; resolved by keeping both with the #1755 entry first (line 15, the two 2026-10-13 entries at 43 and 89). Scratch merge commit `d86a9cd2`.
- `scrub_public_identifiers.py --check`: `0 finding(s) in 4055 tracked files`, exit 0. The ratchet needs a local `main` ref: in a fresh clone that has only `origin/main` it reports `FAIL ratchet: ... main does not resolve` (environmental; passes once `main` exists).
- `scripts/verify_disposition.py docs/reviews/1755-nono-9p-control-round2-disposition-2026-10-15.md`: `PASS - 14 ok / 0 unjustified of 14`.
- Tests (`test_no_host_identity_in_tree`, `test_approval_identity_binding`, `test_public_snapshot_excludes_private_material`, `test_doctrine_freshness`, `test_journal_integrity`): passed. `test_disposition_discipline.py`: 7 failed without `BLARAI_CONSTELLATION_ROOT` in a clone outside the user folder; the same 7 fail on pristine main in the same place (control run, worktree `mainwt`), the cause being "agentic-setup is not present". With `BLARAI_CONSTELLATION_ROOT=%USERPROFILE%`: 43 passed. Total over the six files: 271 passed plus the 7 that pass with the root set, 0 failures attributable to the branch.

## 5. The SID at `docs/performance/containment_probe_2026-10-10/summary-phase1.md:31` on main
- It is the placeholder domain: `S-1-5-21-1000000001-1000000002-1000000003-1001` (RID 1001). Not a real SID.

## Findings

### R3-1 LOW (wording): the README's new limits line says the verdict "rests on the Windows-side checks after the run".
- The effect checks of a live run are made from WSL (`run_live` gets `RealFS()` under WSL, line 2171), and the README itself says the sweep is the WSL view and that the Windows-side sweep is not part of these files. Fix: "rests on the checks made from outside the sandbox (in WSL) after the run".

### R3-2 LOW (wording): disposition row R1-8 says the Windows-side sweep "runs after every live run".
- It runs when the operator runs `--cleanup-windows`; nothing in `--live` calls it, and the README says its output is not in these files. Fix: "runs at `--cleanup-windows`, which follows a live run by procedure".

### R3-3 LOW (evidence): disposition row R1-1 cites `73086d4c`; the fix landed in `dcd4b3f9`.
- `git log -S fail_rc` names `dcd4b3f9` (the R1-5 and R1-7 rows already cite it). `73086d4c` resolves and contains the fix, so the verifier passes, but it is the review-record commit. Fix: cite `dcd4b3f9`.

## Could not break
The redaction (two fields, nothing else). The four hashes. Each reverted fix fails a named check. The hooks cannot be reached from the command line. The SID question.

## Suites at this hash
`--self-test` at `e02f8128`: 1275 / 0 failed / 1 skipped. Scratch merge `d86a9cd2`: scrub `--check` exit 0, `verify_disposition.py` PASS 14/14, the six security test files green (the disposition file with `BLARAI_CONSTELLATION_ROOT` set, as its own message asks).

## Merge read
Nothing blocks. R3-1 to R3-3 are one-line edits and can go in the same commit as the merge's PERFORMANCE_LOG resolution or before it.
