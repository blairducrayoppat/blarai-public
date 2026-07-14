"""Tests for shared.security.cert_provisioning — #863 reuse-if-consistent.

The battery's per-job AO reboots must NOT re-mint a fresh CA out from under a
still-running / leaked AO — that rotates the CA and the AO's in-memory leaf then
fails CERTIFICATE_VERIFY_FAILED (the deterministic per-job STALL, night-20260711).
These lock the reuse-if-consistent path: an existing CONSISTENT set is reused so
every battery AO boot in a run shares one trust chain; an absent/inconsistent set
(or reuse_if_consistent=False, i.e. production) mints fresh (ADR-026 per-boot).
"""

from __future__ import annotations

from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import ec

from shared.security.cert_provisioning import provision_per_boot_certs


def _serial(certs_dir: Path, name: str) -> int:
    return x509.load_pem_x509_certificate((certs_dir / name).read_bytes()).serial_number


def _assert_consistent(certs_dir: Path) -> None:
    """The on-disk CA must sign the on-disk pa_server leaf (mint is self-consistent)."""
    ca = x509.load_pem_x509_certificate((certs_dir / "ca.pem").read_bytes())
    leaf = x509.load_pem_x509_certificate((certs_dir / "pa_server.pem").read_bytes())
    ca.public_key().verify(
        leaf.signature, leaf.tbs_certificate_bytes, ec.ECDSA(leaf.signature_hash_algorithm)
    )


def test_production_default_always_remints(tmp_path: Path) -> None:
    """reuse_if_consistent defaults False (production / interactive) -> every call
    mints a NEW trust chain (ADR-026 per-boot freshness), even over a valid set."""
    d = tmp_path / "certs"
    provision_per_boot_certs(certs_dir=d)
    s1 = _serial(d, "pa_server.pem")
    provision_per_boot_certs(certs_dir=d)  # default reuse_if_consistent=False
    s2 = _serial(d, "pa_server.pem")
    assert s1 != s2  # re-minted, not reused


def test_reuse_if_consistent_reuses_a_valid_set(tmp_path: Path) -> None:
    """#863: with reuse_if_consistent=True and an existing consistent set, the call
    REUSES it (identical serials, no re-mint), so every battery AO boot in a run
    shares one trust chain and the reboot handshake cannot cert-drift."""
    d = tmp_path / "certs"
    provision_per_boot_certs(certs_dir=d)
    pa1, ca1 = _serial(d, "pa_server.pem"), _serial(d, "ca.pem")
    provision_per_boot_certs(certs_dir=d, reuse_if_consistent=True)
    assert (_serial(d, "pa_server.pem"), _serial(d, "ca.pem")) == (pa1, ca1)


def test_reuse_if_consistent_remints_when_absent(tmp_path: Path) -> None:
    """No existing set -> reuse_if_consistent still mints a fresh, consistent one."""
    d = tmp_path / "certs"
    certs = provision_per_boot_certs(certs_dir=d, reuse_if_consistent=True)
    assert certs.pa_server_cert_path.is_file() and (d / "ca.pem").is_file()
    _assert_consistent(d)


def test_reuse_if_consistent_rejects_an_inconsistent_set(tmp_path: Path) -> None:
    """#863 (the load-bearing case): a cross-generation set — a CA that did NOT
    sign the on-disk leaves — must NOT be reused (reusing it is exactly the
    handshake failure). Overwrite ca.pem with a FOREIGN CA and confirm the next
    reuse_if_consistent call MINTS fresh (a new consistent chain)."""
    d = tmp_path / "certs"
    provision_per_boot_certs(certs_dir=d)
    pa_before = _serial(d, "pa_server.pem")
    other = tmp_path / "other"
    provision_per_boot_certs(certs_dir=other)
    (d / "ca.pem").write_bytes((other / "ca.pem").read_bytes())  # ca now mismatches d's leaves
    provision_per_boot_certs(certs_dir=d, reuse_if_consistent=True)
    assert _serial(d, "pa_server.pem") != pa_before  # re-minted, not the mismatched reuse
    _assert_consistent(d)  # and the fresh set is self-consistent
