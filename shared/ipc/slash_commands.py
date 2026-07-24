"""Canonical backend-passthrough slash-command set (SSOT) — UC-010 #668.

A small set of slash commands typed in the WinUI composer are NOT handled
host-side; they must travel to the Python backend AS PROMPT TEXT, where the
gateway parses them:

* ``/external`` — route the message through the ``UNTRUSTED_EXTERNAL`` channel
  (ADR-023 §3.1).
* ``/ingest`` / ``/approve`` / ``/reject`` — the knowledge-bank ingest
  coordinator (UC-002/UC-003, #655).
* ``/imagine`` / ``/illustrate`` / ``/cartoon`` / ``/edit`` / ``/save`` /
  ``/images`` — the UC-010 image generation + management surface, parsed by the
  gateway's ``parse_imagine_command`` → ``ImagineCoordinator`` (ADR-033,
  #666/#667/#668; /illustrate + /cartoon are the #703 flat-illustration styles).
* ``/dispatch`` — headless-coding dispatch to the agentic-setup fleet, parsed by
  the gateway's ``parse_dispatch_command`` → ``DispatchCoordinator`` (brief §9).

Every OTHER slash command is host-side (``/ls``, ``/load``, ``/unload``,
``/rename``, ``/trust``) and is handled in the WinUI client; an unknown slash
command errors client-side rather than being sent on.

WHY THIS CONSTANT EXISTS — the SSOT the WinUI allowlist must cover.
------------------------------------------------------------------
The WinUI front end carries a HAND-COPIED mirror of this set in
``MainWindow.xaml.cs`` (``BackendPassthroughCommands``).  That hand-copy has
SILENTLY DROPPED a newly-added backend command TWICE — first ``/imagine``, then
``/images`` — each time making a shipped backend capability unreachable from the
GUI until someone noticed.  WinUI (C#) and the backend (Python) cannot share a
literal across the language boundary, so this Python constant is the SINGLE
SOURCE OF TRUTH and a gate-time test
(``tests/integration/test_winui_passthrough_allowlist.py``) reads the C# array
out of ``MainWindow.xaml.cs`` and FAILS LOUDLY if the C# set is not a superset of
this one — naming exactly which canonical command(s) the WinUI array is missing.

Adding a new backend-parsed slash command? Add it HERE; the gate test then
forces the WinUI mirror to be updated in the same change (or the build fails).
This is a wiring-correctness guard ONLY — it has NO runtime behavior of its own.
"""

from __future__ import annotations

#: The canonical set of slash commands the WinUI composer must pass through to
#: the backend as prompt text (rather than handling host-side).  Ordered for
#: readability (external/ingest cluster, then the UC-010 image cluster); order
#: is NOT significant — the gate test compares as a set.
BACKEND_PASSTHROUGH_SLASH_COMMANDS: tuple[str, ...] = (
    "/external",
    "/ingest",
    "/approve",
    "/reject",
    "/imagine",
    "/illustrate",
    "/cartoon",
    "/edit",
    "/save",
    "/images",
    "/dispatch",
    # Operator-preference memory (#770 M1, Loop 1): /remember saves the operator's
    # verbatim words as a standing preference; /preferences lists/edits/deletes the
    # active tier.  Parsed by the GATEWAY (transport.py parse_preference_command ->
    # PreferencesCoordinator, intercepted in ui_backend dispatcher._m_prompt before
    # AO dispatch).  The operator's typed command is the tier's ONLY write authority
    # (P8) — no model output ever reaches this seam.
    "/remember",
    "/preferences",
    # Operator-preference PROPOSAL confirm/dismiss (#770 M2 W1): resolve a card
    # the 14B proposed via propose_preference.  These carry an opaque staging
    # token and ride the SAME PREFERENCE_WRITE door (P8 — the operator's typed/
    # clicked confirm is the write authority; the model never re-supplies the
    # body).  The WinUI proposal card's Save/Dismiss buttons emit exactly these.
    "/remember-confirm",
    "/remember-dismiss",
    # Coordinator read surface (#843 C1, ADR-039 §2.10): ``/coord status`` composes
    # a READ-ONLY work-state snapshot (fleet-swap state + queue + latest run +
    # battery campaign + configured boards + flow metrics).  Parsed by the GATEWAY
    # (transport.py -> coord_coordinator); gated BACKEND-side by
    # ``[coordinator].enabled`` — with the flag false the backend answers a clear
    # disabled notice.  The command must always travel; the WinUI never decides.
    # (Missing from this SSOT until the 2026-07-15 go-live ceremony, where the LA
    # typed /coord and got "Unknown command" — the third instance of the
    # hand-copy-drop class this constant exists to kill.)
    "/coord",
)

__all__ = ["BACKEND_PASSTHROUGH_SLASH_COMMANDS"]
