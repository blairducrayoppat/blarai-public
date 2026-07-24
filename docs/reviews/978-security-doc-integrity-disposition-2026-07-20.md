---
title: "#978 security-doc-integrity — findings disposition"
status: closed
area: security
date: 2026-07-20
---

# #978 security-doc-integrity — findings disposition

Disposition of every finding from the independent review of the #978 pair
(`docs/978-security-doc-integrity` + `feat/978-doc-integrity-gate`), plus the
findings I raised myself before and after the merge.

**This record exists because of how the first pass went.** Three of these were
fixed immediately and two were filed as tickets — and I then reported to the
Lead Architect that the surfaces were handled. They were not. Neither deferral
had a reason that would survive being asked *"what concrete failure does the
delay prevent?"*; the change had merged and the box felt closed. Both are now
fixed, and `scripts/verify_disposition.py` exists so the next deferral has to
answer that question in a form a machine can refuse.

```disposition
# finding                                  | status   | evidence / blocked-by
gate false positive on principle 2         | FIXED    | 06636953, merged 38b5ca9a
CLAUDE.md 'welded by 3+ unrelated locks'   | FIXED    | c731b369, merged 809e3454
status_snapshot 'three locks' fetch limb   | FIXED    | c731b369, merged 809e3454
entrypoint.py false boot-time warning      | FIXED    | c731b369, merged 809e3454
ADR-012 inverted on the shipped draft      | FIXED    | f4211acc, merged e1cf0d68
web_search runbook: no EXECUTED banner     | FIXED    | f4211acc, merged e1cf0d68
web_search runbook: stale gov-pf-007 pin   | FIXED    | f4211acc, merged e1cf0d68
ADR-039 'no live module imports'           | FIXED    | 8b14cd83, merged bd28afde
image_generation 'UNUSED today' wording    | FIXED    | 8b14cd83, merged bd28afde
probe 2 passes vacuously once corrected    | DEFERRED | #990 blocked-by: needs a generative check, not a phrase list; scope depends on whether #977 ships an executable boot-time posture check
probe 3 is case-sensitive (DORMANT only)   | DEFERRED | #990 blocked-by: `tests/security/test_doctrine_freshness.py` probe 3 needs IGNORECASE plus a dated-annotation requirement, landing with the #977 posture work
no probe for composite 'N locks' claims    | REJECTED | deliberate and correctly reasoned in the module docstring — such claims depend on registration order and lock independence, so a lint asserting coverage would itself be a control claiming coverage it lacks; belongs to #977's executable check or human review
posture pin fails as ModuleNotFoundError   | DEFERRED | #990 blocked-by: needs an import guard in `tests/security/test_doctrine_freshness.py` so a missing dependency reports as an environment fault rather than a posture finding
```

## Notes on the two that were wrongly deferred

**ADR-012** and the **web_search runbook** were filed as #988 and #990 rather
than fixed. Neither needed a decision. ADR-012 asserted the opposite of what
ships in three separate places while carrying an amendment two lines below
reversing it; the runbook had no EXECUTED banner at all, so an operator working
through it would have re-run a live go-live from 2026-07-02. Both were fixed
the same day once the Lead Architect asked whether they actually had been.

The three rows still marked DEFERRED above are genuinely blocked: each names a
change that belongs with #977's posture work rather than a preference to do it
later. That is the distinction this record is meant to force.

## The limit of the control, stated

`verify_disposition.py` checks the FORM of a disposition once one exists. It
cannot detect a review whose findings were never written down. That gap is
closed by doctrine and the ship motion, not by the script — and saying so here
matters, because a control that overstates its coverage is the exact defect
class #978 was raised to fix.
