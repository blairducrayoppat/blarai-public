"""
P8 write-authority locks (#770 M1) — the OPERATOR is the sole committer.
=========================================================================
The OPERATOR_PREFERENCE tier auto-injects into every turn's system prompt,
which makes its write path a self-modification surface (ADR-022's highest-
risk class) and the MINJA-precondition to kill structurally (design §5): the
model may READ the tier (it is in the prompt) and may someday DRAFT
(M2 ``propose_preference`` — a UI card, never a store write), but a WRITE
reaches the store ONLY through the explicit operator command path
(gateway slash-parse → PREFERENCE_WRITE_REQUEST → the AO handler).

These are STRUCTURAL-ABSENCE locks (the guest-oracle ``transport=None``
precedent): they don't assert a flag is off — they assert the model-reachable
write path DOES NOT EXIST, by registry inspection and by source scan (the
``test_winui_passthrough_allowlist`` source-scan pattern).  Weakening any of
these is a governance decision, not a refactor.
"""

from __future__ import annotations

from pathlib import Path

from services.assistant_orchestrator.src import tools
from services.assistant_orchestrator.src.pgov import TOOL_CALL_ALLOWLIST

_REPO_ROOT = Path(__file__).resolve().parents[3]

#: The preference-write API surface (knowledge_bank methods + the IPC verb).
#: Any NEW write surface must be added here AND justified against P8.
_WRITE_API_NAMES: tuple[str, ...] = (
    "store_preference",
    "update_preference",
    "delete_preference",
)


def _production_py_files(*roots: str) -> list[Path]:
    """All production .py files under *roots* (tests excluded)."""
    files: list[Path] = []
    for root in roots:
        for path in (_REPO_ROOT / root).rglob("*.py"):
            parts = {p.lower() for p in path.parts}
            if "tests" in parts or "test" in parts:
                continue
            files.append(path)
    return files


#: The ONE model-callable tool that may name the preference surface — the M2
#: propose_preference DRAFT tool (#770 M2 W1).  It RENDERS a confirm card and
#: stages verbatim bytes; it has NO store-write path (the write happens only via
#: the operator-typed /remember-confirm, which rides the AO write handler).  Its
#: source isolation from the write channel is enforced by
#: ``TestProposalChannelSourceIsolation`` below (study §5.1).
_PROPOSAL_DRAFT_TOOL: str = "propose_preference"


class TestNoModelCallableWritePath:
    """The tool surface (what the model can invoke) has no preference WRITE.

    M2 adds exactly ONE model-callable tool that names the preference surface —
    ``propose_preference`` — and it is a DRAFT (a card), never a write; the
    structural absence of a model-reachable WRITE path is unchanged.
    """

    def test_only_the_draft_tool_names_the_preference_surface(self) -> None:
        for name in list(tools._REGISTRY) + list(tools.TOOL_SCHEMAS):
            if name == _PROPOSAL_DRAFT_TOOL:
                continue  # the M2 DRAFT surface — a card, never a write
            lowered = name.lower()
            assert "preference" not in lowered and "remember" not in lowered, (
                f"Tool {name!r} references the preference surface — a "
                f"model-callable write path to an auto-injected tier is a "
                f"MINJA-class defect (P8)."
            )

    def test_draft_tool_is_guarded_lock_exempt_and_write_free(self) -> None:
        # propose_preference is a GUARDED DRAFT surface: it can fire under
        # untrusted content (lock-exempt — D-1(a), the card's untrusted-context
        # flag is the weak-signal defense), but it has NO store-write path.
        assert _PROPOSAL_DRAFT_TOOL in tools._REGISTRY
        assert _PROPOSAL_DRAFT_TOOL in tools.TOOL_SCHEMAS
        assert tools.risk_tier(_PROPOSAL_DRAFT_TOOL) is tools.RiskTier.GUARDED
        assert tools.is_lock_exempt(_PROPOSAL_DRAFT_TOOL)

    def test_allowlist_has_no_preference_WRITE_entries(self) -> None:
        # The DRAFT tool is allowlisted (the model may CALL it); no OTHER
        # allowlisted name references the preference surface, and none is a write.
        for name in TOOL_CALL_ALLOWLIST:
            if name == _PROPOSAL_DRAFT_TOOL:
                continue
            assert "preference" not in name.lower()
            assert "remember" not in name.lower()

    def test_forged_preference_tool_call_is_fail_closed(self) -> None:
        # Even if the model EMITS a preference-write tool call, the name is
        # not in the allowlist (the loop breaks) and risk_tier fail-closes
        # unknown tools to DANGEROUS (no /trust override).
        for forged in ("store_preference", "remember_preference", "write_memory"):
            assert forged not in TOOL_CALL_ALLOWLIST
            assert tools.risk_tier(forged) is tools.RiskTier.DANGEROUS

    def test_tools_module_source_never_names_the_write_api(self) -> None:
        source = (
            _REPO_ROOT
            / "services/assistant_orchestrator/src/tools.py"
        ).read_text(encoding="utf-8")
        for api in _WRITE_API_NAMES:
            assert api not in source, (
                f"tools.py references {api!r} — the model-callable surface "
                f"must be structurally free of the preference write API (P8)."
            )
        assert "PREFERENCE_WRITE" not in source


class TestSingleWriteDoor:
    """Source scan: exactly ONE production caller of the write API exists."""

    def test_only_the_ao_handler_calls_the_write_api(self) -> None:
        allowed_definition = "services/assistant_orchestrator/src/knowledge_bank.py"
        allowed_caller = "services/assistant_orchestrator/src/entrypoint.py"
        offenders: list[str] = []
        for path in _production_py_files("services", "shared", "launcher"):
            rel = path.relative_to(_REPO_ROOT).as_posix()
            text = path.read_text(encoding="utf-8", errors="replace")
            for api in _WRITE_API_NAMES:
                if f".{api}(" in text and rel not in (
                    allowed_definition, allowed_caller,
                ):
                    offenders.append(f"{rel}: {api}")
        assert not offenders, (
            "Preference write API called outside the single sanctioned door "
            f"(the AO PREFERENCE_WRITE handler): {offenders} — P8 requires "
            "every write to flow through the operator command path."
        )

    def test_only_the_gateway_leg_encodes_write_frames(self) -> None:
        # PREFERENCE_WRITE_REQUEST frames may be BUILT only by the framer
        # (definition) and the gateway's operator-command transport leg —
        # never by the AO itself (no self-writes) and never by tools.
        allowed = {
            "shared/ipc/protocol.py",              # the encoder's definition
            "services/ui_gateway/src/transport.py",  # the operator command leg
        }
        offenders: list[str] = []
        for path in _production_py_files("services", "shared", "launcher"):
            rel = path.relative_to(_REPO_ROOT).as_posix()
            text = path.read_text(encoding="utf-8", errors="replace")
            if "encode_preference_write_request(" in text and rel not in allowed:
                offenders.append(rel)
        assert not offenders, (
            f"PREFERENCE_WRITE_REQUEST built outside the operator command "
            f"path: {offenders} (P8)."
        )

    def test_gateway_write_leg_is_reachable_only_from_the_slash_parse(self) -> None:
        # transport.py may call _preference_write_call only via the
        # preferences coordinator wiring (constructed with the parse-gated
        # handle_preferences_command flow).  Cheap structural check: the only
        # references to _preference_write_call are its definition and the
        # coordinator construction.
        text = (
            _REPO_ROOT / "services/ui_gateway/src/transport.py"
        ).read_text(encoding="utf-8")
        references = text.count("_preference_write_call")
        assert references == 2, (
            f"_preference_write_call referenced {references} times (expected "
            f"2: definition + coordinator injection) — a new caller must be "
            f"reviewed against P8."
        )


class TestReadIsNotWrite:
    """The model READS the tier (pinned block) — reading stays allowed."""

    def test_render_path_is_read_only_named(self) -> None:
        # The renderer imports no write API — rendering can never mutate.
        source = (
            _REPO_ROOT
            / "services/assistant_orchestrator/src/preference_block.py"
        ).read_text(encoding="utf-8")
        for api in _WRITE_API_NAMES:
            assert api not in source


class TestProposalChannelSourceIsolation:
    """study §5.1 — the M2 PROPOSE channel is source-isolated from the WRITE
    channel: the propose surface renders a card and stages verbatim bytes, but
    the WRITE happens only in the operator-driven confirm handler.  These
    structural-absence locks assert the propose-channel modules never name the
    store write API (so a refactor that reintroduces a write into the draft path
    is a governance decision, not a silent regression).
    """

    #: The propose-channel modules that MUST stay write-free (the card builder
    #: and the ephemeral staging store).  ``tools.py`` is covered by
    #: ``TestNoModelCallableWritePath.test_tools_module_source_never_names_the_write_api``.
    _PROPOSAL_CHANNEL_FILES: tuple[str, ...] = (
        "shared/ipc/preference_proposal.py",
        "services/assistant_orchestrator/src/proposal_staging.py",
    )

    def test_proposal_channel_modules_never_call_the_write_api(self) -> None:
        # Scan for the CALL form (``.store_preference(`` …) — the actual write, not
        # a docstring mention (proposal_staging's own docstring NAMES the API to
        # explain it never calls it; that is the isolation being documented).
        for rel in self._PROPOSAL_CHANNEL_FILES:
            text = (_REPO_ROOT / rel).read_text(encoding="utf-8")
            for api in _WRITE_API_NAMES:
                assert f".{api}(" not in text, (
                    f"{rel} CALLS the preference write API {api!r} — the propose "
                    f"channel must be source-isolated from the write channel "
                    f"(study §5.1; P8)."
                )
            assert "encode_preference_write_request(" not in text, (
                f"{rel} builds a write frame — the propose channel renders a "
                f"card and stages bytes; it never writes (P8)."
            )

    def test_staging_store_has_no_cipher_or_store_handle(self) -> None:
        # The staging store holds decided-proposal DATA only — no cipher, no bank
        # handle, no DB. (It is ephemeral + system-owned; the committed bytes ride
        # the real write door on confirm.)
        text = (
            _REPO_ROOT
            / "services/assistant_orchestrator/src/proposal_staging.py"
        ).read_text(encoding="utf-8")
        for forbidden in ("FieldCipher", "sqlite3", "EncryptedKnowledgeBank"):
            assert forbidden not in text
