# #1740 raw-data summary

### Permission instrument repeatability

- fixtures: 4 inventories; identical masks in all: True; rows where an instrument disagreed with the kernel reference: 0
- real: 4 inventories; identical masks in all: True; rows where an instrument disagreed with the kernel reference: 0

### Arm D: 7 runs

| timing (s) | mean | sd | CV % | min | max | n |
|---|---|---|---|---|---|---|
| launch_wall | 6.587 | 0.125 | 1.9 | 6.484 | 6.819 | 7 |
| payload_total | 6.481 | 0.125 | 1.9 | 6.380 | 6.713 | 7 |
| tool:bash | 0.528 | 0.014 | 2.7 | 0.504 | 0.550 | 7 |
| tool:git | 0.068 | 0.001 | 1.7 | 0.067 | 0.070 | 7 |
| tool:node | 0.057 | 0.001 | 1.8 | 0.056 | 0.058 | 7 |
| tool:opencode | 0.525 | 0.054 | 10.2 | 0.497 | 0.646 | 7 |
| tool:python | 0.068 | 0.003 | 4.5 | 0.066 | 0.075 | 7 |
| tool:task | 0.768 | 0.076 | 9.9 | 0.721 | 0.899 | 7 |

Categorical outcomes: 45; identical in every run: 45; varying: 0.


| outcome | value (all runs) |
|---|---|
| `egress:1.1.1.1:443` | connected/None |
| `egress:example.com:443` | connected/None |
| `identity:appcontainer` | False |
| `identity:integrity` | S-1-16-8192 |
| `identity:restricting_sids` | 0 |
| `identity:user` | S-1-5-21-1000000001-1000000002-1000000003-1001 |
| `inherit:d0:egress` | connected |
| `inherit:d0:integrity` | S-1-16-8192 |
| `inherit:d0:write_authusers` | allowed |
| `inherit:d1:egress` | connected |
| `inherit:d1:integrity` | S-1-16-8192 |
| `inherit:d1:write_authusers` | allowed |
| `inherit:d2:egress` | connected |
| `inherit:d2:integrity` | S-1-16-8192 |
| `inherit:d2:write_authusers` | allowed |
| `loopback:127.0.0.1:8000` | failed/10061 |
| `loopback:127.0.0.1:8099` | failed/10061 |
| `loopback:127.0.0.1:listener` | connected/None |
| `read:C:\Users\__USER__\.codex\.sandbox-secrets` | allowed |
| `read:C:\Users\__USER__\.config\opencode` | allowed |
| `read:C:\Users\__USER__\.git-credentials` | allowed |
| `read:C:\Users\__USER__\.ssh` | allowed |
| `read:C:\Users\__USER__\AppData\Local\BlarAI` | allowed |
| `tool:bash` | 0 |
| `tool:git` | 0 |
| `tool:node` | 0 |
| `tool:opencode` | 0 |
| `tool:python` | 0 |
| `tool:task` | True |
| `write:C:\blarai-spike-1740\instrument\deny-A` | denied |
| `write:C:\blarai-spike-1740\instrument\deny-B2` | allowed |
| `write:C:\blarai-spike-1740\instrument\deny-C` | allowed |
| `write:C:\blarai-spike-1740\instrument\deny-D` | denied |
| `write:C:\blarai-spike-1740\instrument\grant-A` | denied |
| `write:C:\blarai-spike-1740\instrument\grant-B2` | allowed |
| `write:C:\blarai-spike-1740\instrument\grant-C` | allowed |
| `write:C:\blarai-spike-1740\instrument\grant-D` | allowed |
| `write:C:\blarai-spike-1740\leak\authenticated-users-modify` | allowed |
| `write:C:\blarai-spike-1740\leak\fleet` | allowed |
| `write:C:\blarai-spike-1740\leak\models` | allowed |
| `write:C:\blarai-spike-1740\leak\projects` | allowed |
| `write:C:\blarai-spike-1740\leak\users-modify` | allowed |
| `write:C:\blarai-spike-1740\leak\windows-temp-classic` | allowed |
| `write:C:\blarai-spike-1740\leak\windows-temp-today` | denied |
| `write:C:\blarai-spike-1740\worktree` | allowed |

Predictions from `effective-access-fixtures-20261010T221244.json`.

| fixture | predicted write | run result | agree |
|---|---|---|---|
| `C:\blarai-spike-1740\instrument\deny-A` | False | denied | yes |
| `C:\blarai-spike-1740\instrument\deny-B2` | True | allowed | yes |
| `C:\blarai-spike-1740\instrument\deny-C` | True | allowed | yes |
| `C:\blarai-spike-1740\instrument\deny-D` | False | denied | yes |
| `C:\blarai-spike-1740\instrument\grant-A` | False | denied | yes |
| `C:\blarai-spike-1740\instrument\grant-B2` | True | allowed | yes |
| `C:\blarai-spike-1740\instrument\grant-C` | True | allowed | yes |
| `C:\blarai-spike-1740\instrument\grant-D` | True | allowed | yes |
| `C:\blarai-spike-1740\leak\authenticated-users-modify` | True | allowed | yes |
| `C:\blarai-spike-1740\leak\fleet` | True | allowed | yes |
| `C:\blarai-spike-1740\leak\models` | True | allowed | yes |
| `C:\blarai-spike-1740\leak\projects` | True | allowed | yes |
| `C:\blarai-spike-1740\leak\users-modify` | True | allowed | yes |
| `C:\blarai-spike-1740\leak\windows-temp-classic` | True | allowed | yes |
| `C:\blarai-spike-1740\leak\windows-temp-today` | False | denied | yes |
| `C:\blarai-spike-1740\worktree` | True | allowed | yes |

Prediction vs run: 16 of 16 agree.

