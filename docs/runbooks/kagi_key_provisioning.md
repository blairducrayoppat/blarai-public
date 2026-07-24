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

There is **no separate web-search worker process**. The key is loaded once during
Assistant-Orchestrator boot, and what a missing or unusable key stops is the
*registration of the web_search runner* — not the service.

The shipped contract lives in `_maybe_register_web_search`
(`services/assistant_orchestrator/src/entrypoint.py:5548`, called at `:1640`).
It loads the key via `load_wrapped_kagi_key()`
(`shared/secrets/kagi_key_loader.py:105`), which **catches every load failure and
returns `None`** — "every load failure is dormancy, never a crash". So the
`KagiKey*` exceptions below are raised by the underlying store
(`shared/secrets/dpapi_store.py`) but never reach the caller:

| Condition | Behaviour |
|---|---|
| Blob file absent | `KagiKeyNotProvisioned` raised internally, swallowed; loader returns `None`, so the live runner is **not registered**. The AO boots normally with web_search **structurally dormant** — a `web_search` call returns the deterministic "unavailable" notice. |
| DPAPI decryption fails (wrong user / machine / corrupt blob) | `KagiKeyDecryptError` raised internally, swallowed; same outcome — not registered, AO boots, web_search dormant. |
| `[web_search].enabled` is `false` | Runner not registered regardless of the key. Either condition missing is sufficient. |
| `pywin32` not available (non-Windows environment) | `RuntimeError` from the store; also swallowed on this path. No silent *fallback* — the outcome is dormancy, not a degraded live runner. |

Practical consequence: **a bad key produces no error banner at boot.** It looks
like a healthy AO in which web search happens to be unavailable. Diagnose it by
the "unavailable" notice, and by the load-failure line in the log (which records
the exception type only, never key material).

> **Do not read "the AO still boots" as a soft-degradation path.** It is the
> opposite: the failure mode is *structural absence* — the runner object is never
> registered, so with no usable key there is no code path from the model to the
> network at all. That is a stronger posture than a registered-but-erroring
> runner, not a weaker one.
>
> What is **not** true is that the service refuses to start. Earlier revisions of
> this runbook said the worker "refuses to start"; it does not, and an operator
> who provisions a bad key should expect a healthy AO with web search quietly
> unavailable, **not** a boot failure. If you are diagnosing a missing key, look
> for the dormant-notice behaviour, not for a crash.

> **Be clear about what is open today: with a valid key, this reaches the
> internet.** Do not read the fail-closed language above as "egress is still
> welded" — it is not. The ADR-027 egress allowlist was **activated on 2026-07-02**
> at the web_search go-live ceremony and holds one standing entry, `kagi.com`
> (`_EGRESS_ALLOWLIST = frozenset({"kagi.com"})`,
> `services/policy_agent/src/gpu_inference.py`), read by both egress layers — the
> tool-loop dispatch check and the `guarded_fetch` door.
>
> So the live posture is: for `web_search`, `kagi.com` is the only reachable host —
> RULE 3 denies every other one — and a `web_search` with a provisioned key does
> make a real outbound request to Kagi, **gated by the fingerprint envelope
> described below** (which covers a bounded window of queries per touch, not each
> query individually — read the next paragraph, the distinction matters).
>
> Two precision notes, because a flat "everything else is blocked" would be too
> strong. RULE 3 is allowlist-*parameterised*, not a fixed block: the `/ingest`
> path supplies its own one-entry allowlist built from the URL you pasted, so for
> that path RULE 3 approves the host you chose. That is the design, and it is
> dormant at rest (`[guest_parser].enabled = false`). The universal-deny statement
> above is therefore about the `web_search` path specifically.
>
> **The key is necessary but not sufficient.** A third, independent lock sits in
> front of every model-initiated outbound call: the turn-scoped Windows-Hello
> egress envelope (`[egress]` in the AO config, ADR-023 Amendment 4). It has no
> enable flag — it is always on. On the first egress of a turn a fingerprint
> prompt fires showing the exact query; one touch covers up to
> `searches_per_fingerprint` (default 3) searches for that question, and every
> subsequent query is disclosed live in chat as it leaves. It is fail-closed: no
> verifier, a cancel, or a timeout (`fingerprint_timeout_s = 120.0`) refuses the
> egress and ends the turn with nothing sent. It runs **in addition to** the
> deterministic controls above, never instead of them.
>
> So provisioning a key here does not silently open the network: **no
> model-initiated web search leaves this machine without either a fingerprint on
> that exact query, or a live in-chat disclosure under a window you already
> fingerprinted** — bounded at `searches_per_fingerprint` (default 3). Be precise
> about what that means: you fingerprint the *first* query of a turn and see it
> in the dialog; the 2nd and 3rd leave on that one touch, each disclosed in chat
> as it goes, with no second prompt. Set `searches_per_fingerprint = 1` if you
> want a fingerprint on literally every outbound query.
>
> That is the scope of the guarantee, and it is deliberately not broader —
> operator-typed egress (`/ingest <url>`) is consented by the act of pasting the
> URL, not by a fingerprint (ADR-027 Amendment 1 rejected a Hello prompt there as
> merely re-confirming intent you already expressed). That path is dormant at
> rest behind `[guest_parser].enabled = false`. The `--probe` diagnostic also
> reaches Kagi without the envelope; it is operator-run. Those three — the
> envelope-gated `web_search`, `/ingest`, and `--probe` — are the only paths in
> shipped runtime code that reach the network.
>
> The re-weld procedure (removing the allowlist entry) is in
> `docs/runbooks/web_search_go_live.md`.

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

> **Rotation requires a restart of the Assistant Orchestrator.** The key is read
> once at boot and captured by the live adapter at construction
> (`services/assistant_orchestrator/src/websearch/live_adapter.py:254-262` takes
> `api_key: KagiApiKey` and stores it as `self._api_key`); every request then uses
> that held value. It is **not** re-read per call.
>
> So overwriting the blob does nothing to a running AO — it will keep presenting
> the old key to Kagi until it is restarted. After rotating, restart the backend
> and confirm a search works. (An earlier revision of this runbook said no restart
> was needed "if the worker re-reads the key at each call, which the design
> prescribes". The shipped adapter does not do that.)

To revoke a key without replacing it (emergency revocation):
1. Revoke the token in the Kagi API management panel (Settings → API → delete
   the token).
2. The blob on disk becomes inert — it decrypts to a revoked key that Kagi will
   reject.
3. Optionally delete the blob file. On the next AO restart the live runner is
   then not registered at all (§4), so web_search goes structurally dormant —
   which makes the revocation observable at the BlarAI level as well. Note this
   takes effect at the **restart**, not the moment you delete the file.

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
