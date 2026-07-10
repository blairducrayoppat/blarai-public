"""The Acceptance Layer for headless-coding dispatch (increment 3).

Turns a natural-language GOAL into a task decomposition PLUS an ``AcceptanceSpec`` —
plain-English criteria, each tagged by HOW it is verified — so a non-developer never
writes a test yet still gets *verifiable* work. The 14B PROPOSES criteria while it is
resident (before the model swap); a DETERMINISTIC RULER DISPOSES (drops vacuous /
malformed criteria, dedupes, caps, and guarantees at least the build gate). The
objective criteria are compiled INTO the fleet's task prompts so the 30B writes the
tests; the fleet's EXISTING gate runs them; the result is read back HONESTLY — a check
that never ran is UNVERIFIED, never a pass.

The fleet gate (``agentic-setup/scripts/new-agent-task.ps1``) is reused verbatim, never
modified:

  * BUILD     -> ``verify-project.ps1`` (``dotnet build`` / ``py:compile`` / ``npm run build``)
                 -> the report's ``VERIFY:`` line.
  * BEHAVIOR  -> the TESTS stage (``pytest`` / ``npm test``) running a coder-written test
                 -> the report's ``TESTS:`` line.
  * SMOKE     -> a behavior-tier "it starts without crashing" test (the fleet has NO
                 launch / console-scan stage — confirmed; the brief assumed one).
  * VISUAL    -> the operator opens the app and looks.
  * HUMAN     -> the operator judges fit.

Ecosystem honesty (the load-bearing anti-false-pass rule): Python + Node get real
behavior-gating (``pytest`` / ``npm test`` actually run). **.NET is BUILD-ONLY** —
``verify-project.ps1`` runs ``dotnet build`` but there is NO ``dotnet test`` and the
TESTS stage is ``pytest`` / ``npm test`` only, so a C#/UWP behavior or smoke test NEVER
runs and comes back ``none``. :func:`criterion_status` renders that as UNVERIFIED
("couldn't auto-check — verify yourself"), never a green check — the exact false-pass
this layer exists to prevent. The confirm-time preview says this UP FRONT so a
clean-looking report can never mislead.

The model call (``generate_fn``) is injected so this is fully testable without the GPU;
the live wiring passes the AO's text generator. DORMANT until ``[fleet_dispatch].enabled``.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from shared.fleet.decompose import DEFAULT_MAX_TASKS, DecomposeResult, decompose_request

# ---------------------------------------------------------------------------
# Tiers
# ---------------------------------------------------------------------------

TIER_BUILD = "build"
TIER_BEHAVIOR = "behavior"
TIER_SMOKE = "smoke"
TIER_VISUAL = "visual"
TIER_HUMAN = "human"

#: Tiers the fleet can (in principle) gate automatically.
OBJECTIVE_TIERS: frozenset[str] = frozenset({TIER_BUILD, TIER_BEHAVIOR, TIER_SMOKE})
#: Tiers only the operator can judge (open the app and look).
HUMAN_TIERS: frozenset[str] = frozenset({TIER_VISUAL, TIER_HUMAN})
ALL_TIERS: frozenset[str] = OBJECTIVE_TIERS | HUMAN_TIERS

#: Tiers whose criteria become coder test-writing instructions.
TEST_TIERS: frozenset[str] = frozenset({TIER_BEHAVIOR, TIER_SMOKE})

#: Slug of the dedicated final task that writes the acceptance tests.
ACCEPTANCE_TASK_SLUG = "acceptance-tests"

#: Repo-relative path the spec-derived acceptance ORACLE is seeded to (#690). ONE shared,
#: protected pytest file every best-of-N candidate codes against and is judged by — so the
#: gate compares candidates against the byte-identical scorecard instead of each candidate's
#: own self-written tests. ``tests/`` is the layout the seeded python skeleton already uses,
#: and a top-level import (``from calendar_math import add_days``) resolves from there.
ACCEPTANCE_ORACLE_PATH = "tests/test_acceptance.py"

#: Ecosystems whose behavior/smoke tests actually RUN in the fleet gate. .NET is
#: BUILD-ONLY (``dotnet build`` runs, but there is no ``dotnet test``).
BEHAVIOR_GATED_ECOSYSTEMS: frozenset[str] = frozenset({"python", "node"})

#: Hard cap on criteria from one goal.
DEFAULT_MAX_CRITERIA = 8
#: A criterion shorter than this (after strip) is vacuous and dropped.
_MIN_CRITERION_LEN = 5


# ---------------------------------------------------------------------------
# Build-signal (the 14B's COARSE product→platform classification) — increment 1
# ---------------------------------------------------------------------------
#
# A pure-product /dispatch goal ("a calculator that looks like a rocket") carries no
# technical signal, so the deterministic fleet's conservative scaffold picker no-ops and
# the coder authors a project from scratch (proliferation -> build error -> park). The fix
# is to stop discarding the one component that DOES understand the platform — the 14B at
# decompose time. It emits a COARSE, ENUM-CONSTRAINED build-signal (``build_plan``) from a
# PRODUCT-intent prompt; the deterministic fleet (the LA's separate lane) maps it to a
# scaffold + tech. BlarAI's job (this module): emit the signal, thread it onto every queue
# task object, and surface the resolved platform in the PLAN preview.
#
# Fail-closed is absolute: any parse/validation failure, missing field, or unknown enum
# value -> that field becomes ``unknown``/``None`` — NEVER raise, NEVER block PLAN/EXECUTE.
# A ``surface == unknown`` dispatch must reproduce TODAY'S behavior byte-identically (the
# fleet sees no usable signal and falls back to its current conservative no-seed path). The
# signal is a SEPARATE small model call (mirroring assumptions) so the criteria + assumptions
# JSON contracts stay byte-identical and their existing tests are untouched.

#: ``surface`` — the primary, reliably-inferrable signal ("what kind of thing does the
#: product have?"). ``unknown`` is the fail-closed sentinel (no scaffold downstream);
#: ``ambiguous`` (increment 4) is the DISTINCT sentinel the 14B uses when it genuinely
#: cannot tell which PLATFORM a clearly-GUI/app goal targets (desktop vs web vs phone) and
#: lists the real ``candidates`` it is torn between — the trigger for the system's one
#: curated clarifying question. It is NOT a buildable surface and (deliberately) carries no
#: ``_SURFACE_FRIENDLY`` entry, so it never renders a "Building this as" preview line.
SURFACE_VALUES: frozenset[str] = frozenset({
    "desktop-gui", "web", "mobile", "command-line", "automation", "library",
    "unknown", "ambiguous",
})
#: The fail-closed sentinel for an unclassifiable / malformed surface.
SURFACE_UNKNOWN = "unknown"
#: The ambiguity sentinel (increment 4) — the 14B FLAGS "I can't tell the platform"; the
#: SYSTEM owns the question (see :data:`_CLARIFY_DECISION_MAP`). DISTINCT from ``unknown``:
#: ``unknown`` = "couldn't classify at all" (no scaffold, today's behavior); ``ambiguous``
#: = "classified the KIND but the platform forks, here are the candidates" (ask one question).
SURFACE_AMBIGUOUS = "ambiguous"

#: The REAL, buildable surface enum — the only values a ``candidates`` entry may take (and
#: the only values an ``apply_clarification`` answer may resolve to). ``unknown`` and
#: ``ambiguous`` are sentinels, NOT buildable surfaces, so they are excluded: a candidate
#: list containing them (or any garbage) is filtered down to the real members fail-closed.
_REAL_SURFACES: frozenset[str] = SURFACE_VALUES - {SURFACE_UNKNOWN, SURFACE_AMBIGUOUS}

#: Hard cap on ambiguity candidates carried from one goal (a small fork-set; keeps the wire
#: small and the curated decision map tractable). The platform case is 3 (desktop/web/phone).
DEFAULT_MAX_CANDIDATES = 4

#: ``language_hint`` — set ONLY when the product explicitly implies a language; otherwise
#: ``None`` (the system never guesses a language the 14B did not signal — that is today's
#: behavior). Refines the ambiguous surfaces (command-line / library).
LANGUAGE_HINT_VALUES: frozenset[str] = frozenset({
    "python", "dotnet", "node", "cpp", "powershell",
})

#: ``complexity`` — the coarse size label. MUST match the fleet's ``add-fleet-task.ps1
#: -Complexity`` ValidateSet exactly (the cross-repo contract). ``moderate`` is the
#: fail-closed default (a safe middle the fleet already understands).
COMPLEXITY_VALUES: frozenset[str] = frozenset({"simple", "moderate", "complex"})
COMPLEXITY_DEFAULT = "moderate"

#: ``components[].kind`` — drives the fleet's within-task staging (§5.5). ``other`` is the
#: fail-closed default for an unrecognized kind.
KIND_VALUES: frozenset[str] = frozenset({
    "testable-logic", "gui-shell", "web-endpoint", "cli-command", "data", "other",
})
KIND_DEFAULT = "other"

#: Hard cap on classified components surfaced from one goal (keeps the wire small).
DEFAULT_MAX_COMPONENTS = 8

#: surface -> a friendly, operator-facing phrase for the PLAN preview's "Building this as"
#: line (BlarAI-side display map; the fleet's concrete BuildProfile is its own lane). A
#: surface absent from this map (incl. ``unknown`` AND ``ambiguous``) renders NO line —
#: never a guess (an ``ambiguous`` surface has no single platform to name; the clarifying
#: question resolves it to a real surface FIRST, then this map can render it).
_SURFACE_FRIENDLY: dict[str, str] = {
    "desktop-gui": "a Windows desktop app",
    "web": "a web app",
    "mobile": "an Android app",
    "command-line": "a command-line tool",
    "automation": "a system-automation script",
    "library": "a code library / script",
}


# ---------------------------------------------------------------------------
# Confidence-gated clarifying question — the curated decision map (increment 4)
# ---------------------------------------------------------------------------
#
# When (and ONLY when) the 14B flags ``surface == "ambiguous"`` + the real ``candidates``
# it is torn between, the SYSTEM — never the model — asks ONE curated, product-level
# question and maps each answer deterministically to a real surface. The 14B writes NO
# question text (small models write leading/irrelevant ones); it only FLAGS the fork.
#
# Scope discipline (the rubber-stamp-quiz guard): the map is SMALL by design — v1 is the
# PLATFORM/DEVICE case ONLY (desktop vs web vs phone), the textbook decision that (a)
# materially forks the build, (b) the 14B genuinely cannot assume from pure product intent,
# and (c) the operator can answer in product terms ("where will you use it?"). Everything
# else stays assume-and-show-in-the-preview (the assumptions block). A novice quizzed
# per-detail rubber-stamps — worse than not asking — so the map grows only when a NEW
# decision clears all three bars.
#
# Keyed on the FROZENSET of the candidate surfaces (order-independent — the 14B may list
# them in any order). The platform fork has four entries: the full 3-way set and its three
# 2-way subsets, so a goal the 14B narrowed to two platforms still gets the right two-option
# question. ``options`` includes ONLY the surfaces present in that key (built by filtering a
# canonical ordered option list), so the operator is never offered a platform the 14B did
# not flag. Each option's ``surface`` is a real, buildable surface (a member of
# :data:`_REAL_SURFACES`); the labels are product-level and novice-friendly.

#: The canonical, ordered platform options (label + the real surface each answer maps to).
#: An entry is OFFERED for a given candidate-set only when its surface is in that set.
_PLATFORM_OPTIONS: tuple[dict[str, str], ...] = (
    {"label": "On this computer", "surface": "desktop-gui"},
    {"label": "In a web browser", "surface": "web"},
    {"label": "On a phone", "surface": "mobile"},
)

#: The platform/device clarifying question (the system owns this text, NOT the 14B).
_PLATFORM_QUESTION = "Where will you mainly use this?"


def _platform_entry(candidate_surfaces: frozenset[str]) -> dict:
    """Build a decision-map entry for a platform candidate-set: the curated question + the
    canonical options FILTERED to just the surfaces in ``candidate_surfaces`` (so a 2-way
    fork offers two options, the 3-way offers three) — order preserved from
    :data:`_PLATFORM_OPTIONS`."""
    return {
        "question": _PLATFORM_QUESTION,
        "options": [
            dict(opt) for opt in _PLATFORM_OPTIONS if opt["surface"] in candidate_surfaces
        ],
    }


#: surface candidate-set (frozenset) -> ``{question, options:[{label, surface}]}``. v1: the
#: platform fork ONLY — the full {desktop-gui, web, mobile} set plus its three 2-way subsets.
#: A candidate-set with no entry here yields NO question (``resolve_clarifying_question``
#: returns ``None`` -> today's guess+confirm behavior), so an unmapped fork never blocks.
_CLARIFY_DECISION_MAP: dict[frozenset[str], dict] = {
    frozenset({"desktop-gui", "web", "mobile"}): _platform_entry(
        frozenset({"desktop-gui", "web", "mobile"})
    ),
    frozenset({"desktop-gui", "web"}): _platform_entry(frozenset({"desktop-gui", "web"})),
    frozenset({"desktop-gui", "mobile"}): _platform_entry(
        frozenset({"desktop-gui", "mobile"})
    ),
    frozenset({"web", "mobile"}): _platform_entry(frozenset({"web", "mobile"})),
}


def resolve_clarifying_question(build_plan: dict | None) -> dict | None:
    """Return ``{question, options}`` for the system to ask, or ``None`` (no question).

    PURE — no model, no I/O. Returns a question ONLY when BOTH hold:

      * ``build_plan["surface"] == "ambiguous"`` (the 14B FLAGGED a platform fork), AND
      * the ``candidates`` set has a curated :data:`_CLARIFY_DECISION_MAP` entry.

    In EVERY other case it returns ``None`` and the dispatch flow is byte-identical to
    today's guess+confirm (the gating contract): a ``None``/non-dict build_plan, a clear or
    ``unknown`` surface, an ``ambiguous`` surface whose candidate-set is not in the map, or a
    malformed/missing ``candidates`` list. The returned dict is a fresh deep-ish copy
    (options re-materialised) so a caller can never mutate the module-level map.

    Note: ``_parse_build_plan`` already guarantees an ``ambiguous`` surface carries >=2 valid
    real candidates (else it coerces to ``unknown``), so this function trusts that invariant
    but still reads defensively (an externally-constructed build_plan can't crash it)."""
    if not isinstance(build_plan, dict):
        return None
    if build_plan.get("surface") != SURFACE_AMBIGUOUS:
        return None
    raw = build_plan.get("candidates")
    if not isinstance(raw, list):
        return None
    # Only real surfaces form the key (defensive: an externally-built plan may not have been
    # through _parse_build_plan's filter). dedupe via the set itself.
    key = frozenset(c for c in raw if isinstance(c, str) and c in _REAL_SURFACES)
    entry = _CLARIFY_DECISION_MAP.get(key)
    if entry is None:
        return None
    return {
        "question": entry["question"],
        "options": [dict(opt) for opt in entry["options"]],
    }


def apply_clarification(build_plan: dict | None, chosen_surface: str) -> dict | None:
    """Return a NEW build_plan with ``surface = chosen_surface`` + ``candidates`` cleared.

    PURE — no model, no I/O. The operator's answer is VALIDATED against the build_plan's OWN
    ``candidates`` (the surfaces the 14B actually flagged): an off-list / unknown / garbage
    answer is IGNORED and the plan is returned UNCHANGED (a fresh copy), so the caller can
    re-ask or fall back to the un-refined plan — never a silent acceptance of a surface the
    14B did not offer. On a valid choice, ``surface`` becomes the chosen real surface and
    ``candidates`` is reset to ``[]`` (the fork is resolved — the signal is no longer
    ambiguous, so it now flows exactly like an ordinary clear-surface build_plan).

    A ``None``/non-dict build_plan returns ``None`` unchanged (nothing to refine)."""
    if not isinstance(build_plan, dict):
        return None
    raw = build_plan.get("candidates")
    valid = {c for c in raw if isinstance(c, str) and c in _REAL_SURFACES} if isinstance(raw, list) else set()
    refined = dict(build_plan)
    if chosen_surface not in valid:
        # Off-list answer: leave the plan as-is (still ambiguous) so the caller falls back /
        # re-asks. We return a COPY (never the same object) but with no semantic change.
        return refined
    refined["surface"] = chosen_surface
    refined["candidates"] = []
    return refined


# ---------------------------------------------------------------------------
# Criterion statuses (the honest, anti-rubber-stamp vocabulary)
# ---------------------------------------------------------------------------

STATUS_VERIFIED = "verified"      # the objective check actually ran and PASSED
STATUS_FAILED = "failed"          # the objective check ran and FAILED
STATUS_UNVERIFIED = "unverified"  # the check never ran (none/skip) — operator must verify
STATUS_EYEBALL = "eyeball"        # visual/human — only the operator can judge


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AcceptanceCriterion:
    """One plain-English DONE condition, tagged by how it is verified."""

    id: str
    text: str
    tier: str  # build | behavior | smoke | visual | human
    check: str = ""  # the concrete mechanical check, or what to look at by eye

    def to_dict(self) -> dict:
        return {"id": self.id, "text": self.text, "tier": self.tier, "check": self.check}

    @classmethod
    def from_dict(cls, d: dict) -> "AcceptanceCriterion":
        return cls(
            id=str(d.get("id", "")),
            text=str(d.get("text", "")),
            tier=str(d.get("tier", "")),
            check=str(d.get("check", "")),
        )


@dataclass(frozen=True)
class AcceptanceSpec:
    """The validated acceptance criteria for one goal (the operator approves this).

    ``assumptions`` are the 14B's PRODUCT-LEVEL reads of the parts the operator left
    underspecified — WHAT it should do / look / behave (e.g. "Assumed decimals are
    supported", "Assumed a normal resizable window"), NEVER technical/implementation
    choices (the system supplies language/framework/versions via AGENTS.md; the operator
    can't answer those). They are surfaced in the confirm-preview so the operator can
    catch a misread before approving a ~30-minute build — a display-only confirmation, not
    a question/answer turn. Default empty (a fully-specified goal yields none, and every
    existing spec / wire payload that omits the field reconstructs unchanged).

    ``build_plan`` is the 14B's COARSE product→platform classification (increment 1) —
    ``{surface, language_hint, complexity, components}`` from fixed enums (see
    :func:`_parse_build_plan`). It is the system's bridge from product intent to the
    deterministic fleet's scaffold/tech mapping. ``None`` when unclassified (the fail-closed
    default — preserves today's behavior byte-identically: no signal, the fleet's
    conservative no-seed path). It rides the spec across ``to_dict``/``from_dict`` (so it
    crosses the gateway IPC inside the spec dict with no transport change) and its goal-level
    fields are threaded onto every queue task object in :func:`compile_prompts`."""

    goal: str
    criteria: tuple[AcceptanceCriterion, ...] = ()
    assumptions: tuple[str, ...] = ()
    build_plan: dict | None = None
    #: UC-010 dispatch image-asset specs (SEAM A) — a tuple of validated
    #: ``{name, prompt, style, width, height, target_rel_path}`` dicts the 14B
    #: proposed for a VISUAL product (empty for non-visual / no-image goals). Rides
    #: ``to_dict``/``from_dict`` like ``build_plan``; threaded onto every task as
    #: ``asset_specs_json``; consumed AO-side pre-swap. Default ``()`` == today.
    asset_specs: tuple[dict, ...] = ()

    @property
    def objective(self) -> tuple[AcceptanceCriterion, ...]:
        """Criteria the fleet can (in principle) auto-check (build/behavior/smoke)."""
        return tuple(c for c in self.criteria if c.tier in OBJECTIVE_TIERS)

    @property
    def human(self) -> tuple[AcceptanceCriterion, ...]:
        """Criteria the operator must judge by eye (visual/human)."""
        return tuple(c for c in self.criteria if c.tier in HUMAN_TIERS)

    def to_dict(self) -> dict:
        return {
            "goal": self.goal,
            "criteria": [c.to_dict() for c in self.criteria],
            "assumptions": list(self.assumptions),
            "build_plan": self.build_plan,
            "asset_specs": [dict(a) for a in self.asset_specs],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AcceptanceSpec":
        raw = d.get("criteria", []) or []
        # assumptions: tolerate a missing key (older payloads); keep only real, non-blank
        # strings (a non-str item is DROPPED, never coerced — coercing None/42 would invent
        # a bogus "None"/"42" assumption the model never made).
        raw_assumptions = d.get("assumptions", []) or []
        assumptions = tuple(
            a.strip() for a in raw_assumptions if isinstance(a, str) and a.strip()
        )
        # build_plan: tolerate a missing key (older payloads -> None == today's behavior).
        # Defensive: ONLY a real dict survives the round-trip; any non-dict value (a forged
        # list/str/number, or a stray null) reconstructs as None (fail-closed — never a
        # half-built signal the fleet might act on).
        bp = d.get("build_plan")
        build_plan = bp if isinstance(bp, dict) else None
        # asset_specs: tolerate a missing key (older payloads -> () == today). Only
        # well-shaped dicts survive (_coerce_asset_specs re-validates path + style).
        return cls(
            goal=str(d.get("goal", "")),
            criteria=tuple(AcceptanceCriterion.from_dict(c) for c in raw),
            assumptions=assumptions,
            build_plan=build_plan,
            asset_specs=_coerce_asset_specs(d.get("asset_specs")),
        )


@dataclass(frozen=True)
class TaskReport:
    """A per-task report (``new-agent-task.ps1``) parsed into its objective signals.

    Defaults are fail-closed: an ABSENT objective signal is ``none`` ("the check did not
    run"), never silently treated as a pass.
    """

    tests: str = "none"   # pass | fail | none  (the TESTS: line)
    verify: str = "none"  # pass | fail | none  (the VERIFY: line)
    review: str = ""      # MERGE | FIX FIRST | UNCLEAR (the REVIEW VERDICT: line)
    result: str = ""      # the RESULT: line text


@dataclass(frozen=True)
class PlanResult:
    """Outcome of the PLAN step. ``tasks`` are COMPILED ``{repo, task, prompt}`` dicts
    (objective criteria already baked into the prompts), ready to enqueue on approval."""

    ok: bool
    tasks: list[dict] = field(default_factory=list)
    spec: AcceptanceSpec = field(default_factory=lambda: AcceptanceSpec(goal=""))
    fell_back: bool = False  # True if the task decomposition fell back to a single task
    message: str = ""


@dataclass(frozen=True)
class DecompositionOverride:
    """A pre-built, caller-authorized decomposition that BYPASSES the 14B decomposer in
    :func:`generate_plan` (the generic #752 F1 seam).

    ``tasks`` are decompose-shaped ``{repo, task, prompt[, depends_on][, contract]}`` dicts
    — the SAME shape :func:`~shared.fleet.decompose.decompose_request` emits — so they flow
    through the identical ``compile_prompts`` -> ``build_plan_raw`` -> ``validate_plan`` ruler
    and the caller earns NO exemption from validation (a bad override still degrades safely).
    ``job_oracle_code`` / ``job_oracle_path`` are an OPTIONAL pre-authored JOB-level acceptance
    oracle (#752 F2) that rides the final compiled task in place of the 14B-written one;
    ``job_oracle_path`` must be one of :data:`JOB_ORACLE_ALLOWED_PATHS` or the driver drops it
    (the pinned-path containment in :func:`extract_job_oracle`).

    Deliberately GENERIC: it carries no knowledge of WHO built the override or WHY. The M2
    capability battery builds diamond instances in :mod:`shared.fleet.battery_plans`; nothing
    battery-specific lives on this type or in ``generate_plan``."""

    tasks: list[dict]
    job_oracle_code: str = ""
    job_oracle_path: str = ""


# ---------------------------------------------------------------------------
# Criteria generation (the 14B proposes)
# ---------------------------------------------------------------------------

_CRITERIA_TEMPLATE = (
    "You are defining ACCEPTANCE CRITERIA for a software change request — the plain-"
    "English conditions that mean it is DONE and correct, each tagged by HOW it is "
    "checked. Return ONLY a JSON array (no prose) of at most {max_criteria} objects, each "
    '{{"text": "<plain-English condition the requester can understand>", '
    '"tier": "<build|behavior|smoke|visual|human>", '
    '"check": "<the concrete check: a test/assertion, or what to look at by eye>"}}. '
    "Tiers: build = it compiles/installs; behavior = a deterministic rule a unit test can "
    "assert (e.g. 2 + 3 shows 5; divide-by-zero shows an error); smoke = it launches "
    "without crashing; visual = how it looks; human = judgment/fit. Prefer concrete, "
    "testable criteria; include at least one build or behavior criterion.\n\nRequest:\n{idea}\n"
)

# ---------------------------------------------------------------------------
# Product-assumption generation (the 14B surfaces what it had to ASSUME)
# ---------------------------------------------------------------------------
#
# The operator gives DETAILED product prompts but CANNOT give technical direction, so the
# preview confirms the 14B's PRODUCT-LEVEL reads of the underspecified parts — WHAT it
# should do / look / behave — so a misread is caught before a ~30-minute build. This is
# DELIBERATELY a separate, second model call (not folded into the criteria call): it keeps
# the criteria JSON contract and its parse path byte-identical (the decompose eval and
# every criteria test are untouched), and lets the prompt be tightly product-scoped without
# the risk of the model blending implementation language into the criteria array. The
# prompt's load-bearing rule is PRODUCT-NOT-TECH: it asks ONLY for assumptions the operator
# could confirm/correct, and EXPLICITLY excludes language/framework/SDK/version/architecture
# (the system supplies those via AGENTS.md — the operator can't answer them). It emits an
# empty array when the goal was fully specified (no section then — backward-compatible).

#: Hard cap on product assumptions surfaced from one goal (the ~4-most-important rule).
DEFAULT_MAX_ASSUMPTIONS = 4

_ASSUMPTIONS_TEMPLATE = (
    "A non-technical person asked for a software change. Where their request did not spell "
    "something out, you had to ASSUME what they PROBABLY want. List the most important "
    "PRODUCT assumptions you are making about WHAT it should do, show, or how it should "
    "behave — the kind of thing they could read and say \"yes\" or \"no, I meant something "
    "else\" to (for example: \"Assumed decimals are supported\", \"Assumed no calculation "
    "history is kept\", \"Assumed a normal resizable window\"). \n"
    "STRICT RULES:\n"
    "- ONLY product/behaviour/appearance assumptions a non-developer can judge.\n"
    "- NEVER mention programming language, framework, library, SDK, version, file layout, "
    "or any technical/implementation choice — those are decided for you and the requester "
    "cannot answer them. If an assumption is technical, leave it out.\n"
    "- Each must be something the request genuinely left open; if the request already says "
    "it, it is NOT an assumption.\n"
    "- At most {max_assumptions}, most important first. If the request was fully specified "
    "and you assumed nothing the requester would care about, return an empty array.\n"
    "Return ONLY a JSON array of short strings (no prose, no keys).\n\nRequest:\n{idea}\n"
)

# Pull the first JSON array out of a model response (it may wrap it in prose/fences).
_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)

#: An assumption shorter than this (after strip) is vacuous and dropped.
_MIN_ASSUMPTION_LEN = 5


def _parse_assumptions(text: str, *, max_assumptions: int) -> tuple[str, ...]:
    """Best-effort parse of the model output into a tuple of product-assumption strings.

    Returns ``()`` on any failure or an empty/garbage emission (the fully-specified-goal
    case — no preview section then). Accepts the well-behaved shape (a JSON array of
    strings) and is defensive about the rest: a non-array, non-string items, vacuous/blank
    strings, and duplicates (normalized) are all dropped; the cap is enforced last. The
    model PROPOSES; this disposes — mirroring the criteria ruler's discipline so a sloppy
    emission can never put junk (or, worse, a stray implementation note that slipped the
    prompt's net) in front of the operator unfiltered."""
    if not text:
        return ()
    match = _JSON_ARRAY_RE.search(text)
    if not match:
        return ()
    try:
        data = json.loads(match.group(0))
    except (ValueError, TypeError):
        return ()
    if not isinstance(data, list):
        return ()
    out: list[str] = []
    seen: set[str] = set()
    for item in data:
        if not isinstance(item, str):
            continue
        a = item.strip()
        if len(a) < _MIN_ASSUMPTION_LEN:
            continue
        key = re.sub(r"\s+", " ", a.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(a)
        if len(out) >= max_assumptions:
            break
    return tuple(out)


# ---------------------------------------------------------------------------
# Build-signal generation (the 14B classifies product intent -> platform)
# ---------------------------------------------------------------------------
#
# A THIRD, separate model call (after decompose + criteria + assumptions) — separate for
# the SAME reason assumptions is: it keeps the criteria + assumptions JSON contracts byte-
# identical (their parse paths and every existing test untouched) and lets this prompt be
# tightly enum-scoped without the model bleeding a platform guess into the criteria array.
# The prompt asks the 14B to classify from PRODUCT intent ONLY (does it have a window? a web
# page? a phone screen? a terminal? is it just logic?) — deliberately lean, because an over-
# long prompt regresses a small model (the journal's standing lesson). Anything it can't
# classify -> ``surface: "unknown"`` (and the whole signal fails closed to today's behavior).

_BUILD_PLAN_TEMPLATE = (
    "Classify what KIND of software this product is, from the requester's intent ALONE. "
    "Return ONLY a JSON object (no prose), exactly:\n"
    '{{"surface": "<desktop-gui|web|mobile|command-line|automation|library|ambiguous|unknown>", '
    '"candidates": ["<surface>", ...], '
    '"language_hint": "<python|dotnet|node|cpp|powershell|null>", '
    '"complexity": "<simple|moderate|complex>", '
    '"components": [{{"name": "<short-name>", '
    '"kind": "<testable-logic|gui-shell|web-endpoint|cli-command|data|other>"}}]}}\n'
    "surface = where the product runs. Pick ONE if the goal NAMES or IMPLIES a platform: "
    "desktop-gui = a window/buttons app on THIS computer (desktop, windows app); web = a web "
    "page/site/browser app/web service; mobile = a phone app (iPhone, Android); command-line = "
    "a terminal tool or script with no window; automation = an OS/system script; library = "
    "reusable logic/code with no UI. If you truly cannot tell the KIND at all, use \"unknown\".\n"
    "EXCEPTION — \"ambiguous\": if the goal is a bare \"app\"/\"application\" with NO platform word "
    "(it does NOT say desktop, web/site/browser, phone/mobile, script, or command), it could run "
    "on this computer OR a browser OR a phone — set surface=\"ambiguous\" and "
    "candidates=[\"desktop-gui\", \"web\", \"mobile\"]. If ANY platform is named or implied, classify "
    "directly (a wrong specific guess the operator fixes in the preview beats over-asking). "
    "candidates = [] unless surface is \"ambiguous\".\n"
    "language_hint = a language ONLY if the request explicitly implies one (e.g. names it, or "
    "a PowerShell/admin task); otherwise null. Never guess.\n"
    "complexity = simple | moderate | complex (your honest size estimate).\n"
    "components = the few coarse parts (a calculator's logic core, a UI shell); [] is fine.\n"
    "Examples:\n"
    '"a desktop calculator with buttons" -> {{"surface":"desktop-gui","candidates":[]}}\n'
    '"a landing page for my bakery" -> {{"surface":"web","candidates":[]}}\n'
    '"an iPhone app to log workouts" -> {{"surface":"mobile","candidates":[]}}\n'
    '"a script that renames files" -> {{"surface":"command-line","candidates":[]}}\n'
    '"a todo app" -> {{"surface":"ambiguous","candidates":["desktop-gui","web","mobile"]}}\n'
    '"a chat app for messaging" -> {{"surface":"ambiguous","candidates":["desktop-gui","web","mobile"]}}\n'
    "\nRequest:\n{idea}\n"
)

# Pull the first JSON object out of a model response (it may wrap it in prose/fences).
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _first_json_object(text: str) -> str | None:
    """Extract the FIRST balanced-brace ``{...}`` object from ``text``.

    Robust to the stray trailing brace the small model occasionally appends (e.g.
    ``{"surface":"web","candidates":[]}}``) — the greedy ``\\{.*\\}`` regex would over-grab that
    into invalid JSON and lose the whole signal (fail-closed, but a needless miss). String-aware
    (ignores braces inside double-quoted strings) and depth-aware (handles the nested
    ``components`` objects). Returns the object substring, or ``None`` if there is no balanced
    object. Never raises."""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if esc:
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == '"':
            in_str = not in_str
        elif not in_str:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
    return None


def _validate_components(raw, *, max_components: int) -> list[dict]:
    """Validate the optional ``components`` list fail-closed: keep only ``{name, kind}``
    objects with a non-blank name; coerce an unknown/absent kind to ``other``; drop blanks /
    non-dicts; cap. Anything not a list -> ``[]`` (never raises)."""
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        kind = str(item.get("kind", "")).strip().lower()
        if kind not in KIND_VALUES:
            kind = KIND_DEFAULT
        out.append({"name": name, "kind": kind})
        if len(out) >= max_components:
            break
    return out


# ---------------------------------------------------------------------------
# Image-asset specs (UC-010 dispatch, SEAM A) — the 14B proposes, the ruler disposes
# ---------------------------------------------------------------------------
#
# A FOURTH separate 14B call (after decompose + criteria + assumptions + build-signal),
# separate for the SAME reason as the others: it keeps every prior JSON contract byte-
# identical. For a VISUAL product it lists the raster PICTURE assets the app should show
# (a hero image, a logo, a decorative illustration). The model supplies only name +
# subject + style; the DETERMINISTIC ruler owns the file slug, the dims, the in-repo path,
# the cap, the dedup, and the visual-surface gate. These specs are generated AO-side while
# the 14B is resident (SEAM A) BEFORE the model swap, written as plain PNGs into the target
# repo, and committed into the baseline every coder candidate inherits — deliberately
# OUTSIDE the born-encrypted /imagine gallery store (a build artifact, not operator gallery
# content; ADR-033 Am.3). DORMANT behind BLARAI_ENABLE_ASSET_GENERATION at the AO seam.

#: Image-asset styles a spec may request — 1:1 with the AO image_gen STYLE names
#: (illustration/cartoon = flat base-SDXL app art, the dispatch default; photoreal =
#: RealVisXL). An unknown style coerces to the default (never a hard failure).
ASSET_STYLE_VALUES: frozenset[str] = frozenset({"illustration", "cartoon", "photoreal"})
ASSET_STYLE_DEFAULT = "cartoon"

#: Hard cap on image assets generated for one goal — a deterministic GPU-cost + wire +
#: dispatch-timeout ceiling. 3 covers the common "a few product images" ask (#714) while
#: keeping total generation time under the dispatch interception timeout even on a tight box.
DEFAULT_MAX_ASSETS = 3

#: The surfaces that can DISPLAY a raster image (others never get assets).
_ASSET_VISUAL_SURFACES: frozenset[str] = frozenset({"web", "desktop-gui", "mobile"})

#: Generated-asset square edge (px). Base-1024² is the proven co-resident envelope
#: (ADR-033 §Memory Phase-0: 14B + SDXL ~26 GB, 5.3 GB headroom).
_ASSET_DEFAULT_EDGE = 1024
_ASSET_MIN_EDGE = 256
_ASSET_MAX_EDGE = 1024
#: An asset subject shorter than this (after strip) is vacuous and dropped.
_MIN_ASSET_SUBJECT_LEN = 3
#: Length cap on an asset filename slug (shared by :func:`_asset_slug` and the
#: #743 grammar schema, so the constraint and the truncation can never drift).
_ASSET_SLUG_MAX = 40


def _asset_slug(name: str) -> str:
    """A safe lowercase filename slug for a generated asset — a strict ``[a-z0-9]``
    allowlist (runs collapsed to ``-``, trimmed, length-capped). No dots, separators,
    or traversal. ``''`` (the spec is then dropped fail-closed) if nothing usable
    remains."""
    slug = re.sub(r"[^a-z0-9]+", "-", str(name).strip().lower()).strip("-")
    return slug[:_ASSET_SLUG_MAX]


def is_safe_asset_rel_path(rel: str) -> bool:
    """True iff ``rel`` is a RELATIVE, in-tree ``.png`` path with no traversal /
    absolute / UNC / drive component. Defense-in-depth: the ruler builds these from a
    strict slug, but a wire payload (``from_dict`` / the AO seam) is re-checked before
    anything is written to disk."""
    if not rel or not rel.endswith(".png"):
        return False
    if rel.startswith("/") or rel.startswith("\\") or ":" in rel:
        return False
    parts = rel.replace("\\", "/").split("/")
    return not any(p in ("", ".", "..") for p in parts)


def _asset_target_rel_path(slug: str, surface: str) -> str:
    """Deterministic in-repo path for a generated asset. Web assets go under
    ``public/assets/`` (the web scaffold serves static files from ``public/`` ONLY);
    every other surface under ``assets/``. Always a forward-slash relative path."""
    sub = "public/assets" if surface == "web" else "assets"
    return f"{sub}/{slug}.png"


_ASSET_SPECS_TEMPLATE = (
    "This product has a visual interface and may need one or more IMAGE assets "
    "(pictures, illustrations, or icons) generated for it — for example the hero "
    "picture a landing page shows, an app logo, or a decorative illustration. List "
    "the image assets this product should DISPLAY, from the requester's intent alone. "
    "Return ONLY a JSON array (no prose), each item exactly:\n"
    '{{"name": "<short-slug>", "subject": "<what the one picture shows>", '
    '"style": "<illustration|cartoon|photoreal>"}}\n'
    "name = a short lowercase slug used for the file (e.g. \"elephant\", \"hero\", "
    "\"logo\").\n"
    "subject = a plain, concrete description of the SINGLE subject the picture shows "
    "(no multi-scene lists). This becomes the image generation prompt.\n"
    "style = cartoon (playful, flat), illustration (clean flat-vector), or photoreal "
    "(realistic, photo-like). Prefer cartoon or illustration for app graphics; photoreal "
    "only if the request explicitly wants a realistic photo.\n"
    "Rules: ONLY assets the product actually displays; at most {max_assets}, most "
    "important first. If it needs NO generated pictures (a plain form, tool, or data "
    "app), return an empty array [].\n"
    "Examples:\n"
    '"a webpage with a cartoon elephant saying hello" -> '
    '[{{"name":"elephant","subject":"a friendly cartoon elephant waving hello",'
    '"style":"cartoon"}}]\n'
    '"a landing page for my bakery" -> '
    '[{{"name":"hero","subject":"a warm bakery storefront with fresh bread",'
    '"style":"illustration"}}]\n'
    '"a desktop calculator with buttons" -> []\n'
    "\nRequest:\n{idea}\n"
)


def _validate_asset_specs(text, *, surface: str, max_assets: int) -> tuple[dict, ...]:
    """Parse the model output into validated asset-spec dicts, fail-closed. The model
    supplies name/subject/style; the ruler owns the slug, dims, in-repo path, dedup (by
    target path), and cap. Returns ``()`` on any failure/garbage or a non-visual surface.
    Each survivor: ``{name, prompt, style, width, height, target_rel_path}`` (``prompt``
    holds the SUBJECT — the flat-vector style words are wrapped on at generation for
    illustration/cartoon, mirroring ``/illustrate``)."""
    if surface not in _ASSET_VISUAL_SURFACES:
        return ()
    if not isinstance(text, str) or not text:
        return ()
    match = _JSON_ARRAY_RE.search(text)
    if not match:
        return ()
    try:
        data = json.loads(match.group(0))
    except (ValueError, TypeError):
        return ()
    if not isinstance(data, list):
        return ()
    out: list[dict] = []
    seen: set[str] = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        slug = _asset_slug(item.get("name", ""))
        subject = str(item.get("prompt", item.get("subject", ""))).strip()
        if not slug or len(subject) < _MIN_ASSET_SUBJECT_LEN:
            continue
        style = str(item.get("style", "")).strip().lower()
        if style not in ASSET_STYLE_VALUES:
            style = ASSET_STYLE_DEFAULT
        rel = _asset_target_rel_path(slug, surface)
        if rel in seen:
            continue
        seen.add(rel)
        out.append({
            "name": slug,
            "prompt": subject,
            "style": style,
            "width": _ASSET_DEFAULT_EDGE,
            "height": _ASSET_DEFAULT_EDGE,
            "target_rel_path": rel,
        })
        if len(out) >= max_assets:
            break
    return tuple(out)


def _coerce_asset_specs(raw) -> tuple[dict, ...]:
    """Reconstruct ``asset_specs`` from a ``to_dict``/wire payload fail-closed: keep only
    well-shaped dicts (a safe slug name, a non-blank prompt, a known style, and a safe
    relative ``.png`` target path); clamp dims; drop everything malformed. Never re-runs
    the model ruler — the sender already disposed. ``()`` for a non-list."""
    if not isinstance(raw, list):
        return ()
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = _asset_slug(item.get("name", ""))
        prompt = str(item.get("prompt", "")).strip()
        style = str(item.get("style", "")).strip().lower()
        rel = str(item.get("target_rel_path", "")).strip().replace("\\", "/")
        if not name or not prompt or style not in ASSET_STYLE_VALUES:
            continue
        if not is_safe_asset_rel_path(rel):
            continue
        try:
            width = int(item.get("width", _ASSET_DEFAULT_EDGE))
            height = int(item.get("height", _ASSET_DEFAULT_EDGE))
        except (TypeError, ValueError):
            continue
        out.append({
            "name": name,
            "prompt": prompt,
            "style": style,
            "width": max(_ASSET_MIN_EDGE, min(_ASSET_MAX_EDGE, width)),
            "height": max(_ASSET_MIN_EDGE, min(_ASSET_MAX_EDGE, height)),
            "target_rel_path": rel,
        })
    return tuple(out)


def _asset_specs_from_plan(
    goal: str, build_plan: "dict | None", *,
    generate_fn: Callable[[str], str], max_assets: int,
    structured_generate_fn: "Callable[[str, str], str] | None" = None,
) -> tuple[dict, ...]:
    """The 14B proposes image-asset specs for a VISUAL product; the ruler disposes.
    Fail-closed to ``()`` on ANY failure OR a non-visual/unknown surface (no build_plan,
    a CLI/library/unknown surface -> no assets, ever). Non-blocking: an asset-spec failure
    never crashes the plan (the dispatch just generates no pictures). #743: when the W2
    grammar hook is provided the emission is tried schema-constrained FIRST, fail-soft
    to today's free-text path (grammar off/erroring ⇒ byte-identical behavior)."""
    surface = ""
    if isinstance(build_plan, dict):
        surface = str(build_plan.get("surface", "")).strip().lower()
    if surface not in _ASSET_VISUAL_SURFACES:
        return ()
    prompt = _ASSET_SPECS_TEMPLATE.format(max_assets=max_assets, idea=goal)
    raw = _grammar_first(
        prompt,
        structured_generate_fn=structured_generate_fn,
        schema=asset_specs_emission_json_schema(max_assets=max_assets),
        usable=_is_json_array_emission,
    )
    if raw is None:
        try:
            raw = generate_fn(prompt)
        except Exception:  # noqa: BLE001 — an asset-spec failure must not crash the plan
            return ()
    return _validate_asset_specs(raw, surface=surface, max_assets=max_assets)


def decode_asset_specs(tasks: list[dict]) -> list[dict]:
    """Read the run-scoped image-asset specs threaded onto the dispatch tasks (SEAM A).
    The specs are byte-identical across every task (stamped once by
    :func:`_thread_build_fields`), so read the first present ``asset_specs_json``, coerce
    it fail-closed, and dedup by ``target_rel_path``. Returns ``[]`` when no assets were
    planned (the common case) — the dispatch then generates nothing. This is the AO seam's
    single entry point for the spec list (all validation lives here)."""
    for t in tasks:
        raw = t.get("asset_specs_json")
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return []
        seen: set[str] = set()
        out: list[dict] = []
        for spec in _coerce_asset_specs(data):
            rel = spec["target_rel_path"]
            if rel in seen:
                continue
            seen.add(rel)
            out.append(spec)
        return out
    return []


def _validate_candidates(raw, *, max_candidates: int = DEFAULT_MAX_CANDIDATES) -> list[str]:
    """Validate the optional ``candidates`` list fail-closed (increment 4): keep only members
    of the REAL, buildable surface enum (:data:`_REAL_SURFACES`), normalised + deduped, order
    preserved, capped at ``max_candidates``. Drops ``unknown``/``ambiguous`` sentinels,
    unknown surfaces, non-strings, and garbage. Anything not a list -> ``[]`` (never raises).

    The 14B sometimes lists the candidates in mixed case / with stray whitespace, so each is
    lower-stripped before the enum check (the same normalisation ``surface`` gets)."""
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            continue
        s = item.strip().lower()
        if s not in _REAL_SURFACES or s in seen:
            continue
        seen.add(s)
        out.append(s)
        if len(out) >= max_candidates:
            break
    return out


def _parse_build_plan(
    text: str, *, max_components: int = DEFAULT_MAX_COMPONENTS
) -> dict | None:
    """Best-effort parse of the model output into a VALIDATED ``build_plan`` dict, or ``None``.

    The model PROPOSES; this DISPOSES (mirroring the criteria/assumptions rulers). Returns
    ``None`` only when there is no parseable JSON object at all (so the spec carries no
    build_plan and the dispatch is byte-identical to today). When an object IS found, it
    ALWAYS returns a fully-formed, enum-valid dict — every field is validated against its
    fixed enum and any bad/missing value is coerced to its fail-closed default:

      * ``surface``        -> ``unknown`` if absent / not in :data:`SURFACE_VALUES`.
      * ``language_hint``  -> ``None`` if absent / null / not in :data:`LANGUAGE_HINT_VALUES`.
      * ``complexity``     -> ``moderate`` if absent / not in :data:`COMPLEXITY_VALUES`.
      * ``components``     -> validated list (see :func:`_validate_components`); ``[]`` on any
                             non-list / garbage.

    Increment 4 — ``ambiguous`` surface + ``candidates`` (the clarifying-question signal):

      * ``candidates``     -> validated real-surface list (see :func:`_validate_candidates`).
      * **Fail-closed coupling:** an ``ambiguous`` surface is MEANINGLESS without a real fork,
        so if fewer than 2 valid candidates survive, the surface is coerced to ``unknown`` and
        candidates to ``[]`` (-> today's no-question, no-scaffold behavior). A NON-ambiguous
        surface forces candidates empty (a clear surface never carries a fork).
      * **Backward-compat shape:** the ``candidates`` key is present in the returned dict ONLY
        when the surface ends up ``ambiguous`` (i.e. the fork is real). For every clear /
        ``unknown`` surface the dict keeps its exact pre-increment-4 four-key shape
        (``surface``/``language_hint``/``complexity``/``components``) — byte-identical to
        today's output (every existing wire payload + exact-equality test is unaffected).

    NEVER raises. A ``surface == unknown`` result reproduces today's no-scaffold behavior."""
    if not text:
        return None
    obj = _first_json_object(text)
    if obj is None:
        return None
    try:
        data = json.loads(obj)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None

    surface = str(data.get("surface", "")).strip().lower()
    if surface not in SURFACE_VALUES:
        surface = SURFACE_UNKNOWN

    # language_hint: a real enum value, else None (a literal "null"/"none"/"" -> None too).
    lh_raw = data.get("language_hint")
    language_hint = str(lh_raw).strip().lower() if lh_raw is not None else ""
    language_hint = language_hint if language_hint in LANGUAGE_HINT_VALUES else None

    complexity = str(data.get("complexity", "")).strip().lower()
    if complexity not in COMPLEXITY_VALUES:
        complexity = COMPLEXITY_DEFAULT

    # candidates (increment 4) — only meaningful for an ``ambiguous`` surface. Validate
    # fail-closed, then enforce the coupling: an ambiguous flag with <2 real candidates is a
    # non-fork (the model hedged) -> coerce to ``unknown``; a non-ambiguous surface never
    # carries a fork -> candidates empty.
    candidates = _validate_candidates(data.get("candidates"))
    if surface == SURFACE_AMBIGUOUS and len(candidates) < 2:
        surface = SURFACE_UNKNOWN
        candidates = []
    elif surface != SURFACE_AMBIGUOUS:
        candidates = []

    plan: dict = {
        "surface": surface,
        "language_hint": language_hint,
        "complexity": complexity,
        "components": _validate_components(
            data.get("components"), max_components=max_components
        ),
    }
    # Keep the dict byte-identical to today's 4-key shape for every clear/unknown surface;
    # attach ``candidates`` ONLY when the fork is real (surface stayed ``ambiguous``). This
    # mirrors how the IPC layer added optional keys additively without disturbing old frames.
    if surface == SURFACE_AMBIGUOUS:
        plan["candidates"] = candidates
    return plan


def _parse_criteria(text: str, *, max_criteria: int) -> list[dict]:
    """Best-effort parse of the model output into ``[{text, tier, check}]``; ``[]`` on failure."""
    if not text:
        return []
    match = _JSON_ARRAY_RE.search(text)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except (ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    out: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "text": str(item.get("text", "")).strip(),
                "tier": str(item.get("tier", "")).strip().lower(),
                "check": str(item.get("check", "")).strip(),
            }
        )
        if len(out) >= max_criteria * 2:  # parse generously; the ruler caps
            break
    return out


# ---------------------------------------------------------------------------
# #743 — grammar-constrained emission for the REMAINING plan-time calls
# ---------------------------------------------------------------------------
#
# W2 (#740) grammar-constrained the decompose/plan JSON via the #718 xgrammar
# ``StructuredOutputConfig`` machinery (``decompose._generate_plan_json`` + an
# injected ``structured_generate_fn(prompt, json_schema_text)`` adapter). This
# section extends the SAME hook — not a second grammar pathway — to the other
# four structured 14B calls in the PLAN sequence: acceptance criteria, product
# assumptions, the build-signal (including the increment-4 ambiguous-platform
# fork), and image-asset specs. Each schema is derived from the SAME enums and
# caps its parser validates against (the module constants are the SSOT), so a
# constrained emission can never exceed what the ruler would truncate anyway.
#
# Fail-soft is absolute (the W2 contract): the grammar leg is tried FIRST and
# on ANY failure — no hook, hook raises, empty output, unusable output — the
# caller runs today's free-text ``generate_fn`` + parse + fallback path
# UNCHANGED. The grammar constraint may never introduce a new failure mode.
# The oracle calls (#690 per-task / W4 job-level) are NOT constrained here:
# they emit Python/JS CODE, not JSON — a grammar for them is a different class
# of constraint and out of #743's scope.


def _grammar_first(
    prompt: str,
    *,
    structured_generate_fn: "Callable[[str, str], str] | None",
    schema: dict,
    usable: Callable[[str], bool],
) -> "str | None":
    """One OPTIONAL grammar-constrained emission (the W2/#718 hook, #743).

    Tries *structured_generate_fn* FIRST, called as ``(prompt, json_schema_text)``.
    Returns the raw text ONLY when the hook exists, did not raise, and produced
    output *usable* accepts; ``None`` in EVERY other case — the caller then runs
    today's free-text path unchanged (mirrors ``decompose._generate_plan_json``)."""
    if structured_generate_fn is None:
        return None
    try:
        raw = structured_generate_fn(prompt, json.dumps(schema))
    except Exception:  # noqa: BLE001 — the hook must never add a failure mode
        return None
    if raw and usable(raw):
        return raw
    return None


def _is_json_array_emission(text: str) -> bool:
    """True iff *text* carries a parseable JSON array — INCLUDING an empty one.

    The assumptions and asset-specs calls treat ``[]`` as a meaningful answer
    ("nothing to list" — the fully-specified goal / the no-pictures product), so a
    grammar-constrained ``[]`` is accepted rather than triggering a redundant
    free-text retry; garbage still falls back to today's path."""
    if not isinstance(text, str) or not text:
        return False
    match = _JSON_ARRAY_RE.search(text)
    if not match:
        return False
    try:
        return isinstance(json.loads(match.group(0)), list)
    except (ValueError, TypeError):
        return False


def criteria_emission_json_schema(*, max_criteria: int = DEFAULT_MAX_CRITERIA) -> dict:
    """The JSON schema for a grammar-constrained CRITERIA emission — the same
    ``{text, tier, check}`` shape :func:`_parse_criteria` expects, with ``tier``
    pinned to the five-tier enum and the vacuous floor applied at the source.
    ``minItems: 1`` because an empty criteria array is never useful (the ruler
    injects the build floor regardless) — an empty emission falls back."""
    return {
        "type": "array",
        "minItems": 1,
        "maxItems": max_criteria,
        "items": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "minLength": _MIN_CRITERION_LEN},
                "tier": {"enum": sorted(ALL_TIERS)},
                "check": {"type": "string"},
            },
            "required": ["text", "tier"],
            "additionalProperties": False,
        },
    }


def assumptions_emission_json_schema(
    *, max_assumptions: int = DEFAULT_MAX_ASSUMPTIONS
) -> dict:
    """The JSON schema for a grammar-constrained ASSUMPTIONS emission — a flat
    array of short strings (:func:`_parse_assumptions`'s shape). ``[]`` is a
    VALID constrained answer (the fully-specified goal)."""
    return {
        "type": "array",
        "maxItems": max_assumptions,
        "items": {"type": "string", "minLength": _MIN_ASSUMPTION_LEN},
    }


def build_plan_emission_json_schema(
    *, max_components: int = DEFAULT_MAX_COMPONENTS
) -> dict:
    """The JSON schema for a grammar-constrained BUILD-SIGNAL emission — every
    field pinned to the SAME enums :func:`_parse_build_plan` validates against
    (:data:`SURFACE_VALUES` — including the ``ambiguous`` platform-fork sentinel —
    :data:`LANGUAGE_HINT_VALUES` + ``null``, :data:`COMPLEXITY_VALUES`,
    :data:`KIND_VALUES`), with ``candidates`` constrained to the REAL buildable
    surfaces only. The ambiguous-with-<2-candidates coupling stays the PARSER's
    job (a conditional schema is not expressible in the flat shape); the grammar
    guarantees enum validity, the ruler still disposes."""
    return {
        "type": "object",
        "properties": {
            "surface": {"enum": sorted(SURFACE_VALUES)},
            "candidates": {
                "type": "array",
                "items": {"enum": sorted(_REAL_SURFACES)},
                "maxItems": DEFAULT_MAX_CANDIDATES,
            },
            # JSON-Schema enum members may be null — the "no explicit language" answer.
            "language_hint": {"enum": sorted(LANGUAGE_HINT_VALUES) + [None]},
            "complexity": {"enum": sorted(COMPLEXITY_VALUES)},
            "components": {
                "type": "array",
                "maxItems": max_components,
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "minLength": 1},
                        "kind": {"enum": sorted(KIND_VALUES)},
                    },
                    "required": ["name", "kind"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["surface"],
        "additionalProperties": False,
    }


def asset_specs_emission_json_schema(*, max_assets: int = DEFAULT_MAX_ASSETS) -> dict:
    """The JSON schema for a grammar-constrained ASSET-SPECS emission — the
    ``{name, subject, style}`` shape :func:`_validate_asset_specs` expects, with
    ``style`` pinned to :data:`ASSET_STYLE_VALUES` and ``name`` capped at the
    :func:`_asset_slug` length bound. ``[]`` is a VALID constrained answer (the
    product needs no generated pictures)."""
    return {
        "type": "array",
        "maxItems": max_assets,
        "items": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "minLength": 1, "maxLength": _ASSET_SLUG_MAX},
                "subject": {"type": "string", "minLength": _MIN_ASSET_SUBJECT_LEN},
                "style": {"enum": sorted(ASSET_STYLE_VALUES)},
            },
            "required": ["name", "subject", "style"],
            "additionalProperties": False,
        },
    }


# ---------------------------------------------------------------------------
# The deterministic ruler (DISPOSES — never the model)
# ---------------------------------------------------------------------------


def rule_spec(
    goal: str, candidates: list[dict], *, max_criteria: int = DEFAULT_MAX_CRITERIA
) -> AcceptanceSpec:
    """Deterministic disposal: drop vacuous/malformed, dedupe, cap, guarantee >=1 objective.

    The model PROPOSES; this DISPOSES. A candidate is dropped if its text is shorter than
    the vacuous floor or its tier is not one of the five. Duplicates (by normalized text)
    collapse. Order is preserved; ids are assigned ``c1..cN`` at the end. If no valid
    OBJECTIVE (build/behavior/smoke) criterion survives, a default BUILD criterion is
    injected so a dispatch is NEVER gated by nothing (the never-zero-gating discipline,
    mirroring decompose's never-zero-work).
    """
    accepted: list[tuple[str, str, str]] = []  # (text, tier, check)
    seen: set[str] = set()
    for cand in candidates:
        text = str(cand.get("text", "")).strip()
        tier = str(cand.get("tier", "")).strip().lower()
        check = str(cand.get("check", "")).strip()
        if len(text) < _MIN_CRITERION_LEN or tier not in ALL_TIERS:
            continue
        key = re.sub(r"\s+", " ", text.lower())
        if key in seen:
            continue
        seen.add(key)
        accepted.append((text, tier, check))
        if len(accepted) >= max_criteria:
            break

    if not any(tier in OBJECTIVE_TIERS for _, tier, _ in accepted):
        accepted.insert(
            0,
            (
                "The project builds without errors.",
                TIER_BUILD,
                "The fleet's build step (compile / dotnet build / npm run build) succeeds.",
            ),
        )

    criteria = tuple(
        AcceptanceCriterion(id=f"c{i + 1}", text=t, tier=tr, check=ck)
        for i, (t, tr, ck) in enumerate(accepted)
    )
    return AcceptanceSpec(goal=goal.strip(), criteria=criteria)


def _ensure_test_floor(spec: AcceptanceSpec) -> AcceptanceSpec:
    """Append a default SMOKE criterion so a dispatch whose decomposer collapsed the
    model's test tasks still gets acceptance tests downstream — the
    "never end at zero tests" floor.

    Decompose emits feature tasks and the tests are added downstream (compile_prompts
    carries them from the behavior/smoke criteria — folded into the lone feature task, or a
    dedicated final task when there are >=2). So when the right-sizing ruler dropped the
    model's structural test tasks (it WANTED tests) but criteria-gen produced no
    behavior/smoke criterion, the goal would otherwise reach the fleet with ZERO tests.
    This floor closes that gap. It mirrors ``rule_spec``'s build floor: deterministic,
    id-continued, and HONEST — a smoke criterion renders UNVERIFIED on an ecosystem the
    fleet cannot test (.NET), never a false pass.
    """
    smoke = AcceptanceCriterion(
        id=f"c{len(spec.criteria) + 1}",
        text="The project runs without crashing.",
        tier=TIER_SMOKE,
        check="A basic smoke test exercises the main entry point without error.",
    )
    return AcceptanceSpec(
        goal=spec.goal,
        criteria=spec.criteria + (smoke,),
        assumptions=spec.assumptions,   # carry the product assumptions across the copy
        build_plan=spec.build_plan,     # carry the build-signal across the copy (#674)
    )


# ---------------------------------------------------------------------------
# Compile criteria into task prompts (fleet queue schema unchanged)
# ---------------------------------------------------------------------------


def _task_build_fields(build_plan: dict | None) -> dict:
    """The goal-level build-signal fields copied onto EVERY queue task object (#674).

    The fleet reads per-task data from the queue task object (it already reads
    ``$t.complexity``); the LA's fleet lane adds ``$t.surface``. So the three goal-level
    values must ride on each task dict that reaches the queue write. Fail-closed: a missing
    ``build_plan`` (no parseable 14B signal) or any missing field yields the safe defaults —
    ``surface=unknown`` (the fleet's conservative no-seed path == today's behavior),
    ``language_hint=None`` (never guess a language), ``complexity=moderate`` (a value the
    fleet's ValidateSet already accepts). ``build_plan`` has already been enum-validated by
    :func:`_parse_build_plan`, so the values here are trusted; this only supplies defaults
    for the None/absent case. Returns a fresh dict (never shares state across tasks).

    Increment 4 defence-in-depth: an UNRESOLVED ``ambiguous`` surface must never reach the
    fleet (the fleet's BuildProfile map knows nothing about the sentinel). The normal flow
    resolves the fork via :func:`apply_clarification` BEFORE compiling, so ``surface`` is a
    real value here; but if an ambiguous plan ever slips through (e.g. the operator's answer
    was off-list and the flow fell back to the un-refined plan), it is coerced to ``unknown``
    — the fleet's safe no-seed path == today's behavior — never sent as ``ambiguous``."""
    bp = build_plan if isinstance(build_plan, dict) else {}
    surface = bp.get("surface")
    if surface not in SURFACE_VALUES or surface == SURFACE_AMBIGUOUS:
        surface = SURFACE_UNKNOWN
    language_hint = bp.get("language_hint")
    if language_hint not in LANGUAGE_HINT_VALUES:
        language_hint = None
    complexity = bp.get("complexity")
    if complexity not in COMPLEXITY_VALUES:
        complexity = COMPLEXITY_DEFAULT
    return {
        "surface": surface,
        "language_hint": language_hint,
        "complexity": complexity,
    }


def _thread_build_fields(tasks: list[dict], spec: "AcceptanceSpec") -> list[dict]:
    """Stamp the goal-level build-signal (:func:`_task_build_fields`) AND the VLM-design-loop
    fields onto every task dict IN PLACE and return the same list. One copy per task (so two
    tasks never alias the same signal dict). Applied at the single exit of
    :func:`compile_prompts` so EVERY shape (folded-single, dedicated-final, no-test passthrough)
    carries them.

    VLM-design-loop fields (#666/#670 Phase 3, DORMANT until the fleet's post-merge critique
    hook reads them): ``goal`` (the plain-English product goal) and ``visual_criteria_json``
    (a JSON array of the visual-tier criterion texts, from :func:`visual_criteria_texts`). The
    fleet's ``critique-loop.ps1`` passes these to ``python -m shared.fleet.critique``; an empty
    ``"[]"`` (no visual criteria) means the fleet skips the critique entirely. No live caller
    reads them yet — this only threads the data onto the queue task object so the loop CAN be
    wired without changing the fleet's bare ``{repo, task, prompt}`` schema."""
    build_plan = spec.build_plan
    loop_fields = {
        "goal": spec.goal,
        "visual_criteria_json": json.dumps(visual_criteria_texts(spec)),
    }
    # UC-010 SEAM A: thread the image-asset specs ONLY when non-empty, so a goal with no
    # generated pictures produces task dicts byte-identical to today (the AO seam treats an
    # absent key as "no assets"). Stamped once here, identical across every task.
    if spec.asset_specs:
        loop_fields["asset_specs_json"] = json.dumps([dict(a) for a in spec.asset_specs])
    for t in tasks:
        t.update(_task_build_fields(build_plan))
        t.update(loop_fields)
    return tasks


#: Import roots an oracle uses that are NOT part of the coder's public-API contract — the test
#: runner's own deps (pytest / hypothesis) and the standard library. Everything an oracle imports
#: OTHER than these is a first-party symbol the coder must actually provide, so it is surfaced to
#: the coder as a hard requirement (#752 F3). Not exhaustive by design: an unlisted stdlib module
#: only ever ADDS a redundant "provide X" line, never drops a real first-party symbol — fail-soft
#: toward over-stating the contract, never under-stating it.
_ORACLE_NON_API_ROOTS: frozenset[str] = frozenset(
    {
        "pytest", "hypothesis", "__future__", "sys", "os", "re", "math", "json", "typing",
        "collections", "itertools", "functools", "datetime", "unittest", "random", "string",
        "decimal", "fractions", "pathlib", "dataclasses", "enum", "abc", "contextlib", "io",
        "time", "warnings", "copy", "operator", "statistics", "textwrap", "argparse", "csv",
        "hashlib", "uuid", "types", "numbers", "heapq", "bisect", "array", "queue", "struct",
        "subprocess", "tempfile", "shutil", "glob", "logging", "inspect", "importlib",
    }
)


def _oracle_import_contract(oracle_code: str) -> list[str]:
    """The concrete first-party symbols a pytest oracle IMPORTS — the exact importable names the
    coder must provide so the protected acceptance file can be COLLECTED (#752 F3 / B2's failure:
    a missing or renamed one is a ``ModuleNotFoundError`` at pytest collection, so the oracle
    never runs and the job scores RED on import-plumbing, not the coder's logic).

    ``from app.core import summarize, mean`` -> ``["app.core.summarize", "app.core.mean"]``;
    ``import app.core`` -> ``["app.core"]``. Test-runner deps and the standard library
    (:data:`_ORACLE_NON_API_ROOTS`) are excluded; RELATIVE imports (``from . import x``) live
    inside ``tests/`` and are not a public module, so they are skipped. Order-preserving and
    de-duplicated. Fail-soft: anything that will not ``ast.parse`` returns ``[]`` (the generic
    "create exactly the module(s) it imports" guidance still stands)."""
    if not oracle_code:
        return []
    try:
        tree = ast.parse(oracle_code)
    except (SyntaxError, ValueError):  # ValueError: source with NULs etc.
        return []
    out: list[str] = []
    seen: set[str] = set()

    def _add(name: str) -> None:
        if name and name not in seen:
            seen.add(name)
            out.append(name)

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:  # relative import (``from . import x``): within tests/, not public
                continue
            module = node.module or ""
            if not module or module.split(".", 1)[0] in _ORACLE_NON_API_ROOTS:
                continue
            for alias in node.names:
                # ``from app.core import *`` — no concrete symbol; fall back to the module name
                _add(module if alias.name == "*" else f"{module}.{alias.name}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".", 1)[0] not in _ORACLE_NON_API_ROOTS:
                    _add(alias.name)
    return out


def compile_prompts(
    tasks: list[dict], spec: AcceptanceSpec, *, oracle_code: str = ""
) -> list[dict]:
    """Route the behavior/smoke criteria to the coder — FOLDED into the lone feature task
    when there is exactly one, else a dedicated FINAL ``acceptance-tests`` task.

    Two shapes, for right-sizing (#670 Problem 3 — the live-shakedown over-split fix):

    * **One feature task** -> fold the test block into THAT task's prompt. A single-feature
      goal (``is_palindrome``) runs in ONE worktree with ONE auto-merge, so a separate
      ``acceptance-tests`` task buys nothing and costs a second fleet task that spins its
      own worktree + model-swap cycle WITHOUT the implementation in it (the live shakedown
      had that sibling run ~24 min failing). Folding makes the coder write the function and
      its tests together, where the code actually is.
    * **Two or more feature tasks** -> ONE dedicated final task, run last (after the feature
      tasks auto-merge). Baking the SAME tests into every task would write
      duplicate/conflicting test files across the per-task merges; one final task means only
      ONE task writes the tests, against the COMPLETE, already-merged code.

    Either way the SAME test block is used — including the anti-mirror header VERBATIM
    ("assert each criterion's REQUIRED behavior ... NOT whatever the code currently does"),
    kept as a clearly-delimited section so the coder does not write happy-path tests that
    merely mirror its own fresh code. This is also the only way criteria reach the 30B
    without changing the fleet's bare ``{repo, task, prompt}`` queue schema. BUILD needs no
    test (the fleet always builds); visual/human are the operator's and never sent to the
    coder. No behavior/smoke criteria (or no tasks) -> the feature tasks unchanged. Returns
    NEW task dicts (the inputs are not mutated).

    Every returned task dict also carries the goal-level build-signal fields
    (``surface``/``complexity``/``language_hint``, via :func:`_thread_build_fields`) so they
    reach the fleet queue write (#674) — stamped at the SINGLE exit so all three shapes
    (no-test passthrough, folded-single, dedicated-final) carry them uniformly.

    #690 — the shared ORACLE: when ``oracle_code`` is supplied (a 14B-written spec-derived
    pytest file, python single-feature only — see :func:`generate_acceptance_oracle`), the lone
    feature task is told to CODE AGAINST that seeded, protected oracle instead of writing its
    own tests, and carries ``acceptance_test_code`` + ``acceptance_test_path`` so the fleet can
    seed it into every best-of-N candidate and restore it before the gate (every candidate is
    then judged by the byte-identical scorecard). Empty ``oracle_code`` (every existing caller,
    and any non-python/multi-feature shape) is byte-identical to today's behavior.
    """
    feature = [dict(t) for t in tasks]
    test_criteria = [c for c in spec.criteria if c.tier in TEST_TIERS]
    # Only ecosystems whose tests actually RUN in the fleet gate (python/node) get the "write
    # automated tests" instruction below. A build-only ecosystem (.NET / cpp / powershell) has no
    # offline test runner, so mandating tests there is counterproductive: the coder cannot run them
    # AND spawns a separate test project that breaks the bare `dotnet build` gate (the #687 #8
    # review-probe park -- a C# Fibonacci app told to "write tests with Hypothesis (`from hypothesis
    # import ...`)"). An UNKNOWN language (None) keeps the python/node default (backward-compatible).
    language_hint = spec.build_plan.get("language_hint") if getattr(spec, "build_plan", None) else None
    tests_run_in_gate = (language_hint is None) or (language_hint in BEHAVIOR_GATED_ECOSYSTEMS)
    if not test_criteria or not feature or not tests_run_in_gate:
        return _thread_build_fields(feature, spec)

    # #690 — the shared, spec-derived ORACLE. When the 14B wrote one at PLAN time (python,
    # single feature — the case where best-of-N + self-written tests collide worst), the coder
    # CODES AGAINST the seeded, protected oracle instead of writing its own tests, so every
    # best-of-N candidate is judged by the byte-identical scorecard (the gate compares like for
    # like). The fleet seeds the oracle into the worktree at ACCEPTANCE_ORACLE_PATH, commits it
    # into the candidate baseline, and RESTORES it before grading — so a candidate editing or
    # deleting the test cannot help. >=2 features keep today's dedicated acceptance task (the
    # oracle is single-feature MVP); a junk/absent oracle is '' and never reaches here.
    if oracle_code and len(feature) == 1:
        only = feature[0]
        # #752 F3 — close the import-plumbing loop: parse the CONCRETE symbols the protected
        # oracle imports and state them to the coder as a HARD public-API contract, so the
        # coder's modules match exactly what the acceptance file collects. Without this the
        # oracle could import a module the coder never created -> ModuleNotFoundError at pytest
        # collection -> the oracle never runs and the job scores RED on plumbing, not logic
        # (B2's failure). The template already pins the oracle to `app`; this holds even if the
        # oracle's names drift. Fail-soft: no parseable first-party import -> generic guidance.
        contract = _oracle_import_contract(oracle_code)
        contract_line = ""
        if contract:
            joined = ", ".join(f"`{s}`" for s in contract)
            all_under_app = all(s == "app" or s.startswith("app.") for s in contract)
            where = (
                " These belong in the project's EXISTING `app` package — extend `app/core.py` "
                "or add an `app/<name>.py` submodule; do NOT start a second top-level package."
                if all_under_app
                else ""
            )
            contract_line = (
                "\nYour public API MUST provide EXACTLY these importable names, because the "
                f"protected acceptance file imports them: {joined}. If any is missing or renamed, "
                "pytest cannot even collect the tests and the whole attempt scores zero on an "
                f"import error, not on your logic.{where}"
            )
        oracle_block = (
            "--- Acceptance tests (DO NOT EDIT) ---\n"
            f"A protected acceptance-test file `{ACCEPTANCE_ORACLE_PATH}` is ALREADY in this "
            "project. It IS the specification for this task. Make EVERY test in it pass: create "
            "exactly the module(s) and function(s) it imports, with the behavior its assertions "
            "require. Do NOT edit, weaken, delete, rename, or skip any test in that file — it is "
            "restored to the original before grading, so changing it cannot help and only wastes "
            "the attempt. You may add new code files freely; you may NOT modify that test file."
            + contract_line
        )
        only["prompt"] = f"{only['prompt']}\n\n{oracle_block}"
        only["acceptance_test_code"] = oracle_code
        only["acceptance_test_path"] = ACCEPTANCE_ORACLE_PATH
        return _thread_build_fields(feature, spec)

    lines = [
        "Write automated tests (and make them pass) for the acceptance criteria below, "
        "covering the code already in this project. Assert each criterion's REQUIRED "
        "behavior — what the criterion SAYS must be true — NOT whatever the code "
        "currently does; a test that merely mirrors the present implementation proves "
        "nothing (if the code is wrong, a mirror test is wrong with it). Where a criterion "
        "states a general rule or invariant that must hold for ALL valid inputs (not just one "
        "example), ALSO write a PROPERTY-BASED test with Hypothesis "
        "(`from hypothesis import given, strategies as st`) asserting that invariant over many "
        "auto-generated inputs — a property is derived from the spec, so it cannot mirror the "
        "implementation and it catches edge cases an example test misses (Python projects only; "
        "the test runner has hypothesis available). Do not weaken or delete existing passing "
        "tests, and change feature code only as needed to make these tests pass. Each criterion:",
    ]
    for c in test_criteria:
        suffix = f"  (check: {c.check})" if c.check else ""
        lines.append(f"- [{c.tier}] {c.text}{suffix}")
    test_block = "\n".join(lines)

    if len(feature) == 1:
        # Single feature task -> fold the tests in (no doomed second worktree). The header
        # is preserved verbatim as a delimited section so the anti-mirror discipline holds.
        only = feature[0]
        only["prompt"] = f"{only['prompt']}\n\n--- Acceptance tests ---\n{test_block}"
        return _thread_build_fields(feature, spec)

    acceptance_task = {
        "repo": feature[-1].get("repo", ""),
        "task": ACCEPTANCE_TASK_SLUG,
        "prompt": test_block,
    }
    return _thread_build_fields(feature + [acceptance_task], spec)


# ---------------------------------------------------------------------------
# Read the fleet's results back HONESTLY
# ---------------------------------------------------------------------------


def parse_task_report(text: str) -> TaskReport:
    """Parse a per-task report (``new-agent-task.ps1``) into TESTS/VERIFY/REVIEW/RESULT.

    The report has lines like ``TESTS: pass``, ``VERIFY: none``,
    ``REVIEW VERDICT: MERGE``, ``RESULT: MERGED ...``. Missing objective lines default to
    ``none`` (fail-closed: an absent signal is "did not run", never a pass).
    """
    tests = "none"
    verify = "none"
    review = ""
    result = ""
    for raw in (text or "").splitlines():
        line = raw.strip()
        low = line.lower()
        if low.startswith("tests:"):
            tests = line.split(":", 1)[1].strip().lower() or "none"
        elif low.startswith("verify:"):
            verify = line.split(":", 1)[1].strip().lower() or "none"
        elif low.startswith("review verdict:"):
            review = line.split(":", 1)[1].strip()
        elif low.startswith("result:"):
            result = line.split(":", 1)[1].strip()
    return TaskReport(tests=tests, verify=verify, review=review, result=result)


def criterion_status(
    criterion: AcceptanceCriterion, report: TaskReport | None
) -> str:
    """Map a criterion + the fleet's report to an HONEST status (the anti-rubber-stamp core).

    An objective check that NEVER RAN (``none``/``skip`` — e.g. a .NET behavior test the
    fleet has no ``dotnet test`` to run, or pytest not importable) is UNVERIFIED, never
    ``verified``. ``verified`` is returned ONLY on an actual ``pass``. Visual/human
    criteria are always the operator's eyeball; a missing report makes every objective
    criterion UNVERIFIED.
    """
    if criterion.tier in HUMAN_TIERS:
        return STATUS_EYEBALL
    if report is None:
        return STATUS_UNVERIFIED
    signal = report.verify if criterion.tier == TIER_BUILD else report.tests
    if signal == "pass":
        return STATUS_VERIFIED
    if signal == "fail":
        return STATUS_FAILED
    return STATUS_UNVERIFIED  # none / skip / anything-not-pass -> NEVER a green check


def _aggregate_reports(task_reports: list[TaskReport]) -> TaskReport | None:
    """Combine a run's per-task reports into one objective signal per dimension.

    Conservative (fail dominates): if ANY task failed a dimension it shows ``fail``; else
    if any passed it shows ``pass``; else ``none``. A failure is never hidden behind a
    later pass.
    """
    if not task_reports:
        return None

    def combine(values: list[str]) -> str:
        if "fail" in values:
            return "fail"
        if "pass" in values:
            return "pass"
        return "none"

    return TaskReport(
        tests=combine([r.tests for r in task_reports]),
        verify=combine([r.verify for r in task_reports]),
        review="; ".join(r.review for r in task_reports if r.review),
        result="; ".join(r.result for r in task_reports if r.result),
    )


# ---------------------------------------------------------------------------
# Ecosystem + run-command detection (for the honest caveat + open-the-app line)
# ---------------------------------------------------------------------------


def detect_ecosystem(repo: Path) -> str:
    """Best-effort ecosystem sniff: ``node`` | ``python`` | ``dotnet`` | ``unknown``.

    By well-known marker files, in a fixed precedence (node, python, dotnet). Only the
    up-front coverage caveat and the run command depend on this — never a gate.
    """
    try:
        repo = Path(repo)
        if (repo / "package.json").is_file():
            return "node"
        if (
            (repo / "pyproject.toml").is_file()
            or (repo / "setup.py").is_file()
            or any(repo.glob("*.py"))
        ):
            return "python"
        if (
            any(repo.glob("*.sln"))
            or any(repo.glob("*.csproj"))
            or any(repo.glob("*/*.csproj"))
        ):
            return "dotnet"
    except OSError:
        pass
    return "unknown"


def _package_scripts(repo: Path) -> dict:
    try:
        data = json.loads((repo / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    scripts = data.get("scripts", {}) if isinstance(data, dict) else {}
    return scripts if isinstance(scripts, dict) else {}


def detect_run_command(repo: Path) -> str:
    """The single, dead-simplest command to open/run the built app (for the REPORT).

    One obvious step beats a fragile one-tap auto-launch across arbitrary project types
    (and avoids grabbing the operator's screen). Falls back to "open the folder".
    """
    repo = Path(repo)
    eco = detect_ecosystem(repo)
    if eco == "node":
        scripts = _package_scripts(repo)
        if "start" in scripts:
            return "npm start"
        if "dev" in scripts:
            return "npm run dev"
        return "npm start"
    if eco == "dotnet":
        return "dotnet run"
    if eco == "python":
        for entry in ("main.py", "app.py", "__main__.py"):
            if (repo / entry).is_file():
                return f"python {entry}"
        return f"python -m {repo.name}"
    return f"open the folder: {repo}"


# ---------------------------------------------------------------------------
# Renders (operator-facing, plain English, no symbols a non-dev must decode)
# ---------------------------------------------------------------------------

_STATUS_LABEL = {
    STATUS_VERIFIED: "PASS",
    STATUS_FAILED: "FAIL",
    STATUS_UNVERIFIED: "NOT AUTO-CHECKED — verify yourself",
    STATUS_EYEBALL: "your eyeball",
}


def _humanize_task_name(task: dict) -> str:
    """Turn a task's slug (the ``task`` key, e.g. ``add-calc``) into a display name
    (``Add calc``). Hyphens/underscores -> spaces, first letter capitalized. The full
    prompt is never surfaced — only the shape/name."""
    slug = str(task.get("task", "")).replace("-", " ").replace("_", " ").strip()
    return slug[:1].upper() + slug[1:] if slug else slug


def _friendly_surface(spec: AcceptanceSpec) -> str | None:
    """The operator-facing 'Building this as: <X>' phrase for the preview, or ``None`` to
    OMIT the line (#674). Driven by ``spec.build_plan.surface`` through :data:`_SURFACE_FRIENDLY`.

    Fail-closed + display-only: no build_plan, a non-dict build_plan, a missing/``unknown``
    surface, or any surface absent from the friendly map -> ``None`` (no line — never a guess
    in front of the operator). The system never invents a platform it could not classify."""
    bp = spec.build_plan
    if not isinstance(bp, dict):
        return None
    surface = bp.get("surface")
    if not isinstance(surface, str):
        return None
    return _SURFACE_FRIENDLY.get(surface)


def visual_criteria_texts(spec: "AcceptanceSpec") -> list[str]:
    """Return the ``.text`` of every visual-tier criterion in ``spec``.

    This is the list the VLM design loop passes to
    ``shared.fleet.critique.build_critique_prompt`` as the ``visual_criteria``
    argument. It filters the spec's ``.human`` criteria down to the
    ``TIER_VISUAL`` subset (excluding ``TIER_HUMAN``, which is operator
    judgment, not screenshot-assessable).

    Pure function — no I/O, no model calls. Returns an empty list when the
    spec has no visual criteria (the critique prompt then uses its no-criteria
    fallback text).

    NOTE: This helper is additive and does NOT change how ``criterion_status``
    reports visual criteria — they remain ``STATUS_EYEBALL`` regardless of any
    VLM critique result. The VLM is a loop signal only, never a verdict.
    """
    return [c.text for c in spec.criteria if c.tier == TIER_VISUAL]


def render_criteria_preview(
    spec: AcceptanceSpec,
    *,
    ecosystem: str = "unknown",
    tasks: list | None = None,
) -> str:
    """The confirm-time preview the operator approves (PLAN -> WAIT).

    Lists every criterion in plain English, grouped automatic vs eyeball, and — when the
    repo is a build-only ecosystem (.NET) or unknown — says UP FRONT that behavior won't
    be auto-checked, so a clean report later never misleads.

    When ``tasks`` (the COMPILED PlanResult tasks) are provided, a short plain-English
    "build plan" section is rendered near the top so the operator sees HOW the goal will be
    built — not only what counts as DONE — before approving. ``tasks=None`` (every existing
    caller) renders exactly as before, with no build-plan section.

    When ``spec.build_plan`` resolves to a known platform, a single display-only
    "Building this as: <friendly>" line is rendered (e.g. "a Windows desktop app") so the
    operator can sanity-check the resolved platform at the cheapest point — before any GPU
    time — and reject if it's wrong (#674). Fail-closed: an absent / ``unknown`` / unmapped
    surface omits the line (never a guessed platform). Same posture as the assumptions block.

    When ``spec.assumptions`` is non-empty, a plain-English "here's how I read the parts you
    didn't spell out" section is rendered so the operator — who gives detailed PRODUCT
    intent but no technical direction — can catch a PRODUCT-LEVEL misread (WHAT it should
    do / look / behave) before approving a long build, and reject + add detail if one is
    wrong. Display-only: no question/answer turn. Empty/absent assumptions (a fully-
    specified goal, and every existing caller) render exactly as before — no section.
    """
    lines = [f"Here's what I'll treat as DONE for: {spec.goal}", ""]
    friendly = _friendly_surface(spec)
    if friendly is not None:
        lines.append(f"Building this as: {friendly}.")
        lines.append("")
    if tasks:
        lines.append(f"Here's how I'll build it ({len(tasks)} task(s)):")
        lines.extend(f"  - {_humanize_task_name(t)}" for t in tasks)
        lines.append("")
    if spec.assumptions:
        lines.append(
            "Here's how I read the parts you didn't spell out (reject and add detail "
            "if I got one wrong):"
        )
        lines.extend(f"  - {a}" for a in spec.assumptions)
        lines.append("")
    obj = spec.objective
    hum = spec.human
    if obj:
        lines.append("Automatic checks (the coder fleet gates these):")
        lines.extend(f"  - {c.text}" for c in obj)
    if hum:
        lines.append("")
        lines.append("You check these yourself when you open the app:")
        lines.extend(f"  - {c.text}" for c in hum)

    if ecosystem == "dotnet":
        lines += [
            "",
            "Heads up: this is a C#/.NET app. The fleet can only auto-check that it "
            "BUILDS — it does not run .NET tests — so the behavior above is yours to "
            'verify by eye. A clean report means "it compiled," not "the math is right."',
        ]
    elif ecosystem == "unknown":
        lines += [
            "",
            "Heads up: I couldn't tell this project's language, so the automatic "
            'behavior checks may not run — treat a clean report as "it built" and '
            "verify the behavior yourself.",
        ]

    lines += ["", "Reply `/dispatch approve` to start, or `/dispatch reject` to cancel."]
    return "\n".join(lines)


def render_acceptance_report(
    spec: AcceptanceSpec,
    *,
    task_reports: list[TaskReport],
    repo: Path,
    run_command: str | None = None,
) -> str:
    """The post-build report: honest per-criterion status + the open-the-app step.

    Objective criteria are matched against the fleet's results; a check that never ran is
    rendered NOT AUTO-CHECKED, never a pass (the anti-rubber-stamp rule). Visual/human
    criteria are the operator's eyeball checklist. Ends with the one command to open the
    built app.
    """
    agg = _aggregate_reports(task_reports)
    lines = [f"Dispatch done for: {spec.goal}", ""]

    obj = spec.objective
    if obj:
        lines.append("Automatic checks:")
        for c in obj:
            status = criterion_status(c, agg)
            lines.append(f"  [{_STATUS_LABEL.get(status, status)}]  {c.text}")
        if any(criterion_status(c, agg) == STATUS_UNVERIFIED for c in obj):
            lines += [
                "",
                "  NOT AUTO-CHECKED means the fleet had no test it could run for that "
                "item (for C#/.NET, only the build is checked) — please confirm those "
                "yourself; they are NOT proven.",
            ]

    hum = spec.human
    if hum:
        lines += ["", "Please check by eye:"]
        lines.extend(f"  - {c.text}" for c in hum)

    cmd = run_command if run_command is not None else detect_run_command(repo)
    lines += ["", f"Open the app:  {cmd}", f"  (project folder: {repo})"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Acceptance-test ORACLE generation (the shared, spec-derived scorecard) — #690
# ---------------------------------------------------------------------------
#
# Best-of-N (#689) takes N INDEPENDENT coder candidates and lets the deterministic gate pick
# the winner. But in compile_prompts' single-feature shape the test criteria are FOLDED into
# the lone task, so each candidate writes ITS OWN tests — the gate is then comparing candidates
# that each graded their own homework, and a candidate can "pass" with weak happy-path tests
# that merely mirror its own code (the ~8-12%-self-test-validity risk, arXiv:2409.09464). The
# fix (#690): ONE shared, spec-derived acceptance ORACLE, written ONCE by the 14B at PLAN time
# (CROSS-MODEL — the 30B coder never authors the tests that grade it), seeded into every
# candidate's worktree as a PROTECTED file, and RESTORED before the gate so every candidate is
# judged by the byte-identical scorecard. The oracle is spec-BLIND: it is derived from the
# goal-level criteria (which the 14B proposed and the ruler disposed) BEFORE any implementation
# exists, so it cannot mirror code that has not been written yet.
#
# Fail-closed is absolute. The oracle is pytest, so it is PYTHON-ONLY (node/.NET/cpp/powershell
# -> '' == today's fold-the-tests-in behavior); and ANY junk emission (won't ast.parse, or
# defines no test function) -> '' as well. A '' oracle reproduces today's behavior BYTE-
# IDENTICALLY; a non-empty oracle NEVER blocks PLAN/EXECUTE — the worst case is a fall-back.

_ORACLE_TEMPLATE = (
    "Write a COMPLETE Python pytest test file: the executable ACCEPTANCE TESTS the "
    "implementation below must satisfy. Return ONLY Python code — no prose, no markdown fences.\n"
    "RULES:\n"
    "- Write ONLY tests, never the implementation. The project ALREADY contains a Python "
    "package named `app` (its `app/core.py` holds the starter module) and the implementer "
    "EXTENDS that package — so IMPORT everything you test FROM `app`: `from app.core import "
    "<fn>` for the main module, or `from app.<module> import <fn>` for a submodule you name "
    "after the behavior. Do NOT invent a new top-level module (a name like `calendar_math` or "
    "`text_analyzer` will not exist on disk, so pytest cannot even collect the file and every "
    "test fails on the import). Choose the function names from the criteria; the implementer "
    "is told to create EXACTLY the `app` module(s) and functions your tests import.\n"
    "- Derive every assertion from the criteria below — assert the behavior each criterion "
    "REQUIRES, with concrete example inputs and expected outputs. Never assert what some "
    "implementation merely happens to do (a test that mirrors the code proves nothing).\n"
    "- Where a criterion states a rule that must hold for ALL valid inputs (an invariant), ALSO "
    "add a Hypothesis property test (`from hypothesis import given, strategies as st`) asserting "
    "it over many auto-generated inputs.\n"
    "- Name each test function `test_<behavior>`; make the file self-contained and importable; "
    "add the obvious edge cases the criteria imply.\n\n"
    "Implementation the tests must hold against:\n{task_prompt}\n\n"
    "Criteria to assert (the REQUIRED behavior of each):\n{criteria}\n"
)

# Pull a fenced ```python ... ``` (or bare ``` ... ```) code block out of a model reply. The 14B
# is told "no markdown fences", but a small model sometimes wraps anyway; stripping the fence is
# the difference between a usable oracle and a needless fail-closed miss.
_PY_FENCE_RE = re.compile(r"```(?:python|py)?\s*\n?(.*?)```", re.DOTALL | re.IGNORECASE)
#: An OPENING python fence with NO matching close. A small model frequently omits the closing ```
#: (or the generation truncates before it) — the real 14B did exactly this on the first live #690
#: capture, and the stray ```python line then breaks ast.parse and rejects an otherwise-perfect
#: oracle. Strip the opener and keep the rest.
_PY_OPEN_FENCE_RE = re.compile(r"```(?:python|py)?[ \t]*\r?\n", re.IGNORECASE)
#: A trailing fence to drop on the unclosed-path result (belt-and-braces).
_PY_TRAILING_FENCE_RE = re.compile(r"\r?\n?```[ \t]*$")


def _extract_python_code(text: str) -> str:
    """Best-effort extract Python source from a model reply.

    Handles the three shapes a small model actually emits: a properly CLOSED ```python ... ```
    block (the common case); an UNCLOSED opening ```python fence with no close (strip the opener
    and keep the rest — the closing fence is often omitted or the generation truncates before it,
    which a real 14B did on the first live capture); and no fence at all (the whole text). Returns
    ``''`` for empty input."""
    if not text:
        return ""
    m = _PY_FENCE_RE.search(text)
    if m:
        return m.group(1).strip()
    m2 = _PY_OPEN_FENCE_RE.search(text)
    if m2:
        return _PY_TRAILING_FENCE_RE.sub("", text[m2.end():]).strip()
    return text.strip()


def _has_test_function(tree: ast.AST) -> bool:
    """True iff the parsed module defines at least one ``def test*`` (module-level OR a method of
    a ``Test`` class) — pytest's default discovery contract (``python_functions = test*``). A file
    with no test function is not an oracle (it would 'pass' vacuously), so it is rejected."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith(
            "test"
        ):
            return True
    return False


def generate_acceptance_oracle(
    goal: str,
    spec: "AcceptanceSpec",
    tasks: list[dict],
    *,
    generate_fn: Callable[[str], str],
) -> str:
    """PLAN-time: the 14B writes ONE spec-derived, spec-blind pytest ORACLE (#690) — the shared
    scorecard every best-of-N candidate codes against and is judged by.

    CROSS-MODEL by construction: this runs while the 14B is resident, BEFORE the 30B coder ever
    sees the task, so the coder never authors the tests that grade it (sidesteps the self-test
    validity problem). Built from the goal-derived behavior/smoke CRITERIA (the 14B proposed,
    the ruler disposed) plus the lone feature task's prompt, so the oracle's import names align
    with what the coder is told to build.

    Returns the oracle's Python source, or ``''`` (fall back to today's fold-the-tests-in
    behavior, BYTE-IDENTICAL) when ANY of these holds — all fail-closed, never raising:

      * no tasks (nothing to align names against);
      * the project is not PYTHON (the oracle is pytest; ``language_hint`` must be ``"python"`` —
        an absent/unknown/other hint keeps today's behavior; node is a tracked follow-up);
      * there are no behavior/smoke criteria to assert (an oracle adds nothing over the build gate);
      * the model output does not parse as Python, or defines no ``test`` function (junk);
      * the model call itself raises.

    The model call is injected so this is fully testable without the GPU."""
    if not tasks:
        return ""
    language_hint = (
        spec.build_plan.get("language_hint") if getattr(spec, "build_plan", None) else None
    )
    if language_hint != "python":
        # MVP: a pytest oracle only fires for an explicitly-python goal. Every other ecosystem
        # (and an unclassified one) keeps today's fold-the-tests-in behavior — fail-closed,
        # never seed a pytest file into a project that may not be python.
        return ""
    test_criteria = [c for c in spec.criteria if c.tier in TEST_TIERS]
    if not test_criteria:
        return ""
    criteria_block = "\n".join(
        f"- [{c.tier}] {c.text}" + (f"  (check: {c.check})" if c.check else "")
        for c in test_criteria
    )
    task_prompt = str(tasks[0].get("prompt", "")).strip() or goal
    try:
        raw = generate_fn(
            _ORACLE_TEMPLATE.format(task_prompt=task_prompt, criteria=criteria_block)
        )
    except Exception:  # noqa: BLE001 — an oracle-gen failure must not crash the plan
        return ""
    code = _extract_python_code(raw)
    if not code:
        return ""
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):  # ValueError: source with NULs etc.
        return ""
    if not _has_test_function(tree):
        return ""
    return code


# ---------------------------------------------------------------------------
# JOB-level acceptance ORACLE (multi-task jobs) — M2 W4 (#740)
# ---------------------------------------------------------------------------
#
# The #690 per-task oracle fires ONLY for single-task python plans — for MULTI-task jobs
# the final ``acceptance-tests`` task is authored by the 30B itself, i.e. the coder
# grades its own homework at exactly the job level where independence matters most
# (plan §2.3 gap 3). W4 closes that: at PLAN time (the 14B resident, CROSS-MODEL by
# construction) the 14B writes ONE job-level, spec-blind oracle asserting the GOAL's
# behavior/smoke criteria against the interfaces the tasks DECLARE (their W2 contracts
# — ruler-validated plan content, the only prose allowed in a prompt, §10 S2). The
# oracle is NOT seeded into the tree at plan start — a job oracle imports modules that
# do not exist until the last wave, so seeding it early would fail every per-task
# gate's full-suite run. Instead its bytes ride the plan artifacts (task dict →
# swap-state) and the driver grades the FINAL INTEGRATED tree with restore-before-
# grade semantics: the plan-carried bytes are written over whatever is on disk at the
# oracle path immediately before the run (so a merged edit to that path can never
# help), and the prior disk state is restored afterwards. The job reports done ONLY
# when this oracle passes (plan §4.5 — evidence-gated via mark_job_acceptance).
#
# Ecosystem honesty (mirrors #690): python (pytest) and node (node:test) only —
# everything else fail-closed to ("", "") == today's behavior, never a false gate.

#: Pinned job-oracle paths (jobplan/v1 + the §10 S1 containment allowlist — the driver
#: refuses to write oracle bytes anywhere else, so a tampered plan cannot traverse).
JOB_ORACLE_PATH_PYTHON = "tests/test_job_acceptance.py"
JOB_ORACLE_PATH_NODE = "tests/acceptance.job.test.mjs"
JOB_ORACLE_ALLOWED_PATHS: frozenset[str] = frozenset(
    {JOB_ORACLE_PATH_PYTHON, JOB_ORACLE_PATH_NODE}
)

#: The task-dict keys the job oracle rides from PLAN to the swap driver (stamped onto
#: the FINAL compiled task by generate_plan; popped by extract_job_oracle driver-side
#: before the task is enqueued to the fleet).
JOB_ORACLE_CODE_KEY = "job_oracle_code"
JOB_ORACLE_PATH_KEY = "job_oracle_path"

_JOB_ORACLE_TEMPLATE_PY = (
    "Write a COMPLETE Python pytest test file: the executable JOB-LEVEL ACCEPTANCE "
    "TESTS for the whole multi-part goal below, run once on the final integrated "
    "project after every part is built. Return ONLY Python code — no prose, no "
    "markdown fences.\n"
    "RULES:\n"
    "- Write ONLY tests, never the implementation. IMPORT what you test from the "
    "modules the parts declare below (their file paths and exported signatures are "
    "listed) — use exactly those module and function names.\n"
    "- Derive every assertion from the criteria below — assert the behavior each "
    "criterion REQUIRES end-to-end across the parts, with concrete inputs and "
    "expected outputs. Never assert what an implementation merely happens to do.\n"
    "- Name each test function `test_<behavior>`; make the file self-contained and "
    "importable.\n"
    "- If any test calls a CLI entry point (e.g. `main()`) in-process, it MUST first "
    "set `sys.argv` to a plain program name (e.g. `sys.argv = ['app']`, or with the "
    "specific arguments the test intends) — the test runner's own command-line "
    "arguments must never leak into the application under test.\n\n"
    "Goal:\n{goal}\n\n"
    "The project's parts (each part's declared files and exports):\n{contracts}\n\n"
    "Criteria to assert (the REQUIRED behavior of each):\n{criteria}\n"
)

_JOB_ORACLE_TEMPLATE_NODE = (
    "Write a COMPLETE JavaScript (ESM) test file using the built-in `node:test` "
    "runner: the executable JOB-LEVEL ACCEPTANCE TESTS for the whole multi-part goal "
    "below, run once on the final integrated project after every part is built. "
    "Return ONLY JavaScript code — no prose, no markdown fences.\n"
    "RULES:\n"
    "- Start with: import test from 'node:test'; import assert from 'node:assert';\n"
    "- Write ONLY tests, never the implementation. IMPORT what you test from the "
    "module files the parts declare below (their file paths and exported signatures "
    "are listed) — use exactly those paths (relative from the tests/ directory, e.g. "
    "`import {{ addExpense }} from '../src/storage.mjs';`).\n"
    "- Derive every assertion from the criteria below — assert the behavior each "
    "criterion REQUIRES end-to-end across the parts, with concrete inputs and "
    "expected outputs. Never assert what an implementation merely happens to do.\n"
    "- Use `test('...', () => {{ ... }})` blocks; no external dependencies.\n\n"
    "Goal:\n{goal}\n\n"
    "The project's parts (each part's declared files and exports):\n{contracts}\n\n"
    "Criteria to assert (the REQUIRED behavior of each):\n{criteria}\n"
)

# JS fence variants a small model wraps ESM test code in (mirrors _PY_FENCE_RE).
_JS_FENCE_RE = re.compile(
    r"```(?:javascript|js|mjs)?\s*\n?(.*?)```", re.DOTALL | re.IGNORECASE
)
_JS_OPEN_FENCE_RE = re.compile(r"```(?:javascript|js|mjs)?[ \t]*\r?\n", re.IGNORECASE)


def _extract_js_code(text: str) -> str:
    """Best-effort extract JS source from a model reply — the three shapes
    :func:`_extract_python_code` handles (closed fence / unclosed opener / bare)."""
    if not text:
        return ""
    m = _JS_FENCE_RE.search(text)
    if m:
        return m.group(1).strip()
    m2 = _JS_OPEN_FENCE_RE.search(text)
    if m2:
        return _PY_TRAILING_FENCE_RE.sub("", text[m2.end():]).strip()
    return text.strip()


def _node_oracle_valid(code: str) -> bool:
    """Structural validation of a node:test oracle (there is no ``ast.parse`` for JS —
    this is the deliberately-conservative shape check): it must import the node:test
    runner and define at least one ``test(``/``it(`` block. A file failing either is
    not an oracle (it would 'pass' vacuously) and is rejected fail-closed."""
    if not code or "node:test" not in code:
        return False
    return bool(re.search(r"\b(?:test|it)\s*\(", code))


def _job_oracle_target(spec: "AcceptanceSpec") -> "tuple[str, str] | None":
    """``(ecosystem, oracle_rel_path)`` for the job oracle, or ``None`` (fail-closed).

    python ⇐ an explicit ``language_hint == "python"``; node ⇐ an explicit ``node``
    hint OR a ``web`` surface with NO other hint (the fleet's web scaffold is the
    node:http + node:test seed, so a web job's integrated tree is node-testable —
    the Stage-2 shape). Everything else (absent/dotnet/cpp/powershell/unknown) gets
    NO job oracle — build-only ecosystems stay honestly UNVERIFIED, never a false
    gate."""
    bp = spec.build_plan if isinstance(spec.build_plan, dict) else {}
    hint = bp.get("language_hint")
    surface = bp.get("surface")
    if hint == "python":
        return ("python", JOB_ORACLE_PATH_PYTHON)
    if hint == "node" or (hint is None and surface == "web"):
        return ("node", JOB_ORACLE_PATH_NODE)
    return None


def _contracts_block(tasks: list[dict]) -> str:
    """The per-task contract summary fed to the oracle prompt — RULER-VALIDATED plan
    content only (task slug + creates/exports/notes), never anything from built files
    (§10 S2). Tasks without a usable contract are listed by slug alone."""
    lines: list[str] = []
    for t in tasks:
        slug = str(t.get("task", "") or "").strip() or "task"
        contract = t.get("contract") if isinstance(t.get("contract"), dict) else {}
        bits: list[str] = []
        creates = contract.get("creates") or []
        exports = contract.get("exports") or []
        notes = str(contract.get("notes", "") or "").strip()
        if creates:
            bits.append("creates " + ", ".join(str(c) for c in creates[:8]))
        if exports:
            bits.append("exports " + "; ".join(str(e) for e in exports[:8]))
        if notes:
            bits.append("notes: " + notes)
        lines.append(f"- {slug}: " + ("; ".join(bits) if bits else "(no declared interface)"))
    return "\n".join(lines)


def generate_job_acceptance_oracle(
    goal: str,
    spec: "AcceptanceSpec",
    tasks: list[dict],
    *,
    generate_fn: Callable[[str], str],
) -> tuple[str, str]:
    """PLAN-time: the 14B writes the JOB-LEVEL spec-blind oracle for a MULTI-task job.

    Returns ``(code, repo_relative_path)`` or ``("", "")`` — all fail-closed, never
    raising — when ANY of these holds:

      * fewer than 2 tasks (the #690 per-task oracle owns the single-task shape);
      * no python/node target resolves (:func:`_job_oracle_target` — .NET etc. stay
        honestly build-only);
      * there are no behavior/smoke criteria to assert;
      * NO task declares a usable contract (without declared interfaces the oracle
        would have to GUESS import names — a guessed oracle fails every job and
        teaches nothing; the honest outcome is job-acceptance ``not-run``);
      * the emission fails structural validation (python: ``ast.parse`` + a ``test``
        function; node: a ``node:test`` import + a ``test(``/``it(`` block);
      * the model call raises.

    An empty result leaves the dispatch byte-identical to today (the driver records
    job acceptance ``not-run`` — honest, never an implied pass)."""
    if len(tasks) < 2:
        return ("", "")
    target = _job_oracle_target(spec)
    if target is None:
        return ("", "")
    ecosystem, rel_path = target
    test_criteria = [c for c in spec.criteria if c.tier in TEST_TIERS]
    if not test_criteria:
        return ("", "")
    if not any(
        isinstance(t.get("contract"), dict)
        and (t["contract"].get("creates") or t["contract"].get("exports"))
        for t in tasks
    ):
        return ("", "")
    criteria_block = "\n".join(
        f"- [{c.tier}] {c.text}" + (f"  (check: {c.check})" if c.check else "")
        for c in test_criteria
    )
    template = (
        _JOB_ORACLE_TEMPLATE_PY if ecosystem == "python" else _JOB_ORACLE_TEMPLATE_NODE
    )
    try:
        raw = generate_fn(template.format(
            goal=(goal or "").strip(),
            contracts=_contracts_block(tasks),
            criteria=criteria_block,
        ))
    except Exception:  # noqa: BLE001 — an oracle-gen failure must not crash the plan
        return ("", "")
    if ecosystem == "python":
        code = _extract_python_code(raw)
        if not code:
            return ("", "")
        try:
            tree = ast.parse(code)
        except (SyntaxError, ValueError):
            return ("", "")
        if not _has_test_function(tree):
            return ("", "")
        return (code, rel_path)
    code = _extract_js_code(raw)
    if not _node_oracle_valid(code):
        return ("", "")
    return (code, rel_path)


def extract_job_oracle(tasks: list[dict]) -> tuple[list[dict], str, str]:
    """Driver-side: pop the riding job-oracle fields off the task dicts.

    Returns ``(cleaned_tasks, oracle_code, oracle_rel_path)`` — fresh task copies with
    :data:`JOB_ORACLE_CODE_KEY`/:data:`JOB_ORACLE_PATH_KEY` removed (the fleet queue
    never needs the blob), and the first non-empty code/path found. A path outside
    :data:`JOB_ORACLE_ALLOWED_PATHS` is REFUSED (dropped to ``("", "")`` — the §10 S1
    pinned-path containment; a tampered swap-state cannot aim the oracle write)."""
    cleaned: list[dict] = []
    code = ""
    path = ""
    for t in tasks:
        c = dict(t)
        raw_code = str(c.pop(JOB_ORACLE_CODE_KEY, "") or "")
        raw_path = str(c.pop(JOB_ORACLE_PATH_KEY, "") or "")
        if raw_code and raw_path and not code:
            code, path = raw_code, raw_path
        cleaned.append(c)
    if path not in JOB_ORACLE_ALLOWED_PATHS:
        return (cleaned, "", "")
    return (cleaned, code, path)


# ---------------------------------------------------------------------------
# The PLAN step (decompose + criteria + ruler + compile) — nothing irreversible
# ---------------------------------------------------------------------------


def generate_plan(
    idea: str,
    repo: str,
    *,
    generate_fn: Callable[[str], str],
    projects_dir: Path,
    max_tasks: int = DEFAULT_MAX_TASKS,
    max_criteria: int = DEFAULT_MAX_CRITERIA,
    max_assumptions: int = DEFAULT_MAX_ASSUMPTIONS,
    max_assets: int = DEFAULT_MAX_ASSETS,
    decomposition_override: "DecompositionOverride | None" = None,
    structured_generate_fn: "Callable[[str, str], str] | None" = None,
) -> PlanResult:
    """The 14B-resident PLAN step: decompose into tasks + an AcceptanceSpec, validate both,
    compile the criteria into the task prompts.

    Returns COMPILED tasks (ready to enqueue on approval) + the validated spec (for the
    confirm preview and the later report). The spec also carries the 14B's PRODUCT-LEVEL
    assumptions about the underspecified parts of the goal (``spec.assumptions``) — surfaced
    in the confirm preview so the operator can catch a misread before approving — AND the
    14B's COARSE product→platform build-signal (``spec.build_plan``, #674), whose goal-level
    fields are threaded onto every compiled task so they reach the fleet queue write. Nothing
    is enqueued and nothing irreversible happens here — the operator approves the spec before
    any work fires. The model call is injected so this is fully testable without the GPU.

    #743: when *structured_generate_fn* is provided (the W2/#718 xgrammar adapter, called
    ``(prompt, json_schema_text)``) EVERY structured JSON emission in the sequence —
    decompose (threaded through to :func:`decompose_request`), criteria, assumptions,
    build-signal, asset-specs — is tried grammar-constrained FIRST with a transparent
    fail-soft fallback to the free-text path; ``None`` (the default) is byte-identical to
    today. The oracle calls stay unconstrained (code emissions, not JSON).
    """
    # 1. Decompose (reuses the increment-2 decomposer: validate_repo + model + ruler + fallback)
    # — UNLESS a caller passed a pre-built, authorized decomposition (``decomposition_override``,
    # #752 F1). This seam is GENERIC (no caller-/battery-specific logic here): when present, the
    # 14B decomposer is bypassed and the override's tasks are used verbatim, so a caller that
    # KNOWS the right shape — the M2 battery's carded diamond, whose declared shape the 14B
    # right-sizing ruler collapses to one task — gets the graph instead of the collapse. ``None``
    # (every production plan request) leaves the model path byte-identical to today.
    if decomposition_override is not None:
        decomposed = DecomposeResult(
            ok=True,
            tasks=[dict(t) for t in decomposition_override.tasks],
            fell_back=False,
            collapsed_test_intent=False,
            message=(
                f"Using a caller-provided {len(decomposition_override.tasks)}-task decomposition."
            ),
        )
    else:
        decomposed = decompose_request(
            idea, repo, generate_fn=generate_fn, projects_dir=projects_dir,
            max_tasks=max_tasks,
            # #743: the live PLAN entry point is THIS function, so the W2 decompose hook
            # is threaded here — without it the grammar path could never fire on a real
            # /dispatch plan. Additive + fail-soft (None == today).
            structured_generate_fn=structured_generate_fn,
        )
    if not decomposed.ok:
        return PlanResult(ok=False, message=decomposed.message)

    # 2. Acceptance criteria — the 14B proposes; the ruler disposes (+ a build floor).
    # #743: grammar-first over the SAME schema _parse_criteria expects; a missing/erroring
    # hook or an unusable constrained emission runs today's free-text path UNCHANGED.
    goal = (idea or "").strip()
    criteria_prompt = _CRITERIA_TEMPLATE.format(max_criteria=max_criteria, idea=goal)
    raw = _grammar_first(
        criteria_prompt,
        structured_generate_fn=structured_generate_fn,
        schema=criteria_emission_json_schema(max_criteria=max_criteria),
        usable=lambda t: bool(_parse_criteria(t, max_criteria=max_criteria)),
    )
    if raw is None:
        try:
            raw = generate_fn(criteria_prompt)
        except Exception:  # noqa: BLE001 — a criteria-gen failure must not crash the plan
            raw = ""
    spec = rule_spec(goal, _parse_criteria(raw, max_criteria=max_criteria), max_criteria=max_criteria)

    # 2b. Never end at zero tests. The right-sizing decomposer drops the model's
    # structural test tasks (the test task is added downstream). So if it collapsed test
    # intent (it WANTED tests) but criteria-gen yielded no behavior/smoke criterion,
    # inject a default SMOKE criterion so compile_prompts still carries the test criterion
    # (folded into the lone feature task, or a dedicated final task when there are >=2).
    # Gated on collapsed_test_intent so a goal with genuinely no testable behavior (and no
    # test intent) keeps the honest no-test posture unchanged.
    if decomposed.collapsed_test_intent and not any(
        c.tier in TEST_TIERS for c in spec.criteria
    ):
        spec = _ensure_test_floor(spec)

    # 2c. Product assumptions — a SECOND, separate 14B call surfacing the PRODUCT-LEVEL
    # reads of the underspecified parts of the goal (WHAT it should do / look / behave) so
    # the operator can catch a misread in the confirm preview before a ~30-minute build.
    # Separate (not folded into the criteria call) so the criteria contract stays byte-
    # identical; the prompt is PRODUCT-NOT-TECH (it excludes language/framework/versions —
    # the operator can't answer those, the system supplies them via AGENTS.md). Fail-closed
    # AND non-blocking: a model/parse failure (or a fully-specified goal) yields no
    # assumptions and no preview section — the plan proceeds unchanged.
    # #743: grammar-first (array-of-strings schema). A constrained ``[]`` is a VALID
    # answer (the fully-specified goal) — accepted, no redundant free-text retry.
    assumptions_prompt = _ASSUMPTIONS_TEMPLATE.format(
        max_assumptions=max_assumptions, idea=goal
    )
    raw_assumptions = _grammar_first(
        assumptions_prompt,
        structured_generate_fn=structured_generate_fn,
        schema=assumptions_emission_json_schema(max_assumptions=max_assumptions),
        usable=_is_json_array_emission,
    )
    if raw_assumptions is None:
        try:
            raw_assumptions = generate_fn(assumptions_prompt)
        except Exception:  # noqa: BLE001 — an assumptions-gen failure must not crash the plan
            raw_assumptions = ""
    assumptions = _parse_assumptions(raw_assumptions, max_assumptions=max_assumptions)
    if assumptions:
        spec = AcceptanceSpec(
            goal=spec.goal, criteria=spec.criteria, assumptions=assumptions,
            build_plan=spec.build_plan,  # carry the (still-None here) signal — ordering-safe
        )

    # 2d. Build-signal — a THIRD, separate 14B call (after decompose + criteria + assumptions)
    # classifying PRODUCT intent into a COARSE platform signal (surface / language_hint /
    # complexity / components) the deterministic fleet maps to a scaffold + tech (#674). Same
    # SEPARATE-CALL discipline as assumptions: it keeps the criteria + assumptions JSON
    # contracts byte-identical. Fail-closed AND non-blocking: a model/parse failure yields
    # build_plan=None (no signal -> the fleet's conservative no-seed path == today's behavior),
    # and a model object it CAN parse is enum-validated to surface=unknown / language_hint=None
    # / complexity=moderate for any bad field. Attached LAST so it survives the assumptions
    # rebuild above regardless of order. None when the model emitted no parseable object.
    # #743: grammar-first with every field enum-pinned (incl. the ``ambiguous`` fork +
    # its real-surface ``candidates``); the parser still owns the coupling rules.
    build_plan_prompt = _BUILD_PLAN_TEMPLATE.format(idea=goal)
    raw_build_plan = _grammar_first(
        build_plan_prompt,
        structured_generate_fn=structured_generate_fn,
        schema=build_plan_emission_json_schema(),
        usable=lambda t: _parse_build_plan(t) is not None,
    )
    if raw_build_plan is None:
        try:
            raw_build_plan = generate_fn(build_plan_prompt)
        except Exception:  # noqa: BLE001 — a build-signal failure must not crash the plan
            raw_build_plan = ""
    build_plan = _parse_build_plan(raw_build_plan)
    if build_plan is not None:
        spec = AcceptanceSpec(
            goal=spec.goal, criteria=spec.criteria, assumptions=spec.assumptions,
            build_plan=build_plan,
        )

    # 2e. Acceptance-test ORACLE (#690) — the shared, spec-derived scorecard for best-of-N. The
    # 14B writes ONE spec-blind pytest file (CROSS-MODEL: the 30B coder never authors the tests
    # that grade it), seeded into every candidate's worktree and restored before the gate so all
    # candidates are judged by the byte-identical tests. Scoped to the lone PYTHON feature task
    # (the MVP — the case best-of-N + self-written tests collide worst). Only ATTEMPTED for a
    # single task (avoids a wasted GPU call on the multi-task shape, which keeps the dedicated
    # acceptance task); fail-closed to '' (== today's fold-the-tests-in behavior) for any other
    # ecosystem/shape or a junk emission, so a missing oracle never changes today's plan.
    oracle_code = ""
    if decomposition_override is None and len(decomposed.tasks) == 1:
        oracle_code = generate_acceptance_oracle(
            goal, spec, decomposed.tasks, generate_fn=generate_fn
        )

    # 2f. Image-asset specs — a FOURTH separate 14B call (UC-010 dispatch, SEAM A). For a
    # VISUAL product it lists the raster PICTURE assets the app should display (name +
    # subject + style); the deterministic ruler owns the file path, dims, cap, dedup, and
    # the visual-surface gate. Same separate-call discipline as build-signal/assumptions —
    # it keeps every prior JSON contract byte-identical. Fail-closed + non-blocking: any
    # failure (or a non-visual product) yields no asset specs, so the dispatch generates
    # nothing and the coder falls back to inline SVG. Attached LAST (no rebuild follows), so
    # it survives; empty () leaves the compiled tasks byte-identical to today.
    asset_specs = _asset_specs_from_plan(
        goal, spec.build_plan, generate_fn=generate_fn, max_assets=max_assets,
        structured_generate_fn=structured_generate_fn,
    )
    if asset_specs:
        spec = AcceptanceSpec(
            goal=spec.goal, criteria=spec.criteria, assumptions=spec.assumptions,
            build_plan=spec.build_plan, asset_specs=asset_specs,
        )

    # 2g. JOB-level acceptance oracle (M2 W4, #740) — the multi-task analogue of 2e. For a
    # job of >=2 tasks the 14B writes ONE job-level spec-blind oracle (python pytest or
    # node:test by ecosystem) asserting the GOAL criteria against the interfaces the tasks
    # DECLARE (their W2 contracts). Its bytes ride the FINAL compiled task dict
    # (JOB_ORACLE_CODE_KEY/JOB_ORACLE_PATH_KEY — popped by the swap driver via
    # extract_job_oracle before enqueue, graded on the final integrated tree with
    # restore-before-grade). Fail-closed to ("", "") — non-python/node ecosystems,
    # criteria-less specs, contract-less plans, and junk emissions all leave the compiled
    # tasks byte-identical to today (the driver then reports job acceptance not-run).
    job_oracle_code, job_oracle_path = "", ""
    if decomposition_override is not None:
        # The caller authored the JOB-level oracle alongside the decomposition (#752 F2); it
        # rides the final compiled task exactly like the 14B-written one below. The driver's
        # extract_job_oracle still enforces the pinned-path containment on job_oracle_path.
        job_oracle_code = decomposition_override.job_oracle_code
        job_oracle_path = decomposition_override.job_oracle_path
    elif len(decomposed.tasks) >= 2:
        job_oracle_code, job_oracle_path = generate_job_acceptance_oracle(
            goal, spec, decomposed.tasks, generate_fn=generate_fn
        )

    # 3. Compile behavior/smoke criteria into the task prompts (fleet schema unchanged). The
    # goal-level build-signal fields are threaded onto each task here (compile_prompts). When an
    # oracle was generated, the lone feature task is told to code against it (carrying it for the
    # fleet to seed); an empty oracle leaves the compile byte-identical to today.
    tasks = compile_prompts(decomposed.tasks, spec, oracle_code=oracle_code)
    if job_oracle_code and job_oracle_path and tasks:
        tasks[-1][JOB_ORACLE_CODE_KEY] = job_oracle_code
        tasks[-1][JOB_ORACLE_PATH_KEY] = job_oracle_path
    return PlanResult(
        ok=True,
        tasks=tasks,
        spec=spec,
        fell_back=decomposed.fell_back,
        message=f"Planned {len(tasks)} task(s) with {len(spec.criteria)} acceptance criteria.",
    )
