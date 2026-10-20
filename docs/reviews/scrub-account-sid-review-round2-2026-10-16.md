# Adversarial review, round 2: machine account SID scrub (#1799), branch feat/scrub-account-sid

Reviewed at `69b5a97b` (fixes `a413c579`, `69b5a97b` on top of round 1's `47ef9daa`; off main `c412af4d`), 2026-10-16
07:27-07:40 -04:00. Reviewer did not author the change and changed no code. Round 1: `scrub-account-sid-review-2026-10-16.md`.

**Verdict: FAIL (one blocker, N1).** Both round-1 blockers are closed as invariants: every round-1 mutation is now killed by
the test file. The blocker is new and is the same class as round 1's: `--check` and `--dir --check` exit 0 on an unscrubbed
file that carries a full account SID, in a shape the rewrite already clears.

## Round-1 findings, re-verified

Mutations run in a scratch `git clone` of the branch at `69b5a97b` (a real git checkout, so `git ls-files` works for the scope
test), each applied and restored, `git status` clean afterwards. Test file baseline: 51 passed.

| round-1 finding / mutation | result at `69b5a97b` |
|---|---|
| F1 `find_sid_hits` reads raw bytes only (`views()` dropped) | killed, 25 failed |
| F1 `MACHINE_SID_RE` without `re.IGNORECASE` | killed, 3 failed |
| F1 `SID_REWRITE_RE` without `re.IGNORECASE` | killed, 3 failed |
| F1 tree `main()`: SID dropped from the opaque-binary skip | killed, 1 failed |
| F1 tree `main()`: SID dropped from the residual check | killed, 1 failed |
| F1 trailing `(?![0-9])` restored (builder: equivalent mutant) | survives, 51 passed; **equivalent confirmed**: the sub-authority and rid groups are greedy and nothing follows them, so the lookahead can never decide a match; 200 000 fuzz strings, lock and rewrite with and without it, 0 disagreements in search or substitution |
| F2 `--dir` SID-in-name check removed | killed, 1 failed |
| F2 gzip with trailing bytes treated as readable | killed, 2 failed |
| F2 `.zip` not recognised as an archive | killed, 3 failed |
| F2 zip member body not scanned / member name not scanned | killed, 1 failed each |
| F3 `SID_SCOPE` emptied (the mutant the builder could not run) | killed, 6 failed, including `test_sid_scope_names_tracked_files` |
| F4 rewrite without the escape/percent/ANSI boundaries | killed, 9 failed |
| tree `main()` unreadable-gzip `or sid_scope` removed; archive skip removed; `check()` container problems removed | killed, 1 failed each |
| `run_dir` residual `find_sid_hits` disabled | killed, 17 failed |
| zip encrypted-member check removed | survives, 51 passed; equivalent in effect by reading, not run: `ZipFile.read` raises `RuntimeError` on an encrypted member, which the `except` turns into "cannot be opened", still exit 1 |

F3: `SID_SCOPE` now names the tracked MXC records (`docs/performance/mxc_proxy_egress_2026-10-15.json`,
`docs/performance/mxc_1406_probe_2026-10-11/summary.json`, the `mxc-1406-probe` raw tree). F5: `--dir` writes a log of index,
name hash and before/after hashes; on the real run copy it holds 19 rows and no name, host or SID.

## Real run folder (scratch copy)

Scratch copy of `%USERPROFILE%\blarai-research-data\mxc-proxy-egress\run-20261016-1`, 22 files; the real folder was only read.
`--dir --check` exit 1 (19 findings) -> `--dir --log <scratch>` exit 0 -> `--dir --check` exit 0 (0 findings). An independent
census (raw, gzip, UTF-16 LE/BE, NUL-stripped and unicode-unescaped readings; not the lock's code):

| | before | after |
|---|---|---|
| `S-1-5-21-<digits>` SIDs (per-file max over readings, summed) | 6 | 0 |
| occurrences of this machine's three sub-authority values | 18 | 0 |
| host or account name occurrences (content and paths) | 193 | 0 |
| `S-1-16-*` integrity SIDs | 31 | 31 |
| `S-1-15-2-*` AppContainer SIDs | 2622 | 2622 |
| `__MACHINE__` placeholders | 0 | 6 |

## Findings

1. **N1 HIGH (blocker): the lock is narrower than the rewrite, so `--check` certifies a file that still names an account SID.**
   `scripts/identity_lock.py:102` (lock lookbehind `(?<![A-Za-z0-9])` over decoded views) against `scripts/identity_lock.py:108-111`
   (rewrite boundaries). A doubly JSON-encoded record, a JSON log line whose field holds serialised JSON with console output, writes
   a line break before the SID as `\\r\\n`; one unescape leaves `\nS-1-5-21-...`, the `n` blocks the lock in every view, while the
   rewrite's `(?<=\\[ntrfb...])` matches the trailing `\n` and clears it. Cost: the pre-push blocker passes a full machine SID
   whenever the check runs on a bundle the rewrite did not touch (a copied folder, a skipped step, a hook that only checks).
   Reproduced (made-up SID):
   `inner = json.dumps({"stdout": "User Name SID\r\n" + SID}); outer = json.dumps({"event": "probe", "message": inner})` ->
   `find_sid_hits(outer)` **False**, `rewrite_machine_sids(outer)` count **1**; triple-encoded the same. Through the entry point,
   one file `a\\nS-1-5-21-...` in a scratch folder: `--dir --check` **exit 0**, `--dir` rewrites it. The same disagreement for a
   percent-escape or `\xHH`/`\uHHHH` escape of a letter before the SID (`%41S-1-5-21-...`: lock False, rewrite 1). Incidence in
   `run-20261016-1`: 0. The discriminating lock is a property: for every input, a non-zero rewrite count implies
   `find_sid_hits` is True before the rewrite; nothing asserts it.

2. **N2 MEDIUM: the tree-mode file-NAME SID rules are unlocked.** `scripts/scrub_public_identifiers.py:435-436` (`check()`) and
   `:588-589` (`main()`). Removing either: 51 passed. `check()` applies it to every tracked file, not only `SID_SCOPE`; that is the
   only rule standing between a tracked `<SID>/...` path and a publish, and no test reaches it. Tree `--check` on the branch:
   0 findings in 4091 tracked files, so the rule fires on nothing today.

3. **N3 LOW: a lock that mandates a spare.** `tests/security/test_machine_sid_scrub.py:155-160`
   (`test_a_sid_glued_after_a_letter_is_neither_flagged_nor_rewritten`) turns round-1 F6 (`userS-1-5-21-...`: a full SID, neither
   flagged nor rewritten) into asserted behaviour. A later fix that catches it fails this test. Contrived shape, no producer found;
   the issue is that the lock certifies the gap as a decision.

4. **N4 LOW (hypothesis for producers; the behaviour is reproduced): the lock answers "is an `S-1-5-21-a-b-c` string present",
   not "do the sub-authorities leave".** All exit 0 under `--dir --check` and `--dir` with the first sub-authority still present:
   a SID truncated by a table column (`S-1-5-21-<a>-42223…`), a SID wrapped across a line break, the bare domain id `<a>-<b>-<c>`,
   a binary SID (raw bytes), a SID glued after a digit. Binary SID as hex or base64, and a zip behind a stub prefix (self-extractor
   shape) also exit 0 (lock blind; values not present in plain form). Incidence in the run copy: 0, by the sub-authority census
   above, which is the measurement that matters. A live-domain value scan in `--dir`, as the volume-serial lock does with live
   serials, would close the class.

5. **N5 LOW: `--dir` without `--log` from a working directory outside a git checkout crashes.**
   `scripts/scrub_public_identifiers.py:482` (`repo_root(Path.cwd())`). Reproduced: `subprocess.CalledProcessError` traceback from
   `git rev-parse --show-toplevel`, exit 1, nothing rewritten (fails closed). From inside a checkout the default log lands untracked
   in that checkout's `docs/reviews/`, whichever checkout the shell happens to be in.

6. **N6 LOW (process): no disposition record for round 1.** `docs/reviews/` has no `scrub-account-sid-disposition-*.md`
   (CLAUDE.md deferral_discipline). Round-1 F6 was converted to a lock (N3) rather than dispositioned, and the second half of F3
   (outside `SID_SCOPE` the only guard, `tests/security/test_no_machine_sid_domain_in_tree.py`, cannot read UTF-16) is unchanged
   and unrecorded.

## Attacked and could not break

- Every round-1 mutation (table above); `SID_SCOPE` emptied in a real checkout copy.
- The real run copy: 0 SIDs, 0 sub-authority values, 0 names after; integrity and AppContainer SIDs kept; the log carries none.
- JSON `\r\n` / `\t` / `\u0053` / `\x53`, percent `%5C`, ANSI, SDDL, lowercase, UTF-16 LE+BOM/BE, gzip, gzip of UTF-16 (the test
  matrix, reproduced through `--dir`); HTML entity and percent-encoded hyphens/whole SID fail closed (exit 1).
- Containers: UTF-16 SID inside a zip, zip inside gzip with trailing bytes, gzip with trailing bytes, tar.gz: exit 1.
- Existing locks: no baseline file touched (`git diff --stat c412af4d..69b5a97b -- '*.json'` empty); `path_in_scope`'s new
  `*` prefix form matches no `USER_SCOPE` entry; `MACHINE_SID_RE`'s only other consumers are in this branch's files.
  `test_no_host_identity_in_tree.py`, `test_no_machine_sid_domain_in_tree.py`, `test_volume_serial_lock.py` pass unchanged.
  Tree `--check` exit 0.

## What was run (hash `69b5a97b`, LOCALAPPDATA redirected to the reviewer's scratchpad, interpreter the primary checkout's `.venv`)

- `pytest tests/security/test_machine_sid_scrub.py tests/security/test_no_host_identity_in_tree.py tests/security/test_no_machine_sid_domain_in_tree.py tests/security/test_volume_serial_lock.py`: **141 passed in 309.86 s**.
- 20 mutants of `scripts/identity_lock.py` / `scripts/scrub_public_identifiers.py` against `tests/security/test_machine_sid_scrub.py` in a scratch clone.
- `scrub_public_identifiers.py --dir <scratch copy> --check` / `--dir --log <scratch>` / `--dir --check`: 1 (19), 0, 0 (0). Tree `--check`: 0 findings, 4091 files.
- A 15-shape attack matrix through `find_sid_hits`, `scrub_bytes` and `--dir` (`--check` and rewrite); a 200 000-string fuzz for the lookahead.

## Merge read

Block on N1: the ticket's contract is that `--check` fails on any SID that remains, and an ordinary nested-JSON record breaks it
while the rewrite already knows the shape; the property lock (rewrite count > 0 implies the lock fired) makes it an invariant.
Do not block on N2-N6, but N2 is one test and N6 is required finishing work under deferral_discipline before the merge.
