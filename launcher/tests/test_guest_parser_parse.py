"""
Host parse round-trip + ``GuestParserManager.parse_html`` (UC-003 Stage C host
glue, Vikunja #655 sub-task 6).

Transport fully mocked — no live guest, no real AF_HYPERV bridge.  What is
locked: the manager parses ONLY when proven READY (URL ingest never falls back
to host parsing), the version-bridge content path decodes a well-formed
response, and every failure mode (bridge None / bridge raises / oversize body /
no transport at all) maps fail-closed to ``None``.
"""

from __future__ import annotations

import pytest

from launcher.guest_parser import (
    GuestParserConfig,
    GuestParserManager,
    GuestParserState,
    hv_service_guid_for_port,
    set_guest_parser_bridge,
    set_guest_parser_manager,
)
from launcher.guest_parser_health import parse_round_trip
from launcher.parser_channel_seam import (
    ParserEndpoint,
    clear_parser_channel_bindings,
    register_parser_health_probe,
)
from shared.ipc.parse_channel import PARSE_BODY_MAX_BYTES, encode_parse_response


@pytest.fixture(autouse=True)
def _clean():
    clear_parser_channel_bindings()
    set_guest_parser_manager(None)
    set_guest_parser_bridge(None)
    yield
    clear_parser_channel_bindings()
    set_guest_parser_manager(None)
    set_guest_parser_bridge(None)


def _config(**overrides) -> GuestParserConfig:
    base = dict(
        enabled=True,
        vm_name="TestVM",
        guest_root="/opt/blarai/parser",
        vsock_port=50001,
        service_guid=hv_service_guid_for_port(50001),
        service_source_dir="services/cleaner/guest",
        entry_module="blarai_guest_parser",
        deploy_timeout_s=30.0,
        health_timeout_s=5.0,
        health_poll_interval_s=0.01,
        bridge_python="",
    )
    base.update(overrides)
    return GuestParserConfig(**base)


def _manager(**overrides) -> GuestParserManager:
    return GuestParserManager(
        _config(**overrides),
        vm_id="9c7f986f-7afd-48b0-af5b-2c330df6b38f",
        transport_check=lambda endpoint: True,
        clock=lambda: 0.0,
        sleep=lambda s: None,
    )


def _ready_manager() -> GuestParserManager:
    mgr = _manager()
    register_parser_health_probe(lambda endpoint: True)
    assert mgr.start() is True
    assert mgr.state is GuestParserState.READY
    return mgr


def _response_frames(
    *,
    status: str = "clean",
    text: str = "The committee met and recorded a decision in full.",
    word_count: int = 9,
    confidence: float = 0.9,
    reasons: tuple[str, ...] = (),
    title: str | None = "Minutes",
    error_code: str = "",
) -> list[bytes]:
    return encode_parse_response(
        request_id="echo-1",
        status=status,
        text=text,
        word_count=word_count,
        confidence=confidence,
        reasons=reasons,
        title=title,
        error_code=error_code,
    )


class _FakeBridge:
    """Duck-typed GuestParserBridge stand-in (only ``parse`` is exercised)."""

    def __init__(self, frames=None, raise_exc=None):
        self._frames = frames
        self._raise = raise_exc
        self.parse_calls: list = []

    def parse(self, endpoint, request_frames):
        self.parse_calls.append((endpoint, list(request_frames)))
        if self._raise is not None:
            raise self._raise
        return self._frames


class TestParseHtmlAvailabilityGate:
    def test_refuses_when_not_ready(self) -> None:
        mgr = _manager()  # never started → IDLE
        bridge = _FakeBridge(frames=_response_frames())
        set_guest_parser_bridge(bridge)  # type: ignore[arg-type]
        assert mgr.parse_html("<html><body><p>hi</p></body></html>") is None
        assert bridge.parse_calls == []  # gate fired before any transport

    def test_failed_state_refuses(self) -> None:
        mgr = _ready_manager()
        # Degrade READY → FAILED via a lost health re-probe.
        clear_parser_channel_bindings()
        register_parser_health_probe(lambda endpoint: False)
        assert mgr.check_health() is False
        assert mgr.state is GuestParserState.FAILED
        set_guest_parser_bridge(_FakeBridge(frames=_response_frames()))  # type: ignore[arg-type]
        assert mgr.parse_html("<html><body><p>hi</p></body></html>") is None


class TestParseHtmlBridgePath:
    def test_returns_decoded_response(self) -> None:
        mgr = _ready_manager()
        bridge = _FakeBridge(frames=_response_frames(status="clean"))
        set_guest_parser_bridge(bridge)  # type: ignore[arg-type]

        result = mgr.parse_html(
            "<html><head><title>Minutes</title></head><body>"
            "<article><p>The committee met.</p></article></body></html>",
            source_url="https://example.org/minutes",
        )
        assert result is not None
        assert result.status == "clean"
        assert result.title == "Minutes"
        assert "committee" in result.text
        # The bridge was handed encoded request frames for the same endpoint.
        assert len(bridge.parse_calls) == 1
        endpoint, frames = bridge.parse_calls[0]
        assert endpoint.vsock_port == 50001
        assert frames and all(isinstance(f, bytes) for f in frames)

    def test_error_status_decoded_and_returned(self) -> None:
        mgr = _ready_manager()
        set_guest_parser_bridge(
            _FakeBridge(
                frames=_response_frames(
                    status="error", text="", error_code="PARSER_INTERNAL_ERROR"
                )
            )  # type: ignore[arg-type]
        )
        result = mgr.parse_html("<html><body><p>x</p></body></html>")
        assert result is not None
        assert result.status == "error"
        assert result.error_code == "PARSER_INTERNAL_ERROR"

    def test_none_when_bridge_returns_none(self) -> None:
        mgr = _ready_manager()
        set_guest_parser_bridge(_FakeBridge(frames=None))  # type: ignore[arg-type]
        assert mgr.parse_html("<html><body><p>x</p></body></html>") is None

    def test_none_when_bridge_raises(self) -> None:
        mgr = _ready_manager()
        set_guest_parser_bridge(_FakeBridge(raise_exc=RuntimeError("boom")))  # type: ignore[arg-type]
        assert mgr.parse_html("<html><body><p>x</p></body></html>") is None

    def test_none_when_bridge_returns_garbled_frames(self) -> None:
        mgr = _ready_manager()
        set_guest_parser_bridge(_FakeBridge(frames=[b"not-a-valid-frame"]))  # type: ignore[arg-type]
        assert mgr.parse_html("<html><body><p>x</p></body></html>") is None


class TestParseHtmlFailClosedEncode:
    def test_oversize_body_refused_before_transport(self) -> None:
        mgr = _ready_manager()
        bridge = _FakeBridge(frames=_response_frames())
        set_guest_parser_bridge(bridge)  # type: ignore[arg-type]
        oversize = "x" * (PARSE_BODY_MAX_BYTES + 1)
        assert mgr.parse_html(oversize) is None
        assert bridge.parse_calls == []  # encode refused; never reached the guest

    def test_bad_source_url_dropped_not_fatal(self) -> None:
        """A non-ASCII / over-long source_url is dropped to '' — the fetch is
        still parsed (the URL is only extractor-heuristic metadata)."""
        mgr = _ready_manager()
        set_guest_parser_bridge(_FakeBridge(frames=_response_frames()))  # type: ignore[arg-type]
        result = mgr.parse_html(
            "<html><body><article><p>The committee met.</p></article></body></html>",
            source_url="https://exámple.org/\x00bad" + "z" * 5000,
        )
        assert result is not None and result.status == "clean"


class TestMtlsConfigPlumbing:
    """The dormant mTLS host-side plumbing (#655 go-live prep)."""

    def test_shipped_default_mtls_is_empty(self) -> None:
        from launcher.guest_parser import load_guest_parser_config

        cfg = load_guest_parser_config()
        assert cfg.mtls_cert == "" and cfg.mtls_key == "" and cfg.mtls_ca == ""

    def test_configured_mtls_paths_load(self, tmp_path) -> None:
        from launcher.guest_parser import load_guest_parser_config

        toml = tmp_path / "default.toml"
        toml.write_text(
            "[guest_parser]\n"
            "enabled = false\n"
            'mtls_cert = "C:/certs/parser.crt"\n'
            'mtls_key = "C:/certs/parser.key"\n'
            'mtls_ca = "C:/certs/ca.crt"\n',
            encoding="utf-8",
        )
        cfg = load_guest_parser_config(toml)
        assert cfg.mtls_cert == "C:/certs/parser.crt"
        assert cfg.mtls_key == "C:/certs/parser.key"
        assert cfg.mtls_ca == "C:/certs/ca.crt"

    def test_parse_html_threads_mtls_to_round_trip(self, monkeypatch) -> None:
        """parse_html passes the config's mTLS material to parse_round_trip —
        so a future cert provisioning activates mTLS with no code change."""
        import launcher.guest_parser_health as health_mod

        captured: dict = {}

        def _fake_round_trip(endpoint, frames, *, mtls_cert="", mtls_key="", mtls_ca=""):
            captured["mtls"] = (mtls_cert, mtls_key, mtls_ca)
            return None

        monkeypatch.setattr(health_mod, "parse_round_trip", _fake_round_trip)
        mgr = _manager(mtls_cert="c", mtls_key="k", mtls_ca="a")
        register_parser_health_probe(lambda endpoint: True)
        assert mgr.start() is True
        assert mgr.parse_html("<html><body><p>hi there world</p></body></html>") is None
        assert captured["mtls"] == ("c", "k", "a")


class TestParseRoundTripNoTransport:
    def test_no_bridge_no_afhyperv_returns_none(self) -> None:
        """On the 3.11 runtime with no bridge parked there is no path to the
        guest — parse_round_trip is fail-closed None (never raises)."""
        endpoint = ParserEndpoint(
            vm_id="9c7f986f-7afd-48b0-af5b-2c330df6b38f",
            service_guid=hv_service_guid_for_port(50001),
            vsock_port=50001,
            timeout_s=1.0,
        )
        assert parse_round_trip(endpoint, _response_frames()) is None
