"""
Document Loader — UI Gateway
==============================
Secure host-side document loading for the /load command (data pillar v1).

All file I/O happens here, in the Gateway (host side), never in the
Assistant Orchestrator. Security guards are enforced fail-closed:
any guard failure raises a typed DocumentLoadError and nothing is stashed.

Supported formats:
  .txt, .md  — plain text up to DOCUMENT_MAX_BYTES (16 KB on disk)
  .pdf       — extracted to plain text up to EXTRACTED_TEXT_MAX_BYTES
               (16 KB), with file-on-disk capped at PDF_MAX_BYTES (1 MB).
               Extraction uses pypdf (pure Python, no compiled deps).
               Encrypted or image-only PDFs are rejected with a clear
               error message; text is concatenated page-by-page with a
               single newline between pages.
  images     — .png .jpg .jpeg .gif .webp .heic — LAZY (vision on demand).
               No pixels are read at attach; the loader stashes the resolved
               image path and flags it ``pending_vision`` so the attach is
               instant. The Assistant Orchestrator tasks the VLM ON DEMAND —
               when the user actually asks about the image — with a
               context-aware query the 14B formulates from the conversation
               ("brain directs the eyes" — #561, ADR-015). Eager attach-time
               grounding froze voice + chat behind it (BUILD_JOURNAL lesson 24).
  video      — .mp4 .mov .webm — STORE-ONLY (video understanding not wired).

Every load returns a ``media_type`` of ``"text"``, ``"image"``, or
``"video"`` so callers (gateway, UI) can render an attachment the right
way without re-deriving it from the extension. Text loads carry an empty
``message``; an image load carries a "staged — analyzed when you ask"
``message`` plus ``image_path`` + ``pending_vision``; a video load carries
a user-facing "not wired" ``message``.

Path containment: resolved path must be strictly inside userdata/
"""

from __future__ import annotations

import re
from pathlib import Path

import pypdf

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# userdata/ directory — absolute, resolved once at import time.
# Locate relative to BlarAI repo root (two levels up from this file's
# services/ui_gateway/src/ location).
_THIS_FILE = Path(__file__).resolve()
_REPO_ROOT = _THIS_FILE.parents[3]  # BlarAI/
USERDATA_DIR: Path = _REPO_ROOT / "userdata"

# 16 KB ceiling for plain-text content — keeps a loaded document
# comfortably within the AO context budget (4 096 tokens, ~16 KB for
# typical English prose). Also caps PDF extracted text.
DOCUMENT_MAX_BYTES: int = 16_384
EXTRACTED_TEXT_MAX_BYTES: int = 16_384

# PDF files on disk are typically much larger than their extracted text
# (compression, fonts, structure, optional images). 1 MB on disk is a
# reasonable cap that covers most short PDFs people actually carry —
# tax docs, lab results, scanned notes, manual excerpts — while
# preventing pathological inputs.
PDF_MAX_BYTES: int = 1_048_576  # 1 MB

# Store-only media. We never read the bytes (no text to extract until a
# vision model lands, ADR-015), so the cap is a disk-sanity bound rather
# than a context-budget bound. Generous enough for phone photos and short
# clips; large enough that a real attachment is rarely rejected.
IMAGE_MAX_BYTES: int = 67_108_864    # 64 MB (high-res / phone property photos)
VIDEO_MAX_BYTES: int = 536_870_912   # 512 MB

# Extension taxonomy. TEXT extensions are read and grounded as content;
# MEDIA extensions are store-only and grounded as a placeholder.
TEXT_EXTENSIONS: frozenset[str] = frozenset({".txt", ".md", ".pdf"})
PHOTO_EXTENSIONS: frozenset[str] = frozenset(
    {".png", ".jpg", ".jpeg", ".jpe", ".jfif", ".gif", ".webp", ".bmp", ".dib",
     ".tif", ".tiff", ".ico", ".tga", ".heic", ".heif", ".avif"}
)
VIDEO_EXTENSIONS: frozenset[str] = frozenset({".mp4", ".mov", ".webm"})
MEDIA_EXTENSIONS: frozenset[str] = PHOTO_EXTENSIONS | VIDEO_EXTENSIONS

# Extensions permitted by /load and the file picker.
ALLOWED_EXTENSIONS: frozenset[str] = TEXT_EXTENSIONS | MEDIA_EXTENSIONS

# User-facing "vision not wired" messages, keyed by media_type. Surfaced
# in the chat as the attachment's status line / chip caption.
MEDIA_NOT_WIRED_MESSAGE: dict[str, str] = {
    "image": (
        "Photo uploaded; vision is not yet wired so I cannot describe it yet."
    ),
    "video": (
        "Video uploaded; video understanding is not yet wired so I cannot "
        "describe it yet."
    ),
}


def classify_media(filename: str) -> str:
    """Return the media type for *filename*: ``"text"``, ``"image"``, or ``"video"``.

    Classification is by extension only — it does not touch disk. Unknown
    or text extensions return ``"text"`` (the caller still applies the
    extension allowlist separately; this is purely a routing label).
    """
    suffix = Path(filename).suffix.lower()
    if suffix in PHOTO_EXTENSIONS:
        return "image"
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    return "text"


def _human_size(num_bytes: int) -> str:
    """Render a byte count as a short human string (e.g. ``1.2 MB``)."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024.0 or unit == "GB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{num_bytes} B"


# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------


class DocumentLoadError(ValueError):
    """Raised when a document cannot be loaded due to a security or I/O check.

    Always carries a human-readable reason suitable for display in the TUI.
    """


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_document(filename: str) -> dict[str, str]:
    """Load a document from userdata/ with all security guards applied.

    Args:
        filename: Bare filename (e.g. "notes.txt"). No path components.

    Returns:
        ``{"filename": <str>, "content": <str>, "media_type": <str>,
        "message": <str>}`` on success. ``media_type`` is ``"text"``,
        ``"image"``, or ``"video"``. For text/PDF, ``content`` is the
        extracted text and ``message`` is empty. For store-only media,
        ``content`` is a grounded placeholder telling the model it cannot
        see the file yet and ``message`` is the user-facing "vision not
        wired" line.

    Raises:
        DocumentLoadError: If any guard fails (fail-closed — nothing is
            partially loaded).
    """
    # ------------------------------------------------------------------
    # Guard 0 — filename must not be empty
    # ------------------------------------------------------------------
    stripped = filename.strip()
    if not stripped:
        raise DocumentLoadError("Filename cannot be empty.")

    # ------------------------------------------------------------------
    # Guard 0.5 — bare filename only (reject path separators)
    # The /load contract is a bare filename inside userdata/. Rejecting
    # path separators outright is defense-in-depth ahead of the Guard 2
    # containment check, and matches the userdata/README contract.
    # ------------------------------------------------------------------
    if "/" in stripped or "\\" in stripped:
        raise DocumentLoadError(
            f"Invalid filename '{filename}': provide a bare filename with "
            "no folders or path separators (e.g. 'notes.txt')."
        )

    # ------------------------------------------------------------------
    # Guard 1 — extension allowlist
    # ------------------------------------------------------------------
    suffix = Path(stripped).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise DocumentLoadError(
            f"Unsupported file type '{suffix}'. "
            f"Only {allowed} files are accepted."
        )

    # ------------------------------------------------------------------
    # Guard 2 — path containment (traversal prevention)
    # Resolve inside userdata/ and verify the real path is still inside.
    # ------------------------------------------------------------------
    if not USERDATA_DIR.is_dir():
        raise DocumentLoadError(
            "userdata/ directory does not exist. "
            "Create it and place your files there."
        )

    candidate = (USERDATA_DIR / stripped).resolve()
    try:
        candidate.relative_to(USERDATA_DIR.resolve())
    except ValueError:
        raise DocumentLoadError(
            f"Access denied: '{filename}' resolves outside userdata/."
        )

    # ------------------------------------------------------------------
    # Guard 3 — existence and regular-file check
    # ------------------------------------------------------------------
    if not candidate.exists():
        raise DocumentLoadError(
            f"File not found: '{filename}'. "
            "Place the file in the userdata/ folder and try again."
        )
    if not candidate.is_file():
        raise DocumentLoadError(
            f"'{filename}' is not a regular file."
        )

    # ------------------------------------------------------------------
    # Guard 4 — size cap (per-format)
    # ------------------------------------------------------------------
    size = candidate.stat().st_size
    media_type = classify_media(stripped)
    is_pdf = suffix == ".pdf"
    if media_type == "image":
        if size > IMAGE_MAX_BYTES:
            raise DocumentLoadError(
                f"Image too large ({size:,} bytes). "
                f"Maximum accepted image size is {IMAGE_MAX_BYTES:,} bytes (64 MB)."
            )
    elif media_type == "video":
        if size > VIDEO_MAX_BYTES:
            raise DocumentLoadError(
                f"Video too large ({size:,} bytes). "
                f"Maximum accepted video size is {VIDEO_MAX_BYTES:,} bytes (512 MB)."
            )
    elif is_pdf:
        if size > PDF_MAX_BYTES:
            raise DocumentLoadError(
                f"PDF too large ({size:,} bytes). "
                f"Maximum accepted PDF size is {PDF_MAX_BYTES:,} bytes (1 MB)."
            )
    else:
        if size > DOCUMENT_MAX_BYTES:
            raise DocumentLoadError(
                f"File too large ({size:,} bytes). "
                f"Maximum accepted size is {DOCUMENT_MAX_BYTES:,} bytes (16 KB)."
            )

    # ------------------------------------------------------------------
    # Store-only media (image / video) — no bytes are read. We ground a
    # placeholder so the model is AWARE an attachment exists and can say
    # it cannot interpret it yet. When a vision model lands (ADR-015),
    # only this grounded text changes — the rest of the pipeline is
    # already shaped for it.
    # ------------------------------------------------------------------
    if media_type in ("image", "video"):
        if media_type == "image":
            # Lazy vision (#561, ADR-015): do NOT analyze the image on attach.
            # Stash it with its resolved path and a pending_vision flag; the
            # attach returns instantly with no GPU work and no pixels read.
            # The Assistant Orchestrator tasks the VLM ON DEMAND — when the
            # user actually asks about the image — with a query the 14B
            # formulates from the conversation ("brain directs the eyes").
            # Eager attach-time grounding monopolised a single serialised lane
            # and froze voice + chat behind it (BUILD_JOURNAL lesson 24); the
            # path travels to the AO so it can open the file host-side.
            return {
                "filename": stripped,
                "content": "",  # nothing grounded at attach; AO grounds on demand
                "media_type": "image",
                "message": (
                    f"Photo '{stripped}' attached — I'll look at it when you "
                    "ask about it."
                ),
                "image_path": str(candidate),
                "pending_vision": True,
            }
        # Video — store-only placeholder (video understanding is not wired).
        placeholder = (
            f"[Attachment: video file '{stripped}' "
            f"({_human_size(size)}). BlarAI cannot interpret video contents "
            "yet — video understanding is not wired. If the user asks about "
            "this file, explain that video understanding is not yet "
            "available.]"
        )
        return {
            "filename": stripped,
            "content": placeholder,
            "media_type": "video",
            "message": MEDIA_NOT_WIRED_MESSAGE["video"],
        }

    # ------------------------------------------------------------------
    # Read — text formats decode UTF-8 directly; PDFs are extracted to
    # text via pypdf. PDFs that are encrypted or contain no extractable
    # text (e.g. scanned-image-only PDFs) raise a clear DocumentLoadError
    # rather than silently producing an empty grounded context.
    # ------------------------------------------------------------------
    if is_pdf:
        content = _extract_pdf_text(candidate, filename)
    else:
        try:
            content = candidate.read_text(encoding="utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise DocumentLoadError(
                f"Cannot read '{filename}' as UTF-8 text: {exc}"
            ) from exc
        except OSError as exc:
            raise DocumentLoadError(
                f"Cannot read '{filename}': {exc}"
            ) from exc

    return {
        "filename": stripped,
        "content": content,
        "media_type": "text",
        "message": "",
    }


def store_attachment(src_path: str) -> dict[str, str]:
    """Copy a file from anywhere on disk into userdata/ and load it.

    Backs the file picker / drag-and-drop path: the user chooses a file
    from any location; this copies it into userdata/ (the only directory
    /load reads from) and returns the same descriptor :func:`load_document`
    returns, so the caller treats a picked file identically to a
    typed ``/load``.

    All file I/O stays here. Security guards: the source must exist and be
    a regular file with an allowed extension and an in-range size; the
    destination is always a bare filename inside userdata/ (the source
    directory is never honoured), with collision-safe renaming.

    Args:
        src_path: Absolute or relative path to the source file on disk.

    Returns:
        The :func:`load_document` descriptor for the stored copy.

    Raises:
        DocumentLoadError: If any guard fails (fail-closed — nothing is
            copied on failure).
    """
    src_stripped = src_path.strip()
    if not src_stripped:
        raise DocumentLoadError("No file path provided.")

    source = Path(src_stripped)
    suffix = source.suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise DocumentLoadError(
            f"Unsupported file type '{suffix}'. Only {allowed} files "
            "are accepted."
        )

    if not source.exists() or not source.is_file():
        raise DocumentLoadError(f"File not found: '{src_path}'.")

    size = source.stat().st_size
    media_type = classify_media(source.name)
    cap = {
        "image": IMAGE_MAX_BYTES,
        "video": VIDEO_MAX_BYTES,
    }.get(media_type, PDF_MAX_BYTES if suffix == ".pdf" else DOCUMENT_MAX_BYTES)
    if size > cap:
        raise DocumentLoadError(
            f"File too large ({size:,} bytes). Maximum for this type is "
            f"{cap:,} bytes."
        )

    if not USERDATA_DIR.is_dir():
        USERDATA_DIR.mkdir(parents=True, exist_ok=True)

    # Destination is always a bare basename inside userdata/. A picked
    # file named the same as an existing one gets a ` (1)`, ` (2)`, …
    # suffix so a new attachment never silently overwrites an old one.
    dest_name = source.name
    dest = USERDATA_DIR / dest_name
    counter = 1
    while dest.exists():
        dest_name = f"{source.stem} ({counter}){source.suffix}"
        dest = USERDATA_DIR / dest_name
        counter += 1

    try:
        dest.write_bytes(source.read_bytes())
    except OSError as exc:
        raise DocumentLoadError(
            f"Could not copy '{source.name}' into userdata/: {exc}"
        ) from exc

    return load_document(dest_name)


# ---------------------------------------------------------------------------
# PDF extraction
# ---------------------------------------------------------------------------


def _extract_pdf_text(path: Path, filename: str) -> str:
    """Extract text from a PDF using pypdf and apply the text-size cap.

    Args:
        path: Resolved file path inside userdata/.
        filename: Bare filename (used in error messages only).

    Returns:
        Concatenated page text, joined by single newlines. Truncated to
        EXTRACTED_TEXT_MAX_BYTES (UTF-8) with a `[...truncated...]` marker
        when the document exceeds the cap.

    Raises:
        DocumentLoadError: If the PDF is encrypted (with no empty
            password), is corrupted, or yields no extractable text
            (typical for scanned-image-only PDFs).
    """
    try:
        reader = pypdf.PdfReader(str(path))
    except pypdf.errors.PdfReadError as exc:
        raise DocumentLoadError(
            f"Cannot read '{filename}': not a valid PDF ({exc})."
        ) from exc
    except OSError as exc:
        raise DocumentLoadError(
            f"Cannot open '{filename}': {exc}"
        ) from exc

    if reader.is_encrypted:
        # Try the empty password (some PDFs are "encrypted" with no real
        # password set). If that fails, we ask the user.
        try:
            if reader.decrypt("") == pypdf.PasswordType.NOT_DECRYPTED:
                raise DocumentLoadError(
                    f"'{filename}' is password-protected. BlarAI does not "
                    "ask for PDF passwords; please save an unencrypted "
                    "copy in userdata/ and load that."
                )
        except (NotImplementedError, pypdf.errors.PdfReadError) as exc:
            raise DocumentLoadError(
                f"'{filename}' uses a PDF encryption method BlarAI "
                f"cannot read ({exc}); please save an unencrypted copy."
            ) from exc

    pages: list[str] = []
    try:
        for page in reader.pages:
            extracted = page.extract_text() or ""
            if extracted:
                pages.append(extracted)
    except Exception as exc:  # pypdf can raise various extraction errors
        raise DocumentLoadError(
            f"Cannot extract text from '{filename}': {exc}"
        ) from exc

    if not pages:
        raise DocumentLoadError(
            f"'{filename}' contains no extractable text. This usually "
            "means the PDF is a scanned image — OCR would be needed, "
            "which BlarAI does not currently do. Try a text-based PDF "
            "instead."
        )

    full_text = "\n".join(pages)
    encoded = full_text.encode("utf-8", errors="replace")
    if len(encoded) <= EXTRACTED_TEXT_MAX_BYTES:
        return full_text

    # Truncate on a UTF-8 boundary and leave a clear marker so the model
    # and the user both know the document was cut off.
    truncated_bytes = encoded[:EXTRACTED_TEXT_MAX_BYTES]
    truncated = truncated_bytes.decode("utf-8", errors="ignore")
    return (
        f"{truncated}\n"
        "[...truncated: PDF text exceeded "
        f"{EXTRACTED_TEXT_MAX_BYTES:,}-byte cap...]"
    )


# ---------------------------------------------------------------------------
# Prompt-injection heuristic scan
# ---------------------------------------------------------------------------
#
# A loaded document is untrusted content; it may carry text crafted to
# manipulate the assistant ("prompt injection"). This scan is a heuristic
# WARNING signal, not a load-blocking guard: heuristics false-positive, and a
# document may legitimately discuss these phrasings (a document *about* prompt
# injection, for instance). It is one layer of defense-in-depth -- the
# deterministic layer is delimiter neutralization in the context manager, and
# the output backstop is the PGOV delimiter-echo check.

# (description, pattern) -- description is surfaced to the user if the pattern hits.
_INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("an instruction to ignore prior instructions",
     re.compile(r"(?i)\bignore\s+(?:\w+\s+){0,3}(?:instruction|prompt|context|rule|direction)s?\b")),
    ("an instruction to disregard prior instructions",
     re.compile(r"(?i)\bdisregard\s+(?:\w+\s+){0,3}(?:instruction|prompt|context|rule|direction)s?\b")),
    ("an instruction to override prior instructions",
     re.compile(r"(?i)\boverride\s+(?:\w+\s+){0,3}(?:instruction|prompt|rule)s?\b")),
    ("a role-reassignment attempt (\"you are now ...\")",
     re.compile(r"(?i)\byou\s+are\s+now\b")),
    ("a reference to the \"system prompt\"",
     re.compile(r"(?i)\bsystem\s+prompt\b")),
    ("a new- or updated-instructions directive",
     re.compile(r"(?i)\b(?:new|updated|revised)\s+(?:instruction|directive)s?\b")),
    ("a \"reply only with ...\" directive",
     re.compile(r"(?i)\b(?:reply|respond|answer|output|say|print)\s+(?:only|exclusively)\s+with\b")),
    ("a forged internal framing token (<|...|>)",
     re.compile(r"<\|[A-Za-z0-9_]+\|>")),
]


def scan_for_injection(text: str) -> list[str]:
    """Heuristically scan document content for prompt-injection patterns.

    Args:
        text: Document content to scan.

    Returns:
        Human-readable descriptions of suspicious patterns found, deduplicated
        and in a stable order. An empty list means nothing matched. This is a
        warning signal for the user -- not a load-blocking guard.
    """
    found: list[str] = []
    for description, pattern in _INJECTION_PATTERNS:
        if pattern.search(text) and description not in found:
            found.append(description)
    return found
