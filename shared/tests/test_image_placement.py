"""Regression locks for :mod:`shared.fleet.image_placement` — DoD capability 18.

The load-bearing tests here are not the ones proving a repeated picture is found. They are:

* :func:`test_the_operators_own_shop_is_graded_as_he_saw_it` and
  :func:`test_the_next_nights_shop_still_repeats_one_picture` — drive the two ACTUAL
  delivered sites, not fixtures. The first is the six-products/two-pictures shop the Lead
  Architect reviewed on 2026-08-08; the second is the next night's build, which improved to
  one image per CATEGORY and therefore still shows one photograph under three products.
  Mocks lie; these bytes are the ones that shipped.
* :func:`test_a_site_with_no_media_is_ABSENT_not_clean` — the honesty lock. A grading pass
  that examined nothing must never report a clean result.
* :func:`test_toggle_proof_*` — security_by_design principle 12: every control ships with
  proof it FAILS when disengaged, so "graded clean" can be told apart from "the probe never
  reached the code".
* :func:`test_a_shared_logo_and_hero_are_NOT_flagged` — the false-positive lock. Precision
  is the whole design: a false positive nags a coder into "fixing" correct markup.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.fleet import image_placement

#: The shop the operator reviewed: SIX products, TWO pictures. Skipped rather than failed
#: when absent — the battery archives are state, not repository content, so a clean checkout
#: legitimately lacks them — but when present they are the strongest evidence available.
_ARCHIVED_SITE = Path(
    "C:/Users/mrbla/agentic-setup/state/battery/night-20260807-230003/"
    "repos-archived/battery-b9-pottery-site"
)

#: The next night's build of the same shop: SIX products, THREE pictures (one per category).
#:
#: THE ARCHIVED SNAPSHOT, not `~/projects/battery-b9-pottery-site`. These tests asserted exact
#: figures against the live projects tree until 2026-08-09, when the overnight battery rebuilt
#: it and three of them went red on main — the tree they were measuring is a working area the
#: fleet rewrites every night, so the evidence under them expired while they slept.
#:
#: That is DoD capability 16 (#1318) committed by the very tests written to enforce it: a
#: recorded result that cannot be re-derived. A dated `repos-archived/` snapshot CAN be, which
#: is the whole reason the archive exists. Assert exact numbers only against immutable
#: artifacts; a live working directory is evidence-by-reference, and the reference moves.
_LIVE_SITE = Path(
    "C:/Users/mrbla/agentic-setup/state/battery/night-20260808-230002/"
    "repos-archived/battery-b9-pottery-site"
)


def _site(tmp_path: Path, files: dict[str, str]) -> Path:
    """Materialise a site tree from a {relative-path: content} map."""
    root = tmp_path / "site"
    for rel, content in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root


def _pieces(*records: dict) -> str:
    return json.dumps(list(records))


def _rules(report: dict) -> list[str]:
    return [f["rule"] for f in report["findings"]]


# ---------------------------------------------------------------------------
# The real artifacts
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _ARCHIVED_SITE.is_dir(), reason="battery archive not present in this checkout")
def test_the_operators_own_shop_is_graded_as_he_saw_it() -> None:
    """Six products, two pictures, and a banner photograph sold as a bowl.

    The operator said two things about this delivery: "the same images were used over and
    over" and "descriptions of the products don't match the image". Both must appear. The
    second is the harder half — ``hero.png`` names no subject, so no filename comparison can
    call it a mug; it is caught because the asset is page FURNITURE by name and a product is
    wearing it.
    """
    report = image_placement.grade_site(_ARCHIVED_SITE)

    assert report["checked"] is True
    assert report["hard"] is True, "one picture under three products must be a HARD finding"
    assert report["counts"]["items"] == 6
    assert report["counts"]["distinct_item_images"] == 2, "the shop shipped exactly two pictures"
    assert report["counts"]["max_items_per_image"] == 3

    repeats = [f for f in report["findings"] if f["rule"] == "repeated-item-image"]
    assert sorted(f["reference"] for f in repeats) == ["assets/hero.png", "assets/mug.png"]

    # His second complaint: the three bowls all render the potter-at-the-wheel banner.
    decorative = [f for f in report["findings"] if f["rule"] == "decorative-as-item"]
    assert {f["item"] for f in decorative} == {"Bowls Collection", "Large Bowl", "Decorative Bowl"}
    assert all(f["reference"] == "assets/hero.png" for f in decorative)
    assert all(f["severity"] == "low" for f in decorative), "a name-based inference is never HARD"

    summary = image_placement.format_operator_summary(report)
    assert "6 products share only 2 different pictures" in summary
    assert summary.isascii(), "the operator reads this on a Windows console"


@pytest.mark.skipif(not _ARCHIVED_SITE.is_dir(), reason="battery archive not present in this checkout")
def test_the_archived_shop_produces_no_false_positives() -> None:
    """Every finding names ``hero.png`` or ``mug.png`` — the only two pictures it shipped.

    ``favicon.ico`` is also in that tree and must not be reported as unused: nothing links a
    favicon and it is still doing its job.
    """
    report = image_placement.grade_site(_ARCHIVED_SITE)
    stray = [
        f for f in report["findings"]
        if "hero.png" not in f["reference"] and "mug.png" not in f["reference"]
    ]
    assert stray == [], f"false positives on a real delivery: {stray}"
    assert report["counts"]["unreferenced_assets"] == 0
    assert report["counts"]["items_with_missing_image"] == 0


@pytest.mark.skipif(not _LIVE_SITE.is_dir(), reason="the 20260808-230002 battery archive is not present in this checkout")
def test_the_next_nights_shop_still_repeats_one_picture() -> None:
    """One image per CATEGORY is still three products wearing one photograph.

    This is the delivery that looked like an improvement — three pictures instead of two —
    and is exactly why the threshold counts items per ASSET rather than trusting a ratio to
    have got better.
    """
    report = image_placement.grade_site(_LIVE_SITE)

    assert report["checked"] is True
    assert report["counts"]["items"] == 6
    assert report["counts"]["distinct_item_images"] == 3

    repeats = [f for f in report["findings"] if f["rule"] == "repeated-item-image"]
    assert len(repeats) == 1 and repeats[0]["reference"] == "assets/mug.png"
    assert "Classic Mug" in repeats[0]["message"]
    assert "Travel Mug" in repeats[0]["message"]
    assert "Tea Cup Set" in repeats[0]["message"]

    # bowl.png is used TWICE and must NOT be flagged — two is a coin flip, three is a pattern.
    assert not [f for f in repeats if "bowl.png" in f["reference"]]
    # logo.png sits in the header of five pages and hero.png is the home banner. Neither is
    # an item image, so neither can reach the repeat counter. That guard is structural.
    assert not [f for f in report["findings"] if "logo.png" in f["reference"]]


@pytest.mark.skipif(not _LIVE_SITE.is_dir(), reason="the 20260808-230002 battery archive is not present in this checkout")
def test_the_generated_icons_nothing_ever_used_are_reported() -> None:
    """``icon-mug.png`` and ``icon-bowl.png`` cost ~76 s of GPU time each and are referenced nowhere.

    A finding about the PIPELINE rather than the page, which is why it is LOW: the delivered
    site is not broken by it, the generation budget is.
    """
    report = image_placement.grade_site(_LIVE_SITE)
    orphans = [f for f in report["findings"] if f["rule"] == "unreferenced-asset"]

    assert sorted(Path(f["reference"]).name for f in orphans) == ["icon-bowl.png", "icon-mug.png"]
    assert all(f["severity"] == "low" for f in orphans)
    assert report["counts"]["unreferenced_assets"] == 2
    # contact.png is referenced exactly once, and favicon.ico not at all — neither is an orphan.
    assert not [f for f in orphans if "contact.png" in f["reference"] or "favicon" in f["reference"]]


# ---------------------------------------------------------------------------
# The honesty locks (capability 7 — 'did not run' is not 'ran and found nothing')
# ---------------------------------------------------------------------------


def test_a_site_with_no_media_is_ABSENT_not_clean(tmp_path: Path) -> None:
    """A site with no pictures and no product list reports ``checked: False`` and NO counts.

    This is the #1342 defect stated in one sentence: a zero that came from an unrun check
    must not be able to wear a clean check's clothes. An instrument written to catch that
    class must not commit it.
    """
    root = _site(tmp_path, {"public/index.html": "<p>a site with words and nothing else</p>"})
    report = image_placement.grade_site(root)

    assert report["checked"] is False
    assert report["nothing_to_grade"] is True
    assert report["counts"] == {}, "no counts may be published when nothing was graded"
    assert "NOTHING was graded" in " ".join(report["not_measured"])
    assert "nothing" in image_placement.format_operator_summary(report)


def test_no_media_and_correctly_placed_media_produce_DIFFERENT_reports(tmp_path: Path) -> None:
    """The operator's requirement, asserted directly: zero findings twice, two different reports."""
    empty = _site(tmp_path / "empty", {"public/index.html": "<p>words only</p>"})
    placed = _site(
        tmp_path / "placed",
        {
            "public/index.html": "<p>shop</p>",
            "public/assets/mug.png": "x",
            "public/assets/bowl.png": "x",
            "data/items.json": _pieces(
                {"name": "Mug", "category": "mugs", "image": "assets/mug.png"},
                {"name": "Bowl", "category": "bowls", "image": "assets/bowl.png"},
            ),
        },
    )

    empty_report = image_placement.grade_site(empty)
    placed_report = image_placement.grade_site(placed)

    assert empty_report["findings"] == [] and placed_report["findings"] == []
    assert empty_report["checked"] is False and placed_report["checked"] is True
    assert empty_report["counts"] == {} and placed_report["counts"]["items"] == 2


def test_a_dimension_that_could_not_run_says_so_and_publishes_no_counts(tmp_path: Path) -> None:
    """Pictures but no product list: asset usage runs, item placement is NAMED as unrun."""
    root = _site(tmp_path, {"public/index.html": '<img src="assets/a.png">', "public/assets/a.png": "x"})
    report = image_placement.grade_site(root)

    assert report["checked"] is True, "one dimension ran, so the pass is not absent"
    assert report["checks"]["item_placement"]["checked"] is False
    assert report["checks"]["asset_usage"]["checked"] is True
    assert "items" not in report["counts"], "an unrun dimension publishes no counts"
    assert report["counts"]["image_assets"] == 1
    assert "item placement was NOT graded" in " ".join(report["not_measured"])
    assert "NOT CHECKED" in image_placement.format_operator_summary(report)


def test_the_inference_limit_is_stated_in_every_report(tmp_path: Path) -> None:
    """A limit nobody names reads as a clean result. This one is named on every graded pass."""
    root = _site(
        tmp_path,
        {
            "public/index.html": "<p>x</p>",
            "public/assets/mug.png": "x",
            "data/items.json": _pieces(
                {"name": "Mug", "image": "assets/mug.png"},
                {"name": "Cup", "image": "assets/mug.png"},
            ),
        },
    )
    report = image_placement.grade_site(root)
    assert "no image is ever opened" in " ".join(report["not_measured"])


def test_a_missing_site_directory_is_reported_not_crashed(tmp_path: Path) -> None:
    report = image_placement.grade_site(tmp_path / "does-not-exist")
    assert report["checked"] is False
    assert report["nothing_to_grade"] is False, "a missing tree is a FAILURE to grade, not an empty one"
    assert report["hard"] is False
    assert "does not exist" in report["reason"]
    assert "did not run" in image_placement.format_operator_summary(report)


def test_an_unparseable_data_source_degrades_instead_of_raising(tmp_path: Path) -> None:
    root = _site(tmp_path, {"public/index.html": "<p>x</p>", "data/items.json": "{not json,,,"})
    report = image_placement.grade_site(root)  # must not raise
    assert "unreadable" in _rules(report)
    assert report["hard"] is False


# ---------------------------------------------------------------------------
# The false-positive locks — precision is the design
# ---------------------------------------------------------------------------


def test_a_shared_logo_and_hero_are_NOT_flagged(tmp_path: Path) -> None:
    """One logo across every page and one hero banner is CORRECT. Zero findings.

    The guard is structural rather than a tuned threshold: the repeat rule counts only assets
    an ITEM declares, and page furniture is declared by no item. A threshold tuned to dodge
    logos would rot the first time somebody sold six of something.
    """
    pages = {
        f"public/{name}.html": (
            '<img src="assets/logo.png"><img src="assets/hero.png"><p>page</p>'
        )
        for name in ("index", "about", "contact", "shop", "blog")
    }
    root = _site(
        tmp_path,
        {
            **pages,
            "public/assets/logo.png": "x",
            "public/assets/hero.png": "x",
            "public/assets/mug.png": "x",
            "public/assets/bowl.png": "x",
            "public/assets/vase.png": "x",
            "public/assets/plate.png": "x",
            "data/items.json": _pieces(
                {"name": "Classic Mug", "category": "mugs", "image": "assets/mug.png"},
                {"name": "Deep Bowl", "category": "bowls", "image": "assets/bowl.png"},
                {"name": "Tall Vase", "category": "vases", "image": "assets/vase.png"},
                {"name": "Side Plate", "category": "plates", "image": "assets/plate.png"},
            ),
        },
    )
    report = image_placement.grade_site(root)

    assert report["checked"] is True
    assert report["findings"] == [], f"a correct site must be silent: {report['findings']}"
    assert report["hard"] is False
    assert report["counts"]["distinct_item_images"] == 4


def test_two_items_sharing_a_picture_is_below_the_threshold(tmp_path: Path) -> None:
    """Two is a coin flip — variants, a boxed pair, a series shot. The rule stays quiet."""
    root = _site(
        tmp_path,
        {
            "public/index.html": '<img src="assets/mug.png"><img src="assets/bowl.png">',
            "public/assets/mug.png": "x",
            "public/assets/bowl.png": "x",
            "data/items.json": _pieces(
                {"name": "Mug", "category": "mugs", "image": "assets/mug.png"},
                {"name": "Mug Gift Pair", "category": "mugs", "image": "assets/mug.png"},
                {"name": "Bowl", "category": "bowls", "image": "assets/bowl.png"},
                {"name": "Bowl Gift Pair", "category": "bowls", "image": "assets/bowl.png"},
            ),
        },
    )
    report = image_placement.grade_site(root)
    assert "repeated-item-image" not in _rules(report)
    assert report["hard"] is False


def test_a_catalogue_shipped_twice_is_not_a_repeat(tmp_path: Path) -> None:
    """Two copies of the same product list is one shop, not six products on three pictures.

    These scaffolds routinely emit a data file AND a copy under the served root. Grading the
    merged list would double every item and report a repeat on a site where each product has
    its own picture, which is why every rule counts WITHIN a collection.
    """
    catalogue = _pieces(
        {"name": "Classic Mug", "category": "mugs", "image": "assets/mug.png"},
        {"name": "Deep Bowl", "category": "bowls", "image": "assets/bowl.png"},
        {"name": "Tall Vase", "category": "vases", "image": "assets/vase.png"},
    )
    root = _site(
        tmp_path,
        {
            "public/index.html": "<p>x</p>",
            "public/assets/mug.png": "x",
            "public/assets/bowl.png": "x",
            "public/assets/vase.png": "x",
            "data/pieces.json": catalogue,
            "public/data/pieces.json": catalogue,
        },
    )
    report = image_placement.grade_site(root)

    assert len(report["data_sources"]) == 2, "both copies must be found, and graded separately"
    assert report["findings"] == [], f"a duplicated catalogue is not a defect: {report['findings']}"
    assert report["counts"]["max_items_per_image"] == 1


def test_a_short_decorative_name_is_still_recognised_as_decoration(tmp_path: Path) -> None:
    """``bg.png`` is the most conventional decorative name there is, and it is two letters.

    The general token filter drops words under three characters, which would have made this
    case silently invisible. The decorative test tokenises raw for exactly that reason.
    """
    root = _site(
        tmp_path,
        {
            "public/index.html": "<p>x</p>",
            "public/assets/bg.png": "x",
            "public/assets/mug.png": "x",
            "data/items.json": _pieces(
                {"name": "Deep Bowl", "category": "bowls", "image": "assets/bg.png"},
                {"name": "Classic Mug", "category": "mugs", "image": "assets/mug.png"},
            ),
        },
    )
    report = image_placement.grade_site(root)
    assert [f["item"] for f in report["findings"] if f["rule"] == "decorative-as-item"] == ["Deep Bowl"]


def test_a_subject_named_asset_is_not_decoration_because_it_also_says_hero(tmp_path: Path) -> None:
    """``mug-hero.png`` names a subject. A subject outranks a layout word."""
    root = _site(
        tmp_path,
        {
            "public/index.html": "<p>x</p>",
            "public/assets/mug-hero.png": "x",
            "public/assets/bowl.png": "x",
            "data/items.json": _pieces(
                {"name": "Classic Mug", "category": "mugs", "image": "assets/mug-hero.png"},
                {"name": "Deep Bowl", "category": "bowls", "image": "assets/bowl.png"},
            ),
        },
    )
    assert image_placement.grade_site(root)["findings"] == []


def test_a_package_json_is_never_mistaken_for_a_catalogue(tmp_path: Path) -> None:
    """Configuration files carry ``src`` fields and must not be graded as content."""
    root = _site(
        tmp_path,
        {
            "public/index.html": "<p>x</p>",
            "package.json": json.dumps({"name": "site", "files": [{"src": "a.png"}, {"src": "a.png"}]}),
        },
    )
    report = image_placement.grade_site(root)
    assert report["checks"]["item_placement"]["checked"] is False
    assert report["data_sources"] == []


def test_a_singular_plural_category_still_matches_its_asset(tmp_path: Path) -> None:
    """``category: "vases"`` against ``vase.png`` is a match, not a mismatch."""
    root = _site(
        tmp_path,
        {
            "public/index.html": "<p>x</p>",
            "public/assets/vase.png": "x",
            "public/assets/mug.png": "x",
            "data/items.json": _pieces(
                {"name": "Tall Vase", "category": "vases", "image": "assets/vase.png"},
                {"name": "Classic Mug", "category": "mugs", "image": "assets/mug.png"},
            ),
        },
    )
    assert image_placement.grade_site(root)["findings"] == []


# ---------------------------------------------------------------------------
# The rules
# ---------------------------------------------------------------------------


def test_three_items_on_one_picture_is_the_threshold(tmp_path: Path) -> None:
    root = _site(
        tmp_path,
        {
            "public/index.html": "<p>x</p>",
            "public/assets/mug.png": "x",
            "data/items.json": _pieces(
                {"name": "Classic Mug", "category": "mugs", "image": "assets/mug.png"},
                {"name": "Travel Mug", "category": "mugs", "image": "assets/mug.png"},
                {"name": "Tea Cup Set", "category": "mugs", "image": "assets/mug.png"},
            ),
        },
    )
    report = image_placement.grade_site(root)

    assert _rules(report).count("repeated-item-image") == 1
    assert report["hard"] is True
    assert report["counts"]["max_items_per_image"] == 3


def test_a_bowl_rendering_a_mug_is_a_mismatch_when_a_bowl_picture_exists(tmp_path: Path) -> None:
    """The clause that makes this safe: the RIGHT picture was on hand and the wrong one was used."""
    root = _site(
        tmp_path,
        {
            "public/index.html": "<p>x</p>",
            "public/assets/mug.png": "x",
            "public/assets/bowl.png": "x",
            "data/items.json": _pieces(
                {"name": "Deep Bowl", "category": "bowls", "image": "assets/mug.png"},
                {"name": "Classic Mug", "category": "mugs", "image": "assets/mug.png"},
                {"name": "Wide Bowl", "category": "bowls", "image": "assets/bowl.png"},
            ),
        },
    )
    report = image_placement.grade_site(root)
    mismatches = [f for f in report["findings"] if f["rule"] == "subject-mismatch"]

    assert [f["item"] for f in mismatches] == ["Deep Bowl"]
    assert mismatches[0]["severity"] == "low", "a name-based inference must never force a FIX"
    assert "never opens the image" in mismatches[0]["message"]


def test_no_mismatch_is_claimed_when_no_better_picture_exists(tmp_path: Path) -> None:
    """A bowl on a mug picture in a tree with no bowl picture is a PLANNING gap, not a placement one.

    Without this clause the rule would fire on every site whose art has not been generated
    yet, which is the false-positive class that would make the whole grader untrustworthy.
    """
    root = _site(
        tmp_path,
        {
            "public/index.html": "<p>x</p>",
            "public/assets/mug.png": "x",
            "data/items.json": _pieces(
                {"name": "Deep Bowl", "category": "bowls", "image": "assets/mug.png"},
                {"name": "Classic Mug", "category": "mugs", "image": "assets/mug.png"},
            ),
        },
    )
    assert "subject-mismatch" not in _rules(image_placement.grade_site(root))


def test_an_item_pointing_at_a_missing_picture_is_HARD(tmp_path: Path) -> None:
    """The gap :mod:`link_lint` structurally cannot close: ``src="${piece.image}"``.

    That markup is undecidable to a link checker — the value only exists at runtime — and
    fully decidable here, because the value is written down in the data source.
    """
    root = _site(
        tmp_path,
        {
            "public/index.html": '<img src="${piece.image}">',
            "public/assets/mug.png": "x",
            "public/assets/bowl.png": "x",
            "data/items.json": _pieces(
                {"name": "Mug", "image": "assets/mug.png"},
                {"name": "Bowl", "image": "assets/bowl.png"},
                {"name": "Vase", "image": "assets/vase.png"},
            ),
        },
    )
    report = image_placement.grade_site(root)
    missing = [f for f in report["findings"] if f["rule"] == "item-image-missing"]

    assert [f["item"] for f in missing] == ["Vase"]
    assert report["hard"] is True
    assert report["counts"]["items_with_missing_image"] == 1


def test_a_data_source_outside_the_served_root_still_resolves_its_images(tmp_path: Path) -> None:
    """``data/pieces.json`` sits ABOVE ``public/``, and its paths are relative to the mount.

    Getting this wrong would report every image in the operator's own shop as missing — a
    grader that is confidently, uniformly wrong.
    """
    root = _site(
        tmp_path,
        {
            "public/index.html": "<p>x</p>",
            "public/assets/mug.png": "x",
            "public/assets/bowl.png": "x",
            "data/pieces.json": _pieces(
                {"name": "Mug", "image": "assets/mug.png"},
                {"name": "Bowl", "image": "assets/bowl.png"},
            ),
        },
    )
    report = image_placement.grade_site(root)
    assert report["data_sources"] == ["data/pieces.json"]
    assert report["counts"]["items_with_missing_image"] == 0


def test_diffuse_duplication_is_LOW_and_never_doubles_a_repeat_finding(tmp_path: Path) -> None:
    """Four items, two pictures used twice each: nothing hits the threshold, the gallery is halved."""
    root = _site(
        tmp_path,
        {
            "public/index.html": "<p>x</p>",
            "public/assets/a.png": "x",
            "public/assets/b.png": "x",
            "data/items.json": _pieces(
                {"name": "One", "image": "assets/a.png"},
                {"name": "Two", "image": "assets/a.png"},
                {"name": "Three", "image": "assets/b.png"},
                {"name": "Four", "image": "assets/b.png"},
            ),
        },
    )
    report = image_placement.grade_site(root)

    assert _rules(report) == ["item-image-diversity"]
    assert report["hard"] is False


def test_diversity_is_suppressed_when_a_repeat_already_says_it(tmp_path: Path) -> None:
    """One defect, one finding. The archived shop must not be reported twice for one problem."""
    root = _site(
        tmp_path,
        {
            "public/index.html": "<p>x</p>",
            "public/assets/a.png": "x",
            "data/items.json": _pieces(
                {"name": "One", "image": "assets/a.png"},
                {"name": "Two", "image": "assets/a.png"},
                {"name": "Three", "image": "assets/a.png"},
                {"name": "Four", "image": "assets/a.png"},
            ),
        },
    )
    assert _rules(image_placement.grade_site(root)) == ["repeated-item-image"]


def test_an_item_with_no_picture_at_all_is_reported(tmp_path: Path) -> None:
    root = _site(
        tmp_path,
        {
            "public/index.html": "<p>x</p>",
            "public/assets/a.png": "x",
            "public/assets/b.png": "x",
            "data/items.json": _pieces(
                {"name": "One", "image": "assets/a.png"},
                {"name": "Two", "image": "assets/b.png"},
                {"name": "Three"},
            ),
        },
    )
    report = image_placement.grade_site(root)
    assert [f["item"] for f in report["findings"] if f["rule"] == "item-without-image"] == ["Three"]
    assert report["counts"]["items_without_image"] == 1


def test_a_collection_nested_under_a_key_is_found(tmp_path: Path) -> None:
    """A catalogue is as often ``{"pieces": [...]}`` as a bare array."""
    root = _site(
        tmp_path,
        {
            "public/index.html": "<p>x</p>",
            "public/assets/a.png": "x",
            "data/catalog.json": json.dumps(
                {"pieces": [
                    {"name": "One", "image": "assets/a.png"},
                    {"name": "Two", "image": "assets/a.png"},
                    {"name": "Three", "image": "assets/a.png"},
                ]}
            ),
        },
    )
    report = image_placement.grade_site(root)
    assert report["collections"][0]["path"] == "pieces"
    assert "repeated-item-image" in _rules(report)


def test_a_favicon_is_never_reported_as_unused(tmp_path: Path) -> None:
    """Nothing links a favicon and it is still doing its job — and the report SAYS it was exempted."""
    root = _site(tmp_path, {"public/index.html": "<p>x</p>", "public/assets/favicon.ico": "x"})
    report = image_placement.grade_site(root)

    assert "unreferenced-asset" not in _rules(report)
    assert report["counts"]["exempt_assets"] == 1
    assert report["counts"]["referenced_assets"] == 0, "an exempted asset was not verified"
    assert "EXEMPTED" in " ".join(report["not_measured"])


def test_an_asset_referenced_only_from_a_stylesheet_is_used(tmp_path: Path) -> None:
    """Reference hunting is by basename across every text file, so ``url(...)`` counts."""
    root = _site(
        tmp_path,
        {
            "public/index.html": "<p>x</p>",
            "public/styles.css": "body { background: url('assets/bg.png'); }",
            "public/assets/bg.png": "x",
        },
    )
    assert "unreferenced-asset" not in _rules(image_placement.grade_site(root))


# ---------------------------------------------------------------------------
# Toggle proofs — security_by_design principle 12
# ---------------------------------------------------------------------------


def test_toggle_proof_the_probe_fails_when_the_repeat_rule_is_disengaged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Disengage the main detector and the operator's own shop must grade CLEAN.

    Without this, a green suite cannot be told apart from a probe that never reached the
    code. Driven against the REAL archived delivery rather than a fixture, so what is proved
    is that the finding comes from the rule and not from something incidental in a tree this
    test wrote itself.
    """
    if not _ARCHIVED_SITE.is_dir():
        pytest.skip("battery archive not present in this checkout")

    engaged = image_placement.grade_site(_ARCHIVED_SITE)
    assert engaged["hard"] is True, "engaged: three products on one picture must be caught"

    monkeypatch.setattr(image_placement, "_grade_repeats", lambda items: [])
    disengaged = image_placement.grade_site(_ARCHIVED_SITE)

    assert disengaged["hard"] is False, (
        "disengaging the repeat rule must make this defect invisible - if it is still found, "
        "the engaged result was not produced by the control under test"
    )
    assert "repeated-item-image" not in _rules(disengaged)


def test_toggle_proof_the_probe_fails_when_the_threshold_is_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Raising the threshold past the evidence makes the finding vanish.

    This proves the threshold is load-bearing rather than incidental: at 3 the operator's
    shop is reported, at 4 the identical delivery grades clean. It is the difference between
    a judgement call and a number that happens to sit in the file.
    """
    if not _LIVE_SITE.is_dir():
        pytest.skip("the projects tree is not present in this checkout")

    assert image_placement.grade_site(_LIVE_SITE)["hard"] is True

    monkeypatch.setattr(image_placement, "REPEAT_THRESHOLD", 4)
    assert image_placement.grade_site(_LIVE_SITE)["hard"] is False


def test_toggle_proof_the_probe_fails_when_the_reference_hunt_is_disengaged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stop reading text files and a genuinely-used asset becomes a false orphan.

    The mirror image of the other toggles: here disengaging the control must produce a
    finding that is WRONG, which is what proves the reference hunt is doing the work.
    """
    root = _site(
        tmp_path,
        {"public/index.html": '<img src="assets/a.png">', "public/assets/a.png": "x"},
    )
    assert "unreferenced-asset" not in _rules(image_placement.grade_site(root))

    monkeypatch.setattr(image_placement, "_TEXT_SUFFIXES", frozenset())
    assert "unreferenced-asset" in _rules(image_placement.grade_site(root))


# ---------------------------------------------------------------------------
# Reachability — the gate must be WIRED, not merely present
# ---------------------------------------------------------------------------
#
# This project's most-repeated failure class is "built but wired into nothing": a control
# that exists, has passing unit tests, and is called by no one. These drive the REAL entry
# point (`real_run_exec_smoke`) rather than `grade_site`, so a future refactor that unhooks
# the grader fails here instead of shipping a silent no-op.


def _smoke_config(tmp_path: Path):
    from shared.fleet.dispatch import FleetDispatchConfig

    return FleetDispatchConfig(
        scripts_dir=tmp_path / "scripts",
        queue_path=tmp_path / "state" / "q.json",
        runs_dir=tmp_path / "state" / "runs",
        projects_dir=tmp_path / "projects",
    )


def _shop(root: Path, images: dict[str, str], items: list[dict]) -> Path:
    """A minimal delivered web product: an index page, some assets, a data source."""
    files = {"index.html": "<p>shop</p>", "data/items.json": json.dumps(items)}
    files.update({f"assets/{name}": body for name, body in images.items()})
    for rel, content in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root


def _capture(_repo, _root):
    return {"ok": True, "errors": [], "evidence": "loaded clean"}


def _runner(_cmd, _t, _cwd=None, env=None):
    return (True, "", "")


def test_reachability_the_web_floor_carries_a_media_report(tmp_path: Path) -> None:
    """A web build's executability floor must return a media report on the happy path."""
    from shared.fleet import swap_ops as so

    repo = _shop(
        tmp_path / "site",
        {"mug.png": "x"},
        [
            {"name": "Classic Mug", "image": "assets/mug.png"},
            {"name": "Travel Mug", "image": "assets/mug.png"},
            {"name": "Tea Cup Set", "image": "assets/mug.png"},
        ],
    )
    res = so.real_run_exec_smoke(
        _smoke_config(tmp_path), "R1", str(repo), "tests/acceptance.job.test.mjs",
        surface="web", web_console_capture=_capture, run=_runner)

    assert "image_placement" in res, "the web floor must carry the media report — the grader is unwired"
    assert res["image_placement"]["counts"]["max_items_per_image"] == 3
    assert "media placement finding" in res["evidence"], "a finding must reach the evidence line"


def test_reachability_a_media_finding_does_NOT_change_the_verdict(tmp_path: Path) -> None:
    """Advisory by design: the operator asked for the delivery to be REPORTED, not failed.

    A brand-new way for a build to RED is a capability change and therefore his ceremony.
    This lock is what stops a later edit from quietly promoting the grader into a gate.
    """
    from shared.fleet import swap_ops as so

    flagged = _shop(
        tmp_path / "a" / "site",
        {"mug.png": "x"},
        [
            {"name": "Classic Mug", "image": "assets/mug.png"},
            {"name": "Travel Mug", "image": "assets/mug.png"},
            {"name": "Tea Cup Set", "image": "assets/mug.png"},
        ],
    )
    clean = _shop(
        tmp_path / "b" / "site",
        {"mug.png": "x", "bowl.png": "x", "vase.png": "x"},
        [
            {"name": "Classic Mug", "category": "mugs", "image": "assets/mug.png"},
            {"name": "Deep Bowl", "category": "bowls", "image": "assets/bowl.png"},
            {"name": "Tall Vase", "category": "vases", "image": "assets/vase.png"},
        ],
    )

    res_flagged = so.real_run_exec_smoke(
        _smoke_config(tmp_path / "a"), "R1", str(flagged), "tests/acceptance.job.test.mjs",
        surface="web", web_console_capture=_capture, run=_runner)
    res_clean = so.real_run_exec_smoke(
        _smoke_config(tmp_path / "b"), "R1", str(clean), "tests/acceptance.job.test.mjs",
        surface="web", web_console_capture=_capture, run=_runner)

    assert res_flagged["image_placement"]["hard"] is True
    assert res_clean["image_placement"]["findings"] == []
    assert res_flagged["ok"] is True and res_clean["ok"] is True
    assert res_flagged["ok"] == res_clean["ok"], "the media grader must not move the verdict"
    assert res_flagged["fingerprint"] == res_clean["fingerprint"]


def test_reachability_the_sidecar_is_written_for_the_review_loop(tmp_path: Path) -> None:
    """``image-placement.json`` must land beside ``link-lint.json``, where the review loop reads."""
    from shared.fleet import swap_ops as so

    config = _smoke_config(tmp_path)
    repo = _shop(
        tmp_path / "site",
        {"mug.png": "x"},
        [
            {"name": "One", "image": "assets/mug.png"},
            {"name": "Two", "image": "assets/mug.png"},
            {"name": "Three", "image": "assets/mug.png"},
        ],
    )
    so.real_run_exec_smoke(
        config, "R7", str(repo), "tests/acceptance.job.test.mjs", surface="web",
        web_console_capture=_capture, run=_runner)

    sidecar = config.runs_dir / "R7" / "image-placement.json"
    assert sidecar.is_file(), "the review loop has nothing to read without this sidecar"
    banked = json.loads(sidecar.read_text(encoding="utf-8"))
    assert banked["counts"]["max_items_per_image"] == 3
    assert (config.runs_dir / "R7" / "link-lint.json").is_file(), "the sibling sidecar must survive"


def test_reachability_a_site_with_no_media_says_so_in_the_evidence(tmp_path: Path) -> None:
    """"No media to grade" is its own evidence state — never silence, never a scary NOT graded."""
    from shared.fleet import swap_ops as so

    repo = tmp_path / "site"
    repo.mkdir(parents=True)
    (repo / "index.html").write_text("<p>words only</p>", encoding="utf-8")

    res = so.real_run_exec_smoke(
        _smoke_config(tmp_path), "R1", str(repo), "tests/acceptance.job.test.mjs",
        surface="web", web_console_capture=_capture, run=_runner)

    assert res["image_placement"]["checked"] is False
    assert res["image_placement"]["nothing_to_grade"] is True
    assert "no media to grade" in res["evidence"]
    assert "NOT graded" not in res["evidence"]


def test_reachability_a_grader_raise_leaves_the_floor_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A presentation-layer failure must never take an executability floor down with it."""
    from shared.fleet import swap_ops as so

    def boom(_site_dir, _served_root=None):
        raise RuntimeError("grader exploded")

    monkeypatch.setattr(image_placement, "grade_site", boom)
    repo = tmp_path / "site"
    repo.mkdir(parents=True)
    (repo / "index.html").write_text("<p>fine</p>", encoding="utf-8")

    res = so.real_run_exec_smoke(
        _smoke_config(tmp_path), "R1", str(repo), "tests/acceptance.job.test.mjs",
        surface="web", web_console_capture=_capture, run=_runner)

    assert res["ok"] is True, "the floor must survive a grader raise"
    assert res["image_placement"]["checked"] is False
    assert res["image_placement"]["nothing_to_grade"] is False
    assert "media placement NOT graded" in res["evidence"]


# ---------------------------------------------------------------------------
# CLI contract
# ---------------------------------------------------------------------------


def test_cli_emits_one_json_object_and_exits_zero(tmp_path: Path) -> None:
    """Exit 0 even with findings: this is a SIGNAL, matching link_lint's contract."""
    import subprocess
    import sys

    root = _site(
        tmp_path,
        {
            "public/index.html": "<p>x</p>",
            "public/assets/mug.png": "x",
            "data/items.json": _pieces(
                {"name": "One", "image": "assets/mug.png"},
                {"name": "Two", "image": "assets/mug.png"},
                {"name": "Three", "image": "assets/mug.png"},
            ),
        },
    )
    proc = subprocess.run(
        [sys.executable, "-m", "shared.fleet.image_placement", "--site-dir", str(root)],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[2]),
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["hard"] is True
    assert payload["schema"] == "image-placement/v1"


def test_cli_rejects_a_missing_directory_with_exit_two(tmp_path: Path) -> None:
    import subprocess
    import sys

    proc = subprocess.run(
        [sys.executable, "-m", "shared.fleet.image_placement", "--site-dir", str(tmp_path / "nope")],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[2]),
    )
    assert proc.returncode == 2


# ---------------------------------------------------------------------------
# The operator's own material is not the pipeline's waste (2026-08-08 retraction)
# ---------------------------------------------------------------------------
#
# The first population sweep with this module counted 29 of the operator's OWN family
# photographs in `recipe-site` as generated-and-unused, which was five-sixths of the
# headline number reported to him. An instrument that tells a person their uploads were a
# machine's mistake is worse than no instrument — it is the false-positive class this
# module's own docstring warns about, committed by this module.

_INTAKE_README = (
    "Put photos, documents, and other material for the build in here; "
    "screenshots to emulate go in the reference folder.\n"
)
#: The text seeded from 2026-08-30. BOTH must be recognised forever: projects created
#: before that date still carry the one above, and a marker that stopped matching it
#: would re-commit the false positive this section exists to prevent.
_INTAKE_README_2026_08_30 = (
    "Put photos, videos, documents and other material for the build in here. "
    "The plan lists what it finds, and the build is graded on using it. "
    "(The reference folder is for screenshots to copy the look of - not used yet.)\n"
)


def test_operator_intake_photos_are_never_graded_as_waste(tmp_path: Path) -> None:
    """A folder the scaffold told him to fill is his, and no rule may touch it."""
    root = _site(
        tmp_path,
        {
            "assets/README.txt": _INTAKE_README,
            "assets/nan-recipe-1.jpg": "x",
            "assets/nan-recipe-2.jpg": "x",
            "public/index.html": "<p>not built yet</p>",
        },
    )
    report = image_placement.grade_site(root)

    assert report["counts"].get("unreferenced_assets", 0) == 0, (
        "the operator's uploaded photographs must never be reported as pipeline waste"
    )


def test_the_intake_marker_recognises_every_scaffold_wording(tmp_path: Path) -> None:
    """The scaffold's README text has changed once and will change again. The marker is
    what protects the operator's own uploads, so it must recognise EVERY wording ever
    seeded -- a project created in July is still on disk carrying July's text."""
    for label, readme in (("pre_20260830", _INTAKE_README),
                          ("from_20260830", _INTAKE_README_2026_08_30)):
        root = _site(
            tmp_path / label,
            {
                "assets/README.txt": readme,
                "assets/his-own-photo.jpg": "x",
                "public/index.html": "<p>not built yet</p>",
            },
        )
        report = image_placement.grade_site(root)
        assert report["counts"].get("unreferenced_assets", 0) == 0, (
            f"the {label} scaffold wording must still mark the folder as the "
            "operator's own"
        )


def test_the_intake_exclusion_is_NAMED_not_silent(tmp_path: Path) -> None:
    """Excluded is not the same as absent — he should see his material was recognised."""
    root = _site(
        tmp_path,
        {
            "assets/README.txt": _INTAKE_README,
            "assets/photo.jpg": "x",
            "public/index.html": '<img src="hero.png">',
            "public/hero.png": "x",
        },
    )
    report = image_placement.grade_site(root)

    if report.get("checked"):
        assert report["counts"].get("operator_intake_images", 0) == 1
        assert any("OPERATOR fills" in n for n in report["not_measured"])


def test_the_marker_is_the_readme_not_the_directory_name(tmp_path: Path) -> None:
    """Generated media commonly lives in `assets/` too — the NAME must not exempt it.

    Excluding by directory name would have blinded the rule to the real case it was built
    for: `battery-b9-pottery-site` keeps its generated pictures in `public/assets/`.
    """
    root = _site(
        tmp_path,
        {
            "public/index.html": "<p>no pictures referenced</p>",
            "public/assets/generated-1.png": "x",
            "public/assets/generated-2.png": "x",
        },
    )
    report = image_placement.grade_site(root)

    assert report["counts"]["unreferenced_assets"] == 2, (
        "an `assets/` directory with NO intake marker is ordinary generated media"
    )


def test_test_output_screenshots_are_not_site_media(tmp_path: Path) -> None:
    """`Hello-World` reported six 'wasted' images that were testing screenshots."""
    root = _site(
        tmp_path,
        {
            "index.html": "<p>demo</p>",
            "testing_output/Screenshot 2026-06-11 093845.png": "x",
            "testing_output/Screenshot 2026-06-11 094538.png": "x",
        },
    )
    report = image_placement.grade_site(root)
    assert report["counts"].get("unreferenced_assets", 0) == 0


def test_toggle_proof_the_intake_guard_fails_when_disengaged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Disengage the marker read and the operator's photos are called waste again."""
    root = _site(
        tmp_path,
        {
            "assets/README.txt": _INTAKE_README,
            "assets/his-photo.jpg": "x",
            "index.html": "<p>x</p>",
        },
    )
    assert image_placement.grade_site(root)["counts"].get("unreferenced_assets", 0) == 0

    monkeypatch.setattr(image_placement, "_is_operator_intake_dir", lambda d: False)
    disengaged = image_placement.grade_site(root)
    assert disengaged["counts"]["unreferenced_assets"] == 1, (
        "disengaging the intake guard must restore the defect — otherwise the engaged "
        "result was not produced by the control under test"
    )


# ---------------------------------------------------------------------------
# #1391 — the dropped catalogue. The genuine #1231 shape: doing LESS work turns
# a guaranteed hard-fail into an invisible non-event, reached by a malformed
# JSON read rather than a budget clock. No adversary required.
# ---------------------------------------------------------------------------


#: Ten items each DECLARING a picture that does not exist in the delivery. That is the HIGH
#: `item-image-missing` rule and therefore a hard fail. Note the distinction, because the
#: ticket's phrase "ten items all missing images" is ambiguous and the first draft of this
#: fixture got it wrong: an item with `"image": ""` declares nothing and grades under the
#: separate, lower `item-without-image` rule, which does not set `hard`. The scenario that
#: makes #1391 dangerous is the HIGH one — a gallery of broken pictures.
_TEN_ITEMS_BROKEN_PICTURES = _pieces(*[
    {"id": i, "name": f"Piece {i}", "image": f"assets/piece{i}.png"} for i in range(1, 11)
])


def test_ten_broken_pictures_is_a_HARD_fail_when_the_catalogue_parses(tmp_path) -> None:
    """The control half of the ticket's constructed scenario.

    Without this, the malformed-catalogue test below cannot distinguish "the parse failure
    hid the violations" from "this grader never flags missing pictures at all".
    """
    site = _site(tmp_path, {
        "data/pieces.json": _TEN_ITEMS_BROKEN_PICTURES,
        "public/index.html": "<h1>Shop</h1>",
        "public/assets/hero.png": "x",
    })
    report = image_placement.grade_site(site)

    assert report["checked"] is True
    assert report["hard"] is True, "ten items declaring absent pictures must be a HARD finding"
    assert "item-image-missing" in _rules(report)
    assert report["unparsed_data_source_count"] == 0


def test_the_same_ten_items_behind_a_syntax_error_are_not_silently_dropped(tmp_path) -> None:
    """The defect. One JSON syntax error and the ten violations vanished entirely: not
    `items`, not `items_without_image`, not `items_with_missing_image`, one LOW `unreadable`
    finding that cannot set `hard`, and NOT ONE WORD in `not_measured`.

    The disclosure asymmetry is what made this findable — `asset_usage` confessed its
    exclusions in `not_measured` and `item_placement` confessed nothing, so one dimension
    looked like it had nothing to confess.

    ADVISORY, per the ticket's own DONE item 2 and the #1345 precedent: `hard` is deliberately
    NOT raised here, because a new way for a build to fail is the operator's ceremony. What
    must hold is that the loss is IMPOSSIBLE TO MISS in the record.
    """
    site = _site(tmp_path, {
        "data/pieces.json": '[{"id": 1, "name": "Piece 1", "image": ""',  # truncated write
        "public/index.html": "<h1>Shop</h1>",
        "public/assets/hero.png": "x",
    })
    report = image_placement.grade_site(site)

    assert report["unparsed_data_source_count"] == 1, (
        "the unparseable catalogue was not counted anywhere"
    )
    assert "data/pieces.json" in report["unparsed_data_sources"]
    disclosure = " ".join(report["not_measured"]).lower()
    assert "could not be parsed" in disclosure, (
        f"not_measured said nothing about the dropped catalogue: {report['not_measured']}"
    )
    assert "lower bound" in disclosure, (
        "the disclosure must say the item counts are a floor, not a measurement"
    )


def test_an_unparseable_catalogue_is_never_reported_as_a_site_without_media(tmp_path) -> None:
    """The second-order bug. When the ONLY catalogue is unparseable, `item_ran` is False and
    the instrument reported `checked: False, reason: "no data file listing items with
    pictures was found"`.

    That was factually wrong — a file WAS found; it did not parse. It collapsed "did not
    look" into "looked and it broke", which is the STATUS_SENTINEL failure the instrument
    registry's own docstring warns about, and it reported the more alarming state as the
    more innocent one.
    """
    site = _site(tmp_path, {
        "data/pieces.json": '[{"id": 1, "image": ""',   # the only catalogue, truncated
        "public/index.html": "<h1>Shop</h1>",           # no image assets at all
    })
    report = image_placement.grade_site(site)

    reason = report.get("reason", "").lower()
    assert "could not be parsed" in reason, (
        f"a found-but-broken catalogue was reported as an absent one: {reason!r}"
    )
    assert report.get("nothing_to_grade") is not True, (
        "'nothing to grade' asserts the delivery had nothing in it; here it had something "
        "this instrument could not read, which is a different claim"
    )


def test_an_unparseable_catalogue_is_named_even_when_the_site_HAS_pictures(tmp_path) -> None:
    """#1391's SECOND reachable path, and the likelier one.

    The test above covers a site with no images at all, where `item_ran` and `asset_ran` are
    both False and the early branch fires. But a delivery that ships pictures alongside a
    catalogue that failed to parse skips that branch entirely and lands in the `else` that
    sets `checks["item_placement"]["reason"]` — which asserted, unconditionally, that no data
    file "was found". Same false statement as the bug this family was opened for, one branch
    over, on the ordinary case: a site with pictures.

    It reaches the operator through `format_operator_summary`, so a reader is told the coder
    never described its pictures when in fact the description was there and unreadable.
    """
    site = _site(tmp_path, {
        "data/pieces.json": '[{"id": 1, "image": ""',      # found, truncated, unparseable
        "public/index.html": '<img src="assets/mug.png">',  # ... and pictures DO exist
        "public/assets/mug.png": "x",
    })
    report = image_placement.grade_site(site)

    assert report["checks"]["asset_usage"]["checked"] is True, (
        "fixture is wrong if the asset half did not run — this test exists to cover the "
        "branch where it DID"
    )
    reason = report["checks"]["item_placement"]["reason"].lower()
    assert report["checks"]["item_placement"]["checked"] is False
    assert "could not be parsed" in reason, (
        f"a found-but-broken catalogue was reported as an absent one: {reason!r}"
    )
    assert "no data file listing items with pictures was found" not in reason, (
        "the stale absent-file text is still shipping on this path"
    )


def test_the_absent_catalogue_wording_SURVIVES_when_there_really_is_no_catalogue(tmp_path) -> None:
    """The toggle for the branch above. Fixing the unparseable case by deleting the
    absent-file wording would trade one wrong sentence for another: a site that genuinely
    ships no product data must still be told exactly that."""
    site = _site(tmp_path, {
        "public/index.html": '<img src="assets/mug.png">',
        "public/assets/mug.png": "x",
    })
    report = image_placement.grade_site(site)

    reason = report["checks"]["item_placement"]["reason"].lower()
    assert "no data file listing items with pictures was found" in reason
    assert "could not be parsed" not in reason


def test_the_disclosure_is_absent_when_every_catalogue_parses(tmp_path) -> None:
    """The toggle. A `not_measured` line that is always present carries no information."""
    site = _site(tmp_path, {
        "data/pieces.json": _pieces({"id": 1, "name": "Bowl", "image": "assets/bowl.png"}),
        "public/index.html": '<img src="assets/bowl.png">',
        "public/assets/bowl.png": "x",
    })
    report = image_placement.grade_site(site)

    assert report["unparsed_data_source_count"] == 0
    assert report["unparsed_data_sources"] == []
    disclosure = " ".join(report["not_measured"]).lower()
    assert "could not be parsed" not in disclosure, (
        "a clean run claimed a catalogue had failed to parse"
    )
