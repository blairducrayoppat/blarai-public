# Pre-run adversarial review, round 1: MXC loopback-proxy egress probe

- Reviewed: branch `feat/mxc-proxy-egress`, commit `490c2bcd`, `tools/probes/mxc_proxy_egress/` and `.gitattributes`. The working tree matches HEAD; all seven files are LF in both the index and the working tree.
- Spec: CASE_1_mxc-loopback-proxy_2026-10-15.md (v2), read-only. Prior record: `docs/research/windows-containment-comparison-2026-10/mxc-1406-probe/README.md`, `tools/probes/mxc_1406/`.
- Reviewer: independent; did not write the code; fixed nothing. Review finished 2026-10-15 19:12 UTC (15:12 -04:00).
- **Verdict: FAIL.** One HIGH finding. No approval file was written.

## What I ran (all non-elevated through `run_nonelevated.ps1`; `whoami /groups` showed Medium Mandatory Level, Administrators deny-only)

1. `C:\Python314\python.exe -I self_test.py`: **47 PASS, 0 FAIL**, exit 0.
2. `wxc-exec --probe` on arm A (`dl/x64`) and arm B (`build-main-20261015`):
   - Both report tier `base-container` and `baseContainerSupportsIngressHostLoopbackAllow: true`.
   - Arm B also reports `baseContainerSupportsIdentitylessLoopbackProxy: true`. The flag sits at `probes.<flag>`, which is the path `check_arm_b_precondition` reads.
   - Neither launcher reports a PSEC version field.
3. `run_probe.py --out <scratch> --arms A,B,B0 --dry-run-only`:
   - All three arms returned `dry_rc 0`, "Dry run completed. Result: validation passed". The dry-run output says nothing about the network plan.
   - Header values: build 26200.9711, not elevated, arm A `Valid|CN=Microsoft Corporation`, arms B and B0 `NotSigned`, Bitdefender process `bdredline.exe` only.
4. Verdict-logic fixtures run against `summarise.judge_run` and `judge_batch` (scratch `attack1.py`; output quoted below).
5. A port-squat test of `ForwardingProxy`.
6. A read-only firewall and host-state read: `Get-NetFirewallProfile`, `Get-NetFirewallApplicationFilter`, SecurityCenter2 `FirewallProduct`, `netsh winhttp show proxy`, `CheckNetIsolation LoopbackExempt -s`.

No container was launched.

## Findings, most severe first

### 1. HIGH: the B4(i) LAN listener raises the Windows Firewall prompt and is a measurement confound that B5 cannot see
`run_probe.py:258` and `:234` (`Instruments` binds `ProbeListener("lan", <host LAN IPv4>, 18112)` for every run and for the B5 control); `self_test.py` `test_end_to_end` (through `run_probe.main`).

- **(a) The prompt.** This is the only non-loopback bind in the harness and the self-test.
  - The interpreter is `python` on PATH (`launch.ps1:59`), which is `C:\Python314\python.exe`.
  - All three firewall profiles have `NotifyOnListen True`.
  - Current rules for `C:\python314\python.exe`: `Python | Inbound | Allow | enabled=False | Private, Public | TCP` and the same for UDP. These are the rules the 15:01:43 operator click created, since disabled.
  - The self-test's end-to-end section binds the LAN listener through `run_probe.main`. `self_test.py` was last modified at 15:02. The 15:01:43 prompt therefore fits the builder's self-test run. That attribution rests on timing only: a hypothesis, not reproduced.
  - I did not bind a LAN address while the rules were disabled, so as not to raise the prompt on the operator's screen. Whether Windows prompts again when only a *disabled* rule exists is therefore not tested. Treat it as possible.
  - If it does prompt, a live run shows the prompt mid-measurement (it takes the screen), and an operator click changes host firewall posture between runs 1 to 3 of one state.
- **(b) No record.** The harness records no firewall state. `snapshot()` covers ACL hashes, the ProcessSandboxes mappings, the AppContainer mapping count and the state-dir listing. It covers no firewall rules, profiles or loopback exemptions. A rule created or enabled during the batch is invisible, and `state_changed_by_run` cannot STOP on it.
- **(c) The confound.**
  - Connections from the host to its own LAN address are loopback-routed. As far as I know, Windows Firewall does not filter loopback traffic for unconfined processes, so B5b (the unfenced connect to the LAN listener) passes whatever the python rule says. The `host_control` lan check passes for the same reason.
  - If the firewall's default inbound block does apply to an AppContainer or BaseContainer connect to the host's own address (I believe it may, because container loopback is mediated by WFP; not verified), then B4(i) "refused" can be produced by the disabled python rule rather than by MXC.
  - So the control that is meant to attribute a refusal to the container cannot separate "MXC blocked it" from "the firewall blocked the listener". A disabled rule, an unanswered prompt and an "Allow" click each give a different B4(i) condition, possibly within one batch.
- **Cost:** a B4(i) "refused 3/3" could enter a public HOLD claim on a confound. In addition, a screen-taking prompt appears during an operator-attended run.
- **Related label problem.** B4(i) is not a LAN destination. It is the host's own non-loopback address, which Windows treats as loopback. A real LAN peer is never exercised. The prior record notes that `ingress.default=allow` silently adds `privateNetworkClientServer`, so private-network reach is exactly the open question this probe leaves untested while labelling it "LAN".
- **The one correct fix:** remove the host-side LAN listener (B4(i)) and replace it with a connect-only probe to a real LAN peer (the default gateway, port chosen by a B5 unfenced control that must connect). Judge it from the container's error code, as B4(ii) is judged. This removes the only non-loopback bind, and with it the prompt, the firewall confound and the mislabel; the self-test follows automatically.
  - Independently, add the enabled firewall rules matching the harness interpreter path, plus `CheckNetIsolation LoopbackExempt -s`, to `snapshot()` so that `state_changed_by_run` STOPs on them.
  - The spec's B4 asks for "one LAN **or** public destination", and B4(ii) at 1.1.1.1:443 already satisfies it.
- **Reproduced:** partly.
  - The rule state, profiles and code paths were read directly (output above).
  - The prompt trigger and the firewall's effect on container-to-own-IP traffic are hypotheses.
- **Incidence:** one prompt on the operator's screen today (per the coordinator; timing fits the self-test).

### 2. MEDIUM: a dead uplink manufactures a B4(ii) "not reached" and a HOLD
`summarise.py:127-131`.

- HOLD needs only `b4ii.connected is False`. A `TimeoutError`/10060 counts the same as the WFP block signature 10013, which is the code the 10-11 record observed for every blocked connect.
- B5c (the unfenced 1.1.1.1:443 control) runs once, before all arms. If Wi-Fi drops after it, every later B4(ii) times out and is counted as refused.
- Fixture: payload `b4ii: {connected: False, error: TimeoutError, winerror: 10060}`, everything else clean → **HOLD** (`attack1.py`, line "b4ii timed out (10060) not refused (10013)").
- **Fix:** count B4(ii) (and B3/B4) as refused only on an explicit refusal code (10013, or 10061 for B3). Any other error, including a timeout, makes the run INSTRUMENT-BLIND. Better still, also run the unfenced 1.1.1.1:443 connect immediately after each launch.

### 3. MEDIUM: untagged listener entries during the launch are ignored, and a lock mandates that
`summarise.py:65-66, 121-123`; `self_test.py` check "untagged listener hit is not attributed (run tag required) -> HOLD".

Fixtures:
- Payload says refused, plus an untagged entry (`marker ''`, `bytes 0`) on the second loopback listener → **HOLD**.
- Payload missing, plus the same untagged entry → **INSTRUMENT-BLIND**, never FAIL.

During the launch window, the only legitimate sources of connections to 127.0.0.1:18111 are the proxy's tagged B2 forwards. The host-control entries come before the launch and carry `host-control-*` markers. So an unexplained connection in that window is a candidate reach. One concrete shape is a pended connect that completes after the payload's 5 s timeout: the listener accepts it with no data and no marker.

- **Fix:** any target-listener or LAN-listener entry timestamped inside `[launch.started, launch end]` that is not a run-tagged `b2` makes the run INSTRUMENT-BLIND at minimum, never HOLD. Change the self-test lock to assert that.

**Incidence:** 0 in the bank (no live runs yet).

### 4. MEDIUM: a refusal at launch time is reported as INSTRUMENT-BLIND
`summarise.py:74-77, 107-108`.

If `--dry-run` passes but the real launch refuses (non-zero exit, no payload), the verdict is INSTRUMENT-BLIND ("accepted by the dry-run but no payload report"), not a refusal. Fixture: `launch.exit_code 1`, payload None → INSTRUMENT-BLIND.

The dry-run output here carries no network plan ("validation passed" for all three arms), so whether runtime enforcement agrees with dry-run validation is exactly what is unknown. The A1/B1 answer ("accepted or refused") would then be misreported as an instrument failure.

- **Fix:** add a `REFUSED-AT-LAUNCH` verdict when `launch.exit_code != 0` and there is no payload, with the stderr tail and MXC log tail as reasons. It ranks below FAIL and above INSTRUMENT-BLIND.

### 5. MEDIUM: the host is no longer the host the question and the NOT MEASURED lines describe
All docstrings: "NOT MEASURED: ... any PSEC 1.1 host".

- On .9457 the prior record had `baseContainerSupportsIngressHostLoopbackAllow false`. On this host (.9711) it reads true for both launchers. networking.md ties `hostLoopback: allow` to the PSEC 1.1 ingress contract.
- So this run most likely measures the PSEC 1.1 path. It does not measure the `psec_1_0_proxy_loopback_workaround` path that the 10-11 T-on result and arm B's "Support is available on PSEC 1.0-only hosts" prediction were about.
- Arm A's acceptance is then explained by the Windows update, not by a contradiction of #1485.
- The harness records the build and the probe flags, so the data is there, but its own scope sentence is false for this run.
- **Fix (harness):** replace "any PSEC 1.1 host" with a sentence that names the recorded ingress flag value, and add a run-time line to batch-header.json, `scope_note`, computed from `probes.baseContainerSupportsIngressHostLoopbackAllow`.
- **Not the harness's call: escalate to the orchestrator and LA.** The spec's question is "on 26200.9457", and the spec's own NOT MEASURED list and predictions rest on PSEC 1.0-only.
- Also for the orchestrator: on a PSEC 1.1 path, the policy doc says an identity-less proxy "opens both host-loopback directions". A B3 reach may therefore be documented behaviour rather than a vulnerability, and the spec currently routes any B3 reach to FAIL → MSRC. Re-read the doc before the run.

### 6. LOW: the spec's ENVIRONMENT fields are not all recorded
- **Arm B commit:** 525d0f25 is in STATUS.md only. It is not in batch-header.json, and the path says only `build-main-20261015`.
- **PSEC version:** not reported by `--probe`; the record should say "not reported" rather than nothing.
- **`wxc-host-prep`:** whether it was needed or run is not recorded.
- **Firewall owner:** the spec asks for Bitdefender's firewall ownership state. The harness records only a loose process-name regex (`bd|...`). SecurityCenter2 `FirewallProduct` reports **McAfee** on this host, which no record captures.
- **Interpreter hashes:** `CONTAINER_PY` (the payload interpreter) and the host interpreter are not hashed.
- **Fix:** add `arm_b_commit`, `psec_version_reported: null`, `host_prep`, the `FirewallProduct` displayNames plus `Get-NetFirewallProfile`, and sha256 of `CONTAINER_PY` and of `sys.executable` to the batch header.

### 7. LOW: hash binding is narrower than it reads
`launch.ps1:26`.

- `launch.ps1` verifies only four files. It cannot verify itself (circular), `launch.cmd`, `self_test.py`, the container Python toolchain or the launchers. The launchers' sha256 values are recorded, not bound.
- The approval file records all files, so a post-hoc check is possible. I judge that adequate for an operator-launched run, provided the batch header also records launch.ps1's sha256 and the payload interpreter's hash (finding 6).
- `launch.ps1` tolerates `#` comment lines (`launch.ps1:36`).

### 8. LOW: launch.cmd line endings disagree with .gitattributes
- `git ls-files --eol` shows `i/lf w/lf attr/text eol=crlf` for `launch.cmd`. A fresh checkout writes CRLF, so its hash will differ from the LF bytes on disk now.
- It is not verified by `launch.ps1`, so nothing breaks, but an approved hash for `launch.cmd` will not reproduce from the repository.
- **Fix:** `git add --renormalize` the file so the index and the working tree agree with the attribute.

### 9. LOW: ForwardingProxy co-binds a port held by a SO_REUSEADDR socket
`http.server.ThreadingHTTPServer.allow_reuse_address` is True. Repro: a squatter listening on 127.0.0.1:18110 *with* SO_REUSEADDR → `PROXY BOUND ON TOP OF A REUSEADDR LISTENER`. A plain squatter → WinError 10013, refused.

- **Fix:** set `allow_reuse_address = False` and `SO_EXCLUSIVEADDRUSE` on the proxy socket.
- **Incidence:** 0 (ports 18110 to 18113 are not otherwise in use; real service ports 8099 and 8000 are never touched; the proxy forwards to 127.0.0.1:18111 only).

### 10. LOW: host changes that are not snapshotted
- WFP filters (admin needed), loopback exemptions (currently the list is empty), WinHTTP proxy (currently "Direct access") and firewall rules are not in `snapshot()`. ACLs, ProcessSandboxes mappings and the AppContainer mapping count are.
- MXC's per-container WFP filters and any loopback exemption are therefore unverified for restore.
- **Fix:** add `CheckNetIsolation LoopbackExempt -s` and `netsh winhttp show proxy` (non-admin reads) to `snapshot()`, and the WFP filter count when elevated.

### Hygiene (item 3 of the brief)
- The committed files carry no `#`+digits, no numbered fixtures and no account name. The self-test hygiene check passed, and `git show HEAD` grep found none.
- `build1406` in the B0 launcher path is a bare upstream pull-request number inside a filesystem path, not a ticket reference. Noted only.
- Raw records (not committed) contain the account name (`"account"`, every path) and the LAN IPv4. That is fine for raw records; it must be scrubbed before any publication.

### Child windows
- Every child the harness starts uses CREATE_NO_WINDOW.
- Whether wxc-exec gives the container's console python a visible console is not tested (no launch). Hypothesis; the prior mxc_1406 harness used the same pattern.
- `launch.cmd` opens a console by design.

## What I attacked and could not break
- **Arm-B precondition:** reads the real `--probe` JSON path correctly. It refuses false, absent and unparsed; arm A is correctly not gated.
- **B2 control:** needs all three of container 200, proxy `forwarded`/200 and second-listener entry, 3 of 3.
  - Because B2 reaches the same 127.0.0.1 stack and the same target listener during the same run, a B3 refusal cannot be produced by a dead or wrongly bound target listener.
  - The proxy cannot forward the B3 direct connect: it forwards only absolute-form requests to 127.0.0.1:18111, and the B3 request is origin-form to 18111 directly.
- **FAIL precedence:** FAIL outranks BLIND; a container-reported connect without a listener entry is FAIL; batch FAIL dominates.
- **STOP:** prints `STOP: FAIL condition met`, returns 5 after the first FAILing run, and writes only under `--out`.
- **Output-path guard:** refuses a git tree, fails closed if git cannot classify, and the default out root is not in a git tree.
- **fx-a and fx-b** are byte-identical in measured state.
- **No real service port** (8099/8000) is reachable from the proxy.

## Merge / run read
- **Block the live run on finding 1.** The only non-loopback bind raises a screen-taking firewall prompt whose answer changes the condition mid-batch, and its effect on B4(i) is invisible to B5.
- **Fix before the run (one-line or few-line changes, and each one is the lenient direction):** findings 2, 3 and 4.
- **Escalate before the run (the orchestrator and LA decide):** finding 5. Do not block on its harness half.
- **Not blocking:** findings 6 to 10.

Suites I ran, at `490c2bcd`, non-elevated: `self_test.py` 47/0; `--probe` (A, B); `--dry-run-only` (A, B, B0); verdict fixtures; proxy port-squat test.

Approval file: **not written** (verdict FAIL).
