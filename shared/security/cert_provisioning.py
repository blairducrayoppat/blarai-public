"""Per-boot ephemeral mTLS certificate provisioning (ADR-026).

Generates a short-lived Certificate Authority (CA) plus fresh server and
client certificates on every boot for the host↔VM vsock channel.  The
private key for the CA is generated purely in-memory (never persisted to
disk), so each boot produces a fully independent, unlinked trust chain.

Design (ADR-026 §2):
  - ECDSA P-256 for all keys (mirrors ``_generate_test_certs`` and
    ``shared.security.tpm_signer``).
  - Per-boot lifetime: 24 hours (chosen so a stale cert from an
    unclean shutdown is expired within a day; in practice every clean
    boot mints fresh certs, so the effective lifetime is the boot
    session length).
  - CN/SAN per service identity (PA server; gateway/AO client;
    orchestrator listener+client; semantic-router client).
  - ``CERT_REQUIRED`` in both directions enforced by the SSL-context
    factories in ``shared.ipc.vsock``.

Security invariants:
  - **No external network calls.**
  - **No new dependencies** — ``cryptography`` is already a project dep.
  - **CA private key is in-memory only.**  The callers write the CA
    *public* cert to disk (``certs/ca.pem``) as a per-boot artifact so
    both sides can verify each other; the private key is discarded after
    issuance.
  - **Never log or print private key material.**  This module contains
    zero ``logging.*`` / ``print()`` calls involving private bytes.
  - **Fail-Closed:** any cert-generation failure raises
    ``CertProvisioningError`` rather than producing a partial or
    insecure artifact.  The caller is expected to abort startup on any
    raised exception.
  - The per-boot files written to ``certs/`` are gitignored
    (``certs/pa_server.pem``, ``certs/pa_server_key.pem``,
    ``certs/gateway_client.pem``, ``certs/gateway_client_key.pem``,
    ``certs/orch_client.pem``, ``certs/orch_client_key.pem``,
    ``certs/router_client.pem``, ``certs/router_client_key.pem``,
    ``certs/ca.pem``).  Only ``certs/pa_public.pem`` (the TPM JWT
    public key) is tracked in git; per ADR-021 it is the sole exception.

Known limitation (ADR-026 §5 / FUT-02):
  Per-boot certs deliver *freshness* (each boot produces a new,
  unlinked chain) but NOT measured-image CN binding.  The full FUT-02
  vision — where the CA issues certs with a CN derived from the
  verified image measurement, so a cert from a tampered image is
  verifiably different from a clean-boot cert — requires Pluton-sealed
  boot attestation and is deferred.  Freshness is proven; issuer
  attestation is not.
"""

from __future__ import annotations

import datetime
import ipaddress
import logging
from dataclasses import dataclass
from pathlib import Path

# ``cryptography`` is an existing project dependency (see pyproject.toml);
# importing submodules here follows the same pattern as _generate_test_certs
# in test_ipc_transport.py.
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

logger = logging.getLogger(__name__)

# Per-boot certificate lifetime (ADR-026 §2.3).
# 24 hours: long enough to survive an unclean shutdown without immediate
# re-issuance pressure; short enough that any leaked on-disk cert is expired
# within a day.  In practice the CA private key is discarded in-memory at
# process exit, so the trust chain dies with the process regardless.
CERT_LIFETIME_HOURS: int = 24

# Service identities embedded in the CN / SAN fields.
PA_SERVER_CN: str = "blarai-policy-agent-server"
GATEWAY_CLIENT_CN: str = "blarai-gateway-client"
ORCH_CLIENT_CN: str = "blarai-orchestrator"
ROUTER_CLIENT_CN: str = "blarai-semantic-router"
CA_CN: str = "BlarAI Per-Boot CA"

# Standard output paths — mirror the [ipc] config in default.toml.
# These are per-boot gitignored artifacts; not committed.
DEFAULT_CERTS_DIR: str = "certs"
PA_SERVER_CERT_NAME: str = "pa_server.pem"
PA_SERVER_KEY_NAME: str = "pa_server_key.pem"
GATEWAY_CLIENT_CERT_NAME: str = "gateway_client.pem"
GATEWAY_CLIENT_KEY_NAME: str = "gateway_client_key.pem"
ORCH_CLIENT_CERT_NAME: str = "orch_client.pem"
ORCH_CLIENT_KEY_NAME: str = "orch_client_key.pem"
ROUTER_CLIENT_CERT_NAME: str = "router_client.pem"
ROUTER_CLIENT_KEY_NAME: str = "router_client_key.pem"
CA_CERT_NAME: str = "ca.pem"


class CertProvisioningError(RuntimeError):
    """Raised when per-boot cert generation fails (Fail-Closed).

    Callers must abort startup on this exception — partial or absent
    certs must never be presented to the SSL context factories.
    """


@dataclass(frozen=True)
class PerBootCerts:
    """Paths to the freshly-minted per-boot certificate artifacts.

    All paths point to PEM files written to the certs directory.  The
    CA private key is never exposed here — it is discarded in-memory
    after signing.
    """

    ca_cert_path: Path
    """Path to the per-boot CA public certificate (PEM)."""

    pa_server_cert_path: Path
    """Path to the PA server certificate signed by the per-boot CA (PEM)."""

    pa_server_key_path: Path
    """Path to the PA server private key (PEM)."""

    gateway_client_cert_path: Path
    """Path to the gateway/AO client certificate signed by the per-boot CA (PEM)."""

    gateway_client_key_path: Path
    """Path to the gateway/AO client private key (PEM)."""

    orch_client_cert_path: Path
    """Path to the Orchestrator listener+client certificate signed by the per-boot CA (PEM).

    The AO uses this cert both as its own TLS server certificate (listener)
    and as its client certificate when it connects to the Policy Agent.
    EKU: SERVER_AUTH + CLIENT_AUTH.
    """

    orch_client_key_path: Path
    """Path to the Orchestrator private key (PEM)."""

    router_client_cert_path: Path
    """Path to the Semantic Router client certificate signed by the per-boot CA (PEM).

    EKU: CLIENT_AUTH + SERVER_AUTH (matches gateway_client pattern).
    """

    router_client_key_path: Path
    """Path to the Semantic Router private key (PEM)."""


def _make_ec_key() -> ec.EllipticCurvePrivateKey:
    """Generate a fresh ECDSA P-256 private key."""
    return ec.generate_private_key(ec.SECP256R1())


def _now_utc() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _issue_cert(
    *,
    subject_cn: str,
    issuer_name: x509.Name,
    subject_key: ec.EllipticCurvePrivateKey,
    signing_key: ec.EllipticCurvePrivateKey,
    is_ca: bool,
    lifetime_hours: int,
    san_ip: str | None = None,
    eku: list[x509.ObjectIdentifier] | None = None,
) -> x509.Certificate:
    """Issue one X.509 certificate.

    Args:
        subject_cn:    Common Name for the subject.
        issuer_name:   Issuer ``x509.Name`` (CA's distinguished name).
        subject_key:   Key pair for the new certificate.
        signing_key:   Private key used to sign (CA key for end-entity certs;
                       same as subject_key for self-signed CA).
        is_ca:         Whether to set the CA BasicConstraints extension.
        lifetime_hours: Certificate lifetime in hours from now.
        san_ip:        Optional IP address to add as a Subject Alternative Name.
        eku:           Optional list of Extended Key Usage OIDs.

    Returns:
        Signed ``x509.Certificate``.
    """
    now = _now_utc()
    subject_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject_cn)])

    builder = (
        x509.CertificateBuilder()
        .subject_name(subject_name)
        .issuer_name(issuer_name)
        .public_key(subject_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(hours=lifetime_hours))
        .add_extension(
            x509.BasicConstraints(ca=is_ca, path_length=None),
            critical=True,
        )
    )

    # Add SAN extension when an IP address is supplied.
    if san_ip is not None:
        builder = builder.add_extension(
            x509.SubjectAlternativeName([
                x509.IPAddress(ipaddress.IPv4Address(san_ip)),
            ]),
            critical=False,
        )

    # Add Extended Key Usage when specified.
    if eku:
        builder = builder.add_extension(
            x509.ExtendedKeyUsage(eku),
            critical=False,
        )

    return builder.sign(signing_key, hashes.SHA256())


def _write_cert(path: Path, cert: x509.Certificate) -> None:
    """Write a certificate to disk in PEM format."""
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def _write_key(path: Path, key: ec.EllipticCurvePrivateKey) -> None:
    """Write a private key to disk in unencrypted PEM format.

    Keys written here are per-boot ephemeral artifacts stored in the
    gitignored ``certs/`` directory.  They are never printed, logged,
    or committed.
    """
    path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )


def _load_consistent_certs(certs_dir: Path) -> "PerBootCerts | None":
    """Return a :class:`PerBootCerts` for an EXISTING, CONSISTENT cert set in
    *certs_dir*, or ``None`` if any of the nine files is missing/empty, any cert
    is expired, or the set is INCONSISTENT (a partial or cross-generation mint).

    "Consistent" means the PA-server / gateway / orchestrator / router leaves all
    verify against the on-disk CA — the exact chain the mTLS handshake checks — so
    a PASS here proves a reused set will complete the handshake. Used by #863
    reuse-if-consistent to avoid re-minting a fresh CA out from under a still-
    running (or leaked) AO whose in-memory leaf then fails CERTIFICATE_VERIFY_FAILED.
    """
    paths = {
        "ca": certs_dir / CA_CERT_NAME,
        "pa_server": certs_dir / PA_SERVER_CERT_NAME,
        "pa_server_key": certs_dir / PA_SERVER_KEY_NAME,
        "gateway_client": certs_dir / GATEWAY_CLIENT_CERT_NAME,
        "gateway_client_key": certs_dir / GATEWAY_CLIENT_KEY_NAME,
        "orch_client": certs_dir / ORCH_CLIENT_CERT_NAME,
        "orch_client_key": certs_dir / ORCH_CLIENT_KEY_NAME,
        "router_client": certs_dir / ROUTER_CLIENT_CERT_NAME,
        "router_client_key": certs_dir / ROUTER_CLIENT_KEY_NAME,
    }
    if not all(p.is_file() and p.stat().st_size > 0 for p in paths.values()):
        return None
    try:
        now = _now_utc()

        def _not_after(cert: x509.Certificate) -> datetime.datetime:
            try:
                return cert.not_valid_after_utc  # cryptography >= 42 (tz-aware)
            except AttributeError:  # older cryptography: naive UTC
                return cert.not_valid_after.replace(tzinfo=datetime.timezone.utc)

        ca = x509.load_pem_x509_certificate(paths["ca"].read_bytes())
        if _not_after(ca) <= now:
            return None
        ca_pub = ca.public_key()
        for leaf_name in ("pa_server", "gateway_client", "orch_client", "router_client"):
            leaf = x509.load_pem_x509_certificate(paths[leaf_name].read_bytes())
            if _not_after(leaf) <= now:
                return None
            # ECDSA signature check: the on-disk CA actually signed this leaf. A
            # cross-generation set (new CA, old leaf) raises InvalidSignature here.
            ca_pub.verify(
                leaf.signature,
                leaf.tbs_certificate_bytes,
                ec.ECDSA(leaf.signature_hash_algorithm),
            )
    except Exception:  # noqa: BLE001 — any load/verify failure -> not reusable -> mint fresh
        return None
    return PerBootCerts(
        ca_cert_path=paths["ca"],
        pa_server_cert_path=paths["pa_server"],
        pa_server_key_path=paths["pa_server_key"],
        gateway_client_cert_path=paths["gateway_client"],
        gateway_client_key_path=paths["gateway_client_key"],
        orch_client_cert_path=paths["orch_client"],
        orch_client_key_path=paths["orch_client_key"],
        router_client_cert_path=paths["router_client"],
        router_client_key_path=paths["router_client_key"],
    )


def provision_per_boot_certs(
    certs_dir: Path | None = None,
    *,
    repo_root: Path | None = None,
    reuse_if_consistent: bool = False,
) -> PerBootCerts:
    """Generate and write fresh per-boot mTLS certificates.

    Creates a new ephemeral CA, then issues per-service certificates for
    every host-side listener and client role signed by that CA.  Writes
    nine PEM files to ``certs_dir``.  The CA private key is discarded
    in-memory after signing and never written to disk.

    Services covered:
      - Policy Agent server (``pa_server.pem`` / ``pa_server_key.pem``)
      - Gateway/AO outbound client (``gateway_client.pem`` / ``gateway_client_key.pem``)
      - Orchestrator listener + PA client (``orch_client.pem`` / ``orch_client_key.pem``)
      - Semantic Router client (``router_client.pem`` / ``router_client_key.pem``)

    This function is idempotent in the sense that calling it again will
    overwrite the previous boot's certs with a fresh, distinct set.  That
    is the rotation mechanism: calling ``provision_per_boot_certs()`` a
    second time produces certs with different serial numbers, public keys,
    and signatures from the previous call.

    Args:
        certs_dir:  Directory to write cert files into.  Defaults to
                    ``<repo_root>/certs``.  Created if absent.
        repo_root:  Repository root; used to derive the default
                    ``certs_dir``.  If both are ``None``, the current
                    working directory is used as repo root.

    Returns:
        ``PerBootCerts`` with paths to the written PEM files.

    Raises:
        CertProvisioningError: On any failure (Fail-Closed).
    """
    try:
        if certs_dir is None:
            base = repo_root if repo_root is not None else Path.cwd()
            certs_dir = base / DEFAULT_CERTS_DIR
        certs_dir.mkdir(parents=True, exist_ok=True)

        # #863: reuse an existing CONSISTENT set instead of re-minting a fresh CA.
        # The battery's per-job AO reboots (boot_launcher_detached sets
        # reuse_if_consistent) all go through here, so every boot in a run shares
        # ONE trust chain; a re-mint under a still-running/leaked prior AO rotates
        # the CA out from under its in-memory leaf -> CERTIFICATE_VERIFY_FAILED (the
        # deterministic per-job STALL, night-20260711). Production leaves this False
        # -> per-boot minting (ADR-026) unchanged; a single-boot app never drifts.
        # An absent/inconsistent set -> fall through to a fresh mint.
        if reuse_if_consistent:
            existing = _load_consistent_certs(certs_dir)
            if existing is not None:
                logger.info(
                    "per-boot certs: reusing the existing consistent set in %s "
                    "(reuse_if_consistent; #863 — no CA re-mint under a running AO)",
                    certs_dir,
                )
                try:
                    from shared.security.file_dacl import strip_foreign_sids_from_dir

                    strip_foreign_sids_from_dir(certs_dir)
                except Exception as dacl_exc:  # noqa: BLE001 — never fail on DACL hygiene
                    logger.warning(
                        "certs dir DACL hygiene raised (%s); proceeding with %s",
                        dacl_exc, certs_dir,
                    )
                return existing

        # --- Generate CA key pair (in-memory only) ---
        ca_key = _make_ec_key()
        ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, CA_CN)])

        # --- Self-signed CA certificate ---
        ca_cert = _issue_cert(
            subject_cn=CA_CN,
            issuer_name=ca_name,
            subject_key=ca_key,
            signing_key=ca_key,
            is_ca=True,
            lifetime_hours=CERT_LIFETIME_HOURS,
        )

        # --- PA server certificate (SERVER_AUTH + CLIENT_AUTH EKU) ---
        pa_key = _make_ec_key()
        pa_cert = _issue_cert(
            subject_cn=PA_SERVER_CN,
            issuer_name=ca_name,
            subject_key=pa_key,
            signing_key=ca_key,
            is_ca=False,
            lifetime_hours=CERT_LIFETIME_HOURS,
            san_ip="127.0.0.1",  # loopback for fidelity-2 host-local verify
            eku=[ExtendedKeyUsageOID.SERVER_AUTH, ExtendedKeyUsageOID.CLIENT_AUTH],
        )

        # --- Gateway/AO outbound client certificate (CLIENT_AUTH + SERVER_AUTH EKU) ---
        gw_key = _make_ec_key()
        gw_cert = _issue_cert(
            subject_cn=GATEWAY_CLIENT_CN,
            issuer_name=ca_name,
            subject_key=gw_key,
            signing_key=ca_key,
            is_ca=False,
            lifetime_hours=CERT_LIFETIME_HOURS,
            san_ip="127.0.0.1",
            eku=[ExtendedKeyUsageOID.CLIENT_AUTH, ExtendedKeyUsageOID.SERVER_AUTH],
        )

        # --- Orchestrator cert (SERVER_AUTH + CLIENT_AUTH EKU).
        # The AO uses this cert both as the TLS server cert for its own listener
        # AND as its client cert when connecting to the Policy Agent.  Issuing
        # both EKUs on a single cert avoids a separate "orch_server" + "orch_client"
        # split; the PA's mTLS peer-verification accepts any cert signed by the
        # per-boot CA, so the CN here is the distinguishing identity.
        orch_key = _make_ec_key()
        orch_cert = _issue_cert(
            subject_cn=ORCH_CLIENT_CN,
            issuer_name=ca_name,
            subject_key=orch_key,
            signing_key=ca_key,
            is_ca=False,
            lifetime_hours=CERT_LIFETIME_HOURS,
            san_ip="127.0.0.1",
            eku=[ExtendedKeyUsageOID.SERVER_AUTH, ExtendedKeyUsageOID.CLIENT_AUTH],
        )

        # --- Semantic Router client certificate (CLIENT_AUTH + SERVER_AUTH EKU) ---
        router_key = _make_ec_key()
        router_cert = _issue_cert(
            subject_cn=ROUTER_CLIENT_CN,
            issuer_name=ca_name,
            subject_key=router_key,
            signing_key=ca_key,
            is_ca=False,
            lifetime_hours=CERT_LIFETIME_HOURS,
            san_ip="127.0.0.1",
            eku=[ExtendedKeyUsageOID.CLIENT_AUTH, ExtendedKeyUsageOID.SERVER_AUTH],
        )

        # --- Write cert + key files to the certs dir ---
        ca_cert_path = certs_dir / CA_CERT_NAME
        pa_server_cert_path = certs_dir / PA_SERVER_CERT_NAME
        pa_server_key_path = certs_dir / PA_SERVER_KEY_NAME
        gw_client_cert_path = certs_dir / GATEWAY_CLIENT_CERT_NAME
        gw_client_key_path = certs_dir / GATEWAY_CLIENT_KEY_NAME
        orch_client_cert_path = certs_dir / ORCH_CLIENT_CERT_NAME
        orch_client_key_path = certs_dir / ORCH_CLIENT_KEY_NAME
        router_client_cert_path = certs_dir / ROUTER_CLIENT_CERT_NAME
        router_client_key_path = certs_dir / ROUTER_CLIENT_KEY_NAME

        _write_cert(ca_cert_path, ca_cert)
        _write_cert(pa_server_cert_path, pa_cert)
        _write_key(pa_server_key_path, pa_key)
        _write_cert(gw_client_cert_path, gw_cert)
        _write_key(gw_client_key_path, gw_key)
        _write_cert(orch_client_cert_path, orch_cert)
        _write_key(orch_client_key_path, orch_key)
        _write_cert(router_client_cert_path, router_cert)
        _write_key(router_client_key_path, router_key)

        # CA private key (ca_key) is now out-of-scope; the GC will reclaim
        # its memory.  It is never written to disk.

        # #637 (DATA_MAP §7 item 2): strip any orphaned/foreign SID from the
        # certs dir's DACL (the observed ``S-1-5-21-76345465-…`` ACE is a
        # non-resolving cross-machine principal carried in from repo history —
        # ACL hygiene, grants nothing live).  Owner-preserving + fail-safe
        # (``shared.security.file_dacl.strip_foreign_sids_from_dir`` never raises
        # and never blocks); a no-op on non-Windows and when the dir is clean.
        # Runs every boot here so the remediation is self-healing without a
        # manual operator step.
        try:
            from shared.security.file_dacl import strip_foreign_sids_from_dir

            strip_foreign_sids_from_dir(certs_dir)
        except Exception as dacl_exc:  # noqa: BLE001 — never fail cert provisioning
            logger.warning(
                "certs dir DACL hygiene raised unexpectedly (%s); proceeding "
                "with existing ACLs on %s",
                dacl_exc,
                certs_dir,
            )

        return PerBootCerts(
            ca_cert_path=ca_cert_path,
            pa_server_cert_path=pa_server_cert_path,
            pa_server_key_path=pa_server_key_path,
            gateway_client_cert_path=gw_client_cert_path,
            gateway_client_key_path=gw_client_key_path,
            orch_client_cert_path=orch_client_cert_path,
            orch_client_key_path=orch_client_key_path,
            router_client_cert_path=router_client_cert_path,
            router_client_key_path=router_client_key_path,
        )

    except (OSError, ValueError) as exc:
        raise CertProvisioningError(
            f"Per-boot cert provisioning failed: {exc}"
        ) from exc


def verify_per_boot_certs_exist(certs: PerBootCerts) -> bool:
    """Return True if all nine per-boot cert files are present and non-empty.

    This is a lightweight sanity check used by startup code before
    constructing SSL contexts.  It does NOT validate cert contents or
    cryptographic validity — ``ssl.SSLContext`` load methods enforce that.

    Args:
        certs: The ``PerBootCerts`` returned by ``provision_per_boot_certs``.

    Returns:
        True if all paths exist and have non-zero size.
    """
    paths = [
        certs.ca_cert_path,
        certs.pa_server_cert_path,
        certs.pa_server_key_path,
        certs.gateway_client_cert_path,
        certs.gateway_client_key_path,
        certs.orch_client_cert_path,
        certs.orch_client_key_path,
        certs.router_client_cert_path,
        certs.router_client_key_path,
    ]
    return all(p.exists() and p.stat().st_size > 0 for p in paths)
