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
    so the four flags + the harness ``-c`` are byte-identical everywhere."""
    return [
        "--noconftest",
        "-c",
        str(ini_path),
        "-o",
        "addopts=",
        "--import-mode=importlib",
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


def write_clean_grade_ini(dir_path: "str | Path") -> Path:
    """Write :data:`CLEAN_GRADE_INI_CONTENT` to ``<dir_path>/grade-clean.ini`` (a
    HARNESS-OWNED directory — the run dir on the host, the extract root in the guest)
    and return its path. Idempotent; the caller passes the returned path to ``-c``."""
    base = Path(dir_path)
    base.mkdir(parents=True, exist_ok=True)
    ini = base / CLEAN_GRADE_INI_FILENAME
    ini.write_text(CLEAN_GRADE_INI_CONTENT, encoding="utf-8")
    return ini
