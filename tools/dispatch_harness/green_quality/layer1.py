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
* **The seed-divergence check** — the RELATIONAL craft check: is a delivered file still the
  file it was copied from? A lint keyed on a string can be edited into silence, and one was:
  #1142 neutralised the seed README's text, so its markers vanished from the seed AND from
  the untouched copy that ships, and ``lint_stale_readme`` began reading clean on the exact
  file it exists to catch. Comparing the delivery against its SEED cannot be silenced that
  way — the delivered file is a copy, so editing the seed moves both sides at once.

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
import tomllib
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
                encoding="utf-8", errors="replace",
            )
            raw = (cp.stdout or "")[-_PROBE_OUTPUT_CAP:]
            # SILENCE IS NOT A MEASUREMENT (#1269). _PYCALL_HARNESS prints a JSON object on
            # EVERY path it can reach — including its own import failure — so empty stdout
            # means the child never reached a print at all: killed, SystemExit at import
            # (BaseException, so the harness's `except Exception` cannot catch it), or a
            # decode that produced nothing. Returning [] here made two silent probes
            # "comparable" in _diff_probe and minted measured=True with "no behaviour
            # change" — a verdict about code nobody ran.
            if not raw.strip():
                return [f"could-not-run: probe produced no output (rc={cp.returncode})"]
            payload = json.loads(raw.strip().splitlines()[-1])
            if "error" in payload:
                return [f"could-not-run: {payload['error']}"]
            results = payload.get("results") or []
            # The harness emits exactly one result per input. Fewer means it died partway,
            # and a short list would silently compare a prefix against a full run.
            if len(results) != len(probe.inputs):
                return [
                    "could-not-run: probe returned "
                    f"{len(results)} results for {len(probe.inputs)} inputs"
                ]
            return [str(r.get("value", "")) for r in results if isinstance(r, dict)]
        if probe.kind == PROBE_KIND_ARGV_STDOUT:
            outputs: list[str] = []
            for inp in probe.inputs:
                argv = [a.replace("{input}", inp) for a in probe.argv]
                uses_token = any("{input}" in a for a in probe.argv)
                cp = subprocess.run(  # noqa: S603 — descriptor argv, no shell
                    argv, capture_output=True, text=True, timeout=timeout_s, cwd=str(repo),
                    input=None if uses_token else inp,
                    # The deliverable's OWN stdout — arbitrary LLM-authored text, where a
                    # smart quote under cp1252 makes cp.stdout None. 47193a5e guarded the
                    # ruff site and left this one, and this is the site that feeds the
                    # regression verdict (#1269 / #1272).
                    encoding="utf-8", errors="replace",
                )
                # A crashed run that printed nothing is not the empty string — that is the
                # argv-side of the same silence. A program that legitimately prints nothing
                # AND exits 0 is still a real, comparable observation, so the rc is what
                # separates them.
                if cp.returncode != 0 and not (cp.stdout or "").strip():
                    return [
                        f"could-not-run: {argv[0]} exited {cp.returncode} with no output"
                    ]
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
    # SECOND, INDEPENDENT LOCK (#1269). run_probe now returns the sentinel rather than an
    # empty list, so this should be unreachable — which is exactly why it is here. The
    # original defect was that BOTH guards below are vacuously satisfied by two empty
    # lists: any() over an empty sequence is False, and 0 != 0 is False. A future runner
    # (or a stubbed one in a test) that returns [] must not be able to mint a measurement,
    # and no amount of care at the other end of the call is a substitute for the check.
    if not cur or not ref:
        return (False, [])
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
    """One deterministic craft lint result (advisory).

    ``measured`` is the honesty bit, and it defaults to False so a finding assembled without
    running the lint reads as ignorance rather than as a pass. Before it existed, every one
    of these lints answered an unreadable tree with ``flagged=False`` and a detail sentence
    that read like a clean result — the #1183 shape, where a lint that went blind was
    indistinguishable from a lint that looked and found nothing.

    ``flagged`` and ``measured`` are INDEPENDENT, on the same reasoning
    :class:`~tools.dispatch_harness.green_quality.security.SecurityResult` gives: a lint can
    find its marker in the first file it reads and then fail on the second, so
    ``measured=False`` means "there may be more", never "disregard what was found"."""

    #: True == the smell is present (dead scaffold / stale README / no entry point).
    flagged: bool
    detail: str
    #: Whether the lint could actually look. False == the tree (or the file it needed) could
    #: not be read, so ``flagged=False`` says nothing about the deliverable.
    measured: bool = False


#: The seed skeleton's placeholder marker (``core.py`` docstring literally says PLACEHOLDER)
#: and the skeleton README's own phrase — both ship UNCHANGED in a repo nobody did an
#: integration-cleanup pass on (exactly the B2 finding). Bounded read; fail-soft.
_SCAFFOLD_MARKERS = ("PLACEHOLDER", "placeholder so the project builds")
_README_SKELETON_MARKERS = ("project skeleton", "the fleet seeds", "A minimal, clean, offline Python project")
_LINT_READ_CAP = 64 * 1024
#: Surfaces for which a non-coder is entitled to a runnable entry point.
_RUNNABLE_SURFACES = ("python-lib", "python-cli", "command-line", "library", "node", "node-cli")


def _read_capped(path: Path) -> str:
    """One capped file, or ``""`` for both an absent file and an unreadable one. Callers that
    must tell those apart use :func:`_read_capped_status`."""
    return _read_capped_status(path)[0]


def _read_capped_status(path: Path) -> tuple[str, bool]:
    """``(text, readable)`` — the same capped read, with the fact of a read ERROR kept.

    An ABSENT file is readable (its absence is an answer this lint can act on); a file that
    exists and raises is NOT, and collapsing the two is how a blind lint reports clean."""
    try:
        if path.is_file():
            return (path.read_text(encoding="utf-8", errors="replace")[:_LINT_READ_CAP], True)
        return ("", True)
    except OSError:
        return ("", False)


def lint_dead_scaffold(repo: Path) -> CraftFinding:
    """Does the shipped repo still carry the seed scaffold placeholder? (An unremoved
    ``core.py`` PLACEHOLDER in a text-stats toolkit is the 'no integration cleanup' smell.)

    A tree that cannot be walked, or whose files cannot be read, returns ``measured=False``:
    "no placeholder found" is a claim about the deliverable and an unreadable tree supports
    no claim about it."""
    root = Path(repo)
    try:
        if not root.is_dir():
            return CraftFinding(False, f"repo not found at {root.name} (scaffold lint could not run)")
        files = list(root.rglob("*.py"))[:400]
    except OSError as exc:
        return CraftFinding(False, f"repo could not be walked ({type(exc).__name__})")
    unreadable = 0
    for f in files:
        text, readable = _read_capped_status(f)
        if not readable:
            unreadable += 1
            continue
        if any(m in text for m in _SCAFFOLD_MARKERS):
            try:
                rel = f.relative_to(repo)
            except ValueError:
                rel = f
            return CraftFinding(True, f"seed scaffold placeholder still shipped in {rel}",
                                measured=True)
    if unreadable and unreadable == len(files):
        return CraftFinding(False, f"none of the {unreadable} python file(s) could be read")
    detail = "no seed scaffold placeholder found"
    if unreadable:
        # Partial coverage, NAMED. A bound the reader cannot see is a bound that becomes a
        # false clean — the same rule the security scan applies to its skipped trees.
        detail += f" ({unreadable} file(s) unreadable, so coverage is partial)"
    return CraftFinding(False, detail, measured=True)


def lint_stale_readme(repo: Path) -> CraftFinding:
    """Is the shipped README still the fleet skeleton's own readme (never replaced with a
    description of the actual deliverable)?

    #1183 IS this lint's sibling: a marker-string check that went blind when the marker left
    the seed, and reported clean for a week because nothing distinguished "looked and found
    no marker" from "could not look". A repo that is not there, or a README that exists and
    cannot be read, is therefore ``measured=False``. A repo with NO README is measured — the
    absence is itself the answer to the question asked."""
    root = Path(repo)
    try:
        if not root.is_dir():
            return CraftFinding(False, f"repo not found at {root.name} (README lint could not run)")
    except OSError as exc:
        return CraftFinding(False, f"repo unreadable ({type(exc).__name__})")
    unreadable: list[str] = []
    for name in ("README.md", "README.rst", "README.txt", "README"):
        text, readable = _read_capped_status(root / name)
        if not readable:
            unreadable.append(name)
            continue
        if text and any(m in text for m in _README_SKELETON_MARKERS):
            return CraftFinding(True, f"{name} is still the fleet skeleton readme (never replaced)",
                                measured=True)
    if unreadable:
        return CraftFinding(False, f"README present but unreadable ({', '.join(unreadable)})")
    return CraftFinding(False, "README is not the skeleton default", measured=True)


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
        # MEASURED, not skipped: the lint asked its question of this surface and the answer
        # is "does not apply". That is a result, unlike the unreadable-tree cases below.
        return CraftFinding(False, f"surface '{surf}' is not entry-point-graded (GUI/web opens itself)",
                            measured=True)
    root = Path(repo)
    if not root.is_dir():
        return CraftFinding(False, f"repo not found at {root.name} (entry-point lint could not run)")
    try:
        named_entry = any(
            p.name in _RUNNABLE_ENTRY_NAMES
            for p in list(root.rglob("*.py"))[:800]
        )
    except OSError as exc:
        # The walk is the whole evidence for the commonest entry-point shape. Swallowing the
        # error and carrying on produced "no runnable entry point" — an ACCUSATION derived
        # from a failed read, which is the false-alarm mirror of the same defect.
        return CraftFinding(False, f"repo could not be walked ({type(exc).__name__})")
    bin_dir = (root / "bin").is_dir()
    pyproject, py_ok = _read_capped_status(root / "pyproject.toml")
    setup_cfg, cfg_ok = _read_capped_status(root / "setup.cfg")
    package_json, pkg_ok = _read_capped_status(root / "package.json")
    console_script = ("console_scripts" in pyproject or "console_scripts" in setup_cfg
                      or "project.scripts" in pyproject or '"bin"' in package_json)
    if named_entry or bin_dir or console_script:
        return CraftFinding(False, "a runnable entry point is present", measured=True)
    if not (py_ok and cfg_ok and pkg_ok):
        # No entry point FOUND, but a manifest that could declare one was unreadable — so the
        # flag would be an accusation the evidence does not carry.
        return CraftFinding(False, "a packaging manifest could not be read, so a declared "
                                   "console-script entry point cannot be ruled out")
    return CraftFinding(True, "no runnable entry point for a non-coder (no demo/__main__/bin/console-script)",
                        measured=True)


# ---------------------------------------------------------------------------
# The seed-divergence check (relational — asks a question the seed cannot answer for itself)
# ---------------------------------------------------------------------------

#: The fleet's Python seed, relative to the agentic-setup checkout. A delivered project is a
#: COPY of this directory, which is what makes the check below relational rather than textual:
#: the seed is not a list of phrases to match, it is the other side of a diff.
_SEED_REL: tuple[str, ...] = ("build-infra", "python", "reference")

#: The documented agentic-setup root for this box, used only when the harness config names
#: none. Mirrors ``battery_execution_limit._DEFAULT_AGENTIC_ROOT`` and the same resolution
#: order run-battery-night.ps1 uses (env override → ``[fleet_dispatch]`` → this).
_DEFAULT_AGENTIC_ROOT = Path("C:/Users/mrbla/agentic-setup")

#: Compare the whole delivered file against the whole seed file.
SEED_COMPARE_WHOLE_FILE = "whole-file"
#: Compare only named dotted TOML keys — for a file the coder is told to KEEP, where merely
#: some of the metadata is owed a rewrite.
SEED_COMPARE_TOML_FIELDS = "toml-fields"


@dataclass(frozen=True)
class SeedFileSpec:
    """One delivered file compared against its seed original, and WHY the coder owes it a change."""

    rel_path: str
    mode: str
    #: ``toml-fields`` mode: the dotted keys compared (never the whole file — see :data:`SEED_FILES`).
    fields: tuple[str, ...] = ()
    #: The instruction the delivery did not honour, quoted into the finding so the report says
    #: what was owed rather than merely that something matched.
    owed: str = ""


#: The delivered files this check compares, and the SCOPE of each comparison.
#:
#: Membership is deliberate in BOTH directions — a file the coder is not asked to change must
#: never be punished for being unchanged, or the check trains the fleet to churn files nobody
#: reads. What the seed's own ``AGENTS.md`` instructs is the authority for each row:
#:
#: * ``README.md`` — WHOLE-FILE. AGENTS.md: "``README.md`` is the operator's documentation …
#:   Rewrite it to describe what you actually built; do not leave it describing a starter
#:   project." An unchanged README is an explicit instruction the delivery did not follow.
#: * ``pyproject.toml`` — FIELD-WISE, never whole-file. AGENTS.md says "keep ``pyproject.toml``",
#:   so its build-system, packaging and pytest blocks are LEGITIMATELY byte-identical and
#:   comparing them would be a false flag. Only ``project.description`` is operator-facing
#:   product metadata, and the seed's own value ends in "(extend this)".
#:
#: Deliberately EXCLUDED, each for a reason on the seed's own surface:
#:
#: * ``AGENTS.md`` — its first line reads "This file is instructions to YOU, the coder. It is
#:   not part of the delivered product." A byte-identical AGENTS.md is CORRECT, and both real
#:   2026-07-29 deliveries carry one.
#: * ``tests/test_smoke.py`` — AGENTS.md calls it "the neutral toolchain proof -- keep it".
#:   Leaving it alone is compliance; rewriting it would be the defect.
#: * ``project.name`` inside ``pyproject.toml`` — nothing instructs the coder to rename the
#:   distribution, and ``app`` is load-bearing for the seeded packaging + ``pythonpath`` config.
#: * The seeded ``app/`` package files — the coder EXTENDS them; an untouched ``__init__.py``
#:   is not evidence of anything. (``lint_dead_scaffold`` owns unremoved placeholder CODE.)
SEED_FILES: tuple[SeedFileSpec, ...] = (
    SeedFileSpec(
        rel_path="README.md",
        mode=SEED_COMPARE_WHOLE_FILE,
        owed="AGENTS.md tells the coder to rewrite README.md to describe what was actually built",
    ),
    SeedFileSpec(
        rel_path="pyproject.toml",
        mode=SEED_COMPARE_TOML_FIELDS,
        fields=("project.description",),
        owed="the project description is still the seed's own placeholder",
    ),
)

#: A delivered file still carries the seed's content — the FLAGGED state.
SEED_STATUS_IDENTICAL = "identical"
#: Every file that could be compared differs from the seed — measured clean.
SEED_STATUS_DIVERGED = "diverged"
#: Nothing could be compared (no seed root, unreadable file, unparseable metadata). This is
#: NOT clean: an unknown that reads as a pass is precisely the failure this check exists to end.
SEED_STATUS_UNKNOWN = "unknown"


@dataclass(frozen=True)
class SeedDivergenceFinding:
    """Whether the delivery still ships the seed's own files, per :data:`SEED_FILES`.

    TRI-STATE on purpose. :class:`CraftFinding` carries a single boolean, and a boolean cannot
    tell "the coder rewrote it" apart from "the seed could not be found" — a false negative
    wearing the same shape as a pass, which is the exact defect class this check replaces.
    The status is therefore carried as a STRING everywhere it is persisted, never a bool."""

    #: True == some delivered file still carries the seed's content. Never set when unmeasured.
    flagged: bool
    detail: str
    status: str = SEED_STATUS_UNKNOWN
    #: Delivered files still matching the seed (the flagged set).
    identical: tuple[str, ...] = ()
    #: Delivered files the coder genuinely changed.
    diverged: tuple[str, ...] = ()
    #: Files that could not be compared — always NAMED, never folded silently into "clean".
    unknown: tuple[str, ...] = ()
    #: The seed directory actually used ("" when none resolved) — evidence for a later reader.
    seed_root: str = ""

    @property
    def measured(self) -> bool:
        """Whether ANY comparison succeeded — mirrors :attr:`RegressionFinding.measured` so a
        caller can tell "clean" from "not measured" without re-deriving it from the lists."""
        return self.status != SEED_STATUS_UNKNOWN


def default_seed_root(cfg: object = None) -> Optional[Path]:
    """The fleet's Python seed directory, or ``None`` when it cannot be located.

    Resolved the way every other external fleet path in this harness is resolved — the harness
    config's ``agentic_setup_dir`` (itself env-override → TOML → compiled-in fallback), then the
    documented root for this box — rather than by hardcoding one machine's absolute path.

    Fail-soft: a missing, unreadable or malformed harness config degrades to the documented
    default instead of raising into an advisory audit. ``None`` (rather than a guess) is
    returned when the resolved directory does not exist, so the caller reports UNKNOWN."""
    root: Optional[Path] = None
    try:
        if cfg is None:
            # Deferred so this leaf module stays importable without the harness config chain.
            from ..config import load_harness_config

            cfg = load_harness_config()
        configured = getattr(cfg, "agentic_setup_dir", "")
        if configured:
            root = Path(str(configured))
    except Exception:  # noqa: BLE001 — a config fault never sinks an advisory lint
        root = None
    try:
        seed = (root or _DEFAULT_AGENTIC_ROOT).joinpath(*_SEED_REL)
        return seed if seed.is_dir() else None
    except OSError:
        return None


def _normalized(path: Path) -> Optional[str]:
    """*path*'s text with line endings and trailing whitespace normalised, or ``None`` when it
    cannot be read.

    Normalising STRENGTHENS the comparison rather than loosening it: a delivery that differs
    from the seed only in line endings (a copy through a CRLF-rewriting checkout) is still the
    seed's text, and a coder cannot clear the finding by re-saving the file with new newlines."""
    try:
        if not path.is_file():
            return None
        raw = path.read_text(encoding="utf-8", errors="replace")[:_LINT_READ_CAP]
    except OSError:
        return None
    flat = raw.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in flat.split("\n")).strip()


def _toml_fields(path: Path, fields: Sequence[str]) -> Optional[dict[str, object]]:
    """The named dotted keys read out of a TOML file, or ``None`` when it cannot be read or
    parsed (including a file so large the bounded read truncates it mid-document — UNKNOWN is
    the honest answer there, never a guess). A key absent from a parsed file maps to ``None``."""
    try:
        if not path.is_file():
            return None
        data = tomllib.loads(path.read_text(encoding="utf-8", errors="replace")[:_LINT_READ_CAP])
    except (OSError, ValueError):
        return None
    out: dict[str, object] = {}
    for dotted in fields:
        node: object = data
        for part in dotted.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        out[dotted] = node
    return out


def _compare_to_seed(repo: Path, seed_root: Path, spec: SeedFileSpec) -> Optional[bool]:
    """``True`` == the delivered file still carries the seed's content, ``False`` == the coder
    changed it, ``None`` == could not determine (missing/unreadable/unparseable on either side).

    Field mode flags when ANY owed field still matches the seed: :data:`SEED_FILES` lists only
    fields the coder owes a change, so one surviving placeholder is residue regardless of the
    others. A field the SEED itself does not set is not comparable — the seed cannot have
    leaked a value it never had."""
    delivered = Path(repo) / spec.rel_path
    seeded = Path(seed_root) / spec.rel_path
    if spec.mode == SEED_COMPARE_WHOLE_FILE:
        current, original = _normalized(delivered), _normalized(seeded)
        if current is None or original is None:
            return None
        return current == original
    if spec.mode == SEED_COMPARE_TOML_FIELDS:
        current_fields = _toml_fields(delivered, spec.fields)
        seed_fields = _toml_fields(seeded, spec.fields)
        if current_fields is None or seed_fields is None:
            return None
        comparable = [k for k in spec.fields if seed_fields.get(k) is not None]
        if not comparable:
            return None
        return any(current_fields.get(k) == seed_fields.get(k) for k in comparable)
    return None


def lint_seed_divergence(
    repo: Path, *, seed_root: "str | Path | None" = None
) -> SeedDivergenceFinding:
    """Is the delivery still shipping the SEED'S OWN files?

    The relational replacement for marker matching. :func:`lint_stale_readme` asks "does this
    README contain one of three known skeleton phrases?" — a question whose answer can be
    changed by editing the seed, and which #1142 accidentally did change: the neutralised seed
    text contains none of the markers, so the untouched copy that ships contains none either,
    and the lint reads CLEAN on the very file it was written to catch. Both projects delivered
    2026-07-29 shipped the seed README unchanged and scored no finding.

    This check asks a question the seed cannot answer for itself: *is the delivered file still
    the file it was copied from?* Editing the seed cannot satisfy it, because the delivered
    file IS a copy of the seed — an edit moves both sides of the comparison at once, and the
    next delivery ships the new text and is flagged again. The only way to clear it is for the
    coder to write something.

    Fail-soft and tri-state: an unresolvable seed root, an unreadable file or unparseable
    metadata yields ``unknown`` for that file and NEVER a flag; when nothing at all could be
    compared the finding is ``unknown``, which is deliberately not ``clean``. ``seed_root``
    overrides the resolved default (tests and a caller with a non-standard checkout)."""
    root = Path(seed_root) if seed_root is not None else default_seed_root()
    try:
        located = root is not None and Path(root).is_dir()
    except OSError:
        located = False
    if not located:
        return SeedDivergenceFinding(
            False,
            f"seed directory could not be located ({root or 'no configured agentic-setup root'}) "
            "— seed divergence NOT checked",
            status=SEED_STATUS_UNKNOWN,
            unknown=tuple(s.rel_path for s in SEED_FILES),
        )
    root = Path(root)  # type: ignore[arg-type]  — narrowed by the located check above

    identical: list[str] = []
    diverged: list[str] = []
    unknown: list[str] = []
    for spec in SEED_FILES:
        verdict = _compare_to_seed(Path(repo), root, spec)
        (unknown if verdict is None else identical if verdict else diverged).append(spec.rel_path)

    tail = f" (not compared: {', '.join(unknown)})" if unknown else ""
    if identical:
        owed = "; ".join(s.owed for s in SEED_FILES if s.rel_path in identical)
        return SeedDivergenceFinding(
            True,
            f"unchanged from the fleet seed: {', '.join(identical)} — {owed}{tail}",
            status=SEED_STATUS_IDENTICAL,
            identical=tuple(identical), diverged=tuple(diverged), unknown=tuple(unknown),
            seed_root=str(root),
        )
    if not diverged:
        return SeedDivergenceFinding(
            False,
            f"seed divergence NOT checked — no file could be compared against {root}",
            status=SEED_STATUS_UNKNOWN,
            unknown=tuple(unknown), seed_root=str(root),
        )
    return SeedDivergenceFinding(
        False,
        f"every compared file diverges from the fleet seed{tail}",
        status=SEED_STATUS_DIVERGED,
        diverged=tuple(diverged), unknown=tuple(unknown), seed_root=str(root),
    )


def run_ruff_advisory(repo: Path, *, timeout_s: float = GREEN_QUALITY_RUFF_TIMEOUT_S) -> Optional[int]:
    """Advisory ``ruff check`` finding-count over *repo* (a SOFT band input), or ``None``
    when ruff is absent / errored / timed out (skipped, never a fail — the dossier's
    'turn ruff on as advisory'). Counts JSON diagnostics; never raises."""
    # Invoked as ``<this interpreter> -m ruff``, NOT as a bare ``ruff``. The harness runs the
    # venv's python.exe directly rather than through an activated venv, so the venv's
    # Scripts\ directory is not on PATH and a bare command name can never resolve — the lint
    # returned None on every night this project has ever run, and a skipped lint renders
    # identically to a clean one (#1189). Module invocation resolves whenever ruff is
    # installed alongside the interpreter that is already executing, which is the only
    # condition this code can actually assert. The bare form is kept as a fallback for a
    # ruff installed system-wide without being importable here.
    for argv in (
        [sys.executable, "-m", "ruff", "check", "--output-format", "json", "."],
        ["ruff", "check", "--output-format", "json", "."],
    ):
        try:
            cp = subprocess.run(  # noqa: S603 — constant argv, no shell
                argv, capture_output=True, text=True, timeout=timeout_s, cwd=str(repo),
                # ruff emits UTF-8 JSON. `text=True` alone decodes with the LOCALE encoding,
                # which on this host is cp1252 — and a deliverable containing a smart quote
                # (U+201D, bytes E2 80 9D) makes ruff echo that character into the diagnostic's
                # `fix.content`, where byte 0x9D is UNDEFINED in cp1252. The decode then raises
                # inside subprocess's reader THREAD, which cannot propagate, so `subprocess.run`
                # returns normally with `cp.stdout is None`. LLM-written code contains smart
                # quotes routinely, so this is a common input, not an exotic one.
                encoding="utf-8", errors="replace",
            )
        except (OSError, subprocess.TimeoutExpired, ValueError):
            continue
        # A run that did not LINT is not a run that found nothing. #1189 fixed the None-vs-0
        # RENDER and left this producer minting the 0: `json.loads(cp.stdout or "[]")` turned
        # an empty stdout into `len([]) == 0`, which `findings()` prints to the operator as
        # "ruff: 0 advisory findings (measured)" — the word "measured" on a measurement that
        # did not happen (#1244).
        #
        # MEASURED, ruff 0.16.1, 2026-07-30, 11 cases. A run that GENUINELY EXAMINED the tree
        # always writes at least the two-character document `[]` and exits 0 (clean) or 1
        # (findings present). Cases 6-10 were chosen specifically to try to make a real run
        # print nothing — an empty directory, a tree of only non-Python files, `exclude = ["*"]`,
        # `extend-exclude = ["*.py"]`, `select = []`, a file-level `# ruff: noqa` — and every
        # one still emitted `[]`. Zero counterexamples. So a blank stdout is never a clean tree.
        #
        # Both clauses are load-bearing and neither is redundant:
        #   returncode not in (0, 1)  — ruff REFUSED to start. Exit 2, stdout empty: a malformed
        #                               `pyproject.toml` or an unknown rule selector in the
        #                               deliverable's own config, both of which the coder fleet
        #                               writes. This is the live trigger.
        #   not cp.stdout.strip()     — ruff produced nothing while exiting 0 or 1. That is the
        #                               module-not-found shape (rc=1, empty), which COLLIDES with
        #                               ruff's own "findings present" code, so the returncode
        #                               alone cannot discriminate it.
        #
        # `continue` rather than `return None`, so a first argv that could not lint falls through
        # to the bare-command fallback below. Before this guard the fallback was unreachable —
        # `[sys.executable, "-m", "ruff", …]` cannot raise OSError while the interpreter exists,
        # so the loop always broke on the first iteration (#1241 row C-1).
        # `cp.stdout or ""` and NOT `cp.stdout.strip()`: stdout can be None even when
        # `subprocess.run` returns normally (see the encoding note above — a reader-thread decode
        # failure cannot propagate). The pre-#1244 code absorbed that into `json.loads(None or
        # "[]")` == a wrong-but-harmless 0; the first version of this guard turned it into an
        # AttributeError, which this function's own docstring promises it never raises, and which
        # `battery.py:1698-1712` would have swallowed into `{}` — blanking the ENTIRE
        # green-quality stage for the night rather than one lint. None is treated as NOT RUN
        # because a measurement we could not read is not a measurement.
        if cp.returncode not in (0, 1) or not (cp.stdout or "").strip():
            continue
        break
    else:
        return None
    try:
        # No `or "[]"`: the guard above has already established stdout is non-blank, and the
        # fallback is what minted the false zero.
        diagnostics = json.loads(cp.stdout)
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
    #: Defaults to the UNKNOWN finding, never a clean one: a result assembled without running
    #: the seed check has not measured it, and must not be readable as a pass.
    seed_divergence: SeedDivergenceFinding = field(
        default_factory=lambda: SeedDivergenceFinding(False, "seed divergence not checked")
    )
    ruff_findings: Optional[int] = None
    surface: str = ""

    #: The craft lints in report order, each with the name it discloses under — the same four
    #: names ``findings()`` uses. Unannotated on purpose: a dataclass only makes ANNOTATED
    #: names fields, so this stays a class constant rather than becoming a sixth field.
    _CRAFT_LINTS = ("dead scaffold", "stale README", "entry point", "seed divergence")

    @property
    def _craft_findings(self) -> tuple[tuple[str, CraftFinding | SeedDivergenceFinding], ...]:
        """The craft lints paired with their disclosure names, in report order.

        One source for both :attr:`any_craft_residue` and :attr:`craft_lints_unmeasured`, so
        the pair can never end up speaking for different sets of checks."""
        return tuple(zip(self._CRAFT_LINTS, (self.dead_scaffold, self.stale_readme,
                                             self.no_entry_point, self.seed_divergence)))

    @property
    def any_craft_residue(self) -> bool:
        """Whether a lint that COULD look found residue — never merely ``flagged``.

        Each read is gated on its own lint's ``measured`` bit. A lint that could not look
        returns ``flagged=False``, so the ungated form answered "did not look" and "looked and
        found nothing" with the same ``False`` — the #1223 collapse sitting in the property the
        corpus counter and the operator's KPI line are both derived from.

        A bool cannot carry the third state, and this one does not pretend to: the unmeasured
        half is :attr:`craft_lints_unmeasured`, and a caller reporting a residue COUNT must
        render both. Reading this alone is reading a numerator without its denominator."""
        return any(f.measured and f.flagged for _name, f in self._craft_findings)

    @property
    def craft_lints_unmeasured(self) -> tuple[str, ...]:
        """The craft lints that could not look, by name — empty when all four measured.

        The companion that makes :attr:`any_craft_residue`'s ``False`` readable. Named rather
        than counted because "which check went blind" is the actionable half: a reader who
        knows the seed root could not be resolved knows what the night does not cover."""
        return tuple(name for name, f in self._craft_findings if not f.measured)

    def findings(self) -> list[str]:
        """The human finding lines: every flagged check, AND every check that could not run.

        This is the full honest report, and the rule it follows is uniform across all six
        deterministic checks — an absent measurement is STATED, never implied by silence.
        Reporting only the flagged ones made a lint that went blind read exactly like a lint
        that looked and found nothing, which is the whole defect class (#1223): the caller
        sees an empty list and the operator is told "no problems the audit could find"."""
        out: list[str] = []
        if self.regression.measured and self.regression.regressed:
            out.append(f"REGRESSED (data loss) — {self.regression.detail}")
        elif self.regression.measured and self.regression.changed:
            out.append(f"behaviour changed vs last GREEN — {self.regression.detail}")
        elif not self.regression.measured:
            out.append(f"regression probe NOT RUN — {self.regression.detail} "
                       f"(this is an absent measurement, not a clean one)")
        for name, f in (("dead scaffold", self.dead_scaffold),
                        ("stale README", self.stale_readme),
                        ("entry point", self.no_entry_point)):
            if f.measured and f.flagged:
                out.append(f.detail)
            elif not f.measured:
                out.append(f"{name} lint NOT RUN — {f.detail} "
                           f"(this is an absent measurement, not a clean one)")
        if self.seed_divergence.measured and self.seed_divergence.flagged:
            out.append(self.seed_divergence.detail)
        elif not self.seed_divergence.measured:
            out.append(f"seed divergence UNKNOWN — {self.seed_divergence.detail}")
        # `None` (the lint could not run) and `0` (it ran and found nothing) are DIFFERENT
        # answers and must not render the same. The old `if self.ruff_findings:` suppressed
        # both, so a lint that had never executed was indistinguishable from a clean one —
        # which is exactly what happened: ruff was invoked as a bare command name the harness
        # could never resolve, so this read "clean" on every night the project has run
        # (#1189). An absent measurement is stated, never implied by silence.
        if self.ruff_findings is None:
            out.append("ruff: NOT RUN (advisory lint unavailable — this is an absent "
                       "measurement, not a clean one)")
        elif self.ruff_findings:
            out.append(f"ruff: {self.ruff_findings} advisory finding(s)")
        else:
            out.append("ruff: 0 advisory findings (measured)")
        return out


def audit_layer1(
    current_repo: Path,
    reference_repo: Optional[Path],
    probe_set: Optional[ProbeSet],
    *,
    surface: str = "",
    run: ProbeRunner = run_probe,
    ruff: Callable[[Path], Optional[int]] = run_ruff_advisory,
    seed_root: "str | Path | None" = None,
) -> Layer1Result:
    """Run the whole deterministic floor over one GREEN's repo. Pure orchestration — every
    sub-check is fail-soft, so a missing repo yields an all-clean (unmeasured) result rather
    than a crash. ``run``/``ruff`` are injected so tests need no real subprocess; ``seed_root``
    overrides the resolved fleet-seed location for :func:`lint_seed_divergence`."""
    surf = surface or (probe_set.surface if probe_set else "")
    return Layer1Result(
        regression=archetype_regression(current_repo, reference_repo, probe_set, run=run),
        dead_scaffold=lint_dead_scaffold(current_repo),
        stale_readme=lint_stale_readme(current_repo),
        no_entry_point=lint_no_entry_point(current_repo, surf),
        seed_divergence=lint_seed_divergence(current_repo, seed_root=seed_root),
        ruff_findings=ruff(current_repo),
        surface=surf,
    )
