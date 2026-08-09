# Sprint-18 close — confirm + §5.1 ratification (relay to the execution agent)

Paste the block below to the Sprint-18 agent. It confirms the close, ratifies §5.1 (scoped), settles C3,
authorizes closing #631, and records three small non-blocking findings.

---

**Sprint 18 — close CONFIRMED. §5.1 RATIFIED (scoped). Close #631.**

The guide independently verified the close — re-ran the standing gate from `main` with the project `.venv`,
read the SWAGR + SCR + the §5.1 reconcile on disk, not trusting the summary:

- **Gate reproduces GREEN** — 0 failures, 2342 selected, 113 deselected, **no port-5001 skip-shift** (so C6's
  fix holds). The guide's run showed 2340/2 vs your 2342/0 — root-caused to the two symlink tests
  (`shared/tests/test_runtime_config.py:84` / `:104`) skipping in a **non-elevated shell**; 0 failures, same
  coverage. Benign shell-privilege split, not a regression, not a leak. (See finding (a).)
- **SWAGR is rigorous + independent** — it reproduced the gate AND C1 in production posture itself; 0C / 0M /
  5 MINOR; QUALIFIED-YES on §5.1. Verified.
- **§5.1 flip is honest + correctly scoped** — DONE = the verification limb only, explicitly NOT gate-open.

**§5.1 ratification: RATIFIED — scoped, exactly as you framed it.** The production-posture *verification*
criterion is DONE and independently reproduced (C1 green: `dev_mode=False`, real `CERT_REQUIRED` mTLS,
signed-manifest boot, real Qwen3-14B + real PGOV). This is the Auditor's QUALIFIED-YES: it satisfies ONE #598
criterion (the verification), NOT tier-completion and NOT gate-opening. The #598 decision still gates on #612,
the §5.12 sign-off, the #106 remainder, the DORMANT egress posture, and #607. Keep §5.1 = DONE (verification
limb) with the two qualifications recorded.

**C3 — its disposition is now DECIDED; it is no longer an open LA decision.** The LA confirmed (after a guide
investigation): the router is **built-ahead and DEFERRED** — it is NOT a security control (its own code:
"not a security boundary", `constants.py:44-45`; absent from the audit + roadmap controls), correctly parked
until the first skill-dispatch handler lands (web-search, #577). **Keep C3 scored PARTIAL** — the Auditor
blessed that as the honest score; do NOT re-score it. Update **#632** to the decided disposition (built-ahead
→ deferred, not an integration gap to build now); apply **MINOR-1** (rename the test to the adjacent-path
reality) and **MINOR-5** (annotate `coverage_audit.md` GAP-8 known-false). See the guide's #632 comment.

**Close #631.** Confirmed.

**Three small findings — none blocking the close:**
- **(a) The 2342/0 baseline has an unstated shell-elevation dependency.** 2342/0 is the *elevated/Dev-Mode*
  number; a non-elevated shell yields **2340/2** (the two `test_runtime_config` symlink tests skip), 0
  failures, same coverage. Add a one-line note to `TEST_GOVERNANCE.md` §1 + the CLAUDE.md baseline so 2340/2
  is never mistaken for a regression. (**MINOR-2 is NOT implicated** — the guide did not reproduce a port
  race; the two skips were symlink-privilege. MINOR-2 stays "watch/theoretical" as scored.)
- **(b) ~30 lingering python test processes** on the box (mostly dead / 0-WS — the same pattern as Sprint-17's
  ~22). None is holding a port now, but reap them so they don't accumulate (confirm the harness teardown reaps
  its process tree, or a one-time `taskkill` sweep of the dead PIDs).
- **(c) #633** (guide-tracked, not Sprint-18's): the tokenizer `local_files_only`/`trust_remote_code` hardening
  — the `pgov.py:612` instance is LIVE — stays on the pre-gate track. Flagged so it's on the radar, no action
  this close.

Carry-forwards otherwise acknowledged as listed. After this sprint, only the **#612 capstone phase** and the
**§5.12 sign-off** stand between the codebase and the #598 decision — both governance acts, not builds.

---
