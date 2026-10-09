"""Ask whether the DELIVERED SITE satisfies the operator's own stated criteria.

Why this exists
---------------
``tools/probes/requirement_coverage_report.py`` (#1374) is honest and working, and it
answers a different question: *did the EXAM cover his requirements?* It is therefore
downstream of an exam existing. On the runs where ``acceptance-tests`` was skipped there
was no exam, so that report correctly said nothing at all -- and nobody was asking the
other question.

On 2026-08-16 the operator opened a delivered site and found it failed four of his eight
stated criteria (#1343). Every fact he used was already on disk when the run finished:
his criteria in ``acceptance.json`` ``spec.criteria``, the delivered tree in
``operator-review/<stamp>-<project>/public``. No exam, no oracle and no graphics card are
needed to join them, which is what this does.

The three states, and why the third is mandatory
------------------------------------------------
Every criterion resolves to ``SATISFIED``, ``NOT SATISFIED`` or ``NOT DECIDABLE``. The
third is not a hedge, it is the discipline: a criterion this instrument cannot decide must
never render as passing. "The website should launch without crashing" is the honest
example -- this probe starts nothing, so it reports NOT DECIDABLE rather than inferring a
green from a file listing. Absences rendered as confident values are the defect the whole
instrument-honesty arc (#1241) exists to remove.

The asymmetry on judgement criteria is deliberate. "Visually consistent and clean" can be
FALSIFIED mechanically -- a stylesheet whose own layout wrapper is applied to no page is a
concrete defect -- but it cannot be CONFIRMED mechanically, because the absence of that one
defect says nothing about how the page looks. So that check can return NOT SATISFIED or
NOT DECIDABLE and never SATISFIED, and it says so in its own output.

Existence is not reachability -- the defect class this file keeps re-finding
---------------------------------------------------------------------------
Three of the checks below were once written as "the code is there", and all three were
wrong in the same way: something UPSTREAM stops the code being reached, so the feature
exists and still does not happen. They are named together because the next check added
here will be tempted by the same shortcut.

  * per-field validation messages behind the browser's own constraint validation: the
    `required` attribute makes the browser block a blank submission before the page's
    `submit` handler runs, so the custom message cannot fire for the blank case;
  * enquiry storage in a file using ES module syntax that the page loads as a classic
    `<script src>`: the browser discards the whole file with a SyntaxError;
  * a page link, or storage code, living inside such a discarded file -- the mirror image,
    where dead code makes something look reachable rather than looking broken.

Two further instances were found by sweeping the registry for this shape on 2026-08-17 and
are fixed here: the orphan audit counted links inside scripts the browser never runs, and
the storage check matched an API path without its HTTP METHOD, so a server implementing
only `GET /api/enquiries` would have been credited with storing his POSTed enquiries. Both
were latent on real data when found, and latent is not the same as safe. The shared-data,
filter and layout checks were examined for the same shape and do not have it: each already
reads only script the browser will run.

What it is not
--------------
Advisory. It reports; it never fails a build (the operator's direction on #1435/#1437,
2026-08-16). Every verdict carries the name of the heuristic that produced it so a reader
can discount it, because several of them are string-matching over source text and will be
wrong in ways a reader who knows the site can spot instantly.

Usage
-----
    python tools/probes/delivery_criteria_report.py                    # newest delivery
    python tools/probes/delivery_criteria_report.py <delivery-dir-name>
    python tools/probes/delivery_criteria_report.py --all
    python tools/probes/delivery_criteria_report.py --json
    python tools/probes/delivery_criteria_report.py \
        --delivery-path <path/to/delivery> --criteria <path/to/acceptance.json>
"""

from __future__ import annotations

import argparse
import inspect
import json
import os
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_STATE_ROOT = Path(
    os.environ.get("BLARAI_FLEET_STATE_ROOT", r"C:/Users/mrbla/agentic-setup/state")
)

#: Artifact sentinels, same contract as ``tools/probes/harvest_run_evidence.py``: a thing
#: that is not there must never arrive at a caller as a falsy measurement.
ABSENT = "ABSENT"
UNREADABLE = "UNREADABLE"

#: Verdict states. Exactly three, and the third one is the point.
SATISFIED = "SATISFIED"
NOT_SATISFIED = "NOT SATISFIED"
NOT_DECIDABLE = "NOT DECIDABLE"

_HTML_TAG = re.compile(r"<html\b", re.IGNORECASE)
_REDIRECT = re.compile(r"""(?:location\s*\.\s*(?:href|replace)\s*[=(]|meta[^>]+http-equiv\s*=\s*["']refresh)""", re.IGNORECASE)
_NAV_BLOCK = re.compile(r"<nav\b[^>]*>(.*?)</nav\s*>", re.IGNORECASE | re.DOTALL)
_HREF = re.compile(r"""<a\b[^>]*href\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_SCRIPT_SRC = re.compile(r"""<script\b([^>]*?)src\s*=\s*["']([^"']+)["']([^>]*)>""", re.IGNORECASE)
_SCRIPT_INLINE = re.compile(r"<script\b(?![^>]*\bsrc\s*=)[^>]*>(.*?)</script\s*>", re.IGNORECASE | re.DOTALL)
_MODULE_SYNTAX = re.compile(r"^\s*(?:export\s|export\{|import\s+[\w{*'\"])", re.MULTILINE)
_CLASS_ATTR = re.compile(r"""class\s*=\s*["']([^"']*)["']""", re.IGNORECASE)
_CSS_CLASS = re.compile(r"\.([A-Za-z_][-\w]*)")
_FETCH = re.compile(r"""fetch\(\s*["']([^"']+)["']""")
#: Per-field error writes. Two details are load-bearing and both were found by measuring
#: the banked deliveries rather than by reasoning:
#:   * case-insensitive and tolerant of both `name-error` and `nameError`. The three
#:     deliveries use BOTH conventions, and a case-sensitive hyphen-only pattern scored a
#:     page carrying eleven of these as having zero.
#:   * the right-hand side must be NON-EMPTY. `errorEl.textContent = ''` CLEARS a message;
#:     counting it as feedback inflated one page from 11 to 16. A negative lookahead does
#:     not do this -- `\s*` backtracks to zero width and the lookahead then passes on the
#:     space -- so the requirement is written positively instead.
_ERROR_WRITE = re.compile(
    r"""(?:getElementById|querySelector)\(\s*["'][^"']*error[^"']*["']\s*\)\s*\.\s*"""
    r"""(?:textContent|innerHTML|innerText)\s*=\s*(?:['"`][^'"`]|[A-Za-z_$(])""",
    re.IGNORECASE,
)
#: Layout wrapper classes. A stylesheet that DEFINES one of these and applies it to no page
#: is the concrete, falsifiable form of "the pages do not share a layout".
_LAYOUT_CLASSES = frozenset({"container", "wrapper", "layout", "page-wrapper", "site-wrapper"})

#: The entry document a static server hands out for "/". Reachable by construction, so it
#: is never counted as an orphan.
_ENTRY_NAMES = frozenset({"index.html", "index.htm"})


# --------------------------------------------------------------------------------------
# Reading the delivered tree
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Script:
    """One ``<script src=...>`` a page loads, and whether the browser can run it."""

    src: str
    path: Path | None
    is_module: bool
    text: str
    #: ES module syntax in a file loaded as a CLASSIC script. The browser raises a
    #: SyntaxError and the ENTIRE file is discarded, so everything it defines is missing at
    #: runtime. This is not a style nit; it is why one banked delivery's contact form
    #: stores nothing despite carrying working storage code.
    dead: bool


@dataclass
class Page:
    path: Path
    name: str
    text: str
    inline_js: str
    scripts: list[Script]

    @property
    def is_fragment(self) -> bool:
        """No ``<html>`` element -- a snippet meant to be injected, not a page."""
        return not _HTML_TAG.search(self.text)

    @property
    def is_redirect(self) -> bool:
        """A stub whose only job is to forward. It carries no menu and no content."""
        return bool(_REDIRECT.search(self.text)) and not _NAV_BLOCK.search(self.text)

    @property
    def is_content_page(self) -> bool:
        return not self.is_fragment and not self.is_redirect

    @property
    def live_js(self) -> str:
        """Every line of script the browser will actually execute for this page.

        Dead scripts are excluded on purpose: counting a function the browser never
        defines is how "the code is there" becomes "the feature works".
        """
        return "\n".join([self.inline_js] + [s.text for s in self.scripts if not s.dead])


@dataclass
class Delivery:
    """Static facts about one delivered tree. Computed once, read by every check."""

    root: Path
    public: Path
    pages: list[Page] = field(default_factory=list)
    server_js: str = ""
    css_text: str = ""
    css_classes: set[str] = field(default_factory=set)

    @property
    def content_pages(self) -> list[Page]:
        return [p for p in self.pages if p.is_content_page]

    @property
    def fragments(self) -> list[Page]:
        return [p for p in self.pages if p.is_fragment]

    @property
    def redirect_stubs(self) -> list[Page]:
        return [p for p in self.pages if not p.is_fragment and p.is_redirect]

    def page(self, name: str) -> Page | None:
        return next((p for p in self.pages if p.name == name), None)

    def runnable_scripts(self) -> list[Path]:
        """Script files at least one page loads in a way the browser will actually run.

        A file no page loads, or that every page loads as a classic script while it uses
        ES module syntax, never executes -- so nothing it contains can make a page
        reachable. Without this, the orphan audit had the MIRROR IMAGE of the defect the
        blank-field check has: it credited a link living in code that cannot run.
        """
        runnable: set[Path] = set()
        for page in self.pages:
            for script in page.scripts:
                if script.path is not None and not script.dead:
                    runnable.add(script.path)
        return sorted(runnable)

    def referenced_by(self, page: Page) -> list[str]:
        """Which OTHER delivered files name this page's file. Deliberately generous.

        Any occurrence of the filename counts -- an ``href``, a ``location.href``, a
        template string inside an injected header. Being generous is the safe direction:
        an orphan claim should be hard to make, so a page called unreachable here is
        unreachable under a rule that tried hard to find a way in.

        Generous about the FORM of the reference, not about whether the code runs: a
        script the browser discards is not a way in, and a page whose own reachability is
        unresolved is still counted (chain reachability is not computed here).
        """
        token = re.compile(rf"(?<![-\w]){re.escape(page.name)}(?![-\w])")
        hits: list[str] = []
        for other in self.pages:
            if other.name == page.name:
                continue
            if token.search(other.text):
                hits.append(other.name)
        for js in self.runnable_scripts():
            if token.search(_read_text(js)):
                hits.append(js.name)
        return sorted(set(hits))


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _load_scripts(public: Path, page_text: str) -> list[Script]:
    out: list[Script] = []
    for match in _SCRIPT_SRC.finditer(page_text):
        attrs = f"{match.group(1)} {match.group(3)}"
        src = match.group(2)
        is_module = "module" in attrs
        resolved: Path | None = None
        if not src.startswith(("http://", "https://", "//", "data:")):
            candidate = (public / src.lstrip("/").lstrip("./")).resolve()
            if candidate.is_file():
                resolved = candidate
        text = _read_text(resolved) if resolved else ""
        dead = bool(text) and not is_module and bool(_MODULE_SYNTAX.search(text))
        out.append(Script(src=src, path=resolved, is_module=is_module, text=text, dead=dead))
    return out


def load_delivery(root: Path) -> Delivery:
    """Read one delivered tree. Never raises on a malformed or partial delivery."""
    public = root / "public" if (root / "public").is_dir() else root
    delivery = Delivery(root=root, public=public)

    for path in sorted(public.rglob("*.html")):
        text = _read_text(path)
        inline = "\n".join(_SCRIPT_INLINE.findall(text))
        delivery.pages.append(
            Page(
                path=path,
                name=path.name,
                text=text,
                inline_js=inline,
                scripts=_load_scripts(public, text),
            )
        )

    # Server-side code lives outside `public/` in the fleet's web skeleton. It is read
    # so a client POST can be checked against a route that actually exists.
    for src_dir in (root / "src", root / "server", root / "api"):
        if src_dir.is_dir():
            for js in sorted(src_dir.rglob("*.js")):
                delivery.server_js += _read_text(js)

    for css in sorted(public.rglob("*.css")):
        delivery.css_text += _read_text(css)
    delivery.css_classes = set(_CSS_CLASS.findall(delivery.css_text))
    return delivery


def _classes_used(delivery: Delivery) -> dict[str, set[str]]:
    """Class tokens per page, plus those injected from script template strings."""
    per_page: dict[str, set[str]] = {}
    for page in delivery.pages:
        tokens: set[str] = set()
        for match in _CLASS_ATTR.finditer(page.text):
            tokens.update(match.group(1).split())
        for script in page.scripts:
            if script.dead:
                continue
            for match in _CLASS_ATTR.finditer(script.text):
                tokens.update(match.group(1).split())
        per_page[page.name] = tokens
    return per_page


def _nav_menu(delivery: Delivery, page: Page) -> tuple[str, tuple[str, ...]]:
    """Where this page's menu comes from, and which links it holds.

    Returns ``(source, links)`` where source is ``inline``, ``injected:<file>`` or
    ``none``. A menu written into the page and a menu inserted by a shared script are the
    same menu to the operator, so both count -- but the SOURCE travels with the answer so
    a reader can see which pages depend on JavaScript to grow a header.
    """
    blocks = _NAV_BLOCK.findall(page.text)
    if blocks:
        return "inline", tuple(sorted({h for b in blocks for h in _HREF.findall(b)}))

    for script in page.scripts:
        if script.dead or not script.text:
            continue
        found = _NAV_BLOCK.findall(script.text)
        if found:
            name = script.path.name if script.path else script.src
            return f"injected:{name}", tuple(
                sorted({h for b in found for h in _HREF.findall(b)})
            )
        # The script may fetch an HTML fragment and inject that instead.
        for target in _FETCH.findall(script.text):
            fragment = delivery.page(Path(target).name)
            if fragment is None:
                continue
            found = _NAV_BLOCK.findall(fragment.text)
            if found:
                return f"injected:{fragment.name}", tuple(
                    sorted({h for b in found for h in _HREF.findall(b)})
                )
    return "none", ()


# --------------------------------------------------------------------------------------
# The checks
# --------------------------------------------------------------------------------------


@dataclass
class Finding:
    state: str
    heuristic: str
    evidence: list[str] = field(default_factory=list)


@dataclass
class CriterionVerdict:
    id: str
    text: str
    tier: str
    state: str
    check: str
    heuristic: str
    evidence: list[str]


def _no_web_surface(delivery: Delivery) -> Finding | None:
    """Guard every web check. A delivery with no pages is UNDECIDABLE, not failing.

    This instrument reads static web deliveries. Pointed at anything else -- a Python
    library, a CLI -- it must decline rather than convict, or it becomes a machine for
    marking unfamiliar work as broken.
    """
    if delivery.content_pages:
        return None
    return Finding(
        NOT_DECIDABLE,
        "web-surface-required",
        [
            f"no HTML content pages under {delivery.public}",
            (
                "this instrument reads static web deliveries only; it declines rather than "
                "guessing about anything else"
            ),
        ],
    )


def check_launches(delivery: Delivery) -> Finding:
    """"The website should launch without crashing." -- NOT DECIDABLE, always.

    Deciding this means starting a process and watching it, which this probe deliberately
    does not do. The supporting facts below are printed because they are true and useful,
    NOT because they add up to a verdict: a present start script proves nothing about
    whether the server stays up.
    """
    evidence: list[str] = [
        "this probe starts no process, so it cannot witness a launch either way",
    ]
    pkg = delivery.root / "package.json"
    if pkg.is_file():
        try:
            scripts = (json.loads(_read_text(pkg)).get("scripts") or {})
            start = scripts.get("start")
            evidence.append(
                f"package.json start script: {start!r}" if start
                else "package.json defines no start script"
            )
        except (json.JSONDecodeError, AttributeError):
            evidence.append(f"package.json is present and did not parse ({UNREADABLE})")
    else:
        evidence.append(f"no package.json at the delivery root ({ABSENT})")
    evidence.append(
        "a live answer needs the run's own smoke evidence (exec-smoke-web.png and its "
        "console sidecar), which is a different instrument"
    )
    return Finding(NOT_DECIDABLE, "no-execution-by-design", evidence)


def check_shared_menu(delivery: Delivery) -> Finding:
    """"All pages should have the same heading and menu at the top."

    Heuristic: every content page must carry a ``<nav>`` -- written in the page or
    inserted by a script it loads -- and every one of those menus must hold the SAME set
    of links. Redirect stubs are excluded and named; they forward before a menu could be
    seen.
    """
    guard = _no_web_surface(delivery)
    if guard:
        return guard

    evidence: list[str] = []
    for stub in delivery.redirect_stubs:
        evidence.append(
            f"{stub.name} is a redirect stub -- excluded from this check, named here "
            "rather than dropped silently"
        )
    for frag in delivery.fragments:
        evidence.append(f"{frag.name} is a fragment (no <html>) -- excluded from this check")

    menus: dict[str, tuple[str, tuple[str, ...]]] = {}
    for page in delivery.content_pages:
        menus[page.name] = _nav_menu(delivery, page)

    missing = sorted(n for n, (src, _) in menus.items() if src == "none")
    for name, (src, links) in sorted(menus.items()):
        evidence.append(f"{name}: menu {src}, links {list(links) if links else '[]'}")

    if missing:
        return Finding(
            NOT_SATISFIED,
            "nav-block-present-and-identical-link-set",
            evidence + [f"no menu at all on: {', '.join(missing)}"],
        )

    distinct = {links for _, links in menus.values()}
    if len(distinct) > 1:
        detail = "; ".join(
            f"{sorted(n for n, (_, lk) in menus.items() if lk == links)} -> {list(links)}"
            for links in sorted(distinct)
        )
        return Finding(
            NOT_SATISFIED,
            "nav-block-present-and-identical-link-set",
            evidence + [f"{len(distinct)} different menus are shipped: {detail}"],
        )
    return Finding(
        SATISFIED,
        "nav-block-present-and-identical-link-set",
        evidence
        + [
            "every content page carries a menu and all of them hold the same links",
            (
                "this compares link TARGETS only -- it says nothing about where the header "
                "sits on screen or whether it looks the same"
            ),
        ],
    )


def check_shared_data_source(delivery: Delivery) -> Finding:
    """"The list of pieces and individual piece pages should pull data from a shared source."

    Heuristic: collect every data file each page fetches; two or more pages fetching the
    same file is the shared source. Data delivered by a server-rendered template, or read
    through a helper this probe cannot follow, is invisible here.
    """
    guard = _no_web_surface(delivery)
    if guard:
        return guard

    sources: dict[str, set[str]] = {}
    for page in delivery.content_pages:
        targets = {
            t
            for t in _FETCH.findall(page.text) + _FETCH.findall(page.live_js)
            if t.endswith(".json") or "/api/" in t
        }
        if targets:
            sources[page.name] = targets

    if not sources:
        return Finding(
            NOT_DECIDABLE,
            "shared-fetch-target",
            [
                "no page fetches a .json file or an /api/ route",
                "the data may be server-rendered or inlined, which this probe cannot see",
            ],
        )

    evidence = [f"{name}: fetches {sorted(t)}" for name, t in sorted(sources.items())]
    shared = {
        target
        for target in set().union(*sources.values())
        if sum(target in t for t in sources.values()) >= 2
    }
    if shared:
        return Finding(
            SATISFIED,
            "shared-fetch-target",
            evidence
            + [
                f"{len(shared)} source(s) fetched by two or more pages: {sorted(shared)}",
                (
                    "this proves a shared URL, not that both pages render the same fields "
                    "from it"
                ),
            ],
        )
    return Finding(
        NOT_SATISFIED,
        "shared-fetch-target",
        evidence + ["no data file is fetched by more than one page"],
    )


def check_filtering(delivery: Delivery) -> Finding:
    """"The pieces list should allow filtering by category."

    Heuristic: a page must carry a filter CONTROL (a ``data-filter`` attribute, or an
    element whose id or class names a filter) and script that both reads that control and
    narrows a collection. Either half alone is a control wired to nothing.
    """
    guard = _no_web_surface(delivery)
    if guard:
        return guard

    control = re.compile(r"""data-filter\s*=|(?:id|class)\s*=\s*["'][^"']*filter""", re.IGNORECASE)
    reads = re.compile(r"""data-filter|["'][^"']*filter[^"']*["']""", re.IGNORECASE)
    narrows = re.compile(r"\.filter\(|===\s*(?:category|filter)|category\s*===", re.IGNORECASE)

    evidence: list[str] = []
    for page in delivery.content_pages:
        has_control = bool(control.search(page.text))
        js = page.live_js
        wired = bool(reads.search(js)) and bool(narrows.search(js))
        if has_control or wired:
            evidence.append(f"{page.name}: control={has_control} handler={wired}")
        if has_control and wired:
            return Finding(
                SATISFIED,
                "filter-control-plus-handler",
                evidence
                + [
                    (
                        f"{page.name} carries filter controls and script that reads them and "
                        "narrows a collection"
                    ),
                    (
                        "this does not prove the filtered result is correct, only that the "
                        "control is wired to code that filters"
                    ),
                ],
            )
    if not evidence:
        return Finding(
            NOT_SATISFIED,
            "filter-control-plus-handler",
            ["no page carries a filter control or filtering script"],
        )
    return Finding(
        NOT_SATISFIED,
        "filter-control-plus-handler",
        evidence + ["controls and handler never appear on the same page"],
    )


def _balanced_block(text: str, start: int) -> tuple[int, int]:
    """Span of the first ``{...}`` block at or after ``start``, quote-aware.

    Needed because attributing an error write to the listener that contains it requires
    knowing where each listener's body ENDS, and listeners nest: in two of the three banked
    deliveries the `submit` handler sits inside a `DOMContentLoaded` handler, so a rule
    that took the first enclosing span attributed every write to `DOMContentLoaded` and
    concluded the messages were reachable for blank input. They are not.

    Skips string and template literals so a brace inside `'{'` or a template does not
    unbalance the count. It does NOT skip comments; a lone unmatched brace inside one would
    confuse it, which is why the attribution is reported per bucket rather than asserted.
    """
    open_at = text.find("{", start)
    if open_at < 0:
        return (-1, -1)
    depth = 0
    index = open_at
    quote = ""
    while index < len(text):
        char = text[index]
        if quote:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = ""
        elif char in "\"'`":
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return (open_at, index + 1)
        index += 1
    return (open_at, len(text))


_LISTENER = re.compile(r"""addEventListener\(\s*['"](\w+)['"]""")

#: Events that fire whether or not the browser's constraint validation passes. A message
#: written from one of these reaches a user who left a box empty; a message written from
#: the `submit` handler of a validated form does not.
_BLANK_REACHABLE_EVENTS = frozenset(
    {"blur", "focusout", "input", "change", "keyup", "keydown", "click"}
)

_FORM_BLOCK = re.compile(r"<form\b.*?</form\s*>", re.IGNORECASE | re.DOTALL)
_FORM_TAG = re.compile(r"<form\b[^>]*>", re.IGNORECASE)
_CONTROL_TAG = re.compile(r"<(?:input|select|textarea)\b[^>]*>", re.IGNORECASE)
_REQUIRED_ATTR = re.compile(r"\brequired\b", re.IGNORECASE)
_NOVALIDATE = re.compile(r"\b(?:form)?novalidate\b", re.IGNORECASE)


@dataclass
class FormFeedback:
    """Where a page's per-field messages live, and whether blank input can reach them."""

    in_submit: int = 0
    in_other: int = 0
    other_events: tuple[str, ...] = ()
    unattributed: int = 0
    dead: int = 0
    dead_files: tuple[str, ...] = ()
    controls: int = 0
    required: int = 0
    novalidate: bool = False

    @property
    def total(self) -> int:
        return self.in_submit + self.in_other + self.unattributed

    @property
    def every_control_required(self) -> bool:
        return self.controls > 0 and self.required == self.controls

    @property
    def reachable_for_blank(self) -> bool:
        """Can a message reach someone who left a box EMPTY?

        `unattributed` writes -- a top-level helper the submit handler calls -- count as
        NOT reachable. That is the conservative direction and it is the right one: one
        banked delivery keeps all five of its messages in exactly such a helper, and
        crediting them would restore the false pass this check exists to remove.
        """
        if self.total == 0:
            return False
        if self.in_other:
            return True
        if self.novalidate:
            return True
        return not self.every_control_required

    @property
    def rank(self) -> int:
        """Best-page ordering: reachable beats present-but-gated beats nothing."""
        if self.total == 0:
            return 0
        return 2 if self.reachable_for_blank else 1

    def describe(self, page: str) -> list[str]:
        where = (
            f"{list(self.other_events)} handler(s)"
            if self.other_events
            else "any handler that fires without submitting"
        )
        lines = [
            (
                f"{page}: {self.total} per-field message(s) -- {self.in_submit} in the "
                f"submit handler, {self.in_other} in {where}, {self.unattributed} in a "
                "helper this probe cannot attribute to a listener"
            )
        ]
        if self.dead:
            lines.append(
                f"{page}: {self.dead} more sit in {list(self.dead_files)}, which the "
                "browser cannot load (ES module syntax in a classic <script src>)"
            )
        lines.append(
            f"{page}: {self.required} of {self.controls} form control(s) carry `required`"
            + (
                "; the form sets `novalidate`, so the browser does NOT intercept blank "
                "input and the submit handler runs"
                if self.novalidate
                else (
                    " and the form does not set `novalidate`, so the browser intercepts "
                    "blank input before this code runs"
                    if self.every_control_required
                    else "; at least one control is optional, so blank input reaches the "
                    "handler"
                )
            )
        )
        if self.in_other:
            lines.append(
                f"{page}: {list(self.other_events)} fire regardless of `required`, so a "
                "user who tabs out of an empty box does see the custom message"
            )
        return lines


def _form_feedback(page: Page) -> FormFeedback:
    """Read one page's form, and attribute each message to the listener containing it."""
    facts = FormFeedback()

    block = _FORM_BLOCK.search(page.text)
    tag = _FORM_TAG.search(page.text)
    if block is not None:
        controls = _CONTROL_TAG.findall(block.group(0))
        facts.controls = len(controls)
        facts.required = len([c for c in controls if _REQUIRED_ATTR.search(c)])
        # `formnovalidate` on the submit button disables validation for that button only,
        # which is the same escape from the operator's point of view.
        facts.novalidate = bool(_NOVALIDATE.search(block.group(0))) or bool(
            tag and _NOVALIDATE.search(tag.group(0))
        )

    js = page.live_js
    spans = [
        (match.group(1).lower(), *_balanced_block(js, match.end()))
        for match in _LISTENER.finditer(js)
    ]
    spans = [s for s in spans if s[1] >= 0]

    other_events: set[str] = set()
    for write in _ERROR_WRITE.finditer(js):
        pos = write.start()
        # INNERMOST wins: nested listeners are the norm, not the exception.
        enclosing = [s for s in spans if s[1] <= pos < s[2]]
        if not enclosing:
            facts.unattributed += 1
            continue
        event = max(enclosing, key=lambda s: s[1])[0]
        if event in _BLANK_REACHABLE_EVENTS:
            facts.in_other += 1
            other_events.add(event)
        elif event == "submit":
            facts.in_submit += 1
        else:
            # A wrapper such as DOMContentLoaded with the write directly inside it: not a
            # submit path, but not a per-field trigger either.
            facts.unattributed += 1
    facts.other_events = tuple(sorted(other_events))

    dead = [s for s in page.scripts if s.dead]
    facts.dead = sum(len(_ERROR_WRITE.findall(s.text)) for s in dead)
    facts.dead_files = tuple(s.path.name if s.path else s.src for s in dead)
    return facts


def check_blank_field_feedback(delivery: Delivery) -> Finding:
    """"The contact page should provide feedback if a user leaves a field blank."

    Counting per-field error writes measures that the feedback machinery EXISTS. It does
    not measure that the machinery is REACHABLE for the input his sentence describes, and
    those come apart on a form the browser validates for you.

    The mechanism, and it decides this check. A control carrying the HTML `required`
    attribute is checked by the browser's own interactive constraint validation when the
    form is submitted -- BEFORE the `submit` event fires. A blank required field means the
    browser blocks submission, shows its own bubble, and the page's `submit` handler NEVER
    RUNS. So custom per-field messages written inside that handler can only ever appear for
    input that PASSES `required` and then fails a JavaScript rule: a one-character name, a
    malformed email. The blank case -- the case he named -- is precisely the one they
    cannot cover.

    Three escapes from that, each checked here because each genuinely restores reachability:
      * a message written from a NON-submit listener (`blur`, `input`, `change`, `click`):
        those fire regardless of constraint validation, so tabbing out of an empty box does
        show the custom message;
      * `novalidate` on the form (or `formnovalidate` on its submit button), which turns
        the browser's validation off and lets the submit handler run on blank input;
      * a control that does not carry `required`, whose blank value reaches the handler.

    With none of those, the honest verdict is NOT DECIDABLE, and both halves of that matter.
    SATISFIED would be wrong -- the custom path cannot fire for blank input. NOT SATISFIED
    would be equally wrong -- the machinery is genuinely there and does work for the cases
    it can reach, and whether the browser's own native bubble counts as telling him
    "politely" is a judgement about wording, not a fact this instrument can read.

    Still not proven either way, even at SATISFIED: that the message is polite, that it is
    visible, or that a field this probe cannot attribute is the one he would leave blank.
    """
    guard = _no_web_surface(delivery)
    if guard:
        return guard

    form_pages = [p for p in delivery.content_pages if re.search(r"<form\b", p.text, re.IGNORECASE)]
    if not form_pages:
        return Finding(
            NOT_SATISFIED, "per-field-error-writes", ["no delivered page contains a <form>"]
        )

    evidence: list[str] = []
    best: FormFeedback | None = None
    for page in form_pages:
        facts = _form_feedback(page)
        evidence.extend(facts.describe(page.name))
        if best is None or facts.rank > best.rank:
            best = facts

    assert best is not None
    if best.total == 0:
        return Finding(
            NOT_SATISFIED,
            "per-field-error-writes",
            evidence
            + [
                "no runnable script writes a message into a per-field error element",
                (
                    "a page that validates by assigning to an element held in a variable "
                    "would also score zero here -- see the pattern in the module source"
                ),
            ],
        )
    if best.reachable_for_blank:
        return Finding(
            SATISFIED,
            "per-field-error-writes-reachable-for-blank-input",
            evidence
            + [
                (
                    "this counts writes of error text, not their tone, visibility or "
                    "trigger condition"
                ),
            ],
        )
    return Finding(
        NOT_DECIDABLE,
        "per-field-error-writes-behind-browser-constraint-validation",
        evidence
        + [
            (
                "the messages exist and work for input that passes `required` and then "
                "fails a JavaScript rule; they cannot fire for the BLANK case he named"
            ),
            (
                "SATISFIED would be wrong (the custom path is unreachable for blank "
                "input) and NOT SATISFIED would be wrong (the machinery is genuinely "
                "there) -- whether the browser's own bubble counts as telling him "
                "politely is a judgement, not a fact this instrument can read"
            ),
        ],
    )


def check_enquiry_storage(delivery: Delivery) -> Finding:
    """"The contact page should store submitted enquiries in a readable format."

    Heuristic: find a storage path reachable from the form page -- ``localStorage.setItem``
    in runnable script, or a POST to an API route the delivered server actually implements.
    Storage code the browser cannot load, and posts to a route nothing serves, both count
    as NOT satisfied: the code exists and the enquiry still goes nowhere.
    """
    guard = _no_web_surface(delivery)
    if guard:
        return guard

    form_pages = [p for p in delivery.content_pages if re.search(r"<form\b", p.text, re.IGNORECASE)]
    if not form_pages:
        return Finding(
            NOT_SATISFIED, "reachable-storage-path", ["no delivered page contains a <form>"]
        )

    evidence: list[str] = []
    for page in form_pages:
        live = page.live_js
        if "localStorage.setItem" in live:
            return Finding(
                SATISFIED,
                "reachable-storage-path",
                evidence
                + [
                    f"{page.name}: localStorage.setItem in runnable script",
                    (
                        "browser-local storage satisfies 'stored somewhere readable' only if "
                        "he is willing to read it from the browser -- this probe does not "
                        "judge that"
                    ),
                ],
            )
        posts = [
            t for t in _FETCH.findall(live) + _FETCH.findall(page.text) if t.startswith("/")
        ]
        for route in posts:
            method = _fetch_method(live, route) or _fetch_method(page.text, route) or "GET"
            served = _server_serves(delivery.server_js, route, method)
            evidence.append(
                f"{page.name}: sends {method} to {route}; the delivered server handles "
                f"that route AND that method: {served}"
            )
            if served:
                return Finding(
                    SATISFIED,
                    "reachable-storage-path",
                    evidence
                    + [
                        (
                            "the route exists in the delivered server source and is "
                            "matched for this method; whether it writes anything durable "
                            "is not checked here"
                        )
                    ],
                )
        for script in page.scripts:
            if script.dead and "localStorage.setItem" in script.text:
                name = script.path.name if script.path else script.src
                evidence.append(
                    f"{page.name}: storage code lives in {name}, which uses ES module "
                    "syntax while the page loads it as a classic <script src>. The "
                    "browser discards the whole file, so nothing it defines exists at "
                    "runtime."
                )
        if not posts and not any(s.dead for s in page.scripts):
            evidence.append(f"{page.name}: no storage call and no POST found")

    return Finding(NOT_SATISFIED, "reachable-storage-path", evidence)


_METHOD_OPT = re.compile(r"""method\s*:\s*["'](\w+)["']""", re.IGNORECASE)


def _fetch_method(js: str, route: str) -> str | None:
    """The HTTP method a ``fetch`` to ``route`` sends, read from its options object."""
    for match in re.finditer(rf"""fetch\(\s*["']{re.escape(route)}["']""", js):
        window = js[match.end() : match.end() + 400]
        found = _METHOD_OPT.search(window)
        if found:
            return found.group(1).upper()
    return None


def _server_serves(server_js: str, route: str, method: str) -> bool:
    """Does the delivered server handle this route FOR THIS METHOD?

    Matching the path alone was the same defect class the blank-field check exists to
    remove: the handler exists, and the operation the page performs still cannot reach it.
    A server implementing ``GET /api/enquiries`` and nothing else would have been credited
    with storing his enquiries while every POST returned 404.

    The method is looked for within a window around each mention of the route, because the
    delivered skeleton writes them on one line (``pathname === '/api/x' && req.method ===
    'POST'``). A router that declares its method far from its path would read as unserved,
    which is the safe direction: it understates rather than credits.
    """
    for match in re.finditer(re.escape(route), server_js):
        window = server_js[max(0, match.start() - 200) : match.end() + 200]
        if re.search(rf"\b{re.escape(method)}\b", window, re.IGNORECASE):
            return True
    return False


def _named_page_count(criterion_text: str) -> int | None:
    """How many DISTINCT page kinds his sentence names, or None when it cannot tell.

    "a home page, a pieces list page, individual piece pages, and a contact page" -> 4.
    "All pages should have the same heading" -> None: one bare plural names no kinds.

    None is a real answer and the caller must NOT read it as "no requirement".
    """
    parts = re.split(r",| and ", criterion_text)
    named = sum(1 for part in parts if re.search(r"page", part, re.IGNORECASE))
    return named if named >= 2 else None


def _dangling_links(delivery: Delivery) -> dict[str, list[str]]:
    """Link targets naming an .html file that was NOT delivered, keyed by the linking page.

    The INVERSE of the orphan audit, and the half that was missing. The orphan audit asks
    "is every page I shipped linked from somewhere?" -- which a site gets BETTER at by
    shipping fewer pages. This asks "does every link I wrote go somewhere?", which a site
    gets WORSE at by shipping fewer. One of them had to exist, or deleting work looked
    like improving it.
    """
    delivered = {pg.name.lower() for pg in delivery.pages}
    server = delivery.server_js or ""
    out: dict[str, list[str]] = {}
    for page in delivery.content_pages:
        dead: list[str] = []
        for target in re.findall(r"""href\s*=\s*["']([^"'#?]+\.html)""", page.text, re.IGNORECASE):
            name = target.rsplit("/", 1)[-1].lower()
            if not name or name in delivered or name in dead:
                continue
            # A page can be SERVED without existing as a file -- an Express-style route
            # answering "/contact" with no contact.html on disk is ordinary. Convicting on
            # file absence alone would call that a dead link. Measured across the 21 banked
            # deliveries there are 15 dangling targets and NONE is route-served, so this
            # guard changes nothing today; it is here because the corpus cannot warn us
            # when that shape first appears, and the server text is already read for c5.
            stem = name[:-5]
            route = re.compile("[\"'`]/" + re.escape(stem) + "[\"'`]")
            if stem and route.search(server):
                continue
            dead.append(name)
        if dead:
            out[page.name] = sorted(dead)
    return out


def check_pages_present_and_reachable(delivery: Delivery, criterion_text: str = "") -> Finding:
    """"The website should have a home page, a pieces list page, ... and a contact page."

    Heuristic: this does NOT match his page names to files -- that mapping is guesswork.
    It checks three things it can check. The first two were ADDED 2026-08-31 after
    independent review found the check REWARDED DELETING PAGES:

      1. COUNT -- at least as many content pages delivered as his sentence names. The
         original docstring promised exactly this and the code never implemented it; a
         grep for the count found only the prose. That gap is this defect's whole cause.
      2. OUTBOUND -- every ``.html`` a page links to was actually delivered. A menu
         pointing at a contact page that does not exist is the defect his eyes find first.
      3. INBOUND -- every delivered content page is reachable, i.e. some other delivered
         file names it. A page nothing links to is a page he cannot get to (#1343).

    WHY THE FIRST TWO ARE NOT OPTIONAL. With only the inbound audit, FEWER PAGES MEANS
    FEWER ORPHANS. Measured on the banked corpus: a one-page delivery with no contact page
    and two dead menu links scored SATISFIED and OUTSCORED a strictly better three-page
    build; 11 of 21 deliveries read SATISFIED, 9 of them shipping no piece page at all.
    An instrument whose headline number improves when work is deleted is worse than none.

    WHEN THE COUNT CANNOT BE READ from his sentence this returns NOT DECIDABLE even if
    both audits pass -- the criterion's principal claim ("these pages exist") is then
    unchecked, and passing on reachability alone is the overclaim this file refuses.
    """
    guard = _no_web_surface(delivery)
    if guard:
        return guard

    evidence: list[str] = []
    orphans: list[str] = []
    for page in delivery.content_pages:
        if page.name in _ENTRY_NAMES:
            evidence.append(f"{page.name}: entry document, reachable by construction")
            continue
        referrers = delivery.referenced_by(page)
        if referrers:
            evidence.append(f"{page.name}: reachable from {referrers}")
        else:
            orphans.append(page.name)
            evidence.append(f"{page.name}: ORPHAN -- no other delivered file names it")

    if orphans:
        return Finding(
            NOT_SATISFIED,
            "page-audit(inbound)",
            evidence
            + [
                f"{len(orphans)} delivered page(s) cannot be reached: {orphans}",
                (
                    "reachability is decided by filename occurrence anywhere in another "
                    "delivered file, which is generous -- a URL built at runtime from pieces "
                    "the probe cannot join would still read as an orphan"
                ),
            ],
        )

    # OUTBOUND. A link to a page that was never delivered is a dead end his eyes find in
    # one click, and it is the half that stops deletion looking like improvement.
    dangling = _dangling_links(delivery)
    if dangling:
        flat = sorted({t for targets in dangling.values() for t in targets})
        return Finding(
            NOT_SATISFIED,
            "page-audit(outbound)",
            evidence
            + [
                f"{len(flat)} link target(s) named but never delivered: {flat}",
                *(f"{src} links to {tgts} -- not on disk" for src, tgts in sorted(dangling.items())),
                (
                    "a menu entry pointing at a page that does not exist is a dead end; "
                    "this is checked because the inbound audit alone IMPROVES when pages "
                    "are deleted, so a one-page site with a full menu scored SATISFIED"
                ),
            ],
        )

    # COUNT. Never inferred from the delivery -- only from HIS sentence.
    wanted = _named_page_count(criterion_text)
    delivered_n = len(delivery.content_pages)
    if wanted is None:
        return Finding(
            NOT_DECIDABLE,
            "page-audit(count-unreadable)",
            evidence
            + [
                (
                    "both link audits pass, but this instrument cannot read how many "
                    "pages the criterion names, so the claim that those pages EXIST is "
                    "unchecked"
                ),
                "reporting SATISFIED on the link audits alone would overclaim",
            ],
        )
    if delivered_n < wanted:
        return Finding(
            NOT_SATISFIED,
            "page-audit(count)",
            evidence
            + [
                (
                    f"the criterion names {wanted} page(s); {delivered_n} content "
                    f"page(s) delivered: {[pg.name for pg in delivery.content_pages]}"
                ),
                "counted from the criterion's own comma/and-separated clauses naming a page",
            ],
        )
    return Finding(
        SATISFIED,
        "page-audit(count+inbound+outbound)",
        evidence
        + [
            f"{delivered_n} content page(s) delivered against {wanted} named",
            "every delivered content page is named by at least one other file",
            "every .html link target was delivered",
        ],
    )


def check_visual_consistency(delivery: Delivery) -> Finding:
    """"The website should be visually consistent and clean." -- falsifiable, not confirmable.

    This check can return NOT SATISFIED or NOT DECIDABLE and NEVER SATISFIED, and that
    asymmetry is the honest position rather than a gap. A stylesheet that defines a layout
    wrapper and applies it to no page is a concrete defect a reader can verify in seconds.
    The absence of that defect says nothing at all about how the pages look, so claiming
    SATISFIED from it would be the exact overclaim this instrument exists to refuse.
    """
    guard = _no_web_surface(delivery)
    if guard:
        return guard

    if not delivery.css_text:
        return Finding(
            NOT_DECIDABLE,
            "layout-class-audit",
            [f"no stylesheet under {delivery.public} ({ABSENT})"],
        )

    per_page = _classes_used(delivery)
    used: set[str] = set().union(*per_page.values()) if per_page else set()
    content = [p.name for p in delivery.content_pages]
    evidence: list[str] = []

    dead_layout: list[str] = []
    for layout in sorted(_LAYOUT_CLASSES & delivery.css_classes):
        applied = [n for n in content if layout in per_page.get(n, set())]
        evidence.append(
            f"stylesheet defines .{layout}; applied on {len(applied)}/{len(content)} "
            f"content pages {applied}"
        )
        if not applied:
            dead_layout.append(layout)

    unstyled = sorted(used - delivery.css_classes)
    evidence.append(
        f"{len(unstyled)} of {len(used)} class names used in the markup have no rule in "
        f"any delivered stylesheet: {unstyled[:12]}{' ...' if len(unstyled) > 12 else ''}"
    )
    evidence.append(
        "that count is an UPPER BOUND and is reported, not judged: a class can be styled "
        "by an element or attribute selector this probe does not resolve"
    )

    if dead_layout:
        return Finding(
            NOT_SATISFIED,
            "layout-class-audit",
            evidence
            + [
                (
                    f"layout wrapper(s) {dead_layout} are defined and used on no page -- the "
                    "stylesheet's own idea of the page shape reaches nothing"
                )
            ],
        )
    return Finding(
        NOT_DECIDABLE,
        "layout-class-audit",
        evidence
        + [
            (
                "no dead layout wrapper was found, which falsifies nothing and confirms "
                "nothing -- how the site LOOKS needs eyes, and this probe has none"
            ),
        ],
    )


@dataclass(frozen=True)
class Check:
    name: str
    trigger: re.Pattern[str]
    decide: Callable[[Delivery], Finding]


#: ORDER IS LOAD-BEARING. Triggers overlap -- his sentences are English, not a schema --
#: so the specific checks are matched before the general ones and the first hit decides.
#: A criterion that matches nothing falls through to NOT DECIDABLE, which is the correct
#: answer for a sentence this instrument was never built to read.
CHECKS: tuple[Check, ...] = (
    Check("launches", re.compile(r"\bcrash|\blaunch", re.IGNORECASE), check_launches),
    Check(
        "shared-menu",
        re.compile(
            r"(head(ing|er)|menu|nav\b|navigation).{0,80}"
            r"(same|every page|all pages|across all|consistent)"
            r"|(same|every page|all pages|across all|consistent).{0,80}"
            r"(head(ing|er)|menu|nav\b|navigation)",
            re.IGNORECASE | re.DOTALL,
        ),
        check_shared_menu,
    ),
    Check(
        "shared-data-source",
        re.compile(r"shared source|data source|shared data|same data|one data", re.IGNORECASE),
        check_shared_data_source,
    ),
    Check("filtering", re.compile(r"\bfilter|categor", re.IGNORECASE), check_filtering),
    Check(
        "blank-field-feedback",
        re.compile(
            r"blank|missing field|required field|feedback|validat|error message", re.IGNORECASE
        ),
        check_blank_field_feedback,
    ),
    Check(
        "enquiry-storage",
        re.compile(r"\bstor(e|ed|es|age|ing)\b|log or database|persist|saved", re.IGNORECASE),
        check_enquiry_storage,
    ),
    Check(
        "visual-consistency",
        re.compile(r"visual|styling|\bclean\b|alignment|readable text|look", re.IGNORECASE),
        check_visual_consistency,
    ),
    Check("pages-reachable", re.compile(r"\bpages?\b", re.IGNORECASE), check_pages_present_and_reachable),
)


def judge(delivery: Delivery, criteria: list[dict[str, Any]]) -> list[CriterionVerdict]:
    """Decide each of his criteria against the delivered tree."""
    out: list[CriterionVerdict] = []
    for raw in criteria:
        text = str(raw.get("text", ""))
        haystack = f"{text} {raw.get('check', '')}"
        chosen: Check | None = next((c for c in CHECKS if c.trigger.search(haystack)), None)
        if chosen is None:
            out.append(
                CriterionVerdict(
                    id=str(raw.get("id", "?")),
                    text=text,
                    tier=str(raw.get("tier", "")),
                    state=NOT_DECIDABLE,
                    check="none",
                    heuristic="no-matching-check",
                    evidence=[
                        (
                            "no check in this instrument recognises this sentence, so it has "
                            "no opinion. Reporting NOT DECIDABLE is the answer here, not a "
                            "placeholder for one."
                        ),
                    ],
                )
            )
            continue
        # A check may ask for HIS sentence when the criterion's own wording carries part
        # of the requirement -- c1 needs it to count how many pages he named. Passed by
        # inspection rather than by widening every check's signature, so the seven checks
        # that do not need it stay unchanged.
        if "criterion_text" in inspect.signature(chosen.decide).parameters:
            finding = chosen.decide(delivery, criterion_text=text)
        else:
            finding = chosen.decide(delivery)
        out.append(
            CriterionVerdict(
                id=str(raw.get("id", "?")),
                text=text,
                tier=str(raw.get("tier", "")),
                state=finding.state,
                check=chosen.name,
                heuristic=finding.heuristic,
                evidence=finding.evidence,
            )
        )
    return out


# --------------------------------------------------------------------------------------
# Finding his criteria, and finding the delivery
# --------------------------------------------------------------------------------------

_RUN_ID = re.compile(r"\b(20\d{6}-\d{6}-[a-z]{2,4})\b")


@dataclass
class CriteriaSource:
    criteria: list[dict[str, Any]]
    origin: str
    how: str


def _read_criteria_file(path: Path) -> tuple[list[dict[str, Any]] | str, str]:
    if not path.is_file():
        return ABSENT, f"{path} does not exist"
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return UNREADABLE, f"{path} is present and did not parse"
    criteria = ((blob.get("spec") or {}).get("criteria")) if isinstance(blob, dict) else None
    if not isinstance(criteria, list):
        return ABSENT, f"{path} carries no spec.criteria list"
    return criteria, str(path)


def resolve_criteria(
    delivery_root: Path, state_root: Path, explicit: Path | None, run_id: str | None
) -> CriteriaSource:
    """Find the operator's criteria for this delivery, and SAY how they were found.

    The join is not guessed: each review directory's ``REVIEW.html`` names the run that
    produced it, and that run's ``acceptance.json`` holds his sentences. When the pointer
    is missing the fallback matches on the repository name, and the report says which of
    the two happened -- a criteria set attached to the wrong delivery would produce
    confident verdicts about a tree it never described.
    """
    # On failure the SENTINEL becomes the origin and the human explanation becomes the
    # `how`: a reader needs to be told the file was there and would not parse, because a
    # broken writer and a missing record are different faults with different owners.
    if explicit is not None:
        criteria, detail = _read_criteria_file(explicit)
        if isinstance(criteria, str):
            return CriteriaSource([], criteria, f"explicit --criteria path: {detail}")
        return CriteriaSource(criteria, detail, "explicit --criteria path")

    runs = state_root / "fleet-runs"

    if run_id is None:
        review = delivery_root / "REVIEW.html"
        if review.is_file():
            found = sorted(set(_RUN_ID.findall(_read_text(review))))
            if len(found) == 1:
                run_id = found[0]
            elif len(found) > 1:
                return CriteriaSource(
                    [],
                    ABSENT,
                    f"REVIEW.html names {len(found)} runs ({found}); refusing to pick one",
                )

    if run_id is not None:
        criteria, detail = _read_criteria_file(runs / run_id / "acceptance.json")
        if isinstance(criteria, str):
            return CriteriaSource([], criteria, f"run {run_id} named by REVIEW.html: {detail}")
        return CriteriaSource(criteria, detail, f"run {run_id}, named inside REVIEW.html")

    # Fallback: the review directory is named `<stamp>-<project>`, and a run's
    # acceptance.json records the repository path it built.
    project = re.sub(r"^\d{8}-\d{6}-", "", delivery_root.name)
    unreadable = 0
    if runs.is_dir():
        for run in sorted((d for d in runs.iterdir() if d.is_dir()), reverse=True):
            blob = run / "acceptance.json"
            if not blob.is_file():
                continue
            try:
                parsed = json.loads(blob.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError, OSError):
                # A file that is THERE and will not parse is a different fault from one
                # that is absent, and it has a different owner: the writer, not the join.
                # Skipping it here is right -- another run may still match -- but it must
                # be counted, or a broken writer reads as "nothing was ever banked".
                unreadable += 1
                continue
            repo = str(parsed.get("repo", ""))
            if repo and Path(repo.replace("\\", "/")).name == project:
                criteria = (parsed.get("spec") or {}).get("criteria")
                if isinstance(criteria, list):
                    return CriteriaSource(
                        criteria,
                        str(blob),
                        f"newest run building {project!r} ({run.name}) -- REVIEW.html "
                        "named no run, so this is a MATCH ON PROJECT NAME, not on the "
                        "run that produced this tree",
                    )
    tail = (
        f"; {unreadable} candidate acceptance.json file(s) are present and did not parse "
        f"({UNREADABLE}) -- that is a broken writer, not a missing record"
        if unreadable
        else ""
    )
    return CriteriaSource(
        [], ABSENT, f"no acceptance.json could be tied to delivery {delivery_root.name!r}{tail}"
    )


def deliveries(state_root: Path) -> list[Path]:
    root = state_root / "operator-review"
    if not root.is_dir():
        return []
    return sorted(d for d in root.iterdir() if d.is_dir())


def build_report(
    delivery_root: Path, state_root: Path, criteria_path: Path | None = None
) -> dict[str, Any]:
    source = resolve_criteria(delivery_root, state_root, criteria_path, None)
    delivery = load_delivery(delivery_root)
    verdicts = judge(delivery, source.criteria)
    tally: dict[str, int] = {SATISFIED: 0, NOT_SATISFIED: 0, NOT_DECIDABLE: 0}
    for verdict in verdicts:
        tally[verdict.state] = tally.get(verdict.state, 0) + 1
    return {
        "question": (
            "does the DELIVERED site satisfy the operator's stated criteria? "
            "(NOT: did the exam cover them -- that is requirement_coverage_report.py)"
        ),
        "delivery": delivery_root.name,
        "delivery_dir": str(delivery_root),
        "public_dir": str(delivery.public),
        "criteria_origin": source.origin,
        "criteria_resolved_by": source.how,
        "criteria_count": len(source.criteria),
        "content_pages": [p.name for p in delivery.content_pages],
        "excluded_pages": {
            "fragments": [p.name for p in delivery.fragments],
            "redirect_stubs": [p.name for p in delivery.redirect_stubs],
        },
        "tally": tally,
        "advisory": True,
        "criteria": [
            {
                "id": v.id,
                "text": v.text,
                "tier": v.tier,
                "state": v.state,
                "check": v.check,
                "heuristic": v.heuristic,
                "evidence": v.evidence,
            }
            for v in verdicts
        ],
    }


def render(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"DELIVERY: {report['delivery']}")
    lines.append(f"TREE:     {report['public_dir']}")
    lines.append("")
    lines.append("QUESTION ANSWERED: does the DELIVERED SITE satisfy his stated criteria?")
    lines.append(
        "  This is NOT the question requirement_coverage_report.py answers. That one asks"
    )
    lines.append(
        "  whether the EXAM covered his requirements, and reports nothing when no exam ran."
    )
    lines.append(
        "  This one needs no exam, no oracle and no graphics card. Both are useful; they"
    )
    lines.append("  are different numbers.")
    lines.append("")

    if not report["criteria_count"]:
        lines.append(f"HIS CRITERIA COULD NOT BE READ: {report['criteria_resolved_by']}")
        lines.append("")
        lines.append(
            "That is a real outcome, not a gap in this report: with no criteria there is "
            "nothing to judge the delivery against, and inventing verdicts would be worse "
            "than saying so."
        )
        return "\n".join(lines)

    lines.append(
        f"HIS CRITERIA: {report['criteria_count']} read from {report['criteria_origin']}"
    )
    lines.append(f"  resolved by: {report['criteria_resolved_by']}")
    lines.append(f"PAGES JUDGED: {report['content_pages']}")
    excluded = report["excluded_pages"]
    if excluded["fragments"] or excluded["redirect_stubs"]:
        lines.append(
            f"  excluded: fragments {excluded['fragments']}, "
            f"redirect stubs {excluded['redirect_stubs']} -- named, not dropped silently"
        )
    lines.append("")

    for crit in report["criteria"]:
        lines.append(f"  [{crit['state']}] {crit['id']} ({crit['tier']}): {crit['text']}")
        lines.append(f"      heuristic: {crit['heuristic']} (check: {crit['check']})")
        for line in crit["evidence"]:
            lines.append(f"      - {line}")
        lines.append("")

    tally = report["tally"]
    lines.append(
        f"SUMMARY: {tally.get(SATISFIED, 0)} satisfied, "
        f"{tally.get(NOT_SATISFIED, 0)} NOT satisfied, "
        f"{tally.get(NOT_DECIDABLE, 0)} not decidable by this instrument."
    )
    lines.append("")
    lines.append(
        "Every verdict above is a reading of STATIC facts about the delivered files, and "
        "each names the heuristic that produced it so it can be discounted. NOT DECIDABLE "
        "is an answer, not a missing one: a criterion this instrument cannot decide must "
        "never be shown as passing."
    )
    lines.append(
        "ADVISORY ONLY -- this report never fails a build; it always exits 0 once it has "
        "produced a report."
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("delivery", nargs="?", help="review directory name; default is newest")
    parser.add_argument("--all", action="store_true", help="every banked delivery")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--state-root", type=Path, default=DEFAULT_STATE_ROOT)
    parser.add_argument(
        "--delivery-path", type=Path, help="a delivered tree anywhere on disk"
    )
    parser.add_argument(
        "--criteria", type=Path, help="an acceptance.json to read spec.criteria from"
    )
    args = parser.parse_args(argv)

    if args.delivery_path is not None:
        targets = [args.delivery_path]
    else:
        banked = deliveries(args.state_root)
        if not banked:
            print(
                f"no deliveries under {args.state_root / 'operator-review'}", file=sys.stderr
            )
            return 2
        if args.all:
            targets = banked
        elif args.delivery:
            targets = [args.state_root / "operator-review" / args.delivery]
        else:
            targets = [banked[-1]]

    for target in targets:
        if not target.is_dir():
            print(f"no such delivery: {target}", file=sys.stderr)
            return 2

    reports = [build_report(t, args.state_root, args.criteria) for t in targets]
    if args.json:
        print(json.dumps(reports, indent=2, default=str))
    else:
        print(("\n" + "=" * 78 + "\n").join(render(r) for r in reports))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
