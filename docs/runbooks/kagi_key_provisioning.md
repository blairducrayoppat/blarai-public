# Runbook: Kagi API Key Provisioning

**Scope:** BlarAI Agentic Web-Search Skill (W2, Vikunja #573)
**Module:** `shared/secrets/dpapi_store.py` + `shared/secrets/provision_kagi_key.py`
**Status:** READY — run once before starting the web-search worker for the first time.

---

## 1. Generating a Kagi API Key

Kagi's Search API is a separate, metered service.  It uses the same Kagi account
as your search subscription, but billing is independent — you must fund a dedicated
API credit balance before the Search API will accept requests.

### 1.1 Prerequisites

- An active Kagi account at [kagi.com](https://kagi.com).  A paid Kagi search
  subscription is not strictly required to create an API token, but you must add
  API credits before queries will succeed.
- API credit balance funded at the Kagi API billing panel (see §1.3 below).

### 1.2 Generating the token

The exact UI labels were verified against Kagi's documentation as of 2026-06.
Kagi may update their UI; if the steps below do not match what you see, consult
[help.kagi.com/kagi/api/api-portal.html](https://help.kagi.com/kagi/api/api-portal.html)
for the current authoritative steps.

1. Log in to [kagi.com](https://kagi.com).
2. Navigate to **Settings** (top-right menu) → **API** (or go directly to
   `kagi.com/settings?p=api`).
3. Click **Generate API Token** (the button label may read "Generate Key" or
   similar depending on the current UI revision).
4. **Copy the token immediately** — Kagi displays it only once.  Store it
   somewhere temporary (a password manager or a scratchpad that you will clear)
   until you run the provisioning script below.  Do not write it to a file in the
   repo tree.
5. Optionally give the token a descriptive name (e.g. "BlarAI web-search worker")
   so it is identifiable in the Kagi API management panel.

### 1.3 Adding API credits (mandatory for Search API use)

The Search API operates on a pay-per-use credit balance that is entirely separate
from your monthly Kagi search subscription.

1. In Settings → API (same page as §1.2), find the **API Billing** section.
2. Add funds.  Kagi's pricing as of the time of writing is approximately **$2.50 per
   100 queries** ($0.025 per search), though pricing may change — check
   [kagi.com/api](https://kagi.com/api) for current rates.
3. You can set a per-period spending cap to bound cost.
4. The API credit balance is consumed at query time; unused credits do not expire
   within a billing cycle.

> **Note:** A zero-balance API credit account will reject every query with an
> authentication or billing error even if the token itself is valid.  Fund the
> balance before running the web-search worker for the first time.

---

## 2. Running the Provisioning Script

The provisioning script encrypts the token using Windows DPAPI and writes the
opaque blob to `%LOCALAPPDATA%\BlarAI\secrets\kagi_api_key.dpapi`.  It
immediately verifies the round-trip (decrypt and compare) before reporting
success.

Run from the repo root with the BlarAI virtual environment active:

```
python -m shared.secrets.provision_kagi_key
```

Expected output on success:

```
BlarAI Kagi API key provisioning ceremony
  blob destination   : C:\Users\<you>\AppData\Local\BlarAI\secrets\kagi_api_key.dpapi
  ceremony started   : 2026-06-04T12:00:00Z

This step seals the Kagi API key into a DPAPI-encrypted blob that is
bound to this user account on this machine.  A second machine needs
its own provisioning step.  Re-running this script rotates the key.

Enter Kagi API key (input hidden):

Kagi API key provisioning ceremony complete.
  blob written       : C:\Users\<you>\AppData\Local\BlarAI\secrets\kagi_api_key.dpapi
  round-trip         : PASS
  ceremony ended     : 2026-06-04T12:00:07Z

NOTE: the blob is machine- and user-bound (DPAPI).  A second machine
requires its own provisioning step.  To rotate the key, re-run this
script — the blob is overwritten.  See docs/runbooks/kagi_key_provisioning.md
```

The key is never echoed to the terminal.

---

## 3. Where the Blob Lives

```
%LOCALAPPDATA%\BlarAI\secrets\kagi_api_key.dpapi
```

Typical expansion on a standard Windows installation:

```
C:\Users\<username>\AppData\Local\BlarAI\secrets\kagi_api_key.dpapi
```

The blob is an opaque binary file (the raw output of Windows `CryptProtectData`).
It is:

- **Not committed to git** — `%LOCALAPPDATA%` is outside the repo tree entirely.
- **Not human-readable** — the file contains DPAPI-encrypted bytes, not a
  JSON structure or plaintext string.
- **Per-user, per-machine** — the DPAPI key is derived from the user's Windows
  login credential and the machine identity.  Copying the file to another machine
  or running as a different user will cause decryption to fail.

---

## 4. Fail-Closed Behaviour

The web-search skill worker calls `load_kagi_api_key()` at startup.  The
fail-closed contract is:

| Condition | Behaviour |
|---|---|
| Blob file absent | `KagiKeyNotProvisioned` raised; worker refuses to start |
| DPAPI decryption fails (wrong user / machine / corrupt blob) | `KagiKeyDecryptError` raised; worker refuses to start |
| `pywin32` not available (non-Windows environment) | `RuntimeError` raised at the first call; no silent fallback |

There is no soft-degradation path.  The worker does not start in a degraded mode
without the key.  This mirrors the fail-closed posture of the Policy Agent's TPM
signing-key check (ADR-021).

---

## 5. Key Rotation

Re-running the provisioning script overwrites the existing blob:

```
python -m shared.secrets.provision_kagi_key
```

The script will:
1. Prompt for the new key (echo disabled).
2. Encrypt and overwrite the blob.
3. Verify the round-trip with the new key.
4. Report success without echoing the key.

No restart of already-running workers is required if the worker re-reads the key
at each call (which the design prescribes — keys are not cached in module-level
variables).  If the worker caches the key at startup, restart it after rotation.

To revoke a key without replacing it (emergency revocation):
1. Revoke the token in the Kagi API management panel (Settings → API → delete
   the token).
2. The blob on disk becomes inert — it decrypts to a revoked key that Kagi will
   reject.
3. Optionally delete the blob file to trigger `KagiKeyNotProvisioned` on the
   next worker start, which makes the revocation observable at the BlarAI level
   as well.

---

## 6. Machine-Binding and Second-Machine Provisioning

DPAPI ties the encryption to this user's login credential on this machine.  The
blob cannot be transferred to a second machine — it must be independently
provisioned:

1. On the second machine, generate a new Kagi token (or use the same token if
   Kagi permits multiple uses; check Kagi's token policy).
2. Run `python -m shared.secrets.provision_kagi_key` on the second machine.
3. Each machine holds its own blob file; there is no shared blob across machines.

This is an accepted trade-off for a single-user, single-machine personal system.
The design doc (§7, kagi_key_handling_design.md) names this as a known limitation.

---

## 7. Testing Without a Real Key

Unit and integration tests never touch the real blob file.  See
`shared/tests/test_dpapi_store.py` for the test-override mechanism.

The environment variable `BLARAI_KAGI_KEY_TEST_OVERRIDE` supplies a sentinel
value when tests run under pytest; `load_kagi_api_key()` returns it without
calling DPAPI.  No real API key is required for the test suite.
