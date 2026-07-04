# Task 4.12d — EA-4 Execution Summary

**Date:** 2026-03-06  
**Branch:** `feature/p5-task4-12-corpus-hardening`  
**Commit:** `bcd6a66`  
**Predecessor:** `b8054a5` (180 cases, IDs 0–179)  
**File Modified:** `phase2_gates/scripts/run_p5_task4_9_pa_quality_gate.py`

---

## Objective

Add 48 test cases (IDs 180–227) to the PA Classification Quality Gate harness spanning three new categories:

| Category | Count | Expected | Expected Path | Purpose |
|----------|-------|----------|---------------|---------|
| C | 24 | DENY | DENY_AUTHORITY_CLAIM | Rule 4 regex validation — all 5 branches |
| D | 12 | ALLOW | LLM | Boundary ALLOW — DPC bypass, LLM classifies |
| E | 12 | ESCALATE | LLM | Boundary ESCALATE — DPC bypass, LLM classifies |

---

## Category C — DENY_AUTHORITY_CLAIM (IDs 180–203)

All 5 branches of the `_AUTHORITY_CLAIM_RE` regex from `gpu_inference.py` line 253 covered:

| Branch | Regex Pattern | Cases | IDs |
|--------|--------------|-------|-----|
| B1 | `pre-approved` | 5 | 180–184 |
| B2 | `pre_approved(?!_)` | 5 | 185–189 |
| B3 | `security.{0,5}team.{0,10}author` | 5 | 190–194 |
| B4 | `authorization.{0,10}bypass` | 5 | 195–199 |
| B5 | `bypass.{0,10}author` | 4 | 200–203 |

Includes case-insensitive variants (ID 193 uppercase, ID 199 uppercase), hyphenated forms (ID 191), and boundary gap tests (ID 192 max gap1=5, ID 194 gap1=5+gap2=4).

## Category D — Boundary ALLOW (IDs 204–215)

6 types × 2 cases. All bypass DPC (`check()` returns `None`), LLM expected to classify ALLOW:

| Type | Description | IDs |
|------|-------------|-----|
| D-1 | HIGH sensitivity shared-path READs | 204, 205 |
| D-2 | Large writes below 100MB threshold | 206, 207 |
| D-3 | Cross-agent READs (public exports) | 208, 209 |
| D-4 | Near-restricted prefixes (`/processing/`, `/systemd/`) | 210, 211 |
| D-5 | Auth-adjacent words NOT matching Rule 4 | 212, 213 |
| D-6 | Benign security vocabulary (audit, compliance) | 214, 215 |

## Category E — Boundary ESCALATE (IDs 216–227)

6 types × 2 cases. All bypass DPC (`check()` returns `None`), LLM expected to classify ESCALATE:

| Type | Description | SYSTEM_PROMPT Criterion | IDs |
|------|-------------|------------------------|-----|
| E-1 | Implicit cross-agent WRITE | (c) | 216, 217 |
| E-2 | Writes exceeding 100MB | (e) | 218, 219 |
| E-3 | Cert-adjacent ops on non-`/certs/` paths | (d) | 220, 221 |
| E-4 | `/internal/` infrastructure READs | (d) | 222, 223 |
| E-5 | Multi-agent coordination, ambiguous auth | (a) | 224, 225 |
| E-6 | Cryptographic material on non-`/certs/` paths | (d) | 226, 227 |

---

## Lead Architect Advisories Applied

1. **D-5 word diversity:** Case 212 uses "authorized", Case 213 uses "approved" + "validated" (not both "authorized").
2. **Path diversity:** Resources distributed across `/shared/`, `/opt/`, `/workspace/`, `/home/user/` in all three categories (not clustered on `/shared/blarai/`).

---

## Verification Gates

| Gate | Result |
|------|--------|
| AST parse | PASS |
| Pre-filter (48/48) | Cat C: 24/24 trigger Rule 4; Cat D: 12/12 return None; Cat E: 12/12 return None |
| ID continuity | 0–227 contiguous, no gaps, no duplicates |
| Total cases | 228 |
| Verdict distribution | ALLOW=24, DENY=166, ESCALATE=38 |
| K-7 band targets | C: 6/6/6/6, D: 3/3/3/3, E: 3/3/3/3 across 512/1024/2048/4096 |

---

## Corpus State at Close

| Metric | Before (EA-3) | After (EA-4) | Delta |
|--------|---------------|--------------|-------|
| Total cases | 180 | 228 | +48 |
| ALLOW | 12 | 24 | +12 |
| DENY | 142 | 166 | +24 |
| ESCALATE | 26 | 38 | +12 |
| Categories | A, B (+ uncategorized originals) | A, B, C, D, E (+ originals) | +3 |
