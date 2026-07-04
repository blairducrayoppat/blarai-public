---
role: sdo
phase: completion-review
revision: 1
tracking_task: 82
vikunja_comment: null
posted_at: 2026-04-23T06:36:03Z
verdict: APPROVED
---

# Sprint 8 EA-4 — SDO Completion Review

## Verdict

**APPROVED**

## Audit basis

- Branch: `feature/p5-task8-ea4-shared-launcher-hardening`
- Implementation commit: `dc7c43c`
- EA completion comment: Task 82 #383 (EA-4 Completion report task #237)
- Independent diff + pytest re-run against commit `dc7c43c`

## Audit summary

| Category | Result |
|---|---|
| Work item closure | **11 / 11 closed** |
| Negative constraints | **8 / 8 respected** |
| ORACLE gate (no production-code edits) | **clean** — 7 files, all under `shared/tests/`, `launcher/tests/`, or `docs/ledger/` |
| New test count | **46** (matches EA claim; above 20-test floor by 130%) |
| Pytest re-run (full suite) | **1008 passed, 2 skipped** — matches EA claim exactly, above 982 floor by +26 |

## Work item closure (11 / 11)

| WI | File | Tests | Verified |
|----|------|-------|----------|
| WI-1 | `shared/tests/test_runtime_config.py` | 2 (normal + frozen PyInstaller) | pytest collected |
| WI-2 | same | 3 (explicit / env / default) | pytest collected |
| WI-3 | same | 3 (host / guest / invalid) | pytest collected |
| WI-4 | same | 2 (structure + required keys) | pytest collected |
| WI-5 | `launcher/tests/test_guest_deploy.py` | 8 vsock failure branches | pytest collected |
| WI-6 | same | 3 (PA / AO / both fail) | pytest collected |
| WI-7 | `launcher/tests/test_launcher.py` | 2 (success + exception) | pytest collected |
| WI-8 | same | 5 cleanup guards | pytest collected |
| WI-9 | `launcher/tests/test_vm_manager.py` | 3 (success + shellexecute-low + os_error) | pytest collected |
| WI-10 | `shared/tests/test_car.py` (NEW) | 9 (TestCanonicalHash / TestIsComplete / TestDecisionArtifact / TestEnums) | pytest collected |
| WI-11 | `shared/tests/test_ipc_message_types.py` (NEW) | 6 MessageFramer encoders | pytest collected |

Sum: 10 + 11 + 7 + 3 + 9 + 6 = **46** — matches EA claim and commit message.

## Negative constraints

| NC | Severity | Result |
|---|---|---|
| NC-1 — L-15 pure test-authoring | HARD | **respected** (ORACLE diff empty) |
| NC-2 — no renames or file moves | HARD | **respected** |
| NC-3 — per-file ledger (Q1-1) | HARD | **respected** — new `docs/ledger/20260423_062642_sprint8_ea4_shared-launcher-hardening.md`, no edits to frozen monolithic ledger |
| NC-4 — no new runtime dependencies | HARD | **respected** — no `pyproject.toml` changes in diff |
| NC-5 — no real vsock/socket connections | HARD | **respected** — all transport mocked |
| NC-6 — no new production seams | HARD | **respected** — zero production edits |
| NC-7 — Sprint 9 coexistence (no `docs/governance/**`) | HARD | **respected** — diff touches no governance paths |
| NC-8 — scope-limited to named WIs | HARD | **respected** — all tests map to WI-1..WI-11 |

## Path-substitution audit (EA-reported deviations)

EA reported three path substitutions. All three are stable repo refactors, not authorial drift. Verified against current `main`:

| Prompt path | Actual path | Verdict |
|---|---|---|
| `shared/src/runtime_config.py` | `shared/runtime_config.py` | **Accepted** — `shared/src/` was flattened pre-Sprint 8. EA correctly targeted the real module. |
| `shared/src/ipc_types.py` | `shared/ipc/protocol.py` (`MessageFramer` methods) | **Accepted** — IPC encoders live on the framer; EA's 6 encoder tests correctly exercise them. |
| `launcher/tests/test_main.py` (expected) | `launcher/tests/test_launcher.py` (existing) | **Accepted** — prompt said "MODIFY EXISTING or CREATE if absent" and NC-2 prohibits renames. Extending the existing module is the prompt-compliant choice. |

## Quality-gate evidence

```
TEST-FULL:  1008 passed, 2 skipped, 2 warnings in 161.09s
ORACLE:     git diff main...dc7c43c --name-only | grep -vE "tests|conftest|docs|pyproject" -> EMPTY
```

## Merge-gate hint for Co-Lead

The 705-insertion diff is entirely test-code (+609) + ledger (+59) + report (+37-ish once `eb25c26` lands). Expect DEC-11 v3 §3.4 runaway-LOC carve-out to fire (threshold 500) — substance is clean; this is the pattern LA approved for EA-1 (856 LOC ESCALATE → approve).

## Budget self-check

- Session runtime: ~8 min (pytest dominated at 161s).
- Writes: Vikunja mutations + 1 disk report + 1 in-session commit + 1 event trigger. All within SDO `--allowedTools`.
- No CRITICAL breach.
