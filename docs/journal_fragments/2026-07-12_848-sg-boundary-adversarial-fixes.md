### 2026-07-12 — The four ways the door was still ajar

*Plain summary: fixed four adversarial-review-found fail-toward-ALLOW bypasses in the DORMANT #848 self-governance boundary (ADR-039) — F1 hardlink inode identity in `governed_core.py`, F3 roots-required config check, F4 label-shape detection in `provenance.py`, F5 single-read policy load in `policy.py` (+ an additive bytes param on `manifest_signer.verify_manifest_signature`). No live behavior changed; `shared/fleet/dispatch.py` byte-unchanged.*

The #848 boundary is the structural severance that gives BlarAI zero write path to
its own governed core. It shipped dormant, seven controls, a crown-jewel adversarial
suite. Then a reviewer drove live repro probes at it and found four places where the
boundary, when confused, failed toward ALLOW — which is the one direction a
severance is never allowed to fail. Author≠verifier held: I applied the fixes; I did
not write or review the original build. Each fix ships with a regression test that
reproduces the reviewer's exact bypass and asserts it now denies, and I re-ran the
reviewer's `probe.py` against the patched code to confirm.

The most instructive was **F1**. Control 1 decides governed-core membership by
*identity, not name* — it resolves symlinks and Windows junctions to their real
target before the containment test, so a link that points into the core is caught by
where it *actually* lands. But `Path.resolve()` cannot see through a **hardlink**: a
hardlink is a second directory entry for the *same inode*, and its own path is
genuinely under the workspace. Realpath containment passed it, ALLOW — and the
reviewer's probe then wrote through that "workspace" path and overwrote the real
`dispatch.py`. The canonicalization was doing exactly what it promises and still let
the crown jewel be overwritten, because a hardlink is an identity the path layer
cannot observe. The fix keys on the identity the filesystem *does* expose: a target
that shares the device+inode of any known governed-core anchor file (the sentinel +
the `CLAUDE.md`/`DECISION_REGISTER.md`/`dispatch.py` triad, under every root) is
governed core regardless of its path. I went with a bounded anchor-set inode compare
over walking every file under the roots for an inode match — the anchor set is
deterministic and cheap, where a full walk is expensive and itself TOCTOU-prone —
accepting that a hardlink to a *non-anchor* core file still needs the per-write
"during ring" (F2, below) to catch it. Fail-closed throughout: a not-yet-existing
target has no inode to alias (allowed, the normal new-file case), but an *existing*
target that cannot be stat-ed propagates to the deny handler.

**F3** was a fail-open in the config-immutability check: given a path but no roots,
it could not verify governed-core containment, and it fell through to ALLOW — so
`pyproject.toml`, `.mcp.json`, a manifest all slipped past the two-name basename
list. A boundary that cannot verify must refuse; a path-bearing check with
`roots=None` now denies. **F4** was structural-provenance detection that only
understood one label shape: a `labels` delivered as a mapping, a title under `name`
instead of `title`, or a case-variant of the marker each produced
`is_self_advisory=False` and a dispatchable verdict. The fix reads mapping-shaped
labels, both keys, matches case-insensitively, and — the load-bearing part — treats
a *well-formed-but-opaque* label shape as self-advisory (fail-closed: an unreadable
label lane over-routes to humans, never under-routes a self-item to the fleet). The
one thing I was careful not to do was over-refuse: absent/empty/benign labels stay a
normal workspace lane, and a test pins that.

**F5** was a double-read TOCTOU: the policy loader signature-verified the file, then
read it *again* for content — a swap between the two reads loads a malicious policy
under a signature that was valid over a benign one. The fix reads the bytes once and
both verifies and parses *those* bytes. To do it without divergence I added an
optional `manifest_bytes` param to the shared `verify_manifest_signature` rather than
forking a second verifier — the live weight-manifest boot path (default `None`) stays
byte-identical and the existing monkeypatch surface still intercepts, while the policy
loader passes the bytes it already read. Same commit also *consumed* the policy's
`protected_config_sections` field, which was validated and then ignored: a resolver
now folds it into the effective protected set exactly as `extra_roots` already works
— additive over the compiled-in core, never subtractable from inside.

The honest edge of this: **F2 is not fixed and is not mine to fix here.** Probe 2
shows a coder editing under an ALLOWED workspace root can traverse a symlink into the
core *during* execution — the per-file `check_target` primitive denies that reachable
path, but #848's staging check only gates the dispatch *root*. Closing it is the ADR-
named ACP `session/request_permission` responder that re-resolves every tool-call
target at write time. That is the outstanding blocker before any C1 go-live, and it
is a larger build, not a patch.

**Next:** fold this fragment; build the F2 during-ring (per-write path re-resolution
via the ACP permission responder) as the C1-go-live gate; leave the boundary dormant
until then. (The probe also surfaced that several security-relevant config *sections*
— `trust`, `biometric`, `audit`, `vsock`, `ipc`, `models` — are not in the
compiled-in protected-section list; whether to add them is an LA posture decision, and
the new F5 resolver already lets a signed policy add them without a code change.)

**Proposed lesson:** an identity-based severance that canonicalizes *paths*
(realpath/junction/worktree) is incomplete until it also checks *inode* identity —
`resolve()` cannot see through a hardlink, so a path-only identity check fails open on
the exact overwrite vector it exists to stop. Pairs with the standing fail-closed
discipline (a boundary check that cannot verify must DENY). The mechanical half (`Path.resolve()`
does not dereference hardlinks; `os.stat().st_ino`/`st_dev` are Windows-correct on NTFS)
is a `FIELD_NOTES.md` candidate for the governed-core surface.

*(Fixes on `feat/848-sg-boundary` atop `f78d3327`: `governed_core.py` (F1 inode layer + F3 roots-required), `provenance.py` (F4 label shapes), `policy.py` + `manifest_signer.py` (F5 single-read + sections resolver). 90 prior coordinator tests + 24 new regression locks green; 18 manifest_signer/weight_integrity live-path tests unchanged-green; reviewer `probe.py` re-run confirms F1/F3/F4 deny. DORMANT — dispatch.py byte-unchanged.)*
