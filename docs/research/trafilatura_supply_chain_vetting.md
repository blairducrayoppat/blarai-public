# Supply-Chain Vetting: `trafilatura` Extraction Stack (9 packages)

**Scope:** UC-003 Cleaner v1 (ADR-030 §4), Vikunja #655 Stage B — the HTML→article
extraction dependency block for `services/cleaner/`.
**Author:** Stage-B cleaner-pipeline builder agent, 2026-06-10.
**Status:** VETTED + **INSTALLED** — Lead-Architect approval granted 2026-06-10 at the
#655 program comprehension gate (trafilatura + 9 hash-pinned packages). The sanctioned
install is `pip install --require-hashes -r requirements/ingest-cleaner.txt` into the
shared `.venv`. This is the largest dependency block BlarAI has accepted since the
OpenVINO stack, and the first containing a C extension (`lxml`) whose job is parsing
hostile bytes — both facts shaped the posture in §2.

---

## 1. Canonical Package Identity (root package)

| Field | Value |
|---|---|
| PyPI name | `trafilatura` |
| Pinned version | **2.1.0** |
| Release date | 2026-06-07 (3 days before vetting — freshness noted in §5.1) |
| GitHub | https://github.com/adbar/trafilatura |
| Author | Adrien Barbaresi (BBAW — Berlin-Brandenburg Academy of Sciences) |
| License | Apache-2.0 (PyPI `license_expression`, confirmed) |
| Python requires | >=3.10 (BlarAI runs 3.11.9 — met) |
| Wheel | `trafilatura-2.1.0-py3-none-any.whl`, 134,600 B, pure Python |

trafilatura is the de-facto standard Python web-article extraction library
(boilerplate removal + title/author/date metadata), used by large-scale corpus
projects (HuggingFace datasets tooling, academic web-corpus pipelines). It was chosen
over `justext` (+3 packages, no metadata extraction) and `readability-lxml` (+5, no
date/byline) on extraction quality — the knowledge bank stores this text for decades
(ADR-030 §Rejected alternatives, LA-ratified 2026-06-10).

## 2. Architecture and the EXTRACTION-ONLY posture (binding)

trafilatura is two things in one package:

1. **An extraction engine** — `extract()` / `bare_extraction()` / `extract_metadata()`
   operate on HTML **strings the caller already holds**. Pure string/tree processing
   over lxml. This is the ONLY part BlarAI uses.
2. **A fetching convenience layer** — `trafilatura.downloads` with `fetch_url()` /
   `fetch_response()` (urllib3-based, optional pycurl), plus crawling/spider modules.
   This part is **FORBIDDEN in BlarAI runtime code**. Fetching belongs exclusively to
   the single Policy-Agent-gated egress door (`shared/security/guarded_fetch.fetch_external`,
   W4 — the Cleaner's fetch limb is unwritten until Stage C, per the ADR-030 §8
   activation preconditions). A library convenience fetcher would bypass
   PA adjudication, the exfil screen, the kill-switch, and SSRF validation in one call.

**Enforcement is layered, not aspirational** (ADR-030 §4):

- the runtime egress guard (armed at launcher entry) denies + latches on any
  off-allowlist socket/DNS attempt — a stray `fetch_url` call would trip it;
- the static-scan lock in `tests/security/test_no_external_egress.py`
  (`test_runtime_never_uses_trafilatura_fetch`) fails the standing gate if any runtime
  module imports `trafilatura.downloads` or references `fetch_url`/`fetch_response`;
- an import-time lock asserts that importing `services.cleaner.src.pipeline` opens no
  sockets.

None of the optional extras (`all`: brotli/pycurl/py3langid/zstandard; `eval`;
`docs`; `dev`) are installed — the core 9-package tree only.

## 3. Transitive Dependency Tree

Resolved with `pip install --dry-run --report` against the live `.venv`
(Python 3.11.9, 2026-06-10). Nine packages are NEW; the remainder of the tree is
already satisfied by the venv:

```
trafilatura 2.1.0                       NEW  (pure py)
├── courlan >=1.4.0      → 1.4.0        NEW  (pure py — URL cleaning/normalization)
│   ├── babel >=2.16.0                  satisfied (2.18.0)
│   ├── tld >=0.13       → 0.13.2       NEW  (pure py — TLD name validation, bundled Mozilla list)
│   └── urllib3 <3,>=1.26               satisfied (2.6.3)
├── htmldate >=1.10.0    → 1.10.0       NEW  (pure py — publication-date extraction)
│   ├── charset_normalizer >=3.4.0      satisfied (3.4.4)
│   ├── dateparser >=1.1.2 → 1.4.0      NEW  (pure py — natural-language date parsing)
│   │   ├── python-dateutil >=2.7.0     satisfied (2.9.0.post0)
│   │   ├── pytz >=2024.2               satisfied (2025.2)
│   │   ├── regex >=2024.9.11           satisfied (2026.1.15)
│   │   └── tzlocal >=0.2  → 5.3.1      NEW  (pure py — local timezone lookup)
│   │       └── tzdata (Windows)        satisfied (2025.3)
│   ├── lxml >=5.3.0     → 6.1.1        NEW  (C EXTENSION — see §5.2)
│   └── python-dateutil >=2.9.0.post0   satisfied
├── justext >=3.0.2      → 3.0.2        NEW  (pure py — paragraph-level fallback extractor)
│   └── lxml[html_clean] >=4.4.2
│       └── lxml_html_clean → 0.4.5     NEW  (pure py — HTML cleaner split out of lxml)
├── certifi                             satisfied (2026.1.4)
├── charset_normalizer >=3.4.0          satisfied
├── lxml >=6.1.1         → 6.1.1        NEW  (shared with htmldate/justext)
└── urllib3 <3,>=1.26                   satisfied
```

No package in the tree is a cloud SDK, telemetry library, or ML framework. The only
network-capable machinery is `urllib3` (already in the venv, used by trafilatura's
*forbidden* downloads module only) and `certifi` (CA bundle, inert without a fetch).

**Already-satisfied transitives — now pinned (post-review fix, 2026-06-10):**
`certifi`, `charset-normalizer`, `urllib3`, `babel`, `python-dateutil`, `pytz`,
`regex`, and `tzdata` are present in the shared venv as transitives of dev/agent
tooling — they are NOT BlarAI-declared. The original `requirements/ingest-cleaner.txt`
block pinned only the 9 new packages, so a fresh-environment
`pip install --require-hashes` could not resolve. The file now carries hash-pinned
entries (wheel + sdist sha256, PyPI JSON API 2026-06-10) for all of them at the
shared venv's exact versions, completing the fresh-env closure. One-line identity
notes:

- **certifi 2026.1.4** — Mozilla CA bundle (MPL-2.0); inert data without a fetch path.
- **charset-normalizer 3.4.4** — encoding detection (MIT); ships mypyc-compiled
  wheels — the cp311-win_amd64 wheel hash is pinned alongside the pure-python
  fallback wheel and the sdist.
- **urllib3 2.6.3** — HTTP client (MIT); reachable only via trafilatura's
  *forbidden* downloads module — the extraction-only posture (§2) keeps it cold.
- **babel 2.18.0** — locale/CLDR data for courlan (BSD-3-Clause).
- **python-dateutil 2.9.0.post0** — date parsing utilities (Apache-2.0/BSD dual).
- **pytz 2025.2** — historical timezone database (MIT).
- **regex 2026.1.15** — extended regex engine for dateparser (Apache-2.0);
  C-extension wheels — cp311-win_amd64 pinned, sdist fallback.
- **tzdata 2025.3** — IANA timezone data on Windows (Apache-2.0); pure data.
- **six 1.17.0** — Py2/3 compat shim, python-dateutil's dependency (MIT).
  NOT on the review's 8-package list: it never surfaced in satisfied-venv
  dry-runs and was caught by the `--ignore-installed` fresh-env simulation,
  which refused on the unpinned requirement — pinned to complete the closure.

Their DEEP vetting (maintainer posture, release cadence, risk assessment) is not
re-run here: all nine are long-established ecosystem staples already living in the
shared venv and are covered by the Sprint-16 dependency-pinning review for that
venv — see `docs/sprints/sprint_16/dependency_pinning_rationale.md`. This document
adds supply-chain *identity* (exact version + artifact hashes) on top of that
standing rationale; §5's per-package risk work remains scoped to the 9 packages
NEW to the venv.

## 4. Pinned + Hash-Checked Requirements

The canonical block lives at `requirements/ingest-cleaner.txt` (wheel sha256 AND
sdist sha256 per package; lxml's hash is the `cp311-cp311-win_amd64` C-extension
wheel that matches BlarAI's stack). Hashes were taken from the PyPI JSON API on
2026-06-10 and cross-checked against the `pip --dry-run --report` resolution —
both sources agree on every wheel hash.

### 4.1 Version Selection Rationale

All nine versions are exactly what pip resolves today from the latest stable
releases — no downgrades, no floor-riding:

- **trafilatura 2.1.0** — latest stable; the version the LA approved by name.
- **courlan 1.4.0 / htmldate 1.10.0** — the exact floors trafilatura 2.1.0 declares
  (`>=1.4.0` / `>=1.10.0`), also the latest stable of each.
- **lxml 6.1.1** — the exact floor trafilatura declares (`>=6.1.1`), latest stable;
  `lxml_html_clean 0.4.5` requires `lxml>=6.1.1`, consistent.
- **dateparser 1.4.0, tld 0.13.2, tzlocal 5.3.1, justext 3.0.2,
  lxml_html_clean 0.4.5** — latest stable within their declared constraints.

## 5. Supply-Chain Risk Assessment (per package)

OSV (Open Source Vulnerabilities) database queried 2026-06-10 for every pinned
version: **0 known advisories across all 9**.

### 5.1 trafilatura 2.1.0 — release freshness — LOW

Actively maintained (multiple releases per year, responsive tracker, academic
backing). The pinned release is **3 days old** at vetting time. A just-released
version has had minimal community soak. Mitigations: hash-pinning freezes the exact
audited artifact; the wheel is pure Python (auditable); the package's network
machinery is forbidden and statically scanned, so the highest-risk code path is dead
on arrival in BlarAI. Accepted rather than pinning the older 2.0.0: 2.1.0 is the
version that declares the lxml 6.x floor this block standardizes on, and is the
LA-approved name.

### 5.2 lxml 6.1.1 — C extension parsing hostile bytes — THE LARGEST SURFACE (YELLOW)

Say it plainly: **lxml is the largest new attack surface BlarAI has accepted since
OpenVINO.** It is a 4 MB binary wheel bundling libxml2 + libxslt (C code), and the
Cleaner's whole job is feeding it **attacker-authored HTML**. libxml2 has a long
historical CVE record (parser memory-safety bugs); lxml 6.1.1 itself has 0 open OSV
advisories, but the class of risk is structural, not incidental.

Mitigations, in order of weight:

1. **Guest-homed parsing (ADR-030 §3) — a Stage-C deliverable, NOT yet live.** When it
   lands, hostile *web* bytes are parsed inside the Hyper-V VM, never in the host
   process that holds the unsealed DEK — a parser compromise is contained by the VM
   boundary. **Interim state, explicit (LA verdict 2026-06-10):** until the Stage-C
   guest parser exists, Stage B **host-parses operator-consented LOCAL HTML files**
   (`/ingest <path>` on the operator's own file, under ADR-030 §2's path-scope
   controls) — an accepted interim residual for operator-initiated file ingest, given
   the hash-pinned artifacts (§4) and the armed egress locks (§2). Hostile *web* bytes
   never get the interim: the fetch path does not exist until Stage C writes it
   (ADR-030 §8 — dormancy by structural absence). **Stage C guest-homed parsing is the
   durable fix.** Host-side parsing otherwise remains limited to operator-pasted text
   (the operator's own clipboard) — and the paste path (`clean_text`) does no HTML
   parsing at all.
2. **Hash-pinned binary:** the exact cp311-win_amd64 wheel is frozen; a tampered
   re-upload cannot install.
3. **No XSLT, no remote DTDs:** the Cleaner uses extraction only; trafilatura does
   not enable network entity resolution, and the egress guard would deny it anyway.
4. **Maintained upstream:** lxml dev team has a decades-long release record and ships
   security updates promptly; BSD-3-Clause.

### 5.3 Author concentration: trafilatura / courlan / htmldate — NOTE

Three of the nine packages share one maintainer (Adrien Barbaresi). A compromise of
that one PyPI account would touch a third of the tree in a single release cycle.
Hash-pinning closes the silent-update vector; any future version bump re-runs this
vetting. Institutional backing (BBAW) and a multi-year public release history lower
the probability. Accepted.

### 5.4 dateparser 1.4.0 — Scrapinghub/Zyte, large locale surface — LOW

BSD-3-Clause, maintained by Zyte (Scrapinghub), 300 KB wheel dominated by locale
data tables. Pure Python. Its job here is narrow: htmldate consults it for fuzzy
date strings. No known advisories on the pinned version (a historical ReDoS,
CVE-2022-24439-adjacent class, was fixed years before 1.4.0).

### 5.5 justext 3.0.2 — low cadence — LOW

BSD-2-Clause. 837 KB wheel that is mostly bundled language stoplists (data, not
code). Release cadence is slow (3.0.2 is from 2025-02) but the algorithm is stable
by design — it is trafilatura's fallback extractor, not a moving part. The kagiapi
precedent applies: thinness/stability reduces blast radius; hash-pinning removes the
silent-compromise vector.

### 5.6 tld 0.13.2 — bundled Mozilla TLD list; triple license — LOW

Ships a snapshot of the Mozilla public-suffix list (data freshness is a correctness
concern for courlan's URL validation, not a security one). Triple-licensed
`MPL-1.1 OR GPL-2.0-only OR LGPL-2.1-or-later` — an OR-license where BlarAI elects
the **LGPL-2.1-or-later** terms (dynamic import of an unmodified library; no
copyleft obligations attach to BlarAI's closed personal build).

### 5.7 tzlocal 5.3.1 / lxml_html_clean 0.4.5 — trivial — PASS

tzlocal: MIT, 18 KB, single-purpose (local timezone name), depends on tzdata on
Windows (already satisfied). lxml_html_clean: BSD-3-Clause, 14 KB, the HTML
sanitizer split out of lxml core, maintained under the lxml umbrella; justext pulls
it via `lxml[html_clean]`.

### 5.8 Licenses — PASS

Apache-2.0 (trafilatura, courlan, htmldate), BSD-3-Clause (lxml, lxml_html_clean,
dateparser), BSD-2-Clause (justext), MIT (tzlocal), MPL/GPL/LGPL-triple (tld, LGPL
elected). All permissive or weak-copyleft-compatible for a closed personal build.

## 6. Summary Verdict

| Criterion | Result |
|---|---|
| Canonical packages on PyPI | PASS — all 9 are the canonical, multi-year-history artifacts |
| Dependency footprint | PASS — 9 new, tree fully enumerated, no surprises beyond it |
| Licenses | PASS — §5.8 |
| Hash-pinnable | PASS — wheel + sdist hashes locked in `requirements/ingest-cleaner.txt` |
| OSV advisories (pinned versions) | PASS — 0 across all 9 (queried 2026-06-10) |
| C-extension exposure | YELLOW — lxml parses hostile bytes; mitigated by hash-pinning today + Stage-C guest-homed parsing (interim: host-parses operator-consented LOCAL files only — §5.2) |
| Network machinery in tree | YELLOW — trafilatura.downloads exists; FORBIDDEN + statically scanned (§2) |
| Release freshness | LOW — trafilatura 2.1.0 is 3 days old; hash-pinned (§5.1) |
| Author concentration | NOTE — 3/9 packages one maintainer; hash-pinned (§5.3) |

**Recommendation (executed):** adopt under the hash-locked block with the
extraction-only posture enforced by the standing gate. The two yellow findings are
structural to the feature (you cannot extract articles without an HTML parser; the
best extractor ships a fetcher) and are mitigated by containment, pinning, and the
static scan — not by hope.

LA approval was granted 2026-06-10 (#655 comprehension gate); this document is the
adoption record.
