"""
Preference-proposal STAGING store (#770 M2 W1) — confirm-hop integrity.
========================================================================
When the 14B proposes a standing preference mid-conversation
(``propose_preference``), the proposed VERBATIM bytes are staged HERE — an
AO-instance, system-owned, ephemeral store — and the operator is shown a card
referencing an opaque token.  When the operator confirms (an operator-typed /
clicked ``/remember-confirm <token>`` that rides the PREFERENCE_WRITE door), the
handler pops the staged proposal and commits *these* bytes.

Why staging exists (P2 across the proposal hop, study §5.2 case 5): the model
never touches the body between proposal and commit.  The confirm frame carries
only the TOKEN, not a body — so a model that restated the preference during a
later turn cannot change what gets committed.  The authoritative bytes live on
the SYSTEM side (this store), never re-supplied by the model at confirm time.

Structural separation (study §5.1 — source isolation between the proposal
channel and the write channel): this module imports NOTHING from the store
write API (``store_preference`` / ``update_preference`` / ``delete_preference``)
and performs NO write — it only holds decided-proposal data.  The proposal
channel stages here; the WRITE happens only in the operator-driven confirm
handler.  ``test_preference_write_authority.py`` locks that this file names no
write API.

Bounded + single-use: at most ``max_entries`` proposals are retained (oldest
evicted — a DoS guard on model-initiated proposals); a token is consumed on
confirm/dismiss (``pop``) so it can never be replayed.  A stale/unknown token
fails closed (``None`` → the handler refuses with UNKNOWN_TOKEN).
"""

from __future__ import annotations

import secrets
import time
from collections import OrderedDict
from typing import NamedTuple

from shared.ipc.preference_proposal import ProposalAction, ProposalCard

#: Default cap on retained proposals (bounds model-initiated staging; a
#: legitimate operator confirms within a handful of turns, so a small ring is
#: ample and the oldest unconfirmed proposals simply age out).
DEFAULT_MAX_STAGED_PROPOSALS: int = 32


class StagedProposal(NamedTuple):
    """One staged proposal — the authoritative, system-owned proposal bytes."""

    token: str
    action: ProposalAction
    body: str                 # verbatim proposed body (ADD/REPLACE); '' for RETRACT
    type_tag: str
    target_pref_id: str       # existing row id (REPLACE/RETRACT); '' for ADD
    provenance_label: str
    untrusted_context: bool
    target_number: int
    target_body: str          # existing row's verbatim body (REPLACE/RETRACT); '' for ADD
    created_monotonic: float

    def to_card(self) -> ProposalCard:
        """Project onto the shared card model (what the AO streams to render)."""
        return ProposalCard(
            token=self.token,
            action=self.action,
            body=self.body,
            type_tag=self.type_tag,
            provenance_label=self.provenance_label,
            untrusted_context=self.untrusted_context,
            target_pref_id=self.target_pref_id,
            target_number=self.target_number,
            target_body=self.target_body,
        )


class ProposalStaging:
    """AO-instance ephemeral store of staged preference proposals.

    Not thread-safe by design — the AO tool loop is synchronous within a turn
    and the confirm arrives as its own connection-per-message request; there is
    no concurrent mutation of a single instance in the service's model.
    """

    def __init__(self, max_entries: int = DEFAULT_MAX_STAGED_PROPOSALS) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1")
        self._max_entries = max_entries
        self._entries: "OrderedDict[str, StagedProposal]" = OrderedDict()

    def _mint_token(self) -> str:
        """A fresh, unguessable, unique 16-hex staging token."""
        for _ in range(8):  # collision retry (astronomically unlikely)
            token = secrets.token_hex(8)
            if token not in self._entries:
                return token
        # Degenerate fallback — still unique against the current set.
        return secrets.token_hex(8) + secrets.token_hex(8)[:0] or secrets.token_hex(8)

    def stage(
        self,
        *,
        action: ProposalAction,
        body: str,
        type_tag: str,
        target_pref_id: str = "",
        provenance_label: str = "",
        untrusted_context: bool = False,
        target_number: int = 0,
        target_body: str = "",
    ) -> StagedProposal:
        """Stage one decided proposal and return it (with its minted token).

        Evicts the oldest entry first when at capacity (bounded ring).
        """
        while len(self._entries) >= self._max_entries:
            self._entries.popitem(last=False)  # evict oldest
        token = self._mint_token()
        staged = StagedProposal(
            token=token,
            action=action,
            body=body,
            type_tag=type_tag,
            target_pref_id=target_pref_id,
            provenance_label=provenance_label,
            untrusted_context=untrusted_context,
            target_number=target_number,
            target_body=target_body,
            created_monotonic=time.monotonic(),
        )
        self._entries[token] = staged
        return staged

    def get(self, token: str) -> StagedProposal | None:
        """Peek a staged proposal by token (no consume), or ``None`` if absent."""
        return self._entries.get(token)

    def pop(self, token: str) -> StagedProposal | None:
        """Consume a staged proposal by token (single-use), or ``None`` if absent.

        Confirm and dismiss both consume — a token is never honoured twice.
        """
        return self._entries.pop(token, None)

    def count(self) -> int:
        """Number of currently staged (unconsumed) proposals."""
        return len(self._entries)

    def clear(self) -> None:
        """Drop all staged proposals (AO stop / tests)."""
        self._entries.clear()


__all__ = [
    "DEFAULT_MAX_STAGED_PROPOSALS",
    "StagedProposal",
    "ProposalStaging",
]
