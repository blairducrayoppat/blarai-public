# MXC loopback-proxy egress, Q3 (standard token): cold review of the draft #2125 comment

Reviewer: independent, read-only. Date 2026-10-16, 06:38-06:45 -04:00. No probe, self-test or MXC launch run.
Draft: "DRAFT thread comment, Q3 only" in BLARAI_UPDATES_2026-10-15.md (the operator's private updates file), Update 9.
Checked against: run-20261016-1 raw records (header, control-b5, six run records), run-20261015-1/-3 raw records,
the post-run review (mxc-proxy-egress-standard-token-postrun-review-2026-10-16.md), the fork's request
(issuecomment-6206439944, variant 1), the #2125 thread via the GitHub API, and the q3 worktree git log.

## Verdict: FAIL (four sentence-level corrections; every number in the table is correct)

## Verified against the raw records (not the summary)

- Token: header, control and all six records: standard, Medium (S-1-16-8192), not elevated, Administrators deny-only.
- Container: `payload.token` is_appcontainer true, integrity S-1-16-4096 (Low), 6 of 6.
- Policy byte-identical (network + runtimeConfig) to run-20261015-1 and -3: egress deny, ingress allow, hostLoopback
  allow, networkProxy http://127.0.0.1:18110, no allowedProxyPeer.
- `dry_run.rc` 0, "validation passed", 6 of 6; `launch.exit_code` 0, 6 of 6.
- B2 9 of 9 per launcher: payload status 200, proxy_log `forwarded`/200, target_log marker, all three agree per run.
- B3 / B4(i) 10.0.10.1:80 / B4(ii) 1.1.1.1:443: connected false, winerror 10013, 18 of 18; b3_listener_hits 0.
- Unconfined pre/post (1.1.1.1:443 and gateway:80) connected 24 of 24; run token standard.
- MXC log: `enforcement_mode":"capabilities"` and `firewall_rules_created":0` in all 6.
- Launcher hashes A aa444c0f (signed Valid Microsoft), B e951922b (NotSigned, 525d0f25): same as the case-1 batches.
- Draft text carries no account name, host name, email or the gateway IP.

## Findings and corrections

1. MEDIUM. "Three runs per launcher, no change to the machine between them" reads WFP state as unchanged when it was
   not measured: every snapshot carries `wfp_mxc_filters: "unreadable: not elevated"` before and after, so the
   "equality" is two identical "unreadable" strings. The post-run review (finding 3, merge read) required that the
   WFP state not be presented as clean. Replace with:
   "Three runs per launcher, Bitdefender present in all six, the same machine state throughout ([records and harness](LINK-PENDING)):"
   or simply "Three runs per launcher ([records and harness](LINK-PENDING)):".
   The limits bullet on WFP stays.

2. MEDIUM. The harness-change bullet omits the Bitdefender change that the post-run review (finding 5) and the
   draft's own raw block above it both name, and understates the harness change. Records: Bitdefender processes
   1 (run-20261015-1, only bdredline.exe), 14 (run-20261015-3), 16 (this batch); harness hashes all four changed;
   git log between the case-1 code (25210ef3) and 1c6638aa includes stricter refusal judging and HOLD guards, not
   only token recording. Replace the bullet with:
   "Compared with the case-1 batches, my harness also changed (a standard-token mode, token records and stricter
   verdict rules) and Bitdefender's running process set differed, not only the token. The same verdicts and error
   codes are not an isolated token effect."

3. LOW-MEDIUM. "Cases 2 and 3 are still to follow; neither has a result I can stand behind yet." Case 2's Tier 1
   result passed cold review and its evidence is already public (windows-containment-evidence 9fa86af, Update 6); the
   comment is held by Blair's ruling until the AppContainer tier is measured (Update 8), not because the result is
   unreliable. A reader who finds the public folder sees a contradiction. Replace with the case-1 wording:
   "Cases 2 and 3 are still to follow."

4. LOW. Bitdefender bullet: (a) "the case-1 batch with no third-party suite" -- run-20261015-1 had Bitdefender
   uninstalled but one bdredline.exe still running, and Windows Security Center listed a McAfee firewall in every
   batch (checked today: a stale registration, timestamp 2025-03-30, its exe absent, no McAfee service or process;
   state at batch time assumed the same). (b) "keys on program path" omits why that matters here: the container ran a
   different interpreter path from the unconfined controls (same sha256), which is the post-run review's finding 4.
   Replace with:
   "Bitdefender was present. A per-program firewall rule on the container's interpreter path (a different path from
   the unconfined controls') would also give 10013, so this batch alone does not rule it out. Against that, the case-1
   batch with Bitdefender uninstalled gave the same refusals."

## Not findings (checked)

- "carries over to a standard token, which fits your capability-only reading but does not test it": accurate given
  the limits bullet; it does not claim a token effect.
- No console claim in the draft (post-run finding 1 respected); no attribution of the refusals to MXC.

## Before the evidence push (not draft text)

- Records carry `"account"` with the account name and Windows paths under the profile: the scrub must run (the draft
  already says so).
- NEW in this batch: `payload.token.user_sid` (S-1-5-21-..., the account's SID) in all six records; the case-1 records
  did not carry it. `scripts/scrub_public_identifiers.py` has no SID rule. The SID identifies the account on this
  machine; decide before pushing whether it is redacted (hypothesis-level: not a named identifier in identity.md).
