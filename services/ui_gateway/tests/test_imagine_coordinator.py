"""
Regression locks for the gateway-side UC-010 image-generation surface (ADR-033).

The diffusion model is NEVER loaded — the AO transport is INJECTED as a fake
``transport_call`` ``(bytes) -> dict`` returning a canned IMAGE_GEN_RESULT (the
structural shape of ``MessageFramer.decode_image_gen_result``).  These tests lock:

  * command parsing (``/imagine`` / ``/edit`` / ``/save`` only; case-insensitive;
    not a prefix-of-a-word).
  * the HARD no-URL guard on the ``/edit`` seed (image generation = no egress).
  * the LOCAL-file ``/edit`` seed guards (UNC refusal, extension allowlist,
    containment) reused from the ingest coordinator.
  * the ``blarai-img://`` ``/edit`` seed + ``/save`` paths gated on a generated-
    image reader (refuse cleanly when absent / unknown).
  * dispatch surfaces the AO result verbatim (incl. the dormant
    IMAGE_GEN_UNAVAILABLE notice) — proving dormancy passes through unaltered.

Model-free; no AO; LOCALAPPDATA redirected by the root conftest; staging dirs
tmp_path-injected.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from services.ui_gateway.src.imagine_coordinator import (
    ImagineCommand,
    ImagineCoordinator,
    parse_imagine_command,
    is_blarai_img_ref,
)
from shared.security.field_cipher import FieldCipher, derive_subkeys

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x01\x02\x03" * 64


def _cipher() -> FieldCipher:
    return FieldCipher(derive_subkeys(b"\x07" * 32))


class FakeImagineTransport:
    """Captures encoded IMAGE_GEN_REQUEST frames; replies from a scripted list."""

    def __init__(self, responses: list[dict[str, Any]] | None = None) -> None:
        self.sent: list[bytes] = []
        self._responses = list(responses or [])

    async def __call__(self, message: bytes) -> dict[str, Any]:
        self.sent.append(message)
        if self._responses:
            return self._responses.pop(0)
        return {
            "ok": True, "image_ref": "blarai-img://" + "a" * 32,
            "mime": "image/png", "error_code": "",
            "message": "Image generated (blarai-img://%s)." % ("a" * 32),
        }


def _dormant_result() -> dict[str, Any]:
    return {
        "ok": False, "image_ref": "", "mime": "",
        "error_code": "IMAGE_GEN_UNAVAILABLE",
        "message": (
            "Image generation is unavailable (the capability is disabled or the "
            "model is not installed). No image was generated."
        ),
    }


def _make_coordinator(
    *,
    transport: FakeImagineTransport | None = None,
    cipher: FieldCipher | None = None,
    reader=None,
    lister=None,
    manager=None,
    userdata_dir: Path | None = None,
    staging_dir: Path | None = None,
) -> ImagineCoordinator:
    return ImagineCoordinator(
        transport_call=transport or FakeImagineTransport(),
        cipher_provider=(lambda: cipher) if cipher is not None else (lambda: None),
        generated_image_reader=reader,
        image_lister=lister,
        image_manager=manager,
        userdata_dir=userdata_dir,
        staging_dir_provider=(lambda: staging_dir) if staging_dir else None,
    )


# ---------------------------------------------------------------------------
# /illustrate + /cartoon flat-illustration styles (#703)
# ---------------------------------------------------------------------------


def test_parse_illustrate_and_cartoon_verbs():
    """/illustrate + /cartoon parse to their verbs (case-insensitive; a
    prefix-of-a-word is NOT a command; bare verb is allowed)."""
    assert parse_imagine_command("/illustrate a fox").verb == "illustrate"
    assert parse_imagine_command("/cartoon a fox").verb == "cartoon"
    assert parse_imagine_command("/CARTOON a fox").verb == "cartoon"
    assert parse_imagine_command("/illustrateX") is None
    assert parse_imagine_command("/illustrate").verb == "illustrate"


def test_illustrate_wraps_template_and_sends_illustration_style():
    """/illustrate wraps the subject in the flat-illustration template AND sends
    style=illustration on the IMAGE_GEN_REQUEST."""
    from shared.ipc.protocol import MessageFramer

    transport = FakeImagineTransport()
    coord = _make_coordinator(transport=transport)
    reply = asyncio.run(
        coord.handle_command("s1", parse_imagine_command("/illustrate a happy dog"))
    )
    assert "blarai-img://" in reply
    assert len(transport.sent) == 1
    _mt, _rid, payload = MessageFramer().decode(transport.sent[0])
    assert payload["style"] == MessageFramer.IMAGE_GEN_STYLE_ILLUSTRATION
    assert "a happy dog" in payload["prompt"]
    assert "vector illustration" in payload["prompt"]
    assert "flat design" in payload["prompt"]


def test_cartoon_sends_cartoon_style_with_template():
    """/cartoon wraps the SAME flat template but sends style=cartoon (the AO then
    applies the runtime LoRA)."""
    from shared.ipc.protocol import MessageFramer

    transport = FakeImagineTransport()
    coord = _make_coordinator(transport=transport)
    asyncio.run(
        coord.handle_command("s1", parse_imagine_command("/cartoon a robot"))
    )
    _mt, _rid, payload = MessageFramer().decode(transport.sent[0])
    assert payload["style"] == MessageFramer.IMAGE_GEN_STYLE_CARTOON
    assert "a robot" in payload["prompt"]
    assert "vector illustration" in payload["prompt"]


def test_imagine_stays_photoreal_with_verbatim_prompt():
    """/imagine is unchanged: style=photoreal and the prompt passes through
    VERBATIM (no flat template wrapped on)."""
    from shared.ipc.protocol import MessageFramer

    transport = FakeImagineTransport()
    coord = _make_coordinator(transport=transport)
    asyncio.run(
        coord.handle_command("s1", parse_imagine_command("/imagine a red car"))
    )
    _mt, _rid, payload = MessageFramer().decode(transport.sent[0])
    assert payload["style"] == MessageFramer.IMAGE_GEN_STYLE_PHOTOREAL
    assert payload["prompt"] == "a red car"


def test_illustrate_empty_prompt_is_usage_no_request():
    """Bare /illustrate (no subject) returns usage and sends NO request."""
    transport = FakeImagineTransport()
    coord = _make_coordinator(transport=transport)
    reply = asyncio.run(
        coord.handle_command("s1", parse_imagine_command("/illustrate"))
    )
    assert "Usage" in reply
    assert transport.sent == []


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_parse_basic():
    assert parse_imagine_command("/imagine a cat") == ImagineCommand("imagine", "a cat")
    assert parse_imagine_command("/edit foo.png blue") == ImagineCommand("edit", "foo.png blue")
    assert parse_imagine_command("/save abc /tmp/x.png") == ImagineCommand("save", "abc /tmp/x.png")
    assert parse_imagine_command("/IMAGINE Cat") == ImagineCommand("imagine", "Cat")


def test_parse_not_a_command():
    assert parse_imagine_command("/imaginethis") is None
    assert parse_imagine_command("just a sentence") is None
    assert parse_imagine_command("an /imagine inside text") is None


def test_parse_bare_verb():
    assert parse_imagine_command("/imagine") == ImagineCommand("imagine", "")


def test_blarai_img_ref_anchored():
    good = "a" * 32
    assert is_blarai_img_ref("blarai-img://" + good) == good
    assert is_blarai_img_ref("blarai-img://abc") is None
    assert is_blarai_img_ref("blarai-img://" + good + ")") is None
    assert is_blarai_img_ref("x blarai-img://" + good) is None


# ---------------------------------------------------------------------------
# /imagine
# ---------------------------------------------------------------------------


def test_imagine_dispatches_and_surfaces_ref():
    async def run():
        t = FakeImagineTransport()
        c = _make_coordinator(transport=t)
        reply = await c.handle_command("s1", ImagineCommand("imagine", "a red cube"))
        assert "blarai-img://" in reply
        assert len(t.sent) == 1  # one IMAGE_GEN_REQUEST sent
    asyncio.run(run())


def test_imagine_success_reply_leads_with_markdown_embed():
    """The success reply LEADS with ``![generated image](blarai-img://<id>)`` so
    the WinUI markdown renderer fires its inline-image path (UC-010 #666/#665 Pass
    B). The informational line + the /save hint must still follow (the TUI shows
    the embed as literal text and relies on /save). Locks the renderer-firing
    contract — a plain-text reply (the pre-Pass-B shape) would never render a pixel."""
    async def run():
        ref = "blarai-img://" + "a" * 32
        t = FakeImagineTransport()
        c = _make_coordinator(transport=t)
        reply = await c.handle_command("s1", ImagineCommand("imagine", "a red cube"))
        # The markdown image embed is present and references the exact ref the AO
        # returned (this is the ONLY syntax MarkdownBlock.BuildImageInline renders).
        assert f"![generated image]({ref})" in reply
        # And it LEADS the reply (renders as its own block, not buried in prose).
        assert reply.lstrip().startswith(f"![generated image]({ref})")
        # The informational text + /save hint still ride along (TUI fallback).
        assert "renders inline" in reply
        assert f"/save {ref}" in reply
    asyncio.run(run())


def test_imagine_dormant_surfaces_unavailable_verbatim():
    async def run():
        t = FakeImagineTransport([_dormant_result()])
        c = _make_coordinator(transport=t)
        reply = await c.handle_command("s1", ImagineCommand("imagine", "a cat"))
        assert "unavailable" in reply.lower()
    asyncio.run(run())


def test_imagine_empty_is_usage():
    async def run():
        c = _make_coordinator()
        reply = await c.handle_command("s1", ImagineCommand("imagine", ""))
        assert "Usage" in reply
    asyncio.run(run())


# ---------------------------------------------------------------------------
# /edit — HARD no-URL guard + local seed guards
# ---------------------------------------------------------------------------


def test_edit_url_seed_refused_before_transport():
    """A URL seed is refused LOUDLY and NO transport call is made (no egress)."""
    async def run():
        t = FakeImagineTransport()
        c = _make_coordinator(transport=t)
        reply = await c.handle_command(
            "s1", ImagineCommand("edit", "https://evil.example/x.png make it blue")
        )
        assert "never a URL" in reply
        assert t.sent == []  # nothing sent — refused before dispatch
    asyncio.run(run())


def test_edit_unc_seed_refused(tmp_path: Path):
    async def run():
        t = FakeImagineTransport()
        c = _make_coordinator(transport=t, cipher=_cipher())
        reply = await c.handle_command(
            "s1", ImagineCommand("edit", r"\\evilhost\share\x.png make it blue")
        )
        assert "UNC" in reply or "network" in reply.lower()
        assert t.sent == []
    asyncio.run(run())


def test_edit_bad_extension_refused(tmp_path: Path):
    async def run():
        (tmp_path / "doc.txt").write_text("not an image")
        t = FakeImagineTransport()
        c = _make_coordinator(transport=t, cipher=_cipher(), userdata_dir=tmp_path)
        reply = await c.handle_command("s1", ImagineCommand("edit", "doc.txt blue"))
        assert "unsupported seed image type" in reply.lower()
        assert t.sent == []
    asyncio.run(run())


def test_edit_missing_prompt_is_usage():
    async def run():
        c = _make_coordinator(cipher=_cipher())
        reply = await c.handle_command("s1", ImagineCommand("edit", "foo.png"))
        assert "Usage" in reply or "followed by a prompt" in reply
    asyncio.run(run())


def test_edit_local_file_stages_encrypted_and_dispatches(tmp_path: Path):
    """A LOCAL seed file is read, staged ENCRYPTED, and dispatched (no URL)."""
    async def run():
        seed = tmp_path / "seed.png"
        seed.write_bytes(_PNG)
        staging = tmp_path / "staging"
        cipher = _cipher()
        t = FakeImagineTransport()
        c = _make_coordinator(
            transport=t, cipher=cipher, userdata_dir=tmp_path, staging_dir=staging,
        )
        reply = await c.handle_command(
            "s1", ImagineCommand("edit", "seed.png make it blue")
        )
        # Dispatched once with mode=image2image + a staging ref.
        assert len(t.sent) == 1
        import json
        payload = json.loads(t.sent[0].decode("utf-8"))["payload"]
        assert payload["mode"] == "image2image"
        assert payload["staging_ref"]
        assert payload["staging_image_id"]
        assert "blarai-img://" in reply
        # The staged blob is the seed's CIPHERTEXT, never plaintext (and is
        # cleaned up after dispatch — a handoff, not a store).
        assert not list(staging.glob("*.bin")), "seed staging not cleaned up"
    asyncio.run(run())


def test_edit_no_cipher_refuses(tmp_path: Path):
    async def run():
        seed = tmp_path / "seed.png"
        seed.write_bytes(_PNG)
        t = FakeImagineTransport()
        c = _make_coordinator(transport=t, cipher=None, userdata_dir=tmp_path)
        reply = await c.handle_command(
            "s1", ImagineCommand("edit", "seed.png make it blue")
        )
        assert "staging cipher is unavailable" in reply.lower()
        assert t.sent == []
    asyncio.run(run())


def test_edit_staging_purged_on_ao_failure(tmp_path: Path):
    """No seed residue (even encrypted) survives a FAILED generate — the seed
    staging blob is deleted whether the AO returns ok=False or the transport
    raises. Locks the no-residue-on-error invariant (_handle_edit's finally),
    which the success-path test alone would not catch."""
    async def run():
        seed = tmp_path / "seed.png"
        seed.write_bytes(_PNG)

        # (a) AO returns an ok=False refusal — staging must still be purged.
        staging_a = tmp_path / "staging_a"
        c = _make_coordinator(
            transport=FakeImagineTransport([_dormant_result()]),
            cipher=_cipher(), userdata_dir=tmp_path, staging_dir=staging_a,
        )
        reply = await c.handle_command("s1", ImagineCommand("edit", "seed.png bluer"))
        assert "unavailable" in reply.lower()
        assert not list(staging_a.glob("*.bin")), "staging not purged on ok=False"

        # (b) The transport RAISES mid-dispatch — staging must STILL be purged.
        class _RaisingTransport:
            def __init__(self) -> None:
                self.sent: list[bytes] = []

            async def __call__(self, message: bytes) -> dict[str, Any]:
                self.sent.append(message)
                raise RuntimeError("transport boom")

        staging_b = tmp_path / "staging_b"
        c2 = _make_coordinator(
            transport=_RaisingTransport(),
            cipher=_cipher(), userdata_dir=tmp_path, staging_dir=staging_b,
        )
        try:
            await c2.handle_command("s1", ImagineCommand("edit", "seed.png bluer"))
        except RuntimeError:
            pass  # propagation is acceptable; the locked invariant is the purge
        assert not list(staging_b.glob("*.bin")), "staging not purged on transport raise"
    asyncio.run(run())


# ---------------------------------------------------------------------------
# /edit + /save with the blarai-img:// store reader
# ---------------------------------------------------------------------------


def test_edit_blarai_img_seed_without_reader_refuses():
    async def run():
        c = _make_coordinator(cipher=_cipher(), reader=None)
        reply = await c.handle_command(
            "s1", ImagineCommand("edit", "blarai-img://" + "a" * 32 + " make it blue")
        )
        assert "not available" in reply.lower()
    asyncio.run(run())


def test_edit_blarai_img_seed_with_reader_dispatches(tmp_path: Path):
    async def run():
        seen = {}

        def reader(image_id: str):
            seen["id"] = image_id
            return ("image/png", _PNG)

        t = FakeImagineTransport()
        c = _make_coordinator(
            transport=t, cipher=_cipher(), reader=reader,
            staging_dir=tmp_path / "staging",
        )
        iid = "b" * 32
        reply = await c.handle_command(
            "s1", ImagineCommand("edit", f"blarai-img://{iid} make it blue")
        )
        assert seen["id"] == iid
        assert len(t.sent) == 1
        assert "blarai-img://" in reply
    asyncio.run(run())


def test_save_writes_decrypted_png(tmp_path: Path):
    async def run():
        def reader(image_id: str):
            return ("image/png", _PNG)

        c = _make_coordinator(reader=reader)
        dest = tmp_path / "out.png"
        iid = "c" * 32
        reply = await c.handle_command("s1", ImagineCommand("save", f"{iid} {dest}"))
        assert dest.read_bytes() == _PNG
        assert "Saved" in reply
    asyncio.run(run())


def test_save_unknown_id_refuses(tmp_path: Path):
    async def run():
        c = _make_coordinator(reader=lambda _i: None)
        dest = tmp_path / "out.png"
        reply = await c.handle_command("s1", ImagineCommand("save", f"{'d'*32} {dest}"))
        assert "no stored image" in reply.lower()
        assert not dest.exists()
    asyncio.run(run())


def test_save_unc_dest_refused(tmp_path: Path):
    async def run():
        c = _make_coordinator(reader=lambda _i: ("image/png", _PNG))
        reply = await c.handle_command(
            "s1", ImagineCommand("save", f"{'e'*32} \\\\host\\share\\out.png")
        )
        assert "UNC" in reply or "network" in reply.lower()
    asyncio.run(run())


def test_save_bad_id_refused(tmp_path: Path):
    async def run():
        c = _make_coordinator(reader=lambda _i: ("image/png", _PNG))
        dest = tmp_path / "out.png"
        reply = await c.handle_command("s1", ImagineCommand("save", f"not-hex {dest}"))
        assert "32-character hex" in reply
    asyncio.run(run())


# ---------------------------------------------------------------------------
# /save with the GATEWAY-WIRED reader (UC-010/UC-003 WS3)
# ---------------------------------------------------------------------------
#
# The gateway now wires generated_image_reader=self._resolve_generated_image
# (the sync half of the IMAGE_RESOLVE corridor) into the ImagineCoordinator ctor.
# These reaffirm that a coordinator built the SAME way the gateway builds it (a
# reader that returns (mime, bytes) for a stored id) saves the decrypted PNG, and
# that /save still refuses a UNC destination even with the reader wired.


def test_save_with_wired_reader_writes_png(tmp_path: Path):
    """A coordinator built like the gateway (reader resolves the id to bytes)
    writes the decrypted PNG to a local path and replies success."""
    async def run():
        resolved_ids: list[str] = []

        def wired_reader(image_id: str):
            # Stands in for TransportGateway._resolve_generated_image: returns
            # (mime, bytes) for a stored id (here, any well-formed id).
            resolved_ids.append(image_id)
            return ("image/png", _PNG)

        c = _make_coordinator(reader=wired_reader)
        dest = tmp_path / "saved.png"
        iid = "f" * 32
        reply = await c.handle_command("s1", ImagineCommand("save", f"{iid} {dest}"))
        assert resolved_ids == [iid]  # the reader was driven with the parsed id
        assert dest.read_bytes() == _PNG
        assert "Saved" in reply
    asyncio.run(run())


def test_save_with_wired_reader_still_refuses_unc(tmp_path: Path):
    """Even with the reader wired, a UNC/network destination is refused (no
    image is written off-box) — reaffirms the air-gap posture on /save."""
    async def run():
        c = _make_coordinator(reader=lambda _i: ("image/png", _PNG))
        reply = await c.handle_command(
            "s1", ImagineCommand("save", f"{'f'*32} \\\\host\\share\\out.png")
        )
        assert "UNC" in reply or "network" in reply.lower()
    asyncio.run(run())


def test_save_with_wired_reader_unknown_id_refuses(tmp_path: Path):
    """When the wired reader returns None (unknown id / placeholder), /save
    refuses cleanly and writes nothing — the corridor's Fail-Closed shape."""
    async def run():
        c = _make_coordinator(reader=lambda _i: None)
        dest = tmp_path / "out.png"
        reply = await c.handle_command("s1", ImagineCommand("save", f"{'a'*32} {dest}"))
        assert "no stored image" in reply.lower()
        assert not dest.exists()
    asyncio.run(run())


# ---------------------------------------------------------------------------
# UC-010 Phase 1 (#667): /images command (list / delete) + /save marks saved
# ---------------------------------------------------------------------------


class FakeImageManager:
    """Records (action, image_id) calls; replies from a scripted result or a default."""

    def __init__(self, result: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self._result = result

    async def __call__(self, action: str, image_id: str) -> dict[str, Any]:
        self.calls.append((action, image_id))
        if self._result is not None:
            return dict(self._result, action=action, image_id=image_id)
        # Default: ok + found (the happy path).
        return {
            "ok": True, "action": action, "image_id": image_id, "found": True,
            "error_code": "", "message": "",
        }


def _lister(images: list[dict[str, Any]], total: int | None = None, truncated: bool = False):
    """Build an async image_lister returning a canned IMAGE_LIST_RESPONSE dict."""
    async def _call(_session_id):
        return {
            "images": images,
            "total": total if total is not None else len(images),
            "truncated": truncated,
        }
    return _call


def _meta(image_id: str, *, saved: bool = False, mime: str = "image/png",
          size: int = 2048, created: str = "2026-06-17T08:09:10+00:00") -> dict[str, Any]:
    return {
        "image_id": image_id, "session_id": "s1", "mime": mime,
        "byte_size": size, "saved": saved, "created_at": created,
    }


# ── parsing: /images is a recognised verb and never collides with /imagine ──


def test_parse_images_command():
    assert parse_imagine_command("/images") == ImagineCommand("images", "")
    assert parse_imagine_command("/images delete " + "a" * 32) == ImagineCommand(
        "images", "delete " + "a" * 32
    )
    assert parse_imagine_command("/IMAGES") == ImagineCommand("images", "")


def test_parse_images_vs_imagine_no_collision():
    """/imagine and /images are distinct verbs (the stems diverge at char 6)."""
    assert parse_imagine_command("/imagine a cat") == ImagineCommand("imagine", "a cat")
    assert parse_imagine_command("/imaginethis") is None  # not a word-boundary verb
    assert parse_imagine_command("/imagesfoo") is None    # /images is not a prefix here


# ── /images list ────────────────────────────────────────────────────────────


def test_images_list_renders_metadata_and_status():
    async def run():
        imgs = [_meta("a" * 32, saved=True), _meta("b" * 32, saved=False)]
        c = _make_coordinator(lister=_lister(imgs))
        reply = await c.handle_command("s1", ImagineCommand("images", ""))
        # Short ids (first 8) shown; full id NOT spelled out in the table cell.
        assert "aaaaaaaa" in reply
        assert "bbbbbbbb" in reply
        # SAVED / encrypted-only markers both present.
        assert "SAVED" in reply
        assert "encrypted-only" in reply
        # Usage hints for save + delete.
        assert "/save" in reply
        assert "/images delete" in reply
        # METADATA ONLY — no prompt text leaked (the lister never carries it).
        assert "prompt" not in reply.lower()
    asyncio.run(run())


def test_images_list_empty_case():
    async def run():
        c = _make_coordinator(lister=_lister([]))
        reply = await c.handle_command("s1", ImagineCommand("images", ""))
        assert "no generated images" in reply.lower()
        assert "/imagine" in reply
    asyncio.run(run())


def test_images_list_truncation_note():
    async def run():
        imgs = [_meta(f"{i:032x}") for i in range(3)]
        c = _make_coordinator(lister=_lister(imgs, total=250, truncated=True))
        reply = await c.handle_command("s1", ImagineCommand("images", ""))
        assert "of 250" in reply
    asyncio.run(run())


def test_images_list_no_lister_unavailable():
    async def run():
        c = _make_coordinator(lister=None)
        reply = await c.handle_command("s1", ImagineCommand("images", ""))
        assert "not available" in reply.lower()
    asyncio.run(run())


def test_images_list_transport_error_surfaced():
    async def run():
        async def _err(_s):
            return {"images": [], "total": 0, "truncated": False, "error": "boom"}
        c = _make_coordinator(lister=_err)
        reply = await c.handle_command("s1", ImagineCommand("images", ""))
        assert "could not list" in reply.lower()
    asyncio.run(run())


# ── /images delete (full-id confirm-of-intent) ───────────────────────────────


def test_images_delete_full_id_deletes():
    async def run():
        mgr = FakeImageManager()
        c = _make_coordinator(manager=mgr)
        iid = "a" * 32
        reply = await c.handle_command("s1", ImagineCommand("images", f"delete {iid}"))
        assert mgr.calls == [("delete", iid)]
        assert "deleted" in reply.lower()
        assert "securely wiped" in reply.lower()
        # The reply reassures that an already-/save'd file on disk is untouched.
        assert "untouched" in reply.lower()
    asyncio.run(run())


def test_images_delete_accepts_blarai_img_ref():
    async def run():
        mgr = FakeImageManager()
        c = _make_coordinator(manager=mgr)
        iid = "b" * 32
        reply = await c.handle_command(
            "s1", ImagineCommand("images", f"delete blarai-img://{iid}")
        )
        assert mgr.calls == [("delete", iid)]
        assert "deleted" in reply.lower()
    asyncio.run(run())


def test_images_delete_partial_id_refused_no_call():
    """A partial id is REFUSED before any manager call — the full id is the
    confirm-of-intent (no modal in the chat surface)."""
    async def run():
        mgr = FakeImageManager()
        c = _make_coordinator(manager=mgr)
        reply = await c.handle_command("s1", ImagineCommand("images", "delete abc123"))
        assert mgr.calls == []  # nothing deleted — refused at the gate
        assert "32-character" in reply
    asyncio.run(run())


def test_images_delete_forged_id_with_trailing_newline_refused():
    """A 32-hex id followed by a newline (an anchored-match forgery) is refused —
    is_blarai_img_ref / fullmatch are anchored, so the trailing char fails."""
    async def run():
        mgr = FakeImageManager()
        c = _make_coordinator(manager=mgr)
        # An arg with an embedded newline after a 32-hex id.
        reply = await c.handle_command(
            "s1", ImagineCommand("images", "delete " + "a" * 32 + "\nx")
        )
        assert mgr.calls == []
        assert "32-character" in reply or "not a full image id" in reply.lower()
    asyncio.run(run())


def test_images_delete_no_id_is_usage():
    async def run():
        mgr = FakeImageManager()
        c = _make_coordinator(manager=mgr)
        reply = await c.handle_command("s1", ImagineCommand("images", "delete"))
        assert mgr.calls == []
        assert "Usage" in reply or "required" in reply.lower()
    asyncio.run(run())


def test_images_delete_unknown_id_reports_not_found():
    async def run():
        mgr = FakeImageManager({"ok": True, "found": False})
        c = _make_coordinator(manager=mgr)
        iid = "c" * 32
        reply = await c.handle_command("s1", ImagineCommand("images", f"delete {iid}"))
        assert mgr.calls == [("delete", iid)]
        assert "no generated image found" in reply.lower()
    asyncio.run(run())


def test_images_delete_no_manager_unavailable():
    async def run():
        c = _make_coordinator(manager=None)
        reply = await c.handle_command("s1", ImagineCommand("images", f"delete {'a'*32}"))
        assert "not available" in reply.lower()
    asyncio.run(run())


def test_images_unknown_subcommand():
    async def run():
        c = _make_coordinator(lister=_lister([]), manager=FakeImageManager())
        reply = await c.handle_command("s1", ImagineCommand("images", "frobnicate"))
        assert "unknown" in reply.lower()
        assert "/images" in reply
    asyncio.run(run())


# ── /save marks the image saved (fail-soft) ──────────────────────────────────


def test_save_marks_image_saved(tmp_path: Path):
    """A successful /save fires a mark_saved management call for the image id."""
    async def run():
        mgr = FakeImageManager()
        c = _make_coordinator(reader=lambda _i: ("image/png", _PNG), manager=mgr)
        dest = tmp_path / "out.png"
        iid = "a" * 32
        reply = await c.handle_command("s1", ImagineCommand("save", f"{iid} {dest}"))
        assert dest.read_bytes() == _PNG
        assert "Saved" in reply
        assert mgr.calls == [("mark_saved", iid)]  # the save marked it
    asyncio.run(run())


def test_save_mark_failure_does_not_fail_save(tmp_path: Path):
    """A mark_saved failure (AO error OR a raising manager) must NOT fail the
    save — the PNG is already on disk; the flag is best-effort (#667 fail-soft)."""
    async def run():
        # (a) manager returns ok=False — save still succeeds.
        mgr = FakeImageManager({"ok": False, "found": False, "message": "AO down"})
        c = _make_coordinator(reader=lambda _i: ("image/png", _PNG), manager=mgr)
        dest = tmp_path / "a.png"
        reply = await c.handle_command("s1", ImagineCommand("save", f"{'a'*32} {dest}"))
        assert dest.read_bytes() == _PNG
        assert "Saved" in reply

        # (b) manager RAISES — save still succeeds (the exception is swallowed).
        class _Raising:
            async def __call__(self, action, image_id):
                raise RuntimeError("mark boom")

        c2 = _make_coordinator(reader=lambda _i: ("image/png", _PNG), manager=_Raising())
        dest2 = tmp_path / "b.png"
        reply2 = await c2.handle_command("s1", ImagineCommand("save", f"{'b'*32} {dest2}"))
        assert dest2.read_bytes() == _PNG
        assert "Saved" in reply2
    asyncio.run(run())


def test_save_without_manager_still_saves(tmp_path: Path):
    """With no manager wired, /save still writes the file (mark is skipped)."""
    async def run():
        c = _make_coordinator(reader=lambda _i: ("image/png", _PNG), manager=None)
        dest = tmp_path / "out.png"
        reply = await c.handle_command("s1", ImagineCommand("save", f"{'a'*32} {dest}"))
        assert dest.read_bytes() == _PNG
        assert "Saved" in reply
    asyncio.run(run())


def test_save_failure_does_not_mark(tmp_path: Path):
    """If the write FAILS, the image must NOT be marked saved (the file is not
    on disk) — mark only fires AFTER a successful write."""
    async def run():
        mgr = FakeImageManager()
        c = _make_coordinator(reader=lambda _i: ("image/png", _PNG), manager=mgr)
        # A UNC destination is refused before the write — no mark.
        reply = await c.handle_command(
            "s1", ImagineCommand("save", f"{'a'*32} \\\\host\\share\\out.png")
        )
        assert "UNC" in reply or "network" in reply.lower()
        assert mgr.calls == []  # nothing marked — the save never wrote a file
    asyncio.run(run())
