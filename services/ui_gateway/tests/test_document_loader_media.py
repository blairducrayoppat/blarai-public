"""
Tests for media support in document_loader + the picker path.

Covers:
  - photo / video extensions in the allowlist
  - classify_media routing
  - load_document for an image → LAZY staged descriptor (#561): no pixels read,
    no VLM call at attach, image_path + pending_vision carried for the AO
  - load_document for video → store-only descriptor (no error)
  - media size caps
  - store_attachment copy-into-userdata + collision-safe rename
  - list_userdata_files surfaces media_type
"""

from __future__ import annotations

from pathlib import Path

import pytest

from services.ui_gateway.src.document_loader import (
    ALLOWED_EXTENSIONS,
    IMAGE_MAX_BYTES,
    MEDIA_EXTENSIONS,
    PHOTO_EXTENSIONS,
    VIDEO_EXTENSIONS,
    DocumentLoadError,
    classify_media,
    load_document,
    store_attachment,
)


@pytest.fixture()
def userdata_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    import services.ui_gateway.src.document_loader as mod

    monkeypatch.setattr(mod, "USERDATA_DIR", tmp_path)
    return tmp_path


# ── Extension taxonomy ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "ext",
    [".png", ".jpg", ".jpeg", ".jfif", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif"],
)
def test_photo_extensions_allowed(ext: str) -> None:
    assert ext in PHOTO_EXTENSIONS
    assert ext in ALLOWED_EXTENSIONS


@pytest.mark.parametrize("ext", [".mp4", ".mov", ".webm"])
def test_video_extensions_allowed(ext: str) -> None:
    assert ext in VIDEO_EXTENSIONS
    assert ext in ALLOWED_EXTENSIONS


def test_text_extensions_still_allowed() -> None:
    for ext in (".txt", ".md", ".pdf"):
        assert ext in ALLOWED_EXTENSIONS
        assert ext not in MEDIA_EXTENSIONS


@pytest.mark.parametrize(
    "name,expected",
    [
        ("cat.png", "image"),
        ("CAT.JPG", "image"),
        ("clip.mp4", "video"),
        ("notes.txt", "text"),
        ("doc.pdf", "text"),
    ],
)
def test_classify_media(name: str, expected: str) -> None:
    assert classify_media(name) == expected


# ── load_document: store-only media ────────────────────────────────────


def test_load_image_is_lazy_staged(userdata_tmp: Path) -> None:
    """An image attach is LAZY (#561): no grounding content, but it carries the
    resolved path + pending_vision so the AO can task the VLM on demand, and a
    user-facing 'staged' message."""
    (userdata_tmp / "cat.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    result = load_document("cat.png")
    assert result["filename"] == "cat.png"
    assert result["media_type"] == "image"
    assert result["pending_vision"] is True
    assert result["content"] == ""  # nothing grounded at attach
    # path points at the staged file inside userdata/, so the AO can open it
    assert result["image_path"].endswith("cat.png")
    assert Path(result["image_path"]).resolve() == (userdata_tmp / "cat.png").resolve()
    # message tells the user it is staged, to be looked at on demand
    assert "ask about it" in result["message"]


def test_load_image_does_not_call_vlm_on_attach(
    userdata_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Attach must NOT run the VLM — that is the whole point of lazy grounding
    (#561). If describe_image is invoked at attach, fail loudly."""
    def _boom(*_a: object, **_k: object) -> str:
        raise AssertionError("describe_image must not be called at attach time")

    monkeypatch.setattr("shared.inference.vlm.describe_image", _boom)
    (userdata_tmp / "cat.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    result = load_document("cat.png")  # must not raise
    assert result["pending_vision"] is True


def test_load_video_is_store_only(userdata_tmp: Path) -> None:
    (userdata_tmp / "clip.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 16)
    result = load_document("clip.mp4")
    assert result["media_type"] == "video"
    assert "video understanding is not yet wired" in result["message"]


def test_text_load_reports_media_type_text(userdata_tmp: Path) -> None:
    (userdata_tmp / "n.txt").write_text("hello", encoding="utf-8")
    result = load_document("n.txt")
    assert result["media_type"] == "text"
    assert result["message"] == ""


def test_oversized_image_rejected(
    userdata_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import services.ui_gateway.src.document_loader as mod

    monkeypatch.setattr(mod, "IMAGE_MAX_BYTES", 16)
    (userdata_tmp / "big.png").write_bytes(b"x" * 32)
    with pytest.raises(DocumentLoadError, match="Image too large"):
        load_document("big.png")


def test_image_below_cap_accepted(userdata_tmp: Path) -> None:
    # A small image well under the real 16 MB cap loads fine.
    (userdata_tmp / "ok.webp").write_bytes(b"RIFF\x00\x00\x00\x00WEBP")
    assert load_document("ok.webp")["media_type"] == "image"
    assert IMAGE_MAX_BYTES > 1_000_000  # sanity: real cap is generous


# ── store_attachment (picker / drag-drop path) ─────────────────────────


def test_store_attachment_copies_into_userdata(
    userdata_tmp: Path, tmp_path: Path
) -> None:
    src = tmp_path / "elsewhere" / "report.txt"
    src.parent.mkdir()
    src.write_text("quarterly numbers", encoding="utf-8")
    result = store_attachment(str(src))
    assert result["filename"] == "report.txt"
    assert (userdata_tmp / "report.txt").exists()
    assert result["content"] == "quarterly numbers"


def test_store_attachment_image(userdata_tmp: Path, tmp_path: Path) -> None:
    src = tmp_path / "incoming" / "photo.jpg"
    src.parent.mkdir()
    src.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 16)
    result = store_attachment(str(src))
    assert result["media_type"] == "image"
    assert (userdata_tmp / "photo.jpg").exists()


def test_store_attachment_collision_renames(
    userdata_tmp: Path, tmp_path: Path
) -> None:
    (userdata_tmp / "doc.txt").write_text("existing", encoding="utf-8")
    # Source must live OUTSIDE userdata/ (here userdata == tmp_path).
    src = tmp_path / "incoming" / "doc.txt"
    src.parent.mkdir()
    src.write_text("incoming", encoding="utf-8")
    result = store_attachment(str(src))
    assert result["filename"] == "doc (1).txt"
    assert (userdata_tmp / "doc (1).txt").read_text(encoding="utf-8") == "incoming"
    # original is untouched
    assert (userdata_tmp / "doc.txt").read_text(encoding="utf-8") == "existing"


def test_store_attachment_unsupported_extension(tmp_path: Path) -> None:
    src = tmp_path / "evil.exe"
    src.write_bytes(b"MZ")
    with pytest.raises(DocumentLoadError, match="Unsupported file type"):
        store_attachment(str(src))


def test_store_attachment_missing_file(tmp_path: Path) -> None:
    with pytest.raises(DocumentLoadError, match="not found"):
        store_attachment(str(tmp_path / "ghost.txt"))


def test_store_attachment_empty_path() -> None:
    with pytest.raises(DocumentLoadError, match="No file path"):
        store_attachment("   ")


# ── list_userdata_files surfaces media_type ────────────────────────────


def test_list_userdata_files_flags_media(
    userdata_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from services.ui_gateway.src.transport import TransportGateway

    (userdata_tmp / "a.txt").write_text("x", encoding="utf-8")
    (userdata_tmp / "b.png").write_bytes(b"\x89PNG")
    (userdata_tmp / "c.mp4").write_bytes(b"\x00" * 8)

    gateway = TransportGateway(session_store=None, dev_mode=True, port=0)
    files = {f["filename"]: f["media_type"] for f in gateway.list_userdata_files()}
    assert files == {"a.txt": "text", "b.png": "image", "c.mp4": "video"}
