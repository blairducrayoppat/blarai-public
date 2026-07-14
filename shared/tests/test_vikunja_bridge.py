"""Locks for the dispatch→Vikunja bridge (#749).

No real network: a fake in-memory Vikunja is injected as the HTTP transport (the
same seam the real urllib transport plugs into). Covers the non-negotiable
properties — the loopback pin, the knob-off dormancy, create-idempotence, the
FALSE-DONE-shaped close gate (GREEN + oracle-passed ONLY), Vikunja's full-object
update semantics, fail-soft on transport errors, the 2 s per-call cap — plus the
battery wiring lock (a completed job posts exactly ONE outcome comment).
"""

from __future__ import annotations

import asyncio
import re
import urllib.parse
from dataclasses import replace as dc_replace
from types import SimpleNamespace
from typing import Any, Mapping

import pytest

from shared.fleet import vikunja_bridge as vb


# ---------------------------------------------------------------------------
# A fake in-memory Vikunja that speaks the bridge's transport contract.
# ---------------------------------------------------------------------------


class FakeVikunja:
    """An injected transport standing in for a loopback Vikunja.

    ``(method, url, body, headers, timeout) -> (status, parsed_json)`` — the exact
    seam ``tools/dispatch_harness/vikunja_http.urlopen_transport`` implements.
    Records every call so the tests can assert counts (no heartbeats) and the
    per-call timeout.
    """

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, str, dict | None]] = []
        self.timeouts: list[float] = []
        self.comments: dict[int, list[str]] = {}
        self._tasks: dict[int, dict] = {}
        self._project_tasks: dict[int, list[int]] = {}
        self._next_id = 1000
        # C1 read surface (#843) fixtures — views + buckets, keyed the same
        # way the real Vikunja hierarchy is (project -> views; (project, view)
        # -> buckets).
        self._views: dict[int, list[dict]] = {}
        self._buckets: dict[tuple[int, int], list[dict]] = {}
        # Setup-migration fixtures (ADR-039 §2.12.11) — labels are GLOBAL.
        self._labels: list[dict] = []
        self._next_label_id = 5000
        self._next_bucket_id = 6000
        # Every paginated-listing GET, recorded as (project_id, page,
        # per_page) — kept SEPARATELY from ``self.calls`` because that log
        # strips query strings (page/per_page are query params, not body),
        # so it cannot answer "how many pages were requested".
        self.page_requests: list[tuple[int, int, int]] = []

    # -- seam ---------------------------------------------------------------

    def __call__(
        self,
        method: str,
        url: str,
        body: Mapping[str, Any] | None,
        headers: Mapping[str, str],
        timeout: float,
    ) -> tuple[int, Any]:
        parsed = urllib.parse.urlparse(url)
        path = parsed.path.split("/api/v1", 1)[-1]
        self.calls.append((method, path, dict(body) if body else None))
        self.timeouts.append(timeout)
        if self.fail:
            raise OSError("simulated vikunja transport failure")
        return self._route(method, path, parsed, body or {})

    def _route(self, method: str, path: str, parsed, body: Mapping[str, Any]):
        if method == "POST" and path == "/login":
            return 200, {"token": "faketoken"}

        m = re.match(r"^/projects/(\d+)/tasks$", path)
        if m:
            pid = int(m.group(1))
            if method == "PUT":  # create
                return 200, self._create(pid, body)
            if method == "GET":  # list/search/paginate
                qs = urllib.parse.parse_qs(parsed.query)
                if "s" in qs:  # the #749 write-side idempotency search
                    needle = qs.get("s", [""])[0]
                    out = [
                        self._tasks[t]
                        for t in self._project_tasks.get(pid, [])
                        if needle in self._tasks[t]["title"]
                    ]
                    return 200, out
                # C1 read surface (#843): paginated listing — the SAME
                # maxitemsperpage-clamp semantics the real server has (a page
                # always caps at per_page regardless of what's asked; a
                # missing page/per_page defaults exactly like a bare GET).
                page = int(qs.get("page", ["1"])[0])
                per_page = int(qs.get("per_page", ["50"])[0])
                self.page_requests.append((pid, page, per_page))
                all_ids = self._project_tasks.get(pid, [])
                start = (page - 1) * per_page
                end = start + per_page
                out = [self._tasks[t] for t in all_ids[start:end]]
                return 200, out

        m = re.match(r"^/projects/(\d+)/views$", path)
        if m and method == "GET":
            pid = int(m.group(1))
            return 200, list(self._views.get(pid, []))

        m = re.match(r"^/projects/(\d+)/views/(\d+)/buckets$", path)
        if m:
            pid, vid = int(m.group(1)), int(m.group(2))
            if method == "GET":
                return 200, list(self._buckets.get((pid, vid), []))
            if method == "PUT":  # create (setup migration, ADR-039 §2.12.11)
                self._next_bucket_id += 1
                bucket = {
                    "id": self._next_bucket_id,
                    "title": str(body.get("title", "")),
                    "position": 0,
                    "limit": 0,
                }
                self._buckets.setdefault((pid, vid), []).append(bucket)
                return 200, dict(bucket)

        m = re.match(r"^/projects/(\d+)/views/(\d+)/buckets/(\d+)/tasks$", path)
        if m and method == "POST":  # C2 board move (#844) — "update a task bucket"
            pid, vid, bid = int(m.group(1)), int(m.group(2)), int(m.group(3))
            tid = int(body.get("task_id", 0) or 0)
            if tid in self._tasks:
                self._tasks[tid]["bucket_id"] = bid
            return 200, {"task_id": tid, "bucket_id": bid, "project_view_id": vid}

        if path == "/labels":
            if method == "GET":
                return 200, list(self._labels)
            if method == "PUT":  # create (setup migration, ADR-039 §2.12.11)
                self._next_label_id += 1
                label = {
                    "id": self._next_label_id,
                    "title": str(body.get("title", "")),
                    "hex_color": str(body.get("hex_color", "")),
                }
                self._labels.append(label)
                return 200, dict(label)

        m = re.match(r"^/tasks/(\d+)$", path)
        if m:
            tid = int(m.group(1))
            if method == "GET":
                return 200, dict(self._tasks.get(tid, {}))
            if method == "POST":  # full-object update
                self._tasks.setdefault(tid, {"id": tid}).update(dict(body))
                return 200, dict(self._tasks[tid])

        m = re.match(r"^/tasks/(\d+)/comments$", path)
        if m and method == "PUT":
            tid = int(m.group(1))
            self.comments.setdefault(tid, []).append(str(body.get("comment", "")))
            self._next_id += 1
            return 200, {"id": self._next_id, "comment": body.get("comment", "")}

        return 404, None

    # -- helpers ------------------------------------------------------------

    def _create(self, pid: int, body: Mapping[str, Any]) -> dict:
        self._next_id += 1
        tid = self._next_id
        task = {
            "id": tid,
            "title": str(body.get("title", "")),
            "description": str(body.get("description", "")),
            "project_id": pid,
            "priority": 0,
            "done": False,
        }
        self._tasks[tid] = task
        self._project_tasks.setdefault(pid, []).append(tid)
        return dict(task)

    def seed_task(self, pid: int, **fields: Any) -> int:
        self._next_id += 1
        tid = self._next_id
        task = {"id": tid, "title": "", "description": "", "priority": 0, "done": False}
        task.update(fields)
        task["id"] = tid
        self._tasks[tid] = task
        self._project_tasks.setdefault(pid, []).append(tid)
        return tid

    def seed_view(self, pid: int, view_id: int, *, title: str, kind: str) -> None:
        """C1 read surface (#843): register a view (List/Kanban/Table/...)."""
        self._views.setdefault(pid, []).append(
            {"id": view_id, "title": title, "view_kind": kind}
        )

    def seed_bucket(
        self, pid: int, view_id: int, bucket_id: int, *, title: str, **fields: Any
    ) -> None:
        """C1 read surface (#843): register a bucket on (project, view)."""
        bucket = {"id": bucket_id, "title": title, "position": 0, "limit": 0}
        bucket.update(fields)
        self._buckets.setdefault((pid, view_id), []).append(bucket)

    def seed_label(self, label_id: int, *, title: str, hex_color: str = "") -> None:
        """Setup-migration fixture (ADR-039 §2.12.11): register a global label."""
        self._labels.append({"id": label_id, "title": title, "hex_color": hex_color})

    def task_list_page_requests(self, pid: int) -> list[int]:
        """The list of ``page`` numbers requested for *pid* via the
        paginated-listing form (not the ``s=`` search form) — the
        pagination-loop's actual page sequence, for exact-count assertions."""
        return [page for (p, page, _pp) in self.page_requests if p == pid]

    @property
    def creates(self) -> int:
        return sum(
            1
            for (mth, p, _b) in self.calls
            if mth == "PUT" and re.match(r"^/projects/\d+/tasks$", p)
        )

    def comment_count(self, tid: int | None = None) -> int:
        if tid is None:
            return sum(len(v) for v in self.comments.values())
        return len(self.comments.get(tid, []))

    def is_done(self, tid: int) -> bool:
        return bool(self._tasks.get(tid, {}).get("done"))

    def last_body(self, method: str, path_re: str) -> dict | None:
        rx = re.compile(path_re)
        for mth, p, b in reversed(self.calls):
            if mth == method and rx.match(p):
                return b
        return None


def _cfg(*, on: bool = True, project_id: int = 7) -> SimpleNamespace:
    return SimpleNamespace(vikunja_bridge=on, vikunja_bridge_project_id=project_id)


@pytest.fixture(autouse=True)
def _loopback_env(monkeypatch):
    """Pin the resolved Vikunja URL to loopback for every test (hermetic — the
    box's real VIKUNJA_URL, set for the MCP subprocess, must not leak in). The
    loopback-refusal test overrides this with a non-local URL."""
    monkeypatch.setenv("VIKUNJA_URL", "http://localhost:3456")
    monkeypatch.setenv("VIKUNJA_USER", "blarai")
    monkeypatch.setenv("VIKUNJA_PASS", "test-pass")


# ---------------------------------------------------------------------------
# Loopback pin
# ---------------------------------------------------------------------------


def test_is_loopback_accepts_local_refuses_remote():
    assert vb.is_loopback("localhost")
    assert vb.is_loopback("127.0.0.1")
    assert vb.is_loopback("127.5.6.7")
    assert vb.is_loopback("::1")
    assert not vb.is_loopback("evil.example.com")
    assert not vb.is_loopback("10.0.0.5")
    assert not vb.is_loopback("")
    assert not vb.is_loopback(None)


def test_assert_loopback_raises_on_remote():
    vb.assert_loopback("http://localhost:3456")
    vb.assert_loopback("http://127.0.0.1:3456")
    with pytest.raises(ValueError, match="non-loopback"):
        vb.assert_loopback("http://evil.example.com:3456")


def test_loopback_pin_refuses_non_local_url_before_any_call(monkeypatch):
    # A misconfigured non-local VIKUNJA_URL must be refused BEFORE the transport is
    # ever touched — the pin fires in the client constructor, fail-soft to None.
    monkeypatch.setenv("VIKUNJA_URL", "http://evil.example.com:3456")
    fake = FakeVikunja()
    result = vb.ensure_job_ticket(_cfg(), "RID-1", "a goal", "battery-x", transport=fake)
    assert result is None
    assert fake.calls == []  # the pin refused before any HTTP was attempted


# ---------------------------------------------------------------------------
# Knob-off dormancy
# ---------------------------------------------------------------------------


def test_knob_off_makes_zero_calls():
    fake = FakeVikunja()
    off = _cfg(on=False)
    assert vb.ensure_job_ticket(off, "RID", "g", "battery-x", transport=fake) is None
    assert vb.post_outcome(off, 1, {"verdict": "GREEN"}, transport=fake) is False
    assert vb.post_campaign_summary(off, 1, "report", transport=fake) is False
    assert fake.calls == []


def test_unset_project_id_refuses_even_when_enabled():
    fake = FakeVikunja()
    unset = _cfg(on=True, project_id=0)
    assert vb.ensure_job_ticket(unset, "RID", "g", "battery-x", transport=fake) is None
    assert fake.calls == []


# ---------------------------------------------------------------------------
# Create idempotence
# ---------------------------------------------------------------------------


def test_ensure_job_ticket_is_idempotent_by_run_id():
    fake = FakeVikunja()
    cfg = _cfg()
    first = vb.ensure_job_ticket(cfg, "RID-42", "build a calc", "battery-calc", transport=fake)
    assert first is not None
    second = vb.ensure_job_ticket(cfg, "RID-42", "build a calc", "battery-calc", transport=fake)
    assert second == first          # found the existing ticket
    assert fake.creates == 1        # created exactly once across both calls


def test_ticket_title_carries_the_run_id_marker():
    fake = FakeVikunja()
    tid = vb.ensure_job_ticket(_cfg(), "RID-99", "a goal", "battery-x", transport=fake)
    body = fake.last_body("PUT", r"^/projects/\d+/tasks$")
    assert body is not None
    assert body["title"].startswith("[fleet-job RID-99]")
    assert tid is not None


# ---------------------------------------------------------------------------
# The close gate (FALSE-DONE-shaped lock): GREEN + oracle passed ONLY
# ---------------------------------------------------------------------------


def _green(oracle: str) -> dict:
    return {"verdict": "GREEN", "attribution": "", "run_id": "RID",
            "evidence": {"oracle_status": oracle}}


def test_green_with_oracle_passed_closes_the_ticket():
    fake = FakeVikunja()
    tid = fake.seed_task(7, title="[fleet-job RID] x", description="d", priority=2)
    assert vb.post_outcome(_cfg(), tid, _green("passed"), transport=fake) is True
    assert fake.comment_count(tid) == 1     # commented
    assert fake.is_done(tid) is True        # AND closed


def test_parked_honest_comments_but_leaves_ticket_open():
    fake = FakeVikunja()
    tid = fake.seed_task(7, title="[fleet-job RID] x")
    sc = {"verdict": "PARKED-HONEST", "attribution": "BUILD", "run_id": "RID",
          "evidence": {"oracle_status": "failed"}}
    assert vb.post_outcome(_cfg(), tid, sc, transport=fake) is True
    assert fake.comment_count(tid) == 1
    assert fake.is_done(tid) is False       # stays OPEN — the operator's queue


def test_green_without_oracle_passed_does_not_close():
    # A GREEN verdict whose oracle did NOT pass (not-run / failed) must NOT close —
    # a ticket may never close without the oracle-green scorecard.
    for oracle in ("not-run", "failed", "unknown"):
        fake = FakeVikunja()
        tid = fake.seed_task(7, title="[fleet-job RID] x")
        assert vb.post_outcome(_cfg(), tid, _green(oracle), transport=fake) is True
        assert fake.comment_count(tid) == 1
        assert fake.is_done(tid) is False, f"oracle_status={oracle} must not close"


# ---------------------------------------------------------------------------
# Vikunja full-object update semantics
# ---------------------------------------------------------------------------


def test_close_uses_full_object_fetch_then_post():
    # The close path must FETCH the current task then POST the full object (title/
    # description/priority preserved) + done=True — Vikunja zeroes unspecified
    # fields on a bare POST.
    fake = FakeVikunja()
    tid = fake.seed_task(7, title="[fleet-job RID] keepme", description="keep this", priority=3)
    assert vb.post_outcome(_cfg(), tid, _green("passed"), transport=fake) is True

    methods_paths = [(m, p) for (m, p, _b) in fake.calls]
    get_idx = methods_paths.index(("GET", f"/tasks/{tid}"))
    post_idx = methods_paths.index(("POST", f"/tasks/{tid}"))
    assert get_idx < post_idx               # fetched BEFORE posting

    close_body = fake.last_body("POST", rf"^/tasks/{tid}$")
    assert close_body is not None
    assert close_body["done"] is True
    assert close_body["title"] == "[fleet-job RID] keepme"   # preserved
    assert close_body["description"] == "keep this"          # preserved
    assert close_body["priority"] == 3                       # preserved


# ---------------------------------------------------------------------------
# Fail-soft + timeout
# ---------------------------------------------------------------------------


def test_fail_soft_on_transport_exception_never_raises():
    fake = FakeVikunja(fail=True)
    cfg = _cfg()
    assert vb.ensure_job_ticket(cfg, "RID", "g", "battery-x", transport=fake) is None
    assert vb.post_outcome(cfg, 1, _green("passed"), transport=fake) is False
    assert vb.post_campaign_summary(cfg, 1, "report", transport=fake) is False
    # It DID attempt (fail happened at the transport), proving the swallow is real.
    assert fake.calls, "expected the transport to have been reached before failing"


def test_every_call_is_bounded_by_two_seconds():
    fake = FakeVikunja()
    vb.ensure_job_ticket(_cfg(), "RID", "g", "battery-x", transport=fake)
    assert fake.timeouts, "expected at least one bounded call"
    assert all(t == vb.CALL_TIMEOUT_S for t in fake.timeouts)
    assert vb.CALL_TIMEOUT_S == 2.0


# ---------------------------------------------------------------------------
# Campaign summary
# ---------------------------------------------------------------------------


def test_post_campaign_summary_comments_without_closing():
    fake = FakeVikunja()
    tid = fake.seed_task(7, title="battery campaign 2026-07-06")
    assert vb.post_campaign_summary(_cfg(), tid, "morning report: 8 jobs, 6 green", transport=fake) is True
    assert fake.comment_count(tid) == 1
    assert fake.is_done(tid) is False


# ---------------------------------------------------------------------------
# Battery wiring lock — knob ON + fake bridge -> exactly ONE outcome comment
# ---------------------------------------------------------------------------


def test_battery_completed_job_posts_exactly_one_outcome_comment(tmp_path, monkeypatch):
    from tools.dispatch_harness.battery import build_dry_run_harness, run_battery

    card = {
        "id": "B1",
        "repo": "battery-calc",
        "goal": "build a calculator",
        "rigs": [],
        "expected_outcome": {"oracle": {"expected": True}},
    }
    harness = build_dry_run_harness([card])
    # Enable the bridge on the harness's config (the battery reads harness.config).
    harness = dc_replace(
        harness,
        config=dc_replace(harness.config, vikunja_bridge=True, vikunja_bridge_project_id=7),
    )
    fake = FakeVikunja()
    monkeypatch.setattr(vb, "_default_transport", lambda: fake)

    summary = asyncio.run(
        run_battery(harness, [card], out_dir=tmp_path / "out", dry_run=True, log=lambda *_: None)
    )

    assert summary.scorecards[0].verdict == "GREEN"
    assert fake.creates == 1                 # exactly one durable ticket
    assert fake.comment_count() == 1         # exactly ONE outcome comment — no heartbeats
    # The harness's own post-adoption seam stayed OFF (report_outcomes_to_vikunja
    # defaults False), which is what keeps it to a single comment.
    assert harness.report_outcomes_to_vikunja is False


def test_battery_wiring_dormant_when_knob_off(tmp_path, monkeypatch):
    from tools.dispatch_harness.battery import build_dry_run_harness, run_battery

    card = {"id": "B1", "repo": "battery-calc", "goal": "build a calc", "rigs": [],
            "expected_outcome": {"oracle": {"expected": True}}}
    harness = build_dry_run_harness([card])  # config.vikunja_bridge defaults False
    fake = FakeVikunja()
    monkeypatch.setattr(vb, "_default_transport", lambda: fake)

    asyncio.run(
        run_battery(harness, [card], out_dir=tmp_path / "out", dry_run=True, log=lambda *_: None)
    )
    assert fake.calls == []  # knob off -> the battery posts nothing


# ---------------------------------------------------------------------------
# C1 read surface (#843, ADR-039 §2.10) — pagination-aware reads
# ---------------------------------------------------------------------------


def test_pagination_reads_more_than_one_page_exactly():
    """THE critical lock (ADR-039 §2.12.2): a >50-item board must read EXACT
    — not silently truncated to the server's maxitemsperpage clamp. 120
    items at the default page size (50) is 3 pages (50/50/20)."""
    fake = FakeVikunja()
    for i in range(120):
        fake.seed_task(7, title=f"task-{i}", done=False)
    result = vb.list_open_tasks(7, transport=fake)
    assert result.status == vb.ReadStatus.OK
    assert len(result.items) == 120
    assert fake.task_list_page_requests(7) == [1, 2, 3]


def test_pagination_stops_on_short_page_not_a_fixed_count():
    """A board with FEWER than one page must not over-fetch — the loop stops
    the instant a page comes back short, never guessing a fixed page count."""
    fake = FakeVikunja()
    for i in range(9):
        fake.seed_task(7, title=f"task-{i}", done=False)
    result = vb.list_open_tasks(7, transport=fake)
    assert len(result.items) == 9
    assert fake.task_list_page_requests(7) == [1]


def test_pagination_handles_an_exact_multiple_of_page_size():
    """Boundary case: EXACTLY 50 items (== per_page) still terminates
    correctly — page 1 comes back full (50, not < per_page, so the loop
    continues), page 2 comes back EMPTY, which is what actually stops it."""
    fake = FakeVikunja()
    for i in range(50):
        fake.seed_task(7, title=f"task-{i}", done=False)
    result = vb.list_open_tasks(7, transport=fake)
    assert len(result.items) == 50
    assert fake.task_list_page_requests(7) == [1, 2]


def test_list_open_tasks_excludes_done():
    fake = FakeVikunja()
    fake.seed_task(7, title="open-1", done=False)
    fake.seed_task(7, title="done-1", done=True)
    fake.seed_task(7, title="open-2", done=False)
    result = vb.list_open_tasks(7, transport=fake)
    assert result.status == vb.ReadStatus.OK
    assert {t["title"] for t in result.items} == {"open-1", "open-2"}


def test_list_open_tasks_preserves_labels_and_due_date():
    """Classes-of-service inputs (labels, due_date) must survive the read
    untouched — C1 reads them but does not interpret them; a later phase
    computes classes of service over these exact fields."""
    fake = FakeVikunja()
    fake.seed_task(
        7, title="t1", done=False,
        labels=[{"id": 1, "title": "Expedite"}], due_date="2026-08-01T00:00:00Z",
    )
    result = vb.list_open_tasks(7, transport=fake)
    assert result.items[0]["labels"] == [{"id": 1, "title": "Expedite"}]
    assert result.items[0]["due_date"] == "2026-08-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Tri-state discipline (ADR-039 §2.12.6 / §2.14.4)
# ---------------------------------------------------------------------------


def test_tri_state_ok_when_open_tasks_present():
    fake = FakeVikunja()
    fake.seed_task(7, title="t1", done=False)
    result = vb.list_open_tasks(7, transport=fake)
    assert result.status == vb.ReadStatus.OK
    assert result.ok is True


def test_tri_state_empty_when_board_has_zero_open_tasks():
    fake = FakeVikunja()
    fake.seed_task(7, title="all-done", done=True)  # a task exists, but none OPEN
    result = vb.list_open_tasks(7, transport=fake)
    assert result.status == vb.ReadStatus.EMPTY
    assert result.ok is True  # EMPTY is still a SUCCESSFUL read
    assert result.items == ()


def test_tri_state_unreachable_on_transport_failure():
    fake = FakeVikunja(fail=True)
    result = vb.list_open_tasks(7, transport=fake)
    assert result.status == vb.ReadStatus.UNREACHABLE
    assert result.ok is False
    assert result.error  # a fail-soft reason is recorded, never silently blank


def test_unreachable_never_renders_as_empty():
    """THE lock (ADR-039 §2.12.6 / task brief): a fail-soft-swallowed
    transport error must be tri-state DISTINGUISHABLE from a genuinely empty
    board — never the same status, never conflatable by a caller checking
    ``items`` truthiness alone. A dead Vikunja must not look like a finished
    backlog."""
    fake_down = FakeVikunja(fail=True)
    fake_empty = FakeVikunja()
    fake_empty.seed_task(7, title="done-only", done=True)

    down = vb.list_open_tasks(7, transport=fake_down)
    empty = vb.list_open_tasks(7, transport=fake_empty)

    assert down.status != empty.status
    assert down.status == vb.ReadStatus.UNREACHABLE
    assert empty.status == vb.ReadStatus.EMPTY
    # Both have an empty items tuple — status is the ONLY thing that tells
    # them apart, so a caller MUST branch on status, never on `items` alone.
    assert down.items == () and empty.items == ()
    # The .ok convenience must not blur them either: UNREACHABLE is the one
    # and only False case; EMPTY (a successful, if uneventful, read) is True.
    assert down.ok is False
    assert empty.ok is True


def test_loopback_pin_applies_to_reads_too(monkeypatch):
    monkeypatch.setenv("VIKUNJA_URL", "http://evil.example.com:3456")
    fake = FakeVikunja()
    result = vb.list_open_tasks(7, transport=fake)
    assert result.status == vb.ReadStatus.UNREACHABLE
    assert fake.calls == []  # refused before any HTTP was attempted — same pin as writes


def test_reads_are_bounded_by_two_seconds():
    fake = FakeVikunja()
    fake.seed_task(7, title="t1", done=False)
    vb.list_open_tasks(7, transport=fake)
    assert fake.timeouts
    assert all(t == vb.CALL_TIMEOUT_S for t in fake.timeouts)


# ---------------------------------------------------------------------------
# health_check — substrate liveness
# ---------------------------------------------------------------------------


def test_health_check_ok_when_login_succeeds():
    fake = FakeVikunja()
    result = vb.health_check(transport=fake)
    assert result.status == vb.ReadStatus.OK
    assert result.items[0]["reachable"] is True


def test_health_check_unreachable_on_failure():
    fake = FakeVikunja(fail=True)
    result = vb.health_check(transport=fake)
    assert result.status == vb.ReadStatus.UNREACHABLE
    assert result.ok is False


def test_health_check_never_returns_empty():
    """Reachability is binary — EMPTY would be a meaningless third state
    here, so only OK/UNREACHABLE may ever come back."""
    for fake in (FakeVikunja(), FakeVikunja(fail=True)):
        assert vb.health_check(transport=fake).status != vb.ReadStatus.EMPTY


# ---------------------------------------------------------------------------
# list_all_tasks — the flow-metrics feed (open AND done, unfiltered)
# ---------------------------------------------------------------------------


def test_list_all_tasks_includes_done_and_open():
    fake = FakeVikunja()
    fake.seed_task(7, title="open-1", done=False)
    fake.seed_task(7, title="done-1", done=True)
    result = vb.list_all_tasks(7, transport=fake)
    assert result.status == vb.ReadStatus.OK
    assert {t["title"] for t in result.items} == {"open-1", "done-1"}


def test_list_all_tasks_paginates_exact():
    fake = FakeVikunja()
    for i in range(75):
        fake.seed_task(7, title=f"t-{i}", done=(i % 2 == 0))
    result = vb.list_all_tasks(7, transport=fake)
    assert len(result.items) == 75
    assert fake.task_list_page_requests(7) == [1, 2]


def test_list_all_tasks_unreachable_on_failure():
    fake = FakeVikunja(fail=True)
    result = vb.list_all_tasks(7, transport=fake)
    assert result.status == vb.ReadStatus.UNREACHABLE


# ---------------------------------------------------------------------------
# project_read_summary
# ---------------------------------------------------------------------------


def test_project_read_summary_counts_and_labels():
    fake = FakeVikunja()
    fake.seed_task(7, title="a", done=False, labels=[{"id": 1, "title": "Expedite"}])
    fake.seed_task(7, title="b", done=False, labels=[{"id": 1, "title": "Expedite"}])
    fake.seed_task(7, title="c", done=False, labels=[{"id": 2, "title": "Standard"}])
    fake.seed_task(7, title="d", done=True)
    result = vb.project_read_summary(7, transport=fake)
    assert result.status == vb.ReadStatus.OK
    summary = result.items[0]
    assert summary["project_id"] == 7
    assert summary["total"] == 4
    assert summary["open"] == 3
    assert summary["done"] == 1
    assert summary["labels"] == {"Expedite": 2, "Standard": 1}


def test_project_read_summary_empty_when_project_has_zero_tasks():
    fake = FakeVikunja()
    result = vb.project_read_summary(7, transport=fake)
    assert result.status == vb.ReadStatus.EMPTY


def test_project_read_summary_unreachable_on_failure():
    fake = FakeVikunja(fail=True)
    result = vb.project_read_summary(7, transport=fake)
    assert result.status == vb.ReadStatus.UNREACHABLE


# ---------------------------------------------------------------------------
# Views + kind resolution (ADR-039 §2.12.11 — never a hardcoded view id)
# ---------------------------------------------------------------------------


def test_find_view_by_kind_resolves_case_insensitively():
    views = [
        {"id": 1, "title": "List", "view_kind": "list"},
        {"id": 2, "title": "Board", "view_kind": "KANBAN"},
    ]
    assert vb.find_view_by_kind(views, "kanban") == 2
    assert vb.find_view_by_kind(views, "Kanban") == 2


def test_find_view_by_kind_returns_none_when_absent():
    views = [{"id": 1, "title": "List", "view_kind": "list"}]
    assert vb.find_view_by_kind(views, "kanban") is None


def test_list_views_reads_the_fixture():
    fake = FakeVikunja()
    fake.seed_view(7, 1, title="List", kind="list")
    fake.seed_view(7, 2, title="Board", kind="kanban")
    result = vb.list_views(7, transport=fake)
    assert result.status == vb.ReadStatus.OK
    assert {v["view_kind"] for v in result.items} == {"list", "kanban"}


# ---------------------------------------------------------------------------
# board_state — bucket + open-task grouping
# ---------------------------------------------------------------------------


def test_board_state_groups_open_tasks_by_bucket():
    fake = FakeVikunja()
    fake.seed_view(7, 2, title="Board", kind="kanban")
    fake.seed_bucket(7, 2, 10, title="Backlog", position=1)
    fake.seed_bucket(7, 2, 11, title="Ready", position=2)
    fake.seed_task(7, title="t1", done=False, bucket_id=10)
    fake.seed_task(7, title="t2", done=False, bucket_id=10)
    fake.seed_task(7, title="t3", done=False, bucket_id=11)
    fake.seed_task(7, title="t4-done", done=True, bucket_id=11)  # done -> excluded

    result = vb.board_state(7, transport=fake)
    assert result.status == vb.ReadStatus.OK
    by_id = {b["id"]: b for b in result.items}
    assert {t["title"] for t in by_id[10]["tasks"]} == {"t1", "t2"}
    assert {t["title"] for t in by_id[11]["tasks"]} == {"t3"}


def test_board_state_bucket_with_no_open_tasks_still_appears():
    fake = FakeVikunja()
    fake.seed_view(7, 2, title="Board", kind="kanban")
    fake.seed_bucket(7, 2, 10, title="Done", position=3)
    result = vb.board_state(7, transport=fake)
    assert result.status == vb.ReadStatus.OK  # the bucket itself is present
    assert result.items[0]["tasks"] == []


def test_board_state_unreachable_when_no_kanban_view():
    fake = FakeVikunja()
    fake.seed_view(7, 1, title="List", kind="list")  # no kanban view exists
    result = vb.board_state(7, transport=fake)
    assert result.status == vb.ReadStatus.UNREACHABLE
    assert "kanban" in result.error.lower()


def test_board_state_empty_when_kanban_view_has_zero_buckets():
    fake = FakeVikunja()
    fake.seed_view(7, 2, title="Board", kind="kanban")
    result = vb.board_state(7, transport=fake)
    assert result.status == vb.ReadStatus.EMPTY


def test_list_buckets_without_the_open_task_enrichment():
    fake = FakeVikunja()
    fake.seed_bucket(7, 2, 10, title="Backlog")
    result = vb.list_buckets(7, 2, transport=fake)
    assert result.status == vb.ReadStatus.OK
    assert "tasks" not in result.items[0]  # the raw bucket, unlike board_state


# ---------------------------------------------------------------------------
# API-contract pin (ADR-039 §2.12.3) — recorded v2.3.0 response shapes
# ---------------------------------------------------------------------------
# These fixtures are hand-recorded examples of the live v2.3.0 endpoints'
# field names/types — not live-server calls. A future Vikunja upgrade that
# renames/reshapes a field these parsers depend on should be caught by
# reviewing THIS fixture at upgrade time, not discovered silently live.

_RECORDED_TASK_V2_3_0: dict = {
    "id": 42,
    "title": "Fix the thing",
    "description": "<p>details</p>",
    "done": False,
    "done_at": None,
    "due_date": "2026-08-01T00:00:00Z",
    "priority": 2,
    "labels": [{"id": 3, "title": "Expedite", "hex_color": "ff0000"}],
    "bucket_id": 11,
    "project_id": 7,
    "created": "2026-07-01T12:00:00Z",
    "updated": "2026-07-10T09:30:00Z",
}

_RECORDED_VIEW_V2_3_0: dict = {
    "id": 2,
    "title": "Kanban",
    "project_id": 7,
    "view_kind": "kanban",
    "position": 2,
}

_RECORDED_BUCKET_V2_3_0: dict = {
    "id": 11,
    "title": "Ready",
    "project_id": 7,
    "position": 2,
    "limit": 5,
    "is_done_bucket": False,
}


def test_task_list_contract_shape_v2_3_0():
    """Pin the exact field names list_open_tasks/project_read_summary/
    board_state depend on against a recorded v2.3.0 task shape."""
    fake = FakeVikunja()
    fake.seed_task(7, **_RECORDED_TASK_V2_3_0)
    result = vb.list_open_tasks(7, transport=fake)
    assert result.status == vb.ReadStatus.OK
    task = result.items[0]
    for field_name in ("id", "title", "done", "due_date", "priority", "labels", "bucket_id"):
        assert field_name in task, f"v2.3.0 task contract missing field: {field_name}"
    assert task["labels"][0]["title"] == "Expedite"


def test_views_contract_shape_v2_3_0():
    fake = FakeVikunja()
    fake._views.setdefault(7, []).append(dict(_RECORDED_VIEW_V2_3_0))
    result = vb.list_views(7, transport=fake)
    assert result.status == vb.ReadStatus.OK
    assert result.items[0]["view_kind"] == "kanban"
    assert vb.find_view_by_kind(result.items, "kanban") == 2


def test_buckets_contract_shape_v2_3_0():
    fake = FakeVikunja()
    fake._buckets.setdefault((7, 2), []).append(dict(_RECORDED_BUCKET_V2_3_0))
    result = vb.list_buckets(7, 2, transport=fake)
    assert result.status == vb.ReadStatus.OK
    bucket = result.items[0]
    for field_name in ("id", "title", "position", "limit"):
        assert field_name in bucket, f"v2.3.0 bucket contract missing field: {field_name}"


# ---------------------------------------------------------------------------
# Setup-migration primitives (ADR-039 §2.12.11) — OPERATOR-RUN ONLY
# ---------------------------------------------------------------------------


def test_list_labels_reads_the_fixture():
    fake = FakeVikunja()
    fake.seed_label(1, title="Expedite", hex_color="ff0000")
    fake.seed_label(2, title="Standard", hex_color="00ff00")
    result = vb.list_labels(transport=fake)
    assert result.status == vb.ReadStatus.OK
    assert {l["title"] for l in result.items} == {"Expedite", "Standard"}


def test_ensure_label_creates_when_missing():
    fake = FakeVikunja()
    label_id = vb.ensure_label("Expedite", "ff0000", transport=fake)
    assert label_id is not None
    assert fake._labels[0]["title"] == "Expedite"
    assert fake._labels[0]["hex_color"] == "ff0000"


def test_ensure_label_is_idempotent_by_name():
    fake = FakeVikunja()
    first = vb.ensure_label("Expedite", "ff0000", transport=fake)
    second = vb.ensure_label("Expedite", "ff0000", transport=fake)
    assert first == second
    assert len(fake._labels) == 1  # created exactly once


def test_ensure_label_finds_existing_without_creating():
    fake = FakeVikunja()
    fake.seed_label(42, title="Expedite", hex_color="ff0000")
    label_id = vb.ensure_label("Expedite", "ff0000", transport=fake)
    assert label_id == 42
    assert len(fake._labels) == 1  # no duplicate created


def test_ensure_label_fail_soft_on_transport_error():
    fake = FakeVikunja(fail=True)
    assert vb.ensure_label("Expedite", "ff0000", transport=fake) is None


def test_ensure_bucket_creates_when_missing():
    fake = FakeVikunja()
    bucket_id = vb.ensure_bucket(7, 2, "Backlog", transport=fake)
    assert bucket_id is not None
    assert fake._buckets[(7, 2)][0]["title"] == "Backlog"


def test_ensure_bucket_is_idempotent_by_name():
    fake = FakeVikunja()
    first = vb.ensure_bucket(7, 2, "Backlog", transport=fake)
    second = vb.ensure_bucket(7, 2, "Backlog", transport=fake)
    assert first == second
    assert len(fake._buckets[(7, 2)]) == 1


def test_ensure_bucket_finds_existing_without_creating():
    fake = FakeVikunja()
    fake.seed_bucket(7, 2, 99, title="Backlog")
    bucket_id = vb.ensure_bucket(7, 2, "Backlog", transport=fake)
    assert bucket_id == 99
    assert len(fake._buckets[(7, 2)]) == 1


def test_ensure_bucket_fail_soft_on_transport_error():
    fake = FakeVikunja(fail=True)
    assert vb.ensure_bucket(7, 2, "Backlog", transport=fake) is None


# ---------------------------------------------------------------------------
# C2 lifecycle: board movement (#844) — move_job_card + find_bucket_by_title
# ---------------------------------------------------------------------------


def _seed_kanban_board(fake: FakeVikunja, pid: int, view_id: int = 2) -> dict[str, int]:
    """Seed a kanban view + the 5 standard buckets; return {title: bucket_id}."""
    fake.seed_view(pid, view_id, title="Kanban", kind="kanban")
    ids: dict[str, int] = {}
    for offset, title in enumerate(
        ("Backlog", "Ready", "In Progress", "In Review/Verify", "Done"), start=10
    ):
        fake.seed_bucket(pid, view_id, offset, title=title)
        ids[title] = offset
    return ids


def test_move_job_card_happy_path():
    fake = FakeVikunja()
    ids = _seed_kanban_board(fake, 7)
    tid = fake.seed_task(
        7, title="[fleet-job r-1] build widget", done=False, bucket_id=ids["Backlog"]
    )
    result = vb.move_job_card(7, "r-1", "In Progress", transport=fake)
    assert result.moved is True
    assert result.bucket_id == ids["In Progress"]
    assert fake._tasks[tid]["bucket_id"] == ids["In Progress"]
    # the exact move endpoint was hit
    assert any(
        method == "POST"
        and path == f"/projects/7/views/2/buckets/{ids['In Progress']}/tasks"
        for (method, path, _body) in fake.calls
    )


def test_move_job_card_resolves_bucket_by_title_case_insensitive():
    fake = FakeVikunja()
    ids = _seed_kanban_board(fake, 7)
    fake.seed_task(7, title="[fleet-job r-2] x", done=False)
    result = vb.move_job_card(7, "r-2", "in progress", transport=fake)  # lowercase
    assert result.moved is True
    assert result.bucket_id == ids["In Progress"]


def test_move_job_card_no_kanban_view():
    fake = FakeVikunja()
    fake.seed_view(7, 2, title="List", kind="list")  # a view, but not kanban
    fake.seed_task(7, title="[fleet-job r-3] x", done=False)
    result = vb.move_job_card(7, "r-3", "Done", transport=fake)
    assert result.moved is False
    assert "kanban" in result.reason.lower()


def test_move_job_card_unknown_bucket_title():
    fake = FakeVikunja()
    _seed_kanban_board(fake, 7)
    fake.seed_task(7, title="[fleet-job r-4] x", done=False)
    result = vb.move_job_card(7, "r-4", "Nonexistent", transport=fake)
    assert result.moved is False
    assert "no bucket" in result.reason.lower()


def test_move_job_card_no_ticket_for_run():
    fake = FakeVikunja()
    _seed_kanban_board(fake, 7)  # no task seeded for this run
    result = vb.move_job_card(7, "r-missing", "Ready", transport=fake)
    assert result.moved is False
    assert "no job ticket" in result.reason.lower()


def test_move_job_card_fail_soft_on_transport_error():
    fake = FakeVikunja(fail=True)
    result = vb.move_job_card(7, "r-5", "Done", transport=fake)
    assert result.moved is False
    assert "transport failure" in result.reason.lower()


def test_find_bucket_by_title_case_insensitive_and_miss():
    buckets = [{"id": 10, "title": "Backlog"}, {"id": 12, "title": "In Progress"}]
    assert vb.find_bucket_by_title(buckets, "in progress") == 12
    assert vb.find_bucket_by_title(buckets, "  Backlog ") == 10
    assert vb.find_bucket_by_title(buckets, "Done") is None


def test_move_job_card_composes_with_resolve_board_transition():
    """The #844 forged-Done lock holds END-TO-END to the board write: a
    merged-without-oracle event yields NO transition (so no move is even
    attempted), while oracle+merged yields a Done move."""
    from shared.fleet.coord_lifecycle import (
        BUCKET_DONE,
        BUCKET_IN_PROGRESS,
        resolve_board_transition,
    )

    fake = FakeVikunja()
    ids = _seed_kanban_board(fake, 7)
    tid = fake.seed_task(
        7, title="[fleet-job r-6] x", done=False, bucket_id=ids["Backlog"]
    )

    # Forged/premature "done" — merged but NO oracle pass -> the ruler refuses a
    # Done transition, so a caller has nothing to move.
    assert resolve_board_transition(oracle_passed=False, merged=True) is None

    # Dispatch started -> In Progress.
    started = resolve_board_transition(dispatch_started=True)
    assert started is not None
    r1 = vb.move_job_card(7, "r-6", started.to_bucket, transport=fake)
    assert r1.moved is True
    assert fake._tasks[tid]["bucket_id"] == ids[BUCKET_IN_PROGRESS]

    # Genuine done -> oracle passed AND merged -> Done.
    done = resolve_board_transition(oracle_passed=True, merged=True)
    assert done is not None and done.to_bucket == BUCKET_DONE
    r2 = vb.move_job_card(7, "r-6", done.to_bucket, transport=fake)
    assert r2.moved is True
    assert fake._tasks[tid]["bucket_id"] == ids[BUCKET_DONE]


# ---------------------------------------------------------------------------
# post_task_comment (#844 C2 stall-comment sink) — fail-soft, outcomes-only
# ---------------------------------------------------------------------------


def test_post_task_comment_happy_path():
    fake = FakeVikunja()
    tid = fake.seed_task(7, title="[fleet-job r-9] x")
    ok = vb.post_task_comment(tid, "coordinator: stall detected", transport=fake)
    assert ok is True
    assert fake.comments[tid] == ["coordinator: stall detected"]


def test_post_task_comment_fail_soft_on_transport_error():
    """A Vikunja outage must NEVER raise out of the sink (a board outage cannot
    affect a dispatch/heartbeat run) — it returns False."""
    fake = FakeVikunja(fail=True)
    ok = vb.post_task_comment(123, "stall", transport=fake)
    assert ok is False


def test_post_task_comment_is_a_single_comment_call_no_spam():
    """Outcomes-only: exactly one comment PUT per post (never a heartbeat firehose;
    the dedup that makes it one-per-episode lives in the caller's seen-set)."""
    fake = FakeVikunja()
    tid = fake.seed_task(7)
    vb.post_task_comment(tid, "once", transport=fake)
    comment_puts = [
        c for c in fake.calls if c[0] == "PUT" and c[1].endswith("/comments")
    ]
    assert len(comment_puts) == 1
