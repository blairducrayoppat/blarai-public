"""
Tests for the encrypted image staging handoff (shared/security/image_staging.py).

The image staging blob is the ONLY channel display-only image BYTES use to
cross the gateway -> AO boundary (the IPC frame carries image metadata only,
mirroring how cleaned text crosses via ``ingest_staging``).  Locked here:
AES-GCM round trip on raw bytes, AAD binding to BOTH the doc AND image
identity (a blob replayed under a different (doc, image) pair refuses),
``image_id`` uuid4-hex validation (traversal-shaped / dashed / wrong-length
ids refuse before any path exists), the byte cap, the claimed-path
cross-check, and fail-safe delete.  DORMANT: nothing here fetches.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from shared.security.dek_envelope import DekEnvelope, generate_recovery_key
from shared.security.field_cipher import FieldCipher, derive_subkeys
from shared.security.image_staging import (
    DEFAULT_IMAGE_STAGING_MAX_BYTES,
    MAX_IMAGE_BYTES,
    ImageStagingError,
    delete_staged_image,
    image_staging_path_for,
    read_staged_image,
    validate_image_id,
    write_staged_image,
)
from shared.security.ingest_staging import StagingError
from shared.security.tpm_sealer import SoftwareSealer

_DOC_UUID = "0c9adf1e-66cb-4d8e-9b3e-9a4ff1f0a111"
_IMAGE_ID = uuid.uuid4().hex
# A 1x1 PNG-ish byte string is unnecessary here — staging is format-agnostic
# (the door validated the MIME upstream); raw bytes round-tripping is what we lock.
_IMAGE_BYTES = b"\x89PNG\r\n\x1a\n" + b"display-only image payload \x00\xff" * 50


def _make_cipher() -> FieldCipher:
    env = DekEnvelope.create(
        sealer=SoftwareSealer(), recovery_key=generate_recovery_key()
    )
    return FieldCipher(derive_subkeys(env.unseal_dek()))


@pytest.fixture()
def cipher() -> FieldCipher:
    return _make_cipher()


class TestImageIdValidation:
    def test_canonical_hex_passes(self) -> None:
        assert validate_image_id(_IMAGE_ID) == _IMAGE_ID

    def test_uppercase_normalised(self) -> None:
        assert validate_image_id(_IMAGE_ID.upper()) == _IMAGE_ID

    def test_whitespace_normalised(self) -> None:
        assert validate_image_id(f"  {_IMAGE_ID}  ") == _IMAGE_ID

    @pytest.mark.parametrize(
        "bad",
        [
            "",
            "not-a-uuid",
            "..\\evil",
            "../../etc/passwd",
            "a" * 31,  # too short
            "a" * 33,  # too long
            "z" * 32,  # not hex
            _DOC_UUID,  # dashed canonical UUID — rejected, only bare hex stored
            "x.bin",
        ],
    )
    def test_garbage_and_dashed_refuse(self, bad: str) -> None:
        with pytest.raises(ImageStagingError):
            validate_image_id(bad)

    def test_path_for_validates_both_ids(self, tmp_path: Path) -> None:
        # Bad image id refuses.
        with pytest.raises(ImageStagingError):
            image_staging_path_for("..\\evil", _DOC_UUID, tmp_path)
        # Bad doc uuid refuses (validate_doc_uuid raises StagingError, a
        # superclass-sibling RuntimeError — either fail-closed type is fine).
        with pytest.raises((ImageStagingError, StagingError)):
            image_staging_path_for(_IMAGE_ID, "..\\evil", tmp_path)
        path = image_staging_path_for(_IMAGE_ID, _DOC_UUID, tmp_path)
        assert path == tmp_path / f"{_DOC_UUID}__{_IMAGE_ID}.bin"


class TestWriteReadDelete:
    def test_round_trip(self, tmp_path: Path, cipher: FieldCipher) -> None:
        path = write_staged_image(_IMAGE_BYTES, _IMAGE_ID, _DOC_UUID, cipher, tmp_path)
        assert path.exists()
        assert path.name == f"{_DOC_UUID}__{_IMAGE_ID}.bin"
        assert (
            read_staged_image(_IMAGE_ID, _DOC_UUID, cipher, tmp_path) == _IMAGE_BYTES
        )

    def test_encrypted_on_disk(self, tmp_path: Path, cipher: FieldCipher) -> None:
        path = write_staged_image(_IMAGE_BYTES, _IMAGE_ID, _DOC_UUID, cipher, tmp_path)
        raw = path.read_bytes()
        assert b"display-only image payload" not in raw

    def test_write_creates_directory(self, tmp_path: Path, cipher: FieldCipher) -> None:
        nested = tmp_path / "BlarAI" / "ingest_staging"
        write_staged_image(_IMAGE_BYTES, _IMAGE_ID, _DOC_UUID, cipher, nested)
        assert (nested / f"{_DOC_UUID}__{_IMAGE_ID}.bin").exists()

    def test_wrong_cipher_fails_closed(
        self, tmp_path: Path, cipher: FieldCipher
    ) -> None:
        write_staged_image(_IMAGE_BYTES, _IMAGE_ID, _DOC_UUID, cipher, tmp_path)
        with pytest.raises(ImageStagingError):
            read_staged_image(_IMAGE_ID, _DOC_UUID, _make_cipher(), tmp_path)

    def test_aad_binds_image_identity(
        self, tmp_path: Path, cipher: FieldCipher
    ) -> None:
        """A blob renamed to a different IMAGE id (same doc) refuses to decrypt —
        the AAD pins content to the (doc, image) identity it was staged under."""
        other_image = uuid.uuid4().hex
        path = write_staged_image(
            _IMAGE_BYTES, _IMAGE_ID, _DOC_UUID, cipher, tmp_path
        )
        path.rename(tmp_path / f"{_DOC_UUID}__{other_image}.bin")
        with pytest.raises(ImageStagingError):
            read_staged_image(other_image, _DOC_UUID, cipher, tmp_path)

    def test_aad_binds_doc_identity(
        self, tmp_path: Path, cipher: FieldCipher
    ) -> None:
        """A blob renamed to a different DOC (same image id) refuses to decrypt."""
        other_doc = "11111111-2222-4333-8444-555555555555"
        path = write_staged_image(
            _IMAGE_BYTES, _IMAGE_ID, _DOC_UUID, cipher, tmp_path
        )
        path.rename(tmp_path / f"{other_doc}__{_IMAGE_ID}.bin")
        with pytest.raises(ImageStagingError):
            read_staged_image(_IMAGE_ID, other_doc, cipher, tmp_path)

    def test_missing_file_raises(self, tmp_path: Path, cipher: FieldCipher) -> None:
        with pytest.raises(ImageStagingError):
            read_staged_image(_IMAGE_ID, _DOC_UUID, cipher, tmp_path)

    def test_oversize_file_refused_by_cap(
        self, tmp_path: Path, cipher: FieldCipher
    ) -> None:
        write_staged_image(_IMAGE_BYTES, _IMAGE_ID, _DOC_UUID, cipher, tmp_path)
        with pytest.raises(ImageStagingError, match="cap"):
            read_staged_image(_IMAGE_ID, _DOC_UUID, cipher, tmp_path, max_bytes=16)

    def test_default_cap_sized_for_a_generated_seed_image(self) -> None:
        """The /edit SEED read cap is sized for a GENERATED image (a 1536² hires
        PNG is ~3-4 MB), decoupled from the 2 MiB egress cap — a seed is local /
        generated, not door-fetched (#666). The egress cap itself is unchanged."""
        from shared.security.image_staging import SEED_IMAGE_MAX_BYTES

        assert MAX_IMAGE_BYTES == 2 * 1024 * 1024  # egress cap untouched
        assert SEED_IMAGE_MAX_BYTES == 16 * 1024 * 1024
        assert DEFAULT_IMAGE_STAGING_MAX_BYTES > MAX_IMAGE_BYTES
        assert DEFAULT_IMAGE_STAGING_MAX_BYTES >= 16 * 1024 * 1024

    def test_generated_size_seed_round_trips_at_default_cap(
        self, tmp_path: Path, cipher: FieldCipher
    ) -> None:
        """A generated-image-sized seed (~3 MiB, over the OLD 2 MiB cap) now
        round-trips at the default cap — the #666 /edit-on-hires-image fix (a
        3.1 MB hires seed had been refused fail-closed on read)."""
        big = b"\x89PNG\r\n\x1a\n" + b"\x00" * (3 * 1024 * 1024)
        write_staged_image(big, _IMAGE_ID, _DOC_UUID, cipher, tmp_path)
        out = read_staged_image(_IMAGE_ID, _DOC_UUID, cipher, tmp_path)
        assert out == big

    def test_tampered_blob_fails_closed(
        self, tmp_path: Path, cipher: FieldCipher
    ) -> None:
        path = write_staged_image(_IMAGE_BYTES, _IMAGE_ID, _DOC_UUID, cipher, tmp_path)
        blob = bytearray(path.read_bytes())
        blob[len(blob) // 2] ^= 0xFF
        path.write_bytes(bytes(blob))
        with pytest.raises(ImageStagingError):
            read_staged_image(_IMAGE_ID, _DOC_UUID, cipher, tmp_path)

    def test_delete_staged_image(self, tmp_path: Path, cipher: FieldCipher) -> None:
        path = write_staged_image(_IMAGE_BYTES, _IMAGE_ID, _DOC_UUID, cipher, tmp_path)
        assert delete_staged_image(_IMAGE_ID, _DOC_UUID, tmp_path) is True
        assert not path.exists()
        # idempotent
        assert delete_staged_image(_IMAGE_ID, _DOC_UUID, tmp_path) is False

    def test_delete_never_raises_on_bad_id(self, tmp_path: Path) -> None:
        assert delete_staged_image("..\\evil", _DOC_UUID, tmp_path) is False
        assert delete_staged_image(_IMAGE_ID, "..\\evil", tmp_path) is False


class TestClaimedPathCrossCheck:
    def test_matching_claimed_path_accepted(
        self, tmp_path: Path, cipher: FieldCipher
    ) -> None:
        path = write_staged_image(_IMAGE_BYTES, _IMAGE_ID, _DOC_UUID, cipher, tmp_path)
        assert (
            read_staged_image(
                _IMAGE_ID, _DOC_UUID, cipher, tmp_path, claimed_path=str(path)
            )
            == _IMAGE_BYTES
        )

    def test_mismatched_claimed_path_refuses(
        self, tmp_path: Path, cipher: FieldCipher
    ) -> None:
        """A payload-supplied path pointing elsewhere is never dereferenced."""
        write_staged_image(_IMAGE_BYTES, _IMAGE_ID, _DOC_UUID, cipher, tmp_path)
        elsewhere = tmp_path / "elsewhere" / f"{_DOC_UUID}__{_IMAGE_ID}.bin"
        with pytest.raises(ImageStagingError, match="canonical"):
            read_staged_image(
                _IMAGE_ID, _DOC_UUID, cipher, tmp_path, claimed_path=str(elsewhere)
            )

    def test_empty_claimed_path_ignored(
        self, tmp_path: Path, cipher: FieldCipher
    ) -> None:
        write_staged_image(_IMAGE_BYTES, _IMAGE_ID, _DOC_UUID, cipher, tmp_path)
        assert (
            read_staged_image(_IMAGE_ID, _DOC_UUID, cipher, tmp_path, claimed_path="")
            == _IMAGE_BYTES
        )
