# MXC PR #1406 loopback-proxy probe (#1746 item a)

Question: with the self-built Microsoft MXC main build (commit 70fc7d52, contains PR #1406), can a process in MXC's tier-1
process container (BaseContainer) reach a host-side listener on 127.0.0.1:18099 while every other destination stays blocked,
using the "unpackaged non-AppContainer proxy" configuration (`networking.md`; scoping copy in `../sources/mxc-pr1406-scoping/`)?

## Result (n = 3 runs per condition, separate launcher invocations, every run preceded by `--dry-run`)

Judged from the HOST-SIDE listener log (each run: fresh listeners on 127.0.0.1:18099, 127.0.0.1:18100 and 10.0.10.12:18099, each
host-control-tested before the launch). The container's own report supplies the error codes for destinations that cannot log.

| Condition | Launcher / config | Dry-run | Reached 127.0.0.1:18099 (listener log) | 18100 | LAN 10.0.10.12:18099 | 1.1.1.1:443 and example.com:443 (container report) |
|---|---|---|---|---|---|---|
| T-on | main build; egress deny, ingress allow + hostLoopback allow, `runtimeConfig.networkProxy http://127.0.0.1:18099`, no allowedProxyPeer | passed 3/3 | YES 3/3: 5 log lines per run (1 raw socket with marker, 4 proxied `GET http://mxc-proxy-probe.invalid/...` from urllib, curl.exe, WinHTTP default, WinHTTP automatic) | 0 hits, WinError 10013, 3/3 | 0 hits, 10013, 3/3 | 10013 on both, 3/3 |
| P-18100 (scoping discriminator) | as T-on, proxy endpoint moved to 18100 | passed 3/3 | 0 hits, 10013, 3/3 | YES 3/3 (5 lines per run) | 0 hits | 10013 on both |
| L-off-c (baseline) | main build; no proxy, ingress deny, hostLoopback deny, egress deny | passed 3/3 | 0 hits; 10013 | 0 hits; 10013 | 0 hits; 10013 | 10013 / gaierror (DNS failed) |
| L-off-a (no proxy, hostLoopback allow) | main build | REJECTED 3/3: `network.ingress.hostLoopback='allow' is not supported by this version of Windows; host-loopback ingress requires native ProcessContainer support` | not launched | | | |
| L-off-b (proxy, hostLoopback deny) | main build | REJECTED 3/3: `a ProcessContainer proxy without allowedProxyPeer requires network.ingress.hostLoopback='allow'` | not launched | | | |
| V100 | signed v1.0.0 launcher, T-on config | REJECTED 3/3: same `hostLoopback='allow' is not supported ...` message as L-off-a | not launched | | | |

All 18 run records (9 launched: T-on, P-18100, L-off-c; 9 rejected at dry-run and not launched): `verify-clean` rc 0 after every run (NOTE: verify-clean only looks for the earlier #1740 study's own artifacts, so it is borrowed assurance; the real cleanliness evidence is the harness's own snapshot below, plus a reviewer's read-only check after a re-run that found WinHTTP on "Direct access", no loopback exemption and no MXC-named firewall rule); ACL hashes of the granted
folders, the `ProcessSandboxes\Mappings` registry key and the AppContainer mapping count unchanged; MXC state dir empty.
Per-run records: `raw/run-*.json`, `raw-p18100/run-*.json` (config, dry-run output, exit code, container output, full listener log, machine conditions, before/after state).
Batch headers (launcher sha256 and `--probe`, Windows build): `raw/batch-header.json`, `raw-p18100/batch-header.json`.
Condensed: `docs/performance/mxc_1406_probe_2026-10-11/summary.json`. Harness: `tools/probes/mxc_1406/`.

## Observations beyond the question

- The raw direct socket to the proxy endpoint also got through (1 of the 5 log lines per T-on run is a plain `GET /<marker>`): the container reaches the configured
  endpoint with any client, not only proxy-aware ones.
- Under T-on, DNS resolution of example.com succeeded inside the container (104.20.23.154, 172.66.147.243) while connecting to it was blocked (10013); under the L-off-c
  baseline resolution failed (gaierror). DNS is therefore a POSSIBLE side channel under this configuration; this is a hypothesis. Three things moved between T-on and L-off-c, not one: the proxy policy, the `networkLoopback` capability, and the `privateNetworkClientServer` capability that `ingress.default=allow` silently adds (MXC source: network_policy_helpers.rs and base_container_helpers.rs), so the DNS difference cannot be pinned to the proxy setting; DNS also resolved in the P-18100 condition (3 of 3). Only example.com was resolved, and on the unconfined host it resolved in 0.007 s (probably from the host cache), so it is NOT shown that a never-seen name is forwarded to an upstream resolver, which is what would make DNS an exfiltration channel. The discriminating tests are a unique random subdomain with a packet capture, and a no-proxy run with ingress allow and hostLoopback deny.
- HTTP_PROXY and HTTPS_PROXY (upper case only) were set in the container to the endpoint under T-on and P-18100; none under L-off-c.
- L-off-a and L-off-b cannot launch on the main build (rejected at validation), so the evidence that the endpoint reach comes from the proxy configuration is
  L-off-c (no proxy: both loopback ports blocked) and P-18100 (moving the endpoint moves the open port).

## Conditions

Host: Intel Core Ultra 7 258V, Windows 11 Pro 10.0.26200.9457, elevated console, AC power (BatteryStatus 2, 80 % charge), thermal zone 60.1 C, Bitdefender running
(14 processes, unchanged across runs), system CPU 36 to 78 % before each run (the harness's own process-sampling queries, Bitdefender, WMI and SearchIndexer were the
top consumers). Harness at BelowNormal priority. Launcher: main build `wxc-exec.exe` sha256 `3cf91a4598a9...279311`, unsigned; `--probe`: tier base-container,
baseContainerSupportsIdentitylessLoopbackProxy true, baseContainerSupportsIngressHostLoopbackAllow false. V100: Microsoft-signed, sha256 `aa444c0fc4b7...344031`.
Container payload: Python 3.14 from the throwaway fixture toolchain copy, UI lockdown off (as arms E1/E2). 2026-10-11 13:25 to 13:27 -04:00; each container run 0.5 to 0.9 s wall.

## Not tested

IPv6; UDP; other builds or Windows versions; a real model server (ports 8099 and 8000 were deliberately never touched); long duration or volume; a forwarding proxy
(the listener answers locally, so "all other destinations stay blocked" covers direct connections only, not tunnelled CONNECT or HTTPS through the proxy); a non-elevated
launcher; the identity-scoped (allowedProxyPeer) shape; the Hyper-V switch address 172.22.208.1. Instrument variance beyond 3 identical outcomes per condition was not
characterised (outcomes are binary and did not vary across runs).

## Review notes added after the independent review (2026-10-11)

- **Temporary upstream path.** The behaviour measured here sits on a code path MXC's own source marks as temporary (`base_container_runner.rs`: "Temporary compatibility for explicit identity-less proxies on PSEC 1.0-only hosts. Remove once those hosts support PSEC 1.1"; function `psec_1_0_proxy_loopback_workaround`). Anyone planning to rely on this for the coder is relying on a path Microsoft plans to remove.
- **Also not tested:** inbound connections to a listener inside the container (T-on grants `privateNetworkClientServer`, which normally permits inbound private-network connections), `::1`, 127.0.0.2, UDP, the real model ports 8099 and 8000 (deliberately untouched).
- **Observed and unexplained:** every launched run printed MXC stderr "Failed to find real location of ...python.exe"; MXC's own log warns that proxy support on Windows is best-effort and other HTTP stacks may bypass it. The thermal reading (60.1 C) is identical in all 18 records and is probably a static zone reading, not a measurement. The system CPU range 36 to 78 % includes records that were never launched (the launched runs ranged 45 to 66 %).
- **L-off-c and example.com:** name resolution failed first (gaierror), so no connection to example.com was attempted in that condition; 10013 applies to the numeric targets only.
- **Harness note.** The verdict counts any listener line not marked as a host control; it does not require the run tag. In the banked data there are zero untagged lines and zero lines before launch, so the counts stand (independent recount over all 18 records, and a one-run replication of T-on and L-off-c, agreed; an unconfined positive control on the same payload connected to 1.1.1.1:443, so the 10013 results are enforcement).
- **Provenance.** Source archive sha256 34aedd11a5ed3b630a2c426140c8234e491acf4675f027440e055cef804dd546 (zip comment is the full commit id of PR #1406's merge commit 70fc7d52, merged 2026-10-06T23:16:41Z); built with Rust 1.93 via `cargo build --release --target x86_64-pc-windows-msvc -p wxc -p plm -p wxc_winhttp_proxy_shim` (NOT `--locked`); binary sha256 3cf91a45...279311. The build log and archive are kept in `C:/blarai-spike-1740-mxc/build1406/` (a copy of build.log is banked beside this README as `build-provenance.log`).

