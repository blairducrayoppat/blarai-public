"""Gateway-side coordinator for ``/coord`` — the C1 read surface (#843).

ONE command today: ``/coord status`` — a deterministic, READ-ONLY report of
the Coordinator's "state of the work": fleet-swap state, the fleet queue,
the latest run's outcomes, the battery campaign (if configured), and every
configured Vikunja project's board + flow metrics. Mirrors
``dispatch_coordinator.DispatchCoordinator``'s pattern deliberately —
gateway-side interception BEFORE prompt dispatch, no model call, dormancy
gated by ``[coordinator].enabled`` (default ``False``) checked FIRST, before
any collaborator is touched.

Command surface is deliberately MINIMAL for C1: this module changes
NOTHING — no proposal queue, no approve/reject, no write path of any kind.
Extending it (stall detection, redispatch proposals, work origination,
graduated autonomy) is C2-C5 territory under the self-governance boundary
ADR-039 defines and ``#848`` implements; this module does not implement — or
need — any of those controls, because it has no action surface for them to
bound. ``/coord status`` is read-only by construction, not merely by policy.

Its rendered output is composed by :mod:`shared.fleet.coord_render`, which
neutralizes untrusted ticket-derived free text BEFORE interpolation (ADR-039
§2.7 / §2.12.13 — "ticket-title injection must not become chat injection").
The reply is persisted the SAME way ``/dispatch status``'s is — an
INFORMATIONAL turn (see ``TransportGateway._persist_informational_turn``),
which the gateway's existing history filter already excludes from ever
re-entering the model's context on a later turn (only 'approved' assistant
turns are forwarded into prompt history). The render-time neutralization is
additional, deliberate defense-in-depth on top of that structural exclusion
— see the module docstring in ``coord_render.py`` for the full rationale.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

from shared.fleet import coord_render as cr
from shared.fleet import vikunja_bridge as vb
from shared.fleet import work_state as ws
from shared.fleet.dispatch import FleetDispatchConfig

logger = logging.getLogger(__name__)

_PREFIX = "/coord"


@dataclass(frozen=True)
class CoordCommand:
    kind: str  # "status" | "unknown" — C1 implements ONLY status
    raw: str = ""  # the unrecognized subcommand text, for an honest error message


def parse_coord_command(text: str) -> CoordCommand | None:
    """Parse a ``/coord …`` line, or return ``None`` for a normal prompt.

    C1 implements ONLY ``status``. A bare ``/coord`` is treated as
    ``/coord status`` (novice-friendly default — "tell me what's going on"
    without memorizing a subcommand, mirroring how the rest of this
    project's slash commands default to their most useful bare form). Any
    OTHER subcommand text parses to ``kind="unknown"`` — surfaced as an
    honest "not available yet" message by the coordinator, never silently
    reinterpreted as ``status`` (a silent reinterpretation would be
    confusing: an operator typing ``/coord approve`` expecting an error
    must not be shown an unrelated status report instead). C2+ widens this
    parser to real write-shaped subcommands (propose/approve/…) under the
    self-governance boundary; C1 has no such commands to route to."""
    s = text.strip()
    if s.lower() != _PREFIX and not s.lower().startswith(_PREFIX + " "):
        return None
    rest = s[len(_PREFIX):].strip()
    low = rest.lower()
    if low == "" or low == "status" or low.startswith("status "):
        return CoordCommand(kind="status")
    return CoordCommand(kind="unknown", raw=rest)


class CoordCoordinator:
    """Turns a parsed ``/coord`` command into a read-only status report.

    Dormant by construction: with ``enabled=False`` (the shipped default)
    this NEVER touches :mod:`shared.fleet.vikunja_bridge` or
    :mod:`shared.fleet.work_state` — the flag is checked FIRST, mirroring
    ``DispatchCoordinator.handle_command``'s enabled-gate-first pattern
    exactly, so dormancy is a property of the CODE PATH, not merely an
    observation that the read functions happen to go unreached in
    practice.
    """

    def __init__(
        self,
        *,
        enabled: bool,
        fleet_config: FleetDispatchConfig,
        coordinator_projects: Mapping[str, int] | None = None,
        campaign_state_path: Path | None = None,
        stall_seen_path: Path | None = None,
        vikunja_transport: vb.Transport | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._enabled = bool(enabled)
        self._fleet_config = fleet_config
        self._coordinator_projects: dict[str, int] = dict(coordinator_projects or {})
        self._campaign_state_path = campaign_state_path
        self._stall_seen_path = stall_seen_path
        self._vikunja_transport = vikunja_transport
        self._clock = clock

    async def handle_command(self, session_id: str, command: CoordCommand) -> str:
        if not self._enabled:
            return (
                "Coordinator reads are off. It's dormant by default — enable it "
                "with [coordinator].enabled = true in the orchestrator config."
            )
        if command.kind == "unknown":
            return (
                f"'/coord {command.raw}' isn't available yet — today only "
                "`/coord status` is built (the C1 read surface). Later phases "
                "add proposal/approval commands under their own governance gates."
            )
        try:
            return await asyncio.to_thread(self._status)
        except Exception as exc:  # noqa: BLE001 — surface, never crash the turn
            logger.error(
                "Coord status failed for session=%s: %s", session_id, exc, exc_info=True
            )
            return f"Coordinator status failed (Fail-Closed): {exc}"

    def _status(self) -> str:
        """Compose the work-state snapshot + render it. Runs in a thread
        (file + loopback-HTTP reads) — mirrors
        ``DispatchCoordinator._assemble_status``."""
        snapshot = ws.compose_work_state(
            fleet_config=self._fleet_config,
            coordinator_projects=self._coordinator_projects,
            now=self._clock(),
            campaign_state_path=self._campaign_state_path,
            stall_seen_path=self._stall_seen_path,
            vikunja_transport=self._vikunja_transport,
        )
        return cr.render_status(snapshot)
