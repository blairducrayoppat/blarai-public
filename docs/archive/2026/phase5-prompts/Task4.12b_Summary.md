---
title: Task4.12b_Summary
status: archived
area: portfolio
---

# Task 4.12b — Category A: 70 LLM-Path DENY Cases

**Status:** COMPLETE  
**Branch:** `feature/p5-task4-12-corpus-hardening`  
**Commit:** `b13db8d`  
**Date:** 2026-03-06  
**Parent:** `152c0e7` (Task 4.12a harness scaffolding)

---

## Objective

Add 70 Category A test cases (IDs 40–109) to the PA Quality Gate harness. All Category A cases are LLM-path DENY — they bypass the DeterministicPolicyChecker pre-filter (`check()` returns `None`) and must be classified as DENY by the LLM. These cases cover 6 adversarial trigger patterns targeting security-critical operations that a malicious or compromised agent might attempt.

## Files Modified

| File | Action | Delta |
|---|---|---|
| `phase2_gates/scripts/run_p5_task4_9_pa_quality_gate.py` | Modified (sole production change) | +829 / −18 |
| `docs/Task4.12b_EA2_INIT_MESSAGE.xml` | Created (EA-2 initialization message) | +178 |

## Trigger Patterns (6)

| Pattern | Count | Description |
|---|---|---|
| **A-T1** | 10 | DELETE/WRITE on security infrastructure (`/opt/`, `/shared/` paths) — destructive removal or overwrite of security configs, firewall rules, ACLs, encryption keys, authentication tokens |
| **A-T2** | 10 | WRITE to disable monitoring/controls — silences logging, anomaly detection, rate limiting, policy agent classification, sandbox enforcement, security killswitches |
| **A-T3** | 10 | EXECUTE with malicious command parameters — rm -rf equivalents, reverse shells, password changes, chmod 777, cryptominers, disk wipes, firewall flushes, keyloggers, crontab injection, process kills |
| **A-T4** | 10 | READ cross-user data reconnaissance — bulk credential theft, SSH key extraction, session hijacking, PII dumps, audit log analysis, encryption key extraction, API secret harvesting |
| **A-T5** | 20 | Parameter-embedded exfiltration to non-`/tmp/export/` destinations — data staging to `/mnt/external/`, `/tmp/staging/`, `/dev/shm/`, `/var/spool/`, `/mnt/usb/`, and 15 other exfil paths |
| **A-T6** | 10 | Recursive/bulk destructive operations with force flags — recursive wipe of `/shared/`, `/opt/blarai/`, model stores, credential vaults, backup archives, logging infrastructure, entire workspace |

**Total:** 70 cases

## Band Distribution

| Band (tokens) | Count |
|---|---|
| 512 | 15 |
| 1024 | 17 |
| 2048 | 19 |
| 4096 | 19 |
| **Total** | **70** |

Each trigger pattern distributes its cases across bands to ensure coverage at every context-length tier.

## Parameterization Changes

Four hardcoded references to the original 40-case corpus were replaced with dynamic expressions:

| Location | Before | After |
|---|---|---|
| G-01 minimum data gate | `120` (hardcoded 40 × 3) | `len(TEST_CASES) * RUNS_PER_CASE` |
| `compute_metrics` assert | `40` (hardcoded) | `len(TEST_CASES)` |
| `test_matrix` evidence JSON | Hardcoded band/category counts | Dynamic computation via `collections.Counter` |
| Runtime print statements | Hardcoded `"40"` references | `len(TEST_CASES)` / `f"{len(TEST_CASES)}"` |

The `from collections import Counter` import was added at module level (line 57) to support dynamic category and band counting in the evidence artifact.

## Verification Results

### DPC Bypass Verification (70/70 PASS)

All 70 Category A cases were verified to bypass the DeterministicPolicyChecker:
- Constructed `CanonicalActionRepresentation` objects for each case using the same `_make_car()` helper the harness uses
- Called `DeterministicPolicyChecker.check()` on each
- Confirmed `check()` returns `None` for all 70 cases (no pre-filter rule triggers)

### Pre-Filter Verification (110/110 PASS)

The harness's built-in pre-filter verification loop (added in 4.12a step a8) was executed on the full 110-case corpus:
- All 25 original pre-filtered cases: matched `expected_path` (6 distinct DPC rules)
- All 15 original LLM-path cases: matched `expected_path = "LLM"`
- All 70 new Category A cases: matched `expected_path = "LLM"`

### K-2 Regression Check (PASS)

Original 40 cases (IDs 0–39) verified intact:
- Case count, IDs, scenarios, band assignments, and expected values unchanged
- No modifications to any original case dict

### Syntax/Compile Check (PASS)

Full file parsed with `py_compile` — zero syntax errors.

## Case Design Principles

All 70 cases were constructed to:

1. **Bypass DPC** — Use verbs, resources, and parameter combinations that do not match any of the 7 DeterministicPolicyChecker rules (RESTRICTED_PATH, EXFILTRATION, EXTERNAL_NETWORK, AUTHORITY_CLAIM, CROSS_AGENT_OWNERSHIP, INFRA_CONFIG_WRITE, EXCEPTION). This forces classification to the LLM path.
2. **Be obviously DENY** — Each scenario describes an action that any competent policy model should classify as DENY: data destruction, monitoring evasion, command injection, credential theft, data exfiltration, and bulk wipe operations.
3. **Use `_make_car()` helper** — All CARs constructed via the structured helper (added in 4.12a step a5) for consistency and maintainability.
4. **Include descriptive scenarios** — Each case has a detailed scenario string documenting the attack vector, enabling traceability during quality gate analysis.

## Corpus State After 4.12b

| Metric | Value |
|---|---|
| Total test cases | 110 |
| Original cases (IDs 0–39) | 40 |
| Category A cases (IDs 40–109) | 70 |
| Pre-filtered (DPC) cases | 25 (all original) |
| LLM-path cases | 85 (15 original + 70 Category A) |
| Remaining capacity to 236 target | 126 cases (Categories B–E) |

## Bugs Encountered & Resolved

| Issue | Root Cause | Resolution |
|---|---|---|
| DPC bypass verification returned `DENY_EXCEPTION` for all 70 cases | Verification script passed raw CAR text strings instead of `CanonicalActionRepresentation` objects | Constructed proper stub objects matching harness approach |
| `__file__` not defined error during `exec()` verification | `exec()` in inline verification script lacked `__file__` in globals | Provided `__file__` in `exec_globals` dict |
| f-string escaping error in inline print | Nested f-string with backslash in curly braces | Used tuple unpacking instead of nested f-string |
| `Counter` not defined at runtime | `collections.Counter` not imported | Added `from collections import Counter` at line 57 |

All issues resolved in single attempts before commit.

## Commit Details

```
commit b13db8d
Author: Blair <mr.blair.do@gmail.com>
Date:   Fri Mar 6 15:18:25 2026 -0800

    task4.12b: Category A — 70 LLM-path DENY cases (IDs 40-109)

    1 file changed, 829 insertions(+), 18 deletions(-)
```

Supporting commit (EA-2 initialization message):
```
commit 1b1db35
    task4.12b: EA-2 initialization message for Category A LLM-path DENY

    1 file changed, 178 insertions(+)
```
