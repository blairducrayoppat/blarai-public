"""#837 Layer 1 — the deterministic GREEN-audit floor (near-free, no model).

This layer alone would have caught the B2 regression the r4greens dossier found: three
GREEN nights of one job, quality sliding, scoreboard flat. It is grep-and-diff cheap and
ecosystem-agnostic where it can be.

Two kinds of signal:

* **The archetype-regression probe** — the control that catches §1.2 of the dossier. The
  battery archives every GREEN's repo (``repos-archived/``). At battery close, for each
  GREEN, run a small STORED real-input probe-set through the deliverable's public surface
  and DIFF the output against the LAST ARCHIVED GREEN of the same job id. A behavior change
  on a stored probe → advisory ``REGRESSED`` naming the input and both outputs. For B2 the
  probe-set is five real-prose strings through ``tokenize``; night-over-night it screams
  ``['worry']`` vs ``["don't",'worry',"it's",'well-known']``. Deterministic, seconds, no GPU.
* **Craft lints** — one-line deterministic checks that map 1:1 to the dossier's §1.3
  findings: does the shipped repo still contain the seed scaffold placeholder? is the
  README still the skeleton? for a library/CLI surface, is there ANY runnable entry point?
  plus an advisory ``ruff`` pass (soft signal — a missing tool skips, never fails).

Every effect (the probe subprocess, ruff) is bounded + fail-soft: a probe that cannot run,
a repo that cannot be found, a missing linter — each degrades the finding to "could not
determine", never a crash and never a gate. The layer is ADVISORY, like everything in this
package.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Sequence

# ---------------------------------------------------------------------------
# Timeouts (REGISTERED — shared/timeout_registry.py; a new timeout registers in the same
# change or the discovery lock fails). Both bound an advisory subprocess over SANDBOX
# archived code; on expiry the finding is honest ("could-not-run"), never a false flag.
# ---------------------------------------------------------------------------

#: One probe invocation — imports the coder's first-party module and calls a public
#: function on a handful of tiny inputs. Seconds normally; the bound is the abort ceiling
#: on an import-time side effect (a while-True / a blocking call in generated code). Same
#: class + value as #822's IMPORT_PROBE_TIMEOUT_S (both import first-party modules).
GREEN_QUALITY_PROBE_TIMEOUT_S: float = 120.0

#: One advisory ``ruff check`` over the shipped repo. Ruff is fast; the bound covers a cold
#: process start. Missing ruff / a timeout → the lint is SKIPPED (soft signal), never a fail.
GREEN_QUALITY_RUFF_TIMEOUT_S: float = 60.0

# ---------------------------------------------------------------------------
# Probe-set config (ships beside the battery, keyed by job id — the frozen cards stay
# pristine; a job with no probe-set simply skips the regression probe)
# ---------------------------------------------------------------------------

PROBE_SET_SCHEMA = "green-quality-probes/v1"

#: A single probe descriptor kind. ``python-callable`` imports a module and calls an attr
#: on each input (the python-lib shape B2 needs); ``argv-stdout`` runs an argv per input and
#: captures stdout (the ecosystem-agnostic CLI/node shape). The framework is surface-neutral;
#: the descriptor names how to invoke this job's public surface.
PROBE_KIND_PYTHON_CALLABLE = "python-callable"
PROBE_KIND_ARGV_STDOUT = "argv-stdout"
PROBE_KINDS: frozenset[str] = frozenset({PROBE_KIND_PYTHON_CALLABLE, PROBE_KIND_ARGV_STDOUT})

#: Per-invocation stdout read ceiling (a probe output beyond this is not a token list —
#: it is noise; bounded so a pathological deliverable never floods battery close).
_PROBE_OUTPUT_CAP = 8 * 1024


@dataclass(frozen=True)
class Probe:
    """One invocation descriptor for a job's public surface (see the two PROBE_KINDs)."""

    kind: str
    inputs: tuple[str, ...]
    #: python-callable: the module to import + the attribute to call.
    module: str = ""
    attr: str = ""
    #: argv-stdout: the argv template; ``{input}`` tokens are replaced per input, and if no
    #: token appears the input is fed on stdin.
    argv: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProbeSet:
    """The stored real-input probe-set for one job archetype."""

    job_id: str
    surface: str
    probes: tuple[Probe, ...]


def parse_probe_set(data: dict) -> Optional[ProbeSet]:
    """Build a :class:`ProbeSet` from a probe-config dict, or ``None`` if malformed
    (fail-soft: a broken probe-set skips the regression probe, never crashes the audit)."""
    if not isinstance(data, dict) or data.get("schema") != PROBE_SET_SCHEMA:
        return None
    job_id = str(data.get("job_id", "")).strip()
    if not job_id:
        return None
    probes: list[Probe] = []
    for raw in data.get("probes") or []:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("kind", ""))
        if kind not in PROBE_KINDS:
            continue
        inputs = tuple(str(i) for i in (raw.get("inputs") or []) if isinstance(i, (str, int, float)))
        if not inputs:
            continue
        probes.append(Probe(
            kind=kind,
            inputs=inputs,
            module=str(raw.get("import", "") or raw.get("module", "")),
            attr=str(raw.get("attr", "")),
            argv=tuple(str(a) for a in (raw.get("argv") or [])),
        ))
    if not probes:
        return None
    return ProbeSet(job_id=job_id, surface=str(data.get("surface", "")), probes=tuple(probes))


def load_probe_set(job_id: str, probe_dir: Path) -> Optional[ProbeSet]:
    """Load ``<probe_dir>/<job_id>.json`` as a :class:`ProbeSet`, or ``None`` (absent /
    unreadable / malformed — the regression probe is then simply skipped for this job)."""
    path = Path(probe_dir) / f"{job_id}.json"
    try:
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return parse_probe_set(data)


# ---------------------------------------------------------------------------
# The probe executor (injectable — tests pass a fake; the seed proof runs the real one)
# ---------------------------------------------------------------------------

#: The stdin harness that runs a python-callable probe INSIDE the archived repo: insert the
#: repo at sys.path[0], import the module, call the attr on each JSON input, and print one
#: JSON array of results. Run in a child interpreter so an import-time side effect in
#: generated code cannot touch battery close. ``default=str`` keeps a non-JSON return
#: serialisable (advisory — we only need a stable string to diff).
_PYCALL_HARNESS = (
    "import sys, json\n"
    "repo, mod, attr = sys.argv[1], sys.argv[2], sys.argv[3]\n"
    "inputs = json.loads(sys.argv[4])\n"
    "sys.path.insert(0, repo)\n"
    "out = []\n"
    "try:\n"
    "    m = __import__(mod, fromlist=[attr])\n"
    "    fn = getattr(m, attr)\n"
    "except Exception as exc:\n"
    "    print(json.dumps({'error': 'import: ' + type(exc).__name__ + ': ' + str(exc)[:200]}))\n"
    "    sys.exit(0)\n"
    "for i in inputs:\n"
    "    try:\n"
    "        out.append({'ok': True, 'value': json.dumps(fn(i), default=str, sort_keys=True)})\n"
    "    except Exception as exc:\n"
    "        out.append({'ok': False, 'value': type(exc).__name__ + ': ' + str(exc)[:200]})\n"
    "print(json.dumps({'results': out}))\n"
)


def run_probe(
    repo: Path,
    probe: Probe,
    *,
    timeout_s: float = GREEN_QUALITY_PROBE_TIMEOUT_S,
    python_exe: str = "",
) -> list[str]:
    """Run one probe against *repo* and return one output-string PER input (the value the
    diff compares), or a single ``"could-not-run: <why>"`` sentinel list on any failure.

    Fail-soft by construction: an unimportable module, a timeout, a crashed child — each
    yields the sentinel, never an exception. The outputs are opaque strings; the archetype
    diff only needs them to be STABLE across two archives of the same code."""
    exe = python_exe or sys.executable
    try:
        if probe.kind == PROBE_KIND_PYTHON_CALLABLE:
            cmd = [exe, "-I", "-c", _PYCALL_HARNESS, str(repo), probe.module, probe.attr,
                   json.dumps(list(probe.inputs))]
            cp = subprocess.run(  # noqa: S603 — constant harness, vector argv, no shell
                cmd, capture_output=True, text=True, timeout=timeout_s, cwd=str(repo),
            )
            raw = (cp.stdout or "")[-_PROBE_OUTPUT_CAP:]
            payload = json.loads(raw.strip().splitlines()[-1]) if raw.strip() else {}
            if "error" in payload:
                return [f"could-not-run: {payload['error']}"]
            results = payload.get("results") or []
            return [str(r.get("value", "")) for r in results if isinstance(r, dict)]
        if probe.kind == PROBE_KIND_ARGV_STDOUT:
            outputs: list[str] = []
            for inp in probe.inputs:
                argv = [a.replace("{input}", inp) for a in probe.argv]
                uses_token = any("{input}" in a for a in probe.argv)
                cp = subprocess.run(  # noqa: S603 — descriptor argv, no shell
                    argv, capture_output=True, text=True, timeout=timeout_s, cwd=str(repo),
                    input=None if uses_token else inp,
                )
                outputs.append((cp.stdout or "")[-_PROBE_OUTPUT_CAP:].strip())
            return outputs
    except (subprocess.TimeoutExpired, OSError, ValueError) as exc:
        return [f"could-not-run: {type(exc).__name__}"]
    return ["could-not-run: unknown probe kind"]


ProbeRunner = Callable[[Path, Probe], list[str]]


# ---------------------------------------------------------------------------
# The archetype-regression diff (the B2 catch)
# ---------------------------------------------------------------------------


#: A behaviour change is a REGRESSION (C-level data loss), not merely a lateral change
#: (B-level), when the current output MATERIALLY SHRANK — a domain-agnostic proxy for
#: "lost information". Concretely: current is empty where the reference was not, or current
#: is <= this fraction of the reference's size. For B2 the 07-11 GREEN collapses
#: ``["dont","worry","its","well","known"]`` (41 chars) to ``["worry"]`` (9 chars) — a 0.22
#: ratio, a regression; the 07-07->07-09 contraction reformat stays same-size — a change.
_MATERIAL_SHRINK_RATIO = 0.5


def _is_material_shrink(current: str, reference: str) -> bool:
    """True iff *current* lost material content vs *reference* (the data-loss proxy)."""
    ref_len = len(reference)
    if ref_len == 0:
        return False
    if len(current) == 0:
        return True
    return (len(current) / ref_len) <= _MATERIAL_SHRINK_RATIO


@dataclass(frozen=True)
class RegressionFinding:
    """The archetype-regression result for one GREEN vs its last archived GREEN.

    Two severity levels (both advisory): ``changed`` == the observable behaviour differs
    from the last GREEN on some probe input (worth the operator's eyes — leniency DRIFT);
    ``regressed`` == a change that also LOST material output (the C-level data-loss shape —
    B2's ``4->1 tokens``). ``regressed`` implies ``changed``."""

    #: A change that lost material output (data-loss) — the C-level signal.
    regressed: bool
    #: Any observable behaviour change vs the last GREEN — the B-level drift signal.
    changed: bool
    #: A no-newline, capped human detail (the sharpest differing input + both outputs), or a
    #: status ("no-reference GREEN to diff against" / "probe could not run") when not run.
    detail: str
    #: Whether a reference GREEN + a runnable probe were both available (so a caller can tell
    #: "clean" apart from "not-measured").
    measured: bool = False


def _diff_probe(
    current_repo: Path,
    reference_repo: Path,
    probe: Probe,
    run: ProbeRunner,
) -> tuple[bool, list[tuple[str, str, str]]]:
    """``(comparable, diffs)`` — whether the probe produced comparable output on BOTH sides,
    and the list of ``(input, current, reference)`` where they differ. A probe that
    could-not-run on either side is not comparable (we never claim a change we could not
    measure — honest silence)."""
    cur = run(current_repo, probe)
    ref = run(reference_repo, probe)
    if any(o.startswith("could-not-run") for o in cur + ref) or len(cur) != len(ref):
        return (False, [])
    diffs = [(inp, c, r) for inp, c, r in zip(probe.inputs, cur, ref) if c != r]
    return (True, diffs)


def archetype_regression(
    current_repo: Path,
    reference_repo: Optional[Path],
    probe_set: Optional[ProbeSet],
    *,
    run: ProbeRunner = run_probe,
) -> RegressionFinding:
    """Diff *current_repo*'s observable behaviour against *reference_repo* (the last archived
    GREEN of the same job) over *probe_set*. The heart of Layer 1 — for B2 it flags the
    07-11 tokenizer dropping contractions the 07-09 GREEN preserved (a data-loss regression),
    and distinguishes it from the earlier lateral contraction reformat (a mere change)."""
    if probe_set is None:
        return RegressionFinding(False, False, "no probe-set for this job (regression probe skipped)")
    if reference_repo is None or not Path(reference_repo).is_dir():
        return RegressionFinding(False, False, "no-reference GREEN to diff against (first GREEN of this job)")
    if not Path(current_repo).is_dir():
        return RegressionFinding(False, False, "current repo not found (regression probe skipped)")
    measured_any = False
    change_detail = ""
    regression_detail = ""
    for probe in probe_set.probes:
        comparable, diffs = _diff_probe(Path(current_repo), Path(reference_repo), probe, run)
        if comparable:
            measured_any = True
        for inp, cur, ref in diffs:
            line = f"input {inp!r}: now {cur[:80]} vs was {ref[:80]} (last GREEN)"
            if not change_detail:
                change_detail = line
            if _is_material_shrink(cur, ref) and not regression_detail:
                regression_detail = line
    if not measured_any:
        return RegressionFinding(False, False, "probe could not run on this archetype", measured=False)
    if regression_detail:
        return RegressionFinding(True, True, regression_detail, measured=True)
    if change_detail:
        return RegressionFinding(False, True, change_detail, measured=True)
    return RegressionFinding(False, False, "no behaviour change vs the last archived GREEN", measured=True)


# ---------------------------------------------------------------------------
# Reference-GREEN finder (scan the sibling night archives for the last GREEN)
# ---------------------------------------------------------------------------

_SCORECARD_GREEN_RE = re.compile(r'"verdict"\s*:\s*"GREEN"')


def _night_scored_green(night_dir: Path, job_id: str) -> bool:
    """True iff *night_dir* carries a GREEN scorecard for *job_id* (either layout: a
    ``scorecards/`` subdir or a flat ``<id>.scorecard.json`` — both exist across history)."""
    for cand in (night_dir / "scorecards" / f"{job_id}.scorecard.json",
                 night_dir / f"{job_id}.scorecard.json"):
        try:
            if cand.is_file() and _SCORECARD_GREEN_RE.search(
                cand.read_text(encoding="utf-8", errors="replace")
            ):
                return True
        except OSError:
            continue
    return False


def find_reference_green(
    archive_root: Optional[Path],
    job_id: str,
    repo_slug: str,
    *,
    exclude_night: Optional[Path] = None,
) -> Optional[Path]:
    """The archived repo of the most-recent PRIOR GREEN of *job_id*, or ``None``.

    Scans ``<archive_root>/*/`` (the dated battery-run roots sort chronologically), keeps
    only nights strictly OLDER than *exclude_night* (the current run) that scored *job_id*
    GREEN AND still carry ``repos-archived/<repo_slug>/``, and returns the newest such repo
    path. Fail-soft → ``None`` (no reference → the regression probe reports 'first GREEN')."""
    if not archive_root:
        return None
    root = Path(archive_root)
    try:
        if not root.is_dir():
            return None
        nights = sorted(p for p in root.iterdir() if p.is_dir())
    except OSError:
        return None
    exclude_name = Path(exclude_night).name if exclude_night else None
    best: Optional[Path] = None
    for night in nights:
        if exclude_name is not None and night.name >= exclude_name:
            # Only PRIOR nights are a valid reference (name sorts chronologically).
            continue
        repo = night / "repos-archived" / repo_slug
        if repo.is_dir() and _night_scored_green(night, job_id):
            best = repo  # keep walking; the LAST (newest) prior GREEN wins
    return best


# ---------------------------------------------------------------------------
# Craft lints (map 1:1 to the dossier §1.3 findings — one deterministic check each)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CraftFinding:
    """One deterministic craft lint result (advisory)."""

    #: True == the smell is present (dead scaffold / stale README / no entry point).
    flagged: bool
    detail: str


#: The seed skeleton's placeholder marker (``core.py`` docstring literally says PLACEHOLDER)
#: and the skeleton README's own phrase — both ship UNCHANGED in a repo nobody did an
#: integration-cleanup pass on (exactly the B2 finding). Bounded read; fail-soft.
_SCAFFOLD_MARKERS = ("PLACEHOLDER", "placeholder so the project builds")
_README_SKELETON_MARKERS = ("project skeleton", "the fleet seeds", "A minimal, clean, offline Python project")
_LINT_READ_CAP = 64 * 1024
#: Surfaces for which a non-coder is entitled to a runnable entry point.
_RUNNABLE_SURFACES = ("python-lib", "python-cli", "command-line", "library", "node", "node-cli")


def _read_capped(path: Path) -> str:
    try:
        if path.is_file():
            return path.read_text(encoding="utf-8", errors="replace")[:_LINT_READ_CAP]
    except OSError:
        pass
    return ""


def lint_dead_scaffold(repo: Path) -> CraftFinding:
    """Does the shipped repo still carry the seed scaffold placeholder? (An unremoved
    ``core.py`` PLACEHOLDER in a text-stats toolkit is the 'no integration cleanup' smell.)"""
    try:
        files = list(Path(repo).rglob("*.py"))[:400] if Path(repo).is_dir() else []
    except OSError:
        files = []
    for f in files:
        text = _read_capped(f)
        if any(m in text for m in _SCAFFOLD_MARKERS):
            try:
                rel = f.relative_to(repo)
            except ValueError:
                rel = f
            return CraftFinding(True, f"seed scaffold placeholder still shipped in {rel}")
    return CraftFinding(False, "no seed scaffold placeholder found")


def lint_stale_readme(repo: Path) -> CraftFinding:
    """Is the shipped README still the fleet skeleton's own readme (never replaced with a
    description of the actual deliverable)?"""
    for name in ("README.md", "README.rst", "README.txt", "README"):
        text = _read_capped(Path(repo) / name)
        if text and any(m in text for m in _README_SKELETON_MARKERS):
            return CraftFinding(True, f"{name} is still the fleet skeleton readme (never replaced)")
    return CraftFinding(False, "README is not the skeleton default")


#: The DISCOVERABLE runnable-entry filenames a non-coder could plausibly find + run.
#: A buried ``if __name__ == "__main__"`` demo block inside an arbitrary module is NOT
#: discoverable (the dossier §1.4: the 07-11 B2 GREEN "ships no CLI, no demo.py, no __main__
#: entry — the only way to use it is to write Python"), so we deliberately do NOT count it.
_RUNNABLE_ENTRY_NAMES = ("demo.py", "run.py", "cli.py", "main.py", "__main__.py")


def lint_no_entry_point(repo: Path, surface: str) -> CraftFinding:
    """For a library/CLI surface, is there a DISCOVERABLE runnable entry a non-coder can
    invoke — a ``demo.py``/``run.py``/``cli.py``/``main.py``, a ``__main__.py`` (so
    ``python -m pkg`` works), a ``bin/``, or a declared console-script? A buried per-module
    ``if __name__`` demo does NOT count (undiscoverable). Skipped (never flagged) for a
    GUI/web surface, where 'open it and look' is the entry."""
    surf = str(surface or "").strip().lower()
    if surf and surf not in _RUNNABLE_SURFACES:
        return CraftFinding(False, f"surface '{surf}' is not entry-point-graded (GUI/web opens itself)")
    root = Path(repo)
    if not root.is_dir():
        return CraftFinding(False, "repo not found (entry-point lint skipped)")
    try:
        named_entry = any(
            p.name in _RUNNABLE_ENTRY_NAMES
            for p in list(root.rglob("*.py"))[:800]
        )
    except OSError:
        named_entry = False
    bin_dir = (root / "bin").is_dir()
    console_script = "console_scripts" in _read_capped(root / "pyproject.toml") or \
        "console_scripts" in _read_capped(root / "setup.cfg") or \
        "project.scripts" in _read_capped(root / "pyproject.toml") or \
        '"bin"' in _read_capped(root / "package.json")
    if named_entry or bin_dir or console_script:
        return CraftFinding(False, "a runnable entry point is present")
    return CraftFinding(True, "no runnable entry point for a non-coder (no demo/__main__/bin/console-script)")


def run_ruff_advisory(repo: Path, *, timeout_s: float = GREEN_QUALITY_RUFF_TIMEOUT_S) -> Optional[int]:
    """Advisory ``ruff check`` finding-count over *repo* (a SOFT band input), or ``None``
    when ruff is absent / errored / timed out (skipped, never a fail — the dossier's
    'turn ruff on as advisory'). Counts JSON diagnostics; never raises."""
    try:
        cp = subprocess.run(  # noqa: S603 — constant argv, no shell
            ["ruff", "check", "--output-format", "json", "."],
            capture_output=True, text=True, timeout=timeout_s, cwd=str(repo),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    try:
        diagnostics = json.loads(cp.stdout or "[]")
        return len(diagnostics) if isinstance(diagnostics, list) else None
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Layer-1 aggregate
# ---------------------------------------------------------------------------


@dataclass
class Layer1Result:
    """Every deterministic finding for one GREEN (advisory — feeds the band formula + card)."""

    regression: RegressionFinding
    dead_scaffold: CraftFinding
    stale_readme: CraftFinding
    no_entry_point: CraftFinding
    ruff_findings: Optional[int] = None
    surface: str = ""

    @property
    def any_craft_residue(self) -> bool:
        return self.dead_scaffold.flagged or self.stale_readme.flagged or self.no_entry_point.flagged

    def findings(self) -> list[str]:
        """The human finding lines (only the flagged ones — the honest report)."""
        out: list[str] = []
        if self.regression.regressed:
            out.append(f"REGRESSED (data loss) — {self.regression.detail}")
        elif self.regression.changed:
            out.append(f"behaviour changed vs last GREEN — {self.regression.detail}")
        for f in (self.dead_scaffold, self.stale_readme, self.no_entry_point):
            if f.flagged:
                out.append(f.detail)
        if self.ruff_findings:
            out.append(f"ruff: {self.ruff_findings} advisory finding(s)")
        return out


def audit_layer1(
    current_repo: Path,
    reference_repo: Optional[Path],
    probe_set: Optional[ProbeSet],
    *,
    surface: str = "",
    run: ProbeRunner = run_probe,
    ruff: Callable[[Path], Optional[int]] = run_ruff_advisory,
) -> Layer1Result:
    """Run the whole deterministic floor over one GREEN's repo. Pure orchestration — every
    sub-check is fail-soft, so a missing repo yields an all-clean (unmeasured) result rather
    than a crash. ``run``/``ruff`` are injected so tests need no real subprocess."""
    surf = surface or (probe_set.surface if probe_set else "")
    return Layer1Result(
        regression=archetype_regression(current_repo, reference_repo, probe_set, run=run),
        dead_scaffold=lint_dead_scaffold(current_repo),
        stale_readme=lint_stale_readme(current_repo),
        no_entry_point=lint_no_entry_point(current_repo, surf),
        ruff_findings=ruff(current_repo),
        surface=surf,
    )
