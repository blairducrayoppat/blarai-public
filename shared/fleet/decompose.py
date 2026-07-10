"""14B-driven task decomposition + a deterministic RIGHT-SIZING ruler (increment 2).

The 14B's one intelligent job in a swap dispatch: turn a natural-language coding
idea into N concrete fleet tasks WHILE it is still resident (design §2 steps 1-2),
before any teardown. The model PROPOSES; a DETERMINISTIC RULER DISPOSES — the model
never self-certifies (brief §7.3). A model that returns garbage or nothing falls
back to a single validated task (the increment-1 framing), so a dispatch never
silently produces zero work.

Right-sizing (the decomposition-granularity fix): a small goal stays ONE task; a
large goal decomposes into the fewest *coherent units*, never one-line-/one-test-
per-task. A free-associating 14B explodes "write an is_leap_year function" into
~9 fleet tasks (a task per test-case, a `define-` + `implement-` split, a
`create-file` step, an `acceptance-tests` task) — each of which would get its own
git worktree and its own model-swap cycle. The ruler collapses that explosion:

  * It emits only the fewest coherent **FEATURE** tasks. The downstream acceptance
    layer (``acceptance.compile_prompts``) carries the test intent separately — folded
    into the lone feature task, or a dedicated final task when there are >=2 — so the
    decomposer must NEVER emit per-test-case / scaffold / sub-step tasks.
  * Collapse is **sibling-relative + verb/object-anchored**, never a blunt slug
    prefix. A test/verify task is dropped ONLY when a real FEATURE sibling exists
    that it tests; a *standalone* test/verify goal (no feature sibling) is KEPT — it
    IS the deliverable. The test-intent token set deliberately EXCLUDES check /
    validate / lint / health-check / audit / scan so that legitimate
    validation/testing FEATURES ("build a unit-test generator", "add input
    validation", "implement a /health-check endpoint", "write a linter rule")
    survive un-collapsed.
  * A clearly-small (leaf) goal is right-sized to a single task by a conservative,
    single-artifact stop-condition (``_is_leaf_goal``) — the SDD foundation a future
    recursive decompose will call. ``max_depth`` is the recursion bound; single-pass
    decomposition operates at depth 1, keeping a still-too-big node as ONE flagged
    task rather than exploding it.

When the ruler collapses away test/verify tasks it records ``collapsed_test_intent``
so the caller (``acceptance.generate_plan``) can GUARANTEE a downstream test task
even if criteria-generation yields no behavior/smoke criterion — the "never end at
zero tests" invariant (the model wanted tests; the dispatch still produces one).

THE ENVELOPE POLICY (#691) — short, gated increments, not a whole-app one-shot.
A local ~30B coder is near-frontier on a SHORT, well-scoped, gated step and falls off
a cliff on a long unattended run: end-to-end success falls roughly p^N with the step
count (Toby Ord, arXiv:2505.05115), and METR measures ~100% on tasks under ~4 minutes
vs <10% past ~4 hours. So the dispatch UNIT is one COHERENT DELIVERABLE sized for one
short gated run, and the ruler bounds it on BOTH sides:

  * LOWER bound (``_collapse``, #670): never an atomic over-split — a function and its
    tests are one task, no per-test-case / scaffold / sub-step tasks (the live shakedown
    where the 14B exploded ``is_leap_year`` into 9 tasks is the lesson).
  * UPPER bound (this increment, #691): never a whole-app one-shot. A goal that names
    several INDEPENDENT user-invoked units (multiple screens, commands, or services) but
    that the 14B lumped into a SINGLE task is OFFERED to a bounded recursive split (the
    ``max_depth`` foundation made real): the 14B re-judges with a "go finer" prompt, the
    children are right-sized by the same ``_collapse`` ruler, and they REPLACE the lump
    ONLY on a strict improvement (>=2 coherent tasks) — so a genuinely coherent small app
    is left as one task (false-split is worse than a missed split). The strengthened
    decompose prompt is the PRIMARY lever (the 14B makes the semantic add-vs-delete call
    a regex cannot); the recursive split is the deterministic BACKSTOP for the clearest
    under-splits. Each task is then its own gated checkpoint downstream (own worktree ->
    best-of-N build -> test -> verify gate -> merge), so the cadence is one merge per
    coherent step. As local models climb the horizon curve (METR: the 50%-task-length
    doubles ~every 7 months) the same harness rides it automatically — a bigger unit just
    stops tripping the upper bound.

The model call is injected (``generate_fn``) so this is fully testable without the
GPU; the live wiring passes the AO's ``generate_text``. DORMANT until enabled.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from shared.fleet.dispatch import slugify_task, validate_repo

logger = logging.getLogger(__name__)

#: Hard cap on tasks from one idea (a swap runs them all in one 30B residency).
DEFAULT_MAX_TASKS = 8
#: Recursion bound (the SDD foundation, now load-bearing — #691). First-pass decomposition
#: runs at depth 1; the envelope UPPER-bound split runs ONE more level (depth 2) on an
#: under-split single task, then stops (the children are not re-split). ``max_depth <= 1``
#: disables the split entirely (today's single-pass behavior).
DEFAULT_MAX_DEPTH = 2
#: #691 envelope upper-bound trigger: a goal carrying at least this many independent-unit
#: markers ("and" / "," / " / ") that the 14B nonetheless lumped into a SINGLE task is offered
#: to the recursive splitter. 2 markers ≈ 3 enumerated units, which SKIPS a 2-aspect small app
#: ("adds and subtracts" — 1 marker, stays one task) but catches a multi-command app
#: ("add, list, and delete" — 3). Deliberately conservative: the 14B + the strict-improvement
#: fail-safe still gate the actual split, so a false trigger is a harmless no-op, but keeping the
#: trigger tight avoids even offering a coherent small app to the splitter.
_OVERSIZE_MIN_MARKERS = 2
#: Parse generously so the right-sizing ruler sees the WHOLE proposed split; the ruler
#: then enforces the real ``max_tasks`` cap on the survivors.
_PARSE_CEILING = 32

# ---------------------------------------------------------------------------
# M2 W2 (#740) — graph-field elicitation caps + tolerant cleaning
# ---------------------------------------------------------------------------
# The SAME decompose call now ALSO elicits ``depends_on`` + ``contract`` per task
# (additive JSON fields; plan §5 W2 — no 7th structured call). These constants are
# the SSOT for the contract bounds: ``plan_graph``'s ruler imports them, and the
# grammar schema below embeds them, so cleaning, validation, and constrained
# emission can never drift apart. Contract text is the ONLY plan-sourced
# human-language a context pack may carry (§10 S2), hence the hard caps and the
# control-char strip (an escape-evasion surface once composed into prompts/logs).

#: Pinned jobplan/v1 bound: ``contract.notes`` <= 280 chars.
CONTRACT_NOTES_MAX = 280
#: Defensive bounds beyond the pinned minimum: entries per contract list / chars per entry.
CONTRACT_LIST_MAX = 32
CONTRACT_ITEM_MAX = 256

#: Control characters (incl. newlines) stripped from contract strings.
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")


def clean_str_list(raw: object, *, max_items: int, max_len: int) -> list[str]:
    """Tolerant string-list cleaning: non-list ⇒ ``[]``; non-str/empty items dropped;
    control chars stripped; item length and item count capped. Order-preserving,
    deduped. Shared by this module's contract parse and ``plan_graph``'s ruler."""
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            continue
        cleaned = _CTRL_RE.sub("", item).strip()[:max_len]
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            out.append(cleaned)
        if len(out) >= max_items:
            break
    return out


def clean_contract_fields(raw: object) -> dict:
    """Normalize a raw contract into ``{"creates", "exports", "notes"}`` (possibly all
    empty). Non-dict input ⇒ the all-empty shape — a malformed contract must NEVER
    block a task (pinned invariant). Newlines in ``notes`` collapse to spaces (a
    one-line interface card, not documentation)."""
    if not isinstance(raw, dict):
        return {"creates": [], "exports": [], "notes": ""}
    notes_raw = raw.get("notes", "")
    notes = (
        _CTRL_RE.sub(" ", notes_raw).strip()[:CONTRACT_NOTES_MAX]
        if isinstance(notes_raw, str) else ""
    )
    return {
        "creates": clean_str_list(raw.get("creates"), max_items=CONTRACT_LIST_MAX,
                                  max_len=CONTRACT_ITEM_MAX),
        "exports": clean_str_list(raw.get("exports"), max_items=CONTRACT_LIST_MAX,
                                  max_len=CONTRACT_ITEM_MAX),
        "notes": notes,
    }


def _clean_depends_on(raw: object) -> "list[str] | None":
    """Tolerant ``depends_on`` cleaning. ``None`` ⇒ the field was absent or garbage
    (the key is OMITTED from the task — the task does not vote for graph-awareness,
    so an all-omitted plan degrades to today's serial chain at plan build). A valid
    list ⇒ slugified, deduped refs (possibly ``[]`` — an EXPLICIT independent root).
    A ref with no alphanumerics is dropped rather than slugified: ``slugify_task``'s
    ``"task"`` fallback would otherwise INVENT a phantom ref."""
    if not isinstance(raw, list):
        return None
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str) or not any(ch.isalnum() for ch in item):
            continue
        slug = slugify_task(item)
        if slug not in seen:
            seen.add(slug)
            out.append(slug)
    return out

_DECOMPOSE_TEMPLATE = (
    "You are decomposing a software change request into the FEWEST coherent coding "
    "tasks for an automated coding agent. Return ONLY a JSON array (no prose) of at "
    'most {max_tasks} objects, each {{"task": "<kebab-case-slug>", "prompt": "<one '
    'precise instruction>", "depends_on": ["<task slug this builds on>"], '
    '"contract": {{"creates": ["<relative file path>"], "exports": ["<public '
    'signature>"], "notes": "<data shapes, one short line>"}}}}.\n\n'
    "RULES — fewest coherent tasks, never atomic splits:\n"
    "- Prefer ONE task. Split ONLY when the request genuinely spans INDEPENDENT units "
    "of work (e.g. separate features, separate commands a user invokes).\n"
    "- A function AND its tests are ONE task. Do NOT create a separate task per test "
    "case, per file, or per step.\n"
    "- Do NOT emit separate 'define', 'implement', 'create-file', 'scaffold', or "
    "'set-up' sub-step tasks for the same unit — express it as one implementation task.\n"
    "- Do NOT add a standalone 'write tests', 'acceptance-tests', 'verify', or "
    "'edge-cases' task; testing is handled separately downstream.\n"
    "- A single small GUI app — ONE window/screen/dialog and the behavior of the "
    "controls ON it (a button's click, a field's validation, a label that updates) — "
    "is ONE task. Do NOT split the window/UI from its button/handler/logic. Split into "
    "separate tasks ONLY for genuinely independent user-invoked units: separate "
    "top-level commands (add / list / done), separate pages/screens, or separate "
    "services.\n"
    "- ENVELOPE: each task must be small enough to BUILD and VERIFY in ONE short automated "
    "run. A larger app with several independent parts (multiple screens, multiple user "
    "commands, multiple services) is therefore MULTIPLE tasks — one per independent part — "
    "never one giant whole-app task; whole-app-in-one-task is the exception, not the default. "
    "(This does NOT loosen the rules above: a single function or a single small screen is "
    "still ONE task — this only forbids the opposite error of cramming many independent parts "
    "into one run.)\n"
    "- DISTINCT-OUTPUT PIPELINE: a goal that asks for SEVERAL DISTINCT OUTPUTS, or a PIPELINE "
    "of distinct stages (first produce A; then from A produce B and C; then combine them into "
    "D), is MULTIPLE tasks — ONE per distinct output or stage — even when it is described as a "
    "small 'toolkit', 'utility', 'helper', 'library', or 'script'. Diminutive words ('little', "
    "'simple', 'tidy', 'just', 'quick', 'basic') describe TONE, not size: COUNT THE DISTINCT "
    "OUTPUTS/STAGES the goal names, never the adjectives. (Still bounded by the rules above: a "
    "SINGLE stage or a single computation is ONE task — this catches only the opposite error "
    "of collapsing a genuinely multi-stage pipeline into one lump because it was asked for "
    "modestly.)\n"
    "- The PRIMARY functionality the user asks for must ALWAYS be built — there must "
    "be a task that produces it. When a goal names a core deliverable (a calculator, a "
    "parser, a game) alongside decorative or secondary aspects (theming, a custom window "
    "shape, styling), the core functionality is required, never optional — never produce "
    "only the decoration/theming and drop the core. E.g. 'a rocket-themed calculator' "
    "must include building the calculator's actual arithmetic/operations, not only the "
    "rocket visuals.\n"
    "- Each task's prompt must be self-contained and name a single coherent deliverable.\n\n"
    # M2 W2 (#740): dependency + interface elicitation on the SAME call — additive JSON
    # fields the deterministic plan ruler validates (absent/garbage fields degrade to
    # today's serial chain; the model's graph is a PROPOSAL, never an order).
    "GRAPH FIELDS — dependencies and interfaces, for the automated scheduler:\n"
    '- "depends_on": the "task" slugs (from THIS array ONLY) of the tasks this one '
    "builds DIRECTLY on; [] for an independent task. Never reference a slug that is "
    "not in the array.\n"
    '- "contract": the interface this task will create — "creates": the relative file '
    'paths it adds; "exports": the public function/class signatures other tasks may '
    'import; "notes": ONE short line on data shapes (under 280 characters). Use empty '
    "values when unsure — never invent.\n\n"
    # A shape-only few-shot pair: the pipeline case (distinct outputs -> several tasks, the
    # #740 M2 under-decomposition fix) beside the coherent-small-app case (one task) so the
    # model sees BOTH bounds. The 'little toolkit ... report' example directly counters the
    # diminutive-framing under-scope that collapsed a 4-stage text-stats pipeline to 1 task.
    "EXAMPLES (shape only -- mirror the COUNT, not the wording):\n"
    "- 'a little toolkit that reads text: break it into words, then work out how often each "
    "word appears AND which neighbouring word-pairs occur most, then pull both into one tidy "
    "report' -> FOUR tasks: tokenize-text; count-word-frequencies; count-bigram-frequencies; "
    "compose-combined-report (four distinct outputs; 'little'/'tidy' do not make them one).\n"
    "- 'a rocket-themed calculator with add, subtract, and clear buttons' -> ONE task (a "
    "single small screen and the behavior of the controls on it; the theme is not a unit).\n\n"
    "Request:\n{idea}\n"
    # /no_think — the MAIN decompose is a STRUCTURAL JSON enumeration (same class as
    # _SPLIT_TEMPLATE below). With W2's bigger per-task shape (depends_on + contract), a
    # <think> block overflows _PLAN_MAX_NEW_TOKENS and TRUNCATES the JSON array → parse fails
    # → minimal single-task fallback. This was the M2 live-verify failure (2026-07-05, #740):
    # a 3-task goal fell back to a 1-task plan. Suppress thinking here too (ADR-012 §2.4).
    "/no_think\n"
)

# Pull the first JSON array out of a model response (it may wrap it in prose/fences).
_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)


def _repair_json_array(span: str) -> str:
    """Bounded deterministic repair for ALMOST-valid model JSON (#748 live-verify:
    the 14B emitted a perfect 8-task dependency graph and closed the final task
    object with ``]]`` instead of ``}]`` — one wrong closer at the tail cost the
    entire graph and every plan collapsed to the minimal single-task fallback).

    A string-aware bracket-stack walk over the extracted array span:
      * a MISMATCHED closer auto-closes the scopes the model forgot (``]`` while a
        ``{`` is open ⇒ insert ``}`` first);
      * a STRAY closer with no matching opener is dropped;
      * scopes (and an unterminated string) still open at EOF are closed;
      * a dangling comma before any inserted closer is removed.

    Pure and deterministic — model proposes, THIS disposes. Only ever invoked
    AFTER ``json.loads`` failed, so valid output is never touched; if the repair
    still does not parse, the caller keeps today's ``[]``-fallback semantics."""

    def _drop_dangling_comma(buf: list[str]) -> None:
        while buf and buf[-1] in " \t\r\n":
            buf.pop()
        if buf and buf[-1] == ",":
            buf.pop()

    out: list[str] = []
    stack: list[str] = []
    in_str = False
    esc = False
    for ch in span:
        if in_str:
            out.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
            continue
        if ch in "[{":
            stack.append(ch)
            out.append(ch)
            continue
        if ch in "]}":
            want = "[" if ch == "]" else "{"
            while stack and stack[-1] != want:
                opener = stack.pop()
                _drop_dangling_comma(out)
                out.append("]" if opener == "[" else "}")
            if not stack:
                continue  # stray closer — drop it
            stack.pop()
            _drop_dangling_comma(out)
            out.append(ch)
            continue
        out.append(ch)
    if in_str:
        out.append('"')
    while stack:
        opener = stack.pop()
        _drop_dangling_comma(out)
        out.append("]" if opener == "[" else "}")
    return "".join(out)

#: The #691 envelope UPPER-bound "go finer" prompt — used ONLY on a single task the first pass
#: under-split. It deliberately biases toward MORE granularity (the opposite of the decompose
#: template's "fewest"), but still forbids atomic splits, and tells the model to return the lone
#: task UNCHANGED when it is already one coherent short step (so a coherent small app is a no-op
#: under the strict-improvement fail-safe). The routing phrase "TOO LARGE to build and verify in
#: one short" is unique to this template (a test fake routes on it).
_SPLIT_TEMPLATE = (
    "The coding task below is TOO LARGE to build and verify in one short automated run. Break "
    "it into the FEWEST sequential steps that are EACH independently buildable and verifiable "
    "and each of which leaves the project in a WORKING state. Return ONLY a JSON array (no "
    'prose) of at most {max_tasks} objects, each {{"task": "<kebab-case-slug>", "prompt": "<one '
    'precise instruction>", "depends_on": ["<task slug this builds on>"], '
    '"contract": {{"creates": ["<relative file path>"], "exports": ["<public '
    'signature>"], "notes": "<data shapes, one short line>"}}}}.\n\n'
    "RULES:\n"
    "- Each step is ONE coherent unit — one screen, one user command, one endpoint, one service "
    "— small enough to finish and test quickly.\n"
    "- Order them so each builds on the last (the foundational unit first), and record that "
    'order in "depends_on" (slugs from THIS array only; [] for the foundational step).\n'
    "- Do NOT split a single function or a single small screen into sub-steps, and do NOT add "
    "separate 'write tests' / 'scaffold' / 'set-up' steps (testing is handled downstream).\n"
    "- DISTINCT data transformations or DISTINCT reported outputs ARE separate steps: "
    "tokenizing text, computing one statistic, computing a DIFFERENT statistic, and assembling "
    "a combined report over them are FOUR steps, not one -- even for a tool described as "
    "'little', 'simple', or 'tidy'. Count the distinct outputs the task names, not its adjectives.\n"
    "- If the task is ALREADY a single coherent short step, return an array containing just that "
    "one task — do NOT invent splits.\n\n"
    "Task:\n{prompt}\n"
    # /no_think — this is a STRUCTURAL JSON enumeration, not a reasoning task, and the PLAN token
    # budget (_PLAN_MAX_NEW_TOKENS = 1024) is tight: a long <think> block spends the budget and
    # TRUNCATES the JSON array, so the parse fails and the backstop falls back (proven on the Arc
    # 140V — a verbose think block cut the array mid-stream). Suppressing thinking (the ADR-012
    # §2.4 PA-classification posture, applied here to the same kind of structural call) keeps the
    # whole budget for the answer so the split actually fires when it should. (#691)
    "/no_think\n"
)


# ---------------------------------------------------------------------------
# Token taxonomy for the deterministic right-sizing ruler
# ---------------------------------------------------------------------------
# The ruler classifies each PROPOSED task as feature | test | scaffold from its slug
# (leading verb + object). The sets are deliberately tight on the STRUCTURAL side
# (test/scaffold) because false-collapse — wrongly dropping a real feature — is the
# main risk; anything ambiguous stays a FEATURE.

#: Leading verbs of a STRUCTURAL-TEST *candidate* — resolved by the OBJECT (pass 2), so
#: ``verify-signature`` (a deliverable) and ``test-leap-year-2024`` (a per-case test of a
#: sibling) classify differently. ``check`` / ``validate`` / ``lint`` / ``audit`` /
#: ``scan`` / ``monitor`` / ``assert`` are deliberately ABSENT — they name feature
#: domains (health-check, input-validation, linters, scanners, monitors).
_TEST_VERBS = frozenset({"test", "tests", "verify", "verifies"})

#: Leading verbs that mark a SCAFFOLD / sub-step task (collapsed when a feature exists).
#: ``setup`` is here too (setup-<route|harness|config> is plumbing); the sibling guard
#: keeps a standalone ``setup-*`` with no feature sibling.
_SCAFFOLD_VERBS = frozenset({"define", "declare", "scaffold", "stub", "setup"})

#: Verbs that, with a PURELY generic-artifact object, mark a scaffold (``create-file``).
_ARTIFACT_VERBS = frozenset({"create", "add", "make", "generate", "set"})
#: Verbs of the ``create-file`` idiom (a literal FILE being created -> scaffold plumbing).
_FILE_SCAFFOLD_VERBS = frozenset({"create", "make", "generate"})
#: Object nouns that (alone) mark a generic scaffold artifact rather than a feature.
_ARTIFACT_NOUNS = frozenset({
    "file", "files", "folder", "folders", "directory", "directories", "skeleton",
    "boilerplate", "scaffolding", "structure", "layout", "project",
})

#: Verbs whose object, if PURELY a test-noun, mark a structural "write the tests" task.
_TEST_OBJECT_VERBS = frozenset({"add", "write", "create", "make", "generate"})
#: Object nouns that mark a PURELY-test deliverable (the "add tests" anti-pattern). An
#: EXACT closed set, matched only when the WHOLE object reduces to these — never a prefix
#: or substring — so "add-test-data-generator" / "write-test-coverage-reporter" (whose
#: object carries a real feature head-noun) are NOT mis-dropped.
_TEST_NOUNS = frozenset({
    "test", "tests", "testcase", "testcases", "unittest", "unittests",
})

#: Object HEAD nouns that make a test/verify-led slug a deployable FEATURE, not a
#: structural test — a "test-runner" / "mock-generator" / "fuzzer" is a tool you ship.
_ARTIFACT_FEATURE_NOUNS = frozenset({
    "endpoint", "service", "middleware", "page", "component", "resolver", "job",
    "worker", "runner", "harness", "tool", "reporter", "generator", "library",
    "framework", "factory", "client", "server", "daemon", "cli", "api", "dashboard",
    "ui", "widget", "parser", "formatter", "validator", "scanner", "linter",
    "monitor", "fuzzer", "module", "pipeline", "loader", "engine", "plugin",
})
#: Cryptographic / runtime-INTEGRITY object nouns — a "verify-signature" / "verify-
#: checksum" task is the DELIVERABLE (verification IS the product), never structural.
_INTEGRITY_NOUNS = frozenset({
    "signature", "checksum", "hash", "crc", "hmac", "digest", "parity", "seal",
    "cert", "certificate",
})

#: Object tokens that mark a test/verify slug as a STRUCTURAL assertion ("test-resolver-
#: RETURNS-profile", "test-health-503") even though it names an artifact — these prove the
#: task asserts a behavior of a sibling, not that it BUILDS a verification deliverable.
_ASSERTION_TOKENS = frozenset({
    "returns", "return", "missing", "rejects", "reject", "accepts", "accept",
    "handles", "handle", "shows", "show", "raises", "raise", "throws", "throw",
    "fails", "fail", "passes", "valid", "invalid", "empty", "null", "none",
    "equals", "equal", "contains", "matches", "match", "mismatch", "ok", "error",
    "success", "duplicate", "conflict", "roundtrip", "identical", "overflow",
    "required", "decreases", "decrease", "increases", "increase", "crashes", "crash",
    "overfits", "underflow",
    "200", "201", "204", "400", "401", "403", "404", "409", "422", "500", "503",
})

#: Filler tokens ignored when judging whether an object is "purely" test / artifact.
_FILLERS = frozenset({
    "a", "an", "the", "for", "to", "of", "and", "with", "some", "basic", "simple",
    "unit", "integration", "e2e", "end", "all", "new", "more", "additional", "my",
    "that", "this", "in", "on", "is", "it", "no",
})

#: Reserved slugs that are always structural (the planner's stock meta-task shapes).
_RESERVED_STRUCTURAL = frozenset({
    "acceptance-tests", "acceptance-test", "verify-edge-cases", "edge-cases",
    "edge-case-tests", "run-tests", "add-tests", "write-tests", "unit-tests",
    "integration-tests", "test-suite", "test-cases",
})

#: A slug led by a "tests for X" modifier (``unit-tests-X`` / ``integration-tests-Y`` /
#: ``tests-Z``) is a STRUCTURAL "write the tests" task the acceptance layer owns. The leading
#: ``unit`` / ``integration`` / ``e2e`` filler hides the test marker from the verb taxonomy (the
#: verb reads ``unit``, not ``tests``), so a planner that splits "unit-tests-<feature>" off as its
#: own task explodes the queue (the live C dispatch: 7 tasks, 3 of them test slugs). Captured group
#: 1 is the object; collapsed UNLESS it names a test-TOOL deliverable you ship (runner/harness). (#688 F5)
_LEADING_TESTS_RE = re.compile(r"^(?:unit-|integration-|e2e-)?tests?-(.+)$")

#: Single-artifact nouns that mark a GOAL as a leaf (one coherent unit -> one task).
_LEAF_ARTIFACT_RE = re.compile(
    r"\b(function|method|helper|endpoint|route|rule|validator|class|component|"
    r"constant|util|utility|script|command|handler|hook|migration|regex|"
    r"decorator|fixture|query|wrapper|parser|formatter)\b",
    re.IGNORECASE,
)
#: Markers that a goal enumerates MULTIPLE deliverables (so it is NOT a leaf). A "/" is a
#: separator only when space-surrounded ("add / list / done"), never inside a path token
#: ("/health-check"); "with" is intentionally excluded (one unit can have a modifier).
_MULTI_UNIT_RE = re.compile(r"\b(and|also|plus|then)\b|[,;]|\s/\s", re.IGNORECASE)


@dataclass(frozen=True)
class DecomposeResult:
    """Outcome of decomposition. ``tasks`` are ``{repo, task, prompt}`` dicts, plus
    OPTIONAL ``depends_on`` / ``contract`` keys when the model provided usable graph
    fields (M2 W2 — absent keys keep the legacy shape byte-identical; the plan
    builder treats an all-absent plan as today's serial chain)."""

    ok: bool
    tasks: list[dict] = field(default_factory=list)
    fell_back: bool = False   # True if the model output was unusable → single task
    collapsed_test_intent: bool = False  # True if the ruler dropped >=1 structural-test
    split_oversize: bool = False  # True if the #691 envelope split replaced an under-split lump
    used_grammar: bool = False  # True if the MAIN emission ran grammar-constrained (W2)
    message: str = ""


def _parse_candidates(text: str, *, max_tasks: int) -> list[dict]:
    """Best-effort parse of the model output into ``[{task, prompt}]``; ``[]`` on failure.

    M2 W2: ALSO carries the optional graph fields when present-and-valid — a cleaned
    ``depends_on`` (slugified refs; an explicit ``[]`` is kept, marking a deliberate
    independent root) and a normalized non-empty ``contract``. Absent/garbage fields
    are simply OMITTED (tolerant — never a new failure mode; the legacy two-key shape
    is what every pre-W2 caller still sees)."""
    if not text:
        return []
    match = _JSON_ARRAY_RE.search(text)
    if match:
        span = match.group(0)
    else:
        # #748: hard truncation can eat EVERY closing bracket, so the strict
        # regex never matches — repair from the first opener to EOF instead of
        # giving up (bare-token junk still fails json.loads → today's []).
        start = text.find("[")
        if start == -1:
            return []
        span = text[start:]
    try:
        data = json.loads(span)
    except (ValueError, TypeError):
        # #748: one wrong closer at the tail of an otherwise-perfect graph must
        # not cost the whole plan — try the bounded deterministic repair before
        # giving up (repair-then-parse; still-broken keeps today's [] fallback).
        try:
            data = json.loads(_repair_json_array(span))
        except (ValueError, TypeError):
            return []
        logger.info(
            "decompose: JSON repair salvaged the array (span_len=%d)", len(span)
        )
    if not isinstance(data, list):
        return []
    out: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        task = str(item.get("task", "")).strip()
        prompt = str(item.get("prompt", "")).strip()
        if task and prompt:
            cand: dict = {"task": task, "prompt": prompt}
            deps = _clean_depends_on(item.get("depends_on"))
            if deps is not None:
                cand["depends_on"] = deps
            if isinstance(item.get("contract"), dict):
                contract = clean_contract_fields(item["contract"])
                if contract["creates"] or contract["exports"] or contract["notes"]:
                    cand["contract"] = contract
            out.append(cand)
        if len(out) >= max_tasks:
            break
    return out


def _slug_parts(slug: str) -> tuple[str, set[str], set[str]]:
    """``(leading_verb, object_tokens, object_tokens_minus_fillers)`` for a slug."""
    toks = [t for t in slug.split("-") if t]
    verb = toks[0] if toks else ""
    objset = set(toks[1:])
    return verb, objset, (objset - _FILLERS)


def _is_file_scaffold(slug: str) -> bool:
    """The ``create-file`` idiom: a create/make/generate of a literal FILE (``file`` as
    the token right after the verb, or the trailing token) is scaffold plumbing —
    ``create-file-coupon-validator`` / ``create-health-check-handler-file``. Guarded to
    create-verbs so a real feature like ``implement-file-upload`` / ``add-file-watcher``
    is never mistaken for scaffold.
    """
    toks = [t for t in slug.split("-") if t]
    if not toks or toks[0] not in _FILE_SCAFFOLD_VERBS:
        return False
    return (len(toks) > 1 and toks[1] == "file") or toks[-1] == "file"


def _trailing_number(slug: str) -> bool:
    """The slug ends in a 2-4 digit token (``test-leap-year-2024``, ``test-health-503``) —
    a per-test-case enumeration marker."""
    toks = slug.split("-")
    return bool(toks) and toks[-1].isdigit() and 2 <= len(toks[-1]) <= 4


def _classify(slug: str) -> str:
    """Classify a slug as ``feature`` | ``test`` | ``scaffold`` | ``verifyish``.

    ``verifyish`` is a leading test/verify task that carries its OWN object noun and so
    cannot be judged structural-vs-feature in isolation — ``verify-email-address`` (a real
    email-confirmation FEATURE) and ``test-add`` (a test of an ``add`` sibling) have the
    same shape. ``_collapse`` resolves it sibling-relatively (the shared-empty test):
    structural only when nothing of its OWN is left after removing tokens shared with a
    sibling. This is the false-collapse fix the adversarial pass forced — a feature named
    with a leading ``verify`` verb (email / OTP / age / permissions / manifest) is NOT
    silently dropped just because its noun is absent from the artifact/integrity allow-set.
    The decisive-in-isolation cases resolve here; the rest defer to the sibling test.
    """
    if slug in _RESERVED_STRUCTURAL:
        return "test"
    # "unit-tests-X" / "integration-tests-Y" / "tests-Z" -- a "write tests for X" task whose leading
    # unit/integration/e2e filler hid the test marker from the verb taxonomy. Structural (the
    # acceptance layer owns testing) UNLESS X names a test-TOOL deliverable you ship. (#688 F5)
    _lt = _LEADING_TESTS_RE.match(slug)
    if _lt:
        _obj = {t for t in _lt.group(1).split("-") if t} - _FILLERS
        if not (_obj & _ARTIFACT_FEATURE_NOUNS):
            return "test"
    verb, objset, nf = _slug_parts(slug)
    if verb in _TEST_VERBS:
        # An assertion phrase (returns-X, rejects-Y, -503) makes it a structural test of a
        # sibling even when it names an artifact ("test-resolver-returns-profile").
        if nf & _ASSERTION_TOKENS:
            return "test"
        # verify-signature / test-runner — verification/test-tooling IS the product.
        if nf & (_ARTIFACT_FEATURE_NOUNS | _INTEGRITY_NOUNS):
            return "feature"
        # Objectless verify / pure test-noun / reserved edge-cases / per-case number.
        if not nf or nf <= _TEST_NOUNS or "edge" in objset or _trailing_number(slug):
            return "test"
        return "verifyish"  # has its own noun — resolve sibling-relatively in _collapse
    if verb in _SCAFFOLD_VERBS or _is_file_scaffold(slug):
        return "scaffold"
    # create/add/make/generate producing ONLY a generic artifact (+fillers) -> scaffold.
    if verb in _ARTIFACT_VERBS and nf and nf <= _ARTIFACT_NOUNS:
        return "scaffold"
    # add/write/create/make/generate producing ONLY a pure test-noun object -> structural.
    if verb in _TEST_OBJECT_VERBS and (nf & _TEST_NOUNS) and nf <= _TEST_NOUNS:
        return "test"
    return "feature"


def _resolve_verifyish(slug: str, others_tokens: set[str]) -> str:
    """The shared-empty test for a ``verifyish`` slug (a verify/test task with its own
    noun): STRUCTURAL only if it has NO deliverable noun left once tokens shared with the
    OTHER siblings (plus assertion/filler/number tokens) are removed.

    ``test-add`` vs ``implement-add-todo`` -> own {add} - others{...add...} = {} -> test.
    ``verify-email-address`` vs ``send-welcome-email`` -> own {email,address} - others
    {...email...} = {address} (a real deliverable noun) -> FEATURE. Defaults to FEATURE
    (the never-false-collapse-a-real-feature direction).
    """
    _, _objset, nf = _slug_parts(slug)
    own = {t for t in (nf - _ASSERTION_TOKENS) if not t.isdigit()}
    return "test" if not (own - others_tokens) else "feature"


def _collapse(candidates: list[dict]) -> tuple[list[dict], bool]:
    """Right-size the proposed tasks: drop STRUCTURAL-TEST + SCAFFOLD sub-step tasks WHEN
    a real FEATURE sibling exists, leaving the fewest coherent feature tasks.

    Sibling-relative + never-zero. A leading test/verify task survives as a FEATURE when
    it names a deployable artifact / integrity deliverable (``verify-signature``,
    ``test-runner``) OR keeps a deliverable noun of its own under the shared-empty test
    (``verify-email-address`` -> ``address`` remains); it is dropped only when it has no
    such noun (``test-add`` beside ``implement-add-todo``). If NO feature task exists (an
    all-structural proposal with the implementation implicit) the list is collapsed to ONE
    representative rather than kept whole. The last task is never dropped.

    A second pass also reclassifies a feature-shaped "add a test for <X>" task as
    structural when its non-test tokens reference an existing feature root.

    Returns ``(survivors, collapsed_test_intent)`` where ``collapsed_test_intent`` is True
    iff at least one structural-TEST task was dropped (the never-zero-tests signal).
    """
    if not candidates:
        return [], False

    slugs = [slugify_task(c.get("task", "")) for c in candidates]
    kinds = [_classify(s) for s in slugs]
    all_tokens = [set(s.split("-")) for s in slugs]

    # Per-case ENUMERATION: a test/verify-led task that shares an object token with ANOTHER
    # test/verify-led sibling is one of several per-case tests of the same thing -> all
    # structural ("test-iso8601-pt1h" / "-p1dt12h" share "iso8601"). Distinct verify-
    # FEATURES ("verify-email" + "verify-sms") share NO object token, so they are NOT swept.
    tv = [i for i, s in enumerate(slugs) if _slug_parts(s)[0] in _TEST_VERBS]
    tv_obj = {i: _slug_parts(slugs[i])[2] for i in tv}
    for a in tv:
        if any(b != a and (tv_obj[a] & tv_obj[b]) for b in tv):
            kinds[a] = "test"

    # Resolve each REMAINING ambiguous verify/test-with-its-own-noun ('verifyish') sibling-
    # relatively: structural only if it keeps NO deliverable noun once tokens shared with
    # the OTHER tasks are removed (the shared-empty test). "test-add" beside "implement-add-
    # todo" -> structural; "verify-email-address" beside "send-welcome-email" -> FEATURE
    # (own noun "address" remains). The adversarial-pass fix against dropping verify-<feature>.
    for i in range(len(slugs)):
        if kinds[i] == "verifyish":
            others = (set().union(*(all_tokens[j] for j in range(len(slugs)) if j != i))
                      if len(slugs) > 1 else set())
            kinds[i] = _resolve_verifyish(slugs[i], others)

    # The object root nouns of the FEATURE tasks (minus fillers / test-nouns) — what an
    # "add a test FOR <X>" task would reference.
    feature_roots: set[str] = set()
    for slug, kind in zip(slugs, kinds):
        if kind == "feature":
            _, objset, _ = _slug_parts(slug)
            feature_roots |= (objset - _FILLERS - _TEST_NOUNS)

    # Pass 2: reclassify a feature-shaped "add/write a test for <sibling>" task as
    # structural when its non-test tokens reference an existing feature root. Tightly
    # guarded (add/write/create/make verb, NO artifact head-noun) so a real test-tooling
    # deliverable — "add-test-data-generator", "build-test-data-seed-endpoint" — is never
    # mis-dropped (the "test" there is a qualifier of a feature noun, not the intent).
    for i, slug in enumerate(slugs):
        if kinds[i] != "feature":
            continue
        verb, _objset, nf = _slug_parts(slug)
        if verb not in {"add", "write", "create", "make"}:
            continue
        if (nf & _TEST_NOUNS) and not (nf & _ARTIFACT_FEATURE_NOUNS):
            remainder = nf - _TEST_NOUNS
            if remainder and remainder <= feature_roots:
                kinds[i] = "test"

    if not any(k == "feature" for k in kinds):
        # All-structural proposal (implementation implicit) -> ONE representative (prefer a
        # test over a scaffold). Never zero work; never an explosion of meta-tasks.
        rep = next((c for c, k in zip(candidates, kinds) if k == "test"), candidates[0])
        return [rep], False

    survivors: list[dict] = []
    collapsed_test_intent = False
    for cand, kind in zip(candidates, kinds):
        if kind == "feature":
            survivors.append(cand)
        elif kind == "test":
            collapsed_test_intent = True  # acceptance layer owns testing
        # scaffold -> dropped (sub-step folded into the feature it scaffolds)
    if not survivors:  # defensive — the has-feature check above guarantees >=1
        return [candidates[0]], False
    return survivors, collapsed_test_intent


def _is_leaf_goal(idea: str) -> bool:
    """Conservative stop-condition: is the GOAL already ONE coherent unit (a single
    function / endpoint / rule / component)?

    This is the recursion STOP-CONDITION the eventual recursive decompose will call (the
    SDD foundation) — "is this small enough to stop splitting?". It is deliberately NOT
    used as a feature-dropping cap in the single-pass path: the red-team showed that
    capping a leaf-shaped goal to one task wrongly drops genuinely-distinct sibling
    features (``write a linter rule`` -> rule + visitor + fixer). Single-pass right-sizing
    is done entirely by ``_collapse`` (which removes structural/scaffold splits); this
    predicate errs toward False so a multi-unit goal is never a leaf.
    """
    text = (idea or "").strip().lower()
    if not text or len(text.split()) > 14:
        return False
    if _MULTI_UNIT_RE.search(text):
        return False
    return bool(_LEAF_ARTIFACT_RE.search(text))


def _unit_marker_count(idea: str) -> int:
    """Count the independent-unit markers ("and" / "," / ";" / " / ") in a goal — a coarse
    proxy for how many separate user-invoked units it enumerates. Used ONLY to decide whether
    to OFFER a single under-split task to the recursive splitter; the 14B then makes the real
    keep-or-split call. Counts match objects (group-agnostic), so each marker counts once."""
    return sum(1 for _ in _MULTI_UNIT_RE.finditer(idea or ""))


# ---------------------------------------------------------------------------
# M2 W2 (#740) — grammar-constrained plan emission (the #718 xgrammar path)
# ---------------------------------------------------------------------------


def plan_emission_json_schema(*, max_tasks: int = DEFAULT_MAX_TASKS) -> dict:
    """The JSON schema for grammar-constrained plan emission.

    The #718 machinery already proves the substrate: OpenVINO GenAI
    ``StructuredOutputConfig`` composes with speculative decoding + streaming on the
    production pipeline shape (``gpu_inference._build_tool_call_structured_output``
    uses its ``structural_tags_config`` face; THIS schema targets its ``json_schema``
    face — whole-response constraint, since a plan emission IS the response, not a
    triggered tag). The live adapter (an AO-side ``structured_generate_fn`` that sets
    ``gen_config.structured_output_config``) is the driver wiring (Lane A2 / W8);
    this module stays model-free. The caps mirror the cleaning constants above, so a
    constrained emission can never exceed what the ruler would truncate anyway."""
    contract_list = {
        "type": "array",
        "items": {"type": "string", "maxLength": CONTRACT_ITEM_MAX},
        "maxItems": CONTRACT_LIST_MAX,
    }
    return {
        "type": "array",
        "minItems": 1,
        "maxItems": max_tasks,
        "items": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "minLength": 1, "maxLength": 64},
                "prompt": {"type": "string", "minLength": 1},
                "depends_on": {
                    "type": "array",
                    "items": {"type": "string", "maxLength": 64},
                    "maxItems": max_tasks,
                },
                "contract": {
                    "type": "object",
                    "properties": {
                        "creates": contract_list,
                        "exports": contract_list,
                        "notes": {"type": "string", "maxLength": CONTRACT_NOTES_MAX},
                    },
                    "additionalProperties": False,
                },
            },
            "required": ["task", "prompt"],
            "additionalProperties": False,
        },
    }


def _generate_plan_json(
    prompt: str,
    *,
    generate_fn: Callable[[str], str],
    structured_generate_fn: "Callable[[str, str], str] | None",
    max_tasks: int,
) -> tuple[str, bool, str]:
    """One plan emission with the OPTIONAL grammar hook: ``(raw, used_grammar, error)``.

    When *structured_generate_fn* is provided it is tried FIRST — called as
    ``(prompt, json_schema_text)`` for a schema-constrained emission. Fail-soft,
    never a new refusal: an exception, an empty return, or output the tolerant
    parser cannot use falls TRANSPARENTLY back to today's free-text ``generate_fn``
    + regex-parse path, so the hook can only ever improve parse fidelity. With no
    hook the behavior is byte-identical to the pre-W2 call."""
    if structured_generate_fn is not None:
        try:
            raw = structured_generate_fn(
                prompt, json.dumps(plan_emission_json_schema(max_tasks=max_tasks))
            )
        except Exception:  # noqa: BLE001 — the hook must never add a failure mode
            raw = ""
        if raw and _parse_candidates(raw, max_tasks=_PARSE_CEILING):
            return raw, True, ""
    try:
        return generate_fn(prompt), False, ""
    except Exception as exc:  # noqa: BLE001 — a model failure must not crash the dispatch
        return "", False, str(exc)


def _split_oversize_task(
    idea: str,
    single_task: dict,
    repo_target: str,
    *,
    generate_fn: Callable[[str], str],
    structured_generate_fn: "Callable[[str, str], str] | None" = None,
    max_tasks: int,
    max_depth: int,
) -> list[dict] | None:
    """#691 envelope UPPER-bound backstop: re-split a single task the first pass under-split.

    Offers the lone task's prompt to the 14B with the "go finer" :data:`_SPLIT_TEMPLATE`, runs
    the children through the SAME right-sizing ruler (``_collapse`` + ``_ruler``), and returns
    the replacement ONLY on a STRICT improvement (>=2 coherent feature tasks). Returns ``None``
    to keep the original whenever the split is disabled, fails, or does not strictly help — so a
    genuinely-coherent small app (the 14B returns one task) is left untouched. ``max_depth <= 1``
    disables it (today's single-pass behavior); the children are NOT re-split (one extra level
    only). The model failure is swallowed (a split error must never crash or change the plan)."""
    if max_depth <= 1:
        return None
    raw, _used_grammar, _err = _generate_plan_json(
        _SPLIT_TEMPLATE.format(max_tasks=max_tasks, prompt=single_task.get("prompt", "")),
        generate_fn=generate_fn, structured_generate_fn=structured_generate_fn,
        max_tasks=max_tasks,
    )
    if not raw:
        return None
    children = _parse_candidates(raw, max_tasks=_PARSE_CEILING)
    survivors, _ = _collapse(children)
    accepted = _ruler(survivors, repo_target, max_tasks=max_tasks)
    # Strict improvement only: >=2 coherent tasks. One-or-zero means the 14B judged the work a
    # single coherent step (or returned junk) -> keep the original lump (never fewer/equal).
    return accepted if len(accepted) >= 2 else None


# ---------------------------------------------------------------------------
# M2 W5 (#740) — evidence-fed re-decomposition of a consistently-failing task
# ---------------------------------------------------------------------------

#: Hard cap on the failing-evidence block fed back into a planner prompt (plan §10 S3:
#: coder-authored strings reach the planner ONLY structurally extracted + capped).
FAILURE_EVIDENCE_MAX_CHARS = 500

#: Lines worth keeping from gate/oracle output: test identifiers, assertion lines,
#: error classes, exit codes, and the fleet's own RESULT/TESTS/VERIFY signal lines.
_EVIDENCE_LINE_RE = re.compile(
    r"(FAILED|ERROR|AssertionError|assert\b|Traceback|exit(?:\s*code)?[=:\s]\s*\d+"
    r"|RESULT:|TESTS:|VERIFY:|test_[\w.]+|::test|not ok\b|# fail)",
    re.IGNORECASE,
)


def build_failure_evidence(*sources: str, max_chars: int = FAILURE_EVIDENCE_MAX_CHARS) -> str:
    """STRUCTURAL extraction of failing evidence for the re-decompose prompt (§10 S3).

    Coder-authored text (an assertion message IS coder output) must never ride prose
    into the 14B planner's prompt, so this keeps only lines matching the structural
    evidence shapes (test ids, assert/error lines, exit codes, the fleet's signal
    lines), control-strips them, caps each line, dedupes, and caps the whole block.
    Empty input (or nothing structural) ⇒ ``''`` — the caller then feeds no evidence
    block at all rather than inventing one."""
    lines: list[str] = []
    seen: set[str] = set()
    for source in sources:
        for raw in str(source or "").splitlines():
            line = _CTRL_RE.sub(" ", raw).strip()
            if not line or not _EVIDENCE_LINE_RE.search(line):
                continue
            line = line[:200]
            if line in seen:
                continue
            seen.add(line)
            lines.append(line)
    out = "\n".join(lines)
    return out[:max_chars]


#: The failing-evidence context wrapped around a re-decomposed task's prompt. The
#: evidence block is STRUCTURAL (build_failure_evidence) — never raw coder prose.
_FAILURE_CONTEXT_TEMPLATE = (
    "{prompt}\n\n"
    "NOTE: a previous automated attempt at this exact task FAILED its verification. "
    "The structural evidence was:\n{evidence}\n"
    "Break the work into smaller steps that each avoid repeating that failure."
)


def split_failed_task(
    task: dict,
    evidence: str,
    *,
    generate_fn: Callable[[str], str],
    structured_generate_fn: "Callable[[str, str], str] | None" = None,
    max_tasks: int = DEFAULT_MAX_TASKS,
) -> "list[dict] | None":
    """W5 — ONE evidence-fed re-decomposition of a consistently-failing task.

    Reuses the #691 ``_SPLIT_TEMPLATE`` machinery (the proven "go finer" path) with the
    task's prompt AUGMENTED by the structurally-extracted failing evidence (never raw
    coder prose — §10 S3), runs the children through the SAME right-sizing ruler, and
    returns them ONLY on a strict improvement (>=2 coherent tasks). ``None`` keeps the
    original (the caller then parks it — bounded by design; the budget lives in the
    plan's ``redecompose_budget`` and is spent by the CALLER via
    ``plan_graph.spend_redecompose``). A model failure is swallowed (a split error must
    never crash the run — the subtree parks honestly instead)."""
    prompt = str(task.get("prompt", "") or "").strip()
    if not prompt:
        return None
    evidence = build_failure_evidence(evidence)
    seed = (
        _FAILURE_CONTEXT_TEMPLATE.format(prompt=prompt, evidence=evidence)
        if evidence else prompt
    )
    raw, _used_grammar, _err = _generate_plan_json(
        _SPLIT_TEMPLATE.format(max_tasks=max_tasks, prompt=seed),
        generate_fn=generate_fn, structured_generate_fn=structured_generate_fn,
        max_tasks=max_tasks,
    )
    if not raw:
        return None
    children = _parse_candidates(raw, max_tasks=_PARSE_CEILING)
    survivors, _ = _collapse(children)
    accepted = _ruler(survivors, str(task.get("repo", "") or ""), max_tasks=max_tasks)
    return accepted if len(accepted) >= 2 else None


def _ruler(candidates: list[dict], repo_target: str, *, max_tasks: int) -> list[dict]:
    """Deterministic acceptance: well-formed, slugged, deduped, capped. NEVER the model.

    The right-sizing (``_collapse``) has already run; this enforces shape + the final
    ``max_tasks`` cap on the survivors — and RE-MAPS the graph (M2 W2): after collapse,
    dedupe, and the cap, every surviving ``depends_on`` ref must point at a SURVIVING
    sibling slug (refs to collapsed/deduped/capped-away tasks and self-refs are
    removed). The key itself is preserved once the model emitted it — an emptied-out
    ``depends_on: []`` still marks a graph-aware task (an independent root).
    """
    accepted: list[dict] = []
    seen: set[str] = set()
    for cand in candidates:
        task = cand.get("task", "")
        prompt = cand.get("prompt", "")
        if not task or not prompt:
            continue
        slug = slugify_task(task)
        if slug in seen:
            continue
        seen.add(slug)
        entry: dict = {"repo": repo_target, "task": slug, "prompt": prompt}
        if "depends_on" in cand:
            entry["depends_on"] = list(cand.get("depends_on") or [])
        if "contract" in cand:
            entry["contract"] = cand["contract"]
        accepted.append(entry)
        if len(accepted) >= max_tasks:
            break
    survivors = {e["task"] for e in accepted}
    for e in accepted:
        if "depends_on" in e:
            e["depends_on"] = [r for r in e["depends_on"]
                               if r in survivors and r != e["task"]]
    return accepted


def decompose_request(
    idea: str,
    repo: str,
    *,
    generate_fn: Callable[[str], str],
    projects_dir: Path,
    max_tasks: int = DEFAULT_MAX_TASKS,
    max_depth: int = DEFAULT_MAX_DEPTH,
    structured_generate_fn: "Callable[[str, str], str] | None" = None,
) -> DecomposeResult:
    """Decompose *idea* into right-sized fleet tasks for *repo*. Fail-closed + fallback.

    1. Validate *repo* (an existing git repo under *projects_dir*, never BlarAI/
       .openclaw — reuses the engine's ``validate_repo``). Invalid → reject.
    2. Ask the 14B (``generate_fn``) to break the idea into the fewest coherent tasks.
       When *structured_generate_fn* is provided (M2 W2 — an adapter over the #718
       xgrammar ``StructuredOutputConfig`` path, called ``(prompt, json_schema)``),
       the emission is tried grammar-constrained FIRST with a transparent fail-soft
       fallback to the free-text path — never a new refusal.
    3. RIGHT-SIZE: parse generously, ``_collapse`` the structural/scaffold splits, then
       run the DETERMINISTIC ruler (slug + dedupe + cap + graph re-map). A clearly-small
       (leaf) goal is capped to a single task. ≥1 task → use them.
    4. Otherwise FALL BACK to one validated task (the idea as the prompt) — a dispatch
       never silently produces zero work.

    ``max_depth`` is the recursion bound (the SDD foundation): single-pass decomposition
    runs at depth 1; a future recursive decompose keeps a still-too-big node as one
    flagged task at the bound rather than exploding it.
    """
    repo_path = projects_dir / repo
    err = validate_repo(repo_path, projects_dir)
    if err is not None:
        return DecomposeResult(ok=False, message=f"Could not dispatch — {err}.")

    repo_target = str(repo_path)
    idea = (idea or "").strip()
    if not idea:
        return DecomposeResult(ok=False, message="Nothing to dispatch — the idea is empty.")

    raw, used_grammar, gen_error = _generate_plan_json(
        _DECOMPOSE_TEMPLATE.format(max_tasks=max_tasks, idea=idea),
        generate_fn=generate_fn, structured_generate_fn=structured_generate_fn,
        max_tasks=max_tasks,
    )

    candidates = _parse_candidates(raw, max_tasks=_PARSE_CEILING)
    # #740 live-verify diagnostic: make the decompose outcome visible in the AO log so a
    # minimal-fallback root cause (malformed JSON / no array / truncation / think block) is
    # never invisible again.
    logger.info(
        "decompose: raw_len=%d used_grammar=%s parsed_candidates=%d gen_error=%r",
        len(raw or ""), used_grammar, len(candidates), gen_error,
    )
    if not candidates:
        logger.warning("decompose: NO candidates parsed — raw head: %r", (raw or "")[:800])
    # #740/#748 live diagnostic (env-gated; zero-cost unset): raw-output dump — bypasses the AO
    # logging config, which does not emit this module's logger to stdout. Set
    # BLARAI_DECOMPOSE_DEBUG=<path> to capture. This dump + its gpu_inference twins localized the
    # #748 three-defect stack (swallowed xgrammar crash / tool-bait / tail bracket slip).
    try:
        import os as _os
        _dbg = _os.environ.get("BLARAI_DECOMPOSE_DEBUG")
        if _dbg:
            with open(_dbg, "a", encoding="utf-8") as _f:
                _f.write(f"\n=== decompose raw (len={len(raw or '')} cands={len(candidates)} "
                         f"grammar={used_grammar} err={gen_error!r}) ===\n{raw or ''}\n")
    except Exception:
        pass
    # Right-size: _collapse removes the structural/scaffold/per-test-case splits, leaving
    # the fewest coherent FEATURE tasks (a one-function goal -> 1). The ruler then enforces
    # the max_tasks cap. The leaf stop-condition (_is_leaf_goal) is the recursion-bound
    # foundation, NOT a single-pass cap — capping would drop distinct sibling features.
    survivors, collapsed_test_intent = _collapse(candidates)
    tasks = _ruler(survivors, repo_target, max_tasks=max_tasks)

    # #691 envelope UPPER bound: a clearly-multi-unit goal that collapsed to a SINGLE task was
    # under-split into one oversized run. Offer that lone task to the bounded recursive splitter;
    # it replaces the lump only on a strict improvement (>=2 coherent tasks), so a coherent small
    # app stays one task. Leaf goals and goals below the unit-marker threshold are never offered
    # (false-split is worse than a missed split; the strengthened prompt is the primary lever).
    split_oversize = False
    if (
        len(tasks) == 1
        and not _is_leaf_goal(idea)
        and _unit_marker_count(idea) >= _OVERSIZE_MIN_MARKERS
    ):
        replacement = _split_oversize_task(
            idea, tasks[0], repo_target,
            generate_fn=generate_fn, structured_generate_fn=structured_generate_fn,
            max_tasks=max_tasks, max_depth=max_depth,
        )
        if replacement:
            tasks = replacement
            split_oversize = True

    if tasks:
        msg = f"Decomposed into {len(tasks)} task(s)."
        if split_oversize:
            msg += " (envelope: split an oversized single task into gated steps.)"
        return DecomposeResult(
            ok=True,
            tasks=tasks,
            collapsed_test_intent=collapsed_test_intent,
            split_oversize=split_oversize,
            used_grammar=used_grammar,
            message=msg,
        )

    # Fallback: a single validated task (the increment-1 framing). Never zero work.
    fallback = [{"repo": repo_target, "task": slugify_task(idea), "prompt": idea}]
    note = f"model error ({gen_error})" if gen_error else "model output unusable"
    return DecomposeResult(
        ok=True, tasks=fallback, fell_back=True,
        message=f"Decomposition fell back to a single task ({note}).",
    )
