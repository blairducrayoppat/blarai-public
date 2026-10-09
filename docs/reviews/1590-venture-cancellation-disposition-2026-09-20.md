---
title: "#1590 — a record correcting a misleading record, carrying a misleading claim of its own"
status: final
area: governance
---

# Disposition — #1590 (runtime-governance venture cancellation)

**Ten findings from an independent adversarial review of `3c3243a6`, every one reproduced against
the shipped tree. Three blocked the merge. The `DECISION_REGISTER.md` row the ticket was actually
about survived intact; the damage was in the two records I wrote around it.**

**The finding in one line: an ADR written to stop the decision register misleading future sessions
asserted a signing design that does not exist, justified by a measurement I had personally retired
forty-eight hours earlier on the very ticket that retired it.**

```disposition
# finding | status | evidence-or-predicate
BLOCKER 1 — THE ADR AND THE JOURNAL ASSERTED A SIGNING DESIGN BLARAI DOES NOT HAVE AND DECIDED AGAINST. Both claimed BlarAI's audit chain "is built in software with only the head signed", the journal going further with "that is what FORCED" it. The decision of record is the opposite: #1587 comment 3605 (LA 2026-09-18, shipped `bcb8313d`) reads "per-record TPM signing STAYS. The software-chain-with-chip-signed-head redesign is not built and not scheduled. Nothing merges dormant behind a flag for it either." Review reproduced the shipped behaviour by counting signer calls — 5 records appended, 5 `signer.sign()` calls — and traced `_build_audit_chain` selecting `TpmRecordSigner` when `dev_mode=False`. A future session reading ADR-042 as the signing record would have re-litigated a settled decision or built on a premise the code contradicts | FIXED | docs/1590-venture-cancellation — both instances deleted. The ADR and the journal now record what #1587 actually established: the appendix timed the signer DIRECTLY, the re-measurement on the SHIPPED path found the appendix pairing's software side wrong by 230x, and the redesign was DECLINED. The appendix is credited for provoking a measurement that overturned it, which is the honest reason to keep a probe record
BLOCKER 2 — THE FIGURE ITSELF WAS THE RETIRED INSTRUMENT. "~10-12 TPM signatures per second" is quoted accurately from appendix A4 seam 9 — and #1587's own description says of that probe: "Do not repeat the numbers above as a statement about BlarAI's latency, and do not design a fix from them." #1587 then superseded it on the shipped path: the quotable quantity is the DELTA, ~90-135 ms per adjudicated action, because the RATIO moves 213% across chain depth and is a property of how full the chain was, not of the system | FIXED | docs/1590-venture-cancellation — the figure is gone from the ADR, the register row and the journal. Where the appendix's TPM work is cited, it is cited as what PRODUCED #1587, with the correction named, not as a standing measurement
BLOCKER 3 — "SHIPPED 2026-09-19/20" WAS WRONG ON THE 09-19 ENDPOINT. Review reproduced with `git log -1 --format=%ad --date=iso` on all four SHAs: 46c44454 12:53, 336c620e 14:05, 7a03379f 14:56, 45a4da60 16:31 — every one 2026-09-20, and no 2026-09-19 commit on any of the four branches | FIXED | docs/1590-venture-cancellation — "on 2026-09-20" in both the ADR and the register row
FINDING 4 — "ALREADY IN BLARAI BEFORE THE VENTURE" WAS UNSUPPORTED FOR ALL THREE CAPABILITIES. Review reproduced: #1545 `4414d884`, #1544 `bdb0f11b`, #1542 `dc0b8623` all merged 2026-09-18 — the day AFTER the venture was founded (2026-09-17) and the day it was cancelled. The authoritative source, #1549 comment 3569, says only "capability already IN BlarAI", present tense. "Before" is prose I added that the source does not carry — the exact failure mode the review was briefed to hunt | FIXED | docs/1590-venture-cancellation — "Landed in BlarAI independently of the venture, all three on 2026-09-18" in the register, the ADR and the journal. "Independently" holds and is all the source supports
FINDING 5 — `docs/governance/auditability-card.md` HAS BEEN FALSE SINCE `dc0b8623`, AND MY NEW ROW CITED IT AS THE LIVE COVERAGE-DISCLOSURE SURFACE. The card merged at `bdb0f11b` 03:08 and #1542 merged at `dc0b8623` 05:16 the same morning — two hours later — and nothing re-opened it. It still said the AO tool loop and the egress door write "No" to the chain, that ingest was "the ONLY surface that writes receipts today", that "one chain is written, and every other surface decides without leaving a record", and that BlarAI "emits at ZERO of the eight intervention points". #1583 put that document on a screen in the app four days later. Not introduced by this change; surfaced by it | FIXED | docs/1590-venture-cancellation — ten corrections, each re-traced from code rather than from the ticket: `grep source_door=` returns exactly TWO production values (`ao_tool_dispatch`, `guarded_fetch_egress`), so rows 1 and 2 flip to Yes with their fail-closed/fail-loud asymmetry stated, the headline becomes two chains by three enforcement points with the remaining four named, and §2 becomes ONE intervention point (`pre_tool_call`, the only value any production site passes). The card's own forward-looking note predicted #1542 would change THREE rows; it changed two, and the output-validator row now says so. 46 card and disclosure tests pass
FINDING 6 — THE ADR ATTRIBUTED MY REASONING TO THE LA. "Option A — defer rather than cancel. Rejected, by the LA explicitly." Comment 3551 records the OUTCOME ("not deferred, not paused, no check-back date") and not an option he weighed; the argument against deferring — that the cooperative-seam finding is structural rather than a gap awaiting a release — is mine | FIXED | docs/1590-venture-cancellation — "Rejected. The LA recorded the outcome rather than weighing this option; the reasoning below is mine."
FINDING 7 — DECIDER ATTRIBUTION FOR THE SCOPING CORRECTION. The ADR said "the technical scoping correction is mine", while #1549 comment 3569 is signed "LA, 2026-09-18" and written in the first person about his own comment. The source does not record who initiated it | FIXED | docs/1590-venture-cancellation — the ADR now states where the correction is recorded and that who initiated it is not recorded, and claims nothing
FINDING 8 — THE REGISTER ROW POINTED AT THE WRONG TICKET. #1590's description says the appendices produced "#1587"; my row said "#1542's per-verdict cost". #1542 is the receipts ticket, #1587 the measurement ticket — a reader following the pointer lands somewhere else | FIXED | docs/1590-venture-cancellation — the row names #1587 and summarises what it found
FINDING 9 — TWO SPRINT DOCUMENTS STILL DATE THE CANCELLATION 2026-09-17. `sprint_19/kickoff-brief.md:77` and `trust-spine-gap-closure-brief-2026-09-17.md:4,178` say "scrapped by LA decision 2026-09-17", while I corrected `ACTIVE_SPRINT.md:41` from the same wording | REJECTED | The two are DATED 2026-09-17 documents describing 2026-09-17, and on that day the product track had indeed been scrapped by his decision; the formal venture cancellation came the next day. `ACTIVE_SPRINT.md` is different in kind and that is why it was corrected: it is the LIVE sprint pointer, read as current state, and `live_state_pointers` names it as such. Bannering dated briefs to match a later event would make them wrong about their own day. Neither asserts the venture is going ahead — verified by the review's own tree sweep
FINDING 10 — A COLLECTION COUNT REPORTED AS A MEASUREMENT. The journal's closing line said "main measures 11821", beside "recorded at 11777 / 0 / 0 / 133", which reads as a pass count. Review reproduced that 11821 is what `--collect-only` returns | FIXED | docs/1590-venture-cancellation — "main now COLLECTS 11821 — a collection count, not a pass count, until a quiet-box run says otherwise"
FINDING 11 — ADR-042 IS NOT IN THE REGISTER'S ADR INDEX TABLE | REJECTED | The table's rule is scoped to "a BlarAI runtime ADR that changes a trust/security behavior". ADR-042 changes none — it is a venture cancellation with no runtime footprint. It is indexed the way ADR-040 and ADR-041 were, as a dated Notes row carrying a link. The reviewer reached the same reading independently and raised it as INFO
```

## Verification

`tests/security/` (not hardware/winui/slow) at `3c3243a6`: **1473 passed / 2 failed** — the two
documented #1538 worktree-depth dead pointers in `ADR-013`, last modified 2026-07-03, untouched
here. Card and disclosure suites after the fixes: **46 passed**.

**Independently re-verified by the reviewer and not broken:** all four shipping SHAs and their
merge subjects; `50f7100d` as the study merge; the 47,720-byte CLAUDE.md figure (measured from
`git show fe865e12:CLAUDE.md`, raw and LF-normalised identical); ADR-042 as the next free number;
every study number quoted (86.4 ms, 37/37, 61.6% of 281, 8–14 h/week) against the study's own
lines; banner placement above the stale row with its text byte-identical to its parent; the
`BUILD_JOURNAL` banner under the correct one of two adjacent 2026-09-17 entries; uniform CRLF
across every edited file; 455 markdown links with zero new dead pointers; and a tree sweep
confirming **no tracked surface still asserts the venture is going ahead or that BlarAI is its
first shadow target**.

## The honest note

The register row — the thing the ticket was about — was clean and the reviewer could not break it.
Everything that failed was in the two records I wrapped around it, and all four factual errors ran
the same direction: prose that sounded established, asserting more than the source carried.
"Before the venture" for "already in BlarAI". "2026-09-19/20" for four commits on one afternoon.
"Rejected by the LA explicitly" for an option he never weighed. And a design that does not exist,
argued from a number whose retraction I wrote myself.

The pattern from the three reviews earlier in this sprint was *I test the thing behaving, the
reviewer tests the thing broken.* This one is its documentary twin: **I write what makes the
account cohere, the reviewer reads what the source actually says.** The register survived because
I had comment 3569 open beside it while writing. The ADR did not, because by then I was writing
from the story rather than from the ticket.
