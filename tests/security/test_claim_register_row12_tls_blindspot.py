"""Claim-register row 12 says the exfil screen cannot see TLS. Keep that true (#1592).

Row 12 of `docs/governance/trust-spine-claim-register.md` used to claim that every
outbound payload is scanned for secrets before it leaves the host. #1592 measured
that this is structurally false for TLS — and `guarded_fetch` refuses any
non-HTTPS scheme, so it is false for every production egress path. The row was
corrected to say so.

**A corrected claim with nothing holding it is a claim waiting to rot.** #1592's
original plan carried a regression lock (a loopback-TLS test asserting the
kill-switch trips); that deliverable was REJECTED, because it presumed a fix —
making the socket-layer screen see TLS — that the research rejected on measured
grounds. Rejecting the fix is not a reason to ship the correction unlocked, and
the review of that disposition said so (#1592 record review, finding 6).

**What this file locks, and it is deliberately the opposite direction of a normal
security test.** It asserts the BLIND SPOT still exists. Two futures make it fail,
and both of them should:

  1. CPython stops detaching the underlying socket on TLS wrap, or the guard
     starts surviving it. The screen would then see TLS traffic and row 12 would
     be understating the protection — a stale claim in the operator's direction,
     which is the safer error but still a false document.
  2. Somebody adds a transport-level screen. Row 12 must then be rewritten, and
     this test is what tells them.

Either way the failure message says: go and update row 12. That is the whole job.

No network. A `socketpair` gives a genuinely connected socket, and
`wrap_socket(do_handshake_on_connect=False)` constructs the `SSLSocket` — which is
where `detach()` happens — without any handshake, certificate or listener.
"""

from __future__ import annotations

import inspect
import pathlib
import socket
import ssl

import pytest

from shared.security import egress_guard

_REPO = pathlib.Path(__file__).resolve().parents[2]
_CLAIM_REGISTER = _REPO / "docs" / "governance" / "trust-spine-claim-register.md"


def _row_12() -> str:
    text = _CLAIM_REGISTER.read_text(encoding="utf-8")
    rows = [line for line in text.splitlines() if line.startswith("| 12 |")]
    assert len(rows) == 1, (
        f"expected exactly one row 12 in {_CLAIM_REGISTER.name}, found {len(rows)}"
    )
    return rows[0]


def test_the_claim_register_still_records_the_TLS_blind_spot() -> None:
    """The prose half. Cheap, and it is the artifact the operator actually reads."""
    row = _row_12()
    assert "CORRECTED" in row and "#1592" in row, (
        "row 12 no longer carries the #1592 correction. If the screen genuinely "
        "reaches TLS now, rewrite the row; if the correction was dropped, restore "
        "it — the row currently overstates a protection the operator relies on"
    )
    assert "never invoked for HTTPS" in row, (
        "row 12's statement of the limit has changed wording; the limit itself is "
        "asserted by the mechanism test below, so reconcile the two deliberately "
        "rather than editing one of them"
    )


def test_a_TLS_wrap_STILL_discards_the_guarded_socket() -> None:
    """The mechanism half, measured rather than quoted.

    `ssl.SSLSocket._create` builds a NEW object from `fileno=sock.fileno()` and
    then calls `sock.detach()`. `ssl.SSLSocket` inherits from the real
    `socket.socket` captured when `ssl` was imported, so the new object carries
    neither `_GuardedSocket.sendall` nor the external-screen tag, and the screen
    is not called with ciphertext — it is not called at all.
    """
    left, right = socket.socketpair()
    try:
        guarded = egress_guard._GuardedSocket(fileno=left.detach())
    except Exception as exc:  # pragma: no cover - construction shape changed
        right.close()
        pytest.skip(f"_GuardedSocket could not be built from a socketpair fd: {exc}")

    try:
        guarded._screen_outbound_enabled = True
        # Verification is left at PROTOCOL_TLS_CLIENT's defaults — check_hostname
        # on, CERT_REQUIRED — deliberately. Nothing here needs it relaxed: the
        # wrap is constructed with do_handshake_on_connect=False, so no
        # handshake, certificate check or peer ever occurs. A security suite is
        # the last place to leave a copyable example of disabled TLS verification.
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

        wrapped = context.wrap_socket(
            guarded, do_handshake_on_connect=False, server_hostname="example.invalid"
        )
        try:
            assert not isinstance(wrapped, egress_guard._GuardedSocket), (
                "the TLS wrap now PRESERVES the guarded socket. The exfil screen "
                "may reach real egress — re-measure it and rewrite claim-register "
                "row 12, which currently tells the operator it cannot (#1592)"
            )
            assert not getattr(wrapped, "_screen_outbound_enabled", False), (
                "the external-screen tag now SURVIVES the TLS wrap. Row 12 says "
                "it does not; re-measure and rewrite the row (#1592)"
            )
            assert wrapped.sendall.__qualname__ != (
                egress_guard._GuardedSocket.sendall.__qualname__
            ), (
                "the object that sends after a TLS wrap now uses the guarded "
                "sendall, which is where screening happens. Row 12 is stale (#1592)"
            )
        finally:
            wrapped.detach()
    finally:
        right.close()


def test_the_runtime_still_has_no_plaintext_egress_path() -> None:
    """The other half of why row 12's limit bites.

    A socket-layer screen would still be a real control if the runtime ever sent
    plaintext. It does not: the one sanctioned door refuses every non-HTTPS
    scheme. If that constant ever widens, the screen acquires traffic it can see
    and row 12 changes meaning.
    """
    from shared.security import guarded_fetch

    assert guarded_fetch._ALLOWED_SCHEME == "https", (
        "the egress door now permits a non-HTTPS scheme, so plaintext egress is "
        "possible and the exfil screen would see it. Row 12 describes a control "
        "with no reachable traffic; re-measure and rewrite it (#1592)"
    )


def test_this_lock_is_pointed_at_the_real_mechanism_not_a_copy() -> None:
    """The off-test's job, done against the lock itself.

    The mechanism test would pass vacuously if `_GuardedSocket` stopped defining
    `sendall` at all, or if the tag attribute were renamed — both would make the
    assertions trivially true while the real control quietly changed shape. This
    asserts the things the test above is looking AT actually exist.
    """
    assert hasattr(egress_guard._GuardedSocket, "sendall"), (
        "_GuardedSocket no longer defines sendall, so the screening seam moved "
        "and the test above is asserting nothing"
    )
    assert "_screen_outbound_enabled" in inspect.getsource(
        egress_guard._GuardedSocket
    ), (
        "the external-screen tag attribute was renamed; the test above checks a "
        "name that no longer means anything"
    )
