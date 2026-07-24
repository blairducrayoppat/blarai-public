"""Gate: the WinUI gallery DTO field literals match the Python IMAGE_LIST wire.

WHY THIS GATE EXISTS — the silent gallery mis-display (UC-010 #669).
-------------------------------------------------------------------
The WinUI backend client (``services/ui_winui/Ipc/BackendClient.cs``) parses the
non-streaming ``list_generated_images`` result into ``GeneratedImageMeta`` rows by
HAND-CODED field-name string literals — ``Str(img, "image_id")``,
``Str(img, "session_id")``, ``Str(img, "mime")``, ``Long(img, "byte_size")``,
``Bool(img, "saved")``, ``Str(img, "created_at")``.  Those literals must match the
canonical Python wire field set, ``MessageFramer.IMAGE_LIST_KEYS`` in
``shared/ipc/protocol.py``, which the AO normalises every IMAGE_LIST record onto.

C# and Python cannot share a literal across the language boundary, so the SSOT is
the Python tuple and THIS gate-time test reads the C# literals straight out of the
``ListGeneratedImagesAsync`` method body and FAILS LOUDLY — naming exactly which
field(s) drifted — in BOTH directions:
  (a) a C# literal not present in the canonical set (a stale/typo'd key that would
      always read as its zero value → size 0, wrong "saved" badge), and
  (b) a canonical key the C# does not parse (a newly-added wire field the gallery
      would silently ignore).

Renaming a field on EITHER side without updating the other turns this test red in
the same change — the WS5 lesson made structural: vigilance is not a control; a
red test is.  The test never carries a second copy of the field names: it imports
``IMAGE_LIST_KEYS`` as the sole source of truth so it can never drift from the wire.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from shared.ipc.protocol import MessageFramer

# This file lives at <repo_root>/tests/integration/<this>.py, so parents[2] is the
# repo root regardless of where the checkout / worktree is on disk.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_CS = _REPO_ROOT / "services" / "ui_winui" / "Ipc" / "BackendClient.cs"

# The C# method whose field literals the gallery DTO parse depends on.  Scoping the
# literal extraction to THIS method's body keeps identically-named JSON helpers in
# sibling methods (e.g. ``Bool(r, "ok")`` / ``Bool(r, "found")`` in ManageAsync)
# out of the field set.
_METHOD_NAME = "ListGeneratedImagesAsync"

# A per-image field read inside the method body: Str/Long/Bool(img, "<field>").
# Pinned to the ``img`` element argument so nothing but a real per-image field
# literal is captured (a defence-in-depth complement to the body scoping above).
_FIELD_RE = re.compile(r"\b(?:Str|Long|Bool)\s*\(\s*img\s*,\s*\"([^\"]*)\"\s*\)")

# A C# line comment — stripped BEFORE token extraction so a field MENTIONED in a
# comment cannot be miscounted as a live parse.
_LINE_COMMENT_RE = re.compile(r"//[^\n]*")

# Signature anchor: matches ``...ListGeneratedImagesAsync(`` wherever it appears.
_METHOD_SIG_RE = re.compile(rf"\b{re.escape(_METHOD_NAME)}\s*\(")


def _extract_method_body(source: str, method_name: str) -> str:
    """Return the brace-balanced body of ``method_name`` from C# ``source``.

    A method body nests braces (``try``/``foreach``/``catch`` blocks, and the
    empty ``new {{ }}`` object initialiser), so a naive non-greedy ``{{...}}``
    regex would truncate at the FIRST ``}}``.  This scans character-by-character,
    counting brace depth while skipping C# string literals (ordinary, verbatim
    ``@"..."``, and char literals) and comments so a brace INSIDE any of them can
    never unbalance the count.
    """
    sig = _METHOD_SIG_RE.search(source)
    assert sig is not None, (
        f"Could not locate the {method_name} method in {_BACKEND_CS} — the gate "
        "cannot verify the gallery DTO fields. If the method was renamed, update "
        "_METHOD_NAME in this test."
    )
    # The body opens at the first '{' after the signature; the parameter list
    # between '(' and that brace contains no '{', so this is unambiguous.
    open_idx = source.index("{", sig.end())
    body_start = open_idx + 1

    depth = 0
    i = open_idx
    n = len(source)
    in_line_comment = in_block_comment = False
    in_string = in_char = False
    verbatim = False

    while i < n:
        c = source[i]
        nxt = source[i + 1] if i + 1 < n else ""

        if in_line_comment:
            if c == "\n":
                in_line_comment = False
            i += 1
        elif in_block_comment:
            if c == "*" and nxt == "/":
                in_block_comment = False
                i += 2
            else:
                i += 1
        elif in_string:
            if verbatim:
                if c == '"' and nxt == '"':  # "" escapes a quote in a verbatim string
                    i += 2
                elif c == '"':
                    in_string = False
                    i += 1
                else:
                    i += 1
            else:
                if c == "\\":  # backslash escape in an ordinary string
                    i += 2
                elif c == '"':
                    in_string = False
                    i += 1
                else:
                    i += 1
        elif in_char:
            if c == "\\":
                i += 2
            else:
                if c == "'":
                    in_char = False
                i += 1
        elif c == "/" and nxt == "/":
            in_line_comment = True
            i += 2
        elif c == "/" and nxt == "*":
            in_block_comment = True
            i += 2
        elif c == "@" and nxt == '"':
            in_string, verbatim = True, True
            i += 2
        elif c == '"':
            in_string, verbatim = True, False
            i += 1
        elif c == "'":
            in_char = True
            i += 1
        elif c == "{":
            depth += 1
            i += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return source[body_start:i]
            i += 1
        else:
            i += 1

    raise AssertionError(
        f"Unbalanced braces while scanning the {method_name} body in {_BACKEND_CS}."
    )


def _csharp_gallery_fields() -> set[str]:
    """Extract the per-image field-name literals parsed inside ``ListGeneratedImagesAsync``."""
    source = _BACKEND_CS.read_text(encoding="utf-8")
    body = _extract_method_body(source, _METHOD_NAME)
    body = _LINE_COMMENT_RE.sub("", body)
    return set(_FIELD_RE.findall(body))


@pytest.mark.skipif(
    not _BACKEND_CS.exists(),
    reason="WinUI BackendClient.cs not present in this checkout",
)
def test_winui_gallery_dto_fields_match_canonical() -> None:
    csharp = _csharp_gallery_fields()
    canonical = set(MessageFramer.IMAGE_LIST_KEYS)

    extra_in_csharp = csharp - canonical  # (a) C# literal not on the wire
    missing_from_csharp = canonical - csharp  # (b) wire field the C# ignores
    assert not (extra_in_csharp or missing_from_csharp), (
        "The WinUI gallery DTO field literals in "
        f"{_METHOD_NAME} (services/ui_winui/Ipc/BackendClient.cs) have DRIFTED "
        "from the canonical MessageFramer.IMAGE_LIST_KEYS wire set "
        "(shared/ipc/protocol.py).\n"
        f"  C# literals with no canonical key (would always read zero): "
        f"{sorted(extra_in_csharp)}\n"
        f"  Canonical keys the C# does not parse (silently ignored): "
        f"{sorted(missing_from_csharp)}\n"
        "Rename on ONE side requires the matching rename on the other, in the same "
        "change — otherwise the gallery mis-displays (size 0 / wrong saved badge) "
        "with no other failure. This gate is that failure."
    )


def test_winui_gallery_dto_extraction_found_known_fields() -> None:
    """Sanity: the extractor really parsed literals (guards a silently-empty match
    that could make the equality assertion vacuously pass)."""
    if not _BACKEND_CS.exists():
        pytest.skip("WinUI BackendClient.cs not present in this checkout")
    csharp = _csharp_gallery_fields()
    # image_id/byte_size have been parsed by ListGeneratedImagesAsync since the
    # gallery shipped; if the extractor returns them it is reading the real body.
    assert "image_id" in csharp
    assert "byte_size" in csharp
    assert len(csharp) == len(MessageFramer.IMAGE_LIST_KEYS)
