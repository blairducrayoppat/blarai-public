"""Gate tests for the M2 battery runner + scorecard + JobPlan-v1 validation (W9).

Covers the deterministic, GPU-free surfaces W9 ships: the battery-card spec, the
gold JobPlans, the scorecard schema/emitter (incl. the structural S6 caps and the
FALSE-DONE cross-check), the pinned JobPlan-v1 validator, the wave compiler, the
reference plan-hash, and a dry-run of the battery runner end-to-end (the smoke
that proves --dry-run emits a valid scorecard with no GPU/model/AO).

In the standing gate (tests/integration is in scope). asyncio_mode=auto.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.dispatch_harness import battery as bat
from tools.dispatch_harness import scorecard as sc
from tools.dispatch_harness.scorecard import Scorecard

_SPEC_DIR = Path(__file__).resolve().parents[2] / "evals" / "battery"


# ===========================================================================
# Battery cards
# ===========================================================================


def test_all_eight_cards_load_and_validate():
    cards = bat.load_cards(_SPEC_DIR)
    assert set(cards) == {f"B{i}" for i in range(1, 9)}
    for cid, card in cards.items():
        assert card["units"] >= 1
        assert bat._SANDBOX_REPO_RE.match(card["repo"]), f"{cid} repo not sandbox-pinned"


def test_card_repo_must_be_sandbox_pinned():
    bad = {"schema": "battery-card/v1", "id": "B1", "repo": "C:/Users/mrbla/projects/real-repo",
           "goal": "g", "units": 3, "stack": "python-cli", "shape": "chain", "title": "t",
           "rigs": [], "expected_outcome": {"allowed_terminal_verdicts": ["GREEN"],
           "target_verdict": "GREEN", "oracle": {"expected": True}, "must_verify_tiers": []}}
    errors = bat.validate_card(bad)
    assert any("S5 sandbox pin" in e for e in errors)


def test_card_cannot_allow_false_done():
    bad = {"schema": "battery-card/v1", "id": "B2", "repo": "battery-x", "goal": "g",
           "units": 3, "stack": "python-cli", "shape": "chain", "title": "t", "rigs": [],
           "expected_outcome": {"allowed_terminal_verdicts": ["GREEN", "FALSE-DONE"],
           "target_verdict": "GREEN", "oracle": {"expected": True}, "must_verify_tiers": []}}
    errors = bat.validate_card(bad)
    assert any("FALSE-DONE can never be an allowed terminal verdict" in e for e in errors)


def test_b8_carries_the_negative_rigs():
    cards = bat.load_cards(_SPEC_DIR)
    assert cards["B8"]["rigs"] == ["N1", "N2", "N3"]
    # B8 with the rigs armed may only end PARKED-HONEST (a GREEN would be a caught net failing).
    assert cards["B8"]["expected_outcome"]["allowed_terminal_verdicts"] == ["PARKED-HONEST"]


# ===========================================================================
# ADR-038 — frozen/dev card-class split marker + contamination tripwire (#838)
# ===========================================================================


def _card(cid="B5", repo="battery-x", **over):
    """A minimal valid battery card for the card-class tests."""
    card = {
        "schema": "battery-card/v1",
        "id": cid,
        "repo": repo,
        "goal": "g",
        "units": 3,
        "stack": "python-cli",
        "shape": "chain",
        "title": "t",
        "rigs": [],
        "expected_outcome": {
            "allowed_terminal_verdicts": ["GREEN"],
            "target_verdict": "GREEN",
            "oracle": {"expected": True},
            "must_verify_tiers": [],
        },
    }
    card.update(over)
    return card


def test_existing_battery_cards_are_all_frozen():
    # The seed FROZEN eval set: every shipped card loads, validates, and resolves to
    # card_class 'frozen' — byte-behavior-identical to before the split (#838 D4).
    cards = bat.load_cards(_SPEC_DIR)
    assert set(cards) == {f"B{i}" for i in range(1, 9)}
    for cid, card in cards.items():
        assert card["card_class"] == bat.CARD_CLASS_FROZEN, f"{cid} not frozen"
        assert bat.resolve_card_class(card) == "frozen"


def test_frozen_battery_cards_carry_the_explicit_frozen_stamp():
    # The born-frozen attestation is ON DISK, not merely defaulted (#838 D4).
    for i in range(1, 9):
        raw = json.loads((_SPEC_DIR / f"B{i}.json").read_text(encoding="utf-8"))
        assert raw.get("card_class") == "frozen", f"B{i}.json is missing the frozen stamp"


def test_card_class_absent_defaults_to_frozen():
    # Fail-safe: an unstamped card is measurement-only (frozen), never a tuning card.
    card = _card()
    card.pop("card_class", None)
    assert bat.validate_card(card) == []            # absent is valid
    assert bat.resolve_card_class(card) == "frozen"


def test_a_dev_card_is_distinguishable_and_validates():
    dev = _card(cid="D1", card_class="dev")
    assert bat.validate_card(dev) == []
    assert bat.resolve_card_class(dev) == "dev"


def test_born_frozen_xor_born_dev_never_crosses():
    # A frozen (B<n>) id cannot be class 'dev'.
    assert any("never crossing" in e for e in bat.validate_card(_card(cid="B5", card_class="dev")))
    # A dev (D<n>) id MUST self-declare card_class='dev' — a frozen stamp or an absent
    # field on a D-id is rejected (dev cards never inherit frozen).
    assert any("MUST set card_class='dev'" in e
               for e in bat.validate_card(_card(cid="D2", card_class="frozen")))
    d_absent = _card(cid="D3")
    d_absent.pop("card_class", None)
    assert any("MUST set card_class='dev'" in e for e in bat.validate_card(d_absent))
    # An unrecognized class value is rejected outright.
    assert any("card_class 'tuning'" in e for e in bat.validate_card(_card(card_class="tuning")))


def test_load_dev_cards_reads_the_dev_namespace(tmp_path):
    dev_dir = tmp_path / "dev"
    dev_dir.mkdir()
    (dev_dir / "D1.json").write_text(
        json.dumps(_card(cid="D1", repo="battery-dev-probe", card_class="dev")),
        encoding="utf-8",
    )
    cards = bat.load_dev_cards(dev_dir)
    assert set(cards) == {"D1"}
    assert cards["D1"]["card_class"] == "dev"


def test_load_dev_cards_empty_or_absent_is_ok(tmp_path):
    # No dev cards yet is the birth state — {}, never a raise (unlike load_cards).
    assert bat.load_dev_cards(tmp_path / "nonexistent") == {}
    (tmp_path / "dev").mkdir()
    assert bat.load_dev_cards(tmp_path / "dev") == {}


def test_load_dev_cards_fails_closed_on_a_misclassed_dev_file(tmp_path):
    dev_dir = tmp_path / "dev"
    dev_dir.mkdir()
    # A D-named file that is not born-dev must fail loudly, never load as a tuning card.
    (dev_dir / "D9.json").write_text(
        json.dumps(_card(cid="D9", card_class="frozen", repo="battery-x")),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        bat.load_dev_cards(dev_dir)


def test_contamination_tripwire_fires_on_a_frozen_id_in_a_tuning_manifest():
    # A tuning/dev-run manifest that references a frozen card's id trips the fail-loud
    # gate (#838 D4) — the enforcement of "MEASUREMENT-ONLY on frozen cards."
    with pytest.raises(bat.FrozenContaminationError) as exc:
        bat.assert_no_frozen_in_tuning(["D1", "B2", "battery-dev-probe"], spec_dir=_SPEC_DIR)
    assert "B2" in str(exc.value)
    # The sandbox-repo fingerprint fires too (a manifest may record repos, not ids).
    b1_repo = bat.load_cards(_SPEC_DIR)["B1"]["repo"]
    with pytest.raises(bat.FrozenContaminationError):
        bat.assert_no_frozen_in_tuning([b1_repo], spec_dir=_SPEC_DIR)


def test_contamination_tripwire_passes_a_clean_dev_only_manifest():
    # A manifest of only dev ids/repos is clean — no raise; the pure form returns [].
    bat.assert_no_frozen_in_tuning(["D1", "D2", "battery-dev-probe"], spec_dir=_SPEC_DIR)
    prints = bat.frozen_fingerprints(_SPEC_DIR)
    assert bat.frozen_ids_in_manifest(["D1", "battery-dev-probe"], prints) == []


def test_frozen_fingerprints_cover_both_id_and_repo():
    prints = bat.frozen_fingerprints(_SPEC_DIR)
    assert "B1" in prints and "B8" in prints
    assert bat.load_cards(_SPEC_DIR)["B1"]["repo"] in prints


# ===========================================================================
# Gold JobPlans
# ===========================================================================


@pytest.mark.parametrize("name", ["gold-b1", "gold-b3", "gold-b6"])
def test_gold_plans_load_validate_and_hash(name):
    plan = bat.load_gold_plan(_SPEC_DIR / "gold" / f"{name}.json")
    # The stamped hash matches the immutable-identity reference canonicalization
    # (load_gold_plan checks it) — re-stamped for the H3 full-identity hash (#740).
    assert plan["plan_hash"] == bat.reference_plan_hash(plan)


def test_gold_b1_is_a_three_task_chain():
    plan = bat.load_gold_plan(_SPEC_DIR / "gold" / "gold-b1.json")
    waves = bat.compute_waves(plan["tasks"])
    assert [len(w) for w in waves] == [1, 1, 1]  # a strict chain


def test_gold_b3_is_a_five_task_fan_in():
    plan = bat.load_gold_plan(_SPEC_DIR / "gold" / "gold-b3.json")
    waves = bat.compute_waves(plan["tasks"])
    # storage -> {add, total, categories} -> page (fan-in join).
    assert waves[0] == ["storage-module"]
    assert waves[-1] == ["budget-page"]
    assert len(plan["tasks"]) == 5


# ===========================================================================
# JobPlan-v1 validation (the pinned #740 contract)
# ===========================================================================


def _good_plan() -> dict:
    plan = bat._plan_from = {
        "schema": "jobplan/v1", "plan_id": "p", "goal": "g",
        "repo": "C:/Users/mrbla/projects/battery-p",
        "tasks": [
            {"id": "a", "prompt": "x", "depends_on": [],
             "contract": {"creates": ["a.py"], "exports": ["a()"], "notes": ""},
             "status": "pending"},
            {"id": "b", "prompt": "x", "depends_on": ["a"],
             "contract": {"creates": ["b.py"], "exports": ["b()"], "notes": ""},
             "status": "pending"},
        ],
        "integration_nodes": [{"after_wave": 1, "status": "pending"}],
        "job_acceptance": {"criteria": [], "oracle_path": "tests/x.py", "status": "pending"},
        "redecompose_budget": {"per_task": 1, "per_job": 2, "spent": 0},
        "plan_hash": "x",
    }
    return plan


def test_good_plan_validates():
    assert bat.validate_jobplan(_good_plan(), check_hash=False) == []


def test_cycle_is_rejected():
    plan = _good_plan()
    plan["tasks"][0]["depends_on"] = ["b"]  # a<->b
    errors = bat.validate_jobplan(plan, check_hash=False)
    assert any("cycle" in e for e in errors)


def test_self_dependency_is_rejected():
    plan = _good_plan()
    plan["tasks"][0]["depends_on"] = ["a"]
    errors = bat.validate_jobplan(plan, check_hash=False)
    assert any("depends on itself" in e for e in errors)


def test_unknown_dependency_is_rejected():
    plan = _good_plan()
    plan["tasks"][1]["depends_on"] = ["ghost"]
    errors = bat.validate_jobplan(plan, check_hash=False)
    assert any("unknown task" in e for e in errors)


def test_bad_task_status_is_rejected():
    plan = _good_plan()
    plan["tasks"][0]["status"] = "done"  # not in the pinned vocabulary
    errors = bat.validate_jobplan(plan, check_hash=False)
    assert any("status" in e for e in errors)


def test_contract_notes_over_280_is_rejected():
    plan = _good_plan()
    plan["tasks"][0]["contract"]["notes"] = "x" * 281
    errors = bat.validate_jobplan(plan, check_hash=False)
    assert any("notes must be a string of <= 280" in e for e in errors)


def test_integration_node_beyond_wave_count_is_rejected():
    plan = _good_plan()
    plan["integration_nodes"] = [{"after_wave": 9, "status": "pending"}]
    errors = bat.validate_jobplan(plan, check_hash=False)
    assert any("exceeds the plan's" in e for e in errors)


def test_hash_mismatch_is_caught_when_checked():
    plan = _good_plan()
    plan["plan_hash"] = "deadbeef"
    errors = bat.validate_jobplan(plan, check_hash=True)
    assert any("plan_hash mismatch" in e for e in errors)


def test_reference_hash_ignores_volatile_status():
    """The canonical form drops every MUTABLE status field so a legitimate status write
    never invalidates the hash (else the S1 tamper check would fire on our own writes).
    H3 (#740): task.status, budget.spent, integration_nodes[].status, and
    job_acceptance.status are all excluded from the immutable-identity seal."""
    plan = _good_plan()
    h1 = bat.reference_plan_hash(plan)
    plan["tasks"][0]["status"] = "merged"
    plan["tasks"][1]["status"] = "building"
    plan["job_acceptance"]["status"] = "passed"
    plan["redecompose_budget"]["spent"] = 1
    plan["integration_nodes"][0]["status"] = "passed"
    h2 = bat.reference_plan_hash(plan)
    assert h1 == h2


def test_reference_hash_covers_immutable_identity():
    """H3 (#740): a change to ANY hashed identity field must change the hash — the
    complement of the status-exclusion test, so the seal is proven to actually seal."""
    base = bat.reference_plan_hash(_good_plan())
    for mut in (
        lambda p: p.__setitem__("goal", "other"),
        lambda p: p.__setitem__("repo", "C:/Users/mrbla/projects/battery-other"),
        lambda p: p["tasks"][0].__setitem__("prompt", "tampered"),
        lambda p: p["tasks"][1].__setitem__("depends_on", []),
        lambda p: p["tasks"][0]["contract"].__setitem__("creates", ["evil.py"]),
        lambda p: p["job_acceptance"].__setitem__("oracle_path", "../../evil.py"),
        lambda p: p["job_acceptance"].__setitem__("criteria", ["x"]),
        lambda p: p["redecompose_budget"].__setitem__("per_job", 99),
        lambda p: p["integration_nodes"].__setitem__(0, {"after_wave": 2, "status": "pending"}),
    ):
        plan = _good_plan()
        mut(plan)
        assert bat.reference_plan_hash(plan) != base


def test_compute_waves_orders_and_detects_cycles():
    tasks = [{"id": "a", "depends_on": []}, {"id": "b", "depends_on": ["a"]},
             {"id": "c", "depends_on": ["a"]}, {"id": "d", "depends_on": ["b", "c"]}]
    assert bat.compute_waves(tasks) == [["a"], ["b", "c"], ["d"]]
    with pytest.raises(ValueError, match="cycle"):
        bat.compute_waves([{"id": "x", "depends_on": ["y"]},
                          {"id": "y", "depends_on": ["x"]}])


# ===========================================================================
# Scorecard schema + emitter
# ===========================================================================


def _green() -> Scorecard:
    return Scorecard(job_id="B1", verdict="GREEN", evidence={"oracle_status": "passed"},
                     versions={"blarai": "abc1234"})


def test_green_scorecard_validates_and_round_trips(tmp_path):
    path = tmp_path / "B1.scorecard.json"
    sc.write_scorecard(_green(), path)
    back = sc.read_scorecard(path)
    assert back.verdict == "GREEN" and back.attribution == ""


def test_green_with_attribution_is_invalid():
    card = _green()
    card.attribution = "PLAN"
    assert any("GREEN carries no attribution" in e for e in sc.validate(card))


def test_non_green_requires_attribution():
    card = Scorecard(job_id="B1", verdict="PARKED-HONEST", evidence={"oracle_status": "failed"})
    assert any("requires attribution" in e for e in sc.validate(card))
    card.attribution = "VERIFY"
    assert sc.validate(card) == []


def test_scorecard_rejects_raw_log_newlines_in_evidence():
    card = Scorecard(job_id="B1", verdict="STALLED", attribution="HARNESS",
                     evidence={"traceback": "line1\nline2\nline3"})
    problems = sc.validate(card)
    assert any("newline" in e for e in problems)


def test_scorecard_rejects_bad_oracle_status():
    card = Scorecard(job_id="B1", verdict="GREEN", evidence={"oracle_status": "green"})
    assert any("oracle_status" in e for e in sc.validate(card))


def test_write_scorecard_refuses_invalid(tmp_path):
    bad = Scorecard(job_id="", verdict="NOPE")
    with pytest.raises(ValueError, match="refusing to write an invalid scorecard"):
        sc.write_scorecard(bad, tmp_path / "bad.json")


# ===========================================================================
# The FALSE-DONE cross-check (runner teeth)
# ===========================================================================


def test_cross_check_rewrites_green_without_oracle_pass():
    card = {"id": "B1", "rigs": [], "expected_outcome": {"oracle": {"expected": True}}}
    claimed = Scorecard(job_id="B1", verdict="GREEN", evidence={"oracle_status": "not-run"})
    out = bat.cross_check(claimed, card)
    assert out.verdict == "FALSE-DONE" and out.attribution == "VERIFY"


def test_cross_check_rewrites_green_on_rig_job():
    card = {"id": "B8", "rigs": ["N1", "N2", "N3"],
            "expected_outcome": {"oracle": {"expected": True}}}
    claimed = Scorecard(job_id="B8", verdict="GREEN", evidence={"oracle_status": "passed"})
    out = bat.cross_check(claimed, card)
    assert out.verdict == "FALSE-DONE" and out.attribution == "VERIFY"


def test_cross_check_leaves_a_legitimate_green():
    card = {"id": "B1", "rigs": [], "expected_outcome": {"oracle": {"expected": True}}}
    claimed = Scorecard(job_id="B1", verdict="GREEN", evidence={"oracle_status": "passed"})
    assert bat.cross_check(claimed, card).verdict == "GREEN"


# ===========================================================================
# Schema <-> module drift lock (the README promise)
# ===========================================================================


def test_scorecard_json_schema_matches_the_module_taxonomies():
    schema = json.loads((_SPEC_DIR / "scorecard.schema.json").read_text(encoding="utf-8"))
    props = schema["properties"]
    assert set(props["verdict"]["enum"]) == set(sc.VERDICTS)
    assert set(props["attribution"]["enum"]) == set(sc.ATTRIBUTIONS) | {""}
    oracle_enum = props["evidence"]["properties"]["oracle_status"]["enum"]
    assert set(oracle_enum) == set(sc.ORACLE_STATUSES)
    assert schema["properties"]["schema"]["const"] == sc.SCORECARD_SCHEMA


# ===========================================================================
# Dry-run battery smoke (no GPU, no model, no AO) — the runner emits a valid card
# ===========================================================================


async def test_dry_run_battery_b1_emits_green_scorecard(tmp_path):
    cards = bat.load_cards(_SPEC_DIR)
    b1 = cards["B1"]
    harness = bat.build_dry_run_harness([b1], session_id="test")
    summary = await bat.run_battery(harness, [b1], out_dir=tmp_path, dry_run=True, log=lambda *_: None)
    assert len(summary.scorecards) == 1
    card = summary.scorecards[0]
    assert card.job_id == "B1" and card.verdict == "GREEN"
    assert card.evidence.get("oracle_status") == "passed"
    assert summary.false_done == 0 and summary.exit_code() == 0
    # the scorecard + summary landed on disk, valid
    written = sc.read_scorecard(tmp_path / "B1.scorecard.json")
    assert written.verdict == "GREEN"
    assert (tmp_path / "battery-summary.json").is_file()


async def test_dry_run_battery_b8_parks_honestly(tmp_path):
    cards = bat.load_cards(_SPEC_DIR)
    b8 = cards["B8"]
    harness = bat.build_dry_run_harness([b8], session_id="test")
    summary = await bat.run_battery(harness, [b8], out_dir=tmp_path, dry_run=True, log=lambda *_: None)
    card = summary.scorecards[0]
    # B8 carries rigs -> the honest fake parks; a GREEN would have been rewritten FALSE-DONE.
    assert card.verdict == "PARKED-HONEST" and card.attribution == "VERIFY"
    assert summary.false_done == 0


def test_synthesize_scorecard_is_stalled_without_driver_card(tmp_path):
    """No driver scorecard + a 'merged' run == unverifiable == STALLED/HARNESS, never
    an unearned GREEN (the FALSE-DONE class the runner refuses to mint)."""
    from tools.dispatch_harness.report import JobReport

    card = bat.load_cards(_SPEC_DIR)["B1"]
    report = JobReport(repo=card["repo"], goal=card["goal"], verdict="COMPLETE",
                       outcome="MERGED", run_id="RID-1")
    out = bat.synthesize_scorecard(report, card, runs_dir=tmp_path, dry_run=False)
    assert out.verdict == "STALLED" and out.attribution == "HARNESS"
    assert out.evidence["oracle_status"] == "not-run"


def test_unknown_job_id_is_a_loud_stalled_card():
    out = bat.stalled_scorecard("B9", "unknown battery id 'B9'")
    assert out.verdict == "STALLED" and out.attribution == "HARNESS"
    assert sc.validate(out) == []


# ===========================================================================
# #750 fix 2 — re-ensure the live AO before each job (defense-in-depth)
# ===========================================================================


def _reensurer(ready, boot):
    """A fast, socket-free AoReensurer for policy tests (no real socket/process/GPU;
    small timings + a no-op sleep so the poll loops are instant). Returns the
    re-ensurer and a boot-call counter."""
    calls = {"boot": 0}

    def _counting_boot() -> None:
        calls["boot"] += 1
        boot()

    r = bat.AoReensurer(
        port=5001, repo_root=Path("."), ready=ready, boot=_counting_boot,
        sleep=lambda _s: None, log=lambda *_: None,
        initial_grace_s=6.0, boot_wait_s=6.0, poll_s=3.0,
    )
    return r, calls


def test_reensure_noop_when_ao_already_up():
    r, calls = _reensurer(ready=lambda: True, boot=lambda: None)
    assert r.ensure("B1") is True
    assert calls["boot"] == 0  # never re-boot a live AO


def test_reensure_waits_out_inflight_relaunch_without_double_boot():
    # Down on the first check, then a still-cold-loading swap-back relaunch binds
    # during the grace window — no second launcher spawned (the instance-lock trap).
    seq = iter([False, True])
    r, calls = _reensurer(ready=lambda: next(seq, True), boot=lambda: None)
    assert r.ensure("B4") is True
    assert calls["boot"] == 0


def test_reensure_reboots_and_recovers_when_ao_is_dead():
    state = {"booted": False}
    r, calls = _reensurer(
        ready=lambda: state["booted"],                 # down until boot, up after
        boot=lambda: state.__setitem__("booted", True),
    )
    assert r.ensure("B4") is True
    assert calls["boot"] == 1  # exactly one re-boot recovered it


def test_reensure_returns_false_when_reboot_never_comes_up():
    r, calls = _reensurer(ready=lambda: False, boot=lambda: None)
    assert r.ensure("B6") is False   # honest failure -> the job STALLs, next job re-tries
    assert calls["boot"] == 1


def test_reensure_is_failsoft_on_probe_error():
    def _boom() -> bool:
        raise OSError("probe blew up")

    r, calls = _reensurer(ready=_boom, boot=lambda: None)
    assert r.ensure("B1") is False   # never raises into the battery loop
    assert calls["boot"] == 0


def test_ao_socket_ready_true_on_live_listener_false_when_refused():
    import socket as _socket

    srv = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    try:
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        assert bat.ao_socket_ready(port, timeout_s=1.0) is True
    finally:
        srv.close()
    # The just-closed port refuses -> not ready.
    assert bat.ao_socket_ready(port, timeout_s=0.5) is False


def _spawn_mtls_server(server_cert: Path, server_key: Path):
    """Start a one-shot loopback TLS server presenting *server_cert* (signed by some per-boot
    CA); it completes the handshake and closes. Returns ``(port, stop_fn)``. It does NOT
    require a client cert, so the ONLY thing under test is whether the probe's CA verifies the
    SERVER leaf — an exact stand-in for the live AO whose leaf was minted under a since-rotated
    CA (the 2026-07-06 drift)."""
    import socket as _socket
    import ssl as _ssl
    import threading

    ctx = _ssl.SSLContext(_ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=str(server_cert), keyfile=str(server_key))
    srv = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    srv.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    srv.settimeout(0.5)
    port = srv.getsockname()[1]
    stop = threading.Event()

    def _serve() -> None:
        while not stop.is_set():
            try:
                raw, _ = srv.accept()
            except _socket.timeout:
                continue
            except OSError:
                break
            try:
                with ctx.wrap_socket(raw, server_side=True) as ss:
                    ss.recv(1)  # block until the client closes after the handshake
            except (OSError, _ssl.SSLError):
                pass

    t = threading.Thread(target=_serve, daemon=True)
    t.start()

    def _stop() -> None:
        stop.set()
        srv.close()
        t.join(timeout=2.0)

    return port, _stop


def test_ao_mtls_healthy_verifies_current_ca_and_flags_drift(tmp_path):
    """The mTLS-health probe PASSES only when the server leaf verifies against the CA it is
    handed — reproducing the 2026-07-06 trap: a live listener whose leaf was minted under a
    DIFFERENT (since-rotated) CA reads as UNHEALTHY, exactly the state a bare-socket check
    cannot see."""
    from shared.security.cert_provisioning import (
        CA_CERT_NAME,
        GATEWAY_CLIENT_CERT_NAME,
        GATEWAY_CLIENT_KEY_NAME,
        PA_SERVER_CERT_NAME,
        PA_SERVER_KEY_NAME,
        provision_per_boot_certs,
    )

    a = tmp_path / "a"
    b = tmp_path / "b"
    provision_per_boot_certs(certs_dir=a)  # CA_a + its server/client leaves
    provision_per_boot_certs(certs_dir=b)  # a DIFFERENT CA_b (the rotation/drift)

    client_cert = a / GATEWAY_CLIENT_CERT_NAME
    client_key = a / GATEWAY_CLIENT_KEY_NAME
    port, stop = _spawn_mtls_server(a / PA_SERVER_CERT_NAME, a / PA_SERVER_KEY_NAME)
    try:
        # Matching CA -> the server leaf verifies -> healthy.
        assert bat.ao_mtls_healthy(port, client_cert, client_key, a / CA_CERT_NAME) is True
        # A rotated CA (the drift) -> the leaf no longer verifies -> unhealthy.
        assert bat.ao_mtls_healthy(port, client_cert, client_key, b / CA_CERT_NAME) is False
    finally:
        stop()
    # Nothing listening now -> unhealthy (connection refused), never raises.
    assert bat.ao_mtls_healthy(port, client_cert, client_key, a / CA_CERT_NAME) is False
    # Absent certs -> unprobeable == unhealthy, never raises.
    assert bat.ao_mtls_healthy(port, tmp_path / "nope.pem", tmp_path / "no.key",
                               a / CA_CERT_NAME) is False


def test_reensure_real_treats_cert_drift_as_not_ready(tmp_path):
    """AoReensurer.real readiness = socket liveness AND mTLS health: a listener that is UP but
    whose leaf does not verify against the on-disk CA reads NOT ready, so the reensure reboots
    it (re-minting one consistent set) — where the old bare-socket readiness would have reused
    the orphan and every job would STALL [HARNESS] (2026-07-06)."""
    from shared.security.cert_provisioning import (
        PA_SERVER_CERT_NAME,
        PA_SERVER_KEY_NAME,
        provision_per_boot_certs,
    )

    healthy_certs = tmp_path / "healthy" / "certs"
    drift_certs = tmp_path / "drift" / "certs"
    provision_per_boot_certs(certs_dir=healthy_certs)  # the CA the SERVER leaf is signed by
    provision_per_boot_certs(certs_dir=drift_certs)    # a different CA the client would trust

    port, stop = _spawn_mtls_server(healthy_certs / PA_SERVER_CERT_NAME,
                                    healthy_certs / PA_SERVER_KEY_NAME)
    try:
        healthy = bat.AoReensurer.real(port=port, repo_root=tmp_path,
                                       reboot_log_dir=tmp_path, certs_dir=healthy_certs)
        drifted = bat.AoReensurer.real(port=port, repo_root=tmp_path, reboot_log_dir=tmp_path,
                                       certs_dir=drift_certs, log=lambda *_: None)
        assert healthy.ready() is True   # socket up AND the leaf verifies -> reuse
        assert drifted.ready() is False  # socket up but the leaf is orphaned -> reboot
    finally:
        stop()
    # Socket down -> not ready regardless of certs (no listener to verify).
    down = bat.AoReensurer.real(port=port, repo_root=tmp_path, reboot_log_dir=tmp_path,
                                certs_dir=healthy_certs)
    assert down.ready() is False


def test_reensure_real_socket_only_when_certs_absent(tmp_path):
    """When the certs are ABSENT (never in production — the launcher mints them at boot) the
    reensure degrades to socket-only rather than looping on reboots it cannot cure: a live
    listener with no certs on disk still reads ready."""
    import socket as _socket

    srv = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    try:
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        r = bat.AoReensurer.real(port=port, repo_root=tmp_path, reboot_log_dir=tmp_path,
                                 certs_dir=tmp_path / "absent-certs")
        assert r.ready() is True  # socket up, certs unprobeable -> socket-only readiness
    finally:
        srv.close()


async def test_run_battery_calls_ensure_ao_before_each_job(tmp_path):
    cards = bat.load_cards(_SPEC_DIR)
    picked = [cards["B1"], cards["B2"]]
    harness = bat.build_dry_run_harness(picked, session_id="test")
    seen: list[str] = []
    await bat.run_battery(
        harness, picked, out_dir=tmp_path, dry_run=True, log=lambda *_: None,
        ensure_ao=lambda job_id: (seen.append(job_id) or True),
    )
    assert seen == ["B1", "B2"]  # ensured once per job, in dispatch order


async def test_run_battery_without_ensure_ao_is_unchanged(tmp_path):
    # ensure_ao defaults to None (dry-run / tests) -> the loop is byte-identical.
    cards = bat.load_cards(_SPEC_DIR)
    b1 = cards["B1"]
    harness = bat.build_dry_run_harness([b1], session_id="test")
    summary = await bat.run_battery(harness, [b1], out_dir=tmp_path, dry_run=True,
                                    log=lambda *_: None)
    assert summary.scorecards[0].verdict == "GREEN"


# ===========================================================================
# #740 language-force — the dispatched goal states each card's declared stack
# ===========================================================================


def test_augment_goal_forces_the_declared_language_and_shape():
    g = "make me three helpers"
    py = bat.augment_goal_for_stack(g, "python-cli")
    node = bat.augment_goal_for_stack(g, "node")
    web = bat.augment_goal_for_stack(g, "node-web")
    lib = bat.augment_goal_for_stack(g, "python-lib")
    assert py.startswith(g) and "Python command-line tool" in py
    assert node.startswith(g) and "Node.js command-line tool" in node   # NOT a web app
    assert web.startswith(g) and "Node.js web application" in web
    assert lib.startswith(g) and "Python library" in lib
    # the two node shapes are distinguishable so command-line+node -> node-cli, web -> web
    assert "command-line" in node and "web application" not in node


def test_augment_goal_is_noop_for_unmapped_or_empty_stack():
    g = "make me a thing"
    assert bat.augment_goal_for_stack(g, "") == g
    assert bat.augment_goal_for_stack(g, "rust") == g          # no mapping -> unchanged
    assert bat.augment_goal_for_stack(g, "PYTHON-CLI").startswith(g)   # case-insensitive


def test_every_battery_card_stack_is_mapped():
    # every real card's declared stack must have a language-force instruction, else that
    # card would silently fall to the house default (the mixed-language mismatch).
    cards = bat.load_cards(_SPEC_DIR)
    for cid, card in cards.items():
        stack = str(card.get("stack", "")).strip().lower()
        assert stack in bat._STACK_INSTRUCTION, f"{cid} stack '{stack}' has no language-force mapping"


# ===========================================================================
# #740 — UTF-8 runner output (a non-cp1252 char in job content must not crash it)
# ===========================================================================


def test_force_utf8_output_reconfigures_stdout_and_stderr(monkeypatch):
    import sys as _sys

    calls: list[dict] = []

    class _Recon:
        def reconfigure(self, **kw):
            calls.append(kw)

    monkeypatch.setattr(_sys, "stdout", _Recon())
    monkeypatch.setattr(_sys, "stderr", _Recon())
    bat._force_utf8_output()
    assert len(calls) == 2 and all(c.get("encoding") == "utf-8" for c in calls)


def test_force_utf8_output_is_failsoft_without_reconfigure(monkeypatch):
    import sys as _sys

    class _NoRecon:  # a stream that can't be reconfigured (e.g. already-wrapped) must not crash
        pass

    monkeypatch.setattr(_sys, "stdout", _NoRecon())
    monkeypatch.setattr(_sys, "stderr", _NoRecon())
    bat._force_utf8_output()  # no raise
    # and a '≥' can be formatted into a log string without error once UTF-8 is forced
    assert "≥ 2 tasks" in f"needs {chr(0x2265)} 2 tasks"


# ===========================================================================
# Unattended-safety: a web-surface battery dispatch never screen-takes (M2 B3/B5)
# ===========================================================================
#
# The node-web cards (B3 budget, B5 habit) run overnight, unattended. Their #688 VLM design
# critique renders the built page for the vision model -- and that render MUST stay headless
# (off-screen), or an overnight battery would seize the operator's screen. The capture FLAGS
# themselves (--headless=new; Find-AppExe excluding node_modules) are locked co-located with
# the script in agentic-setup scripts/verify-capture.ps1 (the WC* section), plus the live-
# script check below.


def test_web_is_a_design_surface_so_web_jobs_use_the_headless_capture():
    """A web dispatch routes to the #688 design loop (which captures via headless msedge), NOT a
    desktop/foreground GDI grab. Locks web in _DESIGN_SURFACES -- the routing that sends a web
    job to the headless web tier of capture-app.ps1 rather than the (screen-taking) Tier 2."""
    from shared.fleet.swap_driver import _DESIGN_SURFACES

    assert "web" in _DESIGN_SURFACES


def test_node_web_battery_cards_are_visual_eyeball_never_auto_passed():
    """B3/B5 grade on the OBJECTIVE tiers (build+behavior via the node oracle); the visual tier
    is HUMAN/eyeball -- handed to the operator, never machine-passed. This is why an unattended
    overnight web run is honest: it never claims the look is verified, so the VLM capture is a
    loop signal only. Locked so a card can never silently flip visual into must-verify."""
    cards = bat.load_cards(_SPEC_DIR)
    node_web = {cid: c for cid, c in cards.items() if c.get("stack") == "node-web"}
    assert {"B3", "B5"} <= set(node_web), "B3/B5 must be the node-web web cards"
    for cid, card in node_web.items():
        eo = card["expected_outcome"]
        assert card["clarify_answer"] == "web", f"{cid} does not clarify to web"
        assert "visual" in eo["human_tiers_expected"], f"{cid} visual tier is not eyeball/human"
        assert "visual" not in eo["must_verify_tiers"], f"{cid} visual is machine-must-verify (would auto-pass)"


def test_web_design_capture_is_headless_in_the_live_capture_script():
    """The capture the battery's web jobs actually hit (agentic-setup capture-app.ps1) renders
    the page with headless Edge -- no visible window, no full-desktop grab -- and the ONLY
    screen-taking tier (capture-app-foreground.ps1, Tier 2) sits above the web tier and is
    App.exe-gated, so a web project (no App.exe) never reaches it. Skips (never fails) if the
    sibling agentic-setup repo is not on this box (a bare CI checkout); it is present in the
    operator's dev environment, where the battery and the standing gate run."""
    from shared.fleet.dispatch import _AGENTIC_SETUP

    capture = _AGENTIC_SETUP / "scripts" / "capture-app.ps1"
    if not capture.exists():
        pytest.skip(f"fleet capture script not present at {capture} (sibling repo absent)")
    src = capture.read_text(encoding="utf-8", errors="replace")
    assert "TIER WEB" in src, "capture-app.ps1 has no headless web tier"
    assert "--headless=new" in src, "the web tier does not use headless Edge (--headless=new)"
    assert src.index("capture-app-foreground.ps1") < src.index("TIER WEB"), (
        "the screen-taking foreground tier must sit ABOVE the web tier (App.exe-gated; a web "
        "project never reaches it)"
    )


# ===========================================================================
# #761 — boot_launcher_detached: pythonw spawn (no VISIBLE console, no HIDDEN one)
# ===========================================================================
#
# Root cause (#761 c.1424): the venv python.exe is the Windows LAUNCHER SHIM — it
# spawns the BASE console-subsystem interpreter as a CHILD, so DETACHED_PROCESS is
# defeated one hop down (the child gets a fresh VISIBLE console the operator can
# accidentally close — the night-2 window-close incident class). The boot must ride
# the GUI-subsystem pythonw sibling, and must NEVER use CREATE_NO_WINDOW — a HIDDEN
# console crashed Textual on 2026-07-06 ("Driver must be in application mode").

_CREATE_NO_WINDOW = 0x08000000
_DETACHED_PROCESS = 0x00000008


def test_boot_launcher_detached_uses_pythonw_sibling(tmp_path, monkeypatch):
    import subprocess as sp
    import sys

    py = tmp_path / "python.exe"
    py.write_text("")
    pyw = tmp_path / "pythonw.exe"
    pyw.write_text("")
    captured = {}

    def fake_popen(cmd, **kw):
        captured["cmd"] = cmd
        captured["kw"] = kw

    monkeypatch.setattr(sys, "executable", str(py))
    monkeypatch.setattr(sp, "Popen", fake_popen)
    bat.boot_launcher_detached(tmp_path, tmp_path / "logs" / "boot.log")
    assert captured["cmd"] == [str(pyw), "-m", "launcher"]
    flags = captured["kw"]["creationflags"]
    assert flags & _DETACHED_PROCESS
    # 2026-07-06 incident pin: NEVER CREATE_NO_WINDOW on a python-launcher spawn.
    assert flags & _CREATE_NO_WINDOW == 0


def test_boot_launcher_detached_falls_back_without_pythonw(tmp_path, monkeypatch):
    # No pythonw sibling -> sys.executable unchanged (never a broken boot).
    import subprocess as sp
    import sys

    py = tmp_path / "python.exe"
    py.write_text("")
    captured = {}
    monkeypatch.setattr(sys, "executable", str(py))
    monkeypatch.setattr(sp, "Popen", lambda cmd, **kw: captured.update(cmd=cmd, kw=kw))
    bat.boot_launcher_detached(tmp_path, tmp_path / "logs" / "boot.log")
    assert captured["cmd"] == [str(py), "-m", "launcher"]
    assert captured["kw"]["creationflags"] & _CREATE_NO_WINDOW == 0


# ===========================================================================
# #863 Option A — the teardown barrier: run_teardown_barrier (pure policy) +
# build_real_teardown_ops (the live wiring) + boot_launcher_detached integration.
# ===========================================================================
#
# run_teardown_barrier is pure over an injected TeardownBarrierOps (the AoReensurer /
# ProbeOps DI pattern) -- alive -> terminate -> dead -> port-free, and the never-frees
# -> fail-closed path, all driven here with fake callables: no socket, no process, no
# GPU. build_real_teardown_ops is thin wiring, checked by IDENTITY (the real functions,
# never a reimplementation) -- instance_lock's and procspawn's own suites already cover
# behavior. The two tests above (tmp_path, no lock file) already prove the barrier's
# no-holder short-circuit never touches a real port -- load-bearing on a box that may
# have a REAL AO listening on the production port while this suite runs.


def _teardown_ops(*, holder_pid, live, frees_after_polls: float = 0):
    """A fast, effect-free TeardownBarrierOps for policy tests (mirrors _reensurer /
    probe's _ops helper) -- no real socket/process. The port reads OCCUPIED for the
    first *frees_after_polls* polls, then quiet; pass float('inf') to model "never
    frees" (the fail-closed path)."""
    calls = {"terminate": [], "sleeps": [], "polls": 0}

    def _terminate(pid):
        calls["terminate"].append(pid)
        return [pid]

    def _port_occupied():
        occupied = calls["polls"] < frees_after_polls
        calls["polls"] += 1
        return occupied

    ops = bat.TeardownBarrierOps(
        read_holder_pid=lambda: holder_pid,
        is_live_launcher=lambda pid: live,
        terminate=_terminate,
        port_occupied=_port_occupied,
        sleep=lambda s: calls["sleeps"].append(s),
        log=lambda *_: None,
    )
    return ops, calls


def test_teardown_barrier_noop_when_no_lock_holder():
    # A fresh certs/ dir (no lock file) -- the common preflight case -- must never
    # probe the port at all (the module docstring's short-circuit: this is what keeps
    # an isolated repo_root, e.g. THIS test's, from ever waiting on an unrelated
    # process holding the same port number elsewhere on the box).
    ops, calls = _teardown_ops(holder_pid=None, live=False)
    bat.run_teardown_barrier(ops, port=5001)
    assert calls["terminate"] == []
    assert calls["polls"] == 0


def test_teardown_barrier_noop_when_holder_is_not_a_live_launcher():
    # A stale/recycled pid -- the SAME "not our launcher" outcome the instance lock
    # itself already treats as reclaimable, never a peer to act on.
    ops, calls = _teardown_ops(holder_pid=4242, live=False)
    bat.run_teardown_barrier(ops, port=5001)
    assert calls["terminate"] == []
    assert calls["polls"] == 0


def test_teardown_barrier_kills_live_holder_and_proceeds_once_port_frees():
    # alive -> terminate -> dead -> port-free (the ADR's worked example, #863's own
    # PID 3128 shape): the port reads occupied for two polls, then quiet.
    ops, calls = _teardown_ops(holder_pid=3128, live=True, frees_after_polls=2)
    bat.run_teardown_barrier(ops, port=5001, port_free_timeout_s=10.0, poll_s=0.01)
    assert calls["terminate"] == [3128]
    assert len(calls["sleeps"]) == 2
    assert all(s == 0.01 for s in calls["sleeps"])


def test_teardown_barrier_kills_and_proceeds_immediately_when_port_already_quiet():
    # The kill was fast enough that the port is already free on the FIRST check --
    # never sleeps (no wasted wall-clock on the common case).
    ops, calls = _teardown_ops(holder_pid=3128, live=True, frees_after_polls=0)
    bat.run_teardown_barrier(ops, port=5001, port_free_timeout_s=10.0, poll_s=0.01)
    assert calls["terminate"] == [3128]
    assert calls["sleeps"] == []


def test_teardown_barrier_fail_closed_when_port_never_frees():
    # The never-frees path: the kill WAS attempted (a wedged process that somehow
    # survived the tree-kill, or something else re-bound the port) but the barrier
    # REFUSES to proceed -- fail-closed, naming the pid and port.
    ops, calls = _teardown_ops(holder_pid=3128, live=True, frees_after_polls=float("inf"))
    with pytest.raises(bat.TeardownBarrierError, match=r"3128.*:5001"):
        bat.run_teardown_barrier(ops, port=5001, port_free_timeout_s=0.05, poll_s=0.01)
    assert calls["terminate"] == [3128]  # the kill WAS attempted; only the wait failed


def test_teardown_barrier_zero_timeout_still_checks_once_before_failing():
    # A degenerate bound (0s) must still perform the FINAL check -- never raise on a
    # port that is ALREADY quiet just because the poll loop body never ran once.
    ops, calls = _teardown_ops(holder_pid=3128, live=True, frees_after_polls=0)
    bat.run_teardown_barrier(ops, port=5001, port_free_timeout_s=0.0, poll_s=0.01)
    assert calls["terminate"] == [3128]
    assert calls["sleeps"] == []


# ---------------------------------------------------------------------------
# build_real_teardown_ops -- the live wiring is composed from EXISTING primitives,
# never a reimplementation. Identity-checked (``is``); instance_lock's and
# procspawn's own suites already cover the checks' behavior.
# ---------------------------------------------------------------------------


def test_build_real_teardown_ops_wires_the_blessed_primitives(tmp_path):
    from launcher.instance_lock import _is_live_launcher
    from shared.procspawn import terminate_process_tree

    ops = bat.build_real_teardown_ops(tmp_path, 5099, log=lambda *_: None)
    assert ops.is_live_launcher is _is_live_launcher
    assert ops.terminate is terminate_process_tree


def test_build_real_teardown_ops_port_occupied_calls_ao_socket_ready(monkeypatch):
    seen = {}

    def _fake_ready(p, **kw):
        seen["port"] = p
        return True

    monkeypatch.setattr(bat, "ao_socket_ready", _fake_ready)
    ops = bat.build_real_teardown_ops(Path("."), 5099, log=lambda *_: None)
    assert ops.port_occupied() is True
    assert seen["port"] == 5099


def test_build_real_teardown_ops_reads_the_repo_scoped_lock(tmp_path):
    from launcher.instance_lock import lock_path_for_repo

    lock = lock_path_for_repo(tmp_path)
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("4242", encoding="utf-8")
    ops = bat.build_real_teardown_ops(tmp_path, 5099, log=lambda *_: None)
    assert ops.read_holder_pid() == 4242


def test_build_real_teardown_ops_absent_lock_reads_as_no_holder(tmp_path):
    # No certs/launcher.lock at all -- the normal fresh-checkout / fresh-battery-night
    # state -- must read as "no holder", never raise.
    ops = bat.build_real_teardown_ops(tmp_path, 5099, log=lambda *_: None)
    assert ops.read_holder_pid() is None


def test_build_real_teardown_ops_never_treats_its_own_pid_as_a_peer(tmp_path):
    # Defense-in-depth mirroring acquire_instance_lock's own holder != me guard.
    # boot_launcher_detached never runs INSIDE a launcher process, so this is
    # unreachable in production -- but never treat our OWN pid as a peer to kill.
    import os as _os
    from launcher.instance_lock import lock_path_for_repo

    lock = lock_path_for_repo(tmp_path)
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(str(_os.getpid()), encoding="utf-8")
    ops = bat.build_real_teardown_ops(tmp_path, 5099, log=lambda *_: None)
    assert ops.read_holder_pid() is None


# ---------------------------------------------------------------------------
# boot_launcher_detached integration: the barrier runs BEFORE the replacement is
# spawned, and a fail-closed barrier PREVENTS the spawn entirely.
# ---------------------------------------------------------------------------


def test_boot_launcher_detached_runs_teardown_barrier_before_popen(tmp_path, monkeypatch):
    import subprocess as sp

    order: list[str] = []
    monkeypatch.setattr(
        bat, "run_teardown_barrier",
        lambda ops, *, port, **kw: order.append(f"barrier:{port}"),
    )
    monkeypatch.setattr(sp, "Popen", lambda *a, **k: order.append("popen"))
    bat.boot_launcher_detached(tmp_path, tmp_path / "logs" / "boot.log", port=5099)
    assert order == ["barrier:5099", "popen"]


def test_boot_launcher_detached_defaults_to_the_production_ao_port(tmp_path, monkeypatch):
    import subprocess as sp

    seen = {}
    monkeypatch.setattr(
        bat, "run_teardown_barrier",
        lambda ops, *, port, **kw: seen.setdefault("port", port),
    )
    monkeypatch.setattr(sp, "Popen", lambda *a, **k: None)
    bat.boot_launcher_detached(tmp_path, tmp_path / "logs" / "boot.log")
    assert seen["port"] == bat._AO_PORT == 5001


def test_boot_launcher_detached_never_boots_when_barrier_fails_closed(tmp_path, monkeypatch):
    # A barrier that cannot prove the port is free must PREVENT the boot entirely.
    # Every current caller (AoReensurer.ensure / probe._real_restore) already wraps
    # boot_launcher_detached in a broad except Exception, so this propagates as an
    # honest failure -- the job/probe STALLs rather than racing a port collision.
    import subprocess as sp

    popped = {"called": False}

    def _boom(ops, *, port, **kw):
        raise bat.TeardownBarrierError("port never freed")

    monkeypatch.setattr(bat, "run_teardown_barrier", _boom)
    monkeypatch.setattr(sp, "Popen", lambda *a, **k: popped.__setitem__("called", True))
    with pytest.raises(bat.TeardownBarrierError):
        bat.boot_launcher_detached(tmp_path, tmp_path / "logs" / "boot.log")
    assert popped["called"] is False


def test_ao_reensurer_real_boot_threads_port_and_log_into_boot_launcher_detached(tmp_path, monkeypatch):
    # AoReensurer.real's boot lambda must pass ITS OWN port (not the module default)
    # so the barrier checks the SAME port readiness is being probed against.
    seen = {}

    def _fake_boot_launcher_detached(repo_root, log_path, *, port, log):
        seen["port"] = port
        seen["log"] = log

    monkeypatch.setattr(bat, "boot_launcher_detached", _fake_boot_launcher_detached)
    r = bat.AoReensurer.real(port=6161, repo_root=tmp_path, reboot_log_dir=tmp_path,
                             log=lambda *_: None)
    r.boot()
    assert seen["port"] == 6161
    assert callable(seen["log"])


# ---------------------------------------------------------------------------
# #744 certificate consumption (2026-07-08 ceremony close): an instrument
# nobody reads does not exist (lesson 46) — the battery now READS the
# advisory guest-oracle.json into scorecard evidence + the agreement tally.
# ---------------------------------------------------------------------------


def test_guest_agreement_truth_table():
    from tools.dispatch_harness.battery import guest_agreement

    assert guest_agreement("passed", None) == "no-certificate"
    assert guest_agreement("passed", {"status": "not-run", "reason": "x"}) == "guest-not-run"
    assert guest_agreement("passed", {"status": "passed"}) == "agree"
    assert guest_agreement("failed", {"status": "failed"}) == "agree"
    assert guest_agreement("passed", {"status": "failed"}) == "DIVERGENCE"
    assert guest_agreement("failed", {"status": "passed"}) == "DIVERGENCE"
    # A host that never graded (unknown/not-run) can never register agreement.
    assert guest_agreement("unknown", {"status": "passed"}) != "agree"
    assert guest_agreement("", {"status": "not-run", "reason": "r"}) == "guest-not-run"


def test_read_guest_oracle_certificate_fail_soft(tmp_path):
    from tools.dispatch_harness.battery import read_guest_oracle_certificate

    # absent -> None
    assert read_guest_oracle_certificate(tmp_path, "R1") is None
    run_dir = tmp_path / "R1"
    run_dir.mkdir()
    # unreadable -> None (evidence, never a gate)
    (run_dir / "guest-oracle.json").write_text("{not json", encoding="utf-8")
    assert read_guest_oracle_certificate(tmp_path, "R1") is None
    # present -> the dict
    (run_dir / "guest-oracle.json").write_text(
        '{"status": "passed", "reason": ""}', encoding="utf-8")
    cert = read_guest_oracle_certificate(tmp_path, "R1")
    assert cert == {"status": "passed", "reason": ""}


def test_battery_summary_carries_the_agreement_tally():
    from dataclasses import replace as dc_replace

    from tools.dispatch_harness.battery import BatterySummary
    from tools.dispatch_harness.scorecard import Scorecard

    def sc(job, agreement):
        base = Scorecard(job_id=job, verdict="PARKED-HONEST", attribution="BUILD",
                         evidence={"guest_agreement": agreement})
        return base

    summary = BatterySummary(out_dir="x", dry_run=True)
    summary.scorecards.extend([
        sc("B1", "agree"), sc("B2", "agree"), sc("B3", "DIVERGENCE"),
        sc("B4", "no-certificate"),
    ])
    tally = summary.to_dict()["guest_oracle_agreement"]
    assert tally["agree"] == 2
    assert tally["DIVERGENCE"] == 1
    assert tally["no-certificate"] == 1
    assert tally["guest-not-run"] == 0


def test_battery_summary_segments_green_rate_over_plan_graph_eligible():
    """#789 measurement fairness: the GREEN-rate denominator is plan-graph-eligible
    jobs ONLY. A flat-queue job (structurally non-GREEN by under-decomposition) is
    reported SEPARATELY, not counted against the coder — and no verdict is altered.

    The night-20260709 shape: B2 GREEN (plan-graph), B4/B6/B7 PARKED (plan-graph),
    B1/B5 PARKED (flat). Raw = 1/6; the honest coder rate = 1/4 plan-graph-eligible."""
    from tools.dispatch_harness.battery import BatterySummary
    from tools.dispatch_harness.scorecard import Scorecard

    def sc(job, verdict, mode, attribution=""):
        return Scorecard(job_id=job, verdict=verdict, attribution=attribution,
                         evidence={"mode": mode} if mode else {})

    summary = BatterySummary(out_dir="x", dry_run=True)
    summary.scorecards.extend([
        sc("B2", "GREEN", "plan-graph"),
        sc("B4", "PARKED-HONEST", "plan-graph", "BUILD"),
        sc("B6", "PARKED-HONEST", "plan-graph", "BUILD"),
        sc("B7", "PARKED-HONEST", "plan-graph", "BUILD"),
        sc("B1", "PARKED-HONEST", "flat", "BUILD"),
        sc("B5", "PARKED-HONEST", "flat", "BUILD"),
    ])
    assert summary.green == 1
    assert summary.plan_graph_eligible == 4
    assert summary.flat_queue == 2
    assert summary.mode_unknown == 0
    rel = summary.to_dict()["reliability"]
    assert rel["green_over_eligible"] == "1/4"   # the honest coder rate
    assert rel["green_over_total"] == "1/6"      # the raw rate, still shown
    assert rel["flat_queue"] == 2
    # The render surfaces the honest denominator + the flat count, hiding neither.
    text = summary.render()
    assert "GREEN 1/4 plan-graph-eligible" in text
    assert "flat-queue=2" in text


def test_battery_summary_mode_unknown_bucket_and_no_eligible_jobs():
    """A synthesized STALLED/HARNESS card (no mode) is mode-unknown — neither eligible
    nor flat — and a run with zero eligible jobs reports 'g/0' without dividing."""
    from tools.dispatch_harness.battery import BatterySummary
    from tools.dispatch_harness.scorecard import Scorecard

    summary = BatterySummary(out_dir="x", dry_run=True)
    summary.scorecards.extend([
        Scorecard(job_id="B1", verdict="STALLED", attribution="HARNESS",
                  evidence={"oracle_status": "unknown"}),           # no mode
        Scorecard(job_id="B5", verdict="PARKED-HONEST", attribution="BUILD",
                  evidence={"mode": "flat"}),
    ])
    assert summary.plan_graph_eligible == 0
    assert summary.flat_queue == 1
    assert summary.mode_unknown == 1
    rel = summary.to_dict()["reliability"]
    assert rel["green_over_eligible"] == "0/0"
    assert rel["mode_unknown"] == 1


def test_guest_oracle_evidence_is_a_valid_evidence_string(tmp_path):
    """2026-07-08 night-killer repro: the folded certificate was a DICT, the
    fail-closed writer refused it, and the runner died 4 min into the first
    fully-armed pass with zero scorecards. The fold must emit the evidence
    contract (string, one line, capped) for EVERY certificate shape."""
    from tools.dispatch_harness.battery import guest_oracle_evidence

    # the exact certificate that killed night-20260708-230002 (B1, flat-queue)
    cert = {"schema": "guest-oracle/v1", "advisory": True, "status": "not-run",
            "reason": "flat-queue-mode", "host_status": "not-run",
            "divergence": False}
    assert guest_oracle_evidence(cert) == "not-run: flat-queue-mode"
    assert guest_oracle_evidence(None) == "no-certificate"
    assert guest_oracle_evidence({"status": "passed"}) == "passed"
    assert guest_oracle_evidence({}) == "unknown"
    # hostile shapes flatten to one capped line
    ugly = guest_oracle_evidence(
        {"status": "failed", "reason": "a\nb\r\nc" + "x" * 1000})
    assert "\n" not in ugly and "\r" not in ugly and len(ugly) <= 300
    # and the fail-closed writer ACCEPTS the folded card
    folded = Scorecard(
        job_id="B1", verdict="PARKED-HONEST", attribution="BUILD",
        evidence={"oracle_status": "unknown",
                  "guest_oracle": guest_oracle_evidence(cert),
                  "guest_agreement": "guest-not-run"})
    sc.write_scorecard(folded, tmp_path / "b1.json")  # must not raise
    back = sc.read_scorecard(tmp_path / "b1.json")
    assert back.evidence["guest_oracle"] == "not-run: flat-queue-mode"


async def test_invalid_composed_card_degrades_to_stalled_not_a_dead_runner(
        tmp_path, monkeypatch):
    """The other half of the 2026-07-08 fix: when the fail-closed writer refuses
    a composed card, the refusal stands (no invalid record lands) but the cost
    is THAT job — STALLED [HARNESS], fail-loud — never the whole night."""
    cards = bat.load_cards(_SPEC_DIR)
    b1 = cards["B1"]
    harness = bat.build_dry_run_harness([b1], session_id="test")
    poisoned = Scorecard(
        job_id="B1", verdict="GREEN",
        evidence={"oracle_status": "passed", "poison": {"a": 1}})
    monkeypatch.setattr(bat, "adopt_driver_scorecard", lambda *a, **k: poisoned)
    monkeypatch.setattr(bat, "synthesize_scorecard", lambda *a, **k: poisoned)
    summary = await bat.run_battery(
        harness, [b1], out_dir=tmp_path, dry_run=True, log=lambda *_: None)
    assert len(summary.scorecards) == 1
    card = summary.scorecards[0]
    assert card.verdict == "STALLED" and card.attribution == "HARNESS"
    assert "invalid composed scorecard" in card.notes
    # the degraded card (not the invalid one) landed on disk, valid
    written = sc.read_scorecard(tmp_path / "B1.scorecard.json")
    assert written.verdict == "STALLED"
    assert (tmp_path / "battery-summary.json").is_file()


# ---------------------------------------------------------------------------
# #740 B3 re-grain: the per-card run envelope (both bounds, byte-identical default)
# ---------------------------------------------------------------------------


def test_stage_card_run_budget_sets_both_bounds(tmp_path):
    from types import SimpleNamespace

    from shared.fleet.dispatch import FleetDispatchConfig
    from shared.fleet.swap_ops import read_pending_run_budget
    from tools.dispatch_harness.battery import _stage_card_run_budget

    cfg = FleetDispatchConfig(
        scripts_dir=tmp_path / "s", queue_path=tmp_path / "state" / "q.json",
        runs_dir=tmp_path / "state" / "runs", projects_dir=tmp_path / "p")
    harness = SimpleNamespace(config=cfg, overall_timeout_s=10800.0)
    logs = []

    # A per-card budget sets the monitor bound AND stages the driver budget file.
    _stage_card_run_budget(harness, 21600.0, 10800.0, logs.append, "B3")
    assert harness.overall_timeout_s == 21600.0
    assert read_pending_run_budget(cfg) == 21600.0  # (consumes it)

    # A default card (0) restores the base monitor AND clears the pending file.
    harness.overall_timeout_s = 21600.0  # pretend a prior B3 left it raised
    _stage_card_run_budget(harness, 0.0, 10800.0, logs.append, "B1")
    assert harness.overall_timeout_s == 10800.0
    assert read_pending_run_budget(cfg) is None


def test_b3_card_declares_the_six_hour_envelope():
    import json
    from pathlib import Path

    from tools.dispatch_harness.battery import validate_card

    root = Path(__file__).resolve().parents[2]
    b3 = json.loads((root / "evals" / "battery" / "B3.json").read_text(encoding="utf-8"))
    assert b3["run_budget_s"] == 21600
    assert validate_card(b3) == []  # the new field validates clean


def test_run_budget_field_is_validated():
    from tools.dispatch_harness.battery import validate_card

    import json
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    # Start from a REAL valid card so only the run_budget_s axis is under test.
    base = json.loads((root / "evals" / "battery" / "B1.json").read_text(encoding="utf-8"))
    base.pop("run_budget_s", None)
    assert validate_card({**base, "run_budget_s": 3600}) == []      # ok
    assert validate_card(base) == []                               # absent ok
    assert any("run_budget_s" in e
               for e in validate_card({**base, "run_budget_s": -1}))
    assert any("run_budget_s" in e
               for e in validate_card({**base, "run_budget_s": "6h"}))
