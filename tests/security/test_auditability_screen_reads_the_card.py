"""Gate: the in-app auditability screen cannot disagree with the card (#1583).

THE TICKET CALLS THIS GATE "the whole ticket", and it is right: a screen that
claims coverage the system does not have is worse than no screen, because it
converts an unknown into a false assurance.

The ticket allowed two ways to hold that. Either the screen READS the card, or a
gate asserts a hand-maintained screen agrees with it row by row. This change took
the first, so most of these tests are not comparisons — they are reachability
checks on the single path from the one file to the screen:

    docs/governance/auditability-card.md          the one copy
      -> csproj Content Include + Link            copied next to the build
      -> AuditabilityCard.RelativePath            where the loader looks
      -> OnOpenAuditability                       what the button calls
      -> AuditabilityContent.Markdown             what the operator sees

Every link in that chain is asserted here, because "built but wired into
nothing" is this project's most-recurred defect and a disclosure screen wired to
nothing would show the refusal page forever while looking like a feature.

The second-copy check is here too: the C# must not contain re-typed disclosure
rows. That is the failure the ticket names — the WinUI passthrough allowlist,
where a hand-copied C# array silently dropped a live command twice.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_UI = _REPO / "services" / "ui_winui"
_CARD = _REPO / "docs" / "governance" / "auditability-card.md"
_CSPROJ = _UI / "BlarAI.Desktop.csproj"
_LOADER = _UI / "Services" / "AuditabilityCard.Core.cs"
_XAML = _UI / "MainWindow.xaml"
_CODE_BEHIND = _UI / "MainWindow.xaml.cs"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _csproj() -> ET.Element:
    """Parse the csproj, refusing entity declarations before handing it to stdlib.

    CORRECTED. An earlier version of this docstring said "xml.etree resolves
    external entities". It does NOT, in CPython -- pyexpat refuses an undefined
    entity and never fetches a SYSTEM one, which review reproduced on this
    interpreter. ElementTree's real exposure is INTERNAL entity expansion
    (billion laughs / quadratic blowup), which is what the ``<!entity`` check
    below actually defends.

    The SYSTEM and PUBLIC checks that used to sit here defended nothing, and
    were a live false-positive risk besides: a case-insensitive substring over
    the whole file, comments included, in a repository whose doctrine discusses
    the "public mirror" and the "file system". A gate that goes red over a
    comment is a gate nobody trusts.

    ``defusedxml`` is not a dependency here, and adding one for a single gate
    test that reads a version-controlled file in our own repository is
    disproportionate. Refusing the declaration that makes expansion possible is
    not, and is this project's own rule applied literally (validate before
    trust, principle 7).
    """
    raw = _text(_CSPROJ)
    lowered = raw.lower()
    for construct in ("<!doctype", "<!entity"):
        assert construct not in lowered, (
            f"{_CSPROJ.name} contains {construct!r}, which a project file has no "
            "legitimate reason to carry. Refusing to parse it."
        )
    return ET.fromstring(raw)


# ---------------------------------------------------------------------------
# The chain, link by link.
# ---------------------------------------------------------------------------


def test_the_card_exists_where_everything_else_points() -> None:
    assert _CARD.is_file(), f"the disclosure itself is missing: {_CARD}"
    body = _text(_CARD)
    assert "Auditability Card" in body
    assert len(body) > 2000, "the card is suspiciously short for a disclosure"


def test_the_app_ships_the_card_from_its_canonical_path() -> None:
    """Not a copy of the card in the app folder. THE card."""
    root = _csproj()
    includes = [
        element.attrib.get("Include", "")
        for element in root.iter()
        if element.tag.endswith("Content")
    ]
    shipped = [i for i in includes if "auditability-card.md" in i]

    assert shipped, (
        "the csproj does not ship the auditability card, so the screen will "
        "render its refusal page forever"
    )
    assert len(shipped) == 1, f"the card is shipped more than once: {shipped}"

    resolved = (_UI / shipped[0].replace("\\", "/")).resolve()
    assert resolved == _CARD.resolve(), (
        f"the app ships {resolved}, which is not the card at {_CARD}. A second "
        "copy is exactly the drift this gate exists to prevent."
    )


def test_the_shipped_path_matches_where_the_loader_looks() -> None:
    """The Link and the constant must agree, or the copy lands somewhere the
    loader never reads and the screen refuses forever while the build is green."""
    root = _csproj()
    link = next(
        element.attrib.get("Link", "")
        for element in root.iter()
        if element.tag.endswith("Content")
        and "auditability-card.md" in element.attrib.get("Include", "")
    )
    assert link, "the Content entry has no Link, so where it lands is incidental"

    match = re.search(
        r'RelativePath\s*=\s*"([^"]+)"', _text(_LOADER)
    )
    assert match, "AuditabilityCard.RelativePath is gone"

    assert link.replace("\\", "/") == match.group(1), (
        f"the csproj copies the card to {link!r} and the loader reads "
        f"{match.group(1)!r}"
    )


def test_the_card_is_copied_on_build_not_merely_referenced() -> None:
    root = _csproj()
    entry = next(
        element
        for element in root.iter()
        if element.tag.endswith("Content")
        and "auditability-card.md" in element.attrib.get("Include", "")
    )
    copy = [child.text for child in entry if child.tag.endswith("CopyToOutputDirectory")]
    assert copy and copy[0] in ("PreserveNewest", "Always"), (
        f"the card is referenced but not copied to the output ({copy}), so the "
        "loader will not find it beside the running app"
    )


def test_the_button_exists_and_calls_a_handler_that_exists() -> None:
    """Reachability. A screen nothing opens is the defect this project has
    shipped more often than any other."""
    xaml = _text(_XAML)
    assert 'x:Name="AuditabilityButton"' in xaml, "no button opens the disclosure"

    handler = re.search(
        r'x:Name="AuditabilityButton"[^>]*Click="(\w+)"', xaml, re.DOTALL
    )
    assert handler, "the disclosure button has no Click handler"

    code = _text(_CODE_BEHIND)
    assert f"void {handler.group(1)}(" in code, (
        f"the button calls {handler.group(1)}, which does not exist in the "
        "code-behind"
    )


def test_the_handler_loads_the_card_rather_than_a_literal() -> None:
    code = _text(_CODE_BEHIND)
    opener = re.search(
        r"void OnOpenAuditability\(.*?\n    \}", code, re.DOTALL
    )
    assert opener, "OnOpenAuditability is gone"
    body = opener.group(0)

    assert "AuditabilityCard.Load(" in body, (
        "the screen does not load the card; whatever it shows is a second copy"
    )
    assert "AppContext.BaseDirectory" in body, (
        "the loader is not pointed at the app directory, so where it reads from "
        "depends on what the operator launched from"
    )
    assert "AuditabilityContent.Markdown" in body, (
        "the loaded card is never put on screen"
    )


def _xaml_tree() -> "ET.Element":
    """The real MainWindow.xaml as a tree, so ancestry can be asserted.

    Proximity is not containment, and the difference is the whole of review
    blocker 1.
    """
    return ET.fromstring(_text(_XAML))


def _ancestors_of(root: "ET.Element", name: str) -> "list[ET.Element]":
    """Every ancestor of the element with x:Name=``name``, outermost first."""
    xname = "{http://schemas.microsoft.com/winfx/2006/xaml}Name"
    path: list[ET.Element] = []

    def walk(node: "ET.Element", trail: "list[ET.Element]") -> bool:
        if node.attrib.get(xname) == name:
            path.extend(trail)
            return True
        for child in node:
            if walk(child, trail + [node]):
                return True
        return False

    walk(root, [])
    return path


def test_no_ancestor_of_the_disclosure_is_collapsed() -> None:
    """THE STRUCTURAL LOCK, and the reason it exists.

    MEASURED: the overlay was first inserted INSIDE ``GalleryOverlay``, which
    carries ``Visibility="Collapsed"``. A collapsed element does not render its
    subtree, so the button set the disclosure visible and nothing appeared --
    and all 12 gates here plus all 99 C# tests passed, green, over a screen that
    could not be shown. The gate the ticket calls "the whole ticket" certified a
    chain severed at its last link.

    The old test checked that "MarkdownBlock" appeared within 3000 characters of
    the overlay's name. Proximity is not containment. This walks the actual
    element tree.
    """
    root = _xaml_tree()
    ancestors = _ancestors_of(root, "AuditabilityContent")
    assert ancestors, "AuditabilityContent is not in MainWindow.xaml at all"

    xname = "{http://schemas.microsoft.com/winfx/2006/xaml}Name"
    for node in ancestors:
        named = node.attrib.get(xname, node.tag.rsplit("}", 1)[-1])
        if named == "AuditabilityOverlay":
            continue  # the overlay itself is collapsed until the button opens it
        assert node.attrib.get("Visibility") != "Collapsed", (
            f"{named} is an ancestor of the disclosure and is Collapsed, so the "
            "screen can never render. The overlay must be a SIBLING of the other "
            "overlays, not a child of one."
        )


def test_the_disclosure_is_not_inside_another_overlay() -> None:
    """The same defect stated the other way, so a rename cannot slip past.

    Any ancestor whose name ends in 'Overlay' other than this one means the
    disclosure is nested in something that owns its own visibility and its own
    close handler -- which would also take the disclosure down with it.
    """
    xname = "{http://schemas.microsoft.com/winfx/2006/xaml}Name"
    nested = [
        node.attrib.get(xname)
        for node in _ancestors_of(_xaml_tree(), "AuditabilityOverlay")
        if (node.attrib.get(xname) or "").endswith("Overlay")
    ]
    assert not nested, (
        f"the disclosure overlay is nested inside {nested}, which controls its "
        "own visibility"
    )


def test_the_overlay_actually_contains_the_renderer() -> None:
    """Containment, by tree. The renderer must be a DESCENDANT of the overlay."""
    xname = "{http://schemas.microsoft.com/winfx/2006/xaml}Name"
    ancestors = _ancestors_of(_xaml_tree(), "AuditabilityContent")
    names = [node.attrib.get(xname) for node in ancestors]
    assert "AuditabilityOverlay" in names, (
        f"AuditabilityContent is not inside AuditabilityOverlay; its ancestors "
        f"are {names}"
    )

    overlay = next(
        node for node in _xaml_tree().iter()
        if node.attrib.get(xname) == "AuditabilityOverlay"
    )
    renderers = [
        node for node in overlay.iter()
        if node.tag.rsplit("}", 1)[-1] == "MarkdownBlock"
    ]
    assert renderers, "the disclosure overlay contains no MarkdownBlock"


# ---------------------------------------------------------------------------
# No second copy.
# ---------------------------------------------------------------------------


def test_the_app_does_not_re_type_any_disclosure_row() -> None:
    """The failure the ticket names, in its own words: two hand-maintained
    copies drift, and the one that drifts optimistically is the one nobody
    notices.

    Checked by taking distinctive phrases out of the CARD and asserting none of
    them appears in the C# -- so this cannot go stale as the card changes, and
    it fails if someone starts pasting rows into the screen.
    """
    card = _text(_CARD)
    distinctive = [
        phrase
        for phrase in (
            "_adjudicate_tool_dispatch",
            "guarded_fetch.fetch_external",
            "Post-Generation Output Validator",
            "_build_ingest_audit_log",
            "Interception depth",
        )
        if phrase in card
    ]
    assert len(distinctive) >= 4, (
        "the phrases this gate looks for are no longer in the card; pick new "
        f"ones (found {distinctive})"
    )

    # EVERY C# and XAML file under the app, INCLUDING THE TESTS. Scanning only
    # the three shipping files missed the copy that existed: three card rows
    # hand-retyped into MarkdownTableGateTests.cs, already drifted -- it had
    # abridged "the **only** surface that writes receipts today" to "Inline",
    # dropping exactly the qualification that makes the row honest, under a
    # method named "the real disclosure parses".
    sources = sorted(_UI.rglob("*.cs")) + sorted(_UI.rglob("*.xaml"))
    sources = [s for s in sources if "obj" not in s.parts and "bin" not in s.parts]
    assert len(sources) > 5, f"the sweep found only {len(sources)} files to scan"

    for source in sources:
        body = _text(source)
        for phrase in distinctive:
            assert phrase not in body, (
                f"{source.relative_to(_UI)} contains {phrase!r} from the "
                "disclosure. The screen must READ the card, never restate it -- "
                "and a TEST that restates it is the same defect wearing a lock."
            )


def test_the_refusal_page_cannot_be_mistaken_for_the_disclosure() -> None:
    """When the card cannot be read, the operator must be told that what they
    are looking at is a missing answer rather than a clean one."""
    loader = _text(_LOADER)
    assert "treat nothing" in loader.lower()
    assert "could not be loaded" in loader
    assert "docs/governance/auditability-card.md" in loader, (
        "the refusal does not say where to read the real disclosure instead"
    )


@pytest.mark.parametrize(
    "not_wanted",
    ["coverage is complete", "fully audited", "everything is recorded"],
)
def test_the_screen_makes_no_blanket_assurance(not_wanted: str) -> None:
    """A coverage screen that only listed what IS governed would be the
    marketing version, which the ticket rules out explicitly."""
    for source in (_CODE_BEHIND, _LOADER, _XAML):
        assert not_wanted.lower() not in _text(source).lower()
