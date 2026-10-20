# Adversarial review: machine account SID scrub (#1799), branch feat/scrub-account-sid

Reviewed at `47ef9daa` (off main `c412af4d`), 2026-10-16 07:01-07:15 -04:00. Reviewer did not author the change and changed no code.

**Verdict: FAIL (two blockers, F1 and F2).** On the real run folder the scrub works: a scratch copy of
`%USERPROFILE%\blarai-research-data\mxc-proxy-egress\run-20261016-1` (22 files) went from 19 findings to 0, and an independent
scanner (not the lock's code) found 0 `S-1-5-21-<digit>`, 0 occurrences of this machine's three sub-authority numbers, 0 account
names and 0 host names afterwards, in raw, unicode-unescaped and NUL-stripped readings. Before the scrub the same scanner counted
18 SIDs, 54 sub-authority occurrences and 579 account-name occurrences. The only relative id in the run is 1001. The blockers
concern what the locks certify and what `--dir`, the mode a raw-record bundle actually goes through, does not see.

## Findings

1. **HIGH (blocker): the encoding coverage of `--check` is not locked.** `tests/security/test_machine_sid_scrub.py:72-82`.
   The UTF-16 and gzip cases assert only that the lock is *silent after* the rewrite, never that it *fires before* it, so a lock
   that cannot read UTF-16 or gzip passes them trivially. The `--check` and `--dir` tests use plain UTF-8 JSON only; the
   lowercase spelling and the digit lookahead are not exercised at all.
   Reproduced by mutation in a scratch copy of `scripts/` plus the test file (7 tests, baseline 7 passed):
   | mutation | result |
   |---|---|
   | `find_sid_hits` reads raw bytes only (drops `views()`, so UTF-16, gzip, JSON-escape and percent views are gone) | 7 passed |
   | `MACHINE_SID_RE` without `re.IGNORECASE` | 7 passed |
   | `MACHINE_SID_RE` without the trailing `(?![0-9])` | 7 passed |
   | tree-mode `main()`: SID dropped from the opaque-binary skip (`scrub_public_identifiers.py:486`) | 7 passed |
   | tree-mode `main()`: SID dropped from the residual check (`scrub_public_identifiers.py:496`) | 7 passed |
   | `run_dir` rewrite without `sid_scope=True` | 1 failed |
   | `run_dir` check without `find_sid_hits` | 1 failed |
   | `check()` without the SID line | 2 failed |
   The module docstring of the test and `find_sid_hits`'s docstring ("JSON escapes, percent, UTF-16, gzip") claim more than any
   test reaches. A positive assertion per encoding (lock fires before the rewrite, plain/lowercase/UTF-16 LE+BE/gzip/JSON-escaped),
   driven through `check()` and `--dir --check`, is the missing discriminating split.

2. **HIGH (blocker): `--dir` passes a folder that still names an account SID.** `scripts/scrub_public_identifiers.py:386-425`.
   `--dir` is documented as "every file in it is in scope for every rule", and it is the mode a raw-record bundle goes through
   (`PERFORMANCE_LOG.md:53`: raw records stay outside the repository and publish only through the sanitised bundle). Three shapes
   exit 0 under `--dir --check` with the SID still present (made-up SID, scratch folders):
   - SID in a file or folder NAME (`<SID>/ntuser.txt`, `acl-<SID>.json`): exit 0, 0 findings. `name_in_path` checks host and user
     only. Windows names folders and registry keys by SID (`$Recycle.Bin\<SID>`, `HKU\<SID>_Classes`).
   - a gzip member followed by non-gzip trailing bytes: `scrub_bytes` returns `unreadable: 1`, `run_dir` discards that count, the
     lock cannot decompress it either, exit 0. The comment at line 176 ("reported, never silently kept") is false for `--dir`.
   - a `.zip` (or any compressed container): opaque binary, the lock sees no plaintext, exit 0.
   Incidence in `run-20261016-1`: 0 of each (22 files: .json, .log, .py). The finding costs a published SID the first time a run
   emits one of these shapes; nothing complains when it happens.

3. **MEDIUM: `SID_SCOPE` covers zero tracked files.** `scripts/scrub_public_identifiers.py:70-74`. Neither
   `docs/research/mxc-proxy-egress` nor `docs/performance/mxc_proxy_egress` exists, and no document names either as a destination.
   The tracked MXC performance record is `docs/performance/mxc_proxy_egress_2026-10-15.json`, which `path_in_scope` reports
   **outside** the scope (entry is matched as a directory, not a prefix); the earlier MXC raw runs are tracked under
   `docs/research/windows-containment-comparison-2026-10/mxc-1406-probe/raw/`, also outside. The tree-mode rule, its log column
   and its `check()` line are therefore inert on the current tree; "machine-SID occurrences 0 (SID_SCOPE only)" in a scrub log would
   read as a measurement of nothing. Outside the scope the only guard is `tests/security/test_no_machine_sid_domain_in_tree.py`,
   which by its own HONEST LIMIT cannot read UTF-16: reproduced, a UTF-16 file carrying this machine's real SID scores 0 hits in
   that lock's `count_hits`, while the UTF-8 form scores 4, and the scrub's `check()` does not look outside `SID_SCOPE`. Incidence
   now: 26 tracked UTF-16/gzip files, 0 carry any `S-1-5-21-<digits>` SID.

4. **MEDIUM: the rewrite reads raw bytes while the lock reads decoded views, so ordinary shapes fail `--check` and cannot be
   cleared by the scrub.** `scripts/identity_lock.py:102` (lookbehind `(?<![A-Za-z0-9])`). A SID at the start of a line inside a
   JSON string is written `\nS-1-5-21-...` or `\r\nS-1-5-21-...`; the `n` blocks the rewrite, the unescaped view triggers the lock.
   Reproduced with `json.dumps({"stdout": "User Name SID\r\n<SID>"})`: rewrite count 0, lock before and after True. Same for `\t`,
   ANSI colour codes (`\x1b[32m<SID>`), percent-encoded `%5C<SID>`, `S-1-5-21-...` and `&#83;-1-5-21-...`. Fails closed (no
   leak), but each costs a blocked publish and a hand edit of a raw evidence record. Incidence in `run-20261016-1`: 0 (every SID
   there is preceded by `"`). Console-capture fields of the shape `stdout` are the likely first carrier.

5. **LOW: `--dir` rewrites evidence files with no record.** `scripts/scrub_public_identifiers.py:409-413`. Tree mode logs every
   rewritten file with before/after hashes; `--dir` rewrote 19 of 22 run files in place and printed only a count. Nothing ties the
   published bundle back to the pre-scrub records.

6. **LOW (hypothesis, not run): a SID glued after a letter is neither rewritten nor flagged** (`userS-1-5-21-...`: lock False,
   rewrite 0, `--dir --check` exit 0). Contrived; no producer of that shape was found.

## Attacked and could not break

- Real run folder (scratch copy): clean after `--dir`, verified by an independent scanner; `--dir --check` exit 1 before, 0 after.
- Plain, lowercase `s-1-5-21`, UTF-16 LE with BOM, LE and BE without BOM, gzip, gzip with trailing NULs, SDDL strings
  (`O:`, `G:...-513`, ACE trustee), `HKU\<SID>_Classes`, `_<SID>`, digit glued after the rid, Python `\x5c` prefix: all rewritten,
  lock silent afterwards, `--dir --check` 1 then 0.
- Generic SIDs (`S-1-5-32-544`, `S-1-16-*`, `S-1-5-18`, `S-1-5-114`, `S-1-15-2-*` AppContainer) untouched by rewrite and lock.
- The rid: only 1001 in the run; kept rids identify the account's role, not the machine. No finding.
- Opaque binary with a plain SID inside: `--dir` reports it and exits 1 (fails closed).
- Existing locks: the branch touches no baseline file; `test_no_host_identity_in_tree.py` and
  `test_no_machine_sid_domain_in_tree.py` pass unchanged. `scripts/hf_publish.py` preflight independently refuses a machine SID
  (raw text, `\d+` sub-authorities), so the placeholder passes it and a real SID does not.
- Toggle test (`test_removing_the_sid_rule_blinds_the_probe_and_the_rewrite`): does fail with the rule engaged and passes with it
  replaced; it covers the regex, not the encodings (finding 1).

## Not verified

- The evidence-repo push procedure: no script or runbook on this branch wires `--dir` into it, so whether the bundle step runs
  `--dir` at all was not observable here.

## What was run (hash `47ef9daa`, LOCALAPPDATA redirected to the reviewer's scratchpad)

- `pytest tests/security/test_machine_sid_scrub.py tests/security/test_no_host_identity_in_tree.py tests/security/test_no_machine_sid_domain_in_tree.py`: 61 passed in 235.51 s.
- `scrub_public_identifiers.py --dir <scratch copy> --check` / `--dir` / `--check`: exit 1 (19 findings), 0 (19 rewritten), 0.
- Encoding matrix (24 shapes) through `scrub_bytes`, `find_sid_hits` and `main(["--dir", ...])`; mutation runs of the 7-test file in a scratch copy.

## Merge read

Block on F1 (the lock certifies encodings it does not test) and F2 (`--dir`, the operative publish path, passes SIDs in names and
in compressed containers while claiming every rule on every file). F3 should be settled in the same change: either point
`SID_SCOPE` at the paths MXC evidence is actually tracked under, or state that the tree rule is for a future layout and lock that
the scope exists. F4-F6 do not block: they fail closed or have no producer yet.
