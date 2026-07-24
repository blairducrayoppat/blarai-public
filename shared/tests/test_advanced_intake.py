"""Tests for #1031 S1 — the advanced-intake spec floors inside ``generate_plan``.

Two deterministic rulers, both gated on ``advanced_intake``:

* the **realism guard** demotes any machine-tier criterion whose ``check`` names no runnable
  verification to ``human`` — never a manufactured check, never an auto-pass;
* the **delivery floor** gives a WEB-target spec a machine-gated criterion asserting the
  served page actually loads — the #1025 class, promoted from a post-hoc executability
  check to an AUTHORED criterion.

They run FLOOR-then-guard (#1041). The floor is idempotent by a reserved id and never reads
criteria wording; the order matters only through the guard's never-zero-tests invariant, and
floor-first avoids a redundant generic smoke. See the ordering test below.

``advanced_intake=False`` (the dormant default) must leave the spec byte-identical — that
toggle-off proof is the standing bar for every intake slice, and it is the test that
distinguishes "the flag gates the behaviour" from "the test cannot reach the behaviour".

Model calls are faked throughout (offline).
"""

from __future__ import annotations

import json

from shared.fleet.acceptance import (
    TEST_TIERS,
    TIER_BEHAVIOR,
    TIER_BUILD,
    TIER_HUMAN,
    TIER_SMOKE,
    TIER_VISUAL,
    AcceptanceCriterion,
    AcceptanceSpec,
    DELIVERY_FLOOR_ID,
    DecompositionOverride,
    _apply_realism_guard,
    _ensure_delivery_floor,
    generate_plan,
)

_MARKER_DECOMPOSE = "decomposing a software change request"
_MARKER_CRITERIA = "ACCEPTANCE CRITERIA"
_MARKER_BUILD_PLAN = "Classify what KIND of software"

_ONE_TASK_JSON = json.dumps([{"task": "build-it", "prompt": "Build the thing."}])


def _spec(criteria, surface="web"):
    return AcceptanceSpec(
        goal="a habit tracker page",
        criteria=tuple(criteria),
        assumptions=(),
        build_plan={"surface": surface, "candidates": [], "language_hint": None,
                    "complexity": "simple", "components": []},
    )


def _c(cid, text, tier, check=""):
    return AcceptanceCriterion(id=cid, text=text, tier=tier, check=check)


# ---------------------------------------------------------------------------
# Realism guard
# ---------------------------------------------------------------------------


def test_guard_demotes_objective_criterion_with_empty_check():
    spec = _spec([_c("c1", "the app is intuitive", TIER_BEHAVIOR, "")])
    out = _apply_realism_guard(spec)
    assert out.criteria[0].tier == TIER_HUMAN
    # text and check are untouched — the guard re-tiers, it never rewrites or invents.
    assert out.criteria[0].text == "the app is intuitive"
    assert out.criteria[0].check == ""


def test_guard_demotes_objective_criterion_with_a_whitespace_only_check():
    spec = _spec([_c("c1", "it feels premium", TIER_BUILD, "   ")])
    assert _apply_realism_guard(spec).criteria[0].tier == TIER_HUMAN


def test_guard_does_NOT_demote_a_useless_but_NON_EMPTY_check_known_limitation():
    """KNOWN AND ACCEPTED LIMITATION, recorded rather than hidden.

    "It should feel polished." is not a runnable check, and the guard keeps it at build tier.
    The first implementation tried to catch exactly this with a substring allowlist and was
    demolished in review: it demoted this file's own prompt-template examples ("2 + 3 shows
    5") while keeping pure-judgment text on collisions ("import" inside "important"). Deciding
    runnability from prose is not a regex problem, so the ambition was withdrawn rather than
    tuned. This test pins the narrowed contract so a future session cannot mistake the gap for
    an oversight — closing it needs a model-assisted or schema-level check, not a longer list."""
    spec = _spec([_c("c1", "it feels premium", TIER_BUILD, "It should feel polished.")])
    assert _apply_realism_guard(spec).criteria[0].tier == TIER_BUILD


def test_guard_keeps_objective_criterion_whose_check_names_a_mechanism():
    spec = _spec([_c("c1", "it builds", TIER_BUILD, "Run the build and assert exit code 0.")])
    assert _apply_realism_guard(spec).criteria[0].tier == TIER_BUILD


def test_guard_never_touches_operator_judged_tiers():
    """A human/visual criterion has no mechanical check BY DESIGN — demoting it would be a
    no-op at best and a tier-churn at worst. The guard only ever looks at objective tiers."""
    spec = _spec([
        _c("c1", "looks clean", TIER_VISUAL, ""),
        _c("c2", "reads well", TIER_HUMAN, "Open it and read."),
    ])
    out = _apply_realism_guard(spec)
    assert [c.tier for c in out.criteria] == [TIER_VISUAL, TIER_HUMAN]


def test_guard_never_promotes():
    """A human-tier criterion with a perfectly runnable check stays human — the guard is
    one-directional. Promoting would silently claim machine verification nobody authored."""
    spec = _spec([_c("c1", "x", TIER_HUMAN, "Run the test suite and assert it passes.")])
    assert _apply_realism_guard(spec).criteria[0].tier == TIER_HUMAN


def test_guard_returns_the_same_object_when_nothing_changes():
    spec = _spec([_c("c1", "it builds", TIER_BUILD, "Run the build; assert exit code 0.")])
    assert _apply_realism_guard(spec) is spec


# ---------------------------------------------------------------------------
# Delivery floor
# ---------------------------------------------------------------------------


def test_delivery_floor_injected_for_web_surface():
    spec = _spec([_c("c1", "it builds", TIER_BUILD, "Run the build; assert exit 0.")])
    out = _ensure_delivery_floor(spec)
    assert len(out.criteria) == 2
    floor = out.criteria[-1]
    assert floor.tier == TIER_SMOKE          # machine-gated, and in TEST_TIERS
    assert floor.id == DELIVERY_FLOOR_ID     # #1041: a RESERVED id, not a positional one
    assert "loads" in floor.text.lower()


def test_delivery_floor_injected_for_web_static_surface():
    spec = _spec([_c("c1", "it builds", TIER_BUILD, "Run build; assert exit 0.")],
                 surface="web-static")
    assert len(_ensure_delivery_floor(spec).criteria) == 2


def test_delivery_floor_not_injected_for_non_web_surface():
    spec = _spec([_c("c1", "it builds", TIER_BUILD, "Run build; assert exit 0.")],
                 surface="command-line")
    out = _ensure_delivery_floor(spec)
    assert out is spec
    assert len(out.criteria) == 1


def test_delivery_floor_is_idempotent_BY_ID():
    """#1041 REWRITE — flagged to the reviewer, not asserted past.

    The previous version of this test asserted that a MODEL-AUTHORED delivery-ish criterion
    suppressed the floor. That behaviour is deliberately deleted: it was decided by
    substring-matching free-form English, which pre-merge review measured false-positiving on
    ordinary web criteria ("Each page loads at most 5 entries per scroll") and thereby
    silently disabling the floor for the whole spec.

    Idempotency is now by IDENTITY, which is the property that actually needs to hold:
    running the floor twice must not add two."""
    once = _ensure_delivery_floor(_spec([_c("c1", "it builds", TIER_BUILD, "build; exit 0")]))
    twice = _ensure_delivery_floor(once)
    assert twice is once, "second application must be a no-op on the SAME object"
    assert sum(1 for c in once.criteria if c.id == DELIVERY_FLOOR_ID) == 1


def test_a_model_authored_delivery_criterion_NO_LONGER_suppresses_the_floor():
    """The deliberate consequence of #1041, pinned so it cannot be mistaken for a defect.

    The spec may now carry two delivery criteria — the model's and the floor's. That is the
    trade, made with eyes open: a duplicate criterion costs one extra test, whereas a false
    suppression cost the entire guarantee this feature exists to provide. Review measured the
    old predicate failing in BOTH directions, so there is no wording rule to fall back to."""
    spec = _spec([
        _c("c1", "the served page loads and shows the habit list", TIER_SMOKE,
           "Serve the page and assert the list renders."),
    ])
    out = _ensure_delivery_floor(spec)
    assert len(out.criteria) == 2, "the floor must inject alongside the model's own criterion"
    assert any(c.id == DELIVERY_FLOOR_ID for c in out.criteria)


def test_an_ordinary_web_criterion_mentioning_page_loads_does_not_disable_the_floor():
    """The regression that motivated #1041. Under the old substring predicate each of these
    silently suppressed the floor for the whole spec; none may now."""
    for text in (
        "Each page loads at most 5 entries per scroll.",
        "The settings page loads the saved theme from localStorage.",
        "The export never renders in a browser tab that is already busy.",
    ):
        out = _ensure_delivery_floor(_spec([_c("c1", text, TIER_BEHAVIOR, "assert it")]))
        assert any(c.id == DELIVERY_FLOOR_ID for c in out.criteria), f"floor suppressed by: {text}"


def test_the_reserved_floor_id_cannot_collide_with_a_positional_id():
    """Review nit N1: the old `c{len+1}` scheme collided when ids were non-sequential."""
    spec = _spec([_c("c1", "a", TIER_BUILD, "x"), _c("c7", "b", TIER_BUILD, "y")])
    out = _ensure_delivery_floor(spec)
    ids = [c.id for c in out.criteria]
    assert len(ids) == len(set(ids)), f"duplicate criterion id: {ids}"
    assert DELIVERY_FLOOR_ID in ids


def test_delivery_floor_ignores_an_operator_judged_delivery_claim():
    """A VISUAL 'page loads' criterion is not a machine gate, so the floor must still fire —
    otherwise an eyeball criterion would suppress the only automatic delivery check."""
    spec = _spec([_c("c1", "the page loads nicely", TIER_VISUAL, "Look at it.")])
    assert len(_ensure_delivery_floor(spec).criteria) == 2


# ---------------------------------------------------------------------------
# Ordering: floor-then-guard, and it is LOCKED — the two orders differ via the invariant
# ---------------------------------------------------------------------------


def test_a_fake_delivery_claim_is_still_demoted_and_the_floor_still_lands():
    """An objective-tier criterion with an empty check is demoted, and a real delivery floor
    is present regardless. This holds under floor-then-guard, the shipped order."""
    spec = _spec([
        _c("c1", "the served page loads", TIER_SMOKE, ""),          # claims delivery, no check
        _c("c2", "the totals are right", TIER_BEHAVIOR, "assert total() == 6"),
    ])
    out = _apply_realism_guard(_ensure_delivery_floor(spec))
    assert any(c.tier == TIER_HUMAN for c in out.criteria)         # the empty-check claim, demoted
    assert any(c.id == DELIVERY_FLOOR_ID for c in out.criteria)    # a real floor is present


#: A web spec whose SOLE test-tier criterion has an empty check. Under floor-then-guard the
#: delivery floor lands first, so TEST_TIERS is never emptied and no generic never-zero-tests
#: smoke appears; under guard-then-floor the demotion momentarily empties TEST_TIERS and a
#: redundant "runs without crashing" smoke is injected. This is the input class where the two
#: orders differ (review #1041-1).
_EMPTY_CHECK_SMOKE_CRITERIA = json.dumps([
    {"text": "the served page loads", "tier": "smoke", "check": ""},
])


def _generic_neverzero_smokes(criteria):
    """The generic 'never zero tests' smoke _ensure_test_floor injects — distinct from the
    delivery floor (matched by id) and from the empty-check claim (matched by tier)."""
    return [c for c in criteria
            if c.tier == TIER_SMOKE and c.id != DELIVERY_FLOOR_ID
            and "loads" not in c.text.lower()]


def test_gate_order_is_floor_then_guard_THROUGH_generate_plan(tmp_path):
    """#1041-1 lock, driven through the REAL generate_plan — NOT a hand-composed call.

    The two rulers couple through the guard's never-zero-tests invariant, so the shipped
    call-site order is load-bearing and the output differs (review measured 258 distinguishing
    inputs). L4-1's lesson is that a test composing the helpers ITSELF cannot catch the wiring
    being reversed; this drives the gate so a future 'cleanup' that swaps the two lines is
    caught. Mutant B1 (reverse the shipped order) must turn this RED.

    Shipped floor-then-guard on an empty-check web spec: the delivery floor is present, the
    empty-check claim is demoted to human, and there is NO generic never-zero-tests smoke.
    """
    proj, repo = _repo(tmp_path)
    plan = generate_plan("a habit tracker page", repo,
                         generate_fn=_gen(_EMPTY_CHECK_SMOKE_CRITERIA),
                         projects_dir=proj, advanced_intake=True)
    crit = plan.spec.criteria
    assert any(c.id == DELIVERY_FLOOR_ID for c in crit), "delivery floor missing"
    assert any(c.tier == TIER_HUMAN for c in crit), "empty-check claim not demoted"
    # The discriminating assertion: floor-first produces NO generic smoke; guard-first would.
    assert _generic_neverzero_smokes(crit) == [], (
        "a generic never-zero-tests smoke appeared — the gate ran guard-then-floor, not the "
        "shipped floor-then-guard (the two lines are reversed)")


# ---------------------------------------------------------------------------
# Through generate_plan — including the toggle-off proof
# ---------------------------------------------------------------------------


def _repo(tmp_path):
    proj = tmp_path / "projects"
    (proj / "myapp" / ".git").mkdir(parents=True, exist_ok=True)
    return proj, "myapp"


def _gen(criteria_json: str, surface: str = "web"):
    def gen(prompt: str) -> str:
        if _MARKER_CRITERIA in prompt:
            return criteria_json
        if _MARKER_BUILD_PLAN in prompt:
            return json.dumps({"surface": surface, "candidates": [], "language_hint": None,
                               "complexity": "simple", "components": []})
        if _MARKER_DECOMPOSE in prompt:
            return _ONE_TASK_JSON
        return "[]"
    return gen


_WEAK_CRITERIA = json.dumps([
    {"text": "the project builds", "tier": "build", "check": ""},
])


def test_advanced_intake_on_adds_the_delivery_floor_and_demotes_the_weak_criterion(tmp_path):
    proj, repo = _repo(tmp_path)
    plan = generate_plan("a habit tracker page", repo, generate_fn=_gen(_WEAK_CRITERIA),
                         projects_dir=proj, advanced_intake=True)
    tiers = [c.tier for c in plan.spec.criteria]
    # the empty-check build criterion was demoted ...
    assert TIER_BUILD not in tiers
    assert TIER_HUMAN in tiers
    # ... and a real machine-gated delivery criterion exists
    assert any(c.tier == TIER_SMOKE and "loads" in c.text.lower()
               for c in plan.spec.criteria)


def test_advanced_intake_off_is_byte_identical(tmp_path):
    """The standing toggle-off bar: with the flag off, the spec is unchanged from today —
    same criteria, same tiers, same checks, same count. If this ever passes while the ON
    test above also passes trivially, the gate is not reachable."""
    proj, repo = _repo(tmp_path)
    off = generate_plan("a habit tracker page", repo, generate_fn=_gen(_WEAK_CRITERIA),
                        projects_dir=proj, advanced_intake=False)
    default = generate_plan("a habit tracker page", repo, generate_fn=_gen(_WEAK_CRITERIA),
                            projects_dir=proj)
    assert [c.to_dict() for c in off.spec.criteria] == \
           [c.to_dict() for c in default.spec.criteria]
    # and the weak criterion is STILL build-tier when the flag is off (proves the ON test
    # above is measuring the flag, not some unconditional behaviour)
    assert any(c.tier == TIER_BUILD for c in off.spec.criteria)
    assert not any(c.tier == TIER_SMOKE and "loads" in c.text.lower()
                   for c in off.spec.criteria)


def test_battery_card_never_receives_the_intake_floors(tmp_path):
    """A battery/headless card dispatch MUST bypass both floors even with the flag ON.

    The card IS the spec and is frozen for cross-night comparability. If the floors applied
    here, switching the flag on would silently rewrite a card's exam — B5 is a web card, so
    it would gain a delivery criterion it was never authored with, and every night before and
    after the flip would be measuring different instruments. This is the same self-suppression
    ``clarify`` carries, for a stronger reason.
    """
    proj, repo = _repo(tmp_path)
    override = DecompositionOverride(
        tasks=[{"task": "build-page", "prompt": "build the page",
                "contract": {"creates": ["app/page.py"], "exports": []}}],
        job_oracle_code="",
        job_oracle_path="",
    )
    plan = generate_plan("a habit tracker page", repo, generate_fn=_gen(_WEAK_CRITERIA),
                         projects_dir=proj, advanced_intake=True,
                         decomposition_override=override)
    # the card's weak criterion is UNTOUCHED — not demoted ...
    assert any(c.tier == TIER_BUILD for c in plan.spec.criteria), \
        "the realism guard rewrote a frozen battery card's criteria"
    # ... and no delivery floor was injected into the card's exam
    assert not any(c.tier == TIER_SMOKE and "loads" in c.text.lower()
                   for c in plan.spec.criteria), \
        "the delivery floor injected a criterion into a frozen battery card"


# ---------------------------------------------------------------------------
# Card-driven suppression — the BLOCKER found in pre-merge review.
#
# The first predicate was `decomposition_override is None`, which is NOT "not a battery
# card": an override is built only for cards with a registered arm builder (B1/B2/B4 today),
# so B3, B5, B6, B7 and B8 — INCLUDING BOTH WEB CARDS — arrived with override=None and the
# gate opened on them. The delivery floor fires on web surfaces, so the two exposed web cards
# were exactly the ones that would have had a criterion injected into a frozen exam.
# ---------------------------------------------------------------------------


def _battery_repo(tmp_path, name="battery-b5-habit-web"):
    proj = tmp_path / "projects"
    (proj / name / ".git").mkdir(parents=True, exist_ok=True)
    return proj, name


def test_card_sandbox_prefix_is_pinned_to_its_two_mirrors():
    """The prefix exists in three modules because battery_plans imports FROM acceptance, so
    acceptance cannot import it back. Pin all three equal — a silent drift would re-open the
    blocker above on whichever copy fell behind."""
    from shared.fleet import battery_plans as bp
    from shared.fleet import coord_lifecycle as cl
    from shared.fleet.acceptance import _CARD_SANDBOX_REPO_PREFIX

    assert _CARD_SANDBOX_REPO_PREFIX == bp._SANDBOX_REPO_PREFIX
    assert _CARD_SANDBOX_REPO_PREFIX == cl.TEST_ORIGIN_REPO_PREFIX


def test_battery_card_WITHOUT_an_override_is_still_suppressed(tmp_path):
    """The regression that review caught. B5 is a frozen WEB card with no registered arm
    builder, so it reaches generate_plan with override=None. Before the fix, the delivery
    floor injected a machine-gated criterion into its exam — and because TIER_SMOKE is in
    TEST_TIERS, compile_prompts would have carried it to the coder as a test instruction,
    changing what a frozen card builds and how it is graded on the night the flag flips."""
    proj, repo = _battery_repo(tmp_path)
    plan = generate_plan("a habit tracker page", repo, generate_fn=_gen(_WEAK_CRITERIA),
                         projects_dir=proj, advanced_intake=True)  # NOTE: no override
    assert any(c.tier == TIER_BUILD for c in plan.spec.criteria), \
        "the realism guard rewrote a frozen battery card's criteria (no-override path)"
    assert not any(c.tier == TIER_SMOKE and "loads" in c.text.lower()
                   for c in plan.spec.criteria), \
        "the delivery floor injected a criterion into a frozen battery card (no-override path)"


def test_is_card_driven_covers_both_signals():
    from shared.fleet.acceptance import _is_card_driven
    assert _is_card_driven("battery-b5-habit-web", None) is True     # prefix alone
    assert _is_card_driven("BATTERY-B3-Budget-Web", None) is True    # case-insensitive
    assert _is_card_driven("myapp", None) is False                   # an operator repo
    assert _is_card_driven("", None) is False
    assert _is_card_driven("my-battery-app", None) is False          # prefix, not substring


# ---------------------------------------------------------------------------
# NEVER-ZERO-TESTS INVARIANT (pre-merge review, BLOCKER-3)
# ---------------------------------------------------------------------------


def test_demotion_may_not_take_the_spec_below_the_never_zero_tests_floor():
    """Demoting the ONLY test-tier criterion must not leave the spec with no machine
    verification at all. TIER_HUMAN is outside TEST_TIERS, and three consumers bail on an
    empty set: compile_prompts (the coder is told nothing about tests), the per-task oracle,
    and the JOB oracle — whose imports are what #989's coverage contract is derived from. So
    an unguarded demotion could delete the very contract this feature exists to guarantee."""
    spec = _spec([_c("c1", "the totals are right", TIER_BEHAVIOR, "")])
    assert any(c.tier in TEST_TIERS for c in spec.criteria)      # before: has tests
    out = _apply_realism_guard(spec)
    assert out.criteria[0].tier == TIER_HUMAN                    # the demotion still happens
    assert any(c.tier in TEST_TIERS for c in out.criteria),         "the guard emptied TEST_TIERS - compile_prompts and BOTH oracles would bail"


def test_invariant_does_not_fire_when_tests_survive():
    """No gratuitous floor: a spec keeping a test-tier criterion is not given another."""
    spec = _spec([
        _c("c1", "x", TIER_BUILD, ""),                            # demoted
        _c("c2", "the totals are right", TIER_BEHAVIOR, "assert total() == 6"),  # survives
    ])
    out = _apply_realism_guard(spec)
    assert len(out.criteria) == 2
    assert out.criteria[0].tier == TIER_HUMAN
    assert out.criteria[1].tier == TIER_BEHAVIOR


# ---------------------------------------------------------------------------
# #1042 L5-1 — neither ruler may drop a spec field.
# ---------------------------------------------------------------------------


def test_neither_ruler_drops_any_AcceptanceSpec_field():
    """Both rulers used to rebuild AcceptanceSpec field-by-field, naming four of its SIX
    fields and silently dropping ``asset_specs`` (UC-010 image specs) and ``clarifications``
    (#819 operator answers).

    Harmless at the time only because both attach AFTER this gate — but this branch moved
    the gate to immediately before the ``asset_specs`` attachment, so the distance between
    "correct" and "silently discards the operator's image specs" was one reordering, and
    this hook had already been reordered once during the build.

    Enumerates the dataclass rather than listing field names, so a SEVENTH field added later
    is covered by this lock the day it exists — which is the actual failure mode."""
    from dataclasses import fields

    populated = AcceptanceSpec(
        goal="a habit tracker page",
        criteria=(_c("c1", "the totals are right", TIER_BEHAVIOR, "assert total() == 6"),),
        assumptions=("saves locally",),
        build_plan={"surface": "web", "candidates": [], "language_hint": None,
                    "complexity": "simple", "components": []},
        asset_specs=({"name": "hero", "subject": "a calendar", "style": "flat"},),
        clarifications=({"question": "where", "answer": "in a browser", "assumed": False},),
    )
    untouched = [f.name for f in fields(AcceptanceSpec) if f.name != "criteria"]

    # Guard: force a demotion so it rebuilds rather than returning the same object.
    guarded = _apply_realism_guard(
        AcceptanceSpec(**{**{f.name: getattr(populated, f.name) for f in fields(populated)},
                          "criteria": (_c("c1", "it works", TIER_SMOKE, ""),)}))
    for name in untouched:
        assert getattr(guarded, name) == getattr(populated, name), f"guard dropped {name}"

    # Floor: a web spec with no delivery criterion, so it injects and rebuilds.
    floored = _ensure_delivery_floor(populated)
    assert len(floored.criteria) == len(populated.criteria) + 1, "floor did not fire — vacuous"
    for name in untouched:
        assert getattr(floored, name) == getattr(populated, name), f"floor dropped {name}"


def test_is_card_driven_matches_the_repo_BASENAME_like_both_mirrors():
    """#1042 R1-a — a path-shaped repo id must still be recognised as card-driven.

    Not observably broken in production (a bare name is what is passed today), but the raw
    string match diverged from the two mirrors it is pinned equal to, both of which basename
    first. A divergence between a constant's three copies is exactly what the pin test cannot
    see: it pins the VALUES equal, not the SEMANTICS."""
    from shared.fleet.acceptance import _is_card_driven

    assert _is_card_driven("battery-b5-habit-web", None) is True
    assert _is_card_driven("projects/battery-b5-habit-web", None) is True
    assert _is_card_driven("C:/Users/mrbla/projects/battery-b5-habit-web", None) is True
    assert _is_card_driven(r"C:\Users\mrbla\projects\battery-b5-habit-web", None) is True
    # And it must NOT fire on an operator repo that merely lives under a battery-ish parent.
    assert _is_card_driven("battery-ish/my-real-app", None) is False
    assert _is_card_driven("my-real-app", None) is False
