"""Security-cascade integration test — Sprint 17 SDV §4 criterion C4 (GAP-7).

WHY THIS FILE EXISTS — closing GAP-7
====================================
The Sprint-16 coverage audit (``docs/sprints/sprint_16/coverage_audit.md``,
GAP-7, HIGH priority) named the exact gap this file closes:

    "Security components are individually unit-tested.  No automated test
    exercises the full Tier-2 ceremony-to-boot chain: provision-signing-key →
    generate certs → boot → per-boot cert mint → mTLS handshake → TPM-signed
    audit record.  The Sprint-15 production live-verify found failures in this
    chain that no test would have caught."

Each link in that chain (``tpm_signer`` / ``tpm_sealer``, ``cert_provisioning``,
``dek_envelope``, ``vsock`` mTLS, ``audit_log``) has thorough unit coverage in
isolation.  What was missing — and what burned the project at the Sprint-15
terminal — is the *composed walk*: the seams between these components, run as a
single automated sequence.  This file is that walk.

THE CASCADE (the C4 walk, in order)
===================================
1. **provision-key** — the host trust-root signing key.
     - Stand-in tier: an in-memory ECDSA P-256 key (no TPM).
     - Real-TPM tier: ``shared.security.provision_signing_key.provision`` mints
       the non-exportable TPM key + exports its public half (the real ceremony).
2. **cert-gen** — ``provision_per_boot_certs()`` mints the per-boot ephemeral CA
   and the per-service mTLS certs (the REAL function, into ``tmp_path``).
3. **boot** — the at-rest key material comes up: a ``Sealer`` is constructed and
   ``build_envelope()`` creates + persists the dual-wrapped DEK (the per-boot
   key-material step).  The DEK is then unsealed back through the sealer, proving
   the seal/unseal seam works end to end.
4. **per-boot mint** — a SECOND ``provision_per_boot_certs()`` call (the rotation
   semantics the module documents): a fresh boot mints a distinct cert chain.
   We assert the second chain differs from the first (different serials / bytes).
5. **mTLS handshake** — a REAL mutual-TLS handshake over the minted per-boot
   certs: the PA-server cert as the listener identity, the gateway-client cert as
   the connecting identity, ``CERT_REQUIRED`` both ways, verified against the
   per-boot CA.  We assert the peer CN extracted on the server side is the
   gateway client's CN — i.e. the minted certs actually chain and verify.
6. **TPM-signed audit record** — an ``AuditLog`` record is appended and signed,
   then ``verify()`` walks the chain (hash linkage + signature).  This is the
   "every security-relevant boot event is recorded under a signing authority"
   step.
     - Stand-in tier: ``HmacSha256Signer`` (the documented software stub).
     - Real-TPM tier: ``TpmRecordSigner`` (ECDSA P-256 in the TPM, the dedicated
       audit key — separation of duties from the JWT key).

TWO-TIER STRUCTURE (mirrors test_boot_cascade_smoke.py)
=======================================================
- **Stand-in tier** (``TestSecurityCascadeSoftwareSealer``) — GREEN in the
  standing gate.  No TPM, no GPU, no hardware marker.  Uses ``SoftwareSealer``
  (the documented test stand-in for the TPM sealer) + ``HmacSha256Signer``.  The
  mTLS handshake runs over TCP loopback (``dev_mode=True``) but performs a REAL
  ``CERT_REQUIRED`` mutual-TLS handshake using the REAL per-boot minted certs —
  the dev_mode fallback is the transport (AF_INET vs AF_HYPERV), NOT the TLS.
- **Real-TPM tier** (``TestSecurityCascadeRealTpm``) — marked
  ``@pytest.mark.hardware`` so the gate DESELECTS it.  The same cascade walk
  against the real TPM sealer + the real TPM-signed audit stream + the real
  provisioning ceremony.  Its first green run is the LA on-chip session (homed by
  the Orchestrator — Sprint 18 / a batched dev-machine session).  See the class
  docstring for the HOW TO RUN command + prerequisites.

ISOLATION
=========
All tests use ``tmp_path`` only.  The root ``conftest.py`` redirects
``LOCALAPPDATA`` / ``HOME`` / ``XDG_DATA_HOME`` to a throwaway temp dir at process
startup and unsets ``BLARAI_DEK_KEYSTORE``, so the real user-data directory (and
the real DEK keystore) is never touched.  The mTLS handshake binds an ephemeral
loopback port (``port=0``) so it never collides with a live BlarAI instance.

SHARED/SECURITY IS READ-ONLY HERE
=================================
This file IMPORTS and EXERCISES ``shared.security.*`` and ``shared.ipc.vsock``;
it modifies none of them (stream H-a owns ``egress_guard.py``, stream K owns
``dek_envelope.py``).  The cascade is built entirely from the existing public
APIs.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from shared.ipc.vsock import (
    VsockAddress,
    VsockConfig,
    VsockListener,
    VsockTransport,
)
from shared.security.audit_log import (
    AuditLog,
    HmacSha256Signer,
    RecordSigner,
)
from shared.security.cert_provisioning import (
    GATEWAY_CLIENT_CN,
    PerBootCerts,
    provision_per_boot_certs,
)
from shared.security.dek_envelope import (
    DekEnvelope,
    build_envelope,
    generate_recovery_key,
)
from shared.security.tpm_sealer import Sealer, SoftwareSealer

# ---------------------------------------------------------------------------
# Shared cascade helpers — used by BOTH tiers so the walk is identical and only
# the sealer / signer / provisioning differ between stand-in and real-TPM.
# ---------------------------------------------------------------------------

# A benign, PGOV-safe canned adjudication used for the audit-record step.  The
# audit log records adjudication decisions; this is a representative one.
_AUDIT_ADJUDICATION_ID: str = "cascade-boot-event-0001"
_AUDIT_DECISION: str = "ALLOW"
_AUDIT_CAR_HASH: str = "0" * 64  # placeholder sha256-shaped digest (benign)


def _mint_certs(certs_dir: Path) -> PerBootCerts:
    """Cascade step 2/4: mint a per-boot CA + per-service mTLS certs.

    Wraps the REAL ``provision_per_boot_certs`` against a tmp dir.  Returns the
    ``PerBootCerts`` handle whose paths feed the mTLS handshake step.
    """
    certs = provision_per_boot_certs(certs_dir=certs_dir)
    # Sanity: the two certs the mTLS handshake needs must be on disk and be PEM.
    assert certs.pa_server_cert_path.exists(), "PA server cert must be minted"
    assert certs.gateway_client_cert_path.exists(), "Gateway client cert must be minted"
    assert certs.ca_cert_path.exists(), "Per-boot CA cert must be minted"
    return certs


def _boot_dek_envelope(
    *,
    sealer: Sealer,
    keystore_path: Path,
    dev_mode: bool,
) -> DekEnvelope:
    """Cascade step 3: bring up the at-rest DEK (the per-boot key material).

    Creates + persists a dual-wrapped DEK via the production factory, then
    unseals it back through the sealer to prove the seal/unseal seam works.
    Returns the envelope so the caller can make further assertions if needed.
    """
    recovery_key = generate_recovery_key()
    envelope = build_envelope(
        sealer=sealer,
        recovery_key=recovery_key,
        keystore_path=keystore_path,
        dev_mode=dev_mode,
    )
    # The keystore must have been persisted (wrap records, never the DEK clear).
    assert keystore_path.exists(), "DEK keystore must be persisted on boot"

    # Unseal the DEK back through the sealer — the round-trip that proves the
    # seal/unseal seam (TPM or stand-in) is wired correctly.
    dek = envelope.unseal_dek()
    assert len(dek) == 32, "Unsealed DEK must be a 32-byte AES-256 key"

    # The DEK must also be recoverable through a reload from disk (the path a
    # real boot takes: read the keystore, then unseal).
    reloaded = DekEnvelope.load(sealer=sealer, keystore_path=keystore_path)
    assert reloaded.unseal_dek() == dek, "Reloaded keystore must unseal the same DEK"
    return envelope


def _mtls_handshake_over_minted_certs(certs: PerBootCerts) -> str | None:
    """Cascade step 5: a REAL mutual-TLS handshake over the minted per-boot certs.

    Stands up a ``VsockListener`` using the per-boot PA-server cert/key as the
    server identity, connects a ``VsockTransport`` using the per-boot
    gateway-client cert/key, both verifying against the per-boot CA with
    ``CERT_REQUIRED``.  Sends one framed payload and echoes it back, then returns
    the peer CN the server extracted from the client cert during the handshake.

    ``dev_mode=True`` only selects the TCP-loopback transport (AF_INET) in place
    of the production AF_HYPERV socket — the mTLS handshake itself is REAL and is
    performed exactly as in production because the cert paths are set (see
    ``shared.ipc.vsock`` ``VsockListener.start`` / ``VsockTransport.connect``,
    which build the mTLS SSL context whenever ``mtls_cert_path`` + ``ca_cert_path``
    are present, regardless of dev_mode).

    Returns the extracted peer CN (the gateway client's CN on success).
    """
    server_cfg = VsockConfig(
        address=VsockAddress(cid=0, port=0),  # ephemeral loopback port
        mtls_cert_path=str(certs.pa_server_cert_path),
        mtls_key_path=str(certs.pa_server_key_path),
        ca_cert_path=str(certs.ca_cert_path),
        timeout_ms=5_000,
    )
    listener = VsockListener(server_cfg, dev_mode=True)
    assert listener.start() is True, "mTLS listener must start with minted certs"
    port = listener.bound_port
    assert port is not None and port > 0, "Listener must bind an ephemeral port"

    server_peer_cn: list[str | None] = [None]
    server_received: list[bytes | None] = [None]

    def _server_handler() -> None:
        accepted = listener.accept()
        if accepted is not None:
            server_peer_cn[0] = accepted.peer_cn
            data = accepted.receive()
            server_received[0] = data
            if data is not None:
                accepted.send(data)  # echo
            accepted.close()

    server_thread = threading.Thread(target=_server_handler, daemon=True)
    server_thread.start()

    client_cfg = VsockConfig(
        address=VsockAddress(cid=0, port=port),
        mtls_cert_path=str(certs.gateway_client_cert_path),
        mtls_key_path=str(certs.gateway_client_key_path),
        ca_cert_path=str(certs.ca_cert_path),
        timeout_ms=5_000,
    )
    client = VsockTransport(client_cfg, dev_mode=True)
    try:
        assert client.connect() is True, (
            "mTLS client must complete the handshake against the per-boot certs"
        )
        payload = b'{"type":"HEARTBEAT","request_id":"cascade-mtls","payload":{}}'
        assert client.send(payload) is True, "Client must send over the mTLS channel"
        echoed = client.receive()
        assert echoed == payload, "mTLS channel must round-trip the payload intact"
    finally:
        client.close()
        server_thread.join(timeout=5.0)
        listener.stop()

    assert server_received[0] == payload, "Server must have received the framed payload"
    return server_peer_cn[0]


def _signed_audit_record(signer: RecordSigner, audit_path: Path) -> AuditLog:
    """Cascade step 6: append a signed audit record and verify the chain.

    Appends one adjudication record under ``signer`` to a file-backed
    ``AuditLog`` (so the on-disk write seam is exercised, not just the in-memory
    path), then walks the whole chain via ``verify()`` (hash linkage + signature
    authenticity).  Returns the log so callers can make further assertions.
    """
    log = AuditLog.from_path(audit_path, signer=signer)
    record = log.append(
        adjudication_id=_AUDIT_ADJUDICATION_ID,
        decision=_AUDIT_DECISION,
        car_hash=_AUDIT_CAR_HASH,
        source_agent="assistant_orchestrator",
        destination_service="policy_agent",
        verb="boot",
        resource="security-cascade",
        sensitivity="internal",
        rule_engine_passed=True,
        confidence=1.0,
    )
    assert record.seq == 0, "First cascade audit record must be seq 0"
    assert record.signature, "Audit record must carry a non-empty signature"
    assert record.signer_id == signer.signer_id(), "Record must record its signer id"
    assert audit_path.exists(), "Audit log must be persisted to disk"

    # Walk the full chain: recompute hashes, check linkage, verify signatures.
    # Raises AuditChainError on any break; a clean return is the assertion.
    log.verify()
    assert log.record_count == 1, "Exactly one record must be in the chain"
    return log


# ---------------------------------------------------------------------------
# Stand-in tier — GREEN in the standing gate (no TPM, no hardware marker)
# ---------------------------------------------------------------------------


class TestSecurityCascadeSoftwareSealer:
    """The full security cascade with the SoftwareSealer stand-in (gate-green).

    This walks provision-key → cert-gen → boot → per-boot mint → mTLS handshake
    → TPM-signed audit record using software stand-ins for the two hardware-bound
    primitives (the sealer and the audit signer).  Every NON-hardware seam is
    REAL: real per-boot cert generation, a real DEK envelope create/persist/
    unseal/reload cycle, a real ``CERT_REQUIRED`` mutual-TLS handshake over the
    minted certs, and a real signed + chain-verified audit record.

    This is the regression lock that would have caught the Sprint-15 cert-mount
    cascade failures (GAP-7) without an LA at the terminal.
    """

    def test_full_security_cascade_software_tier(self, tmp_path: Path) -> None:
        """One automated walk of the entire C4 security cascade (stand-in tier).

        Steps (each a real seam except the sealer + audit signer, which use the
        documented software stand-ins so the walk runs without a TPM):
          1. provision-key   — in-memory ECDSA P-256 trust-root key (no TPM).
          2. cert-gen        — provision_per_boot_certs() (REAL).
          3. boot            — build_envelope() + unseal + reload (REAL crypto,
                               SoftwareSealer stand-in).
          4. per-boot mint   — second provision_per_boot_certs() (REAL rotation).
          5. mTLS handshake  — REAL CERT_REQUIRED mutual TLS over minted certs.
          6. signed audit    — AuditLog append + verify (REAL chain, HMAC stub).
        """
        # --- Step 1: provision-key (stand-in: in-memory ECDSA P-256) ----------
        # The real ceremony mints a non-exportable TPM key; off-TPM we stand in
        # an in-memory ECDSA P-256 key + export its SPKI, which is the same shape
        # of artifact (a public key the validators would trust).  This proves the
        # provision-key STEP is wired into the cascade; the real-TPM tier proves
        # it against the chip.
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec

        trust_root_key = ec.generate_private_key(ec.SECP256R1())
        trust_root_pub_pem = trust_root_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        assert b"BEGIN PUBLIC KEY" in trust_root_pub_pem, (
            "provision-key step must yield a usable trust-root public key"
        )

        # --- Step 2: cert-gen -------------------------------------------------
        certs_dir = tmp_path / "certs"
        first_certs = _mint_certs(certs_dir)
        # Capture the first boot's PA cert bytes NOW, BEFORE step 4 re-mints into
        # the same dir and overwrites the file (the rotation is in-place).
        first_pa_bytes = first_certs.pa_server_cert_path.read_bytes()

        # --- Step 3: boot (at-rest DEK comes up) ------------------------------
        sealer: Sealer = SoftwareSealer()
        keystore_path = tmp_path / "dek_keystore.json"
        _boot_dek_envelope(
            sealer=sealer,
            keystore_path=keystore_path,
            dev_mode=True,  # SoftwareSealer is only permitted with dev_mode=True
        )

        # --- Step 4: per-boot mint (rotation — a fresh boot mints fresh certs) -
        # provision_per_boot_certs is documented as idempotent-by-rotation:
        # calling it again produces a DISTINCT chain (different serials/keys/
        # signatures), overwriting the previous boot's certs in the same dir.
        second_certs = _mint_certs(certs_dir)
        second_pa_bytes = second_certs.pa_server_cert_path.read_bytes()
        assert first_pa_bytes != second_pa_bytes, (
            "Per-boot mint must rotate: a second provisioning must yield distinct "
            "cert material (different serial / key / signature)"
        )

        # --- Step 5: mTLS handshake over the (current) minted certs -----------
        peer_cn = _mtls_handshake_over_minted_certs(second_certs)
        assert peer_cn == GATEWAY_CLIENT_CN, (
            f"mTLS peer CN must be the gateway client CN {GATEWAY_CLIENT_CN!r} "
            f"(the minted client cert must chain + verify); got {peer_cn!r}"
        )

        # --- Step 6: TPM-signed audit record (stand-in: HMAC-SHA256) ----------
        signer: RecordSigner = HmacSha256Signer(
            key=b"cascade-stand-in-audit-key", key_id="cascade-stub"
        )
        audit_path = tmp_path / "audit.jsonl"
        log = _signed_audit_record(signer, audit_path)

        # Final cross-step assertion: the chain verifies under a freshly
        # constructed verifier with the same key (the verify-after-reopen path).
        reopened = AuditLog.from_path(audit_path, signer=signer)
        reopened.verify()
        assert reopened.record_count == log.record_count == 1

    def test_cascade_mtls_rejects_unrelated_cert(self, tmp_path: Path) -> None:
        """The mTLS step is a REAL trust check — a cert from a different CA fails.

        Negative control proving step 5 is not a no-op: if the client presents a
        cert minted by a DIFFERENT per-boot CA (a second, independent
        provisioning), the ``CERT_REQUIRED`` handshake must fail — the server
        will not accept a client whose chain does not verify against its CA.

        This guards against a regression where mTLS silently degrades to a
        non-verifying channel (the class of fail-open the security sprints exist
        to prevent).
        """
        # Two INDEPENDENT per-boot provisionings → two distinct CAs.
        server_certs = provision_per_boot_certs(certs_dir=tmp_path / "ca_a")
        foreign_certs = provision_per_boot_certs(certs_dir=tmp_path / "ca_b")

        server_cfg = VsockConfig(
            address=VsockAddress(cid=0, port=0),
            mtls_cert_path=str(server_certs.pa_server_cert_path),
            mtls_key_path=str(server_certs.pa_server_key_path),
            ca_cert_path=str(server_certs.ca_cert_path),
            timeout_ms=3_000,
        )
        listener = VsockListener(server_cfg, dev_mode=True)
        assert listener.start() is True
        port = listener.bound_port
        assert port is not None

        def _server_handler() -> None:
            # The accept() will fail the TLS handshake (foreign client cert);
            # accept() swallows the handshake error and returns None.  Nothing
            # to do here but let the thread exit.
            listener.accept()

        server_thread = threading.Thread(target=_server_handler, daemon=True)
        server_thread.start()

        # Client presents a cert signed by the FOREIGN CA, but the server only
        # trusts its OWN CA → the handshake must not establish a working channel.
        client_cfg = VsockConfig(
            address=VsockAddress(cid=0, port=port),
            mtls_cert_path=str(foreign_certs.gateway_client_cert_path),
            mtls_key_path=str(foreign_certs.gateway_client_key_path),
            # Client trusts the foreign CA (so it would accept the server), but
            # the SERVER will reject the client's foreign cert — that is the
            # direction under test.
            ca_cert_path=str(foreign_certs.ca_cert_path),
            timeout_ms=3_000,
        )
        client = VsockTransport(client_cfg, dev_mode=True)
        try:
            connected = client.connect()
            # Either connect() reports failure outright, or the channel never
            # carries data because the server dropped the unverified peer.  A
            # successful, usable channel here would be a fail-open regression.
            if connected:
                client.send(b"should-not-be-trusted")
                assert client.receive() is None, (
                    "A foreign-CA client must NOT get a working mTLS channel "
                    "(server must reject the unverified peer)"
                )
        finally:
            client.close()
            server_thread.join(timeout=3.0)
            listener.stop()


# ---------------------------------------------------------------------------
# Real-TPM tier — BUILT, SCRIPTED, marked @hardware (gate DESELECTS it)
# ---------------------------------------------------------------------------


class TestSecurityCascadeRealTpm:
    """The full security cascade against the REAL TPM — hardware-marked.

    THIS TIER IS BUILT BUT NOT VERIFIED IN THE GATE.  It is marked with the
    ``hardware`` marker so the standing gate DESELECTS it.  Its first green run
    is the LA on-chip session (the Orchestrator homes it — Sprint 18 or a
    batched dev-machine session, per the C4 tier note in the SDV).

    It walks the IDENTICAL cascade as the stand-in tier, but swaps the two
    software stand-ins for their real, chip-bound counterparts:
      - ``SoftwareSealer``      → ``TpmSealer``       (RSA-2048 OAEP in the TPM)
      - ``HmacSha256Signer``    → ``TpmRecordSigner`` (ECDSA P-256 in the TPM,
                                                       dedicated audit key)
    and runs the REAL provision-signing-key ceremony as step 1.

    WHY THE REAL-TPM RUN IS DEFERRED (the gate-honesty discipline):
    a lock that has never gone green locks nothing, but the first real-TPM run
    must be a CONFIRMATION (the cascade harness proven on the stand-in tier) not
    a DISCOVERY (the harness broken because it was never exercised).  The
    stand-in tier above proves the cascade walk works; this tier then confirms it
    against the chip — the real seal/unseal, the real TPM signature, the real
    ceremony — locking the FULL Tier-2 boot security cascade (GAP-7) before the
    #598 air-gap-removal gate.

    HOW TO RUN (dev machine, real TPM 2.0 present)
    ==============================================
    From the repo root, on the deployment hardware (a machine with a TPM 2.0
    exposed via the Microsoft Platform Crypto Provider)::

        C:/Users/mrbla/BlarAI/.venv/Scripts/python.exe -m pytest \\
            tests/integration/test_security_cascade.py::TestSecurityCascadeRealTpm \\
            -m hardware -v

    PREREQUISITES
    -------------
    - Windows host with a usable TPM 2.0 (Microsoft Platform Crypto Provider).
      ``shared.security.tpm_sealer.is_available()`` and
      ``shared.security.tpm_signer.is_available()`` must both return True; the
      test SKIPS (does not fail) if no TPM is reachable, so it is safe to run in
      ``-m hardware`` selections on non-TPM machines.
    - No model files are required — this cascade is security-material only (it
      does NOT load Qwen3-14B), so it is the lightest of the hardware-marked
      tiers to run.

    SIDE EFFECTS / IDEMPOTENCY
    --------------------------
    This test provisions (idempotently) two persisted TPM keys if absent:
      - the JWT signing key (``provision_signing_key`` default name), and
      - the dedicated audit key (``AUDIT_TPM_KEY_NAME``).
    Both ``ensure_key`` calls are no-ops if the keys already exist (the normal
    production state after the LA ceremony).  It also uses a TPM seal key for the
    DEK envelope (``TpmSealer`` auto-provisions one).  It writes only into
    ``tmp_path`` for certs / keystore / audit-log / public-key artifacts; it does
    NOT touch the real ``certs/`` dir or the real DEK keystore.
    """

    @pytest.mark.hardware
    def test_full_security_cascade_real_tpm(self, tmp_path: Path) -> None:
        """One automated walk of the entire C4 cascade against the real TPM.

        Steps:
          1. provision-key   — provision_signing_key.provision() on the REAL chip
                               (non-exportable TPM key + public-half export).
          2. cert-gen        — provision_per_boot_certs() (REAL).
          3. boot            — build_envelope() + unseal + reload with TpmSealer.
          4. per-boot mint   — second provision_per_boot_certs() (REAL rotation).
          5. mTLS handshake  — REAL CERT_REQUIRED mutual TLS over minted certs.
          6. signed audit    — AuditLog append + verify with TpmRecordSigner
                               (REAL TPM ECDSA signature over each record).
        """
        from shared.security import tpm_sealer as _tpm_sealer
        from shared.security import tpm_signer as _tpm_signer

        if not (_tpm_sealer.is_available() and _tpm_signer.is_available()):
            pytest.skip(
                "Real TPM 2.0 (Microsoft Platform Crypto Provider) not available "
                "— the real-TPM cascade tier requires deployment hardware."
            )

        # Imports deferred so the module imports cleanly off-Windows / off-TPM
        # (the stand-in tier must collect + run on any machine).
        from shared.security.audit_log import AUDIT_TPM_KEY_NAME, TpmRecordSigner
        from shared.security.provision_signing_key import provision
        from shared.security.tpm_sealer import TpmSealer

        # Cascade-scoped TPM key names so the test never collides with the
        # operator's PRODUCTION keys (the real JWT/DEK-seal keys keep their
        # production names).  These two are created here and torn down in the
        # finally block so a hardware run leaves no stray persisted keys.
        cascade_jwt_key = "BlarAI-Cascade-Test-JWT"
        cascade_dek_seal_key = "BlarAI-Cascade-Test-DEKSeal"

        try:
            # --- Step 1: provision-key — the REAL ceremony on the chip --------
            pub_key_path = tmp_path / "pa_public.pem"
            # Idempotent: a no-op if the key already exists; the public half is
            # (re-)exported to tmp_path either way.
            rc = provision(cascade_jwt_key, pub_key_path)
            assert rc == 0, "provision-signing-key ceremony must succeed on the chip"
            assert pub_key_path.exists(), "Ceremony must export the public key half"
            assert b"BEGIN PUBLIC KEY" in pub_key_path.read_bytes(), (
                "Exported trust-root public key must be a valid SPKI PEM"
            )

            # --- Step 2: cert-gen --------------------------------------------
            certs_dir = tmp_path / "certs"
            first_certs = _mint_certs(certs_dir)
            first_pa_bytes = first_certs.pa_server_cert_path.read_bytes()

            # --- Step 3: boot (at-rest DEK via the REAL TPM sealer) ----------
            sealer: Sealer = TpmSealer(cascade_dek_seal_key)
            keystore_path = tmp_path / "dek_keystore.json"
            _boot_dek_envelope(
                sealer=sealer,
                keystore_path=keystore_path,
                dev_mode=False,  # real TPM sealer — production posture, no dev gate
            )

            # --- Step 4: per-boot mint (rotation) ----------------------------
            second_certs = _mint_certs(certs_dir)
            second_pa_bytes = second_certs.pa_server_cert_path.read_bytes()
            assert first_pa_bytes != second_pa_bytes, (
                "Per-boot mint must rotate to distinct cert material on a fresh boot"
            )

            # --- Step 5: mTLS handshake over the minted certs ----------------
            peer_cn = _mtls_handshake_over_minted_certs(second_certs)
            assert peer_cn == GATEWAY_CLIENT_CN, (
                f"mTLS peer CN must be {GATEWAY_CLIENT_CN!r}; got {peer_cn!r}"
            )

            # --- Step 6: TPM-signed audit record (REAL TPM ECDSA signature) --
            # The audit record uses the PRODUCTION audit key (AUDIT_TPM_KEY_NAME)
            # — ensure_key is idempotent and this is the dedicated audit key by
            # design (separation of duties).  We do NOT delete it in teardown:
            # it is the operator's real audit key, not a cascade-test artifact.
            signer: RecordSigner = TpmRecordSigner(AUDIT_TPM_KEY_NAME)
            audit_path = tmp_path / "audit.jsonl"
            log = _signed_audit_record(signer, audit_path)

            # Re-verify after reopen with a fresh TpmRecordSigner (the chip
            # verifies its own signatures via the persisted key) — the
            # boot-then-audit path.
            reopened = AuditLog.from_path(
                audit_path, signer=TpmRecordSigner(AUDIT_TPM_KEY_NAME)
            )
            reopened.verify()
            assert reopened.record_count == log.record_count == 1
        finally:
            # Tear down ONLY the cascade-scoped test keys.  Best-effort: a
            # failure to delete must not mask a test failure (the keys are
            # idempotently reused on the next run anyway).
            for _mod, _name in (
                (_tpm_signer, cascade_jwt_key),
                (_tpm_sealer, cascade_dek_seal_key),
            ):
                try:
                    if _mod.is_available() and _mod.key_exists(_name):
                        _mod.delete_key(_name)
                except Exception:  # noqa: BLE001 — teardown must never raise
                    pass
