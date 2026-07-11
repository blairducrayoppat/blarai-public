"""
Operator-preferences coordinator — /remember + /preferences (#770 M1, Loop 1).
===============================================================================
Gateway-side by design (the ingest/imagine/dispatch pattern): the WinUI and
any other front end share ONE implementation.  Parses the explicit operator
commands and drives the AO's PREFERENCE_WRITE / PREFERENCE_LIST verbs over
the same connection-per-message transport every other coordinator uses.

P8 — this parse IS the write authority: a PREFERENCE_WRITE frame exists only
because the operator TYPED ``/remember`` or ``/preferences edit|delete`` into
the composer.  The model never sees these commands (handled turns persist as
informational turns, no model call) and has no tool that reaches this path.

P2 — the ``/remember`` body travels VERBATIM: everything after the command
word (surrounding whitespace trimmed once at parse — the operator's utterance,
not the composer's incidental padding, is the preference).

Numbered addressing: ``/preferences`` lists the ACTIVE tier in the store's
deterministic insertion order — the SAME order the pinned block
renders — so the numbering is stable; ``edit``/``delete`` accept either that
number or a full 32-hex preference id, resolved against a FRESH listing at
command time (never a cached one).

WinUI note (deliberate M1 deferral, 2026-07-09): ``/remember`` and
``/preferences`` are NOT yet in ``shared.ipc.slash_commands
.BACKEND_PASSTHROUGH_SLASH_COMMANDS`` — they land there TOMORROW together
with the C# ``BackendPassthroughCommands`` mirror (the allowlist SSOT step),
keeping the SSOT gate test green tonight.  Until then the commands are
reachable from any front end that forwards raw text (and from tests), not
from the WinUI composer.
"""

from __future__ import annotations

import datetime
import logging
import re
from typing import Any, Awaitable, Callable, NamedTuple

from shared.ipc.preference_proposal import PROPOSAL_TOKEN_RE

logger = logging.getLogger(__name__)

#: Async ``(op, body, pref_id, token, expires) -> decoded WRITE_RESULT dict``.
#: ``token`` (#770 M2 W1) is the staged-proposal handle for confirm/dismiss;
#: ``expires`` (#770 M2 W2) is the operator-stated ISO expiry on a remember.
#: Ellipsis-typed so callers that omit the optional trailing args (the common
#: 4-arg confirm/dismiss/edit path) still type-check.
PreferenceWriteCall = Callable[..., Awaitable[dict[str, Any]]]
#: Async ``() -> decoded PREFERENCE_LIST_RESPONSE dict``.
PreferenceListCall = Callable[[], Awaitable[dict[str, Any]]]

_PREF_ID_RE = re.compile(r"\A[0-9a-f]{32}\Z")
_ISO_DATE_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")
_WEEKDAYS: dict[str, int] = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


def _resolve_date_phrase(phrase: str, today: datetime.date) -> str:
    """Resolve an operator expiry phrase to an ISO date, or ``""`` if unparseable.

    Deterministic, no new dependency, relative to *today*.  Supported (the
    reliable + common cases; anything else keeps the body verbatim with no
    expiry — the operator can always use the explicit ``--until YYYY-MM-DD``):

      * ISO ``YYYY-MM-DD`` (a past date returns "" — an expiry must be future);
      * ``tomorrow``;
      * a weekday name (``friday``) — the NEXT occurrence on/after today
        (inclusive: "until Friday" on a Friday means through that Friday).
    """
    p = " ".join(phrase.strip().lower().rstrip(".").split())
    if _ISO_DATE_RE.match(p):
        try:
            parsed = datetime.date.fromisoformat(p)
        except ValueError:
            return ""
        return parsed.isoformat() if parsed >= today else ""
    if p == "tomorrow":
        return (today + datetime.timedelta(days=1)).isoformat()
    if p in _WEEKDAYS:
        delta = (_WEEKDAYS[p] - today.weekday()) % 7  # 0..6, inclusive of today
        return (today + datetime.timedelta(days=delta)).isoformat()
    return ""


def _extract_expiry(body: str, today: datetime.date) -> tuple[str, str]:
    """Split a ``/remember`` body into ``(clean_body, expires_iso)``.

    An explicit ``--until <phrase>`` (anywhere) or a trailing ``until <phrase>``
    whose phrase resolves to a date is lifted into ``expires`` and stripped from
    the body; an unresolvable clause is left in the body VERBATIM (P2 — the
    operator's words are kept; "wait until I say so" is not an expiry).
    """
    flag = re.search(r"(?i)\s+--until\s+(.+)$", body)
    if flag is not None:
        iso = _resolve_date_phrase(flag.group(1), today)
        if iso:
            return body[: flag.start()].rstrip(), iso
        return body, ""  # explicit but unparseable — keep verbatim, no expiry
    trailing = re.search(r"(?i)\s+until\s+(.+)$", body)
    if trailing is not None:
        iso = _resolve_date_phrase(trailing.group(1), today)
        if iso:
            return body[: trailing.start()].rstrip(), iso
    return body, ""

_REMEMBER_USAGE: str = (
    "Usage: /remember <preference> — saves your exact words as a standing "
    "preference (for example: /remember Always use metric units)."
)
_PREFERENCES_USAGE: str = (
    "Usage: /preferences — list saved preferences; "
    "/preferences edit <number> <new text> — replace one; "
    "/preferences delete <number> — remove one."
)
_PROPOSAL_USAGE: str = (
    "Usage: /remember-confirm <code> — save a preference the assistant "
    "proposed; /remember-dismiss <code> — dismiss it. Use the code shown on "
    "the proposal card."
)


class PreferenceCommand(NamedTuple):
    """One parsed operator preference command."""

    kind: str      # 'remember'|'list'|'edit'|'delete'|'confirm'|'dismiss'|'usage'
    body: str      # verbatim preference text (remember/edit); '' otherwise
    selector: str  # list number / full 32-hex pref id (edit/delete) OR the
                   # 16-hex proposal token (confirm/dismiss); '' otherwise
    usage: str     # the usage string to surface when kind == 'usage'
    expires: str = ""  # #770 M2 W2 — operator-stated ISO expiry (remember); '' = none


def parse_preference_command(
    text: str, today: "datetime.date | None" = None
) -> PreferenceCommand | None:
    """Parse ``/remember`` / ``/preferences`` from a composer message.

    Returns ``None`` for anything else (the caller proceeds with the normal
    prompt flow).  A recognized command with malformed arguments returns
    ``kind='usage'`` so the operator gets deterministic help instead of the
    text falling through to the model.  ``today`` overrides the expiry-resolver
    clock (tests); ``None`` uses the local date.
    """
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None
    head, _, rest = stripped.partition(" ")
    command = head.casefold()

    if command == "/remember":
        body = rest.strip()
        if not body:
            return PreferenceCommand("usage", "", "", _REMEMBER_USAGE)
        clean, expires = _extract_expiry(body, today or datetime.date.today())
        return PreferenceCommand("remember", clean, "", "", expires)

    if command == "/preferences":
        args = rest.strip()
        if not args:
            return PreferenceCommand("list", "", "", "")
        sub, _, sub_rest = args.partition(" ")
        sub = sub.casefold()
        if sub == "edit":
            selector, _, new_body = sub_rest.strip().partition(" ")
            new_body = new_body.strip()
            if not selector or not new_body:
                return PreferenceCommand("usage", "", "", _PREFERENCES_USAGE)
            return PreferenceCommand("edit", new_body, selector, "")
        if sub == "delete":
            selector = sub_rest.strip()
            if not selector or " " in selector:
                return PreferenceCommand("usage", "", "", _PREFERENCES_USAGE)
            return PreferenceCommand("delete", "", selector, "")
        return PreferenceCommand("usage", "", "", _PREFERENCES_USAGE)

    if command in ("/remember-confirm", "/remember-dismiss"):
        # #770 M2 W1 — resolve a staged model PROPOSAL by its card token. The
        # token is 16-hex-anchored (the forged-id gate pattern); a malformed one
        # surfaces deterministic usage rather than crossing IPC.
        token = rest.strip()
        kind = "confirm" if command == "/remember-confirm" else "dismiss"
        if not PROPOSAL_TOKEN_RE.fullmatch(token):
            return PreferenceCommand("usage", "", "", _PROPOSAL_USAGE)
        return PreferenceCommand(kind, "", token, "")

    return None


class PreferencesCoordinator:
    """Drives the /remember + /preferences flow for the gateway (#770 M1).

    All collaborators are injected so the coordinator is fully unit-testable
    with no AO and no real transport:

    Args:
        write_call: Async ``(op, body, pref_id)`` sending one
            PREFERENCE_WRITE_REQUEST over a fresh AO connection, returning
            the decoded PREFERENCE_WRITE_RESULT payload (error-shaped dict on
            any transport failure — Fail-Closed, never raises).
        list_call: Async ``()`` for PREFERENCE_LIST_REQUEST →
            PREFERENCE_LIST_RESPONSE (same contract).
    """

    def __init__(
        self,
        *,
        write_call: PreferenceWriteCall,
        list_call: PreferenceListCall,
    ) -> None:
        self._write_call = write_call
        self._list_call = list_call

    async def handle_command(
        self, session_id: str, command: PreferenceCommand
    ) -> str:
        """Execute one parsed command, returning the deterministic reply text."""
        if command.kind == "usage":
            return command.usage
        if command.kind == "list":
            return await self._handle_list()
        if command.kind == "remember":
            return await self._handle_remember(command.body, command.expires)
        if command.kind in ("edit", "delete"):
            return await self._handle_addressed(command)
        if command.kind in ("confirm", "dismiss"):
            return await self._handle_proposal(command)
        return _PREFERENCES_USAGE  # unreachable via parse; Fail-Closed anyway

    # ── Sub-flows ────────────────────────────────────────────────────────

    async def _handle_list(self) -> str:
        listing = await self._list_call()
        error = str(listing.get("error", "") or "")
        if error:
            return f"Could not read your preferences: {error}"
        preferences = listing.get("preferences", [])
        if not preferences:
            return (
                "No preferences saved yet. Save one with /remember "
                "<preference> (your exact words are kept verbatim)."
            )
        today = datetime.date.today().isoformat()
        lines = ["Saved preferences (applied to every conversation):"]
        for index, record in enumerate(preferences, start=1):
            tag = str(record.get("type_tag", ""))
            body = str(record.get("body", ""))
            expires = str(record.get("expires", "") or "")
            if expires and today > expires:
                # #770 M2 W2 — past its operator-stated bound: still LISTED (never
                # auto-deleted, P6), flagged so the operator can delete it.
                suffix = f"  [expired {expires} — no longer applied; delete to remove]"
            elif expires:
                suffix = f"  [until {expires}]"
            else:
                suffix = ""
            lines.append(f"{index}. ({tag}) {body}{suffix}")
        lines.append(
            "Edit with /preferences edit <number> <new text>; remove with "
            "/preferences delete <number>."
        )
        return "\n".join(lines)

    async def _handle_proposal(self, command: PreferenceCommand) -> str:
        """Confirm or dismiss a staged model proposal (#770 M2 W1).

        The write door carries ONLY the token — the AO commits the store-side
        STAGED verbatim bytes, so a model restatement can never change what is
        saved (confirm-hop integrity).
        """
        result = await self._write_call(command.kind, "", "", command.selector)
        status = str(result.get("status", ""))
        if command.kind == "dismiss":
            if status == "dismissed":
                return "Dismissed — nothing was saved."
            return self._refusal_text(result)
        # confirm
        if status == "stored":
            return (
                "Saved. I will apply this preference in every conversation."
            )
        if status == "updated":
            return (
                "Replaced the earlier preference (the previous wording is kept "
                "as audit history)."
            )
        if status == "deleted":
            return "Removed. It will no longer be applied (audit history kept)."
        return self._refusal_text(result)

    async def _handle_remember(self, body: str, expires: str = "") -> str:
        result = await self._write_call("remember", body, "", "", expires)
        status = str(result.get("status", ""))
        if status == "stored":
            until = f" (until {expires})" if expires else ""
            return (
                f"Saved. I will apply this preference in every conversation{until}:"
                f"\n  {body}"
            )
        if status == "requires_confirmation":
            conflict = result.get("conflict") or {}
            existing = str(conflict.get("body", ""))
            token = str(result.get("token", ""))
            if token:
                # #770 M2 W2 — one-step contradiction confirm: the operator
                # replaces (or keeps) with a single reply, no /preferences edit.
                return (
                    "This looks like it replaces an existing preference:\n"
                    f"  existing: {existing}\n"
                    f"  new:      {body}\n"
                    f"To replace it, reply /remember-confirm {token}; to keep the "
                    f"existing one, reply /remember-dismiss {token}."
                )
            # Fallback (no staged token): the explicit manual path.
            return (
                "This looks like it replaces an existing preference:\n"
                f"  existing: {existing}\n"
                f"  new:      {body}\n"
                "Nothing was saved. To replace it, run /preferences, then "
                "/preferences edit <number> <new text>."
            )
        return self._refusal_text(result)

    async def _handle_addressed(self, command: PreferenceCommand) -> str:
        pref_id = await self._resolve_selector(command.selector)
        if pref_id is None:
            return (
                f"No preference numbered '{command.selector}'. Run "
                f"/preferences to see the current numbers."
            )
        if command.kind == "edit":
            result = await self._write_call("edit", command.body, pref_id, "")
            if str(result.get("status", "")) == "updated":
                return (
                    "Updated. The preference now reads:\n"
                    f"  {command.body}\n"
                    "(The previous wording is kept as audit history.)"
                )
            return self._refusal_text(result)
        result = await self._write_call("delete", "", pref_id, "")
        if str(result.get("status", "")) == "deleted":
            return "Deleted. It will no longer be applied (audit history kept)."
        return self._refusal_text(result)

    async def _resolve_selector(self, selector: str) -> str | None:
        """Resolve a list number OR a full 32-hex id to a pref_id.

        Numbers resolve against a FRESH listing (the store's deterministic
        order — the numbering the operator just saw).  A full id is format-
        gated here and existence-checked by the AO (Fail-Closed there).
        """
        if _PREF_ID_RE.fullmatch(selector):
            return selector
        if not selector.isdigit():
            return None
        number = int(selector)
        listing = await self._list_call()
        preferences = listing.get("preferences", [])
        if not isinstance(preferences, list) or not (
            1 <= number <= len(preferences)
        ):
            return None
        pref_id = str(preferences[number - 1].get("pref_id", ""))
        return pref_id if _PREF_ID_RE.fullmatch(pref_id) else None

    @staticmethod
    def _refusal_text(result: dict[str, Any]) -> str:
        """Deterministic refusal line from an error-shaped write result."""
        message = str(result.get("message", "") or "")
        code = str(result.get("error_code", "") or "")
        if message:
            return f"Not saved: {message}"
        if code:
            return f"Not saved ({code})."
        return "Not saved: the preference operation failed (Fail-Closed)."


__all__ = [
    "PreferenceCommand",
    "PreferencesCoordinator",
    "parse_preference_command",
]
