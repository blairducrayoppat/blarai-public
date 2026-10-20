# Disposition: independent reviews of the case-4 probe and admin driver (#1764)

**Reviews:** `review-1764-case4-probe-r1-2026-10-19.md` (FAIL), `review-1764-case4-probe-r2-2026-10-19.md` (round 2 PASS, round 3 PASS appended),
`review-1764-case4-driver-r1-2026-10-19.md` (FAIL), `review-1764-case4-driver-r2-2026-10-19.md` (round 2 PASS with corrections, round 3 PASS appended).
Reviewers: independent sessions, non-elevated through `run-limited.ps1`, engine never opened; neither wrote a fix.
**Author of the code and of this disposition:** the case-4 session (builders B1 and B2 under its brief).
**Outcome:** probe PASS at `21cb384d` (NcoProbe.cs 28bc05d5), driver PASS at `1ed25f50` (spike-nep5-c4-driver.ps1 47fcd179, corpus f9830409).
Nothing in this record ran live; the live run is the Lead Architect's, per `nco/RUN_SHEET.md`.

```disposition
P1-1 every group SID's resolved name was recorded; the Microsoft-account group resolves to the operator's e-mail, which the scrub does not rewrite | FIXED | 8387e047 - names recorded only for well-known SID families; user SID without a name; least-data identity row on the real token
P1-2 0x80320028 classed as denied; it is FWP_E_OUT_OF_BOUNDS, not an access-denied code | FIXED | 8387e047 - denied is 0x5 and 0x80070005 only; README amendment 6 says the earlier label was wrong; driver mirror fixed at 574712d1
P1-3 a WFP call that throws rendered as rc 0 class succeeded exit 0 | FIXED | 8387e047 - calls behind an interface; a throw is class other with the text, overall incomplete exit 11; eight fake-sequence rows
P1-4 no pre-engine check that the principal matches the condition; a mis-elevated E run would write to the engine | FIXED | 8387e047 - exit 12 wrong_principal before FwpmEngineOpen0 for F/E not as nco-probe and S/A as nco-probe
P1-5 a both-sided swap of the layer constant to IPv6 passed every check | FIXED | 8387e047 - layer compared with a GUID built from parts plus a source scan for the IPv6 layer
P1-6 source scans missed #elif, ExpandEnvironmentVariables and whitespace forms; README overclaimed | FIXED | 8387e047 - scans as functions with 17 teeth rows; README states what they show
P1-7 a filter left behind collides with the next run and the run sheet had no stop on exit 8 | FIXED | 8387e047 and 6f520345 - STOP line on exit 8 and the run sheet's stop-lines section
P1-8 a comment and a refusal message misdescribed the code | FIXED | 8387e047 - toggle comment and folder-as-proof refusal text corrected
P1-9 scrubbing record copies in --dir mode would rewrite the fabricated stale SID as a machine placeholder | FIXED | 892701dc - sanitisation route fixed in SPEC Part 3: rewrite_sid_domain.py on tracked copies, never the scrub's --dir mode
P2-1 add 0 with delete denied and both read-backs denied ended exit 0 with no STOP line | FIXED | 21cb384d - filter_possibly_left_behind, exit 8, STOP line; five fake rows incl. H12 and H13
P2-2 exit 12 printed no STOP line | FIXED | 21cb384d - STOP: wrong principal line on stderr and in operator_action
P2-3 three ordinary forms evaded the process-start scans | FIXED | 21cb384d - psi scoped to RunChild, qualified constructor, instance Start, 22 teeth rows
P2-4 the user-condition GUID was pinned only by the file itself | FIXED | 21cb384d - condition.is_ale_user_id built from parts; MB5 now fails
P3-1 SPEC and README amendment 5 still said an unreadable delete read-back exits 0 | FIXED | 6f520345 - SPEC amendment reworded; README amendment 12 carries the rule
P3-2 the run sheet quoted wrong_principal but the exit-12 line reads STOP: wrong principal | FIXED | 6f520345 - stop on any line starting with STOP:
D1-1 a record was counted under its condition without checking the token state the condition names | FIXED | 574712d1 - per-condition token-state validation, invalid-by-token-state class, elevation_refused class; one wrong-token row per condition
D1-2 the operator's limited token and nco-probe can rewrite any record in drop undetectably | REJECTED | the records are the operator's own measurement on his own machine taken with him at the keyboard, the ACL that lets him and the account write their records is the mechanism of the measurement, -Collect records every file's sha256 and he sees every record in the console it was printed to, so a consistent in-window edit is an accepted residual documented in the scripts README (D2-3 corrected the README's earlier overclaim)
D1-3 -Prepare exited 0 and printed PREPARED when the prepare record could not be written | FIXED | 574712d1 - PREPARED only after the record is on disk and re-read; a write failure rolls back and exits 2
D1-4 an exception before the add escaped -Prepare as exit 7, the code reserved for an unverified rollback | FIXED | 574712d1 - exit 2 with the manual rollback printed; 7 only for a rollback that did not verify
D1-5 the no-account-lifecycle lock missed 11 of 13 ordinary forms | FIXED | 574712d1 and 1ed25f50 - forms added, lock tables and plants moved to case4-lock-corpus.json (schema v2, 248 alternatives each with its plant)
D1-6 the seams lock did not see halfset.exe by path, file creation or deletion, or takeown | FIXED | 574712d1 - forms added; aliases added at 1ed25f50
D1-7 the per-condition n included engine-open failures | FIXED | 574712d1 - open failures listed separately and never counted
D1-8 the wrong-principal STOP was skipped for misnamed files | FIXED | 574712d1 - misnamed files are a listed finding, STOP-checked
D1-9 -Finish deleted records in a sub-folder of drop without copying them | FIXED | 574712d1 - sub-folders refused
D1-10 the S and A lines the driver printed differed from the run sheet | FIXED | 574712d1 - the driver prints the sheet's lines and checks them against RUN_SHEET.md
D1-11 the prepare record was selected by a local-time file name | FIXED | 574712d1 - the newest record is chosen by its own `at` field (the file name keeps the local stamp)
D1-12 the README's owner claim did not reproduce | FIXED | 574712d1 - wording corrected to what reproduces
D1-13 two checks could not fail | FIXED | 574712d1 and 1ed25f50 - clock-order and purity checks made able to fail
D1-14 the run sheet promised a matrix hash the driver never wrote | FIXED | 574712d1 - -Prepare records the sha256 of the live matrix bytes
D1-15 the Part D profile-folder check was an unrun hypothesis | FIXED | 574712d1 - -PartD reads the ProfileList key and nco-probe.* folders
D2-1 elevation_refused was judged on reaching the engine instead of on the token | FIXED | 1ed25f50 - contradicted by any E record from the account with elevation_type 2; the two self-test checks corrected; three reviewer cases as rows
D2-2 the corpus was parsed by every mode, so a missing corpus stopped -Finish, -Collect, -Check, -DryRun and -PartD | FIXED | 1ed25f50 - parsed only under -SelfTest; live modes refuse through the proof hash
D2-3 the README claimed the probe prints each record's sha256, which it does not | FIXED | 1ed25f50 - README states what exists: -Collect hashes each file, the LA sees each record in the console
D2-4 removing alternatives inside a corpus pattern passed the self-test, so -WriteProof would bind a weakened corpus | FIXED | 1ed25f50 - every alternative carries its plant, per-alternative teeth, pinned minimum counts, duplicate JSON keys refused
D2-5 the lifecycle lock missed [Diagnostics.Process]::Start of net.exe and fully qualified AccountManagement types | FIXED | 1ed25f50 - both forms caught; check text states its limit; WinNT:// comment-stripper defect fixed
D2-6 seam gaps: instance-member and stream file writes, cmdlet aliases | FIXED | 1ed25f50 - 22 aliases and wevtutil added; instance-member and stream writes recorded as an accepted residual in the README (none in the code; the seams inventory confirms every machine call sits inside a seam)
D2-7 the F rule assumed the group gives a split token; elevation_type 1 would be a legitimate measurement | FIXED | 1ed25f50 - F accepts elevation_type 1 or 3 and records which; only 2 invalidates
D2-8 the -ElevationRefused note could carry the operator's e-mail | FIXED | 1ed25f50 - a note containing @ or MicrosoftAccount is refused
D2-9 acl-plan-pure missed instance-member calls | FIXED | 1ed25f50 - instance calls named like file writes flagged; .Create() plant found
D2-10 prose mismatches | FIXED | 1ed25f50 - four wording fixes
D2-11 all three driver generations write the same proof file name | REJECTED | the earlier generations no longer exist on disk under a runnable name, the proof binds the driver by its own name and hash so a stale copy's proof is refused by the current driver, the SPEC names case4-selftest-proof.json and renaming would diverge from it, and the behaviour fails closed as the reviewer records
R3-1 the driver pins how many alternatives each pattern has, not which; a deliberate consistent swap of alternatives and plants passes | REJECTED | the corpus is a data file of the operator's own tool bound by hash in the proof that a reviewed self-test writes, it is reviewed with the driver, accidental drift and removal are caught by the per-alternative plants and pinned minimums, and a deliberate consistent edit by the only person who can write the admin-only live folder is outside the threat the lock exists for (the lock is a tripwire against an author mistake, not a defence against the operator)
R3-2 an E record by the account with an unreadable elevation type still lets the note count | REJECTED | the record itself is invalid and -Collect exits 4 for that batch, so the note cannot be reported as the E result without the invalid record being seen and the batch re-run, which is the fail-closed outcome
R3-3 a few more forms are missed (a ProcessStartInfo assigned after construction, mkdir and md, > redirection) | REJECTED | none appears in the code as the reviewer confirms, the README states the lock's limits, and the seams inventory is the control that every machine call sits behind a seam
R3-4 the note accepts AzureAD\Name and an address spelled out in words | REJECTED | the note is written by the author session, never by the operator, under the least-data rule the author applies by hand, and the @ and MicrosoftAccount refusals are tripwires for the one shape the identity scrub cannot rewrite
```

## Findings the reviews returned CLEAN (recorded so a later pass does not re-litigate them)

- Probe: 34 arming-refusal attempts incl. timestamp, GUID and size boundaries; the shipped exe ignores both toggle variables; the self-hash holds
  for a renamed copy and a symlink; struct layouts and the security descriptor match the proven spike; the call order is open, add, get, delete,
  get, close with the real implementation the only engine path; the least-data identity output carries no e-mail, user name or host.
- Driver: the plan adds only the provider and S2; the proof is invalidated by a one-byte edit of each bound file incl. the harness proof and the
  corpus; the planned DACLs read back exactly on a real folder; a junction planted in drop by the limited token redirects neither the ACE removal
  nor the tree delete; 512 generated probe records are all accepted by the validator; the standing scans (tracker references, operator name,
  machine SID, the launch verb) are clean on every file.
