# Disposition — #1152 IPC frame cap + fail-loud, independent pre-merge review (2026-07-28)

Review: independent author≠verifier subagent, verdict **NEEDS FIXES** (1 HIGH / 4 MEDIUM /
4 LOW) against the uncommitted working tree of `fix/1152b-frame-cap-and-fail-loud`. The
reviewer corroborated the root cause from PRIMARY evidence rather than the branch prose —
reading `launcher.log:61421,61433` directly, confirming the raising site is
`MessageFramer.encode` (`shared/ipc/protocol.py:557`) and not the transport's non-raising
`logger.error`, and independently reproducing the 7-vs-8-task story from the decompose log
lines against `DEFAULT_MAX_TASKS = 8`. It also ran the full gate (9307/7/0-failed) and
mutation-tested the new AST lock by stripping a `VsockConfig` kwarg and confirming the
failure named the right line.

This is the SECOND review of this defect; the first fix (`ee09901a`) shipped confidently
against the wrong root cause, which is why every load-bearing claim here was re-verified
against primary evidence rather than accepted.

```disposition
F1 launcher re-parses default.toml instead of using the AO's resolved value; fail-soft lands on the silent side and re-creates the one-sided cap | FIXED | ea1eb8d0 - AO gains resolved_max_message_bytes; launcher _gateway_frame_cap threads it and FAILS CLOSED; the second parse is deleted and a lock forbids its return
F2 the fail-loud guard covers 1 of 3 encode sites; the unbounded exc interpolation and the peer-supplied request_id could themselves exceed the cap | FIXED | ea1eb8d0 - str(exc)[:2000] on the planning-failed path, request_id[:64] on the refusal
F3 ADR + default.toml justify the raise as already-bounded but max_tasks/max_criteria are CARDINALITY caps; goal/requirements have no length limit | FIXED | ea1eb8d0 - both surfaces rewritten to state the honest limit, naming the fail-loud refusal as the control and intake length-bounding as the stronger unfixed option
F4 every date one day in the future (UTC-derived session context vs local PDT clock; log lines and sibling fragments are 2026-07-28) | FIXED | ea1eb8d0 - branch artifacts corrected to 2026-07-28; both journal fragments renamed + reheadered before fold-in; already-merged ee09901a is history and is NOT rewritten
F5 protocol.py docstring forbids restating the cap and restates it in the same sentence; also wrong per-deployment (guest is still 65536) | FIXED | ea1eb8d0 - parenthetical dropped, per-deployment nature stated
F6 ADR-031 section 6 carries stale present-tense claims with no superseded pointer | FIXED | ea1eb8d0 - both sites scoped with forward pointers to Amendment 1
F7 the AST reachability lock is evadable via attribute/alias call forms and scans one file | FIXED | ea1eb8d0 - resolves ImportFrom aliases, matches ast.Attribute, walks all of services/ui_gateway/src/; the alias evasion was injected, confirmed to fail the lock, then restored byte-identical
F8 the framer-rebind lock is a substring match; would pass if the rebind moved after listener.start() | FIXED | ea1eb8d0 - AST-locates both the rebind and the VsockListener call and asserts rebind precedes listener
F9 the baseline headline says 0-skipped but the measured run had 7 live-app skips; a clean-environment (app down) run is still owed | DEFERRED | #1153 blocked-by: #1153 - the LA was actively using BlarAI for dispatch validation and stopping it to re-measure would cost the run this fix exists to enable; the note under the LIVE_GATE_BASELINE in docs/TEST_GOVERNANCE.md records the app-running condition and names #1153, so the surface is not lying - what is owed is the confirming measurement
F10a the branch has zero commits; all artifacts are uncommitted working-tree changes on a shared tree | FIXED | ea1eb8d0 on fix/1152b-frame-cap-and-fail-loud
F10b Vikunja #1152 DESCRIPTION is empty; authority_first says the description owns what the work IS, and the LA's ADR-overriding approval belongs there | FIXED | ea1eb8d0 - #1152 description rewritten with the corrected root cause, the honest limit, and the LA's ADR-overriding approval recorded
```

## Observations carried, not dispositioned (no defect asserted)

**Chunked framing was not named as a rejected alternative.** The reviewer noted the repo
already contains `shared/ipc/parse_channel.py` and `shared/ipc/resolve_channel.py` — proven
chunked framing over this same transport — which would have needed no cap raise and no
both-ends agreement at all. This is a fair criticism of the ADR's completeness rather than a
defect in the code, and it is now named in ADR-031 Amendment 1 as the rejected alternative,
with the trade recorded and an explicit trigger: **if the fail-loud refusal ever fires in
production, chunking is the fix, not a second raise.**

**The resolver idiom was correct.** `_resolve_max_message_bytes` mirrored the launcher's two
existing optional-knob resolvers exactly; the reviewer's F1 objection was to the fail-soft
*posture* for a value that must agree across two processes, not to the shape. The replacement
keeps the idiom for genuinely optional knobs and departs from it only here, where a silent
fallback is indistinguishable from the bug.

**What the reviewer verified as already correct** (recorded so a later session need not
re-derive it): both-ends agreement holds on the AO path — all five `VsockConfig` sites are the
only ones in the gateway, `self._port` is the AO port 5001 and not the PA's 5000, and
receive-side enforcement reads the config cap; the framer rebind at service start precedes the
listener and is never overwritten; 262144 is inside the validator's 1024..1_048_576 band so the
AO will boot; and the security scope holds — the PA config, both `guest_runtime.toml` files,
the guest bridges, and `parse_channel`/`resolve_channel` are all untouched at 64 KB.
