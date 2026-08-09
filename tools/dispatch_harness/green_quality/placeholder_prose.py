"""#1281 — the deterministic PLACEHOLDER-PROSE floor over a banked GREEN's delivered pages.

A website is mostly WORDS, and until this module nothing in the pipeline asked for any of
them. The intake asks about platform, surface, features and assets; the plan carries
``asset_specs`` for images and has no equivalent for copy; the acceptance criteria grade
behaviour — a function returns the right value, a page loads without a console error. So the
coder invents filler, or ships lorem ipsum, or leaves "Welcome to My Site" in the ``<title>``,
and EVERY GATE PASSES, because every gate is measuring something else. This is not a quality
problem the exams are failing to catch; it is a category the exams do not have.

THIS MODULE IS THE FLOOR OF THAT CATEGORY, NOT ITS CEILING, and the distinction is the whole
design. Whether the prose is GOOD is judgment and belongs to the operator (#1280). What a
machine can decide is the difference between *content that was asked for and written* and
*placeholder nobody noticed* — text that announces itself as unfinished. Everything here
stays on that line: there is no readability metric, no tone scorer, no model. A page of bland
but genuine copy about a pottery studio passes this scan, and should.

Three tiers of evidence, weakest last, each with a different claim on the reader:

* :data:`RULE_LOREM_IPSUM` — the Latin filler corpus. Text no human wrote about anything.
* :data:`RULE_FILL_IN_THE_BLANK` — copy that literally instructs someone to replace it
  ("Your text here", "Description goes here", "Replace this paragraph"). Both are HIGH: they
  cannot be what the operator asked for, whatever he asked for. The instruction is matched by
  SHAPE and not only by words: an instruction is the whole of what its slot says, while the
  same words inside a longer sentence are somebody's real copy ("Advertise your business here
  from just 20 pounds a month"). See :func:`_fill_in_by_shape` — that narrowing is what earns
  this rule the right to stay on the band-moving tier.
* :data:`RULE_STARTER_BOILERPLATE`, :data:`RULE_SCAFFOLD_TITLE`,
  :data:`RULE_PLACEHOLDER_CONTACT` — the framework demo strings, the scaffold's default
  document title, and the template contact details (``you@example.com``, ``123-456-7890``,
  ``123 Main Street``). MEDIUM: near-certain in practice, but each is conceivably deliberate,
  so they are RECORDED and REPORTED and never move a band.

WHERE THE SCAN LOOKS, and why it is not simply a grep over the tree. A raw text search for
these strings is wrong in a way that matters: ``<input placeholder="you@example.com">`` is a
CORRECT and idiomatic form hint, not placeholder prose, and a scan that cannot tell an
attribute from a paragraph would convict the deliverables that got it right. So an HTML page
is PARSED and only its user-visible text is graded — element text, plus ``alt`` and
``aria-label`` (which a screen-reader user hears as the page's words). ``placeholder=``,
``value=`` and every other attribute are deliberately NOT read, and ``<script>``/``<style>``
bodies are suppressed.

Component and template files (``.jsx``, ``.vue``, ``.svelte``, ``.hbs``, …) cannot be parsed
this way — their text is interleaved with expressions no HTML parser will resolve — so they
get the RAW scan restricted to the UNAMBIGUOUS tier only. "Lorem ipsum" in a component file
is lorem ipsum wherever it sits; ``you@example.com`` in one might be a form hint. That
asymmetry is the same shape as the sibling security scan's build-output split: the tier is
chosen by which question the rule can still answer once the context is gone.

BUILD OUTPUT IS READ, unlike in the security scan's authorship rules, and for the reason that
module states in the mirror image: *what does the deliverable SHIP?* A static site's
``dist/index.html`` is the page the operator opens, and lorem ipsum in it is shipped lorem
ipsum. Dependency and VCS trees are skipped outright — ``node_modules`` is full of demo pages
that would drown every real finding.

WHAT CAN SILENCE THIS CHECK (#1183's lesson, applied before it costs anything):

* **The phrase lists are word lists**, and a word list is out-run by filler nobody listed —
  a coder that invents its own bland copy ("Our story. We are passionate about quality.")
  produces text this scan cannot distinguish from real writing, because there IS no textual
  difference. That is the ceiling named in the ticket, and no scan closes it; only asking the
  operator what the site should say does (#1281 parts 1 and 2, not built here).
* **Parsing is a silencing vector in itself**: a page that does not parse would fall to the
  raw tier and lose the visible-only rules. It is therefore COUNTED and NAMED in the status,
  never absorbed. That path is also the RARE one, measured rather than assumed — ``html.parser``
  swallows nearly everything malformed without raising.
* **An unclosed suppressing tag silences the REST OF THE PAGE, and the parse still succeeds** —
  the vector that actually fires. A ``<pre>`` or ``<template>`` opened and never closed puts
  every remaining text node inside a suppressed region, so lorem ipsum below it produced no
  finding, no count and a CLEAN disposition. It is now carried out of the parser as
  :attr:`VisibleText.truncated`, counted, named in the status, and backed by a raw unambiguous
  re-scan of the page. Honesty machinery spent on the defended path while the live path went
  uncounted is the shape this bullet exists to stop repeating.
* **A tree with no pages in it** is the vector that matters most, because it is the common
  case: a Python library has no user-visible prose. That must read as NOT APPLICABLE, and it
  is a distinct state from CLEAN — see :meth:`ProseResult.disposition`.

KNOWN LIMITS, stated because a named limit is usable and an unnamed one reads as coverage:
prose that is bland, generic or wrong but GENUINE is invisible here and always will be;
copy held in a database, a CMS payload or a JSON content file is not read; a language other
than English is not covered by any list; text assembled at runtime from fragments is not
seen, because this is a lint over delivered files and never a render; and the MEDIUM tier's
scaffold-title list is an exact whole-element match, so "Welcome to My Pottery Site" is
correctly NOT flagged while "Welcome to My Site" is.

MEASURED ALWAYS, CONSEQUENTIAL ONLY WHEN GRANTED. Two halves of this instrument ship on
different tracks. The MEASUREMENT — the sidecar, the ``green_quality_prose`` evidence stamp,
the rollup corpus block and the night's KPI line — is unconditional, because counts against
real deliverables are the evidence any later argument about this scan has to rest on, and an
instrument that banks nothing until it is trusted can never become trustworthy. The
CONSEQUENCE — the B caveat in the band and the sentence on the operator's card — is gated by
``[fleet_dispatch].green_quality_prose_band``, resolved by :func:`prose_band_enabled`. Read
that flag's live value from the config, never from here: what this module states is the
CONTRACT, and a docstring restating a posture goes stale the day the posture changes.

The gate is cheap by construction, which is why it is the right default. Withholding the band
costs nothing that the measurement does not already deliver, and it removes the only path by
which this scan can make the operator's card WORSE — the card carries one caveat, ordered
security → prose → craft, so a wrong prose sentence does not merely add noise, it evicts the
true Layer-1 sentence that would otherwise have been there.

ADVISORY, AND DELIBERATELY QUIETER THAN ITS SIBLING. Once granted, a HIGH finding is a B
caveat — reported, never banded A, which is #1281's stated predicate — and never a C. The security scan forces C
alone because a false clean there hands a non-technical operator a live credential; a page of
lorem ipsum costs him a reread. An UNMEASURED prose scan does not move the band at all, which
is the opposite of the security scan's rule and is argued rather than assumed: an unreadable
tree blinds every Layer-1 lint too, and spending a caveat on "the wording check could not run"
would buy noise at the price of the caveat the operator can act on. It is still stamped,
still counted, and still rendered — silence is never how this instrument says it did not look.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Optional, Pattern

from .constants import (
    EVIDENCE_VALUE_CAP,
    SEVERITY_HIGH,
    SEVERITY_INFO,
    SEVERITY_MEDIUM,
    SEVERITY_ORDER,
)

# ---------------------------------------------------------------------------
# Scan bounds (a battery-close scan is seconds; these are the ceilings that keep it so)
# ---------------------------------------------------------------------------

#: Pages examined per repo. A deliverable past this is a generated docset, not a site.
_MAX_FILES = 400
#: Bytes read per file. A page longer than this is a data dump with markup around it.
_MAX_FILE_BYTES = 256 * 1024
#: Findings recorded. Past this the scan keeps going but records only HIGH findings, so a
#: truncation can never lower the band by dropping the one unambiguous finding behind a
#: crowd of MEDIUMs — the same rule, and the same reason, as the security scan's cap.
_MAX_FINDINGS = 50
#: The hard ceiling once only HIGHs are kept.
_MAX_HIGH_FINDINGS = 200
#: Characters of matched text kept in a finding detail.
_SNIPPET_CAP = 120

#: Pages parsed for VISIBLE TEXT — the strong path, where every rule applies.
_PAGE_SUFFIXES: frozenset[str] = frozenset({".html", ".htm", ".xhtml"})

#: Component/template sources — the RAW path, unambiguous rules only (see the module
#: docstring). Their markup is interleaved with expressions no HTML parser resolves, so the
#: attribute-versus-text distinction the visible-only rules depend on is not available.
_TEMPLATE_SUFFIXES: frozenset[str] = frozenset({
    ".jsx", ".tsx", ".vue", ".svelte", ".astro", ".ejs", ".hbs", ".handlebars",
    ".njk", ".liquid", ".mustache", ".twig", ".pug", ".jade",
})

#: Directories never read — DEPENDENCY and VCS trees. ``node_modules`` alone carries thousands
#: of demo pages whose lorem ipsum is nobody's deliverable. Build OUTPUT is deliberately NOT
#: here: a static site's ``dist/`` is the page the operator opens. Anything skipped that
#: actually exists in the tree is NAMED in the result status.
_SKIP_DIRS: frozenset[str] = frozenset({
    "node_modules", "vendor", ".git", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", "venv", ".venv", "site-packages", ".tox", ".idea", ".vscode",
})

#: Machine-generated pages that carry no authored copy — coverage reports and minified
#: bundles. Reading them produces findings nobody wrote and nobody can fix.
_SKIP_FILE_RE: Pattern[str] = re.compile(r"(\.min\.(js|html)$|^coverage.*\.html$)", re.IGNORECASE)

#: A finding inside the test suite or a fixture tree is demoted one level: a fixture page
#: legitimately carries lorem ipsum, that being what a fixture is for. Demoted, never
#: dropped — a fixture that became the delivered page is still a delivered page.
_TEST_PATH_RE: Pattern[str] = re.compile(
    r"(^|[/\\])(tests?|spec|__tests__|fixtures?|examples?|__mocks__)([/\\]|$)", re.IGNORECASE)

_DEMOTE: dict[str, str] = {
    SEVERITY_HIGH: SEVERITY_MEDIUM,
    SEVERITY_MEDIUM: SEVERITY_INFO,
    SEVERITY_INFO: SEVERITY_INFO,
}

#: Attributes whose value IS the page's words to somebody. ``alt`` is what a screen-reader
#: user hears in place of the image; ``aria-label`` is what it announces for a control.
#:
#: THE EXCLUSIONS ARE THE LOAD-BEARING HALF. ``placeholder=`` is the single most likely
#: attribute in a delivered site to contain text that LOOKS like placeholder prose — because
#: that is literally its job — and a form hint reading ``you@example.com`` is the deliverable
#: getting it RIGHT. Grading it would convict the good page and leave the bad one alone.
#: ``value``, ``title``, ``href`` and ``data-*`` are excluded on the same principle: an
#: attribute is a mechanism until proven to be prose.
_READ_ATTRS: frozenset[str] = frozenset({"alt", "aria-label"})

#: Element bodies never graded: their content is code or vector data, not prose.
_SUPPRESSED_TAGS: frozenset[str] = frozenset({
    "script", "style", "noscript", "template", "svg", "canvas", "code", "pre",
})

#: Elements whose WHOLE text is matched against :data:`_SCAFFOLD_TITLES`. Exact whole-element
#: matching is what keeps that rule honest: "Welcome to My Pottery Studio" is a real title
#: that happens to start like a scaffold's, and a substring rule would flag it.
_TITLE_TAGS: frozenset[str] = frozenset({"title", "h1", "h2"})


# ---------------------------------------------------------------------------
# Rule ids (stable strings — the sidecar, the evidence stamp and the tests name these)
# ---------------------------------------------------------------------------

RULE_LOREM_IPSUM = "lorem-ipsum-filler"
RULE_FILL_IN_THE_BLANK = "fill-in-the-blank-copy"
RULE_STARTER_BOILERPLATE = "starter-template-copy"
RULE_SCAFFOLD_TITLE = "scaffold-default-title"
RULE_PLACEHOLDER_CONTACT = "placeholder-contact-detail"

#: What each rule means to a NON-CODER, in one sentence. The card renders these; the operator
#: is the reader deciding whether the site is finished enough to show anyone.
RULE_PLAIN_LANGUAGE: dict[str, str] = {
    RULE_LOREM_IPSUM:
        "one of its pages still contains the fake Latin filler text designers use as a "
        "stand-in — nobody wrote real words for that part of the site yet.",
    RULE_FILL_IN_THE_BLANK:
        "one of its pages still says something like 'your text here' — the template's own "
        "instruction to write something, left in place of the writing.",
    RULE_STARTER_BOILERPLATE:
        "one of its pages still carries the example wording that ships with the starter "
        "template, rather than anything written about your site.",
    RULE_SCAFFOLD_TITLE:
        "the page's title is still the default one the template came with (the words shown "
        "in the browser tab), not the name of your site.",
    RULE_PLACEHOLDER_CONTACT:
        "its contact details look like the template's examples rather than yours — worth "
        "checking before anyone tries to reach you through this page.",
}

#: The severity each rule carries BEFORE any test-path demotion. HIGH is reserved for text
#: that cannot be what the operator asked for whatever he asked for; everything else is a
#: near-certainty that is still conceivably deliberate, and is reported without moving a band.
RULE_SEVERITY: dict[str, str] = {
    RULE_LOREM_IPSUM: SEVERITY_HIGH,
    RULE_FILL_IN_THE_BLANK: SEVERITY_HIGH,
    RULE_STARTER_BOILERPLATE: SEVERITY_MEDIUM,
    RULE_SCAFFOLD_TITLE: SEVERITY_MEDIUM,
    RULE_PLACEHOLDER_CONTACT: SEVERITY_MEDIUM,
}


# ---------------------------------------------------------------------------
# The phrase corpora
# ---------------------------------------------------------------------------

#: The Latin filler corpus. Anchored on multi-word runs rather than the bare word "lorem",
#: which appears in real surnames and place names.
_LOREM_RE: Pattern[str] = re.compile(
    r"\blorem\s+ipsum\b"
    r"|\bdolor\s+sit\s+amet\b"
    r"|\bconsectetur\s+adipiscing\b"
    r"|\bsed\s+do\s+eiusmod\b"
    r"|\but\s+enim\s+ad\s+minim\b"
    r"|\bduis\s+aute\s+irure\b"
    r"|\bexcepteur\s+sint\s+occaecat\b"
    r"|\bnulla\s+pariatur\b",
    re.IGNORECASE,
)

#: Copy that instructs someone to replace it. Every pattern requires a GENERIC CONTENT NOUN
#: (text, copy, description, headline, …) — never a specific one. That restriction is what
#: separates "Your content here" from "Add your email here", which is a real newsletter
#: label on a real site, and it is why the noun list is closed rather than ``\w+``.
_CONTENT_NOUN_ALT = (r"text|content|copy|description|title|headline|heading|logo|image|photo"
                     r"|caption|tagline|slogan|paragraph|blurb|bio|about|address")
_CONTENT_NOUN = rf"(?:{_CONTENT_NOUN_ALT})"

#: The nouns "your <noun> here" may name, and DELIBERATELY NARROWER than the content nouns
#: above. ``logo``, ``business`` and ``brand`` were measured convicting standard commercial
#: copy — "Your logo here" is what a festival's sponsor slot says and "Advertise your business
#: here" is what a directory says — and neither is a template's leftover instruction. They stay
#: in :data:`_CONTENT_NOUN_ALT`, so "Logo goes here" is still caught; it is the possessive form
#: that a real page uses to sell a slot. ``name``/``company``/``site`` are the identity words a
#: template genuinely asks you to fill in.
_OWNED_NOUN = (r"(?:text|content|copy|description|title|headline|heading|image|photo"
               r"|caption|tagline|slogan|paragraph|blurb|bio|about|address"
               r"|name|company|site)")

#: What splits a scanned string into the FRAGMENTS the shape-anchored rules below are matched
#: against: markup tags and line breaks, never sentence punctuation. Splitting on a dash or a
#: comma would hand "Your logo here — become a supporter of the festival" straight back, since
#: its first clause reads exactly like an instruction; the whole point is that the sentence
#: CONTINUES. On the parsed path a fragment is normally the text node itself; on the raw path
#: it is the text between two tags, which is the closest thing to a text node available there.
_FRAGMENT_SPLIT_RE: Pattern[str] = re.compile(r"<[^>]*>|\{[^{}]*\}|[\r\n]+")

#: Trimmed off a fragment's ENDS before the shape-anchored match: whitespace, the terminal
#: punctuation a template writes after its own instruction, and the quotes/brackets a component
#: line leaves around a string. Interior punctuation is untouched — that is the signal.
_FRAGMENT_TRIM = " \t\r\n.!?:;,\"'`()[]{}«»“”‘’*|-–—"

#: THE INSTRUCTION SHAPE, matched against a WHOLE fragment. An instruction to fill something in
#: stands alone: it is the entire text of its heading, cell or slot. Real copy that happens to
#: contain the same words is embedded in a sentence — "Advertise your business here from just
#: 20 pounds a month", "Enter your address here and we will confirm by email" — and the words on
#: either side are what make it real. Matching the noun alone convicted both, at HIGH, on the
#: tier that moves a band; a visible "Enter your address here" is also the MORE accessible form
#: of a form label (WCAG discourages placeholder-only labelling), so the rule was convicting the
#: deliverable that got accessibility right for doing so.
_FILL_IN_BARE_RES: tuple[Pattern[str], ...] = tuple(re.compile(p, re.IGNORECASE) for p in (
    rf"your\s+(?:\w+\s+){{0,2}}?{_OWNED_NOUN}\s+here",
))

#: The same shape argument, anchored at the fragment's END only. "Page title goes here" is the
#: real ``web-static`` seed's heading and carries a leading word, so this rule cannot demand a
#: whole-fragment match; what it can demand is that nothing FOLLOWS. "The title goes here,
#: between the tags" is a tutorial explaining the markup, and the clause after the comma is the
#: difference between describing an instruction and being one.
_FILL_IN_TAIL_RES: tuple[Pattern[str], ...] = tuple(re.compile(p, re.IGNORECASE) for p in (
    rf"\b{_CONTENT_NOUN}\s+goes\s+here",
))

#: The context-free remainder: phrases whose words cannot be borrowed by real copy at all, so
#: they hold wherever in a fragment they sit. ``enter`` is deliberately ABSENT from the
#: imperative alternation — it is the FORM verb ("Enter your bio here" is a label), where
#: ``insert``/``replace``/``edit`` are the TEMPLATE verbs.
_FILL_IN_RES: tuple[Pattern[str], ...] = tuple(re.compile(p, re.IGNORECASE) for p in (
    rf"\b(?:insert|replace|edit)\s+(?:\w+\s+){{0,3}}?{_CONTENT_NOUN}\s+here\b",
    (r"\b(?:replace|edit|delete)\s+this\s+"
     r"(?:text|content|copy|paragraph|section|heading|title|placeholder|line)\b"),
    r"\bplaceholder\s+(?:text|content|copy|paragraph|image|description)\b",
    (r"\b(?:add|write|put)\s+your\s+(?:own\s+)?"
     r"(?:text|content|copy|description|blurb|words)\s+(?:here|in\s+here)\b"),
    (r"\bthis\s+is\s+(?:just\s+)?(?:a\s+|some\s+)?(?:dummy|filler|sample|placeholder)\s+"
     r"(?:text|content|copy|paragraph)\b"),
    r"\b(?:lorem\s+)?ipsum\s+placeholder\b",
    r"\bTODO:?\s*(?:add|write)\s+(?:the\s+)?(?:copy|content|text|description)\b",
))

#: Framework and template demo strings, matched as LONG DISTINCTIVE PHRASES only. A short
#: default like "Card title" was considered and rejected: it is a Bootstrap default AND a
#: plausible real heading, and this tier already errs toward the reader rather than the count.
_STARTER_RES: tuple[Pattern[str], ...] = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"some quick example text to build on the card title",
    r"this is a wider card with supporting text below",
    r"the quick brown fox jumps over the lazy dog",
    r"edit\s+src[/\\]app\.(?:js|jsx|ts|tsx)\s+and\s+save\s+to\s+reload",
    r"click on the vite and react logos to learn more",
    r"get started by editing\b",
    r"save and see your changes instantly",
    r"an example page for a bootstrap",
    r"quickly design and customize responsive mobile-first sites",
    r"this is a simple hero unit,? a simple jumbotron-style component",
    r"content here,? content here\b",
    r"it is a long established fact that a reader will be distracted",
    r"there are many variations of passages of\b",
))

#: Template contact details. VISIBLE-TEXT ONLY (see :data:`_READ_ATTRS`): every one of these
#: is a legitimate form-hint value in a ``placeholder`` attribute, and flagging it there
#: would convict the page that got it right.
#:
#: ``example.com`` is reserved by IANA (RFC 2606) precisely so that it can never be a real
#: address, which makes an ``@example.*`` address in a page's visible contact copy placeholder
#: BY CONSTRUCTION rather than by resemblance. The phone and street patterns are the canonical
#: template strings, not merely plausible-looking ones — and that word is load-bearing. The
#: street number was written ``1?23``, which broadened the canonical **123** Main Street into
#: an ORDINARY house number on the commonest street name in the anglosphere: "Ridge Pottery,
#: 23 Main Street, Hexham" is a real business address and was reported as a template's. The
#: optional digit is gone; only the canonical number matches.
#:
#: A "your street address, city, state" pattern was REMOVED rather than narrowed. It convicted
#: "Please enter your address, city, state and postcode", which is a real checkout instruction,
#: and there is no narrowing that separates it from the template's own example line, because
#: they are the same words in the same order — the template borrowed them from the form. A rule
#: that cannot be made to distinguish the two belongs to neither tier.
_CONTACT_RES: tuple[Pattern[str], ...] = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"\b[\w.+-]+@example\.(?:com|org|net)\b",
    r"\b(?:123-456-7890|\(123\)\s*456-?7890|555-?555-?5555|\(555\)\s*555-?5555|555-01\d\d)\b",
    r"\b123\s+(?:main|anywhere|any|your)\s+(?:st|street|road|rd|ave|avenue)\b",
    r"\b1234\s+street\s+address\b",
))

#: Document titles a scaffold leaves behind. Matched against the NORMALISED WHOLE text of a
#: ``<title>``/``<h1>``/``<h2>`` — never as a substring — so a real title that merely starts
#: the same way is untouched. Borderline members ("My First Website", "Test Page", "Home")
#: were deliberately left OUT: each is a title an operator might genuinely want, and a rule
#: that convicts a real choice is how a control gets muted.
_SCAFFOLD_TITLES: frozenset[str] = frozenset({
    "welcome to my site", "welcome to my website", "welcome to our site",
    "welcome to our website", "welcome to my page", "welcome to my homepage",
    "my site", "my website", "my page", "my homepage", "my web page",
    "untitled", "untitled document", "untitled page", "document", "html document",
    "page title", "site title", "new page", "insert title here",
    "title of the document", "your site name", "your website name", "your company name",
    "site name here", "your title here", "document title", "example domain",
})

#: Trailing punctuation stripped before a scaffold-title comparison.
_TITLE_TRIM = " \t\r\n.!?:;\"'“”‘’|-–—"


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProseFinding:
    """One placeholder-prose observation at a named file and line."""

    rule: str
    severity: str
    path: str
    line: int
    detail: str

    def render(self) -> str:
        """The one-line human finding (the shape :meth:`ProseResult.findings_lines` emits)."""
        return f"[{self.severity}] {self.rule} — {self.path}:{self.line}: {self.detail}"

    def means(self) -> str:
        """What this finding means to a NON-CODER, in one sentence.

        Every rule carries one, and every finding CARRIES ITS OWN into the sidecar — not only
        the HIGH ones the band and the card render. Without this the MEDIUM tier's three
        sentences would exist in :data:`RULE_PLAIN_LANGUAGE` and be reachable from nothing,
        which is the built-but-wired-into-nothing shape this project keeps finding: a string
        no renderer consults is the same defect as a control no caller calls, in a smaller
        coat."""
        return RULE_PLAIN_LANGUAGE.get(self.rule, "")


#: The four states this instrument can be in, spelled as constants because THREE of them are
#: routinely collapsed into "clean" by a caller in a hurry, and the collapse is the whole
#: defect class #1223 exists to refuse.
DISPOSITION_UNMEASURED = "unmeasured"
#: Measured, and there is no user-visible prose surface here at all — a Python library, a
#: command-line tool. NOT the same statement as "the words are fine", and kept apart from
#: :data:`DISPOSITION_CLEAN` for exactly that reason: the scan did not approve anything.
DISPOSITION_NOT_APPLICABLE = "not-applicable"
DISPOSITION_CLEAN = "clean"
DISPOSITION_PLACEHOLDER = "placeholder-found"


@dataclass(frozen=True)
class ProseResult:
    """The placeholder-prose scan of one delivered tree.

    ``measured`` is the honesty bit and carries the same contract as its sibling
    ``SecurityResult.measured``: an empty ``findings`` tuple means "nothing found" ONLY when
    ``measured`` is True, and the two fields are INDEPENDENT — a walk interrupted after
    finding lorem ipsum reports both facts, never one instead of the other.

    ``applicable`` is the SECOND honesty bit, and it exists because this instrument has a
    fourth state its sibling does not: a tree with no user-visible prose in it. A Python
    library is not clean prose, it is an absence of prose, and reporting "clean (0 pages)"
    for one would be this module claiming to have approved something it never read. Callers
    must branch on :meth:`disposition`, which cannot express the collapse, rather than on the
    two booleans separately."""

    findings: tuple[ProseFinding, ...] = ()
    measured: bool = False
    applicable: bool = False
    status: str = "placeholder-prose scan did not run"
    pages_scanned: int = 0

    @property
    def worst_severity(self) -> Optional[str]:
        """The highest severity present, or ``None`` when there are no findings."""
        if not self.findings:
            return None
        return max((f.severity for f in self.findings), key=lambda s: SEVERITY_ORDER.get(s, 0))

    def at_or_above(self, severity: str) -> tuple[ProseFinding, ...]:
        """Every finding at *severity* or worse (the band's and the card's input)."""
        floor = SEVERITY_ORDER.get(severity, 0)
        return tuple(f for f in self.findings if SEVERITY_ORDER.get(f.severity, 0) >= floor)

    def disposition(self) -> str:
        """WHICH OF THE FOUR STATES THIS IS — the single read every consumer should make.

        The order is the contract. ``measured`` is asked FIRST, because a scan that could not
        run knows nothing about applicability either; ``applicable`` is asked SECOND, because
        a tree with no pages has no findings for a trivial reason and must never borrow the
        word "clean" from a tree that was read. Only then does the finding list decide."""
        if not self.measured:
            return DISPOSITION_UNMEASURED
        if not self.applicable:
            return DISPOSITION_NOT_APPLICABLE
        if self.findings:
            return DISPOSITION_PLACEHOLDER
        return DISPOSITION_CLEAN

    def is_clean(self) -> bool:
        """True ONLY for a tree that HAD pages, was read, and carried no placeholder prose.

        Deliberately False for a Python library: this scan approves what it read, and it read
        nothing there. A caller wanting "is there anything to worry about here?" should ask
        :meth:`disposition` — the two questions differ precisely where it matters."""
        return self.disposition() == DISPOSITION_CLEAN

    def findings_lines(self) -> list[str]:
        """The human finding lines, worst first (the honest report)."""
        ordered = sorted(self.findings,
                         key=lambda f: (-SEVERITY_ORDER.get(f.severity, 0), f.path, f.line))
        return [f.render() for f in ordered]

    def summary(self) -> str:
        """A single capped line for the scorecard evidence stamp, four-way by construction.

        An unfinished scan that nonetheless FOUND something states both halves, on the same
        reasoning its sibling records: reporting only "could-not-determine" would drop the
        findings out of the stamp while the rollup went on counting them, leaving one
        instrument contradicting itself about one run."""
        if not self.measured and not self.findings:
            return f"could-not-determine: {self.status}"[:EVIDENCE_VALUE_CAP]
        if not self.measured:
            rules = ", ".join(sorted({f.rule for f in self.findings}))
            return (f"PARTIAL SCAN — {len(self.findings)} placeholder finding(s): "
                    f"{rules}")[:EVIDENCE_VALUE_CAP]
        if not self.applicable:
            return (f"not-applicable: no user-visible prose surface "
                    f"({self.status})")[:EVIDENCE_VALUE_CAP]
        if not self.findings:
            return f"no placeholder prose ({self.pages_scanned} page(s) read)"[:EVIDENCE_VALUE_CAP]
        counts = {s: sum(1 for f in self.findings if f.severity == s)
                  for s in (SEVERITY_HIGH, SEVERITY_MEDIUM, SEVERITY_INFO)}
        head = ", ".join(f"{n} {s}" for s, n in counts.items() if n)
        rules = ", ".join(sorted({f.rule for f in self.findings}))
        return f"{head}: {rules}"[:EVIDENCE_VALUE_CAP]


# ---------------------------------------------------------------------------
# Visible-text extraction (the reason this is a parse and not a grep)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VisibleText:
    """What a delivered page actually SAYS, as the scan sees it.

    ``runs`` are ``(line, text)`` for every visible text node and every read attribute.
    ``elements`` are ``(line, tag, whole normalised text)`` for the title-bearing tags, which
    the scaffold-title rule matches WHOLE rather than by substring.

    ``truncated`` says the page WENT SILENT before its end: a ``<pre>``/``<code>``/``<template>``
    that was opened and never closed suppresses every remaining text node, so ``runs`` stops
    describing the page somewhere in the middle. It is a separate fact from an unparseable page
    and it is the more dangerous one, because the parse SUCCEEDS and the missing half looks
    exactly like a page with nothing more to say."""

    runs: tuple[tuple[int, str], ...] = ()
    elements: tuple[tuple[int, str, str], ...] = ()
    truncated: bool = False


class _VisibleTextParser(HTMLParser):
    """Collect user-visible text from a delivered page, dropping mechanism.

    Lenient by construction — a delivered page is frequently not well-formed, and refusing to
    read one would blind the scan on exactly the sloppy deliverables most likely to carry
    filler. Unclosed title tags simply never emit an element; their text is still collected as
    a run, so the unambiguous rules still see it."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.runs: list[tuple[int, str]] = []
        self.elements: list[tuple[int, str, str]] = []
        self._suppress = 0
        self._open: list[tuple[int, str, list[str]]] = []

    @property
    def unbalanced_suppression(self) -> bool:
        """True when a suppressing element was opened and never closed.

        The counter only ever decrements on a MATCHING end tag (and never below zero), so a
        non-zero value at close means the rest of the document was swallowed. Read by
        :func:`extract_visible_text` rather than left as a private detail: a scan whose input
        silently ended early has to be able to SAY so."""
        return self._suppress != 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        name = tag.lower()
        if name in _SUPPRESSED_TAGS:
            self._suppress += 1
            return
        if self._suppress:
            # ONE SUPPRESSION CONTRACT, BOTH HALVES. :meth:`handle_data` drops element text
            # inside a suppressed region; the attribute read below must drop attributes there
            # too, or the module holds two opposite positions about the same ``<template>``.
            # An ``alt`` on an image inside a template is markup a component will clone, not
            # words this page says to anybody — the identical claim that keeps the template's
            # element text out.
            return
        if name in _TITLE_TAGS:
            self._open.append((self.getpos()[0], name, []))
        for attr, value in attrs:
            if value and attr.lower() in _READ_ATTRS:
                self.runs.append((self.getpos()[0], value))

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower()
        if name in _SUPPRESSED_TAGS:
            self._suppress = max(0, self._suppress - 1)
            return
        for index in range(len(self._open) - 1, -1, -1):
            if self._open[index][1] != name:
                continue
            line, opened, parts = self._open[index]
            del self._open[index:]
            self.elements.append((line, opened, " ".join(parts)))
            return

    def handle_data(self, data: str) -> None:
        if self._suppress or not data.strip():
            return
        self.runs.append((self.getpos()[0], data))
        for _line, _tag, parts in self._open:
            parts.append(data)


def extract_visible_text(html: str) -> Optional[VisibleText]:
    """The user-visible words of one page, or ``None`` when it could not be parsed.

    ``None`` is a REAL answer, not an error swallowed: the caller counts it, falls back to the
    raw unambiguous tier, and NAMES the count in the result status. A page silently downgraded
    to a weaker rule set is the #1183 shape — a check that went blind without saying so.

    ``None`` is also the RARER answer, measured rather than assumed: ``html.parser`` is lenient
    enough that truncated tags, stray ``<<<>>>``, NUL bytes, thousand-deep nesting and
    unterminated attributes all parse. The path that DOES fire is the one reported through
    :attr:`VisibleText.truncated` — an unclosed suppressing tag — and it used to be the only
    silencing vector here that nothing counted."""
    parser = _VisibleTextParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 - any parser fault is "could not read this page", not a crash
        return None
    return VisibleText(tuple(parser.runs), tuple(parser.elements),
                       truncated=parser.unbalanced_suppression)


def _normalise_title(text: str) -> str:
    """A title reduced to the form :data:`_SCAFFOLD_TITLES` is keyed on."""
    return re.sub(r"\s+", " ", text).strip(_TITLE_TRIM).strip().lower()


def _snippet(text: str) -> str:
    """One capped, single-line excerpt of matched copy for the finding detail."""
    return re.sub(r"\s+", " ", text).strip()[:_SNIPPET_CAP]


# ---------------------------------------------------------------------------
# The rules
# ---------------------------------------------------------------------------


def _fill_in_by_shape(rel_path: str, line: int, text: str) -> list[ProseFinding]:
    """The fill-in-the-blank findings that depend on the instruction's SHAPE, not just its words.

    An instruction to fill something in OCCUPIES its slot — it is the whole of a heading, a
    table cell, a sponsor box. Genuine copy reusing the same words is surrounded by the rest of
    the sentence. So the fragment is trimmed of its markup, whitespace and terminal punctuation
    and then matched WHOLE (:data:`_FILL_IN_BARE_RES`) or at its END
    (:data:`_FILL_IN_TAIL_RES`), never as a floating substring.

    This is the narrowing that keeps the tier honest enough to stay at HIGH. HIGH moves a band
    and takes the operator's single caveat slot away from whatever else the audit found, so a
    false one does not merely add noise — it evicts a true statement and replaces it with a
    wrong one."""
    out: list[ProseFinding] = []
    for fragment in _FRAGMENT_SPLIT_RE.split(text):
        candidate = fragment.strip(_FRAGMENT_TRIM).strip()
        if not candidate:
            continue
        for pattern in _FILL_IN_BARE_RES:
            if pattern.fullmatch(candidate):
                out.append(ProseFinding(RULE_FILL_IN_THE_BLANK,
                                        RULE_SEVERITY[RULE_FILL_IN_THE_BLANK],
                                        rel_path, line, _snippet(candidate)))
        for pattern in _FILL_IN_TAIL_RES:
            match = pattern.search(candidate)
            if match and match.end() == len(candidate):
                out.append(ProseFinding(RULE_FILL_IN_THE_BLANK,
                                        RULE_SEVERITY[RULE_FILL_IN_THE_BLANK],
                                        rel_path, line, _snippet(match.group(0))))
    return out


def _match_unambiguous(rel_path: str, line: int, text: str) -> list[ProseFinding]:
    """The tier that holds WHEREVER it is found — Latin filler, fill-in-the-blank copy, and
    the long framework demo phrases.

    UNAMBIGUOUS HERE MEANS CONTEXT-INDEPENDENT, WHICH IS NOT THE SAME AXIS AS SEVERITY, and
    conflating the two is the easiest way to misread this module. These three survive the loss
    of context that sends a component file to the raw path — "lorem ipsum" is lorem ipsum in
    an attribute, in a comment and in a paragraph alike, and a forty-character Bootstrap demo
    sentence is that sentence wherever it appears. Their SEVERITY is decided separately by
    :data:`RULE_SEVERITY`: the first two are HIGH because they cannot be what the operator
    asked for, while starter boilerplate is MEDIUM because a template's example sentence could
    conceivably be left deliberately.

    Context-independent does NOT mean position-independent, and :func:`_fill_in_by_shape` is
    where that distinction is spent: "your text here" is an instruction wherever it is found,
    but only when it is the whole of what its slot says."""
    out: list[ProseFinding] = []
    for match in _LOREM_RE.finditer(text):
        out.append(ProseFinding(RULE_LOREM_IPSUM, RULE_SEVERITY[RULE_LOREM_IPSUM],
                                rel_path, line, _snippet(match.group(0))))
    out.extend(_fill_in_by_shape(rel_path, line, text))
    for pattern in _FILL_IN_RES:
        for match in pattern.finditer(text):
            out.append(ProseFinding(RULE_FILL_IN_THE_BLANK,
                                    RULE_SEVERITY[RULE_FILL_IN_THE_BLANK],
                                    rel_path, line, _snippet(match.group(0))))
    for pattern in _STARTER_RES:
        for match in pattern.finditer(text):
            out.append(ProseFinding(RULE_STARTER_BOILERPLATE,
                                    RULE_SEVERITY[RULE_STARTER_BOILERPLATE],
                                    rel_path, line, _snippet(match.group(0))))
    return out


def _match_visible_only(rel_path: str, line: int, text: str) -> list[ProseFinding]:
    """The tier that needs to know the text is PROSE — template contact details.

    Runs only over parsed visible text, never over raw source, because every pattern here is
    a legitimate ``placeholder`` attribute value and convicting it there would punish the
    deliverable that wrote a correct form hint."""
    out: list[ProseFinding] = []
    for pattern in _CONTACT_RES:
        for match in pattern.finditer(text):
            out.append(ProseFinding(RULE_PLACEHOLDER_CONTACT,
                                    RULE_SEVERITY[RULE_PLACEHOLDER_CONTACT],
                                    rel_path, line, _snippet(match.group(0))))
    return out


def scan_visible(rel_path: str, visible: VisibleText) -> list[ProseFinding]:
    """Every finding in one PARSED page — the full rule set."""
    out: list[ProseFinding] = []
    for line, text in visible.runs:
        out.extend(_match_unambiguous(rel_path, line, text))
        out.extend(_match_visible_only(rel_path, line, text))
    for line, tag, whole in visible.elements:
        if _normalise_title(whole) in _SCAFFOLD_TITLES:
            out.append(ProseFinding(RULE_SCAFFOLD_TITLE, RULE_SEVERITY[RULE_SCAFFOLD_TITLE],
                                    rel_path, line, f"<{tag}> is {_snippet(whole)!r}"))
    return out


def scan_raw(rel_path: str, text: str) -> list[ProseFinding]:
    """Every UNAMBIGUOUS finding in one unparsed source — the template/component path.

    The weaker half of the scan, and the docstring says so rather than letting a caller infer
    equal coverage: a component file that carries a placeholder phone number in its visible
    markup is not detected here, because at this tier the scan cannot tell that markup from a
    form hint."""
    lines = text.splitlines()
    out: list[ProseFinding] = []
    for index, line_text in enumerate(lines, start=1):
        out.extend(_match_unambiguous(rel_path, index, line_text))
    return out


# ---------------------------------------------------------------------------
# The repo scan
# ---------------------------------------------------------------------------


def _dedupe(findings: list[ProseFinding]) -> list[ProseFinding]:
    """Collapse findings two patterns reported at the same rule, file and line, keeping the
    sharpest severity. The corpora overlap on purpose (a lorem paragraph often also trips a
    starter phrase); the operator should see one problem per place, not one per pattern."""
    best: dict[tuple[str, str, int], ProseFinding] = {}
    for finding in findings:
        key = (finding.rule, finding.path, finding.line)
        current = best.get(key)
        if current is None or SEVERITY_ORDER.get(finding.severity, 0) > \
                SEVERITY_ORDER.get(current.severity, 0):
            best[key] = finding
    return list(best.values())


def _is_skipped(path: Path, root: Path) -> bool:
    """Does *path* lie inside a skipped directory WITHIN the delivered tree?

    Compared RELATIVE to *root*, for the reason the sibling scan's own version records: a
    deliverable that happens to live under a ``venv`` or a ``node_modules`` on this machine
    matched on an ANCESTOR and skipped the entire tree, reporting a scan that reached nothing.
    Where a tree sits says nothing about what is in it."""
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    return any(part in _SKIP_DIRS for part in relative.parts)


def _present_skipped_dirs(root: Path) -> list[str]:
    """The skipped directories that ACTUALLY EXIST in this tree, so the status can name the
    blind spot rather than leave a reader to assume "no placeholders" meant "everywhere"."""
    found: set[str] = set()
    try:
        for path in root.rglob("*"):
            try:
                parts = set(path.relative_to(root).parts)
            except ValueError:
                continue
            found |= parts & _SKIP_DIRS
            if len(found) >= len(_SKIP_DIRS):
                break
    except OSError:
        return sorted(found)
    return sorted(found)


def _iter_web_files(root: Path) -> Iterable[Path]:
    """Every page and template under *root*, dependency and VCS trees excluded."""
    count = 0
    for path in sorted(root.rglob("*")):
        if count >= _MAX_FILES:
            return
        try:
            if not path.is_file():
                continue
        except OSError:
            continue
        if _is_skipped(path, root):
            continue
        suffix = path.suffix.lower()
        if suffix not in _PAGE_SUFFIXES and suffix not in _TEMPLATE_SUFFIXES:
            continue
        if _SKIP_FILE_RE.search(path.name):
            continue
        count += 1
        yield path


def scan_repo(repo: Optional[Path], surface: str = "") -> ProseResult:
    """Scan one delivered tree for placeholder prose and return the honest :class:`ProseResult`.

    *surface* is accepted for signature parity with the package's other injected checks and is
    recorded in the status; it never gates WHICH files are read, because the surface is the
    card's CLAIM about the deliverable rather than a reading of it. A tree that contains pages
    gets them scanned whatever the card said it would build, and a tree that contains none
    reports NOT APPLICABLE whatever the card said — which is how a ``web`` card that shipped
    no page at all stays distinguishable from a library that correctly has none.

    Total by construction. A missing or unreadable tree yields ``measured=False`` with a
    status naming the reason; it never yields an empty-and-clean result."""
    if repo is None:
        return ProseResult(status="no delivered tree to scan (repo not resolved)")
    root = Path(repo)
    try:
        if not root.is_dir():
            return ProseResult(status=f"delivered tree not found at {root.name}")
    except OSError as exc:
        return ProseResult(status=f"delivered tree unreadable ({type(exc).__name__})")

    findings: list[ProseFinding] = []
    pages = 0
    templates = 0
    unreadable = 0
    unparsed = 0
    silenced = 0
    truncated = False
    skipped_dirs = _present_skipped_dirs(root)
    try:
        for path in _iter_web_files(root):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")[:_MAX_FILE_BYTES]
            except OSError:
                unreadable += 1
                continue
            try:
                rel = str(path.relative_to(root)).replace("\\", "/")
            except ValueError:
                rel = path.name
            if path.suffix.lower() in _PAGE_SUFFIXES:
                pages += 1
                visible = extract_visible_text(text)
                if visible is None:
                    # NAMED, never absorbed: this page fell to the weaker tier, and a reader
                    # told "no placeholder prose" is entitled to know which rules did not run
                    # on which file.
                    unparsed += 1
                    raw = scan_raw(rel, text)
                else:
                    raw = scan_visible(rel, visible)
                    if visible.truncated:
                        # THE SILENCING VECTOR THAT PARSES. An unclosed <pre>/<code>/<template>
                        # suppresses every remaining text node, so the visible scan read the top
                        # of the page and reported CLEAN on a bottom it never saw — measured:
                        # lorem ipsum after an unclosed <pre> produced zero findings and a clean
                        # disposition. FAIL TOWARD DISCLOSURE: the page is counted, NAMED in the
                        # status, and re-run through the unambiguous tier over its raw source,
                        # which is the same fallback an unparseable page already gets and for
                        # the same reason — the parse could not be trusted, so only the rules
                        # that hold without it apply. _dedupe collapses the overlap.
                        silenced += 1
                        raw = raw + scan_raw(rel, text)
            else:
                templates += 1
                raw = scan_raw(rel, text)
            raw = _dedupe(raw)
            if _TEST_PATH_RE.search(rel):
                raw = [ProseFinding(f.rule, _DEMOTE.get(f.severity, f.severity),
                                    f.path, f.line, f.detail) for f in raw]
            if len(findings) < _MAX_FINDINGS:
                findings.extend(raw)
            else:
                # Past the cap the list is a SEVERITY record rather than a full one: keep
                # every HIGH so the band and the worst-severity read stay true, and drop the
                # rest rather than let a truncation decide the band.
                truncated = True
                findings.extend(f for f in raw if f.severity == SEVERITY_HIGH)
                if len(findings) >= _MAX_HIGH_FINDINGS:
                    break
    except OSError as exc:
        # A tree that became unwalkable mid-scan: keep what was found, but the result is
        # explicitly PARTIAL — an interrupted scan must never read as a completed one.
        return ProseResult(tuple(findings), measured=False, applicable=bool(pages + templates),
                           status=f"scan interrupted after {pages + templates} file(s) "
                                  f"({type(exc).__name__})",
                           pages_scanned=pages + templates)

    scanned = pages + templates
    if scanned == 0:
        # MEASURED and NOT APPLICABLE — the state this instrument has and its sibling does
        # not. The tree was read; it simply has no user-visible prose in it, which is the
        # correct and expected answer for a library or a command-line tool. Reporting it as
        # "clean" would be this scan claiming to have approved words it never saw.
        return ProseResult(
            measured=True, applicable=False, pages_scanned=0,
            status=f"no delivered web page or template found in {root.name}"
                   + (f" [surface: {surface}]" if surface else ""),
        )

    status = f"read {pages} page(s) and {templates} template(s)"
    if unreadable:
        status += f", {unreadable} unreadable"
    if skipped_dirs:
        status += f", NOT read: {'/, '.join(skipped_dirs)}/"
    if unparsed:
        status += (f", {unparsed} page(s) did not parse (unambiguous rules only on those — "
                   f"contact and title rules did not run)")
    if silenced:
        status += (f", {silenced} page(s) went silent mid-document on an unclosed code or "
                   f"template tag (unambiguous rules re-run over their raw source; contact "
                   f"and title rules did not run past the break)")
    if scanned >= _MAX_FILES:
        status += f", file list capped at {_MAX_FILES} (coverage is partial)"
    if truncated:
        status += f", finding list capped at {_MAX_FINDINGS} (high-severity findings kept in full)"
    if surface:
        status += f" [surface: {surface}]"
    return ProseResult(tuple(findings), measured=True, applicable=True, status=status,
                       pages_scanned=scanned)


# ---------------------------------------------------------------------------
# The consequence gate
# ---------------------------------------------------------------------------


def prose_band_enabled(cfg: object = None) -> bool:
    """May this scan's findings move the band and take the operator's caveat slot?

    Resolved from ``[fleet_dispatch].green_quality_prose_band`` in the AO ``default.toml`` — the
    file CLAUDE.md names as the authority for what is live and what is dormant — through the
    harness's own loader, the same way :func:`~.layer1.default_seed_root` resolves the fleet
    root rather than hardcoding one machine's answer.

    VALIDATED, NOT COERCED (the #1042 rule): only an explicit TOML boolean ``true`` grants it. A
    quoted ``"false"`` — the shape a hand-edited rollback takes — is not a grant, and neither is
    ``1`` or a non-empty string.

    FAIL-CLOSED in every direction: a missing config, an unreadable one, a malformed one, a fault
    inside the loader, and a fault while READING THE RESOLVED VALUE all resolve to False. The read
    sits inside the guard deliberately. A version of this function guarded only the load and left
    the attribute access outside it, so a cfg whose property raised would have propagated out of a
    function whose docstring promised a denial — this project treats a fail-closed docstring as a
    security assertion, not as a description of the common case. The consequence is the part a
    mistake makes expensive; the measurement runs regardless and is not gated by this function."""
    try:
        if cfg is None:
            # Deferred so this leaf module stays importable without the harness config chain,
            # exactly as layer1's seed-root resolver defers its own import.
            from ..config import load_harness_config

            cfg = load_harness_config()
        return getattr(cfg, "green_quality_prose_band_enabled", False) is True
    except Exception:  # noqa: BLE001 — a config fault denies; it never sinks an advisory audit
        return False
