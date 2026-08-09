# #1241 — the class census: 14 instruments that report a pass they did not measure

**Date:** 2026-07-30 (LOCAL, Pacific)
**Scope:** read-only census over BlarAI `db7b2525` and agentic-setup `33ae7a8`, primary
checkouts, commissioned by the LA directly.
**Design:** `docs/design/CLASS_CURE_DESIGN.md`, committed as `32d128dd` on
`docs/1241-class-cure-design`.

## The result that governs every row below

The census refuted the session lead's own unifying hypothesis, and the refutation is
load-bearing. This is **two** defects, not one, and they need **opposite** fixes:

- **Family A — N carriers of one value.** Cure is topology: delete carriers, or derive them
  from one place. You cannot type your way out of it — both carriers of `surface` are validly
  typed `str` and each is individually correct.
- **Family B — N sites each deciding whether to admit a limit.** Cure is the result type: a
  type in which `clean` is unconstructible without a computed coverage field.

A control shaped for one family **cannot fire** in the other while reporting that it covers
the class. That is the confident-wrong-control failure this project has already produced
twice, which is why no row below is dispositioned as "covered by the unified control."

**No vocabulary lint.** One already exists (`test_doctrine_freshness.py:389`) and missed all
nine claim rows; extending its phrase list catches the four MEDIUM rows and ZERO of the four
HIGH. It would convict misdemeanours, acquit every felony, and then be trusted.

```disposition
C-2 layer1.py:766-778 run_ruff_advisory never reads cp.returncode and `json.loads(cp.stdout or "[]")` turns an empty stdout into a MEASURED ZERO, so findings():835 emits "ruff: 0 advisory findings (measured)" on a lint that never ran - on the exact path the function's own docstring (:750-752) promises returns None | DEFERRED | #1249 blocked-by: the `or "[]"` fallback in `run_ruff_advisory` (tools/dispatch_harness/green_quality/layer1.py) must be removed so a blank stdout returns None - one line, no design needed, no trade-off. MEASURED tonight rather than derived: a probe driving the harness's exact expression against an interpreter lacking the module returns `returncode: 1`, `stdout repr: ''`, and the value the harness would return is 0. CORRECTION to the design branch's own commit message, which states "ruff is not installed" - FALSE on this box, `python -m ruff --version` returns `ruff 0.16.1` exit 0 in the BlarAI runtime venv. The finding survives the correction intact; the defect fires wherever the EXECUTING interpreter lacks the module, which is the coder fleet's per-project uv venv, not BlarAI's own
C-1 test_green_quality.py:904-915 asserts `'["ruff", "check"' in src` and calls that proof the fallback survives, but the fallback is UNREACHABLE - layer1.py:761-771 is a for/break/else that breaks after the first argv not raising OSError, and [sys.executable, "-m", "ruff", ...] cannot raise OSError while the interpreter exists. The test passes on the textual presence of dead code | DEFERRED | #1249 blocked-by: `test_green_quality.py:904-915` must assert BEHAVIOUR - drive `run_ruff_advisory` against an interpreter lacking the module and assert None - instead of asserting source text, and it lands in the same change as C-2 Grouped deliberately: fixing C-2 without C-1 leaves a gate that would pass on a deleted function body
C-3 battery.py:1942/1948/1955 - `{}` is simultaneously the crash sentinel, the never-ran sentinel and a legitimate no-GREEN night, and `if self.green_quality_block:` short-circuits so render_kpi is never called and the operator's summary carries NO LINE AT ALL. mutation.py:442-446 documents "an entirely unaudited night is precisely the state that must not be invisible"; the caller's `if` makes that false. 1 of 3 stages fixed | DEFERRED | #1250 blocked-by: every advisory stage in battery.py must emit a durable per-card record on its own crash path, as `_bank_traceability:1787-1821` already does - it stamps a durable error key on every card while its two sibling stages log to stdout and leave `{}`. This is the Family B stage-contract fix and is designed in CLASS_CURE_DESIGN.md; it is NOT closed by the CraftFinding type change
C-4 green_audit.py:632-634 + :329-335 - _read_text returns None for OSError AND for st_size > 512 KB, and audit_tree does `if source is None: continue` with no counter. THE ONE VERDICT-CHANGING ROW IN THIS CENSUS (GREEN -> PARKED-HONEST) | DEFERRED | #1250 blocked-by: `audit_tree` in tools/dispatch_harness/green_audit.py must carry an `unreadable` counter, as security.py:890-891 already does for the identical loop, and the counter must reach the verdict. Highest-severity row in the census because it is the only one that changes a verdict rather than a description
C-5 green_audit.py:436-442 returns [] for an unreadable pytest.ini/tox.ini/setup.cfg/pyproject.toml while the caller still does scanned += 1; any READABLE pytest.ini is an automatic finding, so unreadability is the only way one passes | DEFERRED | #1250 blocked-by: the unreadable-config branch at `green_audit.py:436-442` must return a value distinguishable from the clean `[]` at its call site, and the caller must stop incrementing `scanned` for a file it could not read
C-6 RegressionFinding.measured is read NOWHERE (layer1.py:807-836, band.py:112-144, card.py:113-145, __init__.py:201-231/428-441), so a GREEN whose entire Layer 1 was unmeasured renders band A, "Looks clean - no problems the automatic audit could find" | DEFERRED | #1251 blocked-by: give CraftFinding the SeedDivergenceFinding shape and make findings(), band_reasons(), build_card() and render_kpi() consult `.measured` the way they already consult `security.measured`. This is the Family B type fix and the census's highest-value single change - it closes C-6, C-8, the invisible half of C-2, and structurally forces the C-4/C-5/C-7 analogues onto every surface, on the only card the operator reads
C-8 layer1.py:413-428/431-438 - `except OSError: files = []` yields CraftFinding(False, "no seed scaffold placeholder found"), plus a [:400], a [:800] and a 64 KB read cap that never reach the verdict | DEFERRED | #1251 blocked-by: `CraftFinding` (tools/dispatch_harness/green_quality/layer1.py) must carry a computed coverage field so the `except OSError: files = []` branch at :413-428 cannot render as a clean finding
C-7 green_audit.py:638-645 via :364-371 returns [] for both "parsed, clean" and "did not parse", so "AST applied to N files" is indistinguishable from "AST applied to 0, all regex" | DEFERRED | #1250 blocked-by: an `unparsed_python` counter in green_audit.py, as security.py:925-928 already carries
C-9 fleet-lib.ps1:1200 `$out.PropertyExecutionMeasured = [bool]$StatsPath` asserts MEASUREDNESS FROM AN ARGUMENT'S PRESENCE, suppressing the NOT MEASURED disclosure at :1312-1316 so `counts.unexecuted_property: 0` reads as a measured zero - exactly what :1313's own comment says the field exists to prevent | DEFERRED | #1252 blocked-by: `PropertyExecutionMeasured` in agentic-setup scripts/fleet-lib.ps1 must derive from whether the stats file was READ and PARSED, not from whether an argument was passed. LATENT today: neither production call site passes -StatsPath, which is why it has never fired - and is also why it will fire silently the first time one does
C-10 coder_test_qa.py:869-871 - `if not root.is_dir(): return []` yields files_scanned=0, findings=[], hard=0 with scope.resolved TRUE | DEFERRED | #1252 blocked-by: the non-directory branch in coder_test_qa.py must return an UNRESOLVED scope rather than a resolved empty one. Rescued at the seam today by fleet-lib.ps1:1204-1224, so any consumer other than that one seam gets a clean-looking zero - the rescue is why this is not HIGH, and the reason it must still be fixed at the source
C-11 traceability.py:955-958 - `oracles[0].read_text(...)`, first glob match decides, while fingerprint() reports over the run | DEFERRED | #1252 blocked-by: the oracle glob in traceability.py must resolve against an allowlist, as mutation.py:276-284 already does when facing the identical glob
C-12 oracle_mutation.py:599-608 - `except (OSError, AttributeError, TypeError): pass`, and not_measured_evidence's own docstring (:558-564) names this exact ambiguity as "the fail-open this audit exists to refuse" | DEFERRED | #1250 blocked-by: the swallowed exception in oracle_mutation.py must produce the not-measured value its neighbouring docstring already defines, rather than falling through to the clean path
C-13 green_audit.py:651-652 - `break` at 400 findings stops the WALK, so files_scanned under-reports with no partial flag | DEFERRED | #1250 blocked-by: the truncation branch in green_audit.py must keep walking and set a `truncated` flag, as security.py:937-976 already does
C-14 fleet-lib.ps1:1191-1198 uses bare property reads while the neighbouring scope block uses defensive Get-JsonField - #1201's control at 1 of 5 sites | REJECTED | not this class. It errs LOUD: under StrictMode a missing property throws rather than yielding a quiet zero. Same shape, opposite direction. Recorded so a later sweep does not re-open it as a silent-narrowing row; the 1-of-5 consistency question is real but is style, not a false measurement
CENSUS-LIMIT the census's own 10/4 split is its classification of its own rows, not an independent measurement, and one census claim was wrong: traceability.py:141-145 was cited for the top-rung prose, which actually lives at :97-100 and says L4-KILLS is "NEVER stamped here" | FIXED | branch docs/1237-1241-dispositions, this record - the corrected line range is stated in the row itself and a correcting comment was posted to #1241 the same day; a false claim inside a census about false claims, recorded rather than quietly amended
COVERAGE the unswept surface must not be read as clean: shared/fleet/acceptance.py (~3100 lines), clarify.py, static_pregate.py and ~35 other shared/fleet modules; tools/dispatch_harness/{scorecard,report,harness,jobs,monitor,probe,watch,failure_taxonomy}.py; battery.py outside 1680-1960; all other agentic-setup PowerShell; all of evals/ | DEFERRED | #1253 blocked-by: none of that surface was written against security.py as a model, and the censor expects the richest remaining vein there - a second census pass over those modules, or an explicit LA decision that the sampled result is sufficient
```

## What a gate can catch here, and the limit that decides the design

Statically findable: C-2 (*a `subprocess.run` whose `returncode` is never read before its
`stdout` is parsed* — greppable, and it would have caught this exact function), C-8 and C-12
(*an `except` whose return is indistinguishable from the clean-path return*), C-3, C-14, and
the mechanical half of C-6.

Reader-only: C-1 (textually correct, semantically empty — no static check knows the
`for/break/else` makes the second argv dead), C-9 (`[bool]$StatsPath` is well-typed,
well-named and wrong), and C-4/C-5, where **the defect is the ABSENCE of a counter, and absence
is not a pattern a linter matches**.

**The limit:** *"`returncode` never read" is satisfied by `_ = cp.returncode`. "`measured` field
with no reader" is satisfied by a debug log line.* A gate for this class is checkable by
inspection and therefore satisfiable by inspection. `traceability.py` already ships a
say-so disclosure and shipped the L4 defect anyway, because the disclosure is static prose. The
only control that resists that is a **type that cannot express the undisclosed state** — which
is why every Family B row above defers to a type change and not to a convention.

**And the strongest control measured in this repository is not a type at all — it is a
RATCHET**, a test whose tolerance self-revokes once the correct artifact exists on disk
(`verify-battery-driver-pinning.ps1` T8a–T8e). Measured survival across a PowerShell refactor:
shared object 4/4, ratchet 2/2, comment-declaring-an-invariant 1/3, type 0 instances in
Family A.
