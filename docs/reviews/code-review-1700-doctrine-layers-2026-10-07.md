# Adversarial review — docs/1700-doctrine-layers (#1700, carrying #1668)

Reviewed tip: `0ed40ad3` (worktree C:/Users/mrbla/BlarAI-worktrees/1700-doctrine, base main `1c2e42b7`). Scope moved from `45c15489` to `0ed40ad3` mid-review; every finding below was re-checked at `0ed40ad3`. Reviewer did not fix anything. All mutations were made on copies or restored byte-for-byte (sha256 verified; `git status` clean afterwards).

Run conditions: LOCALAPPDATA redirected to a scratch dir; interpreter C:/Users/mrbla/BlarAI/.venv/Scripts/python.exe (3.11) for pytest; the hook was ALSO driven through the real `.claude/settings.json` wrapper under `bash`, where `python` on PATH resolves to C:/Python314/python.exe (3.14.3) — that is the interpreter Claude Code actually runs it with on this machine. One live `claude -p --model sonnet` run in the worktree with state/log env redirected.

Counts: **1 BLOCKING, 3 SHOULD-FIX, 7 NOTE.**

---

## D1 — BLOCKING — Parallel tool calls from one agent produce a false "DOCTRINE DELIVERY FAILED" alarm (Windows `os.replace` race), and leak `.tmp` files

- **file:** `scripts/hooks/rules_inject.py:94-100` (`_write_state`), `:181-189` (`handle_session_start` TTL sweep globs `*.json` only).
- **what is wrong:** Two hook processes for the same agent key that both deliver a new rules file each write `<key>.<pid>.tmp` and `os.replace` it onto `<key>.json`. On Windows the second `os.replace` fails with `PermissionError: [WinError 5] Access is denied` while the first replace is in flight. The exception is caught by the catch-all and emitted as `DOCTRINE DELIVERY FAILED ... fix the hook or the rules file`, replacing the delivery; the orphaned `.tmp` is never cleaned (the TTL sweep only matches `*.json`).
- **scenario:** The ordinary first turn of any session or subagent: "Read CLAUDE.md, LESSONS.md and docs/TEST_GOVERNANCE.md" issued as three parallel Reads (the harness instructs parallel independent calls). Two or three of them deliver different rules files → race → the model receives a shouting notice telling it the hook is broken and to repair it. It is not broken. Cost: a session (or an author agent) stops to investigate/"fix" a working hook; a subagent reports a doctrine failure upward; the rule that lost the race is NOT delivered on that call (state not written, so it is retried on the next matching call — the delivery gap is one call, the false alarm is the real cost).
- **reproduced:** `C:/.../scratchpad/race2.py` — N parallel invocations of `python -I -S scripts/hooks/rules_inject.py`, same `agent_id`, each Reading a path that matches a different rules file; 25 turns per width:
  ```
  parallel=2: 25 turns, calls=50,  FAILED notices=22, turns with >=1 false alarm=22, orphan .tmp files=22
  parallel=4: 25 turns, calls=100, FAILED notices=38, turns with >=1 false alarm=22, orphan .tmp files=33
  parallel=8: 25 turns, calls=200, FAILED notices=39, turns with >=1 false alarm=23, orphan .tmp files=19
  ```
  Log line: `FAILED PermissionError: [WinError 5] Access is denied: '...\<key>.23496.tmp' -> '...\<key>.json'`.
  At width 2, 22 of 25 turns raised the false alarm. Width 2 is the common case.
- **incidence:** Not measurable from the banked corpus (no production log exists yet). The shape (parallel first-turn grounding reads touching 2+ rule subjects) is the default session opening.
- **lock gap:** `tests/security/test_doctrine_rules.py` runs every hook call serially; nothing exercises two concurrent calls on one key.

## D2 — SHOULD-FIX — Rules whose first application IS the triggering call arrive one call too late; reproduced live

- **file:** design of `rules_inject.py` (PreToolUse `additionalContext`), `.claude/rules/journal.md`, `.claude/rules/testing.md`, `.claude/rules/handoff.md`.
- **what is wrong:** PreToolUse `additionalContext` is attached to the tool RESULT; it cannot change the call already issued. For a rule whose first application is the write itself, the uninformed write goes out, then the rule arrives. Nothing blocks or re-asks.
- **scenario:** A subagent asked to write a journal fragment composes the entry with no knowledge of the entry form (dated `###` header, `*Plain summary:*`, first-person prose, `**Next:**`, "lessons proposed, never pre-numbered") and Writes it; journal.md arrives with the Write result. Same shape: first `pytest` of a fresh agent (selection/markers in testing.md), first landing-card Write (template path and location now only in handoff.md; CLAUDE.md's `<context_handoff>` no longer names the template or the directory).
- **reproduced (live):** `claude -p --model sonnet` in the worktree, prompt: Write `docs/journal_fragments/zz-review-probe.md`, then Read it, then report. Model's answer: *"The rule text first appeared after the Write was issued, attached to the Write result."* Hook log: `deliver journal.md to session:2a5d9704-ace type=main tool=Write reason=path ...zz-review-probe.md` (the only delivery; no Read preceded the Write). Probe file removed afterwards.
- **incidence:** structural; every first write to a rules subject by every agent that did not Read a matching file first. Mitigations exist (deny-with-reason on first uninformed write to a journal/handoff path, or carry the one-line entry form in `<rules_index>`), choice is the author's.

## D3 — SHOULD-FIX — performance.md is unreachable from the commands that actually run measurements (lenient direction)

- **file:** `.claude/rules/performance.md` frontmatter (`paths`: `scripts/*bench*`, `tools/probes/**`, `evals/**`, `docs/performance/**`; `x-blarai-commands`: `gh\s`, `benchmark`); `.claude/settings.json` matcher (no `WebFetch`).
- **what is wrong:** The rule "record AT THE TIME IT RUNS" exists to catch the session that runs a measurement and does not record it. That session never touches `docs/performance/**` or `PERFORMANCE_LOG.md`, so delivery depends on the RUN command — and the run commands this repo uses mostly miss the triggers.
- **reproduced** (real wrapper, `C:/.../scratchpad/probe.py`):
  ```
  python -m evals.run --suite all              -> []            (cited verbatim in PERFORMANCE_LOG.md)
  python scripts/measure_decode.py             -> ['coding.md'] (performance.md missed)
  Start-ScheduledTask -TaskName BlarAI-Battery -> []
  curl -s https://api.github.com/.../reviews   -> []            (gh matched, curl not)
  WebFetch https://github.com/x/y/pull/1       -> []            (WebFetch is not in the matcher at all; the rule "WebFetch of HTML misses them" is precisely the one needed here)
  ```
- **incidence:** `ls scripts`: 15 bench-named scripts (caught), **10 `measure_*` scripts and 14 probe-named scripts in scripts/ (missed)** — 24 of 39 measurement-script name shapes do not trigger. `python -m evals.run` appears in PERFORMANCE_LOG.md as a cited command and triggers neither performance.md nor testing.md.

## D4 — SHOULD-FIX — The new `enforces-rule` marker certifies a rule it does not test (gap list moved on an over-claim)

- **file:** `tests/security/test_doctrine_rules.py:3` — `enforces-rule: maintenance.register-of-claude-md-and-claude-rules -- the rules files keep the grammar, index and budget that make them doctrine`; `docs/governance/rules-corpus.yaml:1050-1058`; `docs/governance/rules-gaps.md` header.
- **what is wrong:** The rule is "Register of CLAUDE.md and .claude/rules/*: terse-directive, agent-only. Updates keep that register." The test checks frontmatter grammar, index/directory agreement, hook wiring and delivery. None of that observes register (prose style). The corpus now lists the rule as `kind: test` and the gap list dropped it: 142 of 169 gaps where the honest figure is 143 of 169 (`rules-gaps.md` on main listed `maintenance.this-file-s-register-is-terse-directive-agent-only` as `none`; the renamed rule vanished from the list because of this marker, not because of a new control).
- **reproduced:** `grep -n -A9 'id: "maintenance.register-of-claude-md' docs/governance/rules-corpus.yaml` shows the enforcement entry; `git diff main HEAD -- docs/governance/rules-gaps.md` shows the removal with no replacement row.
- **incidence:** 1 rule; but it is the first marker added under the #1690 "enforcement is trace-marked, the author asserts it" contract and it asserts more than it tests — attack #3 exactly.

## D5 — NOTE — The "unchanged rule text" claim: true for #1700's own commit; the tip carries five further text edits, all attributable

Mechanical comparison (`parse_corpus` on `git show main:docs/governance/rules-corpus.yaml` vs `baf39673` vs `0ed40ad3`, scratch `cmp.py`):
- main → baf39673 (#1668): `authority.this-is-claude-md` (history sentence removed), `maintenance.volatile-state-lives-only` (history clause removed), deferral MOMENTUM paragraph rewritten (id changed `the-trigger-is-not` → `the-trigger-is-momentum-not-laziness`; the dropped clause "momentum tickets have been reported to him as handled..." landed in agent-doctrine-evidence.md), `comprehension_gate.present-in-chat-in` (Six→Seven), `comprehension_gate.frequency` (+MONITORING line), `comprehension_gate.monitoring` added. Every removed clause is quoted verbatim in `docs/governance/agent-doctrine-evidence.md` ("History moved out of CLAUDE.md..."). Consistent with #1668's ticket description.
- baf39673 → 0ed40ad3 (#1700 + cherry-pick + WinUI fix): the three maintenance scope edits (two of which CHANGE RULE IDS: `maintenance.doctrine-changes-to-this` → `doctrine-changes-to-claude`, `maintenance.this-file-s-register-is-terse-directive-agent-only` → `register-of-claude-md-and-claude-rules` — ids derive from leading words, so the "rule ids unchanged" claim holds only for rules whose text did not change); `critical_rules.time-is-the-scarce-resource` (DEC-14 battery clause removed); `stack.app-layer` (WinUI build line). The `host_environment` rhythm line and the snapshot bullet are NOT visible to the corpus (fact line without an imperative marker; snapshot is volatile) — the CLAUDE.md diff shows them, the corpus cannot. 
- Lines that vanished from CLAUDE.md without landing in a rules file: none. Sources at tip: CLAUDE.md 130, testing 10, vikunja 8, journal 7, doctrine 6, performance 4, coding 2, handoff 2 (=169).
- `3c4b9eea` (cherry-picked as `629b96b5`) is on the four unmerged `feat/1616*`/`feat/1648`/`feat/1661` branches, not on main: identical content, will merge as a no-op; the DECISION_REGISTER conflict resolution (DEC-14 row only) is as described.

## D6 — NOTE — #1668 fix commit `7f68bae2` re-verified at `0ed40ad3`: the positional gate lock fires

On-disk mutations of the worktree's CLAUDE.md (restored byte-for-byte, sha `46c12294…` re-verified):
- delete line `7. MONITORING …` → `test_gate_section_list_complete_on_every_surface` FAILS naming `CLAUDE.md: MONITORING`; the mutation self-proof also fails (correct: baseline not clean).
- demote point 7 to prose (`Also state MONITORING — …`, text kept, number removed) → same two tests FAIL. This is the masking case the first lock missed; the positional lock sees it.
- remove "with a MONITORING line" from the delta-gate sentence → `test_delta_gate_carries_a_monitoring_line_on_both_surfaces` and the probe self-check FAIL; the whole-file lock stays green (as designed, the delta lock is the one that must see it).
The other three surfaces (sprint-kickoff.md, handoff-brief-template.md, LA_SPRINT_KICKOFF_HOWTO.md) were verified only through the test's own in-memory mutation (`test_gate_lock_fires_when_a_real_point_is_removed_from_a_real_surface`, 28 cases), which runs on the real file text.

## D7 — NOTE — `0ed40ad3` WinUI build-line claim checks out on disk

`launcher/__main__.py:613-616` `WINUI_EXE_REL = services/ui_winui/bin/x64/Debug/net8.0-windows10.0.19041.0/BlarAI.Desktop.exe` (base folder); `tests/harness/test_winui_input.py:36` and `test_winui_model_loaded.py:73` same base path. On disk both `…/BlarAI.Desktop.exe` and `…/win-x64/BlarAI.Desktop.exe` carry 2026-10-07 01:26 timestamps, consistent with the commit's measurement. Not re-measured by me: that the base exe launches today (the commit says so too).

## D8 — NOTE — Hook latency: ~140–180 ms per hooked tool call, untested and unrecorded

Real wrapper under bash + Python 3.14 (PATH): 27 calls, min 137 ms, max 178 ms, median ~144 ms, every Read/Write/Edit/Bash/PowerShell/MCP call. Bash/PowerShell calls also pay the git guard. A 400-tool-call session spends ~1 minute in this hook. Acceptable, but nowhere measured or budgeted; no test asserts an upper bound.

## D9 — NOTE — Over-inclusion shapes worth knowing (safe direction, token cost)

- `.claude/**` in doctrine.md matches USER-level paths: `Read C:/Users/mrbla/.claude/projects/.../memory/MEMORY.md` → doctrine.md delivered; `Read .claude/agents/dod-witness.md` → doctrine.md. Reproduced.
- Native path-scoping fired too: the live sonnet run reported the hook's journal.md block AND a `Contents of C:\...\.claude\rules\journal.md:` block on the same Write (Claude Code 2.1.292 native + hook = ~3 KB twice per file per agent that Reads/Writes a match). The hook has no way to know the native copy went out.
- `git -C <other-tree> add docs/journal_fragments/a.md` → journal.md (suffix match; intended).

## D10 — NOTE — Under-delivery shapes in the shell parser (reproduced)

- Heredoc whose terminator line carries trailing whitespace (`EOF ` ) never closes: everything after it in the same command is dropped (`cat > a.txt <<'EOF'\nx\nEOF \nsed -i … LESSONS.md` → nothing delivered).
- `vikunja.md`'s "Session start: project_summary" is delivered by the first Vikunja call — i.e. by `project_summary` itself, or never for a session that skips Vikunja. Circular by construction; CLAUDE.md grounding step 3 still carries the instruction, so no loss today.

## D11 — NOTE — The hook's real interpreter is not the tested one

`tests/security/test_doctrine_rules.py::Hook.run` executes `sys.executable -I -S` (the 3.11 venv). The wrapper in settings.json runs bare `python`, which under Git Bash on this machine is `C:/Python314/python.exe` (3.14.3). I drove the real wrapper with real payloads under 3.14: it works (27/27 calls rc=0, deliveries correct). The only wrapper test (`test_settings_wrapper_is_loud_when_the_script_is_missing`) exercises the missing-script branch, never a delivery through PATH python. If PATH ever lacks `python` or points at a 2.x/Store stub, the wrapper's fallback notice fires on EVERY tool call (fail-loud, by design — but loud on every call).

---

## What I attacked and could not break

- Rule-text verbatim move (D5): every CLAUDE.md line removed by `45c15489` is present in a rules file, byte-identical except the three declared maintenance edits.
- Grammar: all 11 deviation cases refuse; a single-string `paths:` is refused; BOM would be refused (first line ≠ `---`); CRLF is normalised by the parser. A fresh `git clone` with `core.autocrlf=true` checked the rules files out **LF** (3046 / 2749 bytes; CLAUDE.md 38,652) — the CRLF-on-checkout concern did NOT reproduce, and the hook ran correctly from that clone's rules dir.
- Dedupe keys: parent (session key) and child (agent key) are separate state files; the same agent is told once; a changed file (sha) is re-delivered; `SessionStart source=compact` resets. All via the real entry point.
- Fail-loud paths: bad frontmatter, missing dir, garbage payload, missing script (wrapper) all produce the notice with rc 0 (non-blocking).
- Security dimension: `grep -rn doctrine_rules|rules_inject` — referenced only by `scripts/`, `tests/`, `.claude/settings.json`, CLAUDE.md. No runtime module (shared/, services/, launcher/) imports either. Writes go to `BLARAI_RULES_INJECT_STATE_DIR` (default ~/.claude/state/rules_inject) and the log (default ~/.claude/logs/rules_inject.log) only; the log records the matched path token and reason, never command text.
- Extractor: `source` attribution correct for first (coding.md) and last (vikunja.md) spliced file; `--check` rc 0 at tip; duplicate-id and unclassified-tag refusals unchanged from #1690.
- `test_git_rules_guard._hook_entry` now selects the guard entry by command text; the guard entry itself is unchanged.

## Suites run

At `0ed40ad3`, LOCALAPPDATA redirected, 3.11 venv: `tests/security/test_doctrine_rules.py test_doctrine_freshness.py test_rules_corpus.py test_handoff_discipline.py test_git_rules_guard.py -m "not slow"` → **207 passed, 109 deselected, 0 failed, 0 skipped** (42.97 s). Same figure at `45c15489`. `scripts/extract_rules_corpus.py --check` → rc 0. No full gate, no slow tier, no GPU.

## Merge read

- **Block on D1.** A working hook that tells the model it is broken on most two-wide parallel turns is a fail-loud control firing on its own race; it will be reported upward as a doctrine failure by subagents and will invite "repairs". The fix is small (retry/ignore `PermissionError` on replace, or per-rule marker files, or a lock) and needs a concurrency lock in the test file; I did not write it.
- D2–D4 are should-fix before the ticket closes, not merge blockers: D2 is a design limit the author should either accept in writing (ticket + evidence) or close for the write-first rules; D3 is a trigger list; D4 is one marker line and a regenerated corpus.
- #1668 (D6) is sound at this tip; its prior-round fix is verified.
- Not blocking: D5 (claim slightly over-stated, every edit attributable), D7–D11.

---

# Fix verification — tip `2e45e003` (fixes in `2f556c60`)

Same reviewer, same run conditions (LOCALAPPDATA redirected; 3.11 venv for pytest; the hook driven through the real `.claude/settings.json` wrapper under bash, where `python` is C:/Python314). Per the coordinator's constraint no `test_git_*` file was run this round (a git-tier run was live in the worktree). Tree clean at `2e45e003` before and after; every probe used scratch state/log dirs.

Suites at `2e45e003`: `tests/security/test_doctrine_rules.py test_doctrine_freshness.py test_rules_corpus.py test_handoff_discipline.py -m "not slow"` → **136 passed, 0 failed, 0 skipped** (10.8 s). `extract_rules_corpus.py --check` rc 0. `scripts/verify_disposition.py` on the disposition record → PASS 11/11 (re-run by me).

## Verdicts

- **D1 — CLOSED.** `race2.py` re-run (different-file races, 25 turns per width): `parallel=2/4/8: FAILED notices=0, orphan .tmp=0` (was 22/38/39 notices). New same-file probe `race3.py` (N parallel calls all on LESSONS.md, 20 turns): Read → 0 failures, 0 orphans, 40/71/29 deliveries for 20 turns (duplicates, the documented cost); Write → 0 failures, every parallel Write held (40/70/28 holds for 20 turns), i.e. two parallel first-writes to one subject are both held and both re-issue — bounded, not a loop. Log shows 0 `left to a concurrent writer` lines, so the retry won every race here. Lock check: `test_parallel_calls_of_one_agent_never_raise_a_false_failure` run against the `45c15489` hook in a scratch copy → FAILED (the two hold tests also fail there) — the lock discriminates.
- **D2 — CLOSED for the file-writing tools; the shell-write path stays uninformed by documented choice (see E2).** Through the real wrapper: first `Write docs/journal_fragments/zz.md` → `permissionDecision: deny` with reason `HELD ONCE, NOT AN ERROR … journal.md`; re-issue → no output (passes); third → passes. No loop. `Write` with two subjects (`tests/security/test_x.py`) → one hold naming both `coding.md` and `testing.md`. `NotebookEdit` under tests/ → held. Rules digest: a trailing-newline-only edit to the rules file does not re-hold (body is rstripped); a real body change re-delivers (my mutation broke the grammar, which correctly produced the FAILED notice, not a hold). After `SessionStart source=compact` the next Write to the subject is held again — by design (compaction dropped the delivery), one extra round trip per subject per compaction.
- **D3 — CLOSED.** All five reviewer misses now deliver `performance.md` through the real wrapper: `python -m evals.run --suite all`, `python scripts/measure_decode.py` (+coding.md), `Start-ScheduledTask`, `curl …api.github.com…`, `WebFetch https://github.com/…`. Each is a row in `test_shell_commands` / `test_tool_triggers_and_unrelated_calls`.
- **D4 — CLOSED.** Marker gone from `test_doctrine_rules.py:3`; `rules-gaps.md` header reads 143 of 169 (140 none, 3 reviewer-only) and lists `maintenance.register-of-claude-md-and-claude-rules | none`.
- **D11 — CLOSED.** `test_settings_wrapper_delivers_through_the_python_on_path` drives a real delivery through the wrapper with PATH python; passes at tip (3.14.3 on this machine).
- **D5, D6, D7 — REJECTED rows accepted.** They were recorded as non-defects by me; the disposition's arguments restate that and correct the id claim where it was made.
- **D8 — REJECTED row accepted.** Agree a wall-clock assertion on this laptop would measure the machine, not the hook; the figure is recorded in this review, which is the right home for tooling latency.
- **D9 — REJECTED row accepted**, with the new consequence recorded under E1: over-delivery was the safe direction while the hook only informed; a hold is a deny, and the same over-inclusion now denies.
- **D10 — REJECTED row accepted.** Checked: bash's heredoc terminator must match the delimiter exactly, so `EOF ` (trailing space) does not close it in bash either; the parser models the shell. `project_summary` is grounding step 3 in CLAUDE.md, so vikunja.md need not arrive first.

## Hold attacks (coordinator's questions)

- **Can it loop?** No. Delivery is marked before the deny is emitted; the re-issued identical call passes (probe rows 1–3). The only repeat seen is two *parallel* first-writes to one subject both being held (race3), which resolves on their re-issue.
- **Can it deny something that is not a write to a rules subject?** Yes — see **E1**. The subject test is the suffix-matched glob, which reaches outside the repository.
- **Can it fire on a hook failure?** No. With `BLARAI_RULES_DIR=C:\nonexistent` and with a garbage payload, a Write receives `additionalContext: DOCTRINE DELIVERY FAILED …`, never `permissionDecision` (probe rows 12–13; `parse_output` in the tests also asserts deny and additionalContext are never both present). The wrapper's missing-script fallback is additionalContext only.
- **Parallel Read and Write of the same subject?** If the Read's hook marks first, the Write is **delivered-but-unheld**: probe row 11 (`Read LESSONS.md` → deliver journal.md; then `Write docs/journal_fragments/zz.md` → passes, no hold). In a real parallel batch both calls were composed before either hook ran, so that Write goes out uninformed; the rule reaches the model with the Read's result. If the Write's hook marks first, it is held and the Read passes silently (the model then sees the rule once, in the deny reason). Not reproduced live (whether Sonnet would issue a Read and a Write of one subject in one batch is model-dependent); the hook-level ordering is deterministic as shown. See **E3**.
- **Is an unheld write informed?** Only when something earlier delivered the rule to that agent (a Read, a Bash path token, a prior hold). A Bash/PowerShell write (`cat >> BUILD_JOURNAL.md <<EOF`, `Add-Content LESSONS.md`) on a fresh agent is delivered as additionalContext and not held (probe rows 9–10) — **E2**.

## New findings

- **E1 — SHOULD-FIX — The hold denies writes outside the repository and the user's own auto-memory.** `scripts/hooks/rules_inject.py` HOLD_TOOLS × `doctrine_rules.path_matches` (suffix match, any checkout). Reproduced through the real wrapper, fresh agent key each: `Write C:\Users\mrbla\AppData\Local\Temp\claude\…\scratchpad\probe.py` → `HOLD(deny) ['coding.md']`; `Edit C:\Users\mrbla\.claude\projects\C--Users-mrbla-BlarAI\memory\MEMORY.md` → `HOLD(deny) ['doctrine.md']`; `Write C:\Users\mrbla\.claude\CLAUDE.md` → `HOLD(deny) ['doctrine.md']`; `Write C:\Users\mrbla\agentic-setup\run.ps1` → `HOLD(deny) ['coding.md']`; `Write <repo>\README.md` → passes. Cost: every agent's first scratch-script write and the session's first memory write are denied with a message that calls the maintenance section "binding doctrine" for a file it does not govern, and tells the model to correct the write to it. Under D9 this over-inclusion only cost tokens; a deny is a different instrument. Incidence: structural — every subagent that writes a scratch `.py`, every auto-memory save. The lock `test_hold_applies_only_to_file_writing_tools` does not probe an out-of-repo path.
- **E2 — NOTE — Shell writes to a rules subject remain uninformed (delivered-with-result).** `cat >> BUILD_JOURNAL.md <<'EOF'` and `Add-Content LESSONS.md` on a fresh agent → `deliver ['journal.md']`, no hold. This is the bypass the hook docstring cites as measured ("shell writes bypass a Write/Edit trigger") and `test_hold_applies_only_to_file_writing_tools` locks it as intended; holding Bash on path tokens would deny `git add docs/journal_fragments/x.md`. Documented choice; the disposition's "FIXED" for D2 should be read as "fixed for the file-writing tools".
- **E3 — NOTE — Read+Write of one subject in a single parallel batch leaves the Write unheld and uninformed** (hook-level ordering shown above; live behaviour not measured). Low incidence: a model reads to inform a later write, rarely both at once.
- **E4 — NOTE — `^WebFetch$` and the `probe`/`bench` command regexes over-include:** `WebFetch https://code.claude.com/docs/en/hooks` → performance.md; `git log --grep probe` → performance.md. Safe direction, ~1.5 KB once per agent; recorded so the next reviewer does not re-find it.

## Merge read after the fix round

D1 (the blocker) is closed with a discriminating lock; D2–D4 and D11 closed as claimed. I would not block the merge on E1, but it is the same shape as D1's cost (a control shouting at an ordinary action) in a weaker form, and it is one `path_matches` scope decision plus a lock row; it belongs in the disposition before #1700 closes. E2–E4 are records.

---

# Fix verification 2 — tips `19d746d1` → `69b7d8d1` → `1c8acaf8`

The tree moved twice during this round: `19d746d1` (E1 fix: cwd-anchored resolution to the nearest ancestor whose CLAUDE.md opens with `<blarai_project_instructions`, anchored globs), `69b7d8d1` (disposition rows E1–E4), then `1c8acaf8` (`is_local_path` / `_DRIVE_RELATIVE`: nothing is opened on a non-local path). Probes were run through the real settings.json wrapper against the working tree (which at the time carried the `1c8acaf8` change uncommitted) and, for the open-audit, against copies of the committed `doctrine_rules.py` at `69b7d8d1` and `1c8acaf8` under a `sys.addaudithook` spy on `open`. No `test_git_*` file was run. Tree left clean apart from this file.

Suites at `1c8acaf8`: the four targeted non-git files → **145 passed, 0 failed, 0 skipped**; `verify_disposition.py` → PASS 15/15.

## E1 — CLOSED

Through the real wrapper, fresh agent key each: `Write <scratchpad>/probe.py` → none; `Write C:\Users\mrbla\.claude\CLAUDE.md` → none; `Edit …\memory\MEMORY.md` → none; `Write C:\Users\mrbla\agentic-setup\run.ps1` → none; control `Write <wt>\docs\journal_fragments\zz.md` → `HOLD ['journal.md']`. Lock check: `test_nothing_outside_a_blarai_checkout_is_a_rules_subject` and `test_paths_resolve_to_the_blarai_checkout_that_holds_them` FAIL against the `2e45e003` hook in a scratch copy — the locks discriminate.

## Attacks on the new resolution (all through the real wrapper; latency per call 139–166 ms, unchanged from the 137–178 ms baseline, so the walk-up costs nothing measurable even on a 60-token command)

| case | result |
|---|---|
| payload without `cwd`, absolute Read | delivered (hook falls back to its own cwd) |
| payload without `cwd`, relative Bash token, process cwd = worktree | delivered |
| cwd `<wt>/docs`, Bash `cat ../LESSONS.md` | delivered, reason `path LESSONS.md` |
| cwd = primary checkout, Bash `cat LESSONS.md` | delivered (primary's CLAUDE.md carries the root tag) |
| cwd = home (non-repo), Bash `cat LESSONS.md` | none (correct: not a subject) |
| cwd = home, `git -C C:/…/1700-doctrine add docs/journal_fragments/a.md` | **none** — see F1 |
| cwd = wt, `git -C C:/…/other add docs/journal_fragments/a.md` | delivered (relative token resolved against cwd, right rule by coincidence) |
| lowercase drive `c:\users\…\LESSONS.md`, mixed slashes `C:/…\LESSONS.md`, upper-case path | delivered |
| `..` escaping the repo | none |
| `<wt>\models\qwen3-14b\manifest.json` | none (`models` is not a rules subject; no junction exists in this worktree — `dir /AL` empty, `models/` empty — so junction traversal was not exercisable) |
| nested checkout `<x>/.claude/worktrees/wt1/LESSONS.md` with its own tagged CLAUDE.md | delivered journal.md, rel `LESSONS.md` (nearest ancestor wins) |
| nested `<x>/.claude/worktrees/wt1/.claude/agents/x.md` | delivered doctrine.md, rel `.claude/agents/x.md` |
| nested checkout whose CLAUDE.md starts with a UTF-8 BOM | **invisible**: resolved to the PARENT checkout as `.claude/worktrees/wt2/LESSONS.md` → doctrine.md delivered, journal.md not — see F2 |
| Bash glob token `ruff check **/*.py` | coding.md (literal `**/*.py` matches the regex; over-delivery, harmless) |
| `cat ~/.claude/CLAUDE.md` | none (`~` not expanded; resolves under cwd, no match) |
| relative Write `docs/journal_fragments/zz.md` | held |
| **Git-Bash absolute `/c/Users/mrbla/BlarAI-worktrees/1700-doctrine/LESSONS.md`** in Bash and in Read | **none** — see F1 |

### Open-audit (committed resolvers, spy on `open`)

At `69b7d8d1`: `//attacker/share/x/LESSONS.md` → opened `\\attacker\share\x\CLAUDE.md` and `\\attacker\share\CLAUDE.md`; cwd `//attacker/share/wt` + `LESSONS.md` → opened `\\attacker\share\wt\CLAUDE.md`; `//./pipe/x` → opened `\\.\pipe\CLAUDE.md`. Reproduced: the committed E1 fix opened attacker-controlled network paths inside a PreToolUse hook, before the permission check (the NTLM-leak the automatic review flagged).

At `1c8acaf8`, 20 forms: `//attacker/share/…`, `\\attacker\share\…`, `//?/UNC/attacker/share/…`, `//?/C:/…` (local extended form, refused — over-refusal, harmless), `//./pipe/x`, cwd on a UNC share, `C:LESSONS.md`, `C:/Users/mrbla/../../../attacker/share/…` (normpath keeps it on C:), `<wt>//attacker/share/LESSONS.md` (collapses to a local path under the repo), `file://attacker/…` and `http://attacker/…` (not absolute → joined under cwd, local opens only), `%USERPROFILE%/…`, `$HOME/…`, `~/…` (not expanded, local), 8.3 `C:/Users/mrbla/BLARAI~1/…` (local opens, short name did not resolve to a checkout) → **zero network opens in every case**. `Z:/LESSONS.md` opens `Z:\CLAUDE.md` — the stated mapped-drive residual; nothing else reaches a host. A junction or symlink inside a checkout whose target is a network share would be traversed by the walk-up (the walk-up starts at the file's parent); none exists here, and it would be the operator's own junction.

Walk-up still finds worktrees: worktree, primary checkout and nested `.claude/worktrees/*` all resolve (table above).

## New findings

- **F1 — SHOULD-FIX — Git-Bash absolute paths (`/c/Users/…`) are invisible to the resolver, so Bash-tool commands written in this machine's native form deliver nothing.** `os.path.isabs('/c/Users/…')` is true on Windows and `normpath` makes it `C:\c\Users\…`, which has no checkout ancestor → `rel=None`. Reproduced through the real wrapper: `cat /c/Users/mrbla/BlarAI-worktrees/1700-doctrine/LESSONS.md` → none; the same path in a Read payload → none; `git -C C:/…/1700-doctrine add docs/journal_fragments/a.md` from a non-repo cwd → none (the `-C` target is not used as a base). Under the pre-`19d746d1` suffix match all three delivered. Incidence: every Bash command in this review session used the `/c/…` form, and the harness note for agent threads ("cwd resets between bash calls, use absolute paths") pushes exactly this shape; the `cd /c/…/<wt> && <relative tokens>` idiom only works today because the relative tokens resolve against the payload cwd, which is the *session* cwd, not the `cd` target — a session started outside a BlarAI checkout delivers nothing for it. The lock `test_shell_commands` has no `/c/` row.
- **F2 — NOTE — A checkout whose CLAUDE.md starts with a BOM (or any first-200-chars variation) is invisible and its files are attributed to the parent checkout** (nested-checkout probe: journal.md missed, doctrine.md delivered). CLAUDE.md is LF-pinned and BOM-free in this repo; recorded as the failure shape of the marker test.
- **F3 — NOTE — `//?/C:/…` local extended-length paths are refused** by `is_local_path` (the `//` prefix test fires before the drive test). Harmless (Claude Code never emits them), noted so a future "extended path" report is not re-investigated.

## E2–E4 rejections

- **E2 holds.** The shell parser cannot distinguish a read token from a write target; holding Bash would deny `grep`, `cat`, `git add` on any rules path. Stated in the hook docstring and locked by `test_hold_applies_only_to_file_writing_tools`.
- **E3 holds.** The window needs a first Read and a first Write of one subject in the same parallel batch; the residual equals pre-fix behaviour and the rule still arrives in that turn.
- **E4 holds.** One over-delivery of ~1.5 KB per agent; the triggers are broad so the measurement and upstream rules reach the calls they govern.

## Merge read after round 2

E1 closed; the `1c8acaf8` credential-leak fix verified with a spy on `open` across 20 bypass forms (mapped drives remain the only stated residual). F1 is a real coverage regression from the E1 fix on this machine's dominant Bash path form — one normalisation (`^/([a-zA-Z])/` → `X:/`) and a `test_shell_commands` row; it should be in the disposition before #1700 closes. F2–F3 are records. Nothing blocks the merge.

---

# Fix verification 3 — tip `023b674d` (fix `d4694e4c`; disposition `951ee68b`/`023b674d`)

Scope: `checkout_roots` (roots from `.git` pointer / `commondir` / `worktrees/*/gitdir` only), `repo_relative` (purely lexical), `posix_drive` (`/c/`, `/cygdrive/c/`, `/mnt/c/` → `C:/`), and the `git -C` / `cd` / `pushd` / `Set-Location` re-basing in `select()`. Suites at `023b674d` (four targeted non-git files): **153 passed, 0 failed, 0 skipped**; `verify_disposition.py` PASS 19/19. Tree clean apart from this file.

## Verdicts

- **S1 — CLOSED.** `audit3.py` installs `sys.addaudithook` on `open`, `os.stat`, `os.lstat`, `os.scandir`, `os.listdir`, `pathlib.Path.glob`, `os.readlink`, then calls the tip's `repo_relative` on 44 forms (the 20 bypass forms from round 2, the F1 forms, and the lexical attacks below): **zero filesystem events for every tool-call path**. The only reads are in `checkout_roots`, which touched 14 git-metadata files for this repository in 2.3 ms. Mapped drive `Z:/LESSONS.md` → `None` with no event (the round-2 residual is gone).
- **F1 — CLOSED.** Through the real wrapper with cwd = home: `cat /c/Users/mrbla/BlarAI-worktrees/1700-doctrine/LESSONS.md` → journal.md; the same path in a Read → journal.md; `/cygdrive/c/…` and `/mnt/c/…` → journal.md; `git -C C:/…/1700-doctrine add docs/journal_fragments/a.md` → journal.md (`path docs/journal_fragments/a.md`); `cd /c/…/1700-doctrine && cat LESSONS.md` and `cd "C:/…" && sed -i … LESSONS.md` → journal.md. `/C/…` (upper-case drive letter) also resolves; `/c`, `/cygdrive`, `/mnt/cx/…`, `/tmp/…` → `None`.
- **F2 — REJECTED row holds.** No CLAUDE.md is read; a BOM cannot affect git metadata.
- **F3 — REJECTED row holds.** `//?/C:/…` → `None`, no event; the cost is one late delivery for a form no tool emits.
- **E1 still closed** at this tip: scratchpad `.py`, `~/.claude/CLAUDE.md`, memory `MEMORY.md`, `~/agentic-setup/run.ps1` → none; in-repo fragment Write → held.

## Lexical attacks (direct calls, plus the real wrapper where marked)

| attack | result |
|---|---|
| case: `c:/USERS/MRBLA/BLARAI-WORKTREES/1700-DOCTRINE/LESSONS.md`, cwd `c:/users/…` | `LESSONS.md` (normcase both sides); wrapper: delivered |
| trailing separator: `<wt>/` and `<wt>` | `None` (the root itself is not a subject); `<wt>/docs/` → `docs` |
| doubled separators `<wt>/docs//journal_fragments//a.md` | `docs/journal_fragments/a.md` |
| `..` climbing out after entering a root: `<wt>/docs/../../other/LESSONS.md` | `None`; wrapper: none |
| `..` out and back in: `<wt>/../1700-doctrine/LESSONS.md`, `docs/x/../../LESSONS.md` | `LESSONS.md` |
| root that is a string prefix of another: `C:/Users/mrbla/BlarAI-worktrees/other/…`, `C:/Users/mrbla/BlarAIx/…`, `C:/Users/mrbla/BlarAI-worktrees/LESSONS.md` | `None` for all three (the `root + sep` guard holds); `C:/Users/mrbla/BlarAI/LESSONS.md` → `LESSONS.md` |
| nested checkout inside the primary: `C:/Users/mrbla/BlarAI/.claude/worktrees/trust-spine-research-fc3344/LESSONS.md` | `LESSONS.md` (longest root wins); `…/.claude/agents/x.md` → `.claude/agents/x.md`; wrapper: journal.md / doctrine.md |
| UNREGISTERED nested dir `C:/Users/mrbla/BlarAI/.claude/worktrees/unknown-wt/LESSONS.md` | `.claude/worktrees/unknown-wt/LESSONS.md` → attributed to the primary (doctrine.md would fire, not journal.md) — only a copy that is not a git worktree hits this; NOTE G2 |
| cwd with trailing slash / `docs/..` / lower-case | `LESSONS.md` |
| drive-relative `C:LESSONS.md` with cwd in the worktree | `LESSONS.md` (ntpath join keeps the drive; lexical, no open — the round-2 refusal is no longer needed) |
| UNC token in Bash, UNC cwd + relative token (wrapper) | none, no event |
| `%USERPROFILE%/…`, `$HOME/…`, `~/…`, `file://…`, `http://…` | not expanded; join under cwd, no match, no event |
| per-call latency (real wrapper, 22 calls incl. a 60-token command) | 137–151 ms, unchanged |

## `checkout_roots` on unusual git state (scratch repository, never the real one)

| state | result |
|---|---|
| primary; linked worktree; `--lock`ed worktree | roots complete from either side; locked makes no difference |
| prunable worktree (folder removed, metadata stale) | root kept (lexical, no existence check) — harmless over-inclusion |
| `worktrees/<x>/gitdir` file EMPTY | silently adds the junk root `'.'` (never matches an absolute path) — NOTE G1 |
| junk FILE under `.git/worktrees/`; `worktrees/<dir>` with no `gitdir` | `FileNotFoundError` → every tool call reports DOCTRINE DELIVERY FAILED until `git worktree prune`/repair; loud, as the docstring promises |
| `.git` pointer forms (forward slashes, no space after `gitdir:`, garbage) | NOT exercised: my probe hit a `PermissionError` writing the scratch worktree's `.git` file after `worktree repair` (the file is read-only); the real pointers of all 13 worktrees resolved, and the garbage form raises `ValueError` by inspection |

On this machine `checkout_roots` returns 14 roots, including two scratch worktrees another session registered under `%TEMP%` (`…/scratchpad/rev2/base`, `…/mut`): correct, since they are checkouts of this repository.

## New notes

- **G1 — NOTE** — an empty `worktrees/*/gitdir` file yields a `'.'` root silently instead of raising; harmless (can never contain an absolute path) but inconsistent with the "any unreadable entry raises" docstring.
- **G2 — NOTE** — a directory under a checkout that is not a registered worktree (a plain copy) is attributed to its parent checkout, so `.claude/worktrees/<copy>/LESSONS.md` matches `.claude/**` (doctrine.md) and misses journal.md. Git worktrees, including Claude Code's own `.claude/worktrees/*` isolation, are registered and unaffected.
- **G3 — NOTE** — `select()` re-bases relative tokens against every token following `-C`/`cd`/`pushd`/`Set-Location`; a quoted base containing spaces splits into several tokens and the re-base silently misses (one late delivery). No such path exists in this constellation.

## Merge read after round 3

S1 and F1 closed with evidence that no tool-call path reaches the filesystem and that this machine's Bash path forms resolve; F2/F3 rejections hold; E1 and D1–D4/D11 remain closed at this tip. G1–G3 are records. Nothing blocks the merge.
