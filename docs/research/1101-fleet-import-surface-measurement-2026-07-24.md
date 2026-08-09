# #1101 — Coding fleet's real third-party Python import surface (measured)

**Scope:** read-only measurement. No files were written or committed in `C:/Users/mrbla/BlarAI` or `C:/Users/mrbla/agentic-setup`; no git state was touched in either repo.

**Bottom line up front:** the fleet's generated-code corpus shows almost no real third-party Python usage. This is not a sampling gap — it is a structural property of how the fleet is built: every Python project skeleton is generated with `dependencies = []` and an explicit "offline, zero third-party deps" mandate, and the only third-party packages the harness ever injects are `pytest` and `hypothesis`, hard-coded into the gate's own test-run command. A docset expansion aimed at "what the fleet actually imports" would currently be scoping against three packages, two of which the coder never chose.

---

## 1. Methodology

### 1.1 Locations examined

- `C:/Users/mrbla/agentic-setup/state/fleet-runs/*/` — 200 run directories.
- `C:/Users/mrbla/projects/*` — 27 project directories (each a real dispatched coding project's working tree).

### 1.2 What `fleet-runs/` actually contains (important negative finding)

I first explored the full directory-entry set across all 200 run folders (`find … -type f | basename | sort | uniq -c`). **`fleet-runs/*/` does not hold generated application source at all.** Every run folder contains only orchestration artifacts: `journal.log`, `acceptance.json`, `swap-progress.log`, `SUMMARY.txt`, `start-llm.log`, `scorecard.json`, `JOB_SUMMARY.txt`, `guest-oracle.json`, `wave-gates.log`, `context-packs.log`, per-step `run-fleet-<taskname>.log` logs, `static-pregate.log`, `oracle-qa.json`, `grade-clean.ini`, etc. There is no sandbox copy, diff, or patch of coder-written source anywhere under this tree.

Two exceptions, both **fixed oracle files reused verbatim across many runs**, not varying fleet output:
- `job-oracle-test_job_acceptance.py` — appears 58 times (one static Python acceptance-test oracle, same battery task, copied into each run's folder).
- `job-oracle-acceptance.job.test.mjs` — appears 7 times (the JS equivalent).
I did **not** count these toward the ranked table below — they are a hand/LLM-authored fixed test harness reused per run, not fleet-generated application code, and counting the same file 58 times would badly distort frequency.

I also found `import-probe-targets.json` / `import-probe-verdict.json` / `import-probe.log` (42 instances each) — an internal fleet QA step that checks whether the acceptance oracle's imports resolve against the coder's generated code. I parsed all 42 `import-probe-targets.json` files (109 total `kind: "py"` entries) expecting this might be a richer historical record of attempted imports (including from discarded/retried attempts). **It is not useful for third-party surface measurement**: every single resolved "module" in all 42 files is a first-party module name local to that project (`app`, `app.word_frequencies`, `app.report`, `flashcard_app`, `inventory_manager` — 3 distinct top-level names total across 109 entries). This tool checks first-party interface contracts (does `app.core.add_expense` exist with the right signature), not third-party library usage. Confirmed negative, not a gap.

**Conclusion: real generated Python source lives only under `C:/Users/mrbla/projects/*`.**

### 1.3 What I scanned in `projects/`

11 of the 27 project directories contain any `.py` files at all; the other 16 (`bill-splitter`, `bill-splitter-r2`, `blairs-lab`, `ecomwebsite`, `meridian-cafe`, `portfolio`, `water-tracker`, `battery-b3-budget-web`, `battery-b4-flashcards-cli`, `battery-b5-habit-web`, `battery-b7-util-trio`, `battery-b8-negative-carrier`, `Calc1`, `Hello-World`, `battery-b2-text-stats-archived-110745`, `battery-neg-n3`'s sibling web variants) are JS/Node or static-HTML projects (`package.json` + `app.js`/`.mjs`/`index.html`, no `.py` anywhere) or effectively empty scaffolds.

Projects with real Python (11): `battery-b1-expense-cli`, `battery-b2-text-stats`, `battery-b2-text-stats-archived2-135540`, `battery-b6-inventory-cli`, `battery-neg-n1`, `battery-neg-n2`, `battery-neg-n3`, `flashcards`, `jobhunt-eligibility`, `practice`, `seaquotes`.

- **97 `.py` files** found under these 11 projects (`find … -iname "*.py"`, excluding `.git/`, `venv/`, `site-packages/`, `__pycache__/`, `node_modules/` — no such vendored directories were actually present, the exclusion was precautionary).
- **Parsing method:** Python's `ast` module (via `C:/Users/mrbla/BlarAI/.venv/Scripts/python.exe`, Python 3.11.9 — the same interpreter version the BlarAI standing gate runs on), walking every `ast.Import` and `ast.ImportFrom` node and taking the top-level dotted-path segment (`import foo.bar` → `foo`; `from foo.bar import baz` → `foo`). Relative imports (`from . import x`, `level > 0`) were excluded — they can't name an external package by construction.
- **Classification:** a module name is `stdlib` if it appears in `sys.stdlib_module_names` (Python 3.11.9's own authoritative list, not a hand-maintained guess) plus `__future__`. Otherwise, it is `local`/first-party if it matches a top-level directory or `.py` file at that project's own root (e.g., `app`, `eligibility`, `inventory_manager`, `flashcard_app`, `cli`, `storage`, `main`, `consumer`, `mathutils`, `random_generator`) — these are the project's own package/module names, not installed dependencies. Everything else is `third_party`.
- 85 of the 97 files contained at least one import statement (the rest are empty `__init__.py` files or trivially small). **Zero parse errors** — all 97 files are valid Python 3.

---

## 2. Ranked third-party modules (the entire result set — only 3 exist)

| Rank | Module | Import count | Distinct files | Distinct projects | Projects |
|---|---|---|---|---|---|
| 1 | `pytest` | 29 | 27 | 6 | battery-b1-expense-cli, battery-b2-text-stats, battery-b2-text-stats-archived2-135540, battery-b6-inventory-cli, flashcards, jobhunt-eligibility |
| 2 | `hypothesis` | 6 | 6 | 4 | battery-b1-expense-cli, battery-b2-text-stats-archived2-135540, battery-b6-inventory-cli, seaquotes |
| 3 | `setuptools` | 1 | 1 | 1 | seaquotes (legacy `setup.py`, not runtime code) |

That is the complete ranked list — there is no "top 30" to show because only 3 distinct third-party module names occur anywhere in the 97-file corpus.

For contrast, stdlib usage across the same corpus is much broader: `__future__` (26), `sys` (15), `os` (15), `collections`/`json`/`typing`/`tempfile`/`subprocess` (7 each), `unittest` (6), `re`/`random` (5 each), `io`/`csv` (3 each), `pathlib` (2), `argparse`/`dataclasses`/`enum` (1 each) — 17 distinct stdlib modules vs. 3 third-party ones.

### Why the surface is this thin — a structural cause, not a measurement artifact

I checked *why* before assuming this was just a small sample:

1. **The fleet's own project skeleton bans third-party dependencies by design.** Every generated `pyproject.toml` (`battery-b1-expense-cli`, `battery-b2-text-stats`, `battery-b6-inventory-cli`, `flashcards`, `seaquotes`) carries the identical header comment: *"Minimal, clean Python project skeleton for the BlarAI dispatch fleet... a single importable package under app/, tests under tests/, **zero third-party dependencies (so it builds and tests OFFLINE out of the box)**."* Every one of them declares `dependencies = []` in `[project]`. `jobhunt-eligibility`'s description literally says "offline, stdlib-only."
2. **`pytest` and `hypothesis` are harness-injected, not coder-chosen.** `C:/Users/mrbla/agentic-setup/scripts/fleet-lib.ps1:2519` hard-codes the gate's Python test command as `uv run --no-project --with pytest --with hypothesis pytest -q "<test file>"` — these two packages are installed ephemerally by the gate for every Python candidate run, regardless of what the task asked for. Their appearance in the corpus reflects the harness's fixed test tooling choice, not an emergent pattern of what coding tasks need.
3. **Same story on the JS side, for completeness (not counted in the table above — see §3):** every `package.json` under `projects/` (`battery-b3-budget-web`, `battery-b7-util-trio`, `bill-splitter`, `bill-splitter-r2`, `blairs-lab`, `meridian-cafe`, `tip-splitter-v3`) has **empty** `dependencies` and `devDependencies` — the "zero third-party deps, build offline" constraint is applied uniformly, not just to Python.
4. One indirect, forward-looking signal worth naming: `fleet-lib.ps1:1484`'s language-detection regex recognizes `pandas`, `numpy`, `flask`, `django`, `fastapi`, `pip` as Python-language cues in a task prompt. That means the harness *anticipates* these libraries could show up in a future task description, even though none has ever actually produced code importing them in this corpus. This is a hint about what the fleet's authors expected demand to look like, not evidence of realized demand.

---

## 3. Explicitly out of scope / not counted

- **JS/Node imports** — not parsed or counted. 7 of the 27 project directories are JS/web apps (`bill-splitter`, `bill-splitter-r2`, `blairs-lab`, `meridian-cafe`, `tip-splitter-v3`, `battery-b3-budget-web`, `battery-b7-util-trio`) plus `ecomwebsite`/`portfolio`/`water-tracker`/`Calc1`/`Hello-World`/several battery web variants that are static HTML or Node with no declared deps. I confirmed their `package.json` dependency lists are empty (§2.3), so even a JS-inclusive count would add nothing here — but a genuinely JS-heavy project elsewhere would not be reflected in this report.
- **The two fixed oracle files** (`job-oracle-test_job_acceptance.py` ×58, `job-oracle-acceptance.job.test.mjs` ×7 across `fleet-runs/`) — excluded as duplicated fixed harness code, not varying fleet output (see §1.2).
- **`fleet-runs/*` orchestration artifacts** (`journal.log`, `acceptance.json`, `*.log`, `*.json` QA records) — read enough to confirm no generated source lives there (§1.2), not parsed for imports beyond the `import-probe-targets.json` check, which is a first-party interface-contract checker, not a third-party import record (§1.2).
- **Archived/superseded project variants** — `battery-b2-text-stats-archived-110745` (0 `.py` files, effectively empty) was included in the scan but contributed nothing; `battery-b2-text-stats-archived2-135540` (3 files) was included and did contribute (`pytest`, `hypothesis`).
- **Git history** — I measured only the current on-disk working-tree state of each `projects/*` directory, not prior commits/branches. A project that once imported a library and later had that code removed would not show up here. I did not audit `git log -p` across 27 repos for this measurement.
- **Binary/vendored code** — none was found (no `venv/`, `site-packages/`, or `node_modules/` directories existed under any scanned path), so the exclusion filters in the script never actually triggered, but they were in place as a precaution.
- **agentic-setup's own harness code** (`fleet-lib.ps1`, dispatch scripts, etc.) — I read parts of this to explain *why* the corpus looks the way it does (§2, "structural cause"), but did not treat the harness's own Python/PowerShell tooling as "fleet-generated code" and did not include its imports in the ranked table. That would measure the fleet-builders' tooling, not what the fleet produces.

---

## 4. Recommendation

Given the measured evidence, I would **not** recommend scoping a docset expansion to "the fleet's historically observed third-party libraries" as currently written — there are only 3 such libraries, and 2 of them (`pytest`, `hypothesis`) are already well-documented, stable, and low-risk enough that a generic docset almost certainly already covers them adequately; the third (`setuptools`) is a build-backend, not something a coding task would need deep API docs for.

The real finding for #1101 is upstream of "which libraries": **the fleet is currently structurally forbidden from reaching for third-party libraries at all**, by the `dependencies = []` skeleton mandate. Two honest paths forward, in order of how directly they follow from what was measured:

1. **If the offline/zero-deps constraint is intentional and staying** (plausible — it guarantees the gate runs without network access and matches BlarAI's own local-first posture), then a third-party-library docset expansion has no real task to serve yet, and #1101 should wait until/unless that constraint changes for some project class (e.g., web-facing battery tasks that might legitimately need a request/HTTP client, a templating engine, or a small web framework instead of hand-rolled `http.server`/vanilla JS).
2. **If the LA wants the docset to anticipate near-future demand rather than reconstruct current demand**, the one piece of forward-looking evidence I found is the harness's own language-detection keyword list (`pandas`, `numpy`, `flask`, `django`, `fastapi`, `pip` — `fleet-lib.ps1:1484`). That is a designed-in expectation, not a measurement, so I'm flagging it as a lead worth someone's judgment call, not asserting it as the answer this ticket asked for.

This is a technical/scoping judgment call for the LA (does the docset expansion target *realized* fleet behavior or *anticipated* future task shapes), not something I'm deciding here — I'm reporting the measured gap between "corpus size expected" and "corpus size found," and naming why.
