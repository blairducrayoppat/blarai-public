"""Section A — the Tier-1 acceptance-demo driver abstraction + gate registry (#840 scaffold).

The "Proof" section of the live-proof dashboard shows, for each gate in the ADR-037
grading & integration machinery, a *worked demo*: a concrete input fed to the machinery,
the machinery's response, a CAUGHT / PASS verdict, and a REAL evidence excerpt taken from
an actual gate run. This module is the SCAFFOLD for that — the driver abstraction plus a
registry that stubs every gate demo.

HONESTY IS THE DELIVERABLE'S OWN SUBJECT (ADR-037 §1). Two rules this module enforces so a
scaffold can never masquerade as proof:

* **No fabricated evidence.** Every driver here is a :class:`StubDemoDriver`: it returns a
  clearly-labeled ``status="STUB"`` result with an EMPTY evidence excerpt and
  ``wired=False``. A real driver (filled in later, per its ticket) subclasses
  :class:`DemoDriver`, implements :meth:`run` against an actual gate run, and returns
  ``wired=True`` with a real, quoted excerpt. The dashboard renders the two differently and
  never shows a stub as a pass.
* **The gate's build-status is reported truthfully and SEPARATELY from the demo's status.**
  A gate can be LIVE in the codebase (e.g. #832's ``green_integrity_audit``) while its
  *demo driver* is still a STUB — that is the common case at scaffold time. ``build_status``
  (LIVE / STAGED / PLANNED, straight from ADR-037's ladder) never implies the demo is wired.

This module is deterministic and does no I/O and no network. The registry is data; the
drivers are pure.
"""

from __future__ import annotations

from dataclasses import dataclass

# Demo status vocabulary (the demo driver's own state — NOT the gate's build status).
DEMO_STUB = "STUB"        # not wired — no evidence produced (the scaffold default)
DEMO_CAUGHT = "CAUGHT"    # wired: the gate correctly caught the injected defect
DEMO_PASS = "PASS"        # wired: the gate correctly passed valid work
DEMO_NOT_RUN = "NOT-RUN"  # wired but could not run this cycle (honest not-run)
DEMO_STATUSES = frozenset({DEMO_STUB, DEMO_CAUGHT, DEMO_PASS, DEMO_NOT_RUN})

# Gate build-status vocabulary (ADR-037 §"PLANNED-vs-BUILT honesty" — the truth about the
# gate's presence in the codebase, independent of whether its demo is wired).
BUILD_LIVE = "LIVE"
BUILD_STAGED = "STAGED"
BUILD_PLANNED = "PLANNED"


@dataclass(frozen=True)
class GateSpec:
    """Immutable metadata for one gate demo — the honest description the dashboard renders
    regardless of whether the demo driver is wired yet. Values are lifted verbatim in
    substance from ADR-037 §2 (the gate ladder) and §"PLANNED-vs-BUILT honesty"."""

    key: str            # registry key, e.g. "oracle_qa"
    gate_id: str        # ADR-037 ladder id, e.g. "G8/G9"
    ticket: str         # Vikunja ticket, e.g. "#821"
    title: str
    proves: str         # what a PASS asserts (ADR-037 "Proves" column)
    cannot_prove: str   # the honest limit (ADR-037 "Cannot prove" column)
    build_status: str   # LIVE / STAGED / PLANNED (the codebase truth)
    advisory: bool      # True = advisory-only (never changes a verdict; ADR-037 §1 inv.5/#837)
    demo_scenario: str  # the input the (future) real demo feeds the machinery
    expected_response: str  # what the machinery should do with it
    expected_verdict: str   # the demo's target outcome once wired (CAUGHT / PASS)
    evidence_pointer: str   # where the REAL evidence will be read from once wired


@dataclass
class DemoResult:
    """The render-ready outcome of one gate demo. A stub carries an empty ``evidence_excerpt``
    and ``wired=False``; the dashboard MUST render it as a scaffold placeholder, never a pass."""

    spec: GateSpec
    status: str                     # one of DEMO_STATUSES
    wired: bool                     # False for every stub
    machinery_response: str         # what the machinery did (placeholder text for a stub)
    evidence_excerpt: str = ""      # a REAL quoted excerpt when wired; "" for a stub
    evidence_source: str = ""       # the file:line / run-id the excerpt was quoted from
    honesty_note: str = ""          # the always-present label of what is/ isn't proven here

    def to_dict(self) -> dict:
        s = self.spec
        return {
            "key": s.key,
            "gate_id": s.gate_id,
            "ticket": s.ticket,
            "title": s.title,
            "proves": s.proves,
            "cannot_prove": s.cannot_prove,
            "build_status": s.build_status,
            "advisory": s.advisory,
            "demo_scenario": s.demo_scenario,
            "expected_response": s.expected_response,
            "expected_verdict": s.expected_verdict,
            "evidence_pointer": s.evidence_pointer,
            "status": self.status,
            "wired": self.wired,
            "machinery_response": self.machinery_response,
            "evidence_excerpt": self.evidence_excerpt,
            "evidence_source": self.evidence_source,
            "honesty_note": self.honesty_note,
        }


class DemoDriver:
    """A gate demo driver. The real drivers (filled in later, one per ticket) subclass this
    and implement :meth:`run` against an ACTUAL gate run, returning a :class:`DemoResult`
    with ``wired=True`` and a real, quoted evidence excerpt.

    ``evidence`` (optional) is the parsed data-JSON slice the generator hands each driver —
    the seam a real driver reads its live gate-run artifacts from. A stub ignores it."""

    def __init__(self, spec: GateSpec) -> None:
        self.spec = spec

    def run(self, evidence: dict | None = None) -> DemoResult:  # pragma: no cover - abstract
        raise NotImplementedError(
            f"demo driver for {self.spec.key} ({self.spec.ticket}) is not implemented yet"
        )


class StubDemoDriver(DemoDriver):
    """The scaffold driver: returns a clearly-labeled placeholder that produces NO evidence.

    This is the deliberate honesty floor — until a real driver replaces it, the dashboard
    shows the gate, its build-status, and the demo it WILL run, but marks the demo unwired
    and shows no evidence. It never fabricates a CAUGHT/PASS."""

    def run(self, evidence: dict | None = None) -> DemoResult:
        s = self.spec
        advisory = " (advisory-only — never changes a verdict)" if s.advisory else ""
        return DemoResult(
            spec=s,
            status=DEMO_STUB,
            wired=False,
            machinery_response=(
                "demo not yet wired — the real driver runs this scenario against an actual "
                f"{s.ticket} gate run and quotes the machinery's response here"
            ),
            evidence_excerpt="",
            evidence_source="",
            honesty_note=(
                f"STUB: no evidence produced or fabricated. Gate build-status is "
                f"{s.build_status}; the demo driver is pending {s.ticket}.{advisory}"
            ),
        )


# ---------------------------------------------------------------------------
# The registry — the 10 Tier-1 acceptance demos (#840 c.1782). Ordered bottom-to-top of
# the ADR-037 ladder so the dashboard reads like the machinery runs.
# ---------------------------------------------------------------------------

GATE_SPECS: tuple[GateSpec, ...] = (
    GateSpec(
        key="static_pregate",
        gate_id="G2",
        ticket="#831",
        title="Static pre-gate",
        proves="No undefined names or syntax errors reach the expensive grading spend "
               "(ruff --select F / node --check), fail-fast.",
        cannot_prove="Anything behavioral — a file that imports clean can still be wrong.",
        build_status=BUILD_PLANNED,
        advisory=False,
        demo_scenario="A merged task with an undefined name (F821) in a public module.",
        expected_response="ruff --select F flags F821 before any oracle runs; the task enters "
                          "a bounded fix-cycle.",
        expected_verdict=DEMO_CAUGHT,
        evidence_pointer="<run>/static-pregate.log (planned #831)",
    ),
    GateSpec(
        key="clean_env_grading",
        gate_id="G4",
        ticket="#822",
        title="Import-contract / clean-env grading",
        proves="The oracle's imports resolve to the promised modules/callables at the "
               "promised paths (getattr each export, assert __file__ under the plan path).",
        cannot_prove="That a resolvable symbol behaves correctly.",
        build_status=BUILD_PLANNED,
        advisory=False,
        demo_scenario="A merged task that exports the contract symbol from the wrong path "
                      "(the B6/B7 integration seam).",
        expected_response="The symbol-level probe reports the unresolved contract entry; the "
                          "job parks INTEGRATION-SEAM instead of a misleading pass.",
        expected_verdict=DEMO_CAUGHT,
        evidence_pointer="<run>/import-probe-verdict.json (planned #822)",
    ),
    GateSpec(
        key="console_channel",
        gate_id="G5",
        ticket="#823",
        title="Behavior smoke / runtime-error (console) channel",
        proves="The assembled web app does the thing and throws no runtime error; flags "
               "literal undefined/NaN in rendered text (protocol-layer CDP capture).",
        cannot_prove="Look-and-feel quality — the operator's eyeball owns that.",
        build_status=BUILD_PLANNED,
        advisory=False,
        demo_scenario="A page that renders but emits a console pageerror (sum=undefined).",
        expected_response="The CDP console/pageerror read surfaces the runtime error the "
                          "pixel-only critic is blind to; the design loop addresses it.",
        expected_verdict=DEMO_CAUGHT,
        evidence_pointer="<run>/design-console.json (partial browser-runtime channel landed; "
                         "demo pending #823)",
    ),
    GateSpec(
        key="exec_smoke",
        gate_id="G6",
        ticket="#830",
        title="Wave-final executability floor",
        proves="The integrated app STARTS — import the declared entrypoint + --help/no-op "
               "(gives Node/.NET a behavioral floor they lack).",
        cannot_prove="That it computes correctly.",
        build_status=BUILD_PLANNED,
        advisory=False,
        demo_scenario="An app whose modules import clean but whose entrypoint raises on boot.",
        expected_response="The executability floor imports the declared entrypoint, catches "
                          "the boot crash, and records executability: failed (not a silent pass).",
        expected_verdict=DEMO_CAUGHT,
        evidence_pointer="<run>/exec-smoke.json (web seam landed; language-agnostic demo pending #830)",
    ),
    GateSpec(
        key="oracle_qa",
        gate_id="G8/G9",
        ticket="#821",
        title="Oracle QA (well-posedness + discrimination)",
        proves="The job oracle is WELL-POSED (collectable, spec-valid strategies, no "
               "interactive-IO, imports ⊆ contract, non-vacuity floor) AND DISCRIMINATES "
               "(fails on the empty skeleton; every objective criterion traces to an assertion).",
        cannot_prove="Absolute completeness — mutation (G9/#828) is bounded/sampled.",
        build_status=BUILD_PLANNED,
        advisory=False,
        demo_scenario="A generated oracle with an ill-posed Hypothesis strategy (a spec-invalid "
                      "kwarg) that would reject valid work.",
        expected_response="Oracle-QA reports strategy_illposed at plan time and regenerates the "
                          "oracle (bounded) BEFORE it is seeded — never mid-run repair toward passing.",
        expected_verdict=DEMO_CAUGHT,
        evidence_pointer="<run>/oracle-qa.json (planned #821)",
    ),
    GateSpec(
        key="mutation",
        gate_id="G9",
        ticket="#828",
        title="Bounded deterministic-operator mutation (adequacy)",
        proves="The oracle actually REJECTS invalid work — a bounded, offline, "
               "deterministic-operator mutation the oracle should kill (the discrimination lever).",
        cannot_prove="Absolute adequacy — mutation is bounded and sampled, not exhaustive.",
        build_status=BUILD_PLANNED,
        advisory=False,
        demo_scenario="Inject a deterministic mutant (flip a comparison) into a GREEN's tree.",
        expected_response="The oracle FAILS on the mutant (mutant killed); a surviving mutant is "
                          "disclosed as covered-weak, never silently a full-coverage GREEN.",
        expected_verdict=DEMO_CAUGHT,
        evidence_pointer="<run>/mutation.json (planned #828)",
    ),
    GateSpec(
        key="flake_differential",
        gate_id="G10",
        ticket="#829",
        title="Flake differential",
        proves="A verdict FLIP on one hermetic clean-env re-run means the GRADER is flaky, "
               "not the coder wrong (routes as oracle/harness defect, not a coder park).",
        cannot_prove="Anything about correctness.",
        build_status=BUILD_PLANNED,
        advisory=False,
        demo_scenario="A parking failure that passes on a hermetic re-run in a clean sub-env.",
        expected_response="The differential detects the flip, marks NON_DETERMINISTIC, and "
                          "attributes it to the grader/harness rather than parking the coder.",
        expected_verdict=DEMO_CAUGHT,
        evidence_pointer="<run>/flake-differential.json (planned #829)",
    ),
    GateSpec(
        key="decompose_recovery",
        gate_id="G-plan",
        ticket="#824",
        title="Decompose-downgrade recovery",
        proves="An under-decomposed <2-task plan is re-decomposed rather than silently "
               "dropping to flat mode (which runs no job oracle and caps the job at non-GREEN).",
        cannot_prove="That a well-decomposed plan's tasks are individually correct.",
        build_status=BUILD_PLANNED,
        advisory=False,
        demo_scenario="A goal the planner collapses to a single task (the B1/B5 flat-downgrade).",
        expected_response="Decompose recovery detects the <2-task collapse, re-decomposes with a "
                          "bounded budget, and records the why-flat fingerprint if it cannot.",
        expected_verdict=DEMO_CAUGHT,
        evidence_pointer="<run>/decompose-diagnostics.json (planned #824)",
    ),
    GateSpec(
        key="tampering_scan",
        gate_id="G13",
        ticket="#832",
        title="Earned-GREEN tampering audit",
        proves="A GREEN's winning tree carries NO grader-tampering fingerprint (a coder-authored "
               "conftest hooking the runner, hardcoded oracle answers). The ONE sanctioned "
               "verdict-authority extension: a match downgrades GREEN → PARKED-HONEST, quoting file:line.",
        cannot_prove="Craft quality — that is the GREEN-quality audit (#837).",
        build_status=BUILD_LIVE,  # green_integrity_audit / green_audit.scan_tree are LIVE in battery.py
        advisory=False,
        demo_scenario="A GREEN whose merged tree ships a coder-authored conftest.py that hooks "
                      "the test runner.",
        expected_response="The deterministic AST/regex scan matches the tampering fingerprint and "
                          "downgrades the GREEN to PARKED-HONEST [VERIFY], quoting file:line.",
        expected_verdict=DEMO_CAUGHT,
        evidence_pointer="<run>/green-audit.json (gate LIVE — green_integrity_audit; demo driver pending #832)",
    ),
    GateSpec(
        key="green_audit",
        gate_id="G15",
        ticket="#837",
        title="GREEN-quality audit (leniency drift)",
        proves="Leniency drift — a GREEN that is fragile / regressed / unrunnable. Deterministic "
               "Layer-1 archetype-regression floor + craft lints, then an advisory diverse jury.",
        cannot_prove="Correctness the oracle already owns — and it NEVER gates (advisory band only).",
        build_status=BUILD_LIVE,  # tools/dispatch_harness/green_quality/* is LIVE
        advisory=True,
        demo_scenario="A GREEN whose tokenizer silently regressed vs the last archived GREEN "
                      "(the B2 don't/well-known drift).",
        expected_response="The archetype-regression probe diffs behavior against the last archived "
                          "GREEN, flags the regression, and stamps band C — ADVISORY, the verdict stays GREEN.",
        expected_verdict=DEMO_CAUGHT,
        evidence_pointer="<run>/green-quality.json (gate LIVE — green_quality; demo driver pending #837)",
    ),
)


def build_registry() -> dict[str, DemoDriver]:
    """The Section-A demo registry: every gate mapped to its driver. Every entry is a
    :class:`StubDemoDriver` at scaffold time — a real driver replaces its entry in place
    (same key) when it is wired against an actual gate run."""
    return {spec.key: StubDemoDriver(spec) for spec in GATE_SPECS}


def collect_demo_results(
    registry: dict[str, DemoDriver] | None = None,
    evidence_by_gate: dict[str, dict] | None = None,
) -> list[DemoResult]:
    """Run every registered demo driver, in ladder order, and return the render-ready results.

    ``evidence_by_gate`` maps a gate key to the parsed data-JSON slice a REAL driver reads
    its live artifacts from; a stub ignores it. Fail-soft: a driver that raises (e.g. an
    unfinished real driver still on the abstract base) degrades to an honest NOT-RUN result,
    never a crash and never a fabricated pass."""
    reg = registry if registry is not None else build_registry()
    ev = evidence_by_gate or {}
    by_key = {spec.key: spec for spec in GATE_SPECS}
    results: list[DemoResult] = []
    for spec in GATE_SPECS:
        driver = reg.get(spec.key)
        if driver is None:
            continue
        try:
            results.append(driver.run(ev.get(spec.key)))
        except NotImplementedError:
            s = by_key[spec.key]
            results.append(DemoResult(
                spec=s, status=DEMO_NOT_RUN, wired=False,
                machinery_response="driver present but run() not implemented — honest not-run",
                honesty_note=f"NOT-RUN: {s.ticket} driver is abstract; no evidence produced.",
            ))
    return results
