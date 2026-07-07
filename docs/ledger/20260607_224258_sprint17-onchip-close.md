# Sprint-17 "The Boot Cluster" — on-chip session close

- **Date:** 2026-06-07 22:42 local (2026-06-08T05:42Z)
- **Type:** Hardware-tier verification + FUT-04 ceremony (on-chip)
- **Disposition:** All runnable tiers **GREEN**; C1 design-proven, deployment round-trip **PENDING** (tracked #615)
- **Supersedes-status-of:** `docs/ledger/20260607_180000_sprint17_scr_boot-cluster-close.md` (build-close, which recorded the hardware tiers as deferred/PENDING)
- **Gate:** `2342 passed / 0 failed / 108 deselected` on the standing selection (re-run after every on-chip merge)

## Tiers — final status

| Tier | Criterion | Result |
|---|---|---|
| **C7 / #106** | FUT-04 signed-manifest enforcement | **DONE** — ceremony + flip + signature-verified + gate-green + real boot cleared the manifest gate |
| **C8a** | Boot-cascade smoke, real model | **GREEN** (model-path fix; 1 passed 67s) |
| **C8b / #621** | WinUI GUI harness | **GREEN** — 13/13 critical-path + 2/2 model-loaded |
| **C2** | Model-loaded production boot cascade | **GREEN** — cert-location fix; full real cascade (PA+TPM+model+mTLS+prompt) 1 passed 68.5s; proven test-tier |
| **C4** | Real-TPM security cascade (GAP-7) | **GREEN** — re-verified 1.2s + evidence captured (closes SWAGR MINOR-2) |
| **C1 / #615** | Guest-boundary AF_HYPERV round-trip | **DESIGN-PROVEN here; PENDING** the deployment round-trip (≥3.12 runtime + Alpine responder; tracked #615) |

## C7 / FUT-04 — LOUD (governance posture change, now live)

- `require_signed_manifest = true` is **LIVE** in BOTH service configs (`policy_agent` + `assistant_orchestrator`). Production **fails closed** if the weight manifest is not validly signed.
- 4th TPM key **`BlarAI-Manifest-Signing`** provisioned (non-exportable, in-chip). Trust anchor (SPKI DER SHA-256): `508defe5c27c0f0f7e5477cb033180f6dad1de6c076b32ff8b015923137b5ae4`.
- The manifest **is** signed and verifies under enforcement; the flip **un-skipped 2 signed-manifest gate tests** that now pass; the real production boot cleared the gate.
- **Reversible** by one line. #106 boot-enforcement satisfied; runtime re-verification + CoW criteria left for the LA to confirm in/out of #106 scope.

## Findings recorded this session

- **#615 over-escalation withdrawn (corrected on the ticket, comment 925):** `connect(): bad family` was a Python-version gap (venv 3.11.9 lacks `socket.AF_HYPERV`; system 3.14 has it and dials). Phase-2 `vsock_validation.json` proves the real round-trip; the gateway is OpenVINO-free so it runs ≥3.12 cleanly. The earlier "ctypes rewrite / #598 re-scope" framing is **withdrawn**. Fail-silent probe defect fixed (now refuses to claim guest-mode loudly).
- **C2 mTLS failure proven test-tier:** the model-loaded tier minted certs in tmp while the real PA read shipped `certs/`; not a real mTLS gap (stubbed tier's identical handshake passes). Fixed.
- **MINOR-2 closed:** real-TPM cascade independently re-verified + evidence at `docs/sprints/sprint_17/evidence/`.

## Commits

- `09c62b1` — FUT-04 ceremony+flip (closes #106 boot-enforcement) + C8a model-path + C1 honest-detection
- `f4bdea4` — C2 cert-location fix (green) + C4 real-TPM evidence (MINOR-2)
- `d3fe427` — #621 GUI harness 13/13 (banner-text anchor); GUI rounds at `9429c57`/`2105627`/`6e5958a`

## Pointers

- SCR: `docs/sprints/sprint_17/strategic_completion_report.md` (on-chip addendum)
- Journal: `docs/journal_fragments/2026-06-07_sprint17-onchip-close.md` + `…_gui-harness-621-fixes.md`
- Evidence: `docs/sprints/sprint_17/evidence/c4_real_tpm_cascade_{evidence.json,run.log}`
- Tickets: #106 (comment 926), #615 (comment 925), #628 (tracker)
