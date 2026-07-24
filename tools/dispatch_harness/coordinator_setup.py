"""Coordinator Kanban substrate setup — OPERATOR-RUN migration.

(#843, ADR-039 §2.12.11 / §2.9's paired tenet.)

Idempotent discover-or-create: ensures the buckets + labels the
Coordinator's Kanban method (ADR-039 §2.8) needs exist in a Vikunja
project, resolving every id BY NAME at run time — this project's own
stale-label-id lesson (never a hardcoded id anywhere downstream). Runs
BIDIRECTIONALLY per the §2.9 paired tenet ("scaffolding is retired by the
thing that replaces it"): discover-or-create (:func:`run_setup`) AND
flag-orphans (:func:`find_orphans` — labels/buckets this doctrine no
longer references, surfaced as digest curation candidates; REMOVAL is
always human-approved here, never automatic).

**THIS SCRIPT IS OPERATOR-RUN, NEVER A COORDINATOR ACTION.** The runtime
Coordinator has no write path to its own workflow structure — ADR-039
§2.12.11 states this explicitly: "the buckets/labels/filters the method
needs are created by an idempotent discover-or-create setup script,
executed via the dev channel at C1 — the Coordinator never creates its own
workflow structure." This script IS that setup script: a human runs it,
once per Vikunja project the Coordinator will report on (and again
whenever a new ``[coordinator].projects`` entry is added). It lives under
``tools/`` — the sanctioned dev-side tier, deliberately OUTSIDE the
runtime egress scan (``tests/security/test_no_external_egress.py`` scopes
itself to the runtime roots, never ``tools/``) — mirroring
``tools/dispatch_harness/vikunja_http.py``'s placement. It builds on
:mod:`shared.fleet.vikunja_bridge`'s loopback-pinned/fail-soft transport,
so it opens no second network path.

Usage (from the repo root, with ``VIKUNJA_URL``/``VIKUNJA_USER``/
``VIKUNJA_PASS`` set or a gitignored ``.env`` present — the SAME credential
source ``vikunja_bridge`` reads):

    python -m tools.dispatch_harness.coordinator_setup --project-id 7 --view-id 2

Requires the target project's Kanban VIEW id (this script creates the
view's BUCKETS, not the view itself — resolve the Kanban view id first via
the Vikunja web UI, or via ``shared.fleet.vikunja_bridge.list_views`` +
``find_view_by_kind`` in a one-off REPL; a fresh Vikunja project's default
scaffold already ships a Kanban view).
"""

from __future__ import annotations

import argparse
import sys

from shared.fleet import vikunja_bridge as vb

# The Kanban vocabulary is the SINGLE SOURCE OF TRUTH in
# shared.fleet.coord_lifecycle (#844 C2) — imported here (not re-declared) so
# this operator-run migration CREATES exactly the buckets/labels the runtime
# coordinator REASONS about, with zero drift between the two (the stale-label-id
# lesson: one list only). ADR-039 §2.8: Backlog -> Ready -> In Progress -> In
# Review/Verify -> Done; classes of service Expedite / Fixed-date / Standard /
# Intangible. Re-exported (the names stay valid in this module's namespace so
# run_setup / find_orphans reference them unchanged).
from shared.fleet.coord_lifecycle import (
    CLASSES_OF_SERVICE,
    KANBAN_BUCKETS,
    PROVENANCE_LABELS,
)

#: Every label the migration provisions: the class-of-service labels PLUS the
#: #887 provenance labels (``Battery/Test``). Kept as one tuple so ``run_setup``
#: creates and ``find_orphans`` recognizes exactly the same set the runtime
#: reasons over — the stale-label-id lesson, one list only.
SETUP_LABELS: tuple[tuple[str, str], ...] = (*CLASSES_OF_SERVICE, *PROVENANCE_LABELS)


def run_setup(
    project_id: int,
    view_id: int,
    *,
    transport: vb.Transport | None = None,
) -> dict[str, "int | None"]:
    """Discover-or-create every bucket + label the Kanban method needs.

    Returns ``{step_name: id | None}`` for every bucket/label attempted — a
    ``None`` value means that specific step failed (fail-soft: the operator
    running this sees exactly which step needs attention, never a silently
    partial migration). Idempotent — a re-run finds every already-created
    item by name and creates nothing new."""
    results: dict[str, int | None] = {}
    for title in KANBAN_BUCKETS:
        results[f"bucket:{title}"] = vb.ensure_bucket(
            project_id, view_id, title, transport=transport
        )
    for title, hex_color in SETUP_LABELS:
        results[f"label:{title}"] = vb.ensure_label(
            title, hex_color, transport=transport
        )
    return results


def find_orphans(
    project_id: int,
    view_id: int,
    *,
    transport: vb.Transport | None = None,
) -> dict[str, list[str]]:
    """The §2.9 paired tenet's other half: buckets/labels PRESENT in
    Vikunja that no current doctrine (:data:`KANBAN_BUCKETS` /
    :data:`CLASSES_OF_SERVICE`) references — flagged as digest curation
    candidates, NEVER auto-removed (removal is always a separate,
    human-approved action).

    Returns ``{"buckets": [...], "labels": [...]}`` (sorted titles). An
    UNREACHABLE read degrades to an empty list for that half — this is an
    advisory/curation pass, never a blocking one, so a down Vikunja simply
    means "nothing to report this run", not a crash."""
    known_buckets = set(KANBAN_BUCKETS)
    known_labels = {name for name, _ in SETUP_LABELS}

    buckets_read = vb.list_buckets(project_id, view_id, transport=transport)
    labels_read = vb.list_labels(transport=transport)

    orphan_buckets = (
        sorted(
            {
                str(b.get("title", ""))
                for b in buckets_read.items
                if str(b.get("title", "")) not in known_buckets
            }
        )
        if buckets_read.ok
        else []
    )
    orphan_labels = (
        sorted(
            {
                str(l.get("title", ""))
                for l in labels_read.items
                if str(l.get("title", "")) not in known_labels
            }
        )
        if labels_read.ok
        else []
    )
    return {"buckets": orphan_buckets, "labels": orphan_labels}


def _main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "OPERATOR-RUN Coordinator Kanban substrate setup (#843, ADR-039 "
            "§2.12.11) — idempotent discover-or-create. NEVER invoked by the "
            "runtime Coordinator itself."
        )
    )
    parser.add_argument(
        "--project-id", type=int, required=True, help="Vikunja project id."
    )
    parser.add_argument(
        "--view-id",
        type=int,
        required=True,
        help="The project's Kanban view id (resolve via the web UI or "
        "shared.fleet.vikunja_bridge.list_views + find_view_by_kind).",
    )
    args = parser.parse_args(argv)

    print(
        f"Coordinator Kanban setup for project {args.project_id}, "
        f"view {args.view_id}..."
    )
    results = run_setup(args.project_id, args.view_id)
    failed = [name for name, rid in results.items() if rid is None]
    for name, rid in results.items():
        print(f"  {name}: {'FAILED' if rid is None else rid}")
    if failed:
        print(f"\n{len(failed)} step(s) FAILED — see above.", file=sys.stderr)

    orphans = find_orphans(args.project_id, args.view_id)
    if orphans["buckets"] or orphans["labels"]:
        print("\nOrphan curation candidates (NOT removed — review manually):")
        for b in orphans["buckets"]:
            print(f"  bucket not in current doctrine: {b!r}")
        for label_name in orphans["labels"]:
            print(f"  label not in current doctrine: {label_name!r}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
