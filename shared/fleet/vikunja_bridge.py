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
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

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
