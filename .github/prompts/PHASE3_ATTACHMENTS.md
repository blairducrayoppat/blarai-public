# Phase 3 New Chat – File Attachments

**Attach these files to the new Copilot chat in strict order:**

## Tier 1: System Context (Read First)

1. `.github/copilot-instructions.md`
   - **Why:** Contains Phase 3 directives, autonomy scope, security constraints
   - **Key section:** `<phase_directives>` → Phase_3 (contains mva_requirements)

2. `Use Cases_FINAL.md`
   - **Why:** canonical architecture lock; USE-CASE-004 describes Assistant Orchestrator
   - **Key sections:** [USE-CASE-004], [USE-CASE-001], [USE-CASE-005]
   - **Skip:** USE-CASE-009 (lower priority)

## Tier 2: Implementation Status (Context)

3. `docs/IMPLEMENTATION_PLAN.md`
   - **Why:** shows P1.0–P1.10 complete; where to add P1.11–P1.14
   - **Key sections:** Section 3 (P1.0–P1.10 status), Section 5 (template for new steps)

4. `docs/adrs/ADR-007-iGPU-Trust-Boundary-Software-Fallback.md`
   - **Why:** software fallback (vsock + mTLS); establishes trust posture for UI
   - **Key sections:** Consequences, Architectural Implications

## Tier 3: Backend Contracts (Integration)

5. `services/policy_agent/src/ipc.py`
   - **Why:** defines vsock protocol, mTLS handshake; UI gateway must implement client side
   - **Read:** Lines 1–50 (protocol), Lines 100–150 (mTLS ceremony)

6. `services/assistant_orchestrator/src/npu_inference.py`
   - **Why:** describes request/response contract for Orchestrator
   - **Read:** GenerationResult dataclass, generate() method signature, streaming behavior

7. `services/assistant_orchestrator/src/pgov.py`
   - **Why:** PGOV reason codes; UI must display these
   - **Read:** PGOVResult dataclass, validation pipeline (line comments)

## Tier 4: Test Evidence (Proof)

8. `tests/integration/test_p110_end_to_end.py`
   - **Why:** shows P1.10 complete; UI design must integrate with proven backend
   - **Read:** TestEndToEndPipeline class for full flow

---

**Total:** 8 files


**Attachment Order in New Chat:**
```
1. copilot-instructions.md
2. Use Cases_FINAL.md
3. IMPLEMENTATION_PLAN.md
4. ADR-007-iGPU-Trust-Boundary-Software-Fallback.md
5. services/policy_agent/src/ipc.py
6. services/assistant_orchestrator/src/npu_inference.py
7. services/assistant_orchestrator/src/pgov.py
8. tests/integration/test_p110_end_to_end.py
```

**Plus the bootstrap prompt:**
```
.github/prompts/phase3-ui-design-bootstrap.xml
```

Include this XML as the system prompt verbatim in the new Copilot chat.
