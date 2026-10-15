# Adversarial review: #1765 public-identifier scrub and lock (commit 903b6063)

VERDICT: FAIL

Reviewed commit 903b6063 on `feat/1765-scrub-public-identifiers`; parent 3e8fa63e. The real checkout's tip during the runs was f1c9cc29. The three commits after 903b6063 touch documents only: `scripts/`, `tests/` and `.claude/` are identical between 903b6063 and f1c9cc29. Every rewrite and mutation ran in scratch clones at 903b6063 and 3e8fa63e. Nothing in the real checkout was modified apart from this file. The two identifiers are written here as "the host name" and "the operator name".

## Defects, most severe first

### 1. HIGH. The lock file puts the host name into the tracked tree, and no control sees it

- **Where:** `tests/security/test_no_host_identity_in_tree.py:28-29`, the HONEST LIMIT example.
- **What is wrong:** the example of a name "glued to other word characters" is the real host name in lower case with one letter appended. That glue is the blind spot the sentence describes, so every control passes it.
- **Cost:** once merged, the next public snapshot publishes the host name inside the file meant to keep it out. The "BlarAI Public Snapshot" task next runs 2026-10-19 05:25 local. The journal fragment, DEC-21 and the NEP-0005 evidence write-up (unposted) all state the opposite.
- **Reproduced:**

| probe | result |
|---|---|
| any-case substring search of the host name over `git ls-files` (tip) | 1 file, this one. The parent had 21. |
| `pytest tests/security/test_no_host_identity_in_tree.py` | `10 passed` |
| `python scripts/scrub_public_identifiers.py --check` | `0 finding(s) in 3992 tracked files` |
| the publisher's own match, `git grep -l -E <host pattern> <tip tree>`, using the pattern from the private leak-gate file | 0 files (see finding 4) |

- **Incidence:** 1 file.

### 2. HIGH. Eleven tracked gzip gate logs carry the host name, and the refactored tests keep producing it

- **Where:** `docs/performance/gate_runtime_2026-10-07/`. Eleven of its 26 `.log.gz` files carry the host name 6 to 10 times each. The source is pytest test IDs from `tests/integration/test_hf_publish.py:336`, `:392` and `tests/integration/test_phase1_review_round2.py:351`.
- **What is wrong:** the lock docstring says the host check covers "every tracked file" (`:13`) and that "binary tracked files ... are scanned the same way" (`:25-26`). Compressed bytes never contain the name, so the lock, `--check` and the publisher's `git grep` all miss it.
- **The scrub log hides it:** the scrub's binary-skip warning matches raw bytes, so it stays silent. The rewrite on the parent printed no warning, and the committed log has no "NOT rewritten" section. That absence reads as "no binary file carries an identifier".
- **The leak path is still open.** The refactor moved the literal out of the test source, but pytest copies parametrize values into test IDs. Collection now yields 3 IDs that carry the live host name and 2 that carry the operator name. Every banked verbose gate log will carry them, which is how these eleven logs got the name.
- **Already public:** the last published snapshot (`refs/public-snapshots/main`, 2026-10-09) holds 11 plain files and these same 11 gzip files naming the host. This commit removes only the 11 plain ones.
- **Reproduced:**
  - A decompress-and-search over every tracked `.gz` file finds the host name in 11 and the operator name in 16.
  - `pytest --collect-only -q` on the two test files shows the IDs above.
  - A scratch mutant, a tracked `.log.gz` containing `PASSED test[run on <host>]`, passes both the lock and `--check`.
- **Incidence:** 11 files, measured.

### 3. HIGH. The credential-store access table and the operator name survive in the study's own report and its performance copy

- **The final report:** `docs/research/windows-containment-comparison-2026-10-10.md:161-166`. Six rows, each a full credential-store path containing the operator name, with per-identity access masks (`RWDP`, `R---`). The file names the operator 12 times.
- **The performance copy:** `docs/performance/containment_probe_2026-10-10/summary-phase1.md:44-48`. Five credential-store paths with the operator name, each marked `allowed`. This file is the unscrubbed twin of the scrubbed `docs/research/windows-containment-comparison-2026-10/summary-phase1.md`. A line diff of the two differs only in those five rows, so the pair decodes `<credential-store-2>` to `<credential-store-6>` line by line.
- **Also beside credential-store content:**
  - `tools/probes/containment_arms/summarise_phase2.py:72-73` holds an unused list of five credential-store paths with the operator name.
  - `docs/reviews/code-review-1684-1685-pa-hardening-2026-10-05.md:86` holds the DEK keystore path with the operator name.
- **Why the scope misses them:** `EVIDENCE_DIRS` names two directories. `in_evidence` excludes the sibling report `...-2026-10-10.md` because of the trailing slash. The exposure the commit exists to remove is the operator's credential stores with their access lists. That exposure is still in the tree.
- **Under the brief's own rule:** an operator-name hit outside the two directories counts as a defect when it sits beside credential-store content. These four files do.
- **Reproduced:** a residue sweep over `git ls-files` for every full credential-store path with the operator name. The search covered single-backslash, JSON-escaped and forward-slash forms in any case.
  - Inside the two evidence directories it found 0 files.
  - Outside them it found 9 files. The four above carry credential-store content.
  - The other five name only the BlarAI data directory as a working path: `FIELD_NOTES.md`, `docs/security/DATA_MAP.md`, the RAM-headroom log and two JSON records.

### 4. HIGH. The publisher's leak gate, cited as the backstop, matches one capitalisation of the host name

- **Where:** the private pattern file `.blarai-fleet/leakgate-patterns.txt` in the operator's home directory, and `agentic-setup/scripts/publish-public-snapshot.ps1:102` (`git grep -l -E $rx $tree`, no `-i`).
- **What is wrong:** the host pattern is mixed case. It is neither the upper-case `COMPUTERNAME` form nor lower case, and `git grep -E` is case-sensitive. The journal fragment says this pattern means "the weekly snapshot refuses a tree that regresses even if the gate test is not run". The run below shows otherwise.
- **Reproduced, with the publisher's exact match:**

| tree | publisher pattern, as run | host name, any case |
|---|---|---|
| 3e8fa63e (parent) | 12 files | 21 files |
| f1c9cc29 (tip) | 0 files | 1 file (finding 1) |

- **Note:** this artifact sits outside the repository. It is in scope because the arc's prose relies on it as an independent lock.

### 5. MEDIUM-HIGH. The toggle test does not toggle the lock

- **Where:** `tests/security/test_no_host_identity_in_tree.py:138-150`.
  - `test_lock_sees_every_letter_case_and_boundary` calls `_scan_paths` (`:152`), a second implementation. The tree test calls `_scan` (`:86`).
  - Only host digests are planted. User-name detection, evidence scoping and the tree-level credential-row test have no toggle.
  - Nothing asserts that the evidence directories exist or that any file inside them was scanned.
- **Reproduced:** the test file was mutated inside a scratch clone at 903b6063.

| mutation | result |
|---|---|
| `_scan` returns `([], [])` | `10 passed` |
| `_in_evidence` returns `False` | `10 passed` |
| user digests never consulted in `_scan` | `10 passed` |
| evidence directory moved to `...-2026-10-archived`, operator name planted inside it | lock `10 passed`, `--check` `0 finding(s)` |

- **Cost:** the commit message says "toggle-tested". The journal fragment says "toggle-tested in every letter case and boundary form". Security-by-design principle 12 requires a toggle that fails when the lock is off. This one stays green with the scan deleted.

### 6. MEDIUM. The refactor made four privacy controls depend on the running account (regression against the parent)

- **Where:**
  - `scripts/hf_publish.py:53-55`, `DENY_STRINGS`
  - `scripts/scrub_community_export.py:45-46`
  - `scripts/verify_community_scrub.py:50-51` and `SENSITIVE_FAIL`
  - `scripts/build_phase1_dataset.py:109-110`
  - `scrub_public_identifiers.py --check`, which uses live names only
- **What is wrong:** each now reads the operator name from `USERNAME` or getpass. Under any other account they no longer protect this operator's name. Other accounts exist on this machine: the restricted coder account, and SYSTEM, whose name is the host name followed by `$`.
- **Reproduced, hf_publish preflight:** one text file reading `dataset run by <operator name> on the laptop`, with `USERNAME` varied.

| USERNAME | 3e8fa63e | 903b6063 |
|---|---|---|
| operator account | exit 1, refused | exit 1, refused |
| `blarai-coder` | exit 1, refused | exit 0, `preflight: CLEAN` |
| SYSTEM form (host name with `$`) | exit 1, refused | exit 0, `preflight: CLEAN` |

- **Reproduced, community scrub then verifier:** one JSON record with `measured by <operator name> on <host name>`.

| USERNAME | 3e8fa63e | 903b6063 |
|---|---|---|
| operator account | output clean, verifier 0 | output clean, verifier 0 |
| `blarai-coder` | output clean, verifier 0 | operator name still in the output, verifier exit 0 ("safe to publish") |

- **A comment made false:** `verify_community_scrub.py:49` says the patterns are "defined here independently of the scrub on purpose (two implementations that must agree)". On the identity axis both now read the same environment variable, so they agree on whatever the account says.
- **Why the tests miss it:** the updated tests read the names the same way the scripts do, so they pass under any account.
- **Incidence:** no current job runs these scripts under another account, so real-world firing is a hypothesis. The regression itself is reproduced.

### 7. MEDIUM. Placeholder numbers are reassigned on every run, so a second scrub reuses numbers for different stores

- **Where:** `scripts/scrub_public_identifiers.py:112` (`credential_map`). The docstring at `:15-16` claims "the mapping is the same on every run and across files".
- **Reproduced:** in a scratch clone at 903b6063, one new effective-access record with `kind: secret` rows for the SSH store and the AWS store was added, then the scrub was run.

| store | placeholder in the new record | placeholder in the existing records |
|---|---|---|
| SSH store | `<credential-store-2>` | `<credential-store-5>` |
| AWS store | `<credential-store-1>` | `<credential-store-1>` (same by coincidence of sort order) |
| Codex sandbox-secrets store | none | `<credential-store-2>` |

  `--check` afterwards: `0 finding(s)`.
- **Cost:** the new rule in `.claude/rules/performance.md` makes the scrub a step before every snapshot. Each new batch of evidence then silently takes numbers that collide with earlier ones. A cross-run comparison would compare two different stores under one label.

### 8. MEDIUM. Ordinary shapes that the lock and `--check` both miss

Fifteen mutants were planted one at a time as tracked files in a scratch clone at 903b6063. Fourteen carried an identifier and one was a clean control. Ten of the fourteen passed both controls.

| mutant | lock | `--check` |
|---|---|---|
| host, lower case, prose | FAIL | FAIL |
| host, upper case, UNC path | FAIL | FAIL |
| operator in `C:\Users\<name>\x`, evidence Markdown | FAIL | FAIL |
| operator JSON-escaped, evidence JSON | FAIL | FAIL |
| host after a JSON `\n` escape (whoami-style output) | pass | pass |
| operator after a JSON `\n` escape, evidence JSON | pass | pass |
| host after a JSON `\t` escape | pass | pass |
| host glued to `_trace` (file stem) | pass | pass |
| host in a percent-encoded UNC path (`%5C%5C`) | pass | pass |
| host inside a gzip log | pass | pass |
| host in UTF-16LE text | pass | pass |
| host in a tracked file NAME only | pass | pass |
| host followed by a digit | pass | pass |
| host after a `\x00` escape | pass | pass |
| clean control | pass | pass |

The HONEST LIMIT names punctuation splits, UTF-16 and word-character glue. It does not name JSON escape sequences, which are the ordinary form of multi-line command output in these records. It also does not name compressed files or file names. Current incidence is 0 for the JSON-escape, percent-encoding, underscore, file-name and UTF-16 shapes, and 11 for gzip (finding 2).

### 9. LOW-MEDIUM. The pinned digests are reversible at these name lengths

- **Operator name:** an exhaustive search over 4- and 5-letter lower-case strings reversed the pinned digest in 2.8 s of single-threaded Python.
- **Host name:** a wordlist search with a three-digit suffix would likely reverse it the same way. This is a hypothesis; it was not run.
- **The claim at `:19`:** "Names are never written here" holds for the bytes but not for the information. The exposure this adds for the operator name is nil, because the name appears in about 634 tracked paths. For the host name, the digest is what remains once findings 1 and 2 are fixed.

### 10. LOW. The doctrine rule's command fails as written and overclaims

- **Where:** `.claude/rules/performance.md:29`.
- **The command fails:** `python scripts/scrub_public_identifiers.py`, run exactly as written in a scratch clone, exits 2:

```
scrub_public_identifiers.py: error: --log is required when rewriting
```

- **The overclaim:** "so the host name, the operator name and credential-store paths leave the tree". By design, the operator name leaves only two directories, and the credential-store paths remain (finding 3).
- **What holds:** the register. The bullet is a rule with one reason clause and one dated evidence pointer, and it tells no story.

### 11. LOW. No length guard on an explicit `--host` or `--user`

- **What happened:** `--host PC --user qz` in a scratch clone rewrote 77 tracked files in place, replacing 405 occurrences of the standalone word. It exited 1 only because 27 binary files matched.
- **Why:** `MIN_NAME_LEN` applies only to names read from the machine (`:181-182`).
- **Cost:** undoing an in-place rewrite of tracked files needs a discard verb that the hooks block.

### 12. LOW. The placeholders read as real values

- `WORKSTATION` and `operator` are plausible real machine and account names. The credential placeholders use angle brackets; these two do not, and nothing in the evidence files marks them as redacted.
- `docs/security/DATA_MAP.md` now lists the runtime data directory's expected principal as `WORKSTATION\<operator name>`. That principal will not appear in real `icacls` output.
- Inside the evidence, `operator` now names the scrubbed account. It sits beside the earlier `_OPERATOR_` placeholder and the `kind: operator` row label.

### 13. LOW. Prose made stale by the refactor, or written ahead of the merge

- `scripts/scrub_community_export.py:14-15` and `scripts/verify_community_scrub.py:24` still say the scripts embed the username and hostname and must be kept in sync independently. After the refactor they embed neither, and both read one shared source.
- The NEP-0005 evidence write-up (unposted), at lines 38 and 147, says the work was "done the same day on main" and that `--check` "exits 0 on main". 903b6063 is not on main (main is 3e8fa63e), and the script does not exist there.
- The #1741 disposition marks DECISION-1 FIXED at 903b6063 while findings 1 to 4 stand.
- These three items sit in later commits on the same branch.

## Verified holds

- **Check:** `--check` reports 0 findings over 3992 tracked files.
- **Reproducibility:** the commit's script, run on the parent in a scratch clone, produces evidence and document rewrites byte-identical to 903b6063. The only files that differ are the six hand-refactored code and test files and the eight files the commit added or edited by hand.
- **Idempotence:** a second run rewrites 0 files.
- **No over-scrub:**
  - All 84 changed JSON records parse, and all 179 evidence JSON files at 903b6063 parse.
  - No number, boolean, null, type or array length changed.
  - All 191 changed strings and all 67 changed key sets are explained exactly by the three substitutions, and no keys collided.
- **Within one run:** the credential mapping is sorted and deterministic. Inside the two evidence directories, no form of any of the six credential-store paths with the operator name survives, in any case or slash form, and the operator name appears 0 times.
- **Analysis still reproduces:** the phase-2 summary re-derived from the scrubbed records equals the parent's output after the same substitutions (9377 bytes, identical).
- **The scrub log:** its totals recompute from its rows (92 files, 18 host, 157 operator, 371 credential occurrences). Every "before" digest matches 3e8fa63e and every "after" digest matches 903b6063, LF-normalised.
- **Hash bindings:** the tree records no digest of a pre-scrub file except in the SID-rewrite log's dated "after" column. That column is a historical record that no code reads. The changed records contain no embedded hash fields.
- **The lock's digests and failure mode:**
  - The pinned digests equal the live machine's.
  - With the identity variables unset, the lock fails rather than skips: 8 failed with a getpass `ModuleNotFoundError`. It does not show its own message.
  - With `USERNAME=blarai-coder`, exactly the digest-coverage test fails.
  - It catches upper, lower and mixed case, `C:\Users\<name>`, JSON-escaped backslashes and UNC paths.
- **Refactored scripts:** all four import, and `sanitise_tree` runs. Under the operator account, the preflight still refuses the host name and the operator name.
- **Bundle:** `make_changes.py --check` exits 0. The bundle test passes at 903b6063 and fails at 3e8fa63e (3 failed), which confirms the commit message's claim.
- **Names in metadata:** no tracked file path contains either name, and no author or committer e-mail contains the host name.

## Suites and runs

LOCALAPPDATA was redirected to scratch for every pytest run.

| what | where | result |
|---|---|---|
| `test_no_host_identity_in_tree.py` | real checkout, tip f1c9cc29 | 10 passed |
| the six test files touching the four refactored scripts | real checkout | 216 passed |
| `test_containment_evidence_bundle.py`, `test_rules_corpus.py`, `test_doctrine_freshness.py` | real checkout | 155 passed |
| `test_no_machine_sid_domain_in_tree.py`, `test_disposition_discipline.py`, the new lock | real checkout | 59 passed |
| `test_containment_evidence_bundle.py` | scratch clone at 3e8fa63e | 3 failed, 91 passed |
| lock mutants and planted identifier mutants | scratch clone at 903b6063 | as tabled above |

Not run: the full standing gate, because other review agents were active on this machine.

## Merge read

- **Block on 1, 2, 3 and 4.** This commit exists to keep these identifiers out of the public snapshot. Merging as-is puts the host name onto main in the lock file. It also leaves the gzip logs and the credential-store access table in place for the next weekly publish. The backstop cited for all of this misses the residue.
- **Block on 5.** The lock certifies a toggle it does not perform.
- **Block on 6.** It weakens shipped privacy controls compared with the parent.
- **Fix 7 before the scrub runs again.** The new rule makes that the next snapshot.
- **8 to 13 are not blocking.** 8 and 9 are limits to state honestly in the docstring. 10 to 13 are small corrections.

---

# Round 2 (2026-10-14): re-review of 373e9685 and 3dc8a775

VERDICT: FAIL

Reviewed 373e9685 (the rebuild) and 3dc8a775 (the dispositions) on `feat/1765-scrub-public-identifiers`. The real checkout was at 3dc8a775 throughout. Every rewrite, mutant, lock mutation and ratchet attack ran in scratch clones at 3dc8a775 or 3e8fa63e. Nothing in the real checkout was modified apart from this file.

## Round-1 findings, re-verified at 3dc8a775

| round-1 finding | disposition | what the re-run shows |
|---|---|---|
| 1. host name in the lock file | FIXED | Holds. An independent sweep of raw, gzip, UTF-16 and percent-decoded views, plus file paths, finds the host name in 0 of 3999 tracked files. |
| 2. gzip logs and test IDs | FIXED | Holds. All 16 rewritten gzip logs decompress to content identical with my own run of the scrub on the parent. None of the 136 collected test IDs carries either name. |
| 3. report and performance copy | FIXED | Holds for the present tree. Inside the containment scopes, 0 files carry a credential-store path with the operator name. Five files outside them name only the runtime data directory, which the disposition argues is a working path. New content is not covered (R2-5). |
| 4. publisher's leak gate | FIXED | Holds. The publisher's own `git grep -l -E` finds 21 of 21 files at the parent, 1 of 1 at 903b6063, and 0 at the tip. |
| 5. toggle did not toggle | FIXED, partly | The toggles now catch each of seven mutations: `scan`, `find_hits`, `views`, `path_in_scope`, the user digests, the baseline loader and `json_secret_paths`. `--check` and the ratchet test body are still unlocked (R2-4). |
| 6. account-relative controls | FIXED, partly | Under the operator, coder and SYSTEM-form accounts: the preflight refuses a file naming the operator, the community pair leaks no name (its verifier fails closed under the other two accounts), and `sanitise_tree` leaves no name. The in-place scrub is still account-relative (R2-2). |
| 7. placeholder numbers | FIXED | Holds. Running the tip's scrub on the parent reproduces `scripts/credential_store_map.json` byte for byte. |
| 8. ordinary shapes | FIXED | Holds for all 14 identifier mutants from round 1 (table below). New misses are in R2-6. |
| 9. reversible digests | REJECTED | The argument stands for the names. The placeholder map is a different property (R2-8). |
| 10. rule command | FIXED | Holds. The command runs without `--log`. Its default log has a new problem (R2-9). |
| 11. length guard | FIXED | Holds. `--host PC` exits 2. |
| 12. placeholders | FIXED | Holds. `WORKSTATION` remains only in the two review records. |
| 13. stale prose | FIXED | Holds for the four places named. Two new mismatches are in R2-11. |

The round-1 mutants, rerun at the tip. "Lock" is `test_tree_is_clean` plus the ratchet test; "check" is `--check`.

| mutant | round 1 (lock / check) | round 2 (lock / check) |
|---|---|---|
| host, lower case, prose | FAIL / FAIL | FAIL / FAIL |
| host, upper case, UNC path | FAIL / FAIL | FAIL / FAIL |
| operator in `C:\Users\<name>\x`, evidence Markdown | FAIL / FAIL | FAIL / FAIL |
| operator JSON-escaped, evidence JSON | FAIL / FAIL | FAIL / FAIL |
| host after a JSON `\n` escape | pass / pass | FAIL / FAIL |
| operator after a JSON `\n` escape, evidence JSON | pass / pass | FAIL / FAIL |
| host after a JSON `\t` escape | pass / pass | FAIL / FAIL |
| host glued to `_trace` | pass / pass | FAIL / FAIL |
| host in a percent-encoded UNC path | pass / pass | FAIL / FAIL |
| host inside a gzip log | pass / pass | FAIL / FAIL |
| host in UTF-16LE text | pass / pass | FAIL / FAIL |
| host in a tracked file NAME only | pass / pass | FAIL / FAIL (isolated run; in a mixed batch the lock's earlier assertion masks it) |
| host followed by a digit | pass / pass | FAIL / FAIL |
| host after a `\x00` escape | pass / pass | FAIL / FAIL |
| clean controls | pass / pass | pass / pass |

## Round-2 defects, most severe first

### R2-1. HIGH. The hand edit to the containment payload makes arm A probe the coder account's own profile, not the operator's secrets

- **Where:** `tools/probes/containment_arms/arm_payload.py:30`. At the parent, `HOME` was the operator's profile path, fixed. Now it is `USERPROFILE`, or `Path.home()`, of whatever process runs the payload. The comment beside it still says "the operator profile".
- **What is wrong:** the payload runs inside the setup being measured. Arm A (`arm_a_operator.ps1`) runs the copy that `run_arm.py` deploys. It runs it as `blarai-coder` through an S4U scheduled task and passes no home path. Under that account, `USERPROFILE` is the coder's profile.
- **Cost:** arm A is the one containment measurement still pending. The 10-10 report says "arm A not yet run"; it is for the Lead Architect to run after the #775 flip. Run as written, its five secret reads probe the coder's own profile directory, which exists on this machine. They do not try the operator's stores.
  - The record would show those reads as `absent`.
  - The phase-2 summariser joins secret reads to the effective-access rows by path, so these reads match nothing and drop out of the prediction table.
  - The study asks whether the coder account can read the operator's credentials. It would answer a different question and not say so.
- **Reproduced (the mechanism):** I loaded the payload module under each profile.

| USERPROFILE | first two secret paths the payload probes |
|---|---|
| the operator's | the operator's `.ssh` and `.git-credentials` |
| `C:\Users\blarai-coder` | `C:\Users\blarai-coder\.ssh` and `C:\Users\blarai-coder\.git-credentials` |

- **Not run:** arm A itself, because it needs the coder account's scheduled task, a system change for the Lead Architect. The end-to-end effect on an arm-A record is a hypothesis; the path resolution is reproduced.
- **Incidence:** 1 pending arm.

### R2-2. HIGH. Under any other account the scrub rewrites that account's name to `<user>` across the containment evidence, and every gate stays green

- **Where:** `scripts/scrub_public_identifiers.py:181-182` and `main`. Recognition now uses digests, but the replacement string still comes from `USERNAME`. Nothing checks, before rewriting, that the live name's digest is a pinned operator digest.
- **Reproduced** in a scratch clone at 3dc8a775, with `USERNAME=blarai-coder`:
  - The scrub printed `rewrote 27 file(s)` and logged 81 operator user-name occurrences, exit 0. All 81 are the coder account's name.
  - Sample sentences after the rewrite: "The dedicated account `<user>` on the same payload (needs the Lead Architect)", and "`<user>` account blocked that account's outbound connection to the internet in all 3 runs, while the operator's ...". `<user>` is the operator's placeholder, so these sentences now attribute the coder account's results to the operator.
  - The rewritten files include `PERFORMANCE_LOG.md`, two containment records in `docs/performance`, five effective-access records, the 10-10 report, and 14 files in the 2026-10-05 bundle, PowerShell scripts among them.
  - Afterwards `--check` reports 0 findings, under the operator account and under the coder account. Only the bundle's hash test would notice, and only for that one directory.
- **Cost:** the meaning of security evidence changes silently, with every gate green. The scrub is now a standing step before every snapshot, and the containment study's subject is work run under that other account.
- **Incidence:** no known run under another account; the rewrite itself is reproduced.

### R2-3. MEDIUM. The ratchet does not enforce "only shrinks", and the files it exempts are the ones sessions write to most

- **The claim:** the commit message, DEC-21 and the disposition say new content cannot add the name and the list only comes down.
- **What is enforced:** no file outside the list may carry the name, and the list may hold at most 558 paths.
- **Reproduced** in scratch clones at 3dc8a775. "Ratchet tests" means `test_user_name_baseline_only_shrinks` and `test_no_new_file_outside_the_scope_carries_the_operator_name`.

| attack | ratchet tests | `--check` |
|---|---|---|
| append a line with the name to CLAUDE.md, a listed file | pass | exit 0 |
| swap: clean one listed file and give its slot to a NEW name-carrying file (count stays 558) | pass | exit 0 |
| clean a listed file and leave it listed, a slot that can take the name back later | pass | exit 0 |
| list a 559th file, ceiling untouched | 1 failed | exit 0 |
| list a 559th file and raise `USER_BASELINE_CEILING` to 559 in the same change | pass | exit 0 |

- **What the ceiling catches:** only a bare append to the list.
  - It does not fall when the list falls, so each cleanup opens a slot.
  - `--check`, the gate form the doctrine rule names, does not apply the ceiling at all.
  - Nothing compares the list with main's copy.
- **Which files are exempt:** the list includes CLAUDE.md, FIELD_NOTES.md, BUILD_JOURNAL.md, LESSONS.md, docs/ROADMAP.md, docs/DECISION_REGISTER.md and `.claude/rules/vikunja.md`.
- **Measured on main,** non-merge commits since 2026-09-14: 78 added lines carrying the name went into 19 files that are now on the list. The ratchet would have seen none of them.
- **Today:** 0 listed files are stale, so there is no free headroom yet.

### R2-4. MEDIUM. `--check` and the ratchet test body can be switched off with the whole lock file green

- **Where:**
  - `test_check_mode_agrees_with_the_lock` compares `check()` with the lock only on the clean tree, where both return nothing.
  - `test_toggle_ratchet_sees_a_new_file` asserts `find_hits` and `path_in_scope`, never the ratchet test itself.
- **Reproduced** in a scratch clone at 3dc8a775, one mutation at a time, running the whole lock file:

| mutation | result |
|---|---|
| `check()` returns `[]` | 30 passed |
| the ratchet test skips every file | 30 passed |

- **Cost:** the doctrine rule names `--check` as the gate form before a publish. A `--check` that can never fail passes every test written for it. This is round-1 finding 5's class, still open on these two paths.

### R2-5. MEDIUM. Credential-store paths are redacted only when a raw record sits in the credential scope during the same run

- **Where:** `credential_map` collects real paths only from JSON and gzip records under `CREDENTIAL_SCOPE`. After the first run every collected path is a placeholder, so a later run has nothing to replace. The map holds digests, so it cannot supply the paths either.
- **Reproduced** in a scratch clone at 3dc8a775: I added new study content, then ran the documented workflow (scrub, then `--check`).

| new content | after the scrub | `--check` |
|---|---|---|
| a Markdown table in the evidence directory naming two credential stores with the operator name and `allowed` | `C:\Users\<user>\.ssh` and `C:\Users\<user>\.git-credentials` stay, still marked `allowed` | 0 findings for it |
| a new effective-access record under `docs/performance/containment_probe_2026-10-20/` | user replaced; the `kind: secret` path kept | exit 1, and no run of the scrub can clear it |

- **Cost, first case:** this is round-1 finding 3's shape again. A later report quotes the table, its rows sit beside `<credential-store-N>` records, and the pair decodes them.
- **Cost, second case:** the gate goes red on the next containment study banked to a new `docs/performance` folder. The rule allows only the script as a remedy, and the script cannot fix it.

### R2-6. MEDIUM-LOW. One ordinary shape is still invisible to the lock, the check, the ratchet and the scrub

All of these ran in a scratch clone at 3dc8a775.

| mutant | lock | `--check` |
|---|---|---|
| operator name right after an ANSI colour code, in scope (git-bash prompt: ESC `[32m`, then the name, then `@`) | pass | pass |
| the same, in a NEW file outside the scope | pass | pass |
| operator name with a leading letter, a trailing letter or a leading digit, in scope | pass | pass |
| host name as a UTF-16LE fragment inside an otherwise ASCII log | pass | pass |
| host name in a PNG zTXt chunk, a zip member, base64, or split by a zero-width space | pass | pass |
| host name in gzip inside gzip, or in a tar.gz member | FAIL | FAIL |

- **The scrub:** it leaves the in-scope ANSI case untouched (`rewrote 0 file(s)`; the name is still in the file).
- **Why this one is ordinary:** coloured terminal output is the normal shape of a git-bash transcript. 13 tracked files contain ANSI escape sequences, and 0 have the name directly after one today.
- **The honest limit:** `identity_lock`'s docstring covers punctuation splits, base64 and other compressions. It does not name the ANSI case or a UTF-16 fragment inside an ASCII file.

### R2-7. LOW-MEDIUM. No always-loaded instruction mentions the ratchet, and the only rule forbids its remedy

- **The gap:** CLAUDE.md, `.claude/rules/` and `.claude/agents/` never mention the ratchet, the baseline, or writing `%USERPROFILE%` or `<user>` in new files.
- **The conflict:** `.claude/rules/performance.md:29` says the scrub is "never a hand edit". For a new file outside the scope, the ratchet's only remedy is a hand edit, because the scrub does not rewrite there.
- **Expected firing rate,** measured from main over the last 30 days: 78 new files outside the scope carried the name, on 13 of those days, with at most 15 in one day.
- **Right now:** 16 untracked files in the real working tree, other sessions' in-flight work, carry the name. The first commit of any of them turns the standing gate red. For a session that does not know the ratchet, the nearest fix is the swap in R2-3.

### R2-8. LOW. The credential map decodes every placeholder from public content

- **The decode:** `scripts/credential_store_map.json` holds sha256 digests of normalised paths. I read the account name from a working path in CLAUDE.md and hashed it with ten common store names. All six entries matched, in milliseconds.
- **The overclaim:** `test_credential_numbers_are_stable_across_runs` asserts `"ssh" not in json.dumps(saved)`, which certifies the map as unreadable. It is readable.
- **Either purpose fails:**
  - If the placeholders exist only to keep the operator name out of paths, a fixed `C:\Users\<user>\<store>` does that without a map.
  - If they exist to hide which store is which, three things each undo them: the map, the probe code's list, and the `_OPERATOR_` list rows in the 2026-10-05 bundle.

### R2-9. LOW. A second same-day run of the rule's command erases that day's scrub log

- **Where:** the default log is `docs/reviews/public-identifier-scrub-log-<date>.md`, and it is untracked when written.
- **Reproduced** in a scratch clone: the first run rewrote 1 file and logged 1 row. A second run the same day wrote 0 rows to the same path.
- **Cost:** the docstring says the before and after digests let a recorded fingerprint be re-recorded. They are gone unless the first log was committed in between.

### R2-10. LOW. Two rewrites change what a file is

- **A banked script stops running:** `docs/performance/gate_runtime_2026-10-07/exploratory_parallel_split/parallel_trial.sh` now reads `cd /c/Users/<user>/BlarAI-worktrees/...`. Bash parses `<user>` as an input redirection, so the banked as-run script no longer runs. This is 1 file in scope today.
- **Gzip bytes depend on the interpreter:** the committed logs carry header OS byte `ff`, as Python 3.14 writes it. The project venv, Python 3.11.9, writes `0a`. Decompressed content is identical. The docstring says `mtime` 0 makes the result reproducible.

### R2-11. LOW. Prose that does not match its record

- **Scope:** the disposition's F3 row says `USER_SCOPE` names `tools/probes/containment_arms`. It does not. The 14 probe files sit outside every scope, are not on the list, and are clean, so the ratchet covers them.
- **File count:** the disposition says "now 206 files". The commit message and the scrub log say 200, and the log's rows recompute to 200 (host 112, user 608, credential 382).
- **A test name:** `test_recognition_does_not_depend_on_the_running_account` plants the live names, so under any other account it fails. Independence is real, as the preflight and community-pair runs show, but this test does not demonstrate it.
- **Runtime:** the lock took 52 s and 54 s in two runs, against 5.5 s in round 1, because it scans the tree three times. Other review agents were active during both runs.

## Verified holds (round 2)

- **Reproducibility:** the tip's scrub, run on the parent, reproduces every non-gzip rewrite byte for byte. Every gzip rewrite matches after decompression. The credential map matches exactly. A second run rewrites 0 files.
- **No over-scrub:**
  - All 155 changed JSON records parse.
  - No number, boolean, null, type or array length changed.
  - All 323 changed strings and all 67 changed key sets are explained by the scrub's own substitution.
  - At the parent, no credential-path match runs on into a longer path name (0 cases).
- **The log:** it has 200 rows, and its totals recompute (112, 608, 382). Every "before" digest matches 3e8fa63e and every "after" digest matches 373e9685.
- **Hash bindings:** outside the two scrub logs, no tracked file records a digest of a pre-scrub version of any of the 220 modified files. The search covered sha256, sha1, md5 and git blob IDs, full and as 12- or 16-character prefixes.
- **Tests:** the related suites pass (420 passed). The disposition verifier passes 13 of 13. `make_changes.py --check` is up to date.
- **Failure mode:** with the identity variables unset, the lock fails with its own message (23 failed, 4 passed) rather than skipping.
- **Robustness:** an odd-length, NUL-heavy binary does not crash the scrub.

## Suites and runs (round 2)

LOCALAPPDATA was redirected for every pytest run.

| what | where | result |
|---|---|---|
| `test_no_host_identity_in_tree.py` | real checkout, 3dc8a775 | 30 passed (three runs: 73 s, 54 s, 52 s) |
| hf_publish, the four phase-1 files, gate-runtime dataset, bundle, rules corpus, doctrine freshness, SID lock, disposition discipline | real checkout | 420 passed |
| `--check` | real checkout | 0 findings in 3999 tracked files |
| mutants, lock mutations, ratchet attacks, other-account rewrite, new-content runs | scratch clones at 3dc8a775 | as tabled above |
| scrub reproduction | scratch clone at 3e8fa63e | 207 files: the 200 logged plus the 7 hand-edited files |

Not run: the full standing gate, and arm A.

## Merge read (round 2)

- **Block on R2-1.** The pending arm-A ceremony would measure the wrong account's files and report the result as the operator's.
- **Block on R2-2.** One run under the coder account rewrites the study's evidence about that account, and every control stays green.
- **Block on R2-4.** The gate form the rule names can be disabled without any test noticing. This is the same class as round-1 finding 5, which blocked.
- **Fix R2-3, or restate the claim, before anyone relies on DEC-21 and the commit message.** They promise the list "only shrinks" and that new content cannot add the name. Neither is enforced.
- **R2-5 to R2-11 do not block.** R2-5 is the next real exposure path; close it before the next containment study lands.

---

# Round 3 (2026-10-14): re-review of d51d7c72, 38f5577a, 92033590 and a3e0b296

VERDICT: FAIL

Reviewed a3e0b296 on `feat/1765-scrub-public-identifiers`. The lock and `--check` ran on the real checkout at a3e0b296. Every rewrite, mutant, lock mutation and ratchet attack ran in scratch clones of a3e0b296 or 3e8fa63e. Nothing in the repository was modified by the reviewer. The two identifiers are written here as "the host name" and "the operator name".

## Round-2 findings, re-verified at a3e0b296

| round-2 finding | disposition | what the re-run shows |
|---|---|---|
| R2-1. arm A probes the coder's profile | FIXED | Holds for arm A and for `run_arm.py`. I evaluated arm A's own `$arg` line in pwsh under the operator's session, then parsed it in the payload under `USERPROFILE=C:\Users\blarai-coder`. It resolves to the operator's `.ssh` and `.git-credentials`. Arm E is now broken (R3-1). |
| R2-2. rewrite under another account | FIXED | Holds. The rewrite refuses under `USERNAME=blarai-coder`, under the SYSTEM-form name and under another host name. No log is written and the clone is unchanged. |
| R2-3. ratchet does not only shrink | FIXED | Holds where `main` carries the baseline: append, swap, cleaned-but-listed and count raise each fail both the ratchet test and `--check`. It does not hold where `main` does not resolve, or on main itself (R3-3). |
| R2-4. `--check` and ratchet body unlocked | FIXED | Holds for `check()`, `ratchet_violations()` and `count_user_hits`. The reader of main's copy is still unlocked (R3-3). |
| R2-5 and R2-8. credential map | FIXED | Holds by design. The map is gone, store rows are clean once the path no longer carries the name, and the credential toggle covers it. |
| R2-6. ANSI and other shapes | FIXED | Holds for raw ANSI codes, a leading digit and a UTF-16 fragment. Escaped and encoded variants are still missed (R3-2). |
| R2-7. ratchet not in instructions | FIXED, partly | The rule exists, but it is delivered on the paths where the ratchet does not fire (R3-5). |
| R2-9. same-day log clobber | FIXED | Holds by reading: the log stamp now has seconds. |
| R2-10. banked script, gzip bytes | FIXED, partly | `__USER__` fixes the banked shell script. The gzip bytes still depend on the zlib build (R3-7). |
| R2-11. prose | FIXED | Holds. The log has 200 rows. |
| AUTO-1. ratchet read raw bytes only | FIXED | Holds. Making `count_user_hits` raw-only fails toggle step 8. |

Mutants rerun in scratch clones of a3e0b296. "Lock" means `test_tree_is_clean` plus `test_ratchet_holds_on_the_tree`; "check" means `--check`.

| mutant | lock / check |
|---|---|
| all 11 round-1 host shapes, plus the round-2 UTF-16 fragment inside an ASCII log | FAIL / FAIL |
| host in a tracked file NAME only (run alone, so no earlier assertion masks it) | FAIL / FAIL |
| operator in `C:\Users\<name>\x`, operator JSON-escaped, operator after a JSON `\n`, all in scope | FAIL / FAIL |
| operator after a raw ANSI colour code, operator with a leading digit, in scope | FAIL / FAIL |
| host or operator in plain text appended after a gzip member | FAIL / FAIL (the scrub cannot clear it: R3-8) |
| host or operator with its first letter JSON `\u`-escaped | pass / pass (R3-2) |
| operator after a JSON-escaped ANSI code (`\u001b[32m`) | pass / pass (R3-2) |
| operator after a percent-encoded ANSI code (`%1B%5B32m`) | pass / pass (R3-2) |
| operator with its first letter as an HTML entity | pass / pass (R3-2) |
| PNG zTXt, zip member, base64 | pass / pass (stated limit) |
| clean controls | pass / pass |

## Round-3 defects, most severe first

### R3-1. MEDIUM-HIGH. Arm E can no longer run: its launcher does not pass the argument the payload now requires, and no test locks the R2-1 fix

- **Where:** `tools/probes/containment_arms/run_arm_e.py:129-132`. `build_config` writes the payload command line without `--operator-home`. `arm_payload.py` now declares that argument `required=True`.
- **Reproduced:** I built the command line with arm E's own `build_config("E1", ...)` and ran the payload's argument parsing on it. It exits 2 with:

```
arm_payload.py: error: the following arguments are required: --operator-home
```

- **Cost:**
  - Every arm-E run now ends before probing anything.
  - The launcher records `payload: None` and prints `NO PAYLOAD`.
  - `summarise_phase2.py` lists such variants under "variants that did not start or were refused". In the MXC container comparison, a harness argument error then reads as a containment outcome.
- **No lock:** no test references `arm_payload`, `--operator-home` or `run_arm_e`. The R2-1 fix shipped without a regression lock, and the one launcher it missed shows what that costs.
- **Incidence:** 1 of 3 launchers.

### R3-2. MEDIUM. Escaped and encoded shapes that the lock, `--check`, the ratchet and the scrub all miss, while the publisher's preflight refuses the same files

- **Why they are missed:**
  - `views()` derives every view from the raw bytes independently, and never chains two of them.
  - The JSON view replaces an escape with a separator instead of decoding it.
  - The ANSI view runs only when the raw bytes contain a real ESC byte.
  - So a JSON-escaped ESC (`\u001b[32m`), which is how `json.dumps` writes coloured terminal output, leaves `32m` glued to the name in every view.
  - A JSON-escaped letter (`\u006d` and so on) splits the name in two.
  - A percent-encoded ANSI code is decoded by the percent view, but never ANSI-stripped.
- **The differential:** the same five files, through the lock's `find_hits`, the ratchet's `count_user_hits`, and the publisher's preflight under the operator account:

| file | lock `find_hits` | ratchet count | `hf_publish.py preflight` |
|---|---|---|---|
| operator after a JSON-escaped ANSI code | none | 0 | exit 1, identity refused |
| operator with the first letter `\u`-escaped | none | 0 | exit 1, identity refused |
| host with the first letter `\u`-escaped | none | 0 | exit 1, identity refused |
| operator after a percent-encoded ANSI code | none | 0 | exit 1, identity refused |
| plain-text control | user | 1 | exit 1, identity refused |

- **Why the preflight sees more:** it JSON-decodes `.json` files before scanning, and it matches the live name as a substring.
- **What that means:** the public snapshot of the tree can carry what the Hugging Face upload refuses. Any JSON consumer, such as a dataset viewer, decodes these escapes and shows the name.
- **Ratchet gaming:** both ratchet regimes passed the name added as JSON-escaped ANSI output, once to CLAUDE.md (a listed file) and once to a new file outside the scope. This is the one way to add occurrences while the count stays flat.
- **Incidence:** 0 tracked files at 3e8fa63e or at a3e0b296 contain a JSON-escaped ANSI code or a JSON-escaped ASCII letter. The honest limit in `identity_lock` names none of these shapes.

### R3-3. MEDIUM. The branch comparison is unlocked, and it switches off silently whenever `main` does not resolve to a baseline

- **Where:** `main_user_baseline` returns `None` when `git show main:...` fails. `ratchet_violations` then skips the "never grows on a branch" checks and says nothing.
- **Reproduced:**

| condition | swap (clean a listed file, list a new one) | raise CLAUDE.md's count with its content |
|---|---|---|
| local `main` carries the baseline (simulated merge) | fails | fails |
| no local `main` (a fresh clone of the branch) | ratchet test passes, `--check` exit 0 | ratchet test passes, `--check` exit 0 |
| on main, the same raise committed | n/a | ratchet test passes, `--check` exit 0 |

- **The reader is untested:** mutating `main_user_baseline` to always return `None` leaves the whole lock file at 35 passed. The toggle hands `main_copy` straight to `ratchet_violations` and never exercises the git read.
- **Cost:**
  - Today, on this branch, main has no baseline, so the comparison is off. This is expected before the merge.
  - After the merge it is on for branches. It is blind on main, so the post-merge gate cannot catch a growth that merged.
  - Any run where `main` does not resolve, such as a fresh clone of a feature branch, reports a clean ratchet without saying the comparison did not run.
  - This is round-2 R2-4's class: a control path that can be off with every test green.

### R3-4. LOW-MEDIUM. The preflight's file-name check still depends on the running account

- **Where:** `hf_publish.preflight` checks file names against `deny` only, the live-name string list. It never applies `identity_lock.find_hits` to the name. The lock's `name_in_path` does use digests.
- **Reproduced:** a directory holding one clean file whose NAME carries an identifier.

| account | operator name in the file name | host name in the file name |
|---|---|---|
| operator | exit 1 | exit 1 |
| `blarai-coder` | exit 0, `preflight: CLEAN` | exit 1 |
| SYSTEM form | exit 0, `preflight: CLEAN` | exit 1 |

### R3-5. LOW-MEDIUM. The ratchet's rule reaches sessions only on the paths where the ratchet does not fire

- **Where the rule lives:** the ratchet bullet is in `.claude/rules/performance.md`. That file is delivered for `PERFORMANCE_LOG.md`, `docs/performance/**`, `tools/probes/**`, `evals/**`, and bench, measure and probe scripts.
- **The mismatch:** the first two paths sit inside `USER_SCOPE`, which is exempt from the ratchet. The ratchet fires on new files everywhere else.
- **Measured from main's last 30 days:** 78 new out-of-scope files carried the name.
  - By area: `docs/reviews` 23, `docs/research` 15, `scripts` 11, `tools/probes` 6, `docs/adrs` 4.
  - Only the 6 under `tools/probes` would have had the rule delivered.

### R3-6. LOW. The next month-end journal rotation will fail the gate

- **Mechanism:** BUILD_JOURNAL.md's single listed occurrence sits in the entry dated 2026-10-05. `tools/doc_hygiene/rotate_log.py` moves a closed month's entries into that month's volume under `docs/archive/journal/`, and 2026-10.md does not exist yet.
- **Expected result:** at the first rotation after 2026-10-31 the new volume carries the name and is not on the list. The rotation commit then fails "outside the baseline". It also fails "carries the name no more" for BUILD_JOURNAL.md.
- **Missing guidance:** neither `rotate_log.py` nor the journal rule tells the rotating session to scrub the moved text.
- **Status:** derived from the files; I did not run the rotation.

### R3-7. LOW. `gzip_bytes` is not interpreter-independent

- **The claim:** the docstring and `test_gzip_bytes_are_interpreter_independent` say the output is identical on every interpreter.
- **What happens:** re-compressing a committed log's own content reproduces the committed bytes only under Python 3.14.4, whose zlib is `1.3.1.zlib-ng`. The project venv, Python 3.11.9 with zlib 1.3.1, writes 429,138 bytes against the committed 430,818.
- **Scale:** in my reproduction all 16 rewritten gzip logs differ in bytes, with identical content.
- **Why the test passes:** it compresses one repetitive sample, which happens to compress identically under both.
- **Consequence:** the log's "after" digests for those 16 files can be reproduced only with the interpreter that wrote them.

### R3-8. LOW. The scrub silently skips a gzip member with trailing text, which the lock flags

- **The gap:** `scrub_bytes` returns the input unchanged with zero counts when `gzip.decompress` raises. The run therefore logs nothing about the file and exits 0, while `--check` fails on it.
- **Cost:** a red gate that the standing control cannot clear and does not report.
- **Incidence:** 0 tracked files.

## Verified holds (round 3)

- **Tree state:** the lock passes on the real checkout at a3e0b296 (35 passed, 53.7 s). `--check` reports 0 findings in 3999 tracked files.
- **Residue:** an independent sweep of raw, gzip, UTF-16 and percent views plus file paths finds:
  - the host name in 0 files;
  - the operator name in 0 files in scope;
  - credential-store paths with the operator name only in five files that name the runtime data directory as a working path.
- **No gaming headroom:** for all 558 listed files, the listed count equals both the maximum over views and the raw plain-text count, so no file has hidden-shape headroom. Plain-text occurrences appear in every view, so the plain footprint cannot grow without raising some view's count. Only the R3-2 shapes add occurrences unseen. The list holds 3,861 occurrences in total.
- **Lock mutations, whole file each time:**

| mutation | result |
|---|---|
| `check()` returns `[]` | 1 failed |
| `ratchet_violations()` returns `[]` | 2 failed |
| `count_user_hits` reads raw bytes only | 1 failed |
| `live_names_are_pinned()` always true | 1 failed |
| `main_user_baseline()` always `None` | 35 passed (R3-3) |

- **Other accounts:** the preflight refuses file content naming either identifier under the operator, coder and SYSTEM-form accounts. The community pair leaves no name in its output under any of them, and its verifier fails closed under the other two. `sanitise_tree` leaves no name under any of them.
- **Reproducibility:** the tip's scrub, run on the parent, reproduces every non-gzip rewrite byte for byte. The 16 gzip logs match after decompression. A second run rewrites 0 files.
- **No over-scrub:** all 155 changed JSON records parse. No number, type or array length changed. All 323 changed strings and all 67 changed key sets are explained by the scrub's own substitution.
- **The log:** it has 200 rows, and its totals recompute (host 112, operator 990). Every "before" digest matches 3e8fa63e and every "after" digest matches a3e0b296.
- **Hash bindings:** outside the 1765 logs, no tracked file records any digest of a pre-scrub version of the 220 modified files.

## Suites and runs (round 3)

LOCALAPPDATA was redirected for every pytest run.

| what | where | result |
|---|---|---|
| `test_no_host_identity_in_tree.py` | real checkout, a3e0b296 | 35 passed |
| `--check` | real checkout | 0 findings in 3999 tracked files |
| mutants, lock mutations, ratchet attacks in two regimes, other-account runs, launcher argument checks | scratch clones of a3e0b296 | as tabled above |
| scrub reproduction | scratch clone of 3e8fa63e | 206 files: the 200 logged plus the hand-edited files |

Not run: the full standing gate, arm A, arm E, and the journal rotation.

## Merge read (round 3)

- **Block on R3-1.** This branch broke a measurement harness, and it shipped the fix that broke it without a lock.
- **Fix R3-3 in the same pass.** It is round-2 R2-4's class, which blocked. In the real checkout after merge the comparison does run for branches, which is why it is not listed as a blocker on its own.
- **R3-2 to R3-8 do not block.** R3-2 is the next exposure path and should be closed, or named in the honest limit, before the lock and ratchet are cited as complete.

---

# Round 4 (2026-10-14): re-review of ec11efd6, bbc351c9 and a74a2b4e

VERDICT: PASS, with four findings to fix in the next pass before the ratchet's "never grows" is cited as enforced on main (R4-1 to R4-4). None of them puts an identifier into the public snapshot or switches a control off in the flow that runs today.

Reviewed a74a2b4e on `feat/1765-scrub-public-identifiers` (main 3e8fa63e). The lock, the launcher lock, `--check` and the related suites ran on the real checkout at a74a2b4e with LOCALAPPDATA redirected. Every mutant, mutation, scratch repository and rewrite ran in two scratch clones of a74a2b4e under the reviewer's scratchpad (`r4/clones/tip` for the first mutation battery, `r4/clones/tip2` for everything else). Nothing in the repository was modified by the reviewer except this file. No arm ran, no probe payload ran, no elevated shell was used. The identifiers are written here as "the host name" and "the operator name".

## Round-3 findings, re-verified at a74a2b4e

| round-3 finding | disposition | what the re-run shows |
|---|---|---|
| R3-1. arm E dropped `--operator-home`; no launcher lock | FIXED | Holds. The exact `cmd` expression of `run_arm_e.build_config`, of `run_arm.py` and the `$arg` line of `arm_a_operator.ps1`, evaluated with a stubbed USERPROFILE and handed to CreateProcess with an argv-echo stub in the payload's place, deliver `--operator-home <that profile>` for a plain path, a path with spaces, a `$` and a `%VAR%`. The payload refuses without the argument (exit 2, test passed). Dropping the argument from `run_arm_e.py` fails the launcher lock (mutation table). Trailing-backslash profiles are R4-8. |
| R3-2. escaped and encoded shapes missed | FIXED | Holds. The five round-3 shapes plus HTML hex entities are seen by `find_hits`, counted by the ratchet, flagged by `check()` in and out of scope, and the rewrite run exits 1 naming the file (test passed; mutant table below). Removing the JSON/HTML decoding or the ANSI/percent readings fails the lock (mutation table). New misses are R4-6. |
| R3-3. branch comparison unlocked, silent when main absent | FIXED, with holes | Holds for the cases the author named: on a branch main's copy is read through git and a raise is caught (also from a linked worktree); on main the previous commit's copy catches a raise at the commit that made it; a single-branch clone, an `origin/main`-only clone and an unreadable `main:` copy are each a finding. Making an unresolvable reference read as a first landing fails the toggle. The reference is still blind one commit later on main (R4-1) and reads as clean on a detached HEAD at main's tip and in a shallow clone (R4-2). |
| R3-4. publisher file-name check account-relative | FIXED | Holds. Under `USERNAME=blarai-coder` and another host name the preflight refuses a file named after the operator and one named after the host by digest (test passed); removing the digest check fails it (mutation table). |
| R3-5. rule delivered where the ratchet does not fire | FIXED, partly | The hook delivers `identity.md` on Write/Edit (held once) under `docs/reviews`, `docs/research`, `docs/adrs`, `docs/archive`, `docs/handoffs`, on Bash/PowerShell commands naming such a path (Windows and `/c/` spellings), on the four command names, and to a subagent keyed by `agent_id`. It does not deliver it on `scripts/`, `tests/` or `tools/`, which CLAUDE.md's index says it does (R4-4). |
| R3-6. journal rotation would fail the gate | FIXED | Holds. `rotate_log.py` returns 2, prints REFUSED and writes nothing when a cold entry carries the name (test passed; removing the refusal fails it, mutation table). `BUILD_JOURNAL.md` now counts 0 and is not listed; the baseline at a74a2b4e differs from a3e0b296 by exactly that one removal (557 files, 3,860 occurrences). |
| R3-7. gzip bytes claimed interpreter-independent | FIXED | Holds by reading and by the scratch log: the docstring claims the header only, the test is renamed and asserts header and round trip, and the log records `Python 3.11.9, zlib 1.3.1`. |
| R3-8. unreadable gzip member skipped silently | FIXED | Holds. A member with trailing bytes is logged as such and the run exits 1 (test passed); dropping the marker fails the test (mutation table). |

The round-1, round-2 and round-3 mutant shapes, each planted as one file in a scratch repository and run through the lock's per-file `scan` (the function `test_tree_is_clean` calls) and the scrub's `check()`:

| mutant | lock scan | `check()` |
|---|---|---|
| all 14 round-1 shapes (prose, UNC, JSON `\n`/`\t`/`\x00` escapes, `_trace` glue, percent UNC, gzip log, UTF-16, file NAME, digit glue, operator JSON-escaped path) | FAIL | FAIL |
| round 2: operator after a raw ANSI code in scope, leading digit, UTF-16 fragment inside ASCII, gzip inside gzip, plain text after a gzip member | FAIL | FAIL |
| round 2: operator after a raw ANSI code in a NEW file outside the scope | pass (ratchet's business) | FAIL |
| round 3: operator after a JSON-escaped ANSI code, first letter `\u`-escaped (operator and host), after a percent-encoded ANSI code, as HTML entities | FAIL | FAIL |
| round 3: operator after a JSON-escaped ANSI code in a NEW file outside the scope | pass (ratchet's business) | FAIL |
| stated limits: zero-width split, base64 | pass | pass |
| controls: clean prose; `__HOST__` and `__USER__` | pass | pass |

## Round-4 defects, most severe first

### R4-1. MEDIUM. On main the ratchet's reference is only the previous commit, so a growth that lands without a gate run at its merge commit is accepted one commit later and becomes the reference

- **Cost:** the docstring of `reference_baseline` (`scripts/scrub_public_identifiers.py:189-190`) says "on main it is the previous commit's (the merge's first parent), so a growth that merged is caught by the gate on main". It is caught only if the gate runs at that exact commit. The next docs merge makes the grown baseline the reference, and the weekly snapshot publishes from main. Main took seven merges since local midnight; whether a gate ran at each is not recorded.
- **Where:** `scripts/scrub_public_identifiers.py:196` (`ref = "HEAD~1" if ... == "main"`).
- **Reproduced** (scratch repositories, `merge.ff=false`, through `check()`):

| condition | ratchet |
|---|---|
| branch raises a count together with its content | `baseline count raised on this branch (2 -> 3)` |
| main at the merge commit of that branch | `baseline count raised on this branch (2 -> 3)` |
| main one unrelated docs commit later | clean |
| main one empty commit after a merge whose second parent raised | clean |
| main: commit D deletes the baseline, commit R re-adds it raised; gate at R | clean, `--check` prints `branch comparison skipped: the baseline first lands in this history` |

- **Lock:** `test_toggle_branch_comparison_reads_the_reference_and_fails_closed` drives a raise at HEAD only. Nothing asserts what the reference is one commit after a merge, and nothing prevents the first-landing exemption from firing again on main (last row).
- **What still holds:** a raise on any branch that resolves `main` is caught before it merges, so two gate skips (the branch's and main's) are needed for a growth to land unseen.

### R4-2. MEDIUM-LOW. Three read conditions pass silently instead of failing closed: a detached HEAD at main's tip, a shallow clone of main, and an unborn HEAD

- **The claim:** disposition row R3-3 and the docstring: "a reference that does not resolve or is unreadable is a ratchet finding; only the first landing ... is exempt".
- **Where:** `scripts/scrub_public_identifiers.py:193-196` (`rev-parse --abbrev-ref HEAD` prints `HEAD` when detached, so `ref` becomes `main`; any non-zero exit returns FIRST_LANDING) and `:203-205` (an unreachable `HEAD~1` on main reads as the root commit).
- **Reproduced** (scratch repositories, through `reference_baseline()` and `check()`):

| condition | reference | `check()` |
|---|---|---|
| main, branch checked out, last commit raised the count | previous commit's copy | `baseline count raised on this branch (1 -> 2)` |
| the same commit checked out detached | `main`'s copy, which is this tree | clean |
| `git clone --depth 1 -b main` of that repository | `None`, FIRST_LANDING | clean |
| `git init`, files staged, no commit | `None`, FIRST_LANDING | clean |
| single-branch clone of a feature branch | `None`, "main does not resolve" | finding |
| plain clone of a feature branch (`origin/main` only) | `None`, "main does not resolve" | finding |
| `main:` copy is not JSON | `None`, "not a readable baseline" | finding |

- **Incidence today:** nil. The standing gate runs in the primary checkout or a linked worktree on a branch, and the snapshot publisher runs its own `git grep`, never this check. The first two rows are the ones to close before the gate is ever run from a detached or shallow checkout (a CI-style run). The toggle test exercises none of the three.

### R4-3. LOW-MEDIUM. A listed file's count is a ceiling that does not follow the file down: a partial clean leaves headroom a later branch can fill with a new occurrence, every gate green

- **Where:** `ratchet_violations` (`scripts/scrub_public_identifiers.py:242-247`) fails on `n == 0` and `n > baseline[r]`; `0 < n < baseline[r]` is accepted and the list is not required to come down with it.
- **Reproduced** (scratch repository, `merge.ff=false`, through `check()`): a listed file with 3 occurrences, listed 3.

| step | ratchet |
|---|---|
| branch rewrites one of the three to `%USERPROFILE%`, baseline untouched | clean |
| merged to main | clean |
| a later branch adds a NEW working path to the same file (back to 3) | clean |

- **Cost:** the listed files are the ones edited daily (CLAUDE.md 3, FIELD_NOTES.md 7, LESSONS.md, ROADMAP, DECISION_REGISTER). "What already carries the name is frozen per file" holds against the lock-day count, which is what the operator asked for; "it never gets worse" than the best state reached since does not hold. The rule in `identity.md` covers only the fully cleaned file ("dropped from the list in the same change").
- **No headroom today:** for all 557 listed files the listed count equals `count_user_hits` and equals the plain-text count.

### R4-4. LOW-MEDIUM. CLAUDE.md's rules index claims a delivery surface the hook does not provide, and the index test cannot see it

- **Where:** `CLAUDE.md:255`: "identity.md ... delivered on docs, scripts, tools, tests and the publishing scripts". The frontmatter of `.claude/rules/identity.md` names five `docs/` subtrees, the file itself and four command names.
- **Reproduced** with `scripts/hooks/rules_inject.py`, fresh state per call, fabricated PreToolUse payloads against the scratch clone:

| tool call | rules delivered |
|---|---|
| Write `scripts/new_tool.py` | coding.md |
| Write `tests/security/test_new.py` | coding.md, testing.md |
| Write `tools/probes/x.py` | performance.md (its one pointer line), coding.md |
| Write `docs/journal_fragments/2026-10-14_x.md` | journal.md |
| Write `docs/performance/x/summary.md` | performance.md |
| Write `docs/reviews/new.md`, `docs/research/x.md`, `docs/adrs/ADR-999.md`, `docs/archive/journal/2026-10.md`, `docs/handoffs/x.md` | identity.md, held once |
| Bash `echo > docs/reviews/x.md`; Bash `cat /c/.../docs/research/x.md`; PowerShell `Set-Content docs/adrs/x.md` | identity.md |
| Bash `python scripts/scrub_public_identifiers.py --check`; `rotate_log.py`; `hf_publish.py preflight` | identity.md (by command) |

- **Incidence:** of the files added on main in the last 30 days that are outside `USER_SCOPE`, still present and carry the operator name (67), the frontmatter covers 46: `docs/reviews` 25, `docs/research` 15, `docs/adrs` 4, `docs/archive` 2. Uncovered: `scripts` 6, `tests` 5, `docs/governance` 2, `docs/sprints` 2, and one each in `.claude/agents`, `.claude/rules`, `docs/design`, `docs/runbooks`, `services/policy_agent`, `tools/operator`. The 16 untracked carrying files in the working tree right now (other sessions' in-flight work) are all under `docs/reviews` (15) and `docs/research` (1), so those sessions will be shown the rule on their first write.
- **Why the lock misses it:** `test_rules_index_and_directory_agree` compares file names, not the index sentence. An always-loaded file now asserts a control that is not in place.

### R4-5. LOW. An innocent branch is blamed for "added to the baseline on this branch" when main shrank behind it

- **Where:** `ratchet_violations` (`:252-255`): any key in the branch's list that is absent from main's copy is reported as added by the branch.
- **Reproduced:** a branch cut from main, then main cleans a listed file and drops it, then the branch (which changed nothing related) runs `check()`: `docs/m.md: added to the baseline on this branch; the list never grows`.
- **Cost:** a red gate on a branch that did nothing wrong, with a message that names the wrong cause. The remedy, merging main, is one the branch needs anyway, which is why this is LOW. Concurrent branches are the norm on this tree.

### R4-6. LOW. Shapes the lock does not see and the HONEST LIMIT does not name

Run through `find_hits`, `count_user_hits` and the rewrite in the scratch clone:

| shape | lock | ratchet count | rewrite |
|---|---|---|---|
| operator after an octal colour code (`\033[32m`, the shell-script and Python-literal form) | not seen | 0 | untouched |
| operator after a bash `\e[32m` | not seen | 0 | untouched |
| host after an octal colour code | seen (substring rule) | n/a | cleared |
| JSON escape inside percent-encoding (`%5Cu00..`) | not seen | 0 | untouched |
| UTF-16 inside percent-encoding, double percent-encoding, HTML entity inside percent-encoding, HTML entity inside a JSON escape | not seen | 0 | untouched |
| 8-bit CSI byte (`\x9b32m`) before the operator | not seen | 0 | untouched |
| gzip nested five deep (four is seen) | not seen | 0 | cleared |
| HTML hex entity without its semicolon | not seen | 0 | untouched |
| operator with a letter glued (stated limit); zero-width, soft hyphen, line break, base64, hex, fullwidth letters, zip, PNG chunk (stated limits) | not seen | 0 | untouched |
| mixed case, digit glue, UTF-7, HTML decimal entities with leading zeros, every letter `\u`-escaped, every byte percent-encoded, JSON-escaped ANSI inside UTF-16 or gzip | seen | 1 | as R4-7 |

- **Incidence:** 0 of 4,002 tracked files contain a literal `\033[` or `\e[` sequence, and 0 carry a name directly after an escaped colour code of any form. The nested family is covered by the limit's general sentence ("two escaping schemes nested"); the octal and `\e` colour codes are not nested and are not named.

### R4-7. LOW. Two "seen but not rewritten" shapes the prose does not describe that way

- `scripts/identity_lock.py:25` says the scrub rewrites the "percent-encoded" shape. A name percent-encoded byte by byte (`%6D%72...`) is seen and left in place (residual, exit 1); what the rewrite handles is a percent-escape beside the name. 0 tracked files.
- A `.tar.gz` member carrying the name is seen by the lock (raw view) but the rewrite reads the tar as UTF-16 (a header is mostly NULs, so `looks_utf16` says so) and leaves it; the run exits 1 for a hand edit. 0 tracked `.tar.gz`, `.tgz` or `.zip` files.

### R4-8. LOW, hypothesis-grade for real profiles. A USERPROFILE ending in a backslash corrupts `--operator-home` in all three launchers

- **Reproduced at parse level** (the exact source expressions, CreateProcess, argv-echo stub): `C:\Users\someone\` arrives as `C:\Users\someone"`; a drive-root profile `C:\` arrives as `C:"`. In `run_arm.py` the quote also swallows the next argument, so `--operator-home` receives `C:\Users\someone" --listener-port 5` and the listener port falls back to its default.
- **Incidence:** no profile on this machine ends in a backslash; Windows profiles never do. Spaces, `$` and `%VAR%` in the path are passed intact.

## Verified holds (round 4)

- **Tree state:** the lock and the launcher lock pass on the real checkout at a74a2b4e (40 + 2 = 42 passed, 69.8 s; `test_check_mode_is_clean_on_the_tree` 34.3 s, `test_tree_is_clean` 20.0 s, `test_ratchet_holds_on_the_tree` 13.7 s). `--check` reports 0 findings in 4,002 tracked files, exit 0, and prints the first-landing note (50 s).
- **The first landing is honest:** every one of the 557 listed counts equals the file's `count_user_hits` and its plain-text count; the baseline differs from a3e0b296 by the one removal of `BUILD_JOURNAL.md` (3,861 to 3,860).
- **The two hand edits** (`BUILD_JOURNAL.md`, `docs/reviews/code-review-1665-9b-int8-round2-2026-10-04.md`): the removed lines carry the names, the added lines carry neither.
- **Rewrite logic unchanged:** between a3e0b296 and ec11efd6 the scrub's diff touches `gzip_bytes`'s docstring, the unreadable marker, the ratchet and `main()`; `host_re`, `user_re`, the boundaries and `scrub_text` are byte-identical, so round 3's reproduction and no-over-scrub results carry over. A rewrite run on the clean clone at a74a2b4e rewrote 0 files, exit 0, log with interpreter and zlib lines.
- **No false positive with teeth:** fourteen ordinary legitimate shapes pass `check()` and the lock: a docs file quoting `%USERPROFILE%` and `$env:USERPROFILE`; a fixture with a fake SID and fake names; a journal entry with `__HOST__` and `__USER__`; a file name with the operator name inside a longer word; a secret row at `C:\Users\__USER__\.ssh`; an in-scope record naming `%USERPROFILE%`; a listed file rewritten with CRLF; a listed file where one plain occurrence becomes JSON-escaped or percent-encoded (count flat); a gzip gate log; a long hex digest; `WORKSTATION\operator`; a transcript with raw ANSI codes; a UTF-16 file with a BOM. The four shapes that fire are the designed ones with the designed message: a file name with the name as a hyphenated part; a new review quoting a listed file's working path; a new note naming the runtime data directory; a listed file fully cleaned but still listed.
- **Fail-closed reads that do fail:** a single-branch clone, an `origin/main`-only clone, and an unreadable `main:` copy each produce a ratchet finding; a linked worktree resolves `main` through the shared refs and catches a raise.
- **Lock mutations, whole lock file plus the launcher lock each time, in the scratch clone:**

| mutation | whole lock file + launcher lock, `-x` (stops at the first failure) |
|---|---|
| `check()` returns `[]` | 1 failed: `test_toggle_check_mode_reports_every_class` |
| `ratchet_violations()` returns `[]` | 1 failed: `test_toggle_check_mode_reports_every_class` |
| `reference_baseline()` always FIRST_LANDING | 1 failed: `test_toggle_branch_comparison_reads_the_reference_and_fails_closed` |
| `reference_baseline()`: an unresolvable ref reads as FIRST_LANDING | 1 failed: `test_toggle_branch_comparison_reads_the_reference_and_fails_closed` |
| `views()`: no JSON or HTML decoding | 1 failed: `test_toggle_user_shape_is_found_in_scope_and_not_outside[json-newline-escape]` |
| `_readings()`: raw only (no ANSI strip, no percent decode) | 1 failed: `test_toggle_user_shape_is_found_in_scope_and_not_outside[ansi-prompt]` |
| `count_user_hits` reads raw bytes only | 1 failed: `test_toggle_ratchet_every_way_the_footprint_could_grow` |
| `_host_token_hits`: no substring (glue) match | 1 failed: `test_toggle_host_shape_is_found_and_clean_twin_is_not[glue-digit]` |
| `live_names_are_pinned()` always true | 1 failed: `test_rewrite_refuses_when_the_live_names_are_not_pinned` |
| `scrub_bytes`: unreadable gzip member kept silently (R3-8 regression) | 1 failed: `test_scrub_reports_a_gzip_member_it_cannot_rewrite` |
| `main()`: residual shapes not reported | 1 failed: `test_toggle_escaped_and_encoded_shapes_are_seen_and_reported` |
| `hf_publish`: digest file-name check removed | 1 failed: `test_publisher_refuses_a_file_name_carrying_the_identity_under_any_account` |
| `rotate_log`: refusal removed | 1 failed: `test_rotation_refuses_to_move_an_entry_carrying_the_name` |
| `run_arm_e`: `--operator-home` dropped (the pre-fix file) | 1 failed: `test_containment_arm_launchers.py::test_every_launcher_passes_the_operators_home` |
| `arm_payload`: `--operator-home` made optional | NOT RUN: the launcher lock's second test would then execute the payload (secret reads, egress attempts) instead of asserting exit 2; by reading, it fails on the exit code |

  Every executed mutation is caught by a test whose docstring names that failure. The first battery ran in `r4/clones/tip` and missed eight anchors (the clone checks out CRLF); those eight ran again in `r4/clones/tip2`, 22:02 to 22:11 local, after the first battery had restored its files.

- **Launcher command lines:** spaces, `$` and `%VAR%` in USERPROFILE reach the payload intact from all three launchers (R4-8 for the trailing backslash).
- **Disposition:** `scripts/verify_disposition.py` on the round-3 record: PASS, 8 ok of 8.

## Suites and runs (round 4)

LOCALAPPDATA was redirected to the reviewer's scratchpad for every pytest run. Review scripts live under the scratchpad `r4/bin/` and ran with `-I`.

| what | where | result |
|---|---|---|
| `test_no_host_identity_in_tree.py` + `test_containment_arm_launchers.py` | real checkout, a74a2b4e, 21:37 local, no other reviewer load from this session yet | 42 passed in 69.8 s |
| `scrub_public_identifiers.py --check` | real checkout, 21:48 local, while the scratch mutation battery was running | 0 findings in 4,002 tracked files, exit 0 |
| doctrine rules, doctrine freshness, rules corpus, disposition discipline, SID lock, evidence bundle, `test_hf_publish.py` | real checkout, 21:53 local, concurrent with the scratch battery | 369 passed in 181 s |
| chained-view shapes (39), reference edge cases (9 regimes), hook payloads (19), launcher parse (6 profiles x 3 launchers), legitimate shapes (18), mutant table (31), headroom and baseline diff, 30-day coverage, headroom drift, rewrite run | scratch clones of a74a2b4e | as tabled above |
| lock mutations | scratch clone of a74a2b4e | 14 of 15 mutations executed (two batteries, 21:52 to 22:11 local, clone restored byte-for-byte after each; the 15th not run, see the table); every one caught |

Not run, and why: the full standing gate (other review agents share this machine); every arm and the probe payload (`arm_payload.py` runs secret reads and egress attempts, so the mutation "make `--operator-home` optional" was not executed; by reading, the launcher lock's second test would then run the payload instead of asserting exit 2); the journal rotation on the real `BUILD_JOURNAL.md` (the refusal is exercised on a scratch journal only); the Windows Filtering Platform, accounts and anything elevated.

Attack-list items not executed: none beyond the payload mutation above. "Nested gzip" was run to depth five; "split across a line break" and "zero-width" were run and are stated limits.

## Merge read (round 4)

- **Nothing blocks.** Every round-3 blocker is fixed and holds under execution; the tree is clean in every view the lock reads; the first landing carries no headroom; the publisher's own gate is independent of all of this.
- **Fix R4-1 and R4-2 before the ratchet's reference is described as fail-closed or as catching merged growth on main.** Today the branch-side comparison is the control that works; the on-main one is a one-commit window with two silent regimes.
- **Fix R4-3 or restate the rule:** either the count follows the file down (a listed count above the file's count is a finding), or the doctrine says the ceiling is the lock-day count and nothing else.
- **Fix R4-4 in CLAUDE.md** (an always-loaded sentence asserting delivery that does not happen) or widen the frontmatter; the index test should compare more than names if the sentence is to be trusted.
- **R4-5 to R4-8 do not block.** R4-6 belongs in the HONEST LIMIT.

VERDICT LINE: PASS at a74a2b4e.

# Round 5 (2026-10-15)

VERDICT: PASS at d44738fe (fix pass fe2e2dbd, disposition d44738fe), on one merge condition: land the branch with `git merge --no-ff` (R5-1). Every round-4 fix holds under execution and every new lock fails when its fix is reverted. No identifier reaches the public snapshot through anything found here.

Reviewed d44738fe on `feat/1765-scrub-public-identifiers` (main 3e8fa63e, the fork point; the branch is 19 commits ahead and fast-forwardable). Read: every byte of `git diff a6534a01 d44738fe` (13 files). All execution ran in three scratch clones under the reviewer's scratchpad (`r5b` = branch tip with a local main at 3e8fa63e; `r5` = main with the branch merged `--no-ff`; `r5ff` = main fast-forwarded to the branch). The real checkout was only read; nothing in it was modified except this file. LOCALAPPDATA redirected for every pytest run. No arm and no probe payload ran; nothing elevated. Identifiers written as "the operator name".

## Round-4 fixes, re-verified at d44738fe

| finding | holds? | evidence |
|---|---|---|
| R4-1 window reference | yes (but see R5-1, R5-5) | `test_toggle_main_reference_catches_growth_that_merged_without_a_gate` passes; `WINDOW = 1` in source fails it. A `--no-ff` merge of this branch reads one version on main (557 files) and `--check` on the merged main is 0 findings in 4,003 files (1 min 58 s). Reference read cost 0.12 s at the branch tip. |
| R4-2 shallow / unborn / detached | yes | Test passes; disabling the shallow read fails it; mapping unborn to FIRST_LANDING fails it. Detached at main's tip reads main's window and finds a raise. Detached with no `main` ref is "main does not resolve", a finding. This closes the round-4 silent pass. |
| R4-3 count follows the file down | yes | Test passes; replacing `elif n < baseline[r]` with `elif False` fails it (assertion, not setup). Tree at tip: 0 findings, so no listed count currently exceeds its file. |
| R4-4 delivery widened | yes, lock partial (R5-2) | Reverting identity.md's frontmatter to a6534a01 fails 2 tests. The six widened hook expectations pass. Delivery is once per agent: this session received identity.md once across many docs/scripts/tests touches, so no flood. |
| R4-5 main's change named | yes, one gap (R5-3) | Test passes; passing `fork=None` fails it. |
| R4-6 / R4-7 HONEST LIMIT | true against code | Run through `find_hits` + `scrub_bytes`: byte-by-byte percent-encoded name seen, not rewritten; `.tar.gz` member seen, not rewritten; percent-escape beside the name, ANSI separator and plain form seen and rewritten clean. |
| R4-8 trailing backslash | yes, lock partial (R5-4) | 14 launcher tests pass. Independent CommandLineToArgvW parse of `argv_tail` and of the evaluated `$arg` line (pwsh) for 5 profiles beyond the test's six (`C:\Users\a b\`, UNC `\\srv\share\`, three trailing backslashes, space plus two, `$1` in the path): all intact, next argument intact. Reverting the ps1 line fails 4; gutting `argv_tail` fails 3; dropping the run_arm.py call site fails 1. |

Disposition verifier: PASS 8/8. `scrub_public_identifiers.py --check` at the branch tip: 0 findings in 4,003 tracked files, exit 0 (first landing noted). identity.md register: rules plus provenance parentheticals only; no narration.

## Round-5 findings, most severe first

### R5-1. MEDIUM. A fast-forward merge of this branch turns main's gate red until a code fix
`scripts/scrub_public_identifiers.py:224-226` (`_parse_baseline` failure in `reference_baseline`). The branch's own history holds 373e9685, whose baseline stores `files` as a list (the pre-dict schema). Fast-forwarded, that commit is on main's first-parent line inside the 20-version window, so every later run on main returns "373e968585:scripts/identity_user_baseline.json is not a readable baseline" and `check()` reports "the branch comparison did not run". It stays that way for 20 more baseline versions, and none of those can pass the gate meanwhile. A fast-forward also makes every intermediate development version of a branch part of main's reference, so a count that rose during development reads as growth on main.
Reproduced: `r5ff` (`git merge --ff-only origin/feat/1765-scrub-public-identifiers`), `reference_baseline(Path('.'))` -> `(None, '373e968585:... is not a readable baseline')`. The same check on `r5` (`--no-ff`) reads 557 files, and `--check` is 0.
Incidence: the branch is fast-forwardable now (merge-base == main). Fast-forward history on main: 1 single-parent first-parent commit out of 78 since 2026-09-25, and 46 out of the last 300.
Fix: land with `--no-ff`. In code, read the legacy list shape (`files` is a list) as "no version", the same way a deletion is read, and lock it with a fast-forwarded scratch history. Any other unreadable version must stay a finding.

### R5-2. LOW. The index-claim lock is a prefix match, so it passes the exact round-4 defect for docs
`tests/security/test_doctrine_rules.py:225` (`g.startswith(word + "/")`). Any glob under `docs/` satisfies the claim "delivered on docs", including `docs/reviews/**` alone, which is the shape round 4 found.
Reproduced: in `r5b`, with `- "docs/**"` replaced by `- "docs/reviews/**"`, `test_rules_index_delivery_claims_match_the_frontmatter` PASSES. Only the real-hook test fails, and only because its six-path sample happens to include `docs/governance/x.md`. The disposition row says the test "compares the directories CLAUDE.md claims against the rule's path globs"; it compares prefixes.
Fix: require the glob `<word>/**` itself (or a glob matching every path under it) for each claimed directory.

### R5-3. LOW. "main dropped this file" absolves a branch that also raised the count
`scripts/scrub_public_identifiers.py:293-294`. The dropped-entry branch has no `n <= fork[r]` test (the lowered-count branch has one).
Reproduced: `ratchet_violations(root, [], ud, {"docs/x.md": 5}, {}, "", {"docs/x.md": 3})` returns "...main dropped this file from the baseline after this branch was cut; merge main (not a growth by this branch)" for a branch that raised 3 to 5. The gate still fails, and after main is merged the entry reads as "added on this branch", so this costs a misleading message, not a pass.
Fix: apply the same `n <= fork[r]` condition before naming main's change.

### R5-4. LOW. run_arm.py's real command line is locked by a substring, not a parse
`tests/security/test_containment_arm_launchers.py:96-98` parses a string the test builds itself (`x.exe --operator-home "{run_arm.argv_tail(profile)}"`), not `run_arm.main`'s `cmd`. The only lock on the call site is `"argv_tail(" in cmd` (lines 39-40).
Reproduced: in `r5b`, call site changed to `{os.environ["USERPROFILE"]}{argv_tail("")}` -> 14 passed. Arm E and arm A are parsed from their real expressions, so this applies to run_arm.py only. The disposition's "evaluate the real expressions" overclaims for this one launcher.
Fix: move `cmd` construction into a function and parse its output, as `build_config` is parsed for arm E.

### R5-5. LOW (hypothesis, not reproduced). WINDOW is a fail-open horizon
`scripts/scrub_public_identifiers.py:186`. A growth merged ungated becomes the reference after 20 later baseline versions. One fast-forward of a branch carrying 20 or more baseline commits does it in a single step, which compounds R5-1. Not exercised at a scale of 20.
Fix: a no-fast-forward rule removes the one-step case. Otherwise, state the horizon in identity.md's HONEST LIMIT.

## Attacked and not broken

Raise-then-lower inside the window (the minimum keeps the lowest). Delete-then-re-add (test plus toggle). A branch adding an entry main never had. A detached HEAD at main's tip. Shallow and unborn checkouts. Trailing backslashes in 11 profile shapes across all three launchers. The prose of the HONEST LIMIT against the code. Hook-test widening. Rules-corpus hash (doctrine suite green).

## Suites and runs (round 5)

| what | where | result |
|---|---|---|
| test_no_host_identity_in_tree + test_containment_arm_launchers + test_doctrine_rules | `r5b` at d44738fe, 2026-10-15 ~00:20 local, other reviewers active | 142 passed in 193 s |
| `--check` | `r5b` (branch tip) and `r5` (`--no-ff` merged main) | 0 findings / 4,003 files, both |
| toggle-offs (11) | `r5b`, restored byte-for-byte after each | every fix's named test fails off. Exception: the R5-4 variant |
| verify_disposition.py, round-4 disposition | `r5b` | PASS 8/8 |

Not run: the full standing gate; any arm or payload; anything elevated.

## Merge read (round 5)

- Block only on the merge mode: `--no-ff`, or fix R5-1 first. A fast-forward reddens main's gate with no in-band remedy.
- R5-2 to R5-5 do not block. Each one is a lock that is too narrow or a message that misattributes the cause, and the gate still fails closed in every case.

VERDICT LINE: PASS at d44738fe, on the condition of a `--no-ff` merge.
