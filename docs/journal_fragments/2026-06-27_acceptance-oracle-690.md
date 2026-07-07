### 2026-06-27 — The test the coder isn't allowed to write (the shared oracle, #690)

Best-of-N (#689) was sound but had a hole I'd left open by design. When a goal is a
single feature, the acceptance criteria FOLD into the one task's prompt — so each of the N
independent candidates writes its OWN tests, then the deterministic gate picks a "winner."
But a gate that compares candidates which each authored their own exam isn't selecting the
best implementation; it's selecting the most flattering self-assessment. A weak candidate
can pass by writing a happy-path test that mirrors its own wrong code (the self-test
validity problem, arXiv:2409.09464). Best-of-N multiplies generation coverage, but only if
every candidate is judged against the SAME ruler. It wasn't. #690 is that ruler.

The fix is one shared, spec-derived acceptance ORACLE, and the load-bearing word is
CROSS-MODEL. The 14B writes an executable, spec-blind pytest file at PLAN time — built from
the goal-level criteria it already proposes, BEFORE the 30B coder ever sees the task — so
the model that grades never wrote for the model that codes. The oracle is seeded into the
worktree as a PROTECTED file, committed into the candidate baseline ($codeBase) so every
fresh best-of-N reset inherits it byte-identically, and the coder is told plainly: this file
IS the spec, make its tests pass, you may not edit it. Then — the part that makes the
protection real rather than aspirational — the oracle is RESTORED from the baseline (a
`git checkout $codeBase -- <path>`) immediately after the coder runs and BEFORE the gate, so
a candidate that quietly weakened or deleted the failing test is overwritten and judged by
the original anyway. A candidate cannot pass by editing the exam.

Three judgment calls are worth keeping on the record. First, **python-only, fail-closed.**
The oracle is pytest; a Node project needs jest, a .NET project has no offline test runner
at all. Rather than emit a half-right oracle into an ecosystem that can't run it, the
generator returns '' for anything but an explicitly-python goal — and '' is exactly today's
fold-the-tests-in behavior, byte-for-byte. Same for a model emission that won't `ast.parse`
or defines no test function: '' and fall back. The feature can only ever ADD safety, never
subtract it; the worst case is the world before #690. Node is a tracked follow-up, not a
silent gap. Second, **the oracle rides the task dict, not the spec.** The design note I'd
written said "add a field to AcceptanceSpec," but the spec crosses the gateway IPC to render
the operator's confirm-preview, and a whole pytest file has no business bloating that
payload. The oracle is build-time coder input, so it threads onto the compiled task
(`acceptance_test_code` + `acceptance_test_path`) where the fleet actually consumes it — and
it survives the clarification re-stamp because `_thread_build_fields` only adds keys. Third,
I found and did NOT paper over a pre-existing gap: the Python→queue writer (`enqueue_task`)
forwards only `{repo,task,prompt,model}` to the fleet, dropping the rich PLAN fields —
surface, complexity, goal, and now the oracle — exactly as it already drops them for the
VLM-critique path. That's the minimal increment-1 enqueue predating the rich fields, and
closing it is the go-live EXECUTE-IPC wiring the operator owns, not something to quietly
expand #690's scope into. My named seam (acceptance.py → run-fleet.ps1 → new-agent-task.ps1)
is complete; the oracle flows the moment that wiring lands, alongside the siblings it rides
with.

The honest part. My first behavioral regression — seed an oracle into a real throwaway repo,
have a "candidate" weaken it, restore, assert byte-identical — failed three times, and the
expected and actual strings looked pixel-identical in the diff. It was git's `core.autocrlf`:
the seed writes LF, `git checkout` re-materialises the working tree as CRLF on Windows, and a
byte-equality check rightly flagged the difference. The lesson wasn't "the restore is broken"
— it isn't; git stores LF on add/commit, so the MERGED oracle is LF regardless, and pytest
reads CRLF fine. The lesson was that I'd asserted the wrong property. What #690 must guarantee
is that the ASSERTIONS survive a candidate's tampering, not the line endings — those carry no
test logic and git normalises them identically for every candidate. So the comparison is
line-ending-normalised, and a candidate that changes an assertion still fails. A byte-equality
test that's too strict doesn't catch more bugs; it catches the filesystem.

It works, end to end, on the Arc 140V. A real dispatch seeded the oracle ("Seeded the shared
acceptance oracle -> tests/test_acceptance.py (protected; restored before each gate)"), the
30B read the DO-NOT-EDIT contract and wrote a conforming `is_palindrome`, the gate ran the
seeded oracle (pytest 5 passed, verify pass), and it MERGED — with the git history showing the
`seed: acceptance oracle (protected; the coder codes against this)` commit sitting in the
baseline beneath the agent's work, the merged oracle byte-identical to what the producer
emitted, and an independent re-run of just the oracle green.

And the part I almost didn't check earned its keep. The mechanism is moot if the 14B writes a
bad scorecard, so I swapped the box to the 14B and had it author a real oracle for a date-math
goal. The CONTENT was genuinely good — nine correct example assertions (zero days, month and
year boundaries, a leap-year crossing, negative deltas backwards across all three) plus a
Hypothesis property test. But my validator REJECTED it. The 14B had opened a ```python fence
and never closed it (small models omit the close, or the generation truncates before it), and
my fence-stripper only understood CLOSED fences — so the stray ```python line reached
`ast.parse`, raised SyntaxError, and a perfectly good oracle fell to ''. The unit tests had all
used clean fixtures (closed fences, or none), so they were green and wrong about the world. One
real 14B call found the gap the whole suite had missed. The fix is a three-shape extractor
(closed fence / unclosed-opener / no fence) with its own regression lock built from the exact
emission, and after it the same 14B oracle validates at 1362 characters — proof that the cross-
model author writes a usable scorecard, which is the whole #690 thesis. That is the case for
live verification in one paragraph: the model does what models do, not what your fixtures
assumed.

**Next:** #691 — right-size the task envelope (short, checkpointed, gated steps) so the coder
is asked for less per attempt. Then #695 — the measured parallel-execution follow-up, where
best-of-N's N candidates run concurrently through OVMS continuous batching and the real
ceiling on this integrated GPU is found on the box, not predicted. The node oracle and the
enqueue_task rich-field forwarding (a go-live EXECUTE-wiring item) are both tracked, not
forgotten.

**Proposed lesson:** *When you fan out, hand every branch the same ruler — and make the ruler
unforgeable.* Best-of-N only beats single-shot if the selector is fair; a candidate grading
its own homework is no selector at all. The fix is a cross-model oracle (the judge never wrote
for the coder) that is seeded, protected, and RESTORED before the gate, so weakening or
deleting it cannot help. And when you write the test that proves it, assert the property that
matters (the assertions survive) — not an over-strict proxy (the bytes match) that a benign
filesystem quirk will flunk.

*(commits: blarai `<this>` (acceptance.py generate_acceptance_oracle + compile_prompts oracle
path + the three-shape fence extractor + 17 tests; standing gate green), agentic-setup
`da96997` (new-agent-task.ps1 seed+protect+restore, run-fleet forward, verify-oracle.ps1
[18 tests]; 17/17 fleet policy suites green; merged `e969471`); live on the Arc 140V
2026-06-27 — one clean oracle-seeded MERGE (palindrome) with the protect property confirmed
byte-identical in the merged tree, and a real 14B oracle validated at 1362 chars after the
unclosed-fence fix. Follow-ups #691, #695, + node-oracle / enqueue_task rich-field forwarding.)*
