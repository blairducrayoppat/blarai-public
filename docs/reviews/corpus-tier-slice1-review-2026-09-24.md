# Adversarial pre-merge review — feat/1616-corpus-tier

- **Reviewed at:** `b128a4e7` (branch head), range `main..feat/1616-corpus-tier` (10 commits over main `b73a2dd6`). Tree untouched; only the two pre-existing untracked docs in `git status`.
- **Reviewer:** independent (author session gone). Nothing edited, nothing repaired.
- **Clock:** 2026-09-24 16:51 EDT at start (machine `-04:00`). RAM at start 8.1 GB in use / 23.2 GB free, so the "~2 GiB free" premise in the brief did not hold at that moment; the full gate was still NOT run, per the brief.
- **Probes:** `scratchpad/la_1616/probe_manifest.py`, `probe_fts.py`, `probe_injection.py`, `probe_schema.py`, `probe_dormancy2.py`, `probe_layer3.py`, `test_probe_locks.py` — all on hermetic fixture stores built with the real builder; B:/kiwix touched only by one read-only `sqlite3` open of `meta` + `sources` (no reader.py open, so the 39 GB was not hashed).

## Suites run (LOCALAPPDATA redirected to `scratchpad/la_1616`)

| Invocation | Result |
|---|---|
| `tests/security/test_reference_corpus_dormancy.py shared/tests/test_corpus_reader.py shared/tests/test_corpus_builder.py shared/tests/test_corpus_extraction_rules.py services/assistant_orchestrator/tests/test_retrieval_tools.py services/assistant_orchestrator/tests/test_pgov_leakage_wiring.py tests/security/test_doctrine_freshness.py` | **235 passed**, 0 failed, 0 skipped, 7.7 s |
| `services/assistant_orchestrator/tests/test_knowledge_bank_wiring.py test_research_grounding_flag.py` (shipped `default.toml` through the real resolver with the new section) | **77 passed** |
| `scripts/verify_disposition.py docs/reviews/corpus-extraction-contract-disposition-2026-09-23.md` | PASS 21/21 |
| `scratchpad/la_1616/test_probe_locks.py` (defect reintroduced by monkeypatch) | 5 passed — see findings 5, 6 |
| New tests on the branch | 129 collected in the 4 new files + 6 new test functions (+1 parametrize case) in the 2 modified AO test files |

---

## Findings, most severe first

### 1. SHOULD-FIX (go-live blocker; not a leak) — `search_reference` locks itself after its own first result, and is locked in any session already holding knowledge/web/pasted content
- **Where:** `services/assistant_orchestrator/src/tools.py:1536` (`_LOCK_EXEMPT_TOOLS` = search_knowledge, generate_image, propose_preference — no search_reference); `tools.py:1391` declares it GUARDED "sitting with search_knowledge"; gate at `entrypoint.py:8043` (`not tools.is_lock_exempt(tool_name)`); shipped `block_tools_on_untrusted_content = true` (`default.toml:151`).
- **What is wrong:** the first corpus hit grounds as UNTRUSTED_CORPUS → `has_untrusted_content` → the next `search_reference` call is a GUARDED, non-exempt, non-egress tool → Layer-3 refuses it with `DENY_UNTRUSTED_PROVENANCE_NO_TRUST`. Same for the FIRST call in a session that already had a knowledge-bank hit, a web result, or `/external` content. The capability is single-shot per clean session without `/trust`. This is exactly the #723 rung-1 problem the amendment solved for `search_knowledge`, re-created for the new tool, while the code comments claim parity with search_knowledge.
- **Costs:** at go-live, follow-up questions fail; B5 (search NOT forced, #1651) and any multi-lookup conversation will hit it. The G1 baseline forces ONE call per fresh session (#1641) and therefore cannot see it.
- **Reproduced:** `probe_layer3.py` — real `ContextManager` + `evals/suites/governance.py::layer3_lock_decision` (the gate-locked mirror that calls the REAL `risk_tier/is_lock_exempt/is_egress_tool`):
  ```
  after ONE search_reference result grounded (has_untrusted_content=True):
     search_reference   locked=True   tier=GUARDED exempt=False egress=False
     search_knowledge   locked=False  tier=GUARDED exempt=True  egress=False
     web_search         locked=False  tier=GUARDED exempt=False egress=True
  session with only a knowledge-bank hit: search_reference locked = True
  ```
- **A fix must prove:** second `search_reference` call in one session dispatches (through `_handle_connection`, not the mirror); `generate_image` stays locked after a corpus result (the exemption did not widen); and the exemption is RECORDED — it is an ADR-023 Amendment-4-rung-1-class posture change (bounded-danger allowlist), so it needs the A5 text + DEC-13 row amended, not a silent set edit. If the decision is instead "single-shot is intended", write that down where #1651 will read it.

### 2. SHOULD-FIX (merge) — manifest verification is config-optional; an empty `manifest_path` serves an unverified store
- **Where:** `entrypoint.py:2439` (`manifest_path=resolved.reference_corpus_manifest_path or None`); `shared/corpus/reader.py:161` (`if manifest_path is not None: self._verify(...)`); `default.toml:1420` ("When set, a SHA-256 mismatch makes the reader REFUSE").
- **What is wrong:** ticket D1 and ADR-023 A5.4 say "verified at load, fail-closed"; the code verifies only when a second config key is non-empty. `enabled=true` + `db_path` + `manifest_path=""` enters the registration block and opens the store with NO verification and logs it LIVE. Principle 1/4: a component that cannot verify its precondition must refuse; here the precondition is simply not demanded.
- **Reproduced:** `probe_manifest.py` §A/B and `probe_dormancy2.py`:
  ```
  manifest_path=None (what entrypoint passes for '')         OPENED  chunks=2
  enabled=true, db_path set, manifest EMPTY  -> block entered: True  reader manifest arg: None
  ```
  (All refusal paths otherwise hold: absent file, byte-flipped copy, `sha256=''`, missing key, int, non-JSON → REFUSED; uppercase hex → opens; manifest `bytes`/`schema_version` are not checked, only `sha256`.)
- **A fix must prove:** with `enabled=true`, a store and no manifest → `REFERENCE_CORPUS_UNAVAILABLE`, runner NOT registered; the same probe on a full config → LIVE. Cleanest form: the reader REQUIRES a manifest (drop the `None` branch) so no config shape can skip it.

### 3. SHOULD-FIX (merge, small) — the G2 tie is not in the store; `meta.with_tables` records the builder flag, not the extraction's; the manifest is a checksum, not the "signed manifest" D1 names
- **Where:** `tools/corpus/build_corpus.py:198-212` (reads only `source_name`/`archive_date` from the sidecar), `:335` (`with_tables` from the builder arg), `write_manifest` `:356`; `shared/models/manifest_signer.py` (an existing TPM ECDSA signer for model manifests, unused here).
- **What is wrong:** G2 says the baseline tie is "sidecar `repo_commit` + `extract_rules_sha256` + store `meta.with_tables`". The store carries none of the first two (they live only in `B:/kiwix/work/shards/*.meta.json`, which nothing in the store points at), and `with_tables` is whatever the BUILDER was told — a store built from a `--no-tables` extraction with the builder default reports `with_tables=1`. The manifest can be regenerated by anyone who can write B: (`finalise_store.py` is that flow), so it detects corruption, not substitution; the repo already has `sign_manifest()`/`verify_manifest_signature()` for exactly that threat and the corpus does not use it.
- **Reproduced:** `probe_manifest.py` §C/D:
  ```
  sidecar[repo_commit] -> NOT IN STORE
  sidecar[extract_rules_sha256] -> NOT IN STORE
  sidecar[with_tables] -> meta (store says '1', sidecar says False)
  after silent edit, manifest REGENERATED (no key needed)    OPENED  chunks=999999
  ```
  Real store (`sqlite3` read of `meta`/`sources` only): meta keys = schema_version, zdict_b64, chunk_count, article_count, alias_count, with_tables, articles_with_edit_date, built_utc — no rules hash, no repo commit.
- **A fix must prove:** a store built from a sidecar exposes `extract_rules_sha256`, `repo_commit`, `tool_versions` through the reader AND in the manifest; `with_tables` is false if EITHER stage dropped tables; and either the manifest is signed with the existing signer (verified fail-closed at open) or ADR-023 A5.4 / DEC-13 / the reader docstring stop saying "signed". Note the real store on B: would need a rebuild-or-finalise to carry the fields — it is already the "before" for #1643, so this is a sequencing question for the lead, not a reason to skip it.

### 4. SHOULD-FIX (an LA decision before merge) — the dormant tool is advertised to the model on every live turn, with a description that solicits calls on ordinary factual questions
- **Where:** `tools.py:1045` (TOOL_SCHEMAS entry), `gpu_inference.py:201` (`render_tools_system_block()` renders ALL of TOOL_SCHEMAS into every system prompt), `tools.py:1273-1290` (grammar built from all of TOOL_SCHEMAS), `gpu_inference.py:157-165` (CAPABILITIES prose: "through the search_knowledge and web_search tools … if a tool reports it is unavailable, tell the user").
- **What is wrong:** the merge is labelled dormant, but every production prompt after it carries "Search the offline encyclopedia … Prefer a passage from here over answering from memory … especially when you are not certain", and the grammar lets the model emit it. A dormant call returns "Reference search is unavailable — the offline reference corpus is not enabled on this system", and the CAPABILITIES block instructs the model to tell the user that. House precedent exists (web_search, curate_knowledge, organise_userdata are also advertised while dormant — reproduced), but those descriptions are not invitations on the commonest question class; B5's own bar is a ≥95% call rate on factual questions, which after this merge is a ≥95% rate of wasted tool rounds and user-visible "not enabled" text. That is a quality/latency side effect on live turns → `decision_boundary` says it is his call, not ours.
- **Reproduced (prompt):** `probe_schema.py` — `search_reference advertised in system tools block: True`; 830 of 7,462 chars of the tools block (11.1%); grammar names include it; dormant call → the unavailable notice. **Hypothesis (model behaviour):** the 14B was not run in this review; the call rate on live turns is unmeasured. Incidence in the banked corpus: none (nobody has measured spontaneous call rate; #1651 is the ticket).
- **A fix must prove:** either the tools block and grammar are derived from tools that have a live runner (with a toggle test: runner absent → schema absent; present → present), or the LA explicitly accepts the live-prompt change and a baseline of pre/post answer latency on factual questions is banked.

### 5. NOTE (lock overclaim) — the notice lock's tool→prefix map is hardcoded, so a fourth declared retrieval tool is unchecked
- **Where:** `services/assistant_orchestrator/tests/test_retrieval_tools.py:1024-1028` (`prefixes = {...}` three literals) vs its docstring "Every `*_NOTICE` constant belonging to a provenance-declared tool".
- **Reproduced:** `test_probe_locks.py::test_a_fourth_retrieval_tool_slips_the_notice_lock` — register `search_gutenberg`, declare it in `_TOOL_RESULT_PROVENANCE`, give it `SEARCH_GUTENBERG_NO_RESULTS_NOTICE` NOT in `RETRIEVAL_NOTICES`: partition lock passes (correct), notice lock passes (should fail). Fix: derive the prefix set from `_TOOL_RESULT_PROVENANCE` keys (`name.upper() + "_"`).
- Both 0c6092a6 locks DO fire on the reintroduced defect (`test_partition_lock_fires…` → "registered but unclassified: ['search_reference']"; `test_notice_lock_fires…` → "SEARCH_REFERENCE_… is not in RETRIEVAL_NOTICES"), and the original one-directional lock still passes with the defect present — the author's account in comment 3708 is accurate. `_SYSTEM_AUTHORED_TOOLS` is exhaustive today (REGISTRY = ALLOWLIST = SCHEMAS, 11 tools; 8 system-authored + 3 declared). Inherent limit, reproduced: a new tool MISFILED into `_SYSTEM_AUTHORED_TOOLS` passes the partition (`test_a_new_tool_misfiled…`) — no set assertion can judge a classification; that is review's job and should be said in the lock's docstring.

### 6. NOTE (test gap; certifies by reading) — no test executes the conditional registration block
- **Where:** `entrypoint.py:2431-2457` lives inside `start()` (model load), so nothing drives it; `tests/security/test_reference_corpus_dormancy.py` clears the runner ITSELF before asserting the notice, and checks the toml value. The docstring claim "with no runner registered the tool returns a notice" is true; "the AO registers none with the flag false" is verified by reading only.
- **What I did instead:** applied the three resolution expressions (`entrypoint.py:2940-2947`) and the predicate (`:2432`) verbatim to the shipped toml and five variants (`probe_dormancy2.py`): shipped → block not entered; `enabled=true`+empty path → not entered; section absent → not entered; `enabled="false"` (a string) → `bool()` makes it TRUE (house-wide idiom, not this branch's; noting only). `shared.corpus` is not imported by importing `tools`/`entrypoint` (lazy import confirmed). **Could not execute `start()`.**
- **A fix must prove:** extract the block into a method and drive it with a fixture store: flag off → no runner; flag on + bad manifest → no runner + `REFERENCE_CORPUS_UNAVAILABLE`; flag on + good → runner registered and cleared by `stop()`.

### 7. NOTE — lifecycle: `stop()` clears the runner but never closes `_reference_corpus`
- `entrypoint.py:2627` clears the runner; no `.close()` anywhere in the diff, so the sqlite handle (opened `check_same_thread=False`, one connection shared by every session's tool call) stays open across stop/start. Also `_run_search_reference_tool` with `_reference_corpus is None` returns `""` → the NO_RESULTS notice, not UNAVAILABLE (unreachable in normal flow; worth a guard). Hypothesis on concurrency: one shared `sqlite3` connection driven from concurrent tool calls is documented-unsafe in CPython's module; not exercised here.

### 8. NOTE — boot cost of `_verify` is unmeasured: it hashes the whole 39.3 GB store on every AO start
- `reader.py:182-187`, single-threaded Python sha256 over the file. B: is a Crucial P310 NVMe; at 1.5–2 GB/s hashing that is ~20–30 s per boot, CPU-bound on one core. **Hypothesis, not measured** (not run to keep the box quiet). Needs a banked number before the ceremony, and a decision whether boot-time or first-call verification is wanted.

### 9. NOTE — prose that contradicts its authority
- `entrypoint.py` `_run_search_reference_tool` docstring and `pgov.py:401-403` say "ADR-023 Amendment 4"; the ADR (`ADR-023 §A5` header) declares Amendment 5 the authority and names the residue.
- `context_manager.py` UNTRUSTED_CORPUS docstring: "even while the two gate identically today" — a time-anchored wiring claim (coding standard: state contracts, never current state).
- `gpu_inference.py:160` CAPABILITIES prose names only search_knowledge and web_search as retrieval tools while the tools block advertises a third.
- `default.toml` reference_corpus comment says the manifest is verified "when set" — that is finding 2 written into the config.

### 10. NOTE — DEC-14 rides this feature branch
- Commit `3c4b9eea` (CLAUDE.md rule 9 + rhythm line + snapshot; DECISION_REGISTER DEC-14) is on this branch and NOT on main (`git show main:docs/DECISION_REGISTER.md | grep -c DEC-14` → 0). `test_doctrine_freshness.py` passes on the branch (19 tests). The merge motion must close #1640 too, or the lead lands it separately; either way it should be named in the merge commit.

### 11. NOTE — the gate re-baseline (in slice-1 scope) is not done on the branch
- ~136 new tests; `docs/TEST_GOVERNANCE.md:57` and `CLAUDE.md` status_snapshot both still say 12086/0/0/133 (and cite `3be0e22e`, older than main `b73a2dd6`). The freshness test only checks the two agree, so both go stale silently at merge. Belongs to the post-merge gate run on a quiet box.

### 12. NOTE (quality, owned by #1646/#1648, not security) — sanitiser and re-ranker edges
- `fts_match_expr` drops every one-character token, so "C", "π", "x*" → empty expression → `[]`; a decomposed accent (`gre\u0301ece`) and a soft hyphen split words (`"gre" OR "ece"`, `"ec" OR "lipse"`); `words[:24]` silently truncates long queries. `_rerank` propagates NaN from the embedder as `vector_score=nan` and sorts on it (comment 3660 item 4's class) rather than reporting `None`. Reproduced in `probe_fts.py`. Also `search(candidates=-1)` would be `LIMIT -1` (unbounded) — not reachable from the tool path.

---

## What I attacked and could not break

- **FTS5 injection (item 5):** 40 hostile inputs through the real reader on a real store — quotes, `AND/OR/NOT`, `NEAR(...)`, column filters, `*`, `^`, `-`, `+`, braces, SQL, NUL, newlines, underscores, combining marks, zero-width chars, emoji, CJK, ligatures, 5,000-word and 200,000-char queries — no `OperationalError`, every expression a quoted-phrase OR list, worst case 3.5 ms. Empty phrases (`"__"`) match nothing without error.
- **Injection path (item 4):** a vandalised runner result carrying a forged `CONTEXT_END`, a `SYSTEM:` line, a raw `<tool_call>` tag and an embedded notice string went through `tools.execute` → `result_provenance` = untrusted_corpus, `is_retrieval_notice` False → GROUNDED branch → 8 datamarked lines, exactly one real `CONTEXT_END`, lock flipped, leak feed `[]` (Stage-5 exempt as decided). Notice predicate is exact-match (notice + one space is content); cap = 4000 with marker; runner exceptions → ERROR notice; `max_results` clamps 1..8; non-string query → EMPTY_QUERY notice. Risk tier GUARDED, not egress.
- **Licence boundary (item 6):** `tools/corpus/extract_rules.py` imports `html`, `re`, `unicodedata`, `typing` only; no `zim`/`libzim` import anywhere in the diff; `zstandard` is a lazy build-side import in the builder.
- **Import-time / network / writes (item 10):** nothing runs at import; no network client; builder writes only its CLI-given path; `shared.corpus` is not imported until the flag path; `_search_knowledge`/`_knowledge_retrieve` untouched by the diff.
- **Dormancy of the shipped config:** flag false, paths empty, no runner, notice returned, allowlisted, schema present, tests for all four (11 tests) pass; the partition of REGISTRY/ALLOWLIST/SCHEMAS is exact (11 = 11 = 11).
- **Manifest refusal paths** other than the config gap in finding 2: absent, corrupt, byte-flipped copy, empty/missing/wrong-typed digest, non-JSON — all REFUSED.
- **Docs:** ADR-023 A5 present with a numbering note; DEC-13 row present; journal fragment present, first-person narrative with plain summary, two unnumbered PROPOSED lessons and a Next — correct form; disposition verifier PASS 21/21.

## Merge read

- **I would block on:** finding 2 (a one-line fail-closed fix that the spec already promises), finding 4 (not a code fix — it is the LA's decision whether a "dormant" merge may change every live prompt; a merge that skips that question is the manufactured-approval failure in reverse), and a named merge motion for finding 10.
- **I would not block on, but would ticket before merge with `blocked-by:` predicates:** finding 1 (go-live blocker; needs the ADR sentence and an e2e toggle test — an LA-visible posture change), finding 3 (store rebuild sequencing with #1643), findings 5–9, 11, 12.
- **Not verified because of the box/brief:** the standing gate; `start()`'s registration block (finding 6); the real store through `reader.py` (would hash 39 GB); the 14B's spontaneous call rate (finding 4); the boot hash time (finding 8).
