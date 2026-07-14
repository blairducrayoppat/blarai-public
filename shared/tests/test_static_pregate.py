"""#831 (QUALITY-13) — error-level static pre-gate locks.

The load-bearing locks (from the ticket):
  * TASTE-IMMUNITY — the select set is ERROR level ONLY (E9/F821/F823); a style-only
    file (long lines / unsorted imports) PASSES untouched. Widening the select set to a
    style rule flips ``test_python_error_select_is_frozen`` / the ``build_ruff_cmd`` lock.
  * F821 CAUGHT — an undefined-name defect is named (file:line) for the fix cycle.
  * NODE SYNTAX CAUGHT — ``node --check`` names a syntax error.
  * MISSING-RUFF HONEST DEGRADE — no ruff ⇒ ``skipped-no-ruff`` (``ok=None``), never a
    false green nor a hard block.
  * CLEAN-ENV — ruff runs ``--isolated`` (the #822 H1 lesson: the coder's ``ruff.toml``
    cannot influence the verdict).
  * THE #827 STAMP — clean / fail / skipped.

Deterministic locks use an injected fake ``run`` (captured real ruff JSON shapes), so the
whole gate runs subprocess-free. A handful of REAL ruff/node subprocess tests are the
live proof — guarded to SKIP when the tool is unreachable (uv/network-free CI), never a
flaky hard-fail."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from shared.fleet import static_pregate as sp
from shared.fleet import swap_ops as so
from shared.fleet.dispatch import FleetDispatchConfig

_REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Captured real-ruff JSON shapes (from ruff 0.14.3 --output-format json) — the
# deterministic fixtures the parsing locks feed through a fake ``run``.
# ---------------------------------------------------------------------------

def _ruff_f821(path: str) -> str:
    return json.dumps([{
        "code": "F821", "message": "Undefined name `convertUnits`",
        "location": {"row": 2, "column": 12},
        "end_location": {"row": 2, "column": 24},
        "filename": path, "fix": None, "url": "https://docs.astral.sh/ruff/rules/undefined-name",
    }])


def _ruff_syntax(path: str) -> str:
    return json.dumps([{
        "code": "invalid-syntax",
        "message": "Expected a parameter or the end of the parameter list",
        "location": {"row": 1, "column": 12},
        "end_location": {"row": 1, "column": 13}, "filename": path,
    }])


def _fake_run(mapping):
    """A fake ``run(cmd, timeout_s, cwd=None, env=None)`` that dispatches on the argv:
    ``mapping`` maps a substring found in the joined command → ``(ok, stdout, stderr)``."""
    def _run(cmd, timeout_s, cwd=None, env=None):
        joined = " ".join(str(c) for c in cmd)
        for needle, result in mapping.items():
            if needle in joined:
                return result
        return (True, "", "")
    return _run


# ---------------------------------------------------------------------------
# TASTE-IMMUNITY — the select set is a hard lock, and the ruff cmd is clean-env
# ---------------------------------------------------------------------------


def test_python_error_select_is_frozen_error_level_only():
    # The hard lock: exactly the three error-level codes, no style rule EVER.
    assert sp.PYTHON_ERROR_SELECT == ("E9", "F821", "F823")
    # None of the common STYLE prefixes may appear (E1-E7 pycodestyle, W, I, N, D, …).
    for code in sp.PYTHON_ERROR_SELECT:
        assert code in ("E9", "F821", "F823")
    assert not any(c.startswith(("E1", "E2", "E3", "E4", "E5", "E7", "W", "I", "D", "N", "C", "UP"))
                   for c in sp.PYTHON_ERROR_SELECT)


def test_build_ruff_cmd_is_isolated_error_level_json():
    cmd = sp.build_ruff_cmd(["ruff"], ["a.py", "b.py"])
    assert "--isolated" in cmd                       # clean-env: coder ruff.toml ignored
    assert "--select" in cmd and "E9,F821,F823" in cmd
    assert "--output-format" in cmd and "json" in cmd
    assert cmd[-2:] == ["a.py", "b.py"] and "--" in cmd  # files after a `--` guard
    # no style rule anywhere on the command line
    assert "E501" not in " ".join(cmd) and "--fix" not in cmd


def test_resolve_ruff_argv_prefers_uv_then_ruff_then_none():
    assert sp.resolve_ruff_argv(which=lambda n: "C:/uv.exe" if n == "uv" else None)[:2] == \
        ["C:/uv.exe", "run"]
    assert sp.resolve_ruff_argv(which=lambda n: "C:/ruff.exe" if n == "ruff" else None) == \
        ["C:/ruff.exe"]
    assert sp.resolve_ruff_argv(which=lambda n: None) is None


# ---------------------------------------------------------------------------
# Python leg — parsing (deterministic, captured ruff JSON via a fake run)
# ---------------------------------------------------------------------------


def test_probe_python_names_f821_with_file_line(tmp_path):
    run = _fake_run({"ruff": (False, _ruff_f821(str(tmp_path / "cli.py")), "")})
    res = sp.probe_python_files(["cli.py"], tmp_path,
                                run=run, which=lambda n: "uv")
    assert res["ok"] is False and res["checked"] == 1
    e = res["errors"][0]
    assert e["code"] == "F821" and e["line"] == 2 and e["lang"] == "python"
    assert e["summary"] == "cli.py:2 F821: Undefined name `convertUnits`"


def test_probe_python_catches_syntax_error(tmp_path):
    run = _fake_run({"ruff": (False, _ruff_syntax(str(tmp_path / "x.py")), "")})
    res = sp.probe_python_files(["x.py"], tmp_path, run=run, which=lambda n: "uv")
    assert res["ok"] is False and res["errors"][0]["code"] == "invalid-syntax"


def test_probe_python_clean_empty_array_is_ok(tmp_path):
    # `[]` is what a STYLE-ONLY file yields under --select E9,F821,F823 — the
    # taste-immunity pass, at the parse layer.
    run = _fake_run({"ruff": (True, "[]", "")})
    res = sp.probe_python_files(["style.py"], tmp_path, run=run, which=lambda n: "uv")
    assert res["ok"] is True and res["errors"] == [] and res["checked"] == 1


def test_probe_python_missing_ruff_degrades_honestly(tmp_path):
    res = sp.probe_python_files(["x.py"], tmp_path,
                               run=_fake_run({}), which=lambda n: None)
    assert res["ok"] is None and res["reason"] == "no-ruff" and res["checked"] == 0


def test_probe_python_machinery_failure_is_not_run(tmp_path):
    # uv could not resolve ruff (non-JSON on stdout) → honest not-run, never a false green.
    run = _fake_run({"ruff": (False, "error: failed to resolve", "boom")})
    res = sp.probe_python_files(["x.py"], tmp_path, run=run, which=lambda n: "uv")
    assert res["ok"] is None and "ruff-could-not-run" in res["reason"]


def test_probe_python_no_files_is_vacuously_clean(tmp_path):
    res = sp.probe_python_files([], tmp_path, run=_fake_run({}), which=lambda n: None)
    assert res["ok"] is True and res["checked"] == 0


def test_parse_ruff_json_non_array_is_none():
    assert sp.parse_ruff_json("[]") == []
    assert sp.parse_ruff_json('[{"code":"F821"}]') == [{"code": "F821"}]
    assert sp.parse_ruff_json("") is None
    assert sp.parse_ruff_json('{"not": "array"}') is None
    assert sp.parse_ruff_json("error: boom") is None


# ---------------------------------------------------------------------------
# Node leg — parsing + missing-node degrade
# ---------------------------------------------------------------------------


def test_probe_node_names_syntax_error_line(tmp_path):
    stderr = ("C:/x/cli.js:12\n  const x = ;\n            ^\n\n"
              "SyntaxError: Unexpected token ';'\n    at checkSyntax\n")
    run = _fake_run({"--check": (False, "", stderr)})
    res = sp.probe_node_files(["cli.js"], tmp_path, run=run, which=lambda n: "node")
    assert res["ok"] is False
    e = res["errors"][0]
    assert e["path"] == "cli.js" and e["line"] == 12 and e["code"] == "syntax-error"
    assert "Unexpected token" in e["message"]


def test_probe_node_good_file_is_ok(tmp_path):
    run = _fake_run({"--check": (True, "", "")})
    res = sp.probe_node_files(["ok.mjs"], tmp_path, run=run, which=lambda n: "node")
    assert res["ok"] is True and res["checked"] == 1


def test_probe_node_missing_node_degrades(tmp_path):
    res = sp.probe_node_files(["x.js"], tmp_path, run=_fake_run({}), which=lambda n: None)
    assert res["ok"] is None and res["reason"] == "no-node"


# ---------------------------------------------------------------------------
# classify + orchestration + the #827 stamp vocabulary
# ---------------------------------------------------------------------------


def test_classify_files_splits_by_suffix():
    py, node = sp.classify_files(["a.py", "b.js", "c.mjs", "d.cjs", "e.md", "f.cs"])
    assert py == ["a.py"] and node == ["b.js", "c.mjs", "d.cjs"]


def test_run_static_pregate_stamp_clean(tmp_path):
    run = _fake_run({"ruff": (True, "[]", ""), "--check": (True, "", "")})
    res = sp.run_static_pregate(["a.py", "b.mjs"], tmp_path,
                                run=run, which=lambda n: n)
    assert res["ok"] is True and res["stamp"] == "clean" and res["checked"] == 2


def test_run_static_pregate_stamp_fail_names_errors(tmp_path):
    run = _fake_run({"ruff": (False, _ruff_f821(str(tmp_path / "a.py")), "")})
    res = sp.run_static_pregate(["a.py"], tmp_path, run=run, which=lambda n: "uv")
    assert res["ok"] is False and res["stamp"] == "fail"
    assert "F821" in res["evidence"]


def test_run_static_pregate_stamp_skipped_no_ruff(tmp_path):
    res = sp.run_static_pregate(["a.py"], tmp_path,
                                run=_fake_run({}), which=lambda n: None)
    assert res["ok"] is None and res["stamp"] == "skipped" and "no-ruff" in res["skipped"]


def test_run_static_pregate_error_wins_over_skip(tmp_path):
    # python leg degrades (no ruff) but node finds a real syntax error → FAIL dominates.
    stderr = "x.mjs:1\n^\nSyntaxError: bad\n"
    run = _fake_run({"--check": (False, "", stderr)})
    res = sp.run_static_pregate(
        ["a.py", "x.mjs"], tmp_path,
        run=run, which=lambda n: None if n in ("uv", "ruff") else "node")
    assert res["ok"] is False and res["stamp"] == "fail"


def test_format_fix_prompt_names_exact_errors_single_focus(tmp_path):
    errors = [
        {"summary": "cli.js:12 syntax-error: Unexpected token ';'"},
        {"summary": "main.py:2 F821: Undefined name `convertUnits`"},
    ]
    prompt = sp.format_fix_prompt(errors)
    assert "single focus" in prompt
    assert "cli.js:12 syntax-error: Unexpected token ';'" in prompt
    assert "main.py:2 F821: Undefined name `convertUnits`" in prompt
    # single-focus discipline: it forbids the coder from touching anything else.
    assert "do NOT refactor" in prompt


# ---------------------------------------------------------------------------
# REAL subprocess locks — the LIVE proof (guarded to SKIP off a warm dev box).
# ---------------------------------------------------------------------------


def _write(tmp_path: Path, name: str, text: str) -> str:
    (tmp_path / name).write_text(text, encoding="utf-8")
    return name


def test_real_ruff_catches_f821_and_style_passes_untouched(tmp_path):
    """LIVE taste-immunity lock: real ruff FAILS an undefined-name file and PASSES a
    style-only file (long line + unsorted imports). Skips when uv/ruff is unreachable."""
    if sp.resolve_ruff_argv() is None:
        pytest.skip("no uv/ruff on this box")
    _write(tmp_path, "f821.py", "def go():\n    return convertUnits(3)\n")
    _write(tmp_path, "style.py",
           "import sys\nimport os\nx=1\nLONG = " + '"' + "a" * 90 + '"' + "\n")
    # A planted coder ruff.toml that tries to ignore F821 must NOT save it (--isolated).
    (tmp_path / "ruff.toml").write_text('[lint]\nignore = ["F821"]\n', encoding="utf-8")
    bad = sp.probe_python_files(["f821.py"], tmp_path, run=sp._default_run)
    if bad["ok"] is None:
        pytest.skip(f"ruff could not run live: {bad['reason']}")
    assert bad["ok"] is False and bad["errors"][0]["code"] == "F821"
    good = sp.probe_python_files(["style.py"], tmp_path, run=sp._default_run)
    assert good["ok"] is True, f"style-only file must pass untouched, got {good['errors']}"


def test_real_node_check_catches_syntax_error(tmp_path):
    """LIVE node lock: real ``node --check`` fails a broken file, passes a good one."""
    import shutil
    if not shutil.which("node"):
        pytest.skip("no node on this box")
    _write(tmp_path, "bad.mjs", "export function go(){\n  const x = ;\n}\n")
    _write(tmp_path, "good.mjs", "export function go(){ return 1; }\n")
    bad = sp.probe_node_files(["bad.mjs"], tmp_path, run=sp._default_run)
    assert bad["ok"] is False and bad["errors"][0]["line"] == 2
    good = sp.probe_node_files(["good.mjs"], tmp_path, run=sp._default_run)
    assert good["ok"] is True


def test_cli_emits_verdict_json_and_exit_code(tmp_path):
    """The CLI (run-fleet's cheapest-first step could invoke it): a node syntax error →
    verdict JSON written + exit 1. Deterministic (node on PATH, no uv needed)."""
    import shutil
    if not shutil.which("node"):
        pytest.skip("no node on this box")
    _write(tmp_path, "bad.mjs", "export function go(){\n  const x = ;\n}\n")
    files_json = tmp_path / "files.json"
    files_json.write_text(json.dumps(["bad.mjs"]), encoding="utf-8")
    out = tmp_path / "verdict.json"
    proc = subprocess.run(
        [sys.executable, "-m", "shared.fleet.static_pregate",
         "--files", str(files_json), "--repo", str(tmp_path), "--out", str(out)],
        capture_output=True, text=True, cwd=str(_REPO_ROOT), timeout=120)
    assert proc.returncode == 1, proc.stderr
    verdict = json.loads(out.read_text(encoding="utf-8"))
    assert verdict["ok"] is False and verdict["stamp"] == "fail"


# ===========================================================================
# real_run_static_pregate (swap_ops seam) — git-diff + gate wiring (fake run)
# ===========================================================================


def _config(tmp_path: Path) -> FleetDispatchConfig:
    return FleetDispatchConfig(
        scripts_dir=tmp_path / "scripts",
        queue_path=tmp_path / "state" / "q.json",
        runs_dir=tmp_path / "state" / "runs",
        projects_dir=tmp_path / "projects",
    )


def _seam_run(diff_files: str, ruff_result=None, node_result=None):
    """Fake ``run`` for the seam: the git-diff cmd returns *diff_files*; ruff/node cmds
    return the given results."""
    def _run(cmd, timeout_s, cwd=None, env=None):
        joined = " ".join(str(c) for c in cmd)
        if "diff" in joined and "--name-only" in joined:
            return (True, diff_files, "")
        if "ruff" in joined:
            return ruff_result or (True, "[]", "")
        if "--check" in joined:
            return node_result or (True, "", "")
        return (True, "", "")
    return _run


def test_seam_diffs_gates_and_names_fix_prompt(tmp_path, monkeypatch):
    config = _config(tmp_path)
    repo = tmp_path / "proj"
    repo.mkdir()
    monkeypatch.setattr(sp.shutil, "which", lambda n: f"C:/fake/{n}.exe")
    run = _seam_run("src/cli.py\n",
                    ruff_result=(False, _ruff_f821("src/cli.py"), ""))
    res = so.real_run_static_pregate(config, "R1", str(repo), "a" * 12, "b" * 12, run=run)
    assert res["ok"] is False and res["stamp"] == "fail"
    assert "F821" in res["fix_prompt"] and "single focus" in res["fix_prompt"]
    # the #827 stamp is logged
    log = (config.runs_dir / "R1" / "static-pregate.log").read_text(encoding="utf-8")
    assert "static_pregate: fail" in log


def test_seam_clean_has_no_fix_prompt(tmp_path, monkeypatch):
    config = _config(tmp_path)
    repo = tmp_path / "proj"
    repo.mkdir()
    monkeypatch.setattr(sp.shutil, "which", lambda n: f"C:/fake/{n}.exe")
    res = so.real_run_static_pregate(config, "R1", str(repo), "a" * 12, "b" * 12,
                                     run=_seam_run("src/cli.py\n"))
    assert res["ok"] is True and res["stamp"] == "clean" and res["fix_prompt"] == ""


def test_seam_unreadable_refs_is_skipped(tmp_path):
    config = _config(tmp_path)
    repo = tmp_path / "proj"
    repo.mkdir()
    # empty / equal refs → could-not-run (never a git call needed)
    res = so.real_run_static_pregate(config, "R1", str(repo), "", "",
                                     run=_seam_run("x.py\n"))
    assert res["ok"] is None and res["stamp"] == "skipped" and "no-refs" in res["skipped"]
    res2 = so.real_run_static_pregate(config, "R1", str(repo), "abcd", "abcd",
                                      run=_seam_run("x.py\n"))
    assert res2["ok"] is None  # equal refs


def test_seam_no_source_in_merge_is_skipped(tmp_path):
    config = _config(tmp_path)
    repo = tmp_path / "proj"
    repo.mkdir()
    # the merge touched only docs/config → nothing statically checkable → honest skip
    res = so.real_run_static_pregate(config, "R1", str(repo), "a" * 12, "b" * 12,
                                     run=_seam_run("README.md\nconfig.toml\n"))
    assert res["ok"] is None and res["stamp"] == "skipped" and res["checked"] == 0


def test_seam_git_failure_is_skipped(tmp_path):
    config = _config(tmp_path)
    repo = tmp_path / "proj"
    repo.mkdir()

    def run(cmd, timeout_s, cwd=None, env=None):
        return (False, "", "fatal: bad object")  # git diff failed

    res = so.real_run_static_pregate(config, "R1", str(repo), "a" * 12, "b" * 12, run=run)
    assert res["ok"] is None and res["stamp"] == "skipped"
