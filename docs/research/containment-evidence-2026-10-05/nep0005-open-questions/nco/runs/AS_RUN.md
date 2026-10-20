# Case 4 as run: provenance of the records in this folder

Run on 2026-10-20 (times -04:00, the machine's clock) from the admin-only live folder `C:\ProgramData\BlarAI\trackb-live`; the launch lines are
`../RUN_SHEET.md`, typed by the Lead Architect; the account lifecycle (create, enable, remove from the group, delete, delete the profile) was his, in
Windows' own tools. Windows 11 Pro build 26200.9711; Bitdefender present (two file-level scan exceptions for the driver script, see `../SPEC.md`).

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
| Cleanup | `-Finish`: probe key, library keys, S1/S2/S3 and the provider removed by key; sweep clean, export 0 hits; drop ACEs removed; the public folder removed at 01:43 after the operator closed the consoles that sat in it; matrix `-Check` 20; `-PartD` 20 (account absent, group empty, ProfileList entry absent, no profile folder) |

Timeline: `-Prepare` 00:48:45 to 00:48:52; F runs 01:05:15, 01:14:00, 01:14:24, 01:14:40; E attempts cancelled at the credential prompt (four);
S runs 01:21:45 to 01:21:48; A runs 01:22:40 to 01:22:43; `-Collect` 01:22:58 (10 valid, 0 invalid); `-Finish` 01:23:12 (engine verified; the folder
delete refused while the consoles were open, exit 7, folder removed by hand at 01:43 once empty and free); the operator's part C; `-PartD` 01:42:16.

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
| `case4-final-20261020-012312.json` | 7141 | `990256ae44ce96203a325cc154b3450321508ed127e8233d71cad89237c3b9f7` |
| `case4-partd-20261020-014216.json` | 1193 | `b2efc5f5a9945bde7dfcc777faf7ce632d07821be4393bb55c1099b5bef7ece1` |
| `case4-prepare-20261020-004848.json` | 20243 | `ac2f6ce5c714586ecb71d8c241f484b06a7ee1cce91f605f5464d54f533dca35` |
| `results-summary.json` | 12609 | `7f278eda11620181fb0d5ad28126a759df86f71e5ffeb633bf4fcffe59bc8e66` |
| `controls/nep5-results-n1-20261019-164952.json` | 67220 | `e8606018968d790753deca32d113e6bec5444eea4a7fbefbbcf0530aebacdb66` |
| `controls/nep5-results-taskcheck-20261019-164908.json` | 6512 | `2b50d439fc871215e1832a31ef52ad4ed81ec4f1c454b074ed2f6bcaf5b13ecc` |
| `controls/remove-20261019-164737.json` | 4700 | `cd5883706790f78381308883b4e7ffaaf77d4de3afe9064cc90ea62a41f6e195` |

Sanitisation: `rewrite_sid_domain.py` (in scripts/; machine account domain to the bundle placeholder; log `docs/reviews/case4-sid-rewrite-log-2026-10-20.md`),
then `scrub_public_identifiers.py` (in scripts/; host and operator names). In the prepare, final and part-D copies the key `text` of every `netsh` output
(the engine and container security descriptors, the group listing) is renamed `netsh_text`, because the bundle lock reserves `text` for model output cut to
100 characters; the values are unchanged. The originals stay in the admin-only out dir `nep5-out\case4\`.
