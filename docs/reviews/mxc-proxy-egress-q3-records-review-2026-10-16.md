---
title: "MXC proxy egress, Q3 and variant 4 finishing records: pre-merge review"
status: closed
area: reviews
date: 2026-10-16
---

# Q3 and variant 4 finishing records: pre-merge review

**Subject:** branch `feat/1799-standard-token` at `2de6ae39`: `bebb33da` (two `PERFORMANCE_LOG.md` entries,
`docs/performance/mxc_proxy_egress_standard_token_2026-10-16.json`, `docs/performance/mxc_proxy_egress_variant4_wfp_2026-10-16.json`)
and `2de6ae39` (journal fragment `docs/journal_fragments/2026-10-16_mxc-standard-token-and-wfp-capture.md`, variant 4
post-run disposition). Reviewer: independent, read-only on the records (author != verifier). These records go to main
and to the public mirror, and they feed the upstream maintainer thread.

**Method:** my own extractor over every raw run record of `run-20261016-1` and `run-20261016-2`; my own ElementTree
parse of all 36 run WFP dumps and the 4 control dumps (keyed by `filterKey`); a byte search of both MXC builds'
binaries; a read of MXC source at `525d0f25`; the AppContainer-SID derivation recomputed in Python; Vikunja #1799
c4322-4348 and #1798 c4334-4344; the approval files; `scripts/verify_disposition.py`,
`scripts/scrub_public_identifiers.py --check`, `scripts/research_tracker_lock.py --check`.

## Verdict

**FAIL — one HIGH blocks publication.** Every number in both entries, both JSON files and the fragment matches the raw.
One factual claim about ownership does not hold, and the deferral built on it is wrong in substance.

## Findings

1. **HIGH** (cost: a false ownership statement published into the upstream thread to the people who wrote the code;
   one byte search shows it is false) · `PERFORMANCE_LOG.md:69-70`, `:78`; variant 4 JSON `:103`, `:105`, `:998`;
   journal fragment `:12` · **"None of the eight is from MXC's own binaries" and "owner of the constant
   `S-1-15-2-2397545170-...` package not identified" are both wrong for the two MXC-Loopback filters.**
   - The constant package SID is the AppContainer SID derived from the name `MXC-Loopback`. With the documented
     derivation (SHA-256 of the lower-cased UTF-16LE name, first 28 bytes as seven little-endian uint32),
     `MXC-Loopback` gives `S-1-15-2-2397545170-3775720672-3869633084-1956472232-3059123134-2656009929-3273807654`.
     That matches the filters' `FWPM_CONDITION_ALE_PACKAGE_ID` on all seven sub-authorities. Control: the same
     computation on `microsoft.windowsnotepad_8wekyb3d8bbwe` gives exactly that package's SID in the run records'
     `appcontainer_mappings` (`...-1050576210-...-784472318`). Windows' own `DeriveAppContainerSidFromAppContainerName`
     returned the same last four sub-authorities for both names.
   - `MXC-Loopback` is MXC's own identifier. In `525d0f25`: `base_container_helpers.rs:24`
     `pub(super) const LOOPBACK_NETWORK_PEER: &str = "MXC-Loopback";`, used at `:176` and
     `base_container_runner.rs:3231,3441`; `docs/backends/process-container/networking.md:121-124` says that in proxy
     mode the host-loopback setting "selects both the `networkLoopback` capability and the `MXC-Loopback` peer".
     The ASCII string is in `dl/x64/wxc-exec.exe`, `dl/x64/mxc_ffi.dll` and the arm-B `wxc-exec.exe` (1 hit each).
   - The `Sandbox.{GUID}` pair (keyed to the run package) carries the MXC-Loopback SID in its
     `ALE_REMOTE_USER_ID` descriptor, and the MXC-Loopback pair carries the run SID. The four filters are one
     reciprocal loopback peering between the run container and MXC's named peer. The records describe them as
     unrelated, with the second pair's owner unknown.
   - What still holds: mpssvc (`FWPM_PROVIDER_MPSSVC_APP_ISOLATION`) installs these four, not MXC code, and the
     Tessera string is absent from MXC's binaries. The correct statement is roughly: the four Tessera filters are
     Windows'; the four app-isolation filters are installed by the Windows Firewall service for the `MXC-Loopback`
     peer that MXC names in its process security environment spec (PSEC); the constant SID is that peer's derived
     AppContainer SID. The same overreach is in the post-run review this record follows (0edfd824, verdict paragraph
     and finding 4). The records inherited it; they did not invent it.
   - Also affected: JSON `:103` (snapshot count parenthetical "the Tessera filters are not MXC-named"). The
     MXC-Loopback filters are MXC-named and read 0 only because the snapshot runs before and after the launch.
   - **Reproduced:** `python -c "import hashlib,struct;h=hashlib.sha256('mxc-loopback'.encode('utf-16-le')).digest();print('S-1-15-2-'+'-'.join(map(str,struct.unpack('<7I',h[:28]))))"`
     → `S-1-15-2-2397545170-3775720672-3869633084-1956472232-3059123134-2656009929-3273807654`;
     `grep -c -a MXC-Loopback dl/x64/wxc-exec.exe` → 1. **Incidence:** 12 of 48 filters (2 per run, 6 of 6 runs),
     plus the 12 `Sandbox.{GUID}` filters whose description leaves out the peer.

2. **MEDIUM** (cost: a deferral holds open a question the data already answers) ·
   `docs/reviews/mxc-proxy-egress-variant4-postrun-disposition-2026-10-16.md:21` · **Row F4 is DEFERRED until a new
   capture that "records the AppContainer profile name behind the constant package SID". No capture is needed.** The
   owner can be named now, offline (finding 1). The verifier passes the row on form (5 of 5 PASS); its substance is
   wrong. Per the deferral discipline this is a fix not yet made, not a deferral.

3. **LOW** · variant 4 JSON `:30` · **`harness_sha256_note` says the as-run hashes "are of the CRLF working-tree
   files" and that "the committed (LF) blobs hash differently". That is false for `proxy.py`.** Its as-run hash
   `8ed0f6fc` is the LF blob's hash at `2f792246` and HEAD; the CRLF form is `d1a20bbd`. The approved `README.md`
   (`5a920d8f`) is also the LF blob. The working tree was mixed. The PERFORMANCE_LOG sentence names only
   `run_probe.py` and `summarise.py`, both CRLF, and is correct.

4. **LOW** · `PERFORMANCE_LOG.md` variant 4 entry ("Policy and egress probes as the entry above") and variant 4 JSON
   · **A condition difference is not recorded: the in-container token reads `elevated: true` in 6 of 6 variant 4 runs,
   against `false` in 6 of 6 Q3 runs** (integrity Low, `S-1-16-4096`, in both). The Q3 entry says "not elevated" for
   the container, and a reader will carry that across. It does not change the variant 4 reading. It is a recorded
   field that differs between the two entries and is not stated.

5. **LOW** · Q3 JSON `:283`, `PERFORMANCE_LOG.md:44` · **"token, all four harness files and the Bitdefender process
   set changed together" undercounts the changed set.** `launch.ps1` also changed (`d94e93d8` in run-20261015-1/-3 →
   `b243519b`), and `launch-standard.cmd` is new. The conclusion (not an isolated token effect) stands. The list of
   what changed is incomplete.

6. **LOW** · journal fragment `:10` · **"Variant 4 was added that evening" is wrong.** #1798 c4340 records the LA
   adding it at 07:25 EDT, and it ran at 07:58 EDT.

7. **LOW** · `docs/reviews/mxc-proxy-egress-standard-token-postrun-review-disposition-2026-10-16.md` rows F4, F5 ·
   DEFERRED with `blocked-by:` pointing to `BLARAI_UPDATES_2026-10-15.md` in another project's folder. Both
   statements are now in this repo's records (`bebb33da`, `PERFORMANCE_LOG.md:44`, Q3 JSON `not_measured` and
   `differences_from_the_elevated_case1_batches`), so the rows are FIXED by `bebb33da`. As written, the predicate
   names a file outside the repository that a later session cannot check from here.

## Checked against raw and found correct

- Q3: token (Medium `S-1-16-8192`, limited, Administrators deny-only, same in header, control and 6 runs); 05:48:34
  to 05:49:11.934 (37.3 s); dry-run "validation passed" 6/6; exit 0 6/6; B2 container 200 = proxy log = second
  listener 3/3 per run (18/18); B3/B4(i)/B4(ii) WinError 10013 18/18, B3 listener hits 0; refusal times 0.002 to
  0.027 s; unconfined pre/post 24/24; B5a/b/c true; PSEC 1.1 432 bytes and `firewall_rules_created` 0 in 6/6;
  `state_changed_by_run` `{}` 6/6; wall times 0.880/0.617/0.475 and 0.561/0.572/0.481; container Low-IL AppContainer,
  not elevated, 6/6; Bitdefender 16/16, and 1 and 14 in run-20261015-1 and -3; launcher hashes identical across all
  batches; policy identical to run-20261015-1 and -3; harness hashes equal `APPROVED_SHA256.q3r2.txt` (1c6638aa),
  approved 03:58 local, before the 05:48 run.
- Variant 4: 07:58:04.383 to 07:59:28.716 (84.3 s); High IL; every run 1008/1016/1008, 8 new, 0 removed, before ==
  after key sets, none of the 8 in after; 6 package-keyed and 2 mention-only per run (my parser); Tessera PERMIT TCP
  127.0.0.1/::1 port 18110 weight 8, BLOCK with no address/port/protocol condition weight 1; provider and sublayer
  GUIDs; sublayer weight 65533; constant SID identical in 6/6 and absent from before/after state; state-file run-SID
  mentions 0/8/0; capture during container alive 6/6; wall times 2.116/1.978/1.808 and 1.836/2.102/1.827; control
  dump `control-present-filters.xml` byte-identical (sha256) to A-r1 before and to `control-removed-filters.xml`.
- Attribution wording: B3 by inference only, B4(i)/(ii) not distinguishable, no net-event or `captureDenials` data;
  the capability-only reading revised only as far as the review states; scope limited to two launchers, 26200.9711,
  TCP, this policy. Every NOT MEASURED item from both post-run reviews is present in its entry and JSON.
- Committed probe code: HEAD `tools/` equals `2f792246` (empty diff). Every hash in `APPROVED_SHA256.txt` (variant 4)
  and `APPROVED_SHA256.q3r2.txt` (Q3) equals the LF or the CRLF form of the blob at the approved commit. That is
  "modulo line endings", with the per-file mix noted in finding 3.
- Precedent form (`4b9c793a` case-1 entry): same section sequence, plain summary, tracker-free scope marker,
  machine-readable pointer. Journal fragment form: dated `###` header naming a lesson, `*Plain summary:*`, first
  person, real SHAs (all eight cited SHAs exist on the branch), ends with `**Next:**`.
- Identity: `scrub_public_identifiers.py --check` 0 findings in 4101 tracked files; `research_tracker_lock.py --check`
  ok; grep over every branch-changed file for the account name, the host name and real `S-1-5-21-` values: only the
  synthetic `S-1-5-21-1-2-3-1001` and `S-1-5-21-9-8-7-1001` in `self_test.py`. The variant 4 JSON carries no run
  AppContainer SID, only the truncated constant.
- Disposition verifier: both files PASS 5/5 on form.
- Tickets: #1799 c4332/c4333/c4348 and #1798 c4343/c4344 agree with the records (c4344 carries the same "absent from
  all MXC binaries" and "owner unidentified" wording as finding 1).

## Merge read

Block on finding 1 (and finding 2, which follows from it) before main and before anything public. It needs a record
edit only, not a new run: the data in hand already decides it. Findings 3 to 7 are wording and should go in the same
edit. They would not block on their own. Nothing found changes a verdict, a count or the Q3 answer.

**Suites run:** none of the standing gate (not requested). Tools run at `2de6ae39`: `verify_disposition.py` (x2),
`scrub_public_identifiers.py --check`, `research_tracker_lock.py --check`, with LOCALAPPDATA redirected to a temp dir.
