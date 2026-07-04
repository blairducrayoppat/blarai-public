---
ledger_id: 20260616_182807_uc010_content-attestation
date: 2026-06-16
sprint_id: null
entry_type: OTHER
predecessor: 20260616_161934_uc010_local-generative-imaging
branch: main
merge_commit: null
disposition: COMPLETE
---

# UC-010 — One-Time Operator Content-Safety Attestation (go-live ceremony Step 3)

## Summary

This records the **one-time operator content-safety attestation** required by ADR-033
§Content safety (go-live runbook `docs/runbooks/uc010_image_gen_go_live.md`, Step 3) before
`[image_generation].enabled` is set true. It is the governance gate: content safety for
UC-010 is **governance + this attestation, NOT a classifier** (Lead Architect decision
2026-06-15). The technical go-live prerequisites are complete and verified — the nested SDXL
weight manifest is staged (19 entries: `.bin` + `.xml` + `model_index.json`), TPM-signed
(`manifest.json.sig` + `.pub`, the `BlarAI-Manifest-Signing` key), and passes
`verify_all_manifest_entries_nested(..., require_signed=True)` → **VERIFIED** (confirmed
independently by both the operator and the Guide). With this attestation on the record, the
ceremony is clear for Step 4 (the `enabled=true` flip) and Step 5 (live GPU verify).

## Attestation (operator-adopted, verbatim)

**Date:** 2026-06-16 · **Operator:** Blair (Lead Architect, sole operator)
**Capability:** UC-010 local image generation (text→image + img2img), uncensored SDXL-INT8
(RealVisXL V5.0) on the Arc 140V — local-only, zero network egress, display-only,
born-encrypted at rest, DELETE-on-discard.

As the sole operator of this private, air-gapped system, I attest that:

1. I have **deliberately** chosen an uncensored generation model with **no content
   classifier and no prompt inspection** (ADR-033 §Content safety; decision 2026-06-15).
   Content safety for UC-010 is governance + this attestation, not a technical filter — a
   classifier was considered and rejected as ineffective locally, memory-costly, and
   privacy-invasive.
2. The capability is uncensored for all **legal** content. The one boundary no technical
   control here enforces — and that no local control can robustly enforce — is the
   **legality of what is generated or possessed** (CSAM being the absolute, unambiguous
   example; other categories jurisdiction-dependent).
3. I understand that this legal boundary rests **solely on my discipline as the operator**,
   and I accept **sole legal responsibility** for everything generated with this
   capability. This is a deliberate accepted-risk.
4. The residual is mitigated — not eliminated — by the capability being operator-initiated,
   audited, egress-incapable, and non-distributing (born-encrypted, display-only, never
   shared or exported). These reduce third-party-harm vectors; they do **not** mitigate the
   legality-of-creation boundary, which is mine alone.
5. This is the one-time go-live gate required by ADR-033 before `[image_generation].enabled`
   is set true. It is to be revisited if any share / export / distribution capability is
   ever added.

## Cross-references

- ADR-033 §Content safety (the locked posture); `docs/DECISION_REGISTER.md` ADR-033 row.
- Go-live runbook `docs/runbooks/uc010_image_gen_go_live.md` (Step 3).
- Build ledger `20260616_161934_uc010_local-generative-imaging`; go-live-prereqs merge `f6611f8`.
- Resolve-grain posture (the prior open go-live decision): ADR-033 §Display, recorded 2026-06-16.
