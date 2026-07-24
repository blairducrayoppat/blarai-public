# BlarAI Append-Log + Archive-Architecture Audit
*Auditor session, 2026-07-18. Read-only pass over every accumulation surface in the repo. No repo files touched.*

**One-paragraph orientation.** BlarAI's doctrine ("record every measurement when it runs", "journal every ship", "handoff brief per session", "per-sprint artifact dirs") is working exactly as designed — and that is the problem. The surfaces it writes to are *monolithic* (one ever-growing PERFORMANCE_LOG.md, BUILD_JOURNAL.md) or *flat and unbounded* (docs/handoffs/ 121 files, docs/ root ~160 loose files, docs/sprints/ 279 files). Nothing rotates. A session grounding itself pays tokens proportional to the *entire history* to reach *this week's* facts. The fix is not to write less — it is to keep the **hot** surface a rolling window and push the cold tail into dated, indexed volumes a session reaches in ≤2 reads. The good news: the repo already contains the model design (docs/ledger/ — per-entry files, timestamp-sortable, README index) and an archive precedent (docs/archive/platform_separation/). This proposal generalizes both.

---

## 0. Scope note — the audit found more than the six targets

The six named targets total ~5.5 MB. Two unnamed surfaces dwarf them and must be flagged before any restructure:

| Surface | Files | Size | Verdict |
|---|---|---|---|
| **docs/security/** | **19,253** | **289.6 MB** | NOT investigated per mission scope, but this is 98% of docs/ by bytes and 97% by file count. Almost certainly a vendored/generated blob dump (scan outputs, a tracked dataset, or dependency vendoring), not hand-authored governance. **This is the #1 thing to characterize before the restructure** — the archive design below is moot next to it. Flagged, not touched. |
| **docs/ root loose files** | ~160 | ~4.5 MB | The Phase-5 pre-operational prompt/report era: `P5_TASK*`, `Task4.*`, `P5_FEASIBILITY_*`, EA `.xml` prompts, one-off `ISSUE_*`/`PR_*`/`GENAI_*` upstream drafts, `FEASIBILITY_*`. ~90% cold archive. Biggest *cheap* win after security. |
| docs/learning/ | 26 | 4.98 MB | Not in mission scope; investigate separately (large for 26 files — likely embedded eval artifacts). |
| docs/archive/ (already exists) | 121 | 3.53 MB | Precedent: holds `platform_separation/` (a completed migration's EA XMLs + `temp_for_responses/`). Confirms `docs/archive/<topic>/` as the house convention. |

The rest of this doc addresses the six targets and proposes the unified architecture (§5).

---

## 1. PERFORMANCE_LOG ANATOMY

### Census
- **Size:** 205.5 KB, ~2,790 lines (grown past the 2,240 the mission cited — a live session is appending an uncommitted #897 census entry at the head and a 2026-07-17 head-to-head entry at the tail; READ-ONLY, untouched).
- **~61 dated entries** + a mid-file `[TEMPLATE — do not use as real data]` block + 3 preamble sections ("How to add an entry", "Companion standing measurements", "Metrics glossary").
- **Date span:** 2026-05-21 → 2026-07-17. **Monthly volume:** May ~3, June ~30, July ~28. **Cadence ≈ 30 entries/month** in an active month.
- **Entry anatomy:** dated `###` header naming the *lesson* not the change (e.g. "KV-cache precision at long context: INT8 is the sweet spot…"), a `#NNN` ticket ref, then either terse `**What / Setup / Results / Not measured**` bold-run prose (recent style) or `#### Config stamp / #### Results / #### Not measured` subsections (older style). Length 15–90 lines; median ~35. Nearly every entry names a `docs/performance/*.json` twin and ends with an honest "Not measured" list.

### Structural defect (load-bearing for the rotation redesign)
The file has **two insertion regimes fighting each other**:
- **Lines 1–~2117:** reverse-chronological, newest-at-top (as the "How to add an entry" instructions prescribe: *"paste as a new ### section below (newest at the top)"*).
- **Line ~2151:** the TEMPLATE block sits *mid-file*.
- **Lines ~2203–end:** a second batch appended *at the tail* in forward-chronological order (2026-07-07 … 2026-07-17), i.e. later sessions ignored "newest at top" and appended after the template.

So the file is non-monotonic in both directions and the template acts as an accidental wall. Any rotation redesign should also **re-establish a single insertion discipline** (recommend: newest-at-top; move the TEMPLATE + preamble into a short `docs/performance/PERFLOG_CONTRIBUTING.md` so the data file is pure entries).

### Hot vs. cold split
A future session needs **hot**: (a) the current rolling month of entries, and (b) a small pinned **Landmark Baselines** block — the ~8 canonical current numbers a session actually reaches for (resident 14B spec-decode throughput, memory ceiling census, prefix-caching KEEP-ON verdict, current OV/driver versions, image-model residency). Everything older is **cold** — reached only when a specific historical comparison is needed, which is exactly the index→volume path.
- **Hot target:** current month (~30 entries ≈ 55–65 KB worst case) + ≤10 KB landmark header ⇒ **aim ≤ ~60 KB**, down from 205 KB and never growing past one month. (If a month runs >~80 KB, the rotating session splits it `YYYY-MM.md` + `YYYY-MM.b.md`.)
- **Cold:** one volume per prior month.

### JSON-duplication verdict: **COMPLEMENTARY, NOT REDUNDANT — keep both.**
Sample-verified two entries against their JSON twins:
- **2026-06-24 Playground v2.5** (narrative L1104–1135) vs `playground-v2.5-int8-arc140v-2026-06-24.json`: every *number* in the prose (+8.16/+8.42 GB, 36 s/1.2 s-per-step, 157 s CPU, 32.54 GB over-ceiling by 1.2 GB) is present as a structured JSON field. But the narrative adds **interpretation the JSON does not carry** ("measuring beat estimating", "load-bearing for the design", the swap-per-phase design conclusion). The JSON carries the machine-parseable `not_measured[]` and exact baseline attribution the prose compresses.
- **2026-07-09 prefix-caching** (narrative L2241–2289) vs the JSON: here the narrative cites `…_18-02-15.json` (full S1–S8 matrix) while the untracked file on disk is `…_16-02-52.json` — a **partial S1+S3, runs=2 re-run**. So they are demonstrably **not 1:1 twins**: one narrative entry can front *multiple* JSON runs, and some JSONs have no narrative at all. The JSON holds raw per-arm granularity (median/std/p95, `gpu_mem_peak_bytes` byte breakdowns, tpot) that the narrative summarizes into headlines; the narrative holds the **VERDICT vs pre-committed criteria + LA ratification + cross-ticket context** the JSON never records.

**Consequence for rotation:** the narrative is a lossy human synthesis + decision record; the JSON is the lossless dataset row. Neither subsumes the other, so **both must survive** — but they rotate *independently*: the JSONs in `docs/performance/` are **already a per-file archive** (naturally rotatable, nothing to redesign there except an index). Only the monolithic PERFORMANCE_LOG.md narrative needs the volume-rotation treatment. Rotation stays compatible with "record at the time it runs" because new entries still append **live to the hot file**; rotation only moves the *tail* (entries older than the current window) at the monthly retrospective — write-head and rotate-tail are temporally disjoint, zero conflict.

### docs/performance/ dir health
134 top-level files (127 JSON, 4 md, 1 html, 2 other) + a `community_export/` subtree (~112 files, the curated OpenVINO/Reddit/llmtracker contribution staging area — semi-live, feeds ongoing upstream work). **One outlier:** `vision_head_to_head_2026-07-17.html` at **5.86 MB** is 78% of the directory's bytes and is an **LA-facing artifact, not a dataset row** — it should not live in the machine-readable dataset dir. Recommend relocating operator-facing HTML to `docs/artifacts/` (flag only; another session owns it, untracked). Add `docs/performance/INDEX.md` (date | harness | title | filename) so a session finds the right JSON without `ls`-ing 134 files.

---

## 2. HANDOFFS LIFECYCLE

### Census
- **121 files, 1.55 MB, `docs/handoffs/` is git-ignored** (confirmed: `git ls-files` = 0; `.gitignore` says *"Session handoff briefs — transient cross-session continuity notes… snapshotted for audit via `git add -f` if ever needed"*). So handoff archiving is **pure working-tree hygiene** — it reduces the glob/ls surface a session pays to navigate; it is not a git concern and never enters a commit.
- **Date span:** 2026-05-22 → 2026-07-18. **Naming is inconsistent:** `<topic>-handoff-brief.md`, `day-<date>-handoff-brief.md`, `<topic>-handoff-<date>.md`, `next-session-agenda-<date>.md`, `live-cluster-runplan-<date>.md`.
- **Live vs. dead:** a brief is **dead** once its `predecessor_session_anchor` SHA is an ancestor of `main` AND a newer brief supersedes it. Sampled the oldest (`model-sharing-handoff-brief.md`, 2026-05-22 — its work, the shared 14B pipeline, shipped ~2 months ago and is now the production seam referenced in current JSONs: **dead**) and newest (`next-session-agenda-20260718.md`, today: **live**; `day-20260717-handoff-brief.md`, yesterday: **just-superseded**). **Estimated live set: ~2–3 files (the last ~1–2 days). ~118 are dead.**

### Proposed policy
- **Retention window:** keep the trailing **7 days** (or last 3 sessions, whichever is more) flat in `docs/handoffs/`. That is the set a fresh session might still be handed.
- **Archive (never delete — mission rule):** sweep everything older into `docs/handoffs/archive/YYYY-MM/`. Still git-ignored, so zero git impact; the only effect is that `docs/handoffs/` shows ~5 files instead of 121.
- **Index (cheap insurance):** `docs/handoffs/archive/INDEX.md`, one line per brief: `date | topic | anchor-SHA | superseded-by`. Lets a future session locate the brief behind a shipped arc without opening 118 files.
- **Naming forward:** standardize on `YYYY-MM-DD-<topic>-handoff.md` so date-sort = chrono-sort and the sweep is a pure date-prefix move.
- **Who runs it:** the same monthly-retrospective session (§5) — one `mv` of the >7-day tail.

---

## 3. SPRINTS DIR

### Census
| Dir | Files (recursive) | Size | Newest mod | Structure |
|---|---|---|---|---|
| sprint_8 | 82 (`reports/` 79) | 379 KB | 2026-07-04 | deep `reports/` subtree |
| sprint_9 | 89 (`reports/` 86) | 424 KB | 2026-07-04 | deep `reports/` subtree |
| sprint_10 | 29 (`reports/` 25) | 301 KB | 2026-07-04 | `reports/` subtree |
| sprint_11 | 38 (`reports/` 34) | 321 KB | 2026-07-04 | `reports/` subtree |
| sprint_12 | 3 | 84 KB | 2026-07-04 | flat |
| sprint_13 | 3 | 70 KB | 2026-07-04 | flat |
| sprint_14 | 3 | 79 KB | 2026-07-04 | flat |
| sprint_15 | 8 | 148 KB | 2026-07-04 | flat |
| sprint_16 | 5 | 144 KB | 2026-07-04 | flat |
| sprint_17 | 5 | 69 KB | 2026-07-04 | flat |
| sprint_18 | 6 | 63 KB | 2026-07-02/04 | flat |
| _templates | 3 | 53 KB | 2026-07-04 | **LIVE** |
| iss_2 | 3 | 120 KB | 2026-07-04 | issue-scoped |
| *(root)* | ACTIVE_SPRINT.md 22 KB, FORWARD_EXECUTION_PLAN_to_598.md 15 KB | — | 2026-07-03/04 | **ACTIVE_SPRINT = LIVE** |

**Total 279 files / 2.29 MB, all tracked (276 in git).** Every `sprint_N` dir is frozen (mod 2026-07-04, a bulk reorg date) — **pure archive**. The `strategic_design_vision.md` / `strategic_completion_report.md` / `Strategic_Work_Analysis_and_Gap_Report_*.md` triad recurs in each dir; the `reports/` subtrees under 8–11 are the bulk.

### Archive plan
- **Move** `docs/sprints/sprint_8 … sprint_18` and `iss_2` → `docs/archive/sprints/` (git `mv`, tracked — this is a real commit, **not** my action; design only).
- **Leave in place (live):** `docs/sprints/ACTIVE_SPRINT.md` (the live sprint pointer, named in CLAUDE.md `<live_state_pointers>`), `docs/sprints/_templates/` (reused every sprint), and `FORWARD_EXECUTION_PLAN_to_598.md` (verify live before moving — it reads like a still-referenced plan).
- **Index:** `docs/archive/sprints/INDEX.md`, one line per sprint: `sprint N | date-range | one-line what-it-delivered | dir/`.
- **Must stay reachable:** ADRs and the ledger cross-reference sprint outputs by path; a git `mv` preserves history but breaks hardcoded links. The INDEX + a one-line stub note in the old location's parent (or a redirect note in ACTIVE_SPRINT.md) covers grounding. Because sprints are tracked, the win here is **navigational** (279 files out of the working glob surface), not token-per-file — but it is the single largest *file-count* reduction available in-repo after the docs/ root sweep.

---

## 4. LEDGER + RESEARCH + REVIEWS + ADRS + GOVERNANCE + SCHEDULED

**LEDGER (`docs/ledger/`, 31 files, 189 KB, tracked)** — **Healthy; this is the reference design the whole architecture should emulate.** Per-entry files, `YYYYMMDD_HHMMSS_sprint<N>_ea<M>_<slug>.md`, timestamp-sortable, self-describing `README.md`, required YAML frontmatter (`ledger_id/date/sprint_id/entry_type/predecessor/branch/merge_commit/disposition`). The design was *forced* by a real merge-conflict incident (two branches both claiming "Entry 51" in the old monolith) — i.e. it is battle-tested. No rotation needed; it is already archival-friendly. **One residual:** the frozen monolithic `docs/POST_OPERATIONAL_MATURATION_LEDGER.md` (209 KB, Entry 1–52) still sits at the docs/ root — move it to `docs/archive/ledger/` with a pointer stub (its README already documents the freeze and the ~100 valid back-references).

**RESEARCH (`docs/research/`, 22 files, 503 KB, tracked)** — **Mostly live reference** (all 2026-07: coordinator program plan, C3 heartbeat design, RAM-headroom, heterogeneous-dispatch + audit14/15 recommendations). Low archive priority; small. Rotate only pieces >1 quarter old to `docs/archive/research/`, and only when it exceeds ~1 MB. Note `ram-headroom-apply-log-2026-07.md` is untracked (in-flight).

**REVIEWS (`docs/reviews/`, 2 files, 50 KB, tracked)** — Live-ish: both are the 2026-07-11 durability-distribution tenet review (disposition + adversarial). The disposition file is currently untracked (in-flight). Keep in place; too small to matter. When a third review lands, adopt `docs/reviews/YYYY-MM-DD-<topic>-<kind>.md` and let old ones rotate to `docs/archive/reviews/`.

**ADRS (`docs/adrs/`, 38 files, 742 KB, tracked)** — **LIVE reference in full** (ADR-006 … ADR-041). Do **not** archive — ADRs are the decision SSOT and are read on demand by number. **Two strays to flag:** `DRAFT_cert_remint_race_durable_fix.md` (untracked, a real DRAFT_ prefix) — either promote to an `ADR-NNN` or relocate to a `docs/adrs/drafts/` holding area so the numbered set stays clean. The other untracked docs-security drafts (`AUDIT_AndyStanish_SystemQualities.md`, `STANDARDS_Conformance_Audit.md`) are separate in-flight work.

**GOVERNANCE (`docs/governance/`, 23 files, 398 KB, tracked)** — **Live reference** (README, STYLE.md, doc-lifecycle.md, credential-lifecycle.md, weight-integrity.md, handoff-brief-template.md — the last two named in CLAUDE.md). **Important:** `docs/governance/doc-lifecycle.md` already exists — **the archive architecture below must be reconciled against it, not layered over it** (it may already define retention rules this proposal should extend rather than contradict). **Rotate:** the dated generated HTML digests (`decisions_digest_2026-07-18.html`, `coordinator_shadow_precision_report_2026-07-18.html`) are point-in-time artifacts, not governance policy → `docs/archive/governance-digests/YYYY-MM/`.

**SCHEDULED (`docs/scheduled/`, 22 files, 756 KB, tracked)** — **Pure archive.** All 22 are *executed* EA-queue task XMLs from 2026-04-21…24 (`*_executed_<date>_<sha>.xml`, two `*_stale_*`), the Phase-5 SDO/EA orchestration era. Forensic-only. Move wholesale → `docs/archive/scheduled/`. **Caveat:** the ledger README references `docs/scheduled/wake_templates/sdo.md` as an authoritative live template — if a `wake_templates/` subdir exists it is **live and must stay**; only the executed XMLs archive. Verify before the move.

---

## 5. ARCHIVE ARCHITECTURE PROPOSAL

### The one rule that keeps hot files small permanently
> **Write to the head, rotate the tail on a fixed owned cadence.** Every append-log keeps only a *rolling current window* live; at each monthly retrospective the same session sweeps everything older than the window into a dated cold volume and prepends its one-liners to a per-surface index. Because the cadence is owned by an event that already exists (the monthly retrospective mandated in CLAUDE.md `<journal_discipline>`), the responsibility never orphans and no new ritual is invented.

### Naming convention (unified)
```
docs/archive/<surface>/INDEX.md              # one line per entry, newest-first
docs/archive/<surface>/<period>.md           # a cold volume: one month (or quarter for low-volume)
```
- `<surface>` ∈ `performance` · `journal` · `sprints` · `scheduled` · `ledger` · `governance-digests` · `research` · `reviews` (and, git-ignored, `docs/handoffs/archive/`).
- `<period>` = `YYYY-MM` for high-volume surfaces (performance, journal); `YYYY-Qn` for low-volume; a `<topic>/` subdir for one-shot migrations (matches the existing `docs/archive/platform_separation/`).
- This slots directly beside the archive dir that already exists — no new top-level convention.

### Index-file format (the ≤2-reads guarantee)
One greppable line per entry, pipe-delimited, newest-first:
```
2026-06-24 | Playground v2.5 OV-INT8 on Arc 140V | resident ~8.4 GB; 1024px 36s; cannot co-reside with 30B coder | 2026-06.md
```
`date | title | plain-summary | volume-file[#anchor]`. A session greps the small INDEX for a keyword → gets the volume filename → reads exactly that one ≤~70 KB month-volume. **Never loads a multi-hundred-KB file.** The `plain-summary` column is lifted verbatim from each entry's existing searchable index line (the journal's `*Plain summary:*` line; the performance entry's `**What:**` clause) — no new authoring burden.

### Rotation cadence and owner
- **Cadence:** monthly, at the existing month-end retrospective (or first quiet tree after). Quarterly for low-volume surfaces.
- **Owner:** the retrospective session. Its rotation step (add to its existing checklist):
  1. For each rolling surface, cut entries older than the current month out of the hot file into `docs/archive/<surface>/YYYY-MM.md` (append in-order).
  2. Prepend those entries' one-liners to `docs/archive/<surface>/INDEX.md`.
  3. Leave the hot file = current month + the pinned landmark block.
  4. Sweep `docs/handoffs/` >7-day tail into `docs/handoffs/archive/YYYY-MM/` and append to its INDEX.
  This is one atomic doc-hygiene commit, same standing as folding journal fragments.

### Per-surface hot-size targets
| Surface | Hot file | Target hot size | Cold volumes |
|---|---|---|---|
| PERFORMANCE_LOG.md | current month + Landmark Baselines header | **≤ ~60 KB** (from 205 KB) | `docs/archive/performance/YYYY-MM.md` + `INDEX.md` |
| BUILD_JOURNAL.md | current month + pinned canonical lessons pointer | **≤ ~80 KB** (from 2.26 MB) — biggest single win | `docs/archive/journal/YYYY-MM.md` + `INDEX.md` |
| docs/handoffs/ | last 7 days | ~5 files | `docs/handoffs/archive/YYYY-MM/` (git-ignored) |
| docs/sprints/ | ACTIVE_SPRINT + _templates | 2 files + templates | `docs/archive/sprints/` (one-time move) + `INDEX.md` |
| docs/scheduled/ | (nothing live but wake_templates) | wake_templates only | `docs/archive/scheduled/` (one-time move) |
| docs/ root loose | live root docs only | — | `docs/archive/phase5-prompts/` (one-time sweep of P5_/Task4.* era) |
| docs/performance/*.json | all (already per-file) | unchanged | add `INDEX.md`; relocate the 5.86 MB HTML out of the dataset dir |

*(BUILD_JOURNAL.md at 2.26 MB is the largest hot append-log in the repo and was not a named target — but it is the same problem and the same fix, and it is the highest-token-value surface a grounding session loads. Recommend it be first in scope. [PROPOSED])*

### Compatibility guarantees
- **"Record at the time it runs" (performance) and "journal every ship":** untouched — new entries always append to the *hot* file the instant work lands. Rotation only ever moves entries that are already ≥1 month old. Write-head / rotate-tail are temporally disjoint.
- **The JSON dataset:** untouched by narrative rotation; it is already a per-file archive. Community-export flows keep reading `docs/performance/*.json` exactly as today.
- **The ledger** is already this design — it is the proof the pattern works at scale (31 conflict-free parallel-authored entries). The architecture simply extends the ledger's per-entry + README-index idea to the two monolithic logs and the flat dirs.
- **Reconcile against `docs/governance/doc-lifecycle.md` first** — it may already own part of this; extend it, do not fork it.

### First-cut migration order (largest win → smallest, all one-time except the two logs)
1. Characterize **docs/security/** (290 MB) — gate everything else on knowing what it is.
2. Sweep **docs/ root loose files** (~160 → `docs/archive/phase5-prompts/`) + move the frozen monolith ledger. *Cheapest huge win.*
3. Move **docs/sprints/sprint_* + iss_2** and **docs/scheduled/*** to `docs/archive/`. *Largest file-count reduction.*
4. Stand up **PERFORMANCE_LOG** and **BUILD_JOURNAL** monthly rotation + indexes; fix the PERFORMANCE_LOG insertion-order defect in the same pass.
5. **docs/handoffs/** 7-day sweep (git-ignored, do anytime).

---

## 6. ROOT STRAYS

Classification only — **nothing touched**. Untracked entries flagged as another session's in-flight work (per git status), not judged.

### Genuine working debris → archive candidates (tracked unless noted)
- `just_a_pythonFile.py` — 0 KB, empty, 2026-02-04. Pure junk; the clearest delete-outright candidate (but mission = archive, so `docs/archive/root-debris/`).
- `pytest_baseline.txt`, `pytest_m53_gate.txt`, `pytest_m54_gate.txt`, `pytest_output.txt` — stale gate captures, 2026-03/04.
- `soak_log.txt` — 123 KB, 2026-05-12, old soak output.
- `snapshot_report.html` — 141 KB, 2026-07-18 (recent — likely a live generated artifact; verify before moving).
- **Untracked (in-flight — flag, don't judge):** `SoCWatchHelp.json` (42 KB, Intel SoC Watch tool debris), `hand2.png` (1.4 MB), `blarai_lighthouse3.png` (2.8 MB). These are on another session's working set per `git status`.

### Reference material misfiled at repo root → `docs/reference/papers/` (tracked)
~19 research PDFs from 2026-02-22 (~28 MB total): `AGENTIC AI SECURITY…pdf` (5.5 MB), `CIMemories…pdf` (3.1 MB), `Proactive Privacy Amnesia…pdf` (4.2 MB), `Confidential VMs Explained…pdf`, `Faramesh…pdf`, `Federated RL…pdf`, `Governance-as-a-Service…pdf`, `Indirect Prompt Injection…pdf`, `intel-tdx-connect-architecture-specification.pdf`, `MemTrust…pdf`, `Privacy-Aware Lifelong Learning.pdf`, `Securing AI Agents…pdf`, `SWE-Master…pdf`, `Technical Report… Microsoft and Intel on Intel TDX…pdf`, `Token-Level Differential Privacy…pdf`, `Unveiling Privacy Risks…pdf`, `Virtio-Vsock…pdf`, `The-Complete-Guide-to-Building-Skill-for-Claude.pdf` (548 KB). Plus reference data: `OpenVINO Release Notes….htm` (1.3 MB), `Test Matrix.xlsx`, `llm_models_7-258V.csv`, `OpenVINO_GENAI_Supported_LLM_Models.csv`.

### Substantial project docs misfiled at root → belong under `docs/` (tracked)
- `AI Risk Assessment and Mitigation Strategy.md` (47 KB), `Critical Design Review — Red Team Assessment.md` (36 KB), `Enabling XAttention on Intel Arc - Gemini Study.md` (20 KB), `Phase_2_Test_Plan.md` (24 KB), `github_profile_README.md`. These are real content, just at the wrong altitude.

### Live root files — KEEP IN PLACE (do not archive)
`CLAUDE.md`, `README.md`, `BUILD_JOURNAL.md`, `LESSONS.md`, `FIELD_NOTES.md`, `PERFORMANCE_LOG.md`, `conftest.py`, `pyproject.toml`, `.gitignore`, `.gitattributes`, `.env.example`, `.mcp.json`, `AGENTS.md`, `SECURITY.md`, `LICENSE.md`, `COMMERCIAL-LICENSE.md`, `requirements.2026.1.0.lock.txt`, `requirements.2026.2.1.lock.txt`, `requirements.2026.2.1.hashed.lock.txt`, `sitecustomize.py`, `launch_blarai.bat`, `Use Cases_FINAL.md`, `.blarai-governed-core`.

*(Note: BUILD_JOURNAL.md, LESSONS.md, PERFORMANCE_LOG.md stay at root as the live hot files — their rotation is §5, not a relocation.)*

---

*End of audit. All findings are from a read-only pass; every relocation/move above is a design recommendation for a future tracked commit, not an action taken here.*
