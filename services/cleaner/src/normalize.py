"""
Deterministic text normalization — Cleaner stage 2 (UC-003, ADR-030 §1).
========================================================================
Normalization for *knowledge quality*: the decades-horizon knowledge bank
stores what this stage emits, so the contract is strict determinism — the
same input always yields byte-identical output.

What it does, in order:

1. Unicode NFC normalization (canonical composition — ``cafe`` + combining
   acute (NFD) becomes the composed ``café``).
2. Line-ending normalization (``\\r\\n`` / ``\\r`` → ``\\n``).
3. Zero-width / invisible-format character stripping (zero-width spaces and
   joiners, BOM, soft hyphen, word joiner) — these characters are both a
   storage-pollution problem and a known scanner-evasion vector (a
   zero-width space inside "ignore previous instructions" defeats a naive
   phrase scan), which is why the sanitization stage runs AFTER this one.
   Bidirectional controls (LRM/RLM, embedding/override/isolate) are
   stripped in the same pass — invisible characters that re-order rendered
   text; classic display-spoofing primitives with no place in stored prose.
4. Control-character stripping (C0 except ``\\t``/``\\n``, DEL, C1).
5. Per-line trailing-whitespace strip.
6. Blank-line run collapse (3+ consecutive newlines → 2; paragraph
   separation survives, vertical noise does not).
7. Outer strip.

What it deliberately does NOT do: collapse intra-line whitespace runs.
Leading indentation is meaningful in code blocks and preformatted text
inside articles; flattening it would damage exactly the content the
knowledge bank is supposed to keep faithfully.
"""

from __future__ import annotations

import re
import unicodedata

# Invisible formatting characters stripped outright (storage pollution +
# scanner-evasion vectors — see module docstring). Escape sequences, never
# literal characters, so the table is reviewable in any editor/diff.
_ZERO_WIDTH_CHARS: str = (
    "\u200b"  # ZERO WIDTH SPACE
    "\u200c"  # ZERO WIDTH NON-JOINER
    "\u200d"  # ZERO WIDTH JOINER
    "\u2060"  # WORD JOINER
    "\ufeff"  # ZERO WIDTH NO-BREAK SPACE / BOM
    "\xad"  # SOFT HYPHEN
)

# Bidirectional control characters (display re-ordering / spoofing).
_BIDI_CONTROL_CHARS: str = (
    "\u200e"  # LEFT-TO-RIGHT MARK
    "\u200f"  # RIGHT-TO-LEFT MARK
    "\u202a"  # LEFT-TO-RIGHT EMBEDDING
    "\u202b"  # RIGHT-TO-LEFT EMBEDDING
    "\u202c"  # POP DIRECTIONAL FORMATTING
    "\u202d"  # LEFT-TO-RIGHT OVERRIDE
    "\u202e"  # RIGHT-TO-LEFT OVERRIDE
    "\u2066"  # LEFT-TO-RIGHT ISOLATE
    "\u2067"  # RIGHT-TO-LEFT ISOLATE
    "\u2068"  # FIRST STRONG ISOLATE
    "\u2069"  # POP DIRECTIONAL ISOLATE
)

_STRIP_TRANSLATION: dict[int, None] = {
    ord(ch): None for ch in _ZERO_WIDTH_CHARS + _BIDI_CONTROL_CHARS
}

# C0 controls except \t (\x09) and \n (\x0a); \r is handled by line-ending
# normalization before this pattern applies. Plus DEL and the C1 range.
_CONTROL_RE: re.Pattern[str] = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

_TRAILING_WS_RE: re.Pattern[str] = re.compile(r"[ \t]+$", re.MULTILINE)
_BLANK_RUN_RE: re.Pattern[str] = re.compile(r"\n{3,}")


def normalize_text(text: str) -> str:
    """Normalize *text* per the module contract. Deterministic and total."""
    normalized = unicodedata.normalize("NFC", text)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.translate(_STRIP_TRANSLATION)
    normalized = _CONTROL_RE.sub("", normalized)
    normalized = _TRAILING_WS_RE.sub("", normalized)
    normalized = _BLANK_RUN_RE.sub("\n\n", normalized)
    return normalized.strip()
