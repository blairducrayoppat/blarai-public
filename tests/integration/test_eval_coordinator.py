"""
Eval Harness — Coordinator Suite Standing-Gate Locks (#846 C4 prep / #855)
===========================================================================
Suite-specific locks for evals/suites/coordinator.py — the fixture-board
coordinator eval suite ADR-039 §2.12.7 names (golden boards -> expected
classifications/pull decisions, re-run at every model swap). The generic
harness locks (suite green, baseline clean, runner exit codes) already
apply via tests/integration/test_eval_harness.py's SUITE_NAMES
parametrization; THIS file pins what is specific to the coordinator suite:

  A. Golden integrity — every judgment kind covered; every case explicitly
     BORN-DEV (ADR-038 frozen/dev split: new scenario cards are born-dev,
     add-only; an absent card_class would silently default frozen).
  B. Coverage-shape locks — the tri-state (OK/EMPTY/UNREACHABLE) substrate
     cases, the pagination-past-the-clamp case, and the forged-Done lock
     case must all EXIST in the golden set (a later edit that drops one is
     a silent coverage regression, caught here).
  C. Real-entry-point provenance — the suite drives the REAL coordinator
     modules; source-fragment pins fail loudly if the suite ever grows a
     local reimplementation of the logic it grades (mocks lie).
  D. The #855 model-graded seam — a mode:"model" case is hardware-skipped
     by default and REFUSED (fail-closed) on an include_hardware run until
     the shadow-grading adapter exists. Zero model cases ship today.
  E. Hermeticity — a suite run leaves the process env untouched.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from evals.loader import GOLDEN_DIR, GoldenDataError, load_golden
from evals.suites import SUITE_NAMES, get_runner
from evals.suites import coordinator as coord_suite
from evals.types import CaseStatus

_GOLDEN = GOLDEN_DIR / "coordinator.jsonl"


# ---------------------------------------------------------------------------
# A. Golden integrity
# ---------------------------------------------------------------------------


class TestGoldenIntegrity:
    def test_suite_is_registered(self) -> None:
        assert "coordinator" in SUITE_NAMES

    def test_every_judgment_kind_is_covered(self) -> None:
        cases = load_golden(_GOLDEN)
        kinds = {c["kind"] for c in cases}
        assert kinds == set(coord_suite._KIND_EVALUATORS), (
            "every registered kind must have at least one golden case, and "
            "no golden case may use an unregistered kind"
        )

    def test_every_case_is_explicitly_born_dev(self) -> None:
        """ADR-038: born-frozen-XOR-born-dev, never crossing; new scenario
        cards are BORN-DEV and the field is explicit (the absent-field
        default is frozen — fail-safe — so an unstamped case would silently
        change class). Promotion to frozen is a deliberate, reviewed act
        that updates this lock in the same change."""
        cases = load_golden(_GOLDEN)
        unstamped = [c["id"] for c in cases if "card_class" not in c]
        assert not unstamped, f"cases without an explicit card_class: {unstamped}"
        not_dev = [c["id"] for c in cases if c["card_class"] != "dev"]
        assert not_dev == [], (
            f"non-dev cases found: {not_dev} — this suite's cases are all "
            "born-dev today; a frozen promotion must update this lock "
            "deliberately in the same change"
        )

    def test_no_model_cases_ship_yet(self) -> None:
        """The model-graded slice is the #855 seam — zero cases today.
        The first model case must land WITH its grading adapter (see
        TestModelSeam for the fail-closed behavior until then)."""
        cases = load_golden(_GOLDEN)
        model_cases = [
            c["id"] for c in cases if c.get("mode", "deterministic") == "model"
        ]
        assert model_cases == []


# ---------------------------------------------------------------------------
# B. Coverage-shape locks
# ---------------------------------------------------------------------------


class TestCoverageShape:
    def test_tri_state_substrate_coverage(self) -> None:
        """The golden set must exercise ALL THREE read states (ADR-039
        §2.12.6) through the real bridge — dropping the UNREACHABLE cases
        would quietly stop proving 'a dead Vikunja never reads as empty'."""
        cases = load_golden(_GOLDEN)
        statuses = {
            str(c["expected"]["status"])
            for c in cases
            if c["kind"] == "board_read"
        }
        assert statuses == {"ok", "empty", "unreachable"}

    def test_pagination_past_the_clamp_case_exists(self) -> None:
        """At least one fixture board must exceed the server's
        maxitemsperpage clamp AND expect a COMPLETE read — the ADR-039
        §2.12.2 verified-defect-class lock."""
        cases = load_golden(_GOLDEN)
        oversized = [
            c
            for c in cases
            if c["kind"] == "board_read"
            and isinstance(c["server"].get("tasks"), dict)
            and int(c["server"]["tasks"]["generate"]["count"])
            > coord_suite._SERVER_MAX_PER_PAGE
            and int(c["expected"].get("count", 0))
            > coord_suite._SERVER_MAX_PER_PAGE
        ]
        assert oversized, "no pagination-past-the-clamp golden case found"

    def test_fixture_clamp_matches_the_bridge_contract(self) -> None:
        """The fixture server clamps at the SAME page size the bridge
        requests (vikunja_bridge.DEFAULT_PAGE_SIZE) — if either side drifts,
        the pagination fixture stops testing the real clamp."""
        from shared.fleet import vikunja_bridge as vb

        assert coord_suite._SERVER_MAX_PER_PAGE == vb.DEFAULT_PAGE_SIZE

    def test_forged_done_lock_cases_exist(self) -> None:
        """The board_transition golden slice must keep both halves of the
        forged-Done lock: merged-without-oracle and oracle-without-merged
        each expecting NO transition."""
        cases = [
            c for c in load_golden(_GOLDEN) if c["kind"] == "board_transition"
        ]

        def _facts(c: dict) -> "tuple[bool, bool]":
            f = c["facts"]
            return bool(f.get("oracle_passed")), bool(f.get("merged"))

        merged_only = [
            c for c in cases if _facts(c) == (False, True) and c["expected"] is None
        ]
        oracle_only = [
            c for c in cases if _facts(c) == (True, False) and c["expected"] is None
        ]
        assert merged_only and oracle_only

    def test_tripwire_unknown_never_quiet_case_exists(self) -> None:
        """The unreachable-substrate tripwire-suppression case (unknown is
        never quiet — the silent-stall this program exists to prevent) must
        stay in the golden set."""
        cases = load_golden(_GOLDEN)
        assert any(
            c["kind"] == "snapshot_tripwire"
            and c["expected"]["fired"] is False
            and any(
                "unreachable" in str(f).lower()
                for f in c["expected"].get("suppressed_contains", [])
            )
            for c in cases
        )


# ---------------------------------------------------------------------------
# C. Real-entry-point provenance (mocks lie — the suite must keep driving
#    the real modules, never a local mirror of their logic)
# ---------------------------------------------------------------------------


class TestRealEntryPointProvenance:
    def test_suite_imports_the_real_judgment_modules(self) -> None:
        source = Path(coord_suite.__file__).read_text(encoding="utf-8")
        fragments = (
            "from shared.fleet import coord_lifecycle as cl",
            "from shared.fleet import coord_redispatch as cr",
            "from shared.fleet import flow_metrics as fm",
            "from shared.fleet import vikunja_bridge as vb",
            "from shared.fleet import work_state as ws",
            "from shared.coordinator import heartbeat_cycle as hb",
            "from shared.coordinator.proposal_store import build_proposal_store",
            "normalize_trusted_repo_id",
        )
        missing = [f for f in fragments if f not in source]
        assert not missing, (
            "the coordinator eval suite no longer drives these real entry "
            f"points: {missing} — evals must grade the REAL deterministic "
            "judgment code, never a reimplementation"
        )

    def test_redispatch_store_is_the_real_encrypted_store(self) -> None:
        """The redispatch cases must construct the born-encrypted store
        factory (build_proposal_store), not a stub — the ':memory:' dev path
        is the real cipher wiring end to end."""
        source = Path(coord_suite.__file__).read_text(encoding="utf-8")
        assert 'build_proposal_store(":memory:")' in source


# ---------------------------------------------------------------------------
# D. The #855 model-graded seam — fail-closed until the adapter lands
# ---------------------------------------------------------------------------


@pytest.fixture()
def model_case_golden(tmp_path: Path) -> Path:
    case = {
        "id": "coord-model-probe-001",
        "description": "synthetic model-graded case (the #855 seam probe)",
        "kind": "service_class",
        "card_class": "dev",
        "mode": "model",
        "task": {"id": 1, "labels": None},
        "expected_class": "Standard",
    }
    p = tmp_path / "coordinator.jsonl"
    p.write_text(json.dumps(case) + "\n", encoding="utf-8")
    return p


class TestModelSeam:
    def test_model_case_is_hardware_skipped_by_default(
        self, model_case_golden: Path
    ) -> None:
        report = coord_suite.run_suite(model_case_golden)
        assert [r.status for r in report.results] == [
            CaseStatus.SKIPPED_HARDWARE
        ]
        assert "#855" in report.results[0].detail

    def test_hardware_run_with_model_cases_is_refused(
        self, model_case_golden: Path
    ) -> None:
        """No grading adapter exists yet — a hardware run cannot evaluate a
        model case, and pretending to would be a silent pass. Fail-closed."""
        with pytest.raises(GoldenDataError, match="#855"):
            coord_suite.run_suite(model_case_golden, include_hardware=True)

    def test_deterministic_golden_ignores_include_hardware(self) -> None:
        """With zero model cases shipped, include_hardware is a no-op —
        every case evaluates either way (this breaks the day a model case
        lands without its adapter, which is the intent)."""
        report = coord_suite.run_suite(include_hardware=True)
        assert report.skipped_hardware == 0
        assert report.evaluated == report.total


# ---------------------------------------------------------------------------
# E. Hermeticity
# ---------------------------------------------------------------------------


class TestHermeticity:
    def test_suite_run_leaves_vikunja_env_untouched(self) -> None:
        keys = ("VIKUNJA_URL", "VIKUNJA_USER", "VIKUNJA_PASS")
        before = {k: os.environ.get(k) for k in keys}
        get_runner("coordinator")()
        after = {k: os.environ.get(k) for k in keys}
        assert after == before
