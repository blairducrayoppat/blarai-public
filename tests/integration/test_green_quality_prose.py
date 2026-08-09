"""#1281 — the deterministic PLACEHOLDER-PROSE floor over a banked GREEN's delivered pages.

The gap this suite locks: a website is mostly WORDS and nothing in the pipeline asked for any
of them. The intake asks about platform, surface, features and assets; the plan carries
``asset_specs`` for images and nothing for copy; the criteria grade behaviour. So a coder that
shipped lorem ipsum, or left "Welcome to My Site" in the ``<title>``, passed every gate and
was reported to a non-technical operator as GREEN band A, "Looks clean" — not because a grader
missed it, but because no grader was asking.

Three proofs carry this file, per the standing rule that a control ships with evidence it
BLOCKS, evidence it stays QUIET, and evidence the probe FAILS when the lock is off:

* **The placeholder delivery.** A pottery-studio site of the shape #1281 names, shipping
  filler. Driven through the REAL battery-close entry point (``BatterySummary.green_quality``
  -> ``audit_greens``), the finding must reach the scorecard evidence, the band, the sidecar
  on disk, the night's rollup and the operator's plain-language card.
* **The written delivery.** The SAME site with real (if plain) copy must band A and carry no
  finding. Without this half, a fired rule proves only that the rule fires.
* **The toggle.** The SAME placeholder tree with the prose scanner injected as a disabled
  stub must NOT drop below band A and must carry no prose finding — which is what separates
  "the copy was placeholder and we caught it" from "some other check happened to fire".

A fourth property gets its own section because it is the one that decides whether this
instrument can be trusted at all, and it is NOT the same property its security sibling has:
this scan must distinguish FOUR states, not three. A Python library has no user-visible prose,
and "not applicable" is not "clean" — a night of libraries must never render as a night of
well-written sites.

FALSE POSITIVES ARE WORSE THAN MISSES HERE, and the section that says so is the longest one.
A fail-loud control that convicts a correct page gets muted, and a muted control is worse than
the silence it replaced. The sharpest case is structural rather than lexical:
``<input placeholder="you@example.com">`` is the deliverable getting a form hint RIGHT, and a
scan that graded raw text instead of parsed visible text would punish it for that. Every guard
below was written against a real way to be wrong, not an imagined one.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.dispatch_harness.battery import BatterySummary
from tools.dispatch_harness.green_quality import (
    DISPOSITION_CLEAN,
    DISPOSITION_NOT_APPLICABLE,
    DISPOSITION_PLACEHOLDER,
    DISPOSITION_UNMEASURED,
    audit_green,
    audit_greens,
    band as band_mod,
    card as card_mod,
    placeholder_prose as prose,
    render_kpi,
)
from tools.dispatch_harness.green_quality.constants import (
    BAND_A,
    BAND_B,
    EV_PROSE,
    RESERVED_EVIDENCE_KEYS,
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
)
from tools.dispatch_harness.green_quality.layer1 import CraftFinding, Layer1Result, RegressionFinding
from tools.dispatch_harness.scorecard import Scorecard, validate

# ---------------------------------------------------------------------------
# Fixture trees — a pottery-studio site, once with placeholder copy and once written.
#
# The two differ ONLY in their words. Same files, same markup, same structure, so any band or
# finding difference between them is attributable to the prose scan and to nothing else.
# ---------------------------------------------------------------------------

_PLACEHOLDER_INDEX = """<!doctype html>
<html><head><title>Welcome to My Site</title></head>
<body>
  <h1>Your headline here</h1>
  <p>Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor.</p>
  <img src="bowl.jpg" alt="Image goes here">
  <form><input placeholder="you@example.com"><button>Sign up</button></form>
</body></html>
"""

_WRITTEN_INDEX = """<!doctype html>
<html><head><title>Ridge Pottery Studio</title></head>
<body>
  <h1>Hand-thrown stoneware from the Tyne valley</h1>
  <p>Small-batch pots, fired in a gas kiln, sold from the studio door on Saturdays.</p>
  <img src="bowl.jpg" alt="A grey stoneware bowl on a workbench">
  <form><input placeholder="you@example.com"><button>Sign up</button></form>
</body></html>
"""

_PLACEHOLDER_CONTACT = """<html><head><title>Contact</title></head>
<body><h2>Contact</h2>
  <p>Email: you@example.com</p>
  <p>Phone: 123-456-7890</p>
  <p>123 Main Street</p>
</body></html>
"""

_WRITTEN_CONTACT = """<html><head><title>Contact</title></head>
<body><h2>Contact</h2>
  <p>Email: pots@ridgestudio.co.uk</p>
  <p>Phone: 01434 601 118</p>
  <p>Unit 4, Bridge End Yard, Hexham</p>
</body></html>
"""


def _make_site(root: Path, *, placeholder: bool) -> Path:
    """A multi-page static site of the shape #1281's pottery-studio goal describes."""
    (root / "pages").mkdir(parents=True, exist_ok=True)
    (root / "index.html").write_text(
        _PLACEHOLDER_INDEX if placeholder else _WRITTEN_INDEX, encoding="utf-8")
    (root / "pages" / "contact.html").write_text(
        _PLACEHOLDER_CONTACT if placeholder else _WRITTEN_CONTACT, encoding="utf-8")
    (root / "style.css").write_text("body { font-family: system-ui; }\n", encoding="utf-8")
    return root


def _disabled_scanner(repo, surface=""):
    """The lock turned OFF: a scanner reporting a measured, applicable, empty result.

    Deliberately claims ``measured=True`` AND ``applicable=True`` — a stub returning "could not
    determine" or "not applicable" would be distinguishable from a working scan for the wrong
    reason, and the toggle could not tell a disabled lock from a clean deliverable. This stub
    is the only place in the tree allowed to assert written copy it never read."""
    return prose.ProseResult(measured=True, applicable=True, pages_scanned=0,
                             status="prose scanner disabled for this test")


def _l1_clean() -> Layer1Result:
    """A Layer-1 result with nothing flagged, so the band is decided by the prose scan alone.

    MEASURED-clean: a ``CraftFinding`` is born unmeasured (#1223), so a fixture that leaves the
    flag off asserts against "never looked" while its name claims "found nothing"."""
    clean = CraftFinding(False, "", measured=True)
    return Layer1Result(
        regression=RegressionFinding(False, False, "no behaviour change", measured=True),
        dead_scaffold=clean, stale_readme=clean, no_entry_point=clean,
        ruff_findings=None, surface="web")


def _scan_tree(tmp_path: Path, name: str, files: dict) -> prose.ProseResult:
    root = tmp_path / name
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return prose.scan_repo(root, "web")


# ---------------------------------------------------------------------------
# Each rule catches its planted placeholder — and stays quiet on the written equivalent
# ---------------------------------------------------------------------------


def test_lorem_ipsum_is_caught_at_high_severity(tmp_path):
    result = prose.scan_repo(_make_site(tmp_path / "ph", placeholder=True), "web")
    hits = [f for f in result.findings if f.rule == prose.RULE_LOREM_IPSUM]
    assert hits, "Latin filler in a delivered page was not caught"
    assert hits[0].severity == SEVERITY_HIGH
    assert hits[0].path == "index.html"


def test_fill_in_the_blank_copy_is_caught_at_high_severity(tmp_path):
    """"Your headline here" and an ``alt`` of "Image goes here" are the template's own
    instruction to write something, left in place of the writing."""
    result = prose.scan_repo(_make_site(tmp_path / "ph", placeholder=True), "web")
    hits = [f for f in result.findings if f.rule == prose.RULE_FILL_IN_THE_BLANK]
    assert hits, "fill-in-the-blank copy was not caught"
    assert {f.severity for f in hits} == {SEVERITY_HIGH}
    assert any("headline here" in f.detail.lower() for f in hits)
    assert any("goes here" in f.detail.lower() for f in hits), (
        "the alt text was not read - a screen-reader user hears that as the page's words"
    )


def test_a_scaffold_default_title_is_caught_but_never_band_moving(tmp_path):
    """The ``<title>`` is what the operator sees in the browser tab, and "Welcome to My Site"
    is the scaffold's. Caught at MEDIUM: near-certain, but conceivably deliberate."""
    result = prose.scan_repo(_make_site(tmp_path / "ph", placeholder=True), "web")
    hits = [f for f in result.findings if f.rule == prose.RULE_SCAFFOLD_TITLE]
    assert hits, "the scaffold's default document title survived unreported"
    assert hits[0].severity == SEVERITY_MEDIUM


def test_placeholder_contact_details_are_caught_in_visible_text(tmp_path):
    result = prose.scan_repo(_make_site(tmp_path / "ph", placeholder=True), "web")
    hits = [f for f in result.findings if f.rule == prose.RULE_PLACEHOLDER_CONTACT]
    rules_by_path = {f.path for f in hits}
    assert "pages/contact.html" in rules_by_path
    assert len(hits) >= 3, f"expected the email, phone and street to be caught: {hits}"


def test_starter_template_boilerplate_is_caught(tmp_path):
    """The framework demo strings, matched as long distinctive phrases so a short coincidence
    cannot trip them."""
    result = _scan_tree(tmp_path, "boot", {"index.html":
        "<html><body><div class='card'><p>Some quick example text to build on the card "
        "title and make up the bulk of the card's content.</p></div></body></html>"})
    assert any(f.rule == prose.RULE_STARTER_BOILERPLATE for f in result.findings)


def test_the_written_site_is_measured_clean(tmp_path):
    """THE DISCRIMINATION HALF. The same site, same markup, real words: no findings at all.
    A scan that flags everything grades nothing."""
    result = prose.scan_repo(_make_site(tmp_path / "ok", placeholder=False), "web")
    assert result.measured is True
    assert result.applicable is True
    assert result.disposition() == DISPOSITION_CLEAN
    assert result.is_clean() is True
    assert result.findings == (), result.findings_lines()
    assert result.pages_scanned == 2


# ---------------------------------------------------------------------------
# FALSE POSITIVES ARE WORSE THAN MISSES — the guards, each against a real way to be wrong
# ---------------------------------------------------------------------------


def test_a_placeholder_attribute_is_a_form_hint_and_never_a_finding(tmp_path):
    """THE SHARPEST GUARD IN THE FILE. ``placeholder="you@example.com"`` is a CORRECT form
    hint — that attribute exists to hold example text — and a raw text scan would convict the
    deliverable that wrote one. Parsing the page rather than grepping it is what makes the
    difference, so this asserts the mechanism and not merely the outcome."""
    result = _scan_tree(tmp_path, "hint", {"index.html":
        "<html><head><title>Ridge Pottery</title></head><body>"
        "<form><input placeholder='you@example.com'>"
        "<input placeholder='Your name here'>"
        "<textarea placeholder='Tell us what you are looking for'></textarea>"
        "</form></body></html>"})
    assert result.is_clean() is True, (
        f"a correct form hint was convicted as placeholder prose: {result.findings_lines()}"
    )


def test_a_real_title_that_merely_starts_like_a_scaffold_is_untouched(tmp_path):
    """The scaffold-title rule matches the WHOLE normalised element. "Welcome to My Pottery
    Studio" is a real choice; a substring rule would flag it and the operator would learn to
    ignore the caveat."""
    result = _scan_tree(tmp_path, "title", {"index.html":
        "<html><head><title>Welcome to My Pottery Studio</title></head>"
        "<body><h1>My Site Visits, 2019-2026</h1><p>A travel diary.</p></body></html>"})
    assert result.is_clean() is True, result.findings_lines()


def test_ordinary_words_that_merely_sound_like_placeholders_are_untouched(tmp_path):
    """A legitimate page can contain "sample", "example" and a product actually named
    Placeholder. This scan grades placeholder-versus-written, never plain-versus-polished."""
    result = _scan_tree(tmp_path, "words", {"index.html":
        "<html><head><title>Ridge Pottery Studio</title></head><body>"
        "<h1>Glaze samples</h1>"
        "<p>Ask for a sample tile before ordering a full set. For example, the ash glaze "
        "shifts colour on a thicker pot.</p>"
        "<p>Our Placeholder mug, named for the gap it fills on a shelf, is back in stock.</p>"
        "<p>Enter your email here to hear about firings.</p>"
        "</body></html>"})
    assert result.is_clean() is True, (
        f"genuine prose was convicted: {result.findings_lines()}"
    )


#: Genuine commercial and form copy an independent review MEASURED this scan convicting, every
#: one of them at HIGH — the tier that moves a band and takes the operator's single caveat slot.
#: A false HIGH is not noise here: the card renders security -> prose -> craft, so a wrong prose
#: sentence EVICTS the true Layer-1 one. Each row is the shape, not merely the string: the words
#: of an instruction inside somebody's sentence.
_MEASURED_FALSE_POSITIVES: dict[str, str] = {
    "sponsor slot": "<p>Your logo here — become a supporter of the festival.</p>",
    "directory advertisement": "<p>Advertise your business here from just 20 pounds a month.</p>",
    "visible form label": "<p>Enter your address here and we will confirm by email.</p>",
    "profile helper text": "<p>Enter your bio here.</p>",
    "tutorial about markup": "<p>The title goes here, between the tags.</p>",
    "real Main Street address": "<address>Ridge Pottery, 23 Main Street, Hexham</address>",
    "checkout instruction": "<p>Please enter your address, city, state and postcode.</p>",
}


@pytest.mark.parametrize("name", sorted(_MEASURED_FALSE_POSITIVES))
def test_genuine_copy_that_reuses_placeholder_words_is_not_convicted(tmp_path, name):
    """THE MEASURED FALSE POSITIVES, one test per shape.

    "Enter your address here" is the case that inverts this module's own central argument: it
    parses rather than greps because ``placeholder="you@example.com"`` is the deliverable
    getting a form hint RIGHT — and a VISIBLE label saying the same thing is the MORE accessible
    pattern (WCAG discourages placeholder-only labelling). Convicting it punished the page that
    labelled its form properly."""
    result = _scan_tree(tmp_path, f"fp-{name.replace(' ', '-')}", {"index.html":
        "<html><head><title>Ridge Pottery Studio</title></head><body>"
        + _MEASURED_FALSE_POSITIVES[name] +
        "</body></html>"})
    assert result.is_clean() is True, (
        f"genuine copy was convicted ({name}): {result.findings_lines()}"
    )


def test_the_instruction_shape_still_fires_when_it_stands_alone(tmp_path):
    """THE OTHER HALF of the narrowing above, and the half that keeps it a control. The same
    words with no sentence around them ARE the template's instruction, and every one of them
    must still be caught at HIGH — including on the raw component path, where the text between
    two tags is the closest thing to a text node available."""
    # One per LINE: `_dedupe` collapses findings sharing a rule, file and line, so a single-line
    # page would prove only that the first of them fires.
    result = _scan_tree(tmp_path, "shapes", {
        "index.html": "<html><head><title>Ridge Pottery</title></head><body>\n"
                      "<h1>Your headline here</h1>\n"
                      "<td>Your name here</td>\n"
                      "<p>Description goes here</p>\n"
                      "<img src='x.png' alt='Image goes here'>\n"
                      "</body></html>\n",
        "src/Hero.jsx": "export const Hero = () => (<section><p>Your text here</p></section>);\n",
    })
    hits = [f for f in result.at_or_above(SEVERITY_HIGH)
            if f.rule == prose.RULE_FILL_IN_THE_BLANK]
    caught = " | ".join(f.detail.lower() for f in hits)
    for expected in ("headline here", "name here", "goes here", "your text here"):
        assert expected in caught, f"a standalone instruction stopped firing: {expected} ({caught})"
    assert any(f.path == "src/Hero.jsx" for f in hits), (
        "the raw component path lost the instruction rule entirely"
    )


def test_only_the_canonical_template_street_number_is_a_finding(tmp_path):
    """The MEDIUM tier's own docstring claims these are "the canonical template strings, not
    merely plausible-looking ones", and ``1?23`` broke that claim: it matched an ordinary house
    number on the commonest street name in the anglosphere. Both halves pinned, because a rule
    that stops firing on 123 Main Street is not a narrowing, it is a deletion."""
    real = _scan_tree(tmp_path, "st-real", {"index.html":
        "<html><head><title>Ridge Pottery</title></head>"
        "<body><address>Ridge Pottery, 23 Main Street, Hexham</address></body></html>"})
    assert real.is_clean() is True, real.findings_lines()

    template = _scan_tree(tmp_path, "st-tpl", {"index.html":
        "<html><head><title>Ridge Pottery</title></head>"
        "<body><address>123 Main Street, Anytown</address></body></html>"})
    assert any(f.rule == prose.RULE_PLACEHOLDER_CONTACT for f in template.findings), (
        f"the canonical template address stopped being caught: {template.findings_lines()}"
    )


def test_an_attribute_inside_a_suppressed_element_is_suppressed_too(tmp_path):
    """ONE SUPPRESSION CONTRACT, BOTH HALVES. ``handle_data`` dropped element text inside a
    ``<template>`` while the attribute read did not, so the module held two opposite positions
    about the same element: its text was markup, its ``alt`` was the page's words."""
    result = _scan_tree(tmp_path, "supp-attr", {"index.html":
        "<html><head><title>Ridge Pottery</title></head><body>"
        "<template><img alt='Lorem ipsum dolor sit amet'></template>"
        "<p>Hand-thrown stoneware from the Tyne valley.</p>"
        "</body></html>"})
    assert result.is_clean() is True, result.findings_lines()


def test_bland_but_genuine_copy_is_not_a_finding(tmp_path):
    """THE LIMIT, ASSERTED RATHER THAN ONLY DOCUMENTED. Copy that is dull, generic and
    obviously written in thirty seconds is still WRITTEN, and this scan must not pretend to
    grade it. The ceiling belongs to the operator's review loop (#1280) and to asking him what
    the site should say (#1281 parts 1 and 2) — not to a lint."""
    result = _scan_tree(tmp_path, "bland", {"index.html":
        "<html><head><title>Ridge Pottery Studio</title></head><body>"
        "<h1>Welcome</h1><p>We are passionate about quality and committed to excellence. "
        "Our team works hard to deliver the best possible experience.</p>"
        "</body></html>"})
    assert result.is_clean() is True
    assert result.disposition() == DISPOSITION_CLEAN


def test_code_and_script_bodies_are_not_the_pages_words(tmp_path):
    """A tutorial page that SHOWS a lorem-ipsum snippet inside ``<code>``, and a script that
    holds a demo string, are not the page telling the reader lorem ipsum."""
    result = _scan_tree(tmp_path, "code", {"index.html":
        "<html><head><title>Ridge Pottery Studio</title></head><body>"
        "<p>Designers use filler text while a layout is drafted:</p>"
        "<pre><code>Lorem ipsum dolor sit amet</code></pre>"
        "<script>const demo = 'Lorem ipsum dolor sit amet';</script>"
        "</body></html>"})
    assert result.is_clean() is True, result.findings_lines()


def test_a_fixture_page_is_demoted_not_dropped(tmp_path):
    """A test fixture legitimately carries lorem ipsum, that being what a fixture is for. One
    level down, never silence — a fixture that became the delivered page is still delivered."""
    result = _scan_tree(tmp_path, "fx", {
        "index.html": "<html><head><title>Ridge Pottery</title></head><body><p>Pots.</p></body></html>",
        "tests/fixture.html": "<html><body><p>Lorem ipsum dolor sit amet.</p></body></html>"})
    assert result.findings, "a demoted finding must still be reported"
    assert result.worst_severity == SEVERITY_MEDIUM
    assert result.at_or_above(SEVERITY_HIGH) == ()


# ---------------------------------------------------------------------------
# FOUR STATES, not three — the property this instrument has and its sibling does not
# ---------------------------------------------------------------------------


def test_a_python_library_is_not_applicable_and_never_clean(tmp_path):
    """A library has no user-visible prose. That is the correct answer, and it is NOT the same
    claim as "the words are fine" — this scan approves what it read, and it read nothing here.

    Scoped as the brief requires: a Python library must be UNAFFECTED, which means neither
    convicted nor credited."""
    result = _scan_tree(tmp_path, "lib", {
        "app.py": "def add(a, b):\n    return a + b\n",
        "README.md": "# Adder\n\nAdds two numbers.\n"})
    assert result.measured is True
    assert result.applicable is False
    assert result.disposition() == DISPOSITION_NOT_APPLICABLE
    assert result.is_clean() is False, (
        "a library reported CLEAN prose - a night of libraries would render as a night of "
        "well-written sites"
    )
    assert "not-applicable" in result.summary()
    assert band_mod.compute_band(_l1_clean(), None, None, result) == BAND_A
    assert card_mod._caveat_from_prose(result) == ""


def test_the_four_states_each_render_differently(tmp_path):
    """The collapse this instrument exists to refuse, asserted as four distinct strings. Two
    states that render identically are two facts the operator cannot tell apart."""
    unmeasured = prose.scan_repo(tmp_path / "nope")
    not_applicable = _scan_tree(tmp_path, "lib2", {"app.py": "x = 1\n"})
    clean = prose.scan_repo(_make_site(tmp_path / "ok2", placeholder=False), "web")
    found = prose.scan_repo(_make_site(tmp_path / "ph2", placeholder=True), "web")

    dispositions = [r.disposition() for r in (unmeasured, not_applicable, clean, found)]
    assert dispositions == [DISPOSITION_UNMEASURED, DISPOSITION_NOT_APPLICABLE,
                            DISPOSITION_CLEAN, DISPOSITION_PLACEHOLDER]
    assert len({r.summary() for r in (unmeasured, not_applicable, clean, found)}) == 4


# ---------------------------------------------------------------------------
# FAIL-SOFT, NEVER FAIL-OPEN
# ---------------------------------------------------------------------------


def test_a_scan_that_cannot_run_is_never_clean(tmp_path):
    result = prose.scan_repo(tmp_path / "no-such-tree")
    assert result.measured is False
    assert result.is_clean() is False
    assert result.disposition() == DISPOSITION_UNMEASURED
    assert "could-not-determine" in result.summary()


def test_a_none_repo_is_could_not_determine_rather_than_a_crash():
    result = prose.scan_repo(None)
    assert result.measured is False
    assert "not resolved" in result.status


def test_a_scanner_that_raises_degrades_to_could_not_determine(tmp_path):
    """A scanner fault must not sink battery close, and must not vanish either."""
    def _boom(repo, surface=""):
        raise RuntimeError("prose scanner exploded")

    _make_site(tmp_path / "out" / "repos-archived" / "battery-b9-pottery-web", placeholder=False)
    sc = Scorecard(job_id="B9", verdict="GREEN", repo="battery-b9-pottery-web", run_id="R1")
    result = audit_green(sc, out_dir=tmp_path / "out", surface="web", prose_scan=_boom)
    assert result.prose.measured is False
    assert "RuntimeError" in result.prose.status
    assert result.prose.disposition() == DISPOSITION_UNMEASURED


def test_an_unparseable_page_falls_back_and_says_so(tmp_path, monkeypatch):
    """The fallback path, driven deliberately because it is DEFENSIVE: Python's ``HTMLParser``
    is lenient enough that a real delivered page essentially never fails it, which is exactly
    why the branch would rot unproven. The property under test is #1183's lesson — a page that
    drops to the weaker rule set must be COUNTED and NAMED, never silently downgraded."""
    monkeypatch.setattr(prose, "extract_visible_text", lambda html: None)
    result = _scan_tree(tmp_path, "unparsed", {"index.html":
        "<html><body><p>Lorem ipsum dolor sit amet.</p>"
        "<input placeholder='you@example.com'></body></html>"})
    assert result.measured is True
    assert "did not parse" in result.status
    assert any(f.rule == prose.RULE_LOREM_IPSUM for f in result.findings), (
        "the unambiguous tier must still run on a page that could not be parsed"
    )
    assert not any(f.rule == prose.RULE_PLACEHOLDER_CONTACT for f in result.findings), (
        "the visible-only tier ran over raw source, where a form hint is indistinguishable "
        "from placeholder contact copy"
    )


def test_a_truncated_finding_list_keeps_every_high(tmp_path):
    """Past the finding cap the list becomes a SEVERITY record. A cap that could drop the one
    HIGH behind fifty MEDIUMs would quietly restore band A, which is the fail-open this
    instrument exists to refuse."""
    files = {f"p{i:03d}.html": f"<html><head><title>My Website</title></head>"
                               f"<body><p>Page {i}</p></body></html>" for i in range(60)}
    files["zz_last.html"] = "<html><body><p>Lorem ipsum dolor sit amet.</p></body></html>"
    result = _scan_tree(tmp_path, "many", files)
    assert result.measured is True
    assert result.worst_severity == SEVERITY_HIGH, "the HIGH behind the cap was truncated away"
    assert "capped" in result.status
    assert band_mod.compute_band(_l1_clean(), None, None, result) == BAND_B


# ---------------------------------------------------------------------------
# EDITED INTO SILENCE — the ways this scan can be made to look at nothing
# ---------------------------------------------------------------------------


def test_a_dependency_tree_is_skipped_and_the_blind_spot_is_named(tmp_path):
    """``node_modules`` is full of demo pages whose lorem ipsum is nobody's deliverable, so it
    is skipped — and the reader is TOLD, rather than left to infer that "no placeholder prose"
    meant "everywhere"."""
    result = _scan_tree(tmp_path, "nm", {
        "index.html": "<html><head><title>Ridge Pottery</title></head><body><p>Pots.</p></body></html>",
        "node_modules/ui/demo.html": "<html><body><p>Lorem ipsum dolor sit amet.</p></body></html>"})
    assert result.is_clean() is True
    assert "NOT read" in result.status and "node_modules" in result.status


@pytest.mark.parametrize("tag", ["pre", "code", "template"])
def test_an_unclosed_suppressing_tag_cannot_silence_the_rest_of_the_page(tmp_path, tag):
    """THE SILENCING VECTOR THAT PARSES — and the one this module's honesty machinery was
    NOT spending itself on.

    An unclosed ``<pre>`` suppresses every remaining text node, so a page could ship lorem
    ipsum below it and report zero findings, zero unparsed pages, and disposition CLEAN. The
    parse SUCCEEDS, which is what made it invisible: the defended fallback path counts pages
    that fail to parse, and an independent review measured that path to be effectively
    unreachable (truncated tags, ``<<<>>>``, NUL bytes, 3000-deep nesting and unterminated
    attributes all parse without raising). The counted vector never fired; the uncounted one
    did.

    Two properties, and the finding is the load-bearing one — a status line nobody reads is
    not a control."""
    result = _scan_tree(tmp_path, f"silent-{tag}", {"index.html":
        f"<html><head><title>Ridge Pottery</title></head><body><p>Intro</p><{tag}>sample"
        "<p>Lorem ipsum dolor sit amet, consectetur adipiscing elit.</p></body></html>"})
    assert result.worst_severity == SEVERITY_HIGH, (
        f"an unclosed <{tag}> silenced the rest of the page: {result.status}"
    )
    assert result.disposition() == DISPOSITION_PLACEHOLDER
    assert "went silent" in result.status, (
        f"the page went silent and the status did not say so: {result.status}"
    )


def test_a_balanced_code_block_is_still_not_the_pages_words(tmp_path):
    """THE TOGGLE ON THE FIX ABOVE. The re-scan fires on UNBALANCED markup only — a properly
    closed ``<pre><code>`` showing a lorem-ipsum example is a tutorial doing its job, and if
    this went red the fix would have bought its detection by convicting every page that
    displays a code sample."""
    result = _scan_tree(tmp_path, "balanced", {"index.html":
        "<html><head><title>Ridge Pottery</title></head><body>"
        "<p>Designers use filler text while a layout is drafted:</p>"
        "<pre><code>Lorem ipsum dolor sit amet</code></pre>"
        "</body></html>"})
    assert result.is_clean() is True, result.findings_lines()
    assert "went silent" not in result.status


def test_build_output_is_read_because_a_shipped_page_is_a_shipped_page(tmp_path):
    """The mirror of the security scan's ``dist/`` fail-open. A static site's built page is the
    one the operator opens, so filler there is shipped filler — skipping build trees would let
    a deliverable hide its only real page from the only check that reads pages."""
    result = _scan_tree(tmp_path, "dist", {
        "src/App.jsx": "export default () => <p>Hand-thrown stoneware.</p>;\n",
        "dist/index.html": "<html><body><p>Lorem ipsum dolor sit amet.</p></body></html>"})
    assert result.worst_severity == SEVERITY_HIGH
    assert result.is_clean() is False


def test_a_component_file_gets_the_unambiguous_tier_only(tmp_path):
    """A ``.jsx`` cannot be parsed for visible text, so it gets the raw scan restricted to the
    rules that hold without context. Latin filler is filler wherever it sits; a template phone
    number in raw source might be a form hint, and is not graded there."""
    result = _scan_tree(tmp_path, "jsx", {"src/Hero.jsx":
        "export const Hero = () => (<section>"
        "<p>Lorem ipsum dolor sit amet.</p>"
        "<input placeholder='123-456-7890' />"
        "</section>);\n"})
    assert any(f.rule == prose.RULE_LOREM_IPSUM for f in result.findings)
    assert not any(f.rule == prose.RULE_PLACEHOLDER_CONTACT for f in result.findings)


# ---------------------------------------------------------------------------
# SEED PROOF — the scan fires on REAL fleet substrate, not just on fixtures
#
# A lint proven only against a defect its own author planted proves the regex, not the
# instrument. The fleet's build-infra holds the seeds every coder job extends, and the
# ``web-static`` seed — the starting point for exactly the multi-page static site #1281 is
# about — ships ``<h1 class="placeholder">Page title goes here</h1>`` and "Replace this
# paragraph with the real introduction the goal asks for". Nobody planted that; it is the
# template doing its job, and a deliverable that leaves it in place is the failure this whole
# ticket describes.
#
# Honest scope, because it bounds what this evidence supports: this proves the scan catches
# real fleet copy that a coder is free to leave behind, NOT that any archived GREEN was ever
# reported clean while carrying it. The four archived B5 web deliverables measured here are
# all CLEAN — their coders did write their own words.
# ---------------------------------------------------------------------------

_BUILD_INFRA = Path("C:/Users/mrbla/agentic-setup/build-infra")


def test_seed_proof_the_web_static_seed_carries_fill_in_the_blank_copy():
    """The real ``web-static`` seed page must be caught, and must be caught at HIGH.

    This is the case the scan exists for: a static-site deliverable whose coder wired up the
    layout and never replaced the words would ship this page, and before #1281 it banded A."""
    seed = _BUILD_INFRA / "web-static" / "reference"
    if not seed.is_dir():
        pytest.skip("agentic-setup web-static seed not present")
    result = prose.scan_repo(seed, "web")
    assert result.measured is True
    assert result.disposition() == DISPOSITION_PLACEHOLDER
    hits = [f for f in result.at_or_above(SEVERITY_HIGH)
            if f.rule == prose.RULE_FILL_IN_THE_BLANK]
    assert hits, f"the real web-static seed's placeholder copy was not caught: {result.status}"
    assert any("goes here" in f.detail.lower() for f in hits)


def test_seed_proof_the_non_web_seeds_are_all_not_applicable():
    """The scope guard on real substrate: the python, node-cli, cpp, powershell, dotnet and
    android seeds have no user-visible prose, and every one must report NOT APPLICABLE rather
    than clean or flagged. A library being 'unaffected' is a claim worth measuring."""
    if not _BUILD_INFRA.is_dir():
        pytest.skip("agentic-setup build-infra not present")
    non_web = ["python", "node-cli", "cpp", "powershell", "dotnet-console"]
    present = [(name, _BUILD_INFRA / name / "reference") for name in non_web]
    present = [(name, path) for name, path in present if path.is_dir()]
    if not present:
        pytest.skip("no non-web seeds present")
    for name, path in present:
        result = prose.scan_repo(path, "python-lib")
        assert result.disposition() == DISPOSITION_NOT_APPLICABLE, (
            f"the {name} seed reported {result.disposition()} — a deliverable with no pages "
            f"must be neither convicted nor credited by a check about web copy"
        )


# ---------------------------------------------------------------------------
# The band formula — where a finding becomes a consequence
# ---------------------------------------------------------------------------


def _prose_with(*severities: str) -> prose.ProseResult:
    findings = tuple(
        prose.ProseFinding(prose.RULE_LOREM_IPSUM if s == SEVERITY_HIGH
                           else prose.RULE_SCAFFOLD_TITLE, s, "index.html", 4, "detail")
        for s in severities)
    return prose.ProseResult(findings, measured=True, applicable=True,
                             status="read 2 page(s) and 0 template(s)", pages_scanned=2)


def test_band_high_severity_placeholder_is_B_and_never_C():
    """#1281's stated predicate: a delivery that ships lorem ipsum is REPORTED rather than
    banded A. Never a C — the cost asymmetry that earns security its C runs the other way
    here, and a page of filler costs the operator a reread, not a leaked credential."""
    assert band_mod.compute_band(_l1_clean(), None, None, _prose_with(SEVERITY_HIGH)) == BAND_B


def test_band_medium_severity_never_moves_the_band():
    """A scaffold's default title is near-certain and conceivably deliberate. Recorded in the
    sidecar, stamped in the evidence, counted in the rollup — and not a letter."""
    assert band_mod.compute_band(_l1_clean(), None, None, _prose_with(SEVERITY_MEDIUM)) == BAND_A


def test_band_unmeasured_prose_scan_does_not_move_the_band():
    """THE DELIBERATE INVERSION of the security rule, asserted so it cannot drift into place
    unnoticed. An unmeasured SECURITY scan bands B because its silence is dangerous; an
    unmeasured PROSE scan does not, because a tree unreadable enough to blind it blinds every
    Layer-1 lint too, and a caveat spent on "the wording check could not run" displaces the
    finding the operator can act on. It is still stamped, counted and rendered."""
    unmeasured = prose.ProseResult()
    assert band_mod.compute_band(_l1_clean(), None, None, unmeasured) == BAND_A
    assert "could-not-determine" in unmeasured.summary()


def test_band_without_a_supplied_prose_scan_is_unchanged():
    """``prose=None`` is 'this caller composed no scan', not 'the scan failed'. Existing
    callers must keep their previous bands."""
    assert band_mod.compute_band(_l1_clean(), None) == BAND_A
    assert band_mod.compute_band(_l1_clean(), None, None, None) == BAND_A


def test_band_names_the_prose_trigger_in_plain_language():
    """A B the operator cannot act on is an opaque letter. The reason names the rule, the file
    and the line, and says what it means to someone who cannot read code."""
    _band, _c, b_reasons = band_mod.band_reasons(_l1_clean(), None, None,
                                                 _prose_with(SEVERITY_HIGH))
    assert b_reasons and "index.html:4" in b_reasons[0]
    assert "fake Latin filler" in b_reasons[0]


# ---------------------------------------------------------------------------
# REACHABILITY — the placeholder delivery through the REAL battery-close entry point
# ---------------------------------------------------------------------------


def _green_run(tmp_path: Path, *, placeholder: bool, monkeypatch=None, prose_band: bool = False):
    """Drive a GREEN B9 through ``BatterySummary.green_quality`` — the method ``battery.py``
    itself calls at close — and return ``(scorecard, summary)``.

    ``monkeypatch``/``prose_band`` replace the CONSEQUENCE-GATE RESOLVER, not the gate: the
    battery-close path still calls it, still branches on its answer, and still composes the
    band and the card from that branch. Substituting the resolver rather than passing the
    decision in is what makes this the reachability proof for the gate itself — if
    ``audit_greens`` ever stopped consulting it, the granted half of this pair would fail."""
    out_dir = tmp_path / "battery" / "20260806-000001"
    _make_site(out_dir / "repos-archived" / "battery-b9-pottery-web", placeholder=placeholder)
    sc = Scorecard(job_id="B9", verdict="GREEN", attribution="", repo="battery-b9-pottery-web",
                   run_id="R1", evidence={"oracle_status": "passed"})
    summary = BatterySummary(scorecards=[sc], out_dir=str(out_dir))
    if monkeypatch is not None:
        monkeypatch.setattr(prose, "prose_band_enabled", lambda cfg=None: prose_band)
    summary.green_quality(runs_dir=tmp_path / "runs", out_dir=out_dir,
                          job_surfaces={"B9": "web"})
    return sc, summary


def test_placeholder_delivery_reaches_the_scorecard_the_band_and_the_card(tmp_path, monkeypatch):
    """THE REACHABILITY PROOF. A control nothing calls is not a control, so this drives the
    real object through the real entry point and checks every surface the finding must arrive
    on: the band, the reserved evidence key, the sidecar on disk, the night's rollup, and the
    plain-language card the operator actually reads.

    Run with the #1281 consequence gate GRANTED, because the band and the card are the two
    surfaces it gates; every OTHER surface asserted here is reached with the gate closed too,
    which is what :func:`test_the_measurement_reaches_every_surface_while_the_band_is_dormant`
    pins separately."""
    sc, summary = _green_run(tmp_path, placeholder=True, monkeypatch=monkeypatch, prose_band=True)

    # The verdict is untouched — this audit is advisory, and a prose finding does not change
    # that. It changes what the operator is TOLD about the GREEN.
    assert sc.verdict == "GREEN" and sc.attribution == ""

    assert sc.evidence["green_quality_band"] == BAND_B
    assert prose.RULE_LOREM_IPSUM in sc.evidence[EV_PROSE]

    sidecar = json.loads((tmp_path / "runs" / "R1" / "green-quality.json").read_text(encoding="utf-8"))
    assert sidecar["prose"]["disposition"] == DISPOSITION_PLACEHOLDER
    assert sidecar["prose"]["measured"] is True
    assert sidecar["prose"]["applicable"] is True
    assert sidecar["prose"]["worst_severity"] == SEVERITY_HIGH
    rules = {f["rule"] for f in sidecar["prose"]["findings"]}
    assert {prose.RULE_LOREM_IPSUM, prose.RULE_FILL_IN_THE_BLANK,
            prose.RULE_SCAFFOLD_TITLE} <= rules
    # EVERY finding carries its plain-language sentence, including the MEDIUM ones the band
    # and the card never render. A rule whose sentence is reachable from nothing is the
    # built-but-wired-into-nothing shape, and it is cheap to make it impossible here.
    assert all(f["means"] for f in sidecar["prose"]["findings"]), (
        "a finding reached the sidecar with no plain-language meaning attached"
    )

    assert summary.green_quality_block["prose_placeholder"] == 1
    assert summary.green_quality_block["prose_unmeasured"] == 0
    assert summary.green_quality_block["prose_not_applicable"] == 0
    assert summary.green_quality_block["bands"][BAND_B] == 1

    # The operator's card says it in words he can check with his own eyes.
    assert "filler text" in sc.evidence["green_quality_card"] or \
           "your text here" in sc.evidence["green_quality_card"].lower()

    # The night's KPI line carries the prose counts, including the zeroes.
    kpi = render_kpi(summary.green_quality_block)
    assert any("prose: placeholder=1" in line for line in kpi), kpi
    assert any("no-prose-surface=0" in line for line in kpi), kpi


def test_the_written_delivery_bands_A_through_the_same_path(tmp_path):
    """The discrimination half at the e2e level: the same site with real words banks band A
    with a measured-clean prose scan. Without this, band B proves only that the scan fires."""
    sc, summary = _green_run(tmp_path, placeholder=False)
    assert sc.evidence["green_quality_band"] == BAND_A
    assert sc.evidence[EV_PROSE].startswith("no placeholder prose")
    assert summary.green_quality_block["prose_placeholder"] == 0
    assert summary.green_quality_block["prose_clean"] == 1
    assert summary.green_quality_block["prose_unmeasured"] == 0


def test_toggle_off_the_probe_fails_to_catch_the_same_placeholders(tmp_path):
    """THE TOGGLE PROOF. The identical placeholder tree, with the scanner injected as a
    disabled stub, must NOT leave band A and must carry no prose finding.

    This is what distinguishes "the copy was placeholder and we caught it" from "some other
    check happened to fire". If this test ever passes with band B, the B above was never
    attributable to the prose scan and the control is decoration."""
    out_dir = tmp_path / "battery" / "20260806-000001"
    _make_site(out_dir / "repos-archived" / "battery-b9-pottery-web", placeholder=True)
    sc = Scorecard(job_id="B9", verdict="GREEN", attribution="", repo="battery-b9-pottery-web",
                   run_id="R1", evidence={"oracle_status": "passed"})
    block = audit_greens([sc], runs_dir=tmp_path / "runs", out_dir=out_dir,
                         job_surfaces={"B9": "web"}, prose_scan=_disabled_scanner)

    assert sc.evidence["green_quality_band"] == BAND_A
    assert block["prose_placeholder"] == 0
    sidecar = json.loads((tmp_path / "runs" / "R1" / "green-quality.json").read_text(encoding="utf-8"))
    assert sidecar["prose"]["findings"] == []


# ---------------------------------------------------------------------------
# THE CONSEQUENCE GATE — measurement always, band and card only when granted
#
# The instrument ships in two halves on two tracks. Everything that MEASURES is unconditional,
# because counts against real deliverables are the evidence any later argument about this scan
# has to rest on, and an instrument that banks nothing until it is trusted can never become
# trustworthy. Everything that CHANGES WHAT THE OPERATOR READS waits behind
# ``[fleet_dispatch].green_quality_prose_band``.
#
# Both directions are pinned, per the standing rule that a lock ships with evidence it BLOCKS
# and evidence the probe FAILS when the lock is off: a flag with only an off-test cannot tell
# "dormant" from "broken", and one with only an on-test cannot tell "dormant" from "wired to
# nothing".
# ---------------------------------------------------------------------------


def test_the_measurement_reaches_every_surface_while_the_band_is_dormant(tmp_path):
    """THE OFF HALF, driven through the REAL battery-close entry point with NOTHING patched —
    the shipped posture, resolved from the shipped config.

    The same placeholder delivery whose band and caveat the granted test asserts: here it must
    band A and carry no prose sentence on the card, while the sidecar, the evidence stamp, the
    rollup counts and the KPI line all carry the finding in full. Withholding the band is only
    free if the measurement is genuinely untouched, so this asserts that it is."""
    sc, summary = _green_run(tmp_path, placeholder=True)

    assert sc.evidence["green_quality_band"] == BAND_A, (
        "the prose band contribution is live in the shipped config — this is a quality change "
        "to what the operator reads and it waits for the LA's ceremony"
    )
    assert "filler text" not in sc.evidence["green_quality_card"]
    assert "your text here" not in sc.evidence["green_quality_card"].lower()

    # ...and every measuring surface is unaffected.
    assert prose.RULE_LOREM_IPSUM in sc.evidence[EV_PROSE]
    sidecar = json.loads((tmp_path / "runs" / "R1" / "green-quality.json").read_text(encoding="utf-8"))
    assert sidecar["prose"]["disposition"] == DISPOSITION_PLACEHOLDER
    assert sidecar["prose"]["worst_severity"] == SEVERITY_HIGH
    assert {f["rule"] for f in sidecar["prose"]["findings"]} >= {prose.RULE_LOREM_IPSUM}
    assert summary.green_quality_block["prose_placeholder"] == 1
    assert any("prose: placeholder=1" in line for line in render_kpi(summary.green_quality_block))

    # And the band's own reasons name nothing about prose — the letter is A for the honest
    # reason (no trigger), not because a reason was rendered and then dropped.
    assert not any("placeholder prose" in r
                   for r in sidecar["band_reasons"]["b"] + sidecar["band_reasons"]["c"])


def test_granting_the_gate_is_what_turns_the_finding_into_a_band_and_a_caveat(tmp_path, monkeypatch):
    """THE ON HALF. The identical tree with the resolver answering True must band B AND put the
    prose sentence in the operator's one caveat slot.

    Without this, "dormant" is indistinguishable from "the wiring was never finished" — and the
    two would be told apart only on the night the LA flips the flag, which is the worst possible
    moment to discover it."""
    sc, _summary = _green_run(tmp_path, placeholder=True, monkeypatch=monkeypatch, prose_band=True)
    assert sc.evidence["green_quality_band"] == BAND_B
    card = sc.evidence["green_quality_card"]
    assert "filler text" in card or "your text here" in card.lower(), card


def test_the_gate_displaces_nothing_it_was_not_granted(tmp_path, monkeypatch):
    """THE DISPLACEMENT ARGUMENT, asserted rather than only reasoned about in a docstring.

    The card holds ONE caveat, ordered security -> prose -> craft, so a granted prose finding
    takes the slot from the Layer-1 sentence beneath it. That is the whole cost of a false
    positive here and the whole reason the gate starts closed: with the gate shut the craft
    caveat is what the operator reads; with it open the prose one is."""
    l1 = Layer1Result(
        regression=RegressionFinding(False, False, "no behaviour change", measured=True),
        dead_scaffold=CraftFinding(True, "it still contains some unused starter code that was "
                                         "never cleaned up (harmless, but untidy).", measured=True),
        stale_readme=CraftFinding(False, "", measured=True),
        no_entry_point=CraftFinding(False, "", measured=True),
        ruff_findings=None, surface="web")
    found = _prose_with(SEVERITY_HIGH)

    withheld = card_mod.build_card("B9", "web", BAND_B, l1, prose=None)
    granted = card_mod.build_card("B9", "web", BAND_B, l1, prose=found)
    assert "starter code" in withheld.caveat
    assert "filler text" in granted.caveat
    assert withheld.caveat != granted.caveat, (
        "the prose caveat did not displace the craft one — the ordering this gate exists to "
        "protect is not actually in force"
    )


def test_the_consequence_gate_is_validated_not_coerced(tmp_path):
    """The #1042 rule on the flag that decides what the operator READS. Only an explicit TOML
    boolean ``true`` grants it; the shape a hand-edited rollback takes (a quoted "false") and
    every other non-boolean must resolve to a denial, not to a truthy string."""
    from tools.dispatch_harness.config import load_harness_config

    def _cfg(literal: str):
        path = tmp_path / f"cfg{abs(hash(literal))}.toml"
        path.write_text(f"[fleet_dispatch]\ngreen_quality_prose_band = {literal}\n",
                        encoding="utf-8")
        return load_harness_config(path)

    assert prose.prose_band_enabled(_cfg("true")) is True
    for denied in ('false', '"false"', '"true"', "1", "[]"):
        assert prose.prose_band_enabled(_cfg(denied)) is False, denied

    # An absent key and an absent FILE both deny — fail-closed in every direction.
    empty = tmp_path / "empty.toml"
    empty.write_text("[fleet_dispatch]\n", encoding="utf-8")
    assert prose.prose_band_enabled(load_harness_config(empty)) is False
    assert prose.prose_band_enabled(load_harness_config(tmp_path / "no-such.toml")) is False


def test_a_config_fault_denies_the_consequence_rather_than_raising(monkeypatch):
    """FAIL-CLOSED, not fail-soft-into-granted. A loader that raises must deny — and must not
    take an advisory audit down with it.

    BOTH FAULT SITES, because the docstring promises "every direction" and an earlier version
    of this function guarded only the first: the LOAD can raise, and so can the READ of the
    resolved value. Exercising only the guarded half would have left the fail-closed claim —
    which this project reads as a security assertion rather than a description — asserted by
    nothing, which is how a docstring becomes the least trustworthy thing in the file."""
    import tools.dispatch_harness.config as cfg_mod

    def _boom(*_a, **_k):
        raise RuntimeError("config exploded")

    monkeypatch.setattr(cfg_mod, "load_harness_config", _boom)
    assert prose.prose_band_enabled() is False

    class _HostileConfig:
        """A config object whose flag property raises when it is read."""

        @property
        def green_quality_prose_band_enabled(self) -> bool:
            raise RuntimeError("resolved value exploded")

    assert prose.prose_band_enabled(_HostileConfig()) is False, (
        "a cfg whose property raises propagated out of a function documented fail-closed"
    )


def test_the_shipped_config_leaves_the_prose_band_dormant():
    """THE POSTURE LOCK, read off the artifact the LA reads at a ceremony rather than off a
    docstring. This is a quality change to what a non-technical operator is told about his
    delivery, so it merges dormant and the flip is his."""
    import tomllib

    config = Path(__file__).resolve().parents[2] / "services/assistant_orchestrator/config/default.toml"
    data = tomllib.loads(config.read_text(encoding="utf-8"))
    assert data["fleet_dispatch"]["green_quality_prose_band"] is False, (
        "the placeholder-prose band contribution shipped LIVE — it is a change to what the "
        "operator reads and it waits for an LA-present ceremony"
    )


# ---------------------------------------------------------------------------
# The advisory contract still holds with the new stamp
# ---------------------------------------------------------------------------


def test_the_prose_stamp_stays_inside_the_reserved_keys(tmp_path):
    """The audit is the SOLE writer of ``green_quality_*`` and writes nothing else. Adding a
    prose key must not widen that surface — asserted rather than documented, because an
    evidence key nobody constrains is how an advisory instrument grows a verdict."""
    sc, _ = _green_run(tmp_path, placeholder=True)
    written = {k for k in sc.evidence if k.startswith("green_quality")}
    assert written <= RESERVED_EVIDENCE_KEYS
    assert EV_PROSE in written
    assert sc.evidence["oracle_status"] == "passed"  # pre-existing evidence untouched


def test_the_scorecard_stays_schema_valid_after_the_prose_stamp(tmp_path):
    """Evidence values are single-line and capped; a multi-line finding detail would make the
    durable scorecard artifact unwritable."""
    sc, _ = _green_run(tmp_path, placeholder=True)
    assert validate(sc) == []


def test_the_prose_stamp_is_unconditional(tmp_path):
    """A key written only when a check FIRED makes an absent key mean two opposite things.
    Every GREEN carries this stamp — including a library, whose stamp says so."""
    out_dir = tmp_path / "battery" / "20260806-000002"
    lib = out_dir / "repos-archived" / "battery-b2-tokenizer"
    lib.mkdir(parents=True)
    (lib / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    sc = Scorecard(job_id="B2", verdict="GREEN", attribution="", repo="battery-b2-tokenizer",
                   run_id="R2", evidence={})
    block = audit_greens([sc], runs_dir=tmp_path / "runs", out_dir=out_dir,
                         job_surfaces={"B2": "python-lib"})
    assert EV_PROSE in sc.evidence
    assert "not-applicable" in sc.evidence[EV_PROSE]
    assert block["prose_not_applicable"] == 1
    assert block["prose_clean"] == 0

    # UNAFFECTED, stated precisely. This library bands B on the pre-existing no-entry-point
    # lint, which is nothing to do with this scan — so the assertion is that NO band reason
    # came from the prose check, not that the band is A. Asserting the letter would have
    # coupled this control's regression lock to an unrelated lint's behaviour, and it would
    # have failed for a reason that says nothing about #1281.
    sidecar = json.loads((tmp_path / "runs" / "R2" / "green-quality.json").read_text(encoding="utf-8"))
    reasons = sidecar["band_reasons"]["c"] + sidecar["band_reasons"]["b"]
    assert not any("placeholder prose" in r for r in reasons), (
        f"a Python library was penalised by a check about web copy: {reasons}"
    )
