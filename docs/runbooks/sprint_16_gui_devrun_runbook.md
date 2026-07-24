# Sprint-16 GUI Dev-Machine Run Runbook

> **For the Lead Architect (non-developer-friendly).** Sprint 16, Stream A (#621). This is the
> deferred dev-machine run for the GUI automation harness. The scripts drive the real BlarAI
> window automatically — you do NOT click anything inside the BlarAI window. You only run the
> commands below and paste back what they print.
>
> **Two tiers.** Tier 1 (stub-backend Layer C) runs with NO models and NO elevation — just the
> built exe. It is the baseline confirmation. Tier 2 (model-loaded) requires the GPU model and
> is the end-to-end run.
>
> **Scheduled:** ~~Sprint-17-kickoff home (batched with the #615 hardware boot, per Sprint-16 SCR §5).~~
>
> > **Staleness note (2026-07-20, #979).** That scheduling trigger is long past —
> > Sprint 17 closed, and the project is in Phase 5. Read the line above as
> > history, not as a pending appointment.
> >
> > **The procedure itself is still valid and still live.** Verified on disk: the
> > venv interpreter, both harness test files
> > (`tests/harness/test_winui_critical_path.py`,
> > `tests/harness/test_winui_model_loaded.py`) and the built
> > `BlarAI.Desktop.exe` all resolve today. The `@winui` tier it drives is a
> > current, deliberately deselected-by-default test tier — see
> > `docs/TEST_GOVERNANCE.md` §1 and its tier table — not a retired one.
> >
> > One command below was **not** correct and has been fixed: the "if the exe is
> > not built" recovery step omitted `-r win-x64 --self-contained`, which this
> > project's WinUI build requires. That is the step you reach for exactly when
> > the exe is missing, so it mattered most where it was wrong.
> >
> > **Two things to know before you run it:** these tests drive the **real BlarAI
> > window** via UI Automation, so they take over the screen and will fight a
> > BlarAI instance you are using; and the Sprint-16 framing throughout (stream
> > numbers, SCR references, "deferred" language) describes the context it was
> > written in, not the current sprint.
> >
> > This file is a candidate for relocation to the sprint-16 archive under #951;
> > it is left in place here because it is the working procedure for a live tier.

---

## The golden rules (read once)

1. **One command at a time.** Run a step, then paste me what it printed. I'll confirm before you go on.
2. **You never click inside BlarAI.** The pywinauto harness does the clicking. Your job is to run
   the commands and paste me the output.
3. **Close BlarAI before starting.** If BlarAI is running (visible in the taskbar), close it first.
   The harness launches its own copy.
4. **Stop anytime.** If anything looks wrong, paste me the error and stop. Nothing here
   modifies data or changes security settings. It does, however, **affect the running
   system**: these tests drive the real BlarAI window via UI Automation, so they take
   over the screen and will fight a BlarAI instance you are using (see the staleness
   note at the top).
5. **If a test fails:** do NOT retry blindly — paste me the output. A test failure here is
   diagnostic information (a real bug found), not a mistake.

---

## Before you start (one-time check)

Open a normal (non-admin) PowerShell window. Admin is NOT required for these tests.

```
cd C:\Users\mrbla\blarai
```

Confirm the exe is built:

```
Test-Path "services\ui_winui\bin\x64\Debug\net8.0-windows10.0.19041.0\BlarAI.Desktop.exe"
```

You should see `True`. If you see `False`, the exe needs to be built first — paste me the output
and I will walk you through the build step.

**→ Paste me the result.**

---

## Tier 1 — Stub-backend Layer C (no models, no elevation)

This tier stands up a scripted fake backend and drives the real window through 13 scenarios:
app-launch, session-list render, new-chat, send-prompt, PGOV approved/denied, session
lifecycle, streaming, attach-button, settings flyout, mic-button state, slash-command
autocomplete, and the status-bar handle.

**Make sure BlarAI is closed.** Then run:

```
C:\Users\mrbla\blarai\.venv\Scripts\python.exe -m pytest -m winui tests/harness/test_winui_critical_path.py -v --tb=short 2>&1
```

**What you'll see:** pytest starts, launches the BlarAI window once per test (13 times total,
each for a few seconds). You will see the window appear and close repeatedly — that is correct.
The window opens, the harness drives it, it closes. Do not click into it.

A passing run looks like:

```
PASSED tests/harness/test_winui_critical_path.py::test_app_launch_prompt_box_is_live
PASSED tests/harness/test_winui_critical_path.py::test_greeting_panel_visible_on_fresh_start
...
PASSED tests/harness/test_winui_critical_path.py::test_status_bar_host_is_present_for_degraded_state_assertions
13 passed in ...s
```

**→ Paste me the full output.** I'll read the results. If any tests failed, I'll tell you what
the failure means and what to do next.

---

## Tier 2 — Model-loaded (Qwen3-14B + real window)

> **Prerequisites for this tier:**
> - The Qwen3-14B model weights are present (they should be — they were put there during the
>   initial setup).
> - The Arc 140V GPU is available (this is your normal dev machine, so it should be).
> - BlarAI is closed.
>
> This tier makes the real model generate a reply that the real window renders. The first
> generation is slow (15–30 s cold GPU start) — that is expected. The harness has generous
> timeouts. Do not interrupt during generation.

Run:

```
C:\Users\mrbla\blarai\.venv\Scripts\python.exe -m pytest -m "winui and hardware" tests/harness/test_winui_model_loaded.py -v --tb=short 2>&1
```

**What you'll see:** the BlarAI window opens, you will see the prompt box go grey (the model is
generating), then text appears in the window, then the prompt box becomes active again. Then
the window closes. Repeat for the second test. Total time: 2–5 minutes.

A passing run looks like:

```
PASSED tests/harness/test_winui_model_loaded.py::test_model_loaded_turn_renders_real_reply
PASSED tests/harness/test_winui_model_loaded.py::test_model_loaded_pgov_approved_no_denial_card
2 passed in ...s
```

**→ Paste me the full output.** If any tests fail, paste me the output and I will diagnose.

---

## Running both tiers together

If you want to run both tiers in one command:

```
C:\Users\mrbla\blarai\.venv\Scripts\python.exe -m pytest -m "winui" tests/harness/test_winui_critical_path.py tests/harness/test_winui_model_loaded.py -v --tb=short 2>&1
```

Note: the model-loaded tests will auto-skip if the GPU model is absent, so this command is
safe to run even if the model is not present — it will just skip the Tier 2 tests.

---

## Also included from earlier sprints (run for completeness)

The Sprint-12 and dead-input tests are also part of the Layer-C harness (two separate files).
After Tiers 1 and 2 pass, optionally run:

```
C:\Users\mrbla\blarai\.venv\Scripts\python.exe -m pytest -m winui tests/harness/ -v --tb=short 2>&1
```

This runs ALL winui-marked tests across all harness files (Sprint-12 + dead-input + critical-path).
**→ Paste me the full output** so I can record the complete baseline.

---

## If the exe is not built — how to build it

If `Test-Path` in the "Before you start" section returned `False`:

```
cd C:\Users\mrbla\blarai
dotnet build "services\ui_winui\BlarAI.Desktop.csproj" -c Debug -p:Platform=x64 -r win-x64 --self-contained
```

When it says `Build succeeded`, re-run the `Test-Path` check above, then start at Tier 1.

---

## If you want to undo / go back

These tests do NOT change BlarAI's data, security settings, or configuration. Running
them is completely safe and reversible. There is nothing to "undo."

If BlarAI is left open after a test crash, just close it manually and re-run.

---

## What these results mean for the project

Tier 1 passing = the GUI critical-path is covered by automated scripts that any future
code change is checked against. Tier 2 passing = the full end-to-end path (real model
generating in the real window) is verified and locked. Together, these replace the "boot
and manually check the window" verification that Sprint 15 relied on.
