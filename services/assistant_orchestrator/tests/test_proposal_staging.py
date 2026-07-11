"""
Preference-proposal staging store (#770 M2 W1).
================================================
The confirm-hop integrity mechanism: system-owned verbatim bytes, opaque
single-use tokens, bounded ring.  These lock the token minting, single-use
consume, bounded eviction, and the card projection.
"""

from __future__ import annotations

from shared.ipc.preference_proposal import PROPOSAL_TOKEN_RE, ProposalAction

from services.assistant_orchestrator.src.proposal_staging import (
    ProposalStaging,
    StagedProposal,
)


def _stage_add(store: ProposalStaging, body: str = "always use metric") -> StagedProposal:
    return store.stage(
        action=ProposalAction.ADD, body=body, type_tag="standing-rule",
        provenance_label="your last message", untrusted_context=False,
    )


class TestStaging:
    def test_stage_mints_a_valid_16hex_token(self) -> None:
        store = ProposalStaging()
        staged = _stage_add(store)
        assert PROPOSAL_TOKEN_RE.fullmatch(staged.token)
        assert store.count() == 1

    def test_tokens_are_unique(self) -> None:
        store = ProposalStaging()
        tokens = {_stage_add(store, body=f"pref {i}").token for i in range(20)}
        assert len(tokens) == 20

    def test_get_peeks_pop_consumes(self) -> None:
        store = ProposalStaging()
        staged = _stage_add(store)
        assert store.get(staged.token) is staged           # peek does not consume
        assert store.count() == 1
        assert store.pop(staged.token) is staged           # pop consumes
        assert store.count() == 0
        assert store.pop(staged.token) is None             # single-use — gone

    def test_unknown_token_is_none(self) -> None:
        store = ProposalStaging()
        assert store.get("f" * 16) is None
        assert store.pop("f" * 16) is None

    def test_bounded_ring_evicts_oldest(self) -> None:
        store = ProposalStaging(max_entries=3)
        first = _stage_add(store, body="one")
        _stage_add(store, body="two")
        _stage_add(store, body="three")
        assert store.count() == 3
        _stage_add(store, body="four")           # over cap → evict oldest (first)
        assert store.count() == 3
        assert store.get(first.token) is None    # the oldest was evicted

    def test_to_card_projection_carries_the_fields(self) -> None:
        store = ProposalStaging()
        staged = store.stage(
            action=ProposalAction.REPLACE, body="new body", type_tag="fact",
            target_pref_id="a" * 32, provenance_label="a document you loaded",
            untrusted_context=True, target_number=2, target_body="old body",
        )
        card = staged.to_card()
        assert card.token == staged.token
        assert card.action is ProposalAction.REPLACE
        assert card.body == "new body"
        assert card.target_body == "old body"
        assert card.target_number == 2
        assert card.untrusted_context is True

    def test_clear_drops_all(self) -> None:
        store = ProposalStaging()
        _stage_add(store)
        _stage_add(store)
        store.clear()
        assert store.count() == 0
