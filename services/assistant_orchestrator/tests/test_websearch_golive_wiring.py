"""#719 Part B — web_search go-live build: conditional registration matrix +
the end-to-end dormant chain.

WHAT THIS PROVES (all offline — the egress door is mocked at the seam; no
socket, no DNS, no DPAPI):

  1. THE REAL CONFIG DEFAULT: services/assistant_orchestrator/config/
     default.toml ships ``[web_search].enabled = true`` (LIVE since the
     2026-07-02 go-live ceremony, runbook step 4) — parsed with the real
     tomllib, not assumed. The registration matrix below still proves every
     dormant cell (flag off / key absent) via constructed configs.
  2. THE FLAG x KEY REGISTRATION MATRIX on the REAL
     ``_maybe_register_web_search``: registration happens ONLY at
     (enabled=true AND key loads); every other cell — including
     enabled=true + no key — stays structurally dormant. A pre-existing
     egress-door adjudicator is never clobbered; a loader error refuses;
     stop() re-welds exactly what start() wired.
  3. NEVER-LOGGED: the sentinel key value reaches no log record across the
     full registration path.
  4. THE FULL DORMANT CHAIN, END TO END through the REAL tool loop with the
     REAL runner over the REAL LiveKagiAdapter and a MOCKED door:
       - empty allowlist -> the D4 loop-level RULE-3 deny fires FIRST; the
         runner (and therefore the door) is never consulted;
       - allowlist populated (post-ceremony simulation) but the door still
         denying -> the deterministic failure notice on the plain note path
         (session not locked);
       - allowlist populated + the door returning a Kagi-shaped body -> the
         shaped results ground as UNTRUSTED_WEB (datamarked, action-locked
         Layer-3 feedstock, but EXEMPT from the Stage-5 leakage feed per
         ADR-023 Amendment 3) — never spliced raw.

Uses the established loop harness from test_retrieval_tools (fake transport
+ mocked inference + PGOV patched to approve).
"""

from __future__ import annotations

import dataclasses
import logging
import tomllib
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import MagicMock, patch

import pytest

import shared.secrets.kagi_key_loader as kagi_key_loader_mod
import shared.security.guarded_fetch as guarded_fetch_mod
from services.assistant_orchestrator.src import tools
from services.assistant_orchestrator.src.context_manager import Provenance
from services.assistant_orchestrator.src.websearch.live_adapter import (
    KAGI_SEARCH_ENDPOINT,
)
from services.assistant_orchestrator.tests.test_retrieval_tools import (
    _allowlist_rewelded,
    _FakeTransport,
    _kagi_allowlisted,
    _make_resolved_config,
    _make_service,
    _native_call,
    _pgov_approved,
)
from shared.ipc.protocol import MessageFramer
from shared.secrets.kagi_key_loader import KagiApiKey
from shared.security.guarded_fetch import FetchResult

# Obviously-fake sentinel — NEVER a real-looking key.
_SENTINEL = "FAKE-TEST-SENTINEL-KAGI-KEY-wiring"

_DEFAULT_TOML = (
    Path(__file__).resolve().parents[1] / "config" / "default.toml"
)


@pytest.fixture(autouse=True)
def _pristine_seams() -> Any:
    """Every test starts and ends with the shipped dormant posture: no
    web_search runner, no egress-door adjudicator."""
    tools.clear_web_search_runner()
    guarded_fetch_mod.clear_url_adjudicator()
    yield
    tools.clear_web_search_runner()
    guarded_fetch_mod.clear_url_adjudicator()


def _resolved(web_search_enabled: bool) -> Any:
    return dataclasses.replace(
        _make_resolved_config(), web_search_enabled=web_search_enabled
    )


def _patch_key(monkeypatch: pytest.MonkeyPatch, key: KagiApiKey | None) -> None:
    monkeypatch.setattr(
        kagi_key_loader_mod, "load_wrapped_kagi_key", lambda: key
    )


def _drive(
    service: Any, session: str, responses: list[SimpleNamespace]
) -> tuple[list[str], Any]:
    """Run one prompt through the REAL _handle_prompt_request loop (the
    established test_retrieval_tools harness shape, replicated here rather
    than imported so pytest never re-collects that module's test class)."""
    framer = MessageFramer()
    service._inference = MagicMock()
    captured: list[str] = []

    def _capturing_generate(context_arg: str, **_kwargs: Any) -> SimpleNamespace:
        captured.append(context_arg)
        return responses.pop(0)

    service._inference.generate_text.side_effect = _capturing_generate
    request = framer.encode_prompt_request(
        session_id=session,
        prompt="What is new with OpenVINO?",
        request_id=f"r-{session}",
    )
    transport = _FakeTransport(request)
    service._handle_connection(transport)
    service._test_sent_frames = transport.sent
    return captured, service


# ---------------------------------------------------------------------------
# 1. The real shipped config default.
# ---------------------------------------------------------------------------


class TestShippedConfigDefault:
    def test_default_toml_ships_web_search_enabled(self) -> None:
        """THE REAL CONFIG DEFAULT (not a fixture — the REVIEWED flip of the
        pre-ceremony false-pin at the 2026-07-02 go-live, runbook step 4):
        [web_search].enabled is present and TRUE in the shipped default.toml.
        The flag is one of the three re-weld handles (flag off / allowlist
        emptied / key blob deleted — each independently restores dormancy);
        flipping it back off is re-weld step 1 and must flip THIS lock in the
        same reviewed change."""
        with open(_DEFAULT_TOML, "rb") as fh:
            config = tomllib.load(fh)
        assert "web_search" in config, "[web_search] section missing"
        assert config["web_search"]["enabled"] is True

    def test_dataclass_default_is_dormant(self) -> None:
        """An OLDER config with no [web_search] section resolves dormant."""
        assert _make_resolved_config().web_search_enabled is False


# ---------------------------------------------------------------------------
# 2. The flag x key registration matrix (the REAL registrar).
# ---------------------------------------------------------------------------


class TestWebSearchConditionalRegistration:
    def test_flag_off_key_present_stays_dormant(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_key(monkeypatch, KagiApiKey(_SENTINEL))
        service = _make_service()
        assert service._maybe_register_web_search(_resolved(False)) is False
        assert tools._WEB_SEARCH_RUNNER is None
        assert guarded_fetch_mod.active_url_adjudicator() is None

    def test_flag_on_no_key_stays_dormant(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """enabled=true + an absent/empty/malformed key (loader -> None) is
        STILL dormant — the flag alone can never light web_search up."""
        _patch_key(monkeypatch, None)
        service = _make_service()
        with caplog.at_level(logging.WARNING):
            assert service._maybe_register_web_search(_resolved(True)) is False
        assert tools._WEB_SEARCH_RUNNER is None
        assert guarded_fetch_mod.active_url_adjudicator() is None
        assert "no usable Kagi API key" in caplog.text

    def test_flag_on_key_present_registers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_key(monkeypatch, KagiApiKey(_SENTINEL))
        service = _make_service()
        assert service._maybe_register_web_search(_resolved(True)) is True
        assert tools._WEB_SEARCH_RUNNER is not None
        # The deterministic door adjudicator was wired (none pre-existed).
        assert guarded_fetch_mod.active_url_adjudicator() is not None
        assert service._web_search_door_adjudicator_registered is True

    def test_preexisting_door_adjudicator_never_clobbered(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Another consumer's adjudicator (e.g. the UC-003 go-live wiring)
        survives web_search registration untouched."""
        _patch_key(monkeypatch, KagiApiKey(_SENTINEL))

        def _preexisting(url: str, purpose: str) -> Any:
            return guarded_fetch_mod.Verdict.DENY

        guarded_fetch_mod.register_url_adjudicator(_preexisting)
        service = _make_service()
        assert service._maybe_register_web_search(_resolved(True)) is True
        assert guarded_fetch_mod.active_url_adjudicator() is _preexisting
        assert service._web_search_door_adjudicator_registered is False

    def test_loader_error_refuses_fail_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom() -> KagiApiKey | None:
            raise RuntimeError("keystore exploded")

        monkeypatch.setattr(kagi_key_loader_mod, "load_wrapped_kagi_key", _boom)
        service = _make_service()
        assert service._maybe_register_web_search(_resolved(True)) is False
        assert tools._WEB_SEARCH_RUNNER is None

    def test_stop_rewelds_exactly_what_start_wired(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_key(monkeypatch, KagiApiKey(_SENTINEL))
        service = _make_service()
        assert service._maybe_register_web_search(_resolved(True)) is True
        service.stop()
        assert tools._WEB_SEARCH_RUNNER is None
        assert guarded_fetch_mod.active_url_adjudicator() is None
        assert service._web_search_door_adjudicator_registered is False

    def test_stop_never_clears_another_consumers_adjudicator(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_key(monkeypatch, KagiApiKey(_SENTINEL))

        def _preexisting(url: str, purpose: str) -> Any:
            return guarded_fetch_mod.Verdict.DENY

        guarded_fetch_mod.register_url_adjudicator(_preexisting)
        service = _make_service()
        service._maybe_register_web_search(_resolved(True))
        service.stop()
        assert guarded_fetch_mod.active_url_adjudicator() is _preexisting

    def test_key_never_logged_across_registration(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """NEVER-LOGGED LOCK across the full boot registration path — the
        sentinel key value reaches no record."""
        _patch_key(monkeypatch, KagiApiKey(_SENTINEL))
        service = _make_service()
        with caplog.at_level(logging.DEBUG):
            assert service._maybe_register_web_search(_resolved(True)) is True
        assert _SENTINEL not in caplog.text


# ---------------------------------------------------------------------------
# 3. The full chain, end to end (REAL loop + REAL runner + MOCKED door).
# ---------------------------------------------------------------------------


def _register_live_runner(
    monkeypatch: pytest.MonkeyPatch,
    service: Any,
    door: Callable[[str], FetchResult],
) -> list[dict[str, Any]]:
    """Wire the REAL registrar (flag on + sentinel key) over a mocked door.

    Returns the door-call recording list — empty means the door was never
    consulted.
    """
    calls: list[dict[str, Any]] = []

    def _fake_fetch_external(
        url: str,
        *,
        purpose: str,
        timeout_s: float = 30.0,
        authorization=None,
        method: str = "GET",
        json_body=None,
    ) -> FetchResult:
        calls.append(
            {
                "url": url,
                "purpose": purpose,
                "authorization": authorization,
                "method": method,
                "json_body": json_body,
            }
        )
        return door(url)

    monkeypatch.setattr(guarded_fetch_mod, "fetch_external", _fake_fetch_external)
    _patch_key(monkeypatch, KagiApiKey(_SENTINEL))
    assert service._maybe_register_web_search(_resolved(True)) is True
    return calls


_KAGI_BODY = (
    '{"meta": {"id": "m", "node": "n", "ms": 5}, "data": {"search": ['
    '{"url": "https://news.example/openvino",'
    ' "title": "OpenVINO 2026.3 released", "snippet": "The release adds…",'
    ' "time": "2026-07-01"}], "infobox": []}}'
)


def _door_success(url: str) -> FetchResult:
    return FetchResult(
        url=url,
        status=200,
        content_text=_KAGI_BODY,
        content_type="application/json",
        denied_reason=None,
    )


def _door_denied(url: str) -> FetchResult:
    return FetchResult(
        url=url,
        denied_reason="policy: no Policy-Agent adjudicator registered "
        "(fail-closed default)",
    )


class TestFullChainThroughTheLoop:
    @patch("services.assistant_orchestrator.src.entrypoint.validate_output")
    def test_rewelded_chain_denies_before_the_door(
        self, mock_validate_output: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """THE RE-WELD CHAIN (#719 — the REVIEWED flip of the pre-ceremony
        dormant-chain lock, which proved the same deny on the then-empty
        shipped default): flag on + key present + runner registered — and
        with the allowlist RE-WELDED empty (re-weld step 2,
        docs/runbooks/web_search_go_live.md) STILL nothing reaches the door,
        because the D4 loop-level RULE-3 deny refuses the dispatch before
        execution. Emptying the ONE allowlist alone restores full dormancy
        even with everything else live."""
        mock_validate_output.side_effect = _pgov_approved
        service = _make_service()
        door_calls = _register_live_runner(monkeypatch, service, _door_success)
        responses = [
            SimpleNamespace(
                text=_native_call("web_search", {"query": "openvino news"}),
                token_count=8,
                error=None,
            ),
        ]
        with _allowlist_rewelded():
            captured, service = _drive(service, "chain-dormant", responses)
        assert len(captured) == 1  # loop broke at the PA deny
        assert door_calls == [], "the door must never be consulted while dormant"
        cm = service._context_manager
        assert not cm.has_untrusted_content("chain-dormant")
        assert cm.get_grounded_provenance("chain-dormant") == []

    @patch("services.assistant_orchestrator.src.entrypoint.request_egress_fingerprint", return_value=True)
    @patch("services.assistant_orchestrator.src.entrypoint.validate_output")
    def test_post_ceremony_door_denial_yields_notice_not_lock(
        self, mock_validate_output: MagicMock, mock_fingerprint: MagicMock,
        monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Allowlist populated (ceremony simulated) AND the egress fingerprint
        approved (#723 rung 3), but the DOOR still denying: the adapter
        fail-closes to no results, the tool returns the deterministic failure
        notice on the plain note path, and the session is NOT locked (a refusal
        carries no retrieved content)."""
        mock_validate_output.side_effect = _pgov_approved
        service = _make_service()
        door_calls = _register_live_runner(monkeypatch, service, _door_denied)
        responses = [
            SimpleNamespace(
                text=_native_call("web_search", {"query": "openvino news"}),
                token_count=8,
                error=None,
            ),
            SimpleNamespace(
                text="I could not search the web.", token_count=6, error=None
            ),
        ]
        with _kagi_allowlisted():
            captured, service = _drive(service, "chain-door-denied", responses)
        assert len(captured) == 2
        assert len(door_calls) == 1  # the loop released; the DOOR refused
        assert tools.WEB_SEARCH_ERROR_NOTICE in captured[1]
        cm = service._context_manager
        assert not cm.has_untrusted_content("chain-door-denied")

    @patch("services.assistant_orchestrator.src.entrypoint.request_egress_fingerprint", return_value=True)
    @patch("services.assistant_orchestrator.src.entrypoint.validate_output")
    def test_post_ceremony_success_grounds_untrusted_web(
        self, mock_validate_output: MagicMock, mock_fingerprint: MagicMock,
        monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The full live shape, offline: loop-level allow (allowlist) + the
        egress fingerprint approved (#723 rung 3) -> runner -> adapter -> mocked
        door 200 with a Kagi body -> shaped title/url/snippet result -> grounded
        UNTRUSTED_WEB (datamarked, action-locked, but EXEMPT from the Stage-5
        leakage feed per ADR-023 Amendment 3, so a faithful relay is not held) —
        never spliced raw."""
        mock_validate_output.side_effect = _pgov_approved
        service = _make_service()
        door_calls = _register_live_runner(monkeypatch, service, _door_success)
        responses = [
            SimpleNamespace(
                text=_native_call("web_search", {"query": "openvino news"}),
                token_count=8,
                error=None,
            ),
            SimpleNamespace(
                text="OpenVINO 2026.3 is out.", token_count=6, error=None
            ),
        ]
        with _kagi_allowlisted():
            captured, service = _drive(service, "chain-live", responses)
        assert len(captured) == 2
        assert len(door_calls) == 1
        call = door_calls[0]
        # v1: a POST to the bare endpoint; query in the JSON body, Bearer auth.
        assert call["url"] == KAGI_SEARCH_ENDPOINT
        assert call["method"] == "POST"
        assert call["json_body"] == {"query": "openvino news"}
        assert call["purpose"] == "web_search"
        assert call["authorization"] == f"Bearer {_SENTINEL}"
        cm = service._context_manager
        # MUST-NOT-WEAKEN: the action-lock still trips on the web result.
        assert cm.has_untrusted_content("chain-live")
        assert Provenance.UNTRUSTED_WEB in cm.get_grounded_provenance(
            "chain-live"
        )
        assert Provenance.UNTRUSTED_EXTERNAL not in cm.get_grounded_provenance(
            "chain-live"
        )
        # ADR-023 Amendment 3: web content is EXEMPT from the Stage-5 leakage
        # feed (a faithful relay of public results is not held as a leak).
        feed = cm.get_untrusted_chunk_texts("chain-live")
        assert not any("OpenVINO 2026.3 released" in text for text in feed)
        assert feed == []
        # The shaped result was grounded, not spliced raw into the context.
        assert "added to the grounded context above" in captured[1]

    @patch("services.assistant_orchestrator.src.entrypoint.validate_output")
    def test_key_never_logged_across_the_full_chain(
        self,
        mock_validate_output: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """The sentinel never reaches a record across registration + a full
        loop turn (both the re-welded-deny and the live-allowlisted path)."""
        mock_validate_output.side_effect = _pgov_approved
        service = _make_service()
        _register_live_runner(monkeypatch, service, _door_success)
        with caplog.at_level(logging.DEBUG):
            responses = [
                SimpleNamespace(
                    text=_native_call("web_search", {"query": "q"}),
                    token_count=8,
                    error=None,
                ),
            ]
            with _allowlist_rewelded():
                _drive(service, "chain-log-a", responses)
            with _kagi_allowlisted():
                responses = [
                    SimpleNamespace(
                        text=_native_call("web_search", {"query": "q"}),
                        token_count=8,
                        error=None,
                    ),
                    SimpleNamespace(text="Done.", token_count=2, error=None),
                ]
                _drive(service, "chain-log-b", responses)
        assert _SENTINEL not in caplog.text
