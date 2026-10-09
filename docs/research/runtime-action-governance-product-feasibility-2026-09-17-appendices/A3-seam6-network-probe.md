# P3a — The network seam: Windows Firewall, the Windows Filtering Platform, DNS, TLS

Study #1549 (runtime action governance for AI agents, Windows PC product). Seam 6 of the feasibility probes.
Written 2026-09-17 by the finisher agent from the predecessor's on-disk logs (probe runs 02:47–03:04 EDT) plus the finisher's own
re-parse and re-verification (09:32–09:33 EDT). Machine: Windows 11 Pro 25H2, build 10.0.26200, Intel Core Ultra 7 258V,
Bitdefender Total Security 27.0.60.341 installed, elevated PowerShell 7. All times are local (EDT, UTC−4).

Log directory (S): `…/scratchpad/study/probes/p3a/` — `01-firewall-state.log`, `02-perprocess-block.log`, `02b-wfp-capture.log`,
`02c-remove-timing-midrun.log`, `03-wfp-dump.log`, `03-wfp-parse.log`, `03-wfp-parse2.log`, `03-wfp-parse3.log` (finisher),
`04-dns-tls-adapters.log`, `midrun-*.ps1/.txt`, `parse_wfp.py`, `parse_wfp2.py`, `parse_wfp3.py` (finisher), `wfp-filters.xml`,
`wfp-state.xml`, `wfp-capture-with-rule.cab` + `cap-with-rule/`.

## 1. Outcome first

**The per-process outbound block did not work on this machine, and it failed silently.** A Windows Firewall rule
`New-NetFirewallRule -Program <probe-curl.exe> -Direction Outbound -Action Block -Profile Any` was accepted (cmdlet returned
`PrimaryStatus OK`, `netsh` listed it, the registry held it, the firewall event log recorded event 2097 "rule added"), yet every
one of the 5 + 16 + 16 HTTPS requests made by that program while the rule was in place returned HTTP 200, exit code 0 — identical
to the 5-run baseline with no rule. The rule was never turned into a filter in the kernel: the Windows Filtering Platform (WFP)
filter dump taken while the rule was in place contains **0** filters for it (searched by name and by rule GUID across all 2405
filters). The same is true of the project's own pre-existing rule `blarai-coder-deny-outbound` (0 filters).

**Who owns the firewall here: Bitdefender, not Windows.** Bitdefender Firewall is registered with the Windows Firewall service
(`mpssvc`) as a third-party firewall product claiming rule categories `0,1,2` = BOOT, STEALTH, FIREWALL
(`HNetCfg.FwProducts`, read 03:04:14 and again 09:33:20). Microsoft's own API description of that property: the rule categories
"for which the third-party firewall wishes to take ownership from Windows Firewall" (`INetFwProduct::get_RuleCategories`,
ms.date 2018-12-05). The visible symptom is `netsh advfirewall show allprofiles` reporting
`LocalFirewallRules N/A (GPO-store only)` on all three profiles while `State ON` and the profiles all say `Enabled True` — nothing
in the normal management surface says "your rules are not being enforced". In the kernel, the Windows Firewall provider
(`FWPM_PROVIDER_MPSSVC_WF`) holds only 18 filters, all AppContainer loopback/boot-time filters; Bitdefender's two drivers hold
2176 filters and 44 callouts, and its BDDCI4 sublayer sits at the top of the arbitration order (weight 65280 of 32 sublayers).

**What this means for the product (the seam-ownership score):**

1. Windows Firewall rules are not a seam a governor can own on a consumer PC. Any suite that registers a firewall (Bitdefender
   here; the same registration API is what every consumer suite with a firewall uses) takes the FIREWALL category away, and the
   governor's rules are stored but not enforced, with no error. A governor that uses this path must first read `INetFwProducts`
   (Component Object Model class `HNetCfg.FwProducts`) and treat a non-empty list as "seam not owned". Security Center
   (`root/SecurityCenter2`) is NOT a reliable substitute: on this machine it still lists a McAfee firewall and antivirus as
   enabled whose executable path no longer exists (MEASURED, `Test-Path` False).
2. To own the seam regardless of the installed suite, the governor has to be its own WFP provider (user-mode
   `FwpmFilterAdd` with `FWPM_CONDITION_ALE_APP_ID` in its own sublayer) — that bypasses the Windows Firewall rule store
   entirely. Whether such a filter is honoured next to Bitdefender's top-weight sublayer was NOT probed here (see §9).
3. Anything semantic — the URL, the host name, the HTTP method, the prompt or tool-call content — needs a kernel-mode callout
   driver. User-mode WFP filters match only metadata: program path, user SID (security identifier), package SID, addresses,
   ports, protocol, interface, profile, loopback flag. None of the ~130 documented filtering conditions reads payload
   (Microsoft Learn, ms.date 2024-05-02). Microsoft's driver documentation is explicit that "Deep Inspection" and
   "Stream Modification" are what callout drivers exist for (ms.date 2024-09-27). Bitdefender does exactly this: 52 callouts at
   the connect, accept, flow-established, stream, datagram and connect/bind-redirect layers (MEASURED).
4. DNS filtering is per domain, not per application (Name Resolution Policy Table has 0 entries here; DNS-over-HTTPS is
   configured but not active). TLS content is out of bounds for a consumer governor: reading it needs a root certificate in the
   machine store — Bitdefender has installed one (`CN=Bitdefender Personal CA.Net-Defender`, in both LocalMachine\Root and
   CurrentUser\Root) — yet the one TLS path tested here (a .NET SslStream to example.com) was NOT intercepted.

## 2. Seam table

| Seam | Sees | Stops | Escapes | Cost | Works here today | Grade | Source |
|---|---|---|---|---|---|---|---|
| Windows Firewall per-program rule (`New-NetFirewallRule`, mpssvc store) | Program path, direction, local/remote address & port, protocol, profile, interface type, service, local user/owner SID (`LUAuth`), app package | New connections matching the rule — only while mpssvc owns the FIREWALL category | Everything semantic; and on this machine everything, because the rule is never instantiated as a filter | Add 174–664 ms, remove 2136–2702 ms (PowerShell cmdlets, N=5+1) | **NO** — Bitdefender owns categories BOOT/STEALTH/FIREWALL; 0 WFP filters for the rule; 37/37 requests through the block | MEASURED | `02-perprocess-block.log`, `02c-…log`, `03-wfp-parse3.log`, `01-firewall-state.log` |
| Third-party firewall ownership check (`INetFwProducts`) | Which product claimed which rule categories | Nothing — a detector | — | Registered products = 1: Bitdefender Firewall, categories 0,1,2, exe `wsccommunicator.exe` | YES (as a detector) | MEASURED (03:04:14, 09:33:20) | `01-firewall-state.log`; INetFwProduct ms.date 2018-12-05 |
| User-mode WFP filter (own provider/sublayer, `FWPM_CONDITION_ALE_APP_ID` at `FWPM_LAYER_ALE_AUTH_CONNECT_V4/V6`) | App device path, local user SID, package SID, remote/local address & port, protocol, interface, profile, flags incl. `IS_LOOPBACK` | Connect / accept of a new flow | Content, host names, processes that share one binary, anything after connect | Base Filtering Engine session, administrator rights; arbitration against Bitdefender's sublayer (weight 65280) unknown | NOT PROBED (needs an `FwpmFilterAdd` program; not run) | REPORTED | Filtering condition identifiers ms.date 2024-05-02; WFP architecture ms.date 2018-05-31; flags ms.date 2018-05-31 |
| Kernel-mode WFP callout driver | Stream and datagram data per flow, connect/bind redirection, reclassification | Anything it can parse: deep inspection, stream modification, redirection | Encrypted content (TLS) unless intercepted | Kernel driver + signing/attestation (see R2-D report) | Bitdefender's model: IGNIS 24 callouts, BDDCI4 20, ATC 8 registered (MEASURED); a governor's own driver: not built | REPORTED + MEASURED | WDK callout intro ms.date 2024-09-27; `03-wfp-parse2.log`, `03-wfp-parse3.log` |
| DNS (client NRPT, DoH settings; server-side DNS policy) | Query names per namespace; client subnet/protocol/type on a Windows Server DNS | Resolution of listed names | Per-application attribution (the DNS Client service issues the query); in-app DNS-over-HTTPS; direct-IP connections | Config only | NRPT entries = 0; Wi-Fi DNS 10.0.10.1 (no DoH template); DoH `AutoUpgrade False` on all 12 known servers | MEASURED + REPORTED | `04-dns-tls-adapters.log`; DNS policy page ms.date 2021-01-05 |
| TLS (Transport Layer Security) content | Nothing without a trusted interception root | — | All content | Installing a root CA = a security-posture change; out of bounds for a consumer governor | Bitdefender root present in LocalMachine\Root and CurrentUser\Root (thumbprint CE4A4B36…); SslStream to example.com:443 saw a public chain (`Cloudflare TLS Issuing ECC CA 3, O=SSL Corporation`), TLS 1.3, policy errors None — NOT intercepted on that path | MEASURED | `04-dns-tls-adapters.log` |
| Loopback (127.0.0.1 / ::1) | WFP exposes `FWP_CONDITION_FLAG_IS_LOOPBACK` at the ALE connect/accept layers | AppContainer (UWP) loopback is blocked by a Windows Firewall *default block filter*; classic apps: not established | Classic-app loopback per program by a Windows Firewall rule: not verifiable here | — | The only Windows Firewall filters in the engine here are 18 `AppContainerLoopback` / `AppContainerBoottimeFilter` entries; listeners seen on 127.0.0.1: ports 24830 (AsusSoftwareManager), 28385/28390 (System), 55168 (cceventapp) | MEASURED (what exists) + REPORTED (AppContainer default) | `03-wfp-parse3.log`, `04-…log`; Filter Origin Audit Log ms.date 2025-04-07; UWP troubleshooting ms.date 2025-04-07; flags ms.date 2018-05-31 |
| VPN / tunnel adapters | Per-app identity survives a tunnel (app id is the image path, not the interface); per-address rules do not (all traffic goes to the tunnel endpoint) | — | Address/port-based policy | — | Private Internet Access installed, service running, WireGuard tunnel service and `pia-wintun` driver stopped; its WFP provider persistent with 0 filters; WAN Miniports, Hyper-V Default Switch present | MEASURED (inventory); the "survives" claim is derived | `04-dns-tls-adapters.log`, `03-wfp-parse3.log` |
| Processes sharing one binary path | `ALE_APP_ID` = image device path; two processes of the same exe are one identity | — | Any per-instance decision | — | The project's own rule already sidesteps this by matching the user SID instead of the exe (`blarai-coder-deny-outbound`, "per-SID, not per-exe") | MEASURED (rule text) + derived | `02c-…log` registry entry |

## 3. WFP provider table (dump 02:49:47 EDT, rule BLARAI-STUDY-PROBE-1549 in place; re-parsed 09:32 with a BOM-safe decode)

Decode: both XML files carry a UTF-8 byte-order mark (`EF BB BF`); `utf-8-sig` decoded them (utf-16 fallback not needed).
2405 filters in `wfp-filters.xml`; 20 providers, 32 sublayers, 134 callouts, 20 BFE sessions in `wfp-state.xml`
(state timestamp 2026-09-17T06:49:47Z). Parser: Python 3.14.3, stdlib `xml.etree` (`parse_wfp3.py`).

| Provider display name | Provider key | Filters | of which callout-action | permit | block | Callouts registered |
|---|---|---|---|---|---|---|
| Bitdefender IGNIS Provider (driver `ignisv2.sys`) | {64756d6d-7950-726f-7669-646572000000} | **1978** | 1952 | 26 | 0 | 24 (ALE connect/accept v4+v6, transport in/out, IP forward, stream v4/v6) |
| Bitdefender BDDCI4 Provider (driver `bddci4.sys`; 3 provider keys, one carries the filters) | {88cb63ee-8a0a-4923-bf91-90fa46ba84ba} | **198** | 186 | 12 | 0 | 20 (flow-established, stream, datagram, connect, accept) |
| BD ATC — "Active Threat Control" (driver `atc.sys`) | {eb7a38dd-22f6-4788-b883-70566ba18fa0} | 0 | — | — | — | 8 (connect-redirect, bind-redirect, flow-established, stream, v4+v6) |
| Microsoft — MPSSVC Windows Service Hardening | FWPM_PROVIDER_MPSSVC_WSH | 176 | 0 | 154 | 22 | — |
| Microsoft — MPSSVC App Isolation (`@bfe.dll,-1217`) | FWPM_PROVIDER_MPSSVC_APP_ISOLATION | 24 | 0 | 16 | 8 | — |
| **Microsoft — MPSSVC Windows Firewall** | FWPM_PROVIDER_MPSSVC_WF | **18** (all `AppContainerLoopback` / `AppContainerBoottimeFilter`) | 0 | 12 | 6 | — |
| Microsoft — Teredo firewall provider | {893a4f22-…} | 10 | 2 | 7 | 1 | — |
| Microsoft — edge traversal socket option | {58b46077-…} | 1 | 0 | 0 | 1 | — |
| Private Internet Access Firewall (persistent) | {08de3850-…} | 0 | — | — | — | — |
| Microsoft built-ins with 0 filters: IKEEXT, IPsec Policy Agent (flag DISABLED), TCP Chimney Offload, MPSSVC EDP, IPsec DoS Protection, TCP Templates, MPSSVC Tenant Restrictions, Defender Firewall IPsec, NDU | — | 0 | — | — | — | 30 Microsoft-named + 52 unnamed built-in callouts |

Sublayer arbitration order (weight, higher evaluated first): Bitdefender BDDCI4 **65280** › RPC audit 49152 › … › Universal 32768 ›
… › Private Internet Access 9000 › … › Bitdefender BDDCI4 (second) 256 › Bitdefender IGNIS 43 › BD ATC "Generic inspection
filters" 12 › … › MPSSVC Windows Firewall **2** › Inspection 0.

Findings from the filter table (MEASURED):
- The probe rule: 0 filters (name / GUID `77621ff9` search). The project rule `blarai-coder-deny-outbound`: 0 filters.
- `FWPM_CONDITION_ALE_APP_ID` appears on 174 filters, all Microsoft's (Windows Service Hardening); on **0** Bitdefender filters.
  Bitdefender's 1978 IGNIS filters at the ALE layers carry either no condition (426 of the 470 at `ALE_AUTH_CONNECT_V4`) or
  port/protocol/address conditions, and 1952 of them have action `FWP_ACTION_CALLOUT_UNKNOWN` — the per-application decision is
  made inside the kernel callout, invisible to the filter table. A governor cannot read Bitdefender's per-app policy from WFP.
- `FWPM_CONDITION_ALE_USER_ID` appears on 168 filters (152 Service Hardening, 16 App Isolation); the six Windows Firewall
  block filters that exist are AppContainer-loopback blocks keyed on the app-container SID.
- Bitdefender holds WFP sessions from `bdservicehost.exe` PID 2976 (three "Bitdefender BDDCI4 Session", one
  "Bitdefender IGNIS Session", one kernel session).

## 4. Firewall state (MEASURED, 02:47–02:48 and re-read 09:33)

- Profiles (ActiveStore): Domain / Private / Public all `Enabled True`, `DefaultInboundAction Block`, `DefaultOutboundAction
  Allow`, `AllowLocalFirewallRules True`. Local persistent store shows `NotConfigured` for both defaults. `netsh advfirewall show
  allprofiles`: `State ON`, `Firewall Policy BlockInbound,AllowOutbound`, **`LocalFirewallRules N/A (GPO-store only)`**,
  `LocalConSecRules N/A (GPO-store only)`, logging of allowed and dropped connections both `Disable`.
- Services: `BFE` (Base Filtering Engine) Running/Automatic; `mpssvc` (Windows Defender Firewall) Running/Automatic.
  Bitdefender: BDAppSrv, BDAuxSrv, BDProtSrv, bdredline, bdredline_agent, BDSafepaySrv, UPDATESRV, VSSERV all Running.
  Kernel drivers loaded: `atc`, `BdDci4`, `bdprivmon`, `Ignisv2`, `Trufos` Running; `bdelam` (boot) and `bduefiscan` Stopped.
- Security Center (`root/SecurityCenter2`, 02:47:43). `productState` is an undocumented WMI (Windows Management
  Instrumentation) bit-field; the decode below is the widely used community decoding (byte 2 = owner, byte 3 = 0x10 enabled /
  0x00–0x01 disabled, byte 4 = signature status), not a Microsoft-documented one:
  - FirewallProduct: **Bitdefender Firewall** `0x041000` → third-party owner, enabled ON, timestamp 2026-09-16 21:44:15 GMT;
    **McAfee** `0x041000` → "enabled ON" but `C:\Program Files\McAfee` does not exist (stale registration, timestamp 2025-03-30).
  - AntiVirusProduct: **Windows Defender** `0x060100` → OFF; **McAfee** `0x041000` (stale); **Bitdefender Antivirus** `0x041000` ON.
  - Bitdefender's own registry mirrors this: `HKLM\SOFTWARE\Bitdefender\wsc\fw\status = 0` with `substatus = 1` on all three
    profiles; `FeaturesController` lists `"firewall":{"allowed":true}`.
- Third-party registration held by mpssvc (`HNetCfg.FwProducts`, 03:04:14 and 09:33:20): registered products = 1 —
  `Bitdefender Firewall`, `RuleCategories = 0,1,2` (BOOT, STEALTH, FIREWALL; not 3 = CONSEC), signed exe
  `C:\Program Files\Bitdefender\Bitdefender Security\wsccommunicator.exe`.

## 5. Per-process block probe (MEASURED)

Probe binary: `probe-curl.exe`, a byte-identical copy of the system curl (SHA-256
`73D24149FF289AFC49EC41F08918EF9FAA727D39AD993E929757DC2DDAFAB805`, curl 8.21.0 Windows/Schannel, release 2026-06-24).
Request: `probe-curl.exe -sS -o NUL -w '%{http_code}' https://example.com --max-time 10`.

| Phase | Time (EDT) | Runs | Result |
|---|---|---|---|
| Baseline, no rule | 02:48:33.602–02:48:34.236 | 5 | exit 0, HTTP 200 ×5; 337/156/156/148/156 ms |
| Rule added (Block, Outbound, Program = probe-curl.exe, Profile Any) | 02:48:48 (add 664 ms; event 2097 at 02:48:49.405) | — | Rule `{77621ff9-401c-4c18-986a-ca5351706074}` Enabled True, Action Block, `PrimaryStatus OK`; `netsh` verbose shows Program = probe-curl.exe, all other fields Any; registry `FirewallRules` entry `v2.33|Action=Block|Active=TRUE|Dir=Out|App=…probe-curl.exe|Name=BLARAI-STUDY-PROBE-1549` |
| **With rule** | 02:48:50.960–02:48:51.624 | 5 | **exit 0, HTTP 200 ×5**; 161/157/163/165/160 ms — no block, no slowdown |
| With rule, during the WFP capture attempt | 02:58:11.339, 02:58:11.568 | 2 | exit 0, 200 ×2 |
| After first removal | 03:00:35 | 1 | exit 0, 200, 664 ms |
| Mid-run test 2 — (a) fresh process every ~1.6 s | 03:02:36.126–03:03:01.279 (rule added 03:02:46.203, removed 03:02:54.733) | 16 | **exit 0, 200 ×16** — runs 7–11 (03:02:46.467–03:02:53.701) fell inside the rule window |
| Mid-run test 2 — (b) ONE long-lived process, 16 requests at 1/s, `Connection: close` (new TCP connection each, `newconn=1` on every line) | started 03:02:36.255, PID 12880 | 16 | **200 ×16**, per-request 0.11–1.32 s; requests ~10–18 fell inside the rule window |
| Final | 03:03:06 | 1 | exit 0, 200, 279 ms |

Mid-run test 1 (03:00:54–03:01:09; rule added 03:01:00.166, removed 03:01:08.968) is **invalid**: arm (b) failed at startup
(`curl: option --fresh-connect: is unknown`) and arm (a) wrote no lines; the predecessor re-ran it as test 2 with script files.

Answer to "did the block take effect for an already-running process?": **not answerable here** — no process, new or
already running, was ever blocked, because Windows Firewall rules are not enforced on this machine. The long-lived-process
harness (`midrun-single.ps1`) ran cleanly and is ready for a machine where Windows owns the firewall.

Conditions for every number: elevated PowerShell 7; three other study agents and Bitdefender were running concurrently and were
not held fixed; the curl latencies are single observations per run, not a latency measurement.

## 6. Add / remove timing (MEASURED, `02c-remove-timing-midrun.log`)

`New-NetFirewallRule` / `Remove-NetFirewallRule -DisplayName 'BLARAI-STUDY-PROBE-1549'`, PowerShell 7, elevated, 5 cycles
back-to-back at 03:00:41–03:00:52, plus the first add (02:48:48) and first remove (03:00:35) as single observations.

| Cycle | Time | Add (ms) | Remove (ms) |
|---|---|---|---|
| first add / first remove (N=1 each) | 02:48:48 / 03:00:35 | 664 | 2246 |
| 1 | 03:00:41.745 | 466 | 2702 |
| 2 | 03:00:44.675 | 580 | 2339 |
| 3 | 03:00:47.381 | 444 | 2210 |
| 4 | 03:00:50.301 | 299 | 2606 |
| 5 | 03:00:52.641 | 174 | 2136 |
| **N=5 min / median / max** | | **174 / 444 / 580** | **2136 / 2339 / 2702** |

Removal is consistently ~5× slower than addition (the cmdlet enumerates the store to match `-DisplayName`). Conditions as in §5.
The firewall event log independently records each add (2097) and delete (2052) within ~0.1–0.4 s of the cmdlet timestamps
(see §8). These are cmdlet round-trip times with Bitdefender owning the category; whether instantiation into BFE adds time when
Windows owns the firewall was not measurable here.

## 7. DNS, TLS, adapters (MEASURED 02:56:59–02:57, `04-dns-tls-adapters.log`)

- DNS servers: Wi-Fi `10.0.10.1` (IPv4, the LAN router); every other interface carries only the Windows site-local defaults
  `fec0:0:0:ffff::1–3`. `Get-DnsClientNrptPolicy`: **0 entries** (the Name Resolution Policy Table, NRPT, is keyed by DNS
  namespace — a per-domain instrument, not a per-application one). `Get-DnsClientDohServerAddress`: the 12 built-in
  DNS-over-HTTPS (DoH) templates (Quad9, Google, Cloudflare) all `AutoUpgrade False`, `AllowFallbackToUdp False`; the
  configured server 10.0.10.1 has no template, so DoH is not in use. Suffix search list empty.
- The Microsoft page named in the brief (`apply-filters-on-dns-queries`, ms.date 2021-01-05) documents **Windows Server DNS
  policy** (server-side query filters), not the client NRPT. Its criteria: Client Subnet, Transport Protocol, Internet Protocol,
  Server Interface IP address, FQDN (with wildcard), Query Type, Time of Day — none is per-application. Read together with the
  measured NRPT: DNS on Windows, client or server side, filters by name/network, never by the calling process.
- Certificates: `CN=Bitdefender Personal CA.Net-Defender, O=Bitdefender, OU=IDS, C=US`, thumbprint
  `CE4A4B36AA253FF007EFD1E6D72EBDBCAFDE4564`, valid to 2036-07-05, in **both** `LocalMachine\Root` and `CurrentUser\Root`.
  Two further private roots are present (`CN=LocalAI-Root-CA`, `CN=LocalAI Root CA`) in both stores — observed, not attributed.
- TLS chain actually seen from this host to `example.com:443` (System.Net.Security.SslStream): protocol TLS 1.3, cipher
  `TLS_AES_256_GCM_SHA384`, leaf `CN=example.com` issued by `CN=Cloudflare TLS Issuing ECC CA 3, O=SSL Corporation, C=US`,
  policy errors None — a public chain; Bitdefender did not intercept that path. Interpretation for the product: the comparable
  consumer product carries the *capability* for TLS interception (root installed) but does not apply it to an arbitrary
  Schannel client; a governor cannot assume it can read TLS content and must not install a root to try.
- Adapters: Wi-Fi (Intel AX211) Up; Hyper-V `vEthernet (Default Switch)` Up; Microsoft Wi-Fi Direct ×2 Disconnected;
  WAN Miniports (PPTP, L2TP, SSTP, IKEv2, PPPOE) Disconnected; Teredo / IP-HTTPS / 6to4 Not Present.
  Private Internet Access installed (`C:\Program Files\Private Internet Access`), `PrivateInternetAccessService` Running,
  `PrivateInternetAccessWireguard` Stopped, drivers `pia-wintun` and `WireGuard` Stopped.
- Loopback listeners at probe time: `127.0.0.1:24830` (AsusSoftwareManager), `:28385` and `:28390` (System), `:55168`
  (cceventapp). No local model server was listening.

## 8. Verbatim command log, condensed faithfully from the predecessor's logs

```
02:47:18  Get-NetFirewallProfile                      -> Domain/Private/Public Enabled True; defaults NotConfigured (local store)
          Get-Service mpssvc, BFE                      -> both Running/Automatic
          Get-Service / Get-Process Bitdefender*       -> 8 services Running; bdservicehost x5, bduserhost x4, bdntwrk, bdagent, updatesrv
02:47:43  Get-CimInstance root/SecurityCenter2 FirewallProduct / AntiVirusProduct -> see §4
          Get-NetFirewallProfile -PolicyStore ActiveStore -> Enabled True, Inbound Block, Outbound Allow (x3)
          netsh advfirewall show allprofiles           -> State ON; LocalFirewallRules N/A (GPO-store only) (x3)
02:48:11  Get-ItemProperty HKLM:\SOFTWARE\Bitdefender\* (read-only) -> wsc\fw status 0, substatus 1 x3; FeaturesController firewall allowed
          driverquery                                  -> atc, BdDci4, bdprivmon, Ignisv2, Trufos Running
02:48:31  Copy-Item curl.exe -> probe-curl.exe; Get-FileHash x2 -> equal; probe-curl.exe --version -> 8.21.0
          Get-NetFirewallRule -DisplayName BLARAI-STUDY-PROBE-1549 -> ABSENT (pre-check)
02:48:33  probe-curl … https://example.com x5           -> 200 x5 (baseline)
02:48:48  New-NetFirewallRule -DisplayName 'BLARAI-STUDY-PROBE-1549' -Direction Outbound -Program <probe-curl.exe> -Action Block -Profile Any
                                                        -> 664 ms; {77621ff9-…}; Enabled True; PrimaryStatus OK   [event 2097 02:48:49.405]
          Get-NetFirewallApplicationFilter             -> Program = probe-curl.exe
02:48:50  probe-curl … x5 (WITH RULE)                   -> 200 x5
02:49:47  netsh wfp show state file=wfp-state.xml       -> 229 ms, 4,300,036 bytes
          netsh wfp show filters file=wfp-filters.xml   -> 185 ms, 3,009,638 bytes
02:50:07  netsh advfirewall firewall show rule name=BLARAI-STUDY-PROBE-1549 verbose -> Enabled Yes, Out, Block, Program set
          registry FirewallRules {77621ff9-…} = v2.33|Action=Block|Active=TRUE|Dir=Out|App=…|Name=BLARAI-STUDY-PROBE-1549|
          SharedAccess EnableFirewall=1 x3; Get-NetFirewallSetting; port/address/interface/service filters -> all Any
          Get-WinEvent …Firewall (last 20)              -> 2097 at 02:48:49 for the probe rule
02:50:16  netsh wfp capture start file=wfp-capture-with-rule.cab
02:52:35  inline PowerShell XML parse                   -> 0 providers / 0 filters (wrong element path; superseded)
02:55:19  python parse_wfp.py                           -> 20 providers, 32 sublayers, 2405 filters; probe rule matches = 0
02:56:30  python parse_wfp2.py                          -> 134 callouts; IGNIS APP_ID filters = 0; BFE sessions
02:56:59  Get-DnsClientServerAddress / -DohServerAddress / -NrptPolicy / -GlobalSetting / Get-DnsClient
          Get-ChildItem Cert:\LocalMachine\Root, Cert:\CurrentUser\Root | ? Subject -match Bitdefender -> 1 each
          SslStream example.com:443                     -> TLS1.3, Cloudflare/SSL Corp chain, errors None
          Get-NetAdapter -IncludeHidden; PIA services/drivers; Get-NetTCPConnection -LocalAddress 127.0.0.1 -State Listen
02:58:10  wfp-capture-with-rule.cab written (487,896 bytes)
02:58:11  probe-curl … x2                                -> 200 x2   (AFTER the capture had ended)
          netsh wfp capture stop                        -> "No capture is in progress."
03:00:21  STATE CHECK: rule PRESENT Enabled=True Action=Block
          Remove-NetFirewallRule -DisplayName 'BLARAI-STUDY-PROBE-1549' -> 2246 ms   [event 2052 03:00:35.301]
          Get-NetFirewallRule …                          -> ABSENT;  probe-curl x1 -> 200
03:00:41  5x { New-NetFirewallRule …; Remove-NetFirewallRule … } -> §6   [events 2097/2052 03:00:38.735 … 03:00:52.638]
03:00:54  MID-RUN TEST 1 (loop pid 18712, single pid 24520); rule ADDED 03:01:00.166, REMOVED 03:01:08.968 -> INVALID (--fresh-connect unknown)
03:01:09  FINAL VERIFICATION: ABSENT; netsh "No rules match"; registry BLARAI entries = 1 (blarai-coder-deny-outbound, pre-existing); curl 200
03:02:14  expand / tar.exe wfp-capture-with-rule.cab     -> cap-with-rule/…/wfp-capture-with-rule.etl (917,504 B) + .xml (9,171,329 B)
03:02:34  MID-RUN TEST 2 (midrun-loop.ps1 pid 17868, midrun-single.ps1 pid 12880); rule ADDED 03:02:46.203, REMOVED 03:02:54.733
                                                        -> (a) 16/16 = 200; (b) 16/16 = 200, newconn=1 each   [events 03:02:45.813 / 03:02:54.730]
03:03:06  FINAL VERIFICATION: Get-NetFirewallRule ABSENT; netsh "No rules match"; registry BLARAI = 1 (pre-existing project rule only); curl 200
03:04:14  New-Object -ComObject HNetCfg.FwProducts       -> 1 product: Bitdefender Firewall, RuleCategories 0,1,2
          grep wfp-filters.xml for blarai-coder-deny-outbound -> 0; filters with ALE_USER_ID = 168
          Get-NetFirewallRule -DisplayName blarai-coder-deny-outbound (read-only) -> Enabled True, Outbound, Block (NOT touched)
--- finisher ---
09:32     python parse_wfp3.py (utf-8-sig, utf-16 fallback)  -> 2405 filters; provider table §3; callouts 134 (path .//callouts/item)
          capture XML: root wfpdiag {sysInfo, initialState, firewallState, events(16 items), finalState, firewallState}; probe-curl mentions = 0
09:33:20  Get-NetFirewallRule -DisplayName '*BLARAI-STUDY*' -> ABSENT
          netsh advfirewall firewall show rule name=BLARAI-STUDY-PROBE-1549 -> "No rules match the specified criteria."
          registry FirewallRules values matching BLARAI-STUDY -> 0  (blarai-coder-deny-outbound still present, untouched)
          Get-WinEvent 2097/2052 02:45–03:10 -> the 20 probe-rule events listed above + winget rule churn 02:50:15 (system)
                     + 02:59:05 BlarAIStudyProbe1549 add x2 / delete x2 (P3b-os agent's AppContainer profile create/delete, see §10)
          Get-WinEvent 2097/2052 after 03:10 mentioning BLARAI-STUDY -> none
          HNetCfg.FwProducts -> unchanged (1, Bitdefender, 0,1,2);  ActiveStore profiles -> unchanged
09:33:22  end
```

## 9. Not verified (honest list)

1. **Whether the same per-program Block rule works where Windows owns the FIREWALL category.** No such machine was available;
   Bitdefender may not be disabled under the study rules. The measured non-block is a Bitdefender-present result, and the
   mechanism (category ownership) is sourced to Microsoft's API text, not to a controlled A/B.
2. **Whether a governor-owned user-mode WFP filter is honoured next to Bitdefender.** Not probed; needs an `FwpmFilterAdd`
   program (Python ctypes would do, no install needed). Bitdefender's BDDCI4 sublayer at weight 65280 evaluates first, so the
   answer depends on WFP arbitration semantics I did not exercise. This is the single most useful next probe for this seam.
3. **Already-running-process behaviour.** Unanswerable while nothing blocks (§5). The harness for it exists and ran cleanly.
4. **The WFP capture.** The `.cab` was written at 02:58:10.164, 1.2 s before the two "during capture" curl runs, and the stop
   command reported no capture in progress; the extracted `wfp-capture-with-rule.xml` has 16 event items, none mentioning
   probe-curl. It shows nothing about the probe and was not re-run.
5. **Loopback for classic (non-AppContainer) programs.** No Microsoft statement was found in this pass on whether a per-program
   Windows Firewall rule applies to 127.0.0.1 traffic, and it cannot be measured here because Windows Firewall rules are not
   instantiated at all. Established only: AppContainer loopback is a default block (Microsoft, ms.date 2025-04-07); WFP itself
   exposes `FWP_CONDITION_FLAG_IS_LOOPBACK` at the ALE connect/accept layers (ms.date 2018-05-31).
6. **Bitdefender TLS interception in browsers.** Only a .NET SslStream path was tested (not intercepted). Browser paths were not.
7. **GPO-store rules under third-party ownership.** `netsh` says "GPO-store only"; whether Group Policy Object rules are enforced
   while Bitdefender owns the category was not probed (would need a GPO change — out of bounds).
8. **Address family of the curl requests** (IPv4 vs IPv6 to example.com) was not recorded.
9. **`productState` decoding** (§4) follows the community decoding of an undocumented WMI field; the services and driver list,
   not the decode, are the evidence that Bitdefender is active and Defender AV is off.
10. **The claim that per-app identity "survives a tunnel"** (§2, VPN row) is derived from how `ALE_APP_ID` is defined, not
    measured; the tunnel was down throughout.
11. **Windows Firewall rule fields** (§2, row 1) were taken from this machine's own `netsh … verbose` output and registry
    string, not from a Microsoft reference page.

## 10. Cleanup ledger

| Item | Added | Removed | Verification |
|---|---|---|---|
| Firewall rule `BLARAI-STUDY-PROBE-1549` (first instance, GUID {77621ff9-401c-4c18-986a-ca5351706074}) | 02:48:48 (event 2097 02:48:49.405) | 03:00:35 (event 2052 03:00:35.301) | cmdlet ABSENT 03:00 |
| Same name, 5 timing cycles (new GUID each time, not logged) | 03:00:38.735 / :41.973 / :44.942 / :47.524 / :50.402 | 03:00:41.604 / :44.672 / :47.337 / :50.233 / :52.638 | "after cycles: rule ABSENT" |
| Same name, mid-run test 1 | 03:01:00.166 (event 03:01:00.098) | 03:01:08.968 (event 03:01:08.965) | FINAL VERIFICATION 03:01:09 ABSENT |
| Same name, mid-run test 2 | 03:02:46.203 (event 03:02:45.813) | 03:02:54.733 (event 03:02:54.730) | FINAL VERIFICATION 03:03:06 ABSENT; netsh no match; registry BLARAI-STUDY 0 |
| **Finisher re-verification** | — | — | **09:33:20 EDT: `Get-NetFirewallRule -DisplayName '*BLARAI-STUDY*'` ABSENT; `netsh … show rule` "No rules match"; registry `FirewallRules` values matching BLARAI-STUDY = 0; no 2097/2052 event naming BLARAI-STUDY after 03:10.** The compiler's 09:21 check agrees. The finisher added no rule (the probe demonstrably ran), so no `…-B` rule exists. |
| `netsh wfp capture` trace session | 02:50:16 | ended by itself before 02:58:10 (cab written); `capture stop` at 02:58 → "No capture is in progress." | finisher: see line below |
| `probe-curl.exe` copy (818,512 B) | 02:48:31 | kept as evidence under S (not on PATH, not executed since 03:03) | — |
| Pre-existing project rule `blarai-coder-deny-outbound` | not created by this probe | **not touched** | present at 03:04 and 09:33, Enabled True |
| Events at 02:59:05 named `BlarAIStudyProbe1549` (2097 ×2, 2052 ×2, 0.5 s apart) | P3b-os agent's `CreateAppContainerProfile` (Windows auto-creates firewall rules for an AppContainer profile) | P3b-os agent's `DeleteAppContainerProfile` 0.5 s later | `probes/p3b/appcontainer_probe.log` lines 2 and 46; not a p3a artefact |

Security settings, Bitdefender, Defender, WDAC, SAC, UAC, Windows features, BlarAI and its VM, scheduled tasks: untouched by this seam's probes (only reads, one reversible firewall rule, one trace session).

## 11. Sources

MEASURED — this machine, 2026-09-17 02:47–03:04 and 09:32–09:33 EDT, logs under S (paths at top).

REPORTED — Microsoft Learn, fetched 2026-09-17 09:35–09:40 EDT (dates are the page's `ms.date`; `updated_at` in brackets):
- Windows Filtering Platform start page — ms.date 2018-05-31 [2025-03-11].
  https://learn.microsoft.com/en-us/windows/win32/fwp/windows-filtering-platform-start-page — "The WFP API consists of a
  user-mode API and a kernel-mode API"; "Windows Filtering Platform is a development platform and not a firewall itself. The
  firewall application that is built into … Windows Firewall with Advanced Security (WFAS) is implemented using WFP."
- WFP Architecture — ms.date 2018-05-31 [2025-03-11].
  https://learn.microsoft.com/en-us/windows/win32/fwp/windows-filtering-platform-architecture-overview — "The Base Filtering
  Engine (BFE) is a user-mode service (bfe.dll running in a svchost.exe process)"; "Callout drivers provide additional filtering
  functionality by adding custom callout functions to the filter engine at one or more of the kernel-mode filtering layers.
  Callouts support deep inspection and packet as well as stream modification."
- Introduction to Windows Filtering Platform Callout Drivers (Windows Driver Kit) — ms.date 2024-09-27 [2025-03-25].
  https://learn.microsoft.com/en-us/windows-hardware/drivers/network/introduction-to-windows-filtering-platform-callout-drivers
  (the URL given in the brief, `/windows/win32/fwp/callout-drivers`, returns 404) — "Callouts extend the capabilities of the
  Windows Filtering Platform by processing TCP/IP-based network data in ways that are beyond the scope of the simple filtering
  functionality"; tasks listed: Deep Inspection, Packet Modification, Stream Modification, Data Logging.
- Filtering condition identifiers (Fwpmu.h) — ms.date 2024-05-02 [2024-09-09].
  https://learn.microsoft.com/en-us/windows/win32/fwp/filtering-condition-identifiers- — `FWPM_CONDITION_ALE_APP_ID`: "The
  lower-case fully qualified device path of the application"; `FWPM_CONDITION_ALE_USER_ID`: "The identification of the local
  user"; `FWPM_CONDITION_ALE_PACKAGE_ID`: "The security identifier (SID) of an app container". No condition matches payload;
  the two name-typed conditions (`FWPM_CONDITION_PEER_NAME`, `FWPM_CONDITION_ALE_EFFECTIVE_NAME`) depend on the application
  volunteering a target name through an API (a derived reading, flagged as such).
- Filtering condition flags (Fwptypes.h) — ms.date 2018-05-31 [2024-05-08].
  https://learn.microsoft.com/en-us/windows/win32/fwp/filtering-condition-flags- — `FWP_CONDITION_FLAG_IS_LOOPBACK`: "Tests
  whether the network traffic is loopback traffic", available at `FWPM_LAYER_ALE_AUTH_CONNECT_V{4|6}` and
  `FWPM_LAYER_ALE_AUTH_RECV_ACCEPT_V{4|6}` among others.
- INetFwProduct (netfw.h) — ms.date 2018-12-05 [2024-02-22].
  https://learn.microsoft.com/en-us/windows/win32/api/netfw/nn-netfw-inetfwproduct — "allows an application or service to access
  the properties of a third-party firewall registration."
- INetFwProduct::get_RuleCategories — ms.date 2018-12-05 [2024-02-22].
  https://learn.microsoft.com/en-us/windows/win32/api/netfw/nf-netfw-inetfwproduct-get_rulecategories — "indicates the rule
  categories for which the third-party firewall wishes to take ownership from Windows Firewall."
- NET_FW_RULE_CATEGORY (icftypes.h) — ms.date 2018-12-05 [2024-02-22].
  https://learn.microsoft.com/en-us/windows/win32/api/icftypes/ne-icftypes-net_fw_rule_category — BOOT = 0 "boot time filters",
  STEALTH "stealth filters", FIREWALL "firewall filters", CONSEC "connection security filters".
- Use DNS Policy for Applying Filters on DNS Queries (Windows Server) — ms.date 2021-01-05 [2025-09-22].
  https://learn.microsoft.com/en-us/windows-server/networking/dns/deploy/apply-filters-on-dns-queries — server-side criteria
  listed in §7; no per-application criterion.
- Filter Origin Audit Log — ms.date 2025-04-07 [2025-04-07].
  https://learn.microsoft.com/en-us/windows/security/operating-system-security/network-security/windows-firewall/filter-origin-documentation
  — "AppContainer loopback" is one of the firewall *default block filters*; "Network drop events from the AppContainer loopback
  block filter origin occur when localhost loopback isn't enabled properly for the Universal Windows Platform (UWP) app".
- Troubleshooting UWP App Connectivity Issues in Windows Firewall — ms.date 2025-04-07 [2025-04-07].
  https://learn.microsoft.com/en-us/windows/security/operating-system-security/network-security/windows-firewall/troubleshooting-uwp-firewall
  — "By default, UWP applications aren't allowed to receive loopback traffic"; exemption via
  `CheckNetIsolation.exe LoopbackExempt -a -n=<AppContainer or Package Family>`. Says nothing about classic desktop apps.

Not used as evidence: Bitdefender's product documentation (none read); the `productState` bit-field decoding (undocumented).
