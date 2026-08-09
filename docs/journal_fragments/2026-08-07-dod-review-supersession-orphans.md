# Fragment — fold into BUILD_JOURNAL.md (lesson proposed, not numbered)

### 2026-08-07 — Supersession is where goals go to disappear

*Plain summary: reviewing the day-old coder Definition of Done found ten stale or drifted claims
and five of the operator's own goal clauses with no capability row — the largest lost not by
argument but by supersession, when the DoD replaced the overhaul programme as the target and
never picked up the programme's biggest gap.*

The Lead Architect asked whether the coder Definition of Done was missing elements, needed more
criteria, or contained errors. The document had merged about half an hour earlier (`e7628176`,
16:54 local), so I expected the review to be mostly about structure. It was not. Three
verification agents (code, config/state ledgers, board) re-measured its load-bearing claims the
same evening, and the board sweep alone found five of its cited tickets had closed that same
afternoon, 15:15–17:02 local — three of them in the half-hour AFTER the document merged —
capability 7's "open" residuals list was wrong within hours of the document merging, and
capability 6's headline still said "instructed" above a correction block proving the instruction
had been reverted. Ten fixes shipped in `6b8e55db`. None of the document's CONCLUSIONS failed
verification — every error was in citations, headlines and board-lag, which is the document's own
thesis about statuses demonstrated on itself.

The judgment worth keeping came from mapping the operator's two quoted goal statements clause by
clause against the rows. Five clauses had no row: requirement coverage, media content,
difficulty-scaled candidates, graded decomposition, verdict stability. The first is the one that
teaches. On 2026-07-30 the overhaul programme named "the exam covers what was asked" the single
largest gap against "proper exams" — every GREEN ever produced is `GREEN-UNVERIFIED`. The
traceability instrument then SHIPPED (`green_quality/traceability.py`), and the DoD — written the
same day, replacing the programme as the thing agents check work against — never picked the goal
up. Not rejected, not deferred: orphaned by supersession, while its tickets (#967, #1015) kept
floating with no numbered capability to serve. Proposed lesson: **when a new document supersedes
an old one as the target, sweep the old one's claims for orphans before retiring it — a goal that
misses the handover does not fail, it silently stops being anyone's job.** The five rows are
PROPOSED (17-21) and queued for ratification with a status legend and a machine-check plan on
#1325, because the second finding was structural: nothing scans this file — no size budget, no
vocabulary sweep, no status grammar — so it rots at whatever rate the board moves.

Two suspected errors dissolved under verification and are recorded as REJECTED in the disposition
record: the "#1277 fixed / none of it exists" tension is the ticket's own precise language, and
the add-then-revert commit chain is exact to the minute. Verify-before-critique cost three agents
about ten minutes and converted the review from opinion into measurement; the rejected findings
are as load-bearing as the confirmed ones. Trade-off taken: the proposed rows went INTO the
document marked NOT RATIFIED (following the 11-16 pattern) rather than living only in the report
— visible where the next agent reads, at the price of a longer unratified section the operator
must now clear. Disposition record: docs/reviews/coder-dod-review-disposition-2026-08-07.md,
22/22 PASS. A live B9 pottery-site battery run (20260807-174202-bd, the operator's own goal
shape) started mid-review; ledgers were snapshotted at 17:48 before its artifacts could move them.

**Next:** the LA reads the review and ratifies or strikes 11-21 (#1325); the status-grammar gate
test ships after ratification; #1326 clears the two prose-contradicts-wiring defects once no
dispatch is reading the config.
