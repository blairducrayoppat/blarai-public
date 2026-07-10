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
            if method == "GET":  # list/search
                needle = urllib.parse.parse_qs(parsed.query).get("s", [""])[0]
                out = [
                    self._tasks[t]
                    for t in self._project_tasks.get(pid, [])
                    if needle in self._tasks[t]["title"]
                ]
                return 200, out

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
