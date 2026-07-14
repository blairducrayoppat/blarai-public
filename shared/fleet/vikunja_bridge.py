"""Dispatch -> Vikunja bridge: durable job tickets for the coding fleet (#749).

The fleet's plan-graph (``shared/fleet/plan_graph.py``) tracks work WITHIN a job
— hash-sealed identity, evidence-gated statuses, an oracle-gated done. That layer
is stronger than a ticket and stays untouched. ACROSS jobs, though, the fleet has
no durable memory: PARKED-HONEST outcomes, eyeball tiers, and report-named
follow-ups die in run dirs nobody re-reads. This bridge gives the operator the
same durable unfinished-business queue the dev harness runs on: **one Vikunja
ticket per dispatched job** — created at dispatch, updated with the outcome,
CLOSED only on a GREEN + oracle-passed scorecard, left OPEN on
PARKED-HONEST / STALLED with the failure evidence pointers.

Design invariants (from #749, LA-approved):

* **OUTCOMES ONLY, never heartbeats.** One ticket per job, one comment per
  meaningful transition, nothing per wake. The anti-pattern is the April
  dev-fleet "Fleet Reports" spam (per-phase idle tickets, now Defunct) — a
  notification firehose the operator learned to ignore.
* **Loopback-pinned.** Vikunja is a LOCAL server (``:3456``); this module is
  dev-side dispatch tooling, not the sealed BlarAI runtime, but every request is
  hard-asserted to a loopback host and REFUSED otherwise. It opens no socket
  itself: the raw HTTP transport lives in ``tools/dispatch_harness/vikunja_http``
  (the sanctioned dev tier) so ``shared/`` stays air-gap-clean — this module
  imports only ``urllib.parse`` (URL building, no I/O). The pin is enforced HERE,
  before any transport call is dispatched.
* **FAIL-SOFT.** Any exception or timeout (2 s hard cap per call, NO retries) is
  logged and swallowed — a Vikunja outage must never affect, slow, or fail a
  dispatch/battery run. The functions return ``None`` / ``False`` on any trouble.
* **Reporting code, not a model capability.** The coder/planner models get NO
  ticket tools; this is deterministic dispatch-layer glue with regression locks
  (ticket-created-on-dispatch, closed-only-on-oracle-green — a FALSE-DONE-shaped
  lock: a job ticket may never close without the oracle-green scorecard).

Credentials reuse the SAME source the Vikunja MCP server does (no new secret
store): the ``VIKUNJA_URL`` / ``VIKUNJA_USER`` / ``VIKUNJA_PASS`` environment
variables, with a gitignored ``.env`` in the repo root as the documented
fallback. Auth is Vikunja's JWT bearer flow (``POST /api/v1/login`` -> token).
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import urllib.parse
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Contract constants
# ---------------------------------------------------------------------------

#: Hard per-call cap (seconds). NO retries: a battery night must never stall on
#: ticket I/O, so a slow/hung Vikunja fails one call fast and the run proceeds.
CALL_TIMEOUT_S: float = 2.0

#: The idempotency key stamped into every job ticket title. ``ensure_job_ticket``
#: finds-or-creates by this marker, so a re-report of the same run never
#: duplicates the ticket.
_TITLE_PREFIX = "[fleet-job "
_TITLE_SUFFIX = "]"

#: The close gate (a local mirror of the ``scorecard.py`` §9.4 taxonomy — NOT an
#: import, because ``shared/fleet`` must not depend on ``tools/``). A ticket
#: closes ONLY on this verdict AND an oracle-passed scorecard.
_VERDICT_GREEN = "GREEN"
_ORACLE_PASSED = "passed"

#: Vikunja default connection (identical defaults to the MCP server / cli.py).
_DEFAULT_URL = "http://localhost:3456"
_DEFAULT_USER = "blarai"

#: ``(method, url, json_body|None, headers, timeout_s) -> (status_code, parsed_json|None)``.
#: The real transport (urllib to loopback) lives in the dev tier; tests inject a
#: fake. Non-2xx responses come back as a status code (the client raises), so a
#: transport never needs to know Vikunja's error shapes.
Transport = Callable[
    [str, str, "Mapping[str, Any] | None", "Mapping[str, str]", float],
    "tuple[int, Any]",
]


class BridgeConfig(Protocol):
    """The two knobs the bridge reads off a ``FleetDispatchConfig`` (duck-typed so
    a test can pass any object carrying them)."""

    vikunja_bridge: bool
    vikunja_bridge_project_id: int


# ---------------------------------------------------------------------------
# Loopback pin (non-negotiable) + credential resolution
# ---------------------------------------------------------------------------


def is_loopback(host: str | None) -> bool:
    """True iff *host* is a loopback target (``localhost`` / ``127.0.0.0/8`` /
    ``::1``). Anything else — a public host, a LAN IP, an empty host — is False."""
    if not host:
        return False
    h = host.strip().lower().strip("[]")  # tolerate IPv6 brackets
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return h == "localhost"


def assert_loopback(url: str) -> None:
    """Raise ``ValueError`` unless *url*'s host is loopback. The hard pin: this
    fires BEFORE any transport call, so a misconfigured non-local ``VIKUNJA_URL``
    can never open an off-box socket (the caller's fail-soft turns the raise into
    a logged no-op)."""
    host = urllib.parse.urlparse(url).hostname
    if not is_loopback(host):
        raise ValueError(
            f"vikunja_bridge refuses a non-loopback Vikunja host {host!r} — the "
            "bridge is loopback-pinned to localhost/127.0.0.1 (:3456). Set "
            "VIKUNJA_URL to a loopback address."
        )


_dotenv_loaded = False


def _load_dotenv() -> None:
    """Load a gitignored ``.env`` from the repo root / cwd if present (never
    overriding an already-set env var) — the SAME fallback the Vikunja MCP CLI
    uses. Idempotent; a missing file is a silent no-op."""
    global _dotenv_loaded
    if _dotenv_loaded:
        return
    _dotenv_loaded = True
    here = Path(__file__).resolve().parent
    for candidate in (here.parent.parent, Path.cwd()):  # <repo root>, cwd
        env_file = candidate / ".env"
        try:
            if not env_file.is_file():
                continue
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("\"'")
                if key and key not in os.environ:
                    os.environ[key] = value
            break
        except OSError:
            continue


def _resolve_credentials() -> tuple[str, str, str]:
    """``(url, user, password)`` from the SAME source the MCP server reads —
    ``VIKUNJA_URL`` / ``VIKUNJA_USER`` / ``VIKUNJA_PASS`` (env, then ``.env``)."""
    _load_dotenv()
    url = os.environ.get("VIKUNJA_URL", _DEFAULT_URL)
    user = os.environ.get("VIKUNJA_USER", _DEFAULT_USER)
    password = os.environ.get("VIKUNJA_PASS", "")
    return url, user, password


def _default_transport() -> Transport:
    """The real urllib-to-loopback transport, lazily imported from the dev tier
    so ``shared/`` imports no network client (the air-gap import control stays
    green — the socket lives under ``tools/``, the sanctioned dev-side layer)."""
    from tools.dispatch_harness.vikunja_http import urlopen_transport

    return urlopen_transport


# ---------------------------------------------------------------------------
# Minimal Vikunja REST client (mirrors the MCP server's endpoint shapes)
# ---------------------------------------------------------------------------


class _VikunjaClient:
    """A tiny, single-session Vikunja REST client over an injected transport.

    Mirrors the endpoint shapes the MCP server uses (``tools/vikunja_mcp`` in
    devplatform): PUT creates, POST updates (full-object), PUT posts a comment.
    Loopback-pinned at construction; every call is bounded by ``CALL_TIMEOUT_S``.
    """

    def __init__(
        self,
        base_url: str,
        user: str,
        password: str,
        *,
        transport: Transport,
        timeout_s: float = CALL_TIMEOUT_S,
    ) -> None:
        assert_loopback(base_url)  # HARD pin — before any I/O
        self._api = base_url.rstrip("/") + "/api/v1"
        self._user = user
        self._password = password
        self._transport = transport
        self._timeout_s = timeout_s
        self._token: str | None = None

    # -- low-level ----------------------------------------------------------

    def _call(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
        auth: bool = True,
    ) -> Any:
        url = self._api + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {"Content-Type": "application/json"}
        if auth:
            headers["Authorization"] = f"Bearer {self._token or ''}"
        status, parsed = self._transport(method, url, body, headers, self._timeout_s)
        if status >= 400:
            raise RuntimeError(f"Vikunja {method} {path} -> HTTP {status}")
        return parsed

    def login(self) -> None:
        parsed = self._call(
            "POST",
            "/login",
            body={"username": self._user, "password": self._password},
            auth=False,
        )
        token = (parsed or {}).get("token") if isinstance(parsed, dict) else None
        if not token:
            raise RuntimeError("Vikunja login returned no token")
        self._token = str(token)

    # -- task operations ----------------------------------------------------

    def find_task_id(self, project_id: int, marker: str) -> int | None:
        """The id of the task whose title carries *marker* in *project_id*, or
        ``None``. Searches by the run-id substring then confirms the exact
        marker, so a partial match never adopts the wrong ticket."""
        tasks = self._call(
            "GET",
            f"/projects/{project_id}/tasks",
            params={"s": marker, "per_page": 200},
        )
        if not isinstance(tasks, list):
            return None
        for task in tasks:
            if isinstance(task, dict) and marker in str(task.get("title", "")):
                try:
                    return int(task["id"])
                except (KeyError, TypeError, ValueError):
                    continue
        return None

    def create_task(self, project_id: int, title: str, description: str) -> int:
        task = self._call(
            "PUT",
            f"/projects/{project_id}/tasks",
            body={"title": title, "description": description},
        )
        return int(task["id"])

    def get_task(self, task_id: int) -> dict:
        task = self._call("GET", f"/tasks/{task_id}")
        return task if isinstance(task, dict) else {}

    def close_task(self, task_id: int) -> None:
        """Mark a task done using Vikunja's FULL-object POST semantics: fetch
        current, preserve title/description/priority, set ``done=True``, post
        back. A bare ``{"done": True}`` POST would zero the unspecified fields."""
        current = self.get_task(task_id)
        body = {
            "title": current.get("title", ""),
            "description": current.get("description") or "",
            "priority": current.get("priority", 0),
            "done": True,
        }
        self._call("POST", f"/tasks/{task_id}", body=body)

    def add_comment(self, task_id: int, comment: str) -> None:
        self._call("PUT", f"/tasks/{task_id}/comments", body={"comment": comment})

    def move_task_to_bucket(
        self, project_id: int, view_id: int, bucket_id: int, task_id: int
    ) -> None:
        """Move *task_id* into *bucket_id* of kanban *view_id* on *project_id*.

        Vikunja v2.3.0 ``POST /projects/{project}/views/{view}/buckets/{bucket}/tasks``
        ("Update a task bucket" — verified against the live OpenAPI spec). The
        destination bucket rides BOTH the path and the ``models.TaskBucket`` body,
        and ``project_view_id`` pins the view the move applies to."""
        self._call(
            "POST",
            f"/projects/{project_id}/views/{view_id}/buckets/{bucket_id}/tasks",
            body={
                "task_id": task_id,
                "bucket_id": bucket_id,
                "project_view_id": view_id,
            },
        )

    # -- C1 read-surface operations (#843, ADR-039 §2.10) --------------------
    # Low-level, unconditional (no dormancy gate here — see the module-level
    # docstring on the read section below for why): the caller composing a
    # coordinator snapshot decides WHETHER to read; these methods only decide
    # HOW. Every one returns ``[]`` for a non-list body rather than raising,
    # so a malformed/empty page reads as "no more items" to the pagination
    # loop, not a transport error (transport/HTTP errors still raise via
    # ``_call``, exactly like every method above — fail-soft stays the
    # PUBLIC function's job, mirroring the write side).

    def list_tasks_page(self, project_id: int, params: Mapping[str, Any]) -> list:
        """One page of ``GET /projects/{id}/tasks`` (v2.3.0). *params* carries
        ``page``/``per_page`` (the pagination-aware read loop's contract)."""
        result = self._call("GET", f"/projects/{project_id}/tasks", params=params)
        return result if isinstance(result, list) else []

    def list_views(self, project_id: int) -> list:
        """``GET /projects/{id}/views`` (v2.3.0) — every view (List/Kanban/
        Table) so the Kanban view is resolved by KIND, never a hardcoded id."""
        result = self._call("GET", f"/projects/{project_id}/views")
        return result if isinstance(result, list) else []

    def list_buckets(self, project_id: int, view_id: int) -> list:
        """``GET /projects/{id}/views/{view_id}/buckets`` (v2.3.0) — the
        kanban board's buckets (id/title/position/limit)."""
        result = self._call(
            "GET", f"/projects/{project_id}/views/{view_id}/buckets"
        )
        return result if isinstance(result, list) else []

    # -- setup-migration-ONLY write primitives (ADR-039 §2.12.11) -----------
    # NOT part of the runtime read/write surface: these back
    # ensure_bucket/ensure_label below, which are called ONLY by the
    # operator-run substrate-setup migration script
    # (tools/dispatch_harness/coordinator_setup.py) — never by the runtime
    # coordinator, which has no write path to its own workflow structure.

    def list_labels(self) -> list:
        """``GET /labels`` (v2.3.0) — every label (global, not per-project)."""
        result = self._call("GET", "/labels")
        return result if isinstance(result, list) else []

    def create_label(self, title: str, hex_color: str) -> dict:
        result = self._call(
            "PUT", "/labels", body={"title": title, "hex_color": hex_color}
        )
        return result if isinstance(result, dict) else {}

    def create_bucket(self, project_id: int, view_id: int, title: str) -> dict:
        result = self._call(
            "PUT",
            f"/projects/{project_id}/views/{view_id}/buckets",
            body={"title": title},
        )
        return result if isinstance(result, dict) else {}


# ---------------------------------------------------------------------------
# Rendering (structural — pointers + short statuses, never raw logs)
# ---------------------------------------------------------------------------


def _title_marker(run_id: str) -> str:
    return f"{_TITLE_PREFIX}{run_id}{_TITLE_SUFFIX}"


def _clip(text: str, cap: int = 4000) -> str:
    text = str(text)
    return text if len(text) <= cap else text[: cap - 1] + "…"


def _job_ticket_body(run_id: str, goal: str, repo: str) -> str:
    return (
        f"Auto-created by the dispatch→Vikunja bridge (#749) for fleet run "
        f"`{run_id}`.\n\n"
        f"- **repo:** `{repo}`\n"
        f"- **goal:** {_clip(goal, 1000)}\n\n"
        "This ticket carries the ACROSS-jobs outcome: it is updated with the "
        "job verdict at REPORT time and closed only on a GREEN + oracle-passed "
        "scorecard. PARKED-HONEST / STALLED leave it OPEN with the evidence "
        "pointers below — the operator's actionable queue."
    )


def _fmt_evidence(evidence: Mapping[str, Any]) -> list[str]:
    lines: list[str] = []
    for key in sorted(evidence):
        value = evidence[key]
        if isinstance(value, list):
            rendered = ", ".join(str(v) for v in value)
        else:
            rendered = str(value)
        lines.append(f"  - {key}: {_clip(rendered, 1000)}")
    return lines


def _outcome_comment(scorecard: Mapping[str, Any]) -> str:
    verdict = str(scorecard.get("verdict", "") or "UNKNOWN")
    attribution = str(scorecard.get("attribution", "") or "")
    run_id = str(scorecard.get("run_id", "") or "")
    repo = str(scorecard.get("repo", "") or "")
    evidence = scorecard.get("evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    try:
        wall = float(scorecard.get("wall_clock_s", 0.0) or 0.0)
    except (TypeError, ValueError):
        wall = 0.0
    notes = str(scorecard.get("notes", "") or "")

    head = f"### Dispatch outcome: {verdict}"
    if attribution:
        head += f"  (attribution: {attribution})"
    lines = [
        head,
        f"- run: `{run_id}`" if run_id else "- run: (unknown)",
    ]
    if repo:
        lines.append(f"- repo: `{repo}`")
    lines.append(f"- wall-clock: {wall:.0f}s")
    if evidence:
        lines.append("- evidence:")
        lines.extend(_fmt_evidence(evidence))
    if notes:
        lines.append(f"- notes: {_clip(notes, 1000)}")
    lines.append(
        "\n_Posted by the dispatch→Vikunja bridge (#749). Outcomes only, "
        "never heartbeats._"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API — every function is FAIL-SOFT (returns None/False, never raises)
# ---------------------------------------------------------------------------


def _bridge_target(cfg: BridgeConfig) -> int | None:
    """The configured project id if the bridge is enabled AND targeted, else
    ``None`` (0 = unset -> refuse to post; a missing knob -> disabled)."""
    if not bool(getattr(cfg, "vikunja_bridge", False)):
        return None
    project_id = int(getattr(cfg, "vikunja_bridge_project_id", 0) or 0)
    if project_id <= 0:
        logger.warning(
            "vikunja_bridge is on but vikunja_bridge_project_id is unset (0) — "
            "refusing to post (no target project)."
        )
        return None
    return project_id


def _client(transport: Transport | None) -> _VikunjaClient:
    url, user, password = _resolve_credentials()
    return _VikunjaClient(
        url, user, password, transport=transport or _default_transport()
    )


def ensure_job_ticket(
    cfg: BridgeConfig,
    run_id: str,
    goal: str,
    repo: str,
    *,
    transport: Transport | None = None,
) -> int | None:
    """Find-or-create the durable ticket for fleet run *run_id* (idempotent by the
    ``[fleet-job <run_id>]`` title marker) and return its id, or ``None``.

    ``None`` means "did not post": the bridge is off, the project id is unset, or
    a fail-soft error occurred (a Vikunja outage must never affect the run)."""
    project_id = _bridge_target(cfg)
    if project_id is None:
        return None
    try:
        client = _client(transport)
        client.login()
        marker = _title_marker(run_id)
        existing = client.find_task_id(project_id, marker)
        if existing is not None:
            return existing
        title = f"{marker} {_clip(goal, 120)}".rstrip()
        return client.create_task(project_id, title, _job_ticket_body(run_id, goal, repo))
    except Exception as exc:  # noqa: BLE001 — fail-soft: ticket I/O never affects a run
        logger.warning("vikunja_bridge ensure_job_ticket failed (fail-soft): %s", exc)
        return None


def post_outcome(
    cfg: BridgeConfig,
    ticket_id: int,
    scorecard: Mapping[str, Any],
    *,
    transport: Transport | None = None,
) -> bool:
    """Comment the job outcome (verdict / attribution / evidence pointers) on
    *ticket_id*, and CLOSE the ticket ONLY when the verdict is GREEN **and**
    ``evidence.oracle_status == "passed"``.

    That close gate is the FALSE-DONE-shaped lock from #749: a job ticket must
    never close without the oracle-green scorecard. PARKED-HONEST, STALLED, or a
    GREEN whose oracle did not pass all leave the ticket OPEN (commented) — the
    operator's actionable queue. Returns True iff the comment posted."""
    if _bridge_target(cfg) is None:
        return False
    try:
        client = _client(transport)
        client.login()
        client.add_comment(ticket_id, _outcome_comment(scorecard))

        verdict = str(scorecard.get("verdict", "") or "")
        evidence = scorecard.get("evidence")
        evidence = evidence if isinstance(evidence, dict) else {}
        oracle_status = str(evidence.get("oracle_status", "") or "unknown")
        if verdict == _VERDICT_GREEN and oracle_status == _ORACLE_PASSED:
            client.close_task(ticket_id)
            logger.info("vikunja_bridge closed ticket %s (GREEN + oracle passed)", ticket_id)
        return True
    except Exception as exc:  # noqa: BLE001 — fail-soft
        logger.warning("vikunja_bridge post_outcome failed (fail-soft): %s", exc)
        return False


def post_campaign_summary(
    cfg: BridgeConfig,
    ticket_id: int,
    text: str,
    *,
    transport: Transport | None = None,
) -> bool:
    """Post *text* (e.g. the nightly battery's morning report) as one comment on
    the campaign *ticket_id*. Never closes anything. Returns True iff it posted."""
    if _bridge_target(cfg) is None:
        return False
    try:
        client = _client(transport)
        client.login()
        client.add_comment(ticket_id, _clip(text))
        return True
    except Exception as exc:  # noqa: BLE001 — fail-soft
        logger.warning("vikunja_bridge post_campaign_summary failed (fail-soft): %s", exc)
        return False


# ---------------------------------------------------------------------------
# C1 read surface (#843, ADR-039 §2.10) — coordinator READS.
#
# Everything below is READ-ONLY and extends the SAME loopback-pinned /
# fail-soft / transport-split bridge above (ADR-039 §2.3: "the Coordinator's
# read surface extends vikunja_bridge with more read operations over the
# SAME loopback/fail-soft/transport-split pattern, not a second network
# path"). No dormancy gate lives HERE: whether coordinator reads happen at
# all is a [coordinator].enabled decision made by the CALLER (the work-state
# snapshot composer / the /coord status gateway command) BEFORE it reaches
# this module — mirroring how DispatchCoordinator checks its own `enabled`
# flag before touching any collaborator, rather than threading a config
# object through every leaf function. That separation matters here
# specifically because a read's THREE tri-state outcomes (below) must stay
# about "did Vikunja answer", never conflated with a fourth "reads are
# turned off" case a leaf-level gate would invite.
#
# Two disciplines apply to every function below that the write-side above
# did not need:
#
#   * PAGINATION-AWARE (ADR-039 §2.12.2, a verified defect class). Vikunja's
#     server-side ``maxitemsperpage`` (default 50) silently CLAMPS even an
#     explicit larger ``per_page`` request — so trusting a single page for a
#     >50-item project silently under-reads it (the devplatform
#     ``project_summary`` tool was confirmed doing exactly this). Every
#     collection read here loops pages until a SHORT page
#     (``len(page) < per_page``) via :func:`_paginate`, circuit-broken by
#     ``_MAX_PAGES`` so a misbehaving server that never returns a short page
#     cannot hang a heartbeat cycle forever.
#   * TRI-STATE (ADR-039 §2.12.6 / §2.14.4). Every read returns a
#     :class:`ReadResult` distinguishing OK (succeeded, data present) /
#     EMPTY (succeeded, genuinely nothing there) / UNREACHABLE (the read
#     failed — network error, auth failure, malformed body, loopback
#     refusal, timeout; fail-soft, never raised). ``UNREACHABLE`` must NEVER
#     be interpreted as ``EMPTY`` by a caller: a dead Vikunja must not look
#     like a finished backlog, which is the exact silent-stall this whole
#     program exists to prevent (ADR-039 §2.12.6).
#
# Vikunja IDs are resolved BY NAME/KIND at read time (``find_view_by_kind``)
# rather than hardcoded — the project's own stale-label/bucket-id lesson
# (ADR-039 §2.12.11) — so a fresh or re-migrated project needs no code change.
# ---------------------------------------------------------------------------


class ReadStatus(str, Enum):
    """Tri-state discipline for coordinator reads (ADR-039 §2.12.6)."""

    OK = "ok"
    """The read succeeded and returned at least one item."""

    EMPTY = "empty"
    """The read succeeded and returned ZERO items — a real, known state (e.g.
    a project genuinely has no open tasks right now). Distinct from
    UNREACHABLE on purpose: an EMPTY board is quiet-queue-tripwire-eligible;
    an UNREACHABLE one is neither — it is an UNKNOWN state that must be
    surfaced honestly, never assumed empty."""

    UNREACHABLE = "unreachable"
    """The read failed (network error, auth failure, malformed response,
    loopback refusal, timeout, or an unresolvable view/bucket lookup).
    Fail-soft — never raised to the caller — but the caller MUST be able to
    tell this apart from EMPTY. See ``test_unreachable_never_renders_as_empty``
    for the regression lock."""


@dataclass(frozen=True)
class ReadResult:
    """The tri-state result of every coordinator read in this section.

    ``items`` is always a concrete tuple (never ``None``) so a caller can
    iterate unconditionally without a None-check; ``error`` carries a short
    fail-soft reason ONLY when ``status is UNREACHABLE``.
    """

    status: ReadStatus
    items: tuple[dict[str, Any], ...] = ()
    error: str = ""

    @property
    def ok(self) -> bool:
        """True for OK or EMPTY (the read itself succeeded); False only for
        UNREACHABLE. A caller that only needs "did this work" (not the
        OK-vs-EMPTY distinction) should test THIS, never
        ``status == ReadStatus.OK`` alone — that would wrongly treat a
        successful-but-empty read as a failure."""
        return self.status is not ReadStatus.UNREACHABLE


def _read_result(items: Sequence[Mapping[str, Any]]) -> ReadResult:
    """OK (non-empty) or EMPTY (empty) from a successfully-fetched list —
    never UNREACHABLE (that path is constructed at the ``except`` site)."""
    materialized = tuple(dict(i) for i in items if isinstance(i, Mapping))
    return ReadResult(
        status=ReadStatus.OK if materialized else ReadStatus.EMPTY,
        items=materialized,
    )


def _unreachable(reason: str) -> ReadResult:
    return ReadResult(status=ReadStatus.UNREACHABLE, items=(), error=_clip(reason, 500))


#: Vikunja's server-side ``maxitemsperpage`` default (ADR-039 §2.12.2) — the
#: page size every paginated read below requests. Requesting more is silently
#: clamped by the server, so pagination-correctness depends on requesting
#: exactly this and looping on a short page, never on a larger per_page being
#: honored.
DEFAULT_PAGE_SIZE: int = 50

#: Circuit breaker for :func:`_paginate` — at the default page size this is
#: 50,000 items. A misbehaving server that never returns a short page must
#: not hang a coordinator read (and therefore a heartbeat cycle) forever.
_MAX_PAGES: int = 1000


def _paginate(
    fetch_page: Callable[[int], list],
    *,
    per_page: int = DEFAULT_PAGE_SIZE,
) -> list[dict]:
    """Loop ``fetch_page(page_number)`` (1-based) until a SHORT page (fewer
    than *per_page* items) or an empty page, bounded by ``_MAX_PAGES``.

    This is the ONE pagination loop every collection read below shares.
    Vikunja's ``maxitemsperpage`` silently clamps a too-large ``per_page``
    request, so trusting a single page is a silent-truncation bug — this is
    the fix (ADR-039 §2.12.2 / operational-maturity item 2)."""
    items: list[dict] = []
    page = 1
    while page <= _MAX_PAGES:
        batch = fetch_page(page)
        if not batch:
            break
        items.extend(b for b in batch if isinstance(b, dict))
        if len(batch) < per_page:
            break
        page += 1
    return items


def find_view_by_kind(views: Sequence[Mapping[str, Any]], kind: str) -> int | None:
    """The id of the first view whose ``view_kind`` matches *kind*
    (case-insensitive), or ``None`` if no view matches.

    Name/kind-resolution helper — Vikunja view ids are NEVER hardcoded
    (ADR-039 §2.12.11): the coordinator resolves the Kanban view for a
    project at read time, the same way a human clicking "Kanban" would."""
    kind_lower = kind.strip().lower()
    for v in views:
        if str(v.get("view_kind", "")).strip().lower() == kind_lower:
            try:
                return int(v["id"])  # type: ignore[index]
            except (KeyError, TypeError, ValueError):
                continue
    return None


def _read_all_tasks(client: "_VikunjaClient", project_id: int) -> list[dict]:
    """The full (paginated) task list for *project_id* — done AND open. The
    shared primitive :func:`list_open_tasks`/:func:`project_read_summary`/
    :func:`board_state` all build on."""
    return _paginate(
        lambda page: client.list_tasks_page(
            project_id, {"page": page, "per_page": DEFAULT_PAGE_SIZE}
        )
    )


def list_open_tasks(
    project_id: int, *, transport: Transport | None = None
) -> ReadResult:
    """Every NOT-done task in *project_id*, paginated to completeness.

    Filters client-side on ``done`` deliberately rather than a server-side
    filter query: Vikunja's filter-query syntax (``filter_by``/``filter``)
    is a second API-contract surface this bridge does not otherwise depend
    on, and every task page is already being read for pagination-correctness
    regardless — so client-side filtering is both simpler and no less
    correct. Each returned dict carries Vikunja's native fields verbatim
    (including ``labels`` and ``due_date`` — the classes-of-service inputs
    a later phase computes over; this read does not interpret them)."""
    try:
        client = _client(transport)
        client.login()
        open_tasks = [
            t for t in _read_all_tasks(client, project_id)
            if not bool(t.get("done", False))
        ]
        return _read_result(open_tasks)
    except Exception as exc:  # noqa: BLE001 — fail-soft, tri-state UNREACHABLE
        logger.warning("vikunja_bridge list_open_tasks failed (fail-soft): %s", exc)
        return _unreachable(str(exc))


def list_all_tasks(
    project_id: int, *, transport: Transport | None = None
) -> ReadResult:
    """Every task (done AND open) in *project_id*, paginated to
    completeness — the population :mod:`shared.fleet.flow_metrics`'s cycle
    time / throughput functions need (they read each task's own ``done`` /
    ``done_at`` fields directly; unlike :func:`list_open_tasks` this does
    NOT filter). Open tasks can be derived from this same read by filtering
    client-side (``not t["done"]``) — the deliberate reason
    :func:`shared.fleet.work_state.read_project_work_state` calls this
    ONCE rather than this-and-list_open_tasks separately: two independent
    paginated reads of the same project could observe different snapshots
    of a board mutating between calls, silently double-counting or
    under-counting a task that changed state mid-read."""
    try:
        client = _client(transport)
        client.login()
        return _read_result(_read_all_tasks(client, project_id))
    except Exception as exc:  # noqa: BLE001 — fail-soft, tri-state UNREACHABLE
        logger.warning("vikunja_bridge list_all_tasks failed (fail-soft): %s", exc)
        return _unreachable(str(exc))


def project_read_summary(
    project_id: int, *, transport: Transport | None = None
) -> ReadResult:
    """One rollup dict for *project_id*:
    ``{"project_id", "total", "open", "done", "labels": {label_title: open_count}}``.

    ``items`` carries exactly one dict on OK. ``EMPTY`` means the project has
    ZERO tasks at all (not merely zero OPEN — a fully-done project is a
    legitimate "nothing left open" state, still reported distinctly from
    UNREACHABLE)."""
    try:
        client = _client(transport)
        client.login()
        all_tasks = _read_all_tasks(client, project_id)
        if not all_tasks:
            return ReadResult(status=ReadStatus.EMPTY)
        open_tasks = [t for t in all_tasks if not bool(t.get("done", False))]
        label_counts: dict[str, int] = {}
        for t in open_tasks:
            for label in t.get("labels") or []:
                if isinstance(label, Mapping):
                    name = str(label.get("title", "")).strip()
                    if name:
                        label_counts[name] = label_counts.get(name, 0) + 1
        summary = {
            "project_id": project_id,
            "total": len(all_tasks),
            "open": len(open_tasks),
            "done": len(all_tasks) - len(open_tasks),
            "labels": label_counts,
        }
        return ReadResult(status=ReadStatus.OK, items=(summary,))
    except Exception as exc:  # noqa: BLE001 — fail-soft, tri-state UNREACHABLE
        logger.warning("vikunja_bridge project_read_summary failed (fail-soft): %s", exc)
        return _unreachable(str(exc))


def list_views(
    project_id: int, *, transport: Transport | None = None
) -> ReadResult:
    """Every view (List/Kanban/Table/...) on *project_id* — the name/kind
    resolution source for :func:`find_view_by_kind` (never a hardcoded view
    id)."""
    try:
        client = _client(transport)
        client.login()
        return _read_result(client.list_views(project_id))
    except Exception as exc:  # noqa: BLE001 — fail-soft, tri-state UNREACHABLE
        logger.warning("vikunja_bridge list_views failed (fail-soft): %s", exc)
        return _unreachable(str(exc))


def list_buckets(
    project_id: int, view_id: int, *, transport: Transport | None = None
) -> ReadResult:
    """The buckets (id/title/position/limit) of *view_id* on *project_id* —
    the raw board columns, WITHOUT the open-task grouping :func:`board_state`
    adds. Exposed separately so a caller that already resolved a view id
    (e.g. via :func:`list_views` + :func:`find_view_by_kind`, cached) can
    skip the extra views round-trip :func:`board_state` performs."""
    try:
        client = _client(transport)
        client.login()
        return _read_result(client.list_buckets(project_id, view_id))
    except Exception as exc:  # noqa: BLE001 — fail-soft, tri-state UNREACHABLE
        logger.warning("vikunja_bridge list_buckets failed (fail-soft): %s", exc)
        return _unreachable(str(exc))


def health_check(*, transport: Transport | None = None) -> ReadResult:
    """A minimal Vikunja reachability probe (login only, no board data) — the
    substrate-liveness leg the work-state snapshot composer reads.

    ``OK`` with one ``{"reachable": True}`` item on a successful login;
    ``UNREACHABLE`` otherwise. ``EMPTY`` is never returned — reachability is
    binary, so this function's tri-state degenerates to the two outcomes
    that actually apply (mirrors the loopback/credential/network failure
    modes every other read in this section already handles)."""
    try:
        client = _client(transport)
        client.login()
        return ReadResult(status=ReadStatus.OK, items=({"reachable": True},))
    except Exception as exc:  # noqa: BLE001 — fail-soft, tri-state UNREACHABLE
        logger.warning("vikunja_bridge health_check failed (fail-soft): %s", exc)
        return _unreachable(str(exc))


def board_state(
    project_id: int, *, transport: Transport | None = None
) -> ReadResult:
    """The kanban board for *project_id*: every bucket (id/title/position/
    limit) enriched with a ``"tasks"`` key holding its OPEN tasks.

    Resolves the Kanban view by KIND (never a hardcoded id, ADR-039
    §2.12.11) via :func:`find_view_by_kind`; ``UNREACHABLE`` (with a clear
    ``error``) if the project has no Kanban view, the buckets call fails, or
    the task read fails. ``EMPTY`` if the Kanban view genuinely has zero
    buckets. A bucket with zero open tasks still appears with
    ``"tasks": []`` — the bucket's PRESENCE (not its task count) is what
    ``EMPTY``/``OK`` describes here; per-bucket emptiness is for the caller
    to read off each bucket's own ``tasks`` list.

    Grouping is done by cross-referencing the paginated open-task read on
    each task's ``bucket_id`` — a task whose ``bucket_id`` is absent/None
    (a project with a Kanban view but a task never dragged onto it) is
    simply not attributed to any bucket, not dropped from the underlying
    open-task count elsewhere."""
    try:
        client = _client(transport)
        client.login()
        views = client.list_views(project_id)
        view_id = find_view_by_kind(views, "kanban")
        if view_id is None:
            return _unreachable(f"project {project_id} has no kanban view")
        buckets = client.list_buckets(project_id, view_id)
        open_tasks = [
            t for t in _read_all_tasks(client, project_id)
            if not bool(t.get("done", False))
        ]
        by_bucket: dict[int, list[dict]] = {}
        for t in open_tasks:
            bid = t.get("bucket_id")
            if bid is None:
                continue
            try:
                by_bucket.setdefault(int(bid), []).append(t)
            except (TypeError, ValueError):
                continue
        enriched: list[dict] = []
        for b in buckets:
            if not isinstance(b, Mapping):
                continue
            b = dict(b)
            try:
                bid = int(b.get("id"))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                b["tasks"] = []
            else:
                b["tasks"] = by_bucket.get(bid, [])
            enriched.append(b)
        return _read_result(enriched)
    except Exception as exc:  # noqa: BLE001 — fail-soft, tri-state UNREACHABLE
        logger.warning("vikunja_bridge board_state failed (fail-soft): %s", exc)
        return _unreachable(str(exc))


# ---------------------------------------------------------------------------
# Substrate-setup migration primitives (ADR-039 §2.12.11) — OPERATOR-RUN ONLY
#
# These three functions are the ONLY write-shaped operations in the C1 read
# surface, and they exist for exactly one caller:
# ``tools/dispatch_harness/coordinator_setup.py``, the idempotent
# discover-or-create Kanban substrate migration the OPERATOR runs via the
# dev channel (never the runtime Coordinator, which the design deliberately
# gives no write path to its own workflow structure — ADR-039 §2.12.11:
# "the Coordinator never creates its own workflow structure"). They are
# grouped here, not scattered into the read-surface section above, and each
# is idempotent (find-by-NAME first, create only if genuinely missing) so a
# re-run of the setup script is always safe.
# ---------------------------------------------------------------------------


def list_labels(*, transport: Transport | None = None) -> ReadResult:
    """Every label (global, not per-project) — the discovery half of
    :func:`ensure_label`, also useful standalone for the setup script's
    orphan-flagging pass (ADR-039 §2.9's paired tenet)."""
    try:
        client = _client(transport)
        client.login()
        return _read_result(client.list_labels())
    except Exception as exc:  # noqa: BLE001 — fail-soft, tri-state UNREACHABLE
        logger.warning("vikunja_bridge list_labels failed (fail-soft): %s", exc)
        return _unreachable(str(exc))


def ensure_label(
    title: str, hex_color: str, *, transport: Transport | None = None
) -> int | None:
    """Find-or-create a label by *title* (idempotent) and return its id, or
    ``None`` on failure (fail-soft — the setup script surfaces this as a
    migration-step failure to the OPERATOR running it; never silently
    retried, never invoked by the runtime coordinator)."""
    try:
        client = _client(transport)
        client.login()
        for label in client.list_labels():
            if isinstance(label, Mapping) and str(label.get("title", "")) == title:
                try:
                    return int(label["id"])  # type: ignore[index]
                except (KeyError, TypeError, ValueError):
                    continue
        created = client.create_label(title, hex_color)
        try:
            return int(created["id"])
        except (KeyError, TypeError, ValueError):
            return None
    except Exception as exc:  # noqa: BLE001 — fail-soft
        logger.warning("vikunja_bridge ensure_label(%r) failed (fail-soft): %s", title, exc)
        return None


def ensure_bucket(
    project_id: int, view_id: int, title: str, *, transport: Transport | None = None
) -> int | None:
    """Find-or-create a bucket by *title* on (*project_id*, *view_id*)
    (idempotent) and return its id, or ``None`` on failure (fail-soft — see
    :func:`ensure_label`)."""
    try:
        client = _client(transport)
        client.login()
        for bucket in client.list_buckets(project_id, view_id):
            if isinstance(bucket, Mapping) and str(bucket.get("title", "")) == title:
                try:
                    return int(bucket["id"])  # type: ignore[index]
                except (KeyError, TypeError, ValueError):
                    continue
        created = client.create_bucket(project_id, view_id, title)
        try:
            return int(created["id"])
        except (KeyError, TypeError, ValueError):
            return None
    except Exception as exc:  # noqa: BLE001 — fail-soft
        logger.warning(
            "vikunja_bridge ensure_bucket(%r) failed (fail-soft): %s", title, exc
        )
        return None


# ---------------------------------------------------------------------------
# C2 lifecycle: board movement (#844, ADR-039 §2.8 / §2.13 item 5)
#
# The write-side sibling of the C1 read surface: a card moves to the bucket the
# DETERMINISTIC ruler chose
# (``shared.fleet.coord_lifecycle.resolve_board_transition``) on a real dispatch
# event, never on model opinion. The forged-Done lock lives IN that ruler (a Done
# transition needs ``oracle_passed AND merged``), so this layer only EXECUTES an
# already-decided move — it makes no lifecycle judgment of its own.
#
# Extends the SAME loopback-pinned / fail-soft / transport-split bridge; the target
# bucket is resolved BY TITLE and the kanban view BY KIND at write time (never a
# hardcoded id — ADR-039 §2.12.11), exactly like the read surface.
#
# DORMANCY (as with the C1 read surface): NO ``[coordinator].enabled`` gate lives
# HERE — the ENABLED decision belongs to the CALLER (the future C2 dispatch-event
# hook, which gates on ``[coordinator].enabled`` before acting). This function has
# NO live caller today: nothing in a dispatch/boot path invokes it, so importing
# this module moves no card. It is the capability the dormant C2 hook will consult.
# ---------------------------------------------------------------------------


def find_bucket_by_title(
    buckets: Sequence[Mapping[str, Any]], title: str
) -> int | None:
    """The id of the first bucket whose ``title`` matches *title*
    (case-insensitive), or ``None``. The name-resolution sibling of
    :func:`find_view_by_kind` — a kanban bucket is resolved by its board-legible
    title (``"In Progress"``, ``"Done"``), never a hardcoded id, so a re-migrated
    or per-install board needs no code change (ADR-039 §2.12.11)."""
    title_lower = title.strip().lower()
    for b in buckets:
        if str(b.get("title", "")).strip().lower() == title_lower:
            try:
                return int(b["id"])  # type: ignore[index]
            except (KeyError, TypeError, ValueError):
                continue
    return None


@dataclass(frozen=True)
class BoardMoveResult:
    """The fail-soft outcome of a :func:`move_job_card` call.

    ``moved`` is True ONLY when the card was actually relocated. ``reason`` is an
    operator-legible explanation for every non-move (no kanban view, unknown
    bucket title, no ticket for the run, or a transport failure) — a coordinator
    that cannot move a card must say WHY, never fail silently."""

    moved: bool
    reason: str
    bucket_id: int | None = None


def move_job_card(
    project_id: int,
    run_id: str,
    to_bucket_title: str,
    *,
    transport: Transport | None = None,
) -> BoardMoveResult:
    """Move the fleet-run *run_id*'s job ticket to the bucket titled
    *to_bucket_title* on *project_id*'s kanban board — FAIL-SOFT.

    Driven by the deterministic ruler: the caller passes
    ``resolve_board_transition(...).to_bucket`` (In Progress / Ready / Done). The
    forged-Done lock is UPSTREAM in that ruler, so a caller can never ask this to
    move a card to Done without the oracle-green + merged facts having produced a
    Done transition first.

    Resolves the kanban view BY KIND and the destination bucket BY TITLE at write
    time (never hardcoded ids), finds the ticket by its ``[fleet-job <run_id>]``
    title marker, then issues the move. Every failure — no kanban view, unknown
    bucket, no ticket, a Vikunja outage — returns ``BoardMoveResult(moved=False,
    reason=...)`` and is logged; NOTHING raises (a ticket-board outage must never
    affect a dispatch/battery run, exactly like the #749 write side)."""
    try:
        client = _client(transport)
        client.login()

        views = client.list_views(project_id)
        view_id = find_view_by_kind(views, "kanban")
        if view_id is None:
            return BoardMoveResult(False, f"project {project_id} has no kanban view")

        buckets = client.list_buckets(project_id, view_id)
        bucket_id = find_bucket_by_title(buckets, to_bucket_title)
        if bucket_id is None:
            return BoardMoveResult(
                False, f"no bucket titled {to_bucket_title!r} on the kanban board"
            )

        marker = _title_marker(run_id)
        task_id = client.find_task_id(project_id, marker)
        if task_id is None:
            return BoardMoveResult(
                False, f"no job ticket for run {run_id!r} (marker {marker!r})"
            )

        client.move_task_to_bucket(project_id, view_id, bucket_id, task_id)
        logger.info(
            "vikunja_bridge moved run %s card to %r (bucket %d)",
            run_id,
            to_bucket_title,
            bucket_id,
        )
        return BoardMoveResult(
            True, f"moved to {to_bucket_title!r}", bucket_id=bucket_id
        )
    except Exception as exc:  # noqa: BLE001 — fail-soft: board I/O never affects a run
        logger.warning("vikunja_bridge move_job_card failed (fail-soft): %s", exc)
        return BoardMoveResult(False, f"transport failure: {exc}")


def post_task_comment(
    task_id: int,
    comment: str,
    *,
    transport: Transport | None = None,
) -> bool:
    """Post *comment* on Vikunja task *task_id* — FAIL-SOFT (the stall-comment sink).

    The write-side wiring the C2 stall-comments limb
    (:func:`shared.fleet.coord_stall_monitor.run_stall_cycle`) posts through: one
    comment per stall EPISODE, outcomes-only (the anti-firehose invariant — NEVER a
    per-heartbeat comment; the dedup lives in the caller's seen-set, not here).

    Returns ``True`` iff the comment posted, ``False`` on ANY trouble (a comment
    attaches to the task directly — no bucket/view resolution needed — so the only
    failure modes are a bad id, a Vikunja outage, or a timeout). Nothing raises: a
    ticket-board outage must never affect a dispatch/heartbeat run, exactly like
    :func:`move_job_card` and the #749 write side."""
    try:
        client = _client(transport)
        client.login()
        client.add_comment(task_id, comment)
        logger.info("vikunja_bridge posted stall comment on task %d", task_id)
        return True
    except Exception as exc:  # noqa: BLE001 — fail-soft: board I/O never affects a run
        logger.warning("vikunja_bridge post_task_comment failed (fail-soft): %s", exc)
        return False
