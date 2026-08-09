# Sprint-18 C3 / #632 disposition — guide-confirmed (relay to the execution agent)

Paste the block below to the Sprint-18 execution agent. It confirms the C3 disposition (built-ahead),
tells you how to close C3 cleanly, and does NOT block the in-flight @hardware runs.

---

**C3 / #632 — disposition CONFIRMED: (a) built-ahead. Independently verified. Here's the clean close-out.**

Your finding is correct, and I verified it independently (read `coverage_audit.md` GAP-8 + a full architecture
sweep — not just your grep). Confirmations:
- **GAP-8's premise was false at the source.** `coverage_audit.md:81` says "a regression in the AO→router
  wiring would be invisible" — it *assumed* the wiring exists. It never did. GAP-8 flagged an "untested path"
  that is actually an **unbuilt** path (a phantom gap).
- **The architecture documents the router as a FUTURE milestone.** `Use Cases_FINAL.md:221` (the
  two-microservice design as the *intended* shape); `IMPLEMENTATION_PLAN.md` P1.10 specifies "query → Semantic
  Router → classifies → dispatches to Orchestrator" as the **integration** milestone, separate from P1.7 (the
  router module, done); the router service entrypoint is still a stub ("actual entrypoint TBD"). It activates
  when the first **skill-dispatch** handler lands (e.g. web-search, ADR-024/#577) — today's 2-use-case path has
  nothing to route. Not a regression, not an orphan.

Your honest test + #632 + the journal fragment are the right handling. Three things to close C3 cleanly — **none
blocks your @hardware runs; keep running C1 → C2 → C3 serially, then C5**:

1. **Re-scope SDV §4 C3 to v2** (the v1 criterion was ill-posed — it asked to test wiring that is a deliberate
   future milestone, which a *test sweep* correctly does not build). Amend the C3 row + add a one-line note,
   substance: *"C3 (v2, re-scoped 2026-06-08): GAP-8's premise was false (verified — the AO does not call the
   router in a live turn; the router is built-ahead for future skill-dispatch/multi-handler routing, not wired
   into today's single-AO path). Achievable + valuable criterion: the real bge-small router loads + classifies
   via real ONNX, a real AO turn runs, the standalone status is documented, and a regression-detector test is
   landed that fails if any future AO→router wiring breaks. The decision to actually wire the router (a
   capability build, P1.10+/UC-005+, gated on the first skill-dispatch handler) is parked in #632."* Since you're
   the single active writer on main, you make this edit (branch-guard as usual).

2. **Score C3 MET against the amended v2 criterion** — `test_real_router_invoked_inside_ao_turn` satisfies it —
   rather than a dangling PARTIAL that implies shortfall. **Be fully transparent** in the SCR + the SWAGR: the v1
   criterion was *corrected-because-ill-posed*, not failed; the false-premise discovery + the regression-detector
   + #632 are themselves C3's deliverables. Conduct the C5 production-posture SWAGR against the **amended** C3.

3. **Keep #632 open** as the forward roadmap decision (disposition (a) built-ahead; the router activates when the
   first skill-dispatch handler lands). The guide added an independent-verification comment to it. Re-title if you
   like; the disposition is settled.

Note: the `router_client` mTLS cert (DATA_MAP §1a) is part of the same scaffolded-ahead infra — provisioned but
unused (no listener consumes it). That's consistent with built-ahead, not a finding; leave it.

The air-gap is untouched (this is a test/architecture clarification, zero runtime change). Proceed with the
@hardware tiers and the close; surface the C5 SWAGR when ready and the guide will verify the close independently.

---
