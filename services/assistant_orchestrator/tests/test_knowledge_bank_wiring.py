"""
AO wiring tests for the knowledge bank (UC-002 Substrate v2, Vikunja #655).

Covers:
  - [knowledge] config validation (optional section, strict when present) +
    frozen-dataclass defaults.
  - _build_knowledge_bank: the three-way DEK recipe (dev / :memory: /
    production-refuse), has_encryption regression lock, enabled=false off
    switch, and the loud feature-disable on production audit failure.
  - INGEST_SUBMIT / INGEST_DECISION dispatch in _handle_connection: the full
    staging-file -> pending-row -> approve/reject flow, error frames
    (KNOWLEDGE_BANK_DISABLED, hash mismatch, bad uuid, bad decision), the
    delete-after-persist contract, and the audit chain records.
  - Prompt-path knowledge retrieval: grounded as UNTRUSTED_KNOWLEDGE with
    source='knowledge' (ADR-023 Amendment 2, #664 — untrusted for the Layer-3
    action-lock + datamarking, exempt from the Stage-5 leakage feed so recall
    works), its own k, skipped when a document loaded this turn.

No models anywhere: stub embedders + the in-memory audit log.
"""

from __future__ import annotations

import hashlib
import json
import os
import types
import uuid
import zlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from shared.ipc.protocol import MessageFramer, MessageType
from shared.ipc.vsock import VsockAddress, VsockConfig
from shared.runtime_config import ConfigResolutionError
from shared.security.audit_log import AuditLog, HmacSha256Signer
from shared.security.dek_envelope import DekEnvelope, generate_recovery_key
from shared.security.field_cipher import FieldCipher, derive_subkeys
from shared.security.ingest_staging import write_staged
from shared.security.tpm_sealer import SoftwareSealer
from services.assistant_orchestrator.src.context_manager import (
    ContextManager,
    Provenance,
)
from services.assistant_orchestrator.src.entrypoint import (
    AssistantOrchestratorEntrypointConfig,
    AssistantOrchestratorService,
)
from services.assistant_orchestrator.src.knowledge_bank import (
    EMBED_DIM,
    EncryptedKnowledgeBank,
)


# ---------------------------------------------------------------------------
# Helpers (mirror test_entrypoint_document_wiring.py patterns)
# ---------------------------------------------------------------------------


class _FakeTransport:
    """Minimal stand-in that captures outbound frames."""

    def __init__(self, inbound: bytes | None) -> None:
        self._inbound = inbound
        self.sent: list[bytes] = []
        self.connected: bool = True

    def receive(self) -> bytes | None:
        return self._inbound

    def send(self, data: bytes) -> bool:
        self.sent.append(data)
        return True


def fake_embed(texts: list[str]) -> np.ndarray:
    out = np.zeros((len(texts), EMBED_DIM), dtype=np.float32)
    for i, t in enumerate(texts):
        for word in t.lower().split():
            out[i, zlib.crc32(word.encode()) % EMBED_DIM] += 1.0
    norms = np.linalg.norm(out, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (out / norms).astype(np.float32)


def _make_cipher() -> FieldCipher:
    env = DekEnvelope.create(
        sealer=SoftwareSealer(), recovery_key=generate_recovery_key()
    )
    return FieldCipher(derive_subkeys(env.unseal_dek()))


def _make_resolved_config(**overrides: Any) -> AssistantOrchestratorEntrypointConfig:
    kwargs: dict[str, Any] = dict(
        model_dir=Path("models"),
        manifest_path=None,
        device="GPU",
        priority=1,
        draft_model_dir=None,
        speculative_decoding_enabled=False,
        max_new_tokens=64,
        generation_temperature=0.0,
        generation_top_k=50,
        generation_top_p=0.9,
        generation_repetition_penalty=1.1,
        generation_do_sample=False,
        response_depth_mode="standard",
        dev_mode=True,
        jwt_ca_cert_path=None,
        vsock_config=VsockConfig(address=VsockAddress(cid=0, port=0)),
        pgov_cosine_threshold=0.85,
        deployment_mode="host",
    )
    kwargs.update(overrides)
    return AssistantOrchestratorEntrypointConfig(**kwargs)  # type: ignore[arg-type]


_framer = MessageFramer()


def _make_service_with_bank() -> tuple[AssistantOrchestratorService, EncryptedKnowledgeBank, FieldCipher, AuditLog]:
    """Service with an in-memory knowledge bank + in-memory audit chain."""
    service = AssistantOrchestratorService("dummy.toml")
    service._resolved_config = _make_resolved_config()
    service._context_manager = ContextManager()
    cipher = _make_cipher()
    bank = EncryptedKnowledgeBank(
        db_path=":memory:", embed_fn=fake_embed, cipher=cipher
    )
    audit = AuditLog.in_memory(HmacSha256Signer(key=b"k" * 32))
    service._knowledge = bank
    service._ingest_cipher = cipher
    service._ingest_audit = audit
    return service, bank, cipher, audit


def _stage_article(cipher: FieldCipher, doc_uuid: str, content: str) -> Path:
    """Write a staged article under the (redirected) LOCALAPPDATA."""
    staging_dir = Path(os.environ["LOCALAPPDATA"]) / "BlarAI" / "ingest_staging"
    return write_staged(content, doc_uuid, cipher, staging_dir)


def _submit_frame(doc_uuid: str, content: str, **overrides: Any) -> bytes:
    kwargs: dict[str, Any] = dict(
        doc_uuid=doc_uuid,
        source_type="url",
        source_ref="https://example.org/articles/a",
        staging_path="",
        content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        title="Article title",
        byline="A. Writer",
        published_date="2026-06-01",
        word_count=12,
        cleaner_version="cleaner-v1",
        request_id="req-1",
    )
    kwargs.update(overrides)
    return _framer.encode_ingest_submit(**kwargs)


def _last_result(transport: _FakeTransport) -> dict[str, Any]:
    assert transport.sent, "no frame sent"
    return _framer.decode_ingest_result(transport.sent[-1])


_CONTENT = (
    "Turbochargers compress intake air so engines burn more fuel per cycle "
    "raising power output without enlarging displacement."
)


# ---------------------------------------------------------------------------
# 1. Config validation + dataclass defaults
# ---------------------------------------------------------------------------


_BASE_CONFIG: dict[str, Any] = {
    "runtime": {"deployment_mode": "host"},
    "gpu": {"device": "GPU", "model_dir": "models/x", "priority": 1},
    "generation": {
        "max_new_tokens": 64,
        "temperature": 0.0,
        "top_k": 50,
        "top_p": 0.9,
        "repetition_penalty": 1.1,
        "do_sample": False,
    },
    "security": {"dev_mode": True},
    "ipc": {
        "vsock_cid": 2,
        "vsock_port": 5001,
        "timeout_ms": 5000,
        "max_message_bytes": 65536,
    },
    "pgov": {"cosine_similarity_threshold": 0.85},
}


def _validate(config: dict[str, Any]) -> None:
    service = AssistantOrchestratorService("dummy.toml", deployment_mode="host")
    service._validate_config_data(config, Path("default.toml"))


def _load_config_with_knowledge(
    tmp_path: Path, knowledge_lines: str
) -> AssistantOrchestratorEntrypointConfig:
    """Drive the REAL ``_load_entrypoint_config`` over a hand-written dev-mode
    TOML and return the resolved config.

    dev_mode → ``_validate_security_material`` returns early, so no model/cert
    files are needed; the resolver's real ``knowledge_images_enabled`` expression
    (``bool(knowledge.get("images_enabled", False))``) runs unmocked.  Used to
    test the resolution for real (not a re-implemented expression — #665 item 2).
    """
    toml_text = (
        '[runtime]\ndeployment_mode = "host"\n\n'
        '[gpu]\ndevice = "GPU"\nmodel_dir = "models/x"\npriority = 1\n\n'
        '[generation]\nmax_new_tokens = 64\ntemperature = 0.0\ntop_k = 50\n'
        'top_p = 0.9\nrepetition_penalty = 1.1\ndo_sample = false\n\n'
        '[security]\ndev_mode = true\n\n'
        '[ipc]\nvsock_cid = 2\nvsock_port = 5001\ntimeout_ms = 5000\n'
        'max_message_bytes = 65536\n\n'
        '[pgov]\ncosine_similarity_threshold = 0.85\n'
        + knowledge_lines
    )
    cfg_path = tmp_path / "default.toml"
    cfg_path.write_text(toml_text, encoding="utf-8")
    service = AssistantOrchestratorService(str(cfg_path), deployment_mode="host")
    # Honor the temp config path directly (bypass on-disk service-config lookup).
    service._resolve_config_path = lambda: cfg_path  # type: ignore[method-assign]
    return service._load_entrypoint_config()


class TestKnowledgeConfigValidation:
    def test_missing_section_is_fine(self) -> None:
        _validate(dict(_BASE_CONFIG))  # no [knowledge] — secure defaults apply

    def test_valid_section_passes(self) -> None:
        cfg = dict(_BASE_CONFIG)
        cfg["knowledge"] = {
            "enabled": True,
            "db_filename": "knowledge.db",
            "retrieve_k": 4,
            "embed_max_tokens": 512,
            "staging_max_bytes": 262144,
            "images_enabled": False,
        }
        _validate(cfg)

    def test_non_table_section_rejected(self) -> None:
        cfg = dict(_BASE_CONFIG)
        cfg["knowledge"] = "yes"
        with pytest.raises(ConfigResolutionError):
            _validate(cfg)

    def test_enabled_must_be_bool(self) -> None:
        cfg = dict(_BASE_CONFIG)
        cfg["knowledge"] = {"enabled": "true"}
        with pytest.raises(ConfigResolutionError):
            _validate(cfg)

    @pytest.mark.parametrize(
        "bad", ["", "  ", "sub/knowledge.db", "..\\evil.db", "a\\b.db"]
    )
    def test_db_filename_must_be_bare(self, bad: str) -> None:
        cfg = dict(_BASE_CONFIG)
        cfg["knowledge"] = {"db_filename": bad}
        with pytest.raises(ConfigResolutionError):
            _validate(cfg)

    @pytest.mark.parametrize("bad", [0, -1, 33, "4"])
    def test_retrieve_k_range(self, bad: Any) -> None:
        cfg = dict(_BASE_CONFIG)
        cfg["knowledge"] = {"retrieve_k": bad}
        with pytest.raises(ConfigResolutionError):
            _validate(cfg)

    @pytest.mark.parametrize("bad", [8, 513, 100000])
    def test_embed_max_tokens_range(self, bad: int) -> None:
        cfg = dict(_BASE_CONFIG)
        cfg["knowledge"] = {"embed_max_tokens": bad}
        with pytest.raises(ConfigResolutionError):
            _validate(cfg)

    @pytest.mark.parametrize("bad", [512, 2_000_000])
    def test_staging_max_bytes_range(self, bad: int) -> None:
        cfg = dict(_BASE_CONFIG)
        cfg["knowledge"] = {"staging_max_bytes": bad}
        with pytest.raises(ConfigResolutionError):
            _validate(cfg)

    def test_dataclass_defaults(self) -> None:
        resolved = _make_resolved_config()
        assert resolved.knowledge_enabled is True
        assert resolved.knowledge_db_filename == "knowledge.db"
        assert resolved.knowledge_retrieve_k == 4
        assert resolved.knowledge_embed_max_tokens == 512
        assert resolved.knowledge_staging_max_bytes == 262_144

    # -- 4th weld lock: [knowledge].images_enabled (UC-003 Workstream B) --

    def test_images_enabled_default_is_false(self) -> None:
        """Dormant by construction: the unset key resolves to False so image
        fetch never engages unless the operator deliberately flips it."""
        resolved = _make_resolved_config()
        assert resolved.knowledge_images_enabled is False

    @pytest.mark.parametrize("flag", [True, False])
    def test_images_enabled_resolves_from_real_toml(
        self, tmp_path: Path, flag: bool
    ) -> None:
        """Drive the REAL resolver (``_load_entrypoint_config``, entrypoint.py:817)
        from a ``[knowledge] images_enabled = <flag>`` TOML — NOT a re-implemented
        expression (#665 item 2).  A wrong key / wrong default / inverted bool in
        the real resolution path would now fail here, where the prior tautological
        test could not catch it."""
        resolved = _load_config_with_knowledge(
            tmp_path, f"\n[knowledge]\nimages_enabled = {str(flag).lower()}\n"
        )
        assert resolved.knowledge_images_enabled is flag

    def test_images_enabled_absent_resolves_false_real(
        self, tmp_path: Path
    ) -> None:
        """Through the REAL resolver: no [knowledge] section at all, and a
        [knowledge] section that omits the key, both resolve False (fail-closed
        dormant default)."""
        no_section = _load_config_with_knowledge(tmp_path, "")
        assert no_section.knowledge_images_enabled is False
        present_no_key = _load_config_with_knowledge(
            tmp_path, "\n[knowledge]\nretrieve_k = 4\n"
        )
        assert present_no_key.knowledge_images_enabled is False

    def test_images_enabled_valid_bool_passes(self) -> None:
        cfg = dict(_BASE_CONFIG)
        cfg["knowledge"] = {"images_enabled": True}
        _validate(cfg)

    @pytest.mark.parametrize("bad", ["true", "false", 0, 1, [], {}])
    def test_images_enabled_must_be_bool(self, bad: Any) -> None:
        cfg = dict(_BASE_CONFIG)
        cfg["knowledge"] = {"images_enabled": bad}
        with pytest.raises(ConfigResolutionError) as exc_info:
            _validate(cfg)
        assert exc_info.value.code == "AO_CFG_KNOWLEDGE_IMAGES_ENABLED_INVALID"


# ---------------------------------------------------------------------------
# 2. _build_knowledge_bank — three-way recipe + posture
# ---------------------------------------------------------------------------


def _fake_detector() -> types.SimpleNamespace:
    return types.SimpleNamespace(
        loaded=True,
        _embed=fake_embed,
        embed_documents=lambda texts, max_length=512: fake_embed(texts),
    )


class TestBuildKnowledgeBank:
    def test_in_memory_dev_path_returns_encrypted_bank(self) -> None:
        """LOCALAPPDATA unset → ':memory:' ephemeral SoftwareSealer path."""
        from services.assistant_orchestrator.src import pgov as pgov_mod

        with patch.object(pgov_mod, "_get_detector", return_value=_fake_detector()):
            with patch.dict(
                "os.environ", {"LOCALAPPDATA": "", "BLARAI_DEK_KEYSTORE": ""}
            ):
                orch = AssistantOrchestratorService.__new__(
                    AssistantOrchestratorService
                )
                orch._resolved_config = None
                bank = orch._build_knowledge_bank()
        assert bank is not None
        assert isinstance(bank, EncryptedKnowledgeBank)
        assert bank.has_encryption is True
        assert orch._ingest_cipher is not None
        assert orch._ingest_audit is not None
        bank.close()

    def test_dev_mode_disk_path_builds_bank(self, tmp_path: Path) -> None:
        from services.assistant_orchestrator.src import pgov as pgov_mod

        with patch.object(pgov_mod, "_get_detector", return_value=_fake_detector()):
            with patch.dict(
                "os.environ",
                {"LOCALAPPDATA": str(tmp_path), "BLARAI_DEK_KEYSTORE": ""},
            ):
                orch = AssistantOrchestratorService.__new__(
                    AssistantOrchestratorService
                )
                orch._resolved_config = _make_resolved_config(dev_mode=True)
                bank = orch._build_knowledge_bank()
        assert bank is not None
        assert (tmp_path / "BlarAI" / "knowledge.db").exists()
        bank.close()

    def test_production_without_keystore_disables_loudly(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """dev_mode=False + no BLARAI_DEK_KEYSTORE → feature OFF (None), never
        a silent SoftwareSealer fallback, and never an exception out."""
        from services.assistant_orchestrator.src import pgov as pgov_mod

        with patch.object(pgov_mod, "_get_detector", return_value=_fake_detector()):
            with patch.dict(
                "os.environ",
                {"LOCALAPPDATA": str(tmp_path), "BLARAI_DEK_KEYSTORE": ""},
            ):
                orch = AssistantOrchestratorService.__new__(
                    AssistantOrchestratorService
                )
                orch._resolved_config = _make_resolved_config(dev_mode=False)
                with caplog.at_level("ERROR"):
                    bank = orch._build_knowledge_bank()
        assert bank is None
        assert "BLARAI_DEK_KEYSTORE" in caplog.text
        assert "DISABLED" in caplog.text or "disabled" in caplog.text

    def test_enabled_false_returns_none(self, tmp_path: Path) -> None:
        from services.assistant_orchestrator.src import pgov as pgov_mod

        with patch.object(pgov_mod, "_get_detector", return_value=_fake_detector()):
            with patch.dict("os.environ", {"LOCALAPPDATA": str(tmp_path)}):
                orch = AssistantOrchestratorService.__new__(
                    AssistantOrchestratorService
                )
                orch._resolved_config = _make_resolved_config(
                    knowledge_enabled=False
                )
                bank = orch._build_knowledge_bank()
        assert bank is None

    def test_embedder_failure_disables_loudly(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        from services.assistant_orchestrator.src import pgov as pgov_mod

        dead = types.SimpleNamespace(loaded=False, load_model=lambda: False)
        with patch.object(pgov_mod, "_get_detector", return_value=dead):
            orch = AssistantOrchestratorService.__new__(AssistantOrchestratorService)
            orch._resolved_config = None
            with caplog.at_level("ERROR"):
                bank = orch._build_knowledge_bank()
        assert bank is None
        assert "embedding model" in caplog.text

    def test_production_audit_failure_disables_feature(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """dev_mode=False + DEK present + TPM audit key unprovisioned →
        knowledge feature OFF loudly (audit is a precondition for ingest)."""
        from services.assistant_orchestrator.src import pgov as pgov_mod
        from shared.security import tpm_signer
        from shared.security.dek_envelope import build_envelope

        keystore = tmp_path / "dek_keystore.json"
        build_envelope(
            sealer=SoftwareSealer(),
            recovery_key=generate_recovery_key(),
            keystore_path=keystore,
            dev_mode=True,
        )

        orch = AssistantOrchestratorService.__new__(AssistantOrchestratorService)
        orch._resolved_config = _make_resolved_config(dev_mode=False)
        with patch.object(pgov_mod, "_get_detector", return_value=_fake_detector()):
            with patch.dict(
                "os.environ",
                {
                    "LOCALAPPDATA": str(tmp_path),
                    "BLARAI_DEK_KEYSTORE": str(keystore),
                },
            ):
                # Production sealer path would need a real TPM — substitute the
                # SoftwareSealer load so the test isolates the AUDIT failure.
                with patch(
                    "shared.security.tpm_sealer.TpmSealer",
                    return_value=SoftwareSealer(),
                ), patch.object(tpm_signer, "key_exists", return_value=False):
                    with caplog.at_level("ERROR"):
                        bank = orch._build_knowledge_bank()
        assert bank is None
        assert "audit" in caplog.text.lower()
        assert orch._ingest_audit is None


# ---------------------------------------------------------------------------
# 3. INGEST_SUBMIT dispatch
# ---------------------------------------------------------------------------


class TestIngestSubmitDispatch:
    def test_bank_disabled_yields_loud_error_frame(self) -> None:
        service = AssistantOrchestratorService("dummy.toml")
        service._resolved_config = _make_resolved_config()
        transport = _FakeTransport(
            _submit_frame(str(uuid.uuid4()), _CONTENT)
        )
        assert service._handle_connection(transport) is True
        result = _last_result(transport)
        assert result["ok"] is False
        assert result["error_code"] == "KNOWLEDGE_BANK_DISABLED"

    def test_full_submit_flow(self) -> None:
        service, bank, cipher, audit = _make_service_with_bank()
        doc_uuid = str(uuid.uuid4())
        staged = _stage_article(cipher, doc_uuid, _CONTENT)

        transport = _FakeTransport(_submit_frame(doc_uuid, _CONTENT))
        assert service._handle_connection(transport) is True

        result = _last_result(transport)
        assert result["ok"] is True
        assert result["state"] == "pending"
        assert result["doc_uuid"] == doc_uuid
        # Pending row persisted with the decrypted metadata.
        doc = bank.get_doc(doc_uuid)
        assert doc.approval_state == "pending"
        assert doc.title == "Article title"
        assert "Turbochargers compress" in doc.content
        # Staging file deleted AFTER the row persisted.
        assert not staged.exists()
        # Audit chain carries the labels-only ESCALATE record.
        assert len(audit.records) == 1
        rec = audit.records[0]
        assert rec.verb == "INGEST_SUBMIT"
        assert rec.decision == "ESCALATE"
        assert rec.resource.startswith(f"{doc_uuid}|")
        assert _CONTENT[:30] not in rec.resource  # labels only, never content
        # car_hash is the KEYED content digest, never the plaintext sha
        # (membership-oracle close, #655 LA verdict 2026-06-10).
        plaintext_sha = hashlib.sha256(_CONTENT.encode("utf-8")).hexdigest()
        assert rec.car_hash == bank.content_digest_keyed_hex(plaintext_sha)
        assert rec.car_hash != plaintext_sha

    def test_content_hash_mismatch_refuses(self) -> None:
        service, bank, cipher, audit = _make_service_with_bank()
        doc_uuid = str(uuid.uuid4())
        staged = _stage_article(cipher, doc_uuid, _CONTENT)

        frame = _submit_frame(doc_uuid, _CONTENT, content_sha256="f" * 64)
        transport = _FakeTransport(frame)
        service._handle_connection(transport)

        result = _last_result(transport)
        assert result["ok"] is False
        assert result["error_code"] == "INGEST_CONTENT_HASH_MISMATCH"
        assert bank.count() == 0
        assert staged.exists()  # nothing persisted → staging kept for retry
        assert len(audit.records) == 0

    def test_missing_staging_file_refuses(self) -> None:
        service, bank, _cipher, _audit = _make_service_with_bank()
        doc_uuid = str(uuid.uuid4())
        transport = _FakeTransport(_submit_frame(doc_uuid, _CONTENT))
        service._handle_connection(transport)
        result = _last_result(transport)
        assert result["ok"] is False
        assert result["error_code"] == "INGEST_STAGING_ERROR"
        assert bank.count() == 0

    def test_traversal_doc_uuid_refuses(self) -> None:
        service, bank, _cipher, _audit = _make_service_with_bank()
        raw = _framer.encode(
            MessageType.INGEST_SUBMIT,
            {
                "doc_uuid": "..\\evil",
                "source_type": "url",
                "source_ref": "https://example.org",
                "content_sha256": "a" * 64,
            },
            "r1",
        )
        transport = _FakeTransport(raw)
        service._handle_connection(transport)
        result = _last_result(transport)
        assert result["ok"] is False
        assert result["error_code"] == "INGEST_STAGING_ERROR"
        assert bank.count() == 0

    def test_mismatched_staging_path_refuses(self) -> None:
        """A payload staging_path pointing elsewhere is rejected, not followed."""
        service, bank, cipher, _audit = _make_service_with_bank()
        doc_uuid = str(uuid.uuid4())
        _stage_article(cipher, doc_uuid, _CONTENT)
        frame = _submit_frame(
            doc_uuid, _CONTENT, staging_path=r"C:\\somewhere\\else\\x.bin"
        )
        transport = _FakeTransport(frame)
        service._handle_connection(transport)
        result = _last_result(transport)
        assert result["ok"] is False
        assert result["error_code"] == "INGEST_STAGING_ERROR"
        assert bank.count() == 0

    def test_invalid_source_type_refuses(self) -> None:
        service, bank, cipher, _audit = _make_service_with_bank()
        doc_uuid = str(uuid.uuid4())
        _stage_article(cipher, doc_uuid, _CONTENT)
        frame = _submit_frame(doc_uuid, _CONTENT, source_type="paste")
        # paste IS valid; use a genuinely bad one via generic encode:
        raw = _framer.encode(
            MessageType.INGEST_SUBMIT,
            {
                "doc_uuid": doc_uuid,
                "source_type": "carrier-pigeon",
                "source_ref": "https://example.org",
                "content_sha256": hashlib.sha256(
                    _CONTENT.encode("utf-8")
                ).hexdigest(),
            },
            "r1",
        )
        transport = _FakeTransport(raw)
        service._handle_connection(transport)
        result = _last_result(transport)
        assert result["ok"] is False
        assert result["error_code"] == "INGEST_SUBMIT_INVALID"
        assert bank.count() == 0
        del frame

    def test_resubmit_approved_source_reports_already_ingested(self) -> None:
        service, bank, cipher, audit = _make_service_with_bank()
        first_uuid = str(uuid.uuid4())
        _stage_article(cipher, first_uuid, _CONTENT)
        t1 = _FakeTransport(_submit_frame(first_uuid, _CONTENT))
        service._handle_connection(t1)
        bank.approve(first_uuid)

        second_uuid = str(uuid.uuid4())
        new_content = _CONTENT + " refreshed."
        _stage_article(cipher, second_uuid, new_content)
        frame = _submit_frame(
            second_uuid,
            new_content,
            content_sha256=hashlib.sha256(new_content.encode("utf-8")).hexdigest(),
        )
        t2 = _FakeTransport(frame)
        service._handle_connection(t2)

        result = _last_result(t2)
        assert result["ok"] is True
        assert result["state"] == "already_ingested"
        assert result["doc_uuid"] == first_uuid  # points at the approved doc
        # Only the FIRST submit audited (the second changed nothing).
        assert [r.verb for r in audit.records] == ["INGEST_SUBMIT"]


class TestIngestEditProvenance:
    """#663 Workstream A: an operator-edited re-submit records edited=1 + the
    KEYED cleaner-output digest packed into the audit ``resource`` label, with
    ``car_hash`` staying the keyed digest of the EDITED body — so the signed
    chain honestly attests human curation WITHOUT a canonical-format change and
    WITHOUT a plaintext membership oracle (ADR-029)."""

    def test_edited_resubmit_records_flag_and_keyed_clean_digest(self) -> None:
        service, bank, cipher, audit = _make_service_with_bank()
        edited = _CONTENT + " (operator trimmed the advert.)"
        doc_uuid = str(uuid.uuid4())
        _stage_article(cipher, doc_uuid, edited)
        # The cleaner's ORIGINAL pre-edit digest (a different body).
        original_sha = hashlib.sha256(
            b"the cleaner's ORIGINAL body, before the operator edited it"
        ).hexdigest()

        frame = _submit_frame(doc_uuid, edited, prior_content_sha256=original_sha)
        transport = _FakeTransport(frame)
        assert service._handle_connection(transport) is True
        assert _last_result(transport)["ok"] is True

        rec = audit.records[-1]
        assert rec.verb == "INGEST_SUBMIT" and rec.decision == "ESCALATE"
        # edited=1 + the keyed cleaner digest, packed onto the free-form resource.
        assert "|edited=1|clean=" in rec.resource
        prior_keyed = bank.content_digest_keyed_hex(original_sha)
        assert f"clean={prior_keyed[:16]}" in rec.resource
        # Keyed-only: the plaintext original sha NEVER appears in the chain.
        assert original_sha not in rec.resource
        assert original_sha != prior_keyed
        # car_hash = keyed digest of the EDITED (stored) body.
        edited_sha = hashlib.sha256(edited.encode("utf-8")).hexdigest()
        assert rec.car_hash == bank.content_digest_keyed_hex(edited_sha)
        # The edited body is what actually persisted.
        assert "operator trimmed the advert" in bank.get_doc(doc_uuid).content

    def test_normal_submit_has_no_edited_marker(self) -> None:
        service, bank, cipher, audit = _make_service_with_bank()
        doc_uuid = str(uuid.uuid4())
        _stage_article(cipher, doc_uuid, _CONTENT)
        # No prior_content_sha256 → a plain submit (unchanged, backward-compatible).
        service._handle_connection(_FakeTransport(_submit_frame(doc_uuid, _CONTENT)))
        rec = audit.records[-1]
        assert "edited=" not in rec.resource
        assert "clean=" not in rec.resource

    def test_prior_equal_to_current_is_not_an_edit(self) -> None:
        """A re-submit whose edited bytes hash to the SAME digest records no
        edit (edited recorded only when prior != current)."""
        service, bank, cipher, audit = _make_service_with_bank()
        doc_uuid = str(uuid.uuid4())
        _stage_article(cipher, doc_uuid, _CONTENT)
        same_sha = hashlib.sha256(_CONTENT.encode("utf-8")).hexdigest()
        frame = _submit_frame(doc_uuid, _CONTENT, prior_content_sha256=same_sha)
        service._handle_connection(_FakeTransport(frame))
        assert "edited=" not in audit.records[-1].resource


# ---------------------------------------------------------------------------
# 4. INGEST_DECISION dispatch
# ---------------------------------------------------------------------------


def _submitted_service() -> tuple[AssistantOrchestratorService, Any, str, AuditLog]:
    service, bank, cipher, audit = _make_service_with_bank()
    doc_uuid = str(uuid.uuid4())
    _stage_article(cipher, doc_uuid, _CONTENT)
    t = _FakeTransport(_submit_frame(doc_uuid, _CONTENT))
    service._handle_connection(t)
    assert _last_result(t)["ok"] is True
    return service, bank, doc_uuid, audit


class TestIngestDecisionDispatch:
    def test_approve_flow(self) -> None:
        service, bank, doc_uuid, audit = _submitted_service()
        transport = _FakeTransport(
            _framer.encode_ingest_decision(
                doc_uuid=doc_uuid, decision="approve", request_id="r2"
            )
        )
        assert service._handle_connection(transport) is True
        result = _last_result(transport)
        assert result["ok"] is True
        assert result["state"] == "approved"
        assert result["chunk_count"] >= 1
        assert bank.get_doc(doc_uuid).approval_state == "approved"
        assert [r.verb for r in audit.records] == [
            "INGEST_SUBMIT",
            "INGEST_APPROVE",
        ]
        assert audit.records[-1].decision == "ALLOW"

    def test_reject_flow(self) -> None:
        service, bank, doc_uuid, audit = _submitted_service()
        transport = _FakeTransport(
            _framer.encode_ingest_decision(
                doc_uuid=doc_uuid, decision="reject", request_id="r2"
            )
        )
        service._handle_connection(transport)
        result = _last_result(transport)
        assert result["ok"] is True
        assert result["state"] == "rejected"
        doc = bank.get_doc(doc_uuid)
        assert doc.approval_state == "rejected"
        assert "Turbochargers compress" in doc.content  # tombstone retains
        assert audit.records[-1].verb == "INGEST_REJECT"
        assert audit.records[-1].decision == "DENY"

    def test_unknown_doc_refuses(self) -> None:
        service, _bank, _doc_uuid, _audit = _submitted_service()
        transport = _FakeTransport(
            _framer.encode_ingest_decision(
                doc_uuid=str(uuid.uuid4()), decision="approve"
            )
        )
        service._handle_connection(transport)
        result = _last_result(transport)
        assert result["ok"] is False
        assert result["error_code"] == "INGEST_DECISION_REFUSED"

    def test_invalid_decision_refuses(self) -> None:
        service, _bank, doc_uuid, _audit = _submitted_service()
        raw = _framer.encode(
            MessageType.INGEST_DECISION,
            {"doc_uuid": doc_uuid, "decision": "maybe"},
            "r",
        )
        transport = _FakeTransport(raw)
        service._handle_connection(transport)
        result = _last_result(transport)
        assert result["ok"] is False
        assert result["error_code"] == "INGEST_DECISION_INVALID"

    def test_bank_disabled_refuses(self) -> None:
        service = AssistantOrchestratorService("dummy.toml")
        service._resolved_config = _make_resolved_config()
        transport = _FakeTransport(
            _framer.encode_ingest_decision(doc_uuid="d", decision="approve")
        )
        service._handle_connection(transport)
        result = _last_result(transport)
        assert result["error_code"] == "KNOWLEDGE_BANK_DISABLED"

    def test_unauditable_decision_fails_closed(self) -> None:
        """A decision whose audit append fails returns an error frame — the
        action is never silently unrecorded."""
        service, bank, doc_uuid, _audit = _submitted_service()
        service._ingest_audit = None  # simulate a dead audit sink
        transport = _FakeTransport(
            _framer.encode_ingest_decision(doc_uuid=doc_uuid, decision="approve")
        )
        service._handle_connection(transport)
        result = _last_result(transport)
        assert result["ok"] is False
        assert result["error_code"] == "INGEST_DECISION_FAILED"


# ---------------------------------------------------------------------------
# 5. Prompt-path knowledge retrieval
# ---------------------------------------------------------------------------


def _generate_ok(prompt: str, **_kwargs: Any) -> SimpleNamespace:
    return SimpleNamespace(text="A clean answer.", token_count=4, error=None)


def _pgov_approved(generated_text: str, **_kwargs: Any) -> SimpleNamespace:
    return SimpleNamespace(approved=True, sanitized_text=generated_text)


def _approved_bank_service() -> tuple[AssistantOrchestratorService, Any]:
    service, bank, cipher, _audit = _make_service_with_bank()
    result = bank.submit_pending(
        doc_uuid=str(uuid.uuid4()),
        source_type="url",
        source_ref="https://example.org/turbo",
        content=_CONTENT,
        title="Turbo article",
    )
    bank.approve(result.doc_uuid)
    service._inference = MagicMock()
    service._inference.generate_text.side_effect = _generate_ok
    return service, bank


class TestPromptPathKnowledgeRetrieval:
    @patch("services.assistant_orchestrator.src.entrypoint.validate_output")
    def test_knowledge_grounded_untrusted_with_source_knowledge(
        self, mock_validate: MagicMock
    ) -> None:
        """Knowledge retrieval grounds chunks as ``UNTRUSTED_KNOWLEDGE``
        (ADR-023 Amendment 2, #664) — untrusted for the Layer-3 action-lock and
        still datamarked, but exempt from the Stage-5 leakage OUTPUT block so a
        faithful recall is not held. It must NOT be the plain ``UNTRUSTED_EXTERNAL``
        tier, which would re-impose the leakage block that made the bank
        write-only."""
        mock_validate.side_effect = _pgov_approved
        service, _bank = _approved_bank_service()
        inbound = _framer.encode_prompt_request(
            session_id="sess-k",
            prompt="how do turbochargers compress intake air",
            request_id="r1",
        )
        cm = service._context_manager
        with patch.object(
            cm, "add_grounded_context", wraps=cm.add_grounded_context
        ) as spy:
            service._handle_connection(_FakeTransport(inbound))

        knowledge_calls = [
            c for c in spy.call_args_list
            if c.kwargs.get("source") == "knowledge"
        ]
        assert len(knowledge_calls) == 1
        call = knowledge_calls[0]
        assert call.kwargs.get("provenance") is Provenance.UNTRUSTED_KNOWLEDGE
        chunks = call.args[1]
        assert any("Turbochargers compress" in c for c in chunks)
        assert any("knowledge bank" in c for c in chunks)  # labelled

    @patch("services.assistant_orchestrator.src.entrypoint.validate_output")
    def test_skipped_when_document_loaded_this_turn(
        self, mock_validate: MagicMock
    ) -> None:
        mock_validate.side_effect = _pgov_approved
        service, _bank = _approved_bank_service()
        inbound = _framer.encode_prompt_request(
            session_id="sess-k2",
            prompt="summarize this",
            request_id="r1",
            documents=[{"filename": "fresh.txt", "content": "Fresh attachment."}],
        )
        cm = service._context_manager
        with patch.object(
            cm, "add_grounded_context", wraps=cm.add_grounded_context
        ) as spy:
            service._handle_connection(_FakeTransport(inbound))
        knowledge_calls = [
            c for c in spy.call_args_list
            if c.kwargs.get("source") == "knowledge"
        ]
        assert knowledge_calls == []

    @patch("services.assistant_orchestrator.src.entrypoint.validate_output")
    def test_no_bank_no_knowledge_grounding(self, mock_validate: MagicMock) -> None:
        mock_validate.side_effect = _pgov_approved
        service = AssistantOrchestratorService("dummy.toml")
        service._resolved_config = _make_resolved_config()
        service._context_manager = ContextManager()
        service._inference = MagicMock()
        service._inference.generate_text.side_effect = _generate_ok
        inbound = _framer.encode_prompt_request(
            session_id="sess-k3", prompt="hello there", request_id="r1"
        )
        cm = service._context_manager
        with patch.object(
            cm, "add_grounded_context", wraps=cm.add_grounded_context
        ) as spy:
            service._handle_connection(_FakeTransport(inbound))
        knowledge_calls = [
            c for c in spy.call_args_list
            if c.kwargs.get("source") == "knowledge"
        ]
        assert knowledge_calls == []

    def test_knowledge_retrieve_respects_config_k(self) -> None:
        service, bank = _approved_bank_service()
        service._resolved_config = _make_resolved_config(knowledge_retrieve_k=1)
        # Seed several distinct approved docs.
        for i in range(3):
            r = bank.submit_pending(
                doc_uuid=str(uuid.uuid4()),
                source_type="url",
                source_ref=f"https://example.org/{i}",
                content=f"turbochargers compress air variant {i} words",
            )
            bank.approve(r.doc_uuid)
        labelled = service._knowledge_retrieve("turbochargers compress")
        assert len(labelled) == 1  # config k honored

    def test_knowledge_retrieve_fail_soft(self) -> None:
        """A retrieval exception degrades to no-grounding, never breaks a turn."""
        service, bank = _approved_bank_service()
        with patch.object(bank, "retrieve", side_effect=RuntimeError("boom")):
            assert service._knowledge_retrieve("anything") == []


# ---------------------------------------------------------------------------
# 6. Audit-first ordering (#655 review FIX 2)
# ---------------------------------------------------------------------------


class _RaisingAuditSink:
    """Audit sink whose append always fails — the FIX 2 dead-sink probe."""

    def __init__(self) -> None:
        self.records: list[Any] = []

    def append(self, **_kwargs: Any) -> None:
        from shared.security.audit_log import AuditSinkError

        raise AuditSinkError("injected audit sink failure")


class TestAuditFirstOrdering:
    def test_raising_audit_sink_blocks_submit(self) -> None:
        """Review repro: with a dead audit sink the submit must FAIL — no
        pending row, staging file retained for retry (the pre-fix code
        persisted the row first and only then failed the audit append)."""
        service, bank, cipher, _audit = _make_service_with_bank()
        service._ingest_audit = _RaisingAuditSink()
        doc_uuid = str(uuid.uuid4())
        staged = _stage_article(cipher, doc_uuid, _CONTENT)

        transport = _FakeTransport(_submit_frame(doc_uuid, _CONTENT))
        service._handle_connection(transport)
        result = _last_result(transport)
        assert result["ok"] is False
        assert result["error_code"] == "INGEST_SUBMIT_FAILED"
        assert bank.count() == 0  # nothing persisted without an audit record
        assert staged.exists()  # staging retained — the submit can be retried

    def test_raising_audit_sink_blocks_approve(self) -> None:
        """Review repro: with a dead audit sink the approve must leave the
        doc PENDING and NOT retrievable (the pre-fix code approved + indexed
        the doc, then failed the audit append — an approved, retrievable
        document with no governance record)."""
        service, bank, doc_uuid, _audit = _submitted_service()
        service._ingest_audit = _RaisingAuditSink()
        transport = _FakeTransport(
            _framer.encode_ingest_decision(doc_uuid=doc_uuid, decision="approve")
        )
        service._handle_connection(transport)
        result = _last_result(transport)
        assert result["ok"] is False
        assert result["error_code"] == "INGEST_DECISION_FAILED"
        assert bank.get_doc(doc_uuid).approval_state == "pending"
        assert bank.chunk_count() == 0
        assert bank.retrieve("turbochargers compress intake air") == []

    def test_audit_append_precedes_mutation(self) -> None:
        """Sequence lock: the audit append happens BEFORE the bank mutation."""
        service, bank, doc_uuid, _audit = _submitted_service()
        seq: list[str] = []
        real_approve = bank.approve
        real_audit = service._audit_ingest_event

        def _spy_approve(d: str) -> int:
            seq.append("mutate")
            return real_approve(d)

        def _spy_audit(**kwargs: Any) -> None:
            seq.append("audit")
            real_audit(**kwargs)

        with patch.object(bank, "approve", side_effect=_spy_approve), \
                patch.object(
                    service, "_audit_ingest_event", side_effect=_spy_audit
                ):
            transport = _FakeTransport(
                _framer.encode_ingest_decision(
                    doc_uuid=doc_uuid, decision="approve"
                )
            )
            service._handle_connection(transport)
        assert _last_result(transport)["ok"] is True
        assert seq == ["audit", "mutate"]

    def test_decision_mutation_failure_appends_compensating_deny(self) -> None:
        """The documented residual convention: a mutation failing AFTER a
        successful audit append gets a best-effort '<verb>_FAILED' DENY
        record so the chain never shows an unresolved ALLOW."""
        service, bank, doc_uuid, audit = _submitted_service()
        with patch.object(
            bank, "approve", side_effect=RuntimeError("boom mid-mutation")
        ):
            transport = _FakeTransport(
                _framer.encode_ingest_decision(
                    doc_uuid=doc_uuid, decision="approve"
                )
            )
            service._handle_connection(transport)
        result = _last_result(transport)
        assert result["ok"] is False
        assert result["error_code"] == "INGEST_DECISION_FAILED"
        assert [r.verb for r in audit.records] == [
            "INGEST_SUBMIT",
            "INGEST_APPROVE",
            "INGEST_APPROVE_FAILED",
        ]
        assert audit.records[-1].decision == "DENY"
        assert bank.get_doc(doc_uuid).approval_state == "pending"

    def test_submit_mutation_failure_appends_compensating_deny(self) -> None:
        service, bank, cipher, audit = _make_service_with_bank()
        doc_uuid = str(uuid.uuid4())
        staged = _stage_article(cipher, doc_uuid, _CONTENT)
        with patch.object(
            bank, "submit_pending", side_effect=RuntimeError("boom mid-mutation")
        ):
            transport = _FakeTransport(_submit_frame(doc_uuid, _CONTENT))
            service._handle_connection(transport)
        result = _last_result(transport)
        assert result["ok"] is False
        assert result["error_code"] == "INGEST_SUBMIT_FAILED"
        assert [(r.verb, r.decision) for r in audit.records] == [
            ("INGEST_SUBMIT", "ESCALATE"),
            ("INGEST_SUBMIT_FAILED", "DENY"),
        ]
        assert bank.count() == 0
        assert staged.exists()

    def test_deterministic_refusal_writes_no_audit_record(self) -> None:
        """Refusals that mutate nothing owe no audit record: an unknown doc
        and a reject-an-approved both refuse BEFORE the audit append."""
        service, bank, doc_uuid, audit = _submitted_service()
        # Unknown doc.
        t1 = _FakeTransport(
            _framer.encode_ingest_decision(
                doc_uuid=str(uuid.uuid4()), decision="approve"
            )
        )
        service._handle_connection(t1)
        assert _last_result(t1)["error_code"] == "INGEST_DECISION_REFUSED"
        assert [r.verb for r in audit.records] == ["INGEST_SUBMIT"]
        # Reject an approved doc.
        bank.approve(doc_uuid)
        service._audit_ingest_event(
            verb="INGEST_APPROVE",
            decision="ALLOW",
            doc_uuid=doc_uuid,
            source_hash_hex=bank.source_hash_hex_for(doc_uuid),
        )
        t2 = _FakeTransport(
            _framer.encode_ingest_decision(doc_uuid=doc_uuid, decision="reject")
        )
        service._handle_connection(t2)
        assert _last_result(t2)["error_code"] == "INGEST_DECISION_REFUSED"
        assert [r.verb for r in audit.records] == [
            "INGEST_SUBMIT",
            "INGEST_APPROVE",
        ]


# ---------------------------------------------------------------------------
# 7. content_sha256 is REQUIRED at the AO seam (#655 review FIX 6)
# ---------------------------------------------------------------------------


class TestContentSha256Required:
    @pytest.mark.parametrize("payload_extra", [{}, {"content_sha256": ""}, {"content_sha256": "   "}])
    def test_absent_or_empty_content_sha256_refused(
        self, payload_extra: dict[str, str]
    ) -> None:
        """Absent/empty content_sha256 → INGEST_SUBMIT_INVALID, nothing
        persisted, staging retained, no audit record (the pre-fix code
        silently SKIPPED the integrity cross-check)."""
        service, bank, cipher, audit = _make_service_with_bank()
        doc_uuid = str(uuid.uuid4())
        staged = _stage_article(cipher, doc_uuid, _CONTENT)
        payload: dict[str, Any] = {
            "doc_uuid": doc_uuid,
            "source_type": "url",
            "source_ref": "https://example.org/articles/a",
            "staging_path": "",
            **payload_extra,
        }
        raw = _framer.encode(MessageType.INGEST_SUBMIT, payload, "r1")
        transport = _FakeTransport(raw)
        service._handle_connection(transport)
        result = _last_result(transport)
        assert result["ok"] is False
        assert result["error_code"] == "INGEST_SUBMIT_INVALID"
        assert "content_sha256" in result["message"]
        assert bank.count() == 0
        assert staged.exists()
        assert len(audit.records) == 0


# ---------------------------------------------------------------------------
# 8. Substrate embed_fn follows substrate_meta (#655 review FIX 4)
# ---------------------------------------------------------------------------


class TestSubstrateEmbedWindowBinding:
    @staticmethod
    def _recording_detector() -> tuple[types.SimpleNamespace, list[int]]:
        calls: list[int] = []

        def embed_documents(
            texts: list[str], max_length: int = 512
        ) -> np.ndarray:
            calls.append(int(max_length))
            return fake_embed(texts)

        return (
            types.SimpleNamespace(
                loaded=True, _embed=fake_embed, embed_documents=embed_documents
            ),
            calls,
        )

    def test_binding_follows_substrate_meta(self, tmp_path: Path) -> None:
        """Absent meta → the bound embed_fn calls at the legacy 128-token
        window (today's behaviour, unchanged); after the migration stamps
        embed_max_tokens=512 a rebuild binds at 512 — post-ceremony ingests
        can no longer re-create the mixed-depth store ADR-031 §3 rejects."""
        import sqlite3 as _sqlite3

        from services.assistant_orchestrator.src import pgov as pgov_mod

        detector, calls = self._recording_detector()
        with patch.object(pgov_mod, "_get_detector", return_value=detector):
            with patch.dict(
                "os.environ",
                {"LOCALAPPDATA": str(tmp_path), "BLARAI_DEK_KEYSTORE": ""},
            ):
                orch = AssistantOrchestratorService.__new__(
                    AssistantOrchestratorService
                )
                orch._resolved_config = _make_resolved_config(dev_mode=True)

                store = orch._build_substrate()
                assert store is not None
                store._embed(["window probe"])
                assert calls[-1] == 128  # absent meta → legacy window
                store.close()

                # Stamp the migration's meta key, rebuild → 512 binding.
                db = tmp_path / "BlarAI" / "substrate.db"
                conn = _sqlite3.connect(str(db))
                conn.execute(
                    "INSERT OR REPLACE INTO substrate_meta(key, value) "
                    "VALUES('embed_max_tokens', '512')"
                )
                conn.commit()
                conn.close()

                store2 = orch._build_substrate()
                assert store2 is not None
                store2._embed(["window probe"])
                assert calls[-1] == 512  # post-migration → stored window
                store2.close()

    def test_knowledge_meta_records_configured_window(self) -> None:
        """_build_knowledge_bank stamps the CONFIGURED [knowledge]
        .embed_max_tokens into knowledge_meta (not the module constant)."""
        from services.assistant_orchestrator.src import pgov as pgov_mod

        with patch.object(pgov_mod, "_get_detector", return_value=_fake_detector()):
            with patch.dict(
                "os.environ", {"LOCALAPPDATA": "", "BLARAI_DEK_KEYSTORE": ""}
            ):
                orch = AssistantOrchestratorService.__new__(
                    AssistantOrchestratorService
                )
                orch._resolved_config = _make_resolved_config(
                    knowledge_embed_max_tokens=384
                )
                bank = orch._build_knowledge_bank()
        assert bank is not None
        try:
            row = bank._conn.execute(
                "SELECT value FROM knowledge_meta WHERE key='embed_max_tokens'"
            ).fetchone()
            assert row[0] == "384"
        finally:
            bank.close()


# ---------------------------------------------------------------------------
# 9. Content-fingerprint membership-oracle close (#655 LA verdict 2026-06-10)
# ---------------------------------------------------------------------------


class TestContentFingerprintMembershipOracleClosed:
    """The plaintext content SHA-256 must never reach the audit JSONL bytes;
    the keyed digest is what the chain carries; and the staged-content
    integrity cross-check still refuses tampered staging — the verification
    capability the keyed form must not cost."""

    def test_audit_jsonl_raw_bytes_carry_keyed_digest_never_plaintext_sha(
        self, tmp_path: Path
    ) -> None:
        service, bank, cipher, _mem_audit = _make_service_with_bank()
        audit_path = tmp_path / "audit" / "ingest_audit.jsonl"
        service._ingest_audit = AuditLog.from_path(
            audit_path, HmacSha256Signer(key=b"k" * 32)
        )
        doc_uuid = str(uuid.uuid4())
        _stage_article(cipher, doc_uuid, _CONTENT)
        transport = _FakeTransport(_submit_frame(doc_uuid, _CONTENT))
        service._handle_connection(transport)
        assert _last_result(transport)["ok"] is True

        plaintext_sha = hashlib.sha256(_CONTENT.encode("utf-8")).hexdigest()
        keyed_hex = bank.content_digest_keyed_hex(plaintext_sha)
        raw = audit_path.read_bytes()
        # The signed-PLAINTEXT file must never carry the plaintext digest —
        # it would recreate the membership oracle the keyed column closes.
        assert plaintext_sha.encode("ascii") not in raw
        assert plaintext_sha.upper().encode("ascii") not in raw
        # The keyed form IS recorded (car_hash), and parses back as such.
        assert keyed_hex.encode("ascii") in raw
        last_record = json.loads(raw.splitlines()[-1].decode("utf-8"))
        assert last_record["car_hash"] == keyed_hex

    def test_tampered_staging_file_refused_by_cross_check(self) -> None:
        """Swap the staged ciphertext for a validly-encrypted file carrying
        DIFFERENT content (same doc identity, same key): the AO's recompute-
        and-compare against the frame's plaintext sha must refuse — nothing
        persisted, nothing audited, staging retained for forensics."""
        service, bank, cipher, audit = _make_service_with_bank()
        doc_uuid = str(uuid.uuid4())
        _stage_article(cipher, doc_uuid, _CONTENT)
        _stage_article(
            cipher, doc_uuid, "tampered article body that differs entirely"
        )

        transport = _FakeTransport(_submit_frame(doc_uuid, _CONTENT))
        service._handle_connection(transport)

        result = _last_result(transport)
        assert result["ok"] is False
        assert result["error_code"] == "INGEST_CONTENT_HASH_MISMATCH"
        assert bank.count() == 0
        assert len(audit.records) == 0
