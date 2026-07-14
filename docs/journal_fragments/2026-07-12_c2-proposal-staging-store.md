### 2026-07-12 — Building the vault before the two doors that open it

*Plain summary: shipped the born-encrypted coordinator proposal-staging store
(`shared/coordinator/proposal_store.py`) as its own reviewed unit — the shared
C2↔C3 seam both the PARKED-HONEST redispatch proposal (#844) and the C3 heartbeat
(#845) will stage into. Reuses the existing ADR-025 one-DEK sealed-store crypto
(no new crypto); AAD-bound to row identity; refuse-to-start; crash-safe reconcile.
DORMANT, no live consumer. A sequencing + crypto-reuse trade-off recorded; no
failure, no new lesson.*

The staging store is the one piece of C2 increment-2 that C3 also needs, so the
first real decision of this session was not *how* to build it but *when*: fold it
into the C2 redispatch limb that first consumes it, or build it once, alone, ahead
of both consumers. I built it alone. Three reasons made that the right seam. It is
the shared dependency — the redispatch proposal (C2) and every heartbeat proposal
and digest (C3) append to the same store, and a store built twice, or built inside
one consumer and retrofitted for the other, is how a schema drifts. It is
battery-safe — a new module touching none of the swap path, so it could land now
rather than waiting for the post-battery window the swap-path limb needs. And it is
the most security-sensitive surface in the whole increment: a born-encrypted,
governed-core store (ADR-039 §2.1 item 10 — "appended to only via the sanctioned
staging API, never by direct write"), which deserves an isolated author≠verifier
review of its own rather than being reviewed as a footnote to a larger limb.

The load-bearing trade-off was crypto: reuse or rebuild. The tempting-but-wrong path
was a self-contained store with its own little cipher — easy to reason about in
isolation, and catastrophic in aggregate, because a second crypto surface is a second
thing to get wrong, rotate, and audit. I rejected it for the boring, correct path:
this store is the *third* consumer of the one DEK the session and knowledge stores
already share (ADR-025 §2.1 — one DEK, one envelope). `build_proposal_store` mirrors
`build_session_store` branch for branch — same `BLARAI_DEK_KEYSTORE`, same
`TpmSealer("BlarAI-DEKSeal")`, same `derive_subkeys`/`FieldCipher`, same
missing-keystore-in-production → `StoreProvisioningError` refuse-to-start. Not a line
of AES, HMAC, or HKDF is written here; it only *calls* the sealed-store layer. The
one design choice that is genuinely the store's own is the AAD: every payload
ciphertext is bound to its row UUID via `make_aad_for("coordinator_proposals",
"payload", id)`, so a blob relocated to another row fails authentication rather than
silently decrypting — the verifier proved it by literally moving one proposal's
ciphertext into another's row and watching `get()` raise. The dedup fingerprint
(class + target + evidence hash, §2.12.5) is stored only as its keyed-index HMAC, so
even the target repo it encodes never sits in plaintext.

The governance call worth naming: this store introduces **no new trust posture**, so
it gets **no new DECISION_REGISTER line**. That was not an omission — born-encrypted
coordinator stores are already recorded doctrine (ADR-039 §2.13 item 2), and this is
an instance of it, not a new decision. The register indexes decisions, not every
faithful implementation of one; adding a row here would be noise that dilutes the
signal the register exists to carry. The LA's framing at the gate was exact —
"a DECISION_REGISTER line only if it introduces a *new* trust posture (it shouldn't,
if it reuses)" — and it doesn't.

An independent `Explore` verifier (author≠verifier — it did not write the code) read
the module against the real `session_store.py`, `field_cipher.py`, `dek_envelope.py`,
and `swap_state.py`, spot-checked the branch order and the layering (shared/ never
imports services/, so the store carries its own local `StoreProvisioningError`), and
returned MERGE-READY on all ten claims with no nits. The 24 isolated tests are the
honest kind — one relocates a ciphertext to prove AAD binding, one reads the raw
at-rest bytes to prove the payload is encrypted and the fingerprint is HMAC-only, one
reopens the DB across a simulated reboot to prove the shared-DEK reconcile decrypts,
one drives the illegal DRAFT→APPROVED jump to prove the transition gate is
fail-closed. The LOCALAPPDATA-redirected standing gate is **7739 passed / 3 skipped /
0 failed** — the anchor's 7715 plus exactly these 24, zero regressions.

**Next:** the battery-safe C2 increment-2 limbs consume this store — live board
writes, deduped stall comments + operator surface, ACP `session/update` monitoring,
and the PARKED-HONEST → staged redispatch proposal (which stages into exactly this
store) — then the swap-path limb LAST, outside a battery window and after checking
disk for in-flight #740/M2 work on `swap_driver`/`swap_ops`; then C3 (#845), whose
heartbeat proposals and digests also stage here. Each stays dormant behind
`[coordinator]` flags, author≠verifier'd, held for the LA's LIVE-flip ceremony (#855
shadow-mode graduation) — the one line that is not mine to cross.

*(commit `1c318c00` — the born-encrypted proposal-staging store; new
`shared/coordinator/proposal_store.py` + `shared/tests/test_proposal_store.py`
(24 tests); independent author≠verifier review MERGE-READY, no nits; focused 24/24;
standing gate 7739 passed / 3 skipped / 0 failed, LOCALAPPDATA-redirected. DORMANT
behind `[coordinator]`. Awaits the LA's merge nod — the staging store is an
explicit-nod unit; the merge to main follows the go-ahead.)*
