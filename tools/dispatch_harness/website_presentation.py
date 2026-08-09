"""A website battery run ENDS by leaving the operator something to open (#1343).

The coder fleet built a complete multi-page website on two consecutive nights and
**nobody opened either one**. B9 finished GREEN on 2026-08-07 — six tasks, fourteen
commits, thirty files — and the product sat in
``state/battery/night-*/repos-archived/battery-b9-pottery-web``: three levels inside a
state directory, behind an archive step, reachable only by someone who knows git. A
finished website nobody opens is not a website.

The review loop itself already exists and works (``agentic-setup/Review Website.cmd``,
built 2026-08-08). What was missing is the trigger: it had to be REMEMBERED. This module
is the trigger. At the end of a battery run it writes, per website card:

* a RECORD (``<out_dir>/website-review/<CARD>.website-review.json``) naming the run, the
  card, the sandbox, where the build will be after the archive step, and the run's own
  claims — **including what it SKIPPED and why**; and
* a LAUNCHER he can double-click, which calls the existing ``Review Website.cmd`` with
  this run's repo. One review implementation, not two.

THE SKIPPED LIST IS THE HALF THAT MATTERS
=========================================
His most valuable finding on 2026-08-08 came from a task that was silently skipped:
``create-piece-detail-page``, an explicit operator requirement, dropped by the
already-satisfied pre-check (#1049) and graded GREEN by four gates (#1342). A verdict
alone is not reviewable; the plan's own account of what it did NOT build is what makes
his eyes worth more than the instruments'.

WHY THE POINTER IS A NAME AND NOT A PATH
========================================
The archive runs at the START of the NEXT night, not the end of this one:
``run-battery-night.ps1`` renames ``~/projects/<repo>`` into the *new* night's
``repos-archived/`` as that night begins (FIELD_NOTES, 2026-07-30, #1180). So the path
this run could write down is correct for a few hours and wrong by tomorrow. The launcher
therefore names the REPO and lets ``review-website.ps1 -Name`` resolve it wherever it has
got to — a pointer that survives the move. The record carries both: the path OBSERVED at
write time, and the glob the build moves into.

FAIL-OPEN HERE IS CORRECT, AND THIS IS THE ONLY PLACE THAT IS TRUE
==================================================================
Everything else in this system fails CLOSED, because everything else is a lock: it grants,
gates or adjudicates, and an error path that proceeds hopefully is an unlocked door.
Presentation is not a lock. It grants nothing, gates nothing and adjudicates nothing — it
makes an ALREADY-COMPLETED result visible. Failing closed here would mean destroying a
night of GPU measurement because we could not write a shortcut to it, which trades the
expensive irreplaceable thing for the cheap retryable one: he can always run
``Review Website.cmd`` by hand and the sites are still on disk. So every path here is
caught, LOUDLY logged, and returns; nothing raises, and nothing this module does can move
a verdict, a scorecard field or an exit code.

THE READER LIVES HERE TOO (#1346)
=================================
Landing the launcher BESIDE ``MORNING-REPORT.md`` still asks him to notice a second file in
a directory, and the morning report is the only thing he reads. So the second half of this
module reads those records back and renders the report's own account of them. Reader and
writer share one file on purpose: they share a schema, a subdirectory and a launcher
filename, and a reader that re-spelled any of the three would drift from the writer the
first time either side changed.
"""

from __future__ import annotations

import json
import textwrap
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.dispatch_harness.scorecard import Scorecard

#: The record's own schema, versioned like every other machine-readable artifact here.
WEBSITE_REVIEW_SCHEMA = "battery-website-review/v1"

#: The card ``stack`` values that produce something a person can OPEN in a browser.
#: Branch on this, never on card ids — B3, B5 and B9 are today's web cards and the set
#: changes whenever a card is added, but the stack is what the card declares about its
#: own product. Compared after ``strip().lower()``, mirroring
#: :func:`~tools.dispatch_harness.battery.augment_goal_for_stack`'s normalisation of the
#: same field, so the two can never disagree about what "node-web" means.
WEB_STACKS: frozenset[str] = frozenset({"node-web"})

#: Where the per-run record + launcher land inside the battery's own output dir. A
#: subdirectory (not loose files) so the night's evidence dir stays legible and so a
#: byte-for-byte comparison of the run's OUTPUT can exclude presentation wholesale.
REVIEW_SUBDIR = "website-review"

#: The operator's double-click entry point, at the agentic-setup root (it lives there on
#: purpose — "a deliverable the operator has to go hunting for in a scripts folder is one
#: he will not use"). Generated launchers CALL this rather than re-implementing it.
REVIEW_LAUNCHER_NAME = "Review Website.cmd"

#: Longest single line of card/goal text copied into a launcher's ``echo``. A goal is a
#: paragraph; a console banner is not.
_MAX_ECHO_CHARS = 220

#: Longest skip reason kept in the record. Long enough for "already satisfied before wave
#: 2: the job acceptance oracle PASSED on the current tree" and its tail.
_MAX_DETAIL_CHARS = 400

# Batch ECHO metacharacters. `%` is handled separately (it doubles rather than carets).
_CMD_META = str.maketrans({c: "^" + c for c in "^&<>|()"})

#: Typography that reaches a launcher from run text, folded to ASCII. cmd.exe reads a
#: .cmd in the console's OEM codepage (cp850 here), NOT UTF-8, so a check mark out of a
#: node oracle's output or an em-dash out of a card title renders as mojibake in the one
#: window he actually looks at. Measured against the real B9 record, whose skip detail
#: carries U+2714. Named characters are TRANSLATED (the meaning survives); anything else
#: falls through to `?` — legible as "a character was here", never a broken line.
_ASCII_FOLD = str.maketrans({
    "—": "-", "–": "-", "‘": "'", "’": "'",
    "“": '"', "”": '"', "…": "...", "→": "->",
    "✔": "ok", "✓": "ok", "✗": "x", " ": " ",
})


# ---------------------------------------------------------------------------
# Pure predicates + text shaping (no I/O — driven directly by tests)
# ---------------------------------------------------------------------------


def is_website_card(card: Mapping[str, Any]) -> bool:
    """Does this card build something a person can open in a browser?

    Total and pure. A card with no ``stack``, a non-string ``stack``, or any stack
    outside :data:`WEB_STACKS` is not a website card — presentation is opt-IN by
    declared product shape, so a new non-web card can never acquire a launcher by
    accident."""
    try:
        stack = str(card.get("stack", "") or "").strip().lower()
    except AttributeError:  # not a mapping — not a card, and certainly not a website
        return False
    return stack in WEB_STACKS


def _echo(value: object) -> str:
    """*value* as one batch-safe ``echo`` line.

    Card text is operator-authored prose that reaches a ``.cmd`` file verbatim, so it is
    flattened (a newline would end the echo and run the remainder as commands) and every
    batch metacharacter is escaped. Not a security control — a battery card is trusted
    input — but a title containing ``&`` would otherwise produce a launcher that fails
    with a syntax error at exactly the moment he double-clicks it.

    ASCII by construction (see :data:`_ASCII_FOLD`). Paths are deliberately NOT folded —
    they go through :func:`_quoted` verbatim, because a mangled path breaks the ``call``
    while a mangled word only reads badly."""
    flat = " ".join(str(value).split())
    if len(flat) > _MAX_ECHO_CHARS:
        flat = flat[: _MAX_ECHO_CHARS - 3].rstrip() + "..."
    folded = flat.translate(_ASCII_FOLD).encode("ascii", "replace").decode("ascii")
    return folded.translate(_CMD_META).replace("%", "%%")


def _quoted(path: object) -> str:
    """A path for a QUOTED batch argument. Inside quotes the caret metacharacters are
    literal, so only ``%`` (still expanded) and embedded quotes need handling."""
    return str(path).replace('"', "").replace("%", "%%")


def _detail(value: object) -> str:
    """One skip/park reason, flattened and capped for the record."""
    flat = " ".join(str(value or "").split())
    return flat[: _MAX_DETAIL_CHARS - 3] + "..." if len(flat) > _MAX_DETAIL_CHARS else flat


# ---------------------------------------------------------------------------
# The run's own claims — the plan's account of itself, read from the driver record
# ---------------------------------------------------------------------------


def read_run_claims(runs_dir: "str | Path | None", run_id: str) -> dict[str, Any]:
    """The dispatch's own account of what it built, from
    ``<runs_dir>/<run_id>/scorecard.json``.

    Deliberately NOT a reuse of the battery's adoption reader: adoption decides a
    verdict and fails loudly on a malformed record, while this only quotes the plan back
    to the operator and an unreadable record must degrade to "unknown", never to a clean
    zero. A run with no record and a run that skipped nothing are different facts, and a
    report that renders them identically is the #1342 defect pointed at the reader
    instead of the exam.

    TWO flags, because there are two ways to know nothing. ``found`` says the driver's
    record was read at all; ``tasks_recorded`` says it carried a task list. A record that
    parses but has no ``tasks`` is the second case, and it is not rare — the dry-run fake
    emits exactly that shape, which is how this distinction was found: the first cut set
    ``found`` and then printed "0 merged, 0 SKIPPED, 0 planned" over a run that had never
    reported a single task.

    Never raises."""
    claims: dict[str, Any] = {
        "found": False, "tasks_recorded": False, "source": "", "goal": "", "verdict": "",
        "planned": 0, "merged": [], "skipped": [], "parked": [], "other": [],
    }
    if not runs_dir or not run_id:
        claims["why_not_found"] = "the run has no id, or the harness has no runs dir"
        return claims
    path = Path(runs_dir) / str(run_id) / "scorecard.json"
    claims["source"] = str(path)
    if not path.is_file():
        claims["why_not_found"] = "no driver scorecard was written for this run"
        return claims
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        claims["why_not_found"] = f"the driver scorecard could not be read ({exc})"
        return claims
    if not isinstance(raw, dict):
        claims["why_not_found"] = "the driver scorecard is not an object"
        return claims
    claims["found"] = True
    claims["goal"] = _detail(raw.get("goal", ""))
    claims["verdict"] = str(raw.get("verdict", "") or "")
    tasks = raw.get("tasks")
    if not isinstance(tasks, list):
        claims["why_no_tasks"] = "the driver scorecard records no list of tasks"
        return claims
    claims["tasks_recorded"] = True
    claims["planned"] = len(tasks)
    for task in tasks:
        if not isinstance(task, dict):
            continue
        status = str(task.get("status", "") or "unknown")
        row = {"id": str(task.get("id", "") or "(unnamed)"), "status": status,
               "detail": _detail(task.get("detail", ""))}
        # merged rows carry a boilerplate line; skipped/parked rows carry the REASON,
        # which is the only part of this record he cannot get by looking at the site.
        bucket = {"merged": "merged", "skipped": "skipped", "parked": "parked"}.get(status, "other")
        claims[bucket].append(row["id"] if bucket == "merged" else row)
    return claims


# ---------------------------------------------------------------------------
# The record + the launcher (pure builders — every path is an argument)
# ---------------------------------------------------------------------------


def build_record(
    card: Mapping[str, Any],
    sc: Scorecard | None,
    claims: Mapping[str, Any],
    *,
    sandbox: Path | None,
    archived_seen: Iterable[Path] = (),
    archive_glob: str = "",
    out_dir: Path,
    dry_run: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    """The durable record, as a plain dict. Pure — every fact is an argument, so the
    shape can be asserted without a filesystem.

    ``sandbox``/``archived_seen`` are kept apart on purpose: the first is where the build
    is RIGHT NOW and the second is what was actually seen under previous nights'
    archives. ``archive_glob`` is where it will BE, and it is a glob rather than a path
    because the stamp belongs to a night that has not run yet."""
    stamp = now or datetime.now(timezone.utc)
    return {
        "schema": WEBSITE_REVIEW_SCHEMA,
        "written_utc": stamp.astimezone(timezone.utc).isoformat(),
        "written_local": stamp.astimezone().isoformat(),
        # The same instant a person can read at a glance. The ISO form above stays the
        # machine's; a launcher banner that opens with six decimal places of a second is
        # a banner he skips, and the whole artifact exists to be read.
        "written_local_readable": stamp.astimezone().strftime("%a %d %b %Y, %H:%M local"),
        "dry_run": bool(dry_run),
        "card": {
            "id": str(card.get("id", "")),
            "title": str(card.get("title", "")),
            "stack": str(card.get("stack", "")),
            "repo": str(card.get("repo", "")),
            "goal": _detail(card.get("goal", "")),
        },
        "run": {
            "run_id": str(getattr(sc, "run_id", "") or ""),
            "verdict": str(getattr(sc, "verdict", "") or ""),
            "attribution": str(getattr(sc, "attribution", "") or ""),
            "battery_out_dir": str(out_dir),
        },
        "site": {
            "sandbox_now": str(sandbox) if sandbox is not None else "",
            "sandbox_now_exists": bool(sandbox is not None and sandbox.is_dir()),
            "archive_glob": archive_glob,
            "archived_copies_seen": [str(p) for p in archived_seen],
            "archive_note": (
                "The NEXT battery night renames this sandbox into ITS OWN night "
                "directory as it starts, so the archived copy is stamped with the night "
                "AFTER the one that built it. Review by NAME, not by path."
            ),
        },
        "claims": dict(claims),
        "review": {
            "how": (
                "Double-click the launcher beside this record, or run "
                f"'{REVIEW_LAUNCHER_NAME}' and pick the site by name."
            ),
            "repo_name": str(card.get("repo", "")),
        },
    }


def render_launcher(record: Mapping[str, Any], *, review_launcher: Path | None) -> str:
    """The double-click launcher's text, for the run *record* describes.

    IT NAMES THE RUN IT WAS WRITTEN FOR. A launcher sitting in a well-known place is
    stale the moment a later night runs without this card, and ``-Name`` resolves to the
    NEWEST build — so a shortcut that silently opened a different night's site while
    wearing this run's name would be the same partial-result-presented-as-whole defect
    the review loop exists to catch. The banner states the run id and the moment it was
    written; the operator can always tell which is which.

    ``review_launcher`` is checked at RUN time rather than baked in as a decision made
    at WRITE time — the tool may be installed, moved back, or repaired between the
    battery finishing at 03:00 and him double-clicking at 09:00."""
    card = record.get("card", {}) or {}
    run = record.get("run", {}) or {}
    claims = record.get("claims", {}) or {}
    site = record.get("site", {}) or {}
    skipped = list(claims.get("skipped") or [])
    merged = list(claims.get("merged") or [])
    repo = str(card.get("repo", ""))
    review_path = str(review_launcher) if review_launcher else ""
    verdict = str(run.get("verdict") or "unrecorded")
    if run.get("attribution"):
        verdict = f"{verdict} [{run.get('attribution')}]"

    run_label = _echo(run.get("run_id") or "with no run id recorded")
    written_at = _echo(record.get("written_local_readable") or record.get("written_local"))

    lines: list[str] = [
        "@echo off",
        f"REM Review the website battery run {run_label} built.",
        "REM",
        "REM GENERATED by the battery runner (tools/dispatch_harness/website_presentation.py,",
        "REM #1343) at the end of that run. Overwritten by the next run of the same card.",
        "REM It does not review anything itself -- it calls the one review tool with this",
        "REM run's site already chosen.",
        "",
        f"title Review the website - {_echo(card.get('id'))}",
        "",
        "echo.",
        f"echo   Card {_echo(card.get('id'))} - {_echo(card.get('title'))}",
        f"echo   Built by battery run {run_label}",
        f"echo   Written {written_at}",
        f"echo   The system's own verdict: {_echo(verdict)}",
        "echo.",
    ]
    if record.get("dry_run"):
        lines += [
            "echo   *** DRY RUN *** - this came from a rehearsal against a fake coder,",
            "echo   not a real build. Nothing here was made by the GPU.",
            "echo.",
        ]
    # tasks_recorded, NOT found: a record that parses but lists no tasks knows nothing
    # about what was skipped, and printing "0 SKIPPED" over it would manufacture the
    # reassurance this whole artifact exists to withhold.
    if claims.get("tasks_recorded"):
        lines.append(
            f"echo   Tasks: {len(merged)} merged, {len(skipped)} SKIPPED, "
            f"{_echo(claims.get('planned'))} planned in total"
        )
        if skipped:
            lines += [
                "echo.",
                "echo   THE SKIPPED ONES ARE WORTH YOUR ATTENTION - a page that was never",
                "echo   built is exactly what the automatic checks have missed before:",
            ]
            for row in skipped:
                lines.append(f"echo     - {_echo(row.get('id'))}: {_echo(row.get('detail'))}")
    else:
        lines.append(
            "echo   The run left no record of what it planned, so this shortcut CANNOT"
        )
        lines.append(
            "echo   tell you whether anything was skipped. Treat that as unknown, not none."
        )
    lines += [
        "echo.",
        f"echo   Where it is now: {_echo(site.get('sandbox_now') or 'unknown')}",
        f"echo   Full record:     {_echo(record.get('_record_path', '(beside this file)'))}",
        "echo.",
        f"echo   Opening the newest build named {_echo(repo)}.",
        "echo   If a later run has rebuilt it, that later one is what you will see.",
        "echo.",
        "",
    ]
    if review_path:
        lines += [
            f'if not exist "{_quoted(review_path)}" goto :missing',
            f'call "{_quoted(review_path)}" -Name "{_quoted(repo)}"',
            "goto :eof",
            "",
            ":missing",
            "echo   !! The review tool is not where this shortcut expects it:",
            f"echo   !!   {_echo(review_path)}",
            "echo   !! Nothing was opened. The site itself is untouched - the path above",
            "echo   !! says where it is.",
            "echo.",
            "pause",
        ]
    else:
        # The tool could not be located when this was written. Say so plainly rather
        # than emit a shortcut that fails with a batch error he cannot read.
        lines += [
            "echo   !! This run could not find the review tool "
            f"({_echo(REVIEW_LAUNCHER_NAME)}), so",
            "echo   !! there is nothing for this shortcut to open. The site itself is fine.",
            "echo.",
            "pause",
        ]
    return "\r\n".join(lines) + "\r\n"


# ---------------------------------------------------------------------------
# Path resolution — derived from the harness's own runs dir, never hardcoded
# ---------------------------------------------------------------------------


def resolve_agentic_root(runs_dir: "str | Path | None") -> Path | None:
    """The agentic-setup root implied by *runs_dir* (``<root>/state/fleet-runs``).

    Derived from the harness config rather than a constant so a test, a worktree or a
    relocated installation lands its artifacts in ITS OWN tree — the property that keeps
    a forgotten test from writing a shortcut into the operator's live state directory."""
    if not runs_dir:
        return None
    path = Path(runs_dir)
    return path.parent.parent if len(path.parts) >= 2 else None


def resolve_visible_dir(runs_dir: "str | Path | None") -> Path | None:
    """``<agentic-setup>/state/battery`` — where the night directories and
    ``MORNING-REPORT.md`` live, so the launcher sits beside the thing he reads in the
    morning rather than three levels down inside one night's evidence."""
    root = resolve_agentic_root(runs_dir)
    return None if root is None else root / "state" / "battery"


def resolve_review_launcher(runs_dir: "str | Path | None") -> Path | None:
    """``<agentic-setup>/Review Website.cmd``, or ``None`` when the root is unknown.
    EXISTENCE IS NOT CHECKED HERE — the launcher tests for it at double-click time, which
    is hours later and the only moment the answer matters."""
    root = resolve_agentic_root(runs_dir)
    return None if root is None else root / REVIEW_LAUNCHER_NAME


def find_archived_copies(runs_dir: "str | Path | None", repo: str) -> list[Path]:
    """Every archived copy of *repo* already on disk, newest night first. Observed, not
    predicted — the record keeps these apart from the glob for that reason. Never
    raises; an unreadable state dir yields ``[]`` and the record still carries the glob."""
    root = resolve_agentic_root(runs_dir)
    if root is None or not repo:
        return []
    try:
        found = sorted(
            (root / "state" / "battery").glob(f"night-*/repos-archived/{repo}"),
            key=lambda p: p.parent.parent.name,
            reverse=True,
        )
    except OSError:
        return []
    return [p for p in found if p.is_dir()]


def archive_glob_for(runs_dir: "str | Path | None", repo: str) -> str:
    root = resolve_agentic_root(runs_dir)
    if root is None or not repo:
        return ""
    return str(root / "state" / "battery" / "night-*" / "repos-archived" / repo)


# ---------------------------------------------------------------------------
# The presentation step itself — fail-soft over every artifact, never raises
# ---------------------------------------------------------------------------


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def present_website_builds(
    cards: Iterable[Mapping[str, Any]],
    scorecards: Mapping[str, Scorecard],
    *,
    out_dir: Path,
    runs_dir: "str | Path | None" = None,
    projects_dir: "str | Path | None" = None,
    dry_run: bool = False,
    log: Callable[[str], None] = print,
) -> list[Path]:
    """Leave the operator a record + a launcher for every website *cards* built.

    Returns the artifacts written (for logging and tests); an empty list is the normal
    outcome for a night with no web card in it. **Never raises, never touches a verdict,
    a scorecard field, a summary or an exit code** — it only READS the scorecards it is
    handed and WRITES under ``out_dir/website-review/`` plus, on a live run, one launcher
    into ``<agentic-setup>/state/battery``. (``run_battery`` still wraps the call in its
    own catch-all: this function's promise is the braces, that guard is the belt.)

    Each artifact is written under its OWN guard. A record that cannot be written must
    not also cost the launcher (which is the half he can act on), and a launcher that
    cannot be written must not cost the record (which is the half that survives). Sharing
    one try would let either failure erase the other artifact — the same
    one-instrument's-fault-erases-another's-reading shape :func:`_finalize_evidence`
    splits its three reads to avoid.

    ``dry_run`` suppresses the VISIBLE launcher only. The record and the launcher beside
    it still land in ``out_dir`` (a temp dir on a dry run), so ``--dry-run`` exercises
    this whole path — but a rehearsal against a fake coder must never drop a shortcut
    into his live state directory claiming a site exists."""
    written: list[Path] = []
    review_dir = out_dir / REVIEW_SUBDIR
    # Guarded like everything else below, so the "never raises" promise holds for the
    # WHOLE function rather than for its loop body. A resolution fault degrades to "no
    # visible launcher, no review path baked in" — the record still lands and the
    # launcher still says, at double-click time, that it could not find the tool.
    try:
        visible_dir = None if dry_run else resolve_visible_dir(runs_dir)
        review_launcher = resolve_review_launcher(runs_dir)
    except Exception as exc:  # noqa: BLE001 — see the module header: presentation is not a lock
        log("[battery] website review paths could not be resolved from "
            f"{runs_dir!r} (fail-soft): {type(exc).__name__}: {exc}")
        visible_dir, review_launcher = None, None

    for card in cards:
        if not is_website_card(card):
            continue
        cid = str(card.get("id", "") or "UNKNOWN")
        repo = str(card.get("repo", "") or "")
        try:
            sc = scorecards.get(cid)
            claims = read_run_claims(runs_dir, str(getattr(sc, "run_id", "") or ""))
            sandbox = (Path(projects_dir) / repo) if projects_dir and repo else None
            record = build_record(
                card, sc, claims,
                sandbox=sandbox,
                archived_seen=find_archived_copies(runs_dir, repo),
                archive_glob=archive_glob_for(runs_dir, repo),
                out_dir=out_dir, dry_run=dry_run,
            )
        except Exception as exc:  # noqa: BLE001 — module header: presentation is not a lock
            log(f"[battery {cid}] website review record could not be COMPOSED "
                f"(fail-soft, nothing else is affected): {type(exc).__name__}: {exc}")
            continue

        record_path = review_dir / f"{cid}.website-review.json"
        try:
            _write_text(record_path, json.dumps(record, indent=2, ensure_ascii=False) + "\n")
            written.append(record_path)
        except Exception as exc:  # noqa: BLE001
            log(f"[battery {cid}] website review record could not be WRITTEN to "
                f"{record_path} (fail-soft): {type(exc).__name__}: {exc}")

        # The launcher quotes the record's own path back at the operator, so the two
        # artifacts stay findable from each other even when one of them failed to land.
        launcher_name = launcher_name_for(cid)
        try:
            text = render_launcher({**record, "_record_path": str(record_path)},
                                   review_launcher=review_launcher)
        except Exception as exc:  # noqa: BLE001
            log(f"[battery {cid}] website review launcher could not be RENDERED "
                f"(fail-soft, the record still landed): {type(exc).__name__}: {exc}")
            continue
        # Visible copy FIRST when there is one, so the line below names the launcher he
        # is actually going to find rather than the one buried in the night's evidence.
        landed: list[Path] = []
        for target in ([] if visible_dir is None else [visible_dir / launcher_name]) + [
            review_dir / launcher_name
        ]:
            try:
                _write_text(target, text)
                written.append(target)
                landed.append(target)
            except Exception as exc:  # noqa: BLE001
                log(f"[battery {cid}] website review launcher could not be WRITTEN to "
                    f"{target} (fail-soft): {type(exc).__name__}: {exc}")

        # NAME A FILE THAT EXISTS. Pointing him at a launcher no write succeeded in
        # creating is the fail-soft step telling him the same comfortable half-truth the
        # whole ticket exists to remove — so when nothing landed, say that instead.
        if landed:
            log(f"[battery {cid}] website built — review it by double-clicking {landed[0]}"
                + (f" ({len(claims.get('skipped') or [])} task(s) SKIPPED — the record "
                   "says why)" if claims.get("skipped") else ""))
        else:
            log(f"[battery {cid}] website built, but NO review launcher could be written "
                f"(fail-soft) — review it by hand with '{REVIEW_LAUNCHER_NAME}'.")
    return written


# ---------------------------------------------------------------------------
# READING IT BACK — the morning report NAMES the site, not just the directory (#1346)
# ---------------------------------------------------------------------------


#: The suffix every per-card record carries inside :data:`REVIEW_SUBDIR`. Named because
#: the READER needs the other half of it: a record whose JSON will not parse can still be
#: NAMED from its filename, and being able to name a card whose facts are lost is the
#: whole difference between "built but unpresented" and silently absent.
RECORD_SUFFIX = ".website-review.json"

#: Night directories as ``run-battery-night.ps1`` stamps them (``night-<yyyyMMdd-HHmmss>``)
#: under ``<agentic-setup>/state/battery``. Lexicographic order is chronological order for
#: that stamp, which is what makes "the newest one" a sound answer to "which night just ran".
NIGHT_DIR_GLOB = "night-*"

#: Where under a night directory a record may sit — and NOTHING ELSE IS LOOKED AT.
#: ``run-battery-night.ps1`` passes ``--out <night>\scorecards``, so the records land one
#: level down; a caller that passes the night dir straight through as ``out_dir`` lands
#: them at the top. A night directory also holds ``repos-archived/<repo>`` — whole websites
#: with their dependency trees — so a recursive walk would spend minutes searching the one
#: place a record is never written.
_RECORD_GLOBS: tuple[str, ...] = (
    f"*/{REVIEW_SUBDIR}/*{RECORD_SUFFIX}",
    f"{REVIEW_SUBDIR}/*{RECORD_SUFFIX}",
)

#: Every scorecard verdict in the operator's own words. GREEN is the ONLY entry allowed to
#: use the word "clean", so the word's presence in a rendered section means exactly one
#: thing. An UNKNOWN verdict falls through to a named-but-ungraded phrasing and a MISSING
#: verdict to "not recorded" (see :func:`verdict_in_plain_words`) — reporting an absent
#: verdict as a pass would be #1342 committed by the reporter rather than the exam: a
#: clean-looking claim printed beside the instrument's own field saying it never graded.
_VERDICT_WORDS: dict[str, str] = {
    "GREEN": "**it graded this one clean** — every automatic check it ran passed",
    "PARKED-HONEST": "**not a pass** — the run stopped short of finished and said so",
    "FALSE-DONE": "**not a pass** — the run called itself done without the evidence for it",
    "STALLED": ("**not a pass** — the run could not be completed, so nothing it says about "
                "this site is a measurement"),
    "RECOVERED": "**not a pass** — the run broke part-way through and picked itself back up",
}

#: What a non-GREEN run blamed, in the operator's words. Printed as a tail on the verdict,
#: never as a verdict of its own.
_ATTRIBUTION_WORDS: dict[str, str] = {
    "PLAN": "the way the work was broken up",
    "BUILD": "the coder itself",
    "VERIFY": "the checks that were supposed to catch it",
    "HARNESS": "the machinery around the run rather than the work",
}


def launcher_name_for(card_id: str) -> str:
    """The double-click launcher's filename for *card_id*.

    One spelling, shared by the writer above and the reader below — the reader has to find
    by name exactly what the writer put there, and two copies of this format string would
    drift the first time either side changed."""
    return f"Review Website - {card_id}.cmd"


@dataclass(frozen=True)
class WebsiteBuilt:
    """One website card's night, reduced to what the morning report must state.

    Two fields carry the honesty. ``launcher`` is ``None`` when NOTHING was left that he
    can open — a site that exists and cannot be reviewed, which the report says out loud
    rather than omitting the card. ``unreadable`` carries the reason a record on disk could
    not be parsed: a card that ran and cannot be described is a different fact from a card
    that never ran, and rendering them identically is the defect this ticket exists to
    prevent."""

    card_id: str
    record_path: Path
    title: str = ""
    #: His own words for what he asked for. Preferred over ``title`` everywhere he reads.
    goal: str = ""
    finished: str = ""
    verdict: str = ""
    attribution: str = ""
    dry_run: bool = False
    launcher: Path | None = None
    #: A same-named launcher beside the morning report belonging to a DIFFERENT run.
    #: Only ever set when THIS run's visible copy failed to land, and named in the report
    #: so a leftover shortcut cannot pass for tonight's.
    stale_launcher: Path | None = None
    tasks_recorded: bool = False
    merged: int = 0
    skipped: int = 0
    planned: int = 0
    unreadable: str = ""


def _count(value: object) -> int:
    """``len`` of a list, and 0 for anything else. A malformed claims field must not
    become a confident count — a string of eleven characters is not eleven skipped tasks."""
    return len(value) if isinstance(value, (list, tuple)) else 0


def latest_night_dir(battery_dir: "str | Path | None") -> Path | None:
    """The night directory that just ran, under ``<agentic-setup>/state/battery``.

    The NEWEST one, and deliberately with no fallback to an older one. This is read from
    the postlude of the night that created it, so the newest IS this night; reaching back
    to yesterday when tonight has no records would report a site built last week as one
    built last night — a stale result wearing a fresh stamp, which is the exact shape the
    review loop exists to catch. Never raises: an unreadable directory yields ``None`` and
    the caller says so, rather than rendering an empty heading over a failed look."""
    if not battery_dir:
        return None
    try:
        nights = sorted(p for p in Path(battery_dir).glob(NIGHT_DIR_GLOB) if p.is_dir())
    except OSError:
        return None
    return nights[-1] if nights else None


def find_review_records(night_dir: "str | Path | None") -> list[Path]:
    """Every per-card record under *night_dir*, at most one per card, ordered by card id."""
    if not night_dir:
        return []
    found: dict[str, Path] = {}
    for pattern in _RECORD_GLOBS:
        try:
            matches = sorted(Path(night_dir).glob(pattern))
        except OSError:
            continue
        for path in matches:
            found.setdefault(path.name[: -len(RECORD_SUFFIX)], path)
    return [found[cid] for cid in sorted(found)]


def _read_record(path: Path) -> tuple[dict[str, Any], str]:
    """*path* parsed, or ``({}, reason)``. Never raises."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {}, f"{type(exc).__name__}: {exc}"
    if not isinstance(raw, dict):
        return {}, "the record is not an object"
    return raw, ""


def _launcher_names_this_record(text: str, record: Mapping[str, Any]) -> bool:
    """Was *text* written for THIS record?

    The visible launcher lives under a well-known name beside the morning report and is
    overwritten by the next run of the same card, so one left by an earlier night survives
    a night whose own launcher write failed. Matching on the record's written-at stamp —
    which :func:`render_launcher` echoes verbatim into the banner — is what stops that
    leftover being offered as tonight's. No stamp to match on reads as NOT PROVEN: the
    report would rather name the copy buried beside the record than point him at a
    shortcut it cannot vouch for."""
    stamp = _echo(record.get("written_local_readable") or record.get("written_local") or "")
    return bool(stamp) and stamp in text


def read_night_websites(
    night_dir: "str | Path | None", *, visible_dir: "str | Path | None" = None
) -> list[WebsiteBuilt]:
    """What the night left the operator to open, one entry per website card.

    An EMPTY LIST means no website card left a record, which the renderer turns into
    silence rather than an empty heading. Every other outcome comes back as an ENTRY —
    including a record nobody can parse and a card with no launcher anywhere, because a
    site that was built and cannot be reviewed is the fact this whole ticket exists to
    surface and omitting it is the failure it exists to prevent. Never raises."""
    visible = Path(visible_dir) if visible_dir else None
    builds: list[WebsiteBuilt] = []
    for path in find_review_records(night_dir):
        cid = path.name[: -len(RECORD_SUFFIX)]
        record, unreadable = _read_record(path)
        if unreadable:
            builds.append(WebsiteBuilt(card_id=cid, record_path=path, unreadable=unreadable))
            continue

        card = record.get("card") if isinstance(record.get("card"), dict) else {}
        run = record.get("run") if isinstance(record.get("run"), dict) else {}
        claims = record.get("claims") if isinstance(record.get("claims"), dict) else {}
        name = launcher_name_for(cid)

        launcher: Path | None = None
        stale: Path | None = None
        if visible is not None:
            candidate = visible / name
            try:
                text = candidate.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            if text and _launcher_names_this_record(text, record):
                launcher = candidate
            elif text:
                stale = candidate
        # The copy beside the record cannot be another run's: it lives inside THIS night's
        # own output directory, which is why it needs no stamp check to be trustworthy.
        if launcher is None and (path.parent / name).is_file():
            launcher = path.parent / name

        planned = claims.get("planned")
        builds.append(WebsiteBuilt(
            card_id=cid,
            record_path=path,
            title=str(card.get("title", "") or ""),
            goal=str(card.get("goal", "") or ""),
            finished=str(record.get("written_local_readable", "") or ""),
            verdict=str(run.get("verdict", "") or ""),
            attribution=str(run.get("attribution", "") or ""),
            dry_run=bool(record.get("dry_run")),
            launcher=launcher,
            stale_launcher=stale,
            tasks_recorded=bool(claims.get("tasks_recorded")),
            merged=_count(claims.get("merged")),
            skipped=_count(claims.get("skipped")),
            planned=planned if isinstance(planned, int) else 0,
        ))
    return builds


def verdict_in_plain_words(verdict: str, attribution: str = "") -> str:
    """*verdict* as one sentence a non-technical reader can act on.

    A record with NO verdict renders "not recorded" and never anything else. The record is
    written by a fail-soft step that runs whatever the night did, so an absent verdict is
    an ordinary outcome — and printing a pass over it would tell him the site was checked
    when the only honest statement available is that nobody wrote down whether it was."""
    graded = (verdict or "").strip()
    if not graded:
        return ("**not recorded** — this run wrote down no verdict at all, so nothing here "
                "says the site is either good or bad. Your own eyes are the only reading "
                "there is.")
    words = _VERDICT_WORDS.get(graded)
    if words is None:
        return (f"**{graded}** — this report does not know that word, so read it as neither "
                "a pass nor a failure until someone can say which it is.")
    blamed = _ATTRIBUTION_WORDS.get((attribution or "").strip())
    return words + (f", and it blamed {blamed}" if blamed else "")


#: Longest description of a card in this section. His goal is a PARAGRAPH -- B9's runs
#: past six hundred characters -- and the review tool already walks him through all of it,
#: clause by clause. Here it only has to let him recognise WHICH site this is.
_MAX_DESCRIPTION_CHARS = 160


#: Where this section's own lines wrap. He reads MORNING-REPORT.md as text, and a bullet
#: that runs to three hundred characters is one he scrolls past rather than reads.
_WRAP_COLUMNS = 88


def _para(text: str) -> list[str]:
    """One wrapped paragraph."""
    flat = " ".join(text.split())
    return textwrap.wrap(flat, width=_WRAP_COLUMNS, break_long_words=False,
                         break_on_hyphens=False) or [flat]


def _identifying_sentence(text: str) -> str:
    """Enough of *text* for him to recognise which site this is: its first sentence, and
    that trimmed at a word boundary if even it runs long. Never a mid-word cut — a
    description that stops halfway through a word reads as a fault rather than a summary."""
    flat = " ".join(str(text).split())
    head, sep, _rest = flat.partition(". ")
    first = head + ("." if sep else "")
    if len(first) <= _MAX_DESCRIPTION_CHARS:
        return first
    return first[:_MAX_DESCRIPTION_CHARS].rsplit(" ", 1)[0].rstrip(",;:— ") + "..."


def _bullet(text: str) -> list[str]:
    """One wrapped bullet, hanging-indented under its dash.

    Long words are never broken: the long words here are PATHS, and a path split across
    two lines is one he cannot paste — which is sometimes the only thing he wants from it.
    """
    flat = " ".join(text.split())
    return textwrap.wrap(
        flat, width=_WRAP_COLUMNS, initial_indent="- ", subsequent_indent="  ",
        break_long_words=False, break_on_hyphens=False,
    ) or [f"- {flat}"]


def _render_one(build: WebsiteBuilt) -> list[str]:
    """One card, as he reads it.

    HIS OWN WORDS NAME IT. The card's ``title`` is engineering shorthand — "pottery studio
    site (node-web, 9 units, MULTI-PAGE: shared layout + routing)" — while its ``goal`` is
    the sentence he actually wrote, which is also what the review tool hands back to him
    one clause at a time. A description he does not recognise is one more thing standing
    between him and opening the site, so the title is only ever the fallback.

    Bullets, because the facts below are independent: he should be able to stop reading at
    the one he came for."""
    out: list[str] = [f"**{build.card_id}**", ""]
    described = _identifying_sentence(build.goal or build.title)
    if described:
        out.extend(_para(f'*What you asked for: "{described}"*'))
        out.append("")
    if build.finished:
        out.append(f"*Finished {build.finished}.*")
        out.append("")
    if build.dry_run:
        out.extend(_bullet(
            "This was a REHEARSAL against a stand-in coder, not a real build. Nothing here "
            "was made by the graphics card."))

    if build.unreadable:
        # A card that ran and cannot be described. Named, never dropped -- the alternative
        # is a morning that looks exactly like a morning when nothing was built.
        out.extend(_bullet(
            "!! **It built this, but the note describing it cannot be read**, so this "
            "report cannot tell you what the run made of it or where the site ended up. "
            f"The note is at `{build.record_path}` and what is wrong with it is: "
            f"{build.unreadable}"))
        out.extend(_bullet(
            "None of that is a judgement about the site itself. `Review Website.cmd`, at "
            "the top of the coding folder, still lists every site on the machine."))
        out.append("")
        return out

    out.extend(_bullet(
        f"Its own verdict: {verdict_in_plain_words(build.verdict, build.attribution)}"))

    if build.launcher is not None:
        # The path gets a line to itself, unwrapped: it is the one thing on the page he
        # acts on rather than reads.
        out.append("- To look at it, double-click this file:")
        out.append(f"  `{build.launcher}`")
    else:
        out.extend(_bullet(
            "!! **The site was built, but nothing was left for you to open it with.** The "
            "site itself is on the machine and untouched — what failed is the step that "
            "prepares the shortcut, so this one is NOT ready for you to review. That is a "
            "fault in the machinery, not a verdict on the site."))
        out.extend(_bullet(
            f"What the run wrote about it is at `{build.record_path}`, and "
            "`Review Website.cmd`, at the top of the coding folder, opens any site on the "
            "machine by name."))

    if build.stale_launcher is not None:
        out.append("- !! Ignore this file sitting beside this report — it was written for")
        out.append("  an EARLIER run of the same card and would show you that one instead:")
        out.append(f"  `{build.stale_launcher}`")

    if build.tasks_recorded:
        planned = f"{build.planned} piece{'s' if build.planned != 1 else ''} of work it planned"
        if build.skipped:
            out.extend(_bullet(
                f"It finished {build.merged} of the {planned} and **skipped "
                f"{build.skipped}**. A page that was never built is exactly what the "
                "automatic checks have missed before, so the skipped one is worth more of "
                f"your attention than the rest; the note at `{build.record_path}` says "
                "which it was and why."))
        else:
            out.extend(_bullet(
                f"It finished {build.merged} of the {planned}, and left none out."))
    else:
        out.extend(_bullet(
            "The run left no list of what it set out to build, so nothing here can tell "
            "you whether anything was left out. Treat that as unknown, not as none."))
    out.append("")
    return out


def render_morning_website_section(builds: Sequence[WebsiteBuilt]) -> str:
    """The morning report's website section, or ``""`` when there is nothing to say.

    THE EMPTY CASE RENDERS NOTHING AT ALL, heading included. A heading with nothing under
    it reads as "we looked and there were none" — but the truth behind an empty section
    may be that the step never ran, and those are different facts. Silence commits to
    neither; the caller states the fault LOUDLY when it is the looking that failed."""
    if not builds:
        return ""
    out: list[str] = [
        f"## The website{'s' if len(builds) != 1 else ''} it built for you",
        "",
        "Nothing here needs any technical knowledge. Double-click the file named under each",
        "one: it opens the site in your browser and then asks you, one question at a time,",
        'whether it does what you asked for. "I could not tell" is a real answer every time,',
        "and whatever you say is kept against the run.",
        "",
    ]
    for build in builds:
        out.extend(_render_one(build))
    return "\n".join(out)
