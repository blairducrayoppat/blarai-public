"""#830 G6 — wave-final executability floor (``real_run_exec_smoke``).

The language-agnostic "the assembled app actually starts" gate — the behavioral floor
Node/web jobs lacked (B7: a Node util-trio merged working code but the wave-final oracle
only ran under a test runner the acceptance-tests task authored; when that task parked, the
job had NO behavioral gate). The floor BOOTS the declared entrypoint before the oracle
grades, so a missing/mis-placed module at startup fails FAST with the module NAMED, instead
of an opaque wave-final ModuleNotFoundError.

Locks:
  * python green / B7 (import-time ModuleNotFoundError → ok=False, module named);
  * node green / B7 (ERR_MODULE_NOT_FOUND → ok=False, spec named) — the EXACT B7 shape;
  * precision-first (a loaded app that exits non-zero for its own reasons is ok=True — the
    floor proves START, never correctness);
  * fail-soft not-run (no entrypoint / uv|node absent / timeout → ok=None, non-blocking);
  * language dispatch (surface=web routes to the #823 seam; dotnet/unknown → not-run);
  * the #823 web-console SEAM (delegated, not duplicated) + the #827 evidence stamp.
"""

from __future__ import annotations

import json
from pathlib import Path

from shared.fleet import swap_ops as so
from shared.fleet.acceptance import JOB_ORACLE_PATH_NODE, JOB_ORACLE_PATH_PYTHON
from shared.fleet.dispatch import FleetDispatchConfig


def _config(tmp_path: Path) -> FleetDispatchConfig:
    return FleetDispatchConfig(
        scripts_dir=tmp_path / "scripts",
        queue_path=tmp_path / "state" / "q.json",
        runs_dir=tmp_path / "state" / "runs",
        projects_dir=tmp_path / "projects",
    )


def _mk_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _ok_run(_cmd, _t, _cwd=None, env=None):
    return (True, "", "")


# ===========================================================================
# Python leg
# ===========================================================================


def test_python_green_boots(tmp_path, monkeypatch):
    monkeypatch.setattr(so.shutil, "which", lambda name: f"C:/fake/{name}.exe")
    repo = _mk_repo(tmp_path / "proj")
    (repo / "main.py").write_text("def main():\n    return 0\n", encoding="utf-8")
    res = so.real_run_exec_smoke(_config(tmp_path), "R1", str(repo),
                                 JOB_ORACLE_PATH_PYTHON, run=_ok_run)
    assert res["ok"] is True and res["language"] == "python"
    assert "main.py" in res["evidence"]


def test_python_b7_missing_module_at_import_names_it(tmp_path, monkeypatch):
    """The python B7 shape: the entrypoint imports a module the coder did not place →
    ModuleNotFoundError at import → ok=False, the module NAMED (for the fix cycle) and
    fingerprinted for #827."""
    monkeypatch.setattr(so.shutil, "which", lambda name: f"C:/fake/{name}.exe")
    repo = _mk_repo(tmp_path / "proj")
    (repo / "main.py").write_text("import cli_interface\n", encoding="utf-8")

    def boom(cmd, _t, _cwd=None, env=None):
        # the import check ('-c') fails with the classic missing-module traceback
        return (False, "", "ModuleNotFoundError: No module named 'cli_interface'")

    res = so.real_run_exec_smoke(_config(tmp_path), "R1", str(repo),
                                 JOB_ORACLE_PATH_PYTHON, run=boom)
    assert res["ok"] is False
    assert res["fingerprint"] == "ModuleNotFoundError:cli_interface"
    assert any(u.get("module") == "cli_interface" for u in res["unresolved"])
    assert "main.py" in res["evidence"]


def test_python_import_runs_under_clean_grade_env(tmp_path, monkeypatch):
    """H4 parity: the boot runs under the SAME clean-env recipe (PYTHONPATH=<repo> +
    PYTHONSAFEPATH=1) the oracle imports with — a smoke-green entrypoint is grade-
    importable."""
    monkeypatch.setattr(so.shutil, "which", lambda name: f"C:/fake/{name}.exe")
    repo = _mk_repo(tmp_path / "proj")
    (repo / "main.py").write_text("x = 1\n", encoding="utf-8")
    seen: dict = {}

    def rec(cmd, _t, cwd=None, env=None):
        seen.setdefault("env", env)
        seen.setdefault("cmd", list(cmd))
        return (True, "", "")

    so.real_run_exec_smoke(_config(tmp_path), "R1", str(repo),
                           JOB_ORACLE_PATH_PYTHON, run=rec)
    assert seen["env"]["PYTHONSAFEPATH"] == "1"
    assert seen["env"]["PYTHONPATH"] == str(repo)
    assert "import main" in " ".join(seen["cmd"])


def test_python_non_boot_nonzero_help_is_still_started(tmp_path, monkeypatch):
    """Precision-first: the import succeeds, then `--help` exits non-zero WITHOUT a boot-
    class error (the app's own argparse quibble) → the floor proves START, so ok=True."""
    monkeypatch.setattr(so.shutil, "which", lambda name: f"C:/fake/{name}.exe")
    repo = _mk_repo(tmp_path / "proj")
    (repo / "app.py").write_text("x = 1\n", encoding="utf-8")

    def by_phase(cmd, _t, _cwd=None, env=None):
        if "-c" in cmd:            # import check
            return (True, "", "")
        return (False, "usage: app", "error: unrecognized arguments: --help")

    res = so.real_run_exec_smoke(_config(tmp_path), "R1", str(repo),
                                 JOB_ORACLE_PATH_PYTHON, run=by_phase)
    assert res["ok"] is True


def test_python_help_timeout_is_non_fatal(tmp_path, monkeypatch):
    """A `--help` that hangs (a server-start) times out; the import already proved boot, so
    the timeout is non-fatal → ok=True (never a false red on a slow app)."""
    monkeypatch.setattr(so.shutil, "which", lambda name: f"C:/fake/{name}.exe")
    repo = _mk_repo(tmp_path / "proj")
    (repo / "main.py").write_text("x = 1\n", encoding="utf-8")

    def by_phase(cmd, _t, _cwd=None, env=None):
        if "-c" in cmd:
            return (True, "", "")
        return (False, "", "timed out after 45s")

    res = so.real_run_exec_smoke(_config(tmp_path), "R1", str(repo),
                                 JOB_ORACLE_PATH_PYTHON, run=by_phase)
    assert res["ok"] is True


def test_python_import_timeout_is_not_run(tmp_path, monkeypatch):
    """A hanging IMPORT (an import-time side effect) is could-not-run, not a red."""
    monkeypatch.setattr(so.shutil, "which", lambda name: f"C:/fake/{name}.exe")
    repo = _mk_repo(tmp_path / "proj")
    (repo / "main.py").write_text("x = 1\n", encoding="utf-8")
    res = so.real_run_exec_smoke(
        _config(tmp_path), "R1", str(repo), JOB_ORACLE_PATH_PYTHON,
        run=lambda cmd, t, cwd=None, env=None: (False, "", "timed out after 120s"))
    assert res["ok"] is None and "import" in res["evidence"].lower()


def test_python_no_entrypoint_is_not_run(tmp_path):
    repo = _mk_repo(tmp_path / "proj")
    (repo / "helper.py").write_text("x = 1\n", encoding="utf-8")  # eco=python, no entry
    res = so.real_run_exec_smoke(_config(tmp_path), "R1", str(repo),
                                 JOB_ORACLE_PATH_PYTHON, run=_ok_run)
    assert res["ok"] is None and "no python entrypoint" in res["evidence"]


def test_python_uv_unavailable_is_not_run(tmp_path, monkeypatch):
    monkeypatch.setattr(so.shutil, "which", lambda name: None)  # no uv
    repo = _mk_repo(tmp_path / "proj")
    (repo / "main.py").write_text("x = 1\n", encoding="utf-8")
    res = so.real_run_exec_smoke(_config(tmp_path), "R1", str(repo),
                                 JOB_ORACLE_PATH_PYTHON, run=_ok_run)
    assert res["ok"] is None and "uv unavailable" in res["evidence"]


# ===========================================================================
# Node leg — the exact B7 shape
# ===========================================================================


def test_node_green_boots(tmp_path, monkeypatch):
    monkeypatch.setattr(so.shutil, "which", lambda name: f"C:/fake/{name}.exe")
    repo = _mk_repo(tmp_path / "web")
    (repo / "package.json").write_text('{"main": "main.js"}', encoding="utf-8")
    (repo / "main.js").write_text("console.log('ok');\n", encoding="utf-8")
    res = so.real_run_exec_smoke(_config(tmp_path), "R1", str(repo),
                                 JOB_ORACLE_PATH_NODE, run=_ok_run)
    assert res["ok"] is True and res["language"] == "node"


def test_node_b7_err_module_not_found_names_spec(tmp_path, monkeypatch):
    """The EXACT B7 shape: `node main.js --help` fails at LINK time with
    ERR_MODULE_NOT_FOUND naming a module the coder placed at a different path → ok=False,
    the spec named for the fix cycle, fingerprinted for #827."""
    monkeypatch.setattr(so.shutil, "which", lambda name: f"C:/fake/{name}.exe")
    repo = _mk_repo(tmp_path / "web")
    (repo / "package.json").write_text('{"bin": "main.js"}', encoding="utf-8")
    (repo / "main.js").write_text("import s from './src/slugify-phrase.js';\n",
                                  encoding="utf-8")
    err = ("node:internal/modules/esm/resolve\n"
           "Error [ERR_MODULE_NOT_FOUND]: Cannot find module "
           "'/x/web/src/slugify-phrase.js' imported from /x/web/main.js")
    res = so.real_run_exec_smoke(
        _config(tmp_path), "R1", str(repo), JOB_ORACLE_PATH_NODE,
        run=lambda cmd, t, cwd=None, env=None: (False, "", err))
    assert res["ok"] is False
    assert res["fingerprint"].startswith("ERR_MODULE_NOT_FOUND")
    assert "slugify-phrase" in res["fingerprint"]
    assert any("slugify-phrase" in str(u.get("spec", "")) for u in res["unresolved"])


def test_node_non_boot_nonzero_is_still_started(tmp_path, monkeypatch):
    monkeypatch.setattr(so.shutil, "which", lambda name: f"C:/fake/{name}.exe")
    repo = _mk_repo(tmp_path / "web")
    (repo / "package.json").write_text('{"main": "main.js"}', encoding="utf-8")
    (repo / "main.js").write_text("process.exit(3);\n", encoding="utf-8")
    res = so.real_run_exec_smoke(
        _config(tmp_path), "R1", str(repo), JOB_ORACLE_PATH_NODE,
        run=lambda cmd, t, cwd=None, env=None: (False, "did work", "exit 3, no load error"))
    assert res["ok"] is True  # it STARTED — the floor proves start, not exit code


def test_node_timeout_is_not_run(tmp_path, monkeypatch):
    monkeypatch.setattr(so.shutil, "which", lambda name: f"C:/fake/{name}.exe")
    repo = _mk_repo(tmp_path / "web")
    (repo / "package.json").write_text('{"main": "main.js"}', encoding="utf-8")
    (repo / "main.js").write_text("setInterval(()=>{}, 1000);\n", encoding="utf-8")
    res = so.real_run_exec_smoke(
        _config(tmp_path), "R1", str(repo), JOB_ORACLE_PATH_NODE,
        run=lambda cmd, t, cwd=None, env=None: (False, "", "timed out after 120s"))
    assert res["ok"] is None


def test_node_no_entrypoint_is_not_run(tmp_path, monkeypatch):
    monkeypatch.setattr(so.shutil, "which", lambda name: f"C:/fake/{name}.exe")
    repo = _mk_repo(tmp_path / "web")
    (repo / "package.json").write_text('{"name": "x"}', encoding="utf-8")  # no bin/main/index
    res = so.real_run_exec_smoke(_config(tmp_path), "R1", str(repo),
                                 JOB_ORACLE_PATH_NODE, run=_ok_run)
    assert res["ok"] is None and "no node entrypoint" in res["evidence"]


# ===========================================================================
# Web leg — delegated to the #823 console-capture SEAM (never duplicated here)
# ===========================================================================


def test_web_default_seam_is_not_run(tmp_path):
    """Until #823 wires its capture helper, the web leg is an honest not-run (non-blocking).
    surface='web' routes here; the default seam returns ok=None."""
    repo = _mk_repo(tmp_path / "site")
    (repo / "package.json").write_text('{"main": "index.js"}', encoding="utf-8")
    (repo / "public").mkdir()
    (repo / "public" / "index.html").write_text("<html></html>", encoding="utf-8")
    res = so.real_run_exec_smoke(_config(tmp_path), "R1", str(repo),
                                 JOB_ORACLE_PATH_NODE, surface="web", run=_ok_run)
    assert res["ok"] is None and res["language"] == "web"
    assert "#823" in res["evidence"]


def test_web_seam_console_errors_red_the_floor(tmp_path):
    """When #823's capture reports console/pageerror lines, the floor REDs with them quoted
    (the fix-cycle signal) and a deterministic fingerprint for #827."""
    repo = _mk_repo(tmp_path / "site")
    (repo / "index.html").write_text("<html></html>", encoding="utf-8")

    def capture(_repo, _root):
        return {"ok": False, "errors": ["ReferenceError: foo is not defined",
                                        "TypeError: undefined is not a function"],
                "evidence": "2 console errors"}

    res = so.real_run_exec_smoke(_config(tmp_path), "R1", str(repo),
                                 JOB_ORACLE_PATH_NODE, surface="web",
                                 web_console_capture=capture, run=_ok_run)
    assert res["ok"] is False and res["fingerprint"] == "web-console:2"
    assert "ReferenceError" in res["evidence"]


def test_web_seam_clean_load_passes(tmp_path):
    repo = _mk_repo(tmp_path / "site")
    (repo / "index.html").write_text("<html></html>", encoding="utf-8")
    res = so.real_run_exec_smoke(
        _config(tmp_path), "R1", str(repo), JOB_ORACLE_PATH_NODE, surface="web",
        web_console_capture=lambda r, root: {"ok": True, "errors": [],
                                             "evidence": "loaded clean"}, run=_ok_run)
    assert res["ok"] is True and res["language"] == "web"


def test_web_no_index_html_is_not_run(tmp_path):
    repo = _mk_repo(tmp_path / "site")
    (repo / "package.json").write_text('{"main": "index.js"}', encoding="utf-8")
    res = so.real_run_exec_smoke(_config(tmp_path), "R1", str(repo),
                                 JOB_ORACLE_PATH_NODE, surface="web", run=_ok_run)
    assert res["ok"] is None and "no web entrypoint" in res["evidence"]


def test_web_seam_raise_is_not_run(tmp_path):
    repo = _mk_repo(tmp_path / "site")
    (repo / "index.html").write_text("<html></html>", encoding="utf-8")

    def raiser(_r, _root):
        raise RuntimeError("capture blew up")

    res = so.real_run_exec_smoke(_config(tmp_path), "R1", str(repo),
                                 JOB_ORACLE_PATH_NODE, surface="web",
                                 web_console_capture=raiser, run=_ok_run)
    assert res["ok"] is None and "raised" in res["evidence"]


# ===========================================================================
# #823 FILL of the web-console-capture seam (real_web_console_capture) — the
# capture-app.ps1 CDP web tier mapped to the {ok, errors, evidence} contract.
# ===========================================================================


def _fake_capture_writing(sidecar_obj):
    """A fake ``_run_to_logfile`` that writes ``sidecar_obj`` (or nothing) to the sidecar the
    capture-app.ps1 web tier would produce, so real_web_console_capture's mapping is tested
    without pwsh/Edge."""
    def _fake(cmd, *, log_path, timeout_s, **_kw):  # noqa: ANN001
        base = Path(log_path).parent
        base.mkdir(parents=True, exist_ok=True)
        if sidecar_obj is not None:
            (base / "exec-smoke-web.png.console.json").write_text(
                json.dumps(sidecar_obj), encoding="utf-8")
        return True
    return _fake


def _with_capture_script(tmp_path: Path):
    """Create the dummy capture-app.ps1 so real_web_console_capture's existence check passes."""
    scripts = tmp_path / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "capture-app.ps1").write_text("# stub", encoding="utf-8")


def test_web_console_error_lines_extracts_errors_and_exceptions():
    """Pure: only ERROR-level console + uncaught exceptions become lines (verbatim, file:line);
    warnings/info are ignored (a boot-smoke keys on 'did it throw', not styling)."""
    data = {
        "pageErrors": [{"text": "ReferenceError: sum is not defined", "url": "chart.js", "line": 10}],
        "console": [
            {"level": "error", "text": "render failed", "url": "app.js", "line": 3},
            {"level": "warning", "text": "deprecated"},
            {"level": "info", "text": "ready"},
        ],
    }
    lines = so._web_console_error_lines(data)
    assert lines[0] == "Uncaught: ReferenceError: sum is not defined (chart.js:10)"
    assert any(x.startswith("console.error: render failed") for x in lines)
    assert not any("deprecated" in x or "ready" in x for x in lines)


def test_real_web_console_capture_clean_load_passes(tmp_path, monkeypatch):
    _with_capture_script(tmp_path)
    monkeypatch.setattr(so, "_run_to_logfile",
                        _fake_capture_writing({"captured": True, "hard": False, "errorCount": 0,
                                               "console": [], "pageErrors": []}))
    res = so.real_web_console_capture(_config(tmp_path), "R1", str(tmp_path / "site"), "web_root")
    assert res == {"ok": True, "errors": [], "evidence": "served + loaded + zero console errors"}


def test_real_web_console_capture_console_error_reds(tmp_path, monkeypatch):
    _with_capture_script(tmp_path)
    monkeypatch.setattr(so, "_run_to_logfile", _fake_capture_writing(
        {"captured": True, "hard": True, "errorCount": 1,
         "pageErrors": [{"text": "ReferenceError: sum is not defined", "url": "chart.js", "line": 10}],
         "console": []}))
    res = so.real_web_console_capture(_config(tmp_path), "R1", str(tmp_path / "site"), "web_root")
    assert res["ok"] is False
    assert any("sum is not defined" in e for e in res["errors"])   # verbatim, for the fix cycle
    assert "1 console error" in res["evidence"]


def test_real_web_console_capture_degraded_is_not_run(tmp_path, monkeypatch):
    """captured:false (the msedge --screenshot fallback ran) -> ok=None, honest not-run (the
    ok-flag discipline: a console-blind capture never fakes a boot verdict)."""
    _with_capture_script(tmp_path)
    monkeypatch.setattr(so, "_run_to_logfile", _fake_capture_writing(
        {"captured": False, "error": "cdp unavailable", "console": [], "pageErrors": []}))
    res = so.real_web_console_capture(_config(tmp_path), "R1", str(tmp_path / "site"), "web_root")
    assert res["ok"] is None and res["errors"] == []


def test_real_web_console_capture_missing_sidecar_is_not_run(tmp_path, monkeypatch):
    _with_capture_script(tmp_path)
    monkeypatch.setattr(so, "_run_to_logfile", _fake_capture_writing(None))  # writes no sidecar
    res = so.real_web_console_capture(_config(tmp_path), "R1", str(tmp_path / "site"), "web_root")
    assert res["ok"] is None and "no console sidecar" in res["evidence"]


def test_real_web_console_capture_no_script_is_not_run(tmp_path):
    # capture-app.ps1 absent (agentic-setup not on this box) -> honest not-run, never raises.
    res = so.real_web_console_capture(_config(tmp_path), "R1", str(tmp_path / "site"), "web_root")
    assert res["ok"] is None and "capture-app.ps1 not found" in res["evidence"]


def test_build_swap_ops_fills_web_console_capture_seam(tmp_path, monkeypatch):
    """THE composition lock (#823 x #830): build_swap_ops now wires a NON-None web_console_capture
    that routes to real_web_console_capture — the seam #830 left =None is FILLED."""
    captured: dict = {}

    def fake_exec_smoke(config, run_id, repo, rel, *, surface="", language_hint="",
                        web_console_capture=None, **_kw):
        captured["wcc"] = web_console_capture
        return {"ok": None}

    routed: dict = {}
    monkeypatch.setattr(so, "real_run_exec_smoke", fake_exec_smoke)
    monkeypatch.setattr(so, "real_web_console_capture",
                        lambda config, run_id, r, wr: routed.update(r=r, wr=wr) or {"ok": True})

    ops = so.build_swap_ops(_config(tmp_path), run_id="RID", old_pid=1,
                            relaunch_argv=["py"], relaunch_cwd="C:/x")
    ops.run_exec_smoke("C:/proj", "oracle.py")

    wcc = captured["wcc"]
    assert wcc is not None and callable(wcc)            # the seam is FILLED, not the #830 None
    assert wcc("C:/proj", "C:/proj/public") == {"ok": True}
    assert routed == {"r": "C:/proj", "wr": "C:/proj/public"}   # routes to real_web_console_capture


# ===========================================================================
# Language dispatch + evidence stamp
# ===========================================================================


def test_dotnet_has_no_behavioral_floor(tmp_path):
    """The r4greens matrix: .NET is build-only (the wave gate build-checks it) — the floor
    is an honest not-run, never a false verdict."""
    repo = _mk_repo(tmp_path / "app")
    (repo / "app.csproj").write_text("<Project/>", encoding="utf-8")
    res = so.real_run_exec_smoke(_config(tmp_path), "R1", str(repo), "", run=_ok_run)
    assert res["ok"] is None and res["language"] == "dotnet"
    assert "build-only" in res["evidence"]


def test_surface_web_overrides_node_ecosystem(tmp_path):
    """A web app is node-ecosystem (package.json) but surface='web' routes it to the web
    leg — never mis-smoked as a node CLI (which would start a server and time out)."""
    repo = _mk_repo(tmp_path / "site")
    (repo / "package.json").write_text('{"main": "main.js"}', encoding="utf-8")
    (repo / "main.js").write_text("x=1;\n", encoding="utf-8")
    (repo / "index.html").write_text("<html></html>", encoding="utf-8")
    res = so.real_run_exec_smoke(_config(tmp_path), "R1", str(repo),
                                 JOB_ORACLE_PATH_NODE, surface="web", run=_ok_run)
    assert res["language"] == "web"


def test_language_hint_python_dispatches_python(tmp_path, monkeypatch):
    monkeypatch.setattr(so.shutil, "which", lambda name: f"C:/fake/{name}.exe")
    repo = _mk_repo(tmp_path / "proj")
    (repo / "main.py").write_text("x=1\n", encoding="utf-8")
    res = so.real_run_exec_smoke(_config(tmp_path), "R1", str(repo), "",
                                 language_hint="python", run=_ok_run)
    assert res["language"] == "python" and res["ok"] is True


def test_node_web_with_index_html_routes_web_without_surface(tmp_path):
    """No surface hint, node ecosystem, but an index.html present → the structural web
    check routes to the web leg (not a node CLI smoke)."""
    repo = _mk_repo(tmp_path / "site")
    (repo / "package.json").write_text('{"main": "main.js"}', encoding="utf-8")
    (repo / "index.html").write_text("<html></html>", encoding="utf-8")
    res = so.real_run_exec_smoke(_config(tmp_path), "R1", str(repo),
                                 JOB_ORACLE_PATH_NODE, run=_ok_run)
    assert res["language"] == "web"


def test_evidence_stamp_written_for_827(tmp_path, monkeypatch):
    """The #827 evidence stamp (`exec_smoke: pass|fail:<fingerprint>`) lands in the run's
    exec-smoke.log for both a pass and a boot fail."""
    monkeypatch.setattr(so.shutil, "which", lambda name: f"C:/fake/{name}.exe")
    config = _config(tmp_path)
    repo = _mk_repo(tmp_path / "proj")
    (repo / "main.py").write_text("import missing_mod\n", encoding="utf-8")
    so.real_run_exec_smoke(
        config, "R1", str(repo), JOB_ORACLE_PATH_PYTHON,
        run=lambda cmd, t, cwd=None, env=None: (
            False, "", "ModuleNotFoundError: No module named 'missing_mod'"))
    log = (config.runs_dir / "R1" / "exec-smoke.log").read_text(encoding="utf-8")
    assert "exec_smoke: fail:ModuleNotFoundError:missing_mod" in log

    repo2 = _mk_repo(tmp_path / "proj2")
    (repo2 / "main.py").write_text("x=1\n", encoding="utf-8")
    so.real_run_exec_smoke(config, "R2", str(repo2), JOB_ORACLE_PATH_PYTHON, run=_ok_run)
    log2 = (config.runs_dir / "R2" / "exec-smoke.log").read_text(encoding="utf-8")
    assert "exec_smoke: pass" in log2
