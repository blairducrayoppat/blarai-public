---
title: "Adversarial review, round 3 (targeted) — machine account SID scrub (#1799)"
date: 2026-10-16
review_of: "f40444c4 on feat/scrub-account-sid (fixes b889f070, 14e2747d, f40444c4 for round-2 N1-N6)"
reviewer: independent subagent (author != verifier)
---

# Round 3 — machine account SID scrub (#1799), at `f40444c4`

**Verdict: FAIL (one blocker, R1: N1 is closed for plain text only).** The fix puts `SID_REWRITE_RE` on the raw bytes inside
`find_sid_hits`, but the rewrite runs inside containers (`scrub_bytes` decompresses gzip and decodes UTF-16 before
`rewrite_machine_sids`). Inside a gzip member or a UTF-16 file, the lock is still narrower than the rewrite. N2, N3, N5 and N6
verify.

## Findings

1. **R1 HIGH (blocker): the lock is still narrower than the rewrite inside gzip members and UTF-16 files.**
   `scripts/identity_lock.py:123` checks `SID_REWRITE_RE` against the raw bytes only; `scripts/scrub_public_identifiers.py:179-195`
   (`scrub_bytes`) applies the rewrite to the decompressed member and to the UTF-16-decoded text. `views()` does decompress and
   decode, but it only runs `MACHINE_SID_RE`, which is blind to the doubly encoded and `%41` shapes. Cost: the same as round-2 N1.
   `--dir --check` exits 0 on a bundle that carries a full machine SID, whenever the check runs without the rewrite.
   Reproduced (made-up SID `S-1-5-21-1111111111-2222222222-3333333333-1001`; the doubly encoded record is the round-2 one):

   | shape | `find_sid_hits` | `scrub_bytes` sid count |
   |---|---|---|
   | doubly / triply encoded, plain | True | 1 |
   | `%41`+SID, plain | True | 1 |
   | `\u0053`, `\u`-escaped digit, ANSI after a letter, plain | True | 1 |
   | UTF-16 LE with BOM, of the doubly encoded record | **False** | 1 |
   | UTF-16 LE without BOM, same record | **False** | 1 |
   | gzip of the doubly encoded record | **False** | 1 |
   | gzip of `%41`+SID | **False** | 1 |
   | gzip of UTF-16 of the doubly encoded record | **False** | 1 |

   Through the entry point, with one file per folder in scratch (`log.jsonl.gz` = gzip of the doubly encoded record, and
   `out16.txt` = UTF-16 of it): `--dir --check` gave **exit 0, "0 finding(s)"** for each. `--dir` then rewrote each, and the
   domain left (verified after decompress/decode). Harness: `r3prop.py` and `r3ep.py` in the reviewer's scratchpad.
   Incidence in `run-20261016-1`: 0. Its 22 files include 0 gzip and 0 UTF-16 files. The fix needs the same rewrite-arm test
   applied to each container reading the rewrite uses (decompressed member, UTF-16-decoded text), not only to the raw bytes.

2. **R2 MEDIUM: the N1 property lock overclaims and cannot see R1.**
   `tests/security/test_machine_sid_scrub.py:166-175` (`test_the_lock_is_never_narrower_than_the_rewrite`). The docstring says
   "for every shape and every wrapping". The wrappers are identity, a prefix, single JSON and double JSON. It calls
   `il.rewrite_machine_sids`, the raw-text arm, instead of `scrub.scrub_bytes`, the container dispatch `--dir` actually uses. No
   gzip or UTF-16 wrapper exists, so the property passes at `f40444c4` while R1 holds. The discriminating form takes the rewrite
   count from `scrub_bytes` and adds gzip, UTF-16 (with and without BOM) and gzip(UTF-16) wrappers.

## Round-2 findings, re-verified at `f40444c4`

- **N1:** fixed for plain bytes; open inside containers (R1). Toggle: with the rewrite arm removed from `find_sid_hits` in a
  scratch copy, the suite went from 1 failed (environmental, see below) to 9 failed. The arm is load-bearing.
- **N2:** killed. In a scratch copy, removing the file-name SID rule in `check()` (line 435) gives +1 failure. Removing it in
  `main()` (line 594) also gives +1.
- **N3:** fixed. `test_a_sid_glued_after_a_letter_is_never_rewritten_into_a_wrong_value` (line 158) accepts either
  "left as written" or "rewritten with the sub-authorities gone", so it no longer forbids a fix.
- **N5:** killed. Narrowing the `except` at line 484 to an unrelated exception gives +1 failure.
- **N6:** `python scripts/verify_disposition.py docs/reviews/scrub-account-sid-disposition-2026-10-16.md` reports
  PASS, 13 ok / 0 unjustified. The DEFERRED predicates (f3b, f6, n4) name an observable event: a `--dir --check` refusal and
  named test ids. They are honest about current incidence. The `n1 | FIXED | b889f070` row is now wrong (R1), and must be
  reopened in the next disposition.

## Attacked and could not break

- Plain-text shapes against lock ⇒ rewrite: double and triple JSON encoding, `%41` (either case of the SID), `\u0053`,
  `\u`-escaped digit, ANSI code after a letter. The lock fires on all of them, and after the rewrite it is silent on all.
- `\x41\x53-1-5-21-...`: neither the lock nor the rewrite fires. This is consistent with the deferred F6 letter-glued class, and
  is not a lock/rewrite disagreement.
- No new false positive. Tree `--check`: 0 findings in 4093 tracked files, exit 0. Real run, scratch copy of
  `%USERPROFILE%/blarai-research-data/mxc-proxy-egress/run-20261016-1`: `--dir --check` exit 1 (19 findings), `--dir` exit 0,
  `--dir --check` exit 0. Census before and after: `S-1-16-8192` 25, `S-1-16-4096` 6, `S-1-15-2-*` 2622, all unchanged. Six
  `S-1-5-21` SIDs went to `S-1-5-21-__MACHINE__-1001`, with the relative ID kept.

## What was run

Hash `f40444c4`, worktree `%USERPROFILE%/BlarAI-worktrees/scrub-account-sid`, primary checkout's `.venv` (Python 3.11.9),
LOCALAPPDATA redirected to the reviewer's scratchpad. `tests/security/test_machine_sid_scrub.py`: 60 passed in the worktree.
Mutation runs were in a scratch copy with `--noconftest`. The root conftest imports `shared`, which the copy lacks. That copy
has one environmental failure (`test_sid_scope_names_tracked_files`, an empty git repo) in the baseline, and every mutant count
above is relative to it. The other three identity test files were not run (time).

## Merge read

Block on R1. The ticket's contract is that `--check` fails on any SID the rewrite would remove. The round-2 shape still passes
when it is gzipped or written as UTF-16, both container forms the scrub explicitly handles. R2 should be fixed in the same change,
because it is the lock that would have caught R1. Nothing else blocks.
