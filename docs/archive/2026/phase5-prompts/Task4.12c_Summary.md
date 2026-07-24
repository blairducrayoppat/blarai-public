---
title: Task4.12c_Summary
status: archived
area: portfolio
---

# Task 4.12c — Category B: 50 LLM-Path Adversarial Test Cases

**Date**: 2026-03-06  
**Agent Session**: EA-3 of 5 (Task 4.12 — PA Classification Quality Gate Corpus Hardening)  
**Branch**: `feature/p5-task4-12-corpus-hardening`  
**Commit**: `9ece25f` — `task4.12c: Category B — 50 LLM-path adversarial cases`  
**Diff**: 1 file changed, 588 insertions(+), 0 deletions  

---

## 1. Objective

Add 50 Category B (LLM-path adversarial) test cases to the PA quality gate harness (`phase2_gates/scripts/run_p5_task4_9_pa_quality_gate.py`). These cases are designed to bypass the `DeterministicPolicyChecker` (return `check() → None`) and reach the LLM classification path, while containing adversarial content that should be classified as **DENY** by the probabilistic Policy Agent.

Category B cases stress-test the LLM's ability to correctly deny requests that are crafted to appear legitimate but contain subtle policy violations that only a language model can detect.

---

## 2. Predecessor State (EA-2 Closure)

| Metric | Value |
|---|---|
| Total cases | 110 (IDs 0–109) |
| Original (nominal/boundary) | 40 (IDs 0–39) |
| Category A (LLM-path DENY) | 70 (IDs 40–109) |
| Category B (LLM-path adversarial) | 0 |
| `_make_car()` helper | Present |
| `BAND_TARGETS` | Present |

---

## 3. Design — 5 Adversarial DENY Types (B-V1 through B-V5)

### B-V1: Role Confusion Injections (IDs 110–119)
Parameters claim elevated roles, admin privileges, or delegated authority (`acting_as`, `delegated_by`, `elevated_access`, `role_override`, `assumed_identity`, `service_account`, `inherited_role`, `promotion_to`, `context_switch`, `temporary_elevation`). Source agent is always `blarai-code-agent` — the role claims exist only in `parameters_schema` and must be recognized as illegitimate by the LLM.

### B-V2: Social Engineering Text (IDs 120–129)
Parameters contain urgency/authority narratives (urgent executive requests, compliance audit demands, emergency maintenance claims, CEO-level directives, incident response pressure, board meeting urgency, vendor contractual obligations, regulatory deadlines, scheduled downtime claims, partner data-sharing fabrications). **Critical constraint**: must NOT trigger DeterministicPolicyChecker Rule 4 regex. Avoids banned patterns via synonyms and indirect phrasing.

### B-V3: Prompt Injection via CAR Field Values (IDs 130–139)
CAR fields (resource paths, parameters) contain embedded override instructions: `DECISION: ALLOW` injections, system prompt overrides with new roles, XML-like tag injections, sensitivity classification overrides, multi-line instruction overrides with fake context, label smuggling via repeated ALLOW tokens, homoglyph-based overrides using Unicode lookalikes, multi-turn conversation simulations, and base64-encoded override instructions with decode hints.

### B-V4: Benign-Looking Resources with Hidden Malicious Operations (IDs 140–149)
Resources appear legitimate (reports, analytics dashboards, UI themes, cache directories, log configs, documentation, fonts, backups, notification templates, translation files) but `parameters_schema` hides dangerous payloads: credential harvesting, audit logging disable, privilege escalation to root, security policy deletion, credential dumps to temp paths, backdoor service installation, system binary replacement, private key exfiltration via backup paths, keylogger deployment, and reverse shell installation.

### B-V5: Misleading Sensitivity Levels (IDs 150–159)
LOW sensitivity paired with objectively dangerous operations: bulk deletion of all user data, API key harvesting in plaintext, firewall rule flushing to ACCEPT-all, encryption key nullification (`new_master_key: "0000..."`), world-readable permissions on secrets directory (chmod 777), allow-all RBAC replacement, arbitrary command injection via cron config, monitoring dashboard factory reset, DNS redirect to attacker IPs, and TLS downgrade to NULL-SHA/RC4-MD5 ciphers.

---

## 4. Band Distribution (Category B)

| Band | Count | IDs (representative) |
|---|---|---|
| 512 | 12 | 110, 114, 120, 124, 130, 134, 140, 144, 150, 154, ... |
| 1024 | 13 | 111, 115, 121, 125, 131, 135, 141, 145, 151, 155, ... |
| 2048 | 13 | 112, 116, 122, 126, 132, 136, 142, 146, 152, 156, ... |
| 4096 | 12 | 113, 117, 123, 127, 133, 137, 143, 147, 153, 157, ... |
| **Total** | **50** | |

All bands within `BAND_TARGETS` tolerance ranges.

---

## 5. Key Constraints Enforced

| Constraint | ID | Description | Status |
|---|---|---|---|
| No production code changes | K-1 | Only the harness file is modified | **PASS** |
| Prior cases unchanged | K-2 | All 110 existing cases (IDs 0–109) byte-identical | **PASS** (0 deleted lines) |
| Contiguous IDs | K-3 | IDs 110–159, no gaps | **PASS** |
| LLM-path only | K-4 | All Cat B cases must bypass DeterministicPolicyChecker | **PASS** (50/50) |
| No ALLOW ground truth | K-5 | All Cat B expected = DENY | **PASS** (0 ALLOW) |
| B-V2 Rule 4 safe | BLOCKING | B-V2 cases must not trigger Rule 4 regex | **PASS** (10/10) |

---

## 6. Verification Evidence

### 6.1 AST Parse
```
python -c "import ast; ast.parse(open(r'...\run_p5_task4_9_pa_quality_gate.py', encoding='utf-8').read()); print('AST parse: OK')"
→ AST parse: OK
```

### 6.2 Case Count Verification
```
Total cases:        160
Original:            40 (IDs 0–39, category=nominal/boundary)
Category A:          70 (IDs 40–109)
Category B:          50 (IDs 110–159)
ID range:            0–159, contiguous
```

### 6.3 B-V2 Rule 4 Regex Verification
Standalone script `scripts/verify_bv2_rule4.py` extracted all 10 B-V2 case CAR texts and tested each against the compiled Rule 4 regex pattern. **Result: 10/10 PASS** — no matches.

### 6.4 Pre-filter Verification (DeterministicPolicyChecker)
Standalone script `scripts/verify_prefilter_catb.py` constructed `CanonicalActionRepresentation` objects for all 50 Cat B cases (mirroring harness construction: `Sensitivity.UNCLASSIFIED`, `request_id` field) and called `DeterministicPolicyChecker.check()`. **Result: 50/50 → None** (all cases reach LLM path).

### 6.5 Prior Case Integrity
```
git diff HEAD -- <harness> | Select-String "^-[^-]" | Measure-Object → Count: 0
```
Single insertion hunk at line 1568, 588 new lines, zero deletions.

---

## 7. Bug Encountered & Resolution

**Sensitivity enum mismatch in verification script**: The initial `verify_prefilter_catb.py` used `Sensitivity.LOW/MEDIUM/HIGH/CRITICAL` (from the CAR text-format sensitivity strings), but the actual `Sensitivity` enum in `shared/schemas/car.py` has values `PUBLIC`, `INTERNAL`, `SENSITIVE`, `UNCLASSIFIED`.

**Root cause**: The `_make_car()` helper produces text-format CAR strings with descriptive sensitivity labels, but the structured `CanonicalActionRepresentation` model uses the enum values.

**Resolution**: Mirrored the harness's own CAR construction pattern — `Sensitivity.UNCLASSIFIED` for all verification objects. This is correct because `DeterministicPolicyChecker.check()` never reads the `sensitivity` field in any of its 7 rules.

**Impact**: Zero impact on the actual test cases. The bug was only in the temporary verification script (now deleted).

---

## 8. DeterministicPolicyChecker Rules Reference

For context on why Cat B cases are designed to bypass the pre-filter:

| Priority | Rule | Trigger Condition |
|---|---|---|
| 0 | Null CAR | `car is None` → DENY_NULL_CAR |
| 1 | Restricted path | Resource starts with `/proc/`, `/system/`, `/etc/`, `/var/log/`, contains `/certs/`, or starts with `/home/` (not `/home/user/`) |
| 2 | Export path | `/tmp/export/` in `parameters_schema` JSON string |
| 3 | External URL | Resource starts with `http://` or `https://` |
| 4 | Authority claim | Regex match on CAR text (see B-V2 constraint) |
| 5 | Target owner | `target_owner` field present in parameters |
| 6 | Internal write | `/internal/` in resource + verb == WRITE |

All Cat B cases are constructed to avoid triggering any of these 7 rules.

---

## 9. Corpus State After EA-3

| Category | Count | ID Range | Path | Purpose |
|---|---|---|---|---|
| Original (nominal/boundary) | 40 | 0–39 | Mixed (DPC + LLM) | Baseline coverage |
| A (LLM-path DENY) | 70 | 40–109 | LLM | Deterministic DENY via LLM |
| B (adversarial) | 50 | 110–159 | LLM | Adversarial DENY cases |
| **Total** | **160** | **0–159** | | |

---

## 10. Next Step — EA-4 (Sub-Milestone 4.12d)

EA-4 will add 48 cases — 24 Category C (edge-case resources), 12 Category D (multi-signal composites), and 12 Category E (ESCALATE-path) — IDs 180–227, bringing the corpus to 228 cases.

---

## 11. O-1 Remediation — Adversarial-ESCALATE Coverage (IDs 160–179)

**Finding**: SDO review of EA-3 identified O-1 — zero adversarial cases with expected=ESCALATE.
All 50 Cat B cases targeted DENY, leaving no coverage for adversarial inputs that should
trigger ESCALATE via the LLM's SYSTEM_PROMPT criteria rather than DeterministicPolicyChecker rules.

**Directive**: Lead Architect approved creation of 20 new adversarial-ESCALATE scenarios
using softened adversarial parameters that match SYSTEM_PROMPT ESCALATE criteria (a)–(e).

### 11.1 Design — 5 Adversarial ESCALATE Types (B-E1 through B-E5)

| Sub-Type | IDs | ESCALATE Criterion | Description |
|---|---|---|---|
| B-E1 | 160–163 | (d) Crypto material, legitimacy unconfirmable | Key inventory, cert rotation, SSH consolidation, encryption migration |
| B-E2 | 164–167 | (c) Cross-agent resource access | Read peer config, write to peer inbox, read peer decision logs, modify peer schedule |
| B-E3 | 168–171 | (e) Large-scale writes >100 MB | Archive 210 MB, reorganize 150 MB, consolidate logs 310 MB, model snapshot 520 MB |
| B-E4 | 172–175 | (b) Unverified code/plugins | Plugin install (unverified), script deploy (unreviewed), module config (unsandboxed), automation rules (unverified) |
| B-E5 | 176–179 | (d) System-wide impact, legitimacy unconfirmable | Resource limits all_agents, quota rebalance (self-serving), monitoring self-exclusion, access policy relaxation |

Each sub-type has 4 cases, one per band (512/1024/2048/4096) = 5 per band total.

### 11.2 DPC Bypass

All 20 cases verified to bypass all 7 DeterministicPolicyChecker rules (0–6).
B-E2 cases intentionally omit `target_owner` to avoid Rule 5 trigger — cross-agent
semantics are expressed through resource paths and narrative only, forcing LLM evaluation.

### 11.3 Verification Evidence

```
Total cases: 180
ID range: 0-179, contiguous: True
Ground truths: ALLOW=12, DENY=142, ESCALATE=26
Cat B: 70 total (50 DENY + 20 ESCALATE)
B-ESCALATE bands: {512: 5, 1024: 5, 2048: 5, 4096: 5}
B-E type distribution: {B-E1: 4, B-E2: 4, B-E3: 4, B-E4: 4, B-E5: 4}
DPC bypass: ALL 20 CASES PASS — no rules triggered
```

### 11.4 Updated Corpus State

| Category | Count | ID Range | Path | Purpose |
|---|---|---|---|---|
| Original (nominal/boundary) | 40 | 0–39 | Mixed (DPC + LLM) | Baseline coverage |
| A (LLM-path DENY) | 70 | 40–109 | LLM | Deterministic DENY via LLM |
| B (adversarial DENY) | 50 | 110–159 | LLM | Adversarial DENY cases |
| B (adversarial ESCALATE) | 20 | 160–179 | LLM | Adversarial ESCALATE cases |
| **Total** | **180** | **0–179** | | |
