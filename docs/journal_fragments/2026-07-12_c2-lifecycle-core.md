### 2026-07-12 — Building the ruler before the hand that moves the pieces

*Plain summary: shipped C2 increment-1 (#844) — the deterministic lifecycle
DECISION core (`shared/fleet/coord_lifecycle.py`): class-of-service
classification, event→board-transition mapping, the Definition-of-Ready gate, and
per-class aging-outlier stall detection. All pure, dormant, no side effects. The
side-effecting limbs (live board writes, stall comments, redispatch-proposal
staging, ACP monitoring, driver-integrated checks) are a deliberately-deferred
increment-2. No lesson earned; a scoping trade-off recorded.*

C2 (#844) as written is a large surface — it spans deterministic decisions AND
the side effects those decisions drive, and some of those side effects live on
the battery-sensitive `swap_driver` path or need infrastructure that is really
C3's (a born-encrypted proposal-staging store). Shipping it as one commit would
have meant either a rushed, under-tested sprawl or touching the swap path the
23:00 battery runs on. So I split it where the seam is natural: the **decision
core** — the pure ruler every live limb and C3's heartbeat will consult — lands
first, and the **actors** that consult it land as increment-2.

That seam is real, not cosmetic. The decision core is `gate as JUDGE, model as
SIGNAL` all the way down: `resolve_board_transition` returns a Done move ONLY
when `oracle_passed AND merged` are both true, so a forged or premature "done"
is structurally impossible rather than merely discouraged; `evaluate_dor`
re-derives a dispatch target from the trusted structured repo-id via #848's
`derive_workspace_target` and validates it through #848's `check_target`, so the
self-governance boundary is enforced by the same regression-locked code the SG
phase already locks, never re-implemented; and `detect_stalls` judges each item
against its OWN class-of-service baseline, so a legitimately long-lived Standard
item can't make a stuck Expedite one invisible. The one thing I had to get
honest about was the statistic: a 1.5σ outlier test needs three clustered
baseline items before a single straggler crosses `mean + 1.5·stddev` — with only
two, the straggler inflates the stddev enough to hide itself. My first stall
fixtures assumed detection the math doesn't produce; the failing tests were the
fixtures, not the module, and fixing them to three-baseline-plus-one is the
honest shape of the real board.

The trade-off named: increment-1 is genuinely complete and shippable but it is
NOT all of C2, so #844 does NOT close — it gets a dated CURRENT STATE comment
listing built-vs-remaining, rather than a false "done". The alternative
(one big C2 commit) I rejected because it would have either lowered the quality
bar or dirtied the battery path mid-evening; the cost of the split is that C2
lands in two motions instead of one, which the ticket's CURRENT STATE makes
legible.

**Next:** C2 increment-2 — wire the live limbs (board writes, deduped stall
comments + operator surface, PARKED→redispatch proposal staging with the SG
target re-derivation, ACP-stream monitoring), the swap_driver-touching parts
sequenced AFTER the battery window; then C3 (#845 heartbeat) on the C2
foundation — each dormant, author≠verifier'd, held for the LA's LIVE-flip
ceremony.

*(commit `<this>` — C2 increment-1; new `shared/fleet/coord_lifecycle.py` +
`shared/tests/test_coord_lifecycle.py` (34 tests) + a SSOT vocabulary refactor
of `coordinator_setup.py`; independent author≠verifier review MERGE-READY, no
concerns; focused 43/43; standing gate 7715 passed / 3 skipped / 0 failed,
LOCALAPPDATA-redirected. DORMANT behind `[coordinator]`.)*
