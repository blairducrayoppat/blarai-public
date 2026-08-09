"""Where the Assistant Orchestrator is BOOTED from — as opposed to where the
measuring code was LOADED from.

Two different roots have always been spelled the same way in this package::

    Path(__file__).resolve().parents[2]

*HARNESS root* — the checkout this measuring code came out of. It owns the exam
cards (``evals/battery/B*.json``), the grader, and the git provenance stamped into
every scorecard. It answers "which version of the measuring instrument ran?".

*RUNTIME root* — the checkout ``python -m launcher`` is spawned in. It owns the
model weights (``models/`` is gitignored, so it exists in exactly one checkout),
the per-boot mTLS certs the launcher mints under ``certs/``, and the instance lock
the teardown barrier reads. It answers "which installation was exercised?".

They were identical for as long as the battery ran out of the primary checkout, so
one constant served both and nothing forced the distinction. Pinning the battery to
a dedicated worktree (#1181) separates them: the harness must come from a named
commit on ``main``, while the AO must still boot from the one checkout that has the
weights. Collapsing them again in either direction breaks a night —
harness-root-for-everything boots an AO with no models, runtime-root-for-everything
re-introduces the unpinned measurement this exists to retire.

:data:`RUNTIME_ROOT_ENV` names the override. UNSET means "same tree as the harness",
which is exactly the historical behavior; a caller that wants them split must say so.
When it IS set it is validated and a bad value RAISES — falling back to the harness
root on a malformed override would silently restore the confound while reporting
success, which is the failure mode this whole change exists to remove.
"""

from __future__ import annotations

import os
from pathlib import Path

#: Environment variable naming the checkout the AO is booted from. Read at call
#: time (never cached at import) so a test can set it without reloading modules.
RUNTIME_ROOT_ENV = "BLARAI_BATTERY_RUNTIME_ROOT"

#: What every runtime root must contain. ``python -m launcher`` resolves the
#: ``launcher`` package from its cwd, so a root without this file cannot boot an AO
#: no matter what else is right about it.
_LAUNCHER_MARKER = Path("launcher") / "__main__.py"


class RuntimeRootError(RuntimeError):
    """The runtime-root override was set but unusable.

    Deliberately fatal. The alternative — warn and fall back to the harness root —
    would boot the AO from a worktree with no model weights, and report a normal
    night while doing it.
    """


def resolve_runtime_root(harness_root: Path) -> Path:
    """The checkout to boot ``python -m launcher`` in.

    Returns *harness_root* unchanged when :data:`RUNTIME_ROOT_ENV` is unset or empty
    — the default that keeps an unpinned battery behaving exactly as before.

    Raises:
        RuntimeRootError: the override is set but does not resolve to a directory
            containing ``launcher/__main__.py``.
    """
    raw = os.environ.get(RUNTIME_ROOT_ENV, "").strip()
    if not raw:
        return harness_root

    root = Path(raw).expanduser()
    try:
        root = root.resolve()
    except OSError as exc:  # pragma: no cover — unreachable on a sane filesystem
        raise RuntimeRootError(
            f"{RUNTIME_ROOT_ENV}={raw!r} could not be resolved to a real path: {exc}"
        ) from exc

    if not root.is_dir():
        raise RuntimeRootError(
            f"{RUNTIME_ROOT_ENV}={raw!r} is not a directory. It must name the BlarAI "
            "checkout the Assistant Orchestrator boots from — the one holding the "
            "gitignored model weights, not the pinned measurement worktree."
        )
    if not (root / _LAUNCHER_MARKER).is_file():
        raise RuntimeRootError(
            f"{RUNTIME_ROOT_ENV}={raw!r} has no {_LAUNCHER_MARKER.as_posix()}, so "
            "`python -m launcher` cannot boot there. Point it at a full BlarAI "
            "checkout."
        )
    return root
