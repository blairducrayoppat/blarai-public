"""M2 adversarial-rig fixtures — structural assertions (W9, plan §9.3 / §10.2).

These lock the rig fixtures as MEANINGFUL today (before the code they attack
exists) and give W1-W5 a red target to build against:

* N4 — a task that fails identically every attempt: the canned RESULT sequence
  is truly identical (the precondition for the "one re-decompose then park"
  W5 policy) and carries structured evidence, not prose.
* N5 — garbage plans: malformed JSON is unparseable; wrong-shape JSON is
  parseable-but-invalid; model prose contains no JSON array. All three must be
  handled by degrade-to-fallback, never a crash.
* N6 — a poisoned dependency tree: a STRUCTURAL extraction of the poisoned
  files yields ONLY paths + signatures; NONE of the adversarial instruction
  text survives (asserted against the W3 reference-extractor stub).
* N7 — malicious plans: path-traversal + forbidden-root repos are refused by
  the REAL ``validate_repo``; metacharacter slugs are neutralised by the REAL
  ``slugify_task``; the tampered-hash plan mismatches the reference hash.

GPU-free, deterministic, in the standing gate (shared/tests is in scope).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.fleet.dispatch import slugify_task, validate_repo
from tests.fixtures.m2_rigs import load_json, read_text, rig_path
from tests.fixtures.m2_rigs.reference_extractor import (
    extract_mjs_signatures,
    extract_pack_signatures,
    extract_python_signatures,
)

# Sentences/tokens planted in the poisoned dependency bodies (N6). NONE of these
# may appear in any structural extraction.
_N6_POISON_TOKENS = (
    "ignore your previous instructions",
    "maintenance mode",
    "curl https://evil.example",
    "delete every test file",
    "disregard the task",
    "paste its contents",
    "AKIAINJECTED0EXAMPLE",
    "exfiltrate",
    "reveal your system prompt",
    "rm -rf",
    "process.env",
    "ghp_INJECTED_EXAMPLE_TOKEN",
    "attacker@evil.example",
    "email the result",
    "m2-n6-canary-7f3a",
)


# ===========================================================================
# N4 — identical failure every attempt
# ===========================================================================


def test_n4_attempts_are_byte_identical_failures():
    """The re-decompose-then-park policy (W5) only fires on a CONSISTENT failure;
    the rig must present identical evidence across attempts, or it isn't testing
    that path."""
    rig = load_json("n4_identical_failure.json")
    attempts = rig["attempts"]
    assert len(attempts) >= 3, "need >=3 attempts to prove 'identical every candidate'"
    summaries = {a["summary"] for a in attempts}
    assert len(summaries) == 1, "attempt summaries must be byte-identical"
    evidence = {tuple(sorted(a["evidence"].items())) for a in attempts}
    assert len(evidence) == 1, "attempt evidence must be identical"


def test_n4_evidence_is_structural_not_prose():
    """The evidence fed back to the re-decomposer (S3) is structural: test/verify
    statuses + a single capped assertion line — never a free-text narrative."""
    rig = load_json("n4_identical_failure.json")
    ev = rig["attempts"][0]["evidence"]
    assert ev["tests"] in {"pass", "fail", "none"}
    assert ev["verify"] in {"pass", "fail", "none"}
    assert "\n" not in ev["first_assertion"]
    assert len(ev["first_assertion"]) <= 200


def test_n4_parses_through_the_real_summary_parser():
    """The canned summaries are real run-fleet SUMMARY shapes — the harness's own
    parser must classify them as PARKED (not merged)."""
    from shared.fleet.dispatch import parse_summary

    rig = load_json("n4_identical_failure.json")
    outcomes = parse_summary(rig["attempts"][0]["summary"])
    assert len(outcomes) == 1 and outcomes[0].result == "PARKED"


# ===========================================================================
# N5 — garbage plans (malformed / wrong-shape / prose)
# ===========================================================================


def test_n5_malformed_json_is_unparseable():
    import json

    raw = read_text("n5_garbage_plans", "malformed.json")
    with pytest.raises(json.JSONDecodeError):
        json.loads(raw)


def test_n5_wrong_shape_is_parseable_but_invalid_tasks():
    """Schema-valid JSON whose ``tasks`` is an object, not a list — a ruler must
    reject/degrade, never index into it. We prove the shape here; the ruler lands
    in W1 (the simulator's cycle→linear-chain fallback scenario covers the live
    degrade)."""
    import json

    plan = json.loads(read_text("n5_garbage_plans", "wrong_shape.json"))
    assert not isinstance(plan["tasks"], list)


def test_n5_model_prose_carries_no_json_array():
    from shared.fleet.decompose import _parse_candidates

    prose = read_text("n5_garbage_plans", "model_prose.txt")
    # The REAL decompose parser must yield zero candidates -> the dispatch falls
    # back to a single validated task (never zero work, never a crash).
    assert _parse_candidates(prose, max_tasks=8) == []


# ===========================================================================
# N6 — poisoned dependency tree (structural extraction only)
# ===========================================================================


def test_n6_python_extraction_is_signatures_only():
    """Structural extraction returns the public function signatures and NOTHING
    from comments, docstrings, or module-level string assignments (the poison
    lives there). Exact-signature correctness is W3's own unit test; the RIG asserts
    the security property — no adversarial text leaks."""
    src = read_text("n6_poisoned_dep", "storage.py")
    sigs = extract_python_signatures(src)
    assert "append_expense(store_path, expense)" in sigs
    assert "read_expenses(store_path)" in sigs
    # The module-level POISON_MARKER assignment (an ast.Assign, not a def/class) is
    # NOT part of the extracted public surface — its poison value never appears.
    blob = " ".join(sigs).lower()
    for token in _N6_POISON_TOKENS:
        assert token.lower() not in blob, f"poison leaked into python signatures: {token!r}"


def test_n6_mjs_extraction_is_signatures_only():
    """mjs extraction returns export NAMES + signatures (a dependent legitimately
    imports an exported const by name), but never a comment, a JSDoc line, or a
    string VALUE — so the poison text never rides the pack."""
    src = read_text("n6_poisoned_dep", "widget.mjs")
    sigs = extract_mjs_signatures(src)
    assert "runningTotal(entries)" in sigs
    # An exported const's NAME may surface (public API); its poison string VALUE
    # must not. Assert every extracted item is a bare name/signature, no value text.
    blob = " ".join(sigs).lower()
    for token in _N6_POISON_TOKENS:
        assert token.lower() not in blob, f"poison leaked into mjs signatures: {token!r}"


def test_n6_pack_card_contains_no_adversarial_text():
    """The full context-pack card for a poisoned file: path + signatures, and NOT
    ONE poison token anywhere in the serialized card (S2 worm-cut)."""
    import json

    for rel, fname in (("src/expenses/storage.py", "storage.py"),
                       ("src/widget.mjs", "widget.mjs")):
        src = read_text("n6_poisoned_dep", fname)
        card = extract_pack_signatures(rel, src)
        assert card["path"] == rel
        assert card["signatures"], "expected at least one extracted signature"
        serialized = json.dumps(card).lower()
        for token in _N6_POISON_TOKENS:
            assert token.lower() not in serialized, f"poison in pack card: {token!r}"


def test_n6_readme_carrier_yields_path_only():
    """A poisoned README (pure prose — the plan's named N6 carrier) has NO
    extractable signatures, so its ONLY contribution to a context pack is its
    path. The injection paragraph + the canary token must never survive."""
    import json

    src = read_text("n6_poisoned_dep", "README.md")
    assert "m2-n6-canary-7f3a" in src.lower(), "the README must actually carry the canary"
    card = extract_pack_signatures("README.md", src)
    assert card == {"path": "README.md", "signatures": []}
    serialized = json.dumps(card).lower()
    for token in _N6_POISON_TOKENS:
        assert token.lower() not in serialized, f"poison leaked from README: {token!r}"


def test_n6_poison_tokens_really_are_in_the_source():
    """Guard against a vacuous test: the poison MUST be present in the raw files, so
    the extraction's absence of it is meaningful."""
    raw = (read_text("n6_poisoned_dep", "storage.py")
           + read_text("n6_poisoned_dep", "widget.mjs")
           + read_text("n6_poisoned_dep", "README.md")).lower()
    present = [t for t in _N6_POISON_TOKENS if t.lower() in raw]
    assert len(present) >= 10, "the rig files must actually carry the adversarial text"


# ===========================================================================
# N7 — malicious plans (traversal / forbidden root / metachars / tamper)
# ===========================================================================


def test_n7_path_traversal_repo_is_refused(tmp_path):
    projects = tmp_path / "projects"
    projects.mkdir()
    plan = load_json("n7_malicious_plans", "path_traversal_repo.json")
    # Resolve the declared repo against a real projects dir and prove the S1 gate refuses
    # it (the repo climbs out via ../..). validate_repo is the real gate. Post-H5 (#740)
    # the casefolded forbidden-root net catches the lowercase 'blarai' leaf by NAME (it
    # fires first); the containment net (outside projects_dir) is the belt-and-braces
    # second reason — either is a valid refusal, and pure containment is exercised by
    # test_fleet_dispatch::test_validate_repo_rejects_outside_projects.
    escaped = (projects / ".." / ".." / "blarai")
    err = validate_repo(escaped, projects)
    assert err is not None and ("forbidden root" in err or "outside the allowed projects dir" in err)
    assert "blarai" in plan["repo"].lower()  # the rig really targets an escape


def test_n7_forbidden_root_repo_is_refused(tmp_path):
    projects = tmp_path / "projects"
    (projects / "BlarAI").mkdir(parents=True)
    err = validate_repo(projects / "BlarAI", projects)
    assert err is not None and "forbidden root" in err


def test_n7_metacharacter_slugs_are_neutralised():
    rig = load_json("n7_malicious_plans", "metacharacter_slugs.json")
    produced = [slugify_task(s) for s in rig["hostile_slugs"]]
    # Matches the fixture's declared expectation (the fixture is self-checking).
    assert produced == rig["expected_after_slugify"]
    dangerous = set(";`$|&<>\"'\\ ") | {"..", "~"}
    for slug in produced:
        assert not (set(slug) & dangerous), f"metacharacter survived into slug: {slug!r}"
        assert ".." not in slug and "~" not in slug


def test_n7_tampered_hash_mismatches_reference():
    """The tampered plan's stored hash must NOT equal the reference canonicalization
    of its (tampered) body — so a load-time hash check catches it. Uses the W9
    reference hash until Lane A's PlanStore lands its own."""
    from tools.dispatch_harness.battery import reference_plan_hash, validate_jobplan

    plan = load_json("n7_malicious_plans", "tampered_hash.json")
    recomputed = reference_plan_hash(plan)
    assert plan["plan_hash"] != recomputed
    # And the full validator flags the mismatch as an error (fail-closed).
    errors = validate_jobplan(plan)
    assert any("plan_hash mismatch" in e for e in errors)


def test_n7_all_fixtures_present():
    """Every N7 fixture file exists (a missing rig is a silent coverage hole)."""
    for name in ("path_traversal_repo.json", "forbidden_root_repo.json",
                 "metacharacter_slugs.json", "tampered_hash.json",
                 "tampered_oracle_path.json", "advisory_status.json"):
        assert rig_path("n7_malicious_plans", name).is_file()


# ===========================================================================
# N7 (H3, #740) — immutable-identity tamper (REFUSED) vs advisory status (ADVISORY)
# ===========================================================================


def _realize_rig(tmp_path, fixture_name):
    """Write a fixture body to a hermetic tmp store whose repo points at a REAL tmp git
    repo, so ``PlanStore.load`` can run its full re-validation (hash + repo containment)."""
    from shared.fleet import plan_graph as pg

    body = load_json("n7_malicious_plans", fixture_name)
    proj = tmp_path / "projects"
    (proj / "app" / ".git").mkdir(parents=True, exist_ok=True)
    body["repo"] = str(proj / "app")
    store = pg.PlanStore(tmp_path / "job-plan.json", projects_dir=proj)
    return store, body, proj


def test_n7_oracle_path_tamper_refused_by_planstore(tmp_path):
    """(a) ``job_acceptance.oracle_path`` is a HASHED identity field (H3): redirecting it
    on disk while retaining the original hash makes ``PlanStore.load`` REFUSE on the
    mismatch. An oracle redirect is a FALSE-DONE surface (point the oracle at a passing
    file), so it must never load."""
    from shared.fleet import plan_graph as pg
    from tools.dispatch_harness.battery import reference_plan_hash, validate_jobplan

    # Static: the fixture file is itself a genuine mismatch artifact (documents the tamper).
    raw = load_json("n7_malicious_plans", "tampered_oracle_path.json")
    assert raw["job_acceptance"]["oracle_path"] == "../../evil.py"
    assert reference_plan_hash(raw) != raw["plan_hash"]
    assert any("plan_hash mismatch" in e for e in validate_jobplan(raw))

    # Live: write a clean plan (original oracle), redirect oracle_path on disk (retain the
    # hash), then load -> refuse. Proves H3 covers oracle_path through the REAL PlanStore.
    store, body, proj = _realize_rig(tmp_path, "tampered_oracle_path.json")
    clean = dict(body)
    clean["job_acceptance"] = dict(body["job_acceptance"], oracle_path="tests/test_job_acceptance.py")
    store.write(pg.validate_plan(clean, projects_dir=proj).plan)
    disk = json.loads(store.path.read_text(encoding="utf-8"))
    disk["job_acceptance"]["oracle_path"] = "../../evil.py"  # redirect, keep the hash
    store.path.write_text(json.dumps(disk), encoding="utf-8")
    loaded = store.load()
    assert not loaded.ok and "mismatch" in loaded.reason


def test_n7_advisory_status_loads_and_is_advisory(tmp_path):
    """(b) status is OUTSIDE the immutable-identity hash: flipping the task status to
    ``merged`` and ``job_acceptance.status`` to ``passed`` on disk keeps the hash valid,
    so ``PlanStore.load`` SUCCEEDS and the loaded status rides through as ADVISORY. The
    contract: a driver MUST re-derive done-ness from a fresh oracle run, never trust the
    persisted status as proof of completion."""
    from shared.fleet import plan_graph as pg
    from tools.dispatch_harness.battery import validate_jobplan

    # Static: the fixture (merged/passed on disk) validates clean — status is not integrity-covered.
    raw = load_json("n7_malicious_plans", "advisory_status.json")
    assert raw["tasks"][0]["status"] == "merged" and raw["job_acceptance"]["status"] == "passed"
    assert validate_jobplan(raw) == []

    # Live: write a PENDING plan, flip the statuses on disk (retain the hash), then load
    # -> ok, with the flipped status carried through as ADVISORY (not re-derived here).
    store, body, proj = _realize_rig(tmp_path, "advisory_status.json")
    pending = dict(body)
    pending["tasks"] = [dict(body["tasks"][0], status="pending")]
    pending["job_acceptance"] = dict(body["job_acceptance"], status="pending")
    store.write(pg.validate_plan(pending, projects_dir=proj).plan)
    disk = json.loads(store.path.read_text(encoding="utf-8"))
    disk["tasks"][0]["status"] = "merged"        # advisory flip (outside the hash)
    disk["job_acceptance"]["status"] = "passed"
    store.path.write_text(json.dumps(disk), encoding="utf-8")
    loaded = store.load()
    assert loaded.ok and loaded.plan is not None
    assert loaded.plan.task("storage-module").status == "merged"    # advisory value rides through
    assert loaded.plan.job_acceptance.status == "passed"


def test_n7_new_tamper_fixtures_documented():
    """Each new tamper fixture names its §10 surface + the refused-vs-advisory verdict."""
    for name, verdict in (("tampered_oracle_path.json", "REFUSED"),
                          ("advisory_status.json", "ADVISORY")):
        surface = load_json("n7_malicious_plans", name)["surface"]
        assert "H3" in surface and verdict in surface
