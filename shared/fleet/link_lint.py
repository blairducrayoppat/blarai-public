"""Deterministic link resolver for a delivered web product — DoD capability 15.

**Why this exists (the load-bearing rationale).** On 2026-08-08 the Lead Architect opened
a website the coding fleet had built and, within a minute, clicked a "View Details" button
that answered ``{"error":"not found"}``. Four automated gates had passed that delivery. The
underlying cause was traced to #1342 (an acceptance oracle that could not fail, which
deleted the missing page from the plan) — but the *symptom* needed no oracle, no model and
no browser to catch: **the page the link pointed at did not exist in the delivered tree.**

That is a pure filesystem question, and nothing in this pipeline was asking it. Capability
15 ("the built product is EXERCISED, not just inspected") reads UNKNOWN precisely because
every existing gate inspects source or grades exams; none of them follows a link. This
module is the cheapest possible instrument against the most expensive class of escape: a
site that passes every gate and is visibly broken the moment a human uses it.

**Sibling module.** :mod:`shared.fleet.layout_lint` is the same idea aimed at WinUI XAML —
deterministic, model-free, precision-first, findings that force a coder FIX on a HARD
signal regardless of what any model said. Read that module's header for the shared
philosophy; this one applies it to the web.

**The design decision that makes this work, and the trap it avoids.** The escaped link
lived in a JavaScript template string::

    <a href="piece-detail.html?id=${piece.id}" class="detail-link">View Details</a>

— present in ``public/pieces.html`` *and* in ``public/app.js``. A checker that parsed only
static HTML would have missed the ``.js`` copy; a checker that gave up on any reference
containing ``${...}`` would have missed BOTH, because this one is interpolated. It is also
entirely decidable: the path component before the ``?`` is the literal ``piece-detail.html``.
So the rule is: **split the query and fragment off first, then ask whether what remains is
still a literal.** Getting that ordering backwards produces a checker that passes the exact
delivery it was written to catch.

**Resolution is AS SERVED, never as a filesystem path.** A static site is mounted at some
root (``public/`` here, via ``join(here, '..', 'public')`` in the delivered server) and a
link resolves against that mount, not against the file that contains it. Checking the
filesystem directly would resolve ``piece-detail.html?id=1`` as a *filename containing a
question mark*, find it absent, and be right by accident — or find something and be wrong.

**Scope of the rules** (precision-first — a false positive nags the coder into "fixing"
correct markup, so every rule is guarded to fire only on a real defect):

  broken-link              A reference whose decidable path carries a recognised web
                           extension (.html/.css/.png/...) and names nothing under the
                           served root. The View Details case. HIGH.
  broken-parent-dir        A reference whose filename is interpolated but whose literal
                           parent directory does not exist (``assets/${n}.png`` with no
                           ``assets/``). The filename is undecidable; the directory is not,
                           and a missing directory breaks every expansion. HIGH.
  case-mismatch            The target exists but the on-disk name differs in case. Works on
                           this Windows dev box, 404s on any case-sensitive host. This is a
                           defect that CANNOT be found by opening the site locally. HIGH.
  unresolved-extensionless A reference with no file extension that names nothing on disk
                           (``/pieces``). Often a real break; sometimes a server-side or
                           client-side route this module cannot see. LOW — recorded
                           honestly, never silently cleaned, never forces a FIX.
  unreadable               A file that could not be read or parsed. LOW, fail-soft.

**What this module deliberately does NOT do**, recorded because an unnamed limit reads as a
clean result (capability 7): it does not execute the site, follow redirects, evaluate
JavaScript, resolve client-side routes, check external URLs, or validate that a resolved
page is *correct* — only that it EXISTS. Every reference it could not decide is counted in
``undecidable`` and surfaced in ``not_measured``. A report with zero findings and forty
undecidable references has not checked forty references, and says so.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote

SEVERITY_HIGH = "high"
SEVERITY_LOW = "low"

# A finding is HARD (forces a FIX iteration) iff its severity is HIGH.
_HARD_SEVERITIES = {SEVERITY_HIGH}

#: Attributes that carry a URL a browser will actually fetch or navigate to. Kept
#: deliberately short: every entry here is a reference the operator can reach by using
#: the site. `data-*` attributes are excluded — they are application state, and whether
#: the app treats one as a URL is not decidable from markup.
_URL_ATTRS = frozenset({"href", "src", "action", "poster", "data"})

#: Extensions that make a reference DECIDABLE as a file. A path ending in one of these
#: names a file the server must be able to serve; if it is absent, the link is broken —
#: there is no routing story that rescues `piece-detail.html`. Anything else (a bare
#: `/pieces`) may be a route, so it grades LOW.
_WEB_EXTENSIONS = frozenset(
    {
        ".html", ".htm", ".xhtml",
        ".css", ".js", ".mjs", ".cjs", ".map",
        ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".avif", ".ico", ".bmp",
        ".json", ".xml", ".txt", ".csv", ".pdf",
        ".woff", ".woff2", ".ttf", ".otf", ".eot",
        ".mp4", ".webm", ".ogg", ".mp3", ".wav",
    }
)

#: Directory names that are never part of a delivered static site.
_SKIP_DIRS = frozenset({".git", "node_modules", "__pycache__", ".venv", "coverage", ".cache"})

#: Conventional static-mount directory names, most specific first. Detection prefers a
#: directory that actually contains an index page (see :func:`detect_served_root`).
_ROOT_CANDIDATES = ("public", "static", "www", "dist", "build", "site", "htdocs")

#: Index documents a server serves for a directory request.
_INDEX_NAMES = ("index.html", "index.htm")

#: A URL scheme, or a protocol-relative URL — either way, not ours to resolve.
_ABSOLUTE_RE = re.compile(r"^(?:[a-zA-Z][a-zA-Z0-9+.\-]*:|//)")

#: A template interpolation. Both JS `${...}` and the handlebars-ish `{{...}}` that
#: coders reach for; either makes the span it occupies undecidable.
_INTERPOLATION_RE = re.compile(r"\$\{[^}]*\}|\{\{[^}]*\}\}|<%[^%]*%>")

#: URL-bearing attribute inside a string of markup — used on .js/.mjs files, where markup
#: is emitted from template literals and no HTML parser will see it.
_JS_ATTR_RE = re.compile(
    r"""\b(href|src|action|poster)\s*=\s*(?P<q>["'`])(?P<val>[^"'`]*?)(?P=q)""",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Reference:
    """One URL-bearing reference found in a delivered file.

    Attributes:
        raw: the reference exactly as written, before any splitting.
        path: the decidable path component — query, fragment and any trailing
            interpolation removed. Empty when nothing decidable survives.
        attr: the attribute that carried it (href / src / action / poster).
        tag: the element it sat on ("" for a reference recovered from JavaScript,
            where there is no parsed element).
        file: site-relative path of the file it was found in.
        line: 1-indexed line number, 0 when unknown.
    """

    raw: str
    path: str
    attr: str
    tag: str
    file: str
    line: int = 0


@dataclass(frozen=True)
class Finding:
    """One deterministic link defect.

    Attributes:
        rule: stable rule id (broken-link / case-mismatch / ...).
        severity: ``high`` (a real break -> forces a FIX) or ``low`` (advisory).
        message: actionable, human-readable description of what to fix.
        reference: the offending reference as written.
        file: the file the reference was found in.
        line: 1-indexed line number, 0 when unknown.
    """

    rule: str
    severity: str
    message: str
    reference: str
    file: str
    line: int = 0


@dataclass
class _Tally:
    """Per-status counts over every reference examined.

    ``undecidable`` is carried with the same weight as the rest on purpose: it is the
    field that stops a clean ``broken == 0`` from being read as "every link resolves".
    """

    resolved: int = 0
    broken: int = 0
    undecidable: int = 0
    external: int = 0
    in_page: int = 0
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


class _RefCollector(HTMLParser):
    """Collect URL-bearing attributes from HTML.

    Uses the standard-library parser rather than a regex so the element NAME is known:
    an extensionless ``<a href>`` that answers with JSON is a defect the operator will
    hit, while the same string on a ``<link>`` may be a legitimate API endpoint. Knowing
    the tag is what lets the rules stay precise.
    """

    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=True)
        self._source = source
        self.refs: list[Reference] = []
        self._script_depth = 0
        self._script_line = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        line = self.getpos()[0]
        if tag.lower() == "script":
            self._script_depth += 1
            self._script_line = line
        for name, value in attrs:
            if not value:
                continue
            key = name.lower()
            if key == "srcset":
                # "a.png 1x, b.png 2x" — each candidate is its own reference.
                for candidate in value.split(","):
                    url = candidate.strip().split()[0] if candidate.strip() else ""
                    if url:
                        self.refs.append(_make_reference(url, "srcset", tag, self._source, line))
                continue
            if key in _URL_ATTRS:
                self.refs.append(_make_reference(value, key, tag, self._source, line))

    # A void/self-closing element reaches handle_startendtag, not handle_starttag.
    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._script_depth:
            self._script_depth -= 1

    def handle_data(self, data: str) -> None:
        """Recover references from markup emitted inside an inline ``<script>``.

        An HTML parser is REQUIRED to treat script content as opaque text, so the
        markup a page builds in a template literal is invisible to `handle_starttag`.
        That is correct parsing and a blind spot at the same time: the delivered site
        that prompted this module carried its broken link in BOTH `app.js` and an inline
        script in `pieces.html`, and a parser-only scan reported exactly half of it.
        Line numbers are offset from the opening `<script>` tag so a finding still points
        the reader at the right part of the file.
        """
        if not self._script_depth or not data.strip():
            return
        for ref in extract_references_js(data, self._source):
            self.refs.append(
                Reference(
                    raw=ref.raw,
                    path=ref.path,
                    attr=ref.attr,
                    tag="script",
                    file=ref.file,
                    line=self._script_line + max(ref.line - 1, 0),
                )
            )

    def error(self, message: str) -> None:  # pragma: no cover - py3.12 never calls this
        """Required by the ABC on older Pythons; parsing is fail-soft, so swallow."""


def _decidable_path(raw: str) -> str:
    """The part of ``raw`` this module can resolve on disk, or "" if nothing survives.

    Query and fragment are stripped FIRST, then the remainder is tested for
    interpolation. That ordering is the whole point: ``piece-detail.html?id=${piece.id}``
    is fully decidable (the file is ``piece-detail.html``) while ``${piece.image}`` is not.
    Reversing it makes the checker blind to the exact shape it exists to catch.
    """
    path = raw.split("#", 1)[0].split("?", 1)[0].strip()
    if not path:
        return ""
    if _INTERPOLATION_RE.search(path):
        return ""
    return path


def _make_reference(raw: str, attr: str, tag: str, source: str, line: int) -> Reference:
    return Reference(
        raw=raw.strip(),
        path=_decidable_path(raw),
        attr=attr,
        tag=tag,
        file=source,
        line=line,
    )


def extract_references_html(text: str, source: str) -> list[Reference]:
    """Every URL-bearing reference in an HTML document.

    Fail-soft: a document the parser chokes on yields whatever was collected before the
    failure rather than raising. The site already served this file; a parse problem here
    must never take the gate down with it.
    """
    collector = _RefCollector(source)
    try:
        collector.feed(text)
        collector.close()
    except Exception:  # noqa: BLE001 - fail-soft by contract; partial results are useful
        pass
    return collector.refs


def extract_references_js(text: str, source: str) -> list[Reference]:
    """URL-bearing attributes inside markup emitted from JavaScript.

    Scoped deliberately to `href=`/`src=`/`action=`/`poster=` appearing in a string. A
    broader sweep — every string literal that looks like a path — would flag `fetch()`
    calls against API routes, which are not files and are not defects. This narrow rule
    catches the real escape (markup built in a template literal) with no such class of
    false positive.
    """
    refs: list[Reference] = []
    for match in _JS_ATTR_RE.finditer(text):
        value = match.group("val")
        if not value:
            continue
        line = text.count("\n", 0, match.start()) + 1
        refs.append(_make_reference(value, match.group(1).lower(), "", source, line))
    return refs


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def detect_served_root(site_dir: str | Path) -> tuple[Path, str]:
    """The directory a static server would mount at ``/``, and how it was chosen.

    Prefers a conventional mount directory that actually holds an index document, then a
    conventional directory that exists at all, then any directory holding an index, then
    the site directory itself. The reason string is returned so a report can say WHY a
    root was picked — a wrong root silently turns every link broken, and the only defence
    against a wrong answer that looks confident is showing the working.
    """
    base = Path(site_dir)
    for name in _ROOT_CANDIDATES:
        candidate = base / name
        if candidate.is_dir() and any((candidate / idx).is_file() for idx in _INDEX_NAMES):
            return candidate, f"conventional static root '{name}/' containing an index page"
    for name in _ROOT_CANDIDATES:
        candidate = base / name
        if candidate.is_dir():
            return candidate, f"conventional static root '{name}/' (no index page found in it)"
    for idx in _INDEX_NAMES:
        if (base / idx).is_file():
            return base, f"the site directory itself (it holds {idx})"
    return base, "the site directory itself (no conventional static root found)"


def _iter_site_files(root: Path) -> Iterable[Path]:
    """Every file under ``root``, skipping directories no delivered site serves."""
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        yield path


def _resolve_on_disk(served_root: Path, rel: str) -> tuple[Path | None, bool]:
    """Locate ``rel`` under ``served_root``.

    Returns ``(path, exact)``. ``exact`` is False when the target was only found by
    ignoring case — a real distinction, because this dev box's filesystem is
    case-insensitive and any Linux host serving the same tree would answer 404. That
    class of defect is invisible to opening the site locally, which is exactly why it is
    worth a rule.
    """
    target = served_root / rel
    if target.is_file():
        # `is_file` is case-INSENSITIVE on Windows, so confirm the real on-disk spelling.
        try:
            resolved = target.resolve()
            actual = resolved.name
            wanted = Path(rel).name
            if actual != wanted:
                return target, False
        except OSError:
            return target, True
        return target, True

    if target.is_dir():
        for idx in _INDEX_NAMES:
            if (target / idx).is_file():
                return target / idx, True
        return None, True

    return None, True


def _resolve_reference(ref: Reference, served_root: Path, containing_dir: Path) -> tuple[str, Finding | None]:
    """Classify one reference. Returns ``(status, finding_or_None)``.

    Status is one of ``resolved`` / ``broken`` / ``undecidable`` / ``external`` /
    ``in-page``. A status of ``broken`` always carries a finding; ``undecidable`` may
    carry one when the *directory* part is decidable and absent.
    """
    raw = ref.raw
    if not raw:
        return "undecidable", None
    if raw.startswith("#"):
        return "in-page", None
    if _ABSOLUTE_RE.match(raw):
        return "external", None

    path = ref.path
    if not path:
        # Nothing literal survived. The filename is unknowable — but a literal parent
        # directory still is not, and a missing one breaks every possible expansion.
        prefix = _INTERPOLATION_RE.split(raw.split("#", 1)[0].split("?", 1)[0])[0]
        if "/" in prefix:
            parent_rel = prefix.rsplit("/", 1)[0]
            parent = _base_for(raw, served_root, containing_dir) / unquote(parent_rel).lstrip("/")
            if parent_rel and not parent.is_dir():
                return "undecidable", Finding(
                    rule="broken-parent-dir",
                    severity=SEVERITY_HIGH,
                    message=(
                        f"'{raw}' builds its filename at runtime, but the folder it builds it in "
                        f"('{parent_rel}/') does not exist under the served root — so no value of "
                        f"the filename can ever load."
                    ),
                    reference=raw,
                    file=ref.file,
                    line=ref.line,
                )
        return "undecidable", None

    rel = unquote(path)
    base = _base_for(path, served_root, containing_dir)
    lookup = rel.lstrip("/") if path.startswith("/") else rel
    resolved, exact = _resolve_on_disk(base, lookup)

    if resolved is not None and exact:
        return "resolved", None

    if resolved is not None and not exact:
        return "resolved", Finding(
            rule="case-mismatch",
            severity=SEVERITY_HIGH,
            message=(
                f"'{raw}' resolves only because this machine's filesystem ignores capitalisation. "
                f"The file on disk is named '{resolved.name}'. On a normal web server this link "
                f"returns 'not found'."
            ),
            reference=raw,
            file=ref.file,
            line=ref.line,
        )

    suffix = Path(lookup).suffix.lower()
    if suffix in _WEB_EXTENSIONS:
        where = "a page" if suffix in {".html", ".htm", ".xhtml"} else "a file"
        return "broken", Finding(
            rule="broken-link",
            severity=SEVERITY_HIGH,
            message=(
                f"'{raw}' points at {where} that is not in the delivered site "
                f"('{lookup}' does not exist under the served root). Anyone who clicks or loads "
                f"this gets an error instead."
            ),
            reference=raw,
            file=ref.file,
            line=ref.line,
        )

    return "broken", Finding(
        rule="unresolved-extensionless",
        severity=SEVERITY_LOW,
        message=(
            f"'{raw}' matches no file in the delivered site. It has no file extension, so it may "
            f"be a route the server builds at runtime — this check cannot tell. Worth confirming "
            f"by opening it."
        ),
        reference=raw,
        file=ref.file,
        line=ref.line,
    )


def _base_for(path: str, served_root: Path, containing_dir: Path) -> Path:
    """The directory a reference resolves against: the mount root if it is site-absolute,
    otherwise the directory of the file that contains it — which is how a browser does it."""
    return served_root if path.startswith("/") else containing_dir


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


def lint_site(site_dir: str | Path, served_root: str | Path | None = None) -> dict:
    """Resolve every reference in a delivered site. Returns the report dict.

    The report distinguishes *did not check* from *checked and found nothing* at every
    level (DoD capability 7): ``checked`` says whether the scan ran at all, ``counts``
    breaks every reference down by status including ``undecidable``, and ``not_measured``
    names in words what this instrument cannot see. A caller that reads only ``hard``
    gets a correct answer; a caller that reads ``counts`` gets an honest one.
    """
    base = Path(site_dir)
    if not base.is_dir():
        return {
            "schema": "link-lint/v1",
            "checked": False,
            "reason": f"site directory does not exist: {base}",
            "served_root": "",
            "served_root_reason": "",
            "findings": [],
            "hard": False,
            "files_scanned": 0,
            "references": 0,
            "counts": {},
            "not_measured": ["nothing was scanned: the site directory does not exist"],
        }

    if served_root is None:
        root, root_reason = detect_served_root(base)
    else:
        root, root_reason = Path(served_root), "explicitly supplied by the caller"

    findings: list[Finding] = []
    tally = _Tally()
    files_scanned = 0

    for path in _iter_site_files(root):
        suffix = path.suffix.lower()
        if suffix not in {".html", ".htm", ".xhtml", ".js", ".mjs", ".cjs"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            findings.append(
                Finding(
                    rule="unreadable",
                    severity=SEVERITY_LOW,
                    message=f"Could not read {path.name}: {exc}",
                    reference="",
                    file=path.name,
                )
            )
            continue

        files_scanned += 1
        rel_source = str(path.relative_to(root)).replace("\\", "/")
        if suffix in {".html", ".htm", ".xhtml"}:
            refs = extract_references_html(text, rel_source)
        else:
            refs = extract_references_js(text, rel_source)

        for ref in refs:
            status, finding = _resolve_reference(ref, root, path.parent)
            setattr(tally, status.replace("-", "_"), getattr(tally, status.replace("-", "_")) + 1)
            if finding is not None:
                findings.append(finding)

    # A scan that examined NO files has not produced a clean result — it has produced no
    # result. Reporting `checked: true, hard: false` here would be this project's own
    # #1342 defect committed by the instrument written to catch it: an unmeasured pass
    # sitting where a measured one is expected. Four empty scaffolds under ~/projects
    # returned exactly that shape on this module's first sweep, which is how it was found.
    if files_scanned == 0:
        return {
            "schema": "link-lint/v1",
            "checked": False,
            "reason": (
                "no HTML or JavaScript files were found under the served root "
                f"({root}) - there is nothing here whose links could be followed"
            ),
            "served_root": str(root),
            "served_root_reason": root_reason,
            "findings": [asdict(x) for x in findings],
            "hard": has_hard_findings(findings),
            "files_scanned": 0,
            "references": 0,
            "counts": {},
            "not_measured": [
                "NOTHING was checked: the served root holds no page or script files. "
                "This is not a clean result, it is an absent one"
            ],
        }

    not_measured = [
        "external URLs (http/https/mailto/tel) are never fetched — their reachability is unknown",
        "links built entirely at runtime are counted in counts.undecidable, not verified",
        "this checks that a target EXISTS, never that its content is correct",
        "server-side and client-side routes are invisible to a filesystem check",
    ]
    if tally.undecidable:
        not_measured.insert(
            0,
            f"{tally.undecidable} reference(s) could not be decided without running the site — "
            f"a clean result does NOT mean these resolve",
        )

    return {
        "schema": "link-lint/v1",
        "checked": True,
        "reason": "",
        "served_root": str(root),
        "served_root_reason": root_reason,
        "findings": [asdict(x) for x in findings],
        "hard": has_hard_findings(findings),
        "files_scanned": files_scanned,
        "references": (
            tally.resolved + tally.broken + tally.undecidable + tally.external + tally.in_page
        ),
        "counts": {
            "resolved": tally.resolved,
            "broken": tally.broken,
            "undecidable": tally.undecidable,
            "external": tally.external,
            "in_page": tally.in_page,
        },
        "not_measured": not_measured,
    }


def has_hard_findings(findings: Iterable[dict | Finding]) -> bool:
    """True when any finding is HIGH severity (i.e. forces a FIX iteration)."""
    for f in findings:
        d = asdict(f) if isinstance(f, Finding) else f
        if d.get("severity") in _HARD_SEVERITIES:
            return True
    return False


def format_findings(findings: Iterable[dict | Finding]) -> str:
    """Render findings as a compact, coder-facing bullet list (for FIX feedback)."""
    lines: list[str] = []
    for f in findings:
        d = asdict(f) if isinstance(f, Finding) else f
        loc = f" [{d['file']}"
        loc += f":{d['line']}]" if d.get("line") else "]"
        lines.append(f"- ({d['severity']}/{d['rule']}){loc} {d['message']}")
    return "\n".join(lines)


def format_operator_summary(report: dict) -> str:
    """Render the report in the plain language the Lead Architect reads.

    Leads with what was NOT checked when anything was not checked. The report he was
    handed on 2026-08-08 said a delivery was clean while an unmeasured field sat beside
    the confident one; this ordering is the fix for that class, not a stylistic choice.
    """
    if not report.get("checked"):
        return f"The link check did not run. Reason: {report.get('reason', 'unknown')}"

    counts = report.get("counts", {})
    broken = counts.get("broken", 0)
    undecidable = counts.get("undecidable", 0)
    resolved = counts.get("resolved", 0)
    lines: list[str] = []

    if broken:
        lines.append(
            f"{broken} link(s) on this site lead nowhere. Anyone who clicks them gets an error."
        )
    else:
        lines.append("Every link this check could follow leads somewhere real.")

    if undecidable:
        # ASCII only in this string: it is printed to a Windows console whose code page
        # mangles non-ASCII punctuation, and the operator reads this output directly.
        lines.append(
            f"{undecidable} link(s) are built while the page is running, so this check could not "
            f"follow them. They are NOT confirmed working - they are unchecked."
        )

    lines.append(f"{resolved} link(s) checked and working.")
    for finding in report.get("findings", []):
        if finding.get("severity") == SEVERITY_HIGH:
            lines.append(f"  - {finding['file']}: {finding['message']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# __main__ CLI — the fleet PowerShell bridge
# ---------------------------------------------------------------------------
#
# Usage:
#   python -m shared.fleet.link_lint --site-dir <dir> [--served-root <dir>] [--operator]
#
# Stdout: a single JSON object on one line (or plain text with --operator).
#
# Exit codes:
#   0 — always for a completed scan, findings or not (the JSON carries the state — this is
#       a SIGNAL, matching layout_lint; the caller decides what to do with `hard`).
#   2 — only for a usage error (no --site-dir given / directory absent).

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m shared.fleet.link_lint",
        description="Deterministic link resolver for a delivered site — JSON findings on stdout.",
    )
    parser.add_argument("--site-dir", required=True, help="Root of the delivered site repository.")
    parser.add_argument(
        "--served-root",
        help="Directory the web server mounts at '/'. Detected when omitted.",
    )
    parser.add_argument(
        "--operator",
        action="store_true",
        help="Print the plain-language summary instead of JSON.",
    )
    args = parser.parse_args()

    if not Path(args.site_dir).is_dir():
        print(f"ERROR: --site-dir not found: {args.site_dir}", file=sys.stderr)
        sys.exit(2)

    result = lint_site(args.site_dir, args.served_root)
    print(format_operator_summary(result) if args.operator else json.dumps(result))
    sys.exit(0)
