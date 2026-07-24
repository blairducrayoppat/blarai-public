"""
Eval Suite — Coordinator Deterministic Judgment (#846 C4 prep / #855)
======================================================================
The fixture-board coordinator eval suite ADR-039 §2.12.7 names: golden
synthetic Vikunja-board snapshots (tickets with states/labels/ages/
priorities, tri-state substrate conditions, pagination-shaped inputs) fed
through the coordinator's REAL deterministic classification / pull-order
code — never a reimplementation of it — producing expected classifications
and pull decisions. Re-runs at every model swap alongside the other suites
(the capability-contract enforcement of ADR-039 §2.11) and at every gate
run (evals are standing-gate-locked via tests/integration/test_eval_*).

Real entry points driven (mocks lie — ADR-039 §2.8 "gate as JUDGE"):

  service_class / test_class /       ``shared.fleet.coord_lifecycle`` — the C2
  test_origin_repo                   classes-of-service + #887 provenance rulers.
  board_transition                   ``resolve_board_transition`` — the forged-Done
                                     lock (Done REQUIRES oracle GREEN + merged).
  dor                                ``evaluate_dor`` — Definition of Ready incl.
                                     the #848 SG target ruler over a hermetic
                                     tmp workspace (real filesystem resolution).
  stall_detection / stall_dedup      ``detect_stalls`` (per-class aging outliers,
                                     pull_rank-ordered) + ``new_stall_signals``.
  flow_metrics / flow_partition      ``shared.fleet.flow_metrics`` — ages, cycle
                                     time, throughput, #887 headline/test split.
  board_read                         the REAL ``shared.fleet.vikunja_bridge`` read
                                     surface over an injected fixture Transport
                                     (the sanctioned seam): pagination loop past
                                     the server's ``maxitemsperpage`` clamp
                                     (ADR-039 §2.12.2) + tri-state OK/EMPTY/
                                     UNREACHABLE (§2.12.6).
  snapshot_tripwire                  ``shared.fleet.work_state.compose_work_state``
                                     (the real composer, fixture transport + tmp
                                     fleet substrate) → ``shared.coordinator.
                                     heartbeat_cycle.evaluate_quiet_queue_tripwire``.
  redispatch                         ``shared.fleet.coord_redispatch.
                                     stage_redispatch_proposals`` through a REAL
                                     born-encrypted in-memory ProposalStore —
                                     eligible/ineligible/refused/dedup decisions.
  execution_revalidation             ``revalidate_for_execution`` — the TOCTOU
                                     seam (ADR-039 §2.12.4), incl. a live
                                     world-changed-after-staging case.
  repo_id_normalization              ``shared.coordinator.heartbeat_cycle.
                                     normalize_trusted_repo_id`` — the CaMeL
                                     trusted-repo-id rule (§2.2 control 1).
  prose_guard                        ``shared.coordinator.prose_guard`` — the
                                     #946 verdict-integrity guard (echo +
                                     bidirectional claim screen) over drafted
                                     run summaries; first cases are the
                                     #855-measured failures.

NOT covered here (honest scope, per the C4-prep brief):
  * The C4 class-then-age GLOBAL pull queue with starvation guard (ADR-039
    §2.12.8) — that composition is not yet built (#846); its inputs
    (``ServiceClass.pull_rank``, ages, the DoR gate) are what this suite pins
    today, so the pull policy lands onto already-locked primitives.
  * Anything model-dependent (14B proposal/digest drafting quality) — the
    #855 shadow-grading territory. THE SEAM: golden cases carry an optional
    ``mode`` field ("deterministic" default). A ``mode: "model"`` case is
    SKIPPED_HARDWARE in a default run (exactly the pa_classification
    convention); requesting ``--include-hardware`` while model-mode cases
    exist raises GoldenDataError until #855 lands its grading adapter —
    fail-closed, never silently passed. Zero model cases ship today.

ADR-038 frozen/dev split: every golden case carries an explicit
``card_class`` field; all cases in this suite are BORN-DEV (``"dev"``) per
the ratified growth policy (born-frozen-XOR-born-dev, never crossing;
add-only). An absent field would default to ``"frozen"`` (the ADR-038
fail-safe direction) — the integration test locks the field to explicit.

Golden case schema (evals/golden/coordinator.jsonl): ``kind`` selects the
surface; see ``_KIND_REQUIRED_FIELDS`` and the per-kind evaluators for the
exact fields. All timestamps in golden data are ISO 8601 with an explicit
offset (``Z``); every time-dependent evaluator takes ``now`` from the case,
never the wall clock — the whole suite is deterministic, no GPU, no model,
no network (the fixture Transport never opens a socket).
"""

from __future__ import annotations

import contextlib
import os
import re
import tempfile
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

from evals.loader import GoldenDataError, golden_path, load_golden
from evals.model_target import ModelTarget
from evals.types import CaseResult, CaseStatus, SuiteReport

SUITE_NAME: str = "coordinator"

_VALID_MODES: frozenset[str] = frozenset({"deterministic", "model"})
_VALID_CARD_CLASSES: frozenset[str] = frozenset({"dev", "frozen"})

#: Vikunja's server-side ``maxitemsperpage`` default, mirrored by the fixture
#: server so the bridge's pagination loop is exercised against the SAME clamp
#: the live server applies (ADR-039 §2.12.2 — a larger per_page request is
#: silently clamped; correctness must come from looping short pages).
_SERVER_MAX_PER_PAGE: int = 50

#: Fixed evaluation instant for evaluators that need a clock but whose cases
#: carry no ``now`` (e.g. redispatch staging timestamps) — any fixed tz-aware
#: instant keeps the run deterministic; verdicts never depend on its value.
_FIXED_NOW: datetime = datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Shared fixture plumbing
# ---------------------------------------------------------------------------


def _parse_case_now(case: Mapping[str, Any]) -> datetime:
    """The case's ``now`` as a tz-AWARE datetime (GoldenDataError if absent,
    malformed, or naive — a naive eval clock would silently shift verdicts
    with the host timezone, which is a harness defect, not a case fail)."""
    raw = case.get("now")
    if not isinstance(raw, str) or not raw.strip():
        raise GoldenDataError(f"case {case.get('id')}: missing 'now' timestamp")
    text = raw.strip()
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise GoldenDataError(
            f"case {case.get('id')}: malformed 'now' {raw!r} — {exc}"
        ) from exc
    if parsed.tzinfo is None:
        raise GoldenDataError(
            f"case {case.get('id')}: 'now' {raw!r} must carry an explicit offset"
        )
    return parsed.astimezone(timezone.utc)


@contextlib.contextmanager
def _hermetic_vikunja_env() -> Iterator[None]:
    """Pin the bridge's credential env vars to loopback fixtures for the
    duration of a transport-driven case, restoring the caller's values after.

    The bridge resolves ``VIKUNJA_URL``/``USER``/``PASS`` from the process
    env (with a ``.env`` fallback); a host whose env points elsewhere must
    not change an eval verdict — hermetic, exactly like the governance
    suite's verifier snapshot/restore idiom. No socket is ever opened either
    way (the transport is injected), but the loopback pin runs BEFORE the
    transport, so the URL must be loopback for the read to proceed at all."""
    keys = ("VIKUNJA_URL", "VIKUNJA_USER", "VIKUNJA_PASS")
    saved = {k: os.environ.get(k) for k in keys}
    os.environ["VIKUNJA_URL"] = "http://localhost:3456"
    os.environ["VIKUNJA_USER"] = "eval-fixture"
    os.environ["VIKUNJA_PASS"] = "eval-fixture"
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _server_tasks(server: Mapping[str, Any]) -> "list[dict[str, Any]]":
    """Materialize a fixture server's task list (literal or generated)."""
    spec = server.get("tasks", [])
    if isinstance(spec, Mapping) and "generate" in spec:
        gen = dict(spec["generate"])
        count = int(gen["count"])
        done_every = int(gen.get("done_every", 0))
        bucket_id = gen.get("bucket_id")
        generated: list[dict[str, Any]] = []
        for i in range(1, count + 1):
            done = bool(done_every and i % done_every == 0)
            task: dict[str, Any] = {
                "id": i,
                "title": f"task-{i}",
                "done": done,
                "created": "2026-06-30T12:00:00Z",
                "labels": None,
            }
            if done:
                task["done_at"] = "2026-07-01T00:00:00Z"
            if bucket_id is not None:
                task["bucket_id"] = int(bucket_id)
            generated.append(task)
        return generated
    return [dict(t) for t in spec]


def _fixture_transport(server: Mapping[str, Any]) -> Callable[..., "tuple[int, Any]"]:
    """A deterministic in-process Vikunja API fixture at the bridge's
    injected Transport seam — the synthetic BOARD each golden case declares.

    Serves the endpoints the C1 read surface consumes (login, paginated
    tasks, views, buckets), honoring the live server's ``maxitemsperpage``
    clamp (:data:`_SERVER_MAX_PER_PAGE`) so a >50-task fixture board is only
    read completely by a correctly-looping client. Failure injection:

      * ``login: "fail"``       — HTTP 401 on login (auth failure).
      * ``raise_on: ["tasks"]`` — the transport raises ``OSError`` for that
        endpoint (network-level failure).
      * ``http_error_on: {"tasks": 500}`` — HTTP error status for an endpoint.
      * ``views: []``           — a project with no Kanban view.

    ``tasks`` is either a literal list or a declarative
    ``{"generate": {"count": N, "done_every": k, "bucket_id": b}}`` spec —
    the generator exists so a >``maxitemsperpage`` board (the pagination
    fixture class) stays a one-line golden case; generated tasks are
    id-sequential and fully deterministic."""
    tasks = _server_tasks(server)
    views_spec = server.get("views", "kanban")
    if views_spec == "kanban":
        views: list[dict[str, Any]] = [{"id": 1, "view_kind": "kanban"}]
    else:
        views = [dict(v) for v in views_spec]
    buckets: list[dict[str, Any]] = [dict(b) for b in server.get("buckets", [])]
    login_ok = str(server.get("login", "ok")) == "ok"
    raise_on = frozenset(str(x) for x in server.get("raise_on", []))
    http_error_on: dict[str, int] = {
        str(k): int(v) for k, v in dict(server.get("http_error_on", {})).items()
    }

    def _leg(name: str) -> "int | None":
        if name in raise_on:
            raise OSError(f"fixture server: {name} endpoint unreachable")
        return http_error_on.get(name)

    def transport(
        method: str,
        url: str,
        body: "Mapping[str, Any] | None",
        headers: Mapping[str, str],
        timeout_s: float,
    ) -> "tuple[int, Any]":
        parsed = urllib.parse.urlparse(url)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        if path.endswith("/api/v1/login"):
            error = _leg("login")
            if error is not None:
                return error, None
            if not login_ok:
                return 401, None
            return 200, {"token": "eval-fixture-token"}
        if re.fullmatch(r".*/api/v1/projects/\d+/tasks", path):
            error = _leg("tasks")
            if error is not None:
                return error, None
            page = int(query.get("page", ["1"])[0])
            requested = int(query.get("per_page", [str(_SERVER_MAX_PER_PAGE)])[0])
            per_page = min(requested, _SERVER_MAX_PER_PAGE)  # the live clamp
            start = (page - 1) * per_page
            return 200, tasks[start : start + per_page]
        if re.fullmatch(r".*/api/v1/projects/\d+/views", path):
            error = _leg("views")
            if error is not None:
                return error, None
            return 200, views
        if re.fullmatch(r".*/api/v1/projects/\d+/views/\d+/buckets", path):
            error = _leg("buckets")
            if error is not None:
                return error, None
            return 200, buckets
        return 404, None

    return transport


@contextlib.contextmanager
def _sg_topology(
    *,
    repo_id: "str | None" = None,
    repo_kind: str = "workspace",
) -> Iterator["tuple[Path, Any]"]:
    """A hermetic self-governance topology: a tmp governed repo root + a tmp
    projects dir, optionally containing one workspace repo.

    ``repo_kind`` shapes the repo dir for the case under evaluation:
      * ``"workspace"``         — a plain, allowed workspace repo dir.
      * ``"governed_identity"`` — the repo dir carries the governed core's
        identity markers (a renamed-clone stand-in), so the REAL layer-3
        content-identity check (`shared.coordinator.governed_core`) refuses
        it — the eval creates the condition; the ruler does the judging.

    Yields ``(projects_dir, roots)``. Everything lives under a
    TemporaryDirectory so no case ever touches real state."""
    from shared.coordinator.config import (
        GOVERNED_CORE_IDENTITY_FILESETS,
        GovernedCoreRoots,
    )

    with tempfile.TemporaryDirectory(prefix="coord-eval-") as tmp:
        root = Path(tmp)
        governed = root / "governed-repo"
        governed.mkdir()
        projects = root / "projects"
        projects.mkdir()
        if repo_id is not None and _is_plain_component(repo_id):
            repo_dir = projects / repo_id
            repo_dir.mkdir(parents=True, exist_ok=True)
            if repo_kind == "governed_identity":
                _stamp_governed_identity(repo_dir, GOVERNED_CORE_IDENTITY_FILESETS)
        yield projects, GovernedCoreRoots(repo_root=governed)


def _is_plain_component(candidate: str) -> bool:
    return bool(candidate) and not any(sep in candidate for sep in ("/", "\\", ":"))


def _stamp_governed_identity(
    repo_dir: Path, filesets: Sequence[Sequence[str]]
) -> None:
    """Create ONE complete governed-core identity fileset inside *repo_dir*
    (the smallest one), turning it into a renamed-clone stand-in the REAL
    content-identity layer must refuse."""
    smallest = min(filesets, key=len)
    for rel in smallest:
        target = repo_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("governed-core identity marker (eval fixture)\n", encoding="utf-8")


def _round(value: "float | None", digits: int = 3) -> "float | None":
    return None if value is None else round(float(value), digits)


def _fragments_present(fragments: Sequence[str], haystack: Sequence[str]) -> bool:
    """True iff every fragment appears as a substring of at least one entry."""
    return all(any(frag in entry for entry in haystack) for frag in fragments)


# ---------------------------------------------------------------------------
# Per-kind evaluators — each returns (expected_repr, actual_repr, ok)
# ---------------------------------------------------------------------------


def _eval_service_class(case: Mapping[str, Any]) -> "tuple[Any, Any, bool]":
    from shared.fleet import coord_lifecycle as cl

    expected = str(case["expected_class"])
    actual = cl.classify_service_class(dict(case["task"])).value
    return expected, actual, actual == expected


def _eval_test_class(case: Mapping[str, Any]) -> "tuple[Any, Any, bool]":
    from shared.fleet import coord_lifecycle as cl

    expected = bool(case["expected_test"])
    actual = cl.is_test_class(dict(case["task"]))
    return expected, actual, actual is expected


def _eval_test_origin_repo(case: Mapping[str, Any]) -> "tuple[Any, Any, bool]":
    from shared.fleet import coord_lifecycle as cl

    expected = bool(case["expected_test_origin"])
    actual = cl.is_test_origin_repo(case.get("repo_id"))
    return expected, actual, actual is expected


def _eval_board_transition(case: Mapping[str, Any]) -> "tuple[Any, Any, bool]":
    from shared.fleet import coord_lifecycle as cl

    facts = dict(case["facts"])
    transition = cl.resolve_board_transition(
        dispatch_started=bool(facts.get("dispatch_started", False)),
        oracle_passed=bool(facts.get("oracle_passed", False)),
        merged=bool(facts.get("merged", False)),
        parked=bool(facts.get("parked", False)),
    )
    expected = case["expected"]  # null | {"to_bucket": ...}
    actual = None if transition is None else {"to_bucket": transition.to_bucket}
    return expected, actual, actual == expected


def _eval_dor(case: Mapping[str, Any]) -> "tuple[Any, Any, bool]":
    from shared.fleet import coord_lifecycle as cl

    target_repo_id = case.get("target_repo_id")
    repo_kind = str(case.get("repo_kind", "workspace"))
    provide_ruler_context = bool(case.get("provide_ruler_context", True))
    expected: dict[str, Any] = dict(case["expected"])

    with _sg_topology(
        repo_id=target_repo_id if isinstance(target_repo_id, str) else None,
        repo_kind=repo_kind,
    ) as (projects, roots):
        result = cl.evaluate_dor(
            dict(case["task"]),
            target_repo_id=target_repo_id,
            projects_dir=projects if provide_ruler_context else None,
            roots=roots if provide_ruler_context else None,
            has_open_blocker=bool(case.get("has_open_blocker", False)),
        )

    fragments = [str(f) for f in expected.get("reason_contains", [])]
    actual = {
        "ready": result.ready,
        "reason_count": len(result.reasons),
        "reasons_matched": _fragments_present(fragments, result.reasons),
    }
    expected_repr = {
        "ready": bool(expected["ready"]),
        "reason_count": int(expected.get("reason_count", 0)),
        "reasons_matched": True,
    }
    ok = actual == expected_repr
    if not ok:
        actual["reasons"] = list(result.reasons)  # mismatch forensics
    return expected_repr, actual, ok


def _eval_stall_detection(case: Mapping[str, Any]) -> "tuple[Any, Any, bool]":
    from shared.fleet import coord_lifecycle as cl

    now = _parse_case_now(case)
    signals = cl.detect_stalls(
        [dict(t) for t in case["tasks"]],
        now=now,
    )
    expected = [
        {
            "task_id": int(s["task_id"]),
            "class": str(s["class"]),
            "fingerprint": f"{s['class']}:{int(s['task_id'])}",
        }
        for s in case["expected_stalls"]
    ]
    actual = [
        {
            "task_id": s.task_id,
            "class": s.service_class.value,
            "fingerprint": s.fingerprint,
        }
        for s in signals
    ]
    return expected, actual, actual == expected


def _eval_stall_dedup(case: Mapping[str, Any]) -> "tuple[Any, Any, bool]":
    from shared.fleet import coord_lifecycle as cl

    signals = [
        cl.StallSignal(
            task_id=int(s["task_id"]),
            title=str(s.get("title", "")),
            service_class=cl.ServiceClass(str(s["class"])),
            age_seconds=float(s.get("age_seconds", 0.0)),
            fingerprint=cl.stall_fingerprint(
                cl.ServiceClass(str(s["class"])), int(s["task_id"])
            ),
        )
        for s in case["signals"]
    ]
    fresh = cl.new_stall_signals(signals, frozenset(str(f) for f in case["seen"]))
    expected = [int(t) for t in case["expected_new_task_ids"]]
    actual = [s.task_id for s in fresh]
    return expected, actual, actual == expected


def _eval_flow_metrics(case: Mapping[str, Any]) -> "tuple[Any, Any, bool]":
    from shared.fleet import flow_metrics as fm

    now = _parse_case_now(case)
    tasks = [dict(t) for t in case["tasks"]]
    open_tasks = [t for t in tasks if not bool(t.get("done", False))]
    window = timedelta(days=float(case.get("window_days", 7)))
    metrics = fm.compute_flow_metrics(
        open_tasks,
        tasks,
        now=now,
        window_start=now - window,
        window_end=now,
    )
    expected = dict(case["expected"])
    actual = {
        "open_count": metrics.open_count,
        "oldest_age_s": _round(metrics.oldest_age_seconds),
        "mean_age_s": _round(metrics.mean_age_seconds),
        "throughput": metrics.throughput_count,
        "cycle_times_count": len(metrics.cycle_times_seconds),
        "mean_cycle_time_s": _round(metrics.mean_cycle_time_seconds),
        "outlier_ids": [a.task_id for a in metrics.aging_outliers],
        "skipped_unparseable": metrics.skipped_unparseable,
    }
    expected_repr = {
        "open_count": int(expected["open_count"]),
        "oldest_age_s": _round(expected.get("oldest_age_s")),
        "mean_age_s": _round(expected.get("mean_age_s")),
        "throughput": int(expected.get("throughput", 0)),
        "cycle_times_count": int(expected.get("cycle_times_count", 0)),
        "mean_cycle_time_s": _round(expected.get("mean_cycle_time_s")),
        "outlier_ids": [int(i) for i in expected.get("outlier_ids", [])],
        "skipped_unparseable": int(expected.get("skipped_unparseable", 0)),
    }
    return expected_repr, actual, actual == expected_repr


def _eval_flow_partition(case: Mapping[str, Any]) -> "tuple[Any, Any, bool]":
    from shared.fleet import coord_lifecycle as cl
    from shared.fleet import flow_metrics as fm

    now = _parse_case_now(case)
    tasks = [dict(t) for t in case["tasks"]]
    open_tasks = [t for t in tasks if not bool(t.get("done", False))]
    window = timedelta(days=float(case.get("window_days", 7)))
    common: dict[str, Any] = dict(
        now=now, window_start=now - window, window_end=now
    )
    partitioned = fm.compute_partitioned_flow_metrics(
        open_tasks, tasks, is_test_class=cl.is_test_class, **common
    )
    whole_board = fm.compute_flow_metrics(open_tasks, tasks, **common)
    expected = dict(case["expected"])
    actual = {
        "headline_open": partitioned.headline.open_count,
        "test_open": partitioned.test_class.open_count,
        "headline_equals_whole_board": partitioned.headline == whole_board,
    }
    expected_repr = {
        "headline_open": int(expected["headline_open"]),
        "test_open": int(expected["test_open"]),
        "headline_equals_whole_board": bool(
            expected.get("headline_equals_whole_board", False)
        ),
    }
    return expected_repr, actual, actual == expected_repr


def _eval_board_read(case: Mapping[str, Any]) -> "tuple[Any, Any, bool]":
    from shared.fleet import vikunja_bridge as vb

    op = str(case["op"])
    project_id = int(case.get("project_id", 7))
    expected = dict(case["expected"])
    transport = _fixture_transport(dict(case["server"]))

    with _hermetic_vikunja_env():
        if op == "list_all_tasks":
            result = vb.list_all_tasks(project_id, transport=transport)
        elif op == "list_open_tasks":
            result = vb.list_open_tasks(project_id, transport=transport)
        elif op == "project_read_summary":
            result = vb.project_read_summary(project_id, transport=transport)
        elif op == "board_state":
            result = vb.board_state(project_id, transport=transport)
        elif op == "health_check":
            result = vb.health_check(transport=transport)
        else:
            raise GoldenDataError(f"case {case.get('id')}: unknown op {op!r}")

    actual: dict[str, Any] = {"status": result.status.value}
    expected_repr: dict[str, Any] = {"status": str(expected["status"])}
    if "count" in expected:
        expected_repr["count"] = int(expected["count"])
        actual["count"] = len(result.items)
    if "summary" in expected:
        expected_repr["summary"] = dict(expected["summary"])
        first = dict(result.items[0]) if result.items else {}
        actual["summary"] = {
            k: first.get(k) for k in expected_repr["summary"]
        }
    if "bucket_task_ids" in expected:
        expected_repr["bucket_task_ids"] = {
            str(k): [int(i) for i in v]
            for k, v in dict(expected["bucket_task_ids"]).items()
        }
        actual["bucket_task_ids"] = {
            str(b.get("title", "")): [
                int(t.get("id", 0)) for t in (b.get("tasks") or [])
            ]
            for b in result.items
        }
    if "error_contains" in expected:
        expected_repr["error_matched"] = True
        actual["error_matched"] = str(expected["error_contains"]) in result.error
        if not actual["error_matched"]:
            actual["error"] = result.error
    return expected_repr, actual, actual == expected_repr


def _eval_snapshot_tripwire(case: Mapping[str, Any]) -> "tuple[Any, Any, bool]":
    from shared.coordinator import heartbeat_cycle as hb
    from shared.fleet import work_state as ws
    from shared.fleet.dispatch import FleetDispatchConfig

    now = _parse_case_now(case)
    expected = dict(case["expected"])
    transport = _fixture_transport(dict(case["server"]))
    gated_ids = frozenset(int(i) for i in case.get("resource_gated_ids", []))
    evaluator_mode = str(case.get("eligibility_evaluator", "none"))

    eligible_ready: "Callable[[Mapping[str, Any]], bool] | None"
    if evaluator_mode == "none":
        eligible_ready = None if not gated_ids else (
            lambda t: int(t.get("id", 0)) not in gated_ids
        )
    elif evaluator_mode == "raises":
        def eligible_ready(t: Mapping[str, Any]) -> bool:
            raise RuntimeError("fixture evaluator fault (UNKNOWN must stay gated)")
    else:
        raise GoldenDataError(
            f"case {case.get('id')}: unknown eligibility_evaluator {evaluator_mode!r}"
        )

    with tempfile.TemporaryDirectory(prefix="coord-eval-fleet-") as tmp:
        root = Path(tmp)
        runs_dir = root / "runs"
        runs_dir.mkdir()
        if bool(case.get("active_run", False)):
            # A run dir with NO SUMMARY.txt = a dispatch still in flight (the
            # real read yields EMPTY with (run_id, ()) — active WIP). The name
            # must be a MINTABLE run id (#953 anchored the resolver's shape to
            # what new_run_id() produces — the old "-ev" fixture suffix only
            # resolved via the pre-#953 prefix match).
            (runs_dir / "20260701-000000-bd").mkdir()
        config = FleetDispatchConfig(
            scripts_dir=root / "scripts",
            queue_path=root / "state" / "fleet-queue.json",
            runs_dir=runs_dir,
            projects_dir=root / "projects",
        )
        with _hermetic_vikunja_env():
            snapshot = ws.compose_work_state(
                fleet_config=config,
                coordinator_projects={"proj": int(case.get("project_id", 7))},
                now=now,
                vikunja_transport=transport,
            )
        result = hb.evaluate_quiet_queue_tripwire(
            snapshot,
            in_overnight_window=bool(case.get("in_overnight_window", False)),
            in_boot_grace=bool(case.get("in_boot_grace", False)),
            absence_active=bool(case.get("absence_active", False)),
            eligible_ready=eligible_ready,
        )

    fragments = [str(f) for f in expected.get("suppressed_contains", [])]
    actual = {
        "fired": result.fired,
        "ready_eligible_total": result.ready_eligible_total,
        "gated_inventory": result.gated_inventory,
        "suppressed_count": len(result.suppressed_reasons),
        "suppressed_matched": _fragments_present(
            fragments, result.suppressed_reasons
        ),
    }
    expected_repr = {
        "fired": bool(expected["fired"]),
        "ready_eligible_total": int(expected.get("ready_eligible_total", 0)),
        "gated_inventory": int(expected.get("gated_inventory", 0)),
        "suppressed_count": int(expected.get("suppressed_count", 0)),
        "suppressed_matched": True,
    }
    ok = actual == expected_repr
    if not ok:
        actual["suppressed_reasons"] = list(result.suppressed_reasons)
    return expected_repr, actual, ok


def _categorize_redispatch(result: Any) -> dict[str, "list[str]"]:
    """RedispatchCycleResult → sorted task names per decision category."""
    return {
        "staged": sorted(s.task for s in result.staged),
        "deduped": sorted(s.task for s in result.deduped),
        "already_decided": sorted(s.task for s in result.already_decided),
        "refused": sorted(s.task for s in result.refused),
        "ineligible": sorted(s.task for s in result.ineligible),
        "errors": sorted(s.task for s in result.errors),
    }


def _expected_redispatch(spec: Mapping[str, Any]) -> dict[str, "list[str]"]:
    return {
        category: sorted(str(t) for t in spec.get(category, []))
        for category in (
            "staged", "deduped", "already_decided", "refused", "ineligible", "errors",
        )
    }


def _eval_redispatch(case: Mapping[str, Any]) -> "tuple[Any, Any, bool]":
    from shared.coordinator.proposal_store import build_proposal_store
    from shared.fleet import coord_redispatch as cr
    from shared.fleet.dispatch import TaskOutcome

    outcomes = [
        TaskOutcome(
            task=str(o["task"]),
            outcome="processed",
            result=str(o["result"]),
            detail=str(o.get("detail", "")),
        )
        for o in case["outcomes"]
    ]
    repo_id = str(case["repo_id"])
    repo_kind = str(case.get("repo_kind", "workspace"))
    run_id = str(case.get("run_id", "RID-EVAL-1"))

    with _sg_topology(repo_id=repo_id, repo_kind=repo_kind) as (projects, roots):
        store = build_proposal_store(":memory:")
        try:
            first = cr.stage_redispatch_proposals(
                outcomes,
                run_id=run_id,
                repo_id=repo_id,
                projects_dir=projects,
                roots=roots,
                store=store,
                now=_FIXED_NOW,
            )
            actual: dict[str, Any] = {"first": _categorize_redispatch(first)}
            expected_repr: dict[str, Any] = {
                "first": _expected_redispatch(dict(case["expected"]))
            }
            if bool(case.get("repeat_cycle", False)):
                second = cr.stage_redispatch_proposals(
                    outcomes,
                    run_id=run_id,
                    repo_id=repo_id,
                    projects_dir=projects,
                    roots=roots,
                    store=store,
                    now=_FIXED_NOW,
                )
                actual["second"] = _categorize_redispatch(second)
                expected_repr["second"] = _expected_redispatch(
                    dict(case["expected_second"])
                )
        finally:
            store.close()
    return expected_repr, actual, actual == expected_repr


def _eval_execution_revalidation(case: Mapping[str, Any]) -> "tuple[Any, Any, bool]":
    from shared.coordinator.config import GOVERNED_CORE_IDENTITY_FILESETS
    from shared.coordinator.proposal_store import (
        ProposalLane,
        build_proposal_store,
        proposal_fingerprint,
    )
    from shared.fleet import coord_redispatch as cr
    from shared.fleet.dispatch import TaskOutcome

    scenario = str(case["scenario"])
    expected = dict(case["expected"])

    with _sg_topology(repo_id="myapp", repo_kind="workspace") as (projects, roots):
        store = build_proposal_store(":memory:")
        try:
            if scenario == "missing_repo_id":
                # A REAL stored proposal whose payload lacks the structured
                # repo_id — the fail-closed re-derivation branch.
                proposal = store.add_draft(
                    lane=ProposalLane.WORKSPACE,
                    proposal_class=cr.REDISPATCH_PROPOSAL_CLASS,
                    fingerprint=proposal_fingerprint(
                        proposal_class=cr.REDISPATCH_PROPOSAL_CLASS,
                        target="",
                        evidence_hash="eval-missing-repo-id",
                    ),
                    payload={"goal": "eval fixture without repo_id"},
                    now=_FIXED_NOW,
                )
            else:
                # Stage through the REAL cycle so the proposal is exactly what
                # production would revalidate.
                cycle = cr.stage_redispatch_proposals(
                    [TaskOutcome(task="t1", outcome="processed", result="PARKED", detail="")],
                    run_id="RID-EVAL-REVAL",
                    repo_id="myapp",
                    projects_dir=projects,
                    roots=roots,
                    store=store,
                    now=_FIXED_NOW,
                )
                if len(cycle.staged) != 1:
                    raise GoldenDataError(
                        f"case {case.get('id')}: staging fixture did not stage "
                        f"exactly one proposal ({cycle!r})"
                    )
                history = store.find_by_fingerprint(cycle.staged[0].fingerprint)
                proposal = history[-1]
                if scenario == "toctou_governed":
                    # The world changes AFTER staging: the workspace repo is
                    # replaced by a governed-core-identity tree. The REAL
                    # execution-time ruler must refuse.
                    _stamp_governed_identity(
                        projects / "myapp", GOVERNED_CORE_IDENTITY_FILESETS
                    )
                elif scenario != "valid":
                    raise GoldenDataError(
                        f"case {case.get('id')}: unknown scenario {scenario!r}"
                    )
            verdict = cr.revalidate_for_execution(
                proposal, roots=roots, projects_dir=projects
            )
        finally:
            store.close()

    fragments = [str(f) for f in expected.get("reason_contains", [])]
    actual = {
        "decision": verdict.decision.value,
        "phase": verdict.phase,
        "reason_matched": _fragments_present(fragments, [verdict.reason]),
    }
    expected_repr = {
        "decision": str(expected["decision"]),
        "phase": "EXECUTION",
        "reason_matched": True,
    }
    ok = actual == expected_repr
    if not ok:
        actual["reason"] = verdict.reason
    return expected_repr, actual, ok


def _eval_repo_id_normalization(case: Mapping[str, Any]) -> "tuple[Any, Any, bool]":
    from shared.coordinator.heartbeat_cycle import normalize_trusted_repo_id

    form = str(case["form"])
    name = case.get("name")
    expected = dict(case["expected"])

    with _sg_topology(
        repo_id=name if isinstance(name, str) and _is_plain_component(name) else None
    ) as (projects, _roots):
        repo: Any
        if form == "plain":
            repo = name
        elif form == "direct_child_path":
            repo = str(projects / str(name))
        elif form == "nested_path":
            repo = str(projects / str(name) / "nested")
        elif form == "blank":
            repo = "   "
        elif form == "non_string":
            repo = 12345
        else:
            raise GoldenDataError(f"case {case.get('id')}: unknown form {form!r}")
        repo_id, reason = normalize_trusted_repo_id(repo, projects_dir=projects)

    fragments = [str(f) for f in expected.get("reason_contains", [])]
    actual = {
        "id": repo_id,
        "reason_matched": _fragments_present(fragments, [reason]),
    }
    expected_repr = {
        "id": expected.get("id"),
        "reason_matched": True,
    }
    ok = actual == expected_repr
    if not ok:
        actual["reason"] = reason
    return expected_repr, actual, ok


def _eval_prose_guard(case: Mapping[str, Any]) -> "tuple[Any, Any, bool]":
    """#946: the verdict-integrity guard over drafted run summaries — the REAL
    ``ProseGuard`` (production construction, no toggles) against the run's
    deterministic truth. The first golden cases are the #855-measured failures
    verbatim-class; the lexicons are add-only and every addition lands here."""
    from shared.coordinator import prose_guard as pg

    run = dict(case["run"])
    truth = pg.RunTruth(
        run_id=str(run.get("run_id", "r")),
        oracle_passed=bool(run.get("oracle_passed", False)),
        merged=bool(run.get("merged", False)),
        parked=bool(run.get("parked", False)),
    )
    # #1067: the run's harvested (task, result) pairs are the ONLY vocabulary the
    # negated-failure carve-out accepts in a variable position. The field carries
    # PAIRS, not bare names: production derives merged and non-merged vocabulary
    # from the result, so a names-only fixture would represent a quantity the
    # shipped guard never sees, and the first golden listing a non-merged task
    # would pass here while the live guard refused it. A case that omits the
    # field exercises the EMPTY-vocabulary path, which is the fail-closed one.
    task_results = tuple(
        (str(row[0]), str(row[1]))
        for row in run.get("tasks", ())
        # isinstance, not len(): a 2-CHARACTER string also has len 2 and would
        # parse as a pair, silently turning a stray bare name into vocabulary.
        if isinstance(row, (list, tuple)) and len(row) == 2
    )
    decision = pg.ProseGuard().validate_run_summary(
        truth, str(case["text"]), task_results=task_results
    )
    expected = dict(case["expected"])  # {"accepted": bool, "action_prefix": str}
    actual = {"accepted": decision.accepted, "action": decision.action}
    ok = decision.accepted == bool(expected.get("accepted")) and (
        decision.action.startswith(str(expected.get("action_prefix", "")))
    )
    return expected, actual, ok


_KIND_EVALUATORS: dict[str, Callable[[Mapping[str, Any]], "tuple[Any, Any, bool]"]] = {
    "service_class": _eval_service_class,
    "test_class": _eval_test_class,
    "test_origin_repo": _eval_test_origin_repo,
    "board_transition": _eval_board_transition,
    "dor": _eval_dor,
    "stall_detection": _eval_stall_detection,
    "stall_dedup": _eval_stall_dedup,
    "flow_metrics": _eval_flow_metrics,
    "flow_partition": _eval_flow_partition,
    "board_read": _eval_board_read,
    "snapshot_tripwire": _eval_snapshot_tripwire,
    "redispatch": _eval_redispatch,
    "execution_revalidation": _eval_execution_revalidation,
    "repo_id_normalization": _eval_repo_id_normalization,
    "prose_guard": _eval_prose_guard,
}

_VALID_KINDS: frozenset[str] = frozenset(_KIND_EVALUATORS)

_KIND_REQUIRED_FIELDS: dict[str, "tuple[str, ...]"] = {
    "service_class": ("task", "expected_class"),
    "test_class": ("task", "expected_test"),
    "test_origin_repo": ("expected_test_origin",),
    "board_transition": ("facts", "expected"),
    "dor": ("task", "expected"),
    "stall_detection": ("now", "tasks", "expected_stalls"),
    "stall_dedup": ("signals", "seen", "expected_new_task_ids"),
    "flow_metrics": ("now", "tasks", "expected"),
    "flow_partition": ("now", "tasks", "expected"),
    "board_read": ("op", "server", "expected"),
    "snapshot_tripwire": ("now", "server", "expected"),
    "redispatch": ("repo_id", "outcomes", "expected"),
    "execution_revalidation": ("scenario", "expected"),
    "repo_id_normalization": ("form", "expected"),
    "prose_guard": ("run", "text", "expected"),
}


def _validate_case(case: Mapping[str, Any]) -> "str | None":
    kind = case.get("kind")
    if kind not in _VALID_KINDS:
        return f"invalid kind {kind!r} (must be one of {sorted(_VALID_KINDS)})"
    for required in _KIND_REQUIRED_FIELDS[str(kind)]:
        if required not in case:
            return f"kind {kind!r} requires field '{required}'"
    mode = case.get("mode", "deterministic")
    if mode not in _VALID_MODES:
        return f"invalid mode {mode!r} (must be one of {sorted(_VALID_MODES)})"
    card_class = case.get("card_class", "frozen")  # ADR-038 fail-safe default
    if card_class not in _VALID_CARD_CLASSES:
        return (
            f"invalid card_class {card_class!r} "
            f"(must be one of {sorted(_VALID_CARD_CLASSES)})"
        )
    if bool(case.get("repeat_cycle", False)) and "expected_second" not in case:
        return "repeat_cycle cases require 'expected_second'"
    return None


def run_suite(
    golden_file: "Path | None" = None,
    *,
    include_hardware: bool = False,
    model_target: ModelTarget | None = None,  # noqa: ARG001 — no model in this suite
) -> SuiteReport:
    """Run the coordinator deterministic-judgment suite (no model, no GPU,
    no network — every substrate is a fixture at a real injection seam).

    ``mode: "model"`` cases are the #855 seam: SKIPPED_HARDWARE in a default
    run; a run REQUESTING hardware while such cases exist is refused with
    GoldenDataError until the #855 shadow-grading adapter lands (fail-closed
    — a seam must never silently pass)."""
    path = golden_file or golden_path(SUITE_NAME)
    cases = load_golden(path)

    report = SuiteReport(suite=SUITE_NAME)
    for case in cases:
        problem = _validate_case(case)
        if problem is not None:
            raise GoldenDataError(f"{path.name} case {case.get('id')}: {problem}")
        case_id = str(case["id"])
        description = str(case.get("description", ""))
        if str(case.get("mode", "deterministic")) == "model":
            if include_hardware:
                raise GoldenDataError(
                    f"{path.name} case {case_id}: model-graded coordinator cases "
                    "are the #855 shadow-grading seam — no grading adapter exists "
                    "yet, so a hardware run cannot evaluate them (fail-closed)."
                )
            report.results.append(
                CaseResult(
                    case_id=case_id,
                    status=CaseStatus.SKIPPED_HARDWARE,
                    description=description,
                    detail=(
                        "model-graded coordinator case — joins at #855 "
                        "(shadow-mode measured graduation); skipped without "
                        "hardware by the pa_classification convention"
                    ),
                )
            )
            continue
        evaluator = _KIND_EVALUATORS[str(case["kind"])]
        try:
            expected, actual, ok = evaluator(case)
        except GoldenDataError:
            raise  # malformed golden data is a harness error, never a case fail
        except Exception as exc:  # noqa: BLE001 — harness scoring must not abort the run
            report.results.append(
                CaseResult(
                    case_id=case_id,
                    status=CaseStatus.ERROR,
                    description=description,
                    detail=f"harness error: {exc}",
                )
            )
            continue
        report.results.append(
            CaseResult(
                case_id=case_id,
                status=CaseStatus.PASS if ok else CaseStatus.FAIL,
                description=description,
                expected=expected,
                actual=actual,
                detail=(
                    ""
                    if ok
                    else f"expected {expected!r}, got {actual!r} ({case['kind']})"
                ),
            )
        )
    return report
