"""Job-config parsing for the dispatch sweep.

A sweep is a LIST of jobs; each job is one ``/dispatch <repo> | <goal>`` the harness runs to
completion (or stops fast if doomed). The config is plain JSON / a list of dicts — kept tiny and
declarative so the LA can hand-edit it:

    {
      "default_clarify_answer": "1",
      "jobs": [
        {"repo": "rocket-calc", "goal": "a space rocket calculator",
         "clarify_answer": "1", "expected": "MERGED"},
        {"repo": "todo-web", "goal": "a small todo web app", "clarify_answer": "web"}
      ]
    }

Either the top-level object form (above, with ``jobs`` + an optional ``default_clarify_answer``)
or a BARE list of job dicts is accepted. ``parse_jobs`` is pure (dict → ``list[JobSpec]``);
``load_jobs`` reads a JSON file and parses it. Every field except ``repo`` + ``goal`` is optional.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class JobSpec:
    """One dispatch job in the sweep.

    Attributes:
        repo: The target repo (a name under the projects dir, or an absolute path) — the
            ``<repo>`` half of ``/dispatch <repo> | <goal>``.
        goal: The free-text goal — the ``<goal>`` half.
        clarify_answer: The answer to a possible Inc-4 clarifying question, as the option
            NUMBER ("1") or the option LABEL/surface text ("on this computer" / "web"). Empty
            means "use the sweep default" (resolved by :func:`parse_jobs`).
        expected: An optional expected outcome (MERGED / PARKED / BLOCKED / NOTHING) used only
            to annotate the report with a met/unmet flag — it never changes what the harness does.
    """

    repo: str
    goal: str
    clarify_answer: str = ""
    expected: str = ""

    @property
    def command(self) -> str:
        """The exact ``/dispatch <repo> | <goal>`` string the gateway receives."""
        return f"/dispatch {self.repo} | {self.goal}"


def parse_jobs(data: Any, *, default_clarify_answer: str = "") -> list[JobSpec]:
    """Parse a sweep config (a dict with ``jobs`` OR a bare list) into ``list[JobSpec]``.

    ``default_clarify_answer`` is the fallback for a job that omits ``clarify_answer``; a
    top-level ``default_clarify_answer`` in *data* overrides the argument. Pure + total — raises
    ``ValueError`` with a clear message on a malformed config (never a bare KeyError/TypeError).
    """
    if isinstance(data, list):
        raw_jobs: Any = data
        default = default_clarify_answer
    elif isinstance(data, dict):
        raw_jobs = data.get("jobs", [])
        default = str(data.get("default_clarify_answer", default_clarify_answer) or "")
    else:
        raise ValueError(
            f"job config must be a list of jobs or an object with a 'jobs' list, "
            f"got {type(data).__name__}"
        )

    if not isinstance(raw_jobs, list):
        raise ValueError("'jobs' must be a list")

    jobs: list[JobSpec] = []
    for i, item in enumerate(raw_jobs):
        if not isinstance(item, dict):
            raise ValueError(f"job #{i + 1} must be an object, got {type(item).__name__}")
        repo = str(item.get("repo", "")).strip()
        goal = str(item.get("goal", "")).strip()
        if not repo or not goal:
            raise ValueError(f"job #{i + 1} needs both 'repo' and 'goal'")
        clarify = str(item.get("clarify_answer", "") or "").strip() or default
        expected = str(item.get("expected", "") or "").strip().upper()
        jobs.append(
            JobSpec(repo=repo, goal=goal, clarify_answer=clarify, expected=expected)
        )
    return jobs


def load_jobs(path: str | Path, *, default_clarify_answer: str = "") -> list[JobSpec]:
    """Read + parse a JSON sweep config file. Raises ``ValueError`` on a bad file/shape."""
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"could not read job config {p}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"job config {p} is not valid JSON: {exc}") from exc
    return parse_jobs(data, default_clarify_answer=default_clarify_answer)
