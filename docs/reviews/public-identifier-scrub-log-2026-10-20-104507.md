# Public-identifier scrub log

Rewrote 1 tracked file(s): host-name occurrences 2 (whole tree), operator user-name occurrences 0 (USER_SCOPE only), volume-serial occurrences 0 (whole tree), machine-SID occurrences 0 (SID_SCOPE only), cloud-account-SID occurrences 0 (whole tree). Identifiers and serials are not written here; `scripts/scrub_public_identifiers.py --check` and `tests/security/test_no_host_identity_in_tree.py` verify the result.

Interpreter: Python 3.14.3, zlib 1.3.1.zlib-ng (gzip bodies are reproducible with this zlib build; the decompressed content is what the lock certifies).

| file | host | user | serial | sid | account sid | sha256 before (LF) | sha256 after (LF) |
|---|---|---|---|---|---|---|---|
| `docs/research/containment-evidence-2026-10-05/nep0005-open-questions/nco/runs/case4-prepare-20261020-092824.json` | 2 | 0 | 0 | 0 | 0 | `69e4fde073d086a1eb020088628d40ac5c9cd6bc0797df7b5e41fbc1af57be7d` | `03a30587a525bc46c636ca8d0693a5aea9f944d305891acd1217758566a79657` |
