# Independent re-check of the #1616 fix range `b128a4e7..a727b1cd`

- **Verdict: MERGEABLE on the fixes. No merge-blocker.** Every one of the seven FIXED rows in
  `docs/reviews/corpus-tier-slice1-disposition-2026-09-24.md` closes its original failure
  scenario when RUN, and every lock fails when its defect is re-introduced. Two SHOULD-FIX items
  (one overclaim in the disposition record, one lenient spare in the builder) and eight NOTEs
  below; none opens a store unverified, widens the exemption, or changes a live prompt.
- **Tested at:** branch `feat/1616-corpus-tier` HEAD `a727b1cd` (merge base with main
  `b73a2dd6`), primary checkout, tree untouched (only the two pre-existing untracked docs).
  Clock 2026-10-02 22:43 EDT (machine `-04:00`). Non-elevated shell (symlink probe skipped).
- **Reviewer:** independent of the fix author and of the 09-24 reviewer. Nothing edited,
  nothing repaired; this file is the only artifact created in the tree.
- **Probes** (`scratchpad/recheck/`): `probe_prompt_identity.py`, `probe_reader_open_routes.py`,
  `probe_builder_provenance.py`, `probe_real_loop.py`, `probe_real_loop2.py`, `probe_pa_runs.py`,
  `probe_real_default.py`, `recheck_toggle_plugin.py` (a `pytest -p` plugin that re-introduces one
  defect in-process per run). Fixture stores built with the real builder; `B:/kiwix` touched only
  by a read of the two 203-byte/1 KB sidecar + manifest JSON files and `Path.is_file()` — the
  39 GB store was never opened through `reader.py`.

## Suites run (LOCALAPPDATA redirected to the scratchpad; `-p no:cacheprovider`)

| Invocation | Result |
|---|---|
| `tests/security/test_reference_corpus_dormancy.py shared/tests/test_corpus_reader.py shared/tests/test_corpus_builder.py services/assistant_orchestrator/tests/{test_retrieval_tools,test_tools,test_tools_native_json,test_gpu_inference,test_preference_handlers}.py tests/integration/{test_eval_answer_quality,test_eval_preference_memory,test_rubric_security_checks_are_reachable}.py tests/security/test_doctrine_freshness.py` | **483 passed**, 0 failed, 0 skipped, 2 deselected by the standing `-m` markers, 20.8 s |
| `scripts/verify_disposition.py docs/reviews/corpus-tier-slice1-disposition-2026-09-24.md` | PASS 11 ok / 0 unjustified |
| Six toggle runs (table below) | every lock FAILS with its defect re-introduced |

The standing gate was NOT run (brief: a gate run follows separately).

## Per-fix: original scenario reproduced against the fixed code, then attacked

| Fix | Original failure, re-run on `a727b1cd` | Result | Lock fails when toggled? |
|---|---|---|---|
| 1 `4a3179d2` exemption | second `search_reference` in one turn through the REAL `_handle_connection` loop | runs: `runner_calls=['first','second']`, 3 generations, no deny receipt | yes — `RECHECK_TOGGLE=exempt`: 3 locks FAIL (`..._same_turn_executes`, `..._under_preexisting_knowledge_content`, `test_lock_exempt_set_is_exactly_the_four...`), the author's own toggle test passes |
| 2 `a5bfbe60` no unverified open | `manifest_path=None` / `'' or None` / `'   '` / `''` literal / directory / the db itself, no manifest beside the store | all **REFUSED** (`integrity manifest missing` / `unreadable`) | yes — `RECHECK_TOGGLE=manifest` (old shape: nothing configured → no verify): 4 locks FAIL |
| 3a `84e6ffab` provenance | mismatch in shard 3 of 3; agreeing shards; CLI `main()` | refused `disagree on extract_rules_sha256`; store meta carries `repo_commit`/`extract_rules_sha256`/`with_tables`/`build_with_tables`/`extraction_with_tables`; manifest carries `rules_sha256`/`repo_commit`/`with_tables`; reader exposes all three | yes — `RECHECK_TOGGLE=builder` (first sidecar only): 2 locks FAIL |
| 4 `65e9b31a` advertisement | SHA-256 of `_DEFAULT_SYSTEM_PROMPT` rendered from a `git archive main` export vs the branch | **identical**: `02f4ee36…3576d`, 9,590 chars, both; `render_default_system_prompt()` == the constant; with a runner registered: `1ad9777a…2b861`, 10,421 chars, "You have 11 built-in tools", schema present | yes — `RECHECK_TOGGLE=advertise`: `test_switched_off_corpus_tool_is_not_advertised` + `test_registered_corpus_runner_is_advertised` FAIL |
| 5 `8c160b52` notice lock | plant `search_gutenberg` (registry + schema + allowlist + provenance map) with `SEARCH_GUTENBERG_NO_RESULTS_NOTICE` not in `RETRIEVAL_NOTICES` | lock FAILS naming it: `SEARCH_GUTENBERG_NO_RESULTS_NOTICE is not in RETRIEVAL_NOTICES` (the partition lock passes, correctly) | this run IS the toggle — see finding 1 |
| 7a `84cf736e` stop() | `stop()` with a corpus handle | `close()` called once, handle `None`, runner `None` | yes — `RECHECK_TOGGLE=stop` (handle left open): lock FAILS |
| 7c `84cf736e` prose | `grep "Amendment 4"` in the runner docstring and `pgov.py` declaration | both now say Amendment 5 | n/a |

---

## Findings, most severe first

### 1. SHOULD-FIX — the disposition records a toggle test for the notice lock that does not exist
- **Where:** `docs/reviews/corpus-tier-slice1-disposition-2026-09-24.md:22` (row
  `5-notice-lock-hardcodes-three-prefixes`): "toggle-tested by planting a fourth declared tool with
  an undeclared notice, which the lock names." Commit `8c160b52` touches one file, 6 insertions /
  3 deletions — the derivation at `test_retrieval_tools.py:289-292` and a comment. No test in the
  tree patches `_TOOL_RESULT_PROVENANCE` or plants a fourth tool
  (`grep -rn "search_gutenberg\|fourth" services/ tests/` → the comment at line 286 only).
- **What is wrong:** the disposition is the artifact a later session trusts about what is locked.
  It describes the 09-24 reviewer's scratch probe as if it shipped. The lock itself is correct —
  my toggle fired it by name — so this costs nothing today; it costs the next person who skips
  writing the toggle because the record says one exists.
- **Reproduced:** `RECHECK_TOGGLE=notice` run above (lock fails, names the planted constant).
- **Fix shape (not mine to write):** either land the fourth-tool toggle as a test, or amend the row
  to say the toggle was the reviewer's probe. Row 1's and row 4's toggle claims are TRUE (the
  toggle tests exist and I ran them both ways).

### 2. SHOULD-FIX (lenient spare) — a shard with NO sidecar is merged silently under the other shards' provenance
- **Where:** `tools/corpus/build_corpus.py:381-385` — `_shard_provenance` appends a sidecar only
  `if meta_path.is_file()`; a shard without one is neither read nor counted, and the per-field
  warning fires only when NO sidecar carries the field.
- **What is wrong:** the disposition says the builder "reads every shard sidecar, refuses shards
  that disagree". A missing sidecar is not a disagreement, so a JSONL from an unknown extraction
  (an earlier attempt, a hand-made file) builds into a store that then claims the OTHER shards'
  `repo_commit` and `extract_rules_sha256` for its text — the G2 tie signed for text it does not
  cover. The dangerous neighbour here is an earlier extraction's shard left in the same directory.
- **Reproduced:** `probe_builder_provenance.py` §2:
  ```
  third-shard-has-no-sidecar   BUILT  with_tables='1' ... repo_commit='abc123' extract_rules_sha256='ffff…' chunks=3
  ```
  (no warning printed; `no-sidecar-anywhere` warns three times and says `unknown` — that path is
  honest, the mixed path is not).
- **Incidence:** 0 — the 5 real shards under `B:/kiwix/work/shards/` each have a sidecar, all five
  agree (`repo_commit d34e2516`, `extract_rules_sha256 50a766a2…`, `with_tables: true`).
- **Fix shape:** refuse (or at least warn and record `unknown`) when any shard lacks a sidecar while
  others have one.

### 3. NOTE — `with_tables` is a confident "1" from an absence, and a string `"false"` reads as true
- **Where:** `build_corpus.py:191-192` (`effective = with_tables and extraction_with_tables != "0"`)
  and `:393-394` (`"1" if bool(value) else "0"`).
- **Reproduced:** §3 — sidecar lacking the key + build default → `with_tables='1'`,
  `extraction_with_tables='unknown'`; sidecar `"with_tables": "false"` → `'1'`; `0` (int) → `'0'`.
  The two detail keys tell the truth; the summary key the reader exposes (`corpus.with_tables`)
  is the confident one.
- **Incidence:** 0 — real sidecars carry a JSON `true`. The pre-fix real store on B: reads
  `with_tables='1'`, `repo_commit='unknown'`, `extract_rules_sha256='unknown'` through the reader
  (§5 simulated on a fixture; matches the real `meta` key list the 09-24 review read) — honest, as
  the disposition says.

### 4. NOTE — `verified_by` has no production caller, and its guard tests a handle's SHAPE, not a verification
- **Where:** `shared/corpus/reader.py:185-199`; `grep -rn verified_by` outside tests → reader.py
  only. The docstring says the handoff skips re-hashing "without creating a way to open bytes
  nobody verified".
- **Reproduced:** `probe_reader_open_routes.py` §D — a `ReferenceCorpus.__new__` instance with
  `_path` set and `verified_sha256="deadbeef"` → `OPENED chunks=1 verified_sha256=deadbeef`; a
  closed first reader → OPENED (fine, same bytes); a reader of a byte-identical COPY at another
  path → REFUSED; `verified_by` + `manifest_path` → REFUSED; in-place append after the first verify
  → `verified_by` OPENS (fresh open with the manifest REFUSES). Any code able to forge the handle
  can open sqlite directly, so no privilege is gained; the point is an unused API whose docstring
  overclaims and whose honest description is "point-in-time verification inherited by reference".
  The accuracy suite is named as the intended second reader; it does not call it yet.

### 5. NOTE — the grammar still names `search_reference` while dormant; the CAPABILITIES prose never names it while live
- **Where:** `tools.tool_call_grammar_schema()` (dormant: `search_reference` present — reproduced);
  `gpu_inference.py:160-162` CAPABILITIES block ("through the search_knowledge and web_search
  tools") with the runner registered — reproduced, the 09-24 review's finding 9 bullet 3 is not
  closed. The 09-24 "a fix must prove" asked for tools block AND grammar; the author kept the
  grammar deliberately ("dispatch unchanged") and the disposition says so. Dormant dispatch holds:
  a `search_reference` call with no runner reaches the unavailable notice, `has_untrusted_content`
  stays False (`probe_real_loop.py` §E). Nothing in the dormant prompt says "encyclopedia".

### 6. NOTE (LA-visible posture fact, not a defect of this fix) — after this exemption no GUARDED tool is Layer-3-locked
- **Reproduced:** `probe_real_loop2.py` — after one corpus result, with VALID arguments and the
  audit-deny reason captured: `curate_knowledge` → `DENY_UNTRUSTED_PROVENANCE_NO_TRUST`,
  `organise_userdata` → same; `web_search` dispatches (rung-3 egress envelope);
  `generate_image`, `propose_preference`, `search_knowledge`, `search_reference` dispatch
  (exempt); `get_current_time` dispatches (SAFE). The set
  `{GUARDED} − exempt − egress` is **empty** on this branch. Each exemption was argued on its own;
  the cumulative state — the lock's remaining teeth are the two DANGEROUS tools — is written
  nowhere (the `entrypoint.py:8037` comment "GUARDED tools are /trust-overridable" and ADR §A4.3
  describe a class with no members). The #570 PA adjudication DOES still run on every
  `search_reference` call (`probe_pa_runs.py`: invoked for both calls in one turn), as A5.8 claims.
- Also: the 09-24 review's finding-1 clause "generate_image stays locked after a corpus result"
  was a wrong premise — `generate_image` has been lock-exempt since Amendment 4 rung 2 on main;
  the author rightly did not act on it.

### 7. NOTE — `tool_versions` is not recorded; manifest and meta spell the rules hash differently
- The 09-24 "must prove" listed `tool_versions`; the fix records `repo_commit` +
  `extract_rules_sha256` + `with_tables` (the three G2 fields) and drops it without saying so. The
  manifest key is `rules_sha256`, the meta key `extract_rules_sha256`.

### 8. NOTE — the runner still maps "corpus is None" to the NO_RESULTS notice
- `entrypoint.py:7379-7381` returns `""` → `SEARCH_REFERENCE_NO_RESULTS_NOTICE`, not UNAVAILABLE
  (09-24 finding 7, second half; not in the disposition). Unreachable in normal flow because
  `stop()` clears the runner before closing; worth a guard, not a blocker.

### 9. NOTE — "the entrypoint's own expression is driven here" is a retyped copy
- `tests/security/test_reference_corpus_dormancy.py:163-168` drives `configured or None` typed
  into the test, not `entrypoint.py:2440`. Harmless because the reader has no unverified path at
  all (every shape I tried refused), so the test's premise cannot drift into a hole; the docstring
  just claims more reach than it has.

### 10. NOTE — docs match the code
- ADR-023 §A5.8 and the DEC-13 addendum state exactly what `tools.py:1595` does (`_LOCK_EXEMPT_TOOLS`
  gains `search_reference`; still GUARDED; PA adjudication still runs; orthogonal to D2).
  `default.toml:1421-1424` and the `entrypoint.py:2425-2431` comment describe the "empty resolves
  to the builder's manifest beside the store" behaviour that `probe_real_default.py` confirms:
  shipped `{'enabled': False, 'db_path': '', 'manifest_path': ''}`; for the real store the default
  resolves to `B:/kiwix/corpus/wikipedia_en_all_maxi_2026-08.db.manifest.json`, which exists
  (203 bytes, `sha256` present, written 2026-09-24T02:37Z, no `rules_sha256` — the pre-fix store
  the disposition already names). One prose wobble: A5.8's "Locked: … test_tools.py (the exhaustive
  exempt-set enumeration, toggle-tested)" — the enumeration is a pin; the toggle lives in
  `test_retrieval_tools.py`.

---

## What I attacked and could not break

- **Exemption width:** DANGEROUS tools after a corpus result are refused with the Layer-3 reason;
  the exempt set is exactly four and pinned; `search_reference` under a pre-existing `/external`
  paste and under pre-existing knowledge content runs; the PA adjudication runs on every call.
- **Unverified open:** `None`, `'' or None`, `''`, whitespace, a directory, the db itself, a
  byte-identical copy without its own manifest, relative paths — every route refuses or verifies;
  a wrong digest in the DEFAULT manifest refuses like an explicit one; a tampered store beside a
  good manifest refuses; a copy with the original's manifest opens (same bytes — correct).
- **Prompt identity:** SHA-256 equal to main's render; the branch's `TOOL_SCHEMAS` carries
  `search_reference` and the dormant render drops it and its count; a runner flips both; the
  go-live render without a runner works and refuses non-gated names; `generate()` and the
  preference-composed prompt both render at call time.
- **Builder:** disagreement in the LAST shard is refused on each of the three fields; build-time
  `--no-tables` over a tables extraction records `with_tables='0'` with `tables_skipped=1`;
  extraction-dropped tables under a build default record `'0'`.
- **Locks:** six toggles, every lock fails on its re-introduced defect; the author's own toggle test
  for finding 1 passes with the defect present, as a toggle should.

## Not verified

- The standing gate (brief: separate run). `start()`'s registration block (DEFERRED #1657 — I
  drove the resolver expression and the reader, not `start()`). The real 39 GB store through
  `reader.py` (would hash it). The 14B's spontaneous call rate on the live prompt (#1651). Boot
  hash time (DEFERRED #1656). Symlinked store paths (non-elevated: `os.symlink` → OSError).
- Concurrency on the shared `check_same_thread=False` connection (09-24 finding 7 hypothesis) —
  not exercised.

## Merge read

- **I would not block.** The two SHOULD-FIX items are a record correction (finding 1) and a
  builder guard that the next rebuild (#1643) should carry before it runs over `B:/kiwix/work/`
  (finding 2); neither changes the dormant posture, the verification path, or a live prompt.
- **Name in the merge motion:** finding 2 as a ticket with `blocked-by: #1643` or fix it in the
  branch; finding 6 as one sentence in ADR-023 so the cumulative Layer-3 state is written where
  the next exemption request will read it.
