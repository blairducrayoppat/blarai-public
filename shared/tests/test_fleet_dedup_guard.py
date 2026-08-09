"""#1075 — run-fleet's dedup guard must key ``done.txt`` on DELIVERY, not on a clean exit.

``run-fleet.ps1`` runs ONE task per invocation under a shared ``-RunId``, and ``done.txt``
accumulates across those invocations, so it is the guard that decides whether the driver's
targeted fix cycles (layout / executability / static pre-gate) can re-dispatch a task at
all. Before this fix the guard set ``$outcome = 'processed'`` solely because
``new-agent-task.ps1`` did not throw, and keyed ``done.txt`` on that — so ``MERGED``,
``NOT merged`` and ``Nothing to merge`` were indistinguishable and a task that attempted
and produced nothing was permanently unrepairable inside its own run. B4's add-card built
nothing, the layout fix cycle asked to re-run it with the unresolved imports named, and the
guard refused; the job parked (#1066 forensics, c.2446).

These locks drive the REAL path end to end: :func:`shared.fleet.swap_ops.real_run_task`
spawns the actual ``run-fleet.ps1`` under ``pwsh`` with a real one-task queue file, and the
real script does its own JSON parsing, its own ``done.txt``/``dispatches.txt`` I/O and its
own report scrape. Only the two EXTERNAL boundaries are stood in for — the OVMS model probe
(``Get-LoadedModelId``, which would otherwise need a loaded 30B) and the coder itself
(``new-agent-task.ps1``, which would otherwise need a GPU and hours) — and the stub coder
writes a real report file in the real report directory so the script scrapes a real
``RESULT:`` line. The script under test is copied byte-for-byte from the fleet install at
test time, so it cannot drift away from what production runs.

Locks:
  * an empty task (``Nothing to merge``) is NOT recorded done, and a second dispatch of it
    REACHES the coder — the B4 repair path;
  * TOGGLE-OFF: with the delivery predicate neutralised back to the pre-fix rule
    ("it exited, so it is done"), that same second dispatch is REFUSED — proving the lock
    sees the real defect and not an artefact of the harness;
  * a genuinely MERGED task IS still skipped on re-dispatch — the guard keeps its job;
  * the retries are BOUNDED: a task that never delivers is refused once its dispatch budget
    is spent, so the fix cannot loop;
  * a parked task (``NOT merged``) is likewise retriable — parking leaves main untouched.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from shared.fleet import swap_driver as sd
from shared.fleet import swap_ops as so
from shared.fleet.dispatch import (
    FLEET_AGENTIC_SETUP_DIR_ENV,
    _pwsh,
    build_default_config,
    parse_summary,
    resolve_fleet_root,
)

#: The RESULT bodies ``new-agent-task.ps1`` actually emits (scripts/new-agent-task.ps1:764).
#: Locking against the real strings is the point — a paraphrase would not prove the
#: discriminator handles what the coder really writes.
RESULT_MERGED = "MERGED into your project - just open the app and try it."
RESULT_NOTHING = "Nothing to merge."
RESULT_PARKED = "NOT merged. The work is parked safely on branch 'agent/add-card' (workspace: C:/wt/add-card)."

#: The stub coder's parameter surface — every named parameter ``run-fleet.ps1`` splats.
#: Declared explicitly so a future run-fleet change that passes something new fails HERE,
#: loudly, instead of silently drifting away from the coder's real interface.
_STUB_CODER = """\
param(
    [string]$Repo, [string]$Task, [string]$Prompt,
    [int]$MaxRunMinutes, [int]$MaxReviewMinutes, [int]$IdleTimeoutSec,
    [string]$Model, [string]$Complexity, [string]$Surface, [string]$LanguageHint,
    [string]$Goal, [string]$VisualCriteriaJson,
    [string]$AcceptanceTestCode, [string]$AcceptanceTestPath,
    [string]$CanonicalPackage, [int]$Concurrency,
    [switch]$EnableVisualCritique
)
$ErrorActionPreference = 'Stop'
# Record the dispatch so the test can prove whether the coder was REACHED.
Add-Content -Path $env:BLARAI_TEST_CODER_LOG -Value ("{0}`t{1}" -f $Task, ($Prompt -replace '[\\r\\n]+', ' '))
$n = @(Get-Content $env:BLARAI_TEST_CODER_LOG | Where-Object { $_ }).Count
# One RESULT body per dispatch, '||'-separated; the last entry repeats.
$bodies = @($env:BLARAI_TEST_CODER_RESULTS -split [regex]::Escape('||'))
$body = if ($n -le $bodies.Count) { $bodies[$n - 1] } else { $bodies[-1] }
# The report directory MUST be derived exactly as the real new-agent-task.ps1 derives it. A
# stub that follows a different convention than the coder it stands in for is mock-shape
# divergence on the very dimension #1075 changed - it briefly WAS, and this suite went green
# while the real pair disagreed and the guard inverted. That the REAL two scripts agree is
# proven elsewhere and deliberately not by this stub: test_fleet_script_agreement.py.
$reportDir = Join-Path (Join-Path $env:BLARAI_FLEET_AGENTIC_SETUP_DIR 'state') 'reports'
New-Item -ItemType Directory -Force $reportDir | Out-Null
$safeTask = $Task -replace '[^\\w\\-]', '-'
$repoName = Split-Path $Repo -Leaf
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$path = Join-Path $reportDir "$repoName-$safeTask-$stamp.txt"
Set-Content -Path $path -Value @("TASK: $Task", "RESULT: $body") -Encoding UTF8
"""

#: The toggle-off transform: neutralise the delivery predicate back to the pre-#1075 rule
#: ("run-fleet did not throw, therefore the task is done"). One anchored replacement of the
#: whole function reproduces the legacy guard exactly, because with the predicate always
#: true every dispatch is recorded done on its first pass and the budget never engages.
_PREDICATE_RE = re.compile(r"^function Test-TaskDelivered \{.*?^\}", re.MULTILINE | re.DOTALL)
_LEGACY_PREDICATE = (
    "function Test-TaskDelivered {\n"
    "    param([string]$ResultLine)\n"
    "    return $true   # TOGGLE-OFF: the pre-#1075 rule - a clean exit counts as delivery.\n"
    "}"
)


def _fleet_scripts_dir() -> Path:
    """The INSTALLED fleet's ``scripts/`` — the operator's override first (the same SSOT
    :func:`shared.fleet.dispatch.resolve_fleet_root` uses everywhere), else this host's
    compiled-in default.

    Derived from ``queue_path`` rather than read from ``scripts_dir``, and the distinction is
    load-bearing since #1181a: ``scripts_dir`` FOLLOWS A LIVE RUN'S PIN, while queue/runs
    deliberately stay on the state root. So during any pinned battery this function would
    silently return the MEASURED worktree's scripts, and the test below would grade a
    different `run-fleet.ps1` than the one it names — same test, different artifact, no
    signal. A silent retarget is worse than a red test, which is why this reads the field the
    pin does not touch."""
    cfg = build_default_config(resolve_fleet_root(FLEET_AGENTIC_SETUP_DIR_ENV) or None)
    return cfg.queue_path.parent.parent / "scripts"


def _assert_hermetic(script_path: Path) -> None:
    """HERMETICITY PRECONDITION — refuse to spawn a run-fleet.ps1 that would write into the
    OPERATOR'S live fleet state.

    The script derives ``state\\`` + ``reports\\`` from its fleet root, so whether this test is
    hermetic is decided entirely by whether the script reads that root from
    ``BLARAI_FLEET_AGENTIC_SETUP_DIR``. A build that still hardcodes it writes real run
    directories into a production tree (measured 2026-07-23: a pre-fix build created a live
    ``state/fleet-runs/R1075``).

    Honest limit — this is inspect-before-spawn, NOT structural impossibility. The fleet root
    is an absolute real path, so short of a filesystem sandbox nothing makes the write
    physically impossible; checking the script is the strongest lever available. It is
    therefore called at BOTH seams — install and spawn — so a future bypass has to defeat two
    places rather than one. Read "guarded", never "impossible"."""
    text = script_path.read_text(encoding="utf-8")
    assert FLEET_AGENTIC_SETUP_DIR_ENV in text, (
        f"the run-fleet.ps1 at {script_path} predates #1075: it does not resolve its fleet "
        f"root from {FLEET_AGENTIC_SETUP_DIR_ENV}, so running it here would write into the "
        "operator's REAL fleet state tree. THIS IS A CROSS-REPO LOCK and it is ordered — the "
        "agentic-setup half of #1075 must be merged (or pointed at via "
        f"{FLEET_AGENTIC_SETUP_DIR_ENV}) before this half can go green."
    )


def _install(tmp_path: Path, *, legacy_guard: bool = False) -> Path:
    """Lay out a throwaway fleet root: the REAL run-fleet.ps1, a fleet-lib that dot-sources
    the REAL library and stubs only the OVMS probe, and the stub coder. Returns the root."""
    src = _fleet_scripts_dir()
    root = tmp_path / "fleet"
    scripts = root / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)

    _assert_hermetic(src / "run-fleet.ps1")          # seam 1 of 2: before we even copy it
    text = (src / "run-fleet.ps1").read_text(encoding="utf-8")
    if legacy_guard:
        text, hits = _PREDICATE_RE.subn(_LEGACY_PREDICATE, text)
        assert hits == 1, (
            "the toggle-off could not find exactly one `function Test-TaskDelivered {...}` "
            f"block in run-fleet.ps1 (found {hits}) — if the predicate moved or was renamed, "
            "update this transform so the toggle keeps proving the lock sees the real defect"
        )
    (scripts / "run-fleet.ps1").write_text(text, encoding="utf-8")

    real_lib = (src / "fleet-lib.ps1").resolve()
    (scripts / "fleet-lib.ps1").write_text(
        f". '{real_lib.as_posix()}'\n"
        "function Get-LoadedModelId { param([int]$TimeoutSec = 3) return 'stub-coder-30b' }\n",
        encoding="utf-8",
    )
    (scripts / "new-agent-task.ps1").write_text(_STUB_CODER, encoding="utf-8")
    return root


class _Rig:
    """One fleet root + the environment the real script and the real Python caller share."""

    def __init__(self, tmp_path: Path, monkeypatch, *, legacy_guard: bool = False,
                 results: "list[str] | None" = None):
        self._monkeypatch = monkeypatch
        self.root = _install(tmp_path, legacy_guard=legacy_guard)
        self.config = build_default_config(self.root, tmp_path / "projects")
        self.repo = tmp_path / "projects" / "proj"
        self.repo.mkdir(parents=True, exist_ok=True)
        self.coder_log = tmp_path / "coder-dispatches.log"
        self.run_id = "R1075"
        monkeypatch.setenv(FLEET_AGENTIC_SETUP_DIR_ENV, str(self.root))
        monkeypatch.setenv("BLARAI_TEST_CODER_LOG", str(self.coder_log))
        self.set_results(results or [RESULT_NOTHING])

    def set_results(self, results: "list[str]") -> None:
        self._monkeypatch.setenv("BLARAI_TEST_CODER_RESULTS", "||".join(results))

    def dispatch(self, task_id: str = "add-card", prompt: str = "build the add-card form",
                 max_dispatches: "int | None" = None):
        # Seam 2 of 2. This is the ONLY place a child process is spawned, so re-checking the
        # INSTALLED copy here — not the source checked at install — catches what seam 1
        # cannot: a copy mutated after installation, and a rig assembled by some future route
        # that never ran _install. The env assertion catches the other half of the same
        # hazard: the script may honour the variable perfectly and still write to a
        # production tree if the variable has drifted off this rig's throwaway root.
        _assert_hermetic(self.root / "scripts" / "run-fleet.ps1")
        assert os.environ.get(FLEET_AGENTIC_SETUP_DIR_ENV) == str(self.root), (
            f"{FLEET_AGENTIC_SETUP_DIR_ENV} no longer points at this rig's throwaway root "
            f"({self.root}) — refusing to spawn rather than risk writing elsewhere"
        )
        task = {"repo": str(self.repo), "task": task_id, "prompt": prompt}
        if max_dispatches is None:
            return so.real_run_task(self.config, self.run_id, task)
        # `real_run_task` does not expose -MaxTaskDispatches, and the O1 resume case needs a
        # LARGER budget on a later invocation. Spawn the same script the same way with the one
        # extra flag, reusing the real queue writer and the real SUMMARY parser so only the
        # argv differs from the path above.
        qpath = so.write_single_task_queue(self.config, task)
        proc = subprocess.run(
            [_pwsh(), "-NoProfile", "-NonInteractive", "-File",
             str(self.config.scripts_dir / "run-fleet.ps1"),
             "-Queue", str(qpath), "-RunId", self.run_id,
             "-MaxTaskDispatches", str(max_dispatches)],
            capture_output=True, text=True, timeout=600,
        )
        # Check the spawn rather than trusting SUMMARY.txt to be fresh: a run-fleet that died
        # before writing it would leave the PREVIOUS invocation's file, and the caller would
        # assert against a stale row. It happens to fail closed today only because the two
        # branches' wordings differ — which is a coincidence, not a guarantee.
        assert proc.returncode == 0, (
            f"run-fleet exited {proc.returncode}; SUMMARY.txt may be the previous "
            f"invocation's:\n{proc.stdout}\n{proc.stderr}"
        )
        summary = self.config.runs_dir / self.run_id / "SUMMARY.txt"
        for oc in parse_summary(summary.read_text(encoding="utf-8", errors="replace")):
            if oc.task == task_id:
                return oc
        raise AssertionError(f"no SUMMARY row for {task_id}")

    @property
    def coder_calls(self) -> "list[str]":
        if not self.coder_log.exists():
            return []
        return [ln for ln in self.coder_log.read_text(encoding="utf-8").splitlines() if ln.strip()]

    @property
    def done(self) -> "list[str]":
        path = self.config.runs_dir / self.run_id / "done.txt"
        if not path.exists():
            return []
        return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]

    @property
    def journal(self) -> str:
        path = self.config.runs_dir / self.run_id / "journal.log"
        return path.read_text(encoding="utf-8") if path.exists() else ""


pytestmark = pytest.mark.skipif(
    shutil.which("pwsh") is None or not (_fleet_scripts_dir() / "run-fleet.ps1").exists(),
    reason=(
        "needs PowerShell 7 and the agentic-setup fleet install (the script under test lives "
        "in the sibling repo); an isolated worktree without it cannot drive the real path"
    ),
)


# ---------------------------------------------------------------------------
# The defect: an empty task must stay repairable inside its own run
# ---------------------------------------------------------------------------


def test_an_empty_task_is_not_recorded_done_and_a_repair_reaches_the_coder(tmp_path, monkeypatch):
    """B4's exact shape. The coder builds nothing (`RESULT: Nothing to merge.`); the layout
    fix cycle then re-dispatches the same task id with the unresolved imports named, and
    that re-dispatch must REACH the coder."""
    rig = _Rig(tmp_path, monkeypatch, results=[RESULT_NOTHING, RESULT_MERGED])

    first = rig.dispatch()
    assert first.result == "NOTHING", first.detail
    assert rig.done == [], "an empty task must not be recorded done — that is the defect"
    assert len(rig.coder_calls) == 1

    second = rig.dispatch(prompt="build the add-card form\n\nLAYOUT FIX (single focus)…")
    assert len(rig.coder_calls) == 2, "the repair re-dispatch never reached the coder"
    assert "LAYOUT FIX" in rig.coder_calls[1], "the repair prompt did not reach the coder"
    assert second.result == "MERGED", second.detail
    assert rig.done == ["add-card"], "the repaired task must now be recorded done"


def test_toggle_off_the_legacy_guard_refuses_the_same_repair(tmp_path, monkeypatch):
    """TOGGLE-OFF. With the delivery predicate neutralised to the pre-#1075 rule, the same
    scenario reproduces the defect: the empty task is recorded done and the repair is
    refused. Without this the passing test above could be an artefact of the harness."""
    rig = _Rig(tmp_path, monkeypatch, legacy_guard=True,
               results=[RESULT_NOTHING, RESULT_MERGED])

    first = rig.dispatch()
    assert first.result == "NOTHING", first.detail
    assert rig.done == ["add-card"], "the legacy guard should mark an empty task done"

    rig.dispatch(prompt="build the add-card form\n\nLAYOUT FIX (single focus)…")
    assert len(rig.coder_calls) == 1, (
        "the legacy guard was expected to REFUSE the repair re-dispatch; if the coder ran, "
        "the toggle no longer reproduces the defect and the lock above proves nothing"
    )


# ---------------------------------------------------------------------------
# The guard must keep doing its job
# ---------------------------------------------------------------------------


def test_a_delivered_task_is_still_skipped_on_redispatch(tmp_path, monkeypatch):
    """The guard's real purpose: work already merged into the project is never re-run."""
    rig = _Rig(tmp_path, monkeypatch, results=[RESULT_MERGED])

    first = rig.dispatch()
    assert first.result == "MERGED", first.detail
    assert rig.done == ["add-card"]

    second = rig.dispatch(prompt="build the add-card form\n\nLAYOUT FIX (single focus)…")
    assert len(rig.coder_calls) == 1, "a delivered task must NOT be re-dispatched"
    assert "SKIPPED" in (second.detail or ""), second.detail
    assert "TASK-SKIP-DONE" in rig.journal


def test_a_parked_task_is_retriable_because_nothing_reached_main(tmp_path, monkeypatch):
    """`NOT merged` parks the work on a branch — main is untouched, so it did not deliver.
    The branch-name interpolation also contains the word "merged"; the predicate must not
    be fooled by it."""
    rig = _Rig(tmp_path, monkeypatch, results=[RESULT_PARKED, RESULT_MERGED])

    first = rig.dispatch()
    assert first.result == "PARKED", first.detail
    assert rig.done == []

    rig.dispatch()
    assert len(rig.coder_calls) == 2


# ---------------------------------------------------------------------------
# …but the retries are bounded
# ---------------------------------------------------------------------------


def test_the_dispatch_budget_covers_the_initial_build_plus_every_repair_gate():
    """The budget must be at least the initial build plus the driver's THREE INDEPENDENT
    repair budgets, all of which can target the SAME plan-task id (#1075 F1).

    Sizing it to one repair re-creates this ticket's own defect at a new threshold: the layout
    fix succeeds, the app still fails to boot, and the executability repair is then refused by
    the BUDGET — surfacing to the operator as "the fix cycle did not resolve the boot failure"
    when no coder ever ran. A guard refusing a repair and being read as a failed repair is
    exactly what #1075 exists to stop, so a silent reduction here must fail loudly."""
    # #1075 N3: COUNT the driver's fix cycles rather than asserting a prose number. A literal
    # `>= 4` would let a fourth `_run_*_fix_cycle` land and recur F1 at threshold 5 with no lock
    # firing — the sizing side must be as self-maintaining as the enforcement side already is.
    #
    # LIMIT (#1075 O2), so the derivation is not read as complete: this scans for the NAMING
    # CONVENTION. A fourth repair gate called something else — `_repair_dependency_layout` —
    # is invisible to it and would recur F1 at threshold 5 with nothing firing. The `>= 3`
    # floor below catches a wholesale rename, not an off-convention addition. Inherent to
    # source-scanning; still strictly better than the prose literal it replaced.
    driver = (Path(sd.__file__)).read_text(encoding="utf-8")
    fix_cycles = re.findall(r"def (_run_\w*fix_cycle)\b", driver)
    assert len(fix_cycles) >= 3, (
        f"only {fix_cycles} fix cycles found in swap_driver.py — if they were renamed, update "
        "this derivation; do not delete the lock"
    )
    required = 1 + len(fix_cycles)  # the initial build, plus one repair per independent gate

    text = (_fleet_scripts_dir() / "run-fleet.ps1").read_text(encoding="utf-8")
    match = re.search(r"\$MaxTaskDispatches\s*=\s*(\d+)", text)
    assert match is not None, "run-fleet.ps1 no longer declares a $MaxTaskDispatches default"
    assert int(match.group(1)) >= required, (
        f"the dispatch budget default is {match.group(1)}, below the {required} the driver can "
        f"demand for ONE task id: the initial build plus {', '.join(fix_cycles)} — each an "
        "independent budget able to target the same task"
    )


def _budget_default() -> int:
    text = (_fleet_scripts_dir() / "run-fleet.ps1").read_text(encoding="utf-8")
    match = re.search(r"\$MaxTaskDispatches\s*=\s*(\d+)", text)
    assert match is not None
    return int(match.group(1))


def test_retries_are_bounded_so_a_never_delivering_task_cannot_loop(tmp_path, monkeypatch):
    """A task that never delivers gets its dispatch budget and no more. The budget is read
    from the script rather than hardcoded here — the sibling test above owns whether the
    number is RIGHT; this one owns whether it is ENFORCED, and the two must not rot together."""
    budget = _budget_default()
    rig = _Rig(tmp_path, monkeypatch, results=[RESULT_NOTHING])

    # budget + 2: one dispatch past the budget to prove the refusal, and one past THAT so the
    # skip branch runs and F4's "which of the three ways did it get onto done.txt" is exercised.
    for _ in range(budget + 2):
        rig.dispatch()

    assert len(rig.coder_calls) == budget, (
        "the dispatch budget did not bound the retries — a repeatedly-empty task would loop"
    )
    assert rig.done == ["add-card"], "a spent budget must become terminal, not a silent hole"
    assert "TASK-BUDGET-SPENT" in rig.journal
    # F4: the console must not then claim the task "already delivered" — it plainly did not.
    assert "already delivered" not in rig.journal, (
        "a budget-spent task is being reported as delivered; the dispatch ledger already "
        "distinguishes the two, so this is a plain falsehood in the operator's trail"
    )
    assert "budget was spent without delivering" in rig.journal


def test_every_path_onto_done_txt_records_its_own_reason():
    """#1075 O1 — the STRUCTURAL control, checked structurally.

    Three point-fixes to one ``if/elseif/else`` proved the skip cannot deduce why a task is
    terminal: it claimed "delivered" for a spent budget (F4), "budget spent" for a task that
    delivered on its last permitted dispatch (N1), and "never dispatched" for one that was
    (O1). The control is that every writer RECORDS its reason and the skip LOOKS IT UP, so
    there is no branch left to get wrong — and that property is a source fact, not a
    behaviour, so it is asserted against the source. A fourth writer added with a bare
    ``Add-Content $DoneList`` would silently restore the whole defect class."""
    text = (_fleet_scripts_dir() / "run-fleet.ps1").read_text(encoding="utf-8")
    assert re.search(r"^function Set-TaskDone\b", text, re.MULTILINE), (
        "Set-TaskDone is gone — it is the single writer that keeps the fact and the reason "
        "together; if it was renamed, update this lock rather than deleting it"
    )
    # Every append to done.txt must go through that one writer (its own line is $script:DoneList).
    #
    # LIMIT (#1075 P3), the same honesty O2 carries: this scans ONE IDIOM. A writer spelled
    # `Add-Content -Path $DoneList -Value …` or `$script:DoneList` is invisible to it. That is
    # survivable rather than fine, and only because it is the OUTER of two layers: measured
    # against an off-convention writer, 8 of the behavioural tests in this file go red. A
    # fourth writer would have to be spelled off-convention AND be behaviourally inert across
    # all eight to slip both — which is the point of having two layers rather than one.
    stray = [ln.strip() for ln in text.splitlines()
             if re.search(r"Add-Content\s+\$DoneList\b", ln)]
    assert stray == [], (
        f"done.txt is appended outside Set-TaskDone at: {stray} — that writer records no "
        "reason, so the skip would fall back to 'not recorded' or, worse, someone would "
        "re-add a predicate to deduce it. Route it through Set-TaskDone."
    )
    # And the skip must LOOK UP, never deduce.
    assert "$doneReason.ContainsKey($taskId)" in text, (
        "the skip no longer looks the reason up in the recorded map — if it has gone back to "
        "deducing from the dispatch ledger or the budget, that is the F4/N1/O1 class returning"
    )


def test_a_task_made_terminal_by_its_budget_is_not_called_never_dispatched(
        tmp_path, monkeypatch):
    """#1075 O1 case (b), reproduced without any crash: a task made terminal by its budget,
    then resumed under a LARGER ``-MaxTaskDispatches``. Both are documented features. The old
    predicate asked ``spentForTask >= MaxTaskDispatches`` — 4 >= 8 is false — so it fell to the
    catch-all and told the operator a task that had been dispatched four times was "never
    dispatched", in the SUMMARY row the driver parses."""
    budget = _budget_default()
    rig = _Rig(tmp_path, monkeypatch, results=[RESULT_NOTHING])
    for _ in range(budget + 1):
        rig.dispatch()
    assert "TASK-BUDGET-SPENT" in rig.journal, "the setup did not exhaust the budget"

    final = rig.dispatch(max_dispatches=budget * 2)

    assert "never being dispatched" not in (final.detail or ""), final.detail
    assert "budget was spent without delivering" in (final.detail or ""), final.detail
    assert len(rig.coder_calls) == budget, "raising the budget must not reopen a terminal task"


def test_an_unrecorded_reason_says_so_instead_of_guessing(tmp_path, monkeypatch):
    """#1075 O1 case (a): a task on ``done.txt`` with no recorded reason. A kill between the
    two writes produces it — this subtree really is tree-killed, by the per-task ceiling and
    the budget watchdog — and so does the far commoner case of a run directory written before
    this feature existed and resumed after it, which is every run directory on disk today.

    The fact is written first, so the task stays terminal (already-merged work is never
    re-dispatched); the reason is then simply absent, and the skip must say exactly that and
    stop. Simulated by truncating the reason ledger, which is the state both causes leave."""
    rig = _Rig(tmp_path, monkeypatch, results=[RESULT_MERGED])
    rig.dispatch()
    assert rig.done == ["add-card"]
    reasons = rig.config.runs_dir / rig.run_id / "done-reasons.txt"
    assert reasons.exists(), "no reason ledger — the reason is being deduced again"
    reasons.write_text("", encoding="utf-8")

    final = rig.dispatch()

    assert len(rig.coder_calls) == 1, "the task must stay terminal — the FACT survived"
    assert "the reason is not recorded" in (final.detail or ""), final.detail
    # #1075 P1: it must not name a CAUSE either. "Interrupted between the two writes" was one
    # cause presented as the cause, which is the same defect class one layer down — and it
    # would be wrong for every pre-existing run directory resumed after this lands.
    for cause in ("interrupted", "crash", "killed"):
        assert cause not in (final.detail or "").lower(), (
            f"the skip asserts a cause ({cause!r}) it cannot know"
        )
    for invented in ("already delivered", "never being dispatched", "budget was spent"):
        assert invented not in (final.detail or ""), (
            f"the reason was lost but the skip claims {invented!r} — a confident wrong answer "
            "is what the whole O1 control exists to prevent"
        )


def test_delivering_on_the_LAST_permitted_dispatch_is_still_reported_as_delivered(
        tmp_path, monkeypatch):
    """#1075 N1 — the boundary. A task that delivers on its final permitted dispatch has ALSO
    spent its whole budget, so the two states are indistinguishable from ``done.txt`` alone and
    a reason inferred from the dispatch ledger reports a success as a failure.

    That is F4's own class one step further out, and it reaches further than the console: the
    same string rides the ``TASK-SKIP-DONE`` journal line and the SUMMARY row that
    ``parse_summary`` feeds the driver and ``/dispatch status``. The sibling test above cannot
    see it — it asserts ``"already delivered" not in journal`` for a run where the task never
    delivered, which is the wrong string in the wrong run."""
    budget = _budget_default()
    rig = _Rig(tmp_path, monkeypatch,
               results=[RESULT_NOTHING] * (budget - 1) + [RESULT_MERGED])

    for _ in range(budget):
        rig.dispatch()
    assert len(rig.coder_calls) == budget, "the setup did not reach the boundary"
    assert rig.done == ["add-card"], "the final dispatch delivered, so it must be recorded done"

    # The documented -RunId resume re-walks the queue; this is that walk.
    final = rig.dispatch()

    assert len(rig.coder_calls) == budget, "a delivered task must not be re-dispatched"
    assert "budget was spent without delivering" not in rig.journal, (
        "the task DELIVERED on its last permitted dispatch and is being reported as a "
        "budget failure — in the console, the journal and the SUMMARY row the driver parses"
    )
    assert "already delivered" in rig.journal
    assert "already delivered" in (final.detail or ""), final.detail


def test_the_budget_is_consumed_before_the_coder_runs(tmp_path, monkeypatch):
    """The ledger is written BEFORE the coder is spawned, so a dispatch that is tree-killed
    (the per-task ceiling / the budget watchdog kill this whole subtree) still costs its
    budget. Recording it afterwards would let a wedging task be re-dispatched forever."""
    rig = _Rig(tmp_path, monkeypatch, results=[RESULT_NOTHING])
    rig.dispatch()
    ledger = rig.config.runs_dir / rig.run_id / "dispatches.txt"
    assert ledger.exists(), "no dispatch ledger — the retry bound has nothing to count"
    assert [ln.strip() for ln in ledger.read_text(encoding="utf-8").splitlines() if ln.strip()] == [
        "add-card"
    ]


# ---------------------------------------------------------------------------
# The cross-repo root must be resolved from ONE place
# ---------------------------------------------------------------------------


def test_the_spawn_seam_refuses_what_the_install_seam_already_passed(tmp_path, monkeypatch):
    """The second lock, tested OFF. Seam 1 vetted the source at install time and passed; the
    installed copy is then mutated to drop the fleet-root resolution, which is exactly the
    shape seam 1 can no longer see. The spawn must refuse rather than write into a production
    tree — one lock on this door is a design smell."""
    rig = _Rig(tmp_path, monkeypatch, results=[RESULT_MERGED])
    rig.dispatch()  # green through both seams first, so the refusal below is the mutation

    script = rig.root / "scripts" / "run-fleet.ps1"
    script.write_text(
        script.read_text(encoding="utf-8").replace(FLEET_AGENTIC_SETUP_DIR_ENV, "NOPE"),
        encoding="utf-8",
    )
    with pytest.raises(AssertionError, match="predates #1075"):
        rig.dispatch(task_id="other-task")


def test_the_spawn_seam_refuses_a_fleet_root_variable_that_drifted(tmp_path, monkeypatch):
    """The other half of the same hazard: the script honours the variable perfectly, but the
    variable no longer names this rig's throwaway root."""
    rig = _Rig(tmp_path, monkeypatch, results=[RESULT_MERGED])
    monkeypatch.setenv(FLEET_AGENTIC_SETUP_DIR_ENV, str(tmp_path / "somewhere-else"))
    with pytest.raises(AssertionError, match="no longer points at this rig"):
        rig.dispatch()


def test_run_fleet_honours_the_same_fleet_root_variable_python_resolves(tmp_path, monkeypatch):
    """``real_run_task`` writes the queue under, and reads SUMMARY.txt back out of, the root
    :func:`resolve_fleet_root` gives it. The script must derive its own state\\ tree from the
    SAME variable, or an operator override silently splits the two halves apart."""
    rig = _Rig(tmp_path, monkeypatch, results=[RESULT_MERGED])
    rig.dispatch()
    assert (rig.config.runs_dir / rig.run_id / "SUMMARY.txt").exists(), (
        "run-fleet wrote its run directory somewhere other than the resolved fleet root"
    )
    assert os.environ[FLEET_AGENTIC_SETUP_DIR_ENV] == str(rig.root)
