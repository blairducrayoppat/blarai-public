# Public-identifier scrub log

Rewrote 9 tracked file(s): host-name occurrences 2 (whole tree), operator user-name occurrences 8 (USER_SCOPE only), volume-serial occurrences 0 (whole tree), machine-SID occurrences 0 (SID_SCOPE only), cloud-account-SID occurrences 6 (whole tree). Identifiers and serials are not written here; `scripts/scrub_public_identifiers.py --check` and `tests/security/test_no_host_identity_in_tree.py` verify the result.

Interpreter: Python 3.14.3, zlib 1.3.1.zlib-ng (gzip bodies are reproducible with this zlib build; the decompressed content is what the lock certifies).

| file | host | user | serial | sid | account sid | sha256 before (LF) | sha256 after (LF) |
|---|---|---|---|---|---|---|---|
| `docs/research/containment-evidence-2026-10-05/nep0005-open-questions/nco/runs/case4-A-20261020-052240-21428.json` | 0 | 0 | 0 | 0 | 1 | `795d73213d25c8a0e95b04bea072f2f1d9ebf55e9e1d74cc207ae5487d4a1ed2` | `2de60b9a02d29b66afe2c56f891e3351a71b04ecd50880bfc2031e8771da5c2e` |
| `docs/research/containment-evidence-2026-10-05/nep0005-open-questions/nco/runs/case4-A-20261020-052241-23964.json` | 0 | 0 | 0 | 0 | 1 | `ea4d2ab38c310aabbfaa4534eaaf864134c169887e29f35f4b41a75281610555` | `3c6fc24a75a609aceddd3e8755087f9b80da90d0537c6e5fe6a14809df3cfeed` |
| `docs/research/containment-evidence-2026-10-05/nep0005-open-questions/nco/runs/case4-A-20261020-052242-13572.json` | 0 | 0 | 0 | 0 | 1 | `42b535ee5214b509d14d7d98a884746de50d67721ddfa8c530e53caf49b3e140` | `b5513899d8d8a6a3f87fa0bbdfd4685f613c355c58bf1ebee25606387eb62966` |
| `docs/research/containment-evidence-2026-10-05/nep0005-open-questions/nco/runs/case4-S-20261020-052145-19624.json` | 0 | 0 | 0 | 0 | 1 | `d55974be01c7f9c363fc6e46d3288dbe4720671a9c4a176d3207c1ac1ff36204` | `8be10f9159e73e147ca1678baa8a5974218e8a806beaad18cee96e226f0c4da0` |
| `docs/research/containment-evidence-2026-10-05/nep0005-open-questions/nco/runs/case4-S-20261020-052147-18812.json` | 0 | 0 | 0 | 0 | 1 | `4e80fac9c7d923cb454032e2039258d1c22c2e67ffb4b39413ab0faf92055272` | `170349d6b0ea8826d260633d371d033a542a19be6ce1ec8922a40029a608937e` |
| `docs/research/containment-evidence-2026-10-05/nep0005-open-questions/nco/runs/case4-S-20261020-052148-15020.json` | 0 | 0 | 0 | 0 | 1 | `afa63dfa09e2de057454c353b553a63f32d34e2afbfd3745fbe5e38d8f976c47` | `67f586a56e5b3180ec51930f3f4359a9da1c6c08f2f00bed4b7769405b5844b0` |
| `docs/research/containment-evidence-2026-10-05/nep0005-open-questions/nco/runs/case4-prepare-20261020-004848.json` | 2 | 0 | 0 | 0 | 0 | `f1a301073794b0a8e523d325fa5eeba0d136370255db1b6b4495a9e29c7c5e04` | `c5c1308a63caeb96cac104c2ed5e2bde89036469b0def618c13b35545878ac5d` |
| `docs/research/containment-evidence-2026-10-05/nep0005-open-questions/nco/runs/controls/nep5-results-n1-20261019-164952.json` | 0 | 6 | 0 | 0 | 0 | `6bf6dcceb5999f33ce12a8b4c93ae2c5dc81b448dc1d11ff47bf0a92b39a5f52` | `e8606018968d790753deca32d113e6bec5444eea4a7fbefbbcf0530aebacdb66` |
| `docs/research/containment-evidence-2026-10-05/nep0005-open-questions/nco/runs/controls/nep5-results-taskcheck-20261019-164908.json` | 0 | 2 | 0 | 0 | 0 | `ffc173c50d84c2b145bfc9ac1f685c84144d094db50c3a05d14357eb1e18361d` | `2b50d439fc871215e1832a31ef52ad4ed81ec4f1c454b074ed2f6bcaf5b13ecc` |
