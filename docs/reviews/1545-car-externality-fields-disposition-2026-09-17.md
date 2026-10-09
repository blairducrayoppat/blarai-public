---
title: "#1545 CAR externality fields — adversarial review disposition"
status: final
area: security
---

# Disposition — #1545 (category, systems touched, reversibility, target in the action hash)

**Review run 2026-09-17, pre-merge, by an agent that did not write the code.** Target commit
`4d59bbef` (code blob `327bae00`, unchanged at review HEAD `ea139806`). Fixes landed in `19174571`.

**The shape of this one is the inverse of #1543's.** There the behaviour was broken and the tests
said otherwise. Here **the behaviour is correct and the reviewer could not break it** — 93 subsets
of eight system names produced 93 distinct hashes with zero collisions, every field is genuinely in
the hash, the pydantic surface rejects strings, dicts, None and bad enum values, and the
audit-chain compatibility claim verified independently. What failed was the *locks*, and a commit
message that upgraded a hopeful sentence into a property the suite did not have.

```disposition
# finding | status | evidence-or-predicate
review finding 1 (MEDIUM-HIGH, blocking) — the commit message claimed the parametrised test meant "a fifth field added without hashing it fails immediately". FALSE: the parametrize list is hand-maintained and nothing introspects model_fields, so whoever forgets to hash a new field is whoever would have to remember to add its row. Reviewer added a fifth field, left it out of canonical_hash(), and all 12 tests passed | FIXED | 19174571 — canonical_hash() now builds its mapping in _hashable_payload(); TestEveryModelFieldIsHashedOrExplicitlyVolatile compares that key set against model_fields minus a declared VOLATILE_FIELDS frozenset, so the MODEL is the source of truth. Two companion locks added: no hashed key without a backing field (catches a rename leaving a stale key) and VOLATILE_FIELDS must name real fields (or the exclusion list rots into strings that exclude nothing and the main lock passes vacuously). Mutation-verified: re-running the reviewer's fifth-field mutant now FAILS test_hash_covers_every_non_volatile_field
review finding 2 (MEDIUM) — the over-normalisation toggle used sets differing in BOTH length and alphabetically-first element, leaving the two most destructive weakenings undetected. Reviewer ran six normalisation mutants: nodedup and nosort were caught; casefold, stripchars, firstonly and countonly all passed 12/12. Under countonly, systems_touched=("network",) and ("filesystem",) hash IDENTICALLY, so an approval for a local knowledge read would cover a network egress and #1541's re-derivation would match | FIXED | 19174571 — added same-cardinality fixtures at one member (knowledge_bank vs network) and two members (sharing their alphabetically-first element, which defeats firstonly), plus near-miss names knowledge_bank/knowledgebank and network/NETWORK to catch case-folding and punctuation-stripping. Mutation-verified: countonly, firstonly and casefold now each FAIL
review finding 6 (LOW) — the "UNKNOWN is not an alias for a permissive value" lock enumerated COMPUTE and EGRESS by hand, 2 of 5 non-UNKNOWN members, and let UNKNOWN = "RETRIEVE" through | FIXED | 19174571 — and the obvious repair was itself insufficient, which is recorded because it is the interesting part: comparing against a set comprehension over the enum ALSO lets the mutant through, because `UNKNOWN = "RETRIEVE"` makes RETRIEVE an ALIAS member and Python skips aliases when iterating an Enum, so the derived set never contains the aliased value. Now pins the exact name-to-value mapping for both enums plus the member counts. Mutation-verified: the alias mutant now FAILS
review finding 3 (LOW-MEDIUM) — the class docstring still read "All fields are required. Missing fields cause Fail-Closed rejection" while four of thirteen fields are optional with UNKNOWN defaults and absent from is_complete(). Inherited staleness (last touched in 650f0363) that this commit made materially more false, in a security register, against CLAUDE.md's coding-standards rule that docstrings state contracts | FIXED | 19174571 — rewritten to state BOTH classes of field: identity fields required and enforced by is_complete(), externality fields optional by deliberate choice, with the cost named in the place a reader of the model meets first rather than only in the field comments
review finding 4 (LOW-MEDIUM) — `target`'s docstring claimed `resource` "names the KIND" while `target` carries the instance. The one production site that builds an egress CAR (services/ui_gateway/src/url_adjudicator.py:88-96) puts the full URL in `resource` and leaves `target` empty; the AO dispatch path does the same with KAGI_SEARCH_ENDPOINT. The docstring described neither the code nor the project's own measured vocabulary screen | FIXED | 19174571 — claim withdrawn and replaced with an explicit precedence note: `resource` IS the destination today, including for egress. Whether `target` ever takes that role is deferred to #1541 BY NAME rather than left ambiguous, because #1541 is what shows an operator the thing being approved and showing them two destination-shaped fields is worse than showing them one
review finding 7b (LOW) — the module docstring restated CAVA's required set as three fields (category, systems_touched, reversible); the project's own MEASURED record of schema.js says five, adding runtime and operation. A restatement of a read artifact that quietly shortens it is the shape that gets cited later as if it were the schema | FIXED | 19174571 — corrected to five, with the sentence the original silently assumed: runtime and operation are already covered by source_agent/destination_service and verb
review finding 7a (LOW) — "5605 passed" in the commit message is exactly right and carries none of its conditions; the same run was 2 failed, 5605 passed, 3 skipped, 27 deselected, in a non-elevated worktree | FIXED | 19174571 — the replacement commit message states the count WITH its conditions (the 2 known ADR-013 worktree artifacts, the 3 documented symlink skips, non-elevated, worktree), because a number without its conditions is not a measurement and a commit message becomes the record
review finding 5 (LOW) — model_config is empty so pydantic's extra="ignore" applies: a misspelled field is silently dropped at construction and produces a CAR whose hash is bit-identical to one never classified at all, and an older sender's omitted fields validate cleanly across the real IPC parse paths. Fail-closed downstream via the stage-5 car_hash comparison (jwt_validator.py:366), so a denial rather than a bypass — but a denial with no diagnosable cause | DEFERRED | #1572 blocked-by: #1545 merged. Observable: `grep -n "VOLATILE_FIELDS" shared/schemas/car.py` returns a hit on merged main. extra="forbid" is a MODEL-WIDE posture change — every construction site, test fixture and IPC sender must be conformant or boot fails — and deserves its own gate run and blast-radius check rather than being smuggled into a schema ticket. The reviewer's own merge read said the same
reviewer's observation — canonical_hash() has ZERO production callers; its one caller (services/policy_agent/src/adjudicator.py:493) sits in HybridAdjudicator, whose sole non-test instantiation is a gate script. The change is inert at runtime today | REJECTED | Not a defect and explicitly not the #1543 pattern, which is what the reviewer was sent to look for. #1543's first version CLAIMED to ship a live control while running nowhere in production; this commit says plainly "Not done here: nothing populates the new fields yet" and the ticket is schema work sequenced BEFORE #1541 precisely so the hash is final when approvals start binding to it. Inert-and-says-so is a different thing from inert-and-claims-otherwise. ADR-041 already records the hybrid adjudicator as vestigial and slated for removal under #910
```

## What the reviewer attacked and could not break

Recorded in full because a null result from an adversarial pass is evidence, and because it is most
of this review's result.

- **All four fields are genuinely hashed.** Each dropped from the payload in turn: `category`,
  `reversible`, `target` → 1 failure each; `systems_touched` → 2.
- **No collision in the shipped normalisation.** 93 subsets of size 0–3 over eight plausible names
  → 93 distinct hashes, zero collisions, including the `knowledge_bank`/`knowledgebank` and
  `network`/`NETWORK` near-miss pairs. `sorted(set(...))` is injective on sets.
- **The bare-string trap does not fire.** `systems_touched="network"` is **rejected**
  (`Input should be a valid tuple`); pydantic v2 refuses `str`→tuple. Also rejected: `None`, a
  dict, an int, `("network", 5)`, `(None,)`. A `list` **is** coerced to tuple, which is wanted.
  `category="egress"` and `category="BOGUS"` both rejected — only exact enum values pass.
- **No mutable-default aliasing**, and JSON round-trip is hash-stable (tuple type preserved).
- **The audit-chain compatibility claim is true, verified independently.** `_canonical_bytes` takes
  thirteen named parameters; `car_hash` is a stored opaque string that nothing recomputes. No code
  path anywhere recomputes a CAR hash against a persisted record.
- **No caller pins a literal digest.** The only 64-hex literals in the tree are a LoRA weight SHA
  and an injection-corpus content pin. Every `canonical_hash()` call site computes and compares.
- **The volatile exclusions hold** — `timestamp`, `request_id`, `session_id` all out, so the Hello
  envelope's N=3 lease premise is intact.
- **Nothing in production reads the four new fields**, verified by grep rather than assumed, so the
  permissive-default risk is genuinely future-tense.
- **The `CLAUDE.md` 2→3 symlink edit is factually correct**, confirmed by the reviewer's own
  non-elevated run naming the same three test locations.
- **The two doc-pointer failures are the same known artifact**, unchanged; ADR-013 was last touched
  in `bcbad774`, by neither commit under review.
