"""Moving files inside the operator's own data directory (#1568).

The assistant's FIRST file surface, and the most dangerous tool in the set.
Every argument for it being useful is an argument for it being dangerous: the
argument is a PATTERN and the effect is a SET OF MOVES, which is why it always
rehearses, and why the rehearsal is worth more here than anywhere else.

WHAT THIS DOES AND DOES NOT DO
------------------------------
MOVES ONLY. No delete, no overwrite, no copy. Deleting files is a separate
capability decision and is deliberately absent rather than disabled -- there is
no code here that removes a file, so no flag can turn one on
(``security_by_design`` 4).

A DESTINATION COLLISION IS A REFUSAL. Not a rename, not an overwrite. Silent
renaming is how a move tool loses a file: the operator approves "23 files move
there", one already exists, and a tool that renames leaves him with a file whose
name he will never guess. Refusing costs him a second attempt; renaming costs
him the file.

THE THREAT MODEL IS PATH ESCAPE, AND THE CHECK RUNS FIRST
---------------------------------------------------------
Both the matched sources and the destination must resolve INSIDE the data
directory AFTER symlink resolution, or the whole request is refused before
anything moves (``security_by_design`` 7, validate before trust). The idiom is
the one ``document_loader`` already uses for ``/load`` -- ``resolve()`` then
``relative_to()`` -- reused rather than reinvented, because a second containment
check is a second thing to get wrong.

Resolution happens on the REAL path, so a symlink inside the directory pointing
outward is caught: it is the resolved target that must be contained, not the
link. A link is not followed into a move either -- only regular files move.

DETERMINISM, because a rehearsal is worthless without it. The plan is sorted by
source path, so the same pattern over the same directory yields the same plan in
the rehearsal and in the execution that follows. The file system can still
change underneath between the two, which is the sharpest case for #1541's rule,
and the caller is expected to compare plans rather than trust this module to
notice.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "USERDATA_MAX_MOVES",
    "Move",
    "MoveError",
    "apply_moves",
    "plan_moves",
    "resolve_within",
]

#: Refuse a plan larger than this rather than truncate it. A truncated move set
#: would move a different set than the one shown, and the part it kept would be
#: whichever paths sorted first.
USERDATA_MAX_MOVES: int = 200


class MoveError(RuntimeError):
    """A move request is refused. Raised, never returned, so no caller can read
    a refusal as a plan and proceed."""


@dataclass(frozen=True, slots=True)
class Move:
    """One file, and where it would go. Both already proven contained."""

    source: Path
    destination: Path


def resolve_within(root: Path, candidate: Path | str) -> Path:
    """Resolve ``candidate`` under ``root`` and prove it stayed inside.

    Raises:
        MoveError: If the resolved path is outside ``root``. That covers ``..``
            traversal, an absolute path pointing elsewhere, and a symlink whose
            TARGET is outside -- resolution happens before the comparison, so it
            is the real location that must be contained, not the name.
    """
    root_real = root.resolve()
    resolved = (root_real / candidate).resolve()
    try:
        resolved.relative_to(root_real)
    except ValueError:
        # The name, not its repr. This string reaches a non-technical
        # operator verbatim through the tool's return value, and
        # "WindowsPath('j/steal.txt')" is not something to show him
        # (finding 11).
        raise MoveError(
            f"refused: '{Path(candidate).as_posix()}' is outside your data "
            "folder"
        ) from None
    return resolved


def plan_moves(root: Path, pattern: str, destination: str) -> tuple[Move, ...]:
    """Compute the moves ``pattern`` would make into ``destination``.

    Touches nothing. Sorted by source, so the plan is reproducible.

    Raises:
        MoveError: On an empty pattern or destination, a path escape, a
            destination that is not a directory inside the data directory, a
            plan over :data:`USERDATA_MAX_MOVES`, or any collision -- whether
            with a file already present or between two sources in the same plan.
    """
    if not pattern.strip():
        raise MoveError(
            "refused: no pattern given. A move request that names nothing "
            "matches nothing, never everything."
        )
    if not destination.strip():
        raise MoveError("refused: no destination given")

    root_real = root.resolve()
    if not root_real.is_dir():
        raise MoveError("refused: the data directory does not exist")

    # The destination is checked BEFORE any matching, so a request aimed
    # outside is refused without the pattern ever being evaluated.
    dest_dir = resolve_within(root_real, destination)
    if not dest_dir.exists():
        # REFUSED rather than created (finding 9). `apply_moves` used to
        # mkdir(parents=True), which is a capability nobody declared: not in
        # the tool schema, not in the operator's capability text, not in the
        # config comment. A tool that says "moves only" does not build
        # directory trees, and a destination the operator has not made is more
        # likely a typo than an intention.
        raise MoveError(
            f"refused: destination {destination!r} does not exist. Create the "
            "folder first -- this moves files, it does not make folders."
        )
    if not dest_dir.is_dir():
        raise MoveError(
            f"refused: destination {destination!r} exists and is not a folder"
        )

    # A pattern is a glob, never a path. An absolute pattern, or one that climbs
    # out, is refused here rather than handed to glob() -- Path.glob raises on
    # some of those and silently accepts others, and "it depends" is not a
    # property worth having at a boundary.
    if Path(pattern).is_absolute() or ".." in Path(pattern).parts:
        raise MoveError(
            f"refused: pattern {pattern!r} must stay inside the data directory"
        )

    moves: list[Move] = []
    claimed: dict[Path, Path] = {}
    for match in sorted(root_real.glob(pattern)):
        # Only regular files move. A directory, a symlink, a socket -- anything
        # whose move means something other than "this file is now there" -- is
        # skipped rather than guessed at.
        if not match.is_file() or match.is_symlink():
            continue
        source = resolve_within(root_real, match.relative_to(root_real))
        if source.parent == dest_dir:
            continue  # already there; a no-op is not a move
        target = dest_dir / source.name
        if target.exists():
            raise MoveError(
                f"refused: {source.name!r} already exists in the destination. "
                "Nothing was moved -- renaming it would leave you a file you "
                "cannot find, so this refuses instead."
            )
        if target in claimed:
            raise MoveError(
                f"refused: {claimed[target].name!r} and {source.name!r} would "
                f"both become {target.name!r}. Nothing was moved."
            )
        claimed[target] = source
        moves.append(Move(source=source, destination=target))

    if len(moves) > USERDATA_MAX_MOVES:
        raise MoveError(
            f"refused: {len(moves)} files match, over the {USERDATA_MAX_MOVES} "
            "limit. Narrow the request."
        )
    return tuple(moves)


def apply_moves(moves: tuple[Move, ...], root: Path) -> int:
    """Perform exactly ``moves``; return how many moved.

    Takes the PLAN, never a pattern. A destructive execution that re-evaluated
    its own pattern could act on a different set than the one rehearsed and
    approved; taking the plan means the approved set and the moved set are the
    same object.

    **``root`` is re-verified here, not trusted from the plan.** This function
    used to check nothing, on the reasoning that :func:`plan_moves` had already
    proven containment -- so the entire threat model rested on ONE lock, which
    ``security_by_design`` 3 forbids, and it was breakable: an NTFS directory
    junction swapped over the destination between the plan and the approval
    sent files outside. A junction needs no privilege to create. Paths are
    re-resolved against ``root`` immediately before each move, so a reparse
    point introduced in that window is caught.

    Every failure is a :class:`MoveError`, INCLUDING an operating-system error.
    A bare ``OSError`` used to escape to a caller that catches only MoveError,
    which reported "Nothing was moved" to the operator after a file had already
    moved -- and the ordinary trigger is a matched file being open in another
    program. Each message states how many moved, because a half-finished set is
    recoverable only if the operator is told it happened.

    Raises:
        MoveError: On a path that no longer resolves inside ``root``, a
            collision appearing after the plan, a vanished source, or any
            operating-system failure during the move.
    """
    root_real = root.resolve()
    moved = 0
    for move in moves:
        try:
            for path in (move.source, move.destination):
                resolve_within(root_real, path)
        except MoveError as exc:
            raise MoveError(
                f"stopped after moving {moved} of {len(moves)}: {exc}. A folder "
                "changed underneath this move, so the rest were not moved."
            ) from None
        if not move.source.is_file():
            raise MoveError(
                f"stopped after moving {moved} of {len(moves)}: "
                f"'{move.source.name}' is no longer there. The rest were not "
                "moved."
            )
        if move.destination.exists():
            raise MoveError(
                f"stopped after moving {moved} of {len(moves)}: "
                f"'{move.destination.name}' appeared in the destination after "
                "the plan was made. The rest were not moved, and nothing was "
                "overwritten."
            )
        try:
            move.source.rename(move.destination)
        except OSError as exc:
            raise MoveError(
                f"stopped after moving {moved} of {len(moves)}: "
                f"'{move.source.name}' could not be moved ({exc.strerror or exc}). "
                "It may be open in another program. The rest were not moved."
            ) from None
        moved += 1
    return moved
