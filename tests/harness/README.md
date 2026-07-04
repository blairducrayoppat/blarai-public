# Headless scenario + latency harness (Vikunja #563)

A GUI-free way to drive the real BlarAI backend **in-process** and measure what a
user actually feels — so a regression can be caught automatically, and an agent
can reproduce "it felt slow" **without a human booting the app**.

It exists because every change used to cost the User-Operator a boot-and-hunt.
The harness is the robot tester: build it once, and every later change gets
checked against it instead of against a person's afternoon.

## Three layers (two backend, one front-end)

### Layer A — regression locks (`test_freeze_regression.py`)
Deterministic, **no models, no GPU**. Runs in the default `pytest` suite. It
drives the real `RpcDispatcher` through a fake gateway to lock behavioural
contracts — first among them the **freeze fix** (`f4406c5`): the dispatcher runs
the blocking `gateway.load_document` **off** the event loop, so a slow image
grounding can never again freeze voice + chat behind it (the ~5-minute voice
queue hit on the 2026-06-03 live boot; `BUILD_JOURNAL.md` lesson 24).

The *lazy* half of that fix (attach does not call the VLM) is already unit-locked
in `services/ui_gateway/tests/test_document_loader_media.py`. Layer A locks the
complementary *off-loop* half, which was covered nowhere. The **primary lock**
asserts the exact property the fix guarantees — the blocking `load_document` runs
on a **different thread than the event loop** — by comparing thread identities,
so it is immune to scheduling jitter (no flaky millisecond budgets). The same
test reconstructs the pre-fix sync-on-loop dispatcher and proves it runs the load
*on* the loop thread, so the lock cannot silently rot. Complementary
concurrency probes assert a slow attach does not starve a neighbour, using
*relative* invariants that survive a slow CI box (lessons 24 + 25).

```bash
pytest tests/harness/test_freeze_regression.py tests/harness/test_latency.py   # 10 tests, ~2s, no hardware
```

### Layer B — real-model latency (`test_real_model_latency.py`, `__main__.py`)
Loads the **real OpenVINO models on the Arc 140V** and measures the
User-Operator's actual pain points. Marked `slow` + `hardware`, so it is
**deselected by default** — it only runs where the weights are on disk.

```bash
pytest -m hardware tests/harness            # assert the runtime loads + runs
python -m tests.harness                      # measure + RECORD perf data (all)
python -m tests.harness --scenario vlm       # just the image-question latency
python -m tests.harness --scenario chat      # just the 14B chat latency
python -m tests.harness --scenario router    # just the CPU router
python -m tests.harness --no-record          # print only; write nothing
```

The CLI writes a community-grade JSON per scenario to `docs/performance/`
(`harness_<scenario>_<ts>.json`) — hardware, OpenVINO version, methodology, and
an explicit `not_measured` list — the OpenVINO-on-Lunar-Lake dataset the
User-Operator contributes upstream (CLAUDE.md testing-data mandate).

### Layer C — front-end UI Automation (`test_winui_input.py`, `winui_backend.py`)
Drives the **real WinUI window** with UI Automation (pywinauto). Marked `slow` +
`winui`, **deselected by default** — it needs a free display, the built exe, and
BlarAI closed (the display + GUI are shared singletons, like the GPU for Layer B).
The launcher can't boot autonomously (it forces admin + Hyper-V), so
`winui_backend.py` stands up the real pipe server over a *scripted fake*
(no models, no admin, no VM) and the window connects to it — the UAC-free enabler,
verified by `test_winui_backend.py` (a named-pipe round-trip, no GUI). Layer C then
locks the **dead-input bug end-to-end**: a stalled backend freezes the input and
the merged backend fail-safe re-enables it, proven against the real window.

```bash
pytest -m winui tests/harness     # drives the real window; needs display + exe + BlarAI closed
```

Live-verified 2026-06-04: a normal turn re-enables the input; a stalled backend
freezes it and the fail-safe recovers it — both green against the real window
(`auto_id="PromptBox"` reads `IsEnabled`; WinUI 3 maps `x:Name` straight to the
UIA AutomationId, so no XAML changes were needed).

## Measured baseline (2026-06-04, OpenVINO 2026.1.0, Arc 140V, single cold run)

| Scenario | Device | What it measures | Number |
|----------|--------|------------------|--------|
| `router` | CPU | bge-small classify (per query) | **mean 5.1 ms / p95 5.8 ms** (load 8.9 s) |
| `vlm`    | GPU | image question, cold (lazy load + describe) | **21.7 s** (≈13 s load + ≈8 s inference, 128 tok) |
| `chat`   | GPU | 14B reply, cold first turn (spec-decode on) | **first-token 1.5 s · 6.1 s / 64 tok** (load 19.3 s) |

These confirm the design intuition: the image and chat waits are dominated by
**cold model load** (~13–19 s), not the pipeline — which is exactly what the
keep-warm / eviction follow-up (ADR-015 / Vikunja #550) targets. The freeze the
User-Operator hit was those seconds running **on the event loop**; Layer A locks
them off it.

## Adding a scenario

1. Add a fail-soft function to `scenarios.py` returning a dict with
   `available`, `model`, `precision`, `methodology`, and your numbers (return
   `{"available": False, "reason": ...}` when the model is absent so callers skip).
2. Register it in `scenarios.SCENARIOS` for the CLI.
3. Add an assertion test to `test_real_model_latency.py` (mark it via the module
   `pytestmark = [slow, hardware]`).

For a non-model behavioural lock, use the `InProcessBackend` driver with a fake
gateway (see `fakes.FakeGateway`) — `call_concurrent` is the probe that proves a
blocking handler does not starve its neighbours.

## Honest limits

- **Layer B needs the real GPU + weights** — it runs on the User-Operator's
  machine, not in CI. Elsewhere every scenario skips.
- Numbers are **single cold runs** unless you loop them; cold load dominates, so
  warm latency is lower. Co-residency cost (VLM + 14B together on the 31.3 GB
  ceiling) is **not** measured here — run heavy scenarios one at a time.
- It does **not** judge subjective quality (voice naturalness, whether a visual
  answer is *good*) — only latency and structural correctness. That part still
  needs a human ear/eye.
- Layer A proves the **UI-backend** path is off-loop. The AO-side image grounding
  runs in the AO's own worker thread (so it does not block the UI loop) but is
  itself synchronous — see `services/assistant_orchestrator/src/entrypoint.py`
  `_ground_pending_image`; that is a known, separate property, not locked here.

## Not yet locked (honest follow-ups, tracked on #563)

An adversarial review (2026-06-04) confirmed the freeze lock has teeth but named
real coverage gaps — recorded here so they are not mistaken for covered:

- **`_m_store_attachment`** (picker / drag-drop) runs two blocking ops off-loop;
  same freeze class as `load_document`, not yet locked. (Cheap: parametrize the
  thread-identity test.)
- **`_m_transcribe` / `_m_synthesize`** depend on `asyncio.to_thread` to keep the
  loop free during blocking Whisper/TTS calls — same class, not locked.
- **AO-side on-demand grounding** off-loop-ness (the `_ground_pending_image` path
  on the *prompt*) — the higher-value lock, needs a faked AO prompt path.
- **PGOV-denial path** (`audio_cancel`, denied-turn persistence, tool-call buffer
  discard) — the `FakeGateway` always approves, so the Fail-Closed branch is
  unexercised.

## Pointers
- Vikunja **#563** (this harness). Freeze fix: `f4406c5`. Multimodal arc: **#561**.
- Co-residency / keep-warm follow-up: ADR-015 / Vikunja **#550**.
