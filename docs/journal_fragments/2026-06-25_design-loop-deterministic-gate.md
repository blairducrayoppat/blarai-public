### 2026-06-25 — The one place the machine still graded its own work

The headless-coding dispatch can turn a sentence into a functioning WinUI app, and the
whole arc that got it there was built on a single principle, stated over and over in the
fleet's own lessons: *never trust the local model's self-report — verify the artifact with
an objective tool, every time.* The code loop lives by it. Compile gate, a real `pytest`
run, an ecosystem/language pin, a structural-contract gate, error-feedback, review-feedback.
None of those ask the coder "is this good?"; they all measure. That discipline is exactly
why the function side went from "generates tokens but writes no files" to "merges correct,
tested code unattended."

The design loop broke that principle, and it took the operator to see it. The loop's only
judge was a vision-language model (a small Qwen3-VL) critiquing a screenshot — which is to
say, a local model giving a subjective self-report about the artifact's quality, the precise
anti-pattern the code arc had spent itself eliminating. And it failed in the textbook way: it
certified a calculator grid as "neatly aligned and evenly spaced in a clean grid" when the
display sat *on top of* the keypad and two buttons were oversized into the wrong cells. Worse,
when it handed me that verdict I relayed it — I rubber-stamped the rubber-stamp. The operator's
reply ("this is not good enough… did you look at the image?") is the whole lesson in one line.

So the fix was not to find a better VLM. It was to do for *design* what the project already
did for *code*: put a deterministic gate in front of the soft oracle. In the fleet's own
Compile -> Test -> Oracle order, design had a thin "compile" check (an emoji/seed/image
heuristic) and then jumped straight to the soft "oracle". It was missing the "Test" tier —
something that *measures* the layout instead of asking a model to judge it. `shared/fleet/
layout_lint.py` is that tier: it parses the generated XAML and flags geometry defects with
zero model judgement — two siblings sharing a Grid cell (the Display/keypad overlap), a fixed
Width or Height fighting a star/auto cell (the `0` at Width=130, the `=` at Height=130), an
out-of-range row/column index, a grid whose children claim cells it never defined. Each rule
is precision-guarded so it never nags correct layout: overlap only fires where cells are
actually declared, and a fixed dimension is exempt when the control is deliberately aligned.
A high-severity finding forces a coder FIX *regardless of what the VLM says* — and, because it
reads markup not pixels, it fires even on the structural floor when no screenshot exists at
all. The proof I care about most is the seam test: I pointed the real loop at the broken
rocket-calc with no app to render and no VLM in the loop, and it still came back
ShouldIterate=true with the exact, actionable feedback ("'Display' and 'Keypad' occupy the
same Grid cell… give each its own Grid.Row"). The gap that the false-pass exposed is closed
deterministically.

The VLM didn't get thrown away — it got demoted to what it should always have been, a
*backstop*, and hardened so it earns that role. The critic is now stricter and per-criterion;
it runs as a perspective-diverse multi-vote (a layout lens, a hierarchy lens, a theme lens)
and takes the skeptical union, so a single lens catching a real problem is enough; and it
ingests the deterministic findings into its own prompt ("confirm each of these is fixed"),
turning a vibe-checker into a checker of hard facts. Crucially it stays a *loop signal only* —
`criterion_status` still returns `STATUS_EYEBALL` for every visual criterion, so no VLM verdict
can ever mark a design "done." The deterministic gate is the floor, the VLM is the catch-all
for what geometry can't see (colour, hierarchy, "does it read as a rocket console"), and the
operator's eye remains the verdict. That layering is the governance decision: the rejected
alternative — "just write a sterner prompt / use a bigger VLM" — fails on its face, because a
soft oracle cannot be trusted on exactly the thing it is lenient about. You don't out-prompt a
self-report; you put a measurement in front of it.

Two other seams in the dispatch got the same treatment while I was here. The per-coder-run
circuit breaker was a single absolute wall-clock, which did two wrong things at once: it
guillotined a productive-but-slow coder at the deadline (the operator's earlier "we're killing
it too soon") *and* let a genuinely hung run bleed the entire budget before dying. Splitting it
into a progress-aware idle timeout (no new step and no new edit for a short window = genuinely
stuck, killed fast) plus a generous absolute ceiling fixes both at once — a working coder is
never idle-killed because every edit resets the clock, and a doomed run now dies in minutes
instead of an hour. And the headless dispatch harness, the thing that lets the box drive itself,
had hardcoded its gateway to plaintext dev-mode, so it could never reach a *production* AO over
mutual-TLS; it now defaults to the per-boot mTLS chain the launcher provisions, fail-closed if
the certs are absent. I proved that one live: with BlarAI booted in production, the harness
opened the real per-boot mTLS channel to the running AO and got a full plan back.

What I'm keeping from this: the failure was not the VLM being weak. The failure was trusting a
model's opinion as a gate at all — the same mistake the project diagnosed for code and then
forgot it had a second instance one level up, in the critic. Every oracle gets a deterministic
floor under it, or it isn't a gate.

**Proposed lesson:** *Verify the artifact applies to the critic, not just the coder.* A model
that judges quality is still giving a self-report; a soft oracle (a VLM, an LLM judge) must have
a deterministic gate in front of it for whatever it is lenient about, and must be demoted to a
loop-signal, never the verdict. The code loop learned "never trust the coder's self-report"; the
design loop had to learn the same thing about its own judge. When you add an LLM-as-judge, ask
immediately: what is the hard gate underneath it, and what stops its verdict from being treated
as done?

**Next:** the capstone is the VLM actually rendering and critiquing a real generated app on the
Arc 140V (running now); the deterministic core is already live-proven. Fold this fragment into
`BUILD_JOURNAL.md` at the next quiet point, and lift the proposed lesson into the numbered list.

*(commits: BlarAI `b1ae66d` layout gate, `68e41f4` VLM hardening, merge `41aa608`; `44094ed`
harness mTLS, merge `9840ae8`. agentic-setup `6c1c768` progress-aware timeout, `b7d8ae1` loop
wiring, merge `504416c`. layout_lint 33 tests, critique 54, verify-runtimeout 29/29 (PS 5.1+7),
verify-critique-loop 143->170, dispatch-harness mTLS 59; standing gate 4478/0; live seam +
live mTLS handshake green.)*
