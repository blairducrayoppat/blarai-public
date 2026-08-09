"""#1204 — the DISPROOF record for the plan-grounding "salient symbol" rung.

There is no salient rung. This module is why, and it is here rather than only in
git history so that the next author who has the idea trips over the disproof
BEFORE building it rather than after.

THE IDEA. ``ground_goal`` answers exact symbols and error lines but goes silent
on goals written in English, because BM25 normalizes a page's score by the mass
of the WHOLE query — a multi-topic sentence scores every page beneath
``RELEVANCE_FLOOR`` by construction. Measured on the real 2026-07 corpus:
"build a CLI using argparse that reads a csv file" tops out at 0.2986 against a
floor of 0.35, and its best page IS the csv module's own. The retrieval was
never wrong; the gate discarded it. So: retrieve PER TOPIC — pull the salient
words out of the goal and resolve them as symbols.

WHY IT DOES NOT EXIST. Four independent gates were built and each was defeated
by the next set of words anyone tried. Every one separated the goals it was
tuned on and nothing else:

  1. SALIENCE (corpus document frequency <= 0.05). 1,659 plain lowercase words
     pass it on the real corpus. No cap separates the classes: "track" .049,
     "print" .048, "screen" .047 and "date" .043 must be rejected while "title"
     .024, "keyboard" .017 and "cursor" .014 must be admitted.
  2. SYMBOL (resolves in the docset index). Ordinary English words ARE docset
     entries — that is the whole problem, not a wrinkle in it.
  3. CORROBORATION (page in the goal's own top-40 BM25 ranking). Rank cannot
     see it: a SHORT page carrying a rare word ranks HIGH by construction,
     because BM25 divides by document length. The goal
     "my grandmother baked a big cake for the village fete" puts the DEPRECATED
     ``<big>`` element page at rank 10 of 13,803 (score 0.0783; that page is
     0.55x average length) — far inside the bound of 40. Excluding it needs a
     bound below 10, which also excludes most genuine library groundings, which
     ranked 1..27.
  4. LIBRARY (module pages only, ``library/<name>``). Fixed the element class
     and MOVED the defect one namespace over: 163 plain-lowercase words resolve
     to a module page and pass gates 1+2+4 — calendar, socket, queue, site,
     copy, email, random, signal, platform, secrets, wave, turtle, glob, enum,
     locale, webbrowser. On 30 blind goals using those words in their everyday
     sense only 10 stayed silent:
     "make a copy of my important documents every friday" -> ``library/copy``
     (object copying, steering the planner away from shutil; rank 25);
     "build a site for my running club" -> ``library/site`` (sys.path
     configuration; rank 36); "keep a mailbox of notes from my grandchildren"
     -> ``library/mailbox`` (mbox file formats; rank 2).

A fifth candidate — the corroborating page's SCORE rather than its rank — was
measured under a tune/test split and failed on the TUNING set before it reached
the test set: GOOD min 0.2016 vs JUNK max 0.3279 (tune), 0.2503 vs 0.4284
(blind test, 93 goals). "somewhere to keep my secrets safe with a password"
resolves ``library/secrets`` at 0.4284, higher than 17 of 23 genuine library
groundings.

EVERY number above cites its query VERBATIM, and that is a rule rather than a
style. A docstring here once recorded a rank against "read a json config file..."
with a literal ellipsis; an independent reviewer could not know the input,
guessed a completion, measured 45 and 14, and reported the recorded 69 and 27 as
a defect. Two agents spent a round each on it. A measurement whose input is
abbreviated in the record is unreproducible by construction. Two figures
inherited from that review — ``<big>`` at rank 1, and 153 module names — did not
reproduce here (10, and 163) and are recorded above as re-measured, because
quoting an unverified number onward is the same defect moved one hop downstream.

THE ROOT CAUSE, and why no sixth gate is worth building: a large fraction of the
identifiers in any documentation corpus ARE ordinary English words. Deciding
whether "copy" means duplicate-a-file or the ``copy`` module is word-sense
disambiguation. It is semantic, both senses live in the same corpus and often in
the same sentence, and no lexical statistic derived from that corpus can
separate them.

THE PATH THAT REMAINS. The library class is real — 12/12 and 15/15 on two blind
sets, every one a goal that says "use X". ``lookup.semantic_rerank`` has been a
declared seam since slice 1, and an embedding answers "is this page about this
goal" DIRECTLY where every gate above answered a proxy question. That is a
different instrument and it should start from the seam, not from these gates.

Full record: docs/reviews/1204-plan-grounding-salience-disproof-2026-07-31.md
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from shared.research import docset_index as di
from shared.research import plan_grounding as pg

_WIDGET_HTML = (
    "<title>widgetlib — widget toolkit</title>"
    "<h1>widgetlib</h1>"
    "<p>widgetlib assembles widgets from a manifest and emits them in order. "
    "Use widgetlib.assemble() to build a widget from parts.</p>"
)
_FILLER_HTML = (
    "<title>Filler page {n}</title>"
    "<h1>Filler page {n}</h1>"
    "<p>This page explains how to build a small tool to work with a file that "
    "holds records and parts, and how to sort them.</p>"
)
_FILLER_PAGES = 40


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stage_corpus(root: Path) -> Path:
    corpus = root / "docsets"
    dd = corpus / "devdocs" / "python~3.11"
    dd.mkdir(parents=True)

    pages = {"library/widgetlib": _WIDGET_HTML}
    for n in range(_FILLER_PAGES):
        pages[f"filler/page{n}"] = _FILLER_HTML.format(n=n)
    entries = [{"name": "widgetlib", "path": "library/widgetlib", "type": "Toolkits"}]

    (dd / "index.json").write_text(
        json.dumps({"entries": entries, "types": []}), encoding="utf-8"
    )
    (dd / "db.json").write_text(json.dumps(pages), encoding="utf-8")
    with zipfile.ZipFile(corpus / "notes-docs-html.zip", "w") as archive:
        archive.writestr(
            "notes-stable/index.html", "<h1>Notes</h1><p>Release notes.</p>"
        )

    files = [
        ("devdocs-python-3.11-index", "devdocs/python~3.11/index.json"),
        ("devdocs-python-3.11-db", "devdocs/python~3.11/db.json"),
        ("notes-readthedocs-html", "notes-docs-html.zip"),
    ]
    (corpus / di.CORPUS_MANIFEST_NAME).write_text(
        json.dumps(
            {
                "schema": "blarai-docset-manifest/v1",
                "artifacts": [
                    {
                        "name": name,
                        "file": rel,
                        "sha256": _sha256(corpus / rel),
                        "bytes": (corpus / rel).stat().st_size,
                    }
                    for name, rel in files
                ],
            }
        ),
        encoding="utf-8",
    )
    return corpus


@pytest.fixture(scope="module")
def index(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("disproof_corpus")
    corpus = _stage_corpus(root)
    di.build_index(corpus_dir=corpus, index_dir=root / "index")
    handle = di.load_index(index_dir=root / "index", corpus_dir=corpus)
    yield handle
    handle.close()


#: One library name adrift in ordinary English — the shape the operator actually
#: writes, and the shape the removed rung existed to serve.
PLAIN_GOAL = "build a small tool with a file that uses widgetlib to sort parts"


def test_the_salient_rung_does_not_exist() -> None:
    """STRUCTURAL ABSENCE (security_by_design principle 4): the strongest
    dormancy is code that ISN'T THERE. A disabled flag would leave the next
    author a shape built around a premise disproved four times, inherited as a
    starting point rather than as a rejected design.

    If this fails, someone has rebuilt the rung — read this module's docstring
    and the disproof record before concluding they have solved it."""
    for gone in (
        "_salient_symbol_hits",
        "_best_corroborated",
        "SALIENCE_MAX_DF_RATIO",
        "CORROBORATION_MAX_RANK",
        "MODULE_PAGE_PREFIX",
    ):
        assert not hasattr(pg, gone), (
            f"{gone} is back — see this module's docstring for why four gates "
            "of exactly this kind were each disproved on held-out goals"
        )


def test_a_plain_language_goal_grounds_on_nothing(index) -> None:
    """The KNOWN LIMIT, asserted rather than left to be rediscovered.

    This goal names a library the corpus documents, and it grounds on nothing,
    because BM25 scores a multi-topic English sentence beneath the floor by
    construction. The silence is the deliberate current behaviour: a wrong page
    at the head of the planner prompt is worse than no page, and four attempts
    to tell the right page from the wrong one deterministically all failed."""
    assert pg.ground_goal(PLAIN_GOAL, index=index) == ""


def test_a_spelled_symbol_still_grounds(index) -> None:
    """The half that works and must keep working: name the symbol outright and
    the exact rung answers. Without this the test above could pass against a
    broken corpus and prove nothing."""
    block = pg.ground_goal("widgetlib", index=index)
    assert block and "library/widgetlib" in block


def test_usage_record_attributes_only_rungs_that_reached_the_block(
    index, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Capability 7: a number must say what it measured. Attribution reads the
    RENDERED hits, not what each rung produced — the block refit drops trailing
    hits, so a rung can produce one that never reaches the prompt."""
    log = tmp_path / "usage.jsonl"
    monkeypatch.setenv("BLARAI_RESEARCH_USAGE_LOG", str(log))
    assert pg.ground_goal("widgetlib", index=index)
    record = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
    assert record["outcome"] == "grounded"
    assert record["rungs"].startswith("exact"), record
    assert "salient" not in record["rungs"], record
