# #1671 raw WFP block spike (wfp-coder-egress-spike.ps1)

Question: does a RAW Windows Filtering Platform (WFP) BLOCK filter, keyed to the `blarai-coder` account, enforce on this
machine while Bitdefender owns packet filtering? The existing Windows Firewall per-SID rule is inert (#775 c.1653).
A raw filter in our own provider/sublayer is a different mechanism and may enforce.

## Run (Lead Architect present, elevated 64-bit Windows PowerShell 5.1 or pwsh 7)

    .\wfp-coder-egress-spike.ps1 -SelfTest              # no system change
    .\wfp-coder-egress-spike.ps1 -DryRun                # builds + prints everything; engine opened READ-ONLY, adds nothing
    .\wfp-coder-egress-spike.ps1 -Live [-HoldSeconds 60]   # the test (default 60, max 120)

Helpers are dot-sourced from `C:\Users\_OPERATOR_\agentic-setup\scripts` (`coder-leg-queue.ps1`, `coder-provisioning-lib.ps1`).
Report: `result-<timestamp>.json` here (observations, timestamps, uptime, Bitdefender process names, firewall profiles, mpssvc/BFE).

## Rollback (what to tell the LA)

All objects are added in a DYNAMIC WFP session (`FWPM_SESSION_FLAG_DYNAMIC`): closing the engine handle OR the process
exiting/dying/being killed removes provider, sublayer and all four filters. Nothing is persistent, so a reboot or closing
the window is also a full rollback. Extra layers: a CLR timer thread closes the handle at HoldSeconds+30 s even if
PowerShell hangs; the watchdog removes everything on two consecutive operator connect failures.
Manual check after any run: `netsh wfp show filters` and search the output for `BlarAI #1671` (writes a file; read-only otherwise).

## What -Live does

0 preflight (elevated, 64-bit, coder SID resolved by the verify script's expression, SID is an account-domain SID and is
neither the operator's SID nor a group of the operator token, task exists, our objects absent) ->
1 control: operator connects 3x each to 1.1.1.1:443 and 8.8.8.8:443 (all must succeed) + coder baseline probe through
`\BlarAI\BlarAI-Coder-Leg` (kind=probe, never dispatch; egress must be OPEN today) ->
2 add 1 provider + 1 sublayer + 4 filters in ONE transaction (abort on any error) ->
3/4 hold: operator connect to 1.1.1.1:443 every 2 s (two failures in a row = remove all, exit 3) while the coder probe runs
via the task ->
5 close engine, verify objects gone (read-only lookups by key), re-run coder probe: egress must be open again ->
6 JSON report + exit code.

Filters (all in our sublayer, weight 0xFFFF; every one has the coder-user condition, none without):
permit loopback (flags IS_LOOPBACK ALL_SET + user) V4/V6 weight 0x2000; block (user only) V4/V6 weight 0x1000.
Block on ALE_AUTH_CONNECT is outbound-connect only; inbound accept is not touched.

## Exit codes

0 coder blocked + loopback ok + operator unaffected + removal verified (answer: raw WFP enforces)
1 coder NOT blocked (answer: raw WFP does not enforce under Bitdefender)
2 precondition/argument failure, nothing added | 3 operator affected, aborted | 4 inconclusive | 5 no baseline | 7 removal not verified
(4/5/7 are additions to the brief's 0/1/3; 2 as specified. Precedence: 3, 7, 5, 4, 1, 0.)

## Deviations from the brief (reasons)

* Elevation is required for -Live and for the DryRun engine step; -DryRun and -SelfTest otherwise run un-elevated (the engine
  step is skipped with a message) so they can be inspected anywhere. -Live exits 2 when not elevated.
* The coder-probe start-proof loop (mirrors verify-coder-containment.ps1 lines 127-152) is re-implemented, because that logic
  lives inside the verify script body and cannot be dot-sourced. Queue/wait/path helpers ARE reused.
* The loopback stub is a C# TcpListener (not a Start-Job as in verify) so it dies with this process. It is started only if
  nothing listens on 127.0.0.1:8000, and the coder probe's secret_paths is empty (check 2 is not what this spike asks).
* Added a provider (brief: optional) so the objects are identifiable; added extra exit codes; added the SID-safety refusal.
* Hold semantics: the coder probe runs INSIDE the hold; filters never outlive HoldSeconds (+ the post-hold verification, which runs after close).

## Provenance of constants (read from the installed Windows SDK 10.0.26100.0, not guessed)

* um/fwpmu.h: FWPM_LAYER_ALE_AUTH_CONNECT_V4 c38d57d1-05a7-4c33-904f-7fbceee60e82; _V6 4a72393b-319f-44bc-84c3-ba54dcb3b6b4;
  FWPM_CONDITION_ALE_USER_ID af043a0a-b34d-4f86-979c-c90371af6e66; FWPM_CONDITION_FLAGS 632ce23b-5167-435c-86d7-e903684aa80c.
* shared/fwptypes.h: FWP_DATA_TYPE (UINT32=3, UINT64=4, SECURITY_DESCRIPTOR_TYPE=14), FWP_MATCH_TYPE (EQUAL=0, FLAGS_ALL_SET=6),
  FWP_ACTION_BLOCK 0x1001 / PERMIT 0x1002, FWP_CONDITION_FLAG_IS_LOOPBACK 1, FWP_ACTRL_MATCH_FILTER 1, struct definitions.
* shared/fwpmtypes.h: FWPM_SESSION_FLAG_DYNAMIC 1, FWPM_*0 struct definitions. shared/winerror.h: FWP_E_FILTER_NOT_FOUND
  0x80320003, FWP_E_PROVIDER_NOT_FOUND 0x80320005, FWP_E_SUBLAYER_NOT_FOUND 0x80320007. shared/rpcdce.h: RPC_C_AUTHN_DEFAULT.
* Our provider/sublayer/filter keys are generated for this spike (not Microsoft values).

## Interop risks (not provable without a live run)

* Struct layout: hand-derived x64 sizes/offsets (FWPM_FILTER0 = 200, FWPM_FILTER_CONDITION0 = 40) are asserted in -SelfTest
  against the CLR marshaller, but no C compiler checked them against the real header. Script refuses 32-bit for -Live.
* FWP_VALUE0/FWP_CONDITION_VALUE0 modelled as {uint, IntPtr}; uint32 stored in the low bytes (little-endian); `sd` arm is a
  POINTER to an FWP_BYTE_BLOB (per header), not an inline blob.
* SD lifetime: blob + data live in HGlobal memory freed only after the transaction (BFE copies on add). Self-relative SD,
  DACL only, no owner/group, one ACE (mask 0x1) - same shape as the Windows Firewall rule's `D:(A;;CC;;;sid)`.
* Weights are explicit FWP_UINT64 (not the 0-15 FWP_UINT8 range form). Cross-sublayer arbitration with Bitdefender's own
  sublayers is the unknown being tested; a Block in another sublayer cannot be undone by our permit.
* ALE_AUTH_CONNECT with ALE_USER_ID matches the token of the connecting process; services/impersonation within the coder
  account are covered, other accounts are not. Bitdefender may be enforcing at a layer/driver below or beside BFE; a
  non-enforcing result would not distinguish "WFP callout ordering" from "traffic handled before ALE".
* Loopback permit relies on IS_LOOPBACK at ALE_AUTH_CONNECT; if loopback is not evaluated there, check 3 still passes and
  the permit is simply unused (exit 4 only if loopback fails while blocked).
* Probe false positive: the probe counts an exception as "blocked". The baseline (open) + post-removal (open again) arms are
  what make a "blocked" reading attributable to our filters.
* PowerShell 5.1 compiles C# 5; no newer syntax used. Timer callback closes the engine from a pool thread (guarded by a lock).
