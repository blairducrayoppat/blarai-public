"""
Gateway preferences coordinator (#770 M1) — parse + flow tests.
================================================================
The coordinator is fully injected (fake write/list calls), so these drive
the REAL parse + reply logic with no AO and no transport.
"""

from __future__ import annotations

import datetime
from typing import Any

import pytest

from services.ui_gateway.src.preferences_coordinator import (
    PreferencesCoordinator,
    parse_preference_command,
)

_ID_A = "a" * 32
_ID_B = "b" * 32


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------


class TestParse:
    def test_non_commands_pass_through(self) -> None:
        for text in (
            "hello", "remember me", "/rememberx thing", "/prefs",
            "/load file.txt", "what are /preferences?",
        ):
            assert parse_preference_command(text) is None

    def test_remember_verbatim_body(self) -> None:
        cmd = parse_preference_command("/remember Always call me Blair")
        assert cmd is not None and cmd.kind == "remember"
        assert cmd.body == "Always call me Blair"

    def test_remember_preserves_interior_spacing(self) -> None:
        cmd = parse_preference_command("/remember spacing   matters   here")
        assert cmd.body == "spacing   matters   here"

    def test_remember_case_insensitive_command_word(self) -> None:
        cmd = parse_preference_command("/Remember call me Blair")
        assert cmd is not None and cmd.kind == "remember"

    def test_bare_remember_gives_usage(self) -> None:
        cmd = parse_preference_command("/remember")
        assert cmd.kind == "usage" and "/remember" in cmd.usage

    def test_preferences_list(self) -> None:
        assert parse_preference_command("/preferences").kind == "list"

    def test_preferences_edit(self) -> None:
        cmd = parse_preference_command("/preferences edit 2 always use metric")
        assert cmd.kind == "edit"
        assert cmd.selector == "2"
        assert cmd.body == "always use metric"

    def test_preferences_delete(self) -> None:
        cmd = parse_preference_command("/preferences delete 3")
        assert cmd.kind == "delete" and cmd.selector == "3"

    def test_malformed_subcommands_give_usage(self) -> None:
        for text in (
            "/preferences edit", "/preferences edit 2", "/preferences delete",
            "/preferences delete 1 2", "/preferences frobnicate",
        ):
            assert parse_preference_command(text).kind == "usage"

    def test_confirm_dismiss_parse_token(self) -> None:
        tok = "0123456789abcdef"
        c = parse_preference_command(f"/remember-confirm {tok}")
        assert c.kind == "confirm" and c.selector == tok
        d = parse_preference_command(f"/remember-dismiss {tok}")
        assert d.kind == "dismiss" and d.selector == tok

    def test_confirm_malformed_token_gives_usage(self) -> None:
        for text in (
            "/remember-confirm", "/remember-confirm zzz",
            "/remember-confirm 0123456789ABCDEF",       # uppercase
            "/remember-dismiss 0123456789abcde",        # 15 hex
            "/remember-confirm 0123456789abcdef extra",  # trailing junk
        ):
            assert parse_preference_command(text).kind == "usage"


# ---------------------------------------------------------------------------
# Flow (fake calls)
# ---------------------------------------------------------------------------


def _make_coordinator(
    write_results: list[dict[str, Any]] | None = None,
    listing: dict[str, Any] | None = None,
) -> tuple[PreferencesCoordinator, list[tuple[str, str, str, str, str]]]:
    write_calls: list[tuple[str, str, str, str, str]] = []
    results = list(write_results or [])

    async def write_call(
        op: str, body: str, pref_id: str, token: str = "", expires: str = ""
    ) -> dict[str, Any]:
        write_calls.append((op, body, pref_id, token, expires))
        return results.pop(0) if results else {
            "ok": True, "op": op, "status": "stored", "pref_id": _ID_A,
            "conflict": None, "error_code": "", "message": "",
        }

    async def list_call() -> dict[str, Any]:
        return listing if listing is not None else {"preferences": [], "total": 0}

    return (
        PreferencesCoordinator(write_call=write_call, list_call=list_call),
        write_calls,
    )


_LISTING = {
    "preferences": [
        {"pref_id": _ID_A, "type_tag": "address-form", "subject": "",
         "body": "call me Blair", "created": "", "updated": ""},
        {"pref_id": _ID_B, "type_tag": "standing-rule", "subject": "",
         "body": "always use metric", "created": "", "updated": ""},
    ],
    "total": 2,
}


class TestFlows:
    @pytest.mark.asyncio
    async def test_remember_sends_verbatim_write(self) -> None:
        coordinator, calls = _make_coordinator()
        cmd = parse_preference_command("/remember Always call me Blair")
        reply = await coordinator.handle_command("s-1", cmd)
        assert calls == [("remember", "Always call me Blair", "", "", "")]
        assert "Saved" in reply and "Always call me Blair" in reply

    @pytest.mark.asyncio
    async def test_requires_confirmation_offers_one_step_confirm(self) -> None:
        # #770 M2 W2 — a near-duplicate /remember surfaces a ONE-STEP confirm
        # (the staged REPLACE token), not the old /preferences edit hop.
        tok = "0123456789abcdef"
        coordinator, _calls = _make_coordinator(
            write_results=[{
                "ok": True, "op": "remember", "status": "requires_confirmation",
                "pref_id": _ID_A,
                "conflict": {"pref_id": _ID_A, "body": "call me Bob"},
                "token": tok, "error_code": "", "message": "",
            }]
        )
        cmd = parse_preference_command("/remember call me Blair")
        reply = await coordinator.handle_command("s-1", cmd)
        assert "call me Bob" in reply                     # the existing shown
        assert "call me Blair" in reply                   # the new shown
        assert f"/remember-confirm {tok}" in reply        # one-step replace
        assert f"/remember-dismiss {tok}" in reply        # one-step keep-existing

    @pytest.mark.asyncio
    async def test_requires_confirmation_without_token_falls_back_to_manual(self) -> None:
        coordinator, _calls = _make_coordinator(
            write_results=[{
                "ok": True, "op": "remember", "status": "requires_confirmation",
                "pref_id": _ID_A,
                "conflict": {"pref_id": _ID_A, "body": "call me Bob"},
                "error_code": "", "message": "",  # no token
            }]
        )
        reply = await coordinator.handle_command(
            "s-1", parse_preference_command("/remember call me Blair")
        )
        assert "Nothing was saved" in reply
        assert "/preferences edit" in reply

    @pytest.mark.asyncio
    async def test_remember_with_expiry_threads_expires(self) -> None:
        coordinator, calls = _make_coordinator()
        cmd = parse_preference_command(
            "/remember answer in French until 2026-07-15",
            today=datetime.date(2026, 7, 10),
        )
        reply = await coordinator.handle_command("s-1", cmd)
        assert calls == [("remember", "answer in French", "", "", "2026-07-15")]
        assert "until 2026-07-15" in reply

    @pytest.mark.asyncio
    async def test_list_flags_expired_and_upcoming(self) -> None:
        today = datetime.date.today().isoformat()
        listing = {
            "preferences": [
                {"pref_id": _ID_A, "type_tag": "standing-rule", "subject": "",
                 "body": "call me Blair", "created": "", "updated": "", "expires": ""},
                {"pref_id": _ID_B, "type_tag": "standing-rule", "subject": "",
                 "body": "answer in French", "created": "", "updated": "",
                 "expires": "2000-01-01"},  # long past
                {"pref_id": "c" * 32, "type_tag": "standing-rule", "subject": "",
                 "body": "speak formally", "created": "", "updated": "",
                 "expires": "2999-12-31"},  # far future
            ],
            "total": 3,
        }
        coordinator, _calls = _make_coordinator(listing=listing)
        reply = await coordinator.handle_command(
            "s-1", parse_preference_command("/preferences")
        )
        assert "1. (standing-rule) call me Blair" in reply   # no-expiry: unflagged
        assert "expired 2000-01-01" in reply                 # past → flagged expired
        assert "[until 2999-12-31]" in reply                 # future → shown, not expired
        assert today <= "2999-12-31"  # sanity: the boundary date is future

    @pytest.mark.asyncio
    async def test_list_renders_stable_numbering(self) -> None:
        coordinator, _calls = _make_coordinator(listing=_LISTING)
        cmd = parse_preference_command("/preferences")
        reply = await coordinator.handle_command("s-1", cmd)
        assert "1. (address-form) call me Blair" in reply
        assert "2. (standing-rule) always use metric" in reply

    @pytest.mark.asyncio
    async def test_empty_list_offers_remember(self) -> None:
        coordinator, _calls = _make_coordinator()
        reply = await coordinator.handle_command(
            "s-1", parse_preference_command("/preferences")
        )
        assert "/remember" in reply

    @pytest.mark.asyncio
    async def test_edit_resolves_number_to_pref_id(self) -> None:
        coordinator, calls = _make_coordinator(
            write_results=[{
                "ok": True, "op": "edit", "status": "updated",
                "pref_id": _ID_B, "conflict": None, "error_code": "",
                "message": "",
            }],
            listing=_LISTING,
        )
        cmd = parse_preference_command("/preferences edit 2 use imperial")
        reply = await coordinator.handle_command("s-1", cmd)
        assert calls == [("edit", "use imperial", _ID_B, "", "")]
        assert "Updated" in reply

    @pytest.mark.asyncio
    async def test_edit_accepts_full_hex_id_without_listing(self) -> None:
        coordinator, calls = _make_coordinator(
            write_results=[{
                "ok": True, "op": "edit", "status": "updated",
                "pref_id": _ID_A, "conflict": None, "error_code": "",
                "message": "",
            }],
        )
        cmd = parse_preference_command(f"/preferences edit {_ID_A} new text")
        await coordinator.handle_command("s-1", cmd)
        assert calls == [("edit", "new text", _ID_A, "", "")]

    @pytest.mark.asyncio
    async def test_delete_resolves_number(self) -> None:
        coordinator, calls = _make_coordinator(
            write_results=[{
                "ok": True, "op": "delete", "status": "deleted",
                "pref_id": _ID_A, "conflict": None, "error_code": "",
                "message": "",
            }],
            listing=_LISTING,
        )
        reply = await coordinator.handle_command(
            "s-1", parse_preference_command("/preferences delete 1")
        )
        assert calls == [("delete", "", _ID_A, "", "")]
        assert "Deleted" in reply

    @pytest.mark.asyncio
    async def test_out_of_range_number_is_a_clear_refusal(self) -> None:
        coordinator, calls = _make_coordinator(listing=_LISTING)
        reply = await coordinator.handle_command(
            "s-1", parse_preference_command("/preferences delete 9")
        )
        assert calls == []  # never reached the write leg
        assert "No preference numbered '9'" in reply

    @pytest.mark.asyncio
    async def test_refusal_surfaces_the_ao_message(self) -> None:
        coordinator, _calls = _make_coordinator(
            write_results=[{
                "ok": False, "op": "remember", "status": "refused",
                "pref_id": "", "conflict": None,
                "error_code": "PREFERENCE_TOKEN_CAP",
                "message": "over the pinned block budget",
            }]
        )
        reply = await coordinator.handle_command(
            "s-1", parse_preference_command("/remember something")
        )
        assert "Not saved" in reply and "over the pinned block budget" in reply

    @pytest.mark.asyncio
    async def test_confirm_sends_token_and_reports_saved(self) -> None:
        tok = "0123456789abcdef"
        coordinator, calls = _make_coordinator(
            write_results=[{
                "ok": True, "op": "confirm", "status": "stored",
                "pref_id": _ID_A, "conflict": None, "error_code": "", "message": "",
            }]
        )
        reply = await coordinator.handle_command(
            "s-1", parse_preference_command(f"/remember-confirm {tok}")
        )
        # ONLY the token crosses (no body, no pref_id) — confirm-hop integrity.
        assert calls == [("confirm", "", "", tok, "")]
        assert "Saved" in reply

    @pytest.mark.asyncio
    async def test_confirm_replace_and_retract_messages(self) -> None:
        tok = "0123456789abcdef"
        for status, needle in (("updated", "Replaced"), ("deleted", "Removed")):
            coordinator, calls = _make_coordinator(
                write_results=[{
                    "ok": True, "op": "confirm", "status": status,
                    "pref_id": _ID_A, "conflict": None, "error_code": "",
                    "message": "",
                }]
            )
            reply = await coordinator.handle_command(
                "s-1", parse_preference_command(f"/remember-confirm {tok}")
            )
            assert needle in reply
            assert calls == [("confirm", "", "", tok, "")]

    @pytest.mark.asyncio
    async def test_dismiss_reports_nothing_saved(self) -> None:
        tok = "0123456789abcdef"
        coordinator, calls = _make_coordinator(
            write_results=[{
                "ok": True, "op": "dismiss", "status": "dismissed",
                "pref_id": "", "conflict": None, "error_code": "", "message": "",
            }]
        )
        reply = await coordinator.handle_command(
            "s-1", parse_preference_command(f"/remember-dismiss {tok}")
        )
        assert calls == [("dismiss", "", "", tok, "")]
        assert "Dismissed" in reply

    @pytest.mark.asyncio
    async def test_confirm_unknown_token_is_a_clear_refusal(self) -> None:
        tok = "0123456789abcdef"
        coordinator, _calls = _make_coordinator(
            write_results=[{
                "ok": False, "op": "confirm", "status": "refused", "pref_id": "",
                "conflict": None, "error_code": "UNKNOWN_TOKEN",
                "message": "That preference proposal is no longer available.",
            }]
        )
        reply = await coordinator.handle_command(
            "s-1", parse_preference_command(f"/remember-confirm {tok}")
        )
        assert "Not saved" in reply and "no longer available" in reply

    @pytest.mark.asyncio
    async def test_listing_transport_error_is_fail_closed_text(self) -> None:
        coordinator, _calls = _make_coordinator(
            listing={"preferences": [], "total": 0, "error": "AO unreachable"}
        )
        reply = await coordinator.handle_command(
            "s-1", parse_preference_command("/preferences")
        )
        assert "Could not read your preferences" in reply
