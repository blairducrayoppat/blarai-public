---
title: A confidentiality axis on provenance — design note
status: design-only
area: security
---

# A confidentiality axis on provenance: why the obvious design fails, and what must be settled first

*Written 2026-09-17 under #1546, sprint 19. **Design only; nothing is built.** Rewritten the same
day after independent review refuted the first draft's central claim. The first draft is preserved
in this branch's history and its findings are in
[`docs/reviews/1546-confidentiality-axis-disposition-2026-09-17.md`](../reviews/1546-confidentiality-axis-disposition-2026-09-17.md).*

## Outcome first

**The obvious design does not work, and the reason is architectural rather than fixable in the
algebra.** A label-based confidentiality axis with most-restrictive-wins propagation makes
`web_search` unrunnable in any session containing operator data — which is every session after a
turn or two. That is not a tuning problem. It follows from BlarAI having **one model that reads
everything**.

So this note does not propose an implementation. It records three facts that any future attempt
must start from, and names the one question that has to be answered before a design is possible.

## Three facts, each verified against the running system

**1. A confidentiality axis already exists, and this note's first draft missed it.**
`shared/schemas/car.py` defines `Sensitivity` — `PUBLIC` / `INTERNAL` / `SENSITIVE` /
`UNCLASSIFIED` — as a **required** field on every CAR, with no default, routed on fail-closed by
the rule engine. Any future work starts by extending or replacing that, never by inventing a
parallel vocabulary beside it. (Its live status is qualified: the CAR/rule-engine path is recorded
elsewhere as unreachable in production, which is a separate problem and not a licence to ignore the
field.)

**2. The exfil screen does NOT hold knowledge-bank content.** Measured, with controls:

```
BLOCKED  | an email address
BLOCKED  | an AWS key
ALLOWED  | "Project Ravenhold ships 2027-03. Budget 4.1M EUR."
ALLOWED  | a private medical note
ALLOWED  | an operator legal matter
```

The screen matches secret- and PII-**shaped spans**. Ordinary operator prose passes it untouched.
The common belief that "the exfil screen plus one egress scope hold this today" is **false**, and
the first draft of this note repeated it as its premise for deferring the work.

**3. The Layer-3 lock does not govern the egress tool.** ADR-023 Amendment 4 **exempts** egress
tools from the untrusted-content lock — `entrypoint.py:6996`, `and not tools.is_egress_tool(...)`.
That carve-out was spent deliberately to make `web_search` usable with the knowledge bank on. Any
design that re-locks that path undoes a decision someone made on purpose.

## Why the obvious design fails

Most-restrictive-wins is the only propagation rule that is safe under composition — anything weaker
lets a join launder a label. Combine it with a safe default (unlabelled content is operator-owned,
never public) and follow it honestly:

- Every session acquires operator-derived content within a turn or two.
- Therefore every context is operator-level.
- `web_search` would accept public-level only.
- Therefore search never runs.

**The first draft claimed this is escaped by labelling a narrower unit — the query rather than the
context. It is not.** The query is *emitted by the 14B from that same context*, so it inherits the
restrictive label by the identical join. The collapse moves one step and survives.

CaMeL — the academic form of this design — escapes it by using a **quarantined** model that never
sees privileged data, so the query it produces genuinely carries no label from the operator's
content. **BlarAI has one model reading everything.** That single architectural fact is what
decides whether any of this is buildable.

## The question that must be answered first

> **Can BlarAI have a query-generation path that never sees operator data?**

If **yes** — a small quarantined pass that turns the user's question into search terms without the
grounded context — then a label algebra becomes possible, and the design work is real.

If **no** — because a query written without context would be too poor to be useful, which is a
quality judgement and the Lead Architect's — then **label-based egress control is not available to
BlarAI at all**, and the honest response is to say so and invest in the alternatives: keeping the
egress surface narrow, keeping the fingerprint envelope as the consent, and improving the exfil
screen's coverage now that its real limits are measured.

Either answer is useful. What is not useful is a design note that assumes the first without asking.

## What this note deliberately does not contain

No lattice, no propagation rules, no sequencing plan. The first draft had all three and they were
built on a refuted premise; shipping them would hand the next implementer a design that cannot
work. The disposition record carries what they were and why they failed, which is the part worth
keeping.

## Honest limits

- **FIDES is documentation-level** here — Microsoft's documentation and Costa et al. 2025, not
  Agent Framework's source. **CaMeL's repository was not read.** By this project's own standard the
  prior art is *described*, not *verified*, and the quarantine claim above rests on that
  description. Reading one of the two as source is the first step of any follow-up.
- **No refusal rate has been measured**, and none can be until the labelled unit is decided — which
  is downstream of the quarantine question.
- The three measured facts above were established this session; the conclusion drawn from them was
  not, and was wrong the first time. That is the reason this note now states facts and a question
  rather than a design.
