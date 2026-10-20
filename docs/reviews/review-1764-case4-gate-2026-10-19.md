# Independent review of the Case 4 comprehension gate (#1764), 2026-10-19

Reviewer: a session that did not author the gate. Clock at review: 2026-10-19 16:22 -04:00. Main at `f08d8f67`.

## 1. Verdict

**PASS WITH CORRECTIONS.** The gate is grounded on disk, matches the LA's manual-steps sheet and the campaign brief point for point, and routes the right calls to the LA. Four items need fixing in the re-presented gate (or an addendum) before confirmation; none is a stop. No LA decision is needed.

## 2. What I verified

| Gate claim | Checked against | Result |
|---|---|---|
| nco-probe exists, DISABLED, only member of Network Configuration Operators, no profile folder | `net user nco-probe`, `net localgroup "Network Configuration Operators"`, `Test-Path C:/Users/nco-probe` (all read-only) | All four TRUE: Account active No, Last logon Never, sole member, no folder |
| C17 covers the standard token only | `docs/research/account-level-containment-evidence-2026-10-05.md` row C17 | TRUE: "the account's own non-elevated token", 0x00000005 both calls |
| C27 is the next claim | Same file, last row | TRUE: C26 is the last row |
| .NET Framework compiler on the machine, no install | `C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe` | Present |
| Parts B, C, C.3, D as the gate uses them | `CASE_4_MANUAL_ACCOUNT_STEPS_2026-10-19.md` in the nolabs opportunity folder | Match: B = probe runs, C = remove, C.3 = profile via sysdm.cpl, D = read-only checks; the "disable until part B" clause is in the sheet |
| F and E conditions, 3 runs, controls in the same batch, S2, stale SID, exe-hash arming, Opus non-elevated reviewers, raw results first, disclosure routing, register entry proposed not entered | `CASE_4_PROBE_BRIEF_2026-10-19.md` sections 2 to 4 | Match, with ONE deviation (item 3.1 below) |
| LA rulings | #1764 comments 4477 to 4479; #1763 comments 4074, 4077, 4093, 4094 | Match: lifecycle is the LA's by hand; probe half only is the session's; classifier stops recorded never worked around |
| Engine access list grants the group add/delete | #1763 comment 4093: ACE `(A;;0x307ff;;;NO)` read 2026-10-13 | Recorded there; the gate's "expected, not a finding" framing is right |
| BLARAI_UPDATES_2026-10-19.md exists in the nolabs folder | `ls` | Exists (11 KB, 15:24 today); row 31 holds the case 4 line to be replaced |
| Branch feat/1764-nco-probe, worktree | `git branch -a`, `git worktree list` | Neither exists yet; 60 other worktrees live, none on this topic; `%USERPROFILE%/BlarAI-worktrees/` is the parent folder to use |
| #1764 description | Vikunja `get_task` | EMPTY. The work is defined only in comments and in two files outside the repo |

## 3. Gaps and corrections (most important first)

**3.1 DEFECT (author fix): the research-tree locks are not in the plan.** New run records will carry nco-probe's account SID, the stale SID used for the filter condition, and the ticket number. Three gate locks reject exactly that in tracked files: `tests/security/test_no_machine_sid_domain_in_tree.py` (any form of this machine's account-domain SID, including a stale RID on it), `tests/security/test_account_sid_scrub.py` (#1793, shipped two days ago), and `tests/security/test_research_files_carry_no_tracker_numbers.py`. The 10-13 arc needed a gate exemption for this and then the #1793 scrub. The gate must say: the probe records SIDs in the lock's placeholder form or the records pass `python scripts/scrub_public_identifiers.py --check` before commit, and research files carry no `#1764`. Choose a stale SID OUTSIDE this machine's domain (a well-known or fabricated domain the lock allows) so the filter condition itself is not a lock hit.

**3.2 DEFECT (author fix): the arc stops at the branch.** Deliverable 2 ends "on branch feat/1764-nco-probe in a worktree". Doctrine: merge to main, #1764 closed citing the SHA, the branch standing gate before merge and the gate re-run on merged main (bash shell, app down, LOCALAPPDATA redirected), label Blocked replaced by Doing at start. State it.

**3.3 DEVIATION FROM THE BRIEF, surfaced but under-argued (author decides, LA informed).** The brief's control is "a standard non-administrator token (blarai-spike or equivalent)". The gate substitutes the LA's filtered administrator token, which is a different principal class (Administrators deny-only, not a plain Users member). The reason given ("would need the password-reset design again") is true but that design exists, passed four Opus rounds, is committed (0654307a, 716fd87a) and deployed in `C:/ProgramData/BlarAI/trackb-live` with its proof: `-Run -Phase n1` re-runs C17's shape as blarai-spike in about a minute. Recommendation: run the existing reviewed N1 phase as the standard-token control in the same batch, keep S as an extra row. If the author keeps S alone, C27's text must say the within-batch control is a filtered administrator token and the standard-token comparison is to C17 from 2026-10-13.

**3.4 RISK (author, run-sheet content): the E launch line.** From the LA's own administrator console, "Run as administrator" shows a consent prompt, never a credential dialog, so nco-probe's credentials cannot be entered there. The elevated nco-probe token is reached from INSIDE the filtered nco-probe console (runas first, then an elevation request from that console, which prompts for nco-probe because the group gives it a linked token). The run sheet must carry that two-step verbatim; a one-step "elevate at the UAC prompt" line would elevate the LA, not nco-probe, and the probe's recorded SID would trip the gate's own stop condition. The gate's "a refusal is the recorded E result" stays right.

**3.5 MINOR.** (a) #1764's description is empty; the gate should put the scope there or in a dated CURRENT STATE top comment at start (update_task is a full PUT: re-supply title, priority 4, labels). (b) The drop folder's ACE for nco-probe outlives the account as an orphaned SID; `-Finish` should remove the folder or the ACE and record it. (c) Deliverable (b) builds a new admin driver; the brief says sublayer creation and the sweep run "in the existing admin harness". Reusing `spike-nep5-lib.ps1`'s sublayer, sweep and direct-check functions (new file, new proof, arm scripts untouched per SPEC) keeps the review surface small; a wholly new driver is acceptable but say which.

## 4. Doctrine checks that hold

Grounding named and real (ticket comments, sheet, brief, evidence doc). Yours vs mine correct: lifecycle, typing, confirmation, disclosure routing are the LA's; language, folders, proof, wording are the author's; no technical question is routed to him. No mid-work approval gate (the run sheet hand-over is a required LA action, not a manufactured stop). Security by design: probe armed by exe-hash proof, reviewer no engine, filter matches no account, stop conditions match the brief and comment 4074. Monitoring line present and valid (foreground; reviewers minutes). Dormant/LIVE: not a runtime capability; n/a. Nightly: not referenced. Journal fragment, disposition, PERFORMANCE_LOG named. Nothing posted; HF upload out.

## 5. The one LA decision

None. Item 3.3 is the author's call; the LA only needs to hear which control was run.

## 6. Hand-back to the authoring session

Gate confirmed in substance; re-present with these additions before the LA confirms:
1. Add the lock compliance line (3.1): placeholder SIDs in records, stale SID outside the machine domain, no tracker number in research files, `scrub_public_identifiers.py --check` clean before commit.
2. Add the full arc (3.2): branch gate, merge, re-gate on main, #1764 Doing at start and closed citing the SHA.
3. Decide 3.3 and state it: re-run the existing reviewed `-Run -Phase n1` as the standard-token control (recommended), or label S as a filtered administrator token in C27.
4. Make the E line a two-step in the run sheet (3.4) and treat "elevated as the LA" as a stop, which the SID check already is.
5. Fill #1764's description or a dated top comment; remove the drop-folder ACE in -Finish; name which existing lib functions the driver reuses.
Everything else stands as written.

## 7. Delta gate (same day, ~16:45 -04:00): PASS

All five additions verified on disk: the SPEC's stale SID `S-1-5-21-17630000-17630001-17630002-91763` is a fabricated domain and already allowed by the bundle test; `-Run -Phase n1` exists in the deployed matrix (`%ProgramData%/BlarAI/trackb-live/spike-nep5-matrix.ps1`) and is C17's shape under the 2026-10-13 account-logon design (#1763 comment 4080); the library holds the sublayer, sweep, direct-check and proof functions named (`Get-N5SubLayerId`, `Invoke-Nep5DirectSweep`, `Remove-Nep5All`, `Test-N5Proof`); the two-step E launch is right.

Two facts for the author, neither a stop:
- The deployed proofs (`rollback-selftest-proof-1763.json`, `harness-live-proof-1763.json`, written 2026-10-13 10:45) are past the library's 24-hour limit (`$script:N5ProofMaxAgeHours = 24`). The n1 re-run needs `-SelfTest -WriteProof` on the live folder first; same reviewed bytes, one more line on the run sheet.
- The live folder's `spike-nep5-matrix.ps1` is not byte-identical to the one on main (sha256 8dcede19... live vs 0a9d6035... repo); the repo copy was rewritten after the 10-13 runs. Run n1 from the live bytes and cite their sha256 in the record; do not redeploy from main without a fresh review.
