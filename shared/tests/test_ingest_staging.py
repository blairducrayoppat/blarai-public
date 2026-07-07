"""
Tests for the encrypted ingest staging handoff (shared/security/ingest_staging.py).

The staging file is the ONLY channel cleaned content uses to cross the
gateway -> AO boundary (the IPC frame carries labels only).  Locked here:
AES-GCM round trip, AAD binding to the doc identity, doc_uuid validation
(traversal-shaped identifiers refuse before any path exists), the byte cap,
the claimed-path cross-check, and delete-after-persist.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shared.security.dek_envelope import DekEnvelope, generate_recovery_key
from shared.security.field_cipher import FieldCipher, derive_subkeys
from shared.security.ingest_staging import (
    StagingError,
    default_staging_dir,
    delete_staged,
    read_staged,
    staging_path_for,
    validate_doc_uuid,
    write_staged,
)
from shared.security.tpm_sealer import SoftwareSealer

_DOC_UUID = "0c9adf1e-66cb-4d8e-9b3e-9a4ff1f0a111"
_CONTENT = "Cleaned article body: turbochargers compress intake air. " * 20


def _make_cipher() -> FieldCipher:
    env = DekEnvelope.create(
        sealer=SoftwareSealer(), recovery_key=generate_recovery_key()
    )
    return FieldCipher(derive_subkeys(env.unseal_dek()))


@pytest.fixture()
def cipher() -> FieldCipher:
    return _make_cipher()


class TestDocUuidValidation:
    def test_canonical_uuid_passes(self) -> None:
        assert validate_doc_uuid(_DOC_UUID) == _DOC_UUID

    def test_whitespace_normalised(self) -> None:
        assert validate_doc_uuid(f"  {_DOC_UUID}  ") == _DOC_UUID

    @pytest.mark.parametrize(
        "bad",
        ["", "not-a-uuid", "..\\evil", "../../etc/passwd", "a" * 64, "x.bin"],
    )
    def test_traversal_and_garbage_refuse(self, bad: str) -> None:
        with pytest.raises(StagingError):
            validate_doc_uuid(bad)

    def test_staging_path_for_validates(self, tmp_path: Path) -> None:
        with pytest.raises(StagingError):
            staging_path_for("..\\evil", tmp_path)
        path = staging_path_for(_DOC_UUID, tmp_path)
        assert path == tmp_path / f"{_DOC_UUID}.bin"


class TestWriteReadDelete:
    def test_round_trip(self, tmp_path: Path, cipher: FieldCipher) -> None:
        path = write_staged(_CONTENT, _DOC_UUID, cipher, tmp_path)
        assert path.exists()
        assert read_staged(_DOC_UUID, cipher, tmp_path) == _CONTENT

    def test_encrypted_on_disk(self, tmp_path: Path, cipher: FieldCipher) -> None:
        path = write_staged(_CONTENT, _DOC_UUID, cipher, tmp_path)
        raw = path.read_bytes()
        assert b"turbochargers compress" not in raw

    def test_write_creates_directory(self, tmp_path: Path, cipher: FieldCipher) -> None:
        nested = tmp_path / "BlarAI" / "ingest_staging"
        write_staged(_CONTENT, _DOC_UUID, cipher, nested)
        assert (nested / f"{_DOC_UUID}.bin").exists()

    def test_wrong_cipher_fails_closed(self, tmp_path: Path, cipher: FieldCipher) -> None:
        write_staged(_CONTENT, _DOC_UUID, cipher, tmp_path)
        with pytest.raises(StagingError):
            read_staged(_DOC_UUID, _make_cipher(), tmp_path)

    def test_aad_binds_doc_identity(self, tmp_path: Path, cipher: FieldCipher) -> None:
        """A staged blob renamed to a different doc_uuid refuses to decrypt —
        the AAD pins content to the identity it was staged under."""
        other_uuid = "11111111-2222-4333-8444-555555555555"
        path = write_staged(_CONTENT, _DOC_UUID, cipher, tmp_path)
        path.rename(tmp_path / f"{other_uuid}.bin")
        with pytest.raises(StagingError):
            read_staged(other_uuid, cipher, tmp_path)

    def test_missing_file_raises(self, tmp_path: Path, cipher: FieldCipher) -> None:
        with pytest.raises(StagingError):
            read_staged(_DOC_UUID, cipher, tmp_path)

    def test_oversize_file_refused_by_cap(
        self, tmp_path: Path, cipher: FieldCipher
    ) -> None:
        write_staged(_CONTENT, _DOC_UUID, cipher, tmp_path)
        with pytest.raises(StagingError, match="cap"):
            read_staged(_DOC_UUID, cipher, tmp_path, max_bytes=16)

    def test_tampered_blob_fails_closed(
        self, tmp_path: Path, cipher: FieldCipher
    ) -> None:
        path = write_staged(_CONTENT, _DOC_UUID, cipher, tmp_path)
        blob = bytearray(path.read_bytes())
        blob[len(blob) // 2] ^= 0xFF
        path.write_bytes(bytes(blob))
        with pytest.raises(StagingError):
            read_staged(_DOC_UUID, cipher, tmp_path)

    def test_delete_staged(self, tmp_path: Path, cipher: FieldCipher) -> None:
        path = write_staged(_CONTENT, _DOC_UUID, cipher, tmp_path)
        assert delete_staged(_DOC_UUID, tmp_path) is True
        assert not path.exists()
        assert delete_staged(_DOC_UUID, tmp_path) is False  # idempotent

    def test_delete_never_raises_on_bad_uuid(self, tmp_path: Path) -> None:
        assert delete_staged("..\\evil", tmp_path) is False


class TestClaimedPathCrossCheck:
    def test_matching_claimed_path_accepted(
        self, tmp_path: Path, cipher: FieldCipher
    ) -> None:
        path = write_staged(_CONTENT, _DOC_UUID, cipher, tmp_path)
        assert (
            read_staged(_DOC_UUID, cipher, tmp_path, claimed_path=str(path))
            == _CONTENT
        )

    def test_mismatched_claimed_path_refuses(
        self, tmp_path: Path, cipher: FieldCipher
    ) -> None:
        """A payload-supplied path pointing elsewhere is never dereferenced."""
        write_staged(_CONTENT, _DOC_UUID, cipher, tmp_path)
        elsewhere = tmp_path / "elsewhere" / f"{_DOC_UUID}.bin"
        with pytest.raises(StagingError, match="canonical"):
            read_staged(
                _DOC_UUID, cipher, tmp_path, claimed_path=str(elsewhere)
            )

    def test_empty_claimed_path_ignored(
        self, tmp_path: Path, cipher: FieldCipher
    ) -> None:
        write_staged(_CONTENT, _DOC_UUID, cipher, tmp_path)
        assert read_staged(_DOC_UUID, cipher, tmp_path, claimed_path="") == _CONTENT


class TestDefaultStagingDir:
    def test_resolves_under_localappdata(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        assert default_staging_dir() == tmp_path / "BlarAI" / "ingest_staging"

    def test_refuses_without_localappdata(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LOCALAPPDATA", "")
        with pytest.raises(StagingError):
            default_staging_dir()
