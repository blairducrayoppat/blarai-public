# Independent pre-merge review: containment evidence (docs/containment-evidence) and ADR-049 (docs/adr-049-governator-reopened), 2026-10-05

Reviewer: independent adversarial reviewer, author of neither branch. Report only; nothing fixed.

Tested at: `docs/containment-evidence` @ `8b8c7df0` (worktree C:/Users/mrbla/blarai-wt-evidence; commits 9adcafc4, 5dd5af67, 8b8c7df0 off main 32e31564) and `docs/adr-049-governator-reopened` @ `96e985f0` (worktree C:/Users/mrbla/blarai-wt-adr049). Both hashes re-checked unchanged at the end.

Run:
- `tests/security/test_containment_evidence_bundle.py` @8b8c7df0: 10 passed (LOCALAPPDATA=$(mktemp -d), .venv Python 3.11.9).
- Throwaway merged tree (detached worktree of 32e31564 at a sibling path, `merge --no-ff` 8b8c7df0 then 96e985f0, removed afterwards): `test_doctrine_freshness` 19 passed, `test_doc_pointers_and_banners` 34 passed, `test_rules_corpus` 39 passed, `test_containment_evidence_bundle` 10 passed.
- `wfp-coder-egress-spike.ps1 -SelfTest` (documented as "no system change"; it does not dot-source helpers in that mode), Windows PowerShell 5.1, copies in the scratchpad: original 45 passed / 0 failed; bundled copy throws (V3).
- A semantic JSON comparison of all 7 bundled result files against the raw files in `blarai-research-data` (sanitiser re-applied to the raw side), and `diff` of every bundled script, README, preflight and review against its source.
- Vikunja #1671, #1689, #775, #1693 comments read through the MCP.
- No script that changes system state was run. No GPU or model work.

## Branch 1: docs/containment-evidence

### V1. BLOCKING: C1b attributes loopback reachability to the permit filter, and says C3b covers the model case; neither holds
- Where: `docs/research/account-level-containment-evidence-2026-10-05.md` C1b row (line 27).
- What is wrong: no run exercised the block without the permit, so nothing shows the permit is what "keeps" loopback open. The bundle's own `wfp-spike/README.md` (Interop risks) says: "if loopback is not evaluated there, check 3 still passes and the permit is simply unused". The C1b NOT-tested cell says "(C3b covers the model case, once)". It does not. All four filters sit on ALE_AUTH_CONNECT_V4/V6 (`wfp-coder-egress-spike.ps1:185-188`), and the README says "Block on ALE_AUTH_CONNECT is outbound-connect only; inbound accept is not touched". In Test B the confined account is the LISTENER and the operator makes the connection, so the account's filters never see that flow. Test B would pass with no permit filter at all.
- Cost: the product-shaped direction (the confined coder as a CLIENT of a model server over loopback) rests on a stub listener only (3 of 3). The document tells the reader the model case is covered once.
- Reproduced: by reading the filter layer constants and `testB-20261005-160210.json` (`steps.serve_port`, `steps.operator_request`). The missing toggle arm is an absence, so there is nothing to execute.
- Fix direction (the author's call): restate C1b as "loopback reachable while blocked (stub listener)". Delete the C3b cross-reference. Name the permit-off arm and the coder-to-real-server direction as NOT ESTABLISHED.

### V2. BLOCKING: §1 and §7 state the capability in general, present-tense terms that go beyond what was observed
- Where: §1 line 8-9 ("kept a dedicated, low-privilege Windows account from reaching the internet"). §7 line 115-117 ("It gives OS-enforced, non-cooperative containment of a process tree ... for network egress ... and for file access ... A program running under that account cannot switch either off").
- What is wrong: what was observed is one IPv4 TCP connect to 1.1.1.1:443 per reading, about 5 s (C1) and about 127 s (C3b) windows, in a DYNAMIC session that exists only as long as the operator's elevated process holds the engine handle. That is fail-open on the installer's exit (`wfp-spike/README.md`: "closing the engine handle OR the process exiting/dying ... removes ... all four filters"). "Gives ... containment ... for file access" sits beside C2b (FALSE for `blarai-coder` today, #1678) and C6f (contradicted, #1692). §7 is the "what this gives a product" section. A reader building The Governator's claim will lift it verbatim, and "cannot" is exactly the word the brief bars.
- Fix direction: "The observations are consistent with ..." plus the conditions (IPv4 TCP 443, seconds-long dynamic session, spike account for files), and §1 "from connecting to 1.1.1.1:443".

### V3. BLOCKING: the bundled scripts are not "sanitised and nothing else". The sanitiser broke their self-tests and the cleanup verifier
- Where: bundle `README.md` lines 16-22 ("Sanitising applied (and nothing else)", "SID domain parts are replaced ... the last number is kept", "No numbers ... were changed"). Doc §5 line 95 ("The self-tests (`-SelfTest`, `-DryRun`) change nothing") and the run order, which starts with `-SelfTest`.
- What is wrong: the SID regex was applied to FABRICATED test literals, which were never real SIDs. `S-1-5-21-1111111111-2222222222-3333333333-1001` and `S-1-5-21-1-2-3-1001` became `S-1-5-21-X-X-X-1001`. The code's own guard `^S-1-5-21-\d+-\d+-\d+-\d{3,}$` (`wfp-coder-egress-spike.ps1:166`) rejects that form. The literals were rewritten at:
  - `wfp-coder-egress-spike.ps1` 465-466, 583 (the read-only removal check used by `-Live`) and 643
  - `spike-wfp.ps1` 349 and 397
  - `spike-verify-cleanup.ps1` 29 and 103 (the elevated WFP lookup now always throws, becomes a failed check, so "exit 0 = clean" is unreachable)
  - `spike-provision.ps1` 103-104 and `spike-cleanup.ps1` 103.
- Other changes the README does not declare: the UTF-8 BOM was stripped from `spike-lib.ps1`, and mojibake was repaired in `preflight/775-preflight-2026-10-05.md` (not only "one ... in the WFP results"; each WFP result file had two, rewritten to `--`, not restored to an em dash).
- Reproduced:

      powershell.exe -File <scratch>/orig/wfp-coder-egress-spike.ps1 -SelfTest  -> "SelfTest: 45 passed, 0 failed"
      powershell.exe -File <scratch>/bund/wfp-coder-egress-spike.ps1 -SelfTest  -> Exception calling "Build" with "1" argument(s): "refusing SID (not an account-domain user ..."

- Incidence: 12 literals across 5 of the 8 scripts. Every bundled reproduction path that builds a plan is affected.
- Fix direction: sanitise only real SIDs (the domains `1000000001-1000000002-1000000003` and `76345465-...`), leave the fabricated literals alone, and make the README's "nothing else" true. A bundle test that runs the WFP `-SelfTest` would lock it.

### V4. SHOULD-FIX: the status column softens two negative results
- C6f's evidence column says "Contradicted for the research models", yet the status is `NOT ESTABLISHED`.
- C2b says "for the coder this claim is FALSE today", yet the status is "NOT ESTABLISHED for `blarai-coder`".
- The status vocabulary (line 21) has no word for "contradicted", so a negative result reads as merely unknown in the column a skimmer reads.

### V5. SHOULD-FIX: two §3 sentences are false against the raw files
- "The three result files differ only in clock fields and uptime" (line 45). `diff` shows they also differ in every connect latency (`ms`: for example 24 vs 25, 37 vs 20) and in `filter_ids` (407213-16 / 407217-20 / 407221-24).
- "Three runs inside about 45 seconds" (line 46). The first run started at 23:59:31.0 and the last finished at 00:00:28.3, which is 57 s. The starts alone span 46.9 s.

### V6. SHOULD-FIX: what `outbound_blocked` means is defined in an unbundled file, and the bundled raw data carries a vacuous `true`
- `outbound_blocked=True` comes from agentic-setup `scripts/coder-containment-probe.ps1:33-48`. It is PASS whenever the connect does not complete within 5000 ms OR throws, so any failure counts as blocked. The WFP README discloses this (attribution rests on the baseline and post-removal arms, which is correct). The document's C1 evidence cell does not, and the file is not bundled.
- The `-Live` path also needs `coder-leg-run.ps1` and `coder-containment-probe.ps1` (run by the task), not only the two dot-sourced helpers the bundle README names. So (f) holds only in part: "needs agentic-setup helpers not in the bundle" is true, but the list is incomplete.
- Every bundled WFP result has `"secret_reads_denied": true` under `coder_baseline`, `coder_during` and `coder_after_removal`, while the probe was sent `secret_paths = @()` (`wfp-coder-egress-spike.ps1:593`; the README "Deviations" says so). That is a confident value from an empty check. The document does not cite it, but it sits in the raw data the document says supports C1. It needs one sentence.
- Contrast for the record: C3b's block reading is the specific WSAEACCES signature (WinError 10013, 6.9 ms), stronger than C1's "did not connect".

### V7. SHOULD-FIX: two durations are upper bounds stated as measurements
- "Filters stood about 5.1 s in all (timestamps)": engine close is not timestamped. 5.13 / 5.35 / 5.13 s is `filters_added.at` to the read of the post-removal probe result.
- "Coder probed at about 3.2 s": `coder_during.t` is `Get-Date` at the moment the operator READ the result (`ConvertTo-ProbeObservation`), not the time of the probe.
- Both are bounds, which is fine if they are called bounds.

### V8. SHOULD-FIX: C3b's attribution control comes from other runs
- Test B has no baseline for the spike account and no post-removal probe of its egress. The only evidence that its egress is open without the filters is Test A (CONNECTED at 15:58 and 15:59, before Test B started at 16:00:02).
- C1 earned "attributable to the filters" with in-run arms. C3b borrows the arm, and the row should say so.

### V9. SHOULD-FIX: the tok/s metric is not named
- The ranges "3.7 to 8.5" (confined) and "4.5 to 4.8" (control) are `tok_per_s_tpot`.
- By wall clock (`tok_per_s_wall`) they are 3.66-7.73 and 3.89-4.49. C6a claims no ratio, so this is labelling, not a wrong conclusion.

### V10. SHOULD-FIX: the integrity lock does not cover two of the three sanitising claims
- `test_containment_evidence_bundle.py` checks only the user name and machine name. The README's other claims are SID domains replaced and model text cut to 100 characters.
- I grepped: no `S-1-5-21-<digits>-<digits>-<digits>` remains and every text field is truncated, so this is clean today and unlocked tomorrow.
- The docstring's HONEST LIMIT is accurate about the form-versus-support gap, but the module header says "names scrubbed" while the README promises more.

### V11. NOTE: §4 negative results, precision
- M2 is presented as open ("reasoned bounds, NOT raced"). The review's round 3 reports "M2: FIXED" (line 256), and the "not raced" item in the review is the junction-under-`prompts\`/`logs\` residual, not hard links. This understates rather than overstates.
- The bundled `#1690` review is the 6-round copy from the UNMERGED branch `feat/1690-install-hardening` @ `22efaac9`; it is not on main. Cite the commit.

### V12. NOTE: a correction the document makes but the ticket does not
- #1689 c.3896 says the control ran "at the same time". In the raw data, the control started at 16:02:18.9, after Test B finished at 16:02:10.7.
- The document correctly says "run later", but §3's corrections list omits this one and the ticket carries no correction comment.

### Verified clean (branch 1)
- **C1 per-run counts:** 6 of 6 operator baseline, 3 of 3 watchdog, 2 of 2 operator-during, 4 filters in one transaction, `sid_is_coder=True`, removal objects absent, coder egress open after, exit 0. All three files, all as stated.
- **WFP environment:** Bitdefender process names, firewall profiles, BFE and mpssvc running, PS 5.1.26100, Windows 10.0.26200 (as stated). The `hold_seconds: 100` versus about 5 s disagreement is disclosed.
- **C2a:** 8 of 8 denied in Test A run 2 and in Test B. Run 1 failed on `MethodInvocationException`, and 7 of 8 messages did say access denied (the eighth, `.git-credentials`, was "The directory name is invalid"; the probe changed kind). July check 2 PASS (#775 c.1654, n=1). Pre-flight: 5 paths with no coder ACE, non-elevated.
- **C2b:** 4 of 4 outside writes denied in both passing runs; informational writes to `C:\Windows\Temp` and `B:\models` allowed.
- **C3a:** identity and token fields; load times 24.773 / 17.192 / 33.685 s; 64 tokens twice per run; OpenVINO and GenAI versions; free RAM 19.4-19.56 GB.
- **C3b:** HTTP 200, `model_loaded`, 32 tokens, 7670 ms; mid-hold 10013; task-end probe blocked; watchdog 94 of 94; removal verified; operator connect OK after; filters about 126.7 s.
- **C5:** #775 c.1653, c.3893 and #1671 c.3873, c.3891, c.3894 quoted faithfully.
- **NOT-ESTABLISHED items:** reboot, IPv6, UDP and DNS, other ports, other AV, other driver, 14B/MTP/streaming, speed parity, and `blarai-coder` file confinement under the projects grant are all present.
- **Fused-leg and #1690 findings:** L1 (including the looser variants), M1, N1 (35 s race, 31 passed / 391 refused, victim repo untouched), M3, N2 (3 survivors), N3 (2 survivors), ADR-043's "24+ ... 4000+", and the seed-31337 caveat all match the reports.
- **Sanitisation and data integrity:** numeric values are unchanged in all 7 JSON files. No user name, machine name, real SID domain, password or token is in the bundle or the document. The preflight and both reviews are byte-identical to their sources apart from name substitution (and the mojibake noted in V3).

## Branch 2: docs/adr-049-governator-reopened

### A1. BLOCKING: the fragment's plain-summary line says "the agent cannot talk its way past it"
- Where: `docs/journal_fragments/2026-10-05_the-governator-reopened-on-a-narrower-claim.md` line 3. Also line 7: "nothing the agent does at its own seam changes it".
- What is wrong: "cannot" beyond the observed (V2), in the line the journal uses as its searchable index and the portfolio surface reads first. The body then lists the limits correctly, so the summary contradicts its own entry.

### A2. SHOULD-FIX: words in the LA's quote that he did not say
- ADR-049 line 12, register row line 119, the fragment and the #1693 description all quote him as *"between this [the account-level containment evidence] and the BitDefender study results ..."*.
- The bracket is the session's reading of "this", placed inside the verbatim quote and not labelled. The ADR is careful elsewhere ("Which results he meant is his to say") and should be careful here too: mark it as the session's gloss, or move it outside the quote.

### A3. SHOULD-FIX: "supersedes ADR-042 Decision 1 ONLY" is contradicted by ADR-049's own Decision 2
- ADR-049 Decision 2 rewrites ADR-042 Decision 6. Decision 6 says the governator repository's "disposition is the LA's — archive, keep privately, or delete" and "No session works in it". ADR-049 says the repository is "kept, untouched until scoped" and "not worked in ... until a scope exists".
- It also re-affirms Decision 3 as "moot", but Decision 3's stated ground is "there is no second party", which the reopening removes. Whether Decision 3 stays moot is a governance ruling the session made, not "as recorded".
- Either widen the scope statement or label these as the session's readings for the LA to confirm.

### A4. SHOULD-FIX: the limits omit the negative results that bear on the candidate claim
- The candidate claim (#1693) is "cannot reach the network or read your files". The ADR's limits list omits:
  - `B:\models` writable by the confined account (#1692)
  - `blarai-coder` holding Modify, and so read, on the whole projects folder (#1678)
  - `C:\blarai-fleet` writable by every local account (#1686)
  - coder egress open today (`containment=off`)
  - the Test A run-1 classifier failure.
- Context item 2 reports "8 of 8 ... 4 of 4" without the informational writes that were allowed.
- The evidence document carries all of these. The ADR, which is the decision record, does not.

### A5. NOTE: session judgements not labelled as the session's
- The title and Consequences ("The claim ... is NARROWER") and the Re-visit triggers ("a different antivirus product, a Bitdefender or GPU-driver update, or any bypass") are not marked as the session's, though Options A and B are.
- "3–5 seconds" matches #1671 c.3891; the raw upper bound is 5.1-5.35 s (V7).

### Verified clean (branch 2)
- **Funding and time:** nothing is invented on funding, dates or commitments; the 8–14 h/week and "effectively full time" figures are quoted from ADR-042 Consequences and marked undecided.
- **Status values:** ADR-049 "Accepted (LA decision 2026-10-05)" and the ADR-042 banner.
- **ADR-042 Context:** quote, 37/37 and Decisions 2-5 restated faithfully. 37/37 traces to appendix `A3-seam6-network-probe.md:59`.
- **Cross-references:** #1549, #1590, #1671 c.3873/3891/3894, #1689 c.3882/3896, #775 c.1653/1654/3874/3893 and `50f7100d` resolve. The evidence-document path is correctly marked "on branch, not on disk".
- **Locks and format:** the banner passes `test_doc_pointers_and_banners`. The register row follows the "Updated YYYY-MM-DD (...; #ticket, ADR-N)" form of its neighbours. The fragment has a dated header, `*Plain summary:*`, first-person narrative, a rejected path named, an unnumbered `**Proposed lesson:**` and `**Next:**`, per `docs/journal_fragments/README.md`. LESSONS.md has no existing class on narrowed claims.

## Merge read

- **docs/containment-evidence: NOT MERGE-READY.**
  - Block on V1 (the C3b cross-reference is false, and the permit attribution is unsupported), V2 ("gives" / "cannot" in the product section) and V3 (the bundle's "nothing else" is false, and its reproduction path is broken, reproduced).
  - V4-V10 are wording-level and cheap. None changes a count: every n-of-n in the claims table matches the raw files.
- **docs/adr-049-governator-reopened: NOT MERGE-READY.**
  - Block on A1 (a "cannot" in the index line).
  - A2-A4 are should-fix and small. A4 matters most for the product question, because it is the part of the evidence that cuts against the candidate claim.
  - The decision record itself (LA reopened; supersession; nothing invented on funding) is sound, and the docs suites pass on the merged tree.

---

# Round 2: re-verification at `e9209a4c` (evidence) and `e272935a` (ADR-049)

Same raw data and sources as round 1. Run:
- Bundle test: 30 passed.
- Every bundled script's `-SelfTest` (wfp-coder-egress-spike, spike-provision, spike-cleanup, spike-wfp, spike-verify-cleanup, spike-run-test), under both pwsh 7 and Windows PowerShell 5.1, with TEMP in a scratch dir: all passed, and the scratch dir was left empty. The bundled WFP script gave 45/0.
- The original WFP script's `-SelfTest`: 45/0 in both shells.
- `verify_disposition.py` on both records: 14/14 and 5/5 PASS. Every cited SHA (e87c4b71, a8db647e, 17b94c50, e9209a4c, f9238e0d) exists and is on its branch.
- Throwaway merge of main 32e31564 with e9209a4c and e272935a (detached sibling worktree, force-removed afterwards; it held only the two throwaway merge commits): doctrine_freshness 19, doc_pointers_and_banners 34, rules_corpus 39, containment_evidence_bundle 30, disposition_discipline 43, all passed.
- Bundle against originals, with the CHANGES.md rules applied by an independent script: the 15 text files are byte-identical, and all 7 JSON files are semantically equal (numbers unchanged). The single text difference, the confined README orphan-SID line, is accounted for. CHANGES.md therefore lists every transformation, measured against the CURRENT originals. See N1.

## Round-1 findings
- **V1 CONFIRMED FIXED.** C1b: "the account as client; not shown to be caused by the permit filter". C3b: "the confined account acting as the LISTENER ... this does NOT test the permit filter". C6g was added.
- **V2 PARTLY FIXED.** §1 and §7 are now conditioned ("in these runs", "windows of at most about 5 s", "fail-open"). They introduce a new overclaim, recorded as N2.
- **V3 CONFIRMED FIXED.** Fabricated SIDs are untouched, every self-test passes in both shells, and the BOM is kept. The provenance of the scripts is a separate new defect (N1).
- **V4 CONFIRMED FIXED.** C6f: "CONTRADICTED". C2b: "CONTRADICTED for `blarai-coder` today".
- **V5 CONFIRMED FIXED.** "differ in clock fields, uptime ..., every connect latency and the filter ids"; "about 57 seconds".
- **V6 CONFIRMED FIXED.** "ANY failure counts ... `coder-containment-probe.ps1`"; "`secret_reads_denied: true` ... is vacuous". The README names all 4 agentic-setup scripts.
- **V7 CONFIRMED FIXED.** "filters stood AT MOST about 5.1 to 5.4 s ... engine close is not timestamped"; "a read time, not the probe time".
- **V8 CONFIRMED FIXED.** "comes from the earlier Test A runs ... not from an arm inside Test B".
- **V9 CONFIRMED FIXED.** "`tok_per_s_tpot` ...; by wall clock `tok_per_s_wall` 3.66 to 7.73".
- **V10 CONFIRMED FIXED.** The test locks SID domains, text truncation, CHANGES counts and the self-tests, each with a toggle test.
- **V11 CONFIRMED FIXED.** "the round-3 review reports M2 FIXED"; "copy from the unmerged branch `feat/1690-install-hardening` at `22efaac9`".
- **V12 PARTLY FIXED.** #1689 c.3897 now exists, but §3 line 61 still says "(no correction comment exists on the ticket)". Prose outlived its fix.
- **A1 CONFIRMED FIXED.** The plain-summary line now reads "in these runs an outbound connect from the account failed while the filters stood ... with the limits stated below".
- **A2 CONFIRMED FIXED.** The quote is now exact, with the gloss outside it: "The session's reading, which the LA may correct".
- **A3 CONFIRMED FIXED.** "Supersedes ADR-042 Decision 1 and the repository disposition in ADR-042 Decision 6; flags ADR-042 Decision 3's ground for re-examination". The banner and the register row match.
- **A4 CONFIRMED FIXED.** A new bullet, "Results that cut against the candidate claim", lists #1692 (B:\models and C:\Windows\Temp), #1678, #1686, egress open, the stub-only permit and the Test A classifier bug.
- **A5 CONFIRMED FIXED.** "(the session's reading)"; "(The session's proposal, not the LA's.)"; "upper bound of 5.1–5.35 s".

## New findings
- **N1 BLOCKING (evidence branch): the bundled confined-model scripts are not the scripts that produced the results.**
  - The raw "originals" in `blarai-research-data/confined-model-spike/` were edited AFTER the runs. File mtimes are 16:44-16:50 for README, spike-cleanup, spike-lib, spike-provision, spike-verify-cleanup and spike-wfp. The runs were 15:58-16:02 and the cleanup about 16:25. The edits are the e87c4b71/a8db647e hardening.
  - The bundle copies those post-run versions. For example, `spike-wfp.ps1`, which produced Test A and Test B, differs from the as-ran copy in 9adcafc4 by +37/-8 lines (Read-UntrustedJson, Test-LoopbackPort, a new self-test block). `spike-lib.ps1` differs by +194, `spike-cleanup.ps1` by +151.
  - The as-ran versions now survive only as the round-1 sanitised copies in git 9adcafc4. The unsanitised as-ran originals were overwritten.
  - Nothing in CHANGES.md ("Every file here is a copy of a raw source. The ONLY transformations ..."), the bundle README or doc §5 says that the scripts are post-run revisions. §4 describes the e87c4b71 fix but not that the bundle carries the fixed version. A reader who reruns `spike-wfp.ps1 -TestB` runs different operator-side code from the code that produced `testB-20261005-160210.json`.
  - Unchanged since the runs: spike-run-test.ps1 (15:59:07, before run 2 at 15:59:14), spike_model.py, Run-Spike-AsAdmin.cmd and the WFP spike folder.
  - Fix direction: bundle the as-ran versions recovered from 9adcafc4 (re-sanitised) as the evidence copy, and the hardened versions separately and labelled. Or at least state, per file, "revised after the run; as-ran copy at 9adcafc4".
- **N2 BLOCKING (evidence branch): new overclaim on writes.**
  - §1 lines 12-13 say the throwaway account "could not read the operator's secret folders or write outside its own folders". §7 line 144 says the observations "refused the spike account reads and writes outside its folders".
  - The raw data shows the account WROTE `C:\Windows\Temp\spike-write-test.tmp` and `B:\models\spike-write-test.tmp` (`informational_writes`, outcome allowed, in testA-155954 and testB). C6f says so itself.
  - Fix direction: "4 of 4 tested outside writes denied; writes to C:\Windows\Temp and B:\models allowed".
- **N3 SHOULD-FIX: a stray control character renders a path wrongly.**
  - A backspace (0x08) inside the path at evidence doc line 85 renders as `C:larai-spike`.
  - The same defect is in the ADR-049 fragment line 11 (`C:larai-fleet`).
- **N4 NOTE: the generator is not committed.**
  - CHANGES.md says "generated by the build step; do not edit by hand", but no generator is committed, so the table cannot be regenerated.
  - The test recounts the placeholders, which is the real lock.
- **N5 NOTE: §8 still says "a raw WFP block was enforced ... and ACLs held".**
  - "ACLs held" is unqualified beside C2b and C6f, both CONTRADICTED.
- **N6 NOTE: ADR-049 status mixes the LA's decision with a scope still awaiting his confirmation.**
  - The status is "Accepted (LA decision ...; the supersession scope below is the session's reading, for the LA to confirm)". The supersession scope is pending his confirmation while the ADR reads as Accepted.
  - Acceptable if the gate (#1693) carries that confirmation as an item.

## Round-2 merge read
- **docs/containment-evidence @ e9209a4c: NOT MERGE-READY.**
  - Blockers: N1 (the bundle's scripts are not what ran, and this is undisclosed) and N2 (the new "could not write outside its own folders").
  - Also fix: V12's stale sentence and N3.
- **docs/adr-049-governator-reopened @ e272935a: MERGE-READY once N3 is fixed.** The fragment control character is a one-character fix.
  - All of A1-A5 are fixed as quoted.
  - The ADR cites tickets, not the evidence document's §1 and §7, so N2 does not reach it.

---

# Round 3 (narrow): `c3fc9fa4` (evidence) and `6683d3f3` (ADR-049)

- **R3-1 BLOCKING: the bundle test FAILS on a fresh checkout, which includes merged main.**
  - The repo runs with `core.autocrlf=true`, and nothing in `.gitattributes` covers the bundle. A fresh checkout therefore writes the as-run files with CRLF line endings.
  - `MANIFEST.sha256` holds the hashes of the LF working copies in the builder's worktree.
  - Throwaway merge of main 32e31564 + c3fc9fa4 + 6683d3f3: `test_containment_evidence_bundle` gives 2 failed / 45 passed. The failing tests are `test_changes_and_manifest_are_what_the_generator_produces` and `test_as_run_scripts_match_the_recorded_manifest`, all 9 manifest hashes differ, and `as-run/spike-wfp.ps1` hashes 33d5f72c… against 4aaeafdd… in the manifest.
  - The same test passes 47/47 in the builder's worktree, which has never been re-checked out.
  - Consequence: merging turns the standing gate red, and the "pinned" hashes describe one checkout's line endings, not the stored files.
  - Separately, the original `spike-run-test.ps1` is CRLF while the bundled copy is stored LF, so "Script bytes ... otherwise untouched" is not literally true.
- **R3-2 SHOULD-FIX: C2b's claim text and status disagree.** The claim cell reads "The account cannot write outside its own folders (4 specified targets denied; `C:\Windows\Temp` and `B:\models` were writable)" with status OBSERVED 2 of 2, but the parenthesis contradicts the claim. Restate the claim as "4 of 4 specified outside-write targets denied", or mark the general claim CONTRADICTED, as C6f does.
- **R3-3 NOTE: the manifest is self-generated.** `make_changes.py` hashes the bundle's own files, so the manifest proves only that the files did not change since they were generated, which git already proves. It is not provenance evidence.
- **R3-4 NOTE: one provenance step is inferred, not recorded.** "Test A run 2 and Test B ran the bundled `spike-run-test.ps1`": the task runs a copy in `C:\blarai-spike\bin` made at provisioning (15:56:56), and the source was edited at 15:59:07, 7 s before run 2. Run 2's output matches the fixed classifier (inner exception unwrapped, `.git-credentials` read as a file), which supports the claim, but how the fixed copy reached `bin` is not recorded. Say "inferred from the run output".
- **Verified.**
  - as-run versus the first bundle commit 9adcafc4: the only differences are the restored fabricated SID literals (matching the round-1 raw diff line for line), the placeholder renames and spike-lib's restored BOM.
  - Every as-run and post-run-hardened `-SelfTest` passes in pwsh 7 and 5.1, and the scratch TEMP dir was left empty.
  - The CHANGES line counts equal `git diff --numstat` (+32/-3, +180/-0, +124/-19, +20/-5, +5/-5, +19/-0), and `make_changes.py --check` reports up to date.
  - §1, §7 and §8 now match the raw data (8/8 reads and 4/4 specified writes denied; `C:\Windows\Temp` and `B:\models` written).
  - No control bytes in any changed file on either branch.
  - The dispositions verify: 20/20 and 5/5, with SHAs on-branch.
  - On the merged tree, doctrine_freshness 19, doc_pointers_and_banners 34, rules_corpus 39 and disposition_discipline 43 pass.
  - ADR-049 at 6683d3f3: the status separates the LA's reopening from the "supersession scope as drafted: pending LA confirmation", and the backspace character is gone.
- **Merge read.** docs/containment-evidence @ c3fc9fa4: NOT MERGE-READY (R3-1). docs/adr-049-governator-reopened @ 6683d3f3: MERGE-READY.
