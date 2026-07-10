"""Deterministic dispatch to the agentic-setup coding fleet — the thin surface.

BlarAI's only new coding-capability surface is **dispatch**: write a task to the
fleet's queue, trigger a run, read the run's ``SUMMARY.txt``. The fleet (30B /
OVMS / worktrees / verify-gate / auto-merge) lives entirely on the agentic-setup
side and runs against the operator's OTHER project repos — never BlarAI's tree
(the fleet itself refuses ``~/BlarAI`` and ``~/.openclaw``; this module mirrors
that refusal as fail-fast defense-in-depth).

Security frame:
  * Local host subprocess ONLY (``add-fleet-task.ps1`` / ``run-fleet.ps1``). No
    network egress — the egress guard governs sockets, not local exec.
  * Fail-Closed: vector argv (never a shell line), bounded timeout, any
    non-zero/timeout/exception → a clear failure result, never a silent success.
  * Target-scoped: a dispatch may only target an existing git repo UNDER the
    configured projects dir, never BlarAI/.openclaw.
  * Dormant: the caller gates on ``[fleet_dispatch].enabled`` before reaching here.

The 14B-driven decomposition (turning a vague idea into well-scoped tasks) is NOT
here — it rides on the model swap (the 14B and the fleet's 30B cannot co-reside),
a later increment. This module is the deterministic enqueue / trigger / read.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Repos the fleet refuses (new-agent-task.ps1) — mirrored as fail-fast defense.
_FORBIDDEN_REPO_ROOTS: tuple[str, ...] = ("BlarAI", ".openclaw")

# Windows process-creation flags so a triggered run OUTLIVES a BlarAI teardown
# (the launcher assigns children to a kill-on-close Job Object; breakaway escapes
# it). Best-effort: if the job forbids breakaway we retry detached-only, and the
# run is resumable by RunId regardless.
_CREATE_BREAKAWAY_FROM_JOB = 0x01000000


@dataclass(frozen=True)
class FleetDispatchConfig:
    """Resolved paths for the fleet's documented entry points + output."""

    scripts_dir: Path
    """agentic-setup\\scripts (holds add-fleet-task.ps1 / run-fleet.ps1)."""
    queue_path: Path
    """The fleet queue JSON (state\\fleet-queue.json)."""
    runs_dir: Path
    """Where run-fleet writes state\\fleet-runs\\<RunId>\\SUMMARY.txt."""
    projects_dir: Path
    """The ONLY allowed target root — the operator's projects (never BlarAI)."""
    enqueue_timeout_s: float = 30.0
    plan_graph: bool = False
    """M2 W1 (#740): plan a dispatch as a dependency-ordered JobPlan
    (``shared/fleet/plan_graph.py`` — waves, context packs, integration gates).
    ``False`` (the default) keeps today's flat serial queue byte-identical; the
    swap driver consumes this (Lane A2 wiring). Resolved from
    ``[fleet_dispatch].plan_graph``."""
    vikunja_bridge: bool = False
    """#749: post one durable Vikunja ticket per dispatched job (created at
    dispatch, outcome at REPORT, closed only on GREEN + oracle-passed). ``False``
    (the dormant default, until the supervised live proof) means the bridge posts
    NOTHING — a Vikunja outage cannot affect a run regardless (fail-soft), but
    off is off. Resolved from ``[fleet_dispatch].vikunja_bridge``."""
    vikunja_bridge_project_id: int = 0
    """#749: the Vikunja project id the job tickets land in (the "BlarAI Coder
    Jobs" project). ``0`` (the default) is UNSET — the bridge refuses to post
    without a target project even when ``vikunja_bridge`` is on. Resolved from
    ``[fleet_dispatch].vikunja_bridge_project_id``."""
    guest_oracle_enabled: bool = False
    """#744 guest-certified oracle: re-run the job-level acceptance oracle inside
    the NIC-less Alpine guest as an ADVISORY isolation certificate (plan §10.3
    S4 residual). ``False`` (the dormant default, until the supervised live
    proof) means the swap driver never touches the guest-oracle seams —
    byte-identical today-behavior. Resolved from
    ``[fleet_dispatch].guest_oracle_enabled``."""


@dataclass(frozen=True)
class DispatchResult:
    """Outcome of an engine call. ``ok`` is the operation's success; ``message``
    is the user-facing line. Never raises out of the public API."""

    ok: bool
    message: str
    run_id: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class CreateProjectResult:
    """Outcome of :func:`create_project`. ``ok`` is the operation's success and
    ``message`` is the user-facing line; ``name`` is the slug actually created
    (the dispatch target for a follow-on PLAN) and ``path`` its absolute path.
    Never raised out of the public API (Fail-Closed)."""

    ok: bool
    message: str
    name: str = ""
    path: str = ""
    error: str | None = None


@dataclass(frozen=True)
class TaskOutcome:
    """One parsed task line from a run's SUMMARY.txt."""

    task: str
    outcome: str  # the raw run-fleet outcome word (processed/errored/skipped…)
    result: str  # classified: MERGED | PARKED | BLOCKED | NOTHING | UNKNOWN
    detail: str  # the raw RESULT: line text


# ---------------------------------------------------------------------------
# Internals (small, unit-tested)
# ---------------------------------------------------------------------------


def _pwsh() -> str:
    return shutil.which("pwsh") or shutil.which("powershell") or "powershell"


def _git() -> str | None:
    """The git executable, or None if git is not installed (Fail-Closed)."""
    return shutil.which("git")


#: CREATE_NO_WINDOW for _safe_run's console-subsystem children (pwsh / git / tasklist /
#: uv...) — #761: the detached swap driver is spawned via pythonw.exe (GUI subsystem, no
#: console), so without this flag EVERY _safe_run child in that driver would be allocated
#: a fresh VISIBLE console window (short git calls flash one; a wave-gate pytest/npm
#: child holds one for up to 600s — the accidental-close hazard the ticket closes). Safe
#: by construction: every caller captures output and none is interactive. CONSTRAINT:
#: never apply this flag to a python LAUNCHER spawn — a HIDDEN console crashed Textual on
#: 2026-07-06 ("Driver must be in application mode"); the launcher spawns (swap_ops /
#: battery) use pythonw instead. 0 off-Windows (creationflags is Windows-only).
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def _safe_run(
    cmd: list[str], timeout_s: float, cwd: "str | None" = None
) -> tuple[bool, str, str]:
    """Bounded, no-shell subprocess. Returns (ok, stdout, stderr). Fail-Closed.

    ``cwd`` (M2 W4, additive — the default is byte-identical) lets a gate run inside a
    target repo without the repo path ever entering a command STRING: the path rides
    the process's working directory, never a shell line (§10 S1 argv-only rule).
    ``creationflags=_NO_WINDOW`` (#761): console-subsystem children of the console-less
    pythonw-spawned driver must not each be allocated a visible console."""
    try:
        cp = subprocess.run(  # noqa: S603 — vector argv, no shell
            cmd, capture_output=True, text=True, timeout=timeout_s, cwd=cwd or None,
            creationflags=_NO_WINDOW,
        )
        return (cp.returncode == 0, cp.stdout or "", cp.stderr or "")
    except subprocess.TimeoutExpired:
        return (False, "", f"timed out after {timeout_s:.0f}s")
    except OSError as exc:
        return (False, "", f"spawn error: {type(exc).__name__}: {exc}")
    except Exception as exc:  # noqa: BLE001 — fail-closed: any error is a failure
        return (False, "", f"unexpected error: {type(exc).__name__}: {exc}")


def validate_repo(repo: Path, projects_dir: Path) -> str | None:
    """Return an error string if *repo* is not an acceptable dispatch target,
    else ``None``. A target must be an existing git repo UNDER *projects_dir*
    and never under a forbidden root."""
    try:
        resolved = repo.resolve()
    except Exception:  # noqa: BLE001
        return "repo path could not be resolved"
    # Casefold both sides: a path component 'blarai' / '.OpenClaw' must be refused as
    # readily as 'BlarAI' / '.openclaw' (defense-in-depth; the containment check below
    # already holds, but the NAME refusal must not miss on case — on Windows the paths
    # are the same directory anyway). (#740 H5)
    names = {p.name.casefold() for p in (resolved, *resolved.parents)}
    if names & {r.casefold() for r in _FORBIDDEN_REPO_ROOTS}:
        return (
            f"refusing: {resolved} is under a forbidden root "
            f"({' / '.join(_FORBIDDEN_REPO_ROOTS)}) — fleet jobs target your "
            "OTHER projects, never BlarAI"
        )
    try:
        resolved.relative_to(projects_dir.resolve())
    except ValueError:
        return f"refusing: {resolved} is outside the allowed projects dir ({projects_dir})"
    if not (resolved / ".git").is_dir():
        return f"{resolved} is not a git repository"
    return None


def slugify_task(text: str) -> str:
    """A short, filesystem/branch-safe task name from a free-text request."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")
    return (slug[:48] or "task").rstrip("-")


def project_slug(name: str) -> str:
    """A filesystem/branch-safe project directory name from a free-text name.

    Lowercase, non-alphanumerics collapsed to single hyphens, trimmed, bounded
    to 48 chars. Returns ``""`` for input with no usable characters — unlike
    :func:`slugify_task`, a project is NEVER auto-named ``task``; the caller
    refuses an empty slug and asks the operator to name it deliberately."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug[:48].rstrip("-")


def new_run_id() -> str:
    """A unique RunId matching run-fleet's ``yyyyMMdd-HHmmss`` shape + a suffix."""
    return datetime.now().strftime("%Y%m%d-%H%M%S") + "-bd"


def _classify_result(result_line: str) -> str:
    low = result_line.lower()
    if "merged" in low and "not merged" not in low:
        return "MERGED"
    if "blocked" in low:
        return "BLOCKED"
    if "nothing to merge" in low:
        return "NOTHING"
    if "not merged" in low:
        return "PARKED"
    if "timed out" in low:
        # #757: a tree-killed task (per-task ceiling or budget-watchdog abort) writes an
        # explicit TIMED OUT detail; it must round-trip through the cumulative SUMMARY as
        # TIMEOUT, not decay to UNKNOWN (the #686 shape-divergence class).
        return "TIMEOUT"
    return "UNKNOWN"


def parse_summary(text: str) -> list[TaskOutcome]:
    """Parse a run-fleet ``SUMMARY.txt`` body into per-task outcomes.

    Shape (run-fleet.ps1):  ``- <task>: <outcome>`` then an indented
    ``RESULT: …`` line then ``full report: <path>``.
    """
    outcomes: list[TaskOutcome] = []
    cur_task: str | None = None
    cur_outcome = ""
    for raw in text.splitlines():
        # Tolerate a leading indent on the task line (the cumulative writer used to indent it);
        # the RESULT: line below is already matched stripped.
        m = re.match(r"^\s*- (?P<task>.+?): (?P<outcome>.+)$", raw)
        if m:
            cur_task = m.group("task").strip()
            cur_outcome = m.group("outcome").strip()
            continue
        stripped = raw.strip()
        if cur_task is not None and stripped.upper().startswith("RESULT:"):
            outcomes.append(
                TaskOutcome(
                    task=cur_task,
                    outcome=cur_outcome,
                    result=_classify_result(stripped),
                    detail=stripped,
                )
            )
            cur_task = None
    return outcomes


def summary_report_paths(text: str) -> list[str]:
    """Extract the per-task ``full report: <path>`` paths from a ``SUMMARY.txt`` body.

    run-fleet writes one ``full report: <path>`` line per task pointing at the detailed
    per-task report (which carries the separate ``TESTS:`` / ``VERIFY:`` / ``REVIEW
    VERDICT:`` signals the acceptance layer reads). Order-preserving; missing -> ``[]``.
    """
    paths: list[str] = []
    for raw in (text or "").splitlines():
        stripped = raw.strip()
        if stripped.lower().startswith("full report:"):
            path = stripped.split(":", 1)[1].strip()
            if path:
                paths.append(path)
    return paths


def _format_report(run_id: str, outcomes: list[TaskOutcome]) -> str:
    if not outcomes:
        return f"Fleet run {run_id}: completed, but no task results were parsed from the summary."
    icon = {"MERGED": "✓ merged", "PARKED": "parked (review the branch)",
            "BLOCKED": "BLOCKED (possible secret — left uncommitted)",
            "NOTHING": "no changes", "UNKNOWN": "see report",
            "TIMEOUT": "timed out (tree-killed — see report)"}
    lines = [f"Fleet run {run_id} — {len(outcomes)} task(s):"]
    for o in outcomes:
        lines.append(f"  • {o.task}: {icon.get(o.result, o.result)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def enqueue_task(
    repo: str | Path,
    task: str,
    prompt: str,
    *,
    config: FleetDispatchConfig,
    model: str = "",
) -> DispatchResult:
    """Append one ``{repo,task,prompt,model?}`` task to the fleet queue via
    ``add-fleet-task.ps1``. Validates the target repo first (fail-fast)."""
    err = validate_repo(Path(repo), config.projects_dir)
    if err:
        return DispatchResult(ok=False, message=f"Could not enqueue — {err}.", error=err)
    script = config.scripts_dir / "add-fleet-task.ps1"
    if not script.is_file():
        return DispatchResult(
            ok=False,
            message="Could not enqueue — the fleet is not installed (add-fleet-task.ps1 missing).",
            error="script_missing",
        )
    cmd = [
        _pwsh(), "-NoProfile", "-NonInteractive", "-File", str(script),
        "-Repo", str(repo), "-Task", str(task), "-Prompt", str(prompt),
        "-Queue", str(config.queue_path),
    ]
    if model:
        cmd += ["-Model", str(model)]
    ok, _out, err_txt = _safe_run(cmd, config.enqueue_timeout_s)
    if not ok:
        return DispatchResult(
            ok=False,
            message=f"Enqueue failed: {err_txt.strip() or 'unknown error'}.",
            error=err_txt.strip() or "enqueue_failed",
        )
    return DispatchResult(ok=True, message=f"Enqueued task '{task}' for {repo}.")


def run_fleet(*, config: FleetDispatchConfig, run_id: str | None = None) -> DispatchResult:
    """Trigger ``run-fleet.ps1`` DETACHED with an explicit RunId, so it survives a
    BlarAI teardown (for the model swap) and the RunId is known up front. Does NOT
    wait — run-fleet waits for OVMS READY and processes the queue in the background.

    NOTE: increment-1 leaves the live RUN to the operator (the 30B and the 14B
    cannot co-reside); this is the engine call the increment-2 swap driver uses.
    """
    rid = run_id or new_run_id()
    script = config.scripts_dir / "run-fleet.ps1"
    if not script.is_file():
        return DispatchResult(
            ok=False, run_id=rid,
            message="Could not trigger a run — the fleet is not installed (run-fleet.ps1 missing).",
            error="script_missing",
        )
    cmd = [
        _pwsh(), "-NoProfile", "-NonInteractive", "-File", str(script),
        "-Queue", str(config.queue_path), "-RunId", rid,
    ]
    base_flags = 0
    if sys.platform == "win32":
        base_flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    for flags in (base_flags | _CREATE_BREAKAWAY_FROM_JOB, base_flags):
        try:
            subprocess.Popen(  # noqa: S603 — vector argv, no shell
                cmd, creationflags=flags if sys.platform == "win32" else 0,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, close_fds=True,
            )
            return DispatchResult(
                ok=True, run_id=rid,
                message=f"Triggered fleet run {rid} (it proceeds once the coder model is loaded).",
            )
        except OSError:
            continue  # breakaway may be disallowed; retry detached-only
        except Exception as exc:  # noqa: BLE001
            return DispatchResult(
                ok=False, run_id=rid,
                message=f"Could not trigger the fleet run: {exc}.", error=str(exc),
            )
    return DispatchResult(
        ok=False, run_id=rid,
        message="Could not trigger the fleet run (process launch failed).",
        error="popen_failed",
    )


def read_summary(*, config: FleetDispatchConfig, run_id: str) -> DispatchResult:
    """Read + parse ``state\\fleet-runs\\<run_id>\\SUMMARY.txt`` into a report."""
    summary = config.runs_dir / run_id / "SUMMARY.txt"
    if not summary.is_file():
        return DispatchResult(
            ok=True, run_id=run_id,
            message=(
                f"Run {run_id} has no summary yet — it's still running, or hasn't "
                "started (the coder model must be loaded for it to proceed)."
            ),
        )
    try:
        text = summary.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return DispatchResult(
            ok=False, run_id=run_id,
            message=f"Could not read the run summary: {exc}.", error=str(exc),
        )
    return DispatchResult(ok=True, run_id=run_id, message=_format_report(run_id, parse_summary(text)))


def latest_run_id(*, config: FleetDispatchConfig) -> str | None:
    """The most recent RunId under runs_dir (by name; run-fleet names sort by time)."""
    try:
        runs = [p.name for p in config.runs_dir.iterdir() if p.is_dir()]
    except OSError:
        return None
    return sorted(runs)[-1] if runs else None


# ---------------------------------------------------------------------------
# Acceptance record (run-id-keyed; written on approve, read by /dispatch status)
# ---------------------------------------------------------------------------
# The acceptance criteria for a run are persisted next to its SUMMARY.txt so the
# honest per-criterion report survives a process restart (the model swap relaunches
# the backend). Stored as a plain dict (``{spec, repo}``) — this module never imports
# the acceptance package, so there is no import cycle (acceptance -> decompose ->
# dispatch). The caller serialises the spec via ``AcceptanceSpec.to_dict()``.


def acceptance_record_path(config: FleetDispatchConfig, run_id: str) -> Path:
    """Path of a run's acceptance record (``runs\\<run_id>\\acceptance.json``)."""
    return config.runs_dir / run_id / "acceptance.json"


def write_acceptance_record(
    config: FleetDispatchConfig, run_id: str, *, spec_dict: dict, repo: str
) -> Path:
    """Persist ``{spec, repo}`` for *run_id* so the post-run report can be rendered later."""
    path = acceptance_record_path(config, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"spec": spec_dict, "repo": repo}, indent=2), encoding="utf-8"
    )
    return path


def read_acceptance_record(config: FleetDispatchConfig, run_id: str) -> dict | None:
    """Read a run's ``{spec, repo}`` acceptance record, or ``None`` if absent/unreadable."""
    path = acceptance_record_path(config, run_id)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


# ---------------------------------------------------------------------------
# New-project creation (#712 — create-a-project-via-BlarAI)
# ---------------------------------------------------------------------------
# A non-git operator cannot start a project, because a dispatch target must
# already be a git repo (validate_repo refuses a dir with no .git).
# create_project does the git plumbing for them: a fresh repo under
# projects_dir with a first commit, which is then a valid dispatch target.
# Deterministic, local-only, Fail-Closed — the SAME containment guard as a
# dispatch target, and it never clobbers an existing path.

_PROJECT_GIT_USER = "BlarAI"
_PROJECT_GIT_EMAIL = "blarai@localhost"

# A generic starter ignore covering the ecosystems the fleet builds (Python /
# Node) plus OS + editor cruft. Deliberately broad-but-safe; the fleet can add
# to it per project.
_GITIGNORE_TEXT = (
    "# Created by BlarAI\n"
    "__pycache__/\n"
    "*.py[cod]\n"
    ".venv/\n"
    "venv/\n"
    "env/\n"
    "node_modules/\n"
    "dist/\n"
    "build/\n"
    "*.log\n"
    ".DS_Store\n"
    "Thumbs.db\n"
    ".idea/\n"
    ".vscode/\n"
)


def _readme_text(name: str, goal: str) -> str:
    """A minimal README seeding the new repo. No timestamp — kept deterministic
    for tests; the goal is the useful context for both the operator and the
    fleet's first build."""
    title = name.strip() or "New project"
    body = goal.strip()
    lines = [f"# {title}", ""]
    if body:
        lines += [body, ""]
    lines += ["_Created by BlarAI._", ""]
    return "\n".join(lines)


def create_project(
    name: str, *, config: FleetDispatchConfig, goal: str = ""
) -> CreateProjectResult:
    """Create a NEW empty git repository under the configured projects dir so a
    non-git operator can start a project from BlarAI (#712).

    Deterministic, local-only, Fail-Closed (mirrors :func:`enqueue_task`):
      * vector argv subprocesses (never a shell line), bounded timeout;
      * the target is slug-derived and MUST resolve UNDER ``projects_dir`` and
        never under a forbidden root — the SAME guard a dispatch target passes;
      * refuses to clobber an existing path (never overwrites);
      * an initial commit is REQUIRED (the fleet's worktree/branch machinery
        cannot operate on an unborn HEAD) and the branch is forced to ``main``
        so the fleet's auto-merge target is predictable across git versions.

    On success the repo is a valid dispatch target (``.git`` + one commit);
    the returned ``name`` is the slug created, for a follow-on PLAN.
    """
    slug = project_slug(name)
    if not slug:
        return CreateProjectResult(
            ok=False,
            message=(
                "I need a name for the project (letters or numbers). "
                "Try: /dispatch new my-app | <what to build>."
            ),
            error="empty_slug",
        )
    git = _git()
    if git is None:
        return CreateProjectResult(
            ok=False,
            message="Could not create the project — git is not installed.",
            error="git_missing",
        )

    projects_dir = config.projects_dir
    try:
        projects_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return CreateProjectResult(
            ok=False,
            message=f"Could not create the projects folder ({projects_dir}): {exc}.",
            error="projects_dir_unwritable",
        )

    target = projects_dir / slug
    try:
        resolved = target.resolve()
    except Exception:  # noqa: BLE001
        return CreateProjectResult(
            ok=False, message="The project path could not be resolved.",
            error="unresolvable",
        )
    # Same forbidden-root + containment guard a dispatch target must pass (casefolded
    # so 'blarai' / '.OpenClaw' refuse as readily as the canonical spellings — #740 H5).
    names = {p.name.casefold() for p in (resolved, *resolved.parents)}
    if names & {r.casefold() for r in _FORBIDDEN_REPO_ROOTS}:
        return CreateProjectResult(
            ok=False,
            message=f"Refusing: '{slug}' resolves under a protected folder.",
            error="forbidden_root",
        )
    try:
        resolved.relative_to(projects_dir.resolve())
    except ValueError:
        return CreateProjectResult(
            ok=False,
            message=f"Refusing: '{slug}' resolves outside the projects folder.",
            error="outside_projects",
        )
    if resolved.exists():
        return CreateProjectResult(
            ok=False,
            message=(
                f"A project called '{slug}' already exists. Build in it with "
                f"/dispatch {slug} | <goal>, or pick a different name."
            ),
            error="exists",
        )

    # Create the dir + scaffold, then git init / identity / commit / force-main.
    try:
        resolved.mkdir(parents=False, exist_ok=False)
        (resolved / "README.md").write_text(_readme_text(name, goal), encoding="utf-8")
        (resolved / ".gitignore").write_text(_GITIGNORE_TEXT, encoding="utf-8")
    except OSError as exc:
        return CreateProjectResult(
            ok=False, message=f"Could not write the project files: {exc}.",
            error="scaffold_failed", name=slug, path=str(resolved),
        )

    steps: tuple[list[str], ...] = (
        [git, "-C", str(resolved), "init"],
        [git, "-C", str(resolved), "config", "user.name", _PROJECT_GIT_USER],
        [git, "-C", str(resolved), "config", "user.email", _PROJECT_GIT_EMAIL],
        # Disable commit signing for THIS new repo: a non-git operator won't have
        # a GPG key, and the fleet's later auto-commits would fail under a
        # globally-required signature. The scaffold commit needs no signature.
        [git, "-C", str(resolved), "config", "commit.gpgsign", "false"],
        [git, "-C", str(resolved), "add", "-A"],
        [git, "-C", str(resolved), "commit", "-m", "Initial commit (created by BlarAI)"],
        [git, "-C", str(resolved), "branch", "-M", "main"],
    )
    for cmd in steps:
        ok, _out, err = _safe_run(cmd, config.enqueue_timeout_s)
        if not ok:
            return CreateProjectResult(
                ok=False,
                message=(
                    f"Created the folder but git setup failed at "
                    f"'{' '.join(cmd[3:])}': {err.strip() or 'unknown error'}. "
                    f"The folder is at {resolved} — remove it and retry."
                ),
                error="git_failed", name=slug, path=str(resolved),
            )

    return CreateProjectResult(
        ok=True,
        message=f"Created a new project '{slug}' at {resolved}.",
        name=slug, path=str(resolved),
    )


# This-host FALLBACK defaults for the agentic-setup fleet (a single-host system).
# The dispatch target is now config-driven (#670): the two roots come from
# [fleet_dispatch].agentic_setup_dir / projects_dir (resolved by the AO, threaded to
# the gateway). These compiled-in values are only the fallback when a config key is
# empty/absent — the target is no longer hard-wired.
_AGENTIC_SETUP = Path(r"C:\Users\mrbla\agentic-setup")
_PROJECTS = Path(r"C:\Users\mrbla\projects")


def build_default_config(
    agentic_setup_dir: "str | Path | None" = None,
    projects_dir: "str | Path | None" = None,
    *,
    plan_graph: bool = False,
    vikunja_bridge: bool = False,
    vikunja_bridge_project_id: int = 0,
    guest_oracle_enabled: bool = False,
) -> FleetDispatchConfig:
    """The fleet paths for this host. The two ROOTS are config-driven
    ([fleet_dispatch].agentic_setup_dir / projects_dir, threaded from the AO config);
    an empty/None value falls back to the compiled-in default for this box. The
    scripts/queue/runs paths derive from the agentic-setup root (the fleet's fixed
    state\\ layout), so only the root is configurable, never the internal structure.
    ``plan_graph`` threads the M2 W1 knob ([fleet_dispatch].plan_graph, #740),
    ``vikunja_bridge`` / ``vikunja_bridge_project_id`` thread the #749 durable-ticket
    knobs, and ``guest_oracle_enabled`` threads the #744 guest-certified-oracle knob —
    all keyword-only with dormant defaults, so every existing caller is
    byte-identical."""
    setup = Path(agentic_setup_dir) if agentic_setup_dir else _AGENTIC_SETUP
    projects = Path(projects_dir) if projects_dir else _PROJECTS
    return FleetDispatchConfig(
        scripts_dir=setup / "scripts",
        queue_path=setup / "state" / "fleet-queue.json",
        runs_dir=setup / "state" / "fleet-runs",
        projects_dir=projects,
        plan_graph=plan_graph,
        vikunja_bridge=vikunja_bridge,
        vikunja_bridge_project_id=vikunja_bridge_project_id,
        guest_oracle_enabled=guest_oracle_enabled,
    )
