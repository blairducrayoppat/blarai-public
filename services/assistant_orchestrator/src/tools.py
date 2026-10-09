"""
Tool Registry — Assistant Orchestrator
========================================
Provides the tool-call loop with a minimal, pure tool registry.

v3 (2026-07-01, #718) migrates the tool-call wire format to Qwen3's NATIVE
trained format — a JSON payload inside the ``<tool_call>`` tags:

    <tool_call>{"name": "calculate", "arguments": {"expression": "2*(3+4)"}}</tool_call>

``parse_tool_call`` parses that payload with a strict ``json.loads`` +
schema validation (fail-closed to "no tool call" with a logged deterministic
fingerprint on malformed input), and canonicalises the arguments to a
compact, key-sorted JSON string — the deterministic form the #570 PA
adjudication and ``execute`` both consume.

The legacy homemade forms ``<tool_call>NAME</tool_call>`` /
``<tool_call>NAME(ARGS)</tool_call>`` (v1 2026-05, v2 2026-06-02) were
RETIRED on 2026-07-02 (#718 LA decision D3): the JSON payload is the ONLY
accepted form. A legacy-shaped payload now lands on the standard fail-closed
no-tool-call path (dropped with a logged deterministic fingerprint), the
same as any other malformed payload. The transition fallback ran with zero
live hits (launcher.log evidence) before removal.

Shipped tools:
  - get_current_time        — local date-time string
  - get_current_date        — local date only (no time)
  - get_day_of_week         — current day of week
  - calculate               — safe arithmetic evaluator
                              (numbers, +, -, *, /, %, **, parens, unary -)
  - generate_image          — UC-010 directive shim (points at /imagine)
  - search_knowledge        — #719 GUARDED local knowledge-bank retrieval
                              (runner seam; AO registers it at start)
  - web_search              — #719 GUARDED web retrieval delegate
                              (runner seam; registration is CONDITIONAL,
                              default-off, fail-closed — the AO entrypoint
                              registers the ADR-024 W4 LiveKagiAdapter runner
                              ONLY when [web_search].enabled is true AND the
                              DPAPI-sealed Kagi key loads; the shipped
                              default is structurally dormant with a
                              deterministic disabled notice)

No network, no filesystem, no exec/eval of untrusted strings inside this
module. The calculate tool walks an AST and only permits arithmetic nodes —
there is no path from a model-supplied EXPR to arbitrary Python execution.
The two #719 retrieval tools NEVER construct their own clients: they only
delegate to a runner the host service explicitly registered (and no
production code registers a web-search runner while egress governance is
welded). Retrieval results are size-capped here (RETRIEVAL_RESULT_MAX_CHARS)
and provenance-declared (``result_provenance``) so the AO tool loop grounds
them through the untrusted-content machinery — never splices them raw.
"""

from __future__ import annotations

import ast
import hashlib
import json
import logging
import operator as _op
import re
from datetime import datetime
from enum import Enum
from typing import Callable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def _get_current_time() -> str:
    """Return the current local date-time as a human-readable string."""
    return datetime.now().strftime("%A, %Y-%m-%d %H:%M")


def _get_current_date() -> str:
    """Return the current local date (no time) as a human-readable string."""
    return datetime.now().strftime("%A, %B %d, %Y")


def _get_day_of_week() -> str:
    """Return the current local day of the week."""
    return datetime.now().strftime("%A")


# Safe arithmetic evaluator. Only the listed AST node types and binary
# operators are permitted; any other syntactic construct (Name, Call,
# Attribute, Subscript, etc.) raises a ValueError. There is no path
# from a model-supplied string to arbitrary Python execution.
_BIN_OPS: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: _op.add,
    ast.Sub: _op.sub,
    ast.Mult: _op.mul,
    ast.Div: _op.truediv,
    ast.FloorDiv: _op.floordiv,
    ast.Mod: _op.mod,
    ast.Pow: _op.pow,
}
_UNARY_OPS: dict[type[ast.unaryop], Callable[[float], float]] = {
    ast.UAdd: _op.pos,
    ast.USub: _op.neg,
}


def _eval_arith(node: ast.AST) -> float:
    """Recursively evaluate an arithmetic AST node, refusing anything else."""
    if isinstance(node, ast.Expression):
        return _eval_arith(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_eval_arith(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        left = _eval_arith(node.left)
        right = _eval_arith(node.right)
        return _BIN_OPS[type(node.op)](left, right)
    raise ValueError(
        f"Unsupported expression element: {type(node).__name__}. "
        "Only numbers and the operators + - * / // % ** with parens are allowed."
    )


def _generate_image(prompt: str) -> str:
    """UC-010 (ADR-033) in-loop tool shim — directs the user to ``/imagine``.

    GUARDED, never-raising (the ``_calculate`` contract). Actual generation runs
    in the AO's IMAGE_GEN_REQUEST handler off the gateway ``/imagine`` command
    (which owns the session id + the at-rest cipher needed to store the result);
    the in-loop tool form has neither, so it returns a directive string rather
    than performing the heavy generate inside the conversational loop.

    DORMANT-aware: when image generation is unavailable (the shipped default —
    disabled or model absent) it returns the clear "unavailable" notice with NO
    load attempted; when available it points the user at ``/imagine``. Returns a
    string in every case (never raises, never a model load from here).
    """
    from shared.inference import image_gen

    requested = prompt.strip()
    if not image_gen.is_available():
        return (
            "Image generation is unavailable (the capability is disabled or the "
            "model is not installed)."
        )
    hint = f' "{requested}"' if requested else ""
    return (
        f"To generate an image, use the /imagine command, e.g. `/imagine{hint or ' <prompt>'}`. "
        "Image generation runs locally and the result appears inline."
    )


def _calculate(expression: str) -> str:
    """Safely evaluate a basic arithmetic expression and return its result."""
    expr = expression.strip()
    if not expr:
        return "calculate: no expression provided"
    try:
        tree = ast.parse(expr, mode="eval")
        value = _eval_arith(tree)
    except SyntaxError as exc:
        return f"calculate: could not parse '{expression}' — {exc.msg}"
    except ZeroDivisionError:
        return f"calculate: division by zero in '{expression}'"
    except ValueError as exc:
        return f"calculate: {exc}"
    except Exception as exc:  # noqa: BLE001 — last-resort guard for unknown numeric edges
        return f"calculate: error evaluating '{expression}' — {exc}"
    # Clean integer results render without trailing ".0".
    if value.is_integer():
        return str(int(value))
    return str(value)


# ---------------------------------------------------------------------------
# Retrieval tools (#719) — search_knowledge + web_search
# ---------------------------------------------------------------------------
# Both are GUARDED-tier delegates over a RUNNER SEAM: the tool body holds no
# store handle and no network client; it only calls a runner the host service
# explicitly registered. The AO entrypoint registers the knowledge runner at
# start() (bound over its EncryptedKnowledgeBank retrieval — the SAME surface
# the per-prompt auto-recall uses). The web-search runner registration is
# CONDITIONAL, DEFAULT-OFF, FAIL-CLOSED (#719 Part B, the reviewed change
# that superseded the earlier structural-absence lock): the AO entrypoint's
# _maybe_register_web_search registers the ADR-024 W4 LiveKagiAdapter runner
# ONLY when [web_search].enabled is true (shipped false) AND the
# operator-provisioned DPAPI-sealed Kagi key loads; either missing keeps
# web_search structurally dormant returning WEB_SEARCH_DISABLED_NOTICE. Even
# when registered, egress binds at RULE 3 + the ONE deterministic egress
# allowlist — at the tool loop (the D4 dispatch CAR carries the real Kagi
# endpoint URL) AND at the egress door — so an empty allowlist denies every
# search until the ADR-027 Am.1 LA ceremony populates it.
#
# Every non-notice result is capped at RETRIEVAL_RESULT_MAX_CHARS and, in the
# AO tool loop, grounded through context_manager.add_grounded_context with the
# provenance ``result_provenance`` declares — search_knowledge results are
# UNTRUSTED_KNOWLEDGE (ADR-023 Amendment 2, #664), web_search results are
# UNTRUSTED_WEB (ADR-023 Amendment 3, #719 — action-locked + datamarked but
# Stage-5-leak-exempt, so a faithful relay of public results is not held).
# The deterministic notices below are system-authored
# strings carrying NO retrieved content; ``is_retrieval_notice`` identifies
# them by exact full-string match so the loop's plain-note path (no grounding,
# no Layer-3 lock flip) can never be reached by crafted retrieved content —
# content that forged a notice byte-for-byte would have suppressed itself.

#: Deterministic size cap (characters) applied to every retrieval-tool result
#: BEFORE it reaches the loop/grounding. 4000 chars ≈ 1000 tokens under the
#: repo's len//4 approximation — 25% of the AO's 4096-token context budget,
#: comparable to the per-prompt auto-recall budget (retrieve_k=4 chunks) and
#: small enough that one retrieval can never evict the conversation itself.
RETRIEVAL_RESULT_MAX_CHARS: int = 4000

#: Explicit truncation marker appended when a result exceeds the cap. The
#: capped result's TOTAL length (content + marker) is exactly
#: RETRIEVAL_RESULT_MAX_CHARS, deterministically.
RETRIEVAL_TRUNCATION_MARKER: str = (
    "\n[... truncated: retrieval result exceeded the 4000-character tool cap]"
)

# search_knowledge max_results bounds (clamped fail-safe in the tool body;
# the JSON schema documents them in prose — numeric-bound keywords are kept
# OUT of the schema so the xgrammar structural-tags builder never sees a
# keyword an older xgrammar might reject at construction time).
SEARCH_KNOWLEDGE_DEFAULT_RESULTS: int = 4
SEARCH_KNOWLEDGE_MIN_RESULTS: int = 1
SEARCH_KNOWLEDGE_MAX_RESULTS: int = 8

# Deterministic system-authored notices (exact strings — see module note).
SEARCH_KNOWLEDGE_UNAVAILABLE_NOTICE: str = (
    "Knowledge search is unavailable — the knowledge bank is not enabled on "
    "this system."
)
SEARCH_KNOWLEDGE_EMPTY_QUERY_NOTICE: str = "search_knowledge: no query provided."

# #1616 search_reference notices. Same deterministic-notice contract as the
# knowledge tool: a dormant, absent or erroring corpus yields a fixed system
# string, never an exception into the loop and never a silent empty result
# the model would read as "the encyclopedia has nothing on this".
SEARCH_REFERENCE_UNAVAILABLE_NOTICE: str = (
    "Reference search is unavailable — the offline reference corpus is not "
    "enabled on this system."
)
SEARCH_REFERENCE_EMPTY_QUERY_NOTICE: str = "search_reference: no query provided."
SEARCH_REFERENCE_NO_RESULTS_NOTICE: str = (
    "search_reference: the reference corpus has no passage matching that query."
)
SEARCH_REFERENCE_ERROR_NOTICE: str = (
    "search_reference: the reference corpus could not be read."
)
SEARCH_KNOWLEDGE_NO_RESULTS_NOTICE: str = (
    "No matching content found in the knowledge bank for that query."
)
SEARCH_KNOWLEDGE_ERROR_NOTICE: str = (
    "Knowledge search failed — the knowledge bank could not be queried."
)
WEB_SEARCH_DISABLED_NOTICE: str = (
    "Web search is unavailable — external network access is not enabled on "
    "this system."
)
WEB_SEARCH_EMPTY_QUERY_NOTICE: str = "web_search: no query provided."
WEB_SEARCH_ERROR_NOTICE: str = "Web search failed — no results could be retrieved."

#: Every deterministic retrieval-tool notice. Exact-membership is the loop's
#: test for "system-authored, carries no retrieved content" — anything else a
#: retrieval tool returns is grounded as untrusted content (fail-closed).
RETRIEVAL_NOTICES: frozenset[str] = frozenset({
    SEARCH_KNOWLEDGE_UNAVAILABLE_NOTICE,
    SEARCH_KNOWLEDGE_EMPTY_QUERY_NOTICE,
    SEARCH_KNOWLEDGE_NO_RESULTS_NOTICE,
    SEARCH_KNOWLEDGE_ERROR_NOTICE,
    WEB_SEARCH_DISABLED_NOTICE,
    WEB_SEARCH_EMPTY_QUERY_NOTICE,
    WEB_SEARCH_ERROR_NOTICE,
    # #1616. Omitting these made a notice look like retrieved CONTENT, which
    # put the turn on the grounded path while reporting that nothing was found.
    SEARCH_REFERENCE_UNAVAILABLE_NOTICE,
    SEARCH_REFERENCE_EMPTY_QUERY_NOTICE,
    SEARCH_REFERENCE_NO_RESULTS_NOTICE,
    SEARCH_REFERENCE_ERROR_NOTICE,
})


def is_retrieval_notice(result: str) -> bool:
    """True iff *result* is one of the deterministic retrieval-tool notices.

    Exact full-string membership — never a prefix/substring test, so retrieved
    content cannot smuggle itself onto the ungrounded path by embedding a
    notice (a byte-identical forgery contains no retrieved content at all).
    """
    return result in RETRIEVAL_NOTICES


def _cap_retrieval_result(result: str) -> str:
    """Deterministically cap a retrieval result at RETRIEVAL_RESULT_MAX_CHARS.

    Over-cap results are truncated so that content + RETRIEVAL_TRUNCATION_MARKER
    is exactly the cap; at-or-under-cap results pass through unchanged.
    """
    if len(result) <= RETRIEVAL_RESULT_MAX_CHARS:
        return result
    keep = RETRIEVAL_RESULT_MAX_CHARS - len(RETRIEVAL_TRUNCATION_MARKER)
    return result[:keep] + RETRIEVAL_TRUNCATION_MARKER


# Runner seams. Module-level singletons (the escalation_consent verifier
# registry pattern): the host service registers/clears; the tool bodies only
# read. Registration is an explicit code-reviewed act, never config-driven.
_SEARCH_KNOWLEDGE_RUNNER: Callable[[str, int], str] | None = None
#: #1616 reference-corpus runner. None until the AO registers one,
#: which it does only when the capability is enabled AND its store
#: verified — so None is the shipped default.
_SEARCH_REFERENCE_RUNNER: Callable[[str, int], str] | None = None
_WEB_SEARCH_RUNNER: Callable[[str], str] | None = None


def register_search_knowledge_runner(runner: Callable[[str, int], str]) -> None:
    """Register the live knowledge-search runner (AO entrypoint, at start()).

    Contract: ``runner(query, max_results) -> str`` — the joined, labelled
    retrieval text ("" when nothing matched). The AO binds this over the SAME
    ``_knowledge_retrieve`` labelling the per-prompt auto-recall uses, so the
    tool and the auto-recall present knowledge identically. Re-registration
    replaces (logged) — one live bank per process.
    """
    global _SEARCH_KNOWLEDGE_RUNNER
    if _SEARCH_KNOWLEDGE_RUNNER is not None:
        logger.info("search_knowledge runner replaced (re-registration).")
    _SEARCH_KNOWLEDGE_RUNNER = runner


def clear_search_knowledge_runner() -> None:
    """Deregister the knowledge-search runner (AO stop(); tests)."""
    global _SEARCH_KNOWLEDGE_RUNNER
    _SEARCH_KNOWLEDGE_RUNNER = None


def register_search_reference_runner(runner: Callable[[str, int], str]) -> None:
    """Register the live reference-corpus runner (AO entrypoint, at start()).

    Contract: ``runner(query, max_results) -> str`` — joined, labelled passage
    text with its citation ("" when nothing matched). Registration is the
    STRUCTURAL dormancy switch for this capability: with the config flag false
    the AO never calls this, so no store path exists to reach. That is
    stronger than a runtime check on a flag, which is why it is done this way
    (security principle 4 — structural absence over configuration).
    """
    global _SEARCH_REFERENCE_RUNNER
    if _SEARCH_REFERENCE_RUNNER is not None:
        logger.info("search_reference runner replaced (re-registration).")
    _SEARCH_REFERENCE_RUNNER = runner


def clear_search_reference_runner() -> None:
    """Deregister the reference-corpus runner (AO stop(); tests)."""
    global _SEARCH_REFERENCE_RUNNER
    _SEARCH_REFERENCE_RUNNER = None


def register_web_search_runner(runner: Callable[[str], str]) -> None:
    """Register a live web-search runner (conditional, default-off — #719 Part B).

    Contract: ``runner(query) -> str`` — the shaped results text ("" on no
    results). The ONLY production caller is the AO entrypoint's
    ``_maybe_register_web_search`` (a source-scan test locks that), which
    registers ``make_web_search_runner(LiveKagiAdapter(...))`` ONLY when
    ``[web_search].enabled`` is true AND the DPAPI-sealed Kagi key loads —
    either missing keeps this seam empty (structurally dormant). The live
    adapter delegates to the ONE egress door
    (``shared.security.guarded_fetch.fetch_external``), where the real URL is
    PA-adjudicated and RULE 3 + the (empty) egress allowlist deny every
    external host until ADR-027 Am.1 populates it; the D4 dispatch CAR
    enforces the same allowlist at the tool loop. Tests also register fakes
    here to exercise the grounding path without any network; the repo-wide
    exactly-one-network-client invariant
    (tests/security/test_no_external_egress.py) holds regardless.
    """
    global _WEB_SEARCH_RUNNER
    if _WEB_SEARCH_RUNNER is not None:
        logger.info("web_search runner replaced (re-registration).")
    _WEB_SEARCH_RUNNER = runner


def clear_web_search_runner() -> None:
    """Deregister the web-search runner (tests; defensive symmetry)."""
    global _WEB_SEARCH_RUNNER
    _WEB_SEARCH_RUNNER = None


def _parse_search_knowledge_args(args: str) -> tuple[str, int]:
    """Extract ``(query, max_results)`` from a search_knowledge args string.

    Canonical-JSON args (the native path) yield the ``query`` string and a
    clamped ``max_results`` (SEARCH_KNOWLEDGE_MIN_RESULTS..MAX_RESULTS,
    default SEARCH_KNOWLEDGE_DEFAULT_RESULTS — out-of-range values are
    clamped fail-safe, never refused). A non-JSON bare string (direct
    ``execute`` callers) is treated whole as the query with the default
    budget.
    """
    stripped = args.strip()
    query = stripped
    max_results = SEARCH_KNOWLEDGE_DEFAULT_RESULTS
    if stripped.startswith("{"):
        try:
            parsed = json.loads(stripped)
        except (json.JSONDecodeError, ValueError):
            parsed = None
        if isinstance(parsed, dict):
            raw_query = parsed.get("query", "")
            query = raw_query if isinstance(raw_query, str) else ""
            raw_max = parsed.get("max_results", SEARCH_KNOWLEDGE_DEFAULT_RESULTS)
            if isinstance(raw_max, int) and not isinstance(raw_max, bool):
                max_results = raw_max
    max_results = max(
        SEARCH_KNOWLEDGE_MIN_RESULTS,
        min(SEARCH_KNOWLEDGE_MAX_RESULTS, max_results),
    )
    return query.strip(), max_results


def _search_knowledge(args: str) -> str:
    """#719 GUARDED local knowledge-bank retrieval — never-raising.

    Decision chain the dispatch of this tool has already passed (in loop
    order): (1) pgov.TOOL_CALL_ALLOWLIST membership, (2) the Layer-3
    untrusted-content lock (GUARDED: refused without /trust when the session
    holds untrusted-provenance content — including content a PRIOR retrieval
    grounded), (3) the #570 PA deterministic adjudication over the dispatch
    CAR (``tool:search_knowledge`` + canonical args — injection-shaped args
    are denied by the deterministic rules). This body then delegates to the
    registered runner; the AO loop grounds any non-notice result as
    UNTRUSTED_KNOWLEDGE (ADR-023 Amendment 2: retrieval never promotes bank
    content into the trust boundary — it trips the action-lock and is
    datamarked, exempt only from the Stage-5 leakage feed).

    Fail-closed and never-raising: no runner (bank disabled/absent), an
    erroring runner, or an empty query each return a deterministic notice.
    Results are capped at RETRIEVAL_RESULT_MAX_CHARS.
    """
    query, max_results = _parse_search_knowledge_args(args)
    if not query:
        return SEARCH_KNOWLEDGE_EMPTY_QUERY_NOTICE
    runner = _SEARCH_KNOWLEDGE_RUNNER
    if runner is None:
        return SEARCH_KNOWLEDGE_UNAVAILABLE_NOTICE
    try:
        result = runner(query, max_results)
    except Exception as exc:  # noqa: BLE001 — never an exception into the loop
        logger.error("search_knowledge runner failed: %s", exc)
        return SEARCH_KNOWLEDGE_ERROR_NOTICE
    if not isinstance(result, str) or not result.strip():
        return SEARCH_KNOWLEDGE_NO_RESULTS_NOTICE
    return _cap_retrieval_result(result)


def _search_reference(args: str) -> str:
    """#1616 GUARDED offline reference-corpus retrieval — never-raising.

    Same decision chain as ``search_knowledge`` before this body runs:
    allowlist membership, the Layer-3 untrusted-content lock, then the #570 PA
    deterministic adjudication over the dispatch CAR. This body delegates to
    the registered runner; the AO loop grounds any non-notice result as
    UNTRUSTED_CORPUS (ADR-023 Amendment 5) — action-locked and datamarked, so
    an injection hidden in a vandalised encyclopedia article still cannot fire
    a tool, and exempt only from the Stage-5 leakage feed.

    Fail-closed and never-raising: no runner (capability dormant or the store
    absent/unverified), an erroring runner, or an empty query each return a
    deterministic notice rather than an empty string, because an empty string
    reads to the model as "the corpus covers nothing here" — a silent,
    confident falsehood about coverage.
    """
    query, max_results = _parse_search_knowledge_args(args)
    if not query:
        return SEARCH_REFERENCE_EMPTY_QUERY_NOTICE
    runner = _SEARCH_REFERENCE_RUNNER
    if runner is None:
        return SEARCH_REFERENCE_UNAVAILABLE_NOTICE
    try:
        result = runner(query, max_results)
    except Exception as exc:  # noqa: BLE001 — never an exception into the loop
        logger.error("search_reference runner failed: %s", exc)
        return SEARCH_REFERENCE_ERROR_NOTICE
    if not isinstance(result, str) or not result.strip():
        return SEARCH_REFERENCE_NO_RESULTS_NOTICE
    return _cap_retrieval_result(result)


def _web_search(query: str) -> str:
    """#719 GUARDED web retrieval delegate — never-raising, dormant today.

    What refuses a web_search call TODAY, in loop order:
      1. pgov.TOOL_CALL_ALLOWLIST — web_search IS listed, so this layer passes
         (listing is what lets the layers below own the refusal).
      2. Layer-3 untrusted-content lock — GUARDED tier: refused without
         /trust whenever the session holds untrusted-provenance content.
      3. #570 PA deterministic adjudication — D4 (#719 Part B): the dispatch
         CAR carries the REAL search endpoint URL (KAGI_SEARCH_ENDPOINT), so
         RULE 3 (DENY_EXTERNAL_NETWORK) + the deterministic egress allowlist
         DO fire at this seam — with the allowlist EMPTY (the shipped
         posture) every web_search dispatch is DENIED here (golden case
         gov-adj-008 pins this boundary; gov-pf-007 pins the same denial of
         the raw endpoint). The deterministic rules also screen the ARGS
         (authority-claim/exfil-shaped queries are DENIED regardless).
      4. THIS body — the runner registration is CONDITIONAL, DEFAULT-OFF,
         FAIL-CLOSED ([web_search].enabled shipped false AND the DPAPI-sealed
         Kagi key must load; the AO's _maybe_register_web_search is the only
         production registrar), so with the shipped config every call returns
         WEB_SEARCH_DISABLED_NOTICE: a deterministic, user-comprehensible
         tool result, never an exception into the loop.
      5. (Defense-in-depth, beyond this module) — even a registered runner
         cannot reach the network: the only sanctioned HTTP path is the
         egress-guarded door, where the REAL URL is PA-adjudicated and RULE 3
         + the SAME (empty) egress allowlist deny every external host until
         the LA populates it (ADR-027 Am.1 — ONE allowlist source for the
         loop and the door), and the repo-wide exactly-one-network-client
         invariant is test-enforced.

    When a runner IS registered (tests today; the LA go-live ceremony later),
    the result is labelled, capped at RETRIEVAL_RESULT_MAX_CHARS, and
    grounded by the AO loop as UNTRUSTED_WEB (ADR-023 Amendment 3, #719) —
    action-locked + datamarked (an injected instruction in a result still
    cannot fire a subsequent tool) but EXEMPT from the Stage-5 cosine leakage
    feed, so a faithful answer relaying the public results the operator asked
    for is not held as a false-positive leak. (``/external`` pasted content
    stays UNTRUSTED_EXTERNAL and remains screened — the carve-out is
    web-search-specific.)
    """
    q = query.strip()
    if not q:
        return WEB_SEARCH_EMPTY_QUERY_NOTICE
    runner = _WEB_SEARCH_RUNNER
    if runner is None:
        return WEB_SEARCH_DISABLED_NOTICE
    try:
        answer = runner(q)
    except Exception as exc:  # noqa: BLE001 — never an exception into the loop
        logger.error("web_search runner failed: %s", exc)
        return WEB_SEARCH_ERROR_NOTICE
    if not isinstance(answer, str) or not answer.strip():
        return WEB_SEARCH_ERROR_NOTICE
    return _cap_retrieval_result(f"[Web search results for: '{q}']\n{answer}")


# ---------------------------------------------------------------------------
# propose_preference (#770 M2 W1) — a DRAFT surface, never a store write
# ---------------------------------------------------------------------------
# The 14B may PROPOSE a standing preference mid-conversation; the operator sees a
# confirm card and the write happens ONLY when the operator types/clicks
# /remember-confirm, which rides the existing operator preference write door (P8 preserved
# STRUCTURALLY — study §5.1 source isolation between the proposal channel and the
# write channel). This tool is REGISTERED so the model can call it (schema +
# allowlist + #570 per-dispatch PA adjudication + GUARDED risk tier + lock-exempt
# so it can fire under untrusted content per D-1(a) — the untrusted-context card
# FLAG is the weak-signal defense, not a lock that would kill legitimate captures
# in knowledge-heavy sessions). Its ACTUAL handling is session-aware and lives in
# the AO tool loop (entrypoint._handle_propose_preference: reads the store for the
# P5 add-vs-retract/replace decision, stages the verbatim bytes, streams the
# card). This registry body is therefore a FAIL-CLOSED directive notice — never
# the production path: the loop intercepts propose_preference BEFORE tools.execute
# (test_propose_preference_intercepted_before_execute locks that), and a direct
# execute() (a stray caller/test) gets the notice, never a store write.
PROPOSE_PREFERENCE_DIRECT_NOTICE: str = (
    "Preference proposals are shown to you as a confirm card by the assistant; "
    "there is nothing to run here. Reply /remember to save a preference directly."
)


def _propose_preference(args: str) -> str:
    """DORMANT registry body — see the section note. The real, session-aware
    proposal handling is the AO tool loop's ``_handle_propose_preference``; this
    body is reached only by a direct ``execute()`` (never the production path)
    and returns a deterministic notice, never a store write."""
    return PROPOSE_PREFERENCE_DIRECT_NOTICE


# ---------------------------------------------------------------------------
# curate_knowledge (#1567) — the first tool to declare a dry run. DORMANT.
# ---------------------------------------------------------------------------
# The only action in BlarAI whose effect is BOTH irreversible AND not already
# described by its arguments at the approval prompt. `secure_delete=ON` zeroes
# the freed pages; there is no undo. The argument is a SELECTOR and the effect
# is a SET, and nobody can compute the set from the selector — which is the
# condition that makes a rehearsal worth having rather than ceremony.
#
# DORMANT by the RUNNER SEAM, not only by a flag. With no runner registered the
# body returns a deterministic notice and the knowledge bank is never reached:
# there is no code path from this tool to a delete until the AO registers one at
# startup, behind its config flag (`security_by_design` 4 — the strongest
# dormancy is the path that is not there).

CURATE_KNOWLEDGE_MAX_MATCHES: int = 200
"""Refuse a match set larger than this — never truncate it.

Truncating a destructive set would delete a different set than the one the
operator was shown, silently, and the part it kept would be whichever rows
sorted first. A set too large to show is a request to reformulate."""

CURATE_ACTIONS: frozenset[str] = frozenset({"delete", "mark_saved"})
"""The verbs, reusing the bank's existing vocabulary. No new ones."""

_CURATE_SOURCE_TYPES: frozenset[str] = frozenset({"url", "file", "paste"})

#: EXTENDED ISO only, anchored. Shape FIRST, then calendar validity -- neither
#: alone is enough, and each was tried alone and failed.
#:
#: The regex alone accepted ``9999-99-99``, which is not a date and sorts above
#: every stored timestamp, so ``created_before`` with it selected the entire
#: approved bank.
#:
#: ``fromisoformat`` alone accepts ISO BASIC format and week dates --
#: ``20260101T000000`` and ``2026-W01-1`` -- and on the stored
#: ``2026-09-21T03:16:23.000982+00:00`` under a binary collation ``'0'`` and
#: ``'W'`` both sort ABOVE ``'-'``, so those select the whole bank too. Worse,
#: ``20260101T000000`` and ``2026-01-01`` are the SAME INSTANT and gave opposite
#: destructive sets, which is the property this was supposed to eliminate.
_ISO_EXTENDED: re.Pattern[str] = re.compile(
    r"^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2})?)?$"
)


def _is_iso_timestamp(value: str) -> bool:
    """True iff ``value`` is a REAL date in the one spelling this accepts.

    One spelling, one meaning: the stored form is extended ISO, so a selector
    must be too. A space separator, basic format, a week date, a trailing ``Z``
    and an offset are all refused -- not because they are malformed, but because
    each sorts differently against the stored column and would select a
    different set for the same instant.
    """
    if not _ISO_EXTENDED.match(value):
        return False
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


CURATE_KNOWLEDGE_UNAVAILABLE_NOTICE: str = (
    "curate_knowledge: knowledge curation is not enabled on this system."
)
CURATE_KNOWLEDGE_NO_SELECTOR_NOTICE: str = (
    "curate_knowledge: no selector given. Name a source, a type or a date range "
    "— a curation request with no selector matches nothing, never everything."
)
CURATE_KNOWLEDGE_BAD_ACTION_NOTICE: str = (
    "curate_knowledge: unknown action. Use 'delete' or 'mark_saved'."
)
CURATE_KNOWLEDGE_BAD_ARGS_NOTICE: str = (
    "curate_knowledge: arguments could not be read. Nothing was changed."
)

_CURATE_KNOWLEDGE_RUNNER: Callable[[str], str] | None = None


def register_curate_knowledge_runner(runner: Callable[[str], str]) -> None:
    """Wire the tool to a real knowledge bank — a GO-LIVE step (#1567).

    Not called at import. Until the AO calls this behind its config flag, the
    tool body below returns a notice and no delete path exists.
    """
    global _CURATE_KNOWLEDGE_RUNNER
    if not callable(runner):
        raise TypeError("curate_knowledge runner must be callable")
    _CURATE_KNOWLEDGE_RUNNER = runner


def clear_curate_knowledge_runner() -> None:
    """Unregister the runner, restoring the dormant default."""
    global _CURATE_KNOWLEDGE_RUNNER
    _CURATE_KNOWLEDGE_RUNNER = None


def parse_curate_args(args: str) -> dict[str, str]:
    """Validate curation arguments BEFORE any store is consulted (#1567).

    Anchored validation at the boundary: a forged or malformed request dies
    here, not at the bank (`security_by_design` 7).

    Returns:
        The normalised selector, or ``{}`` when the request must be refused.
        An empty result is always a refusal — never "match everything".
    """
    try:
        parsed = json.loads(args) if args.strip() else {}
    except (ValueError, TypeError):
        return {}
    if not isinstance(parsed, dict):
        return {}

    action = str(parsed.get("action", "")).strip()
    if action not in CURATE_ACTIONS:
        return {}

    selector: dict[str, str] = {"action": action}
    source_ref = str(parsed.get("source_ref", "") or "").strip()
    source_type = str(parsed.get("source_type", "") or "").strip()
    before = str(parsed.get("created_before", "") or "").strip()
    after = str(parsed.get("created_after", "") or "").strip()

    if source_type and source_type not in _CURATE_SOURCE_TYPES:
        return {}
    for stamp in (before, after):
        if stamp and not _is_iso_timestamp(stamp):
            return {}

    if not (source_ref or source_type or before or after):
        return {}

    if source_ref:
        selector["source_ref"] = source_ref
    if source_type:
        selector["source_type"] = source_type
    if before:
        selector["created_before"] = before
    if after:
        selector["created_after"] = after
    return selector


def curate_action_needs_rehearsal(args: str) -> bool:
    """True iff these arguments name the irreversible action (#1567 design 2/3).

    ``delete`` always rehearses; ``mark_saved`` is reversible and routes
    normally. Fail-closed on anything unreadable: arguments that cannot be
    parsed are treated as needing a rehearsal, because the alternative is
    executing something nobody could describe.
    """
    try:
        parsed = json.loads(args) if args.strip() else {}
        if not isinstance(parsed, dict):
            return True
        return str(parsed.get("action", "")).strip() != "mark_saved"
    except (ValueError, TypeError):
        return True


def _curate_knowledge(args: str) -> str:
    """Registry body — delegates to the registered runner, or refuses."""
    if _CURATE_KNOWLEDGE_RUNNER is None:
        return CURATE_KNOWLEDGE_UNAVAILABLE_NOTICE
    selector = parse_curate_args(args)
    if not selector:
        return CURATE_KNOWLEDGE_NO_SELECTOR_NOTICE
    try:
        return _CURATE_KNOWLEDGE_RUNNER(json.dumps(selector, sort_keys=True))
    except Exception:
        logger.exception("curate_knowledge runner failed")
        return CURATE_KNOWLEDGE_BAD_ARGS_NOTICE


# ---------------------------------------------------------------------------
# organise_userdata (#1568) — the assistant's FIRST file surface. DORMANT.
# ---------------------------------------------------------------------------
# The honest cost, stated first: this is the larger of the two approved tools
# because it adds a whole capability class rather than extending one. Every
# argument for it being useful is an argument for it being the most dangerous
# tool in the set.
#
# It ALWAYS rehearses — unlike curate_knowledge there is no reversible action
# here to route normally. The argument is a PATTERN and the effect is a SET OF
# MOVES; "these 23 files would move there" is not answerable from the arguments
# and is tedious to unwind afterwards.
#
# Moves only. No delete, no overwrite, no copy — and `shared.governance.
# userdata_move` contains no code that removes or overwrites a file, so this is
# structural rather than a promise (`security_by_design` 4).

ORGANISE_USERDATA_UNAVAILABLE_NOTICE: str = (
    "organise_userdata: file organising is not enabled on this system."
)
ORGANISE_USERDATA_BAD_ARGS_NOTICE: str = (
    "organise_userdata: a pattern and a destination are both required, and "
    "both must stay inside your data folder. Nothing was moved."
)

#: Windows' classic MAX_PATH. A pattern or destination longer than this cannot
#: name a movable file, so it is refused at the boundary rather than planned and
#: failed at the move.
_ORGANISE_PATH_MAX_CHARS: int = 260

_ORGANISE_USERDATA_RUNNER: Callable[[str], str] | None = None


def register_organise_userdata_runner(runner: Callable[[str], str]) -> None:
    """Wire the tool to a real data directory — a GO-LIVE step (#1568).

    Not called at import. Until the AO calls this behind its config flag, the
    tool body returns a notice and no file path is ever resolved.
    """
    global _ORGANISE_USERDATA_RUNNER
    if not callable(runner):
        raise TypeError("organise_userdata runner must be callable")
    _ORGANISE_USERDATA_RUNNER = runner


def clear_organise_userdata_runner() -> None:
    """Unregister the runner, restoring the dormant default."""
    global _ORGANISE_USERDATA_RUNNER
    _ORGANISE_USERDATA_RUNNER = None


def parse_organise_args(args: str) -> dict[str, str]:
    """Validate move arguments BEFORE any path is resolved (#1568).

    Returns:
        ``{"pattern": ..., "destination": ...}``, or ``{}`` when the request
        must be refused. An empty result is always a refusal.

    The containment check itself lives in ``shared.governance.userdata_move``
    and runs on the resolved paths; this is the cheaper boundary in front of
    it, refusing a malformed request before anything touches the file system.
    """
    try:
        parsed = json.loads(args) if args.strip() else {}
    except (ValueError, TypeError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    raw_pattern = parsed.get("pattern", "")
    raw_destination = parsed.get("destination", "")
    # VALIDATED, not coerced. `str(...)` turned any JSON type into a Python
    # repr and handed it to glob(): a list became "['a', 'b']", a dict became
    # "{'k': 1}", True became "True". `security_by_design` 7 asks for anchored
    # validation, and coercion is the opposite of it.
    if not isinstance(raw_pattern, str) or not isinstance(raw_destination, str):
        return {}
    pattern = raw_pattern.strip()
    destination = raw_destination.strip()
    if not pattern or not destination:
        return {}
    # A path longer than the platform allows cannot be moved, but it CAN be
    # planned -- so the operator was asked to approve a move that could never
    # happen, and the failure then surfaced as a wrong message.
    if len(pattern) > _ORGANISE_PATH_MAX_CHARS or len(destination) > _ORGANISE_PATH_MAX_CHARS:
        return {}
    # A NUL truncates a path in some syscalls, so it is refused at the boundary
    # rather than trusted to be noticed by every layer below.
    nul = chr(0)
    if nul in pattern or nul in destination:
        return {}
    return {"pattern": pattern, "destination": destination}


def _organise_userdata(args: str) -> str:
    """Registry body — delegates to the registered runner, or refuses."""
    if _ORGANISE_USERDATA_RUNNER is None:
        return ORGANISE_USERDATA_UNAVAILABLE_NOTICE
    request = parse_organise_args(args)
    if not request:
        return ORGANISE_USERDATA_BAD_ARGS_NOTICE
    try:
        return _ORGANISE_USERDATA_RUNNER(json.dumps(request, sort_keys=True))
    except Exception:
        logger.exception("organise_userdata runner failed")
        return ORGANISE_USERDATA_BAD_ARGS_NOTICE


# ---------------------------------------------------------------------------
# Registry — each tool takes a single string arg ("" if none provided)
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, Callable[[str], str]] = {
    "get_current_time": lambda _arg: _get_current_time(),
    "get_current_date": lambda _arg: _get_current_date(),
    "get_day_of_week": lambda _arg: _get_day_of_week(),
    "calculate": _calculate,
    # UC-010 Local Generative Imaging (ADR-033 — DORMANT). GUARDED tier; the
    # heavy generate runs in the AO IMAGE_GEN_REQUEST handler off /imagine —
    # this in-loop form is a never-raising directive shim (see _generate_image).
    "generate_image": _generate_image,
    # #719 GUARDED retrieval tools — runner-seam delegates (see the retrieval
    # section above). search_knowledge consumes its CANONICAL JSON args whole
    # (two typed params — listed in _JSON_ARGS_TOOLS); web_search takes the
    # single 'query' string. Neither ever raises into the loop.
    "search_knowledge": _search_knowledge,
    "web_search": _web_search,
    # #1616 GUARDED + DORMANT. Registry body returns its notice until the AO
    # registers a runner, which it does only behind the config flag.
    "search_reference": _search_reference,
    # #770 M2 W1 — a DRAFT surface (renders a confirm card, never a store write).
    # The registry body is a fail-closed notice; the real session-aware handling
    # is the AO tool loop (see the section note above _propose_preference).
    "propose_preference": _propose_preference,
    # #1567 DANGEROUS + DORMANT. Irreversible (secure_delete=ON, no undo) and
    # selector-shaped, so its `delete` always routes to simulate-first. The
    # registry body reaches no store until a runner is registered.
    "curate_knowledge": _curate_knowledge,
    # #1568 DANGEROUS + DORMANT. The assistant's first file surface; moves
    # only, always rehearsed, and the registry body resolves no path until a
    # runner is registered.
    "organise_userdata": _organise_userdata,
}
"""Maps tool name -> callable taking a single string arg ('' if none)."""


# ---------------------------------------------------------------------------
# Tool JSON schemas (#718 — Qwen3 native tool-call format)
# ---------------------------------------------------------------------------
# One Hermes/Qwen3-style function spec per registered tool. These are the
# single source of truth for (a) the <tools> block rendered into the system
# prompt, (b) parse-time argument validation, and (c) the xgrammar
# structured-output schema that constrains generation inside <tool_call>
# (gpu_inference.build_tool_grammar_schema). Keep in lockstep with _REGISTRY
# and pgov.TOOL_CALL_ALLOWLIST — a coupling test enforces this.

TOOL_SCHEMAS: dict[str, dict[str, object]] = {
    "get_current_time": {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "Get the current local date AND time.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    "get_current_date": {
        "type": "function",
        "function": {
            "name": "get_current_date",
            "description": "Get the current local date only (no time).",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    "get_day_of_week": {
        "type": "function",
        "function": {
            "name": "get_day_of_week",
            "description": "Get today's day of the week.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    "calculate": {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": (
                "Safely evaluate a basic arithmetic expression "
                "(numbers and + - * / // % ** with parentheses)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "The arithmetic expression, e.g. 2*(3+4).",
                    },
                },
                "required": ["expression"],
                "additionalProperties": False,
            },
        },
    },
    "generate_image": {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": (
                "Generate an image from a text description. The system replies "
                "telling the user to run the /imagine command (image generation "
                "is local and the result renders inline)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Text description of the image to generate.",
                    },
                },
                "required": ["prompt"],
                "additionalProperties": False,
            },
        },
    },
    # #719 — retrieval tools. NOTE: max_results bounds live in prose + the
    # fail-safe body clamp, NOT as JSON-schema minimum/maximum keywords — the
    # schema feeds the xgrammar structural-tags builder verbatim and numeric
    # bound keywords are the one shape not yet proven on the installed GenAI.
    "search_knowledge": {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": (
                "Search the user's local knowledge bank (their saved, curated "
                "articles and documents) and return the most relevant excerpts. "
                "Use this when the user asks about something they saved, "
                "ingested, or told you to remember."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to look for in the saved knowledge.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": (
                            "Maximum excerpts to return, between 1 and 8 "
                            "(default 4; out-of-range values are clamped)."
                        ),
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    "search_reference": {
        "type": "function",
        "function": {
            "name": "search_reference",
            "description": (
                "Search the offline encyclopedia stored on this machine and "
                "return the most relevant passages, each with the article it "
                "came from. Use this for general factual questions about the "
                "world - people, places, events, science, history - especially "
                "when you are not certain of the answer. Prefer a passage from "
                "here over answering from memory. This is a dated snapshot, "
                "not live, so it will not know about very recent events."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to look up in the encyclopedia.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": (
                            "Maximum passages to return, between 1 and 8 "
                            "(default 4; out-of-range values are clamped)."
                        ),
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    "curate_knowledge": {
        "type": "function",
        "function": {
            "name": "curate_knowledge",
            "description": (
                "Curate the user's local knowledge bank: permanently erase, or "
                "mark as saved, the documents matching a selector. Erasing "
                "CANNOT BE UNDONE. Name what to match by source, by type, or by "
                "when it was taken in — a request with no selector matches "
                "nothing. Use only when the user asks to clear out or tidy "
                "saved material."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["delete", "mark_saved"],
                        "description": (
                            "'delete' erases permanently; 'mark_saved' is "
                            "reversible."
                        ),
                    },
                    "source_ref": {
                        "type": "string",
                        "description": (
                            "Exact source this came from. Matched exactly — "
                            "there is no wildcard."
                        ),
                    },
                    "source_type": {
                        "type": "string",
                        "enum": ["url", "file", "paste"],
                        "description": "How it was taken in.",
                    },
                    "created_before": {
                        "type": "string",
                        "description": "Only items taken in before this date (YYYY-MM-DD).",
                    },
                    "created_after": {
                        "type": "string",
                        "description": "Only items taken in after this date (YYYY-MM-DD).",
                    },
                },
                "required": ["action"],
                "additionalProperties": False,
            },
        },
    },
    "organise_userdata": {
        "type": "function",
        "function": {
            "name": "organise_userdata",
            "description": (
                "Move files into a folder inside the user's own data folder. "
                "Moves only — it never deletes, copies or overwrites, and it "
                "refuses if something with the same name is already there. "
                "Everything stays inside the data folder. It always shows how "
                "many files would move and asks before moving anything."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": (
                            "Which files to move, e.g. '*.pdf' or "
                            "'receipts/*.png'. Relative to the data folder."
                        ),
                    },
                    "destination": {
                        "type": "string",
                        "description": (
                            "An EXISTING folder to move them into, relative to "
                            "the data folder. This tool moves files; it does "
                            "not create folders, and a destination that does "
                            "not exist is refused."
                        ),
                    },
                },
                "required": ["pattern", "destination"],
                "additionalProperties": False,
            },
        },
    },
    "web_search": {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the public web for current or recent information — "
                "news, schedules, releases, prices, weather, and any fact "
                "from after your training data or that may have changed "
                "since. USE this whenever the user asks about current events "
                "or up-to-date facts you cannot reliably know; do not answer "
                "such questions from memory alone. If the result reports "
                "that search is unavailable, answer from your own knowledge "
                "and tell the user you could not search."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The web search query.",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    # #770 M2 W1 — propose_preference. A standing-preference DRAFT: shows the
    # operator a confirm card, saves nothing until they confirm. type_tag and
    # intent are plain strings validated in the AO handler (NOT schema enums —
    # the schema feeds the xgrammar structural-tags builder verbatim and the
    # codebase keeps constraint keywords the installed GenAI has not proven out
    # of it; the handler clamps type_tag to the tier's tags and intent to
    # save/remove, fail-safe).
    "propose_preference": {
        "type": "function",
        "function": {
            "name": "propose_preference",
            "description": (
                "Propose saving (or removing) a STANDING operator preference — a "
                "durable instruction about HOW to respond that should apply to "
                "every future conversation (for example 'always use metric "
                "units', 'call me Blair', 'no source citations'). Use this ONLY "
                "when the user states a lasting preference or correction about "
                "your behaviour, never for a one-off request. This saves nothing "
                "on its own: it shows the user a card they must confirm. To "
                "propose removing a standing preference the user no longer wants, "
                "set intent to 'remove'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": (
                            "The preference in the user's own words, as a "
                            "standing instruction (e.g. 'Always use metric "
                            "units'). For a removal, the preference to remove."
                        ),
                    },
                    "type_tag": {
                        "type": "string",
                        "description": (
                            "Preference kind: 'standing-rule' (default), "
                            "'address-form', or 'fact'."
                        ),
                    },
                    "intent": {
                        "type": "string",
                        "description": (
                            "'save' to propose saving this preference (default), "
                            "or 'remove' to propose removing an existing one."
                        ),
                    },
                },
                "required": ["text"],
                "additionalProperties": False,
            },
        },
    },
}
"""Hermes/Qwen3-style function spec per tool (SSOT for prompt + validation +
grammar). Must mirror ``_REGISTRY`` exactly — no more, no less."""


# The single string parameter each tool's registry callable consumes. Tools
# absent from this map take no arguments (the callable ignores its arg) —
# UNLESS listed in _JSON_ARGS_TOOLS below, which overrides this mapping.
_PRIMARY_STRING_PARAM: dict[str, str] = {
    "calculate": "expression",
    "generate_image": "prompt",
    "web_search": "query",
}

# Tools whose registry callable consumes the CANONICAL JSON arguments string
# WHOLE (multi-parameter tools — the body parses its own typed params).
# Overrides _PRIMARY_STRING_PARAM extraction in _coerce_args_string.
# propose_preference is listed so a direct execute() hands its fail-closed
# notice body the whole args object (harmless — it never touches the store); the
# production path is the AO loop's session-aware handler, not execute().
_JSON_ARGS_TOOLS: frozenset[str] = frozenset(
    {
        "search_knowledge", "search_reference", "propose_preference",
        "curate_knowledge", "organise_userdata",
    }
)


def arguments_schema(tool_name: str) -> dict[str, object] | None:
    """Return the JSON schema for *tool_name*'s ``arguments`` object, or ``None``."""
    spec = TOOL_SCHEMAS.get(tool_name)
    if spec is None:
        return None
    function = spec["function"]
    assert isinstance(function, dict)
    parameters = function["parameters"]
    assert isinstance(parameters, dict)
    return parameters


def tool_call_grammar_schema() -> dict[str, object]:
    """JSON schema constraining the body of a generated ``<tool_call>`` block.

    A union (``anyOf``) of one object schema per registered tool — each pins
    ``name`` to that tool (single-value ``enum``, the xgrammar-proven form)
    and ``arguments`` to that tool's typed parameter schema. Fed to the
    OpenVINO GenAI structured-output triggered grammar (#718): once the model
    emits the ``<tool_call>`` trigger, generation is constrained so a
    malformed or unknown-tool call is structurally impossible at the decoder.
    Purely derived from ``TOOL_SCHEMAS`` — no drift surface.
    """
    return {
        "anyOf": [
            {
                "type": "object",
                "properties": {
                    "name": {"enum": [name]},
                    "arguments": arguments_schema(name),
                },
                "required": ["name", "arguments"],
                "additionalProperties": False,
            }
            for name in TOOL_SCHEMAS
        ]
    }


#: Tools advertised to the model ONLY while their runner is registered. A tool
#: whose capability is switched off by configuration must not be described to
#: the model as something to prefer: the model would call it, receive the
#: unavailable notice, and the switched-off capability would still have
#: changed every conversation's prompt. Structural absence from the prompt,
#: not a notice after the fact (#1616 pre-merge review). Dispatch is unchanged:
#: the tool stays in ``_REGISTRY`` / ``TOOL_CALL_ALLOWLIST`` / the call grammar,
#: so a call emitted anyway still meets its deterministic notice.
_ADVERTISED_ONLY_WHEN_RUNNER_REGISTERED: dict[str, Callable[[], bool]] = {
    "search_reference": lambda: _SEARCH_REFERENCE_RUNNER is not None,
}


def advertised_tool_names(
    also_advertise: frozenset[str] | None = None,
) -> tuple[str, ...]:
    """The tools the system prompt describes, in ``TOOL_SCHEMAS`` order.

    Every schema'd tool, except a runner-gated one whose runner is not
    registered. ``also_advertise`` names runner-gated tools to describe
    regardless, for rendering the prompt a configuration WOULD produce (the
    corpus-accuracy suite measures the go-live prompt with the store closed).
    Unknown names in it are refused rather than ignored.
    """
    extra = frozenset(also_advertise or ())
    unknown = extra - set(_ADVERTISED_ONLY_WHEN_RUNNER_REGISTERED)
    if unknown:
        raise ValueError(
            f"also_advertise names tools that are not runner-gated: {sorted(unknown)}"
        )
    return tuple(
        name
        for name in TOOL_SCHEMAS
        if name not in _ADVERTISED_ONLY_WHEN_RUNNER_REGISTERED
        or name in extra
        or _ADVERTISED_ONLY_WHEN_RUNNER_REGISTERED[name]()
    )


def render_tools_system_block(names: tuple[str, ...] | None = None) -> str:
    """Render the Qwen3/Hermes-style tools block for the system prompt.

    Emits the ``<tools>`` block (one compact JSON function spec per line) plus
    the exact call-format directive Qwen3 was trained on:

        <tool_call>{"name": <function-name>, "arguments": <args-json-object>}</tool_call>

    ``names`` defaults to :func:`advertised_tool_names`. Deterministic: key
    order is the literal ``TOOL_SCHEMAS`` insertion order and JSON is rendered
    compactly, so the rendered prompt is byte-stable for a given tool set.
    """
    selected = advertised_tool_names() if names is None else names
    lines = [
        json.dumps(TOOL_SCHEMAS[name], separators=(", ", ": "), ensure_ascii=False)
        for name in selected
    ]
    tools_block = "\n".join(lines)
    return (
        "TOOL USE: You may call one of the following tools to answer the user. "
        "Function signatures are provided within <tools></tools>:\n"
        f"<tools>\n{tools_block}\n</tools>\n"
        "When a tool is needed, respond with EXACTLY one tool call — a JSON "
        "object with the function name and arguments wrapped in "
        "<tool_call></tool_call> tags, and nothing else:\n"
        '<tool_call>{"name": <function-name>, "arguments": <args-json-object>}'
        "</tool_call>\n"
        "Example: <tool_call>{\"name\": \"calculate\", \"arguments\": "
        "{\"expression\": \"2*(3+4)\"}}</tool_call>\n"
        "Pick the tool that most narrowly fits the question (e.g. use "
        "get_current_date if only the date is asked, not get_current_time). "
        "The system runs the tool and feeds the result back so you can answer "
        "the user. Do NOT use <tool_call> syntax for any other purpose.\n\n"
    )


# ---------------------------------------------------------------------------
# Tool risk tiers (ADR-023 Amendment 1 — capability-scoped locking)
# ---------------------------------------------------------------------------
# A tool's risk tier governs the Layer-3 action-lock, NOT whether its action is
# adjudicated: the #570 per-dispatch Policy-Agent deny (entrypoint
# _adjudicate_tool_dispatch) runs for EVERY tool regardless of tier. The tier
# decides friction; the per-action deny decides danger.
#   SAFE      - deterministic; no external reach, mutation, egress, or
#               untrusted-redirectable parameter. NEVER locked, even under
#               untrusted content.
#   GUARDED   - reads/queries local data with a redirectable parameter. Locked
#               under untrusted content; /trust is the sole override.
#   DANGEROUS - egress / irreversible mutation / external dispatch. Governed by
#               the per-action deny (denied absolutely on a DENY rule, no
#               /trust); the lock is not its mechanism.
# Fail-closed: a tool with no declared tier is DANGEROUS (most restrictive). The
# signed tool manifest (#590) becomes the tamper-evident authority for this map.


class RiskTier(str, Enum):
    """Tool risk tier (ADR-023 Amendment 1)."""

    SAFE = "SAFE"
    GUARDED = "GUARDED"
    DANGEROUS = "DANGEROUS"


_TOOL_RISK_TIER: dict[str, RiskTier] = {
    "get_current_time": RiskTier.SAFE,
    "get_current_date": RiskTier.SAFE,
    "get_day_of_week": RiskTier.SAFE,
    "calculate": RiskTier.SAFE,
    # GUARDED (UC-010, ADR-033): local generation with a redirectable prompt
    # parameter and no egress — Layer-3-lockable under untrusted content, /trust
    # the sole override. Not SAFE (it triggers a heavy local action a clock does
    # not); not DANGEROUS (no egress / irreversible external dispatch — the
    # output is a deletable on-box artifact).
    "generate_image": RiskTier.GUARDED,
    # DANGEROUS (#1567), DECLARED rather than left to risk_tier's fallback. The
    # fallback would reach the same answer, and a control that is right by
    # accident is the defect class this sprint spent itself on: an explicit
    # declaration fails loudly if someone reclassifies it, a fallback does not.
    # Irreversible by construction (secure_delete=ON zeroes the freed pages),
    # mutating, and selector-shaped, so its match set is not knowable from its
    # arguments. NOT Layer-3-exempt: unlike search_knowledge this is a WRITE,
    # so untrusted content in a session must lock it.
    "curate_knowledge": RiskTier.DANGEROUS,
    # DANGEROUS (#1568), declared rather than inherited from the fallback. The
    # first tool that touches the file system: a redirectable PATTERN whose
    # effect is a set of moves. Not Layer-3-exempt — a session holding
    # untrusted content must lock it, because an injection that can steer a
    # pattern can steer where the operator's files end up.
    "organise_userdata": RiskTier.DANGEROUS,
    # GUARDED (#719): local knowledge retrieval with a redirectable query
    # parameter — an injection can steer WHAT is retrieved (and retrieved bank
    # content is itself untrusted, ADR-023 Am.2), so it is locked under
    # untrusted content with /trust the sole override. Not SAFE (redirectable
    # read over the operator's curated store); not DANGEROUS (no egress, no
    # mutation — a read of on-box data).
    "search_knowledge": RiskTier.GUARDED,
    # GUARDED (#719): the tool itself performs no egress — it delegates to a
    # runner that is NOT registered by any production code (structurally
    # dormant; see _web_search's decision chain). GUARDED, not DANGEROUS,
    # because the DISPATCH is a redirectable query handed to an
    # egress-governed subsystem, not an irreversible external action at this
    # seam: the actual network reach is denied independently at the egress
    # door (RULE 3 + empty allowlist) and by the runner's absence. Under
    # untrusted content it locks exactly like the other GUARDED tools.
    "web_search": RiskTier.GUARDED,
    # GUARDED (#1616): a redirectable READ over an on-box, read-only store —
    # no egress, no mutation — so it sits with search_knowledge rather than
    # with the DANGEROUS writes. Declared explicitly rather than left to
    # risk_tier()'s DANGEROUS fallback: the fallback is the right failure mode
    # for a tool nobody classified, not a substitute for classifying one.
    # Lock-exempt too (`_LOCK_EXEMPT_TOOLS`, ADR-023 Amendment 5 addendum) —
    # the bounded-danger property that earns the exemption IS this tier
    # classification, so a tool that "sits with search_knowledge" here and is
    # not also exempt is a drift, not a variant.
    "search_reference": RiskTier.GUARDED,
    # GUARDED (#770 M2 W1): propose_preference RENDERS a confirm card and stages
    # verbatim bytes — it performs NO store write (P8: the write door is the AO
    # operator preference write handler, reached only by an operator-typed confirm) and NO
    # egress. The redirectable parameter is the proposed text, which an injection
    # could shape into a plausible-preference nudge — so it is GUARDED, and its
    # danger is bounded to "a card the operator must confirm" (lock-exempt below,
    # so it can fire under untrusted content with the untrusted-context flag as
    # the defense — D-1(a)). Not SAFE (it reads the store + stages); not
    # DANGEROUS (no egress / irreversible mutation — the card is inert until the
    # operator confirms).
    "propose_preference": RiskTier.GUARDED,
}
"""Declared risk tier per tool. The four core tools are SAFE: pure-Python, no
network, no filesystem, no exec (see module docstring). ``generate_image``,
``search_knowledge``, and ``web_search`` are GUARDED (redirectable parameters;
locking under untrusted content with /trust the sole override)."""


# ---------------------------------------------------------------------------
# Tool-result provenance (#719 — retrieval results are untrusted content)
# ---------------------------------------------------------------------------
# Values are context_manager.Provenance VALUES (kept as strings so this module
# stays a leaf — the entrypoint reconstructs the enum). A declared tool's
# non-notice result is grounded through add_grounded_context with this tier,
# flipping has_untrusted_content so Layer 3 locks subsequent non-SAFE calls.
# Tools absent from this map return SYSTEM-AUTHORED text (clock strings,
# arithmetic, directive shims) that rides the plain tool-note path. EVERY new
# tool MUST make this choice explicitly — a retrieval-shaped tool left out of
# this map would splice untrusted text raw into the context (the
# test_result_provenance_declarations lock names this rule).

_TOOL_RESULT_PROVENANCE: dict[str, str] = {
    # ADR-023 Amendment 2 (#664): knowledge recall is ALWAYS untrusted —
    # operator curation put it in the bank; it did not promote web-sourced
    # text into the trust boundary. Action-locked + datamarked; exempt only
    # from the Stage-5 leakage feed.
    "search_knowledge": "untrusted_knowledge",
    # ADR-023 Amendment 3 (#719): web-search results are untrusted content —
    # action-locked + datamarked (an injected instruction in a result still
    # cannot fire a subsequent tool) — but EXEMPT from the Stage-5 cosine
    # leakage feed, because a faithful answer relaying the public results the
    # operator asked for is ~verbatim to those results and is the intended
    # behaviour, not exfiltration. The web-search go-live ceremony proved the
    # full chain live (Kagi 200, real answer) but the answer was HELD as a
    # 0.930-cosine leak false-positive; this tier carves it out. Kept DISTINCT
    # from untrusted_knowledge (web results are not the curated bank) and from
    # untrusted_external (/external pasted content stays screened).
    "web_search": "untrusted_web",
    # ADR-023 Amendment 5 (#1616): reference-corpus passages are untrusted
    # content — a bulk archive import is not operator curation, so the
    # knowledge-bank rationale does not carry. Action-locked + datamarked in
    # full; EXEMPT from the Stage-5 cosine leakage feed on the UNTRUSTED_WEB
    # precedent, because relaying the public encyclopedia text the operator
    # asked for is the intended behaviour, not exfiltration.
    "search_reference": "untrusted_corpus",
}

#: Registered tools whose results are SYSTEM-AUTHORED — computed or templated
#: here, never carrying third-party text. Maintained as an explicit set so that
#: `_REGISTRY` is exhaustively partitioned between this and
#: `_TOOL_RESULT_PROVENANCE`: a newly registered tool belongs to one or the
#: other, and the completeness lock in the retrieval-tool tests fails until it
#: is classified. The previous lock only rejected declarations for tools that
#: do not exist, so a retrieval tool MISSING from the provenance map passed it.
_SYSTEM_AUTHORED_TOOLS: frozenset[str] = frozenset(
    {
        "get_current_time",
        "get_current_date",
        "get_day_of_week",
        "calculate",
        "generate_image",
        "propose_preference",
        "curate_knowledge",
        "organise_userdata",
    }
)


def result_provenance(tool_name: str) -> str | None:
    """Provenance VALUE for *tool_name*'s results, or ``None`` for
    system-authored results (see the map comment above)."""
    return _TOOL_RESULT_PROVENANCE.get(tool_name)


def risk_tier(tool_name: str) -> RiskTier:
    """Return the declared risk tier for *tool_name* (ADR-023 Amendment 1).

    Fail-closed: an unknown or undeclared tool is ``DANGEROUS`` — the most
    restrictive tier — so a tool that reaches dispatch without a declaration can
    never be treated as never-lockable.
    """
    return _TOOL_RISK_TIER.get(tool_name, RiskTier.DANGEROUS)


# ---------------------------------------------------------------------------
# Layer-3 lock-exemption (ADR-023 Amendment 4, #723 rung 1)
# ---------------------------------------------------------------------------
# A small, EXPLICIT allowlist of tools whose Layer-3 action-lock is lifted
# because the tool's DANGER IS BOUNDED — not because of any property of the
# content in the session. This is a per-TOOL policy, deliberately NOT a
# per-provenance rule: an `UNTRUSTED_KNOWLEDGE`-specific relaxation would behave
# ambiguously when a session holds MIXED untrusted content (knowledge + a pasted
# external document), whereas a tool keyed on its own bounded danger is
# unambiguous regardless of what else the session holds.
#
# `search_knowledge` qualifies: it is a redirectable READ over the operator's
# OWN curated local store. A prompt-injection can at most steer WHICH local
# record is read; the result is grounded as `untrusted_knowledge` (still
# action-locked + datamarked, ADR-023 Am.2), performs NO egress and NO mutation,
# and therefore cannot exfiltrate or fire a subsequent action no matter what
# untrusted content shares the session. Locking it under untrusted content was
# therefore pure friction — the LA's consent doctrine routes danger to
# deterministic controls, and a non-exfiltratable local read carries none.
#
# `generate_image` qualifies too, for a DIFFERENT bounded-danger reason (ADR-023
# Amendment 4 rung 2, reframed): the in-loop `generate_image` tool is a DIRECTIVE
# SHIM (`_generate_image`) — it does NOT generate, store, or render any image; it
# returns a short text string pointing the operator at the `/imagine` command
# (real generation runs ONLY in the operator-typed `/imagine` gateway path, which
# owns the session id + at-rest cipher the in-loop form lacks). A directive string
# has NO egress and NO side effect, so an injection can at most make the model
# emit a "use /imagine" hint — nothing to exfiltrate or fire. Locking the shim
# under untrusted content was pure friction. NOTE: if a FUTURE model-initiated
# path ever performs REAL generation (autonomous image work), it must NOT ride
# this exemption — it goes through the dormant per-batch approval seam instead
# (`is_generation_approval_tool` / `_GEN_APPROVAL_TOOLS`, ADR-023 Am.4 rung 2).
#
# This exemption lifts ONLY the Layer-3 lock. The #570 per-dispatch Policy-Agent
# adjudication (RULE 1-4) STILL runs on every call to an exempt tool (see
# entrypoint.py `_adjudicate_tool_dispatch`, which is downstream of the gate);
# an exempt tool is never a governance bypass, only a friction removal.
#
# `search_reference` qualifies for the SAME rung-1 reason as `search_knowledge`
# (ADR-023 Amendment 5 addendum, #1616 pre-merge review finding 1): it is a
# redirectable READ over an on-box, read-only encyclopedia store. A
# prompt-injection can at most steer WHICH passage is read; the result grounds
# as `untrusted_corpus` (still action-locked + datamarked), performs NO egress
# and NO mutation, so it cannot exfiltrate or fire a subsequent action no
# matter what untrusted content shares the session — the identical bounded-
# danger shape `search_knowledge` was exempted on. Without this exemption the
# tool locks itself after its own first result (and locks on the first call of
# any session already holding knowledge/web/pasted content), making the
# capability single-shot per clean session absent `/trust` — a friction with no
# matching danger, exactly what rung 1 removed for search_knowledge.
#
# Fail-closed: membership is an explicit allowlist. A tool NOT listed here is
# never exempt (the gate locks it exactly as before). Every entry MUST be a
# GUARDED (never a DANGEROUS) tool with the bounded-danger property above; the
# `test_lock_exempt_tools_are_all_guarded` lock enforces that invariant.
_LOCK_EXEMPT_TOOLS: frozenset[str] = frozenset(
    {"search_knowledge", "generate_image", "propose_preference", "search_reference"}
)
"""Tools whose Layer-3 action-lock is lifted on bounded-danger grounds
(ADR-023 Amendment 4, rungs 1 + 2; #770 M2 W1; Amendment 5 addendum, #1616). A
per-tool allowlist, not a provenance rule. `search_knowledge` (non-exfiltratable
local read) + `generate_image` (a no-side-effect directive shim) +
`propose_preference` (#770 M2 W1 — renders a confirm card and stages verbatim
bytes; NO store write and NO egress, so an injection can at most induce a
proposal the operator sees, flagged untrusted-context, and must confirm; D-1(a)
requires it to fire under untrusted content BECAUSE the card flag — not a lock —
is the weak-signal defense) + `search_reference` (#1616 — a non-exfiltratable
read of an on-box, read-only encyclopedia store; same shape as
search_knowledge). The #570 PA adjudication still runs on every dispatch."""


def is_lock_exempt(tool_name: str) -> bool:
    """Return True iff *tool_name*'s Layer-3 action-lock is lifted on
    bounded-danger grounds (ADR-023 Amendment 4, #723 rung 1).

    Fail-closed: only tools on the explicit ``_LOCK_EXEMPT_TOOLS`` allowlist are
    exempt; every other tool (including an unknown one) is NOT exempt and locks
    exactly as before. The exemption lifts ONLY the Layer-3 lock — the #570 PA
    per-dispatch adjudication still runs on every call.
    """
    return tool_name in _LOCK_EXEMPT_TOOLS


# ---------------------------------------------------------------------------
# Per-generation-batch approval — DORMANT SEAM (ADR-023 Amendment 4, #723 rung 2)
# ---------------------------------------------------------------------------
# The tools whose dispatch performs a REAL model-initiated local GENERATION (an
# image the operator did not ask for by typing a slash command). Each such
# dispatch raises a per-generation-batch ONE-CLICK approval showing the exact
# prompt + image count (services/.../generation_consent.py), replacing the
# untrusted-content Layer-3 lock for that tool with a judgeable per-event consent.
# Fail-closed (deny / timeout / no verifier → the generation is refused).
#
# THIS SET IS DELIBERATELY EMPTY TODAY. The current in-loop `generate_image` tool
# is a DIRECTIVE SHIM that generates nothing (see `_generate_image` +
# `_LOCK_EXEMPT_TOOLS` above), so there is no real model-initiated generation to
# gate — a per-batch approval on the shim would prompt the operator to approve a
# text string, pure friction protecting nothing (verified 2026-07-02, LA-approved
# reframe). The approval INFRASTRUCTURE (the consent registry + the one-click
# surface + this gate) is built and tested so it is ready; it ACTIVATES the day a
# real model-initiated generation path is added (e.g. autonomous image work), by:
#   (1) adding that generator tool's name to this set, and
#   (2) registering a generation-approval verifier (the launcher wires the
#       one-click SystemConfirmApprovalVerifier — dormant until then).
# Until both happen the gate is inert (no tool matches) and fail-closed by default.
_GEN_APPROVAL_TOOLS: frozenset[str] = frozenset()
"""Tools performing REAL model-initiated generation, gated by the per-batch
one-click approval (ADR-023 Amendment 4, #723 rung 2). EMPTY today — the in-loop
`generate_image` is a no-op directive shim; this activates when a real
model-initiated generator tool is added. See the block comment above."""


def is_generation_approval_tool(tool_name: str) -> bool:
    """Return True iff *tool_name* performs a REAL model-initiated generation that
    must pass the per-generation-batch one-click approval (ADR-023 Amendment 4,
    #723 rung 2 — the dormant seam).

    EMPTY today (the in-loop ``generate_image`` is a no-op directive shim, so
    there is nothing to gate). Fail-closed: only tools on the explicit
    ``_GEN_APPROVAL_TOOLS`` allowlist are gated; the gate is inert until a real
    generator tool is added AND a verifier is registered.
    """
    return tool_name in _GEN_APPROVAL_TOOLS


# ---------------------------------------------------------------------------
# Egress tools (ADR-023 Amendment 4, #723 rung 3)
# ---------------------------------------------------------------------------
# The tools whose dispatch causes a model-initiated OUTBOUND network action —
# content leaving the machine. These are gated by the turn-scoped Windows-Hello
# egress envelope (services/assistant_orchestrator/src/egress_envelope.py): the
# first egress of a user turn raises a fingerprint showing the exact query, one
# touch covers up to N searches for the question, and each subsequent query is
# disclosed live in chat. This is the HUMAN consent layer that REPLACES the
# per-session /trust for egress tools; it runs IN ADDITION to (never instead of)
# the deterministic egress controls — the #570 PA per-dispatch adjudication
# (RULE 3 DENY_EXTERNAL_NETWORK + the kagi.com allowlist) still runs FIRST, and
# the exfil screen still applies at send. EVERY new outbound tool MUST be added
# here so it inherits the fingerprint envelope; an egress-shaped tool left out
# would leave with no human touch (the coupling is asserted by
# test_egress_tools_are_non_safe).
_EGRESS_TOOLS: frozenset[str] = frozenset({"web_search"})
"""Model-callable tools that cause outbound network egress and are therefore
gated by the turn-scoped Hello envelope (ADR-023 Amendment 4, #723 rung 3)."""


def is_egress_tool(tool_name: str) -> bool:
    """Return True iff *tool_name* causes model-initiated outbound egress and is
    gated by the turn-scoped Hello envelope (ADR-023 Amendment 4, #723 rung 3).

    This predicate governs the HUMAN fingerprint layer. It is not the hard egress
    backstop — a network-bearing tool is ALSO independently denied by the #570 PA
    RULE 3 unless its host is on the deterministic egress allowlist — so a tool
    mistakenly absent here still cannot reach the network unpoliced; it would only
    miss the fingerprint. The `test_egress_tools_are_non_safe` lock keeps the set
    honest (an egress tool is never SAFE).
    """
    return tool_name in _EGRESS_TOOLS


def egress_tool_active(tool_name: str) -> bool:
    """True iff an egress tool currently has a live runner and would perform REAL
    outbound egress (so the turn-scoped Hello fingerprint is warranted).

    A DORMANT / disabled egress tool (no runner registered) returns its
    deterministic "unavailable" notice WITHOUT anything leaving the machine, so it
    must NOT raise a fingerprint (there is nothing to consent to). This mirrors the
    existing principle that a deterministic notice takes the plain path and never
    locks the session. ``web_search`` is the only egress tool today; its liveness
    is exactly its runner registration (#719 — the AO registers the live Kagi
    runner only when [web_search].enabled AND the key loads). A future egress tool
    adds its own liveness branch here (the fingerprint gate reads this).
    """
    if tool_name == "web_search":
        return _WEB_SEARCH_RUNNER is not None
    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# Outer tag boundaries — the payload between the tags is parsed as strict
# JSON (the ONLY accepted form since the #718 D3 legacy retirement).
# Non-greedy DOTALL so a multi-line JSON payload is captured;
# case-insensitive tag boundaries retained from the original pattern.
_TOOL_CALL_TAG_PATTERN: re.Pattern[str] = re.compile(
    r"<tool_call>\s*(.*?)\s*</tool_call>",
    re.IGNORECASE | re.DOTALL,
)

# Kept as an alias for external references/tests that patch the module pattern.
_TOOL_CALL_PATTERN: re.Pattern[str] = _TOOL_CALL_TAG_PATTERN


def _payload_fingerprint(payload: str) -> str:
    """Deterministic failure fingerprint for a malformed tool-call payload.

    Short SHA-256 of the payload bytes — stable across runs for the same
    malformed emission, safe to log (never echoes model output into the log).
    """
    return hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()[:12]


def canonical_arguments(arguments: dict[str, object]) -> str:
    """Render a parsed ``arguments`` object in the CANONICAL string form.

    Compact, key-sorted JSON (``sort_keys=True``, ``(",", ":")`` separators) —
    the single deterministic representation consumed by the #570 PA
    adjudication (``_adjudicate_tool_dispatch`` parameters_schema) and by
    ``execute``. An empty arguments object canonicalises to ``""`` so
    zero-argument JSON calls remain byte-identical to the historical no-arg
    form at every governance surface.
    """
    if not arguments:
        return ""
    return json.dumps(arguments, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _validate_type(value: object, schema: dict[str, object]) -> bool:
    """Minimal JSON-schema type check for the shapes TOOL_SCHEMAS uses."""
    expected = schema.get("type")
    if expected == "string":
        return isinstance(value, str)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    # No/unknown type constraint — accept (schemas here always declare types).
    return True


def validate_arguments(tool_name: str, arguments: dict[str, object]) -> str | None:
    """Validate *arguments* against *tool_name*'s declared parameter schema.

    Hand-rolled minimal validator (no new dependency): checks required
    properties, per-property types, and ``additionalProperties: false``.
    Returns ``None`` when valid, else a deterministic error description.
    Unknown tools return an error — parse-time validation only applies to
    KNOWN tools; unknown tool names are surfaced to the caller unvalidated so
    the allowlist/PGOV governance fires on them (see ``parse_tool_call``).
    """
    schema = arguments_schema(tool_name)
    if schema is None:
        return f"unknown tool: {tool_name}"
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        properties = {}
    required = schema.get("required")
    if not isinstance(required, list):
        required = []
    for key in required:
        if key not in arguments:
            return f"missing required argument: {key}"
    if schema.get("additionalProperties") is False:
        extras = sorted(set(arguments) - set(properties))
        if extras:
            return f"unexpected argument(s): {', '.join(extras)}"
    for key, value in arguments.items():
        prop_schema = properties.get(key)
        if isinstance(prop_schema, dict) and not _validate_type(value, prop_schema):
            return f"argument {key!r} has wrong type"
    return None


def _parse_json_payload(payload: str) -> tuple[str, str] | None:
    """Parse a native-format JSON payload into ``(name, canonical_args)``.

    Fail-closed: any structural defect — invalid JSON, non-object payload,
    missing/non-string ``name``, non-object ``arguments``, unexpected
    top-level keys, or a KNOWN tool whose arguments violate its schema —
    returns ``None`` with a logged deterministic fingerprint. An UNKNOWN tool
    name with valid structure is RETURNED (not swallowed): authorization is
    the entrypoint's TOOL_CALL_ALLOWLIST + PGOV's job, and those locks must
    see the name to fire on it (governance parity with the legacy parser).
    """
    try:
        parsed = json.loads(payload)
    except (json.JSONDecodeError, ValueError):
        logger.warning(
            "Malformed tool-call JSON payload dropped (fail-closed, no tool "
            "call). fingerprint=%s",
            _payload_fingerprint(payload),
        )
        return None
    if not isinstance(parsed, dict):
        logger.warning(
            "Tool-call payload is valid JSON but not an object — dropped "
            "(fail-closed). fingerprint=%s",
            _payload_fingerprint(payload),
        )
        return None
    extras = sorted(set(parsed) - {"name", "arguments"})
    if extras:
        logger.warning(
            "Tool-call JSON carries unexpected top-level key(s) %s — dropped "
            "(fail-closed). fingerprint=%s",
            extras,
            _payload_fingerprint(payload),
        )
        return None
    name = parsed.get("name")
    if not isinstance(name, str) or not re.fullmatch(r"\w+", name):
        logger.warning(
            "Tool-call JSON 'name' missing or not a well-formed identifier — "
            "dropped (fail-closed). fingerprint=%s",
            _payload_fingerprint(payload),
        )
        return None
    arguments = parsed.get("arguments", {})
    if not isinstance(arguments, dict):
        logger.warning(
            "Tool-call JSON 'arguments' is not an object — dropped "
            "(fail-closed). fingerprint=%s",
            _payload_fingerprint(payload),
        )
        return None
    name = name.lower()
    if name in TOOL_SCHEMAS:
        error = validate_arguments(name, arguments)
        if error is not None:
            logger.warning(
                "Tool-call JSON for %r failed schema validation (%s) — dropped "
                "(fail-closed). fingerprint=%s",
                name,
                error,
                _payload_fingerprint(payload),
            )
            return None
    return (name, canonical_arguments(arguments))


def parse_tool_call(text: str) -> tuple[str, str] | None:
    """Return ``(tool_name, args)`` if a tool call is present, else ``None``.

    The Qwen3 NATIVE form — a strict JSON payload inside the tags — is the
    ONLY accepted form (#718 D3 retired the v1/v2 ``NAME``/``NAME(ARGS)``
    legacy syntax, 2026-07-02):

        <tool_call>{"name": "calculate", "arguments": {"expression": "1+1"}}</tool_call>
            ->  ("calculate", '{"expression":"1+1"}')

    ``args`` is the CANONICAL compact key-sorted JSON of the arguments object
    ("" when the arguments object is empty) — deterministic, so the #570 PA
    adjudication sees one stable string form per semantic call. Malformed
    JSON — including any legacy-shaped ``NAME(ARGS)`` payload — schema-
    violating arguments (for known tools), or structural defects fail closed
    to ``None`` with a logged fingerprint. Unknown tool names with valid
    structure are returned so the allowlist/PGOV locks fire on them.

    Matching is case-insensitive on the tag boundaries; the tool name is
    lowercased. Only the FIRST ``<tool_call>`` block is considered (the
    historical ``.search`` semantics) — a malformed first block is a dropped
    call, never a fall-through to a later block.

    Args:
        text: Generated model output to inspect.

    Returns:
        A ``(name, args)`` tuple, or ``None`` if no (valid) tool call is found.
    """
    match = _TOOL_CALL_TAG_PATTERN.search(text)
    if not match:
        return None
    return _parse_json_payload(match.group(1).strip())


def _coerce_args_string(tool_name: str, args: str) -> str:
    """Map an ``execute`` args string to the single string arg the tool takes.

    Canonical-JSON args (the native path) are parsed and the tool's declared
    primary string parameter extracted (``calculate`` -> ``expression``,
    ``generate_image`` -> ``prompt``, ``web_search`` -> ``query``);
    zero-parameter tools coerce to ``""``. Multi-parameter tools listed in
    ``_JSON_ARGS_TOOLS`` (``search_knowledge``) receive the canonical JSON
    string WHOLE and parse their own typed params. Anything that is not a
    JSON object (bare strings from direct ``execute`` callers) passes through
    verbatim — each tool keeps its own argument validation either way.
    """
    if tool_name in _JSON_ARGS_TOOLS:
        return args
    stripped = args.strip()
    if not stripped.startswith("{"):
        return args
    try:
        parsed = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return args
    if not isinstance(parsed, dict):
        return args
    param = _PRIMARY_STRING_PARAM.get(tool_name)
    if param is None:
        return ""
    value = parsed.get(param, "")
    return value if isinstance(value, str) else str(value)


def execute(tool_name: str, args: str = "") -> str:
    """Execute the named tool with the given args and return its result.

    Args:
        tool_name: Name of the tool to run (must be in the registry).
        args: Argument string — either the canonical compact-JSON arguments
            object produced by ``parse_tool_call`` (native format) or a
            bare verbatim string from a direct caller. Typed extraction maps
            a JSON object to the tool's declared string parameter; the tool
            function still performs its own validation.

    Returns:
        The tool's string output.

    Raises:
        KeyError: If *tool_name* is not registered.
    """
    if tool_name not in _REGISTRY:
        raise KeyError(f"Unknown tool: {tool_name!r}. Available: {sorted(_REGISTRY)}")
    return _REGISTRY[tool_name](_coerce_args_string(tool_name, args))


# ---------------------------------------------------------------------------
# Simulate-first capability declaration (#1548) — DENY-BY-DEFAULT
# ---------------------------------------------------------------------------

#: Tools that declare a dry run, and therefore MAY be routed to the
#: simulate-first outcome. **Empty at merge, deliberately** — the outcome ships
#: reachable and unused, which is the correct starting state under
#: security_by_design principle 2 (new capability starts denied, granted
#: explicitly). A tool absent from this set can NEVER be routed to
#: simulate-first: the checker refuses the route rather than falling back to
#: execute.
#:
#: The rule a tool must satisfy before being added: its argument is a SELECTOR
#: rather than a TARGET. `delete_image(id)` needs no simulation because the
#: argument IS the effect; `forget(query)` does, because nobody can compute the
#: match set in their head.
#:
#: RETIRED as a source of truth (#1548 executor). Declaring is now registering a
#: rehearsal with :mod:`shared.governance.dry_run`, because a declaration this
#: module could not honour was a name with nothing behind it. Kept, empty, only
#: so the gate test that pinned it fails loudly if anything writes to it again
#: instead of registering — a second list is what this retired.
_SIMULATE_FIRST_TOOLS: frozenset[str] = frozenset()

#: Tools BARRED from simulate-first no matter what they declare (#1548).
#:
#: `web_search` is barred because it is the only tool that leaves the machine. A
#: dry run of a search is either the query and host shown before sending — which
#: the escalation prompt already does — or the search actually performed and its
#: results shown before approval, **which commits the exact egress the gate
#: exists to control**. That second shape is the trap this bar exists to prevent,
#: and it is enforced here rather than by a comment.
#:
#: This set wins over `_SIMULATE_FIRST_TOOLS`: a tool in both is barred.
_SIMULATE_FIRST_BARRED: frozenset[str] = frozenset({"web_search"})


def declares_dry_run(tool_name: str, tool_args: str = "") -> bool:
    """True iff ``tool_name`` may be routed to the simulate-first outcome (#1548).

    Deny-by-default and bar-wins:

      * no rehearsal registered    -> False (the default for every tool)
      * present in the barred set  -> False, even with one registered
      * registered and not barred  -> True

    Returns False for an unknown tool, so a tool added later is not routable
    until someone registers its rehearsal deliberately.

    THE DECLARATION IS THE REGISTRATION (#1548 executor). This used to read a
    hand-maintained ``_SIMULATE_FIRST_TOOLS`` frozenset that lived separately
    from any implementation, so a name could sit in it with no dry run behind
    it and the only thing between that and a real execution was the tool loop
    noticing. Two lists that must agree will eventually disagree; there is one
    now, and it is the one that can actually rehearse
    (:func:`shared.governance.dry_run.declares_dry_run`).
    """
    if tool_name in _SIMULATE_FIRST_BARRED:
        return False
    from shared.governance import dry_run as _dry_run

    return _dry_run.declares_dry_run(tool_name, tool_args)


#: The fourth route outcome's name (#1548). ALLOW / DENY / ESCALATE are the three
#: that exist today; this is the fourth, and it is a distinct string so a consumer
#: that does not know it cannot silently treat it as one of the others.
SIMULATE_FIRST: str = "SIMULATE_FIRST"


def route_simulate_first(
    tool_name: str,
    *,
    enabled: bool,
    tool_args: str = "",
) -> str | None:
    """Decide whether a dispatch routes to simulate-first (#1548). DORMANT by default.

    Returns :data:`SIMULATE_FIRST` only when ALL of:
      * ``enabled`` is True — the config flag, off in the shipped default, flipped
        only at an LA-present go-live ceremony;
      * the tool declares a dry run FOR THESE ARGUMENTS
        (:func:`declares_dry_run`), which no tool does at merge. Applicability
        is per-argument because one tool can carry actions of different kinds:
        ``curate_knowledge``'s ``delete`` is irreversible and always rehearses,
        its ``mark_saved`` is reversible and routes normally;
      * the tool is not barred.

    Returns ``None`` otherwise, meaning "this outcome does not apply" — the caller
    proceeds with the verdict it already has. It NEVER returns a permissive value
    of its own: a tool that does not declare is not routed here and is not
    thereby allowed, which is the refusal the ticket specifies rather than a
    fallback to execute.

    Reversal is the flag plus a restart, restoring byte-identical prior behaviour.
    """
    if not enabled:
        return None
    if not declares_dry_run(tool_name, tool_args):
        return None
    return SIMULATE_FIRST
