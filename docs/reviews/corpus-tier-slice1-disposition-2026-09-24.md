# Disposition — pre-merge adversarial review of the corpus tier, slice 1 (#1616)

**Reviewed:** `feat/1616-corpus-tier` at `b128a4e7` (10 commits over main `b73a2dd6`), 2026-09-24.
**Reviewer:** independent Fable adversarial reviewer; the branch's author session was gone, and the
fixes below were written by a different session than the one that reviewed. Report:
`docs/reviews/corpus-tier-slice1-review-2026-09-24.md` (probes in that session's scratchpad).
**Outcome:** 11 findings: **7 FIXED, 4 DEFERRED, 0 REJECTED.** Nothing that could not be broken is
listed here as a finding; the review records what held (query sanitisation against 40 hostile
inputs, the injection path, the licence boundary, import-time behaviour, the shipped dormancy
state, every manifest refusal path but the empty-config one).

The four deferrals each wait on something only a later event can supply: a decision the Lead
Architect has not made (#1656), a code shape that exists only once the branch is on main (#1657),
and the merge motion itself (the DEC-14 companion commit).

```disposition
1-search-reference-locks-itself-after-its-first-result | FIXED | 4a3179d2 — search_reference joins _LOCK_EXEMPT_TOOLS on the same rung-1 grounds as search_knowledge (ADR-023 A5.8, DEC-13 amended in the same change). Real tool-loop drive: the second call runs; the same drive with the exemption removed refuses it (toggle); the first call under pre-existing knowledge content runs; the exempt set is pinned exactly.
2-empty-manifest-setting-opens-the-store-unverified | FIXED | a5bfbe60 — the reader has no unverified open: None resolves to the builder's manifest beside the store and a missing or mismatched manifest refuses; a second reader can skip the re-hash only by holding an already-verified reader of the same store (verified_by). The shipped empty setting is driven through the entrypoint's own expression in tests/security/test_reference_corpus_dormancy.py, refusing without a manifest and verifying with one.
3a-store-does-not-record-its-extraction | FIXED | 84e6ffab — the builder reads every shard sidecar, refuses shards that disagree on repo_commit / extract_rules_sha256 / with_tables, writes the agreed values into meta and the manifest (rules_sha256), and records the effective with_tables beside the build and extraction flags; the reader exposes them. The existing real store gains them at its next rebuild.
3b-manifest-is-a-checksum-not-a-signature | DEFERRED | #1656 — D1 says "signed manifest verified at load"; the manifest is a SHA-256 of the file, which proves integrity but not authenticity, while shared/models/manifest_signer.py already signs model weights with the TPM-backed key. Signing it also fixes the per-boot cost question (note 7b). blocked-by: #1656 recording the Lead Architect's verification-frequency decision and his delegation of the signing ceremony for the corpus store.
4-dormant-tool-advertised-in-every-live-prompt | FIXED | 65e9b31a — runner-gated tools are described only while their runner is registered; the prompt renders at call time, cached per advertised set. Measured: the dormant prompt is byte-identical to main's (same SHA-256 digest, 9,590 chars); with the runner registered it carries the tool. Dispatch unchanged. Locks with toggle in test_retrieval_tools.py.
5-notice-lock-hardcodes-three-prefixes | FIXED | 8c160b52 — prefixes derived from _TOOL_RESULT_PROVENANCE; the toggle test (plant a fourth declared tool with an undeclared notice; the lock names it) did NOT exist when this row was first written, and was added at 7a022ecd after the re-check caught the claim.
6-no-test-drives-the-registration-block-in-start | DEFERRED | #1657 — dormancy is certified by the config value and by reading the resolver, never by driving start() with a fixture store. blocked-by: #1616 merged to main, because the test locks the shape start() has on main and the registration block may move into a callable unit to make it reachable.
7a-stop-leaves-the-corpus-handle-open | FIXED | 84cf736e — stop() closes the store handle beside the knowledge bank; locked by test_stop_closes_the_reference_corpus_and_clears_its_runner.
7b-39-gb-hashed-at-every-boot | DEFERRED | #1656 — the cost is unmeasured and the frequency of full-content verification is a security-posture trade-off (every boot is strongest and costs minutes; a signed manifest plus occasional re-hash is what the weights do). blocked-by: #1656 recording the Lead Architect's verification-frequency decision.
7c-amendment-4-residue-in-two-docstrings | FIXED | 84cf736e — the UNTRUSTED_CORPUS tier is ADR-023 Amendment 5; the runner docstring and the pgov declaration now say so.
7d-dec-14-rides-this-branch-and-gate-rebaseline-not-done | FIXED | 2b59f48d — the merge commit of feat/1616-corpus-tier on main. DEC-14 did not ride the merge: it reached main earlier as 629b96b5 (3c4b9eea is a no-op here), recorded for #1640 in the same motion. Gate on the branch in the real checkout at 05a0ad55, elevated, app down: 13179 passed / 0 failed / 0 skipped / 620 deselected (24:46); gate on merged main 2b59f48d in the real checkout, same conditions: 13179 / 0 / 0 / 620 (24:40), identical to the prediction written before it. TEST_GOVERNANCE §1 and the CLAUDE.md snapshot were updated together on the branch at fdfb918a, before the merge.
```

## What the fixes change that a later measurement must know

Finding 1's exemption changes what production does when the model searches twice. The accuracy
baseline (#1641 comment 3718) forced one search per question and recorded four items that searched
a second time; under the lock those second searches were refused. Those four items can answer
differently now. That is at most 4 of 160 answerable items, and the next full run (the expanded
golden set, #1649) measures it. The #1641 baseline's freshness check will flag the retrieval-code
change when both branches are on main; the reseed records this reason rather than hiding it.
