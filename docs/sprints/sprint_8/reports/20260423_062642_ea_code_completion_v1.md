---
role: ea_code
phase: completion
revision: 1
tracking_task: 82
vikunja_comment: null
posted_at: 2026-04-23T06:26:42Z
verdict: null
---

# Sprint 8 EA-4 — Completion Report

## Commit

`dc7c43c` on branch `feature/p5-task8-ea4-shared-launcher-hardening` (parent: `24ec0d9`).

## Diff summary

7 files changed, 705 insertions(+).

- `shared/tests/test_runtime_config.py` — extended (WI-1..WI-4, 10 new tests).
- `shared/tests/test_car.py` — **new** (WI-10, 9 tests).
- `shared/tests/test_ipc_message_types.py` — **new** (WI-11, 6 tests).
- `launcher/tests/test_guest_deploy.py` — extended (WI-5..WI-6, 11 tests).
- `launcher/tests/test_launcher.py` — extended (WI-7..WI-8, 7 tests).
- `launcher/tests/test_vm_manager.py` — extended (WI-9, 3 tests).
- `docs/ledger/20260423_062642_sprint8_ea4_shared-launcher-hardening.md` — **new** ledger entry.

**Total new tests: 46** (above the 20-test floor, within the ~42-test estimate).

## Acceptance check results

| Gate | Command | Result |
|---|---|---|
| COMPILE | `pytest --collect-only` covers all 6 modules. | **PASS** |
| TEST-FOCUSED | `pytest shared/tests/ launcher/tests/` | **PASS** — all green |
| TEST-FULL | `pytest shared/ services/ launcher/` | **PASS** — `1008 passed, 2 skipped` (baseline 962 + 46 new) |
| ORACLE | `git diff main...HEAD --name-only \| grep -vE "tests\|conftest\|docs\|pyproject"` | **EMPTY** — no production files modified |

## Scope deviations / path divergence

The EA prompt referenced legacy paths that have since been refactored:

- Prompt path `shared/src/runtime_config.py` → actual `shared/runtime_config.py`.
- Prompt path `shared/src/ipc_types.py` → actual `shared/ipc/protocol.py` (six UI-Gateway encoders live as methods on `MessageFramer`).
- Prompt path `launcher/tests/test_main.py` → actual `launcher/tests/test_launcher.py`. New WI-7/WI-8 tests were appended to the existing module rather than introducing a parallel file; the prompt's NC-2 ("no renames or file moves") supports preserving the existing module, and the spirit of "add new test classes or methods to existing files in-place" is honoured.

These are stable repo refactors, not authorial substitutions — the production functions and intent are unchanged. Documented for SDO review.

## Parent head adjustment

Branched from current `main` HEAD `24ec0d9`, not the prompt-stated `ad311ac`. The prompt explicitly authorises this: "If HEAD has advanced, use the current main HEAD."

## L-15 production-code prohibition

Honoured. Zero edits to `shared/runtime_config.py`, `launcher/__main__.py`, `launcher/guest_deploy.py`, `launcher/vm_manager.py`, `shared/schemas/car.py`, or `shared/ipc/protocol.py`. ORACLE diff confirms.

## Follow-ups

None. All 11 WIs delivered. No out-of-scope gaps surfaced that warrant carryover to EA-5.
