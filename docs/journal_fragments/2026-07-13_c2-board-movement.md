### 2026-07-13 — The write-side sibling, and a lock that reaches all the way to the board

*Plain summary: shipped the C2-inc-2 live-board-movement limb — `move_job_card`
in `shared/fleet/vikunja_bridge.py`, the write-side sibling of the C1 read
surface. A card moves to the bucket the deterministic ruler chose, name-resolved
(view by kind, bucket by title), fail-soft, DORMANT (no live caller). The
forged-Done lock composes end-to-end. Clean extension; no failure, no new lesson.*

The board-movement limb is small on purpose, and its whole value is that it makes
no decision. `resolve_board_transition` (merged in C2 increment-1) already decides
where a card goes and already carries the forged-Done lock — a Done move requires
`oracle_passed AND merged`, so a premature or forged "done" produces no transition
at all. This limb only *executes* an already-decided move. That separation is why
the interesting test isn't "does the move work" but "does the lock survive the
trip to the board write": a composition test drives `resolve_board_transition(
oracle_passed=False, merged=True)`, asserts it returns None, and confirms a caller
holding None never calls the mover — then drives the genuine oracle+merged case
through to a real bucket change. The lock is upstream, in the pure ruler; the write
layer inherits it by construction and cannot be asked to violate it.

The one thing I refused to guess was the endpoint. Vikunja's kanban bucket-move is
not the obvious `POST /tasks/{id}` with a `bucket_id` field — it is a dedicated
`POST /projects/{project}/views/{view}/buckets/{bucket}/tasks` with a
`models.TaskBucket` body. Rather than infer that from docs of an unknown version, I
pulled the LIVE server's OpenAPI spec (`/api/v1/docs.json`, 396 KB, the exact
v2.3.0 this install runs) and read the path, the summary ("Update a task bucket"),
and the body schema (`task_id`, `bucket_id`, `project_view_id`) straight off it.
The endpoint in the code is the endpoint the server actually serves, not a
plausible guess — the same discipline the C1 read surface used to pin the buckets
endpoint. Everything else is deliberately the read surface's idiom turned around:
the kanban view resolved BY KIND and the destination bucket BY TITLE (never a
hardcoded id — a re-migrated board needs no code change), the ticket found by its
`[fleet-job <run_id>]` marker, and the whole thing FAIL-SOFT — every non-move
(no kanban view, unknown bucket, no ticket, a Vikunja outage) returns a
`BoardMoveResult(moved=False, reason=...)` and nothing raises, because a ticket
board outage must never touch a dispatch or battery run.

Dormancy is structural, matching the C1 read surface exactly: the leaf is ungated,
the `[coordinator].enabled` decision belongs to the future dispatch-event hook that
will call it, and there is no such caller today — a grep for `move_job_card`
returns only the new code and its tests. An independent `Explore` verifier (it did
not write this) confirmed all of that against source — endpoint, name-resolution,
fail-soft completeness, the forged-Done composition, zero production callers, no
route-shadowing in the test fake — and returned MERGE-READY with no nits. The
standing gate is green (0 failed); the run's +7 skips are the documented
port-5001-in-use environmental pattern (a live app came up mid-run), and my two
test files are 88 passed / 0 skipped on their own.

**Next:** the remaining battery-safe C2 limbs — deduped stall comments + operator
surface (the fingerprint math is already in `coord_lifecycle`; this adds the
cross-cycle seen-set state), ACP `session/update` stall monitoring, and the
PARKED-HONEST → redispatch proposal (which stages into the now-merged proposal
store) — then the swap-path limb LAST, outside a battery window and after a
#740/M2 disk check. Each dormant, author≠verifier'd, gate-green.

*(commit `366d43a7` — the C2 board-movement limb; `move_task_to_bucket` +
`find_bucket_by_title` + `BoardMoveResult` + `move_job_card` in
`shared/fleet/vikunja_bridge.py`, +8 tests in `shared/tests/test_vikunja_bridge.py`
(64/64 file-green, 88/0 with the proposal store); endpoint verified against the
live v2.3.0 OpenAPI spec; independent author≠verifier review MERGE-READY, no nits;
standing gate 0 failed (+7 environmental port-5001 skips). DORMANT — no live
caller.)*
