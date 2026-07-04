# Cleaner v1 — First Real-Page Validation Record (2026-06-10)

**Scope:** UC-003 Cleaner v1 (`services/cleaner/src/pipeline.py`, `CLEANER_VERSION 1.0.0`),
Vikunja #655 Stage B. This is the repo-side record of the first real-page run — previously
held only in ticket comments; promoted to the repo per the testing-data capture rule
(unrecorded test results are an incomplete task) at the LA verdict 2026-06-10.

## Environment

| Field | Value |
|---|---|
| Hardware | Intel Core Ultra 7 258V (Lunar Lake); CPU-only — no GPU/NPU involvement (pure text pipeline, no model) |
| Python | 3.11.9 (project `.venv`) |
| Extraction stack | trafilatura 2.1.0, lxml 6.1.1 (hash-pinned, `requirements/ingest-cleaner.txt`) |
| Pipeline commit | `35e6142` (branch `feat/uc003-cleaner-pipeline`) |

## Input

| Field | Value |
|---|---|
| File | `userdata/unifi-os-root-bug-20260610.html` (gitignored `userdata/` — the artifact stays on the dev box, this record is its identity) |
| Raw size | 92,152 bytes (92,144 chars after strict UTF-8 decode) |
| Source | BleepingComputer article "Critical UniFi OS bug lets hackers gain root without authentication" |
| Provenance | Fetched **dev-side** on 2026-06-10 by the development session (Claude dev tooling), NOT through any BlarAI runtime path — the runtime fetch limb does not exist (ADR-030 §8, dormancy by structural absence) |

## Method

Strict UTF-8 decode of the raw bytes → `clean_html(raw)` (no `source_url` passed) →
verdict + metadata read off the returned `CleanResult`. Re-run for determinism.
Re-verified from disk against the pipeline at `35e6142` on 2026-06-10 (this record's
numbers are the re-measured values).

## Results

| Metric | Value |
|---|---|
| Verdict (`status`) | `clean` |
| Confidence | 1.0 |
| Word count | 666 |
| Title | "Critical UniFi OS bug lets hackers gain root without authentication" |
| Byline | Bill Toulas |
| Published date | 2026-06-08 |
| Cleaned text | 4,480 chars |
| Extraction ratio | 4.86% (4,480 cleaned chars / 92,144 raw chars — the pipeline's char-based ratio axis; supersedes the 4.87% rounding in the ticket comment) |
| Reasons | `()` — no quarantine floor tripped |
| Determinism | Re-runs byte-identical (`CleanResult` equality holds across repeated invocations) |

The page lands comfortably clear of every conservative v1 floor (80-word minimum,
0.2% ratio alarm, 0.5 confidence floor): a typical real article page is ~1–5%
text-to-raw, and this one sits mid-range at 4.86%.

## Known imperfection (tracked)

The **trailing sponsored-content block is retained**: the cleaned text ends with the
page's Picus whitepaper call-to-action ("...The Picus whitepaper shows how breach and
attack simulation tests your SIEM and EDR rules... Get the whitepaper"). trafilatura
treats the in-article sponsor block as body text. Tracked as **#658 item 1** (Cleaner
extraction-quality backlog). It is a knowledge-quality defect, not a security one —
the content is still untrusted, datamarked, and operator-reviewed at approval.

## What is NOT measured

- **Single page, single outlet, single template** (n=1, BleepingComputer). No claim of
  extraction quality across the diversity of real news layouts.
- **No fetch path.** The input was fetched dev-side; the runtime fetch limb is
  unwritten until Stage C (ADR-030 §8). Nothing here exercises `guarded_fetch`, PA
  adjudication, the exfil screen, or any egress control.
- **Quarantine floor calibration.** The v1 floors were tuned on the 7-fixture synthetic
  corpus (`docs/performance/cleaner_pipeline_2026-06-10.json`); this run validates one
  real page against them but does not recalibrate. Recalibration against a real-page
  corpus is named in the journal fragment's Next.
- **Latency/throughput.** No timing was captured on this run; the synthetic-corpus
  timings (~2.1 ms/article, fixtures far smaller than real pages) live in the JSON
  record above and do not transfer to 92 KB real pages.
- **Co-resident cost** (run standalone, no model loaded).
