# mxc_proxy_egress variant 4 (WFP capture) — pre-run review, 2026-10-16

Reviewer: independent, non-elevated self-test run; author is the variant-4 builder (#1798). Review hash `2f792246`
(code `2a31e583` + README), branch `feat/1799-standard-token`, worktree `BlarAI-worktrees/q3-standard-token`.
Prior approval: Q3 round 2 at `1c6638aa`.

## Verdict

**PASS (no BLOCKER, no HIGH).** Two MEDIUM findings and two LOW findings, none of which can turn a blind
instrument into a CAPABILITY-ONLY-SUPPORTED reading on a live launch; both MEDIUMs are reading obligations for
the post-run review, listed under "Conditions on the post-run reading".

## Findings

1. **MEDIUM — the variant-4 verdict has no denominator.** `summarise.py` `judge_variant4` (and its call in
   `judge_batch`, `wfp_runs = [r for r in runs if "wfp" in r]`) reads CAPABILITY-ONLY-SUPPORTED from however many
   run records exist, never against `runs_per_arm` x arms. A batch killed after its first launch, stopped by the
   FAIL break, or aborted for a held port leaves `batch-summary.json` with `variant4_wfp.verdict:
   CAPABILITY-ONLY-SUPPORTED, runs: 1`. Reproduced (pure function, review hash):
   `judge_batch([one run with a clean wfp reading], ctl, 3, wfp_control={'ok': True})` ->
   `variant4_wfp.verdict = CAPABILITY-ONLY-SUPPORTED` while the egress group reads INCOMPLETE (with a passing B5
   control) or INSTRUMENT-BLIND (without). Cost: a one-launch reading presented with the same verdict word as a
   full batch. Not blind (the one launch was really captured), so not a HOLD-safety defect; the `runs` field sits
   beside the verdict.
2. **MEDIUM — lock overclaims: "a run with no wfp record is never read as clean" holds for `judge_variant4` only,
   not through `judge_batch`.** `self_test.py` `test_variant4_group` feeds a no-wfp run straight to
   `judge_variant4` (which reads NO-CAPTURE -> INSTRUMENT-BLIND), but `judge_batch` filters such runs out before
   calling it, so the NO-CAPTURE branch is unreachable from the summary path and the docstring sentence "A run
   with no capture counts against it" is false at batch level. Reproduced: `judge_batch([clean wfp run, same run
   without 'wfp'], None, 2, wfp_control={'ok': True})` -> `CAPABILITY-ONLY-SUPPORTED, runs 1`. Incidence on a live
   wfp batch: no reachable path found — both branches of `run_one` set `rec["wfp"]` when `wfp=True`, and an
   exception writes no record at all (which is finding 1, not this). Reachable through `summarise.py <folder>` on
   a folder holding run files from a non-wfp batch.
3. **LOW — the verdict word claims more than the instrument sees.** CAPABILITY-ONLY-SUPPORTED means "no filter in
   the netsh dump names the container's package SID at the hold moment". It cannot see enforcement decided inside
   a callout driver (704 `FWP_ACTION_CALLOUT_UNKNOWN` filters on this host today), a filter present only while
   the payload's probes ran and gone before the hold point, or a SID carried in binary form inside a
   `FWP_BYTE_BLOB_TYPE` value or providerData. `judge_variant4`'s `not_measured` names none of these. Hypothesis
   class (no live observation of any of them); the write-up of a live result should name them as not measured.
4. **LOW — positive-control cleanup has one unguarded path.** `run_probe.py` `positive_control`: the `finally`
   calls `ps(...)` and `rule_count()` with a 120 s timeout; a `subprocess.TimeoutExpired` there propagates out of
   `finally`, crashes the batch and leaves removal unverified. The rule blocks outbound for a synthetic package SID
   that no process carries, so the leak is inert; and a left-over rule makes the next batch's control fail
   (`absent_after_removal` false -> INSTRUMENT-BLIND), the safe direction. Hypothesis (not induced).

## The brief's questions

**(1) Can a blind instrument read CAPABILITY-ONLY-SUPPORTED?** Not found. Per launch `analyse_wfp` reads
INSTRUMENT-BLIND on: any of the three captures missing, unparseable, or listing no filters; container SID unknown;
`alive` not True (pid and launcher alive before and after the during capture and release file absent); hold not
released; plus every `capture_pair` problem. The group needs the positive control `ok` (created, found by the same
`filters_referencing`, removal verified, SID absent afterwards). SID forms checked against the real host dump
(`netsh wfp show filters`, elevated, read-only, 1008 filters, `wfp_filters` parses all 1008): `FWP_SID` conditions
render as `<sid>S-1-…</sid>` (24 `FWPM_CONDITION_ALE_PACKAGE_ID` conditions, found by `filters_referencing`
on `S-1-0-0`: 24 hits); security-descriptor conditions render as SDDL text with literal SIDs (a capability SID
inside `<sd>` found: 6 hits). The search is a substring search over each filter item's whole serialised XML, so a
SID in any element, in an SDDL ACE, or in a display name is found. Filters added before the "before" capture and
kept are found too: the SID search runs over the whole during document, not the delta. Provider- and
sublayer-level objects carry no matching and are not filters; out of scope by construction. Residual blind spots:
finding 3, and the denominator in finding 1.

**(2) Positive control rule removed, and can it leak?** Removal is in `finally`, verified by `Get-NetFirewallRule
-Name` count 0, then a fresh capture must lack the SID. It cannot leak into a measured launch's verdict: its SID
is synthetic (`S-1-15-2-1111111111-…`), never equal to a container's; a constant rule present before, during and
after drops out of the delta. Not verified against real netsh/MPSSVC (no rule created, per the brief): whether
`-Package` with a SID of no installed package materialises a WFP filter is open; if it does not, the batch reads
INSTRUMENT-BLIND (safe direction, but a wasted run). The real dump shows the `ALE_PACKAGE_ID` -> `<sid>` form the
control relies on.

**(3) Egress HOLD/FAIL logic and F3.** The egress verdict chain in `judge_batch` is unchanged except the new
`state_unknown` test, placed after FAIL / state-changed / REFUSED / INSTRUMENT-BLIND and before HOLD: a record
without a dict `state_changed_by_run` now reads INCOMPLETE, never HOLD (locked, with the `{}` control). The F3
WFP half is disclosure only: `unreadable_under_this_token` is carried into `batch-summary.json` (both writers);
an unreadable WFP count still does not change a group verdict. Correct for the elevated variant-4 mode, where WFP
is readable; a standard-token HOLD must still be read with that list.

**(4) Refusals.** `--wfp-capture` returns 2 before any output directory exists when `--token standard`,
`--dry-run-only`, or `is_elevated()` is false. All three locked; the non-elevated one ran for real in this
review's self-test (not skipped).

## Self-test

`self_test.py` at `2f792246`, NON-elevated via `run_nonelevated.ps1` (Medium integrity, Administrators
deny-only, `whoami /groups` captured in the output): **246 PASS, 0 FAIL**, exit 0, `X_ZERO`. The non-elevated
`--wfp-capture` refusal check and `launch.ps1`'s non-elevated live-run refusal both ran (not skipped). Conditions:
other agent sessions active on the box; no MXC launch; no firewall rule created. Additional checks run by the
reviewer: elevated read-only `netsh wfp show filters` dump parsed with `summarise.wfp_filters` (1008/1008), and
pure-function reproductions of findings 1 and 2.

## What I attacked and could not break

Blindness paths per launch (missing / empty / unparseable capture, unknown SID, not alive, hold timed out); SID
rendering forms on the real host XML; pre-existing kept filters; control-SID cross-talk into launch verdicts;
refusal ordering; F3 ordering in the egress chain.

## Conditions on the post-run reading

- Read `variant4_wfp.runs` against `runs_per_arm` x launched arms before quoting the verdict (finding 1).
- Name callout-driver enforcement, transient probe-time filters and binary-form SIDs as not measured (finding 3).

## Approval

Written. `%USERPROFILE%\blarai-research-data\mxc-proxy-egress\APPROVED_SHA256.txt` now reads
`# approved 2026-10-16T11:56:33Z commit 2f792246 reviewer non-elevated variant4`, nine files, hashed with certutil
under the non-elevated runner and cross-checked with sha256sum (all nine equal; probe tree equal to `2f792246`).
The previous file is kept byte-identical as `APPROVED_SHA256.q3r2.txt` (`cmp` equal). Changed against round 2:
README.md, net_payload.py, run_probe.py, self_test.py, summarise.py; unchanged: launch.cmd, launch-standard.cmd,
launch.ps1, proxy.py. `launch.ps1 -VerifyOnly` under the non-elevated runner: `VERIFIED: all probe files match the
approved hashes.`, `PROBE_EXIT=0`, exit 0.
