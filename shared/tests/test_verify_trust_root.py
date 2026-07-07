"""Tests for the read-only trust-root verification probe
(``shared/security/verify_trust_root.py``).

Hardware round-trip (``@pytest.mark.slow``, deselected by default like the sibling
TPM tests): validates the probe LOGIC against EPHEMERAL keys it provisions and
deletes itself.  It NEVER depends on or mutates the four production trust-root
keys — exactly the ephemeral-key pattern ``test_tpm_signer.py`` /
``test_tpm_sealer.py`` use.  Run with::

    pytest shared/tests/test_verify_trust_root.py -m slow

The production-key verification is performed (read-only) by running the module
on the deployment hardware and recording the artifact — NOT by this test, which
stays independent of production-key state so it can never touch the trust root.

(Fast default-suite unit tests for the pure ``_verdict`` state machine are tracked
as a follow-up rather than landed here, to keep this verification session from
shifting the standing-gate baseline — see Vikunja #635.)
"""

from __future__ import annotations

import pytest

from shared.security import tpm_sealer, tpm_signer, verify_trust_root

# Ephemeral keys — created and deleted by these tests only.  Names are distinct
# from the four production keys so the tests can never touch the trust root.
_HW_SIGNER_KEY = "BlarAI-VerifyTrustRoot-PytestHW-Signer"
_HW_SEALER_KEY = "BlarAI-VerifyTrustRoot-PytestHW-Sealer"
_GHOST_KEY = "BlarAI-VerifyTrustRoot-PytestHW-DoesNotExist"


@pytest.mark.slow
class TestVerifyTrustRootHardware:
    """Real-chip validation of the probe logic on EPHEMERAL keys (never production)."""

    @pytest.fixture(autouse=True)
    def _require_tpm(self):
        if not (tpm_signer.is_available() and tpm_sealer.is_available()):
            pytest.skip("no TPM 2.0 / CNG Platform Crypto Provider on this host")
        # Clean any leftover ephemeral keys from a previous interrupted run.
        if tpm_signer.key_exists(_HW_SIGNER_KEY):
            tpm_signer.delete_key(_HW_SIGNER_KEY)
        if tpm_sealer.key_exists(_HW_SEALER_KEY):
            tpm_sealer.delete_key(_HW_SEALER_KEY)
        yield
        if tpm_signer.key_exists(_HW_SIGNER_KEY):
            tpm_signer.delete_key(_HW_SIGNER_KEY)
        if tpm_sealer.key_exists(_HW_SEALER_KEY):
            tpm_sealer.delete_key(_HW_SEALER_KEY)

    def test_probe_signer_key_verified_live_on_ephemeral_key(self) -> None:
        tpm_signer.ensure_key(_HW_SIGNER_KEY)
        r = verify_trust_root.probe_signer_key(_HW_SIGNER_KEY)
        assert r["resident"] is True
        assert r["functional_roundtrip"] is True
        assert r["public_export_ok"] is True
        assert r["private_export_refused"] is True, (
            "private key export was NOT refused on the chip — non-exportability broken"
        )
        assert r["verdict"] == verify_trust_root._VERIFIED_LIVE

    def test_probe_sealer_key_verified_live_on_ephemeral_key(self) -> None:
        tpm_sealer.ensure_key(_HW_SEALER_KEY)
        r = verify_trust_root.probe_sealer_key(_HW_SEALER_KEY)
        assert r["resident"] is True
        assert r["functional_roundtrip"] is True
        assert r["private_export_refused"] is True, (
            "RSA private key export was NOT refused on the chip — non-exportability broken"
        )
        assert r["verdict"] == verify_trust_root._VERIFIED_LIVE

    def test_probe_does_not_create_an_absent_key(self) -> None:
        """The read-only guarantee, proven on hardware: probing a non-existent key
        never creates it."""
        if tpm_signer.key_exists(_GHOST_KEY):  # defensive — should never exist
            tpm_signer.delete_key(_GHOST_KEY)
        assert tpm_signer.key_exists(_GHOST_KEY) is False
        r = verify_trust_root.probe_signer_key(_GHOST_KEY)
        assert r["resident"] is False
        assert r["verdict"] == verify_trust_root._NOT_PROVISIONED
        assert tpm_signer.key_exists(_GHOST_KEY) is False, (
            "probe_signer_key CREATED a key — read-only contract violated"
        )
