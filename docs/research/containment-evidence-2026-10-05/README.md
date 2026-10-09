# Containment evidence bundle (2026-10-05)

Required Notice: Copyright (c) 2026 Blair DuCray-Oppat. This bundle is covered by the repository licence
(`LICENSE.md`); commercial use requires a separate license (`COMMERCIAL-LICENSE.md`). Companion to
`docs/research/account-level-containment-evidence-2026-10-05.md` (read that first: it states what each file does and
does not show).

## What is here

| Folder | Content |
|---|---|
| `wfp-spike/` | #1671: the raw Windows Filtering Platform (WFP) block spike: script, its README, console output, 3 result files |
| `confined-model-spike/` | #1689: the spike. `as-run/` = the scripts as they stood after the runs (the results come from these); `post-run-hardened/` = the same scripts after later hardening; `runs/` = Test A (2 runs), Test B (1 run), in-process control |
| `preflight/` | #775 read-only pre-flight (account, task, ACL listing, offline suites), 2026-10-05 |
| `reviews/` | review reports behind the negative results: agentic-setup fused leg; #1690 rules tooling (copy from the unmerged branch `feat/1690-install-hardening` at `22efaac9`, not on main) |
| `CHANGES.md`, `make_changes.py` | generated table of what was changed in each file, and the generator (the test regenerates it); `as-run/MANIFEST.sha256` pins the as-run set |

## The scripts were changed after the runs

The runs were 15:57 to 16:03 on 2026-10-05; the confined-model scripts were hardened at about 16:44 to 16:50. Use `as-run/` to read what
produced the results (Test A run 1 used an even earlier `spike-run-test.ps1`, now lost; see `CHANGES.md`). `post-run-hardened/` is what to run today. `as-run/MANIFEST.sha256` proves those files are unchanged since it was generated, not their provenance (provenance: first bundle commit `9adcafc4` and the research-data file times in `CHANGES.md`). Text files are stored LF (the originals were CRLF); hashes use LF-normalised bytes, so a CRLF checkout verifies too.

## Sanitising: see `CHANGES.md` for the per-file counts

Only these changes were made: the user name and machine name became `_OPERATOR_` and `_MACHINE_`; the two real machine SID
domains became shape-valid placeholder domains (relative ids kept); JSON files were re-serialised and model text cut to 100
characters. Fabricated test SIDs in the scripts were left alone, so the scripts' own `-SelfTest` runs. Anything else would be
a defect. No password or credential is in any file (the spike password was generated at run time and held only in the
scheduled-task vault).

## Known gaps in the raw data (read before relying on it)

- `outbound_blocked` in the WFP results is defined by agentic-setup `scripts/coder-containment-probe.ps1` (not bundled): it is
  true when the connect does not complete in 5000 ms OR throws, so ANY failure counts as blocked. The in-run baseline and
  post-removal arms are what attribute the block to the filters.
- `secret_reads_denied: true` in the WFP results is vacuous: the probe was sent an empty secret-path list.
- `hold_seconds: 100` is the requested cap; the filters stood for seconds (see the evidence document).

## Run order (elevated, 64-bit; Lead Architect present; only on a machine you can reboot)

1. `-SelfTest` of every script (both sets) changes nothing and is run by the bundle test (PowerShell 7 and Windows PowerShell 5.1).
   `spike-wfp.ps1` and `spike-verify-cleanup.ps1` (either set) need `-WfpScript <path to wfp-spike\wfp-coder-egress-spike.ps1>` because their
   defaults name the operator's original folder.
2. WFP spike: `wfp-spike\wfp-coder-egress-spike.ps1 -DryRun`, then `-Live -HoldSeconds 100`. It needs the account `blarai-coder`,
   the task `\BlarAI\BlarAI-Coder-Leg`, and agentic-setup `coder-leg-queue.ps1`, `coder-provisioning-lib.ps1`,
   `coder-leg-run.ps1`, `coder-containment-probe.ps1`. None of those are in this bundle.
3. Confined-model spike (needs an OpenVINO GenAI 2026.4 venv and a model directory; set the paths in `spike-lib.ps1`):
   `Run-Spike-AsAdmin.cmd` (provision), `spike-wfp.ps1 -DryRun`, `-TestA`, `-TestB`, then `spike-cleanup.ps1 -DryRun`, `-Apply`,
   `spike-verify-cleanup.ps1` (exit 0 = clean). The operator paths inside the scripts are now `_OPERATOR_` placeholders.

Every WFP object lives in a dynamic session: closing the engine, killing the operator process or rebooting removes it.

## Integrity gate

`tests/security/test_containment_evidence_bundle.py` fails if the user or machine name or a real SID domain reappears, if model
text exceeds 100 characters, if `CHANGES.md` disagrees with the files, if the evidence document cites a missing file, has an
incomplete claim row or loses its limits section, or if any bundled script's `-SelfTest` fails.
