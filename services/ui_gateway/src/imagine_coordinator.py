"""
Imagine Coordinator — gateway-side UC-010 command surface (ADR-033)
====================================================================
The operator-facing half of local image generation: parse the explicit
``/imagine`` / ``/edit`` / ``/save`` chat commands, stage the (LOCAL) ``/edit``
seed image ENCRYPTED for the AO, drive the IMAGE_GEN_REQUEST IPC verb, and render
the informational reply that echoes into the chat transcript as a deterministic
turn (never model output, never PGOV-validated) — exactly the
:mod:`ingest_coordinator` pattern.

Commands (explicit by doctrine — generation is never inferred from
conversational text):

  ``/imagine <prompt>``  — text → image.  The prompt is the remainder of the
    message.  An empty prompt is a usage refusal.

  ``/edit <seed> <prompt>``  — image + text → image (img2img).  The *seed* is a
    LOCAL image, NEVER a URL:
      * a stored ``blarai-img://<id>`` reference (a prior generation / display
        image), OR
      * an absolute local file path, OR
      * a bare filename under userdata/ (containment-checked).
    A ``http(s)://`` seed is refused LOUDLY — image generation performs NO
    egress, ever (ADR-033 §H; mirrors the ``/ingest`` air-gap posture).  The
    file guards reuse ``ingest_coordinator`` (UNC/network refusal on the raw AND
    resolved form, an image extension allowlist, containment for bare names).

  ``/save <id> <path>``  — TUI display fallback (ADR-033 §D): write the decrypted
    PNG of ``blarai-img://<id>`` to a LOCAL path on EXPLICIT operator request
    (the WinUI renders ``blarai-img://`` inline via its markdown renderer +
    IMAGE_RESOLVE corridor — UC-010 #666/#665 Pass B; the TUI has no inline image
    surface, so ``/save`` is its escape hatch).  Refuses a UNC/network destination.

Security posture (Fail-Closed, ADR-033):
  * The ``/edit`` seed bytes cross to the AO ONLY via the encrypted
    ``image_staging`` blob under the shared DEK — never the 64 KB IPC frame,
    never a URL.  No cipher → loud refusal (no plaintext staging fallback).
  * The IMAGE_GEN_REQUEST frame carries metadata only (mode + prompt + caps +
    staging ref); the generated PNG returns as a ``blarai-img://<id>`` ref.
  * Generation is INJECTED (``transport_call``) so the coordinator is fully
    unit-testable with no AO, no real model, and no real DEK — a fake transport
    returns a canned IMAGE_GEN_RESULT; the real model is NEVER loaded in a test.
  * Dormant by default: the AO returns an ``IMAGE_GEN_UNAVAILABLE`` result when
    ``[image_generation].enabled=false`` (the shipped default), which this
    coordinator surfaces verbatim — no special-casing here.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid as _uuid_mod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from shared.ipc import MessageFramer
from shared.security.image_staging import (
    SEED_IMAGE_MAX_BYTES,
    delete_staged_image,
    write_staged_image,
)

# Reuse the proven ingest UNC DETECTION verbatim — same air-gap discipline,
# never re-implemented (the two coordinators cannot drift on what a UNC path
# is). The refusal MESSAGE is local (``_imagine_unc_refusal``) so it names
# image generation, not ``/ingest``.
from services.ui_gateway.src.ingest_coordinator import (
    _is_unc_path_str,
)

logger = logging.getLogger(__name__)


def _imagine_unc_refusal(path: Path) -> str:
    """UNC/network-path refusal for an /edit seed or /save destination.

    Image generation reads and writes only LOCAL files — no network egress
    (Fail-Closed). Command-neutral wording: the ingest helper's message names
    ``/ingest``, which would mislead an /edit or /save user.
    """
    return (
        f"Refused: '{path}' is a UNC/network path. Image generation reads and "
        "writes only LOCAL files (no network egress, Fail-Closed). Use a local "
        "path or a file under userdata/."
    )


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: /edit seed image extension allowlist (the raster formats the diffusion
#: pipeline + the renderer accept).  ``.svg`` is deliberately absent (it is a
#: scriptable document, not a raster image — the same posture as the egress
#: door's image allowlist).
IMAGINE_IMAGE_EXTENSIONS: frozenset[str] = frozenset(
    {".png", ".jpg", ".jpeg", ".webp"}
)

#: Per-seed-image PLAINTEXT byte cap for an /edit LOCAL-FILE seed.  Sized for a
#: GENERATED image (a /save'd 1536² hires PNG is ~3-4 MB), sourced from the same
#: staging seed cap — NOT the 2 MiB egress cap, since a seed is local, not
#: door-fetched (#666). A blarai-img:// store seed does not pass through here.
MAX_SEED_IMAGE_BYTES: int = SEED_IMAGE_MAX_BYTES

#: ``blarai-img://<id>`` reference; the id is a 32-char lowercase uuid4 hex,
#: anchored full-string (ADR-032 Am.1 lesson — never a prefix match).
_BLARAI_IMG_RE = re.compile(r"\Ablarai-img://([0-9a-f]{32})\Z")

#: A message that is SOLELY one URL (forbids the /edit URL-seed trap).
_URL_PREFIXES = ("http://", "https://")

_IMAGINE_USAGE: str = (
    "Usage: `/imagine <prompt>` (text → image), or "
    "`/edit <local-image|blarai-img://id> <prompt>` (image + text → image). "
    "The /edit seed is a LOCAL file or a stored blarai-img:// reference — never "
    "a URL (image generation performs no network egress)."
)

#: Flat-illustration prompt template (#703) — wraps the user's subject for both
#: /illustrate AND /cartoon. base SDXL renders clean flat-vector art from these
#: style words; /cartoon ALSO applies the flat-vector LoRA at runtime (AO-side)
#: for a softer cartoon look. Kept SHORT: the SDXL text encoders read only ~77
#: tokens, so the user's subject must stay in range (operator guide §2).
_ILLUSTRATION_TEMPLATE: str = (
    "vector illustration of {subject}, flat design, bold outlines, "
    "solid color background"
)

#: Usage for /illustrate + /cartoon (#703).
_STYLED_USAGE: str = (
    "Usage: `/illustrate <prompt>` (crisp flat-vector illustration) or "
    "`/cartoon <prompt>` (soft cartoon). Just describe the subject — the flat "
    "style is added for you."
)

#: Usage for the /images management surface (UC-010 Phase 1, #667).
_IMAGES_USAGE: str = (
    "Usage: `/images` (list your generated images) or "
    "`/images delete <id>` (remove one — the FULL 32-character id is required)."
)


# ---------------------------------------------------------------------------
# Transport contract (gateway → AO IMAGE_GEN_REQUEST → IMAGE_GEN_RESULT)
# ---------------------------------------------------------------------------

#: Sends one encoded IMAGE_GEN_REQUEST frame over a fresh AO connection and
#: returns the decoded IMAGE_GEN_RESULT payload dict.  Transport failures come
#: back as an ``ok=False`` dict, never an exception (Fail-Closed shape) — exactly
#: the ``ingest_coordinator.TransportCall`` contract.
TransportCall = Callable[[bytes], Awaitable[dict[str, Any]]]
#: Returns the shared-DEK FieldCipher, or None when unavailable.
CipherProvider = Callable[[], Any | None]
#: Reads + decrypts a stored generated image by id → (mime, bytes), or None.
#: Injected so /save + the blarai-img:// /edit seed are testable without a bank.
GeneratedImageReader = Callable[[str], "tuple[str, bytes] | None"]
#: Lists generated-image METADATA (UC-010 Phase 1) → the decoded
#: IMAGE_LIST_RESPONSE dict ``{images, total, truncated[, error]}``.  Async (it
#: crosses the AO leg).  Injected so /images is testable without a bank/AO.
ImageLister = Callable[["str | None"], Awaitable[dict[str, Any]]]
#: Performs a metadata-only management action (UC-010 Phase 1):
#: ``(action, image_id) -> IMAGE_MANAGE_RESULT dict``.  ``action`` is
#: ``'delete'`` | ``'mark_saved'``.  Async; Fail-Closed (an ``ok=False`` dict on
#: any failure, never raises).  Injected so /images delete + the post-/save
#: mark-saved are testable without a bank/AO.
ImageManager = Callable[[str, str], Awaitable[dict[str, Any]]]


# ---------------------------------------------------------------------------
# Command parsing
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ImagineCommand:
    """A parsed image-generation-surface command."""

    verb: str
    """``'imagine'`` | ``'illustrate'`` | ``'cartoon'`` | ``'edit'`` | ``'save'``
    | ``'images'``. illustrate/cartoon are the #703 flat-illustration styles."""

    arg: str
    """Remainder of the message after the verb (stripped; '' when absent)."""


#: The command verbs this coordinator owns.  ``images`` (UC-010 Phase 1, #667)
#: is the management surface (list / delete).  ``images`` is listed BEFORE
#: ``imagine`` so the longer-stem match is tried first — though the two never
#: collide (``/imagine`` and ``/images`` diverge at char 6: ``…ine`` vs ``…es``,
#: so neither is a prefix of the other; locked by test_parse_images_vs_imagine).
_IMAGINE_VERBS: tuple[str, ...] = (
    "images", "imagine", "illustrate", "cartoon", "edit", "save",
)


def parse_imagine_command(text: str) -> ImagineCommand | None:
    """Parse ``/imagine`` / ``/edit`` / ``/save`` / ``/images`` from a chat message.

    Case-insensitive on the verb; the verb must be followed by end-of-string or
    whitespace (``/imaginethis`` is NOT a command and flows to the model
    untouched).  Returns None for anything that is not one of the four commands.
    """
    stripped = text.strip()
    lower = stripped.lower()
    for verb in _IMAGINE_VERBS:
        cmd = "/" + verb
        if lower == cmd:
            return ImagineCommand(verb=verb, arg="")
        if lower.startswith(cmd) and len(stripped) > len(cmd) and stripped[len(cmd)].isspace():
            return ImagineCommand(verb=verb, arg=stripped[len(cmd):].strip())
    return None


def is_blarai_img_ref(token: str) -> str | None:
    """Return the 32-hex image id if *token* is a full ``blarai-img://<id>`` ref,
    else None (anchored full-string — never a prefix match)."""
    m = _BLARAI_IMG_RE.match(token.strip())
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Coordinator
# ---------------------------------------------------------------------------


class ImagineCoordinator:
    """Drives the /imagine, /edit, /save flow for the gateway (UC-010, ADR-033).

    All collaborators are injected so the coordinator is fully unit-testable with
    no AO, no real model, and no real DEK:

    Args:
        transport_call: Async callable sending one encoded IMAGE_GEN_REQUEST over
            a fresh AO connection, returning the decoded IMAGE_GEN_RESULT payload.
        cipher_provider: Returns the shared-DEK ``FieldCipher`` (the session
            store's — ADR-025 one-DEK rule) or None when unavailable.  Required
            to stage an /edit seed image (no cipher → loud refusal).
        generated_image_reader: Reads a stored ``blarai-img://<id>`` to
            ``(mime, bytes)`` or None — used by ``/save`` and the
            ``blarai-img://`` /edit seed.  Defaults to None (those paths then
            refuse cleanly until the gateway wires the bank reader).
        image_lister: Async lister of generated-image METADATA (UC-010 Phase 1)
            → the IMAGE_LIST_RESPONSE dict.  Used by ``/images``.  Defaults to
            None (``/images`` then reports the surface is unavailable).
        image_manager: Async ``(action, image_id) -> IMAGE_MANAGE_RESULT dict``
            for ``delete`` / ``mark_saved`` (UC-010 Phase 1).  Used by ``/images
            delete`` and the post-``/save`` mark-saved.  Defaults to None
            (``/images delete`` then reports the surface is unavailable; the
            post-save mark is silently skipped — it is best-effort).
        staging_dir_provider: Returns the encrypted-staging directory.  Defaults
            to the canonical image-staging dir.
        userdata_dir: /edit FILE-mode root for bare filenames.  Defaults to the
            document_loader's USERDATA_DIR.
        max_width/max_height/steps: Caps forwarded to the AO (which clamps again
            — defence in depth).
    """

    def __init__(
        self,
        *,
        transport_call: TransportCall,
        cipher_provider: CipherProvider,
        generated_image_reader: GeneratedImageReader | None = None,
        image_lister: ImageLister | None = None,
        image_manager: ImageManager | None = None,
        staging_dir_provider: Callable[[], Path] | None = None,
        userdata_dir: Path | None = None,
        max_width: int = 1024,
        max_height: int = 1024,
        steps: int = 0,
    ) -> None:
        self._transport_call = transport_call
        self._cipher_provider = cipher_provider
        self._generated_image_reader = generated_image_reader
        self._image_lister = image_lister
        self._image_manager = image_manager
        self._staging_dir_provider = staging_dir_provider
        self._userdata_dir = userdata_dir
        self._max_width = int(max_width)
        self._max_height = int(max_height)
        self._steps = int(steps)
        self._framer = MessageFramer()
        # One-shot per-session id of the LAST successfully generated image (#712),
        # popped by the gateway to attach Edit/Save follow-up buttons to that reply.
        self._last_image_id: dict[str, str] = {}

    # ── Entry point ───────────────────────────────────────────────────────

    async def handle_command(self, session_id: str, command: ImagineCommand) -> str:
        """Execute one parsed command and return the informational reply text.

        Never raises for operator-shaped failures — every refusal and every AO
        error comes back as a clear message for the transcript (Fail-Closed:
        anything unexpected is also caught and surfaced rather than crashing).
        """
        try:
            if command.verb == "imagine":
                return await self._handle_imagine(session_id, command.arg)
            if command.verb == "illustrate":
                return await self._handle_styled(
                    session_id, command.arg,
                    MessageFramer.IMAGE_GEN_STYLE_ILLUSTRATION,
                )
            if command.verb == "cartoon":
                return await self._handle_styled(
                    session_id, command.arg,
                    MessageFramer.IMAGE_GEN_STYLE_CARTOON,
                )
            if command.verb == "edit":
                return await self._handle_edit(session_id, command.arg)
            if command.verb == "images":
                return await self._handle_images(session_id, command.arg)
            return await self._handle_save(command.arg)
        except Exception as exc:  # noqa: BLE001 — surface, never crash the turn
            logger.error(
                "Imagine command %r failed for session=%s: %s",
                command.verb, session_id, exc, exc_info=True,
            )
            return f"Image command failed (Fail-Closed): {exc}"

    def pop_image_action_meta(self, session_id: str) -> dict[str, str] | None:
        """Pop the last successful generation's id for *session_id* (one-shot, #712).

        Returns ``{"image_id": "<32hex>"}`` exactly once after an imagine / edit /
        illustrate / cartoon that produced an image, so the gateway can attach the
        Edit/Save follow-up buttons to that reply frame; ``None`` otherwise (a
        refusal, a ``/save``, a ``/images`` listing — none carry a NEW image)."""
        image_id = self._last_image_id.pop(session_id, None)
        return {"image_id": image_id} if image_id else None

    # ── /imagine ────────────────────────────────────────────────────────────

    async def _handle_imagine(self, session_id: str, arg: str) -> str:
        prompt = arg.strip()
        if not prompt:
            return _IMAGINE_USAGE
        return await self._dispatch_generate(
            session_id, mode="text2image", prompt=prompt,
            style=MessageFramer.IMAGE_GEN_STYLE_PHOTOREAL,
        )

    # ── /illustrate + /cartoon (#703) ─────────────────────────────────────────

    async def _handle_styled(
        self, session_id: str, arg: str, style: str
    ) -> str:
        """/illustrate (flat-vector) + /cartoon (cartoon): base SDXL + the flat
        prompt template; cartoon ALSO applies the runtime LoRA AO-side (#703).

        Both are text→image only (no seed). The user types only the subject; the
        flat-illustration style words are wrapped on here so base SDXL renders
        clean flat-vector art, and the ``style`` flag tells the AO which model +
        (cartoon) runtime adapter to load."""
        subject = arg.strip()
        if not subject:
            return _STYLED_USAGE
        prompt = _ILLUSTRATION_TEMPLATE.format(subject=subject)
        return await self._dispatch_generate(
            session_id, mode="text2image", prompt=prompt, style=style,
        )

    # ── /edit ─────────────────────────────────────────────────────────────

    async def _handle_edit(self, session_id: str, arg: str) -> str:
        """``/edit <seed> <prompt>`` — img2img from a LOCAL seed (never a URL)."""
        if not arg.strip():
            return _IMAGINE_USAGE
        # First whitespace-delimited token is the seed; the remainder is the
        # prompt.  A seed with no following prompt is a usage refusal.
        parts = arg.strip().split(None, 1)
        seed_token = parts[0]
        prompt = parts[1].strip() if len(parts) > 1 else ""
        if not prompt:
            return (
                "Usage: `/edit <local-image|blarai-img://id> <prompt>` — the "
                "seed image must be followed by a prompt describing the edit."
            )

        # HARD no-URL guard (ADR-033 §H): the /edit seed is never a network
        # fetch.  Checked BEFORE any path/ref handling so a URL can never slip
        # through.
        if seed_token.lower().startswith(_URL_PREFIXES):
            return (
                "Edit refused: the seed image must be a LOCAL file or a stored "
                "blarai-img:// reference — never a URL. Image generation performs "
                "no network egress (Fail-Closed)."
            )

        # Resolve the seed to raw bytes (blarai-img:// ref OR local file).
        seed = await self._resolve_seed(seed_token)
        if isinstance(seed, str):
            return seed  # a loud refusal message
        seed_bytes, _seed_label = seed

        # Stage the seed ENCRYPTED for the AO (never the 64 KB frame, never plaintext).
        cipher = self._cipher_provider()
        if cipher is None:
            return (
                "Edit refused: the encrypted staging cipher is unavailable (no "
                "shared-DEK session store in this process) — the seed image is "
                "never staged in plaintext (Fail-Closed)."
            )
        staging_dir = self._resolve_staging_dir()
        transport_doc_uuid = str(_uuid_mod.uuid4())
        image_id = _uuid_mod.uuid4().hex
        try:
            staging_path = await asyncio.to_thread(
                write_staged_image,
                seed_bytes, image_id, transport_doc_uuid, cipher, staging_dir,
            )
        except Exception as exc:  # noqa: BLE001 — staging failure refuses
            logger.error("Edit seed staging failed: %s", exc)
            return f"Edit refused: could not stage the seed image (Fail-Closed): {exc}"

        try:
            return await self._dispatch_generate(
                session_id,
                mode="image2image",
                prompt=prompt,
                staging_ref=str(staging_path),
                staging_image_id=image_id,
            )
        finally:
            # The AO read the blob (or the request failed); either way the seed
            # staging file is a handoff, not a store — drop it (fail-safe).
            delete_staged_image(image_id, transport_doc_uuid, staging_dir)

    async def _resolve_seed(self, token: str) -> tuple[bytes, str] | str:
        """Resolve an /edit seed token to ``(bytes, label)`` or a refusal string.

        Order: a full ``blarai-img://<id>`` ref (read from the store) → an
        absolute local file → a bare filename under userdata/.  Every file guard
        is the ingest air-gap + containment discipline (reused verbatim).
        """
        image_id = is_blarai_img_ref(token)
        if image_id is not None:
            reader = self._generated_image_reader
            if reader is None:
                return (
                    "Edit refused: stored-image seeds are not available in this "
                    "process (no image store wired)."
                )
            try:
                got = await asyncio.to_thread(reader, image_id)
            except Exception as exc:  # noqa: BLE001 — Fail-Closed
                logger.error("Edit seed read failed for %s: %s", image_id, exc)
                return f"Edit refused: could not read the stored image: {exc}"
            if got is None:
                return (
                    f"Edit refused: no stored image found for "
                    f"blarai-img://{image_id} (it may have been discarded)."
                )
            _mime, data = got
            return data, f"blarai-img://{image_id}"
        # A bare ``blarai-img://`` that did NOT match the strict id shape is a
        # malformed ref — refuse rather than treating it as a file path.
        if token.lower().startswith("blarai-img://"):
            return (
                "Edit refused: malformed blarai-img:// reference (the id must be "
                "a 32-character hex string)."
            )
        return await self._read_seed_file(token)

    async def _read_seed_file(self, token: str) -> tuple[bytes, str] | str:
        """Read a LOCAL seed image file with the ingest air-gap + containment guards."""
        # Absolute path the operator gave → FILE mode (no containment).
        try:
            cand = Path(token)
            is_absolute = cand.is_absolute()
        except (OSError, ValueError):
            is_absolute = False
        if is_absolute:
            return await self._read_image_file(cand, containment_root=None)
        # Bare filename → FILE mode under userdata/.
        if not any(ch.isspace() for ch in token):
            userdata = self._resolve_userdata_dir()
            return await self._read_image_file(
                userdata / token, containment_root=userdata
            )
        return (
            "Edit refused: the seed must be a single local file path, a bare "
            "filename in userdata/, or a blarai-img:// reference."
        )

    async def _read_image_file(
        self, candidate: Path, *, containment_root: Path | None
    ) -> tuple[bytes, str] | str:
        """FILE-mode binary read with the ingest air-gap + containment guards."""
        # Air-gap guard on the RAW string BEFORE any filesystem touch.
        if _is_unc_path_str(str(candidate)):
            return _imagine_unc_refusal(candidate)
        suffix = candidate.suffix.lower()
        if suffix not in IMAGINE_IMAGE_EXTENSIONS:
            allowed = ", ".join(sorted(IMAGINE_IMAGE_EXTENSIONS))
            return (
                f"Edit refused: unsupported seed image type "
                f"'{suffix or '(none)'}'. /edit accepts {allowed} files."
            )
        try:
            resolved = candidate.resolve()
        except (OSError, ValueError) as exc:
            return f"Edit refused: cannot resolve path '{candidate}': {exc}"
        # Re-check the RESOLVED form (a local symlink must not smuggle a share).
        if _is_unc_path_str(str(resolved)):
            return _imagine_unc_refusal(resolved)
        if containment_root is not None:
            try:
                resolved.relative_to(containment_root.resolve())
            except ValueError:
                return (
                    f"Edit refused: '{candidate.name}' resolves outside "
                    "userdata/ (path containment, Fail-Closed)."
                )
        if not resolved.exists() or not resolved.is_file():
            return (
                f"Edit refused: seed image not found: '{resolved}'. Place it in "
                "userdata/ or give an absolute path."
            )
        size = resolved.stat().st_size
        if size > MAX_SEED_IMAGE_BYTES:
            return (
                f"Edit refused: '{resolved.name}' is {size:,} bytes, exceeding "
                f"the {MAX_SEED_IMAGE_BYTES:,}-byte seed-image cap (Fail-Closed)."
            )
        try:
            data = await asyncio.to_thread(resolved.read_bytes)
        except OSError as exc:
            return f"Edit refused: cannot read '{resolved.name}': {exc}"
        if not data:
            return f"Edit refused: '{resolved.name}' is empty."
        return data, str(resolved)

    # ── /save (TUI display fallback) ──────────────────────────────────────

    async def _handle_save(self, arg: str) -> str:
        """``/save <id> <path>`` — write a decrypted PNG to a LOCAL path (ADR-033 §D).

        TUI escape hatch (the WinUI renders blarai-img:// inline via its markdown
        renderer + the IMAGE_RESOLVE corridor — UC-010 #666/#665 Pass B).  Refuses
        a UNC/network destination; writes only on explicit operator request.
        ``<id>`` may be a bare 32-hex id or a full ``blarai-img://<id>`` ref.
        """
        parts = arg.strip().split(None, 1)
        if len(parts) < 2 or not parts[1].strip():
            return "Usage: `/save <id> <path>` — save a generated image to a local file."
        id_token, dest = parts[0], parts[1].strip()
        image_id = is_blarai_img_ref(id_token) or (
            id_token if re.fullmatch(r"[0-9a-f]{32}", id_token) else None
        )
        if image_id is None:
            return (
                "Save refused: the id must be a 32-character hex image id (or a "
                "blarai-img://<id> reference)."
            )
        reader = self._generated_image_reader
        if reader is None:
            return "Save refused: the image store is not available in this process."
        if _is_unc_path_str(dest):
            return _imagine_unc_refusal(Path(dest))
        try:
            got = await asyncio.to_thread(reader, image_id)
        except Exception as exc:  # noqa: BLE001 — Fail-Closed
            logger.error("Save read failed for %s: %s", image_id, exc)
            return f"Save failed: could not read the image (Fail-Closed): {exc}"
        if got is None:
            return f"Save refused: no stored image found for id {image_id}."
        _mime, data = got
        try:
            dest_path = Path(dest)
            if _is_unc_path_str(str(dest_path.resolve())):
                return _imagine_unc_refusal(dest_path)
            await asyncio.to_thread(dest_path.write_bytes, data)
        except OSError as exc:
            return f"Save failed: could not write '{dest}': {exc}"
        # Mark the image saved (UC-010 Phase 1, #667) — FAIL-SOFT: the file is
        # already on disk, so a mark failure must NEVER fail the save.  This is
        # the operator's own forward-looking exported-once record; if the AO is
        # unreachable or returns an error, log + continue with the success reply.
        await self._mark_saved_best_effort(image_id)
        return f"Saved blarai-img://{image_id} to {dest} ({len(data):,} bytes)."

    async def _mark_saved_best_effort(self, image_id: str) -> None:
        """Flag *image_id* as exported-to-disk after a successful /save (fail-soft).

        A mark failure (no manager wired, AO unreachable, store error) is logged
        and SWALLOWED — the PNG is already written, and the ``saved`` flag is a
        convenience record, never load-bearing for the save itself (#667).
        """
        if self._image_manager is None:
            return
        try:
            result = await self._image_manager("mark_saved", image_id)
            if not result.get("ok", False):
                logger.warning(
                    "Post-save mark-saved did not take for %s: %s",
                    image_id, result.get("message", "") or result.get("error_code", ""),
                )
        except Exception as exc:  # noqa: BLE001 — fail-soft: never undo a save
            logger.warning("Post-save mark-saved raised for %s: %s", image_id, exc)

    # ── /images (management: list / delete) — UC-010 Phase 1, #667 ──────────

    async def _handle_images(self, session_id: str, arg: str) -> str:
        """``/images`` — list generated images; ``/images delete <id>`` — remove one.

        Deterministic informational reply (no model, no PGOV — the
        ingest/imagine pattern).  ``/images`` with no arg lists ACROSS ALL
        sessions (the operator manages their whole gallery from chat, not just
        the current session).  ``/images delete <id>`` requires the FULL 32-hex
        id as the confirm-of-intent — there is no modal in the chat surface, so a
        partial / forged id is refused rather than risking the wrong image.
        """
        parts = arg.strip().split(None, 1)
        sub = parts[0].lower() if parts and parts[0] else ""

        if not sub:
            return await self._images_list()
        if sub == "delete":
            target = parts[1].strip() if len(parts) > 1 else ""
            return await self._images_delete(target)
        return (
            f"Unknown /images subcommand '{parts[0]}'.\n\n{_IMAGES_USAGE}"
        )

    async def _images_list(self) -> str:
        """Render the generated-image listing (newest first) for the transcript."""
        if self._image_lister is None:
            return "Image listing is not available in this process."
        try:
            result = await self._image_lister(None)
        except Exception as exc:  # noqa: BLE001 — Fail-Closed, surfaced as a message
            logger.error("Image list failed: %s", exc)
            return f"Could not list images (Fail-Closed): {exc}"
        if result.get("error"):
            return f"Could not list images: {result['error']}"
        images = result.get("images", []) or []
        total = int(result.get("total", len(images)))
        truncated = bool(result.get("truncated", False))
        if not images:
            return (
                "No generated images yet. Create one with `/imagine <prompt>` "
                "(text → image) or `/edit <local-image|blarai-img://id> <prompt>`."
            )
        return self._format_image_list(images, total, truncated)

    def _format_image_list(
        self, images: list[dict[str, Any]], total: int, truncated: bool
    ) -> str:
        """Format a metadata listing as a compact markdown table + usage hint.

        Each row shows: the SHORT id (first 8 hex + an ellipsis — enough to read,
        with the full-id requirement called out for delete), the created date
        (date portion of the ISO timestamp), a human size, the mime, and a
        SAVED / ENCRYPTED-ONLY marker.  METADATA ONLY — no prompt text, no pixels.
        """
        header = (
            f"**Generated images** ({len(images)}"
            + (f" of {total} shown" if truncated else "")
            + "):\n\n"
            "| # | id | created | size | type | status |\n"
            "|---|----|---------|------|------|--------|\n"
        )
        rows: list[str] = []
        for i, m in enumerate(images, start=1):
            image_id = str(m.get("image_id", ""))
            short = (image_id[:8] + "…") if len(image_id) > 8 else image_id
            created = self._short_date(str(m.get("created_at", "")))
            size = self._human_size(int(m.get("byte_size", 0) or 0))
            mime = str(m.get("mime", "")) or "?"
            status = "SAVED" if m.get("saved") else "encrypted-only"
            rows.append(
                f"| {i} | `{short}` | {created} | {size} | {mime} | {status} |"
            )
        footer = (
            "\n\n_SAVED = exported to disk at least once; encrypted-only = held "
            "encrypted in the bank, never written to a file._\n"
            "Save one with `/save <id> <path>`, or remove one with "
            "`/images delete <id>` (the FULL 32-character id is required — copy "
            "it from `/save`/the generation reply or the gallery)."
        )
        return header + "\n".join(rows) + footer

    @staticmethod
    def _short_date(iso: str) -> str:
        """Date portion of an ISO-8601 timestamp (best-effort; the whole string
        on any parse surprise — never raises)."""
        if not iso:
            return "?"
        # ISO-8601 is '<date>T<time>…'; the date is everything before the 'T'.
        return iso.split("T", 1)[0] or iso

    @staticmethod
    def _human_size(num_bytes: int) -> str:
        """A compact human byte size (KB/MB, one decimal) for a UI hint."""
        if num_bytes <= 0:
            return "0 B"
        if num_bytes < 1024:
            return f"{num_bytes} B"
        kb = num_bytes / 1024
        if kb < 1024:
            return f"{kb:.1f} KB"
        return f"{kb / 1024:.1f} MB"

    async def _images_delete(self, target: str) -> str:
        """Delete ONE generated image by its FULL 32-hex id (confirm-of-intent).

        Accepts a bare 32-hex id or a full ``blarai-img://<id>`` ref.  A partial
        id, a forged id (anything not exactly the ``uuid4().hex`` shape), or an
        empty target is REFUSED — there is no modal in the chat surface, so the
        full id IS the confirmation.  An unknown (but well-formed) id reports
        "no image found" (the store's idempotent no-op), NOT a false success.
        """
        if self._image_manager is None:
            return "Image deletion is not available in this process."
        if not target:
            return (
                "Usage: `/images delete <id>` — the FULL 32-character image id "
                "is required (copy it from `/save` or the generation reply)."
            )
        image_id = is_blarai_img_ref(target) or (
            target if re.fullmatch(r"[0-9a-f]{32}", target) else None
        )
        if image_id is None:
            return (
                "Delete refused: that is not a full image id. The FULL "
                "32-character hex id is required as confirmation (a partial id "
                "is not accepted) — copy it from `/save` or the generation reply, "
                "or use a `blarai-img://<id>` reference."
            )
        try:
            result = await self._image_manager("delete", image_id)
        except Exception as exc:  # noqa: BLE001 — Fail-Closed, surfaced as a message
            logger.error("Image delete failed for %s: %s", image_id, exc)
            return f"Could not delete the image (Fail-Closed): {exc}"
        if not result.get("ok", False):
            msg = result.get("message", "") or "image deletion failed"
            return f"Delete failed: {msg}"
        if not result.get("found", False):
            return (
                f"No generated image found for id {image_id} — nothing was "
                "deleted (it may have already been removed)."
            )
        return (
            f"Deleted generated image {image_id}. The encrypted copy is "
            "securely wiped from the bank. (Any file you previously saved to "
            "disk with `/save` is untouched.)"
        )

    # ── shared dispatch ────────────────────────────────────────────────────

    async def _dispatch_generate(
        self,
        session_id: str,
        *,
        mode: str,
        prompt: str,
        style: str = "photoreal",
        staging_ref: str = "",
        staging_image_id: str = "",
    ) -> str:
        """Encode + send IMAGE_GEN_REQUEST and render the IMAGE_GEN_RESULT reply.

        A FAILURE reply is the AO's message verbatim (including the dormant
        IMAGE_GEN_UNAVAILABLE notice) — the coordinator adds no special-casing.
        A SUCCESS reply LEADS with a markdown image embed
        ``![generated image](blarai-img://<id>)`` so the WinUI markdown renderer
        fires its inline-image path and resolves the pixels through the
        IMAGE_RESOLVE corridor (UC-010 #666/#665 Pass B); the informational line +
        ``/save`` hint follow, for the TUI (which has no inline image surface and
        shows the embed as literal text + relies on ``/save``).
        """
        try:
            message = self._framer.encode_image_gen_request(
                session_id=session_id,
                mode=mode,
                prompt=prompt,
                style=style,
                width=self._max_width,
                height=self._max_height,
                steps=self._steps,
                staging_ref=staging_ref,
                staging_image_id=staging_image_id,
                request_id=str(_uuid_mod.uuid4()),
            )
        except ValueError as exc:
            return f"Image generation refused (Fail-Closed): {exc}"
        result = await self._transport_call(message)
        if not result.get("ok", False):
            msg = result.get("message", "") or "image generation failed"
            return str(msg)
        image_ref = str(result.get("image_ref", ""))
        # Record the new image's id so the gateway can attach Edit/Save follow-up
        # buttons to THIS reply (#712). One-shot per session, popped by the gateway;
        # only a SUCCESSFUL generation with a well-formed ref sets it.
        new_image_id = is_blarai_img_ref(image_ref)
        if new_image_id:
            self._last_image_id[session_id] = new_image_id
        # Lead with the markdown image embed on its own line so the WinUI renderer
        # renders the pixels inline (its image path only fires on ![alt](ref)
        # syntax); the informational line + /save hint follow for the TUI, which
        # shows the embed as literal text and relies on /save.
        return (
            f"![generated image]({image_ref})\n\n"
            f"Image generated ({image_ref}). It renders inline in the app; "
            f"in the terminal, save it with `/save {image_ref} <path>`."
        )

    # ── helpers ────────────────────────────────────────────────────────────

    def _resolve_staging_dir(self) -> Path:
        if self._staging_dir_provider is not None:
            return self._staging_dir_provider()
        from shared.security.image_staging import default_staging_dir

        return default_staging_dir()

    def _resolve_userdata_dir(self) -> Path:
        if self._userdata_dir is not None:
            return self._userdata_dir
        from services.ui_gateway.src.document_loader import USERDATA_DIR

        return USERDATA_DIR
