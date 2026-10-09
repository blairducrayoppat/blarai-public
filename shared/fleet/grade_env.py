"""The canonical CLEAN-ENVIRONMENT grading recipe (#822 H1) — one SSOT so the host
grader, the guest twin, the symbol-level import probe, and the seed-time oracle QA
(#821) all grade in the SAME hermetic environment and can never drift into agreeing
on a perturbed verdict.

**Why this exists (the linchpin, r3adversary §1).** The job-acceptance oracle is
SEEDED into the coder's tree readable (#748), so a reward-hacking coder that reads the
exact asserted inputs/outputs holds one half of an evasion. The other half is the
GRADER'S EXECUTION ENVIRONMENT, which the coder owns: `real_run_job_oracle` used to
grade with a bare ``python -m pytest`` at ``cwd=<coder's integrated tree>``, so pytest
discovered and executed the coder's ``conftest.py`` / read the coder's
``pytest.ini`` / ``pyproject [tool.pytest]`` / ``tox.ini`` around the fixed oracle — an
autouse fixture or a ``sys.modules`` shim in a coder conftest could make the protected
oracle exit 0 with no real implementation, and NOTHING downstream caught it (the
FALSE-DONE cross-check reads ``oracle_status`` + rigs; the #744 guest re-ran the SAME
gamed tree; the #827 classifier only inspects non-GREEN cards). restore-before-grade
protects the oracle FILE; it does not protect the oracle's ENVIRONMENT.

**The recipe** denies the coder's tree any influence over the grader's process while
still giving the (self-contained-by-template) oracle its first-party imports:

  python -m pytest --noconftest -c <harness clean.ini> -o addopts= \
      --import-mode=importlib -q <oracle>
  env: PYTHONPATH=<repo>  PYTHONSAFEPATH=1

  * ``--noconftest``            no ``conftest.py`` (coder autouse fixtures / hooks
                               / ``sys.modules`` shims never load);
  * ``-c <clean.ini>``         config comes from a HARNESS-OWNED file, so the coder's
                               ``pytest.ini`` / ``pyproject [tool.pytest]`` / ``tox.ini``
                               / ``setup.cfg`` are ignored (discovery is bypassed);
  * ``-o addopts=``            belt-and-suspenders: no injected plugins / args;
  * ``--import-mode=importlib`` the test module is imported by path, not by inserting
                               a coder-controlled rootdir onto ``sys.path``;
  * ``PYTHONSAFEPATH=1``       Python does NOT auto-prepend the cwd / the script dir to
                               ``sys.path`` (denies a cwd-shadow of stdlib/first-party);
  * ``PYTHONPATH=<repo>``      the ONE first-party path the oracle needs — its
                               ``from cli import main`` resolves the coder's real module
                               at the repo root, and ONLY there.

Live-verified (2026-07-11): a malicious ``conftest.py`` that shims a missing module is
IGNORED under this recipe (the B6n2 package-nested import still fails, exit 2), while a
bare ``python -m pytest`` IS gamed green by the same conftest.

GUEST NOTE: ``guest_oracle.py`` ships to the NIC-less Alpine guest and must stay
stdlib + shared.ipc at module scope, so it REDECLARES the recipe (the
``JOB_ORACLE_ALLOWED_PATHS`` precedent) and a host-side lock pins it equal to this
module (``test_import_probe_gate.py``). Host grader / probe / #821 seed-QA import THIS
module directly — one canonical recipe, drift-locked.
"""

from __future__ import annotations

import os
from pathlib import Path

#: Filename of the harness-owned pytest config, written into a harness-owned dir
#: (never the coder's tree) and passed via ``-c``.
CLEAN_GRADE_INI_FILENAME = "grade-clean.ini"

#: The clean pytest config bytes. Deliberately minimal: an empty ``[pytest]`` with an
#: emptied ``addopts`` — enough that ``-c`` bypasses discovery of the coder's config
#: without importing any plugin or setting any testpath/marker the coder controls.
CLEAN_GRADE_INI_CONTENT = (
    "[pytest]\n"
    "# BlarAI grader clean config (#822 H1) — harness-owned, passed via `-c` so the\n"
    "# coder's pytest.ini / pyproject [tool.pytest] / tox.ini / setup.cfg cannot\n"
    "# influence the grade. Paired with --noconftest, -o addopts=,\n"
    "# --import-mode=importlib, PYTHONSAFEPATH=1, and an explicit PYTHONPATH=<repo>.\n"
    "addopts =\n"
)


def clean_pytest_args(ini_path: "str | Path") -> list[str]:
    """The pytest flags of the clean-env recipe (order-stable, regression-locked).

    Prepended to ``-q <oracle>`` by every grader (host, guest, probe, #821 seed-QA)
    so the flags + the harness ``-c`` are byte-identical everywhere.

    ``--color=no`` IS A CORRECTNESS FLAG, NOT COSMETICS (#1200, 2026-08-15). Every consumer
    of these runs reads the output as TEXT — ``_passed_tests`` matches ``<file>::<name>
    PASSED`` per test, ``_run_completed`` looks for pytest's summary. Coloured output puts
    an escape sequence between the test name and ``PASSED``, so both matchers miss, and the
    F2P baseline — the check that convicts an oracle passing with NO implementation present
    — returns ``not-run`` instead of ``vacuous:<test>``. Measured, not reasoned: with
    ``FORCE_COLOR=3`` in the parent environment the identical call stamped ``not-run``; with
    it cleared, ``vacuous:test_always_green`` with a hard finding.

    pytest colours on a TTY *or* when the environment forces it, and any agent harness, CI
    runner or terminal multiplexer may set ``FORCE_COLOR``. The nightly battery does not,
    which is why this never showed up there — a latent blind spot that fires only where the
    parent happens to be colourful, and fails toward the innocent-looking stamp. Pinning the
    flag is deterministic; scrubbing the environment alone would leave the next colour
    variable to rediscover this."""
    return [
        "--noconftest",
        "-c",
        str(ini_path),
        "-o",
        "addopts=",
        "--import-mode=importlib",
        "--color=no",
    ]


def clean_grade_env(repo_root: "str | Path") -> dict[str, str]:
    """The env OVERLAY of the clean-env recipe: ``PYTHONPATH=<repo>`` (the oracle's
    only first-party path) + ``PYTHONSAFEPATH=1`` (deny the cwd/script-dir auto-path).

    An OVERLAY the caller merges over its base environment (``{**base, **overlay}``) —
    ``PYTHONPATH`` is REPLACED, not extended, so the grader sees the target repo and
    nothing the harness happened to carry (e.g. the BlarAI checkout)."""
    return {"PYTHONPATH": str(repo_root), "PYTHONSAFEPATH": "1"}


def clean_grade_environ(repo_root: "str | Path", base: "dict[str, str] | None" = None) -> dict[str, str]:
    """The FULL subprocess environment for a clean grade: *base* (defaults to the
    current ``os.environ``) with :func:`clean_grade_env` merged over it. For callers
    that pass a complete ``env=`` to ``subprocess.run`` rather than an overlay."""
    merged = dict(os.environ if base is None else base)
    merged.update(clean_grade_env(repo_root))
    return merged


#: uv's own directories, and the environment variable that overrides each:
#: ``(override_var, app_data_root_var, subpath)``. Both live UNDER an app-data root, so a
#: caller that redirects those roots for isolation hides uv's managed interpreter and its
#: wheel cache from it — see :func:`uv_dir_overlay`.
UV_DIR_OVERRIDES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("UV_PYTHON_INSTALL_DIR", "APPDATA", ("uv", "python")),
    ("UV_CACHE_DIR", "LOCALAPPDATA", ("uv", "cache")),
)


def uv_dir_overlay(base: "dict[str, str] | None" = None) -> dict[str, str]:
    """The env OVERLAY that keeps uv's managed interpreter + wheel cache reachable for a
    caller that redirects ``APPDATA`` / ``LOCALAPPDATA`` into an isolated dir.

    uv keeps its managed CPython under ``%APPDATA%\\uv\\python`` and its wheel cache under
    ``%LOCALAPPDATA%\\uv\\cache``. Redirecting those roots does not make uv FAIL — it makes
    uv silently fall back to whatever interpreter it can still find, whose site-packages
    inject their own ``pytest11`` entry points. Pytest can then die during plugin load,
    before it prints anything at all, and a grader reading that empty output cannot tell a
    broken runner from a defective oracle. That defeats the whole point of pinning the
    runner: a verdict reached here only predicts the verdict at grade time if both ran on
    the same interpreter.

    An OVERLAY the caller merges over its base environment BEFORE the redirect
    (``env.update(uv_dir_overlay(env))``). A variable *base* already sets is left alone (an
    explicit override always wins), and a directory that is not on disk is omitted rather
    than invented, so uv falls back to its own defaults rather than to a path we made up.
    Locations are resolved from the LIVE environment, never hardcoded — a fixed absolute
    path would survive a reboot perfectly and follow the operator nowhere.

    Avoidance alone is not a control: on a host where the root variables are unset this
    overlay is empty and uv falls back exactly as before. Callers must therefore still be
    able to DETECT a runner that did not run (see ``oracle_qa.confirm_collectable``'s
    ``not-run`` stamp), never infer a result from silence.

    The interpreter directory is pinned only when it actually HOLDS one — see
    :func:`_has_managed_interpreter`. Exporting a variable at an empty directory would be a
    path uv ignores on its way to the fallback, i.e. not a pin, and it would manufacture
    exactly the state :func:`uv_parity_is_vouched` exists to catch. The cache directory is
    pinned on presence alone: a cold cache costs a wheel fetch, never a different
    interpreter."""
    src = os.environ if base is None else base
    overlay: dict[str, str] = {}
    for var, root, parts in UV_DIR_OVERRIDES:
        if src.get(var):
            continue
        base_dir = os.environ.get(root)
        if not base_dir:
            continue
        real = Path(base_dir).joinpath(*parts)
        usable = (_has_managed_interpreter(real) if var == "UV_PYTHON_INSTALL_DIR"
                  else real.is_dir())
        if usable:
            overlay[var] = str(real)
    return overlay


def _has_managed_interpreter(directory: "str | Path | None") -> bool:
    """Whether *directory* actually CONTAINS a uv-managed interpreter.

    The question every caller here needs, and NOT the one ``Path.is_dir()`` answers. uv lays
    its managed pythons out as ``<root>/cpython-<version>-<platform>/python.exe``, and an
    empty-but-present ``<root>`` is a directory uv looks in, finds nothing in, and abandons
    for the system interpreter. Measured 2026-07-31: pinning ``UV_PYTHON_INSTALL_DIR`` at an
    existing empty directory resolves ``sys._base_executable`` to ``C:\\Python314\\python.exe``
    — the exact contaminated interpreter #1200 exists because of — while a presence check
    reports the pin healthy. (``sys.executable`` shows uv's ephemeral build venv, which is
    what makes this easy to miss.)"""
    if not directory:
        return False
    root = Path(directory)
    try:
        if not root.is_dir():
            return False
        for child in root.iterdir():
            if not child.is_dir() or child.name.startswith("."):
                continue
            if (child / "python.exe").is_file() or (child / "bin" / "python3").is_file():
                return True
    except OSError:
        return False
    return False


def _native_managed_root() -> "str | None":
    """Where uv looks for managed interpreters with NO redirect applied — an explicit operator
    override if there is one, else uv's own default under the real app-data root."""
    explicit = os.environ.get("UV_PYTHON_INSTALL_DIR")
    if explicit:
        return explicit
    base = os.environ.get("APPDATA")
    return str(Path(base).joinpath("uv", "python")) if base else None


def uv_parity_is_vouched(env: "dict[str, str]") -> bool:
    """Whether the interpreter uv resolves under *env* is the one it would resolve natively.

    The companion to :func:`uv_dir_overlay`, and the reason avoidance alone is not a control.
    The overlay can silently produce nothing — a root variable unset, a permissions error, a
    uv release that relocates the directory — and where the fallback happens to WORK, a result
    is true about what it measured and silently false about grade parity: the same defect the
    redirect caused, wearing the remedy's uniform.

    Asks about PARITY, not about pinning, because those come apart in BOTH directions and an
    earlier presence-check version of this got both wrong (measured 2026-07-31):

    * a host with no managed interpreter at all loses nothing to the redirect — uv resolves
      the same system python at probe time and at grade time — so parity holds, and firing
      there would convict an honest run on every invocation, forever;
    * a pin at an existing but EMPTY directory loses everything, because uv abandons it for
      the system interpreter, while looking perfectly healthy to a presence check.

    So: if uv would not have used a managed interpreter anyway there is no parity to lose and
    this is vouched. Otherwise the env must actually reach one."""
    if not _has_managed_interpreter(_native_managed_root()):
        return True
    return _has_managed_interpreter(env.get("UV_PYTHON_INSTALL_DIR"))


def runner_is_uv(cmd: "list[str]") -> bool:
    """Whether *cmd* grades through uv (vs. the current-interpreter fallback). Parity is a
    uv property; a command that never invokes uv has no uv pin to lose."""
    return bool(cmd) and Path(cmd[0]).stem.lower() == "uv"


def write_clean_grade_ini(dir_path: "str | Path") -> Path:
    """Write :data:`CLEAN_GRADE_INI_CONTENT` to ``<dir_path>/grade-clean.ini`` (a
    HARNESS-OWNED directory — the run dir on the host, the extract root in the guest)
    and return its path. Idempotent; the caller passes the returned path to ``-c``."""
    base = Path(dir_path)
    base.mkdir(parents=True, exist_ok=True)
    ini = base / CLEAN_GRADE_INI_FILENAME
    ini.write_text(CLEAN_GRADE_INI_CONTENT, encoding="utf-8")
    return ini
