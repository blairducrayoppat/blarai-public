"""Regression locks for the gateway-side display-only image corridor.

UC-003 Workstream B (display-only images) — DORMANT.  The feature code already
exists in ``services/ui_gateway/src/ingest_coordinator.py`` (the ``_process_images``
method, the 5-tuple ``_stage_and_submit``, the ``images_enabled`` / ``image_fetch_fn``
/ ``image_consent_fn`` constructor params, and the ``images=`` arm of
``encode_ingest_submit``); these tests LOCK its behaviour.  No real socket is ever
touched — the binary egress door is INJECTED as a fake ``image_fetch_fn`` callable
``(url, purpose) -> obj`` where ``obj`` carries ``.ok`` / ``.content_bytes`` /
``.mime`` / ``.content_type`` / ``.truncated`` / ``.denied_reason`` (the structural
shape of ``shared.security.guarded_fetch.BinaryFetchResult``).

CD-1 (LA-locked 2026-06-15): ONLY a URL-ingested article fetches remote images —
paste/file content never silently becomes a network egress.  So the "image fetch"
tests drive the URL-mode tail (``_finalize_clean`` with ``source_type='url'``); the
DORMANT tests drive the shipped paste path (which, with ``images_enabled=False``,
never fetches regardless of source type).  Same-site images (host == the article
host) ride the existing ``/ingest`` consent; off-site images need the coarse
per-article consent (``image_consent_fn``, fail-closed).

THE LOAD-BEARING TEST is ``TestImagesDormant.test_dormant_never_fetches_and_strips_refs``:
with ``images_enabled=False`` (the shipped default) the injected fetch fn is
proven NEVER called and every remote ref collapses to a ``[image: alt]`` placeholder.

Model-free; no AO; staging dirs are tmp_path-injected (the root conftest
redirects LOCALAPPDATA besides).  Reuses the fixtures/helpers from
``test_ingest_coordinator.py``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from services.ui_gateway.src.ingest_coordinator import (
    DEFAULT_INGEST_MAX_BYTES,
    IngestCommand,
    IngestCoordinator,
)
from shared.security.field_cipher import FieldCipher
from shared.security.guarded_fetch import (
    MAX_IMAGES_PER_ARTICLE,
    MAX_TOTAL_IMAGE_BYTES,
)
from shared.security.image_egress_consent import (
    ImageEgressConsentContext,
    clear_image_egress_verifier,
)
from shared.security.image_staging import read_staged_image

# Reuse the proven fakes + helpers from the sibling coordinator test module
# (its FakePipeline / FakeTransportCall / _make_coordinator are the canonical
# idiom for building an IngestCoordinator with everything mocked).
from services.ui_gateway.tests.test_ingest_coordinator import (
    FakeCleanResult,
    FakePipeline,
    FakeTransportCall,
    _cipher,
    _envelope,
)


def _png_header(w: int, h: int) -> bytes:
    """A real PNG header with an in-band IHDR width/height (no decode needed) —
    READABLE by guarded_fetch.image_dimensions, so the dimension gate keeps it
    (unless the dims are below the floor / above the bomb ceiling)."""
    return (
        b"\x89PNG\r\n\x1a\n"
        + (0).to_bytes(4, "big") + b"IHDR"
        + w.to_bytes(4, "big") + h.to_bytes(4, "big")
        + b"\x00" * 8
    )


# A valid, readable 64x64 PNG — the canonical "good image" bytes (kept by the
# dimension gate).  (A bare signature with NO IHDR is UNREADABLE and now DROPS —
# see W3/TD-4 — so the fakes must carry a real header.)
_PNG_BYTES = _png_header(64, 64)


# ---------------------------------------------------------------------------
# Image-fetch fakes (the injected binary egress door — never a real socket)
# ---------------------------------------------------------------------------


@dataclass
class _FakeBinaryFetch:
    """Structural stand-in for guarded_fetch.BinaryFetchResult."""

    url: str
    ok: bool = True
    content_bytes: bytes = b""
    mime: str = "image/png"
    content_type: str = "image/png"
    truncated: bool = False
    denied_reason: str | None = None


class _RecordingImageFetch:
    """An injected image_fetch_fn that RECORDS calls and returns a scripted
    result per call.  ``calls`` proves whether the door was reached at all."""

    def __init__(self, results: list[_FakeBinaryFetch] | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self._results = list(results or [])

    def __call__(self, url: str, purpose: str) -> _FakeBinaryFetch:
        self.calls.append((url, purpose))
        if self._results:
            return self._results.pop(0)
        # Default: a successful, readable PNG for this url.
        return _FakeBinaryFetch(url=url, ok=True, content_bytes=_PNG_BYTES)


class _ExplodingImageFetch:
    """An injected image_fetch_fn that RAISES if ever called — the no-fetch proof
    (any call is an AssertionError that fails the test)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def __call__(self, url: str, purpose: str) -> Any:
        self.calls.append((url, purpose))
        raise AssertionError("image_fetch_fn must NOT be called on this path")


# ---------------------------------------------------------------------------
# Off-site image-egress consent fakes (the injected coarse per-article gate)
# ---------------------------------------------------------------------------


class _RecordingConsent:
    """An injected image_consent_fn returning a fixed answer and recording the
    contexts it was handed (to assert the disclosed off-site host list)."""

    def __init__(self, approve: bool) -> None:
        self.approve = approve
        self.contexts: list[ImageEgressConsentContext] = []

    def __call__(self, context: ImageEgressConsentContext) -> bool:
        self.contexts.append(context)
        return self.approve


class _ExplodingConsent:
    """An injected image_consent_fn that RAISES if ever called — proves a path
    (same-site only, or dormant) never asks for off-site consent."""

    def __call__(self, context: ImageEgressConsentContext) -> bool:
        raise AssertionError("image_consent_fn must NOT be called on this path")


# ---------------------------------------------------------------------------
# Registry hygiene — the real default consent fn delegates to the global
# single-verifier registry; clear it around every test so no verifier leaks.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_image_consent_registry():
    clear_image_egress_verifier()
    yield
    clear_image_egress_verifier()


# ---------------------------------------------------------------------------
# Coordinator builder (images-aware — the sibling _make_coordinator predates
# the images_enabled / image_fetch_fn / image_consent_fn params, so build here)
# ---------------------------------------------------------------------------


def _make_image_coordinator(
    tmp_path: Path,
    *,
    images_enabled: bool = False,
    image_fetch_fn: Any = None,
    image_consent_fn: Any = None,
    pipeline: FakePipeline | None = None,
    transport: FakeTransportCall | None = None,
    cipher: FieldCipher | None = None,
    max_ingest_bytes: int = DEFAULT_INGEST_MAX_BYTES,
) -> tuple[IngestCoordinator, FakePipeline, FakeTransportCall, Path]:
    pipeline = pipeline or FakePipeline()
    transport = transport or FakeTransportCall()
    resolved_cipher = cipher if cipher is not None else _cipher()
    staging_dir = tmp_path / "staging"
    userdata_dir = tmp_path / "userdata"
    userdata_dir.mkdir(parents=True, exist_ok=True)
    coordinator = IngestCoordinator(
        transport_call=transport,
        cipher_provider=lambda: resolved_cipher,
        pipeline_loader=pipeline.loader,
        staging_dir_provider=lambda: staging_dir,
        max_ingest_bytes=max_ingest_bytes,
        userdata_dir=userdata_dir,
        images_enabled=images_enabled,
        image_fetch_fn=image_fetch_fn,
        image_consent_fn=image_consent_fn,
    )
    return coordinator, pipeline, transport, staging_dir


def _run(coro):
    return asyncio.run(coro)


def _ingest(coordinator: IngestCoordinator, arg: str, session: str = "sess-1") -> str:
    """Drive a PASTE-mode ingest through the full command path."""
    return _run(
        coordinator.handle_command(session, IngestCommand(verb="ingest", arg=arg))
    )


# The article host for same-site image fetches — matches the cdn.example image
# hosts in _BODY_WITH_IMAGES, so those images are same-site (no consent prompt).
_SAME_SITE_ARTICLE = "https://cdn.example/article"
# An article on a DIFFERENT host, so cdn.example images are off-site (consent-gated).
_OFFSITE_ARTICLE = "https://news.example/post"


def _finalize_url(
    coordinator: IngestCoordinator,
    clean: FakeCleanResult,
    *,
    article_url: str = _SAME_SITE_ARTICLE,
    session: str = "sess-1",
) -> str:
    """Drive the URL-mode stage+submit+preview tail directly (CD-1: only URL mode
    fetches images).  Faithful to the real ``_handle_url_ingest`` tail without the
    fetch+guest-parse machinery (not what these corridor tests cover)."""
    return _run(
        coordinator._finalize_clean(
            session, clean, source_type="url", source_ref=article_url
        )
    )


def _submit_payload(transport: FakeTransportCall) -> dict[str, Any]:
    assert len(transport.sent) == 1, "expected exactly one submitted frame"
    return _envelope(transport.sent[0])["payload"]


_BODY_WITH_IMAGES = (
    "An article with two pictures.\n\n"
    "![a turbo diagram](https://cdn.example/turbo.png)\n\n"
    "Some body text in between the figures here.\n\n"
    "![a chart of boost](https://cdn.example/chart.png)\n\n"
    "A closing paragraph of real signal."
)

# Images from TWO distinct off-site hosts (cdn.example x2 + ads.other x1) — for
# the distinct-host disclosure test.
_BODY_MIXED_HOSTS = (
    "intro\n\n"
    "![one](https://cdn.example/1.png)\n\n"
    "![two](https://cdn.example/2.png)\n\n"
    "![an ad](https://ads.other/track.png)\n\n"
    "tail"
)


# ---------------------------------------------------------------------------
# 1. DORMANT — the load-bearing test (paste path; images_enabled=False)
# ---------------------------------------------------------------------------


class TestImagesDormant:
    def test_dormant_never_fetches_and_strips_refs(self, tmp_path: Path) -> None:
        """images_enabled=False (the shipped default): the injected fetch fn is
        NEVER called, the staged/previewed stored_text carries NO remote URL and
        NO ![...](http...) ref (refs → [image: alt] placeholders), and the
        INGEST_SUBMIT frame carries NO images (images=()).  THE load-bearing
        dormant lock."""
        exploding = _ExplodingImageFetch()
        coordinator, _, transport, _ = _make_image_coordinator(
            tmp_path,
            images_enabled=False,
            image_fetch_fn=exploding,
            pipeline=FakePipeline(
                result=FakeCleanResult(text=_BODY_WITH_IMAGES, title="Two Figures")
            ),
        )
        reply = _ingest(coordinator, "pasted article with image refs")

        # (a) The door was NEVER reached — nothing left the box.
        assert exploding.calls == []

        # (b) The submitted frame carries the rewritten (stripped) stored_text.
        payload = _submit_payload(transport)
        assert "images" not in payload  # encode omits it when the manifest is empty

        # (c) The pending stored_text == the previewed body, with NO remote URL.
        pending = coordinator.pending_for("sess-1")
        assert pending is not None
        stored_text = pending.cleaned_text
        assert "https://" not in stored_text
        assert "http://" not in stored_text
        assert "cdn.example" not in stored_text
        assert "](http" not in stored_text
        assert "[image: a turbo diagram]" in stored_text
        assert "[image: a chart of boost]" in stored_text
        assert "https://" not in reply
        assert "[image: a turbo diagram]" in reply

    def test_default_construction_is_dormant(self, tmp_path: Path) -> None:
        """An IngestCoordinator built WITHOUT images_enabled defaults to False."""
        coordinator = IngestCoordinator(
            transport_call=FakeTransportCall(),
            cipher_provider=lambda: _cipher(),
            pipeline_loader=FakePipeline().loader,
            staging_dir_provider=lambda: tmp_path / "staging",
            userdata_dir=tmp_path / "userdata",
        )
        assert coordinator._images_enabled is False

    def test_dormant_content_sha_matches_stripped_stored_text(
        self, tmp_path: Path
    ) -> None:
        """The submit's content_sha256 is computed over the STORED (stripped)
        text, never the original http-bearing body."""
        import hashlib

        coordinator, _, transport, _ = _make_image_coordinator(
            tmp_path,
            images_enabled=False,
            image_fetch_fn=_ExplodingImageFetch(),
            pipeline=FakePipeline(result=FakeCleanResult(text=_BODY_WITH_IMAGES)),
        )
        _ingest(coordinator, "pasted article with image refs")
        payload = _submit_payload(transport)
        stored_text = coordinator.pending_for("sess-1").cleaned_text
        expected = hashlib.sha256(stored_text.encode("utf-8")).hexdigest()
        assert payload["content_sha256"] == expected


# ---------------------------------------------------------------------------
# 2. ENABLED + successful fetch (URL mode, same-site images)
# ---------------------------------------------------------------------------


class TestImagesEnabledSuccess:
    def test_each_ref_rewritten_staged_and_in_manifest(
        self, tmp_path: Path
    ) -> None:
        """images_enabled=True + URL mode + same-site PNG fetches: each
        ![alt](url) becomes ![alt](blarai-img://<id>), a per-image staging blob is
        written (and read_staged_image returns the bytes), and the submit frame's
        images manifest carries one record per image with the pinned keys."""
        cipher = _cipher()
        fetch = _RecordingImageFetch(
            results=[
                _FakeBinaryFetch(url="x", ok=True, content_bytes=_PNG_BYTES + b"a"),
                _FakeBinaryFetch(url="y", ok=True, content_bytes=_PNG_BYTES + b"b"),
            ]
        )
        coordinator, _, transport, staging_dir = _make_image_coordinator(
            tmp_path,
            images_enabled=True,
            image_fetch_fn=fetch,
            image_consent_fn=_ExplodingConsent(),  # same-site → consent never asked
            cipher=cipher,
        )
        _finalize_url(coordinator, FakeCleanResult(text=_BODY_WITH_IMAGES))

        # Both refs were fetched once, through the image-ingest purpose label.
        assert len(fetch.calls) == 2
        assert {url for url, _purpose in fetch.calls} == {
            "https://cdn.example/turbo.png",
            "https://cdn.example/chart.png",
        }
        assert {purpose for _url, purpose in fetch.calls} == {"uc003-image-ingest"}

        # The stored text now carries local blarai-img:// refs, no http URL.
        stored_text = coordinator.pending_for("sess-1").cleaned_text
        assert "https://" not in stored_text
        assert stored_text.count("](blarai-img://") == 2
        assert "[image:" not in stored_text  # nothing dropped to a placeholder

        # The submit manifest: one record per image, pinned keys, no bytes.
        payload = _submit_payload(transport)
        images = payload["images"]
        assert isinstance(images, list) and len(images) == 2
        doc_uuid = payload["doc_uuid"]
        for record in images:
            assert set(record) == {
                "image_id",
                "staging_path",
                "alt",
                "source_url",
                "mime",
            }
            assert record["mime"] == "image/png"
            assert record["source_url"].startswith("https://cdn.example/")
            staged = read_staged_image(
                record["image_id"], doc_uuid, cipher, staging_dir
            )
            assert staged in (_PNG_BYTES + b"a", _PNG_BYTES + b"b")
            assert f"blarai-img://{record['image_id']}" in stored_text

    def test_blarai_img_id_matches_staging_filename(self, tmp_path: Path) -> None:
        """The manifest staging_path is the canonical
        <doc_uuid>__<image_id>.bin and exists on disk."""
        coordinator, _, transport, staging_dir = _make_image_coordinator(
            tmp_path,
            images_enabled=True,
            image_fetch_fn=_RecordingImageFetch(),
        )
        _finalize_url(
            coordinator,
            FakeCleanResult(text="![one](https://cdn.example/one.png) and text"),
        )
        payload = _submit_payload(transport)
        record = payload["images"][0]
        expected_name = f"{payload['doc_uuid']}__{record['image_id']}.bin"
        assert record["staging_path"].endswith(expected_name)
        assert (staging_dir / expected_name).exists()


# ---------------------------------------------------------------------------
# 3. ENABLED + denied / empty / truncated / oversize / unreadable fetch
# ---------------------------------------------------------------------------


class TestImagesEnabledDropPaths:
    def _drives_to_placeholder(
        self, tmp_path: Path, result: _FakeBinaryFetch, alt: str
    ) -> tuple[str, dict[str, Any], Path]:
        fetch = _RecordingImageFetch(results=[result])
        coordinator, _, transport, staging_dir = _make_image_coordinator(
            tmp_path, images_enabled=True, image_fetch_fn=fetch
        )
        _finalize_url(
            coordinator,
            FakeCleanResult(
                text=f"![{alt}](https://cdn.example/img.png) body text"
            ),
        )
        assert len(fetch.calls) == 1  # the door WAS consulted (same-site)
        stored_text = coordinator.pending_for("sess-1").cleaned_text
        payload = _submit_payload(transport)
        return stored_text, payload, staging_dir

    def test_denied_fetch_becomes_placeholder_no_metadata_no_blob(
        self, tmp_path: Path
    ) -> None:
        """A fetch the door refuses (ok=False) drops the ref to a [image: alt]
        placeholder — no manifest record, no staging blob."""
        stored_text, payload, staging_dir = self._drives_to_placeholder(
            tmp_path,
            _FakeBinaryFetch(url="x", ok=False, denied_reason="policy: deny"),
            "denied pic",
        )
        assert "[image: denied pic]" in stored_text
        assert "https://" not in stored_text
        assert "blarai-img://" not in stored_text
        assert "images" not in payload
        assert list(staging_dir.glob("*__*.bin")) == []

    def test_empty_bytes_fetch_becomes_placeholder(self, tmp_path: Path) -> None:
        """An ok fetch with zero bytes is dropped (a 0-byte image is a smell)."""
        stored_text, _, staging_dir = self._drives_to_placeholder(
            tmp_path,
            _FakeBinaryFetch(url="x", ok=True, content_bytes=b""),
            "empty pic",
        )
        assert "[image: empty pic]" in stored_text
        assert list(staging_dir.glob("*__*.bin")) == []

    def test_truncated_fetch_becomes_placeholder(self, tmp_path: Path) -> None:
        """W2 / BED-4: an ok fetch flagged truncated=True (hit the per-image byte
        cap → incomplete bytes) is dropped, never stored."""
        stored_text, _, staging_dir = self._drives_to_placeholder(
            tmp_path,
            _FakeBinaryFetch(
                url="x", ok=True, content_bytes=_PNG_BYTES, truncated=True
            ),
            "cut-off pic",
        )
        assert "[image: cut-off pic]" in stored_text
        assert "blarai-img://" not in stored_text
        assert list(staging_dir.glob("*__*.bin")) == []

    def test_oversize_image_becomes_placeholder(self, tmp_path: Path) -> None:
        """W1 / BED-3: an ok fetch whose header declares dimensions over the
        decompression-bomb ceiling is dropped (no decode — header-only)."""
        stored_text, _, staging_dir = self._drives_to_placeholder(
            tmp_path,
            _FakeBinaryFetch(
                url="x", ok=True, content_bytes=_png_header(20000, 100)
            ),
            "bomb pic",
        )
        assert "[image: bomb pic]" in stored_text
        assert list(staging_dir.glob("*__*.bin")) == []

    def test_unreadable_header_image_becomes_placeholder(
        self, tmp_path: Path
    ) -> None:
        """W3 / TD-4: an ok fetch whose header cannot be read (no IHDR) is dropped
        — we cannot prove it is under the bomb ceiling, so fail-closed."""
        stored_text, _, staging_dir = self._drives_to_placeholder(
            tmp_path,
            _FakeBinaryFetch(
                url="x", ok=True, content_bytes=b"\x89PNG\r\n\x1a\n"  # no IHDR
            ),
            "unreadable pic",
        )
        assert "[image: unreadable pic]" in stored_text
        assert list(staging_dir.glob("*__*.bin")) == []


# ---------------------------------------------------------------------------
# 4. Caps — per-article count + total bytes (URL mode, same-site)
# ---------------------------------------------------------------------------


class TestImageCaps:
    def test_per_article_count_cap_truncates_tail_to_placeholders(
        self, tmp_path: Path
    ) -> None:
        """More than MAX_IMAGES_PER_ARTICLE refs: only the first N are fetched;
        the rest are never fetched and drop to placeholders."""
        n_refs = MAX_IMAGES_PER_ARTICLE + 3
        body = "intro\n\n" + "\n\n".join(
            f"![pic {i}](https://cdn.example/img{i}.png)" for i in range(n_refs)
        )
        fetch = _RecordingImageFetch()  # default: ok readable PNG for any url
        coordinator, _, transport, _ = _make_image_coordinator(
            tmp_path, images_enabled=True, image_fetch_fn=fetch
        )
        _finalize_url(coordinator, FakeCleanResult(text=body))

        assert len(fetch.calls) == MAX_IMAGES_PER_ARTICLE
        stored_text = coordinator.pending_for("sess-1").cleaned_text
        assert stored_text.count("](blarai-img://") == MAX_IMAGES_PER_ARTICLE
        assert stored_text.count("[image: pic ") == 3
        payload = _submit_payload(transport)
        assert len(payload["images"]) == MAX_IMAGES_PER_ARTICLE

    def test_total_byte_cap_drops_remaining_images(self, tmp_path: Path) -> None:
        """Once cumulative image bytes would exceed MAX_TOTAL_IMAGE_BYTES the
        remaining images are dropped to placeholders (count cap not hit)."""
        half_plus = (MAX_TOTAL_IMAGE_BYTES // 2) + 1
        big_a = _PNG_BYTES + b"a" * (half_plus - len(_PNG_BYTES))
        big_b = _PNG_BYTES + b"b" * (half_plus - len(_PNG_BYTES))
        body = (
            "intro\n\n"
            "![first big](https://cdn.example/a.png)\n\n"
            "![second big](https://cdn.example/b.png)\n\n"
            "tail"
        )
        fetch = _RecordingImageFetch(
            results=[
                _FakeBinaryFetch(url="a", ok=True, content_bytes=big_a),
                _FakeBinaryFetch(url="b", ok=True, content_bytes=big_b),
            ]
        )
        coordinator, _, transport, staging_dir = _make_image_coordinator(
            tmp_path,
            images_enabled=True,
            image_fetch_fn=fetch,
            max_ingest_bytes=DEFAULT_INGEST_MAX_BYTES,
        )
        _finalize_url(coordinator, FakeCleanResult(text=body))

        stored_text = coordinator.pending_for("sess-1").cleaned_text
        assert stored_text.count("](blarai-img://") == 1
        assert "[image: second big]" in stored_text
        payload = _submit_payload(transport)
        assert len(payload["images"]) == 1
        assert list(staging_dir.glob("*__*.bin")) == [
            staging_dir / f"{payload['doc_uuid']}__{payload['images'][0]['image_id']}.bin"
        ]


# ---------------------------------------------------------------------------
# 5. Edit path — blarai-img refs are preserved, never collapsed / re-fetched
# ---------------------------------------------------------------------------


class TestEditPathPreservesLocalRefs:
    def test_process_images_leaves_blarai_img_refs_unchanged(
        self, tmp_path: Path
    ) -> None:
        """A body already carrying ![alt](blarai-img://abc123) (no http refs)
        through _process_images is returned UNCHANGED — the ref is NOT collapsed
        to a placeholder and NOT re-fetched (regardless of source mode)."""
        exploding = _ExplodingImageFetch()
        coordinator, _, _, staging_dir = _make_image_coordinator(
            tmp_path,
            images_enabled=True,  # even ENABLED, a local ref is never re-fetched
            image_fetch_fn=exploding,
        )
        cipher = coordinator._cipher_provider()
        body = (
            "Edited body keeping a figure.\n\n"
            "![kept figure](blarai-img://abc123)\n\n"
            "and some trailing text."
        )
        stored_text, meta = _run(
            coordinator._process_images(
                body,
                doc_uuid="11111111-2222-3333-4444-555555555555",
                cipher=cipher,
                staging_dir=staging_dir,
                source_type="url",
                source_ref=_SAME_SITE_ARTICLE,
            )
        )
        assert stored_text == body  # byte-identical, unchanged
        assert meta == []
        assert exploding.calls == []  # no http ref → no fetch attempted
        assert not staging_dir.exists() or list(staging_dir.glob("*.bin")) == []

    def test_approve_with_edit_keeps_blarai_img_ref(self, tmp_path: Path) -> None:
        """Through the real approve_with_edit path an edited body with a
        surviving blarai-img:// ref is stored unchanged (not re-fetched)."""
        import hashlib

        from services.ui_gateway.tests.test_ingest_coordinator import (
            _echo_coordinator,
        )
        from shared.security.ingest_staging import read_staged

        coordinator, transport, calls, staging_dir, _ = _echo_coordinator(tmp_path)
        assert coordinator._images_enabled is False
        _ingest(coordinator, "the original article body to curate")
        coordinator.pending_for("sess-1")
        calls["text"].clear()
        edited = "Curated body.\n\n![kept](blarai-img://deadbeef)\n\ntail."
        transport._responses = [
            {"ok": True, "doc_uuid": "ignored", "state": "pending",
             "chunk_count": 0, "error_code": "", "message": ""},
            {"ok": True, "doc_uuid": "ignored", "state": "approved",
             "chunk_count": 1, "error_code": "", "message": ""},
        ]
        reply = _run(coordinator.approve_with_edit("sess-1", edited))

        resubmit = _envelope(transport.sent[1])["payload"]
        new_uuid = resubmit["doc_uuid"]
        assert resubmit["content_sha256"] == hashlib.sha256(
            edited.encode("utf-8")
        ).hexdigest()
        assert "images" not in resubmit
        staged = read_staged(new_uuid, _cipher(), staging_dir)
        assert "blarai-img://deadbeef" in staged
        assert staged == edited
        assert "Approved" in reply
        assert calls["text"] == [edited]


# ---------------------------------------------------------------------------
# 6. Preview / pending body == stored_text (rewritten, not original)
# ---------------------------------------------------------------------------


class TestPreviewMatchesStoredText:
    def test_enabled_preview_meta_is_rewritten_stored_text(
        self, tmp_path: Path
    ) -> None:
        """After an enabled URL ingest, preview_meta_for()['editable_body'] equals
        the rewritten stored text (blarai-img refs), not the original http refs."""
        coordinator, _, _, _ = _make_image_coordinator(
            tmp_path,
            images_enabled=True,
            image_fetch_fn=_RecordingImageFetch(),
        )
        _finalize_url(coordinator, FakeCleanResult(text=_BODY_WITH_IMAGES))
        meta = coordinator.preview_meta_for("sess-1")
        assert meta is not None
        editable = meta["editable_body"]
        assert editable == coordinator.pending_for("sess-1").cleaned_text
        assert editable.count("](blarai-img://") == 2
        assert "https://" not in editable
        assert "cdn.example" not in editable

    def test_dormant_preview_meta_has_no_remote_url(self, tmp_path: Path) -> None:
        coordinator, _, _, _ = _make_image_coordinator(
            tmp_path,
            images_enabled=False,
            image_fetch_fn=_ExplodingImageFetch(),
            pipeline=FakePipeline(result=FakeCleanResult(text=_BODY_WITH_IMAGES)),
        )
        _ingest(coordinator, "pasted article with image refs")
        meta = coordinator.preview_meta_for("sess-1")
        assert meta is not None
        assert "https://" not in meta["editable_body"]
        assert "[image: a turbo diagram]" in meta["editable_body"]


# ---------------------------------------------------------------------------
# 7. Dimension floor (#7) — sub-32px drops; at-floor kept (URL mode, same-site)
# ---------------------------------------------------------------------------


class TestImageDimensionFloor:
    def test_sub_min_image_dropped_to_placeholder(self, tmp_path: Path) -> None:
        """An ok fetch of a 16x16 PNG is below the MIN_IMAGE_DIMENSION_PX floor,
        so it drops to a [image: alt] placeholder — like a door refusal."""
        fetch = _RecordingImageFetch(
            results=[
                _FakeBinaryFetch(
                    url="x", ok=True, content_bytes=_png_header(16, 16),
                    mime="image/png",
                )
            ]
        )
        coordinator, _, transport, staging_dir = _make_image_coordinator(
            tmp_path, images_enabled=True, image_fetch_fn=fetch
        )
        _finalize_url(
            coordinator,
            FakeCleanResult(
                text="![tiny spacer](https://cdn.example/spacer.png) body text"
            ),
        )
        assert len(fetch.calls) == 1
        stored_text = coordinator.pending_for("sess-1").cleaned_text
        assert "[image: tiny spacer]" in stored_text
        assert "blarai-img://" not in stored_text
        payload = _submit_payload(transport)
        assert "images" not in payload
        assert list(staging_dir.glob("*__*.bin")) == []

    def test_at_floor_image_is_kept(self, tmp_path: Path) -> None:
        """A 32x32 PNG (exactly the floor) is kept — it stages + appears in the
        manifest (the floor is keep-at-or-above)."""
        fetch = _RecordingImageFetch(
            results=[
                _FakeBinaryFetch(
                    url="x", ok=True, content_bytes=_png_header(32, 32),
                    mime="image/png",
                )
            ]
        )
        coordinator, _, transport, _ = _make_image_coordinator(
            tmp_path, images_enabled=True, image_fetch_fn=fetch
        )
        _finalize_url(
            coordinator,
            FakeCleanResult(
                text="![real photo](https://cdn.example/photo.png) body text"
            ),
        )
        stored_text = coordinator.pending_for("sess-1").cleaned_text
        assert stored_text.count("](blarai-img://") == 1
        assert "[image:" not in stored_text
        payload = _submit_payload(transport)
        assert len(payload["images"]) == 1


# ---------------------------------------------------------------------------
# 8. CD-1 — paste/file ingests NEVER fetch remote images (offline ≠ egress)
# ---------------------------------------------------------------------------


class TestCD1PasteFileNoFetch:
    def test_paste_mode_never_fetches_even_when_enabled(
        self, tmp_path: Path
    ) -> None:
        """images_enabled=True but a PASTE ingest: the door is NEVER reached and
        every remote ref strips to a placeholder (CD-1 — offline content must not
        silently become a network egress)."""
        exploding = _ExplodingImageFetch()
        coordinator, _, transport, staging_dir = _make_image_coordinator(
            tmp_path,
            images_enabled=True,  # ENABLED — yet paste still never fetches
            image_fetch_fn=exploding,
            image_consent_fn=_ExplodingConsent(),
            pipeline=FakePipeline(result=FakeCleanResult(text=_BODY_WITH_IMAGES)),
        )
        _ingest(coordinator, "pasted article with image refs")

        assert exploding.calls == []  # no fetch
        stored_text = coordinator.pending_for("sess-1").cleaned_text
        assert "https://" not in stored_text
        assert "[image: a turbo diagram]" in stored_text
        assert "[image: a chart of boost]" in stored_text
        payload = _submit_payload(transport)
        assert "images" not in payload
        assert list(staging_dir.glob("*__*.bin")) == []

    def test_file_mode_never_fetches_even_when_enabled(
        self, tmp_path: Path
    ) -> None:
        """source_type='file' through _process_images: same CD-1 no-fetch posture
        as paste (only URL mode fetches)."""
        exploding = _ExplodingImageFetch()
        coordinator, _, _, staging_dir = _make_image_coordinator(
            tmp_path, images_enabled=True, image_fetch_fn=exploding
        )
        cipher = coordinator._cipher_provider()
        stored_text, meta = _run(
            coordinator._process_images(
                _BODY_WITH_IMAGES,
                doc_uuid="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                cipher=cipher,
                staging_dir=staging_dir,
                source_type="file",
                source_ref="/home/op/article.html",
            )
        )
        assert exploding.calls == []
        assert meta == []
        assert "https://" not in stored_text
        assert "[image: a turbo diagram]" in stored_text


# ---------------------------------------------------------------------------
# 9. CD-1 — coarse per-article OFF-SITE image-egress consent (fail-closed)
# ---------------------------------------------------------------------------


class TestOffSiteConsent:
    def test_same_site_images_need_no_consent(self, tmp_path: Path) -> None:
        """When every image host == the article host, the consent fn is NEVER
        consulted and the images are fetched under the existing /ingest consent."""
        coordinator, _, _, _ = _make_image_coordinator(
            tmp_path,
            images_enabled=True,
            image_fetch_fn=_RecordingImageFetch(),
            image_consent_fn=_ExplodingConsent(),  # raises if consulted
        )
        _finalize_url(
            coordinator,
            FakeCleanResult(text=_BODY_WITH_IMAGES),
            article_url=_SAME_SITE_ARTICLE,  # host == the cdn.example image host
        )
        stored_text = coordinator.pending_for("sess-1").cleaned_text
        assert stored_text.count("](blarai-img://") == 2  # both fetched, no prompt

    def test_offsite_with_consent_yes_is_fetched(self, tmp_path: Path) -> None:
        """Off-site images + the operator consents → fetched.  The consent context
        discloses the off-site host, not a URL/payload."""
        consent = _RecordingConsent(approve=True)
        coordinator, _, _, _ = _make_image_coordinator(
            tmp_path,
            images_enabled=True,
            image_fetch_fn=_RecordingImageFetch(),
            image_consent_fn=consent,
        )
        _finalize_url(
            coordinator,
            FakeCleanResult(text=_BODY_WITH_IMAGES),
            article_url=_OFFSITE_ARTICLE,  # news.example → cdn.example is off-site
        )
        stored_text = coordinator.pending_for("sess-1").cleaned_text
        assert stored_text.count("](blarai-img://") == 2  # consented → fetched
        # Consent asked exactly once (coarse per-article), disclosing only hosts.
        assert len(consent.contexts) == 1
        ctx = consent.contexts[0]
        assert ctx.article_host == "news.example"
        assert ctx.offsite_hosts == ("cdn.example",)
        assert "/" not in "".join(ctx.offsite_hosts)  # hosts, never URLs

    def test_offsite_with_consent_no_is_dropped(self, tmp_path: Path) -> None:
        """Off-site images + the operator declines → dropped to placeholders; the
        off-site door is NEVER reached."""
        exploding = _ExplodingImageFetch()
        coordinator, _, transport, staging_dir = _make_image_coordinator(
            tmp_path,
            images_enabled=True,
            image_fetch_fn=exploding,
            image_consent_fn=_RecordingConsent(approve=False),
        )
        _finalize_url(
            coordinator,
            FakeCleanResult(text=_BODY_WITH_IMAGES),
            article_url=_OFFSITE_ARTICLE,
        )
        assert exploding.calls == []  # off-site never fetched
        stored_text = coordinator.pending_for("sess-1").cleaned_text
        assert "[image: a turbo diagram]" in stored_text
        assert "blarai-img://" not in stored_text
        payload = _submit_payload(transport)
        assert "images" not in payload
        assert list(staging_dir.glob("*__*.bin")) == []

    def test_offsite_with_no_verifier_is_dropped_failclosed(
        self, tmp_path: Path
    ) -> None:
        """No image_consent_fn injected → the real default delegates to the global
        registry, which has NO verifier wired → DENY (fail-closed).  Off-site
        images drop; the door is never reached.  THE dormant-default lock."""
        exploding = _ExplodingImageFetch()
        coordinator, _, _, staging_dir = _make_image_coordinator(
            tmp_path,
            images_enabled=True,
            image_fetch_fn=exploding,
            # image_consent_fn omitted → _default_image_egress_consent (registry).
        )
        _finalize_url(
            coordinator,
            FakeCleanResult(text=_BODY_WITH_IMAGES),
            article_url=_OFFSITE_ARTICLE,
        )
        assert exploding.calls == []  # fail-closed: no verifier → no off-site fetch
        stored_text = coordinator.pending_for("sess-1").cleaned_text
        assert "[image: a turbo diagram]" in stored_text
        assert list(staging_dir.glob("*__*.bin")) == []

    def test_consent_error_fails_closed(self, tmp_path: Path) -> None:
        """A consent fn that RAISES is treated as a denial (off-site dropped)."""
        def _boom(context: ImageEgressConsentContext) -> bool:
            raise RuntimeError("surface wedged")

        exploding = _ExplodingImageFetch()
        coordinator, _, _, _ = _make_image_coordinator(
            tmp_path,
            images_enabled=True,
            image_fetch_fn=exploding,
            image_consent_fn=_boom,
        )
        _finalize_url(
            coordinator,
            FakeCleanResult(text=_BODY_WITH_IMAGES),
            article_url=_OFFSITE_ARTICLE,
        )
        assert exploding.calls == []  # the raise is a fail-closed deny
        stored_text = coordinator.pending_for("sess-1").cleaned_text
        assert "[image: a turbo diagram]" in stored_text

    def test_disclosure_list_is_distinct_hosts_only(self, tmp_path: Path) -> None:
        """The consent context discloses the DISTINCT off-site host list (deduped,
        sorted), never per-ref URLs — one coarse decision for the whole article."""
        consent = _RecordingConsent(approve=False)  # decline → nothing fetched
        coordinator, _, _, _ = _make_image_coordinator(
            tmp_path,
            images_enabled=True,
            image_fetch_fn=_ExplodingImageFetch(),
            image_consent_fn=consent,
        )
        _finalize_url(
            coordinator,
            FakeCleanResult(text=_BODY_MIXED_HOSTS),
            article_url=_OFFSITE_ARTICLE,
        )
        assert len(consent.contexts) == 1  # ONE decision for the whole article
        ctx = consent.contexts[0]
        # cdn.example appears twice + ads.other once → two DISTINCT hosts, sorted.
        assert ctx.offsite_hosts == ("ads.other", "cdn.example")

    def test_mixed_same_and_offsite_only_offsite_gated(
        self, tmp_path: Path
    ) -> None:
        """An article on cdn.example with one same-site (cdn.example) + one off-site
        (ads.other) image, off-site declined: the same-site image still fetches,
        only the off-site one drops."""
        body = (
            "intro\n\n"
            "![own figure](https://cdn.example/own.png)\n\n"
            "![third party](https://ads.other/track.png)\n\n"
            "tail"
        )
        consent = _RecordingConsent(approve=False)
        coordinator, _, _, _ = _make_image_coordinator(
            tmp_path,
            images_enabled=True,
            image_fetch_fn=_RecordingImageFetch(),
            image_consent_fn=consent,
        )
        _finalize_url(
            coordinator, FakeCleanResult(text=body), article_url=_SAME_SITE_ARTICLE
        )
        stored_text = coordinator.pending_for("sess-1").cleaned_text
        assert stored_text.count("](blarai-img://") == 1   # same-site kept
        assert "[image: third party]" in stored_text       # off-site dropped
        assert consent.contexts[0].offsite_hosts == ("ads.other",)


# ---------------------------------------------------------------------------
# 10. Dormancy preservation — the weld wins UPSTREAM of consent
# ---------------------------------------------------------------------------


class TestDormancyPreservation:
    def test_disabled_strips_even_with_consenting_verifier(
        self, tmp_path: Path
    ) -> None:
        """images_enabled=False + a consent fn that WOULD approve + off-site refs:
        still strip-no-fetch.  Proves the new consent seam creates NO path around
        the 4th weld lock — the lock short-circuits ahead of any consent."""
        exploding_fetch = _ExplodingImageFetch()
        exploding_consent = _ExplodingConsent()  # must not even be asked
        coordinator, _, _, staging_dir = _make_image_coordinator(
            tmp_path,
            images_enabled=False,  # the weld lock
            image_fetch_fn=exploding_fetch,
            image_consent_fn=exploding_consent,
        )
        cipher = coordinator._cipher_provider()
        stored_text, meta = _run(
            coordinator._process_images(
                _BODY_WITH_IMAGES,
                doc_uuid="ffffffff-ffff-ffff-ffff-ffffffffffff",
                cipher=cipher,
                staging_dir=staging_dir,
                source_type="url",
                source_ref=_OFFSITE_ARTICLE,  # off-site refs present
            )
        )
        assert exploding_fetch.calls == []          # never fetched
        assert meta == []
        assert "https://" not in stored_text
        assert "[image: a turbo diagram]" in stored_text  # stripped to placeholder
