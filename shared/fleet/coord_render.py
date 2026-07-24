"""``/coord status`` rendering (#843, ADR-039 §2.7 / §2.12.13).

Turns a :class:`shared.fleet.work_state.WorkStateSnapshot` into the
human-readable report ``/coord status`` returns. Two disciplines specific to
this module:

* **TRI-STATE HONESTY IN DISPLAY.** Every substrate that read UNREACHABLE is
  rendered as an explicit, labelled line — never silently omitted, which
  would look identical to "nothing to report" (ADR-039 §2.12.6 applied to
  RENDERING, not just data).
* **INJECTION-SAFE RENDERING (ADR-039 §2.7 / §2.12.13).** Ticket-derived
  free text (titles, bucket names, label names) is UNTRUSTED input — a
  hostile or compromised ticket must not be able to forge a
  prompt-injection-shaped control-token sequence into the rendered report.
  Every free-text field is passed through :func:`neutralize_untrusted_text`
  before interpolation. This is the concrete, testable half of "ticket-title
  injection must not become chat injection": today ``/coord status``'s
  reply is persisted as an INFORMATIONAL turn (mirroring ``/dispatch
  status``), which the gateway's existing history filter already excludes
  from ever re-entering the model's context — but this module does not rely
  on that alone, because a rendered report may also be read directly by the
  operator, copy-pasted, or (per ADR-039 §2.14.7a, a later AO-prompt-wiring
  phase) routed through the AO's own grounded-context corridor, where
  forged control tokens WOULD matter. Neutralizing at render time is
  correct defense-in-depth regardless of which transport eventually carries
  this text.

  The delimiter shapes neutralized here mirror (BY VALUE, not by import)
  ``services/assistant_orchestrator/src/context_manager.py``'s Context
  Spotlighting delimiters — this module lives in ``shared/fleet/``, a
  different deployable surface than the AO's own process, so the two stay
  independent modules; :func:`neutralize_untrusted_text`'s regression test
  pins the values against drift.
"""

from __future__ import annotations

import re
from typing import Any

from shared.fleet import coord_lifecycle as cl
from shared.fleet import vikunja_bridge as vb
from shared.fleet import work_state as ws

#: A generic guard against ANY ``<|...|>``-shaped control token (up to 64
#: chars between the pipes) — broader than any specific named-delimiter
#: list, so a not-yet-invented spotlighting/datamark token name is still
#: caught. Mirrors (by value) the shapes
#: ``services/assistant_orchestrator/src/context_manager.py`` defines
#: (``CONTEXT_BEGIN``/``CONTEXT_END``/``SYSTEM_BEGIN``/``SYSTEM_END``, and
#: the ``<|DOC-XXXXXXXX|>`` per-load datamark) without importing that
#: module (a different deployable service).
_CONTROL_TOKEN_PATTERN = re.compile(r"<\|[^|>]{1,64}\|>")

#: The per-bucket task-title cap — a status DIGEST, not a full ticket dump;
#: keeps a large board's report bounded and readable.
_MAX_TASKS_SHOWN_PER_BUCKET = 5

#: The aging-outliers list cap on the rendered report.
_MAX_OUTLIERS_SHOWN = 3

#: The cross-project STALLS rollup cap — a status digest, not a full ticket dump.
_MAX_STALLS_SHOWN = 10


def neutralize_untrusted_text(text: "str | None") -> str:
    """Strip anything shaped like a prompt-injection control token from
    *text* before it is interpolated into a rendered report.

    Ticket titles/descriptions/label names are UNTRUSTED (ADR-039 §2.7): a
    hostile or compromised ticket must not be able to forge a Context
    Spotlighting delimiter or a datamark-lookalike token INTO the rendered
    ``/coord status`` text. Every match of the generic control-token shape
    is replaced with a single space. Never raises — ``None``/non-str input
    coerces to an empty string rather than erroring a whole report over one
    malformed field."""
    if not text:
        return ""
    return _CONTROL_TOKEN_PATTERN.sub(" ", str(text))


def _fmt_duration(seconds: "float | None") -> str:
    if seconds is None:
        return "n/a"
    if seconds < 3600:
        return f"{seconds / 60:.0f}m"
    if seconds < 86400:
        return f"{seconds / 3600:.1f}h"
    return f"{seconds / 86400:.1f}d"


def _render_labels(labels: dict) -> str:
    if not labels:
        return ""
    parts = [
        f"{neutralize_untrusted_text(name)}×{count}" for name, count in labels.items()
    ]
    return " — labels: " + ", ".join(parts)


def render_project(pw: ws.ProjectWorkState) -> list[str]:
    """The report section for one Vikunja project — summary, board, flow."""
    lines = [f"### {neutralize_untrusted_text(pw.name)} (project {pw.project_id})"]

    if pw.summary.status == vb.ReadStatus.UNREACHABLE:
        lines.append(f"  UNREACHABLE — {neutralize_untrusted_text(pw.summary.error)}")
        return lines
    if pw.summary.status == vb.ReadStatus.EMPTY:
        lines.append("  no tasks yet")
        return lines

    summary = pw.summary.items[0]
    # #887: the operator's headline open-count covers REAL work; when synthetic
    # battery/test tickets are present, surface their count ALONGSIDE — never
    # folded into — the real count (``pw.flow.open_count`` is the partitioned
    # headline real-open, authoritative over the summary rollup's all-open).
    test_open = pw.test_flow.open_count if pw.test_flow is not None else 0
    if test_open > 0 and pw.flow is not None:
        open_desc = f"{pw.flow.open_count} open (real) + {test_open} test-class"
    else:
        open_desc = f"{summary['open']} open"
    lines.append(
        f"  {open_desc} / {summary['total']} total"
        + _render_labels(summary.get("labels", {}))
    )

    if pw.board.status == vb.ReadStatus.UNREACHABLE:
        lines.append(f"  board: UNREACHABLE — {neutralize_untrusted_text(pw.board.error)}")
    elif pw.board.status == vb.ReadStatus.EMPTY:
        lines.append("  board: no buckets (has the Kanban setup migration run?)")
    else:
        for bucket in pw.board.items:
            title = neutralize_untrusted_text(bucket.get("title", ""))
            tasks = bucket.get("tasks", [])
            lines.append(f"  [{title}] {len(tasks)} open")
            for t in tasks[:_MAX_TASKS_SHOWN_PER_BUCKET]:
                lines.append(f"    - {neutralize_untrusted_text(t.get('title', ''))}")
            if len(tasks) > _MAX_TASKS_SHOWN_PER_BUCKET:
                lines.append(f"    ... and {len(tasks) - _MAX_TASKS_SHOWN_PER_BUCKET} more")

    if pw.flow is not None and pw.flow.oldest_age_seconds is not None:
        lines.append(
            f"  flow: oldest open {_fmt_duration(pw.flow.oldest_age_seconds)}, "
            f"mean age {_fmt_duration(pw.flow.mean_age_seconds)}, "
            f"{pw.flow.throughput_count} done in the last window"
        )
        if pw.flow.aging_outliers:
            names = ", ".join(
                neutralize_untrusted_text(a.title)
                for a in pw.flow.aging_outliers[:_MAX_OUTLIERS_SHOWN]
            )
            lines.append(f"  aging outliers: {names}")

    # #887: the SYNTHETIC test class on its OWN line — surfaced (never hidden),
    # explicitly marked non-actionable and off the headline so the operator reads
    # the battery park for what it is, not as real unfinished business. The class
    # name is BlarAI's own constant, never attacker-influenced.
    if pw.test_flow is not None and pw.test_flow.open_count > 0:
        lines.append(
            f"  test-class ({cl.TEST_CLASS_LABEL} — non-actionable, off headline): "
            f"{pw.test_flow.open_count} open, "
            f"oldest {_fmt_duration(pw.test_flow.oldest_age_seconds)}, "
            f"mean age {_fmt_duration(pw.test_flow.mean_age_seconds)}"
        )

    return lines


def _render_campaign_value(value: Any) -> str:
    """A SAFE summary of the campaign JSON's shape — key names only, never
    raw values (which could be arbitrarily-shaped/attacker-influenced
    content in an operator-pointed file); neutralized regardless."""
    if isinstance(value, dict):
        keys = ", ".join(sorted(neutralize_untrusted_text(str(k)) for k in value.keys()))
        return keys or "(empty object)"
    return "data present"


def render_stalls(snapshot: ws.WorkStateSnapshot) -> list[str]:
    """The cross-project STALLS rollup — per-class aging outliers, deduped by the
    ONE seen-set (``flagged`` = already commented on its ticket; ``NEW`` = not yet).

    Aggregates every project's ``ProjectWorkState.stalls``, orders them most-urgent-
    class-then-oldest, and renders each injection-safe: the ticket title is
    UNTRUSTED (ADR-039 §2.7 / §2.12.13) and passes through
    :func:`neutralize_untrusted_text`; the class-of-service value is BlarAI's own
    enum, never attacker-influenced. Returns no lines when nothing is stalling."""
    stalls = [s for pw in snapshot.projects for s in pw.stalls]
    if not stalls:
        return []
    stalls.sort(key=lambda s: (s.service_class.pull_rank, -s.age_seconds, s.task_id))
    seen = snapshot.stall_seen_fingerprints
    lines = ["STALLS (class-of-service aging outliers):"]
    for s in stalls[:_MAX_STALLS_SHOWN]:
        flag = "flagged" if s.fingerprint in seen else "NEW"
        title = neutralize_untrusted_text(s.title)
        lines.append(
            f"  - [{s.service_class.value}] #{s.task_id} {title} "
            f"— {_fmt_duration(s.age_seconds)} ({flag})"
        )
    if len(stalls) > _MAX_STALLS_SHOWN:
        lines.append(f"  ... and {len(stalls) - _MAX_STALLS_SHOWN} more")
    return lines


def render_status(snapshot: ws.WorkStateSnapshot) -> str:
    """The full ``/coord status`` report for *snapshot*.

    Substrate UNREACHABLE conditions are surfaced FIRST and unconditionally
    — an operator must never have to infer "Vikunja is down" from an
    otherwise-normal-looking, quietly-incomplete report."""
    lines: list[str] = [f"Coordinator status as of {snapshot.computed_at}", ""]

    unreachable = [s for s in snapshot.substrate if s.status == vb.ReadStatus.UNREACHABLE]
    if unreachable:
        lines.append("SUBSTRATE UNREACHABLE:")
        for s in unreachable:
            lines.append(f"  - {s.name}: {neutralize_untrusted_text(s.error)}")
        lines.append("")

    if snapshot.swap.status == vb.ReadStatus.UNREACHABLE:
        lines.append(
            f"Fleet swap state: UNREACHABLE — {neutralize_untrusted_text(snapshot.swap.error)}"
        )
    elif snapshot.swap_in_flight and snapshot.swap.value is not None:
        swap = snapshot.swap.value
        lines.append(
            f"Fleet swap IN FLIGHT: run {neutralize_untrusted_text(swap.run_id)}, "
            f"phase {neutralize_untrusted_text(swap.phase)}"
        )
    else:
        lines.append("Fleet swap: idle (14B resident)")

    if snapshot.queue.status == vb.ReadStatus.UNREACHABLE:
        lines.append(
            f"Fleet queue: UNREACHABLE — {neutralize_untrusted_text(snapshot.queue.error)}"
        )
    elif snapshot.queue.status == vb.ReadStatus.EMPTY:
        lines.append("Fleet queue: empty")
    else:
        lines.append("Fleet queue: present")

    if snapshot.latest_run.status == vb.ReadStatus.UNREACHABLE:
        lines.append(
            f"Latest run: UNREACHABLE — {neutralize_untrusted_text(snapshot.latest_run.error)}"
        )
    elif snapshot.latest_run.status == vb.ReadStatus.EMPTY:
        lines.append("Latest run: none yet")
    elif snapshot.latest_run.value is not None:
        run_id, outcomes = snapshot.latest_run.value
        merged = sum(1 for o in outcomes if o.result == "MERGED")
        lines.append(
            f"Latest run {neutralize_untrusted_text(run_id)}: {merged}/{len(outcomes)} merged"
        )

    if snapshot.acp_progress.status == vb.ReadStatus.UNREACHABLE:
        lines.append(
            f"Coder run: progress UNREACHABLE — "
            f"{neutralize_untrusted_text(snapshot.acp_progress.error)}"
        )
    elif (
        snapshot.acp_progress.status == vb.ReadStatus.OK
        and snapshot.acp_progress.value is not None
    ):
        lines.append(
            f"Coder run: {neutralize_untrusted_text(snapshot.acp_progress.value.summary)}"
        )

    if snapshot.campaign.status == vb.ReadStatus.UNREACHABLE:
        lines.append(
            f"Battery campaign: UNREACHABLE — {neutralize_untrusted_text(snapshot.campaign.error)}"
        )
    elif snapshot.campaign.status == vb.ReadStatus.EMPTY:
        lines.append("Battery campaign: not configured / no data yet")
    else:
        lines.append(f"Battery campaign: {_render_campaign_value(snapshot.campaign.value)}")

    stall_lines = render_stalls(snapshot)
    if stall_lines:
        lines.append("")
        lines.extend(stall_lines)

    lines.append("")
    if not snapshot.projects:
        lines.append(
            "No coordinator projects configured "
            "([coordinator].projects — see the operator-run setup migration)."
        )
    else:
        for pw in snapshot.projects:
            lines.extend(render_project(pw))
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"
