"""#746 research substrate (slice 1) — index build, deterministic-first lookup,
relevance-floor STOP, caps, refusal, and the zero-egress lock.

Unit tests run against a FIXTURE mini-corpus constructed in ``tmp_path``
(never the real 134 MB staging under ``models/docsets/``, and never writing
into the repo tree). One ``slow``-marked integration test builds the REAL
corpus index into a temp dir when the staged corpus is present.
"""

from __future__ import annotations

import ast
import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from shared.research import docset_index as di
from shared.research import lookup as lk
from shared.research import plan_grounding as pg

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REAL_CORPUS = _REPO_ROOT / "models" / "docsets"


# ---------------------------------------------------------------------------
# Fixture mini-corpus (constructed on disk, hash-pinned like the real one)
# ---------------------------------------------------------------------------

_JSON_PAGE_HTML = (
    "<h1>json — JSON encoder and decoder</h1>"
    "<p>Intro text about the json module and serialization of python objects.</p>"
    '<dl><dt id="json.dumps"><code>json.dumps(obj, indent=None)</code></dt>'
    "<dd>Serialize obj to a JSON formatted str using this conversion table. "
    "Keyword arguments zebra sentinel dumps.</dd>"
    '<dt id="json.dump"><code>json.dump(obj, fp)</code></dt>'
    "<dd>Serialize obj as a JSON formatted stream to fp, a write-supporting "
    "file-like object.</dd></dl>"
    "<script>var tracker = 'must never appear in text';</script>"
)

_EXC_PAGE_HTML = (
    "<h1>Built-in Exceptions</h1><p>Exception hierarchy overview quokka.</p>"
    '<dl><dt id="ValueError"><code>exception ValueError</code></dt>'
    "<dd>Raised when an operation or function receives an argument of the "
    "right type but an inappropriate value.</dd></dl>"
)

_TUTORIAL_PAGE_HTML = "<h1>An Informal Introduction</h1><p>" + (
    "informal tutorial filler words about python basics. " * 40
) + "</p>"

_PYTEST_FIXTURES_HTML = (
    "<title>pytest fixtures — pytest documentation</title>"
    "<h1>pytest fixtures reference</h1>"
    "<p>Fixtures provide a fixed baseline. fixture scope controls teardown "
    "wombat lifetimes across tests and modules.</p>"
)

_PYTEST_GENINDEX_HTML = "<h1>Index</h1><p>site chrome that must be skipped</p>"

# A sphinx-singlehtml-shaped member (the real readthedocs "htmlzip" is ONE
# giant page of nested <section id=...> elements): a tiny preamble (folds
# forward), a real section with a tiny NESTED section (folds back into it),
# and a second real section.
_PYTEST_SINGLE_HTML = (
    "<h1>pytest full documentation</h1>"
    '<section id="approx-usage"><h2>Using approx</h2><p>'
    + "compare floating point values with approx tolerance narwhal. " * 4
    + "</p>"
    '<section id="tiny-stub"><h3>Stub</h3><p>see other section</p></section>'
    "</section>"
    '<section id="parametrize-guide"><h2>Parametrize guide</h2><p>'
    + "parametrize test functions with multiple argument sets pangolin. " * 4
    + "</p></section>"
)

_PYTHON_TEXT_JSON_TXT = (
    '"json" --- JSON encoder and decoder\n'
    "***********************************\n\n"
    "JSON (JavaScript Object Notation) serialization zebra encoder decoder "
    "obj str for python objects.\n"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stage_mini_corpus(root: Path) -> Path:
    """Construct a manifest-pinned mini-corpus mirroring the real staging
    shape: one DevDocs docset + one readthedocs html zip + one official text
    zip + MANIFEST.sha256.json with REAL hashes."""
    corpus = root / "docsets"
    dd = corpus / "devdocs" / "python~3.11"
    dd.mkdir(parents=True)
    (corpus / "devdocs" / "pytest").mkdir()  # the real staging's empty stray dir

    entries = [
        {"name": "json.dumps()", "path": "library/json#json.dumps", "type": "Internet Data"},
        {"name": "json.dump()", "path": "library/json#json.dump", "type": "Internet Data"},
        {"name": "json", "path": "library/json", "type": "Internet Data"},
        {"name": "ValueError", "path": "library/exceptions#ValueError", "type": "Built-in Exceptions"},
        {"name": "with", "path": "library/json", "type": "Keyword"},
        {"name": "dangling.entry()", "path": "library/missing#dangling", "type": "Ghost"},
    ]
    (dd / "index.json").write_text(
        json.dumps({"entries": entries, "types": []}), encoding="utf-8"
    )
    (dd / "db.json").write_text(
        json.dumps(
            {
                "library/json": _JSON_PAGE_HTML,
                "library/exceptions": _EXC_PAGE_HTML,
                "tutorial/introduction": _TUTORIAL_PAGE_HTML,
            }
        ),
        encoding="utf-8",
    )

    with zipfile.ZipFile(corpus / "pytest-docs-html.zip", "w") as archive:
        archive.writestr("pytest-stable/fixtures.html", _PYTEST_FIXTURES_HTML)
        archive.writestr("pytest-stable/single.html", _PYTEST_SINGLE_HTML)
        archive.writestr("pytest-stable/genindex.html", _PYTEST_GENINDEX_HTML)
        archive.writestr("pytest-stable/_static/style.css", "body {}")
        archive.writestr("pytest-stable/.buildinfo", "buildinfo")
    with zipfile.ZipFile(corpus / "python-3.11-docs-text.zip", "w") as archive:
        archive.writestr(
            "python-3.11.13-docs-text/library/json.txt", _PYTHON_TEXT_JSON_TXT
        )

    files = [
        ("devdocs-python-3.11-index", "devdocs/python~3.11/index.json"),
        ("devdocs-python-3.11-db", "devdocs/python~3.11/db.json"),
        ("pytest-readthedocs-html", "pytest-docs-html.zip"),
        ("python-3.11-official-text", "python-3.11-docs-text.zip"),
    ]
    artifacts = [
        {
            "name": name,
            "file": rel,
            "sha256": _sha256(corpus / rel),
            "bytes": (corpus / rel).stat().st_size,
        }
        for name, rel in files
    ]
    (corpus / di.CORPUS_MANIFEST_NAME).write_text(
        json.dumps({"schema": "blarai-docset-manifest/v1", "artifacts": artifacts}),
        encoding="utf-8",
    )
    return corpus


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory):
    """One shared read-only build for the query-side tests."""
    root = tmp_path_factory.mktemp("research_mini")
    corpus = _stage_mini_corpus(root)
    index_dir = root / "index"
    stats = di.build_index(corpus_dir=corpus, index_dir=index_dir)
    index = di.load_index(index_dir=index_dir, corpus_dir=corpus)
    yield corpus, index_dir, stats, index
    index.close()


# ---------------------------------------------------------------------------
# Index build + persistence
# ---------------------------------------------------------------------------


def test_build_persists_index_and_stats(built) -> None:
    corpus, index_dir, stats, index = built
    assert (index_dir / di.INDEX_FILENAME).is_file()
    assert stats.index_bytes > 0
    # 3 devdocs + fixtures.html + 2 section pages of single.html + json.txt.
    assert stats.n_pages == 7
    assert stats.n_symbols == 5  # the dangling entry attaches to no page
    assert stats.n_terms > 0 and stats.n_postings > 0
    assert stats.per_source_pages == {
        "python~3.11": 3,
        "pytest-readthedocs-html": 3,
        "python-3.11-official-text": 1,
    }
    assert index.n_pages == 7 and index.avgdl > 0


def test_zip_site_chrome_is_skipped_and_txt_titled_from_first_line(built) -> None:
    _, _, _, index = built
    assert index.page_by_path("pytest-readthedocs-html", "pytest-stable/genindex.html") is None
    assert index.page_by_path("pytest-readthedocs-html", "pytest-stable/_static/style.css") is None
    fixtures = index.page_by_path("pytest-readthedocs-html", "pytest-stable/fixtures.html")
    assert fixtures is not None and fixtures.title == "pytest fixtures reference"
    txt = index.page_by_path(
        "python-3.11-official-text", "python-3.11.13-docs-text/library/json.txt"
    )
    assert txt is not None
    assert txt.title == '"json" --- JSON encoder and decoder'


def test_singlehtml_bundle_is_split_into_section_pages(built) -> None:
    """A sphinx-singlehtml member becomes per-section pages: real sections get
    their own page (titled by their heading, pathed by ``member#section-id``);
    tiny fragments FOLD into a neighbor instead of being dropped."""
    _, _, _, index = built
    approx = index.page_by_path(
        "pytest-readthedocs-html", "pytest-stable/single.html#approx-usage"
    )
    assert approx is not None and approx.title == "Using approx"
    assert "pytest full documentation" in approx.text  # tiny preamble folded forward
    assert "see other section" in approx.text  # tiny nested section folded back
    parametrize = index.page_by_path(
        "pytest-readthedocs-html", "pytest-stable/single.html#parametrize-guide"
    )
    assert parametrize is not None and parametrize.title == "Parametrize guide"
    assert (
        index.page_by_path(
            "pytest-readthedocs-html", "pytest-stable/single.html#tiny-stub"
        )
        is None
    )
    # Section pages are reachable through ranked search like any other page.
    hits = lk.search_docs(
        "parametrize test functions with multiple argument sets pangolin",
        k=2,
        index=index,
    )
    assert hits and hits[0].path == "pytest-stable/single.html#parametrize-guide"


def test_html_strip_drops_script_and_records_anchors(built) -> None:
    _, _, _, index = built
    page = index.page_by_path("python~3.11", "library/json")
    assert page is not None
    assert "must never appear in text" not in page.text
    assert "json.dumps" in page.anchors and "json.dump" in page.anchors
    assert page.anchors["json.dumps"] < page.anchors["json.dump"]
    assert page.title == "json — JSON encoder and decoder"


def test_page_text_cap_enforced_at_build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    corpus = _stage_mini_corpus(tmp_path)
    monkeypatch.setattr(di, "PAGE_TEXT_CAP", 400)
    di.build_index(corpus_dir=corpus, index_dir=tmp_path / "idx")
    with di.load_index(index_dir=tmp_path / "idx", corpus_dir=corpus) as index:
        page = index.page_by_path("python~3.11", "tutorial/introduction")
        assert page is not None
        assert len(page.text) <= 400  # the fixture page strips to ~2000 chars uncapped


# ---------------------------------------------------------------------------
# Refusal + integrity (fail-closed)
# ---------------------------------------------------------------------------


def test_corpus_dir_absent_refuses_naming_stage_script(tmp_path: Path) -> None:
    with pytest.raises(di.CorpusMissingError, match=r"scripts/stage_docsets\.py"):
        di.build_index(corpus_dir=tmp_path / "nope", index_dir=tmp_path / "idx")


def test_corpus_manifest_absent_refuses_naming_stage_script(tmp_path: Path) -> None:
    (tmp_path / "empty_corpus").mkdir()
    with pytest.raises(di.CorpusMissingError, match=r"scripts/stage_docsets\.py"):
        di.build_index(corpus_dir=tmp_path / "empty_corpus", index_dir=tmp_path / "idx")


def test_tampered_artifact_refuses_with_integrity_error(tmp_path: Path) -> None:
    corpus = _stage_mini_corpus(tmp_path)
    db = corpus / "devdocs" / "python~3.11" / "db.json"
    db.write_bytes(db.read_bytes() + b" ")
    with pytest.raises(di.CorpusIntegrityError, match="SHA-256 mismatch"):
        di.build_index(corpus_dir=corpus, index_dir=tmp_path / "idx")


def test_missing_pinned_artifact_refuses(tmp_path: Path) -> None:
    corpus = _stage_mini_corpus(tmp_path)
    (corpus / "pytest-docs-html.zip").unlink()
    with pytest.raises(di.CorpusIntegrityError, match="missing"):
        di.build_index(corpus_dir=corpus, index_dir=tmp_path / "idx")


def test_load_without_build_raises_index_not_built(tmp_path: Path) -> None:
    corpus = _stage_mini_corpus(tmp_path)
    with pytest.raises(di.IndexNotBuiltError):
        di.load_index(index_dir=tmp_path / "never_built", corpus_dir=corpus)


def test_restaged_corpus_marks_index_stale_and_ensure_rebuilds(tmp_path: Path) -> None:
    corpus = _stage_mini_corpus(tmp_path)
    index_dir = tmp_path / "idx"
    di.build_index(corpus_dir=corpus, index_dir=index_dir)
    manifest = corpus / di.CORPUS_MANIFEST_NAME
    manifest.write_bytes(manifest.read_bytes() + b"\n")  # re-staged corpus
    with pytest.raises(di.StaleIndexError):
        di.load_index(index_dir=index_dir, corpus_dir=corpus)
    with di.ensure_index(index_dir=index_dir, corpus_dir=corpus) as index:
        assert index.n_pages == 7


def test_schema_bump_marks_index_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus = _stage_mini_corpus(tmp_path)
    index_dir = tmp_path / "idx"
    di.build_index(corpus_dir=corpus, index_dir=index_dir)
    monkeypatch.setattr(di, "INDEX_SCHEMA_VERSION", di.INDEX_SCHEMA_VERSION + 1)
    with pytest.raises(di.StaleIndexError):
        di.load_index(index_dir=index_dir, corpus_dir=corpus)


def test_ensure_index_builds_from_scratch(tmp_path: Path) -> None:
    corpus = _stage_mini_corpus(tmp_path)
    with di.ensure_index(index_dir=tmp_path / "idx", corpus_dir=corpus) as index:
        assert index.n_pages == 7


def test_corpus_absent_propagates_loudly_through_lookup_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The coder-facing calls raise (naming the stage script) when neither an
    index nor a corpus exists — a missing corpus is never a quiet []."""
    monkeypatch.setattr(di, "DEFAULT_CORPUS_DIR", tmp_path / "absent")
    monkeypatch.setattr(di, "DEFAULT_INDEX_DIR", tmp_path / "absent" / "index")
    lk.reset_default_index()
    try:
        with pytest.raises(di.CorpusMissingError, match=r"scripts/stage_docsets\.py"):
            lk.search_docs("anything at all")
        with pytest.raises(di.CorpusMissingError):
            lk.exact_lookup("json.dumps")
    finally:
        lk.reset_default_index()


# ---------------------------------------------------------------------------
# exact_lookup — deterministic-first
# ---------------------------------------------------------------------------


def test_exact_lookup_symbol(built) -> None:
    _, _, _, index = built
    hits = lk.exact_lookup("json.dumps", index=index)
    assert hits and hits[0].score == 1.0
    assert hits[0].source == "python~3.11"
    assert hits[0].path == "library/json#json.dumps"
    assert "Serialize obj to a JSON formatted str" in hits[0].excerpt


def test_exact_lookup_normalizes_spelling(built) -> None:
    _, _, _, index = built
    for spelling in ("json.dumps()", "JSON.DUMPS", "  json.dumps :", "`json.dumps`"):
        hits = lk.exact_lookup(spelling, index=index)
        assert hits and hits[0].path == "library/json#json.dumps", spelling


def test_exact_lookup_excerpts_at_the_anchor_not_the_page_head(built) -> None:
    _, _, _, index = built
    hits = lk.exact_lookup("json.dump", index=index)
    assert hits and hits[0].path == "library/json#json.dump"
    assert "stream to fp" in hits[0].excerpt
    assert "Intro text about" not in hits[0].excerpt  # anchor-positioned, not head


def test_exact_lookup_resolves_error_text_via_token_extraction(built) -> None:
    hits = lk.exact_lookup(
        "ValueError: invalid literal for int() with base 10: 'x'", index=built[3]
    )
    assert hits and hits[0].title == "ValueError"
    assert hits[0].score == 0.9  # the token tier, below whole-string exactness
    assert hits[0].path == "library/exceptions#ValueError"


def test_exact_lookup_token_tier_rejects_plain_lowercase_words(built) -> None:
    """The embedded-token fallback accepts only CODE-SHAPED tokens (dotted /
    underscored / cased): ``with`` IS a docset entry, and a deliberate
    whole-string lookup finds it — but buried in prose it is English, not a
    symbol reference, and must not hijack the exact tier (measured live: the
    JS ``with`` statement outranked real pytest hits in a grounding block)."""
    _, _, _, index = built
    direct = lk.exact_lookup("with", index=index)
    assert direct and direct[0].title == "with"  # rung 1: deliberate lookup
    embedded = lk.exact_lookup("write tests with fixtures please", index=index)
    assert embedded == []  # rung 2 never fires on plain lowercase prose


def test_exact_lookup_unknown_symbol_returns_empty(built) -> None:
    assert lk.exact_lookup("frobnicate.zorp", index=built[3]) == []
    assert lk.exact_lookup("", index=built[3]) == []
    assert lk.exact_lookup("   ", index=built[3]) == []


def test_exact_lookup_is_deterministic(built) -> None:
    _, _, _, index = built
    first = lk.exact_lookup("json.dumps()", index=index)
    second = lk.exact_lookup("json.dumps()", index=index)
    assert first == second


# ---------------------------------------------------------------------------
# search_docs — floor-gated local BM25
# ---------------------------------------------------------------------------


def test_search_docs_ranks_the_right_page_first(built) -> None:
    _, _, _, index = built
    hits = lk.search_docs("pytest fixture scope wombat teardown", k=3, index=index)
    assert hits
    assert hits[0].source == "pytest-readthedocs-html"
    assert hits[0].path == "pytest-stable/fixtures.html"
    assert 0.0 < hits[0].score <= 1.0
    assert "fixture scope" in hits[0].excerpt


def test_search_docs_scores_sorted_and_within_unit_interval(built) -> None:
    hits = lk.search_docs("json serialization of python objects", k=4, index=built[3])
    assert hits
    scores = [hit.score for hit in hits]
    assert scores == sorted(scores, reverse=True)
    assert all(0.0 < score <= 1.0 for score in scores)
    assert all(score >= lk.RELEVANCE_FLOOR for score in scores)


def test_search_docs_relevance_floor_stops_junk(built) -> None:
    _, _, _, index = built
    assert lk.search_docs("qqxjz wvvbnq zzptk", k=4, index=index) == []
    # One real term drowned in seven unknown ones: coverage too weak — STOP.
    assert (
        lk.search_docs(
            "zebra qaxw1 qaxw2 qaxw3 qaxw4 qaxw5 qaxw6 qaxw7", k=4, index=index
        )
        == []
    )


def test_search_docs_floor_is_the_module_level_gate(built, monkeypatch) -> None:
    _, _, _, index = built
    query = "pytest fixture scope wombat teardown"
    assert lk.search_docs(query, k=2, index=index)  # clears the default floor
    monkeypatch.setattr(lk, "RELEVANCE_FLOOR", 1.01)  # nothing can clear > 1.0
    assert lk.search_docs(query, k=2, index=index) == []


def test_search_docs_respects_k_and_guards(built) -> None:
    _, _, _, index = built
    assert len(lk.search_docs("json serialization python", k=1, index=index)) <= 1
    assert lk.search_docs("json", k=0, index=index) == []
    assert lk.search_docs("", k=4, index=index) == []
    assert lk.search_docs("   ", k=4, index=index) == []


def test_search_docs_collapses_duplicate_content_sources(built, monkeypatch) -> None:
    """The official python text archive mirrors the DevDocs python docset;
    when both copies of the same page clear the floor only one is returned.
    Non-vacuous: with the dup groups disabled BOTH copies rank (proving the
    query genuinely reaches both), with them active exactly one survives."""
    _, _, _, index = built
    query = "json encoder and decoder zebra"
    dup_sources = {"python~3.11", "python-3.11-official-text"}

    monkeypatch.setattr(lk, "_DUP_SOURCE_GROUPS", ())
    uncollapsed = lk.search_docs(query, k=4, index=index)
    assert dup_sources <= {hit.source for hit in uncollapsed}, (
        "fixture drift: both duplicate copies must clear the floor for this "
        "test to prove anything"
    )
    monkeypatch.undo()

    hits = lk.search_docs(query, k=4, index=index)
    assert hits
    assert len([hit for hit in hits if hit.source in dup_sources]) == 1


def test_search_docs_is_deterministic(built) -> None:
    _, _, _, index = built
    query = "serialize json formatted str conversion table"
    assert lk.search_docs(query, k=4, index=index) == lk.search_docs(
        query, k=4, index=index
    )


def test_results_identical_across_independent_builds(tmp_path: Path, built) -> None:
    """Same corpus in => identical lookup results out, on a from-scratch
    rebuild in a different directory (the determinism contract)."""
    corpus = _stage_mini_corpus(tmp_path)
    di.build_index(corpus_dir=corpus, index_dir=tmp_path / "idx2")
    with di.load_index(index_dir=tmp_path / "idx2", corpus_dir=corpus) as rebuilt:
        for query in ("json.dumps", "ValueError: bad input"):
            assert lk.exact_lookup(query, index=rebuilt) == lk.exact_lookup(
                query, index=built[3]
            )
        for query in ("pytest fixture scope wombat", "json serialization python"):
            assert lk.search_docs(query, k=4, index=rebuilt) == lk.search_docs(
                query, k=4, index=built[3]
            )


def test_excerpts_are_prompt_safe_and_capped(built) -> None:
    _, _, _, index = built
    for hits in (
        lk.exact_lookup("json.dumps", index=index),
        lk.search_docs("informal tutorial filler words about python", k=4, index=index),
    ):
        assert hits
        for hit in hits:
            assert len(hit.excerpt) <= lk.EXCERPT_MAX_CHARS
            assert "\n" not in hit.excerpt and "\r" not in hit.excerpt
            assert not any(ord(ch) < 32 for ch in hit.excerpt)
            # Unicode format/bidi controls (trojan-source class) are stripped
            # too — MDN pages really carry U+2068/2069 around inline code.
            assert not any(0x2060 <= ord(ch) <= 0x2069 for ch in hit.excerpt)
            assert not any(0x202A <= ord(ch) <= 0x202E for ch in hit.excerpt)
            assert "​" not in hit.excerpt and "﻿" not in hit.excerpt


def test_bidi_and_zero_width_controls_stripped_from_excerpts() -> None:
    from shared.research.lookup import _clean_snippet

    poisoned = "call ⁨json.dumps⁩ with​ care ‮ reversed ﻿"
    cleaned = _clean_snippet(poisoned, prefix_ellipsis=False)
    assert "json.dumps" in cleaned
    for bad in ("⁨", "⁩", "​", "‮", "﻿"):
        assert bad not in cleaned


def test_semantic_rerank_seam_is_identity(built) -> None:
    _, _, _, index = built
    hits = lk.search_docs("json serialization python objects", k=3, index=index)
    reranked = lk.semantic_rerank(hits, "json serialization python objects")
    assert reranked == hits
    assert reranked is not hits  # a fresh list — callers may mutate safely


# ---------------------------------------------------------------------------
# plan grounding — pull-not-push, bounded, degrade-gracefully
# ---------------------------------------------------------------------------


def test_ground_goal_renders_bounded_block_with_exact_hit_first(built) -> None:
    _, _, _, index = built
    goal = "add a helper that serializes config dicts with json.dumps"
    block = pg.ground_goal(goal, index=index)
    assert block, "a goal naming a real symbol must ground"
    assert block.startswith(pg.GROUNDING_HEADER)
    assert block.endswith(pg.GROUNDING_FOOTER)
    assert len(block) <= pg.GROUNDING_MAX_CHARS
    assert "#json.dumps" in block  # the exact hit leads
    assert "[python~3.11]" in block


def test_ground_goal_returns_empty_when_nothing_clears_the_floor(built) -> None:
    _, _, _, index = built
    assert pg.ground_goal("qqxjz wvvbnq zzptk blorp", index=index) == ""
    assert pg.ground_goal("", index=index) == ""
    assert pg.ground_goal("json things", k=0, index=index) == ""


def test_ground_goal_is_deterministic(built) -> None:
    _, _, _, index = built
    goal = "write pytest fixtures with module scope teardown wombat"
    assert pg.ground_goal(goal, index=index) == pg.ground_goal(goal, index=index)


def test_ground_goal_fits_even_a_tiny_cap(built, monkeypatch) -> None:
    _, _, _, index = built
    monkeypatch.setattr(pg, "GROUNDING_MAX_CHARS", 120)
    block = pg.ground_goal("json serialization with json.dumps", index=index)
    assert len(block) <= 120  # shrinks/drops hits; "" is an acceptable outcome


def test_ground_goal_merge_dedupes_pages_but_keeps_distinct_sections() -> None:
    """An exact hit (``page#fragment``) suppresses the search copy of the SAME
    DevDocs page; two zip SECTION pages of one document (stored paths carry
    ``#section-id``) are distinct and BOTH survive (regression lock for the
    fragment-stripping over-collapse)."""

    def _hit(source: str, path: str) -> lk.DocHit:
        return lk.DocHit(source=source, title=path, path=path, score=0.9, excerpt="x")

    exact = [_hit("python~3.11", "library/json#json.dumps")]
    searched = [
        _hit("python~3.11", "library/json"),  # same page as the exact hit
        _hit("pytest-readthedocs-html", "pytest-stable/single.html#approx-usage"),
        _hit("pytest-readthedocs-html", "pytest-stable/single.html#parametrize-guide"),
    ]
    merged = pg._merge_hits(exact, searched, k=3)
    assert [(h.source, h.path) for h in merged] == [
        ("python~3.11", "library/json#json.dumps"),
        ("pytest-readthedocs-html", "pytest-stable/single.html#approx-usage"),
        ("pytest-readthedocs-html", "pytest-stable/single.html#parametrize-guide"),
    ]


def test_index_loads_from_a_path_with_uri_hostile_characters(tmp_path: Path) -> None:
    """Index dirs containing spaces/#/% must load — the read-only sqlite URI
    escapes them (no urllib in this package, by the zero-egress lock)."""
    corpus = _stage_mini_corpus(tmp_path)
    index_dir = tmp_path / "odd dir #1 %x"
    di.build_index(corpus_dir=corpus, index_dir=index_dir)
    with di.load_index(index_dir=index_dir, corpus_dir=corpus) as index:
        assert index.n_pages == 7
        assert lk.exact_lookup("json.dumps", index=index)


def test_ground_goal_degrades_gracefully_when_corpus_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Plan grounding is enrichment: no corpus, no index => '' (logged), never
    an exception into decompose."""
    monkeypatch.setattr(di, "DEFAULT_CORPUS_DIR", tmp_path / "absent")
    monkeypatch.setattr(di, "DEFAULT_INDEX_DIR", tmp_path / "absent" / "index")
    lk.reset_default_index()
    try:
        assert pg.ground_goal("serialize dicts with json.dumps") == ""
    finally:
        lk.reset_default_index()


# ---------------------------------------------------------------------------
# Zero-egress lock (stricter, module-scoped twin of
# tests/security/test_no_external_egress.py — which also covers shared/)
# ---------------------------------------------------------------------------

_FORBIDDEN_NETWORK_MODULES = frozenset(
    {
        "urllib", "requests", "socket", "http", "httpx", "aiohttp", "urllib3",
        "websocket", "websockets", "ftplib", "smtplib", "poplib", "imaplib",
        "telnetlib", "nntplib", "ssl", "asyncio",
    }
)


def test_research_modules_import_no_network_machinery() -> None:
    """shared/research/ must be incapable of egress BY CONSTRUCTION: no
    urllib/requests/socket/http/... imports anywhere in the package (stricter
    than the repo-wide scan, which allows e.g. local-IPC socket use)."""
    package_dir = _REPO_ROOT / "shared" / "research"
    sources = sorted(package_dir.glob("*.py"))
    assert len(sources) >= 4, "package files missing — scan would be vacuous"
    for source_path in sources:
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            imported: list[str] = []
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                imported = [node.module]
            for name in imported:
                top = name.split(".")[0]
                assert top not in _FORBIDDEN_NETWORK_MODULES, (
                    f"{source_path.name} imports {name!r} — shared/research/ is "
                    f"local-retrieval-only (zero egress, #746)"
                )


# ---------------------------------------------------------------------------
# Real-corpus integration (slow; skipped when the staging is absent)
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.skipif(
    not (_REAL_CORPUS / di.CORPUS_MANIFEST_NAME).is_file(),
    reason="staged docset corpus absent (provision via scripts/stage_docsets.py)",
)
def test_real_corpus_build_and_lookup(tmp_path: Path) -> None:
    """Build the REAL 2026-07 corpus index into a temp dir (never the repo
    tree) and prove the two lookup rungs on known symbols."""
    stats = di.build_index(corpus_dir=_REAL_CORPUS, index_dir=tmp_path / "index")
    assert stats.n_pages > 10_000 and stats.n_symbols > 20_000
    with di.load_index(index_dir=tmp_path / "index", corpus_dir=_REAL_CORPUS) as index:
        dumps_hits = lk.exact_lookup("json.dumps", index=index)
        assert dumps_hits and dumps_hits[0].source == "python~3.11"
        assert dumps_hits[0].path == "library/json#json.dumps"
        dom_hits = lk.exact_lookup("Element.querySelector", index=index)
        assert dom_hits and dom_hits[0].source == "dom"
        searched = lk.search_docs("pytest fixture scope", k=4, index=index)
        assert searched and any("pytest" in hit.source for hit in searched)
        assert lk.search_docs("xqzzy flurbish gronkulate blimblam", k=4, index=index) == []
