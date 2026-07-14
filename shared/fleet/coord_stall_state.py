"""Coordinator stall-comment seen-set state — cross-cycle dedup working-state (#844 C2).

The C2 stall-comments limb (ADR-039 §2.8) posts EXACTLY ONE Vikunja comment (and
one operator-surface entry) per stall EPISODE, never one per heartbeat cycle — the
anti-firehose invariant the #749 bridge already enforces for job tickets ("outcomes
only, never heartbeats"). The pure detection + dedup math lives in
:mod:`shared.fleet.coord_lifecycle` (``detect_stalls`` -> ``StallSignal`` ->
``new_stall_signals``); that module is stateless by design and says so — "State
lives in the caller." THIS module is that caller's state: the small, durable
seen-set of stall fingerprints carried across cycles.

WHY PLAINTEXT — the affirmed precedent (LA 2026-07-13; recorded, not implied)
----------------------------------------------------------------------------
This is the FIRST coordinator *runtime* state, as distinct from the coordinator's
*proposal* state (which is the born-encrypted :mod:`shared.coordinator.proposal_store`).
The Lead Architect affirmed the storage posture explicitly, and it is an
APPLICATION OF EXISTING DOCTRINE, not a new trust posture — hence NO
``DECISION_REGISTER`` row:

    non-content-bearing coordinator runtime metadata  -> plaintext, owner-DACL JSON
    content-bearing coordinator state (proposals,      -> born-encrypted
      digests, ledgers)                                  (ADR-039 §2.13 item 2)

ADR-039 §2.13 item 2 scopes born-encryption to *content-bearing* stores by name —
the proposal-staging store, the briefing ledger, the shadow journal ("goals,
ticket text"). A stall fingerprint is none of those: it is a deterministic
``"{service_class}:{task_id}"`` string
(:func:`shared.fleet.coord_lifecycle.stall_fingerprint`) — a public
class-of-service enum value plus a Vikunja task id already visible on the loopback
board. Encrypting it would be machinery the data does not warrant, and — worse —
would couple stall *detection* to keystore availability (a missing DEK must never
stop the coordinator noticing a stall). So this store mirrors
:mod:`shared.fleet.swap_state`'s idiom (plaintext JSON, atomic ``temp + os.replace``),
which likewise persists non-sensitive runtime facts ("NO conversation content —
privacy-absolute"), and adds an owner-only DACL
(:func:`shared.security.file_dacl.ensure_owner_only_dacl`) as defense-in-depth.

WHY FAIL-SOFT, AND WHAT "LOSS" COSTS — the tightened reasoning
--------------------------------------------------------------
The seen-set is TRANSIENT DEDUP WORKING-STATE, not an audit record and NOT
recomputable from a board read: it is the post-*history* of which stalls have
already been commented, and Vikunja carries no such history. Losing it (a missing
file on first run, a corrupt read, a wiped state dir) is therefore fail-soft by
COST, not by reconstruction — an empty seen-set means at most ONE duplicate
comment per currently-stalled item on the next cycle, after which the set
re-converges. That bounded, self-healing cost is exactly why plaintext-with-atomic-
write is sufficient and a heavier store is not. Every read here degrades to the
empty set rather than raising.

EPISODE SEMANTICS (not task-lifetime; the pruning contract)
-----------------------------------------------------------
A fingerprint is pruned when the stall CLEARS (the item leaves ``detect_stalls``
output), NOT only when the task closes. One comment per stall EPISODE: a task that
re-stalls after being resolved is a NEW episode and earns a fresh comment, never
silently suppressed forever. The pruning is intrinsic to the cycle's set algebra
(:mod:`shared.fleet.coord_stall_monitor`): the persisted set each cycle is the
still-stalled-and-already-seen plus the newly-posted, so a cleared fingerprint
simply falls out.

DORMANCY: this module writes to disk only when a live cycle calls it, and no
production boot path runs a cycle today (the C3 heartbeat / a C2 dispatch-event
hook wires it later, dormant behind ``[coordinator]``). Importing it arms nothing.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from shared.fleet.dispatch import FleetDispatchConfig
from shared.fleet.swap_ops import state_dir
from shared.security.file_dacl import ensure_owner_only_dacl


@dataclass(frozen=True)
class StallSeenState:
    """The cross-cycle set of stall fingerprints already commented + surfaced.

    ``fingerprints`` are :func:`shared.fleet.coord_lifecycle.stall_fingerprint`
    values (``"{service_class}:{task_id}"``) — non-content-bearing metadata.
    ``updated_at`` is an ISO-8601 stamp supplied by the caller (this layer never
    reads the clock), for operator-legible "last cycle" reporting only; it is
    advisory, never a gate."""

    fingerprints: frozenset[str] = frozenset()
    updated_at: str = ""


def coordinator_state_dir(config: FleetDispatchConfig) -> Path:
    """The coordinator's on-disk state dir — a sibling of ``fleet-swap`` under the
    same state root, so all fleet/coordinator runtime state shares one home."""
    return state_dir(config) / "coordinator"


def default_stall_seen_path(config: FleetDispatchConfig) -> Path:
    """The default seen-set file location (``.../coordinator/stall_seen.json``)."""
    return coordinator_state_dir(config) / "stall_seen.json"


def read_seen_state(path: Path) -> StallSeenState:
    """Read the seen-set, or an EMPTY state on ANY trouble (fail-soft).

    Missing file, unreadable file, malformed JSON, or a wrong-shaped payload all
    degrade to the empty set — the bounded, self-healing "<=1 duplicate comment"
    cost documented in the module header, never a raise. ``fingerprints`` is
    rebuilt element-by-element keeping only non-empty strings, so a
    partially-corrupt file can never inject a non-string fingerprint into the
    set."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return StallSeenState()
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return StallSeenState()
    if not isinstance(data, dict):
        return StallSeenState()
    raw_fingerprints = data.get("fingerprints")
    if not isinstance(raw_fingerprints, (list, tuple)):
        return StallSeenState()
    fingerprints = frozenset(
        fp for fp in raw_fingerprints if isinstance(fp, str) and fp
    )
    updated_at = data.get("updated_at")
    return StallSeenState(
        fingerprints=fingerprints,
        updated_at=updated_at if isinstance(updated_at, str) else "",
    )


def _atomic_write(path: Path, text: str) -> None:
    """Write-ahead, atomic: temp + ``os.replace`` — never a torn half-record
    (mirrors :func:`shared.fleet.swap_state._atomic_write`)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)  # atomic rename on Windows + POSIX


def write_seen_state(state: StallSeenState, *, path: Path) -> None:
    """Persist the seen-set atomically, then apply an owner-only DACL.

    The write is atomic (temp + ``os.replace``) so a crash mid-write never leaves a
    torn file — combined with the fail-soft read, that is the whole crash-safety
    contract this non-content-bearing store needs. Unlike
    :func:`shared.fleet.swap_state.reconcile_swap_state` there is no external
    process state to converge: the NEXT cycle re-derives the correct set from
    fresh detection, so the cycle IS the reconcile. The owner-only DACL
    (:func:`shared.security.file_dacl.ensure_owner_only_dacl`) is fail-safe
    defense-in-depth — on a non-Windows host or any ACL error it is a logged
    no-op, never a raise, so persistence never fails on hardening."""
    payload = {
        "fingerprints": sorted(state.fingerprints),
        "updated_at": state.updated_at,
    }
    _atomic_write(path, json.dumps(payload, indent=2))
    ensure_owner_only_dacl(path)
