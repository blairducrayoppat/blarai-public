"""Gate: the WinUI backend-passthrough allowlist covers every canonical command.

WHY THIS GATE EXISTS — the ``/imagine``-then-``/images`` double-miss.
--------------------------------------------------------------------
The WinUI composer (``services/ui_winui/MainWindow.xaml.cs``) carries a
HAND-COPIED C# array, ``BackendPassthroughCommands``, listing the slash commands
it must forward to the backend as prompt text (rather than handle host-side).
That hand-copy SILENTLY DROPPED a newly-added backend command TWICE — first
``/imagine`` (when image generation shipped), then ``/images`` (when image
management shipped, #667) — each time leaving a live backend capability
unreachable from the GUI until a human happened to notice.

C# and Python cannot share a literal across the language boundary, so the SSOT is
the Python constant ``shared.ipc.BACKEND_PASSTHROUGH_SLASH_COMMANDS`` and THIS
gate-time test reads the C# array straight out of the ``MainWindow.xaml.cs``
source text and FAILS LOUDLY — naming exactly which canonical command(s) are
missing — if the C# set is not a superset of the canonical set.  Adding a new
backend-parsed command to the constant then forces the WinUI mirror to be updated
in the same change, or this test goes red.

The C# array is allowed to be a STRICT superset (it may list a passthrough
command the constant does not yet name) — the gate only requires that nothing
canonical is missing from it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from shared.ipc.slash_commands import BACKEND_PASSTHROUGH_SLASH_COMMANDS

# This file lives at <repo_root>/tests/integration/<this>.py, so parents[2] is
# the repo root regardless of where the checkout / worktree is on disk.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_MAINWINDOW_CS = _REPO_ROOT / "services" / "ui_winui" / "MainWindow.xaml.cs"

# Matches the C# field declaration through its initializer block:
#   private static readonly string[] BackendPassthroughCommands =
#   {  ...  };
# DOTALL so the (multi-line) brace body is captured; non-greedy to the first
# closing brace, which is the array terminator (the body holds only string
# literals + comments, never a nested brace).
_ARRAY_BLOCK_RE = re.compile(
    r"BackendPassthroughCommands\s*=\s*\{(?P<body>.*?)\}",
    re.DOTALL,
)

# A C# double-quoted string literal (no escaped quotes occur in these tokens).
_QUOTED_RE = re.compile(r'"([^"]*)"')

# A C# line comment — stripped BEFORE token extraction so a command MENTIONED in
# a comment (e.g. an explanatory ``// "/images" = list``) is NOT miscounted as a
# live array element.  (The array body uses only ``//`` line comments.)
_LINE_COMMENT_RE = re.compile(r"//[^\n]*")


def _winui_passthrough_commands() -> set[str]:
    """Extract the live ``BackendPassthroughCommands`` token set from the C# source."""
    source = _MAINWINDOW_CS.read_text(encoding="utf-8")
    match = _ARRAY_BLOCK_RE.search(source)
    assert match is not None, (
        "Could not locate the BackendPassthroughCommands array literal in "
        f"{_MAINWINDOW_CS} — the gate cannot verify the allowlist. If the field "
        "was renamed, update _ARRAY_BLOCK_RE in this test."
    )
    body = _LINE_COMMENT_RE.sub("", match.group("body"))
    return set(_QUOTED_RE.findall(body))


@pytest.mark.skipif(
    not _MAINWINDOW_CS.exists(),
    reason="WinUI MainWindow.xaml.cs not present in this checkout",
)
def test_winui_allowlist_is_superset_of_canonical() -> None:
    winui = _winui_passthrough_commands()
    canonical = set(BACKEND_PASSTHROUGH_SLASH_COMMANDS)

    missing = canonical - winui
    assert not missing, (
        "The WinUI BackendPassthroughCommands array is MISSING canonical "
        f"backend-passthrough command(s): {sorted(missing)}. Add them to "
        "services/ui_winui/MainWindow.xaml.cs (the IsBackendCommand allowlist) — "
        "otherwise typing them in the composer is handled host-side / errors "
        "instead of reaching the backend. This is the guard against the "
        "/imagine-then-/images double-miss (see shared/ipc/slash_commands.py)."
    )


def test_winui_allowlist_extraction_found_known_commands() -> None:
    """Sanity: the extractor really parsed tokens (guards a silently-empty match
    that would make the superset assertion vacuously pass)."""
    winui = _winui_passthrough_commands()
    # /external and /ingest have been in the array since long before this gate;
    # if the extractor returns them, it is reading the real literal.
    assert "/external" in winui
    assert "/ingest" in winui
    assert len(winui) >= len(BACKEND_PASSTHROUGH_SLASH_COMMANDS)
