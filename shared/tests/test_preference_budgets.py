"""
Gate lock — operator-preference budgets (#770 M1, P4).
=======================================================
The timeout-registry discipline applied to token budgets: the caps are
REGISTERED with their measured evidence, and this gate cross-checks every
registry entry against its live constant so the table can never rot into
documentation-fiction.  The offline token estimator is PINNED here too —
a silent estimator drift would silently move the enforced cap (coordinator
requirement, 2026-07-09).

Changing any value below is a GOVERNANCE change: it must ship with an updated
registry entry (and, for the token cap, a re-measurement — the S8 pattern),
in the same change.
"""

from __future__ import annotations

import pytest

from shared import preference_budgets as budgets


class TestBudgetValuesPinned:
    """The three P4 caps are exactly the LA-approved, S8-justified values."""

    def test_pinned_block_token_cap(self) -> None:
        # From the S8 ON-curve: edit re-prefill ~4.2 s / cold ~9 s at 1024
        # estimated tokens; 2048 is operator-hostile (>9 s edits, >18 s cold).
        assert budgets.PINNED_BLOCK_TOKEN_CAP == 1024

    def test_per_preference_char_cap(self) -> None:
        assert budgets.PREFERENCE_BODY_MAX_CHARS == 500

    def test_active_count_cap(self) -> None:
        assert budgets.PREFERENCE_MAX_COUNT == 64

    def test_estimator_divisor(self) -> None:
        assert budgets.TOKEN_ESTIMATE_CHARS_PER_TOKEN == 3.0


class TestRegistryCrossCheck:
    """Every registry entry matches its live constant (anti-rot)."""

    def test_every_entry_matches_live_value(self) -> None:
        for entry in budgets.REGISTRY:
            live = getattr(budgets, entry.attribute)
            assert float(live) == entry.value, (
                f"Registry entry {entry.attribute!r} says {entry.value} but "
                f"the live constant is {live} — update BOTH in the same change."
            )

    def test_all_three_caps_are_registered(self) -> None:
        assert budgets.registry_attributes() == {
            "PINNED_BLOCK_TOKEN_CAP",
            "PREFERENCE_BODY_MAX_CHARS",
            "PREFERENCE_MAX_COUNT",
        }

    def test_entries_carry_evidence_and_rationale(self) -> None:
        for entry in budgets.REGISTRY:
            assert entry.evidence.strip(), f"{entry.attribute}: evidence required"
            assert entry.rationale.strip(), f"{entry.attribute}: rationale required"
            assert entry.review.strip(), f"{entry.attribute}: review trigger required"

    def test_token_cap_evidence_names_the_s8_artifact(self) -> None:
        (token_entry,) = [
            e for e in budgets.REGISTRY
            if e.attribute == "PINNED_BLOCK_TOKEN_CAP"
        ]
        assert "prefix_caching_ab_ov2026_2_1_0_2026-07-09" in token_entry.evidence
        assert "S8" in token_entry.evidence


class TestEstimatorPinned:
    """The conservative offline estimator cannot drift silently."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("", 0),                    # empty renders nothing
            ("a", 1),                   # ceil(1/3) = 1
            ("abc", 1),                 # ceil(3/3) = 1
            ("abcd", 2),                # ceil(4/3) = 2
            ("x" * 300, 100),           # ceil(300/3) = 100
            ("x" * 301, 101),           # ceil crosses on the next char
            ("call me Blair", 5),       # 13 chars -> ceil(13/3) = 5
        ],
    )
    def test_known_values(self, text: str, expected: int) -> None:
        assert budgets.estimate_tokens(text) == expected

    def test_estimator_is_conservative_for_english(self) -> None:
        # English Qwen3 text measures ~3.5-4.2 chars/token (the S8 blocks
        # measured ~4.1), so chars/3.0 must OVER-estimate: enforcing the cap
        # on the estimate keeps the real count strictly under it.  Pin the
        # direction with the measured S8 ratio: 4764 real tokens rendered
        # ~19,500 chars (~4.1 chars/token); the estimate at that length is
        # ceil(19500/3) = 6500 >= 4764.
        assert budgets.estimate_tokens("x" * 19_500) >= 4_764

    def test_monotonic_in_length(self) -> None:
        previous = 0
        for length in range(0, 50):
            current = budgets.estimate_tokens("y" * length)
            assert current >= previous
            previous = current
