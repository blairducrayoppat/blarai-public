# Case 4 as run: provenance of the records in this folder

Two runs on 2026-10-20 (times -04:00, the machine's clock) from the admin-only live folder `C:\ProgramData\BlarAI\trackb-live`; the launch lines are
`../RUN_SHEET.md`, typed by the Lead Architect; the account lifecycle (create, enable, remove from the group, delete, delete the profile) and, in the
second run, the scheduled task and the batch-logon right (create, run, delete, remove) were his, in Windows' own tools. Windows 11 Pro build
26200.9711; Bitdefender present (two file-level scan exceptions for the driver script, see `../SPEC.md`). The first run (00:48 to 01:43) measured F, S
and A and found condition E unreachable through the elevation prompt; the second run (09:28 to 11:12) measured E through the scheduled-task route of
RUN_SHEET step 4b, approved by the Lead Architect that morning. The table below is the first run's; the second run's section follows the file table.

| Item | Value |
|---|---|
| Probe exe `ncoprobe.exe` sha256 (raw) | `4fde1ad6db744fa289b65eb6f639628cd1f04ead6f3b5e6db247fcdc3a0e14d4` |
| Probe source `NcoProbe.cs` sha256 (LF; equals raw) | `28bc05d583135c446ae5dff073907b42c855e522123ba7106c76ff185a42f794` (commit `21cb384d`; review PASS rounds 2 and 3) |
| Driver `spike-nep5-c4-driver.ps1` sha256 (LF) | `47fcd179b28f15b6deb9d9bfeb41ee501f7e43ee8824364c2bc757707f6c031a` (commit `1ed25f50`; review PASS rounds 2 and 3); the live copy is the CRLF form |
| Lock corpus `case4-lock-corpus.json` sha256 | `f98304092c2e4ac06feba76cbcc5f9c0bb86fea4f8d0aed7c9a8c4b70b3f97bc` |
| Driver proof | `case4-selftest-proof.json`, written 2026-10-20 00:47:44 -04:00 after 144 checks, 24 tags, probe runner 215 checks |
| Probe proof | `nco-probe-live.json`, written 2026-10-20T04:48:52Z by `-Prepare`, sha256 `77f7b12630b978ebacb78b4b3819d1fde84536681eb30632bcd58819d9e5322b` |
| Live matrix bytes (the standard-token control) | sha256 in `case4-prepare-20261020-004848.json` (`live_matrix_files`); they differ from the repository copy, whose test-account SID constant is the placeholder |
| Test account | `nco-probe`, relative id 2250, local, member of Network Configuration Operators only (plus Users); SID domain sanitised in these copies |
| Stale SID (the filter condition; no such account; fabricated, not sanitised) | `S-1-5-21-17630000-17630001-17630002-91763` |
| Engine access list | read by `netsh wfp show security type=engine` at `-Prepare` and `-Finish`: identical; the group's ACE `(A;;0x307ff;;;NO)` present |
| Cleanup | `-Finish`: probe key, library keys, S1/S2/S3 and the provider removed by key; sweep clean, export 0 hits; drop ACEs removed; the public folder removed at 01:43 after the operator closed the consoles that sat in it; matrix `-Check` 20 (an exit code only: the matrix's `-Check` writes no record); `-PartD` 20 (account absent, group empty, ProfileList entry absent, no profile folder) |

Timeline: `-Prepare` 00:48:45 to 00:48:52; F runs 01:05:15, 01:14:00, 01:14:24, 01:14:40; E attempts cancelled at the credential prompt (four);
S runs 01:21:45 to 01:21:48; A runs 01:22:40 to 01:22:43; `-Collect` 01:22:58 (10 valid, 0 invalid); `-Finish` 01:23:12 (engine verified; the folder
delete refused while the consoles were open, exit 7, folder removed by hand at 01:43 once empty and free; its internal collect pass is
`case4-collect-20261020-012313.json`, the file the final record's `collect.record` names); the operator's part C; `-PartD` 01:42:16.

## Files (size in raw bytes as checked out; sha256 of the LF-normalised bytes; after sanitisation)

| File | Bytes (raw) | sha256 (LF) |
|---|---|---|
| `case4-A-20261020-052240-21428.json` | 11560 | `2de60b9a02d29b66afe2c56f891e3351a71b04ecd50880bfc2031e8771da5c2e` |
| `case4-A-20261020-052241-23964.json` | 11560 | `3c6fc24a75a609aceddd3e8755087f9b80da90d0537c6e5fe6a14809df3cfeed` |
| `case4-A-20261020-052242-13572.json` | 11560 | `b5513899d8d8a6a3f87fa0bbdfd4685f613c355c58bf1ebee25606387eb62966` |
| `case4-F-20261020-050515-23756.json` | 10220 | `a19208ce72bbdcd98662d50086857c5425a80c8237d05399b733db4529c8217d` |
| `case4-F-20261020-051400-5880.json` | 10218 | `60363fc2df402d823bf95944323831c2052ff2a9c1a78983182b47029c933105` |
| `case4-F-20261020-051424-25640.json` | 10220 | `3b01382f788b9b39d1932812622021b264c52a2e23e95287c3a5c3eca54b851d` |
| `case4-F-20261020-051440-28652.json` | 10220 | `a494e7f42a8674e33e5fbcbf4dc38a5cd257d76843cae83fd8f0929ec108a198` |
| `case4-S-20261020-052145-19624.json` | 11570 | `8be10f9159e73e147ca1678baa8a5974218e8a806beaad18cee96e226f0c4da0` |
| `case4-S-20261020-052147-18812.json` | 11570 | `170349d6b0ea8826d260633d371d033a542a19be6ce1ec8922a40029a608937e` |
| `case4-S-20261020-052148-15020.json` | 11570 | `67f586a56e5b3180ec51930f3f4359a9da1c6c08f2f00bed4b7769405b5844b0` |
| `case4-collect-20261020-012258.json` | 10091 | `02aa09f160dff02591b50de38de06d183afa8773e5b339176358eb55f1ef8ca0` |
| `case4-collect-20261020-012313.json` (the first run's `-Finish` internal collect; banked 11:1x) | 10131 | `c8f9d7cfc88f04495f3cd46468f95a069139b400c53242ccf004f2c10be25ea5` |
| `case4-final-20261020-012312.json` | 7141 | `990256ae44ce96203a325cc154b3450321508ed127e8233d71cad89237c3b9f7` |
| `case4-partd-20261020-014216.json` | 1193 | `b2efc5f5a9945bde7dfcc777faf7ce632d07821be4393bb55c1099b5bef7ece1` |
| `case4-prepare-20261020-004848.json` | 20243 | `ac2f6ce5c714586ecb71d8c241f484b06a7ee1cce91f605f5464d54f533dca35` |
| `case4-E-20261020-133312-14960.json` (second run) | 10206 | `574427107e3af4984958e78302c4ca79530338a23875963aca74074e7cb3b33a` |
| `case4-E-20261020-133710-25944.json` (second run) | 10206 | `0548d00190b2d60508af4d192e394a6a5e9d8fb1295122c9cd1e2508f26386c8` |
| `case4-E-20261020-134229-11468.json` (second run) | 10206 | `13ff000ebfbd159e9af02485ce78db03579e2c669ffeae90a3b8a0f27c791733` |
| `case4-prepare-20261020-092824.json` (second run) | 20174 | `03a30587a525bc46c636ca8d0693a5aea9f944d305891acd1217758566a79657` |
| `case4-collect-20261020-102824.json` (second run, exit 21, see below) | 3548 | `07f3ac283eb50ea819a6c73a09d6a738d30bd20f6ea4f4f5eb9f9c2f369b20ad` |
| `case4-collect-20261020-102913.json` (second run, exit 0) | 3560 | `e2526c5a549dfb7c41fcb0f87be60e5b033828b1e7c0cec155d1ef69aef8d001` |
| `case4-collect-20261020-102929.json` (second run, the `-Finish` internal collect) | 3682 | `baf5bb475103145f9dc2f2f581426af70e99b51b44e62ee90c56bea18112ff2e` |
| `case4-final-20261020-102928.json` (second run) | 6515 | `7b2fb92387c3bd1059a607a16bb5ffc5ec9e6dd8758c3d1cc417df886c73ddff` |
| `case4-partd-20261020-110756.json` (second run) | 1161 | `4510bcadd3c751313d3e278c44e5f335d914ba57f4718588b80b75bef04f5bf9` |
| `results-summary.json` (both runs) | 19392 | `42c955505e6979a37f14ac14df80bedf09158aa98022d548f0acd5f112d5f7de` |
| `controls/nep5-results-n1-20261019-164952.json` | 67220 | `e8606018968d790753deca32d113e6bec5444eea4a7fbefbbcf0530aebacdb66` |
| `controls/nep5-results-taskcheck-20261019-164908.json` | 6512 | `2b50d439fc871215e1832a31ef52ad4ed81ec4f1c454b074ed2f6bcaf5b13ecc` |
| `controls/remove-20261019-164737.json` | 4700 | `cd5883706790f78381308883b4e7ffaaf77d4de3afe9064cc90ea62a41f6e195` |

Sanitisation: `rewrite_sid_domain.py` (in scripts/; machine account domain to the bundle placeholder; log `docs/reviews/case4-sid-rewrite-log-2026-10-20.md`),
then `scrub_public_identifiers.py` (in scripts/; host and operator names). In the prepare, final and part-D copies the key `text` of every `netsh` output
(the engine and container security descriptors, the group listing) is renamed `netsh_text`, because the bundle lock reserves `text` for model output cut to
100 characters; the values are unchanged. The originals stay in the admin-only out dir `nep5-out\case4\`. The second run's copies went through the
same two steps (logs `docs/reviews/case4-sid-rewrite-log-2026-10-20-b.md`, `docs/reviews/case4-sid-rewrite-log-2026-10-20-c.md` and the public-identifier
scrub logs of 10:45 and 11:18 beside them).

## The second run: condition E through a scheduled task (RUN_SHEET step 4b)

The first run's E attempts showed that Windows' elevation prompt, raised from inside the account's own console, lists only this machine's administrator
accounts and has no field for another name, so the account's full token was unreachable by that route (four refusals, recorded as `elevation_refused`).
On the morning of 2026-10-20 the Lead Architect approved a second route and performed it by hand: the batch-logon right (`SeBatchLogonRight`) granted
to `nco-probe` in Local Security Policy, and a task created in Task Scheduler running as `nco-probe` whether logged on or not with highest privileges,
its action the E line without `--wait`, run three times from the Task Scheduler window. A batch logon is never split, so the token the probe read is
elevation type 1 (default) with the group ENABLED. The driver's E rule was amended first to accept that token (commit `2ef3e009`, review round 4 PASS
WITH CORRECTIONS, corrections `1881f15d`, round 5 PASS), and the amended driver was deployed before `-Collect`.

| Item | Value |
|---|---|
| Driver that ran `-Prepare` (09:28) | the first run's bytes, `47fcd179...` LF (live CRLF copy of commit `1ed25f50`) |
| Driver that ran `-Collect`, `-Finish` and `-PartD` (10:28 to 11:07) | commit `1881f15d`: sha256 (LF) `4c0b559eb47014c6b69d43573d29cf6af8d5bc0784c9a402ad5a273c7c9e3fdd`; the live CRLF copy `18f2262a464c78944fcd2b50a81f1a56ea4d650a50f9096c3fc5bcddd5d5db9b` |
| Driver after the run (the records-owner fix, commit `e4383096`) | sha256 (LF) `c48019a31aab0f1a3a49297fc5d39bc272b53eac0bcc3023e0ad16a2bad92be2`; deployed 11:22, proof rewritten 11:23:44 (148 checks, 25 tags); no live mode has run on these bytes |
| Driver after the pre-merge review (the copies-owner fix, commit `4ebad95c`) | sha256 (LF) `06d63d9764846df0b5038e17d674ed60b84daf8cb3235f1e653308bd050102c1` (live CRLF form `5acc94255ae29edccd22e901470be18bf18451f3d3e579a8f2ca57cf6aa1f95c`, owner Administrators); deployed 13:38:54, proof rewritten 13:40:14 (150 checks, 26 tags); no live mode has run on these bytes |
| Driver proofs | 10:28:16 (146 checks) before `-Collect`; 11:23:44 after the records-owner fix (148 checks, 25 tags); 13:40:14 after the copies-owner fix (150 checks, 26 tags) |
| Probe | unchanged: `ncoprobe.exe` `4fde1ad6...`, `NcoProbe.cs` `28bc05d5...`; a fresh probe proof written by the 09:28 `-Prepare` (its content is the prepare record's `probe_proof`) |
| Live matrix bytes | identical to the first run's (the prepare record's `matrix_sha256`) |
| Account | the same name, re-created by the Lead Architect: relative id 2251 (the first run's account, 2250, had been deleted); SID domain sanitised |
| Engine access list | read at `-Prepare` and `-Finish`: identical; the group's ACE present |

Timeline: `-Prepare` 09:28:24; task runs 09:33:12, 09:37:10, 09:42:29 (clock of each record); `-Collect` 10:28:24 exit 21 (3 valid, 0 invalid, but the
engine enumeration was skipped because the out dir read non-admin-only: a file in it was owned by the writing token's user SID; which file is
unrecorded, and since the 09:28 `-Prepare` had passed with every first-run record in place it was one written after it, the 09:28 prepare record or
the copies this collect wrote into `case4-runs\`; the defect fixed at `e4383096` for the records and `4ebad95c` for the copies; owner corrected by
hand with `icacls /setowner`) and 10:29:13 exit 0 (3 valid, residue readable, nothing left behind); `-Finish` 10:29:28
exit 0 (its internal collect pass is `case4-collect-20261020-102929.json`, named by the final record's `collect.record`; S1/S2/S3, the provider and the
probe key absent, export 0 hits, engine security descriptor identical to the prepare record's, drop ACEs for the account and the operator removed and
read back as SYSTEM and Administrators only, public folder removed); matrix `-Check` 20 (an exit code only: the matrix's `-Check` writes no record);
the operator's part C (task deleted, account removed from the
group and deleted, batch-logon line removed; the profile could not be deleted while its hive stayed loaded from the batch logon, so he restarted the
machine at 10:52 and deleted the "Account Unknown" profile afterwards); `-PartD` 11:07:56 exit 20 (`net user` absent, `LookupAccountName` error 1332,
group empty, ProfileList entry for relative id 2251 absent, no profile folder).

The three E records: elevation type 1 (default), integrity medium-plus (S-1-16-8448), linked token absent (error 1312), session 0, `S-1-5-32-556`
present with attributes 0x00000007 (enabled, enabled by default, mandatory), Administrators absent, `is_expected_account` true; `FwpmFilterAdd0`
0x00000000 (filter ids 537392, 537393, 537394, each read back present), `FwpmFilterDeleteByKey0` 0x00000000 (read back absent), residue absent, exit 0.

By-hand read-only checks after part C (the session, outside the driver, 11:12:31, script in the session's scratch folder; RUN_SHEET 4b item 5): of 327
scheduled tasks none is named with `nco`, `probe` or `case4` and none runs as `nco-probe`; `secedit /export /areas USER_RIGHTS` to a scratch file
(4824 bytes, sha256 `fc781580acede363b21ada19290f55df44480ec19694053ba7c1d4e28edb78c4`, not tracked) reads `SeBatchLogonRight = blarai-coder,
blarai-spike, *S-1-5-32-544, *S-1-5-32-551, *S-1-5-32-559, *S-1-5-32-568` and names neither `nco-probe` nor relative id 2250 or 2251; `HKEY_USERS` holds
no hive for the account; the policy itself was not written.
