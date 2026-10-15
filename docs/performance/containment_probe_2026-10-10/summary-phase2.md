# #1740 phase-2 summary

### Outcomes per variant (every run of a variant agreed unless marked)

| variant | runs | started | container | integrity | node | git | bash | python | opencode | task | loopback:listener | loopback:8099 | egress:1.1.1.1 | egress:example.com | secrets_denied | writes_allowed | children_inherit | stable |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B1-fixture | 3/3 | yes | none | high | ok | ok | ok | ok | ok | ok | connected | failed(10061) | connected | connected | 0/5 | instrument\deny-B2,instrument\deny-C,instrument\grant-B2,instrument\grant-C,instrument\grant-D,leak\authenticated-users-modify,leak\fleet,leak\models,leak\projects,leak\users-modify,leak\windows-temp-classic,worktree | yes | yes |
| B2-fixture | 3/3 | yes | restricted | medium | ok | ok | rc=3221225794 | ok | ok | FAIL | connected | failed(10061) | connected | connected | 0/5 | instrument\grant-B2,worktree | yes | yes |
| B2-fixture-block-only | 3/3 | yes | restricted | medium | ok | ok | rc=3221225794 | ok | ok | FAIL | connected | failed(10061) | failed | failed | 0/5 | instrument\grant-B2,worktree | yes | yes |
| B2-fixture-block-permit | 3/3 | yes | restricted | medium | ok | ok | rc=3221225794 | ok | ok | FAIL | connected | failed(10061) | connected | connected | 0/5 | instrument\grant-B2,worktree | yes | yes |
| B2-fixture-fence-synthetic-sid | 3/3 | yes | restricted | medium | ok | ok | rc=3221225794 | ok | ok | FAIL | connected | failed(10061) | connected | connected | 0/5 | instrument\grant-B2,worktree | yes | yes |
| B3-fixture | 3/3 | yes | restricted | medium | ok | ok | rc=3221225794 | ok | rc=1 | FAIL | connected | failed(10061) | connected | connected | 5/5 | instrument\grant-B2,leak\authenticated-users-modify,leak\fleet,leak\models,leak\users-modify,worktree | yes | yes |
| B3-fixture-block-only | 3/3 | yes | restricted | medium | ok | ok | rc=3221225794 | ok | rc=1 | FAIL | connected | failed(10061) | failed | failed | 5/5 | instrument\grant-B2,leak\authenticated-users-modify,leak\fleet,leak\models,leak\users-modify,worktree | yes | yes |
| B3-fixture-block-permit | 3/3 | yes | restricted | medium | ok | ok | rc=3221225794 | ok | rc=1 | FAIL | connected | failed(10061) | failed | failed | 5/5 | instrument\grant-B2,leak\authenticated-users-modify,leak\fleet,leak\models,leak\users-modify,worktree | yes | yes |
| B3-real-toolchain | 3/3 | yes | restricted | medium | ok | ok | rc=256 | ok | rc=None | FAIL | connected | failed(10061) | connected | connected | 5/5 | instrument\grant-B2,leak\authenticated-users-modify,leak\fleet,leak\models,leak\users-modify,worktree | yes | yes |
| C-real-toolchain | 3 | NOT STARTED |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | |
| C0-fixture-no-capabilities | 3/3 | yes | AppContainer | low | ok | ok | rc=3221225794 | ok | rc=1 | FAIL | failed(None) | failed(10061) | failed | failed | 5/5 | instrument\deny-C,instrument\grant-C,worktree | yes | yes |
| C1-fixture-loopback-exempt | 3/3 | yes | AppContainer | low | ok | ok | rc=3221225794 | ok | rc=1 | FAIL | connected | failed(10061) | failed | failed | 5/5 | instrument\deny-C,instrument\grant-C,worktree | yes | yes |
| C2-fixture-internetClient | 3/3 | yes | AppContainer | low | ok | ok | rc=3221225794 | ok | rc=1 | FAIL | failed(None) | failed(10061) | connected | connected | 5/5 | instrument\deny-C,instrument\grant-C,worktree | yes | yes |
| C3-fixture-internetClient-fence-package | 3/3 | yes | AppContainer | low | ok | ok | rc=3221225794 | ok | rc=1 | FAIL | connected | failed(10061) | failed | failed | 5/5 | instrument\deny-C,instrument\grant-C,worktree | yes | yes |
| D-fixture | 5/5 | yes | none | medium | ok | ok | ok | ok | ok | ok | connected | failed(10061) | connected | connected | 0/5 | instrument\deny-B2,instrument\deny-C,instrument\grant-B2,instrument\grant-C,instrument\grant-D,leak\authenticated-users-modify,leak\fleet,leak\models,leak\projects,leak\users-modify,leak\windows-temp-classic,worktree | yes | yes |
| D-fixture-block-only | 3/3 | yes | none | medium | ok | ok | ok | ok | ok | ok | connected | failed(10061) | failed | failed | 0/5 | instrument\deny-B2,instrument\deny-C,instrument\grant-B2,instrument\grant-C,instrument\grant-D,leak\authenticated-users-modify,leak\fleet,leak\models,leak\projects,leak\users-modify,leak\windows-temp-classic,worktree | yes | yes |
| D-fixture-block-permit | 3/3 | yes | none | medium | ok | ok | ok | ok | ok | ok | connected | failed(10061) | connected | connected | 0/5 | instrument\deny-B2,instrument\deny-C,instrument\grant-B2,instrument\grant-C,instrument\grant-D,leak\authenticated-users-modify,leak\fleet,leak\models,leak\projects,leak\users-modify,leak\windows-temp-classic,worktree | yes | yes |
| E0 | 3/3 | yes | unknown | ? | rc=3221225794 | rc=3221225794 | rc=3221225794 | ok | rc=1 | FAIL | failed(10013) | failed(10013) | failed | failed | 5/5 | worktree | yes | yes |
| E1 | 3/3 | yes | AppContainer | low | ok | ok | rc=3221225794 | ok | rc=1 | FAIL | failed(10013) | failed(10013) | failed | failed | 5/5 | worktree | yes | yes |
| E2 | 3/3 | yes | AppContainer | low | ok | ok | rc=3221225794 | ok | rc=1 | FAIL | failed(None) | failed(10061) | connected | connected | 5/5 | worktree | yes | yes |
| E3 | 1 | NOT STARTED |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | |
| E4 | 1 | NOT STARTED |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | |

### Timings (seconds, payload-internal) against the control `D-fixture`

| variant | payload_total | node | git | python | task |
|---|---|---|---|---|---|
| B1-fixture | 8.453 (n=3) | 0.108 (n=3) | 0.127 (n=3) | 0.132 (n=3) | 1.387 (n=3) |
| B2-fixture | 7.639 (n=3) | 0.102 (n=3) | 0.143 (n=3) | 0.109 (n=3) | 1.231 (n=3) |
| B2-fixture-block-only | 8.665 (n=3) | 0.137 (n=3) | 0.172 (n=3) | 0.157 (n=3) | 1.743 (n=3) |
| B2-fixture-block-permit | 9.384 (n=3) | 0.134 (n=3) | 0.164 (n=3) | 0.193 (n=3) | 2.300 (n=3) |
| B2-fixture-fence-synthetic-sid | 7.811 (n=3) | 0.114 (n=3) | 0.124 (n=3) | 0.131 (n=3) | 1.352 (n=3) |
| B3-fixture | 7.698 (n=3) | 0.117 (n=3) | 0.128 (n=3) | 0.118 (n=3) | 1.369 (n=3) |
| B3-fixture-block-only | 8.360 (n=3) | 0.143 (n=3) | 0.140 (n=3) | 0.142 (n=3) | 1.895 (n=3) |
| B3-fixture-block-permit | 8.807 (n=3) | 0.175 (n=3) | 0.173 (n=3) | 0.130 (n=3) | 2.044 (n=3) |
| B3-real-toolchain | 6.383 (n=3) | 0.116 (n=3) | 0.137 (n=3) | 0.125 (n=3) | 1.187 (n=3) |
| C0-fixture-no-capabilities | 9.541 (n=3) | 0.084 (n=3) | 0.104 (n=3) | 0.119 (n=3) | 1.217 (n=3) |
| C1-fixture-loopback-exempt | 6.597 (n=3) | 0.100 (n=3) | 0.112 (n=3) | 0.123 (n=3) | 1.219 (n=3) |
| C2-fixture-internetClient | 9.605 (n=3) | 0.089 (n=3) | 0.111 (n=3) | 0.109 (n=3) | 1.182 (n=3) |
| C3-fixture-internetClient-fence-package | 6.440 (n=3) | 0.086 (n=3) | 0.104 (n=3) | 0.122 (n=3) | 1.178 (n=3) |
| D-fixture | 8.637 (n=5) | 0.110 (n=5) | 0.120 (n=5) | 0.133 (n=5) | 1.490 (n=5) |
| D-fixture-block-only | 9.666 (n=3) | 0.149 (n=3) | 0.208 (n=3) | 0.149 (n=3) | 1.964 (n=3) |
| D-fixture-block-permit | 9.857 (n=3) | 0.123 (n=3) | 0.145 (n=3) | 0.148 (n=3) | 1.978 (n=3) |
| E0 | 1.310 (n=3) | 0.062 (n=3) | 0.046 (n=3) | 0.139 (n=3) | 0.424 (n=3) |
| E1 | 2.613 (n=3) | 0.099 (n=3) | 0.112 (n=3) | 0.127 (n=3) | 1.268 (n=3) |
| E2 | 9.814 (n=3) | 0.099 (n=3) | 0.098 (n=3) | 0.126 (n=3) | 1.270 (n=3) |

Control run-to-run variation (CV %): bash 11.1, git 8.8, node 10.4, opencode 13.2, payload_total 3.1, python 9.6, task 3.9. A difference smaller than the control's CV for that measurement is not a finding.

### Prediction (Windows' access check, before launch) against what the payload did

Predictions from `effective-access-fixtures-20261011T111301.json` (fixtures) and `effective-access-real-20261011T111248.json` (secret paths). A fixture write counts as allowed when the probe file was created (deleting it may still have been refused).

| variant | fixture writes agreeing | disagreements | secret reads agreeing | disagreements |
|---|---|---|---|---|
| B1-fixture | 48/48 | none | 15/15 | none |
| B2-fixture | 48/48 | none | 15/15 | none |
| B2-fixture-block-only | 48/48 | none | 15/15 | none |
| B2-fixture-block-permit | 48/48 | none | 15/15 | none |
| B2-fixture-fence-synthetic-sid | 48/48 | none | 15/15 | none |
| B3-fixture | 48/48 | none | 15/15 | none |
| B3-fixture-block-only | 48/48 | none | 15/15 | none |
| B3-fixture-block-permit | 48/48 | none | 15/15 | none |
| B3-real-toolchain | 48/48 | none | 15/15 | none |
| C0-fixture-no-capabilities | 48/48 | none | 15/15 | none |
| C1-fixture-loopback-exempt | 48/48 | none | 15/15 | none |
| C2-fixture-internetClient | 48/48 | none | 15/15 | none |
| C3-fixture-internetClient-fence-package | 48/48 | none | 15/15 | none |
| D-fixture | 80/80 | none | 25/25 | none |
| D-fixture-block-only | 48/48 | none | 15/15 | none |
| D-fixture-block-permit | 48/48 | none | 15/15 | none |

### Variants that did not start

- `C-real-toolchain`: no payload; see the record
- `E3`: error: network.ingress.hostLoopback='allow' is not supported by this version of Windows; host-loopback ingress requires native ProcessContainer support
- `E4`: error: network.ingress.hostLoopback='allow' is not supported by this version of Windows; host-loopback ingress requires native ProcessContainer support
