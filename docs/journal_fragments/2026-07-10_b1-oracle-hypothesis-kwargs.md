### 2026-07-10 — The oracle that parsed but could not run

*Plain summary: the 14B's generated pytest acceptance oracle for battery job B1 emitted
`st.text(min_length=1)` — but Hypothesis strategies bound length with `min_size`/`max_size`, so
the strategy call raised `TypeError` at COLLECTION and the whole oracle file was un-collectable.
No coder candidate could ever pass it, yet the gate blamed the coder (a false BUILD attribution).
The structural validator (`ast.parse` + a `test` function) waved it through because the call is
syntactically valid — structural validity is not runtime validity. Fix: a pure
`_repair_hypothesis_strategy_kwargs` helper in `shared/fleet/acceptance.py`, called before the
structural gate in BOTH the #690 per-task and the #740 job-level oracle generators, that rewrites
the known-invalid strategy size kwargs. AST-scoped to call-site keyword args, surgical byte-offset
edits, no-op-byte-identical on clean code. +10 tests; worktree standing gate 6099/0.*

I found this exactly where the brief pointed: `run-fleet-retrieve-expense-list.log:15` in the
2026-07-09 battery run, an ERROR at collection — `text() got an unexpected keyword argument
'min_length'` — repeated verbatim in the verify stage, then "candidate 1 did not pass the gate,
trying a FRESH independent candidate." Two coder candidates burned against a test that no coder
could ever satisfy, because the failure was not in the code under test; it was baked into the
scorecard the planner handed down. This is the part that stings for a measurement instrument: the
job's report reads as a BUILD failure, and the honest cause is a defect in the oracle GENERATOR. A
mis-attributed failure is worse than a loud one — it points the next fix at the wrong subsystem.

The reason it slipped the gate is the interesting bit. `generate_job_acceptance_oracle` already
runs structural validation — `ast.parse`, then a check for a `def test*` function — precisely so a
junk emission fails closed to an honest not-run. But `st.text(min_length=1)` is *syntactically
perfect* Python; the error is a runtime `TypeError` raised when Hypothesis's strategy factory
rejects the keyword, and that only happens when the module is imported (i.e. at pytest collection),
long after `ast.parse` has blessed it. The validator was answering "is this valid Python?" when the
question that mattered was "will this actually collect under the library it imports?" Those are
different questions, and the gap between them is where a broken oracle seeds itself and then blames
the coder.

I went with a narrow, reversible repair rather than the broader "compile/collect every generated
oracle" control (the report's rec 3, tracked separately as #790 — deliberately out of scope here so
this lands conservative before tonight's 23:00 battery). The helper rewrites the two names that are
*never* valid on any Hypothesis strategy — `min_length=` → `min_size=`, `max_length=` →
`max_size=` — so replacing them in a generated hypothesis test is always a correctness improvement.
The path-not-taken was a blunt `str.replace`: rejected because it would corrupt `min_length` inside
a comment or a string literal, and would rewrite a `def helper(min_length=1)` parameter default or
a plain `min_length = 5` assignment — silently breaking a previously-fine oracle. Instead I parse
the code and rename only the `.arg` of `ast.keyword` nodes, which by CPython's grammar are
*exclusively* call-site keyword arguments — parameter defaults are `ast.arg`, assignments are
`Name` targets, dict keys / strings / comments are other node types entirely, so all of them are
structurally excluded, not heuristically dodged. I verified empirically that `keyword.col_offset`
is a UTF-8 byte offset landing on the first character of the arg name (even with a non-ASCII string
earlier on the same line), then apply the renames as surgical byte-slice edits over the original
source — so comments, formatting and the rest of every line survive, and it is a true no-op
(byte-identical) when there is nothing to repair. Two scope guards keep the blast radius minimal:
the repair does nothing unless the module references `hypothesis` at all, and every edit is
re-verified against the expected identifier before it is applied — any mismatch abandons the whole
repair and returns the original untouched, leaving the existing structural gate to make the
fail-closed call. The documented boundary I accept: inside a hypothesis-importing oracle, a
`min_length=`/`max_length=` kwarg passed to a genuinely non-hypothesis callable would also be
renamed — vanishingly unlikely in a property-test oracle, and covered by the downstream `ast.parse`
if it ever produced invalid syntax.

The load-bearing test does not trust my reasoning about "collectability" — it proves it. Since the
runtime venv has no `hypothesis` (the fleet gate installs it ephemerally via `uv run --with
hypothesis`), I register a faithful stub whose `text`/`lists` accept only `min_size`/`max_size` and
raise the *same* `TypeError` on the invalid kwargs, then assert the broken oracle raises at `exec`
(== collection) and the repaired one runs clean. Watching the pre-repair form fail against the
stub is what makes the regression lock honest (lesson 3 / C3). The rest cover the no-op
byte-identical path, the no-hypothesis scope guard, comments/strings preserved, def-params and
assignments preserved, idempotence, and both generators end-to-end.

**Proposed lesson:** *Validate a machine-generated artifact against the semantics of the system
that will execute it, not merely its syntax.* A structural check (`ast.parse` + "has a test
function") answers "is this well-formed?"; it cannot answer "will this run under the library it
imports?" A syntactically-valid, semantically-dead artifact sails through the structural gate and
fails downstream — and when the artifact is the *scorecard*, the failure is mis-attributed to the
subject under test (here: a planner/generator defect billed as a coder BUILD failure). Closely
adjacent to C5 (*what you configure is not what runs — instrument what actually happened*) and C14
(*a claim the code does not enforce is governance debt* — the "this oracle is valid" claim was
enforced only structurally); the transferable nuance is the syntax-vs-runtime gap for generated
code and the mis-attribution it causes. The durable structural control for the whole class —
compile/collect every generated oracle in a throwaway env before seeding — is rec 3 / #790; this
change is the targeted repair, not that control, so treat this as the first documented instance,
not its enforcement.

**Next:** land #790 (semantic collect-validation of every generated oracle in an ephemeral env —
the class-level control that would have caught this without a name-specific repair); re-run job B1
in the next battery to confirm the oracle now seeds collectable and a real coder verdict is
recorded; if the 14B keeps mis-emitting other strategy kwargs, prefer teaching #790's collect-gate
over extending the rename table.

*(commit: blarai `fix/b1-oracle-hypothesis-kwargs` @ `<this>` — the pure repair helper + both
generator call sites + 10 regression tests + this fragment; evidence:
`agentic-setup/state/fleet-runs/20260709-230141-bd/run-fleet-retrieve-expense-list.log:15-17`;
worktree standing gate 6099 passed / 0 failed / 28 env-skips / 123 deselected in 2:43. NOT merged —
builder branch, per the dispatch brief.)*
