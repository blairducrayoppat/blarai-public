---
title: "#1585 single-importer scan — adversarial review disposition"
status: final
area: security
---

# Disposition — #1585 (the egress scan gets a synthetic violator, and honest roots)

**Review run 2026-09-18, pre-merge, by an agent that did not write the code.** Target `48c867b2` on
`fix/1585-synthetic-violator`, off main `e9f9ee2b`; fixes in `7ce108d9`. It ran 27 mutants
file-scoped and re-ran five of them against the full security tier; its own restore was verified by
md5 against a pristine backup.

**The verdict in one line: the roots half is correct and LARGER than I claimed; the off-test half
proved a helper the standing gate does not run.**

```disposition
# finding | status | evidence-or-predicate
review finding 1 (HIGH) — THE OFF-TEST DID NOT TEST THE SCAN. test_runtime_imports_no_external_network_library — the assertion the standing gate executes, and the one the module docstring is entirely about — carried its OWN copy of the violation loop, hardcoded to _REPO at two points, so it could not be pointed at a synthetic tree and TestTheScanIsTestedOff never called it. Mutant M20 (its loop body replaced with `for f in []`, so it can never flag anything) SURVIVED the full security tier; so did M7 (the exemption widened to excuse every file). I extracted a shared collector and then wired only the COMPANION test to it — a correct mechanism with no consumer, in the file written to retire exactly that defect | FIXED | 7ce108d9 — the violation loop is now `_unexempted_violations(repo)` with the operator-facing text in `_violation_message(violations)`, both taking a repo root; the primary test is three lines that call them. TestTheScanIsTestedOff gains test_the_PRIMARY_gate_assertion_fails_on_the_planted_tree and its clean-tree control, which drive THAT function. M20 and M7 now both die
review finding 2 (HIGH) — LOSING A WHOLE RUNTIME ROOT WAS STILL UNDETECTABLE, which is the same invisible-root defect this commit exists to retire, one level up. Deleting "launcher" from _RUNTIME_ROOTS (240 -> 226 files, taking launcher/__main__.py with it — the module that ARMS the egress guard and WIRES this screen) survived the full tier, because every anchor in the drift guard named a path inside services/. So did M3 (rglob("*/*.py"), which silently drops every file directly under a root: all 14 launcher modules plus shared/constants.py, shared/timeout_registry.py and 10 more). `assert len(files) >= 20` against an actual 240 permitted 92% of the surface to disappear | FIXED | 7ce108d9 — ONE ANCHOR PER ROOT: launcher/__main__.py and shared/timeout_registry.py asserted by exact path, the second of which also catches the rglob narrowing. The floor is 200 against a real 240 — deliberately not an equality, because a brittle count trains people to bump numbers without reading, and the gap absorbs ordinary growth while any lost ROOT trips it. M24, M24b and M3 all die
review finding 3 (MEDIUM-HIGH) — 17 OF THE 18 FORBIDDEN MODULES WERE NEVER EXERCISED. Reducing _FORBIDDEN_TOP_LEVEL to {"httpx"} — dropping requests, aiohttp, urllib3, smtplib, paramiko, boto3, botocore, openai, anthropic, cohere and the rest — survived the full tier. The cross-file drift lock in test_search_docs_cli_controls.py asserts a SUBSET, which by construction passes on a removal; its docstring is honest about growth, and this file and the register both read as though the set were locked | FIXED | 7ce108d9 — both sets pinned by EQUALITY against _EXPECTED_FORBIDDEN_TOP_LEVEL / _EXPECTED_FORBIDDEN_DOTTED in test_the_forbidden_sets_have_not_SHRUNK, whose failure message names what was removed and what was added. A deliberate removal is now an edit in two places. M12b dies
review finding 4 (MEDIUM-HIGH) — THE ENTIRE ast.ImportFrom BRANCH AND ALL OF _FORBIDDEN_DOTTED WERE UNTESTED. The fixture planted only `import httpx`, an ast.Import. Four independent mutants survived: the ImportFrom branch made dead, _FORBIDDEN_DOTTED emptied, the dotted clause dropped from the primary test, and the deletion of the `mods.add(f"{mod}.{alias.name}")` expansion whose own comment reads `# from urllib import request`. `from httpx import AsyncClient` is the ordinary idiom | FIXED | 7ce108d9 — the fixture plants `from httpx import AsyncClient` in a second service and `from urllib import request` in a third file, each with its own test, and each with a benign counterpart in the clean tree (`from json import loads`, `from urllib import parse`) so only the rule under test can produce the difference. urllib is the right discriminator: urllib.parse is pure parsing and urllib.request is the network part, which is why the dotted set exists at all. M4, M16 and M18 all die
review finding 5 (MEDIUM) — A SINGLE-PLANT FIXTURE CANNOT DETECT A SCAN THAT REPORTS ONLY THE FIRST VIOLATOR. With one plant, "finds one" and "finds all" are the same observation, and a collector returning immediately after its first setdefault survived the full tier | FIXED | 7ce108d9 — three violators across two services, and test_EVERY_violator_is_found_not_merely_the_first asserts the exact set rather than membership. M1 dies
review finding 6 (MEDIUM) — THE "NAMES THE VIOLATOR" ASSERTION COULD NOT FAIL. It rebuilt `rendered` inside the test from the dict the preceding line had already asserted contained the violator. Self-referential. The REAL failure text — the one the gate prints and an operator reads — was exercised by nothing, and stripping the paths out of it left the file 11/11 green, while the docstring claimed "the message is part of the control" | FIXED | 7ce108d9 — the message is built by a production helper, `_violation_message`, and test_the_OPERATOR_FACING_MESSAGE_names_the_violating_paths calls THAT and asserts all three planted paths appear and the sanctioned door does not. M22 dies
review finding 7 (MEDIUM) — "231 FILES SCANNED BEFORE" WAS ARITHMETIC PRESENTED AS A MEASUREMENT. It is 240 minus the nine ui_shell/voice modules. Run against the parent commit's own scan code on this tree, the real figure is 220 — the eleven `services/*/__init__.py` package markers were invisible to the old list too, so the real delta is 20, not 9 | FIXED | 7ce108d9 — re-measured independently rather than taking the reviewer's number: 220 old, 240 new, 20 newly covered (11 package markers, 7 ui_shell/src, 2 voice/src), 0 lost. Row 13 carries the corrected figures and says in as many words that the earlier number was reconstruction rather than a run, and that the widening is larger than first claimed. This is the standing rule about deriving what a direct check would settle, and the direct check was one command away
review finding 8 (MEDIUM) — THE REGISTER ROW CITED LINE NUMBERS THE SAME COMMIT INVALIDATED, and its "Stated limitation" column stated no limitation. `_EGRESS_DOOR_EXEMPTION (:81-83)` landed on comment prose and `test_exactly_one_...:144-172` landed inside `_imported_modules`. Worse, the column that had named a real limit (no synthetic-violator test) now held only the fix narrative — a confident value where an absence belongs, while five mutants were unkilled | FIXED | 7ce108d9 — tests cited by NAME, with the reason stated: line citations were invalidated by the commit that wrote them. The column now names two real limits — the dynamic-import gap (importlib.import_module, __import__, exec, getattr, which no static scan reaches) and the fact that the single-door property holds only WITHIN the three roots, with the one sanctioned counter-example named
review finding 10 (LOW) — THE EXCLUSION MATCHED ANCESTOR DIRECTORIES ABOVE THE REPO ROOT. `f.parts` on an absolute path includes every segment of the checkout path, so a repository — or a git worktree, which is where this one lives, under `.claude/worktrees/` — sitting beneath a directory named `tests` or `__pycache__` scanned ZERO files. It failed loud on the "root paths drifted?" assert rather than passing green, so robustness and not a fail-open; but the commit's own standard is that zero files must never be quietly wrong, and the fix addressed the frozen default while leaving this on the line beside it | FIXED | 7ce108d9 — relative to the repo. The first attempt shipped WITHOUT a lock and mutant M10 survived, because the fixed and unfixed forms are indistinguishable unless the repo actually sits under such a directory and no ordinary tmp_path does. test_a_repo_UNDER_a_directory_named_tests_is_still_scanned constructs that path deliberately, for both excluded names. M10 now dies
review finding 11 (LOW) — THE FIXTURE HARDCODED THE DOOR PATH rather than deriving it from _EGRESS_DOOR_EXEMPTION, so moving the door or editing the exemption breaks the ON control for a reason unrelated to what it measures, and the next maintainer's instinct is to edit the fixture | FIXED | 7ce108d9 — the door path is `next(iter(_EGRESS_DOOR_EXEMPTION))`, so the fixture follows the exemption instead of shadowing it
review finding 9 (LOW-MEDIUM) — A SCANNED RUNTIME MODULE REACHES urllib.request BY DELEGATING ONE DIRECTORY OUTSIDE THE SCAN. shared/fleet/vikunja_bridge.py:168-172 imports tools.dispatch_harness.vikunja_http, which imports urllib.request — a _FORBIDDEN_DOTTED member. Proven by execution, module-level, and reached in production via launcher/__main__.py:600. The register's new sentence "a new service is covered the moment it exists" is true only inside services/, shared/ and launcher/ | REJECTED | Not a defect of this change, and not a hidden one: it is argued in ADR-039 §222-228, in the July journal archive, and pinned by tests/security/test_dependency_truth.py as "the ONE runtime-root reference to it". The traffic is loopback-pinned twice and the egress guard constrains it independently. The reviewer's own AST sweep of all 240 scanned files found exactly one such delegation and it is the sanctioned one. What WAS wrong is the register's wording, and that is fixed under finding 8 — the row now states the within-three-roots limit explicitly rather than leaving the sentence to overreach
reviewer's note — WHAT IT ATTACKED AND COULD NOT BREAK | REJECTED | Not defects. The widening was independently enumerated: 20 files newly covered, 0 lost, every one genuine runtime (launcher/__main__.py imports services.ui_shell.src.app and services.voice.src.engine at module level, so both trees are unambiguously shipped). Nothing inappropriate is swept in — services/ui_winui holds zero .py files, no vendored/generated/build/dist/site-packages directory exists under the three roots, and all four conftest.py files live inside tests/ directories. Windows case behaviour errs safe: `Tests/` and `TESTS/` are FLAGGED, not skipped. Path matching is by exact component, not substring: src/tests_helpers/, src/testing/ and shared/testsupport/ are all flagged. _imported_modules catches every realistic static form including as-aliases, function-local, class-body, try/except ImportError and TYPE_CHECKING-guarded. The exemption is a true exact-path match against three synthetic door placements. My own five mutants genuinely die with distinct discriminating tests, and the split of the two dev-tier plants does isolate the two exclusion rules exactly as claimed
```

## Mutation, round 2

Twelve mutants against `tests/security/test_no_external_egress.py`, including **every one of the
five that survived the full security tier** at `48c867b2`. All dead; baseline and restore both 19
passed.

| mutant | at `48c867b2` | at `7ce108d9` |
|---|---|---|
| M20 the primary gate assertion can never flag | SURVIVED (full tier) | DEAD |
| M24 the `launcher` root dropped | SURVIVED (full tier) | DEAD |
| M24b the `shared` root dropped | not tried | DEAD |
| M12b only `httpx` remains forbidden | SURVIVED (full tier) | DEAD |
| M4 the `ast.ImportFrom` branch dead | SURVIVED (full tier) | DEAD |
| M1 the collector reports only the first violator | SURVIVED (full tier) | DEAD |
| M3 `rglob` loses files directly under a root | SURVIVED | DEAD |
| M7 the exemption excuses every file | SURVIVED | DEAD |
| M22 the operator message names no paths | SURVIVED | DEAD |
| M16 the dotted forbidden set emptied | SURVIVED | DEAD |
| M18 the `from x import y` expansion deleted | SURVIVED | DEAD |
| M10 the exclusion matches absolute ancestors | (the fix itself) | DEAD |

M10 is worth its own line: the FIX shipped in the first round of these repairs and had no lock, and
the mutant survived my own first harness run. The fixed and unfixed forms are indistinguishable
unless the repository actually sits beneath a directory named `tests` — which no ordinary `tmp_path`
does, and which this worktree very nearly is.

## Verification

`tests/security/` after the fixes: **1320 passed, 2 failed, 0 skipped, 96.88 s**, elevated — the 2
are the known ADR-013 worktree artifact. The file itself went 6 → 11 → 19 tests.

## The honest note

The ticket was "nothing proves the detection fires on a genuine new violator". I wrote a synthetic
violator, extracted a collector so the test and the scan would share code, and then wired the
collector to the wrong test — leaving the assertion the standing gate actually runs with no off-test
at all, and reducible to a no-op with the whole tier green. That is the third consecutive ticket
where the defect was a correct mechanism with no production consumer, and the second in a row where
I shipped that defect **inside the fix for it**.

The roots half held up and was better than I described it. The part I measured, I got right; the
part I asserted from arithmetic — "231 files" — was wrong by twenty, in the direction that
understated my own case.
