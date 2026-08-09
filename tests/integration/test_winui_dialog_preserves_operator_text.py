"""Gate: a WinUI dialog must never destroy the operator's typed text on a rejection.

WHY THIS GATE EXISTS — the discard-the-operator's-text class, third instance.
----------------------------------------------------------------------------
Three separate defects in this family landed within two days, each destroying text a
human had just typed:

1. #1117 (FIRST, and the one that actually cost data) — ``OnNewProject`` validated
   AFTER ``ShowAsync()`` returned. By then the ``ContentDialog`` and both ``TextBox``es
   are destroyed, so a blank name discarded a ~2,200-character project description on
   2026-07-27. It was recovered only by taking a 674 MB memory dump of the live process
   and scanning the managed heap for UTF-16 runs — which worked solely because the app
   had not been restarted, and is not repeatable in general.
2. #1116 — a parked ``/dispatch`` did not survive an app restart, and no reply path
   echoed the operator's text back.
3. #1126 — a newline after ``/dispatch`` routed a typed answer into normal chat, where
   the clarify question stayed unanswered and the text was nearly lost.

Per the LESSONS Rule-3 discipline the THIRD instance ships a STRUCTURAL CONTROL rather
than a third point fix. This is it, landed with #1117 rather than waiting for a fourth
incident to earn it.

WHAT IT ASSERTS, AND WHY IT PARSES SOURCE.
C# and Python cannot share a runtime, and a ``ContentDialog`` needs a real XAML root —
so a behavioural test would need a built app and a display, i.e. the @winui ceremony
tier, which does NOT run at every gate. This defect class is cheap to reintroduce and
expensive to notice, so the check has to run on every commit. It therefore reads
``MainWindow.xaml.cs`` as text and asserts the STRUCTURE that makes the destruction
impossible: validation is wired to ``Closing`` with ``args.Cancel``, and the
post-``ShowAsync`` path contains no early ``return`` that drops the typed values.

This is deliberately a weaker claim than "the dialog behaves correctly" — it cannot
prove the guard works, only that the guard exists and the destructive shape is gone.
That limit is stated here rather than papered over; the behavioural proof belongs to
the @winui tier. A structural gate that runs 100% of the time and catches the specific
regression shape beats a perfect test that runs at a ceremony nobody schedules.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MAINWINDOW_CS = _REPO_ROOT / "services" / "ui_winui" / "MainWindow.xaml.cs"


def _mainwindow_source() -> str:
    if not _MAINWINDOW_CS.is_file():
        pytest.skip(f"WinUI source not present at {_MAINWINDOW_CS}")
    return _MAINWINDOW_CS.read_text(encoding="utf-8", errors="replace")


def _on_new_project_body(source: str) -> str:
    """The text of OnNewProject, from its signature to the next method declaration.

    Anchored on the signature rather than a brace-matcher: C# string literals in this
    file contain braces (interpolated strings), so counting braces would mis-terminate.
    """
    start = source.find("private async void OnNewProject(")
    assert start != -1, (
        "OnNewProject not found in MainWindow.xaml.cs — the handler was renamed or "
        "moved. RE-ANCHOR this gate rather than deleting it: it is the structural "
        "control for the discard-operator-text class (#1117, Rule-3)."
    )
    nxt = re.search(r"\n    (?:private|public|protected|internal)\s", source[start + 10:])
    end = (start + 10 + nxt.start()) if nxt else len(source)
    return source[start:end]


def test_new_project_validates_before_the_dialog_is_destroyed() -> None:
    """THE REGRESSION LOCK. Validation must be wired to Closing, not run after it."""
    body = _on_new_project_body(_mainwindow_source())

    assert "dialog.Closing" in body, (
        "OnNewProject must validate in a ContentDialog.Closing handler. Validating "
        "after ShowAsync() returns is too late — the dialog and its TextBoxes are "
        "already destroyed, so a failed check discards everything the operator typed "
        "(#1117: ~2,200 characters lost, recovered only from a process memory dump)."
    )
    assert re.search(r"args\.Cancel\s*=\s*true", body), (
        "the Closing handler must set args.Cancel = true on a failed check — that is "
        "what keeps the dialog, and therefore the operator's text, alive (#1117)."
    )


def test_the_post_show_path_no_longer_discards_typed_text() -> None:
    """The specific destroyed-data shape: a bare `return` after ShowAsync on empty input.

    Pinned separately from the wiring check because a future edit could keep the Closing
    handler AND re-add a post-ShowAsync emptiness check — which would restore the exact
    defect while the first test still passed.

    TWO LOCKS, AND THE SECOND ONE IS THE LOAD-BEARING ONE (independent review, 2026-08-06).
    The emptiness regex below is a BLOCKLIST of spellings, and this file's first version
    pinned only ``IsNullOrEmpty`` — the idiom the fix itself ABANDONED in favour of
    ``IsNullOrWhiteSpace``. So the one form an author would naturally write, by copying the
    two lines directly above in ``Closing``, was the one form the lock could not see: the
    reviewer reintroduced #1117 verbatim in the file's current idiom and all three tests
    stayed green. A docstring promising coverage a regex does not have is worse than no
    docstring, because the next reader stops looking.

    Blocklists cannot be completed — ``goal == ""``, ``goal.Length == 0``, a helper, a
    pattern nobody has thought of yet. So the widened regex stays only as a fast, specific
    error message, and the ACTUAL guarantee is the structural one: between ShowAsync and
    the submit call there is NO early return at all, whatever it tests. That is
    deny-by-default rather than a list of known-bad spellings, and it is idiom-independent
    by construction.
    """
    # ANCHOR ON THE CALL, NOT THE WORD. Splitting on a bare ``ShowAsync()`` matches the
    # explanatory comment ABOVE the Closing handler first ("...checked for empty fields
    # AFTER ShowAsync() returned"), so the tail began 30 lines early and included the whole
    # Closing handler — the very code this test must NOT flag. The original spelling passed
    # only by luck: its regex wanted a bare ``goal``/``name``, and the handler happens to
    # use ``goalBox.Text``. Found 2026-08-06 when the structural lock below went red on
    # correct source and the anchor, not the code, turned out to be wrong.
    body = _on_new_project_body(_mainwindow_source())
    after_show = body.split("await dialog.ShowAsync()", 1)
    assert len(after_show) == 2, (
        "The `await dialog.ShowAsync()` call was not found in OnNewProject — re-anchor. "
        "Do NOT relax this to a bare 'ShowAsync()': that matches the comment above the "
        "Closing handler and silently mis-scopes both locks below."
    )
    tail = after_show[1]

    # Lock 2a — the named shapes, kept for the specific diagnosis it can give.
    offenders = re.findall(
        r"(?:string\.IsNullOrEmpty|string\.IsNullOrWhiteSpace)\s*\(\s*(goal|name)\s*\)"
        r"|\b(goal|name)\s*(?:==\s*\"\"|\.Length\s*==\s*0)",
        tail,
    )
    flat = sorted({m for group in offenders for m in group if m})
    assert not flat, (
        "OnNewProject checks "
        f"{flat} for emptiness AFTER ShowAsync() has returned. At that "
        "point the dialog is destroyed and the typed text exists nowhere else, so the "
        "early return silently discards it — this IS #1117. Validate in Closing instead."
    )

    # Lock 2b — the structural guarantee. The ShowAsync guard line legitimately returns
    # (Cancel/ESC must close); nothing after it may, until the work actually starts.
    region = tail.split("SubmitPromptAsync", 1)[0]
    stray = [
        line.strip()
        for line in region.splitlines()[1:]  # [0] is the remainder of the ShowAsync line
        if re.search(r"\breturn\b", line)
    ]
    assert not stray, (
        "OnNewProject returns early between ShowAsync() and SubmitPromptAsync: "
        f"{stray}. Whatever that return tests, the dialog and both TextBoxes are already "
        "destroyed by then, so the operator's typed text exists nowhere and is discarded "
        "— this IS #1117. Any rejection must happen in the Closing handler, where "
        "args.Cancel keeps the text alive. Do not add a spelling to the regex above "
        "instead: this lock exists precisely because that list cannot be completed."
    )


def test_the_operator_gets_told_which_field_is_missing() -> None:
    """Not cosmetic: the original banner named both fields regardless of which was blank.

    The operator left ONE field empty and was told to 'enter both', which reads as
    though neither entry registered. Keeping the dialog open is only half the fix; the
    message has to identify the actual gap, beside the field it refers to.
    """
    body = _on_new_project_body(_mainwindow_source())
    assert "Please enter what you want to build." in body, (
        "a goal-only-missing message must exist (#1117)"
    )
    assert "Please enter a short project name." in body, (
        "a name-only-missing message must exist (#1117)"
    )
    assert re.search(r"\.Focus\(FocusState\.", body), (
        "focus must move to the offending field — otherwise the operator has to hunt "
        "for which of two boxes the message is about (#1117)."
    )
