"""#1545: the CAR's externality fields are covered by the action hash.

The Canonical Action Representation carried source agent, destination, verb, resource,
the argument schema and sensitivity. CAVA's open schema (read from `schema.js`, 2026-09-17)
requires FIVE fields: `runtime`, `operation`, `category`, `systems_touched` and
`reversible`, with `target` optional. BlarAI already covers `runtime` and `operation`
through `source_agent`/`destination_service` and `verb` — an earlier version of this
docstring silently shortened the required list to three, which is the shape that gets
cited later as if it were the schema. The four this ticket adds already existed in BlarAI
as prose inside `RiskTier`'s comments rather than as fields anything could read.

Why the hash matters more than the fields: #1541 binds an operator's approval to
`canonical_hash()` and re-derives it immediately before `tools.execute`. Anything the hash
does not cover is something an approval **cannot be made to mean**. These locks exist so a
later change cannot quietly drop a field out of the hash and leave the binding narrower
than it reads.
"""

from __future__ import annotations

import pytest

from shared.schemas.car import (
    VOLATILE_FIELDS,
    ActionCategory,
    ActionVerb,
    CanonicalActionRepresentation,
    Reversibility,
    Sensitivity,
)


def _car(**overrides) -> CanonicalActionRepresentation:
    base = dict(
        source_agent="assistant_orchestrator",
        destination_service="substrate",
        verb=ActionVerb.EXECUTE,
        resource="tool:web_search",
        parameters_schema={"type": "object"},
        sensitivity=Sensitivity.INTERNAL,
        request_id="req-1",
    )
    base.update(overrides)
    return CanonicalActionRepresentation(**base)


class TestEachExternalityFieldIsInTheHash:
    """Changing any one of the four must change the hash.

    These are PER-FIELD locks and nothing more. They do NOT catch a fifth field added
    without being hashed — the list below is hand-maintained, so whoever forgets to
    hash a new field is whoever would have to remember to add its row. An earlier
    commit message claimed otherwise and an adversarial review falsified it in one
    mutation. `TestEveryModelFieldIsHashedOrExplicitlyVolatile` is what actually
    holds that property; this class is the readable per-field statement of it.
    """

    @pytest.mark.parametrize(
        "field, value",
        [
            ("category", ActionCategory.EGRESS),
            ("systems_touched", ("network",)),
            ("reversible", Reversibility.IRREVERSIBLE),
            ("target", "https://example.invalid/path"),
        ],
    )
    def test_field_change_changes_the_hash(self, field: str, value) -> None:
        baseline = _car().canonical_hash()
        changed = _car(**{field: value}).canonical_hash()

        assert changed != baseline, (
            f"{field!r} does not contribute to canonical_hash(). #1541 binds approvals to "
            f"this hash, so a field outside it is a field an approval cannot be made to "
            f"mean — an operator could approve one value and a different one could execute."
        )

    def test_identical_cars_hash_identically(self) -> None:
        """The toggle for the above: without this, a hash that changed on EVERY call
        would pass every test in this class while being useless."""
        assert _car().canonical_hash() == _car().canonical_hash()


class TestEveryModelFieldIsHashedOrExplicitlyVolatile:
    """THE STRUCTURAL LOCK. Adding a field to the model without hashing it fails here.

    The parametrised class above cannot do this job and an adversarial review of #1545
    proved it: its list is hand-maintained, so the person who forgets to hash a new
    field is the same person who would have to remember to add its row. The reviewer
    added a fifth field, left it out of the hash, and the entire suite stayed green.

    This compares the hash payload's KEY SET against `model_fields` itself, so the
    model is the source of truth rather than a list anyone has to remember.
    """

    def test_hash_covers_every_non_volatile_field(self) -> None:
        hashed = set(_car()._hashable_payload().keys())
        declared = set(CanonicalActionRepresentation.model_fields) - VOLATILE_FIELDS

        missing = declared - hashed
        assert not missing, (
            f"model field(s) {sorted(missing)} are NOT in canonical_hash(). #1541 binds "
            f"an operator's approval to this hash, so an unhashed field is a field an "
            f"approval cannot be made to mean — approve one value, execute another, and "
            f"the re-derived hash still matches. Either hash it, or add it to "
            f"VOLATILE_FIELDS with a reason."
        )

    def test_hash_does_not_invent_keys_the_model_lacks(self) -> None:
        """The other direction: a hashed key with no backing field is dead weight
        that would silently survive a field rename."""
        hashed = set(_car()._hashable_payload().keys())
        declared = set(CanonicalActionRepresentation.model_fields)

        assert not (hashed - declared), (
            f"canonical_hash() hashes {sorted(hashed - declared)}, which is not a model "
            "field — a rename has left a stale key behind"
        )

    def test_volatile_fields_are_real_fields(self) -> None:
        """VOLATILE_FIELDS must name actual fields, or the exclusion list rots into
        a set of strings that excludes nothing and the first test passes vacuously."""
        declared = set(CanonicalActionRepresentation.model_fields)
        assert VOLATILE_FIELDS <= declared, (
            f"VOLATILE_FIELDS names {sorted(VOLATILE_FIELDS - declared)}, which no "
            "longer exist on the model"
        )


class TestSystemsTouchedIsOrderInsensitive:
    """Two CARs describing the same action must not differ by list order alone."""

    def test_order_does_not_change_the_hash(self) -> None:
        a = _car(systems_touched=("network", "knowledge_bank")).canonical_hash()
        b = _car(systems_touched=("knowledge_bank", "network")).canonical_hash()

        assert a == b, (
            "systems_touched is order-sensitive in the hash. That makes an approval "
            "binding defeatable by shuffling the sequence: approve one ordering, "
            "execute another, and the re-derived hash mismatches on a difference that "
            "describes the same action."
        )

    def test_duplicates_do_not_change_the_hash(self) -> None:
        a = _car(systems_touched=("network",)).canonical_hash()
        b = _car(systems_touched=("network", "network")).canonical_hash()

        assert a == b, "a repeated entry describes the same action and must hash the same"

    def test_a_GENUINELY_different_set_still_differs(self) -> None:
        """The toggle: normalisation must not flatten real differences away."""
        a = _car(systems_touched=("network",)).canonical_hash()
        b = _car(systems_touched=("network", "filesystem")).canonical_hash()

        assert a != b, "normalisation has gone too far — distinct system sets now collide"

    def test_SAME_CARDINALITY_different_members_still_differ(self) -> None:
        """The case the length-based toggle above cannot see.

        Adversarial review of #1545 found that the previous over-normalisation toggle
        used sets differing in BOTH length and first element, which left the two most
        destructive weakenings undetected: reducing the hash to `len(set(...))` or to
        `sorted(set(...))[:1]` both passed the whole suite.

        Under a count-only hash, a local knowledge read and a network egress become
        the same action identity — so an approval for one would cover the other and
        #1541's re-derivation would match. These two fixtures have identical
        cardinality, so only genuine member-sensitivity distinguishes them.
        """
        a = _car(systems_touched=("knowledge_bank",)).canonical_hash()
        b = _car(systems_touched=("network",)).canonical_hash()

        assert a != b, (
            "systems_touched collapses distinct single-member sets onto one hash. A "
            "local read and a network egress now share an action identity, which makes "
            "an approval for either cover both."
        )

    def test_same_cardinality_multi_member_sets_still_differ(self) -> None:
        """The same trap one size up, which `[:1]` would otherwise survive."""
        a = _car(systems_touched=("filesystem", "network")).canonical_hash()
        b = _car(systems_touched=("filesystem", "knowledge_bank")).canonical_hash()

        assert a != b, (
            "two-member sets sharing their alphabetically-first element collide — the "
            "hash is reading a prefix rather than the whole set"
        )

    def test_near_miss_names_do_not_collide(self) -> None:
        """Normalisation must not case-fold or strip punctuation.

        Both weakenings escaped the original toggle. `knowledge_bank` and
        `knowledgebank` are different identifiers and must stay different.
        """
        assert (
            _car(systems_touched=("knowledge_bank",)).canonical_hash()
            != _car(systems_touched=("knowledgebank",)).canonical_hash()
        )
        assert (
            _car(systems_touched=("network",)).canonical_hash()
            != _car(systems_touched=("NETWORK",)).canonical_hash()
        )


class TestDefaultsAreUnclassifiedNotPermissive:
    """The defaults are a named gap, and the names must stay honest."""

    def test_defaults_are_the_unknown_variants(self) -> None:
        car = _car()

        assert car.category is ActionCategory.UNKNOWN
        assert car.reversible is Reversibility.UNKNOWN
        assert car.systems_touched == ()
        assert car.target == ""

    def test_unknown_is_not_an_alias_for_a_permissive_value(self) -> None:
        """UNKNOWN must be a distinct member, not a synonym.

        If UNKNOWN were ever collapsed onto REVERSIBLE or COMPUTE, every
        unclassified action would silently acquire the most permissive reading —
        the misclassification-by-default that `Sensitivity` has no default in order
        to avoid.
        """
        # Pin the exact value set. A derived comparison CANNOT catch this class:
        # writing `UNKNOWN = "RETRIEVE"` makes RETRIEVE an ALIAS member, and Python
        # skips aliases when iterating an Enum — so `{m.value for m in ActionCategory}`
        # never contains "RETRIEVE" and a set-difference assertion passes while the
        # two names have silently become one member. Found by mutation-testing the
        # fix for #1545 review finding 6, which had exactly that hole.
        assert {m.name: m.value for m in ActionCategory} == {
            "UNKNOWN": "UNKNOWN",
            "COMPUTE": "COMPUTE",
            "RETRIEVE": "RETRIEVE",
            "GENERATE": "GENERATE",
            "MUTATE": "MUTATE",
            "EGRESS": "EGRESS",
        }, "an ActionCategory member was renamed, removed, or aliased onto another"
        assert {m.name: m.value for m in Reversibility} == {
            "UNKNOWN": "UNKNOWN",
            "REVERSIBLE": "REVERSIBLE",
            "IRREVERSIBLE": "IRREVERSIBLE",
        }, "a Reversibility member was renamed, removed, or aliased onto another"
        # Aliasing collapses the member count; assert it directly too.
        assert len(ActionCategory) == 6 and len(Reversibility) == 3


class TestHashStillExcludesVolatileFields:
    """#1545 must not accidentally widen the hash onto timestamp/request_id.

    The Hello envelope's N=3 approval lease (LA decision 2026-07-02) depends on two
    requests for the same action hashing the same. A hash that moved per-request would
    break that lease silently.
    """

    def test_request_id_does_not_change_the_hash(self) -> None:
        assert _car(request_id="req-1").canonical_hash() == _car(request_id="req-2").canonical_hash()

    def test_session_id_does_not_change_the_hash(self) -> None:
        a = _car(session_id="s1").canonical_hash()
        b = _car(session_id="s2").canonical_hash()
        assert a == b
