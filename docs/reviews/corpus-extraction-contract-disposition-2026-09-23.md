# Disposition — adversarial review of the corpus extraction contract (#1616)

**Reviewed:** the extraction contract and pipeline, 2026-09-23, before a ~3-hour run.
**Reviewer:** independent agent; ran the real code against the real 118.67 GiB archive with
full-span stride sampling. The author did not review their own work; the reviewer wrote no fixes.
**Outcome:** the run was BLOCKED. **20 findings: 15 FIXED, 3 REJECTED, 2 DEFERRED.**

> ## CORRECTION, 2026-09-23 after the extraction ran — two rows below were wrong
>
> The #1641 session found three extraction defects this review missed, and tracing them showed
> **two of my own dispositions rested on instruments that could not see the defect they cleared.**
> Measured against the real archive with uniform stride sampling: **about 2% of articles carrying
> prose lose ALL of it** (18 of 922 sampled), and **every one of those 18 still emits other
> records**, so `zero_record_entries` — the counter I used to certify row 1d — is structurally
> blind to the entire class. Separately **about 6% of articles holding keep-eligible tables lose
> every one** (15 of 250), and the cause is the 120-character block floor in 15 of 15 cases.
>
> Row **1d** stays FIXED for the one article it names and is no longer evidence for the class;
> row **7e** is **RETRACTED from REJECTED to DEFERRED** — the finding it dismissed was real.
> The new row **1e** carries the class. Both corrections are recorded at #1643, and the lesson is
> that a null result is only as good as the instrument: 0.0146% zero-record and "1.26% of
> paragraph text" are both true and both answer a question nobody asked.
>
> Probes retained: `B:/kiwix/work/probe_prose_loss.py`, `B:/kiwix/work/probe_tables.py`.

A deferral is a claim and carries the burden of naming a predicate a later session could observe.
The two deferrals below name #1643 and the baseline that must exist before a fix can be judged;
they are held for SEQUENCING, not convenience — re-extracting before that baseline is recorded
would destroy the "before" the fix has to be measured against. Work that genuinely belongs to a
later limb is ticketed in the contract §6, not here.

Commits: `1d746070` (tier lands dormant), `30056dc4` (run sidecar), `acc8c896` (per-entry
decision moves inside the gate; stub fallback).

```disposition
1a-section-redirect-stubs-emit-nothing | FIXED | 1d746070 — _refresh_target + records_for_entry; 14.0% of article-namespace HTML entries are section redirects reporting is_redirect==False with no prose, falling between both branches. Now emitted as aliases with an opaque anchor. Pinned by TestSectionRedirectStubs.
1b-list-shaped-articles-emit-nothing | FIXED | 1d746070 — `_passages` merges list runs; "List of hotels in the United Kingdom" had 10,999 visible chars and produced nothing. Pinned by TestPagesDoNotVanish.
1c-run-metadata-cannot-see-its-own-omissions | FIXED | 30056dc4 — `zero_record_entries` counter in the shard sidecar; articles were counted only `if ordinal`, so the run could not distinguish 6.8M articles from 2.1M silently dropped pages.
1d-one-sentence-stubs-still-vanish | FIXED | acc8c896 — `STUB_MIN_CHARS` lead-section fallback; the named survivor "Ensomned, U.S. Virgin Islands" (89 chars, under the 110 floor) does now emit. Pinned by TestStubArticlesSurvive. SCOPE CORRECTED 2026-09-23: the "0.04% zero-record" evidence originally cited here does NOT support the general claim, because the fallback is gated on `ordinal == 0` and infobox facts and captions increment `ordinal` before any prose is considered — so an article with an infobox never reaches it, and is not a zero-record entry either. See row 1e; #1643.
1e-prose-lost-while-the-article-still-emits | DEFERRED | #1643 — about 2% of prose-carrying articles lose ALL their prose while emitting facts/captions/images, so the article survives as an infobox with nothing saying what it is (`Euleptorhamphus_viridis`, 74 chars, all lost). 18 of 922 uniformly sampled; 18 of 18 invisible to `zero_record_entries`. Same root cause as 7e: a length floor drops content that is the only content in its scope. blocked-by: #1641 must record its accuracy baseline on the store built from `B:/kiwix/work/shards` before the floors change, because the fix is judged by a before/after on one golden set and re-extracting first destroys the before.
2-sup-stripping-deletes-unit-exponents | FIXED | 1d746070 — `_SUP_CHROME` + `_script_repl`; stripping every sup turned km² into km and m/s² into m/s, producing clean prose asserting falsehoods. Citation sups all carry a reference-ish class, content sups never do (3,293 vs 25, zero overlap). Folded in without a separating space, since the naive fix yields "m/s 2". Pinned by TestExponentsSurvive.
3-infobox-truncated-at-nested-table | FIXED | 1d746070 — `_balanced_table` depth counting replaces a non-greedy closing-table match that truncated 14.5% of infoboxes, losing 91 rows across 37 sampled articles. All infoboxes rendered, not only the first.
3b-infobox-colspan-rows-dropped | FIXED | 1d746070 — 926 single-cell colspan rows were dropped as structure, but that is where infoboxes put result lines. Kept within a 12..200 char band excluding headers and spacers.
7a-ordinary-tables-dropped-entirely | FIXED | 1d746070 — `_table_text`; non-infobox tables carry 17.84% of live prose (election results, discographies, climate rows, sports records). Verified 232 of 4,000 sampled articles yield table blocks. Pinned by TestTableCapture.
7b-captions-unsearchable-and-images-unaddressable | FIXED | 1d746070 — `_figures` pairs each caption with the image in the same figure block; `_all_images` records every path at article scope. Captions were metadata, never indexed, and 30.2% sat in sections emitting no chunk. Measured on the fixtures, 9 of 11 images in one article sit outside any figure block, including its headline photograph.
8a-ampersand-deleted-not-decoded | FIXED | 1d746070 — `html.unescape` in `_clean`; entities were replaced with a space, turning "Rag & Bone" into "Rag Bone" and the taxonomic authority "Sakamoto, Iino & Ohkuma 2017" into a different authority. 17.1% of articles affected.
8b-legacy-namespace-prefixes-drop-real-articles | FIXED | 1d746070 — `I/ M/ X/ -/` are legacy ZIM prefixes absent from this archive; they matched real titles containing a slash and dropped 766 entries including I/O_virtualization and M/M/1_queue. Pinned by TestNamespaceFilter.
8c-builder-silently-discards-every-alias | FIXED | 1d746070 — record-kind dispatch with `unknown_kind` and `malformed` counters replaces a bare `except: continue` that ate all 4,327 aliases in a 400-article trial, ~10M projected. Pinned by shared/tests/test_corpus_builder.py.
8d-contract-figures-were-raw-byte-ratios-and-wrong | FIXED | acc8c896 — contract §1 rewritten from uniform full-span sampling. The cause was one flaw: the sampling strode but stopped after N hits, so it only ever saw the first 7% of a 30.1M-entry archive. Tables "420%" is 81% by text, list items "344%" is 119%, infoboxes "73%" is 60.7%, redirects "56%" is 36.6%.
6-pre-dating-fraction-misstated | FIXED | acc8c896 — "35.3% of articles predate the archive build" was the fraction older than the calendar YEAR. The real figure is 99.2%; every article necessarily predates the dump. The correction strengthens the per-article-date decision.
9-no-test-reaches-any-capture-rule | FIXED | acc8c896 — the pure rules live in `tools/corpus/extract_rules.py` (importing nothing from libzim, so the GPL boundary is unaffected) and `records_for_entry`/`alias_record` moved there from the untested driver. 10 golden fixtures of real article HTML, 126 corpus tests.
4a-dead-section-leaf-notes-and-references | FIXED | 1d746070 — leaf heading "notes and references" was indexed as live prose at ~0.7% incidence; added with two variants to `_DEAD_SECTIONS`.
4b-section-breadcrumbs | REJECTED | Attacked and unbroken. Lead section empty in 414/414 articles; zero headings of any level nested inside any table, verified with a real tag stack rather than a regex; deepest real ancestry reconstructed correctly across 959 distinct crumbs; no dead-section ancestor leaked through the leaf test. No structural change is warranted because no input produced a wrong breadcrumb.
5-redirect-resolution | REJECTED | Attacked and unbroken. 2,918 stride-sampled redirects resolved 100% with zero exceptions, zero chains, zero self-aliases, zero empty titles. 2 of 2,918 target a `Category:` page and are correctly filtered by `_NON_ARTICLE`. The gap was elsewhere, at finding 1a.
3c-css-leakage-into-infobox-facts | REJECTED | The author raised this as open question 9 after one sample leaked a CSS fragment. Searched every emitted `key = value` line across 255 real infoboxes for `/*`, `mw-parser`, `@media`, `font-size:`, `px`, hex colours, `!important` and `display:` — zero hits. `_CSS_NOISE` works. The 40-row cap was hit 0 times in 255 infoboxes and the value>300 filter dropped 2 rows in 3,129.
7e-min-and-max-chars-were-guessed | DEFERRED | #1643 — **RETRACTED FROM REJECTED 2026-09-23; the finding was real.** The rejection measured the floor's cost as 1.26% of live paragraph TEXT and characterised the losses as table legends and "Last updated:" stubs. Volume was the wrong quantity: the real archive loses only 0.56% of prose characters and yet about 2% of articles lose every word they have, and the 120-char floor in `_table_text` drops every table in about 6% of table-bearing articles (15 of 15 losses traced to it; `Ain't_My_Bitch` chart block = 102 chars). A per-character average cannot see a per-article loss. MAX_CHARS=2400 is untouched by this and stands. blocked-by: #1641 must record its accuracy baseline before `MIN_CHARS`/`_table_text` change, so the fix is measured before/after on one golden set rather than asserted.
```

## Rejected design proposals, with the argument

**A per-item length threshold for list items.** The contract proposed keeping `<li>` items over
60 characters. Measured against the population that actually vanishes, that is the wrong
denominator: disambiguation entries are ~24 characters by construction, so a 60-char floor
rescues 15 of 29 vanished articles. Replaced by merging list RUNS into passages — a
disambiguation page's value is the whole list as one retrievable passage.

**A class detector for list-shaped articles.** Measured reach: "disambiguation" markers appear
in 20 of 29 vanished articles and in 3 of 334 normal ones. A detector catches 69% of the
population, still needs the general rule for the remainder, and creates a second code path
exercised by 7% of articles — the path least likely to be tested.

## Honest limits of this review

- Every rule is validated against ONE archive, `wikipedia_en_all_maxi_2026-08`. Gutenberg's HTML
  differs and none of this is validated there.
- The reviewer sampled; it did not process all 30,142,538 entries. Rates are estimates with
  sampling error, not censuses.
- Ten golden fixtures cover ten known defects. They cannot cover an unknown eleventh — that is
  what the next review is for.
- `contentless_delete=1` is present and the schema uses it, but **no partial refresh has been
  performed**. The update path is designed, not proven. See contract §6 and the tickets it names.
