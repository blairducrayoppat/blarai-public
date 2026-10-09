# Reference-corpus extraction contract (#1616) — REVISED after adversarial review

**Status:** EXTRACTION RAN against this contract on 2026-09-23 (commit `d34e2516`, rules SHA
`50a766a2…`, 3.00 h, 7,341,217 articles / 68,374,765 chunks / 11,990,041 aliases). Store build
followed. **§7 retracts the length-floor justifications in §2** — read it before relying on §2.
**History:** a first run was stopped at 28% when the LA caught a date defect. A second was
stopped before launch when the LA asked for an adversarial review; that review found
**19 defects** and blocked the run. A second review round found four more. This is the third version.
**Cost of being wrong:** ~3 hours of saturated CPU to re-extract, ~2 hours to rebuild.
**Disposition of every review finding:** `docs/reviews/corpus-extraction-contract-disposition-2026-09-23.md`

---

## 0. The decision that bounds the damage

**The 118.7 GiB source archive is KEPT, and so is the extracted JSONL (~10 GB).**

| If we later need… | Cost with both kept | If deleted |
|---|---|---|
| A different store schema | **rebuild, ~2 h** | re-download + re-extract |
| A field captured but unused | **rebuild, ~2 h** | ~3 h re-extract |
| A field never captured | ~3 h re-extract | re-download + 3 h |
| Image bytes | **read from the archive** | unrecoverable |

The only genuinely expensive error is failing to write something down during the pass.
Disk: **drive B: (`B:\scratch\zim`, `B:\kiwix`)**, 512 GB free; archive 119 + JSONL ~10 + store ~55 = ~184 GB, leaving ~330 GB.

---

## 1. Measurements — RE-MEASURED, and the earlier figures retracted

**Every figure in the first version of this contract was wrong**, from one cause: the sampling
strode across entries but stopped after N hits, so it only ever saw the first ~7% of a
30,142,538-entry archive. The table below is uniform sampling over the whole id range, measured
independently by the author and by the reviewer, agreeing to within about one point.

**What the archive contains, and therefore what every percentage is a share of.**

| Count | Value |
|---|---|
| Total entries (`all_entry_count`) | 30,142,538 |
| …of which MEDIA files | 8,469,385 |
| …of which content entries (`article_count`) | 21,673,012 |

`all_entry_count` and the catalogue's `article_count` differ by exactly the image files. **Rates
below are shares of all 30,142,538 entries unless the row says otherwise**; as a share of CONTENT
entries only, redirects are ~50% and article HTML pages ~39%.

| Measurement | Value | earlier claim (WRONG) |
|---|---|---|
| Redirects | **36.6%** | 56% |
| Article-namespace HTML entries | ~8.6M | — |
| Articles carrying last-edited + revision id | **85.9%** (co-occur 363/363) | 87% (survives) |
| Articles last edited BEFORE the archive build | **99.2%** | 35.3% |
| Articles with an infobox | **60.7%** | 73% |
| Ordinary-table text vs paragraph text | **81%** | 420% |
| List-item text vs paragraph text | **119%** | 344% |
| **Article HTML entries emitting NOTHING (before fixes)** | **21.5%** | not measured |
| …of which section-redirect stubs | 14.0% | not measured |
| Live prose never indexed (before fixes) | **31.1%** | not measured |
| Articles losing >half their live prose (before fixes) | **22.8%** | not measured |

**After the fixes: `zero_record_entries` = 0.04%, down from 21.5%.** Measured by uniform sampling
over the whole id range (9,000 entries, ids 4,074–30,034,981), 2,559 article HTML entries: 86.1%
produce text, 13.8% produce only an alias (section stubs, correct), 1 produced nothing.

> **The earlier "0 of 400" claim is RETRACTED.** That trial used `--limit`, so it walked from the
> start of the archive and never left it — the identical sampling bias retracted in finding 8d,
> committed by the same author two hours after writing the retraction. A rate measured that way is
> not evidence about the corpus. The single remaining zero-record article was real (a 89-character
> stub) and is fixed at `acc8c896`.

---

## 2. What the extractor emits

```
{"k":"chunk",   t,p,s,x,o, d?,r?, tbl?}   a passage: prose, merged list run, or table rows
{"k":"facts",   t,p,x,o,   d?,r?}         an infobox as `key = value` lines
{"k":"caption", t,p,s,x,o, d?,r?, i?}     a figure caption, SEARCHABLE, paired with its image
{"k":"images",  t,p,paths[]}              every image path in the article, article scope
{"k":"alias",   a,p,h?}                   a redirect title -> target path (+ opaque anchor)
```

### Capture rules, each with the measurement behind it

| Element | Decision | Why |
|---|---|---|
| `<p>` paragraphs | KEEP, floor 110, short runs merged | ⚠️ **justification RETRACTED** — see §7 |
| `<li>` list items | KEEP as merged RUNS, no per-item floor | a per-item floor rescues only half the vanishing articles; disambiguation entries are ~24 chars by construction |
| Infobox tables | `key = value`, ALL infoboxes, depth-balanced, colspan rows kept | 60.7% of articles; densest facts; non-greedy match truncated 14.5% |
| Ordinary tables | KEEP as ` \| `-joined rows, 120-char block floor | **17.84% of live prose** — election results, discographies, climate, sports; ⚠️ but the floor drops every table in ~6% of table-bearing articles — see §7 |
| Navboxes | DROP | pure navigation chrome |
| `<figcaption>` | KEEP as a SEARCHABLE record, paired with its image | captions are how images are found without an image model |
| All `<img>` paths | KEEP at article scope | most images are outside any `<figure>` — including articles' own headline photos |
| `<sup>` | STRIP only if class matches `reference\|mw-ref\|noexcerpt`; else fold in with NO space | 3,293 citation vs 25 content sups, zero overlap; stripping all of them made km²→km |
| `<sub>` | fold in with no space | same bug in the other direction: H₂O was "H 2 O" |
| Entities | `html.unescape`, never delete | "Rag & Bone" → "Rag Bone" in 17.1% of articles |
| `<dd>/<dt>`, `<blockquote>`, `<caption>` | DROP | 0.79% combined; not worth a re-extraction |
| Dead sections | DROP by leaf heading | references/see also/notes-and-references/etc. |
| Redirects | KEEP as aliases | 36.6% of entries; Wikipedia's alias system |
| Section-redirect stubs | KEEP as aliases + opaque anchor | 14.0% of article HTML entries; emitted nothing before |
| Namespaces | DROP `User:` … `_assets_/` **only** | legacy `I/ M/ X/ -/` matched real titles and dropped 766 articles |

**The anchor is stored OPAQUE.** Only 59% of stub anchors join to a section this extractor
emits; the rest name heading ids spelled differently, or table rows. It is recorded, never
promised to resolve.

---

## 3. Store schema (SCHEMA_VERSION 3 — a rebuild, not a re-extract)

```sql
sources(id, name UNIQUE, kind, archive_date, source_sha256, ingested_utc)
articles(id, source_id→sources, path, title, last_edited, revision_id, UNIQUE(source_id,path))
chunks(id, article_id→articles, ordinal, section, kind, z BLOB)     -- zlib + preset dict
chunks_fts USING fts5(body, content='', contentless_delete=1, tokenize='porter unicode61')
aliases(id, source_id→sources, alias, target_path, anchor)
article_images(article_id→articles, ordinal, path)
meta(key, value)
```

**This exists in the code now** — the previous version of this document described a schema that
had not been written, and argued for it as though it had.

**Answering the partial-update question, honestly.** The SCHEMA supports partial refresh. The
BUILDER DOES NOT. An earlier draft of this section claimed otherwise, and that claim is retracted.

What is genuinely in place:

- `archive_date` lives on the SOURCE row, not once for the store, so a refresh cannot relabel
  articles it never touched. A single store-wide date would stamp 8.3M articles with a date they
  never had — the same defect as one date per article, one level up.
- `contentless_delete=1` is verified supported on SQLite 3.45.1. Without it a contentless index
  **cannot delete at all**, and a refresh would be impossible rather than merely unbuilt.

What is NOT in place, and would silently corrupt a refresh today:

- `build()` restarts article and chunk ids at 1 on every run, so a second run into an existing
  store collides.
- `sources` and `articles` use `INSERT OR IGNORE`, so a re-ingest is skipped, not applied.
- Nothing ever DELETEs from `chunks_fts`, so superseded text would keep being served.
- `UNIQUE(source_id, path)` cannot match across a NEW source row, so re-ingesting from a newer
  archive **duplicates every article** rather than updating it.

**Ticketed, each with an observable blocked-by:** #1635 (the refresh path), #1637 (page moves
duplicating articles), #1638 (upstream deletions never retired), #1639 (table-row retrieval
quality, unmeasured).

---

## 4. The structural control that was missing

The extractor lived outside the repository, outside pytest, outside the gate. **No test could
reach any capture rule**, which is why eleven defects survived to the edge of a four-hour run
and were found by hand.

The PURE rules now live at `tools/corpus/extract_rules.py` — they import nothing from the ZIM
ecosystem, so the GPL boundary is untouched; the single `import libzim` stays in a thin driver
outside the repo. They are pinned by **70 golden-fixture tests** over **10 real article pages**
frozen in `shared/tests/fixtures/corpus/` (185 KiB gzipped), one per defect found:
disambiguation, section stub, apostrophe stub, ampersand, exponent, nested-table infobox, list
article, content tables, ordinary prose, one-sentence stub.

Corpus test total: **126 passing** across extraction rules, builder, reader and dormancy.

The driver outside the repo is now version-controlled in its own git repository, records the
repo commit, a dirty-checkout flag and the SHA-256 of `extract_rules.py` in every shard
sidecar, and **refuses to start on an uncommitted checkout** — three hours of output that
cannot name its code version is three hours nobody can reproduce.

---

## 5. Revised projections

| | before review | now |
|---|---|---|
| Chunks | ~43M | **~78M** |
| Store size | ~23 GB | **~55 GB** |
| Extraction (8 shards) | ~3.7 h | **~3 h** |
| Build | ~35 min | **~2 h** |

Larger because materially more is captured: tables, list content, captions, and the 21.5% of
pages that previously vanished.

---

## 6. Known limits, stated rather than discovered later

1. Every rule is validated against **one archive**. Gutenberg's HTML differs and none of this
   is validated there.
2. Sampling gives rates, not censuses.
3. The partial-refresh path is **designed and schema-supported, never executed**.
4. Nine fixtures cover nine known defects; they cannot cover an unknown tenth.
5. Article identity keys on `path`. A Wikipedia page MOVE would appear as a new article and
   leave a stale duplicate. Detectable via revision id/title; nothing does so yet.
6. Nothing marks an article DELETED upstream — a refresh adds and replaces, never retires.
7. The relevance threshold for retrieval remains uncalibrated; it needs the built corpus.
8. Table rows are rendered as ` | `-joined text. Whether that retrieves well is unmeasured.

---

## 7. RETRACTION, 2026-09-23 after the extraction ran — the length floors

Three extraction defects were found by the #1641 session after the 3-hour extraction completed.
Tracing them showed all three are **one cause**: a length floor drops content when that content is
the only content in its scope. The floors are `MIN_CHARS = 110` (paragraphs and merged sections)
and the `len(text) >= 120` block floor in `_table_text`.

**Measured on the real archive, uniform stride sampling** (`B:/kiwix/work/probe_prose_loss.py`,
`B:/kiwix/work/probe_tables.py`):

| | |
|---|---|
| prose characters lost | **0.56%** (16,451 of 2,932,368) |
| articles losing **ALL** their prose | **18 of 922 — about 2%** |
| …still emitting other records, so invisible to `zero_record_entries` | **18 of 18** |
| articles losing every keep-eligible table | **15 of 250 — about 6%** |
| those losses caused by the 120-char block floor | **15 of 15** |

**What is retracted.** §2's justification for the paragraph floor — "only 1.26% of live paragraph
text falls under the floor" — measured VOLUME, and volume is the wrong quantity. The real archive
loses half a percent of characters and yet roughly one article in fifty loses every word it has.
`Euleptorhamphus_viridis` is the shape of it: 74 characters of prose, all dropped, so the store
holds an infobox and image paths for a fish and nothing saying what it is. Species and commune
stubs are a large population.

**Why the run's own numbers did not catch it.** `zero_record_entries` = 0.0146% is correct and
irrelevant here: an article that emits an infobox is not a zero-record entry, so the counter is
structurally blind to the entire class. A null result is only as good as the instrument that
produced it.

**Not yet fixed, deliberately.** The fix principle is that a floor may drop a fragment when better
content exists in the same scope but may never be the reason a scope emits nothing. Applying it
requires a re-extraction, and #1643 is held until #1641 records its accuracy baseline on the store
built from this extraction — re-extracting first would destroy the "before" the fix must be
measured against. Disposition rows 1e and 7e carry it.
