# EA-3 — Precondition Cascade + Off-Chip Stub Harness + Substrate Ratify

> Sprint 15 (Tier-2 production-posture). Size: **M**. Depends on: **EA-1 merged** (uses the per-boot certs + the `dev_mode=false` cascade). Branch off **current `main`** (EA-1 + EA-2 both merged, `a7c9eeb`). Worktree-isolated; same independent merge-gate. **Status: APPROVED for dispatch (LA, 2026-06-06) — clarifications folded.**

## Why

The dev-mode-off flip (EA-2 mechanism → EA-4 activation) makes the Policy Agent refuse-to-start at `dev_mode=false` unless the precondition cascade is satisfied: a Known-Good Manifest must **exist** (`entrypoint.py:773` `if dev_mode: return` / `:781` `PA_CFG_KGM_PATH_NOT_FOUND`), and `jwt.tpm_key_name` + `jwt.ca_cert_path` must resolve (`:737-749`). EA-3 stages the **minimal** pieces so the production boot is satisfiable, and builds an **off-chip stub-signer harness** that proves the full `dev_mode=false` cascade green **before** the LA's on-chip session — narrowing on-chip surprises to the real-TPM-key signing.

## Role

code-specialist, isolated worktree, BlarAI runtime (no external network, no new deps, fail-closed), strict type hints, PEP 8.

## Background — disk-rooted pointers

- `services/policy_agent/src/entrypoint.py:717-749` — config-validation: at `dev_mode=false`, `inference.weight_manifest` + `jwt.tpm_key_name` + `jwt.ca_cert_path` required; `:763-792` — `_validate_security_material`: KGM path must **exist** + `load_manifest_verified` (`require_signed_manifest` default **false**).
- `services/policy_agent/config/default.toml:15` (weight_manifest path), `:31-32` (jwt.tpm_key_name + ca_cert_path).
- `shared/security/audit_log.py` (`HmacSha256Signer` stub vs `TpmRecordSigner`); `services/policy_agent/src/jwt_minter.py` (ephemeral dev key vs `from_tpm`) — the stub signers are the off-chip path.
- `services/assistant_orchestrator/src/entrypoint.py:1007-1108` — the substrate graceful-degradation posture; the misleading comment at `:1012-1014`.

## In-scope (deliverables)

1. **Stage a MINIMAL, STUB-DIGEST Known-Good Manifest** — just enough that PA config-validation + `_validate_security_material` pass at `dev_mode=false` in the **off-chip** harness. The KGM check requires a valid 64-hex SHA-256 digest **keyed by the model binary's filename** (`entrypoint.py:794-808` → `PA_CFG_KGM_MODEL_DIGEST_MISSING` / `_DIGEST_INVALID`). The off-chip builder has **no real Qwen3-14B weights**, so stage a **dummy model file + its (dummy) digest** — this de-risks the cascade **STRUCTURE** (manifest format, digest-keyed-by-filename, the validation flow end-to-end), **NOT** the real-model-digest match. **NOT full FUT-04** (no `require_signed_manifest=true`, no all-weights integrity — that is #106). Clearly label the staged manifest as the harness's **stub-digest placeholder**; the **real Qwen3-14B-digest manifest is EA-4 ceremony-prep** (see Out-of-scope).
2. **Resolve the JWT cert/key config paths** (`jwt.tpm_key_name` + `jwt.ca_cert_path`) so config-validation passes at `dev_mode=false`. The actual TPM key is provisioned by EA-4's ceremony; EA-3 ensures the **config + paths resolve** (no premature key creation).
3. **Off-chip stub-signer cascade harness** — a test/harness that runs the full `dev_mode=false` PA boot cascade **off-chip** using stub signers (`HmacSha256Signer` for audit, ephemeral ECDSA for JWT) + the staged minimal manifest, proving the cascade is green (config-validation + `_validate_security_material` + adjudicator build) **without a TPM**. De-risks the cascade before the LA's on-chip session.
4. **Substrate micro-item (ratify + comment fix)** — keep the graceful-degradation posture (confirmed fail-closed: production + missing keystore refuses the weak sealer + disables substrate memory loudly, `entrypoint.py:1090-1105`); **tighten the misleading comment at `:1012-1014`** ("symmetric with `build_session_store`" — symmetric in *refusing the weak sealer*, asymmetric in *halt-vs-degrade*). No behavior change.

## Out-of-scope

- **Full FUT-04** (`require_signed_manifest=true` + all-weights integrity) — #106.
- **The REAL production-model-digest manifest** (compute the actual Qwen3-14B SHA-256 + stage/finalize the real-digest minimal manifest) — **EA-4 ceremony-prep** (needs the LA's real weights; the off-chip builder can only stage a stub digest). Recorded on #616.
- The per-boot certs (EA-1, merged); the dev-mode flip mechanism (EA-2); the on-chip ceremony + activation + live-verify (EA-4).
- Do NOT run any on-chip ceremony, provision any TPM key, or flip the running default.

## Working set & sequencing

Edits: `services/policy_agent/config/` (manifest + jwt paths), `models/` (the minimal manifest artifact), a new harness under `tests/`/`shared/tests/`, and `services/assistant_orchestrator/src/entrypoint.py` (the `:1012-1014` comment **only**). **Branch off current `main` (`a7c9eeb`, EA-1 + EA-2 merged).** (Disjoint from the now-merged EA-2 — no live parallelism concern.)

## Design constraints & safety

- No new dependencies, fail-closed, typed.
- **CRITICAL isolation (EA-3 merge-gate guard, #616):** the stub harness boots PA at `dev_mode=false`; it MUST inherit the root `conftest.py` isolation (LOCALAPPDATA/HOME/XDG redirect) and MUST NOT re-point `BLARAI_DEK_KEYSTORE` at a real keystore "to exercise the cascade." Keep it on stub signers + a **temp** keystore so it cannot touch the real `sessions.db` / `substrate.db` / real keystore. **This is a reject-the-merge condition.**
- Run tests with the venv: `C:/Users/mrbla/blarai/.venv/Scripts/python.exe -m pytest`.

## Acceptance criteria (maps to SDV v4 §4)

- **Criterion #3:** a minimal KGM staged + the jwt paths resolve → PA config-validation + `_validate_security_material` pass at `dev_mode=false` in the off-chip stub-signer harness (green); explicitly **not** full FUT-04. Substrate posture ratified + the `:1012-1014` comment tightened.

## Process

- **Pre-build comprehension gate (FIRST — before building):** recite (a) your isolation approach — how the harness inherits the root `conftest.py` redirect + uses **stub signers + a temp keystore**, never the real `BLARAI_DEK_KEYSTORE` / real data dir; and (b) the minimal **stub-digest** manifest content (dummy model file + dummy digest). If your approach would touch a real keystore / data dir, or stage a non-stub (real) digest, **STOP and report** before building. (Front-loads the reject-the-merge isolation check, consistent with EA-1.)
- Branch off **current `main`** (`a7c9eeb`), isolated worktree, atomic commits.
- Journal fragment `docs/journal_fragments/2026-06-06_s15-ea3-cascade-stub-harness.md` (dated `###` + narrative + `**Next:**`; `**Proposed lesson:**` if earned).
- Return a structured summary for the Orchestrator merge-gate — expect scrutiny on the **isolation guard** (no real keystore touched) and that the manifest is **minimal** (not FUT-04).
