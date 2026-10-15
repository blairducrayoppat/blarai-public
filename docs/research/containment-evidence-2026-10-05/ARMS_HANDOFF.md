# Evidence arms: handoff record

One section per arm: done or not, the result file paths, the claims rows added to
`docs/research/account-level-containment-evidence-2026-10-05.md`, the limits, the date. Everything here is
sanitised (`_OPERATOR_`, `_MACHINE_`, placeholder SID domains; see `CHANGES.md`). The subject in every arm is a
throwaway local account, never the operator's working accounts; nothing in the product's runtime changed.

## Arm 1: the permit filter's role; the confined account as CLIENT of a real local server — DONE 2026-10-09

**Question.** With a raw Windows Filtering Platform (WFP) block keyed to the account's SID at the connect layer, can
the account reach a real local model server over loopback, and does that depend on the loopback permit filter?

**Result.** Six invocations, alternated permit-on / permit-off, each its own process and dynamic engine session.
With the four filters (two loopback permits, two blocks): the account's POST to `127.0.0.1:<port>` returned HTTP 200
with a 32-token model completion in each of 3 runs while its connect to `1.1.1.1:443` failed with Windows socket
error 10013. With the two block filters only: the same POST failed at the socket with error 10013 in each of 3 runs
(no HTTP status; the server's own log shows the request never arrived), and succeeded again after the filters were
removed. Under this block the permit at `ALE_AUTH_CONNECT` is required for loopback.

**Files.** `arm1-permit/runs/testc-on-20261009-180608.json`, `testc-on-20261009-180910.json`,
`testc-on-20261009-181026.json` (permit on); `testc-off-20261009-180836.json`, `testc-off-20261009-180943.json`,
`testc-off-20261009-181213.json` (permit off); `arm1-permit/runs/server/server-testc-*.json` (the operator-run
server's own request log per run); `arm1-permit/scripts/` (the scripts as run, with their README).

**Claims rows added.** C7 (permit on: OBSERVED 3 of 3), C8 (permit off: OBSERVED 3 of 3); C6g marked superseded;
C1b and C3b point at them. Sections 1, 3, 5, 6 and 7 of the evidence document updated.

**Conditions.** One machine; Windows 11 Pro 26200.9457 (25H2); elevated Windows PowerShell 5.1; Bitdefender running
(its sublayers not isolated); WSL2 installed, distribution stopped; server = `spike_model.py` serve mode run as the
operator from an OpenVINO 2026.4.0 / GenAI 2026.4.0.0-3407 venv with Qwen3.5-4B-int8 on the Arc 140V iGPU; one
prompt, 32 tokens; filters stood 4.2 to 4.3 s (on) and 2.9 s (off), timestamped at add and at engine close.

**Limits.** Short windows only (no hold beyond about 4 s); six runs inside seven minutes are a repeat, not independent
replications; no IPv6, UDP, DNS or other ports; no persistence or reboot; one suite, one driver; no streaming or
concurrent clients; the product's own model server was not the server; one permit weight and layer.

## Arm 2: the long hold — DONE 2026-10-11

**Question.** Does the block keyed to the account's SID stay enforced for an hour or more while Bitdefender runs, or does the suite's sublayer win the flow back over time?

**Result.** One hold of 7,200 s (filters stood 7,200.9 s, 14:48:56 to 16:48:57), the four-filter set in one dynamic session, the account probed through its task once a minute: 120 of 120 samples refused, all with Windows error 10013, probe time 24 to 116 ms (median 48). Filter exports at the start, at 3,600 s and before close each held all four filter keys and the marker `BlarAI #1671`. Operator watchdog: 3,421 connects, 0 failures, longest gap between ticks 5 s. Removal verified; the account's egress was open again; exit 0. Bitdefender signal `bitdefender_folder_timestamps_changed`: five folders (`Bitdefender Security`, `installer`, `updcenter` 14:42 to 16:42; `Bitdefender Security App` 14:27 to 16:27; its `events` 12:42 to 15:42) had a later last-write time at the end than at the start; the start values predate the hold (start 14:48:56), the end values fall inside it, the two-hour spacing looks periodic, no new process: a weak signal, not proof of an engine update.

**Account.** `blarai-spike` with relative id 1271, newly provisioned after the arm 1 cleanup deleted the arm 1 account of the same name (relative id 1011): two different accounts.

**Files.** `arm2-hold/runs/hold-on-20261011-144844.json`, `arm2-hold/runs/hold-on-20261011-144844-samples.txt` (one JSON line per sample), `arm2-hold/runs/wrapper-arm2-log.txt`; scripts and README in `arm2-hold/scripts/` (the arm 2 versions of `spike-wfp.ps1`, `spike-run-test.ps1` and `spike-lib.ps1` are as run; `Start-ElevatedOnce.ps1` gained the admin-only folder check after the run); self-test results in `arm2-hold/selftest/`. Raw filter exports stay in the research-data folder.

**Claims row added.** C9 (OBSERVED 1 of 1). Evidence-document sections 1, 3 and 6 updated.

**Conditions.** One machine; Windows 11 Pro 26200.9457 (25H2); elevated Windows PowerShell 5.1.26100.9444 started by a one-shot elevated scheduled task from an admin-only copy of the scripts; uptime 43.4 h at the start; Bitdefender running; WSL2 distributions stopped by `wsl --shutdown` first; system kept awake for the hold.

**Limits.** One hold is one observation (the samples inside it are not replications). No IPv6, UDP, DNS or other ports; no second hold; no hold across sleep, a restart or a Bitdefender engine update; one suite, one driver.

## Arm 3a: a persistent set added and removed by key, and the absence check — DONE 2026-10-11

**Result.** One run (16:51:27 to 16:52:08) of `spike-wfp-persist.ps1 -Arm3a` with the follow-up `-Remove`, after `-SelfTest -WriteProof`: the gate on the empty fence returned allowed=False (ABSENT); the persistent set (provider, sublayer, two block filters; flags `0x1` on all four; non-dynamic session) was added and read back PRESENT; the account, started through the gate, was refused (10013, 82 ms) while the operator watchdog saw 9 connects and no failure; the set existed 20.9 s; removal by key deleted all four, read back ABSENT; the gate refused again and started nothing; the account's unguarded probe then connected; the follow-up `-Remove` found all four not found; the reviewer's `-Check` at 16:52:29 exited 20 (`post-3a-verification.txt`); no object with the marker remained. The optional SYSTEM dead-man task was NOT registered (the grant covered only the per-run elevated task).

**As run.** Commit `aab46664` as an admin-only live copy (`arm3-persist/runs/AS_RUN.md` lists the live-copy hashes and which files have changed since); `-WfpScript` named the admin-only copy of the wrapped script explicitly and `-NoDeadManTask` was passed (from the lead's account; the banked wrapper log does not record the arguments). The as-run default `-WfpScript` was a user-writable path and the wrapped script's text was evaluated before any hash or proof check: found by the 2026-10-11 review, fixed since.

**Files.** `arm3-persist/runs/arm3a-20261011-165130.json`, `arm3-persist/runs/remove-20261011-165206.json`, `arm3-persist/runs/wrapper-arm3a-log.txt`, `arm3-persist/runs/post-3a-verification.txt` (the reviewer's later `-Check`, exit 20), `arm3-persist/runs/AS_RUN.md`; `arm3-persist/DESIGN.md`; scripts and README in `arm3-persist/scripts/`; self-test results in `arm3-persist/selftest/`.

**Claims rows added.** C10a (the set can be added and removed by key; NOT survival across a restart; OBSERVED 1 of 1), C11 (the absence check refused when the set was absent; OBSERVED 1 of 1).

**Limits.** One run. Partial and unreadable states were exercised against an in-memory fake, not the real engine. No restart. Removal of a half-added set on the real engine was not exercised. Before the 2026-10-11 runs the builder's own session (found to be elevated) also ran `-Check` and `-Remove` once each in two hosts against the real engine: four keys that were absent were queried and four deletes returned not found; nothing was added.

## Arm 3b: persistence across a restart — DONE 2026-10-12

**Result.** One run (`arm3b-20261012-150113`). The persistent set (provider, sublayer, two block filters; flags `0x1` on all four; non-dynamic session) was added at 14:49:23 and read back PRESENT; the restart (`shutdown /r /t 600`, which is FORCED: a timeout above 0 implies `/f` on this machine, so applications are closed without asking) was issued; the machine booted at 14:59:46 (previous boot 12:05:40); the SYSTEM startup task ran at 15:01:13, 88 s after boot: all four objects PRESENT and persistent, the absence check allowed (PRESENT), network up on the first attempt, the account's connect to `1.1.1.1:443` refused (error 10013, 28 ms), operator control 3 of 3 OK; removal by key deleted all four and read back ABSENT; the gate refused afterwards and started nothing; the account's unguarded probe connected (egress open). Objects existed 718.1 s. Exit 0. A `-Check` at 16:57 exited 20 (ABSENT) with no `\BlarAI\` arm 3 task left (`arm3-persist/runs/post-3b-verification.txt`).

**As run.** From the admin-only live copy of commit `68106f0f` (`feat/1682-arm3b-run`): the independent-review fixes of 2026-10-11 plus ONE change made at the Lead Architect's instruction on 2026-10-12: the arming script's idle floor was lowered from 30 to 2 minutes FOR THIS RUN ONLY (`-IdleMinutes 2` was passed; the bundled script has the 30-minute floor again, restored after the review, and the bundle test pins 30; the 10-minute countdown, the input abort, the 600 s forced restart timer and the 30-minute veto task are unchanged). The Lead Architect's acceptance of a forced restart is Vikunja #1682 comment 4065, recorded in `arm3b-restart-decision.json` in the live folder. The rollback proof was rewritten for the changed script (116 checks). Launch attempts: 14:38:29 failed in argument parsing (one quoted argument); 14:38:52 refused (the output folder `blarai-research-data\arm3-persist` was writable by the operator's account); the third, at 14:39:11 with `-OutDir` an admin-only folder, armed the run. Nothing was added by the first two (`wrapper-arm3b-attempts.txt`, `arm3b-arm-refused-20261012-143857.json`).

**Not observed.** The arming script's own steps record, which is written only after the script returns and is therefore never written when the restart ends it first (so idle seconds at the gate, the countdown record, the pre-arm baseline, the shutdown exit code and the veto task's deletion are unrecorded; the countdown, the veto registration and the restart command are inferred from timing and from the armed record, not recorded); the console output (the wrapper log ends at its first line); whether the warning toast and window were seen (the Lead Architect was away); the restart itself (inferred from the boot time and the 600 s timing).

**Files.** `arm3-persist/runs/post-3b-verification.txt`, `arm3-persist/runs/arm3b-post-reboot-result-20261012-150113.json`, `arm3b-armed-20261012-144923.json`, `arm3b-post-reboot-attempts-20261012.json`, `arm3b-arm-refused-20261012-143857.json`, `wrapper-arm3b-attempts.txt`. Raw filter exports stay in `C:\ProgramData\BlarAI\arm3b-out\` (hashes and marker counts are in the result JSON).

**Claims row.** C10 (OBSERVED 1 of 1); C6b marked superseded.

**Limits.** One restart. No sleep, hibernation, fast startup, feature update, BFE crash or Bitdefender engine update; the interval between boot and 88 s is unobserved; no loopback permit in the persistent set; IPv4 TCP port 443 only; one suite, one account.

