"""LIVE-transport mTLS wiring tests for the autonomous-dispatch harness (#683).

The harness's LIVE path (:meth:`DispatchHarness.for_live`) used to hardcode ``dev_mode=True``
(plaintext loopback) and pass NO cert paths, so it could only ever reach a dev-mode AO. #683 makes
LIVE default to **production mutual-TLS** — loopback + the per-boot mTLS chain the launcher writes
to ``<repo>/certs`` (ADR-026) — and keeps ``dev_mode=True`` only as the explicit dev/test path.

These tests are PURE CONSTRUCTION + attribute assertions — no live AO, no GPU, no network. The real
``TransportGateway.__init__`` does ZERO I/O (it only stores the kwargs and builds in-process
coordinators; the mTLS socket is opened lazily, never at construction), so it is safe to construct
a real gateway and inspect its stored attributes. The cert-existence check lives in the harness, so
the production tests stage dummy cert files in a tmp dir.

Each assertion is written to FLIP if the wiring regresses:
  * the production path asserts ``dev_mode=False`` + ``host_mode=True`` + the three cert paths, on
    BOTH the recorded constructor kwargs AND the real gateway instance's stored attributes;
  * the cert filenames are derived from the :mod:`shared.security.cert_provisioning` SSOT constants
    (not literals here), so a hardcoded-filename regression in the harness fails the path-equality;
  * the fail-closed path asserts the missing-cert error actually raises;
  * the dev-mode path asserts plaintext is preserved (dev_mode True, cert paths empty).

In the standing gate (tests/integration is in scope). asyncio_mode=auto — these are sync tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import tools.dispatch_harness.harness as harness_mod
from services.ui_gateway.src.transport import TransportGateway
from shared.security.cert_provisioning import (
    CA_CERT_NAME,
    DEFAULT_CERTS_DIR,
    GATEWAY_CLIENT_CERT_NAME,
    GATEWAY_CLIENT_KEY_NAME,
)
from tools.dispatch_harness.harness import DispatchHarness


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _write_dummy_certs(certs_dir: Path, *, names: tuple[str, ...]) -> None:
    """Write non-empty placeholder PEM files for the given names into ``certs_dir``.

    The harness only checks the files EXIST (``is_file()``); the gateway never reads them at
    construction, so any non-empty bytes suffice — these are never parsed as real certs here.
    """
    certs_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        (certs_dir / name).write_text(
            f"-----BEGIN PLACEHOLDER {name}-----\nnot-a-real-cert\n", encoding="utf-8"
        )


_ALL_CERT_NAMES = (GATEWAY_CLIENT_CERT_NAME, GATEWAY_CLIENT_KEY_NAME, CA_CERT_NAME)


class _RecordingGateway(TransportGateway):
    """A real ``TransportGateway`` that records the kwargs it was constructed with.

    Subclassing the REAL class (rather than a bare stand-in) means the test exercises the genuine
    constructor: the recorded kwargs AND the resulting stored attributes are both asserted, so a
    regression in EITHER the harness's threading OR the gateway's attribute storage is caught.
    """

    last_kwargs: dict = {}

    def __init__(self, **kwargs):  # type: ignore[no-untyped-def]
        type(self).last_kwargs = dict(kwargs)
        super().__init__(**kwargs)


# ---------------------------------------------------------------------------
# production mTLS (the #683 default)
# ---------------------------------------------------------------------------


def test_for_live_production_builds_mtls_gateway_with_resolved_cert_paths(tmp_path, monkeypatch):
    """dev_mode=False (the default) → loopback + mTLS gateway, with the three per-boot cert
    paths resolved from the explicit certs_dir using the canonical SSOT filenames."""
    certs_dir = tmp_path / "certs"
    _write_dummy_certs(certs_dir, names=_ALL_CERT_NAMES)

    monkeypatch.setattr(harness_mod, "TransportGateway", _RecordingGateway)

    harness = DispatchHarness.for_live(
        port=5001,
        agentic_setup_dir=str(tmp_path / "agentic"),
        projects_dir=str(tmp_path / "projects"),
        certs_dir=str(certs_dir),
    )

    expected_cert = str(certs_dir / GATEWAY_CLIENT_CERT_NAME)
    expected_key = str(certs_dir / GATEWAY_CLIENT_KEY_NAME)
    expected_ca = str(certs_dir / CA_CERT_NAME)

    # (a) the constructor kwargs the harness threaded.
    kw = _RecordingGateway.last_kwargs
    assert kw["dev_mode"] is False
    assert kw["host_mode"] is True
    assert kw["mtls_cert_path"] == expected_cert
    assert kw["mtls_key_path"] == expected_key
    assert kw["ca_cert_path"] == expected_ca
    assert kw["port"] == 5001
    assert kw["host"] == "127.0.0.1"
    # fleet roots are still threaded exactly as before.
    assert kw["fleet_dispatch_agentic_setup_dir"] == str(tmp_path / "agentic")
    assert kw["fleet_dispatch_projects_dir"] == str(tmp_path / "projects")
    assert kw["fleet_dispatch_enabled"] is True

    # (b) the REAL gateway instance's stored attributes (construction did no I/O).
    # Reach the actual constructed gateway: it is the bound owner of the harness's send_fn.
    bound_self = harness.send_fn.__self__  # type: ignore[union-attr]
    assert isinstance(bound_self, _RecordingGateway)
    assert bound_self._dev_mode is False
    assert bound_self._host_mode is True
    assert bound_self._mtls_cert_path == expected_cert
    assert bound_self._mtls_key_path == expected_key
    assert bound_self._ca_cert_path == expected_ca
    # harness itself is in LIVE mode (not dry-run).
    assert harness.dry_run is False


def test_for_live_production_with_real_gateway_no_monkeypatch(tmp_path):
    """Same production path but against the REAL (un-patched) TransportGateway — proves the genuine
    class accepts the kwargs and stores them, and that construction performs no cert/file/network
    I/O (it succeeds with placeholder cert files present)."""
    certs_dir = tmp_path / "certs"
    _write_dummy_certs(certs_dir, names=_ALL_CERT_NAMES)

    harness = DispatchHarness.for_live(
        port=5001,
        agentic_setup_dir="",
        projects_dir="",
        certs_dir=str(certs_dir),
    )

    bound_self = harness.send_fn.__self__  # type: ignore[union-attr]
    assert isinstance(bound_self, TransportGateway)
    assert bound_self._dev_mode is False
    assert bound_self._host_mode is True
    assert bound_self._mtls_cert_path == str(certs_dir / GATEWAY_CLIENT_CERT_NAME)
    assert bound_self._mtls_key_path == str(certs_dir / GATEWAY_CLIENT_KEY_NAME)
    assert bound_self._ca_cert_path == str(certs_dir / CA_CERT_NAME)


def test_for_live_production_defaults_certs_dir_to_repo_root_certs(tmp_path, monkeypatch):
    """certs_dir=None → resolves to <repo_root>/certs (= parents[2] of harness.py / DEFAULT_CERTS_DIR).

    We assert the RESOLUTION without depending on the real repo certs existing: stub the harness's
    file-existence check so no real files are needed, capture the kwargs, and confirm the cert paths
    sit under the computed repo-root certs dir with the canonical filenames."""
    monkeypatch.setattr(harness_mod, "TransportGateway", _RecordingGateway)
    # Make the existence assertion pass without staging files at the real default path.
    monkeypatch.setattr(harness_mod.Path, "is_file", lambda self: True, raising=True)

    DispatchHarness.for_live(
        port=5001,
        agentic_setup_dir="",
        projects_dir="",
        certs_dir=None,
    )

    repo_root = Path(harness_mod.__file__).resolve().parents[2]
    expected_dir = repo_root / DEFAULT_CERTS_DIR

    kw = _RecordingGateway.last_kwargs
    assert kw["mtls_cert_path"] == str(expected_dir / GATEWAY_CLIENT_CERT_NAME)
    assert kw["mtls_key_path"] == str(expected_dir / GATEWAY_CLIENT_KEY_NAME)
    assert kw["ca_cert_path"] == str(expected_dir / CA_CERT_NAME)


# ---------------------------------------------------------------------------
# fail-closed: missing per-boot certs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "present_names",
    [
        (),  # none present
        (GATEWAY_CLIENT_CERT_NAME,),  # only the client cert
        (GATEWAY_CLIENT_CERT_NAME, GATEWAY_CLIENT_KEY_NAME),  # CA missing
        (GATEWAY_CLIENT_KEY_NAME, CA_CERT_NAME),  # client cert missing
    ],
)
def test_for_live_production_fails_closed_when_certs_missing(tmp_path, present_names):
    """dev_mode=False with one+ of the three certs absent → a clear, actionable FileNotFoundError;
    NO gateway is built (production never connects without the full mTLS chain)."""
    certs_dir = tmp_path / "certs"
    _write_dummy_certs(certs_dir, names=present_names)

    with pytest.raises(FileNotFoundError) as excinfo:
        DispatchHarness.for_live(
            port=5001,
            agentic_setup_dir="",
            projects_dir="",
            certs_dir=str(certs_dir),
        )

    msg = str(excinfo.value)
    # The message must point the operator at the production launcher + the certs path.
    assert "production" in msg.lower()
    assert str(certs_dir) in msg


def test_for_live_production_missing_certs_dir_entirely_fails_closed(tmp_path):
    """A certs_dir that does not exist at all → still fail-closed (no silent dev fallback)."""
    with pytest.raises(FileNotFoundError):
        DispatchHarness.for_live(
            port=5001,
            agentic_setup_dir="",
            projects_dir="",
            certs_dir=str(tmp_path / "does-not-exist"),
        )


# ---------------------------------------------------------------------------
# dev-mode: plaintext loopback preserved (the old behavior)
# ---------------------------------------------------------------------------


def test_for_live_dev_mode_preserves_plaintext_no_certs(tmp_path, monkeypatch):
    """dev_mode=True → the original plaintext loopback: dev_mode True, host the loopback, and the
    three mTLS cert paths empty (no cert files required, none consulted)."""
    monkeypatch.setattr(harness_mod, "TransportGateway", _RecordingGateway)

    harness = DispatchHarness.for_live(
        port=5001,
        agentic_setup_dir=str(tmp_path / "agentic"),
        projects_dir=str(tmp_path / "projects"),
        dev_mode=True,
    )

    kw = _RecordingGateway.last_kwargs
    assert kw["dev_mode"] is True
    # dev-mode must NOT pass cert paths (plaintext) — assert the kwargs are empty OR absent.
    assert kw.get("mtls_cert_path", "") == ""
    assert kw.get("mtls_key_path", "") == ""
    assert kw.get("ca_cert_path", "") == ""

    bound_self = harness.send_fn.__self__  # type: ignore[union-attr]
    assert bound_self._dev_mode is True
    assert bound_self._mtls_cert_path == ""
    assert bound_self._mtls_key_path == ""
    assert bound_self._ca_cert_path == ""


def test_for_live_dev_mode_with_real_gateway_no_monkeypatch(tmp_path):
    """dev_mode=True against the REAL gateway — plaintext, cert paths empty, no files needed."""
    harness = DispatchHarness.for_live(
        port=5001,
        agentic_setup_dir="",
        projects_dir="",
        dev_mode=True,
    )
    bound_self = harness.send_fn.__self__  # type: ignore[union-attr]
    assert isinstance(bound_self, TransportGateway)
    assert bound_self._dev_mode is True
    assert bound_self._host_mode is True  # default; unused in dev_mode
    assert bound_self._mtls_cert_path == ""
    assert bound_self._ca_cert_path == ""
