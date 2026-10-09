"""Golden-fixture tests for the corpus extraction rules (#1616).

**Why this file exists.** Every capture rule in the corpus pipeline was once
unreachable by any test: the extractor lived outside the repository, outside
pytest, outside the gate. Adversarial review found six defects by hand, at the
edge of a four-hour extraction run, that a dozen cached article pages would
have caught in a second. The rules were moved into ``tools/corpus/extract_rules``
specifically so this file could exist.

Each test below pins ONE defect that was real, against the REAL article that
exhibited it, frozen in ``fixtures/corpus/``. A regression here is not a style
opinion — it is a measured way the corpus lies about the encyclopedia.

The fixtures are gzipped article HTML from ``wikipedia_en_all_maxi_2026-08``,
with their source paths recorded in ``fixtures/corpus/MANIFEST.json``.
"""

from __future__ import annotations

import gzip
import json
import re
from pathlib import Path

import pytest

from tools.corpus import extract_rules as R

_FIX = Path(__file__).parent / "fixtures" / "corpus"


def _html(name: str) -> str:
    return gzip.decompress((_FIX / f"{name}.html.gz").read_bytes()).decode(
        "utf-8", "replace"
    )


def _all_passages(page: str) -> str:
    out = []
    for heading, body in R._sections(page):
        leaf = heading.rsplit("›", 1)[-1].strip().lower()
        if leaf in R._DEAD_SECTIONS:
            continue
        out.extend(R._passages(body))
    return "\n".join(out)


class TestFixturesArePresent:
    def test_manifest_matches_the_files_on_disk(self) -> None:
        manifest = json.loads((_FIX / "MANIFEST.json").read_text(encoding="utf-8"))
        for name in manifest:
            assert (_FIX / f"{name}.html.gz").is_file(), f"fixture missing: {name}"
        assert len(manifest) >= 8


class TestPagesDoNotVanish:
    """21.5% of article-namespace HTML entries used to emit NOTHING.

    Two populations: section-redirect stubs that report ``is_redirect == False``
    and fell between both branches, and list-shaped real articles whose entire
    body is ``<li>``, which the extractor dropped. An encyclopedia that silently
    omits a fifth of its pages is a corpus that lies about its coverage.
    """

    @pytest.mark.parametrize("name", ["disambiguation", "list_article"])
    def test_list_shaped_articles_emit_passages(self, name: str) -> None:
        text = _all_passages(_html(name))
        assert text.strip(), (
            f"{name} emitted NOTHING — list-shaped articles are being dropped "
            "again (#1616 finding 1)"
        )
        assert len(text) > 200

    def test_a_disambiguation_page_reads_as_one_passage_not_fragments(self) -> None:
        """Its value is the whole list together. A per-item length threshold
        was measured to rescue only half these articles, because a
        disambiguation entry is ~24 characters by construction."""
        passages = []
        for heading, body in R._sections(_html("disambiguation")):
            passages.extend(R._passages(body))
        assert passages
        assert max(len(p) for p in passages) > 120, (
            "entries were emitted one-per-item instead of merged into a passage"
        )


class TestSectionRedirectStubs:
    """14% of article HTML entries are section redirects carrying an anchor."""

    def test_a_stub_resolves_to_target_and_anchor(self) -> None:
        got = R._refresh_target(_html("section_stub"))
        assert got is not None, "section-redirect stub not recognised at all"
        target, anchor = got
        assert target == "Sorry"
        assert anchor == "Songs"

    def test_an_apostrophe_in_the_target_does_not_truncate_it(self) -> None:
        """The URL is single-quoted inside a double-quoted attribute, so a
        naive ``(['"])(.*?)\\1`` closes on the apostrophe INSIDE the title and
        banks a wrong target that looks perfectly valid downstream."""
        got = R._refresh_target(_html("stub_apostrophe"))
        assert got is not None
        target, _anchor = got
        assert target.startswith("Now_That's_What_I_Call"), (
            f"target truncated at an apostrophe: {target!r}"
        )
        assert target != "Now_That"

    def test_an_ordinary_article_is_not_mistaken_for_a_stub(self) -> None:
        assert R._refresh_target(_html("ordinary_prose")) is None


class TestEntitiesAreDecodedNotDeleted:
    """``&amp;`` replaced by a space turned "Rag & Bone" into "Rag Bone" and
    the taxonomic authority "Sakamoto, Iino & Ohkuma 2017" into a different
    authority. 17.1% of articles carried at least one entity."""

    def test_ampersand_survives_in_prose(self) -> None:
        text = _all_passages(_html("ampersand"))
        assert "D&G" in text, "ampersand was deleted rather than decoded"
        assert "D G Bus" not in text

    def test_no_stray_entity_markup_leaks_into_text(self) -> None:
        text = _all_passages(_html("ampersand"))
        assert "&amp;" not in text
        assert "&nbsp;" not in text


class TestExponentsSurvive:
    """Stripping every ``<sup>`` deleted unit exponents, producing clean prose
    that states falsehoods: "9.8 m/s" for an acceleration, "2.77 km" for an
    area. Citation superscripts carry a ``reference``-ish class; content ones
    never do — measured 3,293 vs 25 with zero overlap."""

    def test_acceleration_keeps_its_exponent(self) -> None:
        text = _all_passages(_html("exponent"))
        assert "m/s²" in text, (
            "m/s squared lost its exponent — the corpus now states a wrong unit"
        )

    def test_citation_markers_are_still_stripped(self) -> None:
        text = _all_passages(_html("exponent"))
        assert not re.search(r"\[\s*\d+\s*\]", text), "citation markers leaked"

    def test_the_exponent_is_not_split_off_by_a_space(self) -> None:
        """The obvious fix — keep the tag and let the tag-stripper run — yields
        "9.8 m/s 2", a different wrong answer that would cost a second run."""
        text = _all_passages(_html("exponent"))
        assert "m/s 2" not in text


class TestInfoboxRendering:
    def test_a_nested_table_does_not_truncate_the_infobox(self) -> None:
        """A non-greedy ``</table>`` stops at the first NESTED close; measured,
        that truncated 14.5% of infoboxes partway down."""
        facts = R._infobox_facts(_html("nested_infobox"))
        rows = [ln for ln in facts.splitlines() if ln.strip()]
        assert len(rows) >= 8, f"infobox truncated: only {len(rows)} rows"

    def test_infobox_rows_are_key_equals_value(self) -> None:
        facts = R._infobox_facts(_html("ordinary_prose"))
        assert facts, "no infobox rendered for an article that has one"
        assert any("=" in ln for ln in facts.splitlines())

    def test_no_css_or_script_fragments_leak_into_facts(self) -> None:
        for name in ("nested_infobox", "ordinary_prose"):
            facts = R._infobox_facts(_html(name))
            for bad in ("/*", "mw-parser", "@media", "!important", "px;"):
                assert bad not in facts, f"{bad!r} leaked into {name} facts"


class TestFiguresPairCaptionsWithImages:
    """Two independent ``findall`` passes over a section do not pair: the first
    ``<img>`` is often an infobox logo, not the image the first caption
    describes. And image paths used to be recorded ONLY when a caption existed,
    leaving images in half of all sections unaddressable — which is precisely
    what the later images work needs."""

    def test_a_figure_yields_its_own_caption_and_path_together(self) -> None:
        found = []
        for _heading, body in R._sections(_html("ordinary_prose")):
            found.extend(R._figures(body))
        assert found, "no figures found in an article that has them"
        assert any(cap and img for cap, img in found), (
            "no figure produced BOTH a caption and an image path"
        )

    def test_images_outside_a_figure_block_are_still_recorded(self) -> None:
        """The defect this pins, measured on these very fixtures: MOST images
        are not in a `<figure>` at all — the infobox photograph, inline
        thumbnails, map pins. `_figures` alone left 9 of 11 images in one
        article unaddressable, including the article's own headline photo.
        Article-scope capture is what makes their bytes findable later."""
        for name in ("ordinary_prose", "ampersand", "nested_infobox"):
            page = _html(name)
            figure_imgs = {
                img for _h, b in R._sections(page) for _c, img in R._figures(b) if img
            }
            all_imgs = set(R._all_images(page))
            assert all_imgs, f"{name}: no images recorded at article scope"
            assert all_imgs >= figure_imgs, f"{name}: article scope missed a figure image"
            assert len(all_imgs) > len(figure_imgs), (
                f"{name}: article-scope capture found nothing beyond the figures, "
                "so images outside <figure> are still unreachable"
            )

    def test_article_image_paths_are_deduplicated_and_ordered(self) -> None:
        paths = R._all_images(_html("ordinary_prose"))
        assert len(paths) == len(set(paths))


class TestSectionBreadcrumbs:
    def test_the_lead_section_has_an_empty_breadcrumb(self) -> None:
        first = next(iter(R._sections(_html("ordinary_prose"))))
        assert first[0] == ""

    def test_nesting_produces_an_ancestry_not_just_a_leaf(self) -> None:
        crumbs = [h for h, _ in R._sections(_html("exponent")) if h]
        assert crumbs
        assert any("›" in c for c in crumbs), "no nested breadcrumb built"

    def test_dead_sections_are_recognised_by_their_leaf(self) -> None:
        assert "references" in R._DEAD_SECTIONS
        assert "notes and references" in R._DEAD_SECTIONS


class TestNamespaceFilter:
    """``I/ M/ X/ -/`` were LEGACY ZIM prefixes absent from this archive. Left
    in the pattern they matched real titles containing a slash and dropped 766
    entries: I/O_virtualization, M/M/1_queue, X/Open."""

    @pytest.mark.parametrize(
        "path",
        ["I/O_virtualization", "M/M/1_queue", "X/Open", "M/S_Estonia", "I/O"],
    )
    def test_real_titles_containing_a_slash_are_not_filtered(self, path: str) -> None:
        assert not R._NON_ARTICLE.match(path), (
            f"{path} would be dropped as a namespace prefix"
        )

    @pytest.mark.parametrize(
        "path", ["Category:Stimulating_hormones", "Portal:Science", "_assets_/x.png"]
    )
    def test_real_namespaces_are_still_filtered(self, path: str) -> None:
        assert R._NON_ARTICLE.match(path)


class TestTableCapture:
    """Ordinary tables carry 17.84% of live prose and were dropped entirely."""

    def test_tables_are_rendered_as_rows(self) -> None:
        """Uses an election-results article. The first four fixtures contain
        NO ordinary tables at all — every table in them is an infobox or a
        navbox — so a table test written against them passed vacuously."""
        blocks = []
        for _heading, body in R._sections(_html("content_tables")):
            blocks.extend(R._table_text(body))
        assert blocks, "no ordinary table captured"
        assert any("|" in b for b in blocks)
        assert sum(len(b) for b in blocks) > 2000, (
            "table capture returned only fragments"
        )

    def test_navboxes_are_not_captured_as_content(self) -> None:
        """Navigation boxes are tables too, and they are pure chrome."""
        for name in ("ordinary_prose", "exponent", "list_article"):
            blocks = []
            for _heading, body in R._sections(_html(name)):
                blocks.extend(R._table_text(body))
            assert not blocks, f"{name}: a navbox or infobox leaked in as a table"

    def test_the_infobox_is_not_also_emitted_as_a_table(self) -> None:
        """It is already rendered as facts; emitting it twice would duplicate
        the densest content in the article and skew retrieval toward it."""
        page = _html("ordinary_prose")
        facts = R._infobox_facts(page)
        assert facts
        first_key = facts.splitlines()[0].split("=")[0].strip()
        blocks = []
        for _heading, body in R._sections(page):
            blocks.extend(R._table_text(body))
        assert not any(first_key and first_key in b for b in blocks), (
            "infobox content also appeared in the ordinary-table output"
        )


class TestChunkSizeBounds:
    def test_no_passage_exceeds_the_split_ceiling(self) -> None:
        for name in ("ordinary_prose", "exponent", "list_article"):
            for heading, body in R._sections(_html(name)):
                for piece in R._passages(body):
                    assert len(piece) <= R.MAX_CHARS, (
                        f"{name}: passage of {len(piece)} exceeds MAX_CHARS"
                    )

    def test_dates_and_revisions_are_found_in_a_real_article(self) -> None:
        page = _html("ordinary_prose")
        assert R._LAST_EDITED.search(page), "no last-edited date found"
        assert R._OLDID.search(page), "no revision id found"

    def test_the_date_pattern_does_not_match_twice(self) -> None:
        """If it matched article prose as well as the footer, an article could
        be stamped with a date lifted out of its own text."""
        for name in ("ordinary_prose", "exponent", "ampersand"):
            assert len(R._LAST_EDITED.findall(_html(name))) <= 1

# ---------------------------------------------------------------------------
# The layer that used to live in the driver
# ---------------------------------------------------------------------------
#
# Assembling an entry's records — the alias branch, the section-stub branch,
# the infobox floor, the dead-section filter, the ordinal sequence and the run
# counters — lived outside the repository, next to the single `import libzim`,
# where no test could reach it. Findings 1a, 1b, 1c and 8b all came from that
# file. It is in `extract_rules` now, and these are the tests that could not
# have been written before.


def _stub_page(target: str) -> str:
    """The shape of a section-redirect stub, with a chosen target."""
    return (
        '<html><head><meta http-equiv="refresh" '
        "content=\"0;URL='./" + target + "'\"></head><body></body></html>"
    )


class TestEntryRecords:
    def test_a_section_stub_yields_one_alias_and_says_it_is_a_stub(self) -> None:
        result = R.entry_records("Perch (fish)", "Perch_(fish)", _html("section_stub"))
        assert result.is_stub is True
        assert [r["k"] for r in result.records] == ["alias"]
        assert result.records[0]["a"] == "Perch (fish)"

    def test_a_stub_pointing_out_of_the_article_namespace_emits_nothing(self) -> None:
        """Still a stub, though. That distinction is what keeps it out of the
        vanished-article count: filtering is expected, vanishing is a defect."""
        result = R.entry_records("Foo", "Foo", _stub_page("Category:Bar"))
        assert (result.records, result.is_stub) == ([], True)

    def test_an_ordinary_article_is_not_a_stub_and_emits_records(self) -> None:
        result = R.entry_records("Dog", "Dog", _html("ordinary_prose"))
        assert result.is_stub is False
        assert len(result.records) > 5

    def test_records_are_emitted_in_contract_order(self) -> None:
        kinds = [
            r["k"]
            for r in R.entry_records("Dog", "Dog", _html("ordinary_prose")).records
        ]
        assert kinds[0] == "images", "article-scope images come first"
        assert kinds[1] == "facts", "the infobox precedes the sections"
        assert set(kinds[2:]) <= {"chunk", "caption"}

    def test_ordinals_are_contiguous_from_zero(self) -> None:
        """The store keys a chunk by (article_id, ordinal) and a reader
        reconstructs reading order from it, so a gap is a reordering."""
        for name in ("ordinary_prose", "content_tables", "list_article"):
            records = R.entry_records(name, name, _html(name)).records
            ordinals = [r["o"] for r in records if "o" in r]
            assert ordinals == list(range(len(ordinals))), name

    def test_the_images_record_carries_no_ordinal(self) -> None:
        records = R.entry_records("Dog", "Dog", _html("ordinary_prose")).records
        images = [r for r in records if r["k"] == "images"]
        assert images and "o" not in images[0]

    def test_every_record_carries_the_article_provenance(self) -> None:
        records = R.entry_records("Dog", "Dog/path", _html("ordinary_prose")).records
        assert all(r["t"] == "Dog" and r["p"] == "Dog/path" for r in records)
        assert all("d" in r for r in records), "the edit date must reach every record"

    def test_tables_can_be_switched_off(self) -> None:
        with_tables = R.entry_records("t", "t", _html("content_tables")).records
        without = R.entry_records(
            "t", "t", _html("content_tables"), with_tables=False
        ).records
        assert sum(r.get("tbl", 0) for r in with_tables) > 0
        assert sum(r.get("tbl", 0) for r in without) == 0

    def test_a_short_infobox_is_not_emitted_as_facts(self) -> None:
        page = (
            '<html><body><table class="infobox"><tr><th>Type</th><td>x</td></tr>'
            "</table></body></html>"
        )
        assert len(R._infobox_facts(page)) < R.FACTS_MIN_CHARS
        assert R.entry_records("t", "t", page).records == []

    def test_dead_sections_reach_no_record(self) -> None:
        records = R.entry_records("Dog", "Dog", _html("ordinary_prose")).records
        leaves = {r.get("s", "").rsplit("›", 1)[-1].strip().lower() for r in records}
        assert not (leaves & R._DEAD_SECTIONS)


class TestRedirectAlias:
    def test_a_redirect_becomes_an_alias(self) -> None:
        assert R.redirect_alias("JFK", "John_F._Kennedy") == {
            "k": "alias",
            "a": "JFK",
            "p": "John_F._Kennedy",
        }

    def test_an_anchor_is_carried_opaquely(self) -> None:
        assert R.redirect_alias("A", "B", "Some_Heading")["h"] == "Some_Heading"

    @pytest.mark.parametrize(
        "title,target",
        [
            ("", "Dog"),
            ("Dog", ""),
            ("Cats", "Category:Cats"),
            ("Help", "Help:Contents"),
        ],
    )
    def test_out_of_scope_aliases_are_refused_not_raised(
        self, title: str, target: str
    ) -> None:
        assert R.redirect_alias(title, target) is None


class TestRunCounters:
    """Finding 1c: a run's own metadata could not see its own omissions."""

    def test_an_article_that_emits_nothing_is_counted(self) -> None:
        counters = R.new_counters()
        R.tally(counters, R.entry_records("Empty", "Empty", "<html></html>"))
        assert counters["zero_record_entries"] == 1
        assert counters["articles"] == 0

    def test_a_section_stub_is_not_counted_as_a_vanished_article(self) -> None:
        counters = R.new_counters()
        R.tally(counters, R.entry_records("P", "P", _html("section_stub")))
        assert counters["zero_record_entries"] == 0
        assert (counters["refresh_stubs"], counters["aliases"]) == (1, 1)

    def test_a_filtered_stub_is_still_not_a_vanished_article(self) -> None:
        counters = R.new_counters()
        R.tally(counters, R.entry_records("F", "F", _stub_page("Category:Bar")))
        assert (counters["zero_record_entries"], counters["aliases"]) == (0, 0)
        assert counters["refresh_stubs"] == 1

    def test_the_counters_match_the_records_for_a_real_article(self) -> None:
        counters = R.new_counters()
        result = R.entry_records("t", "t", _html("content_tables"))
        R.tally(counters, result)
        kinds = [r["k"] for r in result.records]
        assert counters["articles"] == 1
        assert counters["captions"] == kinds.count("caption")
        assert counters["facts"] == kinds.count("facts")
        assert counters["tables"] == sum(r.get("tbl", 0) for r in result.records)
        assert counters["chunks"] == len(
            [r for r in result.records if r["k"] in ("chunk", "facts")]
        )
        assert counters["html_entries"] == 1

    def test_captions_are_counted_apart_from_chunks_but_stored_as_chunks(self) -> None:
        """The sidecar reports both, because the two numbers mean different
        things and comparing either to the store's row count needs the sum."""
        counters = R.new_counters()
        result = R.entry_records("Dog", "Dog", _html("ordinary_prose"))
        R.tally(counters, result)
        bearing = len([r for r in result.records if "o" in r])
        assert counters["chunks"] + counters["captions"] == bearing

    def test_a_redirect_alias_touches_no_article_counter(self) -> None:
        counters = R.new_counters()
        R.tally(
            counters,
            R.EntryRecords(
                [R.redirect_alias("JFK", "John_F._Kennedy")],
                is_stub=False,
                is_html=False,
            ),
        )
        assert counters["aliases"] == 1
        assert counters["html_entries"] == 0
        assert counters["articles"] == 0
        assert counters["zero_record_entries"] == 0

    def test_anchored_aliases_are_counted_separately(self) -> None:
        counters = R.new_counters()
        R.tally(counters, R.entry_records("P", "P", _html("section_stub")))
        R.tally(
            counters,
            R.EntryRecords(
                [R.redirect_alias("JFK", "John_F._Kennedy")],
                is_stub=False,
                is_html=False,
            ),
        )
        assert (counters["aliases"], counters["alias_anchored"]) == (2, 1)

    def test_tally_writes_no_counter_a_run_would_not_report(self) -> None:
        """A dict counter accepts a typo silently: the increment lands in a
        key nothing reads, and the sidecar shows the old value forever."""
        counters = R.new_counters()
        keys = set(counters)
        for page in ("<html></html>", _html("ordinary_prose"), _html("section_stub")):
            R.tally(counters, R.entry_records("t", "t", page))
        assert set(counters) == keys

    def test_a_date_reaches_the_dated_counter_only_through_a_real_article(self) -> None:
        counters = R.new_counters()
        R.tally(counters, R.entry_records("Dog", "Dog", _html("ordinary_prose")))
        assert counters["dated"] == 1
        R.tally(counters, R.entry_records("Empty", "Empty", "<html></html>"))
        assert counters["dated"] == 1


class TestRecordsForEntry:
    """The whole per-entry decision, which used to live in an untested driver.

    Aliases, section stubs, dead sections, the facts floor, record ORDER and
    the zero-record determination were all outside the repository, outside
    pytest and outside the gate. That is how eleven defects reached the edge of
    a four-hour run.
    """

    def test_an_ordinary_article_emits_images_facts_then_passages(self) -> None:
        recs = R.records_for_entry("Cheseaux", "Cheseaux", _html("ordinary_prose"))
        assert recs
        kinds = [r["k"] for r in recs]
        assert kinds[0] == "images", "article image paths must be recorded first"
        assert "facts" in kinds and "chunk" in kinds
        # ordinal 0 is the infobox: the densest facts in the article
        facts = [r for r in recs if r["k"] == "facts"]
        assert facts and facts[0]["o"] == 0

    def test_ordinals_are_dense_and_ascending(self) -> None:
        recs = R.records_for_entry("Cheseaux", "Cheseaux", _html("ordinary_prose"))
        ordinals = [r["o"] for r in recs if "o" in r]
        assert ordinals == sorted(ordinals)
        assert ordinals == list(range(len(ordinals)))

    def test_every_text_record_carries_the_articles_own_date(self) -> None:
        recs = R.records_for_entry("Cheseaux", "Cheseaux", _html("ordinary_prose"))
        dated = [r for r in recs if r["k"] in ("chunk", "facts", "caption")]
        assert dated
        assert all("d" in r and "r" in r for r in dated), (
            "a text record reached the store without its article's edit date"
        )

    def test_a_section_stub_emits_exactly_one_alias_and_no_text(self) -> None:
        recs = R.records_for_entry("Sorry (2021 song)", "Sorry_(2021_song)",
                                   _html("section_stub"))
        assert len(recs) == 1
        assert recs[0]["k"] == "alias"
        assert recs[0]["p"] == "Sorry"
        assert recs[0]["h"] == "Songs"

    def test_list_shaped_articles_are_not_empty(self) -> None:
        for name, title in (("disambiguation", "John O'Keefe"),
                            ("list_article", "List of Star Trek lists")):
            recs = R.records_for_entry(title, title.replace(" ", "_"), _html(name))
            assert any(r["k"] == "chunk" for r in recs), (
                f"{name} produced no text — it would vanish from the corpus"
            )

    def test_tables_can_be_switched_off(self) -> None:
        on = R.records_for_entry("x", "x", _html("content_tables"), with_tables=True)
        off = R.records_for_entry("x", "x", _html("content_tables"), with_tables=False)
        assert sum(1 for r in on if r.get("tbl")) > 0
        assert sum(1 for r in off if r.get("tbl")) == 0
        assert len(off) < len(on)

    def test_an_alias_to_a_filtered_namespace_is_dropped(self) -> None:
        assert R.alias_record("Stimulating hormones", "Category:Stimulating_hormones") is None
        assert R.alias_record("", "Some_Article") is None
        assert R.alias_record("JFK", "John_F._Kennedy") == {
            "k": "alias", "a": "JFK", "p": "John_F._Kennedy"
        }


class TestStubArticlesSurvive:
    """A one-sentence stub is still an article.

    `MIN_CHARS` exists to suppress noise chunks, not to erase pages. The last
    zero-record article found in a full-span sample after every other fix was
    "Ensomned, U.S. Virgin Islands", whose entire content is an 89-character
    sentence — under the 110 floor. Wikipedia carries a great many such
    geography and species stubs, and an encyclopedia that omits its stubs lies
    about its coverage as surely as one that omits its long pages.
    """

    def test_a_one_sentence_stub_still_produces_a_record(self) -> None:
        recs = R.records_for_entry(
            "Ensomned, U.S. Virgin Islands", "Ensomned", _html("stub_article")
        )
        text = [r for r in recs if r["k"] == "chunk"]
        assert text, "a real stub article produced nothing and would vanish"
        assert "settlement on the island of Saint Thomas" in text[0]["x"]

    def test_the_fallback_does_not_fire_for_ordinary_articles(self) -> None:
        """If it fired everywhere it would duplicate the lead section."""
        recs = R.records_for_entry("Cheseaux", "Cheseaux", _html("ordinary_prose"))
        leads = [r for r in recs if r["k"] == "chunk" and r.get("s") == ""]
        texts = [r["x"] for r in leads]
        assert len(texts) == len(set(texts)), "lead section emitted twice"

    def test_a_page_with_genuinely_no_prose_still_returns_empty(self) -> None:
        """The fallback must not manufacture a record out of nothing — an empty
        return is what the caller counts as a zero-record entry."""
        assert R.records_for_entry("X", "X", "<html><body></body></html>") == []
        assert R.records_for_entry("X", "X", "<html><body><p>ok</p></body></html>") == []
