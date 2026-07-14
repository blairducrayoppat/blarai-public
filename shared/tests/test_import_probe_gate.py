"""#822 — layout/import-contract enforcement v2 + the clean-environment grading recipe.

Locks for the three-part hardening:
  * H1 — CLEAN-ENVIRONMENT GRADING: the job-oracle grade + the import probe run under a
    hermetic recipe (``--noconftest -c <clean.ini> -o addopts= --import-mode=importlib``,
    PYTHONPATH=<repo>, PYTHONSAFEPATH=1), so a coder conftest/pytest.ini cannot force the
    fixed oracle green. One SSOT (``grade_env``) shared by host grade, guest twin, probe,
    and #821 seed-QA; the guest redeclaration is host-locked equal.
  * H3/H3b/H4 — SYMBOL-LEVEL import probe: resolve every first-party module the oracle
    imports EXACTLY as the oracle will and getattr each named export, so an unresolved
    entry is NAMED (the B6n2 signal) instead of an opaque wave-final ModuleNotFoundError.
  * The named failure shapes: B6n2 (package-nested module), stub-module (resolves but
    export absent), B7n1 (node), conftest-in-tree (recipe ignores it), green-path.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from shared.fleet import grade_env
from shared.fleet import guest_oracle as go
from shared.fleet import import_probe as ip
from shared.fleet import swap_ops as so
from shared.fleet.acceptance import JOB_ORACLE_PATH_NODE, JOB_ORACLE_PATH_PYTHON
from shared.fleet.context_pack import extract_import_probe_targets
from shared.fleet.dispatch import FleetDispatchConfig

_PROBE_SCRIPT = Path(so.__file__).with_name("import_probe.py")


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


# ===========================================================================
# grade_env — the canonical recipe SSOT + the guest redeclaration parity lock
# ===========================================================================


def test_grade_env_recipe_shape():
    assert grade_env.clean_pytest_args("X.ini") == [
        "--noconftest", "-c", "X.ini", "-o", "addopts=", "--import-mode=importlib"]
    assert grade_env.clean_grade_env("/repo") == {
        "PYTHONPATH": "/repo", "PYTHONSAFEPATH": "1"}
    assert grade_env.CLEAN_GRADE_INI_CONTENT.startswith("[pytest]")
    assert "addopts =" in grade_env.CLEAN_GRADE_INI_CONTENT


def test_write_clean_grade_ini_is_harness_owned(tmp_path):
    ini = grade_env.write_clean_grade_ini(tmp_path / "runs" / "R1")
    assert ini.name == grade_env.CLEAN_GRADE_INI_FILENAME
    assert ini.read_text(encoding="utf-8") == grade_env.CLEAN_GRADE_INI_CONTENT


def test_guest_twin_redeclares_recipe_identically_drift_lock():
    """The guest ships stdlib-only so it REDECLARES the recipe; this host-side lock pins
    it EQUAL to grade_env so host grade + guest re-run can never grade with different
    recipes (which would let the #744 agreement matrix agree on a perturbed verdict).
    NOTE (integration): #821's oracle_qa.py seed-time F2P is the THIRD leg of this
    parity — when it merges, add ``oracle_qa`` here so seed==grade==guest is one lock."""
    assert go._CLEAN_GRADE_INI_CONTENT == grade_env.CLEAN_GRADE_INI_CONTENT
    assert go._CLEAN_GRADE_INI_FILENAME == grade_env.CLEAN_GRADE_INI_FILENAME
    assert go._clean_pytest_args("X.ini") == grade_env.clean_pytest_args("X.ini")
    assert go._clean_grade_env_overlay("/r") == grade_env.clean_grade_env("/r")
    # THIRD parity leg (#839): the #821 oracle-QA seed-time F2P recipe is the SAME grade_env
    # SSOT (imported, not redeclared), so seed == grade == guest is now ONE lock — a re-inlined
    # recipe drift in oracle_qa.py breaks this.
    from shared.fleet import oracle_qa as oq
    import tempfile
    with tempfile.TemporaryDirectory() as _td:
        oq_ini = oq._clean_ini(Path(_td))
        assert oq_ini.read_text(encoding="utf-8") == grade_env.CLEAN_GRADE_INI_CONTENT
        # the clean-recipe flags appear as a contiguous block in oracle_qa's invocation
        cmd = oq._pytest_cmd("oracle.py", oq_ini, collect_only=False)
        assert " ".join(grade_env.clean_pytest_args(oq_ini)) in " ".join(cmd)
    qa_env = oq._qa_env(Path("/isolated"), extra_path="/repo")
    overlay = grade_env.clean_grade_env("/repo")
    assert qa_env["PYTHONSAFEPATH"] == overlay["PYTHONSAFEPATH"]
    assert qa_env["PYTHONPATH"].split(os.pathsep)[0] == overlay["PYTHONPATH"]


# ===========================================================================
# extract_import_probe_targets — the STRUCTURED sibling of extract_import_contract
# ===========================================================================


def test_probe_targets_python_shapes():
    src = (
        "from main import main\n"
        "from card_manager import CardManager, Card\n"
        "import inventory_manager\n"
        "import a.b.c\n"
        "import pytest\n"                 # test framework — dropped
        "import os\n"                     # stdlib — dropped
        "from hypothesis import given\n"  # test framework — dropped
        "def test_x():\n    assert main()\n"
    )
    got = {(t["module"], tuple(t["names"])) for t in
           extract_import_probe_targets(JOB_ORACLE_PATH_PYTHON, src)}
    assert ("main", ("main",)) in got
    assert ("card_manager", ("CardManager", "Card")) in got
    assert ("inventory_manager", ()) in got
    assert ("a.b.c", ()) in got
    assert not any(m in ("pytest", "os", "hypothesis") for m, _ in got)


def test_probe_targets_relative_import_carries_level():
    tgts = extract_import_probe_targets(JOB_ORACLE_PATH_PYTHON, "from .helper import x\n")
    assert tgts and tgts[0]["level"] == 1 and tgts[0]["module"] == "helper"


def test_probe_targets_node_shapes():
    src = (
        "import test from 'node:test';\n"          # builtin — dropped
        "import assert from 'node:assert';\n"      # builtin — dropped
        "import { addExpense, listExpenses } from '../src/storage.mjs';\n"
        "import slug from './src/slugify.js';\n"   # default import -> 'default'
        "import * as util from './src/util.js';\n" # namespace -> no names
        "import './src/side-effect.js';\n"         # side-effect -> no names
        "const { load } = require('./src/db.js');\n"
        "test('x', () => {});\n"
    )
    got = {(t["spec"], tuple(t["names"])) for t in
           extract_import_probe_targets(JOB_ORACLE_PATH_NODE, src)}
    assert ("../src/storage.mjs", ("addExpense", "listExpenses")) in got
    assert ("./src/slugify.js", ("default",)) in got
    assert ("./src/util.js", ()) in got
    assert ("./src/side-effect.js", ()) in got
    assert ("./src/db.js", ("load",)) in got
    assert not any(s.startswith("node:") for s, _ in got)


def test_probe_targets_deterministic():
    src = "from cli import main\nimport inventory_manager\n"
    a = extract_import_probe_targets(JOB_ORACLE_PATH_PYTHON, src)
    b = extract_import_probe_targets(JOB_ORACLE_PATH_PYTHON, src)
    assert a == b


# ===========================================================================
# import_probe.py — the REAL python probe subprocess against fixture trees.
# These reproduce the exact taxonomy failure shapes (no uv/pytest needed —
# import_probe.py is pure-stdlib, run under the clean-env recipe).
# ===========================================================================


def _run_python_probe(repo: Path, targets: list[dict]) -> dict:
    tj = repo.parent / f"{repo.name}-targets.json"
    out = repo.parent / f"{repo.name}-out.json"
    tj.write_text(json.dumps(targets), encoding="utf-8")
    env = {**os.environ, **grade_env.clean_grade_env(str(repo))}
    cp = subprocess.run(
        [sys.executable, str(_PROBE_SCRIPT), "--targets", str(tj),
         "--repo", str(repo), "--out", str(out)],
        cwd=str(repo), capture_output=True, text=True, timeout=120, env=env,
    )
    verdict = json.loads(out.read_text(encoding="utf-8"))
    verdict["_exit"] = cp.returncode
    return verdict


def _py_targets() -> list[dict]:
    return [
        {"kind": "py", "module": "main", "level": 0, "names": ["main"],
         "raw": "from main import main"},
        {"kind": "py", "module": "cli_interface", "level": 0, "names": ["run_cli"],
         "raw": "from cli_interface import run_cli"},
    ]


def test_probe_b6n2_package_nested_module_named_unresolved(tmp_path):
    """B6n2: the coder built cli_interface INSIDE app/ while the oracle imports it
    top-level. The probe NAMES cli_interface as unresolved (the fix-cycle signal)."""
    repo = _mk_repo(tmp_path / "b6n2")
    (repo / "main.py").write_text("def main():\n    return 'ok'\n", encoding="utf-8")
    (repo / "app").mkdir()
    (repo / "app" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "app" / "cli_interface.py").write_text("def run_cli():\n    return 0\n", encoding="utf-8")
    v = _run_python_probe(repo, _py_targets())
    assert v["ok"] is False and v["_exit"] == 1
    names = {u["module"] for u in v["unresolved"]}
    assert names == {"cli_interface"}
    assert "does not resolve" in v["unresolved"][0]["reason"]


def test_probe_stub_module_resolves_but_export_absent_named(tmp_path):
    """The stub-module evasion (C1): cli_interface resolves but run_cli is absent.
    The probe getattrs each export and NAMES the missing one — closes 'import resolves
    so the layout is fine' as a false green."""
    repo = _mk_repo(tmp_path / "stub")
    (repo / "main.py").write_text("def main():\n    return 'ok'\n", encoding="utf-8")
    (repo / "cli_interface.py").write_text("X = 1  # no run_cli\n", encoding="utf-8")
    v = _run_python_probe(repo, _py_targets())
    assert v["ok"] is False and v["_exit"] == 1
    miss = v["unresolved"][0]
    assert miss["module"] == "cli_interface" and miss["name"] == "run_cli"
    assert "export 'run_cli' is absent" in miss["reason"]


def test_probe_green_path_all_resolve(tmp_path):
    repo = _mk_repo(tmp_path / "green")
    (repo / "main.py").write_text("def main():\n    return 'ok'\n", encoding="utf-8")
    (repo / "cli_interface.py").write_text("def run_cli():\n    return 0\n", encoding="utf-8")
    v = _run_python_probe(repo, _py_targets())
    assert v["ok"] is True and v["_exit"] == 0 and v["unresolved"] == []


def test_probe_relative_import_is_skipped_not_failed(tmp_path):
    repo = _mk_repo(tmp_path / "rel")
    v = _run_python_probe(repo, [
        {"kind": "py", "module": "helper", "level": 1, "names": ["x"],
         "raw": "from .helper import x"}])
    assert v["ok"] is True and v["skipped"] == 1 and v["probed"] == 0


# ===========================================================================
# CONFTEST-IN-TREE lock (real pytest) — the H1 linchpin proof: a coder conftest
# that force-passes the oracle is IGNORED under the clean recipe, but GAMES a
# bare `python -m pytest`. Uses the test env's own pytest (no uv, no skip).
# ===========================================================================


def _make_gamed_repo(repo: Path, *, correct: bool) -> None:
    """A repo whose oracle asserts compute()==42. The real compute returns 0 (a broken
    build) unless *correct*. A malicious conftest monkeypatches compute->42."""
    _mk_repo(repo)
    (repo / "calc.py").write_text(
        f"def compute():\n    return {42 if correct else 0}\n", encoding="utf-8")
    (repo / "tests").mkdir()
    # Attribute access (`calc.compute()`), so a conftest autouse fixture that patches
    # `calc.compute` actually reaches the value the assertion reads (a `from calc import
    # compute` binds the original at import and would dodge the patch — a weaker demo).
    (repo / "tests" / "test_job_acceptance.py").write_text(
        "import calc\n\n\ndef test_x():\n    assert calc.compute() == 42\n",
        encoding="utf-8")
    (repo / "conftest.py").write_text(
        "import pytest\nimport calc\n\n\n"
        "@pytest.fixture(autouse=True)\n"
        "def _force(monkeypatch):\n"
        "    monkeypatch.setattr(calc, 'compute', lambda: 42)\n",
        encoding="utf-8")


def _pytest_rc(repo: Path, *, clean: bool) -> int:
    oracle = JOB_ORACLE_PATH_PYTHON
    if clean:
        ini = grade_env.write_clean_grade_ini(repo / "_grade")
        cmd = [sys.executable, "-m", "pytest",
               *grade_env.clean_pytest_args(str(ini)), "-q", oracle]
        env = {**os.environ, **grade_env.clean_grade_env(str(repo))}
    else:
        cmd = [sys.executable, "-m", "pytest", "-q", oracle]
        env = {k: v for k, v in os.environ.items() if k != "PYTHONSAFEPATH"}
    cp = subprocess.run(cmd, cwd=str(repo), capture_output=True, text=True,
                        timeout=180, env=env)
    return cp.returncode


def test_conftest_in_tree_gamed_by_bare_pytest_but_ignored_by_clean_recipe(tmp_path):
    """The linchpin: a broken build + a force-pass conftest PASSES bare pytest (the
    vuln) and FAILS under the clean recipe (H1 closes it) — the conftest never loads."""
    repo = tmp_path / "gamed"
    _make_gamed_repo(repo, correct=False)
    assert _pytest_rc(repo, clean=False) == 0    # GAMED green (conftest forced the pass)
    assert _pytest_rc(repo, clean=True) != 0      # HONEST red (conftest ignored)


def test_clean_recipe_green_path_correct_build_still_passes(tmp_path):
    """Green-path: a CORRECT build passes under the clean recipe (the recipe does not
    introduce false-reds; first-party imports resolve via PYTHONPATH)."""
    repo = tmp_path / "correct"
    _make_gamed_repo(repo, correct=True)
    assert _pytest_rc(repo, clean=True) == 0


# ===========================================================================
# build_node_probe_script (pure) + the B7n1 node shape via the seam (fake run)
# ===========================================================================


def test_build_node_probe_script_embeds_targets_and_out_safely():
    targets = [{"kind": "node", "spec": "../src/x.mjs", "names": ["f"],
                "raw": "import { f } from '../src/x.mjs'"}]
    script = ip.build_node_probe_script(targets, "/tmp/o.json")
    assert "await import(t.spec)" in script and "writeFileSync" in script
    assert "../src/x.mjs" in script and "/tmp/o.json" in script
    # deterministic
    assert script == ip.build_node_probe_script(targets, "/tmp/o.json")


# ===========================================================================
# real_run_job_oracle — the GRADE-TIME clean-env recipe lock (fake run)
# ===========================================================================


def test_real_run_job_oracle_py_grade_uses_clean_env_recipe(tmp_path, monkeypatch):
    config = _config(tmp_path)
    repo = _mk_repo(tmp_path / "proj")
    monkeypatch.setattr(so.shutil, "which", lambda name: f"C:/fake/{name}.exe")
    seen: dict = {}

    def fake_run(cmd, timeout_s, cwd=None, env=None):
        seen.update(cmd=list(cmd), cwd=cwd, env=env)
        return (True, "1 passed", "")

    res = so.real_run_job_oracle(config, "R1", str(repo), JOB_ORACLE_PATH_PYTHON,
                                 "def test():\n    assert True\n", run=fake_run)
    assert res["status"] == "passed"
    cmd = seen["cmd"]
    assert "--noconftest" in cmd and "--import-mode=importlib" in cmd
    assert "-c" in cmd and "-o" in cmd and "addopts=" in cmd
    assert seen["env"]["PYTHONSAFEPATH"] == "1"
    assert seen["env"]["PYTHONPATH"] == str(repo)
    assert seen["cwd"] == str(repo)
    # the clean.ini is HARNESS-OWNED (the run dir), never under the coder's repo tree.
    ini = cmd[cmd.index("-c") + 1]
    assert grade_env.CLEAN_GRADE_INI_FILENAME in ini
    assert str(repo) not in ini


# ===========================================================================
# real_run_import_probe — seam wiring (fake run writes the verdict file)
# ===========================================================================


def _fake_probe_run(verdict: dict):
    def _run(cmd, timeout_s, cwd=None, env=None):
        out = cmd[cmd.index("--out") + 1]
        Path(out).write_text(json.dumps(verdict), encoding="utf-8")
        return (bool(verdict.get("ok")), "import-probe: ran", "")
    return _run


def test_real_run_import_probe_py_unresolved_names_entry(tmp_path, monkeypatch):
    config = _config(tmp_path)
    repo = _mk_repo(tmp_path / "proj")
    monkeypatch.setattr(so.shutil, "which", lambda name: f"C:/fake/{name}.exe")
    oracle = "from cli_interface import run_cli\ndef test():\n    assert run_cli() == 0\n"
    verdict = {"ok": False, "probed": 1, "unresolved": [
        {"raw": "from cli_interface import run_cli", "module": "cli_interface",
         "reason": "module 'cli_interface' does not resolve from the repo root"}]}
    seen: dict = {}

    def fake_run(cmd, timeout_s, cwd=None, env=None):
        seen.update(cmd=list(cmd), env=env)
        return _fake_probe_run(verdict)(cmd, timeout_s, cwd, env)

    res = so.real_run_import_probe(config, "R1", str(repo), JOB_ORACLE_PATH_PYTHON,
                                   oracle, run=fake_run)
    assert res["ok"] is False
    assert any("cli_interface" in str(u.get("raw", "")) for u in res["unresolved"])
    # the probe runs under the SAME clean env as the grade (H4 interpreter/env parity).
    assert seen["env"]["PYTHONSAFEPATH"] == "1" and seen["env"]["PYTHONPATH"] == str(repo)
    assert any("import_probe.py" in str(c) for c in seen["cmd"])


def test_real_run_import_probe_py_all_resolve(tmp_path, monkeypatch):
    config = _config(tmp_path)
    repo = _mk_repo(tmp_path / "proj")
    monkeypatch.setattr(so.shutil, "which", lambda name: f"C:/fake/{name}.exe")
    res = so.real_run_import_probe(
        config, "R1", str(repo), JOB_ORACLE_PATH_PYTHON,
        "from cli import main\ndef test():\n    assert main()\n",
        run=_fake_probe_run({"ok": True, "unresolved": [], "probed": 1}))
    assert res["ok"] is True and res["unresolved"] == []


def test_real_run_import_probe_node_b7n1_shape(tmp_path, monkeypatch):
    """B7n1 (node twin): the oracle imports a `src/…` module the coder didn't place.
    Wiring lock — a canned ERR_MODULE_NOT_FOUND verdict names the exact spec."""
    config = _config(tmp_path)
    repo = _mk_repo(tmp_path / "web")
    (repo / "tests").mkdir()
    monkeypatch.setattr(so.shutil, "which", lambda name: f"C:/fake/{name}.exe")
    oracle = ("import test from 'node:test';\n"
              "import slug from '../src/slugify-phrase.js';\n"
              "test('x', () => {});\n")
    verdict = {"ok": False, "unresolved": [
        {"raw": "import slug from '../src/slugify-phrase.js'",
         "spec": "../src/slugify-phrase.js",
         "reason": "specifier '../src/slugify-phrase.js' does not resolve (ERR_MODULE_NOT_FOUND)"}]}
    # The node cmd is `[node, <probe.mjs>]` — the verdict path lives INSIDE the generated
    # script, so the fake writes to the known run-dir verdict path (not a `--out` arg).
    out_json = config.runs_dir / "R1" / "import-probe-verdict.json"

    def fake_node_run(cmd, timeout_s, cwd=None, env=None):
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(verdict), encoding="utf-8")
        return (False, "", "")

    res = so.real_run_import_probe(config, "R1", str(repo), JOB_ORACLE_PATH_NODE,
                                   oracle, run=fake_node_run)
    assert res["ok"] is False
    assert any("slugify-phrase.js" in str(u.get("spec", "")) for u in res["unresolved"])
    # the transient node probe file is cleaned up (host tree left as the merges made it).
    assert not (repo / "tests" / so._NODE_IMPORT_PROBE_NAME).exists()


def test_real_run_import_probe_no_contract_is_not_run(tmp_path):
    config = _config(tmp_path)
    repo = _mk_repo(tmp_path / "proj")
    # an oracle with NO first-party imports -> nothing to probe -> honest ok=None
    res = so.real_run_import_probe(config, "R1", str(repo), JOB_ORACLE_PATH_PYTHON,
                                   "import os\ndef test():\n    assert True\n",
                                   run=_fake_probe_run({"ok": True}))
    assert res["ok"] is None and "no first-party import contract" in res["evidence"]


def test_real_run_import_probe_missing_verdict_is_not_run(tmp_path, monkeypatch):
    """A probe that writes no verdict (crash / no --out) is an honest ok=None, never a
    false green nor a false red."""
    config = _config(tmp_path)
    repo = _mk_repo(tmp_path / "proj")
    monkeypatch.setattr(so.shutil, "which", lambda name: f"C:/fake/{name}.exe")
    res = so.real_run_import_probe(
        config, "R1", str(repo), JOB_ORACLE_PATH_PYTHON,
        "from cli import main\ndef test():\n    assert True\n",
        run=lambda cmd, t, cwd=None, env=None: (False, "", "boom"))  # writes no --out file
    assert res["ok"] is None


# ===========================================================================
# #826 — the SIGNATURE layer: each contract callable must accept the arity the
# oracle CALLS it with (the built-wrong-signature B4n2 delta, over #822's name
# resolution). Real import_probe.py subprocess against fixture trees.
# ===========================================================================


def _sig_targets(min_pos, max_pos, *, keywords=(), starargs=False, starkwargs=False):
    return [{"kind": "py", "module": "flashcards", "level": 0,
             "names": ["check_answer"], "raw": "from flashcards import check_answer",
             "signatures": [{"name": "check_answer", "min_positional": min_pos,
                             "max_positional": max_pos, "keywords": list(keywords),
                             "starargs": starargs, "starkwargs": starkwargs}]}]


def test_probe_b4n2_wrong_signature_named(tmp_path):
    """B4n2 GATE half: the oracle calls ``check_answer('cat', 'cat')`` (2 positional) but
    the coder built a one-argument ``check_answer``. The name RESOLVES (H3 green) — the
    probe NAMES the exact arity delta so the coder gets one targeted fix cycle instead of
    a wave-final assertion park."""
    repo = _mk_repo(tmp_path / "b4n2")
    (repo / "flashcards.py").write_text(
        "def check_answer(question):\n    return True\n", encoding="utf-8")
    v = _run_python_probe(repo, _sig_targets(2, 2))
    assert v["ok"] is False and v["_exit"] == 1
    miss = v["unresolved"][0]
    assert miss["module"] == "flashcards" and miss["name"] == "check_answer"
    assert "cannot accept" in miss["reason"]


def test_probe_arity_green_when_signature_accepts(tmp_path):
    """Green path: a matching 2-arg build resolves clean — the arity check adds no
    false-red for a correct signature."""
    repo = _mk_repo(tmp_path / "ok")
    (repo / "flashcards.py").write_text(
        "def check_answer(a, b):\n    return 'correct'\n", encoding="utf-8")
    v = _run_python_probe(repo, _sig_targets(2, 2))
    assert v["ok"] is True and v["unresolved"] == []


def test_probe_keyword_not_accepted_named(tmp_path):
    """A keyword the oracle passes that the built signature cannot accept is a named
    delta (no such parameter and no **kwargs)."""
    repo = _mk_repo(tmp_path / "kw")
    (repo / "flashcards.py").write_text(
        "def check_answer(a):\n    return True\n", encoding="utf-8")
    v = _run_python_probe(repo, _sig_targets(1, 1, keywords=("mode",)))
    assert v["ok"] is False
    assert "cannot accept" in v["unresolved"][0]["reason"]


def test_probe_non_callable_export_named(tmp_path):
    """An export the oracle CALLS that resolves to a non-callable is named (the coder
    built a constant where a function was contracted)."""
    repo = _mk_repo(tmp_path / "notcall")
    (repo / "flashcards.py").write_text("check_answer = 42\n", encoding="utf-8")
    v = _run_python_probe(repo, _sig_targets(2, 2))
    assert v["ok"] is False
    assert "not callable" in v["unresolved"][0]["reason"]


def test_probe_starargs_relaxes_no_false_red(tmp_path):
    """Precision-first: an oracle ``check_answer(*xs)`` call is under-determined, so a real
    2-arg build must NOT be flagged (the positional count is unsound to falsify)."""
    repo = _mk_repo(tmp_path / "star")
    (repo / "flashcards.py").write_text(
        "def check_answer(a, b):\n    return True\n", encoding="utf-8")
    v = _run_python_probe(repo, _sig_targets(0, 0, starargs=True))
    assert v["ok"] is True


def test_probe_uninspectable_callable_is_not_red(tmp_path):
    """A callable whose signature cannot be introspected (a builtin re-export) is a skip,
    never a false red — the sound signal is a concrete bind TypeError only."""
    repo = _mk_repo(tmp_path / "builtin")
    (repo / "flashcards.py").write_text("check_answer = len\n", encoding="utf-8")
    v = _run_python_probe(repo, _sig_targets(2, 2))
    # len's signature (obj, /) actually rejects 2 positionals → named; use a truly opaque one.
    (repo / "flashcards.py").write_text(
        "import functools\ncheck_answer = functools.partial(print)\n", encoding="utf-8")
    v2 = _run_python_probe(repo, _sig_targets(2, 2))
    assert v2["ok"] is True  # partial is not introspected into a false red


def test_probe_arity_end_to_end_via_extract_targets(tmp_path):
    """The FULL host path: ``extract_import_probe_targets`` DERIVES the signatures from the
    oracle and the probe enforces them — the coder's one-arg ``check_answer`` is named
    against the 2-arg oracle with no hand-built target."""
    oracle = ("from flashcards import check_answer\n\n"
              "def test_quiz():\n    assert check_answer('cat', 'cat') == 'correct'\n")
    targets = extract_import_probe_targets(JOB_ORACLE_PATH_PYTHON, oracle)
    assert targets[0]["signatures"][0]["max_positional"] == 2
    repo = _mk_repo(tmp_path / "e2e")
    (repo / "flashcards.py").write_text(
        "def check_answer(q):\n    return True\n", encoding="utf-8")
    v = _run_python_probe(repo, targets)
    assert v["ok"] is False
    assert any(u.get("name") == "check_answer" and "cannot accept" in u["reason"]
               for u in v["unresolved"])


def test_probe_import_module_attribute_arity(tmp_path):
    """The ``import m; m.f(...)`` shape: the module resolves and ``f`` (not in ``names``)
    is still arity-checked via its derived signature entry."""
    oracle = ("import inventory\n\n"
              "def test_x():\n    inventory.add_item('w', 5)\n")
    targets = extract_import_probe_targets(JOB_ORACLE_PATH_PYTHON, oracle)
    repo = _mk_repo(tmp_path / "attr")
    (repo / "inventory.py").write_text("def add_item(name):\n    return 1\n", encoding="utf-8")
    v = _run_python_probe(repo, targets)
    assert v["ok"] is False
    assert any(u.get("name") == "add_item" for u in v["unresolved"])


def test_probe_signatures_backward_compatible_targets(tmp_path):
    """A target with NO ``signatures`` key (a pre-#826 caller) probes exactly as before —
    the arity layer is additive."""
    repo = _mk_repo(tmp_path / "compat")
    (repo / "cli_interface.py").write_text("def run_cli():\n    return 0\n", encoding="utf-8")
    (repo / "main.py").write_text("def main():\n    return 'ok'\n", encoding="utf-8")
    v = _run_python_probe(repo, _py_targets())  # no signatures key
    assert v["ok"] is True and v["unresolved"] == []


# ===========================================================================
# #826 node twin — the export/require surface: a resolved contract callable must
# BE a function (typeof); arity via fn.length is unreliable, so only typeof fires.
# ===========================================================================


def test_node_probe_script_checks_callables():
    targets = [{"kind": "node", "spec": "../src/x.mjs", "names": ["run"],
                "callables": ["run"], "raw": "import { run } from '../src/x.mjs'"}]
    script = ip.build_node_probe_script(targets, "/tmp/o.json")
    assert "typeof val !== 'function'" in script
    assert "t.callables" in script
    # deterministic
    assert script == ip.build_node_probe_script(targets, "/tmp/o.json")


def test_node_probe_targets_mark_called_names():
    src = ("import { addExpense, TAX } from '../src/storage.mjs';\n"
           "test('x', () => { addExpense(3); if (TAX) {} });\n")
    tgts = extract_import_probe_targets(JOB_ORACLE_PATH_NODE, src)
    t = next(t for t in tgts if t["spec"] == "../src/storage.mjs")
    # addExpense is CALLED → a callable; TAX is only read → not marked (no false typeof red).
    assert t.get("callables") == ["addExpense"]
