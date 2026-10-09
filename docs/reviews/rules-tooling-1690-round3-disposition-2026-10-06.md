# Disposition - #1690 install hardening, independent review round 3 (tip 29f44d38; findings K1-K4, no blocking)

**Review:** `docs/reviews/code-review-1690-round3-2026-10-06.md` (Fable reviewer, not the author; ran the code against throwaway
repositories, wrote no fix). Round-3 verdict on the two blocking holes of round 2: **R1 CLOSED, R2 CLOSED** (evidence in the
review: every swap/rollback step injected, 58 slow cases passed; fake-interpreter repro refused). Ids are prefixed K because
the earlier records use N, P, Q, R, S and H2 ids. Author of the K2/K4 fixes and of this record: the session; the fixes are
a test row and one explainer line, not control code.

```disposition
K1-redundant-shell-base-sha-check-on-main | REJECTED | The reviewer's own reading is that no change is needed: on main the python guard also compares the base interpreter hash, so the shell check duplicates it there, and on a feature branch the python guard returns early so the shell check is the only lock; the mutant that removes it is isolated on a feature branch and is killed, so the duplication is deliberate defense in depth, not dead code.
K2-ifs-ld-alias-not-exercised-by-a-test | FIXED | the hostile-environment parametrisation in tests/security/test_git_swap_and_handshake.py gains an IFS-set-to-path-separators row that runs through both the pre-commit shim and the reference-transaction shim, 14 hostile cases pass; aliases are not expanded by a non-interactive sh and LD_ variables do not apply to the native Windows python, argued in the review and left as argument.
K3-interpreter-dlls-and-stdlib-not-hashed | REJECTED | This is the residual ADR-043 already states, not a new finding: hashing the interpreter's DLLs and standard library cannot be closed inside this installer because an attacker who can write beside the base interpreter can also rewrite the record, and the structural answer is the separate confined account of #1689, which owns it.
K4-amend-on-main-refused-looks-like-a-bug | FIXED | one sentence in docs/governance/commit-protection-explained.md says amending a commit already on main is refused as a history rewrite by design and a correction goes in as a new commit.
```
