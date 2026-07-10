"""
Post-Generation Output Validator (PGOV) — Orchestrator
========================================================
USE-CASE-004, P1.9: Validates generated output before it reaches the user.
OWASP LLM04 / Red Team ISSUE-005: Data leakage via cosine similarity.

The PGOV runs a **6-stage validation pipeline** on every generated response:

  Stage 1 — Token budget compliance (circuit breaker confirmation).
  Stage 2 — PII / secret detection (governed by the pii_mode policy).
  Stage 3 — Context Spotlighting delimiter echo detection.
  Stage 4 — Tool-call allowlist enforcement.
  Stage 5 — Retrieval leakage detection (cosine similarity).
  Stage 6 — Final approval gate (Fail-Closed).

Any violation triggers output suppression — the response is replaced
with a safe fallback message.

Leakage Detection Architecture:
  The PGOV optionally loads the same bge-small-en-v1.5 ONNX model used
  by the Semantic Router. The embedding device is configurable (#720,
  [embeddings].device): the default offloads the encoder to the NPU via
  OpenVINO (fail-soft to the ONNX Runtime CPU path), keeping both the
  P-cores and the 14B-contended GPU free. Text is embedded →
  L2-normalized → pairwise cosine similarity computed via dot product.
  Max similarity ≥ 0.85 threshold flags potential verbatim retrieval
  leakage.

  If the embedding model is not loaded, leakage detection Fails Closed
  (returns 1.0 = maximum leakage) to prevent bypass.

Security:
  - PGOV runs AFTER generation but BEFORE response delivery.
  - Cosine similarity threshold: 0.85 (from shared/constants.py).
  - Fail-Closed: PGOV errors suppress the response entirely.
  - No external network calls.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

# Context Spotlighting delimiters that must NEVER appear in user-facing output.
# Re-imported at module level for delimiter echo detection.
from services.assistant_orchestrator.src.context_manager import (
    CONTEXT_BEGIN,
    CONTEXT_END,
    SYSTEM_BEGIN,
    SYSTEM_END,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PGOVResult:
    """Result of post-generation output validation."""

    approved: bool
    """True if the output passed all PGOV checks."""

    original_text: str
    """The original generated text."""

    sanitized_text: str
    """The text to deliver (original if approved, fallback if not)."""

    leakage_score: float
    """Cosine similarity score against retrieved context (0.0 if no context)."""

    pii_detected: bool
    """True if PII patterns were found in the output."""

    token_count_valid: bool
    """True if the output respects the token budget."""

    delimiter_echo: bool = False
    """True if Context Spotlighting delimiters were found in output."""

    tool_call_violation: bool = False
    """True if an unauthorized tool-call reference was found in output."""

    violations: list[str] = field(default_factory=list)
    """List of specific violations detected."""

    pii_redactions: list[dict[str, Any]] = field(default_factory=list)
    """Provenance-redaction audit records (redact mode only). One entry per PII
    span: label, span offsets, action ('surfaced' | 'redacted'), and reason.
    Never carries raw PII values — an audit trail must not itself leak PII."""


FALLBACK_MESSAGE: str = (
    "I'm unable to provide that response due to content policy constraints. "
    "Please rephrase your request."
)
"""Safe fallback when PGOV suppresses a response."""


# ---------------------------------------------------------------------------
# PII Detection — Expanded Pattern Set
# ---------------------------------------------------------------------------

# Named patterns: (label, compiled regex)
_PII_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # US Social Security Number: 123-45-6789
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),

    # Credit card numbers: 13-19 digit strings, Luhn-validated by _luhn_valid().
    # The regex finds candidates; _luhn_valid() accepts only real PANs.
    ("CREDIT_CARD", re.compile(r"\b(?:\d[ -]*?){13,19}\b")),

    # Email addresses (RFC 5321 simplified)
    ("EMAIL", re.compile(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
    )),

    # US phone numbers: (123) 456-7890 or 123-456-7890 or +1-123-456-7890
    ("PHONE_US", re.compile(
        r"(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"
    )),

    # IP addresses (IPv4): 192.168.1.1
    ("IPV4", re.compile(
        r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}"
        r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"
    )),

    # AWS access key IDs: AKIA followed by 16 alphanumeric chars
    ("AWS_KEY", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),

    # Generic API keys / secrets: long hex strings (32+ chars)
    ("HEX_SECRET", re.compile(r"\b[0-9a-fA-F]{32,}\b")),

    # US passport numbers: 9-digit sequences preceded by passport-related
    # context within 30 chars (tightened to reduce false positives).
    ("PASSPORT_US", re.compile(
        r"(?i)(?:passport|travel\s+doc)[\w\s:# -]{0,30}\b([0-9]{9})\b"
    )),

    # Bearer tokens in output (should never be exposed)
    ("BEARER_TOKEN", re.compile(r"\bBearer\s+[A-Za-z0-9\-._~+/]+=*\b")),
]


# ---------------------------------------------------------------------------
# Luhn (mod-10) checksum — credit card PAN validation
# ---------------------------------------------------------------------------


def _luhn_valid(digits: str) -> bool:
    """Return True if *digits* passes the Luhn (mod-10) checksum.

    Accepts a string of decimal digits only (no spaces, dashes, or other
    separators).  The caller is responsible for stripping formatting before
    calling this function.

    Algorithm (ISO/IEC 7812):
      1. Starting from the rightmost digit, double every second digit.
      2. If doubling produces a value > 9, subtract 9.
      3. Sum all digits (original + doubled).
      4. The number is valid iff the total is divisible by 10.
    """
    total = 0
    double = False
    for ch in reversed(digits):
        if not ch.isdigit():
            # Caller should have stripped separators; bail defensively.
            return False
        n = int(ch)
        if double:
            n *= 2
            if n > 9:
                n -= 9
        total += n
        double = not double
    return total % 10 == 0


def _luhn_filter(matched_text: str) -> bool:
    """Post-match validator for CREDIT_CARD candidates.

    Strips spaces and dashes (common card-number separators), then runs
    the Luhn checksum.  Returns True only for digit strings that pass.
    """
    digits = "".join(ch for ch in matched_text if ch.isdigit())
    if len(digits) < 13 or len(digits) > 19:
        return False
    return _luhn_valid(digits)


# Per-label post-match validators.  A candidate that matches the regex for
# its label is accepted only when the corresponding validator returns True.
# Labels absent from this dict have no secondary gate (regex match suffices).
_POST_MATCH_VALIDATORS: dict[str, Callable[[str], bool]] = {
    "CREDIT_CARD": _luhn_filter,
}


def check_pii(text: str) -> list[str]:
    """Scan text for PII / secret patterns (canonical + context-gated).

    Returns:
        Sorted list of distinct pattern labels that matched (empty if clean).
        For positional spans and confidence, use ``find_pii_spans``.
    """
    return sorted({span.label for span in find_pii_spans(text)})


# ---------------------------------------------------------------------------
# Provenance-Aware Redaction (pii_mode = "redact")
# ---------------------------------------------------------------------------
#
# "redact" is the honest middle ground between "off" (surface all PII) and
# "block" (suppress the whole response). Every PII span in the output is checked
# for *provenance*: a span that traces to the user's own loaded documents or
# messages is surfaced unchanged; a span that cannot be traced — model-
# hallucinated or prompt-injected — is replaced with a visible marker. The
# response is still delivered, and every decision is recorded in an audit trail.
#
# This inverts conventional enterprise redaction (which hides the user's data to
# protect third parties): here the user owns the data, so what gets redacted is
# the content that is NOT verifiably theirs — which also catches hallucinated
# and injected PII. See docs/governance/ for the rationale and standards map.


# Detection confidence levels — mirrors the Microsoft Presidio analyzer model,
# where every recognizer result carries a graded score rather than a binary
# flag.
#   HIGH   — a canonical full-format pattern match (e.g. a 10-digit phone).
#   MEDIUM — a context-gated match: a fragment flagged because a PII-announcing
#            word sits next to it (e.g. "Phone Number: 555-0198").
CONFIDENCE_HIGH: float = 0.9
CONFIDENCE_MEDIUM: float = 0.6


@dataclass(frozen=True)
class PIIMatch:
    """A located PII / secret span within generated text."""

    label: str
    """Pattern label (e.g. 'PHONE_US')."""

    text: str
    """The matched substring."""

    start: int
    """Start offset in the source text."""

    end: int
    """End offset (exclusive) in the source text."""

    confidence: float = CONFIDENCE_HIGH
    """Detection confidence — CONFIDENCE_HIGH for a canonical pattern match,
    CONFIDENCE_MEDIUM for a context-gated fragment match."""


# Human-readable entity names for redaction markers — shown to the user.
_FRIENDLY_PII_NAMES: dict[str, str] = {
    "SSN": "Social Security number",
    "CREDIT_CARD": "credit card number",
    "EMAIL": "email address",
    "PHONE_US": "phone number",
    "PHONE_LOCAL": "phone number",
    "AREA_CODE": "area code",
    "ACCOUNT_NUMBER": "account number",
    "IPV4": "IP address",
    "AWS_KEY": "access key",
    "HEX_SECRET": "secret",
    "PASSPORT_US": "passport number",
    "BEARER_TOKEN": "access token",
}


# ---------------------------------------------------------------------------
# Context-gated recognizers — catch PII that canonical patterns miss because it
# has been *fragmented*. A phone number disclosed as "Area Code: 212" then
# "Phone Number: 555-0198" never forms a 10-digit string, so the canonical
# PHONE_US pattern cannot see it. These recognizers flag a number when a
# PII-announcing word sits next to it, and carry CONFIDENCE_MEDIUM.
#
# Precision discipline: a bare number with NO PII-announcing word nearby is not
# flagged — there is no false-positive flood. The gap between the context word
# and the number excludes digits (so the captured group is the first number
# after the word) but allows Markdown punctuation such as "**".
# ---------------------------------------------------------------------------

# Characters permitted between a context word and the number it announces.
_CTX_GAP: str = r"[A-Za-z\s:#*().,/_-]{0,20}?"

_CONTEXT_RECOGNIZERS: list[tuple[str, re.Pattern[str]]] = [
    # 7-digit local phone number near a phone-announcing word.
    ("PHONE_LOCAL", re.compile(
        r"(?i)\b(?:phone|telephone|mobile|fax|tel)\b"
        + _CTX_GAP
        + r"\b(\d{3}[-.\s]?\d{4})\b"
    )),
    # 3-digit area code — gated by the specific phrase "area code".
    ("AREA_CODE", re.compile(
        r"(?i)\barea\s*code\b" + _CTX_GAP + r"\b(\d{3})\b"
    )),
    # 5+ digit account number near the word "account".
    ("ACCOUNT_NUMBER", re.compile(
        r"(?i)\baccount\b(?:\s*(?:number|no\.?|#))?"
        + _CTX_GAP
        + r"\b(\d{5,})\b"
    )),
]


def find_pii_spans(text: str) -> list[PIIMatch]:
    """Locate PII / secret spans with their positions and confidence.

    Runs two recognizer layers:
      * canonical patterns (``_PII_PATTERNS``) — full-format matches, HIGH
        confidence;
      * context-gated recognizers (``_CONTEXT_RECOGNIZERS``) — fragments
        flagged by a neighbouring PII-announcing word, MEDIUM confidence.

    For ``PASSPORT_US`` and the context recognizers — patterns with a capture
    group — the identifier itself (group 1) is located, not the surrounding
    context word.

    Args:
        text: Text to scan.

    Returns:
        List of PIIMatch spans (may overlap; callers resolve overlaps).
    """
    spans: list[PIIMatch] = []
    # Layer 1 — canonical full-format patterns (high confidence).
    for label, pattern in _PII_PATTERNS:
        for match in pattern.finditer(text):
            group = 1 if pattern.groups >= 1 else 0
            start, end = match.span(group)
            if start < 0 or end <= start:
                continue
            matched_text = text[start:end]
            # Apply per-label post-match validator if one is registered.
            # For CREDIT_CARD this is a Luhn checksum; other labels have
            # no secondary gate so the regex match alone suffices.
            validator = _POST_MATCH_VALIDATORS.get(label)
            if validator is not None and not validator(matched_text):
                continue
            spans.append(
                PIIMatch(
                    label=label,
                    text=matched_text,
                    start=start,
                    end=end,
                    confidence=CONFIDENCE_HIGH,
                )
            )
    # Layer 2 — context-gated recognizers (medium confidence). Group 1 is the
    # PII fragment; the context word that triggered it is not redacted.
    for label, pattern in _CONTEXT_RECOGNIZERS:
        for match in pattern.finditer(text):
            start, end = match.span(1)
            if start < 0 or end <= start:
                continue
            spans.append(
                PIIMatch(
                    label=label,
                    text=text[start:end],
                    start=start,
                    end=end,
                    confidence=CONFIDENCE_MEDIUM,
                )
            )
    return spans


def _normalize_for_provenance(value: str) -> str:
    """Reduce text to a lowercase alphanumeric-only form for provenance matching.

    Strips formatting (spaces, dashes, parentheses, dots, '@') so a phone number
    or email matches its source regardless of how the model reformatted it —
    e.g. '(555) 123-4567' and '555-123-4567' both normalize to '5551234567'.
    """
    return "".join(ch.lower() for ch in value if ch.isalnum())


def _redaction_marker(label: str) -> str:
    """Build the visible, honest redaction marker shown in place of a PII span."""
    friendly = _FRIENDLY_PII_NAMES.get(label, "personal detail")
    return f"[{friendly} withheld — not found in your documents or messages]"


def _apply_provenance_redaction(
    text: str,
    spans: list[PIIMatch],
    trusted_source: str,
) -> tuple[str, list[dict[str, Any]]]:
    """Redact PII spans that cannot be traced to trusted (user-provided) content.

    A span is *surfaced* (left in place) when its normalized form appears in
    ``trusted_source`` — the user's own loaded documents and messages. A span
    that cannot be traced is *redacted* with a visible marker.

    Args:
        text: The generated text.
        spans: PII spans located by ``find_pii_spans`` (may overlap).
        trusted_source: Concatenated user-provided content for provenance.

    Returns:
        (rewritten_text, audit) — audit is one record per decision, in document
        order. Each record carries the label, span, action and reason; it never
        carries the raw PII value (an audit trail must not itself leak PII).
    """
    if not spans:
        return text, []

    norm_source = _normalize_for_provenance(trusted_source)

    # Resolve overlapping spans: earliest start wins, ties broken by longer
    # span, then by higher confidence.
    ordered = sorted(
        spans, key=lambda s: (s.start, -(s.end - s.start), -s.confidence)
    )
    chosen: list[PIIMatch] = []
    last_end = -1
    for span in ordered:
        if span.start >= last_end:
            chosen.append(span)
            last_end = span.end

    audit: list[dict[str, Any]] = []
    result = text
    # Rewrite right-to-left so earlier spans' offsets remain valid.
    for span in sorted(chosen, key=lambda s: s.start, reverse=True):
        norm_pii = _normalize_for_provenance(span.text)
        trusted = bool(norm_pii) and norm_pii in norm_source
        audit.append(
            {
                "label": span.label,
                "span": [span.start, span.end],
                "confidence": span.confidence,
                "action": "surfaced" if trusted else "redacted",
                "reason": (
                    "traced to user-provided content"
                    if trusted
                    else "not found in user-provided content"
                ),
            }
        )
        if not trusted:
            result = (
                result[: span.start]
                + _redaction_marker(span.label)
                + result[span.end :]
            )

    audit.reverse()  # restore document order
    return result, audit


# ---------------------------------------------------------------------------
# Delimiter Echo Detection (Context Spotlighting)
# ---------------------------------------------------------------------------

# All delimiters that must never appear in user-facing output.
_SPOTLIGHTING_DELIMITERS: list[str] = [
    CONTEXT_BEGIN,
    CONTEXT_END,
    SYSTEM_BEGIN,
    SYSTEM_END,
]


def check_delimiter_echo(text: str) -> list[str]:
    """Detect Context Spotlighting delimiters leaked into generated output.

    If any delimiter appears in the model output, it means the model is
    echoing internal framing tokens — a prompt injection signal.

    Args:
        text: Generated text to scan.

    Returns:
        List of delimiter strings found (empty if clean).
    """
    found: list[str] = []
    for delim in _SPOTLIGHTING_DELIMITERS:
        if delim in text:
            found.append(delim)
    return found


# ---------------------------------------------------------------------------
# Tool-Call Allowlist
# ---------------------------------------------------------------------------

# Deterministic set of authorized tool-call identifiers that may appear in
# generated output. Any tool-call reference NOT in this set is a violation.
#
# SECURITY NOTE (audit Domain 5, 2026-06-03): This list is intentionally
# limited to the FOUR tools that are actually implemented and callable via
# tools._REGISTRY. Unbuilt tools (search, code_agent, cleaner,
# substrate_query, calendar_read, calendar_write, note_create, note_search,
# health_log, smart_home_control) have been removed. Retaining unbuilt tool
# names in the allowlist pre-approved a side-effecting surface that does not
# exist — the validator would pass output referencing calendar_write,
# smart_home_control, etc. without any corresponding execution gate.
# When a new tool is implemented in tools._REGISTRY, add it here.
TOOL_CALL_ALLOWLIST: frozenset[str] = frozenset({
    # v1 agentic tool-call loop — first implemented tool.
    "get_current_time",
    # v2 (2026-06-02) — zero-arg date/time companions + safe arithmetic.
    "get_current_date",
    "get_day_of_week",
    "calculate",
    # UC-010 Local Generative Imaging (ADR-033). In tools._REGISTRY as a GUARDED
    # tool; the in-loop form is a never-raising directive shim (the heavy
    # generate runs in the AO IMAGE_GEN_REQUEST handler off /imagine).
    "generate_image",
    # #719 GUARDED retrieval tools. Both are runner-seam delegates in
    # tools._REGISTRY: search_knowledge is LIVE (the AO registers its
    # knowledge-bank runner at start; results ground as UNTRUSTED_KNOWLEDGE);
    # web_search is STRUCTURALLY DORMANT (no production code registers a
    # runner — it returns a deterministic disabled notice; the egress door +
    # empty egress allowlist independently deny any actual network reach).
    # Listing web_search here is what routes a model emission to the layered
    # refusal (Layer-3 lock -> #570 dispatch adjudication -> disabled notice)
    # instead of leaving raw <tool_call> text as the user-visible answer.
    "search_knowledge",
    "web_search",
})
"""Authorized tool-call identifiers. Any reference outside this set is blocked.

The allowed set must exactly mirror tools._REGISTRY — no more, no less.
"""

# Pattern to detect tool-call references in generated text.
# Matches: <tool_call>name</tool_call> or [TOOL: name] or {"tool": "name"}.
# The Qwen3 NATIVE JSON form <tool_call>{"name": "x", ...}</tool_call> (#718)
# is handled separately in check_tool_calls by json-parsing every <tool_call>
# tag payload — a regex cannot robustly extract the name from attacker-
# reorderable JSON, and without native-form coverage an unknown-tool call in
# the trained format would escape Stage-4 detection entirely (governance
# parity with the legacy format).
_TOOL_CALL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"<tool_call>\s*(\w+)\s*</tool_call>", re.IGNORECASE),
    re.compile(r"\[TOOL:\s*(\w+)\s*\]", re.IGNORECASE),
    re.compile(r'"tool"\s*:\s*"(\w+)"'),
    re.compile(r"'tool'\s*:\s*'(\w+)'"),
]

# Tag-payload extractor for the native-JSON leg of check_tool_calls (#718).
# Mirrors tools._TOOL_CALL_TAG_PATTERN (non-greedy DOTALL, case-insensitive).
_TOOL_CALL_TAG_RE: re.Pattern[str] = re.compile(
    r"<tool_call>\s*(.*?)\s*</tool_call>", re.IGNORECASE | re.DOTALL
)

# Fallback name-reference scan inside a MALFORMED JSON payload: broken JSON
# cannot be parsed for its true name, so any "name": "x" string it carries is
# treated as a tool reference (fail-closed — an attacker cannot dodge the
# check by breaking their own JSON). Anchored inside the tag payload only, so
# ordinary JSON in prose (e.g. {"name": "John"}) never false-positives.
_JSON_NAME_REF_RE: re.Pattern[str] = re.compile(r'"name"\s*:\s*"(\w+)"')


def _native_json_tool_names(payload: str) -> list[str]:
    """Extract tool-name references from a <tool_call> JSON payload (#718).

    A payload that parses as a JSON object yields its ``name`` value (the
    Qwen3 native form). A payload that starts like JSON but does NOT parse is
    scanned for ``"name": "x"`` references instead — fail-closed: malforming
    the JSON is not an evasion. Non-JSON payloads (e.g. the RETIRED legacy
    NAME shape, which the parser no longer accepts but Stage-4 still detects)
    are handled by _TOOL_CALL_PATTERNS and yield nothing here.
    """
    if not payload.startswith("{"):
        return []
    try:
        parsed = json.loads(payload)
    except (json.JSONDecodeError, ValueError):
        return [m.group(1).lower() for m in _JSON_NAME_REF_RE.finditer(payload)]
    if isinstance(parsed, dict):
        name = parsed.get("name")
        if isinstance(name, str) and re.fullmatch(r"\w+", name):
            return [name.lower()]
        # A dict payload with a missing/malformed name still fail-closes to
        # the reference scan (e.g. {"name": {"evil": 1}} carries no \w+ name).
        return [m.group(1).lower() for m in _JSON_NAME_REF_RE.finditer(payload)]
    return [m.group(1).lower() for m in _JSON_NAME_REF_RE.finditer(payload)]


def check_tool_calls(text: str, allowlist: frozenset[str] | None = None) -> list[str]:
    """Validate tool-call references against the deterministic allowlist.

    Scans generated text for tool-call patterns and verifies each referenced
    tool name is in the allowlist. Unknown tool names are violations.

    Args:
        text: Generated text to scan.
        allowlist: Override allowlist (defaults to ``TOOL_CALL_ALLOWLIST``).

    Returns:
        List of unauthorized tool names found (empty if all authorized).
    """
    allowed = allowlist if allowlist is not None else TOOL_CALL_ALLOWLIST
    unauthorized: list[str] = []
    for pattern in _TOOL_CALL_PATTERNS:
        for match in pattern.finditer(text):
            tool_name = match.group(1).lower()
            if tool_name not in allowed:
                unauthorized.append(tool_name)
    # #718 — Qwen3 native JSON form: json-parse every <tool_call> payload and
    # check the referenced name(s) against the allowlist (see
    # _native_json_tool_names for the fail-closed malformed-JSON handling).
    for match in _TOOL_CALL_TAG_RE.finditer(text):
        for tool_name in _native_json_tool_names(match.group(1)):
            if tool_name not in allowed:
                unauthorized.append(tool_name)
    return unauthorized


# ---------------------------------------------------------------------------
# Leakage Detection (Cosine Similarity)
# ---------------------------------------------------------------------------


class LeakageDetector:
    """Embedding-based retrieval leakage detector.

    Loads the bge-small-en-v1.5 ONNX model (same as Semantic Router) on the
    configured device and computes pairwise cosine similarity between
    generated text and retrieved RAG chunks. If the maximum similarity
    exceeds the threshold, the output is flagged as potential verbatim
    leakage.

    Lifecycle:
      1. ``__init__``: Configure model path and threshold.
      2. ``load_model()``: Load ONNX model + tokenizer.
      3. ``check_leakage()``: Embed + compute similarity.
      4. ``unload()``: Release resources.

    Fail-Closed: If the model is not loaded, ``check_leakage()`` returns 1.0
    (maximum leakage score) to prevent bypass.

    Device offload (Vikunja #720): ``device`` selects the inference device
    for the embedding model.  ``"CPU"`` (the default) is today's ONNX Runtime
    CPU path, byte-identical to the pre-#720 behaviour.  ``"NPU"`` / ``"GPU"``
    compile the SAME fp16 ONNX file through OpenVINO on that device — a device
    knob, NOT a precision knob (the weights and the numerics pipeline are
    unchanged; only the executor moves).  The offload is FAIL-SOFT by design:
    an OpenVINO compile failure logs a deterministic ``EMBED_OFFLOAD_FALLBACK``
    fingerprint and falls back to the ONNX Runtime CPU path — an offload
    optimisation must never refuse-to-start the AO (contrast the fail-CLOSED
    posture of ``check_leakage`` itself, which is a security control).
    """

    # Static token windows compiled for devices that cannot handle dynamic
    # shapes (the NPU plugin requires bounded shapes). 128 = the calibrated
    # PGOV Stage-5 leakage window; 512 = the document/knowledge window
    # (bge-small's native maximum).
    _OFFLOAD_WINDOWS: tuple[int, ...] = (128, 512)

    def __init__(
        self,
        model_path: str | None = None,
        max_input_length: int = 128,
        device: str = "CPU",
    ) -> None:
        from shared.constants import SEMANTIC_ROUTER_ONNX_PATH

        self._model_path = model_path or SEMANTIC_ROUTER_ONNX_PATH
        self._max_input_length = max_input_length
        self._device = (device or "CPU").strip().upper() or "CPU"
        self._session: Any = None
        self._tokenizer: Any = None
        self._input_names: list[str] = []
        self._loaded = False
        # OpenVINO offload state (#720). ``_ov_compiled`` maps a static token
        # window to a compiled model (key 0 = one dynamic-shape model).
        self._ov_compiled: dict[int, Any] = {}
        self._ov_input_names: list[str] = []
        self._active_device: str = "CPU"
        self._backend: str = "ort-cpu"

    @property
    def loaded(self) -> bool:
        """Whether the embedding model is loaded."""
        return self._loaded

    @property
    def active_device(self) -> str:
        """The device actually serving embeddings ("CPU" until loaded)."""
        return self._active_device

    @property
    def backend(self) -> str:
        """The active inference backend: ``"ort-cpu"`` or ``"openvino"``."""
        return self._backend

    def load_model(self) -> bool:
        """Load the bge-small-en-v1.5 ONNX model for leakage detection.

        Device "CPU" (default construction) runs ONNX Runtime CPU execution;
        "NPU"/"GPU" compile the same ONNX via OpenVINO on that device,
        falling SOFT back to the CPU path on any compile failure (#720).

        Performance note (Vikunja #553, resolved 2026-06-04): timing this method
        in a *standalone* process shows ~5-8s, but ~92% of that is the one-time
        ``from transformers import AutoTokenizer`` below — which ``gpu_inference``
        already imports at module load for the 14B, before the Substrate builds.
        In the running AO the marginal cost here is ~0.3s (paid at boot inside the
        AO-entrypoint slice). Do NOT "optimize" this load based on isolated
        profiling; the tax is a measurement artifact. See PERFORMANCE_LOG.md
        (2026-06-04 substrate entry), BUILD_JOURNAL lesson 36, and
        tests/substrate_benchmark/ to re-measure.

        Returns:
            True if loaded successfully, False on error (Fail-Closed).
        """
        try:
            import onnxruntime as ort
            from transformers import AutoTokenizer

            model_dir = str(Path(self._model_path).parent)

            # Local-only tokenizer load: never reach the HF Hub (#633). The
            # runtime is air-gapped and the files are on disk;
            # trust_remote_code=False refuses any repo-carried code execution.
            self._tokenizer = AutoTokenizer.from_pretrained(
                model_dir, local_files_only=True, trust_remote_code=False
            )

            # ── OpenVINO device offload (#720, fail-soft) ────────────────
            # A non-CPU device compiles the SAME fp16 ONNX through OpenVINO.
            # ANY failure here falls back to the ONNX Runtime CPU path below
            # with a deterministic fingerprint — never a refused start.
            if self._device != "CPU":
                if self._try_load_openvino(self._device):
                    self._backend = "openvino"
                    self._active_device = self._device
                    probe = self._embed(["probe"])
                    if probe.shape[1] != 384:
                        logger.error(
                            "Unexpected embedding dim %d (expected 384).",
                            probe.shape[1],
                        )
                        return False
                    self._loaded = True
                    logger.info(
                        "LeakageDetector loaded (OpenVINO %s): model=%s",
                        self._active_device,
                        Path(self._model_path).name,
                    )
                    return True
                logger.warning(
                    "EMBED_OFFLOAD_FALLBACK device=%s -> CPU "
                    "(OpenVINO compile failed; ONNX Runtime CPU path engaged)",
                    self._device,
                )

            sess_options = ort.SessionOptions()
            sess_options.inter_op_num_threads = 1
            sess_options.intra_op_num_threads = 2  # Less aggressive than Router
            sess_options.graph_optimization_level = (
                ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            )

            self._session = ort.InferenceSession(
                self._model_path,
                sess_options=sess_options,
                providers=["CPUExecutionProvider"],
            )
            self._input_names = [inp.name for inp in self._session.get_inputs()]
            self._backend = "ort-cpu"
            self._active_device = "CPU"

            # Verify model loads with a probe
            probe = self._embed(["probe"])
            if probe.shape[1] != 384:
                logger.error(
                    "Unexpected embedding dim %d (expected 384).", probe.shape[1]
                )
                return False

            self._loaded = True
            logger.info(
                "LeakageDetector loaded: model=%s",
                Path(self._model_path).name,
            )
            return True

        except Exception as exc:
            logger.error("LeakageDetector load_model failed (Fail-Closed): %s", exc)
            self._loaded = False
            return False

    def unload(self) -> None:
        """Release model resources."""
        self._session = None
        self._tokenizer = None
        self._input_names = []
        self._ov_compiled = {}
        self._ov_input_names = []
        self._active_device = "CPU"
        self._backend = "ort-cpu"
        self._loaded = False

    def _try_load_openvino(self, device: str) -> bool:
        """Compile the embedding model on *device* via OpenVINO (fail-soft).

        Tries a dynamic-shape compile first (works on GPU/CPU plugins); if the
        plugin rejects dynamic shapes (the NPU requires bounded shapes), falls
        back to one static compile per :data:`_OFFLOAD_WINDOWS` token window —
        texts are then padded to the window and inferred one at a time.

        Returns:
            True when a usable compiled model exists for every needed window.
            False on ANY failure (the caller falls back to ONNX Runtime CPU
            with a deterministic ``EMBED_OFFLOAD_FALLBACK`` fingerprint).
        """
        try:
            import os  # noqa: PLC0415

            import openvino as ov  # noqa: PLC0415 — optional offload path

            core = ov.Core()
            # Compiled-blob cache (fail-soft): cuts the NPU static compile
            # from ~12 s (cold) to ~2.5 s (warm) on Lunar Lake, measured
            # 2026-07-02.  The 14B deliberately runs CACHE_DIR="" (its 9 GB
            # blob cold-reads as slowly as a fresh compile — see the 2026-06-03
            # whisper cache probe); this model is 128 MB, where the cache is a
            # clear win.  Blobs derive from the public model weights only —
            # no user data is cached.
            local_app_data = os.environ.get("LOCALAPPDATA", "")
            if local_app_data:
                try:
                    cache_dir = (
                        Path(local_app_data) / "BlarAI" / "ov_cache" / "embeddings"
                    )
                    cache_dir.mkdir(parents=True, exist_ok=True)
                    core.set_property({"CACHE_DIR": str(cache_dir)})
                except Exception as cache_exc:  # noqa: BLE001 — cache is optional
                    logger.info(
                        "Embedding offload: compile cache unavailable (%s); "
                        "compiling uncached.",
                        type(cache_exc).__name__,
                    )
            model = core.read_model(self._model_path)
            self._ov_input_names = [i.get_any_name() for i in model.inputs]

            # The NPU plugin is static-shape only — probing it with a dynamic
            # compile floods the driver log with ERROR lines and wastes ~1 s,
            # so it goes straight to the static windows.  Other devices try
            # dynamic first (one compiled model, no padding overhead).
            if device != "NPU":
                try:
                    compiled = core.compile_model(model, device)
                    self._ov_compiled = {0: compiled}
                    logger.info(
                        "Embedding offload: dynamic-shape compile OK on %s.",
                        device,
                    )
                    return True
                except Exception as dyn_exc:  # noqa: BLE001 — capability probe
                    logger.info(
                        "Embedding offload: dynamic compile unavailable on %s "
                        "(%s); trying static windows %s.",
                        device,
                        type(dyn_exc).__name__,
                        self._OFFLOAD_WINDOWS,
                    )

            compiled_by_window: dict[int, Any] = {}
            for window in self._OFFLOAD_WINDOWS:
                static = core.read_model(self._model_path)
                static.reshape(
                    {i.get_any_name(): [1, window] for i in static.inputs}
                )
                compiled_by_window[window] = core.compile_model(static, device)
            self._ov_compiled = compiled_by_window
            logger.info(
                "Embedding offload: static compile OK on %s (windows %s).",
                device,
                self._OFFLOAD_WINDOWS,
            )
            return True
        except Exception as exc:  # noqa: BLE001 — fail-soft by design (#720)
            logger.warning(
                "EMBED_OFFLOAD_FALLBACK device=%s error=%s: %s",
                device,
                type(exc).__name__,
                exc,
            )
            self._ov_compiled = {}
            self._ov_input_names = []
            return False

    def _embed(self, texts: list[str]) -> Any:
        """Embed texts into L2-normalized 384-dim vectors (leakage path).

        Mirrors SemanticRouter._embed_raw: tokenize → ONNX inference →
        mean pool → L2 normalize.  Truncates at ``self._max_input_length``
        (128 tokens by default) — the window the PGOV Stage-5 leakage
        thresholds are calibrated at.  This path MUST stay byte-identical;
        document-scale embedding uses :meth:`embed_documents` instead.

        Args:
            texts: Strings to embed.

        Returns:
            numpy array of shape (len(texts), 384).

        Raises:
            RuntimeError: If model is not loaded.
        """
        return self._embed_at(texts, self._max_input_length)

    def embed_documents(
        self, texts: list[str], max_length: int = 512
    ) -> Any:
        """Embed texts at a document-scale token window (knowledge bank, UC-002).

        Reuses the SAME loaded ONNX session + tokenizer as the leakage path but
        truncates at *max_length* (default 512 — bge-small-en-v1.5's native
        maximum) so a full 2048-char knowledge chunk informs its vector instead
        of only its first ~quarter.  Deliberately a SEPARATE method: the
        leakage path's 128-token default (``_embed``) is untouched — PGOV
        Stage-5 thresholds are calibrated at 128 and byte-identical behaviour
        there is a regression requirement.

        Args:
            texts: Strings to embed.
            max_length: Token truncation window (bge-small supports up to 512).

        Returns:
            numpy array of shape (len(texts), 384), L2-normalised float32.

        Raises:
            RuntimeError: If model is not loaded.
        """
        return self._embed_at(texts, max_length)

    def _embed_at(self, texts: list[str], max_length: int) -> Any:
        """Shared embed implementation: tokenize → ONNX → mean pool → L2 norm."""
        import numpy as np

        if self._backend == "openvino" and self._ov_compiled:
            return self._embed_ov(texts, max_length)

        if self._tokenizer is None or self._session is None:
            msg = "LeakageDetector: model not loaded."
            raise RuntimeError(msg)

        tokens = self._tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=max_length,
            return_tensors="np",
        )

        feed = {
            k: v.astype(np.int64) for k, v in tokens.items() if k in self._input_names
        }
        outputs = self._session.run(None, feed)

        last_hidden = outputs[0]  # (batch, seq_len, dim)
        mask = tokens["attention_mask"][..., np.newaxis]
        summed = (last_hidden * mask).sum(axis=1)
        counts = mask.sum(axis=1).clip(min=1e-9)
        embeddings = summed / counts

        norms = np.linalg.norm(embeddings, axis=1, keepdims=True).clip(min=1e-9)
        return (embeddings / norms).astype(np.float32)

    def _embed_ov(self, texts: list[str], max_length: int) -> Any:
        """OpenVINO embed path (#720): tokenize → infer → mean pool → L2 norm.

        Numerically the same pipeline as the ONNX Runtime path — same fp16
        weights, same mean pooling and L2 normalisation in numpy; only the
        executor differs.  For static-shape devices (NPU) texts are padded to
        the selected token window and inferred one at a time (batch dimension
        is fixed at 1); a dynamic-shape compile (key 0) batches like ORT.

        Raises:
            RuntimeError: If the tokenizer or compiled model is missing.
        """
        import numpy as np

        if self._tokenizer is None or not self._ov_compiled:
            msg = "LeakageDetector: model not loaded."
            raise RuntimeError(msg)

        dynamic = 0 in self._ov_compiled
        if dynamic:
            compiled = self._ov_compiled[0]
            tokens = self._tokenizer(
                texts,
                padding=True,
                truncation=True,
                max_length=max_length,
                return_tensors="np",
            )
        else:
            # Smallest static window that covers the request, else the largest.
            window = max(self._ov_compiled)
            for candidate in sorted(self._ov_compiled):
                if candidate >= max_length:
                    window = candidate
                    break
            compiled = self._ov_compiled[window]
            tokens = self._tokenizer(
                texts,
                padding="max_length",
                truncation=True,
                max_length=window,
                return_tensors="np",
            )

        feed_all = {
            k: v.astype(np.int64)
            for k, v in tokens.items()
            if k in self._ov_input_names
        }
        mask_full = tokens["attention_mask"][..., np.newaxis]

        if dynamic:
            outputs = compiled(feed_all)
            last_hidden = outputs[compiled.output(0)]
            mask = mask_full
        else:
            rows: list[Any] = []
            request = compiled.create_infer_request()
            for i in range(len(texts)):
                feed = {k: v[i : i + 1] for k, v in feed_all.items()}
                out = request.infer(feed)
                rows.append(np.asarray(next(iter(out.values()))))
            last_hidden = np.concatenate(rows, axis=0)
            mask = mask_full

        summed = (last_hidden * mask).sum(axis=1)
        counts = mask.sum(axis=1).clip(min=1e-9)
        embeddings = summed / counts

        norms = np.linalg.norm(embeddings, axis=1, keepdims=True).clip(min=1e-9)
        return (embeddings / norms).astype(np.float32)

    def check_leakage(
        self,
        generated_text: str,
        retrieved_chunks: list[str],
        threshold: float = 0.85,
    ) -> float:
        """Compute max cosine similarity between generated text and chunks.

        Embeds the generated text and each retrieved chunk, then computes
        pairwise cosine similarity (dot product of L2-normalized vectors).
        Returns the maximum similarity score.

        Fail-Closed: If the model is not loaded, returns 1.0 (maximum
        leakage) to prevent leakage bypass via model loading failure.

        Args:
            generated_text: Model output to check.
            retrieved_chunks: RAG-retrieved context chunks.
            threshold: Not used in computation, but kept for API compat.

        Returns:
            Maximum cosine similarity (0.0 to 1.0). 1.0 if Fail-Closed.
        """
        if not generated_text or not retrieved_chunks:
            return 0.0

        if not self._loaded:
            logger.warning(
                "LeakageDetector not loaded — Fail-Closed: returning 1.0"
            )
            return 1.0

        try:
            import numpy as np

            gen_emb = self._embed([generated_text])  # (1, 384)
            chunk_embs = self._embed(retrieved_chunks)  # (N, 384)

            # Cosine similarity via dot product (vectors are L2-normalized)
            similarities = (chunk_embs @ gen_emb.T).flatten()  # (N,)
            return float(np.max(similarities))

        except Exception as exc:
            logger.error(
                "LeakageDetector.check_leakage error (Fail-Closed): %s", exc
            )
            return 1.0


# ---------------------------------------------------------------------------
# Module-Level Leakage Function (Backward-Compatible)
# ---------------------------------------------------------------------------

# Singleton detector — initialized lazily on first use.
_detector: LeakageDetector | None = None


def _get_detector(device: str | None = None) -> LeakageDetector:
    """Get or lazily create the singleton LeakageDetector.

    Args:
        device: Inference device for the embedding model (#720) — only
            honoured when the singleton is CREATED by this call; an existing
            singleton is returned unchanged (its device was fixed at
            construction).  ``None`` keeps the CPU default.
    """
    global _detector  # noqa: PLW0603
    if _detector is None:
        _detector = LeakageDetector(device=device or "CPU")
    return _detector


def set_leakage_detector(detector: LeakageDetector) -> None:
    """Inject a LeakageDetector instance (for testing or pre-configured use)."""
    global _detector  # noqa: PLW0603
    _detector = detector


def check_leakage(
    generated_text: str,
    retrieved_chunks: list[str],
    threshold: float = 0.85,
) -> float:
    """Compute maximum cosine similarity between generated text and chunks.

    Uses the singleton LeakageDetector. If the detector is not loaded,
    returns 1.0 (Fail-Closed).

    Args:
        generated_text: The model-generated response.
        retrieved_chunks: RAG-retrieved context chunks.
        threshold: Cosine similarity threshold (passed through).

    Returns:
        Maximum cosine similarity score (0.0 to 1.0). 1.0 if Fail-Closed.
    """
    detector = _get_detector()
    return detector.check_leakage(generated_text, retrieved_chunks, threshold)


# ---------------------------------------------------------------------------
# Full PGOV Pipeline
# ---------------------------------------------------------------------------


def validate_output(
    generated_text: str,
    token_count: int,
    max_tokens: int,
    retrieved_chunks: list[str] | None = None,
    cosine_threshold: float = 0.85,
    tool_allowlist: frozenset[str] | None = None,
    pii_mode: str = "block",
    trusted_source: str = "",
) -> PGOVResult:
    """Run the full 6-stage PGOV pipeline on generated output.

    Stages:
      1. Token budget check — reject if token_count > max_tokens.
      2. PII / secret check — reject if any pattern matches.
      3. Delimiter echo check — reject if spotlighting delimiters leak.
      4. Tool-call allowlist — reject if unauthorized tool references found.
      5. Leakage check — reject if cosine similarity ≥ threshold.
      6. Final approval gate.

    Args:
        generated_text: The raw model output.
        token_count: Number of tokens in the output.
        max_tokens: Circuit breaker token cap.
        retrieved_chunks: RAG chunks to check for leakage (optional).
        cosine_threshold: Leakage detection threshold.
        tool_allowlist: Override tool-call allowlist (defaults to module constant).
        pii_mode: PII-stage policy. "off" skips PII detection entirely;
            "block" (default) suppresses any response containing PII;
            "redact" surfaces PII traced to the user's own documents/messages
            and replaces untraceable PII with a visible marker.
        trusted_source: User-provided content (loaded documents + user
            messages) used for provenance checks in "redact" mode. Ignored by
            the other modes.

    Returns:
        PGOVResult. Fail-Closed: any error returns unapproved result.
    """
    try:
        return _run_pipeline(
            generated_text,
            token_count,
            max_tokens,
            retrieved_chunks,
            cosine_threshold,
            tool_allowlist,
            pii_mode,
            trusted_source,
        )
    except Exception as exc:
        logger.error("PGOV pipeline error (Fail-Closed): %s", exc)
        return PGOVResult(
            approved=False,
            original_text=generated_text,
            sanitized_text=FALLBACK_MESSAGE,
            leakage_score=0.0,
            pii_detected=False,
            token_count_valid=False,
            delimiter_echo=False,
            tool_call_violation=False,
            violations=[f"PGOV internal error: {exc}"],
        )


def _run_pipeline(
    generated_text: str,
    token_count: int,
    max_tokens: int,
    retrieved_chunks: list[str] | None,
    cosine_threshold: float,
    tool_allowlist: frozenset[str] | None,
    pii_mode: str,
    trusted_source: str = "",
) -> PGOVResult:
    """Internal pipeline implementation (wrapped by validate_output for Fail-Closed)."""
    violations: list[str] = []

    # Stage 1: Token budget check
    token_valid = token_count <= max_tokens
    if not token_valid:
        violations.append(f"Token count {token_count} exceeds cap {max_tokens}")

    # Stage 2: PII / secret check — governed by the pii_mode policy.
    #   "off"    skips detection entirely (correct posture for a local,
    #            single-user assistant managing the user's own data).
    #   "block"  detects; any PII suppresses the whole response.
    #   "redact" detects; PII traced to the user's own documents/messages is
    #            surfaced, untraceable PII is redacted in place (honest,
    #            visible, audited) and the response is still delivered.
    pii_redactions: list[dict[str, Any]] = []
    redacted_text = generated_text
    if pii_mode == "off":
        pii_matches: list[str] = []
    elif pii_mode == "redact":
        spans = find_pii_spans(generated_text)
        pii_matches = sorted({s.label for s in spans})
        redacted_text, pii_redactions = _apply_provenance_redaction(
            generated_text, spans, trusted_source
        )
    else:  # "block"
        pii_matches = check_pii(generated_text)
    pii_detected = len(pii_matches) > 0
    if pii_detected and pii_mode != "redact":
        violations.append(f"PII patterns detected: {pii_matches}")
    if pii_mode == "redact" and pii_redactions:
        _n_redacted = sum(1 for r in pii_redactions if r["action"] == "redacted")
        logger.info(
            "PGOV redact — %d PII span(s): %d redacted, %d surfaced as "
            "user-owned | audit=%s",
            len(pii_redactions),
            _n_redacted,
            len(pii_redactions) - _n_redacted,
            pii_redactions,
        )

    # Stage 3: Delimiter echo check
    echo_matches = check_delimiter_echo(generated_text)
    delimiter_echo = len(echo_matches) > 0
    if delimiter_echo:
        violations.append(f"Delimiter echo detected: {echo_matches}")

    # Stage 4: Tool-call allowlist
    unauthorized_tools = check_tool_calls(generated_text, tool_allowlist)
    tool_call_violation = len(unauthorized_tools) > 0
    if tool_call_violation:
        violations.append(f"Unauthorized tool-calls: {unauthorized_tools}")

    # Stage 5: Leakage check (cosine similarity)
    leakage_score = 0.0
    if retrieved_chunks:
        leakage_score = check_leakage(
            generated_text, retrieved_chunks, cosine_threshold
        )
        if leakage_score >= cosine_threshold:
            violations.append(
                f"Leakage score {leakage_score:.3f} >= threshold {cosine_threshold}"
            )

    # Stage 6: Final approval
    approved = len(violations) == 0
    if not approved:
        logger.warning(
            "PGOV DENIED — %d violation(s): %s | text_preview=%.120r",
            len(violations),
            violations,
            generated_text,
        )
    return PGOVResult(
        approved=approved,
        original_text=generated_text,
        sanitized_text=redacted_text if approved else FALLBACK_MESSAGE,
        leakage_score=leakage_score,
        pii_detected=pii_detected,
        token_count_valid=token_valid,
        delimiter_echo=delimiter_echo,
        tool_call_violation=tool_call_violation,
        violations=violations,
        pii_redactions=pii_redactions,
    )
