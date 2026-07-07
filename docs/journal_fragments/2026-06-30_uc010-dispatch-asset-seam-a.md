### 2026-06-30 — The seam that wasn't where the map said it was

The brief handed me a design and a place to build it: wire the local image generator into the
headless-coding dispatch, in a new "ASSETS swap phase" the design doc had pointed at for a week. I
nearly built exactly that. Then the LA, reading my comprehension gate, pushed back on the one
assumption the whole shape rested on — that generating had to happen *inside* the model swap, after
the 14B is gone. It didn't. The only memory constraint anyone had actually measured was
image-model + the 30B coder (32.5 GB, over the 31.323 ceiling). Nobody had measured image-model +
the *14B* as forbidden — because it isn't: \~26 GB, 5.3 GB of headroom, and it is exactly how
`/imagine` already runs. So the asset could be generated the way the assistant already makes
pictures — 14B resident, before the swap — and committed into the repo the coder branches from. The
"ASSETS swap phase" collapsed into a handful of lines at the approve seam. SEAM A.

That reframe is the whole entry. The lesson under it: a design doc is a hypothesis about
constraints, and the constraint this one asserted ("don't co-reside, so generate mid-swap") was a
generalization of a *different* measured fact. Four read-only trace agents, run in parallel before I
touched anything, confirmed it from the code: the swap driver is a detached process that finds the
AO already torn down when it runs — which is *why* generating in the driver is hard, and why
generating AO-side is the natural seam. Verify the constraint, not the doc's summary of it.

The governance turned on the same care. The old Phase-2b design had deliberately kept dispatch
assets OUTSIDE the encrypted gallery — "a build-time tool, not runtime governance." SEAM A routes
through the governed `image_gen.py`, which *does* have a born-encrypted store. The trap would have
been to let dispatch assets land in the operator's `/imagine` gallery. So the code skips the store
entirely and writes a plain project file — the same net posture the Phase-2b doc wanted (build
artifact, not gallery content), reached through the one maintained generator instead of a second
abandoned one (Playground, deleted at #703). ADR-033 Amendment 3 records it.

I proved it the way the F2 lesson taught — memory-safely, in halves. The generator, live on the Arc
140V: a real 1024² cartoon elephant, coherent subject on a clean background, \~60 s at 30 steps, the
"after" to testproject6's hand-drawn `<ellipse>` SVG. Then the *real* W2/W3 code path — the actual
`_maybe_generate_dispatch_assets`, not a stand-in — generating and committing that elephant into a
scratch repo's baseline, working tree clean, only the named file staged. The 14B→30B swap that
follows is the existing, operator-daily-proven pipeline; I left the full-swap dispatch staged for an
operator-present run rather than drive a memory-marginal 30B load past my own active session while
he was away — the honest call over a hero one.

One thing I looked at before I touched it: the brief said "retire `asset_gen.py`." I went to add a
deprecation header and found the file sitting inside an *uncommitted home-directory git tree* — a
`git status` there listed `.git-credentials` and `.gitconfig`. I left it alone and recorded the
retirement in the design doc instead. The map said "a build tool"; the territory was the operator's
home directory with its secrets loose. Look at the target before you write to it.

**Next:** the operator-present full dispatch — `/dispatch <fresh web repo> | a webpage with a cartoon
elephant saying hello` at `-Concurrency 1` — to watch the elephant ride the 14B→30B swap, get
referenced offline by the 30B (the W4 hint), and auto-merge. Then fold this fragment.

**Proposed lesson:** *A design doc asserts constraints; verify the measured fact under the
constraint, not the doc's generalization of it.* The "ASSETS swap phase" existed because someone
generalized "image-model + 30B breaches memory" into "never co-reside a model with generation." The
14B co-resides fine. Trace to the measurement before you build on the summary.

*(commits `9954c0b` (W1 asset specs), `1bd75e8` (W2/W3 SEAM-A seam), `d4b4f69` (W5 doc supersession) on
`feat/uc010-dispatch-asset-gen`; `b1871f3` (W4 fleet hint) on agentic-setup
`feat/uc010-dispatch-asset-w4`; standing gate 4647/0; +40 BlarAI tests + 15 fleet checks, mutation
green→red across four locks; live GPU proof + the full W2/W3 code path proven on-hardware; full-swap
dispatch staged.)*
