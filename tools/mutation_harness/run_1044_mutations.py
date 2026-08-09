"""Mutation harness for #1044 (S3 slice D): prove each lock goes RED against the bug it guards.

**DEV TOOLING. NOT SHIPPED, NOT IMPORTABLE.** Nothing under ``shared/``, ``services/`` or
``launcher/`` may import this, and it sits deliberately outside the standing gate's selection
(``shared/ services/ launcher/ tests/integration/ tests/security/``). The filename carries no
``test_`` prefix and no ``_test`` suffix so pytest cannot collect it by accident: a harness that
rewrites source files and shells out to pytest must never fire inside the gate it exists to
audit.

WHAT IT DOES
------------
Applies one textual mutation to a source file, runs the two #1044 suites, records which tests
died, restores the file, repeats. A mutation that leaves the suites GREEN names a lock that
cannot see the defect it claims to guard — the failure class this slice was about. It reports
survivors, not passes.

WHAT IT CANNOT DO, STATED PLAINLY
---------------------------------
* **The mutation set is authored FOR #1044.** Every entry anchors on a literal string in
  ``acceptance.py`` / ``bad_input_floor.py`` / ``oracle_qa.py`` as those files stood at
  ``afa40bf7``. It measures the locks around the bad-input exam floor and nothing else. A
  different change needs a different set; running this against unrelated work would report a
  clean sweep of mutations that no longer describe anything.
* **It proves locks can fail, not that the feature is correct.** Zero survivors means every
  mutation was caught by a named test. It says nothing about defects no mutation encodes.
* **An anchor that stops matching is REPORTED, never skipped.** ``ANCHOR MISSING`` counts as a
  SURVIVOR, because a mutation that silently fails to apply shrinks the measured set while the
  output still reads as a pass. That has fired twice for real, both times after a refactor moved
  the code an anchor quoted.

THE TWO GUARDS, AND WHY THEY ARE DIFFERENT
------------------------------------------
They look alike and catch opposite mistakes; conflating them is how both went missing.

* :func:`_refuse_poisoned_baseline` catches a **dirty tree**. The restore baseline is read from
  the working tree, so source stranded by a run that died mid-mutation would silently become the
  next run's baseline, be "restored" to, and print success. The baseline therefore comes from
  ``HEAD``, and the harness refuses to start when a file it mutates already differs.
* :func:`_print_anchor` catches a **wrong tree**, which the guard above cannot see at all: a
  checkout at the wrong commit is perfectly clean relative to its own ``HEAD``. So every run
  names its subject — path and commit — at the top and again on the tail line, because the
  banner scrolls away and the figure is what gets quoted. ``0 of 29 survived`` is a true sentence
  about an unnamed tree until the tree is named.

NEITHER GUARD CAN SEE A **BUSY** TREE — DOCUMENTED, NOT FIXED
-------------------------------------------------------------
A run in flight is indistinguishable from a crashed one by inspection. This harness spends most
of its wall time with a source file deliberately broken; it spawns ``python.exe -m pytest``
rather than a ``pytest`` image, so a process check by name finds nothing; and there is a
sub-second window between the subprocess exiting and the restore write where the file is mutated
and truly nothing is running. An observer inventorying the tree in that state sees exactly what a
stranded mutation looks like. That produced one confident, written-down, false "a run died here"
during this slice's own verification, at mutation 29 of 29 — the run completed normally seconds
afterwards.

:func:`_refuse_poisoned_baseline` inherits the confusion. Pointed at a tree with a live run it
refuses: the right OUTCOME through the wrong DIAGNOSIS, reporting a poisoned baseline for what is
actually a busy tree. It fails safe, which is why this is documented rather than fixed — but the
distinction matters more than the outcome, because **a control that is right for the wrong reason
gets trusted for the wrong reason the next time it fires.** Making the two states distinguishable
— a run-marker written before the first mutation and removed in the same ``finally`` that
restores — is a named follow-up on this harness's review, not a silent gap.

USAGE
-----
``python tools/mutation_harness/run_1044_mutations.py <throwaway-worktree> [--allow-dirty]``

The target is MUTATED, so it must be a throwaway detached worktree — never a branch tree under
review and never the primary checkout, both of which are refused outright. Create one with
``git worktree add --detach <path> <branch>``.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

#: The checkout this file is committed in — used only to locate the interpreter and to refuse
#: mutating itself. Never mutated.
_SELF_REPO = pathlib.Path(__file__).resolve().parents[2]


def _require_root() -> pathlib.Path:
    """The tree this harness MUTATES, taken from argv[1]. There is deliberately NO DEFAULT.

    It writes deliberately-broken source and relies on a ``finally`` to restore it, so it must
    never point at a tree anyone reads as a commit: one crash, kill, timeout or power event
    mid-run leaves a mutated ``acceptance.py`` sitting there for the next actor to read as the
    branch. A default path would eventually go stale and silently name the wrong tree, which is
    the failure the anchor banner exists to make visible — so the caller must say it out loud.

    Refused: any tree whose ``HEAD`` is attached to a branch. That is the real rule, and it
    covers the primary checkout and every named-branch worktree without hard-coding anyone's
    paths. A detached worktree is nobody's branch, so a stranded mutation there strands nothing.
    """
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        raise SystemExit(
            "usage: run_1044_mutations.py <throwaway-detached-worktree> [--allow-dirty]\n"
            "  create one with: git worktree add --detach <path> <branch>"
        )
    root = pathlib.Path(args[0])
    if not root.is_dir():
        raise SystemExit(f"mutation root {root} does not exist.")
    if root.resolve() == _SELF_REPO:
        raise SystemExit(f"REFUSED: {root} is the checkout this harness lives in.")
    branch = subprocess.run(["git", "symbolic-ref", "--quiet", "HEAD"], cwd=str(root),
                            capture_output=True, text=True)
    if branch.returncode == 0:
        raise SystemExit(
            f"REFUSED: {root} has HEAD attached to {branch.stdout.strip()} — it is a tree "
            "someone reads as the commit, and a run that dies mid-mutation would strand broken "
            "source in it. Use a throwaway DETACHED worktree "
            "(git worktree add --detach <path> <branch>)."
        )
    return root


ROOT = _require_root()

ACC = ROOT / "shared/fleet/acceptance.py"
RULER = ROOT / "shared/fleet/bad_input_floor.py"
QA = ROOT / "shared/fleet/oracle_qa.py"

#: The project venv if it is there, else whatever is running this. The system python lacks
#: ``cryptography`` and dies at pytest collection, so the venv is strongly preferred.
_VENV_PY = _SELF_REPO / ".venv" / "Scripts" / "python.exe"
PY = str(_VENV_PY) if _VENV_PY.exists() else sys.executable

#: LOCALAPPDATA redirect for every pytest invocation. NON-NEGOTIABLE: an unredirected run has
#: corrupted the operator's real sessions.db before. Derived per-root so two harness runs cannot
#: share a data dir, and never the real one.
_LOCALAPPDATA = pathlib.Path(os.environ.get("TEMP", "/tmp")) / f"mutation-harness-{ROOT.name}"
_LOCALAPPDATA.mkdir(parents=True, exist_ok=True)

MUTATIONS = [
    # --- the three review blockers: each mutation restores the bug the fix removed ---
    ("F1a: call sites MERGED again across positional and keyword",
     RULER,
     "        if shape not in shapes_by_target[key] and len(shapes_by_target[key]) < _MAX_SHAPES:\n"
     "            shapes_by_target[key].append(shape)",
     "        merged_pos = max([positional] + [s[0] for s in shapes_by_target[key]])\n"
     "        merged_kw = tuple(dict.fromkeys(\n"
     "            [k for s in shapes_by_target[key] for k in s[1]] + list(keywords)))\n"
     "        shapes_by_target[key] = [(merged_pos, merged_kw)]"),

    ("F1b: bind check disabled (an unbindable row counts as reached)",
     RULER,
     # Anchored on the CODE, not the docstring: the previous anchor quoted the one-line
     # docstring and went stale the moment that docstring grew, which the harness reported as
     # ANCHOR MISSING rather than passing silently.
     "    try:\n        signature = {_EMIT_PREFIX}inspect.signature(fn)",
     "    return True\n    try:\n        signature = {_EMIT_PREFIX}inspect.signature(fn)"),

    ("F1c: never-bound alarm removed (a probe that measured nothing reports green)",
     RULER,
     "    if not reached:",
     "    if False:"),

    ("F1d: under-determined f(*args) sites driven anyway",
     RULER,
     "        if call.starargs or call.starkwargs:",
     "        if False and call.starargs:"),

    ("F2: single-task exam never floored (compile_prompts sees the pre-floor exam)",
     ACC,
     "        oracle_code = _ensure_bad_input_floor(oracle_code, spec)\n",
     ""),

    ("F3a: floor tests back in the F2P vacuity set (job exam gets REFUSED)",
     QA,
     "            passed = _discriminating_tests(_passed_tests(blob))",
     "            passed = _passed_tests(blob)"),

    # --- N1/N2: the round after the second review ---
    ("N2: over-wide call site TRUNCATED to the cap instead of skipped",
     RULER,
     "        if positional > _MAX_POSITIONAL:\n            continue",
     "        positional = min(positional, _MAX_POSITIONAL)\n        if False:\n            continue"),

    ("N1: ruler no longer imported on the F2P path (docstrings would UNDERclaim)",
     QA,
     "    from shared.fleet.bad_input_floor import FLOOR_TEST_PREFIX\n\n    return [name for name in passed if not name.startswith(FLOOR_TEST_PREFIX)]",
     '    return [name for name in passed if not name.startswith("test_bad_input_floor__")]'),

    # --- F6/F7: the naming contract and the duck-typed filler, one behaviour at a time ---
    ("F6: emit prefix removed (helpers shadow a model-authored exam's own symbols)",
     RULER,
     '_EMIT_PREFIX = "_bif_"',
     '_EMIT_PREFIX = ""'),

    ("F7a: BadValue.__getitem__ raises (a lookup stops the probe at the door)",
     RULER,
     "    def __getitem__(self, key):\n        return 0",
     "    def __getitem__(self, key):\n        raise TypeError('not subscriptable')"),

    ("F7b: BadValue.__call__ raises (a callback argument is rejected)",
     RULER,
     "    def __call__(self, *args, **kwargs):\n        return 0",
     "    def __call__(self, *args, **kwargs):\n        raise TypeError('not callable')"),

    ("F7c: BadValue.__iter__ raises (a loop over it cannot proceed)",
     RULER,
     "    def __iter__(self):\n        return iter((self,))",
     "    def __iter__(self):\n        raise TypeError('not iterable')"),

    ("F7d: BadValue.__iter__ yields a plain value instead of itself",
     RULER,
     "    def __iter__(self):\n        return iter((self,))",
     "    def __iter__(self):\n        return iter((0,))"),

    ("F7e: BadValue is falsy (an `if not x: raise` guard rejects it)",
     RULER,
     "    def __bool__(self):\n        return True",
     "    def __bool__(self):\n        return False"),

    ("F7f: BadValue.__len__ raises",
     RULER,
     "    def __len__(self):\n        return 1",
     "    def __len__(self):\n        raise TypeError('no len')"),

    ("F7g: BadValue repr carries a heap address (failure fingerprints stop matching)",
     RULER,
     '        return "<malformed>"',
     "        return object.__repr__(self)"),

    # --- the original twelve, re-run ---
    ("gate collapses onto the already-LIVE advanced_intake flag",
     ACC,
     "if bad_input_floor and advanced_intake and not _is_card_driven(repo, decomposition_override):",
     "if advanced_intake and not _is_card_driven(repo, decomposition_override):"),

    ("card-driven suppression removed",
     ACC,
     "if bad_input_floor and advanced_intake and not _is_card_driven(repo, decomposition_override):",
     "if bad_input_floor and advanced_intake:"),

    ("node exams get floored too",
     ACC,
     '    if _oracle_ecosystem(spec) != "python":\n        return oracle_code\n',
     ""),

    ("ruler imported at module scope (dormancy becomes a mere disabled boolean)",
     ACC,
     "import ast\nimport json",
     "import ast\nimport json\nimport shared.fleet.bad_input_floor  # noqa: F401"),

    ("fail-soft becomes fail-SILENT (the warning is dropped)",
     ACC,
     '        logger.warning(\n            "generate_plan: bad-input floor crashed',
     '        _ = (\n            "generate_plan: bad-input floor crashed'),

    ("per-slot round dropped (all-arguments-malformed only)",
     RULER,
     "    if slots > 1:\n        filler = {_EMIT_PREFIX}VALUES[-1]",
     "    if False:\n        filler = {_EMIT_PREFIX}VALUES[-1]"),

    ("stdlib is treated as first-party",
     RULER,
     "    return _default_is_first_party(top) and top not in _ORACLE_NON_API_ROOTS",
     "    return True"),

    ("idempotence marker check removed",
     RULER,
     "    if not oracle_code or BAD_INPUT_FLOOR_MARKER in oracle_code:",
     "    if not oracle_code:"),

    ("zero-arity entry points are driven anyway",
     RULER,
     "        if positional <= 0 and not keywords:\n            continue\n        if positional > _MAX_POSITIONAL:",
     "        if False and not keywords:\n            continue\n        if positional > _MAX_POSITIONAL:"),

    ("TypeError counted as an accidental crash",
     RULER,
     "    AttributeError, KeyError, IndexError, NameError, UnboundLocalError,",
     "    AttributeError, KeyError, IndexError, NameError, UnboundLocalError, TypeError,"),

    ("SystemExit no longer treated as handled",
     RULER,
     "            except SystemExit:\n                pass\n",
     ""),

    ("emitted result is no longer parse-checked",
     RULER,
     "    try:\n        ast.parse(floored)\n    except (SyntaxError, ValueError):\n        return oracle_code\n    return floored",
     "    return floored"),

    ("emitted block regains a non-ASCII character",
     RULER,
     "# --- bad-input coverage floor ({BAD_INPUT_FLOOR_MARKER}) - machine-injected",
     "# --- bad-input coverage floor ({BAD_INPUT_FLOOR_MARKER}) \u2014 machine-injected"),
]


#: BOTH suites. The first version ran only the ruler's own file, leaving the 11 AO
#: wiring/dormancy tests outside the loop entirely — a mutation harness that cannot see a
#: third of the locks reports a coverage figure it did not measure.
_SUITES = [
    "shared/tests/test_bad_input_floor.py",
    "services/assistant_orchestrator/tests/test_plan_handler.py",
]


def run() -> str:
    proc = subprocess.run(
        [PY, "-m", "pytest", *_SUITES, "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=str(ROOT), capture_output=True, text=True,
        env={**os.environ, "LOCALAPPDATA": str(_LOCALAPPDATA)},
    )
    out = proc.stdout + proc.stderr
    failed = sorted({ln.split("::")[1].split(" ")[0]
                     for ln in out.splitlines() if ln.startswith("FAILED ")})
    if proc.returncode == 0:
        return "GREEN  <-- mutation SURVIVED, no lock saw it"
    if failed:
        return "RED: " + ", ".join(failed)
    return f"RED (exit {proc.returncode}, no FAILED lines parsed)"


def _head_sha() -> str:
    proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(ROOT),
                          capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else "<no HEAD>"


def _print_anchor() -> None:
    """Name the SUBJECT of this run, at the top and again at the bottom.

    The poisoned-baseline guard cannot see this failure, and that is the whole point: a tree
    checked out at the WRONG COMMIT is perfectly clean relative to its own HEAD, so the guard
    stays silent, the run completes, and it prints "restore verified" — a fully healthy report
    measured against the wrong subject. Three verdicts were put at risk that way in one evening,
    including one where a stale tree was handed over as ready.

    So every figure this harness emits now carries its own subject. "0 of 29 survived" is a true
    sentence about an unnamed tree until the tree is named; naming it converts a stale-anchor
    error from something an operator has to REMEMBER into something the artifact SHOWS, and lets
    any number quoted into a journal or a review be re-anchored later without archaeology. Same
    move as counting ANCHOR MISSING as a survivor: turn vigilance into evidence.
    """
    print(f"mutation subject: {ROOT}")
    print(f"                  HEAD {_head_sha()}\n")


def _porcelain() -> str:
    return subprocess.run(["git", "status", "--porcelain"], cwd=str(ROOT),
                          capture_output=True, text=True).stdout.strip()


def _head_blob(path: pathlib.Path) -> "str | None":
    """The file's content AT HEAD, or None if git cannot produce it.

    Decoded as UTF-8 EXPLICITLY. ``text=True`` uses the locale encoding, which is cp1252 on
    this host, and these sources carry em-dashes: the reader thread then dies on a decode
    error, stdout comes back empty, and every file compares as different. The guard would have
    refused every run including clean ones -- looking exactly like a working guard while
    actually being a broken one, which is this slice's recurring joke at my expense.
    """
    rel = path.relative_to(ROOT).as_posix()
    proc = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=str(ROOT), capture_output=True)
    if proc.returncode != 0:
        return None
    return proc.stdout.decode("utf-8").replace("\r\n", "\n")


def _refuse_poisoned_baseline(paths) -> None:
    """Refuse to run when a MUTATED file already differs from HEAD.

    The hazard this closes (review O2): the harness reads its restore baseline from the
    WORKING TREE at start. If a previous run ever died mid-mutation and stranded broken source,
    the next run captures that mutation as its baseline, mutates on top of it, restores back to
    it, and prints "restore verified" - a poisoned baseline reporting success, which would then
    sit under every future "zero survived" figure.

    Scoped to the three files this harness writes, deliberately. Dirt ELSEWHERE in the tree is
    routine and blocking on it would be the cry-wolf check that gets ignored by the third run;
    dirt HERE is either a stranded mutation or deliberate uncommitted work, and the operator is
    the only one who can tell those apart. So it refuses and says how to proceed, rather than
    guessing. ``--allow-dirty`` is the deliberate override for testing uncommitted work, and it
    prints what it is accepting so the choice is on the record.
    """
    allow = "--allow-dirty" in sys.argv
    differing = [p for p in paths
                 if _head_blob(p) != p.read_text(encoding="utf-8").replace("\r\n", "\n")]
    if not differing:
        return
    listed = "\n".join(f"    {p.relative_to(ROOT).as_posix()}" for p in differing)
    if allow:
        print("--allow-dirty: mutating files that differ from HEAD (uncommitted work):")
        print(listed)
        print("  a stranded mutation from a dead run would look identical -- verify by eye.\n")
        return
    raise SystemExit(
        "REFUSED: these files already differ from HEAD before any mutation was applied:\n"
        f"{listed}\n"
        "That is either deliberate uncommitted work or source stranded by a run that died "
        "mid-mutation -- and a stranded one would silently become this run's restore baseline. "
        "Commit or check out the tree, or pass --allow-dirty if the difference is yours."
    )


def main() -> int:
    _print_anchor()
    _refuse_poisoned_baseline((ACC, RULER, QA))
    originals = {p: p.read_text(encoding="utf-8") for p in (ACC, RULER, QA)}
    # Compared against the state AT START, not against "clean". This tree is routinely dirty on
    # purpose (uncommitted work copied in to mutate), so requiring clean would cry wolf every
    # run and be ignored by the third — which is how a real failed restore gets through.
    before = _porcelain()
    survivors = 0
    try:
        for label, path, old, new in MUTATIONS:
            text = originals[path]
            if old not in text:
                print(f"!! ANCHOR MISSING for {label!r} -- mutation not applied")
                survivors += 1
                continue
            path.write_text(text.replace(old, new, 1), encoding="utf-8")
            verdict = run()
            print(f"- {label}\n    {verdict}")
            if verdict.startswith("GREEN"):
                survivors += 1
            path.write_text(text, encoding="utf-8")
    finally:
        for p, text in originals.items():
            p.write_text(text, encoding="utf-8")
        # Restoration is asserted, not assumed: a harness that silently leaves mutated source
        # behind is the same class of failure as a lock that silently passes.
        after = _porcelain()
        if after == before:
            print("\ntree after restore: UNCHANGED from start (restore verified)")
        else:
            print("\ntree after restore: CHANGED -- RESTORE FAILED, inspect before reusing")
            print(f"  before:\n{before or '    (clean)'}\n  after:\n{after or '    (clean)'}")
    # Repeated at the foot so a figure copied out of the tail of this output carries its
    # subject with it — the top banner scrolls away, the quoted line does not.
    print(f"\nsurvived (unguarded) mutations: {survivors}/{len(MUTATIONS)}"
          f"  [subject: {ROOT.name} @ {_head_sha()[:8]}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
