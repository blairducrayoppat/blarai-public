# Execution brief — close the trust-spine gaps, #1541 to #1548

*Written 2026-09-17 at the close of the #1549 session. Main at `95c24f9e`, security tier
1072 / 0 / 1. The product track opened by #1549 is **scrapped** by LA decision the same day;
this brief is the work that continues.*

---

## What this is

Eight open tickets, all from the #1537 and #1540 research sets, all landed on the board
2026-09-16. They are the gaps between what BlarAI's trust spine **claims** and what it
**does**. Closing them is the upgrade the LA wants; it is not preparation for anything else.

**The ticket DESCRIPTION is the specification for each one.** Every ticket already carries
the defect class, the exact file and line of the surface that owns it, the design shape, the
regression locks, and its scope. Read the description, not the comment tail. Do not redesign
what the description already settles.

| # | What it closes | Shape |
|---|---|---|
| 1541 | Gap A — escalation approval binds to a tool name, not to the arguments that execute | Code + locks |
| 1542 | Gap B — the two live adjudication doors write no tamper-evident receipt, denials included | Code + locks |
| 1543 | Gap D — `AuditLog.verify()` has no production caller; a tampered chain would be extended, not refused | Code + locks |
| 1544 | Coverage disclosure for every execution surface, as an Auditability Card | Documentation |
| 1545 | Extend the Canonical Action Representation with the missing fields so the action hash means more | Code + locks |
| 1546 | A confidentiality axis on provenance so an egress sink can refuse deterministically | Code + locks |
| 1547 | Trace whether a denied turn can leave partial assistant text in the encrypted session store | Read-only trace |
| 1548 | Simulate-first as a fourth route outcome — **ACCEPTED by the LA 2026-09-17**, design settled on the ticket | Code + locks, merges DORMANT |

There is no Gap C ticket. Gap A, Gap B and Gap D are the three that survived triage.

---

## The order, and who owns it

> **CORRECTED 2026-09-17 at the sprint-19 kickoff, by the LA.** This section originally placed
> #1542 fourth and #1547 fifth. That was wrong, and #1548's description restates the same wrong
> order. The confirmed order is
> **`1543 → 1545 → 1541 → 1547 → 1542 → 1544 → 1546 → 1548`**; see item 4 below for the three
> surfaces that say so. Sprint brief: `docs/sprints/sprint_19/kickoff-brief.md`.

**`docs/ROADMAP.md` does not rank these.** Its order is the 2026-08-17 ranking and these
tickets postdate it, which the roadmap's own refresh note says explicitly: *"Nothing below was
re-ranked."* **Ranking is the LA's judgement.** The order below is a technical dependency
order derived from the tickets' own text, and he may reorder it at the gate.

1. **#1543 first, and it carries a stop condition.** Its own description requires verifying
   the real audit chains on this machine read-only *before* anything ships — *"if they do not
   verify today, that is a finding for the LA before anything ships."* Everything downstream
   writes into that chain, so find out first. Register the boot-path verification budget in
   `shared/timeout_registry.py` and **measure** the fast verify over the real active segment
   before choosing fast versus full at boot; the active segment holds up to 100,000 records
   and production signatures are hardware-backed.
2. **#1545 before #1541.** #1541 binds an approval to the CAR's `canonical_hash()`, and
   #1545 changes what the CAR contains. Building #1541 first means #1545 invalidates its
   regression fixtures and the binding has to be re-proved.
3. **#1541.** Bind the approval to the now-richer hash, re-derived immediately before
   `tools.execute`, fail-closed on mismatch.
4. **#1547.** Read-only trace, and it runs **before** #1542, not after.
   `docs/research/acs-vocabulary-adoption-design-2026-09-16.md:123` is explicit: *"Item 3 is a
   separate read-only session and should run first, because its answer might add a field to
   item 1"* — item 3 is this trace, item 1 is #1542's receipts. #1547's own description carries
   the heading *"Why it comes before #1542"*. Running it second risks adding a field to a
   shipped receipt schema and reopening the canonical-bytes question, which is the most
   expensive stop condition on this list. Cheap, independent, and its finding also feeds #1544.
5. **#1542.** Receipts at both doors — into a chain that #1543 has made worth writing into,
   with a field set that #1547 has finished settling.
   Trace first whether the new fields change the canonical bytes of existing ingest records
   and therefore `verify()` over old segments; that question is in the ticket and is not
   optional.
6. **#1544.** The coverage disclosure, which needs #1547's trace and can then state honestly
   what #1541 to #1543 changed. The coder-fleet dispatch path's interception depth has never
   been traced and is asserted nowhere — that is the row most likely to produce a surprise.
7. **#1546.** Confidentiality labels on provenance.
8. **#1548 last.** The capability decision was taken 2026-09-17 — **accepted**, against a
   recommendation to decline. It is now a build item and its DESCRIPTION carries the settled
   design; do not re-open it. It goes last because it changes
   `DeterministicPolicyChecker.check`, the escalation path and the receipt schema — the same
   surfaces #1541, #1542 and #1545 rewrite. **It merges DORMANT behind a config flag** and
   goes live only at an LA-present ceremony. Deny-by-default per tool, zero tools declaring a
   dry run at merge, and `web_search` barred by a lock with its toggle-test, because a dry run
   of the only egress tool performs the egress it is meant to gate.

---

## After the eight: two new tools, approved 2026-09-17

Both are capability changes, both approved by the LA, both **merge DORMANT** and go live only at
a ceremony with him present. They are a **separate arc** — they do not displace the eight and
they are not started until the eight are closed.

| # | Tool | Why it exists |
|---|---|---|
| 1567 | `curate_knowledge(query, action)` | Query-based curation of the knowledge bank. The only action in BlarAI whose effect is **both irreversible and not already described by its arguments** — `secure_delete=ON` zeroes the rows, and the argument is a selector while the effect is a set. **The first tool to declare the dry run #1548 adds.** |
| 1568 | `organise_userdata(pattern, destination)` | Pattern-based file moves inside the operator's own data directory. The assistant has **no file surface today**, so this adds a capability class rather than extending one — the larger and more dangerous of the two. |

**Order: 1567 before 1568.** `curate_knowledge` extends machinery that exists (the bank already
has delete paths and the secure-delete pragma) and is what makes #1548 real; `organise_userdata`
opens the first file surface and its whole threat model is the path-escape check.

**The rule both are built to, and the reason they were the two chosen:** a tool earns a dry run
when its argument is a **selector** rather than a **target**. `delete_image(id)` needs no
simulation — the argument is the effect. `forget(query)` does, because nobody can compute the
match set in their head. Any future tool should be tested against that line before it is given
the capability.

**Deliberately not approved: an outbound tool** (email, message, post). Irreversible and useful,
but it is egress — a new scope, a new ceremony, a new lock set — and a dry run there is the
approval prompt wearing a different name, the same trap that bars `web_search` from
simulate-first.

---

## Ground on disk before the gate

`CLAUDE.md` · `git log --oneline main` + `git status` · Vikunja `project_summary` ·
`docs/sprints/ACTIVE_SPRINT.md` · `docs/TEST_GOVERNANCE.md` §1 · `docs/ROADMAP.md` ·
each ticket's DESCRIPTION · `docs/governance/trust-spine-claim-register.md` (rows 27, 28 and
29 cite gaps A, B and D) · `docs/research/acs-vocabulary-adoption-design-2026-09-16.md` (the
design the tickets cite by section) · `docs/research/trust-spine-proposed-items-index.md`.

Two tickets require reading an **external source before design**, and neither is optional:
#1543 needs Dapr's `workflow-history-signing` implementation read, not its documentation,
because the survey it came from is documentation-level; #1544 needs the Auditable Agents card
definition. Documentation is not evidence — read the artefact and record which artefacts were
read.

---

## Standing rules that bind this work

- **Gate once, briefly, then run the whole arc.** The points and the line ceiling are
  `CLAUDE.md` `<comprehension_gate>`'s, not restated here. After
  confirmation, execute build → test → commit on a feature branch → merge → ticket closed
  citing the SHA → journal, without further permission-seeking.
- **Redirect `LOCALAPPDATA` before every pytest run.** An unredirected run has corrupted the
  real `sessions.db`.
- **Gate green on the branch before merge, and re-run on merged main after.** Read the exit
  code, not the word GREEN — a pipeline's status is the last command's, and
  `pytest … | tail -3` exits 0 on red.
- **No destructive git. No `git add -A`. Feature branches only.** Verify
  `git branch --show-current` before every commit in the primary checkout.
- **Author is not verifier.** Independent adversarial review before each merge; the reviewer
  never writes the fix. Findings get a disposition record under `docs/reviews/` and
  `scripts/verify_disposition.py` passes before the work is reported done.
- **Every control ships both tests** — one proving it blocks, one proving the probe fails when
  the control is switched off.
- **Every measurement is recorded when it runs**, in `PERFORMANCE_LOG.md` and
  `docs/performance/`, with its conditions and what was *not* measured.
- **Journal fragments to `docs/journal_fragments/`**, one per entry, lessons proposed and never
  pre-numbered. Lessons are minted to 368; 344–348 are reserved.
- **Anything that changes what BlarAI can do merges DORMANT** behind a flag and waits for an
  LA ceremony. Seven of these eight are hardening within an approved capability and ship LIVE;
  #1548 is the exception: it changes what the assistant can do, so it merges DORMANT and
  waits for his ceremony.

---

## Stop conditions — return to the LA before finishing

- **#1543:** the real audit chains on this machine do not verify today. That is a finding, not
  a bug to fix quietly.
- **#1542:** adding receipt fields changes the canonical bytes of existing records and breaks
  `verify()` over old segments. That is a migration decision, not an implementation detail.
- **#1547:** a denied turn does leave partial assistant text in the encrypted store. That is a
  privacy posture finding.
- **#1544:** a surface turns out to be observer-only that nobody had said was observer-only.
- **#1548:** a preview for `generate_image` cannot be produced without evicting the resident
  14B. Then the ticket ships with zero declaring tools — that is the designed outcome, not a
  failure, and it is worth telling him.
- Two failed fixes on the same defect: bank the dead end on the ticket and put fresh context
  on it.

---

## Out of scope

`C:\Users\mrbla\governator` — the product track from #1549 is scrapped by LA decision
2026-09-17. The repository still exists with the founding study and sixteen tickets on Vikunja
project 14; **do not work in it, do not delete it, and do not carry anything out of it.** Its
disposition is the LA's.

**#1566** (`CLAUDE.md` consolidation, then the constellation pointer) is open and unrelated.
`CLAUDE.md` has 369 bytes of headroom against its 48,000-byte budget; a load-bearing addition
will hit that wall.

The **August journal rotation and its monthly retrospective** are outstanding — the hot
`BUILD_JOURNAL.md` carries both August and September.
