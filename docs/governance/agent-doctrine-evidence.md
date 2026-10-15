# Agent doctrine — the evidence record

CLAUDE.md and the agent files under `.claude/agents/` state current rules without their
history: dates and incident archaeology dilute always-loaded instructions (Anthropic's own
prompt-audit guidance names history-narratives as an anti-pattern), but this project does not
assert rules it cannot prove. This file is the audit trail — each rule's originating incident,
with the artifact that proves it. When a correction adds a rule to an always-loaded surface,
append its evidence here in the same motion. Never delete a row; supersede it.

## dod-witness

- **Capability 11 / "check RAN" ≠ "check FLAGGED"** — 2026-08-16: the first-ever website
  `coder-test-qa` record (`status: clean, hard: 0`, run `20260816-134142-bd`) tempted promotion
  of rows 4/5 **on the website surface**; neither row's observable had fired ON A WEBSITE (both
  already read LIVE on the Python surface — row 5 since 2026-08-14). Rows amended to say
  exactly that instead.
- **The ```roadmap block wins / never take a COUNT from a card** — 2026-08-16: the landing card
  named #1418/#1410 as rank 1 while the block said #1433; the card sat 10 first-parent commits
  (12 total) behind disk — `git rev-list 2fbb846c..be2e1d34`, endpoints written down because a
  "measured" figure with no endpoints cannot be re-measured, and a round-2 review mis-measured
  it from a mid-card SHA instead of the frontmatter anchor. The first draft of the correction
  itself said "eight" from memory.
- **Evidence class EXECUTED vs DERIVED + the both-surfaces rule** — 2026-08-16: "the stylesheet
  defines a page container and no page applies it" was built from one exact-word grep, told to
  the operator as fact, and inherited by a running builder. His screenshots falsified it (a
  centred contact card and a flush-left gallery in the same build); the real defect was
  cross-file — pages referencing a wrapper the stylesheet never defines (#1435, corrected in
  its comments, correction chased into the builder mid-flight).
- **A fix LANDED only in the delivered tree / a closing line is prose** — BlarAI `32bed3fb`:
  "found, fixed, re-verified in one run" was banked into DoD row 15 and believed all day, until
  the operator pressed Send and nothing happened. The delivered `enquiries.js` still carried
  all five `export` statements; the re-capture showing the fix did not exist; and
  `run-fleet-design-fix-1.log` printed "RESULT: MERGED into your project - just open the app
  and try it" after FIX #1 FAILED, FIX #2 FAILED, FIX #3 produced no changes (#1303, dated
  comment 2026-08-17). Third time his hands found what the gates passed (#1345, #1406, this).
- **Side-file fields validated programmatically** — each of the three (`pass_banking_frozen`,
  `completed_passes` < `target_full_passes`, `end_date` present) has cost a failed launch;
  `end_date`'s own in-script comment is wrong (#1045).
- **Preserve the outgoing sandbox** — the carry-on machinery the operator asked for is not
  built (#1321/#1381); the battery archives and recreates `~/projects/<card>`.
- **The discriminating split** — the first dod-witness session's control for the
  page-container check. The 2026-08-16 form was the weaker two-fixture toggle (this delivery
  FAILS / a wrapped page PASSES); the sharp same-run per-page form — "last night's contact page
  must pass while its gallery page fails, in the same run. If the check can't produce that
  split it's measuring the wrong thing" — is the 2026-08-17 correction (#1435 comment 3205).
- **Builder reports are claims** — 2026-08-16: a builder's "24 tests, every lock
  mutation-proved" was relayed to the operator in a verifier's voice before any review ran.
- **The calibration trigger is wider than his words** — the first session was corrected twice
  on 2026-08-16 (his screenshots; the Send button) and the agent file was not touched either
  time; both lessons had to be mined from git by a later session (#1442).
- **Gate-honesty one-liner** ("if your gate says wait, wait — or name the exception in it") —
  2026-08-16: a gate ending "waiting before I touch the tree" was followed minutes later by
  the first of that evening's direct-to-main doctrine commits (`fcb61ed1` 15:56 through
  `16dac58d` 21:38) — defensible meta-doctrine, but the reviewer paid the reconciliation cost.
- **A ticket's DONE list is a claim** — 2026-08-16: #1416's DONE list named four existing
  Python defect classes; three did not exist (disposition record
  `docs/reviews/coder-test-qa-node-disposition-2026-08-16.md`).
- **Run the code, do not read it** — 2026-08-16 (#1416 arc): fourteen defects in one function
  found by feeding it ordinary JavaScript, zero found by reading the pattern.
- **Sentences rot; tests do not** — 2026-08-16: three separate docstrings in one day described
  behaviour their code no longer had (same disposition record as above).
- **Grep every consumer across BOTH repos, and believe the grep** — `16dac58d`: the bullet
  teaching the rule carried a consumer claim that was itself ungrepped; the grep disproved it
  and found the real state (a field with zero consumers, banked as bare file-presence).

## adversarial-reviewer

- **Expected yield / a clean first round means a weak brief** — 2026-08-16: six rounds against
  work its author believed finished and had toggle-proved found 3 HARD false positives, 2 wrong
  spares, 2 locks certifying more than they tested, 6 unrecognised declaration forms, a
  design-document overclaim, a journal miscount, and a wrong ownership claim — 58 findings
  total in the disposition record above.
- **Denominator attack** — link-lint reported at 1.5% of all runs; 8.6% of web runs once the
  runs it never applied to were excluded (#1431, corrected the same day it was filed).
- **Summary lines vs their own record** — `run-fleet-design-fix-1.log` (see `32bed3fb` row
  above); and the 2026-08-17 digest printing "some work did not land, and it said so" two lines
  below "7 of 7 pieces of work were merged" (#1442).
- **Feed it a neighbour** — 2026-08-17: the digest cited a nine-day-old capture
  (`critique-pottery-studio-pieces-list-page`, banked 8 August, fleet run `20260808-104536-bd`)
  as last night's browser result — "no page errors" — while the run's own sidecar read
  `errorCount: 1, hard: true`. An unscoped glob over the shared `state/reports/` pool. The
  neighbour was NOT a foreign project: it was an earlier fleet attempt at the SAME pottery-site
  goal — the most plausible possible substitute, which is what made the wrong sentence
  undetectable from the citation (#1442, adversarial round 1 sharpened this row).
- **A lock can certify more than it tests — or mandate a defect** —
  `test_a_defect_the_run_REPAIRED_is_not_reported_as_current` required the neighbour-glob
  behaviour, built on the premise `32bed3fb` retracts: that a fix-cycle capture describes the
  delivered state (#1442).

## instrument-forensics

- **What the successes have in common** — one day's yield, 2026-08-16: all five link-lint
  producers were `surface=web` (#1431); every website delivery returned `no-tests` because the
  scanner read Python only (#1416); the one `hard >= 1` in 108 records was a Python card, which
  told the program exactly what rows 4/5 still needed.
- **Provenance before content** — the 2026-08-17 neighbour-capture incident above (#1442): the
  values were perfectly readable, maximally plausible (an earlier attempt at the same goal),
  and still not the case's subject.

## CLAUDE.md

The incidents behind rules whose inline stories were converted to one-clause reasons on
2026-08-17 (#1442, LA-directed):

- **THE CLOCK / elapsed time is measured** — 2026-08-06: a session computed every staleness
  figure in its gate a day out from the UTC-injected date, then drifted eight hours believing
  it was past midnight at 07:50.
- **Deferral momentum** — 2026-07-20: two review findings were ticketed to preserve the
  feeling of finished and reported to the LA as handled; both needed no decision and were
  fixed the same day once he asked.
- **authority_first** — 2026-07-22: four instances in one day of deriving what a surface
  already records. The four surfaces the rule names are the record; no surviving artifact
  enumerates the four instances themselves (searched: LESSONS.md hot index + archive), so any
  1:1 mapping of instances onto surfaces is DERIVED, not documented — this row says so because
  the rule it evidences demands exactly that admission.
- **Never manufacture a stop** — 2026-08-09: "you are throwing up gates" — four times in one
  session. (The quote's only prior record was CLAUDE.md itself; this row is now its home.)
- **Documentation is not evidence** — 2026-07-20: three independent instances in one hour — a
  README hiding a binary's silent detached fetches; a datasheet claiming a CPU feature ADR-007
  measured absent; an integration plan asserting "no network stack" that its own source
  contradicts. Each made the riskier option look safer.
- **Gate kill shapes** — each shape happened live before its control existed: a leaked
  Assistant Orchestrator on port 5001 turned failures into silent skips (now a fail-loud
  detector); a launcher instance-lock `os._exit` in a test silently killed the gate at 76%; a
  test's boot-reconcile tree-killed a live production dispatch.
- **Snapshot byte-bloat** — 2026-07-20: 15 line-count-compliant snapshot bullets had swollen
  to 7.4 KB — 15% of the file, leaving 137 bytes of size budget.
- **Never "execute end to end"** — 2026-07-05: a handoff prompt steered the successor past
  the comprehension gate; the gate exists precisely to catch what the predecessor missed.
- **Comprehension-gate MONITORING point** — 2026-10-04 (#1668): the LA, reviewing the #1663
  Qwen3.5-4B Phase 1 delta-gate — which had no monitoring plan for hours of unattended GPU runs —
  asked whether the gated session would watch its long runs: "maybe every 15 minutes or
  something? We can't waste time simply because the agent wasn't watching while also not wasting
  tokens." He then asked that the comprehension-gate template be fixed so every future gate works
  out what monitoring the effort needs. Earlier record of the same failure: 2026-09-24, a watch
  re-armed every 30 minutes still left him reading an overnight run as stopped (memory
  `feedback_long_runs_must_show_progress`).
- **History moved out of CLAUDE.md to fit its 48,000-byte budget** — 2026-10-04 (#1668): the
  MONITORING point needed 565 bytes against 52 of headroom; no rule was cut and the budget was
  not raised (precedent: the 2026-09-17 DECISION_REGISTER row on #1566). Moved verbatim, each
  clause from the place named: `<authority>` — "Rewritten 2026-07-13 from the prior prose version
  (preserved in git history) into this agent-directed form at the User-Operator's direction.";
  `<maintenance>` Volatile-state bullet — "the prior prose CLAUDE.md's ever-growing Active State
  chapters are retired; that history lives in the ledger, journal, and tickets, and the
  pre-2026-07-13 CLAUDE.md is in git history."; `<deferral_discipline>` — "momentum tickets have
  been reported to him as "handled" when they were same-day fixes not yet done." (the incident
  itself is the "Deferral momentum" row above). The two `<status_snapshot>` bullets were condensed
  with every retraction and every quoted predicate kept; their full text as it stood:
  "**INSTRUMENT-HONESTY ARC (#1241).** **`green_audit`, `oracle_mutation`, ruff STILL
  Python-only** (ceiling 12/15, derived), so #1385's "until web is on par" still cannot be met
  by running web. #1417 open. **`hard>=1` has fired ONCE ever, on Python (08-05) — that is
  row 4 bullet 1 + row 5's trigger.**" and "35B-A3B: **thinking gate RETRACTED 09-22** (our probe
  opened the block it measured; lesson 369). Not genai #4139. Brain switch DORMANT. New `agentic`
  suite (#1621/#1624, lessons 371-372). **Its 14B injection numbers are RETRACTED and ATTRIBUTED
  (#1622): the suite bypassed production's datamarking; a 24-cell split says the datamarked note
  is what stops all three, 3/3.** #930."
- **Doctrine in three layers; each rule has one home** — 2026-10-07 (#1700): CLAUDE.md sat at
  47,948 of 48,000 bytes and the #1668 point no longer fit after main moved. The LA asked whether
  moving content to an AGENT.md would help "or is that just moving bloat around" (it would: Claude
  Code does not read AGENT.md, and an `@` import loads at launch at the same cost), then directed
  the restructure executed with Andrew Stanish's design in mind
  (andrewstanish.com/projects/teaching-claude-to-code-like-me, read in full that night): an
  always-on core, `paths:`-scoped rules files, and a PreToolUse delivery hook, because he measured
  57 subagent file writes with 0 rule injections from native path-scoping alone, and a second
  bypass through shell writes 47 minutes after his first fix. His hook ends `|| true` (fails
  open); BlarAI's is fail-loud instead, per security principle 11. His "when a rule lives in two
  places, one of them is already wrong" is the source of the one-home rule and of the memory
  duplicate pass that followed.

## Format decisions (so they are not re-litigated)

- 2026-08-17 (#1442): the three agent files were converted from narrative prose to
  Markdown-directive form on researched evidence: Anthropic's shipped production agents use
  Markdown-sectioned imperatives (no XML sectioning in any body); XML is recommended for
  mixed content types (examples, embedded data), not for pure-instruction sectioning; history
  narratives in prompt bodies are a named anti-pattern, while reasons welded to rules are
  explicitly endorsed. Emphasis (MUST/IMPORTANT) is reserved for at most two load-bearing rules
  per file — density destroys the signal. `tools:` is deliberately omitted from all three
  frontmatters (inherit-all): an enumerated allowlist that omits a needed tool fails silently,
  looking like the task being impossible, and Bash would bypass a read-only allowlist anyway —
  instrument-forensics' read-only rule is doctrinal, with its reason attached.
- 2026-10-07 (#1700): path-scoped doctrine files hold ONE section each in CLAUDE.md's XML tag
  register, so the rules-corpus extractor splices them back in and every rule keeps its id when
  it moves between files. Frontmatter is a deliberately narrow YAML subset (double-quoted
  `paths`, single-quoted `x-blarai-*` regexes) checked by one parser shared with the delivery
  hook, because Claude Code silently loads a file with unparseable frontmatter in EVERY session.
  The delivery hook warns the model on failure and never blocks a tool call: blocking every Read
  would also block the repair.
- 2026-10-14 (#1765, #1741): the independent review of the NEP-0005 evidence write-up (unposted) found the study records a
  public snapshot would publish carried the host name (10 files), the operator account name (82 files) and
  the paths of the operator's credential stores with their access lists (5 records); 11 tracked files already
  named the host on the mirror. The question was put to the LA; his ruling was that it is never his question:
  a deterministic script removes the identifiers and a gate lock keeps them out, at the publish seam, every
  time. Hence `scripts/scrub_public_identifiers.py`, `tests/security/test_no_host_identity_in_tree.py`, the
  host-name line in the publisher's private leak-gate pattern file, and the performance.md rule.
  Round 3 of the review (same day) measured that 78 new files had carried the account name in 30 days, 38 of
  them under docs/reviews and docs/research where performance.md is never delivered; the two bullets moved to
  `.claude/rules/identity.md`, delivered on docs/reviews, docs/research, docs/adrs, docs/archive and docs/handoffs.
  Round 4 (same day) measured that the delivery list covered 46 of 67 new carrying files and that a partial clean left headroom a later branch could refill; identity.md is now delivered on docs, scripts, tools and tests, and a listed count that exceeds the file's own count is a finding (the count follows the file down).
