## NEP-0005 half-set study: Windows Filtering Platform loopback fence (config `nep0005_halfset`)

This section holds the data behind a set of claims about how a half-installed Windows Filtering Platform (WFP)
set reports, whether a plain re-install repairs it, and what a standard (non-administrator) token can change.
Every count, range and tally below is computed from the CSV tables in this folder by the script that built them
(`scripts/build_nep0005_dataset.py`), except these. Read from the run records, not the tables: the 7200 s hold
length and the exit code of the stopped first cycle. Typed from the run notes: the machine and Windows
description, the pinned srt-win commit, the permit range, the probe address 1.1.1.1:443, the 600 s restart
delay, the -04:00 offset and the pre-registered design. On this machine, under these conditions, and nothing
wider. The tables hold counts, codes, enumerated words, timestamps and hashes. They hold no program output text,
no path and no name.

### Setup and methodology

- Machine: Intel Core Ultra 7 258V (Lunar Lake) laptop, 31.3 GB; the Intel Arc 140V iGPU is present and unused here.
- Windows 11 Pro 10.0.26200, display version 25H2, build 26200.9457 (arm tables record `windows_build`).
- OpenVINO, GenAI, GPU driver and model: not applicable. No model runs in this study.
- Pinned source: the srt-win library of anthropics/sandbox-runtime at commit
  24eb39e94a6de386e83d126c52317d8e0fa49522 (not a model revision). Matrix scripts:
  `docs/research/containment-evidence-2026-10-05/nep0005-open-questions/scripts/` (repository-relative path; the
  public snapshot carries the same files).
- Matrix (`nep5_state_passes.csv`, `nep5_probes.csv`, `nep5_n1_passes.csv`): 15 states (N1, O1, O2, O3, O4, O5,
  O6, R0, R1, R2, R3, R4, R5, R6, R7), three passes each, 45 records. R-states use srt-win's library on test
  sublayer S1; O-states use our own filter objects on test sublayer S2; R7 puts our unlabelled block in S3; N1
  is the account's own standard token calling the engine directly. Per cycle the account connects to 6 loopback
  targets (v4 and v6 on ports 60085, 61763 and 61764; the permit range is 60080-60089) before any filter and
  with the state in place; every state is added and removed by key in the same pass.
- srt-win's own command line (`srtcli_states.csv`, `srtcli_commands.csv`, `srtcli_cycles.csv`): two counted runs
  (stock and patched build), 3 passes each; per pass the full set F, then the IPv6 block deleted (H6), the IPv4
  block deleted (H4) and both loopback permits deleted (HP), each followed by a plain `srt-win install` and a
  `--force` restore, then an uninstall with direct checks. A first cycle that stopped on its access-list check
  (exit 10) is not in these tables.
- Arms 2 and 3 (`arm2_hold_samples.csv`, `arm_runs.csv`): the 7200 s hold with one probe a minute, the
  persistent set added and removed (arm 3a) and the post-restart check (arm 3b); the probe is the account's
  connect to 1.1.1.1:443 through its scheduled task.

Tables (rows; the manifest carries the sha256 of each and of every source file):

| Table | Rows | One row is |
|---|---|---|
| `nep5_state_passes.csv` | 45 | one state in one pass |
| `nep5_probes.csv` | 504 | one account connect (before or during) |
| `nep5_n1_passes.csv` | 3 | one N1 pass |
| `nep5_phases.csv` | 5 | one run file |
| `srtcli_states.csv` | 42 | one half-set state in one pass of one build |
| `srtcli_commands.csv` | 36 | one re-install or restore after a state |
| `srtcli_cycles.csv` | 6 | one install/uninstall cycle of one build |
| `arm2_hold_samples.csv` | 120 | one once-a-minute probe of the hold |
| `arm_runs.csv` | 5 | one arm run record |

### Conditions

- Every matrix target is a loopback listener on 127.0.0.1 or [::1]; probe time per connect 1 to 41 ms. The
  matrix probes ran through an interactive logon of the test account, not the batch logon of its scheduled task.
  Each state stood for seconds. The three passes of a state ran back to back on one boot. Matrix run files:
  halfset 10:46:31 to 10:49:05 (-04:00), exit 0; ours 10:49:30 to 10:51:15 (-04:00), exit 0; n1 10:51:27 to
  10:52:51 (-04:00), exit 0.
- Bitdefender: not recorded during the matrix and the srt-win command-line runs. Bitdefender processes at start:
  arm 2 5, arm 3a 5; the arm 3b post-restart check records 2. Other machine load: not recorded.
- Account and operator controls: before any filter the account connected to 252 of 252 targets; the operator
  connected 252 of 252 loopback targets before and 252 of 252 during, with 0 watchdog failures. After every
  record, removal by key read back ok (45 of 45 records: sweep clean), provider present after: 0, filters left:
  0, export marker hits: 0.

### Findings, with the rows that carry them

Each line names its table and filter. A figure is a tally over the rows shown, nothing more. Passes are repeats
on one machine, not independent samples.

**Half-set reporting (srt-win's library, `nep5_state_passes.csv` and `nep5_probes.csv`, during rows)**

- R2 (IPv4 block deleted): status word installed (x3); filters in S1 3 (x3); targets connected v4:60085,
  v4:61763, v4:61764, v6:60085; targets blocked v6:61763, v6:61764 (3 passes).
- R3 (IPv6 block deleted): status word installed (x3); filters in S1 3 (x3); targets connected v4:60085,
  v6:60085, v6:61763, v6:61764; targets blocked v4:61763, v4:61764 (3 passes).
- R4 (both blocks deleted): status word absent (x3); filters in S1 2 (x3); targets connected v4:60085, v4:61763,
  v4:61764, v6:60085, v6:61763, v6:61764; targets blocked none (3 passes).
- R5 (both permits deleted): status word installed (x3); filters in S1 2 (x3); targets connected none; targets
  blocked v4:60085, v4:61763, v4:61764, v6:60085, v6:61763, v6:61764 (3 passes).
- R6 (full set keyed to a SID that resolves to no account): status word installed (x3); count of 6 targets the
  account connected to, per pass: 6 (x3).
- R7 (our unlabelled block in S3, S1 empty): status word absent (x3); count of 6 targets the account was blocked
  on, per pass: 6 (x3).

**Exact-port permit, refusals and the standard token (same tables; `nep5_n1_passes.csv`)**

- O4 (administrator-added permit for one exact port beside both blocks): connected v4:61763; blocked v4:60085,
  v4:61764, v6:60085, v6:61763, v6:61764 (3 passes). Says nothing about who may add a permit.
- O5 (block that names no provider): attempt added (x3); blocked v4:60085, v4:61763, v4:61764. O6 (filter naming
  a missing sublayer): attempt error (x3) with code 0x80320007 (x3); count of 6 targets the account connected
  to, per pass: 6 (x3).
- N1 (account's own standard token, direct single calls): add denied (x3) with code 0x00000005 (x3) (filter
  present afterwards: False (x3)); delete denied (x3) with code 0x00000005 (x3) (test filter still present: True
  (x3)); 3 passes. A delegated non-administrator was not tested.

**srt-win's own command line (`srtcli_states.csv`, `srtcli_commands.csv`)**

- stock build, H6 (IPv6 block deleted), 3 passes: status word installed (x3); filters 3 (x3); verify v4 out
  blocked (x3), v6 out connected (x3); host check (stock TypeScript) pass (x3), (patched) wfp_fence_inactive
  (x3).
- patched build, H6 (IPv6 block deleted), 3 passes: status word partial (x3); filters 3 (x3); verify v4 out
  blocked (x3), v6 out connected (x3); host check (stock TypeScript) pass (x3), (patched) wfp_fence_inactive
  (x3).
- stock build, H4 (IPv4 block deleted), 3 passes: status word installed (x3); filters 3 (x3); verify v4 out
  connected (x3), v6 out blocked (x3); host check (stock TypeScript) wfp_fence_inactive (x3), (patched)
  wfp_fence_inactive (x3).
- patched build, H4 (IPv4 block deleted), 3 passes: status word partial (x3); filters 3 (x3); verify v4 out
  connected (x3), v6 out blocked (x3); host check (stock TypeScript) wfp_fence_inactive (x3), (patched)
  wfp_fence_inactive (x3).
- stock build, HP (both permits deleted), 3 passes: status word installed (x3); filters 2 (x3); verify v4 out
  blocked (x3), v6 out blocked (x3), v4 in range blocked (x3), v6 in range blocked (x3); host check (stock
  TypeScript) pass (x3), (patched) pass (x3).
- patched build, HP (both permits deleted), 3 passes: status word partial (x3); filters 2 (x3); verify v4 out
  blocked (x3), v6 out blocked (x3), v4 in range blocked (x3), v6 in range blocked (x3); host check (stock
  TypeScript) pass (x3), (patched) pass (x3).
- stock build, plain `install` after H6: exit 0 (x3); message flags: 'already installed' True (x3), 'no changes'
  True (x3), 'port_range=<unknown>' False (x3), filters printed 3 (x3); state read afterwards
  (H6-after-reinstall): status installed (x3), filters 3 (x3), verify v4 out blocked (x3), v6 out connected
  (x3).
- stock build, plain `install` after H4: exit 0 (x3); message flags: 'already installed' True (x3), 'no changes'
  True (x3), 'port_range=<unknown>' False (x3), filters printed 3 (x3); state read afterwards
  (H4-after-reinstall): status installed (x3), filters 3 (x3), verify v4 out connected (x3), v6 out blocked
  (x3).
- stock build, plain `install` after HP: exit 13 (x3); message flags: 'already installed' True (x3), 'no
  changes' False (x3), 'port_range=<unknown>' True (x3), filters printed (none) (x3); state read afterwards
  (HP-after-reinstall): status installed (x3), filters 2 (x3), verify v4 out blocked (x3), v6 out blocked (x3),
  v4 in range blocked (x3), v6 in range blocked (x3).
- patched build, plain `install` after H6: exit 0 (x3); message flags: 'already installed' False (x3), 'no
  changes' False (x3), 'port_range=<unknown>' False (x3), filters printed 4 (x3); state read afterwards
  (H6-after-reinstall): status installed (x3), filters 4 (x3), verify v4 out blocked (x3), v6 out blocked (x3).
- patched build, plain `install` after H4: exit 0 (x3); message flags: 'already installed' False (x3), 'no
  changes' False (x3), 'port_range=<unknown>' False (x3), filters printed 4 (x3); state read afterwards
  (H4-after-reinstall): status installed (x3), filters 4 (x3), verify v4 out blocked (x3), v6 out blocked (x3).
- patched build, plain `install` after HP: exit 0 (x3); message flags: 'already installed' False (x3), 'no
  changes' False (x3), 'port_range=<unknown>' False (x3), filters printed 4 (x3); state read afterwards
  (HP-after-reinstall): status installed (x3), filters 4 (x3), verify v4 out blocked (x3), v6 out blocked (x3),
  v4 in range connected (x3), v6 in range connected (x3).
- `install --force` after a state: exit 0 (x18) over 18 restores (patched (x9), stock (x9)).
- Uninstall (`srtcli_cycles.csv`, 6 cycles): direct checks clean 6 of 6; the store folder remained 6 of 6 with a
  deny entry in its access list 6 of 6; other install footprint items remaining: 0; engine export hits after
  uninstall for srt-win, S1, S2, S3 and the default sublayer: 0 in total.

**Hold and persistence (`arm2_hold_samples.csv`, `arm_runs.csv`)**

- Arm 2: filters stood 7200.9 s; 120 of 120 probes refused, 0 connected; error codes 10013 (x120); the operator
  watchdog made 3421 connects with 0 failures; Bitdefender processes at start: 5; sample offsets 4.8 to 7143.9
  s.
- Arm 3a: set present and persistent (PRESENT, all persistent True) for 20.9 s; account probe refused (10013);
  absence gate refused after removal: True. No restart in 3a.
- Arm 3b: restart confirmed True; at 88 s of uptime the set read PRESENT (all persistent True); account probe
  refused (10013); removal verified True. That the restart was the issued command is inferred from the 600 s
  timing, not recorded.
- Arm 3b arming (`arm_runs.csv`): the first arming attempt finished 2026-10-12 14:38:57 (exit 2, fence ABSENT
  before it); the run that armed the set started 14:49:23, 10 minutes later; the post-restart row above reads
  the set PRESENT.

### Pre-registered limits

- The design in the study's `SPEC.md` (first committed before the matrix ran) fixed: three passes per state; the
  state list above; loopback listeners only, outside the permit range plus one inside it, on both families; the
  account, three test sublayers and one provider as the only objects any script may touch; a clean direct sweep
  before every add and after every removal, with a stop on anything else. The scripts were revised after that
  commit and before the run; the hashes the run's rollback proof recorded are in `runs/AS_RUN.md`. Three passes
  on one machine are repeats, not a variance estimate: 'identical' means identical across those three.

### Not measured

- Anything beyond loopback: no internet address, no other host, no UDP, no DNS, no ports other than 60085, 61763
  and 61764 in the matrix.
- Real IPv6 egress for any state; another machine or another Windows build.
- Persistence or time in the matrix: each state stood seconds; arms 2 and 3 cover the hold and one restart, for
  one filter shape.
- A restart with a half-set in place.
- The batch logon of the account's scheduled task under the matrix states (the matrix used an interactive
  logon).
- A delegated non-administrator (the Network Configuration Operators row was not run); a non-elevated `wfp
  status`.
- Traffic a Windows service sends for the account (BITS as LocalSystem, SMB and WebDAV redirectors,
  out-of-process COM).
- The Bitdefender state during the matrix and the command-line runs, and other machine load.
- Engine access list or security-descriptor dumps; file ownership; exports while a state stood.
- AppContainer and Microsoft Execution Container results are not in these tables.
- Speed: each hold probe took 24 to 116 ms (`probe_ms` in `arm2_hold_samples.csv`); this is not a latency
  measurement.

### Licence

Data in this section: CC-BY-4.0 (cc-by-4.0).
