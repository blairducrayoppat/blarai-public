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

import ast
import dataclasses
import json
import logging
import tomllib
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import MagicMock, patch

import pytest

import shared.secrets.kagi_key_loader as kagi_key_loader_mod
import shared.security.guarded_fetch as guarded_fetch_mod
from services.assistant_orchestrator.src import entrypoint, tools
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

#: The Known-Good Manifest the config resolver validates before returning. The
#: weights are gitignored, so this is absent in an isolated worktree and present
#: in the primary checkout — the documented environment delta, named here rather
#: than discovered as a confusing resolver error.
#:
#: **parents[3] is the REPO ROOT and getting it wrong is silent.** The first
#: version of this used parents[1] (the service directory), a path that exists in
#: NEITHER checkout, so the skip fired everywhere and the test it guards ran
#: nowhere — while its skip message claimed it runs in the primary. A test that
#: cannot execute is the built-but-wired-into-nothing shape wearing a skip mark,
#: and nothing in a green run points at it. `test_the_env_skip_predicate_is_REAL`
#: below is the control: it derives this path from the shipped config and fails
#: loudly if the two ever disagree again.
_KGM_MANIFEST = (
    Path(__file__).resolve().parents[3]
    / "models"
    / "qwen3-14b"
    / "openvino-int4-gpu"
    / "manifest.json"
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


def _streamed_text(service: Any) -> str:
    """The text the operator's client would render, decoded from the frames.

    Not ``str(frame)``: that is a repr of JSON-encoded bytes, in which a single
    backslash in the disclosure appears as four. A test asserting on a transport
    encoding, when the claim is about what a human reads, is measuring the wrong
    string (#1592 r3).
    """
    out: list[str] = []
    for frame in getattr(service, "_test_sent_frames", []):
        raw = frame.decode("utf-8", "replace") if isinstance(frame, bytes) else str(frame)
        for start in range(len(raw)):
            if raw[start] != "{":
                continue
            try:
                payload = json.loads(raw[start:])
            except json.JSONDecodeError:
                continue
            body = payload.get("payload") or {}
            for key in ("token", "text", "message"):
                value = body.get(key)
                if isinstance(value, str):
                    out.append(value)
            break
    return "".join(out)


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


def _assert_the_fallback_reads_the_dataclass_default() -> None:
    """The consent grain must be written down ONCE, checked by AST (#1594).

    The claim is structural: the second argument to
    ``egress.get("searches_per_fingerprint", ...)`` is an attribute read, never a
    literal. An earlier version of this lock matched source TEXT, and the review
    demonstrated three semantics-preserving edits that failed it — collapsing the
    call to one line, splitting the attribute across two, and referring to the
    class through a module alias. Each was told it had "lost the structural
    guarantee" while keeping it exactly.

    That is worse than a weak lock. A security test that fires on a line break,
    and accuses the developer of a regression they did not make, teaches people to
    edit the lock. Matching the AST asserts the thing the claim is actually about
    and is immune to all three, while still killing a restored literal of ANY
    value — the text version only named ``1``, so restoring the old ``3`` slipped
    past the assertion written for it and was caught by the other one, with a
    misleading message. Precedent for AST over text:
    ``tests/security/test_denied_turn_persistence.py``.
    """
    tree = ast.parse(Path(entrypoint.__file__).read_text(encoding="utf-8"))

    fallbacks = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "searches_per_fingerprint"
    ]
    assert len(fallbacks) == 1, (
        f"expected exactly one `.get(\"searches_per_fingerprint\", ...)` in "
        f"entrypoint.py, found {len(fallbacks)}. More than one resolution site "
        "means the consent grain is read in two places and they can disagree"
    )

    call = fallbacks[0]
    assert len(call.args) == 2, (
        "the searches_per_fingerprint lookup has no default argument, so an "
        "older config missing the key raises instead of resolving — or resolves "
        "to None and clamps somewhere unexamined"
    )

    default = call.args[1]
    assert not isinstance(default, ast.Constant), (
        f"the .get() fallback has a LITERAL default again "
        f"({default.value!r} at line {default.lineno}). The consent grain must be "
        "written down once: a literal here is a second number that drifts "
        "silently, and it drifts in the LOOSER direction, because nothing "
        "complains when a limit is too permissive (#1594)"
    )
    assert isinstance(default, ast.Attribute), (
        f"the .get() fallback default is a {type(default).__name__} at line "
        f"{default.lineno}; it must be an attribute read of the dataclass default"
    )
    assert default.attr == "egress_searches_per_fingerprint", (
        f"the .get() fallback reads `.{default.attr}` at line {default.lineno}, "
        "not the dataclass's own egress_searches_per_fingerprint — so the two "
        "surviving copies of this value are no longer the same value"
    )


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

    def test_EVERY_searches_per_fingerprint_default_agrees_with_the_shipped_config(
        self,
    ) -> None:
        """#1594 — one consent value, and it used to be written down three times.

        `searches_per_fingerprint` used to live in THREE places: the shipped
        `default.toml`, the entrypoint-config dataclass default, and a literal in
        the `.get()` fallback that resolves the file. The file is the authority;
        the other two decide what happens when the key is ABSENT — an older
        config, a trimmed deployment, a partial file.

        Changing only the file leaves a value that silently reappears the moment
        the key is missing, and it reappears LOOSER: both stale copies said 3, so
        a config without the key would have gone back to one fingerprint covering
        three searches with nothing saying so. A consent grain that can drift
        upward through absence is not a consent grain.

        **The third place is now gone rather than guarded** — the `.get()` fallback
        reads the dataclass default instead of repeating it, so there is no second
        number to keep in step (`security_by_design` 4, structural absence over
        vigilance). This holds the two that remain, and asserts they AGREE rather
        than asserting the number, so a later tightening does not need a test edit
        to notice.
        """
        with open(_DEFAULT_TOML, "rb") as fh:
            shipped = tomllib.load(fh)["egress"]["searches_per_fingerprint"]

        assert (
            _make_resolved_config().egress_searches_per_fingerprint == shipped
        ), (
            "the dataclass default disagrees with the shipped default.toml, so a "
            "config missing the key — and anything constructing the config "
            "without resolving a file at all — gets a different consent grain "
            "than the one that was reviewed"
        )

        _assert_the_fallback_reads_the_dataclass_default()

    @pytest.mark.skipif(
        not _KGM_MANIFEST.exists(),
        reason=(
            "gitignored model weights absent: _load_entrypoint_config validates "
            "the Known-Good Manifest path before returning, so the REAL resolver "
            "cannot be driven to success without them. Same bounded, documented "
            "environment delta as the semantic-router tests — it RUNS in the "
            "primary checkout, where the gate baseline is measured (verified: the "
            "resolver there returns manifest_path under the repo root), and "
            "env-skips in a worktree"
        ),
    )
    @pytest.mark.parametrize(
        ("label", "mutate"),
        [
            ("key present", lambda cfg: cfg),
            ("key ABSENT", lambda cfg: {**cfg, "egress": {
                k: v for k, v in cfg.get("egress", {}).items()
                if k != "searches_per_fingerprint"
            }}),
            ("[egress] section ABSENT", lambda cfg: {
                k: v for k, v in cfg.items() if k != "egress"
            }),
        ],
    )
    def test_an_OLDER_CONFIG_still_resolves_to_the_shipped_consent_grain(
        self, label: str, mutate: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The `.get()` fallback, driven through the REAL resolver (#1594).

        Nothing in the suite reached this path. `_make_resolved_config()`
        constructs the dataclass directly, so the agreement test above compares
        the dataclass to the file and never executes the line that resolves one
        from the other. The review closed that gap by measurement and recommended
        it be closed by a test; this is the test.

        My first attempt wrote a trimmed config into a temporary directory and it
        failed on path resolution — `_load_entrypoint_config` derives the service
        and repository roots from the config file's LOCATION, so a temp dir is not
        somewhere a config can live. Faking the read at the `tomllib.load` seam
        keeps the real path chain, the real validation and the real construction,
        and varies only the one thing under test: whether the key is there.

        The absent cases are the ones that matter. An older config, a trimmed
        deployment, a partial file — each resolves through the fallback, and
        before #1594 the fallback held its own literal `3` while the shipped file
        said `1`. That failure mode is silent and it is LOOSE.
        """
        with open(_DEFAULT_TOML, "rb") as fh:
            shipped_data = tomllib.load(fh)
        shipped = shipped_data["egress"]["searches_per_fingerprint"]

        service = _make_service()
        # The harness service carries a `dummy.toml` path and host mode requires
        # `default.toml` by NAME, so the resolver refuses it before reading a
        # byte. Point it at the real file: the path chain, the deployment-mode
        # check and the validation all then run for real, and only the parsed
        # CONTENT is varied.
        monkeypatch.setattr(
            type(service), "_resolve_config_path", lambda _self: _DEFAULT_TOML
        )
        monkeypatch.setattr(
            entrypoint.tomllib, "load", lambda _fh: mutate(shipped_data)
        )
        resolved = service._load_entrypoint_config()

        assert resolved.egress_searches_per_fingerprint == shipped, (
            f"{label}: resolved to {resolved.egress_searches_per_fingerprint}, "
            f"not the shipped {shipped}. A config without the key must resolve to "
            "the same consent grain that was reviewed, or the grain silently "
            "depends on whether a line is present"
        )
        assert isinstance(resolved.egress_searches_per_fingerprint, int), (
            f"{label}: resolved to a "
            f"{type(resolved.egress_searches_per_fingerprint).__name__}, not an "
            "int — a dataclasses.Field or None would mean the service fails to "
            "start on any config missing this key, and nothing else would catch it"
        )

    def test_the_env_skip_predicate_is_REAL(self) -> None:
        """An env-skip that can never lift is a test that never runs (#1594 r3).

        `_KGM_MANIFEST` decides whether the test above executes. Its first version
        pointed at the SERVICE directory rather than the repo root — a path that
        exists in neither the worktree nor the primary — so the skip fired
        everywhere, the test ran nowhere, and its own skip message asserted the
        opposite. The post-merge gate read 3 skipped where 0 was predicted, and
        that number has two possible causes with OPPOSITE responses: my three
        tests skipping, or a non-elevated run's symlink delta. They are
        indistinguishable from the count alone.

        This derives the same path from the shipped config, so the two can never
        drift apart silently again. It needs no model weights and runs everywhere,
        which is the point: the control on a conditional skip must not share the
        skip's condition.
        """
        with open(_DEFAULT_TOML, "rb") as fh:
            declared = tomllib.load(fh)["gpu"]["weight_manifest"]

        repo_root = Path(__file__).resolve().parents[3]
        assert _KGM_MANIFEST == repo_root / declared, (
            f"the env-skip predicate names {_KGM_MANIFEST}, but the shipped "
            f"config declares weight_manifest = {declared!r}, which resolves to "
            f"{repo_root / declared}. The skip would fire on the wrong condition "
            "and the test it guards would never run"
        )

    def test_the_shipped_consent_grain_is_ONE_FINGERPRINT_PER_QUERY(self) -> None:
        """The value itself, asserted once and deliberately (#1594).

        The test above holds the three places in agreement; this one records WHICH
        value was decided, so raising it is a visible, reviewed edit rather than a
        quiet config change that the agreement test would happily follow.

        Raising N is a posture LOOSENING — it lets a later search ride on an
        approval given for an earlier, different string — so it is the LA's call
        and should cost a failing test to make.
        """
        with open(_DEFAULT_TOML, "rb") as fh:
            config = tomllib.load(fh)
        assert config["egress"]["searches_per_fingerprint"] == 1, (
            "searches_per_fingerprint is no longer 1. N>1 means a fingerprint "
            "covers queries the operator never affirmatively approved; that is a "
            "posture loosening and needs an LA decision recorded on a ticket, not "
            "a config edit (#1594)"
        )


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


class TestAnUndisclosableQueryNeverReachesTheDoor:
    # NOTE (#1592 r3): "undisclosable" now means ONE thing — too long to show in
    # full. Characters that hide a string's tail are escaped into visibility
    # rather than refused, so they have their own test here, asserting the
    # disclosure rather than a refusal.
    """#1592 — the REFUSAL path, driven through the real loop.

    `extract_query` raising is only half the control. The other half is what the
    caller does with it: catch, record a verdict receipt, and BREAK the tool loop.
    Six unit locks covered the raising; nothing covered the catching, and two
    mutants of it survived the entire suite — including `break` -> `continue`,
    which sends a later search while the operator is told nothing was sent.

    These assert on the DOOR-CALL RECORDING, which is the only artifact that can
    tell a refusal that stopped the send from one that merely logged about it.
    """

    @patch("services.assistant_orchestrator.src.entrypoint.request_egress_fingerprint", return_value=True)
    @patch("services.assistant_orchestrator.src.entrypoint.validate_output")
    def test_a_too_LONG_query_never_reaches_the_door(
        self, mock_validate_output: MagicMock, mock_fingerprint: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The query cannot be shown in full, so nothing is sent — and the Hello
        prompt is never raised, because there is nothing honest to show."""
        mock_validate_output.side_effect = _pgov_approved
        service = _make_service()
        door_calls = _register_live_runner(monkeypatch, service, _door_success)

        long_query = "openvino release notes " * 40  # comfortably over the cap
        responses = [
            SimpleNamespace(
                text=_native_call("web_search", {"query": long_query}),
                token_count=8,
                error=None,
            ),
        ]
        captured, service = _drive(service, "undisclosable-long", responses)

        assert door_calls == [], (
            "a query too long to disclose reached the egress door — the refusal "
            "logged and did not stop the send"
        )
        assert len(captured) == 1, (
            "the tool loop continued past the refusal; a later dispatch in the "
            "same turn can still reach the door"
        )
        assert mock_fingerprint.call_count == 0, (
            "the Hello prompt was raised for a query that cannot be shown in full"
        )

    @patch("services.assistant_orchestrator.src.entrypoint.request_egress_fingerprint", return_value=True)
    @patch("services.assistant_orchestrator.src.entrypoint.validate_output")
    def test_a_SHORT_query_that_hides_its_tail_is_DISCLOSED_BEFORE_it_is_sent(
        self, mock_validate_output: MagicMock, mock_fingerprint: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Thirty-two characters, well under the cap, with its tail scrolled off
        by newlines. This is the case a length cap cannot see.

        **This lock changed shape at the second review, and the change is the
        point.** It used to assert the query never reached the door, because the
        first fix REFUSED such queries. Refusing was over-broad — the same rule
        denied Persian and Devanagari searches, which need U+200C/U+200D as
        ordinary orthography — so the query is now ESCAPED into visibility
        instead, shown to the operator in full, and sent only if they approve.

        So the guarantee to hold is no longer "nothing was sent". It is that the
        string the operator READ contained the tail that had been hiding. If the
        frame carried the raw newlines instead, the operator would be approving a
        string whose tail is scrolled off the screen — the original defect,
        intact, with the whole ticket declared fixed on top of it.
        """
        mock_validate_output.side_effect = _pgov_approved
        service = _make_service()
        door_calls = _register_live_runner(monkeypatch, service, _door_success)

        hidden = "cats" + "\n" * 12 + " ssn 123-45-6789"
        responses = [
            SimpleNamespace(
                text=_native_call("web_search", {"query": hidden}),
                token_count=8,
                error=None,
            ),
            SimpleNamespace(text="here is what I found.", token_count=5, error=None),
        ]
        _captured, service = _drive(service, "undisclosable-hidden", responses)

        shown = _streamed_text(service)
        assert "123-45-6789" in shown, (
            "the planted tail never reached the operator's screen, so they "
            "approved a string they had not seen the end of"
        )
        assert "cats\\u000a" in shown, (
            "the newlines reached the operator's screen RAW — the disclosure "
            "was not rendered, and the tail is scrolled away in whatever "
            "displays it"
        )
        assert "\n" not in shown.split("Searching the web: ", 1)[1].split("\n")[0], (
            "the disclosed query still contains a real newline"
        )
        assert door_calls, (
            "nothing reached the door at all: this fixture is supposed to be "
            "DISCLOSED and then sent, so it is now measuring a refusal path"
        )

    @patch("services.assistant_orchestrator.src.entrypoint.request_egress_fingerprint", return_value=True)
    @patch("services.assistant_orchestrator.src.entrypoint.validate_output")
    def test_the_LOOP_STOPS_so_a_later_search_in_the_same_turn_cannot_slip_out(
        self, mock_validate_output: MagicMock, mock_fingerprint: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """THE MUTANT THAT SURVIVED 3,063 TESTS.

        With `break` replaced by `continue`, the refusal records its verdict, the
        loop carries on, and a SECOND dispatch in the same turn reaches the door —
        while the operator is shown "nothing was sent". This drives exactly that
        sequence: an undisclosable query followed by an ordinary one.

        A test that only asserts the first query was refused cannot see this. The
        second response in the list is the discriminating input.
        """
        mock_validate_output.side_effect = _pgov_approved
        service = _make_service()
        door_calls = _register_live_runner(monkeypatch, service, _door_success)

        responses = [
            SimpleNamespace(
                text=_native_call(
                    "web_search", {"query": "openvino release notes " * 40}
                ),
                token_count=8, error=None,
            ),
            SimpleNamespace(
                text=_native_call("web_search", {"query": "openvino news"}),
                token_count=8, error=None,
            ),
            SimpleNamespace(text="done.", token_count=3, error=None),
        ]
        captured, service = _drive(service, "undisclosable-then-ordinary", responses)

        assert door_calls == [], (
            f"the loop continued past an undisclosable query and sent "
            f"{len(door_calls)} later search(es): {door_calls}. The refusal must "
            "END the turn, not skip one dispatch."
        )
        assert len(captured) == 1, (
            "the model was given a second turn after an undisclosable refusal"
        )

    @patch("services.assistant_orchestrator.src.entrypoint.request_egress_fingerprint", return_value=True)
    @patch("services.assistant_orchestrator.src.entrypoint.validate_output")
    def test_the_OPERATOR_IS_TOLD_THE_TRUTH_about_why_nothing_was_sent(
        self, mock_validate_output: MagicMock, mock_fingerprint: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The refusal reused the Hello-denied help text, which said the
        fingerprint "was not approved" when no prompt was raised, and advised
        asking again — which cannot work, because the refusal is deterministic.

        A summary that contradicts its own correct detail record is the failure
        this entire change exists to fix, so the message is asserted, not trusted.
        """
        mock_validate_output.side_effect = _pgov_approved
        service = _make_service()
        _register_live_runner(monkeypatch, service, _door_success)

        responses = [
            SimpleNamespace(
                text=_native_call(
                    "web_search", {"query": "openvino release notes " * 40}
                ),
                token_count=8, error=None,
            ),
        ]
        _captured, service = _drive(service, "undisclosable-message", responses)

        sent = "".join(str(f) for f in getattr(service, "_test_sent_frames", []))
        assert "nothing was sent" in sent, "the operator is not told the send was refused"
        assert "fingerprint prompt was not approved" not in sent, (
            "the message claims a fingerprint prompt was refused; none was raised"
        )
        assert "fresh fingerprint prompt" not in sent, (
            "the message advises an action that cannot succeed — the refusal is "
            "deterministic, so the identical request fails identically"
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
