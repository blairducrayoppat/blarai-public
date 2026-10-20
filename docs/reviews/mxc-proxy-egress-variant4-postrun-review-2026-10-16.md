# MXC proxy-egress variant 4 — post-run review (#1798)

Date: 2026-10-16, 08:00–08:10 -04:00. Reviewer: independent, read-only (author != verifier).
Subject: raw batch `blarai-research-data/mxc-proxy-egress/run-20261016-2/` (six runs, arm A signed v1.0.0
`dl/x64/wxc-exec.exe`, arm B main `525d0f25`, elevated token, case-1 policy, Windows 10.0.26200.9711), code at
worktree `q3-standard-token` `34e2306d`. Method: an independent parser (ElementTree over the netsh XML, keyed by
`filterKey`, not the probe's `summarise.py`) over every before/during/after dump; reads of the run records,
MXC's log tail, MXC's source at `525d0f25`, and a byte search of MXC's shipped binaries and `C:\Windows\System32`.
No probes, launches or firewall changes.

## Verdict

**ANSWERED (filters exist and who owns them); NOT ANSWERED (which filter produced the 10013s).**

The claim the raw supports: *during every launch, a Windows component named Tessera installed four WFP filters
keyed by `FWPM_CONDITION_ALE_PACKAGE_ID == <that run's own AppContainer SID>` in its own sublayer: a PERMIT for
TCP to 127.0.0.1 / ::1 port 18110 (MXC's configured proxy port) and a BLOCK for everything else from that package.
They appear only in the during dump and are gone after. The Windows Firewall service additionally installed four
inbound loopback PERMIT filters (`Sandbox.{GUID}`, `MXC-Loopback`). None of the eight filters is from MXC's own
binaries; the Tessera filters are the OS policy MXC requests, and MXC's own source names them.*

This does not contradict "MXC created no firewall rules" (`firewall_rules_created: 0` counts MXC-authored
Windows Firewall rules); it does contradict "capability-only": direct egress is under a per-run, SID-keyed
proxy-containment BLOCK in addition to the missing `internetClient` capability.

## Evidence (run A-A1-r1-075819 and B-B1-r1-075853 examined in full; all six checked by script)

| Item | Finding | Source |
|---|---|---|
| (a) delta | Every run: before 1008 filters, during 1016, after 1008; 8 new keys, all 8 absent after; before/after key sets identical; 0 filters removed during. Filter keys differ per run. | independent diff, all 6 runs |
| (b) SID condition, Tessera x4 + Sandbox.{GUID} x2 | `FWPM_CONDITION_ALE_PACKAGE_ID`, `FWP_MATCH_EQUAL`, `FWP_SID` = run SID. A-r1: `S-1-15-2-2988937345-…-3117606681`; B-r1: `S-1-15-2-1059199899-…-101955115`. Each equals that run's `payload.token.appcontainer_sid` (the in-container token readback) and `wfp.container_sid`. | XML + run JSON |
| (b) SID condition, MXC-Loopback x2 | **PACKAGE_ID is a different SID**, `S-1-15-2-2397545170-…-3273807654`, the same in all 6 runs, absent from the before/after state and from `appcontainer_mappings`. The run SID appears only inside the `FWPM_CONDITION_ALE_REMOTE_USER_ID` security descriptor. Owner of the 2397… package: not identified. | XML |
| (c) Tessera provider/sublayer | providerKey `{2f8c6d14-3b7e-4a59-9c08-1d4e7a6b2f30}` "Tessera Sandbox Provider" (no PERSISTENT flag, no serviceName; registered already in every before dump and both control dumps); subLayer `{7b1e9a2c-9d4f-4c8a-b321-5e6d2f8a1c44}` "Tessera Sandbox SubLayer", weight 65533; providerData = SID S-1-5-21-…-1001 (the launching user). | state XML |
| (c) who is Tessera | MXC `525d0f25` `docs/logging-access-denied.md:260-292`: "Tessera is an internal Windows component name"; it requires exactly `ProviderGuid {2F8C6D14-…}` and `SublayerGuid {7B1E9A2C-…}` to attribute decisions; reason 103 = `proxyContainment`. `base_container_helpers.rs:94-96`: "Proxy mode must remain direct-egress denied and therefore deliberately omits internetClient." String "Tessera Sandbox" found in `C:\Windows\System32\processmodel.dll`; **absent** from every .exe/.dll in MXC's `dl/x64` and the arm-B release dir (ASCII, UTF-16 and GUID-bytes search). | source + binary search |
| (c) Sandbox.{GUID}, MXC-Loopback | provider/sublayer `FWPM_PROVIDER_MPSSVC_APP_ISOLATION` / `FWPM_SUBLAYER_MPSSVC_APP_ISOLATION` (Windows Firewall service app-isolation), weight max uint64. The name "MXC-Loopback" indicates MXC asked mpssvc for a loopback exemption; mechanism not in this record. | XML |
| (d) Tessera BLOCK | conditions: PACKAGE_ID == run SID; ALE_USER_ID SD `D:(A;;CC;;;<user>)(A;;CC;;;AC)(A;;CC;;;S-1-15-2-2)`. No address/port/protocol condition — blocks all outbound connects from the package. Weight 1 (eff. 1152921916923707392). Layers ALE_AUTH_CONNECT_V4 and V6. | XML |
| (d) Tessera PERMIT | same two conditions + `IP_REMOTE_ADDRESS` 127.0.0.1/32 (v6: ::1/128) + `IP_PROTOCOL` 6 + `IP_REMOTE_PORT` 18110. Weight 8 (eff. 9512591836032532480) > BLOCK, same sublayer. 18110 = `runtimeConfig.networkProxy` and MXC log `proxy_port`. | XML + run JSON |
| (e) positive control | rule `BlarAI-wfp-poscontrol-075806` (synthetic package SID) produced nothing: `control-present-filters.xml` is byte-identical to A-r1's before dump; neither the SID nor the rule name appears in control filters or state. | cmp + grep |
| (f) timing / other installer | No filter named Tessera/MXC/Sandbox.* in any before or after dump of any run or control; filterIds are contiguous per launch (A-r1: 509136–509143). Only the provider object persists between runs. | all dumps |
| payload | b2 3/3 via proxy 200; b3 127.0.0.1:18111, b4i 10.0.10.1:80, b4ii 1.1.1.1:443 all WinError 10013 (A-r1). | run JSON |

## Findings

1. **MEDIUM — the summary's "filters referencing the container SID" overstates two of the eight.**
   `summarise.py:384-389` `filters_referencing` is a case-insensitive substring match over the whole filter
   text, so it counts the MXC-Loopback filters, whose PACKAGE_ID is another container and which carry the run SID
   only in a remote-user security descriptor. The headline list should distinguish "keyed to the run package"
   (6 per run) from "mentions the SID" (2 per run). Reproduced by the independent parse above. Does not change the
   FILTERS-PRESENT reading (6 genuine package-keyed filters per run).
2. **MEDIUM — the positive control is uninformative, not evidence of blindness.** The synthetic-SID
   `New-NetFirewallRule -Package` rule compiled to no filter at all (dump byte-identical to a baseline), so it tests
   mpssvc's handling of an unregistered package, not the capture. The capture's sight is established by the runs
   themselves (8 per-launch filters, exact-SID conditions, clean before/after). The control as designed cannot pass
   on this machine; a control keyed to a registered package, or a raw WFP filter, would. Hypothesis for why mpssvc
   dropped it: unregistered package SID (not tested).
3. **LOW — the mechanism behind 10013 is not identified.** Two blockers are present for b3/b4: Tessera's BLOCK
   (its sublayer's highest-weight match for any non-18110 connect is the weight-1 BLOCK) and app-isolation's
   missing-`internetClient` / loopback isolation. Without WFP net-event (classify-drop) capture with filterId, the
   raw cannot say which filter dropped each attempt, nor whether either alone suffices. MXC's own reason codes
   (Tessera 103 `proxyContainment` vs App Isolation 1) would discriminate if `captureDenials` were recorded.
4. **LOW — the 2397… AppContainer is unidentified.** It is constant across six launches and both MXC builds and
   exists only during launch; the probe's HTTP proxy at 18110 is the host-side probe listener, not that container.

## Addendum 08:05: item (c) source citations and the 10013 layer

Citations verified on disk at `525d0f25`: `docs/logging-access-denied.md:248` "MXC does not coordinate with WFP
directly"; `:250-258`, where `internetClient` is added only under captureDenials plus direct `network.egress`, "not applied
… when proxy mode is selected"; `:260-264`, which defines Tessera as an internal Windows component; `docs/backends/process-container/networking.md:37-50`
"PSEC blocks outbound with WFP" (matrix row deny/allow; the matrix "covers … without … proxy mode"), and
proxy mode "retain[s] the matrix posture"; `base_container_helpers.rs:94-97`; `base_container_runner.rs:3006`.
The provider key is named in the state dumps' providers section ("Tessera Sandbox Provider", 7 occurrences of the
key in A-r1 and B-r1 during-state) and in the filters dump's provider list.

Which layer produced 10013, per probe:
- **b3 (127.0.0.1:18111): Tessera BLOCK, by inference from the shape of the filters (strong, not observed).** b2 (127.0.0.1:18110) succeeded
  3/3 from the same container to the same address and a host listener of the same kind; b3 differs only by port. In the
  during dumps (A-r1, B-r1), the only filters that name the run SID and condition on a port are the two Tessera
  PERMITs for 18110; no filter anywhere mentions 18111. The app-isolation (capability) gate has no per-run,
  port-specific filter that could pass 18110 and refuse 18111. So the port split is explained only by Tessera's
  PERMIT(18110, w8) over BLOCK(all, w1).
- **b4i (10.0.10.1:80), b4ii (1.1.1.1:443): not distinguishable.** Both gates would refuse: no
  `internetClient`/`privateNetworkClientServer` (MXC's code deliberately omits it in proxy mode) and the Tessera BLOCK.
  MXC's own comment ("let outbound attempts pass the capability gate so Tessera's egress policy makes … the
  decision") implies the capability gate acts first when the capability is absent. That is MXC's statement and was not
  measured here.
- The batch cannot separate them: no WFP net-event (classify-drop, filterId) capture and no `captureDenials`
  reason codes (App Isolation `1` vs Tessera `103`) were recorded.

## What this does and does not show

Shows: per-launch, run-SID-keyed WFP policy from Windows' Tessera component permitting only TCP to the loopback
proxy port and blocking all other outbound connects from the container, removed on exit; plus mpssvc loopback
exemptions; identical shape in both arms. Does not show: which filter dropped any given 10013; whether removing
`internetClient` alone would hold; who owns the 2397… package; whether Tessera is a public, documented Windows
interface (MXC calls it internal).

## Merge read

Block on nothing for the data. Before the FILTERS-PRESENT result is cited, reword it to "6 filters keyed to the
run package (Windows Tessera proxy containment + mpssvc loopback exemptions), 2 further mpssvc filters naming it
as remote" and drop any wording that the positive-control failure weakens or strengthens the reading.
Could not break: the delta (before == after keys in all six runs), the exact-SID match against the in-container
token, or the attribution of the Tessera provider/sublayer GUIDs (MXC source names them byte-for-byte).
Suites run: none (read-only review; no test suite exercised). Code hash reviewed: `34e2306d`.

## Correction (2026-10-16 17:40 EDT, orchestrator; source: records review a57f2aef, finding 1)

Row (b) above, finding 4, and the verdict paragraph's statement that none of the eight filters is from MXC's own binaries say, or imply, that the owner of the constant `S-1-15-2-2397545170-…-3273807654` package is not identified. That is wrong. The SID is the AppContainer SID derived from the name `MXC-Loopback`: SHA-256 of the lower-cased UTF-16LE name, with the first 28 bytes read as seven little-endian uint32 values, matches all seven sub-authorities. The same method on a known package reproduces that package's SID. `MXC-Loopback` is MXC's own named loopback peer (`525d0f25` `base_container_helpers.rs:24`; `docs/backends/process-container/networking.md:121-124`; the string is present in `wxc-exec.exe` and `mxc_ffi.dll`). The `Sandbox.{GUID}` and `MXC-Loopback` pairs are therefore one reciprocal loopback peering between the run container and MXC's named peer, installed by the Windows Firewall service (mpssvc). The Tessera attribution is unchanged. The text above is kept as written; the corrected statement is in the records on this branch (b1923fd5).
