# Adversarial review: fix/scrub-account-sids (#1793)

Reviewed at `ea657719` (commits `602d414d`, `5a4b7f35`, `ea657719` off main `b95eb780`). The reviewer did not write this code
and changed nothing in it. Every result below was produced by running the real entry points (`identity_lock.find_account_sid_hits`,
`scrub_public_identifiers.check`, `scrub_public_identifiers.main` in tree and `--dir` mode, `hf_publish.preflight`) with
LOCALAPPDATA redirected to a scratch folder. No identifier value is written in this file.

**VERDICT: FAIL** on finding 1. The scrub, the lock and the 73-file rewrite are correct for every ordinary shape tried; the block is
a fixture that carries part of the operator's real account SID into a file the forward scrub will publish.

## Findings, most severe first

### 1. HIGH: the test fixture carries four of the operator's real Microsoft-account sub-authorities

- **Where:** `tests/security/test_account_sid_scrub.py:33` (`MSA_SID`), present in both `602d414d` and `ea657719`.
- **What is wrong:** sub-authorities 2 to 5 of `MSA_SID` (two 5-digit and two 10-digit values, in order) are the operator's own,
  copied from the research records; only the first sub-authority (`SUBAUTH`) and the last five are invented. The docstring at
  line 7 says "The SIDs below are made up".
- **Failure scenario:** the branch merges and the forward scrub is pushed to the public mirror. The test file goes with it, carrying
  a run of the identifier this arc exists to remove from the forward tree. No lock can see it: the prefix is assembled at run time
  (the purpose of `ea657719`) and the digits alone are not a SID shape.
- **Reproduced:** yes. Read the operator's account SID from the live token (`whoami /groups`, the one `S-1-11-96-*` entry, 10
  sub-authorities after `96`), then searched every tracked file for each sub-authority of 7+ digits and for the digit tail. The
  only hit in the tree is this test file; with 4+ digits, line 33 matches sub-authorities 2, 3, 4 and 5 and nothing else.
- **Incidence:** 1 file of 4136 tracked. No other tracked file carries the tail, a long sub-authority, the binary SID, its hex
  (plain or `hex:` comma form) or its base64.
- **Fix belongs to the author:** replace the four values with invented ones, and correct nothing else in the docstring.

### 2. MEDIUM: the Hugging Face preflight's file-name refusal and its name redaction are not locked

- **Where:** `scripts/hf_publish.py:520` (`hidden = ... or _il.find_account_sid_hits(...)`) and `:540` (the name hit).
- **What is wrong:** the code is correct, but no test fails when either line is removed; `test_hf_preflight_refuses_an_account_sid_and_passes_the_placeholder` plants the SID in content only. The test module's docstring (lines 3-4) claims the preflight fails while one remains, a file NAME included.
- **Failure scenario:** a later edit drops the name check and `preflight` returns clean for a dataset whose file is named after the
  operator's SID, so it is uploaded to a public dataset (irreversible). Dropping the redaction echoes the SID in FAIL lines.
- **Reproduced:** yes, by mutation. File `run-<SID>.json` with clean content: branch returns 1 problem, shown as `file #0`. Mutant
  M23 (name check removed): 0 problems, preflight clean. Mutant M24 (redaction removed): 1 problem, SID printed in the line.
  Both mutants leave the 45 tests of the account-SID module green.

### 3. MEDIUM: tree-mode `--check` and the gate scan do not fail closed on archives outside `SID_SCOPE`

- **Where:** `scripts/scrub_public_identifiers.py:466` (`container_problems` runs only `if il.path_in_scope(r, SID_SCOPE)`);
  `tests/security/test_no_host_identity_in_tree.py` `scan()` reads raw bytes only.
- **What is wrong:** the account rule is whole-tree, but the fail-closed archive handling it relies on in `--dir` mode is
  `SID_SCOPE`-only in tree mode. The claim "`--check` fails on any remaining occurrence, across every tracked file" overclaims.
- **Failure scenario:** a tracked `.zip` (deflated or stored), `.bz2`, `.xz` or a gzip nested five deep carrying an account SID,
  anywhere outside `SID_SCOPE`, passes `--check` and the gate tree scan. `--dir` mode exits 1 on all of them; `hf_publish`
  refuses all of them (suffix allowlist, nesting-depth refusal).
- **Reproduced:** yes. Battery output, column check(tree, outside scope): `zip_deflate False`, `zip_stored False`, `bz2 False`,
  `xz False`, `gzip_x5 False`; `--dir --check` exit 1 for each. (A stored zip member is also missed by the lock itself: the
  member's file name ends in a letter, which glues to the SID under the `(?<![A-Za-z0-9])` boundary.)
- **Incidence:** zero. No tracked `.zip`, `.bz2`, `.xz`, `.7z` or `.tar`; 26 tracked `.gz` files, all readable by the lock.
  Zero incidence is a reason to be calm, not a reason the claim holds.

### 4. MEDIUM-LOW: four arms of the lock survive their removal

Mutation run: 27 mutants against `tests/security/test_account_sid_scrub.py`; 18 killed, 9 survived. The survivors that open a real gap:

| mutant | removed | gap it opens (reproduced where marked) |
|---|---|---|
| M2 | the `12-1` (Entra ID) arm of `ACCOUNT_SID_RE` | an Entra ID SID in a shape only the views see (fully percent-encoded): branch `True`, mutant `False` (reproduced) |
| M9 | `re.IGNORECASE` on `ACCOUNT_SID_RE` | a lowercase SID in a shape only the views see (percent-encoded lowercase) |
| M10 | gzip recursion in `account_sid_rewrite_would_change` | inside a gzip, a shape the rewrite reads and the views do not (a percent-escape decoding to a letter before `S`): the lock becomes narrower than the rewrite, which the docstring of `find_account_sid_hits` says it never is |
| M18 | `or il.find_account_sid_hits(new)` in tree-mode `main()` residual | a tracked file left with a percent-encoded account SID: branch scrub exits 1 naming it; mutant exits 0, "rewrote 0 file(s)" (reproduced). `--check` still exits 1, so a second lock holds |

Each arm is correct on the branch; each is unlocked. `test_toggle_the_views_arm_and_the_rewrite_arm_each_carry_the_lock` does
kill the whole-arm toggles (M5, M6), but the views-only shapes in it are not run against Entra ID or lowercase input, so the
regex's own arms are certified by the rewrite arm standing next to them.

Survivors judged equivalent or near-dead: M16 (zip member NAME arm; the archive is reported and `--dir` exits 1 regardless, only
the message changes), M20 (the added `or il.find_account_sid_hits(data)` on the unreadable path almost never fires, because an
unreadable gzip yields no view carrying the SID), M23 and M24 (finding 2).

### 5. LOW: shapes no check sees, beyond the documented limits

Seen by nothing (lock `False`, tree `--check` clean, `--dir --check` exit 0): the binary SID (`01 0b ...` structure) and its
registry-export form (`hex:01,..`), a letter or digit glued before `S` (`userS-1-11-96-...`), the digit tail without its prefix,
plus the shapes the machine-SID limits already name (split by a line break or a JSON `\n`, U+2011 / en dash / zero-width space,
double percent-encoding, base64, fullwidth `S`, HTML hex entity without its semicolon). The binary/hex form and the glued letter
are not named in rule 5's limits in `scrub_public_identifiers.py` or in the `hf_publish.py` docstring.
**Incidence:** zero for the operator's SID in every one of these forms across all tracked files (plain, gzip and NUL-stripped
views searched).

## What I attacked and could not break

- **Every ordinary shape is caught** in all four places (lock, tree `check()` outside every scope, `--dir --check`, HF preflight),
  and `--dir` rewrites to clean: plain, lowercase, Entra ID, UTF-16 LE with BOM, UTF-16 BE without, UTF-32, gzip, gzip of UTF-16,
  JSON `\n` before the SID, a `_` or `*` before it (icacls form). All-`\u` JSON escape, `-` hyphens, full and hyphen-only
  percent-encoding and both HTML entities are seen; `--dir` leaves them and exits 1 for a hand edit, as documented.
- **No over-matching** on 20 lookalikes: `S-1-5-21-*` (machine rewrite only), `S-1-15-2-*`, `S-1-16-8192`, `S-1-5-32-544`,
  `S-1-5-18`, `S-1-12-10-*`, `S-1-11-960-*`, `S-1-112-1-*`, `S-1-11-95-*`, `S-1-12-2-*`, bare `S-1-12-1` / `S-1-11-96`,
  `ABS-1-12-1-5`, `version S-1-12-1.2`, and the three placeholders. The rewrite is idempotent on all of them and the lock is
  silent after every rewrite.
- **The 73-file rewrite is exactly the rule's output:** for each file, `rewrite_account_sids(content at b95eb780)` equals the content
  at `ea657719` byte for byte. Total 334 replacements, matching the log; one distinct account SID in the old content, the
  operator's; every file parses as JSON; line counts unchanged; every changed line is the rewrite of its old line. The
  74th file in `5a4b7f35` is the scrub log, which carries no identifier.
- **Tree state:** `scripts/scrub_public_identifiers.py --check --repo .` reports 0 findings in 4136 tracked files.
- **Lock never narrower than the rewrite** holds on the branch by construction (`find_account_sid_hits` ORs the rewrite predicate);
  only M10 shows the property is not locked.

## Merge read

- **Block on finding 1** before the merge or the public push: an author-side edit of four numbers, then re-run the account-SID module.
- **Should land with the merge, not block it:** finding 2 (two tests: a SID-named file is refused and shown as `file #n`).
  The publication path it guards is irreversible.
- **Do not block on:** findings 3 to 5 (zero incidence, a second lock holds in finding 4's M18 case); they need a disposition
  row each under the deferral discipline, with an observable `blocked-by:` predicate or a fix.
- **Required before merge regardless:** land with `git merge --no-ff` (the branch touches `scripts/scrub_public_identifiers.py`
  and `scripts/identity_lock.py`, both ratchet files under identity.md). `scripts/identity_user_baseline.json` is untouched, so
  no baseline change is needed. The standing gate on the branch and again on merged main; I did not run it. A disposition
  record for this review.

## What I ran, at `ea657719`

- Identity suites, LOCALAPPDATA redirected: `tests/integration/test_build_nep0005_dataset.py`, `test_hf_publish.py`,
  `test_phase1_review_fixes.py`, `test_phase1_review_round2.py`, `test_serial_call_sites.py`, `tests/security/test_account_sid_scrub.py`,
  `test_gate_runtime_dataset_publishable.py`, `test_machine_sid_scrub.py`, `test_no_host_identity_in_tree.py` (includes the gate's
  identity tree scan), `test_volume_serial_lock.py`, `test_no_machine_sid_domain_in_tree.py`: **867 passed, 0 failed, 0 skipped**, 435 s.
- `python scripts/scrub_public_identifiers.py --check --repo .`: 0 findings in 4136 tracked files.
- A 36-shape battery through the four entry points, the 20-lookalike over-match and idempotence probe, the 73-file byte comparison,
  the tracked-tree search for the operator's SID in other forms, and the 27-mutant run (on a scratch copy of `scripts/` and the two
  test modules; the branch was not modified).
- Not run: the standing gate.

---

# Round 2: re-review at `9620b00c` (fixes `6474a81f`, disposition `9620b00c`)

**VERDICT: FAIL.** Every round-1 finding is addressed, and the fixes work: no live sub-authority remains in the tree, archives are
opened tree-wide, and the six named mutants die. The block is the new live-token lock, which puts two false positives into the
standing gate. No identifier value is written below.

## Round-2 findings, most severe first

### R2-1. HIGH: the live-token lock fails the gate under any account that has no Microsoft-account or Entra ID SID

- **Where:** `tests/security/test_account_sid_scrub.py:419` (`assert parts, "no Microsoft-account or Entra ID SID in the current
  token: the lock cannot see its subject"`), and the same assertion in the toggle test at `:429`.
- **What is wrong:** the test's subject is the operator's cloud account, but it reads that account from the token of whoever runs
  the gate. A local account's token carries no `S-1-11-96-*` or `S-1-12-1-*` group, so the assertion fires for every such account.
- **Failure scenario:** the coder fleet runs as the local standard account `blarai-coder` (`containment = restricted_account`,
  agentic-setup `docs/fused-leg-operator-uses.md`). The builder briefs tell it to run the standing gate
  (`docs/blarai-builder-brief-dispatch-harness.md:89`). Every coder gate run goes red on 2 tests, for every ticket. The same happens
  on a rebuilt machine signed in with a local account. The red result is "cannot see its subject": it blames the environment, not
  the change, and invites a skip.
- **Reproduced:** in part. I called `test_no_sub_authority_of_the_live_account_sid_is_in_any_tracked_file` with `whoami /groups`
  output for a local account substituted (Everyone, BUILTIN\Users, Medium Mandatory Level). Result: AssertionError, "no
  Microsoft-account or Entra ID SID in the current token". I did not run the gate as `blarai-coder`. The premise that a local
  account's token has no Microsoft-account group is standard Windows behaviour; I have not observed it on this machine.
- **Contrast:** the volume-serial lock also fails when it cannot read its subject, but every account on the machine can read the
  serials. Only the operator's sessions can read this subject.

### R2-2. HIGH: the 5-digit sub-authorities make the lock fire on ordinary process IDs and port numbers, and its remedy text says to falsify the record

- **Where:** `tests/security/test_account_sid_scrub.py:412-414` (`_subauthority_hits` treats every sub-authority as a whole digit
  token, short ones included) and the failure message at `:423` ("replace it with an invented number").
- **What is wrong:** two of the account's ten sub-authorities are 5-digit numbers. Both fall in the range Windows uses for process
  IDs, and one is also in the ephemeral TCP port range. As a bare 5-digit token, either value is indistinguishable from a PID, a
  port, a byte count or a duration.
- **Failure scenario:** a containment run, gate log or probe record captures a process whose PID (or a connection whose local port)
  equals one of the two values. The standing gate goes red. The message tells the author to replace the number with an invented
  one, which in a measurement record means altering evidence.
- **Reproduced:** yes. `{"process": {"name": "python.exe", "pid": <5-digit sub-authority>}}` in `run.json`, and
  `TCP 127.0.0.1:<the other> -> 127.0.0.1:8099 ESTABLISHED` in `probe.log`: `_subauthority_hits` returns both files.
- **Incidence:** zero today; none of the ten values is in the tree after the scrub. Base rate measured on the tree at `9620b00c`,
  every view of every tracked file: 11302 distinct 5-digit tokens (12.6% of all 5-digit values), 17% of the multiples of 4 below
  65536, 8.6% of the ephemeral port range. The tree already holds about one in six PID-shaped values, so a collision on one of the
  two values within roughly the next tree's worth of records is likely, not hypothetical. The eight 10-digit values carry no such
  risk (883 distinct 10-digit tokens in the tree).

### R2-3. MEDIUM: archive member NAMES are not locked in tree mode, and the disposition says they are

- **Where:** `scripts/identity_lock.py` `_archive_members_problems` (the member-name arm). Disposition row `F4-M16-zip-member-name-arm`.
- **What is wrong:** with the member-name arm removed (mutant C5), all 74 module tests still pass. Yet the REJECTED row for M16 argues
  "the tree-mode path now reads member names through account_sid_container_problems, which F3's tests cover". F3's tests plant
  the SID in member bodies only.
- **Reproduced:** branch: a zip whose member is named after the SID with a clean body gives `problems=True`, and so does the same
  case in a tar. Under C5 both give `False`, so the tree check, the gate scan and the tree scrub pass them.

### R2-4. LOW-MEDIUM: reader arms that mask each other, and unlocked bounds

From the round-2 mutant run (below):
- **Mutually masking:** magic detection (C1 bzip2, C2 xz, C3 tar) and the suffix fallback (C10) each survive alone, because
  every test container carries both the magic and the matching suffix.
  - Under C1, a bzip2 stream named `run.dat` reads as clean (reproduced; the branch catches it).
  - No test plants a magic-only or a suffix-only container.
- **Unlocked bounds and paths:**
  - C14 (stream size bound) and C16 (zip size bound): the 256 MiB bound the disposition cites is not tested.
  - C15: with the `SID_SCOPE` filter changed to drop every message, nothing fails, because no test plants an account SID inside
    `SID_SCOPE` through `check()`. The branch is correct there: a bzip2 in `SID_SCOPE` reports the SID.
  - C9: the UTF-16 problem arm is not tested.
- **Equivalent:** C11 (the encrypted-member check). An encrypted member makes `z.read` raise `RuntimeError`, which is already
  reported as unreadable.

### R2-5. LOW: a gzip with trailing zero padding is now refused tree-wide

`_decompress_all` treats trailing NULs after the last gzip member as a new stream that cannot be read. Python's own `gzip.decompress`
and `GzipFile` accept that padding, and `--dir` mode passes the same file. A legitimate padded `.gz` therefore fails `--check` and the
gate (reproduced: `clean_gz_trailing_zeros.gz` gives an "unreadable" finding in tree check and gate scan; `--dir --check` exit 0).
Zero incidence: every tracked `.gz` passes the tree check. This is the fail-closed direction, so it does not block.

## Round-1 items re-verified

| round-1 finding | round-2 result |
|---|---|
| 1 real sub-authorities in the fixture | FIXED. Live-token search over all 4138 tracked files (plain, gzip, NUL-stripped views; whole-token sub-authorities, binary SID, hex, base64): **0 hits**. Commit messages `b95eb780..HEAD`: 0. The `602d414d` copy of the test file still carries them (history; disposition A-1). |
| 2 hf name refusal and redaction | FIXED. M23 and M24 each kill 2 tests. |
| 3 archives outside `SID_SCOPE` | FIXED. Outside every scope, all 15 SID-bearing containers fire in tree `check()`, the gate scan and `--dir`: deflated and stored zip (glued name included), member name, zip in zip, gzip of zip, tar, tar.gz, tar.bz2, xz, bz2, multi-member gzip (SID in the second member), gzip x15, UTF-16 member, tar member name. Gzip x17 and 7z fail closed as unreadable. Clean twins (zip, tar.gz, gzip x15, multi-member gzip, docx, empty `.gz`, random bytes) give no finding, except R2-5. Inside `SID_SCOPE`: gzip x17, 7z, a truncated gzip, bzip2 and gzip x6 all give a finding. |
| 4 mutants M2, M9, M10, M18 | FIXED. All killed (3, 2, 3 and 3 failures). |
| 5 unstated limits | FIXED. Rule 5 and the `hf_publish.py` docstring now name the binary and `hex:` forms, the glued SID and the bare digits. |

## Round-2 mutant run

44 mutants (the 27 from round 1, re-anchored to the new code, plus 16 on the container reader and 1 on the token scan) against
`tests/security/test_account_sid_scrub.py -k "not any_tracked_file"`, on a scratch copy without git. The deselected test reads
the real tree; I ran it separately on the branch. **33 killed, 11 survived:**
- M16, C11: equivalent.
- C1, C2, C3, C10: mutually masking (R2-4).
- C5: R2-3.
- C9, C14, C15, C16: unlocked (R2-4).

## Disposition record

`scripts/verify_disposition.py docs/reviews/scrub-account-sids-disposition-2026-10-17.md`: **PASS, 11 ok / 0 unjustified of 11**.
The verifier checks form only. On substance:
- the `F4-M16` REJECTED argument rests on a coverage claim that C5 disproves (R2-3);
- `A-1` names an observable predicate (a decision on #1793) and is a real choice for the operator.

## Merge read, round 2

- **Block on R2-1 and R2-2.** Both put false failures into the standing gate, the first on every non-operator account. One way
  to fix both: pin digests of the account's long sub-authorities (the host-name approach) instead of reading the live token, and
  drop the 5-digit values. That design is the author's to choose.
- **Fix with the merge:** R2-3 (one test, member name only), and correct the `F4-M16` disposition row.
- **Do not block on:** R2-4 and R2-5; each needs a disposition row.
- **Unchanged from round 1:** `git merge --no-ff`; baseline file untouched; the standing gate is the lead's.

## What I ran, at `9620b00c`

- Identity suites (the same 11 files), LOCALAPPDATA redirected: **897 passed, 0 failed, 0 skipped**, 380 s.
- The live-token sub-authority search over every tracked file, and over the branch's commit messages.
- The 25-case archive battery (tree `check()`, gate `scan()`, `--dir --check`) outside every scope, plus 5 cases inside `SID_SCOPE`.
- The 44-mutant run, and targeted probes on the C1 and C5 survivors.
- The PID and port false-positive repro, and the local-account token repro.
- Base-rate counts of 5- and 10-digit tokens over the tree.
- `scripts/verify_disposition.py` on the disposition record.
- Not run: the standing gate, by instruction.

---

# Round 3: re-review at `8c68d3ab` (fixes `fe25afc8`, disposition `8c68d3ab`)

**VERDICT: PASS.** R2-1 to R2-5 are fixed as the lead decided on #1793 (c4436), and each fix is locked by a test that fails when
it is removed. Two documentation items below should land in the squashed branch; neither blocks. No identifier value is written below.

## R2 items re-verified by running

| item | result at `8c68d3ab` |
|---|---|
| R2-1 local-account token | FIXED. Under the operator's real token, `test_no_long_sub_authority_of_the_live_account_sid_is_in_any_tracked_file` RUNS and passes (reads 8 long sub-authorities, scans the tree). With a local account's `whoami /groups` output it raises `pytest.skip` with "no account SID in this token" (`test_under_a_local_account_the_lock_skips_with_its_reason` passes). Mutants: skip turned into a silent return (R1) and the no-subject guard removed (R3) each fail 1 test. |
| R2-2 PID and port collisions | FIXED. With the real token, the round-2 repro (a `run.json` carrying a 5-digit sub-authority as a PID, a `probe.log` carrying the other as a port) now returns no hit; a file carrying a long sub-authority still fires. The cutoff set back to 5 (R2) fails 2 tests. The failure text says to scrub the identifier, or to stop and report a coincidental number in evidence, never to edit the record. The 8 long values are 10-digit; a collision needs an exact 10-digit match (883 distinct 10-digit tokens in the tree). Three of them fall in the Unix-seconds range for 2015-2040, so a timestamp would have to equal one to the second: noted, not a finding. |
| R2-3 member names | FIXED. C5 now fails 2 tests (zip and tar member named after the SID, through `check()`, the gate scan and the tree scrub). The `F4-M16` row now confines its equivalence argument to `--dir` mode and records the round-1 overclaim. |
| R2-4 masking arms and bounds | FIXED. C1, C2, C3, C10, C9, C14, C15 and C16 each fail 1 test. C11 REJECTED as equivalent: accepted (an encrypted member raises `RuntimeError`, already mapped to unreadable). |
| R2-5 gzip zero padding | FIXED. A clean padded gzip reads clean, a SID-bearing padded gzip reports the SID, and junk after the padding still fails closed. Removing the padding break (C17) fails 1 test. |

## Live-token search

All 10 sub-authorities (the two 5-digit ones included), the binary SID, its hex and base64, searched in plain, gzip and
NUL-stripped views of all 4138 tracked files and in the branch's commit messages: **0 hits**.

## Mutant run

49 mutants (round 2's 44 plus R1, R2, R3, C17 and C17b, accepting zero padding for every stream kind) against
`tests/security/test_account_sid_scrub.py -k "not any_tracked_file"` on a scratch copy. **46 killed, 3 survived:**
- M16 and C11: equivalent, as argued in the disposition.
- C17b: accepting trailing zeros after a bzip2 or xz stream as well. The content is still read and checked either way, so this
  cannot hide a SID. Equivalent in effect.

## Disposition record

`scripts/verify_disposition.py`: **PASS, 20 ok / 0 unjustified of 20**. On substance, two rows lag the code (finding R3-2).
A-1 now names the lead's decision: a fresh branch off main carrying one squashed commit, landed with `--no-ff`; this branch
stays as the audit record.

## Round-3 findings (none blocking)

### R3-1. LOW-MEDIUM: the new local-account skip is not named in TEST_GOVERNANCE

- **Where:** `docs/TEST_GOVERNANCE.md` §1, which names the gate's documented skips (3 symlink skips when non-elevated, 7
  port-5001 skips with the app up). This branch does not touch it.
- **What is wrong:** under `blarai-coder` or any local account, the standing gate now reads 1 skip more. TEST_GOVERNANCE calls an
  unexplained skip a defect. The skip's reason is visible in `-rs` output, but a coder or a session comparing against the bar
  has no record that this delta is expected.
- **Fix:** one line naming the delta, in the squashed branch.

### R3-2. LOW: two disposition rows describe the round-1 lock

- **Where:** row `F1` names `test_no_sub_authority_of_the_live_account_sid_is_in_any_tracked_file`, which was renamed in
  `fe25afc8`, and says the lock "fails on any sub-authority". Row `F5` says the bare digits are "held for the live account by the
  new token lock".
- **What is wrong:** since `fe25afc8` the lock reads only sub-authorities of 8 digits or more, and only when the token carries an
  account SID.
- **Fix:** the `R2-1` and `R2-2` rows state the current behaviour, so a pointer from F1 and F5 to them would close this.

## Merge read, round 3

- **PASS** for the code and its locks at `8c68d3ab`.
- **Before landing:**
  - the squashed branch (A-1) must carry this review and the disposition record as well as the code;
  - fold in R3-1 and R3-2;
  - land with `git merge --no-ff`;
  - run the standing gate on the squashed branch and again on merged main.
- `scripts/identity_user_baseline.json` is untouched.

## What I ran, at `8c68d3ab`

- Identity suites (the same 11 files), LOCALAPPDATA redirected: **909 passed, 0 failed, 0 skipped**, 312 s. This ran under the
  operator's token, so the live-token lock ran rather than skipped.
- The live-token lock and the local-account skip test, run by name; the R2-2 collision repro with the real token values.
- The live-token search over every tracked file and over the branch's commit messages.
- The 49-mutant run.
- `scripts/verify_disposition.py` on the disposition record.
- Not run: the standing gate, by instruction.
