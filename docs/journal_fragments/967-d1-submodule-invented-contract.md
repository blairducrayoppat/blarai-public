### 2026-07-19 — The grader that spent its whole budget on a defect that was never there

*Plain summary: the oracle quality-checker was comparing module names against a list of function names, so every time a generated test imported one of the app's own files it was recorded as a made-up requirement. Both of the checker's two repair attempts went to fixing those imaginary problems, while the real problem — the test file covered none of the six acceptance criteria — was never touched. The repair that followed is what broke the build the coder then got blamed for.*

The #965 post-mortem blamed a re-author for dropping `data_storage` from an
import line while leaving three references to it in the body — a plain
`NameError`, and an easy thing to pin on whoever wrote it. That re-author was
never freely chosen. It was the last of two rounds that `validate_authored_
oracle` spent chasing findings that did not exist, and the reason it was
chasing them is one argument wide.

`_declared_symbols` returns a pair — the plan's declared export NAMES and its
declared MODULE names — because a plan's `contract` promises both: `exports:
add_card` and `creates: flashcard_app/card_manager.py`. `_static_findings`
accepted both and then passed only the first into `scan_invented_contracts`.
So `from flashcard_app import card_manager` — a submodule import Python
resolves exactly like any other, and one the plan explicitly promised — was
judged against the set of function names, found absent, and reported as "the
plan declares no such export." The check's own docstring called that outcome
"an invented contract that convicts valid work," which is precisely what it
was doing.

I did not want to take the diagnosis on trust, so I replayed the real run.
On `20260719-002208-bd`, `oracle-qa.json` records `invented_contract: 9` and
`oracle_coverage: 0/6` with twelve traceability gaps. Driving the on-disk
oracle and that run's reconstructed task contracts through the real function
returned four findings — `card_manager`, `quiz_engine`, `score_tracker`,
`main` — every one of them a declared submodule. The decisive evidence was
sitting in the same directory: `import-probe-verdict.json` reads `{"ok":
true, "unresolved": []}`. The runtime probe had resolved all four names
against the actually-built package. The static checker convicted imports the
dynamic checker had already cleared, and nothing reconciled the two.

The arithmetic did not land exactly where the brief predicted, and that is
worth recording rather than smoothing over. The final on-disk oracle yields
four phantoms per scan, not three; only the last round's text survives on
disk, so the 9 cannot be decomposed into per-round counts after the fact. The
shape of the diagnosis held completely; its stated decomposition was a guess
that I could not confirm and did not need.

Why it cost both rounds rather than merely adding noise: `_priority` ranks
`invented_contract` at 4 and `traceability_gap` at 7, and the loop regenerates
exactly one defect per round, `min(findings, key=_priority)`. A phantom that
outranks a real finding does not just waste a round — it *deterministically*
wins every round until the budget is gone. Nine phantoms and twelve genuine
coverage gaps were visible simultaneously, and the ranking guaranteed the
gaps would never be reached. `MAX_REGEN_ROUNDS = 2` was never the constraint;
the ordering was.

The fix threads `modules` through and widens the accepted set to the union of
declared exports and declared submodules. I deliberately did not widen it
further. The rejected alternative was a path-aware check — verifying that the
imported name is a submodule *of the package it is imported from*, so
`from unrelated import card_manager` could not ride on a module declared
elsewhere. It is genuinely tighter, but it requires changing what
`_declared_symbols` returns (a flat set becomes a mapping) and that return
value also feeds `check_import_contract`. Reshaping a live grading path's data
structure on a night the battery runs, to close a hole whose failure mode is
a missed conviction rather than a false one, is the wrong trade. The flat
union matches the function's stated "precise + conservative, never invent a
false invention" contract; the tighter variant belongs in a ticket, not in
this diff.

Two properties I kept deliberately. The fail-soft floor still keys on
`declared_exports` alone, so a plan with `creates` but no `exports` still
disables the check entirely rather than newly switching it on — widening must
never manufacture a conviction that did not exist before. And the eval-side
wrapper in `evals/oracle_checks.py` is untouched, because its case schema
models `declared_exports` only; adding an optional parameter no caller passes
would have been the built-but-wired-into-nothing shape this project keeps
relearning. I corrected its docstring instead, which had claimed it measures
production "verbatim" — after this change it exercises a strictly narrower
input, and a docstring asserting parity it no longer has is the next thing to
lie.

Four locks ship with it. The live-shape lock asserts both halves in one
place: exports-only flags all four names, exports-plus-modules flags none.
The preservation lock puts a real invention (`check_answer`) and a declared
submodule in the *same import statement* and requires exactly the invention
to survive — without it, "the fix works" and "the check now accepts
everything" are the same green. An accounting lock pins that the other static
classes are class-for-class identical. The fourth drives the whole
orchestrator and asserts the regeneration budget now reaches the real
residual: it inspects which prompt the model was actually asked for, and
requires the coverage-append prompt rather than the whole-file re-author. I
checked all four for teeth by reverting the one-line call-site change: the
two wiring-level locks went red, the two direct-call locks stayed green,
which is exactly the split those two kinds of test should show.

Writing the orchestrator lock surfaced something adjacent I am leaving alone.
`card_manager.add_card(...)` does not count as covering a criterion, because
#826 binds criterion subjects to declared export callables and an attribute
call is not a bare name. That is existing intended behavior and arguably
correct; it is not this defect, and folding it in would have made a
one-argument fix into a redesign.

The transferable judgment: when a function derives several kinds of declared
truth and hands only some of them to the checker, the checker does not become
approximately right — it becomes confidently wrong about exactly the cases the
dropped kind covered, and every one of those is a false conviction. That is
bad enough on its own. It is unrecoverable when the false class outranks the
true one in a priority queue with a fixed budget, because then the grader
cannot ever reach the finding that matters. Priority order and false-positive
rate are not independent knobs; a cheap false positive that sorts first is a
denial-of-service on the whole check.

**Next:** the branch is held for its assigned merge night. The path-aware
submodule check (name must belong to the package it is imported from) wants a
ticket; so does reconciling the static invented-contract verdict against
`import-probe-verdict.json`, which had the right answer on disk the whole
time and was never consulted.

---

**Proposed lesson (unnumbered — integrator to assign):** A checker handed
only part of the declared truth is not approximately right, it is confidently
wrong about precisely the dropped part — and when its false findings outrank
the true ones in a fixed-budget priority loop, they do not merely add noise,
they guarantee the real finding is never reached. Pass every kind of declared
truth to the check that judges against it, and treat "cheap false positive
that sorts first" as a denial-of-service on the whole instrument, not a
tolerable imprecision. (#967 D1; the phantom submodule contracts that ate both
regeneration rounds while `oracle_coverage` sat at 0/6, and whose forced
re-author manufactured the `NameError` blamed on the coder in #965. The run's
own `import-probe-verdict.json` had already resolved every convicted name.)
