# EA-1 — Per-Boot mTLS Certificate Generation + ADR-026

> Sprint 15 (Tier-2 production-posture). Size: **M/L**. Depends on: `main`. **Sequenced BEFORE EA-2** — both edit `launcher/__main__.py` (shared working set), so EA-1 lands cert + wiring and EA-2 flips the default on top. Worktree-isolated builder under the Orchestrator merge gate. **Status: APPROVED for dispatch (LA, 2026-06-06).**

## Role

You are a **code-specialist** builder subagent working in an **isolated git worktree** off `main`. This is **BlarAI runtime code** — the absolute privacy mandate applies: **no external network calls, no new dependencies, fail-closed**. You are building Tier-2 production-posture security on the air-gap-removal campaign (gate #598). Strict type hints, PEP 8, deterministic.

## Objective

Build **per-boot ephemeral mutual-TLS (mTLS) certificate generation** for the host↔VM vsock channel: a certificate authority (CA) plus **fresh-per-boot** server+client certificate issuance and rotation, wired so the production posture (`dev_mode=false`) **auto-mints** fresh certs at startup with **zero manual steps** (supports SDV criterion #8 daily-driver continuity). Author **ADR-026**. Extend the existing fail-closed mTLS lock test.

## Background — disk-rooted pointers (read these first)

- `shared/ipc/vsock.py` — `VsockListener`, `create_server_ssl_context()` / `create_client_ssl_context()` (lines \~86-136), `VsockConfig` (carries `mtls_cert_path` / `mtls_key_path` / `ca_cert_path`). The mTLS code path is production-ready; you are feeding it real per-boot certs.
- `services/policy_agent/config/default.toml` `[ipc]` (lines 38-40) — `mtls_cert_path = "certs/pa_server.pem"`, `mtls_key_path = "certs/pa_server_key.pem"`, `ca_cert_path = "certs/ca.pem"`. These are the paths the production channel expects; today they are unprovisioned placeholders.
- `shared/tests/test_ipc_transport.py:366` — `test_transport_connect_no_mtls_production_fails` (the fail-closed lock you will **extend**); and `_generate_test_certs()` (\~line 50) — the `cryptography` self-signed test-cert helper to reuse.
- Pattern reference: `shared/security/provision_signing_key.py` — the per-chip, gitignored ceremony-artifact pattern (`certs/pa_public.pem`); ADR-021 (TPM-sealed JWT key). Mirror the "per-chip artifact, never committed, fail-closed" discipline.
- ADRs: ADR-018 (TPM trust root), ADR-020 (egress kill-switch — already armed), ADR-025 (at-rest, predecessor). ADR-023 is provenance — **not** relevant to certs.

## In-scope (deliverables)

1. **Per-boot cert generation module** (e.g. `shared/security/cert_provisioning.py`) using **`cryptography`** (already a project dep — **add no new dependencies**): create/load a CA, issue **fresh short-lived** server + client certs per boot for the vsock channel, support **rotation** (re-issue produces distinct certs). Fresh-per-boot, not long-lived.
2. **Wire auto-mint into the production-posture startup — at the named site.** The production wiring site is **`launcher/__main__.py` `main()`**: `_dev_mode` resolves at **:458** (after the interlock at :464-476), then the services + gateway that construct the vsock endpoints follow (PA \~:618, AO \~:684, gateway \~:778-791, all reading the `[ipc]` cert paths; note `gateway_port = … if gateway_dev_mode else 0` → production routes over vsock). Add a startup step **after the interlock (\~:476) and before service construction (\~:618)** that, when `_dev_mode is False`, mints the per-boot certs to the `[ipc]` paths. **You MUST first TRACE and CONFIRM the exact point where, at `dev_mode=false`, (a) the mint is invoked AND (b) the channel actually *consumes* the minted certs** (PA listener + gateway client → `VsockConfig` → `create_server_ssl_context`/`create_client_ssl_context` → handshake) — not "written to the paths and assumed read." Report that trace in your summary. Host-local path only; zero manual steps per boot (criterion #8).
3. **Extend `test_ipc_transport.py`** (the line-366 fail-closed lock) to cover **per-boot issuance + rotation**: a `CERT_REQUIRED` handshake **succeeds** with freshly-issued valid per-boot certs, **fails closed** with absent/expired/invalid certs, and **rotation yields distinct certs**. Keep the existing production-fail assertion intact.
4. **Author `docs/adrs/ADR-026-Per-Boot-mTLS-Ephemeral-Certificates.md`** (BlarAI namespace, next free number): the decision, the design (CA + per-boot issuance + rotation + cert lifetime), the **fidelity-2** verification posture (host-local real mTLS), and a **Known Limitation** section: Sprint-15 per-boot certs are **fresh-per-boot but NOT measured-image-CN-bound** (FUT-02's full vision, deferred with measured-boot) — *freshness proven, issuer-attestation not*. Cite ADR-021/018/020/025.

## Out-of-scope (do NOT do — owned elsewhere)

- The dev-mode-off flip (**EA-2**); the precondition cascade / minimal manifest (**EA-3**); the on-chip ceremony + live-verify (**EA-4**).
- The **guest↔host AF_HYPERV boundary** handshake — deferred, tracked **#615**. You build + verify **host-local only**; do not claim or attempt the guest boundary.
- Pluton-sealing the CA key / measured-image CN binding (FUT-01/FUT-02 full vision); cert **revocation/epoch** (FUT-03 #105 — build issuance now, not revocation).
- Any service relocation into the VM.

## Design constraints & safety

- **No external network. No new dependencies** (`cryptography` only). **Fail-closed** on any cert/handshake error.
- **Never print, log, or persist private key / cert private material** to a transcript or to git. Any CA private key that must persist is a **per-chip, gitignored** artifact (mirror `pa_public.pem`); prefer in-memory per-boot generation where possible.
- **Crypto floor (don't invent crypto):** ECDSA **P-256** (mirror `_generate_test_certs` + `tpm_signer`) or RSA-2048+; a **short per-boot lifetime** (record the chosen value in ADR-026); **CN/SAN per service identity** (PA server; gateway/AO client); **`CERT_REQUIRED` in both directions**.
- **fidelity-2 discipline (sharpened):** verify over the **real** mTLS code path — production SSL contexts + `CERT_REQUIRED` + real per-boot certs. A **local socket transport is fine** — real mTLS over loopback IS fidelity-2; what is forbidden is the **dev-mode path that SKIPS mTLS**. The guest↔host AF_HYPERV boundary stays out of scope (#615). Claim only what host-local exercises (SDV Condition 2).
- **Test isolation (standing rule):** run the suite with the venv `C:/Users/mrbla/blarai/.venv/Scripts/python.exe -m pytest`; tests inherit the root `conftest.py` isolation (LOCALAPPDATA/HOME/XDG redirect) — **do not bypass it**, do not point any path at the real user-data dir or real keystore; use temp dirs + the `_generate_test_certs()` helper.

## Acceptance criteria (maps to SDV §4)

- Criterion **#1**: per-boot cert generation exists and is exercised; the extended `test_ipc_transport.py` lock is **green**; new issuance + rotation unit tests **green**; no suite regression. **Production-wiring regression lock (lesson-46 teeth):** a test asserting the `dev_mode=false` **startup path** actually **mints AND consumes** the per-boot certs (the channel is constructed with the minted cert material / a non-None production mTLS context) — distinct from the handshake unit test, so a "built into nothing" wiring gap fails the gate.
- Criterion **#6**: `docs/adrs/ADR-026-*.md` on the branch, with the Known-Limitation (freshness-not-attestation) section present.
- Contributes the cert machinery the EA-4 fidelity-2 live-verify depends on.

## Process

- **Pre-build comprehension gate (FIRST — before writing any crypto):** trace the production wiring site (in-scope #2) and **recite** the exact wiring line + your full working set (expected: `launcher/__main__.py`, new `shared/security/cert_provisioning.py`, `shared/tests/test_ipc_transport.py`, `docs/adrs/ADR-026-*.md`). If the real wiring site differs from the named `launcher/__main__.py` site, or your working set would collide with EA-2's launcher edits beyond the planned mint step, **STOP and report** before writing crypto. If it matches, proceed. (Pre-build complement to the merge gate — catches a mis-wire before the build, not after.)
- Work in an isolated worktree off `main`. Make atomic, reviewable commits.
- On completion, write a **journal fragment** `docs/journal_fragments/2026-06-06_s15-ea1-per-boot-mtls.md` (dated `###` header + first-person narrative + `**Next:**`; add a `**Proposed lesson:**` block if one was earned).
- Return a structured summary (what changed, file:line of the new module + the extended test, the ADR path, test results, anything that surfaced) for the **Orchestrator merge-gate** review before merge to `main`.
