### 2026-07-13 — One comment per episode, and the first plaintext line in coordinator state

*Plain summary: shipped the C2-inc-2 deduped-stall-comments + operator-surface limb —
`coord_stall_state.py` (the cross-cycle seen-set) + `coord_stall_monitor.py` (the
dedup+post cycle) + a STALLS rollup on `/coord status`. DORMANT. Records the
LA-affirmed storage precedent: non-content-bearing coordinator runtime metadata is
plaintext (owner-DACL, swap_state idiom); content-bearing coordinator state is
born-encrypted per ADR-039 §2.13 item 2. No new lesson; a precedent and a small
elegance worth keeping.*

The stall-comments limb is the one where the pure math was already done and the only
real question was *where the memory lives*. `coord_lifecycle` had shipped
`detect_stalls`, `stall_fingerprint`, and `new_stall_signals` in increment-1, and its
docstring said the quiet part out loud — "State lives in the caller." This limb is
that caller. It had to decide, for the first time in the Coordinator program, where a
piece of coordinator *runtime* state (as opposed to *proposal* state) is kept — and
that decision is the load-bearing thing this entry exists to record, because it sets a
precedent a later session should not have to re-litigate.

The fork the predecessor handed me was: born-encrypt the seen-set like the proposal
store, or keep it plaintext like `swap_state`. I recommended plaintext, the LA
affirmed it, and the reasoning is the part worth writing down. ADR-039 §2.13 item 2
scopes born-encryption to *content-bearing* stores — it names three (the proposal
store, the briefing ledger, the shadow journal — "goals, ticket text"). A stall
fingerprint is none of those: it is a deterministic `"{service_class}:{task_id}"`
string, a public class-of-service enum value plus a Vikunja task id already visible on
the loopback board. Encrypting it would be machinery the data doesn't warrant, and —
the sharper argument — it would couple stall *detection* to keystore availability. A
missing DEK must never be the reason the coordinator stops noticing a stall. So the
line I drew, and the LA affirmed, is exactly the ADR's own content-bearing test:
**non-content-bearing coordinator runtime metadata → plaintext, owner-DACL JSON;
content-bearing coordinator state → born-encrypted (§2.13 item 2).** That is an
*application* of existing doctrine, not a new trust posture, which is why it earns a
journal entry and a module docstring but deliberately **no DECISION_REGISTER row** —
the register indexes decisions, and this is a faithful instance of one already
recorded, not a new one. The store mirrors `swap_state.py` branch for branch: atomic
`temp + os.replace`, fail-soft read, and it adds `ensure_owner_only_dacl` as
defense-in-depth (itself fail-safe — a non-Windows host or an ACL error is a logged
no-op, never a raise, so persistence never fails *on hardening*).

The second thing worth keeping is a small elegance in the dedup algebra, because it
made the hardest requirement fall out for free. The LA sharpened the dedup contract at
the gate: prune a fingerprint when the stall **clears** (leaves `detect_stalls`
output), not only when the task closes — one comment per stall *episode*, so a task
that re-stalls after being resolved earns a fresh comment instead of being silently
suppressed forever. The tempting implementation is an explicit prune pass. The correct
one is to notice that the set you persist each cycle is simply *the still-stalled ∩
already-seen, plus the newly-posted* — which is to say, the currently-stalled set,
with cleared fingerprints falling out by construction. `persisted = (already_seen &
current) | {posted}`. A cleared stall isn't pruned; it just isn't in `current`, so it
never makes the next set. Episode semantics for free. The one place I resisted the
obvious was the failed post: a NEW stall whose comment *post* failed is deliberately
**not** added to the set, so the next cycle retries it. A Vikunja outage should delay
a comment, never lose the only notice — the same fail-soft instinct the whole bridge
runs on, applied to the one place where "already seen" could otherwise swallow a
comment that never landed.

I also tightened the reasoning I'd originally reached for. I had called the seen-set
"recomputable from a board read"; that's wrong, and the LA caught it. It is
*post-history* — which stalls have already been commented — and Vikunja carries no
such history. The honest framing is that the seen-set is transient dedup working-state
whose loss is fail-soft *by cost, not by reconstruction*: an empty set means at most
one duplicate comment per currently-stalled item on the next cycle, after which it
re-converges. That bounded, self-healing cost is the whole reason plaintext-with-
atomic-write is sufficient and a heavier store would be over-engineering.

The operator surface is the smaller half: a cross-project STALLS rollup on
`/coord status`, ordered most-urgent-class-first, each stall marked `flagged` (already
commented on its ticket) or `NEW`, deduped against the *same* seen-set the posting
cycle maintains — read-only in the status path, so the read surface never writes. It
inherits the C1 injection-safety discipline: ticket titles pass through
`neutralize_untrusted_text`, and the posted comment itself is deliberately title-free
(the comment lands *on* the ticket, so the ticket identifies itself — interpolating an
untrusted title would be an injection surface for zero benefit). Everything stays
dormant: nothing in a production boot runs the cycle, and `/coord status` is behind
`[coordinator].enabled=false`. An independent `Explore` reviewer (author≠verifier — it
did not write this) walked the seen-set algebra through a three-cycle scenario, grepped
the tree for live callers, confirmed the plaintext posture against §2.13, and returned
MERGE-READY with no blocking findings; its one flagged item was the pre-existing
`s`-reuse type quirk in the swap-in-flight render block, which I'd already confirmed
predates this limb on `main` and deliberately left untouched (mixing an unrelated
housekeeping fix into feature work is its own anti-pattern).

**Next:** the remaining battery-safe C2 limbs — ACP `session/update` stall monitoring,
then PARKED-HONEST → the staged redispatch proposal (which stages into the merged
`proposal_store`) — then the swap-path limb built dormant. Each flows the same way:
build → independent author≠verifier review → LOCALAPPDATA gate → merge dormant. The
activation wiring for this limb (threading a real `stall_seen_path` from
`[coordinator]` config through the launcher into `CoordCoordinator`, and giving the
future heartbeat/dispatch-event hook a live `run_stall_cycle` caller) is deliberately
deferred to go-live — the one line that is not mine to cross without the LA.

*(commit `9b06ea29` — the C2 stall-comments limb; new `shared/fleet/coord_stall_state.py`
+ `shared/fleet/coord_stall_monitor.py`, `post_task_comment` in `vikunja_bridge.py`,
per-project `stalls` + `stall_seen_fingerprints` in `work_state.py`, the STALLS rollup
in `coord_render.py`, the optional `stall_seen_path` seam in `coord_coordinator.py`;
+35 tests across 5 files; independent author≠verifier review MERGE-READY, no blocking
findings; standing gate 7779 passed / 0 failed, elevated + LOCALAPPDATA-redirected
(7 environmental port-5001 skips, app up). DORMANT — no live caller.)*
