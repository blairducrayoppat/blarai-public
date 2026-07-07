# EA-2 — Dev-Mode-Off Flip MECHANISM (activation deferred to EA-4)

> Sprint 15 (Tier-2 production-posture). Size: **S/M**. Depends on: **EA-1 merged** (shares `launcher/__main__.py`). **Scope: build the flip MECHANISM only — do NOT change the shipped running default; it stays dev all sprint. The live default flip is EA-4's final step, after EA-3's manifest + the ceremony's keys.** Worktree-isolated builder; the same independent post-build merge-gate that caught EA-1's double-mint applies here. **Status: DRAFT — pending LA re-scope approval + SDV v4.**

## Why mechanism-only (read this FIRST)

At `dev_mode=false` the Policy Agent **refuses to start** without a staged Known-Good Manifest (`services/policy_agent/src/entrypoint.py:773` `if dev_mode: return` + `:781` `PA_CFG_KGM_PATH_NOT_FOUND`) and breaks adjudication without the provisioned JWT TPM key. The manifest is staged in **EA-3**; the JWT key is provisioned in **EA-4's ceremony**. So flipping the *running default* to production now would brick every default boot until EA-4. Therefore EA-2 builds the flip mechanism and leaves the **shipped default = dev**; EA-4 throws the switch once everything is present. **There is no brick window under this plan** — the default is dev the entire sprint.

## Role

code-specialist, isolated worktree, BlarAI runtime (no external network, no new deps, fail-closed), strict type hints, PEP 8.

## Objective

Make the production posture fully *ready and safe to activate* — **without activating it.** Build the resolver-inversion capability, preserve + test + document the explicit dev opt-in (the permanent escape hatch), apply the test-suite overrides so the future flip won't break the suite, and lay the regression locks. The shipped running default stays dev.

## Background — disk-rooted pointers

- `shared/security/dev_mode_guard.py:63-108` — `resolve_dev_mode` (the `HOST → True` default at :90-91); the loud banner :95-106; the docstring :75-78. `:111-159` — the deny-by-default interlock. **Keep load-bearing.**
- `launcher/__main__.py:458` — resolves `_dev_mode`; `:454-457` the "HOST still returns True" comment. **EA-1 added the per-boot mint at :483-517, gated `if not _dev_mode:` (:493) — it fires only in production, so it stays dormant the whole sprint under the deferred plan.**
- `services/policy_agent/src/entrypoint.py:594-596` — services apply the override; `:773`/`:781` — the `dev_mode=false` KGM requirement (the reason activation waits).
- `services/policy_agent/config/default.toml:21` — ships `dev_mode=false` (per-service config); the LIVE host default is decided by `resolve_dev_mode`'s HOST branch.

## In-scope (deliverables) — MECHANISM only

1. **Production-resolution capability, default UNCHANGED.** Ensure `resolve_dev_mode` cleanly resolves production when given an explicit production signal, and keep the `dev_mode_override` seam intact. **Do NOT change the HOST default — it stays `True` (dev) this sprint** (the one-line `HOST→False` flip is EA-4's activation). Update the `launcher/__main__.py:454-457` comment to describe the deferred-activation plan, not a live flip.
2. **Preserve + TEST + DOCUMENT the explicit escape hatch** — the permanent explicit-dev opt-in: `dev_mode=true` (explicit override) starts LOUD + air-gapped (`network_facing=false`); the interlock refuses it network-facing. (After EA-4's activation this is how a user deliberately chooses dev — it is **not** a brick-recovery mechanism; under the deferred plan there is no brick.)
3. **Rollback note (document).** One line: how to stay in / return to dev post-activation if the operator ever wants it (e.g. TPM unavailable on a new machine) — in the dev-mode docs / `dev_mode_guard` docstring / ADR-026 ops. Framed as the **permanent opt-in**, not emergency recovery.
4. **Test-blast-radius audit (this is why the suite stays green at EA-4).** Find every test that builds a service / calls `resolve_dev_mode` assuming HOST→dev-by-default, and give it an **explicit dev override** so it stays green when EA-4 flips the live default. Apply these now — while the default is still dev they are harmless/redundant; at EA-4 they are load-bearing.
5. **Regression locks (mechanism-appropriate).** (a) the shipped HOST default is STILL dev this sprint (asserts the flip has NOT fired prematurely); (b) an explicit production signal resolves `dev_mode=false` (capability works); (c) the explicit dev opt-in resolves dev (banner fires); (d) the interlock still refuses `dev_mode=true + network_facing=true`. (The "HOST resolves production" lock belongs to EA-4, post-activation.)
6. **Untrack the auto-generated `certs/ca.pem` (git hygiene, pre-activation).** EA-1's per-boot mint now **auto-generates `certs/ca.pem`** at boot (`launcher/__main__.py:580`), so it is a per-boot artifact — already in `.gitignore` (\~line 130) but a stale copy is still **tracked** (committed in `95c4f19`), making the ignore inert. Run `git rm --cached certs/ca.pem` (non-destructive — leaves the file on disk, only untracks it) and commit, so production minting doesn't leave a tracked file dirty / accidentally committable. **Correct reasoning (do NOT mis-state):** `ca.pem` **is read** — it is the **mTLS CA**, consumed via `ipc.ca_cert_path` (PA `default.toml:40`, AO `:88`); the untrack is right *because the per-boot mint regenerates it every boot*, NOT because "nothing reads it." (The `[jwt]` anchor `pa_public.pem` is a **different** file — do not conflate.) Only `ca.pem` is tracked; the private-key paths are already untracked. No urgency (the mint is dev-gated/dormant until EA-4), but land it before EA-4 activation.

## Out-of-scope

- **Throwing the flip** (changing the HOST default to production) — EA-4's final activation, gated on EA-3's manifest + the ceremony's keys.
- The per-boot certs (EA-1, merged); the manifest/cascade (EA-3); the ceremony + live-verify (EA-4).
- Do NOT write tests that assume the per-boot mint fires by default — it is `if not _dev_mode:`-gated and the default is dev all sprint.

## Working set & sequencing

Edits `shared/security/dev_mode_guard.py` + `launcher/__main__.py` (the :454-458 comment region) + tests. **Branch off EA-1-merged `main`.** EA-2 (launcher/resolver) and EA-3 (config/manifest/substrate) are working-set-disjoint and MAY run in parallel off EA-1-merged main; activation is reserved for EA-4 regardless.

## Design constraints & safety

- No external network, no new dependencies, fail-closed. Keep the interlock + loud banner load-bearing. The shipped default stays dev — no silent production fallback in either direction.
- **Test isolation (standing rule):** venv `C:/Users/mrbla/blarai/.venv/Scripts/python.exe -m pytest`; root `conftest.py` isolation; never touch the real user-data dir / keystore.

## Acceptance criteria (maps to SDV v4 §4)

- Re-scoped **criterion #2 (mechanism):** the production-resolution capability + escape hatch + the four regression locks **green**; the shipped default still dev; the test-blast-radius overrides applied so the suite is green and **stays green** through EA-4's flip. (Activation + the "HOST resolves production" proof = criterion #8, owned by EA-4.)

## Process

- Branch off **EA-1-merged** `main` in an isolated worktree. Atomic, reviewable commits.
- Journal fragment `docs/journal_fragments/2026-06-06_s15-ea2-devmode-mechanism.md` (dated `###` header + narrative + `**Next:**`; `**Proposed lesson:**` if earned).
- Return a structured summary for the Orchestrator merge-gate. **This build gets the same independent post-build merge-gate review that caught EA-1's double-mint** — expect scrutiny on the test-override completeness and that the shipped default genuinely stays dev.
