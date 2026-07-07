"""Engine tests for the BlarAI → fleet dispatch surface (shared/fleet/dispatch.py).

Pure-logic + mocked-subprocess; no real fleet, no 30B, no network. Proves:
target validation (incl. the BlarAI/.openclaw refusal), SUMMARY/RESULT parsing,
fail-closed enqueue, and the detached run trigger.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from shared.fleet.dispatch import (
    FleetDispatchConfig,
    _classify_result,
    build_default_config,
    create_project,
    CreateProjectResult,
    enqueue_task,
    latest_run_id,
    parse_summary,
    project_slug,
    read_acceptance_record,
    read_summary,
    run_fleet,
    slugify_task,
    summary_report_paths,
    validate_repo,
    write_acceptance_record,
)


def _cfg(tmp_path: Path) -> FleetDispatchConfig:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "add-fleet-task.ps1").write_text("# stub", encoding="utf-8")
    (scripts / "run-fleet.ps1").write_text("# stub", encoding="utf-8")
    projects = tmp_path / "projects"
    projects.mkdir()
    runs = tmp_path / "runs"
    runs.mkdir()
    return FleetDispatchConfig(
        scripts_dir=scripts,
        queue_path=tmp_path / "queue.json",
        runs_dir=runs,
        projects_dir=projects,
    )


def _make_repo(cfg: FleetDispatchConfig, name: str = "app") -> Path:
    repo = cfg.projects_dir / name
    (repo / ".git").mkdir(parents=True)
    return repo


# ---- validate_repo --------------------------------------------------------


def test_validate_repo_accepts_git_repo_under_projects(tmp_path):
    cfg = _cfg(tmp_path)
    assert validate_repo(_make_repo(cfg), cfg.projects_dir) is None


def test_validate_repo_rejects_non_git(tmp_path):
    cfg = _cfg(tmp_path)
    plain = cfg.projects_dir / "nope"
    plain.mkdir()
    err = validate_repo(plain, cfg.projects_dir)
    assert err and "not a git" in err


def test_validate_repo_rejects_outside_projects(tmp_path):
    cfg = _cfg(tmp_path)
    outside = tmp_path / "elsewhere"
    (outside / ".git").mkdir(parents=True)
    err = validate_repo(outside, cfg.projects_dir)
    assert err and "outside the allowed" in err


def test_validate_repo_refuses_blarai_component(tmp_path):
    cfg = _cfg(tmp_path)
    bad = cfg.projects_dir / "BlarAI" / "x"
    (bad / ".git").mkdir(parents=True)
    err = validate_repo(bad, cfg.projects_dir)
    assert err and "forbidden" in err


# ---- enqueue (mocked subprocess) ------------------------------------------


def test_enqueue_invokes_add_fleet_task(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    repo = _make_repo(cfg)
    seen: dict = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd

        class _R:
            returncode = 0
            stdout = ""
            stderr = ""

        return _R()

    monkeypatch.setattr(subprocess, "run", fake_run)
    res = enqueue_task(str(repo), "fix-logs", "Fix the logging.", config=cfg)
    assert res.ok, res.message
    joined = " ".join(seen["cmd"])
    assert "add-fleet-task.ps1" in joined
    assert "-Repo" in seen["cmd"] and str(repo) in seen["cmd"]
    assert "-Task" in seen["cmd"] and "fix-logs" in seen["cmd"]
    assert "-Queue" in seen["cmd"]


def test_enqueue_fail_closed_on_nonzero(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    repo = _make_repo(cfg)

    def fake_run(cmd, **kw):
        class _R:
            returncode = 1
            stdout = ""
            stderr = "boom"

        return _R()

    monkeypatch.setattr(subprocess, "run", fake_run)
    res = enqueue_task(str(repo), "t", "p", config=cfg)
    assert not res.ok and "boom" in res.message


def test_enqueue_refuses_blarai_before_subprocess(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    bad = cfg.projects_dir / "BlarAI"
    (bad / ".git").mkdir(parents=True)
    calls = {"n": 0}
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: calls.__setitem__("n", calls["n"] + 1)
    )
    res = enqueue_task(str(bad), "t", "p", config=cfg)
    assert not res.ok and "forbidden" in res.message
    assert calls["n"] == 0  # refused BEFORE any subprocess


def test_enqueue_fails_when_script_missing(tmp_path):
    cfg = _cfg(tmp_path)
    repo = _make_repo(cfg)
    (cfg.scripts_dir / "add-fleet-task.ps1").unlink()
    res = enqueue_task(str(repo), "t", "p", config=cfg)
    assert not res.ok and "not installed" in res.message


# ---- run_fleet (mocked Popen) ---------------------------------------------


def test_run_fleet_launches_detached_with_runid(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    seen: dict = {}

    class FakePopen:
        def __init__(self, cmd, **kw):
            seen["cmd"] = cmd

    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    res = run_fleet(config=cfg, run_id="20260101-000000-bd")
    assert res.ok and res.run_id == "20260101-000000-bd"
    assert "run-fleet.ps1" in " ".join(seen["cmd"])
    assert "-RunId" in seen["cmd"] and "20260101-000000-bd" in seen["cmd"]


# ---- summary parsing + read -----------------------------------------------

_SAMPLE = """FLEET RUN 20260101-000000-bd  (2026-01-01 00:00)
Queue: q.json
Processed this run: 3 of 3 queued

- fix-logs: processed
    RESULT: MERGED into your project - just open the app and try it.
    full report: C:\\path\\r1.txt
- add-tests: processed
    RESULT: NOT merged. The work is parked safely on branch 'agent/add-tests'.
    full report: C:\\path\\r2.txt
- noop: processed
    RESULT: Nothing to merge.
    full report: C:\\path\\r3.txt
"""


def test_parse_summary_classifies_each_task():
    outs = parse_summary(_SAMPLE)
    assert [o.task for o in outs] == ["fix-logs", "add-tests", "noop"]
    assert [o.result for o in outs] == ["MERGED", "PARKED", "NOTHING"]


def test_classify_result_forms():
    assert _classify_result("RESULT: BLOCKED: a potential secret was detected") == "BLOCKED"
    assert _classify_result("RESULT: Nothing to merge.") == "NOTHING"
    assert _classify_result("RESULT: NOT merged. parked on branch") == "PARKED"
    assert _classify_result("RESULT: MERGED into your project") == "MERGED"


def test_read_summary_reports_outcomes(tmp_path):
    cfg = _cfg(tmp_path)
    rd = cfg.runs_dir / "rid1"
    rd.mkdir()
    (rd / "SUMMARY.txt").write_text(_SAMPLE, encoding="utf-8")
    res = read_summary(config=cfg, run_id="rid1")
    assert res.ok
    assert "fix-logs" in res.message and "merged" in res.message.lower()


def test_read_summary_missing_is_in_progress(tmp_path):
    cfg = _cfg(tmp_path)
    res = read_summary(config=cfg, run_id="nope")
    assert res.ok and "no summary yet" in res.message


def test_latest_run_id(tmp_path):
    cfg = _cfg(tmp_path)
    (cfg.runs_dir / "20260101-000000-bd").mkdir()
    (cfg.runs_dir / "20260102-000000-bd").mkdir()
    assert latest_run_id(config=cfg) == "20260102-000000-bd"


def test_slugify_task():
    assert slugify_task("Fix the Logging!") == "fix-the-logging"
    assert slugify_task("   ") == "task"


# ---- acceptance record + report paths (increment 3) -----------------------


def test_summary_report_paths_extracts_each():
    # _SAMPLE's escaped "\\path\\rN.txt" are single backslashes in the real string.
    assert summary_report_paths(_SAMPLE) == [
        "C:\\path\\r1.txt", "C:\\path\\r2.txt", "C:\\path\\r3.txt",
    ]


def test_summary_report_paths_empty_when_absent():
    assert summary_report_paths("no report lines here") == []


def test_acceptance_record_roundtrip(tmp_path):
    cfg = _cfg(tmp_path)
    spec_dict = {"goal": "a calc",
                 "criteria": [{"id": "c1", "text": "it builds", "tier": "build", "check": ""}]}
    path = write_acceptance_record(cfg, "rid1", spec_dict=spec_dict, repo="C:\\projects\\calc")
    assert path.is_file()
    assert read_acceptance_record(cfg, "rid1") == {"spec": spec_dict, "repo": "C:\\projects\\calc"}


def test_read_acceptance_record_missing_is_none(tmp_path):
    assert read_acceptance_record(_cfg(tmp_path), "nope") is None


# ---- build_default_config: config-driven roots (#670) ---------------------


def test_build_default_config_uses_provided_roots():
    cfg = build_default_config(agentic_setup_dir="D:/fleet", projects_dir="D:/projects")
    assert cfg.scripts_dir == Path("D:/fleet/scripts")
    assert cfg.queue_path == Path("D:/fleet/state/fleet-queue.json")
    assert cfg.runs_dir == Path("D:/fleet/state/fleet-runs")
    assert cfg.projects_dir == Path("D:/projects")


def test_build_default_config_falls_back_when_empty_or_absent():
    # Empty strings (the "config key absent" case threaded as "") fall back to the
    # compiled-in default for this box; the no-arg call is the same fallback.
    cfg = build_default_config(agentic_setup_dir="", projects_dir="")
    assert cfg.scripts_dir.name == "scripts" and cfg.scripts_dir.parent.name == "agentic-setup"
    assert cfg.queue_path.name == "fleet-queue.json" and cfg.runs_dir.name == "fleet-runs"
    assert cfg.projects_dir.name == "projects"
    assert build_default_config().projects_dir == cfg.projects_dir


def test_build_default_config_derives_state_layout_from_root_only():
    # Only the ROOT is configurable; the fleet's internal state\ layout is fixed.
    cfg = build_default_config(agentic_setup_dir="X:/somewhere/agentic", projects_dir="Y:/p")
    assert cfg.scripts_dir.parent == Path("X:/somewhere/agentic")
    assert cfg.queue_path.parent == Path("X:/somewhere/agentic/state")
    assert cfg.runs_dir.parent == Path("X:/somewhere/agentic/state")


# ---- create_project (#712): create-a-project-via-BlarAI -------------------


def _git_branch(repo: Path) -> str:
    cp = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True,
    )
    return cp.stdout.strip()


def test_create_project_makes_a_valid_dispatch_target(tmp_path):
    cfg = _cfg(tmp_path)
    res = create_project("My First App", config=cfg, goal="a tiny calculator")
    assert res.ok, res.message
    assert isinstance(res, CreateProjectResult)
    assert res.name == "my-first-app"
    repo = Path(res.path)
    # It is now a VALID dispatch target: a git repo, with a commit, under projects.
    assert (repo / ".git").is_dir()
    assert validate_repo(repo, cfg.projects_dir) is None
    # README seeded with the goal; .gitignore present; default branch == main.
    assert "a tiny calculator" in (repo / "README.md").read_text(encoding="utf-8")
    assert (repo / ".gitignore").is_file()
    assert _git_branch(repo) == "main"


def test_create_project_refuses_empty_name(tmp_path):
    res = create_project("!!!", config=_cfg(tmp_path))
    assert not res.ok and res.error == "empty_slug"


def test_create_project_refuses_existing(tmp_path):
    cfg = _cfg(tmp_path)
    assert create_project("dup", config=cfg).ok
    again = create_project("dup", config=cfg)
    assert not again.ok and again.error == "exists"


def test_create_project_neutralizes_path_traversal(tmp_path):
    # A name with traversal/separators slugifies to a SAFE single segment under
    # projects_dir — never escapes, never lands under a forbidden root.
    cfg = _cfg(tmp_path)
    res = create_project("../../BlarAI/evil", config=cfg)
    assert res.ok, res.message
    repo = Path(res.path)
    assert repo.parent == cfg.projects_dir.resolve()
    assert "BlarAI" not in repo.name  # lowercased + hyphenated slug


def test_project_slug_forms():
    assert project_slug("My App") == "my-app"
    assert project_slug("  Hello, World!  ") == "hello-world"
    assert project_slug("!!!") == ""
    assert project_slug("a" * 80) == "a" * 48
