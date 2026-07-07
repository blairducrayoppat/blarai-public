"""
Cleaner v1 pipeline — UC-003 ingest preprocessing (ADR-030, Vikunja #655).
==========================================================================
The mandatory preprocessing gate for the knowledge bank (ADR-031): raw HTML
or operator-pasted text in, a :class:`CleanResult` out — boilerplate-stripped
article text + metadata, normalized, adversarially sanitized, with a
conservative fail-closed quarantine verdict.

Data-normalizer FIRST, security-sanitizer second (the LA's ratified #613
framing, binding per ADR-030 §1): the primary deliverable is knowledge
QUALITY — signal, not navigation chrome — for a store with a decades
horizon. The sanitization stage is explicitly Layer 1 of 3 (see
``services/cleaner/src/sanitize.py``).

STAGE LAYOUT (Stage C split, #655): the trafilatura knobs, the quarantine
policy constants, and the extraction-quality verdict math live in
``services/cleaner/src/extraction.py`` — the guest-importable leaf module
the guest parser service (``services/cleaner/guest/parser_service.py``)
shares with this pipeline, so the knobs and the verdict have ONE definition.
This module composes that stage with normalization + sanitization for the
host-side paths and RE-EXPORTS the constants (existing importers are
unaffected).  Tune policy in ``extraction.py`` only.

EXTRACTION-ONLY POSTURE (ADR-030 §4, binding): trafilatura is used solely
for extraction over bytes the caller already holds. Its fetch machinery
(``fetch_url`` / ``fetch_response`` / ``trafilatura.downloads``) is FORBIDDEN
— fetching belongs to the single PA-gated egress door
(``shared/security/guarded_fetch.fetch_external``, W4). The URL-mode fetch
limb is written at Stage C through that door (ADR-030 §8 — the #598
sign-off itself is recorded).
The static-scan lock in ``tests/security/test_no_external_egress.py``
enforces this on the standing gate, and an import-time lock asserts this
module opens no sockets. (Importing the ``trafilatura`` package unavoidably
*loads* its downloads module — verified 2026-06-10: even
``trafilatura.core`` imports it — but loading is inert; the locks prove no
socket is ever constructed.)

QUARANTINE POLICY (ADR-030 §6 — "tunable, start conservative"): a document
is ``quarantined`` when extraction fails or yields too little text, when the
text/raw ratio is anomalous (paywall teasers, parse failures), when overall
extraction confidence is low, or when injection sanitization flags fire.
Quarantined results STILL CARRY the cleaned text — the operator reviews it
in chat, and explicit approval is the override (there is no auto-approve
path; every document lands pending either way, per ADR-031 L0). The
constants (re-exported from ``extraction.py``) are the tuning surface; each
is named so a future recalibration is a reviewable one-line diff.

Determinism: same input → same ``CleanResult``, byte-identical. Locked by
tests.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

# Canonical extraction stage + policy constants (re-exported — see module
# docstring).  The noqa'd names are the public re-export surface existing
# importers consume from this module.
from services.cleaner.src.extraction import (  # noqa: F401  (re-exports)
    CONFIDENCE_QUARANTINE_FLOOR,
    INJECTION_CONFIDENCE_FACTOR,
    MIN_EXTRACTION_RATIO,
    MIN_WORDS_HTML,
    MIN_WORDS_TEXT,
    REASON_EXTRACTION_FAILED,
    REASON_INJECTION_PATTERN_DETECTED,
    REASON_LOW_EXTRACTION_CONFIDENCE,
    REASON_LOW_EXTRACTION_RATIO,
    REASON_LOW_TEXT_LENGTH,
    TARGET_EXTRACTION_RATIO,
    TARGET_WORDS,
    _clamp01,
    clean_metadata_field,
    extract_document,
    judge_extraction,
)
from services.cleaner.src.image_refs import escape_image_alt
from services.cleaner.src.normalize import normalize_text
from services.cleaner.src.sanitize import sanitize_text
from shared.ipc.parse_channel import ParseResponse

#: Pipeline version, recorded on every knowledge-bank row (ADR-031 L1's
#: ``cleaner_version``) so a future extraction-quality fix can identify
#: which documents an older pipeline produced. Semver.
CLEANER_VERSION: str = "1.0.0"

# Markdown shape heuristics for clean_text's source_format label (routing
# label only — both formats take the identical processing path).
_MD_HEADING_RE: re.Pattern[str] = re.compile(r"^#{1,6}\s+\S", re.MULTILINE)
_MD_FENCE_RE: re.Pattern[str] = re.compile(r"^```", re.MULTILINE)
_MD_LINK_RE: re.Pattern[str] = re.compile(r"\[[^\]\n]+\]\([^)\s]+\)")
_MD_TITLE_RE: re.Pattern[str] = re.compile(r"\A#\s+(\S[^\n]*)")


@dataclass(frozen=True)
class CleanResult:
    """The Cleaner's output contract (cross-agent interface, #655 Stage B).

    Frozen: a verdict is immutable once issued. ``reasons`` is a tuple of
    stable event-code strings (the ``REASON_*`` constants) in a fixed,
    documented order; ``confidence`` is 0..1 and deterministic.
    """

    status: Literal["clean", "quarantined"]
    text: str
    title: str | None
    byline: str | None
    published_date: str | None
    word_count: int
    confidence: float
    reasons: tuple[str, ...]
    cleaner_version: str
    source_format: Literal["html", "text", "markdown"]


def clean_html(raw_html: str, *, source_url: str | None = None) -> CleanResult:
    """Clean a raw HTML document into article text + metadata with a verdict.

    Canonical extraction (``extraction.extract_document`` — the shared
    trafilatura knobs) → normalization → sanitization → the shared
    extraction-quality verdict composed with the injection axis
    (``extraction.judge_extraction``). *source_url* is metadata for the
    extractor's URL heuristics only — NOTHING here fetches (extraction-only
    posture, module docstring).

    Total function: extractor failure yields a quarantined
    ``EXTRACTION_FAILED`` result (empty text, confidence 0.0) rather than
    raising — the loud, reviewable representation the chat surface renders;
    with no text there is nothing approvable, so nothing can be stored
    degraded (ADR-030 §6).
    """
    raw_len = len(raw_html)
    extracted = extract_document(raw_html, source_url=source_url)
    if extracted is None:
        return _failed_extraction_result()

    normalized = normalize_text(extracted.text)
    sanitized = sanitize_text(normalized)
    # ALWAYS-ON image-alt hardening (UC-003-B): with include_images=True the
    # extracted text carries inline ![alt](url) refs; neutralize any
    # markdown-breakout / active-scheme URL in the alt slot BEFORE the verdict
    # so the stored + previewed text is safe REGARDLESS of whether images are
    # ever fetched (the egress / images_enabled locks do NOT gate this).
    text = escape_image_alt(sanitized.text).strip()

    verdict = judge_extraction(
        text,
        raw_len,
        injection_finding_count=len(sanitized.injection_findings),
    )

    return CleanResult(
        status="quarantined" if verdict.reasons else "clean",
        text=text,
        title=clean_metadata_field(extracted.title),
        byline=clean_metadata_field(extracted.byline),
        published_date=clean_metadata_field(extracted.published_date),
        word_count=verdict.word_count,
        confidence=verdict.confidence,
        reasons=verdict.reasons,
        cleaner_version=CLEANER_VERSION,
        source_format="html",
    )


def clean_text(raw_text: str) -> CleanResult:
    """Clean operator-pasted plaintext/markdown (no HTML parsing).

    Normalization → sanitization → verdict. The paste path is the operator's
    own clipboard, not a hostile parser input (ADR-030 §3) — so there is no
    extractor to distrust and no ratio axis; the floors are a tiny/garbage
    sanity check (``MIN_WORDS_TEXT``) plus the same injection scan, and
    confidence starts at 1.0 instead of being earned from extraction
    signals. ``source_format`` is ``"markdown"`` when the paste is
    markdown-shaped (heading / fence / link), else ``"text"`` — a routing
    label only; for a markdown paste opening with an H1, that heading
    doubles as the title.
    """
    normalized = normalize_text(raw_text)
    sanitized = sanitize_text(normalized)
    # ALWAYS-ON image-alt hardening (UC-003-B) — an operator paste can carry
    # ![alt](url) markdown too; neutralize alt breakout / active-scheme URLs
    # before the verdict and the markdown-shape heuristics run.
    text = escape_image_alt(sanitized.text).strip()

    is_markdown = bool(
        _MD_HEADING_RE.search(text)
        or _MD_FENCE_RE.search(text)
        or _MD_LINK_RE.search(text)
    )
    title: str | None = None
    if is_markdown:
        title_match = _MD_TITLE_RE.match(text)
        if title_match:
            title = title_match.group(1).strip() or None

    word_count = len(text.split())

    confidence = 1.0
    if word_count < MIN_WORDS_TEXT:
        confidence = _clamp01(word_count / MIN_WORDS_TEXT)
    if sanitized.injection_findings:
        confidence *= INJECTION_CONFIDENCE_FACTOR
    confidence = _clamp01(confidence)

    reasons: list[str] = []
    if word_count < MIN_WORDS_TEXT:
        reasons.append(REASON_LOW_TEXT_LENGTH)
    if sanitized.injection_findings:
        reasons.append(REASON_INJECTION_PATTERN_DETECTED)

    return CleanResult(
        status="quarantined" if reasons else "clean",
        text=text,
        title=title,
        byline=None,
        published_date=None,
        word_count=word_count,
        confidence=confidence,
        reasons=tuple(reasons),
        cleaner_version=CLEANER_VERSION,
        source_format="markdown" if is_markdown else "text",
    )


def _failed_extraction_result() -> CleanResult:
    """The quarantined EXTRACTION_FAILED verdict (empty text, confidence 0)."""
    return CleanResult(
        status="quarantined",
        text="",
        title=None,
        byline=None,
        published_date=None,
        word_count=0,
        confidence=0.0,
        reasons=(REASON_EXTRACTION_FAILED,),
        cleaner_version=CLEANER_VERSION,
        source_format="html",
    )


def clean_from_guest_parse(
    response: ParseResponse,
    *,
    raw_len: int,
    extra_injection_findings: int = 0,
) -> CleanResult:
    """Compose the host-side ``CleanResult`` from a guest ``ParseResponse``.

    Stage C division of labor (ADR-030 §5, Vikunja #655): the guest parser
    does trafilatura extraction + pure-Python normalization + the
    extraction-quality verdict with the injection axis FORCED to zero
    (``services/cleaner/guest/parser_service.py``) — the sanitization
    primitives live in host packages the Alpine guest does not carry.  The
    host composes the injection axis HERE so a fetched page's final verdict is
    produced exactly the way :func:`clean_html` produces it for a local
    document — sanitize → re-judge — WITHOUT re-running trafilatura over the
    hostile HTML host-side (the whole reason the parse happened in the guest).

    Args:
        response: the guest's already-extracted, already-normalized result.
            ``response.text`` is the normalized (pre-sanitization) article
            text; ``response.reasons`` are extraction-axis codes only.
        raw_len: length in characters of the fetched HTML the guest parsed —
            the SAME ``raw_len`` the guest used, so the extraction-ratio axis
            stays consistent across the host re-judge.
        extra_injection_findings: an upstream injection signal folded into the
            injection count — the ``guarded_fetch`` ADR-013 Layer-2 scan over
            the raw fetched body (``FetchResult.injection_flags``).  A non-zero
            value quarantines the document even if the host scan over the
            cleaned text does not re-fire (defense in depth, fail-closed-strict).

    A guest extraction failure (empty text — ``REASON_EXTRACTION_FAILED``) is
    preserved verbatim: there is nothing to sanitize and re-judging empty text
    would replace the honest EXTRACTION_FAILED verdict with a misleading
    length/ratio one.  The caller refuses an empty result loudly (nothing
    approvable can be stored — ADR-030 §6).

    Determinism: same ``response`` + ``raw_len`` → byte-identical CleanResult.
    """
    guest_text = response.text
    if not guest_text.strip():
        return CleanResult(
            status="quarantined",
            text="",
            title=response.title,
            byline=response.byline,
            published_date=response.published_date,
            word_count=0,
            confidence=0.0,
            reasons=response.reasons or (REASON_EXTRACTION_FAILED,),
            cleaner_version=CLEANER_VERSION,
            source_format="html",
        )

    sanitized = sanitize_text(guest_text)
    # ALWAYS-ON image-alt hardening (UC-003-B) — the guest emits inline
    # ![alt](url) refs (include_images=True on the shared extraction leaf);
    # neutralize alt breakout / active-scheme URLs host-side before the verdict
    # so a fetched page's stored + previewed text is safe regardless of the
    # fetch locks (composed identically to clean_html).
    text = escape_image_alt(sanitized.text).strip()
    injection_count = len(sanitized.injection_findings) + max(
        0, int(extra_injection_findings)
    )
    # raw_len >= 1 is guaranteed by the caller (a fetched body is non-empty);
    # clamp fail-closed against a zero that would divide-by-zero in the verdict.
    verdict = judge_extraction(
        text,
        max(1, int(raw_len)),
        injection_finding_count=injection_count,
    )
    return CleanResult(
        status="quarantined" if verdict.reasons else "clean",
        text=text,
        title=response.title,
        byline=response.byline,
        published_date=response.published_date,
        word_count=verdict.word_count,
        confidence=verdict.confidence,
        reasons=verdict.reasons,
        cleaner_version=CLEANER_VERSION,
        source_format="html",
    )
