### 2026-07-12 — The constitutional fence goes in, dormant

*Plain summary: merged #848 (the coordinator self-governance boundary — 7 structural
controls, ADR-039) to main, DORMANT behind `[coordinator]` flags, after the F1 hardlink
hole was found, fixed, and independently re-verified; folded the ADR-039 Amendment 2
doctrine-correction on main.*

The self-governance boundary is the fence that makes "BlarAI cannot modify its own governed
core" structural rather than aspirational. It landed today — but the story is the
author≠verifier loop earning its keep. The first F1 fix (an inode-identity check against a
handful of anchor files) *looked* complete, yet the independent re-verify proved at
execution phase that a hardlink to a **non-anchor** core file — `pyproject.toml`, the
boundary's own `shared/coordinator/config.py`, the PA classifier — still returned ALLOW.
The governed core is the whole tree, not four anchors. Option (a), chosen by the LA, closes
the class fail-closed: deny any *existing* target with `st_nlink > 1`, because a hardlink is
the attack primitive, so any already-multiply-linked file is refused whatever it aliases, at
a negligible over-denial cost (only overwrites of files that are *already* hardlinked). A
fresh fixer implemented it, a third agent re-verified PASS, and only then did it merge.

The merge itself taught a small lesson. Main had advanced — Amendment 1 (the `blarai-coder`
Vikunja account) — since the branch forked, so the branch's ADR-039 was stale and shorter.
Folding the F1 doctrine-correction onto that stale branch copy would have fought the merge;
folding it onto main's *current* ADR-039 as Amendment 2, after a clean code-merge (the branch
never touched ADR-039, so no conflict), was the right order. The boundary is dormant — no
live module imports `shared.coordinator` — so nothing behaves differently yet. What shipped
is the fence, ready for the phases to build behind it.

**Next:** integrate the C1 read-surface (`feat/843`) with this boundary into one coordinator
foundation, then C2 (lifecycle) and C3 (heartbeat, the dead-man liveness outside the cycle)
on top — each dormant, author≠verifier-reviewed, held for the LA.

**Proposed lesson (recurrence check):** when a feature branch lags `main` on a shared
governing doc, fold doc-corrections onto `main`'s current copy *post-merge*, never onto the
stale branch copy — it avoids a self-inflicted conflict on a doc the branch never meant to
touch.

*(commits `c0731036` (merge #848), `3f2622c4` (F1 fix); ADR-039 Amendment 2 + DECISION_REGISTER
folded on main; blast-radius gate 189 passed; author≠verifier re-verify PASS. Boundary DORMANT.)*
