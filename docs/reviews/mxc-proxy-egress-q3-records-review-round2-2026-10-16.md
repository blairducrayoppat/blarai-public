---
title: "MXC proxy egress, Q3 and variant 4 finishing records: pre-merge review, round 2"
status: closed
area: reviews
date: 2026-10-16
---

# Q3 and variant 4 finishing records: pre-merge review, round 2

**Subject:** `feat/1799-standard-token` at `9c5f2965` (records unchanged since `0a697541`; `9c5f2965` touches only the post-run review's correction section). Round 1 (`a57f2aef`) returned FAIL with seven findings. Three
commits since then:
- `b1923fd5`: records (PERFORMANCE_LOG.md, both JSON files, the journal fragment).
- `06484a51`: both dispositions.
- `0a697541`: a correction section appended to the variant 4 post-run review. This commit was not named in the brief
  and is reviewed here as well.

Reviewer: the round 1 reviewer, independent of the author. I re-read the files from disk at `0a697541`.

## Verdict

**PASS.** All seven round 1 findings are closed, checked against the raw data, the MXC source and the binaries. The
edits change no verdict, no count and no number from round 1. Two new LOW wording items remain; neither blocks.

## Round 1 findings, re-verified

| # | Round 1 | Now | Evidence |
|---|---|---|---|
| 1 HIGH | "None of the eight is from MXC's own binaries"; constant SID "owner not identified" | **CLOSED** | `PERFORMANCE_LOG.md:69` names the SID as the AppContainer SID of `MXC-Loopback` and states the method and its control. It cites `base_container_helpers.rs:24`, `:176`, `base_container_runner.rs:3231,3441` and `networking.md:121-124`, all re-checked in `525d0f25`. The `wxc-exec.exe` and `mxc_ffi.dll` string presence was re-checked on the binaries. The reciprocal peering is described correctly: `Sandbox.{GUID}` carries the MXC-Loopback SID and MXC-Loopback carries the run SID (re-confirmed in the XML in round 1). "Installed by the Windows Firewall service, not by MXC code" is correct (provider `FWPM_PROVIDER_MPSSVC_APP_ISOLATION`). The step "MXC requests the peer through its PSEC spec" is labelled as a source statement, not observed, and is added to NOT MEASURED (`:78`, JSON `:1001`). `:70` now limits "not MXC's" to the four Tessera filters. JSON `:107` drops "owner not identified"; JSON `:108` `constant_package_sid_owner` matches the log; JSON `:105` snapshot parenthetical is now true (0 because the snapshot runs outside the launch). Journal `:12` retracts the earlier sentence in the first person. Ticket #1798 c4352 corrects c4344. A searched-for "none of the eight", "owner not identified", "unidentified" or "also unknown" now remains only in round 1 and the post-run review's original text, and that text carries the `0a697541` correction section. |
| 2 MEDIUM | Disposition F4 deferred to a needless capture | **CLOSED** | `variant4-postrun-disposition:21` FIXED at `b1923fd5`, naming the derivation and the source lines. The prose at `:14` was updated to match. |
| 3 LOW | CRLF hash note false for `proxy.py` | **CLOSED** | JSON `:30` now says the tree was mixed. `run_probe.py` 4e0d12cc and `summarise.py` 0ceafa16 are CRLF; `proxy.py` 8ed0f6fc and `README.md` 5a920d8f are LF blobs. All four re-checked against the blob hashes at `2f792246` (round 1 table). |
| 4 LOW | In-container `elevated` differs between batches, not stated | **CLOSED** | Log `:55`, variant 4 JSON `in_container_token_elevated`/`_note`, Q3 JSON `container_confined`. The values (true 6/6 in variant 4, false 6/6 in Q3, Low IL in both) match the raw records. |
| 5 LOW | Changed set omits `launch.ps1` and `launch-standard.cmd` | **CLOSED** | Log `:44` and Q3 JSON `:283` add `launch.ps1` d94e93d8 → b243519b and the new `launch-standard.cmd`. The values match the batch headers. |
| 6 LOW | "that evening" | **CLOSED** | Fragment `:10`: "at 07:25 EDT, with the operator present, and ran at 07:58". Matches #1798 c4340 and the batch header `started`. |
| 7 LOW | Q3 F4 and F5 deferred to an out-of-repo file | **CLOSED** | Both rows are FIXED at `bebb33da`. The quoted sentences are in the Q3 entry's NOT MEASURED and in the Q3 JSON. |

## No collateral change

I checked the word-level diff `a57f2aef..0a697541` over all seven changed files. The removed text is limited to the
wrong ownership wording, "that evening", "not elevated" (replaced by the explicit flag), the hash note, and the
disposition statuses and predicates. No count, time, hash, verdict, scope sentence or NOT MEASURED item was removed.
The only NOT MEASURED edit is the swap of "owner of the constant package" for "whether mpssvc installs the peering on
MXC's request (not observed)". Both JSON files parse.

## New findings (round 2)

1. **LOW** · `docs/journal_fragments/2026-10-16_mxc-standard-token-and-wfp-capture.md:14` · **The "Records" line
   still reads "the variant 4 disposition (four findings, all deferred ...)" and cites only `bebb33da`.** After
   `06484a51`, F4 is FIXED, so three of the four are deferred, and the corrected records are in `b1923fd5`. This is
   prose that outlived its own edit, one paragraph below the retraction.
2. **LOW** · `docs/reviews/mxc-proxy-egress-variant4-postrun-review-2026-10-16.md` (correction section, `0a697541`)
   and `docs/reviews/mxc-proxy-egress-standard-token-postrun-review-disposition-2026-10-16.md:18` · **Two small
   inaccuracies.**
   - The correction names "row (b) and finding 4" but not the verdict paragraph's "None of the eight filters is from
     MXC's own binaries". That paragraph is the sentence c4352 itself names.
   - The correction calls `b1923fd5` "the merged records" before any merge.
   - Q3 disposition F4 says `b1923fd5` "adds the WFP layer". The WFP layer was added in `bebb33da`; `b1923fd5` only
     corrected the ownership wording.

   None of these changes a number or a claim about the system.

   **Update at `9c5f2965`:** the first two bullets are fixed. The correction now names the verdict paragraph's
   sentence, and it says "the records on this branch (b1923fd5)". Remaining nuance, not blocking: the correction says
   that sentence "says or implies" the owner is unidentified. It was also wrong on its own terms, because the
   `MXC-Loopback` name string is in MXC's binaries. The correction does state that string presence two sentences
   later, so a reader can reconstruct it. The third bullet (Q3 disposition F4, "adds the WFP layer") is unchanged at
   `9c5f2965`.

## Tools (at `0a697541`, LOCALAPPDATA redirected to a temp dir)

- `verify_disposition.py`: variant 4 disposition PASS 5/5 (F1-F3 DEFERRED, merge-read and F4 FIXED); Q3 disposition
  PASS 5/5 (F1, F2, F4, F5 FIXED; F3 DEFERRED).
- `scrub_public_identifiers.py --check`: 0 findings in 4102 tracked files (run at `0a697541`).
- `research_tracker_lock.py --check`: ok, 0 findings (run at `0a697541`).
- Identity grep over the changed files (account name, host name, real `S-1-5-21-`): 0 hits in the seven changed files at `0a697541`; `9c5f2965` (one line in the post-run review) re-grepped, 0 hits.

## Merge read

Nothing blocks. The HIGH and MEDIUM from round 1 are fixed with the correct mechanism and the right hedge (the
request path is labelled as the source's statement). The two new LOW items can go in the same pass as the merge or
straight after it; neither affects what a reader would conclude. Standing gate not run (not requested; records-only
change).
