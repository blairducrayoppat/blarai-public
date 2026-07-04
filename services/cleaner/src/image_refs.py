"""
Inline image-reference helpers — UC-003 Workstream B (display-only images).
============================================================================
The Cleaner emits article text in markdown, and with ``include_images=True``
on the trafilatura extractor (see ``services/cleaner/src/extraction.py``)
content images ride INLINE in that text as ``![alt](url)`` references — there
is NO separate image field on :class:`~services.cleaner.src.pipeline.CleanResult`;
the refs live in ``.text`` and the host coordinator walks them out of there.

This module is the single home for the three operations performed over those
inline refs:

* :func:`escape_image_alt` — the ALWAYS-ON hardening pass. It neutralizes a
  markdown-breakout in the ALT slot of a ``![alt](url)`` ref so that no
  reference can break out of the image syntax or smuggle an active /
  ``javascript:`` URL into the stored or previewed text.  This runs on EVERY
  cleaned document (``clean_html`` / ``clean_text`` / ``clean_from_guest_parse``)
  **regardless of whether images are ever fetched** — the egress / image fetch
  lock does NOT gate this safety pass (ADR-030 §5 spirit; UC-003-B contract
  spec, Module D).
* :func:`extract_image_refs` — the ordered, absolute-``http(s)``-only list of
  refs the host coordinator iterates to fetch bytes (DORMANT; gated behind the
  4th weld lock ``[knowledge].images_enabled=false`` AND the egress door weld).
* :func:`rewrite_image_refs` — the post-fetch rewrite from remote
  ``![alt](url)`` to the local ``![alt](blarai-img://<image_id>)`` scheme; a
  ref the coordinator could NOT fetch (or chose not to) is dropped to an
  alt-only ``[image: <alt>]`` placeholder so NO dangling remote URL is ever
  stored.

EXTRACTION-ONLY / NO-FETCH POSTURE: nothing here fetches anything.  These are
pure string transforms over already-extracted text.  Determinism: same input
→ byte-identical output (locked by tests).

THE THREAT MODEL for :func:`escape_image_alt`.  A hostile page controls the alt
text of an image.  trafilatura renders ``<img alt="..." src="...">`` as
``![<alt>](<src>)``.  An attacker who can put ``]``, ``(`` or ``)`` (or a
backslash) into the alt slot can break out of the ``![...](...)`` syntax and
forge a SECOND, attacker-chosen ``](javascript:...)`` tail — turning a benign
image into an active link the WinUI markdown renderer might honor.  Two
examples the contract names:

* ``![x](javascript:alert(1))`` — an active-scheme URL in the URL slot.
* ``![a](b) ](javascript:...)`` — alt/URL chosen so a breakout tail forms a
  second ref whose URL is ``javascript:``.

The fix is fail-closed: we re-parse every ``![...](...)`` ref, escape the four
breakout characters inside its alt, and rewrite any URL whose scheme is DANGEROUS
or unknown (``javascript:`` / ``data:`` / ``vbscript:`` / ``file:`` / anything not
``http(s)`` / ``mailto:`` / ``blarai-img://``) to a safe inert placeholder — while
LEAVING a legitimate link (``http(s)`` / ``mailto:`` / a relative or ``#anchor`` /
protocol-relative URL) untouched, so benign article content is never mangled.  The
scheme is read on a CONTROL-STRIPPED probe so a control-obfuscated active scheme
(``java\tscript:``) a normalizing renderer would reconstitute cannot pass as
"benign scheme-less".  After this pass no recognized ``![...](...)`` ref's alt can
break the markdown image syntax and no ref carries an active / ``javascript:`` URL
(within the markdown grammar this module + the WinUI renderer share — the parity
the threat model turns on).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: The local, non-navigable image scheme (PINNED — shared constant, UC-003-B
#: contract spec §"Shared constants").  The host coordinator rewrites a fetched
#: remote ref to ``![alt](blarai-img://<image_id>)``; WinUI renders these by
#: decrypting local bytes and NEVER navigates them.
BLARAI_IMG_SCHEME: str = "blarai-img://"

# ---------------------------------------------------------------------------
# Inline-ref grammar.
#
# A markdown image ref is ``![alt](url)``.  We match it with two deliberately
# breakout-resistant inner classes so the regex itself cannot be walked past
# its own closing token by a hostile alt/url:
#
#   alt slot: any run of characters that are NOT ']' and NOT a newline — i.e.
#             the alt stops at the FIRST unescaped ']'.  A hostile ']' inside
#             the alt therefore terminates the match exactly where markdown
#             renderers terminate it, which is the whole point: we want to see
#             the SAME ref boundaries the renderer sees, then escape them.
#   url slot: any run of characters that are NOT ')' — a URL stops at the first
#             ')', matching the WinUI markdown renderer's URL class EXACTLY
#             (``MarkdownBlock.cs`` uses ``[^)]`` for both the image and the
#             link slot).  This is whitespace-TOLERANT on purpose: the renderer
#             would treat ``](javascript: alert)`` (a space after the scheme) as
#             one navigable URL, so the escaper must see the SAME span to be
#             able to neutralize it.  An earlier ``[^)\s]*`` (stop at whitespace)
#             let exactly that whitespace-bearing active-scheme URL slip past
#             both passes while the renderer still honored it (review MAJOR,
#             2026-06-14) — parity with the renderer closes that gap.
#
# This is intentionally NOT a permissive "anything in between" pattern across
# refs: each class still stops at its own closing token (``]`` for alt, ``)``
# for url) so an attacker's later ``](...)`` cannot masquerade as the real
# closing — the exact breakout we defend against.
# ---------------------------------------------------------------------------

#: Matches one ``![alt](url)`` ref.  Group 1 = raw alt; group 2 = raw url.
#: The alt class ``[^\]\n]*`` stops at the FIRST ``]`` and the url class
#: ``[^)]*`` at the first ``)`` — the SAME ref boundaries the WinUI renderer
#: (``[^)]``) sees, the precondition for escaping/neutralizing them.
_IMAGE_REF_RE: re.Pattern[str] = re.compile(r"!\[([^\]\n]*)\]\(([^)]*)\)")

#: Matches ANY ``](url)`` link/image tail — used in a SECOND pass to catch a
#: DANGLING tail (e.g. ``![a](b) ](javascript:...)``) where the leading ``![``
#: was already consumed/neutralized and an attacker-forged ``](scheme:...)``
#: would otherwise survive as a navigable link the renderer honors.  The url
#: class is ``[^)]*`` (renderer-parity — whitespace-tolerant) so a
#: ``](javascript: alert)`` tail is caught, not skipped.  Group 1 = raw url.
_LINK_TAIL_RE: re.Pattern[str] = re.compile(r"\]\(([^)]*)\)")

#: An absolute http/https URL — the ONLY scheme the coordinator will attempt to
#: fetch.  Case-insensitive scheme; the rest is opaque (we never parse query
#: structure — fail-closed, we either recognize the http(s) prefix or we do not).
_ABSOLUTE_HTTP_RE: re.Pattern[str] = re.compile(r"(?i)\Ahttps?://\S")

#: The placeholder a non-allowlisted URL collapses to in :func:`escape_image_alt`.
#: Inert: it is not a URL the renderer will resolve and carries no scheme.
_NEUTRALIZED_URL_PLACEHOLDER: str = "about:blank#blarai-blocked"


@dataclass(frozen=True)
class ImageRef:
    """One inline ``![alt](url)`` reference (frozen — a parsed ref is a fact).

    ``alt`` is the raw alt text as extracted (the coordinator escapes it again
    at rewrite time via :func:`escape_image_alt`); ``url`` is the absolute
    ``http``/``https`` source URL.
    """

    alt: str
    url: str


#: Explicit URL schemes SAFE to keep verbatim in a link/image slot: http(s) are
#: navigable article links; mailto is a benign mail-client link.  A scheme-LESS
#: URL (relative path, ``#anchor``, ``./foo``) is also kept — it carries no active
#: scheme.  EVERY other explicit scheme — ``javascript:``, ``data:``, ``vbscript:``,
#: ``file:``, or any UNKNOWN scheme — is neutralized (fail-closed on the unknown).
_SAFE_URL_SCHEMES: frozenset[str] = frozenset({"http", "https", "mailto"})

#: Detects a leading URL scheme: a letter then letters/digits/+/-/. up to ':'.
_URL_SCHEME_RE: re.Pattern[str] = re.compile(r"(?i)\A([a-z][a-z0-9+.\-]*):")

#: C0 control chars (\x00–\x1F) + DEL (\x7F).  A WHATWG URL parser STRIPS tab /
#: newline / CR from a URL, so a control-obfuscated active scheme
#: (``java\tscript:``, a leading ``\x00`` before ``javascript:``) that the raw
#: string hides reconstitutes to an ACTIVE scheme at render time.  We strip the
#: whole control range from a DETECTION PROBE — broader than WHATWG's \t\n\r, to
#: fail closed — so the safe-set check sees the underlying scheme.
_CONTROL_CHARS_RE: re.Pattern[str] = re.compile(r"[\x00-\x1f\x7f]")


def _is_allowlisted_url(url: str) -> bool:
    """True iff *url* is SAFE TO KEEP verbatim (carries no dangerous/active scheme).

    Keeps: absolute ``http(s)``; the local ``blarai-img://`` scheme; ``mailto:``;
    and any scheme-LESS URL (a relative path, a ``#anchor``, ``./foo``, a
    protocol-relative ``//host``) — all legitimate article content. Returns False
    (→ the inert ``about:blank#blarai-blocked`` placeholder) for ``javascript:``,
    ``data:``, ``vbscript:``, ``file:``, and ANY other / UNKNOWN explicit scheme.

    Detection runs on a CONTROL-STRIPPED probe (C0 + DEL removed): a WHATWG URL
    parser strips tab/newline/CR, so ``java\\tscript:`` and a leading-``\\x00``
    ``javascript:`` reconstitute to an active scheme at render time.  Deciding on
    the probe — and keeping the ORIGINAL verbatim only when the probe is safe —
    treats a control-laden scheme as the dangerous scheme it reconstitutes to,
    never as "benign scheme-less" (Guide review, 2026-06-14).

    Neutralization is keyed to the DANGEROUS scheme, not to the absence of an
    http(s) one — the "absolute http(s)/blarai-img ONLY" rule before it silently
    rewrote legitimate relative / ``#anchor`` / ``mailto:`` LINKS in pasted +
    re-cleaned article bodies to the placeholder (live body corruption).
    """
    probe = _CONTROL_CHARS_RE.sub("", url).strip()
    if probe.startswith(BLARAI_IMG_SCHEME):
        return True
    scheme = _URL_SCHEME_RE.match(probe)
    if scheme is None:
        return True  # scheme-less after control-strip: relative / #anchor / ./foo / //host
    return scheme.group(1).lower() in _SAFE_URL_SCHEMES


def _escape_alt(value: str) -> str:
    """Escape the four markdown-breakout characters inside an alt slot.

    Backslash FIRST so the backslashes we add escaping ``]``/``(``/``)`` are
    not themselves re-escaped.  After this the alt contains no UNESCAPED
    breakout character, so it can neither terminate ``![...]`` early nor open a
    forged ``](...)`` tail.
    """
    value = value.replace("\\", "\\\\")
    value = value.replace("]", "\\]")
    value = value.replace("(", "\\(")
    value = value.replace(")", "\\)")
    return value


def escape_image_alt(text: str) -> str:
    """Neutralize markdown-breakout in the ALT slot of every ``![alt](url)`` ref.

    The ALWAYS-ON hardening pass (UC-003-B contract spec, Module D).  For each
    inline image ref in *text*:

    * Escape the four breakout characters inside the alt — ``\\``, ``]``,
      ``(``, ``)`` (backslash FIRST so we never double-escape an escape we add)
      — so a hostile ``]``/``(``/``)`` in the alt can no longer terminate the
      ``![...]`` or forge a second ``](...)`` tail.
    * If the URL slot carries a DANGEROUS / active scheme (``javascript:``,
      ``data:``, ``vbscript:``, ``file:``, or any unknown scheme), rewrite it to
      an inert ``about:blank#blarai-blocked`` placeholder.  A safe URL —
      ``http(s)``, ``blarai-img://``, ``mailto:``, or a scheme-less relative /
      ``#anchor`` link — is kept verbatim (legitimate content is never mangled).

    After this pass NO ``![...](...)`` ref's alt can break the markdown image
    syntax and NO ref carries an active / ``javascript:`` URL.  Text that
    contains no image refs is returned unchanged.

    This is a probabilistic Layer-1-style hardening: it makes the STORED and
    PREVIEWED text safe to render.  It is deliberately decoupled from the image
    FETCH path — it runs whether or not images are ever fetched, because the
    refs sit in the text the operator reviews and WinUI renders regardless of
    the egress / ``images_enabled`` locks.

    Implementation is two ordered passes, both fail-closed:

    1. Rewrite every well-formed ``![alt](url)`` ref: escape the alt, and
       neutralize the URL if it is not allowlisted ``http(s)`` /
       ``blarai-img://``.  After this pass the alt of a recognized ref carries
       no UNESCAPED breakout char, so it cannot spawn a forged tail.
    2. Sweep any ``](url)`` link/image TAIL still carrying a non-allowlisted
       URL — the dangling-tail breakout (``![a](b) ](javascript:...)``) where
       the leading ``![`` was consumed by pass 1, or a raw ``]`` in a hostile
       alt that terminated the ``![...]`` early.  A surviving active-scheme
       ``](javascript:...)`` tail is exactly what this pass kills; the URL is
       replaced with the inert placeholder, the literal brackets stay as text.

    Deterministic and total: never raises on any ``str`` input.
    """

    def _replace_ref(match: re.Match[str]) -> str:
        alt = _escape_alt(match.group(1))
        url = match.group(2)
        if not _is_allowlisted_url(url):
            url = _NEUTRALIZED_URL_PLACEHOLDER
        return f"![{alt}]({url})"

    # Pass 1 — well-formed image refs.
    text = _IMAGE_REF_RE.sub(_replace_ref, text)

    def _replace_tail(match: re.Match[str]) -> str:
        url = match.group(1)
        if _is_allowlisted_url(url):
            # A legitimate ``](http…)`` / ``](blarai-img://…)`` tail — leave
            # it (a markdown LINK to an allowlisted target is not the threat;
            # only an active-scheme / non-allowlisted URL is neutralized).
            return match.group(0)
        return f"]({_NEUTRALIZED_URL_PLACEHOLDER})"

    # Pass 2 — dangling/forged tails with a non-allowlisted scheme.
    return _LINK_TAIL_RE.sub(_replace_tail, text)


def extract_image_refs(text: str) -> tuple[ImageRef, ...]:
    """Ordered tuple of ``![alt](url)`` refs whose URL is absolute ``http(s)``.

    The host coordinator (INTEGRATION — not this module) calls this on
    ``CleanResult.text`` to enumerate the images it would fetch through the
    egress door.  Order is document order (the order the refs appear in
    *text*), so the per-image cap (``MAX_IMAGES_PER_ARTICLE``) truncates the
    tail deterministically.

    ONLY absolute ``http``/``https`` URLs are returned — a relative URL, a
    ``data:`` / ``javascript:`` / ``file:`` scheme, an empty URL, or an already
    local ``blarai-img://`` ref is NOT a fetch candidate and is filtered out
    (fail-closed: the coordinator never sees a URL it must not hand to the
    door).  The alt is returned RAW; the coordinator escapes it via
    :func:`escape_image_alt` when it rewrites.

    Deterministic and total: never raises on any ``str`` input.
    """
    refs: list[ImageRef] = []
    for match in _IMAGE_REF_RE.finditer(text):
        alt = match.group(1)
        url = match.group(2)
        if _ABSOLUTE_HTTP_RE.match(url):
            refs.append(ImageRef(alt=alt, url=url))
    return tuple(refs)


def rewrite_image_refs(text: str, mapping: dict[str, str]) -> str:
    """Rewrite fetched refs to the local scheme; drop the rest to a placeholder.

    The host coordinator (INTEGRATION) builds *mapping* = ``{source_url:
    image_id}`` for every image it successfully fetched + staged, then calls
    this to produce the text actually stored / previewed:

    * a ref whose URL is a key in *mapping* becomes
      ``![<escaped_alt>](blarai-img://<image_id>)`` — the local, non-navigable
      scheme WinUI renders from decrypted bytes.
    * a ref whose URL is NOT in *mapping* (not fetched — capped out, refused by
      the door, wrong content-type, or simply never a fetch candidate) is
      dropped to an alt-only ``[image: <escaped_alt>]`` placeholder.  NEVER a
      dangling remote URL: a remote ``![alt](https://…)`` that survived to
      storage would be a navigable, trackable, exfiltration-shaped artifact.

    The alt is escaped via :func:`escape_image_alt`'s alt-escaping in both
    branches (breakout chars neutralized) so the rewritten ref is itself safe.

    Deterministic and total: never raises on any ``str`` input.
    """

    def _replace(match: re.Match[str]) -> str:
        alt = _escape_alt(match.group(1))
        url = match.group(2)
        # A ref ALREADY on the local scheme — an operator-edited re-submit that
        # KEPT a prior blarai-img:// image (the edit path may carry a surviving
        # local ref alongside a NEW http ref) — passes through verbatim (alt
        # re-escaped).  Without this, the local ref is not a *mapping* key and
        # would collapse to a placeholder: silent loss of a kept image (review
        # MAJOR, 2026-06-14).
        if url.startswith(BLARAI_IMG_SCHEME):
            return f"![{alt}]({url})"
        image_id = mapping.get(url)
        if image_id is not None:
            return f"![{alt}]({BLARAI_IMG_SCHEME}{image_id})"
        # Not fetched → alt-only placeholder, no remote URL survives.
        return f"[image: {alt}]"

    return _IMAGE_REF_RE.sub(_replace, text)
