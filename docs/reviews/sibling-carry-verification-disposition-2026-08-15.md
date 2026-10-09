# Disposition — independent verification of the 2026-08-14/15 ten-ticket pass

**Pass:** an independent reviewer (author ≠ verifier; it did not write any of the fixes) checked
every DONE-list item of #1389 #1390 #1391 #1393 #1394 #1395 #1396 #1397 #1399 #1400 against
merged main (BlarAI `739d2163`, agentic-setup `267348f`), on disk, with `file:line` evidence.

**Outcome:** six complete and closed — #1389 #1393 #1394 #1396 #1397 #1399. Three incomplete.
#1390 was already open on an LA decision and is unaffected by this pass.

**The finding behind the findings.** All three incomplete tickets fail the same way: the fix
landed in `security.py` and the ticket's own explicit *"in the same change"* requirement for
`placeholder_prose.py` was not carried through. That is lesson 342's predicate — *run it over
every sibling before the commit lands* — failing three times in one review pass, by the session
that wrote the lesson. Writing the structural control then surfaced a fourth instance. Four is
not a memory problem, so the disposal is a gate test, not a tally.

```disposition
# finding | status | evidence-or-predicate
ticket #1391 item 3 — a SECOND reachable path (asset_ran=True, item_ran=False) still asserted "no data file listing items with pictures was found" when a catalogue was found and failed to parse | FIXED | 4a9fd1c5 — image_placement.py:976 now names the parse failure; toggle test proves the absent-file wording SURVIVES when there genuinely is no catalogue, and a toggle-off probe confirmed the new test fails against the old text
ticket #1395 item 3 — placeholder_prose.py's 256 KiB read slice is a real bound on what was examined and was disclosed nowhere — no counter, no status sentence, no coverage_partial contribution | FIXED | 4a9fd1c5 — counted as truncated_reads, named in status, added to coverage_partial, matching its security sibling; paired toggle proves a page that fits is not reported as truncated
ticket #1400 item 1 — placeholder_prose.py built its summary whole and sliced it to EVIDENCE_VALUE_CAP, so a long rule list lost its tail silently | FIXED | 4a9fd1c5 — extracted to constants.clip_rule_list and used by BOTH scanners rather than copied a second time; test asserts kept + dropped reconciles to the population
ticket #1400 item 2 — placeholder_prose.py inferred cap-hit from `scanned >= _MAX_FILES`, which cannot tell a truncated walk from a tree holding exactly that many | FIXED | 4a9fd1c5 — _iter_web_files yields one past the bound; test pair covers exactly-at-cap (must NOT claim partial) and one-past-cap (must)
FOURTH INSTANCE, found by writing the control: prose could break out at _MAX_HIGH_FINDINGS leaving files unread while publishing complete coverage — it recorded only `truncated`, which means the finding LIST was abbreviated and is deliberately not a coverage signal | FIXED | 4a9fd1c5 — walk_abandoned added, named in status, in coverage_partial; matches security.py since 514c6362
the carry-through failure itself, three times in one pass, after a lesson was written about exactly it | FIXED | 4a9fd1c5 — tests/security/test_sibling_scanner_parity.py: AST-extracts each scanner's coverage_partial disjuncts, maps them to CONCEPTS so unparsed_python vs unparsed is not a false positive, and requires every concept on both sides or listed in DECLARED_ASYMMETRIES with a reason. Toggle-proved: removing truncated_reads from prose fails it naming the exact missing concept and the sibling missing it
a sub-agent reported #1389's fix commit as "not yet merged" | REJECTED | stale commit-message text, not current reality. The lead verifier re-checked with `git merge-base --is-ancestor 217f32e9 HEAD` → true. Recorded because an unchallenged "not merged" would have reopened a correctly-closed ticket
ticket #1390 items 2 and 4 remain unbuilt | DEFERRED | #1390 blocked-by: a recorded LA verdict on ticket #1390 choosing between fail-closed (an unscannable first-party .py becomes a finding, which parks builds) and disclose-only. Observable as a comment on #1390; the cost is already measured there — 1,044 first-party .py across every archived delivery, ZERO over 512 KiB, largest 12,693 bytes
```

## This pass discharges the previous record's deferrals

`docs/reviews/1396-fix-disposition-2026-08-15.md` deferred five rows — three to #1400, one to
#1397, one to #1399 — each with `blocked-by: the 2026-08-14 23:00 battery run completing, or
being confirmed not to have run`. **That predicate is now satisfied**: the battery ran and
completed (`20260814-230237-bd`, 23:07 → 03:49, six waves). #1397 and #1399 were verified
complete and closed; #1400's three rows are the FIXED rows above. No deferral from that record
remains open, which is the property a `blocked-by:` predicate exists to make checkable — it named
an event a later session could observe, and a later session observed it.

## What the control does NOT cover, stated so nobody reads it as wider than it is

It compares the two **bounded scanners'** `coverage_partial` expressions. It does not check
`layer1.py`'s craft lints (which carry their own per-finding `coverage_partial`), it does not
verify that a disclosed shortfall is *accurate*, and it cannot see a bound that neither scanner
discloses at all — a bound invisible to both is invisible to it. It catches divergence, which is
the failure that actually happened four times, not incompleteness in general.
