"""#1075 F2 — ``run-fleet.ps1`` and ``new-agent-task.ps1`` must agree, or the dedup guard inverts.

The guard added in #1075 decides whether a task is recorded done by SCRAPING the report
directory for the coder's ``RESULT:`` line. That makes two things load-bearing across a script
boundary that nothing previously checked:

  1. **Where reports live.** ``run-fleet.ps1`` writes the run tree under the fleet root it
     resolves; ``new-agent-task.ps1`` writes the report the scrape reads. #1075 taught
     run-fleet to resolve that root from ``BLARAI_FLEET_AGENTIC_SETUP_DIR`` (the SSOT
     :func:`shared.fleet.dispatch.resolve_fleet_root` already used on the Python side) while
     new-agent-task still hardcoded it. Set the override and the scrape reads a directory the
     coder never writes to: an empty ``$resultLine`` for EVERY task, so every task — a MERGED
     one included — reads as non-delivering, already-merged work is re-dispatched, and the
     outcomes decay to the "no SUMMARY line" shape ``relabel_unexplained_kill`` reads as a
     possible tree-kill. The fix made this ticket's own "a MERGED task is still skipped" lock
     defeatable by an environment variable.
  2. **What the coder's RESULT line says.** ``Test-TaskDelivered`` classifies the five bodies
     ``new-agent-task.ps1`` emits. It is coupled to that wording — the secret-scan BLOCKED body
     is only classified correctly because it contains the word "blocked"; drop that word
     upstream and the ``-match 'merged'`` fallback (the body says "nothing was committed or
     merged") would record a secret-blocked task as DELIVERED.

Both couplings are real and neither is visible from one repo. The suite that drives run-fleet
end to end cannot see either: its stub coder is written against the NEW convention while the
real coder held the OLD one, which is mock-shape divergence on exactly the dimension #1075
changed — the canonical failure this project names first. So these locks read the REAL scripts
and EXECUTE the real resolutions under ``pwsh`` rather than trusting either side's stub.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from shared.fleet.dispatch import FLEET_AGENTIC_SETUP_DIR_ENV, _pwsh
from shared.tests.test_fleet_dedup_guard import (
    RESULT_MERGED,
    RESULT_NOTHING,
    RESULT_PARKED,
    _PREDICATE_RE,
    _fleet_scripts_dir,
)

#: The two remaining bodies from ``new-agent-task.ps1``'s RESULT expression, so all five real
#: shapes are exercised. The other three are imported above — one definition, not two (the
#: #1075 F5 lesson: two copies of a check drift apart and nobody notices).
RESULT_BLOCKED = (
    "BLOCKED: a potential secret was detected, so nothing was committed or merged. "
    "Your changes are left UNCOMMITTED in C:/wt/add-card for review."
)
RESULT_NO_CHANGE = (
    "Nothing to merge - the coder explicitly declared NO CHANGE NEEDED: the task appears "
    "already satisfied by the current project (see the NO-CHANGE DECLARED line above; an "
    "honest no-change outcome, not a failure to produce)."
)
#: #1074 (fail-loud git capture) landed on agentic-setup main after this file's own predecessor
#: was written against a 5-shape script; the merge with #1075 combined both, and the sixth-shape
#: lock (below) caught it correctly. Two more real bodies, both real prose from the shipped
#: script, added here rather than left for the predicate's fallback to classify by accident.
RESULT_ERRORED = (
    "ERRORED: the stage/commit step failed (git commit failed), so the coder's work was never "
    "captured - see the CAPTURE FAULT line above for git's own message. Any work is left "
    "UNCOMMITTED in C:/wt/add-card. This run measures the BOX, not the model: do not read it as "
    "a coder no-op."
)
RESULT_CAPTURE_FAULT_ELSEWHERE = (
    "Nothing to merge from the selected candidate - but another candidate FAULTED before its "
    "work could be captured (see CAPTURE FAULT above). Nothing was lost from the selected "
    'candidate, but do NOT read this run as a clean "the coder produced nothing" result.'
)

#: RESULT body -> is it a DELIVERY? Only work that reached the project's main line counts.
EXPECTED_VERDICTS = {
    RESULT_MERGED: True,
    RESULT_NOTHING: False,
    RESULT_PARKED: False,
    RESULT_BLOCKED: False,
    RESULT_NO_CHANGE: False,
    RESULT_ERRORED: False,
    RESULT_CAPTURE_FAULT_ELSEWHERE: False,
}

#: Lines that participate in resolving each script's report directory. Collected in file order
#: and evaluated as a unit, so this drives the REAL resolution rather than pattern-matching an
#: intent. Anchored at column 0 to avoid picking up assignments nested inside a block.
_RESOLUTION_RE = re.compile(
    r"^\$(?:Setup|StateDir|FleetRoot|ReportDir)\s*=.*$", re.MULTILINE)


def _pwsh_available() -> bool:
    return shutil.which("pwsh") is not None or shutil.which("powershell") is not None


pytestmark = pytest.mark.skipif(
    not _pwsh_available() or not (_fleet_scripts_dir() / "run-fleet.ps1").exists(),
    reason=("needs PowerShell and the agentic-setup fleet install (the scripts under test live "
            "in the sibling repo); an isolated worktree without it cannot read them"),
)


def _run_pwsh(script: str, tmp_path: Path, env_root: "str | None") -> list[str]:
    """Execute *script* and return its stdout lines. ``env_root`` sets (or clears) the fleet
    root override for the child only — never for this process."""
    path = tmp_path / "probe.ps1"
    path.write_text(script, encoding="utf-8")
    import os

    env = dict(os.environ)
    if env_root is None:
        env.pop(FLEET_AGENTIC_SETUP_DIR_ENV, None)
    else:
        env[FLEET_AGENTIC_SETUP_DIR_ENV] = env_root
    proc = subprocess.run(
        [_pwsh(), "-NoProfile", "-NonInteractive", "-File", str(path)],
        capture_output=True, text=True, env=env, timeout=120,
    )
    assert proc.returncode == 0, f"probe failed: {proc.stdout}\n{proc.stderr}"
    return [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]


def _report_dir_of(script_name: str, tmp_path: Path, env_root: "str | None") -> str:
    """Evaluate ONE script's real report-directory resolution."""
    text = (_fleet_scripts_dir() / script_name).read_text(encoding="utf-8")
    lines = _RESOLUTION_RE.findall(text)
    assert lines, (
        f"no report-directory resolution found in {script_name} — the anchored assignments "
        "moved or were renamed; update this extraction rather than deleting the lock"
    )
    assert any("$ReportDir" in ln for ln in lines), (
        f"{script_name} no longer assigns $ReportDir at column 0"
    )
    body = "\n".join(lines) + "\nWrite-Output $ReportDir\n"
    out = _run_pwsh(body, tmp_path, env_root)
    assert out, f"{script_name}'s resolution produced no path"
    return out[-1]


# ---------------------------------------------------------------------------
# 1. Where reports live
# ---------------------------------------------------------------------------


def test_both_scripts_resolve_the_same_report_dir_under_an_override(tmp_path):
    """The F2 defect, executed. With the fleet-root override set, the writer and the scraper
    must land on the SAME directory — otherwise the scrape is blind and every task, MERGED
    included, reads as non-delivering."""
    root = str(tmp_path / "fleet-root")
    writer = _report_dir_of("new-agent-task.ps1", tmp_path, root)
    scraper = _report_dir_of("run-fleet.ps1", tmp_path, root)
    assert writer == scraper, (
        "the coder writes its report to a different directory than run-fleet scrapes, so "
        f"every task would read as non-delivering: coder={writer!r} run-fleet={scraper!r}"
    )
    assert root.lower() in writer.lower(), (
        f"the override was ignored — {writer!r} does not sit under {root!r}"
    )


def test_both_scripts_agree_on_the_compiled_default_when_no_override_is_set(tmp_path):
    """Non-regression: with no override the pair must still agree, and must still land on this
    host's compiled-in fleet root — the shipped behaviour nothing may change silently."""
    writer = _report_dir_of("new-agent-task.ps1", tmp_path, None)
    scraper = _report_dir_of("run-fleet.ps1", tmp_path, None)
    assert writer == scraper, f"coder={writer!r} run-fleet={scraper!r}"
    assert writer.replace("/", "\\").lower().endswith("\\state\\reports")


# ---------------------------------------------------------------------------
# 2. What the coder's RESULT line says
# ---------------------------------------------------------------------------


def test_the_delivery_predicate_classifies_every_real_result_body(tmp_path):
    """Drive ``Test-TaskDelivered`` — lifted verbatim out of the real run-fleet.ps1 — over the
    five bodies ``new-agent-task.ps1`` really emits. This is the lock that makes the predicate's
    coupling to the coder's wording a GATED coupling instead of a silent one."""
    text = (_fleet_scripts_dir() / "run-fleet.ps1").read_text(encoding="utf-8")
    match = _PREDICATE_RE.search(text)
    assert match is not None, (
        "Test-TaskDelivered is gone from run-fleet.ps1 — if the predicate was renamed or "
        "restructured, update this lock; do not delete it"
    )
    bodies = list(EXPECTED_VERDICTS)
    payload = tmp_path / "bodies.json"
    payload.write_text(json.dumps([f"RESULT: {b}" for b in bodies]), encoding="utf-8")
    script = (
        match.group(0)
        + f"\n$bodies = Get-Content -Raw '{payload.as_posix()}' | ConvertFrom-Json\n"
        "foreach ($b in $bodies) { Write-Output (Test-TaskDelivered $b) }\n"
    )
    verdicts = [ln == "True" for ln in _run_pwsh(script, tmp_path, None)]
    assert len(verdicts) == len(bodies)
    for body, got in zip(bodies, verdicts):
        assert got is EXPECTED_VERDICTS[body], (
            f"Test-TaskDelivered returned {got} for {body[:60]!r}…; expected "
            f"{EXPECTED_VERDICTS[body]}. The coder's RESULT wording and run-fleet's predicate "
            "have drifted apart — fix the predicate, not this expectation"
        )


def test_a_sixth_result_shape_cannot_appear_unnoticed():
    """#1075 N2 — the verdict table covers the five shapes that exist TODAY, and nothing stopped
    a sixth from being added and silently taking whatever ``-match 'merged'`` happened to say.
    That is not hypothetical: #1049 added "Nothing to merge - NO CHANGE NEEDED" as a first-class
    outcome and is already on agentic-setup main. Count the branches of the coder's RESULT
    expression and require the table to have kept up."""
    text = (_fleet_scripts_dir() / "new-agent-task.ps1").read_text(encoding="utf-8")
    result_lines = [ln for ln in text.splitlines() if ln.lstrip().startswith("RESULT:")]
    assert len(result_lines) == 1, (
        f"expected exactly one RESULT expression in new-agent-task.ps1, found "
        f"{len(result_lines)} — this extraction assumes one"
    )
    expr = result_lines[0]
    # `$(if (…) {…} elseif (…) {…} … else {…})` — one branch per outcome the coder can report.
    branches = (1 + len(re.findall(r"\belseif\b", expr))
                + (1 if re.search(r"\belse\s*\{", expr) else 0))
    assert branches == len(EXPECTED_VERDICTS), (
        f"the coder's RESULT expression now has {branches} branches but the delivery table "
        f"covers {len(EXPECTED_VERDICTS)}. A RESULT shape has appeared or gone and nothing has "
        "decided whether it counts as DELIVERY — give it an explicit verdict in "
        "EXPECTED_VERDICTS rather than letting the predicate's fallback decide by accident"
    )


def test_the_coders_result_wording_still_carries_the_markers_the_predicate_keys_on(tmp_path):
    """The other direction. The predicate reads WORDS out of prose the coder writes; the
    BLOCKED body in particular classifies correctly only because it contains "blocked" — its
    own text says "nothing was committed or merged", so losing that one word would flip a
    secret-blocked task to DELIVERED. Assert the markers are still in the coder's source."""
    text = (_fleet_scripts_dir() / "new-agent-task.ps1").read_text(encoding="utf-8")
    result_lines = [ln for ln in text.splitlines() if ln.lstrip().startswith("RESULT:")]
    assert result_lines, "no RESULT: expression found in new-agent-task.ps1"
    blob = " ".join(result_lines).lower()
    for marker in ("blocked", "merged", "not merged", "nothing to merge"):
        assert marker in blob, (
            f"the coder's RESULT wording no longer contains {marker!r}, which "
            "Test-TaskDelivered keys on — re-derive the predicate against the new wording"
        )
