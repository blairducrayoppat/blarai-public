# Trust-spine proposed items: the one list

*Living index, first written 2026-09-17. The [PROPOSED] items that the 2026-09-16 research set and the landscape compilation raised against BlarAI's trust spine were numbered across three documents and had no single home; this file is that home. It carries pointers only: what each item is, which document raised it, and which Vikunja ticket owns it. Status (open, doing, done, declined) lives on the ticket, never here, so this list cannot go stale the way a status table does. Add a row when an item is added; nothing here needs editing when a ticket closes.*

## How to read the list

- **Item** numbers are the ones the documents use. They are permanent; a withdrawn item keeps its number and says so.
- **Class** is what kind of work the item is under the decision boundary: *hardening* (within an already-approved capability, a session's to build once ordered), *test* (a regression lock on a property BlarAI already has), *docs* (a document), *investigation* (read-only), *LA decision* (changes what BlarAI can do or its posture; the operator's call), *landed* (already on `main`, with the commit).
- **Origin** names the document and section that raised the item; that text is the item's full statement.
- **Home** is the Vikunja ticket that owns the item's queue entry; two items live as comments on the ticket whose work they refine.

Every item here is approved for the list by the operator: items 12 to 15 on 2026-09-17, items 4, 5, 6 and 11 by the direction to ticket them the same day, and items 1 to 3 and 8 to 9 by the tickets that already held them. Approval for the list is not an order to build: none is started unless its Home says otherwise. The order in which the hardening items are built is the operator's, ranked against `docs/ROADMAP.md`; this list ranks nothing.

## The list

| Item | What it is, in one line | Class | Origin | Home |
|---|---|---|---|---|
| 1 | Wire the two live doors (tool dispatch, egress door) to the signed audit log so every verdict writes a chained, signed receipt (Gap B) | hardening | `cava-vs-microsoft-agent-framework-vs-blarai-trust-spine-2026-09-16.md`, "[PROPOSED] next steps" | #1542 |
| 2 | Bind an escalation approval to the CAR's canonical hash, re-derived before execution, consumed once (Gap A) | hardening | same, item 2 | #1541 |
| 3 | An executable boot-time posture check that the registered door adjudicator serves every live egress posture (Gap C) | hardening; LA security-posture item per the ticket | same, item 3 | #977 (open since 2026-07-19) |
| 4 | Extend the CAR with CAVA's missing fields (category, systems touched, reversibility, target) so the hash means more | hardening, design first | same, item 4 | #1545 |
| 5 | A confidentiality axis on provenance, FIDES-style, so knowledge-bank content carries a label an egress sink can refuse | hardening, design first; activation of the deny rule is the LA's | same, item 5 | #1546 |
| 6 | Trace whether a turn denied mid-stream leaves partial assistant text in the encrypted session store | investigation | same, item 6 | #1547 |
| 7 | A trust-spine claim register, CAVA-shaped | landed: `docs/governance/trust-spine-claim-register.md`, merged `74fe0b48` (2026-09-16) | same, item 7 | #1539 (closed; shown on the board as identifier #473) |
| 8 | Close denials and escalations into the signed audit log, not only allows (PCAA's non-execution proof) | hardening | `pcaa-placement-and-blarai-mapping-2026-09-16.md`, "[PROPOSED] additions", item 8 | #1542 (covered by its description) |
| 9 | Attach decision basis to each record: exfil-screen labels, provenance set, risk tier, config hash (PCAA's `recordAssumption`) | hardening | same, item 9 | #1542 (the receipt's `basis` object) |
| 10 | Write the coverage-disclosure table for BlarAI's execution surfaces (tool loop, egress door, coder-fleet dispatch, vsock services) with each surface's interception depth | docs | same, item 10 | #1544 (merged with item 15) |
| 11 | `simulate-first` as a route outcome: a dry run before a gated execution | LA decision (a capability change) | same, item 11 | #1548 |
| 12 | Verify the audit chain on load and fail loud on tamper (Gap D): `AuditLog.verify()` has no production caller and the load path restores the chain head unverified | hardening; the LA has said it ships live, not dormant, when ordered | `runtime-action-governance-landscape-2026-09-16.md`, "[PROPOSED] additions", item 12 | #1543 (claim register row 29) |
| 13 | A `decision_source` field on the receipt (`rule`, `layer3_lock`, `envelope_lease`, `verifier`, `no_verifier`, `operator_abort`) | hardening; a refinement of item 1's receipt | same, item 13 | comment 3448 on #1542 |
| 14 | A regression lock that approval text inside untrusted context never lifts an escalation | test | same, item 14 | comment 3447 on #1541 |
| 15 | Shape the coverage-disclosure table as an Auditability Card (six questions: actions recorded, phases covered, checkable policies, responsibility chain, integrity protection, behaviour when logs are missing) | docs | same, item 15 | #1544 |

## Where the four gaps are, since the letters are used everywhere

| Gap | Statement | Ticket | Claim register row |
|---|---|---|---|
| A | An escalation approval binds a tool name and rule label, not the exact action | #1541 | 27 |
| B | The two live doors write log lines, not signed receipts | #1542 | 28 |
| C | The two egress layers agree only while one adjudicator holds the door slot; checked once at boot | #977 | 3 |
| D | The audit chain's own verifier is never invoked on the live path | #1543 | 29 |

## How the count moved, so nobody re-derives it

The comparison document (2026-09-16 morning) listed items 1 to 7 and the PCAA document items 8 to 11; #1537's description called that "twelve". The independent review applied at `9eb14932` changed the comparison document's framing to "eleven" and marked item 7 landed. The landscape compilation (#1540, merged `da805572`) added items 12 to 15. On 2026-09-17 the operator approved items 12 to 15 as additions to the list and directed that items 4, 5, 6 and 11 get tickets; #1545 to #1548 were opened and this index was written. The same day the operator approved the six tickets #1543 to #1548 as list items and the [PROPOSED] marker came off their titles, with none started; #1548 keeps its [LA DECISION] marker because the capability question it carries is still open. Fifteen items, one landed, one waiting on the operator's decision, thirteen open.

## Sources

- `docs/research/cava-vs-microsoft-agent-framework-vs-blarai-trust-spine-2026-09-16.md` (items 1 to 7).
- `docs/research/pcaa-placement-and-blarai-mapping-2026-09-16.md` (items 8 to 11).
- `docs/research/acs-vocabulary-adoption-design-2026-09-16.md` (items 1, 2, 6, 8 and 9 restated in the Agent Control Specification's vocabulary).
- `docs/research/runtime-action-governance-landscape-2026-09-16.md` (items 12 to 15, the rejected list, and the field's state on each of the five questions).
- `docs/governance/trust-spine-claim-register.md` (rows 3, 27, 28, 29).
- Vikunja #977, #1537, #1539, #1540, #1541, #1542, #1543, #1544, #1545, #1546, #1547, #1548.
