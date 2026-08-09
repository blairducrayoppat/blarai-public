"""Gate: a module that redirects the app-data roots must not blind uv doing it.

WHY THIS GATE EXISTS — the same defect, found twice, three weeks apart.
----------------------------------------------------------------------
Isolating a grading subprocess means redirecting ``APPDATA`` / ``LOCALAPPDATA`` into a
throwaway dir, so a run can never touch the operator's real application data. That is
correct and stays. But uv keeps its managed CPython under ``%APPDATA%\\uv\\python`` and its
wheel cache under ``%LOCALAPPDATA%\\uv\\cache``, so the redirect ALSO hides uv's interpreter
from uv.

Nothing fails. uv falls back to whatever interpreter it can still find, whose site-packages
inject their own ``pytest11`` entry points; on this host pytest then dies during plugin load
before printing a single line. The grader reads empty output as a machinery miss and stamps
an honest-looking "cannot tell" — forever, on every invocation.

  * ``oracle_mutation`` (#1195 item 2): ``skipped-baseline-not-run`` on every audit.
  * ``oracle_qa``      (#1200):        ``collectability: unconfirmed`` on two banked nights,
    and the FAIL-TO-PASS baseline — the vacuous-pass gate — permanently ``not-run`` beside it.

Both were invisible for the same reason: every test injected a substitute runner, so
``uv`` was never on the path under test. The remedy now has ONE home
(``grade_env.uv_dir_overlay``) — and this gate is what stops a third module from redirecting
the roots without it, which is the exact way the second one happened.

WHAT THIS GATE DOES.
--------------------
AST-parses every production (non-test) module under ``shared/``, ``services/``,
``launcher/`` and ``tools/``, and finds every assignment writing ``APPDATA`` or
``LOCALAPPDATA`` into a dict (the redirect). Any module that does so AND builds a uv command
must also reference ``uv_dir_overlay``. Fails loudly naming the file
(security_by_design principles 2 deny-by-default + 11 fail-loud).

AST, not a regex, so the redirect MENTIONED in a docstring or comment is never miscounted —
this file's own prose says ``APPDATA`` many times and must not convict itself.

SCOPE (documented, bounded).
----------------------------
* Test files are EXCLUDED: a test legitimately builds a redirected env to assert what the
  production helper put in it.
* A module that redirects but never invokes uv is EXEMPT — it has no interpreter to lose.
  The pairing is the defect, not the redirect.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

SCANNED_DIRS = ("shared", "services", "launcher", "tools")

#: The env keys whose redirection hides uv's own directories.
APP_DATA_KEYS = frozenset({"APPDATA", "LOCALAPPDATA"})

#: The one shared remedy. A module may reference it directly or via the helper that wraps it.
REMEDY_NAMES = frozenset({"uv_dir_overlay", "_preserve_uv_dirs"})


def _production_modules() -> list[Path]:
    out: list[Path] = []
    for d in SCANNED_DIRS:
        for path in (REPO_ROOT / d).rglob("*.py"):
            parts = set(path.parts)
            if "tests" in parts or path.name.startswith("test_"):
                continue
            out.append(path)
    return out


def _redirects_app_data(tree: ast.AST) -> bool:
    """True iff the module ASSIGNS to ``<something>["APPDATA"|"LOCALAPPDATA"]``."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Subscript)
                and isinstance(target.slice, ast.Constant)
                and target.slice.value in APP_DATA_KEYS
            ):
                return True
    return False


def _invokes_uv(source: str) -> bool:
    """True iff the module builds a uv invocation. Deliberately coarse: over-inclusion costs
    a module one call to the shared remedy, under-inclusion costs a silent grader."""
    return '"uv"' in source or "'uv'" in source or 'which("uv")' in source


def _names_the_remedy(tree: ast.AST) -> bool:
    """True iff the module references the shared remedy, as a bare name or an attribute.

    Written as one intersection over the UNION of both node kinds. The first version of this
    read ``REMEDY_NAMES & names | attrs``, and ``&`` binds tighter than ``|`` — so it computed
    ``(REMEDY_NAMES ∩ names) ∪ attrs``, which is non-empty for any module doing
    ``dict(os.environ)`` because ``environ`` is an attribute. The guard was therefore always
    truthy and the gate convicted nothing, ever."""
    referenced = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    referenced |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    return bool(REMEDY_NAMES & referenced)


def find_offenders(paths: "list[Path]") -> list[str]:
    """THE COMPOSED GUARD — every filter in the order the gate applies them.

    A separate function so the proved-off test below can drive the WHOLE decision against a
    known offender. Testing the sub-predicates in isolation is what let the precedence bug
    above ship: each part was correct and the composition was not."""
    offenders: list[str] = []
    for path in paths:
        source = path.read_text(encoding="utf-8", errors="replace")
        if "APPDATA" not in source or not _invokes_uv(source):
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:  # pragma: no cover — a broken module fails its own suite
            continue
        if not _redirects_app_data(tree):
            continue
        if not _names_the_remedy(tree):
            offenders.append(path.name)
    return offenders


def test_no_module_hides_uv_from_itself():
    offenders = find_offenders(_production_modules())

    assert not offenders, (
        "these modules redirect APPDATA/LOCALAPPDATA and invoke uv, but never apply "
        f"grade_env.uv_dir_overlay: {offenders}. uv keeps its managed interpreter under "
        "%APPDATA%\\uv\\python — the redirect does not fail, it silently swaps the "
        "interpreter, and the grader reports 'cannot tell' forever (#1195, #1200)."
    )


#: A module with every property the gate exists to convict: it redirects BOTH app-data roots,
#: it grades through uv, and it never names the remedy. Written out as real source and parsed
#: by the real scanner, so the fixture is what production would look like rather than a shape
#: chosen to match the detector.
_OFFENDING_MODULE = (
    "import os, shutil, subprocess\n"
    "def grade(isolated_home):\n"
    "    env = dict(os.environ)\n"
    '    env["APPDATA"] = str(isolated_home)\n'
    '    env["LOCALAPPDATA"] = str(isolated_home)\n'
    '    uv = shutil.which("uv")\n'
    '    return subprocess.run([uv, "run", "--no-project", "python"], env=env)\n'
)


def test_the_gate_CONVICTS_a_real_offender(tmp_path):
    """Principle 12 — the composed guard proved OFF, against a whole module on disk.

    The earlier version of this test called ``_redirects_app_data`` directly and passed while
    the gate it guards convicted nothing, because the bug was in the composition rather than
    in any one predicate. A detector that cannot see a blatant offender is indistinguishable
    from a clean tree, which is the exact failure this gate exists to prevent elsewhere."""
    offender = tmp_path / "silently_unpinned_grader.py"
    offender.write_text(_OFFENDING_MODULE, encoding="utf-8")

    assert find_offenders([offender]) == ["silently_unpinned_grader.py"], (
        "the gate did not convict a module that redirects BOTH app-data roots, grades through "
        "uv, and never names the remedy. It is reporting a clean tree because it cannot see, "
        "which is the failure mode it exists to prevent in other instruments."
    )


def test_the_gate_ACQUITS_the_same_module_once_it_names_the_remedy(tmp_path):
    """The other half: the only change is applying the overlay. If this still convicted, the
    gate would be flagging every module and would be muted within a week."""
    fixed = tmp_path / "pinned_grader.py"
    fixed.write_text(
        _OFFENDING_MODULE.replace(
            "    env = dict(os.environ)\n",
            "    env = dict(os.environ)\n    env.update(grade_env.uv_dir_overlay(env))\n",
        ),
        encoding="utf-8",
    )

    assert find_offenders([fixed]) == [], (
        "the gate convicted a module that DOES apply the overlay — a control that flags "
        "healthy code gets muted, and is then worse than the silence it replaced"
    )


def test_the_gate_can_see_an_offender():
    """The sub-predicate lock, kept: prose naming APPDATA is not a redirect."""
    offending = ast.parse(
        "import os\n"
        "def build():\n"
        "    env = dict(os.environ)\n"
        '    env["APPDATA"] = "C:/iso"\n'
        "    return env\n"
    )
    assert _redirects_app_data(offending)

    innocent = ast.parse('"""A docstring naming APPDATA."""\nAPPDATA_NOTE = "APPDATA"\n')
    assert not _redirects_app_data(innocent)


def test_both_known_modules_are_covered_by_the_remedy():
    """The two that paid for this lesson stay pinned by name: a refactor that drops the
    remedy from either must fail here even if the scan above is later narrowed."""
    from shared.fleet import grade_env, oracle_mutation, oracle_qa

    for module in (oracle_qa, oracle_mutation):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "uv_dir_overlay" in source or "_preserve_uv_dirs" in source, (
            f"{module.__name__} redirects the app-data roots for isolation and grades with "
            "uv; without the overlay its verdict is produced by an interpreter nobody chose"
        )
    assert callable(grade_env.uv_dir_overlay)
