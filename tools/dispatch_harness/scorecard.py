"""The per-job battery scorecard — dataclass + validation + read/write (M2 W9).

One scorecard per battery job (plan §9.4 scoring): the terminal **verdict**
(closed taxonomy), the failure **attribution** for every non-GREEN, the
measured facts (wall-clock, samples, packs, interventions), **evidence
pointers**, and a versions stamp. The schema contract is published at
``evals/battery/scorecard.schema.json``; this module is the runtime
implementation (stdlib-only — no jsonschema dependency).

STRUCTURAL ONLY (plan §10 S6): scorecards are destined for
``docs/performance/`` and community publication, so the ``evidence`` object
carries file *pointers* and short structured statuses — NEVER raw logs. The
no-newline/length caps below are the enforcement, and ``write_scorecard``
fails closed on an invalid card (an unpublishable artifact is never written
silently). Any actual publication additionally routes through the existing
scrub pipeline (``scripts/scrub_community_export.py``).
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

SCORECARD_SCHEMA = "battery-scorecard/v1"

# ---------------------------------------------------------------------------
# The closed verdict + attribution taxonomies (plan §9.4 — do not extend
# casually; every consumer treats these as exhaustive)
# ---------------------------------------------------------------------------

VERDICT_GREEN = "GREEN"                  # job oracle green, unattended
VERDICT_PARKED_HONEST = "PARKED-HONEST"  # refused with evidence — verification success
VERDICT_FALSE_DONE = "FALSE-DONE"        # reported done without oracle evidence — program-failing
VERDICT_STALLED = "STALLED"              # could not run / had to be killed / could not be scored
VERDICT_RECOVERED = "RECOVERED"          # crash path fired and recovery worked

VERDICTS: frozenset[str] = frozenset(
    {VERDICT_GREEN, VERDICT_PARKED_HONEST, VERDICT_FALSE_DONE, VERDICT_STALLED, VERDICT_RECOVERED}
)

ATTRIBUTION_PLAN = "PLAN"        # decomposition/graph at fault
ATTRIBUTION_BUILD = "BUILD"      # the coder could not produce it
ATTRIBUTION_VERIFY = "VERIFY"    # gates/oracle wrong, missing, or bypassed
ATTRIBUTION_HARNESS = "HARNESS"  # environment/runner/swap fault

ATTRIBUTIONS: frozenset[str] = frozenset(
    {ATTRIBUTION_PLAN, ATTRIBUTION_BUILD, ATTRIBUTION_VERIFY, ATTRIBUTION_HARNESS}
)

#: evidence["oracle_status"] vocabulary (the FALSE-DONE cross-check hook).
ORACLE_STATUSES: frozenset[str] = frozenset({"passed", "failed", "not-run", "unknown"})

# Structural caps (S6 teeth): pointers/statuses, never raw logs.
_MAX_NOTE_CHARS = 500
_MAX_EVIDENCE_VALUE_CHARS = 1000
_MAX_VERSION_VALUE_CHARS = 200
_HAS_NEWLINE = re.compile(r"[\r\n]")


@dataclass
class Scorecard:
    """One battery job's machine-readable outcome record."""

    job_id: str                       # battery card id (B1..B8)
    verdict: str                      # one of VERDICTS
    attribution: str = ""             # one of ATTRIBUTIONS for non-GREEN; "" for GREEN
    wall_clock_s: float = 0.0
    samples_consumed: int = -1        # best-of-N candidates consumed; -1 = not instrumented
    packs_consumed: int = -1          # context packs consumed; -1 = not instrumented
    interventions: int = 0            # human interventions mid-run (hard gate: total 0)
    run_id: str = ""
    plan_id: str = ""
    repo: str = ""
    card_path: str = ""               # the battery card this scores
    evidence: dict = field(default_factory=dict)   # POINTERS + short statuses only
    versions: dict = field(default_factory=dict)   # str -> str stamp (commit, python, runner)
    started_utc: str = ""
    finished_utc: str = ""
    dry_run: bool = False
    notes: str = ""                   # short structural note (<= 500 chars, one line)
    schema: str = SCORECARD_SCHEMA

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Scorecard":
        """Build from a dict, tolerating missing optional fields; unknown keys are
        IGNORED (forward compatibility), never round-tripped."""
        if not isinstance(d, dict):
            raise ValueError(f"scorecard must be an object, got {type(d).__name__}")
        return cls(
            job_id=str(d.get("job_id", "")),
            verdict=str(d.get("verdict", "")),
            attribution=str(d.get("attribution", "") or ""),
            wall_clock_s=float(d.get("wall_clock_s", 0.0) or 0.0),
            samples_consumed=int(d.get("samples_consumed", -1)),
            packs_consumed=int(d.get("packs_consumed", -1)),
            interventions=int(d.get("interventions", 0)),
            run_id=str(d.get("run_id", "") or ""),
            plan_id=str(d.get("plan_id", "") or ""),
            repo=str(d.get("repo", "") or ""),
            card_path=str(d.get("card_path", "") or ""),
            evidence=d.get("evidence") if isinstance(d.get("evidence"), dict) else {},
            versions=d.get("versions") if isinstance(d.get("versions"), dict) else {},
            started_utc=str(d.get("started_utc", "") or ""),
            finished_utc=str(d.get("finished_utc", "") or ""),
            dry_run=bool(d.get("dry_run", False)),
            notes=str(d.get("notes", "") or ""),
            schema=str(d.get("schema", "")),
        )


def _bad_string(value: object, cap: int) -> str | None:
    """Why *value* is not an acceptable structural string, or None if it is."""
    if not isinstance(value, str):
        return f"must be a string, got {type(value).__name__}"
    if len(value) > cap:
        return f"exceeds {cap} chars ({len(value)}) — pointers/statuses only, never raw logs"
    if _HAS_NEWLINE.search(value):
        return "contains a newline — raw log content is forbidden in a scorecard (S6)"
    return None


def validate(card: "Scorecard | dict") -> list[str]:
    """Return every structural problem with *card* ([] == valid). Pure; never raises
    on bad shapes — a malformed card is a list of reasons, not a crash."""
    try:
        sc = card if isinstance(card, Scorecard) else Scorecard.from_dict(card)
    except (ValueError, TypeError) as exc:
        return [f"unparseable scorecard: {exc}"]

    errors: list[str] = []
    if sc.schema != SCORECARD_SCHEMA:
        errors.append(f"schema must be '{SCORECARD_SCHEMA}', got '{sc.schema}'")
    if not sc.job_id:
        errors.append("job_id is required")
    if sc.verdict not in VERDICTS:
        errors.append(f"verdict '{sc.verdict}' not in {sorted(VERDICTS)}")
    # Attribution: REQUIRED for every non-GREEN (plan §9.4); forbidden for GREEN.
    if sc.verdict == VERDICT_GREEN:
        if sc.attribution:
            errors.append("GREEN carries no attribution (got '%s')" % sc.attribution)
    elif sc.verdict in VERDICTS:
        if sc.attribution not in ATTRIBUTIONS:
            errors.append(
                f"non-GREEN verdict '{sc.verdict}' requires attribution in "
                f"{sorted(ATTRIBUTIONS)}, got '{sc.attribution}'"
            )
    if sc.wall_clock_s < 0:
        errors.append("wall_clock_s must be >= 0")
    for name, val in (("samples_consumed", sc.samples_consumed),
                      ("packs_consumed", sc.packs_consumed)):
        if not isinstance(val, int) or val < -1:
            errors.append(f"{name} must be an int >= -1 (-1 = not instrumented)")
    if not isinstance(sc.interventions, int) or sc.interventions < 0:
        errors.append("interventions must be an int >= 0")
    note_problem = _bad_string(sc.notes, _MAX_NOTE_CHARS)
    if note_problem:
        errors.append(f"notes {note_problem}")
    # evidence: {str: str | [str, ...]} — pointers + short statuses, never raw logs.
    for key, value in (sc.evidence or {}).items():
        if not isinstance(key, str) or not key:
            errors.append("evidence keys must be non-empty strings")
            continue
        values = value if isinstance(value, list) else [value]
        if isinstance(value, list) and not value:
            continue
        for item in values:
            problem = _bad_string(item, _MAX_EVIDENCE_VALUE_CHARS)
            if problem:
                errors.append(f"evidence['{key}'] {problem}")
                break
    if "oracle_status" in (sc.evidence or {}):
        status = sc.evidence["oracle_status"]
        if status not in ORACLE_STATUSES:
            errors.append(
                f"evidence['oracle_status'] '{status}' not in {sorted(ORACLE_STATUSES)}"
            )
    for key, value in (sc.versions or {}).items():
        if not isinstance(key, str) or not key:
            errors.append("versions keys must be non-empty strings")
            continue
        problem = _bad_string(value, _MAX_VERSION_VALUE_CHARS)
        if problem:
            errors.append(f"versions['{key}'] {problem}")
    return errors


def write_scorecard(card: "Scorecard | dict", path: Path) -> None:
    """Validate then write (fail-closed: an invalid card raises ``ValueError`` and
    nothing is written — a broken scorecard must never land on disk silently)."""
    errors = validate(card)
    if errors:
        raise ValueError("refusing to write an invalid scorecard: " + "; ".join(errors))
    sc = card if isinstance(card, Scorecard) else Scorecard.from_dict(card)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sc.to_dict(), indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def read_scorecard(path: Path) -> Scorecard:
    """Read + validate a scorecard file. Raises ``ValueError`` (with every reason)
    on a malformed or invalid file — an uncomparable record is never a silent pass."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"could not read scorecard {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"scorecard {path} is not valid JSON: {exc}") from exc
    errors = validate(data)
    if errors:
        raise ValueError(f"scorecard {path} is invalid: " + "; ".join(errors))
    return Scorecard.from_dict(data)
