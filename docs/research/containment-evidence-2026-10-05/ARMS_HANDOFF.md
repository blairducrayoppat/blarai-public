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

## Arm 2: the long hold — NOT RUN

Planned: `-LongHold` up to 7,200 s with the dead-man at hold+30, the account's probe every 60 s, `netsh wfp show
filters` exported at start, mid-hold and before close. Claims row C9 when run.

## Arm 3: persistence, reboot, absence probe — NOT RUN

Planned as a design note first, then a dry run, then one live run with the operator present. Claims rows C10, C11 when
run.
