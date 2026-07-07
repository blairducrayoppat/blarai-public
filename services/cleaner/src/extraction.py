"""
Extraction stage — canonical trafilatura knobs + extraction-quality verdict
===========================================================================
UC-003 (ADR-030 §4/§6, Vikunja #655 Stage C).  This is the LEAF module both
extraction consumers share:

* ``services/cleaner/src/pipeline.py`` — the host-side pipeline (extraction →
  normalization → sanitization → composed verdict);
* ``services/cleaner/guest/parser_service.py`` — the guest-homed parser
  (extraction → normalization → extraction-axis verdict; sanitization is
  composed HOST-side after the vsock response, because the injection-scan
  primitives live in host service packages the Alpine guest does not carry).

It exists so the trafilatura knobs and the quarantine-verdict math have ONE
definition: this module imports ONLY ``trafilatura`` + stdlib (no sanitize
chain, no host service packages), which is what makes it importable inside
the Alpine 3.21 / Python 3.12 / lxml 5.3.0 guest.

EXTRACTION-ONLY POSTURE (ADR-030 §4, binding): trafilatura is used solely
for extraction over bytes the caller already holds.  Its fetch machinery
(``fetch_url`` / ``fetch_response`` / ``trafilatura.downloads``) is FORBIDDEN
— the static AST lock in ``tests/security/test_no_external_egress.py``
enforces this over every runtime root, including this module and the guest
package.

Determinism: same input → same output, byte-identical.  Locked by the
pipeline corpus tests and the guest parser tests.
"""

from __future__ import annotations

from dataclasses import dataclass

# Extraction-only import (module docstring).  The fetch-capable names
# (fetch_url / fetch_response / downloads) are never referenced — the AST
# scan in tests/security/test_no_external_egress.py fails the standing gate
# if they ever are.
import trafilatura

from services.cleaner.src.normalize import normalize_text

# ---------------------------------------------------------------------------
# Quarantine policy constants (ADR-030 §6 — conservative v1 calibration).
# CANONICAL DEFINITION — pipeline.py re-exports these; tune here only.
# ---------------------------------------------------------------------------

#: HTML path: fewer extracted words than this is not an article worth
#: auto-trusting — quarantine for review. (A real news article is rarely
#: under ~150 words; 80 keeps short wire briefs clean while catching
#: teasers/fragments.)
MIN_WORDS_HTML: int = 80

#: Text path: an operator paste below this is tiny/garbage-shaped —
#: quarantine. Deliberately far lower than the HTML floor: the operator's
#: own clipboard needs no extractor trust, only a sanity floor.
MIN_WORDS_TEXT: int = 10

#: HTML path: extracted-chars / raw-chars below this is anomalous —
#: a paywall teaser or a page the extractor mostly failed on. Real-world
#: article pages typically land at 1-5%; 0.2% is the alarm floor.
MIN_EXTRACTION_RATIO: float = 0.002

#: Confidence saturation points (score components reach 1.0 here).
TARGET_WORDS: int = 150
TARGET_EXTRACTION_RATIO: float = 0.01

#: HTML path: composite confidence below this quarantines even when no
#: individual floor tripped (the borderline-on-every-axis case).
CONFIDENCE_QUARANTINE_FLOOR: float = 0.5

#: Any injection finding multiplies confidence by this factor — a flagged
#: document is a less trustworthy extraction by definition.
INJECTION_CONFIDENCE_FACTOR: float = 0.25

# ---------------------------------------------------------------------------
# Stable reason event-codes (the cross-agent contract — gateway/WinUI render
# these AND they ride the INGEST_PARSE_RESPONSE wire; never rename without a
# contract bump)
# ---------------------------------------------------------------------------

REASON_EXTRACTION_FAILED: str = "EXTRACTION_FAILED"
REASON_LOW_TEXT_LENGTH: str = "LOW_TEXT_LENGTH"
REASON_LOW_EXTRACTION_RATIO: str = "LOW_EXTRACTION_RATIO"
REASON_LOW_EXTRACTION_CONFIDENCE: str = "LOW_EXTRACTION_CONFIDENCE"
REASON_INJECTION_PATTERN_DETECTED: str = "INJECTION_PATTERN_DETECTED"


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def clean_metadata_field(value: str | None) -> str | None:
    """Normalize a metadata field; empty/whitespace-only collapses to None."""
    if value is None:
        return None
    cleaned = normalize_text(value)
    return cleaned if cleaned else None


@dataclass(frozen=True)
class ExtractedDocument:
    """Raw trafilatura extraction output (pre-normalization, pre-verdict)."""

    text: str
    """Extracted article text (non-empty by construction)."""

    title: str | None
    byline: str | None
    published_date: str | None


@dataclass(frozen=True)
class ExtractionVerdict:
    """The extraction-quality verdict over a cleaned text."""

    word_count: int
    confidence: float
    reasons: tuple[str, ...]
    """Stable REASON_* codes in fixed order: length → ratio → confidence →
    injection (the last only when ``injection_finding_count`` > 0)."""


def extract_document(
    raw_html: str, *, source_url: str | None = None
) -> ExtractedDocument | None:
    """Run the canonical trafilatura extraction over *raw_html*.

    The ONE place the extraction knobs live (``bare_extraction`` —
    favor_recall off, metadata on, comments OFF: reader comments are
    navigation-chrome-grade noise for a knowledge store, ADR-030 §1).
    *source_url* is metadata for the extractor's URL heuristics only —
    NOTHING here fetches (extraction-only posture, module docstring).

    Total function: empty/whitespace input, an extractor crash on hostile
    bytes, or an empty extraction all return None — the caller maps None to
    its quarantined EXTRACTION_FAILED representation.
    """
    if len(raw_html) == 0 or raw_html.isspace():
        return None
    try:
        document = trafilatura.bare_extraction(
            raw_html,
            url=source_url,
            with_metadata=True,
            favor_recall=False,
            include_comments=False,
            include_formatting=True,
            # UC-003 Workstream B (display-only images): emit content images
            # INLINE in the extracted markdown as ``![alt](url)`` refs (verified
            # empirically — trafilatura 2.1.0 renders ``<img alt src>`` as
            # ``![alt](src)``).  The host coordinator walks these out of the
            # text via ``services/cleaner/src/image_refs.extract_image_refs``.
            #
            # GUEST LEAF CHANGE: this module is the trafilatura-knob leaf shared
            # by the host pipeline AND the guest-homed parser
            # (``services/cleaner/guest/parser_service.py``).  Changing a knob
            # here does NOT affect a GUEST parse until the guest CD-ISO is
            # re-provisioned (#662) — the running guest carries the OLD knobs
            # until then.  Host parses pick the new knob up immediately.
            #
            # DORMANT: emitting the refs is inert.  No image bytes are fetched
            # anywhere — the egress door stays welded and the 4th lock
            # ``[knowledge].images_enabled=false`` keeps the fetch limb dark.
            # The ALWAYS-ON ``escape_image_alt`` pass in the pipeline neutralizes
            # any hostile alt regardless of the fetch locks.
            include_images=True,
        )
    except Exception:  # noqa: BLE001 — extractor crash on hostile bytes is a verdict, not a fault
        return None

    extracted_text = getattr(document, "text", None) if document is not None else None
    if not extracted_text or extracted_text.isspace():
        return None
    return ExtractedDocument(
        text=extracted_text,
        title=getattr(document, "title", None),
        byline=getattr(document, "author", None),
        published_date=getattr(document, "date", None),
    )


def judge_extraction(
    text: str,
    raw_len: int,
    *,
    injection_finding_count: int = 0,
) -> ExtractionVerdict:
    """The ONE extraction-quality verdict computation (ADR-030 §6).

    *text* is the fully cleaned text the verdict applies to (host: post-
    sanitization; guest: post-normalization — the guest passes
    ``injection_finding_count=0`` because the injection scan is composed
    host-side).  *raw_len* is the raw input length in characters.

    Raises:
        ValueError: If *raw_len* < 1 (callers handle empty input before
            judging — fail-closed against a divide-by-zero verdict).
    """
    if raw_len < 1:
        raise ValueError(f"raw_len must be >= 1, got {raw_len}")

    word_count = len(text.split())
    ratio = len(text) / raw_len

    length_score = _clamp01(word_count / TARGET_WORDS)
    ratio_score = _clamp01(ratio / TARGET_EXTRACTION_RATIO)
    confidence = length_score * ratio_score
    if injection_finding_count:
        confidence *= INJECTION_CONFIDENCE_FACTOR
    confidence = _clamp01(confidence)

    # Reasons in fixed order: length → ratio → confidence → injection.
    reasons: list[str] = []
    if word_count < MIN_WORDS_HTML:
        reasons.append(REASON_LOW_TEXT_LENGTH)
    if ratio < MIN_EXTRACTION_RATIO:
        reasons.append(REASON_LOW_EXTRACTION_RATIO)
    if (
        not reasons
        and confidence < CONFIDENCE_QUARANTINE_FLOOR
        and not injection_finding_count
    ):
        reasons.append(REASON_LOW_EXTRACTION_CONFIDENCE)
    if injection_finding_count:
        reasons.append(REASON_INJECTION_PATTERN_DETECTED)

    return ExtractionVerdict(
        word_count=word_count,
        confidence=confidence,
        reasons=tuple(reasons),
    )
