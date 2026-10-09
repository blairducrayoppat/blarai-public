# Why is the coder-fleet containment switched off? (forensics, 2026-10-04)

Read-only investigation by a subagent on the #1665 session; findings below are the agent's report, recorded
here because the agent wrote no file. Verified-on-disk items carry a citation; inferred items are marked.
Ticket of record: #775.

## Answer

It was never switched off by a decision. `"containment": "off"` in agentic-setup `configs/fleet-driver.json`
is the dormant day-one default shipped in agentic-setup commit `4c91809` (2026-07-10). Flipping it was
deliberately deferred and the deferral lapsed with no owner. The flag is the smaller problem: flipping it
today would barely contain anything.

## Timeline

- 2026-07-10 - `4c91809` writes the containment code and the `"off"` default. No flip decision in the commit.
- 2026-07-10 - the Lead Architect (LA) keeps Bitdefender and accepts the coder-egress gap (#775 comment 1653).
  Bitdefender owns packet filtering on this machine, so the per-account firewall block is inert. `d6f7795`
  adds the `-AcceptedEgressGap` verify mode; comment 1654 records the four-check proof green under it.
- 2026-07-11 - the LA approves deferring the flip (comment 1808). Reason: sequencing; the ACP (Agent Client
  Protocol) driver had just gone live and stacking containment on that night's battery would have
  confounded it. Stated bound: 2026-07-18, "re-surface to the LA if it slips".
- 2026-07-15 - last update on #775 (comment 1976). The bound is about 78 days past with no re-surfacing.

Bitdefender and the E8 firewall incident (`PHASE1_DISPATCH_THREAT_MODEL.md` section 5.3, lines 253-254)
explain the accepted EGRESS gap, not the off flag.

## What containment consists of

1. Account `blarai-coder`: exists, enabled, last logon 2026-08-14 (unexplained).
2. ACL denial of operator secrets: proven (check 2).
3. Per-account firewall egress block: provisioned but inert (documented-not-enforced; threat model 266-273).
4. Worktree relocation to `C:\blarai-fleet\worktrees`: built, folder exists.
5. Scheduled task `\BlarAI\BlarAI-Coder-Leg` (Ready): the only thing that runs a coder as `blarai-coder`.
6. VM hybrid: designed only (threat model section 5.4).

## What "off" does today

The only reader of the flag is `Resolve-WorktreeBase` (`new-agent-task.ps1:134`; `fleet-lib.ps1:3487-3489`),
which returns the relocated worktree folder only under `restricted_account`. The production coder path
(`Invoke-AcpCoderRun`, `fleet-lib.ps1:793`) does a plain `Start-Process`, so model-written code runs as the
LA's own account with an open egress path and operator secrets readable. `coder-leg-run.ps1:50` calls
`Invoke-AcpCoderRun` as `blarai-coder` only when the scheduled task is triggered. The FUSED leg (a full
dispatch running as `blarai-coder`) was never wired: the unfinished step in #775's own plan (comments 1654,
1808). Dispatch itself is live (`[fleet_dispatch] enabled = true`, `default.toml:435`; driver `acp` since
2026-07-11).

## Remaining steps (technical; only the last is the LA's)

Re-run `verify-coder-containment.ps1`; wire the fused leg; one watched fused dispatch; then flip the flag
(LA-present go-live). Related: #1671 (raw WFP block rule against Bitdefender) targets the egress leg.

## Unknown

Whether anything ran `verify-coder-containment.ps1` after 2026-07-10; other readers of the flag beyond
`.py`/`.toml`/`.ps1` matches (`acp_coder.py`, `timeout_registry.py` only).
