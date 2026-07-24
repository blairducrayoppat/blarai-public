---
title: "Disposition — independent review of e47a8af (#1027 web-capture Edge leak, agentic-setup)"
date: 2026-07-21
review_of: "e47a8af on fix/1027-web-capture-edge-leak (agentic-setup); merged 3733372"
reviewer: independent subagent (author≠verifier; 3 live red-verifies incl. an adversarial mutation reproducing the real 15-process leak caught by the behavioral locks alone)
---

# Disposition — #1027 Edge-capture leak review (2026-07-21)

Review verdict: MERGE-READY — 0 BLOCKING, 0 SHOULD-FIX, 6 NOTEs + 2 named residuals.
Merged to agentic-setup main `3733372` after the verdict; post-merge verify run recorded on #1027.

```disposition
note-1-ctrlc-teardown-best-effort | REJECTED | A PowerShell platform limit (finally-block cmdlets throw PipelineStoppedException during a pipeline stop) combined with node-on-Windows SIGINT skipping exit handlers; the fleet runs headless so no console Ctrl-C exists in the observed leak class, and no cheap fix exists — accepted as a documented platform boundary, not a defect in this change.
note-2-mjs-escalation-keys-on-rm-failure | REJECTED | The standalone-invocation gap is unreachable in the repo: capture-app.ps1 is the ONLY caller (reviewer grepped), and its finally re-sweeps by user-data-dir key unconditionally, covering the exact case where rmSync succeeds while the detached tree lives.
note-3-source-locks-textual-evadable | REJECTED | By design: the source locks are tripwires; the PROOF is the behavioral pair WC13/WC14, demonstrated by the reviewer's adversarial mutation B to catch the real reproduced leak (15 processes) with every source lock still green — the composition is sound and the record here preserves that division of labor.
note-4-no-third-rescan-in-run | REJECTED | The in-run second kill is a best-effort backstop; final cleanliness is verified at suite time by WC14 — adding an unbounded rescan loop in the capture path would trade a bounded teardown for an unbounded one.
note-5-behavioral-locks-blind-if-lk4-relaxed | REJECTED | LK4 pins the --profile-dir pass that keeps the behavioral pair sighted; the coupling is real and is recorded HERE as the standing warning — relaxing LK4 requires re-scoping WC13/WC14 in the same change.
note-6-basename-powershell-interpolation | REJECTED | Local dev tooling with a single trusted in-repo caller whose generators emit GUID-hex/base36 names only; no untrusted path reaches the interpolation, and the capture surface accepts no external input.
residual-a-ps1-side-node-timeout | DEFERRED | #1029 blocked-by: #1027 merged (3733372) — a ps1-side WaitForExit cap building on the Stop-EdgeCapture surface, defense-in-depth for the native-node-wedge class the mjs watchdog cannot cover.
residual-b-wc14-global-scan-false-alarm | REJECTED | The failure direction is a loud false ALARM, never a false pass; verify-capture is a dev-time tool and the battery runs at 23:00, so collision is unlikely — and the one-line scoping fix (postDirs-only matching) is named in the review for the day it ever fires spuriously.
```
